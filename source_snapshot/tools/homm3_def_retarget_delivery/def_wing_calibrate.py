"""Measure a HoMM3 flier's DEF Move wing beat (degrees peak to peak) by silhouette calibration against its own rig.

    python tools/homm3_def_retarget_delivery/def_wing_calibrate.py measure <unit> [--out J] [--sheet PNG]

Why: flyer_articulation.wing_rule() judges a unit with a row in reference/def_wing_range.json on
wingRange >= DEF_RANGE_SHARE x the DEF's own beat. That beat is not in any file; this tool measures it.

Method (no Blender, no game; numpy + PIL on the canonical build):
  * the canonical GLB (artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb) is posed on its
    <unit>_DEF_Master clip, whose key t is master frame t (the frame the DEF plate t is compared with), and skinned
    (linear blend skinning with the glTF inverse bind matrices);
  * it is projected by the build's own sprite camera (<blend>.spritecam.json: right, up, pxPerUnit, offset, size;
    glTF Y-up -> Blender Z-up) and rasterised; idle frame 0 and every Move frame must match the build's own Blender
    render of that frame (renders/sprite_<t+1>.png) to CAMERA_IOU_MIN or the unit is refused, so a camera, axis,
    skinning or stale-render mismatch cannot produce a number;
  * for every DEF Move frame, each wing (a top wing joint and its subtree) is rotated about the body's long axis
    (the rest-frame Blender +Y carried by the wing's parent bone: the axis castle_refine's "wing" parameter uses)
    through its pivot, both wings together and mirrored, over SWEEP_DEG in STEP_DEG steps; the angle whose whole
    silhouette has the best IoU with the DEF plate's alpha is the match;
  * the frame's beat angle = the posed wing's own angle about that axis (from Move frame 0, raising positive,
    averaged over the two wings) + the matched angle; rangeDeg = its peak to peak over the Move frames.
Bounds are honest, not a confidence interval: a frame's bracket is every swept angle whose IoU is within IOU_TOL of
its best, widened by half a step; the range's bracket is [max(lo) - min(hi), max(hi) - min(lo)] (floored at 0).
A flat IoU curve on a low-flap DEF therefore shows up as a wide bracket; the gate uses the upper end there.
The DEF plate's creature is its opaque pixels: the extracted DEF carries its ground shadow at alpha 64/128.
Score: IoU of the wing outside our body (rig wing pixels not covered by the rig body) with the DEF's pixels outside
our body, so a wing that cannot match is not rewarded for hiding inside the body.
A row is usable only when every match is interior to the sweep, reaches MATCH_IOU_MIN, and our beat is a roll
(ROLL_SHARE_MIN); --write-row refuses anything else and also needs the review sheet's verdict: passing the numbers
is necessary, not sufficient.
Fleet run (2026-09-27, 51 winged fliers): 14 passed the numeric checks. Only the two griffins matched on the sheet.
The rest paired the DEF's wing with a different part of the rig, or with a body in a different pose. Examples:
h3_wyvern_monarch 40.1 and h3_gold_dragon 77.3 show the DEF's swept-back wing unmatched; the cove birds and
gargoyles show the body itself off the plate. So only the griffins carry rows. Output: the measurement with its per-frame curves, and an optional review sheet.
Pilot (2026-09-27): h3_royal_griffin 110.7 [105.7, 190.7], h3_battle_griffin 115.8 [110.8, 125.8], against the
earlier hand calibration's 106 [82, 137] / 107 [83, 137]. Known limit: the sweep is a roll about the body axis;
a DEF "level" frame whose wings are swept back along the body is matched only approximately (griffin level frames
match at 0 .. +35 with IoU ~0.2).
Proof tier: generated artifact (offline measurement of DEF plates against the build's own rig).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from flyer_articulation import GATE_CLIP, MASTER_RUNS, glb_clips  # noqa: E402

SCHEMA = "homm3_def_wing_calibration.v1"
ROWS = HERE / "reference" / "def_wing_range.json"
STEP_DEG = 5.0
SWEEP_DEG = (-90.0, 90.0)
IOU_TOL = 0.005
# A measurement becomes a def_wing_range.json row only when every Move frame's match is interior to the sweep and its
# wing-residual IoU reaches MATCH_IOU_MIN (the griffin pilot: 0.18 .. 0.45). Below that the rig's wing does not
# resemble the DEF's (h3_chimera 0.06 .. 0.13) and the angle is noise; the unit keeps no row (flatFloor).
MATCH_IOU_MIN = 0.15
# The sweep measures the roll of the wing about the body axis; the gate's wingRange is the whole torso-relative
# rotation of any wing bone. They compare only when our own Move beat is itself a roll about that axis: the
# peak-to-peak of our posed roll over the DEF Move frames must be at least ROLL_SHARE_MIN of our Unit_Move wingRange
# (h3_royal_griffin 105.7 / 104.5). A wing that sweeps fore and aft (h3_archangel: roll small against a wingRange of
# 88.5) gets no row: its DEF roll says nothing about a whole-rotation floor.
ROLL_SHARE_MIN = 0.8
# Below STATIC_WING_DEG of wingRange our wing does not beat at all (hota_cove_ayssid 0.7): the beat is then all matched
# angle, a pure DEF roll measurement, and the share rule does not apply.
STATIC_WING_DEG = 10.0
CAMERA_IOU_MIN = 0.8    # h3_royal_griffin 0.92..0.94 (Blender's anti-aliased alpha > 0 is a little wider). Dragons and
                        # pegasi read 0.82..0.86 on raised-wing frames: body exact, far wing a few degrees apart (the
                        # GLB export keeps 4 influences per vertex, the Blender render all of them). A camera, axis or
                        # coordinate error reads far lower (the unshadowed DEF plate against the rig: 0.37).
BLENDER_BODY_AXIS = np.array([0.0, 1.0, 0.0])    # Blender +Y (the capture faces -Y), castle_refine's wing axis
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---------------------------------------------------------------- glTF
def load_glb(path: Path | bytes):
    """(json, accessor reader) of a GLB file or of a GLB's bytes (an in-memory delivery stage's output)."""
    b = bytes(path) if isinstance(path, (bytes, bytearray)) else Path(path).read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    binc = b[28 + jl:]

    def acc(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        dt, w = np.dtype(CT[a["componentType"]]).newbyteorder("<"), NC[a["type"]]
        stride = bv.get("byteStride", dt.itemsize * w)
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        if stride == dt.itemsize * w:
            x = np.frombuffer(binc, dtype=dt, count=w * a["count"], offset=off).reshape(a["count"], w)
        else:
            x = np.stack([np.frombuffer(binc, dtype=dt, count=w, offset=off + k * stride) for k in range(a["count"])])
        x = x.astype(float)
        if a.get("normalized"):
            x /= float(np.iinfo(CT[a["componentType"]]).max)
        return x
    return js, acc


def q2m(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs(t, r, s):
    m = np.eye(4)
    m[:3, :3] = q2m(r) * np.asarray(s, float)
    m[:3, 3] = t
    return m


def rot_about(axis, deg, pivot):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    th = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    R = np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = pivot - R @ pivot
    return m


class Rig:
    def __init__(self, path: Path, clip: str):
        js, acc = load_glb(path)
        if isinstance(path, (bytes, bytearray)):
            path = Path("<in-memory GLB>")
        self.js = js
        nodes = js["nodes"]
        self.parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
        self.base = [(np.array(n.get("translation", [0, 0, 0]), float), np.array(n.get("rotation", [0, 0, 0, 1]), float),
                      np.array(n.get("scale", [1, 1, 1]), float)) for n in nodes]
        anims = {a["name"]: a for a in js["animations"]}
        if clip not in anims:
            raise SystemExit(f"{path.name}: no {clip} clip (the master clip keys master frames)")
        self.chan = {}
        for ch in anims[clip]["channels"]:
            s = anims[clip]["samplers"][ch["sampler"]]
            self.chan[(ch["target"]["node"], ch["target"]["path"])] = (acc(s["input"])[:, 0], acc(s["output"]))
        skin_nodes = [i for i, n in enumerate(nodes) if "skin" in n and "mesh" in n]
        if not skin_nodes or len({nodes[i]["skin"] for i in skin_nodes}) != 1:
            raise SystemExit(f"{path.name}: expected skinned mesh nodes sharing one skin, found {skin_nodes}")
        sk = js["skins"][nodes[skin_nodes[0]]["skin"]]
        self.joints = sk["joints"]
        self.names = [nodes[j].get("name", str(j)) for j in self.joints]
        self.ibm = acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        prims = [p for i in skin_nodes for p in js["meshes"][nodes[i]["mesh"]]["primitives"]]
        V, J, W, F = [], [], [], []
        for p in prims:                      # every skinned mesh (a unit's _Rubble mesh too: its bones hide it)
            at = p["attributes"]
            base = sum(len(v) for v in V)
            V.append(acc(at["POSITION"]))
            J.append(acc(at["JOINTS_0"]).astype(int))
            W.append(acc(at["WEIGHTS_0"]))
            F.append(acc(p["indices"]).astype(int).reshape(-1, 3) + base)
        self.V, self.J, self.W, self.F = np.concatenate(V), np.concatenate(J), np.concatenate(W), np.concatenate(F)
        self.W /= np.maximum(self.W.sum(1, keepdims=True), 1e-9)

    def world(self, frame: int) -> list[np.ndarray]:
        """World matrices of all nodes at master frame `frame` (the clip's key index)."""
        loc = []
        for i, (t, r, s) in enumerate(self.base):
            t, r, s = t.copy(), r.copy(), s.copy()
            for path in ("translation", "rotation", "scale"):
                c = self.chan.get((i, path))
                if c is not None:
                    v = c[1][min(frame, len(c[1]) - 1)]
                    if path == "translation":
                        t = v
                    elif path == "rotation":
                        r = v / np.linalg.norm(v)
                    else:
                        s = v
            loc.append(trs(t, r, s))
        out = [None] * len(loc)

        def g(i):
            if out[i] is None:
                p = self.parent.get(i)
                out[i] = loc[i] if p is None else g(p) @ loc[i]
            return out[i]
        for i in range(len(loc)):
            g(i)
        return out

    def skin(self, jm: np.ndarray, rows=None) -> np.ndarray:
        """Skinned positions (glTF space) from joint world matrices jm [nJ,4,4]."""
        V, J, W = (self.V, self.J, self.W) if rows is None else (self.V[rows], self.J[rows], self.W[rows])
        S = jm @ self.ibm
        Vh = np.concatenate([V, np.ones((len(V), 1))], 1)
        out = np.zeros((len(V), 3))
        for k in range(J.shape[1]):
            out += W[:, k:k + 1] * np.einsum("nij,nj->ni", S[J[:, k]], Vh)[:, :3]
        return out


# ---------------------------------------------------------------- camera
def to_blender(p):
    return np.stack([p[..., 0], -p[..., 2], p[..., 1]], -1)


def to_gltf_dir(v):
    return np.array([v[0], v[2], -v[1]], float)


class Cam:
    def __init__(self, path: Path):
        c = json.loads(path.read_text(encoding="utf-8"))
        self.right, self.up = np.array(c["right"]), np.array(c["up"])
        self.s, (self.ox, self.oy) = float(c["pxPerUnit"]), c["offset"]
        self.size = tuple(int(x) for x in c["size"])

    def px(self, p_gltf):
        b = to_blender(p_gltf)
        return np.stack([self.ox + self.s * (b @ self.right), self.oy - self.s * (b @ self.up)], -1)


def raster(size, P2, F) -> np.ndarray:
    im = Image.new("1", size, 0)
    d = ImageDraw.Draw(im)
    for a, b, c in F:
        d.polygon([tuple(P2[a]), tuple(P2[b]), tuple(P2[c])], fill=1)
    return np.array(im, bool)


def iou(a, b) -> float:
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0


def plate(png: str) -> np.ndarray:
    """Any-alpha mask (our Blender renders)."""
    with Image.open(png) as im:
        return np.array(im.convert("RGBA"))[:, :, 3] > 0


def def_plate(png: str) -> np.ndarray:
    """The creature on a DEF plate: opaque pixels only. The extracted DEF carries its ground shadow as alpha 64/128
    (h3_royal_griffin Move: 1826 shadow pixels against 3270 creature pixels), which would read as a lowered wing."""
    with Image.open(png) as im:
        return np.array(im.convert("RGBA"))[:, :, 3] == 255


def signed_angle(axis, a, b) -> float:
    ax = axis / np.linalg.norm(axis)
    a = a - ax * (a @ ax)
    b = b - ax * (b @ ax)
    return math.degrees(math.atan2(float(np.cross(a, b) @ ax), float(a @ b)))


# ---------------------------------------------------------------- measure
def measure(unit: str, sheet: Path | None = None) -> dict:
    ud = ROOT / "artifacts/homm3_def_retarget" / unit
    glb = ud / f"{unit}_def_retarget.glb"
    camp = ud / f"{unit}_def_retarget.blend.spritecam.json"
    msp = MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    for p in (glb, camp, msp):
        if not p.is_file():
            raise SystemExit(f"{unit}: missing {p}")
    ms = json.loads(msp.read_text(encoding="utf-8"))
    rig = Rig(glb, f"{unit}_DEF_Master")
    cam = Cam(camp)
    nj = len(rig.joints)
    jidx = {j: k for k, j in enumerate(rig.joints)}
    is_wing = ["wing" in n.lower() for n in rig.names]
    roots = [k for k in range(nj) if is_wing[k] and not (rig.parent.get(rig.joints[k]) in jidx and is_wing[jidx[rig.parent[rig.joints[k]]]])]
    sub = {}
    for r in roots:
        s = {r}
        changed = True
        while changed:
            changed = False
            for k in range(nj):
                p = rig.parent.get(rig.joints[k])
                if k not in s and p in jidx and jidx[p] in s:
                    s.add(k)
                    changed = True
        sub[r] = sorted(s)
    wsum = {r: np.array([rig.W[v][np.isin(rig.J[v], sub[r])].sum() for v in range(len(rig.V))]) for r in roots}
    wrow = {r: wsum[r] > 0.5 for r in roots}
    roots = [r for r in roots if wrow[r].any()]      # unweighted legacy wing bones (LeftWing/RightWing) drive nothing
    if len(roots) < 2 or len(roots) % 2:
        raise SystemExit(f"{unit}: expected weighted top wing joints in pairs, found {[rig.names[k] for k in roots]}")
    # insects carry two pairs (WingA*/WingB*): every root is swept by the same angle, raising positive
    anyw = np.logical_or.reduce([wrow[r] for r in roots])
    fw = anyw[rig.F].any(1)
    body_F, wing_F = rig.F[~fw], rig.F[fw]

    segs = [s for s in ms["segments"] if s["contractSuffix"] == "Move"]
    if not segs:
        raise SystemExit(f"{unit}: master sequence has no Move segment")
    seg = max(segs, key=lambda s: s["frameCount"])
    frames = list(range(seg["globalStart"], seg["globalEnd"]))
    idle0 = next(s for s in ms["segments"] if s["contractSuffix"] == "Idle")["globalStart"]
    nkeys = max(len(c[0]) for c in rig.chan.values())
    if nkeys < len(ms["frames"]):
        raise SystemExit(f"{unit}: master clip has {nkeys} keys for {len(ms['frames'])} master frames")

    def posed(t):
        wm = rig.world(t)
        return np.stack([wm[j] for j in rig.joints])

    # camera check: our raster of the master frame must match the build's own Blender sprite render of it
    # (renders/sprite_<t+1>.png, alpha), so a camera, axis or skinning mismatch cannot produce a number
    cam_iou = {}
    for t in [idle0] + frames:
        rp = ud / "renders" / f"sprite_{t + 1:03d}.png"
        if not rp.is_file():
            raise SystemExit(f"{unit}: no build render {rp} to check the camera against")
        cam_iou[t] = round(iou(raster(cam.size, cam.px(rig.skin(posed(t))), rig.F), plate(str(rp))), 4)
    if min(cam_iou.values()) < CAMERA_IOU_MIN:
        raise SystemExit(f"{unit}: raster vs the build's sprite render IoU {cam_iou} < {CAMERA_IOU_MIN}; the GLB, camera "
                         "or renders are out of step (rebuild, or the renders are stale)")

    # raising sign per wing: +theta about the body axis lifts the wing's centroid (glTF +Y) at Move frame 0
    jmF0 = posed(frames[0])
    sign = {}

    def par_rot(jm, r):
        """The wing parent's (torso's) rotation since bind."""
        p = rig.parent.get(rig.joints[r])
        if p not in jidx:
            return np.eye(3)
        return jm[jidx[p]][:3, :3] @ np.linalg.inv(np.linalg.inv(rig.ibm[jidx[p]])[:3, :3])

    AX_REST = to_gltf_dir(BLENDER_BODY_AXIS)

    def wing_axis(jm, r):
        p = rig.parent.get(rig.joints[r])
        par = jm[jidx[p]] if p in jidx else np.eye(4)
        # rest-frame Blender +Y carried by the parent bone's rotation since bind
        bind_par = np.linalg.inv(rig.ibm[jidx[p]]) if p in jidx else np.eye(4)
        R = par[:3, :3] @ np.linalg.inv(bind_par[:3, :3])
        return R @ to_gltf_dir(BLENDER_BODY_AXIS), jm[r][:3, 3].copy()

    P_F0 = rig.skin(jmF0)
    for r in roots:
        ax, pv = wing_axis(jmF0, r)
        c = P_F0[wrow[r]].mean(0)
        c2 = (rot_about(ax, 10.0, pv) @ np.append(c, 1))[:3]
        sign[r] = 1.0 if c2[1] > c[1] else -1.0
    # torso-relative: the wing centroid seen from the pivot, in the parent bone's bind frame, so a body roll or pitch
    # (the whole unit turning) is not read as a wing beat
    ref_vec = {r: np.linalg.inv(par_rot(jmF0, r)) @ (P_F0[wrow[r]].mean(0) - wing_axis(jmF0, r)[1]) for r in roots}

    angles = np.arange(SWEEP_DEG[0], SWEEP_DEG[1] + 1e-9, STEP_DEG)
    rows = []
    wrows = np.nonzero(anyw)[0]
    for t in frames:
        jm = posed(t)
        P = rig.skin(jm)
        body = raster(cam.size, cam.px(P), body_F)
        d = def_plate(ms["frames"][t]["sourcePng"])
        phis = []
        for r in roots:
            ax, pv = wing_axis(jm, r)
            v = np.linalg.inv(par_rot(jm, r)) @ (P[wrow[r]].mean(0) - pv)
            phis.append(sign[r] * signed_angle(AX_REST, ref_vec[r], v))
        curve = []
        for a in angles:
            jmA = jm.copy()
            for r in roots:
                ax, pv = wing_axis(jm, r)
                M = rot_about(ax, sign[r] * a, pv)
                for k in sub[r]:
                    jmA[k] = M @ jm[k]
            PA = P.copy()
            PA[wrows] = rig.skin(jmA, wrows)
            wing = raster(cam.size, cam.px(PA), wing_F) & ~body
            curve.append(iou(wing, d & ~body))
        curve = np.array(curve)
        best = int(np.argmax(curve))
        ok = angles[curve >= curve[best] - IOU_TOL]
        phi = float(np.mean(phis))
        rows.append({"masterFrame": t, "posedDeg": round(phi, 1), "matchDeg": float(angles[best]),
                     "bestIoU": round(float(curve[best]), 4), "beatDeg": round(phi + float(angles[best]), 1),
                     "beatBoundsDeg": [round(phi + float(ok.min()) - STEP_DEG / 2, 1), round(phi + float(ok.max()) + STEP_DEG / 2, 1)],
                     "atEdge": bool(best in (0, len(angles) - 1)),
                     "iouCurve": [round(float(x), 4) for x in curve]})
    beats = [r["beatDeg"] for r in rows]
    lo = [r["beatBoundsDeg"][0] for r in rows]
    hi = [r["beatBoundsDeg"][1] for r in rows]
    rng = max(beats) - min(beats)
    b_lo, b_hi = max(0.0, max(lo) - min(hi)), max(hi) - min(lo)
    b_lo, b_hi = min(b_lo, rng), max(b_hi, rng)
    defname = Path(ms["frames"][frames[0]]["sourcePng"])
    out = {
        "schema": SCHEMA, "unit": unit, "tool": "tools/homm3_def_retarget_delivery/def_wing_calibrate.py",
        "rangeDeg": round(rng, 1), "boundsDeg": [round(b_lo, 1), round(b_hi, 1)],
        "def": f"{defname.parent.name} group {ms['frames'][frames[0]].get('defGroup')} ({len(frames)} Move frames)",
        "method": (f"silhouette calibration (def_wing_calibrate.py): wings swept {SWEEP_DEG[0]:.0f}..{SWEEP_DEG[1]:.0f} deg "
                   f"in {STEP_DEG:.0f} deg steps about the body axis against each DEF Move plate, IoU tol {IOU_TOL}"),
        "cameraIoU": {str(k): v for k, v in cam_iou.items()}, "wings": [rig.names[r] for r in roots],
        "glbSha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
        "frames": rows,
        "proof": "generated artifact: offline measurement of DEF plates against the build's own rig",
    }
    refusals = []
    if any(r["atEdge"] for r in rows):
        refusals.append("a best match sits at the sweep's edge (frames "
                        f"{[r['masterFrame'] for r in rows if r['atEdge']]}); the range may be larger than measured")
    posed_roll = max(r["posedDeg"] for r in rows) - min(r["posedDeg"] for r in rows)
    mv = glb_clips(glb).get(GATE_CLIP) or {}
    ours = mv.get("wingRange")
    out["ourPosedRollRangeDeg"], out["ourWingRangeDeg"] = round(posed_roll, 1), ours
    if ours is None or (ours >= STATIC_WING_DEG and posed_roll < ROLL_SHARE_MIN * ours):
        refusals.append(f"our Move beat is not a roll about the body axis (posed roll {posed_roll:.1f} vs wingRange {ours}; "
                        f"share < {ROLL_SHARE_MIN}): the measured DEF roll does not compare with the gate's wingRange")
    weak = [(r["masterFrame"], r["bestIoU"]) for r in rows if r["bestIoU"] < MATCH_IOU_MIN]
    if weak:
        refusals.append(f"wing-residual IoU under {MATCH_IOU_MIN} on (frame, IoU) {weak}: the rig's wing does not match "
                        "the DEF's, so the matched angle is not a measurement")
    out["rowUsable"] = not refusals
    out["refusals"] = refusals
    if sheet:
        write_sheet(sheet, rig, cam, ms, frames, rows, roots, sub, sign, wing_axis, posed, body_F, wing_F, wrows)
    return out


def write_sheet(path, rig, cam, ms, frames, rows, roots, sub, sign, wing_axis, posed, body_F, wing_F, wrows):
    tiles = []
    for t, r in zip(frames, rows):
        jm = posed(t)
        P = rig.skin(jm)
        jmA = jm.copy()
        for w in roots:
            ax, pv = wing_axis(jm, w)
            M = rot_about(ax, sign[w] * r["matchDeg"], pv)
            for k in sub[w]:
                jmA[k] = M @ jm[k]
        PA = P.copy()
        PA[wrows] = rig.skin(jmA, wrows)
        m = raster(cam.size, cam.px(PA), rig.F)
        d = def_plate(ms["frames"][t]["sourcePng"])
        img = np.zeros(d.shape + (3,), np.uint8)
        img[d & ~m] = (220, 60, 60)
        img[m & ~d] = (60, 120, 230)
        img[m & d] = (230, 230, 230)
        tiles.append(img)
    Image.fromarray(np.concatenate(tiles, 1)).save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("measure")
    s.add_argument("unit")
    s.add_argument("--out", type=Path)
    s.add_argument("--sheet", type=Path, help="review sheet: DEF only red, rig only blue, both white")
    s.add_argument("--write-row", metavar="SHEET_VERDICT",
                   help="write the row into reference/def_wing_range.json, recording this review-sheet verdict "
                        "(refused unless rowUsable; the numbers alone do not make a row)")
    a = ap.parse_args(argv)
    out = measure(a.unit, a.sheet)
    txt = json.dumps(out, indent=1)
    if a.out:
        a.out.write_text(txt + "\n", encoding="utf-8")
    brief = {k: out[k] for k in ("unit", "rangeDeg", "boundsDeg", "wings", "rowUsable", "refusals")}
    brief["frames"] = [(r["posedDeg"], r["matchDeg"], r["beatDeg"], r["beatBoundsDeg"], r["bestIoU"]) for r in out["frames"]]
    print(json.dumps(brief))
    if a.write_row is not None:
        if not a.write_row.strip():
            raise SystemExit("--write-row needs the review sheet's verdict")
        if not out["rowUsable"]:
            raise SystemExit(f"{a.unit}: not written to {ROWS.name}: {'; '.join(out['refusals'])}")
        d = json.loads(ROWS.read_text(encoding="utf-8"))
        d["units"][a.unit] = {"rangeDeg": out["rangeDeg"], "boundsDeg": out["boundsDeg"], "def": out["def"],
                              "method": out["method"], "glbSha256": out["glbSha256"],
                              "frames": [{k: r[k] for k in ("masterFrame", "posedDeg", "matchDeg", "beatDeg", "beatBoundsDeg", "bestIoU")}
                                         for r in out["frames"]],
                              "sheetReview": a.write_row,
                              "proof": out["proof"]}
        ROWS.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{a.unit}: row written to {ROWS.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
