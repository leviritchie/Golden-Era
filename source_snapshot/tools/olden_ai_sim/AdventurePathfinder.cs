using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>
	/// Lightweight 4-neighbor grid pathfinder with portals + occupancy blockers.
	/// When MoveCost length-matches the grid it is the sole cell-cost authority.
	/// </summary>
	public static class AdventurePathfinder
	{
		public static int NodeOf(int x, int z, int sizeX)
		{
			return z * sizeX + x;
		}

		public static void XzOf(int node, int sizeX, out int x, out int z)
		{
			x = sizeX <= 0 ? 0 : node % sizeX;
			z = sizeX <= 0 ? 0 : node / sizeX;
		}

		public static bool InBounds(int node, AdventureSimState state)
		{
			if (state == null || state.SizeX <= 0 || state.SizeZ <= 0)
				return false;
			return node >= 0 && node < state.SizeX * state.SizeZ;
		}

		public static bool MoveCostIsAuthority(AdventureSimState state)
		{
			if (state == null || state.SizeX <= 0 || state.SizeZ <= 0)
				return false;
			var n = state.SizeX * state.SizeZ;
			return state.MoveCost != null && state.MoveCost.Length == n;
		}

		public static bool IsPathable(AdventureSimState state, int node)
		{
			if (!InBounds(node, state))
				return false;
			if (state.Pathable == null || state.Pathable.Length != state.SizeX * state.SizeZ)
				return false;
			return state.Pathable[node];
		}

		public static bool IsBlockedByOccupancy(AdventureSimState state, List<AdventureSimOccupant> occupancy, int node, int allowEntityId)
		{
			if (occupancy == null)
				return false;
			for (var i = 0; i < occupancy.Count; i++)
			{
				var o = occupancy[i];
				if (o == null || !o.Alive)
					continue;
				if (o.Node != node)
					continue;
				if (o.EntityId == allowEntityId)
					continue;
				// Pickups do not block; combatants/towns/mines do.
				if (o.Kind == AdventureSimTargetKind.Pickup)
					continue;
				return true;
			}
			return false;
		}

		public static int CellCost(AdventureSimState state, AdventureSimKnobs knobs, int node)
		{
			var fallback = knobs != null && knobs.DefaultMoveCost > 0 ? knobs.DefaultMoveCost : 100;
			if (MoveCostIsAuthority(state))
				return Math.Max(1, state.MoveCost[node]);

			if (knobs != null && knobs.UseTerrainCosts
				&& state?.Terrain != null && node >= 0 && node < state.Terrain.Length)
			{
				// Prefer committed Olden table when tile id looks like Core (1..23).
				var tile = state.Terrain[node];
				if (tile >= 1 && tile <= 23)
					return Math.Max(1, OldenTileMp.StepMpForTile(tile));
				var mult = AdventureSimTerrain.CostMultiplier(tile);
				return Math.Max(1, (fallback * mult) / 100);
			}
			return fallback;
		}

		public static Dictionary<int, int> ReachableCosts(AdventureSimState state, AdventureSimKnobs knobs, int origin, int maxCost)
		{
			return ReachableCosts(state, knobs, origin, maxCost, null, -1);
		}

		public static Dictionary<int, int> ReachableCosts(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			int origin,
			int maxCost,
			List<AdventureSimOccupant> occupancy,
			int allowEntityId)
		{
			var result = new Dictionary<int, int>();
			if (state == null || !InBounds(origin, state) || !IsPathable(state, origin))
				return result;
			if (IsBlockedByOccupancy(state, occupancy, origin, allowEntityId) && origin != FindNode(occupancy, allowEntityId))
				return result;

			var open = new SortedSet<ReachKey>();
			open.Add(new ReachKey(0, origin));
			result[origin] = 0;

			while (open.Count > 0)
			{
				var cur = open.Min;
				open.Remove(cur);
				int cost;
				if (!result.TryGetValue(cur.Node, out cost) || cost != cur.Cost)
					continue;
				if (cost > maxCost)
					continue;

				XzOf(cur.Node, state.SizeX, out var x, out var z);
				TryRelax(state, knobs, occupancy, allowEntityId, open, result, x + 1, z, cost, maxCost);
				TryRelax(state, knobs, occupancy, allowEntityId, open, result, x - 1, z, cost, maxCost);
				TryRelax(state, knobs, occupancy, allowEntityId, open, result, x, z + 1, cost, maxCost);
				TryRelax(state, knobs, occupancy, allowEntityId, open, result, x, z - 1, cost, maxCost);
				RelaxPortals(state, knobs, occupancy, allowEntityId, open, result, cur.Node, cost, maxCost);
			}
			return result;
		}

		public static List<int> ReconstructPath(AdventureSimState state, AdventureSimKnobs knobs, int origin, int goal, int maxCost)
		{
			return ReconstructPath(state, knobs, origin, goal, maxCost, null, -1);
		}

		public static List<int> ReconstructPath(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			int origin,
			int goal,
			int maxCost,
			List<AdventureSimOccupant> occupancy,
			int allowEntityId)
		{
			var costs = ReachableCosts(state, knobs, origin, maxCost, occupancy, allowEntityId);
			var path = new List<int>();
			if (!costs.ContainsKey(goal))
				return path;

			var cur = goal;
			path.Add(cur);
			var guard = 0;
			while (cur != origin && guard++ < 10000)
			{
				XzOf(cur, state.SizeX, out var x, out var z);
				var best = cur;
				var bestCost = costs[cur];
				TryBetter(state, costs, x + 1, z, ref best, ref bestCost);
				TryBetter(state, costs, x - 1, z, ref best, ref bestCost);
				TryBetter(state, costs, x, z + 1, ref best, ref bestCost);
				TryBetter(state, costs, x, z - 1, ref best, ref bestCost);
				TryBetterPortals(state, costs, cur, ref best, ref bestCost);
				if (best == cur)
					break;
				cur = best;
				path.Add(cur);
			}
			path.Reverse();
			return path;
		}

		public static void AddPortal(AdventureSimState state, int a, int b)
		{
			if (state == null)
				return;
			if (state.Portals == null)
				state.Portals = new Dictionary<int, List<int>>();
			Link(state.Portals, a, b);
			Link(state.Portals, b, a);
		}

		private static void Link(Dictionary<int, List<int>> map, int from, int to)
		{
			List<int> list;
			if (!map.TryGetValue(from, out list) || list == null)
			{
				list = new List<int>();
				map[from] = list;
			}
			if (!list.Contains(to))
				list.Add(to);
		}

		private static int FindNode(List<AdventureSimOccupant> occupancy, int entityId)
		{
			if (occupancy == null || entityId < 0)
				return -1;
			for (var i = 0; i < occupancy.Count; i++)
			{
				if (occupancy[i] != null && occupancy[i].EntityId == entityId)
					return occupancy[i].Node;
			}
			return -1;
		}

		private static void TryBetter(AdventureSimState state, Dictionary<int, int> costs, int x, int z, ref int best, ref int bestCost)
		{
			if (x < 0 || z < 0 || x >= state.SizeX || z >= state.SizeZ)
				return;
			var node = NodeOf(x, z, state.SizeX);
			int c;
			if (!costs.TryGetValue(node, out c))
				return;
			if (c < bestCost)
			{
				bestCost = c;
				best = node;
			}
		}

		private static void TryBetterPortals(AdventureSimState state, Dictionary<int, int> costs, int cur, ref int best, ref int bestCost)
		{
			if (state.Portals == null)
				return;
			List<int> links;
			if (!state.Portals.TryGetValue(cur, out links) || links == null)
				return;
			for (var i = 0; i < links.Count; i++)
			{
				int c;
				if (!costs.TryGetValue(links[i], out c))
					continue;
				if (c < bestCost)
				{
					bestCost = c;
					best = links[i];
				}
			}
		}

		private static void RelaxPortals(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			List<AdventureSimOccupant> occupancy,
			int allowEntityId,
			SortedSet<ReachKey> open,
			Dictionary<int, int> result,
			int fromNode,
			int fromCost,
			int maxCost)
		{
			if (state.Portals == null)
				return;
			List<int> links;
			if (!state.Portals.TryGetValue(fromNode, out links) || links == null)
				return;
			for (var i = 0; i < links.Count; i++)
			{
				var node = links[i];
				if (!IsPathable(state, node))
					continue;
				if (IsBlockedByOccupancy(state, occupancy, node, allowEntityId))
					continue;
				// Portal hop costs the destination cell.
				var next = fromCost + CellCost(state, knobs, node);
				if (next > maxCost)
					continue;
				int prior;
				if (result.TryGetValue(node, out prior) && prior <= next)
					continue;
				result[node] = next;
				open.Add(new ReachKey(next, node));
			}
		}

		private static void TryRelax(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			List<AdventureSimOccupant> occupancy,
			int allowEntityId,
			SortedSet<ReachKey> open,
			Dictionary<int, int> result,
			int x,
			int z,
			int fromCost,
			int maxCost)
		{
			if (x < 0 || z < 0 || x >= state.SizeX || z >= state.SizeZ)
				return;
			var node = NodeOf(x, z, state.SizeX);
			if (!IsPathable(state, node))
				return;
			if (IsBlockedByOccupancy(state, occupancy, node, allowEntityId))
				return;
			var next = fromCost + CellCost(state, knobs, node);
			if (next > maxCost)
				return;
			int prior;
			if (result.TryGetValue(node, out prior) && prior <= next)
				return;
			result[node] = next;
			open.Add(new ReachKey(next, node));
		}

		private struct ReachKey : IComparable<ReachKey>
		{
			public readonly int Cost;
			public readonly int Node;

			public ReachKey(int cost, int node)
			{
				Cost = cost;
				Node = node;
			}

			public int CompareTo(ReachKey other)
			{
				var c = Cost.CompareTo(other.Cost);
				if (c != 0)
					return c;
				return Node.CompareTo(other.Node);
			}
		}
	}
}
