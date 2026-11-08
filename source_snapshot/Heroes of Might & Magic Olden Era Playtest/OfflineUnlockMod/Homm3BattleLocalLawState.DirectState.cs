using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

internal readonly struct Homm3DirectStatusState
{
	internal Homm3DirectStatusState(
		string sid,
		int level,
		int duration,
		int value,
		int appliedRound,
		object source)
	{
		Sid = sid;
		Level = level;
		Duration = duration;
		Value = value;
		AppliedRound = appliedRound;
		Source = source;
	}

	internal string Sid { get; }
	internal int Level { get; }
	internal int Duration { get; }
	internal int Value { get; }
	internal int AppliedRound { get; }
	internal object Source { get; }
}

internal readonly struct Homm3DirectStatusTarget
{
	internal Homm3DirectStatusTarget(object unit, string sid)
	{
		Unit = unit;
		Sid = sid;
	}

	internal object Unit { get; }
	internal string Sid { get; }
}

internal readonly struct Homm3DirectAuraTarget
{
	internal Homm3DirectAuraTarget(long auraId, object source, object ownerSide, int radius, string effectSid)
	{
		AuraId = auraId;
		Source = source;
		OwnerSide = ownerSide;
		Radius = radius;
		EffectSid = effectSid;
	}

	internal long AuraId { get; }
	internal object Source { get; }
	internal object OwnerSide { get; }
	internal int Radius { get; }
	internal string EffectSid { get; }
}

internal readonly struct Homm3DirectCorpseState
{
	internal Homm3DirectCorpseState(long corpseId, long unitKey, int hexKey, string unitSid, long ownerSideKey, int deathSequence)
	{
		CorpseId = corpseId;
		UnitKey = unitKey;
		HexKey = hexKey;
		UnitSid = unitSid;
		OwnerSideKey = ownerSideKey;
		DeathSequence = deathSequence;
	}

	internal long CorpseId { get; }
	internal long UnitKey { get; }
	internal int HexKey { get; }
	internal string UnitSid { get; }
	internal long OwnerSideKey { get; }
	internal int DeathSequence { get; }
}

internal readonly struct Homm3DirectTrapState
{
	internal Homm3DirectTrapState(long trapId, long ownerSideKey, int hexKey, string trapSid, bool armed, bool triggered)
	{
		TrapId = trapId;
		OwnerSideKey = ownerSideKey;
		HexKey = hexKey;
		TrapSid = trapSid;
		Armed = armed;
		Triggered = triggered;
	}

	internal long TrapId { get; }
	internal long OwnerSideKey { get; }
	internal int HexKey { get; }
	internal string TrapSid { get; }
	internal bool Armed { get; }
	internal bool Triggered { get; }
}

internal readonly struct Homm3DirectKillState
{
	internal Homm3DirectKillState(long killId, long killerKey, long receiverKey, long receiverSideKey, int round, bool timeout)
	{
		KillId = killId;
		KillerKey = killerKey;
		ReceiverKey = receiverKey;
		ReceiverSideKey = receiverSideKey;
		Round = round;
		Timeout = timeout;
	}

	internal long KillId { get; }
	internal long KillerKey { get; }
	internal long ReceiverKey { get; }
	internal long ReceiverSideKey { get; }
	internal int Round { get; }
	internal bool Timeout { get; }
}

internal static partial class Homm3BattleLocalLawState
{
	private sealed class DirectStatusSnapshot
	{
		internal long UnitKey;
		internal string Sid;
		internal bool HadValue;
		internal Homm3DirectStatusState OldValue;
		internal bool HadUnitReference;
		internal object OldUnitReference;
		internal bool WasDirty;
	}

	private sealed class DirectCorpseSnapshot
	{
		internal long CorpseId;
		internal long OldNextId;
		internal bool RestoreNextId;
		internal bool HadValue;
		internal Homm3DirectCorpseState OldValue;
	}

	private sealed class DirectTrapSnapshot
	{
		internal long TrapId;
		internal long OldNextId;
		internal bool RestoreNextId;
		internal bool HadValue;
		internal Homm3DirectTrapState OldValue;
		internal int DirtyHexKey;
		internal bool WasDirty;
	}

	private sealed class DirectKillSnapshot
	{
		internal long KillId;
		internal long OldNextId;
		internal bool RestoreNextId;
		internal bool HadValue;
		internal Homm3DirectKillState OldValue;
	}

	private sealed class DirectIntSnapshot
	{
		internal Dictionary<long, int> Owner;
		internal long Key;
		internal bool HadValue;
		internal int OldValue;
		internal bool RestoreDirtyUnit;
		internal bool WasDirty;
	}

	private sealed class DirectLongSetSnapshot
	{
		internal HashSet<long> Owner;
		internal long Key;
		internal bool WasPresent;
	}

	private sealed class DirectObjectSnapshot
	{
		internal Dictionary<long, object> Owner;
		internal long Key;
		internal bool HadValue;
		internal object OldValue;
	}

	private sealed class DirectAuraSnapshot
	{
		internal long AuraId;
		internal long OldNextId;
		internal bool RestoreNextId;
		internal bool HadValue;
		internal DirectAuraState OldValue;
	}

	private sealed class DirectAuraState
	{
		internal long SourceKey;
		internal long OwnerSideKey;
		internal object SourceReference;
		internal object OwnerSideReference;
		internal int Radius;
		internal string EffectSid;
		internal readonly HashSet<long> Members = new();

		internal DirectAuraState Clone()
		{
			var clone = new DirectAuraState
			{
				SourceKey = SourceKey,
				OwnerSideKey = OwnerSideKey,
				SourceReference = SourceReference,
				OwnerSideReference = OwnerSideReference,
				Radius = Radius,
				EffectSid = EffectSid,
			};
			foreach (var member in Members)
				clone.Members.Add(member);
			return clone;
		}
	}

	private sealed class DirectStateLedger : IHomm3DirectStateLedger
	{
		internal readonly Dictionary<long, Dictionary<string, Homm3DirectStatusState>> Statuses = new();
		internal readonly Dictionary<long, object> StatusUnitReferences = new();
		internal readonly Dictionary<long, int> ImmobileCounts = new();
		internal readonly Dictionary<long, int> CastCounts = new();
		internal readonly Dictionary<long, int> FocusShadow = new();
		internal readonly Dictionary<long, int> CooldownShadow = new();
		internal readonly Dictionary<long, object> DamageRedirects = new();
		internal readonly Dictionary<long, Homm3DirectCorpseState> Corpses = new();
		internal readonly Dictionary<long, Homm3DirectTrapState> Traps = new();
		internal readonly Dictionary<long, Homm3DirectKillState> Kills = new();
		internal readonly Dictionary<long, DirectAuraState> Auras = new();
		internal readonly HashSet<long> ClaimedEventTokens = new();
		internal readonly HashSet<long> CompletedEventTokens = new();
		internal readonly HashSet<long> FailedEventTokens = new();
		internal readonly HashSet<long> DirtyUnits = new();
		internal readonly HashSet<int> DirtyHexes = new();
		internal int CurrentRound;
		internal long NextCorpseId;
		internal long NextTrapId;
		internal long NextKillId;
		internal long NextAuraId;

		public bool TryRestore(Homm3DirectStateJournalEntry entry, out string failReason)
		{
			switch (entry.Opcode)
			{
				case Homm3DirectStateJournalOpcode.StatusLedger:
					return RestoreStatus(entry.OldValue as DirectStatusSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.Corpse:
					return RestoreCorpse(entry.OldValue as DirectCorpseSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.Trap:
					return RestoreTrap(entry.OldValue as DirectTrapSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.ManagerObject:
					if (entry.OldValue is DirectKillSnapshot killSnapshot)
						return RestoreKill(killSnapshot, out failReason);
					return RestoreObject(entry.OldValue as DirectObjectSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.ManagerInt:
					return RestoreInt(entry.OldValue as DirectIntSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.EventToken:
					return RestoreLongSet(entry.OldValue as DirectLongSetSnapshot, out failReason);
				case Homm3DirectStateJournalOpcode.Aura:
					return RestoreAura(entry.OldValue as DirectAuraSnapshot, out failReason);
				default:
					failReason = "direct-state ledger cannot restore opcode " + entry.Opcode;
					return false;
			}
		}

		private bool RestoreStatus(DirectStatusSnapshot snapshot, out string failReason)
		{
			if (snapshot == null)
			{
				failReason = "status rollback snapshot is missing";
				return false;
			}
			if (!Statuses.TryGetValue(snapshot.UnitKey, out var bySid))
			{
				bySid = new Dictionary<string, Homm3DirectStatusState>(StringComparer.Ordinal);
				Statuses[snapshot.UnitKey] = bySid;
			}
			if (snapshot.HadValue)
				bySid[snapshot.Sid] = snapshot.OldValue;
			else
				bySid.Remove(snapshot.Sid);
			if (bySid.Count == 0)
				Statuses.Remove(snapshot.UnitKey);
			if (snapshot.HadUnitReference)
				StatusUnitReferences[snapshot.UnitKey] = snapshot.OldUnitReference;
			else
				StatusUnitReferences.Remove(snapshot.UnitKey);
			if (!snapshot.WasDirty)
				DirtyUnits.Remove(snapshot.UnitKey);
			failReason = null;
			return true;
		}

		private bool RestoreCorpse(DirectCorpseSnapshot snapshot, out string failReason)
		{
			if (snapshot == null)
			{
				failReason = "corpse rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				Corpses[snapshot.CorpseId] = snapshot.OldValue;
			else
				Corpses.Remove(snapshot.CorpseId);
			if (snapshot.RestoreNextId)
				NextCorpseId = snapshot.OldNextId;
			failReason = null;
			return true;
		}

		private bool RestoreTrap(DirectTrapSnapshot snapshot, out string failReason)
		{
			if (snapshot == null)
			{
				failReason = "trap rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				Traps[snapshot.TrapId] = snapshot.OldValue;
			else
				Traps.Remove(snapshot.TrapId);
			if (snapshot.RestoreNextId)
				NextTrapId = snapshot.OldNextId;
			if (!snapshot.WasDirty)
				DirtyHexes.Remove(snapshot.DirtyHexKey);
			failReason = null;
			return true;
		}

		private bool RestoreKill(DirectKillSnapshot snapshot, out string failReason)
		{
			if (snapshot == null)
			{
				failReason = "kill rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				Kills[snapshot.KillId] = snapshot.OldValue;
			else
				Kills.Remove(snapshot.KillId);
			if (snapshot.RestoreNextId)
				NextKillId = snapshot.OldNextId;
			failReason = null;
			return true;
		}

		private bool RestoreInt(DirectIntSnapshot snapshot, out string failReason)
		{
			if (snapshot?.Owner == null)
			{
				failReason = "integer rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				snapshot.Owner[snapshot.Key] = snapshot.OldValue;
			else
				snapshot.Owner.Remove(snapshot.Key);
			if (snapshot.RestoreDirtyUnit && !snapshot.WasDirty)
				DirtyUnits.Remove(snapshot.Key);
			failReason = null;
			return true;
		}

		private static bool RestoreLongSet(DirectLongSetSnapshot snapshot, out string failReason)
		{
			if (snapshot?.Owner == null)
			{
				failReason = "event-token rollback snapshot is missing";
				return false;
			}
			if (snapshot.WasPresent)
				snapshot.Owner.Add(snapshot.Key);
			else
				snapshot.Owner.Remove(snapshot.Key);
			failReason = null;
			return true;
		}

		private static bool RestoreObject(DirectObjectSnapshot snapshot, out string failReason)
		{
			if (snapshot?.Owner == null)
			{
				failReason = "object rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				snapshot.Owner[snapshot.Key] = snapshot.OldValue;
			else
				snapshot.Owner.Remove(snapshot.Key);
			failReason = null;
			return true;
		}

		private bool RestoreAura(DirectAuraSnapshot snapshot, out string failReason)
		{
			if (snapshot == null)
			{
				failReason = "aura rollback snapshot is missing";
				return false;
			}
			if (snapshot.HadValue)
				Auras[snapshot.AuraId] = snapshot.OldValue;
			else
				Auras.Remove(snapshot.AuraId);
			if (snapshot.RestoreNextId)
				NextAuraId = snapshot.OldNextId;
			failReason = null;
			return true;
		}
	}

	private static DirectStateLedger DirectState = new();

	internal static bool TryRecordDirectCast(
		Homm3DirectStateTransaction transaction,
		object caster,
		out int castCount,
		out string failReason)
	{
		castCount = 0;
		if (transaction == null || caster == null)
		{
			failReason = "cast state requires transaction and caster";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(caster, out var key, out failReason))
			return false;
		DirectState.CastCounts.TryGetValue(key, out var oldValue);
		var snapshot = new DirectIntSnapshot
		{
			Owner = DirectState.CastCounts,
			Key = key,
			HadValue = DirectState.CastCounts.ContainsKey(key),
			OldValue = oldValue,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.ManagerInt, null, 0, oldValue, snapshot, out failReason))
			return false;
		castCount = checked(oldValue + 1);
		DirectState.CastCounts[key] = castCount;
		return true;
	}

	internal static bool TryRecordDirectResource(
		Homm3DirectStateTransaction transaction,
		object owner,
		bool cooldown,
		int value,
		out string failReason)
	{
		if (transaction == null || owner == null)
		{
			failReason = "resource state requires transaction and owner";
			return false;
		}
		var target = cooldown ? DirectState.CooldownShadow : DirectState.FocusShadow;
		if (!Homm3DirectStateIdentity.TryResolveKey(owner, out var key, out failReason))
			return false;
		target.TryGetValue(key, out var oldValue);
		var snapshot = new DirectIntSnapshot
		{
			Owner = target,
			Key = key,
			HadValue = target.ContainsKey(key),
			OldValue = oldValue,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.ManagerInt, null, 0, oldValue, snapshot, out failReason))
			return false;
		target[key] = value;
		failReason = null;
		return true;
	}

	internal static bool TryApplyDirectStatus(
		Homm3DirectStateTransaction transaction,
		object receiver,
		Homm3DirectStatusState status,
		bool refresh,
		out string failReason)
	{
		if (transaction == null || receiver == null || string.IsNullOrWhiteSpace(status.Sid))
		{
			failReason = "status state requires transaction, receiver, and SID";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(receiver, out var key, out failReason))
			return false;
		if (!DirectState.Statuses.TryGetValue(key, out var bySid))
		{
			bySid = new Dictionary<string, Homm3DirectStatusState>(StringComparer.Ordinal);
			DirectState.Statuses[key] = bySid;
		}
		var hadValue = bySid.TryGetValue(status.Sid, out var oldValue);
		if (hadValue && !refresh)
		{
			failReason = "status already exists and refresh is disabled";
			return false;
		}
		var snapshot = new DirectStatusSnapshot
		{
			UnitKey = key,
			Sid = status.Sid,
			HadValue = hadValue,
			OldValue = oldValue,
			HadUnitReference = DirectState.StatusUnitReferences.TryGetValue(key, out var oldUnitReference),
			OldUnitReference = oldUnitReference,
			WasDirty = DirectState.DirtyUnits.Contains(key),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.StatusLedger, null, 0, 0, snapshot, out failReason))
			return false;
		bySid[status.Sid] = status;
		DirectState.StatusUnitReferences[key] = receiver;
		if (!TryMarkDirty(DirectState.DirtyUnits, key, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TryRemoveDirectStatus(
		Homm3DirectStateTransaction transaction,
		object receiver,
		string sid,
		out string failReason)
	{
		if (transaction == null || receiver == null || string.IsNullOrWhiteSpace(sid))
		{
			failReason = "status removal requires transaction, receiver, and SID";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(receiver, out var key, out failReason))
			return false;
		if (!DirectState.Statuses.TryGetValue(key, out var bySid) || !bySid.TryGetValue(sid, out var oldValue))
		{
			failReason = "status is not present";
			return false;
		}
		var snapshot = new DirectStatusSnapshot
		{
			UnitKey = key,
			Sid = sid,
			HadValue = true,
			OldValue = oldValue,
			HadUnitReference = DirectState.StatusUnitReferences.TryGetValue(key, out var oldUnitReference),
			OldUnitReference = oldUnitReference,
			WasDirty = DirectState.DirtyUnits.Contains(key),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.StatusLedger, null, 0, 0, snapshot, out failReason))
			return false;
		bySid.Remove(sid);
		if (bySid.Count == 0)
		{
			DirectState.Statuses.Remove(key);
			DirectState.StatusUnitReferences.Remove(key);
		}
		if (!TryMarkDirty(DirectState.DirtyUnits, key, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TryTransitionDirectStatus(
		Homm3DirectStateTransaction transaction,
		object receiver,
		string sid,
		Homm3DirectStateOperation operation,
		out int remainingDuration,
		out string failReason)
	{
		remainingDuration = 0;
		if (transaction == null || receiver == null || string.IsNullOrWhiteSpace(sid))
		{
			failReason = "status transition requires transaction, receiver, and SID";
			return false;
		}
		if (operation != Homm3DirectStateOperation.StatusTick
		    && operation != Homm3DirectStateOperation.StatusExpire)
		{
			failReason = "status transition operation is not tick or expire";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(receiver, out var key, out failReason))
			return false;
		if (!DirectState.Statuses.TryGetValue(key, out var bySid) || !bySid.TryGetValue(sid, out var oldValue))
		{
			failReason = "status is not present";
			return false;
		}
		var snapshot = new DirectStatusSnapshot
		{
			UnitKey = key,
			Sid = sid,
			HadValue = true,
			OldValue = oldValue,
			HadUnitReference = DirectState.StatusUnitReferences.TryGetValue(key, out var oldUnitReference),
			OldUnitReference = oldUnitReference,
			WasDirty = DirectState.DirtyUnits.Contains(key),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.StatusLedger, null, 0, 0, snapshot, out failReason))
			return false;
		remainingDuration = operation == Homm3DirectStateOperation.StatusExpire
			? 0
			: Math.Max(0, oldValue.Duration - 1);
		if (remainingDuration == 0)
		{
			bySid.Remove(sid);
			if (bySid.Count == 0)
			{
				DirectState.Statuses.Remove(key);
				DirectState.StatusUnitReferences.Remove(key);
			}
		}
		else
		{
			bySid[sid] = new Homm3DirectStatusState(
				oldValue.Sid,
				oldValue.Level,
				remainingDuration,
				oldValue.Value,
				oldValue.AppliedRound,
				oldValue.Source);
		}
		if (!TryMarkDirty(DirectState.DirtyUnits, key, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TrySetDirectImmobile(
		Homm3DirectStateTransaction transaction,
		object unit,
		bool immobile,
		out string failReason)
	{
		if (transaction == null || unit == null)
		{
			failReason = "immobility state requires transaction and unit";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var key, out failReason))
			return false;
		DirectState.ImmobileCounts.TryGetValue(key, out var oldValue);
		var snapshot = new DirectIntSnapshot
		{
			Owner = DirectState.ImmobileCounts,
			Key = key,
			HadValue = DirectState.ImmobileCounts.ContainsKey(key),
			OldValue = oldValue,
			RestoreDirtyUnit = true,
			WasDirty = DirectState.DirtyUnits.Contains(key),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.ManagerInt, null, 0, oldValue, snapshot, out failReason))
			return false;
		if (immobile)
			DirectState.ImmobileCounts[key] = Math.Max(1, oldValue + 1);
		else
			DirectState.ImmobileCounts.Remove(key);
		if (!TryMarkDirty(DirectState.DirtyUnits, key, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool IsDirectlyImmobile(object unit)
	{
		if (unit == null || !Homm3DirectStateIdentity.TryResolveKey(unit, out var key, out _))
			return false;
		lock (LockObject)
			return DirectState.ImmobileCounts.TryGetValue(key, out var count) && count > 0;
	}

	internal static bool TryCreateDirectCorpse(
		Homm3DirectStateTransaction transaction,
		object unit,
		int hexKey,
		string unitSid,
		long ownerSideKey,
		out Homm3DirectCorpseState corpse,
		out string failReason)
	{
		corpse = default;
		if (transaction == null || unit == null || hexKey < 0 || string.IsNullOrWhiteSpace(unitSid))
		{
			failReason = "corpse creation requires transaction, unit, hex, and unit SID";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var unitKey, out failReason))
			return false;
		var oldNextId = DirectState.NextCorpseId;
		var id = ++DirectState.NextCorpseId;
		var snapshot = new DirectCorpseSnapshot
		{
			CorpseId = id,
			HadValue = false,
			OldNextId = oldNextId,
			RestoreNextId = true,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Corpse, null, 0, 0, snapshot, out failReason))
			return false;
		corpse = new Homm3DirectCorpseState(
			id,
			unitKey,
			hexKey,
			unitSid,
			ownerSideKey,
			(int)Math.Min(int.MaxValue, id));
		DirectState.Corpses[id] = corpse;
		failReason = null;
		return true;
	}

	internal static bool TryConsumeDirectCorpse(
		Homm3DirectStateTransaction transaction,
		long corpseId,
		out Homm3DirectCorpseState corpse,
		out string failReason)
	{
		corpse = default;
		if (transaction == null || !DirectState.Corpses.TryGetValue(corpseId, out corpse))
		{
			failReason = "corpse is not present";
			return false;
		}
		var snapshot = new DirectCorpseSnapshot { CorpseId = corpseId, HadValue = true, OldValue = corpse };
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Corpse, null, 0, 0, snapshot, out failReason))
			return false;
		DirectState.Corpses.Remove(corpseId);
		failReason = null;
		return true;
	}

	internal static bool TryCreateDirectTrap(
		Homm3DirectStateTransaction transaction,
		long ownerSideKey,
		int hexKey,
		string trapSid,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (transaction == null || hexKey < 0 || string.IsNullOrWhiteSpace(trapSid))
		{
			failReason = "trap creation requires transaction, hex, and SID";
			return false;
		}
		var oldNextId = DirectState.NextTrapId;
		var id = ++DirectState.NextTrapId;
		var snapshot = new DirectTrapSnapshot
		{
			TrapId = id,
			HadValue = false,
			OldNextId = oldNextId,
			RestoreNextId = true,
			DirtyHexKey = hexKey,
			WasDirty = DirectState.DirtyHexes.Contains(hexKey),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Trap, null, 0, 0, snapshot, out failReason))
			return false;
		trap = new Homm3DirectTrapState(id, ownerSideKey, hexKey, trapSid, armed: true, triggered: false);
		DirectState.Traps[id] = trap;
		if (!TryMarkDirty(DirectState.DirtyHexes, hexKey, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TryTriggerDirectTrap(
		Homm3DirectStateTransaction transaction,
		long trapId,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (transaction == null || !DirectState.Traps.TryGetValue(trapId, out var oldValue) || !oldValue.Armed)
		{
			failReason = "armed trap is not present";
			return false;
		}
		var snapshot = new DirectTrapSnapshot
		{
			TrapId = trapId,
			HadValue = true,
			OldValue = oldValue,
			DirtyHexKey = oldValue.HexKey,
			WasDirty = DirectState.DirtyHexes.Contains(oldValue.HexKey),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Trap, null, 0, 0, snapshot, out failReason))
			return false;
		trap = new Homm3DirectTrapState(oldValue.TrapId, oldValue.OwnerSideKey, oldValue.HexKey, oldValue.TrapSid, armed: false, triggered: true);
		DirectState.Traps[trapId] = trap;
		if (!TryMarkDirty(DirectState.DirtyHexes, trap.HexKey, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TryRemoveDirectTrap(
		Homm3DirectStateTransaction transaction,
		long trapId,
		out Homm3DirectTrapState trap,
		out string failReason)
	{
		trap = default;
		if (transaction == null || !DirectState.Traps.TryGetValue(trapId, out trap))
		{
			failReason = "trap is not present";
			return false;
		}
		var snapshot = new DirectTrapSnapshot
		{
			TrapId = trapId,
			HadValue = true,
			OldValue = trap,
			DirtyHexKey = trap.HexKey,
			WasDirty = DirectState.DirtyHexes.Contains(trap.HexKey),
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Trap, null, 0, 0, snapshot, out failReason))
			return false;
		DirectState.Traps.Remove(trapId);
		if (!TryMarkDirty(DirectState.DirtyHexes, trap.HexKey, out failReason))
			return false;
		failReason = null;
		return true;
	}

	internal static bool TryConfirmDirectKill(
		Homm3DirectStateTransaction transaction,
		object killer,
		object receiver,
		object receiverSide,
		int round,
		bool timeout,
		out Homm3DirectKillState kill,
		out string failReason)
	{
		kill = default;
		if (transaction == null || receiver == null)
		{
			failReason = "kill confirmation requires transaction and receiver";
			return false;
		}
		var oldNextId = DirectState.NextKillId;
		var id = ++DirectState.NextKillId;
		var snapshot = new DirectKillSnapshot
		{
			KillId = id,
			HadValue = false,
			OldNextId = oldNextId,
			RestoreNextId = true,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.ManagerObject, null, 0, 0, snapshot, out failReason))
			return false;
		if (!Homm3DirectStateIdentity.TryResolveKey(receiver, out var receiverKey, out failReason))
			return false;
		kill = new Homm3DirectKillState(
			id,
			Homm3DirectStateIdentity.ResolveKeyOrZero(killer),
			receiverKey,
			Homm3DirectStateIdentity.ResolveKeyOrZero(receiverSide),
			round,
			timeout);
		DirectState.Kills[id] = kill;
		failReason = null;
		return true;
	}

	internal static bool TrySetDirectDamageRedirect(
		Homm3DirectStateTransaction transaction,
		object receiver,
		object redirectTarget,
		out string failReason)
	{
		if (transaction == null || receiver == null)
		{
			failReason = "damage redirection requires transaction and receiver";
			return false;
		}
		if (Homm3NativeIdentity.Same(receiver, redirectTarget))
		{
			failReason = "damage redirection target cannot be the receiver";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(receiver, out var key, out failReason))
			return false;
		var hadValue = DirectState.DamageRedirects.TryGetValue(key, out var oldValue);
		var snapshot = new DirectObjectSnapshot
		{
			Owner = DirectState.DamageRedirects,
			Key = key,
			HadValue = hadValue,
			OldValue = oldValue,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.ManagerObject, null, 0, 0, snapshot, out failReason))
			return false;
		if (redirectTarget == null)
			DirectState.DamageRedirects.Remove(key);
		else
			DirectState.DamageRedirects[key] = redirectTarget;
		failReason = null;
		return true;
	}

	internal static bool TryGetDirectDamageRedirect(object receiver, out object redirectTarget)
	{
		redirectTarget = null;
		if (receiver == null || !Homm3DirectStateIdentity.TryResolveKey(receiver, out var key, out _))
			return false;
		lock (LockObject)
			return DirectState.DamageRedirects.TryGetValue(key, out redirectTarget)
			       && redirectTarget != null
			       && !Homm3NativeIdentity.Same(receiver, redirectTarget);
	}

	internal static bool TryClaimDirectEventToken(
		Homm3DirectStateTransaction transaction,
		long token,
		out string failReason)
	{
		if (transaction == null || token == 0)
		{
			failReason = "event token requires transaction and non-zero token";
			return false;
		}
		var wasPresent = DirectState.ClaimedEventTokens.Contains(token);
		if (wasPresent)
		{
			failReason = "event token was already claimed";
			return false;
		}
		var snapshot = new DirectLongSetSnapshot
		{
			Owner = DirectState.ClaimedEventTokens,
			Key = token,
			WasPresent = false,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.EventToken, null, 0, 0, snapshot, out failReason))
			return false;
		DirectState.ClaimedEventTokens.Add(token);
		failReason = null;
		return true;
	}

	internal static void CompleteDirectEventToken(long token, bool success)
	{
		lock (LockObject)
		{
			if (!DirectState.ClaimedEventTokens.Contains(token))
				return;
			if (success)
				DirectState.CompletedEventTokens.Add(token);
			else
				DirectState.FailedEventTokens.Add(token);
		}
	}

	internal static bool TryDefineDirectAura(
		Homm3DirectStateTransaction transaction,
		object source,
		object ownerSide,
		int radius,
		string effectSid,
		out long auraId,
		out string failReason)
	{
		auraId = 0;
		if (transaction == null || source == null || radius < 0 || string.IsNullOrWhiteSpace(effectSid))
		{
			failReason = "aura definition requires transaction, source, radius, and effect SID";
			return false;
		}
		if (!Homm3DirectStateIdentity.TryResolveKey(source, out var sourceKey, out failReason))
			return false;
		var oldNextId = DirectState.NextAuraId;
		auraId = ++DirectState.NextAuraId;
		var snapshot = new DirectAuraSnapshot
		{
			AuraId = auraId,
			HadValue = false,
			OldNextId = oldNextId,
			RestoreNextId = true,
		};
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Aura, null, 0, 0, snapshot, out failReason))
			return false;
		DirectState.Auras[auraId] = new DirectAuraState
		{
			SourceKey = sourceKey,
			OwnerSideKey = Homm3DirectStateIdentity.ResolveKeyOrZero(ownerSide),
			SourceReference = source,
			OwnerSideReference = ownerSide,
			Radius = radius,
			EffectSid = effectSid,
		};
		failReason = null;
		return true;
	}

	internal static bool TryReplaceDirectAuraMembers(
		Homm3DirectStateTransaction transaction,
		long auraId,
		IEnumerable<object> members,
		out int memberCount,
		out string failReason)
	{
		memberCount = 0;
		if (transaction == null || !DirectState.Auras.TryGetValue(auraId, out var aura))
		{
			failReason = "aura is not present";
			return false;
		}
		var snapshot = new DirectAuraSnapshot { AuraId = auraId, HadValue = true, OldValue = aura.Clone() };
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Aura, null, 0, 0, snapshot, out failReason))
			return false;
		aura.Members.Clear();
		if (members != null)
		{
			foreach (var member in members)
			{
				if (member == null)
					continue;
				if (!Homm3DirectStateIdentity.TryResolveKey(member, out var memberKey, out failReason))
					return false;
				if (aura.Members.Contains(memberKey))
					continue;
				if (aura.Members.Count >= 32)
				{
					failReason = "aura unique member cap exhausted";
					return false;
				}
				aura.Members.Add(memberKey);
			}
		}
		memberCount = aura.Members.Count;
		failReason = null;
		return true;
	}

	internal static bool TryRemoveDirectAura(
		Homm3DirectStateTransaction transaction,
		long auraId,
		out string failReason)
	{
		if (transaction == null || !DirectState.Auras.TryGetValue(auraId, out var aura))
		{
			failReason = "aura is not present";
			return false;
		}
		var snapshot = new DirectAuraSnapshot { AuraId = auraId, HadValue = true, OldValue = aura.Clone() };
		if (!transaction.TryRecordLedger(DirectState, Homm3DirectStateJournalOpcode.Aura, null, 0, 0, snapshot, out failReason))
			return false;
		DirectState.Auras.Remove(auraId);
		failReason = null;
		return true;
	}

	internal static void SetDirectRound(int round)
	{
		lock (LockObject)
			DirectState.CurrentRound = Math.Max(0, round);
	}

	internal static List<Homm3DirectStatusTarget> SnapshotDirectStatuses(int limit)
	{
		limit = Math.Max(1, Math.Min(32, limit));
		var result = new List<Homm3DirectStatusTarget>(limit);
		lock (LockObject)
		{
			foreach (var unitPair in DirectState.Statuses)
			{
				if (!DirectState.StatusUnitReferences.TryGetValue(unitPair.Key, out var unit)
				    || unit == null)
					continue;
				foreach (var statusPair in unitPair.Value)
				{
					result.Add(new Homm3DirectStatusTarget(unit, statusPair.Key));
					if (result.Count >= limit)
						return result;
				}
			}
		}
		return result;
	}

	internal static List<Homm3DirectAuraTarget> SnapshotDirectAuras(int limit)
	{
		limit = Math.Max(1, Math.Min(32, limit));
		var result = new List<Homm3DirectAuraTarget>(limit);
		lock (LockObject)
		{
			foreach (var pair in DirectState.Auras)
			{
				var aura = pair.Value;
				if (aura.SourceReference == null)
					continue;
				result.Add(new Homm3DirectAuraTarget(
					pair.Key,
					aura.SourceReference,
					aura.OwnerSideReference,
					aura.Radius,
					aura.EffectSid));
				if (result.Count >= limit)
					break;
			}
		}
		return result;
	}

	internal static List<long> SnapshotArmedDirectTrapsAtHex(int hexKey, int limit)
	{
		limit = Math.Max(1, Math.Min(16, limit));
		var result = new List<long>(limit);
		lock (LockObject)
		{
			foreach (var pair in DirectState.Traps)
			{
				if (!pair.Value.Armed || pair.Value.HexKey != hexKey)
					continue;
				result.Add(pair.Key);
				if (result.Count >= limit)
					break;
			}
		}
		return result;
	}

	internal static void ClearDirectDirtyIdentities()
	{
		lock (LockObject)
		{
			DirectState.DirtyUnits.Clear();
			DirectState.DirtyHexes.Clear();
		}
	}

	private static bool TryMarkDirty(HashSet<long> identities, long key, out string failReason)
	{
		if (identities.Contains(key))
		{
			failReason = null;
			return true;
		}
		if (identities.Count >= 32)
		{
			failReason = "unique dirty identity cap exhausted";
			return false;
		}
		identities.Add(key);
		failReason = null;
		return true;
	}

	private static bool TryMarkDirty(HashSet<int> identities, int key, out string failReason)
	{
		if (identities.Contains(key))
		{
			failReason = null;
			return true;
		}
		if (identities.Count >= 32)
		{
			failReason = "unique dirty identity cap exhausted";
			return false;
		}
		identities.Add(key);
		failReason = null;
		return true;
	}

	internal static string SnapshotDirectStateJson()
	{
		lock (LockObject)
		{
			return "{\"generation\":" + RuntimeMechanicGeneration
			       + ",\"round\":" + DirectState.CurrentRound
			       + ",\"statuses\":" + CountStatuses()
			       + ",\"immobile\":" + DirectState.ImmobileCounts.Count
			       + ",\"damageRedirects\":" + DirectState.DamageRedirects.Count
			       + ",\"corpses\":" + DirectState.Corpses.Count
			       + ",\"traps\":" + DirectState.Traps.Count
			       + ",\"kills\":" + DirectState.Kills.Count
			       + ",\"auras\":" + DirectState.Auras.Count
			       + ",\"claimedEvents\":" + DirectState.ClaimedEventTokens.Count
			       + ",\"completedEvents\":" + DirectState.CompletedEventTokens.Count
			       + ",\"failedEvents\":" + DirectState.FailedEventTokens.Count
			       + ",\"dirtyUnits\":" + DirectState.DirtyUnits.Count
			       + ",\"dirtyHexes\":" + DirectState.DirtyHexes.Count
			       + "}";
		}
	}

	private static int CountStatuses()
	{
		var count = 0;
		foreach (var bySid in DirectState.Statuses.Values)
			count += bySid.Count;
		return count;
	}

	private static void ClearDirectStateLedgersLocked()
	{
		DirectState = new DirectStateLedger();
	}
}
