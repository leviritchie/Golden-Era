using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Generated static spell taxonomy seed for no-compromise custom laws.
/// Source: custom_factions/spell_taxonomy_contracts.json.
/// This is source-authored classification only; runtime spell/cooldown/status hooks remain packet-gated.
/// Do not edit by hand; run tools/release_port/generate_spell_taxonomy_registry.py.
/// </summary>
internal static class Homm3SpellTaxonomyRegistry
{
	private static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)
	{
		["day_12_magic_radiant_armor"] = new Entry("day", new[] { "daylight", "support", "blessing", "protection", "defense" }),
		["day_13_magic_holy_arms"] = new Entry("day", new[] { "daylight", "support", "blessing", "heal", "damage" }),
		["day_1_magic_healing_water"] = new Entry("day", new[] { "daylight", "support", "heal" }),
		["day_1_magic_healing_water_special"] = new Entry("day", new[] { "daylight", "support", "heal", "cleanse" }),
		["day_2_magic_sharp_edge"] = new Entry("day", new[] { "daylight", "support", "blessing", "damage" }),
		["day_3_magic_haste"] = new Entry("day", new[] { "daylight", "support", "blessing", "movement" }),
		["day_4_magic_favorable_wind"] = new Entry("day", new[] { "daylight", "support", "blessing", "damage" }),
		["day_7_magic_inner_light"] = new Entry("day", new[] { "daylight", "support", "cleanse" }),
		["day_9_magic_arinas_hymn"] = new Entry("day", new[] { "daylight", "support", "blessing", "initiative" }),
		["neutral_magic_dimension_door"] = new Entry("neutral", new[] { "movement" }),
		["neutral_magic_light_gate"] = new Entry("neutral", new[] { "movement" }),
		["neutral_magic_town_portal"] = new Entry("neutral", new[] { "movement" }),
		["night_10_magic_silence"] = new Entry("night", new[] { "night", "curse", "disable", "control" }),
		["night_11_magic_vulnerability"] = new Entry("night", new[] { "night", "curse", "damage" }),
		["night_12_magic_summon_starchild"] = new Entry("night", new[] { "night", "summon" }),
		["night_2_magic_web"] = new Entry("night", new[] { "night", "curse", "slow", "movement", "control" }),
		["night_2_magic_web_special"] = new Entry("night", new[] { "night", "curse", "slow", "movement", "control" }),
		["night_4_magic_despair"] = new Entry("night", new[] { "night", "curse", "damage" }),
		["night_6_magic_deaths_grip"] = new Entry("night", new[] { "night", "curse", "death", "damage" }),
		["night_7_magic_fatal_decay"] = new Entry("night", new[] { "night", "curse", "decay", "anti_heal" }),
		["night_8_magic_sleep"] = new Entry("night", new[] { "night", "curse", "disable", "control" }),
		["primal_10_magic_primordial_purity"] = new Entry("primal", new[] { "primal", "protection", "cleanse" }),
		["primal_12_magic_chain_lightning"] = new Entry("primal", new[] { "primal", "storm", "damage", "area" }),
		["primal_15_magic_summon_primal_remnant"] = new Entry("primal", new[] { "primal", "summon" }),
		["primal_1_magic_thunderbolt"] = new Entry("primal", new[] { "primal", "storm", "damage" }),
		["primal_2_magic_thick_hide"] = new Entry("primal", new[] { "primal", "support", "protection", "defense" }),
		["primal_3_magic_wean"] = new Entry("primal", new[] { "primal", "curse", "cleanse" }),
		["primal_4_magic_fire_globe"] = new Entry("primal", new[] { "primal", "fire", "damage", "area" }),
		["primal_6_magic_ice_bolt"] = new Entry("primal", new[] { "primal", "damage", "slow", "control" }),
		["primal_7_magic_wall_of_flame"] = new Entry("primal", new[] { "primal", "fire", "summon", "area" }),
		["space_11_magic_decimate"] = new Entry("space", new[] { "space", "damage" }),
		["space_12_magic_rewind"] = new Entry("space", new[] { "space", "support", "heal" }),
		["space_14_magic_doreaths_tide"] = new Entry("space", new[] { "space", "support", "movement", "slow", "cleanse", "sea", "tide" }),
		["space_15_magic_trap_snare"] = new Entry("space", new[] { "space", "movement", "disable", "control" }),
		["space_1_magic_early_start"] = new Entry("space", new[] { "space", "support", "movement" }),
		["space_6_magic_blink"] = new Entry("space", new[] { "space", "movement", "support" }),
	};

	internal readonly struct Entry
	{
		internal readonly string School;
		internal readonly string[] Tags;

		internal Entry(string school, string[] tags)
		{
			School = school;
			Tags = tags ?? Array.Empty<string>();
		}
	}

	internal static bool TryGet(string spellSid, out Entry entry)
	{
		entry = default;
		return !string.IsNullOrWhiteSpace(spellSid)
		       && Entries.TryGetValue(spellSid, out entry);
	}

	internal static bool HasTag(string spellSid, string tag)
	{
		return !string.IsNullOrWhiteSpace(tag)
		       && TryGet(spellSid, out var entry)
		       && EntryHasTag(entry, tag);
	}

	internal static bool HasAnyTag(string spellSid, string[] tags)
	{
		if (tags == null || tags.Length == 0)
			return false;
		if (!TryGet(spellSid, out var entry))
			return false;
		for (var i = 0; i < tags.Length; i++)
		{
			if (EntryHasTag(entry, tags[i]))
				return true;
		}
		return false;
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
