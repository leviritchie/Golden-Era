"""Retime a clip's capture onto the DEF's silhouette-height curve (monotone time warp), before any refine.

Why: the capture of a Stronghold death often collapses a few frames before the DEF does (the berserker is on the
ground while its DEF frame still stands mid-hop). A per-frame screen shift then "fixes" the silhouette by lifting
the fallen body into the air (pose-follow trial A, 2026-09-27: dy up to +53 px, bodies floating). The capture's
poses are right; their timing is not. This hook re-times the clip instead: DEF frame t gets the capture pose at
clip time s(t), where s is monotone, starts at the first frame and ends at the last, and is chosen by dynamic
programming so the skinned mesh's silhouette height under the sprite camera follows the DEF's (both measured from
their own Idle frame 0 ground line and normalised by their own Idle frame 0 height). Poses at fractional s are
interpolated bone by bone (Matrix.lerp: polar decomposition, location/rotation/scale).

Config (unit json), listed in "extensions" before any before_keys refine (castle_refine):
  "deathRetime": {"clips": ["Death"], "sub": 4, "rate": 0.02, "minRate": 0.5, "maxRate": 2.0}
    clips    contract suffixes to retime (each clip's longest segment)
    sub      fractional steps per source frame on the time grid
    rate     cost per source frame of deviation from the natural rate (1 source frame per DEF frame)
    minRate / maxRate  hard bounds on source frames advanced per DEF frame. Without them the fit held the first
             pose for 4-5 frames while the DEF hopped, then collapsed in one (trial B, 2026-09-27: better IoU,
             a freeze-then-pop on the render sheet). minRate > 0 keeps the body moving every frame.
Height uses the opaque DEF pixels (alpha > 0.99, shadow excluded) and the mesh vertices; only the top of the
silhouette is compared (a ground line is fixed per side), so a hop and a collapse both register.
Writes <out>.death_retime.json (per frame: source time, DEF and mesh heights before/after).
Runs in before_keys: every world pose is final except the refines listed after it.
Status (2026-09-27): MEASURED NEGATIVE, enabled on no unit. Pose-follow trials (goblin, orc berserker, ogre; Death,
with castle_refine |dy| <= 8, refine_roll_limit 5 deg, refine_carry) against the plain build:
  - unbounded warp (trial B/BA): Death IoU 0.34/0.19/0.33 -> 0.42/0.44/0.47 and the ratio-to-idle gate passed, but the
    render sheet showed the first pose held 4-5 frames then a one-frame collapse (freeze-then-pop; the freeze gate
    in flyer_articulation.freeze_check now fails it);
  - rate bounded to 0.5..2 (BA2): no held frames, but the mesh still stands while the DEF has crumpled and catches
    up late (goblin pops between frames 5 and 6; berserker ratio 0.48 < 0.6, Hips translation >4 Hz 0.37).
The capture's fall is a different motion from the DEF's hop-and-crumple; re-timing it cannot make it follow.
Kept for a future pose source that does follow the DEF; do not enable it for IoU alone.
Proof tier: generated artifact.
"""
import json
import numpy as np


def before_keys(g):
    R = g["cfg"].get("deathRetime")
    if not R:
        return
    bpy = g["bpy"]
    body, rest, posed_world = g["body"], g["rest"], g["posed_world"]
    ms = json.load(open(g["MASTER"]))
    U_ = np.array(g["up"]); s_px, oy = g["s_px"], g["oy"]
    names = list(posed_world[0].keys())
    col = {n: i for i, n in enumerate(names)}
    V0 = np.array([v.co[:] for v in body.data.vertices]); Vh = np.c_[V0, np.ones(len(V0))]
    gname = {gr.index: gr.name for gr in body.vertex_groups}
    Wm = np.zeros((len(V0), len(names)))
    for v in body.data.vertices:
        for gr in v.groups:
            n = gname[gr.group]
            if n in col:
                Wm[v.index, col[n]] += gr.weight
    sw = Wm.sum(1)
    keep = sw > 1e-6                                   # vertices on no posed bone take no part in the height
    Wm = Wm[keep] / sw[keep, None]; Vh = Vh[keep]
    restinv = {n: np.array(rest[n].inverted()) for n in names}

    def top_px(A):
        out = np.zeros((len(Vh), 3))
        for n, i in col.items():
            w = Wm[:, i]
            if w.max() <= 0:
                continue
            out += w[:, None] * (Vh @ (np.array(A[n]) @ restinv[n]).T)[:, :3]
        y = oy - s_px * (out @ U_)
        return float(y.min()), float(y.max())

    def def_rows(path):
        img = bpy.data.images.load(path, check_existing=True)
        a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 0.99
        bpy.data.images.remove(img)
        r = np.nonzero(a.any(1))[0]
        return float(r.min()), float(r.max())

    idle = next(sg for sg in ms["segments"] if sg["contractSuffix"] == "Idle")
    t_idle = idle["globalStart"]
    d_top0, d_gnd = def_rows(ms["frames"][t_idle]["sourcePng"])
    m_top0, m_gnd = top_px(posed_world[t_idle])
    d_h0, m_h0 = d_gnd - d_top0, m_gnd - m_top0
    sub = int(R.get("sub", 4)); lam = float(R.get("rate", 0.02))
    lo_r, hi_r = float(R.get("minRate", 0.5)), float(R.get("maxRate", 2.0))
    if not (0.0 < lo_r <= 1.0 <= hi_r):
        raise SystemExit(f"deathRetime: need 0 < minRate <= 1 <= maxRate, got {lo_r} / {hi_r}")
    lo_k, hi_k = int(np.ceil(lo_r * sub - 1e-9)), int(np.floor(hi_r * sub + 1e-9))
    log = {"idle": {"defHeightPx": d_h0, "meshHeightPx": m_h0}, "clips": {}}
    for clip in R.get("clips", ["Death"]):
        segs = [sg for sg in ms["segments"] if sg["contractSuffix"] == clip]
        if not segs:
            raise SystemExit(f"deathRetime: no {clip} segment in the master sequence")
        sg = max(segs, key=lambda s: s["frameCount"])
        ts = list(range(sg["globalStart"], sg["globalEnd"]))
        n = len(ts)
        if n < 3:
            continue
        src = [dict(posed_world[t]) for t in ts]

        def pose_at(s):
            k = min(int(np.floor(s)), n - 2); f = s - k
            if f <= 1e-9:
                return dict(src[k])
            return {b: src[k][b].lerp(src[k + 1][b], f) for b in names}

        grid = np.arange((n - 1) * sub + 1) / sub
        hm = np.array([(m_gnd - top_px(pose_at(s))[0]) / m_h0 for s in grid])
        hd = np.array([(d_gnd - def_rows(ms["frames"][t]["sourcePng"])[0]) / d_h0 for t in ts])
        m = len(grid)
        INF = 1e18
        cost = np.full((n, m), INF); back = np.zeros((n, m), int)
        cost[0, 0] = abs(hd[0] - hm[0])
        for i in range(1, n):
            for j in range(m):
                best, arg = INF, 0
                for jp in range(max(0, j - hi_k), j - lo_k + 1):    # bounded rate: never holds, never leaps
                    c = cost[i - 1, jp]
                    if c >= INF:
                        continue
                    c += lam * abs((j - jp) / sub - 1.0)
                    if c < best:
                        best, arg = c, jp
                cost[i, j] = best + abs(hd[i] - hm[j]); back[i, j] = arg
        j = m - 1; path = [j]
        for i in range(n - 1, 0, -1):
            j = back[i, j]; path.append(j)
        path = path[::-1]
        s_of = [float(grid[j]) for j in path]
        for t, s in zip(ts, s_of):
            posed_world[t].clear(); posed_world[t].update(pose_at(s))
        if cost[n - 1, m - 1] >= INF:
            raise SystemExit(f"deathRetime: no warp of {clip} within rate {lo_r}..{hi_r}")
        log["clips"][clip] = {"frames": ts, "rate": [lo_r, hi_r], "sourceTime": s_of, "defHeight": [round(float(x), 3) for x in hd],
                              "meshHeightBefore": [round(float(hm[i * sub]), 3) for i in range(n)],
                              "meshHeightAfter": [round(float(hm[j]), 3) for j in path],
                              "meanAbsBefore": round(float(np.mean([abs(hd[i] - hm[i * sub]) for i in range(n)])), 4),
                              "meanAbsAfter": round(float(np.mean([abs(hd[i] - hm[path[i]]) for i in range(n)])), 4)}
        print("DEATH_RETIME", clip, "source time", [round(x, 2) for x in s_of],
              "height error", log["clips"][clip]["meanAbsBefore"], "->", log["clips"][clip]["meanAbsAfter"])
    json.dump(log, open(g["OUT"] + ".death_retime.json", "w"), indent=0)
