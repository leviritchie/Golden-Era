#!/usr/bin/env python3
"""Transcode + register HoMM3 RoE Castle campaign clips for Olden BhVideoPlayer.

Supports hub strips (Cgood1 / Cgood2) and per-mission clips (Good1a–c, Good2a–d).

For finished mission cutscenes (looped video + CD narration + softsubs), use
`tools/bake_roe_castle_campaign_videos.py --all-missions` instead of plain
`--transcode` (which only letterboxes the short OGV and must not be treated as
a composed cutscene).

Fail-closed:
  - HD Edition source .ogv must exist (or an existing MP4 that already meets canvas).
  - Output MP4 must be >=1280x720 (target canvas 2560x1080 matching Campaign_Intro).
  - Raw ~200x116 encodes are rejected: they flash as a fraction of the screen.

Does not invent silent success when assets are missing or undersized.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from campaign_video_clip import (  # noqa: E402
    TARGET_HEIGHT,
    TARGET_WIDTH,
    mp4_meets_native_canvas,
    probe_mp4,
    resolve_ffmpeg,
    transcode_ogv_to_native_canvas_mp4,
)

DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
DEFAULT_HD_VIDEO_DIR = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic III - HD Edition\data\VIDEO"
)
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
CLIPS_MEMBER = "DB/clips_info.json"
VIDEO_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "video"

# Hub intros + per-mission RoE Castle / remaining-arc clips.
KNOWN_CLIP_KEYS: tuple[str, ...] = (
    "Cgood1",
    "Good1a",
    "Good1b",
    "Good1c",
    "Cgood2",
    "Good2a",
    "Good2b",
    "Good2c",
    "Good2d",
    "Cgood3",
    "Good3a",
    "Good3b",
    "Good3c",
    "Cevil1",
    "Evil1a",
    "Evil1b",
    "Evil1c",
    "Cevil2",
    "Evil2a",
    "Evil2b",
    "Evil2c",
    "Evil2d",
    "Csecret",
    "SecretA",
    "SecretB",
    "SecretC",
    "Cneutral",
    "NeutralA",
    "NeutralB",
    "NeutralC",
)


def fail(message: str) -> None:
    raise SystemExit(f"roe castle campaign video clip register failed: {message}")


def clip_row(clip_key: str) -> dict[str, Any]:
    return {
        "key": clip_key,
        "val": {
            "name": f"{clip_key}.mp4",
            "canSkip": True,
            "haveSubtitles": False,
            "skipByHoldingEsc": True,
            "playVideoShowAnimation": False,
        },
    }


def resolve_clip_keys(raw: list[str] | None, *, all_roe_castle: bool) -> list[str]:
    if all_roe_castle:
        return list(KNOWN_CLIP_KEYS)
    if not raw:
        fail(
            "pass --clip KEY (repeatable), --clips a,b,c, or --all-roe-castle; "
            f"known keys: {', '.join(KNOWN_CLIP_KEYS)}"
        )
    keys: list[str] = []
    for item in raw:
        for part in str(item).split(","):
            key = part.strip()
            if not key:
                continue
            if key not in KNOWN_CLIP_KEYS:
                fail(f"unknown clip key {key!r}; known: {', '.join(KNOWN_CLIP_KEYS)}")
            if key not in keys:
                keys.append(key)
    if not keys:
        fail("no clip keys resolved")
    return keys


def upsert_clips_info(core_zip: Path, clip_keys: list[str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = core_zip.with_name(core_zip.name + f".roe_clips_backup_{stamp}")
    if backup.exists():
        fail(f"backup already exists: {backup}")

    temp_dir = Path(tempfile.mkdtemp(prefix="roe_clips_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source:
            clips = json.loads(source.read(CLIPS_MEMBER).decode("utf-8-sig"))
            rows = clips.get("array", {}).get("data")
            if not isinstance(rows, list):
                rows = clips.get("array")
            if not isinstance(rows, list):
                fail(f"{CLIPS_MEMBER} missing array/data list; got keys={list(clips.keys())}")
            by_key = {
                row.get("key"): row
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("key"), str)
            }
            for clip_key in clip_keys:
                desired = clip_row(clip_key)
                if clip_key in by_key:
                    by_key[clip_key]["val"] = dict(desired["val"])
                else:
                    rows.append(dict(desired))
                    by_key[clip_key] = rows[-1]
            if "array" in clips and isinstance(clips["array"], dict):
                clips["array"]["data"] = rows
            else:
                clips["array"] = rows
            payload = (json.dumps(clips, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            with zipfile.ZipFile(temp_zip, "w") as target:
                for info in source.infolist():
                    data = payload if info.filename == CLIPS_MEMBER else source.read(info.filename)
                    replacement = zipfile.ZipInfo(info.filename, info.date_time)
                    replacement.comment = info.comment
                    replacement.extra = info.extra
                    replacement.internal_attr = info.internal_attr
                    replacement.external_attr = info.external_attr
                    replacement.compress_type = info.compress_type
                    target.writestr(replacement, data)
        shutil.copy2(core_zip, backup)
        shutil.copy2(temp_zip, core_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return backup


def ensure_mp4(
    *,
    clip_key: str,
    game_root: Path,
    hd_video_dir: Path,
    source_ogv: Path | None,
    transcode: bool,
) -> dict[str, Any]:
    mp4 = game_root / VIDEO_REL / f"{clip_key}.mp4"
    ogv = source_ogv if source_ogv is not None else (hd_video_dir / f"{clip_key}.ogv")

    if transcode:
        try:
            resolve_ffmpeg()
        except FileNotFoundError as exc:
            fail(str(exc))
        if not ogv.is_file():
            fail(f"missing source OGV for {clip_key}: {ogv}")
        try:
            report = transcode_ogv_to_native_canvas_mp4(source_ogv=ogv.resolve(), dest_mp4=mp4)
        except Exception as exc:
            fail(f"{clip_key}: {exc}")
        print(
            f"transcoded {ogv} -> {mp4} "
            f"{report.get('width')}x{report.get('height')} "
            f"duration={report.get('duration_sec')}s"
        )
        return report

    if not mp4.is_file():
        fail(
            f"missing {mp4}; pass --transcode to build from HD Edition {clip_key}.ogv "
            f"({TARGET_WIDTH}x{TARGET_HEIGHT} letterboxed), or place a valid MP4 first"
        )
    probe = probe_mp4(mp4)
    ok, reason = mp4_meets_native_canvas(probe)
    if not ok:
        fail(
            f"{mp4} rejected: {reason}. Re-run with --transcode "
            f"(target canvas {TARGET_WIDTH}x{TARGET_HEIGHT})."
        )
    print(
        f"validated existing {mp4} {probe.get('width')}x{probe.get('height')} "
        f"duration={probe.get('duration_sec')}s"
    )
    return probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--hd-video-dir", type=Path, default=DEFAULT_HD_VIDEO_DIR)
    parser.add_argument(
        "--clip",
        action="append",
        dest="clips",
        default=None,
        help="Clip key to process (repeatable). Known: " + ", ".join(KNOWN_CLIP_KEYS),
    )
    parser.add_argument(
        "--clips",
        dest="clips_csv",
        default=None,
        help="Comma-separated clip keys (alias for repeated --clip)",
    )
    parser.add_argument(
        "--all-roe-castle",
        action="store_true",
        help="Process all known RoE Castle Good1/Good2 hub + mission clips",
    )
    parser.add_argument(
        "--source-ogv",
        type=Path,
        default=None,
        help="Override OGV path (only valid when exactly one --clip is selected)",
    )
    parser.add_argument(
        "--transcode",
        action="store_true",
        help=f"Transcode source OGV to {TARGET_WIDTH}x{TARGET_HEIGHT} letterboxed H.264+AAC MP4",
    )
    parser.add_argument(
        "--register-clips-info",
        action="store_true",
        default=True,
        help="Upsert DB/clips_info.json rows in Core.zip (default: on)",
    )
    parser.add_argument(
        "--skip-register-clips-info",
        action="store_true",
        help="Only ensure/validate MP4; do not rewrite Core.zip",
    )
    args = parser.parse_args()
    game_root = args.game_root.resolve()
    hd_video_dir = args.hd_video_dir.resolve()
    raw_keys: list[str] = []
    if args.clips:
        raw_keys.extend(args.clips)
    if args.clips_csv:
        raw_keys.append(args.clips_csv)
    clip_keys = resolve_clip_keys(raw_keys or None, all_roe_castle=bool(args.all_roe_castle))
    if args.source_ogv is not None and len(clip_keys) != 1:
        fail("--source-ogv requires exactly one --clip")

    do_register = bool(args.register_clips_info) and not bool(args.skip_register_clips_info)
    for clip_key in clip_keys:
        report = ensure_mp4(
            clip_key=clip_key,
            game_root=game_root,
            hd_video_dir=hd_video_dir,
            source_ogv=args.source_ogv,
            transcode=bool(args.transcode),
        )
        probe = probe_mp4(game_root / VIDEO_REL / f"{clip_key}.mp4")
        ok, reason = mp4_meets_native_canvas(probe)
        if not ok:
            fail(f"post-condition failed for {clip_key}: {reason}")
        _ = report

    if do_register:
        core_zip = game_root / CORE_ZIP_REL
        if not core_zip.is_file():
            fail(f"missing Core.zip: {core_zip}")
        backup = upsert_clips_info(core_zip, clip_keys)
        print(
            f"registered {len(clip_keys)} clip(s) in {CLIPS_MEMBER}: "
            f"{', '.join(clip_keys)} backup={backup}"
        )
    else:
        print(f"skipped clips_info Core.zip rewrite; MP4s ready under {game_root / VIDEO_REL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
