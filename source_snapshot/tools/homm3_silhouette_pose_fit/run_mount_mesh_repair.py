#!/usr/bin/env python3
"""Mount-specific Meshy bridge repair (horse / rider / prop partition).

Uses --species mount in repair_meshy_prop_bridges.py, then optional rigidization.

Example:
  python tools/homm3_silhouette_pose_fit/run_mount_mesh_repair.py \\
    --lab-sid h3_cavalier --mount-profile cavalier --rigidize

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
MESHY = ROOT / "artifacts/meshy_downloads"
BRIDGEFIX_SCRIPT = TOOL / "repair_meshy_prop_bridges.py"
RIGIDIZE_WRAPPER = TOOL / "run_meshy_rigidization.py"
RIGIDIZE_CONFIG = TOOL / "configs/meshy_rigidization_default.json"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from pose_fit_blender import resolve_pose_fit_blender  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lab-sid", required=True, help="Unit lab SID, e.g. h3_cavalier")
    ap.add_argument("--mount-profile", default="cavalier")
    ap.add_argument("--max-delete-face-frac", type=float, default=0.12)
    ap.add_argument("--max-remaining-mixed-faces", type=int, default=0)
    ap.add_argument("--rigidize", action="store_true", help="Run meshy rigidization after bridgefix")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--blender", type=Path, default=None)
    ap.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="JSON summary (default artifacts/meshy_downloads/<sid>_mount_mesh_repair_summary.json)",
    )
    return ap.parse_args()


def _paths(sid: str) -> dict[str, Path]:
    return {
        "raw": MESHY / f"{sid}_smartrigged.glb",
        "bridge": MESHY / f"{sid}_smartrigged_mount_bridgefix.glb",
        "bridge_report": MESHY / f"{sid}_mount_bridgefix_report.json",
        "rigid": MESHY / f"{sid}_smartrigged_mount_rigidized.glb",
        "rigid_report": MESHY / f"{sid}_mount_rigidization_report.json",
        "legacy_rigid": MESHY / f"{sid}_smartrigged_rigidized.glb",
    }


def _run_bridgefix(
    *,
    blender: Path,
    paths: dict[str, Path],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if paths["bridge"].is_file() and paths["bridge_report"].is_file() and not args.overwrite:
        payload = json.loads(paths["bridge_report"].read_text(encoding="utf-8"))
        return {"status": "reused", "report": payload}
    if not paths["raw"].is_file():
        raise FileNotFoundError(f"raw mesh missing: {paths['raw']}")
    command = [
        str(blender),
        "-b",
        "--python",
        str(BRIDGEFIX_SCRIPT),
        "--",
        "--species",
        "mount",
        "--mount-profile",
        str(args.mount_profile),
        "--src",
        str(paths["raw"]),
        "--out",
        str(paths["bridge"]),
        "--report",
        str(paths["bridge_report"]),
        "--no-chroma",
        "--min-bridge-faces",
        "0",
        "--max-delete-face-frac",
        str(args.max_delete_face_frac),
        "--max-remaining-mixed-faces",
        str(args.max_remaining_mixed_faces),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"mount bridgefix failed (exit {completed.returncode})")
    payload = json.loads(paths["bridge_report"].read_text(encoding="utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"mount bridgefix report not ok: {paths['bridge_report']}")
    return {"status": "ran", "report": payload}


def _run_rigidize(*, blender: Path, paths: dict[str, Path], overwrite: bool) -> dict[str, Any]:
    if paths["rigid"].is_file() and paths["rigid_report"].is_file() and not overwrite:
        return {"status": "reused", "report": json.loads(paths["rigid_report"].read_text(encoding="utf-8"))}
    command = [
        sys.executable,
        str(RIGIDIZE_WRAPPER),
        "--src",
        str(paths["bridge"]),
        "--out",
        str(paths["rigid"]),
        "--report",
        str(paths["rigid_report"]),
        "--config",
        str(RIGIDIZE_CONFIG),
        "--blender",
        str(blender),
    ]
    if overwrite:
        command.append("--overwrite")
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"rigidization failed (exit {completed.returncode})")
    payload = json.loads(paths["rigid_report"].read_text(encoding="utf-8"))
    return {"status": "ran", "report": payload}


def main() -> int:
    args = _parse()
    sid = str(args.lab_sid).strip()
    paths = _paths(sid)
    blender = resolve_pose_fit_blender(args.blender)

    print(
        f"[mount-mesh-repair] {sid} profile={args.mount_profile} bridgefix...",
        flush=True,
    )
    bridge = _run_bridgefix(blender=blender, paths=paths, args=args)
    rigid = None
    if args.rigidize:
        print(f"[mount-mesh-repair] {sid} rigidize...", flush=True)
        rigid = _run_rigidize(blender=blender, paths=paths, overwrite=args.overwrite)

    bridge_report = bridge["report"]
    summary = {
        "ok": True,
        "updatedAt": _utc_now(),
        "labSid": sid,
        "mountProfile": str(args.mount_profile),
        "bridgefix": {
            "status": bridge["status"],
            "output": bridge_report.get("output"),
            "facesDeleted": bridge_report.get("facesDeleted"),
            "bridgeFacesMixedLabel": bridge_report.get("bridgeFacesMixedLabel"),
            "bridgeFacesStretchDiag": bridge_report.get("bridgeFacesStretchDiag"),
            "bridgeFacesUnion": bridge_report.get("bridgeFacesUnion"),
            "horseVertsLabeled": bridge_report.get("horseVertsLabeled"),
            "riderVertsLabeled": bridge_report.get("riderVertsLabeled"),
            "propVertsLabeled": bridge_report.get("propVertsLabeled"),
            "report": str(paths["bridge_report"]).replace("\\", "/"),
        },
        "legacyRigidized": str(paths["legacy_rigid"]).replace("\\", "/"),
        "rigidize": rigid,
        "proof": "generated artifact validated — mount horse/rider/prop bridgefix; not OE runtime proven",
    }
    summary_path = args.summary_out or (MESHY / f"{sid}_mount_mesh_repair_summary.json")
    summary_path = summary_path if summary_path.is_absolute() else (ROOT / summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
