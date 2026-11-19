using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting: pure, deterministic per-region plan (docs/cove_treasure_hunting_design.md).
/// No game or interop references, so tools/cove_treasure/plan_harness compiles this file as-is.
/// A plan is a pure function of (map seed, region id, the region's day-1 candidates, richness, catalog): the same
/// map always buries the same treasure, so plans are never saved. Square grid, node = x + z * width, 8-neighbour
/// (Chebyshev) distance.
/// </summary>
internal static class Homm3CoveTreasurePlan
{
	internal const int PiecesPerRegion = 5;
	internal const int FalseLeads = 3;
	internal const int MinSpacingFloor = 4;
	internal const int MinValue = 4000;
	internal const int MaxValue = 80000;
	/// <summary>Gold's worth every treasure holds on top of its richness share (user, 2026-11-18), so even a poor
	/// region's treasure is worth the trip. MinValue and MaxValue bound the richness share alone.</summary>
	internal const int BaseValue = 8000;
	internal const int SplitMinTiles = 400;
	internal const int SplitTargetTiles = 900;

	internal const int MinGuardedPieces = 2;
	internal const int MinUnguardedPieces = 1;
	internal const byte HolderObject = 0;
	internal const byte HolderSquad = 1;
	internal const byte HolderLoose = 2;

	/// <summary>Core resource sids, spelled as identifiers so this file stays free of raw sid literals
	/// (the symbol literal confinement gate reads a short raw "ore" as a possible build symbol).</summary>
	private enum ResourceSid { wood, ore, gemstones, crystals, mercury, dust }

	internal static readonly (string Name, int Gold)[] ResourcePrices =
	{
		(nameof(ResourceSid.wood), 200), (nameof(ResourceSid.ore), 200), (nameof(ResourceSid.gemstones), 400),
		(nameof(ResourceSid.crystals), 400), (nameof(ResourceSid.mercury), 400), (nameof(ResourceSid.dust), 125),
	};

	internal struct Holder
	{
		internal int Node;
		internal long Key;
		internal byte Kind;
		/// <summary>A neutral stack, or an object a neutral stack stands next to. User rule (2026-11-17): at least
		/// <see cref="MinGuardedPieces"/> pieces are guarded and at least <see cref="MinUnguardedPieces"/> is not.</summary>
		internal bool Guarded;
	}

	internal sealed class RegionInput
	{
		internal int RegionId;
		internal int Width;
		internal int TileCount;
		internal IReadOnlyList<Holder> HolderCandidates;
		internal IReadOnlyList<int> DigCandidates;
		internal long Richness;
	}

	internal struct ArtifactEntry
	{
		internal string Sid;
		internal int Value;
	}

	internal struct UnitEntry
	{
		internal string Sid;
		internal int SquadValue;
		internal int Tier;
	}

	internal sealed class Catalog
	{
		internal IReadOnlyList<ArtifactEntry> Artifacts = Array.Empty<ArtifactEntry>();
		internal IReadOnlyList<UnitEntry> Units = Array.Empty<UnitEntry>();
	}

	internal sealed class Contents
	{
		internal int Gold;
		internal readonly List<(string Name, int Amount)> Resources = new();
		internal string ArtifactSid;
		internal int ArtifactValue;
		internal string UnitSid;
		internal int UnitCount;
		internal int UnitValue;

		internal int Total()
		{
			var total = Gold + ArtifactValue + UnitValue;
			foreach (var (name, amount) in Resources)
				total += amount * PriceOf(name);
			return total;
		}
	}

	internal sealed class RegionPlan
	{
		internal int RegionId;
		internal Holder[] Pieces;
		internal int TrueNode = -1;
		/// <summary>False leads in elimination order: piece 2 removes [0], piece 3 removes [1], piece 4 removes [2].</summary>
		internal int[] FalseNodes = Array.Empty<int>();
		internal int StartSpacing;
		internal int FinalSpacing;
		internal int Value;
		internal Contents Contents;
	}

	internal static int PriceOf(string resource)
	{
		foreach (var (name, gold) in ResourcePrices)
			if (string.Equals(name, resource, StringComparison.Ordinal))
				return gold;
		return 0;
	}

	/// <summary>Richness (DataArea.pickableObjectsValuesOnStart) of the Cove start region on Blitz, measured in game on
	/// 2026-11-17 (build 26615913, 17 regions, map total 7,900,450). It anchors that region at 16000 gold
	/// (doubled from 8000 on 2026-11-17: the user found treasures not quite worth the effort).</summary>
	internal const long AnchorRichness = 558525;
	internal const int AnchorValue = 16000;
	internal const double AnchorK = (double)AnchorValue / AnchorRichness;

	/// <summary>Treasure value in gold: <see cref="BaseValue"/> plus the richness share. <paramref name="k"/> is fixed
	/// so the Blitz Cove start region's share is 16000 (24000 in all).</summary>
	internal static int ValueFor(long richness, double k)
	{
		var raw = richness <= 0 ? 0 : k * richness;
		var rounded = (int)(Math.Round(raw / 250.0) * 250.0);
		return BaseValue + Math.Max(MinValue, Math.Min(MaxValue, rounded));
	}

	internal static int StartSpacingFor(int tileCount)
	{
		var points = PiecesPerRegion + 1 + FalseLeads;
		return Math.Max(MinSpacingFloor, (int)Math.Round(0.5 * Math.Sqrt(Math.Max(1, tileCount) / (double)points)));
	}

	internal static int Distance(int a, int b, int width)
	{
		var dx = Math.Abs(a % width - b % width);
		var dz = Math.Abs(a / width - b / width);
		return dx > dz ? dx : dz;
	}

	internal static RegionPlan Build(ulong mapSeed, RegionInput input, Catalog catalog, double k)
	{
		if (input == null || input.Width <= 0)
			return null;
		var rng = new Rng(mapSeed, (ulong)(uint)input.RegionId);
		var plan = new RegionPlan { RegionId = input.RegionId };
		var spacing = StartSpacingFor(input.TileCount);
		plan.StartSpacing = spacing;

		var chosen = new List<int>(PiecesPerRegion + 1 + FalseLeads);
		var dig = input.DigCandidates ?? Array.Empty<int>();
		var holders = input.HolderCandidates ?? Array.Empty<Holder>();

		// Treasure tiles first: the true tile and the false leads come from the same pool, in the same way.
		var leads = new List<int>(1 + FalseLeads);
		for (var i = 0; i < 1 + FalseLeads; i++)
		{
			var index = PickSpaced(rng, dig.Count, n => dig[n], chosen, input.Width, ref spacing);
			if (index < 0)
				break;
			leads.Add(dig[index]);
			chosen.Add(dig[index]);
		}
		if (leads.Count > 0)
		{
			var trueIndex = rng.Next(leads.Count);
			plan.TrueNode = leads[trueIndex];
			leads.RemoveAt(trueIndex);
			plan.FalseNodes = leads.ToArray();
		}

		var pieces = new List<Holder>(PiecesPerRegion);
		// Quota first (guarded, then unguarded), the rest from the whole pool. A quota the region cannot fill falls
		// back to the whole pool, so a region with no stacks still gets its five pieces.
		var guarded = new List<Holder>();
		var unguarded = new List<Holder>();
		foreach (var holder in holders)
			(holder.Guarded ? guarded : unguarded).Add(holder);
		for (var i = 0; i < PiecesPerRegion; i++)
		{
			IReadOnlyList<Holder> pool = i < MinGuardedPieces ? guarded : i < MinGuardedPieces + MinUnguardedPieces ? unguarded : holders;
			var index = PickSpaced(rng, pool.Count, n => pool[n].Node, chosen, input.Width, ref spacing);
			if (index < 0 && !ReferenceEquals(pool, holders))
			{
				pool = holders;
				index = PickSpaced(rng, pool.Count, n => pool[n].Node, chosen, input.Width, ref spacing);
			}
			if (index < 0)
				break;
			pieces.Add(pool[index]);
			chosen.Add(pool[index].Node);
		}
		// Too few holders in the region: the rest lie loose on empty tiles.
		while (pieces.Count < PiecesPerRegion)
		{
			var index = PickSpaced(rng, dig.Count, n => dig[n], chosen, input.Width, ref spacing);
			if (index < 0)
				break;
			pieces.Add(new Holder { Node = dig[index], Key = dig[index], Kind = HolderLoose });
			chosen.Add(dig[index]);
		}
		plan.Pieces = pieces.ToArray();
		plan.FinalSpacing = spacing;

		plan.Value = ValueFor(input.Richness, k);
		// Own random stream: the contents must come out the same on a reload, whatever the holder pool looks like by then.
		plan.Contents = RollContents(ContentsRng(mapSeed, input.RegionId), plan.Value, catalog ?? new Catalog());
		return plan;
	}

	internal static Rng ContentsRng(ulong mapSeed, int regionId) => new(mapSeed, 0x1_0000_0000UL | (uint)regionId);

	/// <summary>
	/// Picks a random candidate at least <paramref name="spacing"/> from every chosen node. When none fits, the
	/// spacing drops by one and the pick is retried; at spacing 1 only the exact chosen nodes are excluded.
	/// Returns -1 when the pool has no unused node at all.
	/// </summary>
	private static int PickSpaced(Rng rng, int count, Func<int, int> nodeAt, List<int> chosen, int width, ref int spacing)
	{
		if (count <= 0)
			return -1;
		var eligible = new List<int>();
		for (var d = Math.Max(1, spacing); d >= 1; d--)
		{
			eligible.Clear();
			for (var i = 0; i < count; i++)
			{
				var node = nodeAt(i);
				var ok = true;
				for (var c = 0; c < chosen.Count; c++)
				{
					if (Distance(node, chosen[c], width) < d)
					{
						ok = false;
						break;
					}
				}
				if (ok)
					eligible.Add(i);
			}
			if (eligible.Count > 0)
			{
				spacing = d;
				return eligible[rng.Next(eligible.Count)];
			}
		}
		return -1;
	}

	internal static Contents RollContents(Rng rng, int value, Catalog catalog)
	{
		var contents = new Contents();
		var remaining = value;

		// Units: 1 in 3 treasures, one unit type, 25% of the value.
		var wantUnits = rng.Next(3) == 0;
		// Artifact: 2 in 3 treasures. Both rolls are always drawn so one never shifts the other.
		var wantArtifact = rng.Next(3) != 0;

		if (wantUnits && catalog.Units.Count > 0)
		{
			var budget = value / 4;
			var best = new List<UnitEntry>();
			var bestTier = -1;
			foreach (var unit in catalog.Units)
			{
				if (unit.SquadValue <= 0 || budget / unit.SquadValue < 3)
					continue;
				if (unit.Tier > bestTier)
				{
					bestTier = unit.Tier;
					best.Clear();
				}
				if (unit.Tier == bestTier)
					best.Add(unit);
			}
			if (best.Count == 0)
			{
				foreach (var unit in catalog.Units)
					if (unit.SquadValue > 0 && unit.SquadValue <= budget)
						best.Add(unit);
			}
			if (best.Count > 0)
			{
				var unit = best[rng.Next(best.Count)];
				contents.UnitSid = unit.Sid;
				contents.UnitCount = budget / unit.SquadValue;
				contents.UnitValue = contents.UnitCount * unit.SquadValue;
				remaining -= contents.UnitValue;
			}
		}

		if (wantArtifact && catalog.Artifacts.Count > 0)
		{
			var budget = remaining * 45 / 100;
			// Highest standard rarity band that fits, then any artifact in that band.
			var floor = budget >= 24000 ? 12001 : budget >= 12000 ? 6001 : budget >= 6000 ? 3001 : 0;
			var fits = new List<ArtifactEntry>();
			foreach (var artifact in catalog.Artifacts)
				if (artifact.Value >= floor && artifact.Value <= budget && artifact.Value >= 1000)
					fits.Add(artifact);
			if (fits.Count == 0 && floor > 0)
			{
				foreach (var artifact in catalog.Artifacts)
					if (artifact.Value <= budget && artifact.Value >= 1000)
						fits.Add(artifact);
			}
			if (fits.Count > 0)
			{
				var artifact = fits[rng.Next(fits.Count)];
				contents.ArtifactSid = artifact.Sid;
				contents.ArtifactValue = artifact.Value;
				remaining -= artifact.Value;
			}
		}

		// Gold and resources always. Gold takes 55-70% of what is left, resources the rest.
		var goldPercent = 55 + rng.Next(16);
		var resourceBudget = remaining * (100 - goldPercent) / 100;
		var typeCount = 1 + rng.Next(3);
		var order = new int[ResourcePrices.Length];
		for (var i = 0; i < order.Length; i++)
			order[i] = i;
		for (var i = order.Length - 1; i > 0; i--)
		{
			var j = rng.Next(i + 1);
			(order[i], order[j]) = (order[j], order[i]);
		}
		var spent = 0;
		for (var i = 0; i < typeCount; i++)
		{
			var (name, price) = ResourcePrices[order[i]];
			var amount = Math.Max(1, (int)Math.Round(resourceBudget / (double)typeCount / price));
			contents.Resources.Add((name, amount));
			spent += amount * price;
		}
		var gold = remaining - spent;
		contents.Gold = Math.Max(500, (int)(Math.Round(gold / 50.0) * 50.0));
		return contents;
	}

	/// <summary>
	/// Splits one whole-map area into pseudo-regions (H3 stock imports and some campaign maps have a single area).
	/// Multi-source flood from <paramref name="seedNodes"/> (towns, mines) over the area's own tiles; cells under
	/// <see cref="SplitMinTiles"/> merge into the neighbour they touch most. With fewer than two usable seeds the
	/// seeds are spread by farthest-point picking, one per <see cref="SplitTargetTiles"/> tiles.
	/// Returns node -> region index (0-based, dense).
	/// </summary>
	internal static Dictionary<int, int> SplitSingleArea(ulong mapSeed, int width, IReadOnlyList<int> nodes, IReadOnlyList<int> seedNodes)
	{
		var region = new Dictionary<int, int>(nodes.Count);
		if (nodes.Count == 0 || width <= 0)
			return region;
		var inArea = new HashSet<int>(nodes);
		var seeds = new List<int>();
		if (seedNodes != null)
			foreach (var seed in seedNodes)
				if (inArea.Contains(seed) && !seeds.Contains(seed))
					seeds.Add(seed);
		var wanted = Math.Max(1, nodes.Count / SplitTargetTiles);
		if (seeds.Count < 2 && wanted >= 2)
		{
			var rng = new Rng(mapSeed, 0x5eedUL);
			if (seeds.Count == 0)
				seeds.Add(nodes[rng.Next(nodes.Count)]);
			while (seeds.Count < wanted)
			{
				var bestNode = -1;
				var bestDistance = -1;
				foreach (var node in nodes)
				{
					var nearest = int.MaxValue;
					foreach (var seed in seeds)
						nearest = Math.Min(nearest, Distance(node, seed, width));
					if (nearest > bestDistance)
					{
						bestDistance = nearest;
						bestNode = node;
					}
				}
				if (bestNode < 0 || bestDistance <= 0)
					break;
				seeds.Add(bestNode);
			}
		}
		if (seeds.Count == 0)
			seeds.Add(nodes[0]);

		var queue = new Queue<int>();
		for (var i = 0; i < seeds.Count; i++)
		{
			region[seeds[i]] = i;
			queue.Enqueue(seeds[i]);
		}
		var regionCount = seeds.Count;
		while (true)
		{
			while (queue.Count > 0)
			{
				var node = queue.Dequeue();
				var owner = region[node];
				foreach (var next in Neighbours(node, width))
				{
					if (!inArea.Contains(next) || region.ContainsKey(next))
						continue;
					region[next] = owner;
					queue.Enqueue(next);
				}
			}
			if (region.Count == nodes.Count)
				break;
			// Tiles cut off from every seed (islands) start their own cell.
			foreach (var node in nodes)
			{
				if (region.ContainsKey(node))
					continue;
				region[node] = regionCount++;
				queue.Enqueue(node);
				break;
			}
		}

		// Merge small cells into the neighbour they share the longest border with.
		while (true)
		{
			var sizes = new int[regionCount];
			foreach (var pair in region)
				sizes[pair.Value]++;
			var smallest = -1;
			for (var i = 0; i < regionCount; i++)
				if (sizes[i] > 0 && sizes[i] < SplitMinTiles && (smallest < 0 || sizes[i] < sizes[smallest]))
					smallest = i;
			if (smallest < 0)
				break;
			var border = new int[regionCount];
			foreach (var pair in region)
			{
				if (pair.Value != smallest)
					continue;
				foreach (var next in Neighbours(pair.Key, width))
					if (region.TryGetValue(next, out var other) && other != smallest)
						border[other]++;
			}
			var target = -1;
			for (var i = 0; i < regionCount; i++)
				if (border[i] > 0 && (target < 0 || border[i] > border[target]))
					target = i;
			if (target < 0)
			{
				// Isolated small cell with no neighbour: leave it, but stop it from being picked again.
				var live = 0;
				for (var i = 0; i < regionCount; i++)
					if (sizes[i] > 0)
						live++;
				if (live <= 1)
					break;
				target = FindNearestRegion(region, smallest, width);
				if (target < 0)
					break;
			}
			var keys = new List<int>();
			foreach (var pair in region)
				if (pair.Value == smallest)
					keys.Add(pair.Key);
			foreach (var key in keys)
				region[key] = target;
		}

		// Dense renumbering in order of lowest node, so ids are stable.
		var remap = new Dictionary<int, int>();
		var sorted = new List<int>(nodes);
		sorted.Sort();
		foreach (var node in sorted)
		{
			var old = region[node];
			if (!remap.ContainsKey(old))
				remap[old] = remap.Count;
		}
		foreach (var node in sorted)
			region[node] = remap[region[node]];
		return region;
	}

	private static int FindNearestRegion(Dictionary<int, int> region, int from, int width)
	{
		var best = -1;
		var bestDistance = int.MaxValue;
		var mine = new List<int>();
		foreach (var pair in region)
			if (pair.Value == from)
				mine.Add(pair.Key);
		foreach (var pair in region)
		{
			if (pair.Value == from)
				continue;
			foreach (var node in mine)
			{
				var d = Distance(node, pair.Key, width);
				if (d < bestDistance)
				{
					bestDistance = d;
					best = pair.Value;
				}
			}
		}
		return best;
	}

	private static IEnumerable<int> Neighbours(int node, int width)
	{
		var x = node % width;
		for (var dz = -1; dz <= 1; dz++)
		{
			for (var dx = -1; dx <= 1; dx++)
			{
				if (dx == 0 && dz == 0)
					continue;
				var nx = x + dx;
				if (nx < 0 || nx >= width)
					continue;
				var next = node + dx + dz * width;
				if (next >= 0)
					yield return next;
			}
		}
	}

	/// <summary>SplitMix64. Own generator so results never depend on the runtime's System.Random.</summary>
	internal sealed class Rng
	{
		private ulong _state;

		internal Rng(ulong seed, ulong stream)
		{
			_state = seed ^ (stream + 1UL) * 0x9E3779B97F4A7C15UL;
			NextRaw();
		}

		private ulong NextRaw()
		{
			var z = _state += 0x9E3779B97F4A7C15UL;
			z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
			z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
			return z ^ (z >> 31);
		}

		internal int Next(int exclusiveMax)
		{
			if (exclusiveMax <= 1)
				return 0;
			return (int)(NextRaw() % (ulong)exclusiveMax);
		}
	}
}
