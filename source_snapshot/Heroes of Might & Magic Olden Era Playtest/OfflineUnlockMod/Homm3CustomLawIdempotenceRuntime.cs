using System.Collections.Generic;
using System.Globalization;

namespace OfflineUnlockMod;

/// <summary>
/// Session-local idempotence keys for source-prepared custom law seams.
/// This is not persistence and not gameplay proof. Callers must still supply
/// exact native identity evidence before reserving a key.
/// </summary>
internal static class Homm3CustomLawIdempotenceRuntime
{
	private static readonly object Sync = new();
	private static readonly HashSet<string> AppliedKeys = new(System.StringComparer.Ordinal);

	internal static bool TryBeginRewardGrant(
		string handlerKey,
		int lawIndex,
		int rank,
		Homm3RewardEconomyNativeAdapter.RewardSetIdentityInfo rewardSet,
		string grantKind,
		int amount,
		out string key,
		out string failReason)
	{
		key = null;
		if (string.IsNullOrWhiteSpace(handlerKey))
		{
			failReason = "idempotence handler key is empty";
			return false;
		}
		if (lawIndex <= 0)
		{
			failReason = "idempotence law index is invalid";
			return false;
		}
		if (rank <= 0)
		{
			failReason = "idempotence rank is invalid";
			return false;
		}
		if (string.IsNullOrWhiteSpace(grantKind))
		{
			failReason = "idempotence grant kind is empty";
			return false;
		}
		if (amount <= 0)
		{
			failReason = "idempotence amount is invalid";
			return false;
		}
		if (rewardSet.Id == 0 && rewardSet.HeroId == 0 && rewardSet.ObjectId == 0 && string.IsNullOrWhiteSpace(rewardSet.Label))
		{
			failReason = "reward set identity is too weak for idempotence";
			return false;
		}

		key = handlerKey
		      + "|law=" + lawIndex.ToString(CultureInfo.InvariantCulture)
		      + "|rank=" + rank.ToString(CultureInfo.InvariantCulture)
		      + "|kind=" + grantKind
		      + "|amount=" + amount.ToString(CultureInfo.InvariantCulture)
		      + "|rewardId=" + rewardSet.Id.ToString(CultureInfo.InvariantCulture)
		      + "|heroId=" + rewardSet.HeroId.ToString(CultureInfo.InvariantCulture)
		      + "|objectId=" + rewardSet.ObjectId.ToString(CultureInfo.InvariantCulture)
		      + "|label=" + (rewardSet.Label ?? "");

		lock (Sync)
		{
			if (AppliedKeys.Contains(key))
			{
				failReason = "custom law idempotence key already applied: " + key;
				return false;
			}
			AppliedKeys.Add(key);
		}

		failReason = null;
		return true;
	}

	internal static void RollBack(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return;
		lock (Sync)
		{
			AppliedKeys.Remove(key);
		}
	}

	internal static bool TryBeginVisionObject(
		string handlerKey,
		int lawIndex,
		int rank,
		Homm3AdventureVisionNativeAdapter.DataObjectIdentityInfo dataObject,
		int side,
		string action,
		out string key,
		out string failReason)
	{
		key = null;
		if (string.IsNullOrWhiteSpace(handlerKey))
		{
			failReason = "vision idempotence handler key is empty";
			return false;
		}
		if (lawIndex <= 0)
		{
			failReason = "vision idempotence law index is invalid";
			return false;
		}
		if (rank <= 0)
		{
			failReason = "vision idempotence rank is invalid";
			return false;
		}
		if (dataObject.ObjectId == 0 && string.IsNullOrWhiteSpace(dataObject.ConfigSid))
		{
			failReason = "data object identity is too weak for vision idempotence";
			return false;
		}
		if (string.IsNullOrWhiteSpace(action))
		{
			failReason = "vision idempotence action is empty";
			return false;
		}

		key = handlerKey
		      + "|law=" + lawIndex.ToString(CultureInfo.InvariantCulture)
		      + "|rank=" + rank.ToString(CultureInfo.InvariantCulture)
		      + "|action=" + action
		      + "|side=" + side.ToString(CultureInfo.InvariantCulture)
		      + "|objectId=" + dataObject.ObjectId.ToString(CultureInfo.InvariantCulture)
		      + "|configSid=" + (dataObject.ConfigSid ?? "");

		lock (Sync)
		{
			if (AppliedKeys.Contains(key))
			{
				failReason = "custom law vision idempotence key already applied: " + key;
				return false;
			}
			AppliedKeys.Add(key);
		}

		failReason = null;
		return true;
	}
}
