#!/usr/bin/env python3
"""Cut "sticky strand" triangles that overstretch during the shipped animations.

Meshy auto-skinning welds surfaces that should be separate (club to thigh, cape to
elbow, tusk to shoulder). At bind pose the weld is invisible; once the bones move
apart the shared triangles turn into long rubber bands that connect areas which
should not be connected. Weight repair cannot fix a triangle whose three corners
must genuinely follow different bones, so this module removes those triangles from
the index buffer ("scissors"), leaving vertices, skin, and inverse-bind matrices
untouched (bind validation only checks per-vertex rest positions).

Detection is purely geometric and evaluated on the exact poses that ship:

* Every frame of every ``gpu_clip_result`` payload is posed with the delivery
  rotation rule (``gpu_pose_local_rotation``: rest * axis-angle degrees) and skinned
  with CPU linear blend skinning (``roc_geometric_proxy._primitive_points``).
* A triangle is cut when, in any frame, its longest edge is at least
  ``stretch_ratio`` times its bind length **and** at least ``min_edge_fraction`` of
  the bind height (so a 1 mm sliver doubling in size is not a strand).
* Triangles whose corners share identical weights are rigid under rotation-only LBS
  and never reach the ratio.
* Stretch alone is not enough: skin between neighbouring bones (belly between spine and
  hips, wing root to body) stretches under an extreme pose too, and deleting it left holes
  at rest on toa_shahrokh / toa_orc_berserker (2026-09-02 stage audit). A triangle is a
  strand only when some pair of its corners is owned by bones more than
  ``max_bone_distance`` hops apart in the skeleton (hand to hip, club tip to shoulder).
  Stretched neighbour skin is kept and counted as ``stretchedButKeptNeighbourSkin``: that is
  a pose fault to fix upstream, not a mesh fault.

Fail-closed guard: if more than ``max_cut_fraction`` of triangles would be cut, the
rig is broken rather than strandy and the function raises instead of shipping a
shredded mesh.

Output: a GLB with the filtered index buffer plus a JSON report and an optional PNG
preview (posed mesh at the worst frame, cut triangles in red).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clip_character_pass import MOTION_ROOT_KEYS  # noqa: E402
from gpu_cascade_delivery import gpu_pose_local_rotation, require_pose_units_degrees  # noqa: E402
from roc_geometric_proxy import ProxyAsset, _primitive_points, _trs, load_asset  # noqa: E402
from sprite_body_surgery import load_glb, replace_triangle_indices, save_glb, skinned_triangle_faces  # noqa: E402

DEFAULT_STRETCH_RATIO = 2.5
DEFAULT_MIN_EDGE_FRACTION = 0.03
DEFAULT_MAX_CUT_FRACTION = 0.05
DEFAULT_MAX_BONE_DISTANCE = 2


def _pose_world_matrices(asset: ProxyAsset, pose: Mapping[str, Any]) -> np.ndarray:
    locals_: list[np.ndarray] = []
    for node in asset.nodes:
        entry = pose.get(node.name)
        if entry is None or node.name in MOTION_ROOT_KEYS:
            rotation = node.rotation
        else:
            delta = [float(entry.get("x", 0.0)), float(entry.get("y", 0.0)), float(entry.get("z", 0.0))]
            rotation = gpu_pose_local_rotation(node.rotation, delta)
        locals_.append(_trs(node.translation, rotation, node.scale))
    world: list[np.ndarray | None] = [None] * len(asset.nodes)

    def visit(index: int) -> np.ndarray:
        if world[index] is None:
            parent = asset.nodes[index].parent
            world[index] = locals_[index] if parent is None else visit(parent) @ locals_[index]
        return world[index]

    return np.stack([visit(i) for i in range(len(asset.nodes))])


def _skinned_primitive(asset: ProxyAsset):
    skinned = [p for p in asset.primitives if p.skin is not None and p.indices is not None]
    if len(skinned) != 1:
        raise ValueError(f"{asset.path}: expected exactly one skinned indexed primitive, found {len(skinned)}")
    return skinned[0]


def _edge_lengths(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    return np.stack([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1)], axis=1)


def _mixed_influence_faces(prim, faces: np.ndarray) -> np.ndarray:
    dominant = prim.joints[np.arange(len(prim.joints)), np.argmax(prim.weights, axis=1)]
    owners = dominant[faces]
    return ~((owners[:, 0] == owners[:, 1]) & (owners[:, 1] == owners[:, 2]))


def _joint_tree_distance(asset: ProxyAsset, skin) -> np.ndarray:
    """Hops between every pair of skin joints along the node hierarchy (parent/child = 1)."""
    def ancestors(node: int) -> list[int]:
        chain = [node]
        while asset.nodes[chain[-1]].parent is not None:
            chain.append(asset.nodes[chain[-1]].parent)
        return chain

    chains = [ancestors(int(node)) for node in skin.joints]
    count = len(skin.joints)
    dist = np.zeros((count, count), dtype=np.int64)
    for a in range(count):
        depth_a = {node: d for d, node in enumerate(chains[a])}
        for b in range(a + 1, count):
            for d_b, node in enumerate(chains[b]):
                if node in depth_a:
                    dist[a, b] = dist[b, a] = depth_a[node] + d_b
                    break
            else:
                dist[a, b] = dist[b, a] = count  # disjoint roots: never neighbours
    return dist


def _far_bone_faces(asset: ProxyAsset, prim, faces: np.ndarray, *, max_bone_distance: int) -> np.ndarray:
    """True where some pair of corners is owned by bones more than ``max_bone_distance`` hops apart.

    Skin between neighbouring bones (belly between spine and hips, wing root to body) is real
    surface that only stretches when the pose is extreme; cutting it leaves holes at rest. A
    strand joins bones that are not neighbours (hand to hip, club tip to shoulder).
    """
    skin = asset.skins[int(prim.skin)]
    dist = _joint_tree_distance(asset, skin)
    dominant = prim.joints[np.arange(len(prim.joints)), np.argmax(prim.weights, axis=1)]
    owners = dominant[faces]
    pair_max = np.maximum.reduce([
        dist[owners[:, 0], owners[:, 1]],
        dist[owners[:, 1], owners[:, 2]],
        dist[owners[:, 0], owners[:, 2]],
    ])
    return pair_max > int(max_bone_distance)


def find_stretched_triangles(
    mesh: Path,
    payloads: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    stretch_ratio: float = DEFAULT_STRETCH_RATIO,
    min_edge_fraction: float = DEFAULT_MIN_EDGE_FRACTION,
    max_bone_distance: int = DEFAULT_MAX_BONE_DISTANCE,
) -> dict[str, Any]:
    """Return per-triangle worst stretch over all frames plus the cut mask."""
    asset = load_asset(mesh)
    prim = _skinned_primitive(asset)
    faces = prim.indices.reshape(-1, 3).astype(np.int64)
    bind_worlds = _pose_world_matrices(asset, {})
    bind_points = _primitive_points(asset, prim, bind_worlds, 1)
    bind_height = float(bind_points[:, 1].max() - bind_points[:, 1].min())
    bind_edges = _edge_lengths(bind_points, faces)
    min_edge = min_edge_fraction * bind_height
    mixed = _mixed_influence_faces(prim, faces)
    far = _far_bone_faces(asset, prim, faces, max_bone_distance=max_bone_distance)

    worst_ratio = np.ones(len(faces))
    worst_edge = bind_edges.max(axis=1).copy()
    worst_frame: list[tuple[str, str] | None] = [None] * len(faces)
    frames_scored = 0
    for name, payload in payloads:
        require_pose_units_degrees(payload, source=f"clip_stretched_triangles[{name}]")
        for key in sorted(payload["poses"], key=lambda k: int(k)):
            pose = payload["poses"][key]
            worlds = _pose_world_matrices(asset, pose)
            points = _primitive_points(asset, prim, worlds, 1)
            edges = _edge_lengths(points, faces)
            ratio = edges.max(axis=1) / np.maximum(bind_edges.max(axis=1), 1e-9)
            better = ratio > worst_ratio
            worst_ratio = np.where(better, ratio, worst_ratio)
            worst_edge = np.where(better, edges.max(axis=1), worst_edge)
            for index in np.flatnonzero(better & (ratio >= stretch_ratio)):
                worst_frame[index] = (name, key)
            frames_scored += 1

    stretched = (worst_ratio >= stretch_ratio) & (worst_edge >= min_edge)
    # Stretch between neighbouring bones is skin under an extreme pose (a pose fault, kept and
    # reported); stretch between far-apart bones is a weld that should never have existed (cut).
    cut = stretched & far
    return {
        "asset": asset,
        "primitive": prim,
        "faces": faces,
        "cut": cut,
        "stretchedKept": stretched & ~far,
        "worstRatio": worst_ratio,
        "worstEdge": worst_edge,
        "worstFrame": worst_frame,
        "bindHeight": bind_height,
        "framesScored": frames_scored,
        "mixedInfluenceFaces": int(mixed.sum()),
        "farBoneFaces": int(far.sum()),
        "maxBoneDistance": int(max_bone_distance),
    }


def clip_stretched_triangles(
    mesh: Path,
    dest: Path,
    payloads: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    stretch_ratio: float = DEFAULT_STRETCH_RATIO,
    min_edge_fraction: float = DEFAULT_MIN_EDGE_FRACTION,
    max_cut_fraction: float = DEFAULT_MAX_CUT_FRACTION,
    max_bone_distance: int = DEFAULT_MAX_BONE_DISTANCE,
    preview_png: Path | None = None,
) -> dict[str, Any]:
    """Write ``dest`` = ``mesh`` minus strand triangles. Returns the report (also usable when nothing is cut)."""
    if not payloads:
        raise ValueError("clip_stretched_triangles needs at least one clip payload to evaluate")
    scan = find_stretched_triangles(
        mesh, payloads, stretch_ratio=stretch_ratio, min_edge_fraction=min_edge_fraction, max_bone_distance=max_bone_distance
    )
    faces: np.ndarray = scan["faces"]
    cut: np.ndarray = scan["cut"]
    fraction = float(cut.sum()) / max(1, len(faces))
    if fraction > max_cut_fraction:
        raise RuntimeError(
            f"{mesh.name}: {int(cut.sum())}/{len(faces)} triangles ({fraction:.1%}) exceed stretch ratio "
            f"{stretch_ratio}; above max_cut_fraction={max_cut_fraction:.1%}. This is a rig/skinning fault, not strands; do not ship."
        )

    doc, blob = load_glb(mesh)
    existing = skinned_triangle_faces(doc, blob)
    if existing.shape != faces.shape or not np.array_equal(existing, faces):
        raise RuntimeError(f"{mesh.name}: proxy loader and GLB index buffer disagree; refusing to rewrite indices")
    kept = faces[~cut]
    replace_triangle_indices(doc, blob, kept)
    save_glb(dest, doc, blob)

    cut_rows = [
        {
            "triangle": int(i),
            "stretchRatio": round(float(scan["worstRatio"][i]), 3),
            "posedEdge": round(float(scan["worstEdge"][i]), 4),
            "worstFrame": list(scan["worstFrame"][i]) if scan["worstFrame"][i] else None,
        }
        for i in np.flatnonzero(cut)
    ]
    cut_rows.sort(key=lambda r: -r["stretchRatio"])
    report = {
        "source": str(mesh),
        "dest": str(dest),
        "triangles": int(len(faces)),
        "cutTriangles": int(cut.sum()),
        "cutFraction": round(fraction, 5),
        "stretchedButKeptNeighbourSkin": int(scan["stretchedKept"].sum()),
        "maxBoneDistance": scan["maxBoneDistance"],
        "farBoneFaces": scan["farBoneFaces"],
        "mixedInfluenceFaces": scan["mixedInfluenceFaces"],
        "framesScored": scan["framesScored"],
        "clips": [name for name, _ in payloads],
        "stretchRatio": stretch_ratio,
        "minEdgeFraction": min_edge_fraction,
        "minEdge": round(min_edge_fraction * scan["bindHeight"], 4),
        "maxCutFraction": max_cut_fraction,
        "bindHeight": round(scan["bindHeight"], 4),
        "worstStretchRatio": round(float(scan["worstRatio"].max()), 3),
        "cut": cut_rows[:200],
        "proof": "generated-artifact: index-only removal; vertices/skin/IBM unchanged",
    }
    if preview_png is not None:
        report["preview"] = str(render_cut_preview(scan, payloads, preview_png))
    return report


def render_cut_preview(scan: Mapping[str, Any], payloads: Sequence[tuple[str, Mapping[str, Any]]], out_png: Path, *, size: int = 512) -> Path:
    """Orthographic front (+Z toward viewer) and side panels at the worst frame: kept triangles grey, cut triangles red."""
    from PIL import Image, ImageDraw

    asset: ProxyAsset = scan["asset"]
    prim = scan["primitive"]
    faces: np.ndarray = scan["faces"]
    cut: np.ndarray = scan["cut"]
    kept: np.ndarray = scan["stretchedKept"]
    cut_frames = [f for f, c in zip(scan["worstFrame"], cut | kept) if c and f]
    if cut_frames:
        name, key = max(cut_frames, key=lambda f: sum(1 for g in cut_frames if g == f))
        payload = dict(payloads)[name]
        pose = payload["poses"][key]
        title = f"{name} frame {key}"
    else:
        pose, title = {}, "bind (nothing cut)"
    points = _primitive_points(asset, prim, _pose_world_matrices(asset, pose), 1)
    lo, hi = points.min(axis=0), points.max(axis=0)
    extent = float((hi - lo).max()) * 1.1
    center = (lo + hi) / 2

    def panel(axes: tuple[int, int]) -> Image.Image:
        img = Image.new("RGB", (size, size), (18, 18, 22))
        draw = ImageDraw.Draw(img)
        xy = (points[:, axes] - center[list(axes)]) / extent
        px = np.stack([(xy[:, 0] + 0.5) * size, (0.5 - xy[:, 1]) * size], axis=1)
        depth = points[:, 3 - axes[0] - axes[1]]
        order = np.argsort(depth[faces].mean(axis=1))
        for f in order:
            if cut[f] or kept[f]:
                continue
            tri = [tuple(px[v]) for v in faces[f]]
            draw.polygon(tri, fill=(96, 96, 104), outline=(60, 60, 66))
        for f in order:
            if not (cut[f] or kept[f]):
                continue
            tri = [tuple(px[v]) for v in faces[f]]
            if cut[f]:
                draw.polygon(tri, fill=(230, 40, 40), outline=(255, 120, 120))
            else:
                draw.polygon(tri, fill=(235, 200, 40), outline=(255, 235, 140))
        return img

    front, side = panel((0, 1)), panel((2, 1))
    sheet = Image.new("RGB", (size * 2, size + 24), (18, 18, 22))
    sheet.paste(front, (0, 24))
    sheet.paste(side, (size, 24))
    ImageDraw.Draw(sheet).text(
        (8, 6),
        f"cut {int(cut.sum())}/{len(faces)} strand tris (red); {int(kept.sum())} stretched neighbour-skin tris kept (yellow) at {title}; left=front right=side",
        fill=(235, 235, 235),
    )
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--payload", type=Path, action="append", required=True, help="gpu_clip_result.json (repeatable)")
    parser.add_argument("--stretch-ratio", type=float, default=DEFAULT_STRETCH_RATIO)
    parser.add_argument("--min-edge-fraction", type=float, default=DEFAULT_MIN_EDGE_FRACTION)
    parser.add_argument("--max-cut-fraction", type=float, default=DEFAULT_MAX_CUT_FRACTION)
    parser.add_argument("--max-bone-distance", type=int, default=DEFAULT_MAX_BONE_DISTANCE)
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    payloads = [(str(p), json.loads(p.read_text(encoding="utf-8"))) for p in args.payload]
    if len({name for name, _ in payloads}) != len(payloads):
        raise ValueError("payload paths must be unique")
    report = clip_stretched_triangles(
        args.mesh, args.dest, payloads,
        stretch_ratio=args.stretch_ratio, min_edge_fraction=args.min_edge_fraction,
        max_cut_fraction=args.max_cut_fraction, max_bone_distance=args.max_bone_distance, preview_png=args.preview,
    )
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("triangles", "cutTriangles", "cutFraction", "worstStretchRatio", "framesScored", "dest")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
