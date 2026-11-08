#!/usr/bin/env python3
"""Parent-only prep: stage prop-author sprites + manifest before subagent delegation.

The subagent must never search the repo for frames. Run this first; pass
``author_bundle.json`` into the delegate prompt.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ART = ROOT / "artifacts"

# Locked presets — extend here; do not make the subagent discover paths.
PRESETS: dict[str, dict] = {
    "h3_crusader_move_g0_idle_start_move": {
        "unitSid": "h3_crusader",
        "clipId": "move_g0",
        "defGroup": 0,
        "defName": "move",
        "sequence": "idle_start_move (DEF groups 2+20+0; walk is indices 10-17)",
        "sourceFramesDir": ART
        / "pose_picker_runs/h3_crusader/idle_start_move/frames_def12_nn_idle_start_move_shadow_culled",
        "frameIndices": list(range(10, 18)),
        "outDir": ART / "pose_picker_runs/h3_crusader/move_g0_props_authored",
        "joints": ["WeaponTip", "RWrist", "ShieldCenter", "LWrist"],
        "edgeSet": "crusader_sword_shield",
    },
    "h3_crusader_sprite_skeleton_walk_idle_prefix": {
        "unitSid": "h3_crusader",
        "clipId": "idle_start_move_end",
        "defGroup": None,
        "defName": "walk",
        "sequence": "Render via render_sprite_skeleton_overlay.py from idle_prefix_refine_v1",
        "sourceFramesDir": ART
        / "pose_picker_runs/h3_crusader/idle_start_move_end/sprite_skeleton_walk_props_authored/sprites",
        "frameIndices": list(range(10, 18)),
        "outDir": ART
        / "pose_picker_runs/h3_crusader/idle_start_move_end/sprite_skeleton_walk_props_authored",
        "joints": ["WeaponTip", "RWrist", "ShieldCenter", "LWrist"],
        "edgeSet": "crusader_sword_shield_sprite_skeleton",
    },
    "h3_crusader_solved_walk_idle_prefix": {
        "unitSid": "h3_crusader",
        "clipId": "idle_start_move_end",
        "defGroup": None,
        "defName": "walk",
        "sequence": "idle_prefix_refine_v1 solved_rgb walk frames 10-17 (192x172 GPU raster)",
        "sourceFramesDir": ART
        / "pose_picker_runs/h3_crusader/idle_start_move_end/idle_prefix_refine_v1/solve/solved_rgb",
        "frameIndices": list(range(10, 18)),
        "outDir": ART
        / "pose_picker_runs/h3_crusader/idle_start_move_end/solved_walk_props_authored",
        "joints": ["WeaponTip", "RWrist", "ShieldCenter", "LWrist"],
        "edgeSet": "crusader_sword_shield_solved_raster",
    },
    "h3_crusader_move_g0_isolated": {
        "unitSid": "h3_crusader",
        "clipId": "move_g0",
        "defGroup": 0,
        "defName": "move",
        "sequence": "isolated move_g0 only (not idle_start_move prefix)",
        "sourceFramesDir": ART / "crusader_pose_pipeline/source_frames/nn_upscale_g00_move",
        "frameIndices": list(range(8)),
        "sourceNamePattern": "frame_{:02d}.png",
        "outDir": ART / "pose_picker_runs/h3_crusader/move_g0_props_authored_isolated",
        "joints": ["WeaponTip", "RWrist", "ShieldCenter", "LWrist"],
        "edgeSet": "crusader_sword_shield",
    },
}


def _resolve_source_path(source_dir: Path, frame_index: int, pattern: str | None) -> Path:
    if pattern:
        path = source_dir / pattern.format(frame_index)
        if path.is_file():
            return path
        raise FileNotFoundError(f"missing source sprite: {path}")
    numbered = source_dir / f"{frame_index:02d}.png"
    if numbered.is_file():
        return numbered
    plain = source_dir / f"{frame_index}.png"
    if plain.is_file():
        return plain
    raise FileNotFoundError(
        f"missing source sprite for frame {frame_index} under {source_dir} "
        f"(tried {numbered.name} and {plain.name})"
    )


def build_bundle(
    *,
    unit_sid: str,
    clip_id: str,
    source_frames_dir: Path,
    frame_indices: list[int],
    out_dir: Path,
    joints: list[str],
    edge_set: str,
    sequence: str,
    def_group: int | None,
    def_name: str | None,
    source_name_pattern: str | None,
) -> dict:
    source_frames_dir = Path(source_frames_dir)
    out_dir = Path(out_dir)
    if not source_frames_dir.is_dir():
        raise FileNotFoundError(f"source frames dir not found: {source_frames_dir}")

    sprites_dir = out_dir / "sprites"
    if sprites_dir.exists():
        shutil.rmtree(sprites_dir)
    sprites_dir.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    frames_out = []
    width = height = None
    for frame_index in frame_indices:
        source_path = _resolve_source_path(source_frames_dir, int(frame_index), source_name_pattern)
        staged_name = f"{int(frame_index):02d}.png"
        staged_path = sprites_dir / staged_name
        shutil.copy2(source_path, staged_path)
        with Image.open(staged_path) as im:
            w, h = im.size
        if width is None:
            width, height = int(w), int(h)
        elif (width, height) != (int(w), int(h)):
            raise RuntimeError(
                f"frame size mismatch at {source_path}: {(w, h)} vs {(width, height)}"
            )
        frames_out.append(
            {
                "frameIndex": int(frame_index),
                "stagedSprite": str(staged_path).replace("\\", "/"),
                "sourceSprite": str(source_path).replace("\\", "/"),
                "stagedName": staged_name,
            }
        )

    coords_path = out_dir / "props_coords.json"
    write_cmd = (
        f'cd "{ROOT}" && py -3 tools/homm3_silhouette_pose_fit/authorwrite_prop_keypoints.py '
        f'--coords "{coords_path}" '
        f'--frames-dir "{sprites_dir}" '
        f'--out-dir "{out_dir}" '
        f'--clip-id "{clip_id}" '
        f'--unit-sid "{unit_sid}"'
    )

    bundle = {
        "schema": "homm3_prop_author_bundle.v1",
        "unitSid": unit_sid,
        "clipId": clip_id,
        "defGroup": def_group,
        "defName": def_name,
        "sequence": sequence,
        "joints": list(joints),
        "edgeSet": edge_set,
        "spriteSize": {"width": width, "height": height},
        "repoRoot": str(ROOT).replace("\\", "/"),
        "outDir": str(out_dir).replace("\\", "/"),
        "spritesDir": str(sprites_dir).replace("\\", "/"),
        "coordsPath": str(coords_path).replace("\\", "/"),
        "keypointsPath": str(out_dir / "sprite_landmarks/keypoints.json").replace("\\", "/"),
        "previewGifPath": str(out_dir / f"{clip_id}_props_authored.gif").replace("\\", "/"),
        "overlaysDir": str(out_dir / "overlays").replace("\\", "/"),
        "writeCommand": write_cmd,
        "frames": frames_out,
        "markingMethod": "multimodal_eye_only",
        "forbiddenForSubagent": [
            "track_joints_lk",
            "auto tag",
            "automatic tag",
            "pose estimation",
            "opencv",
            "mediapipe",
            "mesh projection",
            "grep/search for sprite paths",
            "glob/search repo for frames",
        ],
    }
    bundle_path = out_dir / "author_bundle.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    bundle["bundlePath"] = str(bundle_path).replace("\\", "/")
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage prop-author bundle for subagent delegation")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Locked clip preset")
    parser.add_argument("--list-presets", action="store_true", help="Print preset names and exit")
    args = parser.parse_args(argv)

    if args.list_presets:
        for name, preset in PRESETS.items():
            print(f"{name}: {preset.get('sequence')}")
            print(f"  out: {preset['outDir']}")
            print(f"  frames: {preset['frameIndices']}")
        return 0

    if not args.preset:
        parser.error("--preset is required (or use --list-presets)")

    preset = PRESETS[args.preset]
    bundle = build_bundle(
        unit_sid=str(preset["unitSid"]),
        clip_id=str(preset["clipId"]),
        source_frames_dir=Path(preset["sourceFramesDir"]),
        frame_indices=[int(i) for i in preset["frameIndices"]],
        out_dir=Path(preset["outDir"]),
        joints=list(preset["joints"]),
        edge_set=str(preset["edgeSet"]),
        sequence=str(preset["sequence"]),
        def_group=preset.get("defGroup"),
        def_name=preset.get("defName"),
        source_name_pattern=preset.get("sourceNamePattern"),
    )
    print(json.dumps({"ok": True, **bundle}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
