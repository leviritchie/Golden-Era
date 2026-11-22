"""Elemental Fusion runtime fluid bodies: writes OfflineUnlockMod/fluid_fusion/fluid_fusion.json (user 2026-11-20:
"Proceed with the full implementation" after the Steam prototype passed in game).

The fused body never exists as an asset. The plugin (Homm3FluidFusionRuntime.cs) assembles it at spawn from per-parent
seed files (<element>.fluidseeds, exported by V:/olden_port_work/elemental_fusion/fluid/fluid_lab.py seeds_all) and this
config, which holds only:
  - "elements": one row per elemental (15): its fluid behaviour (family physics + variant tweaks) and surface look
    (albedo/emission measured from the elemental's own basecolor texture, so the colour stays the HoMM3 unit's);
  - "units": per fusion, the host element (shape + rig) and the guests that infuse it with their share of particles.

Stage-1 pairs (105): host = the pair's host, guest infuses 30%.
Stage-2 recipes (37, parents are fusions): host = the host fusion's host; layers = host fusion's guest 30%, guest
fusion's host 30%, guest fusion's guest 15% (an element already present merges, adding its share, capped at 45%).

    python tools/conflux_fusion/fluid_fusion_config.py [--check]
"""
from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
import spec as S  # noqa: E402

FUSION = ROOT / "custom_factions/conflux_fusion/fusion_config.json"
OUT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/fluid_fusion/fluid_fusion.json"
SEEDS = OUT.parent

# game sid variant -> lab sid short name, per family line (fusion_config.json "lines" order: base, upg, upg_alt)
SHORT = {"air": ["air", "storm", "hurricane"], "water": ["water", "ice", "frost"], "fire": ["fire", "energy", "plasma"],
         "earth": ["earth", "magma", "lava"], "psychic": ["psychic", "magic", "astral"]}

# family physics (temperature: 0 neutral, 1 flame-hot, negative cold; water-family boils into steam above boilTemp)
FAMILY = {
    "air": dict(homeStiffness=22, homeDamping=3.5, viscosity=0.06, cohesion=0.15, repulsion=0.5, buoyancy=0.4,
                baseTemp=0.1, tempRelax=2, conductivity=2, boilTemp=999, boilRate=0, gasLife=1, jitter=0.7),
    "water": dict(homeStiffness=45, homeDamping=6, viscosity=0.25, cohesion=0.6, repulsion=0.5, buoyancy=0,
                  baseTemp=0, tempRelax=1.5, conductivity=3, boilTemp=0.3, boilRate=10, gasLife=1.1, jitter=0.15),
    "fire": dict(homeStiffness=25, homeDamping=4, viscosity=0.05, cohesion=0.2, repulsion=0.5, buoyancy=2.5,
                 baseTemp=1, tempRelax=3, conductivity=3, boilTemp=999, boilRate=0, gasLife=1, jitter=0.5),
    "earth": dict(homeStiffness=90, homeDamping=10, viscosity=0.8, cohesion=0.9, repulsion=0.6, buoyancy=0,
                  baseTemp=0, tempRelax=1, conductivity=1, boilTemp=999, boilRate=0, gasLife=1, jitter=0.02),
    "psychic": dict(homeStiffness=35, homeDamping=5, viscosity=0.3, cohesion=0.5, repulsion=0.5, buoyancy=0.15,
                    baseTemp=0, tempRelax=1.5, conductivity=2, boilTemp=999, boilRate=0, gasLife=1, jitter=0.35),
}
# variant tweaks on top of the family row
VARIANT = {
    "storm": dict(homeStiffness=20, jitter=1.0), "hurricane": dict(homeStiffness=18, viscosity=0.04, jitter=1.3),
    "ice": dict(homeStiffness=70, homeDamping=8, viscosity=0.6, cohesion=0.8, baseTemp=-0.6, tempRelax=1.0, boilTemp=0.05, boilRate=6, jitter=0.05),
    "frost": dict(homeStiffness=60, homeDamping=7, viscosity=0.5, cohesion=0.75, baseTemp=-0.8, tempRelax=1.0, boilTemp=0.1, boilRate=6, jitter=0.1),
    "energy": dict(homeStiffness=22, viscosity=0.04, cohesion=0.15, buoyancy=2.0, baseTemp=1.2, jitter=0.8),
    "plasma": dict(homeStiffness=20, viscosity=0.03, cohesion=0.12, buoyancy=1.6, baseTemp=1.4, jitter=1.0),
    "magma": dict(homeStiffness=70, homeDamping=8, viscosity=0.7, cohesion=0.85, buoyancy=0.2, baseTemp=0.9, conductivity=2, jitter=0.08),
    "lava": dict(homeStiffness=55, homeDamping=7, viscosity=0.55, cohesion=0.8, buoyancy=0.3, baseTemp=1.1, conductivity=2, jitter=0.12),
    "magic": dict(homeStiffness=32, viscosity=0.25, cohesion=0.45, buoyancy=0.2, jitter=0.45),
    "astral": dict(homeStiffness=28, viscosity=0.2, cohesion=0.4, buoyancy=0.3, jitter=0.55),
}
# surface look: glow strength (emission = the texture's own hue at this strength), triplanar tile, upward scroll,
# and point-light intensity for the elements that light their surroundings (0 = none)
LOOK = {
    "air": (0.15, 1.4, 0.4, 0), "storm": (0.3, 1.4, 0.5, 0), "hurricane": (0.25, 1.4, 0.6, 0),
    "water": (0.45, 1.6, 0.0, 0), "ice": (0.4, 1.8, 0.0, 0), "frost": (0.45, 1.8, 0.0, 0),
    "fire": (1.8, 2.4, 0.6, 2.2), "energy": (2.0, 2.4, 0.7, 2.4), "plasma": (2.0, 2.4, 0.8, 2.4),
    "earth": (0.05, 2.0, 0.0, 0), "magma": (0.9, 2.0, 0.1, 1.6), "lava": (1.2, 2.0, 0.15, 1.8),
    "psychic": (0.7, 1.6, 0.15, 0), "magic": (0.8, 1.6, 0.2, 0), "astral": (0.9, 1.6, 0.25, 0),
}
# Fire x Water steam prototype colours (approved in game 2026-11-20) are kept as measured overrides
ALBEDO_OVERRIDE = {"water": [0.32, 0.6, 0.85], "fire": [1.0, 0.55, 0.2]}
EMISSION_OVERRIDE = {"water": [0.12, 0.42, 0.62], "fire": [1.7, 0.7, 0.18]}
# Fluid shader look (tools/conflux_fusion/fluid_shader/Homm3FluidElement.shader): keys are the shader's own property
# names, so the plugin and the lab apply them generically. Family row, then variant tweaks. Colours are linear rgb.
SURF_FAMILY = {
    "water": {"_NoiseScale": 4.5, "_Flow": [0, -0.15, 0], "_Warp": 0.9, "_Detail": 1.1, "_Albedo2": [0.06, 0.22, 0.45], "_Spec": 0.9, "_Gloss": 90,
              "_FresnelColor": [0.5, 0.72, 0.95], "_FresnelPower": 3.5, "_Translucency": 0.5},
    "air": {"_NoiseScale": 2.5, "_Flow": [0, 0.6, 0], "_Warp": 1.2, "_Detail": 0.3, "_Bands": 0.7, "_BandSpin": 3, "_Spec": 0.2,
            "_Gloss": 20, "_FresnelColor": [0.85, 0.92, 1.0], "_FresnelPower": 2.0, "_Translucency": 0.7},
    "fire": {"_NoiseScale": 4.5, "_Flow": [0, 1.2, 0], "_Warp": 1.4, "_Detail": 0.6, "_TempGlow": 1.6, "_TempFrom": 0.55,
             "_HotColor": [1.5, 0.6, 0.15], "_Spec": 0.1, "_Gloss": 12, "_FresnelColor": [0.9, 0.3, 0.06], "_FresnelPower": 2.0,
             "_Translucency": 0.4},
    "earth": {"_NoiseScale": 5, "_Flow": [0, 0, 0], "_Warp": 0.4, "_Detail": 1.2, "_Facet": 0.6, "_Cells": 0.6, "_CellScale": 4,
              "_CrackWidth": 0.07, "_Spec": 0.1, "_Gloss": 12, "_FresnelColor": [0.3, 0.25, 0.2], "_FresnelPower": 4,
              "_Translucency": 0.15},
    "psychic": {"_NoiseScale": 3, "_Flow": [0, 0.25, 0], "_Warp": 1.4, "_Detail": 0.4, "_Irid": 0.6, "_Pulse": 2.5, "_Spec": 0.5,
                "_Gloss": 40, "_FresnelPower": 2.5, "_Translucency": 0.4},
}
SURF_VARIANT = {
    # ice / frost: the basecolor mean is a dark navy that read as muddy (lab look_b); pale glassy body, deep-blue lows
    "ice": {"_Albedo": [0.6, 0.78, 0.95], "_Albedo2": [0.22, 0.4, 0.68], "_Translucency": 0.6, "_NoiseScale": 3, "_Flow": [0, 0, 0], "_Warp": 0.3, "_Detail": 0.3, "_Facet": 0.75, "_Cells": 0.35, "_CellScale": 5,
            "_CrackWidth": 0.06, "_CrackGlow": 0.3, "_HotColor": [0.6, 0.85, 1.2], "_Spec": 1.2, "_Gloss": 120,
            "_FresnelColor": [0.7, 0.85, 1.0], "_FresnelPower": 2.5, "_Sparkle": 1.0},
    "frost": {"_Albedo": [0.72, 0.9, 0.95], "_Albedo2": [0.3, 0.55, 0.62], "_Translucency": 0.6, "_NoiseScale": 3, "_Flow": [0, 0, 0], "_Warp": 0.4, "_Detail": 0.4, "_Facet": 0.5, "_Cells": 0.25, "_CellScale": 6,
              "_CrackWidth": 0.05, "_CrackGlow": 0.25, "_HotColor": [0.7, 0.95, 1.1], "_Spec": 1.0, "_Gloss": 100,
              "_FresnelColor": [0.75, 0.95, 1.0], "_FresnelPower": 2.5, "_Sparkle": 1.3},
    "storm": {"_Bands": 0.8, "_BandSpin": 4, "_Pulse": 5},
    "hurricane": {"_Bands": 1.0, "_BandSpin": 6, "_Flow": [0, 0.9, 0]},
    "energy": {"_Flow": [0, 0.9, 0], "_HotColor": [1.0, 1.2, 2.0], "_Pulse": 6, "_FresnelColor": [0.4, 0.5, 1.2]},
    "plasma": {"_HotColor": [1.8, 1.1, 0.4], "_Pulse": 9, "_Irid": 0.2},
    "magma": {"_Cells": 0.8, "_CrackGlow": 2.0, "_HotColor": [2.4, 0.8, 0.15], "_Flow": [0, -0.05, 0], "_TempGlow": 0.8},
    "lava": {"_Cells": 0.5, "_CrackGlow": 3.0, "_HotColor": [2.8, 0.9, 0.15], "_Flow": [0, -0.25, 0], "_Warp": 0.9, "_Facet": 0.2,
             "_TempGlow": 1.5},
    "magic": {"_Irid": 0.8, "_Pulse": 3.5},
    "astral": {"_Irid": 0.5, "_Sparkle": 1.5, "_Flow": [0, 0.15, 0]},
}
# sprites each element sheds (FluidFusionCore SpriteKind); colour None = derived from the element's own colours
EMIT = {
    "water": None,
    "ice": dict(kind="snow", rate=0.25, life=1.4, size=1.6, color=[0.85, 0.92, 1.0, 0.9]),
    "frost": dict(kind="snow", rate=0.4, life=1.4, size=1.6, color=[0.8, 0.95, 1.0, 0.9]),
    "air": dict(kind="wisp", rate=0.25, life=1.2, size=3.0, color=[0.9, 0.95, 1.0, 0.3]),
    "storm": dict(kind="spark", rate=0.06, life=0.25, size=1.2, color=[1.3, 1.4, 1.8, 1.0]),
    "hurricane": dict(kind="wisp", rate=0.4, life=1.1, size=3.0, color=[0.85, 0.9, 0.95, 0.3]),
    "fire": dict(kind="flame", rate=0.15, life=0.5, size=2.8, color=[1.4, 0.6, 0.18, 1.0], hot=True),
    "energy": dict(kind="spark", rate=0.12, life=0.3, size=1.0, color=[1.4, 1.6, 2.6, 1.0]),
    "plasma": dict(kind="ember", rate=0.3, life=0.7, size=1.0, color=[2.5, 1.6, 0.6, 1.0], hot=True),
    "earth": dict(kind="dust", rate=0.05, life=1.2, size=1.4, color=None),
    "magma": dict(kind="ember", rate=0.12, life=1.0, size=1.0, color=[2.2, 0.9, 0.25, 1.0], hot=True),
    "lava": dict(kind="ember", rate=0.2, life=1.0, size=1.0, color=[2.6, 1.0, 0.25, 1.0], hot=True),
    "psychic": dict(kind="mote", rate=0.08, life=1.6, size=1.6, color=None),
    "magic": dict(kind="mote", rate=0.12, life=1.6, size=1.6, color=None),
    "astral": dict(kind="mote", rate=0.15, life=1.8, size=1.6, color=None),
}
# surface base-emission gain per family (the sprite / light colours keep the full emission)
EMISSION_GAIN = {"fire": 0.55}
KIND = {"steam": 0, "flame": 1, "ember": 2, "spark": 3, "wisp": 4, "snow": 5, "dust": 6, "mote": 7}
DEFAULTS = {"veinScale": 9.0, "cellMul": 0.55, "radiusMul": 2.2, "isoFrac": 0.32, "solverIterations": 2,
            "battleParticles": 2500, "previewParticles": 5000, "lightRange": 1.1}
GUEST_SHARE, STAGE2_MINOR, SHARE_CAP = 0.3, 0.15, 0.45


def texture_colour(short: str) -> tuple[list[float], list[float], list[float]]:
    """Albedo, emission hue and light colour from the elemental's basecolor (opaque, non-black pixels)."""
    im = np.asarray(Image.open(S.out_dir(f"h3_{short}_elemental") / "basecolor.png").convert("RGBA"), dtype=np.float32) / 255.0
    rgb, a = im[..., :3].reshape(-1, 3), im[..., 3].reshape(-1)
    lum = rgb.max(axis=1)
    px = rgb[(a > 0.5) & (lum > 0.08)]
    mean = px.mean(axis=0) if len(px) else np.array([0.6, 0.6, 0.6])
    h, l, sat = colorsys.rgb_to_hls(*mean)
    albedo = colorsys.hls_to_rgb(h, min(max(l, 0.35), 0.7), min(1.0, sat * 1.15))
    hue = colorsys.hls_to_rgb(h, 0.5, min(1.0, max(sat, 0.5)))
    return [round(float(x), 3) for x in albedo], [float(x) for x in hue], [float(x) for x in colorsys.hls_to_rgb(h, 0.6, max(sat, 0.6))]


def element_row(family: str, short: str) -> dict:
    row = dict(FAMILY[family])
    row.update(VARIANT.get(short, {}))
    glow, tile, scroll, light = LOOK[short]
    albedo, hue, lightc = texture_colour(short)
    row["albedo"] = ALBEDO_OVERRIDE.get(short, albedo)
    row["emission"] = EMISSION_OVERRIDE.get(short, [round(c * glow, 3) for c in hue])
    row.update(uvTile=tile, scrollV=scroll)
    if light:
        row.update(lightColor=[round(c * 2.2, 3) for c in lightc] if short != "fire" else [2.2, 0.95, 0.35], lightIntensity=light)
    look = dict(SURF_FAMILY[family])
    look.update(SURF_VARIANT.get(short, {}))
    alb, em = row["albedo"], row["emission"]
    look.setdefault("_Albedo", alb)
    look.setdefault("_Albedo2", [round(c * (0.25 if family in ("earth", "fire") else 0.45), 3) for c in alb])
    look.setdefault("_Emission", [round(c * EMISSION_GAIN.get(family, 1.0), 3) for c in em])
    look.setdefault("_HotColor", [round(c * 2.0, 3) for c in em])
    look.setdefault("_FresnelColor", [round(min(1.0, c * 1.4 + 0.15), 3) for c in alb])
    row["look"] = look
    e = EMIT.get(short)
    if e:
        col = e["color"]
        if col is None:
            col = [round(c * 0.8, 3) for c in alb] + [1.0] if e["kind"] == "dust" else [round(c * 1.8 + 0.2, 3) for c in em] + [1.0]
        row.update(emitKind=KIND[e["kind"]], emitRate=e["rate"], emitLife=e["life"], emitSize=e["size"], emitColor=col,
                   emitHot=bool(e.get("hot")))
    row["steamColor"] = [0.86, 0.88, 0.92, 0.35]
    row["family"] = family
    return row


def build() -> dict:
    cfg = json.loads(FUSION.read_text(encoding="utf-8"))
    short_of, family_of = {}, {}
    for fam, sids in cfg["lines"].items():
        for i, sid in enumerate(sids):
            short_of[sid] = SHORT[fam][i]
            family_of[SHORT[fam][i]] = fam
    elements = {sh: element_row(family_of[sh], sh) for sh in sorted(family_of)}
    units, layers = {}, {}
    for p in cfg["pairs"]:
        host, guest = short_of[p["host"]], short_of[p["guest"]]
        layers[p["fused"]] = (host, guest)
        units[p["fused"]] = {"host": host, "guests": [] if guest == host else [[guest, GUEST_SHARE]], "name": p["name"]}
    for r in cfg["recipes"]:
        (h1, g1), (h2, g2) = layers[r["host"]], layers[r["guest"]]
        share: dict[str, float] = {}
        for el, f in ((g1, GUEST_SHARE), (h2, GUEST_SHARE), (g2, STAGE2_MINOR)):
            if el != h1:
                share[el] = min(SHARE_CAP, share.get(el, 0.0) + f)
        units[r["fused"]] = {"host": h1, "guests": [[k, round(v, 3)] for k, v in share.items()], "name": r["name"], "stage": 2}
    return {
        "schema": "homm3_fluid_fusion.v2",
        "note": "Generated by tools/conflux_fusion/fluid_fusion_config.py; edit the generator, not this file.",
        "enabled": True,
        "defaults": DEFAULTS,
        "shaders": SHADERS,
        "elements": elements,
        "units": units,
    }


# OldenEra/Homm3/FluidElement + FluidSprite (tools/conflux_fusion/fluid_shader), built into one bundle by
# V:/olden_port_work/elemental_fusion/fluid/fluid_lab.py `bundle`; asset names are the lower-case paths the lab built from
_SHADER_ROOT = "assets/homm3vfxlab/fusion_fluid/shaders/"
SHADERS = {
    "bundle": "homm3_fluid_fusion_shaders.bundle",
    "element": _SHADER_ROOT + "homm3fluidelement.shader",
    "sprite": _SHADER_ROOT + "homm3fluidsprite.shader",
    "sky": [0.42, 0.47, 0.55, 1.0],
    "ground": [0.2, 0.17, 0.13, 1.0],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the written config is stale or a seed file is missing")
    a = ap.parse_args()
    doc = build()
    text = json.dumps(doc, indent=1) + "\n"
    missing = [e for e in doc["elements"] if not (SEEDS / f"{e}.fluidseeds").exists()]
    if a.check:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        print("fluid_fusion.json", "STALE" if stale else "ok", "| missing seeds:", missing or "none")
        return 1 if stale or missing else 0
    OUT.write_text(text, encoding="utf-8")
    n2 = sum(1 for u in doc["units"].values() if u.get("stage") == 2)
    print(f"wrote {OUT} ({len(doc['elements'])} elements, {len(doc['units']) - n2} pairs + {n2} stage-2)",
          "| missing seeds:", missing or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
