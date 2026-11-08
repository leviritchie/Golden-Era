#!/usr/bin/env python3
"""Write prop-only keypoints.json + stick overlay GIF from a coords JSON file.

The coords file is produced by the prop-keypoint-author subagent after eye-marking
each sprite. Fail-closed on frame count / joint name mismatches.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from prop_author_common import (
    CRUSADER_SWORD_SHIELD_JOINTS,
    write_prop_authored_clip,
)


def _load_coords(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "frames" not in data:
        raise ValueError("coords JSON must contain a 'frames' array")
    return data


def _frames_xy_from_coords(data: dict) -> tuple[list[dict[str, tuple[int, int]]], list[int] | None]:
    joint_names = tuple(data.get("joints", CRUSADER_SWORD_SHIELD_JOINTS))
    frames_xy: list[dict[str, tuple[int, int]]] = []
    frame_indices: list[int] = []
    has_explicit_index = False
    for entry in data["frames"]:
        if "xy" not in entry:
            raise ValueError("each frame entry needs an 'xy' object")
        xy = {str(k): (int(v[0]), int(v[1])) for k, v in entry["xy"].items()}
        frames_xy.append(xy)
        if "frameIndex" in entry:
            has_explicit_index = True
            frame_indices.append(int(entry["frameIndex"]))
    return frames_xy, frame_indices if has_explicit_index else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write prop-only sprite landmarks + preview GIF")
    parser.add_argument("--coords", type=Path, required=True, help="Authored prop coords JSON")
    parser.add_argument("--frames-dir", type=Path, required=True, help="Sprite PNG directory")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output fit dir")
    parser.add_argument("--clip-id", type=str, default=None, help="Override clipId in coords")
    parser.add_argument("--unit-sid", type=str, default=None, help="Override unitSid in coords")
    parser.add_argument(
        "--edge-set",
        type=str,
        default="crusader_sword_shield",
        help="Named edge set in prop_author_common.PROP_EDGES",
    )
    args = parser.parse_args(argv)

    data = _load_coords(args.coords)
    joint_names = tuple(data.get("joints", CRUSADER_SWORD_SHIELD_JOINTS))
    clip_id = str(args.clip_id or data.get("clipId") or "props_clip")
    unit_sid = str(args.unit_sid or data.get("unitSid") or "h3_crusader")
    notes = str(data.get("notes") or f"prop landmarks for {clip_id}")
    frames_xy, frame_indices = _frames_xy_from_coords(data)

    result = write_prop_authored_clip(
        clip_id=clip_id,
        unit_sid=unit_sid,
        frames_dir=args.frames_dir,
        out_dir=args.out_dir,
        frames_xy=frames_xy,
        joint_names=joint_names,
        notes=notes,
        edge_set=str(data.get("edgeSet") or args.edge_set),
        frame_indices=frame_indices,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
