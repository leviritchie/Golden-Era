#!/usr/bin/env python3
"""Validate the source-static Bulwark Jotunn Frostbound Skies flyer Slow runtime contract."""

from __future__ import annotations

import argparse
from pathlib import Path


def read(path: Path) -> str:
	if not path.is_file():
		raise SystemExit(f"missing required file: {path}")
	return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, label: str) -> None:
	if needle not in text:
		raise SystemExit(f"missing {label}: {needle}")


def reject(text: str, needle: str, label: str) -> None:
	if needle in text:
		raise SystemExit(f"rejected {label}: {needle}")


def require_order(text: str, needles: tuple[str, ...], label: str) -> None:
	positions = [text.find(needle) for needle in needles]
	if any(position < 0 for position in positions) or positions != sorted(positions):
		raise SystemExit(f"invalid {label} ordering: {needles}")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	args = parser.parse_args()
	root = args.repo_root.resolve()
	plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

	runtime = read(plugin_dir / "Homm3BulwarkUnitAbilityRuntime.cs")
	unit_init_registry = read(plugin_dir / "Homm3BattleUnitLawOwnerRegistry.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")
	symbols = read(plugin_dir / "GameSymbols.cs")
	overlay = read(root / "tools" / "release_port" / "apply_release_core_overlay.py")

	require(runtime, 'FlyerSlowBuffSidBase = "homm3_bulwark_frostbound_skies_speed_1"', "base Frostbound Skies speed buff")
	require(runtime, 'FlyerSlowBuffSidWarlord = "homm3_bulwark_frostbound_skies_speed_2"', "Warlord Frostbound Skies speed buff")
	require(runtime, '"h3_jotunn"', "base Jotunn SID")
	require(runtime, '"h3_jotunn_warlord"', "Warlord Jotunn SID")
	require(runtime, '"h3_jotunn_upg_alt"', "alternate Jotunn upgrade SID")
	require(runtime, "FlyerSlowValueBase = 1", "base flyer Slow magnitude")
	require(runtime, "FlyerSlowValueWarlord = 2", "Warlord flyer Slow magnitude")
	require(runtime, "GameSymbols.BattleEventLaws.UnitConfigFlyMoveTypeValue", "centralized fly moveType value")
	require(runtime, "GameSymbols.BattleEventLaws.UnitConfigStatsMoveTypeMembers", "centralized moveType members")
	require(runtime, "GameSymbols.BattleEventLaws.UnitLogicConfigMembers", "centralized unit logic config members")
	require(runtime, "Homm3DirectStateIdentity.TryResolveKey(unit", "native-pointer apply dedupe")
	require(runtime, "HashSet<long> SlowAppliedUnitKeys", "native-pointer SlowAppliedUnitKeys")
	require(runtime, "GameSymbols.DraconicDominion.BattleLogicTypeHints", "centralized BattleLogic type symbol")
	require(runtime, "GameSymbols.DraconicDominion.BattleLogicInit", "centralized BattleLogic.Init symbol")
	register_start = runtime.index("internal static void TryRegister(")
	register_end = runtime.index("\n\tprivate static void PrefixBattleLogicInit", register_start)
	registration = runtime[register_start:register_end]
	require(registration, "PatchPrefix(harmony, battleLogicInitMethod", "BattleLogic.Init prefix")
	require(registration, "PatchPostfix(harmony, battleLogicInitMethod", "BattleLogic.Init postfix")
	require(runtime, "TryRegisterUnitInitConsumer(", "Bulwark Unit.Init consumer registration")
	require(runtime, '"homm3.bulwark.unitAbility"', "stable Bulwark Unit.Init consumer owner")
	if registration.count("PatchPrefix(harmony,") != 1 or registration.count("PatchPostfix(harmony,") != 1:
		raise SystemExit("Bulwark registration must patch only the pinned BattleLogic.Init prefix/postfix")
	if runtime.count("harmony.Patch(") != 2:
		raise SystemExit("Bulwark runtime must keep both Harmony patch writes in the two pinned BattleLogic helpers")
	reject(runtime, "FindUnitInitMethod(", "separate Bulwark Unit.Init target resolution")
	require_order(
		registration,
		(
			"TryRegisterSharedUnitInit(harmony, _log)",
			"PatchPrefix(harmony, battleLogicInitMethod",
			"PatchPostfix(harmony, battleLogicInitMethod",
			"registrationSummary = \"HoMM3 Bulwark unit-ability runtime registered on \"",
			"TryRegisterUnitInitConsumer(",
			"_registered = true;",
		),
		"Bulwark shared Unit.Init registration",
	)
	catch_start = registration.index("catch (Exception ex)")
	catch_end = registration.index("\n\t\tif (_registered)", catch_start)
	catch_block = registration[catch_start:catch_end]
	require_order(
		catch_block,
		(
			"_registered = false;",
			"UnpatchOwned(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit))",
			"UnpatchOwned(harmony, battleLogicInitMethod, nameof(PostfixBattleLogicInit))",
		),
		"Bulwark failed-registration rollback",
	)
	prefix_start = runtime.index("private static void PrefixBattleLogicInit")
	postfix_start = runtime.index("private static void PostfixBattleLogicInit", prefix_start)
	shared_start = runtime.index("private static void OnSharedUnitInit", postfix_start)
	require_order(
		runtime[prefix_start:postfix_start],
		("if (!_registered)", "ClearPlans("),
		"Bulwark inactive prefix guard",
	)
	require_order(
		runtime[postfix_start:shared_start],
		("if (!_registered)", "ApplyPlannedFlyerSlowToRegisteredUnits("),
		"Bulwark inactive postfix guard",
	)
	prefix_helper_start = runtime.index("private static void PatchPrefix(")
	postfix_helper_start = runtime.index("private static void PatchPostfix(", prefix_helper_start)
	postfix_helper_end = runtime.index("\n\tprivate static", postfix_helper_start)
	require(runtime[prefix_helper_start:postfix_helper_start], "harmony.Patch(target, prefix: new HarmonyMethod(prefix));", "Bulwark prefix patch target remains explicit")
	require(runtime[postfix_helper_start:postfix_helper_end], "harmony.Patch(target, postfix: new HarmonyMethod(postfix));", "Bulwark postfix patch target remains explicit")
	require(runtime, "harmony.Unpatch(target, patch);", "Bulwark rollback removes only its exact BattleLogic patch methods")
	on_shared_start = runtime.index("private static void OnSharedUnitInit")
	on_shared_end = runtime.index("\n\tprivate static", on_shared_start)
	on_shared = runtime[on_shared_start:on_shared_end]
	require(on_shared, "if (_registered)", "Bulwark consumer stays inactive unless runtime registration succeeds")
	require(on_shared, "PostfixUnitInit(unit, args)", "Bulwark shared consumer preserves existing Unit.Init apply")
	api_start = unit_init_registry.index("internal static bool TryRegisterUnitInitConsumer(")
	api_end = unit_init_registry.index("\n\tinternal static void Clear", api_start)
	consumer_api = unit_init_registry[api_start:api_end]
	dispatch_start = unit_init_registry.index("private static void DispatchUnitInitConsumers")
	dispatch_end = unit_init_registry.index("\n\tprivate static bool IsRegistryRequired", dispatch_start)
	dispatch = unit_init_registry[dispatch_start:dispatch_end]
	require_order(
		consumer_api,
		(
			"if (!_registered)",
			"UnitInitConsumersByOwner.TryGetValue(owner, out var existing)",
			"if (existing.Handler == handler)",
			"UnitInitConsumersByOwner.Add(owner, consumer);",
			"Volatile.Write(ref _unitInitConsumers, next)",
		),
		"Bulwark consumer fail-closed, idempotence, and publication",
	)
	require(consumer_api, "shared Unit.Init owner is not registered", "consumer registration fails closed without the shared owner")
	require(consumer_api, "already registered with a different handler", "same-owner conflicting callback fails closed")
	require(dispatch, "Volatile.Read(ref _unitInitConsumers)", "allocation-free Unit.Init dispatch snapshot read")
	require(dispatch, "consumer.Handler(unit, args)", "central Unit.Init consumer dispatch")
	require(dispatch, "shared Unit.Init consumer failed closed: owner=", "consumer dispatch retains owner diagnostics")
	reject(dispatch, ".ToArray()", "per-Unit.Init consumer snapshot allocation")
	postfix_start = unit_init_registry.index("private static void PostfixUnitInit")
	consumer_dispatch = unit_init_registry.index("private static void DispatchUnitInitConsumers", postfix_start)
	postfix = unit_init_registry[postfix_start:consumer_dispatch]
	require_order(
		postfix,
		(
			"UnitKeyToUnit[key] = __instance;",
			"Homm3DirectStateIngressDispatcher.DispatchUnitInit(__instance, battleSide);",
			"DispatchUnitInitConsumers(__instance, __args);",
		),
		"registry capture and ordered shared consumer dispatch",
	)
	require_order(
		postfix,
		("UnitToTransferSide[key] = battleSide;", "unitRecorded = true;", "Homm3DirectStateIngressDispatcher.DispatchUnitInit(__instance, battleSide);", "if (unitRecorded)", "DispatchUnitInitConsumers(__instance, __args);"),
		"Bulwark consumer dispatch follows registry capture and Direct State ingress",
	)
	require(postfix, "finally\n\t\t{\n\t\t\tif (unitRecorded)\n\t\t\t\tDispatchUnitInitConsumers(__instance, __args);", "Bulwark consumer dispatch survives Direct State failures after unit capture")
	if postfix.count("DispatchUnitInitConsumers(__instance, __args);") != 1:
		raise SystemExit("Bulwark Unit.Init consumer dispatch must occur exactly once")
	require(runtime, "TryResolveTransferSideFromUnitInitArg(", "Unit.Init TransferSide bridge from eir")
	require(runtime, "BattleSideTransferSideMembers", "centralized eir->TransferSide members")
	require(runtime, "unit init plan miss:", "fail-closed Bulwark plan-miss diagnostic")
	require(runtime, "unit init while plans empty:", "fail-closed empty-plan Unit.Init diagnostic")
	require(runtime, "unit init TransferSide resolve failed while plans active:", "fail-closed bridge-miss diagnostic")
	require(runtime, "ApplyPlannedFlyerSlowToRegisteredUnits(", "BattleLogic.Init postfix SnapshotUnits apply")
	require(runtime, "TryRegisterSharedUnitInit(", "shared Unit.Init registry required for SnapshotUnits")
	require(runtime, 'ApplyPlannedFlyerSlowToRegisteredUnits("battle-logic-init-postfix")', "postfix registry apply stage call")
	require(runtime, "Combat unproven", "runtime-unvalidated proof boundary")
	require(runtime, "Frostbound Skies flyer Slow", "applied flyer Slow success log")
	reject(runtime, "magic_nairas_kiss_slow_effect", "retired Naira Kiss Initiative+Speed buff")
	reject(runtime, 'new[] { "isFlyer", "IsFlyer", "flyer", "Flyer" }', "readable isFlyer name probe")
	reject(runtime, "RuntimeHelpers.GetHashCode(unit)", "managed hash apply dedupe")
	reject(runtime, 'ClearPlans("battle-logic-init-postfix")', "retired Init-postfix plan clear that raced Unit.Init")
	reject(runtime, "GetHashCode(__args[2])", "unbridged Unit.Init arg[2] as TransferSide plan key")

	require(symbols, 'UnitConfigFlyMoveTypeValue = "fly"', "GameSymbols fly moveType constant")
	require(symbols, "UnitConfigStatsMoveTypeMembers", "GameSymbols moveType members")
	require(overlay, "make_homm3_bulwark_frostbound_skies_buff_rows", "overlay Frostbound Skies buff generator")
	require(overlay, '"speed": -magnitude', "speed-only Frostbound Skies buff payload")

	require(plugin, "Homm3BulwarkUnitAbilityRuntime.TryRegister(_harmony, Log);", "plugin registration")
	require(project, "ValidateHomm3BulwarkFlyerSlowRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_bulwark_flyer_slow_runtime_contract.py", "MSBuild validator path")

	print("validated HoMM3 Bulwark flyer Slow source-static runtime contract")


if __name__ == "__main__":
	main()
