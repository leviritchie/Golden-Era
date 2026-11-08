#!/usr/bin/env python3
"""Audit HoMM3 lab battle animation group selection and override mappings."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys


GROUP_MOVEMENT = 0
GROUP_IDLE = 2
GROUP_HITTED = 3
GROUP_DEATH = 5
GROUP_ATTACK_UP = 11
GROUP_ATTACK_FRONT = 12
GROUP_ATTACK_DOWN = 13
GROUP_SHOOT_UP = 14
GROUP_SHOOT_FRONT = 15
GROUP_SHOOT_DOWN = 16
GROUP_TELEPORT_LEAVE = 20
GROUP_TELEPORT_ARRIVE = 21

MOVEMENT_GROUPS = (GROUP_MOVEMENT, 1, GROUP_IDLE)
MELEE_GROUPS = (GROUP_ATTACK_FRONT, GROUP_ATTACK_UP, GROUP_ATTACK_DOWN)
SHOOT_GROUPS = (GROUP_SHOOT_FRONT, GROUP_SHOOT_UP, GROUP_SHOOT_DOWN)
REQUIRED_GROUPS = (GROUP_IDLE, GROUP_HITTED, GROUP_DEATH)
TELEPORT_DIVE_MOVEMENT_UNITS = {
	"hota_cove_nymph",
	"hota_cove_oceanid",
	"hota_cove_nereid",
}
STOCK_ATTACK_VARIANT_CLIPS = (
	"14.Attack",
	"15.Skill_1",
	"16.Skill_2",
	"17.Skill_3",
	"18.Skill_4",
	"19.Skill_5",
)
STOCK_TELEPORT_CLIPS = (
	"10.Tp_Start",
	"11.Tp_End",
	"12.Tp_Ability_Start",
	"13.Tp_Ability_End",
)
TELEPORT_CLIP_GROUPS = {
	"10.Tp_Start": GROUP_TELEPORT_LEAVE,
	"11.Tp_End": GROUP_TELEPORT_ARRIVE,
	"12.Tp_Ability_Start": GROUP_TELEPORT_LEAVE,
	"13.Tp_Ability_End": GROUP_TELEPORT_ARRIVE,
}


def repo_root() -> pathlib.Path:
	return pathlib.Path(__file__).resolve().parents[2]


def absolute_no_resolve(path: pathlib.Path) -> pathlib.Path:
	return pathlib.Path(os.path.abspath(path))


def asset_to_fs(project: pathlib.Path, asset_path: str) -> pathlib.Path:
	asset_path = (asset_path or "").replace("\\", "/")
	if not asset_path.startswith("Assets/"):
		raise ValueError(f"expected Unity Assets path, got {asset_path!r}")
	return project / asset_path


def load_json(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_json_for_frames_folder(project: pathlib.Path, frames_folder: str) -> pathlib.Path:
	frames_dir = asset_to_fs(project, frames_folder)
	stem = frames_dir.name[:-4] if frames_dir.name.lower().endswith(".dir") else frames_dir.name
	return frames_dir.parent / f"{stem}.json"


def group_counts(def_manifest: dict) -> dict[int, int]:
	counts: dict[int, int] = {}
	for sequence in def_manifest.get("sequences") or []:
		try:
			group = int(sequence.get("group"))
		except (TypeError, ValueError):
			continue
		frames = sequence.get("frames") or []
		counts[group] = len([f for f in frames if str(f or "").strip()])
	return counts


def has_any(counts: dict[int, int], groups: tuple[int, ...]) -> bool:
	return any(counts.get(group, 0) > 0 for group in groups)


def preferred_attack_family(authoring: dict, counts: dict[int, int]) -> tuple[str, tuple[int, ...]]:
	configured = str(authoring.get("battleAttackFamily") or "auto").strip().lower()
	if configured == "melee":
		return "melee", MELEE_GROUPS
	if configured in {"shoot", "ranged", "projectile"}:
		return "shoot", SHOOT_GROUPS
	if configured and configured != "auto":
		return f"auto(unknown:{configured})", SHOOT_GROUPS if has_any(counts, SHOOT_GROUPS) else MELEE_GROUPS
	if has_any(counts, SHOOT_GROUPS):
		return "shoot(auto)", SHOOT_GROUPS
	return "melee(auto)", MELEE_GROUPS


def read_guid(meta_path: pathlib.Path) -> str | None:
	if not meta_path.is_file():
		return None
	for line in meta_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
		line = line.strip()
		if line.startswith("guid:"):
			return line.split(":", 1)[1].strip()
	return None


def override_pairs(path: pathlib.Path) -> list[tuple[str, str]]:
	if not path.is_file():
		return []
	pairs: list[tuple[str, str]] = []
	current: str | None = None
	guid_re = re.compile(r"guid:\s*([0-9a-fA-F]+)")
	for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
		if "m_OriginalClip:" in line:
			match = guid_re.search(line)
			current = match.group(1).lower() if match else None
		elif "m_OverrideClip:" in line and current:
			match = guid_re.search(line)
			if match:
				pairs.append((current, match.group(1).lower()))
			current = None
	return pairs


def object_reference_count(path: pathlib.Path) -> int | None:
	if not path.is_file():
		return None
	text = path.read_text(encoding="utf-8-sig", errors="replace")
	return len(re.findall(r"\{fileID:\s*2100000,\s*guid:", text))


def stock_attack_variant_guids(project: pathlib.Path) -> dict[str, str]:
	etalon = project / "Assets" / "CustomUnits" / "esquire" / "Reference" / "etalon"
	result: dict[str, str] = {}
	for clip_name in STOCK_ATTACK_VARIANT_CLIPS:
		guid = read_guid(etalon / f"{clip_name}.anim.meta")
		if guid:
			result[guid.lower()] = clip_name
	return result


def stock_teleport_guids(project: pathlib.Path) -> dict[str, str]:
	etalon = project / "Assets" / "CustomUnits" / "esquire" / "Reference" / "etalon"
	result: dict[str, str] = {}
	for clip_name in STOCK_TELEPORT_CLIPS:
		guid = read_guid(etalon / f"{clip_name}.anim.meta")
		if guid:
			result[guid.lower()] = clip_name
	return result


def audit_unit(
	project: pathlib.Path,
	unit: str,
	stock_attack_guids: dict[str, str],
	stock_teleport_clip_guids: dict[str, str],
) -> tuple[list[str], list[str]]:
	errors: list[str] = []
	notes: list[str] = []
	lab = project / "Assets" / "CustomUnits" / "homm3_lab" / unit
	authoring_path = lab / "authoring.json"
	if not authoring_path.is_file():
		errors.append(f"{unit}: missing authoring.json under {lab}")
		return errors, notes

	authoring = load_json(authoring_path)
	frames_folder = str(authoring.get("framesFolder") or "")
	def_json = manifest_json_for_frames_folder(project, frames_folder)
	if not def_json.is_file():
		errors.append(f"{unit}: missing defextract JSON beside framesFolder: {def_json}")
		return errors, notes

	counts = group_counts(load_json(def_json))
	missing_required = [group for group in REQUIRED_GROUPS if counts.get(group, 0) <= 0]
	if missing_required:
		errors.append(f"{unit}: missing required battle group(s): {missing_required}")
	if not has_any(counts, MOVEMENT_GROUPS):
		errors.append(f"{unit}: no movement fallback groups found: {list(MOVEMENT_GROUPS)}")
	if unit in TELEPORT_DIVE_MOVEMENT_UNITS:
		missing_teleport = [group for group in (GROUP_TELEPORT_LEAVE, GROUP_TELEPORT_ARRIVE) if counts.get(group, 0) <= 0]
		if missing_teleport:
			errors.append(f"{unit}: missing teleport dive movement group(s): {missing_teleport}")
	if not has_any(counts, MELEE_GROUPS) and not has_any(counts, SHOOT_GROUPS):
		errors.append(f"{unit}: no melee or shooter attack DEF groups found")

	family, preferred_groups = preferred_attack_family(authoring, counts)
	if not has_any(counts, preferred_groups):
		errors.append(f"{unit}: preferred attack family {family} has no frames in groups {list(preferred_groups)}")
	notes.append(
		f"{unit}: attackFamily={family} melee={sum(counts.get(g, 0) for g in MELEE_GROUPS)} "
		f"shoot={sum(counts.get(g, 0) for g in SHOOT_GROUPS)} groups={','.join(str(g) for g in sorted(counts))}"
	)

	generated_clips = lab / "Generated" / "BillboardAnim" / "Clips"
	if unit in TELEPORT_DIVE_MOVEMENT_UNITS and not errors:
		walk_refs = object_reference_count(generated_clips / "01.Walk.anim")
		expected_refs = (counts.get(GROUP_TELEPORT_LEAVE, 0) + counts.get(GROUP_TELEPORT_ARRIVE, 0)) * 2
		if walk_refs is None:
			notes.append(f"{unit}: teleport dive walk-clip audit skipped until generated clips exist")
		elif walk_refs != expected_refs:
			errors.append(
				f"{unit}: 01.Walk does not use teleport dive groups {GROUP_TELEPORT_LEAVE}+{GROUP_TELEPORT_ARRIVE} "
				f"(object refs {walk_refs}, expected {expected_refs})"
			)
		for clip_name, group in TELEPORT_CLIP_GROUPS.items():
			clip_refs = object_reference_count(generated_clips / f"{clip_name}.anim")
			expected_clip_refs = counts.get(group, 0) * 2
			if clip_refs is None:
				errors.append(f"{unit}: missing generated single-phase teleport clip {clip_name}")
			elif clip_refs != expected_clip_refs:
				errors.append(
					f"{unit}: {clip_name} does not use teleport group {group} "
					f"(object refs {clip_refs}, expected {expected_clip_refs})"
				)
	attack_guid = read_guid(generated_clips / "14.Attack.anim.meta")
	melee_alt_guid = read_guid(generated_clips / "15.Skill_1.anim.meta")
	death_guid = read_guid(generated_clips / "21.Death.anim.meta")
	teleport_expected_guids = {
		clip_name: read_guid(generated_clips / f"{clip_name}.anim.meta")
		for clip_name in STOCK_TELEPORT_CLIPS
	}
	override_asset = str(authoring.get("overrideOutputPath") or "")
	override_path = asset_to_fs(project, override_asset) if override_asset else lab / "Generated" / "BillboardAnim" / "Homm3BattleBillboard.overrideController"
	pairs = override_pairs(override_path)
	if attack_guid and death_guid and pairs:
		attack_guid = attack_guid.lower()
		melee_alt_guid = melee_alt_guid.lower() if melee_alt_guid else None
		death_guid = death_guid.lower()
		for original, override in pairs:
			clip_name = stock_attack_guids.get(original)
			if not clip_name:
				continue
			expected_guid = attack_guid
			if (
				clip_name == "15.Skill_1"
				and family.startswith("shoot")
				and has_any(counts, MELEE_GROUPS)
				and melee_alt_guid
			):
				expected_guid = melee_alt_guid
			if override == death_guid:
				errors.append(f"{unit}: stock attack variant {clip_name} overrides to 21.Death")
			elif override != expected_guid:
				errors.append(f"{unit}: stock attack variant {clip_name} overrides to unexpected guid {override}")
		if family.startswith("shoot") and has_any(counts, MELEE_GROUPS) and not melee_alt_guid:
			errors.append(f"{unit}: shooter has melee DEF groups but generated 15.Skill_1 melee alternative clip is missing")
	else:
		notes.append(f"{unit}: override-controller GUID audit skipped until generated clips exist")

	if unit in TELEPORT_DIVE_MOVEMENT_UNITS and all(teleport_expected_guids.values()) and pairs:
		teleport_expected_guids = {k: v.lower() for k, v in teleport_expected_guids.items() if v}
		seen_teleport: set[str] = set()
		for original, override in pairs:
			clip_name = stock_teleport_clip_guids.get(original)
			if not clip_name:
				continue
			seen_teleport.add(clip_name)
			expected_guid = teleport_expected_guids[clip_name]
			if override != expected_guid:
				errors.append(f"{unit}: stock teleport clip {clip_name} overrides to unexpected guid {override}")
		missing = sorted(set(STOCK_TELEPORT_CLIPS) - seen_teleport)
		if missing:
			errors.append(f"{unit}: override controller is missing stock teleport clip(s): {missing}")
	elif unit in TELEPORT_DIVE_MOVEMENT_UNITS:
		errors.append(f"{unit}: teleport override GUID audit skipped because generated teleport clips are missing")

	return errors, notes


def discover_units(project: pathlib.Path) -> list[str]:
	lab_root = project / "Assets" / "CustomUnits" / "homm3_lab"
	if not lab_root.is_dir():
		return []
	return sorted(p.name for p in lab_root.iterdir() if (p / "authoring.json").is_file())


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--unity-project", type=pathlib.Path, default=repo_root() / "oldenera_factions")
	ap.add_argument("--unit", action="append", default=[], help="Unit SID to audit; may be repeated. Defaults to all homm3_lab units.")
	args = ap.parse_args()

	project = absolute_no_resolve(args.unity_project)
	units = args.unit or discover_units(project)
	if not units:
		print("audit_unit_animation_frames: no units selected", file=sys.stderr)
		return 1

	stock_attack_guids = stock_attack_variant_guids(project)
	if not stock_attack_guids:
		print("audit_unit_animation_frames: missing stock etalon attack clip GUIDs", file=sys.stderr)
		return 1
	stock_teleport_clip_guids = stock_teleport_guids(project)
	if not stock_teleport_clip_guids:
		print("audit_unit_animation_frames: missing stock etalon teleport clip GUIDs", file=sys.stderr)
		return 1

	all_errors: list[str] = []
	for unit in units:
		errors, notes = audit_unit(project, unit, stock_attack_guids, stock_teleport_clip_guids)
		for note in notes:
			print(note)
		all_errors.extend(errors)

	if all_errors:
		print("\nAnimation audit failures:", file=sys.stderr)
		for error in all_errors:
			print(f"  - {error}", file=sys.stderr)
		return 1
	print(f"Animation audit OK ({len(units)} unit(s)).")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
