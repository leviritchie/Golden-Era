#!/usr/bin/env python3
"""HotA Factory / Bulwark / neutral creature source table for the HoMM3 import lane.

Source-validated against local VCMI HotA zips under vcmi/Mods/hota/mods/.
Does not claim Unity bundles, Core overlay, or Golden Era runtime presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class HotaZipUnitSpec:
	faction: str
	sid: str
	config_stem: str
	battle_stem: str
	map_stem: str
	source: str
	# Optional explicit config path stem override for neutral camelCase files.
	neutral_config_stem: str | None = None


def u(
	faction: str,
	sid: str,
	config_stem: str,
	battle_stem: str,
	map_stem: str,
	*,
	source: str | None = None,
	neutral_config_stem: str | None = None,
) -> HotaZipUnitSpec:
	return HotaZipUnitSpec(
		faction=faction,
		sid=sid,
		config_stem=config_stem,
		battle_stem=battle_stem,
		map_stem=map_stem,
		source=source or f"hota_{faction}_zip",
		neutral_config_stem=neutral_config_stem,
	)


# Lab SIDs stay distinct from game-facing SIDs (see Cove/ToA pattern).
FACTORY_UNITS: tuple[HotaZipUnitSpec, ...] = (
	u("factory", "hota_factory_halfling", "halfling", "CHalf", "AVWhalf"),
	u("factory", "hota_factory_halfling_grenadier", "halflingGrenadier", "CHALFB", "AVWhbom"),
	u("factory", "hota_factory_mechanic", "hotaMechanic", "CMECHAN", "AVWmech"),
	u("factory", "hota_factory_engineer", "hotaEngineer", "CENGINE", "AVWengn"),
	u("factory", "hota_factory_armadillo", "armadillo", "CARMADL", "AVWalmd"),
	u("factory", "hota_factory_bellwether_armadillo", "bellwetherArmadillo", "CBLWARM", "AVWalmb"),
	u("factory", "hota_factory_automaton", "automaton", "CAUTO2", "AVWauto"),
	u("factory", "hota_factory_sentinel_automaton", "sentinelAutomaton", "CHAUTO2", "AVWauth"),
	u("factory", "hota_factory_sandworm", "sandworm", "CSANDWX", "AVWworm"),
	u("factory", "hota_factory_olgoi_khorkhoi", "olgoiKhorkhoi", "COLGOIX", "AVWolgo"),
	u("factory", "hota_factory_gunslinger", "gunslinger", "CGNSLING", "AVWguns"),
	u("factory", "hota_factory_bounty_hunter", "bountyHunter", "CBOUNTHT", "AVWbhun"),
	u("factory", "hota_factory_couatl", "hotaCouatl", "COUATL", "AVWcoat"),
	u("factory", "hota_factory_crimson_couatl", "crimsonCouatl", "COUATR", "AVWradc"),
	u("factory", "hota_factory_dreadnought", "hotaDreadnought", "CDREAD", "AvWdred"),
	u("factory", "hota_factory_juggernaut", "hotaJuggernaut", "CJUGGER", "AvWjugg"),
	# HotA sandworm larva is a support/summon visual, not a town dwelling recruit.
	u("factory", "hota_factory_sandworm_larva", "sandwormLarva", "CLARVA", "AVWworm"),
)

BULWARK_UNITS: tuple[HotaZipUnitSpec, ...] = (
	u("bulwark", "hota_bulwark_kobold", "kobold", "CKOBOLD", "AVWKOBOL"),
	u("bulwark", "hota_bulwark_kobold_foreman", "koboldForeman", "CFKOBLD", "AVWFKOBL"),
	u("bulwark", "hota_bulwark_mountain_ram", "mountainRam", "CMTRAM", "AVWMTRAM"),
	u("bulwark", "hota_bulwark_argali", "argali", "CARHAR", "AVWARGAL"),
	u("bulwark", "hota_bulwark_snow_elf", "snowElf", "CSELF", "AVWSNELF"),
	u("bulwark", "hota_bulwark_steel_elf", "steelElf", "CSTLF", "AVWSTELF"),
	u("bulwark", "hota_bulwark_yeti", "yeti", "CYETI", "AVWYETI"),
	u("bulwark", "hota_bulwark_yeti_runemaster", "yetiRunemaster", "CMSPIR", "AVWMSPRT"),
	u("bulwark", "hota_bulwark_shaman", "shaman", "CSHAMN", "AVWSHAMN"),
	u("bulwark", "hota_bulwark_great_shaman", "greatShaman", "CGSHMN", "AVWGSHMN"),
	u("bulwark", "hota_bulwark_mammoth", "mammoth", "CMAMMTH", "AVWMAMTH"),
	u("bulwark", "hota_bulwark_war_mammoth", "warMammoth", "CWMMTH", "AVWWMAMT"),
	u("bulwark", "hota_bulwark_jotunn", "jotunn", "CJOTUN", "AVWJOTUN"),
	u("bulwark", "hota_bulwark_jotunn_warlord", "jotunnWarlord", "CWJOTN", "AVWJOTNW"),
)

NEUTRAL_UNITS: tuple[HotaZipUnitSpec, ...] = (
	u(
		"neutral",
		"h3_fangarm",
		"fangarm",
		"CFANGARM",
		"AVWfngrm",
		source="hota_neutral_zip",
		neutral_config_stem="fangarm",
	),
	u(
		"neutral",
		"h3_satyr",
		"satyr",
		"CSATYR",
		"AvWSatyr",
		source="hota_neutral_zip",
		neutral_config_stem="satyr",
	),
	u(
		"neutral",
		"h3_leprechaun",
		"leprechaun",
		"CLEPRCHN",
		"AVWlepr",
		source="hota_neutral_zip",
		neutral_config_stem="leprechaun",
	),
	u(
		"neutral",
		"h3_steel_golem",
		"steelGolem",
		"cstlgole",
		"avwslgl0",
		source="hota_neutral_zip",
		neutral_config_stem="steelGolem",
	),
)

ALL_HOTA_ZIP_UNITS: tuple[HotaZipUnitSpec, ...] = FACTORY_UNITS + BULWARK_UNITS + NEUTRAL_UNITS

# Multi-option alt-upgrade recolor galleries. No option is locked until the user picks.
# Evidence level: design suggestion + generated palette transform only (not HotA/ToA art).
# Each line uses the HotA upgraded battle standing frame as the edit source.
# Options use material-class remaps + pixel accents (not a global hue filter).
ALT_RECOLOR_GALLERIES: tuple[dict[str, object], ...] = (
	{
		"faction": "factory",
		"tier": 1,
		"baseSid": "h3_halfling",
		"upgradeSid": "h3_halfling_grenadier",
		"fromLabSid": "hota_factory_halfling_grenadier",
		"gameAltSid": "h3_halfling_upg_alt",
		"role": "T1 shooter alt — differs from Grenadier by niche (demo/utility vs pure ranged chip).",
		"options": [
			{
				"optionId": "A",
				"name": "Halfling Sapper",
				"role": "Demolition/utility shooter; olive-brass kit.",
				"materials": {
					"cloth": {"hue": 85, "sat": 1.05, "val": 0.92},
					"metal": {"hue": 35, "sat": 1.15, "val": 1.05},
					"glow": {"hue": 25, "sat": 1.2, "val": 1.1},
					"base": {"hue": 40, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Halfling Sharpshooter",
				"role": "Precision marksman; cool steel blues.",
				"materials": {
					"cloth": {"hue": -150, "sat": 0.95, "val": 0.95},
					"metal": {"hue": 200, "sat": 0.7, "val": 1.15},
					"glow": {"hue": 190, "sat": 0.8, "val": 1.1},
					"base": {"hue": -160, "sat": 0.75, "val": 1.05},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Halfling Firebug",
				"role": "Incendiary bombs; hotter reds/oranges.",
				"materials": {
					"cloth": {"hue": -8, "sat": 0.55, "val": 0.72},
					"metal": {"hue": 20, "sat": 1.25, "val": 1.05},
					"glow": {"hue": 15, "sat": 1.35, "val": 1.15},
					"base": {"hue": 0, "sat": 0.7, "val": 0.8},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Halfling Powder Monkey",
				"role": "Ammo-runner support; teal bandanas.",
				"materials": {
					"cloth": {"hue": 155, "sat": 1.1, "val": 0.95},
					"metal": {"hue": 40, "sat": 1.05, "val": 1.0},
					"glow": {"hue": 45, "sat": 1.1, "val": 1.05},
					"base": {"hue": 160, "sat": 0.85, "val": 0.95},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 2,
		"baseSid": "h3_mechanic",
		"upgradeSid": "h3_engineer",
		"fromLabSid": "hota_factory_engineer",
		"gameAltSid": "h3_mechanic_upg_alt",
		"role": "T2 walker alt — repair/control niche vs Engineer combat focus.",
		"options": [
			{
				"optionId": "A",
				"name": "Overseer",
				"role": "Field commander/buffs; cyan steel.",
				"materials": {
					"cloth": {"hue": -160, "sat": 0.85, "val": 1.05},
					"metal": {"hue": 185, "sat": 0.8, "val": 1.15},
					"glow": {"hue": 180, "sat": 1.1, "val": 1.1},
					"base": {"hue": -150, "sat": 0.7, "val": 1.05},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Tinker",
				"role": "Gadget/trap specialist; brass-green.",
				"materials": {
					"cloth": {"hue": 95, "sat": 1.15, "val": 0.95},
					"metal": {"hue": 40, "sat": 1.2, "val": 1.05},
					"glow": {"hue": 50, "sat": 1.1, "val": 1.1},
					"base": {"hue": 90, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Forgehand",
				"role": "Close repair/forge; ember copper.",
				"materials": {
					"cloth": {"hue": 10, "sat": 0.7, "val": 0.75},
					"metal": {"hue": 22, "sat": 1.3, "val": 1.05},
					"glow": {"hue": 18, "sat": 1.4, "val": 1.15},
					"base": {"hue": 5, "sat": 0.8, "val": 0.85},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Railwright",
				"role": "Mobility/siege prep; pale iron.",
				"materials": {
					"cloth": {"hue": -170, "sat": 0.55, "val": 1.1},
					"metal": {"hue": 0, "sat": 0.35, "val": 1.2},
					"glow": {"hue": 45, "sat": 1.2, "val": 1.15},
					"base": {"hue": 0, "sat": 0.4, "val": 1.1},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 3,
		"baseSid": "h3_armadillo",
		"upgradeSid": "h3_bellwether_armadillo",
		"fromLabSid": "hota_factory_bellwether_armadillo",
		"gameAltSid": "h3_armadillo_upg_alt",
		"role": "T3 tank alt — armor flavor vs Bellwether charge identity.",
		"options": [
			{
				"optionId": "A",
				"name": "Plated Armadillo",
				"role": "Heavy armor soak; blue-steel plates.",
				"materials": {
					"cloth": {"hue": 195, "sat": 0.75, "val": 1.0},
					"metal": {"hue": 200, "sat": 0.65, "val": 1.1},
					"glow": {"hue": 45, "sat": 1.0, "val": 1.05},
					"base": {"hue": 190, "sat": 0.6, "val": 1.0},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Spined Armadillo",
				"role": "Reflect/thorns; jade spines.",
				"materials": {
					"cloth": {"hue": 115, "sat": 1.05, "val": 0.9},
					"metal": {"hue": 100, "sat": 0.9, "val": 1.0},
					"glow": {"hue": -10, "sat": 1.2, "val": 1.05},
					"base": {"hue": 110, "sat": 0.85, "val": 0.92},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Ash Armadillo",
				"role": "Scorched desert tank; ashen greys.",
				"materials": {
					"cloth": {"hue": 20, "sat": 0.35, "val": 0.75},
					"metal": {"hue": 15, "sat": 0.45, "val": 0.85},
					"glow": {"hue": 20, "sat": 1.1, "val": 0.95},
					"base": {"hue": 10, "sat": 0.3, "val": 0.8},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Gilded Armadillo",
				"role": "Elite prestige tank; gold accents.",
				"materials": {
					"cloth": {"hue": 35, "sat": 1.15, "val": 1.05},
					"metal": {"hue": 40, "sat": 1.3, "val": 1.15},
					"glow": {"hue": 42, "sat": 1.25, "val": 1.2},
					"base": {"hue": 30, "sat": 0.9, "val": 1.0},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 4,
		"baseSid": "h3_automaton",
		"upgradeSid": "h3_sentinel_automaton",
		"fromLabSid": "hota_factory_sentinel_automaton",
		"gameAltSid": "h3_automaton_upg_alt",
		"role": "T4 construct alt — offense/control vs Sentinel guard posture.",
		"options": [
			{
				"optionId": "A",
				"name": "Assault Automaton",
				"role": "Aggressive melee; ember warpaint.",
				"materials": {
					"cloth": {"hue": -15, "sat": 1.2, "val": 0.9},
					"metal": {"hue": 10, "sat": 0.7, "val": 0.95},
					"glow": {"hue": 18, "sat": 1.3, "val": 1.1},
					"base": {"hue": -5, "sat": 0.9, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Arc Automaton",
				"role": "Shock/disable; electric cyan.",
				"materials": {
					"cloth": {"hue": 175, "sat": 1.05, "val": 1.0},
					"metal": {"hue": 40, "sat": 1.1, "val": 1.05},
					"glow": {"hue": 185, "sat": 1.25, "val": 1.15},
					"base": {"hue": 180, "sat": 0.85, "val": 1.0},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Clockwork Automaton",
				"role": "Tempo/initiative; brass clockwork.",
				"materials": {
					"cloth": {"hue": 35, "sat": 1.1, "val": 0.95},
					"metal": {"hue": 38, "sat": 1.25, "val": 1.1},
					"glow": {"hue": 40, "sat": 1.15, "val": 1.1},
					"base": {"hue": 30, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Null Automaton",
				"role": "Magic resist shell; desaturated iron.",
				"materials": {
					"cloth": {"hue": 0, "sat": 0.25, "val": 0.8},
					"metal": {"hue": 0, "sat": 0.2, "val": 1.1},
					"glow": {"hue": -60, "sat": 1.1, "val": 1.05},
					"base": {"hue": 0, "sat": 0.2, "val": 0.85},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 5,
		"baseSid": "h3_sandworm",
		"upgradeSid": "h3_olgoi_khorkhoi",
		"fromLabSid": "hota_factory_olgoi_khorkhoi",
		"gameAltSid": "h3_sandworm_upg_alt",
		"role": "T5 burrower alt — tunnel control vs Olgoi kill pressure.",
		"options": [
			{
				"optionId": "A",
				"name": "Tunnel Wyrm",
				"role": "Deep-earth ambusher; ochre/purple.",
				"materials": {
					"cloth": {"hue": 35, "sat": 1.1, "val": 0.85},
					"metal": {"hue": -50, "sat": 0.9, "val": 0.95},
					"glow": {"hue": -40, "sat": 1.15, "val": 1.05},
					"base": {"hue": 30, "sat": 0.95, "val": 0.88},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Glassworm",
				"role": "Crystal/desert glass; pale teal.",
				"materials": {
					"cloth": {"hue": 160, "sat": 0.8, "val": 1.15},
					"metal": {"hue": 170, "sat": 0.7, "val": 1.2},
					"glow": {"hue": 175, "sat": 1.05, "val": 1.2},
					"base": {"hue": 165, "sat": 0.65, "val": 1.15},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Bloodworm",
				"role": "Bleed/life-drain; deep crimson.",
				"materials": {
					"cloth": {"hue": -5, "sat": 1.25, "val": 0.85},
					"metal": {"hue": 10, "sat": 0.7, "val": 0.95},
					"glow": {"hue": -8, "sat": 1.35, "val": 1.05},
					"base": {"hue": 0, "sat": 1.05, "val": 0.8},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Saltworm",
				"role": "Desiccate/debuff; bleached salt.",
				"materials": {
					"cloth": {"hue": 40, "sat": 0.25, "val": 1.25},
					"metal": {"hue": 0, "sat": 0.2, "val": 1.2},
					"glow": {"hue": 50, "sat": 0.5, "val": 1.15},
					"base": {"hue": 35, "sat": 0.2, "val": 1.2},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 6,
		"baseSid": "h3_gunslinger",
		"upgradeSid": "h3_bounty_hunter",
		"fromLabSid": "hota_factory_bounty_hunter",
		"gameAltSid": "h3_gunslinger_upg_alt",
		"role": "T6 gunner alt — outlaw niche vs Bounty Hunter mark/execute.",
		"options": [
			{
				"optionId": "A",
				"name": "Desperado",
				"role": "Outlaw dual-gun; teal duster.",
				"materials": {
					"cloth": {"hue": 155, "sat": 1.05, "val": 0.9},
					"metal": {"hue": 35, "sat": 1.1, "val": 1.0},
					"glow": {"hue": -10, "sat": 1.15, "val": 1.05},
					"base": {"hue": 150, "sat": 0.85, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Marshal",
				"role": "Lawman control; cold navy.",
				"materials": {
					"cloth": {"hue": -155, "sat": 0.85, "val": 0.95},
					"metal": {"hue": 0, "sat": 0.3, "val": 1.2},
					"glow": {"hue": 0, "sat": 0.4, "val": 1.15},
					"base": {"hue": -160, "sat": 0.7, "val": 1.0},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Hexgunner",
				"role": "Cursed shots; toxic green.",
				"materials": {
					"cloth": {"hue": 110, "sat": 0.7, "val": 0.85},
					"metal": {"hue": -50, "sat": 0.9, "val": 0.95},
					"glow": {"hue": 105, "sat": 1.3, "val": 1.1},
					"base": {"hue": 100, "sat": 0.6, "val": 0.85},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Silverado",
				"role": "Anti-undead silver rounds; bright silver.",
				"materials": {
					"cloth": {"hue": 0, "sat": 0.25, "val": 1.1},
					"metal": {"hue": 0, "sat": 0.15, "val": 1.25},
					"glow": {"hue": 45, "sat": 0.7, "val": 1.2},
					"base": {"hue": 0, "sat": 0.2, "val": 1.15},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 7,
		"line": "couatl",
		"baseSid": "h3_couatl",
		"upgradeSid": "h3_crimson_couatl",
		"fromLabSid": "hota_factory_crimson_couatl",
		"gameAltSid": "h3_couatl_upg_alt",
		"role": "T7a flyer alt — elemental serpent vs Crimson Couatl heat.",
		"options": [
			{
				"optionId": "A",
				"name": "Azure Couatl",
				"role": "Sky/lightning serpent; azure feathers.",
				"materials": {
					"cloth": {"hue": 175, "sat": 1.05, "val": 1.0},
					"metal": {"hue": 185, "sat": 0.8, "val": 1.1},
					"glow": {"hue": 190, "sat": 1.2, "val": 1.15},
					"base": {"hue": 170, "sat": 0.9, "val": 1.0},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Jade Couatl",
				"role": "Nature/poison; jade scales.",
				"materials": {
					"cloth": {"hue": 105, "sat": 1.15, "val": 0.95},
					"metal": {"hue": 95, "sat": 0.9, "val": 1.0},
					"glow": {"hue": 110, "sat": 1.2, "val": 1.1},
					"base": {"hue": 100, "sat": 1.0, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Solar Couatl",
				"role": "Radiant burst; gold-solar.",
				"materials": {
					"cloth": {"hue": 40, "sat": 1.2, "val": 1.1},
					"metal": {"hue": 42, "sat": 1.25, "val": 1.15},
					"glow": {"hue": 45, "sat": 1.3, "val": 1.2},
					"base": {"hue": 35, "sat": 1.05, "val": 1.05},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Void Couatl",
				"role": "Mind/void; deep violet.",
				"materials": {
					"cloth": {"hue": -70, "sat": 1.0, "val": 0.7},
					"metal": {"hue": -55, "sat": 0.85, "val": 0.9},
					"glow": {"hue": -60, "sat": 1.2, "val": 1.05},
					"base": {"hue": -65, "sat": 0.9, "val": 0.75},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "factory",
		"tier": 7,
		"line": "dreadnought",
		"baseSid": "h3_dreadnought",
		"upgradeSid": "h3_juggernaut",
		"fromLabSid": "hota_factory_juggernaut",
		"gameAltSid": "h3_dreadnought_upg_alt",
		"role": "T7b war-machine alt — armor flavor vs Juggernaut siege punch.",
		"options": [
			{
				"optionId": "A",
				"name": "Ironclad",
				"role": "Bright gunmetal hull; durable ironclad.",
				"materials": {
					"cloth": {"hue": 0, "sat": 0.35, "val": 1.1},
					"metal": {"hue": 0, "sat": 0.25, "val": 1.2},
					"glow": {"hue": 200, "sat": 0.9, "val": 1.1},
					"base": {"hue": 0, "sat": 0.3, "val": 1.1},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Thunderhead",
				"role": "Storm cannon; electric blue.",
				"materials": {
					"cloth": {"hue": 185, "sat": 1.0, "val": 0.95},
					"metal": {"hue": 190, "sat": 0.85, "val": 1.1},
					"glow": {"hue": 195, "sat": 1.25, "val": 1.15},
					"base": {"hue": 180, "sat": 0.85, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Hellboiler",
				"role": "Overheat siege; furnace red.",
				"materials": {
					"cloth": {"hue": -12, "sat": 1.2, "val": 0.85},
					"metal": {"hue": 18, "sat": 1.15, "val": 1.0},
					"glow": {"hue": 15, "sat": 1.35, "val": 1.15},
					"base": {"hue": -8, "sat": 1.0, "val": 0.85},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Scrap Titan",
				"role": "Jury-rigged armor; mossy scrap.",
				"materials": {
					"cloth": {"hue": 85, "sat": 0.9, "val": 0.9},
					"metal": {"hue": 70, "sat": 0.75, "val": 0.95},
					"glow": {"hue": 40, "sat": 1.05, "val": 1.0},
					"base": {"hue": 80, "sat": 0.8, "val": 0.9},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 1,
		"baseSid": "h3_kobold",
		"upgradeSid": "h3_kobold_foreman",
		"fromLabSid": "hota_bulwark_kobold_foreman",
		"gameAltSid": "h3_kobold_upg_alt",
		"role": "T1 swarm alt — sapper/scout niche vs Foreman leadership.",
		"options": [
			{
				"optionId": "A",
				"name": "Kobold Sapper",
				"role": "Tunnel bombs; moss greens.",
				"materials": {
					"cloth": {"hue": 90, "sat": 1.1, "val": 0.92},
					"metal": {"hue": 40, "sat": 1.05, "val": 1.0},
					"glow": {"hue": 30, "sat": 1.2, "val": 1.05},
					"base": {"hue": 85, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Kobold Scout",
				"role": "Vision/speed; icy teal.",
				"materials": {
					"cloth": {"hue": 165, "sat": 0.95, "val": 1.05},
					"metal": {"hue": 180, "sat": 0.7, "val": 1.1},
					"glow": {"hue": 175, "sat": 1.05, "val": 1.1},
					"base": {"hue": 160, "sat": 0.8, "val": 1.05},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Kobold Berserker",
				"role": "Frenzy damage; blood reds.",
				"materials": {
					"cloth": {"hue": -8, "sat": 1.25, "val": 0.9},
					"metal": {"hue": 15, "sat": 0.9, "val": 0.95},
					"glow": {"hue": -5, "sat": 1.3, "val": 1.05},
					"base": {"hue": 0, "sat": 1.05, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Kobold Runebearer",
				"role": "Rune buffs; violet marks.",
				"materials": {
					"cloth": {"hue": -55, "sat": 1.05, "val": 0.95},
					"metal": {"hue": -40, "sat": 0.95, "val": 1.05},
					"glow": {"hue": -50, "sat": 1.2, "val": 1.1},
					"base": {"hue": -50, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 2,
		"baseSid": "h3_mountain_ram",
		"upgradeSid": "h3_argali",
		"fromLabSid": "hota_bulwark_argali",
		"gameAltSid": "h3_mountain_ram_upg_alt",
		"role": "T2 charger alt — climate/armor niche vs Argali charge.",
		"options": [
			{
				"optionId": "A",
				"name": "Frost Ram",
				"role": "Ice charge; frosted fleece.",
				"materials": {
					"cloth": {"hue": 185, "sat": 0.7, "val": 1.15},
					"metal": {"hue": 190, "sat": 0.55, "val": 1.2},
					"glow": {"hue": 195, "sat": 1.0, "val": 1.15},
					"base": {"hue": 180, "sat": 0.55, "val": 1.15},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Ashen Ram",
				"role": "Scorched highland; ash browns.",
				"materials": {
					"cloth": {"hue": 20, "sat": 0.45, "val": 0.78},
					"metal": {"hue": 15, "sat": 0.5, "val": 0.85},
					"glow": {"hue": 18, "sat": 1.05, "val": 0.95},
					"base": {"hue": 15, "sat": 0.4, "val": 0.8},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Thorn Ram",
				"role": "Retaliation spines; thorn green.",
				"materials": {
					"cloth": {"hue": 105, "sat": 1.1, "val": 0.92},
					"metal": {"hue": 95, "sat": 0.9, "val": 1.0},
					"glow": {"hue": -10, "sat": 1.15, "val": 1.05},
					"base": {"hue": 100, "sat": 0.95, "val": 0.92},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Aurora Ram",
				"role": "Magic-tinged charge; aurora violet.",
				"materials": {
					"cloth": {"hue": -65, "sat": 1.1, "val": 1.0},
					"metal": {"hue": 170, "sat": 0.9, "val": 1.1},
					"glow": {"hue": -55, "sat": 1.25, "val": 1.15},
					"base": {"hue": -60, "sat": 0.95, "val": 1.0},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 3,
		"baseSid": "h3_snow_elf",
		"upgradeSid": "h3_steel_elf",
		"fromLabSid": "hota_bulwark_steel_elf",
		"gameAltSid": "h3_snow_elf_upg_alt",
		"role": "T3 shooter alt — elemental arrow niche vs Steel Elf armor.",
		"options": [
			{
				"optionId": "A",
				"name": "Glacier Elf",
				"role": "Frost arrows; pale glacier.",
				"materials": {
					"cloth": {"hue": 185, "sat": 0.65, "val": 1.2},
					"metal": {"hue": 190, "sat": 0.5, "val": 1.25},
					"glow": {"hue": 195, "sat": 1.05, "val": 1.2},
					"base": {"hue": 180, "sat": 0.5, "val": 1.2},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Night Elf",
				"role": "Ambush/dark; deep indigo.",
				"materials": {
					"cloth": {"hue": -90, "sat": 0.95, "val": 0.7},
					"metal": {"hue": -70, "sat": 0.7, "val": 0.9},
					"glow": {"hue": -60, "sat": 1.1, "val": 1.0},
					"base": {"hue": -85, "sat": 0.8, "val": 0.75},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Pine Elf",
				"role": "Forest skirmish; pine greens.",
				"materials": {
					"cloth": {"hue": 100, "sat": 1.1, "val": 0.92},
					"metal": {"hue": 35, "sat": 1.05, "val": 1.0},
					"glow": {"hue": 45, "sat": 1.1, "val": 1.05},
					"base": {"hue": 95, "sat": 0.95, "val": 0.92},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Crystal Elf",
				"role": "Piercing crystal shots; cyan crystal.",
				"materials": {
					"cloth": {"hue": 175, "sat": 1.0, "val": 1.05},
					"metal": {"hue": 180, "sat": 0.85, "val": 1.15},
					"glow": {"hue": 185, "sat": 1.2, "val": 1.2},
					"base": {"hue": 170, "sat": 0.85, "val": 1.05},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 4,
		"baseSid": "h3_yeti",
		"upgradeSid": "h3_yeti_runemaster",
		"fromLabSid": "hota_bulwark_yeti_runemaster",
		"gameAltSid": "h3_yeti_upg_alt",
		"role": "T4 bruiser alt — storm/spirit niche vs Runemaster magic.",
		"options": [
			{
				"optionId": "A",
				"name": "Yeti Stormcaller",
				"role": "Storm spells; violet runes.",
				"materials": {
					"cloth": {"hue": -50, "sat": 1.05, "val": 0.95},
					"metal": {"hue": 185, "sat": 0.9, "val": 1.1},
					"glow": {"hue": -45, "sat": 1.25, "val": 1.15},
					"base": {"hue": -40, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Yeti Packlord",
				"role": "Aura leadership; warm ochre.",
				"materials": {
					"cloth": {"hue": 30, "sat": 1.1, "val": 0.95},
					"metal": {"hue": 35, "sat": 1.15, "val": 1.05},
					"glow": {"hue": 40, "sat": 1.15, "val": 1.1},
					"base": {"hue": 25, "sat": 0.95, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Yeti Glacierkin",
				"role": "Ice tank; pale cyan fur.",
				"materials": {
					"cloth": {"hue": 180, "sat": 0.65, "val": 1.2},
					"metal": {"hue": 190, "sat": 0.55, "val": 1.2},
					"glow": {"hue": 195, "sat": 1.0, "val": 1.15},
					"base": {"hue": 175, "sat": 0.5, "val": 1.2},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Yeti Bloodhowl",
				"role": "Frenzy melee; blood-streaked.",
				"materials": {
					"cloth": {"hue": -5, "sat": 1.25, "val": 0.9},
					"metal": {"hue": 10, "sat": 0.85, "val": 0.95},
					"glow": {"hue": -8, "sat": 1.3, "val": 1.05},
					"base": {"hue": 0, "sat": 1.05, "val": 0.88},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 5,
		"baseSid": "h3_shaman",
		"upgradeSid": "h3_great_shaman",
		"fromLabSid": "hota_bulwark_great_shaman",
		"gameAltSid": "h3_shaman_upg_alt",
		"role": "T5 caster alt — spirit school niche vs Great Shaman hexes.",
		"options": [
			{
				"optionId": "A",
				"name": "Spirit Walker",
				"role": "Spirit ally focus; aurora green.",
				"materials": {
					"cloth": {"hue": 115, "sat": 1.1, "val": 0.95},
					"metal": {"hue": 140, "sat": 0.85, "val": 1.05},
					"glow": {"hue": 125, "sat": 1.2, "val": 1.1},
					"base": {"hue": 110, "sat": 0.95, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Frost Speaker",
				"role": "Cold hexes; ice blue.",
				"materials": {
					"cloth": {"hue": 185, "sat": 0.85, "val": 1.1},
					"metal": {"hue": 190, "sat": 0.7, "val": 1.15},
					"glow": {"hue": 195, "sat": 1.1, "val": 1.15},
					"base": {"hue": 180, "sat": 0.7, "val": 1.1},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Ember Seer",
				"role": "Fire visions; ember red.",
				"materials": {
					"cloth": {"hue": -15, "sat": 1.2, "val": 0.9},
					"metal": {"hue": 25, "sat": 1.15, "val": 1.0},
					"glow": {"hue": 18, "sat": 1.35, "val": 1.15},
					"base": {"hue": -10, "sat": 1.05, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Bone Chanter",
				"role": "Necrotic support; bone white.",
				"materials": {
					"cloth": {"hue": 35, "sat": 0.25, "val": 1.2},
					"metal": {"hue": 0, "sat": 0.2, "val": 1.15},
					"glow": {"hue": -40, "sat": 0.7, "val": 1.05},
					"base": {"hue": 30, "sat": 0.2, "val": 1.15},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 6,
		"baseSid": "h3_mammoth",
		"upgradeSid": "h3_war_mammoth",
		"fromLabSid": "hota_bulwark_war_mammoth",
		"gameAltSid": "h3_mammoth_upg_alt",
		"role": "T6 siege alt — climate armor niche vs War Mammoth smash.",
		"options": [
			{
				"optionId": "A",
				"name": "Tundra Mammoth",
				"role": "Cold resist tank; blue tundra.",
				"materials": {
					"cloth": {"hue": 175, "sat": 0.75, "val": 1.1},
					"metal": {"hue": 185, "sat": 0.65, "val": 1.15},
					"glow": {"hue": 190, "sat": 1.0, "val": 1.1},
					"base": {"hue": 170, "sat": 0.65, "val": 1.1},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Steppe Mammoth",
				"role": "Open-field charge; golden steppe.",
				"materials": {
					"cloth": {"hue": 40, "sat": 1.1, "val": 1.05},
					"metal": {"hue": 38, "sat": 1.2, "val": 1.1},
					"glow": {"hue": 42, "sat": 1.15, "val": 1.15},
					"base": {"hue": 35, "sat": 0.95, "val": 1.0},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Runic Mammoth",
				"role": "Rune-warded; violet runes.",
				"materials": {
					"cloth": {"hue": -55, "sat": 1.05, "val": 0.95},
					"metal": {"hue": -40, "sat": 0.95, "val": 1.05},
					"glow": {"hue": -50, "sat": 1.25, "val": 1.1},
					"base": {"hue": -50, "sat": 0.9, "val": 0.95},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Ash Mammoth",
				"role": "Burned-warpath; ash greys.",
				"materials": {
					"cloth": {"hue": 15, "sat": 0.4, "val": 0.78},
					"metal": {"hue": 10, "sat": 0.45, "val": 0.85},
					"glow": {"hue": 18, "sat": 1.1, "val": 0.95},
					"base": {"hue": 10, "sat": 0.35, "val": 0.8},
				},
				"accents": [],
			},
		],
	},
	{
		"faction": "bulwark",
		"tier": 7,
		"baseSid": "h3_jotunn",
		"upgradeSid": "h3_jotunn_warlord",
		"fromLabSid": "hota_bulwark_jotunn_warlord",
		"gameAltSid": "h3_jotunn_upg_alt",
		"role": "T7 giant alt — elemental lord niche vs Warlord command.",
		"options": [
			{
				"optionId": "A",
				"name": "Jotunn Frostlord",
				"role": "Ice lord; frost-blue armor.",
				"materials": {
					"cloth": {"hue": 180, "sat": 0.85, "val": 1.05},
					"metal": {"hue": 190, "sat": 0.7, "val": 1.15},
					"glow": {"hue": 195, "sat": 1.1, "val": 1.15},
					"base": {"hue": 175, "sat": 0.7, "val": 1.05},
				},
				"accents": [],
			},
			{
				"optionId": "B",
				"name": "Jotunn Stormlord",
				"role": "Thunder lord; storm violet.",
				"materials": {
					"cloth": {"hue": -55, "sat": 1.05, "val": 0.9},
					"metal": {"hue": 185, "sat": 0.95, "val": 1.1},
					"glow": {"hue": 195, "sat": 1.25, "val": 1.15},
					"base": {"hue": -50, "sat": 0.9, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "C",
				"name": "Jotunn Stonebinder",
				"role": "Earth armor; granite brown.",
				"materials": {
					"cloth": {"hue": 30, "sat": 0.55, "val": 0.88},
					"metal": {"hue": 25, "sat": 0.5, "val": 0.95},
					"glow": {"hue": 40, "sat": 0.9, "val": 1.0},
					"base": {"hue": 28, "sat": 0.5, "val": 0.9},
				},
				"accents": [],
			},
			{
				"optionId": "D",
				"name": "Jotunn Bloodthane",
				"role": "Rage giant; blood crimson.",
				"materials": {
					"cloth": {"hue": -8, "sat": 1.25, "val": 0.88},
					"metal": {"hue": 15, "sat": 0.9, "val": 0.95},
					"glow": {"hue": -5, "sat": 1.3, "val": 1.05},
					"base": {"hue": 0, "sat": 1.05, "val": 0.88},
				},
				"accents": [],
			},
		],
	},
)


def faction_zip_rel(faction: str) -> PurePosixPath:
	if faction == "neutral":
		return PurePosixPath("vcmi/Mods/hota/mods/neutralCreatures/content.zip")
	return PurePosixPath(f"vcmi/Mods/hota/mods/{faction}/content.zip")


def creature_config_member(spec: HotaZipUnitSpec) -> str:
	if spec.source == "hota_neutral_zip":
		stem = spec.neutral_config_stem or spec.config_stem
		return f"config/hotaNeutralCreatures/{stem}.json"
	return f"config/hota/{spec.faction}/creatures/{spec.config_stem}.json"


def sprites_prefix(spec: HotaZipUnitSpec, surface: str) -> str:
	if spec.source == "hota_neutral_zip":
		return f"sprites/hota/creatures/{surface}/"
	return f"sprites/hota/{spec.faction}/creatures/{surface}/"
