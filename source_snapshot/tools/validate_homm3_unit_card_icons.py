#!/usr/bin/env python3
"""Unit card icons follow the vanilla design language (tools/release_port/homm3_unit_card_icons.py).

Checks custom_factions/unit_designs/card_icons/card_icons.json against card_icon_pools.json (passive cards take a gold glyph,
active cards and alternative attacks a painted icon), and with --core checks every card on every h3_* unit view
row of a built Core: icon present, in the right pool for its section, equal to what the policy says.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "release_port"))
import homm3_unit_card_icons as cards_mod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core")
    args = parser.parse_args()
    pools = cards_mod.load_pools()
    doc = json.loads(cards_mod.POLICY_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key, row in doc["cards"].items():
        section, _, name = key.partition("/")
        if section not in cards_mod.CARD_SECTIONS:
            errors.append(f"policy {key}: key must be <section>/<card name>")
            continue
        row = dict(row, section=section)
        want = cards_mod.pool_for(row["section"])
        if row["icon"] not in pools[want]:
            errors.append(f"policy {name}: {row['section']} card icon {row['icon']} is not in the {want} pool")
        if name in pools["glyph"] or name in pools["painted"]:
            errors.append(f"policy {name}: the card has its own vanilla sprite; drop the entry")
    for kind, names in cards_mod.load_custom_art().items():
        for name in names:
            if not name.startswith(cards_mod.CUSTOM_ART_PREFIX):
                errors.append(f"custom art {name}: key must start with {cards_mod.CUSTOM_ART_PREFIX} (the plugin serves that prefix)")
            png = cards_mod.CUSTOM_ART_DIR / f"{name}.png"
            if not png.is_file():
                errors.append(f"custom art {name}: missing {png}")
    policy = cards_mod.load_policy()
    used: set[str] = set()
    checked = 0
    if args.core:
        with zipfile.ZipFile(args.core) as core:
            for path in core.namelist():
                if "/units_views/" not in path or not path.endswith(".json"):
                    continue
                for row in json.loads(core.read(path).decode("utf-8-sig")).get("array") or []:
                    if not isinstance(row, dict) or not cards_mod.is_custom_unit_view(path, row):
                        continue
                    for section in cards_mod.CARD_SECTIONS:
                        for card in row.get(section) or []:
                            if not isinstance(card, dict):
                                continue
                            checked += 1
                            name, icon = card.get("name"), card.get("icon")
                            used.add(cards_mod.policy_key(section, name))
                            expected = cards_mod.icon_for(name, section, pools, policy)
                            where = f"{row['id']} {section} {name}"
                            if expected is None:
                                errors.append(f"{where}: no vanilla sprite and no policy entry")
                            elif expected not in pools[cards_mod.pool_for(section)]:
                                errors.append(f"{where}: {section} card uses {expected}, outside the "
                                              f"{cards_mod.pool_for(section)} pool")
                            elif icon != cards_mod.served_key(expected):
                                errors.append(f"{where}: icon {icon}, policy says {cards_mod.served_key(expected)}")
                            elif not (cards_mod.CUSTOM_ART_DIR / f"{icon}.png").is_file():
                                # The game cannot draw a card sprite through an explicit icon; the plugin PNG must ship.
                                errors.append(f"{where}: no packaged PNG for {icon} in {cards_mod.CUSTOM_ART_DIR.name}")
        stale = sorted(set(doc["cards"]) - used)
        if stale:
            errors.append(f"policy entries no card uses: {stale[:20]}")
    for line in errors[:60]:
        print("homm3-unit-card-icons:", line, file=sys.stderr)
    if errors:
        print(f"homm3-unit-card-icons: FAIL ({len(errors)} problem(s))", file=sys.stderr)
        return 1
    print(f"homm3-unit-card-icons: OK ({len(doc['cards'])} policy card(s), {checked} built card(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
