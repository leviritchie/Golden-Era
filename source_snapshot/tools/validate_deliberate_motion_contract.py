#!/usr/bin/env python3
"""Fail-closed deliberate-motion / lifecycle gate for skinned delivery.

Wired into ``deploy_faction_fused_push.py``. Lists worst bones, frames, and
edges rather than only a boolean. Full-animation readiness stays blocked when
MoveStart/MoveEnd are one pose, landmarks are missing, Idle/Move seams are
uncalibrated, or the stock Idle<->Move bypass remains the live controller.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))

from deliberate_motion_animator_contract import (  # noqa: E402
    owned_ground_controller_contract,
    validate_controller_graph,
)
from deliberate_motion_contract import unit_contract_from_clip_sidecars  # noqa: E402

DEFAULT_ROLLOUT = ROOT / "artifacts" / "fused_push_skinned_rollout"
DEFAULT_UNITS = DEFAULT_ROLLOUT / "stronghold_skinned_units.txt"
REPORT_DIR = ROOT / "artifacts" / "deliberate_motion_reports"


def _sidecar_rows(unit_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted((unit_dir / "clips").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["clipPath"] = str(path.with_suffix(".glb"))
        rows.append(payload)
    return rows


def validate_unit(unit_dir: Path) -> dict[str, Any]:
    sid = unit_dir.name
    errors: list[str] = []
    worst: list[str] = []
    sidecars = _sidecar_rows(unit_dir)
    if not sidecars:
        return {"labSid": sid, "ok": False, "errors": [f"{sid}: no clip sidecars"], "worst": []}
    mobile = any(str(item.get("contractName") or "").endswith("_Move") for item in sidecars)
    contract = unit_contract_from_clip_sidecars(sid, sidecars, mobile=mobile)
    errors.extend(str(item) for item in contract.get("errors") or [])
    assets_by_role: dict[str, list[str]] = {}
    for row in contract["clips"]:
        name = str(row["contractName"])
        role = str(row["lifecycleRole"])
        assets_by_role.setdefault(role, []).append(name)
        if bool(row.get("loopBlend")):
            errors.append(f"{sid} {name}: loopBlend is forbidden")
        if int(row["sourceFrameCount"]) < 2 and role in {"entry", "exit"}:
            errors.append(f"{sid} {name}: one-pose {role} clip cannot pass full-animation readiness")
            worst.append(f"{name} one-pose {role}")
        if int(row["sourceFrameCount"]) < 2 and role == "cycle":
            errors.append(f"{sid} {name}: cycle needs at least two source poses")
            worst.append(f"{name} one-pose cycle")
        if row.get("fullAnimationReadiness") != "classified":
            worst.append(f"{name} {row.get('fullAnimationReadiness')}")
        expected_keys = int(row["keyCount"])
        sidecar = next(item for item in sidecars if item.get("contractName") == name)
        exported_keys = sidecar.get("keyCount")
        if exported_keys is not None and int(exported_keys) != expected_keys:
            errors.append(
                f"{sid} {name}: exported keyCount {exported_keys} != lifecycle keyCount {expected_keys}"
            )
        if sidecar.get("lifecycleRole") and sidecar.get("lifecycleRole") != role:
            errors.append(f"{sid} {name}: sidecar role {sidecar.get('lifecycleRole')!r} != {role}")
    if "Victory" in {row.get("suffix") for row in contract["clips"]} and "Defence" in {
        row.get("suffix") for row in contract["clips"]
    }:
        victory = [row["contractName"] for row in contract["clips"] if row.get("suffix") == "Victory"]
        defence = [row["contractName"] for row in contract["clips"] if row.get("suffix") == "Defence"]
        if set(victory) & set(defence):
            errors.append(f"{sid}: Victory and StanceLoop share a Unity clip")
    graph_errors = validate_controller_graph(owned_ground_controller_contract())
    if graph_errors:
        errors.extend(graph_errors)
    # Live lab still uses the stock donor + override table, which bypasses
    # ground MoveStart/MoveEnd. That is a contract miss, not a silent pass.
    errors.append(
        f"{sid}: live lab still uses StockEsquireBattle Idle<->Move bypass; "
        "owned ground.MoveStart/ground.MoveEnd controller is not installed"
    )
    errors.append(f"{sid}: authored landmark / motion-island contract is missing")
    report = {
        "labSid": sid,
        "ok": not errors,
        "canonicalIdle": contract.get("canonicalIdle"),
        "canonicalMove": contract.get("canonicalMove"),
        "errors": errors,
        "worst": worst,
        "proofTier": "source/static + generated-artifact",
        "fullAnimationReady": False,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--units-file", type=Path, default=None)
    parser.add_argument("--unit", default="", help="optional single lab SID")
    parser.add_argument("--write-reports", action="store_true")
    args = parser.parse_args(argv)

    units_dir = args.rollout_dir / "units"
    if args.unit:
        names = [args.unit]
    elif args.units_file is not None:
        names = [
            line.strip()
            for line in args.units_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        names = sorted(
            path.name for path in units_dir.iterdir() if (path / "clips").is_dir()
        )
    reports = []
    errors: list[str] = []
    for name in names:
        unit_dir = args.rollout_dir / "units" / name
        if not (unit_dir / "clips").is_dir():
            errors.append(f"missing unit clips: {unit_dir}")
            continue
        report = validate_unit(unit_dir)
        reports.append(report)
        errors.extend(report["errors"])
        if args.write_reports:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            (REPORT_DIR / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    aggregate = {
        "schema": "deliberate_motion_aggregate.v1",
        "unitCount": len(reports),
        "ok": not errors,
        "errors": errors,
        "units": reports,
        "proofTier": "source/static + generated-artifact",
        "fullAnimationReady": False,
    }
    if args.write_reports:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"deliberate-motion contract failed: {len(errors)} errors across {len(reports)} units",
            file=sys.stderr,
        )
        return 1
    print(f"deliberate-motion contract passed: {len(reports)} units", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
