using System;

namespace OfflineUnlockMod;

/// <summary>
/// Dungeon law pass 2026-11-21 / 2026-11-25: the faction laws that act on War Captives. Each helper reads the law rank
/// from the winner's logic hero through <see cref="Homm3CustomFactionLawRuntime.CustomLawRank"/> and fails closed (no
/// law, or an unreadable owner, gives the current War Captives value).
/// </summary>
internal static class Homm3DungeonLawHooks
{
	internal const string FactionSid = "homm3_dungeon";
	// law pass 2026-11-25: Black Market Ransoms (#5) replaces Holding Cells (captive count, a second Dungeon Cells).
	internal const int BlackMarketRansomsLaw = 5;
	// law pass 2026-11-25: Captive Couriers (#7) replaces Ransom Brokers (a second Slave Markets on Ransom/Execute).
	internal const int CaptiveCouriersLaw = 7;
	internal const int TaskmastersLaw = 9;
	internal const int OverlordsDueLaw = 30;

	private static readonly int[] BlackMarketCaptivesPerMercury = { 20, 10 };
	private static readonly double[] CaptiveCouriersMoveShare = { 0.10, 0.20 };
	private static readonly double[] TaskmastersGoldDiscount = { 0.25, 0.50 };
	internal const double OverlordsDueStrength = 0.5;

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

	// law pass 2026-11-25: Black Market Ransoms (#5): Ransom also pays 1 Mercury per 20 / 10 captives.
	internal static int BlackMarketMercury(int level, int captives)
	{
		if (level <= 0 || captives <= 0)
			return 0;
		return captives / BlackMarketCaptivesPerMercury[Math.Min(level, BlackMarketCaptivesPerMercury.Length) - 1];
	}

	// law pass 2026-11-25: Captive Couriers (#7): after the fate, the hero regains 10% / 20% of its daily movement.
	internal static double CaptiveCouriersShare(int level)
	{
		return level <= 0 ? 0.0 : CaptiveCouriersMoveShare[Math.Min(level, CaptiveCouriersMoveShare.Length) - 1];
	}

	// law pass 2026-11-25: Taskmasters (#9): Recruit (from the Recruit Captives subskill) costs 25% / 50% less Gold.
	// It no longer grants Recruit itself (that repeated the subskill).
	internal static int TaskmastersGoldCost(int level, int goldCost)
	{
		if (level <= 0 || goldCost <= 0)
			return goldCost;
		var discount = TaskmastersGoldDiscount[Math.Min(level, TaskmastersGoldDiscount.Length) - 1];
		return Math.Max(0, goldCost - (int)Math.Floor(goldCost * discount));
	}

	// law pass 2026-11-21: Overlord's Due (#30): a second, half-strength fate from Execute, Ransom or Eat.
	internal static bool HasOverlordsDue(object logicHero) => Rank(logicHero, OverlordsDueLaw) > 0;

	internal static int Half(int value)
	{
		return value <= 0 ? 0 : (int)Math.Floor(value * OverlordsDueStrength);
	}
}
