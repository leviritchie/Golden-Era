namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated battle-event law runtime entry points.
/// This class registers no Harmony hooks and does not mutate damage, movement,
/// formation, turn order, or cast state. Future exact battle-event hooks should
/// use these read gates before any packet-backed gameplay implementation.
/// </summary>
internal static class Homm3CustomBattleEventLawRuntime
{
	internal static bool TryReadAllowedDamageEvent(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(eventArgs, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"damage.training",
			Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedDamageEventWithDealerFact(
		object lawOwner,
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredDealerFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification dealerClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		dealerClassification = default;
		if (!TryReadAllowedDamageEvent(lawOwner, eventArgs, out info, out context, out failReason))
			return false;
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			info.Dealer ?? info.Caster,
			requiredDealerFact,
			out dealerClassification,
			out failReason);
	}

	internal static bool TryReadAllowedDamageEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadAllowedDamageEvent(lawOwner, eventArgs, out info, out context, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryReadCandidateDamageEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		info = default;
		profile = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(eventArgs, out info, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateTrainingDamageEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadCandidateDamageEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanTrainingDamageEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryPlanCandidateTrainingDamageApplyEffect(
		object receiverUnit,
		object[] damageApplyArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		out string failReason)
	{
		profile = default;
		context = default;
		plan = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, damageApplyArgs, out info, out failReason))
			return false;
		if (info.Caster == null)
		{
			failReason = "damage-apply invocation caster is null; training-damage law owner is caster-only";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    info.Caster,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var lawOwner,
			    out failReason))
		{
			failReason = "damage-apply caster law-owner resolution failed: " + failReason;
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out context,
			    out failReason))
		{
			failReason = "damage-apply caster law gate failed: " + failReason;
			return false;
		}
		if (!Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(
			    context.Law.FactionSid,
			    context.Law.Rank,
			    out profile,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanTrainingDamageEffect(profile, info, out plan, out failReason);
	}
	internal static bool TryPlanAllowedTrainingDamageApplyEffect(
		object receiverUnit,
		object[] damageApplyArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		out string failReason)
	{
		profile = default;
		context = default;
		plan = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageApplyInvocation(receiverUnit, damageApplyArgs, out info, out failReason))
			return false;
		if (info.Caster == null)
		{
			failReason = "damage-apply invocation caster is null; training-damage law owner is caster-only";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    info.Caster,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var lawOwner,
			    out failReason))
		{
			failReason = "damage-apply caster law-owner resolution failed: " + failReason;
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out context,
			    out failReason))
		{
			failReason = "damage-apply caster law gate failed: " + failReason;
			return false;
		}
		if (!Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(
			    context.Law.FactionSid,
			    context.Law.Rank,
			    out profile,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanTrainingDamageEffect(profile, info, out plan, out failReason);
	}
	internal static bool TryPlanAllowedTrainingDamageEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.TrainingDamageEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadAllowedDamageEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanTrainingDamageEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryReadAllowedDamageEventWithReceiverFact(
		object lawOwner,
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredReceiverFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification receiverClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		receiverClassification = default;
		if (!TryReadAllowedDamageEvent(lawOwner, eventArgs, out info, out context, out failReason))
			return false;
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			info.Receiver,
			requiredReceiverFact,
			out receiverClassification,
			out failReason);
	}

	internal static bool TryReadAllowedDamageEventForDealerLawOwnerWithDealerFact(
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredDealerFact,
		out Homm3BattleEventNativeAdapter.DamageEventInfo info,
		out Homm3UnitLawClassifier.Classification dealerClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		dealerClassification = default;
		lawOwner = null;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(eventArgs, out info, out failReason))
			return false;
		if (info.Dealer == null)
		{
			failReason = "damage event dealer is null; dealer-owned law gate does not fall back to caster";
			return false;
		}
		if (!TryEnterBattleObjectLawHandler(
			    info.Dealer,
			    "damage event dealer",
			    "damage.training",
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			info.Dealer,
			requiredDealerFact,
			out dealerClassification,
			out failReason);
	}

	internal static bool TryReadAllowedMeleeFormationEvent(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadAllowedFormationEvent(
			lawOwner,
			eventArgs,
			"battle.melee-formation",
			Homm3CustomFactionLawRuntime.MeleeFormationIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedMeleeFormationEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadAllowedMeleeFormationEvent(lawOwner, eventArgs, out info, out context, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetFormationProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"battle.melee-formation",
			out profile,
			out failReason);
	}

	internal static bool TryReadCandidateMeleeFormationEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadCandidateFormationEvent(
			    lawOwner,
			    eventArgs,
			    "battle.melee-formation",
			    Homm3CustomFactionLawRuntime.MeleeFormationIndex,
			    out info,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetFormationProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"battle.melee-formation",
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateMeleeFormationEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.FormationEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadCandidateMeleeFormationEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanFormationEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryPlanAllowedMeleeFormationEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.FormationEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadAllowedMeleeFormationEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanFormationEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryReadAllowedMeleeFormationEventWithCasterFactAndTargets(
		object lawOwner,
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredCasterFact,
		int minimumAttackedObjects,
		int minimumAttackedHexes,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3UnitLawClassifier.Classification casterClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		if (!TryReadAllowedMeleeFormationEvent(lawOwner, eventArgs, out info, out context, out failReason))
		{
			casterClassification = default;
			return false;
		}
		return TryRequireFormationCasterFactAndTargets(
			info,
			requiredCasterFact,
			minimumAttackedObjects,
			minimumAttackedHexes,
			out casterClassification,
			out failReason);
	}

	internal static bool TryReadAllowedMeleeFormationEventFromCasterLawOwnerWithCasterFactAndTargets(
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredCasterFact,
		int minimumAttackedObjects,
		int minimumAttackedHexes,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3UnitLawClassifier.Classification casterClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out info, out failReason))
		{
			casterClassification = default;
			lawOwner = null;
			context = default;
			return false;
		}
		if (info.Caster == null)
		{
			casterClassification = default;
			lawOwner = null;
			context = default;
			failReason = "melee formation caster is null";
			return false;
		}
		if (!TryEnterBattleObjectLawHandler(
			    info.Caster,
			    "melee formation caster",
			    "battle.melee-formation",
			    Homm3CustomFactionLawRuntime.MeleeFormationIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			casterClassification = default;
			return false;
		}
		return TryRequireFormationCasterFactAndTargets(
			info,
			requiredCasterFact,
			minimumAttackedObjects,
			minimumAttackedHexes,
			out casterClassification,
			out failReason);
	}

	internal static bool TryReadAllowedRangedFormationEvent(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadAllowedFormationEvent(
			lawOwner,
			eventArgs,
			"battle.ranged-formation",
			Homm3CustomFactionLawRuntime.RangedFormationIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedRangedFormationEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadAllowedRangedFormationEvent(lawOwner, eventArgs, out info, out context, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetFormationProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"battle.ranged-formation",
			out profile,
			out failReason);
	}

	internal static bool TryReadCandidateRangedFormationEventProfile(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadCandidateFormationEvent(
			    lawOwner,
			    eventArgs,
			    "battle.ranged-formation",
			    Homm3CustomFactionLawRuntime.RangedFormationIndex,
			    out info,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetFormationProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"battle.ranged-formation",
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateRangedFormationEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.FormationEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadCandidateRangedFormationEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanFormationEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryPlanAllowedRangedFormationEffect(
		object lawOwner,
		object eventArgs,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawEffectProfiles.FormationProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.FormationEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryReadAllowedRangedFormationEventProfile(lawOwner, eventArgs, out info, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanFormationEffect(profile, info, out plan, out failReason);
	}

	internal static bool TryReadAllowedRangedFormationFirstRoundEventFromCasterLawOwnerWithCasterFactAndTargets(
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredCasterFact,
		int minimumAttackedObjects,
		int minimumAttackedHexes,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3UnitLawClassifier.Classification casterClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out info, out failReason))
		{
			casterClassification = default;
			lawOwner = null;
			context = default;
			return false;
		}
		if (info.RoundNumber != 1)
		{
			casterClassification = default;
			lawOwner = null;
			context = default;
			failReason = "ranged formation event is not a first-round volley; round=" + info.RoundNumber;
			return false;
		}
		if (info.Caster == null)
		{
			casterClassification = default;
			lawOwner = null;
			context = default;
			failReason = "ranged formation caster is null";
			return false;
		}
		if (!TryEnterBattleObjectLawHandler(
			    info.Caster,
			    "ranged formation caster",
			    "battle.ranged-formation",
			    Homm3CustomFactionLawRuntime.RangedFormationIndex,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			casterClassification = default;
			return false;
		}
		return TryRequireFormationCasterFactAndTargets(
			info,
			requiredCasterFact,
			minimumAttackedObjects,
			minimumAttackedHexes,
			out casterClassification,
			out failReason);
	}

	internal static bool TryReadAllowedRangedFormationFirstRoundEventWithCasterFactAndTargets(
		object lawOwner,
		object eventArgs,
		Homm3UnitLawClassifier.FamilyFact requiredCasterFact,
		int minimumAttackedObjects,
		int minimumAttackedHexes,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3UnitLawClassifier.Classification casterClassification,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		if (!TryReadAllowedRangedFormationEvent(lawOwner, eventArgs, out info, out context, out failReason))
		{
			casterClassification = default;
			return false;
		}
		if (info.RoundNumber != 1)
		{
			casterClassification = default;
			failReason = "ranged formation event is not a first-round volley; round=" + info.RoundNumber;
			return false;
		}
		return TryRequireFormationCasterFactAndTargets(
			info,
			requiredCasterFact,
			minimumAttackedObjects,
			minimumAttackedHexes,
			out casterClassification,
			out failReason);
	}

	private static bool TryReadAllowedFormationEvent(
		object lawOwner,
		object eventArgs,
		string handlerKey,
		int lawIndex,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			handlerKey,
			lawIndex,
			out context,
			out failReason);
	}

	private static bool TryReadCandidateFormationEvent(
		object lawOwner,
		object eventArgs,
		string handlerKey,
		int lawIndex,
		out Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryProbeHandler(
			lawOwner,
			handlerKey,
			lawIndex,
			out context,
			out failReason);
	}

	private static bool TryEnterBattleObjectLawHandler(
		object battleObject,
		string battleObjectLabel,
		string handlerKey,
		int lawIndex,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		lawOwner = null;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    battleObject,
			    lawIndex,
			    out lawOwner,
			    out failReason))
		{
			failReason = battleObjectLabel + " law-owner resolution failed: " + failReason;
			return false;
		}
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			handlerKey,
			lawIndex,
			out context,
			out failReason);
	}

	private static bool TryRequireFormationCasterFactAndTargets(
		Homm3BattleEventNativeAdapter.CastAbilityEventInfo info,
		Homm3UnitLawClassifier.FamilyFact requiredCasterFact,
		int minimumAttackedObjects,
		int minimumAttackedHexes,
		out Homm3UnitLawClassifier.Classification casterClassification,
		out string failReason)
	{
		casterClassification = default;
		if (minimumAttackedObjects < 0 || minimumAttackedHexes < 0)
		{
			failReason = "formation target requirements cannot be negative";
			return false;
		}
		if (!Homm3UnitLawClassifier.TryRequireFamilyFact(
			    info.Caster,
			    requiredCasterFact,
			    out casterClassification,
			    out failReason))
		{
			return false;
		}
		if (info.AttackedObjectCount < minimumAttackedObjects)
		{
			failReason = "formation attacked object count " + info.AttackedObjectCount
			             + " is below required " + minimumAttackedObjects;
			return false;
		}
		if (info.AttackedHexCount < minimumAttackedHexes)
		{
			failReason = "formation attacked hex count " + info.AttackedHexCount
			             + " is below required " + minimumAttackedHexes;
			return false;
		}
		failReason = null;
		return true;
	}
}
