"""Character pass: idle understated about the mean stance, motion exaggerated, root untouched."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clip_character_pass import (  # noqa: E402
    DEFAULT_CHARACTER_PROFILE,
    apply_character_pass,
    frame_duration_by_suffix,
)
from deliberate_motion_contract import AUTHENTIC_DEF_FRAME_DURATION_SECONDS  # noqa: E402


def _payload(frames, *, joint_limit=None):
    poses = {str(i): dict(frame) for i, frame in enumerate(frames)}
    payload = {"poseUnits": "degrees", "poses": poses, "physicsSmooth": {"enabled": True}}
    if joint_limit is not None:
        payload["config"] = {"joint_limit_deg": joint_limit}
    return payload


def _z(out, index, bone="Bone_A"):
    entry = out["poses"][str(index)].get(bone, {"x": 0.0, "y": 0.0, "z": 0.0})
    return float(entry["z"])


def _close(a, b, tol=1e-6):
    assert math.isclose(a, b, abs_tol=tol), (a, b)


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def run() -> dict[str, object]:
    # Idle: +/-10 deg swing around a 30 deg stance -> stance kept, swing x0.6.
    frames = [{"Bone_A": {"x": 0.0, "y": 0.0, "z": 30.0 + s}} for s in (-10.0, 0.0, 10.0, 0.0)]
    out, report = apply_character_pass(_payload(frames), groups=(2,), counts=(4,))
    _close(_z(out, 1), 30.0)
    _close(_z(out, 0), 24.0)
    _close(_z(out, 2), 36.0)
    assert report["clampedBoneFrames"] == 0
    assert report["gainPerFrame"] == [0.6] * 4

    # Attack: mean 40, deviations -/+20 -> x1.35 -> 13 / 67; root motion byte-identical.
    root = {"forward": 0.25, "lateral": 0.0, "vertical": 0.1}
    frames = [
        {"Bone_A": {"x": 0.0, "y": 0.0, "z": 20.0}, "__motion_root__": dict(root)},
        {"Bone_A": {"x": 0.0, "y": 0.0, "z": 60.0}, "__motion_root__": dict(root)},
    ]
    out, _ = apply_character_pass(_payload(frames), groups=(12,), counts=(2,))
    _close(_z(out, 0), 13.0)
    _close(_z(out, 1), 67.0)
    assert out["poses"]["1"]["__motion_root__"] == root

    # Motion payload (2, 20, 0): idle prefix untouched (gain 1); motion frames share one reference.
    frames = [{"Bone_A": {"x": 0.0, "y": 0.0, "z": z}} for z in (5.0, 10.0, 30.0, 50.0)]
    out, report = apply_character_pass(_payload(frames), groups=(2, 20, 0), counts=(1, 1, 2))
    _close(_z(out, 0), 5.0)
    assert report["gainPerFrame"][0] == 1.0
    assert report["referenceFrames"] == [1, 2, 3]
    _close(_z(out, 1), 5.0)   # 30 + 1.25 * (10 - 30)
    _close(_z(out, 3), 55.0)  # 30 + 1.25 * (50 - 30)

    # Clamp to the payload's joint limit, counted.
    frames = [{"Bone_A": {"x": 0.0, "y": 0.0, "z": 0.0}}, {"Bone_A": {"x": 0.0, "y": 0.0, "z": 120.0}}]
    out, report = apply_character_pass(_payload(frames, joint_limit=70.0), groups=(12,), counts=(2,))
    assert report["clampedBoneFrames"] == 1
    _close(_z(out, 1), 70.0)

    # Unshipped group / frame-count mismatch fail closed.
    one = [{"Bone_A": {"x": 0.0, "y": 0.0, "z": 1.0}}]
    _raises(KeyError, lambda: apply_character_pass(_payload(one), groups=(7,), counts=(1,)))
    _raises(ValueError, lambda: apply_character_pass(_payload(one * 3), groups=(2,), counts=(4,)))

    # Input not mutated; rotation composition is exact for non-collinear axes too.
    frames = [{"Bone_A": {"x": 20.0, "y": 0.0, "z": 0.0}}, {"Bone_A": {"x": 0.0, "y": 0.0, "z": 20.0}}]
    payload = _payload(frames)
    before = json.dumps(payload, sort_keys=True)
    out, _ = apply_character_pass(payload, groups=(12,), counts=(2,))
    assert json.dumps(payload, sort_keys=True) == before
    from scipy.spatial.transform import Rotation

    ref = Rotation.from_rotvec(np.radians([[20.0, 0.0, 0.0], [0.0, 0.0, 20.0]])).mean()
    dev0 = ref.inv() * Rotation.from_rotvec(np.radians([20.0, 0.0, 0.0]))
    expected0 = np.degrees((ref * Rotation.from_rotvec(dev0.as_rotvec() * 1.35)).as_rotvec())
    got0 = out["poses"]["0"]["Bone_A"]
    assert np.allclose([got0["x"], got0["y"], got0["z"]], expected0, atol=1e-6)

    durations = frame_duration_by_suffix(DEFAULT_CHARACTER_PROFILE)
    _close(durations["Idle"], AUTHENTIC_DEF_FRAME_DURATION_SECONDS * 1.6)
    _close(durations["AttackFront"], AUTHENTIC_DEF_FRAME_DURATION_SECONDS)
    _close(1.0 / durations["Idle"], 7.5)
    return {"ok": True, "idleFps": 1.0 / durations["Idle"]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
