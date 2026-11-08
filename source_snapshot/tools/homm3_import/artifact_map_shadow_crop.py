"""Cull HoMM3 AVA soft shadows from artifact map frames and crop to subject.

Classic DEF special slots encode ground shadows as near-black pixels with partial
alpha (see tools/defextract.py). Those pixels inflate the 64x32 canvas and push
adventure-map billboards off-center once the texture aspect drives quad width.

Proof boundary: generated-asset postpass. Runtime visibility is separate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

# DEF shadow body/border alphas after special-slot convert (defextract / VCMI).
_NEAR_BLACK_MAX = 8
_SHADOW_ALPHA_MAX = 199  # keep fully opaque near-black subject pixels (e.g. metal)


def cull_def_shadow_pixels(image: Image.Image) -> Image.Image:
    """Zero alpha on near-black soft-shadow pixels; leave opaque subject intact."""
    rgba = image.convert("RGBA")
    pixels = list(rgba.getdata())
    out = []
    for r, g, b, a in pixels:
        if a > 0 and a <= _SHADOW_ALPHA_MAX and max(r, g, b) <= _NEAR_BLACK_MAX:
            out.append((0, 0, 0, 0))
        else:
            out.append((r, g, b, a))
    rgba.putdata(out)
    return rgba


def crop_to_opaque_subject(image: Image.Image, *, pad: int = 1) -> Image.Image:
    """Crop to non-transparent bounds with a small pad. Fail closed if empty."""
    rgba = image.convert("RGBA")
    bbox = rgba.getbbox()
    if bbox is None:
        raise ValueError("artifact map frame has no opaque subject after shadow cull")
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(rgba.width, right + pad)
    bottom = min(rgba.height, bottom + pad)
    return rgba.crop((left, top, right, bottom))


def postpass_artifact_map_frame(image: Image.Image, *, pad: int = 1) -> Image.Image:
    """Cull DEF soft shadows then crop to the remaining subject."""
    return crop_to_opaque_subject(cull_def_shadow_pixels(image), pad=pad)


def postpass_artifact_map_png(path: Path, *, pad: int = 1, dry_run: bool = False) -> dict[str, int | str | bool]:
    """Rewrite one 00_00.png in place. Returns a small stats dict."""
    before = Image.open(path)
    before_size = before.size
    after = postpass_artifact_map_frame(before, pad=pad)
    changed = after.size != before_size or list(before.convert("RGBA").getdata()) != list(after.getdata())
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        after.save(path, format="PNG")
    return {
        "path": str(path),
        "before": f"{before_size[0]}x{before_size[1]}",
        "after": f"{after.size[0]}x{after.size[1]}",
        "changed": changed,
        "opaque": sum(1 for p in after.getdata() if p[3] > 0),
    }


def iter_map_frame_pngs(map_root: Path) -> list[Path]:
    if not map_root.is_dir():
        raise FileNotFoundError(f"artifact map root missing: {map_root}")
    return sorted(map_root.glob("homm3_artifact_*/00_00.png"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-root",
        type=Path,
        action="append",
        required=True,
        help="Root containing homm3_artifact_*/00_00.png (repeatable)",
    )
    parser.add_argument("--pad", type=int, default=1, help="Crop pad in pixels (default 1)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    total = 0
    changed = 0
    for root in args.map_root:
        frames = iter_map_frame_pngs(root)
        if not frames:
            print(f"FAIL: no homm3_artifact_*/00_00.png under {root}", file=sys.stderr)
            return 1
        for path in frames:
            stats = postpass_artifact_map_png(path, pad=args.pad, dry_run=args.dry_run)
            total += 1
            if stats["changed"]:
                changed += 1
            print(
                f"{'DRY ' if args.dry_run else ''}"
                f"{path.parent.name}: {stats['before']} -> {stats['after']} "
                f"opaque={stats['opaque']} changed={stats['changed']}"
            )
    print(f"artifact map shadow-crop postpass: frames={total} changed={changed} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
