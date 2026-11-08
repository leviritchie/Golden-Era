using System;
using System.Reflection;
using BepInEx.Logging;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Loads vanilla donor battle prefabs by units/... path for tooltip diagnostics when HoMM3 bundles
/// do not yield a readable portrait texture. Donor identity comes from <see cref="Homm3CustomFactionRegistry"/>
/// so mixed-donor factions such as Fortress do not inherit Stronghold-only Dungeon assumptions.
/// </summary>
internal static class VanillaDungeonTooltipPortraitResLoader
{
	private static MethodInfo _closedGetGameObject;
	private static bool _closedIsStatic;
	private static Type _cachedRmType;
	private static object _resManagerInstance;
	private static int _loggedInvokeFail;
	private static int _loggedNoInstance;

	internal static bool TryGetVanillaDungeonBattlePrefab(string sid, ManualLogSource log, out GameObject prefab)
	{
		return TryGetVanillaDonorBattlePrefab(sid, log, out prefab);
	}

	internal static bool TryGetVanillaDonorBattlePrefab(string sid, ManualLogSource log, out GameObject prefab)
	{
		prefab = null;
		if (string.IsNullOrEmpty(sid) || !Homm3CustomFactionRegistry.TryGetDonorBattlePrefabPath(sid, out var path))
			return false;
		return TryResManagerGetGameObject(path, log, out prefab) && prefab;
	}

	private static bool TryResManagerGetGameObject(string unitsPath, ManualLogSource log, out GameObject go)
	{
		go = null;
		if (!TryEnsureResManagerInvoker(log))
			return false;
		try
		{
			object result;
			if (_closedIsStatic)
				result = _closedGetGameObject.Invoke(null, new object[] { unitsPath });
			else
			{
				if (_resManagerInstance == null)
					return false;
				result = _closedGetGameObject.Invoke(_resManagerInstance, new object[] { unitsPath });
			}

			go = result as GameObject;
			return go;
		}
		catch (Exception ex)
		{
			if (_loggedInvokeFail < 12)
			{
				_loggedInvokeFail++;
				log?.LogWarning("Vanilla donor tooltip portrait: ResManager.Get<GameObject> failed for '" + unitsPath + "': " + ex.Message);
			}

			return false;
		}
	}

	private static bool TryEnsureResManagerInvoker(ManualLogSource log)
	{
		if (_closedGetGameObject == null)
		{
			try
			{
				var asm = typeof(ObjCityConfig).Assembly;
				var rmType = ResManagerInteropProbe.TryResolveResManagerType(asm, msg => log?.LogWarning("Vanilla donor portrait: " + msg));
				if (rmType == null)
					return false;
				var openGeneric = ResManagerInteropProbe.FindResManagerGetOpenGeneric(rmType);
				if (openGeneric == null)
					return false;
				_cachedRmType = rmType;
				_closedGetGameObject = openGeneric.MakeGenericMethod(typeof(GameObject));
				_closedIsStatic = _closedGetGameObject.IsStatic;
			}
			catch (Exception ex)
			{
				log?.LogWarning("Vanilla donor tooltip portrait: init failed: " + ex.Message);
				return false;
			}
		}

		if (_closedIsStatic)
			return true;
		_resManagerInstance = TryFindResManagerInstance(_cachedRmType);
		if (_resManagerInstance == null && _loggedNoInstance < 4)
		{
			_loggedNoInstance++;
			log?.LogWarning(
				"Vanilla donor tooltip portrait: ResManager.Get<GameObject> is instance method but no "
				+ (_cachedRmType?.FullName ?? "?")
				+ " instance yet (open a screen that loads units, or wait for the first ResManager request).");
		}

		return _resManagerInstance != null;
	}

	private static object _instanceFromResManagerHook;

	/// <summary>Called from <see cref="ResManagerGameObjectLaneHooks"/> so we can invoke instance <c>Get&lt;GameObject&gt;</c> without <c>Il2CppSystem.Type</c> scans.</summary>
	internal static void TryNoteResManagerInstance(object __instance)
	{
		if (__instance == null)
			return;
		_instanceFromResManagerHook = __instance;
	}

	private static object TryFindResManagerInstance(Type rmType)
	{
		if (rmType == null)
			return null;
		if (_instanceFromResManagerHook != null)
		{
			var it = _instanceFromResManagerHook.GetType();
			if (rmType.IsInstanceOfType(_instanceFromResManagerHook) || rmType.IsAssignableFrom(it))
				return _instanceFromResManagerHook;
		}
		const BindingFlags bf = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var p in rmType.GetProperties(bf))
		{
			if (!p.CanRead)
				continue;
			var get = p.GetGetMethod(true);
			if (get == null || !get.IsStatic)
				continue;
			if (!rmType.IsAssignableFrom(p.PropertyType))
				continue;
			try
			{
				var v = p.GetValue(null);
				if (v != null)
					return v;
			}
			catch
			{
				// ignored
			}
		}

		foreach (var f in rmType.GetFields(bf))
		{
			if (!f.IsStatic || !rmType.IsAssignableFrom(f.FieldType))
				continue;
			try
			{
				var v = f.GetValue(null);
				if (v != null)
					return v;
			}
			catch
			{
				// ignored
			}
		}

		return null;
	}
}
