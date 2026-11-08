#!/usr/bin/env python3
"""Validate the source-static Factory Split Assembly runtime contract."""

from __future__ import annotations

import argparse
import re
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

	runtime = read(plugin_dir / "Homm3FactorySplitAssemblyRuntime.cs")
	unit_init_registry = read(plugin_dir / "Homm3BattleUnitLawOwnerRegistry.cs")
	conflict_audit = read(plugin_dir / "Homm3DirectStateConflictAudit.cs")
	evaluator = read(plugin_dir / "Homm3FactorySplitAssemblyEvaluator.cs")
	adapter = read(plugin_dir / "Homm3BuffDebuffNativeAdapter.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")

	require(evaluator, 'FactorySkillSid = "skill_faction_homm3_factory"', "Factory faction-skill SID")
	require(evaluator, 'NaturalOverclockSubSkillSid = "sub_skill_faction_homm3_factory_gantry_reserve"', "Natural Overclock subskill SID")
	require(evaluator, 'IndustrialOverclockSubSkillSid = "sub_skill_faction_homm3_factory_industrial_tempo"', "Industrial Overclock subskill SID")
	require(evaluator, "ResolveUnlockedTiers(", "tier unlock helper")
	require(evaluator, "Homm3CustomFactionRegistry.TryGetManifestUnitBranch(", "manifest-owned unit branch lookup")
	require(evaluator, 'string.Equals(branchFamily, NaturalBranch, StringComparison.Ordinal)', "exact Natural branch classification")
	require(evaluator, 'string.Equals(branchFamily, IndustrialBranch, StringComparison.Ordinal)', "exact Industrial branch classification")
	require(evaluator, "naturalLines.Add(baseSid)", "distinct Natural base-line count")
	require(evaluator, "industrialLines.Add(baseSid)", "distinct Industrial base-line count")
	require(runtime, "Homm3FactorySplitAssemblyEvaluator.TryEvaluate(", "combat path uses shared evaluator")
	require(runtime, "CollectTransferSideUnitSids(", "battle TransferSide SID enumeration")
	require(runtime, 'CarapaceBuffSid = "magic_carapace_effect"', "native Carapace buff SID")
	require(runtime, "rank < 1 || rank > 3", "fail-closed rank range")
	require(runtime, "GameSymbols.DraconicDominion.BattleLogicTypeHints", "centralized BattleLogic type symbol")
	require(runtime, "GameSymbols.DraconicDominion.BattleLogicInit", "centralized BattleLogic.Init symbol")
	require(runtime, "GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter", "centralized LogicHero data-Hero getter")
	require(runtime, "GameSymbols.DraconicDominion.DataHeroSkillsMembers", "centralized data-Hero skills members")
	require(runtime, "GameSymbols.DraconicDominion.HeroSkillsListMembers", "centralized HeroSkills list members")
	require(runtime, "GameSymbols.DraconicDominion.HeroSkillSidMembers", "centralized HeroSkill SID members")
	require(runtime, "GameSymbols.DraconicDominion.HeroSkillLevelMembers", "centralized HeroSkill rank members")
	require(runtime, "GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers", "centralized HeroSkill subSkills members")
	require(runtime, 'BuffSid("ranged", magnitude)', "Natural ranged buff SID")
	require(runtime, 'BuffSid("mitigation", magnitude)', "Natural mitigation buff SID")
	require(runtime, 'BuffSid("melee", magnitude)', "Industrial melee buff SID")
	require(runtime, 'BuffSid("speed", magnitude)', "Industrial speed buff SID")
	require(runtime, 'BuffSid("initiative", magnitude)', "Industrial initiative buff SID")
	require(runtime, 'FieldTriageAbilitySid = "skill_faction_homm3_factory_ability_field_triage"', "Field Triage ability SID")
	require(runtime, "ApplyFieldTriageChargeLocks(", "Field Triage Expert+4-line charge gate")
	require(runtime, "FieldTriageUnlockedSideIndexes", "Field Triage unlock tracking by side index")
	require(runtime, "FocusGrantedSideIndexes", "Focus grant tracking by side index")
	require(runtime, "plan.IndustrialTier >= 4", "Industrial tier-4 unlock condition")
	require(runtime, 'TrySetIntMember(ability, "charges", unlocked ? -1 : 0)', "Field Triage charge lock")
	require(runtime, "Homm3FocusNativeAdapter.TryGrantFocusToSide(", "Natural tier-3 Focus grant")
	require(runtime, "Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(", "native buff apply")
	require(adapter, "TryApplyBuffConfigStatsAdditive(", "post-add BuffConfig.data.stats additive fold onto Unit.get_stats")
	require(adapter, 'set_" + field', "UnitStat set_* additive fold")
	overlay = read(root / "tools" / "release_port" / "apply_release_core_overlay.py")
	# Split Assembly Core rows must be battle-long like Bulwark Runes (infinite + addition=data).
	sa_start = overlay.index("def make_homm3_factory_split_assembly_buff_rows()")
	sa_end = overlay.index("\ndef make_homm3_factory_field_triage_hero_ability()")
	sa_block = overlay[sa_start:sa_end]
	require(sa_block, '"infinite": True', "Split Assembly buff rows are infinite")
	require(sa_block, '"addition": "data"', "Split Assembly buff rows use addition=data")
	reject(sa_block, '"addition": "duration"', "Split Assembly must not use addition=duration (live-neg: immediate decay)")
	# Combat buff tooltips resolve name_/description_ from magic_buff / unitsBuff.
	require(
		overlay,
		'factory_combat_buff_lang_rows = [',
		"Factory Split Assembly combat buff LOC rows",
	)
	require(
		overlay,
		'for lang_path in ("Lang/english/texts/magic_buff.json", "Lang/english/texts/unitsBuff.json"):\n            add_lang_overlay_rows(\n                release_zip,\n                output,\n                lang_path,\n                factory_combat_buff_lang_rows,',
		"Split Assembly buff LOC wired into magic_buff + unitsBuff",
	)
	require(overlay, '"sid": "homm3_factory_split_assembly_speed_1_name"', "Factory Drive name LOC SID")
	require(overlay, '"sid": "homm3_factory_split_assembly_speed_1_desc"', "Factory Drive desc LOC SID")
	# Multilingual scrub must keep Split Assembly tooltip SIDs in combat catalogs
	# (not only fractions.json), or a later sync drops magic_buff / unitsBuff rows.
	ml = read(root / "tools" / "release_port" / "multilingual_custom_lang.py")
	require(ml, '"_split_assembly_" in sid', "multilingual canonical keeps Split Assembly SIDs")
	require(
		ml,
		'return {"magic_buff.json", "unitsBuff.json", "heroSkills.json"}',
		"Split Assembly LOC canonical files include magic_buff + unitsBuff",
	)
	pb_path = root / "tools" / "release_port" / "localization_phrasebooks" / "factory_split_assembly_combat_buffs.json"
	if not pb_path.is_file():
		raise SystemExit(f"missing Factory Split Assembly combat buff phrasebook: {pb_path}")
	pb = read(pb_path)
	require(pb, '"english": "Factory Drive"', "phrasebook Factory Drive")
	require(pb, '"russian": "Заводской привод"', "phrasebook Russian Factory Drive")
	register_start = runtime.index("internal static void TryRegister(")
	register_end = runtime.index("\n\tprivate static void PrefixBattleLogicInit", register_start)
	registration = runtime[register_start:register_end]
	require(registration, "PatchPrefix(harmony, battleLogicInitMethod", "BattleLogic.Init prefix")
	require(registration, "PatchPostfix(harmony, battleLogicInitMethod", "BattleLogic.Init postfix")
	require(runtime, "TryRegisterSharedUnitInit(harmony, _log)", "shared Unit.Init owner registration")
	require(runtime, "TryRegisterUnitInitConsumer(", "Factory Unit.Init consumer registration")
	require(runtime, '"homm3.factory.splitAssembly"', "stable Factory Unit.Init consumer owner")
	if registration.count("PatchPrefix(harmony,") != 1 or registration.count("PatchPostfix(harmony,") != 1:
		raise SystemExit("Factory registration must patch only the pinned BattleLogic.Init prefix/postfix")
	if runtime.count("harmony.Patch(") != 2:
		raise SystemExit("Factory runtime must keep both Harmony patch writes in the two pinned BattleLogic helpers")
	reject(runtime, "FindUnitInitMethod(", "separate Factory Unit.Init target resolution")
	require_order(
		registration,
		(
			"TryRegisterSharedUnitInit(harmony, _log)",
			"PatchPrefix(harmony, battleLogicInitMethod",
			"PatchPostfix(harmony, battleLogicInitMethod",
			"registrationSummary = \"HoMM3 Factory Split Assembly runtime registered on \"",
			"TryRegisterUnitInitConsumer(",
			"_registered = true;",
		),
		"Factory shared Unit.Init registration",
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
		"Factory failed-registration rollback",
	)
	prefix_start = runtime.index("private static void PrefixBattleLogicInit")
	postfix_start = runtime.index("private static void PostfixBattleLogicInit", prefix_start)
	shared_start = runtime.index("private static void OnSharedUnitInit", postfix_start)
	require_order(
		runtime[prefix_start:postfix_start],
		("if (!_registered)", "ClearPlans("),
		"Factory inactive prefix guard",
	)
	require_order(
		runtime[postfix_start:shared_start],
		("if (!_registered)", "GrantPendingFocus("),
		"Factory inactive postfix guard",
	)
	prefix_helper_start = runtime.index("private static void PatchPrefix(")
	postfix_helper_start = runtime.index("private static void PatchPostfix(", prefix_helper_start)
	postfix_helper_end = runtime.index("\n\tprivate static", postfix_helper_start)
	require(runtime[prefix_helper_start:postfix_helper_start], "harmony.Patch(target, prefix: new HarmonyMethod(prefix));", "Factory prefix patch target remains explicit")
	require(runtime[postfix_helper_start:postfix_helper_end], "harmony.Patch(target, postfix: new HarmonyMethod(postfix));", "Factory postfix patch target remains explicit")
	require(runtime, "harmony.Unpatch(target, patch);", "Factory rollback removes only its exact BattleLogic patch methods")
	on_shared_start = runtime.index("private static void OnSharedUnitInit")
	on_shared_end = runtime.index("\n\tprivate static", on_shared_start)
	on_shared = runtime[on_shared_start:on_shared_end]
	require(on_shared, "if (_registered)", "Factory consumer stays inactive unless runtime registration succeeds")
	require(on_shared, "PostfixUnitInit(unit, args)", "Factory shared consumer preserves existing Unit.Init apply")

	postfix_start = unit_init_registry.index("private static void PostfixUnitInit")
	consumer_dispatch = unit_init_registry.index("private static void DispatchUnitInitConsumers", postfix_start)
	postfix = unit_init_registry[postfix_start:consumer_dispatch]
	api_start = unit_init_registry.index("internal static bool TryRegisterUnitInitConsumer(")
	api_end = unit_init_registry.index("\n\tinternal static void Clear", api_start)
	consumer_api = unit_init_registry[api_start:api_end]
	dispatch_start = unit_init_registry.index("private static void DispatchUnitInitConsumers")
	dispatch_end = unit_init_registry.index("\n\tprivate static bool IsRegistryRequired", dispatch_start)
	dispatch = unit_init_registry[dispatch_start:dispatch_end]
	require(consumer_api, "UnitInitConsumersByOwner", "idempotent named Unit.Init owners")
	require_order(
		consumer_api,
		(
			"string.IsNullOrWhiteSpace(owner)",
			"if (!_registered)",
			"UnitInitConsumersByOwner.TryGetValue(owner, out var existing)",
			"if (existing.Handler == handler)",
			"var consumer = new UnitInitConsumer(owner, handler);",
			"UnitInitConsumersByOwner.Add(owner, consumer);",
			"Volatile.Write(ref _unitInitConsumers, next)",
		),
		"Unit.Init consumer validation, idempotence, and publication",
	)
	require(consumer_api, "shared Unit.Init owner is not registered", "consumer registration fails closed without the shared owner")
	require(consumer_api, "already registered with a different handler", "same-owner conflicting callback fails closed")
	require(dispatch, "Volatile.Read(ref _unitInitConsumers)", "allocation-free Unit.Init dispatch snapshot read")
	require(dispatch, "consumer.Handler(unit, args)", "central Unit.Init consumer dispatch")
	require(dispatch, "shared Unit.Init consumer failed closed: owner=", "consumer dispatch retains owner diagnostics")
	reject(dispatch, ".ToArray()", "per-Unit.Init consumer snapshot allocation")
	require(unit_init_registry, "next[current.Length] = consumer;", "consumer registration preserves deterministic append order")
	require_order(
		postfix,
		(
			"UnitKeyToUnit[key] = __instance;",
			"Homm3DirectStateIngressDispatcher.DispatchUnitInit(__instance, battleSide);",
			"DispatchUnitInitConsumers(__instance, __args);",
		),
		"Unit.Init registry capture, Direct State ingress, and consumer dispatch",
	)
	require_order(
		postfix,
		("UnitToTransferSide[key] = battleSide;", "unitRecorded = true;", "Homm3DirectStateIngressDispatcher.DispatchUnitInit(__instance, battleSide);", "if (unitRecorded)", "DispatchUnitInitConsumers(__instance, __args);"),
		"Factory consumer dispatch follows registry capture and Direct State ingress",
	)
	require(postfix, "finally\n\t\t{\n\t\t\tif (unitRecorded)\n\t\t\t\tDispatchUnitInitConsumers(__instance, __args);", "Factory consumer dispatch survives Direct State failures after unit capture")
	if postfix.count("DispatchUnitInitConsumers(__instance, __args);") != 1:
		raise SystemExit("Factory Unit.Init consumer dispatch must occur exactly once")
	require(conflict_audit, "declaringType == typeof(Homm3RuntimeMechanicHooks)", "shared owner audit exemption")
	require(conflict_audit, "declaringType == typeof(Homm3BattleUnitLawOwnerRegistry)", "registry owner audit exemption")
	reject(conflict_audit, "Homm3FactorySplitAssemblyRuntime", "Factory competing-patch audit exemption")
	reject(conflict_audit, "Homm3BulwarkUnitAbilityRuntime", "Bulwark competing-patch audit exemption")
	require_order(
		plugin,
		(
			"Homm3FactorySplitAssemblyRuntime.TryRegister(_harmony, Log);",
			"Homm3BulwarkUnitAbilityRuntime.TryRegister(_harmony, Log);",
		),
		"Factory and Bulwark consumer registration",
	)

	# Producer/consumer: battle-local side-index join (live-negative TransferSide ptr).
	require(runtime, "Dictionary<int, SideAssemblyPlan> PlansBySideIndex", "side-index plan map")
	require(runtime, "for (var sideIndex = 0; sideIndex < sides.Length; sideIndex++)", "BuildPlans iterates sides by index")
	require(runtime, "PlansBySideIndex[sideIndex] = plan", "BuildPlans stores by side index")
	require(runtime, "TryResolveBattleLocalSideIndex(", "Unit.Init battle-local side-index resolve")
	require(
		runtime,
		"GameSymbols.BattleEventLaws.BattleSideWrapperLocalSideIndexMembers",
		"centralized wrapper local side-index members",
	)
	require(runtime, "PlansBySideIndex.TryGetValue(sideIndex, out plan)", "Unit.Init plan lookup by side index")
	require(runtime, "ApplyUnitBonuses(__instance, plan, sideIndex)", "Unit.Init direct apply to __instance")
	require(runtime, "sideIndex=", "sideIndex log field on plan/apply path")
	require(runtime, "unit init plan miss:", "fail-closed Factory plan-miss diagnostic")
	require(runtime, "unit init while plans empty:", "fail-closed empty-plan Unit.Init diagnostic")
	require(runtime, "unit init side-index resolve failed while plans active:", "fail-closed side-index miss diagnostic")
	reject(runtime, 'ClearPlans("battle-logic-init-postfix")', "retired Init-postfix plan clear that raced Unit.Init")

	# Retired TransferSide identity join + SnapshotUnits fallback.
	reject(runtime, "PlansByTransferSideKey", "retired TransferSide identity plan map")
	reject(runtime, "TryResolveTransferSideFromUnitInitArg(", "retired Unit.Init TransferSide bridge")
	reject(runtime, "TryResolveTransferSidePlanKey(", "retired TransferSide pointer plan key")
	reject(runtime, "ApplyPlannedBuffsToRegisteredUnits(", "retired SnapshotUnits postfix buff apply")
	reject(runtime, "SnapshotUnits(", "retired SnapshotUnits fallback (stale across Inits)")
	reject(runtime, "Homm3DirectStateIdentity.TryResolveKey(transferSide", "retired TransferSide native-pointer plan key")
	reject(runtime, "transferSideNativeKey=", "retired TransferSide native-key log field")
	reject(runtime, "FocusGrantedSideKeys", "retired TransferSide-keyed Focus set")
	reject(runtime, "FieldTriageUnlockedSideKeys", "retired TransferSide-keyed Field Triage set")
	reject(runtime, "BattleSideTransferSideMembers", "retired eir->TransferSide plan bridge")

	require(runtime, "gameplay remains runtime-unvalidated", "runtime-unvalidated proof boundary")
	require(runtime, "unitSid=", "Phase 0 applied-buff unitSid log field")
	require(runtime, "buffSids=[", "Phase 0 applied-buff SID list log field")
	require(runtime, "verified=", "Phase 0 applied-buff verified log field")
	require(runtime, "Homm3BuffDebuffNativeAdapter.TryRequireBuffSidFromReceiver(", "verified= uses HasBySid read API")
	require(runtime, "_loggedUnitApplications++ < 48", "unit apply log cap unchanged")
	require(runtime, "HashSet<long> BuffAppliedUnitKeys", "native-pointer BuffAppliedUnitKeys")
	require(runtime, "Homm3DirectStateIdentity.TryResolveKey(unit", "native-pointer unit apply dedupe")
	reject(runtime, "RuntimeHelpers.GetHashCode(unit)", "managed hash unit apply dedupe")
	reject(runtime, "HashSet<int> BuffAppliedUnitKeys", "managed-int BuffAppliedUnitKeys")
	require(
		runtime,
		"Core skill/buff rows are data only",
		"explicit Harmony ownership (no native Split Assembly mechanic)",
	)
	require(
		runtime,
		"do NOT key plans by",
		"explicit rejection of TransferSide object-identity join",
	)
	require(
		runtime,
		"no SnapshotUnits",
		"explicit rejection of SnapshotUnits fallback",
	)
	require(
		runtime,
		"folds BuffConfig.data.stats",
		"buff->effective-stat adapter fold ownership",
	)
	require(
		runtime,
		"live-probe-proven for speed mid-combat",
		"buff->effective-stat proof boundary",
	)

	force_setup = read(plugin_dir / "Homm3FactoryBulwarkCombatForceSetupPilot.cs")
	require(force_setup, 'PilotFlag = "homm3_factory_bulwark_combat_force_setup_pilot.flag"', "shared force-setup pilot flag")
	require(force_setup, 'ConfigFileName = "homm3_factory_bulwark_combat_force_setup.json"', "shared force-setup config name")
	require(force_setup, "Homm3DiagnosticFlags.IsEnabled(PilotFlag)", "force-setup flag gate")
	require(force_setup, "priority = Priority.First", "force-setup runs before Split Assembly plan build")
	# Forgotten flag / fixture mismatch must not abort BattleLogic.Init (map Loader NRE).
	require(force_setup, "skipping apply", "force-setup soft-skips zero TransferSide matches")
	require(force_setup, "will not abort Init", "force-setup prefix never rethrows into Init")
	reject(force_setup, "failed closed during battle init", "retired force-setup Init rethrow path")
	require(plugin, "Homm3FactoryBulwarkCombatForceSetupPilot.TryRegister(_harmony, Log);", "force-setup plugin registration")
	example = plugin_dir / "homm3_factory_bulwark_combat_force_setup.example.json"
	if not example.is_file():
		raise SystemExit("missing force-setup example config: " + str(example))
	# Pilot must stay off by default: no armed flag or live config in the plugin tree.
	if (plugin_dir / "homm3_factory_bulwark_combat_force_setup_pilot.flag").is_file():
		raise SystemExit("force-setup pilot flag must not ship armed in the plugin tree")
	if (plugin_dir / "homm3_factory_bulwark_combat_force_setup.json").is_file():
		raise SystemExit("force-setup live config must not ship in the plugin tree; keep example only")

	reject(runtime, "UnitLinesBySid", "duplicate unit-line source of truth")
	reject(runtime, 'new UnitLine("', "hard-coded unit-line classification")
	reject(runtime, ".stacks", "raw split-stack counting")
	reject(runtime, "Math.Max(1", "invalid-rank coercion")
	reject(runtime, "BranchCapsByRank", "retired rank line caps")
	reject(runtime, 'ResolveWritableIntMember(heroStat.GetType(), "offence")', "retired Offence mutation")
	reject(runtime, 'ResolveWritableIntMember(heroStat.GetType(), "defence")', "retired Defence mutation")
	reject(runtime, "PatchFinalizer(harmony, battleLogicInitMethod", "retired Init finalizer restore path")
	reject(runtime, "method.ReturnType != typeof(void)", "retired void-only Unit.Init finder")
	reject(evaluator, "UnitLinesBySid", "duplicate unit-line source of truth in evaluator")
	reject(evaluator, 'new UnitLine("', "hard-coded unit-line classification in evaluator")

	surface = read(plugin_dir / "Homm3BattleUnitInitSurface.cs")
	require(surface, "internal static class Homm3BattleUnitInitSurface", "shared Unit.Init surface type")
	require(surface, "MatchesUnitInitShape(", "shared Unit.Init shape matcher")
	require(surface, "ps.Length != 8 && ps.Length != 10", "shared 8/10-arg Init contract")
	require(surface, "method.ReturnType == typeof(bool)", "shared bool-return Init acceptance")
	require(surface, "MatchesSideTypeHint(ps[2].ParameterType)", "Unit.Init param[2] SideTypeHints gate")
	require(surface, "GameSymbols.BattleUnitInit.SideTypeHints", "centralized Init side type hints")
	require(surface, "DescribeUnitInitMiss(", "fail-closed Unit.Init miss diagnostic")
	require(surface, 'string.Equals(type.Name, "TransferSide"', "reject TransferSide as Init side arg")
	# Fail closed: Unit.Init postfix must not hash __args[2] as if it were TransferSide.
	reject(runtime, "GetHashCode(__args[2])", "unbridged Unit.Init arg[2] as TransferSide plan key")
	reject(runtime, "GetHashCode(battleSideArg)", "hashing battle-side wrapper as plan key")

	symbols = read(plugin_dir / "GameSymbols.cs")
	# Live Golden Era Hex.dll regenerated the battle-side wrapper; legacy eir is absent.
	m = re.search(r"internal static (?:partial )?class BattleUnitInit\b", symbols)
	battle_unit_init_idx = m.start() if m else -1
	if battle_unit_init_idx < 0:
		raise SystemExit("BattleUnitInit class not found in GameSymbols")
	# Bound the class body roughly until the next nested class at the same indent level.
	m = re.compile(r"\n\tinternal static (?:partial )?class ").search(symbols, battle_unit_init_idx + 1)
	next_class_idx = m.start() if m else -1
	battle_unit_init_slice = symbols[battle_unit_init_idx: next_class_idx if next_class_idx > 0 else None]
	side_hints_idx = battle_unit_init_slice.find("internal static readonly string[] SideTypeHints")
	if side_hints_idx < 0:
		raise SystemExit("BattleUnitInit.SideTypeHints block not found")
	side_hints_slice = battle_unit_init_slice[side_hints_idx : side_hints_idx + 500]
	live_pos = side_hints_slice.find('"ObjectPublicPrcgObPrcgInTrPrcgInUnique"')
	legacy_pos = side_hints_slice.find('"eir"')
	if live_pos < 0:
		raise SystemExit("BattleUnitInit.SideTypeHints missing live Unit.Init side wrapper")
	if legacy_pos >= 0 and live_pos > legacy_pos:
		raise SystemExit("BattleUnitInit.SideTypeHints must pin live side wrapper before legacy eir")
	require(symbols, "BattleSideWrapperLocalSideIndexMembers", "GameSymbols battle-local side-index members")
	require(plugin, "Homm3FactorySplitAssemblyRuntime.TryRegister(_harmony, Log);", "plugin registration")
	require(plugin, "Homm3FactorySplitAssemblyArmyStripHud.TryRegister(_harmony, Log);", "army-strip HUD plugin registration")

	hud = read(plugin_dir / "Homm3FactorySplitAssemblyArmyStripHud.cs")
	require(hud, '"Hex.Session.Hud.BhHeroHUDPanel"', "army-strip HUD owns BhHeroHUDPanel")
	require(hud, "GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields", "army-strip HUD uses heroView")
	require(hud, "GameSymbols.ImportVisuals.TooltipHeroItemPortraitFields", "army-strip HUD uses heroFace portrait")
	require(hud, "GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields", "army-strip HUD session hero from heroView")
	require(hud, "GameSymbols.DraconicDominion.DataPartyUnitSidMembers", "army-strip HUD party SID via field_Public_String_0")
	require(hud, "PositionMeterLeftOfPortrait(", "army-strip meters anchored left of heroFace")
	require(hud, "Homm3FactorySplitAssemblyHudHoverPump", "army-strip HUD hover pump for tooltips")
	require(hud, "TickHover(", "army-strip HUD hover tick")
	require(hud, "HOMM3_FACTORY_SPLIT_ASSEMBLY_TOOLTIP", "army-strip HUD tooltip root")
	require(hud, "EnsureLeafSprite(", "army-strip HUD procedural leaf icon")
	require(hud, "EnsureGearSprite(", "army-strip HUD procedural gear icon")
	reject(hud, '"Hex.Session.Hud.BhHeroUIElement"', "army-strip HUD must not target side hero list")
	reject(hud, "GameSymbols.HeroProfile.SideHeroIconFields", "army-strip HUD must not use side-list heroIcon")
	reject(hud, "GameSymbols.HeroProfile.SideHeroRefresh", "army-strip HUD must not hook side-list refresh")
	reject(hud, "PostfixSideHero", "army-strip HUD must not use side-list postfixes")
	require(symbols, '"field_Public_String_0", "get_field_Public_String_0", "sid"', "AdventureAiDecision unit SID pins live field_Public_String_0 first")

	require(project, "ValidateHomm3FactorySplitAssemblyRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_factory_split_assembly_runtime_contract.py", "MSBuild validator path")

	print("validated HoMM3 Factory Split Assembly source-static runtime contract")


if __name__ == "__main__":
	main()
