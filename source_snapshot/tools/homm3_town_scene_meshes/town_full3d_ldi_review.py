#!/usr/bin/env python3
"""Before/after review of the layered-depth back-fill (town_full3d_ldi) on two staged candidates of one faction.

    python tools/homm3_town_scene_meshes/town_full3d_ldi_review.py --faction factory --before fa_v4 --after fa_v5_ldi \
        --out artifacts/homm3_factory_full3d/candidates/fa_v5_ldi/ldi_review [--summary <png>]

Offline moderngl renders (the lane's Hex/Lit diffuse preview, no MSAA in the metric pass), the full build state, of:
  rest                the vanilla rest pose (the pixel-identity check);
  cursor_left/right   the vanilla cursor pan poses (pure rotations: they reveal nothing, a control);
  sweep_left/right/high  the vanilla sweep extremes (the camera's translating pan: what the runtime reaches);
  stress              2 x the sweep_left translation (NOT a runtime pose; a harsher probe).
Per pose and per group (terrain = Mesh_Terrain* + Mesh_Back_*, env = the other environment pieces, buildings):
  revealed        px whose surface point is hidden at the rest pose of the same candidate (reprojected into the rest
                  camera against its rest depth buffer; stronghold_full3d_building_review.measure's test);
  streak          px whose texel footprint is elongated past STREAK_ANISO (one texel smeared over many px);
  revealedStreak  both: the rubber-sheet signature (a surface the painting never saw, smeared).
Rest-frame identity: |after - before| of the rest renders (8-bit sRGB): mean, max, px > 2 and px > 8 levels.
Bridging triangles (rest forward-depth ratio over 1.25 / 1.5 / 2) of every staged lit bin, by group.
Outputs: metrics.json, sheet.png (every pose, before | after, plus zoom crops of each pose's worst terrain streak
window), overlay.png (the same zooms with revealedStreak px in red) and, with --summary, one self-contained PNG
(<= 2400 px wide) with the metrics table on top.
Proof tier: generated artifact / offline render (not the Unity editor, not in-game).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

STRESS_GAIN = 2.0
ZOOM = (480, 270)


def font(sz: int):
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", required=True)
    ap.add_argument("--before", required=True, help="candidate name (candidates/<name>)")
    ap.add_argument("--after", default="", help="candidate name; omit for a before-only measurement")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--label", default="layered-depth back-fill", help="summary header: what the after candidate is")
    ap.add_argument("--summary-poses", default="sweep_left,sweep_right,sweep_high,stress",
                    help="summary body: the poses shown (before | after + worst-streak zoom)")
    a = ap.parse_args()
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import stronghold_full3d_building_review as BR
    import town_full3d_ldi as L

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    W, H = SC.W, SC.H
    pans = S.pan_cams(sc)
    cams = {"rest": sc.cam}
    for k in ("cursor_left", "cursor_right", "sweep_left", "sweep_right", "sweep_high"):
        cams[k] = pans[k]
    sl = pans["sweep_left"]
    cams["stress"] = {**sl, "pos": sc.cam["pos"] + STRESS_GAIN * (np.asarray(sl["pos"]) - sc.cam["pos"])}
    reach = {k: ("control: pure rotation" if k.startswith("cursor") else "not reachable (2x sweep_left translation)"
                 if k == "stress" else "rest pose" if k == "rest" else "reachable (vanilla sweep extreme)")
             for k in cams}
    full = [S.PREFIX + l for l in S.STATES["full"]]
    fov = float(sc.cam["fov"])

    def stage_of(name):
        return SC.DATA / "candidates" / name / "unity_project" / S.ASSET_ROOT

    def load(name):
        st = stage_of(name)
        rows = json.loads((st / "rows.json").read_text(encoding="utf-8"))
        groups = {"terrain": [], "env": [], "buildings": []}
        for prefab in [S.ENV_KEY] + full:
            named = {b["name"] for b in rows.get(prefab, {}).get("bins", [])}
            for it in BR.load_prefab(sc, st, prefab):
                if it[0] not in named:
                    continue
                g = "buildings" if prefab != S.ENV_KEY else \
                    "terrain" if it[0].startswith(("Mesh_Terrain", "Mesh_Back_")) else "env"
                groups[g].append(it)
        bridging = L.measure_stage(st, fov, rows)
        return groups, bridging

    def group_bridging(br):
        g = {"terrain": {}, "env": {}, "buildings": {}}
        for prefab, pcs in br.items():
            for nm, r in pcs.items():
                if prefab == S.ENV_KEY:
                    k = "terrain" if nm.startswith(("Mesh_Terrain", "Mesh_Back_")) else "env"
                elif prefab in full:
                    k = "buildings"
                else:
                    continue
                for c, val in r.items():
                    g[k][c] = g[k].get(c, 0) + val
        return g

    def render_all(groups):
        rig = BR.Rig(sc)
        rig.metas = []
        for pid, g in ((1.0, "terrain"), (2.0, "env"), (3.0, "buildings")):
            rig._add(groups[g], pid)
        res = {}
        rest_lit, rest_a0, rest_a1 = rig.render(sc.cam)
        for ck, cam in cams.items():
            lit, a0, a1 = (rest_lit, rest_a0, rest_a1) if ck == "rest" else rig.render(cam)
            pid = np.round(a0[..., 3]).astype(int)
            Pw = a0[..., :3].reshape(-1, 3).astype(np.float64)
            px, py, zc = S.T.project(sc.cam, Pw)
            inside = (px >= 0) & (px < W) & (py >= 0) & (py < H) & (zc > 0)
            xi = np.clip(np.nan_to_num(px).astype(int), 0, W - 1)
            yi = np.clip(np.nan_to_num(py).astype(int), 0, H - 1)
            rp = rest_a0[yi, xi]
            rz = np.where(rp[:, 3] > 0.5, (rp[:, :3].astype(np.float64) - sc.cam["pos"]) @ sc.cam["fwd"], np.inf)
            revealed = (inside & (zc > rz * 1.004 + 0.1)).reshape(H, W) & (pid > 0)
            streak = (a1[..., 0] > BR.STREAK_ANISO) & (pid > 0)
            m = {}
            for gi, g in ((1, "terrain"), (2, "env"), (3, "buildings")):
                sel = pid == gi
                m[g] = {"px": int(sel.sum()), "revealed": int((revealed & sel).sum()),
                        "streak": int((streak & sel).sum()), "revealedStreak": int((revealed & streak & sel).sum())}
            # nothing drawn at all: the preview's clear colour (pure magenta) - a hole, never content
            empty = (lit[..., 0] >= 250) & (lit[..., 1] <= 5) & (lit[..., 2] >= 250) & (pid < 0)
            m["emptyPx"] = int(empty.sum())
            res[ck] = {"lit": lit, "m": m, "pid": pid, "empty": empty, "rs": revealed & streak, "rs_t": revealed & streak & (pid == 1)}
        rig.ctx.release()
        return res

    names = [a.before] + ([a.after] if a.after else [])
    data = {}
    for nm in names:
        groups, br = load(nm)
        print(nm, {g: len(v) for g, v in groups.items()}, flush=True)
        data[nm] = {"bridging": br, "bridgingByGroup": group_bridging(br), "shots": render_all(groups)}
    B = data[a.before]
    A = data[a.after] if a.after else None
    doc = {"schema": "town_full3d_ldi_review.v1", "faction": a.faction, "before": a.before, "after": a.after or None,
           "proofTier": "generated artifact / offline render (moderngl Hex/Lit preview; not Unity, not in-game)",
           "streakAniso": BR.STREAK_ANISO, "poses": reach, "stressGain": STRESS_GAIN,
           "bridging": {nm: data[nm]["bridgingByGroup"] for nm in names},
           "bridgingPieces": {nm: {p: {k: v for k, v in r.items() if any(v2 for k2, v2 in v.items() if k2 != "tris")}
                                   for p, r in data[nm]["bridging"].items()} for nm in names},
           "perPose": {ck: {nm: data[nm]["shots"][ck]["m"] for nm in names} for ck in cams}}
    if A is not None:
        rb, ra = B["shots"]["rest"]["lit"].astype(np.int16), A["shots"]["rest"]["lit"].astype(np.int16)
        d = np.abs(rb - ra).max(-1)
        rest_d = d
        doc["restDiff"] = {"meanAbs": round(float(np.abs(rb - ra).mean()), 5), "max": int(d.max()),
                           "pxOver2": int((d > 2).sum()), "pxOver8": int((d > 8).sum()), "px": int(d.size)}
        Image.fromarray(np.clip(d * 16, 0, 255).astype(np.uint8)).save(out / "rest_diff_x16.png")
        pb, pa = B["shots"]["rest"]["pid"], A["shots"]["rest"]["pid"]
        grp = {0: "none", 1: "terrain", 2: "env", 3: "buildings"}
        doc["restDiff"]["over8ByGroup"] = {f"{grp.get(i, i)}->{grp.get(j, j)}": int(((d > 8) & (pb == i) & (pa == j)).sum())
                                           for i in range(4) for j in range(4) if ((d > 8) & (pb == i) & (pa == j)).any()}
        Image.fromarray(B["shots"]["rest"]["lit"]).save(out / "rest_before.png")
        Image.fromarray(A["shots"]["rest"]["lit"]).save(out / "rest_after.png")
    if A is not None:
        # sky holes: pixels the before scene shows as terrain that the after scene shows as sky (unlit, no meta id)
        doc["skyHoles"] = {}
        for ck in cams:
            pb_, pa_ = B["shots"][ck]["pid"], A["shots"][ck]["pid"]
            sky_a = (pa_ < 0) & ~A["shots"][ck]["empty"]
            doc["skyHoles"][ck] = {"terrainToSky": int((sky_a & (pb_ == 1)).sum()),
                                   "anyToSky": int((sky_a & (pb_ > 0)).sum())}
    (out / "metrics.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------------------------------------- sheets
    f_lab, f_big = font(18), font(24)

    def tile(img, text, wt):
        im = Image.fromarray(img).resize((wt, round(img.shape[0] * wt / img.shape[1])), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        tw = d.textlength(text, font=f_lab)
        d.rectangle((0, 0, tw + 12, 26), fill=(0, 0, 0))
        d.text((6, 3), text, fill=(255, 255, 255), font=f_lab)
        return im

    def row(ims, gap=8):
        o = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), max(i.height for i in ims)), (40, 40, 40))
        x = 0
        for i in ims:
            o.paste(i, (x, 0))
            x += i.width + gap
        return o

    def col(ims, gap=8, bg=(40, 40, 40)):
        o = Image.new("RGB", (max(i.width for i in ims), sum(i.height for i in ims) + gap * (len(ims) - 1)), bg)
        y = 0
        for i in ims:
            o.paste(i, (0, y))
            y += i.height + gap
        return o

    def worst_box(mask):
        import cv2
        s = cv2.boxFilter(mask.astype(np.float32), -1, ZOOM, normalize=False)
        y, x = np.unravel_index(np.argmax(s), s.shape)
        x0 = int(np.clip(x - ZOOM[0] // 2, 0, W - ZOOM[0]))
        y0 = int(np.clip(y - ZOOM[1] // 2, 0, H - ZOOM[1]))
        return (x0, y0, x0 + ZOOM[0], y0 + ZOOM[1]), float(s.max())

    def mtxt(nm, ck):
        m = data[nm]["shots"][ck]["m"]
        t, b = m["terrain"], m["buildings"]
        return (f"terrain rev {t['revealed']} streak {t['streak']} rev+streak {t['revealedStreak']} | "
                f"bld rev+streak {b['revealedStreak']}")

    def sheet(wt, zoom_poses, overlay=False, only=None):
        rows_ = []
        for ck in cams:
            if only is not None and ck not in only:
                continue
            cells = [tile(B["shots"][ck]["lit"], f"{ck} BEFORE {a.before} [{reach[ck]}]  {mtxt(a.before, ck)}", wt)]
            if A is not None:
                cells.append(tile(A["shots"][ck]["lit"], f"{ck} AFTER {a.after}  {mtxt(a.after, ck)}", wt))
            rows_.append(row(cells))
            if ck in zoom_poses:
                box, score = worst_box(B["shots"][ck]["rs_t"])
                if score <= 0:
                    continue
                zc = []
                for nm in names:
                    img = data[nm]["shots"][ck]["lit"].copy()
                    if overlay:
                        img[data[nm]["shots"][ck]["rs"]] = (255, 0, 0)
                    zc.append(tile(img[box[1]:box[3], box[0]:box[2]],
                                   f"{ck} zoom x{wt / ZOOM[0]:.1f} {nm} @({box[0]},{box[1]})"
                                   + (" red = revealed+streak" if overlay else ""), wt))
                rows_.append(row(zc))
        return col(rows_)

    zp = [k for k in cams if k not in ("rest",)]
    sheet(960, zp).save(out / "sheet.png")
    sheet(960, zp, overlay=True).save(out / "overlay.png")
    if a.summary:
        wt = 1140
        head = Image.new("RGB", (2 * wt + 8, 10), (24, 24, 24))
        lines = [f"{a.faction}: {a.before} (before, installed) vs {a.after} (after, {a.label}) - "
                 "offline moderngl preview renders, generated artifact; not Unity, not in-game"]
        if A is not None:
            rd = doc["restDiff"]
            lines.append(f"rest frame |after-before|: mean {rd['meanAbs']} / max {rd['max']} levels; "
                         f"px > 2 levels: {rd['pxOver2']}, px > 8: {rd['pxOver8']} of {rd['px']}")
        for nm in names:
            g = doc["bridging"][nm]
            lines.append(f"bridging tris (rest depth ratio >1.25/>1.5/>2) {nm}: terrain "
                         f"{'/'.join(str(g['terrain'].get(c, 0)) for c in ('>1.25', '>1.5', '>2'))}  buildings "
                         f"{'/'.join(str(g['buildings'].get(c, 0)) for c in ('>1.25', '>1.5', '>2'))}  env "
                         f"{'/'.join(str(g['env'].get(c, 0)) for c in ('>1.25', '>1.5', '>2'))}")
        lines.append("terrain revealed+streak px per pose (before -> after):  " + "   ".join(
            f"{ck} {doc['perPose'][ck][a.before]['terrain']['revealedStreak']}"
            + (f"->{doc['perPose'][ck][a.after]['terrain']['revealedStreak']}" if A is not None else "")
            for ck in cams))
        lines.append("terrain streak px per pose (before -> after):  " + "   ".join(
            f"{ck} {doc['perPose'][ck][a.before]['terrain']['streak']}"
            + (f"->{doc['perPose'][ck][a.after]['terrain']['streak']}" if A is not None else "")
            for ck in cams))
        lines.append("empty (clear colour) px per pose (before -> after):  " + "   ".join(
            f"{ck} {doc['perPose'][ck][a.before]['emptyPx']}"
            + (f"->{doc['perPose'][ck][a.after]['emptyPx']}" if A is not None else "") for ck in cams)
)
        if A is not None:
            lines.append("sky holes (terrain in before, sky in after) px per pose:  " + "   ".join(
                f"{ck} {doc['skyHoles'][ck]['terrainToSky']}" for ck in cams))
        head = Image.new("RGB", (2 * wt + 8, 16 + 32 * len(lines)), (24, 24, 24))
        d = ImageDraw.Draw(head)
        for i, ln in enumerate(lines):
            d.text((10, 8 + 32 * i), ln, fill=(255, 255, 255) if i else (255, 220, 120), font=f_big if i == 0 else font(20))
        body = sheet(wt, [p for p in a.summary_poses.split(",") if p],
                     only=[p for p in a.summary_poses.split(",") if p])
        parts = [head]
        if A is not None:
            # the rest frame's densest > 8-level difference window, 2x: before | after, the difference marked red
            m8 = rest_d > 8
            ii = np.pad(m8.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
            bw, bh = 480, 270
            ys_, xs_ = np.mgrid[0:H - bh + 1:10, 0:W - bw + 1:10]
            cnt = ii[ys_ + bh, xs_ + bw] - ii[ys_, xs_ + bw] - ii[ys_ + bh, xs_] + ii[ys_, xs_]
            k = int(np.argmax(cnt))
            y0, x0 = int(ys_.ravel()[k]), int(xs_.ravel()[k])
            rbf = B["shots"]["rest"]["lit"][y0:y0 + bh, x0:x0 + bw]
            raf = A["shots"]["rest"]["lit"][y0:y0 + bh, x0:x0 + bw].copy()
            raf[m8[y0:y0 + bh, x0:x0 + bw]] = (255, 0, 0)
            parts.append(row([tile(rbf, f"rest {a.before} @({x0},{y0}) x{wt / bw:.2f}", wt),
                              tile(raf, f"rest {a.after}, px > 8 levels vs before in red "
                                        f"({int(m8[y0:y0 + bh, x0:x0 + bw].sum())} here, {int(m8.sum())} in frame)",
                                   wt)]))
        s = col(parts + [body], bg=(24, 24, 24))
        Path(a.summary).parent.mkdir(parents=True, exist_ok=True)
        s.save(a.summary, optimize=True)
        print("summary", a.summary, s.size)
    print(json.dumps({"bridging": doc["bridging"], "restDiff": doc.get("restDiff"),
                      "terrainRevealedStreak": {ck: {nm: doc["perPose"][ck][nm]["terrain"]["revealedStreak"]
                                                     for nm in names} for ck in cams}}, indent=1))
    bad = {f"{nm}/{ck}": doc["perPose"][ck][nm]["emptyPx"] for nm in names[1:] for ck in cams if ck != "stress"
           if doc["perPose"][ck][nm]["emptyPx"]}
    if bad:
        print(f"FAIL: the after scene leaves empty (clear-colour / magenta) pixels: {bad}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
