"""Synthetic Mixamo-on-horse+rider fixture used when no Cavalier GLB is in-tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .glb_io import write_skinned_mesh, write_unskinned_mesh


def _box(lo: np.ndarray, hi: np.ndarray, steps: int = 4) -> tuple[np.ndarray, np.ndarray]:
    xs = np.linspace(lo[0], hi[0], steps)
    ys = np.linspace(lo[1], hi[1], steps)
    zs = np.linspace(lo[2], hi[2], steps)
    verts = np.array([[x, y, z] for x in xs for y in ys for z in zs], dtype=np.float64)
    faces: list[list[int]] = []

    def idx(ix: int, iy: int, iz: int) -> int:
        return (ix * steps + iy) * steps + iz

    for ix in range(steps - 1):
        for iy in range(steps - 1):
            for iz in range(steps - 1):
                v000 = idx(ix, iy, iz)
                v100 = idx(ix + 1, iy, iz)
                v010 = idx(ix, iy + 1, iz)
                v110 = idx(ix + 1, iy + 1, iz)
                v001 = idx(ix, iy, iz + 1)
                v101 = idx(ix + 1, iy, iz + 1)
                v011 = idx(ix, iy + 1, iz + 1)
                v111 = idx(ix + 1, iy + 1, iz + 1)
                faces.extend(
                    [
                        [v000, v100, v110],
                        [v000, v110, v010],
                        [v001, v011, v111],
                        [v001, v111, v101],
                        [v000, v001, v101],
                        [v000, v101, v100],
                        [v010, v110, v111],
                        [v010, v111, v011],
                    ]
                )
    return verts, np.asarray(faces, dtype=np.int32)


def _append_box(
    pieces: list[tuple[np.ndarray, np.ndarray, str]],
    lo: list[float],
    hi: list[float],
    part: str,
) -> None:
    verts, faces = _box(np.asarray(lo, dtype=np.float64), np.asarray(hi, dtype=np.float64))
    pieces.append((verts, faces, part))


def build_rider_mount_geometry() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pieces: list[tuple[np.ndarray, np.ndarray, str]] = []
    _append_box(pieces, [-0.18, -0.9, 0.18], [0.18, 0.9, 0.55], "horse")
    _append_box(pieces, [-0.12, 0.85, 0.42], [0.12, 1.25, 0.78], "horse")
    _append_box(pieces, [-0.16, 0.55, 0.18], [-0.08, 0.70, 0.40], "horse")
    _append_box(pieces, [-0.16, 0.55, 0.00], [-0.08, 0.70, 0.20], "horse")
    _append_box(pieces, [0.08, 0.55, 0.18], [0.16, 0.70, 0.40], "horse")
    _append_box(pieces, [0.08, 0.55, 0.00], [0.16, 0.70, 0.20], "horse")
    _append_box(pieces, [-0.16, -0.70, 0.18], [-0.08, -0.55, 0.40], "horse")
    _append_box(pieces, [-0.16, -0.70, 0.00], [-0.08, -0.55, 0.20], "horse")
    _append_box(pieces, [0.08, -0.70, 0.18], [0.16, -0.55, 0.40], "horse")
    _append_box(pieces, [0.08, -0.70, 0.00], [0.16, -0.55, 0.20], "horse")
    _append_box(pieces, [-0.10, -0.12, 0.54], [0.10, 0.12, 0.82], "rider")
    _append_box(pieces, [-0.10, -0.12, 0.80], [0.10, 0.12, 1.12], "rider")
    _append_box(pieces, [-0.08, -0.06, 1.10], [0.08, 0.08, 1.28], "rider")
    _append_box(pieces, [-0.22, -0.10, 0.84], [-0.10, 0.02, 0.98], "rider")
    _append_box(pieces, [-0.26, -0.10, 0.70], [-0.14, 0.00, 0.86], "rider")
    _append_box(pieces, [0.10, -0.02, 0.84], [0.22, 0.10, 0.98], "rider")
    _append_box(pieces, [0.14, 0.00, 0.70], [0.26, 0.10, 0.86], "rider")
    _append_box(pieces, [0.08, 0.00, 0.78], [0.12, 0.85, 0.86], "lance")
    _append_box(pieces, [-0.14, -0.08, 0.50], [0.14, 0.08, 0.58], "saddle_band")
    verts = []
    faces = []
    labels = []
    offset = 0
    part_id = {"horse": 0, "rider": 1, "lance": 2, "saddle_band": 3}
    for v, f, part in pieces:
        verts.append(v)
        faces.append(f + offset)
        labels.extend([part_id[part]] * len(v))
        offset += len(v)
    return np.vstack(verts), np.vstack(faces).reshape(-1), np.asarray(labels, dtype=np.int32)


def write_mixamo_rider_mount_fixture(path: Path) -> dict[str, Any]:
    positions, indices, labels = build_rider_mount_geometry()
    bone_names = [
        "mixamorig:Hips",
        "mixamorig:Spine",
        "mixamorig:Head",
        "mixamorig:LeftUpLeg",
        "mixamorig:LeftLeg",
        "mixamorig:LeftFoot",
        "mixamorig:RightUpLeg",
        "mixamorig:RightLeg",
        "mixamorig:RightFoot",
        "mixamorig:LeftArm",
        "mixamorig:RightArm",
    ]
    parents: list[int | None] = [None, 0, 1, 0, 3, 4, 0, 6, 7, 1, 1]
    heads = np.array(
        [
            [0.0, 0.0, 0.40],
            [0.0, 0.05, 0.55],
            [0.0, 0.02, 1.20],
            [-0.12, -0.40, 0.30],
            [-0.12, -0.40, 0.15],
            [-0.12, -0.40, 0.02],
            [0.12, -0.40, 0.30],
            [0.12, -0.40, 0.15],
            [0.12, -0.40, 0.02],
            [-0.18, 0.05, 0.85],
            [0.18, 0.05, 0.85],
        ],
        dtype=np.float64,
    )
    n = len(positions)
    joints = np.zeros((n, 4), dtype=np.int32)
    weights = np.zeros((n, 4), dtype=np.float64)
    weights[:, 0] = 1.0
    for i, label in enumerate(labels):
        if label == 0:
            joints[i, 0] = 3 if positions[i, 1] < 0 else 1
        elif label == 1:
            joints[i, 0] = 1
        else:
            joints[i, 0] = 10
    write_skinned_mesh(
        path,
        positions=positions,
        indices=indices,
        bone_names=bone_names,
        parents=parents,
        heads=heads,
        joints=joints,
        weights=weights,
        extras={"fixture": "synthetic_mixamo_rider_mount", "notAMeshyExport": True},
    )
    return {"output": str(Path(path).resolve()).replace("\\", "/"), "labels": labels.tolist(), "vertexCount": n}


def write_unskinned_rider_mount_fixture(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    positions, indices, labels = build_rider_mount_geometry()
    write_unskinned_mesh(path, positions, indices, extras={"fixture": "synthetic_unskinned_rider_mount"})
    return positions, indices, labels


def authored_part_map_for_fixture() -> dict[str, Any]:
    return {
        "schema": "owned_bind_part_map.v1",
        "method": "human_eye_part_authoring",
        "unitSid": "h3_cavalier",
        "seeds": [
            {"part": "horse", "point": [0.0, 0.0, 0.36]},
            {"part": "horse", "point": [0.0, 1.05, 0.60]},
            {"part": "horse", "point": [-0.12, 0.62, 0.08]},
            {"part": "horse", "point": [0.12, 0.62, 0.08]},
            {"part": "horse", "point": [-0.12, -0.62, 0.08]},
            {"part": "horse", "point": [0.12, -0.62, 0.08]},
            {"part": "rider", "point": [0.0, 0.0, 0.70]},
            {"part": "rider", "point": [0.0, 0.0, 0.95]},
            {"part": "rider", "point": [0.0, 0.0, 1.20]},
            {"part": "rider", "point": [-0.20, -0.04, 0.90]},
            {"part": "rider", "point": [0.20, 0.04, 0.90]},
            {"part": "lance", "point": [0.10, 0.50, 0.82]},
            {"part": "saddle_band", "point": [0.0, 0.0, 0.54]},
        ],
        "expectedShare": {"horse": 0.55, "rider": 0.28},
    }
