using System;

namespace OfflineUnlockMod;

/// <summary>
/// Fail-closed allowlist for Golden Era StoryHub continuity campaign maps (RoE + AB/SoD).
/// Derives from GameSymbols.RoeCastleCampaignMaps (installer mapInstalls SIDs).
/// </summary>
internal static class RoeCastleCampaignMapRegistry
{
	internal static bool IsStoryHubPlayableMap(string fileMapName)
	{
		if (string.IsNullOrWhiteSpace(fileMapName))
			return false;
		var sid = fileMapName.Trim();
		foreach (var candidate in GameSymbols.RoeCastleCampaignMaps.StoryHubPlayableMapSids)
		{
			if (string.Equals(sid, candidate, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}
