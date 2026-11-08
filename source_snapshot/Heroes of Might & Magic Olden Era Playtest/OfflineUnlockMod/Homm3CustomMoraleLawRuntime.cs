using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated morale law runtime entry points.
/// This class registers no Harmony hooks and does not alter morale rolls,
/// action queues, or unit state. Future exact morale-roll hooks must call this
/// only after runtime proof distinguishes trigger, check, positive, and
/// negative morale phases.
/// </summary>
internal static class Homm3CustomMoraleLawRuntime
{
	internal static bool TryGetAllowedMoralePackageProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.MoralePackageProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "morale.package",
			    Homm3CustomFactionLawRuntime.MoraleFlatIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetMoralePackageProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateMoralePackageProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.MoralePackageProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "morale.package",
			    Homm3CustomFactionLawRuntime.MoraleFlatIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetMoralePackageProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateMoralePackageEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.MoralePackageProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateMoralePackageProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanMoralePackageEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedMoralePackageEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.MoralePackageProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedMoralePackageProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanMoralePackageEffect(profile, out plan, out failReason);
	}

	internal static bool TryClassifyAllowedMoraleRoll(
		object lawOwner,
		MethodBase moraleMethod,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollKind kind,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		kind = Homm3MoraleTriggerNativeAdapter.MoraleRollKind.Unknown;
		context = default;
		if (!Homm3MoraleTriggerNativeAdapter.TryClassifyRoll(moraleMethod, out kind, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"morale.trigger",
			Homm3CustomFactionLawRuntime.MoraleTriggerIndex,
			out context,
			out failReason);
	}

	internal static bool TryClassifyAllowedMoraleRollForUnit(
		object unit,
		MethodBase moraleMethod,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollKind kind,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		kind = Homm3MoraleTriggerNativeAdapter.MoraleRollKind.Unknown;
		lawOwner = null;
		context = default;
		if (unit == null)
		{
			failReason = "morale unit is null";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    unit,
			    Homm3CustomFactionLawRuntime.MoraleTriggerIndex,
			    out lawOwner,
			    out failReason))
		{
			failReason = "morale unit law-owner resolution failed: " + failReason;
			return false;
		}
		return TryClassifyAllowedMoraleRoll(lawOwner, moraleMethod, out kind, out context, out failReason);
	}

	internal static bool TryClassifyCandidateMoraleRollForUnit(
		object unit,
		MethodBase moraleMethod,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollKind kind,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		kind = Homm3MoraleTriggerNativeAdapter.MoraleRollKind.Unknown;
		lawOwner = null;
		context = default;
		if (unit == null)
		{
			failReason = "morale unit is null";
			return false;
		}
		if (!Homm3MoraleTriggerNativeAdapter.TryClassifyRoll(moraleMethod, out kind, out failReason))
			return false;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    unit,
			    Homm3CustomFactionLawRuntime.MoraleTriggerIndex,
			    out lawOwner,
			    out failReason))
		{
			failReason = "morale unit law-owner resolution failed: " + failReason;
			return false;
		}
		return Homm3CustomLawHandlerRegistry.TryProbeHandler(
			lawOwner,
			"morale.trigger",
			Homm3CustomFactionLawRuntime.MoraleTriggerIndex,
			out context,
			out failReason);
	}

	internal static bool TryClassifyAllowedMoraleRollForUnitWithFact(
		object unit,
		MethodBase moraleMethod,
		Homm3UnitLawClassifier.FamilyFact requiredUnitFact,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollKind kind,
		out Homm3UnitLawClassifier.Classification unitClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		unitClassification = default;
		if (!TryClassifyAllowedMoraleRollForUnit(
			    unit,
			    moraleMethod,
			    out kind,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			unit,
			requiredUnitFact,
			out unitClassification,
			out failReason);
	}

	internal static bool TryObserveAllowedMoraleRollResultForUnit(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		observation = default;
		lawOwner = null;
		context = default;
		if (!TryClassifyAllowedMoraleRollForUnit(
			    unit,
			    moraleMethod,
			    out _,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3MoraleTriggerNativeAdapter.TryObserveRollResult(
			moraleMethod,
			rollResult,
			out observation,
			out failReason);
	}

	internal static bool TryObserveAllowedMoraleRollResultForUnitWithFact(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		Homm3UnitLawClassifier.FamilyFact requiredUnitFact,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3UnitLawClassifier.Classification unitClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		unitClassification = default;
		if (!TryObserveAllowedMoraleRollResultForUnit(
			    unit,
			    moraleMethod,
			    rollResult,
			    out observation,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3UnitLawClassifier.TryRequireFamilyFact(
			unit,
			requiredUnitFact,
			out unitClassification,
			out failReason);
	}

	internal static bool TryGetAllowedMoraleTriggerProfileForUnit(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryObserveAllowedMoraleRollResultForUnit(
			    unit,
			    moraleMethod,
			    rollResult,
			    out observation,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetMoraleTriggerProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			observation,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateMoraleTriggerProfileForUnit(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		observation = default;
		profile = default;
		if (!TryClassifyCandidateMoraleRollForUnit(
			    unit,
			    moraleMethod,
			    out _,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		if (!Homm3MoraleTriggerNativeAdapter.TryObserveRollResult(
			    moraleMethod,
			    rollResult,
			    out observation,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetMoraleTriggerProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			observation,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateMoraleTriggerEffectForUnit(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateMoraleTriggerProfileForUnit(
			    unit,
			    moraleMethod,
			    rollResult,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanMoraleTriggerEffect(profile, observation, out plan, out failReason);
	}

	internal static bool TryPlanAllowedMoraleTriggerEffectForUnit(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedMoraleTriggerProfileForUnit(
			    unit,
			    moraleMethod,
			    rollResult,
			    out observation,
			    out profile,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectPlans.TryPlanMoraleTriggerEffect(profile, observation, out plan, out failReason);
	}

	internal static bool TryGetAllowedMoraleTriggerProfileForUnitWithFact(
		object unit,
		MethodBase moraleMethod,
		bool rollResult,
		Homm3UnitLawClassifier.FamilyFact requiredUnitFact,
		out Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		out Homm3UnitLawClassifier.Classification unitClassification,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryObserveAllowedMoraleRollResultForUnitWithFact(
			    unit,
			    moraleMethod,
			    rollResult,
			    requiredUnitFact,
			    out observation,
			    out unitClassification,
			    out lawOwner,
			    out context,
			    out failReason))
		{
			return false;
		}
		return Homm3CustomLawEffectProfiles.TryGetMoraleTriggerProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			observation,
			out profile,
			out failReason);
	}
}
