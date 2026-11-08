using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// <c>Player.log</c>: <c>NullReferenceException</c> in the ELang/font bootstrap helper from <c>il..cctor</c> while
/// <c>BhAppStartScript.Update</c> runs. Swallowing that NRE (first only logged) allows ELang static init to complete
/// in offline / no-store conditions when that NRE is the only failure.
/// </summary>
internal static class ElangHjsNreWorkaround
{
	private static bool _nreSwallowLogged;
	private static bool _agentELogged;
	private static bool _patched;

	internal static bool IsPatched => _patched;

	internal static void ResetHarmonyGuardForHotReload()
	{
		_patched = false;
	}

	internal static void ScheduleDeferredTry(Harmony h, ManualLogSource log)
	{
		log?.LogWarning(
			"ELang: font bootstrap helper not found at plugin load; deferred GameObject poller skipped because launch-time "
			+ "Unity object creation can re-enter current Steam UI refresh paths and crash startup.");
	}

	internal static bool TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched)
			return true;
		try
		{
			var m = FindHjsMethod();
			if (m == null)
				return false;
			h.Patch(
				m,
				finalizer: new HarmonyMethod(
					typeof(ElangHjsNreWorkaround),
					nameof(SwallowHjsNreIfAny)));
			_patched = true;
			log?.LogInfo(
				"ELang: Harmony finalizer on "
				+ m.DeclaringType?.FullName
				+ "."
				+ m.Name
				+ " (NRE in ELang/font static init / offline).");
			return true;
		}
		catch (Exception ex)
		{
			log?.LogError("ELang: font bootstrap patch lookup failed; workaround skipped: " + ex);
			return false;
		}
	}

	// Owner and method come only from GameSymbols.ElangFontBootstrap. A hint the current-build scope refused
	// resolves nothing, so the workaround is skipped; there is no per-type name or shape scan behind it.
	private static MethodInfo FindHjsMethod()
	{
		var elang = ResolveElangType();
		if (elang == null)
			return null;
		var fontByLang = ResolveFontByLangType(elang.Assembly);
		if (fontByLang == null)
			return null;
		var dictType = BuildFontDictionaryType(fontByLang);
		if (dictType == null)
			return null;

		var owner = GameMember.FindTypeFromHints(
			GameSymbols.ElangFontBootstrap.OwnerTypeId,
			GameSymbols.ElangFontBootstrap.OwnerTypeHints);
		if (owner == null)
			return null;
		var symbol = GameSymbols.ElangFontBootstrap.Bootstrap;
		var methods = GameMember.FindMethods(owner, typeof(void), new[] { elang, dictType }, symbol);
		var names = symbol.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < names.Length; i++)
		{
			if (string.IsNullOrEmpty(names[i]) || GameSymbolScope.IsSentinel(names[i]))
				continue;
			foreach (var method in methods)
			{
				if (method != null && method.IsStatic && string.Equals(method.Name, names[i], StringComparison.Ordinal))
					return method;
			}
		}
		return null;
	}

	private static Type ResolveElangType()
	{
		var elang = typeof(ObjCityConfig).Assembly.GetType("Hex.UI.ELang", false, false);
		if (elang != null)
			return elang;
		elang = Type.GetType("Hex.UI.ELang, Assembly-CSharp, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null", false, false);
		return elang;
	}

	private static Type ResolveFontByLangType(Assembly preferredAssembly)
	{
		var fontByLang = preferredAssembly?.GetType("Hex.UI.FontByLang", false, false);
		if (fontByLang != null)
			return fontByLang;
		return typeof(ObjCityConfig).Assembly.GetType("Hex.UI.FontByLang", false, false);
	}

	private static Type BuildFontDictionaryType(Type fontByLang)
	{
		try
		{
			return typeof(Il2CppSystem.Collections.Generic.Dictionary<,>).MakeGenericType(typeof(string), fontByLang);
		}
		catch
		{
			return null;
		}
	}

	private static Exception SwallowHjsNreIfAny(Exception __exception)
	{
		if (__exception == null)
			return null;
		if (!IsNullReferenceInHjs(__exception))
			return __exception;
		if (!_nreSwallowLogged)
		{
			_nreSwallowLogged = true;
			Plugin.LogSource?.LogWarning(
				"ELang: Suppressed a NullReferenceException in ELang/font bootstrap (offline / no store).");
		}
		#region agent log
		if (!_agentELogged)
		{
			_agentELogged = true;
			AgentDebugLog.Write("E", "ElangHjsNreWorkaround:SwallowHjsNreIfAny", "swallow_nre", "{}");
		}
		#endregion
		return null;
	}

	private static bool IsNullReferenceInHjs(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			if (e is NullReferenceException)
				return true;
		}
		var t = ex.ToString();
		if (t.IndexOf("NullReferenceException", StringComparison.Ordinal) < 0)
			return false;
		if (t.IndexOf("in.hjs", StringComparison.Ordinal) >= 0
		    || t.IndexOf("::hjs", StringComparison.Ordinal) >= 0
		    || t.IndexOf("DMD<in", StringComparison.Ordinal) >= 0)
			return true;
		return t.IndexOf("Method_Private_Static_Void_ELang_Dictionary_2_String_FontByLang", StringComparison.Ordinal) >= 0
		       || (t.IndexOf("Hex.UI.ELang", StringComparison.Ordinal) >= 0
		           && t.IndexOf("Hex.UI.FontByLang", StringComparison.Ordinal) >= 0);
	}
}

/// <summary>Polls <see cref="ElangHjsNreWorkaround.TryRegister"/> on the main thread if the bootstrap helper was not found at plugin load.</summary>
public sealed class ElangHjsNreDeferredReg : MonoBehaviour
{
	public Harmony Harmony;
	public ManualLogSource Log;
	private int _frames;

	private void Update()
	{
		_frames++;
		if (_frames % 20 != 0 && _frames < 900)
			return;
		if (ElangHjsNreWorkaround.TryRegister(Harmony, Log) || _frames >= 900)
		{
			if (_frames >= 900 && !ElangHjsNreWorkaround.IsPatched)
				Log?.LogWarning("ELang: font bootstrap helper not found after deferred poll; NRE workaround inactive.");
			Destroy(gameObject);
		}
	}
}
