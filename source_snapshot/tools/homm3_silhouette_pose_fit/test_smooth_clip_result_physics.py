"""Tests for smooth_clip_result_physics (post-hoc physics smoothing of payloads).

Run: py -3 test_smooth_clip_result_physics.py
"""
from __future__ import annotations

import json
import math
import struct
import tempfile
from pathlib import Path

import numpy as np

from smooth_clip_result_physics import (
    GlbSkeleton,
    jitter_stats_degrees,
    smooth_payload,
)


def _write_minimal_glb(path: Path) -> None:
    doc = {
        "asset": {"version": "2.0"},
        "nodes": [
            {"name": "Bone_000", "children": [1], "translation": [0.0, 0.0, 0.0]},
            {"name": "Bone_001", "children": [2], "translation": [0.0, 1.0, 0.0]},
            {"name": "Bone_002", "translation": [0.0, 1.0, 0.0]},
        ],
    }
    payload = json.dumps(doc).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    glb = (
        b"glTF"
        + struct.pack("<II", 2, 12 + 8 + len(payload))
        + struct.pack("<I4s", len(payload), b"JSON")
        + payload
    )
    path.write_bytes(glb)


def _payload(poses: dict[int, dict[str, object]], **overrides: object) -> dict:
    payload: dict[str, object] = {
        "poseUnits": "degrees",
        "solver": "cascade",
        "config": {"physics_smooth_enabled": False},
        "physicsSmooth": {"enabled": False, "outlierBoneFrames": 0, "outlierRootFrames": 0},
        "poses": {str(frame): pose for frame, pose in poses.items()},
    }
    payload.update(overrides)
    return payload


def _flat_frames(count: int, *, spike_frame: int | None = None, spike_deg: float = 40.0) -> dict[int, dict[str, object]]:
    poses: dict[int, dict[str, object]] = {}
    for frame in range(count):
        pose: dict[str, object] = {
            "__motion_root__": {"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
            "__motion_root_rotation__": {"camera_forward": 0.0, "camera_right": 0.0, "camera_up": 0.0},
        }
        if spike_frame is not None and frame == spike_frame:
            pose["Bone_001"] = {"x": spike_deg, "y": 0.0, "z": 0.0}
        poses[frame] = pose
    return poses


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = root / "master.glb"
        _write_minimal_glb(mesh)

        skeleton = GlbSkeleton(mesh)
        assert skeleton.depths.tolist() == [0, 1, 2], skeleton.depths
        assert np.allclose(skeleton.directions[0], (0.0, 1.0, 0.0)), skeleton.directions[0]
        assert np.allclose(skeleton.directions[2], (0.0, 1.0, 0.0)), skeleton.directions[2]

        # One-frame 40-degree spike on an otherwise flat bone: the Hampel mask
        # must flag it and the spring must settle back to ~zero.
        payload_path = root / "gpu_clip_result.json"
        payload_path.write_text(json.dumps(_payload(_flat_frames(8, spike_frame=4))), encoding="utf-8")
        before = jitter_stats_degrees(_payload(_flat_frames(8, spike_frame=4))["poses"], ["Bone_001"])
        assert before["max"] > 35.0, before

        report = smooth_payload(payload_path, skeleton, write=True)
        assert report["smoothed"] is True
        assert report["outlierBoneFrames"] >= 1, report
        assert report["jitterAfter"]["max"] < 5.0, report
        assert report["jitterAfter"]["mean"] < report["jitterBefore"]["mean"] * 0.25, report

        rewritten = json.loads(payload_path.read_text(encoding="utf-8"))
        smooth_meta = rewritten["physicsSmooth"]
        assert smooth_meta["enabled"] is True
        assert smooth_meta["postHoc"] is True
        assert smooth_meta["backup"] == "gpu_clip_result.presmooth.json"
        assert rewritten["poseUnits"] == "degrees"
        # Historical solver config is not rewritten by the post-pass.
        assert rewritten["config"]["physics_smooth_enabled"] is False
        # The spike frame's bone entry must collapse below the serialization epsilon.
        frame4 = rewritten["poses"]["4"]
        assert "Bone_001" not in frame4 or max(abs(float(frame4["Bone_001"][axis])) for axis in ("x", "y", "z")) <= 1e-7

        backup = root / "gpu_clip_result.presmooth.json"
        assert backup.is_file(), "original payload must be preserved"
        backup_payload = json.loads(backup.read_text(encoding="utf-8"))
        assert backup_payload["physicsSmooth"]["enabled"] is False
        assert backup_payload["poses"]["4"]["Bone_001"]["x"] == 40.0

        # Re-running on a smoothed payload is an idempotent skip, not a re-smooth.
        second = smooth_payload(payload_path, skeleton, write=True)
        assert second["smoothed"] is False and second["reason"] == "already smoothed"

        # Missing poseUnits fails closed.
        unmarked = root / "unmarked.json"
        unmarked_payload = _payload(_flat_frames(4))
        del unmarked_payload["poseUnits"]
        unmarked.write_text(json.dumps(unmarked_payload), encoding="utf-8")
        try:
            smooth_payload(unmarked, skeleton, write=False)
            raise AssertionError("unmarked payload must fail closed")
        except RuntimeError as exc:
            assert "poseUnits" in str(exc), exc

        # A pose bone that is not a GLB node fails closed.
        stray = root / "stray.json"
        stray_poses = _flat_frames(4)
        stray_poses[1]["Bone_404"] = {"x": 5.0, "y": 0.0, "z": 0.0}
        stray.write_text(json.dumps(_payload(stray_poses)), encoding="utf-8")
        try:
            smooth_payload(stray, skeleton, write=False)
            raise AssertionError("unknown pose bone must fail closed")
        except ValueError as exc:
            assert "Bone_404" in str(exc), exc

    return {"ok": True}


if __name__ == "__main__":
    print(run())
