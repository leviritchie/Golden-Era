using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using OfflineUnlockMod;
using R = OfflineUnlockMod.Homm3FactoryLogisticsRange;
using M = OfflineUnlockMod.Homm3FactoryLogisticsMap;

// Offline checks for the Factory Logistics range solver. Exit code 0 = all pass.
internal static class Program
{
	private static int _fails;

	private static void Check(string name, bool ok, string detail = "")
	{
		Console.WriteLine((ok ? "PASS " : "FAIL ") + name + (detail.Length > 0 ? "  [" + detail + "]" : ""));
		if (!ok) _fails++;
	}

	private static R.Node N(long key, int x, int y, int levels = 1, double hub = 0, string kind = "building") =>
		new() { Key = key, Kind = kind, X = x, Y = y, RangeLevels = levels, HubRefresh = hub };

	private static R.Result Solve(IReadOnlyList<R.Node> src, IReadOnlyList<R.Node> dst, int mp = 100)
	{
		if (!R.TrySolve(1, src, dst, mp, out var res, out var fail))
			throw new Exception("solve failed: " + fail);
		return res;
	}

	private static R.Route Route(R.Result r, long from, long to) => r.Routes.Single(x => x.From == from && x.To == to);

	private static void Reset(int w, int h)
	{
		M.Grid = M.NewGrid(w, h);
		M.Visible = null;
		M.Squads = new List<M.SquadInfo>();
	}

	private static int Main()
	{
		// 1. Straight line, budget exactly met / missed by one step.
		Reset(30, 5);
		var s = N(1, 0, 2);
		var r = Solve(new[] { s }, new[] { N(2, 10, 2), N(3, 11, 2) });
		var a = Route(r, 1, 2);
		var b = Route(r, 1, 3);
		Check("orth 10 tiles = 100 MP reaches", a.Reached && a.MissingMp == 0 && a.Tiles.Count == 11 && a.SpentMp == 100, $"{a.Reached} {a.MissingMp} {a.Tiles.Count} {a.SpentMp}");
		Check("orth 11 tiles cut, missing 10", !b.Reached && !b.NoPath && b.MissingMp == 10 && b.Tiles.Count == 11 && b.Tiles[^1] == (10, 2), $"{b.Reached} {b.MissingMp} {b.Tiles.Count} last={b.Tiles[^1]}");

		// 2. Diagonal cost 14.
		Reset(30, 30);
		r = Solve(new[] { N(1, 0, 0) }, new[] { N(2, 5, 5), N(3, 8, 8) });
		Check("diag 5 = 70 MP", Route(r, 1, 2).Reached && Route(r, 1, 2).SpentMp == 70);
		Check("diag 8 = 112 MP cut missing 12", Route(r, 1, 3).MissingMp == 12, Route(r, 1, 3).MissingMp.ToString());

		// 3. Hub refresh, spec example: B=100, hub after 50 MP with 0.33 -> 66 remaining.
		Reset(40, 5);
		Check("ApplyHubRefresh(50,100,0.33)=66", R.ApplyHubRefresh(50, 100, 0.33) == 66);
		r = Solve(new[] { N(1, 0, 2) }, new[] { N(5, 5, 2, hub: 0.33), N(2, 11, 2), N(3, 12, 2), N(4, 15, 2) });
		Check("via hub: 60 MP after hub fits 66", Route(r, 1, 2).Reached && Route(r, 1, 2).ViaHubs.SequenceEqual(new long[] { 5 }));
		Check("via hub: 70 MP after hub misses 4", !Route(r, 1, 3).Reached && Route(r, 1, 3).MissingMp == 4, Route(r, 1, 3).MissingMp.ToString());
		var cut = Route(r, 1, 4);
		Check("via hub cut stops at 66 MP past hub (x=11)", !cut.Reached && cut.MissingMp == 34 && cut.Tiles[^1] == (11, 2), $"{cut.MissingMp} last={cut.Tiles[^1]}");
		var noHub = Solve(new[] { N(1, 0, 2) }, new[] { N(2, 11, 2) });
		Check("without hub 110 MP misses 10", Route(noHub, 1, 2).MissingMp == 10);
		// Supply Caravan: a hub-only hero node (extraHubs) refreshes routes but gets no route of its own.
		Check("caravan hero hub at x=5 (100%) lets 110 MP reach",
			R.TrySolve(1, new[] { N(1, 0, 2) }, new[] { N(2, 11, 2) }, 100, out var caravan, out _, new[] { N(1L << 40 | 7, 5, 2, hub: 1.0, kind: "hero") })
			&& Route(caravan, 1, 2).Reached && caravan.Routes.Count == 1);

		// 4. Road discount (0.3 -> 7 MP orth).
		Reset(30, 5);
		for (var x = 0; x < 30; x++) M.Grid.RoadBonus[x + 2 * 30] = 0.3f;
		M.Grid.CostOrth = M.Grid.CostDiag = null;
		r = Solve(new[] { N(1, 0, 2) }, new[] { N(2, 14, 2) });
		Check("road 14 tiles x7 = 98 reaches", Route(r, 1, 2).Reached && Route(r, 1, 2).SpentMp == 98, Route(r, 1, 2).SpentMp.ToString());
		Check("StepCost road 0.2 = 8/11", R.StepCost(0.2f, false) == 8 && R.StepCost(0.2f, true) == 11);

		// 5. Guard zone blocks a 3-high corridor; blocker reported.
		Reset(20, 3);
		M.Squads.Add(new M.SquadInfo { Key = 777, Node = 5 + 1 * 20 });
		r = Solve(new[] { N(1, 0, 1, levels: 2) }, new[] { N(2, 10, 1), N(3, 19, 1) });
		Check("guard zone blocks corridor", Route(r, 1, 2).NoPath && !Route(r, 1, 2).Reached);
		var bl = r.Blockers.SingleOrDefault(x => x.GuardKey == 777);
		Check("blocker 777 links 1->2 (within budget) not 1->3 (190 > 200? fits)", bl != null && bl.X == 5 && bl.Y == 1 && bl.WouldLink.Contains((1L, 2L)),
			bl == null ? "none" : string.Join(",", bl.WouldLink));
		// Two overlapping guards: neither alone links.
		M.Squads.Add(new M.SquadInfo { Key = 778, Node = 6 + 1 * 20 });
		r = Solve(new[] { N(1, 0, 1, levels: 2) }, new[] { N(2, 10, 1) });
		Check("two guards on path -> no single blocker", r.Blockers.Count == 0, r.Blockers.Count.ToString());

		// 6. Fog column blocks.
		Reset(20, 3);
		M.Visible = Enumerable.Repeat(true, 60).ToArray();
		for (var y = 0; y < 3; y++) M.Visible[5 + y * 20] = false;
		r = Solve(new[] { N(1, 0, 1) }, new[] { N(2, 8, 1) });
		Check("fog column blocks", Route(r, 1, 2).NoPath);

		// 7. Object wall; node tile inside the wall is reachable but not a passage.
		Reset(20, 3);
		for (var y = 0; y < 3; y++) M.Grid.Block[5 + y * 20] = M.BlockObject;
		r = Solve(new[] { N(1, 0, 1, levels: 2) }, new[] { N(2, 5, 1), N(3, 8, 1) });
		Check("node tile in object body reachable", Route(r, 1, 2).Reached);
		Check("object wall not crossed through node tile", Route(r, 1, 3).NoPath);

		// 8. Source == target is skipped; hub chain of two hubs.
		Reset(60, 3);
		r = Solve(new[] { N(1, 0, 1) }, new[] { N(1, 0, 1), N(5, 8, 1, hub: 0.5), N(6, 16, 1, hub: 0.5), N(2, 24, 1) });
		Check("self pair skipped", r.Routes.All(x => !(x.From == 1 && x.To == 1)));
		var chain = Route(r, 1, 2);
		// 80 spent -> 20+40=60; +80 -> -20 ... hub2 not reachable directly from hub1 (60-80<0); so target cut.
		Check("hub chain cut", !chain.Reached, $"missing={chain.MissingMp} via={string.Join(",", chain.ViaHubs)}");

		// 9. Fail-closed inputs.
		Reset(10, 10);
		Check("out-of-map node fails closed", !R.TrySolve(1, new[] { N(1, 0, 0) }, new[] { N(2, 10, 0) }, 100, out _, out var f1) && f1.Contains("outside"));
		Check("mpPerLevel 0 fails closed", !R.TrySolve(1, new[] { N(1, 0, 0) }, new[] { N(2, 1, 0) }, 0, out _, out _));

		// 10. Perf: 256x256, 15% objects, 5% water patches, 25 squads, 30 nodes (10 hubs, 20 sources).
		var rng = new Random(1234);
		Reset(256, 256);
		for (var i = 0; i < 256 * 256; i++)
		{
			var roll = rng.NextDouble();
			if (roll < 0.15) M.Grid.Block[i] = M.BlockObject;
			else if (roll < 0.20) M.Grid.Block[i] = M.BlockWater;
			else if (roll < 0.26) M.Grid.RoadBonus[i] = 0.25f;
		}
		var vis = new bool[256 * 256];
		for (var i = 0; i < vis.Length; i++) vis[i] = rng.NextDouble() < 0.9;
		M.Visible = vis;
		for (var i = 0; i < 25; i++) M.Squads.Add(new M.SquadInfo { Key = 1000 + i, Node = rng.Next(256 * 256) });
		var nodes = new List<R.Node>();
		for (var i = 0; i < 30; i++)
			nodes.Add(N(i + 1, rng.Next(256), rng.Next(256), levels: 1 + rng.Next(5), hub: i < 10 ? 0.33 : 0));
		var srcs = nodes.Skip(5).Take(20).ToList();
		Solve(srcs, nodes); // warm (JIT + cost arrays)
		var sw = Stopwatch.StartNew();
		const int reps = 5;
		R.Result last = null;
		for (var i = 0; i < reps; i++) last = Solve(srcs, nodes);
		sw.Stop();
		var ms = sw.Elapsed.TotalMilliseconds / reps;
		Check("perf 256x256 / 30 nodes / 20 sources < 100 ms", ms < 100, $"{ms:0.0} ms avg, routes={last.Routes.Count} reached={last.Routes.Count(x => x.Reached)} blockers={last.Blockers.Count}");

		// 9. Reach overlay (viewer): straight line, budget 100 = 10 orthogonal tiles; a hub extends it.
		Reset(40, 3);
		R.GridInput G() { R.EnsureCosts(M.Grid); return new R.GridInput { W = M.Grid.W, H = M.Grid.H, Block = M.Grid.Block, CostOrth = M.Grid.CostOrth, CostDiag = M.Grid.CostDiag, Visible = M.Visible, Squads = M.Squads, Gate = M.Grid.Gate }; }
		var ok9 = R.ReachCore(G(), N(1, 0, 1, levels: 1), 100, null, out var rem, out var via, out var f9);
		Check("reach: tile 10 reached with 0 left, tile 11 not", ok9 && rem[10 + 40] == 0 && rem[11 + 40] == -1 && !via[10 + 40], f9 ?? $"{rem[10 + 40]} {rem[11 + 40]}");
		R.ReachCore(G(), N(1, 0, 1, levels: 1), 100, new[] { N(9, 5, 1, hub: 1.0) }, out rem, out via, out _);
		Check("reach: full hub at 5 refreshes to 100, reach 15 via hub", rem[5 + 40] == 100 && rem[15 + 40] == 0 && via[15 + 40] && rem[16 + 40] == -1, $"{rem[5 + 40]} {rem[15 + 40]} {rem[16 + 40]}");
		M.Squads.Add(new M.SquadInfo { Key = 1, Node = 4 + 1 * 40 });
		R.ReachCore(G(), N(1, 0, 1, levels: 1), 100, null, out rem, out _, out _);
		Check("reach: guard zone stops it", rem[2 + 40] >= 0 && rem[3 + 40] == -1 && rem[6 + 40] == -1, $"{rem[2 + 40]} {rem[3 + 40]}");

		// 10. No-path explanations.
		Check("explain: guards", R.ExplainNoPathCore(G(), N(1, 0, 1), N(2, 10, 1)) == "neutral stacks guard every way through");
		Reset(20, 3);
		for (var y = 0; y < 3; y++) M.Grid.Block[8 + y * 20] = M.BlockWater;
		Check("explain: water", R.ExplainNoPathCore(G(), N(1, 0, 1), N(2, 12, 1)) == "only reachable across water");
		Reset(20, 3);
		M.Visible = Enumerable.Repeat(true, 60).ToArray();
		for (var y = 0; y < 3; y++) M.Visible[8 + y * 20] = false;
		Check("explain: fog", R.ExplainNoPathCore(G(), N(1, 0, 1), N(2, 12, 1)) == "unexplored fog blocks the way");
		Reset(20, 3);
		Check("explain: connected = null", R.ExplainNoPathCore(G(), N(1, 0, 1), N(2, 12, 1)) == null);

		Console.WriteLine("log tail: " + (M.Log.Count > 0 ? M.Log[^1] : "-"));
		Console.WriteLine(_fails == 0 ? "ALL PASS" : _fails + " FAIL");
		return _fails == 0 ? 0 : 1;
	}
}
