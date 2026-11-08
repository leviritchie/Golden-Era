"""Pairs for the style comparison: our prebaked HoMM3 unit <-> the closest vanilla Olden Era unit."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/homm3_style_compare"
NATIVE = OUT / "native"
IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
HEX_REPORT = ROOT / "tools/homm3_import/battle_height_hexes_report.json"

# (ours, vanilla prefab under units/, vanilla display name, category, why)
PAIRS = [
    ("h3_pikeman", "humans/1prefabs/esquire", "Esquire", "infantry", "Castle tier-1 foot soldier (our pikeman's donor)"),
    ("h3_crossbowman", "humans/1prefabs/crossbowman", "Crossbowman", "infantry (ranged)", "same role and name"),
    ("h3_crusader", "humans/1prefabs/esquire_upg", "Esquire (upgraded)", "metal-armoured", "plate-armoured swordsman"),
    ("h3_champion", "humans/1prefabs/sunlight_cavalry_upg", "Sunlight Cavalry (upg)", "metal-armoured cavalry",
     "armoured lancer on horseback (our cavalier's donor)"),
    ("h3_griffin", "humans/1prefabs/griffin", "Griffin", "flier", "same creature (our look is a preview, not applied)"),
    ("h3_archangel", "humans/1prefabs/angel_upg", "Angel (upgraded)", "angel", "same creature class"),
    ("h3_giant_upg", "neutral/1prefabs/titan@authored", "Titan (unused prefab)", "large humanoid",
     "same creature; the vanilla Titan prefab ships but no unit view uses it"),
    ("h3_black_dragon", "dungeon/1prefabs/black_dragon_upg", "Black Dragon (upg)", "dragon", "same creature"),
    ("h3_lich", "undead/1prefabs/lich", "Lich", "caster", "same creature, robed spellcaster"),
    ("h3_medusa", "dungeon/1prefabs/medusa", "Medusa", "monster", "same creature"),
    ("h3_minotaur", "dungeon/1prefabs/minos", "Minotaur", "monster", "same creature"),
    ("h3_hydra", "dungeon/1prefabs/hydra", "Hydra", "monster (large)", "same creature"),
]
# vanilla skeleton: the scale anchor write_battle_height_hexes.py names (h3_skeleton lab sid)
SCALE_ANCHOR = ("h3_skeleton", "undead/1prefabs/skeleton")


def native_name(prefab: str) -> str:
    return prefab.removesuffix("@authored").rsplit("/", 1)[-1]


def per_hex() -> float:
    return float(json.loads(IMPORT_TABLE.read_text(encoding="utf-8-sig"))["battleWorldHeightPerHex"])


def hexes(unit: str) -> float:
    rep = json.loads(HEX_REPORT.read_text(encoding="utf-8"))
    rows = [v for v in rep["written"].values() if v["labSid"] == unit]
    if len(rows) != 1:
        raise SystemExit(f"{unit}: expected one battle-height row by labSid, found {len(rows)}")
    return float(rows[0]["battleHeightHexes"])
