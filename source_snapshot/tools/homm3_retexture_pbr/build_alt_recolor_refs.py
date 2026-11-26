#!/usr/bin/env python3
"""Rebuild the owner-approved HotA alt-upgrade sprite recolors as retexture DEF references.

The alt upgrades (``h3_*_upg_alt``: Factory/Bulwark) were made from ``material_class_hs`` palette recolors of their
HotA upgrade's battle sprites (user-locked option per unit in
``tools/homm3_import/alternate_upgrade_concepts/material_class_hs_selections.json``). The lab
``extracted_battle`` folders were later re-extracted from the plain HotA upgrade, so the ``*_def_retarget.blend.frames.json``
sources of an alt unit are byte-identical to its HotA upgrade's frames. Painting from them gives the alt unit the HotA
upgrade's colours.

This tool re-applies the locked palette remap (same functions as ``bake_hota_alt_material_class_hs_units.py``: source
palette from the HotA zip, ``resolve_target_palette``) to those RGBA frames and writes them to
``artifacts/homm3_alt_recolor_refs/<gameAltSid>/`` with a ``meta.json``. ``def_sprite_loader.resolve_def_sources``
uses that folder for every ``*_upg_alt`` unit and refuses to fall back to the raw frames.

Pixel mapping: exact palette colours map to their target entry. Other opaque pixels (filtered/interpolated frames)
take the nearest source entry's shift (target - source), so blends keep their shading. Special slots 0-7 (key cyan and
shadows) are never remapped. The standing frame is checked against the approved spotcheck pair
(``material_class_hs_bake_spotcheck/<sid>_standing_pair.png``) when it exists.

Usage:
  python tools/homm3_retexture_pbr/build_alt_recolor_refs.py [--only h3_gunslinger_upg_alt,...] [--force]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
IMPORT_DIR = REPO / "tools" / "homm3_import"
sys.path.insert(0, str(IMPORT_DIR))
import bake_hota_alt_material_class_hs_units as B  # noqa: E402

SELECTIONS = IMPORT_DIR / "alternate_upgrade_concepts" / "material_class_hs_selections.json"
SPOTCHECK = IMPORT_DIR / "alternate_upgrade_concepts" / "material_class_hs_bake_spotcheck"
OUT_ROOT = REPO / "artifacts" / "homm3_alt_recolor_refs"
SPECIAL = B.SPECIAL_PALETTE_SLOT_COUNT


def source_palette(selection: dict) -> list[tuple[int, int, int]]:
    row = B.inventory_row(selection["fromLabSid"])
    kind = B.battle_source_kind(row)
    if kind == "def":
        return B.palette_from_def(B.read_zip_member(REPO / Path(row["battleZipPath"]), row["battleZipMember"]))
    basename = row["battleExtractBasename"]
    frame_dir, tmp = B.materialize_json_png_mode_p_frames(
        row, basename=basename, lab_dir=Path("."), zip_json_key="battleJsonZipMember",
        zip_prefix_key="battleJsonDirPrefix", zip_path_key="battleZipPath")
    try:
        return B.require_shared_p_palette(frame_dir)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def remap(rgba: np.ndarray, src: np.ndarray, shift: np.ndarray, exact: dict[int, np.ndarray]) -> tuple[np.ndarray, int, int]:
    out = rgba.copy()
    a = rgba[..., 3] > 0
    px = rgba[a][:, :3].astype(np.int32)
    if not len(px):
        return out, 0, 0
    keys = (px[:, 0] << 16) | (px[:, 1] << 8) | px[:, 2]
    uniq, inv = np.unique(keys, return_inverse=True)
    new = np.empty((len(uniq), 3), np.int32)
    n_exact_u = np.zeros(len(uniq), bool)
    for i, k in enumerate(uniq):
        if int(k) in exact:
            new[i] = exact[int(k)]
            n_exact_u[i] = True
        else:
            c = np.array([(k >> 16) & 255, (k >> 8) & 255, k & 255], np.int32)
            j = int(np.argmin(((src - c) ** 2).sum(1)))
            new[i] = np.clip(c + shift[j], 0, 255)
    out_px = new[inv]
    sub = out[a]
    sub[:, :3] = out_px.astype(np.uint8)
    out[a] = sub
    exact_px = int(n_exact_u[inv].sum())
    return out, exact_px, len(px)


def spotcheck_delta(unit: str, frame: np.ndarray) -> float | None:
    pair = SPOTCHECK / f"{unit}_standing_pair.png"
    if not pair.is_file():
        return None
    im = np.asarray(Image.open(pair).convert("RGBA")).astype(np.int32)
    h, w = frame.shape[:2]
    right = im[:h, w + 16: w + 16 + w]
    if right.shape[:2] != (h, w):
        return None
    m = frame[..., 3] > 200
    if not m.any():
        return None
    return float(np.abs(right[m][:, :3] - frame[m][:, :3].astype(np.int32)).mean())


def build(selection: dict, force: bool) -> dict:
    unit = selection["gameAltSid"]
    frames_json = REPO / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.blend.frames.json"
    sources = [Path(s) for s in json.loads(frames_json.read_text(encoding="utf-8")).get("sources") or []]
    sources = [s if s.is_absolute() else REPO / s for s in sources]
    if not sources or not all(s.is_file() for s in sources):
        raise FileNotFoundError(f"{unit}: frames.json sources missing under {frames_json}")
    out_dir = OUT_ROOT / unit
    if out_dir.exists() and not force:
        return json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    materials = B.gallery_option_materials(selection["faction"], selection["baseSid"], selection["optionId"],
                                           selection.get("line"))
    src_pal = source_palette(selection)
    tgt_pal, _rows = B.resolve_target_palette(src_pal, materials)
    src = np.array(src_pal[SPECIAL:], np.int32)
    tgt = np.array(tgt_pal[SPECIAL:], np.int32)
    shift = tgt - src
    exact: dict[int, np.ndarray] = {}
    for s, t in zip(src, tgt):
        exact.setdefault(int((s[0] << 16) | (s[1] << 8) | s[2]), t)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    written, n_exact, n_px, standing = [], 0, 0, None
    for i, s in enumerate(sources):
        rgba = np.asarray(Image.open(s).convert("RGBA"))
        out, e, n = remap(rgba, src, shift, exact)
        n_exact += e
        n_px += n
        name = f"{i:04d}_{s.parent.name.replace('.dir', '')}_{s.name}"
        Image.fromarray(out).save(out_dir / name)
        written.append(name)
        if standing is None and s.name.startswith("02_"):
            standing = out
    meta = {
        "schema": "homm3_alt_recolor_refs.v1",
        "unit": unit,
        "displayName": selection["displayName"],
        "fromLabSid": selection["fromLabSid"],
        "optionId": selection["optionId"],
        "materials": materials,
        "paletteChangedEntries": int((shift != 0).any(1).sum()),
        "exactPixelFraction": round(n_exact / max(1, n_px), 4),
        "spotcheckMeanAbsDelta": None if standing is None else spotcheck_delta(unit, standing),
        "frames": written,
        "sourceFramesJson": str(frames_json.relative_to(REPO)).replace("\\", "/"),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    want = {u for u in a.only.split(",") if u}
    sels = json.loads(SELECTIONS.read_text(encoding="utf-8-sig"))["selections"]
    bad = 0
    for sel in sels:
        if want and sel["gameAltSid"] not in want:
            continue
        try:
            m = build(sel, a.force)
            print(f"{m['unit']:26s} opt {m['optionId']} from {m['fromLabSid']:34s} frames {len(m['frames']):3d} "
                  f"pal {m['paletteChangedEntries']:3d} exact {m['exactPixelFraction']:.3f} "
                  f"spot {m['spotcheckMeanAbsDelta']}")
        except Exception as exc:  # report every unit, fail at the end
            bad += 1
            print(f"{sel['gameAltSid']:26s} FAILED: {exc}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
