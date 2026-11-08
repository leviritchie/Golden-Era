"""Animation emphasis pass for DEF-retarget units: find under-emphasised action keys, exaggerate them.

Contract and proof tier: docs/homm3_def_retarget_emphasis.md (generated artifact; not in game).
Delivered per unit by deliver.py; validated by tools/validate_homm3_def_retarget_emphasis_contract.py.

This module is imported both by system Python (detection: needs PIL and the unit-look masks) and by
Blender's Python (planning: numpy only), so PIL and the unit-look lane are imported lazily.

DETECTION (silhouette space, the only space the DEF and the fit share):
  For each action clip segment [a, b) (clip keys matching cfg "clips", never a loop clip) the
  neutral frame is its first frame a. For the DEF body mask and for the fit's sprite-camera render:
    area(t)  = |M_t xor M_a| / |M_a|
    reach(t) = per bbox edge (left/right/top/bottom), outward shift of that edge since frame a,
               as a fraction of the neutral bbox height
  The DEF mask is the unit-look lane's own segmentation: masks.body_mask (opaque, non-shadow) minus
  every defFlipbook layer's effectMask for the DEF (group, frame) that layer lists
  (tools/homm3_unit_look/look.py build_ctx, `bodyNoFx`) -- baked lightning/breath/bolts are not body.
  Keys are the DEF's own extremes: local maxima of area_DEF >= minDefExcursion and of each edge's
  reach_DEF >= minDefReach, merged within one frame, at most maxKeysPerClip (largest DEF change first).
  Ratio at a key: r = reach_fit / reach_DEF on the edge the DEF reaches out furthest (area ratio when
  the DEF reach is < minDefReach).  minRatio < r < flagRatio -> underEmphasised (exaggerated);
  r <= minRatio -> missed (a retarget fault, reported, never scaled); r >= flagRatio -> ok.

EXAGGERATION (per selected bone j, per frame t of a clip with >= 1 underEmphasised key):
  r_j(t) = log(M_j(t) M_j(a)^-1)          armature-space swing since the clip's neutral
  g_k    = min(maxGain, 1 + strength (1/r_k - 1));  G(t) = 1 + max_k (g_k - 1) w_k(t), w_k rising
           0 -> 1 from a to k and falling to 0 at the clip's last frame (Death holds 1 after its key)
  r'_j   = r_j (1 + (G - 1) boneWeight_j)
         - anticipation r'_j(k) bump(a, k - anticipationFrames, k)      (no other key just before)
         + followThrough ((1 + overshoot) r'_j(k) - r'_j(t)) bump(k, k + 1, k + 1 + followFrames)
  |r'_j - r_j| <= maxExtraDeg,  |r'_j| <= 170 deg;  M'_j = exp(r'_j) M_j(a), converted back to a
  local key against the parent's new rotation; unselected bones keep their local keys.
  Never changed: Hips, legs (and anything not matching cfg "bones"); an arm chain whose hand comes
  within contactBand of the ground in the clip (a quadruped's front leg) and every ancestor of it
  (the spine it hangs from), so a planted hand stays planted; every ancestor of a leg bone (rigs
  whose legs hang below a spine bone); the clip's first frame;
  a non-Death clip's last frame; frames whose body is hidden (Hips scale < 0.9).
"""
import hashlib, json, math, os, re, sys
import numpy as np

VERSION = "homm3_def_retarget_emphasis.v1"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = f"{ROOT}/artifacts/homm3_def_retarget"
OUT = f"{ROOT}/artifacts/homm3_def_retarget_emphasis"
UNITS = f"{HERE}/units"
EXCEPTIONS = f"{HERE}/exceptions.json"

DEFAULTS = {
    "clips": r"attack|shoot|hitted|defence|death|cast",        # regex over DEF clip keys
    "bones": r"^(Spine|Spine1|Spine2|Neck|Head|(Left|Right)(Shoulder|Arm|ForeArm|Hand))$",
    "boneWeights": {"Spine": 0.5, "Spine1": 0.6, "Spine2": 0.7, "Neck": 0.6, "Head": 0.6,
                    "LeftShoulder": 0.8, "RightShoulder": 0.8},
    "minDefExcursion": 0.06, "minDefReach": 0.03,
    "flagRatio": 0.8, "minRatio": 0.15,
    "strength": 0.5, "maxGain": 1.35, "maxExtraDeg": 18.0, "minKeyDeg": 3.0,
    "anticipation": 0.12, "anticipationFrames": 2,
    "followThrough": 0.3, "overshoot": 0.05, "followFrames": 2,
    "maxKeysPerClip": 3, "contactBand": 0.12,
}
UNIT_KEYS = set(DEFAULTS) | {"_note", "onlyClips", "skipClips"}
HIDDEN_SCALE = 0.9


def load_cfg(unit):
    cfg = json.loads(json.dumps(DEFAULTS))
    p = f"{UNITS}/{unit}.json"
    if os.path.exists(p):
        u = json.load(open(p))
        bad = set(u) - UNIT_KEYS
        if bad:
            raise ValueError(f"{p}: unknown keys {sorted(bad)}")
        bw = dict(cfg["boneWeights"]); bw.update(u.get("boneWeights", {}))
        cfg.update(u); cfg["boneWeights"] = bw
    cfg.pop("_note", None)
    return cfg


def params_sha(cfg):
    return hashlib.sha256(json.dumps({"version": VERSION, "cfg": cfg}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 22), b""):
            h.update(ch)
    return h.hexdigest()


# ------------------------------------------------------------------ quaternion helpers (w, x, y, z)
def qmul(a, b):
    w1, x1, y1, z1 = np.moveaxis(a, -1, 0); w2, x2, y2, z2 = np.moveaxis(b, -1, 0)
    return np.stack([w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
                     w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2], -1)


def qinv(q):
    return q * np.array([1, -1, -1, -1]) / np.sum(q * q, -1, keepdims=True)


def qlog(q):
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    q = np.where(q[..., :1] < 0, -q, q)
    v = q[..., 1:]; s = np.linalg.norm(v, axis=-1, keepdims=True)
    ang = 2 * np.arctan2(s, q[..., :1])
    return np.where(s > 1e-12, v / np.maximum(s, 1e-12) * ang, 2 * v)


def qexp(r):
    ang = np.linalg.norm(r, axis=-1, keepdims=True)
    ax = np.where(ang > 1e-12, r / np.maximum(ang, 1e-12), 0)
    return np.concatenate([np.cos(ang / 2), ax * np.sin(ang / 2)], -1)


def qangle_deg(a, b):
    """Angle between rotations a and b (degrees), sign-agnostic."""
    d = np.abs(np.sum(a * b, -1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1)))
    return np.degrees(2 * np.arccos(np.clip(d, 0, 1)))


# ------------------------------------------------------------------ armature-space rotations
class Skeleton:
    """World (armature-space) rotations from local keys: M_j = M_parent (rest_p^-1 rest_j) q_j,
    q_j = identity for bones without rotation keys."""

    def __init__(self, keys):
        self.names = [str(n) for n in keys["names"]]
        self.alln = [str(n) for n in keys["allNames"]]
        self.par = dict(zip(self.alln, [str(p) for p in keys["allParent"]]))
        self.restq = {n: keys["restQ"][i] for i, n in enumerate(self.alln)}
        self.rel = {n: (qmul(qinv(self.restq[self.par[n]]), self.restq[n]) if self.par[n] else self.restq[n]) for n in self.alln}
        self.col = {n: j for j, n in enumerate(self.names)}
        self.order = []
        seen = set()

        def visit(n):
            if n in seen:
                return
            seen.add(n)
            if self.par[n]:
                visit(self.par[n])
            self.order.append(n)
        for n in self.alln:
            visit(n)

    def forward(self, Q):
        """(T, B_keyed, 4) local keys -> {bone: (T, 4) world rotation} for every bone."""
        T = Q.shape[0]; I = np.broadcast_to(np.array([1.0, 0, 0, 0]), (T, 4)); M = {}
        for n in self.order:
            p = self.par[n]
            base = qmul(M[p], np.broadcast_to(self.rel[n], (T, 4))) if p else np.broadcast_to(self.rel[n], (T, 4))
            M[n] = qmul(base, Q[:, self.col[n]]) if n in self.col else qmul(base, I)
        return M

    def locals_from(self, Q, tgt, a, b):
        """Replace frames a..b-1 of the keyed bones in `tgt` ({bone: (n, 4) world rotation}) and
        return new local keys; every other bone keeps its local key."""
        Q2 = Q.copy(); n = b - a; M = {}
        I = np.broadcast_to(np.array([1.0, 0, 0, 0]), (n, 4))
        for x in self.order:
            p = self.par[x]
            base = qmul(M[p], np.broadcast_to(self.rel[x], (n, 4))) if p else np.broadcast_to(self.rel[x], (n, 4))
            if x in tgt:
                Q2[a:b, self.col[x]] = qmul(qinv(base), tgt[x]); M[x] = tgt[x]
            else:
                M[x] = qmul(base, Q[a:b, self.col[x]] if x in self.col else I)
        return Q2


# ------------------------------------------------------------------ DEF / render silhouettes
def _look():
    sys.path.insert(0, f"{ROOT}/tools/homm3_unit_look")
    import masks as mk          # noqa: WPS433  (the unit-look lane's segmentation, reused as is)
    return mk


def fx_layers(unit):
    """The unit-look spec's defFlipbook layers: [(effectMask, def name, {(group, frame)})]."""
    p = f"{ROOT}/tools/homm3_unit_look/units/{unit}.json"
    if not os.path.exists(p):
        return []
    spec = json.load(open(p, encoding="utf-8"))
    out = []
    for ly in spec.get("vfx", {}).get("layers", []):
        if ly.get("type") == "defFlipbook":
            gf = {(int(c["defGroup"]), int(x)) for c in ly["clips"].values() for x in c["frames"]}
            out.append((ly["effectMask"], ly.get("def"), gf))
    return out


def def_body(unit, src, layers, dname):
    """bodyNoFx for one DEF frame, exactly as look.py build_ctx computes it."""
    mk = _look()
    rgba = mk.load_rgba(src)
    body = mk.body_mask(rgba)
    g, f = (int(x) for x in os.path.basename(src).split(".")[0].split("_")[:2])
    fx = np.zeros_like(body)
    for em, dn, gf in layers:
        if (g, f) in gf:
            fx |= mk.effect_mask(em, rgba, dn or dname, g, f, unit)
    return body & ~fx, int((fx & body).sum())


def fit_mask(rdir, t):
    from PIL import Image
    return np.asarray(Image.open(f"{rdir}/sprite_{t + 1:03d}.png").convert("RGBA"))[..., 3] > 128


def edges(m):
    cols = np.nonzero(m.sum(0) >= 2)[0]; rows = np.nonzero(m.sum(1) >= 2)[0]
    if not len(cols) or not len(rows):
        return None
    return np.array([cols[0], cols[-1], rows[0], rows[-1]], float)


OUTWARD = np.array([-1, 1, -1, 1])   # left edge moving left, right edge right, top up, bottom down


def excursion(masks):
    m0 = masks[0]; e0 = edges(m0)
    if e0 is None:
        return None, None
    h = max(e0[3] - e0[2], 1.0); n0 = max(m0.sum(), 1)
    area, reach = [], []
    for m in masks:
        area.append(float((m ^ m0).sum() / n0))
        e = edges(m)
        reach.append(((e - e0) * OUTWARD / h) if e is not None else np.zeros(4))
    return np.array(area), np.array(reach)


def frames_json(blend):
    return json.load(open(blend + ".frames.json"))


def clip_ranges(fj):
    best = {}
    for k, a, b in fj["segments"]:
        if k not in best or b - a > best[k][1] - best[k][0]:
            best[k] = (a, b)
    return best


def unit_loops(unit):
    c = json.load(open(f"{ROOT}/tools/homm3_def_retarget/units/{unit}.json"))
    return set(c.get("loops", ["Idle", "Move"]))


def peaks(x, n, floor, allow_end):
    out = []
    for t in range(1, n):
        left = x[t] >= x[t - 1]
        right = (t == n - 1 and allow_end) or (t < n - 1 and x[t] > x[t + 1])
        if left and right and x[t] >= floor:
            out.append(t)
    return out


def classify(r, cfg):
    return "missed" if r <= cfg["minRatio"] else "underEmphasised" if r < cfg["flagRatio"] else "ok"


def detect(unit, blend, rdir, cfg):
    """Per action clip: keys, ratios and status, from the DEF (bodyNoFx) and the build's renders.
    Hidden-body frames are not known here (they need the keys); bl_deliver marks them."""
    from PIL import Image  # noqa: F401  (fail early when PIL is missing)
    fj = frames_json(blend)
    layers = fx_layers(unit)
    dname = os.path.basename(os.path.dirname(fj["sources"][0])).rsplit(".", 1)[0].upper() + ".DEF"
    crex = re.compile(cfg["clips"]); loops = unit_loops(unit)
    ms = json.load(open(f"{ROOT}/artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/{unit}/linked_master/master_sequence/master_sequence.json"))
    suffix = {s["clipKey"]: s["contractSuffix"] for s in ms["segments"]}
    out = {}
    for clip, (a, b) in sorted(clip_ranges(fj).items(), key=lambda kv: kv[1][0]):
        if not crex.search(clip) or b - a < 3 or suffix.get(clip) in loops:
            continue
        if cfg.get("onlyClips") and clip not in cfg["onlyClips"]:
            continue
        if clip in cfg.get("skipClips", []):
            continue
        dm, fxpx = [], 0
        for t in range(a, b):
            m, k = def_body(unit, fj["sources"][t], layers, dname); dm.append(m); fxpx += k
        fm = [fit_mask(rdir, t) for t in range(a, b)]
        dA, dR = excursion(dm); fA, fR = excursion(fm)
        if dA is None or fA is None:
            out[clip] = {"range": [a, b], "suffix": suffix.get(clip), "keys": [], "note": "empty neutral silhouette"}
            continue
        n = b - a; death = "death" in clip
        cand = {i: dA[i] for i in peaks(dA, n, cfg["minDefExcursion"], death)}
        for e in range(4):
            for i in peaks(dR[:, e], n, cfg["minDefReach"], death):
                cand[i] = max(cand.get(i, 0.0), dA[i])
        pk = []
        for i in sorted(cand, key=lambda i: -cand[i]):
            if all(abs(i - j) > 1 for j in pk):
                pk.append(i)
        kl = []
        for i in sorted(pk[:cfg["maxKeysPerClip"]]):
            e = int(np.argmax(dR[i])) if dR[i].max() >= cfg["minDefReach"] else int(np.argmax(np.abs(dR[i])))
            if abs(dR[i, e]) >= cfg["minDefReach"]:
                r = float(fR[i, e] / dR[i, e]); basis = "reach:" + "LRTB"[e]
            else:
                r = float(fA[i] / max(dA[i], 1e-9)); basis = "area"
            kl.append({"frame": a + i, "local": i, "defArea": round(float(dA[i]), 3), "fitArea": round(float(fA[i]), 3),
                       "edge": e, "defReach": round(float(dR[i, e]), 3), "fitReach": round(float(fR[i, e]), 3),
                       "basis": basis, "ratio": round(r, 3), "status": classify(r, cfg)})
        out[clip] = {"range": [a, b], "suffix": suffix.get(clip), "keys": kl, "defFxPixels": fxpx,
                     "fxMasked": bool(layers)}
    return out


def ratio_at(unit, blend, rdir, clip_info):
    """Re-measure the fit side of already detected keys on another set of renders (same edge/basis)."""
    fj = frames_json(blend)
    a, b = clip_info["range"]
    fm = [fit_mask(rdir, t) for t in range(a, b)]
    fA, fR = excursion(fm)
    res = []
    for k in clip_info["keys"]:
        i = k["local"]
        if k["basis"] == "area":
            res.append(round(float(fA[i] / max(k["defArea"], 1e-9)), 3))
        else:
            res.append(round(float(fR[i, k["edge"]] / k["defReach"]), 3))
    return res


# ------------------------------------------------------------------ planning (numpy only; runs inside Blender)
def raised(t, lo, hi):
    if hi == lo:
        return 1.0
    u = min(1.0, max(0.0, (t - lo) / (hi - lo)))
    return 0.5 - 0.5 * math.cos(math.pi * u)


def bump(t, lo, c, hi):
    if t <= lo or t >= hi:
        return 0.0
    return raised(t, lo, c) if t <= c else 1.0 - raised(t, c, hi)


LEGS = re.compile(r"^(Hips|(Left|Right)(UpLeg|Leg|Foot|ToeBase))$")


def plan(keys, det, cfg):
    """keys: dump dict (names, Q, head, hipsScale, allNames, allParent, restQ); det: detect() output.
    Returns (Q2, per-clip plan info). Q2 == Q outside emphasised clips."""
    sk = Skeleton(keys); names = sk.names
    Q = keys["Q"]; Q2 = Q.copy(); hs = keys["hipsScale"]; head = keys["head"]
    bre = re.compile(cfg["bones"])
    bsel_all = [j for j, n in enumerate(names) if bre.match(n)]
    cap = math.radians(cfg["maxExtraDeg"]); lim = math.radians(170)
    M = sk.forward(Q)
    info = {}
    zs = head[..., 2]
    for clip, c in det.items():
        a, b = c["range"]; n = b - a; death = "death" in clip
        ci = {"emphasised": False}
        info[clip] = ci
        for k in c["keys"]:
            if (hs[k["frame"]] < HIDDEN_SCALE) and k["status"] != "hidden":
                k["status"] = "hidden"
        flagged = [k for k in c["keys"] if k["status"] == "underEmphasised"]
        if not flagged:
            continue
        # contact chains: an arm whose hand comes within contactBand of the ground (the lowest
        # bone head) at any frame of the clip is a supporting limb, never emphasised
        hgt = max(float((zs[a:b].max(1) - zs[a:b].min(1)).max()), 1e-6)
        ground = zs[a:b].min(1)
        excl = set()
        for side in ("Left", "Right"):
            h = f"{side}Hand"
            if h in sk.col and ((zs[a:b, sk.col[h]] - ground) < cfg["contactBand"] * hgt).any():
                excl |= {f"{side}{p}" for p in ("Shoulder", "Arm", "ForeArm", "Hand")}
        # a planted limb hangs off the spine: its ancestors must not turn either (no IK here).
        # Same for legs: on rigs whose legs hang below a spine bone (basilisk, demon) turning that
        # bone would swing the feet, so every ancestor of a leg bone is protected too.
        excl |= {n for n in sk.alln if LEGS.match(n) and n != "Hips"}
        for e in list(excl):
            p = sk.par.get(e, "")
            while p:
                excl.add(p); p = sk.par.get(p, "")
        bsel = [j for j in bsel_all if names[j] not in excl]
        ci["contactChains"] = sorted(excl & set(names))
        if not bsel:
            ci["note"] = "no articulable bones (all excluded)"
            continue
        bw = np.array([cfg["boneWeights"].get(names[j], 1.0) for j in bsel])
        Wc = np.stack([M[names[j]][a:b] for j in bsel], 1)                   # (n, B, 4)
        dev = qlog(qmul(Wc, qinv(Wc[0])[None]))
        G = np.ones(n)
        for k in flagged:
            i = k["local"]
            g = min(cfg["maxGain"], 1 + cfg["strength"] * (1 / k["ratio"] - 1)); k["gain"] = round(g, 3)
            for t in range(n):
                w = raised(t, 0, i) if t <= i else (1.0 if death else 1.0 - raised(t, i, n - 1))
                G[t] = max(G[t], 1 + (g - 1) * w)
        big = np.zeros(len(bsel), bool)
        for k in flagged:
            big |= np.degrees(np.linalg.norm(dev[k["local"]], axis=-1)) >= cfg["minKeyDeg"]
        scale = 1 + (G[:, None] - 1) * (bw * big)[None]
        dev2 = dev * scale[..., None]
        base = dev2.copy()
        locs = [k["local"] for k in flagged]
        for k in flagged:
            i = k["local"]; vk = base[i]; af = cfg["anticipationFrames"]
            if cfg["anticipation"] > 0 and i >= 2 and not any(0 < i - j <= af + 1 for j in locs if j != i):
                c_ = max(1, i - af)
                for t in range(1, i):
                    dev2[t] -= cfg["anticipation"] * vk * bump(t, 0, c_, i) * big[:, None]
                k["anticipationCentre"] = a + c_
            ff = cfg["followFrames"]; hi = min(i + 1 + ff, n - 1 if not death else n)
            if cfg["followThrough"] > 0 and i + 1 < hi and not any(0 < j - i <= ff for j in locs if j != i):
                for t in range(i + 1, min(hi, n)):
                    dev2[t] += cfg["followThrough"] * ((1 + cfg["overshoot"]) * vk - base[t]) * bump(t, i, i + 1, hi) * big[:, None]
                k["followThroughTo"] = a + hi
        extra = dev2 - dev
        en = np.linalg.norm(extra, axis=-1, keepdims=True)
        dev2 = dev + extra * np.minimum(1, cap / np.maximum(en, 1e-12))
        tn = np.linalg.norm(dev2, axis=-1, keepdims=True)
        dev2 = dev2 * np.minimum(1, np.maximum(lim, np.linalg.norm(dev, axis=-1, keepdims=True)) / np.maximum(tn, 1e-12))
        dev2[0] = dev[0]
        if not death:
            dev2[-1] = dev[-1]
        for t in range(n):
            if hs[a + t] < HIDDEN_SCALE:
                dev2[t] = dev[t]
        Wt = qmul(qexp(dev2), np.broadcast_to(Wc[0], dev2.shape[:-1] + (4,)))
        tgt = {names[bsel[j]]: Wt[:, j] for j in range(len(bsel))}
        Q2 = sk.locals_from(Q2, tgt, a, b)
        ex = np.degrees(np.linalg.norm(dev2 - dev, axis=-1))
        ci.update({"emphasised": True, "bones": [names[j] for j in bsel],
                   "extraDegPerFrameMax": [round(float(x), 2) for x in ex.max(1)],
                   "extraDegByBoneAtKeys": {names[bsel[j]]: [round(float(ex[k["local"], j]), 1) for k in flagged]
                                            for j in range(len(bsel)) if ex[[k["local"] for k in flagged], j].max() > 0.5}})
    return Q2, info


# ------------------------------------------------------------------ invariants (deliver.py and the validator)
def check_invariants(before, after, det, info, cfg):
    """Errors (list of str) for an emphasised pair of key dumps."""
    err = []
    Qa, Qb = before["Q"], after["Q"]
    if Qa.shape != Qb.shape or list(before["names"]) != list(after["names"]):
        return ["key dumps differ in shape or bone names"]
    T = Qa.shape[0]
    names = [str(n) for n in before["names"]]
    changed = np.zeros(T, bool)
    allowed_last = {}
    for clip, c in det.items():
        if info.get(clip, {}).get("emphasised"):
            a, b = c["range"]; changed[a + 1:b] = True
            allowed_last[b - 1] = "death" in clip
    diff = qangle_deg(Qa, Qb).max(1)                         # per frame, largest local key change
    out = np.nonzero((diff > 1e-3) & ~changed)[0]
    if len(out):
        err.append(f"keys changed outside emphasised clips (or on a clip's first frame) at frames {out.tolist()[:10]}")
    for t, is_death in allowed_last.items():
        if not is_death and diff[t] > 1e-3:
            err.append(f"a non-Death clip's last frame {t} changed ({diff[t]:.3f} deg)")
    hs = before["hipsScale"]
    hid = np.nonzero((hs < HIDDEN_SCALE) & (diff > 1e-3))[0]
    if len(hid):
        err.append(f"hidden-body frames changed: {hid.tolist()[:10]}")
    legs = [j for j, n in enumerate(names) if LEGS.match(n)]
    if legs:
        d = float(np.abs(after["head"][:, legs] - before["head"][:, legs]).max())
        if d > 1e-5:
            err.append(f"Hips/leg drift {d:.2e} > 1e-5")
    for clip, ci in info.items():           # a contact chain is planted within its own clip only
        a, b = det[clip]["range"]
        cc = [names.index(n) for n in ci.get("contactChains", []) if n in names]
        if cc:
            d = float(np.abs(after["head"][a:b, cc] - before["head"][a:b, cc]).max())
            if d > 1e-5:
                err.append(f"{clip}: contact-chain drift {d:.2e} > 1e-5")
    sk = Skeleton(before); Ma, Mb = sk.forward(Qa), sk.forward(Qb)
    worst = max(float(qangle_deg(Ma[n], Mb[n]).max()) for n in Ma)
    if worst > cfg["maxExtraDeg"] + 0.5:
        err.append(f"extra rotation {worst:.2f} deg > cap {cfg['maxExtraDeg']}")
    return err
