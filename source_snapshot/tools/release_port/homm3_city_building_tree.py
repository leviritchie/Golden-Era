#!/usr/bin/env python3
"""Canonical HoMM3 (SoD + HotA) town building trees, adapted to Olden Era city rows.

One table owns every ``prevBuildings`` list of every ``homm3_*_city``. The overlay
(``apply_release_core_overlay.py``) replaces each level's prerequisites with exactly
this table, and ``validate_homm3_city_building_tree_contract.py`` checks the installed
Core against it. The construction-tree ``nodePos`` cells are then derived from these
prerequisites by :func:`solve_construction_tree_layout`, so the drawn tree and the
build logic cannot disagree.

Reference: VCMI's SoD faction configs (``vcmi/vcmi`` ``config/factions/*.json`` and
``config/buildingsLibrary.json``) and the HotA mod (``vcmi-mods/horn-of-the-abyss``
``mods/{cove,factory,bulwark}/.../town``). Fetched 2026-10-01. ``upgrades`` in VCMI
means "requires the building it upgrades"; here every level > 1 requires the level
before it implicitly and the table lists only the extra HoMM3 requirements.

OE SID -> HoMM3 building identity follows each city's English name row (the names
the player sees in the build panel); see ``docs/homm3_city_building_tree.md`` for the
per-faction crosswalk and every adaptation.
"""
from __future__ import annotations

from typing import Any, Iterable

Req = tuple[str, int]
Key = tuple[str, int]

MAIN = "Build_Main"
TAVERN = ("Build_Tavern", 1)
MARKET = ("Build_Market", 1)
BLACKSMITH = ("Build_Treasury", 1)  # every HoMM3 city names its Build_Treasury row "Blacksmith"; it is the vanilla OE Treasury (2000 Gold daily) and gates nothing
SILO = ("Build_Resource_Depot", 1)
BANK = ("Build_Bank", 1)


def T(tier: int, level: int = 1) -> Req:
    return (f"Build_Tier_{tier}", level)


def MG(level: int) -> Req:
    return ("Build_Magic_Guild", level)


def WALL(level: int) -> Req:
    return ("Build_Wall", level)


def HALL(level: int) -> Req:
    return (MAIN, level)


# Level-1 prerequisites shared by every HoMM3 city (HoMM3 common buildings).
COMMON_LEVEL_REQS: dict[str, tuple[Req, ...]] = {
    "Build_Main:1": (),  # Village Hall
    "Build_Main:2": (TAVERN,),  # Town Hall requires Tavern
    "Build_Main:3": (MG(1), MARKET),  # City Hall requires MG1 + Marketplace (HoMM3 also needs the Blacksmith, which is OE's Treasury here)
    "Build_Tavern:1": (),
    "Build_Market:1": (),  # HoMM3 Marketplace has no requirement (vanilla OE gates it on Tavern; HoMM3 wins)
    "Build_Artifact_Market:1": (MARKET,),  # Artifact Merchants require Marketplace
    "Build_Resource_Depot:1": (MARKET,),  # Resource Silo requires Marketplace
    "Build_Treasury:1": (BANK, WALL(1)),  # Blacksmith = vanilla OE Treasury: Bank + Fort, exactly as every vanilla city
    "Build_Wall:1": (),  # Fort
    "Build_Magic_Guild:1": (),
    # OE daily-gold income rows on the donor Bank SID keep the vanilla OE Town Hall gate
    # unless the faction table names a HoMM3 identity for them.
    "Build_Bank:1": (HALL(2),),
    # Dwelling 1 is a root (see ADAPTATIONS["*"]); every upgrade requires its base.
    "Build_Tier_1:1": (),
}

# Faction-specific entries. Keys are "SID:level"; values are the extra requirements
# beyond the implicit previous level. A level-1 key with () is a declared root.
FACTION_LEVEL_REQS: dict[str, dict[str, tuple[Req, ...]]] = {
    "homm3_castle": {
        "Build_Tier_2:1": (T(1),),  # Archers' Tower <- Guardhouse
        "Build_Tier_3:1": (T(4),),  # Griffin Tower <- Barracks
        "Build_Tier_4:1": (T(1),),  # Barracks <- Guardhouse (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_5:1": (MG(1), T(4)),  # Monastery <- MG1 + Barracks
        "Build_Tier_6:1": (BANK,),  # Training Grounds <- Stables (Mounted Guard Yard)
        "Build_Tier_7:1": (T(5),),  # Portal of Glory <- Monastery
        "Build_Bank:1": (T(4),),  # Mounted Guard Yard = Stables <- Barracks
        "Build_Resource_Depot_level_2:1": (T(3),),  # Griffin Bastion (horde) <- Griffin Tower
        "Build_Golden_Calf:1": (),  # grail
    },
    "homm3_rampart": {
        "Build_Tier_2:1": (T(1),),  # Dwarf Cottage <- Centaur Stables
        "Build_Tier_3:1": (T(1),),  # Homestead <- Centaur Stables
        "Build_Tier_4:1": (T(3),),  # Enchanted Spring <- Homestead
        "Build_Tier_5:1": (T(3),),  # Dendroid Arches <- Homestead
        "Build_Tier_6:1": (T(4), T(5)),  # Unicorn Glade <- Enchanted Spring + Dendroid Arches
        "Build_Tier_7:1": (T(6), MG(2)),  # Dragon Cliffs <- Unicorn Glade + MG2
        "Build_Tier_7:2": (MG(3),),  # Upg. Dragon Cliffs <- MG3
        "Build_Bank:1": (HALL(2),),  # Mystic Pond (HoMM3: none) keeps the OE income gate
        "Build_Mother_Nature:1": (BANK,),  # Fountain of Fortune upgrades Mystic Pond
        "Build_Artifact_Market:1": (MARKET, ("Build_Resource_Depot_level_2", 1)),  # Treasury <- Miners' Guild (+ market: it trades artifacts)
        "Build_Resource_Depot_level_2:1": (T(2),),  # Miners' Guild (horde) <- Dwarf Cottage
        "Build_Mycelium_Roots:1": (T(5),),  # Dendroid Saplings (horde) <- Dendroid Arches
        "Build_Spring_of_Life:1": (),  # grail
    },
    "homm3_tower": {
        "Build_Tier_2:1": (T(1),),  # Parapet <- Workshop
        "Build_Tier_3:1": (T(1),),  # Golem Factory <- Workshop
        "Build_Tier_4:1": (MG(1), T(2), T(3)),  # Mage Tower <- MG1 + Parapet + Golem Factory
        "Build_Tier_4:2": (("Build_Intelligence_Academy", 1),),  # Upg. Mage Tower <- Library
        "Build_Tier_5:1": (T(4),),  # Altar of Wishes <- Mage Tower
        "Build_Tier_6:1": (T(4),),  # Golden Pavilion <- Mage Tower
        "Build_Tier_7:1": (T(5), T(6)),  # Cloud Temple <- Altar of Wishes + Golden Pavilion
        "Build_Intelligence_Academy:1": (MG(1),),  # Library <- MG1
        "Build_Training_Range:1": (MG(1),),  # Wall of Knowledge <- MG1
        "Build_Bank:1": (HALL(3), WALL(3)),  # Capitol Vault = Capitol <- City Hall + Castle
        "Build_Resource_Depot_level_2:1": (T(2),),  # Sculptor's Wings (horde) <- Parapet
        "Build_Golden_Calf:1": (),  # grail
    },
    "homm3_inferno": {
        "Build_Tier_2:1": (T(1),),  # Hall of Sins <- Imp Crucible
        "Build_Tier_3:1": (T(1),),  # Kennels <- Imp Crucible
        "Build_Tier_4:1": (T(2),),  # Demon Gate <- Hall of Sins
        "Build_Tier_5:1": (T(4),),  # Hell Hole <- Demon Gate
        "Build_Tier_5:2": (MG(2),),  # Upg. Hell Hole <- MG2
        "Build_Tier_6:1": (MG(1), T(4)),  # Fire Lake <- MG1 + Demon Gate
        "Build_Tier_7:1": (T(5), T(6)),  # Forsaken Palace <- Hell Hole + Fire Lake
        "Build_Resource_Depot:1": (T(1),),  # Birthing Pools (horde) <- Imp Crucible
        "Build_Resource_Depot_level_2:1": (WALL(1),),  # Brimstone Tolls = Brimstone Clouds <- Fort
        "Build_Bank:1": (WALL(2),),  # Castle Gate <- Citadel
        "Build_Beelzebubs_Hand:1": (),  # OE-native (vanilla demon root)
        "Build_Rebirth_Of_Shrine:1": (WALL(1),),  # OE-native (vanilla demon gate)
        "Build_Eternal_Flame:1": (),  # grail
    },
    "homm3_necropolis": {
        "Build_Tier_2:1": (T(1),),  # Graveyard <- Cursed Temple
        "Build_Tier_3:1": (T(1),),  # Tomb of Souls <- Cursed Temple
        "Build_Tier_4:1": (T(2),),  # Estate <- Graveyard
        "Build_Tier_4:2": (BANK,),  # Upg. Estate <- Necromancy Amplifier (Bone Archive)
        "Build_Tier_5:1": (MG(1), T(2)),  # Mausoleum <- MG1 + Graveyard
        "Build_Tier_6:1": (T(4), T(5)),  # Hall of Darkness <- Estate + Mausoleum
        "Build_Tier_7:1": (T(6),),  # Dragon Vault <- Hall of Darkness
        "Build_Bank:1": (MG(1),),  # Bone Archive = Necromancy Amplifier <- MG1
        "Build_Skeleton_Converter:1": (T(1),),  # Bone Foundry = Skeleton Transformer <- Cursed Temple
        "Build_Resource_Depot_level_2:1": (T(1), ("Build_Skeleton_Converter", 1)),  # Unearthed Graves (horde) <- Cursed Temple + Transformer
        "Build_Well_Of_Souls:1": (MG(3),),  # OE-native (vanilla undead gate)
        "Build_Gaping_Maw:1": (),  # grail
    },
    "homm3_dungeon": {
        "Build_Tier_2:1": (T(1),),  # Harpy Loft <- Warren
        "Build_Tier_3:1": (T(1),),  # Pillar of Eyes <- Warren
        "Build_Tier_4:1": (T(2), T(3)),  # Chapel of Stilled Voices <- Harpy Loft + Pillar of Eyes
        "Build_Tier_5:1": (T(4),),  # Labyrinth <- Chapel
        "Build_Tier_6:1": (T(4),),  # Manticore Lair <- Chapel
        "Build_Tier_7:1": (MG(2), T(5), T(6)),  # Dragon Cave <- MG2 + Labyrinth + Manticore Lair
        "Build_Tier_7:2": (MG(3),),  # Upg. Dragon Cave <- MG3
        "Build_Bank:1": (MG(1),),  # Spellwell = Mana Vortex <- MG1
        "Build_Resource_Depot_level_2:1": (T(1),),  # Mushroom Rings (horde) <- Warren
        "Build_Gymnasium:1": (),  # Academy of Battle Scholars (HoMM3: none)
        "Build_Lyceum:1": (),  # OE-native (vanilla dungeon root)
        "Build_Spy_Network:1": (),  # grail
    },
    "homm3_stronghold": {
        "Build_Tier_2:1": (T(1),),  # Wolf Pen <- Goblin Barracks
        "Build_Tier_2:2": (T(1, 2),),  # Upg. Wolf Pen <- Upg. Goblin Barracks
        "Build_Tier_3:1": (T(1),),  # Orc Tower <- Goblin Barracks
        "Build_Tier_3:2": (),  # Upg. Orc Tower (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_4:1": (T(3),),  # Ogre Fort <- Orc Tower
        "Build_Tier_4:2": (MG(1),),  # Upg. Ogre Fort <- MG1
        "Build_Tier_5:1": (T(2),),  # Cliff Nest <- Wolf Pen
        "Build_Tier_6:1": (T(4),),  # Cyclops Cave <- Ogre Fort
        "Build_Tier_7:1": (T(5),),  # Behemoth Lair <- Cliff Nest
        "Build_Bank:1": (HALL(2),),  # Muster Yard (OE income row)
        "Build_Resource_Depot_level_2:1": (SILO,),  # Resource Silo II (OE-only second silo)
        "Build_Gymnasium:1": (WALL(1),),  # Hall of Valhalla <- Fort
        "Build_Lyceum:1": (T(1),),  # Mess Hall (Goblin horde) <- Goblin Barracks
        "Build_Spy_Network:1": (),  # grail slot (Escape Vault)
    },
    "homm3_fortress": {
        "Build_Tier_1:2": (TAVERN,),  # Upg. Gnoll Hut <- Tavern
        "Build_Tier_2:1": (T(1),),  # Lizard Den <- Gnoll Hut
        "Build_Tier_3:1": (T(1),),  # Serpent Fly Hive <- Gnoll Hut
        "Build_Tier_4:1": (T(3),),  # Basilisk Pit <- Serpent Fly Hive
        "Build_Tier_5:1": (T(2), T(3)),  # Gorgon Lair <- Lizard Den + Serpent Fly Hive
        "Build_Tier_5:2": (SILO,),  # Upg. Gorgon Lair <- Resource Silo
        "Build_Tier_6:1": (T(2),),  # Wyvern Nest <- Lizard Den
        "Build_Tier_7:1": (T(4), T(6)),  # Hydra Pond <- Basilisk Pit + Wyvern Nest
        "Build_Bank:1": (HALL(2), ("Build_Mother_Nature", 1)),  # Cage of Warlords <- Town Hall + Glyphs of Fear
        "Build_Mother_Nature:1": (WALL(1),),  # Glyphs of Fear <- Fort
        "Build_Mycelium_Roots:1": (T(7),),  # Hydra Marsh (Hydra horde) <- Hydra Pond
        "Build_Resource_Depot_level_2:1": (T(1),),  # Captain's Quarters (Gnoll horde) <- Gnoll Hut
        "Build_Spring_of_Life:1": (),  # grail
    },
    "homm3_conflux": {
        "Build_Tier_2:1": (T(1), MG(1)),  # Altar of Air <- Magic Lantern + MG1
        "Build_Tier_3:1": (T(1), MG(1)),  # Altar of Water <- Magic Lantern + MG1
        "Build_Tier_4:1": (T(2),),  # Altar of Fire <- Altar of Air
        "Build_Tier_5:1": (T(3),),  # Altar of Earth <- Altar of Water
        "Build_Tier_6:1": (T(4), T(5)),  # Altar of Thought <- Fire + Earth
        "Build_Tier_6:2": (MG(2),),  # Upg. Altar of Thought <- MG2
        "Build_Tier_7:1": (T(6),),  # Pyre <- Altar of Thought
        "Build_Bank:1": (MG(1),),  # Magic University <- MG1
        "Build_Mother_Nature:1": (T(1),),  # Garden of Life (Pixie horde) <- Magic Lantern
        "Build_Mycelium_Roots:1": (T(2), T(3), T(4), T(5)),  # Elemental Conflux (OE-only, all four altars)
        "Build_Resource_Depot_level_2:1": (T(6),),  # Vault of Ashes (OE-only Firebird horde) <- Altar of Thought (grid depth, see ADAPTATIONS)
        "Build_Spring_of_Life:1": (),  # grail
    },
    "homm3_cove": {
        "Build_Tier_2:1": (T(1),),  # Shack <- Nymph Waterfall
        "Build_Tier_3:1": (T(2),),  # Frigate <- Shack (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_4:1": (T(2),),  # Nest <- Shack
        "Build_Tier_5:1": (MG(1), T(2)),  # Tower of the Seas <- MG1 + Shack
        "Build_Tier_5:2": (MG(2),),  # Upg. Tower of the Seas <- MG2
        "Build_Tier_6:1": (T(4),),  # Nix Fort <- Nest
        "Build_Tier_7:1": (T(5), T(6)),  # Maelstrom <- Tower of the Seas + Nix Fort
        "Build_Tier_7:2": (MG(2),),  # Upg. Maelstrom <- MG2
        "Build_Bank:1": (HALL(2),),  # Thieves' Guild (HotA: Tavern, implied by Town Hall) + OE income gate
        "Build_Resource_Depot_level_2:1": (T(2),),  # Pub (Crew Mate horde) <- Shack
        "Build_Mother_Nature:1": (T(4),),  # Roost (Stormbird horde) <- Nest
        "Build_Golden_Calf:1": (),  # grail
    },
    "homm3_factory": {
        "Build_Tier_1:2": (),  # Upg. Halfling Adobe (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_2:1": (T(1),),  # Foundry <- Halfling Adobe
        "Build_Tier_2:2": (),  # Upg. Foundry (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_3:1": (T(1),),  # Ranch <- Halfling Adobe
        "Build_Tier_4:1": (T(2),),  # Manufactory <- Foundry (HoMM3 Blacksmith gate dropped: OE Treasury)
        "Build_Tier_5:1": (T(3),),  # Catacombs <- Ranch
        "Build_Tier_5:2": (MG(1),),  # Upg. Catacombs <- MG1
        "Build_Tier_6:1": (T(4),),  # Watchtower <- Manufactory
        "Build_Tier_6:2": (MARKET,),  # Upg. Watchtower <- Marketplace
        "Build_Tier_7:1": (T(5), MG(1)),  # Serpentarium <- Catacombs + MG1
        "Build_Tier_7:2": (MG(2),),  # Upg. Serpentarium <- MG2
        "Build_Factory_Gantry:1": (T(6),),  # Gantry (HotA dwelling 8) <- Watchtower
        "Build_Factory_Gantry:2": (MARKET,),  # Upg. Gantry <- Marketplace
        "Build_Bank:1": (HALL(2),),  # Town Bank (HotA Bank: none) keeps the OE income gate
        "Build_Mother_Nature:1": (WALL(1),),  # Mana Dynamo = Mana Generator <- Fort
        "Build_Resource_Depot_level_2:1": (T(3),),  # Pen (Armadillo horde) <- Ranch
        "Build_Golden_Calf:1": (),  # grail
    },
    "homm3_bulwark": {
        "Build_Tier_2:1": (T(1),),  # Frigid Spur <- Colliery
        "Build_Tier_3:1": (T(2),),  # Hall of the Bold <- Frigid Spur
        "Build_Tier_4:1": (T(3),),  # Mountain Embassy <- Hall of the Bold
        "Build_Tier_5:1": (MG(1), T(3)),  # Shaman Fane <- MG1 + Hall of the Bold
        "Build_Tier_6:1": (T(3),),  # Mammoth Stalls <- Hall of the Bold
        "Build_Tier_7:1": (T(5),),  # Frosthome <- Shaman Fane
        "Build_Bank:1": (HALL(2),),  # Trade Hall (OE income row)
        "Build_Mother_Nature:1": (HALL(2), MARKET),  # Trade Carnival = Fair <- Town Hall + Marketplace
        "Build_Mycelium_Roots:1": (T(1),),  # Clan Stockyards (Kobold horde, OE-only) <- Colliery
        "Build_Resource_Depot_level_2:1": (T(6),),  # Hay Bins (Mammoth horde) <- Mammoth Stalls
        "Build_Spring_of_Life:1": (),  # grail
    },
}

ADAPTATIONS: dict[str, list[str]] = {
    "*": [
        "Dwelling 1 is a root. HoMM3 gates it on the Fort; every vanilla OE faction roots tier 1 and OE's Fort (Build_Wall L1) is the siege-wall line, so the gate would block OE's first-week recruitment pacing.",
        "The Blacksmith (Build_Treasury) is the vanilla OE Treasury in every HoMM3 city (2000 Gold daily, <- Bank + Fort; user decision 2026-10-01). Like the vanilla Treasury it gates nothing, so every HoMM3 Blacksmith requirement (City Hall, Castle Barracks, Stronghold Upg. Orc Tower, Cove Frigate, Factory Upg. Halfling Adobe / Upg. Foundry / Manufactory) is dropped; keeping them would also close cycles (Castle Bank <- Barracks, Tower Bank <- City Hall).",
        "OE's hall has 3 levels (Village/Town/City). Town Hall <- Tavern and City Hall <- MG1 + Marketplace are HoMM3; the Capitol (<- Castle) exists only where a faction row names it (Tower Capitol Vault).",
        "Marketplace is a root as in HoMM3 (vanilla OE gates it on the Tavern).",
        "Rows on the donor Bank SID that only pay daily gold keep vanilla OE's Town Hall gate when HoMM3 names no requirement for them.",
        "Shipyard, Lighthouse, Brotherhood of the Sword, Cover of Darkness, Freelancer's Guild, Ballista Yard, Grotto, Gunpowder Warehouse, Sieidi/Altar of Runes and second horde buildings have no OE row; their requirements are not reproduced, and requirements that point at them are dropped (listed per faction).",
        "OE-native special buildings with no HoMM3 counterpart (Lyceum, Beelzebub's Hand, Rebirth Shrine, Well of Souls) keep their vanilla OE prerequisites.",
        "Only direct HoMM3 requirements are listed; transitive ones (e.g. Gantry <- Halfling Adobe) are implied, which keeps the build panel's arrows readable.",
    ],
    "homm3_castle": [
        "Training Grounds <- Stables: OE has no Stables row; the Castle 'Mounted Guard Yard' (Build_Bank) is the Stables and takes its HoMM3 requirement (Barracks).",
    ],
    "homm3_rampart": [
        "The Rampart 'Treasury' row is an OE artifact market: it takes HoMM3 Treasury's Miners' Guild requirement plus the Marketplace its function needs.",
    ],
    "homm3_tower": [
        "'Wall of Knowledge' lives on the Build_Training_Range row (+1 Knowledge to each visiting hero) and takes its requirement (MG1). Lookout Tower has no row.",
    ],
    "homm3_inferno": [
        "'Brimstone Tolls' stands in for Brimstone Clouds (<- Fort); Order of Fire and Cages have no row.",
    ],
    "homm3_necropolis": [
        "'Bone Archive' (Build_Bank) is the Necromancy Amplifier (<- MG1) so Upg. Estate keeps its HoMM3 gate; 'Bone Foundry' is the Skeleton Transformer.",
    ],
    "homm3_stronghold": [
        "Escape Tunnel's Fort requirement is not applied: the 'Escape Vault' row lives in the OE grail slot.",
    ],
    "homm3_fortress": [
        "'Hydra Marsh' (Build_Mycelium_Roots) is an OE Hydra horde row and requires the Hydra Pond; Blood Obelisk has no row.",
    ],
    "homm3_conflux": [
        "'Elemental Conflux' is OE-only (+1 growth for all four elementals) and requires the four altars.",
        "'Vault of Ashes' is an OE-only Firebird horde. Gating it on the Pyre would make Lantern -> Air -> Fire -> Thought -> Pyre -> Vault a 6-row chain, which the native 5-row build panel cannot draw; it requires the Altar of Thought instead (the Pyre's own requirement).",
    ],
    "homm3_cove": [
        "Thieves' Guild requires Tavern in HotA; it is implied by the OE Town Hall income gate (Town Hall <- Tavern).",
    ],
    "homm3_factory": [],
    "homm3_bulwark": [
        "Upg. Mountain Embassy and Upg. Frosthome require Sieidi of Runes in HotA; OE has no Sieidi row, so they require only their base dwelling.",
        "'Trade Carnival' stands in for the Fair (<- Town Hall + Marketplace); 'Clan Stockyards' is an OE-only Kobold horde (<- Colliery).",
    ],
}

GRAIL_SIDS = {
    "Build_Golden_Calf",
    "Build_Spring_of_Life",
    "Build_Eternal_Flame",
    "Build_Gaping_Maw",
    "Build_Spy_Network",
}

HOMM3_TREE_FACTIONS = tuple(FACTION_LEVEL_REQS)
DERIVED_CITY_DONORS = {
    "homm3_landon_castle_city": "homm3_castle_city",
    "homm3_landon_dungeon_city": "homm3_dungeon_city",
}


def faction_for_city_sid(city_sid: str) -> str | None:
    donor = DERIVED_CITY_DONORS.get(city_sid, city_sid)
    if donor.startswith("homm3_") and donor.endswith("_city"):
        faction = donor[: -len("_city")]
        if faction in FACTION_LEVEL_REQS:
            return faction
    return None


def derived_city_member(city_sid: str) -> str:
    return f"DB/objects_logic/cities/{city_sid}.json"


def rederive_city_clone_members(members: dict[str, bytes], read_core_member: Any) -> list[str]:
    """Rewrite each derived city clone in ``members`` as its stock donor with only ``id`` changed.

    ``members`` are Core members about to be installed (a campaign overlay); ``read_core_member``
    reads a member of the Core they are installed into. The donor comes from ``members`` when the
    overlay ships it, else from that Core, so a clone always follows the target Core's tree, never
    the Core the campaign was emitted against. Fails closed when a donor is missing.
    """
    import json

    notes: list[str] = []
    for clone_sid, donor_sid in sorted(DERIVED_CITY_DONORS.items()):
        clone_member = derived_city_member(clone_sid)
        if clone_member not in members:
            continue
        donor_member = derived_city_member(donor_sid)
        donor_bytes = members.get(donor_member)
        source = "overlay"
        if donor_bytes is None:
            donor_bytes = read_core_member(donor_member)
            source = "core"
        if donor_bytes is None:
            raise ValueError(f"{clone_sid}: stock donor {donor_member} is in neither the overlay nor the Core")
        doc = json.loads(donor_bytes.decode("utf-8-sig"))
        array = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(array, list) or len(array) != 1 or not isinstance(array[0], dict) or array[0].get("id") != donor_sid:
            raise ValueError(f"{donor_member}: expected one array row with id {donor_sid!r}")
        array[0]["id"] = clone_sid
        # Same serialization as the emitter (surface_emit.write_json), so an unchanged clone keeps its bytes.
        rebuilt = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if rebuilt != members[clone_member]:
            notes.append(f"re-derived {clone_sid} from {source} {donor_sid}")
        members[clone_member] = rebuilt
    return notes


def _parse(key: str) -> Key:
    sid, level = key.rsplit(":", 1)
    return sid, int(level)


def city_level_keys(city: dict[str, Any]) -> list[Key]:
    keys: list[Key] = []
    for section in city.values():
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
                continue
            levels = row.get("parametersPerLevel")
            if not isinstance(levels, list):
                continue
            keys.extend((row["sid"], index) for index in range(1, len(levels) + 1))
    return keys


def canonical_prereqs(faction: str, present: Iterable[Key]) -> dict[Key, tuple[Req, ...]]:
    """Exact prevBuildings for every present building level of ``faction``'s city.

    Fails closed when a present level-1 row has no table entry, when a table entry
    names a building level the city does not have, or when a requirement points at a
    building level the city does not have.
    """
    if faction not in FACTION_LEVEL_REQS:
        raise KeyError(f"no HoMM3 building tree for {faction}")
    present_set = set(present)
    table: dict[Key, tuple[Req, ...]] = {_parse(k): v for k, v in COMMON_LEVEL_REQS.items()}
    table.update({_parse(k): v for k, v in FACTION_LEVEL_REQS[faction].items()})
    out: dict[Key, tuple[Req, ...]] = {}
    errors: list[str] = []
    for key in sorted(present_set):
        sid, level = key
        extras = table.get(key)
        if level == 1:
            if extras is None:
                errors.append(f"{sid}@1 has no canonical prerequisite entry")
                continue
            reqs: list[Req] = list(extras)
        else:
            reqs = [(sid, level - 1)] + [r for r in (extras or ()) if r != (sid, level - 1)]
        for req in reqs:
            if req not in present_set:
                errors.append(f"{sid}@{level} requires {req[0]}@{req[1]}, which this city does not have")
        out[key] = tuple(reqs)
    for key in table:
        if key in present_set:
            continue
        if _parse_is_faction_specific(faction, key):
            errors.append(f"canonical entry {key[0]}@{key[1]} names a building level the city does not have")
    if errors:
        raise ValueError(f"{faction}: " + "; ".join(errors))
    cycle = find_cycle(out)
    if cycle:
        raise ValueError(f"{faction}: prerequisite cycle " + " -> ".join(f"{s}@{l}" for s, l in cycle))
    return out


def _parse_is_faction_specific(faction: str, key: Key) -> bool:
    return f"{key[0]}:{key[1]}" in FACTION_LEVEL_REQS[faction]


def find_cycle(prereqs: dict[Key, tuple[Req, ...]]) -> list[Key]:
    state: dict[Key, int] = {}
    stack: list[Key] = []

    def visit(node: Key) -> list[Key]:
        state[node] = 1
        stack.append(node)
        for req in prereqs.get(node, ()):
            if state.get(req) == 1:
                return stack[stack.index(req):] + [req]
            if state.get(req, 0) == 0 and req in prereqs:
                found = visit(req)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return []

    for node in sorted(prereqs):
        if state.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return []


def declared_roots(prereqs: dict[Key, tuple[Req, ...]]) -> list[Key]:
    return sorted(key for key, reqs in prereqs.items() if not reqs)


# --- build orders -----------------------------------------------------------------

def normalize_build_order(order: list[dict[str, Any]], prereqs: dict[Key, tuple[Req, ...]]) -> list[dict[str, Any]]:
    """Drop entries for absent levels and pull every prerequisite ahead of its dependent.

    Entry order is otherwise preserved; a prerequisite missing from the order is inserted
    immediately before the first entry that needs it.
    """
    placed: set[Key] = set()
    out: list[dict[str, Any]] = []

    def place(key: Key, template: dict[str, Any] | None) -> None:
        if key in placed or key not in prereqs:
            return
        placed.add(key)
        for req in prereqs[key]:
            place(req, None)
        entry = dict(template) if template is not None else {"sid": key[0], "level": key[1]}
        out.append(entry)

    for entry in order:
        if not isinstance(entry, dict) or not isinstance(entry.get("sid"), str):
            continue
        level = entry.get("level", 1)
        place((entry["sid"], int(level) if isinstance(level, int) else 1), entry)
    return out


def build_order_errors(order: list[Any], prereqs: dict[Key, tuple[Req, ...]]) -> list[str]:
    errors: list[str] = []
    seen: set[Key] = set()
    for index, entry in enumerate(order):
        if not isinstance(entry, dict) or not isinstance(entry.get("sid"), str):
            errors.append(f"entry {index} is not a building reference")
            continue
        level = entry.get("level", 1)
        key = (entry["sid"], int(level) if isinstance(level, int) else 1)
        if key not in prereqs:
            errors.append(f"entry {index} {key[0]}@{key[1]} is not a building level of this city")
            continue
        for req in prereqs[key]:
            if req not in seen:
                errors.append(f"entry {index} {key[0]}@{key[1]} comes before its prerequisite {req[0]}@{req[1]}")
        seen.add(key)
    return errors


# --- construction-tree layout ------------------------------------------------------

from validate_city_construction_tree_layout import CLICKABLE_COLUMNS, GRID_ROWS, VANILLA_MAX_COLUMN  # noqa: E402

# The native panel has 10 columns, but column 9 is covered by other build-screen UI and
# no stock OE city uses it. The solver places only on the vanilla clickable columns
# 0..VANILLA_MAX_COLUMN; the layout validator owns the bound.

# Preferred cells for the buildings every HoMM3 city shares (economy columns 0..3,
# Mage Guild column 8). Dwelling and faction-special preferences come from the city's
# own nodePos (donor grid + HOMM3_SPECIAL_BUILDING_NODE_POS_BY_FACTION).
COMMON_PREFERRED_CELLS: dict[Key, tuple[int, int]] = {
    ("Build_Tavern", 1): (0, 0),
    ("Build_Main", 1): (1, 0),
    ("Build_Treasury", 1): (2, 0),
    ("Build_Wall", 1): (3, 0),
    ("Build_Market", 1): (0, 1),
    ("Build_Main", 2): (1, 1),
    ("Build_Wall", 2): (3, 1),
    ("Build_Artifact_Market", 1): (0, 2),
    ("Build_Main", 3): (1, 2),
    ("Build_Bank", 1): (2, 2),
    ("Build_Wall", 3): (3, 2),
    ("Build_Resource_Depot", 1): (0, 3),
    **{(sid, 1): (0, 4) for sid in GRAIL_SIDS},
    ("Build_Magic_Guild", 1): (8, 0),
    ("Build_Magic_Guild", 2): (8, 1),
    ("Build_Magic_Guild", 3): (8, 2),
    ("Build_Magic_Guild", 4): (8, 3),
    ("Build_Magic_Guild", 5): (8, 4),
}


def strict_depth(prereqs: dict[Key, tuple[Req, ...]], nodes: Iterable[Key]) -> int:
    node_set = set(nodes)
    memo: dict[Key, int] = {}

    def depth(key: Key) -> int:
        if key not in memo:
            memo[key] = 1 + max((depth(r) for r in prereqs.get(key, ()) if r in node_set), default=0)
        return memo[key]

    return max((depth(k) for k in node_set), default=0)


def solve_construction_tree_layout(
    prereqs: dict[Key, tuple[Req, ...]],
    preferred: dict[Key, tuple[int, int]],
) -> dict[Key, tuple[int, int]]:
    """Place every building level on the clickable 9x5 part of the native build panel.

    Every prerequisite sits on a strictly higher row (smaller y) than its dependent.
    When the city's chain is deeper than 5 rows, a final upgrade level (one nothing
    else requires) may sit beside the level before it on the same row - the only
    relaxation ``validate_city_construction_tree_layout.py`` accepts. Each level keeps
    its preferred cell when that is legal and otherwise moves the least distance.
    """
    nodes = [key for key in prereqs if key in preferred]
    node_set = set(nodes)
    reqs_of = {key: [r for r in prereqs[key] if r in node_set] for key in nodes}
    dependents: dict[Key, list[Key]] = {key: [] for key in nodes}
    for key, reqs in reqs_of.items():
        for req in reqs:
            dependents[req].append(key)
    over_capacity = strict_depth(prereqs, nodes) > GRID_ROWS

    def relaxable(key: Key) -> bool:
        sid, level = key
        return over_capacity and level > 1 and (sid, level - 1) in node_set and not dependents[key]

    def weight(req: Key, key: Key) -> int:
        return 0 if relaxable(key) and req == (key[0], key[1] - 1) else 1

    height: dict[Key, int] = {}

    def h(key: Key) -> int:
        if key not in height:
            height[key] = max((weight(key, d) + h(d) for d in dependents[key]), default=0)
        return height[key]

    latest = {key: GRID_ROWS - 1 - h(key) for key in nodes}
    for key in nodes:
        if latest[key] < 0:
            raise ValueError(f"{key[0]}@{key[1]}: prerequisite chain does not fit the {GRID_ROWS}-row build grid")

    # Topological order, preferring the reading order of the preferred cells.
    order: list[Key] = []
    indegree = {key: len(reqs_of[key]) for key in nodes}
    ready = sorted((k for k in nodes if indegree[k] == 0), key=lambda k: (preferred[k][1], preferred[k][0], k))
    while ready:
        key = ready.pop(0)
        order.append(key)
        for dep in dependents[key]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
        ready.sort(key=lambda k: (preferred[k][1], preferred[k][0], k))
    if len(order) != len(nodes):
        raise ValueError("prerequisite cycle; cannot lay out construction tree")

    placed: dict[Key, tuple[int, int]] = {}
    occupied: set[tuple[int, int]] = set()
    wanted: dict[tuple[int, int], int] = {}
    for key in nodes:
        wanted[preferred[key]] = wanted.get(preferred[key], 0) + 1

    def last_side_cell_of_pending_upgrade(cell: tuple[int, int], key: Key) -> bool:
        # A placed level on its upgrade's last legal row keeps its last free side cell
        # for that upgrade (the relaxed beside-cell placement).
        x, y = cell
        for bx in (x - 1, x + 1):
            for base_key, base_cell in placed.items():
                if base_cell != (bx, y):
                    continue
                upgrade = (base_key[0], base_key[1] + 1)
                if upgrade == key or upgrade in placed or upgrade not in node_set or not relaxable(upgrade):
                    continue
                if y + 1 <= latest[upgrade]:
                    # The upgrade can still take a cell below its base.
                    continue
                other = (2 * bx - x, y)
                if not (0 <= other[0] < CLICKABLE_COLUMNS) or other in occupied:
                    return True
        return False

    def free_columns(row: int, want: int, own: tuple[int, int], key: Key) -> list[int]:
        cols = [x for x in range(CLICKABLE_COLUMNS) if (x, row) not in occupied]
        # Avoid cells another unplaced level prefers, so an early placement does not
        # push a later level off its preferred cell. A shared economy/Mage Guild cell is
        # avoided first: a special shifted off the Blacksmith cell must not take the
        # Fort's (Dungeon Gymnasium / Inferno Beelzebub's Hand, 2026-10-02).
        return sorted(
            cols,
            key=lambda x: (
                last_side_cell_of_pending_upgrade((x, row), key),
                common_cells.get((x, row), key) != key,
                (x, row) != own and wanted.get((x, row), 0) > 0,
                abs(x - want),
                x,
            ),
        )

    common_cells = {cell: key for key, cell in COMMON_PREFERRED_CELLS.items() if key in node_set}
    for key in order:
        wanted[preferred[key]] -= 1
        px, py = preferred[key]
        base = (key[0], key[1] - 1)
        if key not in COMMON_PREFERRED_CELLS and base in placed:
            # An upgrade level reads best directly under the level it upgrades.
            px, py = placed[base][0], placed[base][1] + 1
        elif common_cells.get((px, py), key) != key:
            # A shared economy/Mage Guild cell belongs to that common building.
            px = px + 1
        lo = max((placed[r][1] + 1 for r in reqs_of[key]), default=0)
        hi = latest[key]
        cell: tuple[int, int] | None = None
        if lo <= hi:
            rows = sorted(range(lo, hi + 1), key=lambda r: (abs(r - py), r))
            for row in rows:
                cols = free_columns(row, px, (px, py), key)
                if cols:
                    cell = (cols[0], row)
                    break
        if cell is None and relaxable(key):
            base = placed[(key[0], key[1] - 1)]
            others_ok = all(placed[r][1] < base[1] for r in reqs_of[key] if r != (key[0], key[1] - 1))
            if others_ok:
                for x in sorted((base[0] - 1, base[0] + 1), key=lambda x: (abs(x - px), x)):
                    if 0 <= x < CLICKABLE_COLUMNS and (x, base[1]) not in occupied:
                        cell = (x, base[1])
                        break
        if cell is None:
            raise ValueError(
                f"{key[0]}@{key[1]}: no legal build-grid cell (rows {lo}..{hi}, "
                f"clickable columns 0..{VANILLA_MAX_COLUMN})"
            )
        placed[key] = cell
        occupied.add(cell)
    return placed


def city_node_positions(city: dict[str, Any]) -> dict[Key, tuple[int, int]]:
    out: dict[Key, tuple[int, int]] = {}
    for section in city.values():
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
                continue
            for index, level in enumerate(row.get("parametersPerLevel") or [], start=1):
                node = level.get("nodePos") if isinstance(level, dict) else None
                if isinstance(node, dict) and "xPos" in node and "yPos" in node:
                    out[(row["sid"], index)] = (int(node["xPos"]), int(node["yPos"]))
    return out


def apply_city_building_tree(city: dict[str, Any], faction: str) -> dict[Key, tuple[Req, ...]]:
    """Write canonical prevBuildings, derived nodePos and consistent buildOrders into ``city``."""
    prereqs = canonical_prereqs(faction, city_level_keys(city))
    current = city_node_positions(city)
    preferred = {key: COMMON_PREFERRED_CELLS.get(key, current.get(key, (4, 0))) for key in prereqs}
    layout = solve_construction_tree_layout(prereqs, preferred)
    for section in city.values():
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
                continue
            for index, level in enumerate(row.get("parametersPerLevel") or [], start=1):
                if not isinstance(level, dict):
                    continue
                key = (row["sid"], index)
                level["prevBuildings"] = [{"sid": sid, "level": lvl} for sid, lvl in prereqs[key]]
                if key in layout:
                    x, y = layout[key]
                    level["nodePos"] = {"xPos": x, "yPos": y}
    for build_order in city.get("buildOrders") or []:
        if isinstance(build_order, dict) and isinstance(build_order.get("order"), list):
            build_order["order"] = normalize_build_order(build_order["order"], prereqs)
    return prereqs
