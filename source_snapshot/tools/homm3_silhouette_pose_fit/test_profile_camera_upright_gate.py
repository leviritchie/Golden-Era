"""Refuse pitched pose-picker cameras that lay an upright mesh on its side."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gpu_profile_camera_initializer import (
    assert_solver_camera_is_registered_profile,
    minimum_upright_screen_alignment,
    screen_up_world_alignment,
    select_upright_profile_candidates,
)

LIVE_PROVISIONAL = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/h3_crusader/move_g0/roc_sprite_camera_fit.json"
)
LIVE_REGISTERED = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/h3_crusader/move_g0/gpu_depth_silhouette_simple_rife60_nn_idle_start_move/initialization/profile_camera_fit.json"
)


def _candidate(*, score: float, alignment: float, source: str) -> dict[str, float | str]:
    return {
        "score": float(score),
        "screenUpWorldAlignment": float(alignment),
        "source": source,
    }


def run() -> dict[str, object]:
    floor = minimum_upright_screen_alignment(
        camera_basis_mode="upright_turntable",
        roll_range_deg=8.0,
    )
    assert floor is not None and floor > 0.98, floor

    chosen = select_upright_profile_candidates(
        (
            _candidate(score=0.90, alignment=0.30, source="seed_camera"),
            _candidate(score=0.70, alignment=1.00, source="profile_search"),
        ),
        camera_basis_mode="upright_turntable",
        roll_range_deg=8.0,
    )
    assert chosen[0]["source"] == "profile_search", chosen[0]

    try:
        select_upright_profile_candidates(
            (_candidate(score=0.90, alignment=0.30, source="seed_camera"),),
            camera_basis_mode="upright_turntable",
            roll_range_deg=8.0,
        )
        raise AssertionError("a lying-only candidate list must be refused")
    except RuntimeError as exc:
        assert "onto its side" in str(exc), str(exc)

    diagnostic = select_upright_profile_candidates(
        (_candidate(score=0.90, alignment=0.30, source="seed_camera"),),
        camera_basis_mode="seed_screen_up",
        roll_range_deg=8.0,
    )
    assert diagnostic[0]["source"] == "seed_camera"

    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "camera.json"
        path.write_text(
            json.dumps(
                {
                    "cameraPolicy": "provisional_job_camera",
                    "basisScreenRows": [
                        [0.766044443118978, -0.6427876096865393, 0.0],
                        [-0.25061303042546196, -0.2986689793604664, -0.9208636977038154],
                    ],
                }
            ),
            encoding="utf-8",
        )
        assert_solver_camera_is_registered_profile(path, profile_init_enabled=True)
        try:
            assert_solver_camera_is_registered_profile(path, profile_init_enabled=False)
            raise AssertionError("provisional_job_camera must not skip profile_init")
        except RuntimeError as exc:
            assert "provisional_job_camera" in str(exc), str(exc)

        aligned = Path(raw) / "aligned.json"
        aligned.write_text(
            json.dumps(
                {
                    "cameraPolicy": "gpu_profile_initialization",
                    "basisScreenRows": [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
                }
            ),
            encoding="utf-8",
        )
        assert_solver_camera_is_registered_profile(aligned, profile_init_enabled=False)
        assert abs(screen_up_world_alignment([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]]) - 1.0) < 1e-5

    if not LIVE_PROVISIONAL.is_file():
        raise FileNotFoundError(f"live provisional camera is missing: {LIVE_PROVISIONAL}")
    try:
        assert_solver_camera_is_registered_profile(
            LIVE_PROVISIONAL,
            profile_init_enabled=False,
        )
        raise AssertionError("live crusader picker camera must be refused")
    except RuntimeError as exc:
        assert "provisional_job_camera" in str(exc), str(exc)

    if LIVE_REGISTERED.is_file():
        assert_solver_camera_is_registered_profile(
            LIVE_REGISTERED,
            profile_init_enabled=False,
        )
    return {"ok": True}


if __name__ == "__main__":
    print(run())
