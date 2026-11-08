#!/usr/bin/env python3
"""Refresh AB/SoD campaign dialog overlays with portrait slides (no full map rebuild).

Use when full raw_translation rebuild fails on unrelated GATE/portal contracts but
alignment + existing core_overlay are present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
RAW = POC / "raw_translation"
APPROACH = POC / "approach_cell"
for path in (RAW, POC, APPROACH):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402
from scenario_profile import load_scenario_profile  # noqa: E402
import campaign_runtime_script as campaign_script  # noqa: E402
import layer_atlas as atlas  # noqa: E402
import surface_emit as single  # noqa: E402
import build_raw_translation_map as raw_builder  # noqa: E402
import generate_campaign_raw_translation_profile as raw_profile  # noqa: E402


def refresh_mission_dialogs(batch, mission_id: str) -> dict:
    mission = mission_by_id(batch, mission_id)
    disk_profile = raw_profile.build_raw_translation_profile(batch, mission)
    profile_path = raw_profile.raw_profile_path_for_mission(mission)
    raw_profile.write_json(
        profile_path,
        {key: value for key, value in disk_profile.items() if not str(key).startswith("_")},
    )
    profile = load_scenario_profile(profile_path)
    raw_builder.apply_profile_globals(profile)
    single.set_mission_id(mission_id)
    single.OUT_ROOT = profile.output_root
    atlas.OUT_ROOT = profile.output_root

    alignment_path = profile.alignment_path
    if not alignment_path.is_file():
        raise FileNotFoundError(f"alignment missing: {alignment_path}")
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    alignment_story = alignment["container"]["chunks"][3]

    overlay = profile.output_root / "core_overlay"
    overlay.mkdir(parents=True, exist_ok=True)

    dialog_entries = campaign_script.core_dialog_entries_from_alignment(mission_id, alignment_story)
    monster_entries = campaign_script.core_dialog_entries_from_monster_messages(
        mission_id,
        (alignment.get("alignment") or {}).get("globalObjectProperties", {}).get(
            "propEntities"
        )
        or (alignment_story.get("globalObjectProperties") or {}).get("propEntities")
        or [],
        mission_title=atlas.TITLE,
    )
    if monster_entries:
        known_ids = {str(e.get("id") or "") for e in dialog_entries}
        dialog_entries.extend(
            entry for entry in monster_entries if str(entry.get("id") or "") not in known_ids
        )
    intro_text = "\n\n".join(
        str(segment.get("body") or "").strip()
        for segment in (alignment_story.get("briefingSegments") or [])
        if isinstance(segment, dict) and str(segment.get("body") or "").strip()
    )
    if intro_text:
        intro_sid = f"{mission_id}_intro_dialog"
        intro_title = campaign_script.mission_display_title(mission_id, atlas.TITLE)
        intro_entry = {"id": intro_sid, "title": intro_title, "text": intro_text}
        intro_entry = campaign_script._apply_dialog_portrait_plans(mission_id, [intro_entry])[0]
        dialog_entries = [
            intro_entry,
            *[entry for entry in dialog_entries if entry.get("id") != intro_sid],
        ]
    if not dialog_entries:
        return {"mission": mission_id, "ok": True, "dialogs": 0, "note": "no dialog entries"}

    report = single.generate_campaign_dialog_overlay(dialog_entries)
    multi = sum(1 for e in dialog_entries if isinstance(e.get("slides"), list) and len(e["slides"]) > 1)
    single_count = sum(
        1
        for e in dialog_entries
        if (isinstance(e.get("avatars"), list) and e.get("avatars"))
        and not (isinstance(e.get("slides"), list) and len(e.get("slides") or []) > 1)
    )
    return {
        "mission": mission_id,
        "ok": True,
        "dialogs": len(dialog_entries),
        "multi": multi,
        "single": single_count,
        "overlay": str(overlay),
        "reportKeys": sorted(report.keys()) if isinstance(report, dict) else [],
    }


def _hub_config_mission_manifest_rows() -> list[tuple[Path, str]]:
    """Return (manifest_path, mission_id) for every continuity HUB_CONFIGS mission."""
    import importlib.util

    installer = ROOT / "tools" / "install_roe_castle_continuity_weave.py"
    spec = importlib.util.spec_from_file_location(
        "install_roe_castle_continuity_weave", installer
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load continuity installer: {installer}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    manifests = [
        ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
        ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json",
        ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json",
    ]
    mission_to_manifest: dict[str, Path] = {}
    for path in manifests:
        batch = load_batch_manifest(path.resolve())
        for mission in batch.missions:
            mission_to_manifest[str(mission.mission_id)] = path.resolve()

    rows: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for hub in (getattr(mod, "HUB_CONFIGS", None) or {}).values():
        if not isinstance(hub, dict):
            continue
        for install in hub.get("mapInstalls") or []:
            if not isinstance(install, dict):
                continue
            parts = Path(str(install.get("coreOverlay") or "")).parts
            if "raw_translation_map" not in parts:
                continue
            mission_id = parts[parts.index("raw_translation_map") - 1]
            if mission_id == "homecoming_poc":
                mission_id = "homecoming"
            if mission_id in seen:
                continue
            seen.add(mission_id)
            manifest = mission_to_manifest.get(mission_id)
            if manifest is None:
                raise KeyError(
                    f"HUB_CONFIGS mission {mission_id!r} missing from batch manifests"
                )
            rows.append((manifest, mission_id))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
    )
    ap.add_argument("--mission", action="append", dest="missions", default=[])
    ap.add_argument(
        "--all-hub-configs",
        action="store_true",
        help="Refresh every continuity HUB_CONFIGS mission across RoE/AB/SoD manifests",
    )
    ap.add_argument(
        "--failed-from-summary",
        type=Path,
        help="batch_rebuild_summary.json — refresh dialogs for its failed list",
    )
    args = ap.parse_args()

    work: list[tuple[Path, str]] = []
    if args.all_hub_configs:
        work.extend(_hub_config_mission_manifest_rows())
    missions = list(args.missions or [])
    if args.failed_from_summary and args.failed_from_summary.is_file():
        summary = json.loads(args.failed_from_summary.read_text(encoding="utf-8"))
        missions.extend(summary.get("failed") or [])
    default_manifest = args.manifest.resolve()
    for mission_id in missions:
        work.append((default_manifest, mission_id))
    if not work:
        ap.error("Pass --mission, --all-hub-configs, and/or --failed-from-summary")

    # Dedupe while preserving order.
    deduped: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for manifest, mission_id in work:
        if mission_id in seen:
            continue
        seen.add(mission_id)
        deduped.append((manifest, mission_id))

    batches: dict[Path, object] = {}
    results = []
    for manifest, mission_id in deduped:
        if manifest not in batches:
            batches[manifest] = load_batch_manifest(manifest)
        batch = batches[manifest]
        print(f"DIALOG-REFRESH {mission_id} ({manifest.name})", flush=True)
        try:
            row = refresh_mission_dialogs(batch, mission_id)
            row["manifest"] = str(manifest)
            print(
                f"  OK dialogs={row['dialogs']} multi={row.get('multi')} single={row.get('single')}",
                flush=True,
            )
        except Exception as exc:
            row = {
                "mission": mission_id,
                "ok": False,
                "error": str(exc),
                "manifest": str(manifest),
            }
            print(f"  FAIL {exc}", flush=True)
        results.append(row)

    out = ROOT / "artifacts" / "dialog_portrait_inventory" / "dialog_refresh_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    failed = [r for r in results if not r.get("ok")]
    print(
        json.dumps(
            {
                "ok": len(results) - len(failed),
                "failed": len(failed),
                "failedMissions": [r.get("mission") for r in failed],
            },
            indent=2,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
