using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Generated static building category registry for no-compromise construction laws.
/// Source: custom_factions/construction_building_category_contracts.json.
/// This is source-authored classification only; runtime construction hooks remain packet-gated.
/// Do not edit by hand; run tools/release_port/generate_construction_building_category_registry.py.
/// </summary>
internal static class Homm3ConstructionBuildingCategoryRegistry
{
	private static readonly Dictionary<Key, Entry> Entries = new()
	{
		[new Key("homm3_conflux", "Build_Mother_Nature")] = new Entry("elemental-building", "conflux.garden_of_life"),
		[new Key("homm3_conflux", "Build_Resource_Depot_level_2")] = new Entry("elemental-building", "conflux.vault_of_ashes"),
		[new Key("homm3_conflux", "Build_Mycelium_Roots")] = new Entry("elemental-building", "conflux.elemental_conflux"),
		[new Key("homm3_cove", "Build_Artifact_Market")] = new Entry("market", "cove.shipyard"),
		[new Key("homm3_cove", "Build_Treasury")] = new Entry("pirate-infrastructure", "cove.gunpowder_warehouse"),
		[new Key("homm3_cove", "Build_Resource_Depot_level_2")] = new Entry("tavern", "cove.pub"),
		[new Key("homm3_fortress", "Build_Treasury")] = new Entry("defensive-support", "fortress.field_infirmary"),
		[new Key("homm3_fortress", "Build_Mother_Nature")] = new Entry("defensive-support", "fortress.glyphs_of_fear"),
		[new Key("homm3_fortress", "Build_Resource_Depot_level_2")] = new Entry("defensive-support", "fortress.captains_quarters"),
		[new Key("homm3_fortress", "Build_Bank")] = new Entry("fortification", "fortress.cage_of_warlords"),
		[new Key("homm3_fortress", "Build_Mycelium_Roots")] = new Entry("fortification", "fortress.hydra_marsh"),
		[new Key("homm3_necropolis", "Build_Skeleton_Converter")] = new Entry("converter", "necropolis.skeleton_converter"),
		[new Key("homm3_necropolis", "Build_Resource_Depot_level_2")] = new Entry("dwelling", "necropolis.unearthed_graves"),
		[new Key("homm3_rampart", "Build_Mycelium_Roots")] = new Entry("matured-dwelling-upgrade", "rampart.dendroid_saplings"),
		[new Key("homm3_stronghold", "Build_Gymnasium")] = new Entry("military", "stronghold.hall_of_valhalla"),
		[new Key("homm3_stronghold", "Build_Lyceum")] = new Entry("military", "stronghold.mess_hall"),
		[new Key("homm3_stronghold", "Build_Bank")] = new Entry("military", "stronghold.freelancers_guild"),
		[new Key("homm3_tower", "Build_Resource_Depot_level_2")] = new Entry("construct", "tower.sculptors_wings"),
		[new Key("homm3_tower", "Build_Training_Range")] = new Entry("construct", "tower.workshop_yard"),
		[new Key("homm3_tower", "Build_Intelligence_Academy")] = new Entry("magical", "tower.library"),
		[new Key("homm3_tower", "Build_Golden_Calf")] = new Entry("magical", "tower.skyship_beacon"),
	};

	internal readonly struct Entry
	{
		internal readonly string Group;
		internal readonly string SourceMechanicId;

		internal Entry(string group, string sourceMechanicId)
		{
			Group = group;
			SourceMechanicId = sourceMechanicId;
		}
	}

	private readonly struct Key : IEquatable<Key>
	{
		private readonly string FactionSid;
		private readonly string BuildingSid;

		internal Key(string factionSid, string buildingSid)
		{
			FactionSid = factionSid ?? string.Empty;
			BuildingSid = buildingSid ?? string.Empty;
		}

		public bool Equals(Key other)
		{
			return string.Equals(FactionSid, other.FactionSid, StringComparison.Ordinal)
			       && string.Equals(BuildingSid, other.BuildingSid, StringComparison.Ordinal);
		}

		public override bool Equals(object obj)
		{
			return obj is Key other && Equals(other);
		}

		public override int GetHashCode()
		{
			unchecked
			{
				return ((FactionSid != null ? StringComparer.Ordinal.GetHashCode(FactionSid) : 0) * 397)
				       ^ (BuildingSid != null ? StringComparer.Ordinal.GetHashCode(BuildingSid) : 0);
			}
		}
	}

	internal static bool TryGet(string factionSid, string buildingSid, out Entry entry)
	{
		entry = default;
		return !string.IsNullOrWhiteSpace(factionSid)
		       && !string.IsNullOrWhiteSpace(buildingSid)
		       && Entries.TryGetValue(new Key(factionSid, buildingSid), out entry);
	}

	internal static bool IsInGroup(string factionSid, string buildingSid, string group)
	{
		return !string.IsNullOrWhiteSpace(group)
		       && TryGet(factionSid, buildingSid, out var entry)
		       && string.Equals(entry.Group, group, StringComparison.Ordinal);
	}
}
