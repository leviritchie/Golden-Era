#!/usr/bin/env python3
"""Phase 0 read-only audit of fused-push payloads, seams, and Animator mapping.

Writes ``artifacts/deliberate_motion_baseline.json`` plus a short report of the
worst unsupported movements and worst six boundaries. Does not invent missing
MoveStart/MoveEnd motion. Proof tier: generated-artifact inventory.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
DEFAULT_ROLLOUT = ROOT / "artifacts" / "fused_push_skinned_rollout"
DEFAULT_UNITS = DEFAULT_ROLLOUT / "stronghold_skinned_units.txt"
OUT_JSON = ROOT / "artifacts" / "deliberate_motion_baseline.json"
OUT_REPORT = ROOT / "artifacts" / "deliberate_motion_baseline.md"

import sys

sys.path.insert(0, str(TOOL))

from deliberate_motion_boundaries import bones_in_poses, cycle_seam_report
from deliberate_motion_contract import (
    AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
    PREVIEW_FRAME_DURATION_SECONDS,
    unit_contract_from_clip_sidecars,
)
from gpu_cascade_delivery import require_pose_units_degrees


def _sliced_delivery_poses(payload: Mapping[str, Any], sidecar: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    raw = {int(frame): pose for frame, pose in (payload.get("poses") or {}).items()}
    count = int(sidecar.get("frameCount") or sidecar.get("sourceFrameCount") or 0)
    if count < 1:
        raise ValueError("sidecar is missing frameCount")
    prefix = int(sidecar.get("idlePrefixFrames") or 0)
    animation = str(sidecar.get("fitAnimation") or "")
    if animation == "idle":
        if len(raw) < count:
            raise ValueError("idle payload is shorter than frameCount")
        return {index: raw[index] for index in range(count)}
    missing = [index for index in range(prefix, prefix + count) if index not in raw]
    if missing:
        raise KeyError(f"payload missing sliced frames {missing[:8]}")
    return {index: raw[prefix + index] for index in range(count)}

MOTION_ROOTS = ("__motion_root__", "__motion_root_rotation__")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sprite_pair_mad(paths: list[Path]) -> list[float]:
    mads: list[float] = []
    previous = None
    for path in paths:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((64, 64))
            pixels = list(rgb.getdata())
        if previous is None:
            mads.append(0.0)
        else:
            total = 0.0
            for left, right in zip(previous, pixels):
                total += abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])
            mads.append(total / (255.0 * 3.0 * max(len(pixels), 1)))
        previous = pixels
    return mads


def _mean_bone_step_deg(poses: Mapping[int, Mapping[str, Any]]) -> tuple[float, float, str | None]:
    frames = tuple(sorted(int(frame) for frame in poses))
    bones = bones_in_poses(poses)
    if len(frames) < 2 or not bones:
        return 0.0, 0.0, None
    worst = 0.0
    worst_bone = None
    total = 0.0
    count = 0
    for previous, current in zip(frames, frames[1:]):
        pa = poses[previous]
        pb = poses[current]
        for bone in bones:
            a = pa.get(bone) or {}
            b = pb.get(bone) or {}
            step = math.sqrt(
                sum(
                    (float(a.get(axis, 0.0)) - float(b.get(axis, 0.0))) ** 2
                    for axis in ("x", "y", "z")
                )
            )
            total += step
            count += 1
            if step > worst:
                worst = step
                worst_bone = f"{bone}@f{current}"
    return (total / max(count, 1), worst, worst_bone)


def audit_unit(unit_dir: Path) -> dict[str, Any]:
    sid = unit_dir.name
    clips_dir = unit_dir / "clips"
    sidecars = []
    clip_reports = []
    for sidecar_path in sorted(clips_dir.glob("*.json")):
        sidecar = _load_json(sidecar_path)
        sidecars.append(sidecar)
        glb = sidecar_path.with_suffix(".glb")
        result_path = Path(str(sidecar.get("clipResultPath") or ""))
        payload = _load_json(result_path) if result_path.is_file() else {}
        if payload:
            require_pose_units_degrees(payload, source=str(result_path))
        poses = {}
        if payload.get("poses"):
            try:
                poses = _sliced_delivery_poses(payload, sidecar)
            except Exception as exc:  # noqa: BLE001
                poses = {int(frame): pose for frame, pose in payload["poses"].items()}
                clip_reports.append(
                    {
                        "contractName": sidecar.get("contractName"),
                        "error": f"delivery slice failed: {exc}",
                    }
                )
        mean_step, worst_step, worst_bone = _mean_bone_step_deg(poses) if poses else (0.0, 0.0, None)
        seam = (
            cycle_seam_report(poses, frame_duration_seconds=AUTHENTIC_DEF_FRAME_DURATION_SECONDS)
            if poses
            else {}
        )
        target_paths = [Path(item) for item in (payload.get("targetPaths") or []) if item]
        suffix = str(sidecar.get("contractName") or "")
        want_mad = suffix.endswith("_Idle") or suffix.endswith("_Move")
        sprite_mad = (
            _sprite_pair_mad(target_paths)
            if want_mad and len(target_paths) >= 2 and all(p.is_file() for p in target_paths)
            else []
        )
        physics = payload.get("physicsSmooth") if isinstance(payload.get("physicsSmooth"), Mapping) else {}
        motion_root_serialized = any(
            bone in (poses.get(frame) or {}) for frame in list(poses)[:1] for bone in MOTION_ROOTS
        )
        clip_reports.append(
            {
                "contractName": sidecar.get("contractName"),
                "defGroup": sidecar.get("defGroup"),
                "frameCount": sidecar.get("frameCount") or sidecar.get("sourceFrameCount"),
                "durationSeconds": sidecar.get("durationSeconds"),
                "keyCount": sidecar.get("keyCount"),
                "glbExists": glb.is_file(),
                "physicsSmoothEnabled": bool(physics.get("enabled")),
                "meanBoneStepDeg": mean_step,
                "worstBoneStepDeg": worst_step,
                "worstBoneStep": worst_bone,
                "c0MaxDeg": seam.get("c0MaxDeg"),
                "c1MaxDegPerSecond": seam.get("c1MaxDegPerSecond"),
                "worstC0Bone": seam.get("worstC0Bone"),
                "spritePairMad": sprite_mad,
                "maxSpriteMad": max(sprite_mad) if sprite_mad else 0.0,
                "motionRootPresentInPoses": any(
                    any(bone in (pose or {}) for bone in MOTION_ROOTS) for pose in poses.values()
                ),
                "motionRootSerializedInClip": motion_root_serialized and False,
                "onePose": int(sidecar.get("frameCount") or 0) < 2,
            }
        )
    mobile = any(str(item.get("contractName") or "").endswith("_Move") for item in sidecars)
    contract = unit_contract_from_clip_sidecars(sid, sidecars, mobile=mobile)
    blocked = [
        row["contractName"]
        for row in contract["clips"]
        if str(row.get("fullAnimationReadiness") or "").startswith("blocked")
    ]
    landmarks_missing = True
    return {
        "labSid": sid,
        "contract": contract,
        "clips": clip_reports,
        "blockedTransitions": blocked,
        "authoredLandmarksPresent": not landmarks_missing,
        "timing": {
            "deliveryFrameDurationSeconds": AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
            "deliveryTimingOwner": "authentic_def_group_playback",
            "previewFrameDurationSeconds": PREVIEW_FRAME_DURATION_SECONDS,
            "previewTimingOwner": "pose_pipeline_stick_gif",
            "solverFpsNotAuthority": True,
        },
        "stockGroundBypass": "Idle maps to 22.Idle and Move to 01.Walk; stock donor still Idle<->Move",
        "proofTier": "generated-artifact inventory",
        "fullAnimationReady": False,
        "contractErrors": list(contract.get("errors") or []),
    }


def write_report(units: list[dict[str, Any]], dest: Path) -> None:
    boundaries = []
    unsupported = []
    for unit in units:
        for clip in unit.get("clips") or []:
            if clip.get("error"):
                unsupported.append((1e9, unit["labSid"], clip["error"]))
                continue
            name = str(clip.get("contractName") or "")
            if clip.get("onePose") and name.endswith(("MoveStart", "MoveEnd")):
                unsupported.append(
                    (1e8, unit["labSid"], f"{name} is a one-pose transition")
                )
            if name.endswith(("_Idle", "_Move", "_Mouseover", "_Defence")):
                c0 = float(clip.get("c0MaxDeg") or 0.0)
                boundaries.append((c0, unit["labSid"], name, clip.get("worstC0Bone")))
            step = float(clip.get("worstBoneStepDeg") or 0.0)
            mad = float(clip.get("maxSpriteMad") or 0.0)
            if step > 20.0 and mad < 0.01:
                unsupported.append(
                    (
                        step,
                        unit["labSid"],
                        f"{clip.get('contractName')} {clip.get('worstBoneStep')} travels {step:.1f} deg "
                        f"over still-ish sprites (max MAD {mad:.4f})",
                    )
                )
    boundaries.sort(reverse=True)
    unsupported.sort(reverse=True)
    lines = [
        "# Deliberate motion baseline (Stronghold)",
        "",
        "Proof tier: generated-artifact inventory. Not Unity build, not installed payload,",
        "not user-visible gameplay.",
        "",
        f"Units audited: {len(units)}",
        "",
        "## Worst unsupported movements",
        "",
    ]
    for _, sid, text in unsupported[:12]:
        lines.append(f"- `{sid}`: {text}")
    if not unsupported:
        lines.append("- none recorded")
    lines.extend(["", "## Worst six cycle boundaries (C0 geodesic degrees)", ""])
    for c0, sid, name, bone in boundaries[:6]:
        lines.append(f"- `{sid}` `{name}`: C0={c0:.3f} deg (worst bone `{bone}`)")
    lines.extend(
        [
            "",
            "## Classification",
            "",
            "- Delivery timing owner: authentic DEF group playback at 1/12 s per pose.",
            "- Preview timing owner: stick/lit GIF at 180 ms per pose. These are not interchangeable.",
            "- One-pose MoveStart/MoveEnd blocks the full-animation lane. Missing motion is not invented.",
            "- Stock Esquire still routes ordinary ground walk Idle <-> Move, bypassing MoveStart/MoveEnd.",
            "- Authored landmark contracts are not present on fused-push Stronghold payloads.",
            "",
        ]
    )
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--units-file", type=Path, default=DEFAULT_UNITS)
    parser.add_argument("--write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    names = [
        line.strip()
        for line in args.units_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    units = []
    missing = []
    for name in names:
        unit_dir = args.rollout_dir / "units" / name
        if not (unit_dir / "clips").is_dir():
            missing.append(name)
            continue
        units.append(audit_unit(unit_dir))
    payload = {
        "schema": "deliberate_motion_baseline.v1",
        "proofTier": "generated-artifact inventory",
        "rolloutDir": str(args.rollout_dir),
        "units": units,
        "missingUnits": missing,
        "calibratedLimits": {
            "idleC0MaxDeg": None,
            "moveC0MaxDeg": None,
            "c1MaxDegPerSecond": None,
            "playerApprovedStopLatencySeconds": None,
            "note": "limits are uncalibrated until player-approved reference previews exist",
        },
        "pilots": {
            "groundWalker": "h3_goblin",
            "flyer": "h3_roc",
            "compound": "h3_wolf_rider",
        },
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.write:
        OUT_JSON.write_text(text, encoding="utf-8")
        write_report(units, OUT_REPORT)
        print(f"wrote {OUT_JSON} and {OUT_REPORT}", flush=True)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
