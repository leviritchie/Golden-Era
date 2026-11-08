"""Haiku anim bench core: the unit (GLB + DEF reference), the micro-edit stack and its exact track math (numpy).

The edit math is the GLB patch lane's own (tools/homm3_glb_patch/patch_glb.py):
  rotation edit    -> keyRotations: post-multiply the bone's local rotation keys by a per-key offset quaternion on the
                      clip's key grid (a sparse STEP/2-key channel is regridded onto the clip grid first, exactly as
                      `regrid: true` does: resample_rot, then written LINEAR);
  root translation -> keyTranslations: add a per-key [dx, dy, dz] (parent-local units) to the Hips translation keys.
The bench samples the edited channels with the same glTF sampler the board uses (gltf_scene.sample_channel), so the
bench pose, the exported GLB (export.py, written by patch_glb's own op code) and the three.js viewer (same per-key
offsets, same slerp) show one motion.

An edit's offset at key time t is axis-angle(axisLocal, deg * w(t)), w a raised-cosine bump in DEF-frame units:
w = 0.5 (1 + cos(pi d / hw)) for d < hw (d = |t - tc| / step, cyclic over the clip period for Idle/Move loops so the
loop seam stays continuous), 0 beyond; hw = 0 touches the centre key only. Several edits on one bone compose in stack
order (q = q1 q2 ...), the same as successive keyRotations ops.
Axes are given in the body frame (glTF: +Y up, the unit faces +Z, +X is its own left) and converted once, at edit
creation, to the bone-local axis that turns the bone about that body axis at the edit's centre frame
(axisLocal = R_global(bone, tc)^-1 * axis). pitch+ = nose down (about +X), yaw+ = turn to the unit's left (about +Y),
roll+ = top tilts to the unit's right (about +Z).
CPU joint hierarchy (25 joints x a few dozen times, inherently sequential, ~1 ms); per-vertex work is on the GPU
(anim_gl.py). skin_cpu / edge_stretch_cpu are the parity reference only.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/homm3_authenticity"))
sys.path.insert(0, str(ROOT / "tools/homm3_glb_patch"))
from gltf_scene import Scene, _quat_to_mat, sample_channel  # noqa: E402
from sources import def_reference  # noqa: E402
from spritecam import sprite_camera  # noqa: E402
from patch_glb import STRETCH_RATIO, WORST_STRETCH_SLACK, resample_rot  # noqa: E402  (the lane's own gate + regrid)

SCRATCH = Path("V:/olden_port_work/haiku_anim")
AXES = {"pitch": np.array([1.0, 0, 0]), "yaw": np.array([0, 1.0, 0]), "roll": np.array([0, 0, 1.0])}
MAX_DEG = 120.0         # one part's peak angle (2026-10-07: freedom, big moves allowed; mistakes are undone)
MAX_HW = 6.0            # DEF frames
HW_ALL = 1.0e6          # "hw": "all" -> the same offset at every key of the clip (whole-clip attitude, e.g. a level body)
MIN_HW = 1.0            # no single-key spikes: an edit always reaches its neighbour keys (2026-10-07 run3 rule)
MAX_TR_H = 0.6          # one translation part, x body height
ROOT_BONE = "Hips"
MOVE_CLIPS = ("Unit_Move", "Unit_MoveStart", "Unit_MoveEnd")
EPS_T = 1e-5
CAP_ROT_DEG = 100.0     # composite offset per bone per key (lane refuses > 120)
CAP_TR_H = 0.2          # composite root translation per key, x H (lane refuses > 0.25)
NET_MAX_DEG = 120.0     # a joint's NET offset per key (net stack: stacking cannot run away)
NET_MAX_TR_H = 0.6      # a joint's NET translation per key, x H
_SIDE = (("Left", "left "), ("Right", "right "), ("L_", "left "), ("R_", "right "))


def friendly(bone: str) -> str:
    """Generic words for a bone name (no per-unit tables): WingL_01 -> 'left wing 01', LeftUpLeg -> 'left up leg'."""
    b = bone
    side = ""
    m = re.match(r"^(.*?)(L|R)_(\d+)$", b)
    if m:
        return f"{'left' if m.group(2) == 'L' else 'right'} {friendly(m.group(1)).strip()} {m.group(3)}"
    for k, w in _SIDE:
        if b.startswith(k):
            side, b = w, b[len(k):]
            break
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", b).lower().split()
    return (side + " ".join(words)).strip() or bone


def qmul(a, b):
    """Hamilton product of xyzw quaternions, broadcasting (stride_gait.qmul / patch_glb.qmul formula)."""
    a = np.asarray(a, np.float64); b = np.asarray(b, np.float64)
    ax, ay, az, aw = np.moveaxis(a, -1, 0); bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def axis_angle(axis, rad):
    """(K,) angles about one unit axis -> (K, 4) xyzw."""
    axis = np.asarray(axis, np.float64); axis = axis / np.linalg.norm(axis)
    rad = np.asarray(rad, np.float64)
    s = np.sin(rad / 2)[..., None]
    return np.concatenate([axis * s, np.cos(rad / 2)[..., None]], -1)


def bump(t, tc, hw_t, period):
    """Raised-cosine weight of key times t around tc with half width hw_t (seconds); cyclic when period > 0."""
    d = np.abs(np.asarray(t, np.float64) - tc)
    if period > 0:
        d = np.mod(d, period)
        d = np.minimum(d, period - d)
    if hw_t >= 1e5:
        return np.ones_like(d)
    if hw_t <= EPS_T:
        return (d < 1e-4).astype(np.float64)
    return np.where(d < hw_t, 0.5 * (1 + np.cos(np.pi * np.clip(d / hw_t, 0, 1))), 0.0)


class Unit:
    def __init__(self, unit: str, glb: Path):
        self.unit = unit
        self.glb = Path(glb)
        self.scene = Scene(self.glb, body_name=unit)
        s = self.scene
        self.names = [n.get("name") for n in s.nodes]
        self.jnames = [self.names[j] for j in s.joints]
        self.H = float(s.P[:, 1].max() - s.P[:, 1].min())
        self.ref = def_reference(unit)
        self.spritecam = sprite_camera(self.ref["spritecam"], (s.extras.get("homm3DefRetargetDeliveryDeyaw") or {}).get("yawDeg"))
        self.clips = {}
        for c in self.ref["clips"]:
            if c["clip"] in s.anims:
                self.clips[c["clip"]] = dict(c, **self._timing(c))
        # edges (patch_glb.edge_stretch: unique sorted face edges with rest length > 1e-6)
        F = s.F
        E = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1), axis=0)
        L = np.linalg.norm(s.P[E[:, 0]] - s.P[E[:, 1]], axis=1)
        self.edges, self.rest_len = E[L > 1e-6], L[L > 1e-6]
        self._gaze_setup()

    def refresh(self):
        """After a rig/mesh replay (rig.RigEditor.apply): names, joint list and edge rest lengths from the scene. The
        edge SET stays the pristine one (topology never changes); the gaze ray stays bound to Head's pristine axis."""
        s = self.scene
        self.names = [n.get("name") for n in s.nodes]
        self.jnames = [self.names[j] for j in s.joints]
        self.rest_len = np.maximum(np.linalg.norm(s.P[self.edges[:, 0]] - s.P[self.edges[:, 1]], axis=1), 1e-9)

    def cap_violations(self, clip: str, edits: list[dict]) -> list[str]:
        """The patch lane's per-key table limits on the composite offsets (with a margin): rotation <= CAP_ROT_DEG,
        root translation <= CAP_TR_H x body height (keyTranslations refuses past 0.25 H; run3 hit 1.05 H)."""
        rq, td = self.offsets(clip, edits)
        bad = []
        for b, q in rq.items():
            ang = float(np.degrees(2 * np.arccos(np.clip(np.abs(q[:, 3]), 0, 1))).max())
            if ang > CAP_ROT_DEG:
                bad.append(f"{b} would be turned too far from the original")
        for b, d in td.items():
            if float(np.linalg.norm(d, axis=1).max()) > CAP_TR_H * self.H:
                bad.append(f"{b} would be moved too far from the original")
        return bad

    # ---------------------------------------------------------------- timing (board.py rule)
    def _timing(self, c: dict) -> dict:
        s = self.scene
        rng = s.clip_range(c["clip"])
        n = len(c["frames"])
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if c.get("loop") else 0)
        step = rng["duration"] / m if m > 0 else 1 / 12
        dense = [ti for p, nd, ti, vo, it in s.channels[c["clip"]] if len(ti) > 2]
        grid = max(dense, key=len) if dense else np.array([rng["start"], rng["end"]])
        for ti in dense:
            if len(ti) != len(grid) or np.abs(ti - grid).max() > EPS_T:
                grid = np.unique(np.concatenate([grid, ti]))
        return {"start": rng["start"], "end": rng["end"], "duration": rng["duration"], "n": n, "isLoop": bool(c.get("loop")),
                "m": m, "step": step, "period": rng["duration"] if c.get("loop") else 0.0,
                "times": [rng["start"] + i * step for i in range(n)], "grid": np.asarray(grid, np.float64)}

    def frame_time(self, clip: str, f: float) -> float:
        c = self.clips[clip]
        return c["start"] + float(f) * c["step"]

    # ---------------------------------------------------------------- edits -> channels
    def edited_channels(self, clip: str, edits: list[dict]) -> list:
        """The clip's channel list with every edit of this clip baked in (patch_glb keyRotations/keyTranslations)."""
        base = self.scene.channels[clip]
        mine = [e for e in edits if e["clip"] == clip]
        if not mine:
            return base
        c = self.clips[clip]
        grid = c["grid"]
        rq, td = self.offsets(clip, mine)
        rot_q = {self.names.index(b): q for b, q in rq.items()}
        tr_d = {self.names.index(b): d for b, d in td.items()}
        out = []
        for path, node, ti, vo, it in base:
            if path in ("rotation", "translation") and (node in rot_q if path == "rotation" else node in tr_d)                     and it not in ("LINEAR", "STEP"):
                raise ValueError(f"{clip} {self.names[node]} {path} is {it}; LINEAR and STEP only (patch lane rule)")
            if path == "rotation" and node in rot_q:
                r = vo.reshape(len(ti), 4)
                r = r / np.linalg.norm(r, axis=1, keepdims=True)
                if len(ti) != len(grid) or np.abs(ti - grid).max() > EPS_T:
                    r, ti, it = resample_rot(ti, r, grid, it), grid, "LINEAR"
                out.append((path, node, ti, qmul(r, rot_q[node]), it))
            elif path == "translation" and node in tr_d:
                v = vo.reshape(len(ti), 3)
                if len(ti) != len(grid) or np.abs(ti - grid).max() > EPS_T:
                    if it == "STEP":
                        j = np.clip(np.searchsorted(ti, grid + EPS_T, side="right") - 1, 0, len(ti) - 1)
                        v = v[j]
                    else:
                        v = np.stack([np.interp(grid, ti, v[:, k]) for k in range(3)], 1)
                    ti, it = grid, "LINEAR"
                out.append((path, node, ti, v + tr_d[node], it))
            else:
                out.append((path, node, ti, vo, it))
        return out

    def _raw_offsets(self, clip: str, edits: list[dict]):
        """Composite offsets BEFORE the loop-seam bridge: (grid_ext, {bone: (K', 4)}, {bone: (K', 3)}, bridge). On a loop
        clip with transition keys grid_ext = grid + [t_last, t_wrap] (K' = K + 2). Kinds: "rot" (a bump), "tr" (a bump),
        "net" / "nettr" (a collapsed per-key value on grid_ext, see net_collapse)."""
        c = self.clips[clip]
        grid = np.asarray(c["grid"], np.float64)
        bridge = None
        if c["isLoop"] and c["period"] > 0:
            t_last, t_wrap = self.frame_time(clip, c["n"] - 1), c["start"] + c["period"]
            k = np.nonzero((grid > t_last + EPS_T) & (grid < t_wrap - EPS_T))[0]
            if len(k):
                bridge = (k, (grid[k] - t_last) / (t_wrap - t_last))
                grid = np.r_[grid, t_last, t_wrap]          # two extra evaluation times, dropped after the bridge
        rq, td = {}, {}
        for e in edits:
            if e["clip"] != clip:
                continue
            if e["kind"] == "net":
                q = np.asarray(e["q"], np.float64).reshape(-1, 4)
                if len(q) != len(grid):
                    raise ValueError(f"net offset for {e['bone']} has {len(q)} keys, the clip grid {len(grid)}")
                rq[e["bone"]] = qmul(rq[e["bone"]], q) if e["bone"] in rq else q
                continue
            if e["kind"] == "nettr":
                d = np.asarray(e["d"], np.float64).reshape(-1, 3)
                td[e["bone"]] = td[e["bone"]] + d if e["bone"] in td else d
                continue
            w = bump(grid, self.frame_time(clip, e["frame"]), e["hw"] * c["step"], c["period"])
            if e["kind"] == "rot":
                q = axis_angle(e["axisLocal"], np.radians(e["deg"]) * w)
                rq[e["bone"]] = qmul(rq[e["bone"]], q) if e["bone"] in rq else q
            else:
                d = np.asarray(e["deltaLocal"], np.float64)[None] * w[:, None]
                td[e["bone"]] = td[e["bone"]] + d if e["bone"] in td else d
        return grid, rq, td, bridge

    def offsets(self, clip: str, edits: list[dict]) -> tuple[dict, dict]:
        """Per bone composite offsets on the clip grid: ({bone: (K, 4) xyzw}, {bone: (K, 3) local delta}).
        Edits compose in stack order. On loop clips the transition keys between the last DEF frame and the loop wrap
        are bridged: their offset is the slerp/lerp between the offsets at the last DEF frame and at the wrap (= f0),
        so the seam follows the edits instead of snapping back to the original pose. viewer.html mirrors this."""
        _, rq, td, bridge = self._raw_offsets(clip, edits)
        rq = {b: q.copy() for b, q in rq.items()}
        td = {b: d.copy() for b, d in td.items()}
        if bridge is not None:
            k, a = bridge
            for b, q in rq.items():
                q0, q1 = q[-2], q[-1] * (1 if np.dot(q[-2], q[-1]) >= 0 else -1)
                for kk, aa in zip(k, a):
                    v = (1 - aa) * q0 + aa * q1              # nlerp == slerp to < 1e-3 deg at these offset sizes
                    q[kk] = v / np.linalg.norm(v)
                rq[b] = q[:-2]
            for b, d in td.items():
                for kk, aa in zip(k, a):
                    d[kk] = (1 - aa) * d[-2] + aa * d[-1]
                td[b] = d[:-2]
        return rq, td

    def net_collapse(self, kept: list[dict], ids: dict, new_id) -> list[dict]:
        """The kept stack collapsed to ONE net offset per (clip, bone, rotation|translation), exact on every grid key
        (it is the stack's own composite, pre-bridge, so the seam bridge still follows it). A net rotation is limited
        to NET_MAX_DEG per key and a net translation to NET_MAX_TR_H x H (stacking cannot run away). `ids` maps
        (clip, bone, kind) -> the id that net had before; new_id() hands out a fresh one."""
        out = []
        for clip in sorted({e["clip"] for e in kept}, key=lambda c: [e["clip"] for e in kept].index(c)):
            mine = [e for e in kept if e["clip"] == clip]
            _, rq, td, _ = self._raw_offsets(clip, mine)
            why = {}
            for e in mine:
                why.setdefault((e["bone"], "tr" if e["kind"] in ("tr", "nettr") else "rot"), []).append(e.get("why", ""))
            for b, q in rq.items():
                q = q / np.linalg.norm(q, axis=1, keepdims=True)
                q = q * np.where(q[:, 3:4] < 0, -1.0, 1.0)
                ang = 2 * np.arccos(np.clip(q[:, 3], -1, 1))
                lim = np.radians(NET_MAX_DEG)
                over = ang > lim
                if over.any():
                    ax = q[over, :3] / np.maximum(np.linalg.norm(q[over, :3], axis=1, keepdims=True), 1e-12)
                    q[over] = np.c_[ax * np.sin(lim / 2), np.full(over.sum(), np.cos(lim / 2))]
                if float(ang.max()) < np.radians(0.05):
                    continue
                key = (clip, b, "rot")
                out.append({"kind": "net", "clip": clip, "bone": b, "q": np.round(q, 9).tolist(),
                            "id": ids.get(key) or new_id(), "why": (why.get((b, "rot")) or [""])[-1]})
            for b, d in td.items():
                n = np.linalg.norm(d, axis=1, keepdims=True)
                lim = NET_MAX_TR_H * self.H
                d = np.where(n > lim, d * lim / np.maximum(n, 1e-12), d)
                if float(n.max()) < 1e-4 * self.H:
                    continue
                key = (clip, b, "tr")
                out.append({"kind": "nettr", "clip": clip, "bone": b, "d": np.round(d, 9).tolist(),
                            "id": ids.get(key) or new_id(), "why": (why.get((b, "tr")) or [""])[-1]})
        return out

    def pose(self, clip: str, times, edits: list[dict] | None = None):
        """(G (T, nodes, 4, 4) global node matrices, Jm (T, J, 4, 4) = G[joints] @ IBM, mw (T, M)) -- gltf_scene.pose
        on the edited channels."""
        s = self.scene
        chans = self.edited_channels(clip, edits or [])
        times = np.asarray(times, np.float64)
        T, nn = len(times), len(s.nodes)
        tr = np.broadcast_to(np.array([r[0] for r in s.rest]), (T, nn, 3)).copy()
        ro = np.broadcast_to(np.array([r[1] for r in s.rest]), (T, nn, 4)).copy()
        sc = np.broadcast_to(np.array([r[2] for r in s.rest]), (T, nn, 3)).copy()
        M = s.morphs.shape[0]
        M0 = getattr(self, "M0", M)
        mw = np.broadcast_to(s.default_weights, (T, M)).copy() if M else np.zeros((T, 0))
        for path, node, ti, vo, interp in chans:
            if path == "weights":
                if node == s.body_node:
                    mw[:, :M0] = sample_channel(ti, vo.reshape(-1, M0), interp, times, False)
                continue
            v = sample_channel(ti, vo, interp, times, path == "rotation")
            {"translation": tr, "rotation": ro, "scale": sc}[path][:, node] = v
        for cv in getattr(s, "correctives", None) or []:      # pose-space corrective shapes (rig.RigEditor)
            q = ro[:, cv["node"]]
            q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
            ang = np.degrees(2 * np.arccos(np.clip(np.abs(q @ cv["qref"]), 0, 1)))
            x = np.clip(1 - ang / cv["span"], 0, 1)
            mw[:, cv["m"]] = x * x * (3 - 2 * x)
        L = np.zeros((T, nn, 4, 4))
        L[..., :3, :3] = _quat_to_mat(ro) * sc[..., None, :]
        L[..., :3, 3] = tr
        L[..., 3, 3] = 1
        G = np.zeros_like(L)
        for i in s.order:
            p = s.parent.get(i)
            G[:, i] = L[:, i] if p is None else G[:, p] @ L[:, i]
        return G, G[:, s.joints] @ s.ibm[None], mw

    def make_edit(self, clip: str, bone: str, frame: float, hw: float, edits: list[dict], axis: str | None = None,
                  deg: float = 0.0, tr: list | None = None) -> dict:
        """A new edit record (validated, clamped); the axis is frozen to bone-local at the centre frame of the current
        stack's pose."""
        if clip not in self.clips:
            raise ValueError(f"unknown clip {clip}")
        if bone not in self.jnames:
            raise ValueError(f"unknown bone {bone}")
        c = self.clips[clip]
        frame = float(np.clip(frame, 0, c["n"] - 1))
        hw = HW_ALL if hw >= HW_ALL else float(np.clip(hw, MIN_HW, MAX_HW))
        node = self.names.index(bone)
        G, _, _ = self.pose(clip, [self.frame_time(clip, frame)], edits)
        if tr is not None:
            pass
            d = np.asarray(tr, np.float64)[:3]
            if clip in MOVE_CLIPS and bone in (ROOT_BONE, "Root"):
                d[2] = 0.0          # stride length / move speed are exempt: no forward root travel on Move clips
            n = np.linalg.norm(d)
            if n > MAX_TR_H:
                d *= MAX_TR_H / n
            pl = G[0, self.scene.parent[node], :3, :3]
            dl = np.linalg.solve(pl, d * self.H)
            if not any(ch[0] == "translation" and ch[1] == node for ch in self.scene.channels[clip]):
                raise ValueError(f"{clip} has no {bone} translation channel")
            return {"kind": "tr", "clip": clip, "bone": bone, "frame": frame, "hw": hw,
                    "tr": [round(float(x), 4) for x in d], "deltaLocal": [float(x) for x in dl]}
        if axis not in AXES:
            raise ValueError(f"axis must be one of {sorted(AXES)}")
        if not any(ch[0] == "rotation" and ch[1] == node for ch in self.scene.channels[clip]):
            raise ValueError(f"{clip} has no {bone} rotation channel")
        deg = float(np.clip(deg, -MAX_DEG, MAX_DEG))
        Rg = G[0, node, :3, :3]
        Rg = Rg / np.linalg.norm(Rg, axis=0, keepdims=True)    # strip scale
        al = np.linalg.solve(Rg, AXES[axis])
        al = al / np.linalg.norm(al)
        return {"kind": "rot", "clip": clip, "bone": bone, "frame": frame, "hw": hw, "axis": axis, "deg": round(deg, 3),
                "axisLocal": [float(x) for x in al]}

    def viewer_edit(self, e: dict) -> dict:
        """What the three.js viewer needs to run the same math: times in seconds."""
        c = self.clips[e["clip"]]
        if e["kind"] in ("net", "nettr"):
            K = len(c["grid"])
            v = e["q"] if e["kind"] == "net" else e["d"]
            out = {"clip": e["clip"], "bone": e["bone"], "kind": e["kind"], "vals": v[:K]}
            if len(v) == K + 2:
                out.update(last=v[K], wrap=v[K + 1])
            return out
        out = {"clip": e["clip"], "bone": e["bone"], "kind": e["kind"], "tc": self.frame_time(e["clip"], e["frame"]),
               "hwT": e["hw"] * c["step"], "period": c["period"]}
        if e["kind"] == "rot":
            out.update(axisLocal=e["axisLocal"], deg=e["deg"])
        else:
            out.update(deltaLocal=e["deltaLocal"])
        return out

    # ---------------------------------------------------------------- gaze ray
    def _gaze_setup(self):
        s = self.scene
        # generic: the first of Head / Neck / Spine2 / ... with its own skin; else the most forward-reaching joint
        def depth(b):
            n, k = self.names.index(b), 0
            while s.parent.get(n) is not None and s.parent.get(n) >= 0:
                n, k = s.parent[n], k + 1
            return k
        hn = sorted([b for b in self.jnames if "head" in b.lower() or "neck" in b.lower()],
                    key=lambda b: (-("head" in b.lower() and b == "Head"), -depth(b)))
        cand = hn + [b for b in ("Spine2", "Spine1", "Spine") if b in self.jnames]
        cand += sorted(self.jnames, key=lambda b: -float(np.linalg.inv(s.ibm[self.jnames.index(b)])[2, 3]))
        V = None
        for b in cand:
            j = self.jnames.index(b)
            hw = np.where(s.J == j, s.W, 0).sum(1)
            if (hw > 0.3).sum() >= 8:
                self.head_bone, V = b, s.P[hw > 0.3]
                break
        if V is None:
            self.head_bone, j = self.jnames[-1], len(self.jnames) - 1
            V = s.P[np.argsort(-s.P[:, 2])[:8]]
        Grest = np.linalg.inv(s.ibm[j])
        hp = Grest[:3, 3]
        tip = V[np.argmax(V[:, 2])]          # the unit faces +Z: the head's most forward vertex (beak tip)
        d = tip - hp
        if np.linalg.norm(d) < 1e-6:
            d = np.array([0.0, 0.0, 1.0]) * 0.1 * self.H
        R = Grest[:3, :3] / np.linalg.norm(Grest[:3, :3], axis=0, keepdims=True)
        self.gaze_local = np.linalg.solve(R, d / np.linalg.norm(d))
        self.gaze_len = float(np.linalg.norm(d))

    def gaze(self, G) -> tuple[np.ndarray, np.ndarray]:
        """(T, 3) head joint positions and (T, 3) unit gaze directions in world."""
        node = self.names.index(self.head_bone)
        M = G[:, node]
        R = M[:, :3, :3] / np.linalg.norm(M[:, :3, :3], axis=1, keepdims=True)
        return M[:, :3, 3], np.einsum("tij,j->ti", R, self.gaze_local)

    # ---------------------------------------------------------------- CPU reference (parity only)
    def skin_cpu(self, Jm, mw) -> np.ndarray:
        s = self.scene
        out = []
        for b in range(len(Jm)):
            P = s.P + np.tensordot(mw[b], s.morphs.astype(np.float64), 1) if s.morphs.shape[0] else s.P.copy()
            X = np.c_[P, np.ones(len(P))]
            Y = np.zeros((len(P), 3))
            for k in range(s.J.shape[1]):
                Y += s.W[:, k:k + 1] * np.einsum("nij,nj->ni", Jm[b][s.J[:, k]], X)[:, :3]
            out.append(Y)
        return np.stack(out)

    def edge_stretch_cpu(self, Y) -> np.ndarray:
        E = self.edges
        return np.linalg.norm(Y[:, E[:, 0]] - Y[:, E[:, 1]], axis=2) / self.rest_len


def gate_verdict(base: dict, out: dict) -> dict:
    """patch_glb.parity_errors' stretch rule on one clip's key grid: no more edges past STRETCH_RATIO than the
    original clip, and the worst edge may not exceed the original's worst x WORST_STRETCH_SLACK."""
    bad = []
    if out["edgesOver2x"] > base["edgesOver2x"]:
        bad.append(f"edges>{STRETCH_RATIO:g}x {base['edgesOver2x']}->{out['edgesOver2x']}")
    if out["worst"] > base["worst"] * WORST_STRETCH_SLACK:
        bad.append(f"worst stretch {base['worst']:.2f}->{out['worst']:.2f}")
    return {"ok": not bad, "why": "; ".join(bad), "base": base, "out": out}


def load_json(p: Path, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
