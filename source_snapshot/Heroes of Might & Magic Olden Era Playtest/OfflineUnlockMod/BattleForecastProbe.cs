using System;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

internal static class BattleForecastProbeHelpers
{
	internal static void LogInput(string methodName, DamageUiParams damageUiParams, bool flag)
	{
		if (!RetaliationDebug.IsEnabled())
		{
			return;
		}

		try
		{
			RetaliationDebug.Log($"{methodName} input={FormatDamageUiParams(damageUiParams)} flag={flag}");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Retaliation forecast probe logging failed: {ex.Message}");
		}
	}

	internal static void LogResult(string methodName, DamageUiParams damageUiParams, bool flag, object result)
	{
		if (!RetaliationDebug.IsEnabled())
		{
			return;
		}

		try
		{
			RetaliationDebug.Log(
				$"{methodName} result={FormatForecast(result)} " +
				$"from={FormatDamageUiParams(damageUiParams)} flag={flag}");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Retaliation forecast probe logging failed: {ex.Message}");
		}
	}

	private static string FormatDamageUiParams(DamageUiParams damageUiParams)
	{
		if (damageUiParams == null)
		{
			return "null";
		}

		return
			"{"
			+ $"caster={FormatCaster(ReadRenamed(damageUiParams, GameSymbols.LiveRenamedMembers.DamageUiParamsCaster))}, "
			+ $"castSource={FormatObject(ReadRenamed(damageUiParams, GameSymbols.LiveRenamedMembers.DamageUiParamsCastSource))}, "
			+ $"target={FormatObject(ReadRenamed(damageUiParams, GameSymbols.LiveRenamedMembers.DamageUiParamsTarget))}, "
			+ $"dmgMult={damageUiParams.dmgMult:0.###}, "
			+ $"sideCastType={damageUiParams.sideCastType}, "
			+ $"pathLength={damageUiParams.pathLength}"
			+ "}";
	}

	// Audit B5: the typed DamageUiParams getters bind deobf types (dyt/dyu/dyx) that live Golden Era
	// renames, so read by name; an unreadable member is reported, not thrown.
	private static object ReadRenamed(DamageUiParams owner, string[] names)
	{
		return DeobfInteropCompat.TryGetObjectMember(owner, out var value, names)
			? value
			: "<unresolved " + string.Join("/", names) + ">";
	}

	private static string FormatCaster(object caster)
	{
		if (caster == null)
		{
			return "null";
		}

		var stackCount = SafeInvoke(() => Convert.ToInt32(TryInvokeNoArg(caster, GameSymbols.DamageKill.StackCountGetter.NameHints)), fallback: int.MinValue);
		var defaultSource = SafeInvoke(() => TryInvokeNoArg(caster, GameSymbols.DamageRetaliation.CasterSourceGetter.NameHints), fallback: null);
		var stackText = stackCount == int.MinValue ? "?" : stackCount.ToString();

		return $"{FormatObject(caster)} stack={stackText} defaultSource={FormatObject(defaultSource)}";
	}

	private static string FormatForecast(object forecast)
	{
		if (forecast == null)
		{
			return "null";
		}

		if (DamageDistribution.ForecastReader.TryRead(forecast, out var values))
		{
			return forecast.GetType().Name + "{"
				+ $"damage={values.DamageMin}-{values.DamageMax}, "
				+ $"kills={values.KillMin}-{values.KillMax}"
				+ "}";
		}

		return
			forecast.GetType().Name + "{unmapped}";
	}

	private static string FormatObject(object value)
	{
		if (value == null)
		{
			return "null";
		}

		var pointer = value is Il2CppObjectBase il2Cpp ? il2Cpp.Pointer.ToInt64() : 0;
		var typeName = SafeInvoke(() => value.GetType().Name, fallback: value.GetType().FullName ?? "unknown");
		return pointer == 0 ? typeName : $"{typeName}@0x{pointer:x}";
	}

	private static object TryInvokeNoArg(object target, string[] names)
	{
		if (target == null || names == null)
			return null;
		var type = target.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var method = type.GetMethod(names[i], System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic, null, Type.EmptyTypes, null);
			if (method == null)
				continue;
			try { return method.Invoke(target, null); }
			catch { }
		}
		return null;
	}

	private static T SafeInvoke<T>(Func<T> action, T fallback)
	{
		try
		{
			return action();
		}
		catch
		{
			return fallback;
		}
	}
}

