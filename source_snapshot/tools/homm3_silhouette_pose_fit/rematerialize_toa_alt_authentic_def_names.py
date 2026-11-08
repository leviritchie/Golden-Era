#!/usr/bin/env python3
"""Rewrite ToA HotA-named 12fps plates to authentic GG_FF.png for pose fit.

Castle alts (battle griffin / justiciar) land from VCMI JSON+PNG with HotA
filenames. inventory_authentic_def_groups only accepts GG_FF.png, so those
labs stay planBlocked. This rematerializes extracted_battle_source_12fps from
the existing sequence JSON without re-pulling the zip.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAB = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "BepInEx"
    / "plugins"
    / "OfflineUnlockMod"
    / "homm3_lab"
)

DEFAULT_UNITS = {
    "h3_battle_griffin": "lvl3Alt",
    "h3_justiciar": "lvl6Alt",
}


def rematerialize(lab: Path, sid: str, basename: str) -> dict:
    src_root = lab / sid / "extracted_battle_source_12fps"
    src_dir = src_root / f"{basename}.dir"
    src_json = src_root / f"{basename}.json"
    if not src_dir.is_dir() or not src_json.is_file():
        raise FileNotFoundError(f"missing {src_dir} or {src_json}")

    payload = json.loads(src_json.read_text(encoding="utf-8-sig"))
    sequences = payload.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        raise RuntimeError(f"{src_json}: no sequences")

    backup = src_root / f"{basename}.dir_hota_names_backup"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(src_dir, backup)

    for path in list(src_dir.iterdir()):
        if path.is_file():
            path.unlink()

    new_sequences: list[dict] = []
    groups_written: dict[int, int] = {}
    written = 0
    for seq in sequences:
        group = int(seq["group"])
        frames = list(seq.get("frames") or [])
        new_frames: list[str] = []
        for frame_i, rel in enumerate(frames):
            name = Path(str(rel).replace("\\", "/")).name
            src = backup / name
            if not src.is_file():
                raise FileNotFoundError(
                    f"{sid} group {group} frame {frame_i}: missing {src}"
                )
            out_name = f"{group:02d}_{frame_i:02d}.png"
            shutil.copy2(src, src_dir / out_name)
            new_frames.append(f"{basename}.dir\\{out_name}")
            written += 1
        groups_written[group] = len(new_frames)
        new_sequences.append({"group": group, "frames": new_frames})

    src_json.write_text(
        json.dumps({"sequences": new_sequences}, indent=4) + "\n",
        encoding="utf-8",
    )
    return {
        "labSid": sid,
        "groups": groups_written,
        "frames": written,
        "backup": str(backup),
        "hasIdleGroup2": 2 in groups_written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=DEFAULT_LAB)
    parser.add_argument(
        "--source-lab",
        type=Path,
        help="Read HotA-named plates from this lab and write GG_FF.png into --lab. "
        "Defaults to --lab (in-place). Do not point --lab at the live Golden Era billboard tree.",
    )
    parser.add_argument(
        "--unit",
        action="append",
        dest="units",
        help="labSid to rematerialize (default: battle griffin + justiciar)",
    )
    parser.add_argument(
        "--basename",
        help="DEF extract basename for a single --unit not in the Castle-alt table",
    )
    args = parser.parse_args()
    lab = args.lab.resolve()
    source_lab = args.source_lab.resolve() if args.source_lab else lab
    if args.basename:
        if not args.units or len(args.units) != 1:
            raise SystemExit("--basename requires exactly one --unit")
        selected = {args.units[0]: args.basename}
    else:
        selected = {
            sid: DEFAULT_UNITS[sid]
            for sid in (args.units or list(DEFAULT_UNITS))
            if sid in DEFAULT_UNITS
        }
    if not selected:
        raise SystemExit("no known units selected")

    if source_lab != lab:
        for sid, basename in selected.items():
            src_root = source_lab / sid / "extracted_battle_source_12fps"
            dest_root = lab / sid / "extracted_battle_source_12fps"
            src_dir = src_root / f"{basename}.dir"
            src_json = src_root / f"{basename}.json"
            if not src_dir.is_dir() or not src_json.is_file():
                raise FileNotFoundError(f"missing {src_dir} or {src_json}")
            dest_root.mkdir(parents=True, exist_ok=True)
            dest_dir = dest_root / f"{basename}.dir"
            dest_json = dest_root / f"{basename}.json"
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(src_dir, dest_dir)
            shutil.copy2(src_json, dest_json)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from materialize_rife_source_frames import inventory_authentic_def_groups

    results = []
    for sid, basename in selected.items():
        result = rematerialize(lab, sid, basename)
        inv = inventory_authentic_def_groups(
            lab / sid / "extracted_battle_source_12fps" / f"{basename}.dir"
        )
        result["inventoryGroups"] = {str(k): len(v) for k, v in inv.items()}
        if 2 not in inv:
            raise RuntimeError(f"{sid}: rematerialize left idle group 2 empty")
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)
    print(json.dumps({"ok": True, "units": len(results)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
