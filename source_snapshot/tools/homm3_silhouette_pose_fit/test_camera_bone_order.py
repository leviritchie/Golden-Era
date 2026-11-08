"""camera_near_to_far bone order: bind depth along the camera-to-subject ray."""
from __future__ import annotations

import numpy as np

from gpu_depth_silhouette_solver import (
    DepthSilhouetteConfig,
    order_indices_camera_near_to_far,
)


def run() -> dict[str, object]:
    DepthSilhouetteConfig(bone_order_mode="camera_near_to_far").validate()
    DepthSilhouetteConfig(bone_order_mode="pose_near_to_far").validate()
    DepthSilhouetteConfig(bone_order_mode="leftover_gravity").validate()
    try:
        DepthSilhouetteConfig(bone_order_mode="camera_sideways").validate()
        raise AssertionError("unknown bone_order_mode must stay fail-closed")
    except ValueError as exc:
        assert "pose_near_to_far" in str(exc), str(exc)

    indices = (10, 11, 12)
    origins = np.array(
        [
            [0.0, 0.0, 5.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 3.0],
        ],
        dtype=np.float64,
    )
    ordered = order_indices_camera_near_to_far(indices, origins, (0.0, 0.0, 1.0))
    assert ordered == (11, 12, 10), ordered

    tied = order_indices_camera_near_to_far(
        (4, 5, 6),
        np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]),
        (0.0, 0.0, 1.0),
    )
    assert tied == (4, 5, 6), tied

    try:
        order_indices_camera_near_to_far(indices, origins, (0.0, 0.0, 0.0))
        raise AssertionError("degenerate camera_forward must be refused")
    except ValueError as exc:
        assert "degenerate" in str(exc), str(exc)

    return {"ok": True, "ordered": list(ordered)}


if __name__ == "__main__":
    print(run())
