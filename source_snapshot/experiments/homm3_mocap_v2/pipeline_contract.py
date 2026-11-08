"""Shared provenance contract for the current HoMM3 mocap delivery lane.

This module is deliberately small and data-only.  It keeps the animation
authority explicit so a diagnostic silhouette solver cannot become a delivery
input by accident.
"""
from __future__ import annotations

from typing import Any, Mapping


SCHEMA = "homm3.mocap-pipeline-contract.v1"
LANE = "current_mocap"
MOTION_AUTHORITY = "captured_vendor_positions_fixed_before_skin_fit"
MOTION_RECONSTRUCTION = "shared_idle_reference_fixed_length_rotations"
PRIMARY_MOTION_REPRESENTATION = "capture_positions_v1"
ALLOWED_MOTION_REPRESENTATIONS = frozenset(
    {"capture_positions_v1", "fixed_composed_fk_v1"}
)

# These are the only motion owners that may feed the current raw export lane.
# A source-orientation completion is still explicitly hash-pinned and keeps
# every captured joint position fixed; it is not a new motion generator.
ALLOWED_MOTION_OWNERS = frozenset(
    {
        "frozen_idle_calibrated_adapted_transforms",
        "explicit_source_orientation_completion_fixed_positions",
    }
)

# Match provenance labels, not implementation paths.  The accepted fitter
# imports helpers from the silhouette package, so scanning every path would
# incorrectly reject otherwise valid reports.
FORBIDDEN_MOTION_MARKERS = (
    "fused_push",
    "continuous_tracker",
    "silhouette_pose_search",
    "silhouette_pose_fit",
    "gpu_cascade_animation",
)


def _contains_forbidden(value: Any) -> str | None:
    if isinstance(value, str):
        lowered = value.lower()
        for marker in FORBIDDEN_MOTION_MARKERS:
            if marker in lowered:
                return marker
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            marker = _contains_forbidden(item)
            if marker:
                return marker
    elif isinstance(value, (list, tuple)):
        for item in value:
            marker = _contains_forbidden(item)
            if marker:
                return marker
    return None


def validate_corpus_contract(
    corpus: Mapping[str, Any], *, allow_legacy: bool = True
) -> dict[str, Any]:
    """Validate the immutable capture corpus consumed by the shared fitter.

    Older frozen corpora predate the explicit ``motionRepresentation`` field.
    They remain usable only through this deliberately named legacy mode; new
    producers and strict validators should pass ``allow_legacy=False``.
    """
    if corpus.get("schema") != "homm3.skin-corpus.v1":
        raise ValueError("unsupported mocap corpus schema")
    raw_representation = corpus.get("motionRepresentation")
    legacy_representation = raw_representation in (None, "")
    if legacy_representation and not allow_legacy:
        raise ValueError("mocap corpus must declare motionRepresentation explicitly")
    representation = str(raw_representation or PRIMARY_MOTION_REPRESENTATION)
    if representation not in ALLOWED_MOTION_REPRESENTATIONS:
        raise ValueError(
            f"current mocap lane requires one of {sorted(ALLOWED_MOTION_REPRESENTATIONS)}, got {representation}"
        )
    package = corpus.get("package")
    if not isinstance(package, Mapping):
        raise ValueError("current mocap lane requires a frozen donor package")
    composed_package = (
        representation == "fixed_composed_fk_v1"
        and package.get("kind") == "composed"
        and corpus.get("captureCondition") == "composed_not_raw_vendor"
    )
    if package.get("candidateRole") != "primary" and not composed_package:
        raise ValueError("current mocap lane requires a frozen primary donor package")
    captures = corpus.get("captures")
    if not isinstance(captures, list) or not captures:
        raise ValueError("mocap corpus has no captured clips")
    for row in captures:
        if not isinstance(row, Mapping):
            raise ValueError("mocap corpus capture row is not an object")
        for field in ("key", "capture", "captureSha256", "sourceIndices", "frames"):
            if not row.get(field):
                raise ValueError(f"mocap corpus capture is missing {field}")
    marker = _contains_forbidden(corpus.get("provenance") or {})
    if marker:
        raise ValueError(f"mocap corpus provenance selects forbidden motion lane {marker}")
    return {
        "schema": SCHEMA,
        "lane": LANE,
        "motionAuthority": MOTION_AUTHORITY,
        "motionRepresentation": representation,
        "captureCount": len(captures),
        "primaryDonor": str(package.get("refSeq") or package.get("kind") or ""),
        "singleAssetIdleReference": True,
        "composedFkChecked": representation == "fixed_composed_fk_v1",
        "legacyRepresentationInferred": legacy_representation,
    }


def validate_fit_report_contract(
    report: Mapping[str, Any], *, delivery: bool = False,
    parent_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a fitter report without requiring historical reports to be rewritten."""
    owner = report.get("motionOwner")
    if owner is not None and str(owner) not in ALLOWED_MOTION_OWNERS:
        raise ValueError(f"motion owner {owner!r} is not valid for current mocap delivery")
    reference = report.get("motionReference")
    if reference is not None and not isinstance(reference, Mapping):
        raise ValueError("motionReference must be an object")
    if reference is not None:
        policy = str(reference.get("policy") or "")
        if policy and policy != "single_asset_calibrated_idle_not_per_clip_context":
            raise ValueError("current mocap motion reference is not the shared asset idle reference")
    completion = report.get("motionCompletion")
    if completion is not None and not isinstance(completion, Mapping):
        raise ValueError("motionCompletion must be an object or null")
    marker = _contains_forbidden(
        {
            "motionOwner": owner,
            "motionReference": reference,
            "motionCompletion": completion,
            "motionAuthority": report.get("motionAuthority"),
        }
    )
    if marker:
        raise ValueError(f"fit report selects forbidden motion lane {marker}")
    if delivery and owner is None:
        # Legacy attachment-refit reports do not repeat the owner.  They are
        # accepted only when the caller supplies and validates their parent
        # fit; omission alone must never make an arbitrary report deliverable.
        if parent_report is None:
            raise ValueError("delivery fit report omits motionOwner and has no validated parent fit")
        parent = validate_fit_report_contract(parent_report, delivery=False)
        parent_owner = parent_report.get("motionOwner")
        if parent_owner not in ALLOWED_MOTION_OWNERS:
            raise ValueError("legacy fit report parent has no allowed captured-mocap owner")
        return {
            "ok": True,
            "legacyOwnerOmitted": True,
            "parentMotionOwner": str(parent_owner),
            "deliveryEligible": True,
        }
    return {
        "ok": True,
        "motionOwner": str(owner) if owner is not None else None,
        "deliveryEligible": owner in ALLOWED_MOTION_OWNERS if owner is not None else True,
    }


def contract_metadata(*, geometry_mode: str, bind_mode: str = "prepared") -> dict[str, Any]:
    """Metadata written into new candidate reports for downstream validators."""
    if geometry_mode not in {"weights_only", "weights_mesh"}:
        raise ValueError(f"unknown geometry mode {geometry_mode!r}")
    if bind_mode not in {"prepared", "source_reference"}:
        raise ValueError(f"unknown bind mode {bind_mode!r}")
    return {
        "schema": SCHEMA,
        "lane": LANE,
        "animationAuthority": MOTION_AUTHORITY,
        "motionReconstruction": MOTION_RECONSTRUCTION,
        "motionEditsAllowed": ["none", "explicit_source_orientation_completion_fixed_positions"],
        "skinEditsAllowed": ["weights", "bounded_rest_mesh_only_when_explicit"],
        "geometryMode": geometry_mode,
        "bindMode": bind_mode,
        "deliveryEligible": bind_mode == "prepared",
        "forbiddenMotionInputs": list(FORBIDDEN_MOTION_MARKERS),
    }
