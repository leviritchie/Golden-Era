using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using Hex.Configs;
using DataHero = Hex.Session.Data.Hero;
using DataObjResMine = Hex.Session.Data.ObjResMine;
using DataObjHire = Hex.Session.Data.ObjHire;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataRoot = Hex.Session.Data.Data;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network: world snapshot (owned mines, dwellings, towns, heroes, positions), the network solve
/// (Power Station levels, Rail Station logistics level, Synthesizer multipliers/markets, Arcane hero levels, Rail
/// Network reach) through <see cref="Homm3FactoryLogisticsRange"/>, and the per-building effect math.
/// Range consumers fail closed: when the range engine or the map is unavailable, Power/Synthesizer/Arcane/Rail Network
/// contribute nothing (logged once per day) and the local effects keep working at their built level.
/// </summary>
internal static class Homm3FactoryLogisticsEffects
{
	internal const long HeroKeyOffset = 1L << 40;

	// ---------------------------------------------------------------- world snapshot

	internal sealed class World
	{
		internal DataRoot Data;
		internal int Day;
		internal int WeekId;
		internal readonly Dictionary<int, DataObjResMine> Mines = new();
		internal readonly Dictionary<int, DataObjHire> Dwellings = new();
		internal readonly Dictionary<int, DataObjCity> Cities = new();
		internal readonly Dictionary<int, (int node, int level)> Positions = new();
		internal int MapWidth;
	}

	private static readonly Dictionary<int, (string res, int value)> _mineConfigById = new();

	/// <summary>Mine resource/output seen on the mine logic's config (filled by the mine hooks).</summary>
	internal static void RememberMineConfig(int objectId, string resource, int value)
	{
		if (!string.IsNullOrEmpty(resource))
			_mineConfigById[objectId] = (resource, value);
	}

	/// <summary>Called by the runtime's single session reset only.</summary>
	internal static void ClearSessionCaches()
	{
		_mineConfigById.Clear();
		_network = null;
	}

	private static Type _rootType, _holderType;
	private static string _rootMember, _holderMember;

	/// <summary>
	/// Live session Data plus the session key (logic-root pointer, Data pointer). Every call re-reads the live statics
	/// (through the accessor that worked last time) and hands the key to the runtime, which clears all logistics
	/// caches when it changes. Never served from a stale cache.
	/// </summary>
	internal static bool TryGetData(out DataRoot data, out string fail)
	{
		data = null;
		var rootPtr = IntPtr.Zero;
		if (_rootType != null && TryReadStatic(_rootType, _rootMember, out var cachedRoot) && cachedRoot != null
		    && Homm3TowerArtificingRuntime.ReadMember(cachedRoot, GameSymbols.CustomFactionLawRuntime.LogicRootDataMembers) is DataRoot viaCached && viaCached.Pointer != IntPtr.Zero)
		{
			data = viaCached;
			rootPtr = (cachedRoot as Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
		}
		else if (_holderType != null && TryReadStatic(_holderType, _holderMember, out var cachedHeld) && cachedHeld is DataRoot heldRoot && heldRoot.Pointer != IntPtr.Zero)
		{
			data = heldRoot;
		}
		if (data != null)
		{
			Homm3FactoryLogisticsRuntime.NoteSessionKey(rootPtr, data.Pointer);
			fail = null;
			return true;
		}
		foreach (var typeName in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints)
		{
			var type = string.IsNullOrWhiteSpace(typeName) ? null : GameMember.FindType("factoryLogistics.globalLogicRoot." + typeName, typeName, null, false);
			if (type == null)
				continue;
			foreach (var name in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootInstanceMembers)
			{
				if (!TryReadStatic(type, name, out var root) || root == null)
					continue;
				if (Homm3TowerArtificingRuntime.ReadMember(root, GameSymbols.CustomFactionLawRuntime.LogicRootDataMembers) is DataRoot viaRoot && viaRoot.Pointer != IntPtr.Zero)
				{
					data = viaRoot;
					rootPtr = (root as Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
					_rootType = type;
					_rootMember = name;
					break;
				}
			}
			if (data != null)
				break;
		}
		if (data == null)
		{
			foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
			{
				if (string.IsNullOrWhiteSpace(typeName))
					continue;
				var type = ModActions.GetHexType(typeName) ?? ModActions.GetHexType("Hex.Session." + typeName) ?? ModActions.GetHexType("Hex." + typeName);
				if (type == null)
					continue;
				foreach (var name in GameSymbols.AdventureVisionLaws.SessionDataMembers)
				{
					if (TryReadStatic(type, name, out var value) && value is DataRoot root && root.Pointer != IntPtr.Zero)
					{
						data = root;
						_holderType = type;
						_holderMember = name;
						break;
					}
				}
				if (data != null)
					break;
			}
		}
		if (data == null)
		{
			fail = "session Data unresolved (CustomFactionLawRuntime logic root and AdventureVisionLaws session holder)";
			return false;
		}
		Homm3FactoryLogisticsRuntime.NoteSessionKey(rootPtr, data.Pointer);
		fail = null;
		return true;
	}

	internal static bool TryReadDay(out int day, out int weekId, out string fail)
	{
		day = 0;
		weekId = 0;
		if (!TryGetData(out var data, out fail))
			return false;
		day = data.daysInGameCount;
		// Native month/week counters change exactly at the native week boundary; packed into a 14-bit week id.
		weekId = ((data.month & 0x7FF) << 3 | (data.week & 7)) + 1;
		return true;
	}

	internal static bool TryBuildWorld(out World world, out string fail)
	{
		world = null;
		if (!TryGetData(out var data, out fail))
			return false;
		var objects = data.objects;
		if (objects == null)
		{
			fail = "Data.objects null";
			return false;
		}
		world = new World { Data = data, Day = data.daysInGameCount, WeekId = ((data.month & 0x7FF) << 3 | (data.week & 7)) + 1 };
		var mines = objects.resMines;
		var hires = objects.hireObjs;
		if (mines == null || hires == null)
		{
			// An unreadable list must never look like "every enhanced building vanished" (capture wipe).
			fail = "Data.objects." + (mines == null ? "resMines" : "hireObjs") + " null";
			world = null;
			return false;
		}
		for (var i = 0; i < mines.Count; i++)
		{
			var m = mines[i];
			if (m != null)
				world.Mines[m.idMapObject] = m;
		}
		for (var i = 0; i < hires.Count; i++)
		{
			var h = hires[i];
			if (h != null)
				world.Dwellings[h.idMapObject] = h;
		}
		var cities = objects.cityObjs;
		for (var i = 0; cities != null && i < cities.Count; i++)
		{
			var c = cities[i];
			if (c != null)
				world.Cities[c.idMapObject] = c;
		}
		world.MapWidth = Homm3FactoryLogisticsRange.MapWidth;
		ReadPositions(world);
		return true;
	}

	private static void ReadPositions(World world)
	{
		try
		{
			object map = null;
			foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
			{
				var type = string.IsNullOrWhiteSpace(typeName) ? null : ModActions.GetHexType(typeName) ?? ModActions.GetHexType("Hex.Session." + typeName) ?? ModActions.GetHexType("Hex." + typeName);
				if (type == null)
					continue;
				foreach (var name in GameSymbols.AdventureVisionLaws.SessionHolderStaticNames)
				{
					if (TryReadStatic(type, name, out var value) && value is Hex.Map.Map)
					{
						map = value;
						break;
					}
				}
				if (map != null)
					break;
			}
			map ??= Homm3FactoryLogisticsAdventureView.TryWorldCameraMap();
			var mapData = map == null ? null : Homm3TowerArtificingRuntime.ReadMember(map, GameSymbols.HomecomingBoatTravel.MapData.NameHints);
			var rows = mapData == null ? null : Homm3TowerArtificingRuntime.ReadMember(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
			foreach (var row in Enumerate(rows))
			{
				var ids = Homm3TowerArtificingRuntime.ReadMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsIdsFields) as Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppStructArray<int>;
				var nodes = Homm3TowerArtificingRuntime.ReadMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsNodesFields) as Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppStructArray<int>;
				var levels = (row as Hex.Map.MapDataObjects)?.levels;
				if (ids == null || nodes == null)
					continue;
				var n = Math.Min(ids.Length, nodes.Length);
				for (var i = 0; i < n; i++)
				{
					var level = 0;
					if (levels != null && i < levels.Length)
						level = Convert.ToInt32(levels[i], CultureInfo.InvariantCulture);
					world.Positions[ids[i]] = (nodes[i], level);
				}
			}
			if (world.Positions.Count == 0)
				Homm3FactoryLogisticsRuntime.LogOncePerDay("positions", "map object positions unreadable (MapData.objects ids/nodes); range effects and the viewer have no building tiles.");
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogOncePerDay("positions", "map object positions read threw " + ex.GetBaseException().Message + "; range effects off.");
		}
	}

	internal static bool TryGetTile(World world, int objectId, out int x, out int y, out int level)
	{
		x = y = -1;
		level = 0;
		if (world.MapWidth <= 0 || !world.Positions.TryGetValue(objectId, out var p) || p.node < 0)
			return false;
		x = p.node % world.MapWidth;
		y = p.node / world.MapWidth;
		level = p.level;
		return true;
	}

	internal static string MineResource(DataObjResMine mine)
	{
		if (mine == null)
			return null;
		if (_mineConfigById.TryGetValue(mine.idMapObject, out var cfg))
			return cfg.res;
		// Not yet seen by a mine hook this session: infer from the object sid (logged; the hook value wins later).
		var sid = (mine.sidConfig ?? string.Empty).ToLowerInvariant();
		if (sid.Contains("gold")) return "gold";
		if (sid.Contains("wood") || sid.Contains("sawmill")) return "wood";
		if (sid.Contains(GameSymbols.CovePlunder.OreResourceName)) return GameSymbols.CovePlunder.OreResourceName;
		if (sid.Contains("crystal")) return "crystals";
		if (sid.Contains("mercury") || sid.Contains("alchem")) return "mercury";
		if (sid.Contains("gems") || sid.Contains("gemstone")) return "gemstones";
		return null;
	}

	internal static int MineOutput(DataObjResMine mine, string resource)
	{
		if (mine != null && _mineConfigById.TryGetValue(mine.idMapObject, out var cfg) && cfg.value > 0)
			return cfg.value;
		return resource == "gold" ? 1000 : resource == "wood" || resource == GameSymbols.CovePlunder.OreResourceName ? 2 : 1;
	}

	internal static string Humanize(string sid)
	{
		if (string.IsNullOrEmpty(sid))
			return "Building";
		var words = sid.Replace('-', '_').Split('_');
		var parts = new List<string>();
		foreach (var w in words)
		{
			if (w.Length == 0 || w == "h3" || w == "homm3" || w.All(char.IsDigit))
				continue;
			parts.Add(char.ToUpperInvariant(w[0]) + w.Substring(1));
		}
		return parts.Count == 0 ? sid : string.Join(" ", parts);
	}

	internal static string MineDisplayName(string resource) => resource switch
	{
		"gold" => "Gold Mine",
		"wood" => "Sawmill",
		GameSymbols.CovePlunder.OreResourceName => "Ore Pit",
		"crystals" => "Crystal Cavern",
		"mercury" => "Alchemist's Lab",
		"gemstones" => "Gem Pond",
		_ => "Mine",
	};

	/// <summary>Base unit sid, tier, gold price and the rare its dwelling costs (null = none) of a dwelling's first unit set.</summary>
	internal static bool TryReadDwellingUnit(DataObjHire dwelling, Homm3FactoryLogisticsConfig config, out string unitSid, out int tier, out int goldPrice, out string rare)
	{
		unitSid = null;
		tier = 1;
		goldPrice = 0;
		rare = null;
		var sets = dwelling?.assortmentData?.unitSets;
		if (sets == null || sets.Count == 0 || sets[0]?.sids == null || sets[0].sids.Count == 0)
			return false;
		unitSid = sets[0].sids[0];
		var unit = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unitSid);
		if (unit == null)
			return false;
		tier = Math.Max(1, Math.Min(7, unit.tier));
		ReadUnitCost(unit, config, out goldPrice, out rare);
		return true;
	}

	internal static void ReadUnitCost(UnitLogicConfig unit, Homm3FactoryLogisticsConfig config, out int goldPrice, out string rare)
	{
		goldPrice = 0;
		rare = null;
		var best = 0;
		var costs = unit?.unitCost?.costResArray;
		for (var i = 0; costs != null && i < costs.Length; i++)
		{
			var name = costs[i]?.name?.Trim();
			if (name == null || Homm3TowerArtificingRuntime.ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is not int amount || amount <= 0)
				continue;
			if (name == "gold")
				goldPrice = amount;
			else if (config.DwellingRareResources.Contains(name) && amount > best)
			{
				best = amount;
				rare = name;
			}
		}
	}

	internal static int CountMarkets(World world, int sideIndex)
	{
		var markets = 0;
		foreach (var city in world.Cities.Values)
		{
			if (city.ownerSide != sideIndex)
				continue;
			var list = city.buildings?.markets;
			for (var i = 0; list != null && i < list.Count; i++)
			{
				var m = list[i];
				if (m != null && m.isConstructed && m.level > 0)
				{
					markets++;
					break;
				}
			}
		}
		return markets;
	}

	internal static List<DataHero> SideHeroes(World world, int sideIndex)
	{
		var result = new List<DataHero>();
		var heroes = Homm3TowerArtificingRuntime.ReadMember(world.Data, GameSymbols.AdventureAiDecision.DataRootHeroesMembers);
		var list = heroes is Il2CppSystem.Object ? Homm3TowerArtificingRuntime.ReadMember(heroes, new[] { "list", "array" }) ?? heroes : heroes;
		foreach (var item in Enumerate(list))
		{
			if (item is DataHero hero && hero.sideId == sideIndex && hero.node >= 0)
				result.Add(hero);
		}
		return result;
	}

	internal static int HeroId(DataHero hero) => Homm3TowerArtificingRuntime.ReadMember(hero, GameSymbols.CastleEliteStrategem.DataHeroIdMembers) is int id ? id : -1;

	// ---------------------------------------------------------------- effective levels

	internal static int BuiltActiveLevel(Homm3FactoryLogisticsState.ObjectState o)
	{
		if (o == null || o.ActiveCode == 0 || !o.Built.TryGetValue(o.ActiveCode, out var e))
			return 0;
		return e.Level;
	}

	internal static Homm3FactoryLogisticsConfig.Enhancement ActiveEnhancement(Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsState.ObjectState o)
	{
		return o == null || o.ActiveCode == 0 || BuiltActiveLevel(o) <= 0 ? null : config.Get(o.ActiveCode);
	}

	/// <summary>True when the active enhancement replaces the mine's own output (Export Office and the logistics functions).</summary>
	internal static bool SuppressesOutput(Homm3FactoryLogisticsConfig.Enhancement e)
	{
		return e != null && e.Effect is "export" or "warehouse" or "rail_station" or "power_station" or "synthesizer" or "arcane";
	}

	// ---------------------------------------------------------------- network solve

	internal sealed class Network
	{
		internal int SideIndex;
		internal int Day;
		internal bool RangeOk;
		internal string RangeFail;
		internal int LogisticsLevel;
		internal readonly Dictionary<int, int> PowerBonus = new();          // object id -> extra levels
		internal readonly Dictionary<int, double> SynthMultiplier = new();  // export/merc object id -> multiplier
		internal int ExtraMarkets;
		internal readonly Dictionary<int, int> HeroArcaneLevel = new();     // hero id -> arcane level
		/// <summary>Astrology towns: per Arcane Manufactory min(effective level, owned towns it reaches), summed (DECISIONS.md #55).</summary>
		internal int ArcaneAstrologyTowns;
		/// <summary>Owned dwelling id -> share of each week's growth converted to upgraded stock (max over reaching Manufactories, min(1, eff/6)).</summary>
		internal readonly Dictionary<int, double> DwellingConversion = new();
		/// <summary>Owned dwelling id -> extra weekly units in percent from Support Hubs reaching it (summed over hubs; never the hub itself).</summary>
		internal readonly Dictionary<int, double> SupportGrowthPct = new();
		internal readonly Dictionary<int, HashSet<long>> RailReach = new(); // dwelling id -> reached town ids / hero keys
		internal double WarehouseDiscountPct;
		/// <summary>Supply Caravan heroes: hub-only range nodes at their tile (level 3 Logistics Hub refresh).</summary>
		internal List<Homm3FactoryLogisticsRange.Node> CaravanHubs = new();
		/// <summary>Owned mine/dwelling id -> remote build level granted by a Mobile Command Center hero in range (its skill rank).</summary>
		internal readonly Dictionary<int, int> CommandCenterLevel = new();
		/// <summary>Trade Contracts heroes of the side on the map (each counts as 2 extra markets).</summary>
		internal int TradeContractHeroes;
		internal Homm3FactoryLogisticsRange.Result Display;               // last solve for the viewer
		internal List<Homm3FactoryLogisticsRange.Node> DisplaySources = new();
		internal List<Homm3FactoryLogisticsRange.Node> DisplayTargets = new();

		internal int EffectiveLevel(Homm3FactoryLogisticsConfig.Enhancement e, int objectId, int built)
		{
			if (built <= 0 || e == null)
				return 0;
			if (e.Effect == "power_station")
				return built;
			return built + (PowerBonus.TryGetValue(objectId, out var b) ? b : 0);
		}
	}

	private static Network _network;

	internal static Network GetNetwork(int sideIndex, bool force = false)
	{
		var day = TryReadDay(out var d, out _, out _) ? d : -1;
		if (!force && _network != null && _network.SideIndex == sideIndex && _network.Day == day && day >= 0)
			return _network;
		_network = Solve(sideIndex, day);
		return _network;
	}

	internal static void InvalidateNetwork() => _network = null;

	/// <summary>"What if" for the viewer's before/after preview: object <see cref="ObjectId"/> has <see cref="Code"/> active at
	/// <see cref="Level"/> (Code 0 = nothing active). Never cached, never saved.</summary>
	internal sealed class Hypothetical
	{
		internal int ObjectId;
		internal int Code;
		internal int Level;
	}

	/// <summary>A full network solve with one building's active enhancement replaced (viewer preview; not cached).</summary>
	internal static Network SolveHypothetical(int sideIndex, Hypothetical hypo)
	{
		var day = TryReadDay(out var d, out _, out _) ? d : -1;
		return Solve(sideIndex, day, hypo);
	}

	/// <summary>Owned network members (object, active enhancement, built level), with an optional hypothetical override.</summary>
	internal static List<(Homm3FactoryLogisticsState.ObjectState o, Homm3FactoryLogisticsConfig.Enhancement e, int built)> Members(
		Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsState.SideState state, World world, int sideIndex, Hypothetical hypo)
	{
		var members = new List<(Homm3FactoryLogisticsState.ObjectState o, Homm3FactoryLogisticsConfig.Enhancement e, int built)>();
		foreach (var o in state.Objects.Values)
		{
			if (hypo != null && o.ObjectId == hypo.ObjectId)
				continue;
			if (OwnerOf(world, o.ObjectId) != sideIndex)
				continue;
			var e = ActiveEnhancement(config, o);
			if (e != null)
				members.Add((o, e, BuiltActiveLevel(o)));
		}
		if (hypo != null && hypo.Code != 0 && hypo.Level > 0 && OwnerOf(world, hypo.ObjectId) == sideIndex && config.Get(hypo.Code) is { } he)
		{
			var ho = state.Objects.TryGetValue(hypo.ObjectId, out var have) ? have : new Homm3FactoryLogisticsState.ObjectState { ObjectId = hypo.ObjectId };
			members.Add((ho, he, Math.Min(config.MaxLevel, hypo.Level)));
		}
		return members;
	}

	private static Network Solve(int sideIndex, int day, Hypothetical hypo = null)
	{
		var net = new Network { SideIndex = sideIndex, Day = day };
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var cfgFail))
		{
			net.RangeFail = "config: " + cfgFail;
			return net;
		}
		net.LogisticsLevel = config.BaseLogisticsLevel;
		if (!Homm3FactoryLogisticsState.TryGet(sideIndex, out var state, out var stateFail) || !TryBuildWorld(out var world, out var worldFail))
		{
			net.RangeFail = stateFail ?? "world unreadable";
			return net;
		}
		var members = Members(config, state, world, sideIndex, hypo);
		// Hero subskills: Supply Caravan hubs, Mobile Command Center sources, Trade Contracts markets.
		var commandSources = new List<Homm3FactoryLogisticsRange.Node>();
		var commandRank = new Dictionary<long, int>();
		var caravanRefresh = 1.0;
		foreach (var e in config.Enhancements)
			if (e.Effect == "route_hub")
				caravanRefresh = Math.Min(1.0, e.ValueAt(config.MaxLevel));
		foreach (var hero in SideHeroes(world, sideIndex))
		{
			var id = HeroId(hero);
			if (id < 0 || world.MapWidth <= 0)
				continue;
			int hx = hero.node % world.MapWidth, hy = hero.node / world.MapWidth;
			if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, Homm3FactoryLogisticsConfig.SupplyCaravanSubSkillSid))
				net.CaravanHubs.Add(new Homm3FactoryLogisticsRange.Node { Key = HeroKeyOffset + id, Kind = "hero", X = hx, Y = hy, HubRefresh = caravanRefresh });
			if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, Homm3FactoryLogisticsConfig.TradeContractsSubSkillSid))
				net.TradeContractHeroes++;
			if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, Homm3FactoryLogisticsConfig.CommandCenterSubSkillSid))
			{
				var rank = Homm3FactoryLogisticsRuntime.SkillRank(hero, config.SkillSid);
				if (rank > 0)
				{
					commandSources.Add(new Homm3FactoryLogisticsRange.Node { Key = HeroKeyOffset + id, Kind = "hero", X = hx, Y = hy });
					commandRank[HeroKeyOffset + id] = Math.Min(config.MaxLevel, rank);
				}
			}
		}

		// Warehouse: network-wide, best one applies (no range).
		var railBuilt = 0;
		foreach (var m in members)
		{
			if (m.e.Effect == "rail_station")
				railBuilt += m.built;
		}

		Homm3FactoryLogisticsRange.Node NodeFor(int objectId, int rangeLevels, Homm3FactoryLogisticsConfig.Enhancement e, int eff)
		{
			if (!TryGetTile(world, objectId, out var x, out var y, out var level))
				return null;
			var hub = e == null ? 0.0 : e.Effect == "route_hub" ? e.ValueAt(eff) : e.Effect == "rail_station" ? 1.0 : 0.0;
			return new Homm3FactoryLogisticsRange.Node { Key = objectId, Kind = world.Cities.ContainsKey(objectId) ? "town" : "building", X = x, Y = y, Level = level, RangeLevels = rangeLevels, HubRefresh = Math.Min(1.0, hub) };
		}

		// Pass 1: Power Stations (range from the unpowered logistics level) onto every other enhanced building.
		var level0 = config.BaseLogisticsLevel + railBuilt;
		var powerSources = new List<Homm3FactoryLogisticsRange.Node>();
		var powerLevels = new Dictionary<long, int>();
		var powerTargets = new List<Homm3FactoryLogisticsRange.Node>();
		foreach (var m in members)
		{
			var node = NodeFor(m.o.ObjectId, level0, m.e, m.built);
			if (node == null)
				continue;
			if (m.e.Effect == "power_station")
			{
				powerSources.Add(node);
				powerLevels[node.Key] = (int)Math.Round(m.e.ValueAt(m.built));
			}
			else
			{
				powerTargets.Add(node);
			}
		}
		net.RangeOk = true;
		if (powerSources.Count > 0 && powerTargets.Count > 0)
		{
			if (Homm3FactoryLogisticsRange.TrySolve(sideIndex, powerSources, powerTargets, config.RangeMpPerLevel, out var powerResult, out var powerFail, net.CaravanHubs))
			{
				foreach (var r in powerResult.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
				{
					if (!r.Reached || !powerLevels.TryGetValue(r.From, out var lv))
						continue;
					var target = (int)r.To;
					net.PowerBonus[target] = (net.PowerBonus.TryGetValue(target, out var have) ? have : 0) + lv;
				}
			}
			else
			{
				net.RangeOk = false;
				net.RangeFail = powerFail;
			}
		}
		var railEffective = 0;
		foreach (var m in members)
		{
			var eff = net.EffectiveLevel(m.e, m.o.ObjectId, m.built);
			switch (m.e.Effect)
			{
				case "rail_station":
					railEffective += (int)Math.Round(m.e.ValueAt(eff));
					break;
				case "warehouse":
					net.WarehouseDiscountPct = Math.Max(net.WarehouseDiscountPct, m.e.ValueAt(eff));
					break;
			}
		}
		net.LogisticsLevel = config.BaseLogisticsLevel + railEffective;

		// Pass 2: Synthesizer, Arcane Manufactory and Rail Network sources onto buildings, towns and heroes.
		var sources = new List<Homm3FactoryLogisticsRange.Node>();
		var targets = new List<Homm3FactoryLogisticsRange.Node>();
		var sourceInfo = new Dictionary<long, (Homm3FactoryLogisticsConfig.Enhancement e, int eff)>();
		foreach (var m in members)
		{
			var eff = net.EffectiveLevel(m.e, m.o.ObjectId, m.built);
			var own = m.e.Effect == "rail_network" ? (int)Math.Round(m.e.ValueAt(eff)) : 0;
			var node = NodeFor(m.o.ObjectId, net.LogisticsLevel + own, m.e, eff);
			if (node == null)
				continue;
			if (m.e.Effect is "synthesizer" or "arcane" or "rail_network" or "power_station" or "support")
			{
				sources.Add(node);
				sourceInfo[node.Key] = (m.e, eff);
			}
			if (m.e.Effect is "export" or "mercenary" or "route_hub" or "rail_station")
				targets.Add(NodeFor(m.o.ObjectId, net.LogisticsLevel, m.e, eff));
		}
		foreach (var city in world.Cities.Values)
		{
			if (city.ownerSide != sideIndex)
				continue;
			var node = NodeFor(city.idMapObject, net.LogisticsLevel, null, 0);
			if (node != null)
				targets.Add(node);
		}
		foreach (var hero in SideHeroes(world, sideIndex))
		{
			var id = HeroId(hero);
			if (id < 0 || world.MapWidth <= 0)
				continue;
			targets.Add(new Homm3FactoryLogisticsRange.Node { Key = HeroKeyOffset + id, Kind = "hero", X = hero.node % world.MapWidth, Y = hero.node / world.MapWidth, RangeLevels = net.LogisticsLevel });
		}
		// Arcane unit conversion (DECISIONS.md #56) and Support Hub growth (#81) reach every owned dwelling in range,
		// enhanced or not.
		var arcaneDwellingTargets = new HashSet<long>();
		var anyArcane = false;
		foreach (var v in sourceInfo.Values)
			anyArcane |= v.e.Effect is "arcane" or "support";
		if (anyArcane)
		{
			var targetKeys = new HashSet<long>();
			foreach (var t in targets)
				targetKeys.Add(t.Key);
			foreach (var pair in world.Dwellings)
			{
				if (pair.Value == null || pair.Value.ownerSide != sideIndex)
					continue;
				arcaneDwellingTargets.Add(pair.Key);
				if (targetKeys.Contains(pair.Key))
					continue;
				var node = NodeFor(pair.Key, net.LogisticsLevel, null, 0);
				if (node != null)
					targets.Add(node);
			}
		}
		net.DisplaySources = sources;
		net.DisplayTargets = targets;
		if (sources.Count > 0 && targets.Count > 0)
		{
			if (Homm3FactoryLogisticsRange.TrySolve(sideIndex, sources, targets, config.RangeMpPerLevel, out var result, out var fail, net.CaravanHubs))
			{
				net.Display = result;
				var synthTowns = new Dictionary<long, int>();
				var arcaneTowns = new Dictionary<long, int>();
				foreach (var r in result.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
				{
					if (!r.Reached || !sourceInfo.TryGetValue(r.From, out var src))
						continue;
					var isHero = r.To >= HeroKeyOffset;
					var isTown = !isHero && world.Cities.ContainsKey((int)r.To);
					switch (src.e.Effect)
					{
						case "synthesizer":
							if (isTown)
								synthTowns[r.From] = (synthTowns.TryGetValue(r.From, out var t) ? t : 0) + 1;
							else if (!isHero)
								net.SynthMultiplier[(int)r.To] = Math.Max(net.SynthMultiplier.TryGetValue((int)r.To, out var mul) ? mul : 1.0, src.e.ValueAt(src.eff));
							break;
						case "arcane":
							if (isHero)
							{
								var heroId = (int)(r.To - HeroKeyOffset);
								net.HeroArcaneLevel[heroId] = Math.Max(net.HeroArcaneLevel.TryGetValue(heroId, out var lv) ? lv : 0, (int)Math.Round(src.e.ValueAt(src.eff)));
							}
							else if (isTown)
							{
								if (world.Cities.TryGetValue((int)r.To, out var reached) && reached.ownerSide == sideIndex)
									arcaneTowns[r.From] = (arcaneTowns.TryGetValue(r.From, out var at) ? at : 0) + 1;
							}
							else if (arcaneDwellingTargets.Contains(r.To))
							{
								var share = Math.Min(1.0, src.eff / 6.0);
								var dwellingId = (int)r.To;
								if (share > (net.DwellingConversion.TryGetValue(dwellingId, out var had) ? had : 0.0))
									net.DwellingConversion[dwellingId] = share;
							}
							break;
						case "support":
							if (!isTown && !isHero && r.To != r.From && arcaneDwellingTargets.Contains(r.To))
							{
								var dwellingId = (int)r.To;
								net.SupportGrowthPct[dwellingId] = (net.SupportGrowthPct.TryGetValue(dwellingId, out var pct) ? pct : 0.0) + src.e.ValueAt(src.eff);
							}
							break;
						case "rail_network":
							if (isTown || isHero)
							{
								if (!net.RailReach.TryGetValue((int)r.From, out var set))
									net.RailReach[(int)r.From] = set = new HashSet<long>();
								set.Add(r.To);
							}
							break;
					}
				}
				foreach (var pair in synthTowns)
				{
					var eff = sourceInfo[pair.Key].eff;
					net.ExtraMarkets += Math.Min(eff, pair.Value);
				}
				foreach (var pair in arcaneTowns)
					net.ArcaneAstrologyTowns += Math.Min(sourceInfo[pair.Key].eff, pair.Value);
			}
			else
			{
				net.RangeOk = false;
				net.RangeFail = fail;
			}
		}
		// Mobile Command Center: owned mines and dwellings within the hero's logistics range build remotely up to its rank.
		if (commandSources.Count > 0)
		{
			foreach (var s in commandSources)
				s.RangeLevels = net.LogisticsLevel;
			var commandTargets = new List<Homm3FactoryLogisticsRange.Node>();
			foreach (var id in world.Mines.Keys)
				if (OwnerOf(world, id) == sideIndex && NodeFor(id, net.LogisticsLevel, null, 0) is { } mn)
					commandTargets.Add(mn);
			foreach (var pair in world.Dwellings)
				if (pair.Value != null && pair.Value.ownerSide == sideIndex && NodeFor(pair.Key, net.LogisticsLevel, null, 0) is { } dn)
					commandTargets.Add(dn);
			if (commandTargets.Count > 0)
			{
				if (Homm3FactoryLogisticsRange.TrySolve(sideIndex, commandSources, commandTargets, config.RangeMpPerLevel, out var cmd, out var cmdFail, net.CaravanHubs))
				{
					foreach (var r in cmd.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
					{
						if (!r.Reached || !commandRank.TryGetValue(r.From, out var rank) || r.To >= HeroKeyOffset)
							continue;
						var target = (int)r.To;
						net.CommandCenterLevel[target] = Math.Max(net.CommandCenterLevel.TryGetValue(target, out var had) ? had : 0, rank);
					}
				}
				else
				{
					Homm3FactoryLogisticsRuntime.LogOncePerDay("command", "Mobile Command Center range solve failed for side " + sideIndex + " (" + cmdFail + ").");
				}
			}
		}
		SolveDisplayRoutes(net, members, targets, sideIndex, config, NodeFor, id => id >= 0 && id <= int.MaxValue && world.Dwellings.ContainsKey((int)id));
		if (!net.RangeOk)
			Homm3FactoryLogisticsRuntime.LogOncePerDay("range", "range solve failed for side " + sideIndex + " (" + net.RangeFail + "); Power Station, Synthesizer, Arcane and Rail Network reach are off until it works.");
		return net;
	}

	/// <summary>
	/// Viewer routes (display only; effects use their own solves above). Only range-based logistics effects draw
	/// (user, 2026-11-16: buildings without a logistics effect draw no lines; Warehouse is network-wide, Hubs and
	/// Rail Stations are waypoints routes pass through). Each line is a real effect link:
	/// Power Station -> other enhanced non-Power buildings; Synthesizer -> Export Office / Mercenary HQ and towns;
	/// Arcane Manufactory -> towns, heroes and dwellings; Rail Network -> towns, plus heroes at its hero level;
	/// Support Hub -> other dwellings.
	/// </summary>
	private static void SolveDisplayRoutes(
		Network net,
		List<(Homm3FactoryLogisticsState.ObjectState o, Homm3FactoryLogisticsConfig.Enhancement e, int built)> members,
		List<Homm3FactoryLogisticsRange.Node> effectTargets,
		int sideIndex,
		Homm3FactoryLogisticsConfig config,
		Func<int, int, Homm3FactoryLogisticsConfig.Enhancement, int, Homm3FactoryLogisticsRange.Node> nodeFor,
		Func<long, bool> isDwelling)
	{
		var sources = new List<Homm3FactoryLogisticsRange.Node>();
		var targets = new List<Homm3FactoryLogisticsRange.Node>();
		var effectOf = new Dictionary<long, string>();
		var heroOk = new HashSet<long>();
		foreach (var m in members)
		{
			var eff = net.EffectiveLevel(m.e, m.o.ObjectId, m.built);
			var own = m.e.Effect == "rail_network" ? (int)Math.Round(m.e.ValueAt(eff)) : 0;
			var tgt = nodeFor(m.o.ObjectId, net.LogisticsLevel, m.e, eff);
			if (tgt == null)
				continue;
			targets.Add(tgt);
			effectOf[tgt.Key] = m.e.Effect;
			if (m.e.Effect is "power_station" or "synthesizer" or "arcane" or "rail_network" or "support")
			{
				// Power Station range comes from the unpowered level, as in pass 1.
				var src = nodeFor(m.o.ObjectId, (m.e.Effect == "power_station" ? net.LogisticsLevel : net.LogisticsLevel + own), m.e, eff);
				if (src != null)
					sources.Add(src);
				if (m.e.Effect == "arcane" || (m.e.Effect == "rail_network" && eff >= Math.Max(1, m.e.HeroDeliveryLevel)))
					heroOk.Add(tgt.Key);
			}
		}
		foreach (var t in effectTargets)
		{
			// Unenhanced owned dwellings (added by pass 2 only when an Arcane or Support Hub source exists) are their targets.
			if (t.Kind is "town" or "hero" || (t.Kind == "building" && !effectOf.ContainsKey(t.Key) && isDwelling(t.Key)))
				targets.Add(t);
		}
		if (sources.Count == 0 || targets.Count == 0)
			return;
		if (!Homm3FactoryLogisticsRange.TrySolve(sideIndex, sources, targets, config.RangeMpPerLevel, out var result, out var fail, net.CaravanHubs))
		{
			net.RangeOk = false;
			net.RangeFail ??= fail;
			return;
		}
		var kept = new List<Homm3FactoryLogisticsRange.Route>();
		foreach (var r in result.Routes ?? new List<Homm3FactoryLogisticsRange.Route>())
		{
			if (r.From == r.To || !effectOf.TryGetValue(r.From, out var fx))
				continue;
			var toEffect = effectOf.TryGetValue(r.To, out var tx) ? tx : null;
			var relevant = r.ToKind switch
			{
				"hero" => heroOk.Contains(r.From),
				"town" => fx is "synthesizer" or "arcane" or "rail_network",
				"building" => fx switch
				{
					"power_station" => toEffect != null && toEffect != "power_station",
					"synthesizer" => toEffect is "export" or "mercenary",
					"arcane" => isDwelling(r.To),
					"support" => isDwelling(r.To) && toEffect != "support",
					_ => false,
				},
				_ => false,
			};
			if (relevant)
				kept.Add(r);
		}
		var keptLinks = new HashSet<(long, long)>();
		foreach (var r in kept)
			keptLinks.Add((r.From, r.To));
		var blockers = new List<Homm3FactoryLogisticsRange.Blocker>();
		foreach (var b in result.Blockers ?? new List<Homm3FactoryLogisticsRange.Blocker>())
		{
			b.WouldLink = b.WouldLink?.FindAll(l => keptLinks.Contains((l.from, l.to)));
			if (b.WouldLink != null && b.WouldLink.Count > 0)
				blockers.Add(b);
		}
		result.Routes = kept;
		result.Blockers = blockers;
		net.Display = result;
	}

	/// <summary>Owner side of a mine/dwelling; <see cref="OwnerMissing"/> when the object is not in the world (skip, never wipe).</summary>
	internal const int OwnerMissing = -2;

	internal static int OwnerOf(World world, int objectId)
	{
		if (world.Mines.TryGetValue(objectId, out var m))
			return m.ownerSide;
		if (world.Dwellings.TryGetValue(objectId, out var h))
			return h.ownerSide;
		return OwnerMissing;
	}

	// ---------------------------------------------------------------- effect math

	/// <summary>Daily gold of an Export Office: value x market sell rate of the mine's output x synthesizer.</summary>
	internal static int ExportGold(Homm3FactoryLogisticsConfig config, Network net, World world, int sideIndex, int objectId, string resource, int output, int effectiveLevel)
	{
		var e = config.ById.Values.FirstOrDefault(x => x.Effect == "export");
		if (e == null || effectiveLevel <= 0 || output <= 0)
			return 0;
		var markets = CountMarkets(world, sideIndex) + net.ExtraMarkets + net.TradeContractHeroes * Homm3FactoryLogisticsConfig.TradeContractsMarketsPerHero;
		var synth = net.SynthMultiplier.TryGetValue(objectId, out var s) ? s : 1.0;
		return (int)Math.Floor(e.ValueAt(effectiveLevel) * config.SellValue(resource, markets) * output * synth);
	}

	internal static bool TryAddResource(int sideIndex, string resource, int amount, out string fail)
	{
		fail = null;
		if (amount == 0)
			return true;
		if (!Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out fail))
			return false;
		if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(side, resource, out var res, out var info, out fail))
			return false;
		if (amount < 0 && info.Value < -amount)
		{
			fail = "not enough " + resource + " (" + info.Value + " < " + (-amount) + ")";
			return false;
		}
		return Homm3RewardEconomyNativeAdapter.TryAddResourceValue(res, amount, out fail);
	}

	internal static bool TryReadResource(int sideIndex, string resource, out int value)
	{
		value = 0;
		return Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out _)
		       && Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(side, resource, out _, out var info, out _)
		       && (value = info.Value) >= int.MinValue;
	}

	internal static bool CanAfford(int sideIndex, IReadOnlyDictionary<string, int> cost, out string missing)
	{
		missing = null;
		foreach (var pair in cost)
		{
			if (pair.Value <= 0)
				continue;
			if (!TryReadResource(sideIndex, pair.Key, out var have) || have < pair.Value)
			{
				missing = pair.Key;
				return false;
			}
		}
		return true;
	}

	/// <summary>Charges every resource of an affordable cost; on a partial failure refunds what was taken.</summary>
	internal static bool TryCharge(int sideIndex, IReadOnlyDictionary<string, int> cost, out string fail)
	{
		if (!CanAfford(sideIndex, cost, out var missing))
		{
			fail = "not enough " + missing;
			return false;
		}
		var taken = new List<KeyValuePair<string, int>>();
		foreach (var pair in cost)
		{
			if (pair.Value <= 0)
				continue;
			if (!TryAddResource(sideIndex, pair.Key, -pair.Value, out fail))
			{
				foreach (var t in taken)
					TryAddResource(sideIndex, t.Key, t.Value, out _);
				fail = "charging " + pair.Value + " " + pair.Key + " failed (" + fail + "); refunded";
				return false;
			}
			taken.Add(pair);
		}
		fail = null;
		return true;
	}

	internal static Dictionary<string, int> Discounted(IReadOnlyDictionary<string, int> cost, double discountPct)
	{
		var result = new Dictionary<string, int>(StringComparer.Ordinal);
		var factor = 1.0 - Math.Max(0.0, Math.Min(90.0, discountPct)) / 100.0;
		foreach (var pair in cost)
			result[pair.Key] = (int)Math.Ceiling(pair.Value * factor - 1e-9);
		return result;
	}

	internal static string FormatCost(IReadOnlyDictionary<string, int> cost)
	{
		var parts = new List<string>();
		foreach (var pair in cost)
			parts.Add(pair.Value.ToString(CultureInfo.InvariantCulture) + " " + pair.Key);
		return string.Join(" + ", parts);
	}

	// ---------------------------------------------------------------- helpers

	internal static IEnumerable<object> Enumerate(object list)
	{
		if (list == null)
			yield break;
		var type = list.GetType();
		var count = type.GetProperty("Count", BindingFlags.Instance | BindingFlags.Public)?.GetValue(list) as int?
		            ?? type.GetProperty("Length", BindingFlags.Instance | BindingFlags.Public)?.GetValue(list) as int?;
		var indexer = type.GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public, null, new[] { typeof(int) }, null);
		if (count.HasValue && indexer != null)
		{
			for (var i = 0; i < count.Value; i++)
			{
				var item = indexer.Invoke(list, new object[] { i });
				if (item != null)
					yield return item;
			}
			yield break;
		}
		if (list is System.Collections.IEnumerable e)
		{
			foreach (var item in e)
			{
				if (item != null)
					yield return item;
			}
		}
	}

	private static bool TryReadStatic(Type type, string name, out object value)
	{
		value = null;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			RuntimeHelpers.RunClassConstructor(type.TypeHandle);
		}
		catch
		{
			// Il2Cpp static init is best-effort; the member read decides.
		}
		try
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				value = property.GetValue(null);
				return true;
			}
			var field = type.GetField(name, flags);
			if (field != null)
			{
				value = field.GetValue(null);
				return true;
			}
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void))
			{
				value = method.Invoke(null, null);
				return true;
			}
		}
		catch
		{
			value = null;
		}
		return false;
	}
}

internal static class Homm3FactoryLogisticsLinq
{
	internal static bool All(this string s, Func<char, bool> predicate)
	{
		foreach (var c in s)
		{
			if (!predicate(c))
				return false;
		}
		return true;
	}

	internal static T FirstOrDefault<T>(this IEnumerable<T> items, Func<T, bool> predicate) where T : class
	{
		foreach (var item in items)
		{
			if (predicate(item))
				return item;
		}
		return null;
	}
}
