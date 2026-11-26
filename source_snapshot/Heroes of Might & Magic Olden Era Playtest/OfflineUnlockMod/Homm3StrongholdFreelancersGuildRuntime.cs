using System;
using System.Collections.Generic;
using System.Globalization;
using Hex.Configs;
using DataObjCity = Hex.Session.Data.ObjCity;
using TownHero = OfflineUnlockMod.Homm3TownBuildingWindowKit.TownHero;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22: Stronghold Freelancer's Guild (HoMM3: sell creatures for resources). Lives on the Silo II
/// slot (Build_Resource_Depot_level_2, owner decision). The window sells creatures from the town garrison, the garrison
/// hero or the visiting hero.
/// Price model (assumption, documented in docs/building_pass_20261122/build_sfc.md):
///   value of one creature = half its recruit cost in gold, where each non-gold resource in that cost counts at the
///   Marketplace sell rate (Factory logistics market model: base / (1 + max(0, 3.5 - 0.5 x Marketplaces)));
///   paid in gold, or in a resource bought at base x (1 + same surcharge); gold that does not buy a whole unit of the
///   resource is paid as gold, so nothing is lost.
/// A hero never sells its last creature. Sales are instant, so there is no daily/weekly state to persist.
/// </summary>
internal static class Homm3StrongholdFreelancersGuildRuntime
{
	internal const string FactionSid = "homm3_stronghold";
	internal const string BuildingSid = "Build_Resource_Depot_level_2";
	internal const string LogPrefix = "HoMM3 Stronghold Freelancer's Guild: ";
	internal static readonly string[] PayResources = GameSymbols.TownBuildingPass.FreelancerPayResources;

	internal sealed class Source
	{
		internal string Label;
		internal TownHero Hero; // null for the heroless garrison
		internal object LogicParty; // garrison only
		internal string[] Sid;
		internal int[] Count;
		internal Dictionary<string, int> Totals;
		internal int Stacks;
		internal string Fail;
	}

	internal sealed class Rates
	{
		internal Homm3FactoryLogisticsConfig Config;
		internal int Markets;
		internal int Side;

		internal double Surcharge => Math.Max(0.0, Config.ExtraChargeBase - Config.ExtraChargePerMarket * Math.Max(0, Markets));
		private double Base(string res) => Config.MarketRareResources.Contains(res) ? Config.MarketRareValue : Config.MarketBasicValue;
		internal double SellValue(string res) => Config.SellValue(res, Markets);
		internal double BuyPrice(string res) => Base(res) * (1.0 + Surcharge);
	}

	internal static bool TryRates(int side, out Rates rates, out string fail)
	{
		rates = null;
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out fail))
		{
			fail = "market rates unreadable (" + fail + ")";
			return false;
		}
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out fail))
		{
			fail = "world unreadable (" + fail + ")";
			return false;
		}
		rates = new Rates { Config = config, Markets = Homm3FactoryLogisticsEffects.CountMarkets(world, side), Side = side };
		return true;
	}

	/// <summary>The town's sale sources: the garrison (if it has creatures and is not the garrison hero's own party), then each hero.</summary>
	internal static List<Source> ReadSources(DataObjCity city)
	{
		var result = new List<Source>();
		if (city == null)
			return result;
		var heroes = Homm3TownBuildingWindowKit.HeroesInTown(city);
		var heroParties = new HashSet<IntPtr>();
		foreach (var h in heroes)
		{
			var party = h.Data?.party;
			if (party != null)
				heroParties.Add(party.Pointer);
		}
		var garrisonData = city.garnisonParty;
		if (garrisonData != null && !heroParties.Contains(garrisonData.Pointer))
		{
			var s = new Source { Label = "Garrison" };
			if (Homm3FactoryLogisticsGarrison.TryGetTownGarrisonParty(city, out var party, out var fail)
			    && Homm3PartyArmyWriter.TryReadPartyArmy(party, out var sid, out var count, out var totals, out fail))
			{
				s.LogicParty = party;
				Fill(s, sid, count, totals);
			}
			else
			{
				s.Fail = fail;
			}
			if (s.Fail != null || s.Stacks > 0)
				result.Add(s);
		}
		foreach (var h in heroes)
		{
			var s = new Source { Label = h.Name + (h.Visitor ? " (visiting)" : " (garrison)"), Hero = h };
			if (h.Logic == null)
				s.Fail = "hero not ready yet (end the turn once or move the hero)";
			else if (Homm3PartyArmyWriter.TryReadArmy(h.Logic, h.Data, out var sid, out var count, out var totals, out var fail))
				Fill(s, sid, count, totals);
			else
				s.Fail = fail;
			result.Add(s);
		}
		return result;
	}

	private static void Fill(Source s, string[] sid, int[] count, Dictionary<string, int> totals)
	{
		s.Sid = sid;
		s.Count = count;
		s.Totals = totals;
		s.Stacks = 0;
		for (var i = 0; i < sid.Length; i++)
			if (sid[i] != null && count[i] > 0)
				s.Stacks++;
	}

	/// <summary>How many creatures of <paramref name="slot"/> may be sold (a hero keeps at least one creature).</summary>
	internal static int MaxSell(Source s, int slot)
	{
		if (s?.Sid == null || slot < 0 || slot >= s.Sid.Length || s.Sid[slot] == null)
			return 0;
		var count = s.Count[slot];
		return s.Hero != null && s.Stacks <= 1 ? Math.Max(0, count - 1) : count;
	}

	/// <summary>Gold value of one creature (half its recruit cost, non-gold cost at the sell rate); 0 when unreadable.</summary>
	internal static double WorthGold(string sid, Rates rates)
	{
		UnitLogicConfig unit;
		try
		{
			unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
		}
		catch
		{
			return 0;
		}
		var costs = unit?.unitCost?.costResArray;
		var total = 0.0;
		for (var i = 0; costs != null && i < costs.Length; i++)
		{
			var name = costs[i]?.name?.Trim();
			if (name == null || Homm3TowerArtificingRuntime.ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is not int amount || amount <= 0)
				continue;
			total += name == "gold" ? amount : amount * rates.SellValue(name);
		}
		return total * 0.5;
	}

	/// <summary>The payout of <paramref name="gold"/> in <paramref name="resource"/>: whole units plus leftover gold.</summary>
	internal static (int Amount, int Gold) Convert(long gold, string resource, Rates rates)
	{
		if (gold <= 0)
			return (0, 0);
		if (resource == "gold")
			return ((int)Math.Min(int.MaxValue, gold), 0);
		var price = rates.BuyPrice(resource);
		if (price <= 0)
			return (0, (int)Math.Min(int.MaxValue, gold));
		var amount = (int)Math.Floor(gold / price);
		var left = gold - (long)Math.Ceiling(amount * price);
		return (amount, (int)Math.Max(0, Math.Min(int.MaxValue, left)));
	}

	internal static string Describe((int Amount, int Gold) pay, string resource)
	{
		if (resource == "gold")
			return N(pay.Amount) + " gold";
		var parts = new List<string>();
		if (pay.Amount > 0)
			parts.Add(N(pay.Amount) + " " + resource);
		if (pay.Gold > 0)
			parts.Add(N(pay.Gold) + " gold");
		return parts.Count == 0 ? "nothing" : string.Join(" + ", parts);
	}

	internal static string N(long v) => v.ToString("N0", CultureInfo.InvariantCulture);

	/// <summary>
	/// Sells <paramref name="count"/> creatures from <paramref name="slot"/> of the source labelled <paramref name="label"/>
	/// (re-read live), pays the side, and says what happened. Payment follows the creatures actually removed.
	/// </summary>
	internal static bool Sell(DataObjCity city, string label, int slot, int count, string resource, out string result)
	{
		result = null;
		try
		{
			Source source = null;
			foreach (var s in ReadSources(city))
				if (s.Label == label) { source = s; break; }
			if (source == null || source.Fail != null)
			{
				result = "Cannot sell: " + (source?.Fail ?? "the army is gone");
				return false;
			}
			var max = MaxSell(source, slot);
			count = Math.Min(count, max);
			if (count <= 0)
			{
				result = source.Hero != null ? "A hero must keep at least one creature." : "Nothing to sell.";
				return false;
			}
			if (!TryRates(city.ownerSide, out var rates, out var fail))
			{
				result = "Cannot sell: " + fail;
				return false;
			}
			var sid = source.Sid[slot];
			var worth = WorthGold(sid, rates);
			if (worth <= 0)
			{
				result = "Cannot sell " + Homm3UnitDisplayNames.Resolve(sid) + ": its recruit cost is unreadable.";
				return false;
			}
			var targetSid = (string[])source.Sid.Clone();
			var targetCount = (int[])source.Count.Clone();
			targetCount[slot] -= count;
			if (targetCount[slot] <= 0)
			{
				targetCount[slot] = 0;
				targetSid[slot] = null;
			}
			var steps = new List<string>();
			var write = source.Hero != null
				? Homm3PartyArmyWriter.Write(source.Hero.Logic, source.Hero.Data, targetSid, targetCount, source.Totals, steps, out fail)
				: Homm3PartyArmyWriter.WritePartyArmy(source.LogicParty, targetSid, targetCount, source.Totals, steps, out fail);
			if (write == Homm3PartyArmyWriter.WriteResult.Refused)
			{
				result = "Cannot sell: " + fail;
				return false;
			}
			// Pay for what actually left the army (a partial write pays only for the creatures removed).
			var sold = count;
			if (write != Homm3PartyArmyWriter.WriteResult.Written)
			{
				Homm3TownBuildingWindowKit.LogWarning("Freelancer's Guild write " + write + " (" + fail + "); paying for creatures removed.");
				var after = source.Hero != null
					? Homm3PartyArmyWriter.TryReadArmy(source.Hero.Logic, source.Hero.Data, out _, out _, out var t1, out _) ? t1 : null
					: Homm3PartyArmyWriter.TryReadPartyArmy(source.LogicParty, out _, out _, out var t2, out _) ? t2 : null;
				var before = source.Totals.TryGetValue(sid, out var b) ? b : 0;
				var now = after != null && after.TryGetValue(sid, out var a) ? a : (after != null ? 0 : before);
				sold = Math.Max(0, before - now);
			}
			if (sold <= 0)
			{
				result = "The sale did not go through (" + fail + ").";
				return false;
			}
			var gold = (long)Math.Floor(worth * sold);
			var pay = Convert(gold, resource, rates);
			var paidOk = true;
			if (pay.Amount > 0)
				paidOk &= Homm3FactoryLogisticsEffects.TryAddResource(city.ownerSide, resource, pay.Amount, out fail);
			if (pay.Gold > 0)
				paidOk &= Homm3FactoryLogisticsEffects.TryAddResource(city.ownerSide, "gold", pay.Gold, out fail);
			var line = "Sold " + N(sold) + " " + Homm3UnitDisplayNames.Resolve(sid) + " for " + Describe(pay, resource) + ".";
			Homm3TownBuildingWindowKit.LogInfo("Freelancer's Guild: " + line + " [" + string.Join("; ", steps) + "]" + (paidOk ? "" : " PAYMENT FAILED: " + fail));
			result = paidOk ? line : line + " Payment failed: " + fail;
			return paidOk;
		}
		catch (Exception ex)
		{
			result = "Sale failed: " + ex.GetBaseException().Message;
			Homm3TownBuildingWindowKit.LogWarning("Freelancer's Guild sale threw: " + ex);
			return false;
		}
	}
}
