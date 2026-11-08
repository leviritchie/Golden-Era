#!/usr/bin/env python3
"""Render an owned bind playing its reference animation.

Reads the exported ``owned_bind.glb`` back instead of the in-memory result, so the preview
shows the delivered artifact: the skeleton is reconstructed from the node graph and checked
against the fitted reference rest joints (a mismatch fails closed), then the reference joint
tracks drive it through the same replay the audit uses.

Two views per frame, sharing one deformation:

* the **plate view** - frame N's *own* authored DEF plate, cropped to the subject, with the
  driven mesh and its skeleton on top, so you can see the surface track the silhouette the
  audit measures it against;
* the **turn view** - the same deformed mesh from a fixed three-quarter angle, framed once on
  the rest mesh so the motion is visible as motion rather than as a refit.

Surfaces are drawn per pixel from the mesh's own baked 4096x4096 base-colour texture, with the
authored normals carried along by the driver's bone rotations (recomputing normals from the
deformed triangles would flatten every hard edge the mesh is authored with).  Shading a face with
a single colour read off the DEF plate is not a picture of this asset - the plate is a 39x77 px
sprite, so the whole body resolves to a few thousand texels and reads as blocky.

The preview refuses to render a claim it cannot back.  It reads the sibling
``owned_bind_report.json`` and fails closed unless that report names the same capture,
registration, mesh, bind frame, frame count and fitted scale this run just recomputed, so the
caption's audit state describes *this* artifact against *this* reference.  It also refuses a mesh
with no UVs or normals rather than inventing them, refuses a frame whose mesh rasterises to
nothing, and reports how far the surface actually moves between frames so a still clip is visible
as a still clip rather than passing as an animation.

    py -3 tools/homm3_meshy_frame_pose/preview_exact_reference_bind.py \\
      --run-dir "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf" \\
      --bind-glb "artifacts/homm3_owned_bind/h3_wood_elf/g00_move/owned_bind.glb" \\
      --out-dir "artifacts/homm3_owned_bind/h3_wood_elf/preview" --clip g00_move
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

SCALE_MATCH_TOL = 1e-6

from owned_rerig.exact_bind import (  # noqa: E402
    ExactBindParams,
    ReferenceInconsistentError,
    _dilate,
    bone_names_from_capture,
    driver_transforms,
    fit_reference_scale,
    replay_deformed_vertices,
)
from owned_rerig.glb_io import load_mesh, load_render_surface, read_glb  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402

BG_DIM = 0.45
PANEL_MARGIN = 0.06
SKELETON_RGB = np.array([255, 235, 60], dtype=np.float64)
JOINT_RGB = np.array([255, 90, 40], dtype=np.float64)
GUTTER = 6
CAPTION_H = 22


def render_view(
    *,
    indices: np.ndarray,
    deformed: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    texture: np.ndarray,
    right: np.ndarray,
    down: np.ndarray,
    k: float,
    off: np.ndarray,
    depth_dir: np.ndarray,
    light: np.ndarray,
    width: int,
    height: int,
    background: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """One textured, z-buffered view of the deformed surface, with its coverage mask."""
    if background is None:
        base = np.full((height, width, 3), 22.0, dtype=np.float64)
    else:
        base = background[:, :, :3] * BG_DIM
        mask = background[:, :, 3] > 0
        base[mask] = background[mask, :3] * 0.75
    screen = project(deformed, right, down, k, off)
    rgb, zbuf = rasterise(
        indices=indices,
        screen=screen,
        depth=deformed @ depth_dir,
        normals=normals,
        uvs=uvs,
        texture=texture,
        light=light,
        width=width,
        height=height,
    )
    if not np.isfinite(zbuf).any():
        raise SystemExit(
            "fail-closed: a view rasterised no mesh at all; the render would show nothing, so it "
            "must not be presented as a preview"
        )
    mask = np.isfinite(zbuf)
    base[mask] = rgb[mask]
    return base, mask


def draw_skeleton(
    canvas: np.ndarray,
    placed: np.ndarray,
    parents: list[int | None],
    right: np.ndarray,
    down: np.ndarray,
    k: float,
    off: np.ndarray,
    *,
    labels: list[str] | None = None,
) -> None:
    """Draw the driven joint track: the same joints the driver anchors every bone head on."""
    joint_px = project(placed, right, down, k, off)
    for slot, parent in enumerate(parents):
        if parent is not None:
            draw_line(canvas, joint_px[parent], joint_px[slot], SKELETON_RGB, radius=1)
    for slot in range(len(placed)):
        draw_dot(canvas, joint_px[slot], JOINT_RGB, radius=2)
    if labels:
        from PIL import Image, ImageDraw

        image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(image)
        for slot, name in enumerate(labels):
            draw.text((joint_px[slot][0] + 4, joint_px[slot][1] - 4), name, fill=(120, 255, 255))
        canvas[:] = np.asarray(image, dtype=np.float64)


def _resolve(value: str | None, default: Path | None) -> Path | None:
    if value is None:
        return default
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


# --------------------------------------------------------------------------- #
# read the delivered artifact back
# --------------------------------------------------------------------------- #


def load_delivered_skeleton(path: Path) -> dict[str, Any]:
    """Reconstruct joints, parents and heads from the exported GLB's own node graph."""
    mesh = load_mesh(path)
    if mesh.joints is None or mesh.weights is None:
        raise ValueError(f"{path}: the exported bind has no skin")
    doc = read_glb(path)["json"]
    skins = doc.get("skins") or []
    if not skins:
        raise ValueError(f"{path}: the exported bind has no skin entry")
    joint_nodes = [int(index) for index in skins[0]["joints"]]
    nodes = doc["nodes"]
    position_of_node = {node: slot for slot, node in enumerate(joint_nodes)}
    parent_of_slot: dict[int, int | None] = {slot: None for slot in range(len(joint_nodes))}
    for node_index, node in enumerate(nodes):
        if node_index not in position_of_node:
            continue
        child_slot = position_of_node[node_index]
        for child in node.get("children") or []:
            parent_of_slot[position_of_node[int(child)]] = child_slot
    children: dict[int, list[int]] = {slot: [] for slot in range(len(joint_nodes))}
    for slot, parent in parent_of_slot.items():
        if parent is not None:
            children[parent].append(slot)
    roots = [slot for slot, parent in parent_of_slot.items() if parent is None]
    if len(roots) != 1:
        raise ValueError(f"{path}: exported skeleton has {len(roots)} roots, expected 1")

    heads = np.zeros((len(joint_nodes), 3), dtype=np.float64)
    order: list[int] = []
    queue = [roots[0]]
    while queue:
        slot = queue.pop(0)
        order.append(slot)
        translation = np.asarray(
            nodes[joint_nodes[slot]].get("translation") or [0.0, 0.0, 0.0], dtype=np.float64
        )
        parent = parent_of_slot[slot]
        heads[slot] = translation if parent is None else heads[parent] + translation
        queue.extend(children[slot])
    if len(order) != len(joint_nodes):
        raise ValueError(f"{path}: exported skeleton is not a single connected tree")
    parents = [parent_of_slot[slot] for slot in range(len(joint_nodes))]
    names = [
        str(nodes[joint_nodes[slot]].get("name") or f"joint_{slot}")
        for slot in range(len(joint_nodes))
    ]
    return {
        "positions": mesh.positions,
        "indices": mesh.indices,
        "joints": mesh.joints,
        "weights": mesh.weights,
        "parents": parents,
        "heads": heads,
        "names": names,
        "order": order,
    }


def load_bind_evidence(
    report_path: Path,
    *,
    bind_glb: Path,
    capture: Path,
    registration: Path,
    mesh: Path,
    vertex_count: int,
    bind_frame: int,
    frame_count: int,
    fitted_scale: float,
) -> dict[str, Any]:
    """Read the audit report shipped with this bind and pin it to what we just recomputed.

    The caption states whether the artifact passed its audit, so that statement has to come from
    the artifact's own report - not from a clip name guessing which bones were refused.  Every
    shared input is compared, so a report written for another clip, mesh or reference cannot
    silently caption this render.
    """
    if not report_path.is_file():
        raise SystemExit(
            f"fail-closed: the bind audit report is missing: {report_path}; without it the preview "
            "cannot state whether the artifact it is drawing passed, and a caption guessed from "
            "the clip name is not evidence"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reference = report.get("reference") or {}
    scale_fit = report.get("scaleFit") or {}

    def canonical(value: Any) -> str | None:
        if value is None:
            return None
        return str(Path(str(value)).resolve()).replace("\\", "/").lower()

    checks = {
        "capture": (canonical(reference.get("capture")), canonical(capture)),
        "registration": (canonical(reference.get("registration")), canonical(registration)),
        "mesh": (canonical(reference.get("mesh")), canonical(mesh)),
        "bindFrame": (reference.get("bindFrame"), bind_frame),
        "frameCount": (reference.get("frameCount"), frame_count),
        "vertexCount": (report.get("vertexCount"), vertex_count),
    }
    mismatch = {
        key: {"report": pair[0], "preview": pair[1]}
        for key, pair in checks.items()
        if pair[0] != pair[1]
    }
    reported_scale = scale_fit.get("fittedScale")
    if reported_scale is None or abs(float(reported_scale) - fitted_scale) > SCALE_MATCH_TOL:
        mismatch["fittedScale"] = {"report": reported_scale, "preview": fitted_scale}
    if mismatch:
        raise SystemExit(
            f"fail-closed: {report_path} does not describe this bind ({json.dumps(mismatch)}); "
            "its verdict must not caption this render"
        )

    audit = report.get("audit") or {}
    ok = bool(report.get("auditOk"))
    if ok != bool(audit.get("ok")):
        raise SystemExit(f"fail-closed: {report_path} disagrees with itself on auditOk/audit.ok")
    return {
        "report": str(report_path.resolve()).replace("\\", "/"),
        "ok": ok,
        "issues": [str(issue) for issue in (audit.get("issues") or [])],
        "maxOutsideExcess": audit.get("maxOutsideExcess"),
        "outsideExcessBudget": audit.get("outsideExcessBudget"),
        "maxEscapedFraction": audit.get("maxEscapedFraction"),
        "containmentProof": audit.get("containmentProof"),
        "proof": report.get("proof"),
    }


def evidence_caption(evidence: dict[str, Any]) -> str:
    """One short line naming the audit verdict, with the refused bone when there is one."""
    if evidence["ok"]:
        budget = evidence["outsideExcessBudget"]
        excess = evidence["maxOutsideExcess"]
        detail = f"excess {excess:.2%} of budget {budget:.2%}" if None not in (excess, budget) else ""
        return f"audited-clean ({detail})" if detail else "audited-clean"
    first = evidence["issues"][0] if evidence["issues"] else "unstated"
    who = ""
    for token in first.split("unvalidated: ")[-1].split(","):
        token = token.strip()
        if token and not token[0].isdigit():
            who = token.split(" ")[0]
            break
    return f"refused-by-audit: {who or first[:60]}"


# --------------------------------------------------------------------------- #
# rasteriser
# --------------------------------------------------------------------------- #


def project(points: np.ndarray, right: np.ndarray, down: np.ndarray, scale: float, offset: np.ndarray) -> np.ndarray:
    return (points @ np.stack((right, down), axis=0).T) * scale + offset


def fit_camera(
    points: np.ndarray,
    *,
    right: np.ndarray,
    down: np.ndarray,
    width: int,
    height: int,
    margin: float = 0.10,
) -> tuple[float, np.ndarray]:
    xy = points @ np.stack((right, down), axis=0).T
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scale = (1.0 - 2.0 * margin) * min(width / span[0], height / span[1])
    offset = np.array([width * 0.5, height * 0.5]) - scale * xy.mean(axis=0)
    return float(scale), offset


def rasterise(
    *,
    indices: np.ndarray,
    screen: np.ndarray,
    depth: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    texture: np.ndarray,
    light: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """z-buffered rasteriser: per-pixel UV lookup of the mesh's own base-colour texture.

    Shading a face with one colour read off the DEF plate is not a picture of this asset - the
    plate is a 39x77 px sprite, so the whole body resolves to a few thousand texels and reads as
    blocky.  This interpolates UV and normal across each triangle and samples the real 4096x4096
    baked texture, so the preview shows the mesh as it is.
    """
    texture_height, texture_width = int(texture.shape[0]), int(texture.shape[1])
    colour = np.zeros((height, width, 3), dtype=np.float64)
    zbuf = np.full((height, width), np.inf, dtype=np.float64)
    triangles = indices.reshape(-1, 3)
    for triangle in triangles:
        x = screen[triangle, 0]
        y = screen[triangle, 1]
        x_lo = max(0, int(np.floor(x.min())))
        x_hi = min(width - 1, int(np.ceil(x.max())))
        y_lo = max(0, int(np.floor(y.min())))
        y_hi = min(height - 1, int(np.ceil(y.max())))
        if x_lo > x_hi or y_lo > y_hi:
            continue
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9:
            continue
        xs = np.arange(x_lo, x_hi + 1) + 0.5
        ys = np.arange(y_lo, y_hi + 1) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        w0 = ((x[1] - grid_x) * (y[2] - grid_y) - (x[2] - grid_x) * (y[1] - grid_y)) / area
        w1 = ((x[2] - grid_x) * (y[0] - grid_y) - (x[0] - grid_x) * (y[2] - grid_y)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        face_depth = w0 * depth[triangle[0]] + w1 * depth[triangle[1]] + w2 * depth[triangle[2]]
        window = zbuf[y_lo : y_hi + 1, x_lo : x_hi + 1]
        nearer = inside & (face_depth < window)
        if not nearer.any():
            continue

        # Interpolate the surface attributes only where this face actually wins the depth test.
        uv = np.stack(
            [
                w0 * uvs[triangle[0], 0] + w1 * uvs[triangle[1], 0] + w2 * uvs[triangle[2], 0],
                w0 * uvs[triangle[0], 1] + w1 * uvs[triangle[1], 1] + w2 * uvs[triangle[2], 1],
            ],
            axis=-1,
        )
        normal = (
            w0[..., None] * normals[triangle[0]]
            + w1[..., None] * normals[triangle[1]]
            + w2[..., None] * normals[triangle[2]]
        )
        normal = normal / np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-12)
        shade = 0.25 + 0.75 * np.abs(normal @ light)
        sampled = _sample_texture(uv, texture, texture_width, texture_height)
        lit = np.clip(sampled * shade[..., None], 0.0, 255.0)

        window[nearer] = face_depth[nearer]
        block = colour[y_lo : y_hi + 1, x_lo : x_hi + 1]
        block[nearer] = lit[nearer]
    return colour, zbuf


def _sample_texture(
    uv: np.ndarray, texture: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Bilinear lookup with glTF REPEAT wrapping; UV origin is the image's top-left."""
    u = np.mod(uv[..., 0], 1.0) * width - 0.5
    v = np.mod(uv[..., 1], 1.0) * height - 0.5
    x0 = np.floor(u)
    y0 = np.floor(v)
    fx = (u - x0)[..., None]
    fy = (v - y0)[..., None]
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1
    x0 %= width
    x1 %= width
    y0 %= height
    y1 %= height
    return (
        texture[y0, x0] * (1.0 - fx) * (1.0 - fy)
        + texture[y0, x1] * fx * (1.0 - fy)
        + texture[y1, x0] * (1.0 - fx) * fy
        + texture[y1, x1] * fx * fy
    ).astype(np.float64)


def draw_line(canvas: np.ndarray, p0: np.ndarray, p1: np.ndarray, rgb: np.ndarray, radius: int = 1) -> None:
    height, width = canvas.shape[:2]
    steps = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))) + 1
    for t in np.linspace(0.0, 1.0, min(steps, 4000)):
        x = int(round(p0[0] + (p1[0] - p0[0]) * t))
        y = int(round(p0[1] + (p1[1] - p0[1]) * t))
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < width and 0 <= yy < height:
                    canvas[yy, xx] = rgb


def draw_dot(canvas: np.ndarray, point: np.ndarray, rgb: np.ndarray, radius: int = 2) -> None:
    height, width = canvas.shape[:2]
    x, y = int(round(point[0])), int(round(point[1]))
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius + 1:
                continue
            xx, yy = x + dx, y + dy
            if 0 <= xx < width and 0 <= yy < height:
                canvas[yy, xx] = rgb


def draw_caption(canvas: np.ndarray, text: str) -> None:
    from PIL import Image, ImageDraw

    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    height, width = canvas.shape[:2]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate) > width - 10:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    block = CAPTION_H * len(lines)
    draw.rectangle([0, height - block, width, height], fill=(16, 16, 20))
    for row, line in enumerate(lines):
        draw.text((5, height - block + 5 + row * CAPTION_H), line, fill=(235, 235, 235))
    canvas[:] = np.asarray(image, dtype=np.float64)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--bind-glb", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--registration",
        type=Path,
        default=None,
        help=(
            "explicit accepted registration JSON; when omitted, retain the standard "
            "linked_master_remaining_scale/idle0_registration.json location"
        ),
    )
    parser.add_argument(
        "--mesh",
        type=Path,
        default=None,
        help="override the mesh named by the registration; must be the surface used to build the bind",
    )
    parser.add_argument("--clip", default=None)
    parser.add_argument("--segment", type=int, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument(
        "--bind-report",
        type=Path,
        default=None,
        help="audit report for --bind-glb (default: owned_bind_report.json beside it)",
    )
    parser.add_argument("--plate-height", type=int, default=400, help="plate view render height")
    parser.add_argument(
        "--scale-source",
        default="extent",
        choices=("extent", "registered"),
        help=(
            "must match the choice the bind was built with, or the preview would recompute a different "
            "scale and refuse the artifact; `registered` is the quadruped case"
        ),
    )
    parser.add_argument("--turn-yaw-deg", type=float, default=35.0)
    parser.add_argument("--labels", type=int, default=1, help="draw joint names")
    parser.add_argument(
        "--skeleton",
        type=int,
        default=1,
        help="draw the joint skeleton over the mesh (0 for a bare surface)",
    )
    parser.add_argument(
        "--plate",
        type=int,
        default=1,
        help=(
            "draw the left panel: the mesh over the authored DEF plate.  0 renders only the turned "
            "view of the mesh, which is what a comparison sheet wants; the plate panel is this "
            "tool's own evidence that the mesh lands on the art, not a presentation view"
        ),
    )
    parser.add_argument(
        "--caption",
        type=int,
        default=1,
        help=(
            "draw the per-frame audit caption; 0 leaves the frames clean for a comparison sheet.  The "
            "state is still read from the artifact's own report and still refuses to render without one - "
            "only its drawing is suppressed, so a clean sheet cannot become a flattering one"
        ),
    )
    args = parser.parse_args()

    run_dir = _resolve(str(args.run_dir), None)
    bind_glb = _resolve(str(args.bind_glb), None)
    out_dir = _resolve(str(args.out_dir), None)
    assert run_dir is not None and bind_glb is not None and out_dir is not None
    for label, path in (("run directory", run_dir), ("bind GLB", bind_glb)):
        if not path.exists():
            raise SystemExit(f"fail-closed: {label} missing: {path}")

    report_path = (
        _resolve(str(args.bind_report), None) if args.bind_report is not None else None
    ) or (bind_glb.parent / "owned_bind_report.json")
    capture_path = run_dir / "linked_master/capture/capture/raw_capture.npz"
    registration_path = (
        _resolve(str(args.registration), None)
        if args.registration is not None
        else run_dir / "linked_master_remaining_scale/idle0_registration.json"
    )
    if registration_path is None or not registration_path.is_file():
        raise SystemExit(
            "fail-closed: accepted registration missing; pass --registration for a route-local "
            f"registration or provide the standard path: {registration_path}"
        )
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    mesh_path = _resolve(
        str(args.mesh) if args.mesh is not None else str(registration["mesh"]), None
    )
    if mesh_path is None or not mesh_path.is_file():
        raise SystemExit(f"fail-closed: registration mesh missing: {mesh_path}")

    pose = load_registered_pose_source(
        capture=capture_path,
        registration=registration_path,
        master_sequence=run_dir / "linked_master/master_sequence/master_sequence.json",
        segment_index=args.segment,
        clip_key=args.clip,
        max_frames=args.max_frames,
    )
    delivered = load_delivered_skeleton(bind_glb)
    surface = load_render_surface(bind_glb)
    if len(surface["positions"]) != len(delivered["positions"]):
        raise SystemExit(
            f"fail-closed: {bind_glb} has {len(surface['positions'])} renderable vertices but "
            f"{len(delivered['positions'])} skinned ones; the preview would show the wrong surface"
        )
    if np.abs(surface["positions"] - delivered["positions"]).max() > 1e-6:
        raise SystemExit(
            f"fail-closed: {bind_glb} has inconsistent POSITION data between its render and skin "
            "views; nothing drawn from it would be faithful"
        )
    source = load_mesh(mesh_path)
    if len(delivered["positions"]) != len(source.positions):
        raise SystemExit(
            f"fail-closed: the bind GLB carries {len(delivered['positions'])} vertices but the "
            f"mesh has {len(source.positions)}; the preview would show the wrong surface"
        )

    params = ExactBindParams()
    params.scale_source = str(args.scale_source)
    fitted, scale_fit = fit_reference_scale(
        pose=pose, mesh_positions=source.positions, mesh_indices=source.indices, params=params
    )
    reference_rest = fitted.apply(pose.capture_positions[pose.bind_index()])
    rest_error = float(np.abs(delivered["heads"] - reference_rest).max())
    if rest_error > 1e-4:
        raise SystemExit(
            f"fail-closed: the exported skeleton does not reproduce the fitted reference rest pose "
            f"(worst {rest_error:.5f}); the artifact and the reference disagree, so nothing here "
            "would be a faithful preview"
        )
    evidence = load_bind_evidence(
        report_path,
        bind_glb=bind_glb,
        capture=capture_path,
        registration=registration_path,
        mesh=mesh_path,
        vertex_count=len(delivered["positions"]),
        bind_frame=pose.bind_index(),
        frame_count=pose.frame_count,
        fitted_scale=float(scale_fit["fittedScale"]),
    )
    print(
        json.dumps(
            {
                "clip": pose.frames[0].clip_key,
                "frames": pose.frame_count,
                "bones": len(delivered["names"]),
                "fittedScale": scale_fit["fittedScale"],
                "registeredScale": scale_fit["registeredScale"],
                "deliveredSkeletonRestError": rest_error,
                "audit": evidence,
            },
            indent=2,
        )
    )

    frame_joints = fitted.apply(pose.capture_positions[pose.capture_indices])
    vertices = source.positions
    triangles = np.asarray(source.indices, dtype=np.int64).reshape(-1, 3)
    uvs = surface["uvs"]
    texture = surface["baseColor"]
    rest_normals = surface["normals"]
    if rest_normals is None:
        raise SystemExit(
            f"fail-closed: {bind_glb} carries no NORMAL attribute, so a shaded preview would have "
            "to invent normals; re-export the bind so the authored normals travel with it"
        )
    from PIL import Image

    deformations = [
        replay_deformed_vertices(
            positions=vertices,
            heads=delivered["heads"],
            parents=delivered["parents"],
            joints=delivered["joints"],
            weights=delivered["weights"],
            frame_joints=frame_joints[index],
        )
        for index in range(pose.frame_count)
    ]

    # Plate panel: the registration's own camera, in its own 450x400 pixel coordinates, cropped
    # to the subject.  The crop is a pure orthographic crop, so the mesh still lands on exactly
    # the plate pixels the audit measured; it is only readable because the DEF subject is a
    # 39x77 px figure inside that canvas.
    #
    # The plate drawn behind frame N is frame N's *own* authored plate, because that is the
    # silhouette the audit holds frame N inside.  Drawing the bind plate behind every frame would
    # imply containment against art the frame was never measured against.
    cam = pose.camera
    native_h, native_w = (int(pose.alpha.shape[1]), int(pose.alpha.shape[2]))
    subject = cam.project(np.concatenate(deformations, axis=0))
    covered_rows, covered_cols = np.nonzero(pose.alpha.any(axis=0))
    content_x = np.concatenate((subject[:, 0], covered_cols.astype(float)))
    content_y = np.concatenate((subject[:, 1], covered_rows.astype(float)))
    crop_x0 = max(0.0, float(content_x.min()))
    crop_x1 = min(float(native_w), float(content_x.max()) + 1.0)
    crop_y0 = max(0.0, float(content_y.min()))
    crop_y1 = min(float(native_h), float(content_y.max()) + 1.0)
    panel_h = int(args.plate_height)
    margin = PANEL_MARGIN
    zoom = (panel_h * (1.0 - 2.0 * margin)) / max(crop_y1 - crop_y0, 1e-9)
    panel_w = int(round((crop_x1 - crop_x0) * zoom / (1.0 - 2.0 * margin)))
    slack = np.array(
        [
            max(0.0, (panel_w - (crop_x1 - crop_x0) * zoom) * 0.5),
            max(0.0, (panel_h - (crop_y1 - crop_y0) * zoom) * 0.5),
        ]
    )
    plate_right, plate_down = cam.right, cam.down
    plate_k = cam.px_per_world * zoom
    plate_off = (cam.offset_px - np.array([crop_x0, crop_y0])) * zoom + slack
    plate_depth_dir = cam.forward
    affine = (
        1.0 / zoom,
        0.0,
        crop_x0 - slack[0] / zoom,
        0.0,
        1.0 / zoom,
        crop_y0 - slack[1] / zoom,
    )
    plate_backgrounds = [
        np.asarray(
            Image.open(frame.source_png)
            .convert("RGBA")
            .transform((panel_w, panel_h), Image.AFFINE, affine, resample=Image.NEAREST),
            dtype=np.float64,
        )
        for frame in pose.frames
    ]

    # Turn view: fixed three-quarter camera, framed once on the rest mesh so motion reads as motion.
    yaw = math.radians(float(args.turn_yaw_deg))
    pitch = math.radians(12.0)
    turn_right = np.array([math.cos(yaw), 0.0, math.sin(yaw)])
    turn_down = np.array([-math.sin(pitch) * math.sin(yaw), -math.cos(pitch), math.sin(pitch) * math.cos(yaw)])
    turn_forward = np.cross(turn_right, turn_down)
    turn_forward /= max(float(np.linalg.norm(turn_forward)), 1e-12)
    turn_k, turn_off = fit_camera(vertices, right=turn_right, down=turn_down, width=panel_w, height=panel_h)

    light_turn = turn_forward * 0.7 + (-np.array([0.0, 1.0, 0.0])) * 0.5 + turn_right * 0.4
    light_turn /= np.linalg.norm(light_turn)
    light_plate = plate_depth_dir * 0.7 + (-np.array([0.0, 1.0, 0.0])) * 0.1 + plate_right * 0.6
    light_plate /= np.linalg.norm(light_plate)

    face_labels = pose.joint_names if (args.labels and args.skeleton) else None
    plate_alpha_dilated = [
        _dilate(background[:, :, 3] > 0, int(params.alpha_dilate_px)) for background in plate_backgrounds
    ]
    pixel_outside: list[float] = []

    def skinned_normals(frame_joints_for_frame: np.ndarray) -> np.ndarray:
        """Carry the authored normals with their bones instead of re-deriving them.

        Recomputing normals from the deformed triangles would flatten every hard edge the mesh is
        authored with - and on a 585-patch mesh there is nothing to average across a patch seam,
        so the surface would read as faceted rather than shaded.
        """
        rotations, _offsets = driver_transforms(
            heads=delivered["heads"], parents=delivered["parents"], frame_joints=frame_joints_for_frame
        )
        out = np.zeros_like(rest_normals)
        for slot in range(delivered["joints"].shape[1]):
            bone = delivered["joints"][:, slot]
            weight = delivered["weights"][:, slot]
            active = weight > 0.0
            if not np.any(active):
                continue
            out[active] += weight[active, None] * np.einsum(
                "nij,nj->ni", rotations[bone[active]], rest_normals[active]
            )
        length = np.linalg.norm(out, axis=1, keepdims=True)
        if float(length.min()) < 1e-9:
            raise SystemExit(
                "fail-closed: a skinned normal collapsed to nothing; the shaded preview would "
                "show an unlit surface"
            )
        return out / length

    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    sheets: list[np.ndarray] = []
    motions: list[float] = []
    coverages: list[float] = []
    state = evidence_caption(evidence)
    for index in range(pose.frame_count):
        deformed = deformations[index]
        normals = skinned_normals(frame_joints[index])
        right_panel, right_mask = render_view(
            indices=source.indices,
            deformed=deformed,
            normals=normals,
            uvs=uvs,
            texture=texture,
            right=turn_right,
            down=turn_down,
            k=turn_k,
            off=turn_off,
            depth_dir=turn_forward,
            light=light_turn,
            width=panel_w,
            height=panel_h,
        )
        coverages.append(float(right_mask.mean()))
        # The driver anchors every bone head on the reference joint track, so the drawn skeleton
        # is that track itself - not the delivered rest geometry swung onto it.
        if args.skeleton:
            draw_skeleton(
                right_panel, frame_joints[index], delivered["parents"], turn_right, turn_down,
                turn_k, turn_off, labels=face_labels,
            )
        if args.plate:
            left_panel, left_mask = render_view(
                indices=source.indices,
                deformed=deformed,
                normals=normals,
                uvs=uvs,
                texture=texture,
                right=plate_right,
                down=plate_down,
                k=plate_k,
                off=plate_off,
                depth_dir=plate_depth_dir,
                light=light_plate,
                width=panel_w,
                height=panel_h,
                background=plate_backgrounds[index],
            )
            coverages.append(float(left_mask.mean()))
            # The plate panel draws the mesh over the DEF art with the registration's own camera, so
            # their agreement is checkable in pixels.  This is not the audit's acceptance test (that
            # is exact point-to-triangle against the alpha); it is here to catch a broken crop or
            # offset, which would draw a plausible-looking mesh beside the art instead of on it.
            outside = left_mask & ~plate_alpha_dilated[index]
            painted = int(left_mask.sum())
            pixel_outside.append(float(outside.sum()) / painted if painted else 1.0)
            if args.skeleton:
                draw_skeleton(
                    left_panel, frame_joints[index], delivered["parents"], plate_right, plate_down,
                    plate_k, plate_off,
                )
            merged = np.concatenate(
                [left_panel, np.full((panel_h, GUTTER, 3), 16.0), right_panel], axis=1
            )
        else:
            merged = right_panel
        if index:
            moved = np.linalg.norm(deformed - deformations[index - 1], axis=1)
            motions.append(float(np.median(moved)))
        if args.caption:
            draw_caption(
                merged,
                f"{pose.frames[0].clip_key}  frame {index}/{pose.frame_count - 1}  "
                f"DEF {pose.frames[index].def_group} {pose.frames[index].role}  "
                f"left: plate camera cropped to subject  right: {args.turn_yaw_deg:.0f} deg turn  "
                f"{state}",
            )
        image = Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8))
        frames.append(image)
        sheets.append(np.asarray(image))

    clip_key = pose.frames[0].clip_key
    gif_path = out_dir / f"{clip_key}.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=83,
        loop=0,
        optimize=False,
    )
    columns = min(4, len(frames))
    rows = int(math.ceil(len(frames) / columns))
    sheet = np.zeros((rows * sheets[0].shape[0], columns * sheets[0].shape[1], 3), dtype=np.uint8)
    for position, panel in enumerate(sheets):
        row, col = divmod(position, columns)
        sheet[
            row * panel.shape[0] : (row + 1) * panel.shape[0],
            col * panel.shape[1] : (col + 1) * panel.shape[1],
        ] = panel
    sheet_path = out_dir / f"{clip_key}_sheet.png"
    Image.fromarray(sheet).save(sheet_path)
    motion = {
        "medianVertexMoveWorld": None if not motions else float(np.median(motions)),
        "worstFrameMedianMoveWorld": None if not motions else float(max(motions)),
        "stillFramePairs": sum(1 for value in motions if value <= 1e-9),
        "movingFramePairs": sum(1 for value in motions if value > 1e-9),
        "minPanelCoverage": float(min(coverages)),
    }
    travel = np.linalg.norm(frame_joints - delivered["heads"][None, :, :], axis=2)
    worst_frame, worst_joint = np.unravel_index(int(np.argmax(travel)), travel.shape)
    motion["jointTravelWorld"] = {
        "max": float(travel.max()),
        "joint": pose.joint_names[int(worst_joint)],
        "frame": int(worst_frame),
        "medianAcrossJointsWorld": float(np.median(travel)),
    }
    preview_check = {
        "panelWidth": panel_w,
        "panelHeight": panel_h,
        "plateCameraZoom": float(zoom),
        "maxOutsidePlateFraction": max(pixel_outside) if pixel_outside else None,
        "auditMaxOutsideExcess": evidence["maxOutsideExcess"],
        "note": (
            "rendered-pixel check that the drawn mesh sits on the drawn DEF alpha; a coarse "
            "screen-space companion to the audit's exact point-to-triangle test, not a "
            "replacement for it"
        ),
    }
    if pixel_outside and max(pixel_outside) > 0.5:
        preview_check["warning"] = (
            "the drawn mesh lands mostly off the drawn DEF art, so the plate panel is likely "
            "framed or offset wrongly"
        )
    if motions and max(motions) <= 1e-9:
        motion["warning"] = (
            "every frame pair is identical: this clip does not animate under the swing-only "
            "driver, which is a property of the reference, not a rendering fault"
        )
    print(
        json.dumps(
            {
                "gif": str(gif_path).replace("\\", "/"),
                "sheet": str(sheet_path).replace("\\", "/"),
                "motion": motion,
                "previewCheck": preview_check,
                "proof": evidence["proof"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
