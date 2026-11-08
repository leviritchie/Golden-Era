#!/usr/bin/env python3
"""Render one delivered unit at each pipeline stage so a mangled mesh can be blamed on a step.

Columns per clip row (same frame in every column, CPU LBS, orthographic front view):

1. ``unclipped + raw``      pre-baked GLB posed with the tracker/fused-push payload (what shipped before the tune-up)
2. ``unclipped + shaped``   same mesh, character-pass payload (isolates the character pass)
3. ``clipped + shaped``     scissored GLB, character-pass payload (isolates the strand cut)
4. ``clipped bind``         scissored GLB at rest (holes left by the cut show here as dark gaps)

Reads the unit folder written by ``run_stronghold_prebaked_install_overnight.py``
(``delivery_manifest.json``, ``character_payloads/``, ``*_prebaked.glb``, ``*_prebaked_clipped.glb``).
The frame shown per clip is the one with the largest stretch on the unclipped mesh under the shaped
payload, so the worst case is always on the sheet. Proof tier: generated-artifact preview only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clip_stretched_triangles import _edge_lengths, _pose_world_matrices, _skinned_primitive  # noqa: E402
from roc_geometric_proxy import _primitive_points, clear_asset_cache, load_asset  # noqa: E402


def posed_points(mesh: Path, pose: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    asset = load_asset(mesh)
    prim = _skinned_primitive(asset)
    return _primitive_points(asset, prim, _pose_world_matrices(asset, pose), 1), prim.indices.reshape(-1, 3).astype(np.int64)


def worst_frame(mesh: Path, payload: Mapping[str, Any]) -> str:
    bind, faces = posed_points(mesh, {})
    bind_edges = _edge_lengths(bind, faces).max(axis=1)
    best, best_key = -1.0, "0"
    for key in sorted(payload["poses"], key=lambda k: int(k)):
        pts, _ = posed_points(mesh, payload["poses"][key])
        ratio = float((_edge_lengths(pts, faces).max(axis=1) / np.maximum(bind_edges, 1e-9)).max())
        if ratio > best:
            best, best_key = ratio, key
    return best_key


def draw_panel(points: np.ndarray, faces: np.ndarray, *, size: int, frame: tuple[np.ndarray, float]) -> Image.Image:
    """Flat-lit front view (+Z toward viewer) with fixed framing so columns are comparable."""
    center, extent = frame
    img = Image.new("RGB", (size, size), (18, 18, 22))
    draw = ImageDraw.Draw(img)
    xy = (points[:, :2] - center[:2]) / extent
    px = np.stack([(xy[:, 0] + 0.5) * size, (0.5 - xy[:, 1]) * size], axis=1)
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    normals = np.cross(b - a, c - a)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    light = np.asarray([0.3, 0.6, 0.74])
    shade = np.clip(np.abs(normals @ light), 0.0, 1.0)
    order = np.argsort(points[faces].mean(axis=1)[:, 2])
    for f in order:
        v = int(90 + 140 * shade[f])
        draw.polygon([tuple(px[i]) for i in faces[f]], fill=(v, v, int(v * 0.95)))
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unit-dir", type=Path, required=True, help="artifacts/.../units/<sid>")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--size", type=int, default=320)
    parser.add_argument("--animations", default=None, help="Comma-separated subset of fit animations (default all).")
    args = parser.parse_args()
    wanted = set(args.animations.split(",")) if args.animations else None

    unit_dir = args.unit_dir
    manifest = json.loads((unit_dir / "delivery_manifest.json").read_text(encoding="utf-8"))
    sid = manifest["labSid"]
    clipped = Path(manifest["prebaked"]["glb"])
    unclipped = Path(manifest["prebaked"].get("scannedGlb") or manifest["prebaked"]["unclippedGlb"])
    per_anim = manifest["characterPass"]["perAnimation"]
    clear_asset_cache()

    rows: list[tuple[str, str, list[Image.Image]]] = []
    bind_pts, _ = posed_points(unclipped, {})
    lo, hi = bind_pts.min(axis=0), bind_pts.max(axis=0)
    frame = ((lo + hi) / 2, float((hi - lo).max()) * 1.6)
    for animation, info in sorted(per_anim.items()):
        if wanted is not None and animation not in wanted:
            continue
        shaped = json.loads((unit_dir / "character_payloads" / f"{animation}.gpu_clip_result.json").read_text(encoding="utf-8"))
        raw = json.loads(Path(info["source"]).read_text(encoding="utf-8"))
        key = worst_frame(unclipped, shaped)
        panels = []
        for mesh, pose in (
            (unclipped, raw["poses"][key]),
            (unclipped, shaped["poses"][key]),
            (clipped, shaped["poses"][key]),
            (clipped, {}),
        ):
            pts, faces = posed_points(mesh, pose)
            panels.append(draw_panel(pts, faces, size=args.size, frame=frame))
        rows.append((animation, key, panels))

    header = 26
    labels = ["unclipped + raw", "unclipped + shaped", "clipped + shaped", "clipped bind"]
    sheet = Image.new("RGB", (args.size * 4, header + len(rows) * (args.size + header)), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, label in enumerate(labels):
        d.text((i * args.size + 6, 6), label, fill=(235, 235, 235))
    y = header
    for animation, key, panels in rows:
        d.text((6, y + 4), f"{sid}  {animation}  frame {key}", fill=(255, 210, 120))
        for i, panel in enumerate(panels):
            sheet.paste(panel, (i * args.size, y + header))
        y += args.size + header
    out = args.out or (unit_dir / "stage_audit.png")
    sheet.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
