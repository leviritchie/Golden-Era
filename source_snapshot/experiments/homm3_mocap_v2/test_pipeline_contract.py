from __future__ import annotations

from pipeline_contract import (
    ALLOWED_MOTION_OWNERS,
    contract_metadata,
    validate_corpus_contract,
    validate_fit_report_contract,
)


def _raises(message: str, fn) -> None:
    try:
        fn()
    except ValueError as exc:
        assert message in str(exc)
    else:  # pragma: no cover - this is a tiny standalone test harness
        raise AssertionError(f"expected ValueError containing {message!r}")


def _corpus() -> dict:
    return {
        "schema": "homm3.skin-corpus.v1",
        "package": {"candidateRole": "primary", "refSeq": "donor"},
        "captures": [
            {
                "key": "g00_move",
                "capture": "capture.npz",
                "captureSha256": "a" * 64,
                "sourceIndices": [1],
                "frames": ["000.png"],
            }
        ],
    }


def test_capture_corpus_defaults_to_actual_position_authority():
    result = validate_corpus_contract(_corpus())
    assert result["motionRepresentation"] == "capture_positions_v1"
    assert result["singleAssetIdleReference"] is True
    assert result["legacyRepresentationInferred"] is True


def test_strict_corpus_mode_rejects_implicit_representation():
    _raises("motionRepresentation explicitly", lambda: validate_corpus_contract(
        _corpus(), allow_legacy=False
    ))


def test_explicit_composed_fk_corpus_is_allowed_for_mounted_units():
    corpus = _corpus()
    corpus["motionRepresentation"] = "fixed_composed_fk_v1"
    assert validate_corpus_contract(corpus)["composedFkChecked"] is True


def test_forbidden_silhouette_motion_is_rejected():
    corpus = _corpus()
    corpus["provenance"] = {"motionSource": "fused_push diagnostic"}
    _raises("forbidden", lambda: validate_corpus_contract(corpus))


def test_fit_report_accepts_fixed_capture_owner_only():
    report = {
        "motionOwner": next(iter(ALLOWED_MOTION_OWNERS)),
        "motionReference": {"policy": "single_asset_calibrated_idle_not_per_clip_context"},
    }
    assert validate_fit_report_contract(report)["ok"] is True


def test_fit_report_rejects_silhouette_owner():
    _raises("motion owner", lambda: validate_fit_report_contract({"motionOwner": "fused_push_v24_pipeline"}))


def test_delivery_rejects_legacy_report_without_parent():
    _raises("no validated parent", lambda: validate_fit_report_contract({}, delivery=True))


def test_delivery_accepts_legacy_attachment_with_validated_parent():
    parent = {"motionOwner": next(iter(ALLOWED_MOTION_OWNERS))}
    result = validate_fit_report_contract({}, delivery=True, parent_report=parent)
    assert result["parentMotionOwner"] == parent["motionOwner"]


def test_contract_metadata_marks_source_reference_as_diagnostic():
    metadata = contract_metadata(geometry_mode="weights_only", bind_mode="source_reference")
    assert metadata["animationAuthority"] == "captured_vendor_positions_fixed_before_skin_fit"
    assert metadata["deliveryEligible"] is False
