"""Vanilla-style VFX redesign preview: old effect | new (vanilla-style) effect | vanilla unit with a vanilla effect.

    python tools/homm3_vfx/vanilla_style_lab.py [--units h3_fire_elemental,h3_storm_elemental] [--compose-only]
                                                [--timeout 2400] [--prune-renders]

Fire and storm keep their hand-built NEW/VANILLA panels. Every other unit is spec-driven: its NEW panel is built from
its vanilla-style spec (tools/homm3_vfx/vanilla_style/units/ or drafts/, the file the compiler reads), mapped onto the
recipes by resPath + childPath, and its VANILLA panel comes from LAB_REFS (a vanilla unit with its own effects on their
own authored transforms). --prune-renders deletes the raw half-float frames after a successful compose.
Lab replicas: magic/VfxUber, magic/test/Disappearance_01/02/03, and a DXBC-grounded, two-material-only
magic/Water_fire_stylized branch, and a DXBC-grounded magic/Fresnel replica (the bodyOverlay rim material;
its alpha is the mesh vertex colour's alpha, white when the mesh has none). Other vanilla shaders draw nothing
and are reported. The Aqualotl reference
deliberately shows only its selected idle/self-hit water, not every native idle effect.

Design and evidence: docs/olden_era_vanilla_vfx_style.md. Inputs:
  artifacts/vanilla_vfx_style/recipes/   vanilla ParticleSystem recipes + materials/textures/meshes
                                         (tools/homm3_vfx/vanilla_ps_recipe.py, one call for all specs)
  artifacts/vanilla_vfx_style/native/    vanilla unit posed meshes + bones (tools/homm3_style_compare/extract_native.py)
  artifacts/homm3_unit_look/<unit>/      our look (basecolor, vfx_manifest.json: uvAtlas, defFlipbook, effectLight)
  artifacts/homm3_def_retarget/<unit>/   our GLB + spritecam
Stages them into oldenera_factions/Assets/Homm3VfxLab/vanilla_style/ (marker-managed), runs
Homm3VanillaStyleVfxLab.cs through tools/homm3_vfx/unitylock.py (after the shared game/disk/memory launch_guard.py), reads the
linear half-float frames back, composites them over a flat battlefield-ish ground colour, applies a PPv2-like bloom
(threshold 1, soft knee 0.107, intensity 3 -> 2^(3/10)-1, 3 pyramid levels), sRGB-encodes (no tonemapping) and writes
artifacts/vanilla_vfx_style/lab/<unit>/: sheet_<clip>.png, compare.mp4, hero.png, lab_report.json.

Proof tier: Unity-editor lab render with replica shaders (VfxUber, Hex/Lit + assumed emission) and a Python bloom.
Not in game; nothing here is a delivery path.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
__import__("sys").modules[_uq_spec.name] = UQ  # @dataclass resolves its module via sys.modules
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import spec as S  # noqa: E402
import vanilla_style_fx as VSF  # noqa: E402
from volfire_unity_lab import label, write_video, srgb_to_lin, MARKER  # noqa: E402

PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
SRC = Path(__file__).parent / "unity"
VS = ROOT / "artifacts/vanilla_vfx_style"
REC = VS / "recipes"
ASSET_ROOT = "Assets/Homm3VfxLab/vanilla_style"
SCALE = 2          # render at 2x the DEF pixel density
FPS = 24
GROUND = (0.20, 0.22, 0.16)   # sRGB flat ground behind the panels (not a vanilla value)

RECIPES = {
    "wrist": "units__nature__1prefabs__phoenix__Phoenix_upg_ability_fire_01.json",
    "hit": "units__nature__1prefabs__phoenix__Phoenix_upg_hit_fire_Root.json",
    "rise": "units__nature__1prefabs__phoenix__Phoenix_ability_rise_spine.json",
    "strike": "magic__prefabs_vfx__magic_lightning_strike_hex.json",
    "angel": "units__neutral__1prefabs__sentinel__Angel_idle_SmallWing4_L.json",
}


# h3_phoenix views/ was pruned 2026-10-01; this unit records the same prebake sun and battle camera (identical sunTravelUnity).
SUN_SOURCE = ROOT / "artifacts/homm3_unit_look/hota_cove_crew_mate/work/views/views_meta.json"


def sun_travel_unity(unit):
    """The prebake's camera-relative arena sun ('sand'). The fire/storm looks have no views_meta of their own, so
    this takes the one recorded for another unit. The sun is camera-relative, so a unit whose spritecam differs only
    by yaw about the vertical (same pitch: the battle camera seen from another azimuth) gets the sun turned by that
    yaw; a different pitch is refused."""
    vm = json.loads(SUN_SOURCE.read_text())
    v = next(iter(vm["views"].values()))
    cam = json.loads((S.RETARGET / unit / f"{unit}_def_retarget.blend.spritecam.json").read_text())
    src, dst = np.array(v["camForward"], float), np.array(cam["forward"], float)
    if abs(src[2] - dst[2]) > 1e-4 or abs(np.hypot(*src[:2]) - np.hypot(*dst[:2])) > 1e-4:
        raise SystemExit(f"{unit}: spritecam pitch differs from {SUN_SOURCE}; no sun for this camera")
    yaw = math.atan2(dst[1], dst[0]) - math.atan2(src[1], src[0])
    c, s_ = math.cos(yaw), math.sin(yaw)
    f0 = v["sunFrom"]["sand"]
    f = [c * f0[0] - s_ * f0[1], s_ * f0[0] + c * f0[1], f0[2]]   # Blender z-up yaw
    return [f[0], -f[2], f[1]]  # travel = -from; Blender (x,y,z) -> Unity (-x,z,-y)


def B2U(v):
    return [-v[0], v[2], -v[1]]


def recipe(key):
    return json.loads((REC / RECIPES[key]).read_text(encoding="utf-8"))


def node_index(key, path):
    """'Impact/Lightning_sparks' -> index; names repeat inside a recipe, so match the parent chain."""
    nodes = recipe(key)["nodes"]
    parts = path.split("/")
    for i, n in enumerate(nodes):
        chain, j = [n["name"]], n["parent"]
        while j >= 0 and len(chain) < len(parts):
            chain.insert(0, nodes[j]["name"])
            j = nodes[j]["parent"]
        if chain[-len(parts):] == parts:
            return i
    raise KeyError(f"{key}: no node {path}")


def node_rate(key, path):
    n = recipe(key)["nodes"][node_index(key, path)]
    return n["ps"]["emission"]["rate"]["scalar"]


# ------------------------------------------------------------------ quaternions (x, y, z, w), Unity convention
def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def q_yaw(deg):
    h = math.radians(deg) / 2
    return [0.0, math.sin(h), 0.0, math.cos(h)]


def q_from_m(m):
    r = np.array(m, float)[:3, :3]
    r = r / np.linalg.norm(r, axis=0)
    t = np.trace(r)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        return [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    i = int(np.argmax(np.diag(r)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1 + r[i, i] - r[j, j] - r[k, k]) * 2
    q = [0.0, 0.0, 0.0, 0.0]
    q[i] = 0.25 * s
    q[j] = (r[j, i] + r[i, j]) / s
    q[k] = (r[k, i] + r[i, k]) / s
    q[3] = (r[k, j] - r[j, k]) / s
    return q


def eff(id_, key, bone, **kw):
    e = {"id": id_, "recipeFile": str(REC / RECIPES[key]), "bone": bone, "pos": [0, 0, 0], "rot": [0, 0, 0, 1],
         "rootWorldRot": [], "recolor": [], "scale": 1.0, "rateMul": 1.0, "keepRecipeRoot": False, "loopAll": False,
         "alwaysOn": False, "emitUp": False, "zeroChildPos": False, "anchorNode": -1, "keepPS": [],
         "triggers": [], "stops": []}
    e.update(kw)
    return e


def key_t(k):
    """start of DEF key k at 12 keys/s (the lab's key index is floor(t*12 - 0.5))."""
    return (k + 0.5) / 12.0


# ------------------------------------------------------------------ spec-driven panels
HANDBUILT = ("h3_fire_elemental", "h3_storm_elemental")
H = "units/humans/1prefabs/"
# vanilla reference per unit: native body, title, [(recipe source, authored transform, trigger times | None = always)]
_LW = [(H + "lightweaver_upg:Lightweaver_upg_idle_DEF.staff", "Lightweaver_upg_idle_DEF.staff", None),
       (H + "lightweaver_upg:Lightweaver_upg_ability_01_Hand_L", "Lightweaver_upg_ability_01_Hand_L", (0.2, 1.3)),
       (H + "lightweaver_upg:Lightweaver_upg_ability_01_burst_Hand_L", "Lightweaver_upg_ability_01_burst_Hand_L", (0.6, 1.7))]
_ANGEL = [(H + "angel:Angel_idle_FeatherCUpg2_L", "Angel_idle_FeatherCUpg2_L", None),
          (H + "angel:Angel_idle_FeatherCUpg2_L", "Angel_idle_FeatherCUpg2_R", None),
          (H + "angel:Angel_hit_impact_root", "Angel_hit_impact_root", (0.3, 1.4)),
          (H + "angel:Angel_ability_buff_01_root", "Angel_ability_buff_01_root", (0.8,))]
_AQ, _FW = "units/nature/1prefabs/aqualotl_upg", "units/unfrozen/1prefabs/frostworm_rider_upg"
_STAR, _PHX, _FLK = "units/neutral/1prefabs/star_child", "units/nature/1prefabs/phoenix", "units/undead/1prefabs/flicker_upg"
_PIX = "units/neutral/1prefabs/pixie"
_PIXIE = [(_PIX + ":Pixie_idle_def.wing_2.L", "Pixie_idle_def.wing_2.L", None),
          (_PIX + ":Pixie_idle_def.wing_2.R", "Pixie_idle_def.wing_2.R", None),
          (_PIX + ":scale_roll/Pixie/Rig_Pixie/Root/Pixie_hit_impact_root/Transform_01", "Pixie_hit_impact_root", (0.3, 1.4),
           {"sourceRootTransform": True})]
_PHOENIX = [(_PHX + ":Phoenix_upg_ability_fire_01", "Phoenix_upg_ability_fire_01", None),
            (_PHX + ":Phoenix_upg_hit_fire_Root", "Phoenix_upg_hit_fire_Root", (0.3, 1.4)),
            (_PHX + ":Phoenix_ability_rise_spine", "Phoenix_ability_rise_spine", (1.2,))]
_GRIFFIN = [(H + "griffin_upg:griffin_upg_ability_root", "griffin_upg_ability_root", (0.3, 1.4))]
LAB_REFS = {
    **{u: ("lightweaver_upg", "vanilla Lightweaver (upg): staff idle + hand cast + cast burst", _LW)
       for u in ("h3_monk", "h3_priest", "h3_zealot")},
    **{u: ("angel", "vanilla Angel: idle wing feathers + hit impact + buff feathers", _ANGEL)
       for u in ("h3_angel", "h3_archangel", "h3_seraph")},
    **{u: ("griffin_upg", "vanilla Griffin (upg): ability feather burst", _GRIFFIN)
       for u in ("h3_griffin", "h3_royal_griffin", "h3_battle_griffin")},
    "h3_water_elemental": (
        "aqualotl_upg", "vanilla Aqualotl (upg): selected own idle/self-hit water only; other native FX omitted",
        [("units/nature/1prefabs/aqualotl_upg:scale_roll/naiad_upg/Root/Naiad_upg_idle_root", "Naiad_upg_idle_root", None,
          {"keep": ["Water_01", "Water_02", "Water_03"]}),
         ("units/nature/1prefabs/aqualotl_upg:scale_roll/naiad_upg/Root/Naiad_upg_hit_root/Water_01", "Naiad_upg_hit_root", (0.3, 1.4),
          {"sourceRootTransform": True})]),
    **{u: ("pixie", "vanilla Pixie: idle wing pollen + hit impact (butterflies have no replica)", _PIXIE)
       for u in ("h3_pixie", "h3_sprite", "h3_faerie")},
    **{u: ("aqualotl_upg", "vanilla Aqualotl (upg): selected own idle/self-hit water (vanilla elemental reference)",
           [(_AQ + ":scale_roll/naiad_upg/Root/Naiad_upg_idle_root", "Naiad_upg_idle_root", None,
             {"keep": ["Water_01", "Water_02", "Water_03"]})])
       for u in ("h3_air_elemental", "h3_hurricane_elemental")},
    **{u: ("frostworm_rider_upg", "vanilla Frostworm Rider (upg): idle snow + jaw hit (ice stones have no replica)",
           [(_FW + ":FrostWorm_upg_idle_root", "FrostWorm_upg_idle_root", None),
            (_FW + ":FrostWorm_upg_hit_WormBottomJaw", "FrostWorm_upg_hit_WormBottomJaw", (0.3, 1.4))])
       for u in ("h3_ice_elemental", "h3_frost_elemental")},
    **{u: ("qilin_upg", "vanilla Qilin (upg): its own spine idle lightning",
           [("units/nature/1prefabs/qilin_upg:scale_roll/qilin_upg/Root/Hips/Spine/Qilin_upg_idle_Spine",
             "Qilin_upg_idle_Spine", None)])
       for u in ("h3_energy_elemental", "h3_plasma_elemental")},
    "h3_earth_elemental": ("titan", "vanilla Titan: stone body, no unit effect", []),
    "h3_magma_elemental": ("phoenix", "vanilla Phoenix: rise embers only",
                           [(_PHX + ":Phoenix_ability_rise_spine", "Phoenix_ability_rise_spine", None,
                             {"keep": ["Fire_sparks"]})]),
    **{u: ("flicker_upg", "vanilla Flicker (upg): its own always-on magic/Fresnel body overlay", [],
           {"overlays": [(_FLK + ":Scale_roll/flicker_upg/Flicker_upg", 2)]})
       for u in ("h3_psychic_elemental", "h3_magic_elemental")},
    **{u: ("phoenix", "vanilla Phoenix: wing fire + hit fire + rise", _PHOENIX) for u in ("h3_firebird", "h3_phoenix")},
}


# Per-unit VANILLA panel refs as data (one file per unit, so parallel faction agents never edit this module):
# tools/homm3_vfx/vanilla_style/lab_refs/<unit>.json =
#   {"native": "<native body>", "title": "...",
#    "refs": [{"source": "<resPath>:<childPath>", "transform": "<authored transform>", "times": null | [t, ...],
#              "sourceRootTransform": false, "keep": ["<node>", ...]}],
#    "overlays": [{"source": "<resPath>:<rendererPath>", "materialIndex": 2}]}
LAB_REFS_DIR = ROOT / "tools/homm3_vfx/vanilla_style/lab_refs"


def lab_ref(unit):
    """(native, title, refs, extra) from lab_refs/<unit>.json or LAB_REFS; a unit in both is refused."""
    p = LAB_REFS_DIR / f"{unit}.json"
    if p.is_file():
        if unit in LAB_REFS:
            raise SystemExit(f"{unit}: VANILLA refs in both LAB_REFS and {p.name}; keep one")
        d = json.loads(p.read_text(encoding="utf-8"))
        extra_keys = set(d) - {"native", "title", "refs", "overlays", "note"}
        if extra_keys or not d.get("native") or not d.get("title") or not isinstance(d.get("refs"), list):
            raise SystemExit(f"{p}: needs native, title, refs (unknown keys {sorted(extra_keys)})")
        refs = []
        for r in d["refs"]:
            opts = {k: r[k] for k in ("sourceRootTransform", "keep") if k in r}
            times = tuple(r["times"]) if r.get("times") is not None else None
            refs.append((r["source"], r["transform"], times, opts))
        overlays = [(o["source"], int(o["materialIndex"])) for o in d.get("overlays", ())]
        return d["native"], d["title"], refs, ({"overlays": overlays} if overlays else {})
    if unit not in LAB_REFS:
        raise SystemExit(f"{unit}: no VANILLA reference; write {p}")
    row = LAB_REFS[unit]
    return row[0], row[1], row[2], (row[3] if len(row) > 3 else {})


from vanilla_ps_recipe import recipe_key  # noqa: E402  (the one owner of recipe file names)


def recipe_path(source: str) -> Path:
    p = REC / (recipe_key(source) + ".json")
    if not p.is_file():
        raise SystemExit(f"no lab recipe {p.name}; run tools/homm3_vfx/vanilla_ps_recipe.py {REC} with every recipe "
                         f"source (old and new, one call: materials.json is rewritten) including {source}")
    return p


def node_index_in(rec: dict, path: str) -> int:
    """First node whose parent chain ends with `path` (the first of same-named siblings, as Transform.Find)."""
    if path == "":
        return 0
    nodes, parts = rec["nodes"], [q.strip() for q in path.split("/")]
    for i, n in enumerate(nodes):
        chain, j = [n["name"]], n["parent"]
        while j >= 0 and len(chain) < len(parts):
            chain.insert(0, nodes[j]["name"])
            j = nodes[j]["parent"]
        if [c.strip() for c in chain[-len(parts):]] == parts:
            return i
    raise KeyError(f"{rec['source']}: no node {path}")


def unit_spec(unit):
    for drafts in (False, True):
        hit = VSF.specs(drafts=drafts).get(unit)
        if hit:
            return hit[1], ("draft" if drafts else "shipped")
    raise SystemExit(f"{unit}: no vanilla-style spec in units/ or drafts/")


def spec_layer_effects(unit, spec):
    """A spec's vanillaParticles layers as lab effects. The recipe is the childPath node (its parent when childPath
    ends in a bare 'Transform'); keepNodes/anchorNode resolve inside it; window keys become DEF-time triggers/stops;
    loop -> loopAll; emitUp is the runtime's cone-up aim. orient body is only modelled by the hand-built panels."""
    effects = []
    for l in spec["layers"]:
        if l["type"] != "vanillaParticles":
            continue
        src = l["source"]
        parts = src["childPath"].split("/")
        root, prefix = (parts[-2], "Transform/") if parts[-1] == "Transform" else (parts[-1], "")
        # A recipe extracted under the full pinned childPath is unambiguous (Water_01 repeats across the Aqualotl
        # timeline; Pixie's hit Transform_01 sits under an inactive root the extractor's walk skips), so it wins over
        # the extractor's first short-name match, which older recipes are keyed by.
        full = f"{src['resPath']}:{src['childPath']}"
        recipe_child = src["childPath"] if (REC / (recipe_key(full) + ".json")).is_file() else root
        rp = recipe_path(f"{src['resPath']}:{recipe_child}")
        rec = json.loads(rp.read_text(encoding="utf-8"))
        keep = [node_index_in(rec, prefix + k) for k in src["keepNodes"]]
        if l.get("orient", "bone") == "body":
            raise SystemExit(f"{unit}/{l['id']}: orient body is only modelled by the hand-built panels")
        trig, stops, always = [], [], False
        for t in l["triggers"]:
            if t["mode"] == "always":
                always = True
                continue
            trig.append({"clip": t["clip"], "time": key_t(t["startKey"])})
            if "endKey" in t:
                stops.append({"clip": t["clip"], "time": key_t(t["endKey"])})
        # alignToReach: the runtime's boneLocalRot, measured the same way on the GLB the lab renders.
        rot = [0, 0, 0, 1]
        if l.get("alignToReach") is not None:
            import vanilla_style_fx as VSF  # noqa: E402
            rot = VSF.reach_rotation(Path(S.glb_path(unit)), l)
        # boneAnchor: the runtime's boneLocalPos, through the same inverse bind matrix.
        anchors = {}
        if l.get("boneAnchor"):
            import vanilla_style_fx as VSF  # noqa: E402
            anchors = VSF.bone_local_positions(Path(S.glb_path(unit)), l)
        for b in l["bones"]:
            effects.append({
                "id": f"{l['id']}_{b}", "recipeFile": str(rp), "bone": b, "pos": anchors.get(b, [0, 0, 0]), "rot": rot,
                "rootWorldRot": [], "recolor": list(l.get("recolor") or []),
                "recolorMultiply": l.get("recolorMode") == "multiply", "scale": float(l["scale"]),
                "rateMul": float(l.get("rateMul", 1.0)), "keepRecipeRoot": False, "loopAll": bool(l.get("loop")),
                "alwaysOn": always, "emitUp": l.get("orient") == "emitUp",
                "zeroChildPos": bool(l.get("zeroChildPositions")),
                "anchorNode": node_index_in(rec, prefix + l["anchorNode"]) if l.get("anchorNode") else -1,
                "detachOnTrigger": l.get("follow") == "release",
                "keepPS": keep, "triggers": trig, "stops": stops})
    return effects


def spec_overlays(spec, clips):
    """bodyOverlay layers as lab overlays: the probed renderer's material (its recipe, extracted by
    vanilla_ps_recipe.py with the full rendererPath) appended to the body over the trigger window."""
    out = []
    for l in spec["layers"]:
        if l["type"] != "bodyOverlay":
            continue
        src = l["source"]
        rec = json.loads(recipe_path(f"{src['resPath']}:{src['rendererPath']}").read_text(encoding="utf-8"))
        mm = rec["nodes"][0].get("meshMaterials")
        if not mm or src["materialIndex"] >= len(mm) or not mm[src["materialIndex"]]:
            raise SystemExit(f"{spec['unit']}/{l['id']}: recipe root has no meshMaterials[{src['materialIndex']}]; "
                             "re-extract it with the current vanilla_ps_recipe.py")
        t = l["triggers"][0]
        o = {"id": l["id"], "material": mm[src["materialIndex"]], "clip": "", "start": 0.0, "end": 0.0,
             "always": t["mode"] == "always",
             "colors": [{"name": c["property"], "rgba": c["rgba"]} for c in l.get("colors", ())]}
        if not o["always"]:
            end = key_t(t["endKey"]) if "endKey" in t else next(c["frames"] * c["frameStep"] for c in clips
                                                                 if c["name"] == t["clip"])
            o.update(clip=t["clip"], start=key_t(t["startKey"]), end=end)
        out.append(o)
    return out


def spec_clips(spec):
    names = ["Unit_Idle", "Unit_AttackFront"]
    for l in spec["layers"]:
        for t in l.get("triggers", []):
            if t.get("mode") == "window" and t["clip"] not in names:
                names.append(t["clip"])
    return names


def spec_new_panel(unit, camf, clips, sun):
    spec, tier = unit_spec(unit)
    dest, glb = stage_glb(unit)
    em = next(l for l in spec["layers"] if l["type"] == "emissionMap")
    emission_tex, cover = "", 0.0
    flag = {}
    if any(em["color"]) or em["minPower"] or em["blinkPower"]:
        emission = VSF.build_emission(unit, em, {"basecolor": S.out_dir(unit) / "basecolor.png"}, dest / "emission.png")
        emission_tex, cover = f"{unit}/emission.png", emission["meanMask"]
    displacement = [l for l in spec["layers"] if l["type"] == "bodyDisplacement"]
    if unit == "h3_water_elemental" and len(displacement) != 1:
        raise SystemExit(f"{unit}: water lab requires exactly one masked bodyDisplacement layer")
    if displacement:
        import displacement_mask_bake as bake  # noqa: E402

        layer = displacement[0]
        VSF.check_displacement_layer(layer, f"{unit}/{layer['id']}")
        masked = VS / "lab" / f"{unit}_masked.glb"
        bake.bake(Path(S.glb_path(unit)), masked, layer["mask"])
        dest_glb = dest / f"{unit}_vstyle_masked.glb"
        stage_file(masked, dest_glb)
        glb = f"{ASSET_ROOT}/{unit}/{dest_glb.name}"
        flag = {"flagDirection": layer["direction"], "flagPower": layer["power"], "flagSpeed": layer["speed"]}
    body = {"kind": "glb", "glbAssetPath": glb, "texture": f"{unit}/basecolor.png", "emissionTex": emission_tex,
            "emissionColor": em["color"] if emission_tex else [0, 0, 0], "cellST": [],
            "emissionMin": em["minPower"] if emission_tex else 0,
            "blinkSpeed": em["blinkSpeed"] if emission_tex else 0,
            "blinkPower": em["blinkPower"] if emission_tex else 0, "overlays": spec_overlays(spec, clips), **flag}
    return {"id": "new", "body": body, "clips": clips, "effects": spec_layer_effects(unit, spec), "flipbooks": [],
            "oldLights": [], "sunTravelUnity": sun, "warmupS": 1.0, **camf}, cover, tier


def ref_vanilla_panel(unit, camf, sun, yaw):
    name, title, refs, extra = lab_ref(unit)
    body, bones, centre, h = native_body(name, yaw)
    # the donor's own always-on appended material (e.g. flicker_upg's magic/Fresnel on its body renderer)
    body["overlays"] = []
    for source, idx in extra.get("overlays", ()):
        mm = json.loads(recipe_path(source).read_text(encoding="utf-8"))["nodes"][0].get("meshMaterials") or []
        if idx >= len(mm) or not mm[idx]:
            raise SystemExit(f"{unit}: vanilla overlay {source} has no meshMaterials[{idx}]")
        body["overlays"].append({"id": f"vanilla_overlay_{idx}", "material": mm[idx], "clip": "", "start": 0.0,
                                 "end": 0.0, "always": True})
    effects = []
    for row in refs:
        source, inst, times = row[:3]
        opts = row[3] if len(row) > 3 else {}
        rec = json.loads(recipe_path(source).read_text(encoding="utf-8"))
        s = float(np.linalg.norm(np.array(bones[inst])[:3, 0]))
        source_root = rec["nodes"][0] if opts.get("sourceRootTransform") else None
        effects.append({
            "id": inst, "recipeFile": str(recipe_path(source)), "bone": inst, "pos": [0, 0, 0], "rot": [0, 0, 0, 1],
            "rootWorldRot": [], "recolor": [], "scale": s, "rateMul": 1.0, "keepRecipeRoot": False,
            "loopAll": times is None, "alwaysOn": times is None, "emitUp": False, "zeroChildPos": False,
            "anchorNode": -1, "keepPS": [node_index_in(rec, k) for k in opts.get("keep", [])],
            "triggers": [{"clip": "vanilla", "time": t} for t in (times or ())],
            "stops": []})
        if source_root:
            effects[-1]["pos"], effects[-1]["rot"] = source_root["pos"], source_root["rot"]
    cf = dict(camf)
    shift = np.array(centre) - np.array(camf["camCentre"])
    fwd = np.array(camf["camForward"])
    cf["camCentre"] = (np.array(camf["camCentre"]) + shift - fwd * float(shift @ fwd)).tolist()
    clips = [{"name": "vanilla", "keys": 24, "frames": int(2.4 * FPS), "frameStep": 1.0 / FPS, "boilCells": [],
              "loop": True}]
    return {"id": "vanilla", "body": body, "clips": clips, "effects": effects, "flipbooks": [], "oldLights": [],
            "sunTravelUnity": sun, "warmupS": 1.0, **cf}, title, h


# ------------------------------------------------------------------ staging
def stage_file(src: Path, dst: Path, managed_text=False):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if managed_text and dst.exists() and MARKER not in dst.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"refusing to overwrite unmanaged {dst}")
    shutil.copy2(src, dst)


def stage_common():
    dest = PROJECT / ASSET_ROOT
    marker = dest / "HOMM3_VFX_LAB_GENERATED.txt"
    if dest.exists() and not marker.exists() and any(dest.iterdir()):
        raise FileExistsError(f"refusing to write into unmanaged {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text("managed by tools/homm3_vfx/vanilla_style_lab.py\n")
    for sh in ("Homm3VfxUberReplica.shader", "Homm3VfxHexLitEmissionReplica.shader", "Homm3VfxDisappearanceReplica.shader",
               "Homm3VfxWaterFireStylizedReplica.shader", "Homm3VfxFresnelReplica.shader"):
        stage_file(SRC / sh, PROJECT / "Assets/Homm3VfxLab/Shaders" / sh, True)
    stage_file(SRC / "Homm3VanillaStyleVfxLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3VanillaStyleVfxLab.cs", True)
    lib = json.loads((REC / "materials.json").read_text(encoding="utf-8"))
    for t in lib["textures"].values():
        stage_file(REC / t["file"], dest / t["file"])
    for name, m in lib["meshes"].items():       # .txt so Unity does not import the OBJs as models
        stage_file(REC / m["file"], dest / (m["file"] + ".txt"))
    out = {"materials": lib["materials"],
           "textures": [{"name": k, "file": v["file"], "sRGB": v["sRGB"], "mips": v["mips"], "wrapU": v["wrapU"],
                         "wrapV": v["wrapV"]} for k, v in lib["textures"].items()],
           "meshes": [{"name": k, "file": v["file"] + ".txt"} for k, v in lib["meshes"].items()]}
    p = VS / "lab" / "lab_materials.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    return p


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def emission_map(unit, dest: Path):
    """Emission texture from our own base colour (the vanilla pattern is a painted emissive map; ours is derived):
    fire: the base colour itself where it is bright and warm; storm: grey mask of the brightest streaks."""
    bc = np.asarray(Image.open(S.out_dir(unit) / "basecolor.png").convert("RGB")).astype(np.float32) / 255.0
    lum = bc @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    if unit == "h3_fire_elemental":
        warm = np.clip((bc[..., 0] - bc[..., 2]) * 1.5, 0, 1)
        m = smoothstep(0.30, 0.75, lum) * warm
        out = bc * m[..., None]
    else:
        m = smoothstep(0.30, 0.60, lum)
        out = np.repeat(m[..., None], 3, -1)
    Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).save(dest)
    return float(m.mean())


def native_body(name, yaw):
    nd = VS / "native" / name
    meta = json.loads((nd / "meta.json").read_text())
    d = np.load(nd / "mesh.npz")
    bones = json.loads((nd / "bones.json").read_text())["bones"]
    dest = PROJECT / ASSET_ROOT / f"native_{name}"
    dest.mkdir(parents=True, exist_ok=True)
    mats = []
    for i, m in enumerate(meta["materials"]):
        stage_file(nd / f"mat_{i}.png", dest / f"mat_{i}.png")
        emi = ""
        if "HEX_EMISSION_MAP_ENABLED" in (m["keywords"] or []) and (nd / f"emi_{i}.png").exists():
            stage_file(nd / f"emi_{i}.png", dest / f"emi_{i}.png")
            emi = f"native_{name}/emi_{i}.png"
        f = m["floats"]
        mats.append({"albedo": f"native_{name}/mat_{i}.png", "emission": emi,
                     "emissionColor": m["colors"].get("_EmissionColor", [0, 0, 0, 1])[:3],
                     "emissionMin": f.get("_EmissionMinPower", 1.0), "blinkSpeed": f.get("_EmissionBlinkSpeed", 0.0),
                     "blinkPower": f.get("_EmissionBlinkPower", 0.0),
                     "cutoff": f.get("_AlphaCutoff", 0.5) if "HEX_ALPHA_CLIP_ENABLED" in (m["keywords"] or []) else 0.0})
    pos, nrm, uv, tri, mat = d["pos"], d["nrm"], d["uv"], d["tri"], d["mat"]
    binp = VS / "lab" / f"native_{name}.bin"
    with open(binp, "wb") as fh:
        fh.write(struct.pack("<ii", len(pos), len(mats)))
        fh.write(pos.astype("<f4").tobytes())
        fh.write(nrm.astype("<f4").tobytes())
        fh.write(uv.astype("<f4").tobytes())
        for s in range(len(mats)):
            # only Hex/Lit submeshes are the body; effect shells (e.g. the griffin's magic/Fresnel ability shell) are
            # drawn by their timeline in game, so the static reference leaves them out
            keep = meta["materials"][s].get("shader") == "Hex/Lit"
            idx = (tri[mat == s] if keep else tri[:0]).reshape(-1).astype("<i4")
            fh.write(struct.pack("<i", len(idx)))
            fh.write(idx.tobytes())
    body = {"kind": "native", "nativeMeshFile": str(binp), "nativeMats": mats, "bodyYawDeg": yaw,
            "bones": [{"name": k, "m": [x for row in v for x in row]} for k, v in bones.items()]}
    q = q_yaw(yaw)
    r = np.array([[1 - 2 * (q[1] ** 2), 0, 2 * q[1] * q[3]], [0, 1, 0], [-2 * q[1] * q[3], 0, 1 - 2 * (q[1] ** 2)]])
    p2 = pos @ r.T
    centre = ((p2.min(0) + p2.max(0)) / 2).tolist()
    return body, bones, centre, float(pos[:, 1].max() - pos[:, 1].min())


# ------------------------------------------------------------------ panels
def cam_frame(unit):
    cam = json.loads((S.RETARGET / unit / f"{unit}_def_retarget.blend.spritecam.json").read_text())
    ppu = cam["pxPerUnit"]
    right, up, fwd = np.array(cam["right"]), np.array(cam["up"]), np.array(cam["forward"])
    c_b = right * ((cam["size"][0] * 0.5 - cam["offset"][0]) / ppu) + up * ((cam["offset"][1] - cam["size"][1] * 0.5) / ppu)
    return {"camRight": B2U(right), "camUp": B2U(up), "camForward": B2U(fwd), "camCentre": B2U(c_b),
            "orthoSize": cam["size"][1] * 0.5 / ppu, "width": cam["size"][0] * SCALE, "height": cam["size"][1] * SCALE}


def face_yaw(camf):
    """yaw that turns a vanilla unit's forward (+X in the probed prefabs) to screen-right, as HoMM3 attackers face."""
    d = np.array(camf["camRight"], float)
    d[1] = 0
    d /= np.linalg.norm(d)
    return math.degrees(math.atan2(-d[2], d[0]))


def clip_plan(unit, names, idle_cycles=2):
    seg = S.clip_segments(unit)
    out = []
    for n in names:
        k = len(seg[n]["defFrames"])
        loop = n in ("Unit_Idle", "Unit_Move")
        dur = k / 12.0 * (idle_cycles if loop else 1) + (0 if loop else 0.25)
        out.append({"name": n, "keys": k, "frames": int(round(dur * FPS)), "frameStep": 1.0 / FPS, "boilCells": [],
                    "loop": loop})
    return out


def stage_glb(unit):
    dest = PROJECT / ASSET_ROOT / unit
    dest.mkdir(parents=True, exist_ok=True)
    stage_file(S.glb_path(unit), dest / f"{unit}_vstyle.glb")
    stage_file(S.out_dir(unit) / "basecolor.png", dest / "basecolor.png")
    return dest, f"{ASSET_ROOT}/{unit}/{unit}_vstyle.glb"


def old_panel(unit, camf, clips, sun):
    """(OLD panel, label) from the unit's HoMM3 look manifest. The label names what OLD actually shows: a unit with
    no vfx manifest gets a labelled plain body, and a unitPlane defFlipbook (plane breath) is drawn from its plane
    sheet as a view billboard at the anchor bone, which the label says (in game it is two unit-root crossed cards,
    and its few displaced specks are not drawn)."""
    dest, glb = stage_glb(unit)
    vdir = S.out_dir(unit) / "vfx"
    if not (vdir / "vfx_manifest.json").is_file():
        body = {"kind": "glb", "glbAssetPath": glb, "texture": f"{unit}/basecolor.png", "emissionTex": "",
                "emissionColor": [0, 0, 0], "cellST": [], "emissionMin": 0, "blinkSpeed": 0, "blinkPower": 0}
        return ({"id": "old", "body": body, "clips": json.loads(json.dumps(clips)), "effects": [], "flipbooks": [],
                 "oldLights": [], "sunTravelUnity": sun, "warmupS": 1.0, **camf},
                "OLD: body only (no HoMM3 vfx manifest for this unit)")
    man = json.loads((vdir / "vfx_manifest.json").read_text())
    kinds = sorted({ly["type"] for ly in man["layers"].values()})
    planes = []
    atlas = next((v for v in man["layers"].values() if v["type"] == "uvAtlas"), None)
    body = {"kind": "glb", "glbAssetPath": glb, "texture": f"{unit}/basecolor.png", "emissionTex": "",
            "emissionColor": [0, 0, 0], "cellST": [], "emissionMin": 0, "blinkSpeed": 0, "blinkPower": 0}
    cl = json.loads(json.dumps(clips))
    if atlas:
        stage_file(vdir / atlas["atlas"], dest / atlas["atlas"])
        body["texture"] = f"{unit}/{atlas['atlas']}"
        body["cellST"] = [x for st in atlas["cellST"] for x in st]
        for c in cl:
            c["boilCells"] = [x["cell"] for x in atlas["clips"].get(c["name"], [])]
    flips, lights = [], []
    spec = S.load(unit)
    for lid, ly in man["layers"].items():
        if ly["type"] == "defFlipbook":
            for cn, c in ly["clips"].items():
                if not c.get("anchorBone") or all(k["cell"] < 0 for k in c["keys"]):
                    continue
                sheet = c["sheet"]
                if c.get("render") == "unitPlane":
                    sheet = c["unitPlane"]["sheet"]
                    planes.append(f"{lid}/{cn}")
                if not sheet:
                    raise SystemExit(f"{unit}: defFlipbook {lid}/{cn} has no sheet the lab knows (render {c.get('render')})")
                stage_file(vdir / sheet, dest / sheet)
                flips.append({"clip": cn, "bone": c["anchorBone"], "sheet": f"{unit}/{sheet}", "tilesX": c["tilesX"],
                              "tilesY": c["tilesY"], "sizeX": c["sizeUnits"][0], "sizeY": c["sizeUnits"][1],
                              "cells": [k["cell"] for k in c["keys"]]})
        if ly["type"] == "effectLight":
            sl = next(l for l in spec["vfx"]["layers"] if l["id"] == lid)
            for c in cl:
                ints = [k["intensity"] for k in ly["clips"].get(c["name"], [])] or [float(ly.get("floor", 0.0))] * c["keys"]
                lights.append({"clip": c["name"], "bone": sl["anchor"]["bone"],
                               "towardCamera": float(sl["anchor"].get("towardCameraU", 0.0)), "range": float(ly["range"]),
                               "rgbLinear": [float(x) for x in srgb_to_lin(ly["rgb"])], "intensity": ints})
    name = "OLD (current: " + " + ".join(kinds) + ")"
    if planes:
        name += "; plane breath as a view billboard, not its in-game crossed cards (" + ", ".join(planes) + ")"
    return ({"id": "old", "body": body, "clips": cl, "effects": [], "flipbooks": flips, "oldLights": lights,
             "sunTravelUnity": sun, "warmupS": 1.0, **camf}, name)


def new_panel(unit, camf, clips, sun, yaw):
    dest, glb = stage_glb(unit)
    cover = emission_map(unit, dest / "emission.png")
    phx = json.loads((VS / "native/phoenix/bones.json").read_text())["bones"]
    if unit == "h3_fire_elemental":
        body = {"kind": "glb", "glbAssetPath": glb, "texture": f"{unit}/basecolor.png", "emissionTex": f"{unit}/emission.png",
                "emissionColor": [2.2, 1.1, 0.55], "cellST": [], "emissionMin": 0.8, "blinkSpeed": 1.0, "blinkPower": 0.3}
        fire01 = node_index("wrist", "Fire_01")
        effects = [eff(f"flame_{b}", "wrist", b, keepPS=[fire01], zeroChildPos=True, emitUp=True, loopAll=True,
                       alwaysOn=True, scale=0.5, rateMul=r)
                   for b, r in (("Head", 0.6), ("Spine2", 0.6), ("LeftForeArm", 0.4), ("RightForeArm", 0.4))]
        effects.append(eff("embers", "rise", "Spine2", keepPS=[node_index("rise", "Fire_sparks")], loopAll=True,
                           alwaysOn=True, scale=0.6, rateMul=8.0 / node_rate("rise", "Fire_sparks")))
        # the fist: flame while the HoMM3 punch flipbook shows (keys 3..11), then the phoenix hit at the first fire key
        effects.append(eff("fist_flame", "wrist", "RightHand", keepPS=[fire01], zeroChildPos=True, emitUp=True, loopAll=True,
                           scale=0.5, rateMul=1.5, triggers=[{"clip": "Unit_AttackFront", "time": key_t(3)}],
                           stops=[{"clip": "Unit_AttackFront", "time": key_t(11)}]))
        keep = [node_index("hit", p) for p in ("FlashLight", "Fire_spark_01", "Fire_spark_02", "Fire_spark_03",
                                               "Fire_stretch_01", "Fire_stretch_02", "Fire_stretch_03",
                                               "sparks_01", "sparks_02", "sparks_03")]
        rot = q_mul(q_yaw(yaw), q_from_m(phx["Phoenix_upg_hit_fire_Root"]))
        effects.append(eff("punch_hit", "hit", "RightHand", keepPS=keep, rootWorldRot=rot, scale=0.55,
                           anchorNode=node_index("hit", "Fire_spark_01"),
                           triggers=[{"clip": "Unit_AttackFront", "time": key_t(4)}]))
    else:
        body = {"kind": "glb", "glbAssetPath": glb, "texture": f"{unit}/basecolor.png", "emissionTex": f"{unit}/emission.png",
                "emissionColor": [0.9, 1.5, 2.4], "cellST": [], "emissionMin": 0.7, "blinkSpeed": 1.5, "blinkPower": 0.5}
        cyan = [0.55, 0.85, 1.0]
        idle_keep = [node_index("angel", p) for p in ("Energy_01", "Energy_02", "Smoke")]
        effects = [eff(f"energy_{b}", "angel", b, keepPS=idle_keep, zeroChildPos=True, loopAll=True, alwaysOn=True,
                       scale=0.35, recolor=cyan) for b in ("LeftHand", "RightHand", "Head")]
        crackle = [node_index("strike", "Impact/" + p) for p in ("Lightning_sparks_small_01", "Lightning_sparks_small_02")]
        effects.append(eff("crackle", "strike", "Spine2", keepPS=crackle, scale=0.3, anchorNode=node_index("strike", "Impact"),
                           triggers=[{"clip": "Unit_Idle", "time": t} for t in (0.15, 0.55, 1.05, 1.4)]))
        impact = [node_index("strike", "Impact/" + p) for p in
                  ("Lightning_sparks", "Lightning_trails", "Lightning_sphere", "Flash_01", "Energy", "Flash_light_01",
                   "Flash_light_02", "Sparks_01", "Sparks_02", "Sparks_03", "Lightning_sparks_small_01",
                   "Lightning_sparks_small_02", "Lightning_sparks_small_03")]
        anchor = node_index("strike", "Impact/Flash_01")
        effects.append(eff("attack_bolt", "strike", "LeftHand", keepPS=impact, scale=0.45, anchorNode=anchor,
                           triggers=[{"clip": "Unit_AttackFront", "time": key_t(2)}]))
        effects.append(eff("shoot_bolt", "strike", "Spine2", keepPS=impact, scale=0.45, anchorNode=anchor,
                           triggers=[{"clip": "Unit_ShootFront", "time": key_t(1)}, {"clip": "Unit_ShootFront", "time": key_t(3)}]))
    return {"id": "new", "body": body, "clips": clips, "effects": effects, "flipbooks": [], "oldLights": [],
            "sunTravelUnity": sun, "warmupS": 1.0, **camf}, cover


def vanilla_panel(unit, camf, sun, yaw):
    """The vanilla reference: phoenix (fire page) or sentinel (storm page), static idle-t0 pose, own emission, own
    effects on their own authored transforms, turned to face screen-right like our unit."""
    if unit == "h3_fire_elemental":
        body, bones, centre, h = native_body("phoenix", yaw)
        effects = []
        for inst in ("Phoenix_upg_ability_fire_01", "Phoenix_upg_ability_fire_02"):
            s = float(np.linalg.norm(np.array(bones[inst])[:3, 0]))
            effects.append(eff(inst, "wrist", inst, scale=s, loopAll=True, alwaysOn=True))
        effects.append(eff("hit", "hit", "Phoenix_upg_hit_fire_Root", scale=1.0,
                           triggers=[{"clip": "vanilla", "time": 0.3}, {"clip": "vanilla", "time": 1.4}]))
        title = "vanilla phoenix: wing fire + melee hit fire"
    else:
        body, bones, centre, h = native_body("sentinel", yaw)
        effects = [eff(inst, "angel", inst, scale=float(np.linalg.norm(np.array(bones[inst])[:3, 0])), loopAll=True,
                       alwaysOn=True)
                   for inst in bones if inst.startswith("Angel_idle_SmallWing")]
        effects.append(eff("strike", "strike", "__body", scale=1.0, pos=[0.9, 0, 0],
                           triggers=[{"clip": "vanilla", "time": 0.3}, {"clip": "vanilla", "time": 1.4}]))
        title = "vanilla sentinel idle + vanilla lightning-strike spell"
    cf = dict(camf)
    shift = np.array(centre) - np.array(camf["camCentre"])
    fwd = np.array(camf["camForward"])
    cf["camCentre"] = (np.array(camf["camCentre"]) + shift - fwd * float(shift @ fwd)).tolist()
    clips = [{"name": "vanilla", "keys": 24, "frames": int(2.4 * FPS), "frameStep": 1.0 / FPS, "boilCells": [], "loop": True}]
    return {"id": "vanilla", "body": body, "clips": clips, "effects": effects, "flipbooks": [], "oldLights": [],
            "sunTravelUnity": sun, "warmupS": 1.0, **cf}, title, h


UNIT_CLIPS = {"h3_fire_elemental": ["Unit_Idle", "Unit_AttackFront"],
              "h3_storm_elemental": ["Unit_Idle", "Unit_AttackFront", "Unit_ShootFront"]}


def run_unity(unit, lib_path, out: Path, timeout):
    camf = cam_frame(unit)
    sun = sun_travel_unity(unit)
    yaw = face_yaw(camf)
    tier = "handbuilt"
    if unit in HANDBUILT:
        clips = clip_plan(unit, UNIT_CLIPS[unit])
        new, cover = new_panel(unit, camf, clips, sun, yaw)
        van, title, vh = vanilla_panel(unit, camf, sun, yaw)
    else:
        clips = clip_plan(unit, spec_clips(unit_spec(unit)[0]))
        new, cover, tier = spec_new_panel(unit, camf, clips, sun)
        van, title, vh = ref_vanilla_panel(unit, camf, sun, yaw)
    old, old_title = old_panel(unit, camf, clips, sun)
    (out / "renders").mkdir(parents=True, exist_ok=True)
    job = {"schema": "homm3_vanilla_style_lab.v1", "assetRoot": ASSET_ROOT, "materialLib": str(lib_path),
           "outDir": str(out / "renders"), "requireCompleteEffects": unit == "h3_water_elemental",
           "panels": [old, new, van]}
    sp = out / "lab_spec.json"
    sp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    (out / "panel_meta.json").write_text(json.dumps({"vanillaTitle": title, "oldTitle": old_title, "vanillaHeight": vh, "faceYawDeg": yaw,
                                                     "emissionCover": cover, "specTier": tier}, indent=1))
    gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/launch_guard.py")], capture_output=True,
                          text=True, timeout=900)
    print("launch_guard", gate.returncode, gate.stdout[-300:], gate.stderr[-300:])
    if gate.returncode:
        return gate.returncode
    log = out / "unity_lab.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3VanillaStyleSpec", str(sp),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3VanillaStyleVfxLab.RunFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="vfx_vanilla_style_lab", timeout_s=timeout, direct=UNITY_DIRECT)
    print(done.stdout[-1500:], done.stderr[-1500:])
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for line in text.splitlines():
        if "HOMM3_VSTYLE" in line or "error CS" in line or "Exception" in line:
            print(line[:300])
    ok = done.returncode == 0 and "HOMM3_VSTYLE_LAB_OK" in text
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


# ------------------------------------------------------------------ compose
def read_bin(p: Path, w, h):
    return np.frombuffer(p.read_bytes(), np.float16).astype(np.float32).reshape(h, w, 4)[::-1]


def _down(x):
    h, w = x.shape[0] // 2 * 2, x.shape[1] // 2 * 2
    x = x[:h, :w]
    return 0.25 * (x[0::2, 0::2] + x[1::2, 0::2] + x[0::2, 1::2] + x[1::2, 1::2])


def _blur(x):
    k = np.array([1, 2, 1], np.float32) / 4
    p = np.pad(x, ((1, 1), (1, 1), (0, 0)), mode="edge")
    y = k[0] * p[:, :-2] + k[1] * p[:, 1:-1] + k[2] * p[:, 2:]
    return k[0] * y[:-2] + k[1] * y[1:-1] + k[2] * y[2:]


def _up(x, shape):
    y = np.repeat(np.repeat(x, 2, 0), 2, 1)
    y = np.pad(y, ((0, max(0, shape[0] - y.shape[0])), (0, max(0, shape[1] - y.shape[1])), (0, 0)), mode="edge")
    return _blur(y[:shape[0], :shape[1]])


def bloom(rgb, threshold=1.0, knee=0.107, intensity=2 ** 0.3 - 1, levels=3):
    """PPv2-like: quadratic soft-knee prefilter at half res, `levels` down/up pyramid, additive upsample, added
    to the frame at the linear intensity (PPv2 maps the UI 3.0 to 2^(3/10)-1)."""
    kn = threshold * knee + 1e-5
    br = rgb.max(-1, keepdims=True)
    rq = np.clip(br - (threshold - kn), 0, 2 * kn)
    rq = 0.25 / kn * rq * rq
    pre = rgb * np.maximum(rq, br - threshold) / np.maximum(br, 1e-4)
    mips = [_blur(_down(pre))]
    for _ in range(levels):
        mips.append(_blur(_down(mips[-1])))
    acc = mips[-1]
    for m in reversed(mips[:-1]):
        acc = m + _up(acc, m.shape)
    return rgb + _up(acc, rgb.shape) * intensity


def to_srgb8(lin):
    c = np.clip(lin, 0, 1)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def finish(raw):
    bg = srgb_to_lin(GROUND).astype(np.float32)
    rgb = raw[..., :3] + bg * (1 - np.clip(raw[..., 3:4], 0, 1))
    return to_srgb8(bloom(rgb))


def compose(unit, out: Path):
    job = json.loads((out / "lab_spec.json").read_text())
    meta = json.loads((out / "panel_meta.json").read_text())
    r = out / "renders"
    P = {p["id"]: p for p in job["panels"]}
    w, h = P["old"]["width"], P["old"]["height"]
    frames = {pid: {c["name"]: [read_bin(r / pid / f"{c['name']}_{i:03d}.bin", w, h) for i in range(c["frames"])]
                    for c in P[pid]["clips"]} for pid in P}
    occ = np.zeros((h, w), bool)
    for pid in P:
        for fs in frames[pid].values():
            for f in fs:
                occ |= (f[..., 3] > 0.02) | (f[..., :3].max(-1) > 0.03)
    ys, xs = np.nonzero(occ)
    pad = 16
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, w)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, h)
    fin = lambda f: Image.fromarray(finish(f[y0:y1, x0:x1]))
    names = {"old": meta.get("oldTitle", "OLD (current: uvAtlas + DEF flipbook + effectLight)"),
             "new": "NEW (vanilla-style %s; LAB RENDER, not in game)" % meta.get("specTier", "handbuilt"),
             "vanilla": meta["vanillaTitle"]}
    van = frames["vanilla"]["vanilla"]
    cw, ch = x1 - x0, y1 - y0
    video = []
    gi = 0
    for c in P["old"]["clips"]:
        n = c["frames"]
        cols = sorted(set(np.linspace(0, n - 1, 8).round().astype(int).tolist()))
        sheet = Image.new("RGB", (cw * len(cols), (ch + 14) * 3), (30, 30, 30))
        for ri, pid in enumerate(("old", "new", "vanilla")):
            for j, i in enumerate(cols):
                src = frames[pid][c["name"]][i] if pid != "vanilla" else van[(gi + i) % len(van)]
                t = i / FPS
                sheet.paste(label(fin(src), (names[pid] + "  " if j == 0 else "") + f"{c['name']} t={t:.2f}s"),
                            (j * cw, ri * (ch + 14)))
        sheet.save(out / f"sheet_{c['name']}.png")
        reps = 2 if c["loop"] else 2
        for _ in range(reps):
            for i in range(n):
                fr = Image.new("RGB", (cw * 3, ch + 14), (30, 30, 30))
                for ri, pid in enumerate(("old", "new", "vanilla")):
                    src = frames[pid][c["name"]][i] if pid != "vanilla" else van[gi % len(van)]
                    fr.paste(label(fin(src), f"{names[pid] if pid != 'vanilla' else 'vanilla ref'}  {c['name'] if pid != 'vanilla' else ''}"),
                             (ri * cw, 0))
                video.append(fr)
                gi += 1
    write_video(video, out / "compare.mp4", fps=FPS)
    gif = out / "compare.gif"
    if gif.exists():
        gif.unlink()   # write_video also writes a gif; the mp4 is the deliverable
    # hero still: the attack frame with the most HDR energy in the new panel, next to old and vanilla peaks
    def hdr(f):   # HDR energy, with particle coverage as the tie-break for the non-blooming (feather) effects
        return float(np.clip(f[..., :3] - 1, 0, None).sum()) + 1e-3 * float(f[..., 3].sum())
    atk = max(frames["new"], key=lambda cn: max(hdr(f) for f in frames["new"][cn]))
    energy = [hdr(f) for f in frames["new"][atk]]
    i = int(np.argmax(energy))
    ve = [float(np.clip(f[..., :3] - 1, 0, None).sum()) for f in van]
    vi = int(np.argmax(ve))
    hero = Image.new("RGB", (cw * 3, ch + 14), (30, 30, 30))
    hero.paste(label(fin(frames["old"][atk][i]), f"OLD  {atk} t={i / FPS:.2f}s"), (0, 0))
    hero.paste(label(fin(frames["new"][atk][i]), f"NEW  {atk} t={i / FPS:.2f}s"), (cw, 0))
    hero.paste(label(fin(van[vi]), f"{meta['vanillaTitle']}  t={vi / FPS:.2f}s"), (2 * cw, 0))
    hero.save(out / "hero.png")
    idle = Image.new("RGB", (cw * 3, ch + 14), (30, 30, 30))
    k = len(frames["new"]["Unit_Idle"]) // 3
    for ri, pid in enumerate(("old", "new", "vanilla")):
        src = frames[pid]["Unit_Idle"][k] if pid != "vanilla" else van[5]
        idle.paste(label(fin(src), names[pid] + "  idle"), (ri * cw, 0))
    idle.save(out / "idle.png")
    stats = {"heroClip": atk}
    for pid in P:
        allf = [f for fs in frames[pid].values() for f in fs]
        stats[pid] = {"peakLinear": round(float(max(f[..., :3].max() for f in allf)), 2),
                      "meanHdrPxAbove1": round(float(np.mean([(f[..., :3].max(-1) > 1).sum() for f in allf])), 1)}
    (out / "compose_stats.json").write_text(json.dumps(stats, indent=1))
    print("composed", out, stats)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default="h3_fire_elemental,h3_storm_elemental")
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--compose-only", action="store_true")
    ap.add_argument("--prune-renders", action="store_true", help="delete the raw frames after a successful compose")
    a = ap.parse_args()
    lib = None if a.compose_only else stage_common()
    for unit in a.units.split(","):
        out = VS / "lab" / unit
        out.mkdir(parents=True, exist_ok=True)
        if not a.compose_only:
            rc = run_unity(unit, lib, out, a.timeout)
            if rc:
                return rc
        compose(unit, out)
        if a.prune_renders and (out / "renders").is_dir():
            shutil.rmtree(out / "renders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
