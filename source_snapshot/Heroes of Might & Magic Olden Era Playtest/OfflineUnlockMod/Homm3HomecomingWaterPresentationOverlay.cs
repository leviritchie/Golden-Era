using System;
using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using Hex.Map;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Homecoming map-context helpers shared by water presentation bridges.
/// Passable-water cursor overlay was retired; path-preview depth xray remains.
/// </summary>
internal static class Homm3HomecomingWaterPresentationOverlay
{
	internal const string ActiveArchitecture = "homecoming_map_context_helpers_only";
	private const BindingFlags MemberFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

	internal static bool TryReadHomecomingMapContext(out object mapData, out string fileMapName, out HomecomingMapProfile profile)
	{
		mapData = null;
		fileMapName = null;
		profile = null;
		if (!TryReadCurrentMapContext(out mapData, out fileMapName, out _))
			return false;
		if (!HomecomingMapProfile.TryResolve(fileMapName, mapData, out profile))
			return false;
		return true;
	}

	/// <summary>
	/// Ungated live map context reader shared by Homecoming and campaign-wide water presentation.
	/// Prefer the WORLD owner path used by water traversal; camera is a fallback only.
	/// </summary>
	internal static bool TryReadCurrentMapContext(out object mapData, out string fileMapName, out string reason)
	{
		mapData = null;
		fileMapName = null;
		reason = null;
		string worldReason = null;
		if (TryReadCurrentMapContextFromWorld(out mapData, out fileMapName, out worldReason))
			return true;
		string cameraReason = null;
		if (TryReadCurrentMapContextFromWorldCamera(out mapData, out fileMapName, out cameraReason))
			return true;
		reason = worldReason ?? cameraReason ?? "map_context_unresolved";
		return false;
	}

	private static bool TryReadCurrentMapContextFromWorld(out object mapData, out string fileMapName, out string reason)
	{
		mapData = null;
		fileMapName = null;
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
				if (!TryGetMapFromWorldRoot(root, out var mapInstance, out reason))
					continue;
				if (!TryGetMapData(mapInstance, out mapData))
				{
					reason = "map_data_unresolved";
					continue;
				}
				fileMapName = ReadMapDataString(mapData, 0) ?? ReadMapDataString(mapInstance, 0);
				if (string.IsNullOrWhiteSpace(fileMapName))
				{
					reason = "fileMapName_unresolved";
					continue;
				}
				return true;
			}
		}
		if (reason == null)
			reason = "world_root_not_found";
		return false;
	}

	private static bool TryReadCurrentMapContextFromWorldCamera(out object mapData, out string fileMapName, out string reason)
	{
		mapData = null;
		fileMapName = null;
		reason = null;
		var cameraType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingLayerViewToggleWorldCamera);
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
			catch (Exception ex)
			{
				reason = "world_camera_singleton_invoke_failed " + ex.Message;
			}
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
			var map = currentMap.Invoke(camera, Array.Empty<object>()) as Map;
			if (map == null)
			{
				reason = "world_camera_current_map_null";
				return false;
			}
			if (!TryGetMapData(map, out mapData))
			{
				reason = "world_camera_map_data_unresolved";
				return false;
			}
			fileMapName = ReadMapDataString(mapData, 0) ?? ReadMapDataString(map, 0);
			if (string.IsNullOrWhiteSpace(fileMapName))
			{
				reason = "world_camera_fileMapName_unresolved";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			reason = "world_camera_read_failed " + ex.Message;
			return false;
		}
	}

	private static bool TryGetMapFromWorldRoot(GameObject worldRoot, out object mapInstance, out string reason)
	{
		mapInstance = null;
		reason = null;
		var worldType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldOwner);
		if (worldType == null)
		{
			reason = "world_owner_type_unresolved";
			return false;
		}
		Component worldComponent;
		try { worldComponent = worldRoot.GetComponent(Il2CppType.From(worldType))?.TryCast<Component>(); }
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
		var worldOwner = TryWrapIl2CppObjectAs(worldComponent, worldType) ?? worldComponent;
		mapInstance = InvokeFirstNoArg(worldOwner, typeof(Map), GameSymbols.HomecomingBoatTravel.WorldMap);
		if (mapInstance == null)
		{
			reason = "world_map_getter_unresolved";
			return false;
		}
		return true;
	}

	private static bool TryGetMapData(object value, out object mapData)
	{
		mapData = null;
		if (value == null)
			return false;
		if (value is MapData typed)
		{
			mapData = typed;
			return true;
		}
		var direct = InvokeFirstNoArg(value, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData);
		if (direct == null)
			return false;
		mapData = direct;
		return true;
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

	private static object InvokeFirstNoArg(object obj, Type expectedReturnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null || expectedReturnType == null || symbol.NameHints == null)
			return null;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo method;
				try { method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null || !expectedReturnType.IsAssignableFrom(method.ReturnType))
					continue;
				try { return method.Invoke(obj, null); }
				catch { return null; }
			}
		}
		return null;
	}

	private static object TryReadMember(object value, string name)
	{
		if (value == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = value.GetType();
		PropertyInfo property;
		try { property = type.GetProperty(name, MemberFlags); }
		catch { property = null; }
		if (property != null)
		{
			try { return property.GetValue(value); }
			catch { }
		}
		FieldInfo field;
		try { field = type.GetField(name, MemberFlags); }
		catch { field = null; }
		if (field != null)
		{
			try { return field.GetValue(value); }
			catch { }
		}
		return null;
	}

	private static Type GetTypeByName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		var type = AccessTools.TypeByName(name) ?? AccessTools.TypeByName("Hex." + name) ?? GetHexType(name);
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

	private static Type GetHexType(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		var assembly = typeof(MapData).Assembly;
		return assembly.GetType(name, false)
		       ?? assembly.GetType("Hex.Session.World." + name, false)
		       ?? assembly.GetType("Hex.Map." + name, false)
		       ?? assembly.GetType("Hex." + name, false);
	}

	private static object TryWrapIl2CppObjectAs(object value, Type expectedType)
	{
		if (value == null || expectedType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
			return null;
		if (expectedType.IsInstanceOfType(value))
			return value;
		if (value is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			TryInitializeIl2CppType(expectedType);
			var method = typeof(Il2CppObjectPool).GetMethod("Get", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(IntPtr) }, null);
			if (method == null || !method.IsGenericMethodDefinition)
				return null;
			return method.MakeGenericMethod(expectedType).Invoke(null, new object[] { il2Cpp.Pointer });
		}
		catch { return null; }
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			var classPointerStore = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(classPointerStore.TypeHandle);
		}
		catch { }
	}
}
