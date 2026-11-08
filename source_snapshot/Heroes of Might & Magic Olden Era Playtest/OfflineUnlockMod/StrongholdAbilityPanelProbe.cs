using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Quarantined legacy diagnostic for the pre-release selected-unit ability panel.
/// </summary>
internal static class StrongholdAbilityPanelProbe
{
	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		log?.LogInfo("StrongholdAbilityPanelProbe skipped: stale pre-release action-bar diagnostic is quarantined.");
	}
}
