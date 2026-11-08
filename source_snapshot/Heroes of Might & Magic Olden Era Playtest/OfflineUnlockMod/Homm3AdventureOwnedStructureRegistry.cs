using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Generated static custom adventure owned-structure classifier for vision laws.
/// Source: custom_factions/homm3_*.json identity.citySid and coreOverlay.directDwellingPrefix.
/// This proves custom structure SID classification only; runtime owner-side and reveal behavior remain packet-gated.
/// Do not edit by hand; run tools/release_port/generate_adventure_owned_structure_registry.py.
/// </summary>
internal static class Homm3AdventureOwnedStructureRegistry
{
	private static readonly Dictionary<string, Entry> CityEntries = new(StringComparer.Ordinal)
	{
		["homm3_castle_city"] = new Entry("homm3_castle", "city", "homm3_castle_city"),
		["homm3_conflux_city"] = new Entry("homm3_conflux", "city", "homm3_conflux_city"),
		["homm3_cove_city"] = new Entry("homm3_cove", "city", "homm3_cove_city"),
		["homm3_dungeon_city"] = new Entry("homm3_dungeon", "city", "homm3_dungeon_city"),
		["homm3_fortress_city"] = new Entry("homm3_fortress", "city", "homm3_fortress_city"),
		["homm3_inferno_city"] = new Entry("homm3_inferno", "city", "homm3_inferno_city"),
		["homm3_necropolis_city"] = new Entry("homm3_necropolis", "city", "homm3_necropolis_city"),
		["homm3_rampart_city"] = new Entry("homm3_rampart", "city", "homm3_rampart_city"),
		["homm3_stronghold_city"] = new Entry("homm3_stronghold", "city", "homm3_stronghold_city"),
		["homm3_tower_city"] = new Entry("homm3_tower", "city", "homm3_tower_city"),
	};

	private static readonly PrefixEntry[] DwellingPrefixes =
	{
		new PrefixEntry("homm3_castle", "barracks_homm3_castle_"),
		new PrefixEntry("homm3_conflux", "barracks_homm3_conflux_"),
		new PrefixEntry("homm3_cove", "barracks_homm3_cove_"),
		new PrefixEntry("homm3_dungeon", "barracks_homm3_dungeon_"),
		new PrefixEntry("homm3_fortress", "barracks_homm3_fortress_"),
		new PrefixEntry("homm3_inferno", "barracks_homm3_inferno_"),
		new PrefixEntry("homm3_necropolis", "barracks_homm3_necropolis_"),
		new PrefixEntry("homm3_rampart", "barracks_homm3_rampart_"),
		new PrefixEntry("homm3_stronghold", "barracks_homm3_stronghold_"),
		new PrefixEntry("homm3_tower", "barracks_homm3_tower_"),
	};

	internal readonly struct Entry
	{
		internal readonly string FactionSid;
		internal readonly string Kind;
		internal readonly string SourceSidOrPrefix;

		internal Entry(string factionSid, string kind, string sourceSidOrPrefix)
		{
			FactionSid = factionSid;
			Kind = kind;
			SourceSidOrPrefix = sourceSidOrPrefix;
		}
	}

	private readonly struct PrefixEntry
	{
		internal readonly string FactionSid;
		internal readonly string Prefix;

		internal PrefixEntry(string factionSid, string prefix)
		{
			FactionSid = factionSid;
			Prefix = prefix;
		}
	}

	internal static bool TryClassify(string configSid, out Entry entry)
	{
		entry = default;
		if (string.IsNullOrWhiteSpace(configSid))
			return false;
		if (CityEntries.TryGetValue(configSid, out entry))
			return true;
		for (var i = 0; i < DwellingPrefixes.Length; i++)
		{
			var prefix = DwellingPrefixes[i];
			if (configSid.StartsWith(prefix.Prefix, StringComparison.Ordinal))
			{
				entry = new Entry(prefix.FactionSid, "dwelling", prefix.Prefix);
				return true;
			}
		}
		return false;
	}

	internal static bool IsFactionStructure(string factionSid, string configSid)
	{
		return !string.IsNullOrWhiteSpace(factionSid)
		       && TryClassify(configSid, out var entry)
		       && string.Equals(entry.FactionSid, factionSid, StringComparison.Ordinal);
	}
}
