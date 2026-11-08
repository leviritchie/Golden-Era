using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using Hex.Configs;
using Hex.Map;
using Hex.Session.Logic;
using Il2CppInterop.Runtime;
using TMPro;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static partial class Homm3AiDriverBridge
{
	internal const string ScreenDumpSchemaVersion = "ai-driver.v1.screen-dump";
	internal const string VisibleSnapshotSchemaVersion = "ai-driver.v1.visible-snapshot";
	private const int ScreenDumpMaxElements = 512;
	private const int VisibleSnapshotMaxElements = 256;
	private const int ScreenDumpCacheTtlFrames = 30;
	private const int MapWorldByIdProjectBudget = 48;
	private static Camera _cachedAdventureDumpCamera;
	private static string _cachedAdventureDumpCameraSource;
	private static int _adventureDumpCameraMissUntilFrame = int.MinValue;
	private const int AdventureDumpCameraMissBackoffFrames = 180;

	private static string _lastDumpId;
	private static string _lastDumpJson;
	private static int _cachedDumpFrame = -1;
	private static int _cachedDumpLimit;
	private static bool _cachedDumpIncludeTextOnly;
	private static string _cachedDumpMode;
	private static string _cachedDumpScene;
	private static string _cachedDumpJson;
	private static string _cachedDumpId;
	private static List<DumpElementRecord> _cachedDumpRecords;

	// Session cache: avoid repeating zero-hit FindObjectsOfTypeAll scans every dump.
	private static bool _placedScanCompleted;
	private static bool _placedScanAllCold;
	private static Type _placedScanHotType;
	private static string _placedScanNote;

	private static bool _worldHeroScanCompleted;
	private static bool _worldHeroScanAllCold;
	private static readonly List<Type> _worldHeroScanHotTypes = new();
	private static string _worldHeroScanNote;
	private static string _lastLogicWorldEnumerateNote;
	private static MethodInfo _cachedWorldHeroIdGetter;
	private static bool _worldHeroIdGetterResolveAttempted;

	private sealed class DumpElementRecord
	{
		internal string Id;
		internal string Kind;
		internal string Role;
		internal string Name;
		internal string Path;
		internal string Label;
		internal string Sid;
		internal string RectJson;
		internal bool Visible;
		internal bool Enabled;
		internal bool Interactable;
		internal bool OnScreen;
		internal bool? FogVisible;
		internal string FingerprintValue;
		internal int InstanceId;
		internal float RectX;
		internal float RectY;
		internal float RectW;
		internal float RectH;
	}

	internal static string BuildScreenDumpResponse(string id, string requestJson)
	{
		var uiLimit = ReadIntBounded(requestJson, "elementLimit", 256, 1, ScreenDumpMaxElements);
		var includeTextOnly = !JsonBoolFalseExplicit(requestJson, "includeTextOnly");
		var dumpJson = BuildScreenDumpJson(uiLimit, includeTextOnly);
		return OkResponse(id, "\"dump\":" + dumpJson);
	}

	internal static string BuildVisibleSnapshotResponse(string id, string requestJson)
	{
		var elementLimit = ReadIntBounded(requestJson, "elementLimit", 128, 1, VisibleSnapshotMaxElements);
		var includeTextOnly = !JsonBoolFalseExplicit(requestJson, "includeTextOnly");
		var dumpJson = BuildScreenDumpJson(Math.Min(elementLimit * 2, ScreenDumpMaxElements), includeTextOnly);
		var visibleJson = BuildVisibleSnapshotFromDumpJson(dumpJson, elementLimit, includeTextOnly);
		return OkResponse(id, "\"visible\":" + visibleJson);
	}

	private static bool JsonBoolFalseExplicit(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return false;
		var match = System.Text.RegularExpressions.Regex.Match(
			json,
			"\\\"" + System.Text.RegularExpressions.Regex.Escape(key) + "\\\"\\s*:\\s*(?<v>true|false)");
		return match.Success && string.Equals(match.Groups["v"].Value, "false", StringComparison.Ordinal);
	}

	internal static string BuildScreenDumpJson(int requestedLimit, bool includeTextOnly)
	{
		var elementLimit = Math.Max(1, Math.Min(requestedLimit <= 0 ? 256 : requestedLimit, ScreenDumpMaxElements));
		var activeScene = SceneManager.GetActiveScene();
		var sceneName = activeScene.IsValid() ? activeScene.name ?? "" : "";
		var mode = InferModeFromLoadedScenes(sceneName);
		var frame = Time.frameCount;

		if (!string.IsNullOrEmpty(_cachedDumpJson)
		    && _cachedDumpLimit == elementLimit
		    && _cachedDumpIncludeTextOnly == includeTextOnly
		    && string.Equals(_cachedDumpMode, mode, StringComparison.Ordinal)
		    && string.Equals(_cachedDumpScene, sceneName, StringComparison.Ordinal)
		    && frame >= _cachedDumpFrame
		    && frame - _cachedDumpFrame <= ScreenDumpCacheTtlFrames)
		{
			_lastDumpId = _cachedDumpId;
			_lastDumpJson = _cachedDumpJson;
			return _cachedDumpJson;
		}

		var dumpId = Guid.NewGuid().ToString("N");
		var gaps = new List<string>();
		var elements = new List<DumpElementRecord>(elementLimit);
		var seen = new HashSet<int>();
		var mapRowsEmitted = 0;

		if (mode == "unknown")
			gaps.Add(GapJson("mode_unknown", "Active scene name did not map to a known AI driver mode.", false));

		gaps.Add(GapJson(
			"screen_dump_not_sr_safe",
			"screen_dump is an AI catalog only. Do not feed dump rows to NVDA or AssistiveSupport; use hover_snapshot / visible_snapshot consumers instead.",
			false));

		// Adventure-map mode prefers world catalog rows so UI selectables cannot starve the bound.
		if (string.Equals(mode, "adventure_map", StringComparison.Ordinal))
			mapRowsEmitted = AppendMapWorldDumpElements(elements, seen, elementLimit, gaps);

		if (mapRowsEmitted <= 0)
		{
			gaps.Add(GapJson(
				"map_world_objects_undumped",
				"Adventure-map / battle world interactables were not enumerated in this screen_dump (no map_object/map_marker/map_hero rows).",
				false));
		}
		else
		{
			gaps.Add(GapJson(
				"map_hover_name_unproven",
				"Map dump labels are raw sid/id only; LocKit hover display names are not resolved.",
				false));
			// Fog gap is owned by AppendMapWorldDumpElements (applied vs unresolved).
		}

		// Skip expensive UI/TMP scans once the catalog already filled the bound.
		if (elements.Count < elementLimit)
		{
			var selectables = CollectSupportedUiComponents(Math.Max((elementLimit - elements.Count) * 4, 64), gaps);
			selectables.Sort(CompareUiComponentForStableObservation);
			for (var i = 0; i < selectables.Count && elements.Count < elementLimit; i++)
			{
				var component = selectables[i];
				if (!TryBuildDumpElementFromSelectable(component, seen, out var record))
					continue;
				elements.Add(record);
			}

			if (includeTextOnly && elements.Count < elementLimit)
				AppendTextOnlyDumpElements(elements, seen, elementLimit, gaps);
		}

		if (elements.Count >= elementLimit)
			gaps.Add(GapJson("element_limit_reached", "screen_dump element output reached the requested bound.", false));

		var elementJson = new List<string>(elements.Count);
		for (var i = 0; i < elements.Count; i++)
			elementJson.Add(DumpElementToJson(elements[i]));

		var screenId = "screen-" + StableHash(sceneName + "|" + mode + "|dump|" + elements.Count.ToString(CultureInfo.InvariantCulture));
		for (var i = 0; i < Math.Min(24, elementJson.Count); i++)
			screenId = "screen-" + StableHash(screenId + "|" + elementJson[i]);

		var json = "{"
			+ "\"schemaVersion\":\"" + ScreenDumpSchemaVersion + "\","
			+ "\"dumpId\":\"" + EscapeJson(dumpId) + "\","
			+ "\"screenId\":\"" + EscapeJson(screenId) + "\","
			+ "\"scene\":\"" + EscapeJson(sceneName) + "\","
			+ "\"frame\":" + frame.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(mode) + "\","
			+ "\"timestamp\":\"" + EscapeJson(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) + "\","
			+ "\"elements\":[" + string.Join(",", elementJson) + "],"
			+ "\"gaps\":[" + string.Join(",", gaps) + "],"
			+ "\"srSafe\":false"
			+ "}";
		_lastDumpId = dumpId;
		_lastDumpJson = json;
		_cachedDumpFrame = frame;
		_cachedDumpLimit = elementLimit;
		_cachedDumpIncludeTextOnly = includeTextOnly;
		_cachedDumpMode = mode;
		_cachedDumpScene = sceneName;
		_cachedDumpJson = json;
		_cachedDumpId = dumpId;
		_cachedDumpRecords = elements;
		return json;
	}

	private static string BuildVisibleSnapshotFromDumpJson(string dumpJson, int elementLimit, bool includeTextOnly)
	{
		var gaps = new List<string>();
		gaps.Add(GapJson(
			"visible_not_sr_ordered",
			"visible_snapshot pares on-screen catalog rows; it is not a screen-reader focus order.",
			false));

		// Reuse the dump we just built (or the short TTL cache) — do not run a second full catalog scan.
		var liveDump = dumpJson;
		if (string.IsNullOrEmpty(liveDump)
		    || _cachedDumpRecords == null
		    || _cachedDumpRecords.Count == 0)
			liveDump = BuildScreenDumpJson(Math.Min(elementLimit * 2, ScreenDumpMaxElements), includeTextOnly);

		var dumpId = ReadString(liveDump, "dumpId") ?? (_lastDumpId ?? Guid.NewGuid().ToString("N"));
		var mode = ReadString(liveDump, "mode") ?? InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
		var visible = new List<string>(elementLimit);
		var screenW = Screen.width;
		var screenH = Screen.height;
		var records = _cachedDumpRecords;
		if (records == null)
		{
			gaps.Add(GapJson("visible_dump_records_missing", "No cached dump records available for visible_snapshot.", true));
		}
		else
		{
			for (var i = 0; i < records.Count && visible.Count < elementLimit; i++)
			{
				var record = records[i];
				if (!record.Visible || !record.OnScreen)
					continue;
				if (!RectIntersectsScreen(record.RectX, record.RectY, record.RectW, record.RectH, screenW, screenH))
					continue;
				visible.Add(DumpElementToJson(record));
			}
		}

		if (visible.Count == 0)
			gaps.Add(GapJson("no_visible_elements", "No dump candidates passed on-screen visibility gates.", false));
		if (visible.Count >= elementLimit)
			gaps.Add(GapJson("visible_limit_reached", "visible_snapshot output reached the requested bound.", false));
		gaps.Add(GapJson("occlusion_unproven", "Full UI occlusion is not proven; onScreen uses rect/screen intersection and CanvasGroup alpha only.", false));

		return "{"
			+ "\"schemaVersion\":\"" + VisibleSnapshotSchemaVersion + "\","
			+ "\"dumpId\":\"" + EscapeJson(dumpId) + "\","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(mode) + "\","
			+ "\"timestamp\":\"" + EscapeJson(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) + "\","
			+ "\"visibleElements\":[" + string.Join(",", visible) + "],"
			+ "\"gaps\":[" + string.Join(",", gaps) + "],"
			+ "\"srSafe\":false"
			+ "}";
	}

	private static bool TryBuildDumpElementFromSelectable(Component component, HashSet<int> seen, out DumpElementRecord record)
	{
		record = null;
		if (!component || !component.gameObject || !component.gameObject.activeInHierarchy)
			return false;
		var go = component.gameObject;
		var id = go.GetInstanceID();
		if (!seen.Add(id))
			return false;
		var rectTransform = go.GetComponent<RectTransform>();
		if (rectTransform == null)
			return false;
		var path = UnityPath(component.transform);
		var typeName = ComponentTypeName(component);
		var enabled = TryReadSupportedUiState(component, typeName, out var interactable);
		var role = UiRole(typeName);
		var label = UiText(go);
		if (string.IsNullOrEmpty(label))
			label = go.name ?? "";
		ParseScreenRect(rectTransform, go.GetComponentInParent<Canvas>(), out var x, out var y, out var w, out var h, out var rectJson);
		var onScreen = RectIntersectsScreen(x, y, w, h, Screen.width, Screen.height);
		var canvasHidden = IsCanvasGroupHidden(go);
		var visible = go.activeInHierarchy && HasPositiveRect(rectTransform) && onScreen && !canvasHidden;
		var sceneName = go.scene.IsValid() ? go.scene.name ?? "" : "";
		var fingerprintValue = sceneName + "|" + path + "|" + id.ToString(CultureInfo.InvariantCulture);
		var binderSid = Homm3UiInspectorContextRegistry.FindNearest(go);
		record = new DumpElementRecord
		{
			Id = StableElementId("dump", id, path),
			Kind = "selectable",
			Role = role,
			Name = go.name ?? "",
			Path = path,
			Label = label,
			Sid = ExtractSidHint(binderSid),
			RectJson = rectJson,
			Visible = visible,
			Enabled = enabled,
			Interactable = enabled && interactable,
			OnScreen = onScreen && !canvasHidden,
			FingerprintValue = fingerprintValue,
			InstanceId = id,
			RectX = x,
			RectY = y,
			RectW = w,
			RectH = h
		};
		return true;
	}

	private static void AppendTextOnlyDumpElements(List<DumpElementRecord> elements, HashSet<int> seen, int elementLimit, List<string> gaps)
	{
		TMP_Text[] tmpTexts;
		try
		{
			tmpTexts = UnityObject.FindObjectsOfType<TMP_Text>(true);
		}
		catch (Exception ex)
		{
			gaps.Add(GapJson("text_only_scan_failed", "TMP_Text scan failed: " + ex.GetType().Name + ": " + ex.Message, true));
			return;
		}

		Array.Sort(tmpTexts, (a, b) =>
		{
			var left = a && a.transform ? UnityPath(a.transform) : "";
			var right = b && b.transform ? UnityPath(b.transform) : "";
			return string.Compare(left, right, StringComparison.Ordinal);
		});

		for (var i = 0; i < tmpTexts.Length && elements.Count < elementLimit; i++)
		{
			var tmp = tmpTexts[i];
			if (!tmp || !tmp.gameObject || !tmp.gameObject.activeInHierarchy || string.IsNullOrWhiteSpace(tmp.text))
				continue;
			if (tmp.GetComponentInParent<Selectable>() != null)
				continue;
			var go = tmp.gameObject;
			var id = go.GetInstanceID();
			if (!seen.Add(id))
				continue;
			var rectTransform = go.GetComponent<RectTransform>();
			if (rectTransform == null)
				continue;
			var path = UnityPath(tmp.transform);
			ParseScreenRect(rectTransform, go.GetComponentInParent<Canvas>(), out var x, out var y, out var w, out var h, out var rectJson);
			var onScreen = RectIntersectsScreen(x, y, w, h, Screen.width, Screen.height) && !IsCanvasGroupHidden(go);
			var sceneName = go.scene.IsValid() ? go.scene.name ?? "" : "";
			elements.Add(new DumpElementRecord
			{
				Id = StableElementId("dump-text", id, path),
				Kind = "text_only",
				Role = "text",
				Name = go.name ?? "",
				Path = path,
				Label = tmp.text.Trim(),
				Sid = null,
				RectJson = rectJson,
				Visible = go.activeInHierarchy && HasPositiveRect(rectTransform) && onScreen,
				Enabled = tmp.enabled,
				Interactable = false,
				OnScreen = onScreen,
				FingerprintValue = sceneName + "|" + path + "|" + id.ToString(CultureInfo.InvariantCulture),
				InstanceId = id,
				RectX = x,
				RectY = y,
				RectW = w,
				RectH = h
			});
		}
	}

	private static string DumpElementToJson(DumpElementRecord record)
	{
		var sidPart = string.IsNullOrEmpty(record.Sid) ? "" : ",\"sid\":\"" + EscapeJson(record.Sid) + "\"";
		var fogPart = record.FogVisible.HasValue ? ",\"fogVisible\":" + BoolJson(record.FogVisible.Value) : "";
		return "{"
			+ "\"id\":\"" + EscapeJson(record.Id) + "\","
			+ "\"kind\":\"" + EscapeJson(record.Kind) + "\","
			+ "\"role\":\"" + EscapeJson(record.Role) + "\","
			+ "\"name\":\"" + EscapeJson(record.Name) + "\","
			+ "\"path\":\"" + EscapeJson(record.Path) + "\","
			+ "\"label\":\"" + EscapeJson(record.Label) + "\""
			+ sidPart + ","
			+ "\"rect\":" + record.RectJson + ","
			+ "\"visible\":" + BoolJson(record.Visible) + ","
			+ "\"enabled\":" + BoolJson(record.Enabled) + ","
			+ "\"interactable\":" + BoolJson(record.Interactable) + ","
			+ "\"onScreen\":" + BoolJson(record.OnScreen)
			+ fogPart + ","
			+ "\"fingerprint\":" + FingerprintJson("dump_path", record.FingerprintValue)
			+ "}";
	}

	private static void ParseScreenRect(RectTransform rectTransform, Canvas canvas, out float x, out float y, out float w, out float h, out string rectJson)
	{
		rectJson = ScreenRectJson(rectTransform, canvas);
		x = y = w = h = 0f;
		if (!TryGetScreenRect(rectTransform, canvas, out var minX, out var minY, out var maxX, out var maxY))
			return;
		x = minX;
		y = minY;
		w = Math.Max(0, maxX - minX);
		h = Math.Max(0, maxY - minY);
	}

	private static bool RectIntersectsScreen(float x, float y, float w, float h, int screenW, int screenH)
	{
		if (w <= 0.1f || h <= 0.1f)
			return false;
		return x < screenW && y < screenH && x + w > 0 && y + h > 0;
	}

	private static bool IsCanvasGroupHidden(GameObject go)
	{
		if (!go)
			return false;
		try
		{
			var groups = go.GetComponentsInParent<CanvasGroup>(true);
			for (var g = 0; g < groups.Length; g++)
			{
				if (groups[g] && groups[g].alpha <= 0.01f)
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static string ExtractSidHint(string binderContext)
	{
		if (string.IsNullOrWhiteSpace(binderContext))
			return null;
		// Context registry is free-form diagnostics; only surface an explicit sid='...' token when present.
		var marker = "sid='";
		var idx = binderContext.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (idx < 0)
			return null;
		var start = idx + marker.Length;
		var end = binderContext.IndexOf('\'', start);
		if (end <= start)
			return null;
		var sid = binderContext.Substring(start, end - start).Trim();
		return string.IsNullOrEmpty(sid) || sid == "?" ? null : sid;
	}

	/// <summary>
	/// Adventure-map world catalog: placed objects, MapData markers, propHeroes.
	/// Returns count of map_* rows appended. Fail-closed gaps on resolve/camera misses.
	/// </summary>
	private static int AppendMapWorldDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		List<string> gaps)
	{
		if (elements == null || seen == null || gaps == null || elementLimit <= 0)
			return 0;

		try
		{
			if (!TryResolveAdventureMapContext(out var mapInstance, out var mapData, out var resolveReason))
			{
				gaps.Add(GapJson(
					"map_world_resolve_failed",
					"BhWorldCamera/Map/MapData resolve failed: " + (resolveReason ?? "unknown"),
					true));
				return 0;
			}

			var camera = ResolveAdventureMapDumpCamera(out var cameraSource);
			var cameraOk = camera != null;
			if (!cameraOk)
				gaps.Add(GapJson(
					"map_world_camera_unproven",
					"No adventure-map projection camera (Camera.main / BhWorldCamera). Map rows emit with zero rect until available.",
					false));
			else if (!string.IsNullOrEmpty(cameraSource) && cameraSource != "Camera.main")
				gaps.Add(GapJson(
					"map_world_camera_source",
					"Map dump projection camera source=" + cameraSource + ".",
					false));

			object fogOfWar = null;
			var fogOk = TryResolveAdventureMapFogOfWar(mapInstance, mapData, out fogOfWar, out var fogReason);
			if (!fogOk)
			{
				gaps.Add(GapJson(
					"map_fog_visibility_unresolved",
					"Local Side.fogData / DataFogOfWar unresolved: " + (fogReason ?? "unknown")
					+ ". Map onScreen forced false until FoW is readable (camera frustum alone is not vision).",
					true));
			}
			else
			{
				var fogSource = Homm3AiDriverFogCache.TryGetFogOfWar(out _, out var src) ? src : "session/static";
				gaps.Add(GapJson(
					"map_fog_visibility_applied",
					"Map onScreen requires camera projection AND DataFogOfWar visibility (source="
					+ fogSource
					+ "; Side.fogData / bfrj).",
					false));
			}

			var byNode = new Dictionary<int, MapWorldScreenPoint>();
			var byId = new Dictionary<int, MapWorldScreenPoint>();
			var before = elements.Count;
			var census = new MapWorldCensus();

			// Live transforms when available; MapData.nodes → Map.oar/oaq is the fail-closed rect path when placed scans are cold.
			AppendPlacedObjectDumpElements(elements, seen, elementLimit, camera, cameraOk, fogOfWar, fogOk, byNode, byId, gaps, census);
			if (elements.Count < elementLimit && !_placedScanAllCold)
				AppendMapObjectsByIdDumpElements(elements, seen, elementLimit, mapInstance, mapData, camera, cameraOk, fogOfWar, fogOk, byNode, byId, census);
			if (elements.Count < elementLimit)
				AppendMapDataObjectDumpElements(elements, seen, elementLimit, mapInstance, mapData, camera, cameraOk, fogOfWar, fogOk, byId, byNode, census);
			AppendMapMarkerDumpElements(elements, seen, elementLimit, mapInstance, mapData, camera, cameraOk, fogOfWar, fogOk, byNode, gaps, census);
			var liveHeroes = BuildWorldHeroDumpIndex(camera, cameraOk, fogOfWar, fogOk, gaps, census);
			AppendMapHeroDumpElements(
				elements,
				seen,
				elementLimit,
				mapInstance,
				camera,
				cameraOk,
				byId,
				byNode,
				liveHeroes,
				fogOfWar,
				fogOk,
				gaps,
				census);
			if (cameraOk && _mapNodeToWorldResolveAttempted && _cachedMapNodeToWorld == null)
			{
				gaps.Add(GapJson(
					"map_world_node_to_world_unresolved",
					"Map node→world method unresolved (" + string.Join("/", GameSymbols.AiDriverScreenDump.MapNodeToWorld.NameHints) + "); marker/object rects stay zero without live transforms.",
					true));
			}
			if (census.PlacedFound <= 0 && census.PlacedEmitted > 0)
			{
				gaps.Add(GapJson(
					"map_world_visual_instances_missing",
					"Catalog rows emitted, but Resources.FindObjectsOfTypeAll found 0 placed MonoBehaviour instances. "
					+ (census.PlacedTypeName ?? _placedScanNote ?? ""),
					false));
			}

			var emitted = Math.Max(0, elements.Count - before);
			if (emitted <= 0)
			{
				gaps.Add(GapJson(
					"map_world_catalog_empty",
					"Map/MapData resolved but emitted 0 map rows. census placedType='"
					+ (census.PlacedTypeName ?? "?")
					+ "' placedFound="
					+ census.PlacedFound.ToString(CultureInfo.InvariantCulture)
					+ " placedEmitted="
					+ census.PlacedEmitted.ToString(CultureInfo.InvariantCulture)
					+ " markersFound="
					+ census.MarkersFound.ToString(CultureInfo.InvariantCulture)
					+ " markersEmitted="
					+ census.MarkersEmitted.ToString(CultureInfo.InvariantCulture)
					+ " heroesFound="
					+ census.HeroesFound.ToString(CultureInfo.InvariantCulture)
					+ " heroesEmitted="
					+ census.HeroesEmitted.ToString(CultureInfo.InvariantCulture)
					+ " castMisses="
					+ census.PlacedCastMisses.ToString(CultureInfo.InvariantCulture)
					+ ".",
					true));
			}
			return emitted;
		}
		catch (Exception ex)
		{
			gaps.Add(GapJson(
				"map_world_dump_exception",
				"AppendMapWorldDumpElements failed: " + ex.GetType().Name + ": " + ex.Message,
				true));
			return 0;
		}
	}

	private static Camera ResolveAdventureMapDumpCamera(out string source)
	{
		source = null;
		if (_cachedAdventureDumpCamera)
		{
			source = _cachedAdventureDumpCameraSource ?? "cached";
			return _cachedAdventureDumpCamera;
		}

		if (Time.frameCount < _adventureDumpCameraMissUntilFrame)
			return null;

		// Prefer BhWorldCamera singleton → targetCamera_ (same owner as Map resolve). Camera.main is often null on adventure map.
		try
		{
			var cameraType = ResolveAiDumpHexType(
				GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeId,
				GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeHints);
			if (cameraType != null)
			{
				object worldCam = null;
				var singleton = GameMember.FindFirstMethodByNames(cameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraSingleton);
				if (singleton != null && singleton.IsStatic)
				{
					try { worldCam = singleton.Invoke(null, Array.Empty<object>()); }
					catch { worldCam = null; }
				}
				if (worldCam == null)
				{
					try
					{
						var found = Resources.FindObjectsOfTypeAll(Il2CppType.From(cameraType));
						if (found != null)
						{
							foreach (var obj in found)
							{
								if (!obj)
									continue;
								worldCam = obj;
								break;
							}
						}
					}
					catch { worldCam = null; }
				}

				if (worldCam != null)
				{
					var cam = ReadUnityCameraFromWorldCameraOwner(worldCam);
					if (cam == null)
					{
						var component = TryCastDumpComponent(worldCam as UnityObject);
						if (component != null)
						{
							cam = component.GetComponent<Camera>();
							if (cam == null)
								cam = component.GetComponentInChildren<Camera>(true);
						}
					}
					if (cam != null)
					{
						source = "BhWorldCamera.target";
						_cachedAdventureDumpCamera = cam;
						_cachedAdventureDumpCameraSource = source;
						return cam;
					}
				}
			}
		}
		catch { /* keep trying */ }

		try
		{
			if (Camera.main != null)
			{
				source = "Camera.main";
				_cachedAdventureDumpCamera = Camera.main;
				_cachedAdventureDumpCameraSource = source;
				return _cachedAdventureDumpCamera;
			}
		}
		catch { /* fall through */ }

		// Do not full-scan every Camera via FindObjectsOfTypeAll — that hitchs hard on adventure maps.
		_adventureDumpCameraMissUntilFrame = Time.frameCount + AdventureDumpCameraMissBackoffFrames;
		return null;
	}

	private static Camera ReadUnityCameraFromWorldCameraOwner(object worldCam)
	{
		if (worldCam == null)
			return null;
		foreach (var name in GameSymbols.AiDriverScreenDump.WorldCameraUnityCameraMembers)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var field = worldCam.GetType().GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (field != null && typeof(Camera).IsAssignableFrom(field.FieldType))
				{
					var cam = field.GetValue(worldCam) as Camera;
					if (cam)
						return cam;
				}
			}
			catch { /* next */ }
			try
			{
				var getter = worldCam.GetType().GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, Type.EmptyTypes, null);
				if (getter != null && typeof(Camera).IsAssignableFrom(getter.ReturnType))
				{
					var cam = getter.Invoke(worldCam, Array.Empty<object>()) as Camera;
					if (cam)
						return cam;
				}
			}
			catch { /* next */ }
		}
		return null;
	}

	private sealed class MapWorldCensus
	{
		internal string PlacedTypeName;
		internal int PlacedFound;
		internal int PlacedCastMisses;
		internal int PlacedEmitted;
		internal int MarkersFound;
		internal int MarkersEmitted;
		internal int HeroesFound;
		internal int HeroesEmitted;
		internal int HeroesLiveFound;
		internal int HeroesNodeResolved;
		internal int HeroesRectResolved;
	}

	private sealed class MapWorldScreenPoint
	{
		internal float X;
		internal float Y;
		internal float W;
		internal float H;
		internal string RectJson;
		internal bool OnScreen;
		internal bool? FogVisible;
		internal string Path;
		internal int InstanceId;
		internal int? Node;
		internal string ResolveSource;
	}

	private sealed class HeroLiveDumpPoint
	{
		internal int HeroId;
		internal int Node = -1;
		internal MapWorldScreenPoint Point;
		internal string UnityPath;
		internal string Source;
	}

	private static object _cachedAdventureFogOfWar;
	private static int _adventureFogMissUntilFrame = int.MinValue;
	private const int AdventureFogMissBackoffFrames = 120;

	private static bool TryResolveAdventureMapFogOfWar(object mapInstance, object mapData, out object fogOfWar, out string reason)
	{
		fogOfWar = null;
		reason = null;
		if (_cachedAdventureFogOfWar != null)
		{
			fogOfWar = _cachedAdventureFogOfWar;
			return true;
		}
		if (Time.frameCount < _adventureFogMissUntilFrame)
		{
			reason = "fog resolve miss backoff active";
			return false;
		}

		// Live-proven capture: native fog init/visibility/Side.fogData getter (AI driver Harmony cache).
		if (Homm3AiDriverFogCache.TryGetFogOfWar(out fogOfWar, out var cacheSource))
		{
			_cachedAdventureFogOfWar = fogOfWar;
			reason = null;
			return true;
		}

		// Live holder: ObjectPublicAbstract…Static_Data_0 → Data.sides → get_Side_0 / array[myIndex].fogData
		if (TryResolveFogFromSessionDataStatic(out fogOfWar, out reason))
		{
			_cachedAdventureFogOfWar = fogOfWar;
			Homm3AiDriverFogCache.Remember(fogOfWar, reason);
			reason = null;
			return true;
		}
		var dataPathReason = reason;

		// Data.Side init preseed registry (vanilla + custom) — Side.fogData is exact on registered sides.
		if (Homm3CustomFactionLawRuntime.TryGetAnyRegisteredDataSide(out var registeredSide, out var registeredIndex, out var registeredSource))
		{
			fogOfWar = ReadFirstMemberValue(registeredSide, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
			if (fogOfWar != null)
			{
				_cachedAdventureFogOfWar = fogOfWar;
				reason = null;
				return true;
			}
			dataPathReason += " || registeredSide[" + registeredIndex.ToString(CultureInfo.InvariantCulture)
				+ "] via " + registeredSource + " fogMiss members=" + SummarizeInstanceMemberNames(registeredSide);
		}
		else
			dataPathReason += " || no registered Data.Side in law runtime preseed";

		// Seeded from already-resolved Map/MapData (camera path) — Data static can be null while Map is live.
		if (TryFindFogDataFromSeeds(new[] { mapInstance, mapData }, out fogOfWar, out reason))
		{
			_cachedAdventureFogOfWar = fogOfWar;
			reason = null;
			return true;
		}
		var seedReason = reason;

		// Esquire billboard fog path: session.world.sides.(lookFor|current).data?.fogData / Side.fogData
		if (TryFindSessionRootWithWorld(out var session, out reason))
		{
			var world = ReadFirstMemberValue(session, GameSymbols.AdventureVisionLaws.SessionWorldMembers)
				?? ReadMemberValue(session, "world");
			if (world != null)
			{
				var sides = ReadFirstMemberValue(world, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
					?? ReadMemberValue(world, "sides");
				if (sides != null)
				{
					object side = ReadFirstMemberValue(sides, new[] { "lookFor", "get_lookFor", "<lookFor>k__BackingField" });
					if (side == null)
					{
						var currentSide = GameMember.FindFirstMethodByNames(
							sides.GetType(),
							Type.EmptyTypes,
							GameSymbols.AdventureVisionLaws.DataSidesCurrentSide);
						if (currentSide != null)
						{
							try { side = currentSide.Invoke(sides, Array.Empty<object>()); }
							catch { side = null; }
						}
					}
					if (side == null)
						side = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesCurrentSide.NameHints);
					if (side != null)
					{
						var nested = ReadFirstMemberValue(side, GameSymbols.AdventureVisionLaws.LookForDataMembers);
						if (nested != null)
							side = nested;
						fogOfWar = ReadFirstMemberValue(side, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
						if (fogOfWar != null)
						{
							_cachedAdventureFogOfWar = fogOfWar;
							reason = null;
							return true;
						}
					}
				}
			}
		}

		if (TryFindFogOfWarFromStaticHolders(out fogOfWar, out reason))
		{
			_cachedAdventureFogOfWar = fogOfWar;
			reason = null;
			return true;
		}

		var hudDiag = "";
		var hudType = ModActions.GetHexType("Hex.Session.Hud.BhHUDSession");
		if (hudType != null
			&& TryReadStaticMember(hudType, "field_Public_Static_BhHUDSession_0", out var hud)
			&& hud != null)
		{
			hudDiag = " || HUD.members=" + SummarizeInstanceMemberNames(hud);
			if (TryFindFogDataContainer(hud, 7, 200, out fogOfWar, out var hudPath))
			{
				_cachedAdventureFogOfWar = fogOfWar;
				reason = null;
				return true;
			}
			hudDiag += " fogBfsMiss pathBudget";
		}
		else
			hudDiag = " || HUD.static=null";

		reason = dataPathReason + " || " + seedReason + " || " + reason + hudDiag
			+ " || fogCache=miss (await DataFogOfWar init/visibility or Side.fogData)";
		// Short backoff: cache may fill on the next native fog read.
		_adventureFogMissUntilFrame = Time.frameCount + 15;
		return false;
	}

	private static bool TryFindFogDataFromSeeds(object[] seeds, out object fogOfWar, out string reason)
	{
		fogOfWar = null;
		reason = null;
		var inspected = 0;
		if (seeds != null)
		{
			for (var i = 0; i < seeds.Length; i++)
			{
				var seed = seeds[i];
				if (seed == null)
					continue;
				inspected++;
				if (TryFindFogDataContainer(seed, 6, 160, out fogOfWar, out var path))
				{
					reason = "seed[" + i.ToString(CultureInfo.InvariantCulture) + "]:" + (seed.GetType().FullName ?? seed.GetType().Name) + "->" + path;
					return true;
				}
			}
		}
		reason = "fogData BFS miss from Map/MapData seeds (inspected="
			+ inspected.ToString(CultureInfo.InvariantCulture) + ")";
		return false;
	}

	private static bool TryResolveFogFromSessionDataStatic(out object fogOfWar, out string reason)
	{
		fogOfWar = null;
		reason = null;
		var diag = new List<string>(6);

		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
			{
				diag.Add(typeName + "=typeMiss");
				continue;
			}

			object data = null;
			string dataSlot = null;
			try { RuntimeHelpers.RunClassConstructor(type.TypeHandle); }
			catch { /* Il2Cpp type init best-effort */ }
			foreach (var dataName in GameSymbols.AdventureVisionLaws.SessionDataMembers)
			{
				if (TryReadStaticMember(type, dataName, out data) && data != null)
				{
					dataSlot = dataName;
					break;
				}
				data = null;
			}
			if (data == null)
			{
				// Data static can be null while Map/ObjectsProperties static is live — seed fog BFS from those.
				foreach (var altName in new[] { "field_Private_Static_Map_0", "field_Private_Static_ObjectsProperties_0", "field_Private_Static_StartInfo_0" })
				{
					if (!TryReadStaticMember(type, altName, out var alt) || alt == null)
						continue;
					if (TryFindFogDataContainer(alt, 6, 160, out fogOfWar, out var altPath))
					{
						reason = (type.FullName ?? type.Name) + "." + altName + "->" + altPath;
						return true;
					}
					diag.Add((type.FullName ?? type.Name) + "." + altName + "=hit fogBfsMiss");
				}
				diag.Add((type.FullName ?? type.Name) + "=dataMiss{" + SummarizeStaticMemberNames(type) + "}");
				continue;
			}

			var sides = ReadFirstMemberValue(data, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
				?? ReadMemberValue(data, "sides");
			if (sides == null)
			{
				diag.Add((type.FullName ?? type.Name) + "." + dataSlot + "=sidesMiss");
				continue;
			}

			object side = null;
			// Live GE: DataSides.Method_Public_get_Side_0 is the local side (lookFor is stale).
			var currentSide = GameMember.FindFirstMethodByNames(
				sides.GetType(),
				Type.EmptyTypes,
				GameSymbols.AdventureVisionLaws.DataSidesCurrentSide);
			if (currentSide != null)
			{
				try { side = currentSide.Invoke(sides, Array.Empty<object>()); }
				catch { side = null; }
			}
			if (side == null)
				side = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesCurrentSide.NameHints);
			if (side == null)
			{
				// Fallback: sides.array[myIndex]
				var arr = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
				var myIndexObj = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesMyIndexMembers);
				if (arr != null && myIndexObj != null)
				{
					try
					{
						var myIndex = Convert.ToInt32(myIndexObj, CultureInfo.InvariantCulture);
						if (arr is System.Collections.IList list && myIndex >= 0 && myIndex < list.Count)
							side = list[myIndex];
						else
						{
							var getter = arr.GetType().GetMethod(
								"get_Item",
								BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
								null,
								new[] { typeof(int) },
								null);
							if (getter != null)
								side = getter.Invoke(arr, new object[] { myIndex });
						}
					}
					catch { side = null; }
				}
			}
			if (side != null)
			{
				var nested = ReadFirstMemberValue(side, GameSymbols.AdventureVisionLaws.LookForDataMembers);
				if (nested != null)
				{
					var nestedFog = ReadFirstMemberValue(nested, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
					if (nestedFog != null)
						side = nested;
				}
			}
			if (side == null)
			{
				diag.Add((type.FullName ?? type.Name) + ".sides=get_SideMiss members=" + SummarizeInstanceMemberNames(sides));
				continue;
			}

			fogOfWar = ReadFirstMemberValue(side, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
			if (fogOfWar == null)
			{
				diag.Add("side=" + (side.GetType().FullName ?? side.GetType().Name) + " fogMiss members=" + SummarizeInstanceMemberNames(side));
				continue;
			}

			reason = (type.FullName ?? type.Name) + "." + dataSlot + ".sides.fogData";
			return true;
		}

		reason = "session Data static fog path unresolved [" + string.Join(" | ", diag) + "]";
		return false;
	}

	private static string SummarizeInstanceMemberNames(object obj)
	{
		if (obj == null)
			return "";
		Type type;
		try { type = obj.GetType(); }
		catch { return ""; }
		var names = new List<string>(12);
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		try
		{
			foreach (var p in type.GetProperties(flags) ?? Array.Empty<PropertyInfo>())
			{
				if (p != null && p.CanRead && p.GetIndexParameters().Length == 0)
					names.Add("P:" + p.Name);
				if (names.Count >= 12)
					break;
			}
			foreach (var f in type.GetFields(flags) ?? Array.Empty<FieldInfo>())
			{
				if (f == null)
					continue;
				var n = f.Name ?? "";
				if (n.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal))
					continue;
				names.Add("F:" + n);
				if (names.Count >= 12)
					break;
			}
		}
		catch { }
		return string.Join(",", names);
	}

	private static bool TryFindSessionRootWithWorld(out object session, out string reason)
	{
		session = null;
		reason = null;

		// Fast path only: ModActions.GetHexType + static me/instance/current.
		// Do NOT call EsquirePikemanMapBillboardFogSync.TryGetAdventureSessionRoot here —
		// its first resolve can asm.GetTypes() the Hex assembly and hitch/hang the dump thread.
		if (TryFindSessionRootFromStaticHolders(out session, out var label))
		{
			reason = label;
			return true;
		}

		reason = string.IsNullOrEmpty(label)
			? "no adventure session root with world.sides via GetHexType holders"
			: label;
		return false;
	}

	private static bool TryFindFogOfWarFromStaticHolders(out object fogOfWar, out string reason)
	{
		fogOfWar = null;
		reason = null;
		var inspected = 0;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;
			foreach (var rootEntry in EnumerateStaticReferenceRoots(type))
			{
				if (rootEntry.Value == null)
					continue;
				inspected++;
				if (TryFindFogDataContainer(rootEntry.Value, 5, 96, out fogOfWar, out var path))
				{
					reason = (type.FullName ?? type.Name) + "." + rootEntry.Key + "->" + path;
					return true;
				}
			}
		}
		reason = "fogData BFS miss from static holders (inspectedRoots="
			+ inspected.ToString(CultureInfo.InvariantCulture) + ")";
		return false;
	}

	private static bool TryFindFogDataContainer(object root, int maxDepth, int maxNodes, out object fogOfWar, out string path)
	{
		fogOfWar = null;
		path = null;
		if (root == null || maxDepth < 0 || maxNodes <= 0)
			return false;

		var queue = new Queue<(object Value, string Path, int Depth)>();
		var visited = new HashSet<int>();
		queue.Enqueue((root, root.GetType().Name ?? "root", 0));
		var nodes = 0;
		while (queue.Count > 0 && nodes < maxNodes)
		{
			var (cur, curPath, depth) = queue.Dequeue();
			nodes++;
			if (cur == null)
				continue;
			var id = RuntimeHelpers.GetHashCode(cur);
			if (!visited.Add(id))
				continue;

			var fog = ReadFirstMemberValue(cur, GameSymbols.AdventureVisionLaws.SideFogDataMembers);
			if (fog != null)
			{
				fogOfWar = fog;
				path = curPath + ".fogData";
				return true;
			}

			if (depth >= maxDepth)
				continue;
			Type type;
			try { type = cur.GetType(); }
			catch { continue; }
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			PropertyInfo[] props = null;
			FieldInfo[] fields = null;
			try { props = type.GetProperties(flags); } catch { props = null; }
			try { fields = type.GetFields(flags); } catch { fields = null; }
			if (props != null)
			{
				for (var i = 0; i < props.Length && queue.Count + nodes < maxNodes; i++)
				{
					var p = props[i];
					if (p == null || !p.CanRead || p.GetIndexParameters().Length == 0)
						continue;
					var pt = p.PropertyType;
					if (pt.IsPrimitive || pt == typeof(string) || pt.IsEnum)
						continue;
					var pn = p.Name ?? "";
					if (pn.StartsWith("NativeMethodInfoPtr_", StringComparison.Ordinal)
						|| pn.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal))
						continue;
					object child = null;
					try { child = p.GetValue(cur, null); } catch { child = null; }
					if (child != null)
						queue.Enqueue((child, curPath + "." + p.Name, depth + 1));
				}
			}
			if (fields == null)
				continue;
			for (var i = 0; i < fields.Length && queue.Count + nodes < maxNodes; i++)
			{
				var f = fields[i];
				if (f == null)
					continue;
				var ft = f.FieldType;
				if (ft.IsPrimitive || ft == typeof(string) || ft.IsEnum)
					continue;
				var fn = f.Name ?? "";
				if (fn.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal)
					|| fn.StartsWith("NativeMethodInfoPtr_", StringComparison.Ordinal))
					continue;
				object child = null;
				try { child = f.GetValue(cur); } catch { child = null; }
				if (child != null)
					queue.Enqueue((child, curPath + "." + f.Name, depth + 1));
			}
		}
		return false;
	}

	private static bool TryFindSessionRootFromStaticHolders(out object session, out string label)
	{
		session = null;
		label = null;

		// IL2CPP: do not use Assembly.GetType for Hex types — use ModActions.GetHexType (live interop map).
		var seenTypes = 0;
		var triedStatics = 0;
		var diag = new List<string>(8);
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;
			seenTypes++;
			diag.Add((type.FullName ?? type.Name) + "{statics=" + SummarizeStaticMemberNames(type) + "}");

			foreach (var rootEntry in EnumerateStaticReferenceRoots(type))
			{
				triedStatics++;
				var root = rootEntry.Value;
				if (root == null)
					continue;
				var candidates = new[] { root, UnwrapSessionUntilHasWorld(root, 6) };
				foreach (var candidate in candidates)
				{
					if (candidate == null)
						continue;
					if (!TryGetWorldSidesFromSession(candidate, out _))
						continue;
					session = candidate;
					label = (type.FullName ?? type.Name) + "." + rootEntry.Key;
					return true;
				}

				if (TryFindWorldSidesContainer(root, 4, 64, out var found, out var path))
				{
					session = found;
					label = (type.FullName ?? type.Name) + "." + rootEntry.Key + "->" + path;
					return true;
				}
			}
		}

		label = "GetHexType holders seenTypes=" + seenTypes.ToString(CultureInfo.InvariantCulture)
			+ " staticHits=" + triedStatics.ToString(CultureInfo.InvariantCulture)
			+ (diag.Count > 0 ? " detail=[" + string.Join("; ", diag) + "]" : "");
		return false;
	}

	private static string SummarizeStaticMemberNames(Type type)
	{
		if (type == null)
			return "";
		var names = new List<string>(12);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		try
		{
			foreach (var p in type.GetProperties(flags) ?? Array.Empty<PropertyInfo>())
			{
				if (p != null && p.CanRead && p.GetIndexParameters().Length == 0)
					names.Add("P:" + p.Name);
				if (names.Count >= 10)
					break;
			}
			foreach (var f in type.GetFields(flags) ?? Array.Empty<FieldInfo>())
			{
				if (f != null)
					names.Add("F:" + f.Name);
				if (names.Count >= 10)
					break;
			}
		}
		catch { }
		return string.Join(",", names);
	}

	private static IEnumerable<KeyValuePair<string, object>> EnumerateStaticReferenceRoots(Type type)
	{
		if (type == null)
			yield break;

		// Prefer known slots first.
		foreach (var staticName in GameSymbols.AdventureVisionLaws.SessionHolderStaticNames)
		{
			if (TryReadStaticMember(type, staticName, out var root) && root != null)
				yield return new KeyValuePair<string, object>(staticName, root);
		}

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			PropertyInfo[] props = null;
			FieldInfo[] fields = null;
			try { props = cur.GetProperties(flags); } catch { props = null; }
			try { fields = cur.GetFields(flags); } catch { fields = null; }
			if (props != null)
			{
				foreach (var p in props)
				{
					if (p == null || !p.CanRead || p.GetIndexParameters().Length != 0)
						continue;
					var pt = p.PropertyType;
					if (pt.IsPrimitive || pt == typeof(string) || pt.IsEnum)
						continue;
					object value = null;
					try { value = p.GetValue(null, null); } catch { value = null; }
					if (value != null)
						yield return new KeyValuePair<string, object>(p.Name, value);
				}
			}
			if (fields == null)
				continue;
			foreach (var f in fields)
			{
				if (f == null)
					continue;
				var ft = f.FieldType;
				if (ft.IsPrimitive || ft == typeof(string) || ft.IsEnum)
					continue;
				object value = null;
				try { value = f.GetValue(null); } catch { value = null; }
				if (value != null)
					yield return new KeyValuePair<string, object>(f.Name, value);
			}
		}
	}

	private static bool TryGetWorldSidesFromSession(object sessionObj, out object sides)
	{
		sides = null;
		if (sessionObj == null)
			return false;
		var world = ReadFirstMemberValue(sessionObj, GameSymbols.AdventureVisionLaws.SessionWorldMembers)
			?? ReadMemberValue(sessionObj, "world");
		if (world == null)
			return false;
		sides = ReadFirstMemberValue(world, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
			?? ReadMemberValue(world, "sides");
		return sides != null;
	}

	private static bool TryFindWorldSidesContainer(object root, int maxDepth, int maxNodes, out object found, out string path)
	{
		found = null;
		path = null;
		if (root == null || maxDepth < 0 || maxNodes <= 0)
			return false;

		var queue = new Queue<(object Value, string Path, int Depth)>();
		var visited = new HashSet<int>();
		queue.Enqueue((root, root.GetType().Name ?? "root", 0));
		var nodes = 0;
		while (queue.Count > 0 && nodes < maxNodes)
		{
			var (cur, curPath, depth) = queue.Dequeue();
			nodes++;
			if (cur == null)
				continue;
			var id = RuntimeHelpers.GetHashCode(cur);
			if (!visited.Add(id))
				continue;
			if (TryGetWorldSidesFromSession(cur, out _))
			{
				found = cur;
				path = curPath;
				return true;
			}
			if (depth >= maxDepth)
				continue;
			Type type;
			try { type = cur.GetType(); }
			catch { continue; }
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			PropertyInfo[] props = null;
			FieldInfo[] fields = null;
			try { props = type.GetProperties(flags); } catch { props = null; }
			try { fields = type.GetFields(flags); } catch { fields = null; }
			if (props != null)
			{
				for (var i = 0; i < props.Length && queue.Count + nodes < maxNodes; i++)
				{
					var p = props[i];
					if (p == null || !p.CanRead || p.GetIndexParameters().Length != 0)
						continue;
					var pt = p.PropertyType;
					if (pt.IsPrimitive || pt == typeof(string) || pt.IsEnum)
						continue;
					object child = null;
					try { child = p.GetValue(cur, null); } catch { child = null; }
					if (child != null)
						queue.Enqueue((child, curPath + "." + p.Name, depth + 1));
				}
			}
			if (fields == null)
				continue;
			for (var i = 0; i < fields.Length && queue.Count + nodes < maxNodes; i++)
			{
				var f = fields[i];
				if (f == null)
					continue;
				var ft = f.FieldType;
				if (ft.IsPrimitive || ft == typeof(string) || ft.IsEnum)
					continue;
				object child = null;
				try { child = f.GetValue(cur); } catch { child = null; }
				if (child != null)
					queue.Enqueue((child, curPath + "." + f.Name, depth + 1));
			}
		}
		return false;
	}

	private static bool TryReadStaticMember(Type type, string name, out object value)
	{
		value = null;
		if (type == null || string.IsNullOrEmpty(name))
			return false;
		// Match Esquire: walk DeclaredOnly base chain for static prop/field/get_*.
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			const BindingFlags decl = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
			try
			{
				var prop = cur.GetProperty(name, decl);
				if (prop != null && prop.CanRead && prop.GetIndexParameters().Length == 0)
				{
					value = prop.GetValue(null, null);
					if (value != null)
						return true;
				}
			}
			catch { }
			try
			{
				var field = cur.GetField(name, decl);
				if (field != null)
				{
					value = field.GetValue(null);
					if (value != null)
						return true;
				}
			}
			catch { }
			try
			{
				var getter = cur.GetMethod("get_" + name, decl, null, Type.EmptyTypes, null);
				if (getter != null && getter.ReturnType != typeof(void))
				{
					value = getter.Invoke(null, null);
					if (value != null)
						return true;
				}
			}
			catch { }
		}
		return false;
	}

	private static object UnwrapSessionUntilHasWorld(object root, int maxDepth)
	{
		var cur = root;
		for (var i = 0; i < maxDepth && cur != null; i++)
		{
			if (ReadFirstMemberValue(cur, GameSymbols.AdventureVisionLaws.SessionWorldMembers) != null)
				return cur;
			var next = ReadMemberValue(cur, "me") ?? ReadMemberValue(cur, "instance");
			if (ReferenceEquals(next, cur))
				break;
			cur = next;
		}
		return null;
	}

	private static void ApplyFogVisibilityToPoint(object fogOfWar, bool fogOk, int? node, MapWorldScreenPoint point)
	{
		if (point == null)
			return;
		// Fail closed: camera frustum alone must not mark fog-hidden (or unproven) tiles clickable.
		if (!fogOk || fogOfWar == null)
		{
			point.OnScreen = false;
			return;
		}
		if (!node.HasValue || node.Value < 0)
		{
			point.OnScreen = false;
			return;
		}
		if (!Homm3AdventureVisionNativeAdapter.TryReadFogVisibility(fogOfWar, node.Value, out var visible, out _))
		{
			// Direct visibilityMap[node] fallback when method invoke fails.
			if (!TryReadFogVisibilityMap(fogOfWar, node.Value, out visible))
			{
				point.OnScreen = false;
				return;
			}
		}
		point.FogVisible = visible;
		if (!visible)
			point.OnScreen = false;
	}

	private static bool TryReadFogVisibilityMap(object fogOfWar, int node, out bool visible)
	{
		visible = false;
		var map = ReadFirstMemberValue(fogOfWar, GameSymbols.AdventureVisionLaws.DataFogVisibilityMapMembers);
		if (map == null || node < 0)
			return false;
		try
		{
			if (map is bool[] arr)
			{
				if (node >= arr.Length)
					return false;
				visible = arr[node];
				return true;
			}
			if (map is System.Collections.IList list)
			{
				if (node >= list.Count)
					return false;
				visible = Convert.ToBoolean(list[node], CultureInfo.InvariantCulture);
				return true;
			}
			var lenObj = ReadMemberValue(map, "Length") ?? ReadMemberValue(map, "Count");
			var len = 0;
			if (lenObj != null)
				len = Convert.ToInt32(lenObj, CultureInfo.InvariantCulture);
			if (len > 0 && node >= len)
				return false;
			var getter = map.GetType().GetMethod(
				"get_Item",
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
				null,
				new[] { typeof(int) },
				null);
			if (getter == null)
				return false;
			visible = Convert.ToBoolean(getter.Invoke(map, new object[] { node }), CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryResolveAdventureMapContext(out object mapInstance, out object mapData, out string reason)
	{
		mapInstance = null;
		mapData = null;
		reason = null;

		if (TryResolveMapFromWorldCamera(out mapInstance, out var cameraReason))
		{
			if (TryGetMapDataFromMap(mapInstance, out mapData))
				return true;
			reason = "world_camera_map_data_unresolved";
		}
		else
			reason = cameraReason;

		if (Homm3HomecomingWaterPresentationOverlay.TryReadCurrentMapContext(out mapData, out _, out var overlayReason))
		{
			if (mapInstance == null)
				TryResolveMapFromWorldCamera(out mapInstance, out _);
			return true;
		}

		reason = reason ?? overlayReason ?? "map_context_unresolved";
		mapData = null;
		return false;
	}

	private static bool TryResolveMapFromWorldCamera(out object mapInstance, out string reason)
	{
		mapInstance = null;
		reason = null;
		var cameraType = ResolveAiDumpHexType(
			GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeId,
			GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeHints);
		if (cameraType == null)
		{
			reason = "world_camera_type_unresolved";
			return false;
		}

		var singleton = GameMember.FindFirstMethodByNames(cameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraSingleton);
		var currentMap = GameMember.FindFirstMethodByNames(cameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraCurrentMap);
		if (currentMap == null || !typeof(Map).IsAssignableFrom(currentMap.ReturnType))
		{
			reason = "world_camera_map_getters_unresolved";
			return false;
		}

		object camera = null;
		if (singleton != null && singleton.IsStatic)
		{
			try { camera = singleton.Invoke(null, Array.Empty<object>()); }
			catch (Exception ex) { reason = "world_camera_singleton_invoke_failed " + ex.Message; }
		}
		if (camera == null)
		{
			try
			{
				var found = Resources.FindObjectsOfTypeAll(Il2CppType.From(cameraType));
				if (found != null)
				{
					foreach (var obj in found)
					{
						if (obj)
						{
							camera = obj;
							break;
						}
					}
				}
			}
			catch (Exception ex)
			{
				reason = "world_camera_scan_failed " + ex.Message;
				return false;
			}
		}
		if (camera == null)
		{
			if (reason == null)
				reason = "world_camera_instance_unresolved";
			return false;
		}

		try
		{
			mapInstance = currentMap.Invoke(camera, Array.Empty<object>());
			if (mapInstance == null)
			{
				reason = "world_camera_current_map_null";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "world_camera_current_map_invoke_failed " + ex.Message;
			return false;
		}
	}

	private static bool TryGetMapDataFromMap(object mapInstance, out object mapData)
	{
		mapData = null;
		if (mapInstance == null)
			return false;
		mapData = ReadFirstMemberValue(mapInstance, new[] { "mapData_", "mapData", "<mapData>k__BackingField", "_mapData" });
		if (mapData != null)
			return true;
		try
		{
			var getter = GameMember.FindFirstMethodByNames(
				mapInstance.GetType(),
				Type.EmptyTypes,
				GameSymbols.HomecomingLayerViewToggle.MapData);
			if (getter != null)
				mapData = getter.Invoke(mapInstance, Array.Empty<object>());
		}
		catch
		{
			mapData = null;
		}
		return mapData != null;
	}

	private static void AppendPlacedObjectDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		Camera camera,
		bool cameraOk,
		object fogOfWar,
		bool fogOk,
		Dictionary<int, MapWorldScreenPoint> byNode,
		Dictionary<int, MapWorldScreenPoint> byId,
		List<string> gaps,
		MapWorldCensus census)
	{
		if (!TryFindPlacedObjectInstances(out var placedType, out var found, out var typeScanNote))
		{
			gaps.Add(GapJson(
				"map_world_placed_type_unresolved",
				"Placed-object type/instances unresolved for screen_dump ("
				+ string.Join("/", GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints)
				+ "). "
				+ (typeScanNote ?? ""),
				true));
			census.PlacedTypeName = null;
			return;
		}

		census.PlacedTypeName = (placedType?.FullName ?? placedType?.Name ?? "?") + (typeScanNote != null ? " " + typeScanNote : "");
		if (found == null || found.Length == 0)
			return;

		census.PlacedFound = found.Length;
		Array.Sort(found, (a, b) =>
		{
			var left = DescribeUnityObjectPath(a);
			var right = DescribeUnityObjectPath(b);
			return string.Compare(left, right, StringComparison.Ordinal);
		});

		for (var i = 0; i < found.Length && elements.Count < elementLimit; i++)
		{
			var obj = found[i];
			if (!obj)
				continue;

			var component = TryCastDumpComponent(obj);
			if (component == null || !component.gameObject)
			{
				census.PlacedCastMisses++;
				continue;
			}

			var go = component.gameObject;
			// Prefab assets / inactive hierarchy still catalog; Visible reflects live activity.
			var live = go.activeInHierarchy;
			var instanceId = go.GetInstanceID();
			if (!seen.Add(instanceId))
				continue;

			var sid = ReadFirstStringMember(obj, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields);
			if (string.IsNullOrWhiteSpace(sid))
				sid = ReadFirstStringMember(component, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields);
			var objectId = Homm3MapObjectPropCityResolver.TryGetIntMember(obj, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields)
				?? Homm3MapObjectPropCityResolver.TryGetIntMember(component, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields);
			var node = Homm3MapObjectPropCityResolver.TryGetIntMember(obj, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields)
				?? Homm3MapObjectPropCityResolver.TryGetIntMember(component, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
			var path = UnityPath(component.transform);
			var label = !string.IsNullOrWhiteSpace(sid)
				? sid.Trim()
				: (objectId.HasValue ? "id=" + objectId.Value.ToString(CultureInfo.InvariantCulture) : (go.name ?? "map_object"));

			BuildWorldPointRect(component.transform.position, camera, cameraOk, out var point);
			point.Path = path;
			point.InstanceId = instanceId;
			ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
			if (live)
			{
				if (node.HasValue && node.Value >= 0 && !byNode.ContainsKey(node.Value))
					byNode[node.Value] = point;
				if (objectId.HasValue && objectId.Value > 0 && !byId.ContainsKey(objectId.Value))
					byId[objectId.Value] = point;
			}

			var fingerprint = "map_object|node="
				+ (node.HasValue ? node.Value.ToString(CultureInfo.InvariantCulture) : "?")
				+ "|id="
				+ (objectId.HasValue ? objectId.Value.ToString(CultureInfo.InvariantCulture) : "?")
				+ "|"
				+ path
				+ "|"
				+ instanceId.ToString(CultureInfo.InvariantCulture);

			elements.Add(new DumpElementRecord
			{
				Id = StableElementId("map-object", instanceId, fingerprint),
				Kind = "map_object",
				Role = "map_object",
				Name = go.name ?? "",
				Path = path,
				Label = label,
				Sid = string.IsNullOrWhiteSpace(sid) ? null : sid.Trim(),
				RectJson = point.RectJson,
				Visible = live && point.OnScreen,
				Enabled = live,
				Interactable = live,
				OnScreen = live && point.OnScreen,
				FogVisible = point.FogVisible,
				FingerprintValue = fingerprint,
				InstanceId = instanceId,
				RectX = point.X,
				RectY = point.Y,
				RectW = point.W,
				RectH = point.H
			});
			census.PlacedEmitted++;
		}
	}

	private static bool TryFindPlacedObjectInstances(out Type placedType, out UnityObject[] found, out string note)
	{
		placedType = null;
		found = null;
		note = null;

		if (_placedScanCompleted && _placedScanAllCold)
		{
			placedType = _placedScanHotType;
			found = Array.Empty<UnityObject>();
			note = "cachedCold " + (_placedScanNote ?? "");
			return placedType != null || !string.IsNullOrEmpty(_placedScanNote);
		}

		if (_placedScanCompleted && _placedScanHotType != null)
		{
			placedType = _placedScanHotType;
			try { found = Resources.FindObjectsOfTypeAll(Il2CppType.From(placedType)) ?? Array.Empty<UnityObject>(); }
			catch { found = Array.Empty<UnityObject>(); }
			note = "cachedHotType=" + placedType.Name + " count=" + found.Length.ToString(CultureInfo.InvariantCulture);
			if (found.Length == 0)
			{
				_placedScanAllCold = true;
				_placedScanHotType = null;
			}
			return true;
		}

		var hints = GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints;
		var scanBits = new List<string>();
		UnityObject[] best = null;
		Type bestType = null;

		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			var type = ResolveAiDumpHexTypeHint(hint);
			if (type == null)
			{
				scanBits.Add(hint + "=typeMiss");
				continue;
			}

			UnityObject[] instances = null;
			try { instances = Resources.FindObjectsOfTypeAll(Il2CppType.From(type)); }
			catch (Exception ex)
			{
				scanBits.Add(hint + "=scanFail:" + ex.GetType().Name);
				continue;
			}

			var count = instances == null ? 0 : instances.Length;
			scanBits.Add(hint + "=" + type.Name + ":" + count.ToString(CultureInfo.InvariantCulture));
			if (count > (best == null ? -1 : best.Length))
			{
				best = instances;
				bestType = type;
			}
		}

		_placedScanCompleted = true;
		_placedScanNote = "scan=[" + string.Join(",", scanBits) + "]";
		if (bestType == null || best == null || best.Length == 0)
		{
			_placedScanAllCold = true;
			_placedScanHotType = null;
			var fallback = GameMember.FindPlacedObjectType(
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
				hints,
				hint => ResolveAiDumpHexTypeHint(hint));
			placedType = fallback;
			found = Array.Empty<UnityObject>();
			note = "cold " + _placedScanNote;
			return fallback != null || scanBits.Count > 0;
		}

		_placedScanAllCold = false;
		_placedScanHotType = bestType;
		placedType = bestType;
		found = best;
		note = "hot " + _placedScanNote;
		return true;
	}

	private static Component TryCastDumpComponent(UnityObject obj)
	{
		if (!obj)
			return null;
		if (obj is Component direct)
			return direct;
		try
		{
			if (obj is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase il2)
				return il2.TryCast<Component>();
		}
		catch
		{
			return null;
		}
		return null;
	}

	private static void AppendMapObjectsByIdDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		object mapInstance,
		object mapData,
		Camera camera,
		bool cameraOk,
		object fogOfWar,
		bool fogOk,
		Dictionary<int, MapWorldScreenPoint> byNode,
		Dictionary<int, MapWorldScreenPoint> byId,
		MapWorldCensus census)
	{
		if (mapInstance == null || mapData == null || elements.Count >= elementLimit)
			return;

		var objectsTable = ReadFirstMemberValue(mapInstance, GameSymbols.CampaignSpawnParity.MapObjectsMemberHints);
		if (objectsTable == null)
			return;

		MethodInfo byIdMethod = null;
		foreach (var methodName in GameSymbols.CampaignSpawnParity.MapObjectsByIdMethodHints)
		{
			try
			{
				byIdMethod = objectsTable.GetType().GetMethod(
					methodName,
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					new[] { typeof(int) },
					null);
			}
			catch { byIdMethod = null; }
			if (byIdMethod != null)
				break;
		}
		if (byIdMethod == null)
		{
			// Fail-closed diagnostic once per dump path via census note on caller; keep silent here except no-op.
			return;
		}

		var objectRows = ReadFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (objectRows == null)
			return;

		var index = 0;
		var projected = 0;
		foreach (var row in EnumerateIl2CppListForDump(objectRows))
		{
			if (elements.Count >= elementLimit || projected >= MapWorldByIdProjectBudget)
				break;
			if (row == null)
			{
				index++;
				continue;
			}

			var sid = ReadFirstStringMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsSidFields);
			foreach (var objectId in ReadMapDataObjectIds(row))
			{
				if (elements.Count >= elementLimit || projected >= MapWorldByIdProjectBudget)
					break;
				if (objectId <= 0 || byId.ContainsKey(objectId))
					continue;

				object placed = null;
				try { placed = byIdMethod.Invoke(objectsTable, new object[] { objectId }); }
				catch { placed = null; }
				if (placed == null)
					continue;

				var root = TryGetPlacedObjectRootTransform(placed);
				if (root == null)
					continue;

				var go = root.gameObject;
				var instanceId = go ? go.GetInstanceID() : StableHash("byid|" + objectId).GetHashCode();
				if (!seen.Add(instanceId ^ unchecked((int)0x42594944))) // 'BYID'
					continue;

				var node = Homm3MapObjectPropCityResolver.TryGetIntMember(placed, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
				var liveSid = ReadFirstStringMember(placed, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields);
				if (string.IsNullOrWhiteSpace(liveSid))
					liveSid = sid;
				var label = !string.IsNullOrWhiteSpace(liveSid)
					? liveSid.Trim()
					: "id=" + objectId.ToString(CultureInfo.InvariantCulture);
				var path = go ? UnityPath(root) : ("Map.objects.ById/" + objectId.ToString(CultureInfo.InvariantCulture));

				BuildWorldPointRect(root.position, camera, cameraOk, out var point);
				point.Path = path;
				point.InstanceId = instanceId;
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
				if (node.HasValue && node.Value >= 0 && !byNode.ContainsKey(node.Value))
					byNode[node.Value] = point;
				if (!byId.ContainsKey(objectId))
					byId[objectId] = point;

				var fingerprint = "map_object|byid|id="
					+ objectId.ToString(CultureInfo.InvariantCulture)
					+ "|sid="
					+ (liveSid ?? "")
					+ "|"
					+ path;

				elements.Add(new DumpElementRecord
				{
					Id = StableElementId("map-object-byid", instanceId, fingerprint),
					Kind = "map_object",
					Role = "map_object",
					Name = go ? (go.name ?? "") : label,
					Path = path,
					Label = label,
					Sid = string.IsNullOrWhiteSpace(liveSid) ? null : liveSid.Trim(),
					RectJson = point.RectJson,
					Visible = point.OnScreen,
					Enabled = true,
					Interactable = true,
					OnScreen = point.OnScreen,
					FogVisible = point.FogVisible,
					FingerprintValue = fingerprint,
					InstanceId = instanceId,
					RectX = point.X,
					RectY = point.Y,
					RectW = point.W,
					RectH = point.H
				});
				census.PlacedEmitted++;
				projected++;
			}
			index++;
		}
	}

	private static Transform TryGetPlacedObjectRootTransform(object placed)
	{
		if (placed == null)
			return null;
		var component = TryCastDumpComponent(placed as UnityObject);
		if (component != null && component.transform)
			return component.transform;

		var rootGo = ReadFirstMemberValue(placed, GameSymbols.CustomTownMapBillboard.RootGameObjectFields) as GameObject;
		if (rootGo)
			return rootGo.transform;
		var rootTf = ReadFirstMemberValue(placed, GameSymbols.CustomTownMapBillboard.RootTransformFields) as Transform;
		if (rootTf)
			return rootTf;

		try
		{
			var goGetter = GameMember.FindFirstMethodByNames(
				placed.GetType(),
				Type.EmptyTypes,
				GameSymbols.CustomTownMapBillboard.RootGameObjectGetter);
			if (goGetter != null)
			{
				rootGo = goGetter.Invoke(placed, Array.Empty<object>()) as GameObject;
				if (rootGo)
					return rootGo.transform;
			}
		}
		catch { /* keep trying */ }

		try
		{
			var tfGetter = GameMember.FindFirstMethodByNames(
				placed.GetType(),
				Type.EmptyTypes,
				GameSymbols.CustomTownMapBillboard.RootTransformGetter);
			if (tfGetter != null)
			{
				rootTf = tfGetter.Invoke(placed, Array.Empty<object>()) as Transform;
				if (rootTf)
					return rootTf;
			}
		}
		catch { /* keep trying */ }

		return null;
	}

	private static List<int> ReadMapDataObjectIds(object row)
	{
		return ReadMapDataIntArrayMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsIdsFields);
	}

	private static List<int> ReadMapDataObjectNodes(object row)
	{
		return ReadMapDataIntArrayMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsNodesFields);
	}

	private static List<int> ReadMapDataIntArrayMember(object row, string[] fieldHints)
	{
		var values = new List<int>();
		var raw = ReadFirstMemberValue(row, fieldHints);
		if (raw == null)
			return values;
		try
		{
			if (raw is Array arr)
			{
				for (var i = 0; i < arr.Length; i++)
				{
					try { values.Add(Convert.ToInt32(arr.GetValue(i), CultureInfo.InvariantCulture)); }
					catch { }
				}
				return values;
			}

			foreach (var item in EnumerateIl2CppListForDump(raw))
			{
				try { values.Add(Convert.ToInt32(item, CultureInfo.InvariantCulture)); }
				catch { }
			}
			if (values.Count > 0)
				return values;

			var lenObj = ReadMemberValue(raw, "Length") ?? ReadMemberValue(raw, "Count");
			var len = 0;
			try { if (lenObj != null) len = Convert.ToInt32(lenObj, CultureInfo.InvariantCulture); }
			catch { len = 0; }
			for (var i = 0; i < len; i++)
			{
				object item = null;
				try
				{
					var getter = raw.GetType().GetMethod(
						"get_Item",
						BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
						null,
						new[] { typeof(int) },
						null);
					if (getter != null)
						item = getter.Invoke(raw, new object[] { i });
				}
				catch { item = null; }
				if (item == null)
					continue;
				try { values.Add(Convert.ToInt32(item, CultureInfo.InvariantCulture)); }
				catch { }
			}
		}
		catch
		{
			values.Clear();
		}
		return values;
	}

	private static MethodInfo _cachedMapNodeToWorld;
	private static bool _mapNodeToWorldResolveAttempted;

	private static bool TryProjectMapNode(
		object mapInstance,
		int node,
		Camera camera,
		bool cameraOk,
		out MapWorldScreenPoint point)
	{
		point = null;
		if (mapInstance == null || node < 0 || !cameraOk || camera == null)
			return false;

		if (!_mapNodeToWorldResolveAttempted)
		{
			_mapNodeToWorldResolveAttempted = true;
			_cachedMapNodeToWorld = GameMember.FindFirstMethodByNames(
				mapInstance.GetType(),
				new[] { typeof(int) },
				GameSymbols.AiDriverScreenDump.MapNodeToWorld);
			if (_cachedMapNodeToWorld != null
			    && _cachedMapNodeToWorld.ReturnType != typeof(Vector3)
			    && _cachedMapNodeToWorld.ReturnType != typeof(Vector3).MakeByRefType())
			{
				// Accept UnityEngine.Vector3 only.
				if (_cachedMapNodeToWorld.ReturnType.FullName != "UnityEngine.Vector3")
					_cachedMapNodeToWorld = null;
			}
		}

		if (_cachedMapNodeToWorld == null)
			return false;

		object result;
		try { result = _cachedMapNodeToWorld.Invoke(mapInstance, new object[] { node }); }
		catch { return false; }
		if (result == null)
			return false;

		Vector3 world;
		try { world = (Vector3)result; }
		catch { return false; }

		BuildWorldPointRect(world, camera, true, out point);
		return point != null && point.W > 0f;
	}

	private static void RememberProjectedPoint(
		MapWorldScreenPoint point,
		IList<int> objectIds,
		IList<int> nodes,
		Dictionary<int, MapWorldScreenPoint> byId,
		Dictionary<int, MapWorldScreenPoint> byNode)
	{
		if (point == null)
			return;
		if (objectIds != null && byId != null)
		{
			for (var i = 0; i < objectIds.Count; i++)
			{
				var id = objectIds[i];
				if (id > 0 && !byId.ContainsKey(id))
					byId[id] = point;
			}
		}
		if (nodes != null && byNode != null)
		{
			for (var i = 0; i < nodes.Count; i++)
			{
				var node = nodes[i];
				if (node >= 0 && !byNode.ContainsKey(node))
					byNode[node] = point;
			}
		}
	}

	private static void AppendMapDataObjectDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		object mapInstance,
		object mapData,
		Camera camera,
		bool cameraOk,
		object fogOfWar,
		bool fogOk,
		Dictionary<int, MapWorldScreenPoint> byId,
		Dictionary<int, MapWorldScreenPoint> byNode,
		MapWorldCensus census)
	{
		var objects = ReadFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (objects == null)
			return;

		var index = 0;
		foreach (var row in EnumerateIl2CppListForDump(objects))
		{
			if (elements.Count >= elementLimit)
				break;
			if (row == null)
			{
				index++;
				continue;
			}

			var sid = ReadFirstStringMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsSidFields);
			var idList = ReadMapDataObjectIds(row);
			var nodeList = ReadMapDataObjectNodes(row);
			// One catalog row per MapData.objects entry (sid group), not one row per id.
			// Expanding every id previously exploded dumps to hundreds of near-duplicates.
			var objectId = idList.Count > 0 ? idList[0] : -1;
			MapWorldScreenPoint point = null;
			for (var i = 0; i < idList.Count; i++)
			{
				if (idList[i] > 0 && byId.TryGetValue(idList[i], out point) && point != null && point.W > 0f)
					break;
				point = null;
			}
			for (var i = 0; point == null && i < nodeList.Count; i++)
			{
				if (nodeList[i] >= 0 && byNode.TryGetValue(nodeList[i], out point) && point != null && point.W > 0f)
					break;
				point = null;
			}

			// Already projected by placed/ById — keep maps warm, skip duplicate MapData catalog row.
			if (point != null && point.W > 0f)
			{
				RememberProjectedPoint(point, idList, nodeList, byId, byNode);
				index++;
				continue;
			}

			// Prefer node→world when no live transform is cached (placed FindObjectsOfTypeAll often cold).
			if (cameraOk)
			{
				for (var i = 0; i < nodeList.Count; i++)
				{
					if (nodeList[i] < 0)
						continue;
					if (TryProjectMapNode(mapInstance, nodeList[i], camera, cameraOk, out var projected) && projected != null && projected.W > 0f)
					{
						point = projected;
						break;
					}
				}
			}

			if (point != null && point.W > 0f)
			{
				var fogNode = nodeList.Count > 0 ? (int?)nodeList[0] : null;
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, fogNode, point);
				RememberProjectedPoint(point, idList, nodeList, byId, byNode);
			}

			var label = !string.IsNullOrWhiteSpace(sid)
				? sid.Trim()
				: (objectId > 0 ? "id=" + objectId.ToString(CultureInfo.InvariantCulture) : "map_object");
			var path = "MapData.objects[" + index.ToString(CultureInfo.InvariantCulture) + "]"
				+ (objectId > 0 ? "/id=" + objectId.ToString(CultureInfo.InvariantCulture) : "")
				+ (nodeList.Count > 0 && nodeList[0] >= 0 ? "/node=" + nodeList[0].ToString(CultureInfo.InvariantCulture) : "")
				+ (idList.Count > 1 ? "/ids=" + idList.Count.ToString(CultureInfo.InvariantCulture) : "");
			var syntheticId = StableHash(path + "|" + (sid ?? "")).GetHashCode();
			if (!seen.Add(syntheticId ^ unchecked((int)0x4D444F42))) // 'MDOB'
			{
				index++;
				continue;
			}

			if (point == null)
			{
				point = new MapWorldScreenPoint
				{
					X = 0f,
					Y = 0f,
					W = 0f,
					H = 0f,
					RectJson = "{\"x\":0,\"y\":0,\"width\":0,\"height\":0}",
					OnScreen = false,
					Path = path,
					InstanceId = syntheticId
				};
			}
			else
			{
				point.Path = path;
				point.InstanceId = syntheticId;
			}

			var fingerprint = "map_object|mapdata|id="
				+ objectId.ToString(CultureInfo.InvariantCulture)
				+ "|sid="
				+ (sid ?? "")
				+ "|"
				+ path;

			elements.Add(new DumpElementRecord
			{
				Id = StableElementId("map-object-data", syntheticId, fingerprint),
				Kind = "map_object",
				Role = "map_object",
				Name = label,
				Path = path,
				Label = label,
				Sid = string.IsNullOrWhiteSpace(sid) ? null : sid.Trim(),
				RectJson = point.RectJson,
				Visible = point.OnScreen,
				Enabled = true,
				Interactable = false,
				OnScreen = point.OnScreen,
				FogVisible = point.FogVisible,
				FingerprintValue = fingerprint,
				InstanceId = syntheticId,
				RectX = point.X,
				RectY = point.Y,
				RectW = point.W,
				RectH = point.H
			});
			census.PlacedEmitted++;
			index++;
		}
	}

	private static void AppendMapMarkerDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		object mapInstance,
		object mapData,
		Camera camera,
		bool cameraOk,
		object fogOfWar,
		bool fogOk,
		Dictionary<int, MapWorldScreenPoint> byNode,
		List<string> gaps,
		MapWorldCensus census)
	{
		var markers = ReadFirstMemberValue(mapData, GameSymbols.AiDriverScreenDump.MapDataMarkersMemberHints);
		if (markers == null)
		{
			gaps.Add(GapJson(
				"map_world_markers_unresolved",
				"MapData.markers member unresolved for screen_dump.",
				false));
			return;
		}

		var index = 0;
		foreach (var row in EnumerateIl2CppListForDump(markers))
		{
			census.MarkersFound++;
			if (elements.Count >= elementLimit)
				break;
			if (row == null)
			{
				index++;
				continue;
			}

			var sid = ReadFirstStringMember(row, GameSymbols.AiDriverScreenDump.MarkerSidFields);
			var node = Homm3MapObjectPropCityResolver.TryGetIntMember(row, GameSymbols.AiDriverScreenDump.MarkerNodeFields);
			var markerId = Homm3MapObjectPropCityResolver.TryGetIntMember(row, GameSymbols.AiDriverScreenDump.MarkerIdFields);
			var label = !string.IsNullOrWhiteSpace(sid)
				? sid.Trim()
				: (markerId.HasValue ? "marker_id=" + markerId.Value.ToString(CultureInfo.InvariantCulture) : "map_marker");
			var path = "MapData.markers[" + index.ToString(CultureInfo.InvariantCulture) + "]"
				+ (node.HasValue ? "/node=" + node.Value.ToString(CultureInfo.InvariantCulture) : "");
			var syntheticId = StableHash(path + "|" + (sid ?? "") + "|" + (markerId?.ToString(CultureInfo.InvariantCulture) ?? "")).GetHashCode();
			if (!seen.Add(syntheticId ^ unchecked((int)0x4D41524B))) // 'MARK'
				continue;

			MapWorldScreenPoint point = null;
			if (node.HasValue && node.Value >= 0)
				byNode.TryGetValue(node.Value, out point);
			if ((point == null || point.W <= 0f) && node.HasValue && node.Value >= 0)
				TryProjectMapNode(mapInstance, node.Value, camera, cameraOk, out point);
			if (point != null && point.W > 0f)
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
			if (point != null && point.W > 0f && node.HasValue && node.Value >= 0 && !byNode.ContainsKey(node.Value))
				byNode[node.Value] = point;
			if (point == null)
			{
				point = new MapWorldScreenPoint
				{
					X = 0f,
					Y = 0f,
					W = 0f,
					H = 0f,
					RectJson = "{\"x\":0,\"y\":0,\"width\":0,\"height\":0}",
					OnScreen = false,
					Path = path,
					InstanceId = syntheticId
				};
			}
			else
			{
				point.Path = path;
				point.InstanceId = syntheticId;
			}

			var fingerprint = "map_marker|node="
				+ (node.HasValue ? node.Value.ToString(CultureInfo.InvariantCulture) : "?")
				+ "|sid="
				+ (sid ?? "")
				+ "|"
				+ path;

			elements.Add(new DumpElementRecord
			{
				Id = StableElementId("map-marker", syntheticId, fingerprint),
				Kind = "map_marker",
				Role = "map_marker",
				Name = label,
				Path = path,
				Label = label,
				Sid = string.IsNullOrWhiteSpace(sid) ? null : sid.Trim(),
				RectJson = point.RectJson,
				Visible = point.OnScreen,
				Enabled = true,
				Interactable = false,
				OnScreen = point.OnScreen,
				FogVisible = point.FogVisible,
				FingerprintValue = fingerprint,
				InstanceId = syntheticId,
				RectX = point.X,
				RectY = point.Y,
				RectW = point.W,
				RectH = point.H
			});
			census.MarkersEmitted++;
			index++;
		}
	}

	private static void AppendMapHeroDumpElements(
		List<DumpElementRecord> elements,
		HashSet<int> seen,
		int elementLimit,
		object mapInstance,
		Camera camera,
		bool cameraOk,
		Dictionary<int, MapWorldScreenPoint> byId,
		Dictionary<int, MapWorldScreenPoint> byNode,
		Dictionary<int, HeroLiveDumpPoint> liveHeroes,
		object fogOfWar,
		bool fogOk,
		List<string> gaps,
		MapWorldCensus census)
	{
		if (mapInstance == null)
		{
			gaps.Add(GapJson(
				"map_world_heroes_map_missing",
				"Map instance unavailable; propHeroes rows were not enumerated.",
				false));
			return;
		}

		var objectsProperties = Homm3MapObjectPropCityResolver.ResolveObjectsProperties(mapInstance);
		if (objectsProperties == null)
		{
			gaps.Add(GapJson(
				"map_world_heroes_props_unresolved",
				"Map objectsProperties unresolved; propHeroes rows were not enumerated.",
				false));
			return;
		}

		var propHeroes = ReadFirstMemberValue(objectsProperties, GameSymbols.CampaignSpawnParity.PropHeroesMemberHints);
		if (propHeroes == null)
		{
			gaps.Add(GapJson(
				"map_world_heroes_list_unresolved",
				"propHeroes list unresolved on objectsProperties.",
				false));
			return;
		}

		if (liveHeroes != null && liveHeroes.Count > 0)
		{
			gaps.Add(GapJson(
				"map_world_hero_live_index",
				"Live world-hero index resolved " + liveHeroes.Count.ToString(CultureInfo.InvariantCulture)
				+ " row(s) via transform projection (source="
				+ (_worldHeroScanNote ?? "worldHeroScan")
				+ ").",
				false));
		}

		var unresolvedHeroes = 0;
		var index = 0;
		foreach (var row in EnumerateIl2CppListForDump(propHeroes))
		{
			census.HeroesFound++;
			if (elements.Count >= elementLimit)
				break;
			if (row == null)
			{
				index++;
				continue;
			}

			var defined = ReadFirstBoolMember(row, GameSymbols.AiDriverScreenDump.PropHeroDefinedFields);
			if (defined == false)
			{
				index++;
				continue;
			}

			var heroSid = ReadFirstStringMember(row, GameSymbols.AiDriverScreenDump.PropHeroSidFields);
			var objectId = Homm3MapObjectPropCityResolver.TryGetIntMember(row, GameSymbols.AiDriverScreenDump.PropHeroIdFields);
			var propNode = Homm3MapObjectPropCityResolver.TryGetIntMember(row, GameSymbols.AiDriverScreenDump.PropHeroNodeFields);
			if (string.IsNullOrWhiteSpace(heroSid) && !objectId.HasValue)
			{
				index++;
				continue;
			}

			var label = !string.IsNullOrWhiteSpace(heroSid)
				? heroSid.Trim()
				: "hero_id=" + objectId.Value.ToString(CultureInfo.InvariantCulture);
			var path = "propHeroes[" + index.ToString(CultureInfo.InvariantCulture) + "]"
				+ (objectId.HasValue ? "/id=" + objectId.Value.ToString(CultureInfo.InvariantCulture) : "");
			var syntheticId = StableHash(path + "|" + (heroSid ?? "")).GetHashCode();
			if (!seen.Add(syntheticId ^ unchecked((int)0x4845524F))) // 'HERO'
				continue;

			int? node = propNode.HasValue && propNode.Value >= 0 ? propNode : null;
			MapWorldScreenPoint point = null;
			var resolveSource = (string)null;

			if (objectId.HasValue
			    && objectId.Value > 0
			    && liveHeroes != null
			    && liveHeroes.TryGetValue(objectId.Value, out var live)
			    && live?.Point != null
			    && live.Point.W > 0f)
			{
				point = CloneMapWorldScreenPoint(live.Point);
				if (live.Node >= 0)
					node = live.Node;
				resolveSource = live.Source ?? "worldHero";
				path = live.UnityPath ?? path;
				census.HeroesLiveFound++;
			}

			if (point == null && objectId.HasValue && objectId.Value > 0)
				byId.TryGetValue(objectId.Value, out point);

			if (node == null
			    && TryResolveSessionDataHeroNode(objectId.HasValue ? objectId.Value : -1, heroSid, out var dataNode, out _))
				node = dataNode;

			if (!objectId.HasValue
			    && !string.IsNullOrWhiteSpace(heroSid)
			    && TryResolveSessionDataRoot(out var dataRoot, out _)
			    && TryFindSessionDataHero(dataRoot, -1, heroSid, out var matchedHero, out _)
			    && matchedHero != null)
			{
				var matchedId = Homm3MapObjectPropCityResolver.TryGetIntMember(matchedHero, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints);
				if (matchedId.HasValue && matchedId.Value > 0)
					objectId = matchedId;
			}

			if (point == null && node.HasValue)
			{
				if (byNode.TryGetValue(node.Value, out var byNodePoint) && byNodePoint != null && byNodePoint.W > 0f)
					point = CloneMapWorldScreenPoint(byNodePoint);
				else if (TryProjectMapNode(mapInstance, node.Value, camera, cameraOk, out var projected) && projected != null)
				{
					point = projected;
					ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
					resolveSource = resolveSource ?? "mapNodeProject";
				}
			}

			if (point != null && point.FogVisible == null && node.HasValue)
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
			else if (point != null && point.FogVisible == null && !node.HasValue)
			{
				// Camera-only projection without a proven node must not be treated as vision/actionable.
				point.OnScreen = false;
			}

			if (point == null || point.W <= 0f)
			{
				point = new MapWorldScreenPoint
				{
					X = 0f,
					Y = 0f,
					W = 0f,
					H = 0f,
					RectJson = "{\"x\":0,\"y\":0,\"width\":0,\"height\":0}",
					OnScreen = false,
					Path = path,
					InstanceId = syntheticId,
					Node = node,
					ResolveSource = resolveSource
				};
				unresolvedHeroes++;
			}
			else
			{
				point.Path = path;
				point.InstanceId = syntheticId;
				point.Node = node;
				point.ResolveSource = resolveSource;
				census.HeroesRectResolved++;
			}

			if (node.HasValue)
				census.HeroesNodeResolved++;

			if (node.HasValue)
				path += "/node=" + node.Value.ToString(CultureInfo.InvariantCulture);
			if (!string.IsNullOrEmpty(resolveSource))
				path += "/source=" + resolveSource;

			var fingerprint = "map_hero|id="
				+ (objectId.HasValue ? objectId.Value.ToString(CultureInfo.InvariantCulture) : "?")
				+ "|node="
				+ (node.HasValue ? node.Value.ToString(CultureInfo.InvariantCulture) : "?")
				+ "|heroSid="
				+ (heroSid ?? "")
				+ "|"
				+ path;

			elements.Add(new DumpElementRecord
			{
				Id = StableElementId("map-hero", syntheticId, fingerprint),
				Kind = "map_hero",
				Role = "map_hero",
				Name = label,
				Path = path,
				Label = label,
				Sid = string.IsNullOrWhiteSpace(heroSid) ? null : heroSid.Trim(),
				RectJson = point.RectJson,
				Visible = point.OnScreen,
				Enabled = true,
				Interactable = point.OnScreen,
				OnScreen = point.OnScreen,
				FogVisible = point.FogVisible,
				FingerprintValue = fingerprint,
				InstanceId = syntheticId,
				RectX = point.X,
				RectY = point.Y,
				RectW = point.W,
				RectH = point.H
			});
			census.HeroesEmitted++;
			index++;
		}

		if (unresolvedHeroes > 0)
		{
			var probe = DescribeHeroMarkProbeFailure();
			gaps.Add(GapJson(
				string.IsNullOrEmpty(probe) ? "map_world_hero_mark_probe_failed" : "map_world_hero_mark_probe",
				string.IsNullOrEmpty(probe) ? "Side mark probe failed with no detail." : probe,
				false));

			gaps.Add(GapJson(
				"map_world_hero_node_unresolved",
				unresolvedHeroes.ToString(CultureInfo.InvariantCulture)
				+ " propHero row(s) lacked a proven node+screen rect (live world hero, placed-object byId, or Map node projection).",
				false));
		}
	}

	private static Dictionary<int, HeroLiveDumpPoint> BuildWorldHeroDumpIndex(
		Camera camera,
		bool cameraOk,
		object fogOfWar,
		bool fogOk,
		List<string> gaps,
		MapWorldCensus census)
	{
		var index = new Dictionary<int, HeroLiveDumpPoint>();
		if (!cameraOk || camera == null)
			return index;

		var logicCount = TryBuildWorldHeroDumpIndexFromLogicWorld(camera, fogOfWar, fogOk, index);
		if (logicCount > 0)
		{
			_worldHeroScanNote = "logicWorld count=" + logicCount.ToString(CultureInfo.InvariantCulture);
			return index;
		}

		_worldHeroScanNote = _lastLogicWorldEnumerateNote;

		if (!TryFindWorldHeroInstances(out var instances, out var scanNote))
		{
			if (!string.IsNullOrEmpty(scanNote))
			{
				gaps.Add(GapJson(
					"map_world_hero_scan_unresolved",
					"Live world-hero type/instances unresolved for screen_dump (logicWorld=0; "
					+ scanNote
					+ ").",
					false));
			}
			return index;
		}

		for (var i = 0; i < instances.Length; i++)
		{
			var obj = instances[i];
			if (!obj)
				continue;

			var component = TryCastDumpComponent(obj);
			if (component == null || !component.gameObject || !component.gameObject.activeInHierarchy)
				continue;

			if (!TryReadWorldHeroId(component, out var heroId) || heroId <= 0)
				continue;

			var node = -1;
			TryResolveHeroNodeFromWorldEntry(component, out node, out _);
			BuildWorldPointRect(component.transform.position, camera, true, out var point);
			point.Path = UnityPath(component.transform);
			point.InstanceId = component.gameObject.GetInstanceID();
			point.Node = node >= 0 ? node : (int?)null;
			ApplyFogVisibilityToPoint(fogOfWar, fogOk, node >= 0 ? node : (int?)null, point);

			index[heroId] = new HeroLiveDumpPoint
			{
				HeroId = heroId,
				Node = node,
				Point = point,
				UnityPath = point.Path,
				Source = "worldHeroTransform"
			};
		}

		return index;
	}

	private static int TryBuildWorldHeroDumpIndexFromLogicWorld(
		Camera camera,
		object fogOfWar,
		bool fogOk,
		Dictionary<int, HeroLiveDumpPoint> index)
	{
		if (camera == null || index == null)
			return 0;
		if (!TryEnumerateLogicWorldHeroEntries(out var entries, out _))
			return 0;

		object mapInstance = null;
		TryResolveAdventureMapContext(out mapInstance, out _, out _);

		var added = 0;
		for (var i = 0; i < entries.Count; i++)
		{
			var entry = entries[i];
			if (entry == null)
				continue;

			var dataHero = ResolveDataHeroFromSideEntry(entry);
			var heroId = dataHero == null
				? -1
				: Homm3MapObjectPropCityResolver.TryGetIntMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints) ?? -1;
			if (heroId <= 0)
				TryReadWorldHeroIdFromEntry(entry, out heroId);
			if (heroId <= 0)
				continue;

			var node = -1;
			if (dataHero != null
			    && TryReadDumpIntMember(dataHero, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out node)
			    && node < 0)
				node = -1;
			if (node < 0)
				TryResolveHeroNodeFromWorldEntry(entry, out node, out _);

			MapWorldScreenPoint point = null;
			string unityPath = null;
			var source = "logicWorldHero";
			if (TryResolveWorldHeroScreenPoint(entry, camera, out point, out unityPath))
			{
				point.Node = node >= 0 ? node : (int?)null;
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, node >= 0 ? node : (int?)null, point);
			}
			else if (node >= 0
			         && mapInstance != null
			         && TryProjectMapNode(mapInstance, node, camera, true, out var projected)
			         && projected != null)
			{
				point = projected;
				unityPath = "logicWorldHero/node=" + node.ToString(CultureInfo.InvariantCulture);
				ApplyFogVisibilityToPoint(fogOfWar, fogOk, node, point);
				source = "logicWorldHeroNodeProject";
			}

			if (point == null || point.W <= 0f)
				continue;

			point.Path = unityPath;
			index[heroId] = new HeroLiveDumpPoint
			{
				HeroId = heroId,
				Node = node,
				Point = point,
				UnityPath = unityPath,
				Source = source
			};
			added++;
		}

		return added;
	}

	private static bool TryEnumerateLogicWorldHeroEntries(out List<object> entries, out string note)
	{
		entries = new List<object>(8);
		note = null;
		_lastLogicWorldEnumerateNote = null;

		var registryCount = Homm3AiDriverLogicHeroRegistry.CopyEntriesTo(entries);
		if (registryCount > 0)
		{
			note = Homm3AiDriverLogicHeroRegistry.DescribeState();
			return true;
		}

		if (TryEnumerateLogicWorldHeroEntriesFromDsuStatics(entries, out note) && entries.Count > 0)
			return true;

		if (TryEnumerateLogicWorldHeroEntriesFromGlobalLogicRoot(entries, out note) && entries.Count > 0)
			return true;

		if (TryEnumerateLogicWorldHeroEntriesFromSessionBfs(entries, out var bfsNote) && entries.Count > 0)
		{
			note = bfsNote;
			return true;
		}

		if (!TryFindSessionRootWithWorld(out var session, out var sessionReason))
		{
			note = "session=" + (sessionReason ?? "?");
			return false;
		}

		var world = ReadFirstMemberValue(session, GameSymbols.AdventureVisionLaws.SessionWorldMembers)
		            ?? ReadMemberValue(session, "world");
		if (world == null)
		{
			note = "world_missing";
			return false;
		}

		var sides = ReadFirstMemberValue(world, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
		            ?? ReadMemberValue(world, "sides");
		if (sides == null)
		{
			note = "world.sides_missing";
			return false;
		}

		// world.sides is DataSides — only use sides that expose dtj ccns hero lists, not Data.Side rows.
		var arr = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
		if (arr is IEnumerable enumerable)
		{
			foreach (var side in enumerable)
			{
				if (side == null)
					continue;
				if (!LooksLikeLogicSideForHeroList(side))
					continue;
				TryAppendLogicWorldHeroEntriesFromSide(side, entries);
			}
		}

		if (entries.Count > 0)
		{
			note = "logicSides heroes=" + entries.Count.ToString(CultureInfo.InvariantCulture);
			return true;
		}

		note = "logicSide.heroList_missing";
		_lastLogicWorldEnumerateNote = note;
		return false;
	}

	private static bool TryEnumerateLogicWorldHeroEntriesFromGlobalLogicRoot(List<object> entries, out string note)
	{
		note = null;
		if (!TryResolveGlobalLogicRootForDump(out var logicRoot))
		{
			note = "dsu_logicRoot_missing";
			return false;
		}

		var logicSides = ReadFirstMemberValue(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootSideCollectionMembers);
		if (logicSides == null)
		{
			note = "dsu.sideCollection_missing";
			return false;
		}

		var before = entries.Count;
		if (!TryEnumerateLogicSidesFromCollection(logicSides, entries))
		{
			note = "dsu.logicSide.heroList_missing";
			return false;
		}

		note = "dsu.logicSides heroes=" + (entries.Count - before).ToString(CultureInfo.InvariantCulture);
		return entries.Count > before;
	}

	private static bool TryEnumerateLogicSidesFromCollection(object logicSides, List<object> entries)
	{
		if (logicSides == null || entries == null)
			return false;

		var added = false;
		for (var index = 0; index < 16; index++)
		{
			if (!TryInvokeLogicSideByIndex(logicSides, index, out var logicSide) || logicSide == null)
				break;
			if (TryAppendLogicWorldHeroEntriesFromSide(logicSide, entries))
				added = true;
		}
		if (added)
			return true;

		if (logicSides is IEnumerable sidesEnumerable)
		{
			foreach (var side in sidesEnumerable)
			{
				if (side == null)
					continue;
				if (TryAppendLogicWorldHeroEntriesFromSide(side, entries))
					added = true;
			}
		}

		var inner = ReadFirstMemberValue(logicSides, new[] { "array", "items", "_items", "field_Public_ArrayOf_Object1PublicSiObFrObccSiLiObcc1Unique_0" });
		if (inner is IEnumerable innerEnumerable)
		{
			foreach (var side in innerEnumerable)
			{
				if (side == null)
					continue;
				if (TryAppendLogicWorldHeroEntriesFromSide(side, entries))
					added = true;
			}
		}

		return added;
	}

	private static bool TryInvokeLogicSideByIndex(object logicSides, int index, out object logicSide)
	{
		logicSide = null;
		if (logicSides == null || index < 0)
			return false;

		var methods = GameMember.FindMethodsByNames(
			logicSides.GetType(),
			new[] { typeof(int) },
			"ai.dump.logicSide.byIndex",
			GameSymbols.CustomFactionLawRuntime.LogicSideCollectionByIndexMethods);
		var method = methods.Length > 0 ? methods[0] : null;
		if (method == null)
			return false;

		try { logicSide = method.Invoke(logicSides, new object[] { index }); }
		catch { logicSide = null; }
		return logicSide != null;
	}

	private static bool TryResolveGlobalLogicRootForDump(out object logicRoot)
	{
		logicRoot = null;
		var type = ResolveDumpLogicRootType();
		if (type == null)
			return false;

		foreach (var name in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootInstanceMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (TryReadStaticMember(type, name, out logicRoot) && logicRoot != null)
				return true;
		}

		if (TryFindSessionRootWithWorld(out var session, out _))
		{
			var visited = new HashSet<int>();
			if (TryCollectObjectsMatchingShape(session, LooksLikeGlobalLogicRootForDump, visited, 3000, out var roots)
			    && roots.Count > 0)
			{
				logicRoot = roots[0];
				return true;
			}
		}

		return false;
	}

	private static Type ResolveDumpLogicRootType()
	{
		foreach (var hint in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = ModActions.GetHexType(hint) ?? FindDumpRuntimeType(hint);
			if (type != null)
				return type;
			type = GameMember.FindType("ai.dump.logicRoot." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type FindDumpRuntimeType(string hint)
	{
		if (string.IsNullOrWhiteSpace(hint))
			return null;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type type = null;
			try
			{
				type = asm.GetType(hint, false)
				         ?? asm.GetType("Hex.Session." + hint, false)
				         ?? asm.GetType("Hex." + hint, false);
			}
			catch { type = null; }
			if (type != null)
				return type;
		}
		return null;
	}

	private static bool LooksLikeGlobalLogicRootForDump(object value)
	{
		if (value == null)
			return false;
		var typeName = value.GetType().Name ?? string.Empty;
		if (typeName.Equals(GameSymbols.SwashbucklerGold.SessionManagerTypeHint, StringComparison.Ordinal)
		    || typeName.IndexOf("ObjectPublicObDaObSeEvccObccDaSeUnique", StringComparison.Ordinal) >= 0)
			return ReadFirstMemberValue(value, GameSymbols.CustomFactionLawRuntime.LogicRootSideCollectionMembers) != null;
		return false;
	}

	private static bool TryEnumerateLogicWorldHeroEntriesFromSessionBfs(List<object> entries, out string note)
	{
		note = null;
		var seeds = new List<object>(4);
		if (TryFindSessionRootWithWorld(out var session, out _))
			seeds.Add(session);
		if (TryResolveGlobalLogicRootForDump(out var logicRoot) && logicRoot != null)
			seeds.Add(logicRoot);
		if (TryResolveSessionDataRoot(out var data, out _) && data != null)
			seeds.Add(data);

		if (seeds.Count == 0)
		{
			note = "bfs_no_seeds";
			return false;
		}

		var visited = new HashSet<int>();
		var logicSideCount = 0;
		for (var s = 0; s < seeds.Count; s++)
		{
			if (!TryCollectObjectsMatchingShape(seeds[s], LooksLikeLogicSideForHeroList, visited, 5000, out var logicSides))
				continue;
			logicSideCount += logicSides.Count;
			for (var i = 0; i < logicSides.Count; i++)
				TryAppendLogicWorldHeroEntriesFromSide(logicSides[i], entries);
		}

		for (var s = 0; s < seeds.Count; s++)
		{
			if (!TryCollectObjectsMatchingShape(seeds[s], LooksLikeLogicWorldHeroEntry, visited, 5000, out var worldHeroes))
				continue;
			for (var i = 0; i < worldHeroes.Count; i++)
			{
				var hero = worldHeroes[i];
				if (hero != null && !entries.Contains(hero))
					entries.Add(hero);
			}
		}

		note = "shapeScan sides=" + logicSideCount.ToString(CultureInfo.InvariantCulture)
			+ " heroes=" + entries.Count.ToString(CultureInfo.InvariantCulture);
		return entries.Count > 0;
	}

	private static bool TryCollectObjectsMatchingShape(
		object root,
		Func<object, bool> predicate,
		HashSet<int> visited,
		int maxNodes,
		out List<object> found)
	{
		found = new List<object>(8);
		if (root == null || predicate == null)
			return false;

		var queue = new Queue<object>();
		if (visited == null)
			visited = new HashSet<int>();
		queue.Enqueue(root);
		var nodes = 0;
		while (queue.Count > 0 && nodes < maxNodes)
		{
			var cur = queue.Dequeue();
			nodes++;
			if (cur == null)
				continue;
			var visitId = RuntimeHelpers.GetHashCode(cur);
			if (!visited.Add(visitId))
				continue;
			if (predicate(cur))
				found.Add(cur);
			EnqueueLogicWorldHeroBfsChildren(queue, cur, visited, ref nodes);
		}

		return found.Count > 0;
	}

	private static void EnqueueLogicWorldHeroBfsChildren(Queue<object> queue, object cur, HashSet<int> visited, ref int nodes)
	{
		if (queue == null || cur == null || nodes >= 5000)
			return;

		Type type;
		try { type = cur.GetType(); }
		catch { return; }

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		FieldInfo[] fields = null;
		PropertyInfo[] props = null;
		try { fields = type.GetFields(flags); } catch { fields = null; }
		try { props = type.GetProperties(flags); } catch { props = null; }

		if (fields != null)
		{
			for (var i = 0; i < fields.Length && nodes < 5000; i++)
			{
				var field = fields[i];
				if (field == null)
					continue;
				var ft = field.FieldType;
				if (ft.IsPrimitive || ft == typeof(string) || ft.IsEnum)
					continue;
				object child = null;
				try { child = field.GetValue(cur); } catch { child = null; }
				EnqueueLogicWorldHeroBfsValue(queue, child, visited, ref nodes);
			}
		}

		if (props == null)
			return;
		for (var i = 0; i < props.Length && nodes < 5000; i++)
		{
			var prop = props[i];
			if (prop == null || !prop.CanRead || prop.GetIndexParameters().Length != 0)
				continue;
			var pt = prop.PropertyType;
			if (pt.IsPrimitive || pt == typeof(string) || pt.IsEnum)
				continue;
			object child = null;
			try { child = prop.GetValue(cur, null); } catch { child = null; }
			EnqueueLogicWorldHeroBfsValue(queue, child, visited, ref nodes);
		}
	}

	private static void EnqueueLogicWorldHeroBfsValue(Queue<object> queue, object value, HashSet<int> visited, ref int nodes)
	{
		if (value == null || queue == null)
			return;
		if (value is string || value.GetType().IsPrimitive || value is UnityObject)
			return;
		if (value is IEnumerable enumerable && value is not Il2CppSystem.Object)
		{
			foreach (var item in enumerable)
			{
				if (item == null || item is string || item.GetType().IsPrimitive || item is UnityObject)
					continue;
				var itemId = RuntimeHelpers.GetHashCode(item);
				if (!visited.Contains(itemId))
					queue.Enqueue(item);
				if (++nodes >= 5000)
					break;
			}
			return;
		}

		var id = RuntimeHelpers.GetHashCode(value);
		if (!visited.Contains(id))
			queue.Enqueue(value);
	}

	private static bool LooksLikeLogicWorldHeroEntry(object entry)
	{
		if (entry == null)
			return false;
		var typeName = entry.GetType().Name ?? string.Empty;
		if (!typeName.Equals("eta", StringComparison.Ordinal)
		    && typeName.IndexOf("ObjectPublicHeObInObciSiObVeSeObUnique", StringComparison.Ordinal) < 0)
			return false;
		return ReadFirstMemberValue(entry, GameSymbols.HeroMap.SessionHeroVisualFields) != null
		       || ReadFirstMemberValue(entry, GameSymbols.HeroMap.SessionHeroLogicFields) != null;
	}

	private static bool LooksLikeLogicSideForHeroList(object side)
	{
		if (side == null)
			return false;
		var typeName = side.GetType().Name ?? string.Empty;
		if (typeName.Equals(GameSymbols.SwashbucklerGold.SideLogicTypeHint, StringComparison.Ordinal)
		    || typeName.IndexOf("Object1PublicSiObFrObccSiLiObcc1Unique", StringComparison.Ordinal) >= 0)
			return true;
		return TypeHasAnyInstanceMember(side.GetType(), GameSymbols.SwashbucklerGold.SideHeroListProperties)
		       && !TypeHasAnyInstanceMember(side.GetType(), GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers);
	}

	private static bool TryAppendLogicWorldHeroEntriesFromSide(object logicSide, List<object> entries)
	{
		if (logicSide == null || entries == null)
			return false;
		var heroList = ReadFirstMemberValue(logicSide, GameSymbols.SwashbucklerGold.SideHeroListProperties)
		               ?? ReadFirstMemberValue(logicSide, GameSymbols.AiDriverScreenDump.LogicWorldHeroListMembers);
		if (heroList == null)
			return false;
		var added = false;
		foreach (var entry in EnumerateIl2CppListForDump(heroList))
		{
			if (entry == null)
				continue;
			entries.Add(entry);
			added = true;
		}
		return added;
	}

	private static bool TryReadWorldHeroIdFromEntry(object entry, out int heroId)
	{
		heroId = 0;
		if (entry == null)
			return false;

		var drawer = ReadFirstMemberValue(entry, GameSymbols.HeroMap.SessionHeroVisualFields);
		if (drawer != null)
		{
			var fromDrawer = Homm3MapObjectPropCityResolver.TryGetIntMember(drawer, GameSymbols.HeroMap.DrawerHeroIdFields);
			if (fromDrawer.HasValue && fromDrawer.Value > 0)
			{
				heroId = fromDrawer.Value;
				return true;
			}
		}

		var fromEntry = Homm3MapObjectPropCityResolver.TryGetIntMember(entry, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints)
		                ?? Homm3MapObjectPropCityResolver.TryGetIntMember(entry, new[] { "cicn", "heroId", "id", "field_Public_Int32_0" });
		if (fromEntry.HasValue && fromEntry.Value > 0)
		{
			heroId = fromEntry.Value;
			return true;
		}

		var dataHero = ResolveDataHeroFromSideEntry(entry);
		var fromData = dataHero == null
			? null
			: Homm3MapObjectPropCityResolver.TryGetIntMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints);
		if (fromData.HasValue && fromData.Value > 0)
		{
			heroId = fromData.Value;
			return true;
		}

		return false;
	}

	private static bool TryResolveWorldHeroScreenPoint(
		object worldHeroEntry,
		Camera camera,
		out MapWorldScreenPoint point,
		out string unityPath)
	{
		point = null;
		unityPath = null;
		if (worldHeroEntry == null || camera == null)
			return false;

		var drawer = ReadFirstMemberValue(worldHeroEntry, GameSymbols.HeroMap.SessionHeroVisualFields);
		var rootGo = TryReadHeroDrawerRootGameObject(drawer);
		if (rootGo)
		{
			BuildWorldPointRect(rootGo.transform.position, camera, true, out point);
			unityPath = UnityPath(rootGo.transform);
			return point != null && point.W > 0f;
		}

		if (TryReadDumpVector3Member(worldHeroEntry, GameSymbols.AiDriverScreenDump.WorldHeroPositionFields, out var worldPos))
		{
			BuildWorldPointRect(worldPos, camera, true, out point);
			unityPath = "logicWorldHero/position";
			return point != null && point.W > 0f;
		}

		return false;
	}

	private static GameObject TryReadHeroDrawerRootGameObject(object drawer)
	{
		if (drawer == null)
			return null;
		if (drawer is GameObject go)
			return go;
		if (drawer is Component component && component)
			return component.gameObject;

		foreach (var name in GameSymbols.HeroMap.RootGameObjectProperties)
		{
			try
			{
				var field = drawer.GetType().GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				var value = field?.GetValue(drawer);
				if (value is GameObject fieldGo && fieldGo)
					return fieldGo;
			}
			catch { /* Il2Cpp field read best-effort */ }
		}

		return null;
	}

	private static bool TryReadDumpVector3Member(object obj, string[] names, out Vector3 value)
	{
		value = default;
		if (obj == null || names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			object raw = null;
			try { raw = ReadMemberValue(obj, names[i]); }
			catch { raw = null; }
			if (raw is Vector3 vector)
			{
				value = vector;
				return true;
			}
		}
		return false;
	}

	private static bool TryFindWorldHeroInstances(out UnityObject[] found, out string note)
	{
		found = Array.Empty<UnityObject>();
		note = null;

		if (_worldHeroScanCompleted && _worldHeroScanAllCold)
		{
			note = "cachedCold " + (_worldHeroScanNote ?? "");
			return false;
		}

		if (_worldHeroScanCompleted && _worldHeroScanHotTypes.Count > 0)
		{
			var merged = new List<UnityObject>(8);
			for (var i = 0; i < _worldHeroScanHotTypes.Count; i++)
			{
				var hotType = _worldHeroScanHotTypes[i];
				if (hotType == null)
					continue;
				try
				{
					var batch = Resources.FindObjectsOfTypeAll(Il2CppType.From(hotType));
					if (batch != null && batch.Length > 0)
						merged.AddRange(batch);
				}
				catch { /* keep other types */ }
			}
			found = merged.Count == 0 ? Array.Empty<UnityObject>() : merged.ToArray();
			note = "cachedHotTypes=" + _worldHeroScanHotTypes.Count.ToString(CultureInfo.InvariantCulture)
				+ " count=" + found.Length.ToString(CultureInfo.InvariantCulture);
			return found.Length > 0;
		}

		var hints = GameSymbols.AiDriverScreenDump.WorldHeroScanTypeHints;
		var scanBits = new List<string>();
		var hotTypes = new List<Type>();
		UnityObject[] best = null;

		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			var type = ResolveWorldHeroScanType(hint);
			if (type == null)
			{
				scanBits.Add(hint + "=typeMiss");
				continue;
			}

			UnityObject[] batch = null;
			try { batch = Resources.FindObjectsOfTypeAll(Il2CppType.From(type)); }
			catch (Exception ex)
			{
				scanBits.Add(hint + "=scanFail:" + ex.GetType().Name);
				continue;
			}

			var count = batch == null ? 0 : batch.Length;
			scanBits.Add(hint + "=" + type.Name + ":" + count.ToString(CultureInfo.InvariantCulture));
			if (count > 0 && !hotTypes.Contains(type))
				hotTypes.Add(type);
			if (count > (best == null ? -1 : best.Length))
				best = batch;
		}

		_worldHeroScanCompleted = true;
		_worldHeroScanNote = "scan=[" + string.Join(",", scanBits) + "]";
		if (hotTypes.Count == 0 || best == null || best.Length == 0)
		{
			_worldHeroScanAllCold = true;
			_worldHeroScanHotTypes.Clear();
			note = "cold " + _worldHeroScanNote;
			return false;
		}

		_worldHeroScanAllCold = false;
		_worldHeroScanHotTypes.Clear();
		_worldHeroScanHotTypes.AddRange(hotTypes);
		found = best;
		note = "hot " + _worldHeroScanNote;
		return true;
	}

	private static bool TryReadWorldHeroId(Component component, out int heroId)
	{
		heroId = 0;
		if (component == null)
			return false;

		var fromDrawer = Homm3MapObjectPropCityResolver.TryGetIntMember(component, GameSymbols.HeroMap.DrawerHeroIdFields);
		if (fromDrawer.HasValue && fromDrawer.Value > 0)
		{
			heroId = fromDrawer.Value;
			return true;
		}

		if (!_worldHeroIdGetterResolveAttempted)
		{
			_worldHeroIdGetterResolveAttempted = true;
			_cachedWorldHeroIdGetter = GameMember.FindFirstMethodByNames(
				component.GetType(),
				Type.EmptyTypes,
				GameSymbols.HomecomingBoatTravel.WorldHeroId);
		}

		if (_cachedWorldHeroIdGetter != null)
		{
			try
			{
				var raw = _cachedWorldHeroIdGetter.Invoke(component, Array.Empty<object>());
				if (raw != null && TryConvertDumpInt(raw, out heroId) && heroId > 0)
					return true;
			}
			catch { /* fall through to fields */ }
		}

		var fromFields = Homm3MapObjectPropCityResolver.TryGetIntMember(component, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints)
			?? Homm3MapObjectPropCityResolver.TryGetIntMember(component, new[] { "heroId", "id", "field_Public_Int32_0" });
		if (fromFields.HasValue && fromFields.Value > 0)
		{
			heroId = fromFields.Value;
			return true;
		}

		return false;
	}

	private static bool TryResolveHeroNodeFromWorldEntry(object entry, out int node, out string source)
	{
		node = -1;
		source = null;
		if (entry == null)
			return false;

		if (TryReadDumpIntMember(entry, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out node) && node >= 0)
		{
			source = "direct-node";
			return true;
		}

		var logicHero = ReadFirstMemberValue(entry, GameSymbols.HeroMap.DrawerHeroFields)
		                ?? ReadFirstMemberValue(entry, GameSymbols.HeroMap.SessionHeroLogicFields)
		                ?? ReadFirstMemberValue(entry, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers);
		if (logicHero != null && TryResolveHeroNodeFromLogicHero(logicHero, out node, out source))
			return true;

		return TryResolveHeroNodeFromLogicHero(entry, out node, out source);
	}

	private static bool TryResolveHeroNodeFromLogicHero(object logicHero, out int node, out string source)
	{
		node = -1;
		source = null;
		if (logicHero == null)
			return false;

		var dataHero = ReadFirstMemberValue(logicHero, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers);
		if (dataHero == null)
			return false;
		if (!TryReadDumpIntMember(dataHero, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out node) || node < 0)
			return false;
		source = "logic-data-node";
		return true;
	}

	private static bool TryResolveSessionDataHeroNode(int heroId, string heroSid, out int node, out string source)
	{
		node = -1;
		source = null;
		object data = null;
		TryResolveSessionDataRoot(out data, out _);

		if (data != null
		    && TryFindSessionDataHero(data, heroId, heroSid, out var dataHero, out source)
		    && TryReadDumpIntMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroNodeFieldHints, out node)
		    && node >= 0)
			return true;

		if (TryFindSessionDataHeroViaLogicWorld(heroId, heroSid, out dataHero, out source)
		    && TryReadDumpIntMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroNodeFieldHints, out node)
		    && node >= 0)
			return true;

		if (TryResolveMarkedHeroNode(data, heroSid, out node, out source))
			return true;
		if (TryResolveMarkedQuestNode(data, out node, out source))
			return true;
		if (TryResolveHeroNodeFromMapDataSid(heroSid, out node, out source))
			return true;
		return false;
	}

	private static bool TryResolveMarkedHeroNode(object data, string heroSid, out int node, out string source)
	{
		node = -1;
		source = null;
		if (!TryResolveLiveDataSideForDump(data, out var side, out _))
			return false;

		if (Homm3AdventureLookaheadState.TryCaptureFromLiveSide(side, out var captured, out _)
		    && captured?.Marks != null
		    && captured.Marks.MarkedHero > 0)
		{
			node = captured.Marks.MarkedHero;
			source = "sideAiData.markedHero";
			return true;
		}

		var aiData = ReadFirstMemberValue(side, GameSymbols.AdventureAiDecision.SideAiDataFieldHints);
		if (aiData == null)
			return false;
		var markedHero = Homm3MapObjectPropCityResolver.TryGetIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedHeroFieldHints);
		if (!markedHero.HasValue || markedHero.Value < 0)
			return false;
		node = markedHero.Value;
		source = "sideAiData.markedHero";
		return true;
	}

	private static bool TryResolveMarkedQuestNode(object data, out int node, out string source)
	{
		node = -1;
		source = null;
		if (!TryResolveLiveDataSideForDump(data, out var side, out _))
			return false;

		if (Homm3AdventureLookaheadState.TryCaptureFromLiveSide(side, out var captured, out _)
		    && captured?.Marks != null
		    && captured.Marks.MarkedNode > 0)
		{
			node = captured.Marks.MarkedNode;
			source = "sideAiData.markedNode";
			return true;
		}

		var aiData = ReadFirstMemberValue(side, GameSymbols.AdventureAiDecision.SideAiDataFieldHints);
		if (aiData == null)
			return false;
		var markedNode = Homm3MapObjectPropCityResolver.TryGetIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedNodeFieldHints);
		if (!markedNode.HasValue || markedNode.Value < 0)
			return false;
		node = markedNode.Value;
		source = "sideAiData.markedNode";
		return true;
	}

	private static string DescribeHeroMarkProbeFailure()
	{
		if (TryResolveLiveDataSideForDump(null, out var liveSide, out var liveSideSource)
		    && Homm3AdventureLookaheadState.TryCaptureFromLiveSide(liveSide, out var captured, out _))
		{
			return "Side marks via " + (liveSideSource ?? "?")
			       + ": markedNode=" + captured.Marks.MarkedNode.ToString(CultureInfo.InvariantCulture)
			       + " markedHero=" + captured.Marks.MarkedHero.ToString(CultureInfo.InvariantCulture)
			       + " registry=" + Homm3AiDriverLogicHeroRegistry.DescribeState()
			       + ".";
		}

		var parts = new List<string>(6);
		if (TryResolveSessionDataRoot(out var sessionData, out var dataSource))
			parts.Add("sessionData=" + (dataSource ?? "?"));
		else
			parts.Add("sessionData=miss");

		if (TryFindSessionRootWithWorld(out _, out var sessionReason))
			parts.Add("sessionWorld=" + (sessionReason ?? "ok"));
		else
			parts.Add("sessionWorld=miss:" + (sessionReason ?? "?"));

		if (Homm3CustomFactionLawRuntime.TryGetAnyRegisteredDataSide(out _, out var regIndex, out var regSource))
			parts.Add("registeredSide[" + regIndex.ToString(CultureInfo.InvariantCulture) + "]=" + (regSource ?? "?"));
		else
			parts.Add("registeredSide=miss");

		if (Homm3AiDriverFogCache.TryGetLiveSide(out _, out var sideCacheSource))
			parts.Add("fogSideCache=" + (sideCacheSource ?? "ok"));
		else
			parts.Add("fogSideCache=miss");

		if (liveSide != null)
		{
			parts.Add("liveSideType=" + (liveSide.GetType().FullName ?? liveSide.GetType().Name));
			if (!Homm3AdventureLookaheadState.TryCaptureFromLiveSide(liveSide, out _, out var captureError))
				parts.Add("capture=" + (captureError ?? "?"));
		}
		else
			parts.Add("liveSide=miss");

		parts.Add("registry=" + Homm3AiDriverLogicHeroRegistry.DescribeState());
		return string.Join(" | ", parts);
	}

	private static bool TryResolveLiveDataSideForDump(object dataRoot, out object side, out string source)
	{
		side = null;
		source = null;
		if (dataRoot != null && TryResolveCurrentDataSide(dataRoot, out side, out source))
			return true;

		if (Homm3AiDriverFogCache.TryGetLiveSide(out side, out source))
			return true;

		if (TryResolveLiveDataSideFromSessionStatic(out side, out source))
			return true;

		if (TryResolveSessionDataRoot(out var sessionData, out var dataSource))
		{
			if (TryResolveCurrentDataSide(sessionData, out side, out source))
			{
				source = (source ?? "dataSides.current") + " via " + (dataSource ?? "sessionData");
				return true;
			}

			var world = ReadFirstMemberValue(sessionData, GameSymbols.AdventureVisionLaws.SessionWorldMembers)
			            ?? ReadMemberValue(sessionData, "world");
			if (world != null)
			{
				var sides = ReadFirstMemberValue(world, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
				            ?? ReadMemberValue(world, "sides");
				if (TryResolvePlayerDataSideFromDataSides(sides, out side, out source))
				{
					source += " via " + (dataSource ?? "sessionData.world");
					return true;
				}
			}
		}

		if (!TryFindSessionRootWithWorld(out var session, out _))
		{
			if (Homm3CustomFactionLawRuntime.TryGetAnyRegisteredDataSide(out side, out _, out source))
				return true;
			return false;
		}

		var sessionWorld = ReadFirstMemberValue(session, GameSymbols.AdventureVisionLaws.SessionWorldMembers)
		                 ?? ReadMemberValue(session, "world");
		if (sessionWorld == null)
		{
			if (Homm3CustomFactionLawRuntime.TryGetAnyRegisteredDataSide(out side, out _, out source))
				return true;
			return false;
		}

		var sessionSides = ReadFirstMemberValue(sessionWorld, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
		                 ?? ReadMemberValue(sessionWorld, "sides");
		if (TryResolvePlayerDataSideFromDataSides(sessionSides, out side, out source))
			return true;

		return Homm3CustomFactionLawRuntime.TryGetAnyRegisteredDataSide(out side, out _, out source);
	}

	private static bool TryResolvePlayerDataSideFromDataSides(object sides, out object side, out string source)
	{
		side = null;
		source = null;
		if (sides == null)
			return false;

		object resolved = null;
		var currentSide = GameMember.FindFirstMethodByNames(
			sides.GetType(),
			Type.EmptyTypes,
			GameSymbols.AdventureVisionLaws.DataSidesCurrentSide);
		if (currentSide != null)
		{
			try { resolved = currentSide.Invoke(sides, Array.Empty<object>()); }
			catch { resolved = null; }
		}
		if (resolved == null)
			resolved = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesCurrentSide.NameHints);
		if (resolved == null)
		{
			var arr = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
			var myIndexObj = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesMyIndexMembers);
			if (arr != null && myIndexObj != null)
			{
				try
				{
					var myIndex = Convert.ToInt32(myIndexObj, CultureInfo.InvariantCulture);
					if (arr is System.Collections.IList list && myIndex >= 0 && myIndex < list.Count)
						resolved = list[myIndex];
					else
					{
						var getter = arr.GetType().GetMethod(
							"get_Item",
							BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
							null,
							new[] { typeof(int) },
							null);
						if (getter != null)
							resolved = getter.Invoke(arr, new object[] { myIndex });
					}
				}
				catch { resolved = null; }
			}
		}
		if (resolved == null)
			resolved = ReadFirstMemberValue(sides, new[] { "lookFor", "get_lookFor", "<lookFor>k__BackingField" });
		if (resolved == null)
			return false;

		var nested = ReadFirstMemberValue(resolved, GameSymbols.AdventureVisionLaws.LookForDataMembers);
		if (nested != null)
			resolved = nested;

		side = resolved;
		source = "dataSides.current";
		return true;
	}

	private static bool TryResolveLiveDataSideFromSessionStatic(out object side, out string source)
	{
		side = null;
		source = null;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			var type = ModActions.GetHexType(typeName)
			           ?? ModActions.GetHexType("Hex.Session." + typeName)
			           ?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;

			object data = null;
			string dataSlot = null;
			try { RuntimeHelpers.RunClassConstructor(type.TypeHandle); }
			catch { /* Il2Cpp type init best-effort */ }
			foreach (var dataName in GameSymbols.AdventureVisionLaws.SessionDataMembers)
			{
				if (TryReadStaticMember(type, dataName, out data) && data != null)
				{
					dataSlot = dataName;
					break;
				}
				data = null;
			}
			if (data == null)
				continue;

			var sides = ReadFirstMemberValue(data, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
			            ?? ReadMemberValue(data, "sides");
			if (!TryResolvePlayerDataSideFromDataSides(sides, out side, out source))
				continue;

			source += " via " + (type.FullName ?? type.Name) + "." + (dataSlot ?? "data");
			return true;
		}

		return false;
	}

	private static bool TryEnumerateLogicWorldHeroEntriesFromDsuStatics(List<object> entries, out string note)
	{
		note = null;
		var type = ResolveDumpLogicRootType();
		if (type == null)
		{
			note = "dsu_type_missing";
			return false;
		}

		var before = entries.Count;
		foreach (var rootEntry in EnumerateStaticReferenceRoots(type))
		{
			if (rootEntry.Value == null)
				continue;
			var logicSides = ReadFirstMemberValue(rootEntry.Value, GameSymbols.CustomFactionLawRuntime.LogicRootSideCollectionMembers);
			if (logicSides != null)
				TryEnumerateLogicSidesFromCollection(logicSides, entries);
		}

		if (entries.Count > before)
		{
			note = "dsu.static heroes=" + (entries.Count - before).ToString(CultureInfo.InvariantCulture);
			return true;
		}

		note = "dsu.static_empty";
		return false;
	}

	private static bool TryResolveHeroNodeFromMapDataSid(string heroSid, out int node, out string source)
	{
		node = -1;
		source = null;
		if (string.IsNullOrWhiteSpace(heroSid))
			return false;
		if (!TryResolveAdventureMapContext(out var mapInstance, out var mapData, out _))
			return false;
		_ = mapInstance;
		var objects = ReadFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (objects == null)
			return false;
		foreach (var row in EnumerateIl2CppListForDump(objects))
		{
			if (row == null)
				continue;
			var sid = ReadFirstStringMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsSidFields);
			if (string.IsNullOrWhiteSpace(sid))
				continue;
			if (!string.Equals(sid.Trim(), heroSid.Trim(), StringComparison.OrdinalIgnoreCase)
			    && sid.IndexOf(heroSid.Trim(), StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			var nodes = ReadMapDataObjectNodes(row);
			if (nodes.Count > 0)
			{
				node = nodes[0];
				source = "mapData.objects.sid";
				return true;
			}
		}
		return false;
	}

	private static bool TryResolveSessionDataRoot(out object data, out string reason)
	{
		data = null;
		reason = null;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;

			try { RuntimeHelpers.RunClassConstructor(type.TypeHandle); }
			catch { /* Il2Cpp type init best-effort */ }

			foreach (var dataName in GameSymbols.AdventureVisionLaws.SessionDataMembers)
			{
				if (TryReadStaticMember(type, dataName, out data) && data != null)
				{
					reason = (type.FullName ?? type.Name) + "." + dataName;
					return true;
				}
				data = null;
			}
		}

		reason = "session Data static unresolved";
		return false;
	}

	private static bool TryFindSessionDataHero(object dataRoot, int heroId, string heroSid, out object dataHero, out string source)
	{
		dataHero = null;
		source = null;
		if (dataRoot == null)
			return false;

		if (TryFindSessionDataHeroOnSide(dataRoot, heroId, heroSid, onlyCurrentSide: true, out dataHero, out source))
			return true;
		if (TryFindSessionDataHeroOnSide(dataRoot, heroId, heroSid, onlyCurrentSide: false, out dataHero, out source))
			return true;
		if (!string.IsNullOrWhiteSpace(heroSid)
		    && TryFindSessionDataHeroByConfigSid(dataRoot, heroSid, out dataHero, out source))
			return true;
		return TryFindSessionDataHeroViaLogicWorld(heroId, heroSid, out dataHero, out source);
	}

	private static bool TryFindSessionDataHeroOnSide(
		object dataRoot,
		int heroId,
		string heroSid,
		bool onlyCurrentSide,
		out object dataHero,
		out string source)
	{
		dataHero = null;
		source = null;

		IEnumerable<object> sides;
		if (onlyCurrentSide)
		{
			if (!TryResolveCurrentDataSide(dataRoot, out var side, out var sideSource))
				return false;
			sides = new[] { side };
			source = sideSource;
		}
		else
		{
			var dataSides = ReadFirstMemberValue(dataRoot, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
			                ?? ReadMemberValue(dataRoot, "sides");
			var arr = dataSides == null
				? null
				: ReadFirstMemberValue(dataSides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
			if (arr is not IEnumerable enumerable)
				return false;
			var sideList = new List<object>(4);
			foreach (var item in enumerable)
			{
				if (item != null)
					sideList.Add(item);
			}
			if (sideList.Count == 0)
				return false;
			sides = sideList;
			source = "dataSides.array";
		}

		foreach (var side in sides)
		{
			if (side == null)
				continue;
			if (!string.IsNullOrWhiteSpace(heroSid))
			{
				var startHeroSid = ReadFirstStringMember(side, new[] { "startHeroSid", "get_startHeroSid" });
				if (!string.IsNullOrWhiteSpace(startHeroSid)
				    && string.Equals(startHeroSid.Trim(), heroSid.Trim(), StringComparison.OrdinalIgnoreCase)
				    && TryResolveDataHeroFromSideContainer(side, heroId, heroSid, out dataHero, out var startSource))
				{
					source = startSource + ":" + source;
					return true;
				}
			}

			if (!TryResolveDataHeroFromSideContainer(side, heroId, heroSid, out dataHero, out var containerSource))
				continue;
			source = containerSource + ":" + source;
			return true;
		}

		return false;
	}

	private static bool TryResolveDataHeroFromSideContainer(
		object side,
		int heroId,
		string heroSid,
		out object dataHero,
		out string source)
	{
		dataHero = null;
		source = null;
		var sideHeroesContainer = ReadFirstMemberValue(side, GameSymbols.AdventureAiDecision.SideHeroesFieldHints);
		if (sideHeroesContainer == null)
			return false;

		var heroEntries = ReadFirstMemberValue(sideHeroesContainer, GameSymbols.AdventureAiDecision.SideHeroesListMembers)
		                  ?? sideHeroesContainer;

		if (heroId <= 0 && !string.IsNullOrWhiteSpace(heroSid))
		{
			foreach (var entry in EnumerateIl2CppListForDump(heroEntries))
			{
				if (entry == null || !(entry is string || entry.GetType().IsPrimitive))
					continue;
				if (!TryConvertDumpInt(entry, out var entryId) || entryId <= 0)
					continue;
				if (!TryLookupDataHeroByIdOnSide(side, entryId, out var sidCandidate))
					continue;
				if (!SessionDataHeroMatches(sidCandidate, -1, heroSid))
					continue;
				dataHero = sidCandidate;
				source = "sideHeroes.heroes.sid";
				return true;
			}
		}

		foreach (var entry in EnumerateIl2CppListForDump(heroEntries))
		{
			if (entry == null)
				continue;

			object candidate = null;
			if (entry is string || entry.GetType().IsPrimitive)
			{
				if (!TryConvertDumpInt(entry, out var entryId) || entryId <= 0)
					continue;
				if (heroId > 0 && entryId != heroId)
					continue;
				if (!TryLookupDataHeroByIdOnSide(side, entryId, out candidate))
					continue;
			}
			else
			{
				candidate = ResolveDataHeroFromSideEntry(entry);
			}

			if (candidate == null)
				continue;
			if (!SessionDataHeroMatches(candidate, heroId, heroSid))
				continue;

			dataHero = candidate;
			source = "sideHeroes.heroes";
			return true;
		}

		return false;
	}

	private static bool TryLookupDataHeroByIdOnSide(object side, int heroId, out object dataHero)
	{
		dataHero = null;
		if (side == null || heroId <= 0)
			return false;

		var sideHeroesContainer = ReadFirstMemberValue(side, GameSymbols.AdventureAiDecision.SideHeroesFieldHints);
		var heroEntries = sideHeroesContainer == null
			? null
			: ReadFirstMemberValue(sideHeroesContainer, GameSymbols.AdventureAiDecision.SideHeroesListMembers);
		if (heroEntries != null)
		{
			foreach (var entry in EnumerateIl2CppListForDump(heroEntries))
			{
				if (entry == null || entry is string || entry.GetType().IsPrimitive)
					continue;
				var candidate = ResolveDataHeroFromSideEntry(entry);
				if (candidate == null)
					continue;
				var id = Homm3MapObjectPropCityResolver.TryGetIntMember(candidate, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints);
				if (id.HasValue && id.Value == heroId)
				{
					dataHero = candidate;
					return true;
				}
			}
		}

		_ = side;
		return false;
	}

	private static bool SessionDataHeroMatches(object dataHero, int heroId, string heroSid)
	{
		if (dataHero == null)
			return false;
		var id = Homm3MapObjectPropCityResolver.TryGetIntMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints);
		var sid = ReadFirstStringMember(dataHero, GameSymbols.AiDriverScreenDump.DataHeroConfigSidFields);
		var idMatch = heroId > 0 && id.HasValue && id.Value == heroId;
		var sidMatch = !string.IsNullOrWhiteSpace(heroSid)
		                && !string.IsNullOrWhiteSpace(sid)
		                && string.Equals(sid.Trim(), heroSid.Trim(), StringComparison.OrdinalIgnoreCase);
		return idMatch || sidMatch;
	}

	private static bool TryFindSessionDataHeroByConfigSid(
		object dataRoot,
		string heroSid,
		out object dataHero,
		out string source)
	{
		dataHero = null;
		source = null;
		if (dataRoot == null || string.IsNullOrWhiteSpace(heroSid))
			return false;

		var dataSides = ReadFirstMemberValue(dataRoot, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
		                ?? ReadMemberValue(dataRoot, "sides");
		var arr = dataSides == null
			? null
			: ReadFirstMemberValue(dataSides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
		if (arr is not IEnumerable enumerable)
			return false;

		foreach (var side in enumerable)
		{
			if (side == null)
				continue;
			if (!TryResolveDataHeroFromSideContainer(side, -1, heroSid, out dataHero, out source))
				continue;
			source = source + ":configSid";
			return true;
		}

		return false;
	}

	private static bool TryFindSessionDataHeroViaLogicWorld(int heroId, string heroSid, out object dataHero, out string source)
	{
		dataHero = null;
		source = null;
		if (!TryEnumerateLogicWorldHeroEntries(out var entries, out _))
			return false;

		for (var i = 0; i < entries.Count; i++)
		{
			var entry = entries[i];
			if (entry == null)
				continue;
			var candidate = ResolveDataHeroFromSideEntry(entry);
			if (candidate == null || !SessionDataHeroMatches(candidate, heroId, heroSid))
				continue;
			dataHero = candidate;
			source = "logicWorld.sideHeroes";
			return true;
		}

		return false;
	}

	private static Type ResolveWorldHeroScanType(string hint)
	{
		if (string.IsNullOrWhiteSpace(hint))
			return null;

		if (string.Equals(hint, "esd", StringComparison.Ordinal)
		    || Array.IndexOf(GameSymbols.HeroMap.DrawerTypeHints, hint) >= 0)
		{
			for (var i = 0; i < GameSymbols.HeroMap.DrawerTypeHints.Length; i++)
			{
				var drawerHint = GameSymbols.HeroMap.DrawerTypeHints[i];
				var type = GameMember.FindType(GameSymbols.HeroMap.DrawerTypeId + "." + drawerHint, drawerHint);
				if (type != null && WorldHeroDrawerTypeLooksValid(type))
					return type;
			}
			return ResolveHeroDrawerDumpTypeByShape();
		}

		if (string.Equals(hint, "etc", StringComparison.Ordinal) || string.Equals(hint, "eta", StringComparison.Ordinal))
		{
			return ResolveAiDumpHexType(GameSymbols.HeroMap.SessionHeroTypeId, new[] { hint })
			       ?? ResolveAiDumpHexType(GameSymbols.HomecomingBoatTravel.WorldHeroTypeId, new[] { hint });
		}

		return ResolveAiDumpHexTypeHint(hint)
		       ?? ResolveAiDumpHexType(GameSymbols.HomecomingBoatTravel.WorldHeroTypeId, new[] { hint });
	}

	private static bool WorldHeroDrawerTypeLooksValid(Type type)
	{
		if (type == null)
			return false;
		if (FindHeroDrawerConstructorForDump(type) == null)
			return false;
		return TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerHeroIdFields)
		       || TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerHeroFields)
		       || TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.HeroConfigFields);
	}

	private static Type ResolveHeroDrawerDumpTypeByShape()
	{
		Type best = null;
		var bestScore = 0;
		foreach (var type in GameMember.EnumerateHexTypes())
		{
			if (type == null || type.IsInterface || type.IsAbstract || type.ContainsGenericParameters)
				continue;
			if (FindHeroDrawerConstructorForDump(type) == null)
				continue;
			var score = 0;
			if (TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerHeroIdFields))
				score += 4;
			if (TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerHeroFields))
				score += 3;
			if (TypeHasAnyInstanceMember(type, GameSymbols.HeroMap.HeroConfigFields))
				score += 2;
			if (score > bestScore)
			{
				bestScore = score;
				best = type;
			}
		}
		return bestScore > 0 ? best : null;
	}

	private static ConstructorInfo FindHeroDrawerConstructorForDump(Type drawerType)
	{
		if (drawerType == null)
			return null;
		ConstructorInfo[] constructors;
		try { constructors = drawerType.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic); }
		catch { return null; }
		for (var i = 0; i < constructors.Length; i++)
		{
			var ctor = constructors[i];
			var ps = ctor.GetParameters();
			if (ps.Length != 7)
				continue;
			if (!IsHeroDrawerParamType(ps[0].ParameterType, typeof(Hero))
			    || !IsHeroDrawerParamType(ps[1].ParameterType, typeof(Vector3))
			    || !IsHeroDrawerParamType(ps[2].ParameterType, typeof(Quaternion))
			    || !IsHeroDrawerParamType(ps[3].ParameterType, typeof(HeroConfig))
			    || !IsHeroDrawerParamType(ps[4].ParameterType, typeof(MountConfig))
			    || !IsHeroDrawerParamType(ps[5].ParameterType, typeof(Transform))
			    || !IsHeroDrawerParamType(ps[6].ParameterType, typeof(float)))
				continue;
			return ctor;
		}
		return null;
	}

	private static bool IsHeroDrawerParamType(Type actual, Type expected)
	{
		if (actual == null || expected == null)
			return false;
		if (actual == expected)
			return true;
		return string.Equals(actual.FullName, expected.FullName, StringComparison.Ordinal)
		       || string.Equals(actual.Name, expected.Name, StringComparison.Ordinal);
	}

	private static bool TypeHasAnyInstanceMember(Type type, string[] names)
	{
		if (type == null || names == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				if (type.GetField(name, flags) != null || type.GetProperty(name, flags) != null)
					return true;
			}
			catch { /* Il2Cpp reflection best-effort */ }
		}
		return false;
	}

	private static bool TryResolveCurrentDataSide(object dataRoot, out object side, out string source)
	{
		side = null;
		source = null;
		if (dataRoot == null)
			return false;

		var sides = ReadFirstMemberValue(dataRoot, GameSymbols.AdventureVisionLaws.WorldSidesMembers)
		            ?? ReadMemberValue(dataRoot, "sides");
		if (sides == null)
			return false;

		object resolved = null;
		var currentSide = GameMember.FindFirstMethodByNames(
			sides.GetType(),
			Type.EmptyTypes,
			GameSymbols.AdventureVisionLaws.DataSidesCurrentSide);
		if (currentSide != null)
		{
			try { resolved = currentSide.Invoke(sides, Array.Empty<object>()); }
			catch { resolved = null; }
		}
		if (resolved == null)
			resolved = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesCurrentSide.NameHints);
		if (resolved == null)
		{
			var arr = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesArrayMembers);
			var myIndexObj = ReadFirstMemberValue(sides, GameSymbols.AdventureVisionLaws.DataSidesMyIndexMembers);
			if (arr != null && myIndexObj != null)
			{
				try
				{
					var myIndex = Convert.ToInt32(myIndexObj, CultureInfo.InvariantCulture);
					if (arr is System.Collections.IList list && myIndex >= 0 && myIndex < list.Count)
						resolved = list[myIndex];
					else
					{
						var getter = arr.GetType().GetMethod(
							"get_Item",
							BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
							null,
							new[] { typeof(int) },
							null);
						if (getter != null)
							resolved = getter.Invoke(arr, new object[] { myIndex });
					}
				}
				catch { resolved = null; }
			}
		}
		if (resolved == null)
			return false;

		side = resolved;
		source = "dataSides.current";
		return true;
	}

	private static object ResolveDataHeroFromSideEntry(object entry)
	{
		if (entry == null)
			return null;
		if (LooksLikeDataHero(entry))
			return entry;

		var directDataHero = ReadFirstMemberValue(entry, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers)
		                     ?? ReadFirstMemberValue(entry, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers)
		                     ?? ReadFirstMemberValue(entry, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers)
		                     ?? ReadFirstMemberValue(entry, GameSymbols.CustomFactionLawRuntime.LogicHeroDataHeroMembers);
		if (LooksLikeDataHero(directDataHero))
			return directDataHero;

		var logicHero = ReadFirstMemberValue(entry, GameSymbols.HeroMap.DrawerHeroFields)
		                ?? ReadFirstMemberValue(entry, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers)
		                ?? ReadFirstMemberValue(entry, GameSymbols.HeroMap.SessionHeroLogicFields);
		if (logicHero == null)
			return null;

		var dataHero = ReadFirstMemberValue(logicHero, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers)
		               ?? ReadFirstMemberValue(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers)
		               ?? ReadFirstMemberValue(logicHero, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers)
		               ?? ReadFirstMemberValue(logicHero, GameSymbols.CustomFactionLawRuntime.LogicHeroDataHeroMembers);
		return LooksLikeDataHero(dataHero) ? dataHero : null;
	}

	private static bool LooksLikeDataHero(object value)
	{
		return value != null
		       && (TryReadDumpIntMember(value, GameSymbols.AdventureAiDecision.DataHeroNodeFieldHints, out _)
		           || TryReadDumpIntMember(value, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out _)
		           || ReadFirstMemberValue(value, GameSymbols.HomecomingBoatTravel.DataHeroAdditionalStatsMembers) != null);
	}

	private static bool IsUnityEngineFamilyTypeNameForDump(string typeName)
	{
		if (string.IsNullOrEmpty(typeName))
			return false;
		return typeName.StartsWith("UnityEngine.", StringComparison.Ordinal)
		       || typeName.StartsWith("Unity.", StringComparison.Ordinal);
	}

	private static bool TryReadDumpIntMember(object obj, string[] names, out int value)
	{
		value = 0;
		if (obj == null || names == null)
			return false;
		var fromResolver = Homm3MapObjectPropCityResolver.TryGetIntMember(obj, names);
		if (fromResolver.HasValue)
		{
			value = fromResolver.Value;
			return true;
		}
		for (var i = 0; i < names.Length; i++)
		{
			var raw = ReadMemberValue(obj, names[i]);
			if (raw != null && TryConvertDumpInt(raw, out value))
				return true;
		}
		return false;
	}

	private static bool TryConvertDumpInt(object raw, out int value)
	{
		value = 0;
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

	private static MapWorldScreenPoint CloneMapWorldScreenPoint(MapWorldScreenPoint source)
	{
		if (source == null)
			return null;
		return new MapWorldScreenPoint
		{
			X = source.X,
			Y = source.Y,
			W = source.W,
			H = source.H,
			RectJson = source.RectJson,
			OnScreen = source.OnScreen,
			FogVisible = source.FogVisible,
			Path = source.Path,
			InstanceId = source.InstanceId,
			Node = source.Node,
			ResolveSource = source.ResolveSource
		};
	}

	private static void BuildWorldPointRect(Vector3 world, Camera camera, bool cameraOk, out MapWorldScreenPoint point)
	{
		var size = GameSymbols.AiDriverScreenDump.MapWorldPointRectSize;
		point = new MapWorldScreenPoint
		{
			X = 0f,
			Y = 0f,
			W = 0f,
			H = 0f,
			RectJson = "{\"x\":0,\"y\":0,\"width\":0,\"height\":0}",
			OnScreen = false
		};
		if (!cameraOk || camera == null)
			return;

		Vector3 screen;
		try { screen = camera.WorldToScreenPoint(world); }
		catch { return; }

		if (screen.z <= 0f)
			return;

		var half = size * 0.5f;
		var x = screen.x - half;
		var y = screen.y - half;
		point.X = x;
		point.Y = y;
		point.W = size;
		point.H = size;
		point.RectJson = "{"
			+ "\"x\":" + x.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"y\":" + y.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"width\":" + size.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"height\":" + size.ToString("0.###", CultureInfo.InvariantCulture)
			+ "}";
		point.OnScreen = RectIntersectsScreen(x, y, size, size, Screen.width, Screen.height);
	}

	private static Type ResolveAiDumpHexType(string typeId, string[] hints)
	{
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = GameMember.FindType(
				(typeId ?? "ai.dump") + "." + hint,
				hint,
				() => ResolveAiDumpHexTypeHint(hint));
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type ResolveAiDumpHexTypeHint(string hint)
	{
		if (string.IsNullOrWhiteSpace(hint))
			return null;
		var fromPlugin = ModActions.GetHexType(hint)
			?? ModActions.GetHexType("Hex." + hint)
			?? ModActions.GetHexType("Hex.Map." + hint);
		if (fromPlugin != null)
			return fromPlugin;
		try
		{
			var assembly = typeof(MapData).Assembly;
			return assembly.GetType(hint, false)
			       ?? assembly.GetType("Hex.Map." + hint, false)
			       ?? assembly.GetType("Hex." + hint, false);
		}
		catch
		{
			return null;
		}
	}

	private static string DescribeUnityObjectPath(UnityObject obj)
	{
		try
		{
			if (obj is Component component && component && component.transform)
				return UnityPath(component.transform);
			return obj ? (obj.name ?? "") : "";
		}
		catch
		{
			return "";
		}
	}

	private static object ReadFirstMemberValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = ReadMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static string ReadFirstStringMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		var native = DeobfInteropCompat.TryReadNativeStringMember(obj, names);
		if (!string.IsNullOrWhiteSpace(native))
			return native.Trim();
		for (var i = 0; i < names.Length; i++)
		{
			var value = ReadMemberValue(obj, names[i]) as string;
			if (!string.IsNullOrWhiteSpace(value))
				return value.Trim();
		}
		return null;
	}

	private static bool? ReadFirstBoolMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = ReadMemberValue(obj, names[i]);
			if (value is bool b)
				return b;
		}
		return null;
	}

	private static object ReadMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			try
			{
				var field = t.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { /* keep searching */ }
			try
			{
				var prop = t.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj, null);
			}
			catch { /* keep searching */ }
			try
			{
				var method = t.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, null);
			}
			catch { /* keep searching */ }
		}
		return null;
	}

	private static IEnumerable<object> EnumerateIl2CppListForDump(object listObj)
	{
		if (listObj == null)
			yield break;
		var type = listObj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		PropertyInfo countProp = null;
		MethodInfo countGetter = null;
		MethodInfo itemGetter = null;
		for (var t = type; t != null && countProp == null; t = t.BaseType)
		{
			try { countProp = t.GetProperty("Count", flags); }
			catch { countProp = null; }
		}
		if (countProp == null)
		{
			for (var t = type; t != null && countGetter == null; t = t.BaseType)
			{
				try { countGetter = t.GetMethod("get_Count", flags, null, Type.EmptyTypes, null); }
				catch { countGetter = null; }
			}
		}
		for (var t = type; t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		if (itemGetter == null)
		{
			if (listObj is not IEnumerable enumerable)
				yield break;
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		int count;
		try
		{
			count = countProp != null
				? Convert.ToInt32(countProp.GetValue(listObj), CultureInfo.InvariantCulture)
				: Convert.ToInt32(countGetter.Invoke(listObj, null), CultureInfo.InvariantCulture);
		}
		catch
		{
			yield break;
		}

		for (var i = 0; i < count; i++)
		{
			object item = null;
			try { item = itemGetter.Invoke(listObj, new object[] { i }); }
			catch { item = null; }
			if (item != null)
				yield return item;
		}
	}
}
