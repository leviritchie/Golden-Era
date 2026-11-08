using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Battle-scoped law-owner registry for combat packets.
/// Runtime status: source-prepared on June 19. Unit.Init registration is now required by battle-action candidate gameplay as well as diagnostics; individual law mutations remain packet-gated and fail closed.
/// </summary>
internal static class Homm3BattleUnitLawOwnerRegistry
{
	private const int RegistrationLogCap = 24;
	private static readonly object Gate = new();
	private static readonly Dictionary<long, object> UnitToTransferSide = new();
	private static readonly Dictionary<long, object> UnitKeyToUnit = new();
	/// <summary>Native IL2CPP pointer → managed config SID captured at Init/visual resolve.</summary>
	private static readonly Dictionary<long, string> UnitPointerToConfigSid = new();
	private static readonly Dictionary<long, object> TransferSideKeyToDataSide = new();
	private static readonly Dictionary<int, object> SideIndexToDataSide = new();
	private static readonly Dictionary<string, UnitInitConsumer> UnitInitConsumersByOwner = new(StringComparer.Ordinal);
	private static UnitInitConsumer[] _unitInitConsumers = Array.Empty<UnitInitConsumer>();
	private static bool _registered;
	private static int _registrationLogs;
	private static int _consumerFailureLogs;
	private static int _hitLogs;
	private static int _missLogs;
	private static int _dataSideResolveLogs;
	private static int _dataSideFailLogs;
	private static string _lastRegistrationSummary = "none";
	private static string _lastClearReason = "none";

	private sealed class UnitInitConsumer
	{
		internal readonly string Owner;
		internal readonly Action<object, object[]> Handler;

		internal UnitInitConsumer(string owner, Action<object, object[]> handler)
		{
			Owner = owner;
			Handler = handler;
		}
	}

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		Homm3RuntimeMechanicHooks.TryRegisterSharedUnitInit(harmony, log);
	}

	internal static MethodInfo ResolveUnitInitPostfix()
	{
		return AccessTools.Method(typeof(Homm3BattleUnitLawOwnerRegistry), nameof(PostfixUnitInit));
	}

	internal static void MarkRegistered()
	{
		_registered = true;
	}

	internal static void MarkUnregistered()
	{
		_registered = false;
	}

	internal static bool TryRegisterUnitInitConsumer(
		string owner,
		Action<object, object[]> handler,
		out string failReason)
	{
		failReason = null;
		if (string.IsNullOrWhiteSpace(owner) || handler == null)
		{
			failReason = "Unit.Init consumer owner and handler are required";
			return false;
		}
		if (!_registered)
		{
			failReason = "shared Unit.Init owner is not registered";
			return false;
		}

		lock (Gate)
		{
			if (UnitInitConsumersByOwner.TryGetValue(owner, out var existing))
			{
				if (existing.Handler == handler)
					return true;
				failReason = "Unit.Init consumer owner is already registered with a different handler: " + owner;
				return false;
			}

			var consumer = new UnitInitConsumer(owner, handler);
			var current = _unitInitConsumers;
			var next = new UnitInitConsumer[current.Length + 1];
			Array.Copy(current, next, current.Length);
			next[current.Length] = consumer;
			UnitInitConsumersByOwner.Add(owner, consumer);
			Volatile.Write(ref _unitInitConsumers, next);
			return true;
		}
	}

	internal static void Clear(string reason)
	{
		BattleCombatTransactionManager.AbortRoot(reason ?? "law-owner registry clear");
		BattleCombatTransactionManager.ResetForBattleCleanup();
		Homm3RuntimeMechanicFixtureHarness.ClearForBattle();
		lock (Gate)
		{
			UnitToTransferSide.Clear();
			UnitKeyToUnit.Clear();
			UnitPointerToConfigSid.Clear();
			TransferSideKeyToDataSide.Clear();
			SideIndexToDataSide.Clear();
			Homm3BattleLocalLawState.ClearBattleSideIndexedState(reason);
			_lastClearReason = reason ?? "unspecified";
		}
		Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry cleared: " + (reason ?? "unspecified") + ".");
	}

	/// <summary>
	/// SID captured at Unit.Init / visual resolve as a managed string, keyed by native
	/// IL2CPP pointer so DamageApplied wrappers still resolve. Never re-read live string fields.
	/// </summary>
	internal static bool TryGetRegisteredConfigSid(object battleUnit, out string configSid)
	{
		configSid = null;
		if (!TryGetUnitNativePointer(battleUnit, out var pointer))
			return false;
		lock (Gate)
		{
			if (!UnitPointerToConfigSid.TryGetValue(pointer, out var sid) || string.IsNullOrWhiteSpace(sid))
				return false;
			configSid = sid;
			return true;
		}
	}

	/// <summary>
	/// Upgrade/replace the registered SID for a live unit (e.g. visual path resolved h3_* after
	/// Init stored a donor sid). Rebinds runtime mechanics when the SID has an active binding.
	/// </summary>
	internal static void NoteUnitConfigSid(object battleUnit, object battleSide, string configSid)
	{
		configSid = NormalizeRegisteredConfigSid(configSid);
		if (battleUnit == null || string.IsNullOrWhiteSpace(configSid))
			return;
		if (!TryGetUnitNativePointer(battleUnit, out var pointer))
			return;
		lock (Gate)
		{
			UnitPointerToConfigSid[pointer] = configSid;
		}
		if (battleSide != null
		    && Homm3RuntimeMechanicRegistry.TryGetActiveBinding(configSid, out var runtimeBinding))
			Homm3BattleLocalLawState.BindRuntimeMechanics(battleUnit, battleSide, runtimeBinding);
	}

	/// <summary>
	/// When battle visuals resolve a custom h3_* SID, upgrade any Init registrations that still
	/// hold that unit's donor scaffold SID and rebind mechanics.
	/// </summary>
	internal static void UpgradeDonorRegistrationsToCustomSid(string customSid)
	{
		customSid = NormalizeRegisteredConfigSid(customSid);
		if (string.IsNullOrWhiteSpace(customSid)
		    || !Homm3CustomFactionRegistry.IsCustomUnitSid(customSid)
		    || !Homm3CustomFactionRegistry.TryGetDonorSid(customSid, out var donorSid)
		    || string.IsNullOrWhiteSpace(donorSid))
			return;

		List<KeyValuePair<long, object>> units;
		lock (Gate)
		{
			var upgrades = new List<long>();
			foreach (var pair in UnitPointerToConfigSid)
			{
				if (string.Equals(pair.Value, donorSid, StringComparison.OrdinalIgnoreCase))
					upgrades.Add(pair.Key);
			}
			for (var i = 0; i < upgrades.Count; i++)
				UnitPointerToConfigSid[upgrades[i]] = customSid;

			units = new List<KeyValuePair<long, object>>(UnitKeyToUnit.Count);
			foreach (var pair in UnitKeyToUnit)
				units.Add(pair);
		}

		if (!Homm3RuntimeMechanicRegistry.TryGetActiveBinding(customSid, out var runtimeBinding))
			return;
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i].Value;
			if (!TryGetRegisteredConfigSid(unit, out var sid)
			    || !string.Equals(sid, customSid, StringComparison.OrdinalIgnoreCase))
				continue;
			object battleSide = null;
			TryResolveTransferSide(unit, out battleSide);
			if (battleSide != null)
				Homm3BattleLocalLawState.BindRuntimeMechanics(unit, battleSide, runtimeBinding);
		}
	}

	internal static bool TryGetUnitNativePointer(object battleUnit, out long pointer)
	{
		pointer = 0;
		if (battleUnit is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;
		pointer = il2Cpp.Pointer.ToInt64();
		return true;
	}

	internal static void RegisterDataSide(int sideIndex, object dataSide)
	{
		if (sideIndex < 0 || dataSide == null)
			return;
		lock (Gate)
		{
			SideIndexToDataSide[sideIndex] = dataSide;
		}
	}

	internal static bool TryResolveDataSide(object battleUnit, out object dataSide)
	{
		dataSide = null;
		if (!TryResolveTransferSide(battleUnit, out var battleSide))
			return false;
		if (TryResolveDataSideFromBattleSide(battleSide, out dataSide))
			return true;
		if (!TryReadInt(battleSide, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out var sideIndex))
		{
			LogDataSideFailure("battle-side-to-data-side stage failed: TransferSide exposed no exact sideIdInWorld/side index: battleSide=" + DescribeObject(battleSide));
			return false;
		}
		lock (Gate)
		{
			if (SideIndexToDataSide.TryGetValue(sideIndex, out dataSide) && dataSide != null)
			{
				if (_dataSideResolveLogs++ < RegistrationLogCap)
					Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from preseeded side map: sideIndex=" + sideIndex + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
				return true;
			}
		}
		if (!TryResolveGlobalDataSide(sideIndex, out dataSide, out var failReason))
		{
			LogDataSideFailure("global Data.Side lookup failed: sideIndex=" + sideIndex + " reason=" + failReason);
			return false;
		}
		RegisterDataSide(sideIndex, dataSide);
		if (_dataSideResolveLogs++ < RegistrationLogCap)
			Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from global root: sideIndex=" + sideIndex + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
		return true;
	}
	internal static bool TryResolveDataSideFromBattleSide(object battleSide, out object dataSide)
	{
		dataSide = null;
		if (battleSide == null)
			return false;
		var battleSideKey = Homm3DirectStateIdentity.ResolveKeyOrZero(battleSide);
		lock (Gate)
		{
			if (TransferSideKeyToDataSide.TryGetValue(battleSideKey, out dataSide) && dataSide != null)
			{
				if (_dataSideResolveLogs++ < RegistrationLogCap)
					Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from TransferSide object map: transferSideKey=" + battleSideKey + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
				return true;
			}
		}
		// Runtime-proofed 2026-06-20: live ObjectPublicPrcgObPrcgInTrPrcgInUnique
		// battle-side wrappers carry field_Public_Int32_0 as the battle-local side index.
		// That index matches SideIndexToDataSide keys. Native TransferSide.sideIdInWorld
		// is not reliable for garrison battles because both sides can report 0.
		if (TryReadObject(battleSide, GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers, out var nativeTransferSide)
		    && nativeTransferSide != null
		    && !ReferenceEquals(nativeTransferSide, battleSide)
		    && TryReadInt(battleSide, GameSymbols.BattleEventLaws.BattleSideWrapperLocalSideIndexMembers, out var wrapperSideIndex))
		{
			lock (Gate)
			{
				if (SideIndexToDataSide.TryGetValue(wrapperSideIndex, out dataSide) && dataSide != null)
				{
					RegisterTransferSideDataSide(battleSide, dataSide, "runtime-proven battle-side wrapper local index");
					if (_dataSideResolveLogs++ < RegistrationLogCap)
						Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from battle-side wrapper local index: wrapperSideIndex=" + wrapperSideIndex + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
					return true;
				}
			}
			LogDataSideFailure("battle-side wrapper local-index lookup failed: wrapperSideIndex=" + wrapperSideIndex + " battleSide=" + DescribeObject(battleSide) + " nativeTransferSide=" + DescribeObject(nativeTransferSide));
		}
		if (Homm3CustomFactionLawRuntime.TryResolveDataSideFromBattleTransferSide(battleSide, out dataSide, out var transferSideBridgeReason))
		{
			RegisterTransferSideDataSide(battleSide, dataSide, "TransferSide.logicHero bridge");
			return true;
		}
		if (!TryReadInt(battleSide, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out var sideIndex))
		{
			LogDataSideFailure("caster battle-side-to-data-side stage failed: TransferSide exposed no exact sideIdInWorld/side index: battleSide=" + DescribeObject(battleSide) + "; logicHero bridge failed: " + transferSideBridgeReason);
			return false;
		}
		lock (Gate)
		{
			if (SideIndexToDataSide.TryGetValue(sideIndex, out dataSide) && dataSide != null)
			{
				RegisterTransferSideDataSide(battleSide, dataSide, "preseeded side-index map");
				if (_dataSideResolveLogs++ < RegistrationLogCap)
					Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from exact caster battle side: sideIndex=" + sideIndex + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
				return true;
			}
		}
		if (!TryResolveGlobalDataSide(sideIndex, out dataSide, out var failReason))
		{
			LogDataSideFailure("caster battle side global Data.Side lookup failed: sideIndex=" + sideIndex + " reason=" + failReason + "; logicHero bridge failed: " + transferSideBridgeReason);
			return false;
		}
		RegisterDataSide(sideIndex, dataSide);
		RegisterTransferSideDataSide(battleSide, dataSide, "global side-index map");
		if (_dataSideResolveLogs++ < RegistrationLogCap)
			Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved data side from exact caster battle side/global root: sideIndex=" + sideIndex + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
		return true;
	}

	private static void RegisterTransferSideDataSide(object battleSide, object dataSide, string source)
	{
		if (battleSide == null || dataSide == null)
			return;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(battleSide);
		lock (Gate)
		{
			TransferSideKeyToDataSide[key] = dataSide;
		}
		if (TryReadInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var dataSideIndex))
			RegisterDataSide(dataSideIndex, dataSide);
		if (_dataSideResolveLogs++ < RegistrationLogCap)
			Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry registered TransferSide object owner: transferSideKey=" + key + " source=" + (source ?? "unspecified") + " dataSide=" + DescribeObject(dataSide) + ". Registered for diagnostics/packet-gated candidate gameplay.");
	}
	internal static void RegisterBattleObjectTransferSide(object battleObject, object transferSide, string source)
	{
		if (battleObject == null || transferSide == null)
			return;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(battleObject);
		lock (Gate)
		{
			UnitKeyToUnit[key] = battleObject;
			UnitToTransferSide[key] = transferSide;
			_lastRegistrationSummary = "unitKey=" + key + "; source=" + (source ?? "explicit battle-object side") + "; objectType=" + DescribeObject(battleObject) + "; battleSide=" + DescribeObject(transferSide);
		}
	}

    internal static bool TryResolveTransferSide(object battleUnit, out object transferSide)
    {
        transferSide = null;
        if (battleUnit == null)
            return false;
        var key = Homm3DirectStateIdentity.ResolveKeyOrZero(battleUnit);
        lock (Gate)
        {
            if (UnitToTransferSide.TryGetValue(key, out transferSide) && transferSide != null)
            {
                if (_hitLogs++ < RegistrationLogCap)
                    Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry hit: unitKey=" + key + " battleSide=" + DescribeObject(transferSide) + ".");
                return true;
            }
        }

        // June 20 chained-xref ownership fix: do not treat FieldObject.basa() as
        // a TransferSide. Current DiffableCs/ISIL show dxy.ceis -> ede/FieldObject,
        // then FieldObject.basa()/bcuk()/cfnp -> eir battle context, then eir.cgle
        // -> exact TransferSide. This is a narrow native route, not a broad fallback.
        var transferSideSource = "exact battle-object TransferSide";
        if (!TryReadObject(battleUnit, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out transferSide) || transferSide == null)
        {
            if (TryReadObject(battleUnit, GameSymbols.BattleEventLaws.BattleObjectBattleContextMembers, out var battleContext)
                && battleContext != null
                && !ReferenceEquals(battleContext, battleUnit)
                && TryReadObject(battleContext, GameSymbols.BattleEventLaws.BattleContextTransferSideMembers, out transferSide)
                && transferSide != null)
            {
                transferSideSource = "exact battle-context TransferSide";
            }
            else
            {
                // Last exact alias route: if the event object is a field object that still
                // has a current hex occupant, resolve that occupant through the normal
                // registry. This is retained for non-counterattack field-object payloads.
                if (TryReadObject(battleUnit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex)
                    && hex != null
                    && TryReadObject(hex, GameSymbols.BattleEventLaws.HexOccupantMembers, out var occupant)
                    && occupant != null
                    && !ReferenceEquals(occupant, battleUnit)
                    && TryResolveTransferSide(occupant, out transferSide)
                    && transferSide != null)
                {
                    lock (Gate)
                    {
                        UnitKeyToUnit[key] = battleUnit;
                        UnitToTransferSide[key] = transferSide;
                        _lastRegistrationSummary = "unitKey=" + key + "; source=exact battle-object hex occupant alias; objectType=" + DescribeObject(battleUnit) + "; occupant=" + DescribeObject(occupant) + "; battleSide=" + DescribeObject(transferSide);
                    }
                    if (_hitLogs++ < RegistrationLogCap)
                        Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved exact hex occupant alias: unitKey=" + key + " occupant=" + DescribeObject(occupant) + " battleSide=" + DescribeObject(transferSide) + ".");
                    return true;
                }

                if (_missLogs++ < RegistrationLogCap)
                    Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry miss: unitKey=" + key + " unitType=" + DescribeObject(battleUnit) + "; exact direct TransferSide, battle-context TransferSide, and hex occupant alias routes failed.");
                return false;
            }
        }

        lock (Gate)
        {
            UnitKeyToUnit[key] = battleUnit;
            UnitToTransferSide[key] = transferSide;
            _lastRegistrationSummary = "unitKey=" + key + "; source=" + transferSideSource + "; unitType=" + DescribeObject(battleUnit) + "; battleSide=" + DescribeObject(transferSide);
        }
        if (_hitLogs++ < RegistrationLogCap)
            Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry resolved " + transferSideSource + ": unitKey=" + key + " battleSide=" + DescribeObject(transferSide) + ".");
        return true;
    }

	internal static int RegisteredUnitCount
	{
		get
		{
			lock (Gate)
			{
				return UnitKeyToUnit.Count;
			}
		}
	}

	internal static string LastRegistrationSummary
	{
		get
		{
			lock (Gate)
			{
				return _lastRegistrationSummary;
			}
		}
	}

	internal static string LastClearReason
	{
		get
		{
			lock (Gate)
			{
				return _lastClearReason;
			}
		}
	}

	internal static List<BattleUnitSnapshot> SnapshotUnits(int limit)
	{
		limit = Math.Max(1, Math.Min(limit, 64));
		var snapshot = new List<BattleUnitSnapshot>(limit);
		KeyValuePair<long, object>[] units;
		lock (Gate)
		{
			units = new KeyValuePair<long, object>[UnitKeyToUnit.Count];
			var index = 0;
			foreach (var pair in UnitKeyToUnit)
				units[index++] = pair;
		}

		for (var i = 0; i < units.Length && snapshot.Count < limit; i++)
		{
			var unitKey = units[i].Key;
			var unit = units[i].Value;
			object transferSide = null;
			TryResolveTransferSide(unit, out transferSide);
			var sideIndex = -1;
			var sideIndexKnown = transferSide != null
			                     && TryReadInt(transferSide, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out sideIndex);
			object dataSide = null;
			var dataSideKnown = TryResolveDataSide(unit, out dataSide);
			Homm3CustomFactionLawRuntime.ActiveLawState trainingLaw = default;
			var trainingLawKnown = dataSideKnown
			                       && Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(
				                       dataSide,
				                       Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
				                       out trainingLaw);
			snapshot.Add(new BattleUnitSnapshot(
				unitKey,
				unit,
				transferSide,
				sideIndexKnown,
				sideIndex,
				dataSideKnown,
				dataSide,
				trainingLawKnown,
				trainingLaw));
		}
		return snapshot;
	}

	internal readonly struct BattleUnitSnapshot
	{
		internal readonly long UnitKey;
		internal readonly object Unit;
		internal readonly object TransferSide;
		internal readonly bool SideIndexKnown;
		internal readonly int SideIndex;
		internal readonly bool DataSideKnown;
		internal readonly object DataSide;
		internal readonly bool TrainingLawKnown;
		internal readonly Homm3CustomFactionLawRuntime.ActiveLawState TrainingLaw;

		internal BattleUnitSnapshot(
			long unitKey,
			object unit,
			object transferSide,
			bool sideIndexKnown,
			int sideIndex,
			bool dataSideKnown,
			object dataSide,
			bool trainingLawKnown,
			Homm3CustomFactionLawRuntime.ActiveLawState trainingLaw)
		{
			UnitKey = unitKey;
			Unit = unit;
			TransferSide = transferSide;
			SideIndexKnown = sideIndexKnown;
			SideIndex = sideIndex;
			DataSideKnown = dataSideKnown;
			DataSide = dataSide;
			TrainingLawKnown = trainingLawKnown;
			TrainingLaw = trainingLaw;
		}
	}
	private static void PostfixUnitInit(object __instance, object[] __args)
	{
		if (__instance == null)
			return;
		var unitRecorded = false;
		try
		{
			if (__args == null || __args.Length < 3)
				return;
			var battleSide = __args[2];
			if (battleSide == null)
				return;
			var key = Homm3DirectStateIdentity.ResolveKeyOrZero(__instance);
			lock (Gate)
			{
				UnitKeyToUnit[key] = __instance;
				UnitToTransferSide[key] = battleSide;
				unitRecorded = true;
			}
			if (__args.Length < 8)
				return;
			var rawSid = NormalizeRegisteredConfigSid(__args[7]);
			var configSid = ResolveMechanicConfigSid(rawSid);
			lock (Gate)
			{
				if (TryGetUnitNativePointer(__instance, out var pointer))
				{
					if (!string.IsNullOrWhiteSpace(configSid))
						UnitPointerToConfigSid[pointer] = configSid;
					else
						UnitPointerToConfigSid.Remove(pointer);
				}
				_lastRegistrationSummary = "unitKey=" + key
					+ "; pointer=" + (TryGetUnitNativePointer(__instance, out var p) ? p.ToString() : "none")
					+ "; configSid=" + (configSid ?? "null")
					+ "; rawSid=" + (rawSid ?? "null")
					+ "; slot=" + (__args[4]?.ToString() ?? "null")
					+ "; stacks=" + (__args[5]?.ToString() ?? "null")
					+ "; battleSide=" + DescribeObject(battleSide);
			}
			if (_registrationLogs++ < RegistrationLogCap)
			{
				Plugin.LogSource?.LogInfo(
					"HoMM3 battle unit law-owner registry registered:"
					+ " unitKey=" + key
					+ " configSid='" + (configSid ?? "null") + "'"
					+ " rawSid='" + (rawSid ?? "null") + "'"
					+ " slot='" + (__args[4]?.ToString() ?? "null") + "'"
					+ " stacks='" + (__args[5]?.ToString() ?? "null") + "'"
					+ " battleSide=" + DescribeObject(battleSide)
					+ ". Registered for diagnostics/packet-gated candidate gameplay.");
			}
			if (Homm3RuntimeMechanicRegistry.TryGetActiveBinding(configSid, out var runtimeBinding))
				Homm3BattleLocalLawState.BindRuntimeMechanics(__instance, battleSide, runtimeBinding);
			Homm3DirectStateIngressDispatcher.DispatchUnitInit(__instance, battleSide);
		}
		catch (Exception ex)
		{
			if (_registrationLogs++ < RegistrationLogCap)
				Plugin.LogSource?.LogWarning("HoMM3 battle unit law-owner registry or Direct State ingress failed during Unit.Init postfix: " + ex.Message);
		}
		finally
		{
			if (unitRecorded)
				DispatchUnitInitConsumers(__instance, __args);
		}
	}

	private static void DispatchUnitInitConsumers(object unit, object[] args)
	{
		var consumers = Volatile.Read(ref _unitInitConsumers);
		for (var i = 0; i < consumers.Length; i++)
		{
			var consumer = consumers[i];
			try
			{
				consumer.Handler(unit, args);
			}
			catch (Exception ex)
			{
				if (Interlocked.Increment(ref _consumerFailureLogs) <= RegistrationLogCap)
					Plugin.LogSource?.LogWarning(
						"HoMM3 shared Unit.Init consumer failed closed: owner="
						+ consumer.Owner + " reason=" + ex.Message);
			}
		}
	}

	private static bool IsRegistryRequired()
	{
		if (Homm3RuntimeMechanicRegistry.HasPreparedMechanics)
			return true;
		if (Homm3DiagnosticFlags.IsEnabled(Homm3CustomFactionLawRuntime.DiagnosticFlag))
			return true;
		return Homm3CustomLawPacketGate.IsGameplayAllowed(Homm3CustomLawPacketGate.BattleAction, out _)
		       || Homm3CustomLawPacketGate.IsGameplayAllowed(Homm3CustomLawPacketGate.CommittedDamage, out _)
		       || Homm3CustomLawPacketGate.IsGameplayAllowed(Homm3CustomLawPacketGate.Morale, out _);
	}
	private static Type ResolveUnitType()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				var type = asm.GetType(GameSymbols.BattleUnitInit.UnitTypeId, throwOnError: false);
				if (type != null)
					return type;
			}
			catch
			{
			}
		}
		try { return typeof(Unit); }
		catch { return null; }
	}

	internal static bool TryResolveGlobalDataSide(int sideIndex, out object dataSide, out string failReason)
	{
		dataSide = null;
		failReason = null;
		if (sideIndex < 0)
		{
			failReason = "negative side index";
			return false;
		}
		var logicRoot = ResolveGlobalLogicRoot(out failReason);
		if (logicRoot == null)
		{
			if (string.IsNullOrEmpty(failReason))
				failReason = "global logic root unresolved";
			return false;
		}
		if (!TryReadObject(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootDataMembers, out var dataRoot) || dataRoot == null)
		{
			failReason = "logic root data member unreadable on " + DescribeObject(logicRoot);
			return false;
		}
		if (!TryReadObject(dataRoot, GameSymbols.CustomFactionLawRuntime.DataRootSidesMembers, out var dataSides) || dataSides == null)
		{
			failReason = "Data.sides member unreadable on " + DescribeObject(dataRoot);
			return false;
		}
		if (!TryReadObject(dataSides, GameSymbols.CustomFactionLawRuntime.DataSidesArrayMembers, out var sidesArray) || sidesArray is not System.Collections.IEnumerable enumerable)
		{
			failReason = "Data.sides.array member unreadable or not enumerable on " + DescribeObject(dataSides);
			return false;
		}
		var checkedCandidates = 0;
		foreach (var candidate in enumerable)
		{
			if (candidate == null)
				continue;
			checkedCandidates++;
			if (!TryReadInt(candidate, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var candidateIndex))
				continue;
			if (candidateIndex != sideIndex)
				continue;
			dataSide = candidate;
			return true;
		}
		failReason = "no Data.Side candidate with index " + sideIndex + " among " + checkedCandidates + " non-null candidates";
		return false;
	}

	private static object ResolveGlobalLogicRoot(out string failReason)
	{
		failReason = null;
		foreach (var typeName in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints)
		{
			var type = GameMember.FindType("customFactionLawRuntime.globalLogicRoot." + typeName, typeName) ?? AccessTools.TypeByName(typeName);
			if (type == null)
			{
				failReason = "global logic root type not found: " + typeName;
				continue;
			}
			foreach (var name in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootInstanceMembers)
			{
				if (string.IsNullOrEmpty(name))
					continue;
				try
				{
					var prop = type.GetProperty(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
					if (prop != null && prop.GetIndexParameters().Length == 0 && type.IsAssignableFrom(prop.PropertyType))
					{
						var value = prop.GetValue(null, null);
						if (value == null)
							failReason = "global logic root property returned null: " + type.FullName + "." + name;
						return value;
					}
				}
				catch
				{
				}
				try
				{
					var method = type.GetMethod(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
					if (method != null && type.IsAssignableFrom(method.ReturnType))
					{
						var value = method.Invoke(null, Array.Empty<object>());
						if (value == null)
							failReason = "global logic root method returned null: " + type.FullName + "." + name;
						return value;
					}
				}
				catch
				{
				}
				try
				{
					var field = type.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
					if (field != null && type.IsAssignableFrom(field.FieldType))
					{
						var value = field.GetValue(null);
						if (value == null)
							failReason = "global logic root field returned null: " + type.FullName + "." + name;
						return value;
					}
				}
				catch
				{
				}
			}
			failReason = "global logic root singleton member not found on " + type.FullName;
		}
		if (string.IsNullOrEmpty(failReason))
			failReason = "no global logic root type hints configured";
		return null;
	}

	private static void LogDataSideFailure(string message)
	{
		if (_dataSideFailLogs++ < RegistrationLogCap)
			Plugin.LogSource?.LogInfo("HoMM3 battle unit law-owner registry data side proof failed closed: " + message + ". Registered for diagnostics/packet-gated candidate gameplay.");
	}
	private static bool TryReadObject(object obj, string[] names, out object value)
	{
		value = null;
		if (obj == null || names == null)
			return false;
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var prop = current.GetProperty(name, flags);
					if (prop != null && prop.GetIndexParameters().Length == 0)
					{
						value = prop.GetValue(obj, null);
						return value != null;
					}
				}
				catch
				{
				}
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
					{
						value = method.Invoke(obj, Array.Empty<object>());
						return value != null;
					}
				}
				catch
				{
				}
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(obj);
						return value != null;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}
	private static bool TryReadInt(object obj, string[] names, out int value)
	{
		value = 0;
		if (obj == null || names == null)
			return false;
		var type = obj.GetType();
		foreach (var name in names)
		{
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
						value = (int)method.Invoke(obj, Array.Empty<object>());
						return true;
					}
				}
				catch
				{
				}
				try
				{
					var field = current.GetField(name, flags);
					if (field != null && field.FieldType == typeof(int))
					{
						value = (int)field.GetValue(obj);
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

	private static string NormalizeRegisteredConfigSid(object raw)
	{
		if (raw == null)
			return null;
		try
		{
			var text = raw as string ?? raw.ToString();
			return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
		}
		catch
		{
			return null;
		}
	}

	/// <summary>
	/// Unit.Init often passes the donor scaffold SID (e.g. griffin_upg). Map to the unique
	/// custom SID that owns an active runtime-mechanic binding when possible.
	/// </summary>
	internal static string ResolveMechanicConfigSid(string rawSid)
	{
		if (string.IsNullOrWhiteSpace(rawSid))
			return null;
		rawSid = rawSid.Trim();
		if (Homm3CustomFactionRegistry.IsCustomUnitSid(rawSid))
			return rawSid;

		string uniqueBound = null;
		var boundCount = 0;
		string uniqueAny = null;
		var anyCount = 0;
		foreach (var customSid in Homm3CustomFactionRegistry.EnumerateCustomUnitSids())
		{
			if (!Homm3CustomFactionRegistry.TryGetDonorSid(customSid, out var donorSid)
			    || !string.Equals(donorSid, rawSid, StringComparison.OrdinalIgnoreCase))
				continue;
			anyCount++;
			uniqueAny = customSid;
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveBinding(customSid, out _))
				continue;
			boundCount++;
			uniqueBound = customSid;
		}
		if (boundCount == 1)
			return uniqueBound;
		if (anyCount == 1)
			return uniqueAny;
		return rawSid;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeObject(object value)
	{
		return value == null ? "null" : value.GetType().FullName ?? value.GetType().Name;
	}
}



