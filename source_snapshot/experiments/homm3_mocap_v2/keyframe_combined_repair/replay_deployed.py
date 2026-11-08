"""Replay deployed clips: GLB animation -> joint worlds -> skinned vertices.

Recipe (verified on h3_goblin Unit_Move.glb):
  skeleton = load_bind_skeleton(path)
  times, rotations, translations, info = _serialized_local_rotations(path)
  worlds = gltf_world_matrices(local_rotation=rotations[f],
                               local_translation=skeleton.rest_local_translation,
                               parents=parents)
  posed = skin_vertices(skeleton, worlds)

Notes:
- Deployed clips are rotation-only (25 channels, LINEAR, shared time axis).
- Use ``rest_local_translation``, NOT ``rest_world`` (fk_world_matrices uses a
  different root convention and is off by ~0.49 here).
- Channel->joint mapping must go through ``skeleton.node_indices``
  (``node_to_joint``), even though it is identity on the goblin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# HERE is the module dir: parents[0]=homm3_mocap_v2, [1]=experiments, [2]=repo.
REPO = HERE.parents[2]
EXP = REPO / "experiments" / "homm3_mocap_v2"
# EXP first: sibling mocap modules (eagle_glb, glb_skeleton, ...) win over HERE.
if str(HERE) in sys.path:
    sys.path.remove(str(HERE))
if str(EXP) not in sys.path:
    sys.path.insert(0, str(EXP))
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

from eagle_glb import gltf_world_matrices  # noqa: E402
from glb_skeleton import load_bind_skeleton  # noqa: E402
from mesh_preview import skin_vertices  # noqa: E402
from verify_calibrated_export import _serialized_local_rotations  # noqa: E402


def replay_clip(path: Path) -> dict[str, object]:
    """Replay every keyframe of one deployed clip GLB.

    Returns ``{"skeleton", "times", "worlds" [F,J,4,4], "posed" [F,V,3]}``.
    Motion is read-only: this never writes the GLB.
    """
    path = Path(path)
    skeleton = load_bind_skeleton(path)
    times, rotations, _translations, info = _serialized_local_rotations(path)
    if info.get("translationChannels"):
        raise ValueError(f"{path}: deployed clip must be rotation-only")
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    rest_t = np.asarray(skeleton.rest_local_translation, dtype=np.float64)
    worlds = np.stack(
        [
            gltf_world_matrices(
                local_rotation=np.asarray(rotations[f], dtype=np.float64),
                local_translation=rest_t,
                parents=parents,
            )
            for f in range(len(times))
        ]
    )
    posed = np.stack([skin_vertices(skeleton, worlds[f]) for f in range(len(times))])
    return {
        "skeleton": skeleton,
        "times": np.asarray(times, dtype=np.float64),
        "worlds": worlds,
        "posed": posed,
        "channelInfo": info,
    }


__all__ = ["replay_clip"]
