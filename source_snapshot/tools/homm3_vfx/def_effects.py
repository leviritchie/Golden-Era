"""Shared DEF-effect measurement for the roster VFX inventory and the DEF effect ripper.

Source of truth per unit is what the def_retarget pipeline itself consumed:
  artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.blend.frames.json
    "sources"  one extracted DEF PNG per master frame (RGBA; alpha 255 opaque, 64/128 = HoMM3 shadow slots)
    "segments" [clip, start, end) master-frame ranges, e.g. ["g12_attack_front", 46, 53]
The extraction folder next to those PNGs (<NAME>.dir + <NAME>.json) holds every DEF group, including
groups the retarget did not build (attack up/down, shoot up/down, cast).  PNGs are used rather than
the LOD because about a quarter of the roster (HotA, lvlNAlt mod sprites) is not in the SoD LODs.

Effect pixels are separated from the body by three tests, all measured from the unit's own sprite:
  novel colour  the quantised colour is (almost) absent from the unit's idle frames, so it is not
                body paint that merely moved with the pose;
  effect class  the colour is bright/saturated in a way HoMM3 uses for effects (electric white/pale
                blue, fire, magic green/cyan/purple, water blue, smoke grey);
  detached      a separate opaque component (particles, missiles, thrown things), any colour.
A steady self-effect that is present in idle (fire body, glowing orb) is not "novel"; it is measured
separately (idle_self_effect) from its share of the idle body and its frame-to-frame flicker.

Bone candidates come from the retarget's own GLB: the DEF_Master action is evaluated at master frame m
(time (m+1)/12 s) with a numpy FK and projected through the unit's calibrated SpriteCam
(<blend>.spritecam.json), so a candidate names the mesh bone that sits under the effect in that frame.
"""
from __future__ import annotations

import colorsys
import glob
import json
import os
import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = r"V:/games/Olden Era Playtest Tweak"
ART = os.path.join(ROOT, "artifacts/homm3_def_retarget")
FPS = 12.0
GROUP_NAMES = {0: "move", 1: "mouseover", 2: "idle", 3: "hitted", 4: "defence", 5: "death", 6: "death_ranged",
               7: "turn_left", 8: "turn_right", 9: "turn_left2", 10: "turn_right2", 11: "attack_up",
               12: "attack_front", 13: "attack_down", 14: "shoot_up", 15: "shoot_front", 16: "shoot_down",
               17: "cast_up", 18: "cast_front", 19: "cast_down", 20: "move_start", 21: "move_end"}
EFFECT_CLASSES = ("electric", "fire", "magic", "water", "smoke")


# ----------------------------------------------------------------------------- sprite loading
@dataclass
class UnitSprite:
    unit: str
    def_name: str
    groups: dict[int, list[str]]                 # group -> PNG paths (all groups in the extraction)
    master: list[tuple[int, int]]                # master frame -> (group, frame index)
    segments: list[tuple[str, int, int]]
    frames_json: str
    _cache: dict = field(default_factory=dict, repr=False)

    def rgba(self, path: str) -> np.ndarray:
        if path not in self._cache:
            self._cache[path] = np.asarray(Image.open(path).convert("RGBA"))
        return self._cache[path]

    def group_rgba(self, g: int) -> list[np.ndarray]:
        return [self.rgba(p) for p in self.groups.get(g, [])]

    def master_index(self, g: int, i: int) -> int | None:
        """First master frame that plays DEF group g frame i inside that group's own segment."""
        for name, s, e in self.segments:
            if int(name[1:3]) == g and s + i < e:
                return s + i
        return None


def _gf(path: str) -> tuple[int, int]:
    m = re.search(r"(\d+)_(\d+)\.png$", path.replace("\\", "/"))
    return int(m.group(1)), int(m.group(2))


def load_unit(unit: str) -> UnitSprite:
    fj = glob.glob(os.path.join(ART, unit, f"{unit}_def_retarget.blend.frames.json"))
    if not fj:
        raise FileNotFoundError(f"{unit}: no frames.json (not a built def_retarget unit)")
    fr = json.load(open(fj[0]))
    src = [s.replace("\\", "/") for s in fr["sources"]]
    ddir = os.path.dirname(src[0])
    name = os.path.basename(ddir)[:-4]
    groups: dict[int, list[str]] = {}
    seq_json = os.path.join(os.path.dirname(ddir), name + ".json")
    if os.path.exists(seq_json):
        for s in json.load(open(seq_json))["sequences"]:
            paths = [os.path.join(os.path.dirname(ddir), p.replace("\\", "/")) for p in s["frames"]]
            paths = [p for p in paths if os.path.exists(p)]
            if paths:
                groups[int(s["group"])] = paths
    else:  # materialized sources: rebuild from the directory listing
        for p in sorted(glob.glob(os.path.join(ddir, "*_*.png"))):
            g, _ = _gf(p)
            groups.setdefault(g, []).append(p.replace("\\", "/"))
    master = [_gf(s) for s in src]
    return UnitSprite(unit, name, groups, master, [tuple(x) for x in fr["segments"]], fj[0])


# ----------------------------------------------------------------------------- colour classes
def _hsv(rgb: np.ndarray):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    h = np.where(mx - mn < 1e-6, 0, h)
    return h, s, v


def colour_class(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel class index into ("other",) + EFFECT_CLASSES."""
    h, s, v = _hsv(rgb)
    luma = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    out = np.zeros(rgb.shape[:2], np.uint8)
    blue = (h >= 170) & (h < 250)
    electric = (luma >= 175) & ((s <= 0.22) | (blue & (s <= 0.65)))
    fire = ((h < 60) | (h >= 345)) & (s >= 0.5) & (v >= 0.75) & (rgb[..., 0] >= 190)
    magic = (s >= 0.45) & (v >= 0.55) & (((h >= 60) & (h < 170)) | ((h >= 250) & (h < 345)))
    water = blue & (s >= 0.3) & (v >= 0.35) & ~electric
    smoke = (s < 0.18) & (v >= 0.25) & (v < 0.75)
    for k, m in enumerate((electric, fire, magic, water, smoke), start=1):
        out[(out == 0) & m] = k
    return out


def quant(rgb: np.ndarray) -> np.ndarray:
    q = (rgb >> 3).astype(np.int32)
    return (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]


# ----------------------------------------------------------------------------- per-frame analysis
@dataclass
class UnitBaseline:
    idle_hist: np.ndarray          # counts per quantised colour over the idle frames
    idle_px: int
    novel_thresh: float
    idle_chroma: np.ndarray = None   # (n,3) chromaticity (rgb / sum) of the idle body colours
    idle_sum: np.ndarray = None      # (n,) their r+g+b

    def novel(self, rgb: np.ndarray) -> np.ndarray:
        return self.idle_hist[quant(rgb)] <= self.novel_thresh

    def relit(self, rgb: np.ndarray, mask: np.ndarray, tol: float = 0.03) -> np.ndarray:
        """Novel pixels that are an idle body colour made brighter (same chromaticity, up to 1.8x the
        brightness): the body lit by its own effect.  Lighting, not effect pixels (red dragon limbs
        lit orange by the breath keep the body ramp's chromaticity; the flame itself does not)."""
        out = np.zeros(mask.shape, bool)
        if not mask.any() or self.idle_chroma is None or not len(self.idle_chroma):
            return out
        cols, inv = np.unique(rgb[mask].reshape(-1, 3), axis=0, return_inverse=True)
        sm = cols.sum(1).astype(np.float32)
        ch = cols / np.maximum(sm, 1)[:, None]
        d = np.linalg.norm(ch[:, None, :] - self.idle_chroma[None], axis=2)
        ratio = sm[:, None] / np.maximum(self.idle_sum[None], 1)
        ok = ((d <= tol) & (ratio >= 1.0) & (ratio <= 1.8)).any(1)
        out[mask] = ok[inv.ravel()]
        return out


def baseline(us: UnitSprite, novel_max_idle_count: float | None = None) -> UnitBaseline:
    hist = np.zeros(1 << 15, np.int64)
    n = 0
    idle = us.group_rgba(2) or us.group_rgba(0)
    for a in idle:
        op = a[..., 3] == 255
        hist += np.bincount(quant(a[..., :3][op]), minlength=1 << 15)
        n += int(op.sum())
    # body paint the idle pose hides (a turned-away cloak, a gem seen from the side) shows up in the calm
    # groups too, which never draw effects: a colour present in most frames of 3+ calm groups is body paint
    calm = [g for g in (0, 7, 8, 9, 10, 20, 21) if g in us.groups]
    if len(calm) >= 3:
        votes = np.zeros(1 << 15, np.int32)
        for g in calm:
            fr = us.group_rgba(g)
            pres = np.zeros(1 << 15, np.int32)
            for a in fr:
                pres += np.bincount(quant(a[..., :3][a[..., 3] == 255]), minlength=1 << 15) > 0
            votes += pres >= max(1, 0.5 * len(fr))
        hist = hist + (votes >= 3) * (1 << 20)
    # a colour counts as body paint when it covers at least ~1 px per idle frame on average
    thresh = max(0.5, 0.6 * len(idle)) if novel_max_idle_count is None else float(novel_max_idle_count)
    body_bins = np.nonzero(hist > thresh)[0]
    cols = np.stack([(body_bins >> 10) & 31, (body_bins >> 5) & 31, body_bins & 31], 1).astype(np.float32) * 8 + 4
    sm = cols.sum(1)
    dark = sm >= 60                                   # near-black has no usable chromaticity
    return UnitBaseline(hist, n, thresh, (cols / np.maximum(sm, 1)[:, None])[dark], sm[dark])


def components(opaque: np.ndarray):
    lab, n = ndi.label(opaque, structure=np.ones((3, 3), bool))
    if n == 0:
        return lab, 0, 0, np.zeros(1, np.int64)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab, n, int(sizes.argmax()), sizes


def frame_effects(a: np.ndarray, base: UnitBaseline, classes=None, include_detached: bool = True,
                  min_component_px: int = 1) -> dict:
    """Effect masks for one RGBA frame.  Deterministic; the unit-look vfx stage calls this for
    effectMask.method "defEffects" (classes / includeDetached / minComponentPx map to the arguments,
    novelMaxIdleCount to baseline()).  "fx" is the full effect mask; "layer" is fx narrowed to
    `classes` (None = every class) plus detached components when include_detached."""
    op = a[..., 3] == 255
    rgb = a[..., :3]
    cls = colour_class(rgb)
    lab, n, main, sizes = components(op)
    body = lab == main if n else np.zeros_like(op)
    near_body = ndi.binary_dilation(body, iterations=2)
    detached = op & ~near_body
    novel = op & base.novel(rgb)
    novel &= ~base.relit(rgb, novel)
    fx_col = novel & (cls > 0) & ((cls != 5) | detached)          # smoke-grey only counts when detached
    fx = fx_col | detached
    # on-body tint (lit rims and glints painted over the body) is lighting, not a flipbook: a layer
    # keeps only pixels where effect pixels dominate their 5x5 neighbourhood or that lie off the body
    fxd = ndi.uniform_filter(fx.astype(np.float32), size=5, mode="constant")
    bodyd = ndi.uniform_filter((op & ~fx).astype(np.float32), size=5, mode="constant")
    tint = fx & (bodyd >= 0.4) & (fxd < bodyd)
    base_layer = fx & ~tint
    if classes is None:
        layer = base_layer.copy()
    else:
        layer = np.zeros_like(fx)
        for c in classes:
            if c in EFFECT_CLASSES:
                layer |= base_layer & (cls == EFFECT_CLASSES.index(c) + 1)
        if include_detached:
            layer |= base_layer & detached
    if min_component_px > 1 and layer.any():
        # clusters = layer pixels within 3 px of each other (sparks around a burst stay with it);
        # clusters smaller than min_component_px (stray lit rims, tail-tip glints) are dropped
        grp, _ = ndi.label(ndi.binary_dilation(layer, iterations=1, structure=np.ones((3, 3), bool)) , structure=np.ones((3, 3), bool))
        sizes = np.bincount(grp[layer], minlength=grp.max() + 1)
        keep = sizes >= min_component_px
        keep[0] = False
        layer = layer & keep[grp]
    return {"opaque": op, "cls": cls, "body": body, "detached": detached, "fx": fx, "tint": tint, "layer": layer, "lab": lab}


def luma(rgb):
    return rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)


def translucency(a: np.ndarray) -> dict:
    """Ghostly see-through: dithered holes inside the silhouette, and shadow-slot (semi) pixels on the body."""
    op = a[..., 3] == 255
    semi = (a[..., 3] > 0) & (a[..., 3] < 255)
    if op.sum() < 20:
        return {"dither": 0.0, "semiOnBody": 0.0}
    # checker: opaque px whose 4 neighbours are all transparent, or transparent px enclosed by opaque 4-nbrs
    p = np.pad(op, 1)
    n4 = p[:-2, 1:-1].astype(int) + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
    filled = ndi.binary_fill_holes(ndi.binary_closing(op, iterations=2))
    iso = (op & (n4 == 0)) | (~op & (n4 == 4) & filled)
    area = max(1, int(filled.sum()))
    ys = np.nonzero(op)[0]
    top, bot = ys.min(), ys.max()
    upper = np.zeros_like(op)
    upper[top:int(top + 0.7 * (bot - top)) + 1] = True     # ground shadows live in the bottom band
    return {"dither": round(float(iso.sum()) / area, 4),
            "semiOnBody": round(float((semi & filled & upper).sum()) / area, 4)}


# ----------------------------------------------------------------------------- GLB FK + SpriteCam projection
def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _slerp(q0, q1, t):
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + t * (q1 - q0)
    else:
        th = np.arccos(d)
        q = (np.sin((1 - t) * th) * q0 + np.sin(t * th) * q1) / np.sin(th)
    return q / np.linalg.norm(q)


class BoneProjector:
    """World joint positions of the def_retarget GLB's DEF_Master action, projected to DEF pixels (1x, y down)."""

    def __init__(self, unit: str):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "tools/homm3_def_retarget"))
        import articulation as A  # read-only reuse of its GLB accessor reader
        glb = os.path.join(ART, unit, f"{unit}_def_retarget.glb")
        g, acc = A.load(glb)
        self.g = g
        nodes = g["nodes"]
        self.nodes = nodes
        self.parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
        order, stack = [], [i for i in range(len(nodes)) if i not in self.parent][::-1]
        while stack:
            i = stack.pop()
            order.append(i)
            stack += nodes[i].get("children", [])[::-1]
        self.order = order
        self.rest = {i: (np.array(n.get("translation", [0, 0, 0]), float), np.array(n.get("rotation", [0, 0, 0, 1]), float),
                         np.array(n.get("scale", [1, 1, 1]), float)) for i, n in enumerate(nodes)}
        an = next((a for a in g["animations"] if a["name"].endswith("_DEF_Master")), None)
        if an is None:
            raise ValueError(f"{unit}: GLB has no *_DEF_Master action")
        self.chans = []
        for ch in an["channels"]:
            p = ch["target"].get("path")
            if p not in ("translation", "rotation", "scale") or "node" not in ch["target"]:
                continue
            s = an["samplers"][ch["sampler"]]
            self.chans.append((ch["target"]["node"], p, acc(s["input"])[:, 0].astype(float),
                               acc(s["output"]).astype(float), s.get("interpolation", "LINEAR")))
        skin = g["skins"][0]
        self.joints = {nodes[j].get("name", str(j)): j for j in skin["joints"]}
        cam = json.load(open(os.path.join(ART, unit, f"{unit}_def_retarget.blend.spritecam.json")))
        self.cam = cam
        self.right, self.up = np.array(cam["right"]), np.array(cam["up"])
        self.ppu, self.off = cam["pxPerUnit"], cam["offset"]

    def world(self, master_frame: int) -> dict[str, np.ndarray]:
        t = (master_frame + 1) / FPS
        cur = {i: [v.copy() for v in r] for i, r in self.rest.items()}
        for node, p, ti, vo, interp in self.chans:
            k = int(np.searchsorted(ti, t + 1e-5, side="right")) - 1
            if k < 0:
                v = vo[0]
            elif k >= len(ti) - 1 or interp == "STEP":
                v = vo[min(k, len(vo) - 1)]
            else:
                u = (t - ti[k]) / max(1e-9, ti[k + 1] - ti[k])
                v = _slerp(vo[k], vo[k + 1], u) if p == "rotation" else vo[k] + u * (vo[k + 1] - vo[k])
            cur[node][{"translation": 0, "rotation": 1, "scale": 2}[p]] = np.array(v, float)
        M = {}
        for i in self.order:
            tr, r, s = cur[i]
            L = np.eye(4)
            L[:3, :3] = _qmat(r) * s[None, :]
            L[:3, 3] = tr
            M[i] = (M[self.parent[i]] @ L) if i in self.parent else L
        return {n: M[j][:3, 3] for n, j in self.joints.items()}

    def project(self, p_gltf: np.ndarray) -> tuple[float, float]:
        pb = np.array([p_gltf[0], -p_gltf[2], p_gltf[1]])      # glTF (Y up) -> Blender (Z up)
        return (self.off[0] + self.ppu * float(pb @ self.right), self.off[1] - self.ppu * float(pb @ self.up))

    def pixels(self, master_frame: int) -> dict[str, tuple[float, float]]:
        return {n: self.project(p) for n, p in self.world(master_frame).items()}


def bone_candidates(px: dict[str, tuple[float, float]], point: tuple[float, float], k: int = 2):
    skip = re.compile(r"(_End|End$|^Root$|_Rig$)")
    d = sorted((float(np.hypot(x - point[0], y - point[1])), n) for n, (x, y) in px.items() if not skip.search(n))
    return [{"bone": n, "distPx": round(dd, 1)} for dd, n in d[:k]]
