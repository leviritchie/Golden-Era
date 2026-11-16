#!/usr/bin/env python3
"""Source-static contract for the HoMM3 Conflux Elemental Fusion runtime (plugin side).

Checks that the world-spell intercept, refund, army write, panel, Wall of Flame stamp, plugin registration and the
fusion_config.json deploy item stay wired. When custom_factions/conflux_fusion/fusion_config.json exists (Lane 1 owns
it), it is also checked against what the runtime parser accepts. Proof boundary: source + build only; the intercept,
native charge/refund, panel and army write are runtime-unvalidated.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SPELL_SID = "homm3_conflux_elemental_fusion"
SCHEMA = "homm3_conflux_fusion_config.v1"
LAVA_SID = "h3_earth_elemental_upg_alt"
WALL_TRAP_SID = "magic_primal_wall_of_flame_summon"


def read(path: Path) -> str:
	if not path.is_file():
		raise SystemExit(f"missing {path}")
	return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, why: str) -> None:
	if needle not in text:
		raise SystemExit(f"missing {why}: {needle!r}")


def reject(text: str, needle: str, why: str) -> None:
	if needle in text:
		raise SystemExit(f"rejected {why}: {needle!r}")


def check_config(path: Path) -> str:
	data = json.loads(path.read_text(encoding="utf-8-sig"))
	if data.get("schema") != SCHEMA:
		raise SystemExit(f"{path}: schema {data.get('schema')!r}, expected {SCHEMA}")
	if data.get("spellSid") != SPELL_SID:
		raise SystemExit(f"{path}: spellSid {data.get('spellSid')!r}, expected {SPELL_SID}")
	penalty = data.get("penalty")
	share = data.get("minShare")
	if not isinstance(penalty, (int, float)) or not 0 < penalty <= 1:
		raise SystemExit(f"{path}: penalty {penalty!r} outside (0, 1]")
	if not isinstance(share, (int, float)) or not 0 <= share <= 0.5:
		raise SystemExit(f"{path}: minShare {share!r} outside [0, 0.5]")
	lines = data.get("lines")
	if not isinstance(lines, dict) or not lines:
		raise SystemExit(f"{path}: lines missing")
	line_of: dict[str, str] = {}
	for line, sids in lines.items():
		if not isinstance(sids, list) or not all(isinstance(s, str) and s.strip() for s in sids):
			raise SystemExit(f"{path}: lines.{line} must be a list of sids")
		for sid in sids:
			if sid in line_of:
				raise SystemExit(f"{path}: {sid} in lines {line_of[sid]} and {line}")
			line_of[sid] = line
	tiers = data.get("tierLines")
	if not isinstance(tiers, dict) or not tiers:
		raise SystemExit(f"{path}: tierLines missing")
	for rank, names in tiers.items():
		if rank not in ("1", "2", "3"):
			raise SystemExit(f"{path}: tierLines key {rank!r} is not 1..3")
		for name in names:
			if name not in lines:
				raise SystemExit(f"{path}: tierLines.{rank} names unknown line {name!r}")
	seen = set()
	pairs = data.get("pairs")
	if not isinstance(pairs, list) or not pairs:
		raise SystemExit(f"{path}: pairs missing")
	for pair in pairs:
		a, b, fused = pair.get("a"), pair.get("b"), pair.get("fused")
		if not (a and b and fused):
			raise SystemExit(f"{path}: pair needs a, b and fused: {pair!r}")
		if a == b or a not in line_of or b not in line_of:
			raise SystemExit(f"{path}: bad pair {a}+{b}")
		if not fused.startswith("h3_fusion_"):
			raise SystemExit(f"{path}: fused sid {fused!r} does not start with h3_fusion_")
		key = tuple(sorted((a, b)))
		if key in seen:
			raise SystemExit(f"{path}: pair {key} listed twice")
		seen.add(key)
	fused_stage1 = {pair["fused"] for pair in pairs}
	recipes = data.get("recipes") or []
	for recipe in recipes:
		a, b, fused = recipe.get("a"), recipe.get("b"), recipe.get("fused")
		if not (a and b and fused) or a == b or a not in fused_stage1 or b not in fused_stage1:
			raise SystemExit(f"{path}: bad recipe {recipe!r}")
		if not fused.startswith("h3_fusion_") or fused in fused_stage1:
			raise SystemExit(f"{path}: recipe fused sid {fused!r} is not a new h3_fusion_ unit")
		key = tuple(sorted((a, b)))
		if key in seen:
			raise SystemExit(f"{path}: recipe {key} listed twice")
		seen.add(key)
	return f"; config {len(pairs)} pairs, {len(recipes)} recipes"


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
	args = parser.parse_args()
	root = args.repo_root.resolve()
	plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
	runtime = read(plugin_dir / "Homm3ConfluxFusionRuntime.cs")
	panel = read(plugin_dir / "Homm3ConfluxFusionPanel.cs")
	glossary = read(plugin_dir / "Homm3ConfluxFusionGlossary.cs")
	writer = read(plugin_dir / "Homm3PartyArmyWriter.cs")
	captives = read(plugin_dir / "Homm3DungeonCaptivesRuntime.cs")
	bridge = read(plugin_dir / "Homm3MarshalSuppressingFireTrapBridge.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")

	# Intercept: prefix on the shared native Necromancer Will Cast, foreign modes pass through.
	require(runtime, f'FusionMode = "{SPELL_SID}"', "spell mode constant")
	require(runtime, "GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints", "centralized handler hints")
	require(runtime, "GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast", "centralized Cast symbol")
	require(runtime, "PrefixFusionSpellCast(object __instance, ref bool __result)", "prefix signature")
	require(runtime, "!string.Equals(parameters[0], FusionMode, StringComparison.Ordinal))\n\t\t\t\treturn true;", "foreign modes return true")
	require(runtime, "__result = true;\n\t\t\treturn false;", "panel path reports success and suppresses native")
	require(runtime, "string.Equals(sideType, \"Player\", StringComparison.Ordinal)", "AI / non-human refusal")
	require(runtime, "Homm3SwashbucklerGoldHook.TryReadSessionDay", "plugin usage guard (only acts on a positive usageLimit)")
	# The spell is free and unlimited (Core manaCost 0, usageLimit -1): no player-facing once-per-day text.
	reject(runtime, "once per day.", "once-per-day banner text")
	# Refund: mana and MapMagic usage restored on cancel.
	require(runtime, "session.DataHero.mana = manaNow + charged", "mana refund")
	require(runtime, "magic.usageCounter = session.UsageBefore", "usageCounter rollback")
	require(runtime, "magic.lastUsageDay = session.LastUsageDayBefore", "lastUsageDay rollback")
	require(runtime, "Homm3PartyArmyWriter.Write(", "shared army writer")
	require(runtime, "decimal.Floor(penalty * pooled / vF)", "fused count formula")
	require(runtime, 'LogPrefix = "[ConfluxFusion] "', "log prefix")
	for needle in ("hook registered", "cast intercepted", "panel opened", "confirm: ", "cancel refund", "native charge observed"):
		require(runtime, needle, f"log line {needle!r}")
	require(runtime, '"custom_factions", "conflux_fusion", "fusion_config.json"', "deployed config path")
	require(runtime, f'LavaElementalSid = "{LAVA_SID}"', "Lava Elemental sid")
	# Panel: Cancel/Esc refund, Fuse goes through TryFuse.
	require(panel, 'Close(true, "Cancel")', "Cancel refunds")
	require(panel, 'Close(true, "Esc")', "Esc refunds")
	require(panel, "Homm3ConfluxFusionRuntime.TryFuse(", "Fuse confirm path")
	# Panel v2 (user, 2026-11-15): slots + Fuse only, drag instead of click, trim always on.
	require(runtime, "internal static Plan BuildTrimmedPlan(", "always-on trim plan")
	require(runtime, "var plan = BuildTrimmedPlan(session.Config", "Fuse writes the trimmed plan")
	require(runtime, 'root.TryGetProperty("recipes", out var recipes)', "stage-2 recipes parsed")
	require(runtime, "config.RecipeUnits.Contains(sid)", "stage-2 recipe inputs are eligible")
	require(panel, "Homm3ConfluxFusionRuntime.BuildTrimmedPlan(", "panel previews the trimmed plan")
	require(panel, "Homm3DungeonWarCaptivesWindow.NewDragGhost(", "drag ghost shared with War Captives")
	require(panel, "W.RecruitDragThreshold", "drag threshold shared with War Captives")
	for needle in ('"Auto-trim"', "AutoTrim", "Step(", '"All"', "Fusion is permanent", "lost to rounding", "click to fuse"):
		reject(panel, needle, "removed panel control/explanatory text")
	reject(runtime, "AutoTrim(", "optional auto-trim path")
	require(panel, "Homm3TowerArtificingPickerInputBlock.Begin()", "modal input block")
	require(panel, "ClassInjector.RegisterTypeInIl2Cpp<Homm3ConfluxFusionPanelHost>()", "host type registration")
	# Fusion Glossary (approved mockup tools/conflux_fusion/glossary_mockup.py, 2026-11-15): "?" button in the panel header,
	# opens over the panel, Esc / close return to the panel, live data, typed search, stage tabs, sortable columns.
	require(panel, "Homm3ConfluxFusionGlossary.AddOpenButton(_window, w - L.IconCenterX - Homm3ConfluxFusionGlossaryLayout.OpenButtonInset, hy)", "glossary button opposite the skill icon")
	require(panel, "if (Homm3ConfluxFusionGlossary.IsOpen)\n\t\t\t{\n\t\t\t\tHomm3ConfluxFusionGlossary.Tick(", "glossary takes input (and Esc) before the panel")
	require(panel, "Homm3ConfluxFusionGlossary.Open(_window.parent, _session.Config)", "glossary opens on the panel canvas")
	require(panel, "Homm3ConfluxFusionGlossary.Close();", "panel close also closes the glossary")
	require(glossary, 'ButtonTooltip = "Fusion Glossary"', "glossary button tooltip")
	require(glossary, 'SpriteDatabase = "Button_Database"', "native database button sprite")
	for sprite in ("Button_Database_MouseOver", "KeyField", "Button_Tab_Dark", "Button_Tab_Dark_Selected", "Button_Tab_Dark_MouseOver",
	               "tab_1", "tab_selected_1", "scroll_background", '"scroll"', "Dropdown_arrow"):
		require(glossary, sprite, f"glossary native sprite {sprite}")
	require(glossary, "Input.inputString", "search typing captured from Input.inputString")
	reject(glossary, "TMP_InputField", "glossary search must not use a TMP_InputField")
	require(glossary, "if (Input.GetKeyDown(KeyCode.Escape))\n\t\t\t{\n\t\t\t\tClose();\n\t\t\t\treturn;", "Esc closes the glossary only")
	require(glossary, "Input.mouseScrollDelta", "mouse wheel scrolls the list")
	for label in ('"All ("', '"Stage I ("', '"Stage II ("', '" of " + _entries.Count + " shown"', '"Stage II fusion"', '"Family tree"', '"Abilities"', '"  (active)"', '"Needs "'):
		require(glossary, label, f"glossary label {label}")
	require(glossary, "Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(e.Sid)", "live unit logic stats")
	require(glossary, "GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigTables", "live unit view cards")
	require(glossary, "GameSymbols.LiveRenamedMembers.UnitStatHp", "renamed hp member via GameSymbols")
	require(glossary, 'new("Lang/english/texts/unitsAbility.json"', "localized ability texts")
	require(glossary, 'Numbers.Replace(text, "#")', "per-unit number placeholders shown as #, never invented")
	require(glossary, "r = Math.Max(config.RecipeMinRank, Math.Max(ra, rb));", "stage II unlock rank")
	reject(glossary, "ParameterOverride<", "generic interop override call")
	reject(glossary, "GetWorldCorners", "fill-array interop API")

	# Shared army writer, and War Captives uses it.
	require(writer, "internal static WriteResult Write(", "army writer entry")
	require(captives, "Homm3PartyArmyWriter.Write(", "War Captives recruit uses the shared writer")
	require(captives, "Homm3PartyArmyWriter.TryResolve(", "War Captives resolves the shared writer")
	# Wall of Flame: placer-scaled flat damage, hero casts untouched.
	require(bridge, f'LavaWallOfFlameTrapSid = "{WALL_TRAP_SID}"', "Wall of Flame trap sid")
	require(bridge, "LavaDamagePerCreature = 10", "10 per creature")
	require(bridge, "Homm3ConfluxFusionRuntime.FirewallPlacerSids().Contains(placerSid)", "placer gate")
	require(bridge, "return; // hero cast", "hero casts untouched")
	# Wiring.
	require(plugin, "Homm3ConfluxFusionRuntime.TryRegister(_harmony, Log);", "plugin registration")
	require(project, "ValidateHomm3ConfluxFusionRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_conflux_fusion_runtime_contract.py", "MSBuild validator path")
	require(project, r"custom_factions\conflux_fusion\fusion_config.json", "config deploy item")
	require(project, r"$(PluginDeployDir)custom_factions\conflux_fusion", "config deploy destination")
	# Obfuscated names stay in GameSymbols.
	for text, name in ((runtime, "runtime"), (panel, "panel"), (glossary, "glossary")):
		if re.search(r'"Method_Public_[A-Za-z0-9_]+"', text) or re.search(r'"field_Public_[A-Za-z0-9_]+"', text):
			raise SystemExit(f"obfuscated member string in {name}; centralize it in GameSymbols")

	suffix = ""
	config = root / "custom_factions" / "conflux_fusion" / "fusion_config.json"
	if config.is_file():
		suffix = check_config(config)
	else:
		suffix = "; config not present yet (Lane 1)"
	print("validated HoMM3 Conflux Elemental Fusion runtime source-static contract" + suffix)


if __name__ == "__main__":
	main()
