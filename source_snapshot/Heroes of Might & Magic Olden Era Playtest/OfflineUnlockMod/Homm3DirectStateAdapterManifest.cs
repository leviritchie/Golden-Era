using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Stable, append-only identifiers for direct-state adapter families. Values
/// are persisted in the JSON contract and must never be renumbered or reused.
/// </summary>
internal enum Homm3DirectStateAdapterId
{
	None = 0,
	Damage = 1,
	Cast = 2,
	Focus = 3,
	Cooldown = 4,
	Status = 5,
	Movement = 6,
	Summon = 7,
	Trap = 8,
	Corpse = 9,
	NestedDamage = 10,
	Kill = 11,
	AllyDeath = 12,
	ActionQueue = 13,
	TurnOrder = 14,
	Aura = 15,
}

internal enum Homm3DirectStateOperation
{
	None = 0,
	DamageFlatDelta = 1,
	CastChain = 2,
	FocusGrant = 3,
	FocusSpend = 4,
	FocusSet = 5,
	CooldownSet = 6,
	CooldownReduce = 7,
	CooldownIncrease = 8,
	CooldownCharges = 9,
	CooldownCastCounter = 10,
	StatusApply = 11,
	StatusRefresh = 12,
	StatusTick = 13,
	StatusExpire = 14,
	StatusRemove = 15,
	MovementPush = 16,
	MovementPull = 17,
	MovementTeleport = 18,
	MovementSetImmobile = 19,
	SummonCreate = 20,
	TrapSpawn = 21,
	TrapTrigger = 22,
	TrapDespawn = 23,
	CorpseCreate = 24,
	CorpseConsume = 25,
	NestedReflection = 26,
	NestedRedirection = 27,
	NestedSplash = 28,
	KillConfirm = 29,
	AllyDeathObserve = 30,
	ActionQueueInsert = 31,
	ActionQueueRemove = 32,
	TurnOrderReorder = 33,
	AuraDefine = 34,
	AuraRefresh = 35,
	AuraRemove = 36,
}

[Flags]
internal enum Homm3DirectStateHookSurface
{
	None = 0,
	UnitInit = 1 << 0,
	DamageApplying = 1 << 1,
	DamageApplied = 1 << 2,
	CastCommitted = 1 << 3,
	MovementCommitted = 1 << 4,
	ObjectSpawned = 1 << 5,
	ObjectDestroyed = 1 << 6,
	RoundStart = 1 << 7,
	RoundEnd = 1 << 8,
	ActionStart = 1 << 9,
	ActionEnd = 1 << 10,
	BattleResult = 1 << 11,
}

internal enum Homm3DirectStateJournalOpcode
{
	None = 0,
	DamageScalar = 1,
	ManagerInt = 2,
	ManagerObject = 3,
	NativeIntMember = 4,
	NativeObjectMember = 5,
	NativeListSnapshot = 6,
	StatusLedger = 7,
	Occupancy = 8,
	Spawn = 9,
	Trap = 10,
	Corpse = 11,
	ActionQueue = 12,
	TurnOrder = 13,
	Aura = 14,
	EventToken = 15,
	PresentationToken = 16,
}

internal readonly struct Homm3DirectStateAdapterCaps
{
	internal Homm3DirectStateAdapterCaps(
		int maxRootWork,
		int maxDepth,
		int maxJournalEntries,
		int maxFanout,
		int maxDirtyIdentities,
		int maxQueueSpan)
	{
		MaxRootWork = maxRootWork;
		MaxDepth = maxDepth;
		MaxJournalEntries = maxJournalEntries;
		MaxFanout = maxFanout;
		MaxDirtyIdentities = maxDirtyIdentities;
		MaxQueueSpan = maxQueueSpan;
	}

	internal int MaxRootWork { get; }
	internal int MaxDepth { get; }
	internal int MaxJournalEntries { get; }
	internal int MaxFanout { get; }
	internal int MaxDirtyIdentities { get; }
	internal int MaxQueueSpan { get; }
}

internal sealed class Homm3DirectStateAdapterRecord
{
	internal Homm3DirectStateAdapterRecord(
		Homm3DirectStateAdapterId adapterId,
		string contractId,
		string familyKey,
		Homm3DirectStateHookSurface hookSurfaces,
		Homm3DirectStateAdapterCaps caps,
		Homm3DirectStateOperation[] operations,
		Homm3DirectStateJournalOpcode[] journalOpcodes,
		string fixtureFlag,
		string proofLabel,
		string reconciliationPolicy)
	{
		AdapterId = adapterId;
		ContractId = contractId;
		FamilyKey = familyKey;
		HookSurfaces = hookSurfaces;
		Caps = caps;
		Operations = operations ?? Array.Empty<Homm3DirectStateOperation>();
		JournalOpcodes = journalOpcodes ?? Array.Empty<Homm3DirectStateJournalOpcode>();
		FixtureFlag = fixtureFlag;
		ProofLabel = proofLabel;
		ReconciliationPolicy = reconciliationPolicy;
	}

	internal Homm3DirectStateAdapterId AdapterId { get; }
	internal string ContractId { get; }
	internal string FamilyKey { get; }
	internal Homm3DirectStateHookSurface HookSurfaces { get; }
	internal Homm3DirectStateAdapterCaps Caps { get; }
	internal Homm3DirectStateOperation[] Operations { get; }
	internal Homm3DirectStateJournalOpcode[] JournalOpcodes { get; }
	internal string FixtureFlag { get; }
	internal string ProofLabel { get; }
	internal string ReconciliationPolicy { get; }
}

/// <summary>
/// Code-side exhaustive manifest. JSON can select rows and tune values within
/// these hard caps, but cannot introduce executable expressions or new
/// operations. Adding an adapter requires adding a typed row here.
/// </summary>
internal static class Homm3DirectStateAdapterManifest
{
	private static readonly Homm3DirectStateAdapterCaps DefaultCaps =
		new(maxRootWork: 64, maxDepth: 8, maxJournalEntries: 64, maxFanout: 16, maxDirtyIdentities: 32, maxQueueSpan: 32);

	private static readonly Homm3DirectStateAdapterRecord[] Records =
	{
		null,
		Record(Homm3DirectStateAdapterId.Damage, "damage", "damage", Homm3DirectStateHookSurface.UnitInit | Homm3DirectStateHookSurface.DamageApplying | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.DamageFlatDelta }, Array.Empty<Homm3DirectStateJournalOpcode>()),
		Record(Homm3DirectStateAdapterId.Cast, "cast", "cast", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.ActionEnd | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.CastChain }, new[] { Homm3DirectStateJournalOpcode.ManagerInt, Homm3DirectStateJournalOpcode.EventToken }),
		Record(Homm3DirectStateAdapterId.Focus, "focus", "resource", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.FocusGrant, Homm3DirectStateOperation.FocusSpend, Homm3DirectStateOperation.FocusSet }, new[] { Homm3DirectStateJournalOpcode.ManagerInt, Homm3DirectStateJournalOpcode.NativeIntMember }),
		Record(Homm3DirectStateAdapterId.Cooldown, "cooldown", "resource", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.RoundStart | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.CooldownSet, Homm3DirectStateOperation.CooldownReduce, Homm3DirectStateOperation.CooldownIncrease, Homm3DirectStateOperation.CooldownCharges, Homm3DirectStateOperation.CooldownCastCounter }, new[] { Homm3DirectStateJournalOpcode.NativeIntMember }),
		Record(Homm3DirectStateAdapterId.Status, "status", "status", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.RoundStart | Homm3DirectStateHookSurface.RoundEnd | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.StatusApply, Homm3DirectStateOperation.StatusRefresh, Homm3DirectStateOperation.StatusTick, Homm3DirectStateOperation.StatusExpire, Homm3DirectStateOperation.StatusRemove }, new[] { Homm3DirectStateJournalOpcode.StatusLedger }),
		Record(Homm3DirectStateAdapterId.Movement, "movement", "movement", Homm3DirectStateHookSurface.UnitInit | Homm3DirectStateHookSurface.DamageApplied | Homm3DirectStateHookSurface.MovementCommitted | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.MovementPush, Homm3DirectStateOperation.MovementPull, Homm3DirectStateOperation.MovementTeleport, Homm3DirectStateOperation.MovementSetImmobile }, new[] { Homm3DirectStateJournalOpcode.Occupancy, Homm3DirectStateJournalOpcode.ManagerInt }),
		Record(Homm3DirectStateAdapterId.Summon, "summon", "lifecycle", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.UnitInit | Homm3DirectStateHookSurface.ObjectSpawned | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.SummonCreate }, new[] { Homm3DirectStateJournalOpcode.NativeListSnapshot }),
		Record(Homm3DirectStateAdapterId.Trap, "trap", "lifecycle", Homm3DirectStateHookSurface.CastCommitted | Homm3DirectStateHookSurface.MovementCommitted | Homm3DirectStateHookSurface.ObjectSpawned | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.TrapSpawn, Homm3DirectStateOperation.TrapTrigger, Homm3DirectStateOperation.TrapDespawn }, new[] { Homm3DirectStateJournalOpcode.Trap }),
		Record(Homm3DirectStateAdapterId.Corpse, "corpse", "lifecycle", Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.CorpseCreate, Homm3DirectStateOperation.CorpseConsume }, new[] { Homm3DirectStateJournalOpcode.Corpse }),
		Record(Homm3DirectStateAdapterId.NestedDamage, "nestedDamage", "nestedDamage", Homm3DirectStateHookSurface.DamageApplying | Homm3DirectStateHookSurface.DamageApplied | Homm3DirectStateHookSurface.ActionEnd | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.NestedReflection, Homm3DirectStateOperation.NestedRedirection, Homm3DirectStateOperation.NestedSplash }, Array.Empty<Homm3DirectStateJournalOpcode>()),
		Record(Homm3DirectStateAdapterId.Kill, "kill", "kill", Homm3DirectStateHookSurface.DamageApplied | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.KillConfirm }, new[] { Homm3DirectStateJournalOpcode.ManagerObject, Homm3DirectStateJournalOpcode.EventToken }),
		Record(Homm3DirectStateAdapterId.AllyDeath, "allyDeath", "kill", Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.AllyDeathObserve }, new[] { Homm3DirectStateJournalOpcode.ManagerObject, Homm3DirectStateJournalOpcode.EventToken }),
		Record(Homm3DirectStateAdapterId.ActionQueue, "actionQueue", "action", Homm3DirectStateHookSurface.ActionStart | Homm3DirectStateHookSurface.ActionEnd | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.ActionQueueInsert, Homm3DirectStateOperation.ActionQueueRemove }, new[] { Homm3DirectStateJournalOpcode.NativeListSnapshot }),
		Record(Homm3DirectStateAdapterId.TurnOrder, "turnOrder", "turnOrder", Homm3DirectStateHookSurface.RoundStart | Homm3DirectStateHookSurface.ActionEnd | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.TurnOrderReorder }, new[] { Homm3DirectStateJournalOpcode.NativeListSnapshot }),
		Record(Homm3DirectStateAdapterId.Aura, "aura", "aura", Homm3DirectStateHookSurface.UnitInit | Homm3DirectStateHookSurface.MovementCommitted | Homm3DirectStateHookSurface.ObjectSpawned | Homm3DirectStateHookSurface.ObjectDestroyed | Homm3DirectStateHookSurface.RoundStart | Homm3DirectStateHookSurface.BattleResult,
			new[] { Homm3DirectStateOperation.AuraDefine, Homm3DirectStateOperation.AuraRefresh, Homm3DirectStateOperation.AuraRemove }, new[] { Homm3DirectStateJournalOpcode.Aura }),
	};

	private static readonly Dictionary<string, Homm3DirectStateAdapterRecord> ByContractId =
		BuildContractIndex();

	internal static int Count => Records.Length - 1;

	internal static bool TryGet(Homm3DirectStateAdapterId adapterId, out Homm3DirectStateAdapterRecord record)
	{
		var index = (int)adapterId;
		if (index <= 0 || index >= Records.Length)
		{
			record = null;
			return false;
		}
		record = Records[index];
		return record != null && record.AdapterId == adapterId;
	}

	internal static bool TryGet(string contractId, out Homm3DirectStateAdapterRecord record)
	{
		record = null;
		return !string.IsNullOrWhiteSpace(contractId)
		       && ByContractId.TryGetValue(contractId.Trim(), out record)
		       && record != null;
	}

	internal static Homm3DirectStateAdapterRecord[] Snapshot()
	{
		var result = new Homm3DirectStateAdapterRecord[Records.Length - 1];
		Array.Copy(Records, 1, result, 0, result.Length);
		return result;
	}

	internal static bool ValidateExhaustive(out string failReason)
	{
		for (var value = 1; value <= Count; value++)
		{
			var adapterId = (Homm3DirectStateAdapterId)value;
			if (!TryGet(adapterId, out var record))
			{
				failReason = "stable AdapterId " + value + " has no exact manifest record";
				return false;
			}
			if (string.IsNullOrWhiteSpace(record.ContractId)
			    || string.IsNullOrWhiteSpace(record.FamilyKey)
			    || string.IsNullOrWhiteSpace(record.FixtureFlag)
			    || string.IsNullOrWhiteSpace(record.ProofLabel)
			    || record.Operations.Length == 0
			    || record.HookSurfaces == Homm3DirectStateHookSurface.None)
			{
				failReason = "AdapterId " + adapterId + " has incomplete executable wiring";
				return false;
			}
			// JournalOpcodes may be empty for families that mutate without journaling
			// (Damage / NestedDamage pre-commit scalar). Do not invent unused opcodes.
		}
		failReason = null;
		return true;
	}

	private static Homm3DirectStateAdapterRecord Record(
		Homm3DirectStateAdapterId id,
		string contractId,
		string familyKey,
		Homm3DirectStateHookSurface hooks,
		Homm3DirectStateOperation[] operations,
		Homm3DirectStateJournalOpcode[] opcodes)
	{
		return new Homm3DirectStateAdapterRecord(
			id,
			contractId,
			familyKey,
			hooks,
			DefaultCaps,
			operations,
			opcodes,
			"homm3_runtime_" + contractId + "_pilot.flag",
			familyKey + ".runtime-unvalidated",
			GetReconciliationPolicy(id));
	}

	private static string GetReconciliationPolicy(Homm3DirectStateAdapterId id)
	{
		return id switch
		{
			Homm3DirectStateAdapterId.Damage => "preCommitScalar",
			Homm3DirectStateAdapterId.Cast => "committedEventAndDeferredChildren",
			Homm3DirectStateAdapterId.Focus => "directStorageAndEnergyView",
			Homm3DirectStateAdapterId.Cooldown => "directStorageAndAbilityView",
			Homm3DirectStateAdapterId.Status => "managerAuthoritativeNoNativeInventory",
			Homm3DirectStateAdapterId.Movement => "atomicOccupancyAndView",
			Homm3DirectStateAdapterId.Summon => "battleSideOccupancyAndView",
			Homm3DirectStateAdapterId.Trap => "managerObjectAndOccupancy",
			Homm3DirectStateAdapterId.Corpse => "managerAuthoritativeCorpse",
			Homm3DirectStateAdapterId.NestedDamage => "preCommitRedirectAndPostCommitChildren",
			Homm3DirectStateAdapterId.Kill => "committedDestructionAtMostOnce",
			Homm3DirectStateAdapterId.AllyDeath => "committedDestructionAtMostOnce",
			Homm3DirectStateAdapterId.ActionQueue => "authoritativeQueueAndDerivedView",
			Homm3DirectStateAdapterId.TurnOrder => "authoritativeStableSplice",
			Homm3DirectStateAdapterId.Aura => "dirtyIdentityMembership",
			_ => throw new InvalidOperationException("AdapterId has no reconciliation policy: " + id),
		};
	}

	private static Dictionary<string, Homm3DirectStateAdapterRecord> BuildContractIndex()
	{
		var result = new Dictionary<string, Homm3DirectStateAdapterRecord>(StringComparer.Ordinal);
		for (var i = 1; i < Records.Length; i++)
		{
			var record = Records[i] ?? throw new InvalidOperationException("direct-state adapter manifest row " + i + " is null");
			if ((int)record.AdapterId != i)
				throw new InvalidOperationException("direct-state AdapterId values must be stable and contiguous at " + i);
			if (!result.TryAdd(record.ContractId, record))
				throw new InvalidOperationException("duplicate direct-state adapter contractId '" + record.ContractId + "'");
		}
		return result;
	}
}
