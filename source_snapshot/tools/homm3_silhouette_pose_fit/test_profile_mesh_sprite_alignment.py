"""Profile mesh-sprite alignment metrics (hard gate abandoned 2026-08-23)."""
from __future__ import annotations

from gpu_profile_camera_initializer import (
    PROFILE_MESH_MIN_ALIGNMENT_SUM,
    PROFILE_MESH_MIN_ORIENTATION_IOU,
    PROFILE_MESH_SPRITE_GATE_ENABLED,
    ProfileMeshSpriteMismatchError,
    assert_profile_mesh_sprite_alignment,
)


def _metrics(*, orientation_iou: float, chroma_quality: float) -> dict[str, float]:
    return {
        "orientationIoU": orientation_iou,
        "chromaQuality": chroma_quality,
        "alignmentSum": orientation_iou + chroma_quality,
        "minOrientationIoU": PROFILE_MESH_MIN_ORIENTATION_IOU,
        "minAlignmentSum": PROFILE_MESH_MIN_ALIGNMENT_SUM,
        "passed": (
            orientation_iou >= PROFILE_MESH_MIN_ORIENTATION_IOU
            and (orientation_iou + chroma_quality) >= PROFILE_MESH_MIN_ALIGNMENT_SUM
        ),
    }


def run() -> dict[str, object]:
    assert PROFILE_MESH_SPRITE_GATE_ENABLED is False

    gremlin = _metrics(orientation_iou=0.539, chroma_quality=0.524)
    assert not gremlin["passed"]
    # Soft-miss only: must not raise while the gate is abandoned.
    assert_profile_mesh_sprite_alignment(
        gremlin,
        src_glb="h3_goblin_smartrigged.glb",
        target_frame_dir="frames_def12_nn_idle_shadow_culled",
    )

    restored_batch_res = _metrics(orientation_iou=0.55, chroma_quality=0.574)
    assert not restored_batch_res["passed"]

    restored_low_res = _metrics(orientation_iou=0.565, chroma_quality=0.621)
    assert restored_low_res["passed"]

    roc = _metrics(orientation_iou=0.879, chroma_quality=0.824)
    assert roc["passed"]
    assert_profile_mesh_sprite_alignment(
        roc,
        src_glb="h3_roc_smartrigged.glb",
        target_frame_dir="frames_def12_nn_idle_shadow_culled",
    )

    broken = _metrics(orientation_iou=0.30, chroma_quality=0.70)
    assert not broken["passed"]
    assert_profile_mesh_sprite_alignment(
        broken,
        src_glb="broken.glb",
        target_frame_dir="frames",
    )
    return {"ok": True, "gateEnabled": PROFILE_MESH_SPRITE_GATE_ENABLED}


if __name__ == "__main__":
    print(run())
