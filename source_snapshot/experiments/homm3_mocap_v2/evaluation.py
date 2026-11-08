"""Mocap-only evaluation cases. Separate from historical CASES defaults."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paths import EXPERIMENT, MESHY, POSE_RUNS


@dataclass(frozen=True)
class EvaluationCase:
    key: str
    unit: str
    clip: str
    role: str
    mesh: Path
    frames: Path
    idle: Path
    joint_names: Path
    source_facing: tuple[float, float, float]
    available: bool
    cyclic: bool
    idle_canvas_matches_clip: bool = True
    unavailable_reason: str | None = None


def _case(
    *,
    key: str,
    unit: str,
    clip: str,
    role: str,
    mesh: Path,
    frames: Path,
    idle: Path,
    joint_names: Path,
    source_facing: tuple[float, float, float],
    cyclic: bool,
) -> EvaluationCase:
    def _fail(reason: str) -> EvaluationCase:
        return EvaluationCase(
            key=key,
            unit=unit,
            clip=clip,
            role=role,
            mesh=mesh,
            frames=frames,
            idle=idle,
            joint_names=joint_names,
            source_facing=source_facing,
            available=False,
            cyclic=cyclic,
            idle_canvas_matches_clip=False,
            unavailable_reason=reason,
        )

    if not frames.is_dir():
        return _fail(f"clip frame directory is missing: {frames}")
    if not idle.is_file():
        return _fail(f"idle frame is missing: {idle}")
    from PIL import Image

    clip_pngs = sorted(path for path in frames.glob("*.png") if path.stem.isdigit())
    if not clip_pngs:
        return _fail(f"no numbered PNG frames in {frames}")
    clip_sizes = {Image.open(path).size for path in clip_pngs}
    idle_size = Image.open(idle).size
    if len(clip_sizes) != 1:
        return _fail(f"clip canvas sizes are not identical: {clip_sizes}")
    clip_size = next(iter(clip_sizes))
    idle_matches = clip_size == idle_size
    return EvaluationCase(
        key=key,
        unit=unit,
        clip=clip,
        role=role,
        mesh=mesh,
        frames=frames,
        idle=idle,
        joint_names=joint_names,
        source_facing=source_facing,
        available=True,
        cyclic=cyclic,
        idle_canvas_matches_clip=idle_matches,
        unavailable_reason=None,
    )


CRUSADER_MESH = MESHY / "h3_crusader_smartrigged.glb"
ROC_MESH = MESHY / "h3_roc_smartrigged.glb"
BEHOLDER_MESH = MESHY / "h3_beholder_smartrigged.glb"

EVALUATION_CASES = {
    "crusader_attack": _case(
        key="crusader_attack",
        unit="h3_crusader",
        clip="attack_front_g12",
        role="development",
        mesh=CRUSADER_MESH,
        frames=POSE_RUNS / "h3_crusader" / "attack_front_g12" / "frames_ground_truth_shadow_culled",
        idle=POSE_RUNS / "h3_crusader" / "idle_g2" / "frames_ground_truth_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "crusader_joint_names.json",
        source_facing=(0.0, 0.0, 1.0),
        cyclic=False,
    ),
    "roc_flight": _case(
        key="roc_flight",
        unit="h3_roc",
        clip="move",
        role="development",
        mesh=ROC_MESH,
        frames=POSE_RUNS / "h3_roc" / "move" / "frames_def12_nn_move_shadow_culled",
        idle=POSE_RUNS / "h3_roc" / "idle" / "frames_def12_nn_idle_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "roc_joint_names.json",
        source_facing=(0.0, 0.0, 1.0),
        cyclic=True,
    ),
    "beholder_attack": _case(
        key="beholder_attack",
        unit="h3_beholder",
        clip="idle_attack_front",
        role="development",
        mesh=BEHOLDER_MESH,
        frames=POSE_RUNS
        / "h3_beholder"
        / "idle_attack_front"
        / "frames_def12_nn_idle_attack_front_shadow_culled",
        idle=POSE_RUNS / "h3_beholder" / "idle" / "frames_def12_nn_idle_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "beholder_joint_names.json",
        source_facing=(0.0, 0.0, -1.0),
        cyclic=False,
    ),
    "crusader_move": _case(
        key="crusader_move",
        unit="h3_crusader",
        clip="move_g0",
        role="holdout",
        mesh=CRUSADER_MESH,
        frames=POSE_RUNS / "h3_crusader" / "move_g0" / "frames_ground_truth_shadow_culled",
        idle=POSE_RUNS / "h3_crusader" / "idle_g2" / "frames_ground_truth_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "crusader_joint_names.json",
        source_facing=(0.0, 0.0, 1.0),
        cyclic=True,
    ),
    "roc_attack": _case(
        key="roc_attack",
        unit="h3_roc",
        clip="idle_attack_front",
        role="holdout",
        mesh=ROC_MESH,
        frames=POSE_RUNS
        / "h3_roc"
        / "idle_attack_front"
        / "frames_def12_nn_idle_attack_front_shadow_culled",
        idle=POSE_RUNS / "h3_roc" / "idle" / "frames_def12_nn_idle_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "roc_joint_names.json",
        source_facing=(0.0, 0.0, 1.0),
        cyclic=False,
    ),
    "beholder_move": _case(
        key="beholder_move",
        unit="h3_beholder",
        clip="move_g0",
        role="holdout",
        mesh=BEHOLDER_MESH,
        frames=POSE_RUNS / "h3_beholder" / "move_g0" / "frames_ground_truth_shadow_culled",
        idle=POSE_RUNS / "h3_beholder" / "idle" / "frames_def12_nn_idle_shadow_culled" / "00.png",
        joint_names=EXPERIMENT / "beholder_joint_names.json",
        source_facing=(0.0, 0.0, -1.0),
        cyclic=True,
    ),
}

DEVELOPMENT_KEYS = ("crusader_attack", "roc_flight", "beholder_attack")
HOLDOUT_KEYS = ("crusader_move", "roc_attack", "beholder_move")
FORBIDDEN_MOCAP_INPUTS = frozenset(
    {
        "clip_recipe",
        "kinematic_memory_recipe",
        "weave",
        "dino_candidate_selection",
        "named_chain_ik",
        "kinematic_clip",
        "direct_fit",
        "rest_bookend_output",
    }
)
