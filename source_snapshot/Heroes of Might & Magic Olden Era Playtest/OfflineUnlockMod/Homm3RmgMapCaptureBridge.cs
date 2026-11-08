using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Map;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic capture of a live RMG-generated Map into a gzip .map container under
/// artifacts/rmg_capture/. Gated by flag file; does not mutate gameplay state.
/// Map.Init only arms a deferred host: RMG fills MapData after Init returns.
/// Preferred path: ql.Save() after Map.ogz(). Fallback: JsonUtility.ToJson(MapData).
/// Runtime capture→reload remains unvalidated until in-game proof.
/// </summary>
internal static class Homm3RmgMapCaptureBridge
{
	internal const string DiagnosticFlag = "homm3_rmg_map_capture.flag";
	private const string LogPrefix = "HOMM3_RMG_MAP_CAPTURE";
	private const string DefaultCaptureSid = "h3_rmg_capture";
	private const string CaptureRelativeDir = "artifacts/rmg_capture";
	private const string HostName = "Homm3RmgMapCaptureHost";
	private const float CaptureTimeoutSeconds = 120f;
	private const float PollIntervalSeconds = 0.5f;

	private static bool _registered;
	private static bool _registeredHostType;
	private static bool _captureCompleted;
	private static bool _pending;
	private static Map _pendingMap;
	private static float _pendingSinceRealtime = -1f;
	private static float _nextPollRealtime;
	private static int _pollCount;
	private static ManualLogSource _log;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;

		_log = log;
		try
		{
			var mapInit = FindMapInitMethod();
			if (mapInit == null)
				throw new InvalidOperationException("Map.Init surface was not resolved.");

			harmony.Patch(mapInit, postfix: new HarmonyMethod(typeof(Homm3RmgMapCaptureBridge), nameof(PostfixMapInit)));

			// Terrain prepare-map is the proven post-generate surface that receives a live Map
			// after RMG has populated MapData (same hook used by native water mesh / biome tint).
			MethodInfo prepareMap = null;
			foreach (var hint in GameSymbols.TerrainMaterial.RendererTypeHints)
			{
				var rendererType = GameMember.FindType(
					GameSymbols.TerrainMaterial.RendererTypeId + "." + hint,
					hint,
					() => AccessTools.TypeByName(hint) ?? AccessTools.TypeByName("Hex." + hint),
					logMiss: false);
				if (rendererType == null)
					continue;
				prepareMap = GameMember.FindFirstMethod(
					rendererType,
					typeof(void),
					new[] { typeof(Map), typeof(bool), typeof(bool) },
					GameSymbols.TerrainMaterial.RendererPrepareMap);
				if (prepareMap != null)
					break;
			}
			if (prepareMap != null)
			{
				harmony.Patch(
					prepareMap,
					postfix: new HarmonyMethod(typeof(Homm3RmgMapCaptureBridge), nameof(PostfixRendererPrepareMap)));
			}
			else
			{
				log?.LogWarning(LogPrefix + " terrain prepare-map unresolved; relying on Map.Init + WORLD poll only");
			}

			// Capture hooks only. Pre-RMG SoTerrainMaterial biome-name sanitize lives in
			// Homm3SwampAutumnTintProof (always-on) so ordinary random-map generation is covered.

			EnsureHost();
			_registered = true;
			log?.LogInfo(LogPrefix + " registered deferred capture flag=" + DiagnosticFlag
				+ " prepareMap=" + (prepareMap != null)
				+ " outDir=" + ResolveCaptureDirectory());
		}
		catch (Exception ex)
		{
			log?.LogWarning(LogPrefix + " failed closed during registration: " + ex);
		}
	}

	private static void PostfixMapInit(object __instance)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag) || _captureCompleted)
			return;

		var map = TryCastMap(__instance);
		if (map == null)
		{
			LogWarn("Map.Init armed skipped: instance was not Hex.Map.Map");
			return;
		}

		ArmPending(map, "Map.Init");
	}

	private static void PostfixRendererPrepareMap(object __instance, Map __0)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag) || _captureCompleted || __0 == null)
			return;

		var map = __0;
		TryInvokeNoArg(map, GameSymbols.RmgMapCapture.MapSyncToMapData);
		var mapData = ResolveMapData(map);
		if (IsMapDataReady(mapData))
		{
			LogInfo("RendererPrepareMap MapData ready; capturing immediately");
			CaptureNow(map, mapData);
			return;
		}

		ArmPending(map, "RendererPrepareMap");
	}

	private static void ArmPending(Map map, string source)
	{
		if (_captureCompleted)
			return;
		_pendingMap = map;
		_pending = true;
		_pendingSinceRealtime = Time.realtimeSinceStartup;
		_nextPollRealtime = 0f;
		_pollCount = 0;
		EnsureHost();
		LogInfo(source + " armed deferred capture; waiting for populated MapData");
	}

	internal static void DrainPending()
	{
		if (!_pending || _captureCompleted)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;

		var now = Time.realtimeSinceStartup;
		if (now < _nextPollRealtime)
			return;
		_nextPollRealtime = now + PollIntervalSeconds;
		_pollCount++;

		if (_pendingSinceRealtime >= 0f && now - _pendingSinceRealtime > CaptureTimeoutSeconds)
		{
			_pending = false;
			_captureCompleted = true;
			LogWarn("capture failed closed: MapData still unresolved after "
				+ CaptureTimeoutSeconds.ToString(CultureInfo.InvariantCulture) + "s polls="
				+ _pollCount.ToString(CultureInfo.InvariantCulture));
			return;
		}

		try
		{
			if (!TryResolveReadyMap(out var map, out var mapData, out var resolveReason))
			{
				if (_pollCount == 1 || _pollCount % 10 == 0)
					LogInfo("waiting for MapData poll=" + _pollCount.ToString(CultureInfo.InvariantCulture)
						+ " reason=" + resolveReason);
				return;
			}

			TryInvokeNoArg(map, GameSymbols.RmgMapCapture.MapSyncToMapData);
			mapData = ResolveMapData(map) ?? mapData;
			if (!IsMapDataReady(mapData))
			{
				if (_pollCount == 1 || _pollCount % 10 == 0)
					LogInfo("waiting for MapData readiness poll=" + _pollCount.ToString(CultureInfo.InvariantCulture));
				return;
			}

			CaptureNow(map, mapData);
		}
		catch (Exception ex)
		{
			_pending = false;
			_captureCompleted = true;
			LogWarn("capture failed closed: " + ex);
		}
	}

	private static void CaptureNow(Map map, MapData mapData)
	{
		_pending = false;
		_captureCompleted = true;

		var fileMapName = ReadMapDataString(mapData) ?? DefaultCaptureSid;
		var sid = SanitizeSid(fileMapName);
		var outDir = ResolveCaptureDirectory();
		Directory.CreateDirectory(outDir);

		if (TryNativeQlSave(map, mapData, out var containerBytes, out var nativeReason))
		{
			var rawPath = Path.Combine(outDir, sid + ".map.raw");
			File.WriteAllBytes(rawPath, containerBytes);
			var gzipPath = Path.Combine(outDir, sid + ".map");
			WriteGzipFile(gzipPath, containerBytes);
			WriteSidecar(outDir, sid, "ql.Save", mapData, gzipPath, containerBytes.Length);
			LogInfo("captured mode=ql.Save sid=" + sid + " bytes=" + containerBytes.Length.ToString(CultureInfo.InvariantCulture)
				+ " path=" + gzipPath + " polls=" + _pollCount.ToString(CultureInfo.InvariantCulture));
			// Native save path: fall back to live MapData object walk (native-field reads only).
			try { Homm3CampaignSpawnParityHook.IndexPlacedCitySidsFromMapData(mapData); }
			catch (Exception ex) { LogWarn("campaign city-sid index from MapData failed: " + ex.Message); }
			return;
		}

		LogWarn("native ql.Save unavailable: " + nativeReason + "; trying JsonUtility MapData dump");
		if (!TryJsonUtilityDump(mapData, outDir, sid, out var jsonPath, out var jsonReason))
		{
			LogWarn("capture failed closed: " + jsonReason);
			try { Homm3CampaignSpawnParityHook.IndexPlacedCitySidsFromMapData(mapData); }
			catch (Exception ex) { LogWarn("campaign city-sid index from MapData failed: " + ex.Message); }
			return;
		}

		try
		{
			var json = File.ReadAllText(jsonPath, Encoding.UTF8);
			Homm3CampaignSpawnParityHook.IndexPlacedCitySidsFromMapDataJson(json, sid);
		}
		catch (Exception ex)
		{
			LogWarn("campaign city-sid index from MapData JSON failed: " + ex.Message);
		}

		WriteSidecar(outDir, sid, "JsonUtility.ToJson(MapData)", mapData, jsonPath, new FileInfo(jsonPath).Length);
		LogInfo("captured mode=JsonUtility.ToJson(MapData) sid=" + sid + " path=" + jsonPath
			+ " polls=" + _pollCount.ToString(CultureInfo.InvariantCulture)
			+ " wrapHint=python tools/wrap_rmg_capture_map.py --map-data-json " + jsonPath);
	}

	private static bool TryResolveReadyMap(out Map map, out MapData mapData, out string reason)
	{
		map = _pendingMap;
		mapData = null;
		reason = null;

		if (map != null)
		{
			mapData = ResolveMapData(map);
			if (IsMapDataReady(mapData))
				return true;
			reason = "pending_map_data_not_ready";
		}

		if (TryReadWorldMap(out var worldMap, out var worldData, out var worldReason))
		{
			map = worldMap;
			mapData = worldData;
			_pendingMap = worldMap;
			return true;
		}

		reason = (reason ?? "no_pending_map") + "; world=" + worldReason;
		return false;
	}

	private static bool IsMapDataReady(MapData mapData)
	{
		if (mapData == null)
			return false;
		var sizeX = TryReadIntMember(mapData, "sizeX_", "sizeX");
		var sizeZ = TryReadIntMember(mapData, "sizeZ_", "sizeZ");
		if (sizeX.HasValue && sizeZ.HasValue && sizeX.Value > 0 && sizeZ.Value > 0)
			return true;
		foreach (var name in GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers)
		{
			var tiles = TryReadMember(mapData, name);
			if (tiles == null)
				continue;
			try
			{
				var lengthProp = tiles.GetType().GetProperty("Length") ?? tiles.GetType().GetProperty("Count");
				if (lengthProp != null && Convert.ToInt32(lengthProp.GetValue(tiles), CultureInfo.InvariantCulture) > 0)
					return true;
			}
			catch
			{
			}
		}
		return !string.IsNullOrWhiteSpace(ReadMapDataString(mapData));
	}

	private static bool TryReadWorldMap(out Map map, out MapData mapData, out string reason)
	{
		map = null;
		mapData = null;
		reason = null;
		for (var i = 0; i < SceneManager.sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			GameObject[] roots;
			try { roots = scene.GetRootGameObjects(); }
			catch (Exception ex)
			{
				reason = "scene_root_read_failed " + ex.Message;
				continue;
			}
			foreach (var root in roots)
			{
				if (!root || !string.Equals(root.name, GameSymbols.HomecomingBoatTravel.WorldRootName, StringComparison.Ordinal))
					continue;
				var worldType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldOwner);
				if (worldType == null)
				{
					reason = "world_owner_type_unresolved";
					return false;
				}
				Component worldComponent;
				try { worldComponent = root.GetComponent(Il2CppInterop.Runtime.Il2CppType.From(worldType))?.TryCast<Component>(); }
				catch (Exception ex)
				{
					reason = "world_component_lookup_failed " + ex.Message;
					return false;
				}
				if (!worldComponent)
				{
					reason = "world_component_missing";
					return false;
				}
				var worldMapObj = InvokeFirstNoArg(worldComponent, typeof(Map), GameSymbols.HomecomingBoatTravel.WorldMap);
				map = TryCastMap(worldMapObj);
				if (map == null)
				{
					reason = "world_map_unresolved";
					return false;
				}
				mapData = ResolveMapData(map);
				if (!IsMapDataReady(mapData))
				{
					reason = "world_map_data_not_ready";
					return false;
				}
				return true;
			}
		}
		reason = "world_root_not_found";
		return false;
	}

	private static void EnsureHost()
	{
		if (Homm3RmgMapCaptureHost.Attached)
			return;
		if (!_registeredHostType)
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3RmgMapCaptureHost>();
			_registeredHostType = true;
		}
		var go = new GameObject(HostName);
		go.hideFlags = HideFlags.HideAndDontSave;
		if (go.AddComponent<Homm3RmgMapCaptureHost>() == null)
			throw new InvalidOperationException(LogPrefix + " host component registration failed.");
		UnityEngine.Object.DontDestroyOnLoad(go);
		Homm3RmgMapCaptureHost.Attached = true;
	}

	private static bool TryNativeQlSave(Map map, MapData mapData, out byte[] bytes, out string reason)
	{
		bytes = null;
		reason = null;
		try
		{
			var containerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.RmgMapCaptureMapContainer);
			if (containerType == null)
			{
				reason = "ql_type_unresolved";
				return false;
			}

			object container;
			try { container = Activator.CreateInstance(containerType); }
			catch (Exception ex)
			{
				reason = "ql_ctor_failed " + ex.Message;
				return false;
			}

			if (!TrySetField(container, GameSymbols.RmgMapCapture.MapContainerMap, map))
			{
				reason = "ql.bqpp_set_failed";
				return false;
			}

			TrySetField(container, GameSymbols.RmgMapCapture.MapContainerMapData, mapData);

			var metaType = typeof(MapMetaInfo);
			object meta = null;
			try { meta = Activator.CreateInstance(metaType); }
			catch { meta = null; }
			if (meta != null)
			{
				TrySetStringMember(meta, "title", ReadMapDataString(mapData) ?? DefaultCaptureSid);
				TrySetStringMember(meta, "hashSum", "");
				TrySetField(container, GameSymbols.RmgMapCapture.MapContainerMeta, meta);
			}

			var save = FindInstanceMethodReturningBytes(containerType, GameSymbols.RmgMapCapture.MapContainerSave);
			if (save == null)
			{
				reason = "ql.Save_unresolved";
				return false;
			}

			object raw;
			try { raw = save.Invoke(container, null); }
			catch (Exception ex)
			{
				reason = "ql.Save_threw " + ex.Message;
				return false;
			}

			bytes = CoerceByteArray(raw);
			if (bytes == null || bytes.Length < 40)
			{
				reason = "ql.Save_empty_or_short len=" + (bytes == null ? 0 : bytes.Length);
				return false;
			}

			return true;
		}
		catch (Exception ex)
		{
			reason = ex.Message;
			return false;
		}
	}

	private static bool TryJsonUtilityDump(MapData mapData, string outDir, string sid, out string jsonPath, out string reason)
	{
		jsonPath = null;
		reason = null;
		try
		{
			string json;
			try { json = JsonUtility.ToJson(mapData, false); }
			catch (Exception ex)
			{
				reason = "JsonUtility.ToJson_failed " + ex.Message;
				return false;
			}

			if (string.IsNullOrWhiteSpace(json) || json == "{}" || json.Length < 32)
			{
				reason = "JsonUtility.ToJson_empty_or_stub len=" + (json == null ? 0 : json.Length);
				return false;
			}

			jsonPath = Path.Combine(outDir, sid + ".mapdata.json");
			File.WriteAllText(jsonPath, json, Encoding.UTF8);
			return true;
		}
		catch (Exception ex)
		{
			reason = ex.Message;
			return false;
		}
	}

	private static void WriteSidecar(string outDir, string sid, string mode, MapData mapData, string payloadPath, long payloadBytes)
	{
		var sidecar = new JObject
		{
			["schema"] = "homm3.rmg_map_capture.v1",
			["sid"] = sid,
			["mode"] = mode,
			["payloadPath"] = payloadPath,
			["payloadBytes"] = payloadBytes,
			["fileMapName"] = ReadMapDataString(mapData),
			["sizeX"] = TryReadIntMember(mapData, "sizeX_", "sizeX"),
			["sizeZ"] = TryReadIntMember(mapData, "sizeZ_", "sizeZ"),
			["capturedAtUtc"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
			["proofBoundary"] = "runtime-capture-unvalidated-reload",
		};
		File.WriteAllText(Path.Combine(outDir, sid + ".capture.json"), sidecar.ToString(), Encoding.UTF8);
	}

	private static MethodInfo FindMapInitMethod()
	{
		var mapType = typeof(Map);
		foreach (var hint in GameSymbols.RmgMapCapture.MapInit.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			try
			{
				foreach (var method in mapType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
				{
					if (!string.Equals(method.Name, hint, StringComparison.Ordinal)
					    && !string.Equals(method.Name, "Init", StringComparison.Ordinal))
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length != 1)
						continue;
					var p0 = parameters[0].ParameterType;
					var p0Name = p0.Name ?? "";
					if (p0Name.IndexOf("bud", StringComparison.OrdinalIgnoreCase) >= 0
					    || p0Name.IndexOf("btv", StringComparison.OrdinalIgnoreCase) >= 0
					    || typeof(MonoBehaviour).IsAssignableFrom(p0)
					    || p0.IsInterface)
						return method;
				}
			}
			catch
			{
			}
		}

		try
		{
			foreach (var method in AccessTools.GetDeclaredMethods(mapType))
			{
				if (!string.Equals(method.Name, "Init", StringComparison.Ordinal))
					continue;
				if (method.GetParameters().Length == 1)
					return method;
			}
		}
		catch
		{
		}

		return null;
	}

	private static Map TryCastMap(object value)
	{
		if (value is Map map)
			return map;
		if (value is Il2CppObjectBase il2Cpp)
		{
			try { return il2Cpp.TryCast<Map>(); }
			catch { return null; }
		}
		return null;
	}

	private static MapData ResolveMapData(Map map)
	{
		if (map == null)
			return null;
		try
		{
			var direct = InvokeFirstNoArg(map, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData);
			if (direct is MapData md)
				return md;
			if (direct != null)
			{
				try
				{
					var cast = (direct as Il2CppObjectBase)?.TryCast<MapData>();
					if (cast != null)
						return cast;
				}
				catch
				{
				}
			}
		}
		catch
		{
		}

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[]
		{
			"bvjr",
			"get_bvjr",
			"mapData",
			"get_mapData",
			"<bvjr>k__BackingField",
			"_bvjr_k__BackingField",
			GameSymbols.HomecomingPlayableShell.MapDataNestedData.FieldName,
		})
		{
			try
			{
				var prop = typeof(Map).GetProperty(name, flags);
				if (prop != null && prop.GetValue(map) is MapData fromProp)
					return fromProp;
				var field = typeof(Map).GetField(name, flags);
				if (field != null && field.GetValue(map) is MapData fromField)
					return fromField;
				var method = typeof(Map).GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.Invoke(map, null) is MapData fromMethod)
					return fromMethod;
			}
			catch
			{
			}
		}

		return null;
	}

	private static object TryReadMember(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var field = obj.GetType().GetField(name, flags);
			if (field != null)
				return field.GetValue(obj);
			var prop = obj.GetType().GetProperty(name, flags);
			if (prop != null)
				return prop.GetValue(obj);
			var method = obj.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null)
				return method.Invoke(obj, null);
		}
		catch
		{
		}
		return null;
	}

	private static string ResolveCaptureDirectory()
	{
		var candidates = new[]
		{
			Path.GetFullPath(Path.Combine(Paths.GameRootPath, "..", "..", "..", "Games", "Olden Era Playtest Tweak", CaptureRelativeDir)),
			Path.GetFullPath(Path.Combine(Paths.BepInExRootPath, "..", "..", "..", "Games", "Olden Era Playtest Tweak", CaptureRelativeDir)),
			@"V:\Games\Olden Era Playtest Tweak\artifacts\rmg_capture",
			Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "rmg_capture"),
		};
		foreach (var candidate in candidates)
		{
			try
			{
				var parent = Path.GetDirectoryName(candidate);
				if (!string.IsNullOrWhiteSpace(parent) && Directory.Exists(parent))
					return candidate;
			}
			catch
			{
			}
		}
		return candidates[candidates.Length - 1];
	}

	private static void WriteGzipFile(string path, byte[] uncompressed)
	{
		using var output = File.Create(path);
		using var gzip = new System.IO.Compression.GZipStream(output, System.IO.Compression.CompressionLevel.Optimal);
		gzip.Write(uncompressed, 0, uncompressed.Length);
	}

	private static MethodInfo FindInstanceMethodReturningBytes(Type type, GameSymbols.MethodSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? System.Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cursor = type; cursor != null; cursor = cursor.BaseType)
			{
				MethodInfo method;
				try { method = cursor.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null)
					continue;
				if (method.ReturnType == typeof(byte[])
				    || method.ReturnType.FullName == "Il2CppStructArray`1[System.Byte]"
				    || (method.ReturnType.Name != null && method.ReturnType.Name.IndexOf("Byte", StringComparison.Ordinal) >= 0))
					return method;
			}
		}

		foreach (var method in type.GetMethods(flags))
		{
			if (method.GetParameters().Length != 0)
				continue;
			if (string.Equals(method.Name, "Save", StringComparison.Ordinal))
				return method;
		}
		return null;
	}

	private static byte[] CoerceByteArray(object raw)
	{
		if (raw == null)
			return null;
		if (raw is byte[] managed)
			return managed;

		try
		{
			var lengthProp = raw.GetType().GetProperty("Length")
				?? raw.GetType().GetProperty("Count");
			if (lengthProp == null)
				return null;
			var length = Convert.ToInt32(lengthProp.GetValue(raw), CultureInfo.InvariantCulture);
			if (length < 0)
				return null;
			var result = new byte[length];
			var indexer = raw.GetType().GetProperty("Item", new[] { typeof(int) });
			if (indexer != null)
			{
				for (var i = 0; i < length; i++)
					result[i] = Convert.ToByte(indexer.GetValue(raw, new object[] { i }), CultureInfo.InvariantCulture);
				return result;
			}

			// Il2CppStructArray often exposes a managed copy via ToArray / get_Item.
			var toArray = raw.GetType().GetMethod("ToArray", Type.EmptyTypes);
			if (toArray != null && toArray.Invoke(raw, null) is byte[] copied)
				return copied;

			var getItem = raw.GetType().GetMethod("get_Item", new[] { typeof(int) });
			if (getItem == null)
				return null;
			for (var i = 0; i < length; i++)
				result[i] = Convert.ToByte(getItem.Invoke(raw, new object[] { i }), CultureInfo.InvariantCulture);
			return result;
		}
		catch
		{
			return null;
		}
	}

	private static bool TrySetField(object target, GameSymbols.FieldSymbol symbol, object value)
	{
		if (target == null || value == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[] { symbol.FieldName, symbol.NativeFieldInfoName, "field_Public_Map_0", "field_Public_MapData_0", "field_Public_MapMetaInfo_0" })
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var type = target.GetType(); type != null; type = type.BaseType)
			{
				FieldInfo field;
				try { field = type.GetField(name, flags); }
				catch { field = null; }
				if (field == null)
					continue;
				try
				{
					field.SetValue(target, value);
					return true;
				}
				catch
				{
				}
			}
		}

		foreach (var field in target.GetType().GetFields(flags))
		{
			if (field.FieldType.IsInstanceOfType(value))
			{
				try
				{
					field.SetValue(target, value);
					return true;
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static void TrySetStringMember(object target, string name, string value)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var field = target.GetType().GetField(name, flags);
			if (field != null && field.FieldType == typeof(string))
			{
				field.SetValue(target, value);
				return;
			}
			var prop = target.GetType().GetProperty(name, flags);
			if (prop != null && prop.CanWrite && prop.PropertyType == typeof(string))
				prop.SetValue(target, value);
		}
		catch
		{
		}
	}

	private static void TryInvokeNoArg(object obj, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null)
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? System.Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var type = obj.GetType(); type != null; type = type.BaseType)
			{
				MethodInfo method;
				try { method = type.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null)
					continue;
				try
				{
					method.Invoke(obj, null);
					return;
				}
				catch
				{
				}
			}
		}
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

	private static string ReadMapDataString(object mapData)
	{
		if (mapData == null)
			return null;
		foreach (var name in GameSymbols.HomecomingBoatTravel.MapDataFileNameMembers)
		{
			var value = TryReadStringMember(mapData, name);
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static string TryReadStringMember(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var field = obj.GetType().GetField(name, flags);
			if (field != null && field.GetValue(obj) is string fs)
				return fs;
			var prop = obj.GetType().GetProperty(name, flags);
			if (prop != null && prop.GetValue(obj) is string ps)
				return ps;
			var method = obj.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.Invoke(obj, null) is string ms)
				return ms;
		}
		catch
		{
		}
		return null;
	}

	private static int? TryReadIntMember(object obj, params string[] names)
	{
		if (obj == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			try
			{
				var field = obj.GetType().GetField(name, flags);
				if (field != null)
					return Convert.ToInt32(field.GetValue(obj), CultureInfo.InvariantCulture);
				var prop = obj.GetType().GetProperty(name, flags);
				if (prop != null)
					return Convert.ToInt32(prop.GetValue(obj), CultureInfo.InvariantCulture);
			}
			catch
			{
			}
		}
		return null;
	}

	private static Type GetTypeByName(string name)
	{
		var type = AccessTools.TypeByName(name) ?? AccessTools.TypeByName("Hex." + name);
		if (type != null)
			return type;
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			try { type = assembly.GetType(name, false) ?? assembly.GetType("Hex." + name, false); }
			catch { type = null; }
			if (type != null)
				return type;
		}
		return null;
	}

	private static string SanitizeSid(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return DefaultCaptureSid;
		var sb = new StringBuilder(value.Length);
		foreach (var ch in value.Trim())
		{
			if (char.IsLetterOrDigit(ch) || ch == '_' || ch == '-')
				sb.Append(ch);
			else
				sb.Append('_');
		}
		var sid = sb.ToString();
		return string.IsNullOrWhiteSpace(sid) ? DefaultCaptureSid : sid;
	}

	private static void LogInfo(string message) => (_log ?? Plugin.LogSource)?.LogInfo(LogPrefix + " " + message);
	private static void LogWarn(string message) => (_log ?? Plugin.LogSource)?.LogWarning(LogPrefix + " " + message);
}

/// <summary>Must be public for Il2CppInterop ClassInjector registration.</summary>
public sealed class Homm3RmgMapCaptureHost : MonoBehaviour
{
	internal static bool Attached;

	private void LateUpdate()
	{
		Homm3RmgMapCaptureBridge.DrainPending();
	}
}
