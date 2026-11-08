#!/usr/bin/env python3
"""Emit the RoE Castle Good1 StoryHub continuity weave.

Native StoryHub graph for Homecoming → Guardian Angels → Griffin Cliff with
transferHeroProgressFromSession enabled. Install into Core.zip is a separate
opt-in step (tools/install_roe_castle_continuity_weave.py).

Proof boundary: generated-artifact. Runtime hero writeback remains unvalidated.
Does not mutate Plugin.CreateHomecomingPlayableShellCampaignInfo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BATCH_MANIFEST = ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json"
CARRY_POLICY_GOOD1 = ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy.v1.json"
CARRY_POLICY_GOOD2 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_good2.v1.json"
)
CARRY_POLICY_GOOD3 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_good3.v1.json"
)
CARRY_POLICY_EVIL2 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_evil2.v1.json"
)
CARRY_POLICY_EVIL1 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_evil1.v1.json"
)
CARRY_POLICY_SECRET = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_secret.v1.json"
)
CARRY_POLICY_SECRET1 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_secret1.v1.json"
)
CARRY_POLICY_NEUTRAL1 = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy_neutral1.v1.json"
)
BONUS_DIFFICULTY_POLICY = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_bonus_difficulty.v1.json"
)
DEFAULT_OUT_GOOD1 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_castle_campaign"
    / "continuity_weave"
)
DEFAULT_OUT_GOOD2 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_castle_campaign"
    / "continuity_weave_good2"
)
DEFAULT_OUT_GOOD3 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_good3"
)
DEFAULT_OUT_EVIL2 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_evil2"
)
DEFAULT_OUT_EVIL1 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_evil1"
)
DEFAULT_OUT_SECRET = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_secret"
)
DEFAULT_OUT_SECRET1 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_secret1"
)
DEFAULT_OUT_NEUTRAL1 = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_remaining_campaigns"
    / "continuity_weave_neutral1"
)

# Mirror mainStory Start Phase Mission 1 difficulty rows (indices 0-3).
# Impossible (index 4) stays unavailable — HoMM3 RoE exposes four difficulties.
#
# ai.script MUST be a real DB/ai_world AiConfig id. Empty "" resolves to
# Config id "" not found → fjl(AiConfig) NRE → Hex.Session.Loader.lqo retries
# every Update (hang + unbounded memory). Native Start Phase Mission 1 uses
# campaign_M1; Bot missions (M2+) use non-empty campaign_* scripts too.
NATIVE_AI_SCRIPT = "campaign_M1"
NATIVE_DIFFICULTY_ROWS: tuple[dict[str, Any], ...] = (
    {
        "index": 0,
        "neutralPowerMultiplier": 0.4,
        "guardPowerMultiplier": 0.4,
        "neutralExpMultiplier": 2.25,
        "ai": {
            "script": NATIVE_AI_SCRIPT,
            "battleScript": "normal",
            "buildTag": "supereasy",
            "resourceAddPercent": 0.5,
            "tempStacksMultiplier": 0.5,
            "valuesVsMobsMultiplier": 1.0,
            "blockAreaByEnemyMultiplier": 1.0,
            "buildingColdown": 2,
        },
    },
    {
        "index": 1,
        "neutralPowerMultiplier": 0.8,
        "guardPowerMultiplier": 0.8,
        "neutralExpMultiplier": 1.125,
        "ai": {
            "script": NATIVE_AI_SCRIPT,
            "battleScript": "normal",
            "buildTag": "easy",
            "resourceAddPercent": 0.5,
            "tempStacksMultiplier": 0.5,
            "valuesVsMobsMultiplier": 1.0,
            "blockAreaByEnemyMultiplier": 1.0,
            "buildingColdown": 1,
        },
    },
    {
        "index": 2,
        "neutralPowerMultiplier": 1.125,
        "guardPowerMultiplier": 1.125,
        "neutralExpMultiplier": 0.8,
        "ai": {
            "script": NATIVE_AI_SCRIPT,
            "battleScript": "hard",
            "buildTag": "normal",
            "resourceAddPercent": 0.75,
            "tempStacksMultiplier": 0.75,
            "valuesVsMobsMultiplier": 1.0,
            "blockAreaByEnemyMultiplier": 1.0,
        },
    },
    {
        "index": 3,
        "neutralPowerMultiplier": 1.5,
        "guardPowerMultiplier": 1.5,
        "neutralExpMultiplier": 0.6,
        "ai": {
            "script": NATIVE_AI_SCRIPT,
            "battleScript": "hard",
            "buildTag": "normal",
            "resourceAddPercent": 1.0,
            "tempStacksMultiplier": 1.0,
            "valuesVsMobsMultiplier": 1.0,
            "blockAreaByEnemyMultiplier": 1.0,
        },
    },
)

RESOURCE_FIELD_KEYS: tuple[str, ...] = (
    "gold",
    "wood",
    "ore",
    "gemstones",
    "crystals",
    "mercury",
    "alchemicalDust",
)

EMPTY_RESOURCES = {key: 0 for key in RESOURCE_FIELD_KEYS}


def starting_resources_table(bonus_difficulty: dict[str, Any]) -> dict[int, dict[str, dict[str, int]]]:
    """Return index → {playerStartResources, aiStartResources} from continuity policy."""
    block = bonus_difficulty.get("startingResources")
    if not isinstance(block, dict):
        fail(f"{BONUS_DIFFICULTY_POLICY} must declare startingResources")
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        fail(f"{BONUS_DIFFICULTY_POLICY} startingResources.rows must be a non-empty list")
    out: dict[int, dict[str, dict[str, int]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            fail("startingResources.rows entries must be objects")
        index = row.get("index")
        if not isinstance(index, int) or index < 0 or index > 3:
            fail(f"startingResources row has invalid index {index!r} (expected 0-3)")
        economic: dict[str, dict[str, int]] = {}
        for field in ("playerStartResources", "aiStartResources"):
            resources = row.get(field)
            if not isinstance(resources, dict):
                fail(f"startingResources[{index}] missing {field}")
            normalized: dict[str, int] = {}
            for key in RESOURCE_FIELD_KEYS:
                value = resources.get(key)
                if not isinstance(value, int) or value < 0:
                    fail(
                        f"startingResources[{index}].{field}.{key} must be a non-negative int; "
                        f"got {value!r}"
                    )
                normalized[key] = value
            economic[field] = normalized
        out[index] = economic
    missing = sorted(set(range(4)) - set(out))
    if missing:
        fail(f"startingResources must cover indices 0-3; missing {missing}")
    return out
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
MAPS_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps" / "Story_maps"

SCHEMA = "homm3.olden_campaign_continuity_weave.v1"
HUB_SID_GOOD1 = "homm3_01_roe_castle_good1"
HUB_SID_GOOD2 = "homm3_02_roe_castle_good2"
HUB_SID_GOOD3 = "homm3_03_roe_castle_good3"
HUB_SID_EVIL2 = "homm3_05_roe_necropolis_evil2"
HUB_SID_EVIL1 = "homm3_04_roe_dungeon_evil1"
HUB_SID_SECRET = "homm3_08_roe_necropolis_secret"
HUB_SID_SECRET1 = "homm3_07_roe_rampart_secret1"
HUB_SID_NEUTRAL1 = "homm3_06_roe_neutral_neutral1"

# Mutable hub context — set in main() from carry policy before build_weave.
MISSION_CONFIG_PREFIX = "homm3_roe_castle"
DEFAULT_FACTION_SID = "homm3_castle"
DEFAULT_HERO_SID = "homm3_castle_hero_7"
# Per-mission spawn overrides from campaign.missionSpawns (fallback: defaultSpawn).
# Keys are missionId; values are {"heroSid", "factionSid"}.
MISSION_SPAWNS: dict[str, dict[str, str]] = {}

# BhFractionsReputation.Init requires fractions.json length to match the fixed
# StoryHub UI slot array (native hubs always ship these six). Mismatch logs
# Critical Error then Interrupt — hard crash on hub enter even when
# showReputationPanel is false.
NATIVE_STORYHUB_FRACTIONS: tuple[tuple[str, str], ...] = (
    ("human", "fractionReputation_Human"),
    ("undead", "fractionReputation_Undead"),
    ("unfrozen", "fractionReputation_Unfrozen"),
    ("nature", "fractionReputation_Nature"),
    ("dungeon", "fractionReputation_Dungeon"),
    ("demon", "fractionReputation_Demon"),
)

MISSION_TITLES = {
    "homecoming": "Homecoming",
    "guardian_angels": "Guardian Angels",
    "griffin_cliff": "Griffin Cliff",
    "steadwick_liberation": "Steadwick's Liberation",
    "deal_with_the_devil": "Deal With the Devil",
    "neutral_affairs": "Neutral Affairs",
    "tunnels_and_troglodytes": "Tunnels and Troglodytes",
    "safe_passage": "Safe Passage",
    "united_front": "United Front",
    "for_king_and_country": "For King and Country",
    "a_gryphons_heart": "A Gryphon's Heart",
    "season_of_harvest": "Season of Harvest",
    "corporeal_punishment": "Corporeal Punishment",
    "from_day_to_night": "From Day to Night",
    "a_devilish_plan": "A Devilish Plan",
    "groundbreaking": "Groundbreaking",
    "steadwicks_fall": "Steadwick's Fall",
    "poison_fit_for_a_king": "Poison Fit for a King",
    "to_build_a_tunnel": "To Build a Tunnel",
    "kreegan_alliance": "Kreegan Alliance",
    "with_blinders_on": "With Blinders On",
    "the_grail": "The Grail",
    "independence": "Independence",
    "the_road_home": "The Road Home",
    "neutral_1a": "Borderlands",
    "neutral_1b": "Gold Rush",
    "neutral_1c": "Greed",
}
MISSION_DESCRIPTIONS = {
    "homecoming": (
        "Queen Catherine has returned to Erathia. Secure the homeland and prepare "
        "your heroes for the battles ahead. Heroes are limited to level 6; your "
        "strongest will carry forward."
    ),
    "guardian_angels": (
        "Continue the Restoration of Erathia. Heroes carried from Homecoming should "
        "retain level and sheet progress when transferHeroProgressFromSession is honored."
    ),
    "griffin_cliff": (
        "Final Good1 mission. Confirm carried hero progress still matches the hub save."
    ),
    "steadwick_liberation": (
        "Liberate Steadwick from Nighon and Eeofol. Capture the capital; a Seer quest "
        "may grant a carry reward into later Liberation scenarios."
    ),
    "deal_with_the_devil": (
        "Invade Eeofol and capture Kleesive. Campaign-granted start at the western Castle "
        "when the H3M embeds no player hero."
    ),
    "neutral_affairs": (
        "Defeat Tatalia and Krewlod forces fighting in western Erathia. Capture all "
        "enemy towns and defeat all enemy heroes."
    ),
    "tunnels_and_troglodytes": (
        "Force Nighon and Eeofol back through the coastal tunnels. Capture all enemy "
        "towns and defeat all enemy heroes."
    ),
    "safe_passage": (
        "Escort Nimbus to Highcastle with the Statesman's Medal. Your strongest heroes "
        "carry forward into United Front."
    ),
    "united_front": (
        "Capture all enemy towns and defeat all enemy heroes. Your strongest heroes "
        "carry into For King and Country."
    ),
    "for_king_and_country": (
        "Final Song for the Father battle. Capture all enemy towns without losing "
        "Queen Catherine or Lord Haart."
    ),
    "a_gryphons_heart": (
        "Bring the Spirit of Oppression to Stonecastle. Seer quest artifacts may carry "
        "into later Long Live the King scenarios."
    ),
    "season_of_harvest": (
        "Raise 2500 Skeletons across your armies. Border Guards may require prior "
        "quest artifacts."
    ),
    "corporeal_punishment": (
        "Defeat the Death Knight Mot. Border Guards may require prior quest artifacts."
    ),
    "from_day_to_night": (
        "Final Long Live the King mission. Capture all enemy towns and defeat all "
        "enemy heroes."
    ),
    "a_devilish_plan": (
        "Find and kill the Gold Dragon Queen. Heroes are limited to level 12; your "
        "strongest carry into Groundbreaking."
    ),
    "groundbreaking": (
        "Capture all enemy towns and defeat all enemy heroes. Pandora mana/morale/luck "
        "deltas are omitted at alignment (explicit gap)."
    ),
    "steadwicks_fall": (
        "Capture Steadwick within 3 months. Final Dungeons and Devils mission."
    ),
    "poison_fit_for_a_king": (
        "Capture Haart Castle and leave the Vial of Poison. Sandro must survive; "
        "heroes limited to level 10 with strongest carrying forward."
    ),
    "to_build_a_tunnel": (
        "Obtain 100,000 Gold for the Dungeon Overlords. Sandro must survive; "
        "heroes limited with strongest carrying into Kreegan Alliance."
    ),
    "kreegan_alliance": (
        "Obtain the Eversmoking Ring of Sulfur for the Kreegans. Sandro must survive; "
        "strongest heroes carry into With Blinders On."
    ),
    "with_blinders_on": (
        "Final Specter of Power mission. Sandro must defeat all rival lords without "
        "losing a battle."
    ),
    "the_grail": (
        "Find the Grail within 2 months. First Seeds of Discontent mission."
    ),
    "independence": (
        "Build a Capitol in Welnin so the Contested Lands are free."
    ),
    "the_road_home": (
        "Ryland must reach Welnin with the Grail and give it a permanent home."
    ),
    "neutral_1a": (
        "Flag all mines. Heroes limited to level 12; strongest carry toward the "
        "final Spoils of War scenario."
    ),
    "neutral_1b": (
        "Accumulate 200,000 gold. Heroes limited to level 12; strongest carry into Greed."
    ),
    "neutral_1c": (
        "Capture all towns and defeat all enemy heroes. Final Spoils of War mission."
    ),
}

# HoMM3 Long Live the Queen region anchors from VCMI config/campaignRegions.json
# "good1" (CAMPBACK / G1_BG pixel space, top-left origin). CampText names:
# Southport / Angel Gate / Gryphon Cliff. Mapped into the observed native StoryHub
# node localPosition envelope (mainStory / tutorial_challenges), Y flipped so
# southern HoMM3 pixels sit lower in Olden UI space. Relative triangle preserved;
# absolute geography still sits on Olden's shared Unity scroll background until a
# G1_BG injection bridge exists (storyHub.json has no background field).
HOMM3_GOOD1_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "homecoming": (57.0, 314.0),
    "guardian_angels": (137.0, 309.0),
    "griffin_cliff": (44.0, 163.0),
}
# VCMI config/campaignRegions.json "good2" (G2_BG pixel space).
HOMM3_GOOD2_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "steadwick_liberation": (56.0, 90.0),
    "deal_with_the_devil": (316.0, 49.0),
    "neutral_affairs": (54.0, 378.0),
    "tunnels_and_troglodytes": (151.0, 126.0),
}
# VCMI config/campaignRegions.json "good3" (G3_BG pixel space).
HOMM3_GOOD3_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "safe_passage": (289.0, 376.0),
    "united_front": (60.0, 147.0),
    "for_king_and_country": (131.0, 202.0),
}
# VCMI config/campaignRegions.json "evil2" (E2_BG pixel space).
HOMM3_EVIL2_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "a_gryphons_heart": (131.0, 202.0),
    "season_of_harvest": (60.0, 145.0),
    "corporeal_punishment": (92.0, 261.0),
    "from_day_to_night": (218.0, 307.0),
}
# VCMI config/campaignRegions.json "evil1" (E1_BG) — mission pins A/B/C only.
HOMM3_EVIL1_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "a_devilish_plan": (270.0, 332.0),
    "groundbreaking": (138.0, 113.0),
    "steadwicks_fall": (26.0, 70.0),
}
# VCMI config/campaignRegions.json "spectreOfPower" (SP_BG pixel space).
# Hub MapImage uses dedicated SP_BG bake (see storyhub_map_background.DEFAULT_HUBS).
HOMM3_SECRET_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "poison_fit_for_a_king": (7.0, 295.0),
    "to_build_a_tunnel": (44.0, 141.0),
    "kreegan_alliance": (141.0, 21.0),
    "with_blinders_on": (243.0, 156.0),
}
# VCMI config/campaignRegions.json "secret1" (S1_BG pixel space).
HOMM3_SECRET1_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "the_grail": (263.0, 199.0),
    "independence": (182.0, 210.0),
    "the_road_home": (82.0, 152.0),
}
# VCMI config/campaignRegions.json "neutral1" (N1_BG) — CD is the final pin.
HOMM3_NEUTRAL1_REGION_PIXELS: dict[str, tuple[float, float]] = {
    "neutral_1a": (42.0, 94.0),
    "neutral_1b": (309.0, 290.0),
    "neutral_1c": (188.0, 202.0),
}
STORYHUB_NODE_POS_X_RANGE = (-400.0, -100.0)
STORYHUB_NODE_POS_Y_RANGE = (80.0, -120.0)


def fail(message: str) -> None:
    raise SystemExit(message)


def load_json(path: Path) -> Any:
    if not path.is_file():
        fail(f"missing required JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mission_by_id(batch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    missions = batch.get("missions")
    if not isinstance(missions, list) or not missions:
        fail(f"{BATCH_MANIFEST}: missions[] missing")
    out: dict[str, dict[str, Any]] = {}
    for row in missions:
        if not isinstance(row, dict) or "missionId" not in row:
            fail(f"{BATCH_MANIFEST}: mission row missing missionId")
        out[str(row["missionId"])] = row
    return out


def mission_config_id(mission_id: str) -> str:
    return f"{MISSION_CONFIG_PREFIX}_{mission_id}"


def node_sid(mission_id: str) -> str:
    return f"{MISSION_CONFIG_PREFIX}_node_{mission_id}"


def resolve_map_sid(mission_id: str, batch_row: dict[str, Any], policy: dict[str, Any]) -> str:
    overrides = policy.get("storyHubMapSidOverrides") or {}
    override = overrides.get(mission_id)
    if isinstance(override, str) and override.strip():
        return override.strip()
    map_sid = batch_row.get("mapSid")
    if not isinstance(map_sid, str) or not map_sid:
        fail(f"batch mission {mission_id} missing mapSid")
    return map_sid


def map_file_ready(map_sid: str, maps_dir: Path, repo_root: Path) -> tuple[bool, str]:
    installed = maps_dir / f"{map_sid}.map"
    if installed.is_file() and installed.stat().st_size > 0:
        return True, f"installed:{installed.as_posix()}"
    mission_roots = (
        "homecoming_poc",
        "guardian_angels",
        "griffin_cliff",
        "steadwick_liberation",
        "deal_with_the_devil",
        "neutral_affairs",
        "tunnels_and_troglodytes",
    )
    candidates: list[Path] = []
    for root_name in mission_roots:
        base = (
            repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc"
            if root_name == "homecoming_poc"
            else repo_root
            / "artifacts"
            / "campaign_port_poc"
            / "roe_castle_campaign"
            / root_name
        )
        candidates.append(base / "raw_translation_map" / "maps" / f"{map_sid}.map")
    # Remaining RoE arcs (Good3 / Evil1 / Evil2 / …) live under roe_remaining_campaigns.
    remaining_root = repo_root / "artifacts" / "campaign_port_poc" / "roe_remaining_campaigns"
    if remaining_root.is_dir():
        for mission_dir in remaining_root.iterdir():
            if not mission_dir.is_dir():
                continue
            candidates.append(mission_dir / "raw_translation_map" / "maps" / f"{map_sid}.map")
    # AB + SoD arcs live under ab_sod_campaigns.
    ab_sod_root = repo_root / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns"
    if ab_sod_root.is_dir():
        for mission_dir in ab_sod_root.iterdir():
            if not mission_dir.is_dir():
                continue
            candidates.append(mission_dir / "raw_translation_map" / "maps" / f"{map_sid}.map")
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return True, f"artifact:{path.as_posix()}"
    return False, "missing"


def raw_translation_manifest_path(repo_root: Path, mission_id: str) -> Path | None:
    roots = {
        "homecoming": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "homecoming_poc"
        / "raw_translation_map"
        / "install_manifest.json",
        "guardian_angels": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "guardian_angels"
        / "raw_translation_map"
        / "install_manifest.json",
        "griffin_cliff": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "griffin_cliff"
        / "raw_translation_map"
        / "install_manifest.json",
        "steadwick_liberation": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "steadwick_liberation"
        / "raw_translation_map"
        / "install_manifest.json",
        "deal_with_the_devil": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "deal_with_the_devil"
        / "raw_translation_map"
        / "install_manifest.json",
        "neutral_affairs": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "neutral_affairs"
        / "raw_translation_map"
        / "install_manifest.json",
        "tunnels_and_troglodytes": repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "tunnels_and_troglodytes"
        / "raw_translation_map"
        / "install_manifest.json",
    }
    path = roots.get(mission_id)
    if path is not None and path.is_file():
        return path
    remaining = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_remaining_campaigns"
        / mission_id
        / "raw_translation_map"
        / "install_manifest.json"
    )
    if remaining.is_file():
        return remaining
    ab_sod = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "ab_sod_campaigns"
        / mission_id
        / "raw_translation_map"
        / "install_manifest.json"
    )
    if ab_sod.is_file():
        return ab_sod
    return None


def _assert_manifest_scenario_players_match_map(
    repo_root: Path, mission_id: str, manifest: dict[str, Any]
) -> None:
    """Fail-closed: weave sides must not bind stale install_manifest owners."""
    output = manifest.get("output") if isinstance(manifest.get("output"), dict) else {}
    rel = str(output.get("map") or "").strip()
    if not rel:
        fail(f"{mission_id}: install_manifest missing output.map")
    map_path = (repo_root / rel).resolve()
    if not map_path.is_file():
        fail(f"{mission_id}: raw_translation map missing at {map_path}")
    tools = repo_root / "tools"
    import sys

    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from map_load_preflight import read_map_owners

    map_owners = sorted(read_map_owners(map_path))
    players = manifest.get("scenarioPlayers") or {}
    manifest_owners = sorted(int(o) for o in (players.get("oldenOwners") or []))
    human = players.get("humanOldenOwner")
    if manifest_owners != map_owners:
        fail(
            f"{mission_id}: install_manifest scenarioPlayers.oldenOwners {manifest_owners} "
            f"!= map owners {map_owners}; regenerate raw_translation map+manifest together"
        )
    if human is None or int(human) not in map_owners:
        fail(
            f"{mission_id}: install_manifest humanOldenOwner {human!r} not in map owners "
            f"{map_owners}"
        )


def human_player_side_from_raw_manifest(
    repo_root: Path,
    mission_id: str,
    *,
    default_fraction_sid: str,
) -> dict[str, Any]:
    """Player side spawn follows raw_translation humanOldenOwner (compact scheme: always 1)."""
    spawn = 1
    fraction_sid = default_fraction_sid
    manifest_path = raw_translation_manifest_path(repo_root, mission_id)
    if manifest_path is None:
        return {"type": "Player", "fractionSid": fraction_sid, "spawns": [spawn]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    _assert_manifest_scenario_players_match_map(repo_root, mission_id, manifest)
    players = manifest.get("scenarioPlayers") or {}
    human = players.get("humanOldenOwner")
    if human is not None:
        spawn = int(human)
    reports = players.get("ownerReports") or {}
    report = reports.get(str(spawn)) if isinstance(reports, dict) else None
    if isinstance(report, dict):
        faction = str(report.get("factionSid") or "").strip()
        if faction:
            fraction_sid = faction
    return {"type": "Player", "fractionSid": fraction_sid, "spawns": [spawn]}


def bot_sides_from_raw_manifest(repo_root: Path, mission_id: str) -> list[dict[str, Any]]:
    """Derive StoryHub Bot sides from raw_translation scenarioPlayerSpawns.

    Every mission (including Homecoming) emits one Bot per non-human olden owner
    from ownerReports.factionSid. Owners are the map's final compact numbering
    (human=1, AI=2..N via renumber_map_owners_to_native_compact); hardcoding
    Homecoming Castle@3 / Dungeon@4 here would desync from regenerated maps.
    Xyron (Inferno hero) still binds via propHeroes; Homm3CampaignSpawnParityHook
    fills Bot campaignSpawns.heroSid at runtime.
    """
    manifest_path = raw_translation_manifest_path(repo_root, mission_id)
    if manifest_path is None:
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    players = manifest.get("scenarioPlayers") or {}
    human = players.get("humanOldenOwner")
    reports = players.get("ownerReports") or {}
    sides: list[dict[str, Any]] = []
    for owner_key, report in sorted(reports.items(), key=lambda item: int(item[0])):
        owner = int(owner_key)
        if human is not None and owner == int(human):
            continue
        faction = str((report or {}).get("factionSid") or "")
        if not faction:
            fail(
                f"{mission_id} raw_translation ownerReports[{owner}] missing factionSid; "
                "cannot build StoryHub Bot side"
            )
        sides.append({"type": "Bot", "fractionSid": faction, "spawns": [owner]})
    return sides


def _probe_native_canvas_mp4(mp4_path: Path) -> tuple[bool, str, dict[str, Any]]:
    """Return (ok, reason, probe_summary). Missing/undersized → not ok (fail-closed)."""
    from campaign_video_clip import mp4_meets_native_canvas, probe_mp4

    if not mp4_path.is_file():
        return False, "mp4 missing", {"present": False, "path": str(mp4_path)}
    probe = probe_mp4(mp4_path)
    summary = {
        "present": True,
        "path": str(mp4_path),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "duration_sec": probe.get("duration_sec"),
        "has_audio": probe.get("has_audio"),
        "filesize": probe.get("filesize"),
        "probeMethod": probe.get("probeMethod"),
    }
    ok, reason = mp4_meets_native_canvas(probe)
    return ok, reason, summary


def _mission_clip_ready(
    mp4_path: Path, clip_key: str, video: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    """Canvas + optional composed narration/audio contract for mission PlayVideo."""
    ok, reason, summary = _probe_native_canvas_mp4(mp4_path)
    if not ok:
        return ok, reason, summary
    if not video.get("requireComposedAudio"):
        return True, "ok", summary
    from campaign_video_compose import composed_mp4_meets_contract, ensure_composed_recipe
    from campaign_video_clip import probe_mp4

    recipe = ensure_composed_recipe(clip_key)
    if recipe is None or not recipe.is_composable:
        return False, f"{clip_key} is not a composable mission cutscene recipe", summary
    probe = probe_mp4(mp4_path)
    composed_ok, composed_reason = composed_mp4_meets_contract(probe, recipe)
    if not composed_ok:
        return False, composed_reason, summary
    sidecar = mp4_path.with_suffix(mp4_path.suffix + ".json")
    if not sidecar.is_file():
        return False, f"softsub sidecar missing: {sidecar}", summary
    summary["sidecarPresent"] = True
    return True, "ok", summary


def resolve_video_first_show_actions(
    policy: dict[str, Any], *, game_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Emit hub PlayVideo only when policy opts in and a native-canvas MP4 exists.

    Good1 sets hubFirstShowPlayVideo=false: Cgood1 is a hover-menu clip used as the
    campaign selection still (mainIconSid), not a full hub intro. Undersized encodes
    also block wiring so StoryHub does not flash a broken clip.
    """
    video = policy.get("videoContract") if isinstance(policy.get("videoContract"), dict) else {}
    clip_key = str(video.get("hubFirstShowClipKey") or "Cgood1")
    relative = str(video.get("requiredMp4RelativeToStreamingAssets") or f"video/{clip_key}.mp4")
    mp4_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / relative.replace("\\", "/")
    report: dict[str, Any] = {
        "clipKey": clip_key,
        "requiredMp4": str(mp4_path),
        "mp4Present": mp4_path.is_file(),
        "hubFirstShowPlayVideo": video.get("hubFirstShowPlayVideo", True),
        "hdEditionSources": list(video.get("hdEditionSources") or []),
        "transcodeRequirement": video.get("transcodeRequirement"),
    }
    if video.get("hubFirstShowPlayVideo") is False:
        report["status"] = "omitted_selection_still_only"
        report["omitReason"] = video.get("hubFirstShowOmitReason") or (
            "hubFirstShowPlayVideo false; clip reserved for selection still"
        )
        report["firstShowActions"] = []
        return [], report
    ok, reason, probe = _probe_native_canvas_mp4(mp4_path)
    report["mp4Probe"] = probe
    if not mp4_path.is_file():
        report["status"] = "blocked_missing_mp4"
        report["firstShowActions"] = []
        return [], report
    if not ok:
        report["status"] = "blocked_undersized_mp4"
        report["blockReason"] = reason
        report["firstShowActions"] = []
        return [], report
    actions = [{"type": "PlayVideo", "values": [clip_key]}]
    report["status"] = "wired_playvideo"
    report["firstShowActions"] = actions
    return actions, report


def resolve_mission_interaction_actions(
    mission_id: str,
    policy: dict[str, Any],
    *,
    game_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serial pin actions: optional PlayVideo (mission clip), then OpenMissionsPrologue.

    Matches native StoryHub action-queue ordering (PlayVideo completes before the next
    action). Does not overlap the Loader — video plays before the mission load UI.
    PlayVideo is omitted when the MP4 is missing, undersized, or fails the composed
    narration contract when requireComposedAudio is set.
    """
    mission_cfg_id = mission_config_id(mission_id)
    video = policy.get("videoContract") if isinstance(policy.get("videoContract"), dict) else {}
    clip_map = video.get("missionClipKeys") if isinstance(video.get("missionClipKeys"), dict) else {}
    clip_key = clip_map.get(mission_id)
    report: dict[str, Any] = {
        "missionId": mission_id,
        "clipKey": clip_key,
        "actionOrder": "PlayVideo_then_OpenMissionsPrologue",
    }
    actions: list[dict[str, Any]] = []
    if isinstance(clip_key, str) and clip_key.strip():
        clip_key = clip_key.strip()
        mp4_path = (
            game_root
            / "HeroesOldenEra_Data"
            / "StreamingAssets"
            / "video"
            / f"{clip_key}.mp4"
        )
        report["requiredMp4"] = str(mp4_path)
        report["mp4Present"] = mp4_path.is_file()
        ok, reason, probe = _mission_clip_ready(mp4_path, clip_key, video)
        report["mp4Probe"] = probe
        if not mp4_path.is_file():
            report["playVideoStatus"] = "blocked_missing_mp4"
        elif not ok:
            report["playVideoStatus"] = "blocked_uncomposed_or_undersized_mp4"
            report["blockReason"] = reason
        else:
            actions.append({"type": "PlayVideo", "values": [clip_key]})
            report["playVideoStatus"] = "wired_playvideo"
    else:
        report["playVideoStatus"] = "no_clip_key_in_policy"
    actions.append({"type": "OpenMissionsPrologue", "values": [mission_cfg_id]})
    report["interactionActions"] = actions
    return actions, report


def _fit_range(value: float, src_min: float, src_max: float, dst_a: float, dst_b: float) -> float:
    if src_max == src_min:
        return (dst_a + dst_b) / 2.0
    t = (value - src_min) / (src_max - src_min)
    return dst_a + t * (dst_b - dst_a)


def map_region_to_storyhub_pos(
    mission_id: str, region_pixels: dict[str, tuple[float, float]]
) -> tuple[float, float, float]:
    if mission_id not in region_pixels:
        fail(f"missing HoMM3 region pixel for mission {mission_id}")
    xs = [xy[0] for xy in region_pixels.values()]
    ys = [xy[1] for xy in region_pixels.values()]
    px, py = region_pixels[mission_id]
    pos_x = round(
        _fit_range(px, min(xs), max(xs), STORYHUB_NODE_POS_X_RANGE[0], STORYHUB_NODE_POS_X_RANGE[1]),
        1,
    )
    # Invert Y: larger HoMM3 pixel Y is further south / lower on CAMPBACK.
    pos_y = round(
        _fit_range(py, min(ys), max(ys), STORYHUB_NODE_POS_Y_RANGE[0], STORYHUB_NODE_POS_Y_RANGE[1]),
        1,
    )
    return pos_x, pos_y, 0.0


def build_story_hub(
    chain: list[str],
    policy: dict[str, Any],
    *,
    hub_sid: str,
    region_pixels: dict[str, tuple[float, float]],
    game_root: Path,
    first_show_actions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    mission_video_reports: list[dict[str, Any]] = []
    # Heroes available at campaign open (first mission spawn). Later protagonists
    # unlock via UnlockHero when the previous mission completes — native mainStory
    # pattern (omit isAvailableAtStart + UnlockHero onDone).
    unlocked_heroes: set[str] = set()
    if chain:
        first_hero, _ = spawn_for_mission(chain[0])
        if first_hero:
            unlocked_heroes.add(first_hero)
    for index, mission_id in enumerate(chain):
        mission_cfg_id = mission_config_id(mission_id)
        next_id = chain[index + 1] if index + 1 < len(chain) else None
        on_done: list[dict[str, str | list[str]]] = [
            {"type": "SetCounterValue", "values": [f"{mission_cfg_id}_Completed", "1"]},
            {"type": "changeNodeState", "values": [node_sid(mission_id), "Completed"]},
        ]
        if next_id is not None:
            next_hero, _ = spawn_for_mission(next_id)
            # Native mainStory unlocks later roster heroes on prior-node onDone
            # (UnlockHero) before the next node activates. Keep that order.
            if next_hero and next_hero not in unlocked_heroes:
                on_done.insert(0, {"type": "UnlockHero", "values": [next_hero]})
                unlocked_heroes.add(next_hero)
            on_done.append(
                {"type": "changeNodeState", "values": [node_sid(next_id), "Activated"]}
            )
        pos_x, pos_y, pos_z = map_region_to_storyhub_pos(mission_id, region_pixels)
        interaction_actions, mission_video_report = resolve_mission_interaction_actions(
            mission_id, policy, game_root=game_root
        )
        mission_video_reports.append(mission_video_report)
        nodes.append(
            {
                "sid": node_sid(mission_id),
                "state": "Activated" if index == 0 else "Hidden",
                "repeatable": False,
                "importanceType": "Main",
                "posX": pos_x,
                "posY": pos_y,
                "posZ": pos_z,
                "interactionActions": interaction_actions,
                "onDoneActions": on_done,
            }
        )

    transfer = policy["nativeTransfer"]["requiredValue"]
    if transfer is not True:
        fail("carry policy requires transferHeroProgressFromSession true")

    return {
        "sid": hub_sid,
        "mainIconSid": "main_icon",
        "hubIconSid": "save_icon",
        "transferHeroProgressFromSession": True,
        "showReputationPanel": False,
        "showHeroPanel": True,
        "firstShowActions": list(first_show_actions or []),
        "nodes": nodes,
        "_continuityNote": (
            "transferHeroProgressFromSession is intentionally true so mission-complete "
            "session heroes can write back into StoryHubSave.heroesSaves. "
            "Runtime writeback and strongest-N selection remain unvalidated. "
            "Core.zip install is opt-in via tools/install_roe_castle_continuity_weave.py. "
            "Hub firstShowActions PlayVideo emits only when videoContract."
            "hubFirstShowPlayVideo is not false and a native-canvas MP4 is present "
            "(>=1280x720; target 2560x1080 letterboxed). Good1 omits hub PlayVideo "
            "and uses a Cgood1 still for mainIconSid. Mission pins use serial "
            "PlayVideo then OpenMissionsPrologue (before load UI). "
            "heroes.json mirrors native mainStory delayed unlocks: only the first "
            "mission spawn sets isAvailableAtStart; later protagonists UnlockHero "
            "on the prior node's onDoneActions."
        ),
    }, mission_video_reports


def build_difficulty_parameters() -> list[dict[str, Any]]:
    # Indices 0-3 available (Easy..Expert). Index 4 Impossible stays locked.
    return [
        {
            "index": index,
            "nameSid": f"campaign_difficulty_name_{index + 1}",
            "descriptionSid": f"campaign_difficulty_description_{index + 1}",
            "isAvailable": index < 4,
        }
        for index in range(5)
    ]


def build_difficulty_rows(
    starting_resources: dict[int, dict[str, dict[str, int]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for template in NATIVE_DIFFICULTY_ROWS:
        index = int(template["index"])
        economic = starting_resources.get(index)
        if economic is None:
            fail(f"startingResources missing economic row for difficulty index {index}")
        rows.append(
            {
                "index": index,
                "economic": {
                    "playerStartResources": dict(economic["playerStartResources"]),
                    "aiStartResources": dict(economic["aiStartResources"]),
                },
                "ai": dict(template["ai"]),
                "neutralPowerMultiplier": template["neutralPowerMultiplier"],
                "guardPowerMultiplier": template["guardPowerMultiplier"],
                "neutralExpMultiplier": template["neutralExpMultiplier"],
                # Keep empty: czr.vhk Array.Clears map spawn armies when heroesArmies is set.
                "heroesArmies": [],
            }
        )
    return rows


def spawn_for_mission(mission_id: str) -> tuple[str, str]:
    """Return (heroSid, factionSid) for a mission; prefer MISSION_SPAWNS then defaults."""
    row = MISSION_SPAWNS.get(str(mission_id))
    if isinstance(row, dict):
        hero = str(row.get("heroSid") or "").strip()
        faction = str(row.get("factionSid") or "").strip()
        if hero and faction:
            return hero, faction
    return DEFAULT_HERO_SID, DEFAULT_FACTION_SID


def load_mission_spawns_from_policy(policy: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Build missionId → {heroSid, factionSid} from missionSpawns + defaultSpawn."""
    campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
    default = campaign.get("defaultSpawn") if isinstance(campaign.get("defaultSpawn"), dict) else {}
    default_hero = str(default.get("heroSid") or "").strip() or "homm3_castle_hero_7"
    default_faction = str(default.get("factionSid") or "").strip() or "homm3_castle"
    raw = campaign.get("missionSpawns") if isinstance(campaign.get("missionSpawns"), dict) else {}
    chain = list(policy.get("missionChain") or [])
    out: dict[str, dict[str, str]] = {}
    for mission_id in chain:
        mid = str(mission_id)
        override = raw.get(mid) if isinstance(raw.get(mid), dict) else None
        if override is not None:
            hero = str(override.get("heroSid") or "").strip()
            faction = str(override.get("factionSid") or "").strip()
            if not hero or not faction:
                fail(
                    f"campaign.missionSpawns[{mid!r}] requires non-empty heroSid and factionSid"
                )
            out[mid] = {"heroSid": hero, "factionSid": faction}
        else:
            out[mid] = {"heroSid": default_hero, "factionSid": default_faction}
    for mid, override in raw.items():
        if str(mid) in out:
            continue
        if not isinstance(override, dict):
            fail(f"campaign.missionSpawns[{mid!r}] must be an object")
        hero = str(override.get("heroSid") or "").strip()
        faction = str(override.get("factionSid") or "").strip()
        if not hero or not faction:
            fail(
                f"campaign.missionSpawns[{mid!r}] requires non-empty heroSid and factionSid"
            )
        out[str(mid)] = {"heroSid": hero, "factionSid": faction}
    return out


def build_mission_row(
    mission_id: str,
    batch_row: dict[str, Any],
    *,
    map_sid: str,
    map_ready: bool,
    map_ready_evidence: str,
    repo_root: Path,
    starting_resources: dict[int, dict[str, dict[str, int]]],
) -> dict[str, Any]:
    title = batch_row.get("title") or mission_id
    spawn = batch_row.get("startHeroContract") if isinstance(batch_row.get("startHeroContract"), dict) else {}
    hero_sid, fraction_sid = spawn_for_mission(mission_id)
    # requiredHeroesCount stays 1 for all missions so a single carried hero can start
    # sequels. Strongest-4 selection is a separate documented gap, not a prologue gate.
    # Single variant only: HoMM3 starting-bonus MissionVariant wiring is blocked until
    # additive army / item-grant surfaces exist (see continuity_bonus_difficulty.v1.json).
    #
    # Player spawn follows raw_translation humanOldenOwner (always 1 under the
    # native compact owner scheme). Bot sides cover every other map owner.
    # Raw_translation missions emit AI propSpawns; StoryHub must declare matching Bot
    # sides or propCities stay unbound (fcr.Init NRE / Session.Loader hang).
    player_side = human_player_side_from_raw_manifest(
        repo_root, mission_id, default_fraction_sid=fraction_sid
    )
    sides: list[dict[str, Any]] = [player_side]
    sides.extend(bot_sides_from_raw_manifest(repo_root, mission_id))
    return {
        "id": mission_config_id(mission_id),
        "requiredHeroesCount": 1,
        "fixedHeroesSet": [hero_sid],
        "bannedMagics": [],
        "disableFactionLaws": False,
        "disableMagicGuild": False,
        "idSidesWithoutTimer": [0],
        "difficultiesParameters": build_difficulty_parameters(),
        "importanceType": "Main",
        "variants": [
            {
                "titleSid": f"{mission_config_id(mission_id)}_title",
                "descriptionSid": f"{mission_config_id(mission_id)}_description",
                "mapSid": map_sid,
                "sides": sides,
                "difficulties": build_difficulty_rows(starting_resources),
            }
        ],
        "_continuity": {
            "missionId": mission_id,
            "batchTitle": title,
            "mapReadyForRuntime": map_ready,
            "mapReadyEvidence": map_ready_evidence,
            "startHeroContract": spawn,
            "playerSpawn": player_side.get("spawns"),
            "botSidesSource": "raw_translation_install_manifest_scenarioPlayers",
            "difficultySelection": {
                "availableIndices": [0, 1, 2, 3],
                "lockedIndices": [4],
                "scalingModel": "mainStory Start Phase Mission 1 + DB/difficulties_lobby_solo economic",
                "homm3Mapping": "Easy/Normal/Hard/Expert → Olden Easy/Normal/Difficult/Expert",
                "startingResources": "continuity_bonus_difficulty.v1.json startingResources.rows",
            },
            "startingBonusSelection": {
                "status": "not_shipped_fail_closed",
                "reason": (
                    "BhMissionChoices can present variants, but HoMM3 creature bonuses need "
                    "additive army apply (heroesArmies currently replaces) and item/war-machine "
                    "bonuses lack a StoryHub grant action"
                ),
                "policy": "scenarios/roe_castle_campaign/continuity_bonus_difficulty.v1.json",
            },
            "proofBoundary": (
                "mission config shape mirrors native StoryHub missions; "
                "mapReadyForRuntime true means the .map file exists and is installable; "
                "Bot sides come from raw_translation scenarioPlayers when present; "
                "difficulty rows mirror mainStory multipliers with lobby-solo starting resources; "
                "runtime scaling unvalidated"
            ),
        },
    }


def build_heroes(chain: list[str]) -> dict[str, Any]:
    """Emit hub roster with delayed unlocks for non-starting protagonists.

    Native mainStory ships only the opening hero with ``isAvailableAtStart: true``;
    later heroes omit the flag (unavailable) and are unlocked via ``UnlockHero``
    on prior mission ``onDoneActions``. Mirror that so multi-protagonist HoMM3
    hubs do not expose every campaign face from day one.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for mission_id in chain:
        sid, _faction = spawn_for_mission(mission_id)
        if sid and sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    # Keep defaultSpawn present even when no mission currently references it
    # (hub primary / installer campaignHeroSid contract).
    if DEFAULT_HERO_SID not in seen:
        ordered.insert(0, DEFAULT_HERO_SID)
        seen.add(DEFAULT_HERO_SID)
    if not ordered:
        ordered = [DEFAULT_HERO_SID]
    start_hero = ""
    if chain:
        start_hero, _ = spawn_for_mission(chain[0])
    if not start_hero:
        start_hero = DEFAULT_HERO_SID
    rows: list[dict[str, Any]] = []
    for sid in ordered:
        row: dict[str, Any] = {
            "id": sid,
            "selectedCounterSid": f"SelectedHero_{sid}",
        }
        # Match native: only the opening protagonist sets the flag true; later
        # heroes omit it (defaults unavailable) until UnlockHero fires.
        if sid == start_hero:
            row["isAvailableAtStart"] = True
        rows.append(row)
    return {"array": rows}


def build_fractions() -> dict[str, Any]:
    return {
        "array": [
            {"sid": sid, "counterSid": counter_sid}
            for sid, counter_sid in NATIVE_STORYHUB_FRACTIONS
        ]
    }


def build_counters(chain: list[str], heroes: dict[str, Any]) -> dict[str, Any]:
    # Reputation counters must match fractions.json (native six). Demon uses -666
    # in shipped tutorial/mainStory hubs; keep that native-shaped default.
    rows: list[dict[str, Any]] = [
        {
            "sid": counter_sid,
            "value": -666 if sid == "demon" else 0,
        }
        for sid, counter_sid in NATIVE_STORYHUB_FRACTIONS
    ]
    for mission_id in chain:
        rows.append({"sid": f"{mission_config_id(mission_id)}_Completed", "value": 0})
    for hero in heroes["array"]:
        rows.append({"sid": hero["selectedCounterSid"], "value": 0})
    return {"array": rows}


def build_lang_tokens(
    chain: list[str],
    campaign_title: str,
    hub_sid: str,
    *,
    title_by_mission: dict[str, str] | None = None,
    description_by_mission: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    # BhCampaign.Init LocKit key is "campaign_" + hubSid (const bqgi). Missing that
    # SID renders as LOC:campaign_<hubSid> on the Profiles campaign list.
    titles = {**MISSION_TITLES, **(title_by_mission or {})}
    descriptions = {**MISSION_DESCRIPTIONS, **(description_by_mission or {})}
    tokens = [
        {"sid": f"campaign_{hub_sid}", "text": campaign_title},
        {"sid": hub_sid, "text": campaign_title},
        {"sid": f"{hub_sid}_title", "text": campaign_title},
    ]
    for mission_id in chain:
        cfg = mission_config_id(mission_id)
        title = titles.get(mission_id)
        description = descriptions.get(mission_id) or title
        if not title:
            fail(f"missing mission title for {mission_id!r}")
        tokens.append({"sid": f"{cfg}_title", "text": title})
        tokens.append({"sid": f"{cfg}_description", "text": description})
    return tokens


def build_campaign_info_recipe(
    policy: dict[str, Any],
    first_mission_id: str,
    first_map_sid: str,
    *,
    hub_sid: str,
) -> dict[str, Any]:
    return {
        "schema": "homm3.olden_campaign_info_launch_recipe.v1",
        "proofBoundary": "source/static recipe only; runtime CampaignInfo.vop population unvalidated",
        "doNotApplyTo": "Plugin.CreateHomecomingPlayableShellCampaignInfo",
        "nativeCtor": "Hex.Session.CampaignInfo.vop",
        "fields": {
            "mapSid_": first_map_sid,
            "missionTitleSid_": f"{mission_config_id(first_mission_id)}_title",
            "missionDescriptionSid_": f"{mission_config_id(first_mission_id)}_description",
            "storyHubSave_": f"StoryHubSave for hub sid {hub_sid}",
            "storyHubSaveBeforeStartMission_": "snapshot before mission start",
            "transferHeroProgressFromSession_": True,
            "disableFactionLaws": False,
            "disableMagicGuild": False,
            "isCustomLearningBlocked": False,
        },
        "requiredCarryPolicyHandoff": policy["handoffs"][0],
        "levelPersistenceProofPath": [
            f"1. Opt-in install weave under Core.zip campaigns/{hub_sid}/.",
            f"2. Main Menu → Profiles/Campaign → select hub {hub_sid}.",
            f"3. On StoryHub, click the first node → Start Mission.",
            "4. Complete with hero level > 1.",
            "5. Observe StoryHubSave.heroesSaves writeback.",
            "6. Start the sequel and confirm hero sheet restore.",
        ],
        "uiClickPath": [
            "Launch Golden Era",
            "Main Menu → Campaign / Profiles",
            "Create or select a profile",
            f"Choose campaign sid {hub_sid}",
            "StoryHub map: click first node → Select Difficulty → choose hero → Start Mission",
        ],
    }


def build_weave(
    batch: dict[str, Any],
    policy: dict[str, Any],
    bonus_difficulty: dict[str, Any],
    *,
    maps_dir: Path,
    repo_root: Path,
    game_root: Path,
    hub_sid: str,
    region_pixels: dict[str, tuple[float, float]],
    carry_policy_path: Path,
    weave_title: str,
    batch_manifest_path: Path | None = None,
) -> dict[str, Any]:
    by_id = mission_by_id(batch)
    chain = list(policy["missionChain"])
    for mission_id in chain:
        if mission_id not in by_id:
            fail(f"carry policy missionChain references unknown missionId {mission_id!r}")

    handoffs = policy.get("handoffs") or []
    if not handoffs or len(chain) < 2:
        fail("carry policy requires missionChain length >= 2 and handoffs[]")
    handoff = handoffs[0]
    if handoff.get("fromMissionId") != chain[0] or handoff.get("toMissionId") != chain[1]:
        fail(
            f"first handoff must be {chain[0]} → {chain[1]}; "
            f"got {handoff.get('fromMissionId')} → {handoff.get('toMissionId')}"
        )

    import campaign_hero_level_cap

    for row in handoffs:
        if not isinstance(row, dict):
            fail("carry policy handoffs[] entries must be objects")
        for issue in campaign_hero_level_cap.validate_handoff_level_cap(
            row, repo_root=repo_root
        ):
            fail(issue)

    strongest = int(handoff["strongestHeroesCarryCount"])
    starting_resources = starting_resources_table(bonus_difficulty)
    mission_rows: list[dict[str, Any]] = []
    map_readiness: dict[str, Any] = {}
    for mission_id in chain:
        map_sid = resolve_map_sid(mission_id, by_id[mission_id], policy)
        ready, evidence = map_file_ready(map_sid, maps_dir, repo_root)
        map_readiness[mission_id] = {
            "mapSid": map_sid,
            "mapReadyForRuntime": ready,
            "evidence": evidence,
        }
        mission_rows.append(
            build_mission_row(
                mission_id,
                by_id[mission_id],
                map_sid=map_sid,
                map_ready=ready,
                map_ready_evidence=evidence,
                repo_root=repo_root,
                starting_resources=starting_resources,
            )
        )

    heroes = build_heroes(chain)
    video_actions, video_report = resolve_video_first_show_actions(
        policy, game_root=game_root
    )
    story_hub, mission_video_reports = build_story_hub(
        chain,
        policy,
        hub_sid=hub_sid,
        region_pixels=region_pixels,
        game_root=game_root,
        first_show_actions=video_actions,
    )
    video_report = dict(video_report)
    video_report["missionPins"] = mission_video_reports
    first_map_sid = map_readiness[chain[0]]["mapSid"]
    all_ready = all(row["mapReadyForRuntime"] for row in map_readiness.values())
    sequel_gap_status = "maps_present_campaign_ready" if all_ready else "generation_incomplete"
    map_choice = policy.get("storyHubMapSidOverrides") or {}

    return {
        "schema": SCHEMA,
        "title": weave_title,
        "proofBoundary": (
            "generated-artifact; Core.zip install is opt-in; runtime transfer unvalidated; "
            "strongest-N selection not proven; hub/mission PlayVideo blocked until "
            "native-canvas MP4s exist"
        ),
        "planDoc": policy["planDoc"],
        "carryPolicyPath": str(carry_policy_path.relative_to(ROOT)).replace("\\", "/"),
        "bonusDifficultyPolicyPath": str(BONUS_DIFFICULTY_POLICY.relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "batchManifestPath": str(
            (batch_manifest_path or BATCH_MANIFEST).resolve().relative_to(ROOT)
        ).replace("\\", "/"),
        "hubSid": hub_sid,
        "transferHeroProgressFromSession": True,
        "videoWiring": video_report,
        "difficultySelection": bonus_difficulty.get("homm3Difficulty"),
        "startingBonusSelection": {
            "implementedInWeave": bonus_difficulty.get("homm3StartingBonuses", {}).get(
                "implementedInWeave"
            ),
            "failClosedRule": bonus_difficulty.get("homm3StartingBonuses", {}).get(
                "failClosedRule"
            ),
            "missions": {
                key: value
                for key, value in (bonus_difficulty.get("homm3StartingBonuses") or {}).items()
                if key in set(chain)
            },
        },
        "missionChain": chain,
        "handoffs": policy["handoffs"],
        "homecomingMapSidChoice": {
            "mapSid": first_map_sid,
            "reason": map_choice.get("choiceReason"),
        },
        "mapReadiness": map_readiness,
        "minimumFaithfulSubset": policy["minimumFaithfulSubset"],
        "deferredExplicitLoss": policy["deferredExplicitLoss"],
        "coreZipLayout": {
            "root": f"campaigns/{hub_sid}/",
            "files": [
                "storyHub.json",
                "heroes.json",
                "fractions.json",
                "storyCounters.json",
                "perks.json",
                *[f"missions/{mission_config_id(mid)}.json" for mid in chain],
                "icons/main_icon.png",
                "icons/hub_icon.png",
            ],
            "installStatus": "not_installed",
            "discoveryEvidence": (
                "pm.ivr enumerates campaigns/* via cjq.rsv/rsw over Core.zip virtual FS "
                "(decomp: tmp/cpp2il_experiment/readable_notes/pm_ivr_dossier.md); "
                "hardcoded tutorial/mainStory/tutorial_challenges constants are icon helpers, "
                "not an exclusive allowlist"
            ),
        },
        "langTokens": build_lang_tokens(
            chain,
            policy["campaign"]["campaignTitle"],
            hub_sid,
            title_by_mission=(
                policy.get("missionTitles")
                if isinstance(policy.get("missionTitles"), dict)
                else None
            ),
            description_by_mission=(
                policy.get("missionDescriptions")
                if isinstance(policy.get("missionDescriptions"), dict)
                else None
            ),
        ),
        # StoryHub protagonists that are also town-roster heroes must exist under
        # DB/heroes/… and must NOT be listed in DataInc.campaignHeroes (Quick Play
        # hides that list). See validate_homm3_campaign_heroes_roster_separation_contract.
        "rosterHeroSidRequired": [DEFAULT_HERO_SID],
        "campaignInfoLaunchRecipe": build_campaign_info_recipe(
            policy,
            chain[0],
            first_map_sid,
            hub_sid=hub_sid,
        ),
        "payloads": {
            "storyHub": story_hub,
            "heroes": heroes,
            "fractions": build_fractions(),
            "storyCounters": build_counters(chain, heroes),
            "perks": {"array": [{"sid": "perk1"}, {"sid": "perk2"}]},
            "missions": {
                mission_config_id(mission_id): {"array": [row]}
                for mission_id, row in zip(chain, mission_rows)
            },
        },
        "openGaps": [
            {
                "id": "strongest_n_selection",
                "status": "not_proven",
                "detail": handoff["strongestNSelection"],
            },
            {
                "id": "session_to_hub_writeback",
                "status": "runtime_unvalidated",
                "detail": (
                    "transferHeroProgressFromSession true is required but writeback "
                    "behavior is unproven on Golden Era"
                ),
            },
            {
                "id": "sequel_maps",
                "status": sequel_gap_status,
                "detail": (
                    "Guardian Angels and Griffin Cliff raw_translation .map files are present "
                    "and marked mapReadyForRuntime when installed; broader map gameplay "
                    "quality remains user-unvalidated"
                    if all_ready
                    else "one or more sequel raw_translation .map files are still missing"
                ),
            },
            {
                "id": "campaign_intro_video",
                "status": video_report.get("status") or "unknown",
                "detail": video_report,
            },
            {
                "id": "army_carry",
                "status": "deferred_explicit_loss",
                "detail": policy["deferredExplicitLoss"],
            },
            {
                "id": "starting_bonus_selection",
                "status": "not_shipped_fail_closed",
                "detail": (
                    "StoryHub MissionVariant bonuses remain fail-closed. "
                    "Day-1 QuestScript Dialog pilots exist for homecoming + razor_claw "
                    "(campaign_starting_bonus.py); runtime grant still user-unvalidated."
                ),
                "policyPath": str(BONUS_DIFFICULTY_POLICY.relative_to(ROOT)).replace(
                    "\\", "/"
                ),
            },
            {
                "id": "difficulty_runtime_scaling",
                "status": "source_static_shaped_runtime_unvalidated",
                "detail": (
                    "Mission difficultiesParameters 0-3 available with mainStory Start Phase "
                    "neutral/guard/exp/AI multipliers plus lobby-solo player/AI starting resources; "
                    "Impossible locked. Runtime BhDifficulties selection and "
                    "CampaignInfo.campaignDifficulty_ application user-unvalidated."
                ),
            },
        ],
    }


def emit_selection_main_icon(
    *,
    policy: dict[str, Any],
    game_root: Path,
    repo_root: Path,
    out_dir: Path,
) -> dict[str, Any] | None:
    """When policy.selectionIcon is set, write campaign_payload/icons/main_icon.png."""
    video = policy.get("videoContract") if isinstance(policy.get("videoContract"), dict) else {}
    selection = video.get("selectionIcon") if isinstance(video.get("selectionIcon"), dict) else None
    if selection is None:
        return None
    from campaign_selection_icon import (
        COMPOSE_VERTICAL_FOCUS,
        build_main_icon_from_mp4,
        build_main_icon_from_still,
    )

    compose_policy = str(selection.get("composePolicy") or COMPOSE_VERTICAL_FOCUS)
    focus_x = float(selection.get("focusX", 0.5))
    focus_y = float(selection.get("focusY", 0.5))
    still_rel = selection.get("stillArtifact")
    still_out = (repo_root / still_rel) if isinstance(still_rel, str) and still_rel.strip() else None
    icon_out = out_dir / "campaign_payload" / "icons" / "main_icon.png"

    rel_mp4 = str(
        selection.get("sourceMp4RelativeToStreamingAssets")
        or video.get("requiredMp4RelativeToStreamingAssets")
        or ""
    ).replace("\\", "/")
    mp4_path = (
        game_root / "HeroesOldenEra_Data" / "StreamingAssets" / rel_mp4 if rel_mp4 else None
    )
    if mp4_path is not None and mp4_path.is_file():
        return build_main_icon_from_mp4(
            mp4_path,
            still_out=still_out,
            icon_out=icon_out,
            compose_policy=compose_policy,
            focus_x=focus_x,
            focus_y=focus_y,
        )
    if still_out is not None and still_out.is_file():
        return build_main_icon_from_still(
            still_out,
            icon_out=icon_out,
            compose_policy=compose_policy,
            focus_x=focus_x,
            focus_y=focus_y,
        )
    raise FileNotFoundError(
        "selectionIcon requires StreamingAssets MP4 "
        f"{rel_mp4!r} or existing stillArtifact {still_rel!r}"
    )


def emit_split_files(out_dir: Path, weave: dict[str, Any]) -> list[str]:
    payloads = weave["payloads"]
    written: list[str] = []
    mapping = {
        "storyHub.json": payloads["storyHub"],
        "heroes.json": payloads["heroes"],
        "fractions.json": payloads["fractions"],
        "storyCounters.json": payloads["storyCounters"],
        "perks.json": payloads["perks"],
    }
    for name, payload in mapping.items():
        path = out_dir / "campaign_payload" / name
        write_json(path, payload)
        written.append(str(path.relative_to(out_dir)).replace("\\", "/"))
    for mission_file, payload in payloads["missions"].items():
        path = out_dir / "campaign_payload" / "missions" / f"{mission_file}.json"
        write_json(path, payload)
        written.append(str(path.relative_to(out_dir)).replace("\\", "/"))
    lang_path = out_dir / "campaign_payload" / "lang_tokens.json"
    write_json(lang_path, {"array": weave["langTokens"]})
    written.append(str(lang_path.relative_to(out_dir)).replace("\\", "/"))
    return written


def main() -> int:
    global MISSION_CONFIG_PREFIX, DEFAULT_FACTION_SID, DEFAULT_HERO_SID, MISSION_SPAWNS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument(
        "--hub",
        choices=(
            "good1",
            "good2",
            "good3",
            "evil1",
            "evil2",
            "secret",
            "secret1",
            "neutral1",
            "ab",
            "blood",
            "slayer",
            "festival",
            "fire",
            "fool",
            "sandro",
            "crag",
            "yog",
            "gem",
            "gelu",
            "final",
        ),
        default="good1",
        help="Which StoryHub arc to emit (RoE or AB/SoD).",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    ab_sod_hubs = {
        "ab",
        "blood",
        "slayer",
        "festival",
        "fire",
        "fool",
        "sandro",
        "crag",
        "yog",
        "gem",
        "gelu",
        "final",
    }
    if args.hub in ab_sod_hubs:
        hub_index_path = (
            repo_root / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"
        )
        hub_index = load_json(hub_index_path)
        hub_row = next(
            (row for row in hub_index.get("hubs") or [] if row.get("hub") == args.hub),
            None,
        )
        if hub_row is None:
            fail(f"hub {args.hub!r} missing from {hub_index_path}")
        hub_sid = str(hub_row["hubSid"])
        carry_policy_path = (
            ROOT
            / "scenarios"
            / "ab_sod_campaigns"
            / f"continuity_carry_policy_{args.hub}.v1.json"
        )
        default_out = (
            ROOT
            / "artifacts"
            / "campaign_port_poc"
            / "ab_sod_campaigns"
            / f"continuity_weave_{args.hub}"
        )
        region_pixels = {}
        weave_title = f"{hub_row.get('hub', args.hub)} continuity weave"
    elif args.hub == "good2":
        hub_sid = HUB_SID_GOOD2
        carry_policy_path = CARRY_POLICY_GOOD2
        default_out = DEFAULT_OUT_GOOD2
        region_pixels = HOMM3_GOOD2_REGION_PIXELS
        weave_title = "RoE Castle Good2 (Liberation) continuity weave"
    elif args.hub == "good3":
        hub_sid = HUB_SID_GOOD3
        carry_policy_path = CARRY_POLICY_GOOD3
        default_out = DEFAULT_OUT_GOOD3
        region_pixels = HOMM3_GOOD3_REGION_PIXELS
        weave_title = "RoE Castle Good3 (Song for the Father) continuity weave"
    elif args.hub == "evil1":
        hub_sid = HUB_SID_EVIL1
        carry_policy_path = CARRY_POLICY_EVIL1
        default_out = DEFAULT_OUT_EVIL1
        region_pixels = HOMM3_EVIL1_REGION_PIXELS
        weave_title = "RoE Evil1 (Dungeons and Devils) continuity weave"
    elif args.hub == "evil2":
        hub_sid = HUB_SID_EVIL2
        carry_policy_path = CARRY_POLICY_EVIL2
        default_out = DEFAULT_OUT_EVIL2
        region_pixels = HOMM3_EVIL2_REGION_PIXELS
        weave_title = "RoE Evil2 (Long Live the King) continuity weave"
    elif args.hub == "secret":
        hub_sid = HUB_SID_SECRET
        carry_policy_path = CARRY_POLICY_SECRET
        default_out = DEFAULT_OUT_SECRET
        region_pixels = HOMM3_SECRET_REGION_PIXELS
        weave_title = "RoE Secret (Specter of Power) continuity weave"
    elif args.hub == "secret1":
        hub_sid = HUB_SID_SECRET1
        carry_policy_path = CARRY_POLICY_SECRET1
        default_out = DEFAULT_OUT_SECRET1
        region_pixels = HOMM3_SECRET1_REGION_PIXELS
        weave_title = "RoE Secret1 (Seeds of Discontent) continuity weave"
    elif args.hub == "neutral1":
        hub_sid = HUB_SID_NEUTRAL1
        carry_policy_path = CARRY_POLICY_NEUTRAL1
        default_out = DEFAULT_OUT_NEUTRAL1
        region_pixels = HOMM3_NEUTRAL1_REGION_PIXELS
        weave_title = "RoE Neutral1 (Spoils of War) continuity weave"
    else:
        hub_sid = HUB_SID_GOOD1
        carry_policy_path = CARRY_POLICY_GOOD1
        default_out = DEFAULT_OUT_GOOD1
        region_pixels = HOMM3_GOOD1_REGION_PIXELS
        weave_title = "RoE Castle Good1 continuity weave"

    out_dir = (args.out_dir or (repo_root / default_out.relative_to(ROOT))).resolve()
    maps_dir = args.game_root.resolve() / MAPS_REL

    policy = load_json(repo_root / carry_policy_path.relative_to(ROOT))
    if args.hub in ab_sod_hubs:
        campaign_pixels = (
            policy.get("campaign", {}).get("regionPixels")
            if isinstance(policy.get("campaign"), dict)
            else None
        )
        if not isinstance(campaign_pixels, dict) or not campaign_pixels:
            fail(f"{args.hub} carry policy missing campaign.regionPixels")
        region_pixels = {
            str(mission_id): (float(xy[0]), float(xy[1]))
            for mission_id, xy in campaign_pixels.items()
        }
        weave_title = f"{policy.get('campaign', {}).get('campaignTitle', args.hub)} continuity weave"
    campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
    batch_rel = campaign.get("batchManifest")
    if isinstance(batch_rel, str) and batch_rel.strip():
        batch_path = repo_root / batch_rel.strip()
    else:
        batch_path = repo_root / BATCH_MANIFEST.relative_to(ROOT)
    batch = load_json(batch_path)
    prefix = campaign.get("missionConfigPrefix")
    if isinstance(prefix, str) and prefix.strip():
        MISSION_CONFIG_PREFIX = prefix.strip()
    else:
        MISSION_CONFIG_PREFIX = "homm3_roe_castle"
    spawn = campaign.get("defaultSpawn") if isinstance(campaign.get("defaultSpawn"), dict) else {}
    faction = spawn.get("factionSid")
    hero = spawn.get("heroSid")
    DEFAULT_FACTION_SID = (
        faction.strip() if isinstance(faction, str) and faction.strip() else "homm3_castle"
    )
    DEFAULT_HERO_SID = (
        hero.strip() if isinstance(hero, str) and hero.strip() else "homm3_castle_hero_7"
    )
    MISSION_SPAWNS = load_mission_spawns_from_policy(policy)
    # Fail closed: StoryHub Init NRE-loops if heroes.json references a missing DB hero
    # (seen with AB/SoD defaultSpawn hero_0 — Core only ships hero_1…).
    import re
    import zipfile

    hero_sids_to_check = sorted(
        {
            DEFAULT_HERO_SID,
            *[str(row.get("heroSid") or "").strip() for row in MISSION_SPAWNS.values()],
        }
        - {""}
    )
    core_zip = args.game_root.resolve() / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
    for hero_sid in hero_sids_to_check:
        hero_match = re.fullmatch(r"(homm3_[a-z]+)_hero_(\d+)", hero_sid)
        if not hero_match:
            fail(f"spawn heroSid has unexpected shape: {hero_sid!r}")
        hero_member = f"DB/heroes/{hero_match.group(1)}/{hero_sid}.json"
        if core_zip.is_file():
            with zipfile.ZipFile(core_zip, "r") as zf:
                if hero_member not in zf.namelist():
                    fail(
                        f"spawn heroSid {hero_sid!r} missing from Core.zip "
                        f"({hero_member}). StoryHub will NullRef-loop on hub open. "
                        "Use an existing DB hero (typically *_hero_1 or *_hero_7)."
                    )
    bonus_difficulty = load_json(repo_root / BONUS_DIFFICULTY_POLICY.relative_to(ROOT))
    if policy.get("schema") != "homm3.olden_campaign_continuity_carry_policy.v1":
        fail(f"unsupported carry policy schema in {carry_policy_path}")
    if bonus_difficulty.get("schema") != "homm3.olden_campaign_continuity_bonus_difficulty.v1":
        fail(f"unsupported bonus/difficulty policy schema in {BONUS_DIFFICULTY_POLICY}")
    if policy.get("campaign", {}).get("hubSid") != hub_sid:
        fail(
            f"carry policy hubSid {policy.get('campaign', {}).get('hubSid')!r} "
            f"!= --hub {args.hub} expected {hub_sid!r}"
        )

    weave = build_weave(
        batch,
        policy,
        bonus_difficulty,
        maps_dir=maps_dir,
        repo_root=repo_root,
        game_root=args.game_root.resolve(),
        hub_sid=hub_sid,
        region_pixels=region_pixels,
        carry_policy_path=carry_policy_path,
        weave_title=weave_title,
        batch_manifest_path=batch_path,
    )
    selection_icon = emit_selection_main_icon(
        policy=policy,
        game_root=args.game_root.resolve(),
        repo_root=repo_root,
        out_dir=out_dir,
    )
    if selection_icon is not None:
        weave["selectionIcon"] = selection_icon
        video_wiring = weave.setdefault("videoWiring", {})
        if isinstance(video_wiring, dict):
            video_wiring["selectionIcon"] = selection_icon
    write_json(out_dir / "continuity.weave.v1.json", weave)
    split = emit_split_files(out_dir, weave)
    if selection_icon is not None:
        split.append("campaign_payload/icons/main_icon.png")
    report = {
        "schema": "homm3.olden_campaign_continuity_weave_report.v1",
        "proofBoundary": weave["proofBoundary"],
        "hubSid": hub_sid,
        "transferHeroProgressFromSession": True,
        "firstHandoff": (
            f"{weave['handoffs'][0]['fromMissionId']}->{weave['handoffs'][0]['toMissionId']}"
        ),
        "levelCap": weave["handoffs"][0]["levelCap"],
        "strongestHeroesCarryCount": weave["handoffs"][0]["strongestHeroesCarryCount"],
        "firstMapSid": weave["homecomingMapSidChoice"]["mapSid"],
        "mapReadiness": weave["mapReadiness"],
        "videoWiring": weave.get("videoWiring"),
        "selectionIcon": selection_icon,
        "outputs": {
            "weave": "continuity.weave.v1.json",
            "campaignPayloadFiles": split,
        },
        "installStatus": weave["coreZipLayout"]["installStatus"],
        "rawTranslationPlaytestImpact": (
            f"StoryHub uses raw_translation mapSids for {args.hub} missions; "
            "Plugin.CreateHomecomingPlayableShellCampaignInfo stays empty CampaignInfo()"
        ),
    }
    write_json(out_dir / "continuity.weave_report.v1.json", report)
    print(f"wrote {out_dir / 'continuity.weave.v1.json'}")
    print(f"wrote {len(split)} campaign payload files under {out_dir / 'campaign_payload'}")
    video = weave.get("videoWiring") or {}
    print(f"  hub video status={video.get('status')} mp4Present={video.get('mp4Present')}")
    if selection_icon is not None:
        print(
            f"  selectionIcon main_icon={selection_icon.get('iconPath')} "
            f"size={selection_icon.get('iconSize')}"
        )
    for pin in video.get("missionPins") or []:
        print(
            f"  mission video {pin.get('missionId')} clip={pin.get('clipKey')} "
            f"status={pin.get('playVideoStatus')}"
        )
    for mission_id, row in weave["mapReadiness"].items():
        print(
            f"  mapReady {mission_id}={row['mapReadyForRuntime']} "
            f"sid={row['mapSid']} ({row['evidence']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
