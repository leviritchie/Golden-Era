#!/usr/bin/env python3
"""Strip DEF baked shadows and crop town/dwelling map billboard PNGs to opaque content.

HoMM3 DEF extract maps palette slots 1/4/6/7 to semi-transparent black shadows.
Those left-side blobs displace the practical visual center of center-pivoted
adventure-map billboards. Opaque black building paint is preserved.

Multi-frame ``*.dir`` folders share one crop box (union of opaque bounds after
shadow strip) so flipbook frames stay aligned.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_OBJECT_ROOT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "map_object_refs"
)

# DEF shadow body/border after extract: near-black + partial alpha only.
SHADOW_ALPHA_MAX = 0x90
SHADOW_RGB_MAX = 8
OPAQUE_ALPHA_MIN = 200
EDGE_PAD_PX = 1


def is_town_or_dwelling_folder(name: str) -> bool:
    return name.endswith("_city") or name.endswith("_dwellings") or name == "homm3_neutral_dwellings"


def strip_def_shadow(rgba: np.ndarray) -> tuple[np.ndarray, int]:
    out = rgba.copy()
    rgb = out[:, :, :3].astype(np.int16)
    alpha = out[:, :, 3]
    maxc = rgb.max(axis=2)
    shadow = (alpha > 0) & (alpha <= SHADOW_ALPHA_MAX) & (maxc <= SHADOW_RGB_MAX)
    removed = int(shadow.sum())
    out[shadow] = (0, 0, 0, 0)
    return out, removed


def opaque_bbox(rgba: np.ndarray) -> tuple[int, int, int, int] | None:
    """Inclusive (x0, y0, x1, y1) over opaque-ish pixels, or None if empty."""
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha >= OPAQUE_ALPHA_MIN)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def union_bbox(
    a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int] | None
) -> tuple[int, int, int, int] | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def crop_with_pad(rgba: np.ndarray, box: tuple[int, int, int, int], pad: int) -> np.ndarray:
    """Crop to inclusive opaque box, then guarantee ``pad`` transparent pixels on every side."""
    x0, y0, x1, y1 = box
    content = rgba[y0 : y1 + 1, x0 : x1 + 1]
    ch, cw = content.shape[:2]
    out_h = ch + pad * 2
    out_w = cw + pad * 2
    out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    out[pad : pad + ch, pad : pad + cw] = content
    return out


def process_frame_group(pngs: list[Path], *, dry_run: bool) -> dict:
    """Strip+crop one frame group with a shared opaque crop box."""
    loaded: list[tuple[Path, np.ndarray, int]] = []
    shared: tuple[int, int, int, int] | None = None
    for path in pngs:
        rgba = np.array(Image.open(path).convert("RGBA"))
        stripped, removed = strip_def_shadow(rgba)
        shared = union_bbox(shared, opaque_bbox(stripped))
        loaded.append((path, stripped, removed))

    if shared is None:
        raise RuntimeError(
            "No opaque pixels after shadow strip in frame group: "
            + ", ".join(str(p) for p, _, _ in loaded)
        )

    rows = []
    for path, stripped, removed in loaded:
        cropped = crop_with_pad(stripped, shared, EDGE_PAD_PX)
        src_h, src_w = stripped.shape[:2]
        dst_h, dst_w = cropped.shape[:2]
        changed = removed > 0 or (dst_w, dst_h) != (src_w, src_h)
        if not dry_run and changed:
            Image.fromarray(cropped, "RGBA").save(path)
        rows.append(
            {
                "path": str(path),
                "shadowPixelsRemoved": removed,
                "sourceSize": [src_w, src_h],
                "croppedSize": [dst_w, dst_h],
                "cropBoxInclusive": list(shared),
                "changed": changed,
            }
        )
    return {
        "frameCount": len(rows),
        "sharedCropBoxInclusive": list(shared),
        "frames": rows,
    }


def iter_frame_groups(map_object_root: Path) -> list[list[Path]]:
    groups: list[list[Path]] = []
    for faction_dir in sorted(p for p in map_object_root.iterdir() if p.is_dir()):
        if not is_town_or_dwelling_folder(faction_dir.name):
            continue
        # Prefer *.dir groups; also accept loose PNGs directly under the faction folder.
        dir_groups = sorted(p for p in faction_dir.rglob("*.dir") if p.is_dir())
        seen_dirs = set()
        for frame_dir in dir_groups:
            pngs = sorted(frame_dir.glob("*.png"))
            if not pngs:
                continue
            groups.append(pngs)
            seen_dirs.add(frame_dir.resolve())
        loose = []
        for png in sorted(faction_dir.rglob("*.png")):
            if any(parent.resolve() in seen_dirs for parent in png.parents):
                continue
            loose.append(png)
        for png in loose:
            groups.append([png])
    return groups


def process_tree(map_object_root: Path, *, dry_run: bool) -> dict:
    if not map_object_root.is_dir():
        raise FileNotFoundError(f"map object root missing: {map_object_root}")
    groups = iter_frame_groups(map_object_root)
    results = []
    changed_frames = 0
    shadow_total = 0
    for group in groups:
        result = process_frame_group(group, dry_run=dry_run)
        results.append(result)
        for frame in result["frames"]:
            shadow_total += int(frame["shadowPixelsRemoved"])
            if frame["changed"]:
                changed_frames += 1
    return {
        "mapObjectRoot": str(map_object_root),
        "dryRun": dry_run,
        "groupCount": len(results),
        "changedFrames": changed_frames,
        "shadowPixelsRemovedTotal": shadow_total,
        "opaqueAlphaMin": OPAQUE_ALPHA_MIN,
        "shadowAlphaMax": SHADOW_ALPHA_MAX,
        "shadowRgbMax": SHADOW_RGB_MAX,
        "edgePadPx": EDGE_PAD_PX,
        "groups": results,
    }


def process_paths(paths: list[Path], *, dry_run: bool) -> dict:
    """Process explicit paths; group sibling PNGs under the same *.dir."""
    dir_keys: set[Path] = set()
    singles: list[Path] = []
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        parent = path.parent
        if parent.name.lower().endswith(".dir"):
            dir_keys.add(parent)
        else:
            singles.append(path)

    groups: list[list[Path]] = []
    for frame_dir in sorted(dir_keys):
        pngs = sorted(frame_dir.glob("*.png"))
        if pngs:
            groups.append(pngs)
    for path in singles:
        groups.append([path])

    results = []
    changed_frames = 0
    shadow_total = 0
    for group in groups:
        result = process_frame_group(group, dry_run=dry_run)
        results.append(result)
        for frame in result["frames"]:
            shadow_total += int(frame["shadowPixelsRemoved"])
            if frame["changed"]:
                changed_frames += 1
    return {
        "dryRun": dry_run,
        "groupCount": len(results),
        "changedFrames": changed_frames,
        "shadowPixelsRemovedTotal": shadow_total,
        "groups": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_MAP_OBJECT_ROOT,
        help="map_object_refs root (default: plugin runtime map_object_refs)",
    )
    parser.add_argument(
        "--path",
        action="append",
        type=Path,
        default=[],
        help="Optional explicit PNG or *.dir path (repeatable). Implies scoped mode.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report output path",
    )
    args = parser.parse_args()

    if args.path:
        expanded: list[Path] = []
        for path in args.path:
            if path.is_dir():
                expanded.extend(sorted(path.rglob("*.png")))
            else:
                expanded.append(path)
        report = process_paths(expanded, dry_run=args.dry_run)
    else:
        report = process_tree(args.root, dry_run=args.dry_run)

    text = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(
        f"groups={report['groupCount']} changedFrames={report['changedFrames']} "
        f"shadowPixelsRemovedTotal={report['shadowPixelsRemovedTotal']} dryRun={report['dryRun']}"
    )
    if args.report:
        print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — CLI fail-closed
        print(f"strip_crop_map_building_billboards failed: {exc}", file=sys.stderr)
        raise
