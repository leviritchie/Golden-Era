"""Retime a DEF-retarget GLB's idle to the native Olden Era idle cadence (post-process, one rule).

    python tools/homm3_idle_cadence/retime_idle.py <in.glb> <out.glb> [--report out.json]

Rule (idle_cadence_rule.IDLE_TIME_SCALE, or the unit's entry in idle_exceptions.json): every key time of the idle animation is multiplied by
one global factor, so each DEF pose is kept exactly and only the tempo changes. Because the DEF
idle is keyed at 12 fps with LINEAR interpolation, a plain stretch would leave visible
velocity kinks every key (a key every 0.27 s); the stretched clip is therefore resampled at
RESAMPLE_HZ with a loop-periodic, time-parameterised Catmull-Rom (cubic Hermite) curve through
the original keys (rotation, translation, scale). The original key times are part of the output
grid, so every DEF pose is still hit exactly. The corrective-smooth morph weights (one-hot per
key) are resampled linearly on the same grid: a cubic would dip them below 0.

Only the named idle animation changes; every other animation, the mesh, the skin and the
textures are copied byte-for-byte (new accessors are appended to the binary chunk). The input
GLB is never modified: the def_retarget GLB is hash-stamped by the unit-look lane.

Fails closed (exit 1, nothing written) when: the idle animation is missing or duplicated;
a sampler is CUBICSPLINE or a non-constant STEP; a sampler is shared by several channels; a
transform channel does not close its loop (last key != first key) - the def_retarget exporter always
closes Idle, so an open loop means the input is not what this rule was measured on.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_anim import NCOMP, accessor, animation, read_glb, write_glb  # noqa: E402
import idle_cadence_rule as rule  # noqa: E402

LOOP_TOL = 1e-3


class RetimeError(Exception):
    pass


def _hermite_periodic(times: np.ndarray, vals: np.ndarray, t_out: np.ndarray) -> np.ndarray:
    """Loop-periodic, time-parameterised Catmull-Rom through (times, vals). vals[-1] == vals[0]."""
    n = len(times)
    period = times[-1] - times[0]
    # neighbours across the seam: the key before the first is the second-to-last, shifted back
    tp = np.concatenate([[times[-2] - period], times, [times[1] + period]])
    vp = np.concatenate([vals[-2:-1], vals, vals[1:2]], axis=0)
    tang = (vp[2:] - vp[:-2]) / (tp[2:] - tp[:-2])[:, None]          # one per original key
    out = np.empty((len(t_out), vals.shape[1]))
    for k, t in enumerate(t_out):
        j = min(max(int(np.searchsorted(times, t, side="right")) - 1, 0), n - 2)
        h = times[j + 1] - times[j]
        u = (t - times[j]) / h
        h00 = 2 * u ** 3 - 3 * u ** 2 + 1; h10 = u ** 3 - 2 * u ** 2 + u
        h01 = -2 * u ** 3 + 3 * u ** 2; h11 = u ** 3 - u ** 2
        out[k] = h00 * vals[j] + h10 * h * tang[j] + h01 * vals[j + 1] + h11 * h * tang[j + 1]
    return out


def _align_quats(q: np.ndarray) -> np.ndarray:
    q = q.copy()
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def output_times(t0: float, t_end: float, key_times: np.ndarray, hz: float) -> np.ndarray:
    grid = t0 + np.arange(int(np.floor((t_end - t0) * hz + 1e-6)) + 1) / hz
    t = np.unique(np.round(np.concatenate([grid, key_times, [t_end]]), 6))
    # drop grid samples closer than 1/4 frame to an original key (keeps the key, avoids slivers)
    keep = [t[0]]
    keys = set(np.round(key_times, 6).tolist())
    for v in t[1:]:
        if v - keep[-1] < 0.25 / hz:
            if v in keys:
                keep[-1] = v
            continue
        keep.append(v)
    return np.asarray(keep)


def retime(js: dict, bn: bytes, clip: str, scale: float, hz: float, cycles: dict | None = None):
    """cycles: {node index: n} for decoupled channels (wing buzz). Such a channel's source loop
    is played n times over the stretched idle, i.e. at scale / n, so the loop still closes."""
    cycles = cycles or {}
    an = animation(js, clip)
    # original accessors are never modified (the exporter dedupes and shares them between
    # animations); every retimed channel gets new accessors appended to the binary chunk
    new_bin = bytearray(bn)
    new_bin += b"\x00" * ((4 - len(new_bin) % 4) % 4)
    stats = {"channels": 0, "keysBefore": 0, "keysAfter": 0}
    in_cache: dict[int, tuple] = {}

    def add_accessor(arr: np.ndarray, typ: str, minmax: bool) -> int:
        nonlocal new_bin
        arr = np.ascontiguousarray(arr, dtype="<f4")
        off = len(new_bin)
        new_bin += arr.tobytes()
        new_bin += b"\x00" * ((4 - len(new_bin) % 4) % 4)
        js["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        acc = {"bufferView": len(js["bufferViews"]) - 1, "componentType": 5126,
               "count": int(arr.shape[0]), "type": typ}
        if minmax:
            flat = arr.reshape(arr.shape[0], -1)
            acc["min"] = [float(x) for x in flat.min(axis=0)]
            acc["max"] = [float(x) for x in flat.max(axis=0)]
        js["accessors"].append(acc)
        return len(js["accessors"]) - 1

    used = [c["sampler"] for c in an["channels"]]
    if len(used) != len(set(used)):     # it would be rewritten twice
        raise RetimeError(f"{clip}: a sampler is shared by several channels")
    t_first = min(float(accessor(js, bn, s["input"])[0, 0]) for s in an["samplers"])
    t_last = max(float(accessor(js, bn, s["input"])[-1, 0]) for s in an["samplers"])
    for ch in an["channels"]:
        s = an["samplers"][ch["sampler"]]
        interp = s.get("interpolation", "LINEAR")
        times = accessor(js, bn, s["input"])[:, 0]
        vals = accessor(js, bn, s["output"])
        # Blender writes a constant channel as two equal STEP keys; anything else must be LINEAR
        constant_step = interp == "STEP" and len(times) == 2 and np.allclose(vals[0], vals[-1], atol=1e-6)
        if interp != "LINEAR" and not constant_step:
            raise RetimeError(f"{clip}: sampler interpolation {interp} with {len(times)} keys is not "
                              f"supported (LINEAR, or a constant two-key STEP)")
        path = ch["target"]["path"]
        width = vals.shape[1] if path != "weights" else len(vals) // len(times)
        vals = vals.reshape(len(times), -1) if path == "weights" else vals
        if len(times) < 2:
            raise RetimeError(f"{clip}: channel with a single key")
        if path == "rotation":
            vals = _align_quats(vals)
            closed = min(np.max(np.abs(vals[-1] - vals[0])), np.max(np.abs(vals[-1] + vals[0])))
        elif path == "weights":
            closed = 0.0   # one-hot corrective keys: the closing key has its own (equal) shape key
        else:
            closed = float(np.max(np.abs(vals[-1] - vals[0])))
        if closed > LOOP_TOL:
            raise RetimeError(f"{clip}: channel {path} of node {ch['target'].get('node')} does not close "
                              f"its loop (|last-first|={closed:.4g}); refusing to retime an open idle")
        n_cyc = int(cycles.get(ch["target"].get("node"), 1))
        if n_cyc > 1 and len(times) > 2:
            if abs(times[0] - t_first) > 1e-5 or abs(times[-1] - t_last) > 1e-5:
                raise RetimeError(f"{clip}: decoupled channel of node {ch['target'].get('node')} does not span "
                                  f"the whole idle, so it cannot be tiled into a closed loop")
            per = (t_last - t_first) * scale / n_cyc
            base = (times - t_first) * scale / n_cyc
            new_keys = np.concatenate([t_first + base] + [t_first + k * per + base[1:] for k in range(1, n_cyc)])
            vals = np.concatenate([vals] + [vals[1:]] * (n_cyc - 1), axis=0)
            if path == "rotation":
                vals = _align_quats(vals)
        else:
            new_keys = t_first + (times - t_first) * scale
        t_out = output_times(float(new_keys[0]), float(new_keys[-1]), new_keys, hz)
        if len(times) == 2:            # constant channel: keep two keys, stretched
            t_out = new_keys
            v_out = vals
        elif path == "weights":        # blend weights: linear keeps them in [0,1] and summing to 1
            v_out = np.stack([np.interp(t_out, new_keys, vals[:, i]) for i in range(vals.shape[1])], axis=1)
        else:
            v_out = _hermite_periodic(new_keys, vals, t_out)
        if path == "rotation":
            v_out = v_out / np.linalg.norm(v_out, axis=1, keepdims=True)
        key = (s["input"], len(t_out))
        if key not in in_cache:
            in_cache[key] = add_accessor(t_out[:, None], "SCALAR", True)
        s["input"] = in_cache[key]
        if path == "weights":
            s["output"] = add_accessor(v_out.reshape(-1, 1), "SCALAR", False)
        else:
            s["output"] = add_accessor(v_out, {3: "VEC3", 4: "VEC4"}[width], False)
        stats["channels"] += 1
        stats["keysBefore"] = max(stats["keysBefore"], len(times))
        stats["keysAfter"] = max(stats["keysAfter"], len(t_out))
    js["buffers"][0]["byteLength"] = len(new_bin)
    return bytes(new_bin), stats


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--unit", required=True, help="unit id; selects the exceptions-table treatment")
    ap.add_argument("--report")
    args = ap.parse_args()
    if os.path.abspath(args.src) == os.path.abspath(args.dst):
        sys.exit("FAIL: refusing to overwrite the input GLB")
    js, bn = read_glb(args.src)
    tr = rule.treatment_for(args.unit, rule.load_exceptions())
    if tr["treatment"] == "exclude":
        sys.exit(f"FAIL: {args.unit} is excluded from the retime: {tr['reason']}")
    try:
        new_bin, stats = retime(js, bn, rule.IDLE_CLIP, tr["factor"], rule.RESAMPLE_HZ,
                                rule.cycles_for(js, tr))
    except (RetimeError, KeyError) as e:
        sys.exit(f"FAIL: {e}")
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    write_glb(args.dst, js, new_bin)
    rep = {"schema": "homm3_idle_cadence.retime.v1", "rule": rule.describe(), "treatment": tr, "src": args.src,
           "srcSha256": sha256(args.src), "dst": args.dst, "dstSha256": sha256(args.dst), **stats}
    if args.report:
        json.dump(rep, open(args.report, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
