"""DEF frame access and effect masks for defFlipbook layers.

Frames come from the build's extracted DEF PNGs (``frames.json`` "sources": one full-canvas
RGBA per master frame, the same canvas the SpriteCam renders). Palette methods read the DEF
through tools/homm3_vfx/h3def.py and require the same canvas size.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))


def load_rgba(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0


def body_mask(rgba: np.ndarray) -> np.ndarray:
    """Opaque, non-shadow DEF pixels (the prebake_lab.def_mask rule)."""
    return (rgba[..., 3] > 0.9) & (rgba[..., :3].max(-1) > 0.02)


@lru_cache(maxsize=8)
def _def(name: str):
    import h3def  # noqa: WPS433
    return h3def.read_def(name.lower())


@lru_cache(maxsize=16)
def _fx_base(unit: str, novel_max_idle_count):
    import def_effects as de  # owned by the roster ripper; imported, not modified
    return de, de.baseline(de.load_unit(unit), novel_max_idle_count=novel_max_idle_count)


def def_effects_result(method: dict, rgba: np.ndarray, unit: str) -> dict:
    nmic = method.get("novelMaxIdleCount")
    de, base = _fx_base(unit, None if nmic is None else float(nmic))
    a8 = (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)
    return de.frame_effects(a8, base, classes=method["classes"], include_detached=bool(method.get("includeDetached")),
                            min_component_px=int(method.get("minComponentPx", 1)))


def effect_mask_and_body(method: dict, rgba: np.ndarray, def_name=None, group=None, frame=None, unit=None):
    """(effect mask, the body it touches): for defEffects the ripper's own ``body``; otherwise the DEF's
    opaque non-shadow pixels outside the effect. Used by anchor.defOrigin "auto"."""
    if method["method"] == "defEffects":
        r = def_effects_result(method, rgba, unit)
        return r["layer"].copy(), np.asarray(r["body"], bool) & ~r["layer"]
    msk = effect_mask(method, rgba, def_name, group, frame, unit)
    return msk, body_mask(rgba) & ~msk


def def_effects_mask(method: dict, rgba: np.ndarray, unit: str) -> np.ndarray:
    """``defEffects``: exactly the ripper's selection, tools/homm3_vfx/def_effects.frame_effects()["layer"]
    (novel + class + relit-body exclusion + on-body tint drop + detached + cluster rule). There is no
    second selection path here, so the runner cuts the pixels the ripper previews."""
    return def_effects_result(method, rgba, unit)["layer"]


def effect_mask(method: dict, rgba: np.ndarray, def_name: str | None = None,
                group: int | None = None, frame: int | None = None, unit: str | None = None) -> np.ndarray:
    m = method["method"]
    if m == "defEffects":
        return def_effects_mask(method, rgba, unit)
    opaque = body_mask(rgba)
    if m == "file":
        p = Path(method["path"])
        p = p if p.is_absolute() else ROOT / p
        f = p / f"{group:02d}_{frame:02d}.png"
        return np.asarray(Image.open(f).convert("L")) > 127
    if m in ("palette", "paletteLuma"):
        d = _def(def_name)
        fr = d.groups[group][frame]
        idx = fr.idx
        if idx.shape != rgba.shape[:2]:
            raise ValueError(f"{def_name} {group}/{frame}: DEF canvas {idx.shape} != PNG {rgba.shape[:2]}")
        sel = np.isin(idx, np.array(method["indices"]))
        if m == "paletteLuma":
            c = d.palette.astype(float)[idx]
            sel &= (c @ np.array([0.299, 0.587, 0.114])) >= method.get("minLuma", 175)
        return sel & opaque
    # lumaSparse: bright, optionally sparse and/or blue-leaning pixels
    c = rgba[..., :3] * 255.0
    lum = c @ np.array([0.299, 0.587, 0.114], np.float32)
    sel = opaque & (lum >= method.get("minLuma", 175))
    if method.get("maxNeighbours") is not None:
        dens = ndimage.uniform_filter(opaque.astype(np.float32), size=5, mode="constant") * 25
        sel &= dens <= method["maxNeighbours"] + 1
    if method.get("blueOverRed") is not None:
        sel &= c[..., 2] >= c[..., 0] + method["blueOverRed"]
    return sel
