using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using P = OfflineUnlockMod.Homm3CoveTreasurePlan;

// Offline checks for the Cove treasure plan generator. Exit code 0 = all pass.
// Args: optional JSON files from ../export_map_regions.py (real maps).
internal static class Program
{
	private static int _fails;

	private static void Check(string name, bool ok, string detail = "")
	{
		Console.WriteLine((ok ? "PASS " : "FAIL ") + name + (detail.Length > 0 ? "  [" + detail + "]" : ""));
		if (!ok) _fails++;
	}

	private static P.Catalog StubCatalog() => new()
	{
		Artifacts = new[]
		{
			new P.ArtifactEntry { Sid = "c1", Value = 2500 }, new P.ArtifactEntry { Sid = "c2", Value = 3000 },
			new P.ArtifactEntry { Sid = "r1", Value = 6000 }, new P.ArtifactEntry { Sid = "e1", Value = 12000 },
			new P.ArtifactEntry { Sid = "l1", Value = 24000 },
		},
		Units = new[]
		{
			new P.UnitEntry { Sid = "h3_skeleton", SquadValue = 60, Tier = 1 },
			new P.UnitEntry { Sid = "h3_golem", SquadValue = 250, Tier = 3 },
			new P.UnitEntry { Sid = "h3_black_knight", SquadValue = 1400, Tier = 6 },
		},
	};

	private static P.RegionInput Rect(int id, int width, int w, int h, int holderEvery, long richness = P.AnchorRichness)
	{
		var nodes = new List<int>();
		for (var z = 0; z < h; z++)
			for (var x = 0; x < w; x++)
				nodes.Add(x + z * width);
		var holders = new List<P.Holder>();
		var dig = new List<int>();
		for (var i = 0; i < nodes.Count; i++)
		{
			if (holderEvery > 0 && i % holderEvery == 0)
				holders.Add(new P.Holder { Node = nodes[i], Key = nodes[i], Kind = P.HolderObject });
			else
				dig.Add(nodes[i]);
		}
		return new P.RegionInput { RegionId = id, Width = width, TileCount = nodes.Count, HolderCandidates = holders, DigCandidates = dig, Richness = richness };
	}

	private static int MinPairDistance(P.RegionPlan plan, int width)
	{
		var points = plan.Pieces.Select(p => p.Node).Concat(plan.FalseNodes).Append(plan.TrueNode).Where(n => n >= 0).ToList();
		var min = int.MaxValue;
		for (var i = 0; i < points.Count; i++)
			for (var j = i + 1; j < points.Count; j++)
				min = Math.Min(min, P.Distance(points[i], points[j], width));
		return min;
	}

	private static string Describe(P.Contents c) =>
		$"gold={c.Gold} res=[{string.Join(",", c.Resources.Select(r => r.Amount + " " + r.Name))}] art={c.ArtifactSid ?? "-"}({c.ArtifactValue}) unit={c.UnitSid ?? "-"}x{c.UnitCount} total={c.Total()}";

	private static int Main(string[] args)
	{
		const double k = P.AnchorK;
		var catalog = StubCatalog();

		// 1. Anchor and clamps.
		Check("anchor region -> 24000", P.ValueFor(P.AnchorRichness, k) == 24000, P.ValueFor(P.AnchorRichness, k).ToString());
		Check("floor 12000", P.ValueFor(1000, k) == 12000);
		Check("ceiling 88000", P.ValueFor(8000000, k) == 88000);

		// 2. Roomy region: full plan, spacing holds at the start value.
		var roomy = Rect(1, 200, 40, 30, 7);
		var plan = P.Build(12345, roomy, catalog, k);
		Check("roomy: 5 pieces, 1 true, 3 false", plan.Pieces.Length == 5 && plan.TrueNode >= 0 && plan.FalseNodes.Length == 3);
		Check("roomy: spacing not relaxed", plan.FinalSpacing == plan.StartSpacing && MinPairDistance(plan, 200) >= plan.StartSpacing, $"start={plan.StartSpacing} final={plan.FinalSpacing} min={MinPairDistance(plan, 200)}");
		Check("roomy: pieces are real holders", plan.Pieces.All(p => p.Kind == P.HolderObject));

		// Guard quota (user rule 2026-11-17): at least 2 guarded and 1 unguarded piece when the region has both kinds.
		var quotaOk = true;
		var quotaNote = "";
		for (ulong seed = 1; seed <= 200 && quotaOk; seed++)
		{
			var mixed = Rect(3, 64, 40, 40, 7);
			mixed.HolderCandidates = mixed.HolderCandidates.Select((h, i) => new P.Holder { Node = h.Node, Key = h.Key, Kind = h.Kind, Guarded = i % 4 == 0 }).ToList();
			var q = P.Build(seed, mixed, catalog, k);
			var g = q.Pieces.Count(x => x.Guarded);
			quotaOk = q.Pieces.Length == 5 && g >= P.MinGuardedPieces && 5 - g >= P.MinUnguardedPieces && q.Pieces.Select(x => x.Node).Distinct().Count() == 5;
			quotaNote = "seed=" + seed + " guarded=" + g;
		}
		Check("guard quota: >=2 guarded, >=1 unguarded over 200 seeds", quotaOk, quotaNote);
		var allGuarded = Rect(4, 64, 40, 40, 7);
		allGuarded.HolderCandidates = allGuarded.HolderCandidates.Select(h => new P.Holder { Node = h.Node, Key = h.Key, Kind = h.Kind, Guarded = true }).ToList();
		Check("guard quota: all-guarded region still gets 5 holders", P.Build(9, allGuarded, catalog, k).Pieces.Count(x => x.Kind == P.HolderObject) == 5);

		// 3. Determinism and seed sensitivity.
		var again = P.Build(12345, roomy, catalog, k);
		Check("deterministic", again.TrueNode == plan.TrueNode && again.FalseNodes.SequenceEqual(plan.FalseNodes) && again.Pieces.Select(p => p.Node).SequenceEqual(plan.Pieces.Select(p => p.Node)) && Describe(again.Contents) == Describe(plan.Contents));
		var other = P.Build(54321, roomy, catalog, k);
		Check("different seed differs", other.TrueNode != plan.TrueNode || !other.FalseNodes.SequenceEqual(plan.FalseNodes));

		// 4. Cramped corridor (1 tile wide, 12 long): guard relaxes, all points distinct.
		var corridor = Rect(2, 200, 12, 1, 2);
		plan = P.Build(7, corridor, catalog, k);
		var all = plan.Pieces.Select(p => p.Node).Concat(plan.FalseNodes).Append(plan.TrueNode).ToList();
		Check("corridor: relaxed to fit 9 points", plan.FinalSpacing < plan.StartSpacing && all.Count == 9 && all.Distinct().Count() == 9, $"start={plan.StartSpacing} final={plan.FinalSpacing} points={all.Count}");

		// 5. No holders at all: 5 loose pieces on empty tiles.
		var empty = Rect(3, 200, 30, 30, 0);
		plan = P.Build(9, empty, catalog, k);
		Check("no holders: 5 loose pieces", plan.Pieces.Length == 5 && plan.Pieces.All(p => p.Kind == P.HolderLoose));

		// 6. Tiny region (4 tiles): degrades without throwing.
		var tiny = Rect(4, 200, 2, 2, 0);
		plan = P.Build(9, tiny, catalog, k);
		Check("tiny: no crash, has a true tile", plan != null && plan.TrueNode >= 0, $"pieces={plan.Pieces.Length} false={plan.FalseNodes.Length}");

		// 7. Contents statistics over many regions at V = 8000.
		int units = 0, artifacts = 0, n = 6000, badTotal = 0, noGold = 0, noRes = 0, multiUnit = 0;
		for (var i = 0; i < n; i++)
		{
			var c = P.RollContents(new P.Rng((ulong)i, 1), 8000, catalog);
			if (c.UnitSid != null) units++;
			if (c.ArtifactSid != null) artifacts++;
			if (Math.Abs(c.Total() - 8000) > 600) badTotal++;
			if (c.Gold < 500) noGold++;
			if (c.Resources.Count == 0 || c.Resources.Any(r => r.Amount < 1)) noRes++;
		}
		Check("units in ~1/3", Math.Abs(units / (double)n - 1 / 3.0) < 0.03, (units / (double)n).ToString("0.000"));
		Check("artifacts in ~2/3", Math.Abs(artifacts / (double)n - 2 / 3.0) < 0.03, (artifacts / (double)n).ToString("0.000"));
		Check("totals within 600 of V", badTotal == 0, badTotal.ToString());
		Check("always gold and resources", noGold == 0 && noRes == 0 && multiUnit == 0);
		for (var i = 0; i < 4; i++)
			Console.WriteLine("  sample V=8000: " + Describe(P.RollContents(new P.Rng((ulong)i, 1), 8000, catalog)));
		for (var i = 0; i < 3; i++)
			Console.WriteLine("  sample V=23250: " + Describe(P.RollContents(new P.Rng((ulong)i, 2), 23250, catalog)));

		// 8. Single-area split.
		var big = Rect(0, 100, 100, 60, 0);
		var nodes = Enumerable.Range(0, 100 * 60).ToList();
		var split = P.SplitSingleArea(1, 100, nodes, new[] { 5 + 5 * 100, 90 + 5 * 100, 50 + 50 * 100, 6 + 6 * 100 });
		var sizes = split.Values.GroupBy(v => v).Select(g => g.Count()).OrderBy(v => v).ToList();
		Check("split: covers all tiles", split.Count == nodes.Count);
		Check("split: 3 cells (close seeds merged), none tiny", sizes.Count == 3 && sizes[0] >= P.SplitMinTiles, string.Join(",", sizes));
		var seedless = P.SplitSingleArea(1, 100, nodes, Array.Empty<int>());
		var seedlessSizes = seedless.Values.GroupBy(v => v).Select(g => g.Count()).OrderBy(v => v).ToList();
		Check("split: no seeds -> spread cells", seedlessSizes.Count >= 4 && seedlessSizes[0] >= P.SplitMinTiles, string.Join(",", seedlessSizes));
		Check("split: deterministic", P.SplitSingleArea(1, 100, nodes, Array.Empty<int>()).SequenceEqual(seedless));

		// 9. Real maps.
		foreach (var path in args)
		{
			using var doc = JsonDocument.Parse(File.ReadAllText(path));
			var root = doc.RootElement;
			var width = root.GetProperty("width").GetInt32();
			var seed = (ulong)root.GetProperty("seed").GetInt64();
			var real = new P.Catalog
			{
				Artifacts = root.GetProperty("catalog").GetProperty("artifacts").EnumerateArray().Select(a => new P.ArtifactEntry { Sid = a.GetProperty("sid").GetString(), Value = a.GetProperty("value").GetInt32() }).ToList(),
				Units = root.GetProperty("catalog").GetProperty("units").EnumerateArray().Select(u => new P.UnitEntry { Sid = u.GetProperty("sid").GetString(), SquadValue = u.GetProperty("squadValue").GetInt32(), Tier = u.GetProperty("tier").GetInt32() }).ToList(),
			};
			var inputs = new List<P.RegionInput>();
			foreach (var area in root.GetProperty("areas").EnumerateArray())
			{
				inputs.Add(new P.RegionInput
				{
					RegionId = area.GetProperty("id").GetInt32(),
					Width = width,
					TileCount = area.GetProperty("nodes").GetArrayLength(),
					HolderCandidates = area.GetProperty("holders").EnumerateArray().Select(h => new P.Holder { Node = h.GetInt32(), Key = h.GetInt32() }).ToList(),
					DigCandidates = area.GetProperty("dig").EnumerateArray().Select(d => d.GetInt32()).ToList(),
					Richness = P.AnchorRichness,
				});
			}
			var watch = Stopwatch.StartNew();
			var plans = inputs.Select(i => P.Build(seed, i, real, k)).ToList();
			watch.Stop();
			var name = root.GetProperty("name").GetString();
			var complete = plans.Count(p => p.Pieces.Length == 5 && p.FalseNodes.Length == 3 && p.TrueNode >= 0);
			var relaxed = plans.Count(p => p.FinalSpacing < p.StartSpacing);
			var loose = plans.Sum(p => p.Pieces.Count(x => x.Kind == P.HolderLoose));
			var worst = Enumerable.Range(0, plans.Count).Where(i => plans[i].TrueNode >= 0 && plans[i].Pieces.Length > 0).Select(i => MinPairDistance(plans[i], width)).DefaultIfEmpty(0).Min();
			Console.WriteLine($"  {name}: {plans.Count} regions in {watch.Elapsed.TotalMilliseconds:0.0} ms total ({watch.Elapsed.TotalMilliseconds / Math.Max(1, plans.Count):0.00} ms each); complete={complete} relaxed={relaxed} loosePieces={loose} worstMinDistance={worst}");
			foreach (var p in plans.Take(3))
				Console.WriteLine($"    region {p.RegionId}: spacing {p.StartSpacing}->{p.FinalSpacing}, true={p.TrueNode}, {Describe(p.Contents)}");
			Check(name + ": every region with tiles gets a true tile", plans.Zip(inputs).All(x => x.Second.DigCandidates.Count == 0 || x.First.TrueNode >= 0));
			Check(name + ": all points distinct", plans.All(p => { var pts = p.Pieces.Select(x => x.Node).Concat(p.FalseNodes).Append(p.TrueNode).Where(v => v >= 0).ToList(); return pts.Distinct().Count() == pts.Count; }));
			Check(name + ": under 5 ms per region", watch.Elapsed.TotalMilliseconds / Math.Max(1, plans.Count) < 5);
		}

		Console.WriteLine(_fails == 0 ? "ALL PASS" : _fails + " FAILED");
		return _fails == 0 ? 0 : 1;
	}
}
