#!/usr/bin/env python3
"""Inventory and run the current captured-mocap lane for the full HoMM3 set.

This is intentionally separate from the historical silhouette-fit runners.  It
does not infer missing inputs or promote a custom Blender rig: every unit gets
an inventory row, while only rows with a validated captured corpus, prepared
registration, frozen preparation, and a canonical SmartRig emit a runnable
weights-only command.  The inventory is useful even when most of the 275
source slots are still waiting for captures or registrations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARTIFACTS = ROOT / "artifacts/homm3_mocap_v2"
COVERAGE = ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json"
CORPUS_ROOT = ARTIFACTS / "skin_mesh_pilot"
PREP_ROOT = ARTIFACTS / "shape_preserved"
DEFAULT_OUTPUT_ROOT = ARTIFACTS / "all_mocap_candidates"

# These are deliberate source selections for captures that have a v1 and v2
# (or a diagnostic registration) in the worktree.  They keep the batch runner
# deterministic without treating the newest directory name as quality proof.
CORPUS_PREFERENCES = {
    "h3_roc": "captures_v2/corpus.json",
    "h3_archer": "captures_v2/corpus.json",
    "h3_marksman": "captures_v2/corpus.json",
    "h3_pikeman": "captures_v2/corpus.json",
    "h3_crusader": "capture_physical_v2/corpus.json",
    # The semantic Wolf Rider is the corrected mounted branch (its mesh was
    # named wolf_raider until the 2026-09-27 basename swap). Its composed offsets must match the corrected
    # mounted-capsule preparation; the legacy branch is a different mesh.
    "h3_wolf_rider": "wolf_rider_corrected/composed_v2/corpus.json",
}
REGISTRATION_PREFERENCES = {
    "h3_behemoth": "registration_v2_auto",
    "h3_hobgoblin": "registration_v2_auto",
    "h3_archer": "registration_v2",
    "h3_marksman": "registration_v2",
    # Full-azimuth registration correctly found the silhouette envelope but
    # selected the rear of this asymmetric SmartRig.  Keep the generated
    # front-correction wrapper explicit rather than mirroring the mesh or
    # changing captured joints.  The wrapper is a presentation-only +180 deg
    # vertical yaw and carries its own provenance in camera_registration.json.
    "h3_pikeman": "registration_v3_flip180",
    "h3_crusader": "registration_physical_v2",
    "h3_thunderbird": "registration_v2",
    "h3_wolf_rider": "registration_v2",
}

# Explicit fit-output selections keep corrected reruns visible to every
# downstream stage.  Do not infer from directory mtime or silently fall back
# when a preferred output is absent: a named output is part of provenance.
FIT_OUTPUT_PREFERENCES = {
    "h3_pikeman": "weights_only_flip180",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _corpus_candidates() -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for path in CORPUS_ROOT.glob("**/corpus.json"):
        try:
            unit = str(_load(path).get("unit") or "")
        except (OSError, ValueError, TypeError):
            continue
        if unit:
            result.setdefault(unit, []).append(path.resolve())
    return result


def _preference_path(sid: str, candidates: list[Path], preference: dict[str, str]) -> Path | None:
    wanted = preference.get(sid)
    if not wanted:
        return None
    matches = [p for p in candidates if p.as_posix().endswith("/" + wanted)]
    return matches[0] if len(matches) == 1 else None


def _select_corpus(sid: str, candidates: list[Path]) -> tuple[Path | None, str | None]:
    if not candidates:
        return None, "missing"
    preferred = _preference_path(sid, candidates, CORPUS_PREFERENCES)
    if preferred is not None:
        return preferred, "preferred"
    if len(candidates) == 1:
        return candidates[0], "single"
    # A corpus with an explicit primary package is still not enough to break a
    # tie: different captures can share that label.  Keep the row pending.
    return None, "ambiguous"


def _registration_candidates(sid: str, corpus_sha: str) -> list[Path]:
    result = []
    for report_path in CORPUS_ROOT.glob("**/pilot_report.json"):
        try:
            report = _load(report_path)
        except (OSError, ValueError, TypeError):
            continue
        if report.get("asset") != sid:
            continue
        if report.get("inputs", {}).get("corpusSha256") != corpus_sha:
            continue
        root = report_path.parent
        required = (root / "camera.json", root / "camera_registration.json")
        if all(path.is_file() for path in required):
            try:
                if _load(required[1]).get("status") != "registered":
                    continue
                # The fitter consumes the same asset-wide idle calibration
                # that camera registration recorded.  Historical reports that
                # omit this ownership are evidence, not runnable baselines.
                inputs = _load(report_path).get("inputs", {})
                calibration_path = Path(str(inputs.get("calibrationPath") or ""))
                if not calibration_path.is_file():
                    continue
                if inputs.get("calibration") and _sha(calibration_path) != inputs["calibration"]:
                    continue
            except (OSError, ValueError, TypeError):
                continue
            result.append(root.resolve())
    return sorted(set(result))


def _select_registration(sid: str, candidates: list[Path]) -> tuple[Path | None, str | None]:
    if not candidates:
        return None, "missing"
    wanted = REGISTRATION_PREFERENCES.get(sid)
    if wanted:
        matches = [p for p in candidates if p.name == wanted]
        if len(matches) == 1:
            return matches[0], "preferred"
    if len(candidates) == 1:
        return candidates[0], "single"
    return None, "ambiguous"


def _fit_output_name(sid: str) -> tuple[str, str]:
    """Return the deterministic fit-output directory for a unit."""
    name = FIT_OUTPUT_PREFERENCES.get(sid, "weights_only_v1")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", name):
        raise ValueError(f"{sid}: invalid fit-output name {name!r}")
    return name, "preferred" if sid in FIT_OUTPUT_PREFERENCES else "default"


def _rig_row(record: dict[str, Any]) -> dict[str, Any]:
    sid = str(record["unitSid"])
    smartrig = Path(record["smartrig"]) if record.get("smartrig") else None
    custom = Path(record["customRig"]) if record.get("customRig") else None
    report = None
    accepted = False
    if smartrig and smartrig.is_file():
        kind = "canonical_smartrig"
        path = smartrig
    elif custom and custom.is_file():
        kind = "custom_rig"
        path = custom
        candidate_report = custom.parent / "rig_report.json"
        if candidate_report.is_file():
            report = candidate_report
            try:
                accepted = _load(candidate_report).get("accepted") is True
            except (OSError, ValueError, TypeError):
                accepted = False
    else:
        kind = "none"
        path = None
    return {
        "kind": kind,
        "path": _rel(path) if path else None,
        "report": _rel(report) if report else None,
        "accepted": accepted,
        "meshKind": record.get("meshKind"),
        "mesh": record.get("mesh"),
    }


def _build_row(record: dict[str, Any], corpora: dict[str, list[Path]]) -> dict[str, Any]:
    sid = str(record["unitSid"])
    candidates = corpora.get(sid, [])
    corpus_path, corpus_selection = _select_corpus(sid, candidates)
    corpus_sha = _sha(corpus_path) if corpus_path else None
    corpus_status = "missing"
    corpus_contract: dict[str, Any] | None = None
    corpus_data: dict[str, Any] | None = None
    blockers: list[str] = []
    if corpus_path:
        try:
            corpus_data = _load(corpus_path)
            if corpus_data.get("schema") != "homm3.skin-corpus.v1":
                corpus_status = "invalid"
                blockers.append("corpus_schema")
            else:
                representation = corpus_data.get("motionRepresentation")
                corpus_status = "legacy" if not representation else "present"
                corpus_contract = {
                    "schema": corpus_data.get("schema"),
                    "motionRepresentation": representation or "capture_positions_v1",
                    "legacyRepresentationInferred": not bool(representation),
                    "captureCount": len(corpus_data.get("captures") or []),
                }
        except (OSError, ValueError, TypeError):
            corpus_status = "invalid"
            blockers.append("corpus_json")
    elif corpus_selection == "ambiguous":
        corpus_status = "ambiguous"
        blockers.append("multiple_corpora_without_explicit_selection")
    else:
        blockers.append("missing_corpus")

    registrations = _registration_candidates(sid, corpus_sha) if corpus_sha else []
    registration_path, registration_selection = _select_registration(sid, registrations)
    registration_status = "missing"
    registration_row: dict[str, Any] = {
        "root": _rel(registration_path) if registration_path else None,
        "pilotReport": _rel(registration_path / "pilot_report.json") if registration_path else None,
        "camera": _rel(registration_path / "camera.json") if registration_path else None,
        "cameraRegistration": _rel(registration_path / "camera_registration.json") if registration_path else None,
        "status": registration_status,
        "selection": registration_selection,
        "sha256": _sha(registration_path / "camera_registration.json") if registration_path else None,
    }
    if registration_path:
        try:
            pilot = _load(registration_path / "pilot_report.json")
            registration_status = "registered_unaccepted"
            registration_row["status"] = registration_status
            registration_row["proof"] = pilot.get("proof")
            registration_row["motionOwner"] = pilot.get("motionOwner")
        except (OSError, ValueError, TypeError):
            registration_status = "invalid"
            registration_row["status"] = registration_status
            blockers.append("registration_json")
    elif registration_selection == "ambiguous":
        registration_status = "ambiguous"
        registration_row["status"] = registration_status
        blockers.append("multiple_registrations_without_explicit_selection")
    else:
        blockers.append("missing_registration")

    rig = _rig_row(record)
    fit_output_name, fit_output_selection = _fit_output_name(sid)
    fit_output_root = DEFAULT_OUTPUT_ROOT / sid / fit_output_name
    prep_path = PREP_ROOT / sid / "preparation_frozen.json"
    prep_status = "present" if prep_path.is_file() else "missing"
    if prep_status != "present":
        blockers.append("missing_frozen_preparation")
    elif rig["kind"] == "canonical_smartrig":
        # A canonical filename is not enough: the frozen skin owns the mesh
        # bytes used by the fit.  Refuse a mixed legacy/corrected branch before
        # any GPU work or lighting selection can consume it.
        try:
            frozen = _load(prep_path)
            expected_mesh_sha = str((frozen.get("inputHashes") or {}).get("originalMesh") or "")
            rig_path = (ROOT / str(rig["path"])).resolve() if rig.get("path") else None
            if not expected_mesh_sha:
                blockers.append("preparation_mesh_identity_missing")
            elif rig_path is None or not rig_path.is_file() or _sha(rig_path) != expected_mesh_sha:
                blockers.append("rig_preparation_mesh_mismatch")
        except (OSError, ValueError, TypeError):
            blockers.append("preparation_json")

    if rig["kind"] == "none":
        blockers.append("missing_rig")
    elif rig["kind"] == "custom_rig" and not rig["accepted"]:
        blockers.append("custom_rig_not_accepted")

    ready = (
        corpus_status in {"present", "legacy"}
        and registration_status == "registered_unaccepted"
        and prep_status == "present"
        and rig["kind"] == "canonical_smartrig"
    )
    if ready:
        readiness = "ready_for_weights_only"
    elif rig["kind"] == "custom_rig":
        readiness = "custom_rig_pending"
    elif corpus_status in {"present", "legacy"} and registration_status == "missing":
        readiness = "corpus_only"
    elif corpus_status == "missing" and registration_status == "registered_unaccepted":
        readiness = "registration_only"
    elif any("multiple_" in blocker for blocker in blockers):
        readiness = "pending"
    elif any(blocker in blockers for blocker in ("rig_preparation_mesh_mismatch", "preparation_mesh_identity_missing", "preparation_json")):
        readiness = "blocked"
    elif any(blocker in blockers for blocker in ("missing_mesh", "missing_rig")):
        readiness = "pending"
    else:
        readiness = "blocked" if "corpus_schema" in blockers or "corpus_json" in blockers else "pending"

    command: list[str] = []
    if ready:
        command = [
            sys.executable,
            str(HERE / "run_skin_mesh_pilot.py"),
            "--asset", sid,
            "--baseline-dir", str((ROOT / registration_row["root"]).resolve()),
            "--corpus", str((ROOT / _rel(corpus_path)).resolve()),
            "--output", str(fit_output_root.resolve()),
            "--geometry-mode", "weights_only",
        ]

    return {
        "unit": sid,
        "gameSid": sid,
        "lane": "current_mocap",
        "source": {
            "corpus": _rel(corpus_path) if corpus_path else None,
            "corpusSha256": corpus_sha,
            "corpusCandidates": [_rel(p) for p in candidates],
            "corpusStatus": corpus_status,
            "corpusContract": corpus_contract,
        },
        "registration": registration_row,
        "rig": rig,
        "preparation": {"path": _rel(prep_path), "status": prep_status},
        "fitOutput": {
            "name": fit_output_name,
            "selection": fit_output_selection,
            "root": _rel(fit_output_root),
        },
        "readiness": readiness,
        "blockers": sorted(set(blockers)),
        "plannedCommand": command,
    }


def build_inventory() -> dict[str, Any]:
    coverage = _load(COVERAGE)
    corpora = _corpus_candidates()
    rows = [_build_row(record, corpora) for record in coverage.get("records", [])]
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["readiness"]] = summary.get(row["readiness"], 0) + 1
    return {
        "schema": "homm3.mocap-unit-inventory.v1",
        "lane": "current_mocap",
        "animationAuthority": "captured_vendor_positions_fixed_before_skin_fit",
        "unitCount": len(rows),
        "summary": dict(sorted(summary.items())),
        "units": rows,
        "selectionPolicy": {
            "corpus": "explicit known duplicate preference, otherwise exactly one candidate",
            "registration": "corpus hash match plus explicit known preference, otherwise exactly one candidate",
            "rig": "canonical SmartRig only for automatic fitter; custom Blender rigs remain candidates",
            "fitOutput": "explicit per-unit preference, otherwise deterministic weights_only_v1; no newest/implicit fallback",
        },
        "forbiddenInputs": ["fused_push", "silhouette_pose_search", "continuous_tracker", "gpu_cascade_animation"],
        "proof": "source/static inventory; no GPU work performed",
    }


def _find_row(inventory: dict[str, Any], sid: str) -> dict[str, Any]:
    for row in inventory["units"]:
        if row["unit"] == sid:
            return row
    raise ValueError(f"unknown unit {sid!r}")


def build_lighting_selection(inventory: dict[str, Any]) -> dict[str, Any]:
    """Derive a downstream lighting selection from generated mocap fits."""
    rows: list[dict[str, Any]] = []
    for row in inventory["units"]:
        if row["readiness"] != "ready_for_weights_only":
            continue
        sid = row["unit"]
        fit_output = row.get("fitOutput") or {}
        fit_output_root = ROOT / str(fit_output.get("root") or "")
        report = fit_output_root / "report.json"
        if not report.is_file():
            raise ValueError(f"{sid}: lighting selection requires generated fit report {report}")
        if report.parent.resolve() != fit_output_root.resolve():
            raise ValueError(f"{sid}: fit report escaped selected fit-output root")
        corpus = row["source"].get("corpus")
        corpus_sha = row["source"].get("corpusSha256")
        if not corpus or not corpus_sha:
            raise ValueError(f"{sid}: lighting selection requires a selected corpus")
        rows.append({
            "gameSid": sid,
            "labSid": sid,
            "bundleName": f"custom_units_{sid}",
            "assetId": sid,
            "fitReport": _rel(report),
            "sourceReport": _rel(report),
            "sourceReportSha256": _sha(report),
            "fitOutputName": fit_output.get("name"),
            "fitOutputSelection": fit_output.get("selection"),
            "corpus": corpus,
            "corpusSha256": corpus_sha,
            "kind": "current_mocap_candidate",
            "qualityWarnings": ["candidate quality gates remain authoritative; lighting does not promote a fit"],
            "disposition": "lighting_stage_only",
        })
    return {
        "schema": "homm3.mocap-lighting-selection.v1",
        "lane": "current_mocap_lighting",
        "animationAuthority": "captured_vendor_positions_fixed_before_skin_fit",
        "units": rows,
        "selectionPolicy": "all ready mocap candidates with pinned report and corpus hashes",
        "proof": "generated-candidate selection; lighting and runtime acceptance are separate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ARTIFACTS / "homm3_mocap_unit_inventory.json")
    parser.add_argument("--unit", action="append", help="one explicit unit to run; repeat only for planning")
    parser.add_argument("--run-unit", action="store_true", help="run one explicitly selected ready unit")
    parser.add_argument("--run-ready", action="store_true", help="run every ready unit sequentially")
    parser.add_argument("--max-units", type=int, help="bound --run-ready to the first N units")
    parser.add_argument("--run-report", type=Path, default=ARTIFACTS / "homm3_mocap_batch_run.json")
    parser.add_argument("--lighting-selection", type=Path,
                        help="also write a lighting-stage selection derived from the inventory")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--iterations", type=int, default=120)
    args = parser.parse_args()
    if args.run_unit and args.run_ready:
        raise ValueError("--run-unit and --run-ready are mutually exclusive")
    if (args.run_unit or args.run_ready) and args.unit and args.run_ready:
        raise ValueError("--run-ready does not accept --unit")
    if args.run_unit and len(args.unit or []) != 1:
        raise ValueError("--run-unit requires exactly one --unit")
    if args.max_units is not None and args.max_units <= 0:
        raise ValueError("--max-units must be positive")
    if not 120 <= args.seconds <= 600 or args.iterations <= 0:
        raise ValueError("--seconds must be 120..600 and --iterations must be positive")
    inventory = build_inventory()
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    if args.lighting_selection:
        lighting = build_lighting_selection(inventory)
        lighting_path = args.lighting_selection.resolve()
        lighting_path.parent.mkdir(parents=True, exist_ok=True)
        lighting_path.write_text(json.dumps(lighting, indent=2) + "\n", encoding="utf-8")
    if args.run_unit:
        row = _find_row(inventory, args.unit[0])
        if row["readiness"] != "ready_for_weights_only":
            raise ValueError(f"{args.unit[0]} is not runnable: {row['readiness']} ({row['blockers']})")
        command = row["plannedCommand"] + ["--seconds", str(args.seconds), "--iterations", str(args.iterations)]
        subprocess.run(command, cwd=ROOT, check=True)
    if args.run_ready:
        ready = [row for row in inventory["units"] if row["readiness"] == "ready_for_weights_only"]
        if args.max_units is not None:
            ready = ready[:args.max_units]
        results = []
        for row in ready:
            command = row["plannedCommand"] + ["--seconds", str(args.seconds), "--iterations", str(args.iterations)]
            output_arg = command[command.index("--output") + 1]
            output_path = Path(output_arg)
            if output_path.exists():
                results.append({"unit": row["unit"], "status": "skipped_existing", "output": str(output_path)})
                continue
            try:
                subprocess.run(command, cwd=ROOT, check=True)
            except subprocess.CalledProcessError as exc:
                results.append({"unit": row["unit"], "status": "failed", "returnCode": exc.returncode, "output": str(output_path)})
            else:
                results.append({"unit": row["unit"], "status": "completed", "output": str(output_path)})
        run_report = {
            "schema": "homm3.mocap-batch-run.v1",
            "lane": "current_mocap",
            "proof": "generated-candidate batch execution",
            "seconds": args.seconds,
            "iterations": args.iterations,
            "results": results,
        }
        run_path = args.run_report.resolve()
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(json.dumps(run_report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(output), "unitCount": inventory["unitCount"], "summary": inventory["summary"], "run": bool(args.run_unit or args.run_ready)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
