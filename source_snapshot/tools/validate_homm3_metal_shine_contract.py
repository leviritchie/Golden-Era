#!/usr/bin/env python3
"""Validate the dynamic metal-shine contract (docs/homm3_metal_shine.md).

Static checks only (no Unity, no game):
  * OfflineUnlockMod/homm3_mesh_fx/metal_shine/catalog.json has schema homm3_metal_shine_catalog.v1, the
    OldenEra/Homm3/MetalShine shader block, and its shader bundle file exists next to it;
  * every catalog row is battle-lane, matches exactly one unit sid, and its mask PNG exists with the pinned sha256,
    is RGBA at the pinned size, and has a non-empty alpha mask;
  * every row's sourceGlbSha256 / basecolorSha256 equals the slice row's frozen pins today (a re-frozen unit makes
    its mask stale: rerun tools/homm3_metal_shine/build_masks.py);
  * catalog rows and tools/homm3_metal_shine/units.json name the same units with the same shine values;
  * the plugin keeps its two hooks: the battle attach call and the Hex/Lit rebind exclusion for the shine material.

  python tools/validate_homm3_metal_shine_contract.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
SHINE_DIR = PLUGIN / "homm3_mesh_fx" / "metal_shine"
UNITS = ROOT / "tools" / "homm3_metal_shine" / "units.json"
DELIVERY = ROOT / "tools" / "homm3_def_retarget_delivery"
SHADER = {"bundle": "homm3_metal_shine_shader", "asset": "assets/homm3metalshine/shaders/homm3metalshine.shader",
          "name": "OldenEra/Homm3/MetalShine"}
SHINE_KEYS = {"intensity": (0.0, 4.0), "gloss": (2.0, 512.0), "sheen": (0.0, 2.0), "tint": (0.0, 1.0)}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    errors: list[str] = []
    cat_path = SHINE_DIR / "catalog.json"
    if not cat_path.is_file():
        print(f"FAIL: missing {cat_path}")
        return 1
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    if cat.get("schema") != "homm3_metal_shine_catalog.v1":
        errors.append(f"catalog schema {cat.get('schema')!r}")
    if cat.get("shader") != SHADER:
        errors.append(f"catalog shader block {cat.get('shader')!r} != {SHADER!r}")
    bundle = SHINE_DIR / SHADER["bundle"]
    if not bundle.is_file() or bundle.stat().st_size < 1024:
        errors.append(f"shader bundle missing or truncated: {bundle}")

    units = json.loads(UNITS.read_text(encoding="utf-8"))
    if units.get("schema") != "homm3_metal_shine_units.v1":
        errors.append(f"units.json schema {units.get('schema')!r}")
    units = units.get("units", {})

    try:
        from PIL import Image
        import numpy as np
    except ImportError:          # pragma: no cover - the repo toolchain has both
        Image = None
    seen: set[str] = set()
    for e in cat.get("entries", []):
        rid = e.get("id", "?")
        sids = e.get("match", {}).get("unitSids", [])
        if len(sids) != 1:
            errors.append(f"{rid}: expected exactly one unit sid, got {sids}")
            continue
        sid = sids[0]
        if sid in seen:
            errors.append(f"{rid}: duplicate row for {sid}")
        seen.add(sid)
        if rid != f"metal_shine_{sid}":
            errors.append(f"{rid}: id must be metal_shine_{sid}")
        if e.get("lanes") != ["battle"]:
            errors.append(f"{rid}: lanes {e.get('lanes')} (battle only: map fog / preview have no sun)")
        m = e.get("mask", {})
        png = SHINE_DIR / str(m.get("file", ""))
        if not png.is_file():
            errors.append(f"{rid}: mask file missing {png}")
        else:
            if sha(png) != m.get("sha256"):
                errors.append(f"{rid}: {png.name} sha256 differs from the catalog pin")
            if Image is not None:
                im = Image.open(png)
                if im.mode != "RGBA" or im.size != (m.get("size"), m.get("size")):
                    errors.append(f"{rid}: {png.name} is {im.mode} {im.size}, expected RGBA {m.get('size')}^2")
                elif (np.asarray(im)[..., 3] > 127).sum() < 200:
                    errors.append(f"{rid}: {png.name} alpha mask is (nearly) empty")
        spec = units.get(sid)
        if spec is None:
            errors.append(f"{rid}: {sid} is not opted in by units.json")
            continue
        sel_path = DELIVERY / f"{spec['slice']}.json"
        sel = json.loads(sel_path.read_text(encoding="utf-8"))
        rows = [r for r in sel.get("units", []) if r.get("labSid") == sid]
        if len(rows) != 1:
            errors.append(f"{rid}: {len(rows)} rows for {sid} in {sel_path.name}")
        else:
            fz = rows[0].get("frozen", {})
            if fz.get("lookDeliveredGlbSha256") != m.get("sourceGlbSha256") \
                    or fz.get("basecolorSha256") != m.get("basecolorSha256"):
                errors.append(f"{rid}: mask built from a different frozen GLB/basecolor than {sel_path.name} pins now "
                              "(unit re-frozen: rerun tools/homm3_metal_shine/build_masks.py)")
        shine = e.get("shine", {})
        for k, (lo, hi) in SHINE_KEYS.items():
            v = shine.get(k)
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                errors.append(f"{rid}: shine.{k}={v!r} outside [{lo}, {hi}]")
            elif v != spec.get("shine", {}).get(k):
                errors.append(f"{rid}: shine.{k}={v} differs from units.json ({spec.get('shine', {}).get(k)})")
        if m.get("source") != spec.get("mask"):
            errors.append(f"{rid}: mask source {m.get('source')} differs from units.json {spec.get('mask')}")
    for sid in sorted(set(units) - seen):
        errors.append(f"units.json opts in {sid} but the catalog has no row (rerun build_masks.py)")

    hook = (PLUGIN / "Homm3ImportReleaseBattleVisualHook.cs").read_text(encoding="utf-8")
    if "Homm3MetalShine.TryAttachForSkinnedBattle(instance, entry, Plugin.LogSource);" not in hook:
        errors.append("battle attach call missing from Homm3ImportReleaseBattleVisualHook.AttachRuntimeHelpers")
    vis = (PLUGIN / "Homm3ImportVisuals.cs").read_text(encoding="utf-8")
    if "StartsWith(Homm3MetalShine.MaterialPrefix, StringComparison.Ordinal)" not in vis:
        errors.append("Hex/Lit rebind exclusion for HOMM3_metal_shine_ materials missing from Homm3ImportVisuals")
    src = (PLUGIN / "Homm3MetalShine.cs").read_text(encoding="utf-8")
    if 'MaterialPrefix = "HOMM3_metal_shine_"' not in src:
        errors.append("Homm3MetalShine.MaterialPrefix is not HOMM3_metal_shine_")

    if errors:
        for err in errors:
            print("FAIL:", err)
        return 1
    print(f"OK: metal-shine contract holds for {len(seen)} unit(s): {', '.join(sorted(seen))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
