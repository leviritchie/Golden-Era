using System;
using System.Collections.Generic;
using System.Threading;

namespace OfflineUnlockMod;

/// <summary>
/// Shared parameterized fixture harness. It records the same bounded counters
/// for every family and exposes explicit fault-injection and proof labels.
/// Gameplay flags remain opt-in; source validation does not promote runtime
/// behavior claims.
/// </summary>
internal static class Homm3RuntimeMechanicFixtureHarness
{
	private sealed class AggregateFixtureLedger : IHomm3DirectStateLedger
	{
		internal int RestoreCount;

		public bool TryRestore(Homm3DirectStateJournalEntry entry, out string failReason)
		{
			RestoreCount++;
			failReason = null;
			return true;
		}
	}

	internal const string FaultInjectionFlag = "homm3_runtime_direct_state_fault_injection.flag";
	internal const string AggregateStressFlag = "homm3_runtime_aggregate_pilot.flag";

	private static readonly object Gate = new();
	private static readonly HashSet<int> DirtyHexes = new();
	private static readonly HashSet<long> DirtyUnits = new();
	private static int _distinctHookCount;
	private static int _presentationRetries;
	private static int _faultInjections;
	private static int _aggregateFaultsRemaining;
	private static int _sourceFixturesValidated;
	private static string _lastFailure = "none";

	internal static bool TryValidateSourceFixtures(out string failReason)
	{
		if (!Homm3DirectStateAdapterManifest.ValidateExhaustive(out failReason))
		{
			RecordFailure(failReason);
			return false;
		}
		var records = Homm3DirectStateAdapterManifest.Snapshot();
		var stableIds = new HashSet<int>();
		var operations = new HashSet<Homm3DirectStateOperation>();
		for (var i = 0; i < records.Length; i++)
		{
			var record = records[i];
			if (record == null || !stableIds.Add((int)record.AdapterId))
			{
				failReason = "fixture manifest has a null or duplicate stable AdapterId";
				RecordFailure(failReason);
				return false;
			}
			if (record.Caps.MaxRootWork <= 0
			    || record.Caps.MaxDepth <= 0
			    || record.Caps.MaxJournalEntries <= 0
			    || record.Caps.MaxFanout <= 0
			    || record.Caps.MaxDirtyIdentities <= 0
			    || record.Caps.MaxQueueSpan <= 0)
			{
				failReason = "fixture manifest has non-positive caps for " + record.AdapterId;
				RecordFailure(failReason);
				return false;
			}
			for (var operationIndex = 0; operationIndex < record.Operations.Length; operationIndex++)
			{
				if (!operations.Add(record.Operations[operationIndex]))
				{
					failReason = "operation has more than one typed adapter owner: " + record.Operations[operationIndex];
					RecordFailure(failReason);
					return false;
				}
			}
		}
		var expectedOperationCount = Enum.GetValues(typeof(Homm3DirectStateOperation)).Length - 1;
		if (operations.Count != expectedOperationCount)
		{
			failReason = "fixture operation coverage is " + operations.Count + " but expected " + expectedOperationCount;
			RecordFailure(failReason);
			return false;
		}
		Interlocked.Exchange(ref _sourceFixturesValidated, records.Length);
		if (!TryRunHeadlessReplayScenarios(out var replayFailure))
		{
			failReason = replayFailure;
			RecordFailure(failReason);
			return false;
		}
		if (!TryValidateMovementPushIdentityContract(out var identityFailure))
		{
			failReason = identityFailure;
			RecordFailure(failReason);
			return false;
		}
		failReason = null;
		return true;
	}

	/// <summary>
	/// Catches donor-scaffold vs custom-SID binding gaps without combat.
	/// Source-validated only; does not prove live Il2Cpp wrapper identity.
	/// </summary>
	internal static bool TryValidateMovementPushIdentityContract(out string failReason)
	{
		const string donorSid = "griffin_upg";
		const string expectedCustomSid = "h3_bellwether_armadillo";
		var resolved = Homm3BattleUnitLawOwnerRegistry.ResolveMechanicConfigSid(donorSid);
		if (!string.Equals(resolved, expectedCustomSid, StringComparison.Ordinal))
		{
			// When the movement pilot is inactive, reverse-map may stay on donor or another
			// unique custom owner of griffin_upg. Only fail closed when an active binding exists.
			if (Homm3RuntimeMechanicRegistry.TryGetActiveBinding(expectedCustomSid, out _))
			{
				failReason =
					"MovementPush identity: donor '"
					+ donorSid
					+ "' must resolve to '"
					+ expectedCustomSid
					+ "' while its mechanic binding is active, got '"
					+ (resolved ?? "null")
					+ "'";
				return false;
			}
		}
		else if (Homm3RuntimeMechanicRegistry.HasActiveMechanics
		         && Homm3RuntimeMechanicRegistry.TryGetActiveBinding(expectedCustomSid, out var binding)
		         && binding.UnitMechanicIndex < 0)
		{
			failReason = "MovementPush identity: " + expectedCustomSid + " active binding missing unit mechanic index";
			return false;
		}

		if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(expectedCustomSid, out var indexes)
		    || indexes == null
		    || indexes.Length == 0)
		{
			if (Homm3RuntimeMechanicRegistry.TryGetActiveBinding(expectedCustomSid, out _))
			{
				failReason = "MovementPush identity: " + expectedCustomSid + " has binding but no unit mechanic indexes";
				return false;
			}
		}
		else
		{
			var foundPush = false;
			for (var i = 0; i < indexes.Length; i++)
			{
				if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic))
					continue;
				if (mechanic.Operation == Homm3DirectStateOperation.MovementPush
				    && string.Equals(mechanic.Trigger, "damageApplied", StringComparison.Ordinal)
				    && string.Equals(mechanic.AbilityName, "Shoulder Check", StringComparison.Ordinal))
				{
					foundPush = true;
					break;
				}
			}
			if (!foundPush && Homm3RuntimeMechanicRegistry.TryGetActiveBinding(expectedCustomSid, out _))
			{
				failReason =
					"MovementPush identity: active "
					+ expectedCustomSid
					+ " mechanics missing damageApplied Shoulder Check MovementPush";
				return false;
			}
		}

		failReason = null;
		return true;
	}

	/// <summary>
	/// Model-backed headless replay of production write semantics.
	/// Does not launch combat; proof label is source-replay-validated only
	/// (startup smoke / source-replay). Never combat-proven.
	/// </summary>
	internal static bool TryRunHeadlessReplayScenarios(out string failReason)
	{
		var previous = NativeCombatWriteGateway.ActiveWriteBackend;
		var model = new ModelCombatWriteBackend();
		try
		{
			NativeCombatWriteGateway.UseWriteBackend(model);

			// ≥1 accept case per operation family via shared write primitives.
			var records = Homm3DirectStateAdapterManifest.Snapshot();
			for (var i = 0; i < records.Length; i++)
			{
				var record = records[i];
				for (var opIndex = 0; opIndex < record.Operations.Length; opIndex++)
				{
					var operation = record.Operations[opIndex];
					if (!TryReplayAcceptOperation(model, operation, out failReason))
						return false;
				}
			}

			// Fixed blocked occupancy.
			var hex = "hex:blocked";
			var unitA = new object();
			var unitB = new object();
			if (!model.TrySetOccupancy(hex, unitA, out failReason))
				return false;
			if (model.TrySetOccupancy(hex, unitB, out var occupancyFailure)
			    || string.IsNullOrWhiteSpace(occupancyFailure))
			{
				failReason = "occupancy blocked case did not fail closed";
				return false;
			}

			// Fixed queue boundary.
			var queue = "queue:boundary";
			for (var i = 0; i < 4; i++)
			{
				if (!model.TryInsertListItem(queue, "entry:" + i, i, out failReason))
					return false;
			}
			if (model.TryInsertListItem(queue, "overflow", 99, out var queueFailure)
			    || string.IsNullOrWhiteSpace(queueFailure))
			{
				failReason = "queue boundary case did not fail closed";
				return false;
			}

			// Fixed rollback: damage commit mismatch must refuse.
			var damage = 10;
			var badMutation = new PreparedDamageMutation(0, 9, 11);
			if (NativeCombatWriteGateway.TryCommitPreparedDamage(ref damage, badMutation) || damage != 10)
			{
				failReason = "rollback/mismatch damage commit did not refuse";
				return false;
			}

			// Fixed fault: deferred intent rejects empty kind.
			if (model.TryRecordDeferredIntent("", null, out var faultFailure)
			    || string.IsNullOrWhiteSpace(faultFailure))
			{
				failReason = "fault deferred-intent case did not fail closed";
				return false;
			}

			// Budget boundary: oversized reorder index.
			if (model.TryReorderListItem(queue, "entry:0", 99, out var budgetFailure)
			    || string.IsNullOrWhiteSpace(budgetFailure))
			{
				failReason = "budget/queue reorder boundary did not fail closed";
				return false;
			}

			failReason = null;
			return true;
		}
		finally
		{
			NativeCombatWriteGateway.UseWriteBackend(previous);
		}
	}

	private static bool TryReplayAcceptOperation(
		ModelCombatWriteBackend model,
		Homm3DirectStateOperation operation,
		out string failReason)
	{
		failReason = null;
		var target = "target:" + operation;
		switch (operation)
		{
			case Homm3DirectStateOperation.DamageFlatDelta:
			{
				var damage = 10;
				var mutation = new PreparedDamageMutation(0, 10, 11);
				if (!NativeCombatWriteGateway.TryCommitPreparedDamage(ref damage, mutation) || damage != 11)
				{
					failReason = "DamageFlatDelta accept replay failed";
					return false;
				}
				return true;
			}
			case Homm3DirectStateOperation.FocusGrant:
			case Homm3DirectStateOperation.FocusSpend:
			case Homm3DirectStateOperation.FocusSet:
			case Homm3DirectStateOperation.CooldownSet:
			case Homm3DirectStateOperation.CooldownReduce:
			case Homm3DirectStateOperation.CooldownIncrease:
			case Homm3DirectStateOperation.CooldownCharges:
			case Homm3DirectStateOperation.CooldownCastCounter:
			case Homm3DirectStateOperation.StatusApply:
			case Homm3DirectStateOperation.StatusRefresh:
			case Homm3DirectStateOperation.StatusTick:
			case Homm3DirectStateOperation.StatusExpire:
			case Homm3DirectStateOperation.StatusRemove:
			case Homm3DirectStateOperation.MovementSetImmobile:
			case Homm3DirectStateOperation.AuraDefine:
			case Homm3DirectStateOperation.AuraRefresh:
			case Homm3DirectStateOperation.AuraRemove:
			case Homm3DirectStateOperation.KillConfirm:
			case Homm3DirectStateOperation.AllyDeathObserve:
			case Homm3DirectStateOperation.CastChain:
			case Homm3DirectStateOperation.CorpseCreate:
			case Homm3DirectStateOperation.CorpseConsume:
			case Homm3DirectStateOperation.TrapSpawn:
			case Homm3DirectStateOperation.TrapTrigger:
			case Homm3DirectStateOperation.TrapDespawn:
			case Homm3DirectStateOperation.SummonCreate:
				if (!NativeCombatWriteGateway.TryWriteIntMember(target, operation.ToString(), 1, out failReason))
					return false;
				return true;
			case Homm3DirectStateOperation.MovementPush:
			case Homm3DirectStateOperation.MovementPull:
			case Homm3DirectStateOperation.MovementTeleport:
			{
				var hex = "hex:" + operation;
				var unit = new object();
				if (!model.TrySetOccupancy(hex, unit, out failReason)
				    || !model.TryClearOccupancy(hex, out failReason)
				    || !model.TrySetOccupancy(hex + ":dest", unit, out failReason))
					return false;
				return true;
			}
			case Homm3DirectStateOperation.NestedReflection:
			case Homm3DirectStateOperation.NestedRedirection:
			case Homm3DirectStateOperation.NestedSplash:
				if (!model.TryRecordDeferredIntent(operation.ToString(), target, out failReason))
					return false;
				return true;
			case Homm3DirectStateOperation.ActionQueueInsert:
			{
				var queue = "queue:" + operation;
				if (!model.TryInsertListItem(queue, target, 0, out failReason))
					return false;
				return true;
			}
			case Homm3DirectStateOperation.ActionQueueRemove:
			{
				var queue = "queue:" + operation;
				if (!model.TryInsertListItem(queue, target, 0, out failReason)
				    || !model.TryRemoveListItem(queue, target, out failReason))
					return false;
				return true;
			}
			case Homm3DirectStateOperation.TurnOrderReorder:
			{
				var queue = "queue:" + operation;
				if (!model.TryInsertListItem(queue, "a", 0, out failReason)
				    || !model.TryInsertListItem(queue, "b", 1, out failReason)
				    || !model.TryReorderListItem(queue, "a", 1, out failReason))
					return false;
				return true;
			}
			default:
				failReason = "headless replay missing accept case for " + operation;
				return false;
		}
	}

	internal static bool ShouldInjectFailure(string stage)
	{
		var aggregateFault = Interlocked.CompareExchange(ref _aggregateFaultsRemaining, 0, 0) > 0;
		if (!aggregateFault && !Homm3DiagnosticFlags.IsEnabled(FaultInjectionFlag))
			return false;
		if (aggregateFault)
			Interlocked.Decrement(ref _aggregateFaultsRemaining);
		Interlocked.Increment(ref _faultInjections);
		RecordFailure("fault injection requested at " + (stage ?? "unknown"));
		return true;
	}

	internal static bool TryRunAggregateStress(out string report, out string failReason)
	{
		report = null;
		failReason = null;
		if (!Homm3DiagnosticFlags.IsEnabled(AggregateStressFlag))
		{
			failReason = "aggregate stress flag is not enabled";
			return false;
		}
		for (var adapterValue = 1; adapterValue <= Homm3DirectStateAdapterManifest.Count; adapterValue++)
		{
			if (!Homm3RuntimeMechanicRegistry.IsAdapterActive((Homm3DirectStateAdapterId)adapterValue))
			{
				failReason = "aggregate stress adapter is not active: " + (Homm3DirectStateAdapterId)adapterValue;
				return false;
			}
		}

		ClearForBattle();
		var scope = new object();
		var receiver = new object();
		var caster = new object();
		var statusSid = "diagnostic.aggregate.rollback";

		Interlocked.Exchange(ref _aggregateFaultsRemaining, 1);
		var faultRequest = new Homm3DirectStatusRequest(statusSid, 1, 2, 3, false, 1);
		if (Homm3DirectStateAdapters.TryApplyStatus(scope, receiver, caster, faultRequest, out var faultFailure)
		    || string.IsNullOrWhiteSpace(faultFailure)
		    || Homm3BattleLocalLawState.SnapshotDirectStatuses(4).Count != 0)
		{
			failReason = "fault-injected status transaction did not roll back cleanly";
			return false;
		}
		if (!Homm3DirectStateAdapters.TryApplyStatus(scope, receiver, caster, faultRequest, out failReason)
		    || Homm3BattleLocalLawState.SnapshotDirectStatuses(4).Count != 1
		    || !Homm3DirectStateAdapters.TryRemoveStatus(scope, receiver, statusSid, out failReason)
		    || Homm3BattleLocalLawState.SnapshotDirectStatuses(4).Count != 0)
		{
			failReason ??= "status commit/remove fixture did not reconcile";
			return false;
		}

		if (!TryExerciseDepthBudget(scope, out failReason)
		    || !TryExerciseRootWorkBudget(scope, out failReason)
		    || !TryExerciseJournalBudget(scope, out failReason)
		    || !TryExerciseFanoutBudget(scope, out failReason))
			return false;

		var unitTokens = new object[40];
		for (var i = 0; i < 40; i++)
		{
			unitTokens[i] = new object();
			RecordDirtyUnit(unitTokens[i]);
			RecordDirtyHex(i);
		}
		RecordPresentationRetry();
		RecordPresentationRetry();

		var beforeCleanup = SnapshotJson();
		var transactionCounters = BattleCombatTransactionManager.SnapshotCountersJson();
		var directState = Homm3BattleLocalLawState.SnapshotDirectStateJson();
		var generationBeforeCleanup = Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration;
		ClearAggregateBattleState("aggregate stress battle one cleanup");
		var generationAfterFirstCleanup = Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration;
		if (!IsAggregateStateClean())
		{
			failReason = "aggregate stress first battle cleanup left direct state";
			return false;
		}
		ClearAggregateBattleState("aggregate stress battle two cleanup");
		var generationAfterSecondCleanup = Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration;
		if (!IsAggregateStateClean()
		    || generationAfterFirstCleanup <= generationBeforeCleanup
		    || generationAfterSecondCleanup <= generationAfterFirstCleanup)
		{
			failReason = "aggregate stress repeated cleanup was not idempotent and generation advancing";
			return false;
		}

		report = "{\"beforeCleanup\":" + beforeCleanup
		         + ",\"transactions\":" + transactionCounters
		         + ",\"directState\":" + directState
		         + ",\"afterCleanup\":" + SnapshotJson()
		         + ",\"generationBeforeCleanup\":" + generationBeforeCleanup
		         + ",\"generationAfterFirstCleanup\":" + generationAfterFirstCleanup
		         + ",\"generationAfterSecondCleanup\":" + generationAfterSecondCleanup
		         + "}";
		return true;
	}

	private static bool TryExerciseDepthBudget(object scope, out string failReason)
	{
		var transactions = new Homm3DirectStateTransaction[8];
		var count = 0;
		try
		{
			for (; count < transactions.Length; count++)
			{
				if (!BattleCombatTransactionManager.TryBegin(
					    scope,
					    Homm3DirectStateAdapterId.Status,
					    Homm3DirectStateOperation.StatusApply,
					    1,
					    1,
					    out transactions[count],
					    out failReason))
					return false;
			}
			if (BattleCombatTransactionManager.TryBegin(
				    scope,
				    Homm3DirectStateAdapterId.Status,
				    Homm3DirectStateOperation.StatusApply,
				    1,
				    1,
				    out var overflow,
				    out _))
			{
				overflow.Dispose();
				failReason = "depth budget accepted a ninth transaction";
				return false;
			}
			failReason = null;
			return true;
		}
		finally
		{
			for (var i = count - 1; i >= 0; i--)
			{
				transactions[i]?.Rollback(out _);
				transactions[i]?.Dispose();
			}
		}
	}

	private static bool TryExerciseRootWorkBudget(object scope, out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Aura,
			    Homm3DirectStateOperation.AuraDefine,
			    1,
			    64,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			if (BattleCombatTransactionManager.TryBegin(
				    scope,
				    Homm3DirectStateAdapterId.Aura,
				    Homm3DirectStateOperation.AuraDefine,
				    1,
				    1,
				    out var overflow,
				    out _))
			{
				overflow.Dispose();
				failReason = "root work budget accepted work after exhaustion";
				return false;
			}
			transaction.Rollback(out _);
		}
		failReason = null;
		return true;
	}

	private static bool TryExerciseJournalBudget(object scope, out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Status,
			    Homm3DirectStateOperation.StatusApply,
			    64,
			    1,
			    out var transaction,
			    out failReason))
			return false;
		var ledger = new AggregateFixtureLedger();
		using (transaction)
		{
			for (var i = 0; i < 64; i++)
			{
				if (!transaction.TryRecordLedger(
					    ledger,
					    Homm3DirectStateJournalOpcode.StatusLedger,
					    "aggregate",
					    i,
					    0,
					    null,
					    out failReason))
					return false;
			}
			if (transaction.TryRecordLedger(
				    ledger,
				    Homm3DirectStateJournalOpcode.StatusLedger,
				    "overflow",
				    64,
				    0,
				    null,
				    out _))
			{
				failReason = "journal accepted an entry beyond reserved capacity";
				return false;
			}
			if (!transaction.Rollback(out failReason) || ledger.RestoreCount != 64)
			{
				failReason ??= "journal rollback did not restore all entries";
				return false;
			}
		}
		failReason = null;
		return true;
	}

	private static bool TryExerciseFanoutBudget(object scope, out string failReason)
	{
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    Homm3DirectStateAdapterId.Cast,
			    Homm3DirectStateOperation.CastChain,
			    1,
			    1,
			    out var transaction,
			    out failReason))
			return false;
		using (transaction)
		{
			for (var i = 0; i < 16; i++)
			{
				var item = new Homm3DirectStateWorkItem(
					Homm3DirectStateAdapterId.Cast,
					Homm3DirectStateOperation.CastChain,
					scope,
					null,
					null,
					null,
					i,
					transaction.CorrelationId,
					transaction.Generation);
				if (!transaction.TryEnqueueChild(item, out failReason))
					return false;
			}
			var overflow = new Homm3DirectStateWorkItem(
				Homm3DirectStateAdapterId.Cast,
				Homm3DirectStateOperation.CastChain,
				scope,
				null,
				null,
				null,
				16,
				transaction.CorrelationId,
				transaction.Generation);
			if (transaction.TryEnqueueChild(overflow, out _))
			{
				failReason = "fan-out budget accepted a seventeenth child";
				return false;
			}
			while (BattleCombatTransactionManager.TryDequeueChild(out _))
			{
			}
			transaction.Rollback(out _);
		}
		failReason = null;
		return true;
	}

	private static void ClearAggregateBattleState(string reason)
	{
		BattleCombatTransactionManager.AbortRoot(reason);
		BattleCombatTransactionManager.ResetForBattleCleanup();
		ClearForBattle();
		Homm3BattleLocalLawState.ClearBattleSideIndexedState(reason);
	}

	private static bool IsAggregateStateClean()
	{
		return Homm3BattleLocalLawState.SnapshotDirectStatuses(1).Count == 0
		       && Homm3BattleLocalLawState.SnapshotDirectAuras(1).Count == 0
		       && SnapshotJson().Contains("\"dirtyHexes\":0")
		       && SnapshotJson().Contains("\"dirtyUnits\":0")
		       && SnapshotJson().Contains("\"presentationRetries\":0")
		       && SnapshotJson().Contains("\"faultInjections\":0");
	}

	internal static void RecordDistinctHookCount(int count)
	{
		Interlocked.Exchange(ref _distinctHookCount, Math.Max(0, count));
	}

	internal static void RecordDirtyHex(int key)
	{
		lock (Gate)
		{
			if (DirtyHexes.Count < 32)
				DirtyHexes.Add(key);
		}
	}

	internal static void RecordDirtyUnit(object unit)
	{
		if (unit == null)
			return;
		if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var key, out _))
			return;
		lock (Gate)
		{
			if (DirtyUnits.Count < 32)
				DirtyUnits.Add(key);
		}
	}

	internal static void RecordPresentationRetry()
	{
		Interlocked.Increment(ref _presentationRetries);
	}

	internal static void RecordFailure(string failure)
	{
		lock (Gate)
			_lastFailure = failure ?? "unknown";
	}

	internal static string SnapshotJson()
	{
		int dirtyHexes;
		int dirtyUnits;
		string lastFailure;
		lock (Gate)
		{
			dirtyHexes = DirtyHexes.Count;
			dirtyUnits = DirtyUnits.Count;
			lastFailure = _lastFailure;
		}
		return "{\"sourceFixturesValidated\":" + Volatile.Read(ref _sourceFixturesValidated)
		       + ",\"distinctHooks\":" + Volatile.Read(ref _distinctHookCount)
		       + ",\"dirtyHexes\":" + dirtyHexes
		       + ",\"dirtyUnits\":" + dirtyUnits
		       + ",\"presentationRetries\":" + Volatile.Read(ref _presentationRetries)
		       + ",\"faultInjections\":" + Volatile.Read(ref _faultInjections)
		       + ",\"lastFailure\":\"" + EscapeJson(lastFailure) + "\"}";
	}

	internal static void ClearForBattle()
	{
		lock (Gate)
		{
			DirtyHexes.Clear();
			DirtyUnits.Clear();
			_lastFailure = "none";
		}
		Interlocked.Exchange(ref _presentationRetries, 0);
		Interlocked.Exchange(ref _faultInjections, 0);
	}

	private static string EscapeJson(string value)
	{
		return (value ?? string.Empty)
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n");
	}
}
