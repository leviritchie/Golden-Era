using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>Narrow <c>UiModelsSpawner.Spawn</c> postfix for lane B (see <see cref="Homm3ImportVisuals"/>).</summary>
internal static class Homm3ImportNarrowSpawnerHook
{
	private static bool _isStringParam(ParameterInfo p) =>
		p?.ParameterType == typeof(string) || p?.ParameterType.Name == "String";

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (h == null || log == null)
			return;
		try
		{
			var t = typeof(ObjCityConfig).Assembly.GetType("Hex.UI.UiModelsSpawner", false);
			if (t == null)
			{
				log.LogWarning("Homm3Import narrow UI: Hex.UI.UiModelsSpawner not found.");
				return;
			}

			const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
				| BindingFlags.DeclaredOnly;
			MethodInfo target = null;
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
				log.LogWarning("Homm3Import narrow UI: no matching Spawn method.");
				return;
			}

			h.Patch(
				target,
				postfix: new HarmonyMethod(
					typeof(Homm3ImportNarrowSpawnerHook),
					nameof(SpawnReturnGameObjectPostfix)));
			log.LogInfo("Homm3Import: narrow Harmony postfix on " + t.FullName + "." + target.Name);
		}
		catch (Exception ex)
		{
			log.LogError("Homm3Import narrow spawner hook failed: " + ex);
		}
	}

	private static void SpawnReturnGameObjectPostfix([HarmonyArgument(0)] string _path, ref GameObject __result)
	{
		if (string.IsNullOrEmpty(_path))
			return;
		var units = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(_path);
		if (!__result && !Homm3ImportVisuals.IsSyntheticHomm3ImportUnitsPath(units))
			return;
		if (Homm3ImportVisuals.TryResolveHomm3MapEntry(units, out var gatedEntry)
		    && gatedEntry != null
		    && gatedEntry.SwapAdventureMap
		    && Homm3ImportVisuals.EntryHasGameUnitSidGate(gatedEntry))
			return;
		if (!Homm3ImportVisuals.TryGetTemplateForUnitsPath(units, Plugin.LogSource, out var src) || !src)
			return;
		try
		{
			var original = __result;
			var vanillaRef = original;
			var inst = UnityEngine.Object.Instantiate(src);
			if (Homm3ImportVisuals.TryResolveHomm3MapEntry(units, out var entry) && entry != null && entry.SwapAdventureMap)
			{
				if (!vanillaRef && Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry))
					Homm3ImportVisuals.TryGetMapShellTemplate(entry, Plugin.LogSource, out vanillaRef);
				inst = Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure(vanillaRef, inst, entry, Plugin.LogSource);
			}
			else if (Homm3ImportVisuals.IsAdventureMapUnitsPath(units))
				Homm3ImportVisuals.FinishHomm3MapPrefabForAdventure(vanillaRef, inst, Plugin.LogSource);
			if (original)
				UnityEngine.Object.Destroy(original);
			__result = inst;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import narrow spawner Postfix: " + ex);
		}
	}
}
