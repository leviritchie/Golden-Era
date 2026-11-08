"""Shared HoMM3→Olden campaign video clip helpers (probe + transcode).

Native BhVideoPlayer expects Campaign_Intro-class MP4s (≈2560×1080). Raw HD Edition
Cgood*.ogv clips are tiny Theora strips (~200×116); playing them unscaled shows as a
fraction of the screen. Fail closed on undersized encodes instead of wiring PlayVideo.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# Match native Campaign_Intro.mp4 canvas so Camera/VideoPlayer fill behaves like mainStory.
TARGET_WIDTH = 2560
TARGET_HEIGHT = 1080
# Reject leftover 204×116 (or similar) flash encodes.
MIN_ACCEPT_WIDTH = 1280
MIN_ACCEPT_HEIGHT = 720


def probe_mp4_via_ffmpeg(mp4_path: Path, ffmpeg: Path) -> dict[str, Any]:
    """Return width/height/duration_sec/has_audio using ffmpeg -i stderr parse."""
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(mp4_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    width = height = None
    duration_sec = None
    has_audio = False
    for line in text.splitlines():
        if "Video:" in line and "Audio:" not in line:
            # e.g. ... yuv420p(...), 204x116, 68 kb/s ...
            parts = line.replace(",", " ").split()
            for part in parts:
                if "x" in part and part[0].isdigit():
                    try:
                        w_s, h_s = part.split("x", 1)
                        width, height = int(w_s), int(h_s)
                        break
                    except ValueError:
                        continue
        if "Duration:" in line:
            # Duration: 00:00:04.73,
            try:
                stamp = line.split("Duration:", 1)[1].strip().split(",", 1)[0].strip()
                h, m, s = stamp.split(":")
                duration_sec = int(h) * 3600 + int(m) * 60 + float(s)
            except (IndexError, ValueError):
                pass
        if "Audio:" in line:
            has_audio = True
    return {
        "width": width,
        "height": height,
        "duration_sec": duration_sec,
        "has_audio": has_audio,
        "path": str(mp4_path),
        "filesize": mp4_path.stat().st_size if mp4_path.is_file() else 0,
    }


def probe_mp4_tkhd(mp4_path: Path) -> dict[str, Any]:
    """Fallback dimension probe from tkhd fixed-point width/height (no ffmpeg)."""
    data = mp4_path.read_bytes()
    info: dict[str, Any] = {
        "width": None,
        "height": None,
        "duration_sec": None,
        "has_audio": b"mp4a" in data or b"mp3" in data.lower(),
        "path": str(mp4_path),
        "filesize": len(data),
    }
    idx = data.find(b"mvhd")
    if idx >= 0:
        version = data[idx + 4]
        if version == 0:
            timescale = struct.unpack(">I", data[idx + 16 : idx + 20])[0]
            duration = struct.unpack(">I", data[idx + 20 : idx + 24])[0]
        else:
            timescale = struct.unpack(">I", data[idx + 20 : idx + 24])[0]
            duration = struct.unpack(">Q", data[idx + 24 : idx + 32])[0]
        if timescale:
            info["duration_sec"] = duration / timescale
    pos = 0
    while True:
        pos = data.find(b"tkhd", pos + 1)
        if pos < 0:
            break
        version = data[pos + 4]
        body = pos + 8
        if version == 0:
            w = struct.unpack(">I", data[body + 76 : body + 80])[0] / 65536.0
            h = struct.unpack(">I", data[body + 80 : body + 84])[0] / 65536.0
        else:
            w = struct.unpack(">I", data[body + 88 : body + 92])[0] / 65536.0
            h = struct.unpack(">I", data[body + 92 : body + 96])[0] / 65536.0
        if w >= 2 and h >= 2:
            info["width"] = int(round(w))
            info["height"] = int(round(h))
            break
    return info


def resolve_ffmpeg() -> Path:
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if exe.is_file():
            return exe
    except Exception:
        pass
    which = shutil.which("ffmpeg")
    if which:
        return Path(which)
    raise FileNotFoundError(
        "ffmpeg not found (imageio-ffmpeg package or ffmpeg on PATH required)"
    )


def probe_mp4(mp4_path: Path) -> dict[str, Any]:
    if not mp4_path.is_file():
        return {
            "width": None,
            "height": None,
            "duration_sec": None,
            "has_audio": False,
            "path": str(mp4_path),
            "filesize": 0,
            "present": False,
        }
    try:
        probe = probe_mp4_via_ffmpeg(mp4_path, resolve_ffmpeg())
        probe["present"] = True
        probe["probeMethod"] = "ffmpeg"
        if probe.get("width") and probe.get("height"):
            return probe
    except FileNotFoundError:
        pass
    probe = probe_mp4_tkhd(mp4_path)
    probe["present"] = True
    probe["probeMethod"] = "tkhd"
    return probe


def mp4_meets_native_canvas(probe: dict[str, Any]) -> tuple[bool, str]:
    width = probe.get("width")
    height = probe.get("height")
    if not probe.get("present"):
        return False, "mp4 missing"
    if not isinstance(width, int) or not isinstance(height, int):
        return False, f"could not probe dimensions ({probe})"
    if width < MIN_ACCEPT_WIDTH or height < MIN_ACCEPT_HEIGHT:
        return (
            False,
            f"undersized {width}x{height}; need >={MIN_ACCEPT_WIDTH}x{MIN_ACCEPT_HEIGHT} "
            f"(native Campaign_Intro canvas is {TARGET_WIDTH}x{TARGET_HEIGHT}; raw HoMM3 "
            "Cgood strips are ~200x116 and display as a screen fraction)",
        )
    return True, "ok"


def transcode_ogv_to_native_canvas_mp4(
    *,
    source_ogv: Path,
    dest_mp4: Path,
    ffmpeg: Path | None = None,
) -> dict[str, Any]:
    """Scale+pad HoMM3 OGV into Campaign_Intro-sized H.264+AAC MP4 (fail-closed)."""
    ffmpeg = ffmpeg or resolve_ffmpeg()
    if not source_ogv.is_file():
        raise FileNotFoundError(f"missing source OGV: {source_ogv}")
    dest_mp4.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        "fps=30,format=yuv420p"
    )
    with tempfile.TemporaryDirectory(prefix="roe_cgood_transcode_") as tmp:
        tmp_out = Path(tmp) / dest_mp4.name
        # Silent stereo AAC matches clips_info haveSubtitles=false path; Campaign_Intro uses mp3
        # but AAC is universally available via imageio-ffmpeg builds.
        cmd = [
            str(ffmpeg),
            "-y",
            "-i",
            str(source_ogv),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(tmp_out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not tmp_out.is_file():
            raise RuntimeError(
                "ffmpeg transcode failed:\n"
                + (proc.stderr or proc.stdout or "(no output)")
            )
        probe = probe_mp4(tmp_out)
        ok, reason = mp4_meets_native_canvas(probe)
        if not ok:
            raise RuntimeError(f"transcode produced unacceptable MP4: {reason}")
        # Atomic replace into destination.
        backup = None
        if dest_mp4.is_file():
            backup = dest_mp4.with_suffix(dest_mp4.suffix + ".pre_native_canvas_bak")
            if backup.exists():
                backup.unlink()
            shutil.copy2(dest_mp4, backup)
        shutil.copy2(tmp_out, dest_mp4)
    final = probe_mp4(dest_mp4)
    final["sourceOgv"] = str(source_ogv)
    final["targetCanvas"] = f"{TARGET_WIDTH}x{TARGET_HEIGHT}"
    final["backup"] = str(backup) if backup else None
    final["ffmpegCmd"] = cmd
    return final


def write_probe_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
