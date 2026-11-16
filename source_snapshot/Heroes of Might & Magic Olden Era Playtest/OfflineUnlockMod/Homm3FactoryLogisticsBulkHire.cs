using System;
using System.Collections.Generic;
using DataHero = Hex.Session.Data.Hero;
using Fx = OfflineUnlockMod.Homm3FactoryLogisticsEffects;

namespace OfflineUnlockMod;

/// <summary>One hireable stock in the "Recruit all" screen: a dwelling's own stock or one Arcane upgraded stock entry.</summary>
internal sealed class LogisticsBulkRow
{
	public long DwellingKey;
	public string DwellingName;
	public string UnitSid;
	public int Tier;
	public bool Upgraded;
	public int Available;
	public IReadOnlyDictionary<string, int> UnitCost;
	internal Func<int, IReadOnlyDictionary<string, int>> PriceOf;
	/// <summary>Delivery targets this dwelling's Rail Network can use ("town"/"hero", key), as the hire paths check them.</summary>
	public HashSet<(string Kind, long Key)> Targets = new();
	/// <summary>Why heroes are not targets here (Rail Network below its hero delivery level), or null.</summary>
	public string HeroNote;
}

internal sealed class LogisticsBulkTarget
{
	public string Kind;
	public long Key;
	public string Name;
}

/// <summary>Which army a delivery to a target lands in (first that can be read), and its free slots now.</summary>
internal sealed class LogisticsDeliveryPreview
{
	public string ArmyLabel;
	public int FreeSlots;
	public int Slots;
	public HashSet<string> Present = new(StringComparer.Ordinal);
	public string Note;
}

// Bulk remote recruitment (UX pass 2026-11-16): lists every owned dwelling with an active Rail Network (its own stock and
// its Arcane upgraded stock) and hires a list of orders by looping the existing single-dwelling hire paths, so each order
// keeps their checks, charge, refund and write-verify semantics. Stops at the first refusal and reports what was hired.
internal static partial class Homm3FactoryLogistics
{
	private static DataHero FindSideHero(Ctx c, int id)
	{
		if (id < 0)
			return null;
		foreach (var h in Fx.SideHeroes(c.World, c.Side))
			if (Fx.HeroId(h) == id)
				return h;
		return null;
	}

	/// <summary>Rows and the union of their delivery targets. One context read per Rail Network dwelling; call once per open.</summary>
	public static bool TryGetBulkHire(out List<LogisticsBulkRow> rows, out List<LogisticsBulkTarget> targets, out string fail)
	{
		var rowList = new List<LogisticsBulkRow>();
		rows = rowList;
		targets = new List<LogisticsBulkTarget>();
		try
		{
			if (!TryLocalSide(out var side, out fail))
				return false;
			if (!Homm3FactoryLogisticsState.TryGet(side, out var state, out var stateFail))
				return Fail("logistics state unreadable (" + stateFail + ")", out fail);
			var seen = new HashSet<(string, long)>();
			foreach (var id in new List<int>(state.Objects.Keys))
			{
				if (!TryContext(id, out var c, out var cFail))
				{
					Homm3FactoryLogisticsRuntime.LogOncePerDay("bulk-" + id, "recruit all skips object " + id + ": " + cFail);
					continue;
				}
				if (!c.IsDwelling || !c.World.Dwellings.TryGetValue(c.ObjectId, out var dwelling))
					continue;
				var e = Fx.ActiveEnhancement(c.Config, c.Obj);
				if (e == null || e.Effect != "rail_network")
					continue;
				var eff = c.Net.EffectiveLevel(e, c.ObjectId, Fx.BuiltActiveLevel(c.Obj));
				var heroesOk = eff >= Math.Max(1, e.HeroDeliveryLevel);
				var reach = c.Net.RailReach.TryGetValue(c.ObjectId, out var r) ? r : null;
				var rowTargets = new HashSet<(string, long)>();
				foreach (var city in c.World.Cities.Values)
				{
					if (city.ownerSide == c.Side && reach != null && reach.Contains(city.idMapObject))
					{
						rowTargets.Add(("town", city.idMapObject));
						if (seen.Add(("town", city.idMapObject)))
							targets.Add(new LogisticsBulkTarget { Kind = "town", Key = city.idMapObject, Name = "Town: " + TownDisplayName(city.cityName) });
					}
				}
				if (heroesOk)
				{
					foreach (var h in Fx.SideHeroes(c.World, c.Side))
					{
						var hid = Fx.HeroId(h);
						if (hid < 0 || reach == null || !reach.Contains(Fx.HeroKeyOffset + hid))
							continue;
						rowTargets.Add(("hero", hid));
						if (seen.Add(("hero", hid)))
							targets.Add(new LogisticsBulkTarget { Kind = "hero", Key = hid, Name = "Hero: " + Homm3HeroDisplayNames.Resolve(h.configSid) });
					}
				}
				var name = Homm3UnitDisplayNames.Resolve(c.UnitSid) + " Dwelling";
				var heroNote = heroesOk ? null : "heroes from Rail Network powered level " + e.HeroDeliveryLevel;
				void AddRow(string sid, bool upgraded)
				{
					if (!TryGetHireInfo(c.ObjectId, sid, upgraded, out var info, out _) || info.Available <= 0)
						return;
					rowList.Add(new LogisticsBulkRow
					{
						DwellingKey = c.ObjectId, DwellingName = name, UnitSid = sid, Tier = c.UnitTier, Upgraded = upgraded,
						Available = info.Available, UnitCost = info.UnitCost, PriceOf = info.PriceOf, Targets = rowTargets, HeroNote = heroNote,
					});
				}
				AddRow(c.UnitSid, false);
				foreach (var up in UpgradedStockViews(c))
					AddRow(up.UnitSid, true);
			}
			rows.Sort((a, b) => a.Tier != b.Tier ? a.Tier.CompareTo(b.Tier) : string.CompareOrdinal(a.DwellingName, b.DwellingName));
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			fail = "recruit all read threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogOncePerDay("bulk-read", fail);
			return false;
		}
	}

	/// <summary>Sum of several costs.</summary>
	internal static Dictionary<string, int> SumCost(IEnumerable<IReadOnlyDictionary<string, int>> costs)
	{
		var sum = new Dictionary<string, int>(StringComparer.Ordinal);
		foreach (var cost in costs)
			foreach (var pair in cost ?? new Dictionary<string, int>())
				sum[pair.Key] = (sum.TryGetValue(pair.Key, out var have) ? have : 0) + pair.Value;
		return sum;
	}

	/// <summary>Whether the local side can pay <paramref name="cost"/> now; <paramref name="missing"/> names the short resource.</summary>
	public static bool CanAffordNow(IReadOnlyDictionary<string, int> cost, out string missing)
	{
		missing = null;
		try
		{
			if (!TryLocalSide(out var side, out missing))
				return false;
			var copy = new Dictionary<string, int>(StringComparer.Ordinal);
			foreach (var pair in cost ?? new Dictionary<string, int>())
				copy[pair.Key] = pair.Value;
			return Fx.CanAfford(side, copy, out missing);
		}
		catch (Exception ex)
		{
			missing = ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>
	/// "Max all": counts per row, filled in row order, each the most the side can still pay for after the rows before it.
	/// Rows whose dwelling cannot deliver to <paramref name="target"/> get 0.
	/// </summary>
	public static int[] MaxAll(IReadOnlyList<LogisticsBulkRow> rows, (string Kind, long Key) target)
	{
		var counts = new int[rows?.Count ?? 0];
		var spent = new List<IReadOnlyDictionary<string, int>>();
		for (var i = 0; i < counts.Length; i++)
		{
			var row = rows[i];
			if (row?.PriceOf == null || !row.Targets.Contains(target))
				continue;
			int lo = 0, hi = row.Available;
			while (lo < hi)
			{
				var mid = (lo + hi + 1) / 2;
				var trial = new List<IReadOnlyDictionary<string, int>>(spent) { row.PriceOf(mid) };
				if (CanAffordNow(SumCost(trial), out _))
					lo = mid;
				else
					hi = mid - 1;
			}
			counts[i] = lo;
			if (lo > 0)
				spent.Add(row.PriceOf(lo));
		}
		return counts;
	}

	/// <summary>
	/// The army a delivery to the target lands in, by the hire paths' order (town: garrison hero, town garrison, visiting
	/// hero; hero: that hero), with its free slots now. Read-only. <paramref name="unitSid"/> (optional) picks the first
	/// army that could take that unit, as a hire would.
	/// </summary>
	public static bool TryPreviewDelivery(string targetKind, long targetKey, string unitSid, out LogisticsDeliveryPreview preview, out string fail)
	{
		preview = null;
		try
		{
			if (!TryLocalSide(out var side, out fail))
				return false;
			if (!Fx.TryBuildWorld(out var world, out var worldFail))
				return Fail("game state unreadable (" + worldFail + ")", out fail);
			var c = new Ctx { World = world, Side = side };
			var candidates = new List<(string Label, DataHero Hero, Hex.Session.Data.ObjCity Town)>();
			if (targetKind == "hero")
			{
				var h = targetKey is >= 0 and <= int.MaxValue ? FindSideHero(c, (int)targetKey) : null;
				if (h == null)
					return Fail("hero not found", out fail);
				candidates.Add(("Hero " + Homm3HeroDisplayNames.Resolve(h.configSid), h, null));
			}
			else if (targetKind == "town")
			{
				if (targetKey is < 0 or > int.MaxValue || !world.Cities.TryGetValue((int)targetKey, out var city) || city.ownerSide != side)
					return Fail("that town is not yours", out fail);
				if (city.garnisonHeroId >= 0 && FindSideHero(c, city.garnisonHeroId) is { } gh)
					candidates.Add(("Garrison hero " + Homm3HeroDisplayNames.Resolve(gh.configSid), gh, null));
				candidates.Add(("Town garrison", null, city));
				if (city.visitorHeroId >= 0 && city.visitorHeroId != city.garnisonHeroId && FindSideHero(c, city.visitorHeroId) is { } vh)
					candidates.Add(("Visiting hero " + Homm3HeroDisplayNames.Resolve(vh.configSid), vh, null));
			}
			else
				return Fail("unknown target", out fail);
			LogisticsDeliveryPreview first = null;
			var notes = new List<string>();
			foreach (var cand in candidates)
			{
				string[] sids;
				string readFail;
				if (cand.Town != null)
				{
					if (!Homm3FactoryLogisticsGarrison.TryGetTownGarrisonParty(cand.Town, out var party, out var partyFail))
					{
						notes.Add(cand.Label + ": " + partyFail);
						continue;
					}
					if (!Homm3PartyArmyWriter.TryReadPartyArmy(party, out sids, out _, out _, out readFail))
					{
						notes.Add(cand.Label + ": unreadable");
						continue;
					}
				}
				else
				{
					var lh = Homm3FactoryLogisticsRuntime.CachedLogicHero(cand.Hero);
					if (lh == null)
					{
						notes.Add(cand.Label + ": army not reachable yet");
						continue;
					}
					if (!Homm3PartyArmyWriter.TryReadArmy(lh, cand.Hero, out sids, out _, out _, out readFail))
					{
						notes.Add(cand.Label + ": unreadable");
						continue;
					}
				}
				var p = new LogisticsDeliveryPreview { ArmyLabel = cand.Label, Slots = sids.Length };
				foreach (var s in sids)
				{
					if (string.IsNullOrEmpty(s))
						p.FreeSlots++;
					else
						p.Present.Add(s);
				}
				first ??= p;
				if (unitSid == null || p.FreeSlots > 0 || p.Present.Contains(unitSid))
				{
					p.Note = notes.Count > 0 ? string.Join("; ", notes) : null;
					preview = p;
					fail = null;
					return true;
				}
				notes.Add(cand.Label + ": no free slot");
			}
			if (first != null)
			{
				first.Note = string.Join("; ", notes);
				preview = first;
				fail = null;
				return true;
			}
			return Fail(notes.Count > 0 ? string.Join("; ", notes) : "no army to deliver to", out fail);
		}
		catch (Exception ex)
		{
			fail = "delivery preview threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>
	/// "Hire all": hires each (row, count) in order through <see cref="TryRemoteHire"/> or
	/// <see cref="TryRemoteHireUpgraded"/> (each re-validates, charges, writes and verifies on its own). Stops at the first
	/// refusal. <paramref name="report"/> says what was hired and, when stopped, at which row and why.
	/// </summary>
	public static bool TryHireAll(IReadOnlyList<(LogisticsBulkRow Row, int Count)> orders, string targetKind, long targetKey, out string report, out int hiredOrders)
	{
		hiredOrders = 0;
		var done = new List<string>();
		try
		{
			foreach (var (row, count) in orders ?? Array.Empty<(LogisticsBulkRow, int)>())
			{
				if (row == null || count <= 0)
					continue;
				var name = Homm3UnitDisplayNames.Resolve(row.UnitSid) + (row.Upgraded ? " (upgraded)" : "");
				string fail;
				var ok = row.Upgraded
					? TryRemoteHireUpgraded(row.DwellingKey, row.UnitSid, count, targetKind, targetKey, out fail)
					: TryRemoteHire(row.DwellingKey, row.UnitSid, count, targetKind, targetKey, out fail);
				if (!ok)
				{
					report = (done.Count > 0 ? "Hired " + string.Join(", ", done) + ". " : "Nothing hired. ") + "Stopped at " + name + ": " + (fail ?? "refused") + ".";
					Homm3FactoryLogisticsRuntime.LogInfo("recruit all: " + report);
					return false;
				}
				hiredOrders++;
				done.Add(count + " " + name);
			}
			report = done.Count > 0 ? "Hired " + string.Join(", ", done) + "." : "Nothing to hire.";
			Homm3FactoryLogisticsRuntime.LogInfo("recruit all: " + report);
			return done.Count > 0;
		}
		catch (Exception ex)
		{
			report = (done.Count > 0 ? "Hired " + string.Join(", ", done) + ". " : "") + "Stopped: " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogError("recruit all threw: " + ex);
			return false;
		}
	}
}
