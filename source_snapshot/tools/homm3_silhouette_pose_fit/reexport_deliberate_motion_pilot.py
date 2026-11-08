#!/usr/bin/env python3
"""Re-export Stronghold pilot clips with lifecycle cycle-close keys.

Writes a parallel tree; does not mutate ``artifacts/fused_push_skinned_rollout``.
Proof: generated-artifact only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))

from deliberate_motion_contract import clip_lifecycle_row, default_edges_for_suffix  # noqa: E402
from gpu_cascade_delivery import require_pose_units_degrees, write_oriented_clip_glb  # noqa: E402
from audit_deliberate_motion_baseline import _sliced_delivery_poses  # noqa: E402

DEFAULT_ROLLOUT = ROOT / "artifacts" / "fused_push_skinned_rollout"
DEFAULT_OUT = ROOT / "artifacts" / "deliberate_motion_stronghold_pilot"
PILOTS = ("h3_goblin", "h3_roc", "h3_wolf_rider")


def reexport_unit(unit_sid: str, *, rollout: Path, dest_root: Path) -> list[dict]:
    unit_dir = rollout / "units" / unit_sid
    manifest = json.loads((unit_dir / "delivery_manifest.json").read_text(encoding="utf-8"))
    mesh = Path(str(manifest.get("mesh") or ""))
    if not mesh.is_file():
        raise FileNotFoundError(f"{unit_sid}: mesh missing {mesh}")
    clip_dir = dest_root / unit_sid / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for sidecar_path in sorted((unit_dir / "clips").glob("*.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        result_path = Path(str(sidecar.get("clipResultPath") or ""))
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(payload, source=str(result_path))
        poses = _sliced_delivery_poses(payload, sidecar)
        name = str(sidecar["contractName"])
        predecessor, successor = default_edges_for_suffix(name.split("_", 1)[-1])
        lifecycle = clip_lifecycle_row(
            clip_name=name,
            def_group=int(sidecar["defGroup"]),
            source_frame_count=len(poses),
            predecessor=predecessor,
            successor=successor,
        )
        dest = clip_dir / f"{name}.glb"
        report = write_oriented_clip_glb(
            mesh, dest, poses, clip_name=name, lifecycle=lifecycle
        )
        report.update(
            {
                "contractName": name,
                "defGroup": int(sidecar["defGroup"]),
                "fitAnimation": sidecar.get("fitAnimation"),
                "clipResultPath": str(result_path),
            }
        )
        dest.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        reports.append(report)
    (dest_root / unit_sid / "delivery_manifest.json").write_text(
        json.dumps({"labSid": unit_sid, "mesh": str(mesh), "clips": reports}, indent=2) + "\n",
        encoding="utf-8",
    )
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--units", default=",".join(PILOTS))
    args = parser.parse_args(argv)
    all_reports = {}
    for sid in [item.strip() for item in str(args.units).split(",") if item.strip()]:
        all_reports[sid] = reexport_unit(sid, rollout=args.rollout_dir, dest_root=args.out)
        print(f"reexported {sid}: {len(all_reports[sid])} clips", flush=True)
    (args.out / "pilot_index.json").write_text(
        json.dumps({"proofTier": "generated-artifact", "units": list(all_reports)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
