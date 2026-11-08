using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Current releases resolve the method through <see cref="GameSymbols.UnitViewConfig.MapMeshLoader"/>; do not use a shape-only fallback.
/// Patches <c>UnitViewConfig.rtd()</c> — adventure-map visuals; swap key comes from the <c>mapMesh</c> field (not <c>mesh</c> / battle).
/// <para>
/// Uses a <b>postfix</b> after vanilla <c>rtd()</c> so the Il2CPP return slot reliably receives our bundle template
/// (prefix+skip with <c>ref __result</c> can leave stock art visible). Resolves <c>rtd</c> on the type or a base type
/// (declared-only lookup misses inherited methods).
/// Only <see cref="EsquirePikemanVisuals.MapResPath"/> is swapped. Other rows (e.g. <c>esquire_upg_map</c>) stay separate.
/// Stock <c>esquire_map</c> from vanilla <c>rtd()</c> is used as reference to copy layers and renderer sorting onto the
/// bundle map prefab (same pattern as battle <see cref="EsquirePikemanBattlePoolHook"/> presentation sync).
/// </para>
/// </summary>
internal static class EsquirePikemanUnitViewHook
{
	private static bool _patched;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched)
			return;
		try
		{
			var t = typeof(ObjCityConfig).Assembly.GetType("Hex.Configs.UnitViewConfig", throwOnError: false);
			if (t == null)
			{
				log?.LogWarning("EsquirePikeman: Hex.Configs.UnitViewConfig not found; visual hook not applied.");
				return;
			}

			var rtd = FindMapMeshLoader(t);

			if (rtd == null)
			{
				log?.LogWarning("EsquirePikeman: UnitViewConfig map GameObject loader not found; visual hook not applied.");
				return;
			}

			h.Patch(rtd, postfix: new HarmonyMethod(typeof(EsquirePikemanUnitViewHook), nameof(PostfixRtd)));
			_patched = true;
			log?.LogInfo(
				"EsquirePikeman: Harmony postfix on "
				+ rtd.DeclaringType?.FullName
				+ "."
				+ rtd.Name
				+ "():GameObject (esquire_map swap after vanilla).");
		}
		catch (Exception ex)
		{
			log?.LogError("EsquirePikeman: UnitViewConfig map-loader hook failed: " + ex);
		}
	}

	private static MethodInfo FindMapMeshLoader(Type unitViewConfigType)
	{
		for (var cur = unitViewConfigType; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			foreach (var m in cur.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
			         | BindingFlags.DeclaredOnly))
			{
				if (m.ReturnType != typeof(GameObject) || m.GetParameters().Length != 0)
					continue;
				if (m.IsSpecialName)
					continue;
				foreach (var hint in GameSymbols.UnitViewConfig.MapMeshLoader.NameHints)
				{
					if (string.Equals(m.Name, hint, StringComparison.Ordinal))
						return m;
				}
			}
		}

		return null;
	}

	internal static void Cancel()
	{
		_patched = false;
	}

	private static void PostfixRtd(UnitViewConfig __instance, ref GameObject __result)
	{
		if (__instance == null)
			return;

		try
		{
			// Il2Cpp: `mapMesh` is a public field on the generated proxy — do not use GetProperty (returns null).
			var mapMeshRaw = __instance.mapMesh;
			if (string.IsNullOrEmpty(mapMeshRaw))
				return;
			var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(mapMeshRaw);
			if (!string.Equals(unitsPath, EsquirePikemanVisuals.MapResPath, StringComparison.Ordinal))
			{
				if (EsquirePikemanVisuals.VerboseEsquireHooks
				    && mapMeshRaw.IndexOf("esquire", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					var meshBattle = __instance.mesh;
					Plugin.LogSource?.LogInfo(
						"EsquirePikeman UnitViewHook: PostfixRtd no swap mapMesh='"
						+ mapMeshRaw
						+ "' mesh(battle)='"
						+ (meshBattle ?? "(null)")
						+ "' normalized(mapMesh)='"
						+ unitsPath
						+ "' expected='"
						+ EsquirePikemanVisuals.MapResPath
						+ "' swapAdventureMap="
						+ EsquirePikemanVisuals.SwapAdventureMapEnabledForDiag);
				}

				return;
			}

			if (!EsquirePikemanVisuals.TryFinalizeMapVisualSwap(ref __result, Plugin.LogSource))
				return;
			Plugin.LogSource?.LogInfo(
				"EsquirePikeman UnitViewHook: PostfixRtd swapped "
				+ unitsPath
				+ " template='"
				+ (__result ? __result.name : "?")
				+ "' (after vanilla rtd).");
			if (EsquirePikemanVisuals.VerboseEsquireHooks && __result)
			{
				var sr = __result.GetComponentInChildren<SpriteRenderer>(true);
				var spr = sr ? sr.sprite : null;
				Plugin.LogSource?.LogInfo(
					"EsquirePikeman UnitViewHook: map template rootScale="
					+ __result.transform.localScale
					+ " spriteRenderer="
					+ (sr ? "yes" : "no")
					+ " sprite="
					+ (spr ? spr.name : "(null)"));
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquirePikeman UnitViewHook.PostfixRtd: " + ex);
		}
	}
}
