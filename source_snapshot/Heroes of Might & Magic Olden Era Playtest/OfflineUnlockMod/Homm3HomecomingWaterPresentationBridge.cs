using System;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Release-safe registration for Homecoming path-preview depth xray on BhPathDrawer refresh.
/// </summary>
internal static class Homm3HomecomingWaterPresentationBridge
{
	internal const string DiagnosticFlag = "homm3_homecoming_water_presentation_probe.flag";
	internal const string ActiveArchitecture = Homm3HomecomingWaterPathPreviewXRay.ActiveArchitecture;

	private const string LogPrefix = "HOMM3_HOMECOMING_WATER_PRESENTATION";
	private const int HomecomingMapActiveRefreshFrames = 120;
	private const BindingFlags MethodFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

	private static bool _registered;
	private static ManualLogSource _log;
	private static readonly System.Collections.Generic.Dictionary<int, int> DrawerFingerprints = new();
	private static bool _homecomingMapActive;
	private static int _homecomingMapActiveFrame = -1;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Homecoming water presentation registration.");

		_log = log;
		Homm3HomecomingWaterPathPreviewXRay.SetLog(log);
		var patched = PatchPathDrawerRefresh(harmony);
		if (patched == 0)
			throw new MissingMethodException(LogPrefix + " path drawer refresh methods were not resolved.");
		PatchPathDrawerClear(harmony);
		_registered = true;
		log?.LogInfo(LogPrefix + " registered architecture=" + ActiveArchitecture + " pathDrawerRefreshPatches=" + patched + ".");
	}

	private static int PatchPathDrawerRefresh(Harmony harmony)
	{
		var pathDrawerType = ResolvePathDrawerType();
		var methods = FindRefreshMethods(pathDrawerType).ToArray();
		var postfix = new HarmonyMethod(typeof(Homm3HomecomingWaterPresentationBridge), nameof(PostfixPathDrawerRefresh));
		foreach (var method in methods)
			harmony.Patch(method, postfix: postfix);

		if (methods.Length > 0)
		{
			_log?.LogInfo(LogPrefix + " patched path drawer refresh methods="
				+ string.Join(",", methods.Select(method => method.Name)) + ".");
		}
		return methods.Length;
	}

	private static void PatchPathDrawerClear(Harmony harmony)
	{
		var pathDrawerType = ResolvePathDrawerType();
		var methods = FindClearMethods(pathDrawerType).ToArray();
		if (methods.Length == 0)
			throw new MissingMethodException(pathDrawerType.FullName, "path drawer Clear");

		var postfix = new HarmonyMethod(typeof(Homm3HomecomingWaterPresentationBridge), nameof(PostfixPathDrawerClear));
		foreach (var method in methods)
			harmony.Patch(method, postfix: postfix);

		_log?.LogInfo(LogPrefix + " patched path drawer clear methods="
			+ string.Join(",", methods.Select(method => method.Name)) + ".");
	}

	private static Type ResolvePathDrawerType()
	{
		var type = GameMember.FindTypeFromHints(
			GameSymbols.HomecomingWaterPresentation.PathDrawerTypeId,
			GameSymbols.HomecomingWaterPresentation.PathDrawerTypeHints,
			hint => AccessTools.TypeByName(hint));
		if (type == null)
			throw new MissingMemberException(LogPrefix + " path drawer type not found.");
		return type;
	}

	private static System.Collections.Generic.IEnumerable<MethodInfo> FindRefreshMethods(Type pathDrawerType)
	{
		MethodInfo[] methods;
		try { methods = pathDrawerType.GetMethods(MethodFlags); }
		catch { yield break; }

		var patched = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
		foreach (var name in GameSymbols.HomecomingWaterPresentation.PathDrawerRefreshMethodHints)
		{
			foreach (var method in methods)
			{
				if (method == null || !string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (!IsRefreshMethodShape(method) || IsExcludedRefreshMethod(method))
					continue;
				if (!patched.Add(method.Name))
					continue;
				yield return method;
			}
		}

		foreach (var name in GameSymbols.HomecomingWaterPresentation.PathDrawerShowMethodHints)
		{
			foreach (var method in methods)
			{
				if (method == null || !string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.ReturnType != typeof(void) || IsExcludedRefreshMethod(method))
					continue;
				if (!patched.Add(method.Name))
					continue;
				yield return method;
			}
		}
	}

	private static System.Collections.Generic.IEnumerable<MethodInfo> FindClearMethods(Type pathDrawerType)
	{
		MethodInfo[] methods;
		try { methods = pathDrawerType.GetMethods(MethodFlags); }
		catch { yield break; }

		var hinted = methods
			.Where(method => method != null && method.ReturnType == typeof(void) && method.GetParameters().Length == 0)
			.Where(method => GameSymbols.HomecomingWaterPresentation.PathDrawerClearMethodHints.Contains(method.Name, StringComparer.Ordinal))
			.OrderBy(method => Array.IndexOf(GameSymbols.HomecomingWaterPresentation.PathDrawerClearMethodHints, method.Name))
			.ToList();
		if (hinted.Count > 0)
		{
			yield return hinted[0];
			yield break;
		}

		foreach (var method in methods
			         .Where(method => method != null && method.ReturnType == typeof(void) && method.GetParameters().Length == 0)
			         .Where(method => method.Name.IndexOf("Clear", StringComparison.OrdinalIgnoreCase) >= 0)
			         .OrderBy(method => method.Name)
			         .Take(1))
			yield return method;
	}

	private static bool IsRefreshMethodShape(MethodInfo method)
	{
		if (method == null || method.ReturnType != typeof(void))
			return false;
		ParameterInfo[] parameters;
		try { parameters = method.GetParameters(); }
		catch { return false; }
		return parameters.Length == 0;
	}

	private static bool IsExcludedRefreshMethod(MethodInfo method)
		=> method != null
		   && GameSymbols.HomecomingWaterPresentation.PathDrawerExcludedRefreshMethodHints.Contains(method.Name, StringComparer.Ordinal);

	private static bool IsHomecomingMapActive()
	{
		if (Time.frameCount - _homecomingMapActiveFrame < HomecomingMapActiveRefreshFrames)
			return _homecomingMapActive;
		_homecomingMapActiveFrame = Time.frameCount;
		_homecomingMapActive = Homm3HomecomingWaterPresentationOverlay.TryReadHomecomingMapContext(out _, out _, out _);
		return _homecomingMapActive;
	}

	private static void PostfixPathDrawerRefresh(MonoBehaviour __instance)
	{
		try
		{
			if (!__instance || !IsHomecomingMapActive())
				return;

			var drawerId = __instance.GetInstanceID();
			var fingerprint = Homm3HomecomingWaterPathPreviewXRay.ComputeFingerprint(__instance.transform);
			if (fingerprint == 0)
				return;
			if (DrawerFingerprints.TryGetValue(drawerId, out var previous) && previous == fingerprint)
				return;

			DrawerFingerprints[drawerId] = fingerprint;
			Homm3HomecomingWaterPathPreviewXRay.ApplyForDrawer(__instance.transform);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + " path drawer refresh postfix failed: " + ex.Message);
		}
	}

	private static void PostfixPathDrawerClear(MonoBehaviour __instance)
	{
		try
		{
			if (!__instance)
				return;
			DrawerFingerprints.Remove(__instance.GetInstanceID());
			Homm3HomecomingWaterPathPreviewXRay.ReleaseForDrawer(__instance.transform);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + " path drawer clear postfix failed: " + ex.Message);
		}
	}
}
