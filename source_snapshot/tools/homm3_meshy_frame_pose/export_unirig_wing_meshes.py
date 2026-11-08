"""Export wing-only meshes so UniRig can be asked to rig wing geometry by itself."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
from owned_rerig.glb_io import load_mesh, write_unskinned_mesh  # noqa: E402

# Labels were authored on the Z-up stripped mesh (same vertex order as that file).
MESH = ROOT / "artifacts" / "angel_pose_pipeline" / "owned_bind" / "mesh_stripped.glb"
LABELS = ROOT / "artifacts" / "angel_pose_pipeline" / "part_labels.json"
OUT = ROOT / "artifacts" / "angel_pose_pipeline" / "unirig" / "wing_only"


def _remap_faces(indices: np.ndarray, keep: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    old_to_new = np.full(len(keep), -1, dtype=np.int64)
    old_to_new[keep] = np.arange(int(keep.sum()), dtype=np.int64)
    faces = indices.reshape(-1, 3)
    mapped = old_to_new[faces]
    valid = (mapped >= 0).all(axis=1)
    return mapped[valid].astype(np.int64).reshape(-1), keep


def main() -> None:
    mesh = load_mesh(MESH)
    labels = np.array(json.loads(LABELS.read_text(encoding="utf-8"))["labels"], dtype=np.int32)
    if len(labels) != len(mesh.positions):
        raise ValueError(f"label count {len(labels)} != verts {len(mesh.positions)}")
    names = ["body", "wing_left", "wing_right", "sword"]
    counts = {names[i]: int((labels == i).sum()) for i in range(4)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "label_counts.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    examples = ROOT / "tools" / "third_party" / "UniRig" / "examples"
    for part, idx in (("wing_left", 1), ("wing_right", 2), ("wings", None)):
        keep = (labels == idx) if idx is not None else ((labels == 1) | (labels == 2))
        faces, _ = _remap_faces(mesh.indices, keep)
        dest = OUT / f"h3_angel_{part}.glb"
        write_unskinned_mesh(dest, mesh.positions[keep], faces)
        linked = examples / f"h3_angel_{part}.glb"
        linked.write_bytes(dest.read_bytes())
        print(part, int(keep.sum()), "verts", dest)


if __name__ == "__main__":
    main()
