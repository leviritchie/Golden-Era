#!/usr/bin/env python3
"""Audit gpu_clip_result.json pose magnitudes and stamp the poseUnits marker.

The pose-dict contract is an axis-angle vector in DEGREES per bone
(``RocGpuCascadeExperiment._pose_dicts`` applies ``np.degrees``). Results
persisted before the ``poseUnits`` marker existed carry no explicit units;
the GLB clip exporter refuses unmarked payloads
(``require_pose_units_degrees``).

This script stamps ``"poseUnits": "degrees"`` only when the stored numbers
cannot physically be radians: the largest axis-angle magnitude must exceed
the per-file radians cap ``sqrt(3) * radians(joint_limit_deg) * maxScale``
(the solver bounds each axis by ``tanh(raw) * radians(joint_limit_deg) *
bone_limit_scale``). Files that do not clear the cap are listed and left
untouched — re-fit them or audit by hand. Radians-era results (they exist,
e.g. early ``gpu_cascade_delivery`` runs) must never be stamped.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GLOB = "gpu_clip_result.json"


def _max_pose_magnitude(poses: Mapping[str, Any]) -> float:
    worst = 0.0
    for frame in poses.values():
        if not isinstance(frame, Mapping):
            continue
        for entry in frame.values():
            if not isinstance(entry, Mapping):
                continue
            if not {"x", "y", "z"} <= set(entry):
                continue
            try:
                vector = [float(entry[axis]) for axis in ("x", "y", "z")]
            except (TypeError, ValueError):
                continue
            worst = max(worst, math.sqrt(sum(component * component for component in vector)))
    return worst


def _radians_cap(config: Mapping[str, Any]) -> float:
    joint_limit_deg = float(config.get("joint_limit_deg") or 90.0)
    overrides = config.get("bone_limit_scale_overrides")
    max_scale = 1.0
    if isinstance(overrides, Mapping) and overrides:
        max_scale = max(1.0, max(float(value) for value in overrides.values()))
    return math.sqrt(3.0) * math.radians(joint_limit_deg) * max_scale


def audit_file(path: Path) -> tuple[str, float, float]:
    """Return (verdict, max_magnitude, radians_cap)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    units = payload.get("poseUnits")
    if units is not None:
        if units == "degrees":
            return ("already-stamped", float("nan"), float("nan"))
        raise RuntimeError(f"{path} has unexpected poseUnits={units!r}; refusing to touch it")
    poses = payload.get("poses")
    if not isinstance(poses, Mapping) or not poses:
        raise RuntimeError(f"{path} has no poses mapping; refusing to guess units")
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise RuntimeError(f"{path} has no config block; cannot bound the radians cap")
    magnitude = _max_pose_magnitude(poses)
    cap = _radians_cap(config)
    if magnitude > cap:
        return ("degrees", magnitude, cap)
    return ("unproven", magnitude, cap)


def stamp_degrees(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("poseUnits") == "degrees":
        return
    payload["poseUnits"] = "degrees"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="clip result files to audit (default: every gpu_clip_result.json under artifacts/pose_picker_runs)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="stamp proven-degrees files (default is a dry-run report)",
    )
    args = parser.parse_args(argv)

    if args.paths:
        files = [path.resolve() for path in args.paths]
    else:
        files = sorted((ROOT / "artifacts" / "pose_picker_runs").glob(f"**/{DEFAULT_GLOB}"))
    if not files:
        print("no clip result files found", flush=True)
        return 1

    stamped = 0
    skipped: list[str] = []
    for path in files:
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        try:
            verdict, magnitude, cap = audit_file(path)
        except Exception as exc:
            print(f"ERROR    {rel}: {exc} (left untouched)", flush=True)
            skipped.append(str(rel))
            continue
        if verdict == "already-stamped":
            continue
        if verdict == "degrees":
            print(f"degrees  max={magnitude:9.3f} cap={cap:7.3f}  {rel}", flush=True)
            if args.apply:
                stamp_degrees(path)
                stamped += 1
        else:
            print(f"UNPROVEN max={magnitude:9.3f} cap={cap:7.3f}  {rel} (left untouched)", flush=True)
            skipped.append(str(rel))

    print(
        f"audited={len(files)} stamped={stamped} unproven={len(skipped)} apply={bool(args.apply)}",
        flush=True,
    )
    return 0 if not skipped else 2


if __name__ == "__main__":
    sys.exit(main())
