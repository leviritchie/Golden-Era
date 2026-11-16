using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network range engine (lane CORE-B; API in docs/factory_logistics_runtime_contract.md,
/// rules in docs/factory_logistics_network_design.md "Logistics range").
///
/// Model:
/// - Tiles: native node index = x + y*MapWidth (square grid, 8 neighbours, no corner-cut check, like the
///   native GroundPathfinder). Node.X/Y are those native coordinates; Node.Level is informational only
///   (surface and underground share one grid).
/// - Step cost of entering a tile: 10 MP orthogonal / 14 MP diagonal, times (1 - pathmap roadBonus), at least
///   3 (vanilla Formulas.CalculateMoveCost with the terrain penalty dropped): road 0.2 -> 8/11, road 0.3 -> 7/10.
/// - Blocked: pathmap nodesBlocked (object bodies, blocked cliffs), waterMap != 0, void tiles, tiles the side has
///   not explored, and every neutral guard zone (squad tile + 8 neighbours). Object entrances are walkable.
///   Network node tiles (sources/targets) are walkable even when their tile is an object body.
/// - Budget of a route = source.RangeLevels x mpPerLevel. Entering a hub tile (any node with HubRefresh &gt; 0)
///   with remaining R &gt;= 0 gives R' = min(B, R + floor((B - R) x HubRefresh)) (spec example: B=100, spent 50,
///   L1 hub 0.33 -> 66 remaining).
/// - Best route = the one arriving with the most remaining range. If none arrives, the route that misses by the
///   fewest MP (cheapest path, hubs on the way still refresh), truncated at the last affordable tile.
/// - Blockers: for every unreached pair, the cheapest path that ignores guard zones is checked; a stack is
///   reported when its zone alone covers every guarded tile of that path and the path fits the budget.
///
/// Pure solver code below <see cref="SolveCore"/> is mirrored by tools/factory_logistics/range_harness.
/// Proof tier: source/static + offline harness; runtime unproven.
/// </summary>
internal static class Homm3FactoryLogisticsRange
{
	internal const int OrthBaseMp = 10;
	internal const int DiagBaseMp = 14;
	internal const int MinStepMp = 3;
	private const int Inf = int.MaxValue;
	private const int NoLabel = int.MinValue;
	private const int MaxFloodWorkers = 4;

	internal sealed class Node
	{
		public long Key;
		public string Kind;        // building | town | hero
		public int X, Y, Level;
		public int RangeLevels;    // logistics level (+ own Rail Network bonus) for routes starting here
		public double HubRefresh;  // 0..1 fraction of spent range refreshed when a route passes through
	}

	internal sealed class Route
	{
		public long From, To;
		public bool Reached;
		public List<(int x, int y)> Tiles;
		public int MissingMp;
		// Added by CORE-B (contract allows additions):
		public string FromKind, ToKind;
		public bool NoPath;            // no path at all (fog, water, objects, guards); Tiles = source tile, MissingMp = 0
		public int SpentMp;            // path cost of the shown tiles, before hub refreshes
		public List<long> ViaHubs;     // hub node keys the route passes, in order (empty when direct)
	}

	internal sealed class Blocker
	{
		public int X, Y;
		public long GuardKey;          // Data squad id
		public List<(long from, long to)> WouldLink;
	}

	internal sealed class Result
	{
		public List<Route> Routes;
		public List<Blocker> Blockers;
		// Added by CORE-B:
		public double SolveMs;
		public int GuardedTiles, Squads;
		/// <summary>"kind:key (x,y)->(x,y)" for nodes moved off an enclosed tile (see AnchorNode).</summary>
		public List<string> Anchored = new();
		/// <summary>"from->to" with both node tiles' state, for routes with no path at all (diagnostics).</summary>
		public List<string> NoPathNotes = new();
	}

	/// <summary>Grid inputs of one solve (pure data; built from the live map or by the offline harness).</summary>
	internal sealed class GridInput
	{
		public int W, H;
		public byte[] Block;        // != 0 blocked (static)
		public byte[] CostOrth, CostDiag;
		public bool[] Visible;      // null = everything explored
		public byte[] Gate;         // != 0 object entrance (null = unknown)
		public List<Homm3FactoryLogisticsMap.SquadInfo> Squads;
	}

	internal static int MapWidth => Homm3FactoryLogisticsMap.TryGetStaticGrid(out var g, out _) ? g.W : 0;
	internal static int MapHeight => Homm3FactoryLogisticsMap.TryGetStaticGrid(out var g, out _) ? g.H : 0;

	/// <summary>Drop cached map data (call on day start, map load, or after map objects change).</summary>
	internal static void Invalidate() => Homm3FactoryLogisticsMap.Invalidate();

	internal static bool TryNodeToTile(int node, out int x, out int y)
	{
		x = y = -1;
		if (!Homm3FactoryLogisticsMap.TryGetStaticGrid(out var g, out _) || node < 0 || node >= g.W * g.H)
			return false;
		x = node % g.W;
		y = node / g.W;
		return true;
	}

	internal static bool TryGetTile(int x, int y, int level, int sideId, out byte terrain, out bool road,
		out bool water, out bool blocked, out bool fogged)
	{
		terrain = 0;
		road = water = blocked = false;
		fogged = true;
		if (!Homm3FactoryLogisticsMap.TryGetStaticGrid(out var g, out _))
			return false;
		if (x < 0 || y < 0 || x >= g.W || y >= g.H)
			return false;
		if (!Homm3FactoryLogisticsMap.TryGetFogVisible(sideId, g, out var visible, out _))
			return false;
		var n = x + y * g.W;
		terrain = g.Terrain[n];
		road = g.Road[n] != 0;
		water = g.Water[n] != 0;
		blocked = g.Block[n] != Homm3FactoryLogisticsMap.BlockNone;
		fogged = !visible[n];
		return true;
	}

	internal static bool TrySolve(int sideId, IReadOnlyList<Node> sources, IReadOnlyList<Node> targets,
		int mpPerLevel, out Result result, out string fail, IReadOnlyList<Node> extraHubs = null)
	{
		result = null;
		try
		{
			var sw = Stopwatch.StartNew();
			if (!Homm3FactoryLogisticsMap.TryGetStaticGrid(out var grid, out fail))
				return Fail("map: " + fail, out fail);
			EnsureCosts(grid);
			if (!Homm3FactoryLogisticsMap.TryGetFogVisible(sideId, grid, out var visible, out fail))
				return Fail("fog: " + fail, out fail);
			var squads = new List<Homm3FactoryLogisticsMap.SquadInfo>();
			if (!Homm3FactoryLogisticsMap.TryGetSquads(grid, squads, out fail))
				return Fail("squads: " + fail, out fail);
			var input = new GridInput
			{
				W = grid.W, H = grid.H, Block = grid.Block, CostOrth = grid.CostOrth, CostDiag = grid.CostDiag,
				Visible = visible, Squads = squads, Gate = grid.Gate,
			};
			if (!SolveCore(input, sources, targets, mpPerLevel, out result, out fail, extraHubs))
				return Fail(fail, out fail);
			sw.Stop();
			result.SolveMs = sw.Elapsed.TotalMilliseconds;
			var reached = 0;
			var cut = 0;
			var noPath = 0;
			foreach (var r in result.Routes)
			{
				if (r.Reached) reached++;
				else if (r.NoPath) noPath++;
				else cut++;
			}
			var line = "solve side=" + sideId.ToString(CultureInfo.InvariantCulture)
				+ " sources=" + (sources?.Count ?? 0).ToString(CultureInfo.InvariantCulture)
				+ " targets=" + (targets?.Count ?? 0).ToString(CultureInfo.InvariantCulture)
				+ " routes=" + result.Routes.Count.ToString(CultureInfo.InvariantCulture)
				+ " reached=" + reached.ToString(CultureInfo.InvariantCulture)
				+ " cut=" + cut.ToString(CultureInfo.InvariantCulture)
				+ " noPath=" + noPath.ToString(CultureInfo.InvariantCulture)
				+ " squads=" + result.Squads.ToString(CultureInfo.InvariantCulture)
				+ " blockers=" + result.Blockers.Count.ToString(CultureInfo.InvariantCulture)
				+ " ms=" + result.SolveMs.ToString("0.0", CultureInfo.InvariantCulture)
				+ (result.Anchored.Count > 0 ? " anchored=[" + string.Join("; ", result.Anchored) + "]" : "")
				+ (result.NoPathNotes.Count > 0 ? " nopath=[" + string.Join("; ", result.NoPathNotes) + "]" : "");
			if (result.SolveMs > 50.0)
				Homm3FactoryLogisticsMap.LogWarning(line + " (slow)");
			else
				Homm3FactoryLogisticsMap.LogInfo(line);
			return true;
		}
		catch (Exception ex)
		{
			result = null;
			return Fail("exception " + ex.GetType().Name + ": " + ex.Message, out fail);
		}
	}

	/// <summary>Live grid input (static grid, fog of <paramref name="sideId"/>, neutral squads) for the reach/explain helpers.</summary>
	private static bool TryLiveInput(int sideId, out GridInput input, out string fail)
	{
		input = null;
		if (!Homm3FactoryLogisticsMap.TryGetStaticGrid(out var grid, out fail))
			return false;
		EnsureCosts(grid);
		if (!Homm3FactoryLogisticsMap.TryGetFogVisible(sideId, grid, out var visible, out fail))
			return false;
		var squads = new List<Homm3FactoryLogisticsMap.SquadInfo>();
		if (!Homm3FactoryLogisticsMap.TryGetSquads(grid, squads, out fail))
			return false;
		input = new GridInput { W = grid.W, H = grid.H, Block = grid.Block, CostOrth = grid.CostOrth, CostDiag = grid.CostDiag, Visible = visible, Squads = squads, Gate = grid.Gate };
		return true;
	}

	/// <summary>
	/// Viewer range overlay: every tile a route from <paramref name="source"/> can reach (see <see cref="ReachCore"/>).
	/// Fails closed with a reason; never throws.
	/// </summary>
	internal static bool TryReach(int sideId, Node source, int mpPerLevel, IReadOnlyList<Node> hubs, out int[] remaining, out bool[] viaHub, out int width, out string fail)
	{
		remaining = null;
		viaHub = null;
		width = 0;
		try
		{
			if (!TryLiveInput(sideId, out var input, out fail))
				return false;
			width = input.W;
			return ReachCore(input, source, Math.Max(0, source.RangeLevels) * mpPerLevel, hubs, out remaining, out viaHub, out fail);
		}
		catch (Exception ex)
		{
			fail = "reach threw " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	/// <summary>Why no path at all joins two nodes (live grid); null reason when they are in fact connected.</summary>
	internal static bool TryExplainNoPath(int sideId, Node from, Node to, out string reason, out string fail)
	{
		reason = null;
		try
		{
			if (!TryLiveInput(sideId, out var input, out fail))
				return false;
			reason = ExplainNoPathCore(input, from, to);
			return true;
		}
		catch (Exception ex)
		{
			fail = "explain threw " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool Fail(string reason, out string fail)
	{
		fail = reason;
		Homm3FactoryLogisticsMap.LogError("solve failed (fail-closed): " + reason);
		return false;
	}

	internal static void EnsureCosts(Homm3FactoryLogisticsMap.StaticGrid grid)
	{
		if (grid.CostOrth != null && grid.CostDiag != null)
			return;
		var n = grid.W * grid.H;
		var orth = new byte[n];
		var diag = new byte[n];
		for (var i = 0; i < n; i++)
		{
			var rb = grid.RoadBonus != null ? grid.RoadBonus[i] : 0f;
			orth[i] = StepCost(rb, false);
			diag[i] = StepCost(rb, true);
		}
		grid.CostOrth = orth;
		grid.CostDiag = diag;
	}

	internal static byte StepCost(float roadBonus, bool diagonal)
	{
		var rb = roadBonus < 0f ? 0f : roadBonus > 1f ? 1f : roadBonus;
		var raw = (diagonal ? DiagBaseMp : OrthBaseMp) * (1.0 - rb);
		var cost = (int)Math.Round(raw, MidpointRounding.AwayFromZero);
		return (byte)(cost < MinStepMp ? MinStepMp : cost);
	}

	internal static int ApplyHubRefresh(int remaining, int budget, double refresh)
	{
		if (remaining < 0 || refresh <= 0.0)
			return remaining;
		var spent = budget - remaining;
		if (spent <= 0)
			return remaining;
		var gain = (int)Math.Floor(spent * refresh + 1e-9);
		var r = remaining + gain;
		return r > budget ? budget : r;
	}

	// ------------------------------------------------------------------------------------------------
	// Pure solver
	// ------------------------------------------------------------------------------------------------

	private static readonly int[] Dx = { 1, -1, 0, 0, 1, 1, -1, -1 };
	private static readonly int[] Dy = { 0, 0, 1, -1, 1, -1, 1, -1 };

	/// <summary>Per-flood scratch (one per worker thread).</summary>
	private sealed class FloodState
	{
		public readonly int N;
		public readonly int[] Dist;
		public readonly int[] Stamp;
		public int CurStamp;
		public readonly int[][] Buckets = new int[16][];
		public readonly int[] BucketCount = new int[16];

		public FloodState(int n)
		{
			N = n;
			Dist = new int[n];
			Stamp = new int[n];
			for (var i = 0; i < Buckets.Length; i++)
				Buckets[i] = new int[1024];
		}

		public void Push(int bucket, int node)
		{
			var arr = Buckets[bucket];
			var c = BucketCount[bucket];
			if (c == arr.Length)
			{
				Array.Resize(ref arr, arr.Length * 2);
				Buckets[bucket] = arr;
			}
			arr[c] = node;
			BucketCount[bucket] = c + 1;
		}

		public int NextStamp()
		{
			if (CurStamp == int.MaxValue)
			{
				Array.Clear(Stamp, 0, N);
				CurStamp = 0;
			}
			return ++CurStamp;
		}
	}

	private sealed class Workspace
	{
		public readonly int N;
		public readonly byte[] IsNode;
		public readonly int[] Guard;
		public readonly byte[] Pass;   // PassWalk | PassGuardFree | PassExpand, rebuilt per solve
		public readonly List<byte[]> ParentPool = new();
		public readonly List<FloodState> States = new();

		public Workspace(int n)
		{
			N = n;
			IsNode = new byte[n];
			Guard = new int[n];
			Pass = new byte[n];
		}

		public byte[] Parent(int index)
		{
			while (ParentPool.Count <= index)
				ParentPool.Add(new byte[N]);
			return ParentPool[index];
		}

		public FloodState State(int index)
		{
			while (States.Count <= index)
				States.Add(new FloodState(N));
			return States[index];
		}
	}

	private static Workspace _ws;

	private sealed class Hub
	{
		public int Tile;
		public double Refresh;
		public long Key;
		public int Origin;
	}

	/// <param name="extraHubs">Extra hub-only nodes (Supply Caravan heroes): they refresh routes passing their tile but are
	/// neither sources nor targets.</param>
	internal static bool SolveCore(GridInput g, IReadOnlyList<Node> sources, IReadOnlyList<Node> targets,
		int mpPerLevel, out Result result, out string fail, IReadOnlyList<Node> extraHubs = null)
	{
		result = null;
		fail = null;
		if (g == null || g.W <= 0 || g.H <= 0 || g.Block == null || g.CostOrth == null || g.CostDiag == null)
		{
			fail = "grid input incomplete";
			return false;
		}
		if (sources == null || targets == null)
		{
			fail = "sources/targets null";
			return false;
		}
		if (mpPerLevel <= 0)
		{
			fail = "mpPerLevel must be > 0 (got " + mpPerLevel + ")";
			return false;
		}
		var w = g.W;
		var n = w * g.H;
		if (g.Block.Length != n || g.CostOrth.Length != n || g.CostDiag.Length != n || (g.Visible != null && g.Visible.Length != n))
		{
			fail = "grid array lengths differ from " + w + "x" + g.H;
			return false;
		}
		var allNodes = new List<Node>(sources.Count + targets.Count);
		foreach (var node in sources)
			if (!AddNode(node, "source", w, g.H, allNodes, out fail))
				return false;
		foreach (var node in targets)
			if (!AddNode(node, "target", w, g.H, allNodes, out fail))
				return false;
		if (extraHubs != null)
			foreach (var node in extraHubs)
				if (!AddNode(node, "caravan waypoint", w, g.H, allNodes, out fail))
					return false;
		var anchored = new List<string>();
		foreach (var node in allNodes)
		{
			var before = (node.X, node.Y);
			if (AnchorNode(g, node))
				anchored.Add(node.Kind + ":" + node.Key + " (" + before.X + "," + before.Y + ")->(" + node.X + "," + node.Y + ")");
		}

		var ws = _ws;
		if (ws == null || ws.N != n)
			_ws = ws = new Workspace(n);

		// Node tiles (distinct) and hubs (distinct tiles, strongest refresh wins).
		var nodeTileIndex = new Dictionary<int, int>();
		var nodeTiles = new List<int>();
		var hubByTile = new Dictionary<int, Hub>();
		foreach (var node in allNodes)
		{
			var t = node.X + node.Y * w;
			if (!nodeTileIndex.ContainsKey(t))
			{
				nodeTileIndex[t] = nodeTiles.Count;
				nodeTiles.Add(t);
			}
			if (node.HubRefresh > 0.0)
			{
				if (!hubByTile.TryGetValue(t, out var hub))
					hubByTile[t] = hub = new Hub { Tile = t, Refresh = node.HubRefresh, Key = node.Key };
				else if (node.HubRefresh > hub.Refresh)
				{
					hub.Refresh = node.HubRefresh;
					hub.Key = node.Key;
				}
			}
		}
		var hubs = new List<Hub>(hubByTile.Values);

		// Origins: every source tile and every hub tile.
		var originIndex = new Dictionary<int, int>();
		var originTiles = new List<int>();
		foreach (var s in sources)
			AddOrigin(s.X + s.Y * w, originIndex, originTiles);
		foreach (var h in hubs)
			h.Origin = AddOrigin(h.Tile, originIndex, originTiles);

		// Guard zones (squad node + 8 neighbours) and node tile markers.
		Array.Clear(ws.Guard, 0, n);
		var squadByNode = new Dictionary<int, List<int>>();
		var squads = g.Squads ?? new List<Homm3FactoryLogisticsMap.SquadInfo>();
		var guardedTiles = 0;
		for (var i = 0; i < squads.Count; i++)
		{
			var sn = squads[i].Node;
			if (sn < 0 || sn >= n)
				continue;
			if (!squadByNode.TryGetValue(sn, out var list))
				squadByNode[sn] = list = new List<int>(1);
			list.Add(i);
			var sx = sn % w;
			var sy = sn / w;
			for (var dy = -1; dy <= 1; dy++)
			for (var dx = -1; dx <= 1; dx++)
			{
				var x = sx + dx;
				var y = sy + dy;
				if (x < 0 || y < 0 || x >= w || y >= g.H)
					continue;
				if (ws.Guard[x + y * w]++ == 0)
					guardedTiles++;
			}
		}
		foreach (var t in nodeTiles)
			ws.IsNode[t] = 1;

		try
		{
			BuildPass(g, ws, n);
			// Distance matrix origin x node tile, with guards.
			var nt = nodeTiles.Count;
			var dmat = new int[originTiles.Count * nt];
			var origins = originTiles.Count;
			var workers = Math.Max(1, Math.Min(Math.Min(Environment.ProcessorCount - 1, MaxFloodWorkers), origins));
			for (var o = 0; o < origins; o++)
				ws.Parent(o);
			for (var i = 0; i < workers; i++)
				ws.State(i);
			// Origins are independent: each worker owns one FloodState and writes disjoint parent arrays / dmat rows.
			var nextOrigin = -1;
			Exception floodError = null;
			void Worker(object stateIndex)
			{
				var st = ws.States[(int)stateIndex];
				try
				{
					int o;
					while ((o = System.Threading.Interlocked.Increment(ref nextOrigin)) < origins)
					{
						var stamp = Flood(g, ws, st, originTiles[o], ws.ParentPool[o], false, nt, Inf);
						for (var j = 0; j < nt; j++)
						{
							var t = nodeTiles[j];
							dmat[o * nt + j] = st.Stamp[t] == stamp ? st.Dist[t] : Inf;
						}
					}
				}
				catch (Exception ex)
				{
					floodError = ex;
				}
			}
			if (workers == 1)
				Worker(0);
			else
			{
				var threads = new System.Threading.Thread[workers - 1];
				for (var i = 0; i < threads.Length; i++)
				{
					threads[i] = new System.Threading.Thread(Worker) { IsBackground = true, Name = "FactoryLogisticsFlood" };
					threads[i].Start(i + 1);
				}
				Worker(0);
				foreach (var th in threads)
					th.Join();
			}
			if (floodError != null)
				throw new InvalidOperationException("flood worker failed: " + floodError.Message, floodError);

			var routes = new List<Route>();
			var blockers = new Dictionary<long, Blocker>();
			var label = new int[hubs.Count];
			var pred = new int[hubs.Count];
			var unreached = new List<Node>();
			var guardFreeParent = ws.Parent(originTiles.Count);
			foreach (var s in sources)
			{
				var sTile = s.X + s.Y * w;
				var so = originIndex[sTile];
				var budget = Math.Max(0, s.RangeLevels) * mpPerLevel;
				SolveHubLabels(hubs, dmat, nt, nodeTileIndex, so, sTile, budget, label, pred);
				unreached.Clear();
				foreach (var t in targets)
				{
					if (t.Key == s.Key && string.Equals(t.Kind, s.Kind, StringComparison.Ordinal))
						continue;
					var route = BuildRoute(g, ws, s, t, sTile, so, budget, hubs, label, pred, dmat, nt, nodeTileIndex, originTiles);
					routes.Add(route);
					if (!route.Reached)
						unreached.Add(t);
				}
				if (unreached.Count > 0 && squads.Count > 0)
					FindBlockers(g, ws, s, sTile, budget, unreached, squads, squadByNode, guardFreeParent, nodeTiles.Count, blockers);
			}
			result = new Result
			{
				Routes = routes,
				Blockers = new List<Blocker>(blockers.Values),
				GuardedTiles = guardedTiles,
				Squads = squads.Count,
				Anchored = anchored,
			};
			string Describe(string kind, long key)
			{
				foreach (var nd in allNodes)
				{
					if (nd.Key != key || nd.Kind != kind)
						continue;
					var t = nd.X + nd.Y * w;
					var open = 0;
					for (var dy = -1; dy <= 1; dy++)
					for (var dx = -1; dx <= 1; dx++)
					{
						var x = nd.X + dx;
						var y = nd.Y + dy;
						if ((dx != 0 || dy != 0) && (uint)x < (uint)w && (uint)y < (uint)g.H && (ws.Pass[x + y * w] & PassWalk) != 0)
							open++;
					}
					return kind + ":" + key + "(" + nd.X + "," + nd.Y + " blk=" + g.Block[t] + " seen=" + (g.Visible == null || g.Visible[t] ? 1 : 0)
						+ " guard=" + ws.Guard[t] + " openNb=" + open + ")";
				}
				return kind + ":" + key;
			}
			foreach (var r in routes)
			{
				if (r.NoPath && result.NoPathNotes.Count < 6)
					result.NoPathNotes.Add(Describe(r.FromKind, r.From) + "->" + Describe(r.ToKind, r.To));
			}
			return true;
		}
		finally
		{
			foreach (var t in nodeTiles)
				ws.IsNode[t] = 0;
		}
	}

	/// <summary>
	/// Routes start and end at an object's entrance, as a hero would walk there (2026-11-16 playtest: routes reached the
	/// Factory town from behind, through an open tile on the far side of its body). A node whose position tile is inside
	/// a blocked footprint moves to the nearest entrance tile (pathmap nodesGate) within 4 rings; ties go south (lower
	/// y: map y grows northward, entrances face the viewer), then to the smallest sideways offset. With no entrance in
	/// reach, an enclosed node (no open 8-neighbour) falls back to the nearest open tile with the same preference,
	/// explored first. Nodes on an open tile are left alone. True when moved.
	/// </summary>
	internal static bool AnchorNode(GridInput g, Node node)
	{
		var w = g.W;
		var h = g.H;
		bool Open(int x, int y) => (uint)x < (uint)w && (uint)y < (uint)h && g.Block[x + y * w] == 0;
		bool Gate(int x, int y) => Open(x, y) && g.Gate != null && g.Gate[x + y * w] != 0;
		if (Open(node.X, node.Y))
			return false;
		if (Nearest(Gate, false))
			return true;
		for (var dy = -1; dy <= 1; dy++)
		for (var dx = -1; dx <= 1; dx++)
			if ((dx != 0 || dy != 0) && Open(node.X + dx, node.Y + dy))
				return false;
		return Nearest(Open, true);

		bool Nearest(Func<int, int, bool> accept, bool preferExplored)
		{
			for (var r = 1; r <= 4; r++)
			{
				var found = false;
				var best = (x: 0, y: 0, unseen: 0, dy: 0, adx: 0);
				for (var dy = -r; dy <= r; dy++)
				for (var dx = -r; dx <= r; dx++)
				{
					if (Math.Max(Math.Abs(dx), Math.Abs(dy)) != r)
						continue;
					var x = node.X + dx;
					var y = node.Y + dy;
					if (!accept(x, y))
						continue;
					var unseen = !preferExplored || g.Visible == null || g.Visible[x + y * w] ? 0 : 1;
					var cand = (x, y, unseen, dy, adx: Math.Abs(dx));
					if (!found || cand.unseen < best.unseen || (cand.unseen == best.unseen && (cand.dy < best.dy || (cand.dy == best.dy && cand.adx < best.adx))))
					{
						best = cand;
						found = true;
					}
				}
				if (found)
				{
					node.X = best.x;
					node.Y = best.y;
					return true;
				}
			}
			return false;
		}
	}

	private static bool AddNode(Node node, string role, int w, int h, List<Node> into, out string fail)
	{
		fail = null;
		if (node == null)
		{
			fail = role + " node is null";
			return false;
		}
		if (node.X < 0 || node.Y < 0 || node.X >= w || node.Y >= h)
		{
			fail = role + " node " + node.Kind + ":" + node.Key + " tile (" + node.X + "," + node.Y + ") outside map " + w + "x" + h;
			return false;
		}
		if (double.IsNaN(node.HubRefresh) || node.HubRefresh < 0.0)
		{
			fail = role + " node " + node.Kind + ":" + node.Key + " has invalid HubRefresh " + node.HubRefresh;
			return false;
		}
		into.Add(node);
		return true;
	}

	private static int AddOrigin(int tile, Dictionary<int, int> index, List<int> tiles)
	{
		if (index.TryGetValue(tile, out var o))
			return o;
		o = tiles.Count;
		index[tile] = o;
		tiles.Add(tile);
		return o;
	}

	private const byte PassWalk = 1;       // enterable when guard zones are ignored
	private const byte PassGuardFree = 2;  // outside every guard zone
	private const byte PassExpand = 4;     // may be left again (not an object body that is only a node tile)

	private static void BuildPass(GridInput g, Workspace ws, int n)
	{
		var pass = ws.Pass;
		var block = g.Block;
		var vis = g.Visible;
		var guard = ws.Guard;
		var isNode = ws.IsNode;
		for (var m = 0; m < n; m++)
		{
			byte f = 0;
			if (vis == null || vis[m])
			{
				if (block[m] == 0)
					f = PassWalk | PassExpand;
				else if (isNode[m] != 0)
					f = PassWalk;
				if (guard[m] == 0)
					f |= PassGuardFree;
			}
			pass[m] = f;
		}
	}

	/// <summary>
	/// Dial's algorithm (bucket queue; step costs 3..14). Stops when every node tile is settled or the distance
	/// passes <paramref name="capMp"/>. Returns the stamp marking reached tiles (only settled distances are exact).
	/// </summary>
	private static int Flood(GridInput g, Workspace ws, FloodState st, int origin, byte[] parent, bool ignoreGuards, int nodeTileCount, int capMp)
	{
		var w = g.W;
		var h = g.H;
		var dist = st.Dist;
		var stampArr = st.Stamp;
		var pass = ws.Pass;
		var isNode = ws.IsNode;
		var orth = g.CostOrth;
		var diag = g.CostDiag;
		var need = ignoreGuards ? PassWalk : (byte)(PassWalk | PassGuardFree);
		var stamp = st.NextStamp();
		Array.Clear(st.BucketCount, 0, st.BucketCount.Length);
		dist[origin] = 0;
		stampArr[origin] = stamp;
		st.Push(0, origin);
		var pending = 1;
		var cur = 0;
		var nodesLeft = nodeTileCount;
		while (pending > 0 && cur <= capMp)
		{
			var b = cur & 15;
			while (st.BucketCount[b] > 0)
			{
				var node = st.Buckets[b][--st.BucketCount[b]];
				pending--;
				if (dist[node] != cur || stampArr[node] != stamp)
					continue;
				if (isNode[node] != 0 && --nodesLeft <= 0)
					return stamp;
				// Node tiles inside object bodies are destinations, not passages through the object.
				if (node != origin && (pass[node] & PassExpand) == 0)
					continue;
				var x = node % w;
				var y = node / w;
				for (var k = 0; k < 8; k++)
				{
					var nx = x + Dx[k];
					var ny = y + Dy[k];
					if ((uint)nx >= (uint)w || (uint)ny >= (uint)h)
						continue;
					var m = nx + ny * w;
					if ((pass[m] & need) != need)
						continue;
					var nd = cur + (k < 4 ? orth[m] : diag[m]);
					if (stampArr[m] == stamp && nd >= dist[m])
						continue;
					stampArr[m] = stamp;
					dist[m] = nd;
					parent[m] = (byte)k;
					st.Push(nd & 15, m);
					pending++;
				}
			}
			cur++;
		}
		return stamp;
	}

	private static List<int> Reconstruct(int origin, int dest, byte[] parent, int w, int n)
	{
		var path = new List<int>();
		var cur = dest;
		var guard = 0;
		while (cur != origin)
		{
			path.Add(cur);
			var k = parent[cur];
			cur -= Dx[k] + Dy[k] * w;
			if (++guard > n || cur < 0 || cur >= n)
				throw new InvalidOperationException("path reconstruction broke (parent chain)");
		}
		path.Add(origin);
		path.Reverse();
		return path;
	}

	private static void SolveHubLabels(List<Hub> hubs, int[] dmat, int nt, Dictionary<int, int> nodeTileIndex,
		int so, int sTile, int budget, int[] label, int[] pred)
	{
		for (var i = 0; i < hubs.Count; i++)
		{
			label[i] = NoLabel;
			pred[i] = -2;
			if (hubs[i].Tile == sTile)
				continue;
			var d = dmat[so * nt + nodeTileIndex[hubs[i].Tile]];
			if (d == Inf)
				continue;
			var r = budget - d;
			if (r < 0)
				continue;
			label[i] = ApplyHubRefresh(r, budget, hubs[i].Refresh);
			pred[i] = -1;
		}
		// Label-correcting over the hub graph; a hub never repeats on its own chain (acyclic preds).
		for (var round = 0; round <= hubs.Count; round++)
		{
			var changed = false;
			for (var a = 0; a < hubs.Count; a++)
			{
				if (label[a] == NoLabel)
					continue;
				for (var b = 0; b < hubs.Count; b++)
				{
					if (b == a || hubs[b].Tile == sTile)
						continue;
					var d = dmat[hubs[a].Origin * nt + nodeTileIndex[hubs[b].Tile]];
					if (d == Inf)
						continue;
					var r = label[a] - d;
					if (r < 0)
						continue;
					var r2 = ApplyHubRefresh(r, budget, hubs[b].Refresh);
					if (r2 <= label[b] || InChain(pred, a, b))
						continue;
					label[b] = r2;
					pred[b] = a;
					changed = true;
				}
			}
			if (!changed)
				break;
		}
	}

	private static bool InChain(int[] pred, int start, int needle)
	{
		var guard = 0;
		for (var c = start; c >= 0; c = pred[c])
		{
			if (c == needle || ++guard > pred.Length)
				return true;
		}
		return false;
	}

	private static Route BuildRoute(GridInput g, Workspace ws, Node s, Node t, int sTile, int so, int budget,
		List<Hub> hubs, int[] label, int[] pred, int[] dmat, int nt, Dictionary<int, int> nodeTileIndex,
		List<int> originTiles)
	{
		var w = g.W;
		var n = w * g.H;
		var tTile = t.X + t.Y * w;
		var jt = nodeTileIndex[tTile];
		var route = new Route
		{
			From = s.Key, To = t.Key, FromKind = s.Kind, ToKind = t.Kind, ViaHubs = new List<long>(),
		};
		var bestR = NoLabel;
		var bestVia = -2;
		var dDirect = dmat[so * nt + jt];
		if (dDirect != Inf)
		{
			bestR = budget - dDirect;
			bestVia = -1;
		}
		var targetHub = -1;
		for (var i = 0; i < hubs.Count; i++)
			if (hubs[i].Tile == tTile)
				targetHub = i;
		for (var i = 0; i < hubs.Count; i++)
		{
			if (label[i] == NoLabel || hubs[i].Tile == tTile)
				continue;
			if (targetHub >= 0 && InChain(pred, i, targetHub))
				continue;
			var d = dmat[hubs[i].Origin * nt + jt];
			if (d == Inf)
				continue;
			var r = label[i] - d;
			if (r > bestR)
			{
				bestR = r;
				bestVia = i;
			}
		}
		if (bestVia == -2)
		{
			route.NoPath = true;
			route.Reached = false;
			route.MissingMp = 0;
			route.Tiles = new List<(int x, int y)> { (s.X, s.Y) };
			return route;
		}

		// Chain: source -> hubs... -> target.
		var chain = new List<int>();
		for (var c = bestVia; c >= 0; c = pred[c])
			chain.Add(c);
		chain.Reverse();
		var path = new List<int> { sTile };
		var hubAt = new Dictionary<int, double>();   // path index -> refresh, for chain hubs
		var fromOrigin = so;
		var fromTile = sTile;
		foreach (var hi in chain)
		{
			var seg = Reconstruct(fromTile, hubs[hi].Tile, ws.Parent(fromOrigin), w, n);
			for (var i = 1; i < seg.Count; i++)
				path.Add(seg[i]);
			hubAt[path.Count - 1] = hubs[hi].Refresh;
			route.ViaHubs.Add(hubs[hi].Key);
			fromOrigin = hubs[hi].Origin;
			fromTile = hubs[hi].Tile;
		}
		var last = Reconstruct(fromTile, tTile, ws.Parent(fromOrigin), w, n);
		for (var i = 1; i < last.Count; i++)
			path.Add(last[i]);

		// Walk the path with the budget; truncate where it runs out.
		var remaining = budget;
		var spent = 0;
		var keep = path.Count;
		for (var i = 1; i < path.Count; i++)
		{
			var a = path[i - 1];
			var b = path[i];
			var diagonal = (a % w) != (b % w) && (a / w) != (b / w);
			var step = diagonal ? g.CostDiag[b] : g.CostOrth[b];
			if (remaining - step < 0)
			{
				keep = i;
				break;
			}
			remaining -= step;
			spent += step;
			if (hubAt.TryGetValue(i, out var refresh))
				remaining = ApplyHubRefresh(remaining, budget, refresh);
		}
		route.Reached = bestR >= 0;
		route.MissingMp = bestR >= 0 ? 0 : -bestR;
		route.SpentMp = spent;
		route.Tiles = new List<(int x, int y)>(keep);
		for (var i = 0; i < keep; i++)
			route.Tiles.Add((path[i] % w, path[i] / w));
		return route;
	}

	private static void FindBlockers(GridInput g, Workspace ws, Node s, int sTile, int budget, List<Node> unreached,
		List<Homm3FactoryLogisticsMap.SquadInfo> squads, Dictionary<int, List<int>> squadByNode, byte[] parent,
		int nodeTileCount, Dictionary<long, Blocker> blockers)
	{
		var w = g.W;
		var n = w * g.H;
		// Only paths within the budget can be linked by one fight, so the guard-free flood stops at the budget.
		var st = ws.State(0);
		var stamp = Flood(g, ws, st, sTile, parent, true, nodeTileCount, budget);
		var cover = new List<int>(4);
		foreach (var t in unreached)
		{
			var tTile = t.X + t.Y * w;
			if (st.Stamp[tTile] != stamp || st.Dist[tTile] > budget)
				continue;
			var path = Reconstruct(sTile, tTile, parent, w, n);
			var single = -1;
			var ok = true;
			for (var i = 1; i < path.Count && ok; i++)
			{
				var p = path[i];
				if (ws.Guard[p] == 0)
					continue;
				cover.Clear();
				var px = p % w;
				var py = p / w;
				for (var dy = -1; dy <= 1; dy++)
				for (var dx = -1; dx <= 1; dx++)
				{
					var x = px + dx;
					var y = py + dy;
					if (x < 0 || y < 0 || x >= w || y >= g.H)
						continue;
					if (squadByNode.TryGetValue(x + y * w, out var list))
						cover.AddRange(list);
				}
				if (cover.Count != 1 || (single >= 0 && cover[0] != single))
					ok = false;
				else
					single = cover[0];
			}
			if (!ok || single < 0)
				continue;
			var sq = squads[single];
			if (!blockers.TryGetValue(sq.Key, out var blocker))
			{
				blockers[sq.Key] = blocker = new Blocker
				{
					X = sq.Node % w, Y = sq.Node / w, GuardKey = sq.Key, WouldLink = new List<(long from, long to)>(),
				};
			}
			blocker.WouldLink.Add((s.Key, t.Key));
		}
	}

	// ------------------------------------------------------------------------------------------------
	// Pure helpers for the viewer (mirrored by tools/factory_logistics/range_harness)
	// ------------------------------------------------------------------------------------------------

	/// <summary>Guard-zone counts per tile (squad node + 8 neighbours).</summary>
	private static int[] GuardMap(GridInput g)
	{
		var w = g.W;
		var guard = new int[w * g.H];
		foreach (var sq in g.Squads ?? new List<Homm3FactoryLogisticsMap.SquadInfo>())
		{
			if (sq.Node < 0 || sq.Node >= guard.Length)
				continue;
			int sx = sq.Node % w, sy = sq.Node / w;
			for (var dy = -1; dy <= 1; dy++)
			for (var dx = -1; dx <= 1; dx++)
			{
				int x = sx + dx, y = sy + dy;
				if ((uint)x < (uint)w && (uint)y < (uint)g.H)
					guard[x + y * w]++;
			}
		}
		return guard;
	}

	private static Node CopyAnchored(GridInput g, Node node)
	{
		var copy = new Node { Key = node.Key, Kind = node.Kind, X = node.X, Y = node.Y, Level = node.Level, RangeLevels = node.RangeLevels, HubRefresh = node.HubRefresh };
		if (copy.X >= 0 && copy.Y >= 0 && copy.X < g.W && copy.Y < g.H)
			AnchorNode(g, copy);
		return copy;
	}

	/// <summary>
	/// Range overlay: best remaining MP on every tile a route from <paramref name="source"/> with <paramref name="budget"/>
	/// can step onto, under the solver's rules (explored, unblocked, outside guard zones; 10/14 MP steps with road bonus;
	/// entering a hub tile refreshes spent range with <see cref="ApplyHubRefresh"/>). -1 = unreachable. viaHub marks tiles
	/// whose best value came through a hub refresh. Hub tiles are enterable even inside an object body (they are nodes).
	/// </summary>
	internal static bool ReachCore(GridInput g, Node source, int budget, IReadOnlyList<Node> hubs, out int[] remaining, out bool[] viaHub, out string fail)
	{
		remaining = null;
		viaHub = null;
		fail = null;
		if (g == null || g.W <= 0 || g.H <= 0 || g.Block == null || g.CostOrth == null || g.CostDiag == null || source == null)
		{
			fail = "grid input incomplete";
			return false;
		}
		var w = g.W;
		var n = w * g.H;
		if (source.X < 0 || source.Y < 0 || source.X >= w || source.Y >= g.H)
		{
			fail = "source outside the map";
			return false;
		}
		var guard = GuardMap(g);
		var hubAt = new Dictionary<int, double>();
		foreach (var h in hubs ?? Array.Empty<Node>())
		{
			if (h == null || h.HubRefresh <= 0.0)
				continue;
			var a = CopyAnchored(g, h);
			if (a.X < 0 || a.Y < 0 || a.X >= w || a.Y >= g.H)
				continue;
			var t = a.X + a.Y * w;
			hubAt[t] = Math.Max(hubAt.TryGetValue(t, out var have) ? have : 0.0, Math.Min(1.0, h.HubRefresh));
		}
		var src = CopyAnchored(g, source);
		var start = src.X + src.Y * w;
		var rem = new int[n];
		var via = new bool[n];
		for (var i = 0; i < n; i++)
			rem[i] = -1;
		rem[start] = Math.Max(0, budget);
		if (budget <= 0)
		{
			remaining = rem;
			viaHub = via;
			return true;
		}
		bool Walk(int m) => (g.Visible == null || g.Visible[m]) && guard[m] == 0 && (g.Block[m] == 0 || hubAt.ContainsKey(m));
		bool Expand(int m) => m == start || g.Block[m] == 0;
		var buckets = new List<int>[budget + 1];
		(buckets[budget] = new List<int>()).Add(start);
		var cur = budget;
		var steps = 0;
		while (cur >= 0)
		{
			var list = buckets[cur];
			if (list == null || list.Count == 0)
			{
				cur--;
				continue;
			}
			var node = list[list.Count - 1];
			list.RemoveAt(list.Count - 1);
			if (rem[node] != cur || !Expand(node))
				continue;
			if (++steps > n * 16)
			{
				fail = "reach did not settle";
				return false;
			}
			int x = node % w, y = node / w;
			for (var k = 0; k < 8; k++)
			{
				int nx = x + Dx[k], ny = y + Dy[k];
				if ((uint)nx >= (uint)w || (uint)ny >= (uint)g.H)
					continue;
				var m = nx + ny * w;
				if (!Walk(m))
					continue;
				var r = cur - (k < 4 ? g.CostOrth[m] : g.CostDiag[m]);
				if (r < 0)
					continue;
				var refreshed = false;
				if (hubAt.TryGetValue(m, out var refresh))
				{
					var r2 = ApplyHubRefresh(r, budget, refresh);
					refreshed = r2 > r;
					r = r2;
				}
				if (r <= rem[m])
					continue;
				rem[m] = r;
				via[m] = via[node] || refreshed;
				(buckets[r] ??= new List<int>()).Add(m);
				if (r > cur)
					cur = r;
			}
		}
		remaining = rem;
		viaHub = via;
		return true;
	}

	/// <summary>
	/// Plain-English reason two nodes have no path at all, found by relaxing one rule at a time (guards, fog, water) on an
	/// 8-neighbour connectivity check; null when they are connected under the normal rules.
	/// </summary>
	internal static string ExplainNoPathCore(GridInput g, Node from, Node to)
	{
		if (g == null || from == null || to == null || g.Block == null)
			return "map unreadable";
		var a = CopyAnchored(g, from);
		var b = CopyAnchored(g, to);
		var w = g.W;
		if (a.X < 0 || a.Y < 0 || a.X >= w || a.Y >= g.H || b.X < 0 || b.Y < 0 || b.X >= w || b.Y >= g.H)
			return "outside the map";
		var guard = GuardMap(g);
		int s = a.X + a.Y * w, t = b.X + b.Y * w;
		bool Connected(bool ignoreGuards, bool ignoreFog, bool ignoreWater)
		{
			var n = w * g.H;
			var seen = new bool[n];
			var queue = new Queue<int>();
			seen[s] = true;
			queue.Enqueue(s);
			while (queue.Count > 0)
			{
				var c = queue.Dequeue();
				if (c == t)
					return true;
				if (c != s && g.Block[c] != 0 && !(ignoreWater && g.Block[c] == Homm3FactoryLogisticsMap.BlockWater))
					continue;
				int x = c % w, y = c / w;
				for (var k = 0; k < 8; k++)
				{
					int nx = x + Dx[k], ny = y + Dy[k];
					if ((uint)nx >= (uint)w || (uint)ny >= (uint)g.H)
						continue;
					var m = nx + ny * w;
					if (seen[m])
						continue;
					var fogOk = ignoreFog || g.Visible == null || g.Visible[m] || m == t;
					var guardOk = ignoreGuards || guard[m] == 0 || m == t;
					var blockOk = m == t || g.Block[m] == 0 || (ignoreWater && g.Block[m] == Homm3FactoryLogisticsMap.BlockWater);
					if (!fogOk || !guardOk || !blockOk)
						continue;
					seen[m] = true;
					queue.Enqueue(m);
				}
			}
			return false;
		}
		if (Connected(false, false, false))
			return null;
		if (g.Visible != null && !g.Visible[t])
			return "the target is in unexplored fog";
		if (Connected(true, false, false))
			return "neutral stacks guard every way through";
		if (Connected(false, true, false))
			return "unexplored fog blocks the way";
		if (Connected(true, true, false))
			return "fog and neutral stacks block the way";
		if (Connected(true, true, true))
			return "only reachable across water";
		return "enclosed: no open ground connects them";
	}
}
