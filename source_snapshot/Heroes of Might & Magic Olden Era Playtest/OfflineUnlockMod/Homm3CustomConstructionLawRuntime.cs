using System;

namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated construction law runtime entry points.
/// This class registers no Harmony hooks. Future exact construction commit
/// hooks must call this class only after runtime proof establishes commit
/// ordering between charged resources, constructed state, and the native daily
/// construction counter.
/// </summary>
internal static class Homm3CustomConstructionLawRuntime
{
	internal static bool TryGetAllowedConstructionProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "construction.commit",
			    Homm3CustomFactionLawRuntime.ExtraConstructionIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetConstructionProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateConstructionProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "construction.commit",
			    Homm3CustomFactionLawRuntime.ExtraConstructionIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetConstructionProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateConstructionEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateConstructionProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanConstructionEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedConstructionEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedConstructionProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanConstructionEffect(profile, out plan, out failReason);
	}

	internal static bool TryRefundConstructionCountByRank(object lawOwner, object buildingsData, out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "construction.commit",
			    Homm3CustomFactionLawRuntime.ExtraConstructionIndex,
			    out var context,
			    out failReason))
			return false;

		if (buildingsData == null)
		{
			failReason = "buildings data instance is null";
			return false;
		}

		if (!Homm3ConstructionNativeAdapter.TryReadTodaysConstructionCount(buildingsData, out var currentCount, out failReason))
			return false;
		if (currentCount <= 0)
		{
			failReason = "native daily construction count has no consumed build to refund";
			return false;
		}

		var refund = Math.Min(currentCount, Math.Max(1, context.Law.Rank));
		return Homm3ConstructionNativeAdapter.TrySetTodaysConstructionCount(buildingsData, currentCount - refund, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankForBuildingSid(
		object lawOwner,
		object buildingsData,
		object buildingData,
		string requiredBuildingSid,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireBuildingSid(buildingData, requiredBuildingSid, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRank(lawOwner, buildingsData, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankFromCityContext(
		object lawOwner,
		object cityContext,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryResolveBuildingsDataFromCityContext(cityContext, out var buildingsData, out failReason))
			return false;
		return TryRefundConstructionCountByRank(lawOwner, buildingsData, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankFromCityContext(
		object cityContext,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryResolveConstructionLawOwnerFromCityContext(cityContext, out var lawOwner, out failReason))
			return false;
		return TryRefundConstructionCountByRankFromCityContext(lawOwner, cityContext, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankForBuildingSidFromCityContext(
		object lawOwner,
		object cityContext,
		object buildingData,
		string requiredBuildingSid,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireBuildingSid(buildingData, requiredBuildingSid, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRankFromCityContext(lawOwner, cityContext, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankForBuildingSidFromCityContext(
		object cityContext,
		object buildingData,
		string requiredBuildingSid,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireBuildingSid(buildingData, requiredBuildingSid, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRankFromCityContext(cityContext, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankForAnyBuildingSid(
		object lawOwner,
		object buildingsData,
		object buildingData,
		string[] requiredBuildingSids,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireAnyBuildingSid(buildingData, requiredBuildingSids, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRank(lawOwner, buildingsData, out failReason);
	}

	internal static bool TryRequireProfileEligibleBuildingGroup(
		Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		object buildingData,
		out Homm3ConstructionNativeAdapter.BuildingIdentityInfo info,
		out Homm3ConstructionBuildingCategoryRegistry.Entry entry,
		out string failReason)
	{
		info = default;
		entry = default;
		if (!profile.RequiresBuildingAllowlist)
		{
			failReason = "construction profile does not require a building allowlist";
			return false;
		}
		if (string.IsNullOrWhiteSpace(profile.EligibleGroup))
		{
			failReason = "construction profile has no eligible group";
			return false;
		}
		if (!Homm3ConstructionNativeAdapter.TryReadBuildingIdentity(buildingData, out info, out failReason))
			return false;
		if (!Homm3ConstructionBuildingCategoryRegistry.TryGet(profile.FactionSid, info.Sid, out entry))
		{
			failReason = "building SID has no static construction category contract for faction "
			             + (profile.FactionSid ?? "null")
			             + ": "
			             + (info.Sid ?? "null");
			return false;
		}

		var groups = profile.EligibleGroup.Split(',');
		for (var i = 0; i < groups.Length; i++)
		{
			var group = groups[i].Trim();
			if (group.Length == 0)
				continue;
			if (string.Equals(entry.Group, group, StringComparison.Ordinal))
			{
				failReason = null;
				return true;
			}
		}

		failReason = "building category mismatch: profile groups "
		             + profile.EligibleGroup
		             + " actual "
		             + entry.Group
		             + " source "
		             + entry.SourceMechanicId;
		return false;
	}

	internal static bool TryRefundConstructionCountByRankForAnyBuildingSidFromCityContext(
		object lawOwner,
		object cityContext,
		object buildingData,
		string[] requiredBuildingSids,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireAnyBuildingSid(buildingData, requiredBuildingSids, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRankFromCityContext(lawOwner, cityContext, out failReason);
	}

	internal static bool TryRefundConstructionCountByRankForAnyBuildingSidFromCityContext(
		object cityContext,
		object buildingData,
		string[] requiredBuildingSids,
		out string failReason)
	{
		if (!Homm3ConstructionNativeAdapter.TryRequireAnyBuildingSid(buildingData, requiredBuildingSids, out _, out failReason))
			return false;
		return TryRefundConstructionCountByRankFromCityContext(cityContext, out failReason);
	}
}
