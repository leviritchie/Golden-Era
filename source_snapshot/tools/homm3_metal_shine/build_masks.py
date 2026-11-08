#!/usr/bin/env python3
"""Build the metal-shine masks and the plugin catalog (docs/homm3_metal_shine.md).

For every unit in tools/homm3_metal_shine/units.json:
  * read the slice's FROZEN look-delivered GLB (the mesh whose TEXCOORD_0 ships in the bundle) and its frozen
    base colour, both sha-checked against the slice row (fail closed on drift);
  * mask = tools/homm3_unit_look/metal.py texture_mask(...) on the GLB's Meshy metallicRoughness map
    (B = metallic), at the shipped mask size;
  * tint = the base colour's hue at full value (rgb / max(rgb)), faded to white where the albedo is near black;
  * write <sid>_metal.png (RGBA8, sRGB tint in RGB, linear mask in A) and catalog.json into
    OfflineUnlockMod/homm3_mesh_fx/metal_shine/ (deployed with the plugin's homm3_mesh_fx folder).

CPU on purpose: one 4096^2 resize + blur per unit, I/O bound, about a second each; there is no per-texel loop to
move to the GPU. Peak RAM about 0.6 GB (the 4096^2 float maps).

  python tools/homm3_metal_shine/build_masks.py [--units h3_swordsman ...] [--board DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_unit_look"))
import metal  # noqa: E402
from glbpatch import Glb  # noqa: E402

UNITS = Path(__file__).resolve().parent / "units.json"
DELIVERY = ROOT / "tools" / "homm3_def_retarget_delivery"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
OUT_DIR = PLUGIN / "homm3_mesh_fx" / "metal_shine"
CATALOG_SCHEMA = "homm3_metal_shine_catalog.v1"
SHADER = {"bundle": "homm3_metal_shine_shader", "asset": "assets/homm3metalshine/shaders/homm3metalshine.shader",
          "name": "OldenEra/Homm3/MetalShine"}
MASK_SIZE = 1024
SHINE_KEYS = {"intensity": (0.0, 4.0), "gloss": (2.0, 512.0), "sheen": (0.0, 2.0), "tint": (0.0, 1.0)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def slice_row(slice_name: str, sid: str) -> tuple[dict, Path]:
    sel = json.loads((DELIVERY / f"{slice_name}.json").read_text(encoding="utf-8"))
    rows = [r for r in sel["units"] if r["labSid"] == sid]
    if len(rows) != 1:
        raise SystemExit(f"{sid}: expected one row in {slice_name}.json, found {len(rows)}")
    return rows[0], ROOT / sel["out"] / sid / "inputs"


def build_unit(sid: str, spec: dict) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    row, inputs = slice_row(spec["slice"], sid)
    glb_b = (inputs / "look_delivered.glb").read_bytes()
    bc_b = (inputs / "basecolor.png").read_bytes()
    fz = row["frozen"]
    if sha(glb_b) != fz["lookDeliveredGlbSha256"]:
        raise SystemExit(f"{sid}: inputs/look_delivered.glb sha differs from the {spec['slice']} frozen pin")
    if sha(bc_b) != fz["basecolorSha256"]:
        raise SystemExit(f"{sid}: inputs/basecolor.png sha differs from the {spec['slice']} frozen pin")
    for k, (lo, hi) in SHINE_KEYS.items():
        v = spec["shine"][k]
        if not lo <= v <= hi:
            raise SystemExit(f"{sid}: shine.{k}={v} outside [{lo}, {hi}]")
    glb = Glb(glb_b)
    mask = metal.texture_mask({"mask": spec["mask"]}, glb, MASK_SIZE, None)     # fails closed with no MR map
    bc = np.asarray(Image.open(io.BytesIO(bc_b)).convert("RGB").resize((MASK_SIZE, MASK_SIZE), Image.BOX),
                    np.float32) / 255
    mx = bc.max(-1, keepdims=True)
    hue = bc / np.maximum(mx, 1e-3)
    tint = hue * metal.smooth(mx, 0.03, 0.12) + (1 - metal.smooth(mx, 0.03, 0.12))   # near-black -> white
    covered = bc.max(-1) > 0.02
    share = float((mask[covered] > 0.5).mean())
    if (mask > 0.5).sum() < 200:
        raise SystemExit(f"{sid}: metal mask covers only {int((mask > 0.5).sum())} texels; the Meshy map is "
                         "empty or unusable here (fallback to a material-class / DEF-region mask needs a decision)")
    # The shader multiplies by the mask, so the tint outside it is never seen: flatten it to white there (dilated
    # by 4 texels so bilinear/mip taps at the mask edge still read the true hue). Cuts the PNG several-fold.
    near = ndimage.binary_dilation(mask > 0.004, iterations=4)
    tint = np.where(near[..., None], tint, 1.0)
    rgba = np.concatenate([tint, mask[..., None]], -1)
    png = io.BytesIO()
    Image.fromarray((np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(png, format="PNG", optimize=True)
    pb = png.getvalue()
    name = f"{sid}_metal.png"
    entry = {
        "id": f"metal_shine_{sid}",
        "match": {"unitSids": [sid]},
        "lanes": ["battle"],
        "mask": {"file": name, "sha256": sha(pb), "size": MASK_SIZE,
                 "sourceGlbSha256": fz["lookDeliveredGlbSha256"], "basecolorSha256": fz["basecolorSha256"],
                 "source": spec["mask"], "coveredShare": round(share, 4)},
        "shine": {k: spec["shine"][k] for k in SHINE_KEYS},
    }
    return entry, pb, mask, bc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*")
    ap.add_argument("--board", type=Path, help="also write <sid>_mask_board.png (albedo | mask | overlay) here")
    a = ap.parse_args()
    cfg = json.loads(UNITS.read_text(encoding="utf-8"))
    if cfg.get("schema") != "homm3_metal_shine_units.v1":
        raise SystemExit("units.json schema mismatch")
    sids = a.units or sorted(cfg["units"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cat_path = OUT_DIR / "catalog.json"
    old = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.is_file() else {"entries": []}
    entries = {e["id"]: e for e in old.get("entries", []) if e["match"]["unitSids"][0] in cfg["units"]}
    for sid in sids:
        entry, pb, mask, bc = build_unit(sid, cfg["units"][sid])
        (OUT_DIR / entry["mask"]["file"]).write_bytes(pb)
        entries[entry["id"]] = entry
        print(f"{sid}: mask covers {entry['mask']['coveredShare']:.1%} of the UV-covered texels; "
              f"{entry['mask']['file']} {entry['mask']['sha256'][:12]}")
        if a.board:
            a.board.mkdir(parents=True, exist_ok=True)
            m3 = np.repeat(mask[..., None], 3, -1)
            ov = bc * 0.45 + np.stack([mask, mask * 0.75, mask * 0.1], -1) * 0.55
            row = np.concatenate([bc, m3, ov], 1)
            Image.fromarray((np.clip(row, 0, 1) * 255).astype(np.uint8)).resize(
                (3 * 512, 512), Image.BOX).save(a.board / f"{sid}_mask_board.png")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "proof": "generated artifact: masks from the frozen slice GLBs; shader compile + offline Unity render "
                 "only. Runtime (Hex SRP draw of the appended pass) unproven until the in-game check.",
        "owner": "tools/homm3_metal_shine/build_masks.py (docs/homm3_metal_shine.md)",
        "shader": SHADER,
        "entries": [entries[k] for k in sorted(entries)],
    }
    cat_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {cat_path.relative_to(ROOT)} ({len(catalog['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
