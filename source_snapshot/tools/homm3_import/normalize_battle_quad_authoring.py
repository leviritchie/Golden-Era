#!/usr/bin/env python3
"""Normalize lane-B HoMM3 battle quad authoring for 450x400 DEF canvases."""
from __future__ import annotations

import argparse
import json
import pathlib


CANONICAL_BATTLE_QUAD = {
	"battleQuadLocalScaleX": 13.5,
	"battleQuadLocalScaleY": 12.0,
	"battleQuadLocalScaleZ": 1.0,
	"battleQuadLocalPositionX": 0.75,
	"battleQuadLocalPositionY": 2.01,
	"battleQuadLocalPositionExtraY": 0.0,
}


def update_authoring(path: pathlib.Path, apply: bool) -> bool:
	data = json.loads(path.read_text(encoding="utf-8-sig"))
	changed = False
	for key, value in CANONICAL_BATTLE_QUAD.items():
		if data.get(key) != value:
			data[key] = value
			changed = True
	if changed and apply:
		path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
	return changed


def update_prefab(path: pathlib.Path, apply: bool) -> bool:
	if not path.is_file():
		return False
	lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
	changed = False
	in_quad = False
	replaced_pos = False
	replaced_scale = False
	for i, line in enumerate(lines):
		if line.strip() == "m_Name: quad":
			in_quad = True
			continue
		if not in_quad:
			continue
		if not replaced_pos and "m_LocalPosition:" in line:
			new_line = "  m_LocalPosition: {x: 0.75, y: 2.01, z: 0}"
			if lines[i] != new_line:
				lines[i] = new_line
				changed = True
			replaced_pos = True
			continue
		if not replaced_scale and "m_LocalScale:" in line:
			new_line = "  m_LocalScale: {x: 13.5, y: 12, z: 1}"
			if lines[i] != new_line:
				lines[i] = new_line
				changed = True
			replaced_scale = True
		if replaced_pos and replaced_scale:
			break
	if changed and apply:
		path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	return changed


def iter_authoring_files(repo: pathlib.Path) -> list[pathlib.Path]:
	roots = [
		repo / "tools" / "homm3_import" / "presets",
		repo / "tools" / "homm3_import" / "example_authoring",
		repo / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab",
	]
	files: list[pathlib.Path] = []
	for root in roots:
		if root.is_file() and root.name == "authoring.json":
			files.append(root)
		elif root.is_dir():
			files.extend(sorted(root.glob("*/authoring.json")))
			direct = root / "authoring.json"
			if direct.is_file():
				files.append(direct)
	return files


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Normalize HoMM3 lane-B battle quad aspect and foot anchoring."
	)
	parser.add_argument(
		"--repo-root",
		type=pathlib.Path,
		default=pathlib.Path(__file__).resolve().parents[2],
		help="Repository root. Defaults to two levels above this script.",
	)
	parser.add_argument("--apply", action="store_true", help="Write changes instead of reporting a dry run.")
	args = parser.parse_args()

	repo = args.repo_root.resolve()
	authoring_changed = 0
	prefab_changed = 0
	for authoring in iter_authoring_files(repo):
		if update_authoring(authoring, args.apply):
			authoring_changed += 1
			print(f"authoring: {authoring.relative_to(repo)}")
		prefab = authoring.parent / "battle.prefab"
		if update_prefab(prefab, args.apply):
			prefab_changed += 1
			print(f"prefab:    {prefab.relative_to(repo)}")

	mode = "updated" if args.apply else "would update"
	print(f"{mode} {authoring_changed} authoring file(s), {prefab_changed} prefab file(s)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
