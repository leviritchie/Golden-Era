"""CPU diagnostic: rotate only the source coordinate frame, holding target fixed.

This measures a property of the current retargeter. It does not establish the
cause of a particular rendered clip's errors or change the production solver.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.spatial.transform import Rotation

from reconstruct_adapted import reconstruct_adapted


def diagnose():
    parents = np.array([-1, 0, 0, 1, 2])
    names = ["root", "a", "b", "c", "d"]
    offsets = np.array([
        [0, 0, 0], [.3, .9, .1], [-.4, .5, .3],
        [.6, .2, .1], [-.3, .1, .7],
    ])
    fitted_offsets = offsets * np.array([[1], [1.2], [.8], [.9], [1.1]])

    def fk(local):
        positions = np.zeros((5, 3))
        world = np.zeros((5, 3, 3))
        for index, parent in enumerate(parents):
            if parent < 0:
                world[index] = local[index]
                positions[index] = offsets[index]
            else:
                world[index] = world[parent] @ local[index]
                positions[index] = positions[parent] + world[parent] @ offsets[index]
        return positions

    local = np.tile(np.eye(3), (3, 5, 1, 1))
    local[1, 1] = Rotation.from_euler("xyz", [23, -14, 36], degrees=True).as_matrix()
    local[1, 2] = Rotation.from_euler("xyz", [-16, 8, -11], degrees=True).as_matrix()
    local[2, 1] = Rotation.from_euler("xyz", [-21, 32, 7], degrees=True).as_matrix()
    capture = np.stack([fk(frame) for frame in local])
    rotation = Rotation.from_euler("xyz", [37, 21, 13], degrees=True).as_matrix()

    def run(positions, source_offsets):
        return reconstruct_adapted(
            capture_positions=positions, capture_reference_positions=positions[0],
            capture_offsets=source_offsets, fitted_offsets=fitted_offsets,
            parents=parents, names=names, hub_names=("root", "a", "b"),
        )

    baseline = run(capture, offsets)
    rotated = run(capture @ rotation.T, offsets @ rotation.T)
    # Outputs are already in the same fixed target frame: do not rotate back.
    return {
        "fixture": "three_frame_articulated_source_fixed_target",
        "directPositionMaxError": float(np.max(np.abs(baseline["positions"] - rotated["positions"]))),
        "directLocalRotationMaxError": float(np.max(np.abs(baseline["localRotation"] - rotated["localRotation"]))),
        "baselinePositionChange": float(np.max(np.abs(baseline["positions"] - baseline["positions"][0]))),
        "proof": "isolated_math_diagnostic_not_clip_causality",
    }


if __name__ == "__main__":
    print(json.dumps(diagnose(), indent=2))
