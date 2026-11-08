"""Scissors: a mixed-influence triangle that rubber-bands in a shipped pose is cut; rigid ones stay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clip_stretched_triangles import clip_stretched_triangles, find_stretched_triangles  # noqa: E402
from roc_geometric_proxy import clear_asset_cache, load_asset, validate_bind_pose  # noqa: E402
from sprite_body_surgery import save_glb, skinned_triangle_faces, load_glb  # noqa: E402


def _write_two_bone_glb(path: Path) -> Path:
    """Root at origin, Bone_A at y=1. Triangle 0 is root-rigid, 1 is bone-rigid, 2 spans the joint
    with its bone-owned corner folded back toward the root so a 180° swing stretches it 3x."""
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0), (0.2, 0.0, 0.0), (0.0, 0.2, 0.0),  # root-owned
            (0.0, 0.5, 0.0),                                    # bone-owned, folded below the joint
            (0.0, 1.5, 0.0), (0.2, 1.5, 0.0), (0.0, 2.0, 0.0),  # bone-owned
        ),
        dtype=np.float32,
    )
    indices = np.asarray((0, 1, 2, 4, 5, 6, 0, 1, 3), dtype=np.uint16)
    joints = np.zeros((7, 4), dtype=np.uint16)
    joints[3:, 0] = 1
    weights = np.zeros((7, 4), dtype=np.float32)
    weights[:, 0] = 1.0
    # glTF matrices are column-major: the flat 16 floats list columns, so translation y sits at
    # flat index 13, i.e. [row 3, col 1] of the row-major numpy view that gets serialized.
    ibm = np.stack([np.eye(4, dtype=np.float32), np.eye(4, dtype=np.float32)])
    ibm[1, 3, 1] = -1.0

    chunks: list[bytes] = []

    def add(array: np.ndarray) -> int:
        while sum(len(c) for c in chunks) % 4:
            chunks.append(b"\x00")
        start = sum(len(c) for c in chunks)
        chunks.append(np.asarray(array).tobytes())
        return start

    offsets = [add(positions), add(indices), add(joints), add(weights), add(ibm.reshape(-1))]
    blob = bytearray(b"".join(chunks))
    sizes = [positions.nbytes, indices.nbytes, joints.nbytes, weights.nbytes, ibm.nbytes]
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": o, "byteLength": s} for o, s in zip(offsets, sizes)],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 7, "type": "VEC3",
             "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5123, "count": 9, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5123, "count": 7, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5126, "count": 7, "type": "VEC4"},
            {"bufferView": 4, "componentType": 5126, "count": 2, "type": "MAT4"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 2, "WEIGHTS_0": 3}, "indices": 1}]}],
        "nodes": [
            {"name": "Root", "children": [1, 2], "translation": [0.0, 0.0, 0.0]},
            {"name": "Bone_A", "translation": [0.0, 1.0, 0.0]},
            {"name": "Mesh", "mesh": 0, "skin": 0},
        ],
        "skins": [{"joints": [0, 1], "inverseBindMatrices": 4}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    save_glb(path, doc, blob)
    return path


def _payload(*poses):
    return {"poseUnits": "degrees", "poses": {str(i): dict(p) for i, p in enumerate(poses)}}


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mesh = _write_two_bone_glb(root / "bar.glb")
        clear_asset_cache()
        swing = _payload({}, {"Bone_A": {"x": 0.0, "y": 0.0, "z": 180.0}})
        rest_only = _payload({}, {"Bone_A": {"x": 0.0, "y": 0.0, "z": 5.0}})

        # Root and Bone_A are parent/child: the stretched triangle is neighbour skin and is kept by default.
        scan = find_stretched_triangles(mesh, [("swing", swing)])
        assert scan["cut"].tolist() == [False, False, False], scan["cut"]
        assert scan["stretchedKept"].tolist() == [False, False, True], scan["stretchedKept"]
        # Treating any two distinct bones as far apart turns it into a strand.
        scan = find_stretched_triangles(mesh, [("swing", swing)], max_bone_distance=0)
        assert scan["cut"].tolist() == [False, False, True], scan["cut"]
        # longest posed edge (v1->v3 swung to y=1.5: 1.513) over longest bind edge (v1->v3: 0.539)
        assert 2.7 < scan["worstRatio"][2] < 2.9, scan["worstRatio"]
        assert scan["worstFrame"][2] == ("swing", "1"), scan["worstFrame"]

        # A gentle pose stretches nothing.
        dest_none = root / "none.glb"
        report = clip_stretched_triangles(mesh, dest_none, [("gentle", rest_only)], preview_png=root / "none.png", max_bone_distance=0)
        assert report["cutTriangles"] == 0, report
        assert (root / "none.png").is_file()

        # The strand is cut; rigid triangles and the skin/bind survive untouched.
        dest = root / "cut.glb"
        report = clip_stretched_triangles(
            mesh, dest, [("gentle", rest_only), ("swing", swing)], preview_png=root / "cut.png", max_cut_fraction=0.5, max_bone_distance=0
        )
        assert report["cutTriangles"] == 1 and report["triangles"] == 3, report
        assert report["cut"][0]["worstFrame"] == ["swing", "1"], report["cut"]
        clear_asset_cache()
        faces = skinned_triangle_faces(*load_glb(dest))
        assert faces.tolist() == [[0, 1, 2], [4, 5, 6]], faces
        assert validate_bind_pose(load_asset(dest))["ok"]

        # Too much cutting is a rig fault, not strands: refuse.
        _raises(RuntimeError, lambda: clip_stretched_triangles(mesh, root / "refuse.glb", [("swing", swing)], max_cut_fraction=0.1, max_bone_distance=0))
        _raises(RuntimeError, lambda: clip_stretched_triangles(mesh, root / "units.glb", [("bad", {"poses": {"0": {}}})]))
        _raises(ValueError, lambda: clip_stretched_triangles(mesh, root / "empty.glb", []))
    print("test_clip_stretched_triangles: ok")


if __name__ == "__main__":
    run()
