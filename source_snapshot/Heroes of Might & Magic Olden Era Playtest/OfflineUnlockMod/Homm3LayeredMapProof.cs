using System;
using System.Collections.Generic;
using System.Text;
using BepInEx.Logging;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only proof for the planned no-swap campaign map layer model.
/// This constructs a tiny in-memory map with simultaneous surface/underground
/// layers, same-local-node object and event collisions, and an explicit
/// cross-layer transition edge. It does not touch native map data or gameplay.
/// </summary>
internal static class Homm3LayeredMapProof
{
	internal const string DiagnosticFlag = "homm3_layered_map_proof.flag";
	private const string LogPrefix = "HOMM3_LAYERED_MAP_PROOF";
	private static bool _ran;

	internal static void TryRun(ManualLogSource log)
	{
		if (_ran)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		_ran = true;

		try
		{
			var report = SyntheticLayeredMapProof.Run();
			log?.LogInfo(LogPrefix + " result=" + (report.Passed ? "PASS" : "FAIL")
				+ " layers=" + report.Layers
				+ " size=" + report.Width + "x" + report.Height
				+ " nodesPerLayer=" + report.NodesPerLayer
				+ " totalLayerNodes=" + report.TotalLayerNodes
				+ " objectKeys=" + report.ObjectKeys
				+ " eventKeys=" + report.EventKeys
				+ " crossLayerEdges=" + report.CrossLayerEdges
				+ " pathLength=" + report.PathLength
				+ " sameLocalNodeDistinctObjects=" + report.SameLocalNodeDistinctObjects
				+ " sameLocalNodeDistinctEvents=" + report.SameLocalNodeDistinctEvents
				+ " pathCrossesLayer=" + report.PathCrossesLayer
				+ " nativeMutation=false");
			log?.LogInfo(LogPrefix + " path=" + report.Path);
			if (!report.Passed)
				log?.LogWarning(LogPrefix + " failures=" + report.Failures);
		}
		catch (Exception ex)
		{
			log?.LogWarning(LogPrefix + " failed closed during synthetic proof: " + ex);
		}
	}

	private static class SyntheticLayeredMapProof
	{
		internal static ProofReport Run()
		{
			var model = new LayeredMapModel(4, 4);
			var surface = model.AddLayer("surface", isUnderground: false, stack: -1);
			var underground = model.AddLayer("underground", isUnderground: true, stack: 0);
			model.FillTerrain(surface, "grass");
			model.FillTerrain(underground, "subterranean");

			var sharedLocalNode = model.Node(2, 2);
			var surfaceShared = new LayerNode(surface, sharedLocalNode);
			var undergroundShared = new LayerNode(underground, sharedLocalNode);
			model.AddObject(surfaceShared, "homm3_surface_learning_stone");
			model.AddObject(undergroundShared, "homm3_underground_prison");
			model.AddEvent(surfaceShared, "homm3_surface_visit_reward");
			model.AddEvent(undergroundShared, "homm3_underground_quest_gate");

			var gateSurface = new LayerNode(surface, model.Node(1, 1));
			var gateUnderground = new LayerNode(underground, model.Node(1, 1));
			model.AddBidirectionalTransition(gateSurface, gateUnderground, "homm3_subterranean_gate_a");

			var start = new LayerNode(surface, model.Node(0, 0));
			var goal = new LayerNode(underground, model.Node(3, 3));
			var path = model.FindPath(start, goal);

			var failures = new List<string>();
			Require(model.LayerCount == 2, "expected-two-layers", failures);
			Require(model.NodesPerLayer == 16, "expected-4x4-layer-size", failures);
			Require(model.TotalLayerNodes == 32, "expected-layer-qualified-node-total", failures);
			Require(surfaceShared.LocalNode == undergroundShared.LocalNode && !surfaceShared.Equals(undergroundShared), "same-local-node-distinct-layer-key", failures);
			Require(model.TryGetObject(surfaceShared, out var surfaceObject) && surfaceObject == "homm3_surface_learning_stone", "surface-object-addressable", failures);
			Require(model.TryGetObject(undergroundShared, out var undergroundObject) && undergroundObject == "homm3_underground_prison", "underground-object-addressable", failures);
			Require(model.TryGetEvent(surfaceShared, out var surfaceEvent) && surfaceEvent == "homm3_surface_visit_reward", "surface-event-addressable", failures);
			Require(model.TryGetEvent(undergroundShared, out var undergroundEvent) && undergroundEvent == "homm3_underground_quest_gate", "underground-event-addressable", failures);
			Require(path.Count > 0, "path-found", failures);
			Require(PathCrossesLayer(path), "path-crosses-layer", failures);
			Require(CountLayerTransitions(path) == 1, "path-uses-one-layer-transition", failures);

			return new ProofReport(
				failures.Count == 0,
				model.LayerCount,
				model.Width,
				model.Height,
				model.NodesPerLayer,
				model.TotalLayerNodes,
				model.ObjectCount,
				model.EventCount,
				model.CrossLayerEdgeCount,
				path.Count,
				surfaceShared.LocalNode == undergroundShared.LocalNode && model.TryGetObject(surfaceShared, out _) && model.TryGetObject(undergroundShared, out _),
				surfaceShared.LocalNode == undergroundShared.LocalNode && model.TryGetEvent(surfaceShared, out _) && model.TryGetEvent(undergroundShared, out _),
				PathCrossesLayer(path),
				FormatPath(model, path),
				FormatFailures(failures));
		}

		private static void Require(bool condition, string label, List<string> failures)
		{
			if (!condition)
				failures.Add(label);
		}

		private static bool PathCrossesLayer(List<LayerNode> path)
		{
			if (path.Count == 0)
				return false;
			var firstLayer = path[0].Layer;
			for (var i = 1; i < path.Count; i++)
			{
				if (path[i].Layer != firstLayer)
					return true;
			}
			return false;
		}

		private static int CountLayerTransitions(List<LayerNode> path)
		{
			var transitions = 0;
			for (var i = 1; i < path.Count; i++)
			{
				if (path[i - 1].Layer != path[i].Layer)
					transitions++;
			}
			return transitions;
		}

		private static string FormatPath(LayeredMapModel model, List<LayerNode> path)
		{
			if (path.Count == 0)
				return "<none>";
			var sb = new StringBuilder();
			for (var i = 0; i < path.Count; i++)
			{
				if (i > 0)
					sb.Append("->");
				sb.Append(model.Format(path[i]));
			}
			return sb.ToString();
		}

		private static string FormatFailures(List<string> failures)
		{
			if (failures.Count == 0)
				return "<none>";
			var sb = new StringBuilder();
			for (var i = 0; i < failures.Count; i++)
			{
				if (i > 0)
					sb.Append(",");
				sb.Append(failures[i]);
			}
			return sb.ToString();
		}
	}

	private sealed class LayeredMapModel
	{
		private readonly List<LayerState> _layers = new List<LayerState>();
		private readonly Dictionary<LayerNode, string> _objects = new Dictionary<LayerNode, string>();
		private readonly Dictionary<LayerNode, string> _events = new Dictionary<LayerNode, string>();
		private readonly Dictionary<LayerNode, List<LayerNode>> _transitions = new Dictionary<LayerNode, List<LayerNode>>();

		internal LayeredMapModel(int width, int height)
		{
			if (width <= 0 || height <= 0)
				throw new ArgumentOutOfRangeException(nameof(width), "Layered map dimensions must be positive.");
			Width = width;
			Height = height;
		}

		internal int Width { get; }
		internal int Height { get; }
		internal int LayerCount => _layers.Count;
		internal int NodesPerLayer => Width * Height;
		internal int TotalLayerNodes => LayerCount * NodesPerLayer;
		internal int ObjectCount => _objects.Count;
		internal int EventCount => _events.Count;
		internal int CrossLayerEdgeCount { get; private set; }

		internal int AddLayer(string name, bool isUnderground, int stack)
		{
			if (string.IsNullOrEmpty(name))
				throw new ArgumentException("Layer name must be explicit.", nameof(name));
			var id = _layers.Count;
			_layers.Add(new LayerState(id, name, isUnderground, stack, NodesPerLayer));
			return id;
		}

		internal int Node(int x, int z)
		{
			if (x < 0 || x >= Width)
				throw new ArgumentOutOfRangeException(nameof(x));
			if (z < 0 || z >= Height)
				throw new ArgumentOutOfRangeException(nameof(z));
			return z * Width + x;
		}

		internal void FillTerrain(int layer, string terrainSid)
		{
			var state = RequireLayer(layer);
			if (string.IsNullOrEmpty(terrainSid))
				throw new ArgumentException("Terrain SID must be explicit.", nameof(terrainSid));
			for (var i = 0; i < state.Terrain.Length; i++)
				state.Terrain[i] = terrainSid;
		}

		internal void AddObject(LayerNode node, string objectSid)
		{
			RequireNode(node);
			if (string.IsNullOrEmpty(objectSid))
				throw new ArgumentException("Object SID must be explicit.", nameof(objectSid));
			if (_objects.ContainsKey(node))
				throw new InvalidOperationException("Duplicate object key " + Format(node));
			_objects.Add(node, objectSid);
		}

		internal bool TryGetObject(LayerNode node, out string objectSid)
		{
			return _objects.TryGetValue(node, out objectSid);
		}

		internal void AddEvent(LayerNode node, string eventSid)
		{
			RequireNode(node);
			if (string.IsNullOrEmpty(eventSid))
				throw new ArgumentException("Event SID must be explicit.", nameof(eventSid));
			if (_events.ContainsKey(node))
				throw new InvalidOperationException("Duplicate event key " + Format(node));
			_events.Add(node, eventSid);
		}

		internal bool TryGetEvent(LayerNode node, out string eventSid)
		{
			return _events.TryGetValue(node, out eventSid);
		}

		internal void AddBidirectionalTransition(LayerNode a, LayerNode b, string transitionSid)
		{
			RequireNode(a);
			RequireNode(b);
			if (a.Layer == b.Layer)
				throw new InvalidOperationException("Layer transition must cross layers.");
			if (a.LocalNode != b.LocalNode)
				throw new InvalidOperationException("This proof requires one explicit same-local-node transition.");
			if (string.IsNullOrEmpty(transitionSid))
				throw new ArgumentException("Transition SID must be explicit.", nameof(transitionSid));
			AddTransition(a, b);
			AddTransition(b, a);
			CrossLayerEdgeCount += 2;
		}

		internal List<LayerNode> FindPath(LayerNode start, LayerNode goal)
		{
			RequireNode(start);
			RequireNode(goal);
			var queue = new Queue<LayerNode>();
			var visited = new HashSet<LayerNode>();
			var previous = new Dictionary<LayerNode, LayerNode>();
			queue.Enqueue(start);
			visited.Add(start);

			while (queue.Count > 0)
			{
				var current = queue.Dequeue();
				if (current.Equals(goal))
					return ReconstructPath(previous, start, goal);
				foreach (var next in EnumerateNeighbors(current))
				{
					if (visited.Contains(next))
						continue;
					visited.Add(next);
					previous.Add(next, current);
					queue.Enqueue(next);
				}
			}

			return new List<LayerNode>();
		}

		internal string Format(LayerNode node)
		{
			var x = node.LocalNode % Width;
			var z = node.LocalNode / Width;
			var layer = RequireLayer(node.Layer);
			return layer.Name + "[" + node.Layer + "](" + x + "," + z + ")";
		}

		private void AddTransition(LayerNode from, LayerNode to)
		{
			if (!_transitions.TryGetValue(from, out var list))
			{
				list = new List<LayerNode>();
				_transitions.Add(from, list);
			}
			if (list.Contains(to))
				throw new InvalidOperationException("Duplicate transition " + Format(from) + " -> " + Format(to));
			list.Add(to);
		}

		private IEnumerable<LayerNode> EnumerateNeighbors(LayerNode node)
		{
			var x = node.LocalNode % Width;
			var z = node.LocalNode / Width;
			if (x > 0)
				yield return new LayerNode(node.Layer, Node(x - 1, z));
			if (x + 1 < Width)
				yield return new LayerNode(node.Layer, Node(x + 1, z));
			if (z > 0)
				yield return new LayerNode(node.Layer, Node(x, z - 1));
			if (z + 1 < Height)
				yield return new LayerNode(node.Layer, Node(x, z + 1));
			if (_transitions.TryGetValue(node, out var crossLayer))
			{
				for (var i = 0; i < crossLayer.Count; i++)
					yield return crossLayer[i];
			}
		}

		private List<LayerNode> ReconstructPath(Dictionary<LayerNode, LayerNode> previous, LayerNode start, LayerNode goal)
		{
			var reversed = new List<LayerNode>();
			var current = goal;
			reversed.Add(current);
			while (!current.Equals(start))
			{
				if (!previous.TryGetValue(current, out var prev))
					throw new InvalidOperationException("Path reconstruction lost predecessor for " + Format(current));
				current = prev;
				reversed.Add(current);
			}
			reversed.Reverse();
			return reversed;
		}

		private LayerState RequireLayer(int layer)
		{
			if (layer < 0 || layer >= _layers.Count)
				throw new ArgumentOutOfRangeException(nameof(layer));
			return _layers[layer];
		}

		private void RequireNode(LayerNode node)
		{
			RequireLayer(node.Layer);
			if (node.LocalNode < 0 || node.LocalNode >= NodesPerLayer)
				throw new ArgumentOutOfRangeException(nameof(node.LocalNode));
		}
	}

	private sealed class LayerState
	{
		internal LayerState(int id, string name, bool isUnderground, int stack, int nodesPerLayer)
		{
			Id = id;
			Name = name;
			IsUnderground = isUnderground;
			Stack = stack;
			Terrain = new string[nodesPerLayer];
		}

		internal int Id { get; }
		internal string Name { get; }
		internal bool IsUnderground { get; }
		internal int Stack { get; }
		internal string[] Terrain { get; }
	}

	private readonly struct LayerNode : IEquatable<LayerNode>
	{
		internal LayerNode(int layer, int localNode)
		{
			Layer = layer;
			LocalNode = localNode;
		}

		internal int Layer { get; }
		internal int LocalNode { get; }

		public bool Equals(LayerNode other)
		{
			return Layer == other.Layer && LocalNode == other.LocalNode;
		}

		public override bool Equals(object obj)
		{
			return obj is LayerNode other && Equals(other);
		}

		public override int GetHashCode()
		{
			unchecked
			{
				return (Layer * 397) ^ LocalNode;
			}
		}
	}

	private readonly struct ProofReport
	{
		internal ProofReport(
			bool passed,
			int layers,
			int width,
			int height,
			int nodesPerLayer,
			int totalLayerNodes,
			int objectKeys,
			int eventKeys,
			int crossLayerEdges,
			int pathLength,
			bool sameLocalNodeDistinctObjects,
			bool sameLocalNodeDistinctEvents,
			bool pathCrossesLayer,
			string path,
			string failures)
		{
			Passed = passed;
			Layers = layers;
			Width = width;
			Height = height;
			NodesPerLayer = nodesPerLayer;
			TotalLayerNodes = totalLayerNodes;
			ObjectKeys = objectKeys;
			EventKeys = eventKeys;
			CrossLayerEdges = crossLayerEdges;
			PathLength = pathLength;
			SameLocalNodeDistinctObjects = sameLocalNodeDistinctObjects;
			SameLocalNodeDistinctEvents = sameLocalNodeDistinctEvents;
			PathCrossesLayer = pathCrossesLayer;
			Path = path;
			Failures = failures;
		}

		internal bool Passed { get; }
		internal int Layers { get; }
		internal int Width { get; }
		internal int Height { get; }
		internal int NodesPerLayer { get; }
		internal int TotalLayerNodes { get; }
		internal int ObjectKeys { get; }
		internal int EventKeys { get; }
		internal int CrossLayerEdges { get; }
		internal int PathLength { get; }
		internal bool SameLocalNodeDistinctObjects { get; }
		internal bool SameLocalNodeDistinctEvents { get; }
		internal bool PathCrossesLayer { get; }
		internal string Path { get; }
		internal string Failures { get; }
	}
}
