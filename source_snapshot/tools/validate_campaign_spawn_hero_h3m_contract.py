#!/usr/bin/env python3
"""Fail closed when carry-policy / hub / profile spawn disagrees with H3M evidence.

Playable starts come from H3M map heroType / mainCustomHeroId / heroesNames.
Known ``heroesNames`` display names win over bare type-id mapping (Festival Razor
Claw: type 149 named Kilgor → ``homm3_stronghold_hero_17``, not Mutare).

Campaign-chain display names inherit across an H3C entry (Yog type 45 stays Yog
on later Birth of a Barbarian maps that strip the name). When a human map hero
resolves via name_over_type, that hero is the spawn — not lowest sourceIndex.

Narrative campaign titles alone are never spawn sources (Long Live the Queen prose
names Queen Catherine; Homecoming's H3M start is still Christian unless
heroesNames says otherwise).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from campaign_hub_spawn import campaign_hub_spawn_by_mission  # noqa: E402
from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402
from campaign_profile_derive import (  # noqa: E402
    collect_campaign_chain_hero_names_by_type,
    infer_campaign_spawn_hero_sid,
    infer_human_h3_owner,
)
from h3m_hero_sid import (  # noqa: E402
    H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE,
    campaign_protagonist_hero_types,
    h3_hero_name_to_hero_sid,
    h3_hero_type_to_hero_sid,
    resolve_h3_hero_sid,
)

DEFAULT_MANIFESTS: tuple[Path, ...] = (
    ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json",
    ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json",
    ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
)

# Birth of a Barbarian: type 45 is Yog on mission 1; later maps strip the name.
YOG_CHAIN_SPAWN_PINS: dict[str, str] = {
    "on_the_run": "homm3_stronghold_hero_5",
    "the_meeting": "homm3_stronghold_hero_5",
    "a_tough_start": "homm3_stronghold_hero_5",
    "falor_and_terwen": "homm3_stronghold_hero_5",
    "returning_to_bracada": "homm3_stronghold_hero_5",
}

# Unholy Alliance: maps store Yog as type 96 and Crag Hack as type 102
# (classic Crag/Oris slots). Campaign type aliases remap them.
UNHOLY_ALLIANCE_SPAWN_PINS: dict[str, str] = {
    "harvest": "homm3_stronghold_hero_5",  # Yog
    "gathering_the_legion": "homm3_stronghold_hero_1",  # Crag Hack
}

# Hack and Slash: type 102 is Crag Hack, not Oris.
CRAG_HACK_SPAWN_PINS: dict[str, str] = {
    "bashing_skulls": "homm3_stronghold_hero_1",
}

# Placeholder-type and companion-over-protagonist pins (derive must keep these).
CAMPAIGN_SPAWN_HERO_PINS: dict[str, str] = {
    # Elixir of Life / Final Gelu track
    "graduation_exercise": "homm3_rampart_hero_17",
    "search_for_a_killer": "homm3_rampart_hero_17",
    # Dragon's Blood
    "culling_the_weak": "homm3_dungeon_hero_17",
    # Playing with Fire
    "farming_towns": "homm3_fortress_hero_17",
    # AB
    "catherines_charge": "homm3_castle_hero_17",
    "shadows_of_the_forest": "homm3_rampart_hero_17",
    "seeking_armageddon": "homm3_inferno_hero_17",
    "maker_of_sorrows": "homm3_inferno_hero_17",
    # Rise of the Necromancer — Sandro over Vidomina/Finneas companions
    "master": "homm3_necropolis_hero_11",
    "finneas_vilmar": "homm3_necropolis_hero_11",
    # Long Live the King / New Beginning — Gem over Melodia-slot
    "after_the_amulet": "homm3_rampart_hero_12",
    "clearing_the_border": "homm3_rampart_hero_12",
    # Festival of Life — Kilgor even when early maps place other barbarians
    "taming_of_the_wild": "homm3_stronghold_hero_17",
    "razor_claw": "homm3_stronghold_hero_17",
}


def _existing_manifests() -> list[Path]:
    return [path for path in DEFAULT_MANIFESTS if path.is_file()]


def _name_over_type_map_hero_sids(mission) -> list[str]:
    """SIDs of human concrete map heroes that resolve via name_over_type.

    When the H3C entry declares protagonist types, only those map heroes are
    considered — companion renames (Vidomina) must not force spawn.
    """
    if not mission.alignment_path.exists():
        return []
    human_owner = infer_human_h3_owner(mission)
    names_by_type = collect_campaign_chain_hero_names_by_type(mission)
    protag_types = campaign_protagonist_hero_types(mission.campaign_entry)
    alignment = json.loads(mission.alignment_path.read_text(encoding="utf-8-sig"))
    out: list[str] = []
    for entity in alignment.get("globalEntities") or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("owner") != human_owner:
            continue
        if entity.get("payloadKind") not in {"hero", "hero_or_prison", "hero_placeholder"}:
            continue
        hero_type = entity.get("heroType")
        if not isinstance(hero_type, int) or hero_type == H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
            continue
        if entity.get("templateObjectId") == 214:
            continue
        if protag_types and hero_type not in protag_types:
            continue
        sid, tag = resolve_h3_hero_sid(hero_type, name=names_by_type.get(hero_type))
        if tag == "h3m_hero_name_over_type":
            out.append(sid)
    return out


def _validate_mission(
    mission,
    *,
    policy_spawn: dict[str, str] | None,
    profile_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        derived = infer_campaign_spawn_hero_sid(mission)
    except ValueError as exc:
        # Campaign-granted / placeholder starts need explicit missionSpawns;
        # absence of H3M concrete hero is allowed only when policy has a spawn.
        if policy_spawn is None:
            errors.append(str(exc))
        return errors
    expected = str(derived["heroSid"])
    hero_type = derived.get("heroType")
    hero_name = str(derived.get("heroName") or "").strip()

    # Fail closed: when H3M supplies a known display name for the start type, the
    # derived SID must be that name's OE SID (name wins over type-id table).
    if hero_name and isinstance(hero_type, int):
        named_sid = h3_hero_name_to_hero_sid(hero_name)
        if named_sid is not None and named_sid != expected:
            errors.append(
                f"{mission.mission_id}: derived heroSid {expected!r} disagrees with "
                f"known H3M name {hero_name!r} → {named_sid!r} "
                f"(heroType={hero_type}, evidence={derived.get('evidence')})"
            )
        if named_sid is not None:
            typed_sid = h3_hero_type_to_hero_sid(int(hero_type))
            if named_sid != typed_sid and "name_over_type" not in str(derived.get("evidence") or ""):
                errors.append(
                    f"{mission.mission_id}: known name {hero_name!r} maps to {named_sid!r} "
                    f"over type {hero_type}→{typed_sid!r}, but evidence "
                    f"{derived.get('evidence')!r} does not record name_over_type"
                )

    # If exactly one protagonist-eligible map hero is name_over_type, spawn must
    # match. Multiple distinct renamed protagonists (Yog+Crag) are allowed to
    # fall through to mainCustom / heroesNames.
    over_type_sids = _name_over_type_map_hero_sids(mission)
    if len(set(over_type_sids)) == 1 and over_type_sids[0] != expected:
        errors.append(
            f"{mission.mission_id}: human map has name_over_type hero "
            f"{over_type_sids[0]!r} but derived spawn is {expected!r} "
            f"(evidence={derived.get('evidence')})"
        )

    pinned = YOG_CHAIN_SPAWN_PINS.get(mission.mission_id)
    if pinned is not None and expected != pinned:
        errors.append(
            f"{mission.mission_id}: Yog-chain pin expects {pinned!r}, "
            f"derived {expected!r} (evidence={derived.get('evidence')})"
        )
    pinned = UNHOLY_ALLIANCE_SPAWN_PINS.get(mission.mission_id)
    if pinned is not None and expected != pinned:
        errors.append(
            f"{mission.mission_id}: Unholy Alliance pin expects {pinned!r}, "
            f"derived {expected!r} (evidence={derived.get('evidence')})"
        )
    pinned = CRAG_HACK_SPAWN_PINS.get(mission.mission_id)
    if pinned is not None and expected != pinned:
        errors.append(
            f"{mission.mission_id}: Hack and Slash pin expects {pinned!r}, "
            f"derived {expected!r} (evidence={derived.get('evidence')})"
        )
    pinned = CAMPAIGN_SPAWN_HERO_PINS.get(mission.mission_id)
    if pinned is not None and expected != pinned:
        errors.append(
            f"{mission.mission_id}: campaign spawn pin expects {pinned!r}, "
            f"derived {expected!r} (evidence={derived.get('evidence')})"
        )

    if policy_spawn is None:
        errors.append(
            f"{mission.mission_id}: H3M derives {expected} ({derived.get('evidence')}) "
            "but no carry-policy/hub spawn is registered"
        )
    else:
        got = str(policy_spawn.get("heroSid") or "")
        if got != expected:
            errors.append(
                f"{mission.mission_id}: policy/hub spawn heroSid {got!r} != H3M-derived "
                f"{expected!r} (evidence={derived.get('evidence')}, "
                f"heroType={derived.get('heroType')}, heroName={hero_name or None!r}). "
                "Do not set spawn from campaign title narrative; known heroesNames win."
            )

    pin_path = profile_path or mission.profile_path
    if isinstance(pin_path, Path) and pin_path.is_file():
        try:
            profile = json.loads(pin_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{mission.mission_id}: cannot read profile {pin_path}: {exc}")
        else:
            spawn = profile.get("spawn") if isinstance(profile.get("spawn"), dict) else {}
            profile_hero = str(spawn.get("heroSid") or "")
            if profile_hero and profile_hero != expected:
                errors.append(
                    f"{mission.mission_id}: profile spawn.heroSid {profile_hero!r} != "
                    f"H3M-derived {expected!r} (evidence={derived.get('evidence')})"
                )

    return errors


def _mission_profile_path(mission) -> Path | None:
    scenario_dir = ROOT / "scenarios"
    # Profiles live beside mission folders named {mission_id}_* / *_{mission_id}.
    candidates = [
        scenario_dir / f"{mission.mission_id}_roe_castle" / "raw_translation.profile.json",
        scenario_dir / f"{mission.mission_id}_roe_necropolis" / "raw_translation.profile.json",
        scenario_dir / f"{mission.mission_id}_roe_dungeon" / "raw_translation.profile.json",
        scenario_dir / f"{mission.mission_id}_roe_inferno" / "raw_translation.profile.json",
        scenario_dir / f"{mission.mission_id}_roe_neutral" / "raw_translation.profile.json",
        scenario_dir / f"{mission.mission_id}_ab_sod" / "raw_translation.profile.json",
    ]
    # Also honor mission.scenario_id folder when present on the object.
    scenario_id = getattr(mission, "scenario_id", None)
    if isinstance(scenario_id, str) and scenario_id:
        candidates.insert(0, scenario_dir / scenario_id / "raw_translation.profile.json")
    for path in candidates:
        if path.is_file():
            return path
    # Glob fallback for renamed folders.
    matches = sorted(scenario_dir.glob(f"*{mission.mission_id}*/raw_translation.profile.json"))
    return matches[0] if len(matches) == 1 else (matches[0] if matches else None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        dest="manifests",
        help="Batch manifest to check (default: all RoE + AB/SoD campaign manifests).",
    )
    parser.add_argument(
        "--mission",
        action="append",
        dest="missions",
        help="Optional missionId filter (default: all missions in manifests).",
    )
    args = parser.parse_args()
    manifests = [
        path.resolve() if not path.is_absolute() else path
        for path in (list(args.manifests) if args.manifests else _existing_manifests())
    ]
    if not manifests:
        print("FAIL validate_campaign_spawn_hero_h3m_contract: no batch manifests found")
        return 1
    by_mission = campaign_hub_spawn_by_mission(repo_root=ROOT)
    errors: list[str] = []
    checked = 0
    name_over_type = 0
    for manifest_path in manifests:
        batch = load_batch_manifest(manifest_path.resolve())
        selected = list(args.missions) if args.missions else [
            mission.mission_id for mission in batch.missions
        ]
        for mission_id in selected:
            mission = mission_by_id(batch, mission_id)
            profile_path = mission.profile_path or _mission_profile_path(mission)
            policy = by_mission.get(mission_id)
            errors.extend(
                _validate_mission(
                    mission,
                    policy_spawn=policy,
                    profile_path=profile_path,
                )
            )
            try:
                derived = infer_campaign_spawn_hero_sid(mission)
                if "name_over_type" in str(derived.get("evidence") or ""):
                    name_over_type += 1
            except ValueError:
                pass
            checked += 1
    if errors:
        print(f"FAIL validate_campaign_spawn_hero_h3m_contract ({checked} missions)")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "missionsChecked": checked,
                "manifests": [
                    str(path.resolve().relative_to(ROOT)).replace("\\", "/")
                    for path in manifests
                ],
                "nameOverTypeResolutions": name_over_type,
                "yogChainPins": YOG_CHAIN_SPAWN_PINS,
                "unholyAllianceSpawnPins": UNHOLY_ALLIANCE_SPAWN_PINS,
                "cragHackSpawnPins": CRAG_HACK_SPAWN_PINS,
                "campaignSpawnHeroPins": CAMPAIGN_SPAWN_HERO_PINS,
                "proofBoundary": (
                    "source/static H3M header + alignment map hero; "
                    "known heroesNames / campaign-chain inherited names win over type-id mapping; "
                    "name_over_type map heroes win spawn selection"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
