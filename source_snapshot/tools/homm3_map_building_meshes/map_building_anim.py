#!/usr/bin/env python3
"""Adventure-map building animation: DEF motion inventory + pilot animation data.

Subcommands
-----------
``inventory``  Decode every adventure-map building DEF the mod ships (96 Meshy-mesh cities and
               dwellings, the neutral-dwelling billboards, the seer hut), measure which pixels move
               across frames, and write ``map_building_anim_inventory.json`` next to this file. Every
               animated row carries a motion kind, a delivery lane and a status (``delivered`` or
               ``planned`` with a reason). ``tools/validate_map_building_anim_contract.py`` pins it.

``build``      Produce the animation data for the rows listed in ``map_building_anim_spec.json``:

               * ``rotor``          (mesh): split the rotor faces out of the Meshy GLB into a pivot
                                    node and write ``model_anim.glb`` + ``map_anim.json`` in the
                                    mesh dir. The Unity bundle builder turns the pivot into an
                                    Animator + looping clip (native Olden Era windmill/sawmill
                                    pattern: Animator on a rigid child transform).
               * ``vanilla_style_effect`` (mesh): smoke, fire, glow and water as the game's own
                                    map-object ParticleSystems. ``effects`` (also allowed on a rotor
                                    row) name a preset of ``map_building_fx_presets.json`` and an
                                    anchor measured on the mesh (front / top ortho px at width 512,
                                    or the skyline peak near a column). Each anchor is an empty in
                                    ``model_anim.glb`` whose rotation carries the preset's native
                                    world rotation under the runtime billboard front yaw;
                                    ``map_building_fx.py`` compiles one ``homm3_mesh_fx`` row per
                                    effect. Meshy's frozen sculpt of the effect can be stripped
                                    (``stripGeometryAboveEffect``). HoMM3 sprite flipbooks are
                                    retired: the ``flipbook`` lane is refused.
               * ``billboard_frames`` (billboard): the staged 00_00 PNG is an upscaled redraw, so the
                                    raw DEF frames cannot be swapped in as-is. Each frame is the
                                    redraw with the DEF motion region replaced by that frame's DEF
                                    pixels (silhouette-registered, nearest upscale).

               Runtime frames and ``anim/catalog.json`` are staged under
               ``OfflineUnlockMod/homm3_map_building_meshes/anim/`` (deployed with the mesh folder).

Proof tier of the outputs: generated artifact. Frame timing (180 ms per DEF frame) is a hypothesis
(VCMI-style adventure-map object rate), not a measured HoMM3 constant.
"""
from __future__ import annotations

import argparse
import colorsys
import io
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
MAP_REFS = PLUGIN / "homm3_runtime_assets" / "map_object_refs"
MESH_INVENTORY = ROOT / "artifacts" / "meshy_map_buildings" / "inventory.json"
MESHES_ROOT = ROOT / "artifacts" / "meshy_map_buildings" / "meshes"
NEUTRAL_DWELLINGS = PLUGIN / "homm3_neutral_dwellings.json"
STAGE = PLUGIN / "homm3_map_building_meshes" / "anim"
STAGE_CATALOG = STAGE / "catalog.json"
INVENTORY_OUT = TOOL_DIR / "map_building_anim_inventory.json"
SPEC = TOOL_DIR / "map_building_anim_spec.json"
DATA = ROOT / "vcmi" / "Data"
LODS = ["HotA.lod", "HotA_ext.lod", "H3ab_spr.lod", "H3sprite.lod"]
NEW_GRAPHICS = ROOT / "vcmi/Mods/hota/mods/newGraphics/Content/sprites/hota"
BULWARK_ZIP = ROOT / "vcmi/Mods/hota/mods/bulwark/content.zip"

INVENTORY_SCHEMA = "homm3_map_building_anim_inventory.v1"
CATALOG_SCHEMA = "homm3_map_building_anim.v1"
SIDECAR_SCHEMA = "homm3_map_building_anim_sidecar.v1"
DEFAULT_FRAME_MS = 180.0
ANCHOR_PREFIX = "HOMM3_anim_anchor_"
ROTOR_PIVOT_PREFIX = "HOMM3_anim_rotor_"
PART_PIVOT_PREFIX = "HOMM3_anim_part_"
PART_LANES = {"pendulum", "articulated_rigid"}
EFFECT_LANE = "vanilla_style_effect"
RETIRED_LANES = {"flipbook"}  # HoMM3 sprite flipbooks: rejected by the user 2026-09-26
FX_PRESETS = TOOL_DIR / "map_building_fx_presets.json"
# Runtime billboard front yaw (Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat): the prefab root turns
# 180 deg about Y before the map facing and art yaw, so an anchor bakes yaw(-180) * nativeWorldRotation.
BILLBOARD_FRONT_YAW_DEG = 180.0
PART_KEYS_PER_DEF_FRAME = 8  # dense keys so the Unity clip needs only linear tangents

# Motion parts read off the DEF audit sheets (artifacts/map_building_anim/audit/<def>_audit.png: every
# frame, motion heat mask, zoomed moving region, per-component centroid paths). The DEF alone cannot
# say "this is a rotor"; these labels are the inspected classification, one entry per independent
# moving part. Re-audited 2026-09-26 (docs/homm3_map_object_animation_audit.md): mechanical parts
# first, because the first part sets the row's planned lane.
MECHANICAL_KINDS = {"rotor", "pendulum", "articulated_rigid"}
EFFECT_KINDS = {"smoke", "fire", "glow_pulse", "glow_particles", "water"}
MOTION_PARTS: dict[str, list[tuple[str, str]]] = {
    "avgkbl01": [("articulated_rigid",
                  "crane jib slews about the vertical mast: held toward the viewer (~57 deg from screen "
                  "right) f0-20, swings out parallel to the screen f21-27, holds f28-41, swings back "
                  "f42-49, holds f50-71 (72 frames, measured from the jib tip); the ore bucket hangs at "
                  "a fixed rope length and rides the jib (it shows only once the tip clears the rock "
                  "pile); the rock-pile flicker is render noise, not motion")],
    "avgair0": [("glow_particles", "cloud vortex, orbiting ring and crystal flicker")],
    "avgelp": [("glow_pulse", "cloud swirl inside the magic mirror; frame beads glint")],
    "avgerth0": [("water", "bubbling grey-brown mud pool (not lava)")],
    "avgfbrd": [("glow_particles", "fire vortex funnel with lightning arcs")],
    "avgfire0": [("fire", "fire column")],
    "avgpixie": [("water", "pond ripple and cascade under the house"),
                 ("glow_pulse", "small window-light flicker")],
    "avgwatr0": [("water", "fountain jets")],
    "hasphtpl": [("water", "flat whirlpool swirling in the basin; no wheel or axle")],
    "nimphfo": [("water", "waterfall")],
    "avgrdrg0": [("glow_pulse", "three gold glints")],
    "avcfacz0": [("glow_pulse", "arched windows of the dome drum flicker")],
    "avgarma": [("rotor", "multi-blade windpump rotor, clockwise")],
    "avgauto": [("smoke", "three chimney smoke plumes")],
    "avgmecha": [("smoke", "chimney smoke")],
    "avgworm": [("glow_pulse", "green vent lights pulse on the dome (not a lava pit)")],
    "homm3_fortress_city/capitol": [("fire", "window and brazier glow (2.5% of pixels)")],
    "avgdfly0": [("glow_pulse", "red glowing tree-trunk hollows pulse (not sparkles)")],
    "avghydr0": [("water", "swamp water ripple at the front")],
    "homm3_inferno_city/capitol": [("fire", "fire behind the central window")],
    "avgefre0": [("fire", "molten gold/lava bed shimmers around the base")],
    "avggogs0": [("fire", "lava pours from the cauldron spout into the bubbling lava basin (no smoke)")],
    "avgimp0": [("fire", "fire in the arched crevice")],
    "avgpit0": [("fire", "lava pool and the fire ring in the gate")],
    "avgpega0": [("water", "waterfall")],
    "avgbhmt0": [("fire", "cave-mouth fire")],
    "avggolm0": [("rotor",
                  "two riveted flywheels turn: the large black wheel at the front (rim ellipse centred "
                  "near (60,98) px, 9x18 px, counter-clockwise on screen, rivet ring advances ~4 pitches "
                  "of ~33 deg per 20-frame loop = 6.6 deg/frame, in bursts) and a smaller wheel seen edge-on at the right side (~(92,104) px)"),
                 ("smoke", "steam puffs from the three stack tops")],
    "avggrem0": [("pendulum",
                  "brass pendulum under the house swings side to side: one hinged part, pivot at the top "
                  "of the rod under the floor (~(61,56) px); bob centroid x 59.9 -> 67.1 (f7) -> 60.1 "
                  "(f15), one out-and-back per 16-frame loop; the clock face does not move")],
    "avghalf": [("smoke", "chimney smoke")],
    "avglprch": [("smoke", "chimney smoke")],
}

# Default lane per motion kind for rows not yet delivered (the rollout plan). Effects follow the
# vanilla Olden Era style (docs/olden_era_vanilla_vfx_style.md): no HoMM3 sprite flipbooks.
PLANNED_LANE = {
    "rotor": "rotor",
    "pendulum": "pendulum",
    "articulated_rigid": "articulated_rigid",
    "smoke": "vanilla_style_effect",
    "fire": "vanilla_style_effect",
    "glow_pulse": "vanilla_style_effect",
    "glow_particles": "vanilla_style_effect",
    "water": "vanilla_style_effect",
}
PLANNED_REASON = {
    "rotor": "rotor lane (mesh surgery on the shipped mesh + baked Animator clip); build pending",
    "pendulum": "pendulum lane (cut the swinging part, hinge pivot, baked swing clip); build pending",
    "articulated_rigid": "articulated rig: several rigid parts cut from the shipped mesh, each on its own "
                         "pivot, driven by one baked clip; build pending",
    "vanilla_style_effect": "effect in the vanilla Olden Era style (docs/olden_era_vanilla_vfx_style.md); "
                            "no DEF flipbooks",
    "billboard_frames": "billboard row: same recipe as the delivered avghalf billboard_frames pilot",
}


# ----------------------------------------------------------------------------------------------
# DEF access
# ----------------------------------------------------------------------------------------------

def _lod_index(path: Path):
    data = path.read_bytes()
    (total,) = struct.unpack_from("<I", data, 8)
    off = 92
    idx = {}
    for _ in range(total):
        raw = data[off:off + 16]
        off += 16
        nul = raw.find(b"\0")
        name = (raw[:nul] if nul >= 0 else raw).decode("latin1").lower()
        o, size, _u, csize = struct.unpack_from("<IIII", data, off)
        off += 16
        idx.setdefault(name, (o, size, csize))
    return data, idx


_LOD_CACHE: list | None = None


def _lods():
    global _LOD_CACHE
    if _LOD_CACHE is None:
        _LOD_CACHE = [(n, *_lod_index(DATA / n)) for n in LODS if (DATA / n).is_file()]
    return _LOD_CACHE


def read_def(dir_rel: str) -> tuple[str | None, bytes | None]:
    """Return (source label, DEF bytes) for a staged ``<group>/<stem>.dir`` folder."""
    group = dir_rel.split("/")[0]
    stem = Path(dir_rel).name[:-4]
    if stem.lower() == "capitol":
        faction = group.replace("homm3_", "").replace("_city", "")
        p = NEW_GRAPHICS / faction / "adventureMap/town/capitol.def"
        return ("newGraphics:" + faction, p.read_bytes()) if p.is_file() else (None, None)
    if "bulwark" in group and BULWARK_ZIP.is_file():
        with zipfile.ZipFile(BULWARK_ZIP) as z:
            for m in z.namelist():
                if m.lower().endswith("/" + stem.lower() + ".def"):
                    return "bulwark.zip", z.read(m)
    want = stem.lower() + ".def"
    for name, data, idx in _lods():
        if want in idx:
            o, size, csize = idx[want]
            blob = data[o:o + csize] if csize else data[o:o + size]
            return name, (zlib.decompress(blob) if csize else blob)
    return None, None


def decode_def(blob: bytes):
    """Decode a HoMM3 DEF into (palette[256,3], {group: [uint8 index frames HxW]})."""
    f = io.BytesIO(blob)
    _t, _, _, blocks = struct.unpack("<IIII", f.read(16))
    pal = np.frombuffer(f.read(768), np.uint8).reshape(256, 3)
    groups = {}
    for _ in range(blocks):
        bid, entries, _, _ = struct.unpack("<IIII", f.read(16))
        f.read(13 * entries)
        groups[bid] = [struct.unpack("<I", f.read(4))[0] for _ in range(entries)]
    out = {}
    for bid, offs in groups.items():
        frames = []
        for offs0 in offs:
            f.seek(offs0)
            _, fmt, fw, fh, w, h, lm, tm = struct.unpack("<IIIIIIii", f.read(32))
            img = np.zeros((fh, fw), np.uint8)
            px = bytearray()
            if w and h:
                if fmt == 0:
                    px = f.read(w * h)
                elif fmt == 1:
                    lo = struct.unpack("<" + "I" * h, f.read(4 * h))
                    for line in lo:
                        f.seek(offs0 + 32 + line)
                        n = 0
                        while n < w:
                            c, ln = struct.unpack("<BB", f.read(2))
                            ln += 1
                            px += f.read(ln) if c == 0xFF else bytes([c]) * ln
                            n += ln
                elif fmt == 2:
                    lo = struct.unpack("<%dH" % h, f.read(2 * h))
                    f.read(2)
                    for line in lo:
                        f.seek(offs0 + 32 + line)
                        n = 0
                        while n < w:
                            (s,) = struct.unpack("<B", f.read(1))
                            c = s >> 5
                            ln = (s & 31) + 1
                            px += f.read(ln) if c == 7 else bytes([c]) * ln
                            n += ln
                elif fmt == 3:
                    nb = w // 32
                    lo = [struct.unpack("<" + "H" * nb, f.read(2 * nb)) for _ in range(h)]
                    for row in lo:
                        for line in row:
                            f.seek(offs0 + 32 + line)
                            n = 0
                            while n < 32:
                                (s,) = struct.unpack("<B", f.read(1))
                                c = s >> 5
                                ln = (s & 31) + 1
                                px += f.read(ln) if c == 7 else bytes([c]) * ln
                                n += ln
                a = np.frombuffer(bytes(px[:w * h]), np.uint8).reshape(h, w)
                img[tm:tm + h, lm:lm + w] = a
            frames.append(img)
        out[bid] = frames
    return pal, out


def def_frames(dir_rel: str):
    label, blob = read_def(dir_rel)
    if blob is None:
        raise FileNotFoundError(f"DEF not found for {dir_rel}")
    pal, groups = decode_def(blob)
    g0 = groups.get(0) or next(iter(groups.values()))
    return label, pal, g0


def index_to_rgba(idx: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Palette frame -> RGBA with every special index (0-7: transparency, shadows, flag) cleared.

    Map-building billboards and meshes already drop the DEF shadow and flag; effect frames do too.
    """
    rgba = np.zeros(idx.shape + (4,), np.uint8)
    rgba[..., :3] = pal[idx]
    rgba[..., 3] = np.where(idx > 7, 255, 0)
    return rgba


def motion_mask(frames: list[np.ndarray]) -> np.ndarray:
    st = np.stack(frames)
    body_any = (st > 7).any(0)
    changed = (st != st[0:1]).any(0)
    return changed & body_any


def body_mask(frame: np.ndarray) -> np.ndarray:
    return frame > 7


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        m = out.copy()
        m[1:] |= out[:-1]
        m[:-1] |= out[1:]
        m[:, 1:] |= out[:, :-1]
        m[:, :-1] |= out[:, 1:]
        out = m
    return out


def components(mask: np.ndarray, link: int = 3) -> list[np.ndarray]:
    """Connected components of ``mask`` after bridging gaps up to ``link`` px (4-connectivity)."""
    bridged = dilate(mask, link)
    lab = np.zeros(mask.shape, np.int32)
    comps = []
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(bridged)):
        if lab[y0, x0]:
            continue
        cid = len(comps) + 1
        stack = [(y0, x0)]
        lab[y0, x0] = cid
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and bridged[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cid
                    stack.append((yy, xx))
        comp = np.zeros(mask.shape, bool)
        ys, xs = zip(*pts)
        comp[list(ys), list(xs)] = True
        comps.append(comp & mask)
    return [c for c in comps if c.any()]


def bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def classify_hue(frames, pal, moving) -> dict:
    st = np.stack(frames)
    mv = st[:, moving]
    mv = mv[mv > 7]
    hues = {"fire": 0, "water": 0, "grey": 0, "green": 0, "magic": 0}
    if mv.size:
        rgb = pal[mv].astype(float) / 255
        for r, g, b in rgb[:: max(1, len(rgb) // 4000)]:
            hh, _l, s = colorsys.rgb_to_hls(r, g, b)
            if s < 0.18:
                hues["grey"] += 1
            elif hh < 0.14 or hh > 0.93:
                hues["fire"] += 1
            elif 0.17 < hh < 0.45:
                hues["green"] += 1
            elif 0.45 <= hh < 0.7:
                hues["water"] += 1
            else:
                hues["magic"] += 1
    tot = sum(hues.values()) or 1
    return {k: round(v / tot, 2) for k, v in hues.items() if v}


# ----------------------------------------------------------------------------------------------
# Silhouette registration (DEF frame px -> target image px)
# ----------------------------------------------------------------------------------------------

def _resample_mask(mask: np.ndarray, sx: float, sy: float, tx: float, ty: float, shape) -> np.ndarray:
    """Forward map of source mask into target shape: target(x,y) = src((x-tx)/sx, (y-ty)/sy)."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    u = np.floor((xs + 0.5 - tx) / sx).astype(int)
    v = np.floor((ys + 0.5 - ty) / sy).astype(int)
    ok = (u >= 0) & (v >= 0) & (u < mask.shape[1]) & (v < mask.shape[0])
    out = np.zeros(shape, bool)
    out[ok] = mask[v[ok], u[ok]]
    return out


def register_silhouette(src: np.ndarray, dst: np.ndarray) -> dict:
    """Fit axis-aligned scale+offset mapping src px -> dst px maximising silhouette IoU."""
    sx0, sy0, sx1, sy1 = bbox(src)
    dx0, dy0, dx1, dy1 = bbox(dst)
    sx = (dx1 - dx0 + 1) / (sx1 - sx0 + 1)
    sy = (dy1 - dy0 + 1) / (sy1 - sy0 + 1)
    tx = dx0 - sx0 * sx
    ty = dy0 - sy0 * sy
    # Work at reduced resolution for the search.
    k = max(1, int(max(dst.shape) / 160))
    dsmall = dst[::k, ::k]

    def iou(p):
        a = _resample_mask(src, p[0] / k, p[1] / k, p[2] / k, p[3] / k, dsmall.shape)
        inter = (a & dsmall).sum()
        uni = (a | dsmall).sum()
        return inter / max(1, uni)

    best = [sx, sy, tx, ty]
    best_s = iou(best)
    for step in (0.08, 0.04, 0.02, 0.01):
        improved = True
        while improved:
            improved = False
            for i, d in ((0, best[0] * step), (1, best[1] * step), (2, dst.shape[1] * step), (3, dst.shape[0] * step)):
                for sgn in (-1, 1):
                    cand = list(best)
                    cand[i] += sgn * d
                    s = iou(cand)
                    if s > best_s + 1e-6:
                        best, best_s, improved = cand, s, True
    return {"sx": best[0], "sy": best[1], "tx": best[2], "ty": best[3], "iou": round(float(best_s), 4)}


# ----------------------------------------------------------------------------------------------
# GLB read / front orthographic render / write
# ----------------------------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "tools" / "homm3_vfx"))
from glb_io import Glb  # noqa: E402


class MeshData:
    def __init__(self, path: Path):
        self.path = path
        self.glb = Glb(path)
        j = self.glb.json
        if len(j["meshes"]) != 1 or len(j["meshes"][0]["primitives"]) != 1 or len(j["nodes"]) != 1:
            raise ValueError(f"{path}: expected one node / one mesh / one primitive (Meshy shape)")
        node = j["nodes"][0]
        m = node.get("matrix")
        if m is not None and not np.allclose(np.array(m), np.eye(4).flatten()):
            raise ValueError(f"{path}: mesh node matrix is not identity")
        prim = j["meshes"][0]["primitives"][0]
        self.prim = prim
        self.V = self.glb.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
        self.UV = self.glb.accessor(prim["attributes"]["TEXCOORD_0"]).astype(np.float64)
        self.F = self.glb.accessor(prim["indices"]).astype(np.int64).reshape(-1, 3)
        self.tex = np.asarray(self.glb.image(self.glb.base_color_image_index()).convert("RGBA"))


def render_front(mesh: MeshData, width: int = 512):
    """Front view: viewer on +Z looking -Z, X right, Y up (matches the DEF art)."""
    V, F = mesh.V, mesh.F
    lo, hi = V[:, :2].min(0), V[:, :2].max(0)
    span = hi - lo
    height = int(round(width * span[1] / span[0]))
    s = (width - 1) / span[0]
    X = (V[:, 0] - lo[0]) * s
    Y = (hi[1] - V[:, 1]) * s
    Z = V[:, 2]
    zb = np.full((height, width), -np.inf)
    fid = np.full((height, width), -1, np.int64)
    bary = np.zeros((height, width, 3))
    for f in range(len(F)):
        a, b, c = F[f]
        xs = X[[a, b, c]]
        ys = Y[[a, b, c]]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(width - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(height - 1, np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(d) < 1e-12:
            continue
        l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
        l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
        l2 = 1 - l0 - l1
        ins = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        z = l0 * Z[a] + l1 * Z[b] + l2 * Z[c]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        upd = ins & (z > sub)
        sub[upd] = z[upd]
        fid[y0:y1 + 1, x0:x1 + 1][upd] = f
        bary[y0:y1 + 1, x0:x1 + 1][upd] = np.stack([l0, l1, l2], -1)[upd]
    img = np.zeros((height, width, 4), np.uint8)
    hit = fid >= 0
    fv = mesh.F[fid[hit]]
    uv = (bary[hit][:, :, None] * mesh.UV[fv]).sum(1)
    th, tw = mesh.tex.shape[:2]
    # glTF UV origin is top-left of the image.
    px = np.clip((uv[:, 0] * (tw - 1)).astype(int), 0, tw - 1)
    py = np.clip((uv[:, 1] * (th - 1)).astype(int), 0, th - 1)
    img[hit] = mesh.tex[py, px]
    img[hit, 3] = 255
    return img, {"lo": lo, "hi": hi, "scale": s, "zb": zb, "fid": fid, "W": width, "H": height}


def ortho_px_to_model(info, x: float, y: float) -> tuple[float, float]:
    return info["lo"][0] + x / info["scale"], info["hi"][1] - y / info["scale"]


def write_anim_glb(mesh: MeshData, out: Path, rotors: list[dict], anchors: list[dict],
                   drop_faces: np.ndarray | None = None, parts: list[dict] | None = None) -> None:
    """Write a copy of the Meshy GLB with rotor faces split under pivot nodes and anchor empties.

    ``parts`` (keyed rigid parts: pendulum, articulated_rigid) are split the same way under
    ``HOMM3_anim_part_<i>_pivot`` nodes; a part with ``parent`` >= 0 is nested under that part's
    pivot so it inherits its motion (a crane's bucket rides the jib).

    Every primitive reuses the original vertex accessors; only index accessors are added, so the
    textures, UVs and normals are byte-identical to the shipped mesh.
    """
    parts = parts or []
    j = json.loads(json.dumps(mesh.glb.json))
    binbuf = bytearray(mesh.glb.bin)
    prim = j["meshes"][0]["primitives"][0]

    def add_indices(faces: np.ndarray) -> int:
        while len(binbuf) % 4:
            binbuf.append(0)
        data = faces.astype(np.uint32).reshape(-1).tobytes()
        j["bufferViews"].append({"buffer": 0, "byteOffset": len(binbuf), "byteLength": len(data), "target": 34963})
        binbuf.extend(data)
        j["accessors"].append({
            "bufferView": len(j["bufferViews"]) - 1,
            "componentType": 5125,
            "count": int(faces.size),
            "type": "SCALAR",
        })
        return len(j["accessors"]) - 1

    rotor_faces = set(int(f) for f in (drop_faces if drop_faces is not None else []))
    for r in list(rotors) + list(parts):
        faces_r = set(int(f) for f in r["faces"])
        if faces_r & rotor_faces:
            raise SystemExit(f"{out}: a moving part shares faces with another part or the dropped set")
        rotor_faces.update(faces_r)
    keep = np.array([f for f in range(len(mesh.F)) if f not in rotor_faces], np.int64)
    body_acc = add_indices(mesh.F[keep])
    body_prim = dict(prim)
    body_prim["indices"] = body_acc
    j["meshes"] = [{"name": "body", "primitives": [body_prim]}]
    nodes = [{"name": "body", "mesh": 0}]
    scene_nodes = [0]
    for i, r in enumerate(rotors):
        acc = add_indices(mesh.F[np.array(sorted(r["faces"]), np.int64)])
        p = dict(prim)
        p["indices"] = acc
        j["meshes"].append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_mesh", "primitives": [p]})
        piv = np.asarray(r["pivot"], float)
        if "planeScale" in r:
            # Elliptical rotor: frame (T, R, S) -> pivot (spin about local Z) -> unscale (S^-1) ->
            # mesh (R^-1, -R^-1 T). The composite T R S Spin S^-1 R^-1 T^-1 moves the rim detail
            # along the oval while the oval outline itself stays put.
            q = r["pivotRotation"]
            sc = [float(v) for v in r["planeScale"]]
            base = len(nodes)
            nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_frame", "translation": piv.tolist(), "rotation": q,
                          "scale": sc, "children": [base + 1]})
            nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_pivot", "children": [base + 2]})
            nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_unscale", "scale": [1.0 / v for v in sc],
                          "children": [base + 3]})
            inv_q = [-q[0], -q[1], -q[2], q[3]]
            nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_mesh", "mesh": len(j["meshes"]) - 1,
                          "rotation": inv_q, "translation": (-_quat_rotate(inv_q, piv)).tolist()})
            scene_nodes.append(base)
            continue
        q = r["pivotRotation"]  # xyzw, maps local +Z onto the rotor axis
        nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_pivot", "translation": piv.tolist(), "rotation": q,
                      "children": [len(nodes) + 1]})
        # Child undoes the pivot transform so the vertices stay where they are at rest.
        inv_q = [-q[0], -q[1], -q[2], q[3]]
        t = -_quat_rotate(inv_q, piv)
        nodes.append({"name": f"{ROTOR_PIVOT_PREFIX}{i}_mesh", "mesh": len(j["meshes"]) - 1,
                      "rotation": inv_q, "translation": t.tolist()})
        scene_nodes.append(len(nodes) - 2)
    part_node: list[int] = []
    for i, pt in enumerate(parts):
        acc = add_indices(mesh.F[np.array(sorted(pt["faces"]), np.int64)])
        p = dict(prim)
        p["indices"] = acc
        j["meshes"].append({"name": f"{PART_PIVOT_PREFIX}{i}_mesh", "primitives": [p]})
        piv = np.asarray(pt["pivot"], float)
        q = pt["pivotRotation"]
        par = int(pt.get("parent", -1))
        if par >= i:
            raise SystemExit(f"{out}: part {i} parent {par} must be an earlier part")
        if par >= 0:
            # Pivot pose relative to the parent pivot (both authored in model space).
            qp = parts[par]["pivotRotation"]
            qp_inv = [-qp[0], -qp[1], -qp[2], qp[3]]
            loc_q = _quat_mul(qp_inv, q)
            loc_t = _quat_rotate(qp_inv, piv - np.asarray(parts[par]["pivot"], float))
        else:
            loc_q, loc_t = q, piv
        nodes.append({"name": f"{PART_PIVOT_PREFIX}{i}_pivot", "translation": [float(v) for v in loc_t],
                      "rotation": [float(v) for v in loc_q], "children": [len(nodes) + 1]})
        inv_q = [-q[0], -q[1], -q[2], q[3]]
        t = -_quat_rotate(inv_q, piv)
        nodes.append({"name": f"{PART_PIVOT_PREFIX}{i}_mesh", "mesh": len(j["meshes"]) - 1,
                      "rotation": inv_q, "translation": t.tolist()})
        pivot_idx = len(nodes) - 2
        part_node.append(pivot_idx)
        if par >= 0:
            nodes[part_node[par]]["children"].append(pivot_idx)
        else:
            scene_nodes.append(pivot_idx)
    for a in anchors:
        node = {"name": ANCHOR_PREFIX + a["id"], "translation": [float(v) for v in a["position"]]}
        if "rotation" in a:
            node["rotation"] = [float(v) for v in a["rotation"]]
        nodes.append(node)
        scene_nodes.append(len(nodes) - 1)
    j["nodes"] = nodes
    j["scenes"] = [{"nodes": scene_nodes}]
    j["scene"] = 0
    j["buffers"] = [{"byteLength": len(binbuf)}]
    js = json.dumps(j, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    while len(binbuf) % 4:
        binbuf.append(0)
    total = 12 + 8 + len(js) + 8 + len(binbuf)
    blob = bytearray()
    blob += struct.pack("<III", 0x46546C67, 2, total)
    blob += struct.pack("<II", len(js), 0x4E4F534A) + js
    blob += struct.pack("<II", len(binbuf), 0x004E4942) + binbuf
    out.write_bytes(bytes(blob))


def _quat_rotate(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    v = np.asarray(v, float)
    return 2 * np.dot(u, v) * u + (w * w - np.dot(u, u)) * v + 2 * w * np.cross(u, v)


def _quat_mul(a, b) -> list[float]:
    """Hamilton product a*b of xyzw quaternions (apply b, then a)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def _quat_from_matrix(m: np.ndarray) -> list[float]:
    """xyzw quaternion of a proper rotation matrix (columns = the rotated basis vectors)."""
    m = np.asarray(m, float)
    if np.linalg.det(m) < 0:
        raise ValueError("frame is left-handed")
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    n = np.linalg.norm(q)
    return [float(v / n) for v in q]


def _quat_from_z_to(axis) -> list[float]:
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    z = np.array([0.0, 0.0, 1.0])
    c = float(np.dot(z, a))
    if c > 1 - 1e-9:
        return [0.0, 0.0, 0.0, 1.0]
    if c < -1 + 1e-9:
        return [1.0, 0.0, 0.0, 0.0]
    ax = np.cross(z, a)
    s = np.sqrt((1 + c) * 2)
    q = [ax[0] / s, ax[1] / s, ax[2] / s, s / 2]
    n = np.linalg.norm(q)
    return [float(v / n) for v in q]


# ----------------------------------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------------------------------

def inventory_rows() -> list[dict]:
    rows = []
    inv = json.loads(MESH_INVENTORY.read_text(encoding="utf-8"))["entries"]
    for e in inv:
        if not e.get("generate"):
            continue
        rows.append({"dir": e["dir"], "relativePng": e["relativePng"], "kind": e["kind"],
                     "delivery": "mesh", "prefabKey": e["prefabKey"]})
    nd = json.loads(NEUTRAL_DWELLINGS.read_text(encoding="utf-8"))
    seen = set()
    for d in nd["dwellings"]:
        rel = d["relativePath"]
        if rel in seen:
            continue
        seen.add(rel)
        rows.append({"dir": rel.split("map_object_refs/")[1].rsplit("/", 1)[0], "relativePng": rel,
                     "kind": "neutral_dwelling", "delivery": "billboard"})
    rows.append({"dir": "homm3_seer_hut/avxseer0.dir",
                 "relativePng": "homm3_runtime_assets/map_object_refs/homm3_seer_hut/avxseer0.dir/00_00.png",
                 "kind": "seer_hut", "delivery": "billboard"})
    return rows


def motion_key(dir_rel: str) -> str:
    stem = Path(dir_rel).name[:-4].lower()
    if stem == "capitol":
        return dir_rel.split("/")[0] + "/capitol"
    return stem


def cmd_inventory(_args) -> int:
    spec = load_spec()
    catalog = json.loads(STAGE_CATALOG.read_text(encoding="utf-8")) if STAGE_CATALOG.is_file() else {"entries": []}
    delivered = {e["relativePng"]: e for e in catalog.get("entries", [])}
    out_rows = []
    for r in inventory_rows():
        label, blob = read_def(r["dir"])
        if blob is None:
            raise SystemExit(f"DEF missing for {r['dir']}")
        pal, groups = decode_def(blob)
        g0 = groups.get(0) or next(iter(groups.values()))
        row = {"relativePng": r["relativePng"], "dir": r["dir"], "delivery": r["delivery"],
               "buildingKind": r["kind"], "def": Path(r["dir"]).name[:-4] + ".def", "defSource": label,
               "frames": len(g0)}
        if r.get("prefabKey"):
            row["prefabKey"] = r["prefabKey"]
        if len(g0) > 1:
            mv = motion_mask(g0)
            opaque = (np.stack(g0) > 7).any(0)
            row["movingPx"] = int(mv.sum())
            row["movingFracOfOpaque"] = round(float(mv.sum() / max(1, opaque.sum())), 4)
            row["movingBBox"] = list(bbox(mv)) if mv.any() else None
            row["movingHue"] = classify_hue(g0, pal, mv)
            flag_moving = ((np.stack(g0) == 5).any(0) & (np.stack(g0) != g0[0]).any(0)).sum()
            row["flagMovingPx"] = int(flag_moving)
        animated = len(g0) > 1 and row.get("movingPx", 0) > 0
        row["animated"] = animated
        if animated:
            key = motion_key(r["dir"])
            if key not in MOTION_PARTS:
                raise SystemExit(f"animated DEF {r['dir']} has no MOTION_PARTS classification")
            parts = MOTION_PARTS[key]
            row["motionKind"] = parts[0][0]
            row["motionNote"] = "; ".join(n for _k, n in parts)
            row["motionParts"] = [{"kind": k, "lane": PLANNED_LANE[k], "note": n} for k, n in parts]
            spec_row = spec.get(r["relativePng"])
            if spec_row and r["relativePng"] in delivered:
                row["lane"] = spec_row["lane"]
                row["status"] = "delivered"
                # A delivered row may carry parts of several lanes (golem factory: rotor + steam effect).
                # The billboard_frames repaint carries every effect part of its billboard; on a mesh an
                # effect part is delivered only by a vanilla-style effect of that kind in the catalog row.
                fx_kinds = {fx["kind"] for fx in delivered[r["relativePng"]].get("effects") or []}
                for part in row["motionParts"]:
                    if part["kind"] in EFFECT_KINDS and row["lane"] == "billboard_frames":
                        part["status"] = "delivered"
                        part["deliveredBy"] = "billboard_frames"
                    elif part["kind"] in EFFECT_KINDS and part["kind"] in fx_kinds:
                        part["status"] = "delivered"
                        part["deliveredBy"] = EFFECT_LANE
                    elif part["kind"] not in EFFECT_KINDS and part["lane"] == row["lane"]:
                        part["status"] = "delivered"
                    else:
                        part["status"] = "planned"
            else:
                row["lane"] = "billboard_frames" if r["delivery"] == "billboard" else PLANNED_LANE[parts[0][0]]
                row["status"] = "planned"
                row["plannedReason"] = PLANNED_REASON[row["lane"]]
        else:
            row["status"] = "static"
        out_rows.append(row)
    doc = {
        "schema": INVENTORY_SCHEMA,
        "generator": "tools/homm3_map_building_meshes/map_building_anim.py inventory",
        "frameMsHypothesis": DEFAULT_FRAME_MS,
        "flagFinding": "palette index 5 (player flag) never changes across frames in any building DEF; "
                       "HoMM3 ownership flags are separate overlay DEFs, so there is no flag cloth motion to port",
        "counts": {
            "rows": len(out_rows),
            "animated": sum(1 for x in out_rows if x.get("animated")),
            "delivered": sum(1 for x in out_rows if x.get("status") == "delivered"),
            "planned": sum(1 for x in out_rows if x.get("status") == "planned"),
        },
        "rows": out_rows,
    }
    INVENTORY_OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {INVENTORY_OUT} {doc['counts']}")
    return 0


# ----------------------------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------------------------

def load_spec() -> dict[str, dict]:
    doc = json.loads(SPEC.read_text(encoding="utf-8"))
    return {r["relativePng"]: r for r in doc["rows"]}


def staged_redraw(relative_png: str) -> np.ndarray:
    return np.asarray(Image.open(PLUGIN / relative_png).convert("RGBA"))


def affine_upscale(rgba: np.ndarray, reg: dict, shape) -> np.ndarray:
    """Premultiplied bicubic resample of a DEF RGBA frame into target px (x = u*sx + tx), then a
    hard alpha edge (the Hex/Lit map material alpha-clips) so no dark fringe or half-alpha remains."""
    h, w = shape
    prem = rgba.astype(np.float32)
    prem[..., :3] *= prem[..., 3:4] / 255.0
    chans = []
    for c in range(4):
        im = Image.fromarray(prem[..., c])
        chans.append(np.asarray(im.transform(
            (w, h), Image.AFFINE,
            (1.0 / reg["sx"], 0.0, -reg["tx"] / reg["sx"], 0.0, 1.0 / reg["sy"], -reg["ty"] / reg["sy"]),
            resample=Image.BICUBIC)))
    a = np.clip(chans[3], 0, 255)
    rgb = np.stack(chans[:3], -1)
    safe = np.maximum(a, 1e-3)[..., None]
    rgb = np.clip(rgb * 255.0 / safe, 0, 255)
    out = np.zeros((h, w, 4), np.uint8)
    solid = a >= 128
    out[solid, :3] = rgb[solid].astype(np.uint8)
    out[solid, 3] = 255
    return out


def build_billboard_frames(spec_row: dict, catalog_rows: list, report: dict) -> None:
    rel = spec_row["relativePng"]
    dir_rel = rel.split("map_object_refs/")[1].rsplit("/", 1)[0]
    label, pal, frames = def_frames(dir_rel)
    redraw = staged_redraw(rel)
    base_mask = redraw[..., 3] >= 128
    # Register against a body silhouette common to all frames (the static building).
    static_body = np.logical_and.reduce([body_mask(f) for f in frames])
    reg = register_silhouette(static_body, base_mask)
    mv = dilate(motion_mask(frames), int(spec_row.get("motionDilatePx", 1)))
    h, w = redraw.shape[:2]
    # Erase the redraw where it painted the (static) moving element, then lay each DEF frame in.
    erase = dilate(_resample_mask(mv, reg["sx"], reg["sy"], reg["tx"], reg["ty"], (h, w)),
                   int(spec_row.get("eraseDilatePx", 3)))
    # Only erase redraw pixels that are not part of the static body the DEF keeps in every frame.
    keep_static = _resample_mask(static_body & ~mv, reg["sx"], reg["sy"], reg["tx"], reg["ty"], (h, w))
    erase &= ~keep_static
    ys, xs = np.mgrid[0:h, 0:w]
    u = np.clip(np.floor((xs + 0.5 - reg["tx"]) / reg["sx"]).astype(int), 0, frames[0].shape[1] - 1)
    v = np.clip(np.floor((ys + 0.5 - reg["ty"]) / reg["sy"]).astype(int), 0, frames[0].shape[0] - 1)
    stem = Path(dir_rel).name[:-4].lower()
    out_dir = STAGE / "billboard" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    names = []
    for i, fr in enumerate(frames):
        rgba = index_to_rgba(fr, pal)
        img = redraw.copy()
        img[erase] = 0
        layer = affine_upscale(rgba, reg, (h, w))
        take = erase & (layer[..., 3] > 0)
        img[take] = layer[take]
        name = f"{i:02d}.png"
        Image.fromarray(img).save(out_dir / name)
        names.append(name)
    catalog_rows.append({
        "relativePng": rel,
        "delivery": "billboard",
        "lane": "billboard_frames",
        "frameMs": float(spec_row.get("frameMs", DEFAULT_FRAME_MS)),
        "frames": [f"billboard/{stem}/{n}" for n in names],
    })
    report[rel] = {"lane": "billboard_frames", "defSource": label, "registration": reg,
                   "frames": len(names), "erasePx": int(erase.sum())}


def build_mesh_row(spec_row: dict, catalog_rows: list, report: dict) -> None:
    rel = spec_row["relativePng"]
    inv = {e["relativePng"]: e for e in json.loads(MESH_INVENTORY.read_text(encoding="utf-8"))["entries"]}
    if rel not in inv:
        raise SystemExit(f"{rel} is not in the Meshy mesh inventory")
    e = inv[rel]
    mesh_dir = MESHES_ROOT / e["dir"]
    mesh = MeshData(mesh_dir / "model.glb")
    label, pal, frames = def_frames(e["dir"])
    img, info = render_front(mesh, int(spec_row.get("orthoWidth", 512)))
    static_body = np.logical_and.reduce([body_mask(f) for f in frames])
    reg = register_silhouette(static_body, img[..., 3] > 0)
    stem = Path(e["dir"]).name[:-4].lower()
    rotors, anchors, parts = [], [], []
    removed = np.zeros(0, np.int64)
    lane = spec_row["lane"]
    diag = {"registration": reg, "defSource": label, "ortho": [info["W"], info["H"]]}
    if lane == "rotor" and "wheels" in spec_row:
        rotors.extend(segment_wheels(mesh, spec_row, diag))
    elif lane == "rotor":
        rotor = segment_rotor(mesh, info, frames, reg, spec_row, diag)
        rotors.append(rotor)
    elif lane in RETIRED_LANES:
        raise SystemExit(f"{rel}: lane {lane} is retired (HoMM3 sprite flipbooks were rejected); use {EFFECT_LANE}")
    elif lane == EFFECT_LANE:
        pass
    elif lane in PART_LANES:
        parts = build_parts(mesh, info, frames, pal, spec_row, diag)
    else:
        raise SystemExit(f"unknown mesh lane {lane}")
    effects = []
    if spec_row.get("effects"):
        if lane not in (EFFECT_LANE, "rotor"):
            raise SystemExit(f"{rel}: effects ride only the {EFFECT_LANE} or rotor lane, not {lane}")
        if spec_row.get("stripGeometryAboveEffect"):
            removed = strip_effect_geometry(mesh, info, frames, reg, spec_row)
            diag["strippedFaces"] = int(len(removed))
            taken = {int(f) for r in rotors for f in r["faces"]}
            if taken & {int(f) for f in removed}:
                raise SystemExit(f"{rel}: stripped effect geometry overlaps a rotor")
        effects = build_effects(mesh, info, removed, spec_row, fx_key(e["prefabKey"]), anchors, diag)
    elif lane == EFFECT_LANE:
        raise SystemExit(f"{rel}: lane {EFFECT_LANE} lists no effects")
    write_anim_glb(mesh, mesh_dir / "model_anim.glb", rotors, anchors, drop_faces=removed, parts=parts)
    sidecar = {
        "schema": SIDECAR_SCHEMA,
        "relativePng": rel,
        "prefabKey": e["prefabKey"],
        "lane": lane,
        "frameMs": float(spec_row.get("frameMs", DEFAULT_FRAME_MS)),
        "rotors": [{k: v for k, v in r.items() if k != "faces"} | {"faceCount": len(r["faces"])} for r in rotors],
        "parts": [{k: v for k, v in p.items() if k != "faces"} | {"faceCount": len(p["faces"])} for p in parts],
        "anchors": anchors,
    }
    (mesh_dir / "map_anim.json").write_text(json.dumps(sidecar, indent=1) + "\n", encoding="utf-8")
    row = {"relativePng": rel, "delivery": "mesh", "lane": lane, "prefabKey": e["prefabKey"],
           "frameMs": sidecar["frameMs"]}
    if rotors:
        row["rotors"] = [{"pivot": f"{ROTOR_PIVOT_PREFIX}{i}_pivot", "periodSeconds": r["periodSeconds"],
                          "direction": r["direction"]} for i, r in enumerate(rotors)]
    if effects:
        row["stem"] = fx_key(e["prefabKey"])
        row["effects"] = effects
    if parts:
        row["parts"] = [{"pivot": p["name"], "kind": p["kind"], "parent": p["parent"],
                         "loopSeconds": p["loopSeconds"]} for p in parts]
    catalog_rows.append(row)
    diag["glb"] = str((mesh_dir / "model_anim.glb").relative_to(ROOT)).replace("\\", "/")
    report[rel] = diag
    _debug_overlay(img, info, frames, reg, rotors + parts, anchors, stem)


def load_fx_presets() -> dict:
    doc = json.loads(FX_PRESETS.read_text(encoding="utf-8"))
    if doc.get("schema") != "homm3_map_building_fx_presets.v1":
        raise SystemExit(f"{FX_PRESETS.name}: unexpected schema {doc.get('schema')!r}")
    return doc["presets"]


def _view_mesh(mesh: MeshData, V: np.ndarray) -> MeshData:
    m = MeshData.__new__(MeshData)
    m.__dict__.update(mesh.__dict__)
    m.V = V
    return m


def anchor_rotation_gltf(native_q) -> list[float]:
    """glTF rotation of an anchor whose Unity world rotation, after the runtime front yaw, is ``native_q``.

    Unity local = yaw(-front) * native. glTFast imports glTF (x, y, z, w) as Unity (x, -y, -z, w) (the X mirror);
    the map is an involution, so the glTF value is the mirrored Unity local."""
    h = np.radians(-BILLBOARD_FRONT_YAW_DEG) / 2
    qu = _quat_mul([0.0, float(np.sin(h)), 0.0, float(np.cos(h))], [float(v) for v in native_q])
    n = float(np.linalg.norm(qu))
    return [round(qu[0] / n, 6), round(-qu[1] / n, 6), round(-qu[2] / n, 6), round(qu[3] / n, 6)]


def resolve_anchor(mesh: MeshData, info, removed: np.ndarray, a: dict, views: dict, where: str) -> list[float]:
    """Model-space position of an effect anchor measured on the mesh views (front / top ortho px at the row's
    ortho width, or the skyline peak near a front column).

    * ``{"front": [x, y], "depth": "front"|"center"|"back", "offset": d}``: the front-view pixel; depth is the
      nearest surface, the far surface (a 180-degree turned render) or their mean; ``offset`` moves toward the
      viewer (+Z) in model units.
    * ``{"top": [x, row], "offset": d}``: the top-view pixel (viewer above, front at the bottom), on the highest
      surface there; ``offset`` lifts it (+Y).
    * ``{"skylinePeakNear": x, "radiusPx": r, "offset": d}``: the chimney-top rule (highest skyline plateau);
      ``offset`` lifts it (+Y).
    """
    off = float(a.get("offset", 0.0))
    if "skylinePeakNear" in a:
        mx, my, z = skyline_peak_near(mesh, info, removed, float(a["skylinePeakNear"]), float(a.get("radiusPx", 40)))
        return [mx, my + off, z]
    if "front" in a:
        x, y = (float(v) for v in a["front"])
        mx, my = ortho_px_to_model(info, x, y)
        zf = front_depth_near(info, x, y, radius=int(a.get("searchPx", 6)))
        depth = a.get("depth", "front")
        if depth == "front":
            z = zf
        else:
            if "back" not in views:
                V = mesh.V
                views["back"] = render_front(_view_mesh(mesh, np.stack([-V[:, 0], V[:, 1], -V[:, 2]], 1)), info["W"])[1]
            bi = views["back"]
            zb = -front_depth_near(bi, bi["W"] - 1 - x, y, radius=int(a.get("searchPx", 6)))
            if depth == "back":
                z = zb
            elif depth == "center":
                z = (zf + zb) / 2
            else:
                raise SystemExit(f"{where}: unknown anchor depth {depth!r}")
        return [mx, my, z + off]
    if "top" in a:
        if "top" not in views:
            V = mesh.V
            views["top"] = render_front(_view_mesh(mesh, np.stack([V[:, 0], -V[:, 2], V[:, 1]], 1)), info["W"])[1]
        ti = views["top"]
        x, row = (float(v) for v in a["top"])
        mx, negz = ortho_px_to_model(ti, x, row)
        h = front_depth_near(ti, x, row, radius=int(a.get("searchPx", 6)))
        return [mx, h + off, -negz]
    raise SystemExit(f"{where}: anchor needs front, top or skylinePeakNear")


def fx_key(prefab_key: str) -> str:
    """Unique effect key of a mesh row (the two capitols share the DEF stem)."""
    pre = "map_mesh_homm3_"
    if not prefab_key.startswith(pre):
        raise SystemExit(f"unexpected prefab key {prefab_key}")
    return prefab_key[len(pre):]


def build_effects(mesh: MeshData, info, removed: np.ndarray, spec_row: dict, stem: str, anchors: list,
                  diag: dict) -> list[dict]:
    """Anchors + catalog entries of a row's vanilla-style effects (map_building_fx.py compiles the fx rows)."""
    presets = load_fx_presets()
    dir_rel = spec_row["relativePng"].split("map_object_refs/")[1].rsplit("/", 1)[0]
    kinds = {k for k, _n in MOTION_PARTS.get(motion_key(dir_rel), [])}
    views: dict = {}
    out = []
    diag["effects"] = []
    for fx in spec_row["effects"]:
        fid = str(fx["id"])
        where = f"{spec_row['relativePng']} effect {fid}"
        if not fid.replace("_", "").isalnum() or any(a["id"] == fid for a in anchors):
            raise SystemExit(f"{where}: effect id must be unique and alphanumeric")
        if fx["preset"] not in presets:
            raise SystemExit(f"{where}: unknown preset {fx['preset']!r}")
        if fx["kind"] not in EFFECT_KINDS or fx["kind"] not in kinds:
            raise SystemExit(f"{where}: kind {fx['kind']!r} is not an effect part of this DEF ({sorted(kinds)})")
        p = presets[fx["preset"]]
        pos = resolve_anchor(mesh, info, removed, fx["anchor"], views, where)
        rot = anchor_rotation_gltf(p["nativeWorldRotation"])
        anchors.append({"id": fid, "position": [round(float(v), 6) for v in pos], "rotation": rot})
        scale = float(fx.get("scale", p["scale"]))
        if not 0 < scale <= 4:
            raise SystemExit(f"{where}: scale {scale} outside (0, 4]")
        entry = {"id": fid, "kind": fx["kind"], "preset": fx["preset"], "anchor": ANCHOR_PREFIX + fid,
                 "fxId": f"mbfx_{stem}_{fid}", "scale": scale, "rateMul": float(fx.get("rateMul", 1.0))}
        if fx.get("recolor"):
            entry["recolor"] = [float(c) for c in fx["recolor"]]
        out.append(entry)
        diag["effects"].append({"id": fid, "preset": fx["preset"], "anchor": [round(float(v), 4) for v in pos],
                                "spec": fx["anchor"]})
    return out


def strip_effect_geometry(mesh: MeshData, info, frames, reg, spec_row) -> np.ndarray:
    """Faces of the static sculpt Meshy made of the moving element (e.g. frozen smoke above the
    chimneys): welded pieces lying wholly above the effect's source line inside its column."""
    mv = motion_mask(frames)
    x0, y0, x1, y1 = bbox(mv)
    base_y_px = (y1 + 1) * reg["sy"] + reg["ty"]
    _, base_y = ortho_px_to_model(info, 0, base_y_px)
    widen = float(spec_row.get("stripColumnWiden", 0.5)) * (x1 - x0 + 1)
    lx, _ = ortho_px_to_model(info, (x0 - widen) * reg["sx"] + reg["tx"], 0)
    rx, _ = ortho_px_to_model(info, (x1 + 1 + widen) * reg["sx"] + reg["tx"], 0)
    V, F = mesh.V, mesh.F
    c = V[F].mean(1)
    comp = welded_components(V, F)
    out = []
    for u in np.unique(comp):
        f = np.nonzero(comp == u)[0]
        above = (c[f, 1] >= base_y).mean()
        cx = c[f, 0].mean()
        if above >= 0.9 and lx <= cx <= rx:
            out.extend(f.tolist())
    return np.array(sorted(out), np.int64)


def skyline_peak_near(mesh: MeshData, info, removed: np.ndarray, ox: float, radius_px: float):
    """(x, y, z) model coords of the highest body point in the column nearest ``ox`` that is a local
    skyline peak (chimney top)."""
    V, F = mesh.V, mesh.F
    keep = np.ones(len(F), bool)
    keep[removed] = False
    tri = V[F[keep]]
    s = info["scale"]
    W = info["W"]
    sky = np.full(W, -np.inf)
    sky_z = np.full(W, -np.inf)
    for t in tri:
        xs = (t[:, 0] - info["lo"][0]) * s
        a, b = int(max(0, np.floor(xs.min()))), int(min(W - 1, np.ceil(xs.max())))
        ytop = t[:, 1].max()
        for x in range(a, b + 1):
            if ytop > sky[x]:
                sky[x] = ytop
                sky_z[x] = t[:, 2].max()
    lo = int(max(1, ox - radius_px))
    hi = int(min(W - 2, ox + radius_px))
    peaks = []
    win = 6
    for x in range(lo, hi + 1):
        seg = sky[max(0, x - win):x + win + 1]
        if np.isfinite(sky[x]) and sky[x] >= seg.max() - 1e-9:
            peaks.append(x)
    if not peaks:
        raise SystemExit(f"no skyline peak within {radius_px}px of x={ox:.1f}")
    # Group adjacent plateau columns and take the plateau centre nearest to ox.
    groups, cur = [], [peaks[0]]
    for x in peaks[1:]:
        if x - cur[-1] <= 1:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    # A plateau cut by the search window is the shoulder of a peak outside it, not a peak.
    groups = [g for g in groups if g[0] > lo and g[-1] < hi] or groups
    # Highest peak wins (smoke leaves from the top of the stack); distance breaks ties.
    cands = [((g[0] + g[-1]) / 2.0, float(sky[g[len(g) // 2]])) for g in groups]
    best = min(cands, key=lambda c: (-round(c[1], 3), abs(c[0] - ox)))[0]
    xi = int(round(best))
    return info["lo"][0] + best / s, float(sky[xi]), float(sky_z[xi])


def front_depth_near(info, x, y, radius=10) -> float:
    zb = info["zb"]
    h, w = zb.shape
    xi, yi = int(round(x)), int(round(y))
    best = -np.inf
    for r in range(0, radius + 1):
        y0, y1 = max(0, yi - r), min(h, yi + r + 1)
        x0, x1 = max(0, xi - r), min(w, xi + r + 1)
        win = zb[y0:y1, x0:x1]
        if np.isfinite(win).any():
            best = float(win[np.isfinite(win)].max())
            break
    if not np.isfinite(best):
        raise SystemExit(f"no mesh surface within {radius}px of anchor ({x:.1f},{y:.1f})")
    return best


def segment_rotor(mesh: MeshData, info, frames, reg, spec_row, diag) -> dict:
    """Select the rotor faces: front-visible faces inside the DEF motion disc, in the front layer."""
    mv = motion_mask(frames)
    x0, y0, x1, y1 = bbox(mv)
    # Rotor hub = centre of the swept disc (blades sweep a full circle over a loop).
    cx_def, cy_def = (x0 + x1 + 1) / 2.0, (y0 + y1 + 1) / 2.0
    r_def = max(x1 - x0 + 1, y1 - y0 + 1) / 2.0
    ocx = cx_def * reg["sx"] + reg["tx"]
    ocy = cy_def * reg["sy"] + reg["ty"]
    orad = r_def * 0.5 * (reg["sx"] + reg["sy"]) * float(spec_row.get("discRadiusScale", 1.1))
    if "discOverrideOrtho" in spec_row:  # explicit, inspected correction (ortho px of the width used)
        ocx, ocy, orad = spec_row["discOverrideOrtho"]
    V, F = mesh.V, mesh.F
    s = info["scale"]
    allc = V[F].mean(1)
    px = (allc[:, 0] - info["lo"][0]) * s
    py = (info["hi"][1] - allc[:, 1]) * s
    in_disc = (px - ocx) ** 2 + (py - ocy) ** 2 <= orad ** 2
    # The rotor is a thin slab in front of the tower: take the front-most depth peak of the faces
    # inside the (generous) DEF-registered disc and walk down to the first valley.
    zc = allc[in_disc, 2]
    hist, edges = np.histogram(zc, bins=int(spec_row.get("depthBins", 30)))
    top = int(np.nonzero(hist >= 0.2 * hist.max())[0].max())
    k = top
    while k > 0 and hist[k - 1] >= hist[k]:  # climb to the front peak
        k -= 1
    while k > 0 and hist[k - 1] < hist[k]:  # descend to the valley behind it
        k -= 1
    zmin = float(spec_row["rotorMinZ"]) if "rotorMinZ" in spec_row else float(edges[k + 1])
    slab = np.nonzero(in_disc & (allc[:, 2] >= zmin))[0]
    if len(slab) < 50:
        raise SystemExit(f"rotor segmentation found only {len(slab)} slab faces")
    tri = V[F]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    # Hub: area-weighted centroid of the slab, trimmed to the blade radius and iterated (the tower
    # runs out of the disc in one direction only, so trimming by the median sector radius removes it).
    hub = np.array([(allc[slab, 0].min() + allc[slab, 0].max()) / 2, (allc[slab, 1].min() + allc[slab, 1].max()) / 2])
    for _ in range(12):
        d = allc[slab, :2] - hub
        r = np.hypot(d[:, 0], d[:, 1])
        sec = (np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 360) // 22.5
        p95 = [np.percentile(r[sec == k], 95) for k in range(16) if (sec == k).sum() >= 10]
        keep = slab[r <= np.median(p95) * 1.05]
        wts = area[keep]
        new_hub = (allc[keep, :2] * wts[:, None]).sum(0) / wts.sum()
        if np.linalg.norm(new_hub - hub) < 1e-5:
            break
        hub = new_hub
    if "hubOverrideModel" in spec_row:
        hub = np.asarray(spec_row["hubOverrideModel"], float)
    hub_x, hub_y = float(hub[0]), float(hub[1])
    d = allc[slab, :2] - hub
    r = np.hypot(d[:, 0], d[:, 1])
    sec = (np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 360) // 22.5
    p99 = [np.percentile(r[sec == k], 99) for k in range(16) if (sec == k).sum() >= 10]
    r_tip = float(np.percentile(p99, 75) * 1.05)
    # Rotor = welded mesh pieces that live inside the blade circle and in the front slab. The tower
    # pieces run far outside the circle, so a per-piece rule separates them without cutting faces.
    comp = welded_components(V, F)
    d_all = np.hypot(allc[:, 0] - hub_x, allc[:, 1] - hub_y)
    inside_frac = float(spec_row.get("pieceInsideFrac", 0.9))
    sel = np.zeros(len(F), bool)
    for u in np.unique(comp[slab]):
        f = comp == u
        if (d_all[f] <= r_tip).mean() >= inside_frac and allc[f, 2].mean() >= zmin:
            sel |= f
    faces = np.nonzero(sel)[0]
    if len(faces) < 50:
        raise SystemExit(f"rotor segmentation kept only {len(faces)} faces")
    pts = V[np.unique(F[faces])]
    c = pts - pts.mean(0)
    evals, evecs = np.linalg.eigh(c.T @ c)
    axis = evecs[:, 0]
    if axis[2] < 0:
        axis = -axis
    pivot = [float(hub_x), float(hub_y), float(pts[:, 2].mean())]
    # Rotation speed from the DEF: polar correlation of the rotor pixels around the hub.
    step_deg = def_rotor_step_degrees(frames, (cx_def, cy_def), r_def, int(spec_row.get("blades", 8)))
    period_frames = 360.0 / abs(step_deg) if abs(step_deg) > 1e-3 else float("inf")
    frame_ms = float(spec_row.get("frameMs", DEFAULT_FRAME_MS))
    diag["rotor"] = {"discOrtho": [round(ocx, 2), round(ocy, 2), round(orad, 2)], "faces": int(len(faces)),
                     "rotorMinZ": round(zmin, 4), "hub": [round(hub_x, 4), round(hub_y, 4)],
                     "bladeRadius": round(r_tip, 4), "slabFaces": int(len(slab)),
                     "axis": [round(float(v), 4) for v in axis], "defStepDegPerFrame": round(step_deg, 3),
                     "defFrames": len(frames)}
    return {
        "faces": faces.tolist(),
        "pivot": pivot,
        "axis": [float(v) for v in axis],
        "pivotRotation": _quat_from_z_to(axis),
        # Direction as seen by a viewer in front of the art: ccw = counter-clockwise on screen.
        "direction": "ccw" if step_deg > 0 else "cw",
        "degPerDefFrame": round(float(abs(step_deg)), 4),
        "periodSeconds": round(period_frames * frame_ms / 1000.0, 4),
        # Signed spin about the pivot's local +Z in glTF (right-handed, +Z faces the viewer, so
        # positive = counter-clockwise on screen). The Unity builder converts handedness.
        "gltfDegPerSecondAboutLocalZ": round(step_deg / (frame_ms / 1000.0), 4),
    }


# ----------------------------------------------------------------------------------------------
# Keyed rigid parts (pendulum, articulated_rigid): mesh surgery on the shipped Meshy mesh
# ----------------------------------------------------------------------------------------------
#
# A part is a set of whole welded pieces of the shipped mesh (no face is cut, so no hole opens and
# nothing needs capping), re-parented under a pivot node. Its motion is a keyed track measured on
# the DEF frames: ``angleDeg`` about the pivot's local +Z (glTF, right-handed: + = counter-clockwise
# for a viewer looking down -Z) and ``lift`` along local +Z in model units. The spec gives the
# selection and the pivot in front-ortho px (``orthoWidth``, default 512) because the DEF is an
# isometric painting and the Meshy mesh a front sculpt: the silhouette fit between them is too loose
# to place a hinge, so each pivot is an explicit, inspected value recorded in the build report.

def _ortho_face_px(mesh: MeshData, info) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    c = mesh.V[mesh.F].mean(1)
    s = info["scale"]
    return (c[:, 0] - info["lo"][0]) * s, (info["hi"][1] - c[:, 1]) * s, c


def select_part_faces(mesh: MeshData, info, p: dict, taken: np.ndarray) -> np.ndarray:
    """Whole welded pieces whose every face centroid is inside ``pieceBoxOrtho``; pieces reaching
    above ``neckOrtho[2]`` must also lie inside the neck columns ``neckOrtho[0..1]`` (keeps the
    brackets beside a hanger on the body)."""
    px, py, _c = _ortho_face_px(mesh, info)
    comp = welded_components(mesh.V, mesh.F)
    x0, y0, x1, y1 = p["pieceBoxOrtho"]
    inbox = (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
    neck = p.get("neckOrtho")
    sel = np.zeros(len(mesh.F), bool)
    for u in np.unique(comp[inbox]):
        f = comp == u
        if not inbox[f].all() or taken[f].any():
            continue
        if neck is not None and py[f].min() < neck[2] and (px[f].min() < neck[0] or px[f].max() > neck[1]):
            continue
        sel |= f
    for fx in p.get("excludeFaceBoxesOrtho", []):
        bx0, by0, bx1, by1 = fx
        sel &= ~((px >= bx0) & (px <= bx1) & (py >= by0) & (py <= by1))
    faces = np.nonzero(sel)[0]
    if len(faces) < int(p.get("minFaces", 50)):
        raise SystemExit(f"part {p.get('kind')} selection kept only {len(faces)} faces")
    return faces


def _palette_family(pal: np.ndarray, family: str) -> np.ndarray:
    out = np.zeros(256, bool)
    for i in range(8, 256):
        r, g, b = (pal[i].astype(float) / 255).tolist()
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if family == "gold":
            out[i] = 0.08 <= h <= 0.2 and s > 0.35 and v > 0.25
        else:
            raise SystemExit(f"unknown track hue family {family}")
    return out


def _harmonic_fit(values: np.ndarray, harmonics: int) -> np.ndarray:
    """Least-squares Fourier series (period = len(values)) evaluated at the DEF frames; removes
    the one-pixel jitter of a hand-animated sprite while keeping its timing."""
    n = len(values)
    t = np.arange(n)
    cols = [np.ones(n)]
    for k in range(1, harmonics + 1):
        cols += [np.cos(2 * np.pi * k * t / n), np.sin(2 * np.pi * k * t / n)]
    A = np.stack(cols, 1)
    coef, *_ = np.linalg.lstsq(A, values, rcond=None)
    return coef


def _eval_harmonic(coef: np.ndarray, n: int, t: np.ndarray) -> np.ndarray:
    out = np.full_like(t, coef[0], dtype=float)
    for k in range(1, (len(coef) - 1) // 2 + 1):
        out += coef[2 * k - 1] * np.cos(2 * np.pi * k * t / n) + coef[2 * k] * np.sin(2 * np.pi * k * t / n)
    return out


def def_swing_track(frames, pal, p: dict) -> dict:
    """Per-DEF-frame swing angle of a hanging part, from the centroid of its coloured pixels.

    angle = atan(dx / lever): dx is the centroid's screen offset from its loop mean, lever the
    screen distance from the DEF hinge to the mean centroid. + = the part swings to screen right
    (counter-clockwise about a +Z axis facing the viewer). The DEF is an isometric view, so a
    swing plane not parallel to the screen reads smaller; ``planeProjection`` (<= 1) is that
    foreshortening and is an inspected estimate, not a measurement."""
    fam = _palette_family(pal, p["trackHue"])
    bx0, by0, bx1, by1 = p["defTrackBox"]
    cx, cy = [], []
    for fr in frames:
        m = np.zeros(fr.shape, bool)
        m[by0:by1 + 1, bx0:bx1 + 1] = fam[fr[by0:by1 + 1, bx0:bx1 + 1]]
        ys, xs = np.nonzero(m)
        if len(xs) < 10:
            raise SystemExit("swing track lost the part in a DEF frame")
        cx.append(xs.mean())
        cy.append(ys.mean())
    cx, cy = np.array(cx), np.array(cy)
    hx, hy = p["defHinge"]
    lever = float(cy.mean() - hy)
    dx = (cx - cx.mean()) / float(p.get("planeProjection", 1.0))
    ang = np.degrees(np.arctan2(dx, lever))
    return {"raw": ang, "centroidX": cx, "centroidY": cy, "leverPx": lever}


def def_slew_track(frames, p: dict) -> dict:
    """Per-DEF-frame heading of a jib slewing about a vertical mast, from its tip.

    The tip is the right end of the rightmost horizontal run of >= ``tipRunPx`` opaque pixels in
    ``defTipWindow`` (a one-pixel rope or stay line never makes such a run). With the jib parallel
    to the screen at full reach ``L = max(tip) - defMastX`` the heading is
    ``phi = acos((tip - defMastX) / L)`` degrees from screen right (+X) toward the viewer (+Z).
    The track must be two-level (a rest hold and an out hold): the transitions between holds are
    re-drawn as cosine eases over the measured frames, which keeps the DEF timing and removes the
    one-pixel steps of the sprite."""
    x0, y0, x1, y1 = p["defTipWindow"]
    run = int(p.get("tipRunPx", 3))
    tips = []
    for fr in frames:
        op = fr > 7
        best = None
        for y in range(y0, y1 + 1):
            for x in range(x1, x0 + run - 2, -1):
                if op[y, x - run + 1:x + 1].all():
                    best = x if best is None else max(best, x)
                    break
        if best is None:
            raise SystemExit("slew track found no jib tip in a DEF frame")
        tips.append(best)
    tips = np.array(tips, float)
    mast = float(p["defMastX"])
    reach = tips.max() - mast
    phi = np.degrees(np.arccos(np.clip((tips - mast) / reach, -1.0, 1.0)))
    rest_tip = float(np.bincount(tips.astype(int)).argmax())
    out_tip = float(tips.max())
    level = np.where(tips == rest_tip, 0, np.where(tips == out_tip, 1, -1))
    if (level == 0).sum() == 0 or (level == 1).sum() == 0:
        raise SystemExit("slew track is not two-level (rest hold + out hold)")
    phi_rest, phi_out = float(phi[level == 0][0]), float(phi[level == 1][0])
    n = len(frames)
    # Hold anchors: frames on a level. Between consecutive anchors on different levels, ease.
    anchors = [(k, int(level[k])) for k in range(n) if level[k] >= 0]

    def at(t: float) -> float:
        t = t % n
        prev = max((a for a in anchors if a[0] <= t), default=None, key=lambda a: a[0])
        nxt = min((a for a in anchors if a[0] >= t), default=None, key=lambda a: a[0])
        if prev is None:
            prev = (anchors[-1][0] - n, anchors[-1][1])
        if nxt is None:
            nxt = (anchors[0][0] + n, anchors[0][1])
        va = phi_rest if prev[1] == 0 else phi_out
        vb = phi_rest if nxt[1] == 0 else phi_out
        if nxt[0] == prev[0] or va == vb:
            return va
        u = (t - prev[0]) / (nxt[0] - prev[0])
        return va + (vb - va) * 0.5 * (1 - np.cos(np.pi * u))

    return {"tips": tips, "phiRaw": phi, "phiRest": phi_rest, "phiOut": phi_out, "reachPx": reach, "at": at,
            "holds": _hold_runs(level)}


def _hold_runs(level: np.ndarray) -> list[list[int]]:
    """[first, last, level] of each run of held frames (level 0 = rest, 1 = out)."""
    runs, k, n = [], 0, len(level)
    while k < n:
        if level[k] < 0:
            k += 1
            continue
        j = k
        while j + 1 < n and level[j + 1] == level[k]:
            j += 1
        runs.append([k, j, int(level[k])])
        k = j + 1
    return runs


def build_parts(mesh: MeshData, info, frames, pal, spec_row: dict, diag: dict) -> list[dict]:
    frame_ms = float(spec_row.get("frameMs", DEFAULT_FRAME_MS))
    n = len(frames)
    loop_s = n * frame_ms / 1000.0
    kt = np.arange(n * PART_KEYS_PER_DEF_FRAME + 1) / PART_KEYS_PER_DEF_FRAME  # in DEF frames
    taken = np.zeros(len(mesh.F), bool)
    out, diag_parts = [], []
    for i, p in enumerate(spec_row["parts"]):
        faces = select_part_faces(mesh, info, p, taken)
        taken[faces] = True
        hx, hy = p["pivotOrtho"]
        mx, my = ortho_px_to_model(info, hx, hy)
        px, py, c = _ortho_face_px(mesh, info)
        near = faces[np.hypot(px[faces] - hx, py[faces] - hy) <= float(p.get("pivotDepthRadiusPx", 40))]
        if len(near) == 0:
            raise SystemExit(f"part {i}: no part faces within the pivot depth radius")
        mz = float(c[near, 2].mean())
        if "pivotModel" in p:  # explicit, inspected model-space hinge (e.g. a mast's centre line)
            mx, my, mz = (float(v) for v in p["pivotModel"])
        axis = np.asarray(p["axis"], float)
        d: dict = {"kind": p["kind"], "faces": int(len(faces)), "pivotOrtho": [hx, hy],
                   "pivotModel": [round(mx, 4), round(my, 4), round(mz, 4)], "axis": axis.tolist()}
        angle = np.zeros_like(kt)
        lift = np.zeros_like(kt)
        if p["kind"] == "swing":
            tr = def_swing_track(frames, pal, p)
            coef = _harmonic_fit(tr["raw"], int(p.get("harmonics", 1)))
            coef[0] = 0.0  # the mesh sculpt hangs at rest; the loop mean is the rest pose
            angle = _eval_harmonic(coef, n, kt)
            fit = _eval_harmonic(coef, n, np.arange(n, dtype=float))
            d.update({"leverPx": round(tr["leverPx"], 2), "planeProjection": p.get("planeProjection", 1.0),
                      "defAngleDeg": [round(float(v), 2) for v in tr["raw"]],
                      "fitAngleDeg": [round(float(v), 2) for v in fit],
                      "fitRmsDeg": round(float(np.sqrt(np.mean((fit - (tr["raw"] - tr["raw"].mean())) ** 2))), 3),
                      "amplitudeDeg": round(float(np.abs(angle).max()), 2),
                      "centroidX": [round(float(v), 2) for v in tr["centroidX"]]})
        elif p["kind"] == "slew":
            # Rotation about +Y (right-handed) takes +Z toward +X, i.e. lowers the heading phi.
            tr = def_slew_track(frames, p)
            mesh_heading = float(p["meshHeadingDeg"])
            angle = np.array([mesh_heading - tr["at"](float(t)) for t in kt])
            d.update({"defTipX": [int(v) for v in tr["tips"]], "reachPx": tr["reachPx"],
                      "phiRestDeg": round(tr["phiRest"], 2), "phiOutDeg": round(tr["phiOut"], 2),
                      "meshHeadingDeg": mesh_heading, "holds": tr["holds"],
                      "angleRestDeg": round(mesh_heading - tr["phiRest"], 2),
                      "angleOutDeg": round(mesh_heading - tr["phiOut"], 2)})
        else:
            raise SystemExit(f"unknown part kind {p['kind']}")
        out.append({
            "faces": faces.tolist(),
            "name": f"{PART_PIVOT_PREFIX}{i}_pivot",
            "kind": p["kind"],
            "parent": int(p.get("parent", -1)),
            "pivot": [float(mx), float(my), mz],
            "axis": axis.tolist(),
            "pivotRotation": _quat_from_z_to(axis),
            "loopSeconds": round(loop_s, 4),
            "keyTimes": [round(float(t * frame_ms / 1000.0), 5) for t in kt],
            "angleDeg": [round(float(v), 4) for v in angle],
            "lift": [round(float(v), 6) for v in lift],
        })
        diag_parts.append(d)
    diag["parts"] = diag_parts
    return out


def segment_wheels(mesh: MeshData, spec_row: dict, diag: dict) -> list[dict]:
    """Rotors for wheels the DEF shows at an angle or edge-on (so the DEF motion disc cannot place
    them on a front sculpt): each wheel is the welded pieces lying wholly inside a model-space
    cylinder (``centreModel``, ``radius``, ``halfWidth`` along the shared ``axis``); a piece inside
    two cylinders goes to the nearer centre. The hub is re-centred on the selected geometry. The
    spin rate is the DEF measurement given in ``defDegPerFrame`` (+ = counter-clockwise seen from
    the side the axis points to), recorded with how it was measured."""
    V, F = mesh.V, mesh.F
    axis = np.asarray(spec_row["axis"], float)
    axis /= np.linalg.norm(axis)
    c = V[F].mean(1)
    comp = welded_components(V, F)
    wheels = spec_row["wheels"]
    inside = []
    for w in wheels:
        ctr = np.asarray(w["centreModel"], float)
        d = c - ctr
        along = d @ axis
        radial = np.linalg.norm(d - np.outer(along, axis), axis=1)
        inside.append((np.abs(along) <= float(w["halfWidth"])) & (radial <= float(w["radius"])))
    owner = np.full(len(F), -1)
    # Static pieces sitting between wheels (couplings, axle bosses): explicit, inspected piece
    # centres (centre of the piece's face-centroid extent), matched within 0.02 model units.
    excl = [np.asarray(p, float) for p in spec_row.get("excludePieceCentres", [])]
    excluded = 0
    for u in np.unique(comp[np.logical_or.reduce(inside)]):
        f = comp == u
        full = [i for i in range(len(wheels)) if inside[i][f].all()]
        if not full:
            continue
        box_ctr = (c[f].min(0) + c[f].max(0)) / 2
        if any(np.linalg.norm(box_ctr - e) <= 0.02 for e in excl):
            excluded += 1
            continue
        pc = c[f].mean(0)
        best = min(full, key=lambda i: np.linalg.norm(pc - np.asarray(wheels[i]["centreModel"], float)))
        owner[f] = best
    frame_ms = float(spec_row.get("frameMs", DEFAULT_FRAME_MS))
    step = float(spec_row["defDegPerFrame"])
    out, dw = [], []
    for i, w in enumerate(wheels):
        faces = np.nonzero(owner == i)[0]
        if len(faces) < int(w.get("minFaces", 50)):
            raise SystemExit(f"wheel {i} kept only {len(faces)} faces")
        pts = V[np.unique(F[faces])]
        # The wheel's own frame from PCA: normal = least-variance direction (signed like the spec
        # axis), major/minor in-plane axes. Meshy sculpts a wheel it saw at an angle as an oval, so
        # a rigid spin would turn the oval outline; an oval wheel (minor/major < ovalBelow)
        # spins as T R S Spin S^-1 R^-1 T^-1 instead (see write_anim_glb).
        ctr = pts.mean(0)
        ev, evec = np.linalg.eigh(np.cov((pts - ctr).T))
        n = evec[:, 0] if evec[:, 0] @ axis > 0 else -evec[:, 0]
        e1 = evec[:, 2]
        e2 = np.cross(n, e1)
        p1, p2, pa = pts @ e1, pts @ e2, pts @ n
        hub = e1 * (p1.min() + p1.max()) / 2 + e2 * (p2.min() + p2.max()) / 2 + n * pa.mean()
        if "hubModel" in w:  # explicit, inspected hub (e.g. the centre of a sculpted hub cap)
            h = np.asarray(w["hubModel"], float)
            hub = h - n * (h @ n) + n * pa.mean()
        # Outline ratio from the extents (the silhouette is what must hold still; the vertex
        # spread is rim-weighted by the rivets and reads rounder or flatter than the outline).
        ratio = float((p2.max() - p2.min()) / (p1.max() - p1.min()))
        oval = ratio < float(spec_row.get("ovalBelow", 0.97))
        frame_q = _quat_from_matrix(np.stack([e1, e2, n], 1))
        tilt = float(np.degrees(np.arccos(np.clip(n @ axis, -1, 1))))
        dw.append({"faces": int(len(faces)), "hub": [round(float(v), 4) for v in hub],
                   "normal": [round(float(v), 4) for v in n], "tiltFromSpecAxisDeg": round(tilt, 2),
                   "diameterMajorMinor": [round(float(p1.max() - p1.min()), 4), round(float(p2.max() - p2.min()), 4)],
                   "minorOverMajor": round(ratio, 3), "oval": oval})
        rotor = {
            "faces": faces.tolist(),
            "pivot": [float(v) for v in hub],
            "axis": n.tolist(),
            "pivotRotation": frame_q,
            "direction": "ccw" if step > 0 else "cw",
            "degPerDefFrame": round(abs(step), 4),
            "periodSeconds": round(360.0 / abs(step) * frame_ms / 1000.0, 4),
            "gltfDegPerSecondAboutLocalZ": round(step / (frame_ms / 1000.0), 4),
        }
        if oval:
            rotor["planeScale"] = [1.0, round(ratio, 5), 1.0]
        out.append(rotor)
    if excluded != len(excl):
        raise SystemExit(f"excludePieceCentres matched {excluded} of {len(excl)} pieces")
    diag["wheels"] = dw
    diag["defDegPerFrame"] = step
    diag["excludedPieces"] = excluded
    return out


def welded_components(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Per-face id of the connected surface piece, welding coincident vertex positions."""
    key = np.round(V, 5)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    par = np.arange(inv.max() + 1)

    def find(x):
        r = x
        while par[r] != r:
            r = par[r]
        while par[x] != r:
            par[x], x = r, par[x]
        return r

    for a, b, c in inv[F]:
        ra = find(a)
        par[find(b)] = ra
        par[find(c)] = ra
    return np.array([find(x) for x in inv[F[:, 0]]])


def def_rotor_step_degrees(frames, center, radius, blades) -> float:
    """Median per-frame rotation (degrees, + = counter-clockwise on screen) of the rotor pixels."""
    cx, cy = center
    angs = np.arange(0, 360, 0.5)
    radii = np.linspace(radius * 0.35, radius * 0.95, 12)

    def polar(fr):
        vals = np.zeros((len(radii), len(angs)))
        for i, r in enumerate(radii):
            x = cx + r * np.cos(np.radians(angs))
            y = cy - r * np.sin(np.radians(angs))  # screen y down; + angle = ccw on screen
            xi = np.clip(np.floor(x).astype(int), 0, fr.shape[1] - 1)
            yi = np.clip(np.floor(y).astype(int), 0, fr.shape[0] - 1)
            vals[i] = (fr[yi, xi] > 7).astype(float) * fr[yi, xi]
        return vals - vals.mean(1, keepdims=True)

    sym = 360.0 / blades
    steps = []
    n = len(frames)
    for k in range(n):
        a = polar(frames[k])
        b = polar(frames[(k + 1) % n])
        best, best_s = 0.0, -np.inf
        for sh in np.arange(-sym / 2, sym / 2 + 1e-9, 0.5):
            idx = int(round(sh / 0.5))
            s = float((np.roll(a, idx, axis=1) * b).sum())
            if s > best_s:
                best, best_s = sh, s
        steps.append(best)
    med = float(np.median(np.array(steps)))
    # A loop must close: n steps sum to a whole number of blade spacings. Snap to it.
    turns = round(n * med / sym)
    return float(turns * sym / n) if turns else med


def _debug_overlay(img, info, frames, reg, rotors, anchors, stem):
    dbg = ROOT / "artifacts" / "map_building_anim" / "debug"
    dbg.mkdir(parents=True, exist_ok=True)
    over = img.copy()
    tints = [(255, 0, 0), (0, 90, 255), (0, 200, 0), (255, 0, 255)]
    for i, r in enumerate(rotors):
        sel = np.isin(info["fid"], np.array(r["faces"]))
        tint = np.array(tints[i % len(tints)])
        over[sel, :3] = (over[sel, :3] * 0.4 + tint * 0.6).astype(np.uint8)
        if "pivot" in r:
            x = int((r["pivot"][0] - info["lo"][0]) * info["scale"])
            y = int((info["hi"][1] - r["pivot"][1]) * info["scale"])
            over[max(0, y - 3):y + 4, max(0, x - 3):x + 4] = (255, 255, 0, 255)
    for a in anchors:
        x = (a["position"][0] - info["lo"][0]) * info["scale"]
        y = (info["hi"][1] - a["position"][1]) * info["scale"]
        xi, yi = int(x), int(y)
        over[max(0, yi - 3):yi + 4, max(0, xi - 3):xi + 4] = (0, 255, 255, 255)
    Image.fromarray(over).save(dbg / f"{stem}_front.png")


def cmd_build(args) -> int:
    spec = load_spec()
    STAGE.mkdir(parents=True, exist_ok=True)
    catalog_rows: list = []
    report: dict = {}
    for rel, row in spec.items():
        if args.only and args.only.lower() not in rel.lower():
            continue
        if row["delivery"] == "billboard":
            build_billboard_frames(row, catalog_rows, report)
        else:
            build_mesh_row(row, catalog_rows, report)
    if args.only:
        prev = json.loads(STAGE_CATALOG.read_text(encoding="utf-8")) if STAGE_CATALOG.is_file() else {"entries": []}
        merged = {e["relativePng"]: e for e in prev.get("entries", [])}
        for r in catalog_rows:
            merged[r["relativePng"]] = r
        catalog_rows = list(merged.values())
    catalog_rows.sort(key=lambda r: r["relativePng"])
    STAGE_CATALOG.write_text(json.dumps({
        "schema": CATALOG_SCHEMA,
        "generator": "tools/homm3_map_building_meshes/map_building_anim.py build",
        "entryCount": len(catalog_rows),
        "entries": catalog_rows,
    }, indent=1) + "\n", encoding="utf-8")
    rep_path = ROOT / "artifacts" / "map_building_anim" / "build_report.json"
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps(report, indent=1, default=float) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=float))
    print(f"wrote {STAGE_CATALOG} entries={len(catalog_rows)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    b = sub.add_parser("build")
    b.add_argument("--only", help="substring of relativePng to (re)build; merges into the catalog")
    args = ap.parse_args()
    return {"inventory": cmd_inventory, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
