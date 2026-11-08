#!/usr/bin/env python3
"""Validate the Castle Elite Strategem one-shot and responsive-popup contract."""

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


def symbol_const(text: str, name: str) -> str:
	match = re.search(r"internal (?:const|static readonly) string " + re.escape(name) + r"\s*=\s*\"([^\"]+)\";", text)
	if not match:
		raise SystemExit(f"missing GameSymbols.CastleEliteStrategem.{name} constant")
	return match.group(1)


def current_member(text: str, name: str) -> tuple[str, str] | None:
	"""Return (live member, owner type) from a generated GameSymbolScope.Member pin, if present."""
	match = re.search(
		r"\b" + re.escape(name) + r"\s*=\s*GameSymbolScope\.Member\(\"CastleEliteStrategem\." + re.escape(name)
		+ r"\",\s*" + re.escape(name) + r",\s*0x[0-9A-Fa-f]+u,\s*\"([^\"]+)\",\s*\"([^\"]+)\"\);",
		text,
	)
	return (match.group(1), match.group(2)) if match else None


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	parser.add_argument("--hex-dll", type=Path, help="live Golden Era BepInEx/interop/Hex.dll (OfficialDeobf builds)")
	args = parser.parse_args()
	root = args.repo_root.resolve()
	plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

	runtime = read(plugin_dir / "Homm3CastleEliteStrategemRuntime.cs")
	symbols = read(plugin_dir / "GameSymbols.cs")
	current = read(plugin_dir / "GameSymbolsCurrent.g.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")
	surface = read(root / "docs" / "surfaces" / "separate_hero_battle_actions.md")

	# The pending mode must remain keyed by the casting hero and be claimed before
	# battle writes. A clean no-op restores the token; an exceptional partial write
	# must not leave a stale mode that can leak into later battles.
	require(runtime, "Dictionary<int, HeroModeState> ModesByHeroId", "per-hero pending mode map")
	require(runtime, "ModesByHeroId[heroId] = new HeroModeState", "per-hero mode storage")
	require(runtime, "out var ownerHeroId, out var ownerState", "owner hero id returned for consumption")
	require(runtime, "ModesByHeroId.Remove(ownerHeroId);", "one-shot mode claim")
	require(runtime, "if (!ModesByHeroId.ContainsKey(ownerHeroId))", "replacement-safe no-op restore")
	require(runtime, "ModesByHeroId.Add(ownerHeroId, ownerState);", "clean no-op mode restore")
	require(runtime, "if (changedSides == 0)", "failed-application guard")
	if runtime.index("ModesByHeroId.Remove(ownerHeroId);") > runtime.index("var changedSides = 0;"):
		raise SystemExit("one-shot mode is not claimed before battle writes")
	require(runtime, "eliteModeRecognized = true;", "recognized-mode fail-closed state")
	require(runtime, "native handler suppressed", "recognized-mode native fallback rejection")

	# Do not regress to managed proxy hashing for duplicate suppression. The
	# consumed token itself makes a second BattleLogic.Init call a no-op.
	reject(runtime, "AppliedBattleKeys", "persistent battle-object dedupe state")
	reject(runtime, "RuntimeHelpers.GetHashCode", "managed TransferBattle identity")

	# Popup layout must calculate its content at the current resolution instead
	# of clipping a fixed-height, no-wrap body string.
	require(runtime, "Screen.height / ReferenceHeight", "height-based popup scale")
	require(runtime, "MaximumScale = 3f", "high-resolution popup scale range")
	require(runtime, "s_bodyStyle.CalcHeight", "content-aware popup height")
	require(runtime, "wordWrap = true", "wrapped popup body")
	require(runtime, "Applies to this hero's next battle.", "one-shot popup text")
	require(surface, "consumed after the first successful application", "documented one-shot behavior")

	# Casting-hero bridge (2026-09-27 regression): the handler -> WorldHero member named a
	# type that does not exist in live interop, so every Spread Out / Compress / Ambush cast
	# failed closed with "world-magic WorldHero member missing". The bridge must be resolved
	# at registration with exact property types, never by a best-effort name list at cast time.
	require(runtime, "_handlerWorldHeroProperty = ResolveRequiredTypedProperty(", "registration-time handler->WorldHero pin")
	require(runtime, "_worldHeroLogicHeroProperty = ResolveRequiredTypedProperty(", "registration-time WorldHero->LogicHero pin")
	require(runtime, "GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty", "centralized handler WorldHero symbol")
	require(runtime, "GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty", "centralized WorldHero LogicHero symbol")
	reject(runtime, "NecromancyWorldMagicWorldHeroMembers", "cast-time WorldHero name-list probing")
	reject(symbols, "ObjectPublicAbstractSiObSiObSiObSiObSiUnique", "non-existent world-magic WorldHero type hint")
	handler_property = symbol_const(symbols, "NecromancyWorldMagicWorldHeroProperty")
	logic_hero_property = symbol_const(symbols, "WorldHeroLogicHeroProperty")
	current_handler = current_member(current, "NecromancyWorldMagicWorldHeroProperty")
	current_logic_hero = current_member(current, "WorldHeroLogicHeroProperty")
	if current_handler is None or current_logic_hero is None:
		raise SystemExit("missing generated current-scope GameSymbolScope.Member pins for the Castle Elite Strategem casting-hero bridge")
	scope_needles = {
		# Golden Era base pins in GameSymbols.cs (pre-25672315 interop).
		"base": (
			("NativeFieldInfoPtr_" + handler_property, "world-magic handler WorldHero field"),
			("ObjectPublicMaciObInciObcociUnique", "world-magic handler base type"),
			("ObjectPublicHeObInObciSiObVeSeObUnique", "WorldHero type"),
			("NativeFieldInfoPtr_" + logic_hero_property, "WorldHero LogicHero backing field"),
		),
		# Current-port pins generated into GameSymbolsCurrent.g.cs; owners come from the same pins.
		"current": (
			("NativeFieldInfoPtr_" + current_handler[0], "world-magic handler WorldHero field"),
			(current_handler[1], "world-magic handler base type"),
			(current_logic_hero[1], "WorldHero type"),
			("NativeFieldInfoPtr_" + current_logic_hero[0], "WorldHero LogicHero backing field"),
		),
	}
	matched_scope = None
	if args.hex_dll is not None:
		data = args.hex_dll.read_bytes() if args.hex_dll.is_file() else None
		if data is None:
			raise SystemExit(f"missing live interop Hex.dll: {args.hex_dll}")
		missing_by_scope = {}
		for scope, needles in scope_needles.items():
			missing = [f"{label}: {needle}" for needle, label in needles if needle.encode("utf-8") not in data]
			if not missing:
				matched_scope = scope
				break
			missing_by_scope[scope] = missing
		if matched_scope is None:
			details = "; ".join(f"{scope} scope missing " + ", ".join(missing) for scope, missing in missing_by_scope.items())
			raise SystemExit(f"live Hex.dll {args.hex_dll} matches neither the Golden Era nor the current-port casting-hero pins: {details}")

	require(runtime, "Homm3CastleEliteStrategemIndicatorBootstrap.SetMode(mode, revision);", "popup notification")
	require(plugin, "Homm3CastleEliteStrategemRuntime.TryRegister(_harmony, Log);", "runtime registration")
	require(project, "ValidateHomm3CastleEliteStrategemRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_castle_elite_strategem_runtime_contract.py", "MSBuild validator path")

	print("validated HoMM3 Castle Elite Strategem one-shot, casting-hero bridge, and responsive-popup contract" + (f" against live Hex.dll ({matched_scope} scope pins)" if matched_scope is not None else " (source-static)"))


if __name__ == "__main__":
	main()
