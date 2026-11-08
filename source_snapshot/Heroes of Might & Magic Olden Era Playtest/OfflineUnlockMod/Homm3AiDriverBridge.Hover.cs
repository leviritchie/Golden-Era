using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using Il2CppInterop.Runtime;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static partial class Homm3AiDriverBridge
{
	internal const string HoverSnapshotSchemaVersion = "ai-driver.v1.hover-snapshot";
	private const string HoverGrepKey = "HOMM3_AI_HOVER";
	private static string _lastHoverFingerprint = "";
	private static int _lastHoverEmitFrame = int.MinValue;
	private const int HoverDebounceFrames = 2;
	private const int HoverTickMinFrameGap = 10;
	// Scene events invalidate immediately; this bounded audit also catches roots added without a scene transition.
	private const int MapHoverWorldRootRefreshFrameInterval = 60;
	private const int MapHoverWorldRootRetryFrameInterval = 10;
	private static int _lastHoverTickFrame = int.MinValue;
	private static Vector3 _lastHoverTickPointer;
	private static Type _cachedMapHoverOwnerType;
	private static Type _cachedMapHoverCursorOwnerType;
	private static GameObject _cachedMapHoverWorldRoot;
	private static int _cachedMapHoverWorldRootInstanceId;
	private static int _cachedMapHoverWorldSceneHandle = -1;
	private static Component _cachedMapHoverOwner;
	private static int _cachedMapHoverWorldRootScanFrame = int.MinValue;
	private static int _cachedMapHoverWorldRootScanSceneCount = -1;
	private static string _cachedMapHoverWorldRootScanGap;
	private static bool _mapHoverSceneEventsSubscribed;

	internal static string BuildHoverSnapshotResponse(string id)
	{
		return OkResponse(id, "\"hover\":" + BuildHoverSnapshotJson(writeEventFile: false));
	}

	internal static void TickHoverMonitor()
	{
		try
		{
			var frame = Time.frameCount;
			var pointer = UnityEngine.Input.mousePosition;
			var moved = (pointer - _lastHoverTickPointer).sqrMagnitude > 4f;
			if (!moved && _lastHoverTickFrame != int.MinValue
			    && frame - _lastHoverTickFrame < HoverTickMinFrameGap)
				return;
			_lastHoverTickFrame = frame;
			_lastHoverTickPointer = pointer;
			BuildHoverSnapshotJson(writeEventFile: true);
			TickFocusFromHover();
		}
		catch (Exception ex)
		{
			_log?.LogWarning(HoverGrepKey + " tick failed: " + ex.Message);
		}
	}

	internal static string BuildHoverSnapshotJson(bool writeEventFile)
	{
		var gaps = new List<string>();
		var mode = InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
		var pointer = UnityEngine.Input.mousePosition;
		var lane = "none";
		var fingerprint = "none";
		var path = "";
		var label = "";
		var name = "";
		int? node = null;

		if (TryReadUiHover(pointer, out var uiPath, out var uiLabel, out var uiName, out var uiFp))
		{
			lane = "ui";
			path = uiPath;
			label = uiLabel;
			name = uiName;
			fingerprint = uiFp;
		}
		else
		{
			gaps.Add(GapJson("ui_hover_none", "EventSystem raycast under pointer did not hit an active UI graphic.", false));
		}

		// Map hover only on adventure_map — avoid typed owner scans on menus/town/battle.
		if (string.Equals(mode, "adventure_map", StringComparison.Ordinal))
		{
			if (TryReadMapHoverNode(out var mapNode, out var mapGap))
			{
				node = mapNode;
				if (lane == "none")
				{
					lane = "map";
					fingerprint = "map-node|" + mapNode.ToString(CultureInfo.InvariantCulture);
				}
				gaps.Add(GapJson(
					"map_hover_name_unproven",
					"Map hover node " + mapNode.ToString(CultureInfo.InvariantCulture) + " was read; object sid/name resolve remains unproven.",
					false));
			}
			else if (!string.IsNullOrEmpty(mapGap))
			{
				gaps.Add(GapJson("map_hover_unavailable", mapGap, false));
			}
		}

		var hoverJson = "{"
			+ "\"lane\":\"" + EscapeJson(lane) + "\","
			+ "\"fingerprint\":\"" + EscapeJson(fingerprint) + "\"";
		if (!string.IsNullOrEmpty(path))
			hoverJson += ",\"path\":\"" + EscapeJson(path) + "\"";
		if (!string.IsNullOrEmpty(label))
			hoverJson += ",\"label\":\"" + EscapeJson(label) + "\"";
		if (!string.IsNullOrEmpty(name))
			hoverJson += ",\"name\":\"" + EscapeJson(name) + "\"";
		if (node.HasValue)
			hoverJson += ",\"node\":" + node.Value.ToString(CultureInfo.InvariantCulture);
		hoverJson += "}";

		var json = "{"
			+ "\"schemaVersion\":\"" + HoverSnapshotSchemaVersion + "\","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(mode) + "\","
			+ "\"timestamp\":\"" + EscapeJson(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) + "\","
			+ "\"pointer\":{\"x\":" + pointer.x.ToString("0.###", CultureInfo.InvariantCulture)
			+ ",\"y\":" + pointer.y.ToString("0.###", CultureInfo.InvariantCulture) + "},"
			+ "\"hover\":" + hoverJson + ","
			+ "\"gaps\":[" + string.Join(",", gaps) + "]"
			+ "}";

		if (writeEventFile
		    && !string.Equals(fingerprint, _lastHoverFingerprint, StringComparison.Ordinal)
		    && (_lastHoverEmitFrame == int.MinValue
		        || Time.frameCount - _lastHoverEmitFrame >= HoverDebounceFrames))
		{
			_lastHoverFingerprint = fingerprint;
			_lastHoverEmitFrame = Time.frameCount;
			WriteHoverEventFile(json);
			_log?.LogWarning(HoverGrepKey + " change lane=" + lane + " fp=" + fingerprint + " label=" + label);
		}

		return json;
	}

	private static void WriteHoverEventFile(string json)
	{
		if (string.IsNullOrWhiteSpace(BridgeDirectory))
			return;
		try
		{
			var eventsDir = System.IO.Path.Combine(BridgeDirectory, "events");
			System.IO.Directory.CreateDirectory(eventsDir);
			var fileName = "hover_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture)
				+ "_" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ".json";
			WriteAllTextAtomic(System.IO.Path.Combine(eventsDir, fileName), json);
			WriteAllTextAtomic(System.IO.Path.Combine(BridgeDirectory, "hover_latest.json"), json);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(HoverGrepKey + " event write failed: " + ex.Message);
		}
	}

	private static bool TryReadUiHover(Vector3 screenPoint, out string path, out string label, out string name, out string fingerprint)
	{
		path = "";
		label = "";
		name = "";
		fingerprint = "";
		var eventSystem = EventSystem.current;
		if (!eventSystem)
			return false;

		var pointer = new PointerEventData(eventSystem) { position = new Vector2(screenPoint.x, screenPoint.y) };
		var results = new Il2CppSystem.Collections.Generic.List<RaycastResult>();
		eventSystem.RaycastAll(pointer, results);
		if (results == null || results.Count == 0)
			return false;

		GameObject go = null;
		for (var i = 0; i < results.Count; i++)
		{
			var hit = results[i].gameObject;
			if (hit && hit.activeInHierarchy)
			{
				go = hit;
				break;
			}
		}
		if (!go)
			return false;

		path = UnityPath(go.transform);
		name = go.name ?? "";
		label = UiText(go);
		if (string.IsNullOrEmpty(label))
		{
			var selectable = go.GetComponentInParent<Selectable>();
			if (selectable)
				label = UiText(selectable.gameObject);
		}
		if (string.IsNullOrEmpty(label) || IsPlaceholderSpeechLabel(label))
			label = SanitizeSpeechLabel(name);
		if (IsPlaceholderSpeechLabel(label))
			label = "";
		var sceneName = go.scene.IsValid() ? go.scene.name ?? "" : "";
		fingerprint = "ui|" + sceneName + "|" + path + "|" + go.GetInstanceID().ToString(CultureInfo.InvariantCulture);
		return true;
	}

	private static bool TryReadMapHoverNode(out int node, out string gap)
	{
		node = -1;
		gap = null;
		try
		{
			var owner = ResolveCachedMapHoverOwner(out gap);
			if (owner == null)
				return false;
			if (!TryReadHoverContextFromWorldOwner(owner, out var hoverContext, out gap))
				return false;
			if (TryReadNodeFromHoverContextObject(hoverContext, out node, out gap))
			{
				if (node >= 0)
					return true;
				if (node == -1)
				{
					gap = null;
					return false;
				}
				gap = "HoverContext returned invalid negative node " + node.ToString(CultureInfo.InvariantCulture) + ".";
				return false;
			}
			return false;
		}
		catch (Exception ex)
		{
			gap = "HoverContext scan failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static Component ResolveCachedMapHoverOwner(out string gap)
	{
		gap = null;
		if (!TryFindUniqueWorldRoot(out var worldRoot, out var worldScene, out gap))
		{
			InvalidateCachedMapHoverOwner();
			return null;
		}

		var worldRootInstanceId = worldRoot.GetInstanceID();
		if (!_cachedMapHoverWorldRoot
		    || _cachedMapHoverWorldRootInstanceId != worldRootInstanceId
		    || _cachedMapHoverWorldSceneHandle != worldScene.handle)
		{
			_cachedMapHoverOwner = null;
			_cachedMapHoverWorldRoot = worldRoot;
			_cachedMapHoverWorldRootInstanceId = worldRootInstanceId;
			_cachedMapHoverWorldSceneHandle = worldScene.handle;
		}

		if (_cachedMapHoverOwner && _cachedMapHoverOwner.gameObject
		    && _cachedMapHoverOwner.gameObject.GetInstanceID() == worldRootInstanceId)
			return _cachedMapHoverOwner;

		_cachedMapHoverOwner = null;
		if (_cachedMapHoverOwnerType == null)
			_cachedMapHoverOwnerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldOwner);
		if (_cachedMapHoverOwnerType == null)
		{
			gap = "WORLD root found in scene '" + worldScene.name + "' but the pinned WorldOwner type is unavailable.";
			return null;
		}

		try
		{
			var nativeOwner = worldRoot.GetComponent(Il2CppType.From(_cachedMapHoverOwnerType));
			if (nativeOwner)
			{
				// GetComponent(Type) returns the base Component proxy. Re-wrap its native pointer as
				// the pinned CLR type before reflecting generated interop properties on the owner.
				var owner = Activator.CreateInstance(_cachedMapHoverOwnerType, nativeOwner.Pointer) as Component;
				if (owner && owner.GetType() == _cachedMapHoverOwnerType
				    && owner.gameObject && owner.gameObject.GetInstanceID() == worldRootInstanceId)
					return _cachedMapHoverOwner = owner;
				gap = "WORLD root returned a component that could not be re-wrapped as pinned owner type "
					+ _cachedMapHoverOwnerType.FullName + ".";
				return null;
			}
			gap = "WORLD root in scene '" + worldScene.name + "' has no component of pinned type "
				+ _cachedMapHoverOwnerType.FullName + ".";
		}
		catch (Exception ex)
		{
			gap = "WORLD owner lookup failed: " + ex.GetType().Name + ": " + ex.Message;
		}
		return null;
	}

	private static bool TryFindUniqueWorldRoot(out GameObject worldRoot, out Scene worldScene, out string gap)
	{
		worldRoot = null;
		worldScene = default;
		gap = null;
		EnsureMapHoverSceneEventsSubscribed();
		var frame = Time.frameCount;
		var sceneCount = SceneManager.sceneCount;
		var scanAge = _cachedMapHoverWorldRootScanFrame == int.MinValue
			? int.MaxValue
			: frame - _cachedMapHoverWorldRootScanFrame;
		var rootIsValid = _cachedMapHoverWorldRoot
			&& string.Equals(_cachedMapHoverWorldRoot.name, GameSymbols.HomecomingBoatTravel.WorldRootName, StringComparison.Ordinal)
			&& _cachedMapHoverWorldRoot.transform.parent == null
			&& _cachedMapHoverWorldRoot.scene.IsValid() && _cachedMapHoverWorldRoot.scene.isLoaded
			&& _cachedMapHoverWorldRoot.scene.handle == _cachedMapHoverWorldSceneHandle;
		var refreshInterval = _cachedMapHoverWorldRoot ? MapHoverWorldRootRefreshFrameInterval : MapHoverWorldRootRetryFrameInterval;
		if (_cachedMapHoverWorldRootScanFrame != int.MinValue && scanAge >= 0
		    && scanAge < refreshInterval && sceneCount == _cachedMapHoverWorldRootScanSceneCount)
		{
			if (rootIsValid)
			{
				worldRoot = _cachedMapHoverWorldRoot;
				worldScene = _cachedMapHoverWorldRoot.scene;
				return true;
			}
			if (!string.IsNullOrEmpty(_cachedMapHoverWorldRootScanGap))
			{
				gap = _cachedMapHoverWorldRootScanGap;
				return false;
			}
		}

		var rootName = GameSymbols.HomecomingBoatTravel.WorldRootName;
		for (var i = 0; i < SceneManager.sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;

			GameObject[] roots;
			try { roots = scene.GetRootGameObjects(); }
			catch (Exception ex)
			{
				gap = "Loaded scene '" + scene.name + "' roots could not be read while resolving WORLD: " + ex.GetType().Name + ": " + ex.Message;
				CacheMapHoverWorldRootScan(frame, sceneCount, null, default, gap);
				return false;
			}

			foreach (var root in roots)
			{
				if (!root || !string.Equals(root.name, rootName, StringComparison.Ordinal))
					continue;
				if (worldRoot && worldRoot.GetInstanceID() != root.GetInstanceID())
				{
					gap = "Multiple loaded scene roots named '" + rootName + "'; refusing ambiguous hover ownership.";
					CacheMapHoverWorldRootScan(frame, sceneCount, null, default, gap);
					return false;
				}
				worldRoot = root;
				worldScene = scene;
			}
		}

		if (worldRoot)
		{
			CacheMapHoverWorldRootScan(frame, sceneCount, worldRoot, worldScene, null);
			return true;
		}
		gap = "No loaded scene root named '" + rootName + "'.";
		CacheMapHoverWorldRootScan(frame, sceneCount, null, default, gap);
		return false;
	}

	private static void CacheMapHoverWorldRootScan(int frame, int sceneCount, GameObject root, Scene scene, string gap)
	{
		_cachedMapHoverWorldRootScanFrame = frame;
		_cachedMapHoverWorldRootScanSceneCount = sceneCount;
		_cachedMapHoverWorldRootScanGap = gap;
		_cachedMapHoverWorldRoot = root;
		_cachedMapHoverWorldRootInstanceId = root ? root.GetInstanceID() : 0;
		_cachedMapHoverWorldSceneHandle = root ? scene.handle : -1;
	}

	private static void EnsureMapHoverSceneEventsSubscribed()
	{
		if (_mapHoverSceneEventsSubscribed)
			return;
		var loadedAction = new Action<Scene, LoadSceneMode>(OnMapHoverSceneLoaded);
		var unloadedAction = new Action<Scene>(OnMapHoverSceneUnloaded);
		SceneManager.sceneLoaded += (UnityEngine.Events.UnityAction<Scene, LoadSceneMode>)loadedAction;
		SceneManager.sceneUnloaded += (UnityEngine.Events.UnityAction<Scene>)unloadedAction;
		_mapHoverSceneEventsSubscribed = true;
	}

	private static void OnMapHoverSceneLoaded(Scene scene, LoadSceneMode mode) => InvalidateMapHoverWorldRootScan();
	private static void OnMapHoverSceneUnloaded(Scene scene) => InvalidateMapHoverWorldRootScan();

	private static void InvalidateMapHoverWorldRootScan()
	{
		_cachedMapHoverWorldRootScanFrame = int.MinValue;
		_cachedMapHoverWorldRootScanSceneCount = -1;
		_cachedMapHoverWorldRootScanGap = null;
		_cachedMapHoverWorldRoot = null;
		_cachedMapHoverWorldRootInstanceId = 0;
		_cachedMapHoverWorldSceneHandle = -1;
		_cachedMapHoverOwner = null;
	}

	private static void InvalidateCachedMapHoverOwner()
	{
		_cachedMapHoverOwner = null;
	}

	private static bool TryReadHoverContextFromWorldOwner(object worldOwner, out object hoverContext, out string gap)
	{
		hoverContext = null;
		gap = null;
		if (!TryReadUniqueInstanceMemberValue(
			worldOwner,
			GameSymbols.HomecomingWaterPresentation.MapHoverOwnerStateContainerMembers,
			"WORLD owner state container",
			out var stateContainer,
			out gap))
			return false;
		if (!TryReadUniqueInstanceMemberValue(
			stateContainer,
			GameSymbols.HomecomingWaterPresentation.MapHoverStateCursorOwnerMembers,
			"WORLD state cursor owner",
			out var cursorOwner,
			out gap))
			return false;

		if (_cachedMapHoverCursorOwnerType == null)
			_cachedMapHoverCursorOwnerType = GameMember.FindTypeFromHints(
				GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorOwnerTypeId,
				GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorOwnerTypeHints);
		if (_cachedMapHoverCursorOwnerType == null)
		{
			gap = "Pinned empty-terrain cursor owner type is unavailable.";
			return false;
		}
		var cursorOwnerType = cursorOwner.GetType();
		if (!_cachedMapHoverCursorOwnerType.IsAssignableFrom(cursorOwnerType))
		{
			gap = "WORLD state cursor owner has unexpected type " + cursorOwnerType.FullName
				+ " (expected " + _cachedMapHoverCursorOwnerType.FullName + ").";
			return false;
		}

		return TryReadUniqueInstanceMemberValue(
			cursorOwner,
			GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorHoverContextMembers,
			"empty-terrain cursor hover context",
			out hoverContext,
			out gap);
	}

	private static bool TryReadUniqueInstanceMemberValue(
		object source,
		string[] memberHints,
		string semanticMember,
		out object value,
		out string gap)
	{
		value = null;
		gap = null;
		if (source == null)
		{
			gap = semanticMember + " source was null.";
			return false;
		}

		var matches = new List<MemberInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		for (var current = source.GetType(); current != null; current = current.BaseType)
		{
			foreach (var hint in memberHints ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				FieldInfo field;
				try { field = current.GetField(hint, flags); }
				catch (Exception ex)
				{
					gap = semanticMember + " metadata lookup failed on " + current.FullName + ": " + ex.GetType().Name + ": " + ex.Message;
					return false;
				}
				if (field != null && !matches.Contains(field))
					matches.Add(field);
				PropertyInfo property;
				try { property = current.GetProperty(hint, flags); }
				catch (Exception ex)
				{
					gap = semanticMember + " property metadata lookup failed on " + current.FullName + ": "
						+ ex.GetType().Name + ": " + ex.Message;
					return false;
				}
				if (property != null && !matches.Contains(property))
					matches.Add(property);
			}
		}

		if (matches.Count != 1)
		{
			gap = semanticMember + " resolved " + matches.Count.ToString(CultureInfo.InvariantCulture)
				+ " instance fields/properties on " + source.GetType().FullName + "; refusing ambiguity or missing pin.";
			return false;
		}

		var member = matches[0];
		try
		{
			if (member is FieldInfo field)
				value = field.GetValue(source);
			else if (member is PropertyInfo property)
			{
				var getter = property.GetGetMethod(nonPublic: true);
				if (getter == null || getter.IsStatic || property.GetIndexParameters().Length != 0)
				{
					gap = semanticMember + " property '" + property.Name + "' is not a readable instance property.";
					return false;
				}
				value = property.GetValue(source, null);
			}
			else
			{
				gap = semanticMember + " resolved unsupported member kind " + member.MemberType + ".";
				return false;
			}
		}
		catch (Exception ex)
		{
			var cause = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
			gap = semanticMember + " read failed: " + cause.GetType().Name + ": " + cause.Message;
			return false;
		}
		if (value != null)
			return true;
		gap = semanticMember + " member '" + member.Name + "' was null.";
		return false;
	}

	private static bool TryReadNodeFromHoverContextObject(object hoverContext, out int node, out string gap)
	{
		node = -1;
		gap = null;
		if (hoverContext == null)
		{
			gap = "HoverContext was null while resolving the pinned node accessor.";
			return false;
		}

		var type = hoverContext.GetType();
		foreach (var memberName in GameSymbols.HomecomingWaterPresentation.HoverContextNodeMembers)
		{
			if (string.IsNullOrWhiteSpace(memberName))
				continue;

			var expectsMethod = memberName.StartsWith("Method_", StringComparison.Ordinal)
				|| memberName.StartsWith("get_", StringComparison.Ordinal);
			var accessors = new List<MemberInfo>();
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic
				| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
			for (var current = type; current != null; current = current.BaseType)
			{
				if (expectsMethod)
				{
					MethodInfo[] methods;
					try { methods = current.GetMethods(flags); }
					catch (Exception ex)
					{
						gap = "HoverContext node method metadata lookup failed on " + current.FullName + ": "
							+ ex.GetType().Name + ": " + ex.Message;
						return false;
					}
					foreach (var method in methods)
						if (string.Equals(method.Name, memberName, StringComparison.Ordinal))
							accessors.Add(method);
				}
				else
				{
					FieldInfo field;
					try { field = current.GetField(memberName, flags); }
					catch (Exception ex)
					{
						gap = "HoverContext node field metadata lookup failed on " + current.FullName + ": "
							+ ex.GetType().Name + ": " + ex.Message;
						return false;
					}
					if (field != null)
						accessors.Add(field);
					PropertyInfo property;
					try { property = current.GetProperty(memberName, flags); }
					catch (Exception ex)
					{
						gap = "HoverContext node property metadata lookup failed on " + current.FullName + ": "
							+ ex.GetType().Name + ": " + ex.Message;
						return false;
					}
					if (property != null)
						accessors.Add(property);
				}
			}

			if (accessors.Count == 0)
				continue;
			if (accessors.Count != 1)
			{
				gap = "HoverContext node pin '" + memberName + "' matched "
					+ accessors.Count.ToString(CultureInfo.InvariantCulture) + " accessors; refusing ambiguity.";
				return false;
			}

			var accessor = accessors[0];
			if (accessor is MethodInfo methodInfo)
			{
				ParameterInfo[] parameters;
				try { parameters = methodInfo.GetParameters(); }
				catch (Exception ex)
				{
					gap = "HoverContext node method parameter metadata failed for '" + memberName + "': "
						+ ex.GetType().Name + ": " + ex.Message;
					return false;
				}
				if (methodInfo.IsStatic || methodInfo.ContainsGenericParameters
				    || parameters.Length != 0 || methodInfo.ReturnType != typeof(int))
				{
					gap = "HoverContext node method pin '" + memberName
						+ "' did not match a non-static, non-generic Int32().";
					return false;
				}
			}
			else if (accessor is FieldInfo fieldInfo)
			{
				if (fieldInfo.IsStatic || fieldInfo.FieldType != typeof(int))
				{
					gap = "HoverContext node field pin '" + memberName
						+ "' did not match a non-static Int32 field.";
					return false;
				}
			}
			else if (accessor is PropertyInfo propertyInfo)
			{
				MethodInfo getter;
				try { getter = propertyInfo.GetGetMethod(nonPublic: true); }
				catch (Exception ex)
				{
					gap = "HoverContext node property getter metadata failed for '" + memberName + "': "
						+ ex.GetType().Name + ": " + ex.Message;
					return false;
				}
				if (getter == null || getter.IsStatic || propertyInfo.GetIndexParameters().Length != 0
				    || propertyInfo.PropertyType != typeof(int))
				{
					gap = "HoverContext node property pin '" + memberName
						+ "' did not match a readable non-static Int32 property without index parameters.";
					return false;
				}
			}
			else
			{
				gap = "HoverContext node pin '" + memberName + "' resolved unsupported member kind "
					+ accessor.MemberType + ".";
				return false;
			}

			try
			{
				if (accessor is MethodInfo method)
					node = (int)method.Invoke(hoverContext, null);
				else if (accessor is FieldInfo field)
					node = (int)field.GetValue(hoverContext);
				else if (accessor is PropertyInfo property)
					node = (int)property.GetValue(hoverContext, null);
			}
			catch (Exception ex)
			{
				var cause = ex;
				while (cause is TargetInvocationException && cause.InnerException != null)
					cause = cause.InnerException;
				gap = "HoverContext node pin '" + memberName + "' read failed: "
					+ cause.GetType().Name + ": " + cause.Message;
				return false;
			}
			return true;
		}

		gap = "No pinned Int32 hover-node accessor was found on " + type.FullName + ".";
		return false;
	}
}
