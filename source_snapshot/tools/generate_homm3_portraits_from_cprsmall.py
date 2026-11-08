#!/usr/bin/env python3
"""Generate proper army-strip portrait PNGs from HoMM3 CPRSMALL.DEF frames.

CPRSMALL.DEF contains small creature portraits (32x32 px) for all HoMM3 creatures
in order starting from Pikeman (0) through neutral (151).

Correct mapping per HoMM3 creature table:
  Stronghold (frames 84-97):
    84: Goblin           -> h3_goblin
    85: Hobgoblin        -> h3_goblin_upg, h3_goblin_upg_alt
    86: Wolf Rider       -> h3_wolf_rider
    87: Wolf Raider      -> h3_wolf_rider_upg, h3_wolf_rider_upg_alt
    88: Orc              -> h3_orc
    89: Orc Chieftain    -> h3_orc_upg, h3_orc_upg_alt
    90: Ogre             -> h3_ogre
    91: Ogre Mage        -> h3_ogre_upg, h3_ogre_upg_alt
    92: Roc              -> h3_roc
    93: Thunderbird      -> h3_roc_upg, h3_roc_upg_alt
    94: Cyclops          -> h3_cyclops
    95: Cyclops King     -> h3_cyclops_upg, h3_cyclops_upg_alt
    96: Behemoth         -> h3_behemoth
    97: Ancient Behemoth -> h3_behemoth_upg, h3_behemoth_upg_alt
"""

import json
import os
import shutil
import sys

CPRSMALL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted", "cprsmall.dir")

STRONGHOLD_MAP = {
    86: ["h3_goblin"],
    87: ["h3_goblin_upg", "h3_goblin_upg_alt"],
    88: ["h3_wolf_rider"],
    89: ["h3_wolf_rider_upg", "h3_wolf_rider_upg_alt"],
    90: ["h3_orc"],
    91: ["h3_orc_upg", "h3_orc_upg_alt"],
    92: ["h3_ogre"],
    93: ["h3_ogre_upg", "h3_ogre_upg_alt"],
    94: ["h3_roc"],
    95: ["h3_roc_upg", "h3_roc_upg_alt"],
    96: ["h3_cyclops"],
    97: ["h3_cyclops_upg", "h3_cyclops_upg_alt"],
    98: ["h3_behemoth"],
    99: ["h3_behemoth_upg", "h3_behemoth_upg_alt"],
}

def main():
    source_mod_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Heroes of Might & Magic Olden Era Playtest",
        "OfflineUnlockMod",
        "homm3_portraits"
    )
    os.makedirs(source_mod_dir, exist_ok=True)

    new_manifest = {
        "source": "V:\\Games\\Olden Era Playtest Tweak\\HoMM 3 Complete\\Data\\H3sprite.lod",
        "sourceEntry": "cprsmall.def",
        "portraitSize": 256,
        "note": "Regenerated from CPRSMALL.DEF small creature portraits (32x32 px) - Stronghold frames 84-97",
        "sidToDef": {},
        "sidToFrame": {}
    }

    copied = 0
    for frame_idx, sids in sorted(STRONGHOLD_MAP.items()):
        src_file = os.path.join(CPRSMALL_DIR, f"00_{frame_idx:02d}.png")
        if not os.path.exists(src_file):
            print(f"ERROR: source frame {frame_idx} not found at {src_file}", file=sys.stderr)
            continue
        for sid in sids:
            dest_file = os.path.join(source_mod_dir, f"{sid}.png")
            shutil.copy2(src_file, dest_file)
            new_manifest["sidToDef"][sid] = "cprsmall.def"
            new_manifest["sidToFrame"][sid] = frame_idx
            print(f"  {sid}.png <- CPRSMALL frame {frame_idx}")
            copied += 1

    manifest_path = os.path.join(source_mod_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=2, ensure_ascii=False)
    print(f"\nCopied {copied} portrait PNGs -> {source_mod_dir}")
    print(f"Updated manifest -> {manifest_path}")

if __name__ == "__main__":
    main()