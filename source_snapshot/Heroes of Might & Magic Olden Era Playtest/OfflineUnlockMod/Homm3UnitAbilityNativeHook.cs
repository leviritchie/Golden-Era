using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Quarantine shim for the old pre-release unit ability wrapper hook.
/// Current Steam builds use the selected-HUD recovery path instead.
/// </summary>
internal static class Homm3UnitAbilityNativeHook
{
	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		log?.LogInfo("Homm3UnitAbilityNativeHook skipped: stale pre-release wrapper path is quarantined.");
	}
}
