#!/usr/bin/env python3
"""Validate Bulwark Runes logic-hub owner, incremental buffs, and fail-closed contracts."""

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


def extract_overlay_rune_rows(overlay: str) -> list[dict]:
	"""Evaluate only make_homm3_bulwark_rune_level_buff_rows without importing the full overlay."""
	marker = "def make_homm3_bulwark_rune_level_buff_rows()"
	start = overlay.find(marker)
	if start < 0:
		raise SystemExit("overlay missing make_homm3_bulwark_rune_level_buff_rows")
	rest = overlay[start:]
	match = re.search(r"\ndef [a-zA-Z_]", rest[1:])
	end = (match.start() + 1) if match else len(rest)
	fn_src = rest[:end]
	ns: dict = {}
	exec("from __future__ import annotations\nfrom typing import Any\n" + fn_src, ns, ns)
	rows = ns["make_homm3_bulwark_rune_level_buff_rows"]()
	if not isinstance(rows, list) or len(rows) != 9:
		raise SystemExit(f"expected 9 rune buff rows, got {len(rows) if isinstance(rows, list) else type(rows)}")
	return rows


def validate_incremental_rows(rows: list[dict]) -> None:
	expected = {
		1: {"offence": 2},
		2: {"defence": 2},
		3: {"speed": 1},
		4: {"offence": 2},
		5: {"defence": 2},
		6: {"speed": 1},
		7: {"offence": 2},
		8: {"defence": 2},
		9: {"speed": 1},
	}
	for level, stats in expected.items():
		row = next((r for r in rows if r.get("id") == f"homm3_bulwark_rune_level_{level}"), None)
		if row is None:
			raise SystemExit(f"missing rune buff row level {level}")
		got = (row.get("data") or {}).get("stats") or {}
		if got != stats:
			raise SystemExit(f"rune level {level} stats expected {stats}, got {got}")
		tags = row.get("tags") or []
		if not isinstance(tags, list):
			raise SystemExit(f"rune level {level} tags must be a list")
		if "positive" not in tags:
			raise SystemExit(f"rune level {level} missing positive tag")
		if "speed" in stats:
			for required in ("movementPositive", "hasteEffect", "haste"):
				if required not in tags:
					raise SystemExit(f"rune level {level} speed row missing tag {required}")
		else:
			if "movementPositive" in tags:
				raise SystemExit(f"rune level {level} non-speed row must not carry movementPositive")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	args = parser.parse_args()
	root = args.repo_root.resolve()
	plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
	overlay_path = root / "tools" / "release_port" / "apply_release_core_overlay.py"

	runtime = read(plugin_dir / "Homm3BulwarkRunesRuntime.cs")
	symbols = read(plugin_dir / "GameSymbols.cs")
	hooks = read(plugin_dir / "Homm3RuntimeMechanicHooks.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")
	overlay = read(overlay_path)
	source = read(root / "custom_factions" / "source_mechanics" / "homm3_bulwark.json")

	require(runtime, "internal static class Homm3BulwarkRunesRuntime", "Runes runtime owner")
	require(runtime, "Homm3DirectStateIdentity.TryResolveKey", "native-pointer stack keys")
	require(runtime, "CapBasic = 3", "Basic cap")
	require(runtime, "CapAdvanced = 6", "Advanced cap")
	require(runtime, "CapExpert = 9", "Expert cap")
	require(runtime, "GainForDefend() => 3", "Defend gain")
	require(runtime, "GainForDamageTakenOncePerAction() => 2", "damage gain")
	require(runtime, "GainForAttackOrCast() => 1", "attack/cast gain")
	require(runtime, 'RuneBuffSidPrefix = "homm3_bulwark_rune_level_"', "Rune buff SID prefix")
	require(runtime, "IsWarMachineExcluded(", "war-machine exclusion")
	require(runtime, 'BulwarkSkillSid = "skill_faction_homm3_bulwark"', "Bulwark skill SID")
	require(runtime, "IncrementalOffenceForThreshold", "incremental offence thresholds")
	require(runtime, "IncrementalDefenceForThreshold", "incremental defence thresholds")
	require(runtime, "IncrementalSpeedForThreshold", "incremental speed thresholds")
	require(runtime, "AppliedThresholds", "applied-threshold dedup")
	require(runtime, "AwardedObservationKeys", "action/event deduplication")
	require(runtime, "CorrelateGain(", "correlation owner")
	require(runtime, "PostfixWait", "Wait exclusion hook")
	require(runtime, "PostfixSkipDefend", "Defend/Skip hook")
	require(runtime, "WaitArmedByUnitKey", "Wait arm for Method_15→47 dual-raise")
	require(runtime, "corr Defend/Skip withheld: Wait armed", "dual-raise Wait withholds Defend")
	require(runtime, "armed for dual-raise Method_47", "Wait arms Method_15")
	require(runtime, '"corr Defend/Skip unitKey="', "Defend award log on Skip/Method_47")
	require(runtime, '" gain="\n\t\t\t\t+ gain\n\t\t\t\t+ " reason="', "Defend award gain log shape")
	require(runtime, "LIVE-POSITIVE: Method_47 is Defend/Skip", "Defend Method_47 documentation")
	require(runtime, "LIVE-POSITIVE: Method_15 is Wait", "Wait Method_15 documentation")
	reject(runtime, "PendingDefendByUnitKey", "stale pending-Defend map")
	reject(runtime, "FlushPendingDefendsExcept(", "stale pending-Defend flush")
	reject(runtime, "action.PendingDefend", "Defend pending must not live on ActionCorrelation")
	reject(runtime, "LIVE-NEGATIVE 2026-07-26: Wait raises Method_15", "stale inverted Wait dual-raise note")
	require(runtime, "ClearBattleState(", "battle cleanup API")
	require(runtime, "Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver", "add-and-dispatch buff path")
	require(runtime, "BattleLogicEventsTypeHints", "logic-hub type hints")
	require(runtime, "ResolveLogicEventHubType", "logic-hub resolver")
	require(runtime, "runtime-pending", "runtime-pending proof language")
	require(runtime, "probeOnly", "optional correlation probe gate")

	require(runtime, "GameSymbols.BattleEventLaws.ActionStartedDispatcher", "ActionStart symbol")
	require(runtime, "GameSymbols.BattleEventLaws.ActionEndedDispatcher", "ActionEnd symbol")
	require(runtime, "GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher", "damage symbol")
	require(runtime, "GameSymbols.BattleEventLaws.SkipDispatcher", "Skip/Defend symbol")
	require(runtime, "GameSymbols.BattleEventLaws.WaitDispatcher", "Wait symbol")
	require(runtime, "GameSymbols.BattleEventLaws.CastAbilityDispatcher", "CastAbility symbol retained for xref")
	require(runtime, "GameSymbols.BulwarkRunesLaws.AbilityCommitExecute", "token-pinned ability-commit MethodInfo")
	require(runtime, "PatchAbilityCommitExecute(", "ability-commit patch owner")
	require(runtime, "PostfixAbilityCommitExecute", "ability-commit postfix")
	require(runtime, "corr abilityCommit award", "direct +1 award in commit postfix")
	require(runtime, "IsAwardableCommittedAbility(", "attack/cast/counter classification")
	require(runtime, "LIVE-NEGATIVE", "live-negative Method_34 documentation")
	require(runtime, "EnterObserve(", "reentrancy guard enter")
	require(runtime, "harmony.Patch(", "approved logic-hub Harmony patches")
	reject(runtime, "nameof(PostfixCastAbility)", "CastAbility Harmony postfix registration")
	reject(runtime, "nameof(PostfixChangeAbility)", "ChangeAbility Harmony postfix registration")
	reject(runtime, "CastAbilityDispatcher, nameof(", "CastAbility PatchDispatcher wire")
	reject(runtime, "ChangeAbilityDispatcher, nameof(", "ChangeAbility PatchDispatcher wire")
	reject(runtime, "Attack/cast/counter +1 gains remain disabled", "stale withheld-gain warning")
	reject(runtime, "TryAwardCommittedAttackOrCast(", "ActionEnded attack/cast stash award")
	reject(runtime, "AbilityCommitExecuteMethods", "stale bate/ldn/cec name-list patching")
	reject(runtime, 'foreach (var name in GameSymbols.BulwarkRunesLaws', "short-name ability commit loop")
	reject(runtime, '"bate"', "bate short-name search in Runes runtime")
	reject(runtime, '"ldn"', "ldn short-name search in Runes runtime")
	reject(runtime, '"cec"', "cec short-name search in Runes runtime")
	reject(runtime, "→ ActionEnded +1", "stale ActionEnded award language")
	reject(runtime, "stashed from", "stale stash language")

	reject(runtime, 'TypeByName("edb")', "view-hub TypeByName(edb)")
	reject(runtime, 'AccessTools.TypeByName("edb")', "view-hub AccessTools edb")
	require(runtime, 'string.Equals(hint, "edb"', "explicit edb skip in hub resolver")
	reject(runtime, "PostfixUnitInit", "Unit.Init postfix dependency")
	reject(runtime, "BattleUnitInit", "Unit.Init surface dependency")
	reject(runtime, "Homm3BattleUnitInitSurface", "Unit.Init surface helper")
	reject(runtime, "ExtraGainForRuneBrand", "Rune Brand activation")
	reject(runtime, "PossessesRunes", "Possesses Runes activation")
	reject(runtime, "h3_kobold_upg_alt", "Rune Brand SID")
	reject(runtime, "h3_yeti_runemaster", "Possesses Runes SID")
	reject(runtime, "dispatchEvent: false", "state-only buff application")
	reject(runtime, "TryAddBuffSidFromReceiverWithoutDispatch", "state-only buff helper")
	reject(runtime, "RuntimeHelpers.GetHashCode(unit)", "managed object identity for stack keys")
	reject(runtime, "GetHashCode() as key", "managed hash stack keys")

	require(symbols, "ObjectTookDamageDispatcher", "GameSymbols damage dispatcher")
	require(symbols, "SkipDispatcher", "GameSymbols Skip dispatcher")
	require(symbols, "WaitDispatcher", "GameSymbols Wait dispatcher")
	require(symbols, "CastAbilityDispatcher", "GameSymbols CastAbility dispatcher")
	require(symbols, "BulwarkRunesLaws", "GameSymbols Bulwark Runes ability-commit surface")
	require(symbols, "AbilityCommitExecute", "token-pinned commit MethodSymbol")
	require(symbols, "Method_Private_Void_Il2CppStructArray_1_Int32_HashSet_1_FieldObject_0", "bate generated wrapper name")
	require(symbols, "AbilityCommitExecuteMetadataToken = 100700263", "bate metadata token")
	require(symbols, 'AbilityCommitExecuteRvaHex = "0x2EA7710"', "bate RVA")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_44", "ObjectTookDamage Method_44")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_15", "Wait Method_15")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_47", "Skip/Defend Method_47")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_45", "ActionStarted Method_45")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_42", "ActionEnded Method_42")
	require(symbols, "LIVE-POSITIVE 2026-07-26 (player Wait vs Defend/Skip)", "Wait/Skip Method_N swap proof")
	reject(symbols, 'ObjectTookDamageDispatcher = new(\n\t\t\t"directState.battleEvents.objectTookDamage",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_9")', "stale damage Method_9")
	reject(symbols, 'SkipDispatcher = new(\n\t\t\t"directState.battleEvents.skip",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_15")', "stale Skip Method_15 (Wait)")
	reject(symbols, 'WaitDispatcher = new(\n\t\t\t"directState.battleEvents.wait",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_47")', "stale Wait Method_47 (Skip)")
	reject(symbols, 'SkipDispatcher = new(\n\t\t\t"directState.battleEvents.skip",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_14")', "stale Skip Method_14")
	require(symbols, 'WaitDispatcher = new(\n\t\t\t"directState.battleEvents.wait",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_15")', "Wait Method_15 pin")
	require(symbols, 'SkipDispatcher = new(\n\t\t\t"directState.battleEvents.skip",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_47")', "Skip/Defend Method_47 pin")
	reject(symbols, 'AbilityCommitExecuteMethods', "stale bate/ldn/cec commit methods symbol")
	require(symbols, "prop_AbilityID_0", "AbilityLogicConfig interop AbilityID property")
	require(symbols, "_bxmh_k__BackingField", "AbilityLogicConfig interop AbilityID field")
	require(symbols, "Method_Public_get_AbilityID_0", "AbilityLogicConfig interop AbilityID getter")
	require(symbols, "LIVE-NEGATIVE", "GameSymbols Method_34 live-negative note")
	require(symbols, "Method_Public_Void_Object_BattleEventArgs_35", "repaired BuffEventDispatch Method_35")
	reject(symbols, "Method_Public_Void_Object_BattleEventArgs_63", "stale BuffEventDispatch Method_63")
	reject(symbols, 'BuffEventDispatch = new(\n\t\t\t"law.buffDebuff.buffEventDispatch.bcja",\n\t\t\t"bcja",\n\t\t\t"Method_Public_Void_Object_BattleEventArgs_39")', "stale BuffEventDispatch Method_39")
	require(symbols, '"eda", "ObjectPublicEv1BacfEv1BacfBoEvUnique"', "logic-hub type hints")
	require(symbols, '"ObjectPublicObceInBoInceAbObELInUnique"', "ability runtime interop type")
	require(hooks, "Homm3BulwarkRunesRuntime.ClearBattleState(", "shared battle-result cleanup")
	require(plugin, "Homm3BulwarkRunesRuntime.TryRegister(_harmony, Log);", "plugin registration")
	require(project, "ValidateHomm3BulwarkRunesRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_bulwark_runes_runtime_contract.py", "MSBuild validator path")
	require(project, "validate_homm3_bulwark_runes_correlation_fixture.py", "expensive correlation fixture wiring")
	require(project, "RunExpensiveArtifactAudits", "expensive audit gate")

	require(overlay, "make_homm3_bulwark_rune_level_buff_rows", "overlay Rune level buff generator")
	require(overlay, "Incremental Rune Level threshold buffs", "incremental buff docstring")
	require(overlay, 'bulwark_combat_buff_lang_rows', "Bulwark combat buff LOC row set")
	require(
		overlay,
		'for lang_path in ("Lang/english/texts/magic_buff.json", "Lang/english/texts/unitsBuff.json"):',
		"Rune/Frostbound buff LOC catalogs (buff UI)",
	)
	require(overlay, '"homm3_bulwark_rune_level_1_name"', "Rune level 1 name LOC")
	require(overlay, '"homm3_bulwark_rune_level_9_desc"', "Rune level 9 desc LOC")
	phrasebook = read(
		root / "tools" / "release_port" / "localization_phrasebooks" / "bulwark_runes_combat_buffs.json"
	)
	require(phrasebook, '"Runes I"', "Runes I phrasebook entry")
	require(phrasebook, '"+2 Offence."', "Offence desc phrasebook entry")
	require(phrasebook, '"+2 Defence."', "Defence desc phrasebook entry")
	require(phrasebook, '"Runes IX"', "Runes IX phrasebook entry")
	require(phrasebook, '"zhCN"', "CJK locale coverage in Runes phrasebook")
	rows = extract_overlay_rune_rows(overlay)
	validate_incremental_rows(rows)

	require(runtime, "TryResolveTransferSideForRunes(", "live TransferSide prefer over registry cache")
	require(runtime, "TryReuseCachedEligibleRank(", "cached skillRank continuity after logicHero miss")
	require(runtime, "HasLogicHero(", "logicHero-present TransferSide preference")
	reject(runtime, "RuneBuffLevel = 1", "stale fixed buff level=1 for all thresholds")

	require(source, '"id": "bulwark.runes"', "source_mechanics Runes row")
	require(source, '"status": "runtime-pending"', "Runes remains runtime-pending")

	print("validated HoMM3 Bulwark Runes logic-hub runtime contract")


if __name__ == "__main__":
	main()
