"""Storm elemental VFX experiments: composite effect approaches over the retargeted mesh
render and compare them with the original CSTORM.DEF frames at the same scale and timing.

Inputs  : CSTORM.DEF (H3sprite.lod), Blender renders from render_mesh_frames.py
          (work/mesh2x/base_*, mask_*, bones.json; blend frame t+1 = DEF master frame t).
Outputs : artifacts/homm3_vfx_experiments/storm_elemental/{compare_*.png,.gif}, anchors.json

Panels  : DEF original | mesh, no VFX | A DEF flipbook (hand-anchored) |
          B procedural, HoMM3 rules | M modern soft additive | A+C flipbook + body glow
Everything is a 2D composite of an offline Blender render (generated artifact); none of it
is a Unity or in-game render.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation, gaussian_filter, label

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import h3def  # noqa: E402
from def_effect_layer import effect_mask  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXP = ROOT / "artifacts/homm3_vfx_experiments/storm_elemental"
MESH = EXP / "work/mesh2x"
S = 2  # display scale; DEF pixels are nearest-upscaled, mesh is rendered at 2x
BG = (72, 88, 64)
GLOW = np.array([215, 215, 150], float)  # measured mean of CSTORM's yellow body glow (R=G)
CLIPS = {"idle": ("g02_idle", 0, 10), "attack_front": ("g12_attack_front", 42, 48),
         "shoot_front": ("g15_shoot_front", 49, 55)}
FRAME_MS = 100  # HoMM3 base (slow) speed per VCMI: 10 fps; normal speed doubles it
LABELS = ["HoMM3 DEF", "mesh only", "A flipbook", "B procedural", "M modern", "A+C glow"]


def master_frames(d):
    """DEF frame per master-sequence index (matches the .blend.frames.json segments)."""
    order = [(2, 10), (20, 1), (0, 4), (21, 1), (2, 1), (1, 5), (2, 1), (3, 6), (2, 1), (4, 11),
             (2, 1), (12, 6), (2, 1), (15, 6), (2, 1), (5, 9)]
    out = []
    for g, n in order:
        out += d.groups[g][:n]
    return out


def up(a):
    return a.repeat(S, 0).repeat(S, 1)


def over(bg, rgba):
    a = rgba[..., 3:4].astype(float) / 255
    return bg * (1 - a) + rgba[..., :3].astype(float) * a


def hands(bones, t):
    fr = bones["frames"][str(t + 1)]
    return [np.array(fr[b]["tail"][:2]) for b in ("LeftHand", "RightHand") if b in fr]


def def_layers(f, pal):
    idx = f.idx
    fil = effect_mask(idx, pal)
    lum = pal.astype(float)[idx] @ np.array([0.299, 0.587, 0.114])
    core = (idx > 7) & (lum >= 235) & binary_dilation(fil, iterations=4) & ~fil
    return fil, core


def shift(a, dx, dy):
    h, w = a.shape[:2]
    out = np.zeros_like(a)
    sx0, sx1 = max(0, -dx), min(w, w - dx)
    sy0, sy1 = max(0, -dy), min(h, h - dy)
    out[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx] = a[sy0:sy1, sx0:sx1]
    return out


def bolt_paths(rng, origin, heading, length, n_branch):
    """1-px jagged dendrite as float point lists (sprite 1x space)."""
    paths = []
    stack = [(np.array(origin, float), heading, length, 0)]
    while stack and len(paths) < 1 + n_branch:
        p, h, L, depth = stack.pop()
        pts = [p.copy()]
        travelled = 0.0
        while travelled < L:
            h += rng.normal(0, 0.55)
            step = rng.uniform(1.5, 3.5)
            p = p + step * np.array([math.cos(h), math.sin(h)])
            travelled += step
            pts.append(p.copy())
            if depth < 2 and rng.random() < 0.18 and len(paths) + len(stack) < n_branch:
                stack.append((p.copy(), h + rng.choice([-1, 1]) * rng.uniform(0.5, 1.2),
                              L * rng.uniform(0.25, 0.5), depth + 1))
        paths.append(pts)
    return paths


def raster_1px(shape, paths, colour):
    im = Image.new("RGBA", shape[::-1], (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    for pts in paths:
        dr.line([tuple(int(v) for v in np.round(q)) for q in pts], fill=colour, width=1)
    return np.array(im)


def def_stats(fil, core):
    lab, n = label(fil, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())[1:] if n else np.array([])
    ys, xs = np.nonzero(fil)
    return {"px": int(fil.sum()), "components": int(n),
            "meanComponent": round(float(sizes.mean()), 2) if n else 0.0,
            "extent": float(max(np.ptp(xs), np.ptp(ys))) if len(xs) else 0.0, "corePx": int(core.sum())}


def main():
    d = h3def.read_def("cstorm.def")
    pal = d.palette
    frames = master_frames(d)
    bones = json.load(open(MESH / "bones.json"))
    H, W = 400, 450
    report = {}
    rng = np.random.default_rng(3)
    for clip, (seg, a, b) in CLIPS.items():
        heading = {"shoot_front": -math.pi / 2, "attack_front": 0.0, "idle": 0.0}[clip]
        rows, anchors, prev_paths = [], [], []
        for t in range(a, b):
            f = frames[t]
            fil, core = def_layers(f, pal)
            st = def_stats(fil, core)
            base = np.array(Image.open(MESH / f"base_{t + 1:03d}.png").convert("RGBA")).astype(float)
            hmask = np.array(Image.open(MESH / f"mask_{t + 1:03d}.png").convert("L")).astype(float) / 255
            bgimg = np.ones((H * S, W * S, 3)) * BG
            mesh_rgb = over(bgimg, base)
            hs = hands(bones, t)  # bones.json is in 1x sprite pixels
            hmid = np.mean(hs, axis=0)

            # ---- A: DEF effect pixels, rigidly moved so the DEF's hot fists land on the mesh hands
            if core.any():
                cy, cx = np.nonzero(core)
                src = np.array([cx.mean(), cy.mean()])
            elif fil.any():
                body = (f.idx > 7) & ~fil
                near = fil & binary_dilation(body, iterations=2)
                yy, xx = np.nonzero(near if near.any() else fil)
                src = np.array([xx.mean(), yy.mean()])
            else:
                src = hmid
            dxy = np.round(hmid - src).astype(int)
            anchors.append({"masterFrame": t, "defAnchor": src.round(1).tolist(), "meshHands": hmid.round(1).tolist(),
                            "shiftPx1x": dxy.tolist(), **st})
            rgba = h3def.to_rgba(f, pal)
            eff = rgba.copy()
            eff[~(fil | core)] = 0
            effA = up(shift(eff, int(dxy[0]), int(dxy[1])))
            A = over(mesh_rgb, effA)

            # ---- B: procedural 1-px bolts, pixel count / extent / decay measured from the DEF frame
            effB = np.zeros((H, W, 4), np.uint8)
            if st["px"] and st["meanComponent"] < 4 and prev_paths:  # decay frame: scattered sparks
                pts = np.concatenate([np.array(p) for p in prev_paths])
                pick = pts[rng.choice(len(pts), min(len(pts), st["px"]), replace=False)]
                pick = pick + rng.normal(0, 3, pick.shape)
                for x, y in np.round(pick).astype(int):
                    if 0 <= x < W and 0 <= y < H:
                        effB[y, x] = (240, 240, 150, 255) if rng.random() < .6 else (255, 255, 255, 255)
            elif st["px"]:
                paths, k = [], 0
                L = max(8.0, st["extent"] * 0.6)
                while sum(len(p) * 2 for p in paths) < st["px"] and k < 40:
                    o = hs[k % len(hs)]
                    hd = heading + rng.normal(0, 0.9 if clip == "attack_front" else 0.35)
                    paths += bolt_paths(rng, o, hd, L * rng.uniform(.5, 1), 4)
                    k += 1
                prev_paths = paths
                effB = raster_1px((H, W), paths, (255, 255, 255, 255))
                if st["corePx"]:
                    r = max(1.5, 0.5 * math.sqrt(st["corePx"] / math.pi / len(hs)))  # fists are body paint; keep only a small hot spot
                    im = Image.fromarray(effB)
                    dr = ImageDraw.Draw(im)
                    for o in hs:
                        dr.polygon([(o[0] + r * rng.uniform(.6, 1.2) * math.cos(q), o[1] + r * rng.uniform(.6, 1.2) * math.sin(q))
                                    for q in np.linspace(0, 2 * math.pi, 9)[:-1]], fill=(255, 255, 255, 255))
                    effB = np.array(im)
            B = over(mesh_rgb, up(effB))

            # ---- M: typical modern look on the same paths: soft cyan additive halo + AA core
            if effB[..., 3].any():
                a2 = np.array(Image.fromarray(effB[..., 3]).resize((W * S, H * S), Image.BILINEAR)).astype(float) / 255
                halo = gaussian_filter(a2, 5) * 6
                M = np.clip(mesh_rgb + halo[..., None] * np.array([110, 200, 255.0]) * 0.9
                            + gaussian_filter(a2, 1.2)[..., None] * 255 * 1.5, 0, 255)
            else:
                M = mesh_rgb

            # ---- C: body glow as an opaque lerp toward the measured cream (HoMM3 paints it; it adds no light)
            op = (f.idx > 7) & ~fil
            c = pal.astype(float)[f.idx]
            yel = op & (c[..., 0] > 140) & (c[..., 2] < c[..., 0] - 45)
            frac = yel.sum() / max(1, op.sum())
            ys_, _ = np.nonzero(op)
            hcen = float((ys_.max() - np.nonzero(yel)[0].mean()) / max(1, np.ptp(ys_))) if yel.any() else 0.4
            yy, xx = np.mgrid[0:H * S, 0:W * S]
            handw = np.zeros((H * S, W * S))
            if clip != "idle":
                for o in hs:
                    handw = np.maximum(handw, np.exp(-(((xx - o[0] * S) ** 2 + (yy - o[1] * S) ** 2) / (2 * (14 * S) ** 2))))
            band = np.exp(-((hmask - hcen) ** 2) / (2 * 0.12 ** 2))
            w = np.clip(frac * 8, 0, 1) * np.maximum(band * (0.8 if clip == "idle" else 0.4), handw) * (base[..., 3] / 255)
            glow_mesh = base.copy()
            # keep the texture's own relief: the cream is scaled by the mesh's local luminance
            lum = base[..., :3].mean(-1, keepdims=True)
            rel = np.clip(lum / max(1.0, float(lum[base[..., 3] > 0].mean())), 0.4, 2.2)
            glow_mesh[..., :3] = base[..., :3] * (1 - w[..., None]) + np.clip(GLOW * (0.55 + 0.45 * rel), 0, 255) * w[..., None]
            AC = over(over(bgimg, glow_mesh), effA)
            anchors[-1]["glowFraction"] = round(float(frac), 3)
            anchors[-1]["glowHeight"] = round(hcen, 2)

            defimg = over(np.ones((H, W, 3)) * BG, rgba)
            rows.append([up(defimg), mesh_rgb, A, B, M, AC])

        diff = np.zeros((H * S, W * S), bool)
        for r in rows:
            for im in (r[0], r[1], r[3]):
                diff |= np.abs(im - np.array(BG, float)).sum(-1) > 12
        ys, xs = np.nonzero(diff)
        pad = 12
        box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(W * S, xs.max() + pad), min(H * S, ys.max() + pad))
        tw, th = box[2] - box[0], box[3] - box[1]
        gif = []
        for i, r in enumerate(rows):
            canvas = Image.new("RGB", (tw * 6, th + 16), (18, 18, 18))
            dr = ImageDraw.Draw(canvas)
            for j, im in enumerate(r):
                canvas.paste(Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).crop(box), (j * tw, 16))
                dr.text((j * tw + 3, 2), LABELS[j], fill=(230, 230, 230))
            dr.text((3, th + 3), f"{seg} f{i}  ({FRAME_MS} ms/frame)", fill=(255, 255, 120))
            gif.append(canvas)
        gif[0].save(EXP / f"compare_{clip}.gif", save_all=True, append_images=gif[1:], duration=FRAME_MS, loop=0)
        sheet = Image.new("RGB", (tw * 6, (th + 16) * len(gif)), (18, 18, 18))
        for i, g in enumerate(gif):
            sheet.paste(g, (0, i * (th + 16)))
        sheet.save(EXP / f"compare_{clip}_sheet.png")
        report[clip] = anchors
    (EXP / "anchors.json").write_text(json.dumps(report, indent=1))
    for clip, an in report.items():
        print(clip, [(x["masterFrame"], x["px"], x["shiftPx1x"]) for x in an])


if __name__ == "__main__":
    main()
