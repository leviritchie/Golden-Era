using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Prefix-only battle-result proof for post-battle custom law packets.
/// Mirrors the already-working skeletal necromancy surface shape, but performs no gameplay mutation.
/// June 19 status: source-prepared only until a pilot battle completes without a turn-end crash and logs this probe.
/// </summary>
internal static class Homm3BattleResultSafeLawProbe
{
	internal const string DiagnosticFlag = "homm3_battle_result_safe_law_probe.flag";

	private const int LogCap = 12;
	private static bool _registered;
	private static int _logged;
	private static readonly HashSet<int> ObservedBattleLogicKeys = new();

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;

		MethodInfo method;
		try
		{
			method = Homm3BattleResultSurface.ResolveApplyBattleResultMethod();
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 battle-result safe law probe failed closed during surface resolution: " + ex.Message);
			return;
		}

		if (method == null)
		{
			log?.LogWarning("HoMM3 battle-result safe law probe: exact battle-result apply surface not found.");
			return;
		}

		var prefix = AccessTools.Method(typeof(Homm3BattleResultSafeLawProbe), nameof(PrefixApplyBattleResult));
		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
		{
			log?.LogWarning("HoMM3 battle-result safe law probe: refusing incompatible prefix for " + FormatMethod(method) + ": " + reason);
			return;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.Last });
		_registered = true;
		log?.LogInfo("HoMM3 battle-result safe law probe registered prefix-only trace on " + FormatMethod(method) + ". Diagnostic observation only.");
	}

	private static void PrefixApplyBattleResult(object __0, MethodBase __originalMethod)
	{
		try
		{
			if (__0 == null || _logged >= LogCap)
				return;
			if (ReadBoolMember(__0, GameSymbols.BattleResultLaws.BattleLogicAlreadyAppliedFields) == true)
				return;

			var key = GetBattleLogicKey(__0);
			lock (ObservedBattleLogicKeys)
			{
				if (!ObservedBattleLogicKeys.Add(key))
					return;
			}

			var line = BuildProofLine(__0, __originalMethod, key);
			_logged++;
			Plugin.LogSource?.LogInfo("HoMM3 battle-result safe law probe: " + line + ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			if (_logged++ < LogCap)
				Plugin.LogSource?.LogWarning("HoMM3 battle-result safe law probe failed closed: " + ex.Message);
		}
	}

	private static string BuildProofLine(object battleLogic, MethodBase method, int key)
	{
		var transferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicTransferBattleFields) as TransferBattle;
		var startedTransferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicStartedTransferBattleFields) as TransferBattle;
		var resultInfo = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicBattleResultInfoFields) as BattleResultInfo;
		if (transferBattle?.sides == null || startedTransferBattle?.sides == null || resultInfo == null)
			return "status=missing-transfer-or-result method=" + FormatMethod(method) + " key=" + key;

		var winnerIndex = resultInfo.winnerIndex;
		var loserIndices = ResolveLoserIndices(resultInfo);
		var winner = SideAt(transferBattle, winnerIndex);
		var winnerStarted = SideAt(startedTransferBattle, winnerIndex);
		var winnerHero = HeroSid(winnerStarted) ?? HeroSid(winner);
		var winnerLaws = DescribeActiveKnownCustomLaws(winnerStarted) ?? DescribeActiveKnownCustomLaws(winner);

		var enemyLostValue = 0;
		var enemyLostStacks = 0;
		foreach (var loserIndex in loserIndices)
		{
			var started = SideAt(startedTransferBattle, loserIndex);
			var after = SideAt(transferBattle, loserIndex);
			enemyLostValue += SumLostSquadValue(started, after, out var lostStacks);
			enemyLostStacks += lostStacks;
		}

		var ownLostValue = SumLostSquadValue(winnerStarted, winner, out var ownLostStacks);
		return "status=observed"
		       + " method=" + FormatMethod(method)
		       + " key=" + key
		       + " winnerIndex=" + winnerIndex
		       + " winnerHero=" + (winnerHero ?? "null")
		       + " loserIndices=[" + string.Join(",", loserIndices) + "]"
		       + " enemyLostStacks=" + enemyLostStacks
		       + " enemyLostSquadValue=" + enemyLostValue
		       + " winnerLostStacks=" + ownLostStacks
		       + " winnerLostSquadValue=" + ownLostValue
		       + " winnerLaws=" + (winnerLaws ?? "none-or-unresolved");
	}

	private static TransferSide SideAt(TransferBattle battle, int index)
	{
		if (battle?.sides == null || index < 0 || index >= battle.sides.Length)
			return null;
		return battle.sides[index];
	}

	private static List<int> ResolveLoserIndices(BattleResultInfo resultInfo)
	{
		var result = new List<int>();
		if (resultInfo == null)
			return result;

		var losers = ReadMember(resultInfo, GameSymbols.BattleResultLaws.BattleResultLosersFields);
		foreach (var loser in EnumerateObjects(losers))
		{
			if (!TryReadIntMember(loser, GameSymbols.BattleResultLaws.BattleResultLoserIndexFields, out var loserIndex))
				continue;
			if (loserIndex >= 0)
				result.Add(loserIndex);
		}
		return result;
	}

	private static int SumLostSquadValue(TransferSide started, TransferSide after, out int lostStacksTotal)
	{
		lostStacksTotal = 0;
		if (started?.units == null)
			return 0;

		var value = 0;
		foreach (var beforeUnit in started.units)
		{
			if (beforeUnit == null || beforeUnit.stacks <= 0)
				continue;
			var afterUnit = FindMatchingAfterBattleUnit(after, beforeUnit);
			var afterStacks = afterUnit != null ? Math.Max(0, afterUnit.stacks) : 0;
			var lostStacks = Math.Max(0, beforeUnit.stacks - afterStacks);
			if (lostStacks <= 0)
				continue;

			lostStacksTotal += lostStacks;
			var config = ResolveUnitLogicConfig(beforeUnit);
			if (config != null)
				value += Math.Max(0, config.squadValue) * lostStacks;
		}
		return value;
	}

	private static TransferUnit FindMatchingAfterBattleUnit(TransferSide after, TransferUnit beforeUnit)
	{
		if (after?.units == null || beforeUnit == null)
			return null;
		foreach (var candidate in after.units)
		{
			if (candidate == null)
				continue;
			if (candidate.slotPos == beforeUnit.slotPos && string.Equals(NormalizeSid(candidate.configSid), NormalizeSid(beforeUnit.configSid), StringComparison.Ordinal))
				return candidate;
		}
		return null;
	}

	private static UnitLogicConfig ResolveUnitLogicConfig(TransferUnit transfer)
	{
		if (transfer == null)
			return null;
		var direct = ReadMember(transfer, GameSymbols.SkeletalNecromancy.TransferUnitLogicConfigGetter.NameHints) as UnitLogicConfig;
		if (direct != null)
			return direct;
		return ReadMember(transfer, GameSymbols.SkeletalNecromancy.TransferUnitLogicConfigFields) as UnitLogicConfig;
	}

	private static string HeroSid(TransferSide side)
	{
		return NormalizeSid(side?.hero?.configId);
	}

	private static string DescribeActiveKnownCustomLaws(object owner)
	{
		if (owner == null)
			return null;

		var parts = new List<string>(4);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(owner, lawIndex, out var state))
				continue;
			parts.Add("index=" + state.Index + ":rank=" + state.Rank + ":faction=" + state.FactionSid);
			if (parts.Count >= 4)
				break;
		}
		return parts.Count == 0 ? null : "[" + string.Join(";", parts) + "]";
	}

	private static int GetBattleLogicKey(object battleLogic)
	{
		var id = ReadIntMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicIdFields);
		if (id != 0)
			return id;
		return RuntimeHelpers.GetHashCode(battleLogic);
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

	private static IEnumerable<object> EnumerateObjects(object obj)
	{
		if (obj == null)
			yield break;
		if (obj is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
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
		var declaring = method.DeclaringType != null ? method.DeclaringType.FullName : "?";
		return declaring + "." + method.Name;
	}
}
