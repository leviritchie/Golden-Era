using System;

namespace OfflineUnlockMod;

/// <summary>
/// Tower law pass 2026-11-21 / 2026-11-25: the faction laws that act on Artificing. Each helper reads the law rank from
/// the hero's side through <see cref="Homm3CustomFactionLawRuntime.CustomLawRank"/> and fails closed (no law, or an
/// unreadable owner, gives the current Artificing value).
/// </summary>
internal static class Homm3TowerLawHooks
{
	internal const string FactionSid = "homm3_tower";
	internal const int ScryingLensesLaw = 5;
	internal const int EssenceDistilleryLaw = 7;
	/// <summary>law pass 2026-11-25: Resonant Grafts (was Twin Grafts).</summary>
	internal const int ResonantGraftsLaw = 8;
	internal const int WardedGraftsLaw = 9;
	internal const int GrandSchematicLaw = 28;

	/// <summary>law pass 2026-11-25: Scrying Lenses (#5) Arcane Essence per recorded passive, by law level. Must match the
	/// law's display carrier.</summary>
	internal static readonly int[] ScryingEssenceByLevel = { 0, 10, 20 };
	/// <summary>law pass 2026-11-25: Resonant Grafts (#8) buff rows h3_law_tower_resonant_1/_2 carry 2/4 Attack and
	/// Defense (2 per carried graft, at most MaxSlots grafts). Must match the law's display carrier.</summary>
	internal const string ResonantBuffPrefix = "h3_law_tower_resonant_";
	internal const int ResonantStatPerGraft = 2;
	private const double EssenceDistilleryPerLevel = 0.25;
	private const double GrandSchematicPerLevel = 0.20;
	private const int GraftCostRoundTo = 5;
	private const int GraftCostMinimum = 5;

	internal static int Rank(object logicHero, int lawIndex)
	{
		if (logicHero == null)
			return 0;
		try
		{
			return Math.Max(0, Homm3CustomFactionLawRuntime.CustomLawRank(logicHero, lawIndex, FactionSid));
		}
		catch
		{
			return 0;
		}
	}

	// law pass 2026-11-25: Scrying Lenses (#5): each passive recorded in the Schematic Book also yields 10/20 Arcane
	// Essence. (The old +5/+10 observation-chance points are retired.)
	internal static int ScryingEssence(object logicHero)
	{
		var rank = Rank(logicHero, ScryingLensesLaw);
		return rank <= 0 ? 0 : ScryingEssenceByLevel[Math.Min(rank, ScryingEssenceByLevel.Length - 1)];
	}

	// law pass 2026-11-21: Essence Distillery (#7): essence award x (1 + 0.25 x level), rounded down; the caller keeps the cap.
	internal static long EssenceAward(long essence, object logicHero, out int level)
	{
		level = Rank(logicHero, EssenceDistilleryLaw);
		if (level <= 0 || essence <= 0)
			return essence;
		return (long)Math.Floor(essence * (1.0 + EssenceDistilleryPerLevel * level));
	}

	// law pass 2026-11-25: graft slots follow the skill rank only. The old Twin Grafts lever (second slot at Basic)
	// duplicated Expert Artificing and is retired; the helper stays so every slot read keeps one entry point.
	internal static int SlotsFor(int rank, object logicHero)
	{
		return Homm3TowerArtificingRuntime.SlotsForRank(rank);
	}

	// law pass 2026-11-25: Resonant Grafts (#8): Tower creatures gain 2 Attack and Defense per graft they carry.
	internal static bool HasResonantGrafts(object logicHero)
	{
		return Rank(logicHero, ResonantGraftsLaw) > 0;
	}

	// law pass 2026-11-21: Warded Grafts (#9): grafts purged by enemy effects come back at the next round start.
	internal static bool HasWardedGrafts(object logicHero)
	{
		return Rank(logicHero, WardedGraftsLaw) > 0;
	}

	// law pass 2026-11-21: Grand Schematic (#28): graft cost x (1 - 0.2 x level), rounded to 5, at least 5.
	internal static int GraftCost(int baseCost, object logicHero)
	{
		if (baseCost <= 0 || baseCost == int.MaxValue)
			return baseCost;
		var level = Rank(logicHero, GrandSchematicLaw);
		if (level <= 0)
			return baseCost;
		var scaled = baseCost * Math.Max(0.0, 1.0 - GrandSchematicPerLevel * level);
		var rounded = (int)(Math.Round(scaled / GraftCostRoundTo, MidpointRounding.AwayFromZero) * GraftCostRoundTo);
		return Math.Max(GraftCostMinimum, rounded);
	}
}
