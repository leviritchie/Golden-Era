using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Cove faction laws that change Treasure Hunting (law pass 2026-11-21, docs/faction_law_pass_20261121/cove.md and
/// build_cove.md; law pass 2026-11-25, docs/faction_law_pass_20261125/build_cove.md: Treasure Fever replaces Quick Shovels). Treasure Hunting runs on the map, so every law is read from the owning player's data side by side
/// index. Ranks are cached per side for a short time because the search tick and the marker layer ask often.
/// Fail closed: no law, or a read failure, gives level 0 and the skill's current behaviour.
/// </summary>
internal static class Homm3CoveLawHooks
{
	internal const string FactionSid = "homm3_cove";
	/// <summary>Spyglass Watch: heroes search for map pieces +1/+2 hexes further.</summary>
	internal const int SpyglassWatch = 5;
	/// <summary>Finder's Fee: each map piece a hero collects pays 250/500 Gold.</summary>
	internal const int FindersFee = 9;
	/// <summary>Treasure Fever (law pass 2026-11-25, replaces Quick Shovels): each treasure a hero digs up pays 1000/2000 XP.</summary>
	internal const int TreasureFever = 20;
	/// <summary>King's Ransom: dug treasure holds +20%/+40%/+60% Gold and resources.</summary>
	internal const int KingsRansom = 27;
	/// <summary>Cartographers' Guild: maps show 1/2 fewer possible sites per region.</summary>
	internal const int CartographersGuild = 32;

	internal static readonly int[] FindersFeeGoldByLevel = { 0, 250, 500 };
	internal static readonly int[] KingsRansomPercentByLevel = { 0, 20, 40, 60 };
	/// <summary>Treasure Fever XP per dug treasure; must equal the display carrier in law_overrides/homm3_cove.json #20.</summary>
	internal static readonly int[] TreasureFeverXpByLevel = { 0, 1000, 2000 };

	private const int CacheMs = 1500;
	private static readonly Dictionary<long, (int Tick, int Level)> _cache = new();

	/// <summary>Law level (0 = not taken) for the player at <paramref name="sideIndex"/>.</summary>
	internal static int Level(int sideIndex, int lawIndex)
	{
		if (sideIndex < 0 || sideIndex > 31 || lawIndex <= 0)
			return 0;
		var key = ((long)sideIndex << 32) | (uint)lawIndex;
		var now = Environment.TickCount;
		if (_cache.TryGetValue(key, out var hit) && unchecked(now - hit.Tick) < CacheMs)
			return hit.Level;
		var level = 0;
		try
		{
			if (Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out _) && side != null)
				level = Math.Max(0, Homm3CustomFactionLawRuntime.CustomLawRank(side, lawIndex, FactionSid));
		}
		catch
		{
			level = 0;
		}
		_cache[key] = (now, level);
		return level;
	}

	internal static int Table(int[] table, int level) => table == null || level <= 0 ? 0 : table[Math.Min(level, table.Length - 1)];

	// law pass 2026-11-21: Spyglass Watch (#5)
	internal static int SearchRadius(int sideIndex) => Homm3CoveTreasureRuntime.SearchRadius + Math.Min(2, Level(sideIndex, SpyglassWatch));

	/// <summary>Largest search radius any side can have (the area sweep uses it as an upper bound).</summary>
	internal const int MaxSearchRadius = Homm3CoveTreasureRuntime.SearchRadius + 2;

	// law pass 2026-11-21: Cartographers' Guild (#32)
	internal static int FalseLeadsRemoved(int sideIndex) => Math.Min(2, Level(sideIndex, CartographersGuild));

	// law pass 2026-11-21: Finder's Fee (#9)
	internal static int FindersFeeGold(int sideIndex) => Table(FindersFeeGoldByLevel, Level(sideIndex, FindersFee));

	// law pass 2026-11-21: King's Ransom (#27)
	internal static int KingsRansomPercent(int sideIndex) => Table(KingsRansomPercentByLevel, Level(sideIndex, KingsRansom));

	internal static int ApplyRansom(int amount, int percent) => amount <= 0 || percent <= 0 ? amount : (int)Math.Min(int.MaxValue, (long)amount * (100 + percent) / 100);

	/// <summary>Player-facing line for the dig cost (law pass 2026-11-25: Quick Shovels is gone, so it is the skill's cost).</summary>
	internal static string DigCostText(int sideIndex) => "Digging needs two thirds of a day's movement.";

	// law pass 2026-11-25: Treasure Fever (#20)
	internal static int TreasureFeverXp(int sideIndex) => Table(TreasureFeverXpByLevel, Level(sideIndex, TreasureFever));

	private static MethodInfo _expAdd;
	private static Type _expAddOwner;

	/// <summary>
	/// law pass 2026-11-25: Treasure Fever (#20). Pays the law's XP to the hero that dug a treasure, through the native hero
	/// experience component AddExp(xp, true) (the War Captives Execute and Grotto path: Learning and the native level-up
	/// loop apply). Returns the popup line, or null when the law is not taken or the grant failed (fail closed: no XP).
	/// </summary>
	internal static string GrantTreasureFeverXp(object logicHero, Hex.Session.Data.Hero hero, Action<string> warn)
	{
		try
		{
			if (logicHero == null || hero == null)
				return null;
			var xp = TreasureFeverXp(hero.sideId);
			if (xp <= 0)
				return null;
			var component = Homm3TowerArtificingRuntime.ReadMember(logicHero, GameSymbols.DungeonCaptives.LogicHeroExpComponentMembers);
			if (component == null)
			{
				warn?.Invoke("Treasure Fever: hero " + hero.configSid + " exp component unreadable; " + xp + " XP unpaid.");
				return null;
			}
			var type = component.GetType();
			if (_expAddOwner != type)
			{
				_expAddOwner = type;
				_expAdd = GameMember.FindFirstMethodByNames(type, new[] { typeof(int), typeof(bool) }, GameSymbols.DungeonCaptives.ExpComponentAddExp);
				if (_expAdd != null && _expAdd.ReturnType != typeof(void))
					_expAdd = null;
			}
			if (_expAdd == null)
			{
				warn?.Invoke("Treasure Fever: AddExp unresolved on " + type.Name + " (DungeonCaptives.ExpComponentAddExp); " + xp + " XP unpaid.");
				return null;
			}
			_expAdd.Invoke(component, new object[] { xp, true });
			return "Treasure Fever: " + xp.ToString("N0", CultureInfo.InvariantCulture) + " XP";
		}
		catch (Exception ex)
		{
			warn?.Invoke("Treasure Fever threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
			return null;
		}
	}

	internal static void ClearCache() => _cache.Clear();
}
