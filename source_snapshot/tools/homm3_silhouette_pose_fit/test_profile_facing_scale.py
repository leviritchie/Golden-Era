"""Profile init: scale, weak facing, chroma near-tie orientation pick."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from gpu_profile_camera_initializer import (
    PROFILE_CHROMA_WEIGHT,
    PROFILE_FACING_WEIGHT,
    PROFILE_MIN_PROFILE_FACING,
    PROFILE_SILHOUETTE_NEAR_TIE,
    _character_ground_forward,
    _fit_scale_and_offset,
    _profile_facing_score,
    _silhouette_selection_score,
    select_profile_orientation_candidate,
)
from roc_geometric_proxy import load_asset


def run() -> dict[str, object]:
    vertices = np.asarray(
        ((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 2.0, 0.0)),
        dtype=np.float32,
    )
    target = {
        "width": 10.0,
        "height": 20.0,
        "centerX": 5.0,
        "centerY": 10.0,
    }
    px, _offset = _fit_scale_and_offset(
        vertices,
        target,
        np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
        np.asarray((0.0, -1.0, 0.0), dtype=np.float32),
        np.asarray((1.0, 1.0), dtype=np.float32),
        1.0,
    )
    assert abs(float(px[1]) - 10.0) < 1e-5, px
    assert abs(float(px[0]) - 10.0) < 1e-5, px

    face = np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
    assert abs(_profile_facing_score(face, (0.0, 0.0, 1.0)) - 1.0) < 1e-6
    assert _profile_facing_score(face, (1.0, 0.0, 0.0)) < 1e-6
    assert _profile_facing_score(face, (0.0, 0.0, -1.0)) < 1e-6

    # Weak facing can still break a small silhouette gap in the composite score,
    # but must not override a clear silhouette win (pikeman failure mode).
    frontish, _ = _silhouette_selection_score(
        silhouette_score=0.63,
        geometry_score=0.0,
        character_forward=face,
        right=np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
        camera_basis_mode="upright_turntable",
        chroma_quality=0.0,
        chroma_weight=0.0,
    )
    side, _ = _silhouette_selection_score(
        silhouette_score=0.61,
        geometry_score=0.0,
        character_forward=face,
        right=np.asarray((0.0, 0.0, 1.0), dtype=np.float32),
        camera_basis_mode="upright_turntable",
        chroma_quality=0.0,
        chroma_weight=0.0,
    )
    assert side > frontish, (side, frontish)
    assert abs(side - (0.61 + PROFILE_FACING_WEIGHT)) < 1e-6
    clear_sil, _ = _silhouette_selection_score(
        silhouette_score=0.70,
        geometry_score=0.0,
        character_forward=face,
        right=np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
        camera_basis_mode="upright_turntable",
        chroma_quality=0.0,
        chroma_weight=0.0,
    )
    assert clear_sil > side, (clear_sil, side)
    assert PROFILE_FACING_WEIGHT <= 0.05 + 1e-9

    # Gargoyle-shaped near-tie: slightly worse silhouette, better chroma wins.
    back = {
        "yawDeg": -75.0,
        "rollDeg": 0.0,
        "silhouetteScore": 0.8018,
        "iou": 0.760,
        "chromaQuality": 0.794,
        "facingScore": 0.747,
        "score": 1.10,
        "screenUpWorldAlignment": 1.0,
    }
    front_view = {
        "yawDeg": 15.0,
        "rollDeg": 0.0,
        "silhouetteScore": 0.7909,
        "iou": 0.757,
        "chromaQuality": 0.796,
        "facingScore": 0.664,
        "score": 1.08,
        "screenUpWorldAlignment": 1.0,
    }
    far = {
        "yawDeg": 105.0,
        "rollDeg": 0.0,
        "silhouetteScore": 0.70,
        "iou": 0.65,
        "chromaQuality": 0.90,
        "facingScore": 0.0,
        "score": 1.20,
        "screenUpWorldAlignment": 1.0,
    }
    picked, diag = select_profile_orientation_candidate(
        [back, front_view, far],
        silhouette_near_tie=PROFILE_SILHOUETTE_NEAR_TIE,
        chroma_enabled=True,
    )
    assert picked["yawDeg"] == 15.0, (picked, diag)
    assert diag["selectionRule"] == "near_tie_profile_facing_then_chroma_on_silhouetteScore"
    assert diag["nearTieCount"] == 2

    # Goblin-shaped: chroma prefers a rear yaw; facing floor must keep screen-right.
    rear = {
        "yawDeg": -120.0,
        "rollDeg": 8.0,
        "silhouetteScore": 0.6982,
        "iou": 0.618,
        "chromaQuality": 0.649,
        "facingScore": 0.058,
        "score": 0.70,
        "screenUpWorldAlignment": 0.99,
    }
    profile = {
        "yawDeg": 0.0,
        "rollDeg": -8.0,
        "silhouetteScore": 0.7057,
        "iou": 0.62,
        "chromaQuality": 0.615,
        "facingScore": 0.827,
        "score": 0.92,
        "screenUpWorldAlignment": 0.99,
    }
    face_left = {
        "yawDeg": 60.0,
        "rollDeg": -8.0,
        "silhouetteScore": 0.6985,
        "iou": 0.617,
        "chromaQuality": 0.628,
        "facingScore": 0.0,
        "score": 0.92,
        "screenUpWorldAlignment": 0.99,
    }
    picked_g, diag_g = select_profile_orientation_candidate(
        [rear, profile, face_left],
        silhouette_near_tie=PROFILE_SILHOUETTE_NEAR_TIE,
        chroma_enabled=True,
    )
    assert picked_g["yawDeg"] == 0.0, (picked_g, diag_g)
    assert float(picked_g["facingScore"]) >= 0.35

    # Pikeman-shaped: higher silhouette outside facing lock wins via primary sil.
    locked = {
        "yawDeg": -30.0,
        "rollDeg": -8.0,
        "silhouetteScore": 0.4569,
        "iou": 0.35,
        "chromaQuality": 0.324,
        "facingScore": 0.998,
        "score": 0.90,
        "screenUpWorldAlignment": 0.99,
    }
    frontish = {
        "yawDeg": 45.0,
        "rollDeg": -8.0,
        "silhouetteScore": 0.4975,
        "iou": 0.44,
        "chromaQuality": 0.413,
        "facingScore": 0.202,
        "score": 0.70,
        "screenUpWorldAlignment": 0.99,
    }
    picked2, diag2 = select_profile_orientation_candidate(
        [locked, frontish],
        silhouette_near_tie=PROFILE_SILHOUETTE_NEAR_TIE,
        chroma_enabled=True,
    )
    assert picked2["yawDeg"] == 45.0, (picked2, diag2)

    world_up = np.asarray((0.0, 1.0, 0.0), dtype=np.float32)
    root = Path(r"V:/Games/Olden Era Playtest Tweak/artifacts/meshy_downloads")
    live = {}
    for name in ("h3_hobgoblin_smartrigged_rigidized.glb", "h3_crusader_smartrigged_rigidized.glb"):
        path = root / name
        if not path.is_file():
            continue
        forward = _character_ground_forward(load_asset(path), world_up)
        assert abs(float(forward[1])) < 0.05, forward
        assert float(forward[2]) > 0.9, forward
        live[name] = [round(float(value), 3) for value in forward]
    return {
        "ok": True,
        "live": live,
        "facingWeight": PROFILE_FACING_WEIGHT,
        "chromaWeight": PROFILE_CHROMA_WEIGHT,
        "silhouetteNearTie": PROFILE_SILHOUETTE_NEAR_TIE,
        "minProfileFacing": PROFILE_MIN_PROFILE_FACING,
    }


if __name__ == "__main__":
    print(run())
