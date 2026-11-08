#!/usr/bin/env python3
"""
Summarize HoMM3 creature DEF output from tools/defextract_py3.py (or defextract.py).

defextract writes <basename>.json next to <basename>.dir/ with:
  { "sequences": [ { "group": <int>, "frames": [ "basename.dir/GG_FF.png", ... ] }, ... ], ... }

Group indices match the usual HoMM3 / VCMI creature convention:
  https://vcmi.eu/modders/Animation_Format/  (section "Creature animation groups")

Usage:
  python tools/defextract_summarize_groups.py path/to/avwpike.json
  python tools/defextract_summarize_groups.py   # reads avwpike.json from cwd
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# VCMI "Creature animation groups" (same indices as classic H3 .def blocks)
VCMI_CREATURE_GROUP_NAMES: dict[int, str] = {
    0: "Movement",
    1: "Mouse over",
    2: "Idle",
    3: "Hitted",
    4: "Defence",
    5: "Death",
    6: "Death (ranged)",
    7: "Turn left",
    8: "Turn right",
    9: "(unused / reserved)",
    10: "(unused / reserved)",
    11: "Attack (up)",
    12: "Attack (front)",
    13: "Attack (down)",
    14: "Shooting (up)",
    15: "Shooting (front)",
    16: "Shooting (down)",
    17: "Special (up)",
    18: "Special (front)",
    19: "Special (down)",
    20: "Movement start",
    21: "Movement end",
    22: "Dead (corpse pose)",
    23: "Dead ranged",
    24: "Resurrection",
    30: "Cast (up)",
    31: "Cast (front)",
    32: "Cast (down)",
    40: "Group attack (up)",
    41: "Group attack (front)",
    42: "Group attack (down)",
    50: "Teleport start",
    51: "Teleport end",
}


def summarize(data: dict) -> None:
    sequences = data.get("sequences") or []
    if not sequences:
        print("No sequences[] in JSON (empty DEF or wrong file).", file=sys.stderr)
        return

    rows = sorted(sequences, key=lambda s: int(s.get("group", -1)))
    print("group  frames  VCMI / HoMM3 role")
    print("-----  ------  --------------------")
    total = 0
    for seq in rows:
        gid = int(seq["group"])
        frames = seq.get("frames") or []
        n = len(frames)
        total += n
        label = VCMI_CREATURE_GROUP_NAMES.get(gid, f"(unknown group {gid})")
        print(f"{gid:5d}  {n:6d}  {label}")
    print(f"-----  ------")
    print(f"{'ALL':5s}  {total:6d}  concatenated if you sort all PNGs by path")


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: defextract_summarize_groups.py [path/to/basename.json]", file=sys.stderr)
        return 1
    if len(sys.argv) == 2:
        path = Path(sys.argv[1])
    else:
        here = Path.cwd()
        candidates = list(here.glob("*.json"))
        json_files = [p for p in candidates if not p.name.endswith(".meta")]
        if len(json_files) != 1:
            print(
                "Pass explicit JSON path, or run from a folder with exactly one .json (defextract output).",
                file=sys.stderr,
            )
            return 1
        path = json_files[0]

    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    summarize(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
