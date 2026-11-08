#!/usr/bin/env python3
"""Expensive installed Bulwark Runes combat audit (not a normal build step).

Checks installed Core.zip contains the nine incremental Rune buff rows with exact
stat effects. Does not claim user-visible gameplay proof.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


EXPECTED = {
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


def load_buff_rows(core: Path) -> dict[str, dict]:
	with zipfile.ZipFile(core, "r") as zf:
		# Overlay places Rune rows in buffs_night_magics; also scan sub_skills tables.
		candidates = [
			n
			for n in zf.namelist()
			if n.endswith(".json")
			and "buff" in n.lower()
			and ("sub_skills" in n.lower() or "night_magics" in n.lower() or "day_magics" in n.lower())
		]
		found: dict[str, dict] = {}
		for name in candidates:
			try:
				raw = json.loads(zf.read(name).decode("utf-8-sig"))
			except Exception:
				continue
			rows = raw if isinstance(raw, list) else raw.get("list") or raw.get("rows") or raw.get("array") or []
			if not isinstance(rows, list):
				continue
			for row in rows:
				if not isinstance(row, dict):
					continue
				sid = row.get("id") or row.get("sid")
				if isinstance(sid, str) and sid.startswith("homm3_bulwark_rune_level_"):
					found[sid] = row
		return found


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	parser.add_argument(
		"--core",
		type=Path,
		default=Path(
			r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
			r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
		),
	)
	args = parser.parse_args()
	core = args.core.resolve()
	if not core.is_file():
		raise SystemExit(f"missing Core.zip for installed Runes combat audit: {core}")

	found = load_buff_rows(core)
	for level, stats in EXPECTED.items():
		sid = f"homm3_bulwark_rune_level_{level}"
		row = found.get(sid)
		if row is None:
			raise SystemExit(f"installed Core missing {sid}")
		got = ((row.get("data") or {}).get("stats")) or {}
		if got != stats:
			raise SystemExit(f"installed {sid} stats expected {stats}, got {got}")
		tags = row.get("tags") or []
		if "speed" in stats:
			for required in ("movementPositive", "hasteEffect", "haste"):
				if required not in tags:
					raise SystemExit(f"installed {sid} missing speed-donor tag {required}")

	print("validated installed HoMM3 Bulwark Runes Core buff audit")


if __name__ == "__main__":
	main()
