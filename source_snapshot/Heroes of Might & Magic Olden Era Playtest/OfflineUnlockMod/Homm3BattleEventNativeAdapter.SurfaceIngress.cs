namespace OfflineUnlockMod;

/// <summary>
/// Surface-keyed normalization for non-damage HookSurfaces. Returns named
/// Homm3DirectStateIngressOutcome; typed payloads stay on the stack via out params.
/// </summary>
internal static partial class Homm3BattleEventNativeAdapter
{
	internal static Homm3DirectStateIngressOutcome NormalizeCastCommitted(
		object eventArgs,
		out CastAbilityEventInfo cast)
	{
		cast = default;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.CastCommitted,
				"castCommitted eventArgs is null");
		if (!TryReadCastAbilityEvent(eventArgs, out cast, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.CastCommitted,
				failReason ?? "castCommitted payload unreadable");
		if (cast.Caster == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.CastCommitted,
				"castCommitted caster is null");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.CastCommitted,
			default,
			cast.AbilityName);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeMovementCommitted(
		object eventArgs,
		out MovementEventInfo movement)
	{
		movement = default;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.MovementCommitted,
				"movementCommitted eventArgs is null");
		if (!TryReadMovementEvent(eventArgs, out movement, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.MovementCommitted,
				failReason ?? "movementCommitted payload unreadable");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.MovementCommitted,
			default,
			null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeObjectSpawned(
		object eventArgs,
		out SpawnedEventInfo spawned)
	{
		spawned = default;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.ObjectSpawned,
				"objectSpawned eventArgs is null");
		if (!TryReadSpawnedEvent(eventArgs, out spawned, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.ObjectSpawned,
				failReason ?? "objectSpawned payload unreadable");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.ObjectSpawned,
			default,
			null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeObjectDestroyed(
		object eventArgs,
		out DestroyedEventInfo destroyed)
	{
		destroyed = default;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.ObjectDestroyed,
				"objectDestroyed eventArgs is null");
		if (!TryReadDestroyedEvent(eventArgs, out destroyed, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.ObjectDestroyed,
				failReason ?? "objectDestroyed payload unreadable");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.ObjectDestroyed,
			default,
			null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeRound(
		object eventArgs,
		bool started,
		out RoundEventInfo round)
	{
		round = default;
		var surface = started
			? Homm3DirectStateHookSurface.RoundStart
			: Homm3DirectStateHookSurface.RoundEnd;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(surface, "round eventArgs is null");
		if (!TryReadRoundEvent(eventArgs, started, out round, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				surface,
				failReason ?? "round payload unreadable");
		return Homm3DirectStateIngressOutcome.AcceptDamage(surface, default, null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeAction(
		object eventArgs,
		bool started,
		out ActionEventInfo action)
	{
		action = default;
		var surface = started
			? Homm3DirectStateHookSurface.ActionStart
			: Homm3DirectStateHookSurface.ActionEnd;
		if (eventArgs == null)
			return Homm3DirectStateIngressOutcome.Reject(surface, "action eventArgs is null");
		if (!TryReadActionEvent(eventArgs, started, out action, out var failReason))
			return Homm3DirectStateIngressOutcome.Reject(
				surface,
				failReason ?? "action payload unreadable");
		return Homm3DirectStateIngressOutcome.AcceptDamage(surface, default, null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeUnitInit(
		object unit,
		object ownerSide)
	{
		if (unit == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.UnitInit,
				"unitInit unit is null");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.UnitInit,
			default,
			null);
	}

	internal static Homm3DirectStateIngressOutcome NormalizeBattleResult(object battleResult)
	{
		if (battleResult == null)
			return Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.BattleResult,
				"battleResult is null");
		return Homm3DirectStateIngressOutcome.AcceptDamage(
			Homm3DirectStateHookSurface.BattleResult,
			default,
			null);
	}
}
