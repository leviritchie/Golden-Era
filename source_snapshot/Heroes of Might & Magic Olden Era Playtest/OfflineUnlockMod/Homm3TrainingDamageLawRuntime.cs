using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Data;

namespace OfflineUnlockMod;

/// <summary>
/// Exact committed-damage executor for custom training-damage law rows.
/// Source-prepared on June 19 after the direct Unit damage method and caster
/// law-owner route were narrowed. This class intentionally binds only the
/// current exact Unit damage method from <see cref="GameSymbols"/> and remains
/// inert while the committed-damage packet gate is closed.
/// </summary>
internal static class Homm3TrainingDamageLawRuntime
{
	internal const string PilotFlag = "homm3_training_damage_runtime_pilot.flag";
	private const int LogCap = 32;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private const int BurningAshPercentPerPoint = 5;
	private const int BurningAshMaxPercent = 30;
	private const int BurningAshMaxPoints = BurningAshMaxPercent / BurningAshPercentPerPoint;
	// Native-identity keyed: the receiver proxy at store and read differ. Cleared at battle cleanup
	// (Homm3BattleLocalLawState.ClearBattleSideIndexedState) because native pointers are reused.
	private static readonly Homm3NativeKeyedTable<BurningAshState> BurningAshByTarget = new("Cove Burning Ash target state");
	private static readonly object BurningAshLock = new();

	internal static int ClearBurningAshForBattle()
	{
		return BurningAshByTarget.Clear();
	}

	private sealed class BurningAshState
	{
		internal int Points;
	}

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;

		if (!Homm3CustomLawPacketGate.IsGameplayAllowed(Homm3CustomLawPacketGate.CommittedDamage, out var packetFail)
		    && !Homm3DiagnosticFlags.IsEnabled(PilotFlag))
		{
			_registrationAuditStatus = "BLOCKED_BY_PACKET_GATE: " + packetFail;
			log?.LogInfo("HoMM3 training-damage runtime not registered: " + packetFail);
			return;
		}
		if (Homm3DiagnosticFlags.IsEnabled(PilotFlag))
			log?.LogWarning("HoMM3 training-damage runtime pilot flag is enabled; committed-damage packet proof remains unpromoted.");

		var unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
		if (unitType == null)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact battle Unit type not found";
			log?.LogWarning("HoMM3 training-damage runtime failed closed: exact battle Unit type not found.");
			return;
		}

		var patched = 0;
		foreach (var methodName in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints)
			patched += PatchExactDamageMethod(harmony, log, unitType, methodName);

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact Unit damage method was not patched";
			log?.LogWarning("HoMM3 training-damage runtime failed closed: exact Unit damage method was not patched.");
			return;
		}

		_registrationAuditStatus = "REGISTERED_EXACT_PREFIX_PATCHES=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 training-damage runtime registered " + patched + " exact committed-damage prefix patch(es).");
	}

	private static int PatchExactDamageMethod(Harmony harmony, ManualLogSource log, Type unitType, string methodName)
	{
		var method = ResolveExactVoidMethod(unitType, methodName, 8);
		if (method == null)
		{
			log?.LogWarning("HoMM3 training-damage runtime: exact " + unitType.FullName + "." + methodName + "(8 args) not found.");
			return 0;
		}

		var prefix = AccessTools.Method(typeof(Homm3TrainingDamageLawRuntime), nameof(PrefixApplyTrainingDamage));
		if (prefix == null)
		{
			log?.LogWarning("HoMM3 training-damage runtime: prefix method not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
		{
			log?.LogWarning("HoMM3 training-damage runtime: refusing incompatible prefix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.First });
		return 1;
	}

	private static void PrefixApplyTrainingDamage(object __instance, MethodBase __originalMethod, object[] __args)
	{
		try
		{
			if (__args == null || __args.Length != 8 || __args[3] is not int currentDamage)
			{
				LogLimited("HoMM3 training-damage runtime failed closed: damage argument shape is not the exact 8-argument committed-damage shape.");
				return;
			}

			var mutated = false;
			if (TryApplyExistingFortressThornedHidesWeakness(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyExistingCoveBurningAsh(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyExistingStrongholdBloodFeud(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyExistingRampartAvengerReprisal(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyExistingDungeonOutnumber(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyCandidateSurfaceOneShotDamage(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyHardLawCsvDamageCandidates(__instance, __args, currentDamage, __originalMethod, out currentDamage))
				mutated = true;
			if (TryApplyExistingFortressThornedHidesCounterattackMark(__instance, __args, __originalMethod))
				mutated = true;
			if (TryPlanAllowedFortressDebuffedAttackerDamageReduction(
				    __instance,
				    __args,
				    out var fortressDamageInfo,
				    out var fortressContext,
				    out var fortressPlan,
				    out var fortressBuffInfo,
				    out var fortressFailReason))
			{
				if (!ApplyPlannedDamageDelta(__args, currentDamage, fortressDamageInfo.Damage, fortressPlan, fortressContext, __originalMethod, fortressBuffInfo.ToString(), null, out currentDamage, out var applyFailReason))
				{
					LogLimited("HoMM3 training-damage runtime failed closed: " + applyFailReason);
					return;
				}
				mutated = true;
			}
			else
			{
				LogLimited("HoMM3 training-damage runtime Fortress receiver reduction skipped: " + fortressFailReason);
			}

			if (!Homm3CustomBattleEventLawRuntime.TryPlanAllowedTrainingDamageApplyEffect(
				    __instance,
				    __args,
				    out var damageInfo,
				    out var profile,
				    out var context,
				    out var plan,
				    out var failReason))
			{
				if (!mutated)
					LogLimited("HoMM3 training-damage runtime skipped: " + failReason);
				return;
			}

			if (TryApplyCoveBurningAshMark(damageInfo, profile, context, plan, __originalMethod, out var burningAshFailReason))
				return;
			if (string.Equals(profile.EffectKey, "cove.gunpowder-defense-debuff", StringComparison.Ordinal))
			{
				LogLimited("HoMM3 training-damage runtime Burning Ash skipped: " + burningAshFailReason);
				return;
			}

			if (string.Equals(profile.EffectKey, "rampart.avenger-vulnerability", StringComparison.Ordinal)
			    && !TryRequireRampartAvengerGameplayMark(damageInfo.Receiver, out _, out var avengerMarkFailReason))
			{
				LogLimited("HoMM3 training-damage runtime Avenger potency skipped: " + avengerMarkFailReason);
				return;
			}

			if (!TryRequireSupportedDirectDamageScalarProfile(profile, plan, damageInfo, out var predicateDetail, out var plannedDamageOverride, out var unsupportedReason))
			{
				LogLimited("HoMM3 training-damage runtime skipped: " + unsupportedReason);
				return;
			}
			if (!ApplyPlannedDamageDelta(__args, currentDamage, damageInfo.Damage, plan, context, __originalMethod, predicateDetail, plannedDamageOverride, out _, out var scalarApplyFailReason))
			{
				LogLimited("HoMM3 training-damage runtime failed closed: " + scalarApplyFailReason);
				return;
			}
			if (string.Equals(profile.EffectKey, "rampart.avenger-vulnerability", StringComparison.Ordinal)
			    && !TryStrengthenRampartAvengerPotency(damageInfo, profile, context, __originalMethod, out var potencyFailReason))
			{
				LogLimited("HoMM3 training-damage runtime Avenger potency strengthen skipped after damage: " + potencyFailReason);
			}
		}
		catch (OverflowException)
		{
			LogLimited("HoMM3 training-damage runtime failed closed: calculated damage overflow.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 training-damage runtime failed closed during prefix: " + ex.Message);
		}
	}

	private static bool TryApplyExistingCoveBurningAsh(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (receiverUnit == null || args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		BurningAshState state;
		lock (BurningAshLock)
		{
			if (!BurningAshByTarget.TryGetValue(receiverUnit, out state) || state == null || state.Points <= 0)
				return false;
		}
		var percent = Math.Min(BurningAshMaxPercent, state.Points * BurningAshPercentPerPoint);
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			return false;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied Cove Burning Ash custom damage: method="
		           + FormatMethod(originalMethod)
		           + " ashPoints=" + state.Points
		           + " percent=" + percent
		           + " oldDamage=" + currentDamage
		           + " delta=" + delta
		           + " newDamage=" + newDamage
		           + ".");
		return true;
	}

	private static bool TryApplyExistingStrongholdBloodFeud(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Blood Feud skipped: " + readFailReason);
			return false;
		}
		if (!Homm3BattleLocalLawState.TryGetStrongholdBloodFeudDamagePercent(damageInfo.Caster, out var percent, out var stateFailReason))
			return false;
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			return false;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied Stronghold Blood Feud custom damage: method="
		           + FormatMethod(originalMethod)
		           + " percent=" + percent
		           + " oldDamage=" + currentDamage
		           + " delta=" + delta
		           + " newDamage=" + newDamage
		           + "; custom battle-local state, no native buff/status mutation.");
		return true;
	}

	private static bool TryApplyExistingDungeonOutnumber(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Outnumber skipped: " + readFailReason);
			return false;
		}
		if (!Homm3BattleLocalLawState.TryConsumeDungeonOutnumber(damageInfo.Caster, out var percent, out var stateFailReason))
			return false;
		if (!TryReadBattleStackCount(damageInfo.Caster, out var attackerStacks, out var attackerStackFailReason))
		{
			LogLimited("HoMM3 training-damage runtime consumed Outnumber without damage bonus: attacker stack count failed: " + attackerStackFailReason);
			return false;
		}
		if (!TryReadBattleStackCount(damageInfo.Receiver, out var defenderStacks, out var defenderStackFailReason))
		{
			LogLimited("HoMM3 training-damage runtime consumed Outnumber without damage bonus: defender stack count failed: " + defenderStackFailReason);
			return false;
		}
		if (attackerStacks <= defenderStacks)
		{
			LogLimited("HoMM3 training-damage runtime consumed Outnumber without damage bonus: counterattacker stacks="
			           + attackerStacks
			           + " target stacks="
			           + defenderStacks
			           + "; target is not outnumbered.");
			return false;
		}
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			return false;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied Dungeon Outnumber custom counterattack damage: method="
		           + FormatMethod(originalMethod)
		           + " percent=" + percent
		           + " counterattackerStacks=" + attackerStacks
		           + " targetStacks=" + defenderStacks
		           + " oldDamage=" + currentDamage
		           + " delta=" + delta
		           + " newDamage=" + newDamage
		           + "; exact CounterAttack event armed one-shot state, stack comparison happens on committed damage.");
		return true;
	}
		private static bool TryApplyCandidateSurfaceOneShotDamage(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 candidate-surface damage runtime skipped: committed-damage read failed: " + readFailReason);
			return false;
		}
		if (damageInfo.Caster == null)
			return false;

		var mutated = false;
		if (Homm3BattleLocalLawState.TryConsumeBattleActionOneShotDamage(damageInfo.Caster, out var battleActionPercent, out _))
		{
			var delta = checked(currentDamage * battleActionPercent / 100);
			if (delta <= 0)
				delta = 1;
			newDamage = checked(currentDamage + delta);
			args[3] = newDamage;
			currentDamage = newDamage;
			mutated = true;
			LogLimited("HoMM3 candidate-surface damage runtime consumed battle-action one-shot damage: method="
			           + FormatMethod(originalMethod)
			           + " percent=" + battleActionPercent
			           + " delta=" + delta
			           + " newDamage=" + newDamage + ".");
		}
		if (Homm3BattleLocalLawState.TryConsumeMoraleOneShotDamage(damageInfo.Caster, out var moralePercent, out _))
		{
			var delta = checked(currentDamage * moralePercent / 100);
			if (delta <= 0)
				delta = 1;
			newDamage = checked(currentDamage + delta);
			args[3] = newDamage;
			mutated = true;
			LogLimited("HoMM3 candidate-surface damage runtime consumed morale one-shot damage: method="
			           + FormatMethod(originalMethod)
			           + " percent=" + moralePercent
			           + " delta=" + delta
			           + " newDamage=" + newDamage + ".");
		}
		return mutated;
	}
private static bool TryApplyHardLawCsvDamageCandidates(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (receiverUnit == null || args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 hard-law CSV damage runtime skipped: " + readFailReason);
			return false;
		}

		var mutated = false;
		if (TryApplyConfluxBacklashCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyNecropolisDeathGripCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyTowerSpellcastDamageCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyCoveGunpowderFocusCsvLaw(damageInfo, originalMethod))
		{
			mutated = true;
		}		if (TryApplyCoveMoraleDefenseCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}		if (TryApplyCoveCrewMateRangedProtectionCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyRampartAvengerRangedProtectionCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyDungeonDebuffedTargetRangedDamageCsvLaw(damageInfo, args, currentDamage, originalMethod, out currentDamage))
		{
			mutated = true;
		}
		if (TryApplyStrongholdBerserkerChargeHasteCsvLaw(damageInfo, originalMethod))
		{
			mutated = true;
		}
		if (TryArmStrongholdPostAttackDamageCsvLaw(damageInfo, originalMethod))
		{
			mutated = true;
		}
		newDamage = currentDamage;
		return mutated;
	}

	private static bool TryApplyConfluxBacklashCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleLocalLawState.TryConsumeConfluxBacklash(damageInfo.Caster, out var percent, out var failReason))
			return false;
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			delta = 1;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Conflux Elemental Backlash damage: percent=" + percent + " oldDamage=" + currentDamage + " delta=" + delta + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ". This is a battle-local damage hook, not a separate Magic Arrow projectile.");
		return true;
	}

	private static bool TryApplyNecropolisDeathGripCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleLocalLawState.TryConsumeNecropolisDeathGrip(damageInfo.Caster, out var percent, out var failReason))
			return false;
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			delta = 1;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Necropolis Death Grip drain damage: percent=" + percent + " oldDamage=" + currentDamage + " delta=" + delta + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ". HP restoration is not mutated because no restore surface is registered.");
		return true;
	}
	private static bool TryApplyTowerSpellcastDamageCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Caster,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var casterLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    casterLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Tower, StringComparison.Ordinal))
			return false;
		if (!Homm3BattleLocalLawState.TryGetTowerSpellcastDamagePercent(casterLawOwner, out var percent, out failReason))
			return false;
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			delta = 1;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Tower spellcast battle-local damage: context={" + context + "} percent=" + percent + " oldDamage=" + currentDamage + " delta=" + delta + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ". This is a damage scalar, not a native Attack/Defense buff.");
		return true;
	}
	private static bool TryApplyCoveGunpowderFocusCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		MethodBase originalMethod)
	{
		if (damageInfo.Caster == null || damageInfo.Damage <= 0)
			return false;
		if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
			    damageInfo.Caster,
			    Homm3UnitLawClassifier.FamilyFact.Gunpowder,
			    out var gunpowderClassification,
			    out var failReason))
			return false;

		var applied = false;
		if (TryGrantCoveGunpowderFocusForLaw(
			    damageInfo.Caster,
			    Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			    oncePerBattle: false,
			    "Storm Charts gunpowder Focus credit",
			    out var lowDetail,
			    out failReason))
		{
			applied = true;
			LogLimited("HoMM3 hard-law CSV runtime applied Cove Storm Charts Focus credit: " + lowDetail + " gunpowder={" + gunpowderClassification + "} method=" + FormatMethod(originalMethod) + ". This is a Focus grant on gunpowder damage, not a native Heroic Strike cooldown mutation.");
		}
		else
		{
			LogLimited("HoMM3 hard-law CSV runtime Cove Storm Charts Focus credit skipped: " + failReason);
		}

		if (TryGrantCoveGunpowderFocusForLaw(
			    damageInfo.Caster,
			    Homm3CustomFactionLawRuntime.RangedFormationIndex,
			    oncePerBattle: true,
			    "Gun Decks first gunpowder Focus credit",
			    out var rangedDetail,
			    out failReason))
		{
			applied = true;
			LogLimited("HoMM3 hard-law CSV runtime applied Cove Gun Decks first Focus credit: " + rangedDetail + " gunpowder={" + gunpowderClassification + "} method=" + FormatMethod(originalMethod) + ". This is a once-per-battle Focus grant on gunpowder damage, not a native Heroic Strike cost override.");
		}
		else
		{
			LogLimited("HoMM3 hard-law CSV runtime Cove Gun Decks Focus credit skipped: " + failReason);
		}

		return applied;
	}

	private static bool TryGrantCoveGunpowderFocusForLaw(
		object caster,
		int lawIndex,
		bool oncePerBattle,
		string label,
		out string detail,
		out string failReason)
	{
		detail = null;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(caster, lawIndex, out var lawOwner, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(lawOwner, lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex ? "spell.low" : "battle.ranged-formation", lawIndex, out var context, out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Cove, StringComparison.Ordinal))
		{
			failReason = label + " active law is not Cove: " + context.Law;
			return false;
		}
		if (oncePerBattle && !Homm3BattleLocalLawState.TryConsumeCoveFirstHeroicFocusGrant(lawOwner, out failReason))
			return false;
		var focusDelta = Math.Max(1, context.Law.Rank);
		if (!Homm3FocusNativeAdapter.TryGrantFocusToSide(lawOwner, focusDelta, out failReason))
			return false;
		detail = "label=" + label + " law=" + context.Law + " focusDelta=" + focusDelta;
		failReason = null;
		return true;
	}
	private static bool TryApplyCoveMoraleDefenseCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Receiver == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Receiver,
			    Homm3CustomFactionLawRuntime.MoraleFlatIndex,
			    out var receiverLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    receiverLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.MoraleFlatIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Cove, StringComparison.Ordinal))
			return false;
		if (!TryRequirePositiveUnitMoraleValue(damageInfo.Receiver, out var moraleValue, out var moraleDetail, out failReason))
			return false;
		var percent = Math.Min(60, Math.Max(1, moraleValue) * Math.Max(1, context.Law.Rank) * 5);
		var reduction = checked(currentDamage * percent / 100);
		if (reduction <= 0 && currentDamage > 1)
			reduction = 1;
		if (reduction <= 0)
			return false;
		newDamage = Math.Max(0, checked(currentDamage - reduction));
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Cove morale defense: context={" + context + "} " + moraleDetail + " percent=" + percent + " oldDamage=" + currentDamage + " reduction=" + reduction + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ".");
		return true;
	}


	private static bool TryApplyCoveCrewMateRangedProtectionCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || damageInfo.Receiver == null || currentDamage <= 0)
			return false;
		if (!TryRequireRangedDamageMechanic(damageInfo.FromMech, out var rangedDetail, out var failReason))
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(damageInfo.Receiver, Homm3CustomFactionLawRuntime.MeleeFormationIndex, out var receiverLawOwner, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(receiverLawOwner, "battle.melee-formation", Homm3CustomFactionLawRuntime.MeleeFormationIndex, out var context, out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Cove, StringComparison.Ordinal))
			return false;
		if (!TryFindAdjacentFriendlyCrewMate(damageInfo.Receiver, receiverLawOwner, out var crewDetail, out failReason))
		{
			LogLimited("HoMM3 Cove Boarding Parties skipped: " + failReason);
			return false;
		}

		const int percent = 30;
		var reduction = checked(currentDamage * percent / 100);
		if (reduction <= 0 && currentDamage > 1)
			reduction = 1;
		if (reduction <= 0)
			return false;
		newDamage = Math.Max(0, checked(currentDamage - reduction));
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Cove Boarding Parties ranged protection: context={" + context + "} " + rangedDetail + " " + crewDetail + " percent=" + percent + " oldDamage=" + currentDamage + " reduction=" + reduction + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ". This is law-gated damage reduction, not an unconditional copied aura.");
		return true;
	}

	private static bool TryRequireRangedDamageMechanic(object fromMech, out string detail, out string failReason)
	{
		detail = null;
		if (fromMech == null)
		{
			failReason = "ranged predicate requires non-null EMechType";
			return false;
		}
		var raw = fromMech.ToString();
		if (string.IsNullOrWhiteSpace(raw))
		{
			failReason = "ranged predicate EMechType string is empty";
			return false;
		}
		if (raw.IndexOf("shoot", StringComparison.OrdinalIgnoreCase) < 0 && raw.IndexOf("ranged", StringComparison.OrdinalIgnoreCase) < 0)
		{
			failReason = "ranged predicate rejected EMechType='" + raw + "'";
			return false;
		}
		detail = "rangedMech='" + raw + "'";
		failReason = null;
		return true;
	}

	private static bool TryFindAdjacentFriendlyCrewMate(object receiver, object receiverLawOwner, out string detail, out string failReason)
	{
		detail = null;
		if (!TryReadBattleObjectHex(receiver, out var receiverHex, out failReason))
		{
			failReason = "Crew Mate adjacency receiver hex failed: " + failReason;
			return false;
		}
		if (!TryReadHexCoordinates(receiverHex, out var receiverX, out var receiverZ, out failReason))
		{
			failReason = "Crew Mate adjacency receiver coordinates failed: " + failReason;
			return false;
		}
		if (!TryEnumerateBattleUnitsFromObject(receiver, out var units, out failReason))
		{
			failReason = "Crew Mate adjacency unit enumeration failed: " + failReason;
			return false;
		}

		var checkedUnits = 0;
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			if (unit == null || SameRuntimeObject(unit, receiver))
				continue;
			if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(unit, Homm3CustomFactionLawRuntime.MeleeFormationIndex, out var unitLawOwner, out _))
				continue;
			if (!SameLawOwnerSide(unitLawOwner, receiverLawOwner))
				continue;
			var classification = Homm3UnitLawClassifier.Classify(unit);
			if (!IsCrewMateLineSid(classification.Sid))
				continue;
			if (!TryReadBattleObjectHex(unit, out var unitHex, out _))
				continue;
			if (!TryReadHexCoordinates(unitHex, out var unitX, out var unitZ, out _))
				continue;
			checkedUnits++;
			var distance = HexDistance(receiverX, receiverZ, unitX, unitZ);
			if (distance == 1)
			{
				detail = "adjacentCrewMateSid='" + classification.Sid + "' receiverHex=(" + receiverX + "," + receiverZ + ") crewHex=(" + unitX + "," + unitZ + ") checkedCrewMateUnits=" + checkedUnits;
				failReason = null;
				return true;
			}
		}
		failReason = "no adjacent friendly Crew Mate-line unit found near receiverHex=(" + receiverX + "," + receiverZ + ") checkedCrewMateUnits=" + checkedUnits;
		return false;
	}

	private static bool IsCrewMateLineSid(string sid)
	{
		return string.Equals(sid, "h3_crew_mate", StringComparison.Ordinal)
		       || string.Equals(sid, "h3_crew_mate_upg", StringComparison.Ordinal)
		       || string.Equals(sid, "h3_crew_mate_upg_alt", StringComparison.Ordinal);
	}	private static bool TryApplyRampartAvengerRangedProtectionCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || damageInfo.Receiver == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Receiver,
			    Homm3CustomFactionLawRuntime.FormationIndex,
			    out var receiverLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    receiverLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.FormationIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Rampart, StringComparison.Ordinal))
			return false;
		if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
			    damageInfo.Receiver,
			    Homm3UnitLawClassifier.FamilyFact.Shooter,
			    out var shooterClassification,
			    out failReason))
			return false;
		if (!TryRequireRampartAvengerGameplayMark(damageInfo.Caster, out var markCount, out failReason))
			return false;
		var percent = context.Law.Rank >= 2 ? 30 : 20;
		var reduction = checked(currentDamage * percent / 100);
		if (reduction <= 0 && currentDamage > 1)
			reduction = 1;
		if (reduction <= 0)
			return false;
		newDamage = Math.Max(0, checked(currentDamage - reduction));
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Rampart Avenger ranged protection: context={" + context + "} markCount=" + markCount + " receiver=" + shooterClassification + " percent=" + percent + " oldDamage=" + currentDamage + " reduction=" + reduction + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ".");
		return true;
	}

	private static bool TryApplyDungeonDebuffedTargetRangedDamageCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (damageInfo.Caster == null || damageInfo.Receiver == null || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Caster,
			    Homm3CustomFactionLawRuntime.FormationIndex,
			    out var casterLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    casterLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.FormationIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Dungeon, StringComparison.Ordinal))
			return false;
		if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
			    damageInfo.Caster,
			    Homm3UnitLawClassifier.FamilyFact.Shooter,
			    out var shooterClassification,
			    out failReason))
			return false;
		if (!Homm3CustomBuffDebuffLawRuntime.TryRequireAllowedStatusTagsFromReceiver(
			    casterLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.FormationIndex,
			    damageInfo.Receiver,
			    new[] { "negative" },
			    out var buffInfo,
			    out _,
			    out failReason))
			return false;
		var percent = context.Law.Rank >= 2 ? 20 : 10;
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			return false;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 hard-law CSV runtime applied Dungeon debuffed-target ranged damage: context={" + context + "} caster=" + shooterClassification + " status={" + buffInfo + "} percent=" + percent + " oldDamage=" + currentDamage + " delta=" + delta + " newDamage=" + newDamage + " method=" + FormatMethod(originalMethod) + ".");
		return true;
	}

	private static bool TryApplyStrongholdBerserkerChargeHasteCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		MethodBase originalMethod)
	{
		if (damageInfo.Receiver == null || damageInfo.Damage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Receiver,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var receiverLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    receiverLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Stronghold, StringComparison.Ordinal))
			return false;
		const string hasteBuffSid = "magic_haste_effect_0";
		var duration = Math.Max(1, context.Law.Rank);
		if (!Homm3BuffDebuffNativeAdapter.TryDiagnosticAddBuffSidFromReceiver(
			    damageInfo.Receiver,
			    hasteBuffSid,
			    damageInfo.Receiver,
			    level: 1,
			    duration: duration,
			    value: 0,
			    refresh: true,
			    out var info,
			    out failReason))
		{
			LogLimited("HoMM3 hard-law CSV runtime Stronghold Berserker Charge Haste skipped: " + failReason);
			return false;
		}
		LogLimited("HoMM3 hard-law CSV runtime applied Stronghold Berserker Charge Haste: context={" + context + "} buffSid=" + hasteBuffSid + " duration=" + duration + " status={" + info + "} method=" + FormatMethod(originalMethod) + ". This uses native Haste buff application after committed damage; wounded-threshold and turn-order refresh remain runtime-unproven.");
		return true;
	}

	private static bool TryArmStrongholdPostAttackDamageCsvLaw(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		MethodBase originalMethod)
	{
		if (damageInfo.Caster == null || damageInfo.Damage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Caster,
			    Homm3CustomFactionLawRuntime.CounterattackIndex,
			    out var casterLawOwner,
			    out var failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    casterLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.CounterattackIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Stronghold, StringComparison.Ordinal))
			return false;
		var percentDelta = context.Law.Rank >= 2 ? 10 : 5;
		if (!Homm3BattleLocalLawState.TryAddStrongholdBloodFeudDamagePercent(
			    damageInfo.Caster,
			    percentDelta,
			    out var oldPercent,
			    out var newPercent,
			    out failReason))
		{
			LogLimited("HoMM3 hard-law CSV runtime failed closed for Stronghold post-attack damage: " + failReason);
			return false;
		}
		LogLimited("HoMM3 hard-law CSV runtime armed Stronghold post-attack damage state: context={" + context + "} percentDelta=" + percentDelta + " oldPercent=" + oldPercent + " newPercent=" + newPercent + " method=" + FormatMethod(originalMethod) + ".");
		return true;
	}
	private static bool TryApplyExistingFortressThornedHidesWeakness(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Thorned Hides weakness skipped: " + readFailReason);
			return false;
		}
		if (!Homm3BattleLocalLawState.TryConsumeFortressThornedHidesWeakness(damageInfo.Caster, out var percent, out var stateFailReason))
			return false;
		var reduction = checked(currentDamage * percent / 100);
		if (reduction <= 0 && currentDamage > 1)
			reduction = 1;
		if (reduction <= 0)
		{
			LogLimited("HoMM3 training-damage runtime consumed Thorned Hides weakness without damage reduction: currentDamage=" + currentDamage + " percent=" + percent + ".");
			return false;
		}
		newDamage = Math.Max(0, checked(currentDamage - reduction));
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied Fortress Thorned Hides outgoing damage reduction: method="
		           + FormatMethod(originalMethod)
		           + " percent=" + percent
		           + " oldDamage=" + currentDamage
		           + " reduction=" + reduction
		           + " newDamage=" + newDamage
		           + "; custom battle-local state, no native Attack/stat/status mutation.");
		return true;
	}

	private static bool TryApplyExistingFortressThornedHidesCounterattackMark(
		object receiverUnit,
		object[] args,
		MethodBase originalMethod)
	{
		if (args == null || args.Length != 8)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Thorned Hides mark skipped: " + readFailReason);
			return false;
		}
		if (!Homm3BattleLocalLawState.TryConsumeFortressThornedHidesCounterattack(damageInfo.Caster, out var percent, out var stateFailReason))
			return false;
		if (!Homm3BattleLocalLawState.TryMarkFortressThornedHidesWeakened(
			    damageInfo.Receiver,
			    percent,
			    out var oldPercent,
			    out var newPercent,
			    out var markFailReason))
		{
			LogLimited("HoMM3 training-damage runtime consumed Thorned Hides counterattack state without marking struck unit: " + markFailReason);
			return false;
		}
		LogLimited("HoMM3 training-damage runtime applied Fortress Thorned Hides battle-local weakness mark: method="
		           + FormatMethod(originalMethod)
		           + " oldPercent=" + oldPercent
		           + " newPercent=" + newPercent
		           + "; exact CounterAttack event armed one-shot state, no native Attack/stat/status mutation.");
		return true;
	}

	private static bool TryApplyExistingRampartAvengerReprisal(
		object receiverUnit,
		object[] args,
		int currentDamage,
		MethodBase originalMethod,
		out int newDamage)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || currentDamage <= 0)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, args, out var damageInfo, out var readFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Reprisal skipped: " + readFailReason);
			return false;
		}
		if (damageInfo.Receiver == null)
			return false;
		if (!TryRequireRampartAvengerGameplayMark(damageInfo.Receiver, out var markCount, out var markFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Reprisal kept armed because target is not Avenger-marked: " + markFailReason);
			return false;
		}
		if (!Homm3BattleLocalLawState.TryConsumeSingleRampartAvengerReprisal(out var armedDataSideIndex, out var percent, out var stateFailReason))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Reprisal skipped: " + stateFailReason);
			return false;
		}
		var delta = checked(currentDamage * percent / 100);
		if (delta <= 0)
			return false;
		newDamage = checked(currentDamage + delta);
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied Rampart Avenger's Reprisal custom counterattack damage: method="
		           + FormatMethod(originalMethod)
		           + " armedDataSideIndex=" + armedDataSideIndex
		           + " percent=" + percent
		           + " receiverMarkCount=" + markCount
		           + " oldDamage=" + currentDamage
		           + " delta=" + delta
		           + " newDamage=" + newDamage
		           + "; exact CounterAttack event armed one-shot state consumed by the next Avenger-marked damage event because damage caster interfaces do not expose a reliable law-owner side.");
		return true;
	}
private static bool TryStrengthenRampartAvengerPotency(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		MethodBase originalMethod,
		out string failReason)
	{
		if (!string.Equals(profile.EffectKey, "rampart.avenger-vulnerability", StringComparison.Ordinal))
		{
			failReason = "not Avenger's Tutelage";
			return false;
		}
		if (damageInfo.Caster == null || damageInfo.Receiver == null)
		{
			failReason = "Avenger potency requires exact caster and receiver battle units";
			return false;
		}
		if (!TryRequireRampartAvengerGameplayMark(damageInfo.Receiver, out var existingMarkCount, out failReason))
		{
			failReason = "Avenger's Tutelage requires an existing Avenger gameplay mark before it can increase potency: " + failReason;
			return false;
		}
		if (!Homm3BattleLocalLawState.TryMarkRampartAvengerTarget(damageInfo.Receiver, out var oldMarkCount, out var newMarkCount, out failReason, applyMarker: false))
			return false;
		LogLimited("HoMM3 training-damage runtime strengthened Rampart Avenger potency: method="
		           + FormatMethod(originalMethod)
		           + " law=" + context.Law
		           + " existingMarkCount=" + existingMarkCount
		           + " oldMarkCount=" + oldMarkCount
		           + " newMarkCount=" + newMarkCount
		           + "; requires pre-existing Avenger gameplay mark and does not create the first marker.");
		failReason = null;
		return true;
	}

	private static bool TryApplyRampartAvengersPatienceMana(object casterUnit, MethodBase originalMethod)
	{
		if (casterUnit == null)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    casterUnit,
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var casterLawOwner,
			    out var failReason))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Patience mana skipped: " + failReason);
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    casterLawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var context,
			    out failReason))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Patience mana skipped: " + failReason);
			return false;
		}
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Rampart, StringComparison.Ordinal))
			return false;
		if (!Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(casterUnit, out var transferSide))
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Patience mana failed closed: caster TransferSide unresolved.");
			return false;
		}
		var dataHero = ReadDataHero(transferSide);
		if (dataHero == null)
		{
			LogLimited("HoMM3 training-damage runtime Avenger's Patience mana failed closed: caster Data.Hero unresolved from TransferSide.");
			return false;
		}
		const int manaRestore = 10;
		var before = dataHero.mana;
		dataHero.mana = before > int.MaxValue - manaRestore ? int.MaxValue : before + manaRestore;
		LogLimited("HoMM3 training-damage runtime applied Rampart Avenger's Patience mana restoration: method="
		           + FormatMethod(originalMethod)
		           + " law=" + context.Law
		           + " manaBefore=" + before.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaRestored=" + manaRestore.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + " manaAfter=" + dataHero.mana.ToString(System.Globalization.CultureInfo.InvariantCulture)
		           + ". This uses the normal hero mana field; temporary-mana UI/state remains unproven.");
		return true;
	}

	private static Hero ReadDataHero(object side)
	{
		if (side == null)
			return null;
		if (!TryReadExactObject(side, GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers, out var logicHero) || logicHero == null)
			return null;
		return TryReadExactObject(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers, out var dataHero) ? dataHero as Hero : null;
	}

	private static bool TryApplyCoveBurningAshMark(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		MethodBase originalMethod,
		out string failReason)
	{
		if (!string.Equals(profile.EffectKey, "cove.gunpowder-defense-debuff", StringComparison.Ordinal))
		{
			failReason = "not Burning Ash";
			return false;
		}
		if (damageInfo.Caster == null || damageInfo.Receiver == null)
		{
			failReason = "Burning Ash requires exact caster and receiver battle units";
			return false;
		}
		if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
			    damageInfo.Caster,
			    Homm3UnitLawClassifier.FamilyFact.Gunpowder,
			    out var gunpowderClassification,
			    out failReason))
		{
			failReason = "Burning Ash gunpowder predicate failed: " + failReason;
			return false;
		}
		var points = Math.Abs(plan.DefenseDebuffPerHit);
		if (points <= 0)
		{
			failReason = "Burning Ash plan has no ash points";
			return false;
		}
		BurningAshState state;
		int oldPoints;
		int newPoints;
		lock (BurningAshLock)
		{
			state = BurningAshByTarget.GetOrCreateValue(damageInfo.Receiver);
			if (state == null)
			{
				failReason = "Burning Ash refused: receiver has no native identity";
				return false;
			}
			oldPoints = state.Points;
			state.Points = Math.Min(BurningAshMaxPoints, state.Points + points);
			newPoints = state.Points;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(damageInfo.Receiver, Homm3CustomLawVisualMarkerRuntime.BurningAsh, newPoints, 99, "Cove Burning Ash");
		LogLimited("HoMM3 training-damage runtime applied Cove Burning Ash mark: method="
		           + FormatMethod(originalMethod)
		           + " law=" + context.Law
		           + " effect=" + plan.EffectKey
		           + " addedAshPoints=" + points
		           + " oldAshPoints=" + oldPoints
		           + " newAshPoints=" + newPoints
		           + " gunpowder=" + (gunpowderClassification.Sid ?? "unknown")
		           + "; custom battle-local state, no native buff/status mutation.");
		failReason = null;
		return true;
	}
	private static bool TryPlanAllowedFortressDebuffedAttackerDamageReduction(
		object receiverUnit,
		object[] damageApplyArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo buffInfo,
		out string failReason)
	{
		damageInfo = default;
		context = default;
		plan = default;
		buffInfo = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, damageApplyArgs, out damageInfo, out failReason))
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    damageInfo.Receiver,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var receiverLawOwner,
			    out failReason))
		{
			failReason = "Fortress receiver law-owner resolution failed: " + failReason;
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    receiverLawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out context,
			    out failReason))
		{
			failReason = "Fortress receiver law gate failed: " + failReason;
			return false;
		}
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Fortress, StringComparison.Ordinal))
		{
			failReason = "receiver active training law is not Fortress: " + context.Law;
			return false;
		}
		if (!Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(
			    context.Law.FactionSid,
			    context.Law.Rank,
			    out var profile,
			    out failReason))
		{
			return false;
		}
		if (!profile.RequiresDebuffedAttacker)
		{
			failReason = "Fortress receiver profile does not require debuffed attacker: " + profile.EffectKey;
			return false;
		}
		if (!Homm3CustomLawEffectPlans.TryPlanTrainingDamageEffect(profile, damageInfo, out plan, out failReason))
			return false;
		if (!string.Equals(plan.MutationKind, "attacker-damage-reduction", StringComparison.Ordinal))
		{
			failReason = "Fortress receiver profile has unsupported mutation kind '" + (plan.MutationKind ?? "null") + "'";
			return false;
		}
		if (damageInfo.Caster == null)
		{
			failReason = "Fortress debuffed-attacker predicate requires exact caster battle object";
			return false;
		}
		if (!Homm3StatusTaxonomyRegistry.TryGetSidsForAnyTag(new[] { "negative" }, out var negativeStatusSids))
		{
			failReason = "status taxonomy has no exact negative-status SID set";
			return false;
		}
		if (!Homm3BuffDebuffNativeAdapter.TryRequireAnyBuffSidFromReceiver(
			    damageInfo.Caster,
			    negativeStatusSids,
			    out buffInfo,
			    out failReason))
		{
			failReason = "Fortress debuffed-attacker predicate failed: " + failReason;
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool ApplyPlannedDamageDelta(
		object[] args,
		int currentDamage,
		int observedDamage,
		Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		MethodBase originalMethod,
		string predicateDetail,
		int? plannedDamageOverride,
		out int newDamage,
		out string failReason)
	{
		newDamage = currentDamage;
		if (args == null || args.Length != 8 || args[3] is not int argDamage || argDamage != currentDamage)
		{
			failReason = "damage argument shape changed before mutation";
			return false;
		}
		var damageDelta = plannedDamageOverride ?? plan.PlannedBonusDamage;
		if (damageDelta == 0)
		{
			failReason = "planned damage delta is zero for " + plan.EffectKey;
			return false;
		}
		newDamage = checked(currentDamage + damageDelta);
		if (newDamage < 0)
			newDamage = 0;
		args[3] = newDamage;
		LogLimited("HoMM3 training-damage runtime applied damage delta: method="
		           + FormatMethod(originalMethod)
		           + " law=" + context.Law
		           + " effect=" + plan.EffectKey
		           + " observedDamage=" + observedDamage
		           + " oldDamage=" + currentDamage
		           + " delta=" + damageDelta
		           + " newDamage=" + newDamage
		           + " predicate=" + (predicateDetail ?? "none")
		           + " plan={" + plan + "}.");
		failReason = null;
		return true;
	}

	private static bool TryRequireRampartAvengerGameplayMark(object receiver, out int markCount, out string failReason)
	{
		markCount = 0;
		if (Homm3RampartAvengerMarkerRuntime.TrySynchronizeMarkFromReceiver(receiver, out var oldMarkCount, out var newMarkCount, out var detail, out var syncFailReason))
		{
			markCount = newMarkCount;
			failReason = null;
			LogLimited("HoMM3 training-damage runtime confirmed Rampart Avenger gameplay mark state: oldMarkCount="
			           + oldMarkCount
			           + " newMarkCount="
			           + newMarkCount
			           + " detail={"
			           + detail
			           + "}.");
			return true;
		}
		failReason = "no active Rampart Avenger gameplay mark: " + syncFailReason;
		return false;
	}
	private static bool TryRequireSupportedDirectDamageScalarProfile(
		Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		out string predicateDetail,
		out int? plannedDamageOverride,
		out string failReason)
	{
		predicateDetail = "none";
		plannedDamageOverride = null;
		if (!string.Equals(plan.MutationKind, "damage-percent-scalar", StringComparison.Ordinal)
		    && !string.Equals(plan.MutationKind, "gated-entry-damage-scalar", StringComparison.Ordinal))
		{
			failReason = "unsupported mutation kind '" + (plan.MutationKind ?? "null") + "' for " + plan.EffectKey;
			return false;
		}

		if (profile.RequiresPositiveMoraleValue)
		{
			if (profile.RequiresIsolatedTarget
			    || profile.RequiresGunpowderDealer
			    || profile.RequiresCannonOrPirateDealer
			    || profile.RequiresDebuffedAttacker
			    || profile.RequiresAvengerMark
			    || profile.RequiresHeroSpellCast
			    || profile.RequiresElementalFamily
			    || profile.RequiresGatedIdentity
			    || profile.RequiresCorpseCount
			    || profile.RequiresWoundedUnit)
			{
				failReason = "profile '" + profile.EffectKey + "' combines positiveMoraleValue with unimplemented predicate(s): " + plan.RequiredPredicates;
				return false;
			}
			if (plan.BonusDamagePercent <= 0)
			{
				failReason = "positiveMoraleValue profile has no positive per-morale damage percent: " + profile.EffectKey;
				return false;
			}
			if (!TryRequirePositiveUnitMoraleValue(damageInfo.Caster, out var moraleValue, out predicateDetail, out failReason))
				return false;
			plannedDamageOverride = checked(damageInfo.Damage * plan.BonusDamagePercent * moraleValue / 100);
			if (plannedDamageOverride.Value == 0)
			{
				failReason = "positiveMoraleValue planned damage delta rounded to zero for " + profile.EffectKey;
				return false;
			}
			return true;
		}

		if (profile.RequiresIsolatedTarget)
		{
			if (profile.RequiresElementalFamily)
		{
			if (profile.RequiresGunpowderDealer
			    || profile.RequiresCannonOrPirateDealer
			    || profile.RequiresDebuffedAttacker
			    || profile.RequiresAvengerMark
			    || profile.RequiresHeroSpellCast
			    || profile.RequiresGatedIdentity
			    || profile.RequiresCorpseCount
			    || profile.RequiresWoundedUnit)
			{
				failReason = "profile '" + profile.EffectKey + "' combines elementalFamily with unimplemented predicate(s): " + plan.RequiredPredicates;
				return false;
			}
			if (plan.BonusDamagePercent <= 0)
			{
				failReason = "elementalFamily profile has no positive damage percent: " + profile.EffectKey;
				return false;
			}
			if (damageInfo.Caster == null)
			{
				failReason = "elementalFamily predicate requires exact caster battle unit";
				return false;
			}
			if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
				    damageInfo.Caster,
				    Homm3UnitLawClassifier.FamilyFact.Elemental,
				    out var elementalClassification,
				    out failReason))
			{
				failReason = "elementalFamily predicate failed: " + failReason;
				return false;
			}
			predicateDetail = "elementalFamily sid=" + (elementalClassification.Sid ?? "unknown") + ";source=" + (elementalClassification.IdentitySource ?? "unknown");
			return true;
		}
		if (profile.RequiresGunpowderDealer
			    || profile.RequiresCannonOrPirateDealer
			    || profile.RequiresDebuffedAttacker
			    || profile.RequiresAvengerMark
			    || profile.RequiresHeroSpellCast
			    || profile.RequiresElementalFamily
			    || profile.RequiresGatedIdentity
			    || profile.RequiresCorpseCount
			    || profile.RequiresWoundedUnit)
			{
				failReason = "profile '" + profile.EffectKey + "' combines isolatedTarget with unimplemented predicate(s): " + plan.RequiredPredicates;
				return false;
			}
			if (!TryRequireReceiverIsolatedFromOtherAdjacentUnits(damageInfo, out predicateDetail, out failReason))
				return false;
			return true;
		}

		if (profile.RequiresGatedIdentity)
		{
			if (profile.RequiresGunpowderDealer
			    || profile.RequiresCannonOrPirateDealer
			    || profile.RequiresDebuffedAttacker
			    || profile.RequiresAvengerMark
			    || profile.RequiresHeroSpellCast
			    || profile.RequiresElementalFamily
			    || profile.RequiresCorpseCount
			    || profile.RequiresWoundedUnit)
			{
				failReason = "profile '" + profile.EffectKey + "' combines gatedIdentity with unimplemented predicate(s): " + plan.RequiredPredicates;
				return false;
			}
			if (!string.Equals(plan.MutationKind, "gated-entry-damage-scalar", StringComparison.Ordinal))
			{
				failReason = "gatedIdentity profile has unsupported mutation kind '" + (plan.MutationKind ?? "null") + "' for " + profile.EffectKey;
				return false;
			}
			if (!TryRequireGatedOrSummonedCaster(damageInfo.Caster, out predicateDetail, out failReason))
				return false;
			return true;
		}

		if (profile.RequiresAvengerMark)
		{
			if (profile.RequiresGunpowderDealer
			    || profile.RequiresCannonOrPirateDealer
			    || profile.RequiresDebuffedAttacker
			    || profile.RequiresHeroSpellCast
			    || profile.RequiresElementalFamily
			    || profile.RequiresGatedIdentity
			    || profile.RequiresCorpseCount
			    || profile.RequiresWoundedUnit)
			{
				failReason = "profile '" + profile.EffectKey + "' combines avengerMark with unimplemented predicate(s): " + plan.RequiredPredicates;
				return false;
			}
			if (plan.BonusDamagePercent <= 0)
			{
				failReason = "avengerMark profile has no positive damage percent: " + profile.EffectKey;
				return false;
			}
			if (damageInfo.Receiver == null)
			{
				failReason = "avengerMark predicate requires exact receiver battle unit";
				return false;
			}
			if (!TryRequireRampartAvengerGameplayMark(damageInfo.Receiver, out var markCount, out failReason))
			{
				failReason = "avengerMark predicate failed: " + failReason;
				return false;
			}
			var cappedMarkCount = Math.Min(5, Math.Max(1, markCount));
			plannedDamageOverride = checked(damageInfo.Damage * plan.BonusDamagePercent * cappedMarkCount / 100);
			if (plannedDamageOverride.Value == 0)
			{
				failReason = "avengerMark planned damage delta rounded to zero for " + profile.EffectKey;
				return false;
			}
			predicateDetail = "customAvengerMarker count=" + markCount + ";cappedPotency=" + cappedMarkCount + ";source=homm3_law_marker_avenger_intensity";
			return true;
		}

		if (profile.RequiresGunpowderDealer
		    || profile.RequiresCannonOrPirateDealer
		    || profile.RequiresDebuffedAttacker
		    || profile.RequiresAvengerMark
		    || profile.RequiresHeroSpellCast
		    || profile.RequiresElementalFamily
		    || profile.RequiresCorpseCount
		    || profile.RequiresWoundedUnit)
		{
			failReason = "profile '" + profile.EffectKey + "' has unimplemented runtime predicate(s): " + plan.RequiredPredicates;
			return false;
		}

		failReason = null;
		return true;
	}
	private static bool TryRequireGatedOrSummonedCaster(object unit, out string predicateDetail, out string failReason)
	{
		predicateDetail = null;
		if (unit == null)
		{
			failReason = "gatedIdentity predicate requires exact attacking battle unit";
			return false;
		}
		if (!TryReadExactBool(unit, GameSymbols.BattleUnitInit.BattleUnitIsSummonMembers, out var isSummon, out var summonMember))
		{
			failReason = "gatedIdentity predicate could not read exact battle Unit isSummon member; unitEvidence=" + Homm3UnitLawClassifier.DescribeEvidence(unit);
			return false;
		}
		if (!TryReadExactBool(unit, GameSymbols.BattleUnitInit.BattleUnitSpawnedInBattleMembers, out var spawnedInBattle, out var spawnedMember))
		{
			failReason = "gatedIdentity predicate could not read exact battle Unit spawnedInBattle member; unitEvidence=" + Homm3UnitLawClassifier.DescribeEvidence(unit);
			return false;
		}
		if (!isSummon || !spawnedInBattle)
		{
			failReason = "gatedIdentity rejected permanent or non-summoned unit: isSummon="
			             + isSummon
			             + " spawnedInBattle="
			             + spawnedInBattle
			             + " unitEvidence="
			             + Homm3UnitLawClassifier.DescribeEvidence(unit);
			return false;
		}
		predicateDetail = "gatedIdentity " + summonMember + "=true " + spawnedMember + "=true unitEvidence=" + Homm3UnitLawClassifier.DescribeEvidence(unit);
		failReason = null;
		return true;
	}
	private static bool TryRequirePositiveUnitMoraleValue(object unit, out int moraleValue, out string predicateDetail, out string failReason)
	{
		moraleValue = 0;
		predicateDetail = null;
		if (unit == null)
		{
			failReason = "positiveMoraleValue predicate requires exact attacking battle unit";
			return false;
		}
		for (var i = 0; i < GameSymbols.MoraleTriggerLaws.UnitStatMembers.Length; i++)
		{
			var statMember = GameSymbols.MoraleTriggerLaws.UnitStatMembers[i];
			if (!TryReadExactObject(unit, new[] { statMember }, out var stat) || stat == null)
				continue;
			if (!TryReadExactObject(stat, GameSymbols.MoraleTriggerLaws.UnitCurrentMoraleValueMembers, out var rawMorale) || rawMorale == null)
				continue;
			try
			{
				moraleValue = Convert.ToInt32(rawMorale, System.Globalization.CultureInfo.InvariantCulture);
			}
			catch (Exception ex)
			{
				failReason = "positiveMoraleValue exact moral member was not Int32-compatible: " + ex.Message;
				return false;
			}
			if (moraleValue <= 0)
			{
				failReason = "positiveMoraleValue rejected non-positive current morale: " + moraleValue;
				return false;
			}
			predicateDetail = "positiveMoraleValue statMember=" + statMember + " morale=" + moraleValue;
			failReason = null;
			return true;
		}
		failReason = "positiveMoraleValue found no exact current morale stat member";
		return false;
	}
	private static bool TryRequireReceiverIsolatedFromOtherAdjacentUnits(
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		out string predicateDetail,
		out string failReason)
	{
		predicateDetail = null;
		if (damageInfo.Receiver == null)
		{
			failReason = "isolatedTarget predicate requires exact receiver battle object";
			return false;
		}
		if (!TryReadBattleObjectHex(damageInfo.Receiver, out var receiverHex, out failReason))
		{
			failReason = "isolatedTarget receiver hex failed: " + failReason;
			return false;
		}
		if (!TryReadHexCoordinates(receiverHex, out var receiverX, out var receiverZ, out failReason))
		{
			failReason = "isolatedTarget receiver coordinates failed: " + failReason;
			return false;
		}
		if (!TryEnumerateBattleUnitsFromObject(damageInfo.Receiver, out var units, out failReason))
		{
			failReason = "isolatedTarget unit enumeration failed: " + failReason;
			return false;
		}

		var checkedUnits = 0;
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			if (unit == null || SameRuntimeObject(unit, damageInfo.Receiver) || SameRuntimeObject(unit, damageInfo.Caster))
				continue;
			if (!TryReadBattleObjectHex(unit, out var unitHex, out _))
				continue;
			if (!TryReadHexCoordinates(unitHex, out var unitX, out var unitZ, out _))
				continue;
			checkedUnits++;
			var distance = HexDistance(receiverX, receiverZ, unitX, unitZ);
			if (distance == 1)
			{
				failReason = "isolatedTarget rejected: another unit is adjacent to receiver; unit=" + DescribeRuntimeObject(unit);
				return false;
			}
		}

		predicateDetail = "isolatedTarget receiverHex=(" + receiverX + "," + receiverZ + ") checkedUnits=" + checkedUnits;
		failReason = null;
		return true;
	}


	private static bool TryReadBattleStackCount(object battleUnit, out int stackCount, out string failReason)
	{
		stackCount = 0;
		if (battleUnit == null)
		{
			failReason = "battle unit is null";
			return false;
		}
		try
		{
			for (var i = 0; i < GameSymbols.DamageKill.StackCountGetter.NameHints.Length; i++)
			{
				var name = GameSymbols.DamageKill.StackCountGetter.NameHints[i];
				var method = battleUnit.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				if (method == null)
					continue;
				var value = method.Invoke(battleUnit, Array.Empty<object>());
				if (value == null)
					continue;
				stackCount = Convert.ToInt32(value, System.Globalization.CultureInfo.InvariantCulture);
				if (stackCount > 0)
				{
					failReason = null;
					return true;
				}
			}
		}
		catch (Exception ex)
		{
			failReason = "exact stack-count getter failed: " + ex.Message;
			return false;
		}
		if (DamageKillMapping.TryGetAliveCreatureCount(battleUnit, out stackCount) && stackCount > 0)
		{
			failReason = null;
			return true;
		}
		failReason = "no exact positive stack-count value found";
		return false;
	}	private static bool SameLawOwnerSide(object leftLawOwner, object rightLawOwner)
	{
		return TryReadDataSideIndex(leftLawOwner, out var leftIndex)
		       && TryReadDataSideIndex(rightLawOwner, out var rightIndex)
		       && leftIndex == rightIndex;
	}

	private static bool TryReadDataSideIndex(object dataSide, out int dataSideIndex)
	{
		dataSideIndex = -1;
		if (dataSide == null)
			return false;
		var type = dataSide.GetType();
		for (var i = 0; i < GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers.Length; i++)
		{
			var name = GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers[i];
			if (string.IsNullOrEmpty(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType == typeof(int) && !method.ContainsGenericParameters)
					{
						dataSideIndex = (int)method.Invoke(dataSide, Array.Empty<object>());
						return dataSideIndex >= 0;
					}
				}
				catch
				{
					return false;
				}
				try
				{
					var field = current.GetField(name, flags);
					if (field != null && field.FieldType == typeof(int))
					{
						dataSideIndex = (int)field.GetValue(dataSide);
						return dataSideIndex >= 0;
					}
				}
				catch
				{
					return false;
				}
			}
		}
		return false;
	}
private static string DescribeRuntimeObject(object value)
	{
		return value == null ? "<null>" : value.GetType().FullName;
	}

	private static bool TryEnumerateBattleUnitsFromObject(object battleObject, out System.Collections.Generic.List<object> units, out string failReason)
	{
		units = null;
		if (battleObject == null)
		{
			failReason = "battle object is null";
			return false;
		}
		if (!TryReadExactObject(battleObject, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers, out var battleLogic) || battleLogic == null)
		{
			failReason = "battle object exposed no exact battle logic";
			return false;
		}
		if (!TryReadExactObject(battleLogic, GameSymbols.BattleEventLaws.BattleLogicTransferBattleMembers, out var transferBattle) || transferBattle == null)
		{
			failReason = "battle logic exposed no exact transfer battle";
			return false;
		}
		if (!TryReadExactObject(transferBattle, GameSymbols.BattleEventLaws.TransferBattleSidesMembers, out var sides) || sides is not System.Collections.IEnumerable sideEnumerable)
		{
			failReason = "transfer battle exposed no enumerable exact sides";
			return false;
		}
		units = new System.Collections.Generic.List<object>();
		foreach (var side in sideEnumerable)
		{
			if (side == null)
				continue;
			if (!TryReadExactObject(side, GameSymbols.BattleEventLaws.TransferSideUnitsMembers, out var sideUnits) || sideUnits is not System.Collections.IEnumerable unitEnumerable)
				continue;
			foreach (var unit in unitEnumerable)
			{
				if (unit != null)
					units.Add(unit);
				if (units.Count > 512)
				{
					failReason = "battle unit enumeration exceeded safety cap";
					return false;
				}
			}
		}
		if (units.Count == 0)
		{
			failReason = "battle unit enumeration found no units";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryReadBattleObjectHex(object battleObject, out object hex, out string failReason)
	{
		hex = null;
		if (battleObject == null)
		{
			failReason = "battle object is null";
			return false;
		}
		if (!TryReadExactObject(battleObject, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out hex) || hex == null)
		{
			failReason = "battle object exposed no exact hex";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryReadHexCoordinates(object hex, out int x, out int z, out string failReason)
	{
		x = 0;
		z = 0;
		if (hex == null)
		{
			failReason = "hex is null";
			return false;
		}
		if (!TryReadExactObject(hex, GameSymbols.BattleEventLaws.HexXMembers, out var rawX) || rawX == null)
		{
			failReason = "hex exposed no exact x coordinate";
			return false;
		}
		if (!TryReadExactObject(hex, GameSymbols.BattleEventLaws.HexZMembers, out var rawZ) || rawZ == null)
		{
			failReason = "hex exposed no exact z coordinate";
			return false;
		}
		try
		{
			x = Convert.ToInt32(rawX, System.Globalization.CultureInfo.InvariantCulture);
			z = Convert.ToInt32(rawZ, System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "hex coordinates were not Int32-compatible: " + ex.Message;
			return false;
		}
	}

	private static int HexDistance(int ax, int az, int bx, int bz)
	{
		var dx = bx - ax;
		var dz = bz - az;
		return (Math.Abs(dx) + Math.Abs(dz) + Math.Abs(dx + dz)) / 2;
	}

	private static bool TryReadExactBool(object obj, string[] names, out bool value, out string matchedMember)
	{
		value = false;
		matchedMember = null;
		if (obj == null || names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (!TryReadExactObject(obj, new[] { name }, out var raw) || raw == null)
				continue;
			if (raw is bool b)
			{
				value = b;
				matchedMember = name;
				return true;
			}
		}
		return false;
	}
	private static bool TryReadExactObject(object obj, string[] names, out object value)
	{
		value = null;
		if (obj == null || names == null)
			return false;
		var type = obj.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(obj);
						return value != null;
					}
				}
				catch { }
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(obj, null);
						return value != null;
					}
				}
				catch { }
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
					{
						value = method.Invoke(obj, null);
						return value != null;
					}
				}
				catch { }
			}
		}
		return false;
	}

	private static bool SameRuntimeObject(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		var leftKey = Homm3DirectStateIdentity.ResolveKeyOrZero(left);
		var rightKey = Homm3DirectStateIdentity.ResolveKeyOrZero(right);
		return leftKey != 0 && leftKey == rightKey;
	}
	private static MethodInfo ResolveExactVoidMethod(Type type, string name, int parameterCount)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}

		return null;
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
