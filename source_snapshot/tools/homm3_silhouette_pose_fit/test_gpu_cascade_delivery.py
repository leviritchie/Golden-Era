"""Idle-prefix slice and GPU cascade clip GLB delivery."""
from __future__ import annotations

import io
import json
import math
import struct
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from gpu_cascade_delivery import (
    ALBEDO_JPEG_NAME,
    CONTRACT_BY_GROUP,
    CURRENT_CASCADE_KEEP,
    METALLIC_GLOSS_PNG_NAME,
    NORMAL_PNG_NAME,
    SKIPPED_DEF_GROUPS,
    apply_current_cascade_keep,
    clip_result_matches_current_keep,
    delivery_poses_by_group,
    glb_basecolor_image_payload,
    gpu_pose_local_rotation,
    group_frame_spans,
    pack_gltf_metallic_roughness_to_unity_metallic_gloss,
    require_pose_units_degrees,
    write_oriented_clip_glb,
    write_oriented_master_glb,
)
from roc_gpu_cascade_experiment import _axis_angle_quaternion_np, _quat_multiply


ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
MESH = ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb"
LAB_BUILDERS = (
    ROOT / "tools/homm3_import/unity_editor/CrusaderOwnedSkinnedLabBuild.cs",
    ROOT / "oldenera_factions/Assets/Editor/CrusaderOwnedSkinnedLabBuild.cs",
)


def _read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        if chunk_type == b"JSON":
            return json.loads(data[start : start + chunk_length].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = start + chunk_length
    raise ValueError(f"no JSON chunk: {path}")


def _read_glb_json_and_bin(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    json_doc: dict | None = None
    bin_blob = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        payload = data[start : start + chunk_length]
        if chunk_type == b"JSON":
            json_doc = json.loads(payload.decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_blob = payload
        offset = start + chunk_length
    if json_doc is None:
        raise ValueError(f"no JSON chunk: {path}")
    return json_doc, bin_blob


def _glb_rotation_channel(doc: dict, bin_blob: bytes, node_name: str) -> np.ndarray:
    node_index = next(
        index for index, node in enumerate(doc["nodes"]) if node.get("name") == node_name
    )
    animation = doc["animations"][0]
    channel = next(
        item
        for item in animation["channels"]
        if item["target"]["node"] == node_index and item["target"]["path"] == "rotation"
    )
    accessor = doc["accessors"][animation["samplers"][channel["sampler"]]["output"]]
    view = doc["bufferViews"][accessor["bufferView"]]
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    return np.frombuffer(bin_blob, dtype="<f4", count=int(accessor["count"]) * 4, offset=offset).reshape(-1, 4)


def run() -> dict[str, object]:
    spans = group_frame_spans((2, 20, 0), (8, 2, 8))
    assert spans == ((2, 0, 8), (20, 8, 2), (0, 10, 8)), spans

    poses = {index: {"Bone_000": {"x": float(index), "y": 0.0, "z": 0.0}} for index in range(18)}
    delivered = delivery_poses_by_group(poses, (2, 20, 0), (8, 2, 8))
    assert set(delivered) == {20, 0}, set(delivered)
    assert list(delivered[20]) == [0, 1]
    assert delivered[20][0]["Bone_000"]["x"] == 8.0
    assert delivered[20][1]["Bone_000"]["x"] == 9.0
    assert list(delivered[0]) == list(range(8))
    assert delivered[0][0]["Bone_000"]["x"] == 10.0
    assert delivered[0][7]["Bone_000"]["x"] == 17.0
    idle_values = {pose["Bone_000"]["x"] for pose in delivered[0].values()} | {
        pose["Bone_000"]["x"] for pose in delivered[20].values()
    }
    assert idle_values.isdisjoint(set(range(8))), idle_values

    attack = delivery_poses_by_group(
        {index: {"marker": {"x": float(index)}} for index in range(15)},
        (2, 12),
        (8, 7),
    )
    assert set(attack) == {12}
    assert [attack[12][index]["marker"]["x"] for index in range(7)] == [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]

    attack_return = delivery_poses_by_group(
        {index: {"marker": {"x": float(index)}} for index in range(23)},
        (2, 12, 2),
        (8, 7, 8),
    )
    assert set(attack_return) == {12}, set(attack_return)
    assert [attack_return[12][index]["marker"]["x"] for index in range(7)] == [
        8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0,
    ]

    locomotion = delivery_poses_by_group(
        {index: {"Bone_000": {"x": float(index)}} for index in range(32)},
        (2, 20, 0, 21, 2),
        (8, 2, 8, 6, 8),
    )
    assert set(locomotion) == {20, 0, 21}, set(locomotion)
    assert list(locomotion[20]) == [0, 1]
    assert locomotion[20][0]["Bone_000"]["x"] == 8.0
    assert locomotion[0][0]["Bone_000"]["x"] == 10.0
    assert locomotion[21][0]["Bone_000"]["x"] == 18.0
    assert locomotion[21][5]["Bone_000"]["x"] == 23.0

    idle_only = delivery_poses_by_group(
        {index: {"marker": {"x": float(index)}} for index in range(8)},
        (2,),
        (8,),
    )
    assert set(idle_only) == {2}
    assert list(idle_only[2]) == list(range(8))

    try:
        delivery_poses_by_group({}, (2,), (8,))
        raise AssertionError("missing concatenated frames must fail closed")
    except KeyError as exc:
        assert "missing concatenated frames" in str(exc)

    rest = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    # Pose-dict x/y/z are axis-angle DEGREES (serializer applies np.degrees;
    # _pose_entry_to_xyz converts back with math.radians). The exporter must
    # produce rest * axis-angle(radians(delta)) — a 90-degree delta is a
    # quarter turn, not 90 radians.
    delta = (0.0, 90.0, 0.0)
    composed = gpu_pose_local_rotation(rest, delta)
    expected = _quat_multiply(rest, _axis_angle_quaternion_np(np.radians(np.asarray(delta))))
    assert float(np.linalg.norm(composed - expected)) < 1e-12
    half_turn_quarter = math.sin(math.pi / 4.0)
    assert np.allclose(composed, (0.0, half_turn_quarter, 0.0, math.cos(math.pi / 4.0)), atol=1e-12), composed
    small = gpu_pose_local_rotation(rest, (0.25, 0.0, 0.0))
    assert np.allclose(
        small,
        _axis_angle_quaternion_np(np.asarray((math.radians(0.25), 0.0, 0.0))),
        atol=1e-12,
    ), small

    require_pose_units_degrees({"poseUnits": "degrees"}, source="synthetic")
    for bad_payload in ({"poses": {}}, {"poseUnits": "radians"}):
        try:
            require_pose_units_degrees(bad_payload, source="synthetic")
            raise AssertionError("unmarked/radians payloads must fail closed")
        except RuntimeError as exc:
            assert "poseUnits" in str(exc), exc

    stale = {"solver": "cascade", "config": {"fine_iterations": 1}, "poses": {"0": {}}}
    assert clip_result_matches_current_keep(stale) is False
    current = {
        "solver": "cascade",
        "config": {
            "joint_collision_positive_abs_slack": 0.12,
            "joint_temporal_consensus_enabled": True,
            "joint_temporal_consensus_bidirectional": True,
            "joint_temporal_consensus_idle_end": True,
            "joint_temporal_consensus_independent_passes": True,
            "joint_temporal_consensus_whole_pose": True,
            "root_rotation_camera_up_limit_deg": 45.0,
            "root_rotation_defer_camera_up": True,
            "joint_adaptive_step_enabled": True,
            "joint_step_score_norm": "logit_minmax",
            "articulated_iterations": 2,
            "physics_smooth_enabled": True,
        },
        "poses": {"0": {"Bone_000": {"x": 0.1}}},
    }
    assert clip_result_matches_current_keep(current) is True
    missing_whole = {
        "solver": current["solver"],
        "config": {key: value for key, value in current["config"].items() if key != "joint_temporal_consensus_whole_pose"},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(missing_whole) is False
    missing_yaw = {
        "solver": current["solver"],
        "config": {
            key: value
            for key, value in current["config"].items()
            if key != "root_rotation_camera_up_limit_deg"
        },
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(missing_yaw) is False
    missing_defer = {
        "solver": current["solver"],
        "config": {
            key: value
            for key, value in current["config"].items()
            if key != "root_rotation_defer_camera_up"
        },
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(missing_defer) is False
    dinov3_only = {
        "solver": current["solver"],
        "config": {**current["config"], "score_mode": "dinov3_dense"},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(dinov3_only) is False
    chain_space = {
        "solver": current["solver"],
        "config": {**current["config"], "chain_space_enabled": True},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(chain_space) is False
    motion_led = {
        "solver": current["solver"],
        "config": {**current["config"], "motion_weight": 1.0},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(motion_led) is False
    sprite_aligned = {
        "solver": current["solver"],
        "config": {**current["config"], "sprite_aligned_motion_keep_enabled": True},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(sprite_aligned) is False
    raw_norm = {
        "solver": current["solver"],
        "config": {**current["config"], "joint_step_score_norm": "raw"},
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(raw_norm) is False
    missing_norm = {
        "solver": current["solver"],
        "config": {
            key: value
            for key, value in current["config"].items()
            if key != "joint_step_score_norm"
        },
        "poses": current["poses"],
    }
    assert clip_result_matches_current_keep(missing_norm) is False
    assert float(CURRENT_CASCADE_KEEP["root_rotation_camera_up_limit_deg"]) == 45.0
    assert bool(CURRENT_CASCADE_KEEP["root_rotation_defer_camera_up"]) is True
    assert str(CURRENT_CASCADE_KEEP["joint_step_score_norm"]) == "logit_minmax"
    assert "temporal_loop_wrap_enabled" not in CURRENT_CASCADE_KEEP

    if not MESH.is_file():
        raise FileNotFoundError(f"crusader smartrig mesh is missing: {MESH}")
    identity = {0: {}, 1: {"Bone_000": {"x": 0.25, "y": 0.0, "z": 0.0}}}
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        master = write_oriented_master_glb(MESH, out_dir / "master.glb")
        master_doc = _read_glb_json(out_dir / "master.glb")
        orientation = next(node for node in master_doc["nodes"] if node.get("name") == "Orientation")
        assert orientation["children"], orientation
        clip = write_oriented_clip_glb(
            MESH,
            out_dir / "Crusader_Move.glb",
            identity,
            clip_name="Crusader_Move",
        )
        clip_doc = _read_glb_json(out_dir / "Crusader_Move.glb")
        animations = clip_doc.get("animations") or []
        assert len(animations) == 1, animations
        assert animations[0]["name"] == "Crusader_Move"
        assert len(animations[0]["channels"]) == len(clip_doc["skins"][0]["joints"])
        assert any(node.get("name") == "Orientation" for node in clip_doc["nodes"])
        assert clip["frameCount"] == 2
        assert clip["sourceFrameCount"] == 2
        assert clip["keyCount"] == 3
        assert clip["lifecycleRole"] == "cycle"
        assert math.isclose(clip["durationSeconds"], 2.0 / 12.0)
        clip_doc_full, clip_bin = _read_glb_json_and_bin(out_dir / "Crusader_Move.glb")
        bone000 = _glb_rotation_channel(clip_doc_full, clip_bin, "Bone_000")
        rest_node = next(node for node in clip_doc_full["nodes"] if node.get("name") == "Bone_000")
        rest_quat = np.asarray(rest_node.get("rotation", (0.0, 0.0, 0.0, 1.0)), dtype=np.float64)
        rest_quat /= float(np.linalg.norm(rest_quat))
        expected_frame1 = _quat_multiply(
            rest_quat, _axis_angle_quaternion_np(np.asarray((math.radians(0.25), 0.0, 0.0)))
        )
        assert np.allclose(bone000[0].astype(np.float64), rest_quat, atol=1e-6), bone000[0]
        assert np.allclose(
            bone000[1].astype(np.float64), expected_frame1, atol=1e-6
        ), (bone000[1], expected_frame1)
        assert bone000.shape[0] == 3
        assert np.allclose(bone000[2].astype(np.float64), bone000[0].astype(np.float64), atol=1e-6)
        assert Path(master["master"]).is_file()
        albedo = out_dir / ALBEDO_JPEG_NAME
        normal = out_dir / NORMAL_PNG_NAME
        metal = out_dir / METALLIC_GLOSS_PNG_NAME
        assert albedo.is_file(), master
        assert normal.is_file(), master
        assert metal.is_file(), master
        assert master["albedo"]["width"] == 4096
        assert master["albedo"]["height"] == 4096
        assert master["pbr"]["normal"]["width"] == 4096
        assert master["pbr"]["metallicGloss"]["width"] == 4096
        payload, mime = glb_basecolor_image_payload(MESH)
        assert mime == "image/png"

        with Image.open(io.BytesIO(payload)) as source, Image.open(albedo) as jpeg:
            source_rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
            jpeg_rgb = np.asarray(jpeg.convert("RGB"), dtype=np.float32)
        mae = float(np.mean(np.abs(source_rgb - jpeg_rgb)))
        assert mae < 8.0, mae
        packed = np.asarray(Image.open(metal).convert("RGBA"))
        assert packed.shape[2] == 4
        assert int(packed[..., 3].max()) > 0

    orm = np.zeros((2, 2, 4), dtype=np.uint8)
    orm[..., 1] = 64
    orm[..., 2] = 200
    orm[..., 3] = 255
    packed_test = np.asarray(pack_gltf_metallic_roughness_to_unity_metallic_gloss(Image.fromarray(orm, "RGBA")))
    assert packed_test[0, 0, 0] == 200
    assert packed_test[0, 0, 3] == 191

    from run_crusader_gpu_cascade_animation_set import _expected_def_frame_count

    assert _expected_def_frame_count(8) == 8
    assert _expected_def_frame_count((8, 2, 8)) == 18
    assert _expected_def_frame_count([2]) == 2
    from gpu_raster_depth_animation import cascade_optimize_root_rotation

    assert cascade_optimize_root_rotation(
        root_search_enabled=False,
        root_rotation_defer_camera_up=True,
    ) is True
    assert cascade_optimize_root_rotation(
        root_search_enabled=False,
        root_rotation_defer_camera_up=False,
    ) is False

    keep_kwargs = apply_current_cascade_keep(
        {
            "score_mode": "dinov3_dense",
            "physics_smooth_enabled": False,
            "articulated_iterations": 1,
            "silhouette_weight": 0.00001,
            "depth_weight": 0.000001,
            "chroma_weight": 0.000001,
            "collision_enabled": False,
            "chain_space_enabled": True,
            "motion_weight": 1.0,
        }
    )
    assert clip_result_matches_current_keep(
        {"solver": "cascade", "config": keep_kwargs, "poses": {"0": {"Bone_000": {"x": 0.0}}}}
    )
    assert keep_kwargs["score_mode"] == "geometry"
    assert keep_kwargs["physics_smooth_enabled"] is True
    assert int(keep_kwargs["articulated_iterations"]) == int(CURRENT_CASCADE_KEEP["articulated_iterations"])

    assert SKIPPED_DEF_GROUPS == frozenset({7, 8, 11, 13, 14, 16})
    assert 7 not in CONTRACT_BY_GROUP and 8 not in CONTRACT_BY_GROUP
    assert 11 not in CONTRACT_BY_GROUP and 13 not in CONTRACT_BY_GROUP
    assert "Crusader_TurnLeft" not in CONTRACT_BY_GROUP.values()
    assert "Crusader_TurnRight" not in CONTRACT_BY_GROUP.values()
    assert "Crusader_AttackUp" not in CONTRACT_BY_GROUP.values()
    assert "Crusader_AttackDown" not in CONTRACT_BY_GROUP.values()
    assert CONTRACT_BY_GROUP[2] == "Crusader_Idle"

    missing_contracts = []
    for path in LAB_BUILDERS:
        text = path.read_text(encoding="utf-8")
        if "gpu_cascade_skinned" not in text:
            missing_contracts.append(f"{path}: missing gpu_cascade_skinned path")
            continue
        for contract in CONTRACT_BY_GROUP.values():
            if f"{contract}.glb" not in text:
                missing_contracts.append(f"{path}: missing {contract}.glb")
        if "Crusader_TurnLeft.glb" in text or "Crusader_TurnRight.glb" in text:
            missing_contracts.append(f"{path}: still ships skipped turn DEF clips")
        if "DeliveryAlbedoSource" not in text or "File.Copy(DeliveryAlbedoSource" not in text:
            missing_contracts.append(f"{path}: does not copy the ship-mesh albedo into the lab jpg")
        if "DeliveryNormalSource" not in text or "File.Copy(DeliveryNormalSource" not in text:
            missing_contracts.append(f"{path}: does not copy the ship-mesh normal into the lab png")
        if "DeliveryMetallicGlossSource" not in text or "File.Copy(DeliveryMetallicGlossSource" not in text:
            missing_contracts.append(f"{path}: does not copy the ship-mesh metallic-gloss into the lab png")
        if "owned_bind\\crusader_master_rigid_components.glb" in text or "g00_move_fixed_length" in text:
            missing_contracts.append(f"{path}: still points at the broken owned-bind mesh/clips")
    if missing_contracts:
        raise AssertionError("; ".join(missing_contracts))

    return {
        "ok": True,
        "locomotionGroups": sorted(delivered),
        "attackFrames": 7,
        "clipJoints": clip["jointCount"],
    }


if __name__ == "__main__":
    print(run())
