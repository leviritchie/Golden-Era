using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Optional narrow hook: <c>Hex.UI.UiModelsSpawner</c> <c>Spawn</c> with <c>GameObject</c> return, does not touch <c>ResManager</c> at patch time
/// (see <c>esquirePikemanNarrowUiSpawnerHook</c> in mod config). UI previews only; map/battle still use <c>ResManager</c> or pool code.
/// </summary>
internal static class EsquirePikemanNarrowSpawnerHook
{
	private static bool _isStringParam(ParameterInfo p) =>
		p?.ParameterType == typeof(string) || p?.ParameterType.Name == "String";

	internal static void TryRegister(Harmony h, ManualLogSource log, bool resManagerPatched)
	{
		if (h == null || log == null)
			return;
		if (resManagerPatched)
		{
			log.LogInfo(
				"EsquirePikeman narrow UI spawner hook skipped (esquirePikemanApplyHarmony=true; use ResManager prefix for template swap).");
			return;
		}

		try
		{
			var t = typeof(ObjCityConfig).Assembly.GetType("Hex.UI.UiModelsSpawner", false);
			if (t == null)
			{
				log.LogWarning("EsquirePikeman narrow UI: type Hex.UI.UiModelsSpawner not found; hook not applied.");
				return;
			}

			const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
				| BindingFlags.DeclaredOnly;
			MethodInfo? target = null;
			foreach (var m in t.GetMethods(f))
			{
				if (m.Name != "Spawn" || m.ReturnType != typeof(GameObject))
					continue;
				var p = m.GetParameters();
				if (p.Length < 1 || !_isStringParam(p[0]))
					continue;
				target = m;
				break;
			}

			if (target == null)
			{
				log.LogWarning(
					"EsquirePikeman narrow UI: no instance Spawn(string, …): GameObject on UiModelsSpawner; hook not applied (enable esquirePikemanSpawnerReflectionProbe to inspect).");
				return;
			}

			h.Patch(
				target,
				postfix: new HarmonyMethod(
					typeof(EsquirePikemanNarrowSpawnerHook),
					nameof(SpawnReturnGameObjectPostfix)));
			log.LogInfo("EsquirePikeman: narrow Harmony postfix on " + t.FullName + "." + target);
		}
		catch (Exception ex)
		{
			log.LogError("EsquirePikeman narrow UI spawner hook failed: " + ex);
		}
	}

	private static void SpawnReturnGameObjectPostfix(
		[HarmonyArgument(0)] string _path,
		ref GameObject __result)
	{
		if (string.IsNullOrEmpty(_path) || !__result)
			return;
		var units = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(_path);
		if (units != EsquirePikemanVisuals.BattleResPath && units != EsquirePikemanVisuals.MapResPath)
			return;
		if (!EsquirePikemanVisuals.TryGetEsquireTemplateForUnitsPath(units, Plugin.LogSource, out var src) || !src)
			return;
		try
		{
			UnityEngine.Object.Destroy(__result);
			__result = UnityEngine.Object.Instantiate(src);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquirePikeman narrow spawner Postfix: " + ex);
		}
	}
}
