#!/usr/bin/env python3
"""Full-3D T2 towns: make the building animations that the town_full3d_fx "glow" kind staged actually read in game.

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<cand> python town_t2_anim_pass.py apply
    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<cand> python town_t2_anim_pass.py plan   # print, write nothing

Why: town_full3d_fx.k_glow stages every "glow" DEF as one masked pulse (VfxUber smoothstep(0.1, 0.7, noise * mask),
_Blend 0.3, vertex alpha 0.55) whose mask is the DEF's per-pixel change normalised by its peak. On the 2026-09-30 editor
renders that pulse changes 0-52 px per building (castle banners 5-52, rampart dragon cliff 0, dungeon beholder 9,
slime 0, necropolis pillars 11, holy obelisk 0): the building is staged as animated and does not visibly animate.

What each HoMM3 DEF animates was read from its frames (per-layer recipe in RECIPES; decision recorded in the town's
doc). A recipe rewrites that layer's Fx_Glow_* groups in rows.json (same group, same rest position and size):

  cloth    waving banners/flags (castle halls, training grounds): a fold system (dark _Color, _Blend 1: darkens the
           painted cloth under horizontally scrolling, horizontally-stretched noise = fold bands travelling along the
           cloth) + a sheen system (additive, the cloth's own lit colour, offset phase). Mask: the DEF's moving pixels
           widened to the whole cloth (smoothstep of the peak-normalised change, then blurred).
  pulse    lamps, orbs, gems, glowing pillars: additive, lower threshold (smoothstep(0, 0.35)), brighter colour, the two
           overlapping particles never fade to zero (the light breathes, it does not blink out).
  strike   lightning (town_full3d_fx "lightning" kind, Fx_Lightning_* groups: bolt + glow + sparks): only the bolt's
           visibility changes (mask linear, threshold on the decoded noise, additive, brighter); its lifetime and
           alpha keys (the strike flicker) are kept. Tower tbtwdw_6_2 measured 0 px moved on the 2026-09-30 render.
  shimmer  small / scattered moving highlights (slime drips, beholder skin, dragon-cliff glints): additive, fast
           two-noise scroll, moderate gain.

Every recipe keeps the effect inside the DEF's own change mask: nothing lights a pixel HoMM3 does not animate.
Every recipe imports its mask as linear data (srgb false). k_glow's masks are imported sRGB, so the shader read the
peak-normalised change through the sRGB decode (0.5 -> 0.21): measured on the first castle render (2026-09-30) the
cloth recipe under that decode moved 4-6 px per banner, i.e. nothing. The noise textures stay sRGB (the same
TileNoise files are shared with every other effect of the town, and the importer flag is per file), so the thresholds
are set on the DECODED noise: min(n1, n2) * mask over the cloth is p25 0.03 / p50 0.07 / p75 0.13 / p90 0.19 (castle
tbcshal3), and the second castle render (thresholds 0.15 / 0.25 on that) still moved 4-6 px.
--base <cand> re-applies onto groups a previous apply already rewrote: each group's systems are taken from the base
candidate's rows.json (which must still be the single k_glow pulse), the group's own pos/rot/scale (occlusion snap)
are kept.
apply (and `catalog`, which only does this step) then rewrites the Unity build spec + catalog from rows.json
(stronghold_full3d_scene.write_catalog), keeping the lane keys write_catalog does not own (props, phase-2 blocks).
The Unity builder reads build_spec.json, not rows.json: until 2026-09-30 evening apply wrote rows.json only, so every
re-tune after the first apply (srgb false, the decoded-noise thresholds) never reached a bundle, and the "4-6 px"
cloth renders above measured the FIRST tuning (_Min 0.28 / _Max 0.7, mask sRGB). The scene's bundle step now refuses
a build spec that differs from rows.json.
Proof tier of its output: generated artifact (rows.json + mask textures). Visibility is measured afterwards on the
editor renders (full3d_full_t0/1/2), runtime appearance is unproven until seen in game.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_fx as SF  # noqa: E402

# layer id -> recipe. Only layers whose DEF was inspected are listed; an unlisted glow layer is left untouched.
RECIPES = {
    "castle": {"tbcsdw_5": "cloth", "tbcsdw_5_2": "cloth", "tbcshall": "cloth", "tbcshal2": "cloth",
               "tbcshal3": "cloth", "tbcsmag3": "pulse", "tbcsmag4": "pulse", "tbcsspec": "pulse"},
    "rampart": {"tbrmdw_6": "shimmer", "tbrmdw_6_2": "shimmer"},
    "necropolis": {"tbncblak": "pulse", "tbncholy": "pulse"},
    "tower": {"tbtwdw_6_2": "strike"},
    "dungeon": {"tbdndw_0": "shimmer", "tbdndw_0_2": "shimmer", "tbdnhrd2": "shimmer",
                "tbdndw_2": "shimmer", "tbdndw_2_2": "shimmer"},
}


def _float(mat: dict, name: str, value: float) -> None:
    for f in mat["floats"]:
        if f["name"] == name:
            f["value"] = float(value)
            return
    mat["floats"].append({"name": name, "value": float(value)})


def _colour(mat: dict) -> list[float]:
    return next(c["rgba"] for c in mat["colors"] if c["name"] == "_Color")


def _set_colour(mat: dict, rgba) -> None:
    for c in mat["colors"]:
        if c["name"] == "_Color":
            c["rgba"] = [float(x) for x in rgba]


def _tex(mat: dict, prop: str) -> dict:
    return next(t for t in mat["textures"] if t["prop"] == prop)


def widened_mask(src: Path, dst: Path, lo: float, hi: float, blur: float) -> None:
    m = np.asarray(Image.open(src).convert("L"), np.float32) / 255.0
    t = np.clip((m - lo) / max(hi - lo, 1e-6), 0, 1)
    t = t * t * (3 - 2 * t)
    t = cv2.GaussianBlur(t, (0, 0), blur * m.shape[0] / 256.0)
    Image.fromarray((np.clip(t / max(float(t.max()), 1e-6), 0, 1) * 255).astype(np.uint8)).save(dst)


def cloth(pk: str, q: dict) -> list[dict]:
    base = q["systems"][0]
    m0 = base["material"]
    col = _colour(m0)[:3]
    mask = _tex(m0, "_Mask")
    mask["srgb"] = False
    src = S.STAGE / pk / Path(mask["path"]).name
    dst_name = src.name.replace("glow_", "cloth_")
    widened_mask(src, S.STAGE / pk / dst_name, 0.02, 0.16, 2.0)
    mpath = f"{S.ASSET_ROOT}/{pk}/{dst_name}"
    fold = copy.deepcopy(base)
    fold["name"] = "fold"
    fm = fold["material"]
    _tex(fm, "_Mask")["path"] = mpath
    _tex(fm, "_Texture").update(st=[3.0, 0.6, 0.0, 0.0])
    _tex(fm, "_Texture2").update(st=[1.6, 0.35, 0.0, 0.0])
    for k, v in {"_Min": 0.04, "_Max": 0.2, "_Lerp": 1.0, "_Blend": 1.0,
                 "_xSpeed01": 0.32, "_ySpeed01": 0.0, "_xSpeed02": 0.21, "_ySpeed02": 0.02}.items():
        _float(fm, k, v)
    _set_colour(fm, [0.03, 0.03, 0.05, 1.0])
    fold["color"] = [1.0, 1.0, 1.0, 0.8]
    sheen = copy.deepcopy(fold)
    sheen["name"] = "sheen"
    sheen["seed"] = int(base["seed"]) ^ 0x5A5A5
    sm = sheen["material"]
    _tex(sm, "_Texture").update(st=[2.4, 0.5, 0.37, 0.0])
    _tex(sm, "_Texture2").update(st=[1.3, 0.3, 0.61, 0.0])
    for k, v in {"_Min": 0.08, "_Max": 0.25, "_Blend": 0.0, "_xSpeed01": 0.27, "_xSpeed02": 0.17}.items():
        _float(sm, k, v)
    _set_colour(sm, [c * 1.3 for c in col] + [1.0])
    sheen["color"] = [1.0, 1.0, 1.0, 0.7]
    return [fold, sheen]


def pulse(pk: str, q: dict) -> list[dict]:
    s = copy.deepcopy(q["systems"][0])
    m = s["material"]
    _tex(m, "_Mask")["srgb"] = False
    for k, v in {"_Min": 0.0, "_Max": 0.35, "_Lerp": 1.0, "_Blend": 0.0}.items():
        _float(m, k, v)
    _set_colour(m, [c * 1.8 for c in _colour(m)[:3]] + [1.0])
    s["color"] = [1.0, 1.0, 1.0, 0.95]
    s["alphaKeys"] = [0.0, 0.3, 0.5, 1.0, 1.0, 0.3]
    return [s]


def shimmer(pk: str, q: dict) -> list[dict]:
    s = copy.deepcopy(q["systems"][0])
    m = s["material"]
    _tex(m, "_Mask")["srgb"] = False
    # 2026-09-30 dungeon render at _Min 0.02 / _Max 0.15, colour x1.6, alpha 0.9: the slime tower turned into solid
    # yellow-green blotches (843 px moved, most of the cloth of slime saturated): softened to a highlight.
    for k, v in {"_Min": 0.06, "_Max": 0.3, "_Lerp": 1.0, "_Blend": 0.0,
                 "_xSpeed01": 0.18, "_ySpeed01": 0.26, "_xSpeed02": -0.22, "_ySpeed02": 0.14}.items():
        _float(m, k, v)
    _set_colour(m, list(_colour(m)[:3]) + [1.0])
    s["color"] = [1.0, 1.0, 1.0, 0.7]
    return [s]


def strike(pk: str, q: dict) -> list[dict]:
    out = copy.deepcopy(q["systems"])
    b = out[0]
    m = b["material"]
    _tex(m, "_Mask")["srgb"] = False
    for k, v in {"_Min": 0.0, "_Max": 0.2, "_Lerp": 1.0, "_Blend": 0.0}.items():
        _float(m, k, v)
    _set_colour(m, [min(c * 1.5, 2.0) for c in _colour(m)[:3]] + [1.0])
    return out


KINDS = {"cloth": cloth, "pulse": pulse, "shimmer": shimmer, "strike": strike}
# recipe -> (group name prefix, the k_* system names the group must have before the recipe)
SOURCE = {"cloth": ("Fx_Glow_", ["pulse"]), "pulse": ("Fx_Glow_", ["pulse"]), "shimmer": ("Fx_Glow_", ["pulse"]),
          "strike": ("Fx_Lightning_", ["bolt", "glow", "sparks"])}


def recipes_for(faction: str) -> dict:
    """Group A's RECIPES, or another group's (town_t2_props_gen.EXTRA_RECIPES, TOWN_T2_PROPS_GROUP) for its towns."""
    if faction in RECIPES:
        return RECIPES[faction]
    import town_t2_props_gen as GEN
    return GEN.EXTRA_RECIPES.get(faction, {})


def refresh_catalog() -> None:
    """build_spec.json + catalog.json from rows.json, lane keys of the previous catalog kept (as town_t2_props.stage)."""
    cp = S.OUT / "catalog.json"
    S.write_catalog(S.Scene(), carry="previous")
    print("catalog + build spec rewritten from rows.json:", cp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "apply", "catalog"])
    ap.add_argument("--base", default="", help="re-apply: take each group's systems from this candidate's rows.json")
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    if a.cmd == "catalog":
        refresh_catalog()
        return 0
    recipes = recipes_for(SC.FACTION)
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    base_rows = None
    if a.base:
        bp = SC.DATA / "candidates" / a.base / S.ROWS.relative_to(S.CAND)
        base_rows = json.loads(bp.read_text(encoding="utf-8"))
    rep = []
    for lid, kind in recipes.items():
        pk = S.PREFIX + lid
        if pk not in rows:
            raise SystemExit(f"anim pass: recipe for {lid} but no staged prefab {pk}")
        prefix, want = SOURCE[kind]
        groups = [q for q in rows[pk].get("particles", []) if q["name"].startswith(prefix)]
        if not groups:
            raise SystemExit(f"anim pass: recipe for {lid} but it stages no {prefix} group")
        for q in groups:
            if base_rows is not None:
                bq = [g for g in base_rows.get(pk, {}).get("particles", []) if g["name"] == q["name"]]
                if len(bq) != 1 or [s["name"] for s in bq[0]["systems"]] != want:
                    raise SystemExit(f"anim pass: base {a.base} has no unmodified {want} group {pk}/{q['name']}")
                q["systems"] = copy.deepcopy(bq[0]["systems"])
            if [s["name"] for s in q["systems"]] != want or (kind == "strike" and not a.base):
                raise SystemExit(f"anim pass: {pk}/{q['name']} is not the unmodified {want} group "
                                 f"({[s['name'] for s in q['systems']]}); already applied? (strike keeps the system "
                                 f"names, so it is applied with --base only)")
            q["systems"] = KINDS[kind](pk, q)
            rep.append({"layer": lid, "group": q["name"], "recipe": kind, "systems": [s["name"] for s in q["systems"]]})
    for r in rep:
        print(json.dumps(r))
    if a.cmd == "apply":
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        (S.WORK / "anim_pass.json").write_text(json.dumps({"faction": SC.FACTION, "groups": rep}, indent=1),
                                               encoding="utf-8")
        refresh_catalog()
    print(f"{a.cmd}: {len(rep)} group(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
