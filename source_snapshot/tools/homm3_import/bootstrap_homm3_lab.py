#!/usr/bin/env python3
"""Copy lane-A esquire prefab/material/controller scaffold into homm3_lab/<unitSid> and install preset authoring.json.

Fully automated CI precondition: the Unity project must already contain Assets/CustomUnits/esquire/ (same as esquire bundle work).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys


def _absolute_no_resolve(path: pathlib.Path) -> pathlib.Path:
	return pathlib.Path(os.path.abspath(path))


def _copy_pair(src: pathlib.Path, dst: pathlib.Path) -> None:
	dst.parent.mkdir(parents=True, exist_ok=True)
	if not src.is_file():
		raise FileNotFoundError(f"bootstrap_homm3_lab: missing source {src}")
	shutil.copy2(src, dst)
	# Never copy the .meta: a copied .meta repeats the donor's GUID, Unity then resolves that GUID to neither file,
	# and every override controller serializing it loads with a null base (the esquire/Crusader dcc84d... collision).
	# Unity assigns the copy a fresh GUID on import; references inside the copied prefab keep pointing at the donor.
	dst_meta = dst.with_name(dst.name + ".meta")
	if dst_meta.is_file() and meta_guid(dst_meta) == meta_guid(src.with_name(src.name + ".meta")):
		raise RuntimeError(f"bootstrap_homm3_lab: {dst_meta} repeats the donor GUID; delete it so Unity assigns a new one")


def meta_guid(meta: pathlib.Path) -> str | None:
	if not meta.is_file():
		return None
	for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
		if line.startswith("guid:"):
			return line.split(":", 1)[1].strip()
	return None


def main() -> int:
	ap = argparse.ArgumentParser(description="Scaffold homm3_lab/<unit> from esquire + preset authoring.")
	ap.add_argument("--unity-project", type=pathlib.Path, required=True, help="Unity project root (ProjectSettings/...)")
	ap.add_argument("--unit", type=str, required=True, help="homm3_lab folder name / unitSid")
	ap.add_argument(
		"--preset-dir",
		type=pathlib.Path,
		default=None,
		help="Folder containing authoring.json (default: <this>/presets/<unit>)",
	)
	args = ap.parse_args()

	project = _absolute_no_resolve(args.unity_project)
	esq = project / "Assets" / "CustomUnits" / "esquire"
	if not esq.is_dir():
		print(f"bootstrap_homm3_lab: esquire lab not found: {esq}", file=sys.stderr)
		return 1

	script_dir = pathlib.Path(__file__).resolve().parent
	preset = _absolute_no_resolve(args.preset_dir) if args.preset_dir else (script_dir / "presets" / args.unit)
	auth_src = preset / "authoring.json"
	if not auth_src.is_file():
		print(f"bootstrap_homm3_lab: no authoring.json in {preset}", file=sys.stderr)
		return 1

	lab = project / "Assets" / "CustomUnits" / "homm3_lab" / args.unit
	ref = lab / "Reference"
	_pairs = [
		(esq / "battle.prefab", lab / "battle.prefab"),
		(esq / "map.prefab", lab / "map.prefab"),
		(esq / "battle_billboard_mesh.mat", lab / "battle_billboard_mesh.mat"),
		(esq / "Reference" / "StockEsquireBattle.controller", ref / "StockEsquireBattle.controller"),
	]

	try:
		for s, d in _pairs:
			_copy_pair(s, d)
		lab.mkdir(parents=True, exist_ok=True)
		shutil.copy2(auth_src, lab / "authoring.json")
	except (OSError, RuntimeError) as ex:
		print("bootstrap_homm3_lab: " + str(ex), file=sys.stderr)
		return 1

	print(f"bootstrap_homm3_lab: OK -> {lab}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
