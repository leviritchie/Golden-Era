"""
Create Demon heroes + specializations from Demo dungeon data (Demo Core has no DB/heroes/demon/).

Reads dungeon heroes and specializations_dungeon from the Steam Demo Core.zip, maps Dungeon
creature IDs to Demon tier equivalents, converts faction/skills/mesh/mount/icon strings,
writes DB/heroes/demon/*.json and DB/heroes_specializations/specializations_demon.json into
Playtest Core.zip, and merges Demo English demon_hero_* strings into Playtest heroInfo.json.

Run:
  python generate_demon_heroes.py
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

DEMO_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_HEROINFO_EN = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Lang\english\texts\heroInfo.json"
)
DEMO_HEROINFO_EN = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo"
    r"\HeroesOE_Data\StreamingAssets\Lang\english\texts\heroInfo.json"
)

# Dungeon town creatures (specializations + starting squads) -> Demon counterparts by tier.
UNIT_MAP: dict[str, str] = {
    "trogl": "trick_demon",
    "trogl_upg": "trick_demon_upg",
    "trogl_upg_alt": "trick_demon_upg_alt",
    "assassin": "locust",
    "assassin_upg": "locust_upg",
    "assassin_upg_alt": "locust_upg_alt",
    "blade_dancer": "wasp",
    "blade_dancer_upg": "wasp_upg",
    "blade_dancer_upg_alt": "wasp_upg_alt",
    "medusa": "jaw",
    "medusa_upg": "jaw_upg",
    "medusa_upg_alt": "jaw_upg_alt",
    "minos": "godslayer",
    "minos_upg": "godslayer_upg",
    "minos_upg_alt": "godslayer_upg_alt",
    "hydra": "olgoi",
    "hydra_upg": "olgoi_upg",
    "hydra_upg_alt": "olgoi_upg_alt",
}

TEXT_PREFIX_REPLACEMENTS: list[tuple[str, str]] = [
    ("dungeon_magic_skills_table", "demons_magic_skills_table"),
    ("dungeon_might_skills_table", "demons_might_skills_table"),
    ("dungeon_mage", "hive_mage"),
    ("dungeon_warrior", "hive_warrior"),
    ("dungeon_mount", "hive_mount"),
    ("skill_faction_dungeon", "skill_faction_demons"),
    ("hero_dungeon_", "hero_demon_"),
    ("dungeon_hero_", "demon_hero_"),
]


def remap_unit_strings(obj):
    """Replace Dungeon unit SIDs used in arrays/dicts with Demon tier mappings."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "sid" and isinstance(v, str) and v in UNIT_MAP:
                obj[k] = UNIT_MAP[v]
            else:
                remap_unit_strings(v)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item in UNIT_MAP:
                obj[i] = UNIT_MAP[item]
            else:
                remap_unit_strings(item)


def apply_text_replacements(s: str) -> str:
    for old, new in TEXT_PREFIX_REPLACEMENTS:
        s = s.replace(old, new)
    return s


def morph_hero_record(h: dict) -> None:
    icon_src = h.get("icon")
    h["id"] = apply_text_replacements(h["id"])
    h["specialization"] = apply_text_replacements(h["specialization"])
    h["mesh"] = apply_text_replacements(h["mesh"])
    h["mounts"] = [apply_text_replacements(m) for m in (h.get("mounts") or [])]
    h["icon"] = apply_text_replacements(h["icon"])
    # UI ships portrait sprites as hero_dungeon_*; hero_demon_* are not in the atlas (placeholder art).
    if isinstance(icon_src, str) and icon_src.startswith("hero_dungeon_"):
        h["icon"] = icon_src
    h["fraction"] = "demon"
    if "skillsRollVariant" in h:
        h["skillsRollVariant"] = apply_text_replacements(h["skillsRollVariant"])
    for sk in h.get("startSkills") or []:
        if isinstance(sk, dict) and "sid" in sk:
            sk["sid"] = apply_text_replacements(sk["sid"])
    remap_unit_strings(h.get("startSquad"))
    remap_unit_strings(h.get("startSquadAlt"))


def load_json_from_zip(zpath: Path, inner_path: str) -> dict:
    with zipfile.ZipFile(zpath, "r") as z:
        raw = z.read(inner_path).decode("utf-8-sig")
        return json.loads(raw)


def morph_specializations(data: dict) -> dict:
    out = copy.deepcopy(data)
    for item in out.get("array") or []:
        item["id"] = apply_text_replacements(item["id"])
        item["name"] = apply_text_replacements(item["name"])
        item["desc"] = apply_text_replacements(item["desc"])
        remap_unit_strings(item)
    return out


def rebuild_zip(core_path: Path, updates: dict[str, bytes]) -> None:
    backup = core_path.with_suffix(".zip.bak_before_demon_heroes")
    if not backup.exists():
        backup.write_bytes(core_path.read_bytes())

    with zipfile.ZipFile(core_path, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    all_data.update(updates)

    with zipfile.ZipFile(core_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)


def merge_demon_tokens_into_playtest_english() -> None:
    if not DEMO_HEROINFO_EN.exists():
        raise SystemExit(f"Missing Demo heroInfo: {DEMO_HEROINFO_EN}")
    if not PLAYTEST_HEROINFO_EN.exists():
        raise SystemExit(f"Missing Playtest heroInfo: {PLAYTEST_HEROINFO_EN}")

    demo = json.loads(DEMO_HEROINFO_EN.read_text(encoding="utf-8-sig"))
    pt = json.loads(PLAYTEST_HEROINFO_EN.read_text(encoding="utf-8-sig"))

    demon_tokens = [t for t in demo["tokens"] if t["sid"].startswith("demon_hero")]
    existing = {t["sid"] for t in pt["tokens"]}
    added = [t for t in demon_tokens if t["sid"] not in existing]
    if not added:
        print("Playtest heroInfo.json already contains demon_hero tokens; skipping merge.")
        return

    # Insert before closing bracket of tokens array (keep campaign blocks after demon if any).
    pt["tokens"].extend(added)
    PLAYTEST_HEROINFO_EN.write_text(
        json.dumps(pt, ensure_ascii=False, indent="\t") + "\n",
        encoding="utf-8",
    )
    print(f"Merged {len(added)} demon_hero token(s) into {PLAYTEST_HEROINFO_EN}")


def main() -> None:
    if not DEMO_CORE.exists():
        raise SystemExit(f"Missing Demo Core.zip: {DEMO_CORE}")
    if not PLAYTEST_CORE.exists():
        raise SystemExit(f"Missing Playtest Core.zip: {PLAYTEST_CORE}")

    updates: dict[str, bytes] = {}

    for i in range(1, 19):
        inner = f"DB/heroes/dungeon/dungeon_hero_{i}.json"
        data = load_json_from_zip(DEMO_CORE, inner)
        hero = copy.deepcopy(data["array"][0])
        morph_hero_record(hero)
        raw = json.dumps({"array": [hero]}, ensure_ascii=False, indent="\t").encode("utf-8")
        updates[f"DB/heroes/demon/demon_hero_{i}.json"] = raw

    specs = load_json_from_zip(DEMO_CORE, "DB/heroes_specializations/specializations_dungeon.json")
    demon_specs = morph_specializations(specs)
    updates["DB/heroes_specializations/specializations_demon.json"] = json.dumps(
        demon_specs, ensure_ascii=False, indent="\t"
    ).encode("utf-8")

    rebuild_zip(PLAYTEST_CORE, updates)

    merge_demon_tokens_into_playtest_english()

    print(f"Patched {PLAYTEST_CORE}: 18 demon heroes + specializations_demon.json")
    print(f"Backup (if created): {PLAYTEST_CORE.with_suffix('.zip.bak_before_demon_heroes')}")


if __name__ == "__main__":
    main()
