#!/usr/bin/env python3
"""Fail-closed validator for the three DINOv3 autograd example artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from run_dinov3_branch_vector_examples import (
    CLIPS,
    DEFAULT_OUT,
    RIG_AUTHORITY,
    _contract_source_hashes,
    _file_hash,
    _frame_set_hash,
    _json_hash,
    _runtime_contract,
    _validate_payload,
    _verify_gif,
)


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object at {path}")
    return value


def _validate_manifest(
    manifest: Mapping[str, Any], *, plan: Mapping[str, Any], frame_count: int
) -> str:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise RuntimeError("input manifest has no inputs object")
    input_hash = str(manifest.get("inputHash") or "")
    if input_hash != _json_hash(inputs):
        raise RuntimeError("input manifest hash does not match its inputs")
    for name in ("mesh", "cameraFit", "notebook"):
        row = inputs.get(name) or {}
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or str(row.get("sha256")) != _file_hash(path):
            raise RuntimeError(f"{name} input is missing or changed: {path}")
    targets = inputs.get("targetFrames") or {}
    target_dir = Path(str(targets.get("path") or ""))
    if int(targets.get("count") or 0) != int(frame_count):
        raise RuntimeError("target frame count drifted")
    if str(targets.get("sha256")) != _frame_set_hash(target_dir, frame_count):
        raise RuntimeError("target frame set changed")
    model = inputs.get("model") or {}
    snapshot = Path(str(model.get("snapshot") or ""))
    for name, row in (model.get("files") or {}).items():
        path = snapshot / str(name)
        if (
            not path.is_file()
            or int(row.get("size") or -1) != path.stat().st_size
            or str(row.get("sha256")) != _file_hash(path)
        ):
            raise RuntimeError(f"DINOv3 model file is missing or changed: {path}")
    expected_sources = _contract_source_hashes()
    if inputs.get("contractSources") != expected_sources:
        raise RuntimeError("solver or presentation source changed after the fit")
    if inputs.get("fitKwargs") != plan.get("fitKwargs"):
        raise RuntimeError("clip fitKwargs do not match the experiment plan")
    if inputs.get("runtime") != plan.get("runtime"):
        raise RuntimeError("clip runtime contract does not match the experiment plan")
    effective = inputs.get("effectiveGpuCascadeConfig") or {}
    if str(inputs.get("effectiveGpuCascadeConfigHash") or "") != _json_hash(
        effective
    ):
        raise RuntimeError("effective GpuCascadeConfig hash does not match")
    if inputs.get("rigAuthority") != {
        "mode": RIG_AUTHORITY,
        "ownedBindValidated": False,
        "meshyRigidizationReport": None,
    }:
        raise RuntimeError("diagnostic rig authority is missing or changed")
    return input_hash


def validate_output_root(out_root: Path) -> dict[str, Any]:
    out_root = Path(out_root).resolve()
    plan = _read_object(out_root / "experiment_plan.json")
    if plan.get("runtime") != _runtime_contract():
        raise RuntimeError("runtime or CUDA contract changed after the fit")
    summary = _read_object(out_root / "example_summary.json")
    known_by_label = {str(row["label"]): row for row in CLIPS}
    plan_clips = plan.get("clips") or []
    expected_labels = {str(row.get("label") or "") for row in plan_clips}
    if not expected_labels or not expected_labels.issubset(known_by_label):
        raise RuntimeError("experiment plan contains an empty or unknown clip set")
    if len(expected_labels) != len(plan_clips):
        raise RuntimeError("experiment plan contains duplicate clips")
    summary_rows = summary.get("reports") or []
    summary_by_label = {
        str((row.get("clip") or {}).get("label")): row for row in summary_rows
    }
    if set(summary_by_label) != expected_labels:
        raise RuntimeError("summary does not contain exactly the planned clips")

    reports = []
    for label in sorted(expected_labels):
        spec = known_by_label[label]
        frame_count = int(spec["frame_count"])
        clip_root = out_root / label
        manifest = _read_object(clip_root / "input_manifest.json")
        input_hash = _validate_manifest(
            manifest, plan=plan, frame_count=frame_count
        )
        result_path = clip_root / "fit/gpu_clip_result.json"
        payload = _read_object(result_path)
        validated = _validate_payload(
            payload,
            frame_count=frame_count,
            dest=clip_root / "fit",
            input_hash=input_hash,
            effective_config=(manifest.get("inputs") or {}).get(
                "effectiveGpuCascadeConfig"
            )
            or {},
            expected_camera_fit=Path(
                str(((manifest.get("inputs") or {}).get("cameraFit") or {}).get("path"))
            ),
        )
        gif_path = clip_root / f"{label}_dinov3_autograd.gif"
        _verify_gif(gif_path, frame_count=frame_count, duration_ms=180)
        gif_report = _read_object(gif_path.with_suffix(".json"))
        if gif_report.get("panels") != ["HoMM3 target", "DINOv3 autograd"]:
            raise RuntimeError(f"{label} GIF panel contract drifted")
        if int(gif_report.get("sourceFrameDurationMs") or 0) != 180:
            raise RuntimeError(f"{label} GIF report timing drifted")
        report = _read_object(clip_root / "example_report.json")
        if str(report.get("inputHash")) != input_hash:
            raise RuntimeError(f"{label} report input hash drifted")
        output_hashes = {
            "solvedRgbSha256": _frame_set_hash(
                clip_root / "fit/solved_rgb",
                frame_count,
                label="solved RGB",
            ),
            "gifSha256": _file_hash(gif_path),
            "gifMetadataSha256": _file_hash(gif_path.with_suffix(".json")),
            "resultSha256": _file_hash(result_path),
        }
        for name, expected in output_hashes.items():
            if str(report.get(name) or "") != expected:
                raise RuntimeError(f"{label} output hash {name} drifted")
        summary_row = summary_by_label[label]
        for name in (
            "frameCount",
            "score",
            "evaluationCount",
            "branchVisits",
            "acceptedBranches",
            "acceptedGroupCount",
            "branchGroupCount",
            "searchBoneCount",
            "exactlyFrozenBoneCount",
            "meaningfullyMovedBoneCount",
            "meaningfulMotionThresholdDeg",
            "meaningfulBoneCoverage",
            "motionCoverageStatus",
            "inputHash",
            "gif",
            "result",
            "solvedRgbSha256",
            "gifSha256",
            "gifMetadataSha256",
            "resultSha256",
            "proof",
        ):
            if summary_row.get(name) != report.get(name):
                raise RuntimeError(f"{label} summary field {name} drifted")
        reports.append({"clip": label, "inputHash": input_hash, **validated})
    return {
        "ok": True,
        "outputRoot": str(out_root).replace("\\", "/"),
        "clips": reports,
        "proof": "generated artifact validated; not delivery or runtime validated",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(validate_output_root(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
