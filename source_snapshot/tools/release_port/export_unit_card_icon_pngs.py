#!/usr/bin/env python3
"""Package the vanilla sprites the unit card icon policy picks as plugin PNGs (see homm3_unit_card_icons.py).

The game cannot draw a name-keyed card sprite through a card's explicit `icon`, so every chosen vanilla sprite ships
as OfflineUnlockMod/homm3_skill_icons/<served key>.png, which the plugin serves by key. Reads the sprites from the
game's assets (UnityPy), resizes to 128 px like the other packaged ability icons, and removes packaged copies the
policy no longer uses.

  python tools/release_port/export_unit_card_icon_pngs.py --game-data "<game>/HeroesOldenEra_Data"
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import homm3_unit_card_icons as cards_mod  # noqa: E402

SIZE = 128


def wanted_sprites() -> set[str]:
    """Policy picks. Cards that carry a vanilla card name use that sprite too: pass those with --names (the
    validator's --core run names any that lack a PNG)."""
    doc = json.loads(cards_mod.POLICY_PATH.read_text(encoding="utf-8"))
    return {row["icon"] for row in doc["cards"].values() if not row["icon"].startswith(cards_mod.CUSTOM_ART_PREFIX)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-data", required=True, type=pathlib.Path)
    ap.add_argument("--names", type=pathlib.Path, help="extra sprite names, one per line (vanilla-named cards)")
    args = ap.parse_args()
    import UnityPy
    from PIL import Image

    want = wanted_sprites()
    if args.names:
        want |= {ln.strip() for ln in args.names.read_text(encoding="utf-8").splitlines() if ln.strip()}
    out_dir = cards_mod.CUSTOM_ART_DIR
    found: set[str] = set()
    files = sorted(glob.glob(str(args.game_data / "resources.assets")) + glob.glob(str(args.game_data / "sharedassets*.assets")))
    for f in files:
        env = UnityPy.load(f)
        for obj in env.objects:
            if obj.type.name != "Sprite":
                continue
            try:
                name = obj.peek_name()
            except Exception:  # noqa: BLE001 - some objects cannot be peeked
                continue
            if name not in want or name in found:
                continue
            image = obj.read().image.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
            image.save(out_dir / f"{cards_mod.served_key(name)}.png", optimize=True)
            found.add(name)
    missing = sorted(want - found)
    keep = {cards_mod.served_key(n) + ".png" for n in want}
    removed = 0
    for png in out_dir.glob(cards_mod.SERVED_VANILLA_PREFIX + "*.png"):
        if png.name not in keep:
            png.unlink()
            removed += 1
    print(f"exported {len(found)} card sprite(s), removed {removed} stale; missing {missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
