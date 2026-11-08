#!/usr/bin/env python3
"""Combine NVIDIA MP4 captures: trim, 1080p, title cards, transitions, HoMM3 music."""

from __future__ import annotations

import argparse
import glob
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

DEFAULT_INPUT = Path.home() / "Videos" / "NVIDIA" / "Heroes Of Might And Magic Olden Era - Golden Era"
DEFAULT_MUSIC = (
    Path(__file__).resolve().parent.parent / "HoMM 3 Complete" / "Mp3" / "COMBAT02.MP3"
)
FONT_FILE = Path(r"C:\Windows\Fonts\arialbd.ttf")
FPS = 30
TITLE_DURATION = 2.5
TRANSITION_DURATION = 0.75
TITLE_TO_CONTENT_TRANSITIONS = ("fadeblack", "circleopen", "wipeleft", "smoothleft")
SECTION_TRANSITIONS = ("wiperight", "fade", "smoothdown", "diagtl")
OUTRO_DURATION = 12.0
OUTRO_HEADER = "Golden Era Mod - Download Link in Comments"
OUTRO_FEATURES = (
    "HoMM3-inspired custom factions (Castle, Rampart, Tower, Inferno, and more)",
    "Custom creatures, town screens, buildings, and heroes",
    "HoMM3 battle animations and combat music",
    "Authentic hero specializations and skill icons",
    "Optional upscaled hero portraits",
    "HoMM3 hero sprites on the adventure map",
    "Custom native terrain biomes",
    "Separate install — your Steam Olden Era copy stays vanilla",
)


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def overlay_label(path: Path) -> str:
    name = path.name
    for ext in (".mp4", ".gif", ".mkv", ".mov"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return path.stem


def newest_mp4s(folder: Path, count: int) -> list[Path]:
    skip_prefixes = ("combined_recent_",)
    paths = [
        Path(p)
        for p in glob.glob(str(folder / "*.mp4"))
        if not Path(p).name.lower().startswith(skip_prefixes)
    ]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[:count]


def probe_duration_seconds(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        raise RuntimeError(f"Could not read duration for {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def escape_ffmpeg_path(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    return resolved.replace(":", r"\:")


def run_ffmpeg(ffmpeg: str, args: list[str], *, context: str) -> None:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({context}):\n{proc.stderr[-4000:]}")


def encode_args(crf: int) -> list[str]:
    return [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
    ]


def write_text_file(content: str, *, suffix: str = ".txt") -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=suffix,
        delete=False,
    )
    handle.write(content)
    handle.close()
    return Path(handle.name)


def on_video_overlay_filter(font: str, textfile: str) -> str:
    return (
        f"drawtext=fontfile='{font}':textfile='{textfile}':reload=1:"
        f"fontsize=52:fontcolor=white:x=(w-text_w)/2:y=50:"
        f"box=1:boxcolor=black@0.67:boxborderw=20"
    )


def render_title_card(
    ffmpeg: str,
    label: str,
    output: Path,
    *,
    duration: float,
    crf: int,
) -> None:
    text_path = write_text_file(label)
    try:
        font = escape_ffmpeg_path(FONT_FILE)
        textfile = escape_ffmpeg_path(text_path)
        fade_out_start = max(0.0, duration - 0.55)
        vf = (
            f"drawtext=fontfile='{font}':textfile='{textfile}':reload=1:"
            f"fontsize=72:fontcolor=white:borderw=3:bordercolor=0x33333388:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.55:boxborderw=28,"
            f"fade=t=in:st=0:d=0.85:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d=0.55:alpha=1"
        )
        run_ffmpeg(
            ffmpeg,
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0c1018:s=1920x1080:d={duration}:r={FPS}",
                "-vf",
                vf,
                *encode_args(crf),
                str(output),
            ],
            context=f"title card '{label}'",
        )
    finally:
        text_path.unlink(missing_ok=True)


def process_clip(
    ffmpeg: str,
    source: Path,
    label: str,
    output: Path,
    *,
    trim_start: float,
    trim_end: float,
    crf: int,
) -> float:
    duration = probe_duration_seconds(ffmpeg, source)
    end_time = duration - trim_end
    if end_time <= trim_start:
        raise ValueError(
            f"{source.name}: duration {duration:.2f}s is too short to trim "
            f"{trim_start}s from start and {trim_end}s from end"
        )
    kept = end_time - trim_start

    text_path = write_text_file(label)
    try:
        font = escape_ffmpeg_path(FONT_FILE)
        textfile = escape_ffmpeg_path(text_path)
        vf = (
            f"trim=start={trim_start}:end={end_time},setpts=PTS-STARTPTS,"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            f"{on_video_overlay_filter(font, textfile)}"
        )
        run_ffmpeg(
            ffmpeg,
            ["-i", str(source), "-vf", vf, *encode_args(crf), str(output)],
            context=f"clip {source.name}",
        )
    finally:
        text_path.unlink(missing_ok=True)
    return kept


def render_outro_card(
    ffmpeg: str,
    output: Path,
    *,
    duration: float,
    crf: int,
    scroll_speed: float = 48.0,
) -> None:
    header_path = write_text_file(OUTRO_HEADER)
    features_path = write_text_file("\n".join(f"- {line}" for line in OUTRO_FEATURES))
    try:
        font = escape_ffmpeg_path(FONT_FILE)
        header_file = escape_ffmpeg_path(header_path)
        features_file = escape_ffmpeg_path(features_path)
        fade_out_start = max(0.0, duration - 0.85)
        vf = (
            f"drawtext=fontfile='{font}':textfile='{header_file}':reload=1:"
            f"fontsize=54:fontcolor=white:borderw=2:bordercolor=0x444444aa:"
            f"x=(w-text_w)/2:y=120:"
            f"box=1:boxcolor=black@0.6:boxborderw=22,"
            f"drawtext=fontfile='{font}':textfile='{features_file}':reload=1:"
            f"fontsize=40:fontcolor=0xE6E6E6:line_spacing=14:"
            f"x=(w-text_w)/2:y=h-300-t*{scroll_speed},"
            f"fade=t=in:st=0:d=0.9:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d=0.85:alpha=1"
        )
        run_ffmpeg(
            ffmpeg,
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0c1018:s=1920x1080:d={duration}:r={FPS}",
                "-vf",
                vf,
                *encode_args(crf),
                str(output),
            ],
            context="outro card",
        )
    finally:
        header_path.unlink(missing_ok=True)
        features_path.unlink(missing_ok=True)


def link_with_xfade(
    ffmpeg: str,
    first: Path,
    second: Path,
    output: Path,
    transition: str,
    *,
    duration: float,
    crf: int,
) -> None:
    first_dur = probe_duration_seconds(ffmpeg, first)
    if first_dur <= duration:
        raise ValueError(
            f"Cannot xfade: first segment ({first_dur:.2f}s) is shorter than "
            f"transition ({duration:.2f}s)"
        )
    offset = first_dur - duration
    filter_complex = (
        f"[0:v][1:v]xfade=transition={transition}:duration={duration}:offset={offset:.3f}[v]"
    )
    run_ffmpeg(
        ffmpeg,
        [
            "-i",
            str(first),
            "-i",
            str(second),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            *encode_args(crf),
            str(output),
        ],
        context=f"xfade {transition} ({first.name} -> {second.name})",
    )


def add_background_music(
    ffmpeg: str,
    video: Path,
    music: Path,
    output: Path,
    *,
    volume: float,
) -> None:
    duration = probe_duration_seconds(ffmpeg, video)
    fade_out_start = max(0.0, duration - 2.5)
    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2e+09,atrim=duration={duration:.3f},"
        f"volume={volume},"
        f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_start:.3f}:d=2.5[music]"
    )
    run_ffmpeg(
        ffmpeg,
        [
            "-i",
            str(video),
            "-i",
            str(music),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[music]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ],
        context="background music mux",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--trim-start", type=float, default=2.0)
    parser.add_argument("--trim-end", type=float, default=2.0)
    parser.add_argument("--title-duration", type=float, default=TITLE_DURATION)
    parser.add_argument("--transition-duration", type=float, default=TRANSITION_DURATION)
    parser.add_argument("--crf", type=int, default=18, help="H.264 quality (lower=better)")
    parser.add_argument(
        "--music",
        type=Path,
        default=DEFAULT_MUSIC,
        help="Background track (default: HoMM3 COMBAT02.MP3)",
    )
    parser.add_argument("--music-volume", type=float, default=0.32)
    parser.add_argument("--outro-duration", type=float, default=OUTRO_DURATION)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Default: Downloads/combined_recent_clips.mp4",
    )
    args = parser.parse_args()

    if not FONT_FILE.is_file():
        raise SystemExit(f"Font not found: {FONT_FILE}")
    if not args.music.is_file():
        raise SystemExit(f"Music not found: {args.music}")

    clips = newest_mp4s(args.input_dir, args.count)
    if len(clips) < args.count:
        raise SystemExit(f"Found only {len(clips)} MP4(s) in {args.input_dir}")

    clips = list(reversed(clips))
    ffmpeg = ffmpeg_exe()
    output = args.output or (Path.home() / "Downloads" / "combined_recent_clips.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="combine_nvidia_") as tmp:
        tmp_dir = Path(tmp)
        sections: list[Path] = []

        print(f"Processing {len(clips)} clip(s) -> {output}")
        for index, source in enumerate(clips):
            label = overlay_label(source)
            title_path = tmp_dir / f"title_{index:02d}.mp4"
            content_path = tmp_dir / f"content_{index:02d}.mp4"
            section_path = tmp_dir / f"section_{index:02d}.mp4"

            render_title_card(
                ffmpeg,
                label,
                title_path,
                duration=args.title_duration,
                crf=args.crf,
            )
            kept = process_clip(
                ffmpeg,
                source,
                label,
                content_path,
                trim_start=args.trim_start,
                trim_end=args.trim_end,
                crf=args.crf,
            )
            title_transition = TITLE_TO_CONTENT_TRANSITIONS[
                index % len(TITLE_TO_CONTENT_TRANSITIONS)
            ]
            link_with_xfade(
                ffmpeg,
                title_path,
                content_path,
                section_path,
                title_transition,
                duration=args.transition_duration,
                crf=args.crf,
            )
            sections.append(section_path)
            print(
                f"  [{index + 1}/{len(clips)}] {label} "
                f"(title {title_transition}, {kept:.1f}s gameplay)"
            )

        chained = sections[0]
        for index in range(1, len(sections)):
            next_path = tmp_dir / f"chained_{index:02d}.mp4"
            section_transition = SECTION_TRANSITIONS[index % len(SECTION_TRANSITIONS)]
            link_with_xfade(
                ffmpeg,
                chained,
                sections[index],
                next_path,
                section_transition,
                duration=args.transition_duration,
                crf=args.crf,
            )
            chained = next_path
            print(f"  chained section {index + 1} via {section_transition}")

        outro_path = tmp_dir / "outro.mp4"
        render_outro_card(
            ffmpeg,
            outro_path,
            duration=args.outro_duration,
            crf=args.crf,
        )
        with_outro = tmp_dir / "with_outro.mp4"
        link_with_xfade(
            ffmpeg,
            chained,
            outro_path,
            with_outro,
            "fadeblack",
            duration=args.transition_duration,
            crf=args.crf,
        )
        print("  appended outro card (scrolling features)")

        add_background_music(
            ffmpeg,
            with_outro,
            args.music,
            output,
            volume=args.music_volume,
        )

    size_mb = output.stat().st_size / (1024 * 1024)
    final_dur = probe_duration_seconds(ffmpeg, output)
    print(
        f"Wrote {output} ({final_dur:.1f}s, {size_mb:.1f} MB, 1920x1080, "
        f"music={args.music.name})"
    )


if __name__ == "__main__":
    main()
