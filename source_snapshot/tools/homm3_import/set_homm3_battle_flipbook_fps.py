#!/usr/bin/env python3
"""Set flipBookFps and deathClipFps to 120 on all HoMM3 lab authoring.json presets (battle RIFE pipeline)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FPS = 120.0


def update_file(path: Path, fps: float, apply: bool) -> bool:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = False
    for key in ("flipBookFps", "deathClipFps"):
        if data.get(key) != fps:
            data[key] = fps
            changed = True
    if changed and apply:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    roots = [
        REPO_ROOT / "tools/homm3_import/presets",
        REPO_ROOT / "tools/homm3_import/example_authoring",
        REPO_ROOT
        / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab",
        REPO_ROOT / "oldenera_factions/Assets/CustomUnits/homm3_lab",
    ]
    touched = 0
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/authoring.json")):
            if update_file(path, args.fps, apply=not args.dry_run):
                print(path.relative_to(REPO_ROOT))
                touched += 1
    print(f"{'Would update' if args.dry_run else 'Updated'} {touched} authoring.json file(s) -> {args.fps} FPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
