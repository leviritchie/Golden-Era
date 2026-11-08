using System;
using System.Collections;
using System.Runtime.CompilerServices;
using System.Threading;

namespace OfflineUnlockMod;

internal readonly struct Homm3DirectStateWorkItem
{
	internal Homm3DirectStateWorkItem(
		Homm3DirectStateAdapterId adapterId,
		Homm3DirectStateOperation operation,
		object scope,
		object source,
		object target,
		object payload,
		int value,
		long correlationId,
		int generation)
	{
		AdapterId = adapterId;
		Operation = operation;
		Scope = scope;
		Source = source;
		Target = target;
		Payload = payload;
		Value = value;
		CorrelationId = correlationId;
		Generation = generation;
	}

	internal Homm3DirectStateAdapterId AdapterId { get; }
	internal Homm3DirectStateOperation Operation { get; }
	internal object Scope { get; }
	internal object Source { get; }
	internal object Target { get; }
	internal object Payload { get; }
	internal int Value { get; }
	internal long CorrelationId { get; }
	internal int Generation { get; }
}

internal readonly struct Homm3DirectStateJournalEntry
{
	internal Homm3DirectStateJournalEntry(
		Homm3DirectStateJournalOpcode opcode,
		object target,
		string memberId,
		int index,
		int oldInt,
		object oldValue,
		object[] oldItems)
	{
		Opcode = opcode;
		Target = target;
		MemberId = memberId;
		Index = index;
		OldInt = oldInt;
		OldValue = oldValue;
		OldItems = oldItems;
	}

	internal Homm3DirectStateJournalOpcode Opcode { get; }
	internal object Target { get; }
	internal string MemberId { get; }
	internal int Index { get; }
	internal int OldInt { get; }
	internal object OldValue { get; }
	internal object[] OldItems { get; }
}

internal interface IHomm3DirectStateLedger
{
	bool TryRestore(Homm3DirectStateJournalEntry entry, out string failReason);
}

internal sealed class Homm3DirectStateRootBudget
{
	internal Homm3DirectStateRootBudget(long correlationId, Homm3DirectStateAdapterCaps caps)
	{
		CorrelationId = correlationId;
		MaxRootWork = caps.MaxRootWork;
		RemainingWork = caps.MaxRootWork;
		RemainingJournal = caps.MaxJournalEntries;
		RemainingFanout = caps.MaxFanout;
		MaxDepth = caps.MaxDepth;
		MaxJournalEntries = caps.MaxJournalEntries;
		WorkItems = new Homm3DirectStateWorkItem[caps.MaxFanout];
		Journal = new Homm3DirectStateJournalEntry[Math.Max(1, caps.MaxJournalEntries)];
	}

	internal long CorrelationId;
	internal int MaxRootWork;
	internal int RemainingWork;
	internal int RemainingJournal;
	internal int RemainingFanout;
	internal int MaxDepth;
	internal int MaxJournalEntries;
	internal int Depth;
	internal int WorkCount;
	internal int WorkReadIndex;
	internal int PendingChildCount;
	internal int JournalCount;
	internal readonly Homm3DirectStateWorkItem[] WorkItems;
	internal readonly Homm3DirectStateJournalEntry[] Journal;
}

/// <summary>
/// One transaction envelope for all battle direct-state writes. The reversible
/// phase holds the shared battle-state lock. Child work stays pending on the root
/// until the root correlation hard-accepts at depth 0, so beforeCommit rollback
/// cannot leave deferred damage/cast queued. Native callbacks and draining happen
/// only after Commit releases the lock and CompleteCurrentLevel reaches depth 0.
/// </summary>
internal sealed class Homm3DirectStateTransaction : IDisposable
{
	private readonly object _syncRoot;
	private readonly Homm3DirectStateRootBudget _root;
	private readonly int _journalMark;
	private readonly int _pendingChildMark;
	private int _pendingChildReservations;
	private bool _completed;
	private bool _lockHeld;
	private bool _accepted;

	internal Homm3DirectStateTransaction(
		object syncRoot,
		Homm3DirectStateRootBudget root,
		Homm3DirectStateAdapterId adapterId,
		Homm3DirectStateOperation operation,
		object scope,
		int generation,
		int reservedJournal)
	{
		_syncRoot = syncRoot;
		_root = root;
		AdapterId = adapterId;
		Operation = operation;
		Scope = scope;
		Generation = generation;
		CorrelationId = root.CorrelationId;
		ReservedJournal = reservedJournal;
		_journalMark = root.JournalCount;
		_pendingChildMark = root.PendingChildCount;
		Monitor.Enter(_syncRoot);
		_lockHeld = true;
	}

	internal Homm3DirectStateAdapterId AdapterId { get; }
	internal Homm3DirectStateOperation Operation { get; }
	internal object Scope { get; }
	internal int Generation { get; }
	internal long CorrelationId { get; }
	internal int ReservedJournal { get; }
	internal int JournalCount => _root.JournalCount - _journalMark;

	internal bool TryRecordNativeInt(object target, string memberId, int oldValue, out string failReason)
	{
		return TryAppend(
			new Homm3DirectStateJournalEntry(
				Homm3DirectStateJournalOpcode.NativeIntMember,
				target,
				memberId,
				-1,
				oldValue,
				null,
				null),
			out failReason);
	}

	internal bool TryRecordNativeObject(object target, string memberId, object oldValue, out string failReason)
	{
		return TryAppend(
			new Homm3DirectStateJournalEntry(
				Homm3DirectStateJournalOpcode.NativeObjectMember,
				target,
				memberId,
				-1,
				0,
				oldValue,
				null),
			out failReason);
	}

	internal bool TryRecordListSnapshot(IList list, out string failReason)
	{
		if (list == null)
		{
			failReason = "native list snapshot target is null";
			return false;
		}
		var oldItems = new object[list.Count];
		for (var i = 0; i < oldItems.Length; i++)
			oldItems[i] = list[i];
		return TryAppend(
			new Homm3DirectStateJournalEntry(
				Homm3DirectStateJournalOpcode.NativeListSnapshot,
				list,
				null,
				-1,
				0,
				null,
				oldItems),
			out failReason);
	}

	internal bool TryRecordOccupancySnapshot(Homm3MovementRollbackSnapshot snapshot, out string failReason)
	{
		if (snapshot == null)
		{
			failReason = "movement rollback snapshot is null";
			return false;
		}
		return TryAppend(
			new Homm3DirectStateJournalEntry(
				Homm3DirectStateJournalOpcode.Occupancy,
				snapshot,
				null,
				-1,
				0,
				null,
				null),
			out failReason);
	}

	internal bool TryRecordLedger(
		IHomm3DirectStateLedger ledger,
		Homm3DirectStateJournalOpcode opcode,
		string memberId,
		int index,
		int oldInt,
		object oldValue,
		out string failReason)
	{
		if (ledger == null)
		{
			failReason = "direct-state ledger is null";
			return false;
		}
		return TryAppend(
			new Homm3DirectStateJournalEntry(opcode, ledger, memberId, index, oldInt, oldValue, null),
			out failReason);
	}

	internal bool TryEnqueueChild(Homm3DirectStateWorkItem workItem, out string failReason)
	{
		if (_completed)
		{
			failReason = "transaction is already completed";
			return false;
		}
		if (_root.RemainingWork <= 0 || _root.RemainingFanout <= 0)
		{
			failReason = "root correlation work/fan-out budget exhausted";
			return false;
		}
		if (_root.PendingChildCount >= _root.WorkItems.Length)
		{
			failReason = "root correlation child queue is full";
			return false;
		}
		_root.RemainingWork--;
		_root.RemainingFanout--;
		_root.WorkItems[_root.PendingChildCount++] = workItem;
		_pendingChildReservations++;
		BattleCombatTransactionManager.RecordFanoutHighWater(_root.PendingChildCount);
		BattleCombatTransactionManager.RecordRootWorkHighWater(_root.MaxRootWork - _root.RemainingWork);
		failReason = null;
		return true;
	}

	internal bool Commit(out string failReason)
	{
		if (_completed)
		{
			failReason = "transaction is already completed";
			return false;
		}
		if (Generation != Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration)
		{
			RollbackInternal(out _);
			failReason = "battle generation changed before transaction commit";
			return false;
		}
		if (Homm3RuntimeMechanicFixtureHarness.ShouldInjectFailure(
			    AdapterId + "." + Operation + ".beforeCommit"))
		{
			RollbackInternal(out var rollbackFailure);
			failReason = rollbackFailure == null
				? "fixture fault injected before commit"
				: "fixture fault injected before commit; rollback failed: " + rollbackFailure;
			return false;
		}
		_completed = true;
		_accepted = true;
		ReleaseLock();
		BattleCombatTransactionManager.RecordCommitted(JournalCount);
		failReason = null;
		return true;
	}

	internal bool Rollback(out string failReason)
	{
		if (_completed)
		{
			failReason = "transaction is already completed";
			return false;
		}
		return RollbackInternal(out failReason);
	}

	public void Dispose()
	{
		if (!_completed)
			RollbackInternal(out _);
		BattleCombatTransactionManager.CompleteCurrentLevel(_accepted);
	}

	private bool TryAppend(Homm3DirectStateJournalEntry entry, out string failReason)
	{
		if (_completed)
		{
			failReason = "transaction is already completed";
			return false;
		}
		if (_root.JournalCount >= _root.Journal.Length
		    || JournalCount >= ReservedJournal)
		{
			failReason = "reserved transaction journal capacity exhausted";
			return false;
		}
		_root.Journal[_root.JournalCount++] = entry;
		BattleCombatTransactionManager.RecordJournalHighWater(_root.JournalCount);
		failReason = null;
		return true;
	}

	private bool RollbackInternal(out string failReason)
	{
		string firstFailure = null;
		for (var i = _root.JournalCount - 1; i >= _journalMark; i--)
		{
			if (!NativeCombatWriteGateway.TryRestore(_root.Journal[i], out var restoreFailure))
				firstFailure ??= restoreFailure;
			_root.Journal[i] = default;
		}
		_root.JournalCount = _journalMark;

		// Drop children enqueued by this transaction (and any nested accept that shared marks).
		var removedChildren = _root.PendingChildCount - _pendingChildMark;
		if (removedChildren > 0)
		{
			for (var i = _pendingChildMark; i < _root.PendingChildCount; i++)
				_root.WorkItems[i] = default;
			_root.PendingChildCount = _pendingChildMark;
			_root.RemainingWork += removedChildren;
			_root.RemainingFanout += removedChildren;
		}
		_pendingChildReservations = 0;

		_completed = true;
		_accepted = false;
		ReleaseLock();
		BattleCombatTransactionManager.RecordRolledBack();
		failReason = firstFailure;
		return firstFailure == null;
	}

	private void ReleaseLock()
	{
		if (!_lockHeld)
			return;
		_lockHeld = false;
		Monitor.Exit(_syncRoot);
	}
}

internal static class BattleCombatTransactionManager
{
	[ThreadStatic] private static Homm3DirectStateRootBudget _currentRoot;
	private static long _nextCorrelationId;
	private static long _begun;
	private static long _committed;
	private static long _rolledBack;
	private static int _maxDepth;
	private static int _journalHighWater;
	private static int _fanoutHighWater;
	private static int _rootWorkHighWater;

	internal static bool TryBegin(
		object scope,
		Homm3DirectStateAdapterId adapterId,
		Homm3DirectStateOperation operation,
		int reserveJournal,
		int reserveRootWork,
		out Homm3DirectStateTransaction transaction,
		out string failReason)
	{
		transaction = null;
		if (scope == null)
		{
			failReason = "direct-state transaction scope is null";
			return false;
		}
		if (!Homm3RuntimeMechanicRegistry.IsAdapterActive(adapterId))
		{
			failReason = "direct-state adapter is not active: " + adapterId;
			return false;
		}
		if (!Homm3DirectStateAdapterManifest.TryGet(adapterId, out var record))
		{
			failReason = "direct-state adapter has no manifest record: " + adapterId;
			return false;
		}
		if (!Contains(record.Operations, operation))
		{
			failReason = "operation " + operation + " does not belong to adapter " + adapterId;
			return false;
		}
		if (reserveJournal <= 0 || reserveJournal > record.Caps.MaxJournalEntries)
		{
			failReason = "journal reservation is outside adapter cap";
			return false;
		}
		if (reserveRootWork <= 0 || reserveRootWork > record.Caps.MaxRootWork)
		{
			failReason = "root work reservation is outside adapter cap";
			return false;
		}

		var root = _currentRoot;
		if (root == null)
		{
			root = new Homm3DirectStateRootBudget(
				Interlocked.Increment(ref _nextCorrelationId),
				record.Caps);
			_currentRoot = root;
		}
		if (root.Depth >= root.MaxDepth
		    || root.RemainingJournal < reserveJournal
		    || root.RemainingWork < reserveRootWork)
		{
			failReason = "root correlation depth/journal/work budget exhausted";
			return false;
		}

		root.Depth++;
		root.RemainingJournal -= reserveJournal;
		root.RemainingWork -= reserveRootWork;
		RecordRootWorkHighWater(root.MaxRootWork - root.RemainingWork);
		RecordDepthHighWater(root.Depth);
		Interlocked.Increment(ref _begun);
		transaction = new Homm3DirectStateTransaction(
			Homm3BattleLocalLawState.RuntimeTransactionSyncRoot,
			root,
			adapterId,
			operation,
			scope,
			Homm3BattleLocalLawState.CurrentRuntimeMechanicGeneration,
			reserveJournal);
		failReason = null;
		return true;
	}

	internal static bool TryDequeueChild(out Homm3DirectStateWorkItem workItem)
	{
		var root = _currentRoot;
		if (root == null || root.WorkReadIndex >= root.WorkCount)
		{
			workItem = default;
			return false;
		}
		workItem = root.WorkItems[root.WorkReadIndex++];
		return true;
	}

	/// <summary>
	/// Decrements root depth. On hard-accept at depth 0, promotes pending children into the
	/// drainable queue and discards the undo journal. On rejected completion at depth 0,
	/// drops pending children so deferred work cannot outlive a failed correlation.
	/// </summary>
	internal static void CompleteCurrentLevel(bool accepted = true)
	{
		var root = _currentRoot;
		if (root == null)
			return;
		if (root.Depth > 0)
			root.Depth--;
		if (root.Depth != 0)
			return;

		if (accepted)
		{
			// Hard-accept: journal is no longer reversible; promote pending children for drain.
			for (var i = 0; i < root.JournalCount; i++)
				root.Journal[i] = default;
			root.JournalCount = 0;
			root.WorkCount = root.PendingChildCount;
		}
		else
		{
			for (var i = 0; i < root.JournalCount; i++)
				root.Journal[i] = default;
			root.JournalCount = 0;
			for (var i = 0; i < root.PendingChildCount; i++)
				root.WorkItems[i] = default;
			root.PendingChildCount = 0;
			root.WorkCount = 0;
			root.WorkReadIndex = 0;
		}

		if (root.WorkReadIndex < root.WorkCount)
			return;
		Array.Clear(root.WorkItems, 0, root.WorkItems.Length);
		root.PendingChildCount = 0;
		root.WorkCount = 0;
		root.WorkReadIndex = 0;
		_currentRoot = null;
	}

	internal static void AbortRoot(string reason)
	{
		var root = _currentRoot;
		if (root == null)
			return;
		for (var i = 0; i < root.JournalCount; i++)
			root.Journal[i] = default;
		root.JournalCount = 0;
		Array.Clear(root.WorkItems, 0, root.WorkItems.Length);
		root.PendingChildCount = 0;
		root.WorkCount = 0;
		root.WorkReadIndex = 0;
		_currentRoot = null;
		Plugin.LogSource?.LogWarning("HoMM3 direct-state root correlation aborted: " + (reason ?? "unspecified") + ".");
	}

	/// <summary>
	/// Restores every journaled mutation on the current root, drops pending children,
	/// then aborts the correlation. Used when a compound cast/event must not partially apply.
	/// </summary>
	internal static void RollbackAndAbortRoot(string reason)
	{
		var root = _currentRoot;
		if (root == null)
			return;
		for (var i = root.JournalCount - 1; i >= 0; i--)
		{
			if (!NativeCombatWriteGateway.TryRestore(root.Journal[i], out var restoreFailure))
				Plugin.LogSource?.LogWarning(
					"HoMM3 direct-state compound rollback restore failed: " + restoreFailure);
			root.Journal[i] = default;
		}
		root.JournalCount = 0;
		var pending = root.PendingChildCount;
		if (pending > 0)
		{
			root.RemainingWork += pending;
			root.RemainingFanout += pending;
		}
		Array.Clear(root.WorkItems, 0, root.WorkItems.Length);
		root.PendingChildCount = 0;
		root.WorkCount = 0;
		root.WorkReadIndex = 0;
		_currentRoot = null;
		Interlocked.Increment(ref _rolledBack);
		Plugin.LogSource?.LogWarning(
			"HoMM3 direct-state root correlation rolled back and aborted: " + (reason ?? "unspecified") + ".");
	}

	internal static string SnapshotCountersJson()
	{
		return "{\"begun\":" + Interlocked.Read(ref _begun)
		       + ",\"committed\":" + Interlocked.Read(ref _committed)
		       + ",\"rolledBack\":" + Interlocked.Read(ref _rolledBack)
		       + ",\"maxDepth\":" + Volatile.Read(ref _maxDepth)
		       + ",\"journalHighWater\":" + Volatile.Read(ref _journalHighWater)
		       + ",\"fanoutHighWater\":" + Volatile.Read(ref _fanoutHighWater)
		       + ",\"rootWorkHighWater\":" + Volatile.Read(ref _rootWorkHighWater)
		       + "}";
	}

	internal static void ResetForBattleCleanup()
	{
		_currentRoot = null;
	}

	internal static void RecordCommitted(int journalCount)
	{
		Interlocked.Increment(ref _committed);
		RecordJournalHighWater(journalCount);
	}

	internal static void RecordRolledBack()
	{
		Interlocked.Increment(ref _rolledBack);
	}

	internal static void RecordDepthHighWater(int value)
	{
		UpdateHighWater(ref _maxDepth, value);
	}

	internal static void RecordJournalHighWater(int value)
	{
		UpdateHighWater(ref _journalHighWater, value);
	}

	internal static void RecordFanoutHighWater(int value)
	{
		UpdateHighWater(ref _fanoutHighWater, value);
	}

	internal static void RecordRootWorkHighWater(int value)
	{
		UpdateHighWater(ref _rootWorkHighWater, value);
	}

	private static bool Contains(Homm3DirectStateOperation[] operations, Homm3DirectStateOperation operation)
	{
		for (var i = 0; i < operations.Length; i++)
		{
			if (operations[i] == operation)
				return true;
		}
		return false;
	}

	private static void UpdateHighWater(ref int location, int value)
	{
		var current = Volatile.Read(ref location);
		while (value > current)
		{
			var observed = Interlocked.CompareExchange(ref location, value, current);
			if (observed == current)
				return;
			current = observed;
		}
	}
}
