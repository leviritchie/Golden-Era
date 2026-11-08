"""Measure native Olden Era battle-unit idle cadence from the installed game (read-only).

    python tools/homm3_idle_cadence/measure_native_idles.py --out artifacts/homm3_idle_cadence/native_idles.json

Every AnimatorOverrideController in `resources.assets` whose base is `_Battle_Unit_Anim_ctrl_v2`
is a battle unit. Its `22.Idle` / `23.Idle_Rare` overrides are decoded (Unity muscle-clip
streamed + dense + constant curves, generic Transform bindings), resampled at 60 Hz and
measured by `idle_metrics.cadence`. The base controller's idle / rareIdle states are also
recorded (state speed and speed parameter), and each unit view's `rareIdleTime` from Core.zip.

Requires UnityPy. Fails closed if the base controller or its idle states are missing, or if a
decoded streamed curve is discontinuous (a decoder error would otherwise read as motion).
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from idle_metrics import cadence, summarize  # noqa: E402

GAME = r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
DATA = GAME + "/HeroesOldenEra_Data/"
BASE_CTRL = "_Battle_Unit_Anim_ctrl_v2"
SAMPLE_HZ = 60.0
TRANSFORM = 4


def decode_streamed(words: list[int]):
    """Unity StreamedClip: frames of (time, nKeys, nKeys x (curveIndex, coeff[4]))."""
    buf = struct.pack(f"<{len(words)}I", *words)
    pos, frames = 0, []
    while pos < len(buf):
        t, n = struct.unpack_from("<fI", buf, pos); pos += 8
        keys = []
        for _ in range(n):
            idx = struct.unpack_from("<I", buf, pos)[0]
            c = struct.unpack_from("<4f", buf, pos + 4); pos += 20
            keys.append((idx, c))
        frames.append((t, keys))
    curves: dict[int, list] = {}
    for t, keys in frames:
        if not np.isfinite(t):
            continue
        for idx, c in keys:
            curves.setdefault(idx, []).append((t, c))
    return curves


def eval_streamed(keys, times):
    kt = np.array([k[0] for k in keys])
    co = np.array([k[1] for k in keys])
    out = np.empty(len(times))
    for i, t in enumerate(times):
        j = max(0, int(np.searchsorted(kt, t, side="right")) - 1)
        dt = t - kt[j]
        a, b, c, d = co[j]
        out[i] = ((a * dt + b) * dt + c) * dt + d
    return out


def continuity_error(keys) -> float:
    """Max |poly(key j at t_{j+1}) - value(key j+1)| relative to the curve's range."""
    if len(keys) < 3:
        return 0.0
    vals = np.array([k[1][3] for k in keys])
    rng = max(float(np.ptp(vals)), 1e-4)
    err = 0.0
    for (t0, c0), (t1, c1) in zip(keys[:-1], keys[1:]):
        dt = t1 - t0
        a, b, c, d = c0
        err = max(err, abs(((a * dt + b) * dt + c) * dt + d - c1[3]))
    return err / rng


def clip_rotations(tt: dict):
    mc = tt["m_MuscleClip"]
    start, stop = float(mc["m_StartTime"]), float(mc["m_StopTime"])
    length = stop - start
    data = mc["m_Clip"]["data"]
    sc = data["m_StreamedClip"]; dc = data["m_DenseClip"]; cc = data["m_ConstantClip"]["data"]
    n_s = int(sc["curveCount"]); n_d = int(dc["m_CurveCount"])
    times = np.linspace(start, stop, int(round(length * SAMPLE_HZ)) + 1)
    streamed = decode_streamed(sc["data"]) if sc["data"] else {}
    worst = max((continuity_error(k) for k in streamed.values()), default=0.0)
    dense = np.asarray(dc["m_SampleArray"], dtype=np.float64)
    if n_d:
        dense = dense.reshape(int(dc["m_FrameCount"]), n_d)
        dtimes = float(dc["m_BeginTime"]) + np.arange(dense.shape[0]) / float(dc["m_SampleRate"])

    def curve(i):
        if i < n_s:
            k = streamed.get(i)
            return eval_streamed(k, times) if k else np.zeros(len(times))
        i -= n_s
        if i < n_d:
            return np.interp(times, dtimes, dense[:, i])
        i -= n_d
        return np.full(len(times), float(cc[i]))

    rots, ci, humanoid = {}, 0, 0
    for b in tt["m_ClipBindingConstant"]["genericBindings"]:
        if b["typeID"] == TRANSFORM:
            size = 4 if b["attribute"] == 2 else 3
            if b["attribute"] == 2:
                rots[str(b["path"])] = np.stack([curve(ci + k) for k in range(4)], axis=1)
        else:
            size = 1
            humanoid += 1
        ci += size
    return rots, length, float(tt["m_SampleRate"]), worst, humanoid


def rare_idle_times() -> dict:
    out = {}
    z = zipfile.ZipFile(GAME + "/HeroesOldenEra_Data/StreamingAssets/Core.zip")
    for n in z.namelist():
        if not (n.startswith("DB/units/units_views/") and n.endswith(".json")) or "/homm3_" in n:
            continue
        try:
            arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
        except Exception:
            continue
        for v in arr:
            if isinstance(v, dict) and "mesh" in v:
                out[v["mesh"].rsplit("/", 1)[-1].lower()] = {
                    "id": v.get("id"), "rareIdleTime": v.get("rareIdleTime"), "scale": v.get("scale"),
                    "modelHeight": v.get("modelHeight")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    import UnityPy
    env = UnityPy.load(DATA + "resources.assets")
    byid = {o.path_id: o for o in env.objects}
    base = [o for o in env.objects if o.type.name == "AnimatorController" and o.peek_name() == BASE_CTRL]
    if len(base) != 1:
        sys.exit(f"FAIL: expected one {BASE_CTRL}, found {len(base)}")
    btt = base[0].read_typetree()
    tos = {int(k): v for k, v in btt["m_TOS"]}
    states = {}
    for st in btt["m_Controller"]["m_StateMachineArray"][0]["data"]["m_StateConstantArray"]:
        s = st["data"]; name = tos.get(s["m_NameID"])
        if name in ("idle", "rareIdle 0"):
            states[name] = {"speed": s["m_Speed"], "speedParam": tos.get(s["m_SpeedParamID"]) or None,
                            "transitions": [{"to": tos.get(t["data"]["m_UserID"]) or None,
                                             "hasExitTime": bool(t["data"]["m_HasExitTime"]),
                                             "exitTime": round(t["data"]["m_ExitTime"], 4),
                                             "conditions": [tos.get(c["data"]["m_EventID"]) for c in t["data"]["m_ConditionConstantArray"]]}
                                            for t in s["m_TransitionConstantArray"]]}
    if set(states) != {"idle", "rareIdle 0"}:
        sys.exit(f"FAIL: base controller idle states missing: {sorted(states)}")
    views = rare_idle_times()
    # prefab root name per override controller (for the view lookup)
    prefab_of = {}
    for o in env.objects:
        if o.type.name != "Animator":
            continue
        a = o.read_typetree()
        c = a["m_Controller"]["m_PathID"]; go = byid.get(a["m_GameObject"]["m_PathID"])
        if go is not None:
            prefab_of.setdefault(c, []).append(go.peek_name())
    rows, seen = [], set()
    for o in env.objects:
        if o.type.name != "AnimatorOverrideController":
            continue
        tt = o.read_typetree()
        b = byid.get(tt["m_Controller"]["m_PathID"])
        if b is None or b.peek_name() != BASE_CTRL:
            continue
        clips = {}
        for c in tt["m_Clips"]:
            a = byid.get(c["m_OriginalClip"]["m_PathID"]); ov = byid.get(c["m_OverrideClip"]["m_PathID"])
            if a is not None and ov is not None:
                clips[a.peek_name()] = ov
        prefabs = sorted(set(prefab_of.get(o.path_id, [])))
        view = next((views[p.lower()] for p in prefabs if p.lower() in views), None)
        for role in ("22.Idle", "23.Idle_Rare"):
            ov = clips.get(role)
            if ov is None or (ov.path_id, role) in seen:
                continue
            seen.add((ov.path_id, role))
            ctt = ov.read_typetree()
            rots, length, rate, worst, humanoid = clip_rotations(ctt)
            if worst > 0.05:
                sys.exit(f"FAIL: streamed decode discontinuity {worst:.3f} in {o.peek_name()} {role}")
            m = cadence(rots, length)
            rows.append({"controller": o.peek_name(), "prefabs": prefabs, "role": role,
                         "clip": ov.peek_name(), "sampleRate": rate, "humanoidCurves": humanoid,
                         "viewUsingPrefab": view and view["id"], "rareIdleTime": view and view["rareIdleTime"],
                         "viewScale": view and view["scale"], **m})
            print(o.peek_name(), role, m["lengthS"], m.get("beats"), m.get("angSpeedDegS"), flush=True)
    idle = [r for r in rows if r["role"] == "22.Idle"]
    rare = [r for r in rows if r["role"] == "23.Idle_Rare"]
    report = {"schema": "homm3_idle_cadence.native.v1", "source": DATA + "resources.assets",
              "baseController": BASE_CTRL, "states": states, "sampleHz": SAMPLE_HZ,
              "summary": {k: {"lengthS": summarize(v, "lengthS"), "beats": summarize(v, "beats"),
                              "beatPeriodS": summarize(v, "beatPeriodS"),
                              "angSpeedDegS": summarize(v, "angSpeedDegS"),
                              "peakAngSpeedDegS": summarize(v, "peakAngSpeedDegS"),
                              "amplitudeDeg": summarize(v, "amplitudeDeg")}
                          for k, v in (("idle", idle), ("idleRare", rare))},
              "clips": rows}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(report, open(args.out, "w"), indent=1)
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
