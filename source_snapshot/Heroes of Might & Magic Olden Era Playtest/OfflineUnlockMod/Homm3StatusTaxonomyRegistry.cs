using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Generated static status taxonomy seed for no-compromise custom laws.
/// Source: custom_factions/status_taxonomy_contracts.json.
/// This is source-authored classification only; runtime buff/status hooks remain packet-gated.
/// Do not edit by hand; run tools/release_port/generate_status_taxonomy_registry.py.
/// </summary>
internal static class Homm3StatusTaxonomyRegistry
{
	private static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)
	{
		["blade_dancer_debuff"] = new Entry(new[] { "negative", "defense_down" }),
		["dragon_hunter_blood"] = new Entry(new[] { "negative", "wound", "damage_over_time" }),
		["dragon_hunter_buff"] = new Entry(new[] { "positive", "protection", "spell_immunity", "preserve" }),
		["druid_bees"] = new Entry(new[] { "negative", "damage_over_time" }),
		["druid_buff"] = new Entry(new[] { "positive", "protection", "spell_immunity", "preserve" }),
		["druid_debuff"] = new Entry(new[] { "negative", "defense_down" }),
		["flicker_curse"] = new Entry(new[] { "negative", "curse", "damage_over_time" }),
		["frog_debuff"] = new Entry(new[] { "negative", "max_hp_down" }),
		["frog_poison"] = new Entry(new[] { "negative", "poison", "damage_over_time" }),
		["frostworm_rider_debuff"] = new Entry(new[] { "negative", "damage_taken_up" }),
		["graverobber_debuff"] = new Entry(new[] { "negative", "damage_taken_up" }),
		["graverobber_poison"] = new Entry(new[] { "negative", "poison", "damage_over_time" }),
		["healing_water_effect_special"] = new Entry(new[] { "positive", "heal", "preserve" }),
		["healing_water_effect_special_1"] = new Entry(new[] { "positive", "heal", "cleanse", "preserve" }),
		["hive_queen_debuff_parasite"] = new Entry(new[] { "negative", "slow", "movement_restriction", "initiative_down" }),
		["hydra_debuff"] = new Entry(new[] { "negative", "damage_down" }),
		["inquisitor_buff"] = new Entry(new[] { "positive", "morale_up", "luck_up", "preserve" }),
		["inquisitor_selfbuff_1"] = new Entry(new[] { "positive", "defense_up", "speed", "preserve" }),
		["jaw_buff_2"] = new Entry(new[] { "positive", "protection", "damage_reduction", "preserve" }),
		["kitten_horn_buff"] = new Entry(new[] { "positive", "morale_up", "preserve" }),
		["lich_debuff"] = new Entry(new[] { "negative", "anti_heal", "decay" }),
		["lightweaver_buff_1"] = new Entry(new[] { "positive", "attack_up", "defense_up", "speed", "initiative", "preserve" }),
		["magic_arinas_hymn_effect"] = new Entry(new[] { "positive", "speed", "initiative", "preserve" }),
		["magic_avalanche_effect"] = new Entry(new[] { "negative", "initiative_down", "control" }),
		["magic_carapace_effect"] = new Entry(new[] { "positive", "protection", "preserve" }),
		["magic_carapace_effect_description_1"] = new Entry(new[] { "positive", "protection", "preserve" }),
		["magic_carapace_effect_description_1_special"] = new Entry(new[] { "positive", "protection", "preserve", "negative_immunity" }),
		["magic_carapace_effect_description_special"] = new Entry(new[] { "positive", "protection", "preserve", "negative_immunity" }),
		["magic_decimate_effect"] = new Entry(new[] { "negative", "damage_taken_up" }),
		["magic_despair_effect_1"] = new Entry(new[] { "negative", "morale_down", "luck_down", "curse" }),
		["magic_despair_effect_2"] = new Entry(new[] { "negative", "focus_block", "curse" }),
		["magic_despair_effect_3"] = new Entry(new[] { "negative", "curse", "damage_over_time" }),
		["magic_doreaths_tide_ally_effect"] = new Entry(new[] { "positive", "speed", "initiative", "movement_boost", "tide" }),
		["magic_doreaths_tide_enemy_effect"] = new Entry(new[] { "negative", "slow", "movement_restriction", "initiative_down", "tide", "control" }),
		["magic_fatal_decay_effect_description_1"] = new Entry(new[] { "negative", "anti_heal", "decay" }),
		["magic_fatal_decay_effect_description_2"] = new Entry(new[] { "negative", "anti_heal", "decay", "max_hp_down" }),
		["magic_fatal_decay_effect_description_3"] = new Entry(new[] { "negative", "anti_heal", "decay", "max_hp_down" }),
		["magic_favorable_wind_effect"] = new Entry(new[] { "positive", "damage_boost", "ranged_support" }),
		["magic_haste_effect"] = new Entry(new[] { "positive", "speed", "movement_boost" }),
		["magic_holy_arms_effect"] = new Entry(new[] { "positive", "heal", "damage_boost", "preserve" }),
		["magic_ice_bolt_effect"] = new Entry(new[] { "negative", "initiative_down", "control" }),
		["magic_mirror_copy_effect"] = new Entry(new[] { "negative", "temporary_stack", "damage_down", "damage_taken_up" }),
		["magic_nairas_kiss_effect"] = new Entry(new[] { "negative", "mark", "damage_over_time" }),
		["magic_nairas_kiss_effect_description_1"] = new Entry(new[] { "negative", "mark", "damage_over_time", "slow", "movement_restriction", "initiative_down" }),
		["magic_nairas_kiss_effect_description_2"] = new Entry(new[] { "negative", "slow", "movement_restriction", "initiative_down" }),
		["magic_optical_illusion_effect"] = new Entry(new[] { "positive", "protection", "damage_reduction", "preserve" }),
		["magic_primordial_purity_effect"] = new Entry(new[] { "positive", "protection", "spell_immunity", "preserve" }),
		["magic_radiant_armor_effect"] = new Entry(new[] { "positive", "protection", "damage_reduction", "preserve" }),
		["magic_shackles_effect"] = new Entry(new[] { "negative", "counterattack_block", "control" }),
		["magic_sharp_edge_effect"] = new Entry(new[] { "positive", "damage_boost" }),
		["magic_shorten_shadow_effect"] = new Entry(new[] { "negative", "attack_down", "defense_down", "curse" }),
		["magic_silence_effect"] = new Entry(new[] { "negative", "ability_block", "focus_block", "disable", "control" }),
		["magic_sleep_effect"] = new Entry(new[] { "negative", "disable", "skip_turn", "control" }),
		["magic_sleep_effect_description_1"] = new Entry(new[] { "negative", "disable", "skip_turn", "control" }),
		["magic_sleep_ignore_effect"] = new Entry(new[] { "positive", "protection", "sleep_immunity", "preserve" }),
		["magic_thick_hide_effect"] = new Entry(new[] { "positive", "protection", "damage_reduction", "preserve" }),
		["magic_trap_snare_effect"] = new Entry(new[] { "negative", "disable", "skip_turn", "movement_restriction", "control" }),
		["magic_twilight_effect"] = new Entry(new[] { "negative", "ranged_block", "control" }),
		["magic_twilight_effect_description_1"] = new Entry(new[] { "negative", "ranged_block", "damage_down", "control" }),
		["magic_unnatural_calm_effect"] = new Entry(new[] { "negative", "damage_down", "curse" }),
		["magic_unnatural_calm_effect_description_special"] = new Entry(new[] { "negative", "damage_down", "curse" }),
		["magic_vulnerability_effect"] = new Entry(new[] { "negative", "damage_taken_up", "curse" }),
		["magic_vulnerability_effect_description_special"] = new Entry(new[] { "negative", "damage_taken_up", "curse" }),
		["magic_web_effect"] = new Entry(new[] { "negative", "slow", "movement_restriction", "control" }),
		["magic_web_effect_description_special"] = new Entry(new[] { "negative", "slow", "movement_restriction", "control" }),
		["medusa_debuff"] = new Entry(new[] { "negative", "initiative_down" }),
		["medusa_stone"] = new Entry(new[] { "negative", "damage_taken_up", "disable", "skip_turn", "control" }),
		["pet_blood"] = new Entry(new[] { "negative", "wound", "damage_over_time" }),
		["pet_debuff"] = new Entry(new[] { "negative", "defense_down" }),
		["phoenix_ignition"] = new Entry(new[] { "negative", "burn", "damage_over_time" }),
		["qilin_selfbuff"] = new Entry(new[] { "positive", "protection", "damage_reduction", "movement_boost" }),
		["sentinel_buff_2"] = new Entry(new[] { "positive", "protection", "spell_immunity", "negative_immunity", "preserve" }),
		["succubus_debuff_1"] = new Entry(new[] { "negative", "ability_block", "disable", "control" }),
		["succubus_debuff_2"] = new Entry(new[] { "negative", "focus_tax", "control" }),
		["succubus_debuff_3"] = new Entry(new[] { "negative", "focus_block", "control" }),
		["trogl_debuff"] = new Entry(new[] { "negative", "damage_taken_up" }),
		["unfrozen_cultist_curse"] = new Entry(new[] { "negative", "curse", "damage_over_time" }),
		["unfrozen_cultist_debuff_1"] = new Entry(new[] { "negative", "initiative_down" }),
		["unfrozen_cultist_debuff_2"] = new Entry(new[] { "negative", "slow", "movement_restriction" }),
	};

	private static readonly Dictionary<string, string[]> SidsByTag = new(StringComparer.Ordinal)
	{
		["ability_block"] = new[] { "magic_silence_effect", "succubus_debuff_1" },
		["anti_heal"] = new[] { "lich_debuff", "magic_fatal_decay_effect_description_1", "magic_fatal_decay_effect_description_2", "magic_fatal_decay_effect_description_3" },
		["attack_down"] = new[] { "magic_shorten_shadow_effect" },
		["attack_up"] = new[] { "lightweaver_buff_1" },
		["burn"] = new[] { "phoenix_ignition" },
		["cleanse"] = new[] { "healing_water_effect_special_1" },
		["control"] = new[] { "magic_avalanche_effect", "magic_doreaths_tide_enemy_effect", "magic_ice_bolt_effect", "magic_shackles_effect", "magic_silence_effect", "magic_sleep_effect", "magic_sleep_effect_description_1", "magic_trap_snare_effect", "magic_twilight_effect", "magic_twilight_effect_description_1", "magic_web_effect", "magic_web_effect_description_special", "medusa_stone", "succubus_debuff_1", "succubus_debuff_2", "succubus_debuff_3" },
		["counterattack_block"] = new[] { "magic_shackles_effect" },
		["curse"] = new[] { "flicker_curse", "magic_despair_effect_1", "magic_despair_effect_2", "magic_despair_effect_3", "magic_shorten_shadow_effect", "magic_unnatural_calm_effect", "magic_unnatural_calm_effect_description_special", "magic_vulnerability_effect", "magic_vulnerability_effect_description_special", "unfrozen_cultist_curse" },
		["damage_boost"] = new[] { "magic_favorable_wind_effect", "magic_holy_arms_effect", "magic_sharp_edge_effect" },
		["damage_down"] = new[] { "hydra_debuff", "magic_mirror_copy_effect", "magic_twilight_effect_description_1", "magic_unnatural_calm_effect", "magic_unnatural_calm_effect_description_special" },
		["damage_over_time"] = new[] { "dragon_hunter_blood", "druid_bees", "flicker_curse", "frog_poison", "graverobber_poison", "magic_despair_effect_3", "magic_nairas_kiss_effect", "magic_nairas_kiss_effect_description_1", "pet_blood", "phoenix_ignition", "unfrozen_cultist_curse" },
		["damage_reduction"] = new[] { "jaw_buff_2", "magic_optical_illusion_effect", "magic_radiant_armor_effect", "magic_thick_hide_effect", "qilin_selfbuff" },
		["damage_taken_up"] = new[] { "frostworm_rider_debuff", "graverobber_debuff", "magic_decimate_effect", "magic_mirror_copy_effect", "magic_vulnerability_effect", "magic_vulnerability_effect_description_special", "medusa_stone", "trogl_debuff" },
		["decay"] = new[] { "lich_debuff", "magic_fatal_decay_effect_description_1", "magic_fatal_decay_effect_description_2", "magic_fatal_decay_effect_description_3" },
		["defense_down"] = new[] { "blade_dancer_debuff", "druid_debuff", "magic_shorten_shadow_effect", "pet_debuff" },
		["defense_up"] = new[] { "inquisitor_selfbuff_1", "lightweaver_buff_1" },
		["disable"] = new[] { "magic_silence_effect", "magic_sleep_effect", "magic_sleep_effect_description_1", "magic_trap_snare_effect", "medusa_stone", "succubus_debuff_1" },
		["focus_block"] = new[] { "magic_despair_effect_2", "magic_silence_effect", "succubus_debuff_3" },
		["focus_tax"] = new[] { "succubus_debuff_2" },
		["heal"] = new[] { "healing_water_effect_special", "healing_water_effect_special_1", "magic_holy_arms_effect" },
		["initiative"] = new[] { "lightweaver_buff_1", "magic_arinas_hymn_effect", "magic_doreaths_tide_ally_effect" },
		["initiative_down"] = new[] { "hive_queen_debuff_parasite", "magic_avalanche_effect", "magic_doreaths_tide_enemy_effect", "magic_ice_bolt_effect", "magic_nairas_kiss_effect_description_1", "magic_nairas_kiss_effect_description_2", "medusa_debuff", "unfrozen_cultist_debuff_1" },
		["luck_down"] = new[] { "magic_despair_effect_1" },
		["luck_up"] = new[] { "inquisitor_buff" },
		["mark"] = new[] { "magic_nairas_kiss_effect", "magic_nairas_kiss_effect_description_1" },
		["max_hp_down"] = new[] { "frog_debuff", "magic_fatal_decay_effect_description_2", "magic_fatal_decay_effect_description_3" },
		["morale_down"] = new[] { "magic_despair_effect_1" },
		["morale_up"] = new[] { "inquisitor_buff", "kitten_horn_buff" },
		["movement_boost"] = new[] { "magic_doreaths_tide_ally_effect", "magic_haste_effect", "qilin_selfbuff" },
		["movement_restriction"] = new[] { "hive_queen_debuff_parasite", "magic_doreaths_tide_enemy_effect", "magic_nairas_kiss_effect_description_1", "magic_nairas_kiss_effect_description_2", "magic_trap_snare_effect", "magic_web_effect", "magic_web_effect_description_special", "unfrozen_cultist_debuff_2" },
		["negative"] = new[] { "blade_dancer_debuff", "dragon_hunter_blood", "druid_bees", "druid_debuff", "flicker_curse", "frog_debuff", "frog_poison", "frostworm_rider_debuff", "graverobber_debuff", "graverobber_poison", "hive_queen_debuff_parasite", "hydra_debuff", "lich_debuff", "magic_avalanche_effect", "magic_decimate_effect", "magic_despair_effect_1", "magic_despair_effect_2", "magic_despair_effect_3", "magic_doreaths_tide_enemy_effect", "magic_fatal_decay_effect_description_1", "magic_fatal_decay_effect_description_2", "magic_fatal_decay_effect_description_3", "magic_ice_bolt_effect", "magic_mirror_copy_effect", "magic_nairas_kiss_effect", "magic_nairas_kiss_effect_description_1", "magic_nairas_kiss_effect_description_2", "magic_shackles_effect", "magic_shorten_shadow_effect", "magic_silence_effect", "magic_sleep_effect", "magic_sleep_effect_description_1", "magic_trap_snare_effect", "magic_twilight_effect", "magic_twilight_effect_description_1", "magic_unnatural_calm_effect", "magic_unnatural_calm_effect_description_special", "magic_vulnerability_effect", "magic_vulnerability_effect_description_special", "magic_web_effect", "magic_web_effect_description_special", "medusa_debuff", "medusa_stone", "pet_blood", "pet_debuff", "phoenix_ignition", "succubus_debuff_1", "succubus_debuff_2", "succubus_debuff_3", "trogl_debuff", "unfrozen_cultist_curse", "unfrozen_cultist_debuff_1", "unfrozen_cultist_debuff_2" },
		["negative_immunity"] = new[] { "magic_carapace_effect_description_1_special", "magic_carapace_effect_description_special", "sentinel_buff_2" },
		["poison"] = new[] { "frog_poison", "graverobber_poison" },
		["positive"] = new[] { "dragon_hunter_buff", "druid_buff", "healing_water_effect_special", "healing_water_effect_special_1", "inquisitor_buff", "inquisitor_selfbuff_1", "jaw_buff_2", "kitten_horn_buff", "lightweaver_buff_1", "magic_arinas_hymn_effect", "magic_carapace_effect", "magic_carapace_effect_description_1", "magic_carapace_effect_description_1_special", "magic_carapace_effect_description_special", "magic_doreaths_tide_ally_effect", "magic_favorable_wind_effect", "magic_haste_effect", "magic_holy_arms_effect", "magic_optical_illusion_effect", "magic_primordial_purity_effect", "magic_radiant_armor_effect", "magic_sharp_edge_effect", "magic_sleep_ignore_effect", "magic_thick_hide_effect", "qilin_selfbuff", "sentinel_buff_2" },
		["preserve"] = new[] { "dragon_hunter_buff", "druid_buff", "healing_water_effect_special", "healing_water_effect_special_1", "inquisitor_buff", "inquisitor_selfbuff_1", "jaw_buff_2", "kitten_horn_buff", "lightweaver_buff_1", "magic_arinas_hymn_effect", "magic_carapace_effect", "magic_carapace_effect_description_1", "magic_carapace_effect_description_1_special", "magic_carapace_effect_description_special", "magic_holy_arms_effect", "magic_optical_illusion_effect", "magic_primordial_purity_effect", "magic_radiant_armor_effect", "magic_sleep_ignore_effect", "magic_thick_hide_effect", "sentinel_buff_2" },
		["protection"] = new[] { "dragon_hunter_buff", "druid_buff", "jaw_buff_2", "magic_carapace_effect", "magic_carapace_effect_description_1", "magic_carapace_effect_description_1_special", "magic_carapace_effect_description_special", "magic_optical_illusion_effect", "magic_primordial_purity_effect", "magic_radiant_armor_effect", "magic_sleep_ignore_effect", "magic_thick_hide_effect", "qilin_selfbuff", "sentinel_buff_2" },
		["ranged_block"] = new[] { "magic_twilight_effect", "magic_twilight_effect_description_1" },
		["ranged_support"] = new[] { "magic_favorable_wind_effect" },
		["skip_turn"] = new[] { "magic_sleep_effect", "magic_sleep_effect_description_1", "magic_trap_snare_effect", "medusa_stone" },
		["sleep_immunity"] = new[] { "magic_sleep_ignore_effect" },
		["slow"] = new[] { "hive_queen_debuff_parasite", "magic_doreaths_tide_enemy_effect", "magic_nairas_kiss_effect_description_1", "magic_nairas_kiss_effect_description_2", "magic_web_effect", "magic_web_effect_description_special", "unfrozen_cultist_debuff_2" },
		["speed"] = new[] { "inquisitor_selfbuff_1", "lightweaver_buff_1", "magic_arinas_hymn_effect", "magic_doreaths_tide_ally_effect", "magic_haste_effect" },
		["spell_immunity"] = new[] { "dragon_hunter_buff", "druid_buff", "magic_primordial_purity_effect", "sentinel_buff_2" },
		["temporary_stack"] = new[] { "magic_mirror_copy_effect" },
		["tide"] = new[] { "magic_doreaths_tide_ally_effect", "magic_doreaths_tide_enemy_effect" },
		["wound"] = new[] { "dragon_hunter_blood", "pet_blood" },
	};

	internal readonly struct Entry
	{
		internal readonly string[] Tags;

		internal Entry(string[] tags)
		{
			Tags = tags ?? Array.Empty<string>();
		}
	}

	internal static bool TryGet(string statusSid, out Entry entry)
	{
		entry = default;
		return !string.IsNullOrWhiteSpace(statusSid)
		       && Entries.TryGetValue(statusSid, out entry);
	}

	internal static bool HasTag(string statusSid, string tag)
	{
		return !string.IsNullOrWhiteSpace(tag)
		       && TryGet(statusSid, out var entry)
		       && EntryHasTag(entry, tag);
	}

	internal static bool TryGetSidsForTag(string tag, out string[] statusSids)
	{
		statusSids = null;
		return !string.IsNullOrWhiteSpace(tag)
		       && SidsByTag.TryGetValue(tag, out statusSids)
		       && statusSids != null
		       && statusSids.Length > 0;
	}

	internal static bool TryGetSidsForAnyTag(string[] tags, out string[] statusSids)
	{
		statusSids = null;
		if (tags == null || tags.Length == 0)
			return false;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		var result = new List<string>();
		for (var i = 0; i < tags.Length; i++)
		{
			if (!TryGetSidsForTag(tags[i], out var current))
				return false;
			for (var j = 0; j < current.Length; j++)
			{
				if (seen.Add(current[j]))
					result.Add(current[j]);
			}
		}
		statusSids = result.ToArray();
		return statusSids.Length > 0;
	}

	private static bool EntryHasTag(Entry entry, string tag)
	{
		if (string.IsNullOrWhiteSpace(tag) || entry.Tags == null)
			return false;
		for (var i = 0; i < entry.Tags.Length; i++)
		{
			if (string.Equals(entry.Tags[i], tag, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}
