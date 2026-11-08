using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;

namespace OfflineUnlockMod;

/// <summary>
/// Shared post-battle squadValue economy runtime for custom faction reward laws.
///
/// June 19 status: unvalidated candidate gameplay implementation. This uses defeated enemy
/// squadValue as the exact post-battle economy signal for reward-law rows. It does not
/// inspect localized reward text, does not approximate adventure reward identity, and does
/// not add a second battle-result hook beyond this one exact apply-result prefix.
/// </summary>
internal static class Homm3SquadValueEconomyLawRuntime
{
	private const string NecropolisFactionSid = "homm3_necropolis";
	private const int SquadValuePerManaPerRank = 500;
	private const int SquadValuePerTrainingManaPerRank = 1000;
	private const int LogCap = 48;

	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static readonly HashSet<string> AppliedBattleLawKeys = new();
	private static readonly Dictionary<string, GoldFormula> RewardGoldFormulas = new(StringComparer.Ordinal)
	{
		["homm3_cove"] = new GoldFormula("Prize Shares", 18),
		["homm3_dungeon"] = new GoldFormula("Subjugated Mines", 25),
		["homm3_fortress"] = new GoldFormula("Marsh Rights", 30),
		["homm3_rampart"] = new GoldFormula("Preservation Tithe", 35),
		["homm3_tower"] = new GoldFormula("Transmutation Ledger", 30),
		["homm3_conflux"] = new GoldFormula("Elemental Market", 30),
		["homm3_inferno"] = new GoldFormula("Soul Contract", 25),
		["homm3_necropolis"] = new GoldFormula("Mortuary Accounting", 20),
		["homm3_stronghold"] = new GoldFormula("Spoils Ledger", 18),
	};

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		MethodInfo method;
		try
		{
			method = ResolveApplyBattleResultMethod();
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 squadValue economy law runtime failed closed during surface resolution: " + ex.Message);
			_registrationAuditStatus = "FAILED_CLOSED: surface resolution exception: " + ex.Message;
			return;
		}

		if (method == null)
		{
			log?.LogWarning("HoMM3 squadValue economy law runtime failed closed: exact battle-result apply surface not found.");
			_registrationAuditStatus = "FAILED_CLOSED: exact battle-result apply surface not found";
			return;
		}

		var prefix = AccessTools.Method(typeof(Homm3SquadValueEconomyLawRuntime), nameof(PrefixApplyBattleResult));
		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
		{
			log?.LogWarning("HoMM3 squadValue economy law runtime failed closed: incompatible prefix for " + FormatMethod(method) + ": " + reason);
			_registrationAuditStatus = "FAILED_CLOSED: incompatible prefix: " + reason;
			return;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.Last });
		_registered = true;
		_registrationAuditStatus = "REGISTERED_EXACT_PREFIX=" + FormatMethod(method);
		log?.LogInfo("HoMM3 squadValue economy law runtime registered on " + FormatMethod(method) + ". Reward law gold = rank * floor(enemyLostSquadValue / factionDivisor). Necropolis Corpse Wisdom mana = rank * floor(enemyLostSquadValue / " + SquadValuePerTrainingManaPerRank.ToString(System.Globalization.CultureInfo.InvariantCulture) + "), minimum 1 mana if any enemy squadValue was defeated. Necropolis Corpse Fuel mana = rank * floor(enemyLostSquadValue / " + SquadValuePerManaPerRank.ToString(System.Globalization.CultureInfo.InvariantCulture) + "), minimum 1 mana if any enemy squadValue was defeated.");
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
				if ((ps.Length == 1 || ps.Length == 2) && ps[0].ParameterType == logicType && (ps.Length == 1 || ps[1].ParameterType == typeof(bool)))
					return method;
			}
		}

		return null;
	}

	private static void PrefixApplyBattleResult(object __0, MethodBase __originalMethod)
	{
		try
		{
			if (__0 == null)
				return;
			if (ReadBoolMember(__0, GameSymbols.BattleResultLaws.BattleLogicAlreadyAppliedFields) == true)
				return;

			var key = GetBattleLogicKey(__0);
			TryApplySquadValueLaws(__0, __originalMethod, key);
		}
		catch (Exception ex)
		{
			LogLimited("failed closed: " + ex.Message);
		}
	}

	private static void TryApplySquadValueLaws(object battleLogic, MethodBase method, int key)
	{
		var transferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicTransferBattleFields) as TransferBattle;
		var startedTransferBattle = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicStartedTransferBattleFields) as TransferBattle;
		var resultInfo = ReadMember(battleLogic, GameSymbols.BattleResultLaws.BattleLogicBattleResultInfoFields) as BattleResultInfo;
		if (transferBattle?.sides == null || startedTransferBattle?.sides == null || resultInfo == null)
		{
			LogLimited("skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " method=" + FormatMethod(method) + " reason=missing-transfer-or-result");
			return;
		}

		var winnerIndex = resultInfo.winnerIndex;
		var winner = SideAt(transferBattle, winnerIndex);
		var winnerStarted = SideAt(startedTransferBattle, winnerIndex);
		var lawOwner = winnerStarted ?? winner;
		var dataHero = ReadDataHero(lawOwner) ?? ReadDataHero(winner);

		var enemyLostValue = 0;
		var enemyLostStacks = 0;
		foreach (var loserIndex in ResolveLoserIndices(resultInfo))
		{
			var started = SideAt(startedTransferBattle, loserIndex);
			var after = SideAt(transferBattle, loserIndex);
			enemyLostValue += SumLostSquadValue(started, after, out var lostStacks);
			enemyLostStacks += lostStacks;
		}
		if (enemyLostValue <= 0)
		{
			LogLimited("skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " winnerIndex=" + winnerIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + " reason=no-enemy-squadvalue-lost");
			return;
		}

		TryApplyRewardLawGold(lawOwner, key, winnerIndex, enemyLostValue, enemyLostStacks);
		TryApplyNecropolisCorpseWisdomMana(lawOwner, dataHero, key, winnerIndex, enemyLostValue, enemyLostStacks);
		TryApplyNecropolisCorpseFuelMana(lawOwner, dataHero, key, winnerIndex, enemyLostValue, enemyLostStacks);
	}

	private static void TryApplyRewardLawGold(object lawOwner, int key, int winnerIndex, int enemyLostValue, int enemyLostStacks)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "reward.gold-economy",
			    Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			    out var context,
			    out var guardFailReason))
		{
			LogLimited("reward gold skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " winnerIndex=" + winnerIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + " reason=" + guardFailReason);
			return;
		}
		if (!RewardGoldFormulas.TryGetValue(context.Law.FactionSid, out var formula))
		{
			LogLimited("reward gold failed closed key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=no-formula-for-faction-" + (context.Law.FactionSid ?? "null"));
			return;
		}
		if (!TryMarkBattleLawApplied(key, context.Law.Index, out var appliedFailReason))
		{
			LogLimited(formula.LawName + " skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=" + appliedFailReason);
			return;
		}

		var rank = Math.Max(1, context.Law.Rank);
		var baseGold = enemyLostValue / formula.SquadValuePerGoldPerRank;
		if (baseGold <= 0)
			baseGold = 50;
		var goldGrant = SafeMultiply(baseGold, rank);
		if (goldGrant <= 0)
			return;

		if (!Homm3CustomRewardEconomyLawRuntime.TryAddGoldEconomyGrantFromActiveLawSide(lawOwner, goldGrant, out var grantFailReason))
		{
			LogLimited(formula.LawName + " failed closed key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=" + grantFailReason);
			return;
		}
		LogLimited(formula.LawName + " applied key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " law=" + context.Law.LawSid
		           + " faction=" + context.Law.FactionSid
		           + " rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostStacks=" + enemyLostStacks.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostSquadValue=" + enemyLostValue.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " divisor=" + formula.SquadValuePerGoldPerRank.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " goldGranted=" + goldGrant.ToString(System.Globalization.CultureInfo.InvariantCulture));
	}

	private static void TryApplyNecropolisCorpseWisdomMana(object lawOwner, Hero dataHero, int key, int winnerIndex, int enemyLostValue, int enemyLostStacks)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var context,
			    out var guardFailReason))
		{
			LogLimited("Corpse Wisdom skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " winnerIndex=" + winnerIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + " reason=" + guardFailReason);
			return;
		}
		if (!string.Equals(context.Law.FactionSid, NecropolisFactionSid, StringComparison.Ordinal))
			return;
		if (!TryMarkBattleLawApplied(key, context.Law.Index, out var appliedFailReason))
		{
			LogLimited("Corpse Wisdom skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=" + appliedFailReason);
			return;
		}
		if (dataHero == null)
		{
			LogLimited("Corpse Wisdom skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=no-data-hero");
			return;
		}

		var baseMana = enemyLostValue / SquadValuePerTrainingManaPerRank;
		if (baseMana <= 0)
			baseMana = 1;
		var rank = Math.Max(1, context.Law.Rank);
		var manaRestore = SafeMultiply(baseMana, rank);
		if (manaRestore <= 0)
			return;

		var before = dataHero.mana;
		dataHero.mana = before > int.MaxValue - manaRestore ? int.MaxValue : before + manaRestore;
		LogLimited("Corpse Wisdom applied key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " law=" + context.Law.LawSid
		           + " rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostStacks=" + enemyLostStacks.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostSquadValue=" + enemyLostValue.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaBefore=" + before.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaRestored=" + manaRestore.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaAfter=" + dataHero.mana.ToString(System.Globalization.CultureInfo.InvariantCulture));
	}

	private static void TryApplyNecropolisCorpseFuelMana(object lawOwner, Hero dataHero, int key, int winnerIndex, int enemyLostValue, int enemyLostStacks)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var context,
			    out var guardFailReason))
		{
			LogLimited("Corpse Fuel skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " winnerIndex=" + winnerIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + " reason=" + guardFailReason);
			return;
		}
		if (!string.Equals(context.Law.FactionSid, NecropolisFactionSid, StringComparison.Ordinal))
			return;
		if (!TryMarkBattleLawApplied(key, context.Law.Index, out var appliedFailReason))
		{
			LogLimited("Corpse Fuel skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=" + appliedFailReason);
			return;
		}
		if (dataHero == null)
		{
			LogLimited("Corpse Fuel skipped key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture) + " law=" + context.Law.LawSid + " reason=no-data-hero");
			return;
		}

		var baseMana = enemyLostValue / SquadValuePerManaPerRank;
		if (baseMana <= 0)
			baseMana = 1;
		var rank = Math.Max(1, context.Law.Rank);
		var manaRestore = SafeMultiply(baseMana, rank);
		if (manaRestore <= 0)
			return;

		var before = dataHero.mana;
		dataHero.mana = before > int.MaxValue - manaRestore ? int.MaxValue : before + manaRestore;
		LogLimited("Corpse Fuel applied key=" + key.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " law=" + context.Law.LawSid
		           + " rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostStacks=" + enemyLostStacks.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " enemyLostSquadValue=" + enemyLostValue.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaBefore=" + before.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaRestored=" + manaRestore.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaAfter=" + dataHero.mana.ToString(System.Globalization.CultureInfo.InvariantCulture));
	}

	private readonly struct GoldFormula
	{
		internal readonly string LawName;
		internal readonly int SquadValuePerGoldPerRank;

		internal GoldFormula(string lawName, int squadValuePerGoldPerRank)
		{
			LawName = lawName;
			SquadValuePerGoldPerRank = squadValuePerGoldPerRank;
		}
	}

	private static bool TryMarkBattleLawApplied(int battleKey, int lawIndex, out string failReason)
	{
		var key = battleKey.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
		lock (AppliedBattleLawKeys)
		{
			if (!AppliedBattleLawKeys.Add(key))
			{
				failReason = "already-applied-for-battle-law";
				return false;
			}
		}
		failReason = null;
		return true;
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

	private static Hero ReadDataHero(TransferSide side)
	{
		if (side == null)
			return null;
		var logicHero = ReadMember(side, GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers);
		return ReadMember(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers) as Hero;
	}

	private static int SafeMultiply(int value, int multiplier)
	{
		if (value <= 0 || multiplier <= 0)
			return 0;
		if (value > int.MaxValue / multiplier)
			return int.MaxValue;
		return value * multiplier;
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
			type = GameMember.FindType("squadValueEconomy.type." + name, name);
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
			type = GameMember.FindType("squadValueEconomy.type." + name, name);
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
		var declaring = method.DeclaringType != null ? method.DeclaringType.FullName : "?";
		return declaring + "." + method.Name;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged++ < LogCap)
			Plugin.LogSource?.LogInfo("HoMM3 squadValue economy law runtime: " + message + ".");
	}
}




