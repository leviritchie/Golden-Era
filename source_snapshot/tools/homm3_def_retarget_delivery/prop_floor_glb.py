"""Keep a rigid hand prop (a walking cane) out of the floor by tilting it within its own lean plane.

    python tools/homm3_def_retarget_delivery/prop_floor_glb.py apply <unit> [--glb P] [--out P]
    python tools/homm3_def_retarget_delivery/prop_floor_glb.py check <glb...>

Why (2026-09-27, h3_leprechaun Move): the cane is rigid on RightHand and its tip went up to 0.098 of the Idle height
through the floor on every Move key. The whole-body ground stage then lifted the body to clear it, and the stride-planted
feet floated (the lowest foot contact went from +0.036 to +0.073 above Idle, slip 0.156 -> 0.318). The DEF swings the cane
like a pendulum (25-35 deg either side), with its tip on the floor. The mesh held it within 17.6 deg of vertical, and its
wrist was lower than the cane was long. So the correction belongs to the prop's bone, not to the body.

Opt-in by unit config: "propFloor": {"bone": "<prop bone>", "prop": "<name>", "clips": ["Move", ...], "reason": "..."}.
Exit 3 when the unit has no "propFloor" (fleet_rebuild skips the stage).
Rule, per listed clip, on one coherent time grid (every sampler's keys, as ground_check.glb_ground):
  floor  the lowest skinned vertex at Unit_Idle's first key (rubble excluded), which is ground_check's floor;
  prop   the vertices weighted more than 0.5 to the prop bone;
  lean   v = lowest prop vertex - the bone's joint; axis = v x up (the vertical plane that holds v);
  tilt   when the prop's lowest vertex is below the floor, the smallest rotation about that axis through the joint
         that brings it to the floor (a 1 deg scan for the first clearing tilt, then bisection below it: a spear
         held mid-shaft dips its far end as the near end lifts, so clearance is not monotonic; the prop bone's
         whole subtree turns with it). Lift only: a prop above
         the floor is left alone. The lean plane keeps its azimuth, so a cane that passes the vertical sideways swings
         outward instead of flipping front to back.
Written as new rotation keys of the prop bone on the grid (LINEAR, or STEP when the track was a varying STEP track;
a constant STEP track is written LINEAR: held_interpolation); every other
channel keeps its sampler (checked). Refuses: a prop with no lean plane (exactly vertical), a tilt beyond 80 deg, a
loop-closed clip the correction would open, a GLB already stamped, and a result whose prop is still below the floor.
Stamps asset.extras.homm3DefRetargetDeliveryPropFloor {reason, per-clip max tilt} and writes <glb>.prop_floor.json.
fleet_rebuild.py runs it after densify and before ground_glb.py. freeze_slice.py requires the stamp for an opted-in unit.
Proof tier: generated artifact (offline GLB edit); runtime unproven.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import ground_check as GC  # noqa: E402
import stride_gait as G  # noqa: E402
from ground_glb import EPS, canonical_glb, channel_snapshot, loop_closed  # noqa: E402
from stride_match_glb import IDLE, UPI, Glb, skin_body, skin_heights, write_channels  # noqa: E402

STAMP = "homm3DefRetargetDeliveryPropFloor"
SCHEMA = "homm3_def_retarget_delivery_prop_floor.v1"
MAX_TILT_DEG = 80.0
FLOOR_EPS = 1e-5     # world units: the prop's lowest vertex may sit this far below the floor (bisection residue)
LOOP_TOL = 1e-4
NOT_OPTED_IN = 3


def spec_of(unit: str) -> dict | None:
    spec = GC.unit_config(unit).get("propFloor")
    if spec is None:
        return None
    missing = [k for k in ("bone", "prop", "clips", "reason") if not spec.get(k)]
    if missing:
        raise SystemExit(f"{unit}: propFloor is missing {missing}")
    return spec


def subtree(g: Glb, root: int) -> set[int]:
    out, todo = set(), [root]
    while todo:
        i = todo.pop()
        out.add(i)
        todo.extend(g.nodes[i].get("children", []))
    return out


def clip_times(g: Glb, clip: str) -> np.ndarray:
    a = g.anim(clip)
    ts = []
    for ch in a["channels"]:
        s = a["samplers"][ch["sampler"]]
        if s.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
            raise SystemExit(f"{clip}: {s.get('interpolation')} sampler; prop_floor keeps LINEAR and STEP tracks only")
        ts.append(g.read(s["input"])[:, 0])
    return np.unique(np.concatenate(ts))


def rot_about(axis: np.ndarray, theta: float, pivot: np.ndarray) -> np.ndarray:
    q = np.r_[axis * np.sin(theta / 2), np.cos(theta / 2)]
    m = np.eye(4)
    m[:3, :3] = G.qmat(q[None])[0]
    m[:3, 3] = pivot - m[:3, :3] @ pivot
    return m


def prop_heights(body: dict, mats, k: int, mask: np.ndarray, sub: set[int], Q: np.ndarray) -> np.ndarray:
    """World heights of the masked vertices at key k with the prop subtree's world matrices premultiplied by Q."""
    B, J, W = body["B"][mask], body["J"][mask], body["W"][mask]
    nodes, inv = np.unique(J, return_inverse=True)
    up = np.stack([(Q @ mats[n][k] if n in sub else mats[n][k])[UPI] for n in nodes.tolist()])
    U = up[inv.reshape(J.shape)]           # (v, k, 4) gathered once, not a per-vertex Python list (same values)
    return np.einsum("vk,vki,vki->v", W, U, B)


def plan_clip(g: Glb, body: dict, clip: str, bone: int, floor: float, mask: np.ndarray) -> tuple:
    times = clip_times(g, clip)
    local = g.sample_local(clip, times)
    mats = g.world(local)
    sub = subtree(g, bone)
    upv = np.eye(3)[UPI]
    rots, tilts, depth = [], [], []
    I = np.eye(4)
    for k in range(len(times)):
        h0 = prop_heights(body, mats, k, mask, sub, I)
        low = float(h0.min())
        depth.append(low - floor)
        theta = 0.0
        Q = I
        if low < floor - FLOOR_EPS:
            B, J, W = body["B"][mask], body["J"][mask], body["W"][mask]
            i = int(h0.argmin())
            tip = np.einsum("k,kij,kj->i", W[i], np.stack([mats[n][k] for n in J[i]]), B[i])[:3]
            pivot = mats[bone][k][:3, 3]
            ax = np.cross(tip - pivot, upv)
            if np.linalg.norm(ax) < 1e-6:
                raise SystemExit(f"{clip} key {k}: the prop hangs exactly vertical; it has no lean plane to tilt in")
            ax /= np.linalg.norm(ax)
            # First clearing tilt on a 1 deg scan, then bisect below it. A prop held mid-shaft (a spear) has a far
            # end that swings down as the near end lifts, so clearance is not monotonic in the tilt: the full 80 deg
            # can put the far end back through the floor although 2-15 deg clears it (2026-09-30 troglodyte line,
            # Move). For a one-ended cane this finds the same smallest root as bisecting [0, 80] did.
            lo, hi = 0.0, None
            for step in range(1, int(MAX_TILT_DEG) + 1):
                if prop_heights(body, mats, k, mask, sub, rot_about(ax, np.radians(step), pivot)).min() >= floor:
                    lo, hi = np.radians(step - 1), np.radians(step)
                    break
            if hi is None:
                raise SystemExit(f"{clip} key {k}: no tilt up to {MAX_TILT_DEG:.0f} deg lifts the prop out of the floor")
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if prop_heights(body, mats, k, mask, sub, rot_about(ax, mid, pivot)).min() < floor:
                    lo = mid
                else:
                    hi = mid
            theta = hi
            Q = rot_about(ax, theta, pivot)
        new_world = Q @ mats[bone][k]
        par = g.parent.get(bone)
        loc = new_world if par is None else np.linalg.solve(mats[par][k], new_world)
        r = loc[:3, :3] / np.linalg.norm(loc[:3, :3], axis=0)[None, :]
        rots.append(G.mat_q(r[None])[0])
        tilts.append(np.degrees(theta))
    rots = np.array(rots)
    for i in range(1, len(rots)):
        if np.dot(rots[i], rots[i - 1]) < 0:
            rots[i] = -rots[i]
    return times, local, rots, np.array(tilts), np.array(depth)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def prop_mask(g: Glb, body: dict, bone: int) -> np.ndarray:
    m = ((body["J"] == bone) * body["W"]).sum(1) > 0.5
    if not m.any():
        raise SystemExit(f"no vertex is weighted more than 0.5 to {g.names[bone]}")
    return m


def held_interpolation(g: Glb, sampler: dict, new: np.ndarray) -> str:
    """The interpolation to write the prop bone's new rotation keys with: the track's own, except that a constant
    STEP track (the exporter's held rest, two equal keys) is exactly the same curve as LINEAR, so a varying tilt
    written onto it is LINEAR. Kept STEP it snaps the prop from key to key and leaves an N-key STEP Unit_Idle
    (2026-09-28 h3_leprechaun RightHand.rotation: 2-key STEP -> 11-key STEP in Idle, 54 in Move; the ground_glb
    twin of this rule is 33fba4ab45)."""
    it = sampler.get("interpolation", "LINEAR")
    if it == "STEP" and np.abs(np.diff(g.read(sampler["output"]), axis=0)).max(initial=0.0) <= EPS             and np.abs(np.diff(new, axis=0)).max(initial=0.0) > EPS:
        return "LINEAR"
    return it


def apply_bytes(unit: str, data: bytes, p: Path, out: Path | None = None):
    """The prop-floor stage on GLB bytes, in memory: a stage_sidecar.StageResult whose sidecar names `p` as source and
    `out` (default p) as output, as the CLI writes it, or None when the unit config has no "propFloor"."""
    args = argparse.Namespace(unit=unit)
    spec = spec_of(args.unit)
    if spec is None:
        return None
    p = Path(p)
    out = Path(out or p)
    g = Glb(data)
    if STAMP in g.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{args.unit}: {p.name} already carries {STAMP}")
    src = g.raw
    if spec["bone"] not in g.names:
        raise SystemExit(f"{args.unit}: propFloor bone {spec['bone']} is not in the GLB")
    bone = g.names.index(spec["bone"])
    body = skin_body(g)
    ti = np.array([float(g.read(g.anim(IDLE)["samplers"][0]["input"])[0, 0])])
    floor = float(skin_heights(body, g.world(g.sample_local(IDLE, ti)), [0]).min())
    mask = prop_mask(g, body, bone)
    before = channel_snapshot(g)
    clips, H = {}, GC.glb_ground(src)["H"]
    for c in spec["clips"]:
        clip = f"Unit_{c}"
        times, local, rots, tilts, depth = plan_clip(g, body, clip, bone, floor, mask)
        if tilts.max() <= 0:
            clips[c] = {"keys": len(times), "tiltedKeys": 0, "deepestBelowFloorOverHeight": round(float(depth.min()) / H, 4)}
            continue
        closed = loop_closed(g, clip, times)
        if closed and abs(tilts[0] - tilts[-1]) > LOOP_TOL:
            raise SystemExit(f"{args.unit}: the {clip} loop would open (tilt {tilts[0]:.3f} vs {tilts[-1]:.3f} deg)")
        a = g.anim(clip)
        it = "LINEAR"
        for ch in a["channels"]:
            if ch["target"]["node"] == bone and ch["target"]["path"] == "rotation":
                it = held_interpolation(g, a["samplers"][ch["sampler"]], rots)
        write_channels(g, a, times, {(bone, "rotation"): rots}, it)
        clips[c] = {"keys": len(times), "tiltedKeys": int((tilts > 0).sum()), "maxTiltDeg": round(float(tilts.max()), 2),
                    "deepestBelowFloorOverHeight": round(float(depth.min()) / H, 4), "loopClosed": closed}
    rewritten = {(g.names.index(spec["bone"]), "rotation")}
    changed = {f"Unit_{c}" for c, i in clips.items() if i.get("tiltedKeys")}
    after = channel_snapshot(g)            # once: it reads every accessor of every channel
    bad = [f"{k} changed" for k, v in after.items()
           if not (k[0] in changed and (k[1], k[2]) in rewritten) and (k not in before or not all(
               (np.array_equal(x, y) if isinstance(x, np.ndarray) else x == y) for x, y in zip(before[k], v)))]
    bad += [f"{k} dropped" for k in before if k not in after
            and not (k[0] in changed and (k[1], k[2]) in rewritten)]
    if bad:
        raise SystemExit(f"{args.unit}: prop_floor changed channels it does not own: {bad[:6]}")
    # the result: every listed clip's prop at or above the floor on its own grid
    for c in spec["clips"]:
        _, _, _, t2, d2 = plan_clip(g, body, f"Unit_{c}", bone, floor, mask)
        if d2.min() < -FLOOR_EPS * 10:
            raise SystemExit(f"{args.unit}: {c} prop still {d2.min():.5f} below the floor after the tilt")
    g.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = {
        "schema": SCHEMA, "tool": "tools/homm3_def_retarget_delivery/prop_floor_glb.py", "sourceGlbSha256": sha(src),
        "bone": spec["bone"], "prop": spec["prop"], "reason": spec["reason"], "clips": clips,
        "proof": "generated artifact: prop-bone rotation keys on the delivered GLB; not built into a bundle, not in game"}
    data = g.to_bytes()
    import stage_sidecar
    return stage_sidecar.result(
        data, src, "prop_floor",
        {"schema": SCHEMA, "unit": args.unit, "sourceGlb": str(p), "sourceGlbSha256": sha(src), "outputGlb": str(out),
         "outputGlbSha256": sha(data), "bone": spec["bone"], "prop": spec["prop"], "reason": spec["reason"],
         "clips": clips},
        {"unit": args.unit, "out": str(out), "clips": clips})


def cmd_apply(args) -> int:
    if spec_of(args.unit) is None:
        print(json.dumps({"unit": args.unit, "skipped": "no propFloor in the unit config"}))
        return NOT_OPTED_IN
    p = Path(args.glb or canonical_glb(args.unit))
    out = Path(args.out or p)
    r = apply_bytes(args.unit, p.read_bytes(), p, out)
    import stage_sidecar
    stage_sidecar.commit(out, r)
    print(json.dumps(r.report))
    return 0


def stamp_errors(unit: str, js: dict) -> list[str]:
    spec = spec_of(unit)
    st = js.get("asset", {}).get("extras", {}).get(STAMP)
    if spec is None:
        return [f"{STAMP} present but the unit config has no propFloor"] if st else []
    if not isinstance(st, dict):
        return [f"no {STAMP} stamp (fleet_rebuild.py runs prop_floor_glb.py apply)"]
    bad = []
    if st.get("schema") != SCHEMA:
        bad.append(f"{STAMP} schema {st.get('schema')!r} != {SCHEMA}")
    if st.get("bone") != spec["bone"] or sorted(st.get("clips", {})) != sorted(spec["clips"]):
        bad.append(f"{STAMP} bone/clips differ from the unit config's propFloor")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path)
    s.add_argument("--out", type=Path)
    s = sub.add_parser("check")
    s.add_argument("unit")
    s.add_argument("glbs", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "apply":
        return cmd_apply(args)
    bad = 0
    for p in args.glbs:
        errs = stamp_errors(args.unit, Glb.load(Path(p)).json)
        print(json.dumps({"glb": p, "ok": not errs, "errors": errs}))
        bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
