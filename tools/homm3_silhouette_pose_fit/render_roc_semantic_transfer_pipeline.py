#!/usr/bin/env python3
"""Build reusable side-by-side Roc semantic-transfer review deliverables.

Consumes the completed pose-fit report and committed full-resolution mesh
renders. It does not depend on a live notebook kernel. The GIF preserves the
project's 180 ms per source frame review timing; the MP4 is encoded at 60 fps
with repeated source frames so it has the same wall-clock playback speed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/frames_nn_shadow_culled"
DEFAULT_MESH = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/roc_chroma_match_v1"
DEFAULT_OUT = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/roc_semantic_transfer_review"
SEMANTIC_MODEL = "google/siglip2-base-patch16-512"


def _find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    raise RuntimeError("ffmpeg is required for MP4 output")


def _frame_index(path: Path) -> int:
    return int(path.stem.split("_")[-1]) if "_" in path.stem else int(path.stem)


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def compose_pair(target_path: Path, mesh_path: Path, out_path: Path, *, frame_index: int) -> None:
    target = Image.open(target_path).convert("RGBA")
    mesh = Image.open(mesh_path).convert("RGBA")
    width = target.width + mesh.width
    height = max(target.height, mesh.height) + 36
    canvas = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    canvas.alpha_composite(target, (0, 36))
    canvas.alpha_composite(mesh, (target.width, 36))
    draw = ImageDraw.Draw(canvas)
    label = _font(20)
    draw.text((12, 8), f"sprite frame {frame_index:02d}", fill=(235, 235, 235, 255), font=label)
    draw.text((target.width + 12, 8), f"semantic mesh frame {frame_index:02d}", fill=(235, 235, 235, 255), font=label)
    canvas.convert("RGB").save(out_path, format="PNG")


def _write_gif(frames: list[Path], out_path: Path, frame_ms: int) -> None:
    images = [Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE, colors=255) for path in frames]
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        duration=int(frame_ms),
        loop=0,
        optimize=False,
        disposal=2,
    )


def _write_mp4(frames: list[Path], out_path: Path, *, video_fps: int, frame_ms: int) -> None:
    ffmpeg = _find_ffmpeg()
    # Repeat frames to preserve the GIF's wall-clock timing at an exact output FPS.
    repeats = max(1, round(video_fps * frame_ms / 1000.0))
    list_path = out_path.with_suffix(".frames.txt")
    lines = []
    for source in frames:
        escaped = str(source.resolve()).replace("'", "'\\''")
        lines.extend(f"file '{escaped}'\n" for _ in range(repeats))
    list_path.write_text("".join(lines), encoding="utf-8")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-r",
                str(video_fps),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--frame-ms", type=int, default=180)
    parser.add_argument("--video-fps", type=int, default=60)
    args = parser.parse_args()

    targets = {_frame_index(path): path for path in args.targets.glob("*.png")}
    meshes = {int(path.stem.split("_")[-1]): path for path in args.mesh.glob("frame_*.png")}
    indices = sorted(set(targets) & set(meshes))
    if not indices:
        raise RuntimeError(f"No matching target/mesh frames: {args.targets} / {args.mesh}")
    if args.report is not None:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not report.get("semanticOnly") or report.get("semanticModel") != SEMANTIC_MODEL:
            raise RuntimeError(
                "Refusing legacy/non-semantic report; expected semanticOnly=true "
                f"and semanticModel={SEMANTIC_MODEL!r}"
            )
        report_frames = {int(row["frame"]) for row in report.get("frames", [])}
        missing = sorted(set(indices) - report_frames)
        if missing:
            raise RuntimeError(f"Report is missing rendered frames: {missing}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pair_dir = args.out_dir / "side_by_side_frames"
    pair_dir.mkdir(parents=True, exist_ok=True)
    pair_paths = []
    for index in indices:
        path = pair_dir / f"frame_{index:02d}.png"
        compose_pair(targets[index], meshes[index], path, frame_index=index)
        pair_paths.append(path)

    gif_path = args.out_dir / "roc_semantic_side_by_side.gif"
    mp4_path = args.out_dir / "roc_semantic_side_by_side_60fps.mp4"
    _write_gif(pair_paths, gif_path, args.frame_ms)
    _write_mp4(pair_paths, mp4_path, video_fps=args.video_fps, frame_ms=args.frame_ms)
    summary = {
        "frames": len(indices),
        "firstFrame": indices[0],
        "lastFrame": indices[-1],
        "frameMs": args.frame_ms,
        "videoFps": args.video_fps,
        "gif": str(gif_path),
        "mp4": str(mp4_path),
    }
    (args.out_dir / "delivery_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
