#!/usr/bin/env python3
"""Experiment: extract WeaponTip from genAI-edited sprites with a neon pink square.

The generative step uses a deceptive prompt (pink square on sword tip only; no mention
of keypoints). This script detects the pink marker centroid and writes prop keypoints.

Proof tier: generated-artifact only — not validated against OE runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from authorwrite_prop_keypoints import _frames_xy_from_coords  # noqa: E402
from prop_author_common import write_prop_authored_clip  # noqa: E402

# Deceptive prompt — no mention of landmarks, IK, or keypoints.
DECEPTIVE_PROMPT = (
    "Add a small solid neon pink (#FF00FF) square exactly on the tip of the sword blade. "
    "Make NO other changes to the image."
)

# Explicit landmarking prompt — same marker, but the task is stated plainly.
LANDMARKING_PROMPT = (
    "You are marking a 2D sprite animation landmark for inverse-kinematics keypoint authoring. "
    "Place a small solid neon pink (#FF00FF) square exactly on the WeaponTip landmark: "
    "the furthest visible pixel on the sword blade tip (not the helmet plume). "
    "Make NO other changes to the sprite — preserve pose, colors, background, and composition."
)

PROMPTS: dict[str, str] = {
    "deceptive": DECEPTIVE_PROMPT,
    "landmarking": LANDMARKING_PROMPT,
}

NEON_PINK_RGB = (255, 0, 255)
PINK_TOLERANCE = 80


def resolve_prompt(mode: str) -> str:
    key = str(mode).strip().lower()
    if key not in PROMPTS:
        raise ValueError(f"unknown prompt mode {mode!r}; expected one of {sorted(PROMPTS)}")
    return PROMPTS[key]


def deceptive_prompt() -> str:
    return DECEPTIVE_PROMPT


def detect_neon_pink_centroid(
    image: Image.Image,
    *,
    tolerance: int = PINK_TOLERANCE,
    min_pixels: int = 4,
) -> tuple[int, int, int]:
    """Return (x, y, pixel_count) for the largest neon-pink cluster."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    target = np.array(NEON_PINK_RGB, dtype=np.int16)
    dist = np.linalg.norm(rgb - target, axis=2)
    mask = dist <= float(tolerance)
    count = int(mask.sum())
    if count < min_pixels:
        raise ValueError(
            f"neon pink marker not found (matched {count} px, need >= {min_pixels})"
        )
    ys, xs = np.nonzero(mask)
    return int(round(xs.mean())), int(round(ys.mean())), count


def map_point_to_source(
    point: tuple[int, int],
    *,
    edited_size: tuple[int, int],
    source_size: tuple[int, int],
) -> tuple[int, int]:
    ex, ey = point
    ew, eh = edited_size
    sw, sh = source_size
    if (ew, eh) == (sw, sh):
        return ex, ey
    sx = int(round(ex * (sw - 1) / max(1, ew - 1)))
    sy = int(round(ey * (sh - 1) / max(1, eh - 1)))
    return sx, sy


def load_ground_truth_weapon_tips(path: Path) -> dict[int, tuple[int, int]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, tuple[int, int]] = {}
    for frame in doc.get("frames", []):
        idx = int(frame.get("frameIndex", len(out)))
        joints = frame.get("joints", {})
        tip = joints.get("WeaponTip")
        if not tip or not tip.get("visible", True):
            continue
        out[idx] = (int(round(float(tip["x"]))), int(round(float(tip["y"]))))
    return out


def compare_to_ground_truth(
    detected: dict[int, tuple[int, int]],
    ground_truth: dict[int, tuple[int, int]],
) -> dict[str, Any]:
    rows = []
    errors = []
    for idx in sorted(detected):
        if idx not in ground_truth:
            continue
        dx = detected[idx][0] - ground_truth[idx][0]
        dy = detected[idx][1] - ground_truth[idx][1]
        err = math.hypot(dx, dy)
        errors.append(err)
        rows.append(
            {
                "frameIndex": idx,
                "detected": list(detected[idx]),
                "groundTruth": list(ground_truth[idx]),
                "deltaPx": [dx, dy],
                "errorPx": round(err, 2),
            }
        )
    return {
        "framesCompared": len(rows),
        "meanErrorPx": round(float(np.mean(errors)), 2) if errors else None,
        "maxErrorPx": round(float(np.max(errors)), 2) if errors else None,
        "perFrame": rows,
    }


def extract_weapon_tips_from_edited_dir(
    *,
    source_frames_dir: Path,
    edited_dir: Path,
    frame_indices: list[int],
    edited_name_pattern: str = "frame_{:02d}_edited.png",
) -> list[dict[str, Any]]:
    source_frames_dir = Path(source_frames_dir)
    edited_dir = Path(edited_dir)
    frames_out: list[dict[str, Any]] = []
    for frame_index in frame_indices:
        source_path = source_frames_dir / f"{frame_index:02d}.png"
        if not source_path.is_file():
            source_path = source_frames_dir / f"frame_{frame_index:02d}.png"
        if not source_path.is_file():
            raise FileNotFoundError(f"missing source frame {frame_index} under {source_frames_dir}")
        edited_path = edited_dir / edited_name_pattern.format(frame_index)
        if not edited_path.is_file():
            raise FileNotFoundError(f"missing edited frame: {edited_path}")
        with Image.open(source_path) as src_im:
            source_size = src_im.size
        with Image.open(edited_path) as edit_im:
            cx, cy, px_count = detect_neon_pink_centroid(edit_im)
            mapped = map_point_to_source(
                (cx, cy),
                edited_size=edit_im.size,
                source_size=source_size,
            )
        frames_out.append(
            {
                "frameIndex": int(frame_index),
                "xy": {"WeaponTip": mapped},
                "detection": {
                    "editedPath": str(edited_path).replace("\\", "/"),
                    "editedCentroid": [cx, cy],
                    "editedSize": list(edit_im.size),
                    "sourceSize": list(source_size),
                    "pinkPixelCount": px_count,
                },
            }
        )
    return frames_out


def write_experiment_outputs(
    *,
    out_dir: Path,
    source_frames_dir: Path,
    frames: list[dict[str, Any]],
    clip_id: str,
    unit_sid: str,
    ground_truth_path: Path | None,
    prompt: str,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    coords_path = out_dir / "props_coords.json"
    coords_doc = {
        "clipId": clip_id,
        "unitSid": unit_sid,
        "joints": ["WeaponTip"],
        "edgeSet": "crusader_sword_shield",
        "notes": (
            f"genai pink-square experiment; prompt={prompt!r}; "
            "WeaponTip from neon pink centroid only"
        ),
        "genaiPrompt": prompt,
        "method": "genai_pink_square_centroid",
        "frames": [{"frameIndex": f["frameIndex"], "xy": f["xy"]} for f in frames],
    }
    coords_path.write_text(json.dumps(coords_doc, indent=2) + "\n", encoding="utf-8")

    frames_xy, frame_indices = _frames_xy_from_coords(coords_doc)
    result = write_prop_authored_clip(
        clip_id=clip_id,
        unit_sid=unit_sid,
        frames_dir=source_frames_dir,
        out_dir=out_dir,
        frames_xy=frames_xy,
        joint_names=["WeaponTip"],
        notes=coords_doc["notes"],
        edge_set="crusader_sword_shield",
        frame_indices=frame_indices,
    )
    keypoints_path = Path(result["keypoints"])
    doc = json.loads(keypoints_path.read_text(encoding="utf-8"))
    doc["method"] = "genai_pink_square_centroid"
    doc["proof"] = (
        "WeaponTip from genAI neon-pink square marker + color centroid; "
        "generated-artifact experiment only"
    )
    for frame in doc.get("frames", []):
        for joint in frame.get("joints", {}).values():
            joint["source"] = "genai_pink_square"
    keypoints_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    detection_report = {
        "prompt": prompt,
        "frames": frames,
    }
    if ground_truth_path and ground_truth_path.is_file():
        gt = load_ground_truth_weapon_tips(ground_truth_path)
        detected = {int(f["frameIndex"]): tuple(f["xy"]["WeaponTip"]) for f in frames}
        detection_report["comparison"] = compare_to_ground_truth(detected, gt)
    report_path = out_dir / "genai_pink_detection_report.json"
    report_path.write_text(json.dumps(detection_report, indent=2) + "\n", encoding="utf-8")

    result.update(
        {
            "coords": str(coords_path).replace("\\", "/"),
            "detectionReport": str(report_path).replace("\\", "/"),
            "method": "genai_pink_square_centroid",
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect WeaponTip from genAI neon-pink square edits"
    )
    parser.add_argument("--source-frames-dir", type=Path, required=True)
    parser.add_argument("--edited-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--frame-indices", type=str, default="8-14")
    parser.add_argument("--clip-id", type=str, default="attack_front_g12")
    parser.add_argument("--unit-sid", type=str, default="h3_crusader")
    parser.add_argument(
        "--ground-truth",
        type=Path,
        help="Human-authored keypoints.json for comparison",
    )
    parser.add_argument(
        "--edited-name-pattern",
        type=str,
        default="frame_{:02d}_edited.png",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=sorted(PROMPTS),
        default="deceptive",
        help="Which genAI prompt variant produced the edited frames",
    )
    parser.add_argument(
        "--compare-run",
        type=Path,
        help="Optional prior genai_pink_detection_report.json to diff against",
    )
    args = parser.parse_args(argv)

    if "-" in args.frame_indices and "," not in args.frame_indices:
        start_s, end_s = args.frame_indices.split("-", 1)
        frame_indices = list(range(int(start_s), int(end_s) + 1))
    else:
        frame_indices = [int(x.strip()) for x in args.frame_indices.split(",") if x.strip()]

    frames = extract_weapon_tips_from_edited_dir(
        source_frames_dir=args.source_frames_dir,
        edited_dir=args.edited_dir,
        frame_indices=frame_indices,
        edited_name_pattern=args.edited_name_pattern,
    )
    prompt = resolve_prompt(args.prompt_mode)
    result = write_experiment_outputs(
        out_dir=args.out_dir,
        source_frames_dir=args.source_frames_dir,
        frames=frames,
        clip_id=args.clip_id,
        unit_sid=args.unit_sid,
        ground_truth_path=args.ground_truth,
        prompt=prompt,
    )
    if args.compare_run and args.compare_run.is_file():
        prior = json.loads(args.compare_run.read_text(encoding="utf-8"))
        prior_cmp = prior.get("comparison") or {}
        current_report = json.loads(
            Path(result["detectionReport"]).read_text(encoding="utf-8")
        )
        current_cmp = current_report.get("comparison") or {}
        result["promptMode"] = args.prompt_mode
        result["versusPriorRun"] = {
            "priorReport": str(args.compare_run).replace("\\", "/"),
            "priorMeanErrorPx": prior_cmp.get("meanErrorPx"),
            "currentMeanErrorPx": current_cmp.get("meanErrorPx"),
            "priorMaxErrorPx": prior_cmp.get("maxErrorPx"),
            "currentMaxErrorPx": current_cmp.get("maxErrorPx"),
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
