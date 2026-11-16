using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.Json;
using BepInEx;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network data contract: custom_factions/factory_logistics/logistics_config.json (the overlay
/// tools/release_port/homm3_factory_logistics_core_overlay.py reads the same file). Loaded fail-closed: a missing
/// or malformed file disables every logistics effect and command, with the reason logged under [FactoryLogistics].
/// </summary>
internal sealed class Homm3FactoryLogisticsConfig
{
	internal const string Schema = "homm3_factory_logistics_config/1";

	internal sealed class Enhancement
	{
		internal string Id;
		internal int Code;
		internal string Kind;   // mine | dwelling | any
		internal string Name;
		internal string Effect;
		internal HashSet<string> Resources = new(StringComparer.Ordinal);
		internal double[] Values = new double[3];
		internal double Step;
		internal double? Cap;
		internal double[] Values2;
		internal double Step2;
		internal string[] LevelLines = new string[3];
		internal List<Dictionary<string, int>> Costs;   // mines/hub: per level, "R" = advanced resource
		internal double[] DwellingGoldFactors;            // dwellings: per level
		internal int HeroDeliveryLevel;

		/// <summary>Effect value at an effective level (built + Power Station levels), extrapolated past 3, capped.</summary>
		internal double ValueAt(int effectiveLevel) => Extrapolate(Values, Step, Cap, effectiveLevel);

		internal double Value2At(int effectiveLevel) => Values2 == null ? 0 : Extrapolate(Values2, Step2, null, effectiveLevel);

		private static double Extrapolate(double[] values, double step, double? cap, int level)
		{
			if (level <= 0)
				return 0;
			var v = level <= values.Length ? values[level - 1] : values[values.Length - 1] + step * (level - values.Length);
			return cap.HasValue ? Math.Min(cap.Value, v) : v;
		}
	}

	internal int MaxLevel;

	// Hero subskills with runtime effects (SIDs kept from Split Assembly for save compatibility; text in
	// tools/release_port/homm3_factory_logistics_core_overlay.py SUBSKILL_TEXT).
	internal const string CommandCenterSubSkillSid = "sub_skill_faction_homm3_factory_sand_advantage";   // Mobile Command Center
	internal const string SupplyCaravanSubSkillSid = "sub_skill_faction_homm3_factory_industrial_tempo";  // Supply Caravan
	internal const string TradeContractsSubSkillSid = "sub_skill_faction_homm3_factory_couatl_relay";     // Trade Contracts
	internal const int TradeContractsMarketsPerHero = 2;
	internal int BaseLogisticsLevel;
	internal int RangeMpPerLevel;
	internal int[] DustCostByLevel;
	internal int GoldRounding;
	internal double CostScale = 1.0;
	internal string SkillSid;
	internal string SpellSid;
	internal string CarrierBuffSid;
	internal string HeroStatBuffPrefix;
	internal int HeroStatBuffMaxLevel;
	internal HashSet<string> MineResources = new(StringComparer.Ordinal);
	internal Dictionary<string, string> MineRareCycle = new(StringComparer.Ordinal);
	internal int MarketBasicValue;
	internal int MarketRareValue;
	internal HashSet<string> MarketRareResources = new(StringComparer.Ordinal);
	internal double ExtraChargeBase;
	internal double ExtraChargePerMarket;
	internal HashSet<string> MarketBuildingSids = new(StringComparer.Ordinal);
	internal Dictionary<int, int> DwellingTierGold = new();
	internal Dictionary<int, int> DwellingTierWeeklyValue = new();
	internal string DwellingRareFallback;
	internal int DwellingRareFallbackMultiplier;
	internal HashSet<string> DwellingRareResources = new(StringComparer.Ordinal);
	internal int AstrologyPerTown;   // per counted town per day, Arcane Manufactory (DECISIONS.md #55)
	internal bool PersistenceEnabled;
	internal List<Enhancement> Enhancements = new();
	internal Dictionary<string, Enhancement> ById = new(StringComparer.Ordinal);
	internal Dictionary<int, Enhancement> ByCode = new();

	internal static string ConfigPath => Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "custom_factions", "factory_logistics", "logistics_config.json");

	internal Enhancement Get(string id) => id != null && ById.TryGetValue(id, out var e) ? e : null;

	internal Enhancement Get(int code) => ByCode.TryGetValue(code, out var e) ? e : null;

	/// <summary>Market sell value of one unit of <paramref name="resource"/> for a side that owns <paramref name="markets"/> markets.</summary>
	internal double SellValue(string resource, int markets)
	{
		var baseValue = MarketRareResources.Contains(resource) ? MarketRareValue : MarketBasicValue;
		var extra = Math.Max(0.0, ExtraChargeBase - ExtraChargePerMarket * Math.Max(0, markets));
		return baseValue / (1.0 + extra);
	}

	/// <summary>
	/// Cost of building <paramref name="level"/> (1..3) of <paramref name="e"/> before the Warehouse discount.
	/// Mines/hubs: table cost, "R" = the mine's advanced resource from the cycle (dwelling hubs: the dwelling rare).
	/// Dwellings: gold = factor x tier gold rounded to <see cref="GoldRounding"/>; L1 adds b wood and b ore, L2 q rare, L3 2q rare.
	/// Every L2/L3 also costs <see cref="DustCostByLevel"/> dust.
	/// </summary>
	internal Dictionary<string, int> CostOf(Enhancement e, int level, bool isDwelling, string mineResource, int unitTier, string dwellingRare, out string fail)
	{
		fail = null;
		var cost = new Dictionary<string, int>(StringComparer.Ordinal);
		if (level < 1 || level > MaxLevel)
		{
			fail = "level " + level + " outside 1.." + MaxLevel;
			return null;
		}
		string rare;
		var rareMultiplier = 1;
		if (isDwelling)
		{
			rare = dwellingRare;
			if (string.IsNullOrEmpty(rare))
			{
				rare = DwellingRareFallback;
				rareMultiplier = DwellingRareFallbackMultiplier;
			}
		}
		else if (!MineRareCycle.TryGetValue(mineResource ?? "", out rare))
		{
			fail = "no advanced resource for mine resource '" + mineResource + "'";
			return null;
		}
		if (e.Costs != null)
		{
			foreach (var pair in e.Costs[level - 1])
				Add(cost, pair.Key == "R" ? rare : pair.Key, pair.Key == "R" ? pair.Value * rareMultiplier : pair.Value);
		}
		else if (e.DwellingGoldFactors != null)
		{
			if (!DwellingTierGold.TryGetValue(Math.Max(1, Math.Min(7, unitTier)), out var d))
			{
				fail = "no tier gold for tier " + unitTier;
				return null;
			}
			Add(cost, "gold", RoundGold(d * e.DwellingGoldFactors[level - 1]));
			var t = Math.Max(1, Math.Min(7, unitTier));
			var half = (t + 1) / 2;
			if (level == 1)
			{
				Add(cost, "wood", half + 2);
				Add(cost, GameSymbols.CovePlunder.OreResourceName, half + 2);
			}
			else
			{
				Add(cost, rare, (half + 1) * (level == 3 ? 2 : 1) * rareMultiplier);
			}
		}
		else
		{
			fail = "enhancement " + e.Id + " has no cost data";
			return null;
		}
		if (DustCostByLevel != null && level - 1 < DustCostByLevel.Length && DustCostByLevel[level - 1] > 0)
			Add(cost, "dust", DustCostByLevel[level - 1]);
		return Scaled(cost);
	}

	/// <summary>
	/// <see cref="CostScale"/> over every price (user 2026-11-16: "about 20 percent"): gold rounds to GoldRounding x scale
	/// (250 -> 50), every other resource rounds to nearest with a floor of 1.
	/// </summary>
	private Dictionary<string, int> Scaled(Dictionary<string, int> cost)
	{
		if (CostScale <= 0.0 || Math.Abs(CostScale - 1.0) < 1e-9)
			return cost;
		var step = Math.Max(10, (int)Math.Round(Math.Max(1, GoldRounding) * CostScale));
		var scaled = new Dictionary<string, int>(StringComparer.Ordinal);
		foreach (var pair in cost)
		{
			var v = pair.Value * CostScale;
			scaled[pair.Key] = pair.Key == "gold"
				? (int)Math.Max(step, Math.Round(v / step, MidpointRounding.AwayFromZero) * step)
				: Math.Max(1, (int)Math.Round(v, MidpointRounding.AwayFromZero));
		}
		return scaled;
	}

	internal int RoundGold(double gold)
	{
		var step = Math.Max(1, GoldRounding);
		return (int)Math.Max(step, Math.Round(gold / step, MidpointRounding.AwayFromZero) * step);
	}

	private static void Add(Dictionary<string, int> cost, string resource, int amount)
	{
		if (amount <= 0 || string.IsNullOrEmpty(resource))
			return;
		cost[resource] = (cost.TryGetValue(resource, out var have) ? have : 0) + amount;
	}

	// ---------------------------------------------------------------- loading

	private static Homm3FactoryLogisticsConfig _cached;
	private static DateTime _cachedWrite;
	private static string _cachedPath;

	internal static bool TryLoad(out Homm3FactoryLogisticsConfig config, out string failReason) => TryLoad(ConfigPath, out config, out failReason);

	/// <summary>Reads and validates the config; re-parses only when the file changed. False with the reason (fail closed).</summary>
	internal static bool TryLoad(string path, out Homm3FactoryLogisticsConfig config, out string failReason)
	{
		config = null;
		failReason = null;
		try
		{
			if (!File.Exists(path))
			{
				failReason = "file missing: " + path;
				return false;
			}
			var write = File.GetLastWriteTimeUtc(path);
			if (_cached != null && write == _cachedWrite && string.Equals(path, _cachedPath, StringComparison.OrdinalIgnoreCase))
			{
				config = _cached;
				return true;
			}
			using var doc = JsonDocument.Parse(File.ReadAllText(path), new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
			var parsed = Parse(doc.RootElement);
			_cached = parsed;
			_cachedWrite = write;
			_cachedPath = path;
			config = parsed;
			return true;
		}
		catch (Exception ex)
		{
			failReason = ex.GetBaseException().Message;
			return false;
		}
	}

	private static Homm3FactoryLogisticsConfig Parse(JsonElement root)
	{
		if (Str(root, "schema") != Schema)
			throw new FormatException("schema is not " + Schema);
		var c = new Homm3FactoryLogisticsConfig
		{
			SkillSid = Str(root, "skillSid"),
			SpellSid = Str(root, "spellSid"),
			CarrierBuffSid = Str(root, "carrierBuffSid"),
			HeroStatBuffPrefix = Str(root, "heroStatBuffPrefix"),
			HeroStatBuffMaxLevel = Int(root, "heroStatBuffMaxLevel"),
			MaxLevel = Int(root, "maxLevel"),
			BaseLogisticsLevel = Int(root, "baseLogisticsLevel"),
			RangeMpPerLevel = Int(root, "rangeMpPerLevel"),
			GoldRounding = Int(root, "goldRounding"),
			CostScale = root.TryGetProperty("costScale", out var costScale) && costScale.ValueKind == System.Text.Json.JsonValueKind.Number ? costScale.GetDouble() : 1.0,
			AstrologyPerTown = Int(root, "astrologyPerTown"),
			// Kill-switch for the side-buff save carrier; required (fail closed when absent or not a bool).
			PersistenceEnabled = root.GetProperty("persistenceEnabled").GetBoolean(),
		};
		if (c.MaxLevel != 3)
			throw new FormatException("maxLevel must be 3");
		c.DustCostByLevel = Ints(root.GetProperty("dustCostByLevel"), "dustCostByLevel");
		if (c.DustCostByLevel.Length != 3)
			throw new FormatException("dustCostByLevel needs 3 entries");
		foreach (var s in Strings(root.GetProperty("mineResources"), "mineResources"))
			c.MineResources.Add(s);
		foreach (var p in root.GetProperty("mineRareCycle").EnumerateObject())
			c.MineRareCycle[p.Name] = p.Value.GetString();
		foreach (var r in c.MineResources)
		{
			if (!c.MineRareCycle.TryGetValue(r, out var rare) || string.IsNullOrEmpty(rare) || rare == r)
				throw new FormatException("mineRareCycle has no valid entry for " + r);
		}
		var market = root.GetProperty("market");
		c.MarketBasicValue = Int(market, "basicValue");
		c.MarketRareValue = Int(market, "rareValue");
		c.ExtraChargeBase = Dbl(market, "extraChargeBase");
		c.ExtraChargePerMarket = Dbl(market, "extraChargePerMarket");
		foreach (var s in Strings(market.GetProperty("rareResources"), "market.rareResources"))
			c.MarketRareResources.Add(s);
		foreach (var s in Strings(market.GetProperty("marketBuildingSids"), "market.marketBuildingSids"))
			c.MarketBuildingSids.Add(s);
		var dwelling = root.GetProperty("dwelling");
		foreach (var p in dwelling.GetProperty("tierGold").EnumerateObject())
			c.DwellingTierGold[int.Parse(p.Name, CultureInfo.InvariantCulture)] = p.Value.GetInt32();
		foreach (var p in dwelling.GetProperty("tierWeeklyValue").EnumerateObject())
			c.DwellingTierWeeklyValue[int.Parse(p.Name, CultureInfo.InvariantCulture)] = p.Value.GetInt32();
		for (var t = 1; t <= 7; t++)
		{
			if (!c.DwellingTierGold.ContainsKey(t) || !c.DwellingTierWeeklyValue.ContainsKey(t))
				throw new FormatException("dwelling tier tables miss tier " + t);
		}
		c.DwellingRareFallback = Str(dwelling, "rareFallback");
		c.DwellingRareFallbackMultiplier = Int(dwelling, "rareFallbackMultiplier");
		foreach (var s in Strings(dwelling.GetProperty("rareResources"), "dwelling.rareResources"))
			c.DwellingRareResources.Add(s);

		foreach (var row in root.GetProperty("enhancements").EnumerateArray())
		{
			var e = new Enhancement
			{
				Id = Str(row, "id"),
				Code = Int(row, "code"),
				Kind = Str(row, "kind"),
				Name = Str(row, "name"),
				Effect = Str(row, "effect"),
				Step = Dbl(row, "step"),
			};
			if (e.Code < 1 || e.Code > 31)
				throw new FormatException(e.Id + ": code must be 1..31 (5-bit save field)");
			if (e.Kind != "mine" && e.Kind != "dwelling" && e.Kind != "any")
				throw new FormatException(e.Id + ": kind must be mine, dwelling or any");
			e.Values = Dbls(row.GetProperty("values"), e.Id + ".values");
			if (e.Values.Length != 3)
				throw new FormatException(e.Id + ": values needs 3 entries");
			if (row.TryGetProperty("cap", out var cap) && cap.ValueKind == JsonValueKind.Number)
				e.Cap = cap.GetDouble();
			if (row.TryGetProperty("values2", out var v2))
			{
				e.Values2 = Dbls(v2, e.Id + ".values2");
				e.Step2 = Dbl(row, "step2");
			}
			if (row.TryGetProperty("heroDeliveryLevel", out var hd))
				e.HeroDeliveryLevel = hd.GetInt32();
			var lines = Strings(row.GetProperty("levelLines"), e.Id + ".levelLines");
			if (lines.Count != 3)
				throw new FormatException(e.Id + ": levelLines needs 3 entries");
			e.LevelLines = lines.ToArray();
			if (row.TryGetProperty("resources", out var res))
			{
				foreach (var s in Strings(res, e.Id + ".resources"))
					e.Resources.Add(s);
			}
			if (row.TryGetProperty("costs", out var costs))
			{
				e.Costs = new List<Dictionary<string, int>>();
				foreach (var level in costs.EnumerateArray())
				{
					var d = new Dictionary<string, int>(StringComparer.Ordinal);
					foreach (var p in level.EnumerateObject())
						d[p.Name] = p.Value.GetInt32();
					e.Costs.Add(d);
				}
				if (e.Costs.Count != 3)
					throw new FormatException(e.Id + ": costs needs 3 levels");
			}
			if (row.TryGetProperty("dwellingGoldFactors", out var factors))
			{
				e.DwellingGoldFactors = Dbls(factors, e.Id + ".dwellingGoldFactors");
				if (e.DwellingGoldFactors.Length != 3)
					throw new FormatException(e.Id + ": dwellingGoldFactors needs 3 entries");
			}
			if (e.Costs == null && e.DwellingGoldFactors == null)
				throw new FormatException(e.Id + ": no costs");
			if (e.Kind != "dwelling" && e.Resources.Count == 0)
				throw new FormatException(e.Id + ": mine enhancement without resources");
			if (c.ById.ContainsKey(e.Id) || c.ByCode.ContainsKey(e.Code))
				throw new FormatException("duplicate enhancement id/code " + e.Id + "/" + e.Code);
			c.Enhancements.Add(e);
			c.ById[e.Id] = e;
			c.ByCode[e.Code] = e;
		}
		foreach (var effect in new[] { "byproduct", "export", "warehouse", "rail_station", "power_station", "synthesizer", "arcane", "route_hub", "food", "housing", "rail_network", "mercenary", "support" })
		{
			if (!c.Enhancements.Exists(e => e.Effect == effect))
				throw new FormatException("no enhancement with effect " + effect);
		}
		return c;
	}

	private static string Str(JsonElement obj, string name)
	{
		var s = obj.GetProperty(name).GetString();
		if (string.IsNullOrWhiteSpace(s))
			throw new FormatException("empty " + name);
		return s;
	}

	private static int Int(JsonElement obj, string name) => obj.GetProperty(name).GetInt32();

	private static double Dbl(JsonElement obj, string name) => obj.GetProperty(name).GetDouble();

	private static int[] Ints(JsonElement array, string label)
	{
		if (array.ValueKind != JsonValueKind.Array)
			throw new FormatException(label + " is not an array");
		var list = new List<int>();
		foreach (var item in array.EnumerateArray())
			list.Add(item.GetInt32());
		return list.ToArray();
	}

	private static double[] Dbls(JsonElement array, string label)
	{
		if (array.ValueKind != JsonValueKind.Array)
			throw new FormatException(label + " is not an array");
		var list = new List<double>();
		foreach (var item in array.EnumerateArray())
			list.Add(item.GetDouble());
		return list.ToArray();
	}

	private static List<string> Strings(JsonElement array, string label)
	{
		if (array.ValueKind != JsonValueKind.Array)
			throw new FormatException(label + " is not an array");
		var list = new List<string>();
		foreach (var item in array.EnumerateArray())
		{
			var s = item.GetString();
			if (string.IsNullOrWhiteSpace(s))
				throw new FormatException(label + " has an empty entry");
			list.Add(s);
		}
		return list;
	}
}
