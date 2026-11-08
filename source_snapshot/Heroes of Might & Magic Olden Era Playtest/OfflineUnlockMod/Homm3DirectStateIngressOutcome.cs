namespace OfflineUnlockMod;

internal enum Homm3DirectStateIngressStatus : byte
{
	Accepted = 0,
	Rejected = 1,
	Failed = 2,
}

/// <summary>
/// Stack-only ingress outcome. Accepted paths carry no heap diagnostics;
/// Rejected/Failed carry a named reason for cap-logged fail-closed exits.
/// </summary>
internal readonly struct Homm3DirectStateIngressOutcome
{
	internal Homm3DirectStateIngressOutcome(
		Homm3DirectStateIngressStatus status,
		Homm3DirectStateHookSurface surface,
		Homm3BattleEventNativeAdapter.DamageEventInfo damage,
		string abilityName,
		string reason)
	{
		Status = status;
		Surface = surface;
		Damage = damage;
		AbilityName = abilityName;
		Reason = reason;
	}

	internal Homm3DirectStateIngressStatus Status { get; }
	internal Homm3DirectStateHookSurface Surface { get; }
	internal Homm3BattleEventNativeAdapter.DamageEventInfo Damage { get; }
	internal string AbilityName { get; }
	internal string Reason { get; }

	internal bool IsAccepted => Status == Homm3DirectStateIngressStatus.Accepted;

	internal static Homm3DirectStateIngressOutcome AcceptDamage(
		Homm3DirectStateHookSurface surface,
		Homm3BattleEventNativeAdapter.DamageEventInfo damage,
		string abilityName)
	{
		return new Homm3DirectStateIngressOutcome(
			Homm3DirectStateIngressStatus.Accepted,
			surface,
			damage,
			abilityName,
			null);
	}

	internal static Homm3DirectStateIngressOutcome Reject(
		Homm3DirectStateHookSurface surface,
		string reason)
	{
		return new Homm3DirectStateIngressOutcome(
			Homm3DirectStateIngressStatus.Rejected,
			surface,
			default,
			null,
			reason ?? "rejected");
	}

	internal static Homm3DirectStateIngressOutcome Fail(
		Homm3DirectStateHookSurface surface,
		string reason)
	{
		return new Homm3DirectStateIngressOutcome(
			Homm3DirectStateIngressStatus.Failed,
			surface,
			default,
			null,
			reason ?? "failed");
	}
}
