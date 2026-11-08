#!/usr/bin/env python3
"""RIFE dual-stream map billboard previews @ 50 FPS (adventure-map DEF cycles).

Reads HoMM3 adventure-map creature DEF extracts (extracted_map/, group 0 cycle).
Outputs WebM VP9+alpha for browser review — same contract as battle comparison but
native map flip-book is ~10 FPS and target preview is 50 FPS (5×) with rife-v4.6
dual-stream alpha (gray-plate RGB + separate alpha-mask RIFE).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from homm3_rife_core import (
    DEFAULT_RIFE_EXE,
    configure_fps,
    interpolate_rgba_sequence_dual_stream,
    normalize_frames,
    target_frame_count,
    v_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
UNITY_LAB = REPO_ROOT / "oldenera_factions/Assets/CustomUnits/homm3_lab"
OFFLINE_LAB = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
WORK_ROOT = TOOLS / ".cache/vfi-work-map50"
WEBM_STAGE_ROOT = TOOLS / ".cache/vfi-webm-frames-map50"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_map_animation_ai_interpolation_comparison"

MAP_SOURCE_FPS = 10
MAP_TARGET_FPS = 50
RIFE_MODEL = "rife-v4.6"

GROUP_IDLE = 2
GROUP_MOVEMENT = 0

UNITS = (
    ("toa_goblin_trapper", "Stronghold Goblin Trapper (h3_goblin_upg_alt)"),
    ("h3_gremlin", "Tower Gremlin"),
    ("h3_hobgoblin", "Stronghold Hobgoblin"),
    ("h3_harpy", "Dungeon Harpy"),
    ("h3_bone_dragon", "Necropolis Bone Dragon"),
)

# Map billboards use the adventure-map walk/idle cycle (group 0 when idle is absent).
CLIPS = (("map_cycle", GROUP_IDLE, GROUP_MOVEMENT),)


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def resolve_map_dir(unit_sid: str) -> Path:
    for root in (OFFLINE_LAB, UNITY_LAB):
        candidate = root / unit_sid / "extracted_map"
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    raise FileNotFoundError(
        f"No extracted_map for {unit_sid} under OfflineUnlockMod or oldenera_factions homm3_lab"
    )


def load_map_manifest(map_dir: Path) -> tuple[Path, dict]:
    json_files = sorted(
        p
        for p in map_dir.glob("*.json")
        if not p.name.startswith(".") and p.name.lower() != "manifest.json"
    )
    if not json_files:
        raise FileNotFoundError(map_dir)
    path = json_files[0]
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def group_frame_paths(manifest: dict, group_id: int) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) != group_id:
            continue
        return [str(f).strip() for f in (sequence.get("frames") or []) if str(f or "").strip()]
    return []


def resolve_frame_path(map_dir: Path, rel: str) -> Path:
    rel_norm = rel.replace("\\", "/")
    direct = map_dir / rel_norm
    if direct.is_file():
        return direct
    parts = rel_norm.split("/")
    if len(parts) != 2:
        return direct
    dir_name, file_name = parts
    dir_path = map_dir / dir_name
    if not dir_path.is_dir():
        for child in map_dir.iterdir():
            if child.is_dir() and child.name.lower() == dir_name.lower():
                dir_path = child
                break
    candidate = dir_path / file_name
    if candidate.is_file():
        return candidate
    if dir_path.is_dir():
        for png in dir_path.glob("*.png"):
            if png.name.lower() == file_name.lower():
                return png
    return direct


def load_group_frames(map_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for rel in rel_paths:
        path = resolve_frame_path(map_dir, rel)
        if not path.is_file():
            raise FileNotFoundError(path)
        frames.append(Image.open(path).convert("RGBA"))
    return frames


def pick_map_cycle_frames(manifest: dict, map_dir: Path) -> tuple[list[Image.Image], str]:
    for clip_name, prefer_group, fallback_group in CLIPS:
        for group_id in (prefer_group, fallback_group):
            rel = group_frame_paths(manifest, group_id)
            if rel:
                frames = normalize_frames(load_group_frames(map_dir, rel))
                label = (
                    f"Adventure-map DEF group {group_id}: {len(frames)} native frames "
                    f"@ {MAP_SOURCE_FPS} FPS (in-game mapFlipBookFps)"
                )
                return frames, label
    raise ValueError("no map animation groups in manifest")


def baseline_hold_frames(frames: list[Image.Image], hold: int) -> list[Image.Image]:
    held: list[Image.Image] = []
    for frame in frames:
        held.extend([frame] * hold)
    return held


def even_rgba(frame: Image.Image) -> Image.Image:
    rgba = frame.convert("RGBA")
    w, h = rgba.size
    ew, eh = w + (w % 2), h + (h % 2)
    if (ew, eh) == (w, h):
        return rgba
    canvas = Image.new("RGBA", (ew, eh), (0, 0, 0, 0))
    canvas.paste(rgba, (0, 0), rgba)
    return canvas


def write_webm(path: Path, frames: list[Image.Image], fps: float) -> None:
    if not frames:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = WEBM_STAGE_ROOT / path.stem
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for i, frame in enumerate(frames):
        even_rgba(frame).save(staging / f"{i:08d}.png")

    ffmpeg = resolve_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        f"{fps:.6f}",
        "-i",
        str(staging / "%08d.png"),
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-auto-alt-ref",
        "0",
        "-crf",
        "28",
        "-b:v",
        "0",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, env=v_env())
    shutil.rmtree(staging, ignore_errors=True)


def write_index(out_dir: Path, unit_notes: dict[str, str]) -> None:
    hold = MAP_TARGET_FPS // MAP_SOURCE_FPS
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HoMM3 map billboard RIFE @ {MAP_TARGET_FPS} FPS</title>
<style>
body{{font-family:system-ui,sans-serif;background:#fff;color:#111;margin:1.5rem;max-width:1200px}}
h1,h2,h3{{color:#000}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #ccc;padding:.5rem;vertical-align:top}}
th{{background:#f0f0f0;width:28%}}
video{{max-width:420px;max-height:480px;background:#fff;border:1px solid #999;display:block}}
.note{{color:#444;font-size:.9rem;line-height:1.45}}
a{{color:#06c}} code{{color:#06c;background:#f5f5f5;padding:.1em .25em;border-radius:3px}}
</style></head><body>
<h1>HoMM3 map billboard — dual-stream RIFE @ {MAP_TARGET_FPS} FPS</h1>
<p class="note">Adventure-map creature DEF cycles (<code>extracted_map</code>; prefers DEF idle group 2, else movement group 0).
Native in-game map flip-book is <strong>{MAP_SOURCE_FPS} FPS</strong>; previews target <strong>{MAP_TARGET_FPS} FPS</strong>
({hold}×). Dual-stream row uses <strong>rife-v4.6</strong>: gray-plate RGB RIFE plus a separate RIFE pass on the alpha mask
(same method as production <code>HOMM3_DUAL_STREAM_ALPHA</code>). White background to expose halos.</p>
<p class="note"><strong>Rows:</strong> <code>01_*</code> = native DEF @ {MAP_SOURCE_FPS} FPS;
<code>01b_*</code> = each native frame held {hold}× @ {MAP_TARGET_FPS} FPS (no AI);
<code>04_rife_dual_stream_{MAP_TARGET_FPS}fps</code> = dual-stream RIFE v4.6 @ {MAP_TARGET_FPS} FPS.</p>
<p class="note">Battle sprite comparison:
<a href="../homm3_animation_ai_interpolation_comparison/index.html">battle RIFE gallery</a>.</p>
"""
    for unit_sid, display in UNITS:
        html += f"<h2>{display} (<code>{unit_sid}</code>)</h2>"
        if unit_sid in unit_notes:
            html += f"<p class='note'>{unit_notes[unit_sid]}</p>"
        clip_dir = out_dir / unit_sid / "map_cycle"
        if not clip_dir.is_dir():
            continue
        html += "<h3>map_cycle</h3><table><tr><th>Method</th><th>Preview</th></tr>"
        for webm in sorted(clip_dir.glob("*.webm")):
            rel = webm.relative_to(out_dir).as_posix()
            txt = webm.with_suffix(".txt")
            label = txt.read_text(encoding="utf-8") if txt.is_file() else webm.stem
            html += (
                f"<tr><td><strong>{webm.stem}</strong><br>{label}</td>"
                f"<td><video src='{rel}' autoplay loop muted playsinline></video></td></tr>"
            )
        html += "</table>"
    html += "</body></html>"
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def process_unit(
    unit_sid: str,
    display: str,
    out_dir: Path,
    *,
    encode_only: bool,
    rife_exe: Path,
) -> str:
    map_dir = resolve_map_dir(unit_sid)
    _manifest_path, manifest = load_map_manifest(map_dir)
    native_frames, native_label = pick_map_cycle_frames(manifest, map_dir)
    native_count = len(native_frames)
    hold = MAP_TARGET_FPS // MAP_SOURCE_FPS
    target_n = target_frame_count(native_count)
    clip_out = out_dir / unit_sid / "map_cycle"
    if clip_out.exists():
        for stale in clip_out.glob("*"):
            if stale.is_file():
                stale.unlink()
    clip_out.mkdir(parents=True, exist_ok=True)

    work_dir = WORK_ROOT / unit_sid / "map_cycle"

    print(f"  native frames: {native_count} -> target {target_n} @ {MAP_TARGET_FPS} FPS")
    write_webm(clip_out / f"01_baseline_{MAP_SOURCE_FPS}fps.webm", native_frames, float(MAP_SOURCE_FPS))
    (clip_out / f"01_baseline_{MAP_SOURCE_FPS}fps.txt").write_text(
        f"{native_label} (no AI in-betweens)", encoding="utf-8"
    )

    hold_stem = f"01b_baseline_{MAP_TARGET_FPS}fps_hold"
    write_webm(
        clip_out / f"{hold_stem}.webm",
        baseline_hold_frames(native_frames, hold),
        float(MAP_TARGET_FPS),
    )
    (clip_out / f"{hold_stem}.txt").write_text(
        f"Each native frame held {hold}× @ {MAP_TARGET_FPS} FPS (no AI in-betweens)",
        encoding="utf-8",
    )

    dual_stem = f"04_rife_dual_stream_{MAP_TARGET_FPS}fps"
    dual_desc = (
        "Dual-stream RIFE v4.6: gray-plate RGB + separate alpha-mask RIFE "
        f"({target_n} frames @ {MAP_TARGET_FPS} FPS VP9+alpha)"
    )
    if encode_only:
        seq = interpolate_rgba_sequence_dual_stream(
            native_frames,
            rife_exe=rife_exe,
            work_dir=work_dir,
            model_name=RIFE_MODEL,
            reuse_cache=True,
        )
    else:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        print(f"  RIFE dual-stream ({unit_sid})...")
        seq = interpolate_rgba_sequence_dual_stream(
            native_frames,
            rife_exe=rife_exe,
            work_dir=work_dir,
            model_name=RIFE_MODEL,
            reuse_cache=False,
        )
    if not seq:
        print(f"    FAIL: empty dual-stream sequence for {unit_sid}")
        return f"Source: <code>{map_dir.relative_to(REPO_ROOT).as_posix()}</code>. Dual-stream RIFE failed."
    print(f"  WebM {dual_stem} ({len(seq)} frames)...")
    write_webm(clip_out / f"{dual_stem}.webm", seq, float(MAP_TARGET_FPS))
    (clip_out / f"{dual_stem}.txt").write_text(dual_desc, encoding="utf-8")

    rel_map = map_dir.relative_to(REPO_ROOT).as_posix()
    return (
        f"Map frames from <code>{rel_map}</code> — {native_count} native DEF frames, "
        f"dual-stream target {len(seq)} @ {MAP_TARGET_FPS} FPS."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--units",
        nargs="*",
        default=[u[0] for u in UNITS],
        help="Unit SIDs (default: hobgoblin, harpy, bone dragon)",
    )
    parser.add_argument("--source-fps", type=int, default=10)
    parser.add_argument("--target-fps", type=int, default=50)
    parser.add_argument(
        "--encode-only",
        action="store_true",
        help="Skip RIFE; encode WebM from cached tools/.cache/vfi-work-map50 PNGs",
    )
    args = parser.parse_args()

    global MAP_SOURCE_FPS, MAP_TARGET_FPS  # noqa: PLW0603
    MAP_SOURCE_FPS, MAP_TARGET_FPS, _ = configure_fps(args.source_fps, args.target_fps)

    rife_exe = DEFAULT_RIFE_EXE
    if not args.encode_only and not rife_exe.is_file():
        print("Run setup first: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    try:
        resolve_ffmpeg()
    except FileNotFoundError as ex:
        print(ex, file=sys.stderr)
        return 1

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    unit_notes: dict[str, str] = {}
    catalog = {u[0]: u[1] for u in UNITS}

    for unit_sid in args.units:
        display = catalog.get(unit_sid, unit_sid)
        print(f"{display} ({unit_sid})")
        try:
            unit_notes[unit_sid] = process_unit(
                unit_sid,
                display,
                out_dir,
                encode_only=args.encode_only,
                rife_exe=rife_exe,
            )
        except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as ex:
            print(f"  FAIL: {ex}")
            unit_notes[unit_sid] = f"<strong>Error:</strong> {ex}"

    write_index(out_dir, unit_notes)
    readme = f"""# HoMM3 map billboard RIFE @ {MAP_TARGET_FPS} FPS

Open **index.html** in a browser. Previews use **WebM VP9 + alpha** at **{MAP_TARGET_FPS} FPS**
from adventure-map DEF cycles (`extracted_map/`, native **{MAP_SOURCE_FPS} FPS** in-game).

## Regenerate

```bash
bash tools/homm3_import/setup_vfi_env.sh
tools/.venv-homm3-vfi/Scripts/python.exe -m pip install imageio-ffmpeg
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_map_animation_ai_interpolation_comparison.py
```

Re-encode only (dual-stream PNG caches under `tools/.cache/vfi-work-map50/`):

```bash
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_map_animation_ai_interpolation_comparison.py --encode-only
```

## Methods

- **01_baseline_{MAP_SOURCE_FPS}fps.webm** — native adventure-map DEF cycle
- **01b_baseline_{MAP_TARGET_FPS}fps_hold.webm** — each native frame held {MAP_TARGET_FPS // MAP_SOURCE_FPS}× @ {MAP_TARGET_FPS} FPS
- **04_rife_dual_stream_{MAP_TARGET_FPS}fps.webm** — dual-stream RIFE v4.6 (production-style alpha pass)
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Done: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
