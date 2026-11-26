using System;
using System.Collections.Generic;
using System.Globalization;
using BepInEx.Logging;
using Picks = OfflineUnlockMod.Homm3CoveTreasureSubskills;
using DataArea = Hex.Session.Data.DataArea;
using DataHero = Hex.Session.Data.Hero;
using DataObject = Hex.Session.Data.DataObject;
using DataRoot = Hex.Session.Data.Data;
using DataSquad = Hex.Session.Data.DataSquad;
using Plan = OfflineUnlockMod.Homm3CoveTreasurePlan;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting, map pieces and search reveal (docs/cove_treasure_hunting_design.md sections 4 to 6.1).
///
/// Nothing runs for a game without a hero that has the Cove faction skill: every tick first looks for such a hero
/// on the map and returns when there is none. With one, the per-map tables (node to region, static object and
/// stack lists) are built once, and a region's plan is built the first time a Cove hero's search radius touches it.
///
/// Rules implemented here:
/// - Search: a Cove hero reveals, for its side, every map piece within <see cref="SearchRadius"/> tiles.
/// - Collect: when a holder (chest, resource pile, artifact, neutral stack) is taken or beaten and a Cove hero is
///   next to it, that hero's side gets the piece. Otherwise the piece lies loose on the holder's tile and a Cove
///   hero must step on that tile. Heroes without the skill never reveal or collect.
/// - Leads: the first piece shows 4 possible treasure tiles, each further piece removes one false lead.
///
/// State is in memory only (save/load persistence is a later step). Proof tier: build only; runtime unproven.
/// </summary>
internal static partial class Homm3CoveTreasureRuntime
{
	internal const string LogPrefix = "HoMM3 Cove Treasure: ";
	internal const string CoveSkillSid = "skill_faction_homm3_cove";
	/// <summary>Half of the base hero view radius (6). Vision upgrades do not change it.</summary>
	internal const int SearchRadius = 3;
	private const int CityHolderExclusion = 5;
	private const int GuardRange = 2;
	private const int LogCap = 200;

	internal enum MarkerKind : byte { Piece, LoosePiece, Lead, Treasure, Hole }

	internal enum DigOutcome : byte { Refused, Hole, Treasure }

	internal struct Marker
	{
		internal int Node;
		internal int AreaId;
		internal MarkerKind Kind;
	}

	private sealed class HolderState
	{
		internal Plan.Holder Holder;
		internal DataObject Object;
		internal DataSquad Squad;
		/// <summary>The holder is gone (or the piece never had one): the piece lies on the tile.</summary>
		internal bool Loose;
		internal uint RevealedSides;
		internal uint CollectedSides;
	}

	private sealed class RegionState
	{
		internal int AreaId;
		internal Plan.RegionPlan Plan;
		internal HolderState[] Holders;
		internal readonly Dictionary<int, int> PiecesBySide = new();
		/// <summary>The treasure was dug up (by any side): nothing in this region is shown or collectable any more.</summary>
		internal bool Dug;
		/// <summary>The side that dug it up (Ancient Curses), -1 while buried.</summary>
		internal int DugSide = -1;
		/// <summary>Sides that already got their Archivist bonus piece here.</summary>
		internal uint ArchivistSides;
		/// <summary>Sides with a Treasure Hunting hero that has stood in the region (the chart's "charted" state).</summary>
		internal uint VisitedSides;
	}

	private sealed class MapState
	{
		internal IntPtr DataPointer;
		internal int Width;
		internal int Height;
		internal ulong Seed;
		internal Dictionary<int, int> AreaOfNode;
		internal Dictionary<int, DataArea> Areas;
		internal Dictionary<int, List<Plan.Holder>> HolderCandidates;
		internal HashSet<int> StaticOccupied;
		internal Dictionary<int, DataObject> LiveObjects;
		internal Dictionary<int, DataSquad> LiveSquads;
		internal readonly Dictionary<int, RegionState> Regions = new();
		/// <summary>Tiles dug without success, by anyone. A hole removes that tile as a lead for every side.</summary>
		internal readonly HashSet<int> Holes = new();
		internal Plan.Catalog Catalog;
		internal bool RichnessReady;
		internal bool Failed;
		// Save persistence (Homm3CoveTreasureSave.cs).
		/// <summary>The stored state was read (or there was none). Nothing is planned or saved before this.</summary>
		internal bool SaveLoaded;
		/// <summary>Why the stored state was rejected; while set, this map is never written.</summary>
		internal string SaveBlocked;
		/// <summary>Stored regions not planned yet.</summary>
		internal Dictionary<int, SavedRegion> Saved;
		/// <summary>The records now in the save model; null while nothing is stored.</summary>
		internal List<int> SavedRecords;
		internal int SaveSide = -1;
	}

	private static ManualLogSource _log;
	private static MapState _map;
	private static int _logged;
	private static readonly Dictionary<int, (int Day, int Rank)> _rankCache = new();
	private static readonly Dictionary<int, (int Day, int Max)> _moveMax = new();
	private static readonly List<DataHero> _coveHeroes = new();
	private static bool _inTick;

	/// <summary>Bumped whenever what a side can see changes (reveal, collect, new session). Markers poll it.</summary>
	internal static int Version { get; private set; }

	/// <summary>Last piece event for the local side, for the on-map notice. Cleared by the marker layer.</summary>
	internal static string PendingNotice;
	internal static int PendingNoticeNode = -1;

	internal static void TryRegister(ManualLogSource log)
	{
		_log = log;
		Homm3HomecomingWaterTraversalBridge.EnterNodeAccepted += OnEnterNode;
		if (Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.cove.treasureHunting", OnDayStartHero, out var failure))
			log?.LogInfo(LogPrefix + "registered (enter-node + day-start).");
		else
			log?.LogWarning(LogPrefix + "day-start bus NOT registered (" + failure + "); enter-node only.");
	}

	private static void OnEnterNode(object worldHero, int node)
	{
		Tick();
		try
		{
			AiEnterNode(worldHero);
		}
		catch (Exception ex)
		{
			Warn("AI dig threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
		}
	}

	private static int OnDayStartHero(object entry)
	{
		Tick();
		return 0;
	}

	private static void Info(string message)
	{
		if (_logged++ < LogCap)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < LogCap)
			_log?.LogWarning(LogPrefix + message);
	}

	private static string N(int value) => value.ToString(CultureInfo.InvariantCulture);

	// ---------------------------------------------------------------- tick

	internal static void Tick()
	{
		if (_inTick)
			return;
		_inTick = true;
		try
		{
			var before = Version;
			TickCore();
			// The host also writes the save records, so it must exist once any region is planned.
			if (Version != before || PendingNotice != null || (_map != null && _map.Regions.Count > 0))
				Homm3CoveTreasureMarkers.EnsureHost();
		}
		catch (Exception ex)
		{
			Warn("tick threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
		}
		finally
		{
			_inTick = false;
		}
	}

	private static void TickCore()
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) || data == null)
			return;
		if (_map != null && _map.DataPointer != data.Pointer)
		{
			_map = null;
			_rankCache.Clear();
			_moveMax.Clear();
			_aiDugDay.Clear();
			_aiSide.Clear();
			_aiPayouts.Clear();
			_logged = 0;
			Version++;
		}
		CollectCoveHeroes(data);
		CountAiHunters();
		var localSide = LocalSide(data);
		var localHunter = false;
		foreach (var hero in _coveHeroes)
			localHunter |= hero.sideId == localSide;
		if (localHunter != LocalHunter)
		{
			LocalHunter = localHunter;
			if (localHunter)
				Homm3CoveTreasureMarkers.EnsureHost();
		}
		if (_coveHeroes.Count == 0)
			return;
		if (_map == null)
			_map = BuildMapState(data);
		var map = _map;
		if (map.Failed)
			return;
		LoadSaved(data, map);
		if (!map.SaveLoaded && map.SaveBlocked == null)
			return;
		MaterializeSaved(map);

		foreach (var hero in _coveHeroes)
		{
			var node = hero.node;
			var side = hero.sideId;
			if (side < 0 || side > 31)
				continue;
			TickPicks(data, map, hero, node, side);
			// law pass 2026-11-21: Spyglass Watch (#5)
			var radius = Homm3CoveLawHooks.SearchRadius(side);
			foreach (var areaId in AreasInSearchRange(map, node, radius))
			{
				var region = EnsureRegion(map, areaId);
				if (region == null)
					continue;
				for (var i = 0; i < region.Holders.Length; i++)
				{
					var h = region.Holders[i];
					var bit = 1u << side;
					if ((h.RevealedSides & bit) != 0 || Plan.Distance(node, h.Holder.Node, map.Width) > radius)
						continue;
					h.RevealedSides |= bit;
					Version++;
					Info("side " + N(side) + " hero " + hero.configSid + " found a map piece at node " + N(h.Holder.Node)
						+ " (area " + N(areaId) + ", " + Describe(h) + ").");
				}
			}
		}

		foreach (var region in map.Regions.Values)
		{
			for (var i = 0; i < region.Holders.Length; i++)
			{
				var h = region.Holders[i];
				if (!h.Loose && IsTaken(h))
				{
					// First sight of the holder being gone: a Cove hero standing next to it took the piece.
					h.Loose = true;
					Version++;
					var taker = NearestCoveHero(map, h.Holder.Node, 1, h.CollectedSides);
					if (taker != null)
						Collect(data, map, region, h, taker);
					else
						Info("holder at node " + N(h.Holder.Node) + " (area " + N(region.AreaId) + ") is gone with no Cove hero next to it: the piece stays on the tile.");
				}
				if (!h.Loose)
					continue;
				foreach (var hero in _coveHeroes)
				{
					var side = hero.sideId;
					if (side < 0 || side > 31 || hero.node != h.Holder.Node || (h.CollectedSides & (1u << side)) != 0)
						continue;
					Collect(data, map, region, h, hero);
				}
			}
		}
	}

	/// <summary>Archivist's bonus piece for the region the hero stands in, and the Lay of the Land terrain buff.</summary>
	private static void TickPicks(DataRoot data, MapState map, DataHero hero, int node, int side)
	{
		if (!map.AreaOfNode.TryGetValue(node, out var areaId))
		{
			Picks.RefreshLayOfTheLand(hero, 0);
			return;
		}
		var region = EnsureRegion(map, areaId);
		if (region == null)
			return;
		var bit = 1u << side;
		region.VisitedSides |= bit;
		region.PiecesBySide.TryGetValue(side, out var pieces);
		if (!region.Dug && (region.ArchivistSides & bit) == 0 && Picks.Has(hero, Picks.Archivist))
		{
			region.ArchivistSides |= bit;
			pieces++;
			region.PiecesBySide[side] = pieces;
			Version++;
			var leads = LeadCount(pieces, side);
			Info("side " + N(side) + " hero " + hero.configSid + " (Archivist) gained a bonus map piece in area " + N(areaId)
				+ ": pieces " + N(pieces) + ", possible treasure tiles now " + N(leads) + ".");
			if (side == LocalSide(data))
				Homm3CoveTreasurePopup.ShowPiece(areaId, pieces, Plan.PiecesPerRegion, leads, archivist: true, side: side);
		}
		Picks.RefreshLayOfTheLand(hero, pieces);
	}

	// ---------------------------------------------------------------- chart (Homm3CoveTreasureChart)

	/// <summary>The local player has a hero with Treasure Hunting on the map (as of the last tick).</summary>
	internal static bool LocalHunter { get; private set; }

	internal enum ChartState { Sea, NoTreasure, Uncharted, NoPieces, Pieces, Site, Yours, Rival }

	internal struct ChartRegion
	{
		internal int AreaId;
		internal ChartState State;
		internal int Pieces;
		internal int Leads;
		internal int Tiles;
	}

	internal sealed class ChartSnapshot
	{
		internal int Width;
		internal int Height;
		/// <summary>Area id per tile (index = node), -1 where the tile belongs to no area.</summary>
		internal int[] AreaOfTile;
		internal readonly List<ChartRegion> Regions = new();
	}

	/// <summary>What one side knows about every region, for the Treasure Chart. Null when the map is not ready.</summary>
	internal static ChartSnapshot SnapshotChart(int side)
	{
		var map = _map;
		if (map == null || map.Failed || map.AreaOfNode == null || map.Width <= 0 || map.Height <= 0 || side < 0 || side > 31)
			return null;
		var total = map.Width * map.Height;
		var snap = new ChartSnapshot { Width = map.Width, Height = map.Height, AreaOfTile = new int[total] };
		for (var i = 0; i < total; i++)
			snap.AreaOfTile[i] = -1;
		var tiles = new Dictionary<int, int>();
		foreach (var pair in map.AreaOfNode)
		{
			if (pair.Key < 0 || pair.Key >= total)
				continue;
			snap.AreaOfTile[pair.Key] = pair.Value;
			tiles.TryGetValue(pair.Value, out var n);
			tiles[pair.Value] = n + 1;
		}
		var bit = 1u << side;
		foreach (var pair in tiles)
		{
			var row = new ChartRegion { AreaId = pair.Key, Tiles = pair.Value, State = ChartState.Uncharted };
			// One area covering most of the map is the open sea on island maps: it holds no treasure.
			if (pair.Value * 5 > total * 2)
				row.State = ChartState.Sea;
			else if (map.Regions.TryGetValue(pair.Key, out var region))
			{
				region.PiecesBySide.TryGetValue(side, out var pieces);
				row.Pieces = Math.Min(pieces, Plan.PiecesPerRegion);
				row.Leads = LeadCount(pieces, side);
				if (region.Plan.TrueNode < 0)
					row.State = ChartState.NoTreasure;
				else if (region.Dug)
					row.State = region.DugSide == side ? ChartState.Yours : ChartState.Rival;
				else if (pieces > 0)
					row.State = row.Leads <= 1 ? ChartState.Site : ChartState.Pieces;
				else if ((region.VisitedSides & bit) != 0)
					row.State = ChartState.NoPieces;
			}
			snap.Regions.Add(row);
		}
		snap.Regions.Sort((a, b) => a.AreaId.CompareTo(b.AreaId));
		return snap;
	}

	/// <summary>The region of a tile, -1 when it has none or the map is not ready.</summary>
	internal static int AreaOf(int node)
	{
		var map = _map;
		return map != null && !map.Failed && map.AreaOfNode.TryGetValue(node, out var areaId) ? areaId : -1;
	}

	/// <summary>Whether that side dug up the region's treasure.</summary>
	internal static bool DugBy(int side, int areaId)
	{
		var map = _map;
		return map != null && !map.Failed && map.Regions.TryGetValue(areaId, out var region) && region.Dug && region.DugSide == side;
	}

	private static void CollectCoveHeroes(DataRoot data)
	{
		_coveHeroes.Clear();
		var list = data.heroes?.list;
		if (list == null)
			return;
		var day = data.daysInGameCount;
		var count = list.Count;
		for (var i = 0; i < count; i++)
		{
			var hero = list[i];
			if (hero == null || hero.status != Hex.Session.Data.EHeroStatus.OnMap || hero.node < 0)
				continue;
			var id = hero.field_Public_Int32_0;
			if (!_rankCache.TryGetValue(id, out var cached) || cached.Day != day)
			{
				cached = (day, Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(hero, CoveSkillSid));
				_rankCache[id] = cached;
			}
			if (cached.Rank <= 0)
				continue;
			_coveHeroes.Add(hero);
			// Highest movement seen today stands in for the daily maximum (Dig needs 2/3 of it).
			var move = hero.worldMovePoints;
			if (!_moveMax.TryGetValue(id, out var seen) || seen.Day != day || move > seen.Max)
				_moveMax[id] = (day, move);
		}
	}

	/// <summary>The most movement points this hero was seen with today (never less than it has now).</summary>
	internal static int MaxMoveToday(DataRoot data, DataHero hero)
	{
		var now = hero.worldMovePoints;
		return _moveMax.TryGetValue(hero.field_Public_Int32_0, out var seen) && seen.Day == data.daysInGameCount ? Math.Max(seen.Max, now) : now;
	}

	// ---------------------------------------------------------------- dig

	/// <summary>
	/// Whether this hero may dig on its tile at all. A refusal costs nothing; <paramref name="refusal"/> is the player
	/// text. Movement is the caller's check (Homm3CoveTreasureDig), between this and <see cref="CommitDig"/>.
	/// </summary>
	internal static bool CheckDig(DataRoot data, DataHero hero, out string refusal)
	{
		refusal = null;
		Tick();
		if (hero == null || Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(hero, CoveSkillSid) <= 0)
		{
			refusal = "Only a hero with Treasure Hunting can dig.";
			return false;
		}
		var map = _map;
		if (map == null || map.Failed || map.DataPointer != data.Pointer)
		{
			refusal = "There is no buried treasure on this map.";
			return false;
		}
		var node = hero.node;
		if (!map.AreaOfNode.TryGetValue(node, out var areaId))
		{
			refusal = "Nothing can be buried here.";
			return false;
		}
		if (map.Holes.Contains(node))
		{
			refusal = "This spot has already been dug up.";
			return false;
		}
		if (Homm3FactoryLogisticsMap.TryGetStaticGrid(out var grid, out _) && grid.W == map.Width && node >= 0 && node < grid.Block.Length
			&& (grid.Road[node] != 0 || grid.Water[node] != 0 || grid.Gate[node] != 0))
		{
			refusal = "You cannot dig on a road or on water.";
			return false;
		}
		if (EnsureRegion(map, areaId) == null)
		{
			refusal = "Nothing can be buried here.";
			return false;
		}
		return true;
	}

	/// <summary>Digs on the hero's tile after <see cref="CheckDig"/> passed and the movement was paid.</summary>
	internal static DigOutcome CommitDig(DataRoot data, DataHero hero, out Plan.Contents contents, out int areaId)
	{
		contents = null;
		areaId = -1;
		return hero == null ? DigOutcome.Refused : CommitDigAt(hero, hero.node, out contents, out areaId);
	}

	/// <summary>The dig on a given tile. The player digs under the hero; a computer hero digs a site within reach.</summary>
	private static DigOutcome CommitDigAt(DataHero hero, int node, out Plan.Contents contents, out int areaId)
	{
		contents = null;
		areaId = -1;
		var map = _map;
		if (map == null || map.Failed || hero == null || !map.AreaOfNode.TryGetValue(node, out areaId) || !map.Regions.TryGetValue(areaId, out var region))
			return DigOutcome.Refused;
		Version++;
		if (!region.Dug && node == region.Plan.TrueNode)
		{
			region.Dug = true;
			region.DugSide = hero.sideId;
			contents = region.Plan.Contents;
			Info("side " + N(hero.sideId) + " hero " + hero.configSid + " dug up the treasure of area " + N(areaId) + " at node " + N(node)
				+ " (value " + N(region.Plan.Value) + ").");
			return DigOutcome.Treasure;
		}
		map.Holes.Add(node);
		Info("side " + N(hero.sideId) + " hero " + hero.configSid + " dug at node " + N(node) + " (area " + N(areaId) + ") and found nothing: hole left.");
		return DigOutcome.Hole;
	}

	/// <summary>Called when a hero may have just learned the skill (level-up), so the next tick re-reads ranks.</summary>
	internal static void InvalidateRanks() => _rankCache.Clear();

	private static readonly int[] RangeOffsets = { 0, 0, -1, -1, 0, -1, 1, -1, -1, 0, 1, 0, -1, 1, 0, 1, 1, 1 };
	private static readonly List<int> _areaScratch = new();

	private static List<int> AreasInSearchRange(MapState map, int node, int radius = SearchRadius)
	{
		_areaScratch.Clear();
		var x = node % map.Width;
		var z = node / map.Width;
		for (var i = 0; i < RangeOffsets.Length; i += 2)
		{
			var px = x + RangeOffsets[i] * radius;
			var pz = z + RangeOffsets[i + 1] * radius;
			if (px < 0 || pz < 0 || px >= map.Width || pz >= map.Height)
				continue;
			if (map.AreaOfNode.TryGetValue(px + pz * map.Width, out var area) && !_areaScratch.Contains(area))
				_areaScratch.Add(area);
		}
		return _areaScratch;
	}

	private static bool IsTaken(HolderState h)
	{
		switch (h.Holder.Kind)
		{
			case Plan.HolderObject:
				return h.Object == null || h.Object.released;
			case Plan.HolderSquad:
				return h.Squad == null || h.Squad.released;
			default:
				return true;
		}
	}

	private static DataHero NearestCoveHero(MapState map, int node, int maxDistance, uint excludeSides)
	{
		DataHero best = null;
		var bestDistance = int.MaxValue;
		foreach (var hero in _coveHeroes)
		{
			var side = hero.sideId;
			if (side < 0 || side > 31 || (excludeSides & (1u << side)) != 0)
				continue;
			var d = Plan.Distance(hero.node, node, map.Width);
			if (d <= maxDistance && d < bestDistance)
			{
				best = hero;
				bestDistance = d;
			}
		}
		return best;
	}

	private static void Collect(DataRoot data, MapState map, RegionState region, HolderState h, DataHero hero)
	{
		var side = hero.sideId;
		var bit = 1u << side;
		if ((h.CollectedSides & bit) != 0)
			return;
		h.CollectedSides |= bit;
		h.RevealedSides |= bit;
		region.PiecesBySide.TryGetValue(side, out var pieces);
		pieces++;
		region.PiecesBySide[side] = pieces;
		Version++;
		var leads = LeadCount(pieces, side);
		Info("side " + N(side) + " hero " + hero.configSid + " took map piece " + N(pieces) + "/" + N(Plan.PiecesPerRegion)
			+ " in area " + N(region.AreaId) + " at node " + N(h.Holder.Node) + "; possible treasure tiles now " + N(leads) + ".");
		if (side == LocalSide(data))
			Homm3CoveTreasurePopup.ShowPiece(region.AreaId, pieces, Plan.PiecesPerRegion, leads, side: side);
		// law pass 2026-11-21: Finder's Fee (#9). Collect runs inside the native move, so the Gold is queued and
		// paid from the marker host's Update (FlushAiPayouts), like the computer's treasure payouts.
		var fee = Homm3CoveLawHooks.FindersFeeGold(side);
		if (fee > 0)
		{
			_findersFees.Add((side, fee));
			Homm3CoveTreasureMarkers.EnsureHost();
		}
	}

	private static readonly List<(int Side, int Gold)> _findersFees = new();

	/// <summary>Pays queued Finder's Fee Gold (law pass 2026-11-21, #9). Called from FlushAiPayouts.</summary>
	private static void FlushFindersFees()
	{
		if (_findersFees.Count == 0 || _inTick)
			return;
		var due = new List<(int Side, int Gold)>(_findersFees);
		_findersFees.Clear();
		foreach (var fee in due)
		{
			if (Homm3CovePlunderHook.Grant(fee.Side, GameSymbols.EconomyLaws.GoldResourceName, fee.Gold, out _, out _, out var fail))
				Info("side " + N(fee.Side) + " Finder's Fee paid " + N(fee.Gold) + " Gold for a map piece.");
			else
				Warn("side " + N(fee.Side) + " Finder's Fee of " + N(fee.Gold) + " Gold not paid: " + fail);
		}
	}

	/// <summary>How many candidate treasure tiles a side still sees with that many pieces (0 pieces: none shown).</summary>
	internal static int LeadCount(int pieces)
	{
		if (pieces <= 0)
			return 0;
		return Math.Max(1, 1 + Plan.FalseLeads - (pieces - 1));
	}

	// law pass 2026-11-21: Cartographers' Guild (#32). Each level removes one more false lead, as if the side held
	// one more piece; 0 pieces still shows nothing.
	internal static int LeadCount(int pieces, int side) => pieces <= 0 ? 0 : LeadCount(pieces + Homm3CoveLawHooks.FalseLeadsRemoved(side));

	/// <summary>First false node the side still sees: piece 2 removes FalseNodes[0], piece 3 [1], piece 4 [2].</summary>
	internal static int FalseLeadStart(int pieces, int side) => Math.Max(0, pieces - 1 + Homm3CoveLawHooks.FalseLeadsRemoved(side));

	internal static int LocalSide(DataRoot data)
	{
		try { return data?.sides == null ? -1 : data.sides.myIndex; }
		catch { return -1; }
	}

	private static string Describe(HolderState h)
	{
		switch (h.Holder.Kind)
		{
			case Plan.HolderObject:
				return "object " + (h.Object?.sidConfig ?? "?") + " #" + h.Holder.Key.ToString(CultureInfo.InvariantCulture);
			case Plan.HolderSquad:
				return "stack " + (h.Squad?.configSid ?? "?") + " #" + h.Holder.Key.ToString(CultureInfo.InvariantCulture);
			default:
				return "loose";
		}
	}

	// ---------------------------------------------------------------- queries for the marker layer and Dig

	/// <summary>Everything the side may see on the map right now. Returns false when there is nothing to show.</summary>
	internal static bool CollectMarkers(int side, List<Marker> into)
	{
		into.Clear();
		var map = _map;
		if (map == null || map.Failed || side < 0 || side > 31)
			return false;
		var bit = 1u << side;
		foreach (var hole in map.Holes)
			into.Add(new Marker { Node = hole, AreaId = -1, Kind = MarkerKind.Hole });
		foreach (var region in map.Regions.Values)
		{
			if (region.Dug)
				continue;
			foreach (var h in region.Holders)
			{
				if ((h.RevealedSides & bit) == 0 || (h.CollectedSides & bit) != 0)
					continue;
				into.Add(new Marker { Node = h.Holder.Node, AreaId = region.AreaId, Kind = h.Loose ? MarkerKind.LoosePiece : MarkerKind.Piece });
			}
			region.PiecesBySide.TryGetValue(side, out var pieces);
			if (pieces <= 0 || region.Plan.TrueNode < 0)
				continue;
			var leads = LeadCount(pieces, side);
			into.Add(new Marker { Node = region.Plan.TrueNode, AreaId = region.AreaId, Kind = leads <= 1 ? MarkerKind.Treasure : MarkerKind.Lead });
			var falseNodes = region.Plan.FalseNodes;
			// Piece 2 removes FalseNodes[0], piece 3 removes [1], piece 4 removes [2] (Cartographers' Guild, #32, removes more).
			for (var i = FalseLeadStart(pieces, side); i < falseNodes.Length && leads > 1; i++)
				if (!map.Holes.Contains(falseNodes[i]))
					into.Add(new Marker { Node = falseNodes[i], AreaId = region.AreaId, Kind = MarkerKind.Lead });
		}
		return into.Count > 0;
	}

	/// <summary>Whether the tile is one of the region's false treasure sites (a "?" lead for someone).</summary>
	internal static bool IsFalseLead(int areaId, int node)
	{
		var map = _map;
		return map != null && !map.Failed && map.Regions.TryGetValue(areaId, out var region) && Array.IndexOf(region.Plan.FalseNodes, node) >= 0;
	}

	internal static int MapWidth => _map == null || _map.Failed ? 0 : _map.Width;

	/// <summary>Pieces the side holds in a region (0 when the region has no plan yet).</summary>
	internal static int PiecesOf(int side, int areaId)
	{
		var map = _map;
		if (map == null || map.Failed || !map.Regions.TryGetValue(areaId, out var region))
			return 0;
		region.PiecesBySide.TryGetValue(side, out var pieces);
		return pieces;
	}

	// ---------------------------------------------------------------- per-map tables

	private static MapState BuildMapState(DataRoot data)
	{
		var watch = System.Diagnostics.Stopwatch.StartNew();
		var map = new MapState { DataPointer = data.Pointer };
		if (!Homm3FactoryLogisticsMap.TryGetMapData(out var mapData, out var fail))
			return FailMap(map, "static map data unavailable: " + fail);
		map.Width = mapData.sizeX_;
		map.Height = mapData.sizeZ_;
		if (map.Width <= 0 || map.Height <= 0)
			return FailMap(map, "map size unreadable");
		var areas = data.areas?.list;
		if (areas == null || areas.Count == 0)
			return FailMap(map, "no native regions on this map");
		if (areas.Count == 1)
			return FailMap(map, "single-region map: treasure hunting is not placed here yet (region detection deferred)");

		unchecked
		{
			map.Seed = ((ulong)(uint)data.mapGeneratorChecksum << 32) ^ (uint)mapData.cliffRandomSeed
				^ ((ulong)(uint)(map.Width * 73856093) << 16) ^ (ulong)(uint)(map.Height * 19349663);
		}

		map.AreaOfNode = new Dictionary<int, int>(map.Width * map.Height);
		map.Areas = new Dictionary<int, DataArea>(areas.Count);
		for (var i = 0; i < areas.Count; i++)
		{
			var area = areas[i];
			if (area == null)
				continue;
			var id = area.field_Public_Int32_0;
			map.Areas[id] = area;
			var nodes = area.nodes;
			var n = nodes == null ? 0 : nodes.Count;
			for (var k = 0; k < n; k++)
				map.AreaOfNode[nodes[k]] = id;
		}

		// Live objects and stacks, by id. Only pickable object kinds hold pieces in this version.
		map.LiveObjects = new Dictionary<int, DataObject>();
		var pickableSids = new HashSet<string>(StringComparer.Ordinal);
		var objects = data.objects;
		if (objects != null)
		{
			AddLive(map, pickableSids, objects.chestObjs);
			AddLive(map, pickableSids, objects.resObjs);
			AddLive(map, pickableSids, objects.itemObjs);
		}
		map.LiveSquads = new Dictionary<int, DataSquad>();
		var squads = data.squads?.list;
		for (var i = 0; squads != null && i < squads.Count; i++)
		{
			var squad = squads[i];
			if (squad != null)
				map.LiveSquads[squad.field_Public_Int32_0] = squad;
		}

		var cityIds = new HashSet<int>();
		var cities = objects?.cityObjs;
		for (var i = 0; cities != null && i < cities.Count; i++)
		{
			var city = cities[i];
			if (city != null)
				cityIds.Add(city.idMapObject);
		}

		// Static (as generated) object and stack positions: the candidate pool never changes during the game.
		map.StaticOccupied = new HashSet<int>();
		map.HolderCandidates = new Dictionary<int, List<Plan.Holder>>();
		var cityNodes = new List<int>();
		var staticObjects = mapData.objects;
		var pending = new List<Plan.Holder>();
		for (var g = 0; staticObjects != null && g < staticObjects.Length; g++)
		{
			var group = staticObjects[g];
			if (group == null)
				continue;
			var ids = group.field_Public_Il2CppStructArray_1_Int32_0;
			var nodes = group.nodes;
			if (ids == null || nodes == null)
				continue;
			var pickable = pickableSids.Contains(group.field_Public_String_0 ?? string.Empty);
			var n = Math.Min(ids.Length, nodes.Length);
			for (var i = 0; i < n; i++)
			{
				var node = nodes[i];
				map.StaticOccupied.Add(node);
				if (cityIds.Contains(ids[i]))
					cityNodes.Add(node);
				if (pickable)
					pending.Add(new Plan.Holder { Node = node, Key = ids[i], Kind = Plan.HolderObject });
			}
		}
		var squadNodes = new HashSet<int>();
		var staticSquads = mapData.squads;
		for (var g = 0; staticSquads != null && g < staticSquads.Length; g++)
		{
			var group = staticSquads[g];
			if (group == null)
				continue;
			var ids = group.field_Public_List_1_Int32_0;
			var nodes = group.nodes;
			if (ids == null || nodes == null)
				continue;
			var n = Math.Min(ids.Count, nodes.Count);
			for (var i = 0; i < n; i++)
			{
				var node = nodes[i];
				map.StaticOccupied.Add(node);
				squadNodes.Add(node);
				pending.Add(new Plan.Holder { Node = node, Key = ids[i], Kind = Plan.HolderSquad, Guarded = true });
			}
		}
		// Generated maps keep their neutral stacks only in the session data (the static squad groups are empty), so
		// every live stack not listed above is a holder candidate and a guard too.
		var staticSquadCount = squadNodes.Count;
		foreach (var pair in map.LiveSquads)
		{
			var node = pair.Value.node;
			if (node < 0 || !squadNodes.Add(node))
				continue;
			map.StaticOccupied.Add(node);
			pending.Add(new Plan.Holder { Node = node, Key = pair.Key, Kind = Plan.HolderSquad, Guarded = true });
		}
		var holders = 0;
		var guardedCount = 0;
		foreach (var candidate in pending)
		{
			var holder = candidate;
			// An object counts as guarded when a neutral stack stands within GuardRange tiles of it.
			if (holder.Kind == Plan.HolderObject)
				holder.Guarded = HasNodeWithin(squadNodes, holder.Node, GuardRange, map.Width, map.Height);
			if (holder.Guarded)
				guardedCount++;

			if (!map.AreaOfNode.TryGetValue(holder.Node, out var areaId))
				continue;
			var nearCity = false;
			foreach (var cityNode in cityNodes)
			{
				if (Plan.Distance(cityNode, holder.Node, map.Width) <= CityHolderExclusion)
				{
					nearCity = true;
					break;
				}
			}
			if (nearCity)
				continue;
			if (!map.HolderCandidates.TryGetValue(areaId, out var list))
				map.HolderCandidates[areaId] = list = new List<Plan.Holder>();
			list.Add(holder);
			holders++;
		}
		foreach (var list in map.HolderCandidates.Values)
			list.Sort((a, b) => a.Node != b.Node ? a.Node.CompareTo(b.Node) : a.Kind != b.Kind ? a.Kind.CompareTo(b.Kind) : a.Key.CompareTo(b.Key));

		watch.Stop();
		Info("map tables built in " + watch.Elapsed.TotalMilliseconds.ToString("0.0", CultureInfo.InvariantCulture) + " ms: "
			+ N(map.Width) + "x" + N(map.Height) + ", regions=" + N(map.Areas.Count) + ", holder candidates=" + N(holders)
			+ " (guarded=" + N(guardedCount) + ", static stacks=" + N(staticSquadCount) + ", pickable kinds=" + N(pickableSids.Count) + ", live objects=" + N(map.LiveObjects.Count) + ", live stacks=" + N(map.LiveSquads.Count)
			+ "), cities=" + N(cityNodes.Count) + ".");
		return map;
	}

	private static void AddLive<T>(MapState map, HashSet<string> sids, Il2CppSystem.Collections.Generic.List<T> list) where T : DataObject
	{
		if (list == null)
			return;
		var count = list.Count;
		for (var i = 0; i < count; i++)
		{
			var o = list[i];
			if (o == null)
				continue;
			map.LiveObjects[o.idMapObject] = o;
			var sid = o.sidConfig;
			if (!string.IsNullOrEmpty(sid))
				sids.Add(sid);
		}
	}

	private static bool HasNodeWithin(HashSet<int> nodes, int node, int range, int width, int height)
	{
		var x = node % width;
		var z = node / width;
		for (var dz = -range; dz <= range; dz++)
		{
			var pz = z + dz;
			if (pz < 0 || pz >= height)
				continue;
			for (var dx = -range; dx <= range; dx++)
			{
				var px = x + dx;
				if (px >= 0 && px < width && nodes.Contains(px + pz * width))
					return true;
			}
		}
		return false;
	}

	private static MapState FailMap(MapState map, string why)
	{
		map.Failed = true;
		Warn("disabled for this game: " + why + ".");
		return map;
	}

	private static RegionState EnsureRegion(MapState map, int areaId)
	{
		if (map.Regions.TryGetValue(areaId, out var existing))
			return existing;
		if (!map.Areas.TryGetValue(areaId, out var area))
			return null;
		// The game fills the region values a little after the map loads. Planning before that would price every
		// treasure at the floor, so wait until at least one region has a value.
		if (!map.RichnessReady)
		{
			foreach (var a in map.Areas.Values)
			{
				if (a.pickableObjectsValuesOnStart > 0)
				{
					map.RichnessReady = true;
					break;
				}
			}
			if (!map.RichnessReady)
				return null;
		}
		var watch = System.Diagnostics.Stopwatch.StartNew();
		var dig = new List<int>();
		var tiles = 0;
		if (Homm3FactoryLogisticsMap.TryGetStaticGrid(out var grid, out var gridFail) && grid.W == map.Width)
		{
			var nodes = area.nodes;
			tiles = nodes == null ? 0 : nodes.Count;
			for (var i = 0; i < tiles; i++)
			{
				var node = nodes[i];
				if (node < 0 || node >= grid.Block.Length)
					continue;
				if (grid.Block[node] != Homm3FactoryLogisticsMap.BlockNone || grid.Gate[node] != 0 || grid.Road[node] != 0 || grid.Water[node] != 0)
					continue;
				if (map.StaticOccupied.Contains(node))
					continue;
				dig.Add(node);
			}
			dig.Sort();
		}
		else
		{
			Warn("area " + N(areaId) + ": static grid unavailable (" + gridFail + "); no treasure tiles placed.");
		}
		map.HolderCandidates.TryGetValue(areaId, out var holders);
		var input = new Plan.RegionInput
		{
			RegionId = areaId,
			Width = map.Width,
			TileCount = tiles,
			HolderCandidates = holders ?? new List<Plan.Holder>(),
			DigCandidates = dig,
			Richness = area.pickableObjectsValuesOnStart,
		};
		map.Catalog ??= LoadCatalog();
		var plan = Plan.Build(map.Seed, input, map.Catalog, Plan.AnchorK);
		var saved = TakeSaved(map, areaId);
		if (saved != null)
			ApplySavedPlan(map, plan, saved, input.HolderCandidates);
		var region = new RegionState { AreaId = areaId, Plan = plan, Holders = new HolderState[plan.Pieces.Length] };
		for (var i = 0; i < plan.Pieces.Length; i++)
		{
			var holder = plan.Pieces[i];
			var state = new HolderState { Holder = holder };
			if (holder.Kind == Plan.HolderObject)
				map.LiveObjects.TryGetValue((int)holder.Key, out state.Object);
			else if (holder.Kind == Plan.HolderSquad)
				map.LiveSquads.TryGetValue((int)holder.Key, out state.Squad);
			else
				state.Loose = true;
			region.Holders[i] = state;
		}
		if (saved != null)
			ApplySavedState(region, saved);
		map.Regions[areaId] = region;
		watch.Stop();
		var text = new System.Text.StringBuilder();
		foreach (var h in region.Holders)
			text.Append(' ').Append(N(h.Holder.Node)).Append(':').Append(Describe(h)).Append(h.Holder.Guarded ? "(guarded)" : "");
		Info("area " + N(areaId) + " planned in " + watch.Elapsed.TotalMilliseconds.ToString("0.00", CultureInfo.InvariantCulture) + " ms: tiles=" + N(tiles)
			+ " dig candidates=" + N(dig.Count) + " holder candidates=" + N(holders?.Count ?? 0) + " spacing " + N(plan.StartSpacing) + "->" + N(plan.FinalSpacing)
			+ " value=" + N(plan.Value) + " contents=[" + DescribeContents(plan.Contents) + "] treasure node=" + N(plan.TrueNode) + " false=[" + string.Join(",", plan.FalseNodes) + "] pieces:" + text + ".");
		return region;
	}

	// ---------------------------------------------------------------- treasure catalog

	internal const string CatalogFile = "treasure_catalog.tsv";

	/// <summary>
	/// Artifacts and nonliving units a treasure may hold, with their Core values (built by
	/// tools/cove_treasure/build_treasure_catalog.py). Missing or unreadable: treasures hold gold and resources only.
	/// </summary>
	private static readonly Dictionary<string, string> DisplayNames = new(StringComparer.Ordinal);

	/// <summary>The English in-game name of an artifact, unit or resource from the catalog; null when it has none.</summary>
	internal static string DisplayName(string sid) => sid != null && DisplayNames.TryGetValue(sid, out var name) ? name : null;

	private static Plan.Catalog LoadCatalog()
	{
		var artifacts = new List<Plan.ArtifactEntry>();
		var units = new List<Plan.UnitEntry>();
		var path = System.IO.Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", "homm3_ui", "cove_treasure", CatalogFile);
		try
		{
			foreach (var line in System.IO.File.ReadAllLines(path))
			{
				var cells = line.Split('\t');
				if (cells.Length >= 3 && cells[0] == "A" && int.TryParse(cells[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
				{
					artifacts.Add(new Plan.ArtifactEntry { Sid = cells[1], Value = value });
					if (cells.Length >= 4 && cells[3].Length > 0)
						DisplayNames[cells[1]] = cells[3];
				}
				else if (cells.Length >= 3 && cells[0] == "N" && cells[2].Length > 0)
					DisplayNames[cells[1]] = cells[2];
				else if (cells.Length >= 4 && cells[0] == "U" && int.TryParse(cells[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out var squadValue)
					&& int.TryParse(cells[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out var tier))
				{
					units.Add(new Plan.UnitEntry { Sid = cells[1], SquadValue = squadValue, Tier = tier });
					if (cells.Length >= 5 && cells[4].Length > 0)
						DisplayNames[cells[1]] = cells[4];
				}
			}
			Info("catalog: " + N(artifacts.Count) + " artifacts, " + N(units.Count) + " units from " + path + ".");
		}
		catch (Exception ex)
		{
			artifacts.Clear();
			units.Clear();
			Warn("catalog unreadable (" + ex.GetBaseException().Message + "): treasures hold gold and resources only.");
		}
		return new Plan.Catalog { Artifacts = artifacts, Units = units };
	}

	internal static string DescribeContents(Plan.Contents c)
	{
		if (c == null)
			return "none";
		var text = new System.Text.StringBuilder();
		text.Append(N(c.Gold)).Append(" gold");
		foreach (var (name, amount) in c.Resources)
			text.Append(", ").Append(N(amount)).Append(' ').Append(name);
		if (c.ArtifactSid != null)
			text.Append(", artifact ").Append(c.ArtifactSid);
		if (c.UnitSid != null)
			text.Append(", ").Append(N(c.UnitCount)).Append(' ').Append(c.UnitSid);
		return text.ToString();
	}
}
