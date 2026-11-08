"""HoMM3 external dwelling (AVG*) → Olden land-on barracks clones.

Donor SIDs are ``barracks_homm3_{faction}_{tier}`` already in Core. Campaign emit
uses 1x1 visit-GATE clones ``homm3_landon_barracks_{faction}_{tier}``.

Neutral dwellings (H3M objects 18-20) use creature-keyed SIDs
``barracks_homm3_neutral_{creature}`` → ``homm3_landon_barracks_neutral_{creature}``.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Faction → max dwelling tier present as barracks_homm3_* in Core.
HOMM3_BARRACKS_FACTION_TIERS: dict[str, int] = {
    "castle": 7,
    "rampart": 7,
    "tower": 7,
    "inferno": 7,
    "necropolis": 7,
    "dungeon": 7,
    "stronghold": 7,
    "fortress": 7,
    "conflux": 7,
    "cove": 7,
    "factory": 8,
    "bulwark": 7,
}


def barracks_donor_sid(faction: str, tier: int) -> str:
    return f"barracks_homm3_{faction}_{tier}"


def landon_barracks_clone_sid(faction: str, tier: int) -> str:
    return f"homm3_landon_barracks_{faction}_{tier}"


def neutral_barracks_donor_sid(creature_key: str) -> str:
    return f"barracks_homm3_neutral_{creature_key}"


def neutral_landon_barracks_clone_sid(creature_key: str) -> str:
    return f"homm3_landon_barracks_neutral_{creature_key}"


def _load_neutral_dwelling_keys() -> list[tuple[str, str, str]]:
    """Return (defName, creature_key, rule) rows from the neutral catalog."""
    repo_root = Path(__file__).resolve().parents[2]
    tools_release = repo_root / "tools" / "release_port"
    if str(tools_release) not in sys.path:
        sys.path.insert(0, str(tools_release))
    from homm3_neutral_catalog import catalog_dwellings, load_homm3_neutral_catalog

    catalog = load_homm3_neutral_catalog(repo_root / "tools" / "homm3_import" / "faction_concepts" / "homm3_neutral.json")
    rows: list[tuple[str, str, str]] = []
    for dwelling in catalog_dwellings(catalog):
        barracks_sid = str(dwelling["barracksSid"])
        creature_key = barracks_sid.removeprefix("barracks_homm3_neutral_")
        def_name = str(dwelling["defName"])
        rule = f"creature_generator_neutral_{creature_key}"
        rows.append((def_name, creature_key, rule))
        aliases = dwelling.get("defNameAliases") or []
        if isinstance(aliases, list):
            for alias in aliases:
                rows.append((str(alias), creature_key, rule))
    return rows


def build_landon_barracks_by_donor() -> dict[str, str]:
    out: dict[str, str] = {}
    for faction, max_tier in HOMM3_BARRACKS_FACTION_TIERS.items():
        for tier in range(1, max_tier + 1):
            donor = barracks_donor_sid(faction, tier)
            out[donor] = landon_barracks_clone_sid(faction, tier)
    for _def_name, creature_key, _rule in _load_neutral_dwelling_keys():
        donor = neutral_barracks_donor_sid(creature_key)
        out[donor] = neutral_landon_barracks_clone_sid(creature_key)
    return out


HOMM3_LANDON_BARRACKS_BY_DONOR = build_landon_barracks_by_donor()
HOMM3_LANDON_BARRACKS_SIDS = frozenset(HOMM3_LANDON_BARRACKS_BY_DONOR.values())


def _entry(faction: str, tier: int, rule: str) -> tuple[str, str]:
    return landon_barracks_clone_sid(faction, tier), rule


def _neutral_entry(creature_key: str, rule: str) -> tuple[str, str]:
    return neutral_landon_barracks_clone_sid(creature_key), rule


# Exact HoMM3 adventure-map dwelling DEF → land-on barracks clone.
# Keys are canonical spelling as seen on H3M templates (case-sensitive match first;
# callers should also try the lowercase key).
CREATURE_GENERATOR_ANIMATION_EXACT_MAP: dict[str, tuple[str, str]] = {
    # Castle
    "AVGpike0.def": _entry("castle", 1, "creature_generator_castle_guardhouse"),
    "AVGcros0.def": _entry("castle", 2, "creature_generator_castle_archers_tower"),
    "AVGgrff0.def": _entry("castle", 3, "creature_generator_castle_griffin_tower"),
    "AVGswor0.def": _entry("castle", 4, "creature_generator_castle_barracks"),
    "AVGmonk0.def": _entry("castle", 5, "creature_generator_castle_monastery"),
    "AVGcavl0.def": _entry("castle", 6, "creature_generator_castle_training_grounds"),
    "AVGangl0.def": _entry("castle", 7, "creature_generator_castle_portal_of_glory"),
    # Rampart
    "AVGcent0.def": _entry("rampart", 1, "creature_generator_rampart_centaur_stables"),
    "AVGdwrf0.def": _entry("rampart", 2, "creature_generator_rampart_dwarf_cottage"),
    "AVGelf0.def": _entry("rampart", 3, "creature_generator_rampart_homestead"),
    "AVGpega0.def": _entry("rampart", 4, "creature_generator_rampart_enchanted_spring"),
    "AVGtree0.def": _entry("rampart", 5, "creature_generator_rampart_dendroid_arches"),
    "AVGunic0.def": _entry("rampart", 6, "creature_generator_rampart_unicorn_glade"),
    "AVGgren0.def": _entry("rampart", 7, "creature_generator_rampart_dragon_cliffs"),
    "AVGgdrg0.def": _entry("rampart", 7, "creature_generator_rampart_gold_dragon_cliffs"),
    # Tower
    "AVGgrem0.def": _entry("tower", 1, "creature_generator_tower_workshop"),
    "AVGgarg0.def": _entry("tower", 2, "creature_generator_tower_parapet"),
    "AVGgolm0.def": _entry("tower", 3, "creature_generator_tower_golem_factory"),
    "AVGmage0.def": _entry("tower", 4, "creature_generator_tower_mage_tower"),
    "AVGgeni0.def": _entry("tower", 5, "creature_generator_tower_altar_of_wishes"),
    "AVGnaga0.def": _entry("tower", 6, "creature_generator_tower_golden_pavilion"),
    "AVGtitn0.def": _entry("tower", 7, "creature_generator_tower_cloud_temple"),
    # Inferno
    "AVGimp0.def": _entry("inferno", 1, "creature_generator_inferno_imp_crucible"),
    "AVGgogs0.def": _entry("inferno", 2, "creature_generator_inferno_hall_of_sins"),
    "AVGhell0.def": _entry("inferno", 3, "creature_generator_inferno_kennels"),
    "AVGdemn0.def": _entry("inferno", 4, "creature_generator_inferno_demon_gate"),
    "AVGpit0.def": _entry("inferno", 5, "creature_generator_inferno_hell_hole"),
    "AVGefre0.def": _entry("inferno", 6, "creature_generator_inferno_fire_lake"),
    "AVGdevl0.def": _entry("inferno", 7, "creature_generator_inferno_forsaken_palace"),
    # Necropolis
    "AVGskel0.def": _entry("necropolis", 1, "creature_generator_necropolis_cursed_temple"),
    "AVGzomb0.def": _entry("necropolis", 2, "creature_generator_necropolis_graveyard"),
    "AVGwght0.def": _entry("necropolis", 3, "creature_generator_necropolis_tomb_of_souls"),
    "AVGwigh0.def": _entry("necropolis", 3, "creature_generator_necropolis_tomb_of_souls"),
    "AVGvamp0.def": _entry("necropolis", 4, "creature_generator_necropolis_estate"),
    "AVGlich0.def": _entry("necropolis", 5, "creature_generator_necropolis_mausoleum"),
    "AVGbkni0.def": _entry("necropolis", 6, "creature_generator_necropolis_hall_of_darkness"),
    "AVGbone0.def": _entry("necropolis", 7, "creature_generator_necropolis_dragon_vault"),
    # Dungeon
    "AVGtrog0.def": _entry("dungeon", 1, "creature_generator_dungeon_warren"),
    "AVGharp0.def": _entry("dungeon", 2, "creature_generator_dungeon_harpy_loft"),
    "AVGbehl0.def": _entry("dungeon", 3, "creature_generator_dungeon_pillar_of_eyes"),
    # Live H3M / HotA sprite stems for Beholder / Medusa (faction art uses these too)
    "AVGbhld0.def": _entry("dungeon", 3, "creature_generator_dungeon_pillar_of_eyes"),
    "AVGbhld.def": _entry("dungeon", 3, "creature_generator_dungeon_pillar_of_eyes"),
    "AVGmedu0.def": _entry("dungeon", 4, "creature_generator_dungeon_chapel_of_stilled_voices"),
    "AVGmdsa0.def": _entry("dungeon", 4, "creature_generator_dungeon_chapel_of_stilled_voices"),
    "AVGmdsa.def": _entry("dungeon", 4, "creature_generator_dungeon_chapel_of_stilled_voices"),
    "AVGmino0.def": _entry("dungeon", 5, "creature_generator_dungeon_labyrinth"),
    "AVGmant0.def": _entry("dungeon", 6, "creature_generator_dungeon_manticore_lair"),
    "AVGddgn0.def": _entry("dungeon", 7, "creature_generator_dungeon_dragon_cave"),
    "AVGrdrg0.def": _entry("dungeon", 7, "creature_generator_dungeon_red_dragon_cave"),
    # Stronghold
    "AVGgobl0.def": _entry("stronghold", 1, "creature_generator_stronghold_goblin_barracks"),
    "AVGwolf0.def": _entry("stronghold", 2, "creature_generator_stronghold_wolf_pen"),
    "AVGorcc0.def": _entry("stronghold", 3, "creature_generator_stronghold_orc_tower"),
    "AVGorcg0.def": _entry("stronghold", 3, "creature_generator_stronghold_orc_tower"),
    "AVGogre0.def": _entry("stronghold", 4, "creature_generator_stronghold_ogre_fort"),
    "AVGrocs0.def": _entry("stronghold", 5, "creature_generator_stronghold_cliff_nest"),
    "AVGcycl0.def": _entry("stronghold", 6, "creature_generator_stronghold_cyclops_cave"),
    "AVGbhmt0.def": _entry("stronghold", 7, "creature_generator_stronghold_behemoth_lair"),
    # Fortress
    "AVGgnll0.def": _entry("fortress", 1, "creature_generator_fortress_gnoll_hut"),
    "AVGlzrd0.def": _entry("fortress", 2, "creature_generator_fortress_lizard_den"),
    "AVGdfly0.def": _entry("fortress", 3, "creature_generator_fortress_serpent_fly_hive"),
    "AVGbasl0.def": _entry("fortress", 4, "creature_generator_fortress_basilisk_pit"),
    "AVGgorg0.def": _entry("fortress", 5, "creature_generator_fortress_gorgon_lair"),
    "AVGwyvn0.def": _entry("fortress", 6, "creature_generator_fortress_wyvern_nest"),
    "AVGhydr0.def": _entry("fortress", 7, "creature_generator_fortress_hydra_pond"),
    # Conflux (RoE stems + SoD/AB variant stems seen on live H3M templates)
    "AVGpxie0.def": _entry("conflux", 1, "creature_generator_conflux_magic_lantern"),
    "AVGpixie.def": _entry("conflux", 1, "creature_generator_conflux_magic_lantern"),
    "AVGpixie0.def": _entry("conflux", 1, "creature_generator_conflux_magic_lantern"),
    "AVGair0.def": _entry("conflux", 2, "creature_generator_conflux_altar_of_air"),
    "AVG2ela.def": _entry("conflux", 2, "creature_generator_conflux_altar_of_air"),
    "AVG2ela0.def": _entry("conflux", 2, "creature_generator_conflux_altar_of_air"),
    "AVGwatr0.def": _entry("conflux", 3, "creature_generator_conflux_altar_of_water"),
    "AVG2elw.def": _entry("conflux", 3, "creature_generator_conflux_altar_of_water"),
    "AVG2elw0.def": _entry("conflux", 3, "creature_generator_conflux_altar_of_water"),
    "AVGfire0.def": _entry("conflux", 4, "creature_generator_conflux_altar_of_fire"),
    "AVG2elf.def": _entry("conflux", 4, "creature_generator_conflux_altar_of_fire"),
    "AVG2elf0.def": _entry("conflux", 4, "creature_generator_conflux_altar_of_fire"),
    "AVGerth0.def": _entry("conflux", 5, "creature_generator_conflux_altar_of_earth"),
    "AVG2ele.def": _entry("conflux", 5, "creature_generator_conflux_altar_of_earth"),
    "AVG2ele0.def": _entry("conflux", 5, "creature_generator_conflux_altar_of_earth"),
    "AVGpsy0.def": _entry("conflux", 6, "creature_generator_conflux_altar_of_thought"),
    "AVGfbrd.def": _entry("conflux", 6, "creature_generator_conflux_altar_of_thought"),
    "AVGfbrd0.def": _entry("conflux", 6, "creature_generator_conflux_altar_of_thought"),
    "AVGelem0.def": _entry("conflux", 7, "creature_generator_conflux_pyre"),
    "AVGelp.def": _entry("conflux", 7, "creature_generator_conflux_pyre"),
    "AVGelp0.def": _entry("conflux", 7, "creature_generator_conflux_pyre"),
    # Rampart SoD unicorn / crystal-dragon cliff variants
    "AVG2uni.def": _entry("rampart", 6, "creature_generator_rampart_unicorn_glade"),
    "AVG2uni0.def": _entry("rampart", 6, "creature_generator_rampart_unicorn_glade"),
    "AVGcdrg.def": _entry("rampart", 7, "creature_generator_rampart_dragon_cliffs"),
    "AVGcdrg0.def": _entry("rampart", 7, "creature_generator_rampart_dragon_cliffs"),
    # SoD Azure Dragon cave (no Core neutral azure barracks; role→Rampart T7 cliffs)
    "AVGazur.def": _entry("rampart", 7, "creature_generator_azure_dragon_cave_to_rampart_dragon_cliffs"),
    "AVGazur0.def": _entry("rampart", 7, "creature_generator_azure_dragon_cave_to_rampart_dragon_cliffs"),
    # SoD Faerie / Rust Dragon caves (same role→Rampart T7 cliffs policy as Azure)
    "AVGfdrg.def": _entry("rampart", 7, "creature_generator_faerie_dragon_cave_to_rampart_dragon_cliffs"),
    "AVGfdrg0.def": _entry("rampart", 7, "creature_generator_faerie_dragon_cave_to_rampart_dragon_cliffs"),
    "AVGrust.def": _entry("rampart", 7, "creature_generator_rust_dragon_cave_to_rampart_dragon_cliffs"),
    "AVGrust0.def": _entry("rampart", 7, "creature_generator_rust_dragon_cave_to_rampart_dragon_cliffs"),
    # Neutral Troll cave (SoD/AB); Core has unit h3_troll but no neutral troll barracks yet →
    # Stronghold T4 Ogre Fort role stand-in (same tier band).
    "AVGtrll.def": _entry("stronghold", 4, "creature_generator_neutral_troll_to_stronghold_ogre_fort"),
    "AVGtrll0.def": _entry("stronghold", 4, "creature_generator_neutral_troll_to_stronghold_ogre_fort"),
}


def _register_neutral_dwelling_animations() -> None:
    for def_name, creature_key, rule in _load_neutral_dwelling_keys():
        entry = _neutral_entry(creature_key, rule)
        CREATURE_GENERATOR_ANIMATION_EXACT_MAP[def_name] = entry
        CREATURE_GENERATOR_ANIMATION_EXACT_MAP[def_name.lower()] = entry


_register_neutral_dwelling_animations()


def lookup_creature_generator_replacement(animation: str) -> tuple[str, str] | None:
    if not animation:
        return None
    hit = CREATURE_GENERATOR_ANIMATION_EXACT_MAP.get(animation)
    if hit is not None:
        return hit
    return CREATURE_GENERATOR_ANIMATION_EXACT_MAP.get(animation.lower())
