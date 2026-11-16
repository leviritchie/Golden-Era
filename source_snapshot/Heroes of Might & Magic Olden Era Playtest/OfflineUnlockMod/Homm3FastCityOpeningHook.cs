using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

// Clamps the SmoothOpening black-screen frame count for custom cities. 26297049 (static native evidence, port
// 26297049 P5): the tracker's Int32(EType, String) is round(Single(EType, String) * 60), plus 2 for EType 1, where the
// Single is the longest recorded open time for the content sid, capped at 10 s. So vanilla can still ask for up to
// 600 frames and the clamp stays. Every Single(EType, String) caller is an Int32(EType, String) wrapper, and the
// facade's static Int32(EType, String) tail-jumps into the scoped tracker method, so clamping the Int32 results
// covers the Single path; the other tracker Int32 overloads (_PDM_0.._3) are code copies with no live caller.
internal static class Homm3FastCityOpeningHook
{
	private const int SmoothOpeningCityTypeValue = 2;
	private static readonly HashSet<MethodBase> PatchedMethods = new();
	private static readonly HashSet<string> ClampLogKeys = new(StringComparer.Ordinal);
	private static ManualLogSource _log;
	private static int _maxFrames = 12;
	private static bool _enabled;

	internal static void TryRegister(Harmony harmony, ManualLogSource log, bool enabled, int maxFrames)
	{
		_log = log;
		_enabled = enabled;
		_maxFrames = Math.Max(0, maxFrames);
		if (!enabled)
		{
			log?.LogInfo("HoMM3 fast city opening: skipped by homm3FastCityOpening=false.");
			return;
		}
		if (harmony == null)
			return;

		var patched = 0;
		foreach (var typeName in GameSymbols.SmoothOpening.OpenTimeTrackerTypeHints)
		{
			var type = ModActions.GetHexType(typeName);
			if (type == null)
				continue;
			patched += PatchNamedFrameMethods(harmony, type, GameSymbols.SmoothOpening.CityFrameCount);
		}
		foreach (var typeName in GameSymbols.SmoothOpening.OpeningFacadeTypeHints)
		{
			var type = ModActions.GetHexType(typeName);
			if (type == null)
				continue;
			patched += PatchNamedFrameMethods(harmony, type, GameSymbols.SmoothOpening.OpeningFrameCount);
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 fast city opening: no SmoothOpening frame-count methods were found; custom city opening timing remains native.");
			return;
		}

		log?.LogInfo("HoMM3 fast city opening: patched " + patched + " SmoothOpening frame-count method(s), maxFrames=" + _maxFrames + ".");
	}

	private static int PatchNamedFrameMethods(Harmony harmony, Type type, GameSymbols.MethodSymbol symbol)
	{
		var count = 0;
		var declared = AccessTools.GetDeclaredMethods(type);
		var shapeMatches = new List<string>();
		foreach (var method in declared)
		{
			if (IsFrameCountMethod(method))
				shapeMatches.Add(method.Name);
		}
		foreach (var name in symbol.NameHints)
		{
			foreach (var method in declared)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (!IsFrameCountMethod(method))
					continue;
				if (!PatchedMethods.Add(method))
					continue;

				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3FastCityOpeningHook), nameof(ClampCityOpenFrames)));
				count++;
			}
		}
		if (count == 0 && shapeMatches.Count > 0)
		{
			// The shape alone is ambiguous (several Int32(EType, String) overloads), so a hint miss is not guessed.
			_log?.LogWarning("HoMM3 fast city opening: " + symbol.Id + " named no Int32(EType, String) method on " + type.FullName
				+ " (shape matches: " + string.Join(", ", shapeMatches) + "; " + GameBuild.Describe() + "); that type stays native.");
		}
		return count;
	}

	private static bool IsFrameCountMethod(MethodInfo method)
	{
		if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(int))
			return false;

		var parameters = method.GetParameters();
		if (parameters.Length != 2)
			return false;

		return parameters[0].ParameterType.IsEnum
			&& string.Equals(parameters[0].ParameterType.Name, "EType", StringComparison.Ordinal)
			&& parameters[1].ParameterType == typeof(string);
	}

	private static void ClampCityOpenFrames(ref int __result, object __0, string __1, MethodBase __originalMethod)
	{
		if (!_enabled || __result <= _maxFrames)
			return;
		if (!IsCityOpenType(__0) || !Homm3CustomFactionRegistry.IsCustomCitySid(__1))
			return;

		var before = __result;
		__result = _maxFrames;
		var key = (__originalMethod?.DeclaringType?.FullName ?? "?") + "." + (__originalMethod?.Name ?? "?") + "|" + __1;
		if (ClampLogKeys.Add(key))
		{
			_log?.LogInfo(
				"HoMM3 fast city opening: clamped SmoothOpening city frames for "
				+ __1
				+ " from "
				+ before
				+ " to "
				+ _maxFrames
				+ " via "
				+ (__originalMethod?.DeclaringType?.FullName ?? "?")
				+ "."
				+ (__originalMethod?.Name ?? "?"));
		}
	}

	private static bool IsCityOpenType(object value)
	{
		if (value == null)
			return false;
		try
		{
			return Convert.ToInt32(value) == SmoothOpeningCityTypeValue;
		}
		catch
		{
			return false;
		}
	}
}
