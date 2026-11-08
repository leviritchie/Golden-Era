"""Register a SmartRig cascade bind without guessing biped left/right orientation.

SmartRig exports carry a named ``Orientation`` node and non-semantic ``Bone_*``
joint names.  This adapter reads the route's recorded orientation, removes that
container transform into the mesh frame, and emits a small idle-only linked-master
reference for diagnostic replay.  It is generated-artifact evidence; it does not
rewrite the staged SmartRig clips or claim delivery/runtime proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from glb_skeleton import load_bind_skeleton, read_glb  # noqa: E402
from idle0_meshy_registration import write_idle0_meshy_registration  # noqa: E402
from oe_motion_style_v2 import _animation  # noqa: E402
from static_bind_registration import rotation_matrix  # noqa: E402


def _q_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    values = np.asarray(quaternion, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12:
        raise ValueError("SmartRig animation contains a zero quaternion")
    x, y, z, w = values / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _fk_positions(local_rotations: np.ndarray, translations: np.ndarray, parents: tuple[int, ...]) -> np.ndarray:
    local_rotations = np.asarray(local_rotations, dtype=np.float64)
    translations = np.asarray(translations, dtype=np.float64)
    worlds = np.zeros((len(local_rotations), 4, 4), dtype=np.float64)
    for index, parent in enumerate(parents):
        local = np.eye(4, dtype=np.float64)
        local[:3, :3] = local_rotations[index]
        local[:3, 3] = translations[index]
        worlds[index] = local if int(parent) < 0 else worlds[int(parent)] @ local
    return worlds[:, :3, 3]


def _orientation_yaw(clip_json: dict[str, Any], bind_doc: dict[str, Any]) -> float:
    orientation = clip_json.get("orientation") or {}
    if orientation.get("root") != "UniRigArmature" or orientation.get("skeletonRoot") != "Bone_000":
        raise ValueError("SmartRig clip is missing the expected explicit orientation provenance")
    declared = float(orientation.get("rotationYawDeg"))
    nodes = bind_doc["json"].get("nodes") or []
    orientation_nodes = [node for node in nodes if node.get("name") == "Orientation"]
    if len(orientation_nodes) != 1:
        raise ValueError("SmartRig bind must have exactly one Orientation node")
    actual = orientation_nodes[0].get("rotation")
    if actual is None:
        raise ValueError("SmartRig Orientation node has no rotation")
    actual_matrix = _q_to_matrix(np.asarray(actual, dtype=np.float64))
    expected = rotation_matrix(declared, 0.0, 0.0)
    if not np.allclose(actual_matrix, expected, atol=2e-5, rtol=0.0):
        raise ValueError("SmartRig clip orientation metadata disagrees with the bind Orientation node")
    return declared


def _source_idle_frames(manifest_path: Path, frame_count: int) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    clips = [row for row in manifest.get("clips", ()) if row.get("key") == "g02_idle"]
    if len(clips) != 1:
        raise ValueError("Hydra corpus must have exactly one g02_idle source clip")
    frames = [Path(str(path)) for path in clips[0].get("frames", ())]
    if len(frames) < int(frame_count):
        raise ValueError(f"g02_idle has {len(frames)} source frames, needs {frame_count}")
    selected = frames[: int(frame_count)]
    missing = [str(path) for path in selected if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    return selected


def build_smartrig_idle0_reference(
    *,
    unit: str,
    bind: Path,
    clip: Path,
    manifest: Path,
    output_root: Path,
) -> dict[str, Any]:
    bind = Path(bind).resolve()
    clip = Path(clip).resolve()
    manifest = Path(manifest).resolve()
    output_root = Path(output_root).resolve()
    if not bind.is_file() or not clip.is_file() or not manifest.is_file():
        raise FileNotFoundError("SmartRig bind, clip metadata, and corpus manifest are required")
    bind_doc = read_glb(bind)
    skeleton = load_bind_skeleton(bind)
    clip_json = json.loads(clip.read_text(encoding="utf-8"))
    orientation_yaw = _orientation_yaw(clip_json, bind_doc)
    animation_doc = read_glb(Path(clip_json["output"]) if Path(str(clip_json.get("output", ""))).is_file() else clip)
    _animation_doc, times, rotations, _outputs = _animation(animation_doc, animation_doc["bin"], skeleton)
    frame_count = int(clip_json.get("frameCount", len(times) - 1))
    if frame_count < 1 or len(times) < frame_count:
        raise ValueError("SmartRig clip frame count is inconsistent with its animation")
    source_frames = _source_idle_frames(manifest, frame_count)

    rest_local = np.asarray(skeleton.rest_local_rotation, dtype=np.float64)
    rest_positions = _fk_positions(rest_local, skeleton.rest_local_translation, skeleton.parents)
    inverse_orientation = rotation_matrix(-orientation_yaw, 0.0, 0.0)
    loaded_rest = np.asarray(skeleton.rest_world, dtype=np.float64) @ inverse_orientation.T
    if not np.allclose(rest_positions, loaded_rest, atol=2e-5, rtol=0.0):
        raise ValueError("SmartRig FK rest pose does not match the Orientation-normalized bind")

    frames = []
    positions = []
    for index in range(frame_count):
        local = np.stack([_q_to_matrix(row) for row in rotations[index]], axis=0)
        positions.append(_fk_positions(local, skeleton.rest_local_translation, skeleton.parents))
        frames.append(
            {
                "globalIndex": index,
                "segmentIndex": 0,
                "clipKey": "g02_idle",
                "defGroup": 2,
                "role": "cycle",
                "localIndex": index,
                "sourcePng": str(source_frames[index]).replace("\\", "/"),
                "numberedPng": str(source_frames[index]).replace("\\", "/"),
            }
        )
    positions_array = np.asarray(positions, dtype=np.float64)
    if not np.isfinite(positions_array).all():
        raise ValueError("SmartRig FK produced non-finite positions")
    if not np.allclose(positions_array[0], rest_positions, atol=2e-5, rtol=0.0):
        raise ValueError("SmartRig idle frame 0 is not the bind rest pose")

    capture = output_root / "linked_master/capture/capture/raw_capture.npz"
    master = output_root / "linked_master/master_sequence/master_sequence.json"
    registration = output_root / "linked_master/idle0_registration.json"
    for path in (capture, master, registration):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite SmartRig reference: {path}")
    capture.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        capture,
        pred_position=positions_array,
        local_rotation=np.stack([np.stack([_q_to_matrix(row) for row in rotations[i]], axis=0) for i in range(frame_count)]),
        joint_names=np.asarray(skeleton.names),
        parents=np.asarray(skeleton.parents, dtype=np.int64),
        motionRepresentation=np.asarray("smartrig_local_rotation_fk_orientation_normalized"),
    )
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_text(
        json.dumps(
            {
                "schema": "homm3.linked-master-sequence.v2",
                "reelPolicy": "smartrig_idle_only_source_frames",
                "idleBookendFrames": 0,
                "poseCapacity": 10000,
                "unit": unit,
                "frameCount": frame_count,
                "bindGroup": 2,
                "bindLocalFrame": 0,
                "bindGlobalIndex": 0,
                "sourceFrameMs": 1000.0 / float(clip_json.get("fps", 12.0)),
                "segments": [
                    {
                        "segmentIndex": 0,
                        "clipKey": "g02_idle",
                        "defGroup": 2,
                        "contractSuffix": "Idle",
                        "role": "cycle",
                        "globalStart": 0,
                        "globalEnd": frame_count,
                        "frameCount": frame_count,
                        "sourceClipFrameCount": frame_count,
                        "exportsClip": True,
                    }
                ],
                "frames": frames,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = write_idle0_meshy_registration(
        output_path=registration,
        unit=unit,
        mesh_path=bind,
        mesh_vertices=np.asarray(skeleton.vertices, dtype=np.float64),
        mesh_triangles=np.asarray(skeleton.triangles, dtype=np.int64),
        capture_path=capture,
        capture_joints=positions_array[0],
        capture_parents=np.asarray(skeleton.parents, dtype=np.int64),
        idle_frame0=source_frames[0],
        bind_frame=0,
        fit="idle0_ground_height",
        explicit_capture_yaw_undo_deg=0.0,
        capture_yaw_policy=(
            "smartrig_orientation_node_inverse_yaw_"
            + str(-orientation_yaw).rstrip("0").rstrip(".")
            + "_mesh_frame"
        ),
    )
    report = {
        "schema": "homm3.smartrig-idle0-adapter.v1",
        "proof": "generated-artifact registration and idle replay reference only",
        "unit": unit,
        "bind": str(bind).replace("\\", "/"),
        "clip": str(clip).replace("\\", "/"),
        "orientation": {
            "source": "SmartRig clip metadata plus bind Orientation node",
            "rotationYawDeg": orientation_yaw,
            "meshFrameInverseYawDeg": -orientation_yaw,
        },
        "capture": str(capture).replace("\\", "/"),
        "master": str(master).replace("\\", "/"),
        "registration": str(registration).replace("\\", "/"),
        "frameCount": frame_count,
        "registrationAccepted": bool(payload["acceptance"]["accepted"]),
    }
    (output_root / "linked_master/smartrig_idle0_adapter_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_hydra")
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_smartrig_idle0_reference(
        unit=str(args.unit),
        bind=args.bind,
        clip=args.clip,
        manifest=args.manifest,
        output_root=args.out,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
