using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

internal static class Homm3BattleUnitInitDiagnostics
{
	private const string GrepKey = "HOMM3_BATTLE_UNIT_INIT_DIAG";
	private static int _exceptionLogs;
	private static int _registered;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		var unitType = ResolveUnitType();
		if (unitType == null)
			throw new MissingMemberException("Battle Unit.Init diagnostic type resolution failed: Unit");

		var method = Homm3BattleUnitInitSurface.FindUnitInitMethod(unitType);
		if (method == null)
			throw new MissingMethodException(GameSymbols.BattleUnitInit.UnitTypeId + ".Init battle unit initializer");

		harmony.Patch(method, finalizer: new HarmonyMethod(typeof(Homm3BattleUnitInitDiagnostics), nameof(FinalizerUnitInit)));
		_registered++;
		log?.LogInfo(
			"HOMM3_BATTLE_UNIT_INIT_DIAG registered "
			+ unitType.FullName + "." + method.Name
			+ " params=" + method.GetParameters().Length
			+ " signature='" + DescribeMethodSignature(method) + "'");
	}

	private static Type ResolveUnitType()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				var type = asm.GetType(GameSymbols.BattleUnitInit.UnitTypeId, throwOnError: false);
				if (type != null)
					return type;
			}
			catch { }
		}
		try { return typeof(Unit); }
		catch { return null; }
	}

	private static string DescribeMethodSignature(MethodInfo method)
	{
		if (method == null)
			return "?";
		var ps = method.GetParameters();
		var parts = new string[ps.Length];
		for (var i = 0; i < ps.Length; i++)
			parts[i] = ps[i].ParameterType?.Name ?? "?";
		return method.ReturnType?.Name + " (" + string.Join(", ", parts) + ")";
	}

	private static Exception FinalizerUnitInit(Exception __exception, MethodBase __originalMethod, object[] __args)
	{
		if (__exception == null)
			return null;
		if (_exceptionLogs++ >= 24)
			return __exception;

		try
		{
			var configSid = GetArg(__args, 7);
			var unitId = GetArg(__args, 0);
			var slot = GetArg(__args, 4);
			var stacks = GetArg(__args, 5);
			var lifetime = GetArg(__args, 6);
			Plugin.LogSource?.LogError(
				GrepKey
				+ " event=unit-init-exception"
				+ " method='" + (__originalMethod?.DeclaringType?.FullName ?? "?") + "." + (__originalMethod?.Name ?? "?") + "'"
				+ " configSid='" + configSid + "'"
				+ " unitId='" + unitId + "'"
				+ " slot='" + slot + "'"
				+ " stacks='" + stacks + "'"
				+ " lifetime='" + lifetime + "'"
				+ " exception='" + __exception.GetType().FullName + ": " + __exception.Message + "'");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(GrepKey + " event=diagnostic-failed error='" + ex.Message + "'");
		}
		return __exception;
	}

	private static string GetArg(object[] args, int index)
	{
		if (args == null || index < 0 || index >= args.Length)
			return "?";
		return args[index]?.ToString() ?? "(null)";
	}
}
