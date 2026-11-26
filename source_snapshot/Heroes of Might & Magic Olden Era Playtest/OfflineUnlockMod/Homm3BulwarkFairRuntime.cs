using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22, bulwark.fair (HotA Fair: "trade rates as if the player owned two Marketplaces from this
/// town"; REVIEW 2 decided +1). Each owned Bulwark town with both <c>Build_Market</c> and <c>Build_Mother_Nature</c>
/// built adds +1 to the side's native market count, so that town counts as two Marketplaces. The native price formula
/// reads the count (extraCharge = max(0, 3.5 - 0.5 x count)), so each Fair lowers the extra charge by 0.5 until the floor.
///
/// No patch of its own: <see cref="Homm3FactoryLogisticsRuntime"/>'s GetMarketsCount postfix (the one shared hook on
/// the world side's market count) adds <see cref="ExtraMarkets"/>. The count is read on every market UI refresh, so
/// the town scan is cached per side for 1 s (the reader's city list itself is cached per game day; building levels are
/// read live, so a Fair built today counts within a second).
///
/// Main thread only (the postfix runs on the native caller's thread, which is the main thread for UI/trade reads).
/// Fails closed: any read error adds nothing. Proof tier: source only (not compiled, not run).
/// </summary>
internal static class Homm3BulwarkFairRuntime
{
	internal const string FairSid = "Build_Mother_Nature";
	internal const string MarketSid = "Build_Market";
	internal const string BulwarkCitySid = "homm3_bulwark_city";
	private const int CacheMs = 1000;

	private static readonly Dictionary<int, (int tick, int fairs)> _cache = new();
	private static int _lastLoggedSide = -1, _lastLoggedFairs = -1;

	/// <summary>Extra markets for <paramref name="sideIndex"/>: one per owned Bulwark town with Market + Fair built.</summary>
	internal static int ExtraMarkets(int sideIndex)
	{
		if (sideIndex < 0)
			return 0;
		try
		{
			var now = Environment.TickCount;
			if (_cache.TryGetValue(sideIndex, out var cached) && unchecked(now - cached.tick) <= CacheMs)
				return cached.fairs;
			var fairs = 0;
			foreach (var city in Homm3TownBuildingReader.SideCities(sideIndex))
			{
				if (!Homm3TownBuildingReader.CityMatchesSid(city, BulwarkCitySid))
					continue;
				if (Homm3TownBuildingReader.CityHasBuilding(city, FairSid) && Homm3TownBuildingReader.CityHasBuilding(city, MarketSid))
					fairs++;
			}
			_cache[sideIndex] = (now, fairs);
			if (fairs != _lastLoggedFairs || sideIndex != _lastLoggedSide)
			{
				_lastLoggedSide = sideIndex;
				_lastLoggedFairs = fairs;
				if (fairs > 0)
					Homm3FactoryLogisticsRuntime.LogEvent("bulwark fair: side " + sideIndex + " owns " + fairs + " Fair town(s); market count +" + fairs + ".");
			}
			return fairs;
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogOncePerDay("bulwark-fair", "bulwark fair count failed closed: " + ex.GetBaseException().Message);
			return 0;
		}
	}
}
