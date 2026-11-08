using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise post-battle law families.
/// This traces the exact battle-result world-apply surface so later corpse,
/// spoils, defensive-win, and low-loss laws can use committed battle identity
/// instead of animations, reward UI, or generic resource mutations.
/// </summary>
internal static class Homm3BattleResultLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_battle_result_law_diag.flag";

	private const int LogCap = 80;
	private const int MaxUnitsPerSide = 8;
	private static bool _registered;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		_registered = true;

		MethodInfo method;
		try
		{
			method = ResolveApplyBattleResultMethod();
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 battle-result law diagnostics failed closed during surface resolution: " + ex.Message);
			return;
		}

		if (method == null)
		{
			log?.LogWarning("HoMM3 battle-result law diagnostics: exact battle-result apply surface not found; post-battle law gameplay remains disabled.");
			return;
		}

		var prefix = AccessTools.Method(typeof(Homm3BattleResultLawDiagnostics), nameof(PrefixApplyBattleResult));
		var postfix = AccessTools.Method(typeof(Homm3BattleResultLawDiagnostics), nameof(PostfixApplyBattleResult));
		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var prefixReason))
		{
			log?.LogWarning("HoMM3 battle-result law diagnostics: refusing incompatible prefix for " + FormatMethod(method) + ": " + prefixReason);
			return;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var postfixReason))
		{
			log?.LogWarning("HoMM3 battle-result law diagnostics: refusing incompatible postfix for " + FormatMethod(method) + ": " + postfixReason);
			return;
		}

		harmony.Patch(
			method,
			prefix: new HarmonyMethod(prefix) { priority = Priority.Last },
			postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		log?.LogInfo("HoMM3 battle-result law diagnostics registered exact trace patch on " + FormatMethod(method) + ". Diagnostic observation only.");
		log?.LogInfo("HoMM3 battle-result law diagnostics: traces are observational only; do not implement corpse/spoils/low-loss laws until runtime proof confirms committed ordering, side identity, and active law-rank access.");
		log?.LogInfo("HoMM3 battle-result law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static MethodInfo ResolveApplyBattleResultMethod()
	{
		var assembly = typeof(TransferSide).Assembly;
		var logicType = ResolveTypeByNames(assembly, GameSymbols.BattleResultLaws.BattleLogicTypeHints);
		if (logicType == null)
			return null;

		foreach (var managerType in ResolveTypesByNames(assembly, GameSymbols.BattleResultLaws.BattlesManagerTypeHints))
		{
			foreach (var name in GameSymbols.BattleResultLaws.ApplyBattleResult.NameHints)
			{
				var method = managerType.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (method == null || method.ReturnType != typeof(void))
					continue;
				var ps = method.GetParameters();
				if ((ps.Length == 1 || ps.Length == 2)
				    && ps[0].ParameterType == logicType
				    && (ps.Length == 1 || ps[1].ParameterType == typeof(bool)))
					return method;
			}
		}

		return null;
	}

	private static void PrefixApplyBattleResult(object __0, MethodBase __originalMethod)
	{
		LogTrace("pre-apply", __0, __originalMethod);
	}

	private static void PostfixApplyBattleResult(object __0, MethodBase __originalMethod)
	{
		LogTrace("post-apply", __0, __originalMethod);
	}

	private static void LogTrace(string stage, object battleLogic, MethodBase method)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 battle-result law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " battle="
				+ DescribeBattleLogic(battleLogic)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 battle-result law diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeBattleLogic(object battleLogic)
	{
		if (battleLogic == null)
			return "null";

		var id = ReadIntMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicIdFields);
		var applied = ReadBoolMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicAlreadyAppliedFields);
		var transferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicTransferBattleFields) as TransferBattle;
		var startedTransferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicStartedTransferBattleFields) as TransferBattle;
		var resultInfo = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicBattleResultInfoFields) as BattleResultInfo;

		var parts = new List<string>
		{
			"type=" + (battleLogic.GetType().FullName ?? battleLogic.GetType().Name),
			"id=" + id,
			"applied=" + (applied.HasValue ? applied.Value.ToString() : "null"),
			"winner=" + (resultInfo != null ? resultInfo.winnerIndex.ToString() : "null"),
			"losers=[" + string.Join(",", ResolveLoserIndices(resultInfo)) + "]",
			"startedSides=" + CountSides(startedTransferBattle),
			"afterSides=" + CountSides(transferBattle),
			"battleLogicLaws=" + DescribeActiveKnownCustomLaws(battleLogic),
			"startedBattleLaws=" + DescribeActiveKnownCustomLaws(startedTransferBattle),
			"afterBattleLaws=" + DescribeActiveKnownCustomLaws(transferBattle)
		};

		parts.Add("sides=[" + DescribeSides(startedTransferBattle, transferBattle, resultInfo) + "]");
		return "{" + string.Join("|", parts) + "}";
	}

	private static string DescribeSides(TransferBattle started, TransferBattle after, BattleResultInfo resultInfo)
	{
		var max = Math.Max(CountSides(started), CountSides(after));
		if (max <= 0)
			return "";

		var sideParts = new List<string>();
		for (var i = 0; i < max; i++)
		{
			var startedSide = started != null && started.sides != null && i < started.sides.Length ? started.sides[i] : null;
			var afterSide = after != null && after.sides != null && i < after.sides.Length ? after.sides[i] : null;
			sideParts.Add(DescribeSide(i, startedSide, afterSide, resultInfo));
		}

		return string.Join(";", sideParts);
	}

	private static string DescribeSide(int index, TransferSide started, TransferSide after, BattleResultInfo resultInfo)
	{
		var role = resultInfo != null && resultInfo.winnerIndex == index ? "winner" : "side";
		return "{idx="
		       + index
		       + ",role="
		       + role
		       + ",heroBefore="
		       + HeroSid(started)
		       + ",heroAfter="
		       + HeroSid(after)
		       + ",unitsBefore="
		       + CountUnits(started)
		       + ",unitsAfter="
		       + CountUnits(after)
		       + ",stacksBefore="
		       + CountStacks(started)
		       + ",stacksAfter="
		       + CountStacks(after)
		       + ",losses="
		       + SummarizeLosses(started, after)
		       + ",startedLaws="
		       + DescribeActiveKnownCustomLaws(started)
		       + ",afterLaws="
		       + DescribeActiveKnownCustomLaws(after)
		       + "}";
	}

	private static string DescribeActiveKnownCustomLaws(object owner)
	{
		if (owner == null)
			return "null";

		var lawParts = new List<string>(8);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(owner, lawIndex, out var state))
				continue;
			lawParts.Add("index=" + state.Index
			             + ",rank=" + state.Rank
			             + ",faction=" + state.FactionSid
			             + ",family=" + state.Family);
			if (lawParts.Count >= 8)
				break;
		}

		return lawParts.Count == 0 ? "none-or-unresolved" : "[" + string.Join(";", lawParts) + "]";
	}

	private static string SummarizeLosses(TransferSide started, TransferSide after)
	{
		if (started == null || started.units == null)
			return "none";

		var parts = new List<string>();
		foreach (var before in started.units)
		{
			if (before == null)
				continue;
			var beforeStacks = Math.Max(0, before.stacks);
			var afterStacks = FindAfterStacks(after, before);
			var lost = Math.Max(0, beforeStacks - afterStacks);
			if (lost <= 0)
				continue;
			parts.Add(NormalizeSid(before.configSid) + ":" + beforeStacks + "->" + afterStacks + " lost=" + lost);
			if (parts.Count >= MaxUnitsPerSide)
				break;
		}

		return parts.Count == 0 ? "none" : string.Join(",", parts);
	}

	private static int FindAfterStacks(TransferSide after, TransferUnit before)
	{
		if (after == null || after.units == null || before == null)
			return 0;
		foreach (var candidate in after.units)
		{
			if (candidate == null)
				continue;
			if (candidate.slotPos == before.slotPos
			    && string.Equals(NormalizeSid(candidate.configSid), NormalizeSid(before.configSid), StringComparison.Ordinal))
				return Math.Max(0, candidate.stacks);
		}
		return 0;
	}

	private static List<int> ResolveLoserIndices(BattleResultInfo resultInfo)
	{
		var result = new List<int>();
		if (resultInfo == null)
			return result;

		var losers = ReadMember(resultInfo, GameSymbols.BattleResultLaws.BattleResultLosersFields);
		foreach (var loser in EnumerateObjects(losers))
		{
			if (TryReadIntMember(loser, GameSymbols.BattleResultLaws.BattleResultLoserIndexFields, out var loserIndex)
			    && loserIndex >= 0)
				result.Add(loserIndex);
		}

		return result;
	}

	private static int CountSides(TransferBattle battle)
	{
		return battle != null && battle.sides != null ? battle.sides.Length : 0;
	}

	private static int CountUnits(TransferSide side)
	{
		return side != null && side.units != null ? side.units.Length : 0;
	}

	private static int CountStacks(TransferSide side)
	{
		if (side == null || side.units == null)
			return 0;
		var total = 0;
		foreach (var unit in side.units)
		{
			if (unit != null)
				total += Math.Max(0, unit.stacks);
		}
		return total;
	}

	private static string HeroSid(TransferSide side)
	{
		return NormalizeSid(side?.hero?.configId) ?? "null";
	}

	private static IEnumerable<object> EnumerateObjects(object collection)
	{
		if (collection == null || collection is string || !(collection is IEnumerable enumerable))
			yield break;
		foreach (var item in enumerable)
		{
			if (item != null)
				yield return item;
		}
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj, null);
			}
			catch
			{
			}
			try
			{
				var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (field != null)
					return field.GetValue(obj);
			}
			catch
			{
			}
			try
			{
				var method = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (method != null && method.GetParameters().Length == 0)
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static int ReadIntMember(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		return value is int i ? i : 0;
	}

	private static bool? ReadBoolMember(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		return value is bool b ? b : null;
	}

	private static bool TryReadIntMember(object obj, string[] names, out int result)
	{
		result = 0;
		var value = ReadMember(obj, names);
		if (value is int i)
		{
			result = i;
			return true;
		}

		return false;
	}

	private static Type ResolveTypeByNames(Assembly asm, IEnumerable<string> names)
	{
		if (asm == null || names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null)
				return type;
			type = GameMember.FindType("law.battleResult.type." + name, name);
			if (type != null && type.Assembly == asm)
				return type;
		}
		return null;
	}

	private static IEnumerable<Type> ResolveTypesByNames(Assembly asm, IEnumerable<string> names)
	{
		if (asm == null || names == null)
			yield break;
		var emitted = new HashSet<Type>();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null && emitted.Add(type))
				yield return type;
			type = GameMember.FindType("law.battleResult.type." + name, name);
			if (type != null && type.Assembly == asm && emitted.Add(type))
				yield return type;
		}
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
