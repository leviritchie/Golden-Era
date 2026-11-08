"""Real-time stick-figure review: native Olden Era idle | ours before | ours after.

    python tools/homm3_idle_cadence/review_sticks.py --native-prefab griffin --native-ctrl griffin_ctrl \
        --before artifacts/homm3_def_retarget/h3_griffin/h3_griffin_def_retarget.glb \
        --after artifacts/homm3_idle_cadence/pilots/h3_griffin/h3_griffin_idle_retimed.glb \
        --out artifacts/homm3_idle_cadence/pilots/h3_griffin/h3_griffin_idle_sticks.mp4 [--seconds 8]

All three panels are forward kinematics of the clip's own local bone curves, played at 1x real
time (30 fps video) and looped, each fitted to its own skeleton's bbox so body size does not
matter. The native skeleton is the prefab's Transform hierarchy (bind TRS), matched to the
clip's bindings by CRC32 of the path relative to the Animator (Unity's binding hash).
A per-panel sparkline of the pose's first principal component shows each loop's beats.
"""
from __future__ import annotations

import argparse
import os
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_anim import accessor, animation, read_glb  # noqa: E402

FPS = 30


def qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def fk(parents, trs):
    """parents: list of parent index (-1 root) in topological order; trs: list of (t, q, s)."""
    n = len(parents)
    R = [None] * n; P = [None] * n; S = [None] * n
    for i in range(n):
        t, q, s = trs[i]
        m = qmat(q) * np.asarray(s)[None, :]
        if parents[i] < 0:
            R[i], P[i] = m, np.asarray(t, float)
        else:
            p = parents[i]
            R[i] = R[p] @ m; P[i] = P[p] + R[p] @ np.asarray(t, float)
    return np.array(P)


# ------------------------------------------------------------------ native (UnityPy)
def native_track(prefab: str, ctrl: str, role: str = "22.Idle"):
    import UnityPy
    from measure_native_idles import DATA, clip_rotations, decode_streamed, eval_streamed  # noqa: F401
    env = UnityPy.load(DATA + "resources.assets")
    byid = {o.path_id: o for o in env.objects}
    anim = None
    for o in env.objects:
        if o.type.name != "Animator":
            continue
        a = o.read_typetree()
        go = byid.get(a["m_GameObject"]["m_PathID"]); c = byid.get(a["m_Controller"]["m_PathID"])
        if go is not None and c is not None and go.peek_name() == prefab and c.peek_name() == ctrl:
            anim = (go, c); break
    if anim is None:
        raise SystemExit(f"FAIL: no Animator on prefab {prefab!r} with controller {ctrl!r}")
    go, c = anim
    ctt = c.read_typetree()
    clip = None
    for cl in ctt["m_Clips"]:
        a = byid.get(cl["m_OriginalClip"]["m_PathID"])
        if a is not None and a.peek_name() == role:
            clip = byid[cl["m_OverrideClip"]["m_PathID"]]
    if clip is None:
        raise SystemExit(f"FAIL: {ctrl} has no {role} override")
    # hierarchy under the animator's GameObject
    gtt = go.read_typetree()
    tr = None
    for comp in gtt["m_Component"]:
        o = byid.get(comp["component"]["m_PathID"])
        if o is not None and o.type.name == "Transform":
            tr = o
    names, parents, bind, paths = [], [], [], []

    def walk(t_obj, parent, path):
        t = t_obj.read_typetree()
        g = byid[t["m_GameObject"]["m_PathID"]].peek_name()
        p = f"{path}/{g}" if path else g
        idx = len(names)
        names.append(g); parents.append(parent); paths.append(p)
        lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
        bind.append(([lp["x"], lp["y"], lp["z"]], [lr["x"], lr["y"], lr["z"], lr["w"]], [ls["x"], ls["y"], ls["z"]]))
        for ch in t["m_Children"]:
            walk(byid[ch["m_PathID"]], idx, p)

    root_t = tr.read_typetree()
    names.append("<root>"); parents.append(-1); paths.append(""); bind.append(([0, 0, 0], [0, 0, 0, 1], [1, 1, 1]))
    for ch in root_t["m_Children"]:
        walk(byid[ch["m_PathID"]], 0, "")
    crc = {zlib.crc32(p.encode("utf-8")) & 0xFFFFFFFF: i for i, p in enumerate(paths) if p}
    tt = clip.read_typetree()
    rots, length, rate, _, _ = clip_rotations(tt)
    # positions and scales too
    pos = _native_vec_curves(tt, attribute=1)
    scl = _native_vec_curves(tt, attribute=3)
    T = len(next(iter(rots.values())))
    mapped = sum(1 for k in rots if int(k) in crc)
    if mapped < max(3, len(rots) // 2):
        raise SystemExit(f"FAIL: only {mapped}/{len(rots)} native bindings map to the prefab hierarchy")
    frames = []
    for f in range(T):
        trs = [list(b) for b in bind]
        for k, q in rots.items():
            i = crc.get(int(k))
            if i is not None:
                trs[i][1] = q[f]
        for k, v in pos.items():
            i = crc.get(int(k))
            if i is not None:
                trs[i][0] = v[f]
        for k, v in scl.items():
            i = crc.get(int(k))
            if i is not None:
                trs[i][2] = v[f]
        frames.append(fk(parents, trs))
    animated = {crc[int(k)] for k in rots if int(k) in crc}
    keep = _bones_to_draw(parents, animated)
    return np.array(frames), parents, keep, length, rots


def _native_vec_curves(tt, attribute):
    from measure_native_idles import SAMPLE_HZ, decode_streamed, eval_streamed
    mc = tt["m_MuscleClip"]; start, stop = float(mc["m_StartTime"]), float(mc["m_StopTime"])
    data = mc["m_Clip"]["data"]; sc = data["m_StreamedClip"]; dc = data["m_DenseClip"]; cc = data["m_ConstantClip"]["data"]
    n_s = int(sc["curveCount"]); n_d = int(dc["m_CurveCount"])
    times = np.linspace(start, stop, int(round((stop - start) * SAMPLE_HZ)) + 1)
    streamed = decode_streamed(sc["data"]) if sc["data"] else {}
    dense = np.asarray(dc["m_SampleArray"], float)
    if n_d:
        dense = dense.reshape(int(dc["m_FrameCount"]), n_d)
        dt_ = float(dc["m_BeginTime"]) + np.arange(dense.shape[0]) / float(dc["m_SampleRate"])

    def curve(i):
        if i < n_s:
            k = streamed.get(i)
            return eval_streamed(k, times) if k else np.zeros(len(times))
        i -= n_s
        if i < n_d:
            return np.interp(times, dt_, dense[:, i])
        return np.full(len(times), float(cc[i - n_d]))

    out, ci = {}, 0
    for b in tt["m_ClipBindingConstant"]["genericBindings"]:
        size = (4 if b["attribute"] == 2 else 3) if b["typeID"] == 4 else 1
        if b["typeID"] == 4 and b["attribute"] == attribute:
            out[str(b["path"])] = np.stack([curve(ci + k) for k in range(3)], axis=1)
        ci += size
    return out


def _bones_to_draw(parents, animated):
    keep = set()
    for i in animated:
        j = i
        while j >= 0 and j not in keep:
            keep.add(j); j = parents[j]
    return keep


# ------------------------------------------------------------------ ours (GLB)
def glb_track(path: str, clip: str = "Unit_Idle", hz: float = 60.0):
    from glb_anim import sample_quat
    js, bn = read_glb(path)
    an = animation(js, clip)
    skin = js["skins"][0]
    joints = skin["joints"]
    nodes = js["nodes"]
    parent_of = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent_of[c] = i
    order = []
    jset = set(joints)

    def depth(i):
        d = 0
        while i in parent_of and parent_of[i] in jset:
            i = parent_of[i]; d += 1
        return d
    order = sorted(joints, key=depth)
    idx = {n: k for k, n in enumerate(order)}
    parents = [idx.get(parent_of.get(n), -1) for n in order]
    ins = [accessor(js, bn, an["samplers"][c["sampler"]]["input"])[:, 0] for c in an["channels"]]
    t0 = min(i.min() for i in ins); t1 = max(i.max() for i in ins)
    length = float(t1 - t0)
    t = np.linspace(t0, t1, int(round(length * hz)) + 1)
    base = [[np.array(nodes[n].get("translation", [0, 0, 0]), float),
             np.array(nodes[n].get("rotation", [0, 0, 0, 1]), float),
             np.array(nodes[n].get("scale", [1, 1, 1]), float)] for n in order]
    curves = {}
    for c in an["channels"]:
        n = c["target"]["node"]
        if n not in idx or c["target"]["path"] not in ("translation", "rotation", "scale"):
            continue
        s = an["samplers"][c["sampler"]]
        times = accessor(js, bn, s["input"])[:, 0]; vals = accessor(js, bn, s["output"])
        interp = s.get("interpolation", "LINEAR")
        if c["target"]["path"] == "rotation":
            v = sample_quat(times, vals, t, interp)
        else:
            v = np.stack([np.interp(t, times, vals[:, k]) for k in range(3)], axis=1)
        curves[(idx[n], c["target"]["path"])] = v
    slot = {"translation": 0, "rotation": 1, "scale": 2}
    frames = []
    for f in range(len(t)):
        trs = [list(b) for b in base]
        for (i, p), v in curves.items():
            trs[i][slot[p]] = v[f]
        frames.append(fk(parents, trs))
    rots = {str(i): v for (i, p), v in curves.items() if p == "rotation"}
    return np.array(frames), parents, set(range(len(order))), length, rots


# ------------------------------------------------------------------ render
def pc1(rots, length):
    from idle_metrics import _align_signs, _normalize
    X = np.concatenate([_align_signs(_normalize(q)) - _align_signs(_normalize(q)).mean(0) for q in rots.values()], axis=1)
    u, s, _ = np.linalg.svd(X - X.mean(0), full_matrices=False)
    sig = u[:, 0] * s[0]
    return -sig if sig[0] > 0 else sig        # PCA sign is arbitrary; start every trace low


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native-prefab", required=True)
    ap.add_argument("--native-ctrl", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--title", default="")
    args = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter

    tracks = [("native OE " + args.native_ctrl, *native_track(args.native_prefab, args.native_ctrl)),
              ("ours before (DEF 12 fps)", *glb_track(args.before)),
              ("ours after (x3.2, eased)", *glb_track(args.after))]
    fig, axes = plt.subplots(2, 3, figsize=(12, 5.6), gridspec_kw={"height_ratios": [4, 1]})
    fig.patch.set_facecolor("white")
    draws = []
    for col, (label, frames, parents, keep, length, rots) in enumerate(tracks):
        ax = axes[0, col]
        # view: x (right) vs y (up), unit-agnostic fit
        P = frames[:, sorted(keep)]
        lo = P.reshape(-1, 3).min(0); hi = P.reshape(-1, 3).max(0)
        c = (lo + hi) / 2; r = max(hi[0] - lo[0], hi[1] - lo[1]) * 0.6 + 1e-6
        ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"{label}\nloop {length:.2f} s", fontsize=9)
        segs = [(i, parents[i]) for i in sorted(keep) if parents[i] >= 0 and parents[i] in keep]
        lines = [ax.plot([], [], "-", color="#2a6fdb" if col == 0 else ("#c0392b" if col == 1 else "#1e8449"), lw=1.6)[0] for _ in segs]
        sig = pc1(rots, length)
        tt = np.linspace(0, length, len(sig) + 1)[:-1]
        bx = axes[1, col]
        bx.plot(tt, sig, color="#555", lw=1); bx.set_xlim(0, max(tr[4] for tr in tracks))
        bx.set_yticks([]); bx.set_xlabel("s (pose PC1 over one loop)", fontsize=8)
        cursor = bx.axvline(0, color="k", lw=1)
        draws.append((frames, segs, lines, length, cursor))
    fig.suptitle(args.title or "idle cadence review - 1x real time", fontsize=11)
    fig.tight_layout()
    n = int(args.seconds * FPS)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    writer = FFMpegWriter(fps=FPS, codec="libx264", extra_args=["-pix_fmt", "yuv420p"])
    with writer.saving(fig, args.out, dpi=100):
        for k in range(n):
            tsec = k / FPS
            for frames, segs, lines, length, cursor in draws:
                ph = (tsec % length) / length
                f = min(int(round(ph * (len(frames) - 1))), len(frames) - 1)
                P = frames[f]
                for (i, p), ln in zip(segs, lines):
                    ln.set_data([P[p][0], P[i][0]], [P[p][1], P[i][1]])
                cursor.set_xdata([tsec % length])
            writer.grab_frame()
    print("WROTE", args.out)


if __name__ == "__main__":
    main()
