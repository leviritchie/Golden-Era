#!/usr/bin/env python3
"""Batch bridgefix + rigidize for Castle Meshy SmartRig GLBs still on raw mesh.

Proven archer/halberdier invocation:
  repair_meshy_prop_bridges.py --max-tip-contam 200 --min-bridge-faces 0
  run_meshy_rigidization.py --src *_bridgefix.glb --out *_rigidized.glb

After a successful batch, rerun inventory_smartrig_skinned_rollout.py so status.json
prefers the new *_smartrigged_rigidized.glb paths.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import struct
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
RIGIDIZE_CONFIG = TOOL / "configs" / "meshy_rigidization_default.json"
DEFAULT_SUMMARY = MESHY / "castle_mesh_repair_batch_summary.json"
UNIRIG_WEAPON_BONES = {
    "Bone_033",
    "Bone_034",
    "Bone_035",
    "Bone_036",
    "Bone_037",
}
MIXAMO_WEAPON_BONES = {"RightShoulder", "RightArm", "RightForeArm", "RightHand"}

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from inventory_smartrig_skinned_rollout import STATUS_PATH, _load_json  # noqa: E402
from pose_fit_blender import resolve_pose_fit_blender  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _castle_lab_sids() -> list[str]:
    status = _load_json(STATUS_PATH)
    units = status.get("units")
    if not isinstance(units, list):
        raise RuntimeError(f"{STATUS_PATH} has no units")
    sids: list[str] = []
    for row in units:
        if not isinstance(row, dict):
            continue
        bundle = str(row.get("bundleName") or "")
        if "custom_units_castle_" not in bundle:
            continue
        sid = str(row.get("labSid") or "").strip()
        if sid:
            sids.append(sid)
    if not sids:
        raise RuntimeError("no Castle lab SIDs found in status.json")
    return sorted(set(sids))


def _paths_for(sid: str) -> dict[str, Path]:
    raw = MESHY / f"{sid}_smartrigged.glb"
    bridge = MESHY / f"{sid}_smartrigged_bridgefix.glb"
    rigid = MESHY / f"{sid}_smartrigged_rigidized.glb"
    bridge_report = MESHY / f"{sid}_bridgefix_report.json"
    rigid_report = MESHY / f"{sid}_rigidization_report.json"
    return {
        "raw": raw,
        "bridge": bridge,
        "rigid": rigid,
        "bridge_report": bridge_report,
        "rigid_report": rigid_report,
    }


def _bridgefix_ok(report_path: Path, *, expected_out: Path) -> bool:
    if not report_path.is_file() or not expected_out.is_file():
        return False
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not payload.get("ok"):
        return False
    out = Path(str(payload.get("output") or ""))
    if not out.is_absolute():
        out = report_path.parent / out
    return out.resolve() == expected_out.resolve()


def _rigid_ok(report_path: Path, *, expected_out: Path) -> bool:
    if not report_path.is_file() or not expected_out.is_file():
        return False
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("status") != "pass":
        return False
    out = Path(str(payload.get("output") or ""))
    if not out.is_absolute():
        out = report_path.parent / out
    return out.resolve() == expected_out.resolve()


def _skin_joint_names(glb_path: Path) -> set[str]:
    with glb_path.open("rb") as handle:
        handle.read(12)
        chunk_len, _chunk_type = struct.unpack("<II", handle.read(8))
        gltf = json.loads(handle.read(chunk_len))
    skins = gltf.get("skins") or []
    if not skins:
        return set()
    joints = skins[0].get("joints") or []
    names: set[str] = set()
    for joint_index in joints:
        name = str(gltf["nodes"][joint_index].get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _bridgefix_presets_for(raw: Path) -> list[str | None]:
    joints = _skin_joint_names(raw)
    presets: list[str | None] = []
    if UNIRIG_WEAPON_BONES.issubset(joints):
        presets.append(None)
    if MIXAMO_WEAPON_BONES.issubset(joints):
        presets.append("mixamo_sword")
    if not presets:
        presets.append(None)
    # De-dupe while preserving order.
    seen: set[str | None] = set()
    ordered: list[str | None] = []
    for preset in presets:
        if preset in seen:
            continue
        seen.add(preset)
        ordered.append(preset)
    return ordered


def _run_bridgefix(
    *,
    blender: Path,
    paths: dict[str, Path],
    max_tip_contam: int,
    overwrite: bool,
    weapon_bones: str | None = None,
    max_delete_face_frac: float = 0.12,
) -> dict[str, Any]:
    if _bridgefix_ok(paths["bridge_report"], expected_out=paths["bridge"]) and not overwrite:
        return {"status": "reused", "output": str(paths["bridge"]), "report": str(paths["bridge_report"])}
    if not paths["raw"].is_file():
        raise FileNotFoundError(f"raw Meshy GLB missing: {paths['raw']}")
    command = [
        str(blender),
        "-b",
        "--python",
        str(BRIDGEFIX_SCRIPT),
        "--",
        "--src",
        str(paths["raw"]),
        "--out",
        str(paths["bridge"]),
        "--report",
        str(paths["bridge_report"]),
        "--max-tip-contam",
        str(max_tip_contam),
        "--min-bridge-faces",
        "0",
        "--max-delete-face-frac",
        str(max_delete_face_frac),
    ]
    if weapon_bones:
        command.extend(["--weapon-bones", weapon_bones])
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"bridgefix failed for {paths['raw'].name} (exit {completed.returncode})")
    if not _bridgefix_ok(paths["bridge_report"], expected_out=paths["bridge"]):
        raise RuntimeError(f"bridgefix report not ok for {paths['raw'].name}")
    payload = json.loads(paths["bridge_report"].read_text(encoding="utf-8"))
    return {
        "status": "ran",
        "output": str(paths["bridge"]),
        "report": str(paths["bridge_report"]),
        "facesDeleted": payload.get("facesDeleted"),
        "chromaBridgeFallback": payload.get("chromaBridgeFallback"),
        "weaponBonesPreset": weapon_bones or "unirig_default",
    }


def _run_bridgefix_with_retries(
    *,
    blender: Path,
    paths: dict[str, Path],
    max_tip_contam: int,
    overwrite: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    delete_fracs = (0.12, 0.15)
    for preset in _bridgefix_presets_for(paths["raw"]):
        for delete_frac in delete_fracs:
            try:
                result = _run_bridgefix(
                    blender=blender,
                    paths=paths,
                    max_tip_contam=max_tip_contam,
                    overwrite=overwrite,
                    weapon_bones=preset,
                    max_delete_face_frac=delete_frac,
                )
                if delete_frac > 0.12:
                    result["maxDeleteFaceFrac"] = delete_frac
                return result
            except Exception as exc:
                errors.append(f"{preset or 'unirig_default'}@{delete_frac}: {exc}")
    raise RuntimeError("; ".join(errors))


def _run_rigidize(*, paths: dict[str, Path], overwrite: bool, src: Path | None = None) -> dict[str, Any]:
    if _rigid_ok(paths["rigid_report"], expected_out=paths["rigid"]) and not overwrite:
        return {"status": "reused", "output": str(paths["rigid"]), "report": str(paths["rigid_report"])}
    mesh_src = (src or paths["bridge"]).resolve()
    if not mesh_src.is_file():
        raise FileNotFoundError(f"rigidize source GLB missing: {mesh_src}")
    command = [
        sys.executable,
        str(RIGIDIZE_WRAPPER),
        "--src",
        str(mesh_src),
        "--out",
        str(paths["rigid"]),
        "--report",
        str(paths["rigid_report"]),
        "--config",
        str(RIGIDIZE_CONFIG),
    ]
    if overwrite:
        command.append("--overwrite")
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"rigidization failed for {paths['bridge'].name} (exit {completed.returncode})")
    if not _rigid_ok(paths["rigid_report"], expected_out=paths["rigid"]):
        raise RuntimeError(f"rigidization report not pass for {mesh_src.name}")
    return {
        "status": "ran",
        "output": str(paths["rigid"]),
        "report": str(paths["rigid_report"]),
        "source": str(mesh_src),
    }


def _repair_unit(
    *,
    sid: str,
    blender: Path,
    max_tip_contam: int,
    overwrite: bool,
) -> dict[str, Any]:
    paths = _paths_for(sid)
    bridge_mode = "bridgefix"
    try:
        bridge = _run_bridgefix_with_retries(
            blender=blender,
            paths=paths,
            max_tip_contam=max_tip_contam,
            overwrite=overwrite,
        )
        rigid_src = paths["bridge"]
    except Exception as bridge_exc:
        err = str(bridge_exc).lower()
        weapon_bones_missing = "weapon bones missing" in err or "weapon-bones resolved empty" in err
        if not weapon_bones_missing:
            raise bridge_exc
        bridge_mode = "rigidize_raw_only"
        bridge = {
            "status": "skipped",
            "reason": str(bridge_exc),
            "weaponBonesPreset": "none",
        }
        rigid_src = paths["raw"]
    print(f"[castle-mesh-repair] {sid} rigidize ({bridge_mode})...", flush=True)
    rigid = _run_rigidize(paths=paths, overwrite=overwrite, src=rigid_src)
    return {"labSid": sid, "mode": bridge_mode, "bridgefix": bridge, "rigidize": rigid}


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        default=[],
        help="Restrict to these lab SIDs (default: all Castle units missing rigidized mesh).",
    )
    parser.add_argument("--max-tip-contam", type=int, default=200)
    parser.add_argument("--overwrite", action="store_true", help="Re-run even when passing reports exist.")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first bridgefix/rigidize failure (default: record and continue).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--blender", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse()
    blender = resolve_pose_fit_blender(args.blender)
    targets: list[str] = []
    skipped_done: list[str] = []
    for sid in _castle_lab_sids():
        if args.only and sid not in args.only:
            continue
        paths = _paths_for(sid)
        if not paths["raw"].is_file():
            continue
        if paths["rigid"].is_file() and not args.overwrite:
            skipped_done.append(sid)
            continue
        targets.append(sid)

    plan = {
        "updatedAt": _utc_now(),
        "blender": str(blender),
        "maxTipContam": int(args.max_tip_contam),
        "targets": targets,
        "skippedAlreadyRigidized": skipped_done,
        "dryRun": bool(args.dry_run),
    }
    print(json.dumps(plan, indent=2))
    if args.dry_run:
        return 0

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for sid in targets:
        try:
            print(f"[castle-mesh-repair] {sid} bridgefix...", flush=True)
            results.append(
                _repair_unit(
                    sid=sid,
                    blender=blender,
                    max_tip_contam=int(args.max_tip_contam),
                    overwrite=bool(args.overwrite),
                )
            )
        except Exception as exc:
            failure = {"labSid": sid, "error": str(exc)}
            failures.append(failure)
            print(json.dumps({"failed": failure}, indent=2), file=sys.stderr)
            if args.fail_fast:
                break

    summary = {
        **plan,
        "completedAt": _utc_now(),
        "ok": not failures,
        "repairedCount": len(results),
        "failureCount": len(failures),
        "results": results,
        "failures": failures,
        "nextStep": "python tools/homm3_silhouette_pose_fit/inventory_smartrig_skinned_rollout.py",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(args.summary), "repairedCount": len(results), "failureCount": len(failures)}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
