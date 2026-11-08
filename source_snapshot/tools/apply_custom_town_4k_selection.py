#!/usr/bin/env python3
"""Apply picker selections.json into clean finals + live town mockups."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "artifacts" / "custom_town_4k_work"
PICKER = WORK / "picker"
FINALS = ROOT / "artifacts" / "custom_town_4k_finals"
TOWN_REFS = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selections",
        type=Path,
        default=PICKER / "selections.json",
        help="JSON map faction -> variant (v1|v2|v3)",
    )
    parser.add_argument("--install", action="store_true", help="Also copy into plugin town_scene_refs")
    args = parser.parse_args()
    if not args.selections.is_file():
        raise SystemExit(f"missing selections file: {args.selections}")
    selections = json.loads(args.selections.read_text(encoding="utf-8"))
    if not isinstance(selections, dict) or not selections:
        raise SystemExit("selections.json must be a non-empty object of faction->variant")
    FINALS.mkdir(parents=True, exist_ok=True)
    applied = {}
    for faction, variant in sorted(selections.items()):
        variant = str(variant).strip().lower()
        if variant not in ("v1", "v2", "v3"):
            raise SystemExit(f"{faction}: invalid variant {variant!r}")
        src = WORK / faction / f"compose_{variant}_3840x2160.png"
        if not src.is_file():
            raise SystemExit(f"missing composed variant: {src}")
        name = f"homm3_{faction}_background_upscaled_3840x2160.png"
        final = FINALS / name
        shutil.copy2(src, final)
        applied[faction] = {"variant": variant, "final": final.as_posix()}
        print(f"{faction}: selected {variant} -> {final.name}")
        if args.install:
            dest = TOWN_REFS / f"homm3_{faction}" / "mockups" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"  installed {dest.relative_to(ROOT).as_posix()}")
    out = PICKER / "applied_selections.json"
    out.write_text(json.dumps(applied, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
