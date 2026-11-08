"""DEF keypoint tracks: per-unit 2D chains marked on the HoMM3 DEF frames, the reference for rubric 3a.

    python tools/homm3_authenticity/keypoints.py <unit> sheet     [--clips g02_idle] [--frames 0,3] [--scale 6]
    python tools/homm3_authenticity/keypoints.py <unit> set       <file.txt|file.json|-> [--text "..."]
    python tools/homm3_authenticity/keypoints.py <unit> propagate [--clips ...] [--matcher ncc|dino] [--device cuda|cpu]
    python tools/homm3_authenticity/keypoints.py <unit> review    [--clips ...] [--glb <path>] [--view-yaw D] [--align clip|idle]
    python tools/homm3_authenticity/keypoints.py <unit> eval      [--clips ...] [--matcher ncc|dino] [--device cuda|cpu]
    python tools/homm3_authenticity/keypoints.py <unit> status

Authoring data: tools/homm3_authenticity/keypoints/<labSid>.json (tracked, small). Images and reports go to
V:/olden_port_work/authenticity/<labSid>/keypoints/ (outside git). Coordinates are DEF canvas pixels of the frame PNG
(the same canvas board.py crops), continuous: pixel i spans [i, i + 1), so its centre is i + 0.5. The sheets label
grid lines at integer coordinates.

File (schema homm3.authenticity.def_keypoints.v1):
  view   {"yawDeg": D|null, "align": "clip"|"idle"}  default DEF view for projecting our GLB (board --view-yaw/--align)
  chains {name: {"points": [p0, p1, ...], "bones": {p: "Bone" | "Bone@tip" | null}, "desc": {p: where to mark},
                 "missing": "why our rig has no bone for it" (optional)}}
         A chain's interior points are its joints: the 2D bend angle at p_i is the signed angle between
         (p_i - p_{i-1}) and (p_{i+1} - p_i). The first point is usually an anchor on the parent part (rump for
         the tail, withers for a leg) so the first real joint has an incoming segment.
         "Bone" = the bone's head (world translation); "Bone@tip" = head + its +Y axis times the tip length measured
         from the skin (95th percentile of the bone-local +Y of the vertices it dominates); "Bone@far" = the dominated
         vertices farthest from the head (a lance point); "Bone@+z" (any of +-x/y/z) = the dominated vertices
         farthest along that local axis (a beak); "Bone@0.5" = half the tip offset; null = our rig has no bone
         there (every joint using that point is MISSING, a rig defect). A joint whose three points are all fixed in
         one bone's frame (a head sits on its bone and its parent, an offset point on its bone) cannot bend: MISSING
         (rigid).
  clips  {clipKey: {"frames": {"<i>": {"pts": {chain: [[x, y] | null, ...]},
                                         "src": {chain: "mth-"}}}}}
         src, one char per point: m = marked by eye, t = tracked (propagate), h = marked hidden/occluded (null on
         purpose; propagate never fills it), - = unknown.

set input (text; '#' comments):
  clip g02_idle 0,1          select clip and frame(s) for the following lines (several frames: same values)
  foreleg_near 212,240 214,252 - 215,266     a whole chain: 'x,y' marks, '-' hidden, '?' leave as is
  tail.tip 170,215           one point;  'tail.tip -' marks it hidden;  'tail.tip ?' clears it to unknown
  JSON input: {clipKey: {"<i>": {chain: [[x,y]|null|"?", ...]}}}

propagate: every point not marked in a frame is tracked from the nearest marked frames on both sides (frame to
frame, wrapping on Idle/Move loops), forward from the previous and backward from the next; the nearer side wins when
the two disagree by more than CONFLICT_PX and the point is listed for review. Frames that are pixel-identical to a
frame with marks (any clip) take its marks first. Matcher: GPU patch correlation (Gaussian-weighted NCC of the
premultiplied RGBA patch around the point, against both the previous frame and the keyframe, inside the DEF alpha
mask, with a small displacement prior and sub-pixel parabola), optionally plus DINOv3 dense-feature cosine
(facebook/dinov3-vits16-pretrain-lvd1689m, the repo's cached encoder; --matcher dino). Torch on CUDA by default;
--device cpu is the reference (test_keypoints.py); no silent fallback.
eval: leave-one-out over marked frames: hide one frame's marks, propagate from the rest, report the px error.
Proof tier: authoring data plus a generated measurement; the DEF and the eye decide.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import ROOT, def_reference, load, unit_ids  # noqa: E402
from spritecam import project, sprite_camera, view_yawed  # noqa: E402

SCHEMA = "homm3.authenticity.def_keypoints.v1"
KP_DIR = HERE / "keypoints"
SCRATCH = Path("V:/olden_port_work/authenticity")
BG = (196, 198, 202)
CONFLICT_PX = 3.0
PATCH_R = 4             # template half-size, DEF px (9x9)
SEARCH_R = 12           # search half-size, DEF px per frame step
DISP_PRIOR = 0.0015     # score penalty per px^2 of displacement from the previous position
OFFMASK_PEN = 1.0       # score penalty when the candidate centre is off the sprite (point was on it)
DINO_MODEL = "facebook/dinov3-vits16-pretrain-lvd1689m"
DINO_UPSCALE = 4        # DEF px -> encoder px (a 16 px patch then covers 4 DEF px)
DINO_W = 0.5
DINO_CACHE = 16         # frame feature maps kept on the device (a clip is <= 10 frames)
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 140, 0), (0, 130, 200), (145, 30, 180), (70, 240, 240),
           (240, 50, 230), (160, 110, 40), (0, 128, 128), (128, 0, 0), (170, 255, 195), (128, 128, 0),
           (255, 215, 180), (0, 0, 128), (250, 190, 212), (255, 255, 25), (100, 100, 100), (210, 245, 60)]


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover (Pillow < 10.1)
        return ImageFont.load_default()


# ------------------------------------------------------------------ file
KP_OVERRIDE: Path | None = None   # --kp: work on a private copy (parallel marking agents)


def kp_path(lab: str) -> Path:
    return KP_OVERRIDE or KP_DIR / f"{lab}.json"


def load_kp(lab: str, must: bool = True) -> dict:
    p = kp_path(lab)
    if not p.is_file():
        if must:
            raise SystemExit(f"{lab}: no keypoint file {p.as_posix()} (author its chains first; README)")
        return None
    d = load(p)
    if d.get("schema") != SCHEMA:
        raise SystemExit(f"{p}: schema {d.get('schema')!r}, expected {SCHEMA}")
    for name, ch in d["chains"].items():
        bad = set(ch.get("bones", {})) - set(ch["points"])
        if bad:
            raise SystemExit(f"{p}: chain {name} maps unknown points {sorted(bad)}")
    d.setdefault("clips", {})
    return d


def save_kp(lab: str, d: dict) -> None:
    """Compact, diff-friendly JSON: one line per frame."""
    p = kp_path(lab)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in d.items() if k != "clips"}
    s = json.dumps(head, indent=1)[:-2] + ',\n "clips": {'
    clips = []
    for ck in sorted(d["clips"], key=lambda k: clip_order(d, k)):
        fr = d["clips"][ck]["frames"]
        lines = [f'   "{i}": ' + json.dumps(fr[i], separators=(",", ":")) for i in sorted(fr, key=int)]
        clips.append(f'\n  "{ck}": {{"frames": {{\n' + ",\n".join(lines) + "\n  }}")
    s += ",".join(clips) + "\n }\n}\n"
    json.loads(s)
    p.write_text(s, encoding="utf-8", newline="\n")


def clip_order(d: dict, ck: str) -> int:
    order = d.get("_clipOrder") or []
    return order.index(ck) if ck in order else 999


def frame_rec(d: dict, ck: str, i: int, create: bool = False) -> dict | None:
    c = d["clips"].get(ck)
    if c is None:
        if not create:
            return None
        c = d["clips"][ck] = {"frames": {}}
    f = c["frames"].get(str(i))
    if f is None and create:
        f = c["frames"][str(i)] = {"pts": {}, "src": {}}
    return f


def chain_slot(d: dict, f: dict, chain: str) -> tuple[list, list]:
    n = len(d["chains"][chain]["points"])
    pts = f["pts"].setdefault(chain, [None] * n)
    src = list(f["src"].get(chain, "-" * n))
    if len(pts) != n or len(src) != n:
        raise SystemExit(f"chain {chain}: stored {len(pts)} points / src {''.join(src)}, chain has {n}")
    return pts, src


# ------------------------------------------------------------------ DEF frames
class Unit:
    def __init__(self, unit: str):
        self.lab, self.src = unit_ids(unit)
        self.ref = def_reference(self.src)
        self.clips = {c["clipKey"]: c for c in self.ref["clips"]}
        self.order = [c["clipKey"] for c in self.ref["clips"]]
        self._img = {}
        self.out = SCRATCH / self.lab / "keypoints"

    def img(self, ck: str, i: int) -> np.ndarray:
        k = (ck, i)
        if k not in self._img:
            self._img[k] = np.asarray(Image.open(self.clips[ck]["frames"][i]).convert("RGBA"))
        return self._img[k]

    def n(self, ck: str) -> int:
        return len(self.clips[ck]["frames"])

    def loop(self, ck: str) -> bool:
        return bool(self.clips[ck].get("loop"))

    def frame_hash(self, ck: str, i: int) -> str:
        return hashlib.sha1(self.img(ck, i).tobytes()).hexdigest()

    def box(self, ck: str, pad: int = 6) -> tuple[int, int, int, int]:
        """Union alpha bbox of the clip (x0, y0, x1, y1), padded and clamped."""
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for i in range(self.n(ck)):
            ys, xs = np.nonzero(self.img(ck, i)[..., 3] > 0)
            if len(xs):
                x0, y0, x1, y1 = min(x0, xs.min()), min(y0, ys.min()), max(x1, xs.max() + 1), max(y1, ys.max() + 1)
        H, W = self.img(ck, 0).shape[:2]
        return max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)

    def pick_clips(self, arg: str | None) -> list[str]:
        if not arg:
            return list(self.order)
        out = []
        for a in arg.split(","):
            a = a.strip()
            hit = [ck for ck in self.order if a in (ck, self.clips[ck]["clip"], self.clips[ck]["clip"][5:])]
            if not hit:
                raise SystemExit(f"{self.lab}: no clip {a!r} (have {', '.join(self.order)})")
            out += hit
        return out


def composite(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * a + np.array(BG, np.float32) * (1 - a)
    return rgb.astype(np.uint8)


# ------------------------------------------------------------------ sheet / review drawing
def draw_frame(u: Unit, ck: str, i: int, scale: int, box, kp: dict | None = None, ours: dict | None = None,
               grid: bool = True, title: str | None = None) -> Image.Image:
    x0, y0, x1, y1 = box
    rgb = composite(u.img(ck, i)[y0:y1, x0:x1])
    w, h = x1 - x0, y1 - y0
    m = 30 if grid else 0
    im = Image.new("RGB", (w * scale + 2 * m, h * scale + 2 * m + 18), (250, 250, 250))
    im.paste(Image.fromarray(rgb).resize((w * scale, h * scale), Image.NEAREST), (m, m + 18))
    dr = ImageDraw.Draw(im, "RGBA")
    f = font(12)
    if title:
        dr.text((4, 2), title, fill=(0, 0, 0), font=font(14))
    oy = m + 18

    def P(x, y):
        return m + (x - x0) * scale, oy + (y - y0) * scale

    if grid:
        for gx in range(x0, x1 + 1):
            if scale >= 5 or gx % 5 == 0:
                col = (0, 0, 0, 120) if gx % 10 == 0 else (0, 0, 0, 60) if gx % 5 == 0 else (0, 0, 0, 18)
                X = P(gx, 0)[0]
                dr.line([(X, oy), (X, oy + h * scale)], fill=col)
                if gx % 10 == 0:
                    dr.text((X - 9, oy - 14), str(gx), fill=(0, 0, 0), font=f)
                    dr.text((X - 9, oy + h * scale + 2), str(gx), fill=(0, 0, 0), font=f)
        for gy in range(y0, y1 + 1):
            if scale >= 5 or gy % 5 == 0:
                col = (0, 0, 0, 120) if gy % 10 == 0 else (0, 0, 0, 60) if gy % 5 == 0 else (0, 0, 0, 18)
                Y = P(0, gy)[1]
                dr.line([(m, Y), (m + w * scale, Y)], fill=col)
                if gy % 10 == 0:
                    dr.text((2, Y - 7), str(gy), fill=(0, 0, 0), font=f)
                    dr.text((m + w * scale + 3, Y - 7), str(gy), fill=(0, 0, 0), font=f)
    if ours:
        for ci, (name, pts) in enumerate(ours.items()):
            col = PALETTE[ci % len(PALETTE)]
            q = [P(*p) if p is not None else None for p in pts]
            for a, b in zip(q, q[1:]):
                if a and b:
                    _dashed(dr, a, b, col + (230,), max(1, scale // 3))
            for p in q:
                if p:
                    r = max(2, scale // 2)
                    dr.rectangle([p[0] - r, p[1] - r, p[0] + r, p[1] + r], outline=col + (255,), width=1)
    if kp:
        f2 = font(max(10, min(14, 2 * scale)))
        for ci, name in enumerate(kp["chains"]):
            fr = frame_rec(kp, ck, i)
            if not fr or name not in fr["pts"]:
                continue
            col = PALETTE[ci % len(PALETTE)]
            pts, src = fr["pts"][name], fr["src"].get(name, "")
            q = [P(*p) if p is not None else None for p in pts]
            for a, b in zip(q, q[1:]):
                if a and b:
                    dr.line([a, b], fill=col + (255,), width=max(1, scale // 3))
            names = kp["chains"][name]["points"]
            for k, p in enumerate(q):
                if not p:
                    continue
                r = max(2, scale // 2 + 1)
                s = src[k] if k < len(src) else "-"
                if s == "m":
                    dr.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col + (255,), outline=(0, 0, 0, 255))
                else:
                    dr.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], outline=col + (255,), width=2)
                if scale >= 4:
                    dr.text((p[0] + r + 1, p[1] - r - 2), f"{_short(name)}.{names[k][:5]}", fill=col + (255,), font=f2,
                            stroke_width=1, stroke_fill=(0, 0, 0, 255))
    return im


def _short(name: str) -> str:
    return re.sub(r"[aeiou_]", "", name)[:6] or name[:6]


def _dashed(dr, a, b, col, width):
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 6))
    for k in range(0, n, 2):
        t0, t1 = k / n, min(1, (k + 1) / n)
        dr.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                 (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=col, width=width)


def legend(kp: dict, width: int) -> Image.Image:
    f = font(13)
    rows = []
    for ci, (name, ch) in enumerate(kp["chains"].items()):
        bones = ch.get("bones", {})
        mp = " ".join(f"{p}->{bones.get(p) or 'MISSING'}" for p in ch["points"])
        rows.append((PALETTE[ci % len(PALETTE)], f"{_short(name)} = {name}: {mp}"))
    im = Image.new("RGB", (width, 18 * len(rows) + 8), (250, 250, 250))
    dr = ImageDraw.Draw(im)
    for k, (col, t) in enumerate(rows):
        dr.rectangle([4, 6 + 18 * k, 14, 16 + 18 * k], fill=col)
        dr.text((20, 4 + 18 * k), t, fill=(0, 0, 0), font=f)
    return im


def cmd_sheet(a) -> None:
    u = Unit(a.unit)
    kp = load_kp(u.lab, must=False)
    out = Path(a.out) if a.out else u.out / "sheets"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for ck in u.pick_clips(a.clips):
        box = tuple(int(v) for v in a.box.split(",")) if a.box else u.box(ck)
        frames = [int(x) for x in a.frames.split(",")] if a.frames else range(u.n(ck))
        for i in frames:
            im = draw_frame(u, ck, i, a.scale, box, kp if a.marks else None,
                            title=f"{u.lab} {ck} f{i}  (DEF canvas px; grid 1/5/10)")
            im.save(out / f"{ck}_f{i}{'_' + a.box.replace(',', '_') if a.box else ''}.png")
            n += 1
    print(f"SHEET {u.lab}: {n} frame(s) -> {out}")


# ------------------------------------------------------------------ set
def parse_point(tok: str):
    if tok == "-":
        return "h"
    if tok == "?":
        return "?"
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", tok)
    if not m:
        raise SystemExit(f"bad point {tok!r} (want x,y or - or ?)")
    return [float(m.group(1)), float(m.group(2))]


def apply_point(d: dict, ck: str, i: int, chain: str, k: int, v) -> None:
    f = frame_rec(d, ck, i, create=True)
    pts, src = chain_slot(d, f, chain)
    if v == "h":
        pts[k], src[k] = None, "h"
    elif v == "?":
        pts[k], src[k] = None, "-"
    else:
        pts[k], src[k] = [round(float(v[0]), 2), round(float(v[1]), 2)], "m"
    f["src"][chain] = "".join(src)


def cmd_set(a) -> None:
    u = Unit(a.unit)
    d = load_kp(u.lab)
    if a.text is not None:
        txt = a.text
    elif a.input == "-":
        txt = sys.stdin.read()
    else:
        txt = Path(a.input).read_text(encoding="utf-8")
    n = 0
    if txt.lstrip().startswith("{"):
        for ck, frames in json.loads(txt).items():
            for i, chains in frames.items():
                for chain, pts in chains.items():
                    for k, v in enumerate(pts):
                        apply_point(d, check_clip(u, ck), check_frame(u, ck, int(i)), check_chain(d, chain), k,
                                    "h" if v is None else v)
                        n += 1
    else:
        ck, frames = None, []
        for ln, line in enumerate(txt.splitlines(), 1):
            line = line.split("#")[0].strip()
            if not line:
                continue
            tok = line.split()
            if tok[0] == "clip":
                ck = check_clip(u, tok[1])
                frames = [check_frame(u, ck, int(x)) for x in tok[2].split(",")]
                continue
            if ck is None:
                raise SystemExit(f"line {ln}: no 'clip <key> <frames>' before {line!r}")
            if "." in tok[0]:
                chain, pt = tok[0].split(".", 1)
                check_chain(d, chain)
                names = d["chains"][chain]["points"]
                if pt not in names:
                    raise SystemExit(f"line {ln}: chain {chain} has no point {pt!r} ({names})")
                if len(tok) != 2:
                    raise SystemExit(f"line {ln}: one value expected for {tok[0]}")
                for i in frames:
                    apply_point(d, ck, i, chain, names.index(pt), parse_point(tok[1]))
                    n += 1
                continue
            chain = check_chain(d, tok[0])
            names = d["chains"][chain]["points"]
            if len(tok) - 1 != len(names):
                raise SystemExit(f"line {ln}: chain {chain} has {len(names)} points {names}, got {len(tok) - 1}")
            for i in frames:
                for k, t in enumerate(tok[1:]):
                    v = parse_point(t)
                    if v != "?":
                        apply_point(d, ck, i, chain, k, v)
                        n += 1
    d["_clipOrder"] = u.order
    save_kp(u.lab, d)
    print(f"SET {u.lab}: {n} point value(s) -> {kp_path(u.lab).as_posix()}")


def check_clip(u: Unit, ck: str) -> str:
    return u.pick_clips(ck)[0]


def check_frame(u: Unit, ck: str, i: int) -> int:
    if not 0 <= i < u.n(ck):
        raise SystemExit(f"{ck} has {u.n(ck)} frames, got {i}")
    return i


def check_chain(d: dict, chain: str) -> str:
    if chain not in d["chains"]:
        raise SystemExit(f"no chain {chain!r} (have {', '.join(d['chains'])})")
    return chain


# ------------------------------------------------------------------ tracker (torch)
class Tracker:
    """Frame-to-frame point matcher on one device. Images are premultiplied RGBA float tensors (4, H, W)."""

    def __init__(self, u: Unit, device: str, matcher: str):
        import torch
        self.torch = torch
        sys.path.insert(0, str(HERE))
        import raster as R
        self.dev = R.resolve_device(device)
        self.u = u
        self.matcher = matcher
        self._t = {}
        self._feat = {}
        self.model = None
        r = PATCH_R
        yy, xx = torch.meshgrid(torch.arange(-r, r + 1.0), torch.arange(-r, r + 1.0), indexing="ij")
        self.poff = torch.stack([xx, yy], -1).reshape(-1, 2).to(self.dev, torch.float32)       # (k*k, 2)
        g = torch.exp(-(xx ** 2 + yy ** 2) / (2 * (r / 1.5) ** 2)).reshape(-1)
        self.gw = (g / g.sum()).to(self.dev, torch.float32)
        S = SEARCH_R
        sy, sx = torch.meshgrid(torch.arange(-S, S + 1.0), torch.arange(-S, S + 1.0), indexing="ij")
        self.soff = torch.stack([sx, sy], -1).reshape(-1, 2).to(self.dev, torch.float32)       # (D, 2)
        self.side = 2 * S + 1
        if matcher == "dino":
            self._load_dino()

    def _load_dino(self):
        from transformers import AutoModel
        self.model = AutoModel.from_pretrained(DINO_MODEL, local_files_only=True).to(self.dev).eval()
        for p in self.model.parameters():
            p.requires_grad_(False)
        self.n_reg = int(getattr(self.model.config, "num_register_tokens", 0))

    def tex(self, ck: str, i: int):
        k = (ck, i)
        if k not in self._t:
            a = self.torch.as_tensor(np.array(self.u.img(ck, i)), dtype=self.torch.float32, device=self.dev) / 255.0
            a = a.permute(2, 0, 1).contiguous()
            a[:3] *= a[3:4]
            self._t[k] = a
        return self._t[k]

    def sample(self, img, xy):
        """Bilinear sample img (C, H, W) at continuous px xy (N, 2) -> (N, C)."""
        F = self.torch.nn.functional
        C, H, W = img.shape
        g = self.torch.stack([2 * xy[:, 0] / W - 1, 2 * xy[:, 1] / H - 1], -1)[None, None]   # (1, 1, N, 2)
        return F.grid_sample(img[None], g, mode="bilinear", padding_mode="zeros", align_corners=False)[0, :, 0].T

    def patches(self, img, xy):
        """(N, 2) centres -> (N, C * k * k) patches."""
        N = xy.shape[0]
        pts = (xy[:, None, :] + self.poff[None]).reshape(-1, 2)
        return self.sample(img, pts).reshape(N, -1, img.shape[0]).permute(0, 2, 1).reshape(N, -1)

    def dino(self, ck: str, i: int):
        """DINOv3 feature map of the clip box, upsampled to DEF px: (D, h, w) on the device, plus the box origin."""
        k = (ck, i)
        if k in self._feat:
            self._feat[k] = self._feat.pop(k)                       # LRU: most recent last
            return self._feat[k]
        while len(self._feat) >= DINO_CACHE:                        # ~35 MB per frame map; bound VRAM
            self._feat.pop(next(iter(self._feat)))
        torch = self.torch
        F = torch.nn.functional
        x0, y0, x1, y1 = self.u.box(ck, pad=8)
        img = self.tex(ck, i)[:, y0:y1, x0:x1]
        rgb = img[:3] + (1 - img[3:4]) * torch.tensor(BG, device=self.dev, dtype=torch.float32)[:, None, None] / 255
        h, w = y1 - y0, x1 - x0
        H, W = (h * DINO_UPSCALE + 15) // 16 * 16, (w * DINO_UPSCALE + 15) // 16 * 16
        x = F.interpolate(rgb[None], size=(H, W), mode="bilinear", align_corners=False)
        mean = torch.tensor([0.485, 0.456, 0.406], device=self.dev)[:, None, None]
        std = torch.tensor([0.229, 0.224, 0.225], device=self.dev)[:, None, None]
        with torch.no_grad():
            tok = self.model(pixel_values=(x - mean) / std).last_hidden_state[0]
        tok = tok[1 + self.n_reg:]
        gh, gw = H // 16, W // 16
        fm = tok.T.reshape(-1, gh, gw)
        fm = F.interpolate(fm[None], size=(int(round(gh * 16 / DINO_UPSCALE)), int(round(gw * 16 / DINO_UPSCALE))),
                           mode="bilinear", align_corners=False)[0]
        fm = F.normalize(fm, dim=0)
        self._feat[k] = (fm, x0, y0)
        return self._feat[k]

    def dino_at(self, ck, i, xy):
        fm, x0, y0 = self.dino(ck, i)
        q = xy - self.torch.tensor([x0, y0], device=self.dev, dtype=self.torch.float32)
        return self.torch.nn.functional.normalize(self.sample(fm, q), dim=1)

    def ncc(self, t, c):
        """t (N, M), c (N, D, M) -> (N, D) Gaussian-weighted NCC minus a weighted SSD term."""
        w = self.gw.repeat(t.shape[1] // self.gw.shape[0])
        w = w / w.sum()
        tm = t - (t * w).sum(-1, keepdim=True)
        cm = c - (c * w).sum(-1, keepdim=True)
        num = (cm * (tm[:, None] * w)).sum(-1)
        den = ((cm ** 2 * w).sum(-1) * (tm[:, None] ** 2 * w).sum(-1)).clamp_min(1e-10).sqrt()
        ssd = (((c - t[:, None]) ** 2) * w).sum(-1)
        flat = (tm ** 2 * w).sum(-1, keepdim=True) < 1e-5
        return self.torch.where(flat, -4 * ssd, num / den - 2 * ssd)

    def step(self, ck: str, i_from: int, i_to: int, xy_from, key: tuple | None):
        """Track points xy_from (N, 2) on frame i_from to frame i_to. key = (ck, i_key, xy_key) adds the keyframe's
        own patch to the template score. Returns (N, 2) positions and the best score."""
        torch = self.torch
        A, B = self.tex(ck, i_from), self.tex(ck, i_to)
        N = xy_from.shape[0]
        cand = (xy_from[:, None, :] + self.soff[None]).reshape(-1, 2)                # (N*D, 2)
        cp = self.patches(B, cand).reshape(N, self.soff.shape[0], -1)
        score = self.ncc(self.patches(A, xy_from), cp)
        if key is not None:
            kck, ki, kxy = key
            score = 0.5 * score + 0.5 * self.ncc(self.patches(self.tex(kck, ki), kxy), cp)
        score = score - DISP_PRIOR * (self.soff ** 2).sum(-1)[None]
        # stay on the sprite: alpha (3x3 max) at the candidate centre when the source point is on it
        aB = torch.nn.functional.max_pool2d(B[3:4][None], 3, 1, 1)[0]
        on_src = self.sample(torch.nn.functional.max_pool2d(A[3:4][None], 3, 1, 1)[0], xy_from)[:, 0] > 0.5
        on_c = self.sample(aB, cand)[:, 0].reshape(N, -1) > 0.5
        score = score - OFFMASK_PEN * (on_src[:, None] & ~on_c).float()
        if self.matcher == "dino":
            fa = self.dino_at(ck, i_from, xy_from)
            fb = self.dino_at(ck, i_to, cand).reshape(N, -1, fa.shape[1])
            score = score + DINO_W * (fb * fa[:, None]).sum(-1)
        best = score.argmax(1)
        side = self.side
        by, bx = best // side, best % side
        sc = score.reshape(N, side, side)
        ar = torch.arange(N, device=self.dev)

        def parab(lo, mid, hi):
            den = lo - 2 * mid + hi
            return torch.where(den < -1e-9, 0.5 * (lo - hi) / den, torch.zeros_like(mid)).clamp(-0.5, 0.5)
        xl, xh = (bx - 1).clamp(0, side - 1), (bx + 1).clamp(0, side - 1)
        yl, yh = (by - 1).clamp(0, side - 1), (by + 1).clamp(0, side - 1)
        mid = sc[ar, by, bx]
        dx = torch.where((bx > 0) & (bx < side - 1), parab(sc[ar, by, xl], mid, sc[ar, by, xh]), torch.zeros_like(mid))
        dy = torch.where((by > 0) & (by < side - 1), parab(sc[ar, yl, bx], mid, sc[ar, yh, bx]), torch.zeros_like(mid))
        off = self.soff[best] + torch.stack([dx, dy], -1)
        return xy_from + off, mid


def virtual_marks(u: Unit, d: dict, clips: list[str]) -> dict:
    """{(ck, i): {chain: (pts, src)}} = the marks, plus marks copied onto pixel-identical frames (any clip)."""
    marks = {}
    for ck, c in d["clips"].items():
        if ck not in u.clips:
            continue
        for si, f in c["frames"].items():
            i = int(si)
            for chain, src in f["src"].items():
                if chain not in d["chains"]:
                    continue
                for k, s in enumerate(src):
                    if s in "mh":
                        marks.setdefault((ck, i), {}).setdefault(chain, {})[k] = (f["pts"][chain][k], s, (ck, i))
    by_hash = {}
    for ck in u.order:
        for i in range(u.n(ck)):
            by_hash.setdefault(u.frame_hash(ck, i), []).append((ck, i))
    for grp in by_hash.values():
        if len(grp) < 2:
            continue
        union = {}
        for fk in grp:
            for chain, ks in marks.get(fk, {}).items():
                for k, v in ks.items():
                    union.setdefault(chain, {}).setdefault(k, v)
        for fk in grp:
            if fk[0] not in clips:
                continue
            for chain, ks in union.items():
                for k, v in ks.items():
                    marks.setdefault(fk, {}).setdefault(chain, {}).setdefault(k, v)
    return marks


def propagate(u: Unit, d: dict, clips: list[str], tr: Tracker, hide: set | None = None) -> dict:
    """Fill every unmarked point of the clips by tracking. hide = {(ck, i)} frames whose marks are ignored (eval).
    Returns {"conflicts": [...], "filled": n} and writes 't' points into d."""
    torch = tr.torch
    marks = virtual_marks(u, d, clips)
    if hide:
        marks = {fk: v for fk, v in marks.items() if fk not in hide}
    rep = {"conflicts": [], "filled": 0, "copied": 0, "untracked": 0}
    for ck in clips:
        n, loop = u.n(ck), u.loop(ck)
        # tracks: one per (chain, k, keyframe, direction)
        res = {}   # (chain, k, i) -> list of (xy, steps, keyframe)
        for chain, ch in d["chains"].items():
            for k in range(len(ch["points"])):
                keys = {i: marks[(ck, i)][chain][k] for i in range(n)
                        if (ck, i) in marks and chain in marks[(ck, i)] and k in marks[(ck, i)][chain]}
                if not keys:
                    continue
                for i0, (xy, s, _) in keys.items():
                    if s != "m":
                        continue
                    for dirn in (1, -1):
                        res.setdefault(("_tracks",), []).append((chain, k, i0, xy, dirn, keys))
        tracks = res.pop(("_tracks",), [])
        # active: (chain, k, key_i, key_xy, cur_i, cur_xy, steps, dirn, keys)
        active = [(c, k, i0, xy, i0, xy, 0, dn, keys) for c, k, i0, xy, dn, keys in tracks]
        while active:
            groups = {}
            nxt = []
            for t in active:
                c, k, i0, kxy, ci, cxy, st, dn, keys = t
                ni = ci + dn
                if loop:
                    ni %= n
                elif not 0 <= ni < n:
                    continue
                if ni in keys or st + 1 >= n:
                    continue
                groups.setdefault((ci, ni, i0), []).append(t)
            for (ci, ni, i0), ts in groups.items():
                xy = torch.tensor([t[5] for t in ts], dtype=torch.float32, device=tr.dev)
                kxy = torch.tensor([t[3] for t in ts], dtype=torch.float32, device=tr.dev)
                out, _ = tr.step(ck, ci, ni, xy, (ck, i0, kxy))
                out = out.cpu().numpy().astype(np.float64)
                for t, p in zip(ts, out):
                    c, k, i0_, kxy_, _ci, _cxy, st, dn, keys = t
                    p = [float(p[0]), float(p[1])]
                    res.setdefault((c, k, ni), []).append((p, st + 1, i0_))
                    nxt.append((c, k, i0_, kxy_, ni, p, st + 1, dn, keys))
            active = nxt
        # write: marks (incl. copied) first, then combine tracks
        for i in range(n):
            if hide and (ck, i) in hide:
                f = frame_rec(d, ck, i, create=True)
            else:
                f = frame_rec(d, ck, i, create=True)
            for chain, ch in d["chains"].items():
                pts, src = chain_slot(d, f, chain)
                for k in range(len(ch["points"])):
                    mk = marks.get((ck, i), {}).get(chain, {}).get(k)
                    if mk is not None and mk[2] == (ck, i):
                        continue                                            # own mark stays
                    if mk is not None:                                      # identical-frame copy
                        pts[k] = None if mk[1] == "h" else list(mk[0])
                        src[k] = mk[1] if mk[1] == "h" else "t"
                        rep["copied"] += 1
                        continue
                    cands = res.get((chain, k, i))
                    if not cands:
                        if src[k] == "t":
                            pts[k], src[k] = None, "-"
                        rep["untracked"] += src[k] == "-"
                        continue
                    cands.sort(key=lambda x: x[1])
                    best = cands[0][0]
                    if len(cands) > 1:
                        (p1, s1, k1), (p2, s2, k2) = cands[0], cands[1]
                        dd = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
                        if dd > CONFLICT_PX:
                            rep["conflicts"].append({"clip": ck, "frame": i, "point": f"{chain}.{ch['points'][k]}",
                                                     "px": round(dd, 1), "from": [k1, k2]})
                        else:
                            w1 = s2 / (s1 + s2)
                            best = [w1 * p1[0] + (1 - w1) * p2[0], w1 * p1[1] + (1 - w1) * p2[1]]
                    pts[k], src[k] = [round(best[0], 2), round(best[1], 2)], "t"
                    rep["filled"] += 1
                f["src"][chain] = "".join(src)
    return rep


def cmd_propagate(a) -> None:
    t0 = time.perf_counter()
    u = Unit(a.unit)
    d = load_kp(u.lab)
    clips = u.pick_clips(a.clips)
    tr = Tracker(u, a.device, a.matcher)
    rep = propagate(u, d, clips, tr)
    d["_clipOrder"] = u.order
    save_kp(u.lab, d)
    rep.update(perf(t0, a.device))
    u.out.mkdir(parents=True, exist_ok=True)
    (u.out / "propagate.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"PROPAGATE {u.lab} [{a.matcher}/{a.device}]: filled {rep['filled']}, copied from identical frames "
          f"{rep['copied']}, still unknown {rep['untracked']}, conflicts {len(rep['conflicts'])}  wall {rep['wallSeconds']} s "
          f"peak RSS {rep['peakRssMB']} MB VRAM {rep.get('peakVramMB')} MB")
    for c in rep["conflicts"][:40]:
        print(f"  CONFLICT {c['clip']} f{c['frame']} {c['point']}: tracks from f{c['from'][0]} / f{c['from'][1]} differ {c['px']} px")


def perf(t0: float, device: str) -> dict:
    out = {"wallSeconds": round(time.perf_counter() - t0, 2)}
    try:
        import psutil
        mi = psutil.Process().memory_info()
        out["peakRssMB"] = round(getattr(mi, "peak_wset", mi.rss) / 2 ** 20, 1)
    except Exception:  # pragma: no cover
        out["peakRssMB"] = None
    if device == "cuda" and "torch" in sys.modules:
        import torch
        out["peakVramMB"] = round(torch.cuda.max_memory_reserved() / 2 ** 20, 1)
    return out


# ------------------------------------------------------------------ eval (leave one marked frame out)
def cmd_eval(a) -> None:
    t0 = time.perf_counter()
    u = Unit(a.unit)
    d0 = load_kp(u.lab)
    clips = u.pick_clips(a.clips)
    tr = Tracker(u, a.device, a.matcher)
    errs, per = [], []
    for ck in clips:
        c = d0["clips"].get(ck, {"frames": {}})
        mframes = sorted(int(i) for i, f in c["frames"].items() if any("m" in s for s in f["src"].values()))
        if len(mframes) < 2:
            continue
        hashes = {i: u.frame_hash(ck, i) for i in mframes}
        for i in mframes:
            # a held-out frame that is pixel-identical to another marked frame would be copied, not tracked
            if any(hashes[j] == hashes[i] for j in mframes if j != i):
                continue
            d = json.loads(json.dumps(d0))
            propagate(u, d, [ck], tr, hide={(ck, i)})
            f0, f1 = frame_rec(d0, ck, i), frame_rec(d, ck, i)
            for chain, src in f0["src"].items():
                for k, s in enumerate(src):
                    if s != "m":
                        continue
                    p, q = f0["pts"][chain][k], f1["pts"][chain][k]
                    if q is None:
                        continue
                    e = math.hypot(p[0] - q[0], p[1] - q[1])
                    errs.append(e)
                    per.append({"clip": ck, "frame": i, "point": f"{chain}.{d0['chains'][chain]['points'][k]}",
                                "px": round(e, 2)})
    if not errs:
        raise SystemExit("eval: no clip has two or more marked, non-identical frames")
    e = np.array(errs)
    rep = {"matcher": a.matcher, "device": a.device, "n": len(e), "medianPx": round(float(np.median(e)), 2),
           "p90Px": round(float(np.percentile(e, 90)), 2), "meanPx": round(float(e.mean()), 2),
           "within2Px": round(float((e <= 2).mean()), 3), "within4Px": round(float((e <= 4).mean()), 3),
           "worst": sorted(per, key=lambda x: -x["px"])[:15], **perf(t0, a.device)}
    u.out.mkdir(parents=True, exist_ok=True)
    (u.out / f"eval_{a.matcher}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"EVAL {u.lab} [{a.matcher}/{a.device}] leave-one-frame-out over {rep['n']} marked points: median "
          f"{rep['medianPx']} px, p90 {rep['p90Px']} px, <=2 px {rep['within2Px']:.0%}, <=4 px {rep['within4Px']:.0%}  "
          f"wall {rep['wallSeconds']} s  peak RSS {rep['peakRssMB']} MB  VRAM {rep.get('peakVramMB')} MB")
    for w in rep["worst"][:8]:
        print(f"  {w['clip']} f{w['frame']} {w['point']}: {w['px']} px")


# ------------------------------------------------------------------ ours: GLB bones at DEF frame times
class OursPoints:
    """Our GLB's mapped bones projected through the DEF-matched sprite camera (numpy, no torch)."""

    def __init__(self, glb: Path | None, src: str, ref: dict, view_yaw: float | None, scene=None):
        from gltf_scene import Scene
        self.sc = scene if scene is not None else Scene(glb, body_name=src)
        sc = self.sc
        self.jn = [sc.nodes[j].get("name", str(j)) for j in sc.joints]
        self.jix = {n: k for k, n in enumerate(self.jn)}
        self.ibm_inv = np.linalg.inv(sc.ibm)
        node2k = {j: k for k, j in enumerate(sc.joints)}
        self.parent = {k: node2k.get(sc.parent.get(j)) for k, j in enumerate(sc.joints)}
        own = np.zeros(len(self.jn))
        np.add.at(own, sc.J.ravel(), sc.W.ravel())
        self.own = own
        kids = {}
        for k, p in self.parent.items():
            if p is not None:
                kids.setdefault(p, []).append(k)
        self.kids = kids
        sub = {}

        def subtree(k):
            if k not in sub:
                sub[k] = own[k] + sum(subtree(c) for c in kids.get(k, []))
            return sub[k]
        self.subtree = np.array([subtree(k) for k in range(len(self.jn))])
        deyaw = (sc.extras.get("homm3DefRetargetDeliveryDeyaw") or {}).get("yawDeg")
        self.cam = view_yawed(sprite_camera(ref["spritecam"], deyaw), view_yaw)
        self.view_yaw, self.deyaw = view_yaw, deyaw
        self._tip = {}

    def times(self, c: dict) -> list[float]:
        """board.py timing: DEF frame i at start + i * step, step = duration / m."""
        rng = self.sc.clip_range(c["clip"])
        n = len(c["frames"])
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if c.get("loop") else 0)
        step = rng["duration"] / m if m > 0 else 1 / 12
        return [rng["start"] + i * step for i in range(n)]

    def _dominated_local(self, k: int) -> np.ndarray:
        """Bind-pose vertices this bone dominates (weight >= 0.5, else >= 0.25), in the bone's local frame."""
        sc = self.sc
        jw = np.zeros(len(sc.P))
        for s in range(sc.J.shape[1]):
            jw += np.where(sc.J[:, s] == k, sc.W[:, s], 0.0)
        v = sc.P[jw >= 0.5]
        if len(v) < 3:
            v = sc.P[jw >= 0.25]
        return (sc.ibm[k, :3, :3] @ v.T).T + sc.ibm[k, :3, 3] if len(v) else np.zeros((0, 3))

    def local_offset(self, k: int, mode: str) -> np.ndarray:
        """Bone-local offset of a point spec: 'tip' = +Y times the 95th percentile of the dominated vertices' local
        y; 'far' = mean of the 2% dominated vertices farthest from the head (a prop's end); '+z' etc. = mean of the
        2% dominated vertices farthest along that bone-local axis (a beak, a chin); a float f = f times the tip
        offset."""
        key = (k, mode)
        if key not in self._tip:
            loc = self._dominated_local(k)
            if mode == "far" or re.fullmatch(r"[+-][xyz]", mode):
                if len(loc) == 0:
                    raise SystemExit(f"{self.jn[k]}@{mode}: the bone dominates no vertex")
                dd = (np.linalg.norm(loc, axis=1) if mode == "far"
                      else loc[:, "xyz".index(mode[1])] * (1 if mode[0] == "+" else -1))
                off = loc[dd >= np.percentile(dd, 98)].mean(0)
            else:
                ln = float(max(0.0, np.percentile(loc[:, 1], 95))) if len(loc) else 0.0
                if ln <= 0:
                    raise SystemExit(f"{self.jn[k]}@{mode}: no dominated vertex along +Y (use a child bone or @far)")
                off = np.array([0.0, ln, 0.0]) * (1.0 if mode == "tip" else float(mode))
            self._tip[key] = off
        return self._tip[key]

    def resolve(self, spec: str | None) -> tuple[int, str | None] | None:
        """'Bone' -> (k, None) head; 'Bone@tip' / 'Bone@far' / 'Bone@0.5' -> (k, mode)."""
        if not spec:
            return None
        name, _, mode = spec.partition("@")
        k = self.jix.get(name)
        if k is None:
            raise SystemExit(f"keypoint bone {name!r} is not a joint of this GLB (have {', '.join(self.jn)})")
        if mode and mode not in ("tip", "far") and not re.fullmatch(r"[+-][xyz]", mode):
            try:
                float(mode)
            except ValueError:
                raise SystemExit(f"bad point spec {spec!r}: want Bone, Bone@tip, Bone@far, Bone@+x/-x/+y/-y/+z/-z or Bone@<fraction>")
        return k, (mode or None)

    def frames_of(self, spec: str | None) -> set:
        """Bones whose frame holds this point fixed: a head sits on the bone and on its parent; an offset point
        only on its bone. A joint whose three points share a frame cannot bend (rigid)."""
        r = self.resolve(spec)
        if r is None:
            return set()
        k, mode = r
        return {k} if mode else ({k} | ({self.parent[k]} if self.parent[k] is not None else set()))

    def world(self, G: np.ndarray, spec) -> np.ndarray | None:
        """(T, 3) world position of a point spec at the sampled transforms G (T, J, 4, 4)."""
        r = self.resolve(spec)
        if r is None:
            return None
        k, mode = r
        p = G[:, k, :3, 3]
        if mode:
            p = p + G[:, k, :3, :3] @ self.local_offset(k, mode)      # columns carry the bone's world scale
        return p

    def sample(self, clip: str, times) -> np.ndarray:
        Jm, _ = self.sc.pose(clip, np.asarray(times, np.float64))
        return Jm @ self.ibm_inv[None]

    def chains_2d(self, kp: dict, G: np.ndarray) -> dict:
        """{chain: (T, P, 2) px with NaN for unmapped points}."""
        out = {}
        T = G.shape[0]
        for name, ch in kp["chains"].items():
            arr = np.full((T, len(ch["points"]), 2), np.nan)
            for k, p in enumerate(ch["points"]):
                w = self.world(G, ch.get("bones", {}).get(p))
                if w is not None:
                    arr[:, k] = project(self.cam, w)
            out[name] = arr
        return out


def bend_series(pts: np.ndarray) -> np.ndarray:
    """(T, P, 2) chain points -> (T, P - 2) signed 2D bend (deg) at each interior point, NaN where a point is
    missing; image axes (y down) on both the DEF and our projection, so signs agree."""
    u = pts[:, 1:-1] - pts[:, :-2]
    v = pts[:, 2:] - pts[:, 1:-1]
    cr = u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]
    dt = (u * v).sum(-1)
    return np.degrees(np.arctan2(cr, dt))


def unwrap_deg(a: np.ndarray) -> np.ndarray:
    """Unwrap a (T,) angle series over its finite entries (NaN kept)."""
    out = a.copy()
    ok = np.isfinite(a)
    if ok.sum() > 1:
        out[ok] = np.degrees(np.unwrap(np.radians(a[ok])))
    return out


def circ_range(a: np.ndarray) -> float:
    """Smallest arc (deg) holding every finite angle of a: 360 minus the largest gap between sorted angles. Unlike
    max - min of an unwrapped series it cannot exceed 360 when a short segment spins between frames."""
    x = np.sort(np.mod(a[np.isfinite(a)], 360.0))
    if len(x) < 2:
        return 0.0
    gaps = np.diff(np.concatenate([x, x[:1] + 360.0]))
    return float(360.0 - gaps.max())


def similarity_2d(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray]:
    """Scale + shift (no rotation) taking src (N, 2) to dst (N, 2), least squares."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    k = float((a * b).sum() / max((a * a).sum(), 1e-9))
    return k, md - k * ms


def def_points(kp: dict, ck: str, n: int) -> dict:
    """{chain: (n, P, 2)} DEF points with NaN where unknown or hidden."""
    out = {}
    for name, ch in kp["chains"].items():
        arr = np.full((n, len(ch["points"]), 2), np.nan)
        for i in range(n):
            f = frame_rec(kp, ck, i)
            if f and name in f["pts"]:
                for k, p in enumerate(f["pts"][name]):
                    if p is not None:
                        arr[i, k] = p
        out[name] = arr
    return out


def cmd_review(a) -> None:
    u = Unit(a.unit)
    d = load_kp(u.lab)
    out = Path(a.out) if a.out else u.out / "review"
    out.mkdir(parents=True, exist_ok=True)
    ours = None
    view = d.get("view") or {}
    vy = a.view_yaw if a.view_yaw is not None else view.get("yawDeg")
    align = a.align or view.get("align") or "clip"
    fits = {}
    if a.glb:
        ours = OursPoints(Path(a.glb), u.src, u.ref, vy)
        # 2D similarity per clip from the keypoints of frame 0 (align clip) or Idle frame 0 (align idle)
        ref_ck = "g02_idle" if "g02_idle" in u.clips else u.order[0]
        for ck in [ref_ck] + u.pick_clips(a.clips):
            c = u.clips[ck]
            G = ours.sample(c["clip"], ours.times(c))
            fits[ck] = (ours.chains_2d(d, G), def_points(d, ck, u.n(ck)))
    sheets = 0
    for ck in u.pick_clips(a.clips):
        box = u.box(ck)
        tiles = []
        n = u.n(ck)
        sim = None
        if ours:
            src_ck = ("g02_idle" if align == "idle" and "g02_idle" in fits else ck)
            o2, dp = fits[src_ck]
            A = np.concatenate([o2[c][0] for c in d["chains"]])
            B = np.concatenate([dp[c][0] for c in d["chains"]])
            ok = ~np.isnan(A).any(1) & ~np.isnan(B).any(1)
            sim = similarity_2d(A[ok], B[ok]) if ok.sum() >= 3 else None
        for i in range(n):
            od = None
            if ours and sim:
                o2 = fits[ck][0]
                od = {c: [None if np.isnan(p).any() else tuple(sim[0] * p + sim[1]) for p in o2[c][i]] for c in d["chains"]}
            im = draw_frame(u, ck, i, a.scale, box, d, od,
                            title=f"{u.lab} {ck} f{i}  filled = marked, ring = tracked" + ("  squares/dashed = ours" if od else ""))
            im.save(out / f"{ck}_f{i}.png")
            tiles.append(draw_frame(u, ck, i, 3, box, d, od, grid=False, title=f"f{i}"))
        W = sum(t.width for t in tiles) + 4 * len(tiles)
        strip = Image.new("RGB", (W, max(t.height for t in tiles)), (250, 250, 250))
        x = 0
        for t in tiles:
            strip.paste(t, (x, 0))
            x += t.width + 4
        lg = legend(d, max(W, 900))
        sheet = Image.new("RGB", (max(W, lg.width), strip.height + lg.height), (250, 250, 250))
        sheet.paste(strip, (0, 0))
        sheet.paste(lg, (0, strip.height))
        sheet.save(out / f"{ck}_strip.png")
        sheets += 1
    print(f"REVIEW {u.lab}: {sheets} clip strip(s) + per-frame sheets -> {out}"
          + (f"  ours: {Path(a.glb).name} view yaw {vy} align {align}" if ours else ""))


def cmd_status(a) -> None:
    u = Unit(a.unit)
    d = load_kp(u.lab)
    print(f"{u.lab}: {len(d['chains'])} chains, "
          f"{sum(len(c['points']) for c in d['chains'].values())} points per frame")
    for ck in u.order:
        n = u.n(ck)
        cnt = {"m": 0, "t": 0, "h": 0, "-": 0}
        mf = []
        for i in range(n):
            f = frame_rec(d, ck, i)
            tot = sum(len(c["points"]) for c in d["chains"].values())
            got = 0
            if f:
                for chain, s in f["src"].items():
                    for ch in s:
                        cnt[ch] = cnt.get(ch, 0) + 1
                        got += 1
                if any("m" in s for s in f["src"].values()):
                    mf.append(i)
            cnt["-"] += tot - got
        print(f"  {ck:18s} {n:2d} fr  marked frames {mf}  points m {cnt['m']} t {cnt['t']} h {cnt['h']} unknown {cnt['-']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit")
    ap.add_argument("--kp", help="keypoint file to read/write instead of keypoints/<labSid>.json (a private copy)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sheet")
    s.add_argument("--clips"); s.add_argument("--frames"); s.add_argument("--scale", type=int, default=6)
    s.add_argument("--marks", action="store_true", help="draw the current points too"); s.add_argument("--out")
    s.add_argument("--box", help="x0,y0,x1,y1 DEF px region to zoom (default: the clip's sprite box)")
    s = sp.add_parser("set")
    s.add_argument("input", nargs="?", default="-"); s.add_argument("--text")
    for name in ("propagate", "eval"):
        s = sp.add_parser(name)
        s.add_argument("--clips"); s.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
        s.add_argument("--matcher", default="ncc", choices=("ncc", "dino"))
    s = sp.add_parser("review")
    s.add_argument("--clips"); s.add_argument("--scale", type=int, default=6); s.add_argument("--out")
    s.add_argument("--glb", help="also draw our GLB's mapped bones (dashed), 2D-similarity aligned on the keypoints")
    s.add_argument("--view-yaw", type=float); s.add_argument("--align", choices=("clip", "idle"))
    sp.add_parser("status")
    a = ap.parse_args(argv)
    global KP_OVERRIDE
    KP_OVERRIDE = Path(a.kp).resolve() if a.kp else None
    {"sheet": cmd_sheet, "set": cmd_set, "propagate": cmd_propagate, "review": cmd_review, "eval": cmd_eval,
     "status": cmd_status}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
