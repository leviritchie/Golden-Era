using BepInEx.Logging;

namespace OfflineUnlockMod;

/// <summary>
/// Launch-time hygiene audit for source-prepared custom law packet hooks.
/// This is intentionally not a proof promotion. It reports packet proof gate state and hook registration
/// state so prepared code cannot be mistaken for active implementation.
/// </summary>
internal static class Homm3CustomLawGameplayRegistrationAudit
{
	private static bool _ran;

	internal static void TryRun(ManualLogSource log)
	{
		if (_ran)
			return;
		_ran = true;

		log?.LogWarning(
			"HoMM3 custom law packet gate audit: generated packet proofs remain authoritative; this is a launch-time implementation audit only.");

		Report(log, Homm3CustomLawPacketGate.CommittedDamage, "STARTUP_HOOK_AUDIT", Homm3TrainingDamageLawRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.Counterattack, "STARTUP_RUNTIME_AUDIT", Homm3CounterattackDoctrineMutationRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.SpellCooldown, "STARTUP_RUNTIME_AUDIT", Homm3CustomSpellCooldownLawRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.BattleAction, "STARTUP_RUNTIME_AUDIT", Homm3BattleActionLawRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.RewardResult, "STARTUP_RUNTIME_AUDIT", Homm3SquadValueEconomyLawRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.Morale, "STARTUP_RUNTIME_AUDIT", Homm3MoraleTriggerLawRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.CommittedDamage, "STARTUP_HOOK_AUDIT", "rampartAvengerMarker=" + Homm3RampartAvengerMarkerRuntime.RegistrationAuditStatus);
		Report(log, Homm3CustomLawPacketGate.Vision, "INTENTIONALLY_BLOCKED", "Vision laws remain blocked unless packet proof is promoted or a diagnostic flag explicitly registers observation hooks.");
		Report(log, Homm3CustomLawPacketGate.Construction, "INTENTIONALLY_BLOCKED", "Construction laws remain blocked unless packet proof is promoted or a diagnostic flag explicitly registers observation hooks.");
	}

	private static void Report(ManualLogSource log, string packet, string registrationState, string detail)
	{
		var gateOpen = Homm3CustomLawPacketGate.IsGameplayAllowed(packet, out var failReason);
		var level = gateOpen && (registrationState == "HELPER_ONLY_NO_STARTUP_GAMEPLAY_HOOK" || registrationState == "NO_RUNTIME_IMPLEMENTATION_REGISTERED" || detail.StartsWith("FAILED_CLOSED", System.StringComparison.Ordinal) || detail.StartsWith("BLOCKED_BY_PACKET_GATE", System.StringComparison.Ordinal) || detail.StartsWith("NOT_ATTEMPTED", System.StringComparison.Ordinal))
			? "WARN"
			: "INFO";
		var message = "HoMM3 custom law gameplay audit: packet="
			+ packet
			+ " gateOpen="
			+ gateOpen
			+ " registration="
			+ registrationState
			+ " detail="
			+ detail;
		if (!gateOpen)
			message += " gateReason=" + failReason;

		if (level == "WARN")
			log?.LogWarning(message);
		else
			log?.LogInfo(message);
	}
}



