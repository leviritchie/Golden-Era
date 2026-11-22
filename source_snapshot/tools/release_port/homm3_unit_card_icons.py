"""Unit card icons for every custom (h3_*) unit row, by the vanilla design language.

Vanilla Olden Era keys each unit card's icon by the card's name SID (the sprite `angel_ability_1_name` is the icon
of the card named `angel_ability_1_name`), and its art splits by kind:

- passives and descriptive traits: understated gold line-glyphs on a navy disc (`*_passive_*_name`,
  `base_passive_*_name`);
- active abilities and alternative attacks: colourful painted discs (`*_ability_*_name`, the battle spell
  paintings `primal_*` / `space_*` / `night_*` / `day_*`, and `common_attack_*_name`).

Custom cards have no sprite of their own, so they carry an explicit `icon`. This pass sets it, last, on every unit
view card of an h3_* row:

1. a card whose name is itself a vanilla card sprite gets that sprite (an explicit icon would override the
   native one; that is how vanilla-named cards ended up with hero-skill or flag icons);
2. otherwise the card's entry (keyed `<section>/<name>`) in `custom_factions/unit_designs/card_icons/card_icons.json`.

`custom_factions/unit_designs/card_icons/card_icon_pools.json` lists the allowed sprites per kind (scanned from the game's
sprite assets with tools/release_port/scan_unit_card_icon_pools.py). The validator
tools/validate_homm3_unit_card_icons.py checks the built Core against both files.

The game resolves an explicit `icon` through a different lookup than the name-keyed card sprites, and that lookup
does not hold them (in game 2026-11-21: every card pointed at `*_passive_*_name` / `*_ability_*_name` drew the orange
placeholder). So the chosen sprite ships as a plugin PNG and the card carries its served key
(`served_key`): the plugin draws any `sub_skill_faction_homm3_*` key that has a PNG in
OfflineUnlockMod/homm3_skill_icons (Homm3FactionSkillIconSpriteCache). export_unit_card_icon_pngs.py writes them.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

REPO = pathlib.Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "custom_factions" / "unit_designs" / "card_icons" / "card_icons.json"
POOLS_PATH = REPO / "custom_factions" / "unit_designs" / "card_icons" / "card_icon_pools.json"
# Our own card art in the same two styles: PNGs the plugin serves by name from OfflineUnlockMod/homm3_skill_icons
# (Homm3FactionSkillIconSpriteCache: any `sub_skill_faction_homm3_*` key with a packaged PNG).
CUSTOM_ART_PATH = REPO / "custom_factions" / "unit_designs" / "card_icons" / "custom_art.json"
CUSTOM_ART_DIR = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_skill_icons"
CUSTOM_ART_PREFIX = "sub_skill_faction_homm3_card_"
SERVED_VANILLA_PREFIX = "sub_skill_faction_homm3_card_v_"


def served_key(sprite: str) -> str:
    """The icon key a card carries for a chosen sprite: our own art as is, a vanilla sprite via its packaged copy."""
    return sprite if sprite.startswith(CUSTOM_ART_PREFIX) else SERVED_VANILLA_PREFIX + sprite
CARD_SECTIONS = ("passives", "abilities", "alternativeAttacks")
PASSIVE_SECTIONS = {"passives"}


def load_custom_art() -> dict[str, list[str]]:
    if not CUSTOM_ART_PATH.is_file():
        return {"glyph": [], "painted": []}
    doc = json.loads(CUSTOM_ART_PATH.read_text(encoding="utf-8"))
    return {"glyph": list(doc.get("glyph") or []), "painted": list(doc.get("painted") or [])}


def load_pools() -> dict[str, set[str]]:
    doc = json.loads(POOLS_PATH.read_text(encoding="utf-8"))
    custom = load_custom_art()
    return {"glyph": set(doc["glyph"]) | set(custom["glyph"]), "painted": set(doc["painted"]) | set(custom["painted"])}


def policy_key(section: str, name: str) -> str:
    # One card name can sit in two sections (a shared melee card is a passive on one unit, an alternative attack
    # on another), and the two take different art, so the policy is keyed by both.
    return section + "/" + name


def load_policy() -> dict[str, str]:
    doc = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy = {key: row["icon"] for key, row in doc["cards"].items()}
    # Staging fragments (card_icons_<lane>.json, same "cards" shape) let parallel lanes add entries without editing
    # the main file; they are folded into card_icons.json when the lanes finish.
    for fragment in sorted(POLICY_PATH.parent.glob("card_icons_*.json")):
        for key, row in json.loads(fragment.read_text(encoding="utf-8"))["cards"].items():
            if policy.setdefault(key, row["icon"]) != row["icon"]:
                raise RuntimeError(f"unit card icons: {fragment.name} maps {key} to {row['icon']}, main policy differs")
    return policy


def pool_for(section: str) -> str:
    return "glyph" if section in PASSIVE_SECTIONS else "painted"


def icon_for(name: str, section: str, pools: dict[str, set[str]], policy: dict[str, str]) -> str | None:
    if name in pools["glyph"] or name in pools["painted"]:
        return name
    return policy.get(policy_key(section, name))


def is_custom_unit_view(path: str, row: dict[str, Any]) -> bool:
    return "/units_views/" in path and str(row.get("id", "")).startswith("h3_")


def apply_card_icons(
    output: dict[str, bytes],
    notes: list[str],
    write_json: Callable[[Any], bytes],
) -> None:
    pools, policy = load_pools(), load_policy()
    changed = cards = 0
    unmapped: set[str] = set()
    for path in sorted(output):
        if "/units_views/" not in path or not path.endswith(".json"):
            continue
        doc = json.loads(output[path].decode("utf-8-sig"))
        rows = doc.get("array") if isinstance(doc, dict) else None
        dirty = False
        for row in rows or []:
            if not isinstance(row, dict) or not is_custom_unit_view(path, row):
                continue
            for section in CARD_SECTIONS:
                for card in row.get(section) or []:
                    if not isinstance(card, dict) or not isinstance(card.get("name"), str):
                        continue
                    cards += 1
                    icon = icon_for(card["name"], section, pools, policy)
                    if icon is None:
                        unmapped.add(policy_key(section, card["name"]))
                        continue
                    icon = served_key(icon)
                    if card.get("icon") != icon:
                        card["icon"] = icon
                        changed += 1
                        dirty = True
        if dirty:
            output[path] = write_json(doc)
    if unmapped:
        raise RuntimeError(f"unit card icons: {len(unmapped)} card(s) with no vanilla sprite and no entry in "
                           f"{POLICY_PATH.name}: {sorted(unmapped)[:20]}")
    notes.append(f"unit card icons: {cards} card(s) on h3_* rows, {changed} icon(s) set from the vanilla card "
                 f"sprites and {POLICY_PATH.name}")
