"""Measure the fire motion the phoenix DEF (CPHX.DEF) actually draws, per clip.

Regions per frame (indexed DEF via h3def; slot 5 selection outline treated as transparent):
- BODY:   the silhouette after a morphological opening (disk r=OPEN_R) and keeping the largest
          component: feathers, wings, tail, legs. Flame tongues are thinner than 2*OPEN_R+1 px.
- FLAME:  opaque main-silhouette pixels outside BODY (the tongues licking off the body).
- EMBER:  opaque pixels in components detached from the main silhouette (sparks, the breath jet).
- CORE:   BODY pixels with luma >= CORE_L (the white-yellow hot core painted into the body).

Measurements (DEF px per DEF frame; 12 fps as extracted; +y is down on screen):
1. per consecutive pair (and the loop seam for idle / mouseover):
   - rigid shift of the whole silhouette (SSD search);
   - fraction of BODY / FLAME-zone pixels whose colour changed (>60 sum RGB) after that shift;
   - FLAME-zone block flow: 8x8 blocks over the flame zone, each block's best shift (+-6 px)
     relative to the silhouette shift. best/zero < 0.6 counts as coherent travel, else redraw.
2. loops: multi-lag texture velocity for the flame zone and the body interior, the lag
   dissimilarity curve, flame-pixel membership flip rate per lag, and highlight (CORE) survival
   against chance. Spatial distribution of flame pixels: by height band of the body box and by
   the side of the body (leading edge = beak side, trailing = tail side).
3. per clip: flame / ember / core pixel counts per frame, unique-frame sequence (holds and
   ping-pongs from the DEF's own frame names).

Outputs: artifacts/homm3_vfx_experiments/phoenix/evidence/fire_motion.json, fire_motion_summary.txt,
regions_g<group>.png (4x: body outline white, flame red, ember yellow, core cyan, coherent flow arrows).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
import h3def  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/homm3_vfx_experiments/phoenix/evidence"
CLIPS = {2: "idle", 1: "mouseover", 20: "move_start", 0: "move", 21: "move_end", 3: "hitted",
         4: "defence", 12: "attack_front", 11: "attack_up", 13: "attack_down", 5: "death"}
LOOPING = {2, 0}
OPEN_R = 3
CORE_L = 225.0
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def frame_rgba(fr, pal):
    rgba = h3def.to_rgba(fr, pal)
    rgba[fr.idx == 5] = 0
    return rgba


def segment(rgba):
    opaque = rgba[..., 3] == 255
    lab, n = ndimage.label(opaque, structure=np.ones((3, 3)))
    sizes = ndimage.sum(opaque, lab, index=np.arange(1, n + 1)) if n else []
    main = lab == 1 + int(np.argmax(sizes)) if n else opaque
    opened = ndimage.binary_opening(main, disk(OPEN_R))
    lb, nb = ndimage.label(opened)
    body = lb == 1 + int(np.argmax(ndimage.sum(opened, lb, index=np.arange(1, nb + 1)))) if nb else opened
    body = ndimage.binary_dilation(body, disk(1)) & main
    flame = main & ~body
    ember = opaque & ~main
    luma = rgba[..., :3].astype(np.float32) @ LUMA
    core = body & (luma >= CORE_L)
    return {"opaque": opaque, "main": main, "body": body, "flame": flame, "ember": ember, "core": core, "luma": luma}


def rigid_shift(a, b, mask, search=8):
    ys, xs = np.nonzero(mask)
    if len(ys) < 20:
        return (0, 0)
    H, W = mask.shape
    best, bc = (0, 0), np.inf
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            y2, x2 = ys + dy, xs + dx
            ok = (y2 >= 0) & (y2 < H) & (x2 >= 0) & (x2 < W)
            c = float(np.mean((a[ys[ok], xs[ok]] - b[y2[ok], x2[ok]]) ** 2)) + (1e-3 * (dx * dx + dy * dy))
            if c < bc:
                best, bc = (dx, dy), c
    return best


def block_flow(la, lb, zone, occ_b, block=8, search=6):
    """Per 8x8 block of the flame zone: best shift of frame a's texture into frame b (luma + occupancy)."""
    H, W = zone.shape
    out = []
    for y0 in range(0, H - block, block):
        for x0 in range(0, W - block, block):
            m = zone[y0:y0 + block, x0:x0 + block]
            if m.sum() < 12:
                continue
            pa = la[y0:y0 + block, x0:x0 + block]
            costs = {}
            for dy in range(-search, search + 1):
                for dx in range(-search, search + 1):
                    ya, xa = y0 + dy, x0 + dx
                    if ya < 0 or xa < 0 or ya + block > H or xa + block > W:
                        continue
                    pb = lb[ya:ya + block, xa:xa + block]
                    costs[(dx, dy)] = float(np.mean((pa - pb)[m] ** 2))
            if (0, 0) not in costs:
                continue
            best = min(costs, key=lambda k: costs[k] + 2.0 * (k[0] ** 2 + k[1] ** 2))
            z = costs[(0, 0)]
            ratio = costs[best] / z if z > 1e-6 else 1.0
            out.append({"x": x0 + block // 2, "y": y0 + block // 2, "d": best, "ratio": ratio})
    return out


def multilag_velocity(L, region, lags=(1, 2, 3), vmax=4.0, step=0.5):
    n = len(L)
    ys, xs = np.nonzero(region)
    if len(ys) < 30:
        return None
    vs = np.arange(-vmax, vmax + 1e-6, step)
    HP = [l - ndimage.gaussian_filter(l, 3) for l in L]

    def cost(vx, vy):
        c = []
        for lag in lags:
            for t in range(n):
                b = ndimage.shift(HP[(t + lag) % n], (-vy * lag, -vx * lag), order=1, mode="nearest")
                c.append(np.mean((HP[t] - b)[region] ** 2))
        return float(np.mean(c))

    C = np.array([[cost(vx, vy) for vx in vs] for vy in vs])
    j, i = np.unravel_index(np.argmin(C), C.shape)
    zero = C[len(vs) // 2, len(vs) // 2]
    return {"bestV": [float(vs[i]), float(vs[j])], "bestOverZero": round(float(C[j, i] / zero), 3)}


def loop_analysis(rgba, segs):
    n = len(rgba)
    L = [s["luma"] for s in segs]
    body_int = segs[0]["body"].copy()
    for s in segs:
        body_int &= ndimage.binary_erosion(s["body"], disk(2))
    zone = np.zeros_like(body_int)
    for s in segs:
        zone |= s["flame"]
    zone &= ~body_int
    flame = [s["flame"] for s in segs]
    flip = []
    for lag in range(1, n):
        flip.append(round(float(np.mean([(flame[t] ^ flame[(t + lag) % n])[zone].mean() for t in range(n)])), 3))
    lagd = []
    HP = [l - ndimage.gaussian_filter(l, 3) for l in L]
    for lag in range(1, n):
        lagd.append(round(float(np.mean([np.mean((HP[t] - HP[(t + lag) % n])[body_int] ** 2) for t in range(n)])), 1))
    keep, chance = [], []
    for t in range(n):
        c0, c1 = segs[t]["core"] & body_int, segs[(t + 1) % n]["core"] & body_int
        near = ndimage.binary_dilation(c1, np.ones((3, 3)))
        keep.append(float((c0 & near).sum() / max(1, c0.sum())))
        chance.append(float(near[body_int].mean()))
    # flame tongue tips: the topmost flame pixel per column, tracked frame to frame
    tops = []
    for f in flame:
        cols = np.nonzero(f.any(0))[0]
        tops.append({int(c): int(np.nonzero(f[:, c])[0].min()) for c in cols})
    tipdy = []
    for t in range(n):
        a, b = tops[t], tops[(t + 1) % n]
        common = [c for c in a if c in b]
        tipdy.append(float(np.median([b[c] - a[c] for c in common])) if common else 0.0)
    return {
        "flameZonePx": int(zone.sum()), "bodyInteriorPx": int(body_int.sum()),
        "flameMembershipFlipByLag": flip,
        "bodyInteriorLagDissimilarity": lagd,
        "flameVelocity": multilag_velocity(L, zone),
        "bodyInteriorVelocity": multilag_velocity(L, body_int),
        "coreSurvivesWithin1px": round(float(np.mean(keep)), 3), "coreChance": round(float(np.mean(chance)), 3),
        "medianTipDyPerFrame": [round(v, 1) for v in tipdy],
    }


def spatial(segs, facing_right=True):
    """Where the flames sit relative to the body box: height thirds and front/back halves."""
    acc = {"top": 0, "mid": 0, "low": 0, "front": 0, "back": 0, "aboveBody": 0}
    tot = 0
    for s in segs:
        ys, xs = np.nonzero(s["body"])
        if not len(ys):
            continue
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        fy, fx = np.nonzero(s["flame"])
        tot += len(fy)
        h = max(1, y1 - y0)
        rel = (fy - y0) / h
        acc["aboveBody"] += int((fy < y0).sum())
        acc["top"] += int((rel < 1 / 3).sum())
        acc["mid"] += int(((rel >= 1 / 3) & (rel < 2 / 3)).sum())
        acc["low"] += int((rel >= 2 / 3).sum())
        cx = 0.5 * (x0 + x1)
        acc["front"] += int(((fx > cx) if facing_right else (fx < cx)).sum())
        acc["back"] += int(((fx <= cx) if facing_right else (fx >= cx)).sum())
    return {k: round(v / max(1, tot), 3) for k, v in acc.items()} | {"flamePx": tot}


def analyse(d, g):
    frames = d.groups[g]
    rgba = [frame_rgba(f, d.palette) for f in frames]
    segs = [segment(r) for r in rgba]
    n = len(frames)
    loop = g in LOOPING
    pairs = [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if loop else [])
    recs = []
    for i, j in pairs:
        a, b = rgba[i][..., :3].astype(np.float32), rgba[j][..., :3].astype(np.float32)
        sx, sy = rigid_shift(a, b, segs[i]["body"])
        bs = np.roll(np.roll(b, -sy, 0), -sx, 1)
        ob = np.roll(np.roll(segs[j]["opaque"], -sy, 0), -sx, 1)
        chg = np.abs(a - bs).sum(-1) > 60
        body_i = ndimage.binary_erosion(segs[i]["body"], disk(2))
        zone = ndimage.binary_dilation(segs[i]["flame"], disk(2)) & ~body_i
        lb = np.roll(np.roll(segs[j]["luma"], -sy, 0), -sx, 1)
        lb = np.where(ob, lb, 0.0)
        la = np.where(segs[i]["opaque"], segs[i]["luma"], 0.0)
        fl = block_flow(la, lb, zone, ob)
        coh = [f for f in fl if f["ratio"] < 0.6 and f["d"] != (0, 0)]
        rec = {"pair": [i, j], "silShift": [sx, sy],
               "bodyChanged": round(float((chg & body_i & ob).sum() / max(1, (body_i & ob).sum())), 3),
               "flameZoneMembershipChanged": round(float((segs[i]["flame"] ^ np.roll(np.roll(segs[j]["flame"], -sy, 0), -sx, 1))[zone].mean()), 3) if zone.any() else None,
               "flowBlocks": len(fl), "coherentBlocks": len(coh),
               "coherentMeanD": [round(float(np.mean([c["d"][0] for c in coh])), 2), round(float(np.mean([c["d"][1] for c in coh])), 2)] if coh else None,
               "coherentUpShare": round(float(np.mean([c["d"][1] < 0 for c in coh])), 2) if coh else None,
               "_flow": fl}
        recs.append(rec)
    per = [{"flame": int(s["flame"].sum()), "ember": int(s["ember"].sum()), "core": int(s["core"].sum()),
            "body": int(s["body"].sum()), "emberSpecks": int(ndimage.label(s["ember"], np.ones((3, 3)))[1]),
            "coreShareOfBody": round(float(s["core"].sum() / max(1, s["body"].sum())), 3)} for s in segs]
    names = [f.name for f in frames]
    uniq = []
    for nme in names:
        if nme not in uniq:
            uniq.append(nme)
    seq = [uniq.index(nm) for nm in names]
    res = {"name": CLIPS.get(g, str(g)), "frames": n, "uniqueFrames": len(uniq), "frameSeq": seq, "perFrame": per,
           "pairs": recs, "spatial": spatial(segs)}
    if loop:
        res["loop"] = loop_analysis(rgba, segs)
    return rgba, segs, res


def draw(rgba, segs, res, path, scale=3):
    m = np.zeros(rgba[0].shape[:2], bool)
    for s in segs:
        m |= s["opaque"]
    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = xs.min() - 3, ys.min() - 3, xs.max() + 4, ys.max() + 4
    W, H = (x1 - x0) * scale, (y1 - y0) * scale
    sheet = Image.new("RGB", (W * len(segs), H + 14), (40, 40, 40))
    for k, (r, s) in enumerate(zip(rgba, segs)):
        arr = np.full(r.shape[:2] + (3,), 40, np.uint8)
        arr[s["opaque"]] = (r[..., :3][s["opaque"]] * 0.5).astype(np.uint8)
        arr[s["flame"]] = (230, 40, 30)
        arr[s["ember"]] = (255, 230, 40)
        arr[s["core"]] = (60, 230, 255)
        edge = s["body"] & ~ndimage.binary_erosion(s["body"])
        arr[edge] = (255, 255, 255)
        tile = Image.fromarray(arr[y0:y1, x0:x1]).resize((W, H), Image.NEAREST)
        dr = ImageDraw.Draw(tile)
        if k < len(res["pairs"]):
            for f in res["pairs"][k]["_flow"]:
                if f["ratio"] < 0.6 and f["d"] != (0, 0):
                    px, py = (f["x"] - x0) * scale, (f["y"] - y0) * scale
                    dr.line([(px, py), (px + f["d"][0] * scale * 2, py + f["d"][1] * scale * 2)], fill=(80, 255, 80), width=2)
        sheet.paste(tile, (k * W, 0))
        ImageDraw.Draw(sheet).text((k * W + 3, H + 1), f"{k} fl{res['perFrame'][k]['flame']} em{res['perFrame'][k]['ember']}", fill=(230, 230, 230))
    sheet.save(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = h3def.read_def("cphx.def")
    report = {"def": "CPHX.DEF", "units": "DEF px per DEF frame; frames extracted at 12 fps; +y down",
              "regions": {"openRadius": OPEN_R, "coreLuma": CORE_L}, "clips": {}}
    lines = []
    for g in CLIPS:
        rgba, segs, res = analyse(d, g)
        draw(rgba, segs, res, OUT / f"regions_g{g:02d}.png")
        report["clips"][str(g)] = res
        lines.append(f"== g{g:02d} {res['name']}: {res['frames']} frames, {res['uniqueFrames']} unique, seq {res['frameSeq']}")
        lines.append("   spatial " + json.dumps(res["spatial"]))
        for p in res["pairs"]:
            lines.append(f"   {p['pair']} sil{p['silShift']} bodyChg {p['bodyChanged']} flameFlip {p['flameZoneMembershipChanged']} "
                         f"coherent {p['coherentBlocks']}/{p['flowBlocks']} meanD {p['coherentMeanD']} up {p['coherentUpShare']}")
        lines.append("   perFrame flame " + str([p["flame"] for p in res["perFrame"]]) + " ember " + str([p["ember"] for p in res["perFrame"]])
                     + " core% " + str([p["coreShareOfBody"] for p in res["perFrame"]]))
        if "loop" in res:
            lines.append("   loop " + json.dumps(res["loop"]))
    for c in report["clips"].values():
        for p in c["pairs"]:
            p["flow"] = [{"x": f["x"], "y": f["y"], "d": list(f["d"]), "ratio": round(f["ratio"], 3)} for f in p.pop("_flow")]
    (OUT / "fire_motion.json").write_text(json.dumps(report, indent=1))
    (OUT / "fire_motion_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
