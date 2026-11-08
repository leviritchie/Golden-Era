using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Quarantine shim for the old battle attack command diagnostic probe.
/// The broad probe was useful for May 2026 traces but is unsafe as a standing
/// compile dependency on generated obfuscated wrappers.
/// </summary>
internal static class Homm3BattleAttackCommandProbe
{
	private const string FlagFileName = "homm3_battle_attack_command_probe.flag";

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (Homm3DiagnosticFlags.IsEnabled(FlagFileName))
			log?.LogWarning("Homm3BattleAttackCommandProbe skipped: stale broad command probe is quarantined pending retrace.");
	}
}
