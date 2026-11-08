#!/usr/bin/env python3
"""Validate exhaustive direct-state adapter wiring and ownership invariants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


def fail(message: str) -> None:
    print(f"direct-state-adapter-invariants: {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

    manifest_source = read(plugin / "Homm3DirectStateAdapterManifest.cs")
    registry = read(plugin / "Homm3RuntimeMechanicRegistry.cs")
    transaction = read(plugin / "BattleCombatTransactionManager.cs")
    gateway = read(plugin / "NativeCombatWriteGateway.cs")
    adapters = read(plugin / "Homm3DirectStateAdapters.cs")
    hooks = read(plugin / "Homm3RuntimeMechanicHooks.cs")
    conflict_audit = read(plugin / "Homm3DirectStateConflictAudit.cs")
    fixture = read(plugin / "Homm3RuntimeMechanicFixtureHarness.cs")
    symbols = read(plugin / "GameSymbols.cs")
    owner_registry = read(plugin / "Homm3BattleUnitLawOwnerRegistry.cs")
    skeletal_runtime = read(plugin / "Homm3SkeletalNecromancyProbe.cs")
    handoff = read(root / "docs" / "runtime_mechanics_implementation_handoff.md")
    manifest_json = json.loads(
        read(root / "custom_factions" / "runtime_mechanics" / "homm3_adapter_manifest.json")
    )

    rows = manifest_json["adapters"]
    require(
        [row["stableId"] for row in rows] == list(range(1, 16)),
        "stable AdapterIds must remain append-only and contiguous 1..15",
    )
    contract_ids = [row["adapterId"] for row in rows]
    require(len(contract_ids) == len(set(contract_ids)), "AdapterIds must be unique")

    operations: list[str] = []
    proof_families: set[str] = set()
    for row in rows:
        operations.extend(row["operations"])
        proof_families.add(row["family"])
        require(
            row["proofLabel"] == f"{row['family']}.runtime-unvalidated",
            f"{row['adapterId']}: proof label must preserve proof boundary",
        )
        require(
            isinstance(row.get("reconciliationPolicy"), str)
            and bool(row["reconciliationPolicy"]),
            f"{row['adapterId']}: reconciliation policy is required",
        )
        require(
            all(isinstance(value, int) and value > 0 for value in row["caps"].values()),
            f"{row['adapterId']}: all caps must be positive integers",
        )
    require(len(operations) == len(set(operations)), "each operation must have one owner")

    enum_block = re.search(
        r"internal enum Homm3DirectStateAdapterId\s*\{(?P<body>.*?)\n\}",
        manifest_source,
        re.S,
    )
    require(enum_block is not None, "code AdapterId enum is missing")
    for row in rows:
        require(
            re.search(
                rf"\b{re.escape(row['adapterId'][0].upper() + row['adapterId'][1:])}\s*=\s*{row['stableId']}\b",
                enum_block.group("body"),
            )
            is not None,
            f"code enum missing stable row {row['adapterId']}={row['stableId']}",
        )
        require(
            f'"{row["adapterId"]}"' in manifest_source,
            f"code manifest missing contract ID {row['adapterId']}",
        )
        require(
            f'"{row["family"]}"' in manifest_source,
            f"code manifest missing family {row['family']}",
        )
        require(
            f'"{row["reconciliationPolicy"]}"' in manifest_source,
            f"code manifest missing reconciliation policy for {row['adapterId']}",
        )
    for operation in operations:
        require(
            operation in manifest_source,
            f"code manifest missing operation {operation}",
        )
        require(
            operation in adapters or operation == "DamageFlatDelta",
            f"typed executor surface missing operation {operation}",
        )

    for token in (
        "ValidateAdapterManifest",
        "TryParseOperation",
        "GetPreparedHookSurfaces",
        "IsAdapterPrepared",
        "IsAdapterActive",
        "RequiredArray",
        "JArray.Parse(token.ToString())",
    ):
        require(token in registry, f"registry missing exhaustive wiring token {token}")

    for token in (
        "Homm3DirectStateJournalEntry[]",
        "RemainingWork",
        "RemainingJournal",
        "RemainingFanout",
        "MaxDepth",
        "TryEnqueueChild",
        "TryDequeueChild",
        "RollbackInternal",
        "rootWorkHighWater",
    ):
        require(token in transaction, f"transaction bounds missing {token}")
    require("Stack<Action>" not in transaction, "rollback journal must not use callbacks")

    for token in (
        "NativeCombatWriteGateway",
        "TryRestore(",
        "TryCommitUnitHexMove",
        "TryInitializeAndInsertObject",
        "TryInvokeDeferredDamage",
        "TryInvokeRedirectedDamage",
        "TryResolveUnitAbility",
        "TryResolveActionQueue",
        "TryPrepareCooldownStorage",
        "HasWritableIntMember",
    ):
        require(token in gateway, f"gateway missing {token}")
    for forbidden in (".SetValue(", ".Insert(", ".RemoveAt(", "ApplyDamageMethod.Invoke"):
        require(forbidden not in adapters, f"adapter bypasses gateway with {forbidden}")

    require(
        "harmony.Patch(" in hooks and "harmony.Unpatch(" in hooks,
        "sole hook owner must register and precisely unpatch",
    )
    require(
        "harmony.Patch(" not in owner_registry,
        "battle unit registry must delegate Unit.Init ownership to runtime hooks",
    )
    require(
        "harmony.Patch(" not in skeletal_runtime
        and "ObserveBeforeBattleResult" in skeletal_runtime,
        "skeletal reward must delegate battle-result ownership to runtime hooks",
    )
    require(
        "Homm3DirectStateConflictAudit.TryAuditTarget" in hooks,
        "hook owner must audit claimed native surfaces before patching",
    )
    for token in ("Harmony.GetPatchInfo", "competingOwner", "native surface conflict"):
        require(token in conflict_audit, f"conflict audit missing {token}")
    for direct_file in (
        plugin / "BattleCombatTransactionManager.cs",
        plugin / "NativeCombatWriteGateway.cs",
        plugin / "Homm3DirectStateAdapters.cs",
        plugin / "Homm3BattleLocalLawState.DirectState.cs",
    ):
        source = read(direct_file)
        require(
            "harmony.Patch(" not in source and "new Harmony(" not in source,
            f"{direct_file.name} must not own Harmony hooks",
        )

    for token in (
        "DirectStateLaws",
        "SpellStoredCooldownMembers",
        "FocusValueMembers",
        "FieldObjectHexWriteMembers",
        "HexNeighbourFieldMembers",
        "ObjectSpawnedEventArgsTypeHints",
        "RoundActionEventArgsTypesAbsentLive",
        "BattleLogicEventsTypeHints",
        "ActionStartedDispatcher",
        "RoundEndedDispatcher",
        "UnitAbilityTypeHints",
    ):
        require(token in symbols, f"GameSymbols missing centralized binding {token}")
    # Round/action start-end have no typed EventArgs subclass in live interop (Hex.dll, 2026-09-26);
    # their hint sets missed every session and each miss paid a full TypeByName scan.
    for retired in (
        "RoundStartedEventArgsTypeHints",
        "RoundEndedEventArgsTypeHints",
        "ActionStartedEventArgsTypeHints",
        "ActionEndedEventArgsTypeHints",
    ):
        require(retired not in symbols, f"retired dead type hint set {retired} must not return to GameSymbols")
    require(
        "AccessTools.TypeByName" not in read(plugin / "Homm3BattleEventNativeAdapter.cs"),
        "Homm3BattleEventNativeAdapter must resolve types via GameMember.FindType only (no TypeByName full scan)",
    )
    require(
        "BattleLogicUnitHexCommit" not in symbols,
        "retired BattleLogic Unit_Hex commit symbol must not remain in GameSymbols",
    )
    unit_hex_native = read(plugin / "Homm3DirectStateUnitHexNative.cs")
    require(
        "TryMoveUnitHex" in unit_hex_native and "TryValidateSurface" in unit_hex_native,
        "movement write must live in Homm3DirectStateUnitHexNative",
    )

    for token in (
        "TryValidateSourceFixtures",
        "expectedOperationCount",
        "RecordDistinctHookCount",
        "RecordPresentationRetry",
        "FaultInjectionFlag",
        "AggregateStressFlag",
        "TryRunAggregateStress",
        "TryExerciseDepthBudget",
        "TryExerciseRootWorkBudget",
        "TryExerciseJournalBudget",
        "TryExerciseFanoutBudget",
        "generationAfterSecondCleanup",
    ):
        require(token in fixture, f"fixture harness missing {token}")

    for token in (
        "TryRecordCastCommit",
        "TryMutateFocus",
        "TryMutateCooldown",
        "TryApplyStatus",
        "TryTickOrExpireStatus",
        "DispatchDamageApplied",
        "TryEnqueueNestedDamageFromIngress",
        "ObserveDestroyed",
        "ObserveAction",
        "ObserveRound",
        "RefreshAuras",
        "TryRegisterSharedBattleResult",
        "ResolveBattleEventDispatcher",
        "PostfixBattleEventDispatched",
    ):
        require(token in hooks, f"typed fixture dispatch missing {token}")
    require(
        "BattleLogic Unit_Hex commit Harmony prefix is retired" in hooks
        or "Unit_Hex commit Harmony prefix is retired" in hooks,
        "hooks must document retired BattleLogic Unit_Hex Harmony path",
    )
    require(
        "PrefixMovementCommit" not in hooks,
        "retired PrefixMovementCommit must be deleted (immobility is enforced in TryMove)",
    )

    require(
        "TryApplyBellwetherPush" not in hooks,
        "Bellwether-named TryApplyBellwetherPush must be deleted from production hooks",
    )
    require(
        "LogBellwetherReject" not in hooks,
        "Bellwether-named LogBellwetherReject must be deleted from production hooks",
    )
    require(
        "NormalizeDamageApplyInvocation" in hooks
        or "NormalizeDamageApplyInvocation"
        in read(plugin / "Homm3BattleEventNativeAdapter.DamageIngress.cs"),
        "damage ingress must normalize once via Homm3BattleEventNativeAdapter",
    )
    dispatcher = read(plugin / "Homm3DirectStateIngressDispatcher.cs")
    require("CapLogOutcome" in dispatcher, "dispatcher must cap-log rejects/failures")
    require(
        "TryRouteMovementPush" in dispatcher,
        "damageApplied MovementPush must route via generic dispatcher",
    )
    require(
        "TryReadbackDamageSurfaceOwnership" in conflict_audit,
        "conflict audit must read back damage surface ownership",
    )
    # Defect: DamageApplied without typed prefix/__state pairing
    require(
        "var needsDamagePrefix = needsDamagePostfix" in hooks,
        "DamageApplied must always pair typed damage prefix for Harmony __state",
    )
    require(
        "out bool __state" in hooks and "if (!__state)" in hooks,
        "damage postfix must gate on Harmony __state from typed prefix",
    )
    # Defect: enabled-path silent return without capped outcome
    require(
        "CapLogOutcome" in dispatcher and "Homm3DirectStateIngressOutcome.Reject" in dispatcher,
        "enabled MovementPush path must emit capped named outcomes instead of silent returns",
    )
    for reject_token in (
        "MovementPush missing caster or receiver",
        "MovementPush non-positive damage",
        "no active mechanics for caster sid=",
        "bound MovementPush ability unresolved",
        "bound MovementPush ability mismatch",
    ):
        require(
            reject_token in dispatcher,
            f"MovementPush must CapLog named reject: {reject_token}",
        )

    damage_ingress = read(plugin / "Homm3BattleEventNativeAdapter.DamageIngress.cs")
    require(
        "TryResolveUnitSid" in damage_ingress,
        "DamageIngress must own TryResolveUnitSid",
    )
    require(
        "TryReadNativeStringMember" not in damage_ingress,
        "DamageApplied SID resolve must not call TryReadNativeStringMember (Il2CppStringToManaged can fatal-crash)",
    )
    require(
        "Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid" in damage_ingress,
        "DamageApplied SID resolve must prefer Init/visual registered managed SID",
    )
    require(
        "UnitPointerToConfigSid" in owner_registry,
        "law-owner registry must key config SID by native IL2CPP pointer, not managed GetHashCode",
    )
    require(
        "TryGetUnitNativePointer" in owner_registry,
        "law-owner registry must expose native pointer keying for cross-wrapper DamageApplied lookups",
    )
    require(
        "ResolveMechanicConfigSid" in owner_registry,
        "Unit.Init must reverse-map donor scaffold SIDs to custom SIDs for mechanic binding",
    )
    require(
        "UpgradeDonorRegistrationsToCustomSid" in owner_registry,
        "battle visual resolve must upgrade donor Init SIDs to h3_* custom SIDs",
    )
    runtime_mechanics_state = read(plugin / "Homm3BattleLocalLawState.RuntimeMechanics.cs")
    require(
        "UnitPointerToBoundMechanics" in runtime_mechanics_state,
        "runtime mechanic binds must be pointer-keyed so DamageApplied wrappers still see Init binds",
    )
    require(
        "TryValidateMovementPushIdentityContract" in fixture,
        "fixture harness must headless-validate donor→custom MovementPush identity before combat",
    )
    require(
        "DamageKillMapping.TryGetStackCountIncludingZero" in dispatcher,
        "MovementPush dead-stack gate must use TryGetStackCountIncludingZero (plain TryGetStackCount never returns 0)",
    )
    require(
        "target stack count already dead" in dispatcher,
        "MovementPush must CapLog when stacks are known zero",
    )
    require(
        "target stack count unavailable or already dead" not in dispatcher,
        "MovementPush must not reject on unavailable stack reads; only reject when stacks are known dead",
    )
    require(
        'string.IsNullOrWhiteSpace(abilityName)\n\t\t\t    || Homm3BattleEventNativeAdapter.IsAbilityNameMatch'
        not in dispatcher.replace("\r\n", "\n"),
        "bound MovementPush must not auto-commit when ability name is empty",
    )
    adapters_cs = read(plugin / "Homm3DirectStateAdapters.cs")
    symbols_cs = read(plugin / "GameSymbols.cs")
    neighbour_native_cs = read(plugin / "Homm3DirectStateHexNeighbourNative.cs")
    expected_neighbours = [
        "_cfqh_k__BackingField",
        "_cfqi_k__BackingField",
        "_cfqj_k__BackingField",
        "_cfqk_k__BackingField",
        "_cfql_k__BackingField",
        "_cfqm_k__BackingField",
    ]
    for name in expected_neighbours:
        require(
            f'"{name}"' in symbols_cs,
            f"HexNeighbourFieldMembers must pin live Hex.dll slot {name}",
        )
    neighbour_members_match = re.search(
        r"HexNeighbourFieldMembers\s*=\s*\{(.*?)\};",
        symbols_cs,
        flags=re.DOTALL,
    )
    require(neighbour_members_match is not None, "HexNeighbourFieldMembers block missing")
    neighbour_members_block = neighbour_members_match.group(1)
    require(
        "<cfnv>" not in neighbour_members_block and "cfnv" not in neighbour_members_block,
        "dump.cs Hex neighbour names must stay out of HexNeighbourFieldMembers",
    )
    require(
        "TryReadHexNeighbourFields" in adapters_cs
        and "Homm3DirectStateHexNeighbourNative.TryReadNeighbourSlots" in adapters_cs,
        "relative movement must resolve push destinations via Homm3DirectStateHexNeighbourNative",
    )
    require(
        "TryReadHexFieldOnly" not in adapters_cs,
        "managed GetField neighbour reads must stay deleted; use NativeFieldInfoPtr path",
    )
    require(
        "HexNeighbourFieldMembers" in symbols_cs and "HexNeighbourFieldMembers" in neighbour_native_cs,
        "push destination must use HexNeighbourFieldMembers through native reader",
    )
    require(
        "NativeFieldInfoPtr_" in neighbour_native_cs
        and "il2cpp_field_get_offset" in neighbour_native_cs,
        "neighbour reader must use NativeFieldInfoPtr + il2cpp_field_get_offset",
    )
    require(
        "Method_Public_get_Hex_" not in adapters_cs and "Method_Public_get_Hex_" not in neighbour_native_cs,
        "Hex neighbour getter Invoke must stay deleted from movement path (live AccessViolation)",
    )
    require(
        "private static IEnumerable<object> EnumerateHexNeighbours" not in adapters_cs,
        "EnumerateHexNeighbours helper must stay deleted (live AccessViolation)",
    )
    require(
        "TryInvokeBattleLogicHexAt" not in adapters_cs and "TryScanObjectForHexAt" not in adapters_cs,
        "board-wide hex scans must stay deleted; push uses neighbour field links only",
    )
    require(
        "Il2CppObjectPool" not in neighbour_native_cs,
        "neighbour Hex wrap must use IntPtr ctor only (no Il2CppObjectPool fallback)",
    )
    gateway_cs = read(plugin / "NativeCombatWriteGateway.cs")
    unit_hex_native = read(plugin / "Homm3DirectStateUnitHexNative.cs")
    require(
        "NativeHexIdentityEquals" in gateway_cs,
        "movement commit verification must compare Hex by native pointer/index, not ReferenceEquals alone",
    )
    require(
        'ReferenceEquals(committedHex, destinationHex)' not in gateway_cs,
        "movement publish check must not use ReferenceEquals on Il2Cpp Hex wrappers",
    )
    require(
        "Homm3DirectStateMovementPublish.TryPublishUnitPosChanged" in gateway_cs
        or "TryPublishUnitPosChanged" in read(plugin / "Homm3DirectStateMovementPublish.cs"),
        "movement commit must publish UnitPosChanged after hex write",
    )
    require(
        "MovementPositionChangedDispatch" in symbols_cs
        and "bcqv" in symbols_cs,
        "GameSymbols must keep MovementPositionChangedDispatch=bcqv for push presentation",
    )
    validate_destination = ""
    marker = "private static bool ValidateDestination"
    if marker in gateway_cs:
        validate_destination = gateway_cs.split(marker, 1)[1].split(
            "private static void LogPrepareHonestyOnce", 1
        )[0]
    require(
        "destination blocked state unavailable" in gateway_cs
        and "Hex.fieldObjects unavailable for occupancy gate" in gateway_cs
        and "destination hex is occupied (Hex.fieldObjects)" in gateway_cs
        and "HexOccupantMembers" not in validate_destination
        and "cfqf" not in validate_destination
        and "bcxo" not in validate_destination,
        "ValidateDestination must fail-closed on blocked flags + Hex.fieldObjects (never bcxo/HexOccupantMembers)",
    )
    require(
        "MovementPull unsupported" in adapters_cs,
        "MovementPull must CapLog unsupported until a free adjacent destination exists",
    )
    require(
        "(towardSource + 3)" not in adapters_cs and "(towardSource+3)" not in adapters_cs,
        "unproven ring opposite (i+3)%6 must stay deleted; push uses axial neighbour coords only",
    )
    require(
        "LogPrepareHonestyOnce" in gateway_cs and "manager-or-deferred-native" in gateway_cs,
        "PrepareAdapter no-op families must CapLog prepare honesty once",
    )
    neighbour_members_match = re.search(
        r"FieldObjectHexWriteMembers\s*=\s*\{(.*?)\};",
        symbols_cs,
        flags=re.DOTALL,
    )
    require(neighbour_members_match is not None, "FieldObjectHexWriteMembers block missing")
    require(
        "field_Private_Hex_0" in neighbour_members_match.group(1),
        "FieldObjectHexWriteMembers must pin field_Private_Hex_0",
    )
    require(
        "_hex_k__BackingField" not in neighbour_members_match.group(1),
        "stale FieldObject._hex_ write names must stay out of FieldObjectHexWriteMembers",
    )
    require(
        "il2cpp_gc_wbarrier_set_field" in unit_hex_native,
        "unit hex native writer must use il2cpp_gc_wbarrier_set_field",
    )
    require(
        "Method_Public_Void_Unit_Hex_0" not in gateway_cs
        or "TryMoveUnitHex" in gateway_cs,
        "gateway must not rely solely on BattleLogic Method_Public_Void_Unit_Hex_0",
    )

    for family in proof_families:
        require(
            family in handoff,
            f"handoff proof index missing direct-state family {family}",
        )
    require(
        "runtime-unvalidated" in handoff,
        "handoff must not promote unproven runtime behavior",
    )

    
    wave_map = manifest_json.get("ingressWaveMap")
    require(isinstance(wave_map, dict) and wave_map, "manifest ingressWaveMap is required")
    routed = set()
    for surface, adapter_ids in wave_map.items():
        require(isinstance(surface, str) and surface, "ingressWaveMap surface keys must be non-empty")
        require(isinstance(adapter_ids, list) and adapter_ids, f"ingressWaveMap[{surface}] must list adapters")
        for adapter_id in adapter_ids:
            require(adapter_id in contract_ids, f"ingressWaveMap routes unknown adapter {adapter_id}")
            routed.add(adapter_id)
    require(routed == set(contract_ids), "ingressWaveMap must route all 15 adapters")
    dispatcher = read(plugin / "Homm3DirectStateIngressDispatcher.cs")
    for token in (
        "DispatchTypedEventConstructed",
        "DispatchBattleEventSurface",
        "DispatchUnitInit",
        "DispatchDamageApplied",
    ):
        require(token in dispatcher, f"ingress dispatcher missing {token}")
    surface_ingress = read(plugin / "Homm3BattleEventNativeAdapter.SurfaceIngress.cs")
    for token in (
        "NormalizeCastCommitted",
        "NormalizeMovementCommitted",
        "NormalizeObjectSpawned",
        "NormalizeObjectDestroyed",
        "NormalizeRound",
        "NormalizeAction",
        "NormalizeUnitInit",
        "NormalizeBattleResult",
    ):
        require(token in surface_ingress, f"surface ingress missing {token}")

print("validated direct-state adapter invariants")


if __name__ == "__main__":
    main()
