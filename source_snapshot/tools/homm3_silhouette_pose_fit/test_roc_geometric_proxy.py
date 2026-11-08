import json
import struct
from pathlib import Path

import numpy as np

from roc_geometric_proxy import (
    evaluate_batch,
    evaluate_points,
    load_asset,
    point_mask,
    prepare_batch,
    project_points,
    score_masks_batch,
    validate_bind_pose,
)


def _synthetic_glb(path: Path) -> None:
    # One triangle, two-bone skin, interleaved POSITION accessor, accessor offset,
    # and sparse WEIGHTS accessor exercise the host decoder without Blender.
    chunks = bytearray()
    views = []
    accessors = []
    def add(raw, component, typ, count, *, normalized=False, accessor_offset=0):
        offset = len(chunks); chunks.extend(raw)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views)-1, "byteOffset": accessor_offset, "componentType": component, "count": count, "type": typ, "normalized": normalized})
        return len(accessors)-1
    # POSITION starts with a 4-byte prefix, proving accessor byteOffset is honored.
    positions = np.array([[0,0,0],[1,0,0],[0,1,0]], np.float32).tobytes()
    pos_view_offset = len(chunks); chunks.extend(b"ABCD" + positions)
    views.append({"buffer": 0, "byteOffset": pos_view_offset, "byteLength": len(positions)+4})
    accessors.append({"bufferView": len(views)-1, "byteOffset": 4, "componentType": 5126, "count": 3, "type": "VEC3"})
    pos = len(accessors)-1
    joints = add(np.array([[0,0,0,0],[0,0,0,0],[1,0,0,0]], np.uint8).tobytes(), 5121, "VEC4", 3)
    weights = add(np.array([[1,0,0,0],[1,0,0,0],[1,0,0,0]], np.float32).tobytes(), 5126, "VEC4", 3)
    indices = add(np.array([0,1,2], np.uint16).tobytes(), 5123, "SCALAR", 3)
    ibm = np.stack([np.eye(4), np.eye(4)]).astype(np.float32).transpose(0,2,1).tobytes()
    ibm_acc = add(ibm, 5126, "MAT4", 2)
    doc = {"asset":{"version":"2.0"}, "buffers":[{"byteLength":len(chunks)}], "bufferViews":views, "accessors":accessors,
           "nodes":[{"name":"Root","children":[1],"mesh":0,"skin":0},{"name":"Tip","translation":[0,0,0]}],
           "meshes":[{"primitives":[{"attributes":{"POSITION":pos,"JOINTS_0":joints,"WEIGHTS_0":weights},"indices":indices}]}],
           "skins":[{"joints":[0,1],"inverseBindMatrices":ibm_acc}], "scenes":[{"nodes":[0]}], "scene":0}
    raw_json = json.dumps(doc, separators=(",", ":")).encode(); raw_json += b" " * ((4-len(raw_json)%4)%4)
    blob = bytes(chunks); total = 12 + 8 + len(raw_json) + 8 + len(blob)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(raw_json), b"JSON") + raw_json + struct.pack("<I4s", len(blob), b"BIN\x00") + blob)


def test_bind_identity_and_cache(tmp_path):
    path = tmp_path / "synthetic.glb"; _synthetic_glb(path)
    asset = load_asset(path)
    assert load_asset(path) is asset
    assert validate_bind_pose(asset)["ok"]


def test_projection_and_pose_deformation(tmp_path):
    path = tmp_path / "synthetic.glb"; _synthetic_glb(path); asset = load_asset(path)
    cam = {"right":[1,0,0], "up":[0,1,0], "forward":[0,0,1], "pxPerWorld":10, "screenOffset":[5,5]}
    assert np.allclose(project_points(np.array([[1,2,0.]]), cam, width=20, height=20), [[15,25]])
    base = evaluate_points(asset, {"Tip":{"axis":"z","angle":np.pi/2}}, level=1)
    assert np.allclose(base[2], [-1, 0, 0], atol=1e-6)


def test_batch_score(tmp_path):
    path = tmp_path / "synthetic.glb"; _synthetic_glb(path); asset = load_asset(path)
    cam = {"basisScreenRows":[[1,0,0],[0,-1,0]], "pxPerWorld":4, "screenOffset":[4,4]}
    target = point_mask(project_points(evaluate_points(asset), cam, width=8, height=8), width=8, height=8, radius=1)
    result = evaluate_batch(asset, [{}, {"Tip":{"axis":"z","angle":0.1}}], cam, width=8, height=8, target_alpha=target)
    assert result["masks"].shape == (2, 8, 8)
    assert result["scores"][0]["iou"] == 1.0


def test_root_transform_and_batched_limits(tmp_path):
    path = tmp_path / "synthetic.glb"; _synthetic_glb(path); asset = load_asset(path)
    context = {
        "basis": {"lateral": [1, 0, 0], "forward": [0, 0, 1], "vertical": [0, 1, 0]},
        "referenceLengthWorld": 2.0,
        "rotation": {
            "basisVectors": {"camera_forward": [0, 0, 1], "camera_right": [1, 0, 0], "camera_up": [0, 1, 0]},
            "pivot": [0, 0, 0],
        },
    }
    base = evaluate_points(asset, {}, level=1, max_points=2, root_context=context)
    moved = evaluate_points(
        asset,
        {"__motion_root__": {"lateral": 0.5}, "__motion_root_rotation__": {"camera_forward": 90}},
        level=1,
        max_points=2,
        root_context=context,
    )
    assert not np.allclose(base, moved)


def test_prepared_wave_reuses_worlds_across_proxy_levels(tmp_path):
    path = tmp_path / "synthetic.glb"; _synthetic_glb(path); asset = load_asset(path)
    cam = {"basisScreenRows":[[1,0,0],[0,-1,0]], "pxPerWorld":4, "screenOffset":[4,4]}
    poses = [{}, {"Tip":{"axis":"z", "angle":0.1}}]
    target = point_mask(
        project_points(evaluate_points(asset), cam, width=8, height=8),
        width=8,
        height=8,
        radius=1,
    )
    prepared = prepare_batch(asset, poses, device="cpu")
    level0 = evaluate_batch(
        asset, poses, cam, width=8, height=8, level=0,
        target_alpha=target, device="cpu", prepared=prepared,
    )
    level1 = evaluate_batch(
        asset, poses, cam, width=8, height=8, level=1,
        target_alpha=target, device="cpu", prepared=prepared,
    )
    assert level0["preparedBatchReused"]
    assert level1["preparedBatchReused"]
    assert level0["masks"].shape == level1["masks"].shape == (2, 8, 8)
    assert all("iou" in score for score in level0["scores"] + level1["scores"])


def test_score_masks_batch_matches_single_score_shape(tmp_path):
    masks = np.zeros((2, 6, 7), dtype=np.uint8)
    masks[0, 1:3, 2:4] = 1
    masks[1, 3:5, 4:6] = 1
    target = masks[0]
    scores = score_masks_batch(masks, target)
    assert len(scores) == 2
    assert scores[0]["iou"] == 1.0
    assert scores[1]["iou"] < 1.0
