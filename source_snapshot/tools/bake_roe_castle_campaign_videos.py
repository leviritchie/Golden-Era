#!/usr/bin/env python3
"""Inventory + compose RoE Castle campaign cutscenes from HoMM3 HD Edition sources.

Fail-closed:
  - Mission clips require VIDEO/*.ogv + HEROES3CD.SND narration + H3C prolog text.
  - Hub strips Cgood1/Cgood2 refuse compose (no CD narration).
  - Softsubs preferred (*.mp4.json + cinematic.json LocKit); burn-in is not used.

Does not commit. Does not restore Cgood1 as Good1 hub firstShow.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from campaign_video_clip import (  # noqa: E402
    TARGET_HEIGHT,
    TARGET_WIDTH,
    probe_mp4,
)
from campaign_video_compose import (  # noqa: E402
    COMPOSED_CLIP_RECIPES,
    MISSION_COMPOSE_KEYS,
    assert_recipe_prolog_matches_h3c_transcripts,
    clips_info_row_composed,
    compose_campaign_cutscene_mp4,
    composed_mp4_meets_contract,
    inventory_clip_sources,
    refresh_softsub_text_for_clip,
    upsert_cinematic_lockit_in_core,
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
REPORT_DIR = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_castle_campaign"
    / "campaign_video_bake"
)


def fail(message: str) -> None:
    raise SystemExit(f"roe castle campaign video bake failed: {message}")


def resolve_clip_keys(raw: list[str] | None, *, all_missions: bool, all_known: bool) -> list[str]:
    if all_missions:
        return list(MISSION_COMPOSE_KEYS)
    if all_known:
        return list(COMPOSED_CLIP_RECIPES.keys())
    if not raw:
        fail(
            "pass --clip KEY, --all-missions, or --all-known; "
            f"mission keys: {', '.join(MISSION_COMPOSE_KEYS)}"
        )
    keys: list[str] = []
    for item in raw:
        for part in str(item).split(","):
            key = part.strip()
            if not key:
                continue
            if key not in COMPOSED_CLIP_RECIPES:
                fail(f"unknown clip key {key!r}")
            if key not in keys:
                keys.append(key)
    return keys


def upsert_clips_info_composed(core_zip: Path, clip_keys: list[str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = core_zip.with_name(core_zip.name + f".roe_compose_clips_backup_{stamp}")
    if backup.exists():
        fail(f"backup already exists: {backup}")

    import shutil
    import tempfile

    temp_dir = Path(tempfile.mkdtemp(prefix="roe_compose_clips_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source:
            clips = json.loads(source.read(CLIPS_MEMBER).decode("utf-8-sig"))
            rows = clips.get("array", {}).get("data")
            if not isinstance(rows, list):
                rows = clips.get("array")
            if not isinstance(rows, list):
                fail(f"{CLIPS_MEMBER} missing array/data list")
            by_key = {
                row.get("key"): row
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("key"), str)
            }
            for clip_key in clip_keys:
                desired = clips_info_row_composed(clip_key)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--hd-video-dir", type=Path, default=DEFAULT_HD_VIDEO_DIR)
    parser.add_argument("--narration-snd", type=Path, default=None)
    parser.add_argument("--clip", action="append", dest="clips", default=None)
    parser.add_argument("--all-missions", action="store_true", help="Good1a–c + Good2a–d")
    parser.add_argument(
        "--all-known",
        action="store_true",
        help="Include Cgood1/Cgood2 inventory (compose still fails closed for those)",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Write inventory/decision report only; do not bake or install",
    )
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Bake MP4s + sidecars but do not rewrite Core.zip clips_info/cinematic",
    )
    parser.add_argument(
        "--refresh-softsubs-only",
        action="store_true",
        help=(
            "Rewrite *.mp4.json + cinematic LocKit from H3C prologText using existing "
            "MP4 durations; do not re-encode video"
        ),
    )
    args = parser.parse_args()

    try:
        assert_recipe_prolog_matches_h3c_transcripts()
    except Exception as exc:
        fail(str(exc))

    game_root = args.game_root.resolve()
    hd_video_dir = args.hd_video_dir.resolve()
    clip_keys = resolve_clip_keys(
        args.clips,
        all_missions=bool(args.all_missions),
        all_known=bool(args.all_known),
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    inventories = [
        inventory_clip_sources(
            clip_key=key,
            hd_video_dir=hd_video_dir,
            narration_snd=args.narration_snd,
        )
        for key in clip_keys
    ]
    inventory_path = REPORT_DIR / "campaign_video_source_inventory.v1.json"
    inventory_doc = {
        "schema": "homm3.roe_castle_campaign_video_source_inventory.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetCanvas": f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
        "subtitleMode": "softsub_sidecar_and_lockit",
        "burnIn": False,
        "clips": inventories,
        "decisionLog": [
            {
                "decision": "softsubs_not_burn_in",
                "reason": "Match native Campaign_Intro haveSubtitles + *.mp4.json + cinematic.json",
            },
            {
                "decision": "cgood_hub_strips_not_composed",
                "reason": (
                    "Cgood1/Cgood2 are silent ~5s 200x116 menu strips with no HEROES3CD "
                    "narration; Good1 hub stays selection-still-only; Good2 hub must not "
                    "treat Cgood2 as a finished intro"
                ),
            },
            {
                "decision": "mission_voice_from_heroes3cd",
                "reason": (
                    "HD LOC/EN/HEROES3CD.SND entries G1A–G1C / G2A–G2D are the classic "
                    "prolog voices; OGV-embedded Vorbis is a short bed only"
                ),
            },
            {
                "decision": "prolog_text_from_h3c_not_loose_txt",
                "reason": (
                    "No .txt/.vxt beside VIDEO/; prolog strings live in Good1.h3c / "
                    "Good2.h3c block0"
                ),
            },
        ],
    }
    inventory_path.write_text(json.dumps(inventory_doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote inventory {inventory_path}")

    if args.inventory_only:
        for row in inventories:
            print(
                f"  {row['clipKey']}: composable={row['composable']} "
                f"decision={row['decision']}"
            )
        return 0

    compose_keys = [key for key in clip_keys if COMPOSED_CLIP_RECIPES[key].is_composable]
    refused = [key for key in clip_keys if key not in compose_keys]
    if refused:
        for key in refused:
            inv = next(row for row in inventories if row["clipKey"] == key)
            print(f"REFUSED compose {key}: {inv['decision']}")
        # Fail closed if user asked only for non-composable keys.
        if not compose_keys:
            fail(
                "no composable clips in selection; refused: "
                + ", ".join(refused)
                + ". Use --all-missions for Good1a–c/Good2a–d."
            )

    results: list[dict[str, Any]] = []
    cue_batches: list[list[dict[str, Any]]] = []
    for clip_key in compose_keys:
        dest = game_root / VIDEO_REL / f"{clip_key}.mp4"
        if args.refresh_softsubs_only:
            print(f"refreshing softsubs {clip_key} <- {dest}")
            try:
                report = refresh_softsub_text_for_clip(clip_key=clip_key, mp4_path=dest)
            except Exception as exc:
                fail(str(exc))
            probe = probe_mp4(dest)
            cue_batches.append(report["softsubCues"])
            results.append(
                {
                    "clipKey": clip_key,
                    "mp4": str(dest),
                    "durationSec": probe.get("duration_sec"),
                    "width": probe.get("width"),
                    "height": probe.get("height"),
                    "hasAudio": probe.get("has_audio"),
                    "sidecar": report.get("sidecar"),
                    "subtitleMode": report.get("subtitleMode"),
                    "status": report.get("status"),
                    "prologOpening": (report.get("prologText") or "")[:64],
                }
            )
            print(
                f"  ok softsub refresh duration={probe.get('duration_sec'):.2f}s "
                f"cues={len(report['softsubCues'])} "
                f"opens={(report.get('prologText') or '')[:48]!r}"
            )
            continue

        print(f"composing {clip_key} -> {dest}")
        try:
            report = compose_campaign_cutscene_mp4(
                clip_key=clip_key,
                dest_mp4=dest,
                hd_video_dir=hd_video_dir,
                narration_snd=args.narration_snd,
            )
        except Exception as exc:
            fail(str(exc))
        recipe = COMPOSED_CLIP_RECIPES[clip_key]
        probe = probe_mp4(dest)
        ok, reason = composed_mp4_meets_contract(probe, recipe)
        if not ok:
            fail(f"post-condition failed for {clip_key}: {reason}")
        sidecar = dest.with_suffix(dest.suffix + ".json")
        if not sidecar.is_file():
            fail(f"missing softsub sidecar {sidecar}")
        cue_batches.append(report["softsubCues"])
        results.append(
            {
                "clipKey": clip_key,
                "mp4": str(dest),
                "durationSec": probe.get("duration_sec"),
                "width": probe.get("width"),
                "height": probe.get("height"),
                "hasAudio": probe.get("has_audio"),
                "sidecar": str(sidecar),
                "subtitleMode": report.get("subtitleMode"),
                "narrationDurationSec": report.get("narrationDurationSec"),
                "decisionLog": report.get("decisionLog"),
            }
        )
        print(
            f"  ok {probe.get('width')}x{probe.get('height')} "
            f"duration={probe.get('duration_sec'):.2f}s audio={probe.get('has_audio')}"
        )

    bake_report = {
        "schema": "homm3.roe_castle_campaign_video_bake_report.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "gameRoot": str(game_root),
        "inventoryPath": str(inventory_path),
        "refusedCompose": refused,
        "composed": results,
        "subtitleMode": "softsub_sidecar_and_lockit",
        "burnIn": False,
    }

    if not args.skip_register and compose_keys:
        core_zip = game_root / CORE_ZIP_REL
        if not core_zip.is_file():
            fail(f"missing Core.zip: {core_zip}")
        clips_backup = upsert_clips_info_composed(core_zip, compose_keys)
        cinematic_backup = upsert_cinematic_lockit_in_core(core_zip, cue_batches)
        bake_report["clipsInfoBackup"] = str(clips_backup)
        bake_report["cinematicBackup"] = str(cinematic_backup)
        print(
            f"registered {len(compose_keys)} clip(s) in {CLIPS_MEMBER} "
            f"(haveSubtitles=true); cinematic LocKit english updated"
        )
    else:
        print("skipped Core.zip clips_info/cinematic rewrite")

    report_path = REPORT_DIR / "campaign_video_bake_report.v1.json"
    report_path.write_text(json.dumps(bake_report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote bake report {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
