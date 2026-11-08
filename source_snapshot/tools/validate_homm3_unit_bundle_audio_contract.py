#!/usr/bin/env python3
"""Fail if inventory units with battle SFX metadata ship AssetBundles without sound prefabs.

Gate: units_inventory.json rows with sndBattlePrefix or non-empty soundPaths that also
appear in homm3_units_manifest.json must have sounds/*.prefab entries in the matching
Unity .manifest under tools/homm3_import/build_out (or --bundle-dir).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "tools" / "homm3_import" / "units_inventory.json"
DEFAULT_MANIFEST = ROOT / "tools" / "homm3_import" / "homm3_units_manifest.json"
DEFAULT_BUNDLE_DIR = ROOT / "tools" / "homm3_import" / "build_out"

SOUND_PREFAB_RE = re.compile(r"sounds/.*\.prefab", re.IGNORECASE)


def load_json(path: Path) -> object:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def bundle_name_matches(bundle_name: str, prefix: str) -> bool:
	"""Exact bundle names stay exact; a trailing '_' is a family prefix.

	`custom_units_h3_mage` must not pull `custom_units_h3_mage_upg`.
	`custom_units_factory_` still matches every Factory bundle.
	"""
	if prefix.endswith("_"):
		return bundle_name.startswith(prefix)
	return bundle_name == prefix


def has_audio_meta(row: dict) -> bool:
	if isinstance(row.get("sndBattlePrefix"), str) and row["sndBattlePrefix"].strip():
		return True
	paths = row.get("soundPaths")
	return isinstance(paths, dict) and bool(paths)


def validate(
    *,
    inventory_path: Path,
    manifest_path: Path,
    bundle_dir: Path,
    name_prefixes: list[str] | None = None,
) -> list[str]:
	errors: list[str] = []
	if not inventory_path.is_file():
		return [f"missing inventory: {inventory_path}"]
	if not manifest_path.is_file():
		return [f"missing unit manifest: {manifest_path}"]
	if not bundle_dir.is_dir():
		return [f"missing bundle dir: {bundle_dir}"]

	inv = load_json(inventory_path)
	man = load_json(manifest_path)
	units = inv.get("units") if isinstance(inv, dict) else None
	man_units = man.get("units") if isinstance(man, dict) else None
	if not isinstance(units, list):
		return [f"{inventory_path}: units must be a list"]
	if not isinstance(man_units, list):
		return [f"{manifest_path}: units must be a list"]

	by_sid = {
		u["unitSid"]: u["bundleName"]
		for u in man_units
		if isinstance(u, dict) and isinstance(u.get("unitSid"), str) and isinstance(u.get("bundleName"), str)
	}

	for row in units:
		if not isinstance(row, dict):
			continue
		sid = row.get("unitSid")
		if not isinstance(sid, str) or not sid:
			continue
		if not has_audio_meta(row):
			continue
		bundle_name = by_sid.get(sid)
		if not bundle_name:
			continue
		if name_prefixes and not any(bundle_name_matches(bundle_name, prefix) for prefix in name_prefixes):
			continue
		manifest_file = bundle_dir / f"{bundle_name}.manifest"
		if not manifest_file.is_file():
			errors.append(
				f"{sid}: expected audio but missing Unity manifest {manifest_file.name} under {bundle_dir}"
			)
			continue
		text = manifest_file.read_text(encoding="utf-8", errors="replace")
		count = len(SOUND_PREFAB_RE.findall(text))
		if count <= 0:
			errors.append(
				f"{sid}: expected audio but {manifest_file.name} lists 0 sounds/*.prefab "
				f"(stage_homm3_unit_audio + Homm3BattleSoundPrefabsBuild + rebuild bundle)"
			)
	return errors


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
	ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
	ap.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
	ap.add_argument(
		"--name-prefix",
		action="append",
		default=[],
		help="Limit checks to this exact bundle name, or a family prefix ending in '_'; repeatable.",
	)
	args = ap.parse_args()
	errors = validate(
		inventory_path=args.inventory.resolve(),
		manifest_path=args.manifest.resolve(),
		bundle_dir=args.bundle_dir.resolve(),
		name_prefixes=args.name_prefix,
	)
	if errors:
		print("validate_homm3_unit_bundle_audio_contract: FAIL", file=sys.stderr)
		for err in errors:
			print(f"  - {err}", file=sys.stderr)
		return 1
	print("validate_homm3_unit_bundle_audio_contract: OK")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
