"""Preflight for the mocap-only entry point. Fail closed on recipe/weave inputs."""
from __future__ import annotations

import unittest
from pathlib import Path

from evaluation import FORBIDDEN_MOCAP_INPUTS, EvaluationCase
from paths import EXPERIMENT, require_file


MOCAP_STRUCTURAL_TESTS = (
    "test_contract.py",
    "test_native_rotation.py",
    "test_adapter_coordinates.py",
    "test_semantic_names.py",
    "test_review_metrics.py",
    "test_motion_metrics.py",
    "test_temporal_context.py",
    "test_diagnosis_controls.py",
    "test_known_motion.py",
    "test_position_transfer.py",
    "test_mocap_preflight.py",
    "test_vendor_contract.py",
    "test_vendor_reference.py",
    "test_intermediate_fk.py",
    "test_capture_binding.py",
    "test_intermediate_capture.py",
    "test_direction_retarget.py",
    "test_donor_eagle.py",
    "test_reconstruct_ab.py",
    "test_eagle_skinned_roc.py",
    "test_conform_roc.py",
    "test_shape_preserved.py",
)


def refuse_forbidden_inputs(
    *,
    clip_recipe: Path | None = None,
    memory_recipe: Path | None = None,
    weave: bool = False,
    drive: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    if clip_recipe is not None:
        raise ValueError("mocap-only path refuses clip recipes")
    if memory_recipe is not None:
        raise ValueError("mocap-only path refuses kinematic memory recipes")
    if weave:
        raise ValueError("mocap-only path refuses weave refinement")
    if drive in {"named_chain_ik", "kinematic_clip", "weaved", "position_ik"}:
        raise ValueError(
            f"mocap-only path refuses drive {drive!r}; native rotation is the transfer, "
            "position IK is an explicit second diagnostic"
        )
    payload = extra or {}
    for token in FORBIDDEN_MOCAP_INPUTS:
        if payload.get(token):
            raise ValueError(f"mocap-only path refuses forbidden input {token!r}")


def refuse_case_recipes(case: EvaluationCase) -> None:
    refuse_forbidden_inputs()
    if case.joint_names.is_file():
        text = case.joint_names.read_text(encoding="utf-8")
        if '"policy": "weighted_memory_poses"' in text:
            raise ValueError("joint-name file contains a clip recipe")


def refuse_holdout_without_freeze(case: EvaluationCase, *, allow_holdout: bool) -> None:
    if case.role != "holdout":
        return
    if case.available and not allow_holdout:
        raise ValueError(
            f"{case.key} is a holdout case; pass --allow-holdout only after the shared configuration is frozen"
        )


def refuse_smartrig_network_input(*, species: str | None = None, extra: dict[str, object] | None = None) -> None:
    payload = extra or {}
    if payload.get("smartRigNetworkInput") or payload.get("referenceNpz"):
        raise ValueError("intermediate capture refuses SmartRig tensors in the neural-network input")
    if species in {"bind_reference", "smartrig", "h3_crusader", "h3_roc", "h3_beholder"}:
        raise ValueError(
            f"intermediate capture refuses SmartRig species {species!r} as the network skeleton; "
            "use an unmodified vendor reference package"
        )


def refuse_retarget_without_capture_pass(verdict: dict[str, object] | None) -> None:
    if not isinstance(verdict, dict) or verdict.get("proceedToRetarget") is not True:
        raise ValueError(
            "retargeter is gated on a capture that visibly improves the source action; "
            "do not spend solver work making a weak capture look stronger"
        )


def run_structural_tests() -> None:
    suite = unittest.TestSuite()
    for pattern in MOCAP_STRUCTURAL_TESTS:
        path = EXPERIMENT / pattern
        require_file(path, label="required mocap control test")
        discovered = unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern=pattern)
        if not discovered.countTestCases():
            raise RuntimeError(f"no control tests discovered in {pattern}")
        suite.addTests(discovered)
    if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
        raise RuntimeError("mocap structural/control tests failed")


if __name__ == "__main__":
    run_structural_tests()
