using System;

namespace OfflineUnlockMod;

/// <summary>
/// Rampart faction laws that change Avenger (law pass 2026-11-21, docs/faction_law_pass_20261121/rampart.md;
/// law pass 2026-11-25, docs/faction_law_pass_20261125/build_rampart.md).
/// Ranks are read once per battle when the side is armed (<see cref="Homm3RampartAvengerStrikeRuntime"/>).
/// Fail closed: no law, or a read failure, gives rank 0 and the skill's current behaviour.
/// </summary>
internal static class Homm3RampartLawHooks
{
	internal const string FactionSid = "homm3_rampart";
	/// <summary>Wardens' Oath: avenging strikes deal +10%/+20% Damage.</summary>
	internal const int WardensOath = 5;
	/// <summary>law pass 2026-11-25: Thorned Vengeance (was Paths of the Glade): enemy stacks hit by an avenging strike
	/// lose 2/4 Initiative until the end of the round (law buff h3_law_rampart_thorned_1/_2).</summary>
	internal const int ThornedVengeance = 9;
	/// <summary>law pass 2026-11-25: Mighty Oaks: a stack that makes an avenging strike takes -20% Damage until the end
	/// of the round (law buff h3_law_rampart_oaks_1).</summary>
	internal const int MightyOaks = 11;
	/// <summary>Elder's Ward: an enemy attack that is avenged deals -10%/-20% Damage.</summary>
	internal const int EldersWard = 13;
	/// <summary>law pass 2026-11-25: Call of the Grove: avenging strikes heal the striking stack for 30% of the Damage
	/// they deal, restoring fallen creatures up to the starting stack size.</summary>
	internal const int CallOfTheGrove = 30;

	internal static readonly int[] OathPercentByLevel = { 0, 10, 20 };
	internal static readonly int[] WardPercentByLevel = { 0, 10, 20 };
	/// <summary>Thorned Vengeance buff level by law level (the buff rows carry -2/-4 Initiative).</summary>
	internal static readonly int[] ThornedLevelByLevel = { 0, 1, 2 };
	/// <summary>Mighty Oaks buff level by law level (the buff row carries -20% Damage taken).</summary>
	internal static readonly int[] OaksLevelByLevel = { 0, 1 };
	/// <summary>Call of the Grove heal percent by law level. Must match the law's display carrier.</summary>
	internal static readonly int[] GrovePercentByLevel = { 0, 30 };
	internal const string ThornedBuffPrefix = "h3_law_rampart_thorned_";
	internal const string OaksBuffPrefix = "h3_law_rampart_oaks_";

	/// <summary>Law level (0 = not taken) for the battle side's owner; tries each owner object in turn.</summary>
	internal static int Rank(int lawIndex, params object[] owners)
	{
		if (owners == null)
			return 0;
		foreach (var owner in owners)
		{
			if (owner == null)
				continue;
			try
			{
				var rank = Homm3CustomFactionLawRuntime.CustomLawRank(owner, lawIndex, FactionSid);
				if (rank > 0)
					return rank;
			}
			catch
			{
				// fail closed: try the next owner
			}
		}
		return 0;
	}

	internal static int Level(int[] table, int rank) => table == null || rank <= 0 ? 0 : table[Math.Min(rank, table.Length - 1)];
}
