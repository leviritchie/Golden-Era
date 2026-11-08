"""Shared constants and source readers for the full-3D town lane (docs/homm3_stronghold_full_3d_town.md).

The faction is town_full3d_factions.KEY (--faction / TOWN_FULL3D_FACTION; default stronghold). Sources are ONLY the
faction's original HoMM3 town background (<Faction>-in-background.png, 800x374) and its HoMM3 building sprites
(layers/*.png) at their positions.json places. The old runtime 2D backdrop mockups (mockups/homm3_*_background_*) are
never read. No Meshy output is read.

Frame convention (identical to the Conflux full-3D lane, so the runtime seating and the v2 rest pose are shared):
the 1920x1080 reference frame of the cityHuman2 MainCamera rest pose, the HoMM3 screen at x1.8 top-left
(1440x673), positions.json coordinateBasis 3840 px canvas at x3.6.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

import town_full3d_factions as FA

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
FACTION = FA.KEY
FP = FA.P                                  # the faction profile (town_full3d_factions/<key>.py)
FRACTION = FP.FRACTION
REFS = PLUGIN / "homm3_runtime_assets" / "town_scene_refs" / FRACTION
# Profile LAYER_REFS (optional): a dir holding positions.json + the static sprites on the native 800x374 canvas, for a
# faction whose committed refs are not native px (HotA Factory: x,y doubled, sprites painted upscales clamped to 1024).
# building_layer_map.json and anims/ are still read from REFS. Absent: REFS/layers, as before.
LAYERS = Path(getattr(FP, "LAYER_REFS", None) or (REFS / "layers"))
# STRONGHOLD_FULL3D_ROOT (legacy name) overrides the output root; it is only honoured for the faction it was set for.
_root_env = os.environ.get("STRONGHOLD_FULL3D_ROOT", "").strip()
if _root_env and FACTION != "stronghold":
    raise SystemExit("STRONGHOLD_FULL3D_ROOT is set but the faction is '" + FACTION + "'; unset it")
DATA = Path(_root_env or str(ROOT / "artifacts" / FP.DATA_DIR))
# Model weights are faction-independent: one cache (V:, never C:) shared by every faction.
HF_CACHE = ROOT / "artifacts" / "homm3_stronghold_full3d" / "hf_cache"
W, H = 1920, 1080
SCALE = 1.8
TW, TH = round(800 * SCALE), round(374 * SCALE)   # 1440 x 673


def background_rgba() -> Image.Image:
    return Image.open(REFS / FP.BACKGROUND).convert("RGBA")


def background_rgb() -> Image.Image:
    return background_rgba().convert("RGB")


def positions() -> dict:
    return json.loads((LAYERS / "positions.json").read_text(encoding="utf-8"))


def layers() -> dict:
    return {l["id"]: l for l in positions()["layers"]}


def sprite(L: dict) -> Image.Image:
    return Image.open(LAYERS / L["sprite"]).convert("RGBA")


def layer_map() -> dict:
    return json.loads((REFS / "layers" / "building_layer_map.json").read_text(encoding="utf-8-sig"))


def reachable_layers() -> list[str]:
    native = layer_map()["nativeLevels"]
    return sorted({v for lv in native.values() for v in lv.values()})


def anim_frames() -> dict:
    meta = json.loads((REFS / "layers" / "anims" / "metadata.json").read_text(encoding="utf-8"))
    return {m["id"]: m for m in meta}


def static_plate(L: dict) -> Image.Image:
    """The sprite a building is textured with. The faction's effects module (profile FX_MODULE) may replace the parts it
    animates (the Stronghold windmill's sails) by the DEF frames' median; FX_MODULE None means the sprite itself."""
    if FP.FX_MODULE is None:
        return sprite(L)
    import importlib
    return importlib.import_module(FP.FX_MODULE).static_plate(L)


# TOWN_FULL3D_TEXSRC=<dir> (town_full3d_texsrc.py): the albedo bakes read an upscaled painting / static plates from
# <dir> instead of the native art. Masks, depth and geometry never read it. Unset: the native art (byte-identical).
TEXSRC = os.environ.get("TOWN_FULL3D_TEXSRC", "").strip()


def _texsrc() -> Path:
    d = Path(TEXSRC)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man.get("faction") != FACTION:
        raise SystemExit(f"TOWN_FULL3D_TEXSRC {d} is for faction {man.get('faction')!r}, not {FACTION!r}")
    return d


def albedo_background(carve: bool = True) -> Image.Image:
    """The painting the terrain / sky albedo is baked from (RGB): native, or the texsrc upscale. With
    TOWN_FULL3D_HOUSES (town_full3d_houses.py) the modelled instances' pixels are refilled with nearby ground
    (carve=False: the painting as is, e.g. for the instances' own projection)."""
    if carve and HOUSES:
        if TEXSRC:
            raise SystemExit("TOWN_FULL3D_HOUSES and TOWN_FULL3D_TEXSRC are both set; the carve refills the native "
                             "painting only")
        import town_full3d_houses as HS
        return HS.carved_background()
    return Image.open(_texsrc() / "background.png").convert("RGB") if TEXSRC else background_rgb()


# TOWN_FULL3D_HOUSES=<dir> (town_full3d_houses.py, schema town_full3d_houses.v1): repeated painted props replaced by
# one instanced model; the terrain albedo and depth are carved under them. Unset: unchanged (byte-identical).
HOUSES = os.environ.get("TOWN_FULL3D_HOUSES", "").strip()


def albedo_sprite(L: dict) -> Image.Image:
    """The static plate a building's albedo is baked from (RGBA): native, or the texsrc upscale."""
    return Image.open(_texsrc() / "layers" / f"{L['id']}.png").convert("RGBA") if TEXSRC else static_plate(L)


# TOWN_FULL3D_EXTSRC=<dir> (an integrated outpaint, e.g. the ChatGPT kit's integrate.py): the frame extension (outside
# the painted rect) and the left pan's periphery are baked from that canvas instead of the vanilla-texture synthesis.
# The canvas is the rest camera's image plane, frame px, columns canvasX[0]..canvasX[1]. Unset: the synthesis.
EXTSRC = os.environ.get("TOWN_FULL3D_EXTSRC", "").strip()


def extension_canvas():
    """(sRGB float32 kH x kWc x 3 in [0, 1], frame x of column 0, k) of the TOWN_FULL3D_EXTSRC canvas, or None if
    unset. k (manifest "scale", default 1) is canvas px per frame px: a detail pass may ship the canvas at k x."""
    if not EXTSRC:
        return None
    d = Path(EXTSRC)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man.get("schema") != "town_full3d_extsrc.v1" or man.get("faction") != FACTION:
        raise SystemExit(f"TOWN_FULL3D_EXTSRC {d}: schema {man.get('schema')!r} / faction {man.get('faction')!r} "
                         f"is not town_full3d_extsrc.v1 / {FACTION!r}")
    x0, x1 = man["canvasX"]
    if list(man["rect"]) != [TW, TH] or list(man["frame"]) != [W, H] or x0 > 0 or x1 < W:
        raise SystemExit(f"TOWN_FULL3D_EXTSRC {d}: canvas {man['canvasX']} rect {man['rect']} does not cover the frame")
    k = man.get("scale", 1)
    if not isinstance(k, int) or k < 1:
        raise SystemExit(f"TOWN_FULL3D_EXTSRC {d}: scale {k!r} is not a positive integer")
    img = np.asarray(Image.open(d / man["file"]).convert("RGB")).astype(np.float32) / 255
    if img.shape[:2] != (H * k, (x1 - x0) * k):
        raise SystemExit(f"TOWN_FULL3D_EXTSRC {d}: {man['file']} is {img.shape[1]}x{img.shape[0]}, "
                         f"manifest says {(x1 - x0) * k}x{H * k} (scale {k})")
    return img, int(x0), k


# TOWN_FULL3D_GROUNDSRC=<dir> (an authored ground material, schema town_full3d_groundsrc.v1): the floor outside the
# painted rect is sampled from a world-XZ albedo map plus mean-1 detail ratios instead of the vanilla-texture synthesis
# (stronghold_full3d_ground.GroundSrc). Walls keep the synthesis. Unset: the synthesis (byte-identical).
GROUNDSRC = os.environ.get("TOWN_FULL3D_GROUNDSRC", "").strip()


def ground_source():
    """(dir, manifest) of the TOWN_FULL3D_GROUNDSRC material, or None if unset."""
    if not GROUNDSRC:
        return None
    if EXTSRC:
        raise SystemExit("TOWN_FULL3D_GROUNDSRC and TOWN_FULL3D_EXTSRC are both set; they texture the same ground")
    d = Path(GROUNDSRC)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man.get("schema") != "town_full3d_groundsrc.v1" or man.get("faction") != FACTION:
        raise SystemExit(f"TOWN_FULL3D_GROUNDSRC {d}: schema {man.get('schema')!r} / faction {man.get('faction')!r} "
                         f"is not town_full3d_groundsrc.v1 / {FACTION!r}")
    return d, man


def sprite_frame(L: dict) -> np.ndarray:
    """The sprite placed in the 1920x1080 frame at x1.8 (RGBA uint8, LANCZOS; used for masks/texture, not scenery)."""
    s = sprite(L)
    s = s.resize((round(s.width * SCALE), round(s.height * SCALE)), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(s, (round(L["x"] * SCALE), round(L["y"] * SCALE)))
    return np.asarray(canvas)
