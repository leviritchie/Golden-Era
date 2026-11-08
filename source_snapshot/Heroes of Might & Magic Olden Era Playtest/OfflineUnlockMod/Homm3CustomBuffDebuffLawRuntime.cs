namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated buff/debuff law read seam.
/// This class registers no Harmony hooks and does not mutate buffs. It only
/// lets future exact hooks require a proven native buff manager plus an exact
/// buff SID after the relevant law handler gate allows execution.
/// </summary>
internal static class Homm3CustomBuffDebuffLawRuntime
{
	internal static bool TryRequireAllowedBuffSid(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object buffManager,
		string buffSid,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(lawOwner, handlerKey, lawIndex, out context, out failReason))
			return false;
		return Homm3BuffDebuffNativeAdapter.TryRequireBuffSid(buffManager, buffSid, out info, out failReason);
	}

	internal static bool TryRequireAllowedBuffSidFromReceiver(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object receiver,
		string buffSid,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(lawOwner, handlerKey, lawIndex, out context, out failReason))
			return false;
		return Homm3BuffDebuffNativeAdapter.TryRequireBuffSidFromReceiver(receiver, buffSid, out info, out failReason);
	}

	internal static bool TryRequireAllowedBuffSidForReceiverLawOwner(
		string handlerKey,
		int lawIndex,
		object receiver,
		string buffSid,
		out object lawOwner,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		lawOwner = null;
		info = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(receiver, lawIndex, out lawOwner, out failReason))
		{
			failReason = "buff receiver law-owner resolution failed: " + failReason;
			return false;
		}
		return TryRequireAllowedBuffSidFromReceiver(
			lawOwner,
			handlerKey,
			lawIndex,
			receiver,
			buffSid,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAnyAllowedBuffSid(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object buffManager,
		string[] buffSids,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(lawOwner, handlerKey, lawIndex, out context, out failReason))
			return false;
		return Homm3BuffDebuffNativeAdapter.TryRequireAnyBuffSid(buffManager, buffSids, out info, out failReason);
	}

	internal static bool TryRequireAnyAllowedBuffSidFromReceiver(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object receiver,
		string[] buffSids,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(lawOwner, handlerKey, lawIndex, out context, out failReason))
			return false;
		return Homm3BuffDebuffNativeAdapter.TryRequireAnyBuffSidFromReceiver(receiver, buffSids, out info, out failReason);
	}

	internal static bool TryRequireAnyAllowedBuffSidForReceiverLawOwner(
		string handlerKey,
		int lawIndex,
		object receiver,
		string[] buffSids,
		out object lawOwner,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		lawOwner = null;
		info = default;
		context = default;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(receiver, lawIndex, out lawOwner, out failReason))
		{
			failReason = "buff receiver law-owner resolution failed: " + failReason;
			return false;
		}
		return TryRequireAnyAllowedBuffSidFromReceiver(
			lawOwner,
			handlerKey,
			lawIndex,
			receiver,
			buffSids,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedStatusTags(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object buffManager,
		string[] requiredTags,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!TryResolveStatusSidsForTags(requiredTags, out var statusSids, out failReason))
			return false;
		return TryRequireAnyAllowedBuffSid(
			lawOwner,
			handlerKey,
			lawIndex,
			buffManager,
			statusSids,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedStatusTagsFromReceiver(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object receiver,
		string[] requiredTags,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!TryResolveStatusSidsForTags(requiredTags, out var statusSids, out failReason))
			return false;
		return TryRequireAnyAllowedBuffSidFromReceiver(
			lawOwner,
			handlerKey,
			lawIndex,
			receiver,
			statusSids,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedStatusTagsForReceiverLawOwner(
		string handlerKey,
		int lawIndex,
		object receiver,
		string[] requiredTags,
		out object lawOwner,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		lawOwner = null;
		info = default;
		context = default;
		if (!TryResolveStatusSidsForTags(requiredTags, out var statusSids, out failReason))
			return false;
		return TryRequireAnyAllowedBuffSidForReceiverLawOwner(
			handlerKey,
			lawIndex,
			receiver,
			statusSids,
			out lawOwner,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedRampartAvengerMark(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object buffManager,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryRequireAnyAllowedBuffSid(
			lawOwner,
			handlerKey,
			lawIndex,
			buffManager,
			GameSymbols.RampartAvengerLaws.CustomMarkerBuffSids,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedRampartAvengerMarkFromReceiver(
		object lawOwner,
		string handlerKey,
		int lawIndex,
		object receiver,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryRequireAnyAllowedBuffSidFromReceiver(
			lawOwner,
			handlerKey,
			lawIndex,
			receiver,
			GameSymbols.RampartAvengerLaws.CustomMarkerBuffSids,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryRequireAllowedRampartAvengerMarkForReceiverLawOwner(
		string handlerKey,
		int lawIndex,
		object receiver,
		out object lawOwner,
		out Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryRequireAnyAllowedBuffSidForReceiverLawOwner(
			handlerKey,
			lawIndex,
			receiver,
			GameSymbols.RampartAvengerLaws.CustomMarkerBuffSids,
			out lawOwner,
			out info,
			out context,
			out failReason);
	}

	private static bool TryResolveStatusSidsForTags(string[] requiredTags, out string[] statusSids, out string failReason)
	{
		statusSids = null;
		if (requiredTags == null || requiredTags.Length == 0)
		{
			failReason = "required status taxonomy tags are empty";
			return false;
		}
		for (var i = 0; i < requiredTags.Length; i++)
		{
			if (string.IsNullOrWhiteSpace(requiredTags[i]))
			{
				failReason = "required status taxonomy tag is empty";
				return false;
			}
		}
		if (!Homm3StatusTaxonomyRegistry.TryGetSidsForAnyTag(requiredTags, out statusSids))
		{
			failReason = "status taxonomy has no entries for one or more required tags";
			return false;
		}
		failReason = null;
		return true;
	}
}
