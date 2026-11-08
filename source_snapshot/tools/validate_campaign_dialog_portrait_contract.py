#!/usr/bin/env python3
"""Fail-closed campaign dialog portrait contract.

Checks:
1. Installed Core.zip must not keep custom_maps/*AbSod dialog JSON that duplicates
   a primary dialog id (last-wins wipe of planned avatars).
2. Planner must not attribute the mission protagonist to narration / unresolved NPC
   speech (regression fixtures + overlay replan consistency).

Proof boundary: source/static + installed Core.zip readback. Not runtime UI proof.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/"
    r"Heroes of Might and Magic Olden Era - Golden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
POC = REPO / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

import dialog_portrait_plan as portraits  # noqa: E402

# Protagonist must not appear on these NPC / narration bodies.
_ATTRIBUTION_FIXTURES: list[tuple[str, str, str]] = [
    (
        "lost_at_sea",
        "natives_briefing",
        'The leader of the natives meets with you. The jolly old fellow seems very '
        'excited and says; "Our prayers have been answered! You are the one who '
        'will help us." After you agree, he and his tribesmen cheer and then begin '
        'singing, "Follow the cobblestone road..."',
    ),
    (
        "lost_at_sea",
        "goblin_song",
        'You are confronted by a bunch of short odorous goblins. They all line up '
        'in front of you and begin singing in unison, "Follow the cobblestone road..."',
    ),
    (
        "lost_at_sea",
        "day1_narration",
        "While on a three-hour sight seeing tour, the mighty Sir Christian's ship "
        "was blown off course by a sudden summer storm.",
    ),
    (
        "bashing_skulls",
        "generic_you_are_narration",
        'You are confronted by a messenger who says, "The enemy approaches."',
    ),
]


def _has_avatar(row: dict) -> bool:
    for slide in row.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        avatars = slide.get("avatars") or []
        if isinstance(avatars, list) and avatars:
            return True
    return False


def _dialog_rows_from_bytes(raw: bytes) -> list[dict]:
    data = json.loads(raw.decode("utf-8-sig"))
    rows = data.get("array") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _slide_icons(row: dict) -> list[str]:
    icons: list[str] = []
    for slide in row.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for av in slide.get("avatars") or []:
            if isinstance(av, dict) and av.get("icon"):
                icons.append(str(av["icon"]))
    return icons


def check_planner_attribution_fixtures() -> list[str]:
    errors: list[str] = []
    for mission_id, fixture_id, text in _ATTRIBUTION_FIXTURES:
        plan = portraits.plan_dialog_portraits(
            dialog_sid=fixture_id, mission_id=mission_id, text=text
        )
        banned = (
            "defaulted to mission protagonist",
            "filled unresolved quote speaker with mission protagonist",
        )
        for note in plan.notes:
            if any(token in note for token in banned):
                errors.append(
                    f"fixture {mission_id}/{fixture_id}: banned planner note {note!r}"
                )
        protagonist = portraits.mission_protagonist_icon(mission_id)
        if protagonist is not None:
            label, icon = protagonist
            for slide in plan.slides:
                if slide.icon == icon:
                    errors.append(
                        f"fixture {mission_id}/{fixture_id}: protagonist portrait "
                        f"{icon!r} attributed to non-player speech "
                        f"(speaker={slide.speaker_label!r}, notes={plan.notes})"
                    )
                    break
                if slide.speaker_label == label:
                    errors.append(
                        f"fixture {mission_id}/{fixture_id}: protagonist name "
                        f"{label!r} used as speaker title"
                    )
                    break
    natives = portraits.plan_dialog_portraits(
        dialog_sid="natives_briefing",
        mission_id="lost_at_sea",
        text=_ATTRIBUTION_FIXTURES[0][2],
    )
    if not any(s.icon and "dialogue_unit_h3_goblin" in (s.icon or "") for s in natives.slides):
        errors.append(
            "fixture lost_at_sea/natives_briefing: expected goblin unit dialog portrait "
            f"(got {[s.icon for s in natives.slides]})"
        )
    goblin = portraits.plan_dialog_portraits(
        dialog_sid="goblin_song",
        mission_id="lost_at_sea",
        text=_ATTRIBUTION_FIXTURES[1][2],
    )
    if not any(s.icon and "dialogue_unit_h3_goblin" in (s.icon or "") for s in goblin.slides):
        errors.append(
            "fixture lost_at_sea/goblin_song: expected goblin unit dialog portrait "
            f"(got {[s.icon for s in goblin.slides]})"
        )
    # Positive control: player actually speaking keeps protagonist.
    speak = portraits.plan_dialog_portraits(
        dialog_sid="you_complain",
        mission_id="lost_at_sea",
        text='You begin complaining to your troops. "How are we supposed to follow the road?"',
    )
    proto = portraits.mission_protagonist_icon("lost_at_sea")
    if proto is not None:
        _label, icon = proto
        if not any(s.icon == icon for s in speak.slides):
            errors.append(
                "positive control lost_at_sea/you_complain: expected protagonist when player speaks"
            )
    return errors


def check_core_absod_collisions(core_zip: Path) -> list[str]:
    errors: list[str] = []
    by_id: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    with zipfile.ZipFile(core_zip, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("DB/dialogs/dialogs/custom_maps/") or not name.endswith(
                ".json"
            ):
                continue
            folder = name.split("custom_maps/", 1)[1].split("/", 1)[0]
            for row in _dialog_rows_from_bytes(zf.read(name)):
                dialog_id = str(row.get("id") or "").strip()
                if not dialog_id:
                    continue
                by_id[dialog_id].append((name, _has_avatar(row)))
            if folder.endswith("AbSod") or any(
                folder.endswith(suffix)
                for suffix in (
                    "RoeDungeon",
                    "RoeNeutral",
                    "RoeInferno",
                    "RoeNecropolis",
                    "RoeCastle",
                    "RoeRampart",
                )
            ):
                # Presence alone is enough to fail — these trees are obsolete.
                errors.append(f"stale duplicate dialog member still in Core.zip: {name}")
    # Also report id collisions that would wipe portraits if AbSod somehow returns.
    for dialog_id, rows in sorted(by_id.items()):
        if len(rows) < 2:
            continue
        if any(has for _, has in rows) and not all(has for _, has in rows):
            paths = ", ".join(f"{path}(avatars={has})" for path, has in rows)
            errors.append(
                f"dialog id {dialog_id!r} has conflicting avatar presence across members: {paths}"
            )
    return errors


def _load_dialog_loc(overlay_root: Path) -> dict[str, str]:
    loc_path = overlay_root / "Lang" / "english" / "texts" / "dialogues.json"
    if not loc_path.is_file():
        return {}
    data = json.loads(loc_path.read_text(encoding="utf-8"))
    rows = data.get("array") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or row.get("sid") or "").strip()
        text = row.get("text") or row.get("en") or row.get("value") or ""
        if isinstance(text, dict):
            text = text.get("text") or ""
        if sid:
            out[sid] = str(text)
    return out


def _dialog_body_from_loc(dialog_id: str, loc: dict[str, str]) -> str:
    parts: list[str] = []
    i = 0
    while True:
        key = f"dialogue_text_{dialog_id}_{i}"
        if key not in loc:
            break
        parts.append(loc[key])
        i += 1
    if parts:
        return "".join(parts)
    return loc.get(f"dialogue_text_{dialog_id}", "")


def check_overlay_attribution(overlay_root: Path, mission_id: str) -> list[str]:
    """Emitted protagonist icons/titles must match a fresh replan of the english body."""
    errors: list[str] = []
    protagonist = portraits.mission_protagonist_icon(mission_id)
    if protagonist is None:
        return errors
    proto_label, proto_icon = protagonist
    dialogs = overlay_root / "DB" / "dialogs" / "dialogs" / "custom_maps"
    if not dialogs.is_dir():
        errors.append(f"{mission_id}: missing dialog overlay at {dialogs}")
        return errors
    loc = _load_dialog_loc(overlay_root)
    checked = 0
    for path in sorted(dialogs.rglob("*.json")):
        folder = path.parent.name
        if any(
            folder.endswith(suffix)
            for suffix in (
                "AbSod",
                "RoeDungeon",
                "RoeNeutral",
                "RoeInferno",
                "RoeNecropolis",
                "RoeCastle",
                "RoeRampart",
            )
        ):
            continue
        for row in _dialog_rows_from_bytes(path.read_bytes()):
            dialog_id = str(row.get("id") or "")
            if not dialog_id.startswith(f"{mission_id}_"):
                continue
            if not any(
                token in dialog_id
                for token in ("_briefing_", "_intro_dialog", "_map_event_", "_monster_")
            ):
                continue
            checked += 1
            body = _dialog_body_from_loc(dialog_id, loc)
            if not body.strip():
                continue
            plan = portraits.plan_dialog_portraits(
                dialog_sid=dialog_id, mission_id=mission_id, text=body
            )
            planned_icons = [s.icon for s in plan.slides if s.icon]
            planned_titles = {s.speaker_label for s in plan.slides if s.speaker_label}
            emitted = _slide_icons(row)
            if proto_icon in emitted and proto_icon not in planned_icons:
                errors.append(
                    f"{mission_id}: {dialog_id} emits protagonist portrait but replan "
                    f"does not (notes={plan.notes})"
                )
            for slide in row.get("slides") or []:
                if not isinstance(slide, dict) or slide.get("id") == "ending":
                    continue
                title_obj = slide.get("title")
                tsid = title_obj.get("sid") if isinstance(title_obj, dict) else None
                title = loc.get(str(tsid or ""), "")
                if title == proto_label and proto_label not in planned_titles:
                    errors.append(
                        f"{mission_id}: {dialog_id} emits protagonist title {title!r} "
                        f"but replan speakers are {sorted(planned_titles)!r}"
                    )
                    break
    if checked == 0:
        errors.append(f"{mission_id}: no briefing/intro/map_event dialogs under {dialogs}")
    return errors


def _hub_config_overlay_pairs(repo_root: Path) -> list[tuple[str, Path]]:
    import importlib.util

    installer = repo_root / "tools" / "install_roe_castle_continuity_weave.py"
    spec = importlib.util.spec_from_file_location(
        "install_roe_castle_continuity_weave", installer
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load continuity installer: {installer}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out: list[tuple[str, Path]] = []
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
            overlay = (repo_root / Path(str(install.get("coreOverlay") or ""))).resolve()
            out.append((mission_id, overlay))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=REPO)
    ap.add_argument("--core-zip", type=Path, default=DEFAULT_CORE)
    ap.add_argument(
        "--overlay",
        action="append",
        default=[],
        metavar="MISSION=PATH",
        help="mission_id=path/to/core_overlay (repeatable)",
    )
    ap.add_argument(
        "--all-hub-configs",
        action="store_true",
        help="Validate every continuity HUB_CONFIGS mission core_overlay",
    )
    ap.add_argument(
        "--require-overlays",
        action="store_true",
        help="Fail if no overlay rows were supplied",
    )
    args = ap.parse_args()
    errors: list[str] = []
    errors.extend(check_planner_attribution_fixtures())
    if args.core_zip.is_file():
        errors.extend(check_core_absod_collisions(args.core_zip.resolve()))
    else:
        errors.append(f"missing Core.zip: {args.core_zip}")

    overlays: list[tuple[str, Path]] = []
    for item in args.overlay:
        if "=" not in item:
            errors.append(f"--overlay must be mission_id=path; got {item!r}")
            continue
        mission_id, raw_path = item.split("=", 1)
        overlays.append((mission_id.strip(), Path(raw_path).resolve()))
    if args.all_hub_configs:
        overlays.extend(_hub_config_overlay_pairs(args.repo_root.resolve()))
    # Dedupe by mission id.
    deduped: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for mission_id, overlay in overlays:
        if mission_id in seen:
            continue
        seen.add(mission_id)
        deduped.append((mission_id, overlay))
    if args.require_overlays and not deduped:
        errors.append("--require-overlays set but no overlay rows provided")
    for mission_id, overlay in deduped:
        errors.extend(check_overlay_attribution(overlay, mission_id))

    if errors:
        print("FAIL campaign dialog portrait contract:")
        for err in errors:
            print(f"- {err}")
        return 1
    print(
        "PASS campaign dialog portrait contract "
        f"(core={args.core_zip}, overlays={len(deduped)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
