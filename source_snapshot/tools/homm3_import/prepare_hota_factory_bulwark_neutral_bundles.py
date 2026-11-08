#!/usr/bin/env python3
"""Prepare HotA Factory, Bulwark, and neutral unit bundle inputs.

Updates lane-B inventory/manifest/presets from local HotA content.zip archives.
Does not touch Core.zip, live Golden Era install, or lock alt-upgrade recolors.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

from hota_zip_unit_prep import (
	ALL_HOTA_ZIP_UNITS,
	BULWARK_UNITS,
	FACTORY_UNITS,
	HotaZipUnitSpec,
	NEUTRAL_UNITS,
	creature_config_member,
	faction_zip_rel,
	sprites_prefix,
)

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INVENTORY = HERE / "units_inventory.json"
MANIFEST = HERE / "homm3_units_manifest.json"
PRESETS = HERE / "presets"
UNIT_LIST = HERE / "factory_bulwark_neutral_unit_sids.txt"
INVENTORY_SOURCE_KEYS = (
	"comment",
	"battleExtractBasename",
	"mapExtractBasename",
	"battleDefPath",
	"battleLod",
	"battleLodEntry",
	"battleZipPath",
	"battleZipMember",
	"battleJsonZipMember",
	"battleJsonDirPrefix",
	"mapDefPath",
	"mapZipPath",
	"mapZipMember",
	"mapJsonZipMember",
	"mapJsonDirPrefix",
	"soundPaths",
	"sndBattlePrefix",
)


def load_json(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: pathlib.Path, data: dict) -> None:
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def loads_jsonc(text: str) -> dict:
	lines = []
	for line in text.splitlines():
		lines.append(re.sub(r"\s*//.*$", "", line))
	return json.loads("\n".join(lines))


def first_object(data: dict) -> dict:
	if len(data) == 1:
		value = next(iter(data.values()))
		if isinstance(value, dict):
			return value
	return data


def repo_relative_file(path: pathlib.PurePosixPath) -> pathlib.Path:
	candidates = [ROOT / pathlib.Path(path)]
	if ROOT.parent.name.lower() == "worktrees":
		candidates.append(ROOT.parent.parent / pathlib.Path(path))
	for candidate in candidates:
		if candidate.is_file():
			return candidate
	return candidates[0]


def zip_names_ci(zf: zipfile.ZipFile) -> dict[str, str]:
	return {name.replace("\\", "/").lower(): name.replace("\\", "/") for name in zf.namelist()}


def resolve_member(names_ci: dict[str, str], candidate: str) -> str | None:
	return names_ci.get(candidate.replace("\\", "/").lower())


def find_surface_member(names_ci: dict[str, str], spec: HotaZipUnitSpec, surface: str) -> tuple[str, str] | None:
	"""Return (kind, member) where kind is 'def' or 'json'."""
	prefix = sprites_prefix(spec, "adventureMap" if surface == "map" else "battle")
	stem = spec.map_stem if surface == "map" else spec.battle_stem
	for ext in ("def", "DEF", "json", "JSON"):
		member = prefix + f"{stem}.{ext}"
		hit = resolve_member(names_ci, member)
		if hit:
			kind = "json" if hit.lower().endswith(".json") else "def"
			return kind, hit
	# Stem-only search under prefix (case / extension drift).
	stem_l = stem.lower()
	for low, real in names_ci.items():
		if not low.startswith(prefix.lower()):
			continue
		base = pathlib.PurePosixPath(low).name
		if base.rsplit(".", 1)[0] == stem_l and base.endswith((".def", ".json")):
			kind = "json" if base.endswith(".json") else "def"
			return kind, real
	return None


def sound_paths_for(spec: HotaZipUnitSpec, names_ci: dict[str, str], row_cfg: dict) -> dict[str, str] | None:
	sound = row_cfg.get("sound") or {}
	zip_rel = faction_zip_rel("neutral" if spec.source == "hota_neutral_zip" else spec.faction)
	paths: dict[str, str] = {}
	for key in ("move", "attack", "wince", "killed"):
		value = sound.get(key)
		if not value:
			return None
		member = "sounds/" + pathlib.PurePosixPath(str(value)).as_posix().lstrip("/")
		# HotA configs sometimes already include hota/... under sounds/
		if not member.lower().startswith("sounds/"):
			member = "sounds/" + member
		hit = resolve_member(names_ci, member)
		if hit is None:
			# Config paths for factory/bulwark are often relative to sounds/ already
			# like hota/factory/creatures/...
			alt = pathlib.PurePosixPath(str(value)).as_posix()
			if not alt.startswith("sounds/"):
				alt = "sounds/" + alt
			hit = resolve_member(names_ci, alt)
		if hit is None:
			return None
		paths[key] = f"{zip_rel.as_posix()}!{hit}"
	return paths


def inventory_row(spec: HotaZipUnitSpec, names_ci: dict[str, str], cfg: dict) -> dict:
	zip_rel = faction_zip_rel("neutral" if spec.source == "hota_neutral_zip" else spec.faction)
	battle = find_surface_member(names_ci, spec, "battle")
	amap = find_surface_member(names_ci, spec, "map")
	if battle is None or amap is None:
		missing = []
		if battle is None:
			missing.append("battle")
		if amap is None:
			missing.append("map")
		raise SystemExit(f"{spec.sid}: missing {'/'.join(missing)} sprite member in {zip_rel}")

	battle_kind, battle_member = battle
	map_kind, map_member = amap
	battle_base = pathlib.PurePosixPath(battle_member).stem
	map_base = pathlib.PurePosixPath(map_member).stem
	src_label = {
		"hota_factory_zip": "HotA Factory content.zip",
		"hota_bulwark_zip": "HotA Bulwark content.zip",
		"hota_neutral_zip": "HotA neutralCreatures content.zip",
	}.get(spec.source, spec.source)
	row: dict = {
		"unitSid": spec.sid,
		"comment": f"{spec.faction.title()} unit prepared from {src_label}.",
		"battleExtractBasename": battle_base,
		"mapExtractBasename": map_base,
		"battleZipPath": zip_rel.as_posix(),
		"mapZipPath": zip_rel.as_posix(),
	}
	if battle_kind == "def":
		row["battleZipMember"] = battle_member
	else:
		row["battleJsonZipMember"] = battle_member
		row["battleJsonDirPrefix"] = str(pathlib.PurePosixPath(battle_member).with_suffix(""))
	if map_kind == "def":
		row["mapZipMember"] = map_member
	else:
		row["mapJsonZipMember"] = map_member
		row["mapJsonDirPrefix"] = str(pathlib.PurePosixPath(map_member).with_suffix(""))
	paths = sound_paths_for(spec, names_ci, cfg)
	if paths:
		row["soundPaths"] = paths
	elif spec.sid in (
		"hota_factory_halfling",
		"hota_factory_halfling_grenadier",
	):
		# HotA Factory ship only shot loops for halfings; use classic Heroes3.snd HALF* set.
		row["sndBattlePrefix"] = "HALF"
	return row


def manifest_row(spec: HotaZipUnitSpec) -> dict:
	if spec.faction == "neutral":
		bundle_name = f"custom_units_neutral_{spec.sid}"
	else:
		bundle_name = f"custom_units_{spec.faction}_{spec.sid}"
	return {
		"unitSid": spec.sid,
		"battlePrefabAsset": f"Assets/CustomUnits/homm3_lab/{spec.sid}/battle.prefab",
		"mapPrefabAsset": f"Assets/CustomUnits/homm3_lab/{spec.sid}/map.prefab",
		"bundleName": bundle_name,
	}


def authoring_json(spec: HotaZipUnitSpec, inv_row: dict) -> dict:
	battle_base = inv_row["battleExtractBasename"]
	map_base = inv_row["mapExtractBasename"]
	sid = spec.sid
	return {
		"unitSid": sid,
		"framesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_battle/{battle_base}.dir",
		"templateMaterialPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle_billboard_mesh.mat",
		"battlePrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle.prefab",
		"mapPrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/map.prefab",
		"mapFramesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_map/{map_base}.dir",
		"generatedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim",
		"mapGeneratedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard",
		"mapAnimatorControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard/Homm3MapBillboard.controller",
		"referenceControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Reference/StockEsquireBattle.controller",
		"overrideOutputPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.overrideController",
		"legacyFlatControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.controller",
		"mapFlipBookFps": 10.0,
		"flipBookFps": 12.0,
		"deathClipFps": 10.0,
		"battleQuadLocalScaleX": 13.5,
		"battleQuadLocalScaleY": 12.0,
		"battleQuadLocalScaleZ": 1.0,
		"battleQuadLocalPositionX": 0.75,
		"battleQuadLocalPositionY": 2.01,
		"battleQuadLocalPositionExtraY": 0.0,
		"mapQuadLocalScaleX": 16.0,
		"mapQuadLocalScaleY": 16.0,
		"mapQuadLocalScaleZ": 1.0,
		"mapQuadLocalPositionX": 1.45,
		"mapQuadLocalPositionY": 2.45,
		"generatedClipNamesCsv": "",
	}


def load_config(spec: HotaZipUnitSpec, zf: zipfile.ZipFile, names_ci: dict[str, str]) -> dict:
	member = creature_config_member(spec)
	hit = resolve_member(names_ci, member)
	if hit is None:
		raise SystemExit(f"{spec.sid}: missing config {member}")
	return first_object(loads_jsonc(zf.read(hit).decode("utf-8-sig")))


def validate_and_build_rows(units: tuple[HotaZipUnitSpec, ...]) -> list[tuple[HotaZipUnitSpec, dict]]:
	by_zip: dict[str, list[HotaZipUnitSpec]] = {}
	for spec in units:
		zip_key = faction_zip_rel("neutral" if spec.source == "hota_neutral_zip" else spec.faction).as_posix()
		by_zip.setdefault(zip_key, []).append(spec)

	rows: list[tuple[HotaZipUnitSpec, dict]] = []
	for zip_key, group in by_zip.items():
		zip_path = repo_relative_file(pathlib.PurePosixPath(zip_key))
		if not zip_path.is_file():
			raise SystemExit(f"missing HotA archive: {zip_path}")
		with zipfile.ZipFile(zip_path) as zf:
			names_ci = zip_names_ci(zf)
			for spec in group:
				cfg = load_config(spec, zf, names_ci)
				rows.append((spec, inventory_row(spec, names_ci, cfg)))
	return rows


def update_metadata(units: tuple[HotaZipUnitSpec, ...]) -> list[str]:
	prepared = validate_and_build_rows(units)
	inv = load_json(INVENTORY)
	manifest = load_json(MANIFEST)
	inv_units = inv.setdefault("units", [])
	manifest_units = manifest.setdefault("units", [])
	inv_by_sid = {row.get("unitSid"): row for row in inv_units}
	manifest_by_sid = {row.get("unitSid"): row for row in manifest_units}

	added: list[str] = []
	for spec, desired in prepared:
		if spec.sid not in inv_by_sid:
			inv_units.append(desired)
			added.append(spec.sid)
		else:
			row = inv_by_sid[spec.sid]
			for key in INVENTORY_SOURCE_KEYS:
				if key in desired:
					row[key] = desired[key]
				else:
					row.pop(key, None)
		desired_manifest = manifest_row(spec)
		if spec.sid not in manifest_by_sid:
			manifest_units.append(desired_manifest)
		else:
			manifest_by_sid[spec.sid].update(desired_manifest)
		preset_dir = PRESETS / spec.sid
		preset_dir.mkdir(parents=True, exist_ok=True)
		write_json(preset_dir / "authoring.json", authoring_json(spec, desired))

	write_json(INVENTORY, inv)
	write_json(MANIFEST, manifest)
	UNIT_LIST.write_text("\n".join(spec.sid for spec, _ in prepared) + "\n", encoding="utf-8")
	return added


def run(args: list[str]) -> None:
	print(" ".join(args))
	result = subprocess.run(args, cwd=str(ROOT))
	if result.returncode != 0:
		raise SystemExit(result.returncode)


def extract_and_bootstrap(units: tuple[HotaZipUnitSpec, ...], unity_project: pathlib.Path) -> None:
	project = pathlib.Path(os.path.abspath(unity_project))
	for spec in units:
		run([sys.executable, str(HERE / "extract_creature.py"), "--unit", spec.sid, "--unity-project", str(project)])
		run([sys.executable, str(HERE / "bootstrap_homm3_lab.py"), "--unit", spec.sid, "--unity-project", str(project)])


def select_units(faction: str) -> tuple[HotaZipUnitSpec, ...]:
	if faction == "factory":
		return FACTORY_UNITS
	if faction == "bulwark":
		return BULWARK_UNITS
	if faction == "neutral":
		return NEUTRAL_UNITS
	return ALL_HOTA_ZIP_UNITS


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--faction", choices=("factory", "bulwark", "neutral", "all"), default="all")
	ap.add_argument("--unity-project", type=pathlib.Path, help="Optional Unity project for extract/bootstrap.")
	ap.add_argument("--extract-bootstrap", action="store_true")
	args = ap.parse_args()

	units = select_units(args.faction)
	added = update_metadata(units)
	print(f"Prepared metadata for {len(units)} Factory/Bulwark/neutral unit(s); newly added inventory rows: {len(added)}.")
	print(f"Unit list: {UNIT_LIST}")
	if args.extract_bootstrap:
		if not args.unity_project:
			raise SystemExit("--extract-bootstrap requires --unity-project")
		extract_and_bootstrap(units, args.unity_project)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
