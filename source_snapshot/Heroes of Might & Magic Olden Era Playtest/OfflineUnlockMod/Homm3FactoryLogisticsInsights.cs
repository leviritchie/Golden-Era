using System;
using System.Collections.Generic;
using System.Globalization;
using Fx = OfflineUnlockMod.Homm3FactoryLogisticsEffects;
using Cfg = OfflineUnlockMod.Homm3FactoryLogisticsConfig;

namespace OfflineUnlockMod;

/// <summary>Network-wide income and output, as the runtime pays it (viewer totals bar and before/after preview).</summary>
internal sealed class LogisticsTotals
{
	public int GoldPerDay;
	/// <summary>7 x the daily gold plus weekly gold (Mercenary Headquarters).</summary>
	public int GoldPerWeek;
	public int WeeklyGold;
	/// <summary>Extra resources per day (Byproduct Processing extra output, before the pooled rounding).</summary>
	public readonly SortedDictionary<string, double> ResourcesPerDay = new(StringComparer.Ordinal);
	/// <summary>Mine output given up per day (enhancements that replace output).</summary>
	public readonly SortedDictionary<string, int> GivenUpPerDay = new(StringComparer.Ordinal);
	public int ExtraUnitsPerWeek;
	public int UnitsGivenUpPerWeek;
	public int UpgradedPerWeek;
	public int AstrologyPerDay;
	public int RangeMp;
}

// Read-only explanations for the Logistics panels (UX pass 2026-11-16): link status, recommended enhancement,
// effect numbers in the runtime's own maths, network totals, before/after previews, range reach and no-path reasons.
// Nothing here mutates state; every entry point fails closed with a reason.
internal static partial class Homm3FactoryLogistics
{
	/// <summary>Player range unit: 1 day = vanilla base hero movement (shared vocabulary, ux_lanes.md).</summary>
	internal const int MpPerDay = 200;

	private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

	/// <summary>"0.5 day", "1.0 day", "1.5 days" (one decimal, rounded up to the next tenth).</summary>
	internal static string Days(int mp)
	{
		var d = Math.Ceiling(Math.Max(0, mp) / (MpPerDay / 10.0) - 1e-9) / 10.0;
		return d.ToString("0.0", Inv) + (d > 1.0 + 1e-9 ? " days" : " day");
	}

	internal static string NeedsRange(int missingMp) => "needs +" + Days(Math.Max(1, missingMp)) + " of range";

	private static string N0(double v) => Math.Round(v).ToString("N0", Inv);

	private static string F1(double v) => v.ToString(v >= 10 || Math.Abs(v - Math.Round(v)) < 0.05 ? "0" : "0.#", Inv);

	private static string Res(string sid) => Homm3FactoryLogisticsUi.ResourceName(sid);

	/// <summary>True when the enhancement stops the building's own production (mines: Export Office and the logistics
	/// functions; dwellings: Mercenary Headquarters and Support Hub).</summary>
	internal static bool ReplacesOutput(Cfg.Enhancement e) => e != null && (Fx.SuppressesOutput(e) || e.Effect is "mercenary" or "support");

	// ---------------------------------------------------------------- per-building numbers

	private static int MineOutputOf(Fx.World world, int id, string resource) =>
		world.Mines.TryGetValue(id, out var mine) ? Fx.MineOutput(mine, resource) : 0;

	/// <summary>(native weekly units, gold price, tier) of every unit set of a dwelling.</summary>
	private static List<(int Weekly, int Price, int Tier)> DwellingSets(Cfg config, Fx.World world, int id)
	{
		var list = new List<(int, int, int)>();
		if (!world.Dwellings.TryGetValue(id, out var d))
			return list;
		var sets = d.assortmentData?.unitSets;
		for (var i = 0; sets != null && i < sets.Count; i++)
		{
			var set = sets[i];
			if (set == null)
				continue;
			var sid = set.sids != null && set.sids.Count > 0 ? set.sids[0] : null;
			var unit = sid == null ? null : Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
			var price = 0;
			if (unit != null)
				Fx.ReadUnitCost(unit, config, out price, out _);
			list.Add((Math.Max(0, set.weeklyIncrement), price, unit == null ? 1 : Math.Max(1, Math.Min(7, unit.tier))));
		}
		return list;
	}

	/// <summary>Mercenary Headquarters gold per week, as the dwelling week postfix pays it.</summary>
	private static int MercenaryGold(Cfg config, Fx.World world, Fx.Network net, int id, Cfg.Enhancement e, int eff)
	{
		var support = net.SupportGrowthPct.TryGetValue(id, out var sp) ? sp : 0.0;
		var synth = net.SynthMultiplier.TryGetValue(id, out var s) ? s : 1.0;
		var gold = 0L;
		foreach (var (weekly, price, tier) in DwellingSets(config, world, id))
		{
			if (weekly <= 0 || price <= 0)
				continue;
			var delta = weekly + (int)Math.Floor(weekly * support / 100.0 + 1e-9);
			var cap = config.DwellingTierWeeklyValue.TryGetValue(tier, out var c) ? c : int.MaxValue;
			gold += (long)Math.Floor(Math.Min((long)delta * price, cap) * e.ValueAt(eff) * synth);
		}
		return (int)Math.Min(int.MaxValue, gold);
	}

	private static int WeeklyUnits(Cfg config, Fx.World world, int id)
	{
		var n = 0;
		foreach (var set in DwellingSets(config, world, id))
			n += set.Weekly;
		return n;
	}

	private static int ReachedFrom(Fx.Network net, int id, Func<Homm3FactoryLogisticsRange.Route, bool> accept)
	{
		var n = 0;
		foreach (var r in net.Display?.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
		{
			if (r.Reached && r.From == id && r.To != id && accept(r))
				n++;
		}
		return n;
	}

	/// <summary>
	/// What the enhancement does here at <paramref name="eff"/> (powered level), in numbers from the runtime's maths:
	/// e.g. "+250 gold/day; replaces 1 crystal/day". <paramref name="active"/> adds counts of what it reaches now.
	/// </summary>
	private static string EffectText(Ctx c, Cfg.Enhancement e, int eff, bool active)
	{
		if (e == null || eff <= 0)
			return null;
		var cfg = c.Config;
		var v = e.ValueAt(eff);
		var output = c.IsDwelling ? 0 : MineOutputOf(c.World, c.ObjectId, c.Resource);
		var replaces = output > 0 ? "replaces " + output + " " + Res(c.Resource) + "/day" : "the mine stops producing";
		var weekly = c.IsDwelling ? WeeklyUnits(cfg, c.World, c.ObjectId) : 0;
		string text;
		switch (e.Effect)
		{
			case "byproduct":
			{
				var extra = output * e.Value2At(eff) / 100.0;
				text = "+" + N0(v) + " gold/day" + (extra > 0.0 ? ", +" + F1(extra) + " " + Res(c.Resource) + "/day" : "");
				break;
			}
			case "export":
				text = "+" + N0(Fx.ExportGold(cfg, c.Net, c.World, c.Side, c.ObjectId, c.Resource, output, eff)) + " gold/day; " + replaces;
				break;
			case "warehouse":
				text = "Other enhancements cost " + N0(Math.Min(90, v)) + "% less; " + replaces;
				break;
			case "rail_station":
				text = "+" + Days((int)Math.Round(v) * cfg.RangeMpPerLevel) + " of network range; works as a full Logistics Hub; " + replaces;
				break;
			case "power_station":
			{
				var n = active ? ReachedFrom(c.Net, c.ObjectId, r => r.ToKind == "building") : -1;
				text = "+" + N0(v) + " powered level" + (v >= 1.5 ? "s" : "") + " to " + (n >= 0 ? n + " enhanced building" + (n == 1 ? "" : "s") : "enhanced buildings") + " in range; " + replaces;
				break;
			}
			case "synthesizer":
				text = "Export Offices and Mercenary HQs in range pay x" + v.ToString("0.##", Inv) + "; +1 market for up to " + eff + " town" + (eff == 1 ? "" : "s") + "; " + replaces;
				break;
			case "arcane":
				text = "Heroes in range +" + N0(v) + " to all stats; +" + cfg.AstrologyPerTown + " astrology/day per town (up to " + eff + "); " + Math.Min(6, eff) + "/6 of dwelling growth upgraded; " + replaces;
				break;
			case "route_hub":
				text = "Routes through here get back " + N0(Math.Min(1.0, v) * 100) + "% of the range they spent";
				break;
			case "food":
			{
				var add = 0;
				foreach (var set in DwellingSets(cfg, c.World, c.ObjectId))
					add += (int)Math.Floor(set.Weekly * v / 100.0);
				text = "+" + add + " unit" + (add == 1 ? "" : "s") + "/week (+" + N0(v) + "%)";
				break;
			}
			case "housing":
				text = "Units hired here cost " + N0(Math.Min(90, v)) + "% less";
				break;
			case "rail_network":
				text = "Hire here from the viewer; delivers to towns" + (eff >= Math.Max(1, e.HeroDeliveryLevel) ? " and heroes" : " (heroes from level " + e.HeroDeliveryLevel + ")") + " in range"
				       + (v >= 0.5 ? "; +" + Days((int)Math.Round(v) * cfg.RangeMpPerLevel) + " of range for its routes" : "");
				break;
			case "mercenary":
			{
				var gold = MercenaryGold(cfg, c.World, c.Net, c.ObjectId, e, eff);
				text = "+" + N0(gold) + " gold/week (about " + N0(gold / 7.0) + "/day); replaces " + weekly + " unit" + (weekly == 1 ? "" : "s") + "/week";
				break;
			}
			case "support":
			{
				var units = 0;
				var reached = 0;
				if (active)
				{
					foreach (var r in c.Net.Display?.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
					{
						if (!r.Reached || r.From != c.ObjectId || r.To == c.ObjectId || r.ToKind != "building" || r.To > int.MaxValue || !c.World.Dwellings.ContainsKey((int)r.To))
							continue;
						reached++;
						foreach (var set in DwellingSets(cfg, c.World, (int)r.To))
							units += (int)Math.Floor(set.Weekly * v / 100.0 + 1e-9);
					}
				}
				text = (active ? "+" + units + " unit" + (units == 1 ? "" : "s") + "/week at " + reached + " dwelling" + (reached == 1 ? "" : "s") + " in range (+" + N0(v) + "%)"
				                : "Other dwellings in range: +" + N0(v) + "% units each week") + "; replaces " + weekly + " unit" + (weekly == 1 ? "" : "s") + "/week";
				break;
			}
			default:
				text = null;
				break;
		}
		return text;
	}

	/// <summary>Powered level of <paramref name="e"/> at built level <paramref name="built"/> on this building.</summary>
	private static int PoweredLevel(Ctx c, Cfg.Enhancement e, int built) => c.Net.EffectiveLevel(e, c.ObjectId, built);

	/// <summary>Fills the UX fields of a building view (active effect numbers, option numbers and tags).</summary>
	private static void AddInsights(Ctx c, LogisticsBuildingView view)
	{
		try
		{
			var active = Fx.ActiveEnhancement(c.Config, c.Obj);
			if (active != null)
			{
				var built = Fx.BuiltActiveLevel(c.Obj);
				var eff = PoweredLevel(c, active, built);
				view.ActiveEffectText = EffectText(c, active, eff, true);
				view.ActiveReplacesOutput = ReplacesOutput(active);
				view.ActivePoweredLevel = eff;
			}
			foreach (var o in view.Options ?? Array.Empty<LogisticsOption>())
			{
				var e = c.Config.Get(o.Id);
				if (e == null)
					continue;
				o.ReplacesOutput = ReplacesOutput(e);
				var level = Math.Min(c.Config.MaxLevel, Math.Max(1, o.BuiltLevel + (o.BuiltLevel < c.Config.MaxLevel ? 1 : 0)));
				o.EffectLevel = level;
				o.EffectText = EffectText(c, e, PoweredLevel(c, e, level), false);
			}
			foreach (var b in view.Built ?? Array.Empty<LogisticsEnhancementView>())
			{
				var e = c.Config.Get(b.Id);
				if (e != null && b.Level > 0)
					b.EffectText = EffectText(c, e, PoweredLevel(c, e, b.Level), e.Id == active?.Id);
			}
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogOncePerDay("insights-" + c.ObjectId, "effect numbers for object " + c.ObjectId + " failed: " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- totals

	private static LogisticsTotals Totals(Cfg cfg, Fx.World world, Homm3FactoryLogisticsState.SideState state, Fx.Network net, int side, Fx.Hypothetical hypo)
	{
		var t = new LogisticsTotals { RangeMp = net.LogisticsLevel * cfg.RangeMpPerLevel };
		var active = new Dictionary<int, (Cfg.Enhancement e, int eff)>();
		foreach (var m in Fx.Members(cfg, state, world, side, hypo))
			active[m.o.ObjectId] = (m.e, net.EffectiveLevel(m.e, m.o.ObjectId, m.built));
		double gold = 0;
		foreach (var pair in active)
		{
			if (!world.Mines.TryGetValue(pair.Key, out var mine))
				continue;
			var (e, eff) = pair.Value;
			var resource = Fx.MineResource(mine);
			if (resource == null)
				continue;
			var output = Fx.MineOutput(mine, resource);
			if (e.Effect == "export")
				gold += Fx.ExportGold(cfg, net, world, side, pair.Key, resource, output, eff);
			else if (e.Effect == "byproduct")
			{
				gold += Math.Round(e.ValueAt(eff));
				var extra = output * e.Value2At(eff) / 100.0;
				if (extra > 0)
					t.ResourcesPerDay[resource] = (t.ResourcesPerDay.TryGetValue(resource, out var have) ? have : 0) + extra;
			}
			if (Fx.SuppressesOutput(e) && output > 0)
				t.GivenUpPerDay[resource] = (t.GivenUpPerDay.TryGetValue(resource, out var lost) ? lost : 0) + output;
		}
		var dwellings = new HashSet<int>();
		foreach (var id in active.Keys)
			if (world.Dwellings.ContainsKey(id))
				dwellings.Add(id);
		foreach (var id in net.SupportGrowthPct.Keys)
			dwellings.Add(id);
		foreach (var id in net.DwellingConversion.Keys)
			dwellings.Add(id);
		foreach (var id in dwellings)
		{
			if (!world.Dwellings.TryGetValue(id, out var d) || d.ownerSide != side)
				continue;
			active.TryGetValue(id, out var a);
			var e = a.e;
			if (e != null && e.Effect == "support")
			{
				t.UnitsGivenUpPerWeek += WeeklyUnits(cfg, world, id);
				continue;
			}
			if (e != null && e.Effect == "mercenary")
			{
				t.WeeklyGold += MercenaryGold(cfg, world, net, id, e, a.eff);
				t.UnitsGivenUpPerWeek += WeeklyUnits(cfg, world, id);
				continue;
			}
			var support = net.SupportGrowthPct.TryGetValue(id, out var sp) ? sp : 0.0;
			var share = net.DwellingConversion.TryGetValue(id, out var sh) ? sh : 0.0;
			foreach (var set in DwellingSets(cfg, world, id))
			{
				var add = 0;
				if (e != null && e.Effect == "food")
					add += (int)Math.Floor(set.Weekly * e.ValueAt(a.eff) / 100.0);
				add += (int)Math.Floor(set.Weekly * support / 100.0 + 1e-9);
				t.ExtraUnitsPerWeek += add;
				t.UpgradedPerWeek += (int)Math.Floor((set.Weekly + add) * share);
			}
		}
		t.GoldPerDay = (int)Math.Round(gold);
		t.GoldPerWeek = t.GoldPerDay * 7 + t.WeeklyGold;
		t.AstrologyPerDay = cfg.AstrologyPerTown * net.ArcaneAstrologyTowns;
		return t;
	}

	/// <summary>Network totals for the viewer's totals bar (today's network, the runtime's maths).</summary>
	public static bool TryGetNetworkTotals(out LogisticsTotals totals, out string fail)
	{
		totals = null;
		try
		{
			if (!TryLocalSide(out var side, out fail))
				return false;
			if (!Cfg.TryLoad(out var cfg, out var cfgFail))
				return Fail("configuration not loaded (" + cfgFail + ")", out fail);
			if (!Homm3FactoryLogisticsState.TryGet(side, out var state, out var stateFail))
				return Fail("logistics state unreadable (" + stateFail + ")", out fail);
			if (!Fx.TryBuildWorld(out var world, out var worldFail))
				return Fail("game state unreadable (" + worldFail + ")", out fail);
			totals = Totals(cfg, world, state, Fx.GetNetwork(side), side, null);
			return true;
		}
		catch (Exception ex)
		{
			fail = "totals threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogOncePerDay("totals", fail);
			return false;
		}
	}

	private static bool Fail(string reason, out string fail)
	{
		fail = reason;
		return false;
	}

	// ---------------------------------------------------------------- before / after preview

	private static string NameOf(Ctx c, long key)
	{
		if (key >= Fx.HeroKeyOffset)
		{
			foreach (var h in Fx.SideHeroes(c.World, c.Side))
				if (Fx.HeroId(h) == key - Fx.HeroKeyOffset)
					return Homm3HeroDisplayNames.Resolve(h.configSid);
			return "hero";
		}
		if (key < 0 || key > int.MaxValue)
			return "?";
		var id = (int)key;
		if (c.World.Cities.TryGetValue(id, out var city))
			return TownDisplayName(city.cityName);
		if (c.World.Mines.TryGetValue(id, out var mine))
			return Fx.MineDisplayName(Fx.MineResource(mine));
		if (c.World.Dwellings.TryGetValue(id, out var d) && Fx.TryReadDwellingUnit(d, c.Config, out var sid, out _, out _, out _))
			return Homm3UnitDisplayNames.Resolve(sid) + " Dwelling";
		return "building";
	}

	private static HashSet<(long, long)> ReachedLinks(Fx.Network net)
	{
		var set = new HashSet<(long, long)>();
		foreach (var r in net.Display?.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
			if (r.Reached && r.From != r.To)
				set.Add((r.From, r.To));
		return set;
	}

	private static string Signed(long v) => (v >= 0 ? "+" : "-") + Math.Abs(v).ToString("N0", Inv);

	/// <summary>
	/// Before/after of making <paramref name="enhancementId"/> at <paramref name="level"/> the active enhancement here
	/// (a remote build or a switch lands as the active one tomorrow): income, units, range and the effect links that
	/// appear or vanish. One full network re-solve with the hypothetical state; the viewer caches the lines per option.
	/// </summary>
	public static bool TryPreview(long objectKey, string enhancementId, int level, out string[] lines, out string fail)
	{
		lines = null;
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return false;
			var e = c.Config.Get(enhancementId);
			if (e == null || !Eligible(c, e))
				return Fail("this enhancement cannot be built here", out fail);
			var hypo = new Fx.Hypothetical { ObjectId = c.ObjectId, Code = e.Code, Level = Math.Max(1, Math.Min(c.Config.MaxLevel, level)) };
			var after = Fx.SolveHypothetical(c.Side, hypo);
			var before = c.Net;
			var tb = Totals(c.Config, c.World, c.State, before, c.Side, null);
			var ta = Totals(c.Config, c.World, c.State, after, c.Side, hypo);
			var list = new List<string>();
			if (ta.GoldPerDay != tb.GoldPerDay)
				list.Add("Gold: " + Signed(ta.GoldPerDay - tb.GoldPerDay) + "/day (network " + N0(tb.GoldPerDay) + " -> " + N0(ta.GoldPerDay) + ")");
			if (ta.WeeklyGold != tb.WeeklyGold)
				list.Add("Weekly gold: " + Signed(ta.WeeklyGold - tb.WeeklyGold) + "/week");
			if (ta.ExtraUnitsPerWeek != tb.ExtraUnitsPerWeek)
				list.Add("Extra units: " + Signed(ta.ExtraUnitsPerWeek - tb.ExtraUnitsPerWeek) + "/week");
			if (ta.UnitsGivenUpPerWeek != tb.UnitsGivenUpPerWeek)
				list.Add("Units given up: " + Signed(ta.UnitsGivenUpPerWeek - tb.UnitsGivenUpPerWeek) + "/week");
			if (ta.UpgradedPerWeek != tb.UpgradedPerWeek)
				list.Add("Upgraded units: " + Signed(ta.UpgradedPerWeek - tb.UpgradedPerWeek) + "/week");
			var resources = new SortedSet<string>(StringComparer.Ordinal);
			foreach (var k in ta.ResourcesPerDay.Keys) resources.Add(k);
			foreach (var k in tb.ResourcesPerDay.Keys) resources.Add(k);
			foreach (var k in ta.GivenUpPerDay.Keys) resources.Add(k);
			foreach (var k in tb.GivenUpPerDay.Keys) resources.Add(k);
			foreach (var r in resources)
			{
				var gain = (ta.ResourcesPerDay.TryGetValue(r, out var a1) ? a1 : 0) - (tb.ResourcesPerDay.TryGetValue(r, out var b1) ? b1 : 0);
				var lost = (ta.GivenUpPerDay.TryGetValue(r, out var a2) ? a2 : 0) - (tb.GivenUpPerDay.TryGetValue(r, out var b2) ? b2 : 0);
				var net = gain - lost;
				if (Math.Abs(net) > 0.01)
					list.Add(Res(r) + ": " + (net > 0 ? "+" : "-") + F1(Math.Abs(net)) + "/day");
			}
			if (ta.AstrologyPerDay != tb.AstrologyPerDay)
				list.Add("Astrology: " + Signed(ta.AstrologyPerDay - tb.AstrologyPerDay) + "/day");
			if (ta.RangeMp != tb.RangeMp)
				list.Add("Network range: " + Days(tb.RangeMp) + " -> " + Days(ta.RangeMp));
			var lb = ReachedLinks(before);
			var la = ReachedLinks(after);
			var shown = 0;
			foreach (var link in la)
			{
				if (lb.Contains(link) || shown++ >= 3)
					continue;
				list.Add("New link: " + NameOf(c, link.Item1) + " -> " + NameOf(c, link.Item2));
			}
			shown = 0;
			foreach (var link in lb)
			{
				if (la.Contains(link) || shown++ >= 3)
					continue;
				list.Add("Link lost: " + NameOf(c, link.Item1) + " -> " + NameOf(c, link.Item2));
			}
			if (list.Count == 0)
				list.Add("No change to income, units or links.");
			lines = list.ToArray();
			return true;
		}
		catch (Exception ex)
		{
			fail = "preview threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogOncePerDay("preview", fail);
			return false;
		}
	}

	// ---------------------------------------------------------------- range nodes

	private static Homm3FactoryLogisticsRange.Node NodeOf(Ctx c, int id, int rangeLevels, Cfg.Enhancement e, int eff)
	{
		if (!Fx.TryGetTile(c.World, id, out var x, out var y, out var level))
			return null;
		var hub = e == null ? 0.0 : e.Effect == "route_hub" ? e.ValueAt(eff) : e.Effect == "rail_station" ? 1.0 : 0.0;
		return new Homm3FactoryLogisticsRange.Node { Key = id, Kind = c.World.Cities.ContainsKey(id) ? "town" : "building", X = x, Y = y, Level = level, RangeLevels = rangeLevels, HubRefresh = Math.Min(1.0, hub) };
	}

	/// <summary>Range levels of routes starting at this building (as the effect solves use them).</summary>
	private static int SourceLevels(Ctx c, Cfg.Enhancement e, int eff)
	{
		if (e?.Effect == "power_station")
		{
			var rail = 0;
			foreach (var m in Fx.Members(c.Config, c.State, c.World, c.Side, null))
				if (m.e.Effect == "rail_station")
					rail += m.built;
			return c.Config.BaseLogisticsLevel + rail;
		}
		var own = e?.Effect == "rail_network" ? (int)Math.Round(e.ValueAt(eff)) : 0;
		return c.Net.LogisticsLevel + own;
	}

	private static List<Homm3FactoryLogisticsRange.Node> HubNodes(Fx.Network net)
	{
		var hubs = new List<Homm3FactoryLogisticsRange.Node>();
		foreach (var list in new[] { net.DisplayTargets, net.DisplaySources, net.CaravanHubs })
			foreach (var n in list ?? new List<Homm3FactoryLogisticsRange.Node>())
				if (n != null && n.HubRefresh > 0.0)
					hubs.Add(n);
		return hubs;
	}

	/// <summary>
	/// Range overlay for the viewer: best remaining MP on every tile this building's routes can reach (-1 = not), and
	/// whether a hub refresh got it there. Range = the building's own route range (network range, plus its Rail Network
	/// bonus; a Power Station uses the unpowered range as its solve does). Computed on demand; the viewer caches it.
	/// </summary>
	public static bool TryGetReach(long objectKey, out int[] remaining, out bool[] viaHub, out int width, out int budgetMp, out string fail)
	{
		remaining = null;
		viaHub = null;
		width = 0;
		budgetMp = 0;
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return false;
			var e = Fx.ActiveEnhancement(c.Config, c.Obj);
			var eff = e == null ? 0 : PoweredLevel(c, e, Fx.BuiltActiveLevel(c.Obj));
			var src = NodeOf(c, c.ObjectId, SourceLevels(c, e, eff), null, 0);
			if (src == null)
				return Fail("building tile unknown", out fail);
			budgetMp = src.RangeLevels * c.Config.RangeMpPerLevel;
			return Homm3FactoryLogisticsRange.TryReach(c.Side, src, c.Config.RangeMpPerLevel, HubNodes(c.Net), out remaining, out viaHub, out width, out fail);
		}
		catch (Exception ex)
		{
			fail = "reach threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>Why a route has no path at all (other map level, unexplored fog, guards, water, enclosed).</summary>
	public static bool TryExplainNoPath(long fromKey, string toKind, long toKey, out string reason, out string fail)
	{
		reason = null;
		try
		{
			if (!TryContext(fromKey, out var c, out fail))
				return false;
			if (!Fx.TryGetTile(c.World, c.ObjectId, out var fx, out var fy, out var fl))
				return Fail("building tile unknown", out fail);
			int tx, ty, tl = fl;
			if (toKind == "hero")
			{
				tx = ty = -1;
				foreach (var h in Fx.SideHeroes(c.World, c.Side))
				{
					if (Fx.HeroId(h) == toKey && c.World.MapWidth > 0)
					{
						tx = h.node % c.World.MapWidth;
						ty = h.node / c.World.MapWidth;
					}
				}
				if (tx < 0)
					return Fail("hero not found", out fail);
			}
			else if (toKey < 0 || toKey > int.MaxValue || !Fx.TryGetTile(c.World, (int)toKey, out tx, out ty, out tl))
				return Fail("target tile unknown", out fail);
			if (tl != fl)
			{
				reason = "on another map level";
				return true;
			}
			var from = new Homm3FactoryLogisticsRange.Node { Key = fromKey, Kind = "building", X = fx, Y = fy };
			var to = new Homm3FactoryLogisticsRange.Node { Key = toKey, Kind = toKind, X = tx, Y = ty };
			if (!Homm3FactoryLogisticsRange.TryExplainNoPath(c.Side, from, to, out reason, out fail))
				return false;
			reason ??= "no path found";
			return true;
		}
		catch (Exception ex)
		{
			fail = "explain threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	// ---------------------------------------------------------------- link status (build panel, item 24)

	/// <summary>
	/// Range status of one building for the build panel: "Linked to Castle Town and 2 buildings", or
	/// "Isolated: needs +0.5 day of range to reach Castle Town", or "Isolated: no path to Castle Town (unexplored fog
	/// blocks the way)". Targets: owned towns and the other enhanced buildings, from this building at its route range,
	/// with hubs and Supply Caravan heroes refreshing. One range solve per call (call once when a panel opens).
	/// </summary>
	public static bool TryGetLinkStatus(long objectKey, out string summary, out string fail)
	{
		summary = null;
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return false;
			var active = Fx.ActiveEnhancement(c.Config, c.Obj);
			var eff = active == null ? 0 : PoweredLevel(c, active, Fx.BuiltActiveLevel(c.Obj));
			var src = NodeOf(c, c.ObjectId, SourceLevels(c, active, eff), active, eff);
			if (src == null)
				return Fail("building tile unknown", out fail);
			var targets = new List<Homm3FactoryLogisticsRange.Node>();
			foreach (var city in c.World.Cities.Values)
				if (city.ownerSide == c.Side && NodeOf(c, city.idMapObject, c.Net.LogisticsLevel, null, 0) is { } tn)
					targets.Add(tn);
			foreach (var m in Fx.Members(c.Config, c.State, c.World, c.Side, null))
			{
				if (m.o.ObjectId == c.ObjectId)
					continue;
				var meff = c.Net.EffectiveLevel(m.e, m.o.ObjectId, m.built);
				if (NodeOf(c, m.o.ObjectId, c.Net.LogisticsLevel, m.e, meff) is { } bn)
					targets.Add(bn);
			}
			if (targets.Count == 0)
			{
				summary = "No town or enhanced building to link to yet";
				return true;
			}
			if (!Homm3FactoryLogisticsRange.TrySolve(c.Side, new[] { src }, targets, c.Config.RangeMpPerLevel, out var result, out fail, c.Net.CaravanHubs))
				return false;
			var towns = new List<string>();
			var buildings = 0;
			Homm3FactoryLogisticsRange.Route nearest = null;
			Homm3FactoryLogisticsRange.Route noPath = null;
			foreach (var r in result.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
			{
				if (r.Reached)
				{
					if (r.ToKind == "town")
						towns.Add(NameOf(c, r.To));
					else
						buildings++;
				}
				else if (r.NoPath)
					noPath ??= r;
				else if (nearest == null || r.MissingMp < nearest.MissingMp)
					nearest = r;
			}
			if (towns.Count > 0 || buildings > 0)
			{
				var parts = new List<string>();
				if (towns.Count > 0)
					parts.Add(towns.Count <= 2 ? string.Join(" and ", towns) : towns[0] + ", " + towns[1] + " and " + (towns.Count - 2) + " more town" + (towns.Count == 3 ? "" : "s"));
				if (buildings > 0)
					parts.Add(buildings + " building" + (buildings == 1 ? "" : "s"));
				summary = "Linked to " + string.Join(" and ", parts);
			}
			else if (nearest != null)
				summary = "Isolated: " + NeedsRange(nearest.MissingMp) + " to reach " + NameOf(c, nearest.To);
			else if (noPath != null)
			{
				var why = TryExplainNoPath(objectKey, noPath.ToKind, noPath.To, out var reason, out _) ? reason : null;
				summary = "Isolated: no path to " + NameOf(c, noPath.To) + (why != null ? " (" + why + ")" : "");
			}
			else
				summary = "Isolated";
			return true;
		}
		catch (Exception ex)
		{
			fail = "link status threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogOncePerDay("linkstatus-" + objectKey, fail);
			return false;
		}
	}

	// ---------------------------------------------------------------- recommended enhancement (item 5 data)

	/// <summary>
	/// One recommended enhancement with a one-line reason. Heuristic, in order (first that applies and is eligible):
	/// 1. Gold mine: Logistics Hub (the only option there).
	/// 2. An active enhancement below level 3: upgrade it (it is the one working now).
	/// 3. Mines: an ore mine while the side has no Rail Station: Rail Station; otherwise Byproduct Processing (gold, and the
	///    mine keeps producing).
	/// 4. Dwellings: Food Distribution Center while the side has none; else Rail Network while the side has none; else Food.
	/// False (with the reason) when the active enhancement is already at the top level.
	/// </summary>
	public static bool TryGetRecommendedEnhancement(long objectKey, out string enhancementId, out string reason, out string fail)
	{
		enhancementId = null;
		reason = null;
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return false;
			Cfg.Enhancement ByEffect(string effect)
			{
				foreach (var e in c.Config.Enhancements)
					if (e.Effect == effect && Eligible(c, e))
						return e;
				return null;
			}
			bool SideHas(string effect)
			{
				foreach (var o in c.State.Objects.Values)
				{
					if (Fx.OwnerOf(c.World, o.ObjectId) != c.Side)
						continue;
					foreach (var code in o.Built.Keys)
						if (c.Config.Get(code)?.Effect == effect)
							return true;
				}
				return false;
			}
			Cfg.Enhancement pick;
			if (!c.IsDwelling && c.Resource == "gold")
			{
				pick = ByEffect("route_hub");
				reason = "Gold mines can only build the Logistics Hub; it gives routes passing here their range back.";
			}
			else if (Fx.ActiveEnhancement(c.Config, c.Obj) is { } act)
			{
				if (Fx.BuiltActiveLevel(c.Obj) >= c.Config.MaxLevel)
					return Fail("the active enhancement is fully upgraded", out fail);
				pick = act;
				reason = "Upgrade the active enhancement: it is the one working now.";
			}
			else if (!c.IsDwelling)
			{
				if (c.Resource == GameSymbols.CovePlunder.OreResourceName && !SideHas("rail_station") && ByEffect("rail_station") is { } rail)
				{
					pick = rail;
					reason = "Your first Rail Station adds +" + Days(c.Config.RangeMpPerLevel) + " of range per level to the whole network.";
				}
				else
				{
					pick = ByEffect("byproduct");
					reason = "Adds gold every day and the mine keeps producing (more output at levels 2 and 3).";
				}
			}
			else if (!SideHas("food"))
			{
				pick = ByEffect("food");
				reason = "More units every week, and the dwelling keeps producing.";
			}
			else if (!SideHas("rail_network"))
			{
				pick = ByEffect("rail_network");
				reason = "Lets you hire here from the network viewer and deliver to a town in range.";
			}
			else
			{
				pick = ByEffect("food");
				reason = "More units every week, and the dwelling keeps producing.";
			}
			if (pick == null)
				return Fail("no eligible enhancement", out fail);
			enhancementId = pick.Id;
			return true;
		}
		catch (Exception ex)
		{
			fail = "recommendation threw " + ex.GetBaseException().Message;
			return false;
		}
	}
}
