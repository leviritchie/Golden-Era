"""Articulation audit: does a clip move the unit's limbs/wings, or just bounce a rigid body?

Usage: python tools/homm3_def_retarget/articulation.py [unit ...] [--json out.json]
       (default: every artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb)

Pure Python (numpy). Reads the exported GLB and skins the mesh itself at every key time of each
Unit_* clip. Vertices are grouped by their dominant bone into regions:
  torso (Hips/Spine*), head (Neck/Head), arms (Shoulder/Arm/ForeArm/Hand), legs (UpLeg/Leg/Foot/Toe),
  wings (*Wing*), extra (anything else: tails, hook-added chains, props).
Arms, legs and wings are split per side so a rigid fit does not average left and right away.
Per clip:
  bodyRot / bodyMove  the torso's rigid rotation (deg) and travel (fraction of the unit's size)
                      relative to the clip's first frame: the "held toy" motion;
  <region>            the largest swing (deg) of that region relative to the torso: a rigid fit of the
                      region, in the torso's frame, against frame 0 (0 = it just rides along);
  flapCycles          wings: direction reversals / 2 of the wing's elevation about the torso
                      (Move/Idle include the wrap back to frame 0);
  toy                 body moves (bodyRot >= 8 or bodyMove >= 0.03) while no limb region swings
                      >= 10 deg and wings (if any) swing < 15 deg;
  wingStill           the wings swing < 15 deg relative to the torso;
  wingFold            articulated wings (chains named *Wing*_NN): the largest rotation of the outermost
                      chain bone's region relative to the innermost one (0 = the wing never folds);
                      absent for one-bone wings, which cannot fold;
  rigidShare          share of the clip's vertex motion, after removing the centroid's travel, that
                      one rotation of the whole mesh explains (1.0 = a toy tilted by hand);
  nonRigid            RMS vertex motion left after that rigid fit, as a fraction of the unit's size.
silhouette (per DEF clip key): frame-to-frame silhouette change of the DEF vs the build's
  sprite-camera renders (renders/sprite_NNN.png) and their ratio; see silhouette_motion().
Thresholds are a first pass; the numbers are the evidence, the flags are a triage.
"""
import json, os, re, struct, sys
import numpy as np

ROOT = r"V:/games/Olden Era Playtest Tweak"
ART = os.path.join(ROOT, "artifacts/homm3_def_retarget")
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
LIMBS = ("head", "arms", "legs", "wings", "extra")


def load(path):
    b = open(path, "rb").read()
    jl = struct.unpack_from("<I", b, 12)[0]
    g = json.loads(b[20:20 + jl])
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    bin_ = b[28 + jl:28 + jl + bl]

    def acc(i):
        a = g["accessors"][i]; bv = g["bufferViews"][a["bufferView"]]
        dt = np.dtype(CT[a["componentType"]]); n = NC[a["type"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or dt.itemsize * n
        rows = [np.frombuffer(bin_, dtype=dt, count=n, offset=off + k * stride) for k in range(a["count"])] \
            if stride != dt.itemsize * n else None
        out = np.stack(rows) if rows is not None else \
            np.frombuffer(bin_, dtype=dt, count=n * a["count"], offset=off).reshape(a["count"], n)
        if a.get("normalized"):
            out = out.astype(np.float32) / np.iinfo(dt).max
        return out
    return g, acc


def qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs(t, r, s):
    M = np.eye(4); M[:3, :3] = qmat(r) * np.asarray(s)[None, :]; M[:3, 3] = t
    return M


def kabsch(A, B):
    """rotation R, translation t minimising |R A + t - B| (rows are points)."""
    ca, cb = A.mean(0), B.mean(0)
    U, S, Vt = np.linalg.svd((A - ca).T @ (B - cb))
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R, cb - R @ ca


def angle(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def region_of(name):
    n = name.lower()
    if "wing" in n: return "wings"
    if n == "hips" or n.startswith("spine"): return "torso"
    if n.startswith("neck") or n.startswith("head"): return "head"
    if "upleg" in n or "toebase" in n or "foot" in n or n.endswith("leg"): return "legs"
    if "shoulder" in n or "forearm" in n or "hand" in n or n.endswith("arm"): return "arms"
    if n == "root": return "root"
    return "extra"


def side_of(name):
    n = name.lower()
    if "left" in n or re.search(r"(^|[_.])l([_.0-9]|$)|wing[a-z]?l([_.0-9]|$)", n): return "L"
    if "right" in n or re.search(r"(^|[_.])r([_.0-9]|$)|wing[a-z]?r([_.0-9]|$)", n): return "R"
    return "C"


def audit(path, keep=None):
    """keep: optional dict; filled with {clip: (frames, region per vertex)} for drawing."""
    g, acc = load(path)
    nodes = g["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    nverts = lambda i: sum(g["accessors"][p["attributes"]["POSITION"]]["count"] for p in g["meshes"][nodes[i]["mesh"]]["primitives"])
    mi = max((i for i, n in enumerate(nodes) if "skin" in n and "mesh" in n and "rubble" not in n.get("name", "").lower()), key=nverts)
    skin = g["skins"][nodes[mi]["skin"]]; joints = skin["joints"]
    ibm = acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(float)
    P, J, W = [], [], []
    for p in g["meshes"][nodes[mi]["mesh"]]["primitives"]:
        a = p["attributes"]
        P.append(acc(a["POSITION"])); J.append(acc(a["JOINTS_0"]).astype(int)); W.append(acc(a["WEIGHTS_0"]).astype(float))
    P, J, W = np.concatenate(P).astype(float), np.concatenate(J), np.concatenate(W)
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    Ph = np.c_[P, np.ones(len(P))]
    jnames = [nodes[j].get("name", str(j)) for j in joints]
    dom = J[np.arange(len(J)), W.argmax(1)]
    reg = np.array([region_of(jnames[d]) for d in dom])
    sid = np.array([side_of(jnames[d]) for d in dom])
    rest = {i: (np.array(n.get("translation", [0, 0, 0]), float), np.array(n.get("rotation", [0, 0, 0, 1]), float),
                np.array(n.get("scale", [1, 1, 1]), float)) for i, n in enumerate(nodes)}
    order = []
    stack = [i for i in range(len(nodes)) if i not in parent][::-1]
    while stack:
        i = stack.pop(); order.append(i); stack += nodes[i].get("children", [])[::-1]
    tor = reg == "torso"
    if tor.sum() < 10:
        tor = np.ones(len(P), bool)
    groups = {}
    for r in LIMBS:
        for sd in "LRC":
            idx = np.where((reg == r) & ((sid == sd) if r in ("arms", "legs", "wings") else True))[0]
            if r not in ("arms", "legs", "wings") and sd != "C":
                continue
            if len(idx) >= 20:
                groups[(r, sd)] = idx

    # wing chains: innermost and outermost bone region per side, for the fold measure
    fold_groups = {}
    for sd in "LR":
        idxs = {}
        for d in np.unique(dom):
            m = re.search(r"wing.*_(\d+)$", jnames[d].lower())
            if m and side_of(jnames[d]) == sd:
                idxs[int(m.group(1))] = np.where(dom == d)[0]
        if len(idxs) >= 2 and min(len(idxs[min(idxs)]), len(idxs[max(idxs)])) >= 20:
            fold_groups[sd] = (idxs[min(idxs)], idxs[max(idxs)])
    out = {}
    for an in g["animations"]:
        name = an["name"]
        if not name.startswith("Unit_"):
            continue
        chans, times = [], set()
        for ch in an["channels"]:
            pth = ch["target"]["path"]
            if pth == "weights" or "node" not in ch["target"]:
                continue
            s = an["samplers"][ch["sampler"]]
            ti = acc(s["input"])[:, 0].astype(float); vo = acc(s["output"]).astype(float)
            chans.append((ch["target"]["node"], {"translation": 0, "rotation": 1, "scale": 2}[pth], ti, vo, s.get("interpolation", "LINEAR")))
            times.update(np.round(ti, 5).tolist())
        times = sorted(times)
        if len(times) < 2:
            out[name[5:]] = {"frames": len(times)}
            continue
        frames = []
        for t in times:
            cur = {i: list(v) for i, v in rest.items()}
            for node, k3, ti, vo, interp in chans:
                k = int(np.searchsorted(ti, t + 1e-6, side="right")) - 1
                if k < 0:
                    v = vo[0]
                elif k >= len(ti) - 1 or interp == "STEP":
                    v = vo[min(k, len(vo) - 1)]
                else:
                    u = (t - ti[k]) / max(ti[k + 1] - ti[k], 1e-9); a0, a1 = vo[k], vo[k + 1]
                    if k3 == 1 and np.dot(a0, a1) < 0:
                        a1 = -a1
                    v = a0 * (1 - u) + a1 * u
                    if k3 == 1:
                        v = v / np.linalg.norm(v)
                cur[node][k3] = v
            G = {}
            for i in order:
                L = trs(*cur[i]); G[i] = G[parent[i]] @ L if i in parent else L
            M = np.stack([G[j] @ ibm[k] for k, j in enumerate(joints)])
            V = np.zeros((len(P), 3))
            for c in range(J.shape[1]):
                V += W[:, c:c + 1] * np.einsum("nij,nj->ni", M[J[:, c]], Ph)[:, :3]
            frames.append(V)
        V0 = frames[0]
        if keep is not None:
            keep[name[5:]] = (frames, reg)
        size = max(float(np.ptp(V0, axis=0).max()), 1e-6)
        rec = {"frames": len(times), "bodyRot": 0.0, "bodyMove": 0.0}
        tot2 = res2 = 0.0
        sw = {r: 0.0 for r, _ in groups}
        elev = {sd: [] for sd in "LR"}
        fold = 0.0
        for V in frames:
            Rg, tg = kabsch(V0, V)             # whole mesh as one rigid body
            tot2 += float(((V - V.mean(0) - V0 + V0.mean(0)) ** 2).sum()); res2 += float(((V0 @ Rg.T + tg - V) ** 2).sum())
            R, t = kabsch(V0[tor], V[tor])
            rec["bodyRot"] = max(rec["bodyRot"], angle(R))
            rec["bodyMove"] = max(rec["bodyMove"], float(np.linalg.norm(V[tor].mean(0) - V0[tor].mean(0))) / size)
            Vt = (V - t) @ R                    # undo the torso's rigid motion
            for inner, outer in fold_groups.values():
                Ri, _ = kabsch(V0[inner], V[inner]); Ro, _ = kabsch(V0[outer], V[outer])
                fold = max(fold, angle(Ri.T @ Ro))
            for (r, sd), idx in groups.items():
                Rr, _ = kabsch(V0[idx], Vt[idx])
                sw[r] = max(sw[r], angle(Rr))
                if r == "wings" and sd in "LR":
                    c = Vt[idx].mean(0) - Vt[tor].mean(0)
                    elev[sd].append(float(np.degrees(np.arctan2(c[1], np.hypot(c[0], c[2])))))
        rec["bodyRot"] = round(rec["bodyRot"], 1); rec["bodyMove"] = round(rec["bodyMove"], 3)
        # share of the clip's vertex motion that one rigid transform of the whole mesh explains
        rec["rigidShare"] = round(1 - res2 / tot2, 3) if tot2 > 1e-12 else None
        rec["nonRigid"] = round(float(np.sqrt(res2 / (len(frames) * len(P)))) / size, 4)
        rec.update({k: round(v, 1) for k, v in sw.items()})
        if fold_groups:
            rec["wingFold"] = round(fold, 1)
        if any(elev.values()):
            cyc = []
            for a in elev.values():
                d = np.diff(a + a[:1] if name[5:] in ("Move", "Idle") else a)     # loops: count the wrap too; d = d[np.abs(d) > 1.0]
                cyc.append(int((np.sign(d[1:]) != np.sign(d[:-1])).sum()) / 2 if len(d) > 1 else 0)
            rec["flapCycles"] = max(cyc)
        moving = rec["bodyRot"] >= 8 or rec["bodyMove"] >= 0.03
        limb = max([v for k, v in sw.items() if k != "wings"] + [0.0])
        wing = sw.get("wings")
        rec["toy"] = bool(moving and limb < 10 and (wing is None or wing < 15))
        if wing is not None:
            rec["wingStill"] = bool(wing < 15)
        out[name[5:]] = rec
    return {"regions": {r: int((reg == r).sum()) for r in sorted(set(reg.tolist()))}, "clips": out}


def silhouette_motion(unit):
    """Frame-to-frame silhouette change, DEF vs the sprite-camera renders of the build, per clip.

    Each consecutive pair (and the wrap pair for looping clips) is centroid-aligned, so sliding
    across the screen does not count; the pixels that differ are divided by the mean silhouette
    area. `ratio` = mesh / DEF: well below 1 means the DEF changes shape (wing beats, strides)
    and the mesh does not."""
    from PIL import Image
    O = os.path.join(ART, unit)
    fj = json.load(open(os.path.join(O, f"{unit}_def_retarget.blend.frames.json")))
    loops = set(fj.get("loops") or ["g00_move", "g02_idle"])

    def mask(p, thr):
        a = np.asarray(Image.open(p).convert("RGBA"))[..., 3]
        return a >= thr

    def energy(ms, loop):
        pairs = list(zip(ms, ms[1:])) + ([(ms[-1], ms[0])] if loop and len(ms) > 2 else [])
        e = []
        for A, B in pairs:
            ya, xa = np.nonzero(A); yb, xb = np.nonzero(B)
            if len(ya) == 0 or len(yb) == 0:
                continue
            dy, dx = int(round(ya.mean() - yb.mean())), int(round(xa.mean() - xb.mean()))
            Bs = np.roll(np.roll(B, dy, 0), dx, 1)
            e.append((A ^ Bs).sum() / ((A.sum() + B.sum()) / 2))
        return float(np.mean(e)) if e else 0.0
    seg = {}
    for k, a, b in fj["segments"]:
        if k not in seg or b - a > seg[k][1] - seg[k][0]:
            seg[k] = (a, b)
    out = {}
    for k, (a, b) in seg.items():
        if b - a < 2:
            continue
        d = energy([mask(fj["sources"][t], 255) for t in range(a, b)], k in loops)
        m = energy([mask(os.path.join(O, "renders", f"sprite_{t + 1:03d}.png"), 129) for t in range(a, b)], k in loops)
        out[k] = {"def": round(d, 3), "mesh": round(m, 3), "ratio": round(m / d, 2) if d > 1e-3 else None}
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    jo = None
    if "--json" in args:
        i = args.index("--json"); jo = args[i + 1]; args = args[:i] + args[i + 2:]
    units = args or sorted(d for d in os.listdir(ART) if os.path.exists(os.path.join(ART, d, f"{d}_def_retarget.glb")))
    res = {}
    for u in units:
        try:
            res[u] = audit(os.path.join(ART, u, f"{u}_def_retarget.glb"))
            res[u]["silhouette"] = silhouette_motion(u)
        except Exception as e:
            res[u] = {"error": repr(e)}
            print(u, "ERROR", repr(e), flush=True)
            continue
        print(u, res[u]["regions"], flush=True)
        for c, r in res[u]["clips"].items():
            print(f"   {c:12s} {r}")
    if jo:
        json.dump(res, open(jo, "w"), indent=1)
