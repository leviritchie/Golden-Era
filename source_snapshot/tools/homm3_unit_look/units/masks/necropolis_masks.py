"""Region-cut `file` effect masks for necropolis units whose DEF effect shares the body's colours.

The roster ripper (def_effects.frame_effects) only counts smoke-grey when it is detached from the
body, so the vampires' bat-transform cloud (DEF groups 20 move_start / 21 move_end: a white smoke
column the vampire sinks into and a bat flies out of) is invisible to `defEffects`.

bat_cloud rule, per DEF frame of groups 20 and 21:
  - where the def_retarget mesh has shrunk away (its SpriteCam render covers < 25% of its idle
    coverage), the whole opaque DEF frame is the effect: cloud *and* bat, because the mesh draws
    nothing there and the DEF's bat is the only bat there is;
  - elsewhere (the vampire standing in the cloud) only the cloud: opaque, grey (max-min channel
    <= 34) and light (luma >= 125) pixels, dilated 1 px and closed, so the body stays mesh.

staff_burst (h3_lich_master, groups 12 and 15): the red-white starburst the staff tip throws on
frames 4-8. Its reds are the robe's reds, so defEffects keeps ~8% of it. Per frame: the burst core is
the centroid of the opaque luma > 240 pixels (>= 5 of them, else no burst); within 60 px of it, the
opaque pixels that are bright and not staff-gold, or red-pink (R-G >= 60, B >= G-10), or violet
(B >= G+25) form the candidate set, and only the 8-connected pieces that touch the core are kept, so
lit armour and bone highlights stay body.

staff_orb (h3_lich, h3_power_lich, group 15 frames 2-8): the staff-tip orb turns red while the
body is washed red (an on-body tint, carried as a light). The orb is the red (R >= 150, R-G >= 70)
component of >= 5 px that lies farthest from the opaque median, grown 2 px into red or bright
pixels. It is the carrier of the shoot glow light.

    python tools/homm3_unit_look/units/masks/necropolis_masks.py [unit ...]

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (L, 0/255, DEF canvas).
Proof: generated artifact (DEF measurement).
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../../.."))
sys.path.insert(0, os.path.join(ROOT, "tools/homm3_vfx"))
import def_effects as D  # noqa: E402

UNITS = ("h3_vampire", "h3_vampire_lord", "h3_vampire_prince", "h3_lich_master", "h3_lich", "h3_power_lich")
GROUPS = (20, 21)
EIGHT = np.ones((3, 3), bool)


def mesh_cover(unit: str, master: int) -> int:
    # renders are 1-based: sprite_001.png is master frame 0
    p = os.path.join(D.ART, unit, "renders", f"sprite_{master + 1:03d}.png")
    return int((np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 0).sum())


def cloud_pixels(a: np.ndarray) -> np.ndarray:
    rgb = a[..., :3].astype(np.int32)
    op = a[..., 3] == 255
    lum = rgb @ np.array([299, 587, 114]) / 1000
    grey = (rgb.max(-1) - rgb.min(-1)) <= 34
    m = op & grey & (lum >= 125)
    m = ndi.binary_closing(m, iterations=2) & op
    m = ndi.binary_dilation(m, iterations=1) & op
    lab, n = ndi.label(m)
    if n:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        m = sizes[lab] >= 20
    return m


def _lum(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114])


def staff_burst(a: np.ndarray) -> np.ndarray:
    rgb = a[..., :3].astype(np.int32)
    op = a[..., 3] == 255
    lum = _lum(rgb)
    core = (lum > 240) & op
    if core.sum() < 5:
        return np.zeros_like(op)
    ys, xs = np.nonzero(core)
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
    near = (yy - ys.mean()) ** 2 + (xx - xs.mean()) ** 2 < 60 ** 2
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gold = (r >= g) & (g >= b) & (b < 0.6 * g)
    m = op & near & (((lum >= 165) & ~gold) | ((r - g >= 60) & (b >= g - 10)) | (b >= g + 25))
    lab, _ = ndi.label(ndi.binary_dilation(m, structure=EIGHT), structure=EIGHT)
    keep = [k for k in np.unique(lab[core]) if k]
    return m & np.isin(lab, keep)


def staff_orb(a: np.ndarray) -> np.ndarray:
    rgb = a[..., :3].astype(np.int32)
    op = a[..., 3] == 255
    r, g = rgb[..., 0], rgb[..., 1]
    red = op & (r >= 150) & (r - g >= 70)
    lab, n = ndi.label(ndi.binary_dilation(red, iterations=1), structure=EIGHT)
    lab = lab * red
    ys, xs = np.nonzero(op)
    cy, cx = np.median(ys), np.median(xs)
    best = None
    for k in range(1, n + 1):
        yy, xx = np.nonzero(lab == k)
        if len(yy) < 5:
            continue
        d = np.hypot(yy.mean() - cy, xx.mean() - cx)
        if best is None or d > best[0]:
            best = (d, k)
    if best is None:
        return np.zeros_like(op)
    m = ndi.binary_dilation(lab == best[1], iterations=2)
    return m & op & ((r - g >= 40) | (_lum(rgb) >= 170))


def _save(unit, layer, g, i, m):
    out = os.path.join(HERE, unit, layer)
    os.makedirs(out, exist_ok=True)
    Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{g:02d}_{i:02d}.png"))
    return int(m.sum())


def build(unit: str) -> dict:
    us = D.load_unit(unit)
    if unit == "h3_lich_master":
        return {f"{g:02d}_{i:02d}": _save(unit, "staff_burst", g, i, staff_burst(us.group_rgba(g)[i]))
                for g in (12, 15) for i in range(4, 9)}
    if unit in ("h3_lich", "h3_power_lich"):
        return {f"15_{i:02d}": _save(unit, "staff_orb", 15, i, staff_orb(us.group_rgba(15)[i])) for i in range(2, 9)}
    return build_bat_cloud(unit, us)


def build_bat_cloud(unit: str, us) -> dict:
    idle_cover = np.median([mesh_cover(unit, us.master_index(2, i)) for i in range(len(us.groups[2]))])
    out = os.path.join(HERE, unit, "bat_cloud")
    os.makedirs(out, exist_ok=True)
    report = {}
    for g in GROUPS:
        for i, a in enumerate(us.group_rgba(g)):
            cover = mesh_cover(unit, us.master_index(g, i)) / idle_cover
            if cover < 0.25:
                m = a[..., 3] == 255
                how = "whole"
            else:
                m = cloud_pixels(a)
                how = "cloud"
            Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{g:02d}_{i:02d}.png"))
            report[f"{g:02d}_{i:02d}"] = (how, round(float(cover), 2), int(m.sum()))
    return report


if __name__ == "__main__":
    for u in sys.argv[1:] or UNITS:
        print(u, build(u))
