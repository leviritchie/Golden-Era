"""volumetricFire layer: DEF-ripped, view-independent fire as native Unity ParticleSystems on the body.

The contract is in docs/homm3_unit_look_pipeline.md ("volumetricFire"). In short:

- **Texture (DEF-ripped).** The DEF's own looping fire (``source.defGroup`` / ``frames``, a group where the
  fire boils in place and the silhouette does not move) is cut into fixed windows. Each window is taken at
  the same DEF position in every listed frame, so one window is an N-frame flipbook of the DEF's real flicker
  at that spot. Three banks:
    tongues  windows hung from the silhouette's upper edge (the crest), ragged-bottomed, lens-clipped;
    body     windows inside the fire, teardrop-clipped (the boil on the body surface);
    embers   detached specks (single-frame cells).
  The fire pixels are ``opaque & luma >= minLuma & R - B >= minWarmth`` (``source.fireMask``).
- **Volume (view independence).** Particles are emitted from the skinned body surface (the triangles whose
  UV centroid lies inside ``emitter`` - a ``lighting.regions`` name, a ``maskPath``, or the whole body) and
  drawn as camera-facing, point-filtered, alpha-blended billboards that depth-test against the body. The fire
  is therefore a shell of flame sprites around the 3D surface: whatever the facing, the rim shows tongues
  standing off the silhouette and the facing side shows boiling flame; the far side is hidden by the body.
  Nothing is a baked view.
- **Timing.** Each particle steps through its window's flipbook at 12 fps (the DEF redraws its fire every
  frame at 12 fps) from a random phase, so the flicker is the DEF's own; births are continuous
  (``rateOverTime``), scaled per key by the clip's multiplier.
- **Density.** ``coverage`` is the fraction of the emitter's visible projected area the system's live
  sprites cover. The expected live count is ``coverage * A / (2 * s)`` (A = the emitter's rest-pose world
  area, s = the mean opaque sprite area in world units; a closed surface projects A/4 on average and half
  the particles face away). The rate is live count / mean lifetime.

The unlit particle material is what makes the body read as fire: Hex/Lit has no emission, so no base colour
can glow; unlit DEF flame pixels over the body do. Proof tier of this module's output: generated artifact.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import spec as S

sys.path.insert(0, str(S.ROOT / "tools/homm3_vfx"))
import h3def  # noqa: E402

FPS = 12.0
LUMA = np.array([0.299, 0.587, 0.114], np.float32)
SYSTEMS = ("tongues", "body", "embers")
SYSTEM_KEYS = {
    "tongues": {"windows", "cellPx", "baseAt", "coverage", "heightRange", "minUp", "lifetimeDefFrames", "riseDefPxPerFrame",
                "sizeJitter", "seed", "notes"},
    "body": {"windows", "cellPx", "coverage", "heightRange", "minUp", "lifetimeDefFrames", "riseDefPxPerFrame", "sizeJitter", "seed",
             "normalOffsetDefPx", "notes"},
    "embers": {"perSecond", "heightRange", "minUp", "lifetimeDefFrames", "riseDefPxPerFrame", "spreadDefPx", "minPx", "seed", "notes"},
}
SOURCE_KEYS = {"def", "defGroup", "frames", "fireMask"}   # def omitted = the unit's own frames (unit_frame_source)
FIRE_MASK_KEYS = {"minLuma", "minWarmth"}
EMITTER_KEYS = {"region", "maskPath", "bones", "excludeBones", "threshold"}
DEFAULTS = {
    "tongues": {"windows": 24, "cellPx": [16, 40], "baseAt": 0.8, "coverage": 0.5,
                "lifetimeDefFrames": [4, 8], "riseDefPxPerFrame": 1.0, "sizeJitter": 0.2, "seed": 1},
    "body": {"windows": 24, "cellPx": [12, 22], "coverage": 0.8, "lifetimeDefFrames": [3, 6],
             "riseDefPxPerFrame": 0.5, "sizeJitter": 0.2, "seed": 2, "normalOffsetDefPx": 2},
    "embers": {"perSecond": 24, "lifetimeDefFrames": [6, 12], "riseDefPxPerFrame": 3.0, "spreadDefPx": 1.5,
               "minPx": 2, "seed": 3},
}
EMITTER_TEX = 512


# ------------------------------------------------------------------ validation (called by spec.validate)
def validate(e: list, w: str, ly: dict, spec: dict, clips) -> None:
    src = ly.get("source")
    if not isinstance(src, dict):
        e.append(f"{w}: source {{defGroup, frames}} required")
        src = {}
    else:
        for k in src:
            if k not in SOURCE_KEYS:
                e.append(f"{w}.source: unknown key {k!r}")
        if not isinstance(src.get("defGroup"), int) or src.get("defGroup") < 0:
            e.append(f"{w}.source.defGroup must be an int >= 0")
        fr = src.get("frames")
        if not (isinstance(fr, list) and len(fr) >= 2 and all(isinstance(x, int) and x >= 0 for x in fr)):
            e.append(f"{w}.source.frames must list >= 2 DEF frame indices (a looping group)")
        fm = src.get("fireMask", {})
        if not isinstance(fm, dict) or any(k not in FIRE_MASK_KEYS for k in fm) \
                or not all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in fm.values()):
            e.append(f"{w}.source.fireMask must be {{minLuma, minWarmth}} numbers in [0, 255]")
    em = ly.get("emitter", {})
    if not isinstance(em, dict) or any(k not in EMITTER_KEYS for k in em):
        e.append(f"{w}.emitter keys are {sorted(EMITTER_KEYS)}")
    else:
        if sum(k in em for k in ("region", "maskPath", "bones")) > 1:
            e.append(f"{w}.emitter: region, maskPath and bones are exclusive")
        for k in ("bones", "excludeBones"):
            if k in em and not (isinstance(em[k], list) and em[k] and all(isinstance(x, str) and x for x in em[k])):
                e.append(f"{w}.emitter.{k} must be a non-empty list of joint-name globs")
        if "excludeBones" in em and "bones" not in em and ("region" in em or "maskPath" in em):
            e.append(f"{w}.emitter.excludeBones combines only with bones or the whole body")
        if "region" in em:
            names = {r.get("name") for r in spec.get("lighting", {}).get("regions", [])}
            if em["region"] not in names:
                e.append(f"{w}.emitter.region {em['region']!r} is not a lighting.regions name")
        if "maskPath" in em and not (S.ROOT / em["maskPath"]).exists():
            e.append(f"{w}.emitter.maskPath {em['maskPath']} does not exist")
        th = em.get("threshold", 0.5)
        if not (isinstance(th, (int, float)) and 0 < th < 1):
            e.append(f"{w}.emitter.threshold must be in (0, 1)")
    unit = spec.get("unit")
    if unit and isinstance(em, dict) and any(k in em for k in ("bones", "excludeBones")) and S.glb_exists(unit):
        import fnmatch
        g = _glb(unit)
        joints = [n.get("name", "") for sk in g.json.get("skins", []) for n in (g.json["nodes"][j] for j in sk["joints"])]
        for k in ("bones", "excludeBones"):
            for pat in em.get(k, []) if isinstance(em.get(k), list) else []:
                if not any(fnmatch.fnmatchcase(j, pat) for j in joints):
                    e.append(f"{w}.emitter.{k} glob {pat!r} matches no joint of the unit's GLB skin")
    if isinstance(src.get("defGroup"), int) and isinstance(src.get("frames"), list):
        name = src.get("def")
        try:
            name = name or unit_frame_source(unit)
            n = group_len(name, src["defGroup"])
            if not n or any(isinstance(f, int) and f >= n for f in src["frames"]):
                e.append(f"{w}.source: {name} group {src['defGroup']} has {n} frames; frames {src['frames']} out of range")
        except (OSError, ValueError, KeyError) as ex:
            e.append(f"{w}.source {name or unit!r} does not load: {ex}")
    sy = ly.get("systems")
    if not isinstance(sy, dict) or not sy or any(k not in SYSTEMS for k in sy):
        e.append(f"{w}.systems must map a non-empty subset of {SYSTEMS} to settings")
        sy = {}
    for name, cfg in sy.items():
        if name not in SYSTEMS:
            continue
        sw = f"{w}.systems.{name}"
        if not isinstance(cfg, dict):
            e.append(f"{sw} must be an object")
            continue
        for k in cfg:
            if k not in SYSTEM_KEYS[name]:
                e.append(f"{sw}: unknown key {k!r}")
        c = {**DEFAULTS[name], **cfg}
        lt = c["lifetimeDefFrames"]
        if not (isinstance(lt, list) and len(lt) == 2 and all(isinstance(x, (int, float)) for x in lt) and 1 <= lt[0] <= lt[1]):
            e.append(f"{sw}.lifetimeDefFrames must be [min, max] with 1 <= min <= max")
        if "coverage" in c and not (isinstance(c["coverage"], (int, float)) and 0 < c["coverage"] <= 4):
            e.append(f"{sw}.coverage must be in (0, 4]")
        if "cellPx" in c and not (isinstance(c["cellPx"], list) and len(c["cellPx"]) == 2
                                  and all(isinstance(x, int) and 4 <= x <= 128 for x in c["cellPx"])):
            e.append(f"{sw}.cellPx must be [w, h] ints in [4, 128]")
        if "windows" in c and not (isinstance(c["windows"], int) and 1 <= c["windows"] <= 64):
            e.append(f"{sw}.windows must be an int in [1, 64]")
        if "baseAt" in c and not (isinstance(c["baseAt"], (int, float)) and 0.5 <= c["baseAt"] <= 1):
            e.append(f"{sw}.baseAt must be in [0.5, 1]")
        hr = c.get("heightRange", [0.0, 1.0])
        if not (isinstance(hr, list) and len(hr) == 2 and all(isinstance(x, (int, float)) for x in hr) and 0 <= hr[0] < hr[1] <= 1):
            e.append(f"{sw}.heightRange must be [lo, hi] with 0 <= lo < hi <= 1")
        if "minUp" in c and not (isinstance(c["minUp"], (int, float)) and -1 <= c["minUp"] <= 1):
            e.append(f"{sw}.minUp must be in [-1, 1]")
        if "perSecond" in c and not (isinstance(c["perSecond"], (int, float)) and c["perSecond"] > 0):
            e.append(f"{sw}.perSecond must be > 0")
    ca = ly.get("clearAt", {})
    if not isinstance(ca, dict) or not all(isinstance(v, int) and v >= 0 for v in ca.values()):
        e.append(f"{w}.clearAt must map clip -> DEF key index (int >= 0)")
        ca = {}
    for cn, k in ca.items():
        if cn not in (ly.get("clips") or {}):
            e.append(f"{w}.clearAt names clip {cn!r} that is not in clips")
        elif clips is not None and cn in clips and k >= len(clips[cn]["defFrames"]):
            e.append(f"{w}.clearAt.{cn} = {k} is past the clip's {len(clips[cn]['defFrames'])} keys")
    cl = ly.get("clips")
    if not isinstance(cl, dict) or not cl:
        e.append(f"{w}: clips must map clip -> emission multiplier (number or per-DEF-frame list)")
        cl = {}
    for cn, m in cl.items():
        if isinstance(m, (int, float)):
            ok = m >= 0
        else:
            ok = isinstance(m, list) and m and all(isinstance(x, (int, float)) and x >= 0 for x in m)
        if not ok:
            e.append(f"{w}.clips.{cn} must be a number >= 0 or a list of numbers >= 0")
            continue
        if clips is not None:
            if cn not in clips:
                e.append(f"{w}: clip {cn!r} is not a built clip")
            elif isinstance(m, list) and len(m) != len(clips[cn]["defFrames"]):
                e.append(f"{w}.clips.{cn} has {len(m)} values for {len(clips[cn]['defFrames'])} DEF frames")


# ------------------------------------------------------------------ DEF banks
def _is_dir_source(name: str) -> bool:
    return Path(name).suffix.lower() == ".dir"


def unit_frame_source(unit: str) -> str:
    """The unit's own frame source: its DEF name when the game LODs hold it, else the extracted ``<name>.dir``
    of GG_FF.png frames its retarget was built from (alt / HotA packs such as lvl5Alt). Explicit, not a fallback:
    the frames the retarget used are the frames the fire is ripped from."""
    src = Path(S.frames_meta(unit)["sources"][0]).parent
    dname = S.def_name(unit)
    try:
        h3def.lod_read(dname.lower(), h3def.DEFAULT_LODS)
        return dname
    except FileNotFoundError:
        return str(src)


def group_len(name: str, group: int) -> int:
    if _is_dir_source(name):
        return len(list(Path(name).glob(f"{group:02d}_*.png")))
    return len(h3def.read_def(name.lower()).groups.get(group, []))


def read_frame(name: str, group: int, frame: int, d=None) -> np.ndarray:
    """RGBA of one frame with the selection outline cleared (DEF) and shadow kept at alpha < 255."""
    if _is_dir_source(name):
        p = Path(name) / f"{group:02d}_{frame:02d}.png"
        if not p.is_file():
            raise ValueError(f"{p} does not exist")
        return np.array(Image.open(p).convert("RGBA"))
    d = d or h3def.read_def(name.lower())
    fr = d.groups[group][frame]
    rgba = h3def.to_rgba(fr, d.palette)
    rgba[fr.idx == 5] = 0                           # selection outline slot
    return rgba


def load_frames(name: str, group: int, frames: list[int]) -> list[np.ndarray]:
    """``name`` is a DEF in the game LODs or an extracted ``<name>.dir`` of GG_FF.png frames."""
    n = group_len(name, group)
    if not n:
        raise ValueError(f"{name} has no group {group}")
    bad = [f for f in frames if f >= n]
    if bad:
        raise ValueError(f"{name} group {group} has {n} frames; {bad} out of range")
    d = None if _is_dir_source(name) else h3def.read_def(name.lower())
    out = []
    for f in frames:
        rgba = read_frame(name, group, f, d)
        rgba[rgba[..., 3] < 255] = 0                # shadow slots are not fire
        out.append(rgba)
    return out


def fire_mask(rgba: np.ndarray, rule: dict) -> np.ndarray:
    rgb = rgba[..., :3].astype(np.float32)
    luma = rgb @ LUMA
    return (rgba[..., 3] == 255) & (luma >= rule.get("minLuma", 100)) & (rgb[..., 0] - rgb[..., 2] >= rule.get("minWarmth", 40))


def _cut(rgba, m):
    out = np.zeros_like(rgba)
    out[m] = rgba[m]
    out[..., 3] = np.where(m, 255, 0)
    return out


def _lens(h, w, rng, pointed_top=True):
    """Flame envelope over a (h, w) window: a pointed top, a rounded bottom and a slightly ragged edge."""
    t = (np.arange(h)[:, None] + 0.5) / h
    prof = np.sin(np.pi * np.clip(t, 0, 1) ** (1.6 if pointed_top else 1.0)) ** 0.7   # widest at 0.65 h
    half = 0.5 * w * np.clip(prof, 0, 1) + rng.normal(0, 0.6, (h, 1))
    cx = 0.5 * w + ndimage.gaussian_filter1d(rng.normal(0, 0.9, h), 2)[:, None]
    x = np.arange(w)[None, :] + 0.5
    return np.abs(x - cx) <= half


def _main_component(fire):
    lab, n = ndimage.label(fire, np.ones((3, 3)))
    if not n:
        return fire
    return lab == 1 + int(np.argmax(ndimage.sum(fire, lab, np.arange(1, n + 1))))


def tongue_bank(frames, fires, cfg):
    """Windows hung from the silhouette's upper edge (main component only, so stray specks do not lift the
    window): one N-frame flipbook per window, lens-clipped (pointed top, rounded bottom)."""
    cw, chh = cfg["cellPx"]
    rng = np.random.default_rng(cfg["seed"])
    mains = [_main_component(f) for f in fires]
    union = np.any(mains, 0)
    H, W = union.shape
    tops = np.stack([np.where(m.any(0), np.argmax(m, 0), H) for m in mains])      # (N, W) first fire row per column
    ys = np.nonzero(union.any(1))[0]
    xs_all = np.nonzero(union.any(0))[0]
    y_top, height = ys.min(), ys.max() - ys.min()
    med_top = np.median(tops, 0)
    cand = [x for x in xs_all if med_top[x] < y_top + 0.6 * height]                 # crest columns
    if not cand:
        return []
    n = min(cfg["windows"], len(cand))
    xs = np.sort(rng.choice(cand, size=n, replace=False))
    seqs = []
    for xc in xs:
        x0 = int(np.clip(xc - cw // 2, 0, W - cw))
        ytop = int(np.clip(np.median(tops[:, x0:x0 + cw].min(1)) - 0.12 * chh, 0, H - chh))
        env = _lens(chh, cw, rng)
        seq = [_cut(rgba[ytop:ytop + chh, x0:x0 + cw], fires[f][ytop:ytop + chh, x0:x0 + cw] & env)
               for f, rgba in enumerate(frames)]
        px = [int((c[..., 3] > 0).sum()) for c in seq]
        if min(px) >= 0.12 * cw * chh:
            seqs.append({"cells": seq, "defXY": [x0, ytop]})
    return seqs


def body_bank(frames, fires, cfg):
    """Teardrop windows inside the fire (fire in every frame under the window centre)."""
    cw, chh = cfg["cellPx"]
    rng = np.random.default_rng(cfg["seed"])
    solid = np.all(fires, 0)
    solid = ndimage.binary_erosion(solid, np.ones((max(3, chh // 3), max(3, cw // 2)), bool))
    ys, xs = np.nonzero(solid)
    if not len(ys):
        return []
    n = min(cfg["windows"], len(ys))
    pick = rng.choice(len(ys), size=n, replace=False)
    H, W = solid.shape
    seqs = []
    for k in pick:
        y0 = int(np.clip(ys[k] - chh // 2, 0, H - chh))
        x0 = int(np.clip(xs[k] - cw // 2, 0, W - cw))
        env = _lens(chh, cw, rng)
        seq = [_cut(rgba[y0:y0 + chh, x0:x0 + cw], fires[f][y0:y0 + chh, x0:x0 + cw] & env) for f, rgba in enumerate(frames)]
        seqs.append({"cells": seq, "defXY": [x0, y0]})
    return seqs


def ember_bank(frames, fires, cfg):
    """Detached fire specks (components off the main silhouette), single cells padded to one size."""
    out = []
    for f, rgba in enumerate(frames):
        op = rgba[..., 3] == 255
        lab, n = ndimage.label(op, np.ones((3, 3)))
        if not n:
            continue
        sizes = ndimage.sum(op, lab, np.arange(1, n + 1))
        main = 1 + int(np.argmax(sizes))
        for i, sl in enumerate(ndimage.find_objects(lab)):
            if i + 1 == main:
                continue
            m = (lab[sl] == i + 1) & fires[f][sl]
            if m.sum() >= cfg["minPx"]:
                out.append(_cut(rgba[sl], m))
    if not out:
        return []
    ch = max(c.shape[0] for c in out)
    cw = max(c.shape[1] for c in out)
    cells = []
    for c in out[:64]:
        pad = np.zeros((ch, cw, 4), np.uint8)
        y, x = (ch - c.shape[0]) // 2, (cw - c.shape[1]) // 2
        pad[y:y + c.shape[0], x:x + c.shape[1]] = c
        cells.append({"cells": [pad], "defXY": None})
    return cells


def pack(seqs, base_at=None):
    """Sheet: one row per window, one column per frame. ``base_at`` pads the bottom so the emission point
    (base_at of the window height from its top) is the cell centre, the billboard's pivot."""
    cells = [s["cells"] for s in seqs]
    ch, cw = cells[0][0].shape[:2]
    pad = 0
    if base_at is not None:
        pad = int(round((2 * base_at - 1) * ch))
    rows, cols = len(cells), len(cells[0])
    sheet = np.zeros((rows * (ch + pad), cols * cw, 4), np.uint8)
    for r, seq in enumerate(cells):
        for c, cell in enumerate(seq):
            sheet[r * (ch + pad):r * (ch + pad) + ch, c * cw:(c + 1) * cw] = cell
    opaque = np.mean([[(cell[..., 3] > 0).sum() for cell in seq] for seq in cells])
    return sheet, [cw, ch + pad], float(opaque)


# ------------------------------------------------------------------ emitter
def _glb(unit):
    from glbpatch import Glb
    return Glb(S.glb_bytes(unit))


def emitter_weight(ly, spec, unit) -> np.ndarray | None:
    """Texture-space emitter weight (top-down glTF UV), or None (whole body, or a bones emitter)."""
    em = ly.get("emitter", {})
    if "region" in em:
        import regions
        reg = next(r for r in spec["lighting"]["regions"] if r["name"] == em["region"])
        return regions.texture_weight(reg, S.glb_bytes(unit), 512)
    if "maskPath" in em:
        return np.asarray(Image.open(S.ROOT / em["maskPath"]).convert("L").resize((512, 512), Image.BILINEAR), np.float32) / 255
    return None


def emitter_triangles(ly, spec, unit):
    """Per body triangle (rest pose): area, region selection, vertex-normal up component, centroid height as a
    fraction of the body's height. The region weight is sampled nearest at the UV centroid from the SAVED
    emitter mask (EMITTER_TEX), the same image and rule the Unity builder uses."""
    import regions
    g = _glb(unit)
    wmap = emitter_weight(ly, spec, unit)
    img = None
    if wmap is not None:
        img = Image.fromarray((np.clip(wmap, 0, 1) * 255).astype(np.uint8)).resize((EMITTER_TEX, EMITTER_TEX), Image.BILINEAR)
        wmap = np.asarray(img, np.float32) / 255
    th = ly.get("emitter", {}).get("threshold", 0.5)
    em = ly.get("emitter", {})
    mi = g.body_mesh_index()
    bone_w = None
    if "bones" in em or "excludeBones" in em:
        inc = regions.vertex_values(g, {"bones": em.get("bones", ["*"])})
        exc = regions.vertex_values(g, {"bones": em["excludeBones"]}) if "excludeBones" in em else None
        bone_w = [np.clip(v - (exc[k][2] if exc else 0), 0, 1) for k, (_, _, v) in enumerate(inc)]
    A, SEL, UP, HY = [], [], [], []
    for pi, p in enumerate(g.json["meshes"][mi]["primitives"]):
        P = regions.accessor(g, p["attributes"]["POSITION"]).astype(np.float64)
        N = regions.accessor(g, p["attributes"]["NORMAL"]).astype(np.float64) if "NORMAL" in p["attributes"] else None
        UV = regions.accessor(g, p["attributes"]["TEXCOORD_0"]).astype(np.float64)
        I = regions.accessor(g, p["indices"]).reshape(-1, 3).astype(np.int64)
        fn = np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]])
        A.append(0.5 * np.linalg.norm(fn, axis=1))
        n = N[I].mean(1) if N is not None else fn
        UP.append(n[:, 1] / np.maximum(np.linalg.norm(n, axis=1), 1e-12))
        HY.append(P[I].mean(1)[:, 1])
        if bone_w is not None:
            SEL.append(bone_w[pi][I].mean(1) >= th)
        elif wmap is None:
            SEL.append(np.ones(len(I), bool))
        else:
            c = UV[I].mean(1)
            px = np.clip((c * EMITTER_TEX).astype(int), 0, EMITTER_TEX - 1)
            SEL.append(wmap[px[:, 1], px[:, 0]] >= th)
    hy = np.concatenate(HY)
    y0, y1 = float(hy.min()), float(hy.max())
    tri = {"area": np.concatenate(A), "sel": np.concatenate(SEL), "up": np.concatenate(UP),
           "h": (hy - y0) / max(y1 - y0, 1e-9), "yRange": [y0, y1]}
    return tri, img


def system_filter(tri, cfg):
    lo, hi = cfg.get("heightRange", [0.0, 1.0])
    m = tri["sel"] & (tri["h"] >= lo) & (tri["h"] <= hi)
    if "minUp" in cfg:
        m &= tri["up"] >= cfg["minUp"]
    return m


# ------------------------------------------------------------------ build
def clip_multipliers(ly, clips_ctx):
    out = {}
    for cn, m in ly["clips"].items():
        n = len(clips_ctx[cn]["defFrames"]) if clips_ctx and cn in clips_ctx else (len(m) if isinstance(m, list) else 1)
        out[cn] = [float(x) for x in m] if isinstance(m, list) else [float(m)] * n
    return out


def build(ly, spec, unit, ppu: float, vdir: Path, clips_ctx=None, def_name=None) -> dict:
    """Write the layer's sheets (+ emitter mask) into ``vdir``; return its manifest entry."""
    src = ly["source"]
    dname = src.get("def") or unit_frame_source(unit)
    frames = load_frames(dname, src["defGroup"], src["frames"])
    fires = [fire_mask(f, src.get("fireMask", {})) for f in frames]
    tri, img = emitter_triangles(ly, spec, unit)
    em = ly.get("emitter", {})
    emitter = {"areaWorld": round(float(tri["area"][tri["sel"]].sum()), 5), "triangles": int(tri["sel"].sum()),
               "bodyTriangles": len(tri["sel"]), "threshold": ly.get("emitter", {}).get("threshold", 0.5),
               "bones": em.get("bones"), "excludeBones": em.get("excludeBones"),
               "selection": "bones: mean over the triangle's vertices of (skin weight on joints matching bones - weight on "
                            "excludeBones), clipped to [0, 1], >= threshold; mask: triangle UV centroid, nearest texel, "
                            ">= threshold; whole body otherwise. Then per system "
                            "heightRange (centroid y as a fraction of the rest body's triangle-centroid y range) and minUp "
                            "(mean vertex normal's up component, rest pose)",
               "restCentroidYRange": [round(v, 5) for v in tri["yRange"]], "mask": None}
    if img is not None:
        mname = f"{ly['id']}__emitter.png"
        img.save(vdir / mname)
        emitter["mask"] = mname
        emitter["maskUv"] = "top-down glTF UV (v down); Unity samples at (u, 1 - v)"
    systems = {}
    for name in SYSTEMS:
        if name not in ly["systems"]:
            continue
        cfg = {**DEFAULTS[name], **ly["systems"][name]}
        if name == "tongues":
            seqs, base = tongue_bank(frames, fires, cfg), cfg["baseAt"]
        elif name == "body":
            seqs, base = body_bank(frames, fires, cfg), None
        else:
            seqs, base = ember_bank(frames, fires, cfg), None
        if not seqs:
            raise ValueError(f"layer {ly['id']}: the {name} bank is empty (fireMask too strict for {dname} g{src['defGroup']}?)")
        sheet, cell, opaque_px = pack(seqs, base)
        sname = f"{ly['id']}__{name}.png"
        Image.fromarray(sheet).save(vdir / sname)
        lt = [cfg["lifetimeDefFrames"][0] / FPS, cfg["lifetimeDefFrames"][1] / FPS]
        fm = system_filter(tri, cfg)
        if not fm.any():
            raise ValueError(f"layer {ly['id']}: the {name} emitter filter selects no triangle")
        em_area = float(tri["area"][fm].sum())
        sprite_area = opaque_px / (ppu * ppu)
        if name == "embers":
            rate = float(cfg["perSecond"])
            live = rate * 0.5 * (lt[0] + lt[1])
        else:
            live = cfg["coverage"] * em_area / (2.0 * max(sprite_area, 1e-9))
            rate = live / (0.5 * (lt[0] + lt[1]))
        frames_n = len(seqs[0]["cells"])
        systems[name] = {
            "sheet": sname, "tilesX": frames_n, "tilesY": len(seqs), "cellPx": cell,
            "sizeWorld": [round(cell[0] / ppu, 5), round(cell[1] / ppu, 5)],
            "sizeJitter": cfg.get("sizeJitter", 0.0),
            "flipbook": {"fps": FPS, "row": "random", "startFrame": "random" if frames_n > 1 else 0},
            "lifetimeS": [round(x, 5) for x in lt],
            "ratePerSecond": round(rate, 3), "expectedLive": round(live, 1),
            "riseWorldPerS": round(cfg["riseDefPxPerFrame"] * FPS / ppu, 5),
            "spreadWorldPerS": round(cfg.get("spreadDefPx", 0) * FPS / ppu, 5),   # +- sideways drift (x, z)
            "normalOffsetWorld": round(cfg.get("normalOffsetDefPx", 0) / ppu, 5),
            "meanOpaqueDefPx": round(opaque_px, 1),
            "emitterFilter": {"heightRange": cfg.get("heightRange", [0.0, 1.0]), "minUp": cfg.get("minUp", -1.0)},
            "emitterTriangles": int(fm.sum()), "emitterAreaWorld": round(em_area, 5),
            "windowsDefXY": [s["defXY"] for s in seqs if s["defXY"] is not None],
            "pivot": "cell centre (tongue cells are bottom-padded so the centre is the flame base at baseAt)",
        }
    return {
        "type": "volumetricFire",
        "source": {("framesDir" if _is_dir_source(dname) else "def"): dname, "defGroup": src["defGroup"], "frames": src["frames"], "fireMask": src.get("fireMask", {})},
        "anchor": ly["anchor"], "light": ly.get("light"), "emitter": emitter, "systems": systems,
        "clips": clip_multipliers(ly, clips_ctx),
        "clearAtKey": dict(ly.get("clearAt", {})),   # all live particles removed when that key's window opens
        "unity": {"component": "ParticleSystem per system, parented to anchor.bone; shape = SkinnedMeshRenderer over "
                               "an emitter-only skinned submesh (forceRenderingOff) of the emitter triangles",
                  "simulationSpace": "World", "render": "Billboard, alignment View, sortMode Distance",
                  "material": "Sprites/Default (unlit, alpha blend), point filter, no mips",
                  "emission": "rateOverTime = ratePerSecond; the clip multiplier is a stepped curve on "
                              "EmissionModule.rateOverTime.scalar keyed on the timing rule's windows",
                  "textureSheet": "Grid, SingleRow random row, timeMode FPS 12, random start frame"},
    }


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Build a unit's volumetricFire layers standalone (lab; the vfx stage calls build()).")
    ap.add_argument("unit")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = S.load(a.unit)
    cam = json.loads((S.RETARGET / a.unit / f"{a.unit}_def_retarget.blend.spritecam.json").read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    for ly in spec["vfx"]["layers"]:
        if ly["type"] == "volumetricFire":
            res[ly["id"]] = build(ly, spec, a.unit, cam["pxPerUnit"], out)
    (out / "volfire_manifest.json").write_text(json.dumps({"unit": a.unit, "spritecam": cam, "layers": res}, indent=1))
    print(json.dumps({k: {s: {x: v[x] for x in ("tilesY", "cellPx", "ratePerSecond", "expectedLive")}
                          for s, v in e["systems"].items()} for k, e in res.items()}, indent=1))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.path.insert(0, str(S.ROOT / "tools/homm3_prebake"))
    _main()
