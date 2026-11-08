using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Data;

namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared June 19 from edited hard-law CSV. Applies packet-gated
/// battle-start status laws using exact native status add/query/event surfaces.
/// Runtime behavior is unvalidated until a Necropolis combat pilot proves that
/// native duration expiry yields Death March's round-3 net Speed increase.
/// </summary>
internal static class Homm3BattleStartStatusLawRuntime
{
	private const string NecropolisFactionSid = "homm3_necropolis";
	private const string FortressFactionSid = "homm3_fortress";
	private const string DeathMarchHandlerKey = "battle.melee-formation";
	private const string HasteStatusSid = "magic_haste_effect";
	private const string WebStatusSid = "magic_web_effect";
	private const string InitiativeDownStatusSid = "magic_ice_bolt_effect";
	private const int DeathMarchStatusLevel = 1;
	private const int DeathMarchStatusValue = 1;
	private const int DeathMarchHasteDuration = 10;
	private const int DeathMarchWebDuration = 2;
	private const int BogLineStatusDuration = 10;
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplications;
	private static int _loggedFailures;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var battleLogicType = ResolveRequiredTypeByHint(hexAssembly, GameSymbols.DraconicDominion.BattleLogicTypeHints, "homm3.battleStartStatus.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(hexAssembly, GameSymbols.DraconicDominion.TransferBattleTypeName, "homm3.battleStartStatus.transferBattle");
			var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.battleStartStatus.battleLogic.init",
				m => !m.IsStatic);

			PatchPostfix(harmony, battleLogicInitMethod, nameof(PostfixBattleLogicInit));
			_registered = true;
			_log?.LogInfo("HoMM3 Battle Start Status law runtime registered on " + FormatMethod(battleLogicInitMethod) + ". Gameplay is packet-gated and fails closed if unit owner, law/rank, unit family, or native status add surfaces are unresolved.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Battle Start Status law runtime not registered; exact startup surface missing: " + ex.Message);
		}
	}

	private static void PostfixBattleLogicInit(object __1)
	{
		try
		{
			ApplyDeathMarch();
			ApplyFortressBogLine();
		}
		catch (Exception ex)
		{
			LogLimited("battle init status mutation failed closed: " + ex.Message);
		}
	}

	private static void ApplyDeathMarch()
	{
		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		if (units.Count == 0)
		{
			LogLimited("Death March skipped: no battle-unit ownership snapshots were available at BattleLogic.Init postfix.");
			return;
		}

		var applied = 0;
		var skipped = 0;
		foreach (var snapshot in units)
		{
			if (snapshot.Unit == null)
			{
				skipped++;
				continue;
			}
			if (!snapshot.DataSideKnown || snapshot.DataSide == null)
			{
				skipped++;
				LogLimited("Death March skipped unitKey=" + snapshot.UnitKey + ": Data.Side owner unresolved.");
				continue;
			}
			if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(snapshot.DataSide, DeathMarchHandlerKey, Homm3CustomFactionLawRuntime.MeleeFormationIndex, out var context, out var failReason))
			{
				skipped++;
				LogLimited("Death March skipped unitKey=" + snapshot.UnitKey + ": " + failReason);
				continue;
			}
			if (!string.Equals(context.Law.FactionSid, NecropolisFactionSid, StringComparison.Ordinal))
			{
				skipped++;
				continue;
			}
			if (!Homm3UnitLawClassifier.TryRequireFamilyFact(snapshot.Unit, Homm3UnitLawClassifier.FamilyFact.Undead, out var classification, out failReason))
			{
				skipped++;
				LogLimited("Death March skipped unitKey=" + snapshot.UnitKey + ": undead classifier rejected unit; reason=" + failReason + " evidence=" + Homm3UnitLawClassifier.DescribeEvidence(snapshot.Unit));
				continue;
			}

			if (!TryApplyStatus(snapshot.Unit, HasteStatusSid, DeathMarchHasteDuration, out failReason))
			{
				skipped++;
				LogLimited("Death March failed closed adding Haste to unitKey=" + snapshot.UnitKey + " sid='" + classification.Sid + "': " + failReason);
				continue;
			}
			if (!TryApplyStatus(snapshot.Unit, WebStatusSid, DeathMarchWebDuration, out failReason))
			{
				skipped++;
				LogLimited("Death March failed closed adding Web offset to unitKey=" + snapshot.UnitKey + " sid='" + classification.Sid + "': " + failReason);
				continue;
			}

			applied++;
			if (_loggedApplications++ < 16)
				_log?.LogInfo("HoMM3 Necropolis Death March applied native status pair to unitKey=" + snapshot.UnitKey + " sid='" + classification.Sid + "' context={" + context + "}: Haste +1 Speed duration " + DeathMarchHasteDuration + ", Web -1 Speed duration " + DeathMarchWebDuration + ". Expected net +1 Speed after native duration expiry reaches round 3; runtime proof pending.");
		}

		if (applied == 0)
			LogLimited("Death March applied to zero units; skipped=" + skipped + ". This is fail-closed, not a fallback.");
	}


	private static void ApplyFortressBogLine()
	{
		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		if (units.Count == 0)
		{
			LogLimited("Bog Line skipped: no battle-unit ownership snapshots were available at BattleLogic.Init postfix.");
			return;
		}

		var applied = 0;
		var skipped = 0;
		foreach (var snapshot in units)
		{
			if (snapshot.Unit == null)
			{
				skipped++;
				continue;
			}
			if (!snapshot.DataSideKnown || snapshot.DataSide == null)
			{
				skipped++;
				LogLimited("Bog Line skipped unitKey=" + snapshot.UnitKey + ": Data.Side owner unresolved.");
				continue;
			}
			if (!Homm3CustomFactionLawRuntime.TryResolveAllowedActiveKnownCustomLawForRegisteredFactionExcludingDataSide(
				    FortressFactionSid,
				    Homm3CustomFactionLawRuntime.MeleeFormationIndex,
				    snapshot.DataSide,
				    out var state,
				    out var fortressDataSide,
				    out var failReason))
			{
				skipped++;
				LogLimited("Bog Line skipped unitKey=" + snapshot.UnitKey + ": " + failReason);
				continue;
			}
			if (!TryApplyStatus(snapshot.Unit, InitiativeDownStatusSid, BogLineStatusDuration, out failReason))
			{
				skipped++;
				LogLimited("Bog Line failed closed adding initiative-down status to enemy unitKey=" + snapshot.UnitKey + ": " + failReason);
				continue;
			}
			applied++;
			if (_loggedApplications++ < 16)
				_log?.LogInfo("HoMM3 Fortress Bog Line applied native initiative-down status to enemy unitKey=" + snapshot.UnitKey + " opposingLaw=" + state.LawSid + " rank=" + state.Rank.ToString(System.Globalization.CultureInfo.InvariantCulture) + " status=" + InitiativeDownStatusSid + " duration=" + BogLineStatusDuration.ToString(System.Globalization.CultureInfo.InvariantCulture) + ". This is the edited CSV substitute and does not claim native-terrain detection; runtime proof pending.");
		}

		if (applied == 0)
			LogLimited("Bog Line applied to zero enemy units; skipped=" + skipped + ". This is fail-closed, not a fallback.");
	}

	private static bool TryApplyStatus(object unit, string statusSid, int duration, out string failReason)
	{
		if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, statusSid, unit, DeathMarchStatusLevel, duration, DeathMarchStatusValue, true, out _, out failReason))
			return false;
		failReason = null;
		return true;
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

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = AccessTools.Method(typeof(Homm3BattleStartStatusLawRuntime), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static void LogLimited(string message)
	{
		if (_loggedFailures++ < 32)
			_log?.LogWarning("HoMM3 Battle Start Status law runtime: " + message);
	}
}
