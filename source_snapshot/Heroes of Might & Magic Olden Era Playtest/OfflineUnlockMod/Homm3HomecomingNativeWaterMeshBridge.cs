using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Map;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Rebuilds native animated water mesh chunks on Homecoming maps by routing ocean
/// <c>MapData.waterMap</c> bytes through the verified native <c>Map.ohl(node, waterId)</c>
/// setter, which marks touched bws chunks dirty with <c>RebuildFlags.Mesh</c>.
/// </summary>
internal static class Homm3HomecomingNativeWaterMeshBridge
{
	internal const string ActiveArchitecture = "native_watermap_mesh_via_verified_map_ohl_deferred_once_force_toggle";
	private const string LogPrefix = "HOMM3_HOMECOMING_NATIVE_WATER_MESH";
	private const string HostName = "Homm3HomecomingNativeWaterMeshHost";
	private const int ApplyDeferFrames = 3;

	private static bool _registered;
	private static bool _registeredHostType;
	private static ManualLogSource _log;
	private static MethodInfo _verifiedSetWaterNodeMethod;
	private static int _loggedApplied;
	private static int _loggedSkipped;
	private static int _loggedFailed;
	private static readonly HashSet<long> _completedScopeKeys = new();
	private static readonly HashSet<long> _pendingScopeKeys = new();
	private static readonly Queue<PendingApply> _pendingApplies = new();
	[ThreadStatic] private static bool _applyInProgress;

	private sealed class PendingApply
	{
		internal long ScopeKey;
		internal Map Map;
		internal object TerrainRenderer;
		internal string Source;
		internal int FramesRemaining;
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Homecoming native water mesh registration.");

		_log = log;
		EnsureHost();
		_registered = true;
		log?.LogInfo(LogPrefix + " registered native waterMap mesh rebuild architecture=" + ActiveArchitecture + ".");
	}

	internal static void ResetCompletedScopesForMapScopeChange(string source)
	{
		if (_completedScopeKeys.Count == 0 && _pendingScopeKeys.Count == 0 && _pendingApplies.Count == 0)
			return;
		_completedScopeKeys.Clear();
		_pendingScopeKeys.Clear();
		_pendingApplies.Clear();
		_verifiedSetWaterNodeMethod = null;
		_log?.LogInfo(LogPrefix + " cleared deferred mesh scope state source=" + (source ?? "?") + ".");
	}

	internal static void TryScheduleForMap(Map map, object terrainRenderer, string source)
	{
		if (!_registered || map == null)
			return;
		if (!TryGetScopeKey(map, out var scopeKey))
			return;
		if (_completedScopeKeys.Contains(scopeKey) || _pendingScopeKeys.Contains(scopeKey))
			return;

		_pendingScopeKeys.Add(scopeKey);
		_pendingApplies.Enqueue(new PendingApply
		{
			ScopeKey = scopeKey,
			Map = map,
			TerrainRenderer = terrainRenderer,
			Source = source,
			FramesRemaining = ApplyDeferFrames,
		});
	}

	internal static void DrainPending()
	{
		if (_pendingApplies.Count == 0)
			return;
		var batch = new List<PendingApply>();
		while (_pendingApplies.Count > 0)
			batch.Add(_pendingApplies.Dequeue());

		foreach (var pending in batch)
		{
			if (pending.FramesRemaining > 0)
			{
				pending.FramesRemaining--;
				_pendingApplies.Enqueue(pending);
				continue;
			}

			_pendingScopeKeys.Remove(pending.ScopeKey);
			if (pending.Map == null || _completedScopeKeys.Contains(pending.ScopeKey))
				continue;
			if (TryApplyForMapNow(pending.Map, pending.TerrainRenderer, pending.Source))
				_completedScopeKeys.Add(pending.ScopeKey);
		}
	}

	private static bool TryApplyForMapNow(Map map, object terrainRenderer, string source)
	{
		if (!_registered || map == null || _applyInProgress)
			return false;

		_applyInProgress = true;
		try
		{
			if (!TryGetMapData(map, out var mapData))
			{
				LogSkip(source, "map_data_unresolved");
				return false;
			}

			var fileMapName = ReadMapDataString(mapData, 0);
			if (!HomecomingMapProfile.TryResolve(fileMapName, mapData, out var profile))
				return false;

			if (!TryReadByteArray(mapData, GameSymbols.HomecomingBoatTravel.MapDataWaterMapMembers, out var waterMap, out var waterReason))
			{
				LogSkip(source, "waterMap_read_failed " + waterReason);
				return false;
			}
			if (!TryReadByteArray(mapData, GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers, out var tilesMap, out var tilesReason))
			{
				LogSkip(source, "tilesMap_read_failed " + tilesReason);
				return false;
			}
			if (!TryReadLevelArray(mapData, out var levelsMap, out var levelsReason))
			{
				LogSkip(source, "levelsMap_read_failed " + levelsReason);
				return false;
			}

			if (!TryReadMapDimensions(mapData, out var width, out var height, out var dimensionReason))
			{
				LogSkip(source, "map_dimensions_unresolved " + dimensionReason);
				return false;
			}

			var cellCount = width * height;
			if (cellCount <= 0 || waterMap.Length < cellCount || tilesMap.Length < cellCount || levelsMap.Length < cellCount)
			{
				LogSkip(source, "map_array_length_mismatch");
				return false;
			}

			var setWater = ResolveVerifiedSetWaterNodeMethod(map, mapData, waterMap, tilesMap, levelsMap, cellCount, profile, source);
			if (setWater == null)
			{
				LogSkip(source, "verified_water_setter_unresolved");
				return false;
			}

			var painted = 0;
			var failed = 0;
			for (var node = 0; node < cellCount; node++)
			{
				if (!profile.ContainsRuntimeWaterNode(node))
					continue;
				if (!GameSymbols.HomecomingBoatTravel.IsOceanCell(tilesMap[node], waterMap[node], levelsMap[node]))
					continue;
				var waterId = waterMap[node];
				if (waterId == 0)
					continue;
				try
				{
					ForceRefreshWaterNode(setWater, map, node, waterId);
					painted++;
				}
				catch (Exception ex)
				{
					failed++;
					if (_loggedFailed < 8)
					{
						_loggedFailed++;
						_log?.LogWarning(
							LogPrefix
							+ " setWater_failed map="
							+ (fileMapName ?? "?")
							+ " node="
							+ node.ToString(CultureInfo.InvariantCulture)
							+ " waterId="
							+ waterId.ToString(CultureInfo.InvariantCulture)
							+ " source="
							+ (source ?? "?")
							+ " error="
							+ ex.GetType().Name
							+ ": "
							+ ex.Message);
					}
				}
			}

			if (painted <= 0)
			{
				LogSkip(source, "no_native_water_terrain_cells_with_waterMap map=" + (fileMapName ?? "?"));
				return false;
			}

			if (_loggedApplied < 12)
			{
				_loggedApplied++;
				_log?.LogWarning(
					LogPrefix
					+ " mesh_rebuild_applied map="
					+ (fileMapName ?? "?")
					+ " profile="
					+ profile.Id
					+ " painted="
					+ painted.ToString(CultureInfo.InvariantCulture)
					+ " failed="
					+ failed.ToString(CultureInfo.InvariantCulture)
					+ " source="
					+ (source ?? "?")
					+ " setter="
					+ setWater.Name
					+ " architecture="
					+ ActiveArchitecture
					+ ".");
			}
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedFailed < 12)
			{
				_loggedFailed++;
				_log?.LogWarning(
					LogPrefix
					+ " apply_failed source="
					+ (source ?? "?")
					+ " error="
					+ ex.GetType().Name
					+ ": "
					+ ex.Message);
			}
			return false;
		}
		finally
		{
			_applyInProgress = false;
		}
	}

	// Map.ohl only marks bws chunks dirty when waterMap changes; Homecoming maps already
	// serialize the ocean waterMap id on ocean cells, so a same-value write is a no-op for mesh rebuild.
	private static void ForceRefreshWaterNode(MethodInfo setWater, Map map, int node, byte waterId)
	{
		setWater.Invoke(map, new object[] { node, (byte)0 });
		setWater.Invoke(map, new object[] { node, waterId });
	}

	private static MethodInfo ResolveVerifiedSetWaterNodeMethod(
		Map map,
		object mapData,
		byte[] waterMap,
		byte[] tilesMap,
		sbyte[] levelsMap,
		int cellCount,
		HomecomingMapProfile profile,
		string source)
	{
		if (_verifiedSetWaterNodeMethod != null)
			return _verifiedSetWaterNodeMethod;

		var testNode = -1;
		byte testWaterId = 0;
		for (var node = 0; node < cellCount; node++)
		{
			if (!profile.ContainsRuntimeWaterNode(node))
				continue;
			if (!GameSymbols.HomecomingBoatTravel.IsOceanCell(tilesMap[node], waterMap[node], levelsMap[node]))
				continue;
			testNode = node;
			testWaterId = waterMap[node];
			break;
		}
		if (testNode < 0)
			return null;

		var liveWaterMap = TryReadFirstMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataWaterMapMembers);
		if (liveWaterMap == null)
			return null;

		_verifiedSetWaterNodeMethod = IdentifyWaterSetter(map, mapData, liveWaterMap, testNode, testWaterId, source);
		return _verifiedSetWaterNodeMethod;
	}

	private static MethodInfo IdentifyWaterSetter(
		Map map,
		object mapData,
		object liveWaterMap,
		int testNode,
		byte expectedWaterId,
		string source)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var byteArrayMemberNames = new[]
		{
			"tilesMap", "tilesMap_",
			"levelsMap", "levelsMap_",
			"waterMap", "waterMap_",
			"roadsMap", "roadsMap_",
			"decorationsMap", "decorationsMap_",
			"cliffsMap", "cliffsMap_",
		};
		var byteArrays = new List<(string Name, object Array)>();
		foreach (var name in byteArrayMemberNames)
		{
			var value = TryReadMember(mapData, name);
			if (value != null && TryGetArrayLength(value) > testNode)
				byteArrays.Add((name, value));
		}

		var candidates = map.GetType()
			.GetMethods(flags)
			.Where(method => method.ReturnType == typeof(void))
			.Where(method =>
			{
				var parameters = method.GetParameters();
				return parameters.Length == 2
				       && parameters[0].ParameterType == typeof(int)
				       && parameters[1].ParameterType == typeof(byte);
			})
			.ToList();
		if (candidates.Count == 0)
			throw new InvalidOperationException(LogPrefix + " no void(int, byte) methods exist on live Map.");

		// Probe ids are always in-catalog: water ids 1 ("water dirt") and 2 ("water sand") exist in
		// the Golden Era and Steam 25509697 DB/map/waters/waters.json, so the 1/2 alternate-value
		// probe below never writes an invalid id.
		var waterBefore = ReadArrayByte(liveWaterMap, testNode);
		var probeValue = waterBefore == expectedWaterId
			? (byte)(expectedWaterId == 1 ? 2 : 1)
			: expectedWaterId;
		foreach (var candidate in candidates)
		{
			var before = byteArrays.Select(entry => ReadArrayByte(entry.Array, testNode)).ToArray();
			try
			{
				candidate.Invoke(map, new object[] { testNode, probeValue });
			}
			catch
			{
				continue;
			}

			var waterAfter = ReadArrayByte(liveWaterMap, testNode);
			if (waterAfter == probeValue)
			{
				candidate.Invoke(map, new object[] { testNode, (byte)waterBefore });
				_log?.LogWarning(
					LogPrefix
					+ " verified_water_setter="
					+ candidate.Name
					+ " source="
					+ (source ?? "?")
					+ " testNode="
					+ testNode.ToString(CultureInfo.InvariantCulture)
					+ ".");
				return candidate;
			}

			for (var i = 0; i < byteArrays.Count; i++)
			{
				var after = ReadArrayByte(byteArrays[i].Array, testNode);
				if (after != before[i])
					candidate.Invoke(map, new object[] { testNode, (byte)before[i] });
			}
		}

		throw new InvalidOperationException(
			LogPrefix
			+ " could not verify Map water setter among void(int, byte) candidates ["
			+ string.Join(", ", candidates.Select(candidate => candidate.Name))
			+ "] source="
			+ (source ?? "?")
			+ ".");
	}

	private static int TryGetArrayLength(object arrayLike)
	{
		if (arrayLike == null)
			return 0;
		if (arrayLike is Array array)
			return array.Length;
		if (arrayLike is Il2CppArrayBase il2CppArray)
			return il2CppArray.Length;
		try
		{
			var lengthProperty = arrayLike.GetType().GetProperty("Length", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                     ?? arrayLike.GetType().GetProperty("Count", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return lengthProperty == null ? 0 : Convert.ToInt32(lengthProperty.GetValue(arrayLike), CultureInfo.InvariantCulture);
		}
		catch
		{
			return 0;
		}
	}

	private static int ReadArrayByte(object arrayLike, int index)
	{
		if (arrayLike == null || index < 0)
			return -1;
		try
		{
			if (arrayLike is byte[] bytes)
				return index < bytes.Length ? bytes[index] : -1;
			if (arrayLike is Il2CppStructArray<byte> il2CppBytes)
				return index < il2CppBytes.Length ? il2CppBytes[index] : -1;
			if (arrayLike is Array array)
				return index < array.Length ? Convert.ToInt32(array.GetValue(index), CultureInfo.InvariantCulture) : -1;
		}
		catch
		{
			return -1;
		}
		return -1;
	}

	private static void EnsureHost()
	{
		if (Homm3HomecomingNativeWaterMeshHost.Attached)
			return;
		if (!_registeredHostType)
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3HomecomingNativeWaterMeshHost>();
			_registeredHostType = true;
		}
		var go = new GameObject(HostName);
		go.hideFlags = HideFlags.HideAndDontSave;
		if (go.AddComponent<Homm3HomecomingNativeWaterMeshHost>() == null)
			throw new InvalidOperationException(LogPrefix + " host component registration failed.");
		UnityEngine.Object.DontDestroyOnLoad(go);
		Homm3HomecomingNativeWaterMeshHost.Attached = true;
	}

	private static bool TryGetScopeKey(Map map, out long scopeKey)
	{
		scopeKey = 0;
		if (map is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			scopeKey = il2Cpp.Pointer.ToInt64();
			return true;
		}
		return false;
	}

	private static void LogSkip(string source, string reason)
	{
		if (_loggedSkipped >= 12)
			return;
		_loggedSkipped++;
		_log?.LogInfo(LogPrefix + " mesh_rebuild_skip source=" + (source ?? "?") + " reason=" + reason + ".");
	}

	private static bool TryGetMapData(Map map, out object mapData)
	{
		mapData = null;
		if (map == null)
			return false;
		var direct = InvokeFirstNoArg(map, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData);
		if (direct is MapData typed)
		{
			mapData = typed;
			return true;
		}
		if (direct != null)
		{
			mapData = direct;
			return true;
		}
		return false;
	}

	private static string ReadMapDataString(object value, int depth)
	{
		if (value == null || depth > 4)
			return null;
		foreach (var name in GameSymbols.HomecomingBoatTravel.MapDataFileNameMembers)
		{
			var direct = TryReadMember(value, name) as string;
			if (!string.IsNullOrWhiteSpace(direct))
				return direct;
		}
		if (value is Map map && TryGetMapData(map, out var mapData) && mapData != null)
		{
			var fromMapData = ReadMapDataString(mapData, depth + 1);
			if (!string.IsNullOrWhiteSpace(fromMapData))
				return fromMapData;
		}
		return null;
	}

	private static bool TryReadMapDimensions(object mapData, out int width, out int height, out string reason)
	{
		width = 0;
		height = 0;
		reason = null;
		if (!TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeXMembers, out width, out reason))
			return false;
		if (!TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeZMembers, out height, out reason))
			return false;
		return true;
	}

	private static bool TryReadLevelArray(object mapData, out sbyte[] values, out string reason)
	{
		values = null;
		reason = null;
		var raw = TryReadFirstMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataLevelsMapMembers);
		if (raw == null)
		{
			reason = "member_missing";
			return false;
		}
		if (raw is sbyte[] signedBytes)
		{
			values = signedBytes;
			return true;
		}
		if (raw is Il2CppStructArray<sbyte> il2CppSignedBytes)
		{
			values = new sbyte[il2CppSignedBytes.Length];
			for (var i = 0; i < il2CppSignedBytes.Length; i++)
				values[i] = il2CppSignedBytes[i];
			return true;
		}
		reason = "unsupported_type " + raw.GetType().FullName;
		return false;
	}

	private static bool TryReadByteArray(object mapData, string[] memberNames, out byte[] values, out string reason)
	{
		values = null;
		reason = null;
		var raw = TryReadFirstMember(mapData, memberNames);
		if (raw == null)
		{
			reason = "member_missing";
			return false;
		}
		if (raw is byte[] bytes)
		{
			values = bytes;
			return true;
		}
		if (raw is Il2CppStructArray<byte> il2CppBytes)
		{
			values = new byte[il2CppBytes.Length];
			for (var i = 0; i < il2CppBytes.Length; i++)
				values[i] = il2CppBytes[i];
			return true;
		}
		if (raw is Array array)
		{
			values = new byte[array.Length];
			for (var i = 0; i < array.Length; i++)
				values[i] = Convert.ToByte(array.GetValue(i), CultureInfo.InvariantCulture);
			return true;
		}
		reason = "unsupported_type " + raw.GetType().FullName;
		return false;
	}

	private static object InvokeFirstNoArg(object obj, Type expectedReturnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null || expectedReturnType == null || symbol.NameHints == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo method;
				try { method = type.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null || !expectedReturnType.IsAssignableFrom(method.ReturnType))
					continue;
				try { return method.Invoke(obj, null); }
				catch { return null; }
			}
		}
		return null;
	}

	private static object TryReadFirstMember(object value, string[] memberNames)
	{
		if (value == null || memberNames == null)
			return null;
		foreach (var name in memberNames)
		{
			var member = TryReadMember(value, name);
			if (member != null)
				return member;
		}
		return null;
	}

	private static object TryReadMember(object value, string name)
	{
		if (value == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = value.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var property = type.GetProperty(name, flags);
			if (property != null)
				return property.GetValue(value);
		}
		catch { }
		try
		{
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(value);
		}
		catch { }
		return null;
	}

	private static bool TryReadPositiveIntMember(object value, string[] memberNames, out int result, out string reason)
	{
		result = 0;
		reason = null;
		var raw = TryReadFirstMember(value, memberNames);
		if (raw == null)
		{
			reason = "member_missing";
			return false;
		}
		try
		{
			result = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			if (result <= 0)
			{
				reason = "non_positive_value";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "convert_failed " + ex.Message;
			return false;
		}
	}
}

/// <summary>Must be public for Il2CppInterop ClassInjector registration.</summary>
public sealed class Homm3HomecomingNativeWaterMeshHost : MonoBehaviour
{
	internal static bool Attached;

	private void LateUpdate()
	{
		Homm3HomecomingNativeWaterMeshBridge.DrainPending();
	}
}
