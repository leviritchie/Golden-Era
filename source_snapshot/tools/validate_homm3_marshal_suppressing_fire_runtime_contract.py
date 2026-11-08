#!/usr/bin/env python3
"""Validate Marshal Suppressing Fire Wall-of-Flame stamp source-static contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


LIVE_TRAP_TYPE = "FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique"
LIVE_TRAP_CONFIG = "_cgtl_k__BackingField"
TRAP_SID = "homm3_factory_suppressing_fire_trap"


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


def parse_string_array(source: str, class_name: str, array_name: str) -> list[str]:
	m = re.search(rf"internal static (?:partial )?class {re.escape(class_name)}\b", source)
	class_idx = m.start() if m else -1
	if class_idx < 0:
		raise SystemExit(f"missing GameSymbols class {class_name}")
	m = re.compile(r"\n\tinternal static (?:partial )?class ").search(source, class_idx + 1)
	next_class = m.start() if m else -1
	slice_ = source[class_idx: next_class if next_class > 0 else None]
	header = re.search(
		rf"internal\s+static\s+readonly\s+string\[\]\s+{re.escape(array_name)}\s*=",
		slice_,
	)
	if not header:
		raise SystemExit(f"missing {class_name}.{array_name}")
	semi = slice_.find(";", header.end())
	if semi < 0:
		raise SystemExit(f"unterminated {class_name}.{array_name}")
	return re.findall(r'"([^"]+)"', slice_[header.end():semi])


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	args = parser.parse_args()
	root = args.repo_root.resolve()
	plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

	bridge = read(plugin_dir / "Homm3MarshalSuppressingFireTrapBridge.cs")
	symbols = read(plugin_dir / "GameSymbols.cs")
	plugin = read(plugin_dir / "Plugin.cs")
	project = read(plugin_dir / "OfflineUnlockMod.csproj")
	overlay = read(root / "tools" / "release_port" / "apply_release_core_overlay.py")

	type_hints = parse_string_array(symbols, "MarshalSuppressingFireTrap", "TrapRuntimeTypeHints")
	config_hints = parse_string_array(symbols, "MarshalSuppressingFireTrap", "InstanceTrapConfigMembers")
	if not type_hints or type_hints[0] != LIVE_TRAP_TYPE:
		raise SystemExit(
			"TrapRuntimeTypeHints must lead with live type "
			f"{LIVE_TRAP_TYPE}; got {type_hints!r}"
		)
	if "ekh" not in type_hints:
		raise SystemExit("TrapRuntimeTypeHints must retain legacy alias ekh")
	if type_hints.index("ekh") == 0:
		raise SystemExit("legacy alias ekh must not lead TrapRuntimeTypeHints")
	if not config_hints or config_hints[0] != LIVE_TRAP_CONFIG:
		raise SystemExit(
			"InstanceTrapConfigMembers must lead with "
			f"{LIVE_TRAP_CONFIG}; got {config_hints!r}"
		)

	require(symbols, f'TrapSid = "{TRAP_SID}"', "centralized trap SID")
	require(bridge, "GameSymbols.MarshalSuppressingFireTrap.TrapRuntimeTypeHints", "centralized trap type hints")
	require(bridge, "GameSymbols.MarshalSuppressingFireTrap.TrapInitMembers", "centralized Init members")
	require(bridge, "GameSymbols.MarshalSuppressingFireTrap.InstanceTrapConfigMembers", "centralized TrapConfig members")
	require(bridge, f'string.Equals(sid, GameSymbols.MarshalSuppressingFireTrap.TrapSid', "SID gate via GameSymbols")
	require(bridge, "PostfixTrapInit(object __instance, bool __result, object[] __args)", "Il2Cpp-safe __args postfix signature")
	require(bridge, "AccessTools.GetDeclaredMethods(trapType)", "declared-only Init resolution")
	require(bridge, "ps.Length != 6", "six-argument Init gate")
	require(bridge, "method.ReturnType != typeof(bool)", "Boolean Init gate")
	require(bridge, "trap_Init_ambiguous", "fail-closed ambiguous Init diagnostic")
	require(bridge, "__args[0] as string", "SID from __args[0]")
	require(bridge, "__args[5]", "initialCastSource from __args[5]")
	reject(bridge, "AccessTools.Method(trapType,", "AccessTools.Method Init lookup that AmbiguousMatchException-bricks plugin Load")
	reject(bridge, "string sid,", "named sid postfix arg mismatched live param_1")
	require(bridge, "AttackDamageMult = 1.5f", "150% multiplier")
	require(bridge, "MidpointRounding.AwayFromZero", "round-away-from-zero scaling")
	require(bridge, "perCreatureDamage * (double)stacks * AttackDamageMult", "damageMin/Max × stacks × 1.5")
	require(bridge, "dealer.minBaseDmg = minDamage", "flat min base damage write")
	require(bridge, "dealer.maxBaseDmg = maxDamage", "flat max base damage write")
	require(bridge, "dealer.minStackDmg = 0", "zero min stack damage")
	require(bridge, "dealer.maxStackDmg = 0", "zero max stack damage")
	require(bridge, "dealer.statDmgMult = 0f", "zero Magog-style statDmgMult")
	require(bridge, "combat stamping and", "combat-unvalidated proof boundary")
	require(bridge, "observed damage remain unvalidated", "observed-damage unvalidated proof boundary")
	# Magog-style scaling must stay rejected: only the explicit zero write is allowed.
	stat_assignments = re.findall(r"statDmgMult\s*=\s*([^;\n]+)", bridge)
	if not stat_assignments:
		raise SystemExit("missing dealer.statDmgMult assignment")
	for value in stat_assignments:
		if value.strip() != "0f":
			raise SystemExit(f"rejected Magog-style non-zero statDmgMult write: {value.strip()!r}")
	if re.search(r"statDmgMult\s*\*", bridge) or re.search(r"\*\s*.*statDmgMult", bridge):
		raise SystemExit("rejected Magog-style statDmgMult multiplication")

	require(overlay, "make_homm3_factory_suppressing_fire_trap", "overlay trap row helper")
	require(overlay, f'"id": "{TRAP_SID}"', "overlay trap SID")
	require(overlay, "Homm3MarshalSuppressingFireTrapBridge", "overlay cites runtime stamp bridge")

	require(plugin, "Homm3MarshalSuppressingFireTrapBridge.TryRegister(_harmony, Log);", "plugin registration")
	require(project, "ValidateHomm3MarshalSuppressingFireRuntimeContract", "MSBuild validator target")
	require(project, "validate_homm3_marshal_suppressing_fire_runtime_contract.py", "MSBuild validator path")

	# Obfuscated live type must stay centralized, not scattered into feature code.
	reject(bridge, f'"{LIVE_TRAP_TYPE}"', "live trap type string must not appear outside GameSymbols")
	reject(bridge, '"ekh"', "legacy trap type alias must not appear outside GameSymbols")
	reject(bridge, f'"{LIVE_TRAP_CONFIG}"', "TrapConfig member string must not appear outside GameSymbols")

	print("validated HoMM3 Marshal Suppressing Fire Wall-of-Flame stamp source-static contract")


if __name__ == "__main__":
	main()
