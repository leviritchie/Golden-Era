#!/usr/bin/env python3
"""Fail if homm3_import.json lab units lack UniverSR unique-clip cache files.

The runtime overlay in Homm3UpscaledBattleSfx is the playback path. Missing catalog
rows or WAVs would silently keep the original 22 kHz bundle clips.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
DEFAULT_SFX = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_upscaled_sfx"
REQUIRED_ROLES = ("attack", "move", "wince", "killed")


def lab_sid_from_prefab(path: str | None) -> str | None:
	if not path:
		return None
	p = path.replace("\\", "/")
	needle = "/homm3_lab/"
	i = p.lower().find(needle)
	if i < 0:
		return None
	rest = p[i + len(needle) :]
	return rest.split("/", 1)[0].strip() or None


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--import-json", type=Path, default=DEFAULT_IMPORT)
	ap.add_argument("--sfx-root", type=Path, default=DEFAULT_SFX)
	args = ap.parse_args()
	errors: list[str] = []
	if not args.import_json.is_file():
		print(f"validate_homm3_upscaled_sfx_contract: missing {args.import_json}", file=sys.stderr)
		return 1
	catalog_path = args.sfx_root / "catalog.json"
	if not catalog_path.is_file():
		print(f"validate_homm3_upscaled_sfx_contract: missing {catalog_path}", file=sys.stderr)
		return 1
	catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
	units = catalog.get("units") if isinstance(catalog, dict) else None
	clips = catalog.get("clips") if isinstance(catalog, dict) else None
	if not isinstance(units, dict) or not isinstance(clips, dict):
		print("validate_homm3_upscaled_sfx_contract: catalog missing units/clips", file=sys.stderr)
		return 1
	table = json.loads(args.import_json.read_text(encoding="utf-8-sig"))
	seen: set[str] = set()
	for entry in table.get("entries") or []:
		if not isinstance(entry, dict):
			continue
		lab_sid = lab_sid_from_prefab(entry.get("battlePrefabAssetPath"))
		if not lab_sid or lab_sid in seen:
			continue
		seen.add(lab_sid)
		roles = units.get(lab_sid)
		if not isinstance(roles, dict):
			errors.append(f"{lab_sid}: missing catalog.units row")
			continue
		for role in REQUIRED_ROLES:
			if lab_sid == "h3_cannon" and role == "move":
				continue
			clip_id = roles.get(role)
			if not isinstance(clip_id, str) or not clip_id:
				errors.append(f"{lab_sid}: missing role {role}")
				continue
			rel = clips.get(clip_id)
			if not isinstance(rel, str) or not rel:
				errors.append(f"{lab_sid}: role {role} clip '{clip_id}' not in catalog.clips")
				continue
			wav = args.sfx_root / rel.replace("/", "\\")
			if not wav.is_file():
				errors.append(f"{lab_sid}: missing WAV {wav}")
	for extra in ("esquire", "esquire_upg"):
		roles = units.get(extra)
		if not isinstance(roles, dict):
			errors.append(f"{extra}: missing catalog.units row")
			continue
		for role in REQUIRED_ROLES:
			clip_id = roles.get(role)
			if not isinstance(clip_id, str) or not clip_id:
				errors.append(f"{extra}: missing role {role}")
				continue
			rel = clips.get(clip_id)
			if not isinstance(rel, str):
				errors.append(f"{extra}: clip '{clip_id}' not in catalog.clips")
				continue
			wav = args.sfx_root / rel.replace("/", "\\")
			if not wav.is_file():
				errors.append(f"{extra}: missing WAV {wav}")
	if errors:
		print("validate_homm3_upscaled_sfx_contract: FAIL", file=sys.stderr)
		for err in errors:
			print(f"  - {err}", file=sys.stderr)
		return 1
	print(f"validate_homm3_upscaled_sfx_contract: OK ({len(seen)} lab units + esquire)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
