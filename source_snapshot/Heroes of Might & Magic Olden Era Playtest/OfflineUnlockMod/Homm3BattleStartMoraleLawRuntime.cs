using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Data;

namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared June 19 from edited hard-law CSV. Applies Dungeon Terror Exploitation
/// by temporarily reducing opposing TransferHero morale before native BattleLogic.Init
/// builds battle state, then restoring the transfer data immediately after Init.
/// Runtime behavior is unvalidated until a Dungeon combat pilot proves visible morale odds.
/// </summary>
internal static class Homm3BattleStartMoraleLawRuntime
{
	private const string DungeonFactionSid = "homm3_dungeon";
	private const int DungeonEnemyMoralePenalty = 1;
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplications;
	private static int _loggedSkips;

	private sealed class BattleInitState
	{
		internal readonly List<HeroStatSnapshot> Snapshots = new();
	}

	private sealed class HeroStatSnapshot
	{
		internal HeroStat Stat;
		internal int OriginalMorale;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var battleLogicType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.DraconicDominion.BattleLogicTypeHints,
				"homm3.battleStartMorale.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.battleStartMorale.transferBattle");
			var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.battleStartMorale.battleLogic.init",
				m => !m.IsStatic);

			PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			PatchFinalizer(harmony, battleLogicInitMethod, nameof(FinalizerBattleLogicInit));
			_registered = true;
			_log?.LogInfo("HoMM3 Battle Start Morale law runtime registered on " + FormatMethod(battleLogicInitMethod) + ". Gameplay is packet-gated and fails closed if active law/rank or transfer hero stats are unresolved.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Battle Start Morale law runtime not registered; exact startup surface missing: " + ex.Message);
		}
	}

	private static void PrefixBattleLogicInit(object __1, ref BattleInitState __state)
	{
		__state = null;
		try
		{
			__state = ApplyBattleStartMorale(__1);
		}
		catch (Exception ex)
		{
			LogLimited("battle init mutation failed closed: " + ex.Message);
		}
	}

	private static Exception FinalizerBattleLogicInit(Exception __exception, BattleInitState __state)
	{
		RestoreSnapshots(__state);
		return __exception;
	}

	private static BattleInitState ApplyBattleStartMorale(object transferBattle)
	{
		if (transferBattle == null)
			return null;
		var sidesValue = ReadMember(transferBattle, GameSymbols.DraconicDominion.TransferBattleSidesMembers);
		var transferSides = EnumerateObjects(sidesValue).Where(side => side != null).ToList();
		if (transferSides.Count < 2)
			return null;

		var state = new BattleInitState();
		foreach (var lawSide in transferSides)
		{
			if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
				    lawSide,
				    "morale.package",
				    Homm3CustomFactionLawRuntime.MoraleFlatIndex,
				    out var context,
				    out var failReason))
			{
				LogLimited("Dungeon Terror Exploitation skipped side: " + failReason);
				continue;
			}
			if (!string.Equals(context.Law.FactionSid, DungeonFactionSid, StringComparison.Ordinal))
				continue;

			var enemyChanged = 0;
			foreach (var enemySide in ResolveEnemyTransferSides(lawSide, transferSides))
			{
				foreach (var heroStat in ResolveTransferSideHeroStats(enemySide))
				{
					RecordSnapshot(state, heroStat);
					heroStat.moral -= DungeonEnemyMoralePenalty;
					enemyChanged++;
				}
			}

			if (enemyChanged == 0)
			{
				LogLimited("Dungeon Terror Exploitation failed closed for " + context + ": enemy transfer hero morale stat missing.");
				continue;
			}

			if (_loggedApplications++ < 12)
				_log?.LogInfo("HoMM3 Dungeon Terror Exploitation applied -" + DungeonEnemyMoralePenalty + " enemy Morale before battle init: context={" + context + "} enemyHeroStats=" + enemyChanged + ". Restored after Init; expected native battle state should capture the temporary transfer morale.");
		}

		return state.Snapshots.Count == 0 ? null : state;
	}

	private static IEnumerable<object> ResolveEnemyTransferSides(object ownTransferSide, IReadOnlyList<object> allTransferSides)
	{
		foreach (var candidate in allTransferSides ?? Array.Empty<object>())
		{
			if (candidate == null || ReferenceEquals(candidate, ownTransferSide))
				continue;
			yield return candidate;
		}
	}

	private static IEnumerable<HeroStat> ResolveTransferSideHeroStats(object transferSide)
	{
		var seen = new HashSet<HeroStat>();
		var transferHero = (transferSide as TransferSide)?.hero;
		if (transferHero == null)
			yield break;
		if (transferHero.heroStat != null && seen.Add(transferHero.heroStat))
			yield return transferHero.heroStat;
		if (transferHero.heroStatUnclamped != null && seen.Add(transferHero.heroStatUnclamped))
			yield return transferHero.heroStatUnclamped;
	}

	private static void RecordSnapshot(BattleInitState state, HeroStat heroStat)
	{
		if (state == null || heroStat == null)
			return;
		if (state.Snapshots.Any(snapshot => ReferenceEquals(snapshot.Stat, heroStat)))
			return;
		state.Snapshots.Add(new HeroStatSnapshot { Stat = heroStat, OriginalMorale = heroStat.moral });
	}

	private static void RestoreSnapshots(BattleInitState state)
	{
		if (state == null)
			return;
		foreach (var snapshot in state.Snapshots)
		{
			if (snapshot?.Stat == null)
				continue;
			snapshot.Stat.moral = snapshot.OriginalMorale;
		}
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new MissingMemberException(symbolId + " type not found: " + fullName);
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new MissingMemberException(symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(Type type, Type returnType, Type[] parameterTypes, string methodName, string symbolId, Func<MethodInfo, bool> predicate)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (method.ReturnType != returnType)
				continue;
			var parameters = method.GetParameters();
			if (parameterTypes != null)
			{
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameterTypes.Length; i++)
				{
					if (parameters[i].ParameterType != parameterTypes[i])
					{
						exact = false;
						break;
					}
				}
				if (!exact)
					continue;
			}
			if (predicate != null && !predicate(method))
				continue;
			return method;
		}
		throw new MissingMethodException(symbolId + " exact method not found on " + (type?.FullName ?? "null"));
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = AccessTools.Method(typeof(Homm3BattleStartMoraleLawRuntime), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static void PatchFinalizer(Harmony harmony, MethodInfo target, string finalizerName)
	{
		var finalizer = AccessTools.Method(typeof(Homm3BattleStartMoraleLawRuntime), finalizerName);
		if (!GameMember.IsHarmonyPatchCompatible(target, finalizer, out var reason))
			throw new MissingMethodException("finalizer incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, finalizer: new HarmonyMethod(finalizer));
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;
		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				if (item != null)
					yield return item;
		}
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
				return property.GetValue(obj);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(obj);
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null)
				return method.Invoke(obj, null);
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ < 24)
			_log?.LogWarning("HoMM3 Battle Start Morale law runtime: " + message);
	}
}
