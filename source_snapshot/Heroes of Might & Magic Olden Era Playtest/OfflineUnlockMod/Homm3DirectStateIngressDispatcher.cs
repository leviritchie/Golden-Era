using System;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Routing-only fan-out from normalized ingress to active direct-state adapters.
/// Normalization and outcome logging happen outside this type.
/// </summary>
internal static class Homm3DirectStateIngressDispatcher
{
	private static int _rejectLogs;
	private static int _failLogs;

	internal static void CapLogOutcome(Homm3DirectStateIngressOutcome outcome)
	{
		Homm3DirectStateIngressMining.ObserveOutcome(in outcome);
		if (outcome.IsAccepted || string.IsNullOrWhiteSpace(outcome.Reason))
			return;
		Homm3RuntimeMechanicFixtureHarness.RecordFailure(outcome.Reason);
		if (outcome.Status == Homm3DirectStateIngressStatus.Failed)
		{
			if (_failLogs++ >= 12)
				return;
			Plugin.LogSource?.LogWarning(
				"HoMM3 direct-state ingress failed: surface="
				+ outcome.Surface
				+ " reason=" + outcome.Reason);
			return;
		}
		if (_rejectLogs++ >= 12)
			return;
		Plugin.LogSource?.LogWarning(
			"HoMM3 direct-state ingress rejected: surface="
			+ outcome.Surface
			+ " reason=" + outcome.Reason);
	}

	internal static void DispatchDamageApplied(
		in Homm3DirectStateIngressOutcome outcome,
		MethodInfo applyDamageMethod)
	{
		if (!outcome.IsAccepted)
		{
			CapLogOutcome(outcome);
			return;
		}
		Homm3DirectStateIngressMining.ObserveOutcome(in outcome);
		if (Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Movement))
			TryRouteMovementPush(in outcome);
		if (Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.NestedDamage))
			Homm3RuntimeMechanicHooks.TryEnqueueNestedDamageFromIngress(in outcome, applyDamageMethod);
		Homm3DirectStateAdapters.DrainDeferredWork();
	}

	internal static void DispatchTypedEventConstructed(object eventArgs)
	{
		if (eventArgs == null)
			return;

		var castOutcome = Homm3BattleEventNativeAdapter.NormalizeCastCommitted(eventArgs, out var cast);
		if (castOutcome.IsAccepted)
		{
			// Cast / Focus / Cooldown / Status / Trap / Summon piggyback CastCommitted.
			Homm3RuntimeMechanicHooks.ObserveCastCommitted(eventArgs, cast);
			Homm3RuntimeMechanicHooks.RefreshAuras();
			Homm3DirectStateAdapters.DrainDeferredWork();
			return;
		}

		var moveOutcome = Homm3BattleEventNativeAdapter.NormalizeMovementCommitted(eventArgs, out var movement);
		if (moveOutcome.IsAccepted)
		{
			// Trap / Aura piggyback MovementCommitted.
			if (movement.TargetHex != null
			    && TryReadInt(movement.TargetHex, GameSymbols.BattleEventLaws.HexIndexMembers, out var hexIndex))
			{
				Homm3RuntimeMechanicFixtureHarness.RecordDirtyHex(hexIndex);
				Homm3RuntimeMechanicHooks.TriggerTrapsAtHex(movement.TargetHex, hexIndex);
			}
			Homm3RuntimeMechanicHooks.RefreshAuras();
			return;
		}

		var spawnedOutcome = Homm3BattleEventNativeAdapter.NormalizeObjectSpawned(eventArgs, out var spawned);
		if (spawnedOutcome.IsAccepted)
		{
			// Summon / Trap / Aura piggyback ObjectSpawned.
			Homm3RuntimeMechanicFixtureHarness.RecordDirtyUnit(spawned.SpawnedObject);
			Homm3RuntimeMechanicHooks.ObserveSpawned(spawned);
			Homm3RuntimeMechanicHooks.RefreshAuras();
			return;
		}

		var destroyedOutcome = Homm3BattleEventNativeAdapter.NormalizeObjectDestroyed(eventArgs, out var destroyed);
		if (destroyedOutcome.IsAccepted)
		{
			// Kill / AllyDeath / Corpse / Status / ActionQueue / Aura piggyback ObjectDestroyed.
			Homm3RuntimeMechanicHooks.ObserveDestroyed(destroyed);
			Homm3RuntimeMechanicHooks.RefreshAuras();
			return;
		}

		if (Homm3BattleEventNativeAdapter.TryReadRoundEvent(eventArgs, out var round, out _))
		{
			Homm3BattleLocalLawState.SetDirectRound(round.RoundNumber);
			Homm3RuntimeMechanicHooks.ObserveRound(round);
			Homm3RuntimeMechanicHooks.RefreshAuras();
			if (!round.Started)
				Homm3DirectStateAdapters.DrainDeferredWork();
			return;
		}

		if (Homm3BattleEventNativeAdapter.TryReadActionEvent(eventArgs, out var action, out _))
		{
			Homm3RuntimeMechanicHooks.ObserveAction(action);
			if (!action.Started)
				Homm3DirectStateAdapters.DrainDeferredWork();
		}
	}

	internal static void DispatchBattleEventSurface(
		Homm3DirectStateHookSurface surface,
		object eventArgs)
	{
		if (surface == Homm3DirectStateHookSurface.RoundStart
		    || surface == Homm3DirectStateHookSurface.RoundEnd)
		{
			var started = surface == Homm3DirectStateHookSurface.RoundStart;
			var outcome = Homm3BattleEventNativeAdapter.NormalizeRound(eventArgs, started, out var round);
			if (!outcome.IsAccepted)
			{
				CapLogOutcome(outcome);
				return;
			}
			// Cooldown / Status / TurnOrder / Aura piggyback round surfaces.
			Homm3BattleLocalLawState.SetDirectRound(round.RoundNumber);
			Homm3RuntimeMechanicHooks.ObserveRound(round);
			Homm3RuntimeMechanicHooks.RefreshAuras();
			if (!started)
				Homm3DirectStateAdapters.DrainDeferredWork();
			return;
		}

		if (surface == Homm3DirectStateHookSurface.ActionStart
		    || surface == Homm3DirectStateHookSurface.ActionEnd)
		{
			var started = surface == Homm3DirectStateHookSurface.ActionStart;
			var outcome = Homm3BattleEventNativeAdapter.NormalizeAction(eventArgs, started, out var action);
			if (!outcome.IsAccepted)
			{
				CapLogOutcome(outcome);
				return;
			}
			// Cast / NestedDamage / ActionQueue / TurnOrder piggyback action surfaces.
			Homm3RuntimeMechanicHooks.ObserveAction(action);
			if (!started)
				Homm3DirectStateAdapters.DrainDeferredWork();
		}
	}

	internal static void DispatchUnitInit(object unit, object ownerSide)
	{
		var outcome = Homm3BattleEventNativeAdapter.NormalizeUnitInit(unit, ownerSide);
		if (!outcome.IsAccepted)
		{
			CapLogOutcome(outcome);
			return;
		}
		// Damage / Movement / Summon / Aura piggyback UnitInit.
		Homm3RuntimeMechanicHooks.ObserveUnitInitialized(unit, ownerSide);
	}

	internal static void TryRouteMovementPush(in Homm3DirectStateIngressOutcome outcome)
	{
		try
		{
			TryRouteMovementPushCore(in outcome);
		}
		catch (Exception ex)
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Fail(
				Homm3DirectStateHookSurface.DamageApplied,
				"MovementPush route threw: " + ex.GetType().Name + ": " + ex.Message));
		}
	}

	private static void TryRouteMovementPushCore(in Homm3DirectStateIngressOutcome outcome)
	{
		var damage = outcome.Damage;
		if (damage.Caster == null || damage.Receiver == null)
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.DamageApplied,
				"MovementPush missing caster or receiver"));
			return;
		}
		if (damage.Damage <= 0)
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.DamageApplied,
				"MovementPush non-positive damage"));
			return;
		}

		// Prefer Init-bound mechanic index — no live SID string reads required.
		if (Homm3BattleLocalLawState.TryGetBoundUnitMechanicIndex(damage.Caster, out var boundIndex)
		    && Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(boundIndex, out var boundMechanic)
		    && boundMechanic.AdapterId == Homm3DirectStateAdapterId.Movement
		    && boundMechanic.Operation == Homm3DirectStateOperation.MovementPush
		    && string.Equals(boundMechanic.Trigger, "damageApplied", StringComparison.Ordinal))
		{
			var abilityName = outcome.AbilityName;
			if (string.IsNullOrWhiteSpace(abilityName))
			{
				CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
					Homm3DirectStateHookSurface.DamageApplied,
					"bound MovementPush ability unresolved"));
				return;
			}
			if (!Homm3BattleEventNativeAdapter.IsAbilityNameMatch(boundMechanic.AbilityName, abilityName))
			{
				CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
					Homm3DirectStateHookSurface.DamageApplied,
					"bound MovementPush ability mismatch expected="
					+ (boundMechanic.AbilityName ?? "null")
					+ " observed=" + abilityName));
				return;
			}
			TryCommitMovementPush(
				in outcome,
				boundMechanic.UnitSid ?? "bound",
				boundMechanic.AbilityName ?? abilityName);
			return;
		}

		if (!Homm3BattleEventNativeAdapter.TryResolveUnitSid(damage.Caster, out var casterSid)
		    && !(damage.Dealer != null
		         && Homm3BattleEventNativeAdapter.TryResolveBattleUnit(damage.Dealer, out var dealerUnit)
		         && Homm3BattleEventNativeAdapter.TryResolveUnitSid(dealerUnit, out casterSid)))
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.DamageApplied,
				"caster identity unresolved after Unit unwrap type="
				+ DescribeTypeName(damage.Caster)
				+ " dealer=" + DescribeTypeName(damage.Dealer)));
			return;
		}
		if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(casterSid, out var indexes))
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.DamageApplied,
				"no active mechanics for caster sid=" + casterSid));
			return;
		}
		var observedAbility = outcome.AbilityName;
		var matchedWithoutName = false;
		if (string.IsNullOrWhiteSpace(observedAbility))
		{
			var movementCount = 0;
			var soleIndex = -1;
			for (var i = 0; i < indexes.Length; i++)
			{
				if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var candidate)
				    || candidate.AdapterId != Homm3DirectStateAdapterId.Movement
				    || candidate.Operation != Homm3DirectStateOperation.MovementPush
				    || !string.Equals(candidate.Trigger, "damageApplied", StringComparison.Ordinal))
					continue;
				movementCount++;
				soleIndex = indexes[i];
			}
			if (movementCount == 1
			    && Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(soleIndex, out var sole)
			    && !string.IsNullOrWhiteSpace(sole.AbilityName))
			{
				observedAbility = sole.AbilityName;
				matchedWithoutName = true;
			}
			else
			{
				CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
					Homm3DirectStateHookSurface.DamageApplied,
					"ability name unresolved for sid=" + casterSid
					+ " castSource=" + DescribeTypeName(damage.CastSource)
					+ " dealer=" + DescribeTypeName(damage.Dealer)));
				return;
			}
		}
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || mechanic.AdapterId != Homm3DirectStateAdapterId.Movement
			    || mechanic.Operation != Homm3DirectStateOperation.MovementPush
			    || !string.Equals(mechanic.Trigger, "damageApplied", StringComparison.Ordinal)
			    || !(matchedWithoutName
			         || Homm3BattleEventNativeAdapter.IsAbilityNameMatch(mechanic.AbilityName, observedAbility)))
				continue;
			TryCommitMovementPush(in outcome, casterSid, observedAbility ?? mechanic.AbilityName);
			return;
		}
		CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
			Homm3DirectStateHookSurface.DamageApplied,
			"no matching MovementPush mechanic for sid=" + casterSid
			+ " ability=" + observedAbility));
	}

	private static void TryCommitMovementPush(
		in Homm3DirectStateIngressOutcome outcome,
		string casterSid,
		string abilityName)
	{
		var damage = outcome.Damage;
		// Prefer proven DamageKill stack accessors. IncludingZero is required so stacks==0
		// can CapLog; TryGetStackCount only returns true when stacks > 0.
		if (DamageKillMapping.TryGetStackCountIncludingZero(damage.Receiver, out var stacks)
		    && stacks <= 0)
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Reject(
				Homm3DirectStateHookSurface.DamageApplied,
				"target stack count already dead sid=" + casterSid));
			return;
		}
		var moveCaster = damage.Caster;
		if (!Homm3BattleEventNativeAdapter.TryResolveBattleUnit(moveCaster, out moveCaster))
			moveCaster = damage.Caster;
		var scope = ResolveBattleScope(damage.Receiver) ?? damage.Receiver;
		if (Homm3DirectStateAdapters.TryMove(
			    scope,
			    moveCaster,
			    damage.Receiver,
			    Homm3DirectStateOperation.MovementPush,
			    null,
			    out var destination,
			    out var failure))
		{
			var destIndex = TryReadInt(destination, GameSymbols.BattleEventLaws.HexIndexMembers, out var di)
				? di.ToString()
				: "?";
			Plugin.LogSource?.LogInfo(
				"HoMM3 direct-state MovementPush committed:"
				+ " casterSid=" + casterSid
				+ " ability=" + (abilityName ?? "null")
				+ " destIndex=" + destIndex
				+ " destination=" + (destination?.ToString() ?? "null")
				+ " (see " + Homm3DirectStateM3BfdiShoveDiagnostic.CapLogPrefix + " agree for dual-readback).");
		}
		else
		{
			CapLogOutcome(Homm3DirectStateIngressOutcome.Fail(
				Homm3DirectStateHookSurface.DamageApplied,
				"MovementPush blocked: " + failure));
		}
	}

	private static string DescribeTypeName(object value)
	{
		return value == null ? "null" : (value.GetType().FullName ?? value.GetType().Name);
	}

	private static object ResolveBattleScope(object unit)
	{
		return TryReadObject(
			unit,
			GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers,
			out var scope)
			? scope
			: null;
	}

	private static bool TryReadInt(object value, string[] names, out int result)
	{
		result = 0;
		if (!TryReadObject(value, names, out var raw) || raw == null)
			return false;
		try
		{
			result = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadObject(object value, string[] names, out object result)
	{
		result = null;
		if (value == null || names == null)
			return false;
		for (var current = value.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						result = field.GetValue(value);
						return true;
					}
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						result = property.GetValue(value, null);
						return true;
					}
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						result = method.Invoke(value, null);
						return true;
					}
				}
				catch
				{
					return false;
				}
			}
		}
		return false;
	}
}
