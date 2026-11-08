using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;

namespace OfflineUnlockMod;

internal enum Homm3RuntimeLawCacheStatus
{
	Unknown,
	Present,
	Absent,
	Failed,
}

internal enum Homm3RuntimeMechanicApplicationScope
{
	Unit,
	LawSide,
}

internal readonly struct Homm3RuntimeMechanicApplication
{
	internal Homm3RuntimeMechanicApplication(
		int mechanicIndex,
		int generation,
		Homm3RuntimeMechanicApplicationScope scope,
		object lawOwner,
		object sideScope)
	{
		MechanicIndex = mechanicIndex;
		Generation = generation;
		Scope = scope;
		LawOwner = lawOwner;
		SideScope = sideScope;
	}

	internal int MechanicIndex { get; }
	internal int Generation { get; }
	internal Homm3RuntimeMechanicApplicationScope Scope { get; }
	internal object LawOwner { get; }
	internal object SideScope { get; }
}

internal static partial class Homm3BattleLocalLawState
{
	private sealed partial class UnitDamageState
	{
		internal int RuntimeMechanicGeneration;
		internal int RuntimeUnitMechanicIndex = -1;
		internal int RuntimeLawMechanicIndex = -1;
		internal int RuntimeUnitConsumed;
		internal int RuntimeLawOwnerGeneration;
		internal int RuntimeLawOwnerStatus;
		internal object RuntimeLawOwner;
		internal object RuntimeBattleSide;
	}

	private sealed partial class LawOwnerBattleState
	{
		internal int RuntimeMechanicGeneration;
		internal int RuntimeMechanicIndex = -1;
		internal int RuntimeLawStatus;
		internal int RuntimeLawRank;
		internal int RuntimeLawConsumed;
		internal int RuntimeBattleApplicationCount;
		internal object RuntimeLawOwner;
	}

	private static int RuntimeMechanicGeneration = 1;
	private static readonly Dictionary<long, BoundUnitMechanicState> UnitPointerToBoundMechanics = new();

	private struct BoundUnitMechanicState
	{
		internal int Generation;
		internal int UnitMechanicIndex;
		internal int LawMechanicIndex;
		internal object BattleSide;
	}

	internal static int CurrentRuntimeMechanicGeneration => Volatile.Read(ref RuntimeMechanicGeneration);
	internal static object RuntimeTransactionSyncRoot => LockObject;

	internal static void BindRuntimeMechanics(
		object battleUnit,
		object battleSide,
		Homm3RuntimeMechanicBinding binding)
	{
		if (battleUnit == null
		    || battleSide == null
		    || !binding.HasAny
		    || !Homm3RuntimeMechanicRegistry.HasActiveMechanics)
			return;

		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
				return;
			state.RuntimeMechanicGeneration = RuntimeMechanicGeneration;
			state.RuntimeUnitMechanicIndex = binding.UnitMechanicIndex;
			state.RuntimeLawMechanicIndex = binding.LawMechanicIndex;
			state.RuntimeUnitConsumed = 0;
			state.RuntimeLawOwnerGeneration = RuntimeMechanicGeneration;
			state.RuntimeLawOwnerStatus = (int)Homm3RuntimeLawCacheStatus.Unknown;
			state.RuntimeLawOwner = null;
			state.RuntimeBattleSide = battleSide;

			// Pointer key survives Il2Cpp managed-wrapper identity changes across hooks.
			if (Homm3BattleUnitLawOwnerRegistry.TryGetUnitNativePointer(battleUnit, out var pointer))
			{
				UnitPointerToBoundMechanics[pointer] = new BoundUnitMechanicState
				{
					Generation = RuntimeMechanicGeneration,
					UnitMechanicIndex = binding.UnitMechanicIndex,
					LawMechanicIndex = binding.LawMechanicIndex,
					BattleSide = battleSide,
				};
			}
		}
	}

	internal static bool TryGetBoundUnitMechanicIndex(object battleUnit, out int mechanicIndex)
	{
		mechanicIndex = -1;
		if (battleUnit == null)
			return false;
		var generation = Volatile.Read(ref RuntimeMechanicGeneration);
		if (Homm3BattleUnitLawOwnerRegistry.TryGetUnitNativePointer(battleUnit, out var pointer))
		{
			lock (LockObject)
			{
				if (UnitPointerToBoundMechanics.TryGetValue(pointer, out var bound)
				    && bound.Generation == generation
				    && bound.UnitMechanicIndex >= 0)
				{
					mechanicIndex = bound.UnitMechanicIndex;
					return true;
				}
			}
		}
		if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null)
			return false;
		if (Volatile.Read(ref state.RuntimeMechanicGeneration) != generation)
			return false;
		mechanicIndex = Volatile.Read(ref state.RuntimeUnitMechanicIndex);
		return mechanicIndex >= 0;
	}

	internal static bool TryGetUnitRuntimeMechanicApplication(
		object battleUnit,
		out Homm3RuntimeMechanicApplication application)
	{
		application = default;
		if (battleUnit == null || !UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null)
			return false;

		var generation = Volatile.Read(ref RuntimeMechanicGeneration);
		if (Volatile.Read(ref state.RuntimeMechanicGeneration) != generation
		    || Volatile.Read(ref state.RuntimeUnitConsumed) != 0)
			return false;
		var mechanicIndex = Volatile.Read(ref state.RuntimeUnitMechanicIndex);
		if (mechanicIndex < 0)
			return false;

		application = new Homm3RuntimeMechanicApplication(
			mechanicIndex,
			generation,
			Homm3RuntimeMechanicApplicationScope.Unit,
			null,
			null);
		return true;
	}

	internal static bool TryGetLawRuntimeMechanicBinding(
		object battleUnit,
		out int mechanicIndex,
		out int generation,
		out Homm3RuntimeLawCacheStatus ownerStatus,
		out object lawOwner,
		out object battleSide)
	{
		mechanicIndex = -1;
		generation = Volatile.Read(ref RuntimeMechanicGeneration);
		ownerStatus = Homm3RuntimeLawCacheStatus.Unknown;
		lawOwner = null;
		battleSide = null;
		if (battleUnit == null || !UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null)
			return false;
		if (Volatile.Read(ref state.RuntimeMechanicGeneration) != generation)
			return false;

		mechanicIndex = Volatile.Read(ref state.RuntimeLawMechanicIndex);
		if (mechanicIndex < 0)
			return false;
		battleSide = Volatile.Read(ref state.RuntimeBattleSide);
		if (battleSide == null)
			return false;
		if (LawOwnerStates.TryGetValue(battleSide, out var sideState)
		    && sideState != null
		    && Volatile.Read(ref sideState.RuntimeMechanicGeneration) == generation
		    && Volatile.Read(ref sideState.RuntimeMechanicIndex) == mechanicIndex)
		{
			var sideStatus = (Homm3RuntimeLawCacheStatus)Volatile.Read(ref sideState.RuntimeLawStatus);
			if (sideStatus == Homm3RuntimeLawCacheStatus.Absent
			    || sideStatus == Homm3RuntimeLawCacheStatus.Failed
			    || (sideStatus == Homm3RuntimeLawCacheStatus.Present
			        && Volatile.Read(ref sideState.RuntimeLawConsumed) != 0))
				return false;
		}
		if (Volatile.Read(ref state.RuntimeLawOwnerGeneration) != generation)
			return true;

		ownerStatus = (Homm3RuntimeLawCacheStatus)Volatile.Read(ref state.RuntimeLawOwnerStatus);
		if (ownerStatus == Homm3RuntimeLawCacheStatus.Present)
			lawOwner = Volatile.Read(ref state.RuntimeLawOwner);
		return true;
	}

	internal static Homm3RuntimeLawCacheStatus PublishRuntimeLawOwner(
		object battleUnit,
		int generation,
		object lawOwner)
	{
		if (battleUnit == null)
			return Homm3RuntimeLawCacheStatus.Failed;
		lock (LockObject)
		{
			if (generation != RuntimeMechanicGeneration
			    || !UnitDamageStates.TryGetValue(battleUnit, out var state)
			    || state == null
			    || state.RuntimeMechanicGeneration != generation
			    || state.RuntimeLawMechanicIndex < 0)
				return Homm3RuntimeLawCacheStatus.Failed;

			var nextStatus = lawOwner == null
				? Homm3RuntimeLawCacheStatus.Failed
				: Homm3RuntimeLawCacheStatus.Present;
			if (state.RuntimeLawOwnerGeneration != generation)
			{
				state.RuntimeLawOwnerGeneration = generation;
				state.RuntimeLawOwnerStatus = (int)Homm3RuntimeLawCacheStatus.Unknown;
				state.RuntimeLawOwner = null;
			}

			var current = (Homm3RuntimeLawCacheStatus)state.RuntimeLawOwnerStatus;
			if (current == Homm3RuntimeLawCacheStatus.Unknown)
			{
				state.RuntimeLawOwner = lawOwner;
				Volatile.Write(ref state.RuntimeLawOwnerStatus, (int)nextStatus);
				return nextStatus;
			}
			if (current == Homm3RuntimeLawCacheStatus.Present
			    && nextStatus == Homm3RuntimeLawCacheStatus.Present
			    && Homm3NativeIdentity.Same(state.RuntimeLawOwner, lawOwner))
				return current;

			state.RuntimeLawOwner = null;
			Volatile.Write(ref state.RuntimeLawOwnerStatus, (int)Homm3RuntimeLawCacheStatus.Failed);
			return Homm3RuntimeLawCacheStatus.Failed;
		}
	}

	internal static Homm3RuntimeLawCacheStatus ReadRuntimeLawActivation(
		object sideScope,
		object lawOwner,
		int mechanicIndex,
		int generation,
		out int rank)
	{
		rank = 0;
		if (sideScope == null
		    || lawOwner == null
		    || !LawOwnerStates.TryGetValue(sideScope, out var state)
		    || state == null
		    || Volatile.Read(ref state.RuntimeMechanicGeneration) != generation
		    || Volatile.Read(ref state.RuntimeMechanicIndex) != mechanicIndex
		    || !Homm3NativeIdentity.Same(Volatile.Read(ref state.RuntimeLawOwner), lawOwner))
			return Homm3RuntimeLawCacheStatus.Unknown;

		var status = (Homm3RuntimeLawCacheStatus)Volatile.Read(ref state.RuntimeLawStatus);
		if (status == Homm3RuntimeLawCacheStatus.Present)
			rank = Volatile.Read(ref state.RuntimeLawRank);
		return status;
	}

	internal static Homm3RuntimeLawCacheStatus PublishRuntimeLawActivation(
		object sideScope,
		object lawOwner,
		int mechanicIndex,
		int generation,
		Homm3RuntimeLawCacheStatus status,
		int rank)
	{
		if (sideScope == null
		    || lawOwner == null
		    || status == Homm3RuntimeLawCacheStatus.Unknown
		    || generation != Volatile.Read(ref RuntimeMechanicGeneration))
			return Homm3RuntimeLawCacheStatus.Failed;

		lock (LockObject)
		{
			if (generation != RuntimeMechanicGeneration)
				return Homm3RuntimeLawCacheStatus.Failed;
			var state = LawOwnerStates.GetOrCreateValue(sideScope);
			if (state == null)
				return Homm3RuntimeLawCacheStatus.Failed;
			if (state.RuntimeMechanicGeneration != generation)
			{
				state.RuntimeMechanicGeneration = generation;
				state.RuntimeMechanicIndex = mechanicIndex;
				state.RuntimeLawStatus = (int)Homm3RuntimeLawCacheStatus.Unknown;
				state.RuntimeLawRank = 0;
				state.RuntimeLawConsumed = 0;
				state.RuntimeBattleApplicationCount = 0;
				state.RuntimeLawOwner = lawOwner;
			}
			if (state.RuntimeMechanicIndex != mechanicIndex
			    || !Homm3NativeIdentity.Same(state.RuntimeLawOwner, lawOwner))
			{
				state.RuntimeLawStatus = (int)Homm3RuntimeLawCacheStatus.Failed;
				return Homm3RuntimeLawCacheStatus.Failed;
			}

			var current = (Homm3RuntimeLawCacheStatus)state.RuntimeLawStatus;
			if (current == Homm3RuntimeLawCacheStatus.Unknown)
			{
				state.RuntimeLawRank = status == Homm3RuntimeLawCacheStatus.Present ? rank : 0;
				Volatile.Write(ref state.RuntimeLawStatus, (int)status);
				return status;
			}
			if (current == status
			    && (status != Homm3RuntimeLawCacheStatus.Present || state.RuntimeLawRank == rank))
				return current;

			state.RuntimeLawRank = 0;
			Volatile.Write(ref state.RuntimeLawStatus, (int)Homm3RuntimeLawCacheStatus.Failed);
			return Homm3RuntimeLawCacheStatus.Failed;
		}
	}

	internal static bool TryGetLawRuntimeMechanicApplication(
		int mechanicIndex,
		int generation,
		object lawOwner,
		object sideScope,
		out Homm3RuntimeMechanicApplication application)
	{
		application = default;
		if (lawOwner == null
		    || sideScope == null
		    || generation != Volatile.Read(ref RuntimeMechanicGeneration)
		    || !LawOwnerStates.TryGetValue(sideScope, out var state)
		    || state == null
		    || Volatile.Read(ref state.RuntimeMechanicGeneration) != generation
		    || Volatile.Read(ref state.RuntimeMechanicIndex) != mechanicIndex
		    || !Homm3NativeIdentity.Same(Volatile.Read(ref state.RuntimeLawOwner), lawOwner)
		    || (Homm3RuntimeLawCacheStatus)Volatile.Read(ref state.RuntimeLawStatus) != Homm3RuntimeLawCacheStatus.Present
		    || Volatile.Read(ref state.RuntimeLawConsumed) != 0)
			return false;

		application = new Homm3RuntimeMechanicApplication(
			mechanicIndex,
			generation,
			Homm3RuntimeMechanicApplicationScope.LawSide,
			lawOwner,
			sideScope);
		return true;
	}

	internal static bool TryCommitRuntimeMechanicDamage(
		object battleUnit,
		Homm3RuntimeMechanicApplication application,
		PreparedDamageMutation mutation,
		ref int damage)
	{
		if (battleUnit == null || !mutation.IsValid || mutation.MechanicIndex != application.MechanicIndex)
			return false;
		if (!BattleCombatTransactionManager.TryBegin(
			    battleUnit,
			    Homm3DirectStateAdapterId.Damage,
			    Homm3DirectStateOperation.DamageFlatDelta,
			    reserveJournal: 1,
			    reserveRootWork: 1,
			    out var transaction,
			    out _))
			return false;

		var oldDamage = damage;
		var consumedUnit = false;
		LawOwnerBattleState consumedLawState = null;
		using (transaction)
		{
			lock (LockObject)
			{
				if (application.Generation != RuntimeMechanicGeneration
				    || !UnitDamageStates.TryGetValue(battleUnit, out var unitState)
				    || unitState == null
				    || unitState.RuntimeMechanicGeneration != application.Generation)
					return false;

				if (application.Scope == Homm3RuntimeMechanicApplicationScope.Unit)
				{
					if (unitState.RuntimeUnitMechanicIndex != application.MechanicIndex
					    || unitState.RuntimeUnitConsumed != 0
					    || !NativeCombatWriteGateway.TryCommitPreparedDamage(ref damage, mutation))
						return false;
					Volatile.Write(ref unitState.RuntimeUnitConsumed, 1);
					consumedUnit = true;
				}
				else
				{
					if (application.Scope != Homm3RuntimeMechanicApplicationScope.LawSide
					    || application.LawOwner == null
					    || application.SideScope == null
					    || !Homm3NativeIdentity.Same(unitState.RuntimeBattleSide, application.SideScope)
					    || !Homm3NativeIdentity.Same(unitState.RuntimeLawOwner, application.LawOwner)
					    || !LawOwnerStates.TryGetValue(application.SideScope, out var lawState)
					    || lawState == null
					    || lawState.RuntimeMechanicGeneration != application.Generation
					    || lawState.RuntimeMechanicIndex != application.MechanicIndex
					    || !Homm3NativeIdentity.Same(lawState.RuntimeLawOwner, application.LawOwner)
					    || (Homm3RuntimeLawCacheStatus)lawState.RuntimeLawStatus != Homm3RuntimeLawCacheStatus.Present
					    || lawState.RuntimeLawConsumed != 0
					    || !NativeCombatWriteGateway.TryCommitPreparedDamage(ref damage, mutation))
						return false;

					Volatile.Write(ref lawState.RuntimeLawConsumed, 1);
					lawState.RuntimeBattleApplicationCount = checked(lawState.RuntimeBattleApplicationCount + 1);
					consumedLawState = lawState;
				}
			}
			if (!transaction.Commit(out _))
			{
				lock (LockObject)
				{
					damage = oldDamage;
					if (consumedUnit
					    && UnitDamageStates.TryGetValue(battleUnit, out var rollbackUnitState)
					    && rollbackUnitState != null)
						Volatile.Write(ref rollbackUnitState.RuntimeUnitConsumed, 0);
					if (consumedLawState != null)
					{
						Volatile.Write(ref consumedLawState.RuntimeLawConsumed, 0);
						consumedLawState.RuntimeBattleApplicationCount =
							Math.Max(0, consumedLawState.RuntimeBattleApplicationCount - 1);
					}
				}
					return false;
			}
		}
		return true;
	}

	private static void AdvanceRuntimeMechanicGenerationLocked()
	{
		RuntimeMechanicGeneration = RuntimeMechanicGeneration == int.MaxValue
			? 1
			: RuntimeMechanicGeneration + 1;
		UnitPointerToBoundMechanics.Clear();
		BattleCombatTransactionManager.ResetForBattleCleanup();
		ClearDirectStateLedgersLocked();
	}
}
