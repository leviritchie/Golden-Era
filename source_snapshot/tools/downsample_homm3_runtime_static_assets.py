#!/usr/bin/env python3
"""Downsample painted high-res masters into runtime-sized live plugin PNGs.

Keeps artifacts/static_asset_painted_upscale/final masters untouched.
Writes Lanczos-downsampled alpha PNGs into OfflineUnlockMod live paths and
optionally force-copies into a Golden Era plugin folder.

Contract: artifacts/static_asset_painted_upscale/RUNTIME_SIZE_CONTRACT.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "artifacts" / "static_asset_painted_upscale" / "RUNTIME_SIZE_CONTRACT.json"
DEFAULT_PLUGIN = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
DEFAULT_MASTERS = ROOT / "artifacts" / "static_asset_painted_upscale" / "final"
DEFAULT_GE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\BepInEx\plugins\OfflineUnlockMod"
)


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def fit_max_side(size: tuple[int, int], max_side: int) -> tuple[int, int]:
    w, h = size
    m = max(w, h)
    if m <= max_side:
        return w, h
    scale = max_side / float(m)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return nw, nh


def downsample_rgba(src: Path, dst: Path, max_side: int, force_square: bool) -> tuple[int, int, int]:
    with Image.open(src) as im:
        im = im.convert("RGBA")
        before = im.size
        if force_square:
            side = min(max_side, max(before))
            if before != (side, side):
                im = im.resize((side, side), Image.Resampling.LANCZOS)
        else:
            target = fit_max_side(before, max_side)
            if target != before:
                im = im.resize(target, Image.Resampling.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, format="PNG", optimize=True)
        return before[0], before[1], im.size[0] * 1_000_000 + im.size[1]  # pack after for logging


def downsample_portrait(src: Path, dst: Path, max_side: int) -> tuple[tuple[int, int], tuple[int, int]]:
    with Image.open(src) as im:
        im = im.convert("RGBA")
        before = im.size
        side = min(max_side, max(before))
        after = (side, side) if before[0] == before[1] else fit_max_side(before, max_side)
        if after != before:
            im = im.resize(after, Image.Resampling.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, format="PNG", optimize=True)
        return before, im.size


def downsample_billboard(src: Path, dst: Path, max_side: int) -> tuple[tuple[int, int], tuple[int, int]]:
    with Image.open(src) as im:
        im = im.convert("RGBA")
        before = im.size
        after = fit_max_side(before, max_side)
        if after != before:
            im = im.resize(after, Image.Resampling.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, format="PNG", optimize=True)
        return before, im.size


def bytes_of(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def dir_png_bytes(path: Path, pattern: str = "*.png") -> tuple[int, int]:
    files = list(path.glob(pattern)) if path.is_dir() else []
    return len(files), sum(f.stat().st_size for f in files)


def rglob_bytes(path: Path, pattern: str) -> tuple[int, int]:
    files = list(path.rglob(pattern)) if path.is_dir() else []
    return len(files), sum(f.stat().st_size for f in files)


def resolve_master_portrait(masters: Path, live: Path, name: str) -> Path:
    candidate = masters / name
    if candidate.is_file():
        return candidate
    # Masters may only hold promoted finals; fall back to current live (already upscaled).
    if live.is_file():
        return live
    raise FileNotFoundError(f"No master or live portrait for {name}")


def resolve_master_billboard(masters: Path, live: Path, rel_key: str) -> Path:
    # Prefer flat final name matching live leaf when present; else live itself.
    leaf = live.name
    flat = masters / leaf
    if flat.is_file():
        return flat
    # Some pipelines store finals with path-encoded names.
    encoded = masters / rel_key.replace("\\", "__").replace("/", "__")
    if encoded.is_file():
        return encoded
    if live.is_file():
        return live
    raise FileNotFoundError(f"No master or live billboard for {rel_key}")


def process_portraits(plugin: Path, masters: Path, max_side: int, dry_run: bool) -> dict:
    live_dir = plugin / "homm3_portraits"
    files = sorted(live_dir.glob("h3_*.png"))
    changed = 0
    for live in files:
        src = resolve_master_portrait(masters, live, live.name)
        if dry_run:
            with Image.open(src) as im:
                before = im.size
            after = (min(max_side, max(before)),) * 2 if before[0] == before[1] else fit_max_side(before, max_side)
            if after != before:
                changed += 1
            continue
        before, after = downsample_portrait(src, live, max_side)
        if after != before:
            changed += 1
    n, total = dir_png_bytes(live_dir, "h3_*.png")
    return {"count": n, "bytes": total, "changed": changed, "maxSide": max_side}


def process_billboards(plugin: Path, masters: Path, max_side: int, dry_run: bool) -> dict:
    refs = plugin / "homm3_runtime_assets" / "map_object_refs"
    files = sorted(refs.rglob("00_00.png"))
    changed = 0
    for live in files:
        rel = str(live.relative_to(plugin)).replace("\\", "/")
        src = resolve_master_billboard(masters, live, rel)
        if dry_run:
            with Image.open(src) as im:
                before = im.size
            after = fit_max_side(before, max_side)
            if after != before:
                changed += 1
            continue
        before, after = downsample_billboard(src, live, max_side)
        if after != before:
            changed += 1
    n, total = rglob_bytes(refs, "00_00.png")
    return {"count": n, "bytes": total, "changed": changed, "maxSide": max_side}


def force_copy_tree(src_root: Path, dst_root: Path, relative: str) -> None:
    src = src_root / relative
    dst = dst_root / relative
    if not src.exists():
        raise FileNotFoundError(src)
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    if dst.exists():
        # Copy file-by-file for portrait dir / billboard frames only when relative is a dir.
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    else:
        shutil.copytree(src, dst)


def deploy_to_ge(plugin: Path, ge: Path) -> None:
    if not ge.is_dir():
        raise FileNotFoundError(f"Golden Era plugin folder missing: {ge}")
    # Portraits: replace entire folder contents for h3_*.png
    src_p = plugin / "homm3_portraits"
    dst_p = ge / "homm3_portraits"
    dst_p.mkdir(parents=True, exist_ok=True)
    for src in src_p.glob("h3_*.png"):
        shutil.copy2(src, dst_p / src.name)
    # Billboards: only 00_00.png frames under map_object_refs
    src_refs = plugin / "homm3_runtime_assets" / "map_object_refs"
    dst_refs = ge / "homm3_runtime_assets" / "map_object_refs"
    for src in src_refs.rglob("00_00.png"):
        rel = src.relative_to(src_refs)
        target = dst_refs / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def refresh_factory_bulwark_manifest_hashes(plugin: Path) -> int:
    """Keep fail-closed Factory/Bulwark file-hash manifest aligned after billboard downsamples."""
    manifest_path = plugin / "homm3_runtime_assets" / "hota_factory_bulwark_asset_manifest.json"
    if not manifest_path.is_file():
        return 0
    import hashlib

    root = ROOT
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_plugin_rel = plugin.resolve().relative_to(root.resolve())
    updated = 0
    for row in manifest.get("files") or []:
        try:
            relative = Path(row["path"]).relative_to(source_plugin_rel)
        except Exception:
            continue
        path = plugin / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        dig = hashlib.sha256(data).hexdigest().upper()
        if row.get("length") != len(data) or row.get("sha256") != dig:
            row["length"] = len(data)
            row["sha256"] = dig
            updated += 1
    if updated:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN)
    ap.add_argument("--masters-dir", type=Path, default=DEFAULT_MASTERS)
    ap.add_argument("--ge-plugin-root", type=Path, default=DEFAULT_GE)
    ap.add_argument("--deploy-ge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--portrait-max-side", type=int, default=0)
    ap.add_argument("--billboard-max-side", type=int, default=0)
    args = ap.parse_args()

    contract = load_contract()
    portrait_max = args.portrait_max_side or int(contract["runtime"]["unitPortraits"]["maxSidePx"])
    billboard_max = args.billboard_max_side or int(
        contract["runtime"]["mapBillboardPrimaryFrames"]["maxSidePx"]
    )

    plugin = args.plugin_root.resolve()
    masters = args.masters_dir.resolve()
    if not plugin.is_dir():
        print(f"FAIL: plugin root missing: {plugin}", file=sys.stderr)
        return 2

    before_p = dir_png_bytes(plugin / "homm3_portraits", "h3_*.png")
    before_b = rglob_bytes(plugin / "homm3_runtime_assets" / "map_object_refs", "00_00.png")
    print(
        f"BEFORE portraits n={before_p[0]} MB={before_p[1]/1e6:.1f}; "
        f"billboard 00_00 n={before_b[0]} MB={before_b[1]/1e6:.1f}"
    )

    portraits = process_portraits(plugin, masters, portrait_max, args.dry_run)
    billboards = process_billboards(plugin, masters, billboard_max, args.dry_run)
    refreshed = 0 if args.dry_run else refresh_factory_bulwark_manifest_hashes(plugin)
    if refreshed:
        print(f"Refreshed {refreshed} hota_factory_bulwark_asset_manifest.json hash row(s)")

    print(
        f"AFTER  portraits n={portraits['count']} MB={portraits['bytes']/1e6:.1f} "
        f"changed={portraits['changed']} maxSide={portraits['maxSide']}"
    )
    print(
        f"AFTER  billboard 00_00 n={billboards['count']} MB={billboards['bytes']/1e6:.1f} "
        f"changed={billboards['changed']} maxSide={billboards['maxSide']}"
    )

    if args.deploy_ge and not args.dry_run:
        deploy_to_ge(plugin, args.ge_plugin_root.resolve())
        ge_p = dir_png_bytes(args.ge_plugin_root / "homm3_portraits", "h3_*.png")
        ge_b = rglob_bytes(args.ge_plugin_root / "homm3_runtime_assets" / "map_object_refs", "00_00.png")
        print(
            f"DEPLOYED GE portraits n={ge_p[0]} MB={ge_p[1]/1e6:.1f}; "
            f"billboard 00_00 n={ge_b[0]} MB={ge_b[1]/1e6:.1f}"
        )

    report = {
        "before": {"portraits": {"count": before_p[0], "bytes": before_p[1]}, "billboards": {"count": before_b[0], "bytes": before_b[1]}},
        "after": {"portraits": portraits, "billboards": billboards},
        "dryRun": args.dry_run,
        "deployedGe": bool(args.deploy_ge and not args.dry_run),
    }
    out = ROOT / "artifacts" / "static_asset_painted_upscale" / "RUNTIME_DOWNSAMPLE_REPORT.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
