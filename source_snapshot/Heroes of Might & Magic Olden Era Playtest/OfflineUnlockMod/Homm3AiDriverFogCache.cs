using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// AI-driver FoW cache: remember the live <c>DataFogOfWar</c> instance from native fog
/// initialize / visibility-read. Session static <c>Data</c> can be null on adventure map
/// while the engine still invokes fog APIs — dump consumes this cache fail-closed until set.
/// </summary>
internal static class Homm3AiDriverFogCache
{
	private static readonly object Gate = new object();
	private static object _fogOfWar;
	private static string _source;
	private static object _liveSide;
	private static string _liveSideSource;
	private static bool _patched;
	private static ManualLogSource _log;

	internal static bool TryGetLiveSide(out object side, out string source)
	{
		lock (Gate)
		{
			side = _liveSide;
			source = _liveSideSource;
			return side != null;
		}
	}

	internal static void RememberSide(object side, string source)
	{
		if (side == null)
			return;
		lock (Gate)
		{
			_liveSide = side;
			_liveSideSource = source ?? "unknown";
		}
	}

	internal static bool TryGetFogOfWar(out object fogOfWar, out string source)
	{
		lock (Gate)
		{
			fogOfWar = _fogOfWar;
			source = _source;
			return fogOfWar != null;
		}
	}

	internal static void Remember(object fogOfWar, string source)
	{
		if (fogOfWar == null)
			return;
		lock (Gate)
		{
			_fogOfWar = fogOfWar;
			_source = source ?? "unknown";
		}
	}

	internal static void Clear()
	{
		lock (Gate)
		{
			_fogOfWar = null;
			_source = null;
			_liveSide = null;
			_liveSideSource = null;
		}
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_patched || harmony == null)
			return;
		_log = log;

		var fogType = ModActions.GetHexType("Hex.Session.Data.DataFogOfWar")
			?? ModActions.GetHexType("DataFogOfWar");
		if (fogType == null)
		{
			log?.LogWarning("HOMM3_AI_FOG DataFogOfWar type unresolved; FoW cache patches skipped.");
			return;
		}

		var patched = 0;
		patched += PatchExact(
			harmony,
			fogType,
			GameSymbols.AdventureVisionLaws.FogInitialize.NameHints,
			parameterCount: 2,
			requireVoid: true,
			nameof(PostfixFogInitialize));
		patched += PatchExact(
			harmony,
			fogType,
			GameSymbols.AdventureVisionLaws.FogVisibilityRead.NameHints,
			parameterCount: 1,
			requireVoid: false,
			nameof(PostfixFogVisibilityRead));

		// Side.fogData getter — captures FoW even when visibility-read is not yet hit this frame.
		var sideType = ModActions.GetHexType("Hex.Session.Data.Side")
			?? ModActions.GetHexType("Side");
		if (sideType != null)
		{
			foreach (var name in GameSymbols.AdventureVisionLaws.SideFogDataMembers)
			{
				if (patchedFogDataGetter(harmony, sideType, name))
				{
					patched++;
					break;
				}
			}
		}

		_patched = patched > 0;
		log?.LogWarning(
			"HOMM3_AI_FOG cache patches registered="
			+ patched.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " on "
			+ (fogType.FullName ?? fogType.Name)
			+ ".");
	}

	private static int PatchExact(
		Harmony harmony,
		Type type,
		string[] names,
		int parameterCount,
		bool requireVoid,
		string postfixName)
	{
		var patched = 0;
		if (names == null)
			return 0;
		for (var i = 0; i < names.Length; i++)
		{
			var method = ResolveExactMethod(type, names[i], parameterCount, requireVoid);
			if (method == null)
				continue;
			var postfix = AccessTools.Method(typeof(Homm3AiDriverFogCache), postfixName);
			if (postfix == null)
				continue;
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out _))
				continue;
			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
			break;
		}
		return patched;
	}

	private static bool patchedFogDataGetter(Harmony harmony, Type sideType, string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		MethodInfo getter = null;
		try
		{
			var prop = sideType.GetProperty(
				name,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop != null && prop.CanRead && prop.GetIndexParameters().Length == 0)
				getter = prop.GetGetMethod(true);
		}
		catch { getter = null; }
		if (getter == null)
		{
			try
			{
				getter = sideType.GetMethod(
					name.StartsWith("get_", StringComparison.Ordinal) ? name : "get_" + name,
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					Type.EmptyTypes,
					null);
			}
			catch { getter = null; }
		}
		if (getter == null || getter.ReturnType == typeof(void))
			return false;
		var postfix = AccessTools.Method(typeof(Homm3AiDriverFogCache), nameof(PostfixSideFogDataGetter));
		if (postfix == null || !GameMember.IsHarmonyPatchCompatible(getter, postfix, out _))
			return false;
		harmony.Patch(getter, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return true;
	}

	private static MethodInfo ResolveExactMethod(Type type, string name, int parameterCount, bool requireVoid)
	{
		if (type == null || string.IsNullOrEmpty(name))
			return null;
		MethodInfo[] methods;
		try { methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic); }
		catch { return null; }
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (method == null || !string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (requireVoid && method.ReturnType != typeof(void))
				continue;
			if (!requireVoid && method.ReturnType == typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static void PostfixFogInitialize(object __instance)
	{
		Remember(__instance, "DataFogOfWar.FogInitialize");
	}

	private static void PostfixFogVisibilityRead(object __instance)
	{
		Remember(__instance, "DataFogOfWar.FogVisibilityRead");
	}

	private static void PostfixSideFogDataGetter(object __instance, object __result)
	{
		if (__instance != null)
			RememberSide(__instance, "Side.fogData.this");
		if (__result != null)
			Remember(__result, "Side.fogData");
	}
}
