using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace OfflineUnlockMod;

/// <summary>
/// Custom battle-local state for law effects that are safer as mod-owned state
/// than as native buff/status mutations. Source-prepared June 19; runtime proof
/// is still required for each consuming law.
/// </summary>
internal static partial class Homm3BattleLocalLawState
{
	private const int StrongholdBloodFeudMaxPercent = 20;
	// Native-identity keyed (AGENTS.md: managed proxy != native identity). Store and read sites reach
	// the same native unit/side through different proxies (e.g. counterattack observation vs
	// DamageInfo.Caster); ConditionalWeakTable<object,...> silently missed. Cleared with the
	// battle-side indexed state because native pointers are reused after battle teardown.
	private static readonly Homm3NativeKeyedTable<UnitDamageState> UnitDamageStates = new("battle-local unit damage state");
	private static readonly Homm3NativeKeyedTable<LawOwnerBattleState> LawOwnerStates = new("battle-local law owner state");
	private static readonly Dictionary<int, int> RampartAvengerReprisalPercentByDataSideIndex = new();
	private static readonly Dictionary<int, int> RampartAvengerMarkCountByHexIndex = new();
	private static readonly object LockObject = new();

	private sealed partial class UnitDamageState
	{
		internal int StrongholdBloodFeudDamagePercent;
		internal int RampartAvengerMarkCount;
		internal int RampartAvengerReprisalOneShotDamagePercent;
		internal int DungeonOutnumberOneShotDamagePercent;
		internal int ConfluxBacklashOneShotDamagePercent;
		internal int NecropolisDeathGripOneShotDamagePercent;

		internal int BattleActionOneShotDamagePercent;
		internal int MoraleOneShotDamagePercent;
		internal int FortressThornedHidesArmedDamageReductionPercent;
		internal int FortressThornedHidesNextOutgoingDamageReductionPercent;
	}

	private sealed partial class LawOwnerBattleState
	{
		internal int TowerSpellcastDamagePercent;
		internal bool CoveFirstHeroicFocusGranted;
		internal int RampartAvengerReprisalOneShotDamagePercent;
	}

	internal static void ClearBattleSideIndexedState(string reason)
	{
		lock (LockObject)
		{
			RampartAvengerReprisalPercentByDataSideIndex.Clear();
			RampartAvengerMarkCountByHexIndex.Clear();
			UnitDamageStates.Clear();
			LawOwnerStates.Clear();
			Homm3TrainingDamageLawRuntime.ClearBurningAshForBattle();
			AdvanceRuntimeMechanicGenerationLocked();
		}
		Plugin.LogSource?.LogInfo("HoMM3 battle-local law state cleared indexed state: " + (reason ?? "unspecified") + ".");
	}
	internal static bool TryAddTowerSpellcastDamagePercent(
		object lawOwner,
		int percentDelta,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (lawOwner == null)
		{
			failReason = "Tower spellcast damage requires exact law owner";
			return false;
		}
		if (percentDelta <= 0)
		{
			failReason = "Tower spellcast damage percent delta must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = LawOwnerStates.GetOrCreateValue(lawOwner);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.TowerSpellcastDamagePercent;
			state.TowerSpellcastDamagePercent = Math.Min(60, checked(state.TowerSpellcastDamagePercent + percentDelta));
			newPercent = state.TowerSpellcastDamagePercent;
		}
		failReason = null;
		return true;
	}

	internal static bool TryGetTowerSpellcastDamagePercent(
		object lawOwner,
		out int percent,
		out string failReason)
	{
		percent = 0;
		if (lawOwner == null)
		{
			failReason = "Tower spellcast damage requires exact law owner";
			return false;
		}
		lock (LockObject)
		{
			if (!LawOwnerStates.TryGetValue(lawOwner, out var state) || state == null || state.TowerSpellcastDamagePercent <= 0)
			{
				failReason = "law owner has no Tower spellcast battle-local damage state";
				return false;
			}
			percent = state.TowerSpellcastDamagePercent;
		}
		failReason = null;
		return true;
	}

	internal static bool TryConsumeCoveFirstHeroicFocusGrant(
		object lawOwner,
		out string failReason)
	{
		if (lawOwner == null)
		{
			failReason = "Cove first heroic Focus credit requires exact law owner";
			return false;
		}
		lock (LockObject)
		{
			var state = LawOwnerStates.GetOrCreateValue(lawOwner);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			if (state.CoveFirstHeroicFocusGranted)
			{
				failReason = "Cove first heroic Focus credit already granted for this law-owner battle state";
				return false;
			}
			state.CoveFirstHeroicFocusGranted = true;
		}
		failReason = null;
		return true;
	}
	internal static bool TryMarkRampartAvengerTarget(
		object battleUnit,
		out int oldMarkCount,
		out int newMarkCount,
		out string failReason,
		bool applyMarker = true,
		int markerDuration = 99,
		string markerSource = "Rampart Avenger intensity")
	{
		oldMarkCount = 0;
		newMarkCount = 0;
		if (battleUnit == null)
		{
			failReason = "Avenger mark requires exact target battle unit";
			return false;
		}

		var hasHexIndex = TryResolveBattleHexIndex(battleUnit, out var hexIndex, out var hexFailReason);
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			RampartAvengerMarkCountByHexIndex.TryGetValue(hexIndex, out var hexMarkCount);
			oldMarkCount = hasHexIndex ? Math.Max(state.RampartAvengerMarkCount, hexMarkCount) : state.RampartAvengerMarkCount;
			newMarkCount = Math.Min(99, checked(oldMarkCount + 1));
		}

		if (applyMarker
		    && !Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.AvengerIntensity, newMarkCount, markerDuration, markerSource))
		{
			newMarkCount = oldMarkCount;
			failReason = "custom Avenger marker SID was not applied";
			return false;
		}

		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			RampartAvengerMarkCountByHexIndex.TryGetValue(hexIndex, out var hexMarkCount);
			var currentMarkCount = hasHexIndex ? Math.Max(state.RampartAvengerMarkCount, hexMarkCount) : state.RampartAvengerMarkCount;
			if (currentMarkCount != oldMarkCount)
			{
				failReason = "Avenger mark state changed while applying marker";
				newMarkCount = currentMarkCount;
				return false;
			}
			state.RampartAvengerMarkCount = newMarkCount;
			if (hasHexIndex)
				RampartAvengerMarkCountByHexIndex[hexIndex] = newMarkCount;
		}
		if (!hasHexIndex)
			LogRampartAvenger("marked object without exact hex alias: target=" + DescribeRuntimeObject(battleUnit) + " reason=" + hexFailReason + ".");
		failReason = null;
		return true;
	}


	internal static bool TryRequireRampartAvengerMark(
		object battleUnit,
		out int markCount,
		out string failReason)
	{
		markCount = 0;
		if (battleUnit == null)
		{
			failReason = "Avenger mark requires exact target battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (UnitDamageStates.TryGetValue(battleUnit, out var state) && state != null && state.RampartAvengerMarkCount > 0)
			{
				markCount = state.RampartAvengerMarkCount;
				failReason = null;
				return true;
			}
		}

		if (!TryResolveBattleHexIndex(battleUnit, out var hexIndex, out var hexFailReason))
		{
			failReason = "target has no Rampart Avenger battle-local object mark and no exact battle hex alias: " + hexFailReason;
			return false;
		}
		lock (LockObject)
		{
			if (!RampartAvengerMarkCountByHexIndex.TryGetValue(hexIndex, out markCount) || markCount <= 0)
			{
				failReason = "target has no Rampart Avenger battle-local mark for hex index " + hexIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
				markCount = 0;
				return false;
			}
		}
		failReason = null;
		return true;
	}
	internal static bool TryArmConfluxBacklash(
		object battleUnit,
		int damagePercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Elemental Backlash requires exact counterattacking battle unit";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = "Elemental Backlash damage percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.ConfluxBacklashOneShotDamagePercent;
			state.ConfluxBacklashOneShotDamagePercent = damagePercent;
			newPercent = state.ConfluxBacklashOneShotDamagePercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.ConfluxBacklash, Math.Max(1, newPercent), 2, "Conflux Elemental Backlash armed");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeConfluxBacklash(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (battleUnit == null)
		{
			failReason = "Elemental Backlash requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.ConfluxBacklashOneShotDamagePercent <= 0)
			{
				failReason = "damaging unit has no armed Elemental Backlash battle-local state";
				return false;
			}
			damagePercent = state.ConfluxBacklashOneShotDamagePercent;
			state.ConfluxBacklashOneShotDamagePercent = 0;
		}
		failReason = null;
		return true;
	}

	internal static bool TryArmNecropolisDeathGrip(
		object battleUnit,
		int damagePercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Death Grip requires exact counterattacking battle unit";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = "Death Grip damage percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.NecropolisDeathGripOneShotDamagePercent;
			state.NecropolisDeathGripOneShotDamagePercent = damagePercent;
			newPercent = state.NecropolisDeathGripOneShotDamagePercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.NecropolisDeathGrip, Math.Max(1, newPercent), 2, "Necropolis Death Grip armed");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeNecropolisDeathGrip(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (battleUnit == null)
		{
			failReason = "Death Grip requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.NecropolisDeathGripOneShotDamagePercent <= 0)
			{
				failReason = "damaging unit has no armed Death Grip battle-local state";
				return false;
			}
			damagePercent = state.NecropolisDeathGripOneShotDamagePercent;
			state.NecropolisDeathGripOneShotDamagePercent = 0;
		}
		failReason = null;
		return true;
	}
	internal static bool TryArmRampartAvengerReprisal(
		object battleUnit,
		int damagePercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Avenger's Reprisal requires exact counterattacker battle unit";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = "Avenger's Reprisal damage percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.RampartAvengerReprisalOneShotDamagePercent;
			state.RampartAvengerReprisalOneShotDamagePercent = damagePercent;
			newPercent = state.RampartAvengerReprisalOneShotDamagePercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.AvengerReprisal, 1, 2, "Rampart Avenger Reprisal armed");
		failReason = null;
		return true;
	}
	internal static bool TryArmRampartAvengerReprisalForLawOwner(
		object lawOwner,
		object counterattackerBattleUnit,
		int damagePercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (lawOwner == null)
		{
			failReason = "Avenger's Reprisal requires exact law owner";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = "Avenger's Reprisal damage percent must be positive";
			return false;
		}
		if (!TryResolveDataSideIndex(lawOwner, out var dataSideIndex, out failReason))
		{
			failReason = "Avenger's Reprisal requires canonical Data.Side index for law owner: " + failReason;
			return false;
		}
		lock (LockObject)
		{
			RampartAvengerReprisalPercentByDataSideIndex.TryGetValue(dataSideIndex, out oldPercent);
			RampartAvengerReprisalPercentByDataSideIndex[dataSideIndex] = damagePercent;
			newPercent = damagePercent;
		}
		if (counterattackerBattleUnit != null)
			Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(counterattackerBattleUnit, Homm3CustomLawVisualMarkerRuntime.AvengerReprisal, 1, 2, "Rampart Avenger Reprisal armed");
		LogRampartReprisal("armed side-indexed state: dataSideIndex=" + dataSideIndex + " oldPercent=" + oldPercent + " newPercent=" + newPercent + " lawOwner=" + DescribeRuntimeObject(lawOwner) + " counterattacker=" + DescribeRuntimeObject(counterattackerBattleUnit) + ".");
		failReason = null;
		return true;
	}
	internal static bool TryConsumeRampartAvengerReprisal(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (battleUnit == null)
		{
			failReason = "Avenger's Reprisal requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.RampartAvengerReprisalOneShotDamagePercent <= 0)
			{
				failReason = "damaging unit has no armed Avenger's Reprisal battle-local state";
				return false;
			}
			damagePercent = state.RampartAvengerReprisalOneShotDamagePercent;
			state.RampartAvengerReprisalOneShotDamagePercent = 0;
		}
		failReason = null;
		return true;
	}
	internal static bool TryConsumeRampartAvengerReprisalForLawOwner(
		object lawOwner,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (lawOwner == null)
		{
			failReason = "Avenger's Reprisal requires exact law owner";
			return false;
		}
		if (!TryResolveDataSideIndex(lawOwner, out var dataSideIndex, out failReason))
		{
			failReason = "Avenger's Reprisal requires canonical Data.Side index for law owner: " + failReason;
			LogRampartReprisal("consume failed before state lookup: " + failReason + " lawOwner=" + DescribeRuntimeObject(lawOwner) + ".");
			return false;
		}
		lock (LockObject)
		{
			if (!RampartAvengerReprisalPercentByDataSideIndex.TryGetValue(dataSideIndex, out damagePercent) || damagePercent <= 0)
			{
				damagePercent = 0;
				failReason = "law owner has no armed Avenger's Reprisal side-indexed battle-local state for Data.Side index " + dataSideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
				LogRampartReprisal("consume miss: " + failReason + " lawOwner=" + DescribeRuntimeObject(lawOwner) + ".");
				return false;
			}
			RampartAvengerReprisalPercentByDataSideIndex.Remove(dataSideIndex);
		}
		LogRampartReprisal("consumed side-indexed state: dataSideIndex=" + dataSideIndex + " percent=" + damagePercent + " lawOwner=" + DescribeRuntimeObject(lawOwner) + ".");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeSingleRampartAvengerReprisal(
		out int dataSideIndex,
		out int damagePercent,
		out string failReason)
	{
		dataSideIndex = -1;
		damagePercent = 0;
		lock (LockObject)
		{
			if (RampartAvengerReprisalPercentByDataSideIndex.Count == 0)
			{
				failReason = "no armed Avenger's Reprisal side-indexed battle-local state";
				LogRampartReprisal("single consume miss: " + failReason + ".");
				return false;
			}
			if (RampartAvengerReprisalPercentByDataSideIndex.Count != 1)
			{
				failReason = "ambiguous armed Avenger's Reprisal side-indexed state count " + RampartAvengerReprisalPercentByDataSideIndex.Count.ToString(System.Globalization.CultureInfo.InvariantCulture);
				LogRampartReprisal("single consume blocked: " + failReason + ".");
				return false;
			}
			foreach (var entry in RampartAvengerReprisalPercentByDataSideIndex)
			{
				dataSideIndex = entry.Key;
				damagePercent = entry.Value;
				break;
			}
			if (damagePercent <= 0)
			{
				failReason = "armed Avenger's Reprisal percent is not positive for Data.Side index " + dataSideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
				LogRampartReprisal("single consume blocked: " + failReason + ".");
				return false;
			}
			RampartAvengerReprisalPercentByDataSideIndex.Remove(dataSideIndex);
		}
		LogRampartReprisal("single consumed side-indexed state: dataSideIndex=" + dataSideIndex + " percent=" + damagePercent + ".");
		failReason = null;
		return true;
	}
	private static bool TryResolveBattleHexIndex(object battleObject, out int hexIndex, out string failReason)
	{
		hexIndex = -1;
		if (battleObject == null)
		{
			failReason = "battle object is null";
			return false;
		}
		if (!TryReadExactObject(battleObject, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex) || hex == null)
		{
			failReason = "battle object exposed no exact hex";
			return false;
		}
		if (!TryReadExactInt(hex, GameSymbols.BattleEventLaws.HexIndexMembers, out hexIndex))
		{
			failReason = "battle hex exposed no exact index";
			return false;
		}
		if (hexIndex < 0)
		{
			failReason = "battle hex index is negative: " + hexIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryReadExactObject(object owner, string[] names, out object value)
	{
		value = null;
		return TryReadExactMember(owner, names, out value);
	}

	private static bool TryReadExactInt(object owner, string[] names, out int value)
	{
		value = 0;
		if (!TryReadExactMember(owner, names, out var raw) || raw == null)
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

	private static bool TryReadExactMember(object owner, string[] names, out object value)
	{
		value = null;
		if (owner == null || names == null)
			return false;
		var type = owner.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(owner);
						return true;
					}
				}
				catch { }
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(owner, null);
						return true;
					}
				}
				catch { }
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
					{
						value = method.Invoke(owner, Array.Empty<object>());
						return true;
					}
				}
				catch { }
			}
		}
		return false;
	}

	private static bool TryResolveDataSideIndex(object dataSide, out int dataSideIndex, out string failReason)
	{
		dataSideIndex = -1;
		if (dataSide == null)
		{
			failReason = "Data.Side object is null";
			return false;
		}
		var type = dataSide.GetType();
		for (var i = 0; i < GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers.Length; i++)
		{
			var name = GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers[i];
			if (string.IsNullOrEmpty(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType == typeof(int) && !method.ContainsGenericParameters)
					{
						dataSideIndex = (int)method.Invoke(dataSide, Array.Empty<object>());
						if (dataSideIndex >= 0)
						{
							failReason = null;
							return true;
						}
						failReason = "Data.Side index method '" + name + "' returned negative value " + dataSideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
						return false;
					}
				}
				catch (Exception ex)
				{
					failReason = "Data.Side index method '" + name + "' threw: " + ex.Message;
					return false;
				}
				try
				{
					var field = current.GetField(name, flags);
					if (field != null && field.FieldType == typeof(int))
					{
						dataSideIndex = (int)field.GetValue(dataSide);
						if (dataSideIndex >= 0)
						{
							failReason = null;
							return true;
						}
						failReason = "Data.Side index field '" + name + "' returned negative value " + dataSideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
						return false;
					}
				}
				catch (Exception ex)
				{
					failReason = "Data.Side index field '" + name + "' threw: " + ex.Message;
					return false;
				}
			}
		}
		failReason = "Data.Side index member not found on " + DescribeRuntimeObject(dataSide);
		return false;
	}

	private static void LogRampartAvenger(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record("HoMM3 Rampart Avenger state: " + message);
		Plugin.LogSource?.LogInfo("HoMM3 Rampart Avenger state: " + message);
	}

	private static void LogRampartReprisal(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record("HoMM3 Rampart Avenger's Reprisal state: " + message);
		Plugin.LogSource?.LogInfo("HoMM3 Rampart Avenger's Reprisal state: " + message);
	}

	private static string DescribeRuntimeObject(object value)
	{
		return value == null ? "null" : value.GetType().FullName ?? value.GetType().Name;
	}
internal static bool TryArmDungeonOutnumber(
		object battleUnit,
		int damagePercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Outnumber requires exact counterattacker battle unit";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = "Outnumber damage percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.DungeonOutnumberOneShotDamagePercent;
			state.DungeonOutnumberOneShotDamagePercent = damagePercent;
			newPercent = state.DungeonOutnumberOneShotDamagePercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.DungeonOutnumber, Math.Max(1, newPercent), 2, "Dungeon Outnumber armed");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeDungeonOutnumber(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (battleUnit == null)
		{
			failReason = "Outnumber requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.DungeonOutnumberOneShotDamagePercent <= 0)
			{
				failReason = "damaging unit has no armed Outnumber battle-local state";
				return false;
			}
			damagePercent = state.DungeonOutnumberOneShotDamagePercent;
			state.DungeonOutnumberOneShotDamagePercent = 0;
		}
		failReason = null;
		return true;
	}

		internal static bool TryArmBattleActionOneShotDamage(
		object battleUnit,
		int damagePercent,
		string markerLabel,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		return TryArmGenericOneShotDamage(
			battleUnit,
			damagePercent,
			markerLabel,
			state => state.BattleActionOneShotDamagePercent,
			(state, value) => state.BattleActionOneShotDamagePercent = value,
			out oldPercent,
			out newPercent,
			out failReason);
	}

	internal static bool TryConsumeBattleActionOneShotDamage(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		return TryConsumeGenericOneShotDamage(
			battleUnit,
			"BattleAction",
			state => state.BattleActionOneShotDamagePercent,
			(state, value) => state.BattleActionOneShotDamagePercent = value,
			out damagePercent,
			out failReason);
	}

	internal static bool TryArmMoraleOneShotDamage(
		object battleUnit,
		int damagePercent,
		string markerLabel,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		return TryArmGenericOneShotDamage(
			battleUnit,
			damagePercent,
			markerLabel,
			state => state.MoraleOneShotDamagePercent,
			(state, value) => state.MoraleOneShotDamagePercent = value,
			out oldPercent,
			out newPercent,
			out failReason);
	}

	internal static bool TryConsumeMoraleOneShotDamage(
		object battleUnit,
		out int damagePercent,
		out string failReason)
	{
		return TryConsumeGenericOneShotDamage(
			battleUnit,
			"Morale",
			state => state.MoraleOneShotDamagePercent,
			(state, value) => state.MoraleOneShotDamagePercent = value,
			out damagePercent,
			out failReason);
	}

	private static bool TryArmGenericOneShotDamage(
		object battleUnit,
		int damagePercent,
		string markerLabel,
		Func<UnitDamageState, int> getter,
		Action<UnitDamageState, int> setter,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = markerLabel + " requires exact battle unit";
			return false;
		}
		if (damagePercent <= 0)
		{
			failReason = markerLabel + " damage percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = getter(state);
			setter(state, Math.Max(oldPercent, damagePercent));
			newPercent = getter(state);
		}
		failReason = null;
		return true;
	}

	private static bool TryConsumeGenericOneShotDamage(
		object battleUnit,
		string label,
		Func<UnitDamageState, int> getter,
		Action<UnitDamageState, int> setter,
		out int damagePercent,
		out string failReason)
	{
		damagePercent = 0;
		if (battleUnit == null)
		{
			failReason = label + " one-shot damage requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || getter(state) <= 0)
			{
				failReason = "damaging unit has no armed " + label + " battle-local one-shot damage state";
				return false;
			}
			damagePercent = getter(state);
			setter(state, 0);
		}
		failReason = null;
		return true;
	}
internal static bool TryArmFortressThornedHides(
		object battleUnit,
		int damageReductionPercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Thorned Hides requires exact counterattacker battle unit";
			return false;
		}
		if (damageReductionPercent <= 0)
		{
			failReason = "Thorned Hides damage reduction percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.FortressThornedHidesArmedDamageReductionPercent;
			state.FortressThornedHidesArmedDamageReductionPercent = damageReductionPercent;
			newPercent = state.FortressThornedHidesArmedDamageReductionPercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.FortressThornedHidesArmed, Math.Max(1, newPercent), 2, "Fortress Thorned Hides armed");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeFortressThornedHidesCounterattack(
		object battleUnit,
		out int damageReductionPercent,
		out string failReason)
	{
		damageReductionPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Thorned Hides requires exact damaging battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.FortressThornedHidesArmedDamageReductionPercent <= 0)
			{
				failReason = "damaging unit has no armed Thorned Hides battle-local state";
				return false;
			}
			damageReductionPercent = state.FortressThornedHidesArmedDamageReductionPercent;
			state.FortressThornedHidesArmedDamageReductionPercent = 0;
		}
		failReason = null;
		return true;
	}

	internal static bool TryMarkFortressThornedHidesWeakened(
		object battleUnit,
		int damageReductionPercent,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Thorned Hides weakness requires exact struck battle unit";
			return false;
		}
		if (damageReductionPercent <= 0)
		{
			failReason = "Thorned Hides weakness damage reduction percent must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.FortressThornedHidesNextOutgoingDamageReductionPercent;
			state.FortressThornedHidesNextOutgoingDamageReductionPercent = Math.Max(
				state.FortressThornedHidesNextOutgoingDamageReductionPercent,
				damageReductionPercent);
			newPercent = state.FortressThornedHidesNextOutgoingDamageReductionPercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.FortressThornedHidesWeakness, Math.Max(1, newPercent), 2, "Fortress Thorned Hides weakness");
		failReason = null;
		return true;
	}

	internal static bool TryConsumeFortressThornedHidesWeakness(
		object battleUnit,
		out int damageReductionPercent,
		out string failReason)
	{
		damageReductionPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Thorned Hides weakness requires exact attacking battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.FortressThornedHidesNextOutgoingDamageReductionPercent <= 0)
			{
				failReason = "attacking unit has no Thorned Hides battle-local weakness";
				return false;
			}
			damageReductionPercent = state.FortressThornedHidesNextOutgoingDamageReductionPercent;
			state.FortressThornedHidesNextOutgoingDamageReductionPercent = 0;
		}
		failReason = null;
		return true;
	}	internal static bool TryAddStrongholdBloodFeudDamagePercent(
		object battleUnit,
		int percentDelta,
		out int oldPercent,
		out int newPercent,
		out string failReason)
	{
		oldPercent = 0;
		newPercent = 0;
		if (battleUnit == null)
		{
			failReason = "Blood Feud requires exact counterattacker battle unit";
			return false;
		}
		if (percentDelta <= 0)
		{
			failReason = "Blood Feud percent delta must be positive";
			return false;
		}
		lock (LockObject)
		{
			var state = UnitDamageStates.GetOrCreateValue(battleUnit);
			if (state == null)
			{
				failReason = "battle-local state refused: target has no native identity";
				return false;
			}
			oldPercent = state.StrongholdBloodFeudDamagePercent;
			state.StrongholdBloodFeudDamagePercent = Math.Min(
				StrongholdBloodFeudMaxPercent,
				checked(state.StrongholdBloodFeudDamagePercent + percentDelta));
			newPercent = state.StrongholdBloodFeudDamagePercent;
		}
		Homm3CustomLawVisualMarkerRuntime.TryApplyUnitMarker(battleUnit, Homm3CustomLawVisualMarkerRuntime.StrongholdBloodFeud, Math.Max(1, newPercent), 99, "Stronghold Blood Feud damage state");
		failReason = null;
		return true;
	}

	internal static bool TryGetStrongholdBloodFeudDamagePercent(
		object battleUnit,
		out int percent,
		out string failReason)
	{
		percent = 0;
		if (battleUnit == null)
		{
			failReason = "Blood Feud requires exact attacking battle unit";
			return false;
		}
		lock (LockObject)
		{
			if (!UnitDamageStates.TryGetValue(battleUnit, out var state) || state == null || state.StrongholdBloodFeudDamagePercent <= 0)
			{
				failReason = "attacking unit has no Blood Feud battle-local damage state";
				return false;
			}
			percent = state.StrongholdBloodFeudDamagePercent;
		}
		failReason = null;
		return true;
	}
}






