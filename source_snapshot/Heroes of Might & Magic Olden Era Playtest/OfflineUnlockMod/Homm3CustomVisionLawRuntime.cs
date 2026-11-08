namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated vision law runtime entry points.
/// This class registers no Harmony hooks and does not classify map objects or
/// mutate fog tiles. Future exact adventure-map hooks must pass an already
/// classified native DataObject and side after object/side/idempotence proof.
/// </summary>
internal static class Homm3CustomVisionLawRuntime
{
	internal static bool TryMarkObjectScoutedBySide(object lawOwner, object dataObject, int side, out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    out var context,
			    out failReason))
			return false;

		return Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason);
	}

	internal static bool TryMarkObjectScoutedByActiveLawSide(object lawOwner, object dataObject, out string failReason)
	{
		if (!TryResolveVisionLawSide(lawOwner, out _, out var side, out failReason))
			return false;
		return Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason);
	}

	internal static bool TryMarkObjectScoutedBySideOnceForConfigSid(
		object lawOwner,
		object dataObject,
		int side,
		string requiredConfigSid,
		out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    out var context,
			    out failReason))
			return false;
		if (!Homm3AdventureVisionNativeAdapter.TryRequireDataObjectConfigSid(dataObject, requiredConfigSid, out var identity, out failReason))
			return false;
		if (!Homm3CustomLawIdempotenceRuntime.TryBeginVisionObject(
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    context.Law.Rank,
			    identity,
			    side,
			    "scout",
			    out var idempotenceKey,
			    out failReason))
			return false;

		if (Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason))
			return true;

		Homm3CustomLawIdempotenceRuntime.RollBack(idempotenceKey);
		return false;
	}

	internal static bool TryMarkObjectScoutedByActiveLawSideOnceForConfigSid(
		object lawOwner,
		object dataObject,
		string requiredConfigSid,
		out string failReason)
	{
		if (!TryResolveVisionLawSide(lawOwner, out var context, out var side, out failReason))
			return false;
		if (!Homm3AdventureVisionNativeAdapter.TryRequireDataObjectConfigSid(dataObject, requiredConfigSid, out var identity, out failReason))
			return false;
		if (!Homm3CustomLawIdempotenceRuntime.TryBeginVisionObject(
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    context.Law.Rank,
			    identity,
			    side,
			    "scout",
			    out var idempotenceKey,
			    out failReason))
			return false;

		if (Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason))
			return true;

		Homm3CustomLawIdempotenceRuntime.RollBack(idempotenceKey);
		return false;
	}

	internal static bool TryMarkObjectScoutedBySideOnceForAnyConfigSid(
		object lawOwner,
		object dataObject,
		int side,
		string[] requiredConfigSids,
		out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    out var context,
			    out failReason))
			return false;
		if (!Homm3AdventureVisionNativeAdapter.TryRequireAnyDataObjectConfigSid(dataObject, requiredConfigSids, out var identity, out failReason))
			return false;
		if (!Homm3CustomLawIdempotenceRuntime.TryBeginVisionObject(
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    context.Law.Rank,
			    identity,
			    side,
			    "scout",
			    out var idempotenceKey,
			    out failReason))
			return false;

		if (Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason))
			return true;

		Homm3CustomLawIdempotenceRuntime.RollBack(idempotenceKey);
		return false;
	}

	internal static bool TryMarkObjectScoutedByActiveLawSideOnceForAnyConfigSid(
		object lawOwner,
		object dataObject,
		string[] requiredConfigSids,
		out string failReason)
	{
		if (!TryResolveVisionLawSide(lawOwner, out var context, out var side, out failReason))
			return false;
		if (!Homm3AdventureVisionNativeAdapter.TryRequireAnyDataObjectConfigSid(dataObject, requiredConfigSids, out var identity, out failReason))
			return false;
		if (!Homm3CustomLawIdempotenceRuntime.TryBeginVisionObject(
			    "vision.reveal",
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    context.Law.Rank,
			    identity,
			    side,
			    "scout",
			    out var idempotenceKey,
			    out failReason))
			return false;

		if (Homm3AdventureVisionNativeAdapter.TryMarkObjectScoutedBySide(dataObject, side, out failReason))
			return true;

		Homm3CustomLawIdempotenceRuntime.RollBack(idempotenceKey);
		return false;
	}

	internal static bool TryGetAllowedVisionProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.VisionProfile profile,
		out string failReason)
	{
		profile = default;
		if (!TryResolveVisionLawSide(lawOwner, out var context, out _, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetVisionProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanAllowedVisionEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.VisionProfile profile,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryResolveVisionLawSide(lawOwner, out var context, out var side, out failReason))
		{
			profile = default;
			return false;
		}
		if (!Homm3CustomLawEffectProfiles.TryGetVisionProfile(context.Law.FactionSid, context.Law.Rank, out profile, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanVisionEffect(profile, side, out plan, out failReason);
	}

	internal static bool TryGetCandidateVisionProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.VisionProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out int side,
		out string failReason)
	{
		profile = default;
		if (!TryResolveCandidateVisionLawSide(lawOwner, out context, out side, out failReason))
			return false;
		return Homm3CustomLawEffectProfiles.TryGetVisionProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateVisionEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.VisionProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out int side,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateVisionProfile(lawOwner, out profile, out context, out side, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanVisionEffect(profile, side, out plan, out failReason);
	}

	internal static bool TryRequireProfileOwnedStructureOrigin(
		Homm3CustomLawEffectProfiles.VisionProfile profile,
		object dataObject,
		int requiredOwnerSide,
		out Homm3AdventureVisionNativeAdapter.DataObjectIdentityInfo identity,
		out Homm3AdventureOwnedStructureRegistry.Entry entry,
		out string failReason)
	{
		identity = default;
		entry = default;
		if (!profile.RequiresOwnedStructureRadius)
		{
			failReason = "vision profile does not require owned-structure radius";
			return false;
		}
		if (!Homm3AdventureVisionNativeAdapter.TryReadDataObjectIdentity(dataObject, out identity, out failReason))
			return false;
		if (identity.OwnerSide != requiredOwnerSide)
		{
			failReason = "owned structure side mismatch: expected "
			             + requiredOwnerSide
			             + " actual "
			             + identity.OwnerSide;
			return false;
		}
		if (!Homm3AdventureOwnedStructureRegistry.TryClassify(identity.ConfigSid, out entry))
		{
			failReason = "data object config SID is not a generated custom adventure structure: "
			             + (identity.ConfigSid ?? "null");
			return false;
		}
		if (!string.Equals(entry.FactionSid, profile.FactionSid, System.StringComparison.Ordinal))
		{
			failReason = "owned structure faction mismatch: expected "
			             + (profile.FactionSid ?? "null")
			             + " actual "
			             + (entry.FactionSid ?? "null");
			return false;
		}

		failReason = null;
		return true;
	}

	private static bool TryResolveVisionLawSide(
		object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out int side,
		out string failReason)
	{
		context = default;
		side = -1;
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawSideIndex(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    out _,
			    out side))
		{
			failReason = "vision law owner did not resolve active custom law side index";
			return false;
		}
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"vision.reveal",
			Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			out context,
			out failReason);
	}

	private static bool TryResolveCandidateVisionLawSide(
		object lawOwner,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out int side,
		out string failReason)
	{
		context = default;
		side = -1;
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawSideIndex(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			    out _,
			    out side))
		{
			failReason = "vision law owner did not resolve active custom law side index";
			return false;
		}
		return Homm3CustomLawHandlerRegistry.TryProbeHandler(
			lawOwner,
			"vision.reveal",
			Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			out context,
			out failReason);
	}
}
