using System;

namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated reward/calendar economy runtime entry points.
/// This class registers no Harmony hooks and does not classify rewards,
/// captures, or resources. Future exact reward/calendar hooks must pass an
/// already-proven native resource object and amount after idempotent commit
/// identity has been established.
/// </summary>
internal static class Homm3CustomRewardEconomyLawRuntime
{
	internal static bool TryGetAllowedGoldEconomyProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "reward.gold-economy",
			    Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"reward.gold-economy",
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateGoldEconomyProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "reward.gold-economy",
			    Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"reward.gold-economy",
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateGoldEconomyEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateGoldEconomyProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanRewardEconomyEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedGoldEconomyEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedGoldEconomyProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanRewardEconomyEffect(profile, out plan, out failReason);
	}

	internal static bool TryGetAllowedCalendarProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.CalendarProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "reward.calendar",
			    Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetCalendarProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateCalendarProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.CalendarProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "reward.calendar",
			    Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetCalendarProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateCalendarEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.CalendarProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateCalendarProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanCalendarEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedCalendarEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.CalendarProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedCalendarProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanCalendarEffect(profile, out plan, out failReason);
	}

	internal static bool TryAddGoldEconomyGrant(object lawOwner, object goldResourceData, int amount, out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryRequireGoldResource(goldResourceData, out _, out failReason))
			return false;
		return TryAddResourceGrant(
			lawOwner,
			goldResourceData,
			amount,
			"reward.gold-economy",
			Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			out failReason);
	}

	internal static bool TryAddGoldEconomyGrantFromSide(object lawOwner, object sideOrResHeap, int amount, out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(sideOrResHeap, out var goldResourceData, out _, out failReason))
			return false;
		return TryAddGoldEconomyGrant(lawOwner, goldResourceData, amount, out failReason);
	}

	internal static bool TryAddGoldEconomyGrantFromActiveLawSide(object lawOwner, int amount, out string failReason)
	{
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawDataSide(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			    out _,
			    out var dataSide))
		{
			failReason = "gold economy law owner did not resolve active custom law data side";
			return false;
		}
		return TryAddGoldEconomyGrantFromSide(lawOwner, dataSide, amount, out failReason);
	}

	internal static bool TryAddGoldEconomyGrantOnceForRewardSet(
		object lawOwner,
		object rewardSet,
		object goldResourceData,
		int amount,
		out string failReason)
	{
		return TryAddGoldGrantOnceForRewardSet(
			lawOwner,
			rewardSet,
			goldResourceData,
			amount,
			"reward.gold-economy",
			Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			"gold-economy",
			out failReason);
	}

	internal static bool TryAddGoldEconomyGrantOnceForRewardSetFromSide(
		object lawOwner,
		object rewardSet,
		object sideOrResHeap,
		int amount,
		out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(sideOrResHeap, out var goldResourceData, out _, out failReason))
			return false;
		return TryAddGoldEconomyGrantOnceForRewardSet(lawOwner, rewardSet, goldResourceData, amount, out failReason);
	}

	internal static bool TryAddGoldEconomyGrantOnceForRewardSetFromActiveLawSide(
		object lawOwner,
		object rewardSet,
		int amount,
		out string failReason)
	{
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawDataSide(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			    out _,
			    out var dataSide))
		{
			failReason = "gold economy law owner did not resolve active custom law data side";
			return false;
		}
		return TryAddGoldEconomyGrantOnceForRewardSetFromSide(lawOwner, rewardSet, dataSide, amount, out failReason);
	}

	internal static bool TryAddCalendarGrant(object lawOwner, object goldResourceData, int amount, out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryRequireGoldResource(goldResourceData, out _, out failReason))
			return false;
		return TryAddResourceGrant(
			lawOwner,
			goldResourceData,
			amount,
			"reward.calendar",
			Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			out failReason);
	}

	internal static bool TryAddCalendarGrantFromSide(object lawOwner, object sideOrResHeap, int amount, out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(sideOrResHeap, out var goldResourceData, out _, out failReason))
			return false;
		return TryAddCalendarGrant(lawOwner, goldResourceData, amount, out failReason);
	}

	internal static bool TryAddCalendarGrantFromActiveLawSide(object lawOwner, int amount, out string failReason)
	{
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawDataSide(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			    out _,
			    out var dataSide))
		{
			failReason = "calendar law owner did not resolve active custom law data side";
			return false;
		}
		return TryAddCalendarGrantFromSide(lawOwner, dataSide, amount, out failReason);
	}

	internal static bool TryAddCalendarGrantOnceForRewardSet(
		object lawOwner,
		object rewardSet,
		object goldResourceData,
		int amount,
		out string failReason)
	{
		return TryAddGoldGrantOnceForRewardSet(
			lawOwner,
			rewardSet,
			goldResourceData,
			amount,
			"reward.calendar",
			Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			"calendar",
			out failReason);
	}

	internal static bool TryAddCalendarGrantOnceForRewardSetFromSide(
		object lawOwner,
		object rewardSet,
		object sideOrResHeap,
		int amount,
		out string failReason)
	{
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(sideOrResHeap, out var goldResourceData, out _, out failReason))
			return false;
		return TryAddCalendarGrantOnceForRewardSet(lawOwner, rewardSet, goldResourceData, amount, out failReason);
	}

	internal static bool TryAddCalendarGrantOnceForRewardSetFromActiveLawSide(
		object lawOwner,
		object rewardSet,
		int amount,
		out string failReason)
	{
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawDataSide(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			    out _,
			    out var dataSide))
		{
			failReason = "calendar law owner did not resolve active custom law data side";
			return false;
		}
		return TryAddCalendarGrantOnceForRewardSetFromSide(lawOwner, rewardSet, dataSide, amount, out failReason);
	}

	internal static bool TryReadAllowedGoldEconomyRewardSet(
		object lawOwner,
		object rewardSet,
		out Homm3RewardEconomyNativeAdapter.RewardSetIdentityInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3RewardEconomyNativeAdapter.TryReadRewardSetIdentity(rewardSet, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"reward.gold-economy",
			Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedGoldEconomyRewardSetProfile(
		object lawOwner,
		object rewardSet,
		out Homm3RewardEconomyNativeAdapter.RewardSetIdentityInfo info,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadAllowedGoldEconomyRewardSet(lawOwner, rewardSet, out info, out context, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"reward.gold-economy",
			out profile,
			out failReason);
	}

	internal static bool TryReadAllowedCalendarRewardSet(
		object lawOwner,
		object rewardSet,
		out Homm3RewardEconomyNativeAdapter.RewardSetIdentityInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3RewardEconomyNativeAdapter.TryReadRewardSetIdentity(rewardSet, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"reward.calendar",
			Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			out context,
			out failReason);
	}

	internal static bool TryReadAllowedCalendarRewardSetProfile(
		object lawOwner,
		object rewardSet,
		out Homm3RewardEconomyNativeAdapter.RewardSetIdentityInfo info,
		out Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		if (!TryReadAllowedCalendarRewardSet(lawOwner, rewardSet, out info, out context, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			"reward.calendar",
			out profile,
			out failReason);
	}

	private static bool TryAddResourceGrant(
		object lawOwner,
		object resourceData,
		int amount,
		string handlerKey,
		int lawIndex,
		out string failReason)
	{
		if (amount <= 0)
		{
			failReason = "resource grant amount must be positive";
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    handlerKey,
			    lawIndex,
			    out _,
			    out failReason))
			return false;
		return Homm3RewardEconomyNativeAdapter.TryAddResourceValue(resourceData, amount, out failReason);
	}

	private static bool TryAddGoldGrantOnceForRewardSet(
		object lawOwner,
		object rewardSet,
		object goldResourceData,
		int amount,
		string handlerKey,
		int lawIndex,
		string grantKind,
		out string failReason)
	{
		if (amount <= 0)
		{
			failReason = "resource grant amount must be positive";
			return false;
		}
		if (!Homm3RewardEconomyNativeAdapter.TryReadRewardSetIdentity(rewardSet, out var rewardIdentity, out failReason))
			return false;
		if (!Homm3RewardEconomyNativeAdapter.TryRequireGoldResource(goldResourceData, out _, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    handlerKey,
			    lawIndex,
			    out var context,
			    out failReason))
			return false;

		if (!Homm3CustomLawIdempotenceRuntime.TryBeginRewardGrant(
			    handlerKey,
			    lawIndex,
			    context.Law.Rank,
			    rewardIdentity,
			    grantKind,
			    amount,
			    out var idempotenceKey,
			    out failReason))
			return false;

		if (Homm3RewardEconomyNativeAdapter.TryAddResourceValue(goldResourceData, amount, out failReason))
			return true;

		Homm3CustomLawIdempotenceRuntime.RollBack(idempotenceKey);
		return false;
	}
}
