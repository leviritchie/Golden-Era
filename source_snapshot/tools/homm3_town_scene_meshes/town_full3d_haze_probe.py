#!/usr/bin/env python3
"""Atmospheric-haze masking probe for the full-3D town rubber-sheet streaks (offline, one staged candidate).

    python tools/homm3_town_scene_meshes/town_full3d_haze_probe.py --faction factory --candidate fa_v4 \
        --out <dir> [--summary <png>]

Question: can a vanilla-style distance / height haze (cityHuman2 ships linear RenderSettings fog, colour
(0.580, 0.773, 0.767), start 16.1 / end 92.1 m; the full-3D lane sets catalog "fog": "off") fade the far canyon's
smears into atmosphere at the reachable sweep poses without touching the rest frame's painting texels?

Poses are exactly town_full3d_ldi_review.py's rest / sweep_left / sweep_right / sweep_high (S.pan_cams: the native
cityHuman2 sweep extremes, unframed, panScale 1). The haze is applied as a post pass on the moderngl Hex/Lit preview
from the per-pixel world position (the same quantity a fog term in the shader sees), so the numbers are what a fog
of that shape would do, not a claim about the Hex pipeline's own fog path.

Variants (see HAZES): static distance fog (vanilla shape), static far-only fog (starts behind the town), and the same
fog with its density ramped by the camera's offset from the rest pose (zero at rest by construction).
Per pose and variant: terrain streak px, the streak px' residual contrast sum(1 - fog) ("unmasked streak"), the
revealed+streak equivalent, and the rest-frame diff. Proof tier: generated artifact / offline render.
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
sys.path.insert(0, str(HERE.parent / "homm3_unit_look"))

ZOOM = (480, 270)
POSES = ("rest", "sweep_left", "sweep_right", "sweep_high")


def font(sz: int):
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--best", default="", help="variant for the summary's right column (default: lowest unmasked "
                                               "streak among the variants with zero rest diff)")
    ap.add_argument("--from-cache", action="store_true", help="reuse <out>/buffers.npz (no GPU render)")
    a = ap.parse_args()
    import gpuslot
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import stronghold_full3d_building_review as BR

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    W, H = SC.W, SC.H
    pans = S.pan_cams(sc)
    cams = {"rest": sc.cam, **{k: pans[k] for k in POSES[1:]}}
    full = [S.PREFIX + l for l in S.STATES["full"]]
    st = SC.DATA / "candidates" / a.candidate / "unity_project" / S.ASSET_ROOT
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

    shots = {}
    cache = out / "buffers.npz"
    if a.from_cache:
        z = np.load(cache)
        for ck in POSES:
            shots[ck] = {k: z[f"{ck}_{k}"] for k in ("lit", "pid", "streak", "revealed", "dist", "y")}
            shots[ck]["cam"] = cams[ck]
    else:
        shots = render_shots(a, sc, cams, groups, gpuslot, S, BR, W, H)
        np.savez_compressed(cache, **{f"{ck}_{k}": v for ck, s_ in shots.items() for k, v in s_.items() if k != "cam"})
    main_rest(a, sc, shots, out, BR, W, H)
    return 0


def render_shots(a, sc, cams, groups, gpuslot, S, BR, W, H):
    shots = {}
    with gpuslot.slot(sys.argv, f"haze_probe_{a.candidate}"):
        rig = BR.Rig(sc)
        rig.metas = []
        for pid, g in ((1.0, "terrain"), (2.0, "env"), (3.0, "buildings")):
            rig._add(groups[g], pid)
        rest_lit, rest_a0, _ = rig.render(sc.cam)
        for ck, cam in cams.items():
            lit, a0, a1 = rig.render(cam)
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
            dist = np.linalg.norm(a0[..., :3].astype(np.float64) - np.asarray(cam["pos"]), axis=-1)
            shots[ck] = {"lit": lit.copy(), "pid": pid, "streak": streak, "revealed": revealed, "dist": dist,
                         "y": a0[..., 1].astype(np.float64), "cam": cam}
        rig.ctx.release()
    for s_ in shots.values():
        s_["pid"] = s_["pid"].astype(np.int8)
        s_["dist"] = s_["dist"].astype(np.float32)
        s_["y"] = s_["y"].astype(np.float32)
    return shots


def main_rest(a, sc, shots, out, BR, W, H):
    # ---------------------------------------------------------------- where the smears are (depth / height)
    r = shots["rest"]
    tpx = r["pid"] == 1
    bpx = r["pid"] == 3
    q = lambda v: [round(float(x), 1) for x in np.percentile(v, [5, 25, 50, 75, 95])] if v.size else []
    depth = {"restTerrainDist_p5_25_50_75_95": q(r["dist"][tpx]),
             "restBuildingDist_p5_25_50_75_95": q(r["dist"][bpx]),
             "restTerrainY_p5_25_50_75_95": q(r["y"][tpx])}
    for ck in POSES[1:]:
        s_ = shots[ck]
        m = s_["streak"] & (s_["pid"] == 1)
        depth[f"{ck}TerrainStreakDist_p5_25_50_75_95"] = q(s_["dist"][m])
        depth[f"{ck}TerrainStreakY_p5_25_50_75_95"] = q(s_["y"][m])
        depth[f"{ck}AllStreakDist_p5_25_50_75_95"] = q(s_["dist"][s_["streak"]])
    bmax = float(np.percentile(r["dist"][bpx], 99)) if bpx.any() else 0.0

    # fog colour: the painting's own sky just above the horizon at rest (vanilla: the scene fog matches its horizon)
    sky = r["pid"] < 0
    ys, xs = np.nonzero(sky)
    lowest = np.zeros(W, int) - 1
    np.maximum.at(lowest, xs, ys)
    band = np.zeros_like(sky)
    for x in range(0, W, 4):
        y0 = lowest[x]
        if y0 > 20:
            band[max(0, y0 - 40):y0 - 8, x] = True
    band &= sky
    fogc = np.median(r["lit"][band].reshape(-1, 3), 0) if band.any() else np.array([148, 197, 196])
    vanilla_c = np.array([0.580, 0.773, 0.767]) * 255
    rest_off = np.asarray(sc.cam["pos"], np.float64)
    offs = {ck: float(np.linalg.norm(np.asarray(shots[ck]["cam"]["pos"]) - rest_off)) for ck in POSES}
    off_max = max(offs.values())

    # ---------------------------------------------------------------- haze variants
    tdist = r["dist"][tpx]
    d50, d75, d95 = (float(np.percentile(tdist, p)) for p in (50, 75, 95))
    far0 = max(bmax, d75)
    floor_y = float(np.percentile(r["y"][tpx], 50))   # the town floor (most rest terrain px lie on it)

    def fog_static(sh, start, end, dmax, colour, rise=None, terrain_only=False):
        f = dmax * smoothstep(start, end, sh["dist"])
        if rise is not None:                # none on the town floor, full on the canyon walls above it
            f = f * smoothstep(rise[0], rise[1], sh["y"])
        f = np.where((sh["pid"] > 0) & ((sh["pid"] != 3) if terrain_only else True), f, 0.0)
        return f, colour

    def ramped(**kw):
        return lambda sh: (lambda f, c: (f * offs_ramp(sh), c))(*fog_static(sh, colour=fogc, **kw))

    HAZES = {
        "vanilla_linear": lambda sh: fog_static(sh, d50 * 0.3, d95 * 1.3, 1.0, vanilla_c),
        "static_far": lambda sh: fog_static(sh, far0, d95 * 1.2, 0.85, fogc),
        "static_far_strong": lambda sh: fog_static(sh, far0, d95, 1.0, fogc),
        "ramped_far": ramped(start=far0, end=d95 * 1.2, dmax=0.85),
        "ramped_mid": ramped(start=d50, end=d95, dmax=0.9),
        "ramped_mid_strong": ramped(start=d50 * 0.8, end=d75 * 1.1, dmax=1.0),
        # terrain + env only (buildings keep their texels), rising off the town floor: canyon walls only
        "ramped_walls": ramped(start=d50, end=d95, dmax=0.9, rise=(floor_y, floor_y + 12), terrain_only=True),
        "ramped_walls_strong": ramped(start=d50 * 0.8, end=d75 * 1.2, dmax=1.0, rise=(floor_y, floor_y + 8),
                                      terrain_only=True),
    }

    DESC = {"ramped_mid": f"dist smoothstep {d50:.0f}->{d95:.0f} max 0.9, all surfaces, "
                          "density x smoothstep(camera offset / sweep max)",
            "ramped_walls": f"dist smoothstep {d50:.0f}->{d95:.0f} max 0.9, terrain+env only, rising off the floor "
                            "over 12 u, density x smoothstep(camera offset / sweep max)",
            "ramped_walls_strong": f"dist smoothstep {d50 * 0.8:.0f}->{d75 * 1.2:.0f} max 1.0, terrain+env only, rising "
                                   "off the floor over 8 u, density x smoothstep(camera offset / sweep max)",
            "ramped_mid_strong": f"dist smoothstep {d50 * 0.8:.0f}->{d75 * 1.1:.0f} max 1.0, all surfaces, "
                                 "density x smoothstep(camera offset / sweep max)"}

    def offs_ramp(sh):
        o = float(np.linalg.norm(np.asarray(sh["cam"]["pos"]) - rest_off))
        return float(smoothstep(0.0, off_max, o))

    def apply(sh, name):
        if name == "none":
            return sh["lit"], np.zeros(sh["pid"].shape)
        f, c = HAZES[name](sh)
        img = sh["lit"].astype(np.float64) * (1 - f[..., None]) + np.asarray(c)[None, None] * f[..., None]
        return np.clip(np.round(img), 0, 255).astype(np.uint8), f

    res = {"schema": "town_full3d_haze_probe.v1", "faction": a.faction, "candidate": a.candidate,
           "proofTier": "generated artifact / offline render (moderngl Hex/Lit preview + post-pass haze; "
                        "not Unity, not in-game)",
           "poses": "town_full3d_ldi_review rest / sweep_left / sweep_right / sweep_high (native, unframed)",
           "streakAniso": BR.STREAK_ANISO, "fogColourPaintingHorizon": [int(v) for v in fogc],
           "fogColourVanillaCityHuman2": [int(v) for v in vanilla_c], "cameraOffsetFromRest": offs,
           "hazeParams": {"d50": d50, "d75": d75, "d95": d95, "buildingDistP99": bmax, "farStart": far0},
           "depth": depth, "variants": {}}
    imgs = {}
    for name in ["none"] + list(HAZES):
        v = {}
        imgs[name] = {}
        for ck in POSES:
            sh = shots[ck]
            img, f = apply(sh, name)
            imgs[name][ck] = (img, f)
            ts = sh["streak"] & (sh["pid"] == 1)
            trs = ts & sh["revealed"]
            v[ck] = {"terrainStreak": int(ts.sum()), "unmaskedTerrainStreak": int(round(float((1 - f)[ts].sum()))),
                     "terrainRevStreak": int(trs.sum()),
                     "unmaskedTerrainRevStreak": int(round(float((1 - f)[trs].sum()))),
                     "allStreak": int(sh["streak"].sum()),
                     "unmaskedAllStreak": int(round(float((1 - f)[sh["streak"]].sum()))),
                     "meanFogOnBuildings": round(float(f[sh["pid"] == 3].mean()), 4) if (sh["pid"] == 3).any() else 0.0,
                     "meanFogOnNonStreakTerrain": round(float(f[(sh["pid"] == 1) & ~sh["streak"]].mean()), 4)}
        d = np.abs(imgs[name]["rest"][0].astype(np.int16) - shots["rest"]["lit"].astype(np.int16)).max(-1)
        v["restDiff"] = {"meanAbs": round(float(d.mean()), 4), "max": int(d.max()), "pxOver2": int((d > 2).sum()),
                         "pxOver8": int((d > 8).sum()), "px": int(d.size)}
        res["variants"][name] = v
        print(name, json.dumps({ck: v[ck]["unmaskedTerrainStreak"] for ck in POSES[1:]}), v["restDiff"], flush=True)
    (out / "metrics.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for name in imgs:
        for ck in POSES:
            Image.fromarray(imgs[name][ck][0]).save(out / f"{name}_{ck}.png")

    best = a.best or min((n for n in HAZES if res["variants"][n]["restDiff"]["pxOver2"] == 0),
                         key=lambda n: sum(res["variants"][n][ck]["unmaskedTerrainStreak"] for ck in POSES[1:]))
    res["best"] = best
    (out / "metrics.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("best", best)
    if not a.summary:
        return 0

    # ---------------------------------------------------------------- summary sheet (ldi_review format)
    f_lab = font(18)

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

    def col(ims, gap=8, bg=(24, 24, 24)):
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
        return (x0, y0, x0 + ZOOM[0], y0 + ZOOM[1])

    wt = 1140
    V = res["variants"]
    lines = [f"{a.faction}: {a.candidate} (left, installed, no haze) vs {a.candidate} + haze '{best}' (right) - "
             "offline moderngl preview + post-pass haze; generated artifact; not Unity, not in-game",
             f"haze '{best}': {DESC.get(best, '')}; colour = painting horizon sky {res['fogColourPaintingHorizon']}; "
             f"rest terrain dist p50/p75/p95 {d50:.0f}/{d75:.0f}/{d95:.0f}, buildings p99 {bmax:.0f}, floor y {floor_y:.1f}",
             f"rest frame |after-before|: mean {V[best]['restDiff']['meanAbs']} / max {V[best]['restDiff']['max']}; "
             f"px > 2: {V[best]['restDiff']['pxOver2']}   (static vanilla-shape fog for comparison: px > 2 "
             f"{V['vanilla_linear']['restDiff']['pxOver2']}, static far-only: {V['static_far']['restDiff']['pxOver2']})",
             "terrain streak px -> unmasked (sum 1-fog over streak px):  " + "   ".join(
                 f"{ck} {V['none'][ck]['terrainStreak']} -> {V[best][ck]['unmaskedTerrainStreak']}" for ck in POSES[1:]),
             "terrain revealed+streak -> unmasked:  " + "   ".join(
                 f"{ck} {V['none'][ck]['terrainRevStreak']} -> {V[best][ck]['unmaskedTerrainRevStreak']}" for ck in POSES[1:]),
             "mean haze on buildings / on non-streak terrain:  " + "   ".join(
                 f"{ck} {V[best][ck]['meanFogOnBuildings']:.3f}/{V[best][ck]['meanFogOnNonStreakTerrain']:.3f}"
                 for ck in POSES[1:])]
    head = Image.new("RGB", (2 * wt + 8, 16 + 32 * len(lines)), (24, 24, 24))
    d = ImageDraw.Draw(head)
    for i, ln in enumerate(lines):
        d.text((10, 8 + 32 * i), ln, fill=(255, 255, 255) if i else (255, 220, 120), font=font(24 if i == 0 else 20))
    parts = [head]
    for ck in POSES:
        b, af = imgs["none"][ck][0], imgs[best][ck][0]
        mb, ma = V["none"][ck], V[best][ck]
        parts.append(row([tile(b, f"{ck} BEFORE {a.candidate}  terrain streak {mb['terrainStreak']}", wt),
                          tile(af, f"{ck} AFTER haze {best}  unmasked streak {ma['unmaskedTerrainStreak']}"
                                   f"  rest diff px>2 {V[best]['restDiff']['pxOver2']}" if ck == "rest" else
                               f"{ck} AFTER haze {best}  unmasked terrain streak {ma['unmaskedTerrainStreak']}", wt)]))
        if ck != "rest":
            box = worst_box(shots[ck]["streak"] & shots[ck]["revealed"] & (shots[ck]["pid"] == 1))
            parts.append(row([tile(b[box[1]:box[3], box[0]:box[2]], f"{ck} zoom x{wt / ZOOM[0]:.1f} before @({box[0]},{box[1]})", wt),
                              tile(af[box[1]:box[3], box[0]:box[2]], f"{ck} zoom after haze", wt)]))
    s = col(parts)
    Path(a.summary).parent.mkdir(parents=True, exist_ok=True)
    s.save(a.summary, optimize=True)
    print("summary", a.summary, s.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
