#!/usr/bin/env python3
"""Opt-in install of RoE Castle Good1/Good2 StoryHub continuity weave into Golden Era Core.zip.

Installs:
  - campaigns/homm3_NN_<expansion>_…/ (storyHub, missions, heroes, counters, perks, icons);
    hub SIDs are zero-padded so Profiles alpha-sorts into Complete play order
    (see tools/homm3_campaign_hub_sid_order.py). Orphan/non-canonical homm3_*
    campaign folders (e.g. pre-rename Playing with Fire necropolis packaging) are
    scrubbed from Core.zip on every install.
  - Lang/*/texts/campaign.json tokens for hub + mission titles
  - Lang/*/texts/{customMaps,dialogues,cities,...}.json SID merges from mission overlays
    (tokens+array; fails closed on Loc:-class missing SIDs via preflight/validator)
  - DB/data.json campaignHeroes scrub: never register shared town-roster
    hero SIDs (e.g. Crag Hack / Christian) there — native Quick Play hides
    DataInc.campaignHeroes from custom-game selection. Campaign-only stubs
    without DB/heroes rows may still be listed.
  - Mission raw_translation maps into StreamingAssets/maps/Story_maps/
    (StoryHub StartInfo path; maps/ root is not enough)
  - After each Story_maps copy/keep: rewrite main-goal quest UI into LocKit
    checklist bullets (``*_main_goal_obj_*``); inject English + phrasebook
    rows into Lang/*/texts/customMaps.json before Core merge so reinstalls
    cannot stomp prior surgical objective patches

Core overlay merge: id-array JSON catalogs (notably
``DB/buildings_constructions/custom_maps_buildings_presets.json``) merge by
``id`` across mission overlays and into existing Core members. Lang text
catalogs merge by ``sid`` across ``tokens`` and ``array``. Whole-file
later-wins previously let Tunnels wipe Steadwick town construction rows and
Liberation dialog/quest LocKit rows.

Multi-hub: ``--hub`` is repeatable; ``--all-hubs`` installs every StoryHub in
play order with **one** Core.zip rewrite (maps still copy per hub first).

Performance knobs:
- ``--jobs N``: parallel weave regen (processes) + overlay collect (threads).
- Lang overlay dumps are fingerprint/doc-cached so identical multi-MB
  ``dialogues.json`` files are parsed once per unique content.
- Story_maps copy skips when artifact SHA matches installed map unless
  ``--force-map-copy``.

Always backs up Core.zip before mutating. Does not change
Plugin.CreateHomecomingPlayableShellCampaignInfo.

Post-install fail-closed: ``tools/map_load_preflight.py`` (Meta logic ↔
ObjectConfig, orphan ``homm3_xfp_*`` scrub, camp_fire aliases, boat ObjectConfig,
StoryHub owner/ai.script, Story_maps-only dual-install, city construction SIDs).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from homm3_campaign_hub_sid_order import PLAY_ORDER_HUB_SIDS  # noqa: E402

DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
# Known rename leftovers that must never remain beside the canonical play-order hub.
# Playing with Fire moved necropolis_* packaging → fortress_* (Adrienne).
STALE_HOMM3_HUB_SIDS: frozenset[str] = frozenset(
    {
        "homm3_13_ab_necropolis_fire",
        "homm3_ab_necropolis_fire",
    }
)
CANONICAL_HOMM3_HUB_SIDS: frozenset[str] = frozenset(PLAY_ORDER_HUB_SIDS)
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
# StoryHub Start Game resolves mapSid under maps/Story_maps/ (native c_M*/t_* layout).
# Installing only under maps/ makes Start a silent no-op with Critical Error in Player.log.
# Installing the same mapSid under BOTH maps/ and Story_maps/ registers QuestScript twice
# (Player.log: each StartTurn Dialog plays twice). Never leave a maps/-root duplicate.
MAPS_ROOT_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
MAPS_REL = MAPS_ROOT_REL / "Story_maps"
INSTALL_DESTINATION_POLICY = "story_maps_only_forbid_maps_root_duplicate"

# Process caches for install: Lang overlays are near-full Core dumps; filtering the
# same blob across missions/langs dominated --all-hubs wall time.
_LANG_ALLOWLIST_CACHE: dict[str, set[str] | None] = {}
_LANG_FILTER_CACHE: dict[tuple[str, str], bytes] = {}
_LANG_FILE_FILTER_CACHE: dict[tuple[str, str], bytes] = {}
_CORE_ICON_CACHE: dict[tuple[str, int, int], dict[str, bytes]] = {}


def _log(message: str) -> None:
    print(message, flush=True)


def _lang_file_fingerprint(path: Path) -> str:
    """Cheap content fingerprint so identical multi-MB Lang dumps share one parse."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        head = handle.read(65536)
        if size > 131072:
            handle.seek(size - 65536)
            tail = handle.read(65536)
        else:
            tail = b""
    return hashlib.sha256(
        head + b"\0" + tail + str(size).encode("ascii")
    ).hexdigest()


def _load_lang_doc(path: Path) -> dict[str, Any] | None:
    # Parsed docs are NOT cached. --all-hubs reads ~5600 overlay Lang files (8.7 GB, ~945
    # distinct multi-MB dumps); caching every parsed dump (plus its raw bytes) grew the
    # process past free RAM and died with MemoryError (port phase 4, 2026-09-30). Only the
    # small filtered output is cached, in _LANG_FILE_FILTER_CACHE.
    return _try_parse_lang_sid_catalog(path.read_bytes())


def _filter_lang_doc_to_allow(doc: dict[str, Any], allow: set[str]) -> bytes:
    filtered: dict[str, Any] = {
        key: value for key, value in doc.items() if key not in ("tokens", "array")
    }
    kept_by_sid: dict[str, str] = {}
    for key in ("tokens", "array"):
        for row in doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            text = row.get("text")
            if isinstance(sid, str) and sid in allow and isinstance(text, str):
                kept_by_sid[sid] = text
    if not kept_by_sid:
        return b""
    rows = [{"sid": sid, "text": text} for sid, text in kept_by_sid.items()]
    filtered["tokens"] = list(rows)
    filtered["array"] = list(rows)
    return (json.dumps(filtered, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _filter_lang_path(
    path: Path,
    *,
    overlay_root: Path,
    relative: str,
    allow: set[str] | None,
) -> bytes:
    if allow is None:
        return path.read_bytes()
    allow_fp = hashlib.sha256("\0".join(sorted(allow)).encode("utf-8")).hexdigest()
    file_fp = _lang_file_fingerprint(path)
    cache_key = (file_fp, allow_fp)
    cached = _LANG_FILE_FILTER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    doc = _load_lang_doc(path)
    if doc is None:
        raw = path.read_bytes()
        _LANG_FILE_FILTER_CACHE[cache_key] = raw
        return raw
    filtered = _filter_lang_doc_to_allow(doc, allow)
    _LANG_FILE_FILTER_CACHE[cache_key] = filtered
    return filtered

# Install key order matches Profiles play-order hub SIDs (RoE → AB → SoD).
HUB_INSTALL_KEYS_PLAY_ORDER: tuple[str, ...] = (
    "good1",
    "good2",
    "good3",
    "evil1",
    "evil2",
    "neutral1",
    "secret1",
    "secret",
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
)
HUB_CHOICES: tuple[str, ...] = HUB_INSTALL_KEYS_PLAY_ORDER

HUB_CONFIGS: dict[str, dict[str, Any]] = {
    "good1": {
        "hubSid": "homm3_01_roe_castle_good1",
        "campaignHeroSid": "homm3_castle_hero_7",
        "weaveDir": Path("artifacts/campaign_port_poc/roe_castle_campaign/continuity_weave"),
        "missions": (
            "homm3_roe_castle_homecoming.json",
            "homm3_roe_castle_guardian_angels.json",
            "homm3_roe_castle_griffin_cliff.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_castle_homecoming_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/homecoming_poc/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/homecoming_poc/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_guardian_angels_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/guardian_angels/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/guardian_angels/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_griffin_cliff_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/griffin_cliff/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/griffin_cliff/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "good2": {
        "hubSid": "homm3_02_roe_castle_good2",
        "campaignHeroSid": "homm3_castle_hero_7",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_castle_campaign/continuity_weave_good2"
        ),
        "missions": (
            "homm3_roe_castle_steadwick_liberation.json",
            "homm3_roe_castle_deal_with_the_devil.json",
            "homm3_roe_castle_neutral_affairs.json",
            "homm3_roe_castle_tunnels_and_troglodytes.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_castle_steadwick_liberation_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/steadwick_liberation/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/steadwick_liberation/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_deal_with_the_devil_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/deal_with_the_devil/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/deal_with_the_devil/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_neutral_affairs_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/neutral_affairs/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/neutral_affairs/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_tunnels_and_troglodytes_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/tunnels_and_troglodytes/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_castle_campaign/tunnels_and_troglodytes/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "good3": {
        "hubSid": "homm3_03_roe_castle_good3",
        "campaignHeroSid": "homm3_necropolis_hero_12",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_good3"
        ),
        "missions": (
            "homm3_roe_castle_safe_passage.json",
            "homm3_roe_castle_united_front.json",
            "homm3_roe_castle_for_king_and_country.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_castle_safe_passage_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/safe_passage/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/safe_passage/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_united_front_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/united_front/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/united_front/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_castle_for_king_and_country_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/for_king_and_country/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/for_king_and_country/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "evil2": {
        "hubSid": "homm3_05_roe_necropolis_evil2",
        "campaignHeroSid": "homm3_necropolis_hero_7",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_evil2"
        ),
        "missions": (
            "homm3_roe_necropolis_a_gryphons_heart.json",
            "homm3_roe_necropolis_season_of_harvest.json",
            "homm3_roe_necropolis_corporeal_punishment.json",
            "homm3_roe_necropolis_from_day_to_night.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_necropolis_a_gryphons_heart_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/a_gryphons_heart/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/a_gryphons_heart/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_season_of_harvest_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/season_of_harvest/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/season_of_harvest/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_corporeal_punishment_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/corporeal_punishment/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/corporeal_punishment/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_from_day_to_night_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/from_day_to_night/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/from_day_to_night/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "evil1": {
        "hubSid": "homm3_04_roe_dungeon_evil1",
        "campaignHeroSid": "homm3_dungeon_hero_7",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_evil1"
        ),
        "missions": (
            "homm3_roe_dungeon_a_devilish_plan.json",
            "homm3_roe_dungeon_groundbreaking.json",
            "homm3_roe_dungeon_steadwicks_fall.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_dungeon_a_devilish_plan_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/a_devilish_plan/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/a_devilish_plan/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_dungeon_groundbreaking_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/groundbreaking/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/groundbreaking/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_dungeon_steadwicks_fall_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/steadwicks_fall/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/steadwicks_fall/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "secret": {
        "hubSid": "homm3_08_roe_necropolis_secret",
        "campaignHeroSid": "homm3_necropolis_hero_11",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_secret"
        ),
        "missions": (
            "homm3_roe_necropolis_poison_fit_for_a_king.json",
            "homm3_roe_necropolis_to_build_a_tunnel.json",
            "homm3_roe_necropolis_kreegan_alliance.json",
            "homm3_roe_necropolis_with_blinders_on.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_necropolis_poison_fit_for_a_king_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/poison_fit_for_a_king/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/poison_fit_for_a_king/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_to_build_a_tunnel_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/to_build_a_tunnel/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/to_build_a_tunnel/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_kreegan_alliance_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/kreegan_alliance/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/kreegan_alliance/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_necropolis_with_blinders_on_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/with_blinders_on/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/with_blinders_on/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "secret1": {
        "hubSid": "homm3_07_roe_rampart_secret1",
        "campaignHeroSid": "homm3_rampart_hero_1",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_secret1"
        ),
        "missions": (
            "homm3_roe_neutral_the_grail.json",
            "homm3_roe_neutral_the_road_home.json",
            "homm3_roe_neutral_independence.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_neutral_the_grail_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/the_grail/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/the_grail/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_neutral_the_road_home_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/the_road_home/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/the_road_home/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_neutral_independence_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/independence/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/independence/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    "neutral1": {
        "hubSid": "homm3_06_roe_neutral_neutral1",
        "campaignHeroSid": "homm3_fortress_hero_7",
        "weaveDir": Path(
            "artifacts/campaign_port_poc/roe_remaining_campaigns/continuity_weave_neutral1"
        ),
        "missions": (
            "homm3_roe_neutral_1a.json",
            "homm3_roe_neutral_1b.json",
            "homm3_roe_neutral_1c.json",
        ),
        "mapInstalls": [
            {
                "mapSid": "h3_roe_neutral_1a_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1a/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1a/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_neutral_1b_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1b/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1b/raw_translation_map/core_overlay"
                ),
            },
            {
                "mapSid": "h3_roe_neutral_1c_raw_translation",
                "artifact": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1c/raw_translation_map/maps"
                ),
                "coreOverlay": Path(
                    "artifacts/campaign_port_poc/roe_remaining_campaigns/neutral_1c/raw_translation_map/core_overlay"
                ),
            },
        ],
    },
    # --- BEGIN AB/SoD HUB_CONFIGS (generated) ---
    "ab": {
        "hubSid": 'homm3_09_ab_conflux_ab',
        "campaignHeroSid": 'homm3_castle_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_ab'),
        "missions": (
            'homm3_ab_conflux_catherines_charge.json',
            'homm3_ab_conflux_shadows_of_the_forest.json',
            'homm3_ab_conflux_seeking_armageddon.json',
            'homm3_ab_conflux_maker_of_sorrows.json',
            'homm3_ab_conflux_return_of_the_king.json',
            'homm3_ab_conflux_a_blade_in_the_back.json',
            'homm3_ab_conflux_to_kill_a_hero.json',
            'homm3_ab_conflux_oblivions_edge.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_conflux_catherines_charge_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/catherines_charge/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/catherines_charge/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_shadows_of_the_forest_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/shadows_of_the_forest/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/shadows_of_the_forest/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_seeking_armageddon_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/seeking_armageddon/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/seeking_armageddon/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_maker_of_sorrows_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/maker_of_sorrows/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/maker_of_sorrows/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_return_of_the_king_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/return_of_the_king/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/return_of_the_king/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_a_blade_in_the_back_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_blade_in_the_back/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_blade_in_the_back/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_to_kill_a_hero_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/to_kill_a_hero/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/to_kill_a_hero/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_conflux_oblivions_edge_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/oblivions_edge/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/oblivions_edge/raw_translation_map/core_overlay'),
            },
        ],
    },
    "blood": {
        "hubSid": 'homm3_10_ab_dungeon_blood',
        "campaignHeroSid": 'homm3_dungeon_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_blood'),
        "missions": (
            'homm3_ab_dungeon_culling_the_weak.json',
            'homm3_ab_dungeon_savaging_the_scavengers.json',
            'homm3_ab_dungeon_blood_of_the_dragon_father.json',
            'homm3_ab_dungeon_blood_thirsty.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_dungeon_culling_the_weak_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/culling_the_weak/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/culling_the_weak/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_dungeon_savaging_the_scavengers_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/savaging_the_scavengers/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/savaging_the_scavengers/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_dungeon_blood_of_the_dragon_father_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/blood_of_the_dragon_father/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/blood_of_the_dragon_father/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_dungeon_blood_thirsty_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/blood_thirsty/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/blood_thirsty/raw_translation_map/core_overlay'),
            },
        ],
    },
    "slayer": {
        "hubSid": 'homm3_11_ab_tower_slayer',
        "campaignHeroSid": 'homm3_tower_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_slayer'),
        "missions": (
            'homm3_ab_tower_crystal_dragons.json',
            'homm3_ab_tower_rust_dragons.json',
            'homm3_ab_tower_faerie_dragons.json',
            'homm3_ab_tower_azure_dragons.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_tower_crystal_dragons_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/crystal_dragons/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/crystal_dragons/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_tower_rust_dragons_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/rust_dragons/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/rust_dragons/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_tower_faerie_dragons_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/faerie_dragons/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/faerie_dragons/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_tower_azure_dragons_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/azure_dragons/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/azure_dragons/raw_translation_map/core_overlay'),
            },
        ],
    },
    "festival": {
        "hubSid": 'homm3_12_ab_stronghold_festival',
        "campaignHeroSid": 'homm3_stronghold_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_festival'),
        "missions": (
            'homm3_ab_stronghold_razor_claw.json',
            'homm3_ab_stronghold_taming_of_the_wild.json',
            'homm3_ab_stronghold_clan_war.json',
            'homm3_ab_stronghold_for_the_throne.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_stronghold_razor_claw_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/razor_claw/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/razor_claw/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_taming_of_the_wild_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/taming_of_the_wild/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/taming_of_the_wild/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_clan_war_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/clan_war/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/clan_war/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_for_the_throne_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/for_the_throne/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/for_the_throne/raw_translation_map/core_overlay'),
            },
        ],
    },
    "fire": {
        "hubSid": 'homm3_13_ab_fortress_fire',
        "campaignHeroSid": 'homm3_fortress_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_fire'),
        "missions": (
            'homm3_ab_fortress_farming_towns.json',
            'homm3_ab_fortress_march_of_the_undead.json',
            'homm3_ab_fortress_burning_of_tatalia.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_fortress_farming_towns_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/farming_towns/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/farming_towns/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_fortress_march_of_the_undead_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/march_of_the_undead/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/march_of_the_undead/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_fortress_burning_of_tatalia_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/burning_of_tatalia/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/burning_of_tatalia/raw_translation_map/core_overlay'),
            },
        ],
    },
    "fool": {
        "hubSid": 'homm3_14_ab_castle_fool',
        "campaignHeroSid": 'homm3_castle_hero_7',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_fool'),
        "missions": (
            'homm3_ab_castle_lost_at_sea.json',
            'homm3_ab_castle_their_end_of_the_bargain.json',
            'homm3_ab_castle_here_there_be_pirates.json',
            'homm3_ab_castle_hurry_up_and_wait.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_castle_lost_at_sea_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/lost_at_sea/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/lost_at_sea/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_castle_their_end_of_the_bargain_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/their_end_of_the_bargain/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/their_end_of_the_bargain/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_castle_here_there_be_pirates_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/here_there_be_pirates/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/here_there_be_pirates/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_castle_hurry_up_and_wait_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/hurry_up_and_wait/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/hurry_up_and_wait/raw_translation_map/core_overlay'),
            },
        ],
    },
    "sandro": {
        "hubSid": 'homm3_15_sod_necropolis_sandro',
        "campaignHeroSid": 'homm3_necropolis_hero_11',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_sandro'),
        "missions": (
            'homm3_sod_necropolis_target.json',
            'homm3_sod_necropolis_master.json',
            'homm3_sod_necropolis_finneas_vilmar.json',
            'homm3_sod_necropolis_duke_alarice.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_necropolis_target_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/target/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/target/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_master_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/master/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/master/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_finneas_vilmar_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/finneas_vilmar/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/finneas_vilmar/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_duke_alarice_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/duke_alarice/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/duke_alarice/raw_translation_map/core_overlay'),
            },
        ],
    },
    "crag": {
        "hubSid": 'homm3_16_sod_stronghold_crag',
        "campaignHeroSid": 'homm3_stronghold_hero_1',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_crag'),
        "missions": (
            'homm3_sod_stronghold_bashing_skulls.json',
            'homm3_sod_stronghold_black_sheep.json',
            'homm3_sod_stronghold_a_cage_in_the_hand.json',
            'homm3_sod_stronghold_grave_robber.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_stronghold_bashing_skulls_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/bashing_skulls/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/bashing_skulls/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_black_sheep_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/black_sheep/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/black_sheep/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_a_cage_in_the_hand_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_cage_in_the_hand/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_cage_in_the_hand/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_grave_robber_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/grave_robber/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/grave_robber/raw_translation_map/core_overlay'),
            },
        ],
    },
    "yog": {
        "hubSid": 'homm3_17_sod_stronghold_yog',
        "campaignHeroSid": 'homm3_stronghold_hero_5',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_yog'),
        "missions": (
            'homm3_sod_stronghold_on_the_run.json',
            'homm3_sod_stronghold_the_meeting.json',
            'homm3_sod_stronghold_a_tough_start.json',
            'homm3_sod_stronghold_falor_and_terwen.json',
            'homm3_sod_stronghold_returning_to_bracada.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_stronghold_on_the_run_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/on_the_run/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/on_the_run/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_the_meeting_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/the_meeting/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/the_meeting/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_a_tough_start_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_tough_start/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_tough_start/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_falor_and_terwen_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/falor_and_terwen/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/falor_and_terwen/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_stronghold_returning_to_bracada_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/returning_to_bracada/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/returning_to_bracada/raw_translation_map/core_overlay'),
            },
        ],
    },
    "gem": {
        "hubSid": 'homm3_18_sod_rampart_gem',
        "campaignHeroSid": 'homm3_rampart_hero_12',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_gem'),
        "missions": (
            'homm3_sod_rampart_clearing_the_border.json',
            'homm3_sod_rampart_after_the_amulet.json',
            'homm3_sod_rampart_retrieving_the_cowl.json',
            'homm3_sod_rampart_driving_for_the_boots.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_rampart_clearing_the_border_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/clearing_the_border/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/clearing_the_border/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_after_the_amulet_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/after_the_amulet/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/after_the_amulet/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_retrieving_the_cowl_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/retrieving_the_cowl/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/retrieving_the_cowl/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_driving_for_the_boots_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/driving_for_the_boots/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/driving_for_the_boots/raw_translation_map/core_overlay'),
            },
        ],
    },
    "gelu": {
        "hubSid": 'homm3_19_sod_rampart_gelu',
        "campaignHeroSid": 'homm3_rampart_hero_17',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_gelu'),
        "missions": (
            'homm3_sod_rampart_graduation_exercise.json',
            'homm3_sod_rampart_cutthroats.json',
            'homm3_sod_rampart_valley_of_the_dragon_lords.json',
            'homm3_sod_rampart_a_thief_in_the_night.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_rampart_graduation_exercise_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/graduation_exercise/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/graduation_exercise/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_cutthroats_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/cutthroats/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/cutthroats/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_valley_of_the_dragon_lords_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/valley_of_the_dragon_lords/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/valley_of_the_dragon_lords/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_rampart_a_thief_in_the_night_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_thief_in_the_night/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/a_thief_in_the_night/raw_translation_map/core_overlay'),
            },
        ],
    },
    "final": {
        "hubSid": 'homm3_20_sod_necropolis_final',
        "campaignHeroSid": 'homm3_stronghold_hero_5',
        "weaveDir": Path('artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_final'),
        "missions": (
            'homm3_sod_necropolis_harvest.json',
            'homm3_sod_necropolis_gathering_the_legion.json',
            'homm3_sod_necropolis_search_for_a_killer.json',
            'homm3_sod_necropolis_final_peace.json',
            'homm3_sod_necropolis_secrets_revealed.json',
            'homm3_sod_necropolis_agents_of_vengeance.json',
            'homm3_sod_necropolis_wrath_of_sandro.json',
            'homm3_sod_necropolis_invasion.json',
            'homm3_sod_necropolis_to_strive_to_seek.json',
            'homm3_sod_necropolis_barbarian_brothers.json',
            'homm3_sod_necropolis_union.json',
            'homm3_sod_necropolis_fall_of_sandro.json',
        ),
        "mapInstalls": [
            {
                "mapSid": 'h3_necropolis_harvest_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/harvest/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/harvest/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_gathering_the_legion_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/gathering_the_legion/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/gathering_the_legion/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_search_for_a_killer_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/search_for_a_killer/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/search_for_a_killer/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_final_peace_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/final_peace/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/final_peace/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_secrets_revealed_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/secrets_revealed/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/secrets_revealed/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_agents_of_vengeance_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/agents_of_vengeance/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/agents_of_vengeance/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_wrath_of_sandro_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/wrath_of_sandro/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/wrath_of_sandro/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_invasion_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/invasion/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/invasion/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_to_strive_to_seek_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/to_strive_to_seek/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/to_strive_to_seek/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_barbarian_brothers_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/barbarian_brothers/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/barbarian_brothers/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_union_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/union/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/union/raw_translation_map/core_overlay'),
            },
            {
                "mapSid": 'h3_necropolis_fall_of_sandro_raw_translation',
                "artifact": Path('artifacts/campaign_port_poc/ab_sod_campaigns/fall_of_sandro/raw_translation_map/maps'),
                "coreOverlay": Path('artifacts/campaign_port_poc/ab_sod_campaigns/fall_of_sandro/raw_translation_map/core_overlay'),
            },
        ],
    },
    # --- END AB/SoD HUB_CONFIGS ---
}


_ROSTER_HERO_MEMBER_RE = re.compile(
    r"^DB/heroes/(homm3_[^/]+)/(homm3_.+_hero_\d+)\.json$"
)


def collect_homm3_roster_hero_sids(source: zipfile.ZipFile) -> set[str]:
    """Town-roster HoMM3 hero SIDs that have real DB/heroes rows (Quick Play eligible)."""
    sids: set[str] = set()
    for name in source.namelist():
        match = _ROSTER_HERO_MEMBER_RE.match(name.replace("\\", "/"))
        if match:
            sids.add(match.group(2))
    return sids


def fail(message: str) -> None:
    raise SystemExit(f"roe castle continuity install failed: {message}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _regen_one_hub(job: tuple[str, str, str]) -> dict[str, Any]:
    repo_root, game_root, hub = job
    t0 = time.perf_counter()
    script = Path(repo_root) / "experiments" / "campaign_port_poc" / "build_roe_castle_continuity_weave.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            repo_root,
            "--game-root",
            game_root,
            "--hub",
            hub,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"weave regeneration failed for {hub}:\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )
    return {"hub": hub, "elapsedSec": round(time.perf_counter() - t0, 3)}


def regenerate_weaves_parallel(
    repo_root: Path, game_root: Path, hubs: list[str], *, jobs: int
) -> list[dict[str, Any]]:
    work = [(str(repo_root), str(game_root), hub) for hub in hubs]
    if jobs <= 1 or len(work) <= 1:
        return [_regen_one_hub(item) for item in work]
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_regen_one_hub, item): item[2] for item in work}
        for fut in concurrent.futures.as_completed(futures):
            hub = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                fail(f"weave regeneration failed for {hub}: {exc}")
            _log(f"  weave ok {row['hub']} ({row['elapsedSec']}s)")
            rows.append(row)
    return rows


def regenerate_weave(repo_root: Path, game_root: Path, hub: str) -> None:
    row = _regen_one_hub((str(repo_root), str(game_root), hub))
    _log(f"  weave ok {row['hub']} ({row['elapsedSec']}s)")


def collect_raw_overlay_members_for_hubs(
    repo_root: Path,
    hub_jobs: list[dict[str, Any]],
    *,
    jobs: int = 1,
) -> dict[str, bytes]:
    """Collect+merge mission overlays for every hub (optionally parallel per hub)."""

    def _one(job: dict[str, Any]) -> dict[str, bytes]:
        return collect_raw_overlay_members(repo_root, job["hubCfg"]["mapInstalls"])

    overlay_members: dict[str, bytes] = {}
    if jobs <= 1 or len(hub_jobs) <= 1:
        parts = [_one(job) for job in hub_jobs]
    else:
        parts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(_one, job) for job in hub_jobs]
            for fut in concurrent.futures.as_completed(futures):
                parts.append(fut.result())
    for part in parts:
        overlay_members = merge_overlay_member_dicts(overlay_members, part)
    return overlay_members


def require_payload(repo_root: Path, hub_cfg: dict[str, Any]) -> Path:
    payload = repo_root / hub_cfg["weaveDir"] / "campaign_payload"
    hub_sid = hub_cfg["hubSid"]
    required = [
        payload / "storyHub.json",
        payload / "heroes.json",
        payload / "fractions.json",
        payload / "storyCounters.json",
        payload / "perks.json",
        payload / "lang_tokens.json",
        *[payload / "missions" / name for name in hub_cfg["missions"]],
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        fail("missing campaign payload files:\n- " + "\n- ".join(missing))
    story = load_json(payload / "storyHub.json")
    if story.get("transferHeroProgressFromSession") is not True:
        fail("storyHub.json must set transferHeroProgressFromSession true")
    if story.get("sid") != hub_sid:
        fail(f"storyHub.sid must be {hub_sid}")
    expected_hero = str(hub_cfg.get("campaignHeroSid") or "").strip()
    heroes = load_json(payload / "heroes.json")
    rows = heroes.get("array") if isinstance(heroes, dict) else None
    installed_ids = [
        str(row.get("id") or "")
        for row in (rows or [])
        if isinstance(row, dict)
    ]
    if expected_hero and expected_hero not in installed_ids:
        fail(
            f"campaign_payload/heroes.json must list campaignHeroSid {expected_hero!r} "
            f"(got {installed_ids!r}). Stale weave payloads ship the wrong starting hero "
            f"(e.g. Playing with Fire previously installed necropolis_hero_1 instead of "
            f"fortress Adrienne). Re-run weave regen for hub {hub_cfg.get('hub')!r}."
        )
    # Fail closed: every mission fixedHeroesSet entry must be present in heroes.json
    # (multi-protagonist hubs such as AB / Unholy Alliance).
    locked_heroes: set[str] = set()
    for mission_name in hub_cfg["missions"]:
        mission_doc = load_json(payload / "missions" / mission_name)
        mission_rows = mission_doc.get("array") if isinstance(mission_doc, dict) else None
        if not mission_rows:
            continue
        first = mission_rows[0] if isinstance(mission_rows[0], dict) else {}
        for hero_id in first.get("fixedHeroesSet") or []:
            sid = str(hero_id or "").strip()
            if sid:
                locked_heroes.add(sid)
    missing_locked = sorted(sid for sid in locked_heroes if sid not in installed_ids)
    if missing_locked:
        fail(
            f"campaign_payload/heroes.json missing locked mission heroes {missing_locked!r} "
            f"(heroes.json has {installed_ids!r}). Re-run weave regen so missionSpawns "
            f"union is emitted."
        )
    unlock_validator = repo_root / "tools" / "validate_storyhub_delayed_hero_unlock_contract.py"
    if unlock_validator.is_file():
        tools_dir = str(repo_root / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from validate_storyhub_delayed_hero_unlock_contract import (  # noqa: WPS433
            validate_payload_dir,
        )

        unlock_errors = validate_payload_dir(payload)
        if unlock_errors:
            fail(
                "StoryHub delayed hero unlock contract failed:\n- "
                + "\n- ".join(unlock_errors)
            )
    return payload


def backup_file(path: Path, backup_suffix: str) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(path.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    shutil.copy2(path, backup)
    return backup


def _apply_objective_bullets_after_map_install(
    dst_map: Path, result_row: dict[str, Any], english_rows: dict[str, str]
) -> None:
    """Rewrite quest-log bullets on the installed map; accumulate LocKit English rows."""
    from campaign_objective_install import (
        apply_objective_bullets_to_map,
        lockit_rows_from_patch_report,
    )

    try:
        obj_report = apply_objective_bullets_to_map(dst_map)
    except Exception as exc:
        fail(f"objective bullet rewrite failed for {dst_map.name}: {exc}")
    english_rows.update(lockit_rows_from_patch_report(obj_report))
    result_row["objectiveBullets"] = obj_report["bulletCount"]
    result_row["missionId"] = obj_report["missionId"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def install_maps(
    repo_root: Path,
    game_root: Path,
    backup_suffix: str,
    map_installs: list[dict[str, Any]],
    *,
    skip_unchanged_maps: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    maps_dir = game_root / MAPS_REL
    maps_root = game_root / MAPS_ROOT_REL
    maps_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    objective_english: dict[str, str] = {}
    for row in map_installs:
        sid = row["mapSid"]
        src_dir = repo_root / row["artifact"]
        src_map = src_dir / f"{sid}.map"
        src_json = src_dir / f"{sid}.json"
        dst_map = maps_dir / f"{sid}.map"
        dst_json = maps_dir / f"{sid}.json"
        # Remove stale maps/-root copies so StoryHub QuestScript cannot double-register.
        for stale_name in (f"{sid}.map", f"{sid}.json"):
            stale = maps_root / stale_name
            if stale.is_file():
                backup_file(stale, backup_suffix)
                stale.unlink()
                results.append(
                    {
                        "mapSid": sid,
                        "action": "removed_maps_root_duplicate",
                        "path": str(stale),
                        "policy": INSTALL_DESTINATION_POLICY,
                    }
                )
        if not src_map.is_file():
            if dst_map.is_file():
                from map_load_preflight import (
                    rewrite_map_file_expand_meta_random_res,
                )

                expanded = rewrite_map_file_expand_meta_random_res(dst_map)
                kept: dict[str, Any] = {
                    "mapSid": sid,
                    "action": "kept_existing_installed",
                    "path": str(dst_map),
                    "expandedMetaRandomRes": expanded,
                    "rarityPolicy": "homm3_rarity_bin_to_olden_erarity_v1_generator_owned",
                }
                _apply_objective_bullets_after_map_install(
                    dst_map, kept, objective_english
                )
                results.append(kept)
                continue
            fail(f"missing map artifact and no installed map for {sid}: {src_map}")
        unchanged = (
            skip_unchanged_maps
            and dst_map.is_file()
            and _sha256_file(src_map) == _sha256_file(dst_map)
        )
        if unchanged:
            copied: dict[str, Any] = {
                "mapSid": sid,
                "action": "skipped_unchanged_map",
                "path": str(dst_map),
                "expandedMetaRandomRes": False,
                "rarityPolicy": "homm3_rarity_bin_to_olden_erarity_v1_generator_owned",
            }
            _apply_objective_bullets_after_map_install(dst_map, copied, objective_english)
            results.append(copied)
        else:
            backup_file(dst_map, backup_suffix)
            if src_json.is_file():
                backup_file(dst_json, backup_suffix)
                shutil.copy2(src_json, dst_json)
            shutil.copy2(src_map, dst_map)
            from map_load_preflight import (
                rewrite_map_file_expand_meta_random_res,
            )

            expanded = rewrite_map_file_expand_meta_random_res(dst_map)
            copied = {
                "mapSid": sid,
                "action": "copied_from_artifact",
                "path": str(dst_map),
                "expandedMetaRandomRes": expanded,
                "rarityPolicy": "homm3_rarity_bin_to_olden_erarity_v1_generator_owned",
            }
            _apply_objective_bullets_after_map_install(dst_map, copied, objective_english)
            results.append(copied)
        root_dup = maps_root / f"{sid}.map"
        if root_dup.is_file() and dst_map.is_file():
            fail(
                f"dual mapSid install forbidden ({INSTALL_DESTINATION_POLICY}): "
                f"{root_dup} and {dst_map} both exist"
            )
    return results, objective_english


def collect_icon_bytes(core_zip: Path, payload: Path | None = None) -> dict[str, bytes]:
    """Prefer weave campaign_payload/icons overlays; otherwise clone mainStory icons."""
    resolved = core_zip.resolve()
    stat = resolved.stat()
    cache_key = (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    icons = _CORE_ICON_CACHE.get(cache_key)
    if icons is None:
        icons = {}
        with zipfile.ZipFile(core_zip, "r") as source:
            names = set(source.namelist())
            for name in (
                "campaigns/mainStory/icons/main_icon.png",
                "campaigns/mainStory/icons/hub_icon.png",
                "campaigns/mainStory/icons/save_icon.png",
            ):
                if name in names:
                    icons[Path(name).name] = source.read(name)
        # hubIconSid is save_icon in storyHub; mainStory stores hub_icon.png — map both.
        if "hub_icon.png" in icons and "save_icon.png" not in icons:
            icons["save_icon.png"] = icons["hub_icon.png"]
        if "main_icon.png" not in icons:
            fail("Core.zip missing campaigns/mainStory/icons/main_icon.png to clone")
        _CORE_ICON_CACHE[cache_key] = icons
    icons = dict(icons)
    if payload is not None:
        icon_dir = payload / "icons"
        for name in ("main_icon.png", "hub_icon.png", "save_icon.png"):
            override = icon_dir / name
            if override.is_file():
                icons[name] = override.read_bytes()
    return icons


def merge_lang_campaign(existing: dict[str, Any], tokens: list[dict[str, str]]) -> dict[str, Any]:
    by_sid = {str(t["sid"]): t for t in tokens if isinstance(t, dict) and "sid" in t}
    for key in ("tokens", "array"):
        rows = list(existing.get(key) or [])
        present = {str(row.get("sid")) for row in rows if isinstance(row, dict)}
        for sid, token in by_sid.items():
            if sid in present:
                for row in rows:
                    if isinstance(row, dict) and row.get("sid") == sid:
                        row["text"] = token["text"]
            else:
                rows.append({"sid": sid, "text": token["text"]})
                present.add(sid)
        existing[key] = rows
    return existing


def _try_parse_lang_sid_catalog(raw: bytes) -> dict[str, Any] | None:
    """Return a Lang text doc when it has tokens/array rows keyed by ``sid``."""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    has_sid_rows = False
    for key in ("tokens", "array"):
        rows = doc.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        if all(isinstance(row, dict) and isinstance(row.get("sid"), str) for row in rows):
            has_sid_rows = True
        else:
            return None
    return doc if has_sid_rows else None


def merge_lang_sid_catalog_bytes(
    base: bytes | None, overlay: bytes, *, member: str
) -> bytes:
    """SID-keyed merge for Lang text catalogs (``tokens`` + ``array``).

    Whole-file later-wins previously let Good2's last map (Tunnels) wipe Steadwick
    dialog/quest/city LocKit rows from Core.zip, leaving Loc: placeholders.
    Overlay rows win per sid; every overlay sid is written into both ``tokens`` and
    ``array`` so tokens-only dialog bodies become runtime-visible.
    """
    overlay_doc = _try_parse_lang_sid_catalog(overlay)
    if overlay_doc is None:
        return overlay
    if base is None:
        merged: dict[str, Any] = {"tokens": [], "array": []}
    else:
        base_doc = _try_parse_lang_sid_catalog(base)
        if base_doc is None:
            fail(f"cannot sid-merge Lang catalog {member}: base is not a sid-array JSON object")
        merged = {
            "tokens": list(base_doc.get("tokens") or []),
            "array": list(base_doc.get("array") or []),
        }
        for key, value in base_doc.items():
            if key not in ("tokens", "array"):
                merged[key] = value

    overlay_by_sid: dict[str, str] = {}
    for key in ("tokens", "array"):
        for row in overlay_doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            text = row.get("text")
            if isinstance(sid, str) and isinstance(text, str):
                overlay_by_sid[sid] = text
    if not overlay_by_sid:
        return overlay

    rows = [{"sid": sid, "text": text} for sid, text in overlay_by_sid.items()]
    merge_lang_campaign(merged, rows)
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def strip_private_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: strip_private_fields(value)
            for key, value in payload.items()
            if not str(key).startswith("_")
        }
    if isinstance(payload, list):
        return [strip_private_fields(item) for item in payload]
    return payload


RESOURCES_LOGIC_MEMBER = "DB/objects_logic/res/resources.json"
CAMP_FIRE_META_ALIASES_MEMBER = "DB/map/objects/homm3_camp_fire_meta_aliases.json"
CAMP_FIRE_META_ALIAS_IDS = ("camp_fire_1", "camp_fire_2", "camp_fire_3")


def build_campaign_members(
    payload: Path, icons: dict[str, bytes], hub_cfg: dict[str, Any]
) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    root = f"campaigns/{hub_cfg['hubSid']}"
    for name in ("storyHub.json", "heroes.json", "fractions.json", "storyCounters.json", "perks.json"):
        data = strip_private_fields(load_json(payload / name))
        members[f"{root}/{name}"] = (
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    for mission in hub_cfg["missions"]:
        data = strip_private_fields(load_json(payload / "missions" / mission))
        members[f"{root}/missions/{mission}"] = (
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    members[f"{root}/icons/main_icon.png"] = icons["main_icon.png"]
    members[f"{root}/icons/hub_icon.png"] = icons.get("hub_icon.png", icons["main_icon.png"])
    members[f"{root}/icons/save_icon.png"] = icons.get(
        "save_icon.png", icons.get("hub_icon.png", icons["main_icon.png"])
    )
    return members


def _try_parse_id_array_catalog(raw: bytes) -> list[dict[str, Any]] | None:
    """Return rows when ``raw`` is a JSON object with ``array`` of dicts that have ``id``."""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    rows = doc.get("array")
    if not isinstance(rows, list):
        return None
    # Empty catalogs are valid (prior installs may leave empty overlay stubs in Core).
    if not rows:
        return []
    if not all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows):
        return None
    return rows


def merge_id_array_catalog_bytes(
    base: bytes | None,
    overlay: bytes,
    *,
    member: str,
    drop_unreferenced_base_xfp: bool = False,
) -> bytes:
    """Id-keyed merge for Core catalog JSON (``{"array":[{"id":...},...]}``).

    Whole-file later-wins is wrong for mission-scoped catalogs such as
    ``DB/buildings_constructions/custom_maps_buildings_presets.json``: Good2's
    last map (Tunnels) previously replaced Steadwick/Deal/Neutral town
    construction rows and left Liberation cities resolving missing
    ``homecoming_h3_town_construction_*`` configs at Loader time.

    When ``drop_unreferenced_base_xfp`` is true (Core←overlay install only),
    prior ``homm3_xfp_*`` ObjectConfig rows in
    ``homecoming_exact_footprint_objects.json`` that are absent from the current
    overlay set are dropped. That retires resized mine clones without wiping
    sibling hub/mission clones during overlay-to-overlay merges.
    """
    # Fail closed: returning ``overlay`` alone would wipe previously merged hub
    # rows (e.g. Homecoming Mirham/Trailia/Terraneus construction SIDs).
    overlay_rows = _try_parse_id_array_catalog(overlay)
    if overlay_rows is None:
        fail(
            f"cannot id-merge catalog {member}: overlay is not an id-array JSON object"
        )
    drop_base_xfp = drop_unreferenced_base_xfp and (
        member.replace("\\", "/").endswith(
            "DB/map/objects/homecoming_exact_footprint_objects.json"
        )
        or (
            member.replace("\\", "/").startswith("DB/objects_logic/")
            and member.replace("\\", "/").endswith(".json")
        )
    )
    by_id: dict[str, dict[str, Any]] = {}
    if base is not None:
        base_rows = _try_parse_id_array_catalog(base)
        if base_rows is None:
            fail(
                f"cannot id-merge catalog {member}: base is not an id-array JSON object"
            )
        for row in base_rows:
            row_id = str(row["id"])
            if drop_base_xfp and row_id.startswith("homm3_xfp_"):
                continue
            by_id[row_id] = row
    for row in overlay_rows:
        by_id[str(row["id"])] = row
    merged = {"array": list(by_id.values())}
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _campaign_lang_sid_allowlist(overlay_root: Path) -> set[str] | None:
    """Return SID allowlist for a mission overlay, or None to keep the full file.

    Raw-translation Lang overlays are near-full Core dumps. Merging them wholesale
    across four Good2 missions is multi-minute and race-prone. Keep only campaign-port
    rows: menu/quest shells, land-on object names, dialog bodies, and registered cities.
    """
    cache_key = str(overlay_root.resolve())
    if cache_key in _LANG_ALLOWLIST_CACHE:
        return _LANG_ALLOWLIST_CACHE[cache_key]
    allowed = _compute_campaign_lang_sid_allowlist(overlay_root)
    _LANG_ALLOWLIST_CACHE[cache_key] = allowed
    return allowed


def _compute_campaign_lang_sid_allowlist(overlay_root: Path) -> set[str] | None:
    allowed: set[str] = set()
    tools_parent = Path(__file__).resolve().parents[1]
    exp = tools_parent / "experiments" / "campaign_port_poc"
    if str(exp) not in sys.path:
        sys.path.insert(0, str(exp))
    try:
        import homecoming_localization as homecoming_lang
    except Exception:
        return None

    allowed.update(homecoming_lang.CUSTOM_MAPS_EN.keys())
    allowed.update(homecoming_lang.MAP_OBJECTS_EN.keys())
    allowed.update(homecoming_lang.CITIES_EN.keys())
    allowed.update(homecoming_lang.DIALOGUE_SIDS)

    dialog_root = overlay_root / "DB" / "dialogs"
    if dialog_root.is_dir():
        for path in dialog_root.rglob("*.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            for row in doc.get("array") or []:
                if not isinstance(row, dict):
                    continue
                dialog_id = str(row.get("id") or "").strip()
                if not dialog_id:
                    continue
                if dialog_id == "homecoming_intro_dialog":
                    allowed.add("dialogue_title_homecoming_intro")
                    allowed.add("dialogue_text_homecoming_intro_0")
                else:
                    allowed.add(f"dialogue_title_{dialog_id}")
                    allowed.add(f"dialogue_text_{dialog_id}_0")
                for slide in row.get("slides") or []:
                    if not isinstance(slide, dict):
                        continue
                    title = slide.get("title")
                    if isinstance(title, dict) and isinstance(title.get("sid"), str):
                        allowed.add(str(title["sid"]))
                    text = slide.get("text")
                    if isinstance(text, str) and text.startswith("dialogue_"):
                        allowed.add(text)
                    for answer in slide.get("answers") or []:
                        if not isinstance(answer, dict):
                            continue
                        answer_text = answer.get("text")
                        if isinstance(answer_text, str) and answer_text.startswith("dialogue_"):
                            allowed.add(answer_text)

    # Preserve mission-registered city LocKit SIDs already present in the overlay.
    cities_path = overlay_root / "Lang" / "english" / "texts" / "cities.json"
    if cities_path.is_file():
        try:
            cities = json.loads(cities_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            cities = {}
        for section in ("tokens", "array"):
            for row in cities.get(section) or []:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid")
                if not isinstance(sid, str):
                    continue
                # Any PropCity customCityName LocKit SID ({mission}_city_name_* or
                # legacy homecoming_/campaign_ prefixes). Do not gate on an early
                # Castle mission mid-list — operator-precedence previously dropped
                # a_gryphons_heart_city_name_* and every other non-listed mission.
                if (
                    sid.startswith("homecoming_city_name_")
                    or sid.startswith("campaign_city_name_")
                    or "_city_name_" in sid
                ):
                    allowed.add(sid)
    custom_maps_path = overlay_root / "Lang" / "english" / "texts" / "customMaps.json"
    if custom_maps_path.is_file():
        try:
            custom_maps = json.loads(custom_maps_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            custom_maps = {}
        for section in ("tokens", "array"):
            for row in custom_maps.get(section) or []:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid")
                if not isinstance(sid, str):
                    continue
                if (
                    "_main_goal_obj_" in sid
                    or sid.endswith("_main_goal")
                    or sid.endswith("_main_goal_desc")
                    or sid.endswith("_intro")
                ):
                    allowed.add(sid)
    return allowed


def filter_lang_overlay_to_campaign_sids(
    raw: bytes,
    *,
    overlay_root: Path,
    member: str,
    allow: set[str] | None = None,
) -> bytes:
    if allow is None:
        allow = _campaign_lang_sid_allowlist(overlay_root)
    if allow is None:
        return raw
    allow_fp = hashlib.sha256("\0".join(sorted(allow)).encode("utf-8")).hexdigest()
    raw_fp = hashlib.sha256(raw).hexdigest()
    cache_key = (raw_fp, allow_fp)
    cached = _LANG_FILTER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    doc = _try_parse_lang_sid_catalog(raw)
    if doc is None:
        _LANG_FILTER_CACHE[cache_key] = raw
        return raw
    filtered: dict[str, Any] = {
        key: value for key, value in doc.items() if key not in ("tokens", "array")
    }
    kept_by_sid: dict[str, str] = {}
    for key in ("tokens", "array"):
        for row in doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            text = row.get("text")
            if isinstance(sid, str) and sid in allow and isinstance(text, str):
                kept_by_sid[sid] = text
    if not kept_by_sid:
        # Empty campaign delta — skip installing this Lang member from this overlay.
        _LANG_FILTER_CACHE[cache_key] = b""
        return b""
    rows = [{"sid": sid, "text": text} for sid, text in kept_by_sid.items()]
    filtered["tokens"] = list(rows)
    filtered["array"] = list(rows)
    result = (json.dumps(filtered, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _LANG_FILTER_CACHE[cache_key] = result
    return result


def collect_h3_campaign_placed_heroes_overlay(repo_root: Path) -> dict[str, Any]:
    """Load generated campaign-only H3 placed-hero stubs for Core merge.

    Overlay root: ``artifacts/campaign_port_poc/h3_campaign_placed_heroes_overlay``.
    Returns overlay member bytes plus campaignHeroes SID list. Empty if not generated.
    """
    overlay_root = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "h3_campaign_placed_heroes_overlay"
    )
    if not overlay_root.is_dir():
        return {"members": {}, "campaignHeroes": [], "overlayRoot": str(overlay_root)}

    members: dict[str, bytes] = {}
    for path in sorted(overlay_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(overlay_root).as_posix()
        if relative in {"overlay_manifest.json"}:
            continue
        if relative.endswith(".h3_campaign_placed.json"):
            # Sidecar Loc is merged into canonical heroInfo/heroes below.
            continue
        if relative.startswith("DB/heroes/campaign/") and relative.endswith(".json"):
            members[relative] = path.read_bytes()
            continue
        if relative == "DB/h3_campaign_placed_heroes_catalog.json":
            members[relative] = path.read_bytes()
            continue

    catalog_path = overlay_root / "DB" / "h3_campaign_placed_heroes_catalog.json"
    campaign_heroes: list[str] = []
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        campaign_heroes = [
            str(sid)
            for sid in (catalog.get("campaignHeroes") or [])
            if isinstance(sid, str) and sid
        ]

    hero_info_path = overlay_root / "Lang" / "english" / "texts" / "heroInfo.h3_campaign_placed.json"
    heroes_path = overlay_root / "Lang" / "english" / "texts" / "heroes.h3_campaign_placed.json"
    if hero_info_path.is_file():
        members["Lang/english/texts/heroInfo.json"] = hero_info_path.read_bytes()
    if heroes_path.is_file():
        members["Lang/english/texts/heroes.json"] = heroes_path.read_bytes()

    return {
        "members": members,
        "campaignHeroes": campaign_heroes,
        "overlayRoot": str(overlay_root),
    }


def collect_raw_overlay_members(
    repo_root: Path, map_installs: list[dict[str, Any]]
) -> dict[str, bytes]:
    """Merge DB/ + Lang/ members from each mapInstalls coreOverlay.

    Binary / non-catalog files: later path wins.
    Id-array JSON catalogs: merge by ``id`` (later path wins per id).
    Lang text catalogs (``tokens``/``array`` + ``sid``): merge by ``sid`` after
    filtering each mission overlay down to campaign-port SIDs only.
    """
    members: dict[str, bytes] = {}
    for row in map_installs:
        overlay_rel = row.get("coreOverlay")
        if overlay_rel is None:
            continue
        overlay_root = repo_root / overlay_rel
        if not overlay_root.is_dir():
            fail(f"missing core overlay for {row['mapSid']}: {overlay_root}")
        allow = _campaign_lang_sid_allowlist(overlay_root)
        lang_jobs: list[tuple[Path, str]] = []
        other_files: list[tuple[Path, str]] = []
        for path in overlay_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(overlay_root).as_posix()
            if relative.endswith("_overlay_manifest.json"):
                continue
            if relative == "quickStart.json":
                members["DB/quickStart.json"] = path.read_bytes()
                continue
            if not (relative.startswith("DB/") or relative.startswith("Lang/")):
                continue
            if relative.startswith("Lang/") and relative.endswith(".json"):
                lang_jobs.append((path, relative))
            else:
                other_files.append((path, relative))

        # Lang dumps dominate I/O; fingerprint-cache + thread pool across locales.
        if lang_jobs:
            def _one(job: tuple[Path, str]) -> tuple[str, bytes]:
                path, relative = job
                return relative, _filter_lang_path(
                    path, overlay_root=overlay_root, relative=relative, allow=allow
                )

            # json parsing holds the GIL, so more threads add peak memory (one parsed
            # multi-MB dump in flight each, times the per-hub --jobs) but little speed.
            workers = max(1, min(2, len(lang_jobs)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                for relative, raw in pool.map(_one, lang_jobs):
                    if not raw:
                        continue
                    if relative in members:
                        members[relative] = merge_lang_sid_catalog_bytes(
                            members[relative], raw, member=relative
                        )
                    else:
                        members[relative] = merge_lang_sid_catalog_bytes(
                            None, raw, member=relative
                        )

        for path, relative in other_files:
            raw = path.read_bytes()
            if _try_parse_id_array_catalog(raw) is not None:
                members[relative] = merge_id_array_catalog_bytes(
                    members.get(relative), raw, member=relative
                )
            elif relative in members and _try_parse_id_array_catalog(
                members[relative]
            ) is not None:
                fail(
                    f"core overlay {relative} for {row['mapSid']} is not an id-array "
                    "catalog but an earlier mission already contributed id-array rows; "
                    "refusing whole-file clobber"
                )
            else:
                members[relative] = raw
    return members


def is_stale_duplicate_campaign_dialog_member(name: str) -> bool:
    """Legacy packaged dialog folders reuse primary dialog ids without portraits.

    Patterns seen in Core.zip that last-wins wipe planned avatars:
    - ``*AbSod``
    - ``*RoeDungeon`` / ``*RoeNeutral`` / ``*RoeInferno`` / ``*RoeNecropolis`` / …

    Canonical emit uses ``campaign_dialog_folder_name()`` only (e.g. ``TheGrail``).
    """
    marker = "DB/dialogs/dialogs/custom_maps/"
    if not name.startswith(marker) or not name.endswith(".json"):
        return False
    folder = name[len(marker) :].split("/", 1)[0]
    stale_suffixes = (
        "AbSod",
        "RoeDungeon",
        "RoeNeutral",
        "RoeInferno",
        "RoeNecropolis",
        "RoeCastle",
        "RoeRampart",
    )
    return any(folder.endswith(suffix) for suffix in stale_suffixes)


# Back-compat alias used by older call sites / scrub tool imports.
def is_stale_absod_dialog_member(name: str) -> bool:
    return is_stale_duplicate_campaign_dialog_member(name)


def hub_sid_from_campaign_member(name: str) -> str | None:
    """Return hub SID for campaigns/<hub>/… members; else None."""
    if not name.startswith("campaigns/"):
        return None
    parts = name.split("/")
    if len(parts) < 2 or not parts[1]:
        return None
    return parts[1]


def is_orphan_homm3_campaign_member(name: str) -> bool:
    """True for stale/non-canonical homm3_* StoryHub folders left in Core.zip."""
    hub = hub_sid_from_campaign_member(name)
    if hub is None or not hub.startswith("homm3_"):
        return False
    if hub in STALE_HOMM3_HUB_SIDS:
        return True
    # Any play-order-looking or legacy homm3 hub not in the canonical 20.
    return hub not in CANONICAL_HOMM3_HUB_SIDS


def scrub_orphan_homm3_campaign_tokens(doc: dict[str, Any]) -> list[str]:
    """Drop LocKit rows whose SID belongs to a scrubbed orphan hub."""
    removed: list[str] = []

    def is_orphan_sid(sid: str) -> bool:
        if not sid:
            return False
        for stale in STALE_HOMM3_HUB_SIDS:
            if (
                sid == stale
                or sid == f"campaign_{stale}"
                or sid.startswith(f"{stale}_")
                or f"_{stale}_" in sid
            ):
                return True
        # Playing with Fire necropolis packaging leftovers (hub + mission configs).
        if "necropolis_fire" in sid or sid.startswith("homm3_ab_necropolis_"):
            return True
        if sid.startswith("homm3_"):
            hub = sid[len("campaign_") :] if sid.startswith("campaign_") else sid
            hub = hub.split("_title", 1)[0]
            if hub in STALE_HOMM3_HUB_SIDS:
                return True
            if (
                hub.startswith("homm3_")
                and hub not in CANONICAL_HOMM3_HUB_SIDS
                and re.fullmatch(r"homm3_\d{2}_[a-z0-9_]+", hub)
            ):
                return True
        return False

    for key in ("tokens", "array"):
        rows = doc.get(key)
        if not isinstance(rows, list):
            continue
        kept: list[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            sid = str(row.get("sid") or "")
            if is_orphan_sid(sid):
                removed.append(sid)
            else:
                kept.append(row)
        doc[key] = kept
    return sorted(set(removed))


def merge_overlay_member_dicts(
    left: dict[str, bytes], right: dict[str, bytes]
) -> dict[str, bytes]:
    """Merge two core-overlay member maps with the same rules as collect_raw_overlay_members."""
    members = dict(left)
    for relative, raw in right.items():
        if relative.startswith("Lang/") and relative.endswith(".json"):
            members[relative] = merge_lang_sid_catalog_bytes(
                members.get(relative), raw, member=relative
            )
        elif _try_parse_id_array_catalog(raw) is not None:
            members[relative] = merge_id_array_catalog_bytes(
                members.get(relative), raw, member=relative
            )
        elif relative in members and _try_parse_id_array_catalog(members[relative]) is not None:
            fail(
                f"core overlay {relative} is not an id-array catalog but an earlier hub "
                "already contributed id-array rows; refusing whole-file clobber"
            )
        else:
            members[relative] = raw
    return members


def patch_core_zip(
    repo_root: Path,
    game_root: Path,
    payload: Path,
    backup_suffix: str,
    hub_cfg: dict[str, Any],
    objective_english: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Single-hub Core.zip patch (compatibility wrapper around multi-hub write)."""
    return patch_core_zip_for_hubs(
        repo_root,
        game_root,
        backup_suffix,
        [
            {
                "hubKey": str(hub_cfg.get("hubSid") or "hub"),
                "payload": payload,
                "hubCfg": hub_cfg,
                "objectiveEnglish": dict(objective_english or {}),
            }
        ],
    )


def patch_core_zip_for_hubs(
    repo_root: Path,
    game_root: Path,
    backup_suffix: str,
    hub_jobs: list[dict[str, Any]],
    *,
    overlay_jobs: int = 1,
) -> dict[str, Any]:
    """Rewrite Core.zip once for one or more StoryHubs.

    Each hub_jobs entry: hubKey, payload (Path), hubCfg, objectiveEnglish (dict).
    """
    if not hub_jobs:
        fail("patch_core_zip_for_hubs requires at least one hub job")
    core_zip = game_root / CORE_ZIP_REL
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")

    campaign_members: dict[str, bytes] = {}
    lang_tokens_by_sid: dict[str, dict[str, str]] = {}
    objective_english: dict[str, str] = {}
    map_sids: list[str] = []
    hero_sids: list[str] = []

    t_overlay = time.perf_counter()
    overlay_members = collect_raw_overlay_members_for_hubs(
        repo_root, hub_jobs, jobs=overlay_jobs
    )
    _log(
        f"  overlay collect+merge members={len(overlay_members)} "
        f"({round(time.perf_counter() - t_overlay, 2)}s)"
    )

    for job in hub_jobs:
        payload = Path(job["payload"])
        hub_cfg = job["hubCfg"]
        icons = collect_icon_bytes(core_zip, payload)
        campaign_members.update(build_campaign_members(payload, icons, hub_cfg))
        tokens = load_json(payload / "lang_tokens.json").get("array") or []
        if not tokens:
            fail(f"lang_tokens.json missing array for hub {job.get('hubKey')}")
        for token in tokens:
            if isinstance(token, dict) and isinstance(token.get("sid"), str):
                lang_tokens_by_sid[str(token["sid"])] = {
                    "sid": str(token["sid"]),
                    "text": str(token.get("text") or ""),
                }
        objective_english.update(dict(job.get("objectiveEnglish") or {}))
        for row in hub_cfg["mapInstalls"]:
            map_sids.append(str(row["mapSid"]))
        hero_sids.append(str(hub_cfg.get("campaignHeroSid") or "homm3_castle_hero_7"))

    overlay_members = {
        name: data
        for name, data in overlay_members.items()
        if not is_stale_absod_dialog_member(name)
    }
    placed_hero_overlay = collect_h3_campaign_placed_heroes_overlay(repo_root)
    overlay_members = merge_overlay_member_dicts(
        overlay_members,
        placed_hero_overlay["members"],
    )
    objective_lockit_report: dict[str, Any] = {"langs": 0, "sids": 0}
    if objective_english:
        from campaign_objective_install import inject_objective_lockit_into_overlay_members

        objective_lockit_report = inject_objective_lockit_into_overlay_members(
            overlay_members, objective_english
        )
    lang_tokens = list(lang_tokens_by_sid.values())

    backup = core_zip.with_name(core_zip.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")

    temp_dir = Path(tempfile.mkdtemp(prefix="roe_castle_continuity_core_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    # Read from a private copy so AV/Steam cannot race the live Core.zip mid-rewrite.
    temp_source_zip = temp_dir / f"source_{core_zip.name}"
    shutil.copy2(core_zip, temp_source_zip)
    lang_updated = 0
    roster_heroes_scrubbed: list[str] = []
    h3_campaign_placed_heroes_added: list[str] = []
    absod_dialogs_scrubbed = 0
    orphan_hubs_scrubbed: list[str] = []
    orphan_campaign_members_scrubbed = 0
    orphan_lang_tokens_scrubbed: list[str] = []
    coordinate_city_rows_scrubbed = 0
    from validate_campaign_town_name_contract import (
        prune_coordinate_city_rows_from_catalog_bytes,
    )
    try:
        with zipfile.ZipFile(temp_source_zip, "r") as source:
            source_names = set(source.namelist())
            data_json = json.loads(source.read("DB/data.json").decode("utf-8-sig"))
            roster_hero_sids = collect_homm3_roster_hero_sids(source)
            missing_heroes = sorted({sid for sid in hero_sids if sid not in roster_hero_sids})
            if missing_heroes:
                fail(
                    "campaignHeroSid values must exist as DB/heroes/<faction>/<sid>.json "
                    "(StoryHub needs a real hero row; do not invent campaignHeroes-only "
                    "SIDs for shared roster protagonists). Missing:\n- "
                    + "\n- ".join(missing_heroes)
                )
            campaign_heroes = list(data_json.get("campaignHeroes") or [])
            # Root cause of missing Quick Play heroes (Crag Hack, Yog, …): continuity
            # installs previously appended shared roster SIDs into campaignHeroes.
            # Native DataInc treats that list as campaign-reserved and omits them from
            # custom-game / Quick Play hero select. Scrub any roster bleed; do not re-add.
            roster_heroes_scrubbed = sorted(
                sid for sid in campaign_heroes if sid in roster_hero_sids
            )
            if roster_heroes_scrubbed:
                scrubbed_set = set(roster_heroes_scrubbed)
                campaign_heroes = [
                    sid for sid in campaign_heroes if sid not in scrubbed_set
                ]
            # Non-hireable H3 bespoke placed names (Tyranell, …) — campaign-folder
            # stubs only; never roster SIDs.
            placed_campaign_sids = [
                sid
                for sid in placed_hero_overlay.get("campaignHeroes") or []
                if isinstance(sid, str) and sid and sid not in roster_hero_sids
            ]
            missing_stub_files = [
                sid
                for sid in placed_campaign_sids
                if f"DB/heroes/campaign/{sid}.json" not in overlay_members
                and f"DB/heroes/campaign/{sid}.json" not in source_names
            ]
            if missing_stub_files:
                fail(
                    "h3 campaign placed hero SIDs missing DB/heroes/campaign rows:\n- "
                    + "\n- ".join(missing_stub_files)
                )
            existing_campaign = set(campaign_heroes)
            for sid in placed_campaign_sids:
                if sid not in existing_campaign:
                    campaign_heroes.append(sid)
                    existing_campaign.add(sid)
                    h3_campaign_placed_heroes_added.append(sid)
            data_json["campaignHeroes"] = campaign_heroes

            if "DB/quickStart.json" in overlay_members:
                qs = json.loads(overlay_members["DB/quickStart.json"].decode("utf-8-sig"))
            else:
                qs = json.loads(source.read("DB/quickStart.json").decode("utf-8-sig"))
            scenarios = list(qs.get("scenarios") or [])
            for sid in map_sids:
                if sid not in scenarios:
                    scenarios.append(sid)
            qs["scenarios"] = scenarios
            overlay_members["DB/quickStart.json"] = (
                json.dumps(qs, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")

            lang_members: dict[str, bytes] = {}
            for info in source.infolist():
                name = info.filename
                if name.startswith("Lang/") and name.endswith("/texts/campaign.json"):
                    existing = json.loads(source.read(name).decode("utf-8-sig"))
                    merged = merge_lang_campaign(existing, lang_tokens)
                    orphan_lang_tokens_scrubbed.extend(
                        scrub_orphan_homm3_campaign_tokens(merged)
                    )
                    lang_members[name] = (
                        json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
                    ).encode("utf-8")
                    lang_updated += 1
            orphan_lang_tokens_scrubbed = sorted(set(orphan_lang_tokens_scrubbed))

            from map_load_preflight import (
                apply_loader_hang_core_guards,
                seer_hut_core_members_to_delete,
            )

            try:
                guard_report = apply_loader_hang_core_guards(source, overlay_members)
            except ValueError as exc:
                fail(str(exc))
            deleted_core_members = set(
                seer_hut_core_members_to_delete(source, overlay_members)
            )
            # homm3_landon_*_city are emitted as copies of the stock city in the Core the
            # campaign was emitted against. Re-derive them from the Core being installed into
            # (validate_homm3_city_building_tree_contract: clone == stock city except id).
            release_port_dir = str(Path(__file__).resolve().parent / "release_port")
            if release_port_dir not in sys.path:
                sys.path.insert(0, release_port_dir)
            from homm3_city_building_tree import rederive_city_clone_members

            try:
                derived_city_notes = rederive_city_clone_members(
                    overlay_members,
                    lambda member: source.read(member) if member in source_names else None,
                )
            except ValueError as exc:
                fail(str(exc))
            for note in derived_city_notes:
                _log(f"  {note}")
            removed = guard_report["scrubbedOrphanXfpLogic"]
            removed_by_member = guard_report["scrubbedOrphanXfpLogicByMember"]
            boat_ensured = guard_report["ensuredHomm3BoatObjectConfig"]
            town_gates_normalized = guard_report["normalizedHomm3TownBottomCenterGates"]

            with zipfile.ZipFile(temp_zip, "w") as target:
                written: set[str] = set()
                for info in source.infolist():
                    name = info.filename
                    if name in deleted_core_members:
                        continue
                    if is_stale_absod_dialog_member(name):
                        absod_dialogs_scrubbed += 1
                        continue
                    if is_orphan_homm3_campaign_member(name):
                        hub = hub_sid_from_campaign_member(name)
                        if hub:
                            orphan_hubs_scrubbed.append(hub)
                        orphan_campaign_members_scrubbed += 1
                        continue
                    if name in campaign_members:
                        data = campaign_members[name]
                    elif name == "DB/data.json":
                        data = (
                            json.dumps(data_json, indent=2, ensure_ascii=False) + "\n"
                        ).encode("utf-8")
                    elif name in overlay_members:
                        overlay_data = overlay_members[name]
                        if name.startswith("Lang/") and name.endswith(".json"):
                            data = merge_lang_sid_catalog_bytes(
                                source.read(name), overlay_data, member=name
                            )
                        elif name == "DB/map/objects/homecoming_custom_objects.json":
                            # Guards may delete SIDs (e.g. move homm3_seer_hut to
                            # 4_interactables). Id-merge would resurrect source rows.
                            data = overlay_data
                        elif name.startswith("DB/buildings_constructions/") or (
                            _try_parse_id_array_catalog(overlay_data) is not None
                        ):
                            # Buildings presets and any other id-array overlay must
                            # merge into live Core (never whole-file replace).
                            # Exact-footprint ObjectConfigs and objects_logic: drop
                            # Core-only homm3_xfp_* rows so retired mine clones /
                            # orphan logic cannot survive id-merge.
                            data = merge_id_array_catalog_bytes(
                                source.read(name) if name in source_names else None,
                                overlay_data,
                                member=name,
                                drop_unreferenced_base_xfp=(
                                    name.replace("\\", "/").endswith(
                                        "DB/map/objects/homecoming_exact_footprint_objects.json"
                                    )
                                    or (
                                        name.replace("\\", "/").startswith("DB/objects_logic/")
                                        and name.endswith(".json")
                                    )
                                ),
                            )
                        else:
                            data = overlay_data
                    elif name in lang_members:
                        data = lang_members[name]
                    else:
                        data = source.read(name)
                    if name.startswith("Lang/") and name.endswith("/texts/cities.json"):
                        # Retired f"Town {sourceKey}" placeholder rows survive upsert-only
                        # lang merges; prune them from the installed catalog on rewrite.
                        data, pruned = prune_coordinate_city_rows_from_catalog_bytes(data)
                        coordinate_city_rows_scrubbed += pruned
                    replacement = zipfile.ZipInfo(name, info.date_time)
                    replacement.comment = info.comment
                    replacement.extra = info.extra
                    replacement.internal_attr = info.internal_attr
                    replacement.external_attr = info.external_attr
                    replacement.compress_type = info.compress_type
                    target.writestr(replacement, data)
                    written.add(name)
                for name, data in campaign_members.items():
                    if name not in written and name not in deleted_core_members:
                        target.writestr(name, data)
                for name, data in overlay_members.items():
                    if name not in written and name not in deleted_core_members:
                        target.writestr(name, data)
                for name, data in lang_members.items():
                    if name not in written and name not in deleted_core_members:
                        target.writestr(name, data)

        shutil.copy2(core_zip, backup)
        shutil.copy2(temp_zip, core_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "coreZip": str(core_zip),
        "backup": str(backup),
        "hubKeys": [str(job.get("hubKey")) for job in hub_jobs],
        "campaignMembers": sorted(campaign_members.keys()),
        "overlayMembers": sorted(overlay_members.keys()),
        "langCampaignFilesUpdated": lang_updated,
        "campaignHeroesRosterScrubbed": roster_heroes_scrubbed,
        "h3CampaignPlacedHeroesAdded": h3_campaign_placed_heroes_added,
        "h3CampaignPlacedHeroesOverlayRoot": placed_hero_overlay.get("overlayRoot"),
        "scrubbedOrphanXfpLogic": removed,
        "scrubbedOrphanXfpLogicByMember": removed_by_member,
        "campFireMetaAliasObjectIds": guard_report["campFireMetaAliasObjectIds"],
        "campFireMetaAliasMember": guard_report["campFireMetaAliasMember"],
        "ensuredHomm3BoatObjectConfig": boat_ensured,
        "normalizedHomm3TownBottomCenterGates": town_gates_normalized,
        "scrubbedAbsodDialogMembers": absod_dialogs_scrubbed,
        "scrubbedCoordinateCityLangRows": coordinate_city_rows_scrubbed,
        "scrubbedOrphanHomm3Hubs": sorted(set(orphan_hubs_scrubbed)),
        "scrubbedOrphanHomm3CampaignMembers": orphan_campaign_members_scrubbed,
        "scrubbedOrphanHomm3LangTokens": orphan_lang_tokens_scrubbed,
        "objectiveLockit": objective_lockit_report,
    }


def mark_weave_installed(
    repo_root: Path, install_report: dict[str, Any], hub_cfg: dict[str, Any]
) -> None:
    weave_dir = repo_root / hub_cfg["weaveDir"]
    hub_sid = hub_cfg["hubSid"]
    weave_path = weave_dir / "continuity.weave.v1.json"
    report_path = weave_dir / "continuity.weave_report.v1.json"
    weave = load_json(weave_path)
    weave["coreZipLayout"]["installStatus"] = "installed"
    weave["coreZipLayout"]["installedAt"] = install_report["installedAt"]
    weave["coreZipLayout"]["installBackup"] = install_report["core"]["backup"]
    weave["proofBoundary"] = (
        f"generated-artifact + deployed-payload (Core.zip campaigns/{hub_sid}); "
        "runtime transfer / strongest-N still unvalidated"
    )
    write_json(weave_path, weave)
    if report_path.is_file():
        report = load_json(report_path)
        report["installStatus"] = "installed"
        report["installReport"] = install_report
        write_json(report_path, report)
    write_json(weave_dir / "continuity.install_report.v1.json", install_report)


def verify_installed(
    game_root: Path,
    hub_cfg: dict[str, Any],
    objective_english: dict[str, str] | None = None,
) -> None:
    core_zip = game_root / CORE_ZIP_REL
    hub_sid = hub_cfg["hubSid"]
    first_mission = hub_cfg["missions"][0]
    first_map_sid = hub_cfg["mapInstalls"][0]["mapSid"]
    from campaign_objective_install import (
        assert_core_has_objective_sids,
        assert_map_has_objective_bullets,
    )

    for install in hub_cfg["mapInstalls"]:
        map_path = game_root / MAPS_REL / f"{install['mapSid']}.map"
        if not map_path.is_file():
            fail(f"post-install missing Story_maps map: {map_path}")
        try:
            assert_map_has_objective_bullets(map_path)
        except ValueError as exc:
            fail(str(exc))
    if objective_english:
        try:
            assert_core_has_objective_sids(
                core_zip,
                {
                    sid
                    for sid in objective_english
                    if "_main_goal_obj_" in sid or sid.endswith("_main_goal_desc")
                },
            )
        except ValueError as exc:
            fail(str(exc))
    with zipfile.ZipFile(core_zip, "r") as source:
        required = [
            f"campaigns/{hub_sid}/storyHub.json",
            f"campaigns/{hub_sid}/heroes.json",
            f"campaigns/{hub_sid}/fractions.json",
            f"campaigns/{hub_sid}/storyCounters.json",
            f"campaigns/{hub_sid}/perks.json",
            *[f"campaigns/{hub_sid}/missions/{name}" for name in hub_cfg["missions"]],
            f"campaigns/{hub_sid}/icons/main_icon.png",
        ]
        missing = [name for name in required if name not in source.namelist()]
        if missing:
            fail("post-install Core.zip missing:\n- " + "\n- ".join(missing))
        story = json.loads(source.read(f"campaigns/{hub_sid}/storyHub.json").decode("utf-8-sig"))
        if story.get("transferHeroProgressFromSession") is not True:
            fail("installed storyHub missing transferHeroProgressFromSession true")
        if story.get("mainIconSid") != "main_icon":
            fail(f"installed storyHub.mainIconSid must be main_icon; got {story.get('mainIconSid')!r}")
        first = json.loads(
            source.read(f"campaigns/{hub_sid}/missions/{first_mission}").decode("utf-8-sig")
        )
        map_sid = first["array"][0]["variants"][0]["mapSid"]
        if map_sid != first_map_sid:
            fail(f"installed first mission mapSid unexpected: {map_sid} != {first_map_sid}")
        data = json.loads(source.read("DB/data.json").decode("utf-8-sig"))
        hero_sid = str(hub_cfg.get("campaignHeroSid") or "homm3_castle_hero_7")
        roster_hero_sids = collect_homm3_roster_hero_sids(source)
        if hero_sid not in roster_hero_sids:
            fail(f"installed Core missing roster hero row for campaignHeroSid {hero_sid}")
        heroes_doc = json.loads(
            source.read(f"campaigns/{hub_sid}/heroes.json").decode("utf-8-sig")
        )
        hero_ids = [
            str(row.get("id") or "")
            for row in (heroes_doc.get("array") or [])
            if isinstance(row, dict)
        ]
        if hero_sid not in hero_ids:
            fail(
                f"installed campaigns/{hub_sid}/heroes.json must list campaignHeroSid "
                f"{hero_sid!r} as isAvailableAtStart roster; got {hero_ids!r}"
            )
        leaked = sorted(
            sid for sid in (data.get("campaignHeroes") or []) if sid in roster_hero_sids
        )
        if leaked:
            fail(
                "installed DB/data.json campaignHeroes must not list shared town-roster "
                "SIDs (native Quick Play hides them). Leaked:\n- "
                + "\n- ".join(leaked)
            )

        orphan_hubs = sorted(
            {
                hub_sid_from_campaign_member(name) or ""
                for name in source.namelist()
                if is_orphan_homm3_campaign_member(name)
            }
            - {""}
        )
        if orphan_hubs:
            fail(
                "installed Core.zip still has orphan/non-canonical homm3 StoryHub folders "
                "(Profiles would show duplicate or stale campaign titles):\n- "
                + "\n- ".join(orphan_hubs)
            )

        # Payload icons override must land in Core (not a stale mainStory clone).
        payload_icon = (
            Path(__file__).resolve().parents[1]
            / hub_cfg["weaveDir"]
            / "campaign_payload"
            / "icons"
            / "main_icon.png"
        )
        if payload_icon.is_file():
            installed_icon = source.read(f"campaigns/{hub_sid}/icons/main_icon.png")
            if installed_icon != payload_icon.read_bytes():
                fail(
                    f"installed {hub_sid} main_icon.png must match campaign_payload/icons/"
                    "main_icon.png (curated HoMM3 selection crop)"
                )
        if hub_sid == "homm3_01_roe_castle_good1":
            first_show = story.get("firstShowActions") or []
            if any(
                isinstance(a, dict) and a.get("type") == "PlayVideo" for a in first_show
            ):
                fail(
                    "installed Good1 firstShowActions must not PlayVideo Cgood1 "
                    "(selection still only; keep mission-pin Good1a/b/c)"
                )

        # Fail closed: installed PlayVideo keys must match the weave payload exactly.
        # Catches Core.zip clobber by concurrent installs leaving stale clip wiring.
        payload_story_path = (
            Path(__file__).resolve().parents[1]
            / hub_cfg["weaveDir"]
            / "campaign_payload"
            / "storyHub.json"
        )
        if payload_story_path.is_file():
            payload_story = load_json(payload_story_path)
            def _playvideo_by_node(doc: dict[str, Any]) -> dict[str, list[str]]:
                out: dict[str, list[str]] = {}
                for node in doc.get("nodes") or []:
                    if not isinstance(node, dict):
                        continue
                    sid = str(node.get("sid") or "")
                    clips = [
                        str(v)
                        for action in (node.get("interactionActions") or [])
                        if isinstance(action, dict) and action.get("type") == "PlayVideo"
                        for v in (action.get("values") or [])
                        if isinstance(v, str)
                    ]
                    out[sid] = clips
                return out

            installed_pv = _playvideo_by_node(story)
            payload_pv = _playvideo_by_node(payload_story)
            if installed_pv != payload_pv:
                fail(
                    f"installed {hub_sid} storyHub PlayVideo wiring drifted from "
                    f"campaign_payload/storyHub.json:\n"
                    f"  installed={installed_pv}\n"
                    f"  payload={payload_pv}"
                )
    # Fail-closed Loader hang preflight (Meta/ObjectConfig, owners, dual install).
    from map_load_preflight import format_issues, run_installed_campaign_preflight

    map_checks: list[dict[str, Any]] = []
    with zipfile.ZipFile(core_zip, "r") as source:
        for mission_name, install in zip(hub_cfg["missions"], hub_cfg["mapInstalls"]):
            member = f"campaigns/{hub_sid}/missions/{mission_name}"
            mission = json.loads(source.read(member).decode("utf-8-sig"))
            map_checks.append(
                {
                    "mapSid": install["mapSid"],
                    "mapPath": game_root / MAPS_REL / f"{install['mapSid']}.map",
                    "mission": mission,
                    "missionLabel": member,
                    "missionId": Path(mission_name).stem.replace("homm3_roe_castle_", "")
                    .replace("homm3_roe_necropolis_", "")
                    .replace("homm3_roe_inferno_", "")
                    .replace("homm3_roe_dungeon_", "")
                    .replace("homm3_roe_necropolis_", "")
                    .replace("homm3_roe_neutral_", "")
                    .replace("homm3_roe_rampart_", ""),
                }
            )
    issues = run_installed_campaign_preflight(
        game_root=game_root,
        core_zip=core_zip,
        map_checks=map_checks,
    )
    if issues:
        fail(format_issues(issues))

    # Town display names must be authentic HoMM3 pool names, never coordinate
    # placeholders (h3_town_name_pool / validate_campaign_town_name_contract).
    from validate_campaign_town_name_contract import validate_installed_town_names

    town_name_issues = validate_installed_town_names(game_root=game_root, core_zip=core_zip)
    if town_name_issues:
        fail("campaign town-name contract failed:\n- " + "\n- ".join(town_name_issues))

    # BeforeIamVsHero.p must equal a fought propHeroes.heroSid (stub or roster).
    repo_root = Path(__file__).resolve().parents[1]
    before_hero_validator = (
        repo_root / "tools" / "validate_campaign_before_iam_vs_hero_prop_contract.py"
    )
    if not before_hero_validator.is_file():
        fail(f"missing BeforeIamVsHero-in-propHeroes validator: {before_hero_validator}")
    story_maps = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps" / "Story_maps"
    proc = subprocess.run(
        [
            sys.executable,
            str(before_hero_validator),
            "--repo-root",
            str(repo_root),
            "--installed-story-maps",
            str(story_maps),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        fail(
            "campaign BeforeIamVsHero-in-propHeroes contract failed:\n"
            + detail.strip()
        )


def validate_hub_spawn_heroes_against_h3m(repo_root: Path, hub: str, hub_cfg: dict[str, Any]) -> None:
    """Fail closed when H3M-derived playable starts disagree with campaignHeroSid/policy."""
    validator = repo_root / "tools" / "validate_campaign_spawn_hero_h3m_contract.py"
    if not validator.is_file():
        fail(f"missing spawn-hero validator: {validator}")
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    from campaign_hub_spawn import mission_id_from_map_install_artifact  # noqa: WPS433

    missions: list[str] = []
    for install in hub_cfg.get("mapInstalls") or []:
        if not isinstance(install, dict) or "artifact" not in install:
            continue
        missions.append(mission_id_from_map_install_artifact(install["artifact"]))
    if not missions:
        return
    campaign_policy = None
    for pattern in (
        repo_root / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy*.json",
        repo_root / "scenarios" / "ab_sod_campaigns" / "continuity_carry_policy_*.json",
    ):
        for path in sorted(pattern.parent.glob(pattern.name)):
            doc = load_json(path)
            if str((doc.get("campaign") or {}).get("hubSid") or "") == hub_cfg["hubSid"]:
                campaign_policy = doc
                break
        if campaign_policy is not None:
            break
    manifest = None
    if campaign_policy is not None:
        batch = (campaign_policy.get("campaign") or {}).get("batchManifest")
        if isinstance(batch, str) and batch.strip():
            manifest = repo_root / batch
    cmd = [sys.executable, str(validator)]
    if manifest is not None and manifest.is_file():
        cmd.extend(["--manifest", str(manifest)])
    for mid in missions:
        cmd.extend(["--mission", mid])
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        fail(f"H3M spawn-hero contract failed for hub {hub}:\n{detail.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--skip-regenerate", action="store_true")
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(6, (os.cpu_count() or 2))),
        help="Parallel workers for weave regen + overlay collect (default: min(6, CPUs)).",
    )
    parser.add_argument(
        "--force-map-copy",
        action="store_true",
        help="Always copy Story_maps even when artifact SHA matches installed map.",
    )
    parser.add_argument(
        "--hub",
        action="append",
        dest="hubs",
        choices=HUB_CHOICES,
        help="StoryHub key to install (repeatable). Default: good1.",
    )
    parser.add_argument(
        "--all-hubs",
        action="store_true",
        help="Install every StoryHub in play order with a single Core.zip rewrite.",
    )
    parser.add_argument(
        "--no-mark-installed",
        action="store_true",
        help=(
            "Do not record the install in the repo weave JSON (continuity.weave.v1.json, "
            "continuity.install_report.v1.json). For staged game roots such as "
            "tools/port_current/rebuild_core_from_vanilla.py; refused for the default game root."
        ),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()
    if args.no_mark_installed and game_root == DEFAULT_GAME_ROOT.resolve():
        fail("--no-mark-installed is for staged game roots; the default install must record its install state")
    jobs = max(1, int(args.jobs))
    phase_timings: dict[str, float] = {}
    t_all = time.perf_counter()

    if args.all_hubs and args.hubs:
        fail("use either --all-hubs or --hub, not both")
    if args.all_hubs:
        hubs = list(HUB_INSTALL_KEYS_PLAY_ORDER)
    elif args.hubs:
        # Preserve caller order but dedupe.
        seen: set[str] = set()
        hubs = []
        for hub in args.hubs:
            if hub not in seen:
                hubs.append(hub)
                seen.add(hub)
    else:
        hubs = ["good1"]

    unknown = [hub for hub in hubs if hub not in HUB_CONFIGS]
    if unknown:
        fail(f"unknown hub keys: {unknown}")

    _log(f"continuity install hubs={len(hubs)} jobs={jobs} gameRoot={game_root}")

    t0 = time.perf_counter()
    if jobs <= 1:
        for hub in hubs:
            validate_hub_spawn_heroes_against_h3m(repo_root, hub, HUB_CONFIGS[hub])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {
                pool.submit(
                    validate_hub_spawn_heroes_against_h3m,
                    repo_root,
                    hub,
                    HUB_CONFIGS[hub],
                ): hub
                for hub in hubs
            }
            for fut in concurrent.futures.as_completed(futures):
                hub = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    fail(f"spawn-hero contract failed for hub {hub}: {exc}")
    phase_timings["validateSpawnHeroes"] = round(time.perf_counter() - t0, 3)

    if not args.skip_regenerate:
        t0 = time.perf_counter()
        _log(f"regenerating weaves ({len(hubs)} hubs, jobs={jobs})")
        regenerate_weaves_parallel(repo_root, game_root, hubs, jobs=jobs)
        phase_timings["regenerateWeaves"] = round(time.perf_counter() - t0, 3)
    else:
        phase_timings["regenerateWeaves"] = 0.0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_suffix = f".roe_castle_continuity_backup_{stamp}"

    hub_jobs: list[dict[str, Any]] = []
    all_map_results: list[dict[str, Any]] = []
    per_hub_objectives: dict[str, dict[str, str]] = {}
    t0 = time.perf_counter()
    for hub in hubs:
        hub_cfg = HUB_CONFIGS[hub]
        payload = require_payload(repo_root, hub_cfg)
        map_results, objective_english = install_maps(
            repo_root,
            game_root,
            backup_suffix,
            hub_cfg["mapInstalls"],
            skip_unchanged_maps=not bool(args.force_map_copy),
        )
        all_map_results.extend(map_results)
        per_hub_objectives[hub] = objective_english
        hub_jobs.append(
            {
                "hubKey": hub,
                "payload": payload,
                "hubCfg": hub_cfg,
                "objectiveEnglish": objective_english,
            }
        )
        skipped = sum(1 for row in map_results if row.get("action") == "skipped_unchanged_map")
        copied = sum(1 for row in map_results if row.get("action") == "copied_from_artifact")
        _log(f"  maps {hub}: copied={copied} skippedUnchanged={skipped}")
    phase_timings["installMaps"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    core_report = patch_core_zip_for_hubs(
        repo_root,
        game_root,
        backup_suffix,
        hub_jobs,
        overlay_jobs=jobs,
    )
    phase_timings["patchCoreZip"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    for hub in hubs:
        hub_cfg = HUB_CONFIGS[hub]
        hub_sid = hub_cfg["hubSid"]
        objective_english = per_hub_objectives[hub]
        hub_map_sids = {row["mapSid"] for row in hub_cfg["mapInstalls"]}
        hub_map_results = [
            row for row in all_map_results if row.get("mapSid") in hub_map_sids
        ]
        install_report = {
            "schema": "homm3.olden_campaign_continuity_install_report.v1",
            "installedAt": stamp,
            "hubSid": hub_sid,
            "hub": hub,
            "destinationPolicy": INSTALL_DESTINATION_POLICY,
            "maps": hub_map_results,
            "objectiveLockitSids": sorted(objective_english.keys()),
            "core": core_report,
            "multiHubInstall": {
                "hubs": hubs,
                "singleCoreRewrite": True,
            },
            "phaseTimingsSec": phase_timings,
        }
        if not args.no_mark_installed:
            mark_weave_installed(repo_root, install_report, hub_cfg)
        verify_installed(game_root, hub_cfg, objective_english=objective_english)
    phase_timings["verifyInstalled"] = round(time.perf_counter() - t0, 3)
    phase_timings["total"] = round(time.perf_counter() - t_all, 3)

    print(
        f"installed RoE Castle continuity weave "
        f"({','.join(hubs)}; single Core.zip rewrite)",
        flush=True,
    )
    print(f"  hubs={len(hubs)}", flush=True)
    print(f"  maps={len(all_map_results)} Story_maps entries", flush=True)
    print(
        f"  objectiveBullets="
        f"{sum(1 for row in all_map_results if row.get('objectiveBullets'))} maps, "
        f"{sum(len(v) for v in per_hub_objectives.values())} LocKit SIDs",
        flush=True,
    )
    print(f"  coreBackup={core_report['backup']}", flush=True)
    print(f"  phaseTimingsSec={phase_timings}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
