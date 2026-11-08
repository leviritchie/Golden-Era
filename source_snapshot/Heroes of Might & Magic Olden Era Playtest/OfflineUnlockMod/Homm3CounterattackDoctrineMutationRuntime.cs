using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Candidate gameplay mutation for no-compromise Counterstroke Doctrine laws.
/// Source-prepared from eir.cglw -> eix.bdwy(int) Focus/Energy evidence and the
/// exact dxy ChangeAbilityEventArgs factory surface. Runtime proof is still
/// required; failures fail closed and do not approximate counterattacks from
/// damage timing, animations, or broad battle-event buses.
/// </summary>
internal static class Homm3CounterattackDoctrineMutationRuntime
{
	private const int LogCap = 80;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		// Register the exact native event hook independently of packet state. Gameplay mutation still fails closed
		// inside TryPlanAllowedCounterattackDoctrineEffectForChangeAbilityEvent, which resolves the active law/rank
		// through the central runtime guard before returning any effect plan.
		_registered = true;

		var patched = 0;
		try
		{
			patched = PatchAbilityRuntimeChangeEvents(harmony, log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 counterattack doctrine mutation runtime failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact dxy ChangeAbilityEventArgs factories patched";
			log?.LogWarning("HoMM3 counterattack doctrine mutation runtime found no exact change-event factories; counterattack law mutations remain disabled.");
			return;
		}

		_registrationAuditStatus = "STARTUP_HOOK_REGISTERED_RUNTIME_UNPROVEN: exact dxy change-event patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 counterattack doctrine mutation runtime registered " + patched + " exact change-event patch(es). Runtime proof still required.");
	}

	private static int PatchAbilityRuntimeChangeEvents(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsAbilityRuntime);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack doctrine mutation runtime: ability runtime type not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterattackDoctrineMutationRuntime), nameof(PostfixAbilityRuntimeChangeEvent));
		var patchedMethods = new HashSet<MethodInfo>();
		var patched = 0;
		foreach (var methodName in GameSymbols.CounterattackCorrelationLaws.AbilityRuntimeChangeEvent.NameHints)
		{
			var method = ResolveExactMethod(type, methodName, 0);
			if (method == null)
				continue;
			if (!IsAbilityRuntimeChangeEventSignature(method))
			{
				log?.LogWarning("HoMM3 counterattack doctrine mutation runtime: refusing change-event candidate with wrong signature " + FormatMethod(method) + ".");
				continue;
			}
			if (!patchedMethods.Add(method))
				continue;
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("HoMM3 counterattack doctrine mutation runtime: refusing incompatible patch for " + FormatMethod(method) + ": " + reason);
				continue;
			}
			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}
		return patched;
	}

	private static void PostfixAbilityRuntimeChangeEvent(object __result)
	{
		try
		{
			if (!Homm3CustomCounterattackLawRuntime.TryPlanAllowedCounterattackDoctrineEffectForChangeAbilityEvent(
				    __result,
				    out var observation,
				    out var profile,
				    out var lawOwner,
				    out var context,
				    out var plan,
				    out var failReason))
			{
				LogLimited("HoMM3 counterattack doctrine mutation skipped: " + failReason);
				return;
			}

			if (string.Equals(plan.EffectKey, "cove.focus.on-counterattack", StringComparison.Ordinal) && plan.FocusDelta > 0)
			{
				if (!Homm3FocusNativeAdapter.TryGrantFocusToSide(lawOwner, plan.FocusDelta, out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation applied Focus: context={" + context + "} observation={" + observation + "} profile={" + profile + "} plan={" + plan + "}.");
				return;
			}

			if (string.Equals(plan.EffectKey, "conflux.extra-magic-damage-counterattack", StringComparison.Ordinal))
			{
				var percent = Math.Max(10, context.Law.Rank * 10);
				if (!Homm3BattleLocalLawState.TryArmConfluxBacklash(
					    observation.Counterattacker,
					    percent,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation armed Conflux Elemental Backlash battle-local damage: context={" + context + "} observation={" + observation + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}. Separate Magic Arrow damage surface is not used in this candidate.");
				return;
			}

			if (string.Equals(plan.EffectKey, "necropolis.counterattack-drain-restore", StringComparison.Ordinal) && plan.DrainPercent > 0)
			{
				if (!Homm3BattleLocalLawState.TryArmNecropolisDeathGrip(
					    observation.Counterattacker,
					    plan.DrainPercent,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation armed Necropolis Death Grip battle-local drain damage: context={" + context + "} observation={" + observation + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}. HP restore surface remains unproven and is not mutated.");
				return;
			}
			if (string.Equals(plan.EffectKey, "stronghold.stacking-damage-buff-on-counterattack", StringComparison.Ordinal) && plan.StackingDamagePercent > 0)
			{
				if (!Homm3BattleLocalLawState.TryAddStrongholdBloodFeudDamagePercent(
					    observation.Counterattacker,
					    plan.StackingDamagePercent,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation applied Blood Feud battle-local state: context={" + context + "} observation={" + observation + "} profile={" + profile + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}.");
				return;
			}


			
			if (string.Equals(plan.EffectKey, "fortress.attack-debuff-on-counterattack", StringComparison.Ordinal) && plan.AttackDebuff < 0)
			{
				var reductionPercent = Math.Min(50, Math.Max(5, Math.Abs(plan.AttackDebuff) * 10));
				if (!Homm3BattleLocalLawState.TryArmFortressThornedHides(
					    observation.Counterattacker,
					    reductionPercent,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation armed Fortress Thorned Hides battle-local weakness: context={" + context + "} observation={" + observation + "} profile={" + profile + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}.");
				return;
			}if (string.Equals(plan.EffectKey, "dungeon.damage-vs-smaller-stack", StringComparison.Ordinal) && plan.DamagePercentBonus > 0)
			{
				if (!Homm3BattleLocalLawState.TryArmDungeonOutnumber(
					    observation.Counterattacker,
					    plan.DamagePercentBonus,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation armed Dungeon Outnumber battle-local one-shot damage: context={" + context + "} observation={" + observation + "} profile={" + profile + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}.");
				return;
			}			if (string.Equals(plan.EffectKey, "rampart.avenger-marked-counterattack-damage", StringComparison.Ordinal) && plan.DamagePercentBonus > 0)
			{
				if (!Homm3BattleLocalLawState.TryArmRampartAvengerReprisalForLawOwner(
					    lawOwner,
					    observation.Counterattacker,
					    plan.DamagePercentBonus,
					    out var oldPercent,
					    out var newPercent,
					    out failReason))
				{
					LogLimited("HoMM3 counterattack doctrine mutation failed closed for " + plan.EffectKey + ": " + failReason);
					return;
				}

				LogLimited("HoMM3 counterattack doctrine mutation armed Rampart Avenger's Reprisal law-owner one-shot damage: context={" + context + "} observation={" + observation + "} profile={" + profile + "} oldPercent=" + oldPercent + " newPercent=" + newPercent + " plan={" + plan + "}.");
				return;
			}

			LogLimited("HoMM3 counterattack doctrine mutation has no implemented mutator for effect " + plan.EffectKey + ".");
		}
		catch (Exception ex)
		{
			LogLimited("HoMM3 counterattack doctrine mutation failed closed: " + ex.Message);
		}
	}

	private static MethodInfo ResolveExactMethod(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		foreach (var method in AccessTools.GetDeclaredMethods(type))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static bool IsAbilityRuntimeChangeEventSignature(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(ChangeAbilityEventArgs))
			return false;
		return method.GetParameters().Length == 0;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		Plugin.LogSource?.LogInfo(message);
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
