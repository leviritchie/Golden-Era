#!/usr/bin/env python3
"""Shared derivation helpers for campaign scenario profiles.

Centralizes values that used to be hand-copied across per-mission profile JSON:
size/layers from H3C, start-hero from object walk, entity counts from alignment
or port-manifest. Mission-specific overrides stay in the batch manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import h3m_format as h3m
from campaign_mission import CampaignMission, load_batch_manifest
from h3c_mission_source import load_h3c_block
from h3m_hero_sid import (
    H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE,
    campaign_hero_type_name_aliases,
    campaign_protagonist_hero_types,
    collect_h3m_hero_names_by_type,
    h3_hero_sid_to_hero_type,
    merge_h3m_hero_names_by_type,
    resolve_h3_hero_sid,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BATCH_MANIFESTS: tuple[Path, ...] = (
    _REPO_ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json",
    _REPO_ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json",
    _REPO_ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
)


def rel_repo(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def infer_human_h3_owner(mission: CampaignMission) -> int:
    """Return the H3M player index that can be human (default 0 if none/ambiguous)."""
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    header = h3m.decode_h3m_scenario_header(source.h3m_data)
    humans = [
        index
        for index, player in enumerate(header.get("players") or [])
        if isinstance(player, dict) and player.get("playable") and player.get("canHuman")
    ]
    if len(humans) == 1:
        return int(humans[0])
    if not humans:
        return 0
    return int(min(humans))


def _human_player_row(header: dict[str, Any], human_owner: int) -> dict[str, Any] | None:
    players = header.get("players") or []
    if not isinstance(players, list):
        return None
    if 0 <= human_owner < len(players) and isinstance(players[human_owner], dict):
        return players[human_owner]
    for player in players:
        if isinstance(player, dict) and player.get("canHuman") and player.get("playable"):
            return player
    return None


def discover_campaign_chain_missions(
    mission: CampaignMission,
    *,
    chain_missions: Sequence[CampaignMission] | None = None,
) -> tuple[CampaignMission, ...]:
    """Return missions that share this mission's H3C campaign entry (same hub chain)."""
    if chain_missions is not None:
        entry = str(mission.campaign_entry)
        siblings = tuple(
            row for row in chain_missions if str(row.campaign_entry) == entry
        )
        return siblings or (mission,)
    entry = str(mission.campaign_entry)
    found: list[CampaignMission] = []
    seen: set[str] = set()
    for manifest_path in _DEFAULT_BATCH_MANIFESTS:
        if not manifest_path.is_file():
            continue
        batch = load_batch_manifest(manifest_path.resolve())
        for row in batch.missions:
            if str(row.campaign_entry) != entry:
                continue
            if row.mission_id in seen:
                continue
            seen.add(row.mission_id)
            found.append(row)
    if not found:
        return (mission,)
    # Prefer the live mission object for the current id (paths/overrides).
    return tuple(mission if row.mission_id == mission.mission_id else row for row in found)


def collect_campaign_chain_hero_names_by_type(
    mission: CampaignMission,
    *,
    chain_missions: Sequence[CampaignMission] | None = None,
) -> dict[int, str]:
    """Collect heroType→displayName across the H3C campaign chain.

    Later missions often strip the renamed protagonist display name (Yog type 45
    on Birth of a Barbarian missions 2–5). Names discovered on any chain mission
    apply when resolving bare type ids on the others.

    Also merges H3C campaign / mission type→name aliases (Unholy Alliance type
    96→Yog / 102→Crag Hack; AB Shadows 148→Gelu; Seeking 155→Xeron; …) so map
    emit and spawn derive use the scenario identity, not the classic roster slot.
    """
    maps: list[dict[int, str]] = []
    for sibling in discover_campaign_chain_missions(mission, chain_missions=chain_missions):
        source = load_h3c_block(sibling.campaign_entry, sibling.block_index)
        header = h3m.decode_h3m_scenario_header(source.h3m_data)
        maps.append(collect_h3m_hero_names_by_type(header))
    merged = merge_h3m_hero_names_by_type(
        *maps,
        context=f"campaign chain for {mission.mission_id} ({mission.campaign_entry})",
    )
    aliases = campaign_hero_type_name_aliases(
        mission.campaign_entry, mission_id=mission.mission_id
    )
    if not aliases:
        return merged
    return merge_h3m_hero_names_by_type(
        merged,
        aliases,
        context=(
            f"campaign type aliases for {mission.mission_id} "
            f"({mission.campaign_entry})"
        ),
    )


def _human_map_hero_candidates(
    mission: CampaignMission,
    *,
    human_owner: int,
) -> list[dict[str, Any]]:
    if not mission.alignment_path.exists():
        return []
    alignment = json.loads(mission.alignment_path.read_text(encoding="utf-8-sig"))
    candidates: list[dict[str, Any]] = []
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
        candidates.append(entity)
    candidates.sort(
        key=lambda row: (
            0 if int(str(row.get("sourceKey") or "1:0:0").split(":", 1)[0]) == 0 else 1,
            int(row.get("sourceIndex") or 0),
        )
    )
    return candidates


def infer_campaign_spawn_hero_sid(
    mission: CampaignMission,
    *,
    chain_missions: Sequence[CampaignMission] | None = None,
) -> dict[str, Any]:
    """Derive StoryHub/map spawn hero from H3M evidence (never from campaign title).

    When the H3C entry declares protagonist type ids, any protagonist evidence
    (map / mainCustomHeroId / heroesNames) beats companion map heroes — even
    companions that resolve via name_over_type (Vidomina on Master; Melodia-slot
    on After the Amulet).

    Within the active candidate set (protagonists only when those are present,
    otherwise all human map heroes):
    1. Exactly one name_over_type map hero
    2. Exactly one protagonist-type map hero
    3. Concrete ``mainCustomHeroId`` (protagonist-eligible when set is known)
    4. First protagonist ``heroesNames`` id, else first concrete heroesNames id
    5. First concrete human map hero (surface layer, then sourceIndex)

    Display names come from this mission plus the rest of the H3C campaign chain
    (so Yog type 45 stays Yog after later maps strip the name), plus H3C /
    mission type→name aliases (Final 96→Yog, Gelu 148→Gelu, AB Seeking
    155→Xeron, …). Narrative campaign titles alone are still not spawn sources.
    """
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    header = h3m.decode_h3m_scenario_header(source.h3m_data)
    human_owner = infer_human_h3_owner(mission)
    local_names = collect_h3m_hero_names_by_type(header)
    chain_names = collect_campaign_chain_hero_names_by_type(
        mission, chain_missions=chain_missions
    )
    # Local names win on conflict only if identical after normalize; merge already
    # fail-closes on conflicts, and local is included in chain scan — use chain map.
    names_by_type = chain_names if chain_names else local_names
    protag_types = campaign_protagonist_hero_types(mission.campaign_entry)

    def _resolve(hero_type: int, *, evidence_prefix: str, **extra: Any) -> dict[str, Any]:
        name = names_by_type.get(hero_type)
        hero_sid, evidence_tag = resolve_h3_hero_sid(hero_type, name=name)
        row: dict[str, Any] = {
            "heroSid": hero_sid,
            "heroType": hero_type,
            "evidence": f"{evidence_prefix}:{evidence_tag}",
            "humanH3Owner": human_owner,
        }
        if name:
            row["heroName"] = name
            if hero_type not in local_names:
                row["heroNameInherited"] = True
        row.update(extra)
        return row

    def _is_protag(hero_type: int) -> bool:
        return not protag_types or hero_type in protag_types

    map_candidates = _human_map_hero_candidates(mission, human_owner=human_owner)
    player = _human_player_row(header, human_owner)
    names_rows = [
        row
        for row in ((player or {}).get("heroesNames") or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and row["id"] != H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE
    ]
    protag_map = [
        entity
        for entity in map_candidates
        if isinstance(entity.get("heroType"), int) and int(entity["heroType"]) in protag_types
    ] if protag_types else []
    protag_names_rows = (
        [row for row in names_rows if int(row["id"]) in protag_types] if protag_types else []
    )
    main_id = (player or {}).get("mainCustomHeroId")
    main_concrete = (
        isinstance(main_id, int) and main_id != H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE
    )
    main_is_protag = bool(main_concrete and _is_protag(int(main_id)))
    # Sandro on Master is heroesNames-only; Gem on After the Amulet likewise.
    # Do not let companion map name_over_type win when any protagonist evidence exists.
    has_protag_evidence = bool(
        protag_types
        and (
            protag_map
            or protag_names_rows
            or (main_is_protag and int(main_id) in protag_types)
        )
    )
    select_map = protag_map if has_protag_evidence else map_candidates

    name_over_type: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entity in select_map:
        hero_type = int(entity["heroType"])
        resolved = _resolve(
            hero_type,
            evidence_prefix="h3m_map_human_hero",
            sourceKey=entity.get("sourceKey"),
        )
        if "name_over_type" in str(resolved.get("evidence") or ""):
            name_over_type.append((entity, resolved))
    if len(name_over_type) > 1:
        # Multiple renamed protagonists (Yog+Crag): fall through to mainCustom /
        # heroesNames rather than fail closed — fixedHeroesSet still lists both.
        name_over_type = []
    if len(name_over_type) == 1:
        return name_over_type[0][1]

    if has_protag_evidence and len(protag_map) == 1:
        entity = protag_map[0]
        return _resolve(
            int(entity["heroType"]),
            evidence_prefix="h3m_map_campaign_protagonist",
            sourceKey=entity.get("sourceKey"),
        )

    if main_concrete and (not has_protag_evidence or main_is_protag):
        return _resolve(int(main_id), evidence_prefix="h3m_mainCustomHeroId")

    if has_protag_evidence and protag_names_rows:
        return _resolve(int(protag_names_rows[0]["id"]), evidence_prefix="h3m_heroesNames")

    if select_map:
        return _resolve(
            int(select_map[0]["heroType"]),
            evidence_prefix=(
                "h3m_map_campaign_protagonist" if has_protag_evidence else "h3m_map_human_hero"
            ),
            sourceKey=select_map[0].get("sourceKey"),
        )

    if names_rows:
        chosen = protag_names_rows[0] if protag_names_rows else names_rows[0]
        return _resolve(int(chosen["id"]), evidence_prefix="h3m_heroesNames")

    # Campaign-granted starts (no map hero / mainCustomHeroId): honor carry-policy
    # campaign.missionSpawns (or defaultSpawn via resolve_campaign_hub_spawn).
    from campaign_hub_spawn import resolve_campaign_hub_spawn

    hub_spawn = resolve_campaign_hub_spawn(mission.mission_id)
    if hub_spawn is not None:
        hero_sid = str(hub_spawn["heroSid"])
        return {
            "heroSid": hero_sid,
            "heroType": h3_hero_sid_to_hero_type(hero_sid),
            "evidence": "campaign.missionSpawns",
            "humanH3Owner": human_owner,
        }

    raise ValueError(
        f"{mission.mission_id}: cannot derive campaign spawn hero from H3M "
        f"(humanOwner={human_owner}; no concrete map hero / mainCustomHeroId). "
        "Set campaign.missionSpawns explicitly with H3C start-option evidence, "
        "or fix the alignment walk."
    )


def _walk_record_in_map_bounds(
    record: dict[str, Any],
    *,
    map_size: int | None,
) -> bool:
    """True when a walk/alignment record sits on an emit-able H3 cell (not border overhang)."""
    if not isinstance(map_size, int) or map_size <= 0:
        return True
    key = str(record.get("key") or record.get("sourceKey") or "")
    parts = key.split(":")
    if len(parts) >= 3:
        x = int(parts[1])
        y = int(parts[2])
    else:
        x = record.get("sourceX")
        y = record.get("sourceY")
        if not isinstance(x, int) or not isinstance(y, int):
            return True
    return 0 <= x < map_size and 0 <= y < map_size


def infer_start_hero_contract(mission: CampaignMission) -> dict[str, Any] | None:
    """Prefer an explicit manifest contract; otherwise pick the best surface hero from the walk.

    When the mission has no player hero (campaign-granted start), synthesize a contract
    anchored at a surface town. Prefer the H3M human-capable owner (not always red/0) —
    Specter Poison Fit (human blue) and Seeds ``the_grail`` (human purple) need this.
    """
    if mission.start_hero_contract is not None:
        return {
            key: value
            for key, value in mission.start_hero_contract.items()
            if not str(key).startswith("_")
        }
    if not mission.object_walk_path.exists():
        return None
    walk = json.loads(mission.object_walk_path.read_text(encoding="utf-8-sig"))
    human_owner = infer_human_h3_owner(mission)
    candidates: list[dict[str, Any]] = []
    for record in walk.get("records") or []:
        if record.get("syntheticHeader"):
            continue
        payload_kind = record.get("payloadKind")
        if payload_kind not in {"hero", "hero_or_prison", "hero_placeholder"}:
            continue
        # Empty AHplace slots (heroType 255 / template 214) are not playable starts;
        # treating them as the contract leaves raw emit with zero hero-spawners.
        hero_type = record.get("heroType")
        template_id = record.get("templateObjectId")
        if hero_type in (None, 255, 0xFF) or template_id == 214:
            continue
        candidates.append(record)
    if candidates:

        def sort_key(record: dict[str, Any]) -> tuple[int, int, int, int, int]:
            key = str(record.get("key") or "0:0:0")
            layer = int(key.split(":", 1)[0])
            owner = record.get("owner")
            if owner == human_owner:
                owner_rank = 0
            elif owner in (0, None):
                owner_rank = 1
            elif owner in (255, 0xFF):
                owner_rank = 3  # prison / neutral — last resort
            else:
                owner_rank = 2
            template_rank = 0 if record.get("templateObjectId") == 34 else 1
            payload_rank = 0 if record.get("payloadKind") in {"hero", "hero_placeholder"} else 1
            layer_rank = 0 if layer == 0 else 1
            return (owner_rank, layer_rank, template_rank, payload_rank, int(record.get("index", 0)))

        preferred = [row for row in candidates if row.get("owner") == human_owner]
        # Align start placement with spawn SID selection: when exactly one human
        # map hero remaps via display name (Yog on On the Run), that entity is
        # the start — not the lowest sourceIndex sibling. Prefer only in-bounds
        # anchors; overhang name_over_type heroes still win spawn.heroSid via
        # infer_campaign_spawn_hero_sid, but cannot be emit start tiles.
        if preferred:
            try:
                names_by_type = collect_campaign_chain_hero_names_by_type(mission)
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
                names_by_type = {}
            try:
                _layers, _underground, map_size = layer_ids_from_h3c(mission)
            except (OSError, ValueError, KeyError, TypeError):
                map_size = None
            name_over: list[dict[str, Any]] = []
            for row in preferred:
                hero_type = row.get("heroType")
                if not isinstance(hero_type, int):
                    continue
                _sid, tag = resolve_h3_hero_sid(
                    hero_type, name=names_by_type.get(hero_type)
                )
                if tag == "h3m_hero_name_over_type":
                    name_over.append(row)
            name_over_in_bounds = [
                row
                for row in name_over
                if _walk_record_in_map_bounds(row, map_size=map_size)
            ]
            if len(name_over_in_bounds) == 1:
                preferred = name_over_in_bounds
            elif len(name_over_in_bounds) > 1:
                raise ValueError(
                    f"{mission.mission_id}: multiple in-bounds human map heroes resolve "
                    f"via name_over_type for startHeroContract; refuse ambiguous start"
                )
            # If the only name_over_type hero is border overhang, keep the normal
            # in-bounds preferred pool for physical start (SID still comes from spawn).
        # Never adopt an enemy AI hero as the StoryHub start when the H3C human
        # color has no playable map hero — synthesize at a human town instead.
        # Owner 0 is only a valid fallback when H3C human is also red/0; otherwise
        # maps like A Gryphon's Heart (human teal/5, red Castle AI) wrongly bind
        # the player to Stonecastle.
        if not preferred:
            if human_owner in (0, None):
                owner0 = [row for row in candidates if row.get("owner") in (0, None)]
                if owner0:
                    record = sorted(owner0, key=sort_key)[0]
                else:
                    return _synthesize_start_at_owner0_town(mission, walk, human_owner=human_owner or 0)
            else:
                return _synthesize_start_at_owner0_town(mission, walk, human_owner=human_owner)
        else:
            record = sorted(preferred, key=sort_key)[0]
        key = str(record.get("key") or "0:0:0")
        layer = int(key.split(":", 1)[0])
        owner = record.get("owner", human_owner)
        # Prisons / neutral placeholders still bind the StoryHub human color.
        if owner in (None, 255, 0xFF):
            owner = human_owner
        return {
            "sourceLayer": layer,
            "heroType": record.get("heroType"),
            "owner": owner,
            "payloadKind": record.get("payloadKind"),
            "templateAnimation": record.get("templateAnimation"),
            "templateObjectId": record.get("templateObjectId"),
            "sourceKey": record.get("key"),
            "sourceIndex": record.get("index"),
        }

    return _synthesize_start_at_owner0_town(mission, walk, human_owner=human_owner)


def _synthesize_start_at_owner0_town(
    mission: CampaignMission,
    walk: dict[str, Any] | None = None,
    *,
    human_owner: int = 0,
) -> dict[str, Any] | None:
    """Campaign-granted start: no player hero on the H3M — anchor at mainTown.

    Prefer the H3M ``mainTown`` (entrance stored; town object is typically
    ``mainTown.x + 2`` on the same ``z`` layer) when ``generateHero`` is set.
    Underground starts (e.g. Groundbreaking ``z=1``) must be included — a
    surface-only scan previously missed the owned Dungeon and left a stale
    profile pointing at an enemy surface Tower.

    Otherwise prefer a town already owned by the human, then a neutral town,
    and only then an owner-0 town when the human color is also 0. Enemy AI
    towns are never chosen.
    """
    towns: list[dict[str, Any]] = []
    if mission.alignment_path.exists():
        alignment = json.loads(mission.alignment_path.read_text(encoding="utf-8-sig"))
        for entity in alignment.get("globalEntities") or []:
            if not isinstance(entity, dict):
                continue
            if entity.get("category") != "town":
                continue
            towns.append(entity)
    if not towns and walk is not None:
        for record in walk.get("records") or []:
            if record.get("payloadKind") != "town":
                continue
            towns.append(record)
    if not towns:
        return None

    main_town_key: str | None = None
    try:
        source = load_h3c_block(mission.campaign_entry, mission.block_index)
        header = h3m.decode_h3m_scenario_header(source.h3m_data)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        header = None
    if isinstance(header, dict):
        for player in header.get("players") or []:
            if not isinstance(player, dict) or int(player.get("index", -1)) != human_owner:
                continue
            main_town = player.get("mainTown")
            if not isinstance(main_town, dict) or not main_town.get("generateHero"):
                break
            # H3 stores the main-town entrance; the placed town object is two
            # cells east of that entrance (vanilla_stock / VCMI convention).
            town_x = int(main_town["x"]) + 2
            town_y = int(main_town["y"])
            town_z = int(main_town.get("z") or 0)
            main_town_key = f"{town_z}:{town_x}:{town_y}"
            break

    if main_town_key is not None:
        for row in towns:
            key = str(row.get("sourceKey") or row.get("key") or "")
            if key == main_town_key:
                town_layer = int(str(main_town_key).split(":", 1)[0])
                return _campaign_granted_start_contract(
                    mission,
                    source_layer=town_layer,
                    human_owner=human_owner,
                    source_key=main_town_key,
                    town_owner=row.get("owner"),
                    note=(
                        f"No player hero on map; H3M mainTown.generateHero entrance "
                        f"anchors campaign-granted start at town {main_town_key} "
                        f"(humanH3Owner={human_owner}; townOwner={row.get('owner')})."
                    ),
                )

    def town_sort(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
        owner = row.get("owner")
        if owner == human_owner:
            owner_rank = 0
        elif owner in (255, 0xFF):
            owner_rank = 1  # neutral — valid campaign-grant / ownership-reassign anchor
        elif owner in (0, None) and human_owner == 0:
            owner_rank = 2
        else:
            owner_rank = 3  # enemy AI towns are last-resort / usually invalid anchors
        key = str(row.get("sourceKey") or row.get("key") or "0:0:0")
        parts = key.split(":")
        layer = int(parts[0]) if len(parts) >= 3 else int(row.get("sourceLayer") or 0)
        x = int(parts[1]) if len(parts) >= 3 else 0
        y = int(parts[2]) if len(parts) >= 3 else 0
        return (owner_rank, layer, x, y, int(row.get("sourceIndex") or row.get("index") or 0))

    preferred = [row for row in towns if row.get("owner") == human_owner]
    neutrals = [row for row in towns if row.get("owner") in (255, 0xFF)]
    owner0 = [
        row
        for row in towns
        if row.get("owner") in (0, None) and human_owner == 0
    ]
    pool = preferred or neutrals or owner0
    if not pool:
        return None
    town = sorted(pool, key=town_sort)[0]
    source_key = str(town.get("sourceKey") or town.get("key"))
    parts = source_key.split(":")
    source_layer = int(parts[0]) if len(parts) >= 3 else int(town.get("sourceLayer") or 0)
    return _campaign_granted_start_contract(
        mission,
        source_layer=source_layer,
        human_owner=human_owner,
        source_key=source_key,
        town_owner=town.get("owner"),
        note=(
            f"No player hero on map; raw_translation synthesizes campaign-granted start "
            f"at town {source_key} (humanH3Owner={human_owner}; townOwner={town.get('owner')})."
        ),
    )


def _campaign_granted_start_contract(
    mission: CampaignMission,
    *,
    source_layer: int,
    human_owner: int,
    source_key: str,
    town_owner: Any,
    note: str,
) -> dict[str, Any]:
    """Town-anchored start contract using the derived spawn heroType (never Christian/6)."""
    del town_owner  # diagnostic only via note
    try:
        derived = infer_campaign_spawn_hero_sid(mission)
        hero_type = int(derived["heroType"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"{mission.mission_id}: campaign-granted town start at {source_key!r} "
            f"requires a derivable spawn heroType (not hardcoded Christian/6): {exc}"
        ) from exc
    return {
        "sourceLayer": source_layer,
        "heroType": hero_type,
        "owner": human_owner,
        "payloadKind": "hero_or_prison",
        "templateAnimation": "ah00_e.def",
        "templateObjectId": 34,
        "sourceKey": source_key,
        "campaignGranted": True,
        "_note": note,
    }


def layer_ids_from_h3c(mission: CampaignMission) -> tuple[tuple[int, ...], frozenset[int], int]:
    """Return (layer_ids, underground_layers, size) from the H3C block summary."""
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    size = int(source.summary.size)
    layer_count = int(source.summary.layers)
    layer_ids = tuple(range(layer_count))
    underground = frozenset(layer_ids[1:]) if layer_count > 1 else frozenset()
    return layer_ids, underground, size


def expected_layer_entity_counts(mission: CampaignMission) -> dict[int, int] | None:
    """Prefer port-manifest layerCounts, then alignment globalEntities, then manifest pins."""
    if mission.object_port_manifest_path.exists():
        manifest = json.loads(mission.object_port_manifest_path.read_text(encoding="utf-8-sig"))
        layer_counts = manifest.get("layerCounts")
        if isinstance(layer_counts, dict) and layer_counts:
            return {int(key): int(value) for key, value in sorted(layer_counts.items())}

    if mission.alignment_path.exists():
        alignment = json.loads(mission.alignment_path.read_text(encoding="utf-8-sig"))
        entities = alignment.get("globalEntities") or []
        if isinstance(entities, list) and entities:
            counts: dict[int, int] = {}
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                layer = entity.get("sourceLayer")
                if isinstance(layer, int):
                    counts[layer] = counts.get(layer, 0) + 1
            if counts:
                return {key: counts[key] for key in sorted(counts)}

    if mission.validation_expected_layer_counts:
        return dict(sorted(mission.validation_expected_layer_counts.items()))
    return None


def map_sid_to_raw_translation(map_sid: str) -> str:
    """Normalize a manifest mapSid to the shipped raw_translation SID.

    Manifests now declare `*_raw_translation` directly; this stays idempotent so a
    manifest that omits the suffix still resolves to the shipped SID.
    """
    if map_sid.endswith("_raw_translation"):
        return map_sid
    return f"{map_sid}_raw_translation"


def title_to_raw_translation(title: str) -> str:
    if title.endswith(" - Raw Translation"):
        return title
    return f"{title} - Raw Translation"
