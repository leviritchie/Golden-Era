#!/usr/bin/env python3
"""Validate ownership and hot-path contracts for direct-state combat mechanics."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


def fail(message: str) -> None:
    print(f"custom-combat-effect-framework-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.is_file():
        fail(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, context: str) -> None:
    if needle not in text:
        fail(f"{context} must contain {needle!r}")


def reject(text: str, needle: str, context: str) -> None:
    if needle in text:
        fail(f"{context} must not contain {needle!r}")


def method_body(source: str, name: str) -> str:
    match = re.search(
        r"(?:private|internal|public)\s+(?:static\s+)?[\w<>,\s\[\]?]+\s+"
        + re.escape(name)
        + r"\s*\(",
        source,
    )
    if not match:
        fail(f"missing method {name}")
    start = source.find("{", match.end())
    if start < 0:
        fail(f"missing body for method {name}")
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    fail(f"unterminated method {name}")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

    framework = read(plugin / "CustomCombatEffectFramework.cs")
    transaction = read(plugin / "BattleCombatTransactionManager.cs")
    gateway = read(plugin / "NativeCombatWriteGateway.cs")
    manifest = read(plugin / "Homm3DirectStateAdapterManifest.cs")
    adapters = read(plugin / "Homm3DirectStateAdapters.cs")
    hooks = read(plugin / "Homm3RuntimeMechanicHooks.cs")
    state = read(plugin / "Homm3BattleLocalLawState.RuntimeMechanics.cs")
    direct_state = read(plugin / "Homm3BattleLocalLawState.DirectState.cs")
    fixture = read(plugin / "Homm3RuntimeMechanicFixtureHarness.cs")
    owner_registry = read(plugin / "Homm3BattleUnitLawOwnerRegistry.cs")
    training = read(plugin / "Homm3TrainingDamageLawRuntime.cs")
    result_surface = read(plugin / "Homm3BattleResultSurface.cs")
    result_probe = read(plugin / "Homm3BattleResultSafeLawProbe.cs")
    event_adapter = read(plugin / "Homm3BattleEventNativeAdapter.cs")
    plugin_source = read(plugin / "Plugin.cs")
    project = read(plugin / "OfflineUnlockMod.csproj")
    handoff = read(root / "docs" / "runtime_mechanics_implementation_handoff.md")
    proof = read(root / "docs" / "custom_combat_effect_framework_decomp_proof_20260626.md")

    for token in (
        "internal readonly struct PreparedDamageMutation",
        "internal static class CustomCombatEffectManager",
        "TryPrepareDamageApplying",
        "Homm3DirectStateAdapterId.Damage",
    ):
        require(framework, token, "compiled definition dispatcher")
    reject(framework, "ICustomCombatEffect", "compiled definition dispatcher")
    reject(framework, "List<CombatTransformation>", "compiled definition dispatcher")
    reject(framework, "class CombatMutationApi", "dispatcher must not own write shim")

    for token in (
        "internal static class BattleCombatTransactionManager",
        "internal sealed class Homm3DirectStateTransaction",
        "Homm3DirectStateRootBudget",
        "RemainingWork",
        "RemainingJournal",
        "RemainingFanout",
        "TryEnqueueChild",
        "RollbackInternal",
        "ShouldInjectFailure",
        "Monitor.Enter",
        "Monitor.Exit",
    ):
        require(transaction, token, "transaction manager")
    reject(transaction, "Action rollback", "typed journal")
    reject(transaction, "Stack<Action>", "typed journal")

    for token in (
        "internal static class NativeCombatWriteGateway",
        "internal static class CombatMutationApi",
        "TryCommitPreparedDamage",
        "TryCommitUnitHexMove",
        "TryInitializeAndInsertObject",
        "TryInsertListItem",
        "TryReorderListItem",
        "TryInvokeDeferredDamage",
        "TryRestore(",
    ):
        require(gateway, token, "native write gateway")

    for token in (
        "internal enum Homm3DirectStateAdapterId",
        "internal enum Homm3DirectStateOperation",
        "internal enum Homm3DirectStateJournalOpcode",
        "ValidateExhaustive",
        "MaxRootWork",
        "MaxDepth",
        "MaxJournalEntries",
        "MaxFanout",
        "MaxDirtyIdentities",
        "MaxQueueSpan",
    ):
        require(manifest, token, "stable adapter manifest")

    for token in (
        "TryMutateFocus",
        "TryMutateCooldown",
        "TryApplyStatus",
        "TryMove",
        "TrySummon",
        "TryCreateTrap",
        "TryCreateCorpse",
        "TryEnqueueNestedDamage",
        "TryConfirmKill",
        "TryInsertAction",
        "TryReorderTurn",
        "TryDefineAura",
    ):
        require(adapters, token, "typed adapter executors")
    for forbidden in (
        ".SetValue(",
        ".RemoveAt(",
        ".Insert(",
        "ApplyDamageMethod.Invoke",
    ):
        reject(adapters, forbidden, "adapter native-write ownership")

    require(
        hooks,
        "private static bool PrefixDamageApplying(",
        "runtime mechanic hook",
    )
    require(
        hooks,
        "private static void PostfixDamageApplied(",
        "runtime mechanic hook",
    )
    for token in (
        "NativeCombatWriteGateway.TryPrepareAdapter",
        "RegisterTypedEventHooks",
        "PostfixTypedEventConstructed",
        "HashSet<MethodBase>",
        "Homm3RuntimeMechanicRegistry.PublishPreparedSnapshot()",
        "UnpatchTypedEventHooks",
        "PrefixBattleResultCleanup",
        "NormalizeDamageApplyInvocation",
        "DispatchDamageApplied",
        "TryEnqueueNestedDamageFromIngress",
    ):
        require(hooks, token, "sole runtime hook owner")
    reject(hooks, "TryApplyBellwetherPush", "Bellwether-named production symbols must be deleted")
    reject(hooks, "LogBellwetherReject", "Bellwether-named production symbols must be deleted")
    reject(hooks, "object[] __args", "runtime hot hook ownership")

    prefix = method_body(hooks, "PrefixDamageApplying")
    for forbidden in (
        "object[]",
        "new List<",
        "JObject",
        "File.",
        "GetField",
        ".Invoke(",
        "AccessTools",
    ):
        reject(prefix, forbidden, "typed damage prefix")
    require(prefix, "ref __3", "typed damage prefix")
    require(hooks, "out bool __state", "typed damage prefix")
    require(
        hooks,
        "var needsDamagePostfix = (requiredSurfaces & Homm3DirectStateHookSurface.DamageApplied) != 0;",
        "DamageApplied postfix must detect DamageApplied surface",
    )
    require(
        hooks,
        "var needsDamagePrefix = needsDamagePostfix",
        "DamageApplied postfix must always register the typed prefix so Harmony __state is initialized",
    )
    require(prefix, "TryInvokeRedirectedDamage", "pre-commit redirection")

    require(hooks, "Homm3DirectStateIngressOutcome", "named ingress outcome")
    require(hooks, "TryReadbackDamageSurfaceOwnership", "damage surface Harmony readback")
    dispatcher = read(plugin / "Homm3DirectStateIngressDispatcher.cs")
    require(dispatcher, "CapLogOutcome", "capped reject/fail diagnostics")
    require(dispatcher, "TryRouteMovementPush", "generic MovementPush routing")


    require(state, "RuntimeTransactionSyncRoot", "shared battle transaction lock")
    require(
        state,
        "BattleCombatTransactionManager.TryBegin(",
        "damage transaction routing",
    )
    require(
        state,
        "NativeCombatWriteGateway.TryCommitPreparedDamage",
        "sole committed-damage write route",
    )
    require(state, "ClearDirectStateLedgersLocked", "generation cleanup")

    for token in (
        "private sealed class DirectStateLedger",
        "DirectStatusSnapshot",
        "DirectCorpseSnapshot",
        "DirectTrapSnapshot",
        "TryClaimDirectEventToken",
        "CompleteDirectEventToken",
        "SnapshotDirectStateJson",
    ):
        require(direct_state, token, "generation-owned direct state")

    for token in (
        "TryValidateSourceFixtures",
        "FaultInjectionFlag",
        "RecordDistinctHookCount",
        "RecordDirtyHex",
        "SnapshotJson",
    ):
        require(fixture, token, "shared fixture harness")

    for token in (
        "CastAbilityEventInfo",
        "MovementEventInfo",
        "DamageEventInfo",
        "DestroyedEventInfo",
        "SpawnedEventInfo",
        "RoundEventInfo",
        "ActionEventInfo",
        "TryGetTypedEventType",
    ):
        require(event_adapter, token, "typed event contexts")

    require(
        owner_registry,
        "Homm3RuntimeMechanicRegistry.HasPreparedMechanics",
        "shared Init registration gate",
    )
    require(
        owner_registry,
        "Homm3BattleLocalLawState.BindRuntimeMechanics",
        "shared Init sparse binding",
    )
    reject(
        training,
        "CustomCombatEffectManager.TryPrepareDamageApplying",
        "dormant training runtime",
    )
    require(
        result_probe,
        "Homm3BattleResultSurface.ResolveApplyBattleResultMethod()",
        "diagnostic result probe",
    )
    reject(
        result_probe,
        "Homm3BattleUnitLawOwnerRegistry.Clear(",
        "diagnostic result probe",
    )
    require(
        result_surface,
        "TryReadBattleResultAlreadyApplied",
        "native duplicate-result guard",
    )

    require(
        plugin_source,
        "Homm3RuntimeMechanicRegistry.PrepareFromDirectory(",
        "plugin startup",
    )
    require(
        plugin_source,
        "Homm3RuntimeMechanicHooks.TryRegister(_harmony, Log);",
        "plugin startup",
    )
    reject(
        plugin_source,
        "Homm3TrainingDamageLawRuntime.TryRegister(",
        "plugin startup sole committed-damage owner",
    )
    require(project, "ValidateCustomCombatEffectFrameworkContract", "MSBuild target")
    require(handoff, "Runtime-mechanics ownership matrix", "runtime handoff")
    require(handoff, "runtime-unvalidated", "runtime handoff proof boundary")
    require(
        proof,
        "runtime_mechanics_implementation_handoff.md",
        "combat framework provenance",
    )

    print("validated direct-state custom combat effect framework")


if __name__ == "__main__":
    main()
