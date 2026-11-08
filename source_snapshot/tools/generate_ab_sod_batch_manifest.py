#!/usr/bin/env python3
"""Generate scenarios/ab_sod_campaigns/batch_manifest.json and print H3M map rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

import port_homecoming_poc as poc
from h3c_mission_source import load_h3c_block, resolve_h3c_lod_path

SPEC = [
    (
        "ab",
        "ab.h3c",
        "Armageddon's Blade",
        "conflux",
        [
            ("catherines_charge", "Catherine's Charge", "A- Catherine's Charge.h3m"),
            ("seeking_armageddon", "Seeking Armageddon", "B- Seeking Armageddon.h3m"),
            ("shadows_of_the_forest", "Shadows of the Forest", "C- Shadows of the Forest.h3m"),
            ("maker_of_sorrows", "Maker of Sorrows", "D- Maker of Sorrows.h3m"),
            ("return_of_the_king", "Return of the King", "E- Return of the King.h3m"),
            ("a_blade_in_the_back", "A Blade in the Back", "F- A Blade in the Back.h3m"),
            ("to_kill_a_hero", "To Kill A Hero", "G- To Kill a Hero.h3m"),
            ("oblivions_edge", "Oblivion's Edge", "H- Oblivion's Edge.h3m"),
        ],
    ),
    (
        "blood",
        "blood.h3c",
        "Dragon's Blood",
        "dungeon",
        [
            ("culling_the_weak", "Culling the Weak", "DB1 Culling the Weak.h3m"),
            ("savaging_the_scavengers", "Savaging the Scavengers", "DB2 Savaging the Scavengers.h3m"),
            ("blood_of_the_dragon_father", "Blood of the Dragon Father", "DB3 Blood of the Dragon Father.h3m"),
            ("blood_thirsty", "Blood Thirsty", "DB4 Blood Thirsty.h3m"),
        ],
    ),
    (
        "slayer",
        "slayer.h3c",
        "Dragon Slayer",
        "tower",
        [
            ("rust_dragons", "Rust Dragons", "DragonSlayer02.h3m"),
            ("faerie_dragons", "Faerie Dragons", "DragonSlayer03.h3m"),
            ("azure_dragons", "Azure Dragons", "DragonSlayer04.h3m"),
            ("crystal_dragons", "Crystal Dragons", "DragonSlayer01.h3m"),
        ],
    ),
    (
        "festival",
        "festival.h3c",
        "Festival of Life",
        "stronghold",
        [
            ("for_the_throne", "For the Throne", "Festival of life 4.h3m"),
            ("clan_war", "Clan War", "Festival of Life 3.h3m"),
            ("taming_of_the_wild", "Taming of the wild", "Festival of life 2.h3m"),
            ("razor_claw", "Razor Claw", "Festival of life 1.h3m"),
        ],
    ),
    (
        "fire",
        "fire.h3c",
        "Playing with Fire",
        "necropolis",
        [
            ("farming_towns", "Farming Towns", "Adrienne1.h3m"),
            ("march_of_the_undead", "March of the Undead", "Adrienne2.h3m"),
            ("burning_of_tatalia", "Burning of Tatalia", "Adrienne3.h3m"),
        ],
    ),
    (
        "fool",
        "fool.h3c",
        "Foolhardy Waywardness",
        "castle",
        [
            ("lost_at_sea", "Lost at Sea", "Secret 1 - Lost at Sea.h3m"),
            ("here_there_be_pirates", "Here There Be Pirates", "Secret 3 - Here There Be Pirates.h3m"),
            ("hurry_up_and_wait", "Hurry Up and Wait", "Secret 4 - Hurry Up and Wait.h3m"),
            ("their_end_of_the_bargain", "Their End of the Bargain", "Secret 2 - Their End Of the Bargain.h3m"),
        ],
    ),
    (
        "sandro",
        "Sandro.h3c",
        "Rise of the Necromancer",
        "necropolis",
        [
            ("target", "Target", "Sandro A.h3m"),
            ("master", "Master", "Sandro B.h3m"),
            ("finneas_vilmar", "Finneas Vilmar", "Sandro C.h3m"),
            ("duke_alarice", "Duke Alarice", "Sandro D.h3m"),
        ],
    ),
    (
        "crag",
        "Crag.h3c",
        "Hack and Slash",
        "stronghold",
        [
            ("bashing_skulls", "Bashing Skulls", "Has01.h3m"),
            ("black_sheep", "Black Sheep", "Has02.h3m"),
            ("a_cage_in_the_hand", "A Cage in the Hand", "Has03.h3m"),
            ("grave_robber", "Grave Robber", "Has04.h3m"),
        ],
    ),
    (
        "yog",
        "Yog.h3c",
        "Birth of a Barbarian",
        "stronghold",
        [
            ("on_the_run", "On the Run", "Yog A.h3m"),
            ("the_meeting", "The Meeting", "Yog B.h3m"),
            ("a_tough_start", "A Tough Start", "Yog C.h3m"),
            ("falor_and_terwen", "Falor and Terwen", "Yog D.h3m"),
            ("returning_to_bracada", "Returning to Bracada", "Yog E.h3m"),
        ],
    ),
    (
        "gem",
        "Gem.h3c",
        "New Beginning",
        "rampart",
        [
            ("clearing_the_border", "Clearing the Border", "Gem1.h3m"),
            ("after_the_amulet", "After the Amulet", "Gem2.h3m"),
            ("retrieving_the_cowl", "Retrieving the Cowl", "Gem3.h3m"),
            ("driving_for_the_boots", "Driving for the Boots", "Gem4.h3m"),
        ],
    ),
    (
        "gelu",
        "Gelu.h3c",
        "Elixir of Life",
        "rampart",
        [
            ("graduation_exercise", "Graduation Exercise", "gelu1.h3m"),
            ("cutthroats", "Cutthroats", "gelu2.h3m"),
            ("valley_of_the_dragon_lords", "Valley of the Dragon Lords", "gelu3.h3m"),
            ("a_thief_in_the_night", "A Thief in the Night", "gelu4.h3m"),
        ],
    ),
    (
        "final",
        "Final.h3c",
        "Unholy Alliance",
        "necropolis",
        [
            ("harvest", "Harvest", "Final A.h3m"),
            ("gathering_the_legion", "Gathering the Legion", "Final B.h3m"),
            ("search_for_a_killer", "Search for a Killer", "Final C.h3m"),
            ("final_peace", "Final Peace", "Final D.h3m"),
            ("secrets_revealed", "Secrets Revealed", "Final E.h3m"),
            ("agents_of_vengeance", "Agents of Vengeance", "Final F.h3m"),
            ("wrath_of_sandro", "Wrath of Sandro", "Final G.h3m"),
            ("invasion", "Invasion", "Final H.h3m"),
            ("to_strive_to_seek", "To Strive, To Seek", "Final I.h3m"),
            ("barbarian_brothers", "Barbarian Brothers", "Final J .h3m"),
            ("union", "Union", "Final K.h3m"),
            ("fall_of_sandro", "Fall of Sandro", "Final L.h3m"),
        ],
    ),
]

NEED_H3M_MAP = {
    "ab.h3c",
    "blood.h3c",
    "slayer.h3c",
    "festival.h3c",
    "fire.h3c",
    "fool.h3c",
    "Final.h3c",
}


def main() -> int:
    missions: list[dict] = []
    h3m_rows: list[str] = []
    for _hub, entry, camp_title, faction_tag, miss in SPEC:
        for i, (mid, display, h3m) in enumerate(miss, 1):
            src = load_h3c_block(entry, i)
            layers = list(range(int(src.summary.layers)))
            ug = [layer for layer in layers if layer > 0]
            missions.append(
                {
                    "missionId": mid,
                    "scenarioId": f"{mid}_ab_sod",
                    "campaignEntry": entry,
                    "blockIndex": i,
                    "campaignTitle": camp_title,
                    "artifactRoot": f"artifacts/campaign_port_poc/ab_sod_campaigns/{mid}",
                    "mapSid": f"h3_{faction_tag}_{mid}_raw_translation",
                    "title": f"{display} - Raw Translation",
                    "layerIds": layers,
                    "undergroundLayers": ug,
                    "pathability": {
                        "surfaceGapFill": False,
                        "emitCoreOverlay": False,
                    },
                    "rawTranslation": {
                        "playersCount": 1,
                        "replaceKnownGaps": True,
                        "knownGaps": [
                            "AB/SoD StoryHub raw_translation first pass; videos deferred; runtime unvalidated.",
                            "Campaign-unique heroes may map lossily via h3m_hero_sid.",
                        ],
                    },
                }
            )
            if entry in NEED_H3M_MAP:
                h3m_rows.append(f'    ("{entry}", {i}): "{h3m}",')
            print(f"OK {mid}: layers={layers} v={src.summary.version}")

    if len(missions) != 60:
        raise SystemExit(f"expected 60 missions; got {len(missions)}")

    manifest = {
        "schema": "homm3.olden_campaign_batch_manifest.v1",
        "title": "Armageddon's Blade + Shadow of Death — Complete Edition campaigns",
        "description": (
            "All 12 AB+SoD official campaigns (60 missions). StoryHub weaves install via "
            "tools/install_roe_castle_continuity_weave.py --hub "
            "ab|blood|slayer|festival|fire|fool|sandro|crag|yog|gem|gelu|final. "
            "Videos deferred (Specter pattern). HotA/H3HD excluded. "
            "Source: Complete H3bitmap.lod + H3ab_bmp.lod."
        ),
        "templateMap": (
            "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
            "HeroesOldenEra_Data/StreamingAssets/maps/Thirst_for_Power.map"
        ),
        "coreCatalog": (
            "artifacts/campaign_port_poc/olden_entity_catalog/"
            "olden_core_map_valid_entity_catalog.json"
        ),
        "defaultSpawn": {
            "factionSid": "homm3_castle",
            "heroSid": "homm3_castle_hero_7",
            "playersCount": 1,
        },
        "missions": missions,
    }

    out = ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out} missions={len(missions)}")

    for _hub, entry, _camp_title, _faction_tag, miss in SPEC:
        if entry not in NEED_H3M_MAP:
            continue
        lod = resolve_h3c_lod_path(entry)
        raw = poc.read_lod_entry(lod, entry)
        blocks = poc.split_concatenated_gzip_members(raw)
        campaign_bytes = b"".join(member.payload for member in blocks)
        strings = {item.text for item in poc.scan_length_prefixed_strings(campaign_bytes)}
        for i, (_mid, _display, h3m) in enumerate(miss, 1):
            if h3m not in strings:
                raise SystemExit(f"MISSING STRING {entry} block {i}: {h3m!r}")
            print(f"found {entry}/{i}: {h3m}")

    map_out = ROOT / "scenarios" / "ab_sod_campaigns" / "h3m_name_map_additions.txt"
    map_out.write_text("\n".join(h3m_rows) + "\n", encoding="utf-8")
    print(f"Wrote {map_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
