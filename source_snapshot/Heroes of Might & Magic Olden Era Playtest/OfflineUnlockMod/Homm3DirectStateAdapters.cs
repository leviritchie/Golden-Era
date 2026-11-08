using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

namespace OfflineUnlockMod;

internal readonly struct Homm3DirectStatusRequest
{
	internal Homm3DirectStatusRequest(string sid, int level, int duration, int value, bool refresh, int round)
	{
		Sid = sid;
		Level = level;
		Duration = duration;
		Value = value;
		Refresh = refresh;
		Round = round;
	}

	internal string Sid { get; }
	internal int Level { get; }
	internal int Duration { get; }
	internal int Value { get; }
	internal bool Refresh { get; }
	internal int Round { get; }
}

internal readonly struct Homm3DirectSpawnRequest
{
	internal Homm3DirectSpawnRequest(Type runtimeType, object[] initArgs, IList ownerCollection)
	{
		RuntimeType = runtimeType;
		InitArgs = initArgs;
		OwnerCollection = ownerCollection;
	}

	internal Type RuntimeType { get; }
	internal object[] InitArgs { get; }
	internal IList OwnerCollection { get; }
}

internal readonly struct Homm3DirectDamageRequest
{
	internal Homm3DirectDamageRequest(
		object receiver,
		MethodInfo applyDamageMethod,
		object[] arguments,
		int damage,
		Homm3DirectStateOperation operation)
	{
		Receiver = receiver;
		ApplyDamageMethod = applyDamageMethod;
		Arguments = arguments;
		Damage = damage;
		Operation = operation;
	}

	internal object Receiver { get; }
	internal MethodInfo ApplyDamageMethod { get; }
	internal object[] Arguments { get; }
	internal int Damage { get; }
	internal Homm3DirectStateOperation Operation { get; }
}

internal readonly struct Homm3DirectCastRequest
{
	internal Homm3DirectCastRequest(object target, MethodInfo castMethod, object[] arguments)
	{
		Target = target;
		CastMethod = castMethod;
		Arguments = arguments;
	}

	internal object Target { get; }
	internal MethodInfo CastMethod { get; }
	internal object[] Arguments { get; }
	internal bool IsValid => CastMethod != null && Arguments != null && (CastMethod.IsStatic || Target != null);
}

internal static class Homm3DirectStateAdapters
{
	internal const string StatusSynchronizationPolicy = "ManagerAuthoritativeNoNativeInventory";

	internal static bool TryRecordCastCommit(
		object scope,
		object caster,
		string correlationToken,
		out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Cast,
			    Homm3DirectStateOperation.CastChain,
			    reserveJournal: 2,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3DirectStateIdentity.TryResolveKey(caster, out var casterKey, out failReason))
				return Fail(transaction, failReason, out failReason);
			var eventToken = (casterKey << 32)
			                 ^ (uint)(correlationToken ?? string.Empty).GetHashCode();
			if (eventToken == 0)
				eventToken = 1;
			if (!Homm3BattleLocalLawState.TryClaimDirectEventToken(transaction, eventToken, out failReason)
			    || !Homm3BattleLocalLawState.TryRecordDirectCast(transaction, caster, out _, out failReason)
			    || !transaction.Commit(out failReason))
				return Fail(transaction, failReason, out failReason);
			Homm3BattleLocalLawState.CompleteDirectEventToken(eventToken, success: true);
		}
		return true;
	}

	internal static bool TryRecordCastAndQueueChain(
		object scope,
		object caster,
		Homm3DirectCastRequest chainRequest,
		out long correlationId,
		out string failReason)
	{
		correlationId = 0;
		if (!chainRequest.IsValid)
		{
			failReason = "cast-chain request is incomplete";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Cast,
			    Homm3DirectStateOperation.CastChain,
			    reserveJournal: 2,
			    reserveRootWork: 2,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			correlationId = transaction.CorrelationId;
			if (!Homm3BattleLocalLawState.TryRecordDirectCast(transaction, caster, out _, out failReason))
				return Fail(transaction, failReason, out failReason);
			var work = new Homm3DirectStateWorkItem(
				Homm3DirectStateAdapterId.Cast,
				Homm3DirectStateOperation.CastChain,
				scope,
				caster,
				null,
				chainRequest,
				0,
				transaction.CorrelationId,
				transaction.Generation);
			if (!transaction.TryEnqueueChild(work, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryMutateFocus(
		object scope,
		object side,
		Homm3DirectStateOperation operation,
		int value,
		out int oldFocus,
		out int newFocus,
		out string failReason)
	{
		oldFocus = 0;
		newFocus = 0;
		if (operation != Homm3DirectStateOperation.FocusGrant
		    && operation != Homm3DirectStateOperation.FocusSpend
		    && operation != Homm3DirectStateOperation.FocusSet)
		{
			failReason = "unsupported Focus operation " + operation;
			return false;
		}
		if (!NativeCombatWriteGateway.TryResolveFocusManager(side, out var manager, out failReason)
		    || !NativeCombatWriteGateway.TryReadIntMember(manager, "focus.value", out oldFocus, out failReason))
			return false;
		try
		{
			newFocus = operation switch
			{
				Homm3DirectStateOperation.FocusGrant => checked(oldFocus + Math.Max(0, value)),
				Homm3DirectStateOperation.FocusSpend => oldFocus - Math.Max(0, value),
				_ => Math.Max(0, value),
			};
		}
		catch (OverflowException)
		{
			failReason = "Focus mutation overflowed";
			return false;
		}
		if (newFocus < 0)
		{
			failReason = "Focus spend exceeds current Focus";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Focus,
			    operation,
			    reserveJournal: 2,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!transaction.TryRecordNativeInt(manager, "focus.value", oldFocus, out failReason)
			    || !Homm3BattleLocalLawState.TryRecordDirectResource(transaction, manager, cooldown: false, newFocus, out failReason)
			    || !NativeCombatWriteGateway.TryWriteIntMember(manager, "focus.value", newFocus, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryMutateCooldown(
		object scope,
		object cooldownOwner,
		Homm3DirectStateOperation operation,
		int value,
		out int oldCooldown,
		out int newCooldown,
		out string failReason)
	{
		oldCooldown = 0;
		newCooldown = 0;
		var memberId = operation == Homm3DirectStateOperation.CooldownCharges
			? "ability.charges"
			: operation == Homm3DirectStateOperation.CooldownCastCounter
				? "ability.castCounter"
				: NativeCombatWriteGateway.GetCooldownMemberId(cooldownOwner);
		if (!NativeCombatWriteGateway.TryReadIntMember(cooldownOwner, memberId, out oldCooldown, out failReason))
			return false;
		try
		{
			newCooldown = operation switch
			{
				Homm3DirectStateOperation.CooldownSet => Math.Max(0, value),
				Homm3DirectStateOperation.CooldownReduce => Math.Max(0, oldCooldown - Math.Max(0, value)),
				Homm3DirectStateOperation.CooldownIncrease => checked(oldCooldown + Math.Max(0, value)),
				Homm3DirectStateOperation.CooldownCharges => Math.Max(0, value),
				Homm3DirectStateOperation.CooldownCastCounter => Math.Max(0, value),
				_ => -1,
			};
		}
		catch (OverflowException)
		{
			failReason = "cooldown mutation overflowed";
			return false;
		}
		if (newCooldown < 0)
		{
			failReason = "unsupported cooldown operation " + operation;
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Cooldown,
			    operation,
			    reserveJournal: 2,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!transaction.TryRecordNativeInt(cooldownOwner, memberId, oldCooldown, out failReason)
			    || !Homm3BattleLocalLawState.TryRecordDirectResource(transaction, cooldownOwner, cooldown: true, newCooldown, out failReason)
			    || !NativeCombatWriteGateway.TryWriteIntMember(cooldownOwner, memberId, newCooldown, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryApplyStatus(
		object scope,
		object receiver,
		object caster,
		Homm3DirectStatusRequest request,
		out string failReason)
	{
		var operation = request.Refresh
			? Homm3DirectStateOperation.StatusRefresh
			: Homm3DirectStateOperation.StatusApply;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Status,
			    operation,
			    reserveJournal: 2,
			    reserveRootWork: 2,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			var state = new Homm3DirectStatusState(
				request.Sid,
				Math.Max(0, request.Level),
				Math.Max(0, request.Duration),
				request.Value,
				Math.Max(0, request.Round),
				caster);
			if (!Homm3BattleLocalLawState.TryApplyDirectStatus(transaction, receiver, state, request.Refresh, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryRemoveStatus(
		object scope,
		object receiver,
		string sid,
		out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Status,
			    Homm3DirectStateOperation.StatusRemove,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryRemoveDirectStatus(transaction, receiver, sid, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryTickOrExpireStatus(
		object scope,
		object receiver,
		string sid,
		bool expire,
		out int remainingDuration,
		out string failReason)
	{
		remainingDuration = 0;
		var operation = expire
			? Homm3DirectStateOperation.StatusExpire
			: Homm3DirectStateOperation.StatusTick;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Status,
			    operation,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryTransitionDirectStatus(
				    transaction,
				    receiver,
				    sid,
				    operation,
				    out remainingDuration,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryMove(
		object scope,
		object sourceUnit,
		object targetUnit,
		Homm3DirectStateOperation operation,
		object explicitDestinationHex,
		out object destinationHex,
		out string failReason)
	{
		destinationHex = null;
		// MovementPush ungates after M3 live-positive (or M3 diagnostic flag).
		// MovementTeleport ungates after M6 live-positive (or M6 diagnostic flag).
		// Both share journaled UnitData.bfdi via TryCommitUnitHexMove (movement.commit.bfdi_v1 /
		// movement.relocate.bfdi_v1). MovementPull stays CapLog-unsupported.
		if ((operation == Homm3DirectStateOperation.MovementTeleport
		     && !Homm3DirectStateM6BfdiTeleportDiagnostic.IsMovementTeleportAllowed())
		    || (operation == Homm3DirectStateOperation.MovementPush
		        && !Homm3DirectStateM3BfdiShoveDiagnostic.IsMovementPushAllowed()))
		{
			failReason = "movement occupancy mutation gated until native push_unit/walk is live-positive (battle_state_logic_map)";
			return false;
		}
		if (operation == Homm3DirectStateOperation.MovementSetImmobile)
		{
			if (!BattleCombatTransactionManager.TryBegin(
				    scope,
				    Homm3DirectStateAdapterId.Movement,
				    operation,
				    reserveJournal: 1,
				    reserveRootWork: 1,
				    out var immobileTransaction,
				    out failReason))
				return false;
			using (immobileTransaction)
			{
				if (!Homm3BattleLocalLawState.TrySetDirectImmobile(immobileTransaction, targetUnit, explicitDestinationHex != null, out failReason))
					return Fail(immobileTransaction, failReason, out failReason);
				if (!immobileTransaction.Commit(out failReason))
					return false;
			}
			return true;
		}
		if (targetUnit == null)
		{
			failReason = "movement target unit is null";
			return false;
		}
		if (operation == Homm3DirectStateOperation.MovementPull)
		{
			failReason = "MovementPull unsupported";
			return false;
		}
		if (Homm3BattleLocalLawState.IsDirectlyImmobile(targetUnit))
		{
			failReason = "movement target is directly immobilized";
			return false;
		}
		if (operation == Homm3DirectStateOperation.MovementTeleport)
			destinationHex = explicitDestinationHex;
		else if (!TryResolveRelativeDestination(sourceUnit, targetUnit, operation, out destinationHex, out failReason))
			return false;
		if (destinationHex == null)
		{
			failReason = "movement destination is null";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Movement,
			    operation,
			    reserveJournal: 2,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!NativeCombatWriteGateway.TryCommitUnitHexMove(
				    targetUnit,
				    destinationHex,
				    transaction,
				    out var sourceHex,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (TryReadHexIndex(sourceHex, out var sourceIndex))
				Homm3RuntimeMechanicFixtureHarness.RecordDirtyHex(sourceIndex);
			if (TryReadHexIndex(destinationHex, out var destinationIndex))
				Homm3RuntimeMechanicFixtureHarness.RecordDirtyHex(destinationIndex);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TrySummon(
		object scope,
		Homm3DirectSpawnRequest request,
		out object summoned,
		out string failReason)
	{
		summoned = null;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Summon,
			    Homm3DirectStateOperation.SummonCreate,
			    reserveJournal: 2,
			    reserveRootWork: 2,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!NativeCombatWriteGateway.TryInitializeAndInsertObject(
				    request.RuntimeType,
				    request.InitArgs,
				    request.OwnerCollection,
				    transaction,
				    out summoned,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryCreateTrap(
		object scope,
		object ownerSide,
		int hexKey,
		string trapSid,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Trap,
			    Homm3DirectStateOperation.TrapSpawn,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryCreateDirectTrap(
				    transaction,
				    Homm3DirectStateIdentity.ResolveKeyOrZero(ownerSide),
				    hexKey,
				    trapSid,
				    out trap,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryTriggerTrap(
		object scope,
		long trapId,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Trap,
			    Homm3DirectStateOperation.TrapTrigger,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryTriggerDirectTrap(transaction, trapId, out trap, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryDespawnTrap(
		object scope,
		long trapId,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Trap,
			    Homm3DirectStateOperation.TrapDespawn,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryRemoveDirectTrap(transaction, trapId, out trap, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryCreateCorpse(
		object scope,
		object unit,
		int hexKey,
		string unitSid,
		object ownerSide,
		out Homm3DirectCorpseState corpse,
		out string failReason)
	{
		corpse = default;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Corpse,
			    Homm3DirectStateOperation.CorpseCreate,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryCreateDirectCorpse(
				    transaction,
				    unit,
				    hexKey,
				    unitSid,
				    Homm3DirectStateIdentity.ResolveKeyOrZero(ownerSide),
				    out corpse,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryConsumeCorpse(
		object scope,
		long corpseId,
		out Homm3DirectCorpseState corpse,
		out string failReason)
	{
		corpse = default;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Corpse,
			    Homm3DirectStateOperation.CorpseConsume,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryConsumeDirectCorpse(transaction, corpseId, out corpse, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryRaiseCorpse(
		object scope,
		long corpseId,
		Homm3DirectSpawnRequest summonRequest,
		out Homm3DirectCorpseState consumedCorpse,
		out object summoned,
		out string failReason)
	{
		consumedCorpse = default;
		summoned = null;
		if (!Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Summon))
		{
			failReason = "corpse raising requires the summon adapter in the same active snapshot";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Corpse,
			    Homm3DirectStateOperation.CorpseConsume,
			    reserveJournal: 3,
			    reserveRootWork: 3,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryConsumeDirectCorpse(
				    transaction,
				    corpseId,
				    out consumedCorpse,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!NativeCombatWriteGateway.TryInitializeAndInsertObject(
				    summonRequest.RuntimeType,
				    summonRequest.InitArgs,
				    summonRequest.OwnerCollection,
				    transaction,
				    out summoned,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryEnqueueNestedDamage(
		object scope,
		object source,
		Homm3DirectDamageRequest request,
		out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.NestedDamage,
			    request.Operation,
			    reserveJournal: 1,
			    reserveRootWork: 2,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			var work = new Homm3DirectStateWorkItem(
				Homm3DirectStateAdapterId.NestedDamage,
				request.Operation,
				scope,
				source,
				request.Receiver,
				request,
				request.Damage,
				transaction.CorrelationId,
				transaction.Generation);
			if (!transaction.TryEnqueueChild(work, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TrySetDamageRedirection(
		object scope,
		object receiver,
		object redirectTarget,
		out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.NestedDamage,
			    Homm3DirectStateOperation.NestedRedirection,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TrySetDirectDamageRedirect(
				    transaction,
				    receiver,
				    redirectTarget,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryConfirmKill(
		object scope,
		object killer,
		object receiver,
		object receiverSide,
		int round,
		bool timeout,
		bool allyDeath,
		out Homm3DirectKillState kill,
		out string failReason)
	{
		kill = default;
		long token = 0;
		var adapterId = allyDeath ? Homm3DirectStateAdapterId.AllyDeath : Homm3DirectStateAdapterId.Kill;
		var operation = allyDeath ? Homm3DirectStateOperation.AllyDeathObserve : Homm3DirectStateOperation.KillConfirm;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    adapterId,
			    operation,
			    reserveJournal: 2,
			    reserveRootWork: 2,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryConfirmDirectKill(
				    transaction,
				    killer,
				    receiver,
				    receiverSide,
				    round,
				    timeout,
				    out kill,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			token = ComposeToken(
				Homm3DirectStateIdentity.ResolveKeyOrZero(receiver),
				allyDeath ? killer : receiver,
				allyDeath ? "allyDeath" : "kill");
			if (token == 0)
				token = allyDeath ? 2 : 1;
			if (!Homm3BattleLocalLawState.TryClaimDirectEventToken(transaction, token, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		Homm3BattleLocalLawState.CompleteDirectEventToken(token, success: true);
		return true;
	}

	internal static bool TryInsertAction(
		object scope,
		IList queue,
		int index,
		object entry,
		out string failReason)
	{
		if (queue == null || index < 0 || index > queue.Count || queue.Count >= 32)
		{
			failReason = "action queue insert is outside bounded queue/index contract";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.ActionQueue,
			    Homm3DirectStateOperation.ActionQueueInsert,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!NativeCombatWriteGateway.TryInsertListItem(queue, index, entry, transaction, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryRemoveAction(
		object scope,
		IList queue,
		int index,
		out object removed,
		out string failReason)
	{
		removed = null;
		if (queue == null || index < 0 || index >= queue.Count)
		{
			failReason = "action queue remove index is outside queue";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.ActionQueue,
			    Homm3DirectStateOperation.ActionQueueRemove,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!NativeCombatWriteGateway.TryRemoveListItem(queue, index, transaction, out removed, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryReorderTurn(
		object scope,
		IList queue,
		int fromIndex,
		int toIndex,
		out string failReason)
	{
		if (queue == null
		    || fromIndex < 0
		    || fromIndex >= queue.Count
		    || toIndex < 0
		    || toIndex >= queue.Count
		    || Math.Abs(toIndex - fromIndex) > 32)
		{
			failReason = "turn-order reorder is outside bounded queue/span contract";
			return false;
		}
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.TurnOrder,
			    Homm3DirectStateOperation.TurnOrderReorder,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!NativeCombatWriteGateway.TryReorderListItem(queue, fromIndex, toIndex, transaction, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryDefineAura(
		object scope,
		object source,
		object ownerSide,
		int radius,
		string effectSid,
		out long auraId,
		out string failReason)
	{
		auraId = 0;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Aura,
			    Homm3DirectStateOperation.AuraDefine,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryDefineDirectAura(
				    transaction,
				    source,
				    ownerSide,
				    radius,
				    effectSid,
				    out auraId,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryRefreshAura(
		object scope,
		long auraId,
		IEnumerable<object> members,
		out int memberCount,
		out string failReason)
	{
		memberCount = 0;
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Aura,
			    Homm3DirectStateOperation.AuraRefresh,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryReplaceDirectAuraMembers(
				    transaction,
				    auraId,
				    members,
				    out memberCount,
				    out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryRemoveAura(
		object scope,
		long auraId,
		out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Aura,
			    Homm3DirectStateOperation.AuraRemove,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (!Homm3BattleLocalLawState.TryRemoveDirectAura(transaction, auraId, out failReason))
				return Fail(transaction, failReason, out failReason);
			if (!transaction.Commit(out failReason))
				return false;
		}
		return true;
	}

	internal static bool TryExecuteDeferredWork(Homm3DirectStateWorkItem workItem, out string failReason)
	{
		if (workItem.Generation != Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration)
		{
			failReason = "deferred work belongs to a stale battle generation";
			return false;
		}
		if (workItem.Operation == Homm3DirectStateOperation.NestedReflection
		    || workItem.Operation == Homm3DirectStateOperation.NestedRedirection
		    || workItem.Operation == Homm3DirectStateOperation.NestedSplash)
		{
			if (workItem.Payload is not Homm3DirectDamageRequest request
			    || request.Receiver == null
			    || request.ApplyDamageMethod == null
			    || request.Arguments == null)
			{
				failReason = "nested damage work item is incomplete";
				return false;
			}
			if (TryReadIntMember(request.Receiver, GameSymbols.DirectStateLaws.UnitStackCountMembers, out var stacks)
			    && stacks <= 0)
			{
				failReason = "nested damage receiver is no longer alive";
				return false;
			}
			return NativeCombatWriteGateway.TryInvokeDeferredDamage(request, out failReason);
		}
		if (workItem.Operation == Homm3DirectStateOperation.CastChain)
		{
			if (workItem.Payload is not Homm3DirectCastRequest castRequest)
			{
				failReason = "cast-chain work requires an exact typed native cast request";
				return false;
			}
			return NativeCombatWriteGateway.TryInvokeDeferredCast(castRequest, out failReason);
		}
		failReason = "unsupported deferred direct-state operation " + workItem.Operation;
		return false;
	}

	internal static void DrainDeferredWork()
	{
		string firstFailure = null;
		while (BattleCombatTransactionManager.TryDequeueChild(out var workItem))
		{
			if (TryExecuteDeferredWork(workItem, out var failure))
				continue;
			firstFailure ??= failure;
			Plugin.LogSource?.LogWarning("HoMM3 direct-state deferred work failed closed: " + failure);
			BattleCombatTransactionManager.AbortRoot("deferred child failed: " + failure);
			break;
		}
		BattleCombatTransactionManager.CompleteCurrentLevel(accepted: firstFailure == null);
		if (firstFailure != null)
			Homm3RuntimeMechanicFixtureHarness.RecordFailure(firstFailure);
	}

	/// <summary>
	/// Interim dest_recipe (movement.dest.ehh_bdpe_v1 plant-incomplete for ehh.bdpe /
	/// een helpers). Evidence-based Shoulder Check policy: axial opposite of pusher→target
	/// via proven Hex neighbour fields + Hex.bcyf / IsLockedForSide legality (or equivalent
	/// blocked+fieldObjects composition). Not silent guessing; not commit ownership.
	/// </summary>
	private static bool TryResolveRelativeDestination(
		object sourceUnit,
		object targetUnit,
		Homm3DirectStateOperation operation,
		out object destination,
		out string failReason)
	{
		destination = null;
		if (sourceUnit == null || targetUnit == null)
		{
			failReason = "relative movement requires source and target units";
			return false;
		}
		if (!TryReadExactMember(sourceUnit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var sourceHex)
		    || sourceHex == null
		    || !TryReadExactMember(targetUnit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var targetHex)
		    || targetHex == null)
		{
			failReason = "relative movement source or target has no exact hex";
			return false;
		}
		if (!TryReadHexCoordinates(sourceHex, out var sourceX, out var sourceZ)
		    || !TryReadHexCoordinates(targetHex, out var targetX, out var targetZ))
		{
			failReason = "relative movement hex coordinates are unavailable";
			return false;
		}

		var dist = HexDistance(sourceX, sourceZ, targetX, targetZ);
		if (dist != 1)
		{
			failReason = "relative movement requires adjacent stacks dist=" + dist;
			return false;
		}

		// Resolve through native neighbour field links on the target hex only.
		// Do not Invoke Hex neighbour getters — live combat AccessViolation'd that path.
		// Axial opposite only: ring (i+3)%6 order is unproven for live Hex neighbour slots.
		if (operation == Homm3DirectStateOperation.MovementPull)
		{
			destination = null;
			failReason = "MovementPull unsupported";
			return false;
		}
		if (operation != Homm3DirectStateOperation.MovementPush)
		{
			failReason = "relative movement operation is not push/pull";
			return false;
		}

		if (!TryReadHexNeighbourFields(targetHex, out var neighbours, out failReason))
			return false;

		// Shoulder Check values:[false] → push away (+1 axial opposite of pusher→defender).
		var destX = targetX + (targetX - sourceX);
		var destZ = targetZ + (targetZ - sourceZ);
		if (!TryMatchNeighbourCoordinates(neighbours, destX, destZ, out destination))
		{
			failReason =
				"interim dest_recipe: push destination neighbour missing for coords ("
				+ destX + "," + destZ + ")";
			return false;
		}

		if (HexesMatch(destination, sourceHex))
		{
			failReason = "interim dest_recipe: push destination collapsed onto source hex";
			destination = null;
			return false;
		}

		if (!TryValidatePushDestinationLegality(destination, targetUnit, out failReason))
		{
			destination = null;
			return false;
		}

		failReason = null;
		return true;
	}

	/// <summary>
	/// Dest legality from proven Hex.bcyf stores: blocked flags + fieldObjects occupancy.
	/// Prefer native IsLockedForSide invoke when side + method resolve; otherwise compose the
	/// same stores fail-closed. Never Hex.bcxo.
	/// </summary>
	private static bool TryValidatePushDestinationLegality(
		object destinationHex,
		object pushedUnit,
		out string failReason)
	{
		if (TryInvokeIsLockedForSide(destinationHex, pushedUnit, out var locked, out var invokeReason))
		{
			if (locked)
			{
				failReason = "interim dest_recipe: Hex.bcyf IsLockedForSide rejected dest";
				return false;
			}
			failReason = null;
			return true;
		}

		// Composition path — same stores bcyf reads (pin table 1d / ehh_bdpe.asm).
		// Unreadable blocked flags fail closed; never treat missing reads as "not blocked".
		if (!NativeCombatWriteGateway.TryReadExactMemberPublic(
			    destinationHex,
			    GameSymbols.DirectStateLaws.HexBlockedMembers,
			    out _))
		{
			failReason =
				"interim dest_recipe: dest legality unresolved (bcyf unavailable: "
				+ (invokeReason ?? "null")
				+ "; blocked flags unavailable)";
			return false;
		}
		var blockedNames = GameSymbols.DirectStateLaws.HexBlockedMembers;
		for (var i = 0; i < blockedNames.Length; i++)
		{
			if (!TryReadExactMember(destinationHex, new[] { blockedNames[i] }, out var raw))
			{
				failReason =
					"interim dest_recipe: blocked flag unreadable (" + blockedNames[i] + ")";
				return false;
			}
			if (raw is not bool flag)
			{
				failReason =
					"interim dest_recipe: blocked flag non-bool (" + blockedNames[i] + ")";
				return false;
			}
			if (!flag)
				continue;
			failReason = "interim dest_recipe: destination blocked (" + blockedNames[i] + ")";
			return false;
		}
		if (!NativeCombatWriteGateway.TryFieldObjectsContainsUnitPublic(
			    destinationHex,
			    pushedUnit,
			    out _,
			    out var occupancyReason)
		    && !string.IsNullOrWhiteSpace(occupancyReason)
		    && occupancyReason.IndexOf("unavailable", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			failReason = "interim dest_recipe: Hex.fieldObjects unavailable for dest gate";
			return false;
		}
		if (!TryDestinationFieldObjectsEmptyOrSelf(destinationHex, pushedUnit, out failReason))
			return false;
		failReason = null;
		return true;
	}

	private static bool TryDestinationFieldObjectsEmptyOrSelf(
		object destinationHex,
		object pushedUnit,
		out string failReason)
	{
		if (!NativeCombatWriteGateway.TryFieldObjectsContainsUnitPublic(
			    destinationHex,
			    pushedUnit,
			    out var selfPresent,
			    out failReason))
			return false;
		if (!TryReadExactMember(
			    destinationHex,
			    GameSymbols.DirectStateLaws.HexFieldObjectsMembers,
			    out var listObj)
		    || listObj == null)
		{
			failReason = "interim dest_recipe: Hex.fieldObjects unavailable";
			return false;
		}
		// Prefer Count when present; empty list is legal. Non-empty without self means foreign occupant.
		if (TryReadIntMember(listObj, new[] { "Count", "get_Count", "_size" }, out var count))
		{
			if (count > 0 && !selfPresent)
			{
				failReason = "interim dest_recipe: destination Hex.fieldObjects occupied count=" + count;
				return false;
			}
			failReason = null;
			return true;
		}
		// Count surface missing — refuse rather than approve an unverified destination.
		failReason = "interim dest_recipe: Hex.fieldObjects Count unavailable for dest gate";
		return false;
	}

	private static bool TryInvokeIsLockedForSide(
		object hex,
		object pushedUnit,
		out bool locked,
		out string failReason)
	{
		locked = false;
		failReason = null;
		if (hex == null)
		{
			failReason = "IsLockedForSide requires hex";
			return false;
		}
		if (!TryResolvePushedUnitSideIndex(pushedUnit, out var sideIndex, out failReason))
			return false;

		var names = GameSymbols.DirectStateLaws.HexIsLockedForSideMembers;
		if (names == null || names.Length == 0)
		{
			failReason = "HexIsLockedForSideMembers empty";
			return false;
		}

		const int allegAll = 2; // ehh.bdpe push path ETargetAllegiance
		for (var current = hex.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo method = null;
				try
				{
					foreach (var candidate in current.GetMethods(flags))
					{
						if (!string.Equals(candidate.Name, name, StringComparison.Ordinal))
							continue;
						var parameters = candidate.GetParameters();
						// Proven signature: bool bcyf(int side, bool ignoreUnits, ETargetAllegiance alleg).
						if (parameters.Length != 3)
							continue;
						if (parameters[0].ParameterType != typeof(int)
						    && parameters[0].ParameterType != typeof(Int32))
							continue;
						if (parameters[1].ParameterType != typeof(bool))
							continue;
						if (candidate.ReturnType != typeof(bool))
							continue;
						var allegType = parameters[2].ParameterType;
						if (!allegType.IsEnum && allegType != typeof(int) && allegType != typeof(Int32))
							continue;
						method = candidate;
						break;
					}
				}
				catch
				{
					continue;
				}
				if (method == null)
					continue;
				try
				{
					var allegParam = method.GetParameters()[2];
					object allegArg = allegAll;
					if (allegParam.ParameterType.IsEnum)
						allegArg = Enum.ToObject(allegParam.ParameterType, allegAll);
					var result = method.Invoke(hex, new[] { sideIndex, false, allegArg });
					if (result is bool flag)
					{
						locked = flag;
						failReason = null;
						return true;
					}
					failReason = "IsLockedForSide returned non-bool";
					return false;
				}
				catch (Exception ex)
				{
					failReason = "IsLockedForSide invoke failed: " + ex.GetType().Name + ": " + ex.Message;
					return false;
				}
			}
		}
		failReason = "IsLockedForSide method unresolved";
		return false;
	}

	private static bool TryResolvePushedUnitSideIndex(object unit, out int sideIndex, out string failReason)
	{
		sideIndex = -1;
		failReason = null;
		if (unit == null)
		{
			failReason = "pushed unit null for side resolve";
			return false;
		}
		var snapshots = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		for (var i = 0; i < snapshots.Count; i++)
		{
			var snap = snapshots[i];
			if (snap.Unit == null || !UnitsMatch(snap.Unit, unit))
				continue;
			if (snap.SideIndexKnown)
			{
				sideIndex = snap.SideIndex;
				return true;
			}
		}
		if (TryReadExactMember(unit, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out var side)
		    && side != null
		    && TryReadIntMember(side, GameSymbols.BattleEventLaws.BattleSideWrapperLocalSideIndexMembers, out sideIndex))
			return true;
		failReason = "pushed unit side index unresolved";
		return false;
	}

	private static bool UnitsMatch(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		if (left is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase leftNative
		    && right is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase rightNative
		    && leftNative.Pointer != IntPtr.Zero
		    && leftNative.Pointer == rightNative.Pointer)
			return true;
		return false;
	}

	private static bool TryReadHexNeighbourFields(object hex, out object[] neighbours, out string failReason)
	{
		return Homm3DirectStateHexNeighbourNative.TryReadNeighbourSlots(hex, out neighbours, out failReason);
	}

	private static bool TryMatchNeighbourCoordinates(object[] neighbours, int x, int z, out object neighbour)
	{
		neighbour = null;
		if (neighbours == null)
			return false;
		for (var i = 0; i < neighbours.Length; i++)
		{
			var candidate = neighbours[i];
			if (candidate == null)
				continue;
			if (!TryReadHexCoordinates(candidate, out var nx, out var nz) || nx != x || nz != z)
				continue;
			neighbour = candidate;
			return true;
		}
		return false;
	}

	private static bool HexesMatch(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		if (left is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase leftNative
		    && right is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase rightNative
		    && leftNative.Pointer != IntPtr.Zero
		    && leftNative.Pointer == rightNative.Pointer)
			return true;
		return TryReadHexCoordinates(left, out var lx, out var lz)
		       && TryReadHexCoordinates(right, out var rx, out var rz)
		       && lx == rx
		       && lz == rz;
	}

	private static int HexDistance(int ax, int az, int bx, int bz)
	{
		var dx = ax - bx;
		var dz = az - bz;
		return (Math.Abs(dx) + Math.Abs(dz) + Math.Abs(dx + dz)) / 2;
	}

	private static bool TryReadHexCoordinates(object hex, out int x, out int z)
	{
		x = 0;
		z = 0;
		return TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexXMembers, out x)
		       && TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexZMembers, out z);
	}

	private static bool TryReadHexIndex(object hex, out int index)
	{
		return TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexIndexMembers, out index);
	}

	private static bool TryReadIntMember(object target, string[] names, out int value)
	{
		value = 0;
		if (!TryReadExactMember(target, names, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadExactMember(object target, string[] names, out object value)
	{
		value = null;
		if (target == null || names == null)
			return false;
		for (var current = target.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
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
						value = field.GetValue(target);
						return true;
					}
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(target, null);
						return true;
					}
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						value = method.Invoke(target, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static long ComposeToken(long correlationId, object target, string discriminator)
	{
		unchecked
		{
			var targetKey = Homm3DirectStateIdentity.ResolveKeyOrZero(target);
			var discriminatorKey = discriminator == null ? 0 : StringComparer.Ordinal.GetHashCode(discriminator);
			return (correlationId * 397L) ^ (targetKey << 16) ^ (uint)discriminatorKey;
		}
	}

	private static bool Fail(
		Homm3DirectStateTransaction transaction,
		string reason,
		out string failReason)
	{
		string rollbackFailure = null;
		transaction?.Rollback(out rollbackFailure);
		failReason = rollbackFailure == null ? reason : reason + "; rollback failed: " + rollbackFailure;
		return false;
	}
}
