#!/usr/bin/env python3
"""Generate AB/SoD LocKit rows and StoryHub carry policies (videos deferred)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from h3c_mission_source import load_h3c_block  # noqa: E402
from campaign_hero_level_cap import (  # noqa: E402
    h3m_hero_level_limit,
    source_text_for_level_cap,
)

HUB_SPECS: list[dict] = [
    {
        "hub": "ab",
        "entry": "ab.h3c",
        "title": "Armageddon's Blade",
        "factionTag": "conflux",
        "prefix": "homm3_ab_conflux",
        "hubSid": "homm3_09_ab_conflux_ab",
        "factionSid": "homm3_conflux",
        "heroSid": "homm3_conflux_hero_1",
        "iconStill": "Cgood1_selection_still.png",
        "focusX": 0.72,
        "focusY": 0.45,
        "missions": [
            "catherines_charge",
            "seeking_armageddon",
            "shadows_of_the_forest",
            "maker_of_sorrows",
            "return_of_the_king",
            "a_blade_in_the_back",
            "to_kill_a_hero",
            "oblivions_edge",
        ],
    },
    {
        "hub": "blood",
        "entry": "blood.h3c",
        "title": "Dragon's Blood",
        "factionTag": "dungeon",
        "prefix": "homm3_ab_dungeon",
        "hubSid": "homm3_10_ab_dungeon_blood",
        "factionSid": "homm3_dungeon",
        "heroSid": "homm3_dungeon_hero_1",
        "iconStill": "Cevil1_selection_still.png",
        "focusX": 0.40,
        "focusY": 0.45,
        "missions": [
            "culling_the_weak",
            "savaging_the_scavengers",
            "blood_of_the_dragon_father",
            "blood_thirsty",
        ],
    },
    {
        "hub": "slayer",
        "entry": "slayer.h3c",
        "title": "Dragon Slayer",
        "factionTag": "tower",
        "prefix": "homm3_ab_tower",
        "hubSid": "homm3_11_ab_tower_slayer",
        "factionSid": "homm3_tower",
        "heroSid": "homm3_tower_hero_1",
        "iconStill": "Cgood2_selection_still.png",
        "focusX": 0.55,
        "focusY": 0.45,
        "missions": [
            "rust_dragons",
            "faerie_dragons",
            "azure_dragons",
            "crystal_dragons",
        ],
    },
    {
        "hub": "festival",
        "entry": "festival.h3c",
        "title": "Festival of Life",
        "factionTag": "stronghold",
        "prefix": "homm3_ab_stronghold",
        "hubSid": "homm3_12_ab_stronghold_festival",
        "factionSid": "homm3_stronghold",
        "heroSid": "homm3_stronghold_hero_1",
        "iconStill": "Cneutral_selection_still.png",
        "focusX": 0.50,
        "focusY": 0.45,
        "missions": [
            "for_the_throne",
            "clan_war",
            "taming_of_the_wild",
            "razor_claw",
        ],
    },
    {
        "hub": "fire",
        "entry": "fire.h3c",
        "title": "Playing with Fire",
        # Packaging SIDs remain historical necropolis_* ids; protagonist is Fortress Adrienne.
        "factionTag": "fortress",
        "prefix": "homm3_ab_necropolis",
        "hubSid": "homm3_13_ab_fortress_fire",
        "factionSid": "homm3_fortress",
        "heroSid": "homm3_fortress_hero_17",
        "iconStill": "fire_selection_still.png",
        "focusX": 0.42,
        "focusY": 0.55,
        "missions": [
            "farming_towns",
            "march_of_the_undead",
            "burning_of_tatalia",
        ],
    },
    {
        "hub": "fool",
        "entry": "fool.h3c",
        "title": "Foolhardy Waywardness",
        "factionTag": "castle",
        "prefix": "homm3_ab_castle",
        "hubSid": "homm3_14_ab_castle_fool",
        "factionSid": "homm3_castle",
        "heroSid": "homm3_castle_hero_7",
        "iconStill": "Cgood3_selection_still.png",
        "focusX": 0.40,
        "focusY": 0.45,
        "missions": [
            "lost_at_sea",
            "here_there_be_pirates",
            "hurry_up_and_wait",
            "their_end_of_the_bargain",
        ],
    },
    {
        "hub": "sandro",
        "entry": "Sandro.h3c",
        "title": "Rise of the Necromancer",
        "factionTag": "necropolis",
        "prefix": "homm3_sod_necropolis",
        "hubSid": "homm3_15_sod_necropolis_sandro",
        "factionSid": "homm3_necropolis",
        "heroSid": "homm3_necropolis_hero_7",
        "iconStill": "Cevil2_selection_still.png",
        "focusX": 0.55,
        "focusY": 0.45,
        "missions": ["target", "master", "finneas_vilmar", "duke_alarice"],
    },
    {
        "hub": "crag",
        "entry": "Crag.h3c",
        "title": "Hack and Slash",
        "factionTag": "stronghold",
        "prefix": "homm3_sod_stronghold",
        "hubSid": "homm3_16_sod_stronghold_crag",
        "factionSid": "homm3_stronghold",
        "heroSid": "homm3_stronghold_hero_1",
        "iconStill": "Cneutral_selection_still.png",
        "focusX": 0.45,
        "focusY": 0.45,
        "missions": [
            "bashing_skulls",
            "black_sheep",
            "a_cage_in_the_hand",
            "grave_robber",
        ],
    },
    {
        "hub": "yog",
        "entry": "Yog.h3c",
        "title": "Birth of a Barbarian",
        "factionTag": "stronghold",
        "prefix": "homm3_sod_stronghold",
        "hubSid": "homm3_17_sod_stronghold_yog",
        "factionSid": "homm3_stronghold",
        "heroSid": "homm3_stronghold_hero_1",
        "iconStill": "Cneutral_selection_still.png",
        "focusX": 0.58,
        "focusY": 0.45,
        "missions": [
            "on_the_run",
            "the_meeting",
            "a_tough_start",
            "falor_and_terwen",
            "returning_to_bracada",
        ],
    },
    {
        "hub": "gem",
        "entry": "Gem.h3c",
        "title": "New Beginning",
        "factionTag": "rampart",
        "prefix": "homm3_sod_rampart",
        "hubSid": "homm3_18_sod_rampart_gem",
        "factionSid": "homm3_rampart",
        "heroSid": "homm3_rampart_hero_1",
        "iconStill": "Cgood2_selection_still.png",
        "focusX": 0.65,
        "focusY": 0.45,
        "missions": [
            "clearing_the_border",
            "after_the_amulet",
            "retrieving_the_cowl",
            "driving_for_the_boots",
        ],
    },
    {
        "hub": "gelu",
        "entry": "Gelu.h3c",
        "title": "Elixir of Life",
        "factionTag": "rampart",
        "prefix": "homm3_sod_rampart",
        "hubSid": "homm3_19_sod_rampart_gelu",
        "factionSid": "homm3_rampart",
        "heroSid": "homm3_rampart_hero_1",
        "iconStill": "Cgood1_selection_still.png",
        "focusX": 0.72,
        "focusY": 0.45,
        "missions": [
            "graduation_exercise",
            "cutthroats",
            "valley_of_the_dragon_lords",
            "a_thief_in_the_night",
        ],
    },
    {
        "hub": "final",
        "entry": "Final.h3c",
        "title": "Unholy Alliance",
        "factionTag": "necropolis",
        "prefix": "homm3_sod_necropolis",
        "hubSid": "homm3_20_sod_necropolis_final",
        "factionSid": "homm3_necropolis",
        "heroSid": "homm3_necropolis_hero_7",
        "iconStill": "Csecret_selection_still.png",
        "focusX": 0.52,
        "focusY": 0.45,
        "missions": [
            "harvest",
            "gathering_the_legion",
            "search_for_a_killer",
            "final_peace",
            "secrets_revealed",
            "agents_of_vengeance",
            "wrath_of_sandro",
            "invasion",
            "to_strive_to_seek",
            "barbarian_brothers",
            "union",
            "fall_of_sandro",
        ],
    },
]


def clip(text: str, limit: int) -> str:
    one = " ".join((text or "").split())
    if len(one) <= limit:
        return one
    return one[: limit - 3].rstrip() + "..."


def map_sid(faction_tag: str, mission_id: str) -> str:
    return f"h3_{faction_tag}_{mission_id}_raw_translation"


def chain_region_pixels(mission_ids: list[str]) -> dict[str, list[float]]:
    """Synthetic left-to-right pin layout (no authentic campaign-map pixels yet)."""
    n = max(len(mission_ids), 1)
    out: dict[str, list[float]] = {}
    for index, mission_id in enumerate(mission_ids):
        t = index / max(n - 1, 1)
        out[mission_id] = [80.0 + t * 720.0, 220.0]
    return out


def build_loc_rows() -> dict[str, str]:
    from campaign_objective_text import objective_loc_rows

    rows: dict[str, str] = {}
    for hub in HUB_SPECS:
        for block_index, mission_id in enumerate(hub["missions"], 1):
            source = load_h3c_block(hub["entry"], block_index)
            title = (source.summary.title or mission_id).strip()
            full_desc = (source.summary.description or title).strip()
            prefix = hub["prefix"]
            rows.update(
                objective_loc_rows(
                    mission_id=mission_id,
                    title=title,
                    full_description=full_desc,
                    menu_title_sid=f"{prefix}_{mission_id}_title",
                    menu_desc_sid=f"{prefix}_{mission_id}_description",
                )
            )
    return rows


def write_localization(rows: dict[str, str]) -> Path:
    path = ROOT / "experiments" / "campaign_port_poc" / "ab_sod_localization.py"
    lines = [
        '"""English LocKit rows for AB+SoD campaign raw_translation maps.',
        "",
        "Auto-derived from Complete H3C scenario title/description. Menu shell keeps",
        "vanilla budgets (title<=23, desc<=172). Quest-log attributes use unclipped",
        "main_goal_obj_* bullets (native quest_sub pattern). Merged into",
        "homecoming_localization.CUSTOM_MAPS_EN.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "AB_SOD_CUSTOM_MAPS_EN: dict[str, str] = {",
    ]
    for key, value in rows.items():
        lines.append(f"    {key!r}: {value!r},")
    lines.append("}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_carry_policy(
    hub: dict,
    titles_by_mission: dict[str, str],
    descriptions_by_mission: dict[str, str],
) -> Path:
    missions: list[str] = list(hub["missions"])
    faction_tag = hub["factionTag"]
    overrides = {
        mission_id: map_sid(faction_tag, mission_id) for mission_id in missions
    }
    handoffs = []
    for index in range(len(missions) - 1):
        frm = missions[index]
        to = missions[index + 1]
        level_cap = h3m_hero_level_limit(
            campaign_entry=hub["entry"],
            block_index=index + 1,
        )
        handoffs.append(
            {
                "fromMissionId": frm,
                "toMissionId": to,
                "sourceBlockIndex": index + 1,
                "nextBlockIndex": index + 2,
                "levelCap": level_cap,
                "strongestHeroesCarryCount": 8,
                "sourceTextProven": source_text_for_level_cap(
                    level_cap, from_mission_id=frm
                ),
                "mapSids": {
                    "from": overrides[frm],
                    "to": overrides[to],
                },
                "strongestNSelection": {
                    "hoMM3Behavior": "carry_top_n_heroes_by_strength",
                    "oldenNativeStatus": "not_proven",
                    "v1Policy": (
                        "require_transferHeroProgressFromSession_true_and_document_strongest_n_gap"
                    ),
                    "blocker": (
                        "native_storyhub_may_transfer_all_available_heroes_not_top_n; "
                        "needs runtime proof or explicit bridge"
                    ),
                },
            }
        )

    still = (
        f"artifacts/campaign_port_poc/ab_sod_campaigns/storyhub_visual/"
        f"{hub['hub']}_selection_still.png"
    )
    policy = {
        "schema": "homm3.olden_campaign_continuity_carry_policy.v1",
        "title": f"{hub['title']} continuity carry policy",
        "proofBoundary": (
            "source/static + generated-artifact; Core.zip install is opt-in via "
            f"tools/install_roe_castle_continuity_weave.py --hub {hub['hub']}; "
            "runtime transfer writeback unvalidated"
        ),
        "planDoc": "docs/plans/2026-07-10-homm3-campaign-continuity-viability.md",
        "hostShell": "native_storyhub",
        "campaign": {
            "hubSid": hub["hubSid"],
            "campaignTitle": hub["title"],
            "campaignEntry": hub["entry"],
            "batchManifest": "scenarios/ab_sod_campaigns/batch_manifest.json",
            "missionConfigPrefix": hub["prefix"],
            "defaultSpawn": {
                "factionSid": hub["factionSid"],
                "heroSid": hub["heroSid"],
            },
            "hubSidNote": (
                "AB/SoD StoryHub: dedicated selection stills from hub strips; "
                "MapImage may still reuse RoE BG stand-ins."
                + (
                    " Packaging SIDs remain historical necropolis_* ids; "
                    "protagonist is Fortress Adrienne."
                    if hub["hub"] == "fire"
                    else ""
                )
            ),
            "regionPixels": chain_region_pixels(missions),
        },
        "storyHubMapSidOverrides": {
            **overrides,
            "choiceReason": (
                f"{hub['title']} missions use raw_translation (full core overlay) "
                "with Story_maps-only install."
            ),
        },
        "nativeTransfer": {
            "storyHubField": "transferHeroProgressFromSession",
            "campaignInfoField": "transferHeroProgressFromSession_",
            "requiredValue": True,
            "storyHubSaveField": "heroesSaves",
            "heroProgressFields": [
                "level",
                "experience",
                "skills",
                "magics",
                "slots",
                "inventory",
                "statsByLevel",
                "additionalStats",
                "perks",
            ],
            "evidence": [
                "Hex.StoryHub.DB.Config.StoryHub.transferHeroProgressFromSession",
                "Hex.Session.CampaignInfo.transferHeroProgressFromSession_",
                "Hex.StoryHub.Data.StoryHubSave.heroesSaves",
                "Hex.StoryHub.Data.Hero level/experience/skills/magics/slots/inventory",
            ],
        },
        "minimumFaithfulSubset": {
            "dimensions": [
                "experience",
                "primarySkills",
                "secondarySkills",
                "spells",
                "artifacts",
            ],
            "status": "required_for_v1",
            "proofLabel": "source/static-inferred from StoryHub.Data.Hero shape + VCMI heroKeeps",
        },
        "deferredExplicitLoss": {
            "dimensions": ["keepCreatures"],
            "status": "deferred_not_silently_supported",
            "reason": (
                "Olden StoryHub hero save sheet does not prove army/creature carry; "
                "army carry remains a separate decision."
            ),
            "proofLabel": "not-traceable-yet",
        },
        "handoffs": handoffs,
        "missionChain": missions,
        "missionTitles": {
            mission_id: titles_by_mission[mission_id] for mission_id in missions
        },
        "missionDescriptions": {
            mission_id: descriptions_by_mission[mission_id] for mission_id in missions
        },
        "nonGoalsForThisMilestone": [
            "Plugin playable-shell CampaignInfo population",
            "Army/creature carry",
            "Strongest-N selection bridge",
            "Mission/hub PlayVideo clips",
            "Dedicated AB/SoD MapImage bake",
            "Town growth / negative resource timed-event fidelity",
        ],
        "videoContract": {
            "status": "hub_hover_strip_omitted_no_mission_clips",
            "hubFirstShowPlayVideo": False,
            "hubFirstShowClipKey": None,
            "hubFirstShowOmitReason": (
                "AB/SoD first pass defers videos (Specter pattern); OpenMissionsPrologue only."
            ),
            "requiredMp4RelativeToStreamingAssets": None,
            "selectionIcon": {
                "storyHubField": "mainIconSid",
                "iconSid": "main_icon",
                "coreMember": f"campaigns/{hub['hubSid']}/icons/main_icon.png",
                "nativeSize": [378, 693],
                "stillArtifact": still,
                "composePolicy": "letterbox_trim_then_vertical_focus",
                "focusX": hub["focusX"],
                "focusY": hub["focusY"],
                "cropReason": (
                    f"Stand-in still {hub['iconStill']} pending dedicated {hub['hub']} art"
                ),
                "cropsCatalog": "scenarios/roe_castle_campaign/selection_icon_crops.v1.json",
            },
            "clipsInfoMember": "DB/clips_info.json",
            "missionClipKeys": {},
            "actionOrder": "OpenMissionsPrologue only on each mission pin (no PlayVideo)",
            "failClosed": (
                f"{hub['hub']} hub firstShowActions must stay empty. "
                "missionClipKeys stays empty — no per-mission PlayVideo."
            ),
        },
    }
    out = ROOT / "scenarios" / "ab_sod_campaigns" / f"continuity_carry_policy_{hub['hub']}.v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    rows = build_loc_rows()
    loc_path = write_localization(rows)
    print(f"Wrote {loc_path} rows={len(rows)}")

    titles_by_mission: dict[str, str] = {}
    descriptions_by_mission: dict[str, str] = {}
    for hub in HUB_SPECS:
        for block_index, mission_id in enumerate(hub["missions"], 1):
            source = load_h3c_block(hub["entry"], block_index)
            titles_by_mission[mission_id] = (source.summary.title or mission_id).strip()
            descriptions_by_mission[mission_id] = clip(
                source.summary.description or titles_by_mission[mission_id], 172
            )

    for hub in HUB_SPECS:
        path = write_carry_policy(hub, titles_by_mission, descriptions_by_mission)
        print(f"Wrote {path}")

    hub_index = {
        "schema": "homm3.ab_sod_hub_index.v1",
        "hubs": [
            {
                "hub": h["hub"],
                "hubSid": h["hubSid"],
                "prefix": h["prefix"],
                "factionTag": h["factionTag"],
                "missions": h["missions"],
                "factionSid": h["factionSid"],
                "heroSid": h["heroSid"],
            }
            for h in HUB_SPECS
        ],
    }
    index_path = ROOT / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"
    index_path.write_text(json.dumps(hub_index, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
