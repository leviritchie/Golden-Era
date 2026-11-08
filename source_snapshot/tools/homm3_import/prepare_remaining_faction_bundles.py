#!/usr/bin/env python3
"""Prepare HoMM3/HotA unit bundle inputs for the shared HoMM3 import lane.

This updates the lane-B inventory, bundle manifest, and per-unit authoring
presets, then optionally extracts DEF frames and bootstraps Unity lab folders.
It deliberately does not touch Core.zip, runtime import tables, or the release
candidate install.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
INVENTORY = HERE / "units_inventory.json"
MANIFEST = HERE / "homm3_units_manifest.json"
PRESETS = HERE / "presets"
UNIT_LIST = HERE / "remaining_faction_unit_sids.txt"
INVENTORY_SOURCE_KEYS = (
	"comment",
	"battleExtractBasename",
	"mapExtractBasename",
	"battleDefPath",
	"battleLod",
	"battleLodEntry",
	"battleZipPath",
	"battleZipMember",
	"battleJsonZipMember",
	"battleJsonDirPrefix",
	"mapDefPath",
	"mapZipPath",
	"mapZipMember",
	"mapJsonZipMember",
	"mapJsonDirPrefix",
)

HOTA_NEW_GFX = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "newGraphics" / "Content" / "sprites" / "hota"
COVE_ROOT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "sprites" / "hota" / "cove" / "creatures"
COVE_CONFIG_ROOT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "config" / "hota" / "cove" / "creatures"
COVE_SOUND_ROOT_REL = pathlib.PurePosixPath("vcmi/Mods/hota/mods/cove/Content/sounds")
TOA_ZIP_REL = pathlib.PurePosixPath("vcmi/Mods/tears-of-ashan/content.zip")
HOTA_NEUTRAL_CREATURES_ZIP_REL = pathlib.PurePosixPath("vcmi/Mods/hota/mods/neutralCreatures/content.zip")
HOMM3_SND = ROOT / "HoMM 3 Complete" / "Data" / "Heroes3.snd"

STANDARD_SND_PREFIXES: dict[str, str] = {
	"h3_pikeman": "PIKE",
	"h3_halberdier": "HALB",
	"h3_archer": "LCRS",
	"h3_marksman": "HCRS",
	"h3_griffin": "GRIF",
	"h3_royal_griffin": "RGRF",
	"h3_swordsman": "SWRD",
	"h3_crusader": "CRUS",
	"h3_monk": "MONK",
	"h3_zealot": "ZELT",
	"h3_cavalier": "CAVA",
	"h3_champion": "CHMP",
	"h3_angel": "ANGL",
	"h3_archangel": "AAGL",
	"h3_centaur": "CNTR",
	"h3_centaur_captain": "ECNT",
	"h3_dwarf": "DWRF",
	"h3_battle_dwarf": "BDRF",
	"h3_wood_elf": "WELF",
	"h3_grand_elf": "GELF",
	"h3_pegasus": "PEGA",
	"h3_silver_pegasus": "APEG",
	"h3_dendroid_guard": "TREE",
	"h3_dendroid_soldier": "BTRE",
	"h3_unicorn": "UNIC",
	"h3_war_unicorn": "WUNC",
	"h3_green_dragon": "GRDR",
	"h3_gold_dragon": "GODR",
	"h3_gremlin": "AGRM",
	"h3_gremlin_upg": "MGRM",
	"h3_gargoyle": "SGRG",
	"h3_gargoyle_upg": "OGRG",
	"h3_golem": "SGLM",
	"h3_golem_upg": "IGLM",
	"h3_mage": "MAGE",
	"h3_mage_upg": "AMAG",
	"h3_genie": "GENI",
	"h3_genie_upg": "CALF",
	"h3_naga": "NGRD",
	"h3_naga_upg": "NGRD",
	"h3_giant": "GTIT",
	"h3_giant_upg": "LTIT",
	"h3_imp": "IMPP",
	"h3_familiar": "FMLR",
	"h3_gog": "GOGG",
	"h3_magog": "MGOG",
	"h3_hell_hound": "HHND",
	"h3_cerberus": "CERB",
	"h3_demon": "DHDM",
	"h3_horned_demon": "DHDM",
	"h3_pit_fiend": "PFND",
	"h3_pit_lord": "PFOE",
	"h3_efreeti": "EFRT",
	"h3_efreet_sultan": "ESUL",
	"h3_devil": "DEVL",
	"h3_arch_devil": "ADVL",
	"h3_skeleton": "SKEL",
	"h3_skeleton_warrior": "SKLW",
	"h3_walking_dead": "ZOMB",
	"h3_zombie": "ZMBL",
	"h3_wight": "WGHT",
	"h3_wraith": "WRTH",
	"h3_vampire": "VAMP",
	"h3_vampire_lord": "NOSF",
	"h3_lich": "LICH",
	"h3_power_lich": "PLCH",
	"h3_black_knight": "BKNT",
	"h3_dread_knight": "BLRD",
	"h3_bone_dragon": "BODR",
	"h3_ghost_dragon": "GHDR",
	"h3_troglodyte": "TROG",
	"h3_infernal_troglodyte": "ITRG",
	"h3_harpy": "HARP",
	"h3_harpy_hag": "HHAG",
	"h3_beholder": "BHDR",
	"h3_evil_eye": "EVLI",
	"h3_medusa": "MEDU",
	"h3_medusa_queen": "MEDQ",
	"h3_minotaur": "MINO",
	"h3_minotaur_king": "MINK",
	"h3_manticore": "MANT",
	"h3_scorpicore": "SCRP",
	"h3_red_dragon": "RDDR",
	"h3_black_dragon": "BKDR",
	"h3_gnoll": "GNOL",
	"h3_gnoll_marauder": "GNLM",
	"h3_lizardman": "PLIZ",
	"h3_lizard_warrior": "ALIZ",
	"h3_serpent_fly": "DFLY",
	"h3_dragon_fly": "FDFL",
	"h3_basilisk": "BASL",
	"h3_greater_basilisk": "GBAS",
	"h3_gorgon": "CGOR",
	"h3_mighty_gorgon": "BGOR",
	"h3_wyvern": "WYVN",
	"h3_wyvern_monarch": "WYVM",
	"h3_hydra": "HYDR",
	"h3_chaos_hydra": "CHYD",
	"h3_pixie": "PIXI",
	"h3_sprite": "SPRT",
	"h3_air_elemental": "AELM",
	"h3_storm_elemental": "STOR",
	"h3_water_elemental": "WELM",
	"h3_ice_elemental": "ICEL",
	"h3_fire_elemental": "FELM",
	"h3_energy_elemental": "ENER",
	"h3_earth_elemental": "EELM",
	"h3_magma_elemental": "MAGM",
	"h3_psychic_elemental": "PSYC",
	"h3_magic_elemental": "MGEL",
	"h3_firebird": "FIRB",
	"h3_phoenix": "PHOE",
}


@dataclass(frozen=True)
class UnitSpec:
	faction: str
	sid: str
	battle_def: str
	map_def: str
	source: str = "h3sprite"


def u(faction: str, sid: str, battle_def: str, map_def: str) -> UnitSpec:
	return UnitSpec(faction=faction, sid=sid, battle_def=battle_def, map_def=map_def)


def toa(faction: str, sid: str, level: int) -> UnitSpec:
	stem = f"lvl{level}Alt"
	return UnitSpec(faction=faction, sid=sid, battle_def=stem, map_def=stem, source="toa_zip")


UNITS: tuple[UnitSpec, ...] = (
	# Stronghold
	u("stronghold", "h3_goblin", "CGOBLI.def", "AVWgobl0.def"),
	u("stronghold", "h3_hobgoblin", "CHGOBL.def", "AVWgobx0.def"),
	u("stronghold", "h3_wolf_rider", "CBWLFR.def", "AVWwolf0.def"),
	u("stronghold", "h3_wolf_raider", "CUWLFR.def", "AVWwolx0.def"),
	u("stronghold", "h3_orc", "CORC.def", "AVWorc0.def"),
	u("stronghold", "h3_orc_chieftain", "CORCCH.def", "AVWorcx0.def"),
	u("stronghold", "h3_ogre", "COGRE.def", "AVWogre0.def"),
	u("stronghold", "h3_ogre_mage", "COGMAG.def", "AVWogrx0.def"),
	u("stronghold", "h3_roc", "CROC.def", "AVWroc0.def"),
	u("stronghold", "h3_thunderbird", "CTBIRD.def", "AVWrocx0.def"),
	u("stronghold", "h3_cyclops", "CCYCLR.def", "AVWcycl0.def"),
	u("stronghold", "h3_cyclops_king", "CcyclLor.def", "AVWcycx0.def"),
	u("stronghold", "h3_behemoth", "CYBEHE.def", "AVWbhmt0.def"),
	u("stronghold", "h3_ancient_behemoth", "CABEHE.def", "AVWbhmx0.def"),
	# Tower
	u("tower", "h3_gremlin", "CGREMA.def", "AVWgrem0.def"),
	u("tower", "h3_gremlin_upg", "CGREMM.def", "AVWgrex0.def"),
	u("tower", "h3_gargoyle", "CGARGO.def", "AVWgarg0.def"),
	u("tower", "h3_gargoyle_upg", "COGARG.def", "AVWgarx0.def"),
	u("tower", "h3_golem", "CSGOLE.def", "AVWgolx0.def"),
	u("tower", "h3_golem_upg", "CIGOLE.def", "AVWgolm0.def"),
	u("tower", "h3_mage", "CMAGE.def", "AVWmage0.def"),
	u("tower", "h3_mage_upg", "CAMAGE.def", "AVWmagx0.def"),
	u("tower", "h3_genie", "CGENIE.def", "AVWgeni0.def"),
	u("tower", "h3_genie_upg", "CSULTA.def", "AVWgenx0.def"),
	u("tower", "h3_naga", "CNAGA.def", "AVWnaga0.def"),
	u("tower", "h3_naga_upg", "CNAGAG.def", "AVWnagx0.def"),
	u("tower", "h3_giant", "CLTITA.def", "AVWtitx0.def"),
	u("tower", "h3_giant_upg", "CGTITA.def", "AVWtitn0.def"),
	# Castle
	u("castle", "h3_pikeman", "CPKMAN.def", "AvWPike.def"),
	u("castle", "h3_halberdier", "CHALBD.def", "AVWpikx0.def"),
	u("castle", "h3_archer", "CLCBOW.def", "AvWLCrs.def"),
	u("castle", "h3_marksman", "CHCBOW.def", "AvWHCrs.def"),
	u("castle", "h3_griffin", "CGRIFF.def", "AvWGrif.def"),
	u("castle", "h3_royal_griffin", "CRGRIF.def", "AVWgrix0.def"),
	u("castle", "h3_swordsman", "CSWORD.def", "AVWswrd0.def"),
	u("castle", "h3_crusader", "CCRUSD.def", "AVWswrx0.def"),
	u("castle", "h3_monk", "CMONKK.def", "AvWMonk.def"),
	u("castle", "h3_zealot", "CZEALT.def", "AVWmonx0.def"),
	u("castle", "h3_cavalier", "CCAVLR.def", "AVWcvlr0.def"),
	u("castle", "h3_champion", "CCHAMP.def", "AVWcvlx0.def"),
	u("castle", "h3_angel", "CANGEL.def", "AvWAngl.def"),
	u("castle", "h3_archangel", "CRANGL.def", "AvWArch.def"),
	# Rampart
	u("rampart", "h3_centaur", "CCENTR.def", "AVWcent0.def"),
	u("rampart", "h3_centaur_captain", "CECENT.def", "AVWcenx0.def"),
	u("rampart", "h3_dwarf", "CDWARF.def", "AVWdwrf0.def"),
	u("rampart", "h3_battle_dwarf", "CBDWAR.def", "AVWdwrx0.def"),
	u("rampart", "h3_wood_elf", "CELF.def", "avwelfw0.def"),
	u("rampart", "h3_grand_elf", "CGRELF.def", "AVWelfx0.def"),
	u("rampart", "h3_pegasus", "CPEGAS.def", "AVWpega0.def"),
	u("rampart", "h3_silver_pegasus", "CAPEGS.def", "AVWpegx0.def"),
	u("rampart", "h3_dendroid_guard", "CTREE.def", "AVWtree0.def"),
	u("rampart", "h3_dendroid_soldier", "CBTREE.def", "AVWTREX0.def"),
	u("rampart", "h3_unicorn", "CUNICO.def", "AVWunic0.def"),
	u("rampart", "h3_war_unicorn", "CWUNIC.def", "AVWunix0.def"),
	u("rampart", "h3_green_dragon", "CGDRAG.def", "AVWdrag0.def"),
	u("rampart", "h3_gold_dragon", "CDDRAG.def", "AVWdrax0.def"),
	# Inferno
	u("inferno", "h3_imp", "CIMP.def", "AVWimp0.def"),
	u("inferno", "h3_familiar", "CFAMIL.def", "AVWimpx0.def"),
	u("inferno", "h3_gog", "CGOG.def", "avwgog0.def"),
	u("inferno", "h3_magog", "CMAGOG.def", "avwgogx0.def"),
	u("inferno", "h3_hell_hound", "CHHOUN.def", "AVWhoun0.def"),
	u("inferno", "h3_cerberus", "CCERBU.def", "AVWhoux0.def"),
	u("inferno", "h3_demon", "COHDEM.def", "AVWdemn0.def"),
	u("inferno", "h3_horned_demon", "CTHDEM.def", "AVWdemx0.def"),
	u("inferno", "h3_pit_fiend", "CPFIEN.def", "AVWpitf0.def"),
	u("inferno", "h3_pit_lord", "CPFOE.def", "AVWpitx0.def"),
	u("inferno", "h3_efreeti", "CEFREE.def", "AVWefre0.def"),
	u("inferno", "h3_efreet_sultan", "CEFRES.def", "AVWefrx0.def"),
	u("inferno", "h3_devil", "CDEVIL.def", "AVWdevl0.def"),
	u("inferno", "h3_arch_devil", "CADEVL.def", "AVWdevx0.def"),
	# Necropolis
	u("necropolis", "h3_skeleton", "CSKELE.def", "AVWskel0.def"),
	u("necropolis", "h3_skeleton_warrior", "CWSKEL.def", "AVWSKEX0.DEF"),
	u("necropolis", "h3_walking_dead", "CZOMBI.def", "AVWzomb0.def"),
	u("necropolis", "h3_zombie", "CZOMLO.def", "AVWzomx0.def"),
	u("necropolis", "h3_wight", "CWIGHT.def", "AvWWigh.def"),
	u("necropolis", "h3_wraith", "CWRAIT.def", "AVWwigx0.def"),
	u("necropolis", "h3_vampire", "CVAMP.def", "AVWvamp0.def"),
	u("necropolis", "h3_vampire_lord", "CNOSFE.def", "AVWvamx0.def"),
	u("necropolis", "h3_lich", "CLICH.def", "AVWlich0.def"),
	u("necropolis", "h3_power_lich", "CPLICH.def", "avwlicx0.def"),
	u("necropolis", "h3_black_knight", "CBKNIG.def", "AVWbkni0.def"),
	u("necropolis", "h3_dread_knight", "CBLORD.def", "AVWbknx0.def"),
	u("necropolis", "h3_bone_dragon", "CNDRGN.def", "AVWbone0.def"),
	u("necropolis", "h3_ghost_dragon", "CHDRGN.def", "AVWbonx0.def"),
	# Dungeon
	u("dungeon", "h3_troglodyte", "CTROGL.def", "AVWtrog0.def"),
	u("dungeon", "h3_infernal_troglodyte", "CITROG.def", "AvWInfr.def"),
	u("dungeon", "h3_harpy", "CHARPY.def", "AVWharp0.def"),
	u("dungeon", "h3_harpy_hag", "CHARPH.def", "AVWharx0.def"),
	u("dungeon", "h3_beholder", "CBEHOL.def", "AVWbehl0.def"),
	u("dungeon", "h3_evil_eye", "CEVEYE.def", "AVWbehx0.def"),
	u("dungeon", "h3_medusa", "CMEDUS.def", "AvWMeds.def"),
	u("dungeon", "h3_medusa_queen", "CMEDUQ.def", "AVWmedx0.def"),
	u("dungeon", "h3_minotaur", "CMINOT.def", "AvWMino.def"),
	u("dungeon", "h3_minotaur_king", "CMINOK.def", "AVWminx0.def"),
	u("dungeon", "h3_manticore", "CMCORE.def", "AVWmant0.def"),
	u("dungeon", "h3_scorpicore", "CCMCOR.def", "AVWmanx0.def"),
	u("dungeon", "h3_red_dragon", "CRDRGN.def", "AvWRDrg.def"),
	u("dungeon", "h3_black_dragon", "CBDRGN.def", "AVWddrx0.def"),
	# Fortress
	u("fortress", "h3_gnoll", "CGNOLL.def", "AVWgnll0.def"),
	u("fortress", "h3_gnoll_marauder", "CGNOLM.def", "AVWgnlx0.def"),
	u("fortress", "h3_lizardman", "CPLIZA.def", "AvWLizr.def"),
	u("fortress", "h3_lizard_warrior", "CALIZA.def", "AVWlizx0.def"),
	u("fortress", "h3_serpent_fly", "CDRFLY.def", "AvWDfly.def"),
	u("fortress", "h3_dragon_fly", "CDRFIR.def", "AvWDfir.def"),
	u("fortress", "h3_basilisk", "CBASIL.def", "AvWBasl.def"),
	u("fortress", "h3_greater_basilisk", "CGBASI.def", "AvWGBas.def"),
	u("fortress", "h3_gorgon", "CCGORG.def", "AvWGorg.def"),
	u("fortress", "h3_mighty_gorgon", "CBGOG.def", "AVWgorx0.def"),
	u("fortress", "h3_wyvern", "CWYVER.def", "AvWWyvr.def"),
	u("fortress", "h3_wyvern_monarch", "CWYVMN.def", "AVWwyvx0.def"),
	u("fortress", "h3_hydra", "CHYDRA.def", "AvWHydr.def"),
	u("fortress", "h3_chaos_hydra", "CCHYDR.def", "AVWhydx0.def"),
	# Conflux
	u("conflux", "h3_pixie", "CPIXIE.def", "AVWpixie.def"),
	u("conflux", "h3_sprite", "CSPRITE.def", "AVWsprit.def"),
	u("conflux", "h3_air_elemental", "CAELEM.def", "avwelma0.def"),
	u("conflux", "h3_storm_elemental", "CSTORM.def", "avwstorm.def"),
	u("conflux", "h3_water_elemental", "CWELEM.def", "AVWelmw0.def"),
	u("conflux", "h3_ice_elemental", "CICEE.def", "AVWicee.def"),
	u("conflux", "h3_fire_elemental", "CFELEM.def", "AVWelmf0.def"),
	u("conflux", "h3_energy_elemental", "CNRG.def", "avwnrg.def"),
	u("conflux", "h3_earth_elemental", "CEELEM.def", "AVWelme0.def"),
	u("conflux", "h3_magma_elemental", "CSTONE.def", "avwstone.def"),
	u("conflux", "h3_psychic_elemental", "CPSYEL.def", "AVWpsye.def"),
	u("conflux", "h3_magic_elemental", "CMAGEL.def", "AVWmagel.def"),
	u("conflux", "h3_firebird", "CFBIRD.def", "AVWfbird.def"),
	u("conflux", "h3_phoenix", "CPHX.def", "AVWphx.def"),
	# Cove (HotA)
	UnitSpec("cove", "hota_cove_nymph", "CNIMPH.def", "AVWNIMPH.def", "cove"),
	UnitSpec("cove", "hota_cove_oceanid", "COCEANID.def", "AVWOCEAN.def", "cove"),
	UnitSpec("cove", "hota_cove_crew_mate", "CSEADOG.def", "AVWSEADG.def", "cove"),
	UnitSpec("cove", "hota_cove_seaman", "CSWASH.def", "AVWSWASH.def", "cove"),
	UnitSpec("cove", "hota_cove_pirate", "CPIRATE.def", "AVWPIRAT.def", "cove"),
	UnitSpec("cove", "hota_cove_corsair", "CCORSAIR.def", "AVWCORSA.def", "cove"),
	UnitSpec("cove", "hota_cove_sea_dog", "CPR3UP.def", "AVWPR3UP.def", "cove"),
	UnitSpec("cove", "hota_cove_stormbird", "CASSID.def", "AVWASSUP.def", "cove"),
	UnitSpec("cove", "hota_cove_ayssid", "CASSIDUP.def", "AVWASSID.def", "cove"),
	UnitSpec("cove", "hota_cove_sea_witch", "CPRIEST.def", "AVWPRIES.def", "cove"),
	UnitSpec("cove", "hota_cove_sorceress", "CSORCSS.def", "AVWSORCS.def", "cove"),
	UnitSpec("cove", "hota_cove_nix", "CNIX.def", "AVWNIX.def", "cove"),
	UnitSpec("cove", "hota_cove_nix_warrior", "CNIXWARR.def", "AVWNIXUP.def", "cove"),
	UnitSpec("cove", "hota_cove_sea_serpent", "CSERPENT.def", "AVWSERPE.def", "cove"),
	UnitSpec("cove", "hota_cove_haspid", "CHASPID.def", "AVWHASPI.def", "cove"),
	# Neutral HotA creature needed by Cove Tidecaller Summon Fangarms.
	UnitSpec("neutral", "h3_fangarm", "CFANGARM.DEF", "AVWfngrm.def", "hota_neutral_zip"),
# Tears of Ashan alternate upgrades for Tower. Tower keeps game-facing
# *_upg_alt rows, but the source/lab SIDs must remain distinct.
toa("tower", "h3_gremlin_mechanic", 1),
toa("tower", "h3_elemental_gargoyle", 2),
toa("tower", "h3_magnetic_golem", 3),
toa("tower", "h3_battle_mage", 4),
toa("tower", "h3_genie_vizier", 5),
toa("tower", "h3_naga_rani", 6),
toa("tower", "h3_colossus", 7),
# Tears of Ashan alternate upgrades for the remaining documented factions.
	toa("castle", "h3_glaivier", 1),
	toa("castle", "h3_crossbowman", 2),
	toa("castle", "h3_battle_griffin", 3),
	toa("castle", "h3_guardsman", 4),
	toa("castle", "h3_priest", 5),
	toa("castle", "h3_justiciar", 6),
	toa("castle", "h3_seraph", 7),
	toa("inferno", "h3_vermin", 1),
	toa("inferno", "h3_amalek", 2),
	toa("inferno", "h3_fire_hound", 3),
	toa("inferno", "h3_gore_demon", 4),
	toa("inferno", "h3_pit_spawn", 5),
	toa("inferno", "h3_efreet_sufi", 6),
	toa("inferno", "h3_arch_demon", 7),
	toa("necropolis", "h3_skeleton_archer", 1),
	toa("necropolis", "h3_rot_zombie", 2),
	toa("necropolis", "h3_banshee", 3),
	toa("necropolis", "h3_vampire_prince", 4),
	toa("necropolis", "h3_lich_master", 5),
	toa("necropolis", "h3_dreadtaur", 6),
	toa("necropolis", "h3_spectral_dragon", 7),
	toa("dungeon", "h3_chthonian", 1),
	toa("dungeon", "h3_fury", 2),
	toa("dungeon", "h3_fargazer", 3),
	toa("dungeon", "h3_medusa_warrior", 4),
	toa("dungeon", "h3_minotaur_taskmaster", 5),
	toa("dungeon", "h3_chimera", 6),
	toa("dungeon", "h3_shadow_dragon", 7),
	toa("fortress", "h3_gnoll_shaman", 1),
	toa("fortress", "h3_lizard_assassin", 2),
	toa("fortress", "h3_damsel_fly", 3),
	toa("fortress", "h3_basilisk_flamespitter", 4),
	toa("fortress", "h3_corrosive_gorgon", 5),
	toa("fortress", "h3_paokai", 6),
	toa("fortress", "h3_ruinous_hydra", 7),
	toa("rampart", "h3_centaur_ranger", 1),
	toa("rampart", "h3_dwarf_battlerager", 2),
	toa("rampart", "h3_elf_wardancer", 3),
	toa("rampart", "h3_gold_pegasus", 4),
	toa("rampart", "h3_dendroid_shaman", 5),
	toa("rampart", "h3_pristine_unicorn", 6),
	toa("rampart", "h3_diamond_dragon", 7),
	toa("conflux", "h3_faerie", 1),
	toa("conflux", "h3_hurricane_elemental", 2),
	toa("conflux", "h3_frost_elemental", 3),
	toa("conflux", "h3_plasma_elemental", 4),
	toa("conflux", "h3_lava_elemental", 5),
	toa("conflux", "h3_astral_elemental", 6),
	toa("conflux", "h3_sacred_phoenix", 7),
	toa("cove", "hota_cove_nereid", 1),
	toa("cove", "hota_cove_swashbuckler", 2),
	toa("cove", "hota_cove_halcyon", 4),
	toa("cove", "hota_cove_tidecaller", 5),
	toa("cove", "hota_cove_nix_praetorian", 6),
	toa("cove", "hota_cove_abyss_serpent", 7),
)


def rel(path: pathlib.Path) -> str:
	return path.relative_to(ROOT).as_posix()


def load_json(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def loads_jsonc(text: str) -> dict:
	lines = []
	for line in text.splitlines():
		lines.append(re.sub(r"\s*//.*$", "", line))
	return json.loads("\n".join(lines))


def load_jsonc(path: pathlib.Path) -> dict:
	return loads_jsonc(path.read_text(encoding="utf-8-sig"))


def write_json(path: pathlib.Path, data: dict) -> None:
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cove_path(kind: str, filename: str) -> pathlib.Path:
	return COVE_ROOT / kind / filename


def repo_relative_file(path: pathlib.PurePosixPath) -> pathlib.Path:
	candidates = [ROOT / pathlib.Path(path)]
	if ROOT.parent.name.lower() == "worktrees":
		candidates.append(ROOT.parent.parent / pathlib.Path(path))
	for candidate in candidates:
		if candidate.is_file():
			return candidate
	return candidates[0]


def snd_names() -> set[str]:
	if not HOMM3_SND.is_file():
		return set()
	tools_dir = str(HERE.parent)
	if tools_dir not in sys.path:
		sys.path.insert(0, tools_dir)
	from extract_homm3_snd import read_index

	return {name for name, _, _ in read_index(HOMM3_SND)}


def has_creature_snd_prefix(names: set[str], prefix: str) -> bool:
	return all(prefix + suffix in names for suffix in ("MOVE", "ATTK", "WNCE", "KILL"))


def first_object(data: dict) -> dict:
	if len(data) == 1:
		value = next(iter(data.values()))
		if isinstance(value, dict):
			return value
	return data


def sound_prefix_from_names(sound: dict) -> str | None:
	required = [sound.get(key) for key in ("move", "attack", "wince", "killed")]
	if not all(required):
		return None
	stems = [pathlib.PurePosixPath(str(value)).stem.upper() for value in required]
	suffixes = ("MOVE", "ATTK", "WNCE", "KILL")
	prefixes: list[str] = []
	for stem, suffix in zip(stems, suffixes):
		if not stem.endswith(suffix):
			return None
		prefixes.append(stem[: -len(suffix)])
	if len(set(prefixes)) != 1:
		return None
	return prefixes[0]


def toa_config_row(spec: UnitSpec) -> dict:
	toa_zip = repo_relative_file(TOA_ZIP_REL)
	config = f"config/creatures/{spec.faction}/{spec.battle_def}.json"
	with zipfile.ZipFile(toa_zip) as zf:
		return first_object(loads_jsonc(zf.read(config).decode("utf-8-sig")))


def toa_sound_prefix(spec: UnitSpec, names: set[str]) -> str | None:
	row = toa_config_row(spec)
	prefix = sound_prefix_from_names(row.get("sound") or {})
	if prefix and has_creature_snd_prefix(names, prefix):
		return prefix
	return None


def toa_loose_sound_paths(spec: UnitSpec) -> dict[str, str] | None:
	row = toa_config_row(spec)
	sound = row.get("sound") or {}
	paths: dict[str, str] = {}
	for key in ("move", "attack", "wince", "killed"):
		value = sound.get(key)
		if not value:
			return None
		rel_value = pathlib.PurePosixPath(str(value))
		if not rel_value.as_posix().lower().startswith("hota/cove/"):
			return None
		rel_path = COVE_SOUND_ROOT_REL / rel_value
		if not (ROOT / pathlib.Path(rel_path)).is_file():
			return None
		paths[key] = rel_path.as_posix()
	return paths


def cove_sound_paths(spec: UnitSpec) -> dict[str, str] | None:
	battle_key = spec.battle_def.replace("\\", "/").lower()
	for config_path in COVE_CONFIG_ROOT.glob("*.json"):
		row = first_object(load_jsonc(config_path))
		animation = str((row.get("graphics") or {}).get("animation") or "").replace("\\", "/").lower()
		if not animation.endswith("/" + battle_key):
			continue
		sound = row.get("sound") or {}
		paths: dict[str, str] = {}
		for key in ("move", "attack", "wince", "killed"):
			value = sound.get(key)
			if not value:
				return None
			rel_path = COVE_SOUND_ROOT_REL / pathlib.PurePosixPath(str(value))
			if not (ROOT / pathlib.Path(rel_path)).is_file():
				return None
			paths[key] = rel_path.as_posix()
		return paths
	return None


def hota_neutral_config_stem(spec: UnitSpec) -> str:
	if spec.sid.startswith("h3_"):
		return spec.sid[3:]
	return pathlib.Path(spec.map_def).stem.removeprefix("AVW").lower()


def hota_neutral_config_row(spec: UnitSpec) -> dict:
	zip_path = repo_relative_file(HOTA_NEUTRAL_CREATURES_ZIP_REL)
	config = f"config/hotaNeutralCreatures/{hota_neutral_config_stem(spec)}.json"
	with zipfile.ZipFile(zip_path) as zf:
		return first_object(loads_jsonc(zf.read(config).decode("utf-8-sig")))


def hota_neutral_sound_paths(spec: UnitSpec) -> dict[str, str] | None:
	row = hota_neutral_config_row(spec)
	sound = row.get("sound") or {}
	zip_path = repo_relative_file(HOTA_NEUTRAL_CREATURES_ZIP_REL)
	with zipfile.ZipFile(zip_path) as zf:
		names_by_lower = {name.lower(): name for name in zf.namelist()}
	paths: dict[str, str] = {}
	for key in ("move", "attack", "wince", "killed"):
		value = sound.get(key)
		if not value:
			return None
		member = "sounds/" + pathlib.PurePosixPath(str(value)).as_posix()
		member = names_by_lower.get(member.lower(), member)
		paths[key] = f"{HOTA_NEUTRAL_CREATURES_ZIP_REL.as_posix()}!{member}"
	return paths


def sound_metadata(spec: UnitSpec, names: set[str]) -> dict:
	if spec.source == "cove":
		paths = cove_sound_paths(spec)
		return {"soundPaths": paths} if paths else {}
	if spec.source == "hota_neutral_zip":
		paths = hota_neutral_sound_paths(spec)
		return {"soundPaths": paths} if paths else {}
	if spec.source == "toa_zip":
		prefix = toa_sound_prefix(spec, names)
		if prefix and has_creature_snd_prefix(names, prefix):
			return {"sndBattlePrefix": prefix}
		paths = toa_loose_sound_paths(spec)
		return {"soundPaths": paths} if paths else {}
	else:
		prefix = STANDARD_SND_PREFIXES.get(spec.sid)
	if prefix and has_creature_snd_prefix(names, prefix):
		return {"sndBattlePrefix": prefix}
	return {}


def map_path(spec: UnitSpec) -> pathlib.Path:
	if spec.source == "cove":
		return cove_path("adventureMap", spec.map_def)
	return HOTA_NEW_GFX / spec.faction / "adventureMap" / "creatures" / spec.map_def


def battle_def_path(spec: UnitSpec) -> pathlib.Path | None:
	if spec.source == "cove":
		return cove_path("battle", spec.battle_def)
	return None


def toa_member(spec: UnitSpec, surface: str, ext: str) -> str:
	return f"sprites/creatures/{spec.faction}/{surface}/{spec.battle_def}.{ext}"


def hota_neutral_member(spec: UnitSpec, surface: str) -> str:
	return f"sprites/hota/creatures/{surface}/{spec.battle_def if surface == 'battle' else spec.map_def}"


def toa_member_exists(names: set[str], spec: UnitSpec, surface: str, ext: str) -> bool:
	return toa_member(spec, surface, ext) in names


def path_exists_case_insensitive(path: pathlib.Path) -> bool:
	return path.is_file()


def validate_sources() -> None:
	missing: list[str] = []
	toa_zip = repo_relative_file(TOA_ZIP_REL)
	toa_names: set[str] = set()
	if any(spec.source == "toa_zip" for spec in UNITS):
		if not toa_zip.is_file():
			missing.append(str(toa_zip))
		else:
			with zipfile.ZipFile(toa_zip) as zf:
				toa_names = set(zf.namelist())
	hota_neutral_zip = repo_relative_file(HOTA_NEUTRAL_CREATURES_ZIP_REL)
	hota_neutral_names: set[str] = set()
	if any(spec.source == "hota_neutral_zip" for spec in UNITS):
		if not hota_neutral_zip.is_file():
			missing.append(str(hota_neutral_zip))
		else:
			with zipfile.ZipFile(hota_neutral_zip) as zf:
				hota_neutral_names = set(zf.namelist())
	for spec in UNITS:
		if spec.source == "cove":
			battle = battle_def_path(spec)
			if battle is None or not path_exists_case_insensitive(battle):
				missing.append(f"{spec.sid}: {battle}")
		elif spec.source == "hota_neutral_zip":
			config = f"config/hotaNeutralCreatures/{hota_neutral_config_stem(spec)}.json"
			for member in (config, hota_neutral_member(spec, "battle"), hota_neutral_member(spec, "adventureMap")):
				if member not in hota_neutral_names:
					missing.append(f"{spec.sid}: {HOTA_NEUTRAL_CREATURES_ZIP_REL}/{member}")
			continue
		elif spec.source == "toa_zip":
			config = f"config/creatures/{spec.faction}/{spec.battle_def}.json"
			icon = f"sprites/creatures/{spec.faction}/iconsbig/{spec.battle_def}.png"
			for member in (config, icon):
				if member not in toa_names:
					missing.append(f"{spec.sid}: {TOA_ZIP_REL}/{member}")
			for surface in ("battle", "map"):
				if not (
					toa_member_exists(toa_names, spec, surface, "def")
					or toa_member_exists(toa_names, spec, surface, "json")
				):
					missing.append(f"{spec.sid}: {TOA_ZIP_REL}/sprites/creatures/{spec.faction}/{surface}/{spec.battle_def}.def|json")
			continue
		if spec.source != "toa_zip" and not path_exists_case_insensitive(map_path(spec)):
			missing.append(f"{spec.sid}: {map_path(spec)}")
	if missing:
		raise SystemExit("Missing source DEF(s):\n" + "\n".join(missing))


def inventory_row(spec: UnitSpec, names: set[str]) -> dict:
	battle_base = pathlib.Path(spec.battle_def).stem
	map_base = pathlib.Path(spec.map_def).stem
	row = {
		"unitSid": spec.sid,
		"comment": f"{spec.faction.title()} bundle placeholder prepared from {'Tears of Ashan content.zip' if spec.source == 'toa_zip' else 'HotA neutralCreatures content.zip' if spec.source == 'hota_neutral_zip' else 'HotA Cove loose DEFs' if spec.source == 'cove' else 'HoMM3 battle DEF + HotA adventure-map DEF'}.",
		"battleExtractBasename": battle_base,
		"mapExtractBasename": map_base,
	}
	if spec.source == "toa_zip":
		row["mapZipPath"] = str(TOA_ZIP_REL)
		row["battleZipPath"] = str(TOA_ZIP_REL)
		toa_zip = repo_relative_file(TOA_ZIP_REL)
		with zipfile.ZipFile(toa_zip) as zf:
			names = set(zf.namelist())
		for surface in ("battle", "map"):
			if toa_member_exists(names, spec, surface, "def"):
				row[f"{surface}ZipMember"] = toa_member(spec, surface, "def")
			else:
				key = "battle" if surface == "battle" else "map"
				row[f"{key}JsonZipMember"] = toa_member(spec, surface, "json")
				row[f"{key}JsonDirPrefix"] = f"sprites/creatures/{spec.faction}/{surface}/{spec.battle_def}"
	elif spec.source == "cove":
		row["mapDefPath"] = rel(map_path(spec))
		row["battleDefPath"] = rel(battle_def_path(spec))
	elif spec.source == "hota_neutral_zip":
		row["mapZipPath"] = str(HOTA_NEUTRAL_CREATURES_ZIP_REL)
		row["mapZipMember"] = hota_neutral_member(spec, "adventureMap")
		row["battleZipPath"] = str(HOTA_NEUTRAL_CREATURES_ZIP_REL)
		row["battleZipMember"] = hota_neutral_member(spec, "battle")
	else:
		row["mapDefPath"] = rel(map_path(spec))
		row["battleLod"] = "H3sprite.lod"
		row["battleLodEntry"] = spec.battle_def
	row.update(sound_metadata(spec, names))
	return row


def manifest_row(spec: UnitSpec) -> dict:
	if spec.faction in ("stronghold", "tower") or spec.sid.startswith("toa_"):
		bundle_name = f"custom_units_{spec.sid}"
	else:
		bundle_name = f"custom_units_{spec.faction}_{spec.sid}"
	return {
		"unitSid": spec.sid,
		"battlePrefabAsset": f"Assets/CustomUnits/homm3_lab/{spec.sid}/battle.prefab",
		"mapPrefabAsset": f"Assets/CustomUnits/homm3_lab/{spec.sid}/map.prefab",
		"bundleName": bundle_name,
	}


def authoring_json(spec: UnitSpec) -> dict:
	battle_base = pathlib.Path(spec.battle_def).stem
	map_base = pathlib.Path(spec.map_def).stem
	sid = spec.sid
	return {
		"unitSid": sid,
		"framesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_battle/{battle_base}.dir",
		"templateMaterialPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle_billboard_mesh.mat",
		"battlePrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle.prefab",
		"mapPrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/map.prefab",
		"mapFramesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_map/{map_base}.dir",
		"generatedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim",
		"mapGeneratedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard",
		"mapAnimatorControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard/Homm3MapBillboard.controller",
		"referenceControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Reference/StockEsquireBattle.controller",
		"overrideOutputPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.overrideController",
		"legacyFlatControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.controller",
		"mapFlipBookFps": 10.0,
		"flipBookFps": 12.0,
		"deathClipFps": 10.0,
		"battleQuadLocalScaleX": 13.5,
		"battleQuadLocalScaleY": 12.0,
		"battleQuadLocalScaleZ": 1.0,
		"battleQuadLocalPositionX": 0.75,
		"battleQuadLocalPositionY": 2.01,
		"battleQuadLocalPositionExtraY": 0.0,
		"mapQuadLocalScaleX": 16.0,
		"mapQuadLocalScaleY": 16.0,
		"mapQuadLocalScaleZ": 1.0,
		"mapQuadLocalPositionX": 1.45,
		"mapQuadLocalPositionY": 2.45,
		"generatedClipNamesCsv": "",
	}


def update_metadata() -> list[str]:
	validate_sources()
	names = snd_names()
	inv = load_json(INVENTORY)
	manifest = load_json(MANIFEST)
	inv_units = inv.setdefault("units", [])
	manifest_units = manifest.setdefault("units", [])
	inv_by_sid = {row.get("unitSid"): row for row in inv_units}
	manifest_by_sid = {row.get("unitSid"): row for row in manifest_units}

	added: list[str] = []
	for spec in UNITS:
		audio = sound_metadata(spec, names)
		desired_inventory = inventory_row(spec, names)
		if spec.sid not in inv_by_sid:
			inv_units.append(desired_inventory)
			added.append(spec.sid)
		else:
			row = inv_by_sid[spec.sid]
			for key in INVENTORY_SOURCE_KEYS:
				if key in desired_inventory:
					row[key] = desired_inventory[key]
				else:
					row.pop(key, None)
			if audio.get("sndBattlePrefix"):
				row["sndBattlePrefix"] = audio["sndBattlePrefix"]
			if audio.get("soundPaths") and (not row.get("soundPaths") or spec.source == "hota_neutral_zip"):
				row["soundPaths"] = audio["soundPaths"]
		desired_manifest = manifest_row(spec)
		if spec.sid not in manifest_by_sid:
			manifest_units.append(desired_manifest)
		else:
			manifest_by_sid[spec.sid].update(desired_manifest)
		preset_dir = PRESETS / spec.sid
		preset_dir.mkdir(parents=True, exist_ok=True)
		write_json(preset_dir / "authoring.json", authoring_json(spec))

	write_json(INVENTORY, inv)
	write_json(MANIFEST, manifest)
	UNIT_LIST.write_text("\n".join(spec.sid for spec in UNITS) + "\n", encoding="utf-8")
	return added


def run(args: list[str]) -> None:
	print(" ".join(args))
	result = subprocess.run(args, cwd=str(ROOT))
	if result.returncode != 0:
		raise SystemExit(result.returncode)


def extract_and_bootstrap(unity_project: pathlib.Path) -> None:
	project = pathlib.Path(os.path.abspath(unity_project))
	for spec in UNITS:
		run([sys.executable, str(HERE / "extract_creature.py"), "--unit", spec.sid, "--unity-project", str(project)])
		run([sys.executable, str(HERE / "bootstrap_homm3_lab.py"), "--unit", spec.sid, "--unity-project", str(project)])


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--unity-project", type=pathlib.Path, help="Optional Unity project for extract/bootstrap.")
	ap.add_argument("--extract-bootstrap", action="store_true", help="Extract DEFs and bootstrap Unity lab folders for all remaining faction units.")
	args = ap.parse_args()

	added = update_metadata()
	print(f"Prepared metadata for {len(UNITS)} remaining-faction unit bundle(s); newly added inventory rows: {len(added)}.")
	print(f"Unit list: {UNIT_LIST}")
	if args.extract_bootstrap:
		if not args.unity_project:
			raise SystemExit("--extract-bootstrap requires --unity-project")
		extract_and_bootstrap(args.unity_project)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
