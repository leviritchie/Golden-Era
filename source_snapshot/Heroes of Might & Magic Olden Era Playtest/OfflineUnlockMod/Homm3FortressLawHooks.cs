using System;

namespace OfflineUnlockMod;

/// <summary>
/// Fortress faction laws that change Predator Instinct (law pass 2026-11-21, docs/faction_law_pass_20261121/fortress.md;
/// law pass 2026-11-25, docs/faction_law_pass_20261125/build_fortress.md).
/// Ranks are read once per battle when the side is recorded (<see cref="Homm3FortressPredatorInstinctRuntime"/>).
/// Fail closed: no law, or a read failure, gives rank 0 and the skill's current behaviour.
/// </summary>
internal static class Homm3FortressLawHooks
{
	internal const string FactionSid = "homm3_fortress";
	/// <summary>Beastmaster's Eye: pairing sorted by stack Health (strongest with strongest) instead of shuffled.</summary>
	internal const int BeastmastersEye = 5;
	/// <summary>law pass 2026-11-25: Stalkers (was Scent of Blood): predators gain 1 Speed and 1 Initiative while their prey lives.</summary>
	internal const int Stalkers = 9;
	/// <summary>Fresh Quarry: a predator whose prey died picks a new prey at the next round start.</summary>
	internal const int FreshQuarry = 12;
	/// <summary>Pack Kill: +10%/+20% Damage on another friendly pair's prey.</summary>
	internal const int PackKill = 13;
	/// <summary>law pass 2026-11-25: Pack Discipline, one rank: no off-prey penalty.</summary>
	internal const int PackDiscipline = 32;

	internal static readonly int[] PackKillPercentByLevel = { 0, 10, 20 };

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
