using System;
using System.Collections.Generic;
using System.Globalization;
using DataHero = Hex.Session.Data.Hero;
using DataObjHire = Hex.Session.Data.ObjHire;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

// Shared API of docs/factory_logistics_runtime_contract.md ("Shared API"): CORE implements, UI consumes.
// Every command validates against the live state, fails closed with a reason and logs under [FactoryLogistics].

internal enum LogisticsBuildingKind { Mine, Dwelling }

internal sealed class LogisticsBuildingView
{
	public long ObjectKey;
	public string DisplayName;
	public LogisticsBuildingKind Kind;
	public string ResourceSid;
	public string UnitSid;
	public int UnitTier;
	public int TileX, TileY, Level;
	/// <summary>Remote build level: max(Upgrade Center, Mobile Command Center hero in range).</summary>
	public int UpgradeCenterLevel;
	/// <summary>The remote build level comes from a Mobile Command Center hero, not this building's Upgrade Center.</summary>
	public bool ViaCommandCenter;
	public bool SwitchUsedThisWeek;
	public string ActiveEnhancementId;
	public string PendingActiveId;
	public IReadOnlyList<LogisticsEnhancementView> Built;
	public IReadOnlyList<LogisticsOption> Options;
	public int PowerStationBonusLevels;
	/// <summary>Arcane Manufactory upgraded stock at this dwelling (empty for mines and dwellings without stock).</summary>
	public IReadOnlyList<LogisticsUpgradedStockView> UpgradedStock;
	/// <summary>Percent of each week's growth an Arcane Manufactory in range converts here (0 = none).</summary>
	public int ConversionPct;
	/// <summary>What the active enhancement does here now, in the runtime's numbers (UX pass; null when none).</summary>
	public string ActiveEffectText;
	/// <summary>The active enhancement stops the building's own production.</summary>
	public bool ActiveReplacesOutput;
	/// <summary>Powered level of the active enhancement (built level + Power Station bonus).</summary>
	public int ActivePoweredLevel;
}

/// <summary>One upgraded unit held in a dwelling's Arcane stock, priced per unit at the dwelling's current charge.</summary>
internal sealed class LogisticsUpgradedStockView
{
	public string UnitSid;
	public int Count;
	public IReadOnlyDictionary<string, int> UnitCost;
	public bool CanAffordOne;
}

/// <summary>What the Rail Network hire tab shows for one unit: stock left, per-unit price, and the most the side can pay for.</summary>
internal sealed class LogisticsHireInfo
{
	public int Available;
	public IReadOnlyDictionary<string, int> UnitCost;
	public int MaxAffordable;
	internal Func<int, IReadOnlyDictionary<string, int>> PriceOf;
}

internal sealed class LogisticsEnhancementView
{
	public string Id;
	public int Level;
	public int PendingLevel;
	/// <summary>What it does here at its built level (numbers), for the switch tab.</summary>
	public string EffectText;
}

internal sealed class LogisticsOption
{
	public string Id, Name;
	public string[] LevelLines;
	public int BuiltLevel;
	public int MaxLevelNow;
	public IReadOnlyDictionary<string, int> NextCost;
	public bool CanAfford;
	public string BlockReason;
	/// <summary>Stops the building's own production ("Replaces output") rather than adding to it.</summary>
	public bool ReplacesOutput;
	/// <summary>Level <see cref="EffectText"/> describes (the next level, or the top level when fully built).</summary>
	public int EffectLevel;
	/// <summary>What the option does here at <see cref="EffectLevel"/>, in the runtime's numbers.</summary>
	public string EffectText;
}

internal sealed class LogisticsRoute
{
	public long FromKey;
	public string ToKind;
	public long ToKey;
	public IReadOnlyList<(int x, int y)> Tiles;
	public bool Cut;
	public bool NoPath;
	public int MissingRangeLevels;
	public int MissingMp;
}

internal sealed class LogisticsBlockingStack
{
	public int TileX, TileY;
	public string Label;
	/// <summary>(from, to) keys of the links defeating this stack would open (hero targets offset like the routes).</summary>
	public IReadOnlyList<(long from, long to)> Links;
}

internal sealed class LogisticsNetworkView
{
	public int LogisticsLevel;
	public int RangeMpPerLevel;
	public IReadOnlyList<LogisticsBuildingView> Buildings;
	public IReadOnlyList<(long key, string name, int x, int y)> Towns, Heroes;
	public IReadOnlyList<LogisticsRoute> Routes;
	public IReadOnlyList<LogisticsBlockingStack> BlockingStacks;
	/// <summary>Town key -> faction sid (from the city-name token, e.g. homm3_factory); hero key -> hero config sid. Marker art only.</summary>
	public IReadOnlyDictionary<long, string> TownFactions, HeroSids;
}

internal static partial class Homm3FactoryLogistics
{
	// Town names are Lang tokens (e.g. homm3_factory_city_name_20 in fractions.json); resolve for the viewer.
	private static readonly Homm3LangTokenFile TownNamesFractions = new("Lang/english/texts/fractions.json", "town names");
	private static readonly Homm3LangTokenFile TownNamesCities = new("Lang/english/texts/cities.json", "town names");

	internal static string TownDisplayName(string cityName)
	{
		if (string.IsNullOrWhiteSpace(cityName))
			return "Town";
		var sid = cityName.Trim();
		return TownNamesFractions.TryGet(sid, out var text) || TownNamesCities.TryGet(sid, out text) ? text : sid;
	}

	/// <summary>A skilled hero of a local human side visited an owned mine or dwelling (raised after the native hire window closed).</summary>
	public static event Action<object, long> VisitRequested;

	public static int MapWidth => Homm3FactoryLogisticsRange.MapWidth;
	public static int MapHeight => Homm3FactoryLogisticsRange.MapHeight;

	private static int _lastSide = -1;

	internal static void RaiseVisit(DataHero hero, long key)
	{
		if (hero != null)
			_lastSide = hero.sideId;
		var handler = VisitRequested;
		if (handler == null)
		{
			Homm3FactoryLogisticsRuntime.LogWarning("visit at object " + key + " has no UI subscriber (Homm3FactoryLogisticsUi.TryRegister not called?).");
			return;
		}
		try
		{
			handler(hero, key);
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogError("VisitRequested handler threw " + ex.GetBaseException().Message);
		}
	}

	internal static void NoteSide(int sideIndex) => _lastSide = sideIndex;

	/// <summary>The local human side the viewer works for: the last side that visited or cast, else the first human side.</summary>
	private static bool TryLocalSide(out int sideIndex, out string fail)
	{
		if (_lastSide >= 0 && Homm3FactoryLogisticsRuntime.IsLocalHuman(_lastSide))
		{
			sideIndex = _lastSide;
			fail = null;
			return true;
		}
		for (var i = 0; i < 8; i++)
		{
			if (Homm3FactoryLogisticsRuntime.IsLocalHuman(i))
			{
				sideIndex = _lastSide = i;
				fail = null;
				return true;
			}
		}
		sideIndex = -1;
		fail = "no local human side found";
		return false;
	}

	public static bool TryGetTerrainTile(int x, int y, int level, out byte terrain, out bool road, out bool water, out bool fogged)
	{
		terrain = 0;
		road = water = fogged = false;
		if (!TryLocalSide(out var side, out _))
			return false;
		return Homm3FactoryLogisticsRange.TryGetTile(x, y, level, side, out terrain, out road, out water, out _, out fogged);
	}

	/// <summary>Resolve the viewer's side once (bulk tile loops call the side-resolved overload below).</summary>
	public static bool TryGetViewerSide(out int sideIndex) => TryLocalSide(out sideIndex, out _);

	/// <summary>Tile read for a side already resolved by <see cref="TryGetViewerSide"/> (no per-tile side lookup).</summary>
	public static bool TryGetTerrainTile(int sideIndex, int x, int y, int level, out byte terrain, out bool road, out bool water, out bool fogged)
		=> TryGetTerrainTile(sideIndex, x, y, level, out terrain, out road, out water, out _, out fogged);

	/// <summary>As above, plus whether an object body / cliff blocks the tile (the viewer draws an obstacle glyph).</summary>
	public static bool TryGetTerrainTile(int sideIndex, int x, int y, int level, out byte terrain, out bool road, out bool water, out bool blocked, out bool fogged)
	{
		terrain = 0;
		road = water = blocked = fogged = false;
		if (sideIndex < 0)
			return false;
		if (!Homm3FactoryLogisticsRange.TryGetTile(x, y, level, sideIndex, out terrain, out road, out water, out blocked, out fogged))
			return false;
		blocked = blocked && !water;
		return true;
	}

	/// <summary>Faction sid from a town-name token ("homm3_factory_city_name_3" -> "homm3_factory"); null when not of that shape.</summary>
	internal static string TownFactionSid(string cityName)
	{
		if (string.IsNullOrWhiteSpace(cityName))
			return null;
		var i = cityName.IndexOf("_city_name", StringComparison.Ordinal);
		return i > 0 ? cityName.Substring(0, i).Trim() : null;
	}

	// ---------------------------------------------------------------- context

	private sealed class Ctx
	{
		internal Homm3FactoryLogisticsConfig Config;
		internal Homm3FactoryLogisticsEffects.World World;
		internal Homm3FactoryLogisticsState.SideState State;
		internal Homm3FactoryLogisticsEffects.Network Net;
		internal int Side;
		internal int ObjectId;
		internal bool IsDwelling;
		internal string Resource;
		internal string UnitSid;
		internal int UnitTier = 1;
		internal string DwellingRare;
		internal Homm3FactoryLogisticsState.ObjectState Obj; // may be a fresh, unsaved record
	}

	private static bool TryContext(long objectKey, out Ctx ctx, out string fail)
	{
		ctx = null;
		if (objectKey < 0 || objectKey > int.MaxValue)
		{
			fail = "invalid object key " + objectKey;
			return false;
		}
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var cfgFail))
		{
			fail = "configuration not loaded (" + cfgFail + ")";
			return false;
		}
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out var worldFail))
		{
			fail = "game state unreadable (" + worldFail + ")";
			return false;
		}
		var id = (int)objectKey;
		var c = new Ctx { Config = config, World = world, ObjectId = id };
		if (world.Mines.TryGetValue(id, out var mine))
		{
			c.Side = mine.ownerSide;
			c.Resource = Homm3FactoryLogisticsEffects.MineResource(mine);
			if (c.Resource == null)
			{
				fail = "mine resource unknown (visit the mine once so its type is read)";
				return false;
			}
		}
		else if (world.Dwellings.TryGetValue(id, out var dwelling))
		{
			c.Side = dwelling.ownerSide;
			c.IsDwelling = true;
			if (!Homm3FactoryLogisticsEffects.TryReadDwellingUnit(dwelling, config, out c.UnitSid, out c.UnitTier, out _, out c.DwellingRare))
			{
				fail = "dwelling unit unreadable";
				return false;
			}
		}
		else
		{
			fail = "object " + id + " is not a mine or dwelling";
			return false;
		}
		if (c.Side < 0 || !Homm3FactoryLogisticsRuntime.IsLocalHuman(c.Side))
		{
			fail = "the building is not owned by a local human player";
			return false;
		}
		if (!Homm3FactoryLogisticsState.TryGet(c.Side, out var state, out var stateFail))
		{
			fail = "logistics state unreadable (" + stateFail + ")";
			return false;
		}
		c.State = state;
		if (Homm3FactoryLogisticsRuntime.Maintain(state, world, config))
			Homm3FactoryLogisticsState.TrySave(state, "maintain", out _);
		c.Obj = state.Objects.TryGetValue(id, out var o) ? o : new Homm3FactoryLogisticsState.ObjectState { ObjectId = id };
		c.Net = Homm3FactoryLogisticsEffects.GetNetwork(c.Side);
		ctx = c;
		fail = null;
		return true;
	}

	private static bool Eligible(Ctx c, Homm3FactoryLogisticsConfig.Enhancement e)
	{
		if (c.IsDwelling)
			return e.Kind == "dwelling" || e.Kind == "any";
		return (e.Kind == "mine" || e.Kind == "any") && e.Resources.Contains(c.Resource);
	}

	private static Dictionary<string, int> NextCost(Ctx c, Homm3FactoryLogisticsConfig.Enhancement e, int level, out string fail)
	{
		var raw = c.Config.CostOf(e, level, c.IsDwelling, c.Resource, c.UnitTier, c.DwellingRare, out fail);
		if (raw == null)
			return null;
		var discount = e.Effect == "warehouse" ? 0.0 : c.Net.WarehouseDiscountPct;
		var cost = Homm3FactoryLogisticsEffects.Discounted(raw, discount);
		// law pass 2026-11-21: Standard Parts (#12), applied after the Warehouse discount
		var parts = Homm3FactoryLawHooks.StandardPartsPercent(c.Side);
		return parts > 0 && cost != null ? Homm3FactoryLogisticsEffects.Discounted(cost, parts) : cost;
	}

	private static int HeroRank(Ctx c, object heroOrNull, out DataHero hero)
	{
		hero = heroOrNull as DataHero;
		if (hero == null || hero.sideId != c.Side)
			return 0;
		return Homm3FactoryLogisticsRuntime.SkillRank(hero, c.Config.SkillSid);
	}

	/// <summary>Remote build level: the building's Upgrade Center, or a Mobile Command Center hero in range if higher.</summary>
	private static int RemoteLevel(Ctx c, out bool viaCommand)
	{
		var command = c.Net.CommandCenterLevel.TryGetValue(c.ObjectId, out var lv) ? lv : 0;
		// law pass 2026-11-21: Telegraph Lines (#5) acts as a remote command level (Basic/Advanced) everywhere
		command = Math.Max(command, Homm3FactoryLawHooks.TelegraphLevel(c.Side));
		viaCommand = command > c.Obj.UpgradeCenter;
		return Math.Max(c.Obj.UpgradeCenter, command);
	}

	private static LogisticsBuildingView BuildView(Ctx c, object heroOrNull)
	{
		var o = c.Obj;
		Homm3FactoryLogisticsEffects.TryGetTile(c.World, c.ObjectId, out var x, out var y, out var level);
		var rank = HeroRank(c, heroOrNull, out _);
		var remote = RemoteLevel(c, out var viaCommand);
		var maxNow = rank > 0 ? rank : remote;
		var built = new List<LogisticsEnhancementView>();
		foreach (var pair in o.Built)
		{
			var e = c.Config.Get(pair.Key);
			if (e != null)
				built.Add(new LogisticsEnhancementView { Id = e.Id, Level = pair.Value.Level, PendingLevel = pair.Value.PendingLevel });
		}
		var options = new List<LogisticsOption>();
		foreach (var e in c.Config.Enhancements)
		{
			if (!Eligible(c, e))
				continue;
			o.Built.TryGetValue(e.Code, out var st);
			var builtLevel = st?.Level ?? 0;
			var option = new LogisticsOption { Id = e.Id, Name = e.Name, LevelLines = e.LevelLines, BuiltLevel = builtLevel, MaxLevelNow = Math.Min(c.Config.MaxLevel, maxNow) };
			var next = builtLevel + 1;
			if (builtLevel >= c.Config.MaxLevel)
				option.BlockReason = "Already at the highest level.";
			else if (st != null && st.PendingLevel > builtLevel)
				option.BlockReason = "Level " + st.PendingLevel + " is under construction (ready tomorrow).";
			else if (next > maxNow)
				option.BlockReason = rank > 0 ? "Needs a hero with a higher Logistics Network level."
					: remote <= 0 ? "No Upgrade Center here: visit with a Logistics Network hero, or bring a Mobile Command Center hero in range."
					: viaCommand ? "Command Center " + remote + " allows remote builds up to level " + remote + "; needs a higher skill."
					: "Upgrade Center " + remote + " allows remote builds up to level " + remote + "; visit with a higher-skilled hero.";
			if (builtLevel < c.Config.MaxLevel)
			{
				var cost = NextCost(c, e, next, out var costFail);
				option.NextCost = cost;
				if (cost == null)
					option.BlockReason ??= "Cost unknown (" + costFail + ").";
				else
				{
					option.CanAfford = Homm3FactoryLogisticsEffects.CanAfford(c.Side, cost, out var missing);
					if (!option.CanAfford)
						option.BlockReason ??= "Not enough " + missing + ".";
				}
			}
			options.Add(option);
		}
		var activeE = Homm3FactoryLogisticsEffects.ActiveEnhancement(c.Config, o);
		return new LogisticsBuildingView
		{
			ObjectKey = c.ObjectId,
			DisplayName = c.IsDwelling ? Homm3UnitDisplayNames.Resolve(c.UnitSid) + " Dwelling" : Homm3FactoryLogisticsEffects.MineDisplayName(c.Resource),
			Kind = c.IsDwelling ? LogisticsBuildingKind.Dwelling : LogisticsBuildingKind.Mine,
			ResourceSid = c.IsDwelling ? null : c.Resource,
			UnitSid = c.UnitSid,
			UnitTier = c.UnitTier,
			TileX = x,
			TileY = y,
			Level = level,
			UpgradeCenterLevel = remote,
			ViaCommandCenter = viaCommand,
			SwitchUsedThisWeek = o.SwitchWeek != 0 && o.SwitchWeek == c.World.WeekId,
			ActiveEnhancementId = activeE?.Id,
			PendingActiveId = o.PendingActiveCode == 0 ? null : c.Config.Get(o.PendingActiveCode)?.Id,
			Built = built,
			Options = options,
			PowerStationBonusLevels = c.Net.PowerBonus.TryGetValue(c.ObjectId, out var pb) ? pb : 0,
			UpgradedStock = UpgradedStockViews(c),
			ConversionPct = c.IsDwelling && c.Net.DwellingConversion.TryGetValue(c.ObjectId, out var share) ? (int)Math.Round(share * 100.0) : 0,
		};
	}

	public static bool TryGetBuilding(long objectKey, object heroOrNull, out LogisticsBuildingView view, out string fail)
	{
		view = null;
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return false;
			_lastSide = c.Side;
			view = BuildView(c, heroOrNull);
			AddInsights(c, view);
			return true;
		}
		catch (Exception ex)
		{
			fail = "building read threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogError(fail);
			return false;
		}
	}

	public static bool TryGetNetwork(out LogisticsNetworkView view, out string fail)
	{
		view = null;
		try
		{
			if (!TryLocalSide(out var side, out fail))
				return false;
			if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var cfgFail))
			{
				fail = "configuration not loaded (" + cfgFail + ")";
				return false;
			}
			if (!Homm3FactoryLogisticsState.TryGet(side, out var state, out var stateFail))
			{
				fail = "logistics state unreadable (" + stateFail + ")";
				return false;
			}
			if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out var worldFail))
			{
				fail = "game state unreadable (" + worldFail + ")";
				return false;
			}
			if (Homm3FactoryLogisticsRuntime.Maintain(state, world, config))
				Homm3FactoryLogisticsState.TrySave(state, "maintain", out _);
			var net = Homm3FactoryLogisticsEffects.GetNetwork(side, force: true);
			var buildings = new List<LogisticsBuildingView>();
			var names = new Dictionary<long, string>();
			foreach (var id in new List<int>(state.Objects.Keys))
			{
				if (!TryContext(id, out var c, out var cFail))
				{
					Homm3FactoryLogisticsRuntime.LogOncePerDay("netview-" + id, "network view skips object " + id + ": " + cFail);
					continue;
				}
				var b = BuildView(c, null);
				AddInsights(c, b);
				buildings.Add(b);
				names[id] = b.DisplayName;
			}
			var towns = new List<(long key, string name, int x, int y)>();
			var townFactions = new Dictionary<long, string>();
			var heroSids = new Dictionary<long, string>();
			foreach (var city in world.Cities.Values)
			{
				if (city.ownerSide != side || !Homm3FactoryLogisticsEffects.TryGetTile(world, city.idMapObject, out var tx, out var ty, out _))
					continue;
				var name = TownDisplayName(city.cityName);
				towns.Add((city.idMapObject, name, tx, ty));
				var faction = TownFactionSid(city.cityName);
				if (faction != null)
					townFactions[city.idMapObject] = faction;
				names[city.idMapObject] = name;
			}
			var heroes = new List<(long key, string name, int x, int y)>();
			foreach (var hero in Homm3FactoryLogisticsEffects.SideHeroes(world, side))
			{
				var id = Homm3FactoryLogisticsEffects.HeroId(hero);
				if (id < 0 || world.MapWidth <= 0)
					continue;
				var name = Homm3HeroDisplayNames.Resolve(hero.configSid);
				heroes.Add((id, name, hero.node % world.MapWidth, hero.node / world.MapWidth));
				if (!string.IsNullOrWhiteSpace(hero.configSid))
					heroSids[id] = hero.configSid;
				names[Homm3FactoryLogisticsEffects.HeroKeyOffset + id] = name;
			}
			var routes = new List<LogisticsRoute>();
			var stacks = new List<LogisticsBlockingStack>();
			if (net.Display != null)
			{
				foreach (var r in net.Display.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
				{
					var isHero = r.To >= Homm3FactoryLogisticsEffects.HeroKeyOffset;
					routes.Add(new LogisticsRoute
					{
						FromKey = r.From,
						ToKind = isHero ? "hero" : r.ToKind ?? "building",
						ToKey = isHero ? r.To - Homm3FactoryLogisticsEffects.HeroKeyOffset : r.To,
						Tiles = r.Tiles ?? new List<(int x, int y)>(),
						Cut = !r.Reached && !r.NoPath,
						NoPath = r.NoPath,
						MissingMp = r.Reached ? 0 : r.MissingMp,
						MissingRangeLevels = r.Reached || r.NoPath ? 0 : (r.MissingMp + config.RangeMpPerLevel - 1) / Math.Max(1, config.RangeMpPerLevel),
					});
				}
				foreach (var bl in net.Display.Blockers ?? new List<Homm3FactoryLogisticsRange.Blocker>())
				{
					var link = bl.WouldLink != null && bl.WouldLink.Count > 0 ? bl.WouldLink[0] : (0L, 0L);
					var from = names.TryGetValue(link.Item1, out var fn) ? fn : "building";
					var to = names.TryGetValue(link.Item2, out var tn) ? tn : "target";
					stacks.Add(new LogisticsBlockingStack { TileX = bl.X, TileY = bl.Y, Links = bl.WouldLink != null ? new List<(long, long)>(bl.WouldLink) : new List<(long, long)>(), Label =  "Defeat to link " + from + " -> " + to + (bl.WouldLink != null && bl.WouldLink.Count > 1 ? " (+" + (bl.WouldLink.Count - 1) + " more)" : "") });
				}
			}
			view = new LogisticsNetworkView
			{
				LogisticsLevel = net.LogisticsLevel,
				RangeMpPerLevel = config.RangeMpPerLevel,
				Buildings = buildings,
				Towns = towns,
				Heroes = heroes,
				TownFactions = townFactions,
				HeroSids = heroSids,
				Routes = routes,
				BlockingStacks = stacks,
			};
			if (!net.RangeOk)
				Homm3FactoryLogisticsRuntime.LogOncePerDay("netview-range", "network view without routes: " + net.RangeFail);
			return true;
		}
		catch (Exception ex)
		{
			fail = "network read threw " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogError(fail);
			return false;
		}
	}

	// ---------------------------------------------------------------- commands

	private static bool Commit(Ctx c, string why, out string fail)
	{
		c.State.Objects[c.ObjectId] = c.Obj;
		if (!Homm3FactoryLogisticsState.TrySave(c.State, why, out fail))
		{
			fail = "saving failed (" + fail + ")";
			return false;
		}
		Homm3FactoryLogisticsEffects.InvalidateNetwork();
		Homm3FactoryLogisticsRange.Invalidate();
		var net = Homm3FactoryLogisticsEffects.GetNetwork(c.Side, force: true);
		Homm3FactoryLogisticsRuntime.ApplyHousing(c.Config, c.World, c.State, net);
		Homm3FactoryLogisticsRuntime.RefreshArcaneForCachedHeroes(c.Side);
		Homm3FactoryLogisticsState.TrySave(c.State, why + " (housing)", out _);
		return true;
	}

	public static bool TryBuild(long objectKey, string enhancementId, object heroOrNull, out string fail)
	{
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return Refuse("build " + enhancementId + " at " + objectKey, fail);
			var e = c.Config.Get(enhancementId);
			if (e == null || !Eligible(c, e))
				return Refuse("build " + enhancementId + " at " + objectKey, fail = "this enhancement cannot be built here");
			var rank = HeroRank(c, heroOrNull, out var hero);
			var onSite = rank > 0;
			if (heroOrNull != null && !onSite)
				return Refuse("build " + e.Id, fail = "the visiting hero does not have Logistics Network");
			var cap = onSite ? rank : RemoteLevel(c, out _);
			c.Obj.Built.TryGetValue(e.Code, out var st);
			var builtLevel = st?.Level ?? 0;
			var next = builtLevel + 1;
			if (builtLevel >= c.Config.MaxLevel)
				return Refuse("build " + e.Id, fail = "already at the highest level");
			if (st != null && st.PendingLevel > builtLevel)
				return Refuse("build " + e.Id, fail = "a level is already under construction");
			if (next > cap)
				return Refuse("build " + e.Id, fail = onSite ? "the hero's skill level is too low" : cap <= 0 ? "no Upgrade Center here: a Logistics Network hero must visit (or a Mobile Command Center hero be in range)" : "remote build allows level " + cap + " here (Upgrade Center / Command Center " + cap + ")");
			var cost = NextCost(c, e, next, out var costFail);
			if (cost == null)
				return Refuse("build " + e.Id, fail = "cost unknown (" + costFail + ")");
			if (!Homm3FactoryLogisticsEffects.TryCharge(c.Side, cost, out var chargeFail))
				return Refuse("build " + e.Id, fail = chargeFail);
			if (st == null)
				c.Obj.Built[e.Code] = st = new Homm3FactoryLogisticsState.EnhState();
			var undoLevel = st.Level;
			var undoActive = c.Obj.ActiveCode;
			if (onSite)
			{
				st.Level = next;
				if (c.Obj.ActiveCode == 0)
					c.Obj.ActiveCode = e.Code;
				if (c.Obj.UpgradeCenter < rank)
					c.Obj.UpgradeCenter = rank;
			}
			else
			{
				st.PendingLevel = next;
				st.PendingDay = c.World.Day;
			}
			if (!Commit(c, "build " + e.Id, out fail))
			{
				st.Level = undoLevel;
				st.PendingLevel = 0;
				c.Obj.ActiveCode = undoActive;
				foreach (var pair in cost)
					Homm3FactoryLogisticsEffects.TryAddResource(c.Side, pair.Key, pair.Value, out _);
				return Refuse("build " + e.Id, fail + "; cost refunded");
			}
			if (onSite)
				Homm3FactoryLogisticsRuntime.OnLevelApplied(c.Config, c.World, c.State, c.Obj, e.Code, undoLevel);
			Homm3FactoryLogisticsRuntime.LogEvent((onSite ? "built " : "remote build ordered ") + e.Id + " L" + next + " at object " + c.ObjectId + " for " + Homm3FactoryLogisticsEffects.FormatCost(cost)
				+ (onSite ? " by hero " + hero.configSid : " (ready day " + (c.World.Day + 1) + ")") + ".");
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			return Refuse("build " + enhancementId, fail = "build threw " + ex.GetBaseException().Message);
		}
	}

	public static bool TrySetActive(long objectKey, string enhancementId, out string fail)
	{
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return Refuse("set active " + enhancementId, fail);
			var e = c.Config.Get(enhancementId);
			if (e == null || !c.Obj.Built.TryGetValue(e.Code, out var st) || st.Level <= 0)
				return Refuse("set active " + enhancementId, fail = "that enhancement is not built here");
			var o = c.Obj;
			if (o.ActiveCode == 0)
			{
				o.ActiveCode = e.Code;
				o.PendingActiveCode = 0;
			}
			else if (o.ActiveCode == e.Code)
			{
				if (o.PendingActiveCode == 0)
					return Refuse("set active " + e.Id, fail = "it is already active");
				o.PendingActiveCode = 0; // cancel the pending switch (the weekly switch stays used)
			}
			else
			{
				if (o.SwitchWeek != 0 && o.SwitchWeek == c.World.WeekId && o.PendingActiveCode == 0)
					return Refuse("set active " + e.Id, fail = "this building already switched this week");
				o.PendingActiveCode = e.Code;
				o.PendingActiveDay = c.World.Day;
				o.SwitchWeek = c.World.WeekId;
			}
			if (!Commit(c, "set active " + e.Id, out fail))
				return Refuse("set active " + e.Id, fail);
			Homm3FactoryLogisticsRuntime.LogEvent("object " + c.ObjectId + ": active " + Homm3FactoryLogisticsRuntime.Name(c.Config, o.ActiveCode) + ", pending " + Homm3FactoryLogisticsRuntime.Name(c.Config, o.PendingActiveCode) + ".");
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			return Refuse("set active " + enhancementId, fail = "switch threw " + ex.GetBaseException().Message);
		}
	}

	public static bool TryDemolish(long objectKey, string enhancementId, out string fail)
	{
		try
		{
			if (!TryContext(objectKey, out var c, out fail))
				return Refuse("demolish " + enhancementId, fail);
			var e = c.Config.Get(enhancementId);
			if (e == null || !c.Obj.Built.Remove(e.Code))
				return Refuse("demolish " + enhancementId, fail = "that enhancement is not built here");
			if (c.Obj.ActiveCode == e.Code)
				c.Obj.ActiveCode = 0;
			if (c.Obj.PendingActiveCode == e.Code)
				c.Obj.PendingActiveCode = 0;
			if (!Commit(c, "demolish " + e.Id, out fail))
				return Refuse("demolish " + e.Id, fail);
			Homm3FactoryLogisticsRuntime.LogEvent("demolished " + e.Id + " at object " + c.ObjectId + " (no refund).");
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			return Refuse("demolish " + enhancementId, fail = "demolish threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Rail Network remote hire: buys <paramref name="count"/> units from the dwelling's stock at its current price
	/// (Housing Office included) and writes them into one army. A hero target delivers to that hero. A town target
	/// delivers to the first army, in this order, that exists, is readable and can take the units (an existing stack of
	/// the same sid, else an empty slot of 7): (1) the garrison hero, (2) the town's own heroless garrison, (3) the
	/// visiting hero. Fails closed: the target is chosen and checked before anything is charged; a refused write refunds
	/// the cost and the dwelling stock only drops after a verified write.
	/// </summary>
	public static bool TryRemoteHire(long dwellingKey, string unitSid, int count, string targetKind, long targetKey, out string fail)
	{
		var what = "remote hire " + count + "x " + unitSid + " from " + dwellingKey + " to " + targetKind + " " + targetKey;
		try
		{
			if (count <= 0)
				return Refuse(what, fail = "count must be positive");
			if (!TryContext(dwellingKey, out var c, out fail))
				return Refuse(what, fail);
			if (!c.IsDwelling || !c.World.Dwellings.TryGetValue(c.ObjectId, out var dwelling))
				return Refuse(what, fail = "not a dwelling");
			var e = Homm3FactoryLogisticsEffects.ActiveEnhancement(c.Config, c.Obj);
			if (e == null || e.Effect != "rail_network")
				return Refuse(what, fail = "the Rail Network is not the active enhancement here");
			var eff = c.Net.EffectiveLevel(e, c.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(c.Obj));
			long reachKey;
			// Delivery candidates in order: a hero (Hero set, or HeroId of a missing one) or the town garrison (Town set).
			var candidates = new List<(string Label, DataHero Hero, int HeroId, Hex.Session.Data.ObjCity Town)>();
			DataHero FindHero(int id)
			{
				if (id < 0)
					return null;
				foreach (var h in Homm3FactoryLogisticsEffects.SideHeroes(c.World, c.Side))
				{
					if (Homm3FactoryLogisticsEffects.HeroId(h) == id)
						return h;
				}
				return null;
			}
			if (targetKind == "hero")
			{
				if (eff < Math.Max(1, e.HeroDeliveryLevel))
					return Refuse(what, fail = "delivering to a hero needs Rail Network level " + e.HeroDeliveryLevel);
				reachKey = Homm3FactoryLogisticsEffects.HeroKeyOffset + targetKey;
				var targetHero = targetKey is >= 0 and <= int.MaxValue ? FindHero((int)targetKey) : null;
				if (targetHero == null)
					return Refuse(what, fail = "target hero not found");
				candidates.Add(("hero", targetHero, (int)targetKey, null));
			}
			else if (targetKind == "town")
			{
				reachKey = targetKey;
				if (targetKey is < int.MinValue or > int.MaxValue || !c.World.Cities.TryGetValue((int)targetKey, out var city) || city.ownerSide != c.Side)
					return Refuse(what, fail = "that town is not yours");
				if (city.garnisonHeroId >= 0)
					candidates.Add(("garrison hero", FindHero(city.garnisonHeroId), city.garnisonHeroId, null));
				candidates.Add(("town garrison", null, -1, city));
				if (city.visitorHeroId >= 0 && city.visitorHeroId != city.garnisonHeroId)
					candidates.Add(("visiting hero", FindHero(city.visitorHeroId), city.visitorHeroId, null));
			}
			else
			{
				return Refuse(what, fail = "unknown target kind " + targetKind);
			}
			if (!c.Net.RailReach.TryGetValue(c.ObjectId, out var reach) || !reach.Contains(reachKey))
				return Refuse(what, fail = c.Net.RangeOk ? "the target is not in this dwelling's logistics range" : "logistics range unavailable (" + c.Net.RangeFail + ")");
			var sets = dwelling.assortmentData?.unitSets;
			Hex.Session.Data.HiredUnitSet set = null;
			for (var i = 0; sets != null && i < sets.Count && set == null; i++)
			{
				var s = sets[i];
				for (var j = 0; s?.sids != null && j < s.sids.Count; j++)
				{
					if (s.sids[j] == unitSid)
					{
						set = s;
						break;
					}
				}
			}
			if (set == null)
				return Refuse(what, fail = "this dwelling does not offer " + unitSid);
			if (set.currentAmount < count)
				return Refuse(what, fail = "only " + set.currentAmount + " available");
			var unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unitSid);
			if (unit == null)
				return Refuse(what, fail = "unit config " + unitSid + " not found");
			var factor = Math.Max(Homm3FactoryLogisticsRuntime.MinPriceFactor, 1.0 + dwelling.assortmentData.extraCharge);
			var cost = new Dictionary<string, int>(StringComparer.Ordinal);
			var costs = unit.unitCost?.costResArray;
			for (var i = 0; costs != null && i < costs.Length; i++)
			{
				var name = costs[i]?.name?.Trim();
				if (name == null || Homm3TowerArtificingRuntime.ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is not int amount || amount <= 0)
					continue;
				cost[name] = (cost.TryGetValue(name, out var have) ? have : 0) + (int)Math.Ceiling(amount * (double)count * factor - 1e-9);
			}

			// The first candidate that can take the units; read and slot-checked before anything is charged.
			string label = null;
			LogicHero logicHero = null;
			DataHero hero = null;
			object townParty = null;
			string[] slotSid = null;
			int[] slotCount = null;
			Dictionary<string, int> totals = null;
			var slot = -1;
			var skipped = new List<string>();
			foreach (var cand in candidates)
			{
				string[] sids;
				int[] counts;
				Dictionary<string, int> tot;
				string readFail;
				LogicHero lh = null;
				object party = null;
				if (cand.Town != null)
				{
					if (!Homm3FactoryLogisticsGarrison.TryGetTownGarrisonParty(cand.Town, out party, out var partyFail))
					{
						skipped.Add(cand.Label + ": " + partyFail);
						continue;
					}
					if (!Homm3PartyArmyWriter.TryReadPartyArmy(party, out sids, out counts, out tot, out readFail))
					{
						skipped.Add(cand.Label + ": army unreadable (" + readFail + ")");
						continue;
					}
				}
				else
				{
					if (cand.Hero == null)
					{
						skipped.Add(cand.Label + ": hero " + cand.HeroId + " not found");
						continue;
					}
					lh = Homm3FactoryLogisticsRuntime.CachedLogicHero(cand.Hero);
					if (lh == null)
					{
						skipped.Add(cand.Label + ": army not reachable yet (select or move the hero once, or wait for the next day)");
						continue;
					}
					if (!Homm3PartyArmyWriter.TryReadArmy(lh, cand.Hero, out sids, out counts, out tot, out readFail))
					{
						skipped.Add(cand.Label + ": army unreadable (" + readFail + ")");
						continue;
					}
				}
				var at = Array.IndexOf(sids, unitSid);
				if (at < 0)
					at = Array.FindIndex(sids, string.IsNullOrEmpty);
				if (at < 0)
				{
					skipped.Add(cand.Label + ": no free slot");
					continue;
				}
				label = cand.Label;
				hero = cand.Hero;
				logicHero = lh;
				townParty = party;
				slotSid = sids;
				slotCount = counts;
				totals = tot;
				slot = at;
				break;
			}
			if (label == null)
				return Refuse(what, fail = (candidates.Count == 1 ? "" : "no army here can take the units: ") + string.Join("; ", skipped));
			if (skipped.Count > 0)
				Homm3FactoryLogisticsRuntime.LogInfo(what + ": delivering to the " + label + " (skipped " + string.Join("; ", skipped) + ").");

			if (!Homm3FactoryLogisticsEffects.TryCharge(c.Side, cost, out var chargeFail))
				return Refuse(what, fail = chargeFail);
			var newSid = (string[])slotSid.Clone();
			var newCount = (int[])slotCount.Clone();
			newSid[slot] = unitSid;
			newCount[slot] = (string.IsNullOrEmpty(slotSid[slot]) ? 0 : slotCount[slot]) + count;
			var steps = new List<string>();
			string writeFail;
			var result = townParty != null
				? Homm3PartyArmyWriter.WritePartyArmy(townParty, newSid, newCount, totals, steps, out writeFail)
				: Homm3PartyArmyWriter.Write(logicHero, hero, newSid, newCount, totals, steps, out writeFail);
			if (result != Homm3PartyArmyWriter.WriteResult.Written)
			{
				if (result == Homm3PartyArmyWriter.WriteResult.Refused)
				{
					foreach (var pair in cost)
						Homm3FactoryLogisticsEffects.TryAddResource(c.Side, pair.Key, pair.Value, out _);
					return Refuse(what, fail = "army write refused (" + writeFail + "); cost refunded");
				}
				Homm3FactoryLogisticsRuntime.LogError(what + ": " + label + " army write " + result + " (" + writeFail + "); steps " + string.Join(", ", steps) + ". Cost kept, stock unchanged.");
				fail = "the army write did not complete (" + result + ")";
				return false;
			}
			set.currentAmount -= count;
			Homm3FactoryLogisticsRuntime.LogEvent(what + ": delivered to the " + label + (hero != null ? " " + hero.configSid : "") + " slot " + slot + " for " + Homm3FactoryLogisticsEffects.FormatCost(cost) + " (stock now " + set.currentAmount + ").");
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			return Refuse(what, fail = "remote hire threw " + ex.GetBaseException().Message);
		}
	}

	private static bool Refuse(string what, string fail)
	{
		Homm3FactoryLogisticsRuntime.LogWarning(what + " refused: " + fail);
		return false;
	}

	// ---------------------------------------------------------------- Arcane upgraded stock (DECISIONS.md #56-#59)

	/// <summary>The unit set and upgraded sid a pool key names, or null when the dwelling no longer offers it.</summary>
	private static Hex.Session.Data.HiredUnitSet UpgradedStockSet(DataObjHire dwelling, int poolKey, out string sid)
	{
		sid = null;
		var sets = dwelling?.assortmentData?.unitSets;
		var setIndex = poolKey & 7;
		var sidIndex = poolKey >> 3;
		if (sets == null || setIndex >= sets.Count || sets[setIndex]?.sids == null || sidIndex < 1 || sidIndex >= sets[setIndex].sids.Count)
			return null;
		sid = sets[setIndex].sids[sidIndex];
		return string.IsNullOrEmpty(sid) ? null : sets[setIndex];
	}

	/// <summary>Native hire price factor (Housing Office included) with the remote-hire floor (DECISIONS.md #45).</summary>
	private static double UpgradedPriceFactor(DataObjHire dwelling) =>
		Math.Max(Homm3FactoryLogisticsRuntime.MinPriceFactor, 1.0 + dwelling.assortmentData.extraCharge);

	private static Dictionary<string, int> UpgradedPrice(Hex.Configs.UnitLogicConfig unit, int count, double factor)
	{
		var cost = new Dictionary<string, int>(StringComparer.Ordinal);
		var costs = unit.unitCost?.costResArray;
		for (var i = 0; costs != null && i < costs.Length; i++)
		{
			var name = costs[i]?.name?.Trim();
			if (name == null || Homm3TowerArtificingRuntime.ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is not int amount || amount <= 0)
				continue;
			cost[name] = (cost.TryGetValue(name, out var have) ? have : 0) + (int)Math.Ceiling(amount * (double)count * factor - 1e-9);
		}
		return cost;
	}

	private static List<LogisticsUpgradedStockView> UpgradedStockViews(Ctx c)
	{
		var list = new List<LogisticsUpgradedStockView>();
		if (!c.IsDwelling || c.Obj.UpgradedPool.Count == 0 || !c.World.Dwellings.TryGetValue(c.ObjectId, out var dwelling))
			return list;
		var factor = UpgradedPriceFactor(dwelling);
		foreach (var pair in c.Obj.UpgradedPool)
		{
			if (pair.Value <= 0 || UpgradedStockSet(dwelling, pair.Key, out var sid) == null)
				continue;
			var unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
			var cost = unit == null ? null : UpgradedPrice(unit, 1, factor);
			list.Add(new LogisticsUpgradedStockView
			{
				UnitSid = sid,
				Count = pair.Value,
				UnitCost = cost,
				CanAffordOne = cost != null && Homm3FactoryLogisticsEffects.CanAfford(c.Side, cost, out _),
			});
		}
		return list;
	}

	/// <summary>
	/// Read-only numbers for the Rail Network hire tab: the dwelling's stock of <paramref name="unitSid"/> (its own
	/// assortment, or the Arcane upgraded stock), the price per unit and for n units with the same factor and rounding
	/// TryRemoteHire / TryRemoteHireUpgraded charge, and the largest count the side can afford out of that stock.
	/// </summary>
	public static bool TryGetHireInfo(long dwellingKey, string unitSid, bool upgraded, out LogisticsHireInfo info, out string fail)
	{
		info = null;
		try
		{
			if (string.IsNullOrEmpty(unitSid))
			{
				fail = "no unit";
				return false;
			}
			if (!TryContext(dwellingKey, out var c, out fail))
				return false;
			if (!c.IsDwelling || !c.World.Dwellings.TryGetValue(c.ObjectId, out var dwelling))
			{
				fail = "not a dwelling";
				return false;
			}
			var unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unitSid);
			if (unit == null)
			{
				fail = "unit config " + unitSid + " not found";
				return false;
			}
			var available = 0;
			if (upgraded)
			{
				foreach (var pair in c.Obj.UpgradedPool)
				{
					if (pair.Value > 0 && UpgradedStockSet(dwelling, pair.Key, out var sid) != null && sid == unitSid)
						available += pair.Value;
				}
			}
			else
			{
				var sets = dwelling.assortmentData?.unitSets;
				for (var i = 0; sets != null && i < sets.Count; i++)
				{
					var s = sets[i];
					for (var j = 0; s?.sids != null && j < s.sids.Count; j++)
					{
						if (s.sids[j] == unitSid)
						{
							available = Math.Max(0, s.currentAmount);
							i = sets.Count;
							break;
						}
					}
				}
			}
			var factor = UpgradedPriceFactor(dwelling);
			var side = c.Side;
			int lo = 0, hi = available;
			while (lo < hi)
			{
				var mid = (lo + hi + 1) / 2;
				if (Homm3FactoryLogisticsEffects.CanAfford(side, UpgradedPrice(unit, mid, factor), out _))
					lo = mid;
				else
					hi = mid - 1;
			}
			info = new LogisticsHireInfo
			{
				Available = available,
				UnitCost = UpgradedPrice(unit, 1, factor),
				MaxAffordable = lo,
				PriceOf = n => UpgradedPrice(unit, Math.Max(0, n), factor),
			};
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			fail = "hire info failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>
	/// Arcane upgraded stock bought by the hero visiting the dwelling (upgrade panel): <paramref name="count"/> units of
	/// <paramref name="unitSid"/> from this dwelling's upgraded stock into that hero's army.
	/// </summary>
	public static bool TryHireUpgradedOnSite(long dwellingKey, string unitSid, int count, object heroOrNull, out string fail)
	{
		var what = "upgraded hire " + count + "x " + unitSid + " at " + dwellingKey;
		try
		{
			if (count <= 0)
				return Refuse(what, fail = "count must be positive");
			if (!TryContext(dwellingKey, out var c, out fail))
				return Refuse(what, fail);
			if (!c.IsDwelling)
				return Refuse(what, fail = "not a dwelling");
			if (heroOrNull is not DataHero hero || hero.sideId != c.Side)
				return Refuse(what, fail = "no hero of yours is visiting");
			var candidates = new List<(string Label, DataHero Hero, int HeroId, Hex.Session.Data.ObjCity Town)>
			{
				("visiting hero", hero, Homm3FactoryLogisticsEffects.HeroId(hero), null),
			};
			return TryTakeUpgraded(c, what, unitSid, count, candidates, out fail);
		}
		catch (Exception ex)
		{
			return Refuse(what, fail = "upgraded hire threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Arcane upgraded stock bought through the Rail Network (viewer Hire tab). Same target rules as
	/// <see cref="TryRemoteHire"/>: a hero needs the Rail Network's hero level and must be in Rail reach; a town in
	/// reach delivers to its garrison hero, else its garrison, else its visiting hero (first that can take the units).
	/// </summary>
	public static bool TryRemoteHireUpgraded(long dwellingKey, string unitSid, int count, string targetKind, long targetKey, out string fail)
	{
		var what = "remote upgraded hire " + count + "x " + unitSid + " from " + dwellingKey + " to " + targetKind + " " + targetKey;
		try
		{
			if (count <= 0)
				return Refuse(what, fail = "count must be positive");
			if (!TryContext(dwellingKey, out var c, out fail))
				return Refuse(what, fail);
			if (!c.IsDwelling)
				return Refuse(what, fail = "not a dwelling");
			var e = Homm3FactoryLogisticsEffects.ActiveEnhancement(c.Config, c.Obj);
			if (e == null || e.Effect != "rail_network")
				return Refuse(what, fail = "the Rail Network is not the active enhancement here");
			var eff = c.Net.EffectiveLevel(e, c.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(c.Obj));
			var candidates = new List<(string Label, DataHero Hero, int HeroId, Hex.Session.Data.ObjCity Town)>();
			DataHero FindHero(int id)
			{
				if (id < 0)
					return null;
				foreach (var h in Homm3FactoryLogisticsEffects.SideHeroes(c.World, c.Side))
				{
					if (Homm3FactoryLogisticsEffects.HeroId(h) == id)
						return h;
				}
				return null;
			}
			long reachKey;
			if (targetKind == "hero")
			{
				if (eff < Math.Max(1, e.HeroDeliveryLevel))
					return Refuse(what, fail = "delivering to a hero needs Rail Network level " + e.HeroDeliveryLevel);
				reachKey = Homm3FactoryLogisticsEffects.HeroKeyOffset + targetKey;
				var targetHero = targetKey is >= 0 and <= int.MaxValue ? FindHero((int)targetKey) : null;
				if (targetHero == null)
					return Refuse(what, fail = "target hero not found");
				candidates.Add(("hero", targetHero, (int)targetKey, null));
			}
			else if (targetKind == "town")
			{
				reachKey = targetKey;
				if (targetKey is < int.MinValue or > int.MaxValue || !c.World.Cities.TryGetValue((int)targetKey, out var city) || city.ownerSide != c.Side)
					return Refuse(what, fail = "that town is not yours");
				if (city.garnisonHeroId >= 0)
					candidates.Add(("garrison hero", FindHero(city.garnisonHeroId), city.garnisonHeroId, null));
				candidates.Add(("town garrison", null, -1, city));
				if (city.visitorHeroId >= 0 && city.visitorHeroId != city.garnisonHeroId)
					candidates.Add(("visiting hero", FindHero(city.visitorHeroId), city.visitorHeroId, null));
			}
			else
			{
				return Refuse(what, fail = "unknown target kind " + targetKind);
			}
			if (!c.Net.RailReach.TryGetValue(c.ObjectId, out var reach) || !reach.Contains(reachKey))
				return Refuse(what, fail = c.Net.RangeOk ? "the target is not in this dwelling's logistics range" : "logistics range unavailable (" + c.Net.RangeFail + ")");
			return TryTakeUpgraded(c, what, unitSid, count, candidates, out fail);
		}
		catch (Exception ex)
		{
			return Refuse(what, fail = "remote upgraded hire threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Picks the first candidate army that can take the units (read and slot-checked before charging), charges the
	/// upgraded price, writes the army, then takes the units out of the upgraded stock and saves (UI command = safe
	/// point). Write Refused refunds; WriteFailed / ReadBackMismatch keep the cost and the stock (as remote hire).
	/// </summary>
	private static bool TryTakeUpgraded(Ctx c, string what, string unitSid, int count,
		List<(string Label, DataHero Hero, int HeroId, Hex.Session.Data.ObjCity Town)> candidates, out string fail)
	{
		if (!c.World.Dwellings.TryGetValue(c.ObjectId, out var dwelling))
			return Refuse(what, fail = "not a dwelling");
		var key = -1;
		foreach (var pair in c.Obj.UpgradedPool)
		{
			if (pair.Value > 0 && UpgradedStockSet(dwelling, pair.Key, out var sid) != null && sid == unitSid)
			{
				key = pair.Key;
				break;
			}
		}
		if (key < 0)
			return Refuse(what, fail = "no upgraded " + Homm3UnitDisplayNames.Resolve(unitSid) + " in stock here");
		var have = c.Obj.UpgradedPool[key];
		if (have < count)
			return Refuse(what, fail = "only " + have + " in upgraded stock");
		var unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unitSid);
		if (unit == null)
			return Refuse(what, fail = "unit config " + unitSid + " not found");
		var cost = UpgradedPrice(unit, count, UpgradedPriceFactor(dwelling));

		string label = null;
		LogicHero logicHero = null;
		DataHero hero = null;
		object townParty = null;
		string[] slotSid = null;
		int[] slotCount = null;
		Dictionary<string, int> totals = null;
		var slot = -1;
		var skipped = new List<string>();
		foreach (var cand in candidates)
		{
			string[] sids;
			int[] counts;
			Dictionary<string, int> tot;
			string readFail;
			LogicHero lh = null;
			object party = null;
			if (cand.Town != null)
			{
				if (!Homm3FactoryLogisticsGarrison.TryGetTownGarrisonParty(cand.Town, out party, out var partyFail))
				{
					skipped.Add(cand.Label + ": " + partyFail);
					continue;
				}
				if (!Homm3PartyArmyWriter.TryReadPartyArmy(party, out sids, out counts, out tot, out readFail))
				{
					skipped.Add(cand.Label + ": army unreadable (" + readFail + ")");
					continue;
				}
			}
			else
			{
				if (cand.Hero == null)
				{
					skipped.Add(cand.Label + ": hero " + cand.HeroId + " not found");
					continue;
				}
				lh = Homm3FactoryLogisticsRuntime.CachedLogicHero(cand.Hero);
				if (lh == null)
				{
					skipped.Add(cand.Label + ": army not reachable yet (select or move the hero once, or wait for the next day)");
					continue;
				}
				if (!Homm3PartyArmyWriter.TryReadArmy(lh, cand.Hero, out sids, out counts, out tot, out readFail))
				{
					skipped.Add(cand.Label + ": army unreadable (" + readFail + ")");
					continue;
				}
			}
			var at = Array.IndexOf(sids, unitSid);
			if (at < 0)
				at = Array.FindIndex(sids, string.IsNullOrEmpty);
			if (at < 0)
			{
				skipped.Add(cand.Label + ": no free slot");
				continue;
			}
			label = cand.Label;
			hero = cand.Hero;
			logicHero = lh;
			townParty = party;
			slotSid = sids;
			slotCount = counts;
			totals = tot;
			slot = at;
			break;
		}
		if (label == null)
			return Refuse(what, fail = (candidates.Count == 1 ? "" : "no army here can take the units: ") + string.Join("; ", skipped));

		if (!Homm3FactoryLogisticsEffects.TryCharge(c.Side, cost, out var chargeFail))
			return Refuse(what, fail = chargeFail);
		var newSid = (string[])slotSid.Clone();
		var newCount = (int[])slotCount.Clone();
		newSid[slot] = unitSid;
		newCount[slot] = (string.IsNullOrEmpty(slotSid[slot]) ? 0 : slotCount[slot]) + count;
		var steps = new List<string>();
		string writeFail;
		var result = townParty != null
			? Homm3PartyArmyWriter.WritePartyArmy(townParty, newSid, newCount, totals, steps, out writeFail)
			: Homm3PartyArmyWriter.Write(logicHero, hero, newSid, newCount, totals, steps, out writeFail);
		if (result != Homm3PartyArmyWriter.WriteResult.Written)
		{
			if (result == Homm3PartyArmyWriter.WriteResult.Refused)
			{
				foreach (var pair in cost)
					Homm3FactoryLogisticsEffects.TryAddResource(c.Side, pair.Key, pair.Value, out _);
				return Refuse(what, fail = "army write refused (" + writeFail + "); cost refunded");
			}
			Homm3FactoryLogisticsRuntime.LogError(what + ": " + label + " army write " + result + " (" + writeFail + "); steps " + string.Join(", ", steps) + ". Cost kept, stock unchanged.");
			fail = "the army write did not complete (" + result + ")";
			return false;
		}
		if (have == count)
			c.Obj.UpgradedPool.Remove(key);
		else
			c.Obj.UpgradedPool[key] = have - count;
		c.State.Objects[c.ObjectId] = c.Obj;
		if (!Homm3FactoryLogisticsState.TrySave(c.State, what, out var saveFail))
		{
			Homm3FactoryLogisticsState.MarkDirty(c.State, "upgraded hire");
			Homm3FactoryLogisticsRuntime.LogError(what + ": units delivered but saving the stock failed (" + saveFail + "); retried at the next safe point.");
		}
		Homm3FactoryLogisticsRuntime.LogEvent(what + ": delivered to the " + label + (hero != null ? " " + hero.configSid : "") + " slot " + slot + " for "
			+ Homm3FactoryLogisticsEffects.FormatCost(cost) + " (upgraded stock now " + (have - count) + ").");
		fail = null;
		return true;
	}
}
