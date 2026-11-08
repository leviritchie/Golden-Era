using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated counterattack law runtime entry points.
/// This class registers no Harmony hooks and does not infer counterattacks from
/// damage timing, animations, or event order. Future exact hooks must pass a
/// native EAbilityType value that has already been proven to belong to the
/// relevant attack/counterattack context.
/// </summary>
internal static class Homm3CustomCounterattackLawRuntime
{
	internal readonly struct CounterattackAbilityObservation
	{
		internal readonly object Counterattacker;
		internal readonly EAbilityType AbilityType;
		internal readonly int AbilityIndex;

		internal CounterattackAbilityObservation(object counterattacker, EAbilityType abilityType, int abilityIndex)
		{
			Counterattacker = counterattacker;
			AbilityType = abilityType;
			AbilityIndex = abilityIndex;
		}

		internal bool IsCounterAttackCandidate => AbilityType == EAbilityType.CounterAttack;

		public override string ToString()
		{
			return "abilityType=" + AbilityType
			       + " abilityIndex=" + AbilityIndex
			       + " isCounterAttackCandidate=" + IsCounterAttackCandidate
			       + " counterattacker=" + (Counterattacker == null ? "null" : Counterattacker.GetType().FullName)
			       + " semanticBoundary=ability-listener-not-yet-correlated-to-committed-damage";
		}
	}

	internal static bool TryObserveCounterattackAbility(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out string failReason)
	{
		observation = default;
		if (counterattacker == null)
		{
			failReason = "counterattacking battle object is null";
			return false;
		}
		observation = new CounterattackAbilityObservation(counterattacker, abilityType, abilityIndex);
		failReason = null;
		return true;
	}

	internal static bool TryObserveCounterattackChangeAbilityEvent(
		object changeAbilityEventArgs,
		out CounterattackAbilityObservation observation,
		out string failReason)
	{
		observation = default;
		if (!Homm3BattleEventNativeAdapter.TryReadChangeAbilityEvent(changeAbilityEventArgs, out var info, out failReason))
			return false;
		return TryObserveCounterattackAbility(info.Target, info.AbilityType, info.AbilityIndex, out observation, out failReason);
	}

	internal static bool TryPlanAllowedCounterattackDoctrineEffectForChangeAbilityEvent(
		object changeAbilityEventArgs,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan,
		out string failReason)
	{
		observation = default;
		profile = default;
		lawOwner = null;
		context = default;
		plan = default;
		if (!Homm3BattleEventNativeAdapter.TryReadChangeAbilityEvent(changeAbilityEventArgs, out var info, out failReason))
			return false;
		if (!TryGetAllowedCounterattackDoctrineProfileForBattleObject(
			    info.Target,
			    info.AbilityType,
			    info.AbilityIndex,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanCounterattackDoctrineEffect(profile, observation, out plan, out failReason);
	}
	internal static bool TryGetCandidateCounterattackDoctrineProfileForChangeAbilityEvent(
		object changeAbilityEventArgs,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		observation = default;
		profile = default;
		lawOwner = null;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadChangeAbilityEvent(changeAbilityEventArgs, out var info, out failReason))
			return false;
		return TryGetCandidateCounterattackDoctrineProfileForBattleObject(
			info.Target,
			info.AbilityType,
			info.AbilityIndex,
			out observation,
			out profile,
			out lawOwner,
			out context,
			out failReason);
	}

	internal static bool TryPlanCandidateCounterattackDoctrineEffectForChangeAbilityEvent(
		object changeAbilityEventArgs,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateCounterattackDoctrineProfileForChangeAbilityEvent(
			    changeAbilityEventArgs,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanCounterattackDoctrineEffect(profile, observation, out plan, out failReason);
	}

	internal static bool TryObserveAllowedCounterattackAbilityForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		observation = default;
		if (!TryEnterAllowedCounterattackForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return TryObserveCounterattackAbility(counterattacker, abilityType, abilityIndex, out observation, out failReason);
	}

	internal static bool TryGetAllowedCounterattackDoctrineProfileForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryObserveAllowedCounterattackAbilityForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out observation,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetCounterattackDoctrineProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			observation,
			out profile,
			out failReason);
	}

	internal static bool TryPlanAllowedCounterattackDoctrineEffectForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedCounterattackDoctrineProfileForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanCounterattackDoctrineEffect(profile, observation, out plan, out failReason);
	}

	internal static bool TryGetCandidateCounterattackDoctrineProfileForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		observation = default;
		profile = default;
		if (!TryEnterCandidateCounterattackForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		if (!TryObserveCounterattackAbility(counterattacker, abilityType, abilityIndex, out observation, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetCounterattackDoctrineProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			observation,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateCounterattackDoctrineEffectForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out CounterattackAbilityObservation observation,
		out Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateCounterattackDoctrineProfileForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanCounterattackDoctrineEffect(profile, observation, out plan, out failReason);
	}

	internal static bool TryEnterAllowedCounterattack(
		object lawOwner,
		EAbilityType abilityType,
		int abilityIndex,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		context = default;
		if (abilityType != EAbilityType.CounterAttack)
		{
			failReason = "native ability type is not CounterAttack: " + abilityType + " index=" + abilityIndex;
			return false;
		}

		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"counterattack.doctrine",
			Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			out context,
			out failReason);
	}

	internal static bool TryEnterAllowedCounterattackForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		lawOwner = null;
		context = default;
		if (abilityType != EAbilityType.CounterAttack)
		{
			failReason = "native ability type is not CounterAttack: " + abilityType + " index=" + abilityIndex;
			return false;
		}
		if (counterattacker == null)
		{
			failReason = "counterattacking battle object is null";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    counterattacker,
			    Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			    out lawOwner,
			    out failReason))
		{
			failReason = "counterattacking battle object law-owner resolution failed: " + failReason;
			return false;
		}

		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"counterattack.doctrine",
			Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			out context,
			out failReason);
	}

	internal static bool TryEnterCandidateCounterattackForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		lawOwner = null;
		context = default;
		if (abilityType != EAbilityType.CounterAttack)
		{
			failReason = "native ability type is not CounterAttack: " + abilityType + " index=" + abilityIndex;
			return false;
		}
		if (counterattacker == null)
		{
			failReason = "counterattacking battle object is null";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    counterattacker,
			    Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			    out lawOwner,
			    out failReason))
		{
			failReason = "counterattacking battle object law-owner resolution failed: " + failReason;
			return false;
		}

		return Homm3CustomLawHandlerRegistry.TryProbeHandler(
			lawOwner,
			"counterattack.doctrine",
			Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedCounterattackDamage(
		object lawOwner,
		EAbilityType abilityType,
		int abilityIndex,
		object damageEventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!TryEnterAllowedCounterattack(lawOwner, abilityType, abilityIndex, out context, out failReason))
			return false;
		return Homm3BattleEventNativeAdapter.TryReadDamageEvent(damageEventArgs, out info, out failReason);
	}

	internal static bool TryReadAllowedCounterattackDamageForBattleObject(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		object damageEventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		lawOwner = null;
		context = default;
		if (!TryEnterAllowedCounterattackForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3BattleEventNativeAdapter.TryReadDamageEvent(damageEventArgs, out info, out failReason);
	}

	internal static bool TryReadAllowedCounterattackDamageForBattleObjectWithCounterattackerFact(
		object counterattacker,
		EAbilityType abilityType,
		int abilityIndex,
		object damageEventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredCounterattackerFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification counterattackerClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		counterattackerClassification = default;
		if (!TryReadAllowedCounterattackDamageForBattleObject(
			    counterattacker,
			    abilityType,
			    abilityIndex,
			    damageEventArgs,
			    out info,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			counterattacker,
			requiredCounterattackerFact,
			out counterattackerClassification,
			out failReason);
	}

	internal static bool TryReadAllowedCounterattackDamageWithDealerFact(
		object lawOwner,
		EAbilityType abilityType,
		int abilityIndex,
		object damageEventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredDealerFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification dealerClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		dealerClassification = default;
		if (!TryReadAllowedCounterattackDamage(lawOwner, abilityType, abilityIndex, damageEventArgs, out info, out context, out failReason))
			return false;
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			info.Dealer ?? info.Caster,
			requiredDealerFact,
			out dealerClassification,
			out failReason);
	}

	internal static bool TryReadAllowedCounterattackDamageWithReceiverFact(
		object lawOwner,
		EAbilityType abilityType,
		int abilityIndex,
		object damageEventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredReceiverFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification receiverClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		receiverClassification = default;
		if (!TryReadAllowedCounterattackDamage(lawOwner, abilityType, abilityIndex, damageEventArgs, out info, out context, out failReason))
			return false;
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			info.Receiver,
			requiredReceiverFact,
			out receiverClassification,
			out failReason);
	}
}
