#!/usr/bin/env python3
"""Plan or run the accepted captured-mocap lane for Castle units.

The old Castle batch entry point drove fused-push silhouette fitting.  This
entry point is deliberately explicit: it consumes frozen captured corpora and
the shared skin fitter, starts in weights-only mode, and never treats a
silhouette result as animation authority.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline_contract import (  # noqa: E402
    contract_metadata,
    validate_corpus_contract,
    validate_fit_report_contract,
)


CASTLE_UNITS: dict[str, dict[str, str]] = {
    "h3_archer": {"corpus": "skin_mesh_pilot/archer/captures_v2/corpus.json", "registration": "skin_mesh_pilot/archer/registration_v2"},
    "h3_marksman": {"corpus": "skin_mesh_pilot/marksman/captures_v2/corpus.json", "registration": "skin_mesh_pilot/marksman/registration_v2"},
    "h3_pikeman": {"corpus": "skin_mesh_pilot/pikeman/captures_v2/corpus.json", "registration": "skin_mesh_pilot/pikeman/registration_v2"},
    "h3_crusader": {"corpus": "skin_mesh_pilot/crusader/capture_physical_v2/corpus.json", "registration": "skin_mesh_pilot/crusader/registration_physical_v2"},
    "h3_monk": {"corpus": "skin_mesh_pilot/monk/captures_v1/corpus.json", "registration": "skin_mesh_pilot/monk/registration_v1"},
    "h3_swordsman": {"corpus": "skin_mesh_pilot/swordsman/captures_v1/corpus.json", "registration": "skin_mesh_pilot/swordsman/registration_v1"},
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _unit_plan(unit: str, *, output_root: Path, allow_legacy_corpus: bool) -> dict[str, Any]:
    if unit not in CASTLE_UNITS:
        raise ValueError(f"unknown Castle unit {unit!r}; choose one of {sorted(CASTLE_UNITS)}")
    spec = CASTLE_UNITS[unit]
    corpus = (ROOT / "artifacts/homm3_mocap_v2" / spec["corpus"]).resolve()
    registration = (ROOT / "artifacts/homm3_mocap_v2" / spec["registration"]).resolve()
    if not corpus.is_file():
        raise FileNotFoundError(corpus)
    pilot_path = registration / "pilot_report.json"
    camera_path = registration / "camera.json"
    registration_path = registration / "camera_registration.json"
    if not pilot_path.is_file() or not camera_path.is_file() or not registration_path.is_file():
        raise FileNotFoundError(f"incomplete prepared registration for {unit}: {registration}")
    pilot = _load(pilot_path)
    if pilot.get("asset") != unit:
        raise ValueError(f"prepared registration asset mismatch for {unit}: {pilot.get('asset')!r}")
    validate_fit_report_contract(pilot)
    camera_registration = _load(registration_path)
    if camera_registration.get("status") != "registered":
        raise ValueError(
            f"prepared registration for {unit} is not registered: "
            f"{camera_registration.get('status')!r}"
        )
    corpus_contract = validate_corpus_contract(
        _load(corpus), allow_legacy=allow_legacy_corpus
    )
    output = (output_root / unit / "weights_only_v1").resolve()
    command = [
        sys.executable,
        str(HERE / "run_skin_mesh_pilot.py"),
        "--asset", unit,
        "--baseline-dir", str(registration),
        "--corpus", str(corpus),
        "--output", str(output),
        "--geometry-mode", "weights_only",
    ]
    return {
        "unit": unit,
        "lane": "current_mocap",
        "corpus": str(corpus),
        "corpusSha256": _sha(corpus),
        "registration": str(registration),
        "registrationContract": {
            "pilotReport": str(pilot_path),
            "camera": str(camera_path),
            "cameraRegistration": str(registration_path),
            "status": camera_registration.get("status"),
            "proof": pilot.get("proof"),
        },
        "output": str(output),
        "geometryMode": "weights_only",
        "legacyCorpusMode": allow_legacy_corpus,
        "pipelineContract": {**contract_metadata(geometry_mode="weights_only"), "corpus": corpus_contract},
        "command": command,
        "proof": "planned-inputs-only",
    }


def _sha(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_plan(*, units: list[str], output_root: Path,
               allow_legacy_corpus: bool = True) -> dict[str, Any]:
    rows = [_unit_plan(unit, output_root=output_root,
                       allow_legacy_corpus=allow_legacy_corpus) for unit in units]
    return {
        "schema": "homm3.castle-current-mocap-pipeline-plan.v1",
        "lane": "current_mocap",
        "animationAuthority": "captured_vendor_positions_fixed_before_skin_fit",
        "units": rows,
        "forbiddenInputs": ["fused_push", "silhouette_pose_search", "continuous_tracker"],
        "legacyCorpusMode": allow_legacy_corpus,
        "proof": "source-static plan; no GPU work performed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", choices=sorted(CASTLE_UNITS), action="append")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/castle_mocap_candidates")
    parser.add_argument("--plan-output", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/castle_mocap_pipeline_plan.json")
    parser.add_argument("--run-unit", action="store_true", help="run the explicitly selected unit after writing the plan")
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--iterations", type=int, default=160)
    parser.add_argument("--require-explicit-corpus", action="store_true",
                        help="fail unless every Castle corpus declares motionRepresentation")
    args = parser.parse_args()
    if args.run_unit and not args.unit:
        raise ValueError("--run-unit requires exactly one --unit")
    if args.run_unit and len(args.unit) != 1:
        raise ValueError("--run-unit accepts one --unit at a time")
    if not 120 <= args.seconds <= 600 or args.iterations <= 0:
        raise ValueError("--seconds must be 120..600 and --iterations must be positive")
    units = args.unit or list(CASTLE_UNITS)
    plan = build_plan(units=units, output_root=args.output_root.resolve(),
                      allow_legacy_corpus=not args.require_explicit_corpus)
    args.plan_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.plan_output.resolve().write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(args.plan_output.resolve()), "units": units, "run": bool(args.run_unit)}, indent=2))
    if args.run_unit:
        row = plan["units"][0]
        command = row["command"] + ["--seconds", str(args.seconds), "--iterations", str(args.iterations)]
        subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
