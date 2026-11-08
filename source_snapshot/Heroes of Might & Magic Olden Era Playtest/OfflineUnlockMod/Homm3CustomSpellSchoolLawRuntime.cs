namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated spell school/access law runtime entry points.
/// This class registers no Harmony hooks and mutates no spellbook, cast gate,
/// cooldown, or UI state. Future exact spellbook/cast hooks must call this
/// only after runtime proof establishes access, cast ordering, and UI sync.
/// </summary>
internal static class Homm3CustomSpellSchoolLawRuntime
{
	internal static bool TryGetAllowedLowSpellSchoolProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryGetAllowedSpellSchoolProfile(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out profile,
			out context,
			out failReason);
	}

	internal static bool TryGetAllowedHighSpellSchoolProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryGetAllowedSpellSchoolProfile(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out profile,
			out context,
			out failReason);
	}

	internal static bool TryGetCandidateLowSpellSchoolProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		return TryGetCandidateSpellSchoolProfile(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out profile,
			out context,
			out failReason);
	}

	internal static bool TryGetCandidateHighSpellSchoolProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		return TryGetCandidateSpellSchoolProfile(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out profile,
			out context,
			out failReason);
	}

	internal static bool TryPlanCandidateLowSpellSchoolEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		return TryPlanCandidateSpellSchoolEffect(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out profile,
			out context,
			out plan,
			out failReason);
	}

	internal static bool TryPlanCandidateHighSpellSchoolEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		return TryPlanCandidateSpellSchoolEffect(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out profile,
			out context,
			out plan,
			out failReason);
	}

	internal static bool TryPlanAllowedLowSpellSchoolEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		return TryPlanAllowedSpellSchoolEffect(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out profile,
			out context,
			out plan,
			out failReason);
	}

	internal static bool TryPlanAllowedHighSpellSchoolEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		return TryPlanAllowedSpellSchoolEffect(
			lawOwner,
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out profile,
			out context,
			out plan,
			out failReason);
	}

	internal static bool TryGetAllowedSpellSchoolProfile(
		object lawOwner,
		int lawIndex,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!TryGetHandlerKey(lawIndex, out var handlerKey, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    handlerKey,
			    lawIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetSpellSchoolProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			lawIndex,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateSpellSchoolProfile(
		object lawOwner,
		int lawIndex,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!TryGetHandlerKey(lawIndex, out var handlerKey, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    handlerKey,
			    lawIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetSpellSchoolProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			lawIndex,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateSpellSchoolEffect(
		object lawOwner,
		int lawIndex,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateSpellSchoolProfile(lawOwner, lawIndex, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanSpellSchoolEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedSpellSchoolEffect(
		object lawOwner,
		int lawIndex,
		out Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedSpellSchoolProfile(lawOwner, lawIndex, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanSpellSchoolEffect(profile, out plan, out failReason);
	}

	private static bool TryGetHandlerKey(int lawIndex, out string handlerKey, out string failReason)
	{
		if (lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex)
		{
			handlerKey = "spell.low";
			failReason = null;
			return true;
		}
		if (lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex)
		{
			handlerKey = "spell.high";
			failReason = null;
			return true;
		}

		handlerKey = null;
		failReason = "spell school runtime requires law index 15 or 27";
		return false;
	}
}
