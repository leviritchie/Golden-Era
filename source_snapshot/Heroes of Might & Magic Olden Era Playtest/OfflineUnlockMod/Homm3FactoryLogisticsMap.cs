using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using Hex.Map;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network map adapter (lane CORE-B). Reads the live adventure map for the range solver
/// in <see cref="Homm3FactoryLogisticsRange"/>; it never mutates game state.
///
/// Sources (all names via GameSymbols):
/// - Map: session holder static <c>Map</c> (AdventureVisionLaws.SessionHolderTypeHints/StaticNames).
/// - Passability: the native <c>Hex.Map.Pathmap</c> (FactoryLogisticsMap.*). nodesBlocked already holds
///   every object's blocked footprint (ObjectNodesMaker, config node value 1) plus blocked cliffs; nodesGate
///   holds object entrances (value 2), which native ground pathing walks onto. No footprint decoding here.
/// - Terrain / roads / water: MapData tilesMap, roadsMap, waterMap (byte per node, node = x + z*sizeX).
/// - Fog: Data.Side(index).fogData.visibilityMap (native GroundPathfinder blocks !visibilityMap[node]).
/// - Neutral stacks: Data.squads.list (id, node, released). Guard zone = squad node + its 8 neighbours,
///   the exact native rule (WorldSquadsMap.Add uses GridUtils.GetNeighboursAll).
///
/// The surface and underground share one grid (Map views split it); neighbouring tiles across a view border
/// are not checked here (void tile code 23 is blocked). Portals/gates between levels are not traversed.
/// Proof tier: source/static; build target proven when the plugin compiles; runtime unproven.
/// </summary>
internal static class Homm3FactoryLogisticsMap
{
	internal const string LogPrefix = "[FactoryLogistics] range: ";

	internal const byte BlockNone = 0;
	internal const byte BlockObject = 1;   // pathmap nodesBlocked > 0 (object body or blocked cliff)
	internal const byte BlockWater = 2;    // MapData waterMap != 0
	internal const byte BlockVoid = 3;     // void terrain tile (outside the playable area)

	internal sealed class StaticGrid
	{
		public int W, H;
		public long MapKey;
		public byte[] Terrain;      // tilesMap
		public byte[] Road;         // roadsMap (0 = none)
		public byte[] Water;        // waterMap (0 = land)
		public byte[] Gate;         // 1 = object entrance (pathmap nodesGate > 0)
		public byte[] Block;        // Block* code per node
		public float[] RoadBonus;   // pathmap roadBonus (0..1)
		// Filled lazily by Homm3FactoryLogisticsRange (it owns the cost formula).
		public byte[] CostOrth, CostDiag;
		public int BlockedCount, GateCount, WaterCount, RoadCount;
	}

	internal struct SquadInfo
	{
		public long Key;
		public int Node;
	}

	private sealed class FogSnapshot
	{
		public bool[] Visible;
		public int Frame;
		public long MapKey;
	}

	private const BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private const BindingFlags StaticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	private static StaticGrid _grid;
	private static int _validatedFrame = -1;
	private static readonly Dictionary<int, FogSnapshot> _fog = new();
	private static readonly Dictionary<(Type, string[]), MemberInfo> _memberCache = new();
	private static string _lastGridFail;

	internal static void Invalidate()
	{
		_grid = null;
		_validatedFrame = -1;
		_fog.Clear();
	}

	internal static void LogInfo(string message) => Plugin.LogSource?.LogInfo(LogPrefix + message);
	internal static void LogWarning(string message) => Plugin.LogSource?.LogWarning(LogPrefix + message);
	internal static void LogError(string message) => Plugin.LogSource?.LogError(LogPrefix + message);

	/// <summary>Static grid of the current map; re-validates the map identity at most once per frame.</summary>
	internal static bool TryGetStaticGrid(out StaticGrid grid, out string fail)
	{
		fail = null;
		var frame = Time.frameCount;
		if (_grid != null && _validatedFrame == frame)
		{
			grid = _grid;
			return true;
		}
		grid = null;
		if (!TryResolveMap(out var map, out fail))
			return FailGrid(fail, out grid);
		if (!Homm3DirectStateIdentity.TryResolveKey(map, out var mapKey, out var keyFail) || mapKey == 0)
			return FailGrid("map identity unresolved: " + keyFail, out grid);
		if (_grid != null && _grid.MapKey == mapKey)
		{
			_validatedFrame = frame;
			grid = _grid;
			return true;
		}
		_fog.Clear();
		if (!TryBuildStaticGrid(map, mapKey, out var built, out fail))
			return FailGrid(fail, out grid);
		_grid = built;
		_validatedFrame = frame;
		_lastGridFail = null;
		grid = built;
		LogInfo("static grid built " + built.W.ToString(CultureInfo.InvariantCulture) + "x" + built.H.ToString(CultureInfo.InvariantCulture)
			+ " blocked=" + built.BlockedCount.ToString(CultureInfo.InvariantCulture)
			+ " gates=" + built.GateCount.ToString(CultureInfo.InvariantCulture)
			+ " water=" + built.WaterCount.ToString(CultureInfo.InvariantCulture)
			+ " road=" + built.RoadCount.ToString(CultureInfo.InvariantCulture) + ".");
		return true;
	}

	/// <summary>Static MapData of the current map (objects, squads and tile maps as authored/generated).</summary>
	internal static bool TryGetMapData(out Hex.Map.MapData mapData, out string fail)
	{
		mapData = null;
		if (!TryResolveMap(out var map, out fail))
			return false;
		mapData = ReadMember(map, GameSymbols.HomecomingBoatTravel.MapData.NameHints) as Hex.Map.MapData;
		if (mapData != null)
			return true;
		fail = "Map.data unresolved";
		return false;
	}

	private static bool FailGrid(string fail, out StaticGrid grid)
	{
		grid = null;
		_grid = null;
		_validatedFrame = -1;
		if (!string.Equals(fail, _lastGridFail, StringComparison.Ordinal))
		{
			_lastGridFail = fail;
			LogError("map unavailable (fail-closed): " + fail);
		}
		return false;
	}

	private static bool TryResolveMap(out object map, out string fail)
	{
		map = null;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			if (string.IsNullOrWhiteSpace(typeName))
				continue;
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;
			try { RuntimeHelpers.RunClassConstructor(type.TypeHandle); }
			catch { /* Il2Cpp static init is best-effort; the member read decides. */ }
			foreach (var name in GameSymbols.AdventureVisionLaws.SessionHolderStaticNames)
			{
				if (!TryReadStatic(type, name, out var value) || value == null)
					continue;
				if (value is Map)
				{
					map = value;
					fail = null;
					return true;
				}
			}
		}
		map = Homm3FactoryLogisticsAdventureView.TryWorldCameraMap();
		if (map != null)
		{
			fail = null;
			return true;
		}
		fail = "session holder static Map and world camera map unresolved (not on an adventure map?)";
		return false;
	}

	private static bool TryBuildStaticGrid(object map, long mapKey, out StaticGrid grid, out string fail)
	{
		grid = null;
		var pathmap = ReadMember(map, GameSymbols.FactoryLogisticsMap.MapPathmapMembers);
		if (pathmap == null)
		{
			fail = "Map.pathmap unresolved on " + map.GetType().FullName;
			return false;
		}
		if (!TryReadInt(pathmap, GameSymbols.FactoryLogisticsMap.PathmapSizeXMembers, out var w)
			|| !TryReadInt(pathmap, GameSymbols.FactoryLogisticsMap.PathmapSizeZMembers, out var h))
		{
			fail = "Pathmap sizeX/sizeZ unresolved";
			return false;
		}
		if (w <= 0 || h <= 0 || (long)w * h > GameSymbols.AdventureAiDecision.MaxLiveMapCells * 4L)
		{
			fail = "Pathmap size out of range " + w + "x" + h;
			return false;
		}
		var n = w * h;
		var mapData = ReadMember(map, GameSymbols.HomecomingBoatTravel.MapData.NameHints);
		if (mapData == null)
		{
			fail = "Map.data unresolved";
			return false;
		}
		if (TryReadInt(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeXMembers, out var dataW)
			&& TryReadInt(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeZMembers, out var dataH)
			&& (dataW != w || dataH != h))
		{
			fail = "Pathmap size " + w + "x" + h + " differs from MapData " + dataW + "x" + dataH;
			return false;
		}
		if (!TryReadBytes(pathmap, GameSymbols.FactoryLogisticsMap.PathmapNodesBlockedMembers, n, "Pathmap.nodesBlocked", out var blocked, out fail)
			|| !TryReadBytes(pathmap, GameSymbols.FactoryLogisticsMap.PathmapNodesGateMembers, n, "Pathmap.nodesGate", out var gates, out fail)
			|| !TryReadFloats(pathmap, GameSymbols.FactoryLogisticsMap.PathmapRoadBonusMembers, n, "Pathmap.roadBonus", out var roadBonus, out fail)
			|| !TryReadBytes(mapData, GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers, n, "MapData.tilesMap", out var terrain, out fail)
			|| !TryReadBytes(mapData, GameSymbols.AdventureAiDecision.LiveMapRoadsMembers, n, "MapData.roadsMap", out var roads, out fail)
			|| !TryReadBytes(mapData, GameSymbols.HomecomingBoatTravel.MapDataWaterMapMembers, n, "MapData.waterMap", out var water, out fail))
			return false;

		var g = new StaticGrid
		{
			W = w, H = h, MapKey = mapKey,
			Terrain = terrain, Road = roads, Water = water, RoadBonus = roadBonus,
			Gate = new byte[n], Block = new byte[n],
		};
		var objectBlocked = 0;
		for (var i = 0; i < n; i++)
		{
			if (gates[i] > 0)
			{
				g.Gate[i] = 1;
				g.GateCount++;
			}
			if (roads[i] != 0)
				g.RoadCount++;
			if (blocked[i] > 0)
			{
				g.Block[i] = BlockObject;
				objectBlocked++;
			}
			else if (water[i] != 0)
			{
				g.Block[i] = BlockWater;
				g.WaterCount++;
			}
			else if (terrain[i] == GameSymbols.AdventureAiDecision.LiveMapVoidTerrainTileCode)
				g.Block[i] = BlockVoid;
			if (g.Block[i] != BlockNone)
				g.BlockedCount++;
			var rb = roadBonus[i];
			if (float.IsNaN(rb) || rb < 0f || rb > 1f)
			{
				fail = "Pathmap.roadBonus out of range at node " + i + ": " + rb.ToString(CultureInfo.InvariantCulture);
				return false;
			}
		}
		// Field-order pin check: nodesBlocked (bodies + cliffs) must outnumber nodesGate (entrances) on any
		// real map. If the two backing fields were swapped the solver would walk through object bodies.
		if (g.GateCount > 0 && objectBlocked < g.GateCount)
		{
			fail = "Pathmap sanity: blocked nodes (" + objectBlocked + ") < gate nodes (" + g.GateCount
				+ "); nodesBlocked/nodesGate pins look swapped";
			return false;
		}
		grid = g;
		fail = null;
		return true;
	}

	/// <summary>Visibility (explored) map for a side, re-read at most once per frame.</summary>
	internal static bool TryGetFogVisible(int sideId, StaticGrid grid, out bool[] visible, out string fail)
	{
		visible = null;
		fail = null;
		if (grid == null)
		{
			fail = "grid null";
			return false;
		}
		var frame = Time.frameCount;
		if (_fog.TryGetValue(sideId, out var snap) && snap.Frame == frame && snap.MapKey == grid.MapKey)
		{
			visible = snap.Visible;
			return true;
		}
		if (!Homm3BattleUnitLawOwnerRegistry.TryResolveGlobalDataSide(sideId, out var dataSide, out var sideFail) || dataSide == null)
		{
			fail = "Data.Side " + sideId + " unresolved: " + sideFail;
			return false;
		}
		var fog = ReadMember(dataSide, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
		if (fog == null)
		{
			fail = "Side.fogData unresolved for side " + sideId;
			return false;
		}
		var raw = ReadMember(fog, GameSymbols.AdventureVisionLaws.DataFogVisibilityMapMembers);
		var n = grid.W * grid.H;
		var buffer = snap != null && snap.Visible != null && snap.Visible.Length == n ? snap.Visible : new bool[n];
		if (raw is Il2CppStructArray<bool> il2cpp)
		{
			if (il2cpp.Length != n)
			{
				fail = "fog visibilityMap length " + il2cpp.Length + " != " + n;
				return false;
			}
			var tmp = new byte[n];
			if (!TryBulkCopy(il2cpp.Pointer, n, tmp, out fail))
				return false;
			for (var i = 0; i < n; i++)
				buffer[i] = tmp[i] != 0;
			if (buffer[0] != il2cpp[0] || buffer[n - 1] != il2cpp[n - 1])
			{
				fail = "fog visibilityMap bulk copy disagrees with indexer (array header offset?)";
				return false;
			}
		}
		else if (raw is bool[] managed)
		{
			if (managed.Length != n)
			{
				fail = "fog visibilityMap length " + managed.Length + " != " + n;
				return false;
			}
			Array.Copy(managed, buffer, n);
		}
		else
		{
			fail = "fog visibilityMap unresolved (" + (raw?.GetType().FullName ?? "null") + ")";
			return false;
		}
		_fog[sideId] = new FogSnapshot { Visible = buffer, Frame = frame, MapKey = grid.MapKey };
		visible = buffer;
		return true;
	}

	/// <summary>Live neutral stacks (Data.squads.list, not released). Every live squad has a native guard zone.</summary>
	internal static bool TryGetSquads(StaticGrid grid, List<SquadInfo> into, out string fail)
	{
		into.Clear();
		fail = null;
		if (!TryResolveSessionData(out var data))
		{
			fail = "session Data root unresolved";
			return false;
		}
		var container = ReadMember(data, GameSymbols.AdventureAiDecision.DataRootSquadsMembers);
		if (container == null)
		{
			fail = "Data.squads unresolved";
			return false;
		}
		var list = ReadMember(container, GameSymbols.AdventureAiDecision.DataSquadsAllMembers) ?? container;
		var n = grid.W * grid.H;
		var rows = 0;
		var unreadable = 0;
		foreach (var row in EnumerateList(list))
		{
			rows++;
			if (!TryReadInt(row, GameSymbols.AdventureAiDecision.DataSquadIdFieldHints, out var id)
				|| !TryReadInt(row, GameSymbols.AdventureAiDecision.DataSquadNodeFieldHints, out var node))
			{
				unreadable++;
				continue;
			}
			if (TryReadBool(row, GameSymbols.AdventureAiDecision.DataSquadReleasedFieldHints, out var released) && released)
				continue;
			if (node < 0 || node >= n)
				continue;
			into.Add(new SquadInfo { Key = id, Node = node });
		}
		if (rows > 0 && unreadable == rows)
		{
			fail = "Data.squads rows unreadable (" + rows + " rows, id/node pins missed)";
			return false;
		}
		if (unreadable > 0)
			LogWarning("squads: " + unreadable + "/" + rows + " rows unreadable (id/node), skipped.");
		return true;
	}

	private static bool TryResolveSessionData(out object data)
	{
		data = null;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			if (string.IsNullOrWhiteSpace(typeName))
				continue;
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;
			foreach (var name in GameSymbols.AdventureVisionLaws.SessionDataMembers)
			{
				if (TryReadStatic(type, name, out var value) && value != null)
				{
					data = value;
					return true;
				}
			}
		}
		// Same fallback as the map: the holder statics can be null while the logic root still carries Data.
		if (Homm3FactoryLogisticsEffects.TryGetData(out var root, out _) && root != null)
		{
			data = root;
			return true;
		}
		return false;
	}

	// ---- reflection helpers (names come only from GameSymbols arrays) ----

	private static object ReadMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		var key = (type, names);
		if (!_memberCache.TryGetValue(key, out var member))
		{
			member = FindMember(type, names);
			_memberCache[key] = member;
		}
		if (member == null)
			return null;
		try
		{
			switch (member)
			{
				case PropertyInfo p: return p.GetValue(obj, null);
				case FieldInfo f: return f.GetValue(obj);
				case MethodInfo m: return m.Invoke(obj, null);
			}
		}
		catch (Exception ex)
		{
			LogWarning("member read " + type.Name + "." + member.Name + " threw " + ex.GetBaseException().GetType().Name);
		}
		return null;
	}

	private static MemberInfo FindMember(Type type, string[] names)
	{
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			for (var t = type; t != null; t = t.BaseType)
			{
				try
				{
					var p = t.GetProperty(name, InstanceFlags | BindingFlags.DeclaredOnly);
					if (p != null && p.CanRead && p.GetIndexParameters().Length == 0)
						return p;
					var f = t.GetField(name, InstanceFlags | BindingFlags.DeclaredOnly);
					if (f != null)
						return f;
					var m = t.GetMethod(name, InstanceFlags | BindingFlags.DeclaredOnly, null, Type.EmptyTypes, null);
					if (m != null && m.ReturnType != typeof(void))
						return m;
				}
				catch (AmbiguousMatchException)
				{
					// keep searching the next hint
				}
			}
		}
		return null;
	}

	private static bool TryReadStatic(Type type, string name, out object value)
	{
		value = null;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		try
		{
			var property = type.GetProperty(name, StaticFlags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				value = property.GetValue(null);
				return true;
			}
			var field = type.GetField(name, StaticFlags);
			if (field != null)
			{
				value = field.GetValue(null);
				return true;
			}
			var method = type.GetMethod(name, StaticFlags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void))
			{
				value = method.Invoke(null, null);
				return true;
			}
		}
		catch (Exception)
		{
			value = null;
		}
		return false;
	}

	private static bool TryReadInt(object obj, string[] names, out int value)
	{
		value = 0;
		var raw = ReadMember(obj, names);
		if (raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadBool(object obj, string[] names, out bool value)
	{
		value = false;
		var raw = ReadMember(obj, names);
		if (raw is bool b)
		{
			value = b;
			return true;
		}
		return false;
	}

	/// <summary>IL2CPP array header: klass, monitor, bounds, max_length (Il2CppInterop's ArrayStartPointer offset).</summary>
	private static readonly int Il2CppArrayDataOffset = IntPtr.Size * 4;

	/// <summary>Bulk copy of a native IL2CPP byte/bool array (Il2CppStructArray.AsSpan needs System.Runtime 6 and breaks the netstandard2.1 build).</summary>
	private static bool TryBulkCopy(IntPtr array, int count, byte[] into, out string fail)
	{
		fail = null;
		if (array == IntPtr.Zero)
		{
			fail = "native array pointer is null";
			return false;
		}
		if (count > 0)
			System.Runtime.InteropServices.Marshal.Copy(array + Il2CppArrayDataOffset, into, 0, count);
		return true;
	}

	private static bool TryReadBytes(object owner, string[] names, int expected, string label, out byte[] values, out string fail)
	{
		values = null;
		fail = null;
		var raw = ReadMember(owner, names);
		if (raw is Il2CppStructArray<byte> il2cpp)
		{
			if (il2cpp.Length != expected)
			{
				fail = label + " length " + il2cpp.Length + " != " + expected;
				return false;
			}
			values = new byte[expected];
			if (!TryBulkCopy(il2cpp.Pointer, expected, values, out fail))
				return false;
			if (expected > 0 && (values[0] != il2cpp[0] || values[expected - 1] != il2cpp[expected - 1]))
			{
				fail = label + " bulk copy disagrees with indexer (array header offset?)";
				return false;
			}
			return true;
		}
		if (raw is byte[] managed)
		{
			if (managed.Length != expected)
			{
				fail = label + " length " + managed.Length + " != " + expected;
				return false;
			}
			values = (byte[])managed.Clone();
			return true;
		}
		fail = label + " unresolved (" + (raw?.GetType().FullName ?? "null") + ")";
		return false;
	}

	private static bool TryReadFloats(object owner, string[] names, int expected, string label, out float[] values, out string fail)
	{
		values = null;
		fail = null;
		var raw = ReadMember(owner, names);
		if (raw is Il2CppStructArray<float> il2cpp)
		{
			if (il2cpp.Length != expected)
			{
				fail = label + " length " + il2cpp.Length + " != " + expected;
				return false;
			}
			values = new float[expected];
			if (il2cpp.Pointer == IntPtr.Zero)
			{
				fail = label + " native array pointer is null";
				return false;
			}
			if (expected > 0)
				System.Runtime.InteropServices.Marshal.Copy(il2cpp.Pointer + Il2CppArrayDataOffset, values, 0, expected);
			if (expected > 0 && (!values[0].Equals(il2cpp[0]) || !values[expected - 1].Equals(il2cpp[expected - 1])))
			{
				fail = label + " bulk copy disagrees with indexer (array header offset?)";
				return false;
			}
			return true;
		}
		if (raw is float[] managed)
		{
			if (managed.Length != expected)
			{
				fail = label + " length " + managed.Length + " != " + expected;
				return false;
			}
			values = (float[])managed.Clone();
			return true;
		}
		fail = label + " unresolved (" + (raw?.GetType().FullName ?? "null") + ")";
		return false;
	}

	private static IEnumerable<object> EnumerateList(object listObj)
	{
		if (listObj == null)
			yield break;
		var type = listObj.GetType();
		PropertyInfo countProp = null;
		MethodInfo itemGetter = null;
		for (var t = type; t != null && countProp == null; t = t.BaseType)
		{
			try { countProp = t.GetProperty("Count", InstanceFlags | BindingFlags.DeclaredOnly); }
			catch (AmbiguousMatchException) { countProp = null; }
		}
		for (var t = type; t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", InstanceFlags | BindingFlags.DeclaredOnly, null, new[] { typeof(int) }, null); }
			catch (AmbiguousMatchException) { itemGetter = null; }
		}
		if (countProp == null || itemGetter == null)
		{
			if (listObj is IEnumerable enumerable)
			{
				foreach (var item in enumerable)
					if (item != null)
						yield return item;
			}
			yield break;
		}
		int count;
		try { count = Convert.ToInt32(countProp.GetValue(listObj), CultureInfo.InvariantCulture); }
		catch { yield break; }
		for (var i = 0; i < count; i++)
		{
			object item;
			try { item = itemGetter.Invoke(listObj, new object[] { i }); }
			catch { continue; }
			if (item != null)
				yield return item;
		}
	}
}
