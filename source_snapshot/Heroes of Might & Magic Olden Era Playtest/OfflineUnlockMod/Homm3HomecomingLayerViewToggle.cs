using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using BepInEx.Logging;
using Hex.Map;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class Homm3HomecomingLayerViewToggleBootstrap
{
	private const string GoName = "HOMM3_HOMECOMING_LAYER_VIEW_TOGGLE";
	private static bool _registered;
	private static bool _attached;
	private static ManualLogSource _log;

	internal static void Ensure(ManualLogSource log)
	{
		_log = log;
		if (_attached)
			return;
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3HomecomingLayerViewToggleBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<Homm3HomecomingLayerViewToggleBehaviour>() == null)
			{
				_log?.LogError(Homm3HomecomingLayerViewToggle.LogPrefix + " host_add_component_failed");
				return;
			}

			UnityObject.DontDestroyOnLoad(go);
			_attached = true;
			_log?.LogInfo(Homm3HomecomingLayerViewToggle.LogPrefix + " host_attached generic_two_view_atlas=true native_view_switching=live_probe_validated button_art=iam003_iam010 button_click=unvalidated");
		}
		catch (Exception ex)
		{
			_log?.LogError(Homm3HomecomingLayerViewToggle.LogPrefix + " host_attach_failed error=" + FormatException(ex));
		}
	}

	private static string FormatException(Exception ex)
	{
		return ex == null ? "unknown" : ex.GetType().Name + ": " + ex.Message;
	}

	internal static ManualLogSource Log => _log ?? Plugin.LogSource;
}

public sealed class Homm3HomecomingLayerViewToggleBehaviour : MonoBehaviour
{
	private void OnGUI()
	{
		var evt = Event.current;
		if (evt == null)
			return;

		// Absolute DrawTexture/hit-test only — skip Layout and other IMGUI passes.
		if (evt.type != EventType.Repaint && evt.type != EventType.MouseDown)
			return;

		// Hide immediately when adventure HUD is gone (menus / town / battle), even if map data still resolves.
		if (!Homm3HomecomingLayerViewToggle.IsAdventureHudVisible())
			return;

		if (!Homm3HomecomingLayerViewToggle.TryReadLayerState(out var state, out var reason, out var targetMapSeen))
		{
			if (targetMapSeen)
				Homm3HomecomingLayerViewToggle.LogTargetMapFailure(reason);
			return;
		}

		if (!Homm3HomecomingLayerViewToggle.TryEnsureButtonTextures())
			return;

		GUI.depth = -5000;
		var rect = Homm3HomecomingLayerViewToggle.ButtonRect();
		var showUndergroundIcon = state.CurrentIndex == Homm3HomecomingLayerViewToggle.SurfaceIndex;
		var hovering = rect.Contains(evt.mousePosition);
		var pressed = hovering && Input.GetMouseButton(0);
		var texture = Homm3HomecomingLayerViewToggle.ResolveButtonTexture(showUndergroundIcon, hovering, pressed);
		var clicked = evt.type == EventType.MouseDown
			&& evt.button == 0
			&& hovering;
		if (clicked)
		{
			evt.Use();
			Homm3HomecomingLayerViewToggle.LogButtonClick(evt.mousePosition);
			if (!Homm3HomecomingLayerViewToggle.TryToggleLayer(out var toggleReason))
				Homm3HomecomingLayerViewToggle.LogToggleFailure(toggleReason);
		}

		if (evt.type == EventType.Repaint && texture != null)
			GUI.DrawTexture(rect, texture, ScaleMode.StretchToFill, true);
	}
}

internal static class Homm3HomecomingLayerViewToggle
{
	internal const string LogPrefix = "HOMM3_HOMECOMING_LAYER_VIEW_TOGGLE";
	internal const int SurfaceIndex = 0;
	internal const int UndergroundIndex = 1;
	private const float NativeButtonPixels = 32f;
	private const float ReferenceHeight = 1080f;
	private const float DisplayMultiplier = 2f;
	private const float ButtonMargin = 16f;
	private const float ButtonTopOffset = 56f;
	private const string AssetRoot = "homm3_adventure_ui/layer_toggle";
	private const string SessionHudSceneName = "sessionHUD";
	private const string AdventureHudCanvasName = "CanvasTechHUDPanel";

	private static Type _worldCameraType;
	private static string _lastFailureReason;
	private static float _nextFailureLogAt;
	private static int _failureLogCount;
	private static bool _loggedAvailable;
	private static bool _loggedMissingTextures;
	private static bool _texturesResolved;
	private static Texture2D _surfaceNormal;
	private static Texture2D _surfacePressed;
	private static Texture2D _surfaceHover;
	private static Texture2D _undergroundNormal;
	private static Texture2D _undergroundPressed;
	private static Texture2D _undergroundHover;
	private static int _adventureHudCacheFrame = -1;
	private static bool _adventureHudCacheVisible;
	private static int _layerStateCacheFrame = -1;
	private static bool _layerStateCacheOk;
	private static LayerState _layerStateCache;
	private static string _layerStateCacheReason;
	private static bool _layerStateCacheTargetMapSeen;

	internal sealed class LayerState
	{
		internal object Camera;
		internal Map Map;
		internal MapData MapData;
		internal string FileMapName;
		internal object ViewState;
		internal MapViewData[] Views;
		internal int CurrentIndex;
		internal string CurrentName;
		internal MethodInfo SetCurrentIndex;
		internal int ViewCount;
		internal MethodInfo MoveCameraBetweenViews;
	}

	internal static float UiScale()
	{
		if (Screen.height <= 0)
			return DisplayMultiplier;
		return Mathf.Clamp(Screen.height / ReferenceHeight, 0.75f, 2f) * DisplayMultiplier;
	}

	internal static Rect ButtonRect()
	{
		var size = NativeButtonPixels * UiScale();
		var margin = ButtonMargin * (UiScale() / DisplayMultiplier);
		return new Rect(
			Mathf.Max(margin, Screen.width - size - margin),
			ButtonTopOffset * (UiScale() / DisplayMultiplier),
			size,
			size);
	}

	internal static bool IsAdventureHudVisible()
	{
		if (_adventureHudCacheFrame == Time.frameCount)
			return _adventureHudCacheVisible;

		_adventureHudCacheFrame = Time.frameCount;
		_adventureHudCacheVisible = false;

		var active = SceneManager.GetActiveScene();
		if (active.IsValid())
		{
			var activeName = active.name ?? string.Empty;
			if (ContainsModeToken(activeName, "menu")
			    || ContainsModeToken(activeName, "battle")
			    || ContainsModeToken(activeName, "city")
			    || ContainsModeToken(activeName, "town"))
				return false;
		}

		var sessionHudLoaded = false;
		var worldPresent = false;
		for (var i = 0; i < SceneManager.sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			var name = scene.name ?? string.Empty;
			if (string.Equals(name, SessionHudSceneName, StringComparison.Ordinal))
				sessionHudLoaded = true;
			if (string.Equals(name, "worldLight", StringComparison.Ordinal)
			    || string.Equals(name, "sessionWorld", StringComparison.Ordinal))
				worldPresent = true;
		}

		if (!sessionHudLoaded || !worldPresent)
			return false;

		_adventureHudCacheVisible = CountActiveNamedInScene(AdventureHudCanvasName, SessionHudSceneName) > 0;
		return _adventureHudCacheVisible;
	}

	internal static bool TryEnsureButtonTextures()
	{
		if (_texturesResolved)
			return _surfaceNormal != null && _undergroundNormal != null;

		_texturesResolved = true;
		_surfaceNormal = LoadButtonTexture("surface/00_00.png", "homm3_layer_toggle_surface_normal");
		_surfacePressed = LoadButtonTexture("surface/00_01.png", "homm3_layer_toggle_surface_pressed");
		_surfaceHover = LoadButtonTexture("surface/00_03.png", "homm3_layer_toggle_surface_hover");
		_undergroundNormal = LoadButtonTexture("underground/00_00.png", "homm3_layer_toggle_underground_normal");
		_undergroundPressed = LoadButtonTexture("underground/00_01.png", "homm3_layer_toggle_underground_pressed");
		_undergroundHover = LoadButtonTexture("underground/00_03.png", "homm3_layer_toggle_underground_hover");
		if (_surfaceNormal == null || _undergroundNormal == null)
		{
			if (!_loggedMissingTextures)
			{
				_loggedMissingTextures = true;
				Log?.LogError(LogPrefix + " missing_iam_button_textures root=" + AssetRoot);
			}
			return false;
		}

		Log?.LogInfo(LogPrefix + " button_textures_loaded surface=IAM003 underground=IAM010");
		return true;
	}

	internal static Texture2D ResolveButtonTexture(bool showUndergroundIcon, bool hovering, bool pressed)
	{
		if (showUndergroundIcon)
		{
			if (pressed && _undergroundPressed != null)
				return _undergroundPressed;
			if (hovering && _undergroundHover != null)
				return _undergroundHover;
			return _undergroundNormal;
		}

		if (pressed && _surfacePressed != null)
			return _surfacePressed;
		if (hovering && _surfaceHover != null)
			return _surfaceHover;
		return _surfaceNormal;
	}

	private static Texture2D LoadButtonTexture(string relativeName, string textureName)
	{
		var relativePath = AssetRoot + "/" + relativeName;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(relativePath);
		if (path == null)
			return null;
		try
		{
			var bytes = File.ReadAllBytes(path);
			var loaded = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			loaded.hideFlags = HideFlags.HideAndDontSave;
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			if (!ImageConversion.LoadImage(loaded, il2cppBytes))
			{
				UnityObject.Destroy(loaded);
				return null;
			}

			loaded.name = textureName;
			loaded.filterMode = FilterMode.Point;
			loaded.wrapMode = TextureWrapMode.Clamp;
			return loaded;
		}
		catch (Exception ex)
		{
			Log?.LogWarning(LogPrefix + " button_texture_load_failed path=" + path + " error=" + FormatException(ex));
			return null;
		}
	}

	private static bool ContainsModeToken(string sceneName, string token)
	{
		return !string.IsNullOrEmpty(sceneName)
			&& sceneName.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static int CountActiveNamedInScene(string objectName, string sceneName)
	{
		// Scene roots only — FindObjectsOfTypeAll<GameObject>() scanned every asset and
		// annihilated adventure-map FPS after the campaign layer-toggle OnGUI path shipped.
		var scene = SceneManager.GetSceneByName(sceneName);
		if (!scene.IsValid() || !scene.isLoaded)
			return 0;
		var roots = scene.GetRootGameObjects();
		var count = 0;
		for (var i = 0; i < roots.Length; i++)
			count += CountActiveNamedUnder(roots[i].transform, objectName);
		return count;
	}

	private static int CountActiveNamedUnder(Transform root, string objectName)
	{
		if (root == null)
			return 0;
		var count = 0;
		var go = root.gameObject;
		if (go != null
		    && go.activeInHierarchy
		    && string.Equals(go.name, objectName, StringComparison.Ordinal))
			count++;
		for (var i = 0; i < root.childCount; i++)
			count += CountActiveNamedUnder(root.GetChild(i), objectName);
		return count;
	}

	internal static bool TryToggleLayer(out string reason)
	{
		reason = null;
		if (!TryReadLayerState(out var state, out reason, out _))
			return false;

		var targetIndex = state.CurrentIndex == SurfaceIndex ? UndergroundIndex : SurfaceIndex;
		try
		{
			InvokeSetCurrentView(state, targetIndex);
			try
			{
				InvokeMoveCameraBetweenViews(state, state.CurrentIndex, targetIndex);
			}
			catch
			{
				InvokeSetCurrentView(state, state.CurrentIndex);
				throw;
			}

			Log?.LogInfo(
				LogPrefix
				+ " toggled map=" + state.FileMapName
				+ " from=" + state.CurrentName + "(" + state.CurrentIndex.ToString(CultureInfo.InvariantCulture) + ")"
				+ " to=" + ViewName(targetIndex) + "(" + targetIndex.ToString(CultureInfo.InvariantCulture) + ")"
				+ " viewTransition=" + state.CurrentIndex.ToString(CultureInfo.InvariantCulture) + "," + targetIndex.ToString(CultureInfo.InvariantCulture));
			return true;
		}
		catch (Exception ex)
		{
			reason = "native_toggle_failed " + FormatException(ex);
			return false;
		}
	}

	internal static bool TryReadLayerState(out LayerState state, out string reason, out bool targetMapSeen)
	{
		state = null;
		reason = null;
		targetMapSeen = false;

		// OnGUI fires Layout+Repaint (and more) each frame; cache the heavy resolve once.
		if (_layerStateCacheFrame == Time.frameCount)
		{
			state = _layerStateCache;
			reason = _layerStateCacheReason;
			targetMapSeen = _layerStateCacheTargetMapSeen;
			return _layerStateCacheOk;
		}

		var ok = TryReadLayerStateUncached(out state, out reason, out targetMapSeen);
		_layerStateCacheFrame = Time.frameCount;
		_layerStateCacheOk = ok;
		_layerStateCache = state;
		_layerStateCacheReason = reason;
		_layerStateCacheTargetMapSeen = targetMapSeen;
		return ok;
	}

	private static bool TryReadLayerStateUncached(out LayerState state, out string reason, out bool targetMapSeen)
	{
		state = null;
		reason = null;
		targetMapSeen = false;

		if (!TryResolveNativeCameraAndMap(out var camera, out var map, out var moveCameraBetweenViews, out reason))
			return false;
		if (!TryResolveMapData(map, out var mapData, out reason))
			return false;
		if (!TryReadMapSid(mapData, out var fileMapName, out reason))
			return false;
		if (!TryValidateLayeredMapContract(mapData, fileMapName, out var views, out targetMapSeen, out reason))
			return false;
		if (!TryResolveViewState(map, out var viewState, out reason))
			return false;
		if (!TryResolveViewStateMethods(viewState, out var getCurrentIndex, out var getViewCount, out var setCurrentIndex, out reason))
			return false;
		if (!TryReadCurrentIndex(viewState, getCurrentIndex, out var currentIndex, out reason))
			return false;
		if (!TryReadViewCount(viewState, getViewCount, out var viewCount, out reason))
			return false;
		if (viewCount != views.Length)
		{
			reason = "view_state_count_mismatch viewStateCount=" + viewCount.ToString(CultureInfo.InvariantCulture) + " mapDataViews=" + views.Length.ToString(CultureInfo.InvariantCulture);
			return false;
		}
		if (currentIndex < 0 || currentIndex >= viewCount)
		{
			reason = "current_view_index_outside_native_view_count index=" + currentIndex.ToString(CultureInfo.InvariantCulture) + " viewCount=" + viewCount.ToString(CultureInfo.InvariantCulture);
			return false;
		}

		if (currentIndex != SurfaceIndex && currentIndex != UndergroundIndex)
		{
			reason = "current_view_index_outside_layer_contract index=" + currentIndex.ToString(CultureInfo.InvariantCulture);
			return false;
		}

		state = new LayerState
		{
			Camera = camera,
			Map = map,
			MapData = mapData,
			FileMapName = fileMapName,
			ViewState = viewState,
			Views = views,
			CurrentIndex = currentIndex,
			CurrentName = ViewName(currentIndex),
			SetCurrentIndex = setCurrentIndex,
			ViewCount = viewCount,
			MoveCameraBetweenViews = moveCameraBetweenViews,
		};
		if (!_loggedAvailable)
		{
			_loggedAvailable = true;
			Log?.LogInfo(
				LogPrefix + " available map=" + fileMapName + " views=surface,underground"
				+ " nativeSymbols=" + GameSymbols.HomecomingLayerViewToggle.CurrentViewIndexGetter.Id
				+ "/" + GameSymbols.HomecomingLayerViewToggle.ViewCountGetter.Id
				+ "/" + GameSymbols.HomecomingLayerViewToggle.CurrentViewIndexSetter.Id
				+ " viewCount=" + state.ViewCount.ToString(CultureInfo.InvariantCulture)
				+ " cameraSymbol=" + GameSymbols.HomecomingLayerViewToggle.WorldCameraMoveBetweenViews.Id
				+ " native_view_switching=live_probe_validated button_click=unvalidated");
		}
		return true;
	}

	internal static void LogTargetMapFailure(string reason)
	{
		LogLimited("target_map_toggle_unavailable reason=" + (reason ?? "unknown"));
	}

	internal static void LogToggleFailure(string reason)
	{
		LogLimited("toggle_failed reason=" + (reason ?? "unknown"));
	}

	internal static void LogButtonClick(Vector2 mousePosition)
	{
		Log?.LogInfo(
			LogPrefix
			+ " button_click x=" + mousePosition.x.ToString("0.###", CultureInfo.InvariantCulture)
			+ " y=" + mousePosition.y.ToString("0.###", CultureInfo.InvariantCulture));
	}

	private static ManualLogSource Log => Homm3HomecomingLayerViewToggleBootstrap.Log;

	private static bool TryResolveNativeCameraAndMap(out object camera, out Map map, out MethodInfo moveCameraBetweenViews, out string reason)
	{
		camera = null;
		map = null;
		moveCameraBetweenViews = null;
		reason = null;

		var cameraType = ResolveWorldCameraType();
		if (cameraType == null)
		{
			reason = "world_camera_type_unresolved";
			return false;
		}

		var singleton = GameMember.FindFirstMethodByNames(cameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraSingleton);
		if (singleton == null || !cameraType.IsAssignableFrom(singleton.ReturnType))
		{
			reason = "world_camera_singleton_unresolved";
			return false;
		}
		var currentMap = GameMember.FindFirstMethodByNames(cameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraCurrentMap);
		if (currentMap == null || !typeof(Map).IsAssignableFrom(currentMap.ReturnType))
		{
			reason = "world_camera_current_map_unresolved";
			return false;
		}
		moveCameraBetweenViews = GameMember.FindFirstMethodByNames(cameraType, new[] { typeof(int), typeof(int) }, GameSymbols.HomecomingLayerViewToggle.WorldCameraMoveBetweenViews);
		if (moveCameraBetweenViews == null || moveCameraBetweenViews.ReturnType != typeof(void))
		{
			reason = "world_camera_move_between_views_unresolved";
			return false;
		}

		try
		{
			camera = singleton.Invoke(null, Array.Empty<object>());
			if (camera == null)
			{
				reason = "world_camera_singleton_null";
				return false;
			}

			map = currentMap.Invoke(camera, Array.Empty<object>()) as Map;
			if (map == null)
			{
				reason = "world_camera_current_map_null";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "world_camera_read_failed " + FormatException(ex);
			return false;
		}
	}

	private static Type ResolveWorldCameraType()
	{
		if (_worldCameraType != null)
			return _worldCameraType;
		foreach (var hint in GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeHints)
		{
			_worldCameraType = GameMember.FindType(GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeId + "." + hint, hint);
			if (_worldCameraType != null)
				return _worldCameraType;
		}
		return null;
	}

	private static bool TryResolveMapData(Map map, out MapData mapData, out string reason)
	{
		mapData = null;
		reason = null;
		var method = GameMember.FindFirstMethodByNames(map.GetType(), Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.MapData);
		if (method == null || !typeof(MapData).IsAssignableFrom(method.ReturnType))
		{
			reason = "map_data_getter_unresolved";
			return false;
		}
		try
		{
			mapData = method.Invoke(map, Array.Empty<object>()) as MapData;
			if (mapData == null)
			{
				reason = "map_data_null";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "map_data_read_failed " + FormatException(ex);
			return false;
		}
	}

	private static bool TryResolveViewState(Map map, out object viewState, out string reason)
	{
		viewState = null;
		reason = null;
		var method = GameMember.FindFirstMethodByNames(map.GetType(), Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.MapViewState);
		if (method == null)
		{
			reason = "map_view_state_getter_unresolved";
			return false;
		}
		try
		{
			viewState = method.Invoke(map, Array.Empty<object>());
			if (viewState == null)
			{
				reason = "map_view_state_null";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "map_view_state_read_failed " + FormatException(ex);
			return false;
		}
	}

	private static bool TryResolveViewStateMethods(object viewState, out MethodInfo getCurrentIndex, out MethodInfo getViewCount, out MethodInfo setCurrentIndex, out string reason)
	{
		getCurrentIndex = null;
		getViewCount = null;
		setCurrentIndex = null;
		reason = null;
		var viewType = viewState.GetType();
		getCurrentIndex = GameMember.FindFirstMethodByNames(viewType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.CurrentViewIndexGetter);
		if (getCurrentIndex == null || getCurrentIndex.ReturnType != typeof(int))
		{
			reason = "current_view_index_getter_unresolved";
			return false;
		}

		getViewCount = GameMember.FindFirstMethodByNames(viewType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.ViewCountGetter);
		if (getViewCount == null || getViewCount.ReturnType != typeof(int))
		{
			reason = "view_count_getter_unresolved";
			return false;
		}

		setCurrentIndex = GameMember.FindFirstMethodByNames(viewType, new[] { typeof(int) }, GameSymbols.HomecomingLayerViewToggle.CurrentViewIndexSetter);
		if (setCurrentIndex == null || setCurrentIndex.ReturnType != typeof(void))
		{
			reason = "current_view_index_setter_unresolved";
			return false;
		}
		return true;
	}

	private static bool TryReadCurrentIndex(object viewState, MethodInfo getCurrentIndex, out int currentIndex, out string reason)
	{
		currentIndex = -1;
		reason = null;
		try
		{
			currentIndex = Convert.ToInt32(getCurrentIndex.Invoke(viewState, Array.Empty<object>()), CultureInfo.InvariantCulture);
			return true;
		}
		catch (Exception ex)
		{
			reason = "current_view_index_read_failed " + FormatException(ex);
			return false;
		}
	}

	private static bool TryReadViewCount(object viewState, MethodInfo getViewCount, out int viewCount, out string reason)
	{
		viewCount = -1;
		reason = null;
		try
		{
			viewCount = Convert.ToInt32(getViewCount.Invoke(viewState, Array.Empty<object>()), CultureInfo.InvariantCulture);
			return true;
		}
		catch (Exception ex)
		{
			reason = "view_count_read_failed " + FormatException(ex);
			return false;
		}
	}

	private static bool TryReadMapSid(MapData mapData, out string fileMapName, out string reason)
	{
		fileMapName = null;
		reason = null;
		for (var i = 0; i < GameSymbols.HomecomingLayerViewToggle.MapDataFileNameMembers.Length; i++)
		{
			var value = ReadMember(mapData, GameSymbols.HomecomingLayerViewToggle.MapDataFileNameMembers[i]) as string;
			if (!string.IsNullOrWhiteSpace(value))
			{
				fileMapName = value;
				return true;
			}
		}
		reason = "map_file_name_unresolved";
		return false;
	}

	private static bool TryValidateLayeredMapContract(MapData mapData, string fileMapName, out MapViewData[] views, out bool targetMapSeen, out string reason)
	{
		views = null;
		targetMapSeen = false;
		reason = null;
		var viewsValue = ReadFirstMember(mapData, GameSymbols.HomecomingLayerViewToggle.MapDataViewsMembers);
		if (!TryCopyViews(viewsValue, out views, out reason))
			return false;
		if (views.Length != 2)
		{
			reason = "not_two_view_layered_atlas map=" + (fileMapName ?? "null") + " count=" + views.Length.ToString(CultureInfo.InvariantCulture);
			return false;
		}

		targetMapSeen = true;
		var surface = views[SurfaceIndex];
		var underground = views[UndergroundIndex];
		if (!ViewHasRole(surface, "surface", false, -1))
		{
			reason = "surface_view_contract_mismatch map=" + (fileMapName ?? "null") + " actual=" + DescribeView(surface);
			return false;
		}
		if (!ViewHasRole(underground, "underground", true, -1))
		{
			reason = "underground_view_contract_mismatch map=" + (fileMapName ?? "null") + " actual=" + DescribeView(underground);
			return false;
		}
		if (surface.secSizeX <= 0 || surface.secSizeZ <= 0)
		{
			reason = "surface_view_invalid_size actual=" + DescribeView(surface);
			return false;
		}
		if (surface.minSecX != 0 || surface.minSecZ != 0)
		{
			reason = "surface_view_origin_mismatch actual=" + DescribeView(surface);
			return false;
		}
		if (underground.minSecX != surface.minSecX + surface.secSizeX || underground.minSecZ != surface.minSecZ)
		{
			reason = "underground_view_not_horizontal_atlas surface=" + DescribeView(surface) + " underground=" + DescribeView(underground);
			return false;
		}
		if (underground.secSizeX != surface.secSizeX || underground.secSizeZ != surface.secSizeZ)
		{
			reason = "layer_view_size_mismatch surface=" + DescribeView(surface) + " underground=" + DescribeView(underground);
			return false;
		}
		return true;
	}

	private static bool TryCopyViews(object viewsValue, out MapViewData[] views, out string reason)
	{
		views = null;
		reason = null;
		if (viewsValue == null)
		{
			reason = "map_views_null";
			return false;
		}
		if (viewsValue is MapViewData[] managedViews)
		{
			views = managedViews;
			return true;
		}
		if (viewsValue is Il2CppReferenceArray<MapViewData> il2CppViews)
		{
			views = new MapViewData[il2CppViews.Length];
			for (var i = 0; i < il2CppViews.Length; i++)
				views[i] = il2CppViews[i];
			return true;
		}
		if (viewsValue is IEnumerable enumerable && viewsValue is not string)
		{
			var list = new List<MapViewData>();
			foreach (var item in enumerable)
			{
				if (item is not MapViewData view)
				{
					reason = "map_views_entry_type_mismatch type=" + (item == null ? "null" : item.GetType().FullName);
					return false;
				}
				list.Add(view);
			}
			views = list.ToArray();
			return true;
		}
		reason = "map_views_type_mismatch type=" + viewsValue.GetType().FullName;
		return false;
	}

	private static bool ViewHasRole(MapViewData actual, string name, bool isUnderground, int stack)
	{
		return actual != null
			&& string.Equals(actual.name, name, StringComparison.Ordinal)
			&& actual.isUnderground == isUnderground
			&& actual.stack == stack;
	}

	private static string DescribeView(MapViewData view)
	{
		if (view == null)
			return "null";
		return (view.name ?? "null")
			+ ":minSec=" + view.minSecX.ToString(CultureInfo.InvariantCulture) + "," + view.minSecZ.ToString(CultureInfo.InvariantCulture)
			+ ":secSize=" + view.secSizeX.ToString(CultureInfo.InvariantCulture) + "," + view.secSizeZ.ToString(CultureInfo.InvariantCulture)
			+ ":underground=" + view.isUnderground.ToString()
			+ ":stack=" + view.stack.ToString(CultureInfo.InvariantCulture);
	}

	private static void InvokeSetCurrentView(LayerState state, int viewIndex)
	{
		state.SetCurrentIndex.Invoke(state.ViewState, new object[] { viewIndex });
	}

	private static void InvokeMoveCameraBetweenViews(LayerState state, int sourceViewIndex, int targetViewIndex)
	{
		state.MoveCameraBetweenViews.Invoke(state.Camera, new object[] { sourceViewIndex, targetViewIndex });
	}

	private static string ViewName(int index)
	{
		return index == UndergroundIndex ? "Underground" : "Surface";
	}

	private static object ReadFirstMember(object instance, string[] names)
	{
		for (var i = 0; i < names.Length; i++)
		{
			var value = ReadMember(instance, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object ReadMember(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var type = instance.GetType(); type != null && type != typeof(object); type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(instance);
			}
			catch
			{
			}

			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(instance, null);
			}
			catch
			{
			}
		}
		return null;
	}

	private static void LogLimited(string message)
	{
		var now = Time.realtimeSinceStartup;
		if (string.Equals(message, _lastFailureReason, StringComparison.Ordinal) && now < _nextFailureLogAt)
			return;
		_lastFailureReason = message;
		_nextFailureLogAt = now + 10f;
		if (_failureLogCount >= 12)
			return;
		_failureLogCount++;
		Log?.LogWarning(LogPrefix + " " + message);
	}

	private static string FormatException(Exception ex)
	{
		if (ex is TargetInvocationException target && target.InnerException != null)
			ex = target.InnerException;
		return ex == null ? "unknown" : ex.GetType().Name + ": " + ex.Message;
	}
}