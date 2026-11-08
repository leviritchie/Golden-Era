"""Joint coverage: capture joints that bend or shift in the DEF while our mesh animation keeps them still.

    python tools/homm3_authenticity/joint_coverage.py <unit> [--glb <path>] [--out <json>] [--clips Idle,Move]

Rubric item 3a of docs/homm3_unit_authenticity_pass.md. Per clip, one table: reference (capture) joint -> mapped
bone(s) of our rig -> reference range (deg) vs ours (deg) -> flag. Prints only the non-OK rows; writes everything to
V:/olden_port_work/authenticity/<labSid>/joint_coverage.json (next to the boards) unless --out says otherwise.

Reference: the unit's linked-master capture (raw_capture.npz pred_position, one pose per DEF frame; the clip's frames
are the master_sequence segment). Only joint *directions* are used: pred_rot6d and bone lengths are unreliable
(tools/homm3_def_retarget/README.md, Method 4). Two measures, chosen per joint kind:
  hinge  (knee, ankle, toe, elbow, wrist, spine, neck, head): the angle between the incoming segment (parent -> joint)
         and the outgoing one (joint -> child); range = max - min over the clip's frames.
  swing  (UpLeg, Arm, Shoulder: ball joints off the torso, where the hinge angle against the lateral pelvis/clavicle
         line barely changes when the limb swings fore/aft): the outgoing segment's direction in the torso frame
         (pelvis frame for legs, chest frame for arms); range = the largest pairwise angle over the clip's frames.
Each row also carries the mean frame-to-frame change (deg per DEF frame) of the same measure.

Ours: the GLB the game ships, resolved exactly as board.py does (sources.shipped_glb), or --glb. Sampled at the board's
DEF frame times (same timing rule as board.py: one-shot m = n - 1, loops m = n + transitionKeys). Joint heads are the
evaluated world translations; a bone's outgoing direction is its world +Y (every chain child of these rigs sits on its
parent's +Y; verified on the champion, pikeman and royal griffin GLBs), so leaf bones and extra chains are measured too.
Torso frames for swing are the world rotation of the nearest Hips / Spine* ancestor.

Mapping capture joint -> our bone(s):
  name        the same Mixamo name in our rig (build_unit.py drives bones by capture name; DRIVE_SRC copies are
              not distinguishable from a GLB, so extra-arm prefixes are not mapped).
  mountProxy  mounted units (castle_mount staticChains HFL/HFR/HHL/HHR): the human capture's legs land on the horse's
              legs in the sprite, so capture <side>UpLeg / Leg / Foot -> every same-side horse chain bone 0 / 1 / 2
              (front and hind); ours = the most-moving one. A proxy: the capture has two legs, the horse four.
  For quadruped configs (rampart_quadruped "legs") the capture is a human skeleton fitted to a creature sprite, so its
  limbs are a proxy for the creature's legs even where the names match; the JSON says so.
Capture joints with no counterpart and no proxy (e.g. a horse rider's toes) are skipped for mounts, otherwise
MISSING. Bones that are animated but carry ~zero skin weight (whole subtree) are MISSING too, and every animated
zero-own-weight bone is listed under zeroWeightBones.

Capture noise floor: the capture is not trustworthy frame to frame (royal griffin: up to 93 deg of forearm and 22 deg
of head/neck motion across DEF frames that are pixel-identical to idle f0). DEF frames whose sprites are near-identical
(< 0.5% of sprite pixels differ by more than 8/255, matched across all clips) are grouped; a joint's noise is the
largest range the capture shows inside any such group, and that joint's reference minimum is raised to noise + gap.
A capture joint whose noise swamps its range therefore reads OK, not STATIC (captureNoise in the JSON).

DEF reference (tools/homm3_authenticity/keypoints/<labSid>.json, see keypoints.py): when the file exists, every chain
joint with marked/tracked 2D points in the clip gets a row with ref "def". DEF side: the signed 2D bend angle at the
joint over the clip's frames (circular range); its noise is 2 x 1 px marking error over the median segment length,
and refMin = max(15 deg, 2 x noise). Ours: the mapped bone points (Bone head, Bone@tip, Bone@far, axis extremes) of the
GLB projected through the DEF-matched sprite camera (spritecam.py; --view-yaw, default the file's view.yawDeg) at the
board's DEF frame times; 2D bend angles are invariant to the board's similarity fit, so --align is only recorded.
Flags as for capture rows (STATIC / WEAK / OK), MISSING when a chain point has no bone (a rig defect) or the three
points ride one rigid bone, plus TIMING when our peak excursion lands more than 1 DEF frame from the DEF's peak
(cyclic on loops). The DEF reference wins: a capture row whose bone is a measured DEF joint is kept in the JSON with
supersededBy "def" but not printed; the remaining capture rows still report. One table, the ref column per row.

Silhouette evidence (task step 3) is NOT implemented: a per-region DEF frame-difference energy cannot tell limb
articulation from whole-body motion (a rearing horse turns its rigid legs and changes the leg band as much as bent
knees do), and region boxes need the sprite camera to see the DEF's side, which the griffin line does not
(README "DEF view"). The capture table plus the board is the instrument.

CPU on purpose (GPU-first policy, AGENTS.md): the work is a few dozen joints x tens of frames of 3x3 math plus one
skin-weight sum; it runs in well under a second of numpy, below the cost of creating a CUDA context. No torch import.
Read-only over unit artifacts. Proof tier: generated-artifact measurement; the eye on the board confirms.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gltf_scene import Scene  # noqa: E402
from sources import MOCAP_RUNS, ROOT, def_reference, load, sha256, shipped_glb, unit_ids  # noqa: E402
import keypoints as KP  # noqa: E402

SCHEMA = "homm3.authenticity.joint_coverage.v1"
UNITS = ROOT / "tools/homm3_def_retarget/units"

# --- thresholds (tuned 2026-10-07 on h3_pikeman, h3_champion, h3_royal_griffin against their boards) ---
# The capture jitters: on the pikeman Idle, whose DEF legs barely move, hinge ranges of 8-16 deg appear on the legs and
# feet, and short bones (feet, toes, clavicles) are the noisiest. A reference joint counts as moving at REF_MIN_DEG;
# 15 deg sits above that jitter for most joints while the gaps the boards show (champion AttackFront knees 62-101 deg,
# rearing forelimbs) are far above it. Joints on short end bones need REF_MIN_SHORT_DEG.
REF_MIN_DEG = 15.0
REF_MIN_SHORT_DEG = 25.0
# Swing is a max pairwise angle of a 3D direction, so the same jitter inflates it more than a scalar hinge angle
# (pikeman Idle UpLeg swing 7-13 deg, champion Idle capture "horse hip" 15.6 deg on a standing horse).
REF_MIN_SWING_DEG = 20.0
SHORT_JOINTS = ("Foot", "ToeBase", "Shoulder", "Hand")   # capture segments ~0.1-0.2 of the leg: angular noise x2
# Ours relative to the reference. Delta retarget reproduces the capture's ranges within ~20% on directly driven
# bones (pikeman), so < 50% is a real damping (WEAK) and < 25% is effectively still (STATIC).
STATIC_RATIO = 0.25
WEAK_RATIO = 0.50
# Minimum absolute shortfall (ref - ours) for any flag: the capture's jitter adds ~5-10 deg to every range, so a
# 20-deg reference against 9 deg ours (ratio 0.45) is within noise, while 60 vs 20 is a real gap. Without it the
# champion's damped rider (riderDamp 0.5) flooded ~30 WEAK rows at 15-25 deg references.
MIN_GAP_DEG = 15.0
# Ours below this many degrees is still, whatever the ratio (procedural rigs often hold a joint at exactly 0).
STILL_DEG = 2.0
# A bone whose subtree carries less than this summed skin weight (vertex equivalents) deforms nothing visible.
MIN_SUBTREE_WEIGHT = 5.0

# Capture noise floor (coordinator 2026-10-07, lane A): on royal griffin DEF frames pixel-identical to idle f0 the
# capture still swings the forearm 93 deg and head/neck 22 deg. Per joint, the largest range inside one group of
# (near-)identical DEF frames is that joint's noise; a capture reference must exceed noise + MIN_GAP_DEG to flag.
STATIC_DIFF_LEVEL = 8
STATIC_DIFF_FRAC = 0.005
# DEF keypoint reference (keypoints/<unit>.json). Hand marks are good to about MARK_SIGMA_PX; the bend angle of a
# joint whose segments are L px long then jitters by about deg(2 * sigma / L), so a DEF reference counts as moving
# only above max(DEF_REF_MIN_DEG, 2 x that). Ours is exact (bone transforms), so the flags use the same
# STATIC/WEAK ratios and MIN_GAP_DEG as the capture rows. TIMING: ours peaks (largest excursion from the clip
# median, in the DEF's direction) more than TIMING_FRAMES DEF frames from the DEF's peak (cyclic on loops).
MARK_SIGMA_PX = 1.0
DEF_REF_MIN_DEG = 15.0
TIMING_FRAMES = 1

SWING_SUFFIXES = ("UpLeg", "Arm", "Shoulder")   # endswith; "ForeArm" is excluded explicitly
TORSO = re.compile(r"^(Hips|Spine\d*)$")
MOUNT_CHAIN = re.compile(r"^H([FH])([LR])$")


def base(n: str) -> str:
    return str(n).split(":")[-1]


def kind_of(name: str) -> str:
    if name.endswith("ForeArm"):
        return "hinge"
    return "swing" if name.endswith(SWING_SUFFIXES) else "hinge"


def ang(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angle (deg) between row vectors."""
    na = np.linalg.norm(a, axis=-1); nb = np.linalg.norm(b, axis=-1)
    c = (a * b).sum(-1) / np.maximum(na * nb, 1e-12)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def frame_of(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(T,3,3) orthonormal frames, rows = axes: a, b orthogonalised against a, a x b."""
    a = a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    b = b - a * (a * b).sum(-1, keepdims=True)
    b = b / np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-12)
    return np.stack([a, b, np.cross(a, b)], axis=-2)


def measure(series: np.ndarray, kind: str) -> tuple[float, float]:
    """(range, mean frame-to-frame change) in degrees. hinge: series (T,) angles; swing: (T,3) directions."""
    if len(series) < 2:
        return 0.0, 0.0
    if kind == "hinge":
        return float(series.max() - series.min()), float(np.abs(np.diff(series)).mean())
    d = series / np.maximum(np.linalg.norm(series, axis=-1, keepdims=True), 1e-12)
    pair = np.degrees(np.arccos(np.clip(d @ d.T, -1, 1)))
    return float(pair.max()), float(ang(d[1:], d[:-1]).mean())


# ---------------------------------------------------------------- reference (capture)
class Capture:
    def __init__(self, src: str):
        d = MOCAP_RUNS / src / "linked_master"
        self.path = d / "capture/capture/raw_capture.npz"
        z = np.load(self.path)
        self.P = z["pred_position"].astype(np.float64)          # (F, J, 3); pred_rot6d deliberately unused
        self.names = [base(n) for n in z["joint_names"]]
        self.parents = [int(p) for p in z["parents"]]
        self.ix = {n: i for i, n in enumerate(self.names)}
        self.child = {}
        for j, p in enumerate(self.parents):
            if p >= 0:
                self.child.setdefault(p, []).append(j)
        ms = load(d / "master_sequence/master_sequence.json")
        if ms["frameCount"] != len(self.P):
            raise SystemExit(f"{src}: capture has {len(self.P)} poses, master_sequence {ms['frameCount']}")
        self.segments = {s["clipKey"]: s for s in ms["segments"] if s["role"] != "bookend" and s.get("exportsClip", True)}

    def _pos(self, X, n):
        return X[:, self.ix[n]]

    def torso(self, X, arm: bool) -> np.ndarray | None:
        g = lambda n: self._pos(X, n)  # noqa: E731
        try:
            if arm:
                return frame_of(g("Neck") - g("Spine1"), g("LeftArm") - g("RightArm"))
            return frame_of(g("Spine1") - g("Hips"), g("LeftUpLeg") - g("RightUpLeg"))
        except KeyError:
            return None

    def joints(self, clip_key: str) -> dict:
        s = self.segments[clip_key]
        return self.joints_at(np.arange(s["globalStart"], s["globalEnd"]))

    def noise_floor(self, groups: list[list[int]]) -> dict:
        """Per joint: the largest range the capture shows inside one group of pixel-identical / near-identical DEF
        frames (where the DEF itself does not move), i.e. the capture's own jitter for that joint."""
        out = {}
        for g in groups:
            for n, r in self.joints_at(np.array(sorted(g))).items():
                out[n] = max(out.get(n, 0.0), r["range"])
        return out

    def joints_at(self, idx: np.ndarray) -> dict:
        X = self.P[idx]
        out = {}
        for j, n in enumerate(self.names):
            p = self.parents[j]
            if p < 0 or j not in self.child:
                continue
            c = self.child[j][0]
            k = kind_of(n)
            if k == "hinge":
                ser = ang(X[:, j] - X[:, p], X[:, c] - X[:, j])
            else:
                F = self.torso(X, arm=not n.endswith("UpLeg"))
                if F is None:
                    continue
                ser = np.einsum("tij,tj->ti", F, X[:, c] - X[:, j])
            r, st = measure(ser, k)
            out[n] = {"kind": k, "range": r, "step": st}
        return out


def def_static_groups(ref: dict, cap: Capture) -> tuple[list[list[int]], dict]:
    """Groups of capture (global master) frames whose DEF PNGs are pixel-identical or near-identical (fewer than
    STATIC_DIFF_FRAC of the sprite's pixels differ by more than STATIC_DIFF_LEVEL in any channel); union-find over
    every pair of exported DEF frames, any clip. CPU: ~60 small crops, a few hundred ms."""
    from PIL import Image
    gidx, imgs = [], []
    for c in ref["clips"]:
        seg = cap.segments.get(c["clipKey"])
        if not seg:
            continue
        for i, png in enumerate(c["frames"]):
            gidx.append(seg["globalStart"] + i)
            imgs.append(np.asarray(Image.open(png).convert("RGBA")).astype(np.int16))
    if not imgs:
        return [], {}
    A = np.stack([im[..., 3] > 0 for im in imgs]).any(0)
    ys, xs = np.nonzero(A)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crops = np.stack([im[y0:y1, x0:x1] for im in imgs])
    area = max(1, int((crops[..., 3] > 0).any(0).sum()))
    par = list(range(len(crops)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for a in range(len(crops) - 1):
        diff = (np.abs(crops[a + 1:] - crops[a]) > STATIC_DIFF_LEVEL).any(-1).reshape(len(crops) - a - 1, -1).sum(1)
        for b in np.nonzero(diff < STATIC_DIFF_FRAC * area)[0]:
            par[find(a)] = find(a + 1 + int(b))
    groups = {}
    for k in range(len(crops)):
        groups.setdefault(find(k), []).append(gidx[k])
    gl = [g for g in groups.values() if len(g) > 1]
    return gl, {"groups": len(gl), "framesInGroups": sum(len(g) for g in gl), "framesTotal": len(crops),
                "rule": f"< {STATIC_DIFF_FRAC:.1%} of {area} sprite px differ by > {STATIC_DIFF_LEVEL}/255"}


# ---------------------------------------------------------------- ours (GLB)
class Ours:
    def __init__(self, path: Path, body: str):
        self.sc = Scene(path, body_name=body)
        sc = self.sc
        self.jn = [sc.nodes[j].get("name", str(j)) for j in sc.joints]
        self.jix = {n: k for k, n in enumerate(self.jn)}
        self.ibm_inv = np.linalg.inv(sc.ibm)
        node2k = {j: k for k, j in enumerate(sc.joints)}
        self.parent = {}
        for k, j in enumerate(sc.joints):
            p = sc.parent.get(j)
            self.parent[k] = node2k.get(p) if p is not None else None
        own = np.zeros(len(self.jn))
        np.add.at(own, sc.J.ravel(), sc.W.ravel())
        self.own_weight = own
        kids = {}
        for k, p in self.parent.items():
            if p is not None:
                kids.setdefault(p, []).append(k)
        sub = {}

        def subtree(k):
            if k not in sub:
                sub[k] = own[k] + sum(subtree(c) for c in kids.get(k, []))
            return sub[k]
        self.subtree_weight = np.array([subtree(k) for k in range(len(self.jn))])

    def torso_anc(self, k: int) -> int | None:
        p = self.parent[k]
        while p is not None and not TORSO.match(self.jn[p]):
            p = self.parent[p]
        return p

    def sample(self, clip: str, times) -> np.ndarray:
        Jm, _ = self.sc.pose(clip, np.asarray(times, np.float64))
        return Jm @ self.ibm_inv[None]                     # (T, J, 4, 4) world transforms of the joints

    def measure_bone(self, G: np.ndarray, name: str, kind: str) -> dict | None:
        k = self.jix.get(name)
        if k is None:
            return None
        R = G[:, k, :3, :3]
        y = R[:, :, 1] / np.maximum(np.linalg.norm(R[:, :, 1], axis=-1, keepdims=True), 1e-12)   # outgoing (+Y)
        if kind == "hinge":
            p = self.parent[k]
            if p is None:
                return None
            inc = G[:, k, :3, 3] - G[:, p, :3, 3]
            if np.linalg.norm(inc, axis=-1).min() < 1e-9:           # coincident heads: use the parent's +Y
                inc = G[:, p, :3, 1]
            ser = ang(inc, y)
        else:
            a = self.torso_anc(k)
            if a is None:
                return None
            Ra = G[:, a, :3, :3]
            Ra = Ra / np.maximum(np.linalg.norm(Ra, axis=-2, keepdims=True), 1e-12)   # drop scale per column
            ser = np.einsum("tji,tj->ti", Ra, y)                                    # y in the torso frame
        r, st = measure(ser, kind)
        return {"bone": name, "range": r, "step": st, "subtreeWeight": float(self.subtree_weight[k])}

    def animated(self, G: np.ndarray, k: int) -> bool:
        p = self.parent[k]
        L = G[:, k] if p is None else np.linalg.inv(G[:, p]) @ G[:, k]
        return bool(np.abs(L - L[:1]).max() > 1e-4)


# ---------------------------------------------------------------- mapping
def mapping(cfg: dict, ours: Ours, cap_names: list[str]) -> tuple[dict, list[str]]:
    notes = []
    chains = {}
    for ch in cfg.get("staticChains", []):
        m = MOUNT_CHAIN.match(ch["prefix"])
        if m:
            chains.setdefault(m.group(2), []).append(ch["prefix"])
    mount = bool(chains) and "castle_mount" in (cfg.get("extensions") or [])
    if mount:
        notes.append("mountProxy: capture legs -> same-side horse legs (front and hind), ours = the most-moving one")
    if cfg.get("quadruped"):
        notes.append("quadruped config: the capture is a human skeleton fitted to a creature sprite; its limbs are a "
                     "proxy for the creature's legs even where the bone names match")
    out = {}
    for n in cap_names:
        if n in ours.jix:
            out[n] = {"via": "name", "bones": [n]}
            continue
        m = re.match(r"^(Left|Right)(UpLeg|Leg|Foot)$", n)
        if mount and m:
            idx = {"UpLeg": 0, "Leg": 1, "Foot": 2}[m.group(2)]
            bones = [f"{pre}{idx}" for pre in chains.get(m.group(1)[0], []) if f"{pre}{idx}" in ours.jix]
            if bones:
                out[n] = {"via": "mountProxy", "bones": bones}
                continue
        if mount and re.match(r"^(Left|Right)(ToeBase|Toe_End)$", n):
            out[n] = {"via": "skip", "bones": [], "reason": "no horse counterpart of a rider's toe"}
            continue
        out[n] = {"via": "none", "bones": []}
    return out, notes


def flag(ref: float, ours: float | None, weighted: bool, ref_min: float) -> str:
    if ref < ref_min or (ours is not None and weighted and ref - ours < MIN_GAP_DEG):
        return "OK"
    if ours is None or not weighted:
        return "MISSING"
    if ours < STILL_DEG or ours < STATIC_RATIO * ref:
        return "STATIC"
    if ours < WEAK_RATIO * ref:
        return "WEAK"
    return "OK"


# ---------------------------------------------------------------- DEF keypoint reference
def peak_frame(a: np.ndarray, sign: float | None = None) -> tuple[int, float]:
    """Frame of the largest excursion from the median (finite entries); sign forces the direction."""
    dev = a - np.nanmedian(a)
    if sign is None:
        k = int(np.nanargmax(np.abs(dev)))
        return k, float(np.sign(dev[k]) or 1.0)
    return int(np.nanargmax(sign * dev)), sign


def def_rows(kp: dict, op, G: np.ndarray, ck: str, n: int, loop: bool) -> tuple[list[dict], set]:
    """Rows for every interior chain point (a joint): DEF 2D bend range vs ours, projected through the sprite
    camera at the DEF frame times. Returns the rows and the bones whose rotation a measured DEF joint covers."""
    dp = KP.def_points(kp, ck, n)
    o2 = op.chains_2d(kp, G)
    rows, covered = [], set()
    for name, ch in kp["chains"].items():
        pts, bones = ch["points"], ch.get("bones", {})
        da = KP.bend_series(dp[name])                       # (n, P-2)
        oa = KP.bend_series(o2[name])
        seg = np.linalg.norm(np.diff(dp[name], axis=1), axis=-1)   # (n, P-1)
        for j in range(1, len(pts) - 1):
            specs = [bones.get(pts[j - 1]), bones.get(pts[j]), bones.get(pts[j + 1])]
            ok = np.isfinite(da[:, j - 1])
            row = {"ref": "def", "joint": f"{name}.{pts[j]}", "kind": "bend2d",
                   "bones": [b for b in specs if b], "defFrames": int(ok.sum())}
            if ok.sum() < 2:
                row.update(flag="NODATA", refDeg=None, oursDeg=None, ratio=None)
                rows.append(row)
                continue
            d = KP.unwrap_deg(da[:, j - 1])
            ref = KP.circ_range(d)
            L = float(np.nanmedian(np.minimum(seg[:, j - 1], seg[:, j])[ok]))
            noise = math.degrees(2 * MARK_SIGMA_PX / max(L, 1e-6))
            ref_min = max(DEF_REF_MIN_DEG, 2 * noise)
            missing = None
            if None in specs:
                missing = "no bone for " + ", ".join(p for p, b in zip(pts[j - 1:j + 2], specs) if not b)
            else:
                common = op.frames_of(specs[0]) & op.frames_of(specs[1]) & op.frames_of(specs[2])
                if common:
                    missing = "rigid: all three points sit on " + "/".join(op.jn[k] for k in sorted(common))
            row.update(refDeg=round(ref, 1), segPx=round(L, 1), noiseDeg=round(noise, 1),
                       refMinDeg=round(ref_min, 1))
            if missing:
                f = "OK" if ref < ref_min else "MISSING"
                row.update(oursDeg=None, ratio=None, flag=f, missing=missing)
                rows.append(row)
                continue
            r = op.resolve(specs[1])
            if r and r[1] is None:
                covered.add(op.jn[r[0]])           # the joint's rotation is this bone's (its head is the pivot)
            o = KP.unwrap_deg(np.where(ok, oa[:, j - 1], np.nan))
            ours = KP.circ_range(o)
            oseg = np.linalg.norm(np.diff(o2[name][:, j - 1:j + 2], axis=1), axis=-1)[ok]
            row["oursSegPx"] = round(float(np.nanmedian(np.min(oseg, axis=1))), 1)
            # the bone that bends this joint must carry skin
            kb = r[0] if r else None
            weighted = kb is None or op.subtree[kb] >= MIN_SUBTREE_WEIGHT
            f = flag(ref, ours, weighted, ref_min)
            row.update(oursDeg=round(ours, 1), ratio=round(ours / ref, 2) if ref > 1e-6 else None, flag=f)
            if f in ("OK", "WEAK") and ref >= ref_min and ours >= STILL_DEG:
                pk, sg = peak_frame(d)
                po, _ = peak_frame(o, sg)
                lag = abs(po - pk)
                if loop:
                    lag = min(lag, n - lag)
                row["timing"] = {"defPeak": pk, "oursPeak": po, "lagFrames": lag}
                if lag > TIMING_FRAMES:
                    row["timingFlag"] = True
            rows.append(row)
    return rows, covered


# ---------------------------------------------------------------- main
def run(a) -> dict:
    t0 = time.perf_counter()
    lab, src = unit_ids(a.unit)
    if a.glb:
        p = Path(a.glb).resolve()
        if not p.is_file():
            raise SystemExit(f"--glb {p} does not exist")
        sel = {"mode": "override", "path": p, "sha256": sha256(p), "notes": ["--glb override: a candidate"]}
    else:
        sel = shipped_glb(lab, src)
    cfgp = UNITS / f"{src}.json"
    cfg = load(cfgp) if cfgp.is_file() else {}
    ref = def_reference(src)
    cap = Capture(src)
    ours = Ours(sel["path"], src)
    mp, notes = mapping(cfg, ours, [n for j, n in enumerate(cap.names) if cap.parents[j] >= 0 and j in cap.child])
    groups, ginfo = def_static_groups(ref, cap)
    noise = cap.noise_floor(groups)
    kp = KP.load_kp(lab, must=False)
    view = (kp or {}).get("view") or {}
    vy = a.view_yaw if a.view_yaw is not None else view.get("yawDeg")
    align = a.align or view.get("align") or "clip"
    op = KP.OursPoints(None, src, ref, vy, scene=ours.sc) if kp else None
    if kp:
        notes.append(f"DEF keypoint reference: {KP.kp_path(lab).relative_to(ROOT).as_posix()} ({len(kp['chains'])} chains), "
                     f"ours projected through the sprite camera at view yaw {vy} (align {align}: 2D bend angles are "
                     "invariant to the board's similarity fit); capture rows whose bone a measured DEF joint covers "
                     "are kept in the JSON as supersededBy=def and not flagged")
    want = {c.strip() for c in a.clips.split(",")} if a.clips else None
    clips, zero_w = {}, {}
    for c in ref["clips"]:
        if want and not ({c["clip"], c["clip"][5:], c["clipKey"]} & want):
            continue
        if c["clip"] not in ours.sc.anims or c["clipKey"] not in cap.segments:
            clips[c["clip"][5:]] = {"skipped": "clip missing in GLB or capture"}
            continue
        rng = ours.sc.clip_range(c["clip"])
        n = len(c["frames"])
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if c.get("loop") else 0)
        step = rng["duration"] / m if m > 0 else 1 / 12
        times = [rng["start"] + i * step for i in range(n)]
        G = ours.sample(c["clip"], times)
        cj = cap.joints(c["clipKey"])
        drows, covered = def_rows(kp, op, G, c["clipKey"], n, bool(c.get("loop"))) if kp else ([], set())
        rows = []
        for jn, r in cj.items():
            mm = mp.get(jn, {"via": "none", "bones": []})
            if mm["via"] == "skip":
                continue
            meas = [x for x in (ours.measure_bone(G, b, r["kind"]) for b in mm["bones"]) if x]
            best = max(meas, key=lambda x: x["range"]) if meas else None
            weighted = bool(best) and best["subtreeWeight"] >= MIN_SUBTREE_WEIGHT
            ref_min = (REF_MIN_SHORT_DEG if jn.endswith(SHORT_JOINTS)
                       else REF_MIN_SWING_DEG if r["kind"] == "swing" else REF_MIN_DEG)
            nz = noise.get(jn, 0.0)
            ref_min = max(ref_min, nz + MIN_GAP_DEG) if nz > 0 else ref_min
            f = flag(r["range"], best["range"] if best else None, weighted, ref_min)
            sup = "def" if covered & set(mm["bones"]) else None
            rows.append({"ref": "capture", "supersededBy": sup, "noiseDeg": round(nz, 1), "refMinDeg": round(ref_min, 1),
                         "joint": jn, "kind": r["kind"], "via": mm["via"], "bones": mm["bones"],
                         "refDeg": round(r["range"], 1), "refStepDeg": round(r["step"], 1),
                         "oursDeg": round(best["range"], 1) if best else None,
                         "oursStepDeg": round(best["step"], 1) if best else None,
                         "oursBone": best["bone"] if best else None,
                         "perBoneDeg": {x["bone"]: round(x["range"], 1) for x in meas} if len(meas) > 1 else None,
                         "subtreeWeight": round(best["subtreeWeight"], 1) if best else None,
                         "ratio": round(best["range"] / r["range"], 2) if best and r["range"] > 1e-6 else None,
                         "flag": f})
        # rig bones with no capture counterpart (horse chains, wings, tails): ours only, for the eye
        mapped = {b for v in mp.values() for b in v["bones"]}
        extra = {}
        for k, b in enumerate(ours.jn):
            if b in mapped or b == "Root" or ours.parent[k] is None:
                continue
            x = ours.measure_bone(G, b, "hinge")
            if x:
                extra[b] = round(x["range"], 1)
            if ours.own_weight[k] < MIN_SUBTREE_WEIGHT * 0.2 and ours.animated(G, k):
                zero_w.setdefault(b, []).append(c["clip"][5:])
        clips[c["clip"][5:]] = {"clipKey": c["clipKey"], "defFrames": n, "times": [round(t, 4) for t in times],
                                "rows": rows + drows, "unmappedRigBonesDeg": extra}
    rec = {"schema": SCHEMA, "unit": a.unit, "labSid": lab, "sourceUnit": src,
           "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "glb": {"mode": sel["mode"], "path": str(Path(sel["path"]).resolve()), "sha256": sel["sha256"],
                   "notes": sel.get("notes", [])},
           "capture": str(cap.path.relative_to(ROOT).as_posix()), "unitConfig": cfgp.relative_to(ROOT).as_posix(),
           "mapping": mp, "mappingNotes": notes,
           "captureNoise": {"staticGroups": ginfo, "perJointDeg": {k: round(v, 1) for k, v in sorted(noise.items())}},
           "defKeypoints": ({"file": KP.kp_path(lab).relative_to(ROOT).as_posix(), "viewYawDeg": vy, "align": align,
                             "chains": {k: {"points": v["points"], "bones": v.get("bones", {}), "missing": v.get("missing")}
                                        for k, v in kp["chains"].items()},
                             "tipOffsets": {f"{op.jn[k]}@{m}": [round(float(x), 4) for x in v] for (k, m), v in op._tip.items()}}
                            if kp else None),
           "zeroWeightBones": {b: {"ownWeight": round(float(ours.own_weight[ours.jix[b]]), 2), "animatedIn": v}
                               for b, v in zero_w.items()},
           "thresholds": {"REF_MIN_DEG": REF_MIN_DEG, "REF_MIN_SHORT_DEG": REF_MIN_SHORT_DEG,
                          "REF_MIN_SWING_DEG": REF_MIN_SWING_DEG, "MIN_GAP_DEG": MIN_GAP_DEG,
                          "SHORT_JOINTS": SHORT_JOINTS, "STATIC_RATIO": STATIC_RATIO, "WEAK_RATIO": WEAK_RATIO,
                          "STILL_DEG": STILL_DEG, "MIN_SUBTREE_WEIGHT": MIN_SUBTREE_WEIGHT,
                          "STATIC_DIFF_LEVEL": STATIC_DIFF_LEVEL, "STATIC_DIFF_FRAC": STATIC_DIFF_FRAC,
                          "MARK_SIGMA_PX": MARK_SIGMA_PX, "DEF_REF_MIN_DEG": DEF_REF_MIN_DEG, "TIMING_FRAMES": TIMING_FRAMES},
           "silhouetteEvidence": "not implemented (see module docstring)",
           "clips": clips}
    rec["perf"] = {"wallSeconds": round(time.perf_counter() - t0, 2), "peakRssMB": peak_rss_mb()}
    return rec


def peak_rss_mb():
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return round(getattr(mi, "peak_wset", mi.rss) / 2 ** 20, 1)
    except Exception:  # pragma: no cover
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit")
    ap.add_argument("--glb", help="measure this candidate GLB instead of the shipped one")
    ap.add_argument("--out", help="JSON path (default V:/olden_port_work/authenticity/<labSid>/joint_coverage.json)")
    ap.add_argument("--clips", help="comma list: Unit_Idle / Idle / g02_idle")
    ap.add_argument("--view-yaw", type=float, help="DEF view for the keypoint rows (board --view-yaw); default: the "
                    "keypoint file's view.yawDeg")
    ap.add_argument("--align", choices=("clip", "idle"), help="recorded with the keypoint rows (board --align); bend "
                    "angles do not depend on it")
    a = ap.parse_args(argv)
    rec = run(a)
    out = Path(a.out) if a.out else Path("V:/olden_port_work/authenticity") / rec["labSid"] / "joint_coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"JOINT COVERAGE {rec['labSid']}  glb {rec['glb']['mode']} {Path(rec['glb']['path']).name} "
          f"{rec['glb']['sha256'][:10]}  -> {out}")
    for n in rec["mappingNotes"]:
        print("NOTE:", n)
    print(f"{'clip':12s} {'ref':7s} {'joint':24s} {'bone(s)':26s} {'ref':>6s} {'ours':>6s} {'ratio':>5s}  flag")
    nbad = {"capture": 0, "def": 0}
    for cl, c in rec["clips"].items():
        for r in c.get("rows", []):
            bad = r["flag"] not in ("OK", "NODATA") or r.get("timingFlag")
            if not bad or r.get("supersededBy"):
                continue
            nbad[r["ref"]] += 1
            if r["ref"] == "capture":
                bones = r["oursBone"] or ",".join(r["bones"]) or "-"
                if r["via"] == "mountProxy":
                    bones = f"{bones} (mount)"
            else:
                bones = ",".join(r["bones"]) or "-"
            fl = r["flag"] + (f" TIMING(def f{r['timing']['defPeak']} ours f{r['timing']['oursPeak']})"
                              if r.get("timingFlag") else "")
            if r.get("missing") and r["flag"] == "MISSING":
                fl += f" [{r['missing']}]"
            print(f"{cl:12s} {r['ref']:7s} {r['joint']:24s} {bones[:26]:26s} {r['refDeg']:6.1f} "
                  f"{'-' if r['oursDeg'] is None else format(r['oursDeg'], '6.1f'):>6s} "
                  f"{'-' if r['ratio'] is None else format(r['ratio'], '.2f'):>5s}  {fl}")
    if rec["zeroWeightBones"]:
        print("animated bones with ~zero skin weight:", ", ".join(rec["zeroWeightBones"]))
    print(f"non-OK rows: capture {nbad['capture']}, def {nbad['def']}  wall {rec['perf']['wallSeconds']} s  peak RSS {rec['perf']['peakRssMB']} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
