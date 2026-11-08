using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Single Harmony postfix on <c>Hex.ResManager.Get&lt;GameObject&gt;(string)</c> for lane-B + Esquire map/SFX.
/// Registering two separate postfixes on the same Il2CPP-instrumented method (Homm3 + Esquire) has caused startup NREs;
/// this chains both bodies behind one patch.
/// </summary>
internal static class ResManagerGameObjectLaneHooks
{
	private static bool _registered;
	private static int _traceLines;
	private const int MaxTraceLines = 40;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: true);
	}

	private static void Register(Harmony h, ManualLogSource log, bool required)
	{
		if (_registered)
			return;
		if (h == null)
		{
			if (required)
				throw new System.InvalidOperationException("Harmony was not initialized before required ResManager GameObject lane registration.");
			return;
		}

		try
		{
			var asm = typeof(ObjCityConfig).Assembly;
			var probeLog = BuildProbeLog(log, required);
			var rmType = ResManagerInteropProbe.TryResolveResManagerType(asm, probeLog);
			if (rmType == null)
			{
				HandleMissing(required, "Hex.ResManager type not found.");
				return;
			}

			var openGeneric = ResManagerInteropProbe.FindResManagerGameObjectLoaderMethod(rmType, probeLog);
			if (openGeneric == null)
			{
				HandleMissing(required, "ResManager GameObject/Object loader not found.");
				return;
			}

			var closed = openGeneric;

			var postfixName = closed.ReturnType == typeof(GameObject)
				? nameof(PostfixResManagerGetGameObject)
				: nameof(PostfixResManagerGetUnityObject);
			h.Patch(
				closed,
				postfix: new HarmonyMethod(typeof(ResManagerGameObjectLaneHooks), postfixName));
			_registered = true;
			log?.LogInfo(
				"ResManager lane hooks: Harmony postfix on "
				+ (closed.DeclaringType?.FullName ?? "?")
				+ "."
				+ closed.Name
				+ "<GameObject>(string) return="
				+ (closed.ReturnType?.Name ?? "?")
				+ " ("
				+ (required ? "required " : "")
				+ "Homm3 lane-B + Esquire map/SFX).");
		}
		catch (System.Exception ex)
		{
			if (required)
				throw;
			log?.LogError("ResManager lane hooks: patch failed: " + ex);
		}
	}

	private static void HandleMissing(bool required, string message)
	{
		if (required)
			throw new System.InvalidOperationException("required ResManager GameObject lane surface missing: " + message);
		Plugin.LogSource?.LogWarning("ResManager lane hooks: " + message);
	}

	private static System.Action<string> BuildProbeLog(ManualLogSource log, bool required)
	{
		return msg =>
		{
			if (required)
				log?.LogInfo("ResManager lane hooks: " + msg);
			else
				log?.LogWarning("ResManager lane hooks: " + msg);
		};
	}

	private static void PostfixResManagerGetUnityObject(object __instance, [HarmonyArgument(0)] string resPath, ref UnityEngine.Object __result)
	{
		var go = __result as GameObject;
		if (!go)
		{
			VanillaDungeonTooltipPortraitResLoader.TryNoteResManagerInstance(__instance);
			Homm3ImportVisuals.TryNoteResManagerInstance(__instance);
			return;
		}

		PostProcessGameObjectResult(__instance, resPath, ref go);
		__result = go;
	}

	private static void PostfixResManagerGetGameObject(object __instance, [HarmonyArgument(0)] string resPath, ref GameObject __result)
	{
		PostProcessGameObjectResult(__instance, resPath, ref __result);
	}

	private static void PostProcessGameObjectResult(object __instance, string resPath, ref GameObject __result)
	{
		VanillaDungeonTooltipPortraitResLoader.TryNoteResManagerInstance(__instance);
		Homm3ImportVisuals.TryNoteResManagerInstance(__instance);
		Homm3ImportVisuals.TryCacheNativeResManagerGameObject(resPath, __result);
		if (!LooksLikeResourcePath(resPath))
		{
			Trace("skip non-resource path '" + Sanitize(resPath) + "'");
			return;
		}
		Trace("path='" + Sanitize(resPath) + "' preResult=" + (__result ? __result.name : "(null)"));
		Homm3ImportResManagerHook.PostfixResGetGameObject(resPath, ref __result);
		Homm3ImportVisuals.PostfixResGetProjectileGameObject(resPath, ref __result);
		EsquirePikemanVisuals.PostfixResGetGameObjectMapOnly(resPath, ref __result);
		Trace("path='" + Sanitize(resPath) + "' postResult=" + (__result ? __result.name : "(null)"));
	}

	internal static void ResetRegistrationStateForUnload()
	{
		_registered = false;
		_traceLines = 0;
	}

	private static bool LooksLikeResourcePath(string path)
	{
		if (string.IsNullOrWhiteSpace(path))
			return false;
		var p = path.Trim();
		// Resource keys we care about are slash-separated ("units/...", "Humans/...", "sounds/...").
		if (p.IndexOf('/') < 0 && p.IndexOf('\\') < 0)
			return false;
		if (p.IndexOf(' ') >= 0)
			return false;
		return true;
	}

	private static string Sanitize(string s) =>
		string.IsNullOrEmpty(s) ? string.Empty : s.Replace('\r', ' ').Replace('\n', ' ').Replace('\t', ' ');

	private static void Trace(string msg)
	{
		if (_traceLines >= MaxTraceLines)
			return;
		_traceLines++;
		Plugin.LogSource?.LogInfo("ResManager lane hooks trace: " + msg);
	}
}
