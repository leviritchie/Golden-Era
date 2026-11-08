using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: <c>ResManager.Get&lt;GameObject&gt;</c> body for HoMM3 battle/map — invoked from
/// <see cref="ResManagerGameObjectLaneHooks"/> (single Harmony postfix; do not patch ResManager twice).
/// </summary>
internal static class Homm3ImportResManagerHook
{
	private static int _loggedReplace;

	internal static void ResetHarmonyGuardForHotReload()
	{
		_loggedReplace = 0;
		ResManagerGameObjectLaneHooks.ResetRegistrationStateForUnload();
	}

	internal static void PostfixResGetGameObject([HarmonyArgument(0)] string resPath, ref GameObject __result)
	{
		if (string.IsNullOrEmpty(resPath))
			return;

		var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(resPath);
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var battleEntry))
		{
			if (Homm3ImportVisuals.TryGetBattleTemplate(battleEntry, Plugin.LogSource, out var battleTemplate) && battleTemplate)
			{
				if (__result)
				{
					EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(__result, battleTemplate);
					EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(__result, battleTemplate);
				}

				__result = battleTemplate;
				LogReplace("battle", resPath, unitsPath, battleTemplate);
			}

			return;
		}

		if (Homm3ImportVisuals.TryResolveHomm3MapEntry(unitsPath, out var mapEntry)
		    && mapEntry != null
		    && mapEntry.SwapAdventureMap
		    && Homm3ImportVisuals.TryGetMapTemplate(mapEntry, Plugin.LogSource, out var mapTemplate)
		    && mapTemplate)
		{
			var vanilla = __result;
			if (!vanilla && Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(mapEntry))
				Homm3ImportVisuals.TryGetMapShellTemplate(mapEntry, Plugin.LogSource, out vanilla);
			__result = Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure(vanilla, mapTemplate, mapEntry, Plugin.LogSource);
			LogReplace("map", resPath, unitsPath, __result);
		}
	}

	private static void LogReplace(string kind, string resPath, string unitsPath, GameObject template)
	{
		if (_loggedReplace >= 40)
			return;
		_loggedReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import ResManager: replaced "
			+ kind
			+ " '"
			+ resPath
			+ "' (unitsPath="
			+ unitsPath
			+ ") with template '"
			+ (template ? template.name : "?")
			+ "'.");
	}
}
