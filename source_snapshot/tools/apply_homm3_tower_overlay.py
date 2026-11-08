#!/usr/bin/env python3
"""Integrate the reviewed HoMM3 Tower overlay into a local Core.zip/Lang tree.

This is intentionally narrower than the Stronghold generator. Tower data still
comes from experiments/homm3_tower/generated_core_overlay, while this script
adds the live Core registration rows that the overlay lane deliberately omitted.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "HeroesOE_Data"
    / "StreamingAssets"
    / "Core.zip"
)
DEFAULT_LANG = DEFAULT_CORE.parent / "Lang"
DEFAULT_OVERLAY = ROOT / "experiments" / "homm3_tower" / "generated_core_overlay"
TOWER_MANIFEST = ROOT / "custom_factions" / "homm3_tower.json"
TOWER_HERO_OVERRIDE = ROOT / "custom_factions" / "hero_overrides" / "homm3_tower.json"

FRACTION_ID = "homm3_tower"
CITY_ID = "homm3_tower_city"
FRACTION_JSON = "DB/fractions/10_homm3_tower.json"
CITY_JSON = f"DB/objects_logic/cities/{CITY_ID}.json"

HUMAN_TO_TOWER_BASE = {
    "esquire": "h3_gremlin",
    "crossbowman": "h3_gargoyle",
    "griffin": "h3_golem",
    "lightweaver": "h3_mage",
    "sunlight_cavalry": "h3_genie",
    "inquisitor": "h3_naga",
    "angel": "h3_giant",
}

TOWER_ARTIFICE_CONSTRUCT_RECEIVERS = (
    "h3_gremlin",
    "h3_gremlin_upg",
    "h3_gargoyle",
    "h3_gargoyle_upg",
    "h3_golem",
    "h3_golem_upg",
)

TOWER_ARTIFICE_SCALING = ("0.20", "0.40", "0.60")
TOWER_ARTIFICE_SUBSKILLS_BY_LEVEL = {
    2: (
        "sub_skill_faction_homm3_tower_construct_offense",
        "sub_skill_faction_homm3_tower_construct_defense",
    ),
    3: (
        "sub_skill_faction_homm3_tower_expert_construct_offense",
        "sub_skill_faction_homm3_tower_expert_construct_defense",
        "sub_skill_faction_homm3_tower_arcane_workshop",
    ),
}

def tower_native_biome() -> str:
    with TOWER_MANIFEST.open("r", encoding="utf-8-sig") as f:
        manifest = json.load(f)
    identity = manifest.get("identity") or {}
    native_biome = identity.get("nativeBiome")
    if not isinstance(native_biome, str) or not native_biome:
        raise ValueError(f"{TOWER_MANIFEST}: identity.nativeBiome is required")
    return native_biome


TOWER_NATIVE_BIOME = tower_native_biome()


def tower_hero_count() -> int:
    with TOWER_MANIFEST.open("r", encoding="utf-8-sig") as f:
        manifest = json.load(f)
    return int((manifest.get("heroes") or {}).get("count") or 16)


def tower_hero_lang_rows() -> list[tuple[str, str]]:
    with TOWER_HERO_OVERRIDE.open("r", encoding="utf-8-sig") as f:
        override = json.load(f)
    hero_overrides = override.get("heroOverrides")
    if not isinstance(hero_overrides, dict):
        raise ValueError(f"{TOWER_HERO_OVERRIDE}: heroOverrides object is required")

    rows: list[tuple[str, str]] = []
    for index in range(1, tower_hero_count() + 1):
        hero_sid = f"homm3_tower_hero_{index}"
        entry = hero_overrides.get(hero_sid)
        if not isinstance(entry, dict):
            raise ValueError(f"{TOWER_HERO_OVERRIDE}: missing {hero_sid}")
        name = entry.get("nameText")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{TOWER_HERO_OVERRIDE}: {hero_sid} is missing nameText")
        rows.append((hero_sid, name.strip()))
        rows.append((f"{hero_sid}_name", name.strip()))

        spec = entry.get("specialization")
        spec_name = spec.get("nameText") if isinstance(spec, dict) else None
        if not isinstance(spec_name, str) or not spec_name.strip():
            raise ValueError(f"{TOWER_HERO_OVERRIDE}: {hero_sid} specialization is missing nameText")
        rows.append((f"{hero_sid}_specialization", spec_name.strip()))
    return rows


def read_json_bytes(data: bytes) -> Any:
    return json.loads(data.decode("utf-8-sig"))


def write_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent="\t", ensure_ascii=False) + "\n").encode("utf-8")


def read_zip_json(zf: zipfile.ZipFile, name: str) -> Any:
    return read_json_bytes(zf.read(name))


def remap_string(value: str) -> str:
    if value.startswith("human_hero_"):
        rest = value[len("human_hero_") :]
        if rest and rest[0].isdigit():
            return "homm3_tower_hero_" + rest
    if value.startswith("hero_human_"):
        rest = value[len("hero_human_") :]
        return "hero_homm3_tower_" + rest
    if value.startswith("sub_class_human_"):
        return "sub_class_homm3_tower_" + value[len("sub_class_human_") :]
    if value.startswith("humans_"):
        return "homm3_tower_" + value[len("humans_") :]
    if value.startswith("arenaGame_humans_"):
        return "arenaGame_homm3_tower_" + value[len("arenaGame_humans_") :]
    if value == "human":
        return FRACTION_ID
    if value == "human_city":
        return CITY_ID
    if value == "squads_human":
        return "squads_homm3_tower"
    if value == "skill_faction_humans":
        return "skill_faction_homm3_tower"
    if value.startswith("squad_human"):
        return "squad_homm3_tower" + value[len("squad_human") :]
    if value.startswith("barracks_human_"):
        return "barracks_homm3_tower_" + value.rsplit("_", 1)[-1]
    for human, tower in HUMAN_TO_TOWER_BASE.items():
        for suffix in ("_upg_alt", "_upg", ""):
            source = human + suffix
            target = tower + suffix
            if value == source:
                return target
    return value


def remap_value(value: Any) -> Any:
    if isinstance(value, str):
        return remap_string(value)
    if isinstance(value, list):
        return [remap_value(item) for item in value]
    if isinstance(value, dict):
        return {key: remap_value(item) for key, item in value.items()}
    return value


def upsert_array_row(doc: dict[str, Any], row: dict[str, Any], id_key: str = "id") -> bool:
    rows = doc.get("array")
    if not isinstance(rows, list):
        rows = []
        doc["array"] = rows
    row_id = row.get(id_key)
    if not isinstance(row_id, str):
        raise ValueError("row lacks string " + id_key)
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get(id_key) == row_id:
            if existing == row:
                return False
            rows[index] = row
            return True
    rows.append(row)
    return True


def dedupe_array_rows_by_id(doc: dict[str, Any], id_key: str = "id") -> bool:
    rows = doc.get("array")
    if not isinstance(rows, list):
        return False
    seen: set[str] = set()
    output: list[Any] = []
    changed = False
    for row in reversed(rows):
        if isinstance(row, dict) and isinstance(row.get(id_key), str):
            row_id = row[id_key]
            if row_id in seen:
                changed = True
                continue
            seen.add(row_id)
        output.append(row)
    if changed:
        output.reverse()
        doc["array"] = output
    return changed


def upsert_data_entry(container: dict[str, Any], key: str, value: Any) -> bool:
    array = container.get("array")
    if not isinstance(array, dict):
        return False
    rows = array.get("data")
    if not isinstance(rows, list):
        rows = []
        array["data"] = rows
    for row in rows:
        if isinstance(row, dict) and row.get("key") == key:
            if row.get("val") == value:
                return False
            row["val"] = value
            return True
    rows.append({"key": key, "val": value})
    return True


def tower_building_icon_key(building_sid: str, level: int) -> str:
    return f"homm3_tower_building_{building_sid}_level_{max(1, level)}"


def normalize_tower_city_icons(doc: Any) -> Any:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            sid = value.get("sid")
            icons = value.get("icons")
            if isinstance(sid, str) and sid.startswith("Build_") and isinstance(icons, list):
                names = value.get("names")
                descriptions = value.get("descriptions")
                count = max(
                    len(icons),
                    len(names) if isinstance(names, list) else 0,
                    len(descriptions) if isinstance(descriptions, list) else 0,
                )
                value["icons"] = [tower_building_icon_key(sid, index + 1) for index in range(count)]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(doc)
    return doc


def normalize_tower_skill_refs(value: Any) -> Any:
    if isinstance(value, str):
        return "skill_faction_homm3_tower" if value == "skill_faction_humans" else value
    if isinstance(value, list):
        return [normalize_tower_skill_refs(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_tower_skill_refs(item) for key, item in value.items()}
    return value


def normalize_tower_faction_skill(tower: dict[str, Any]) -> dict[str, Any]:
    tower["id"] = "skill_faction_homm3_tower"
    tower["name"] = "skill_faction_homm3_tower_name"
    tower["desc"] = "skill_faction_homm3_tower_desc"
    for index, level in enumerate(tower.get("parametersPerLevel") or [], start=1):
        if not isinstance(level, dict):
            continue
        scale = TOWER_ARTIFICE_SCALING[min(index, len(TOWER_ARTIFICE_SCALING)) - 1]
        level["icon"] = f"skill_faction_homm3_tower_{index}" if index > 1 else "skill_faction_homm3_tower"
        level["name"] = f"skill_faction_homm3_tower_name_{index}"
        level["desc"] = f"skill_faction_homm3_tower_desc_{index}"
        level["bonuses"] = [
            {
                "type": "unitStat",
                "receivers": list(TOWER_ARTIFICE_CONSTRUCT_RECEIVERS),
                "parameters": ["heroSpellPowerModifier", scale],
            },
            {
                "type": "unitStat",
                "receivers": list(TOWER_ARTIFICE_CONSTRUCT_RECEIVERS),
                "parameters": ["heroIntelligenceModifier", scale],
            },
        ]
        level["subSkills"] = list(TOWER_ARTIFICE_SUBSKILLS_BY_LEVEL.get(index, ()))
    return tower


def make_tower_artifice_subskills() -> list[dict[str, Any]]:
    receivers = list(TOWER_ARTIFICE_CONSTRUCT_RECEIVERS)
    return [
        {
            "id": "sub_skill_faction_homm3_tower_construct_offense",
            "name": "sub_skill_faction_homm3_tower_construct_offense_name",
            "desc": "sub_skill_faction_homm3_tower_construct_offense_desc",
            "icon": "skill_faction_homm3_tower_2",
            "bonuses": [
                {"type": "unitStat", "receivers": receivers, "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"]}
            ],
        },
        {
            "id": "sub_skill_faction_homm3_tower_construct_defense",
            "name": "sub_skill_faction_homm3_tower_construct_defense_name",
            "desc": "sub_skill_faction_homm3_tower_construct_defense_desc",
            "icon": "skill_faction_homm3_tower_3",
            "bonuses": [
                {"type": "unitStat", "receivers": receivers, "parameters": ["heroIntelligenceModifier", "0.20"]}
            ],
        },
        {
            "id": "sub_skill_faction_homm3_tower_expert_construct_offense",
            "name": "sub_skill_faction_homm3_tower_expert_construct_offense_name",
            "desc": "sub_skill_faction_homm3_tower_expert_construct_offense_desc",
            "icon": "skill_faction_homm3_tower_2",
            "bonuses": [
                {"type": "unitStat", "receivers": receivers, "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"]}
            ],
        },
        {
            "id": "sub_skill_faction_homm3_tower_expert_construct_defense",
            "name": "sub_skill_faction_homm3_tower_expert_construct_defense_name",
            "desc": "sub_skill_faction_homm3_tower_expert_construct_defense_desc",
            "icon": "skill_faction_homm3_tower_3",
            "bonuses": [
                {"type": "unitStat", "receivers": receivers, "parameters": ["heroIntelligenceModifier", "0.20"]}
            ],
        },
        {
            "id": "sub_skill_faction_homm3_tower_arcane_workshop",
            "name": "sub_skill_faction_homm3_tower_arcane_workshop_name",
            "desc": "sub_skill_faction_homm3_tower_arcane_workshop_desc",
            "icon": "skill_faction_homm3_tower",
            "bonuses": [
                {"type": "cityUnitsIncrement", "parameters": ["1", "2"]},
                {"type": "cityUnitsIncrement", "parameters": ["2", "1"]},
                {"type": "cityUnitsIncrement", "parameters": ["3", "1"]},
            ],
        },
    ]


def normalize_tower_hero_doc(doc: Any, target: str) -> Any:
    item = doc.get("array", [None])[0] if isinstance(doc, dict) and isinstance(doc.get("array"), list) else None
    if not isinstance(item, dict):
        return normalize_tower_skill_refs(doc)
    try:
        hero_index = int(Path(target).stem.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        hero_index = None
    if hero_index is not None:
        item["id"] = f"homm3_tower_hero_{hero_index}"
        item["icon"] = f"hero_homm3_tower_{hero_index}"
        item["name"] = f"homm3_tower_hero_{hero_index}_name"
        item["classType"] = "might" if hero_index <= 8 else "magic"
        item["skillsRollVariant"] = "homm3_tower_might_skills_table" if hero_index <= 8 else "homm3_tower_magic_skills_table"
    item["fraction"] = FRACTION_ID
    item["nativeBiome"] = TOWER_NATIVE_BIOME
    return normalize_tower_skill_refs(doc)


def normalize_tower_skill_table(doc: Any) -> Any:
    return normalize_tower_skill_refs(doc)


def add_tower_to_data_json(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/data.json"
    data = read_zip_json(zf, name)
    changed = False
    for key in ("fractions", "availableFractions"):
        values = list(data.get(key) or [])
        if FRACTION_ID not in values:
            values.append(FRACTION_ID)
            data[key] = values
            changed = True
    if changed:
        overlay[name] = write_json_bytes(data)
        notes.append("merge DB/data.json Tower registration")


def add_city_map_object(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/map/objects/4_interactables.json"
    doc = read_zip_json(zf, name)
    human_row = None
    for row in doc.get("array", []):
        if isinstance(row, dict) and row.get("id") == "human_city":
            human_row = row
            break
    if human_row is None:
        notes.append("warn missing human_city map object donor")
        return
    tower_row = remap_value(copy.deepcopy(human_row))
    tower_row["id"] = CITY_ID
    tower_row["prefs"] = ["interactive/castle"]
    changed = upsert_array_row(doc, tower_row)
    changed = dedupe_array_rows_by_id(doc) or changed
    if changed:
        overlay[name] = write_json_bytes(doc)
        notes.append("merge map interactable " + CITY_ID)


def add_barracks_map_objects(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/map/objects/4_interactables.json"
    doc = read_json_bytes(overlay[name]) if name in overlay else read_zip_json(zf, name)
    changed = False
    for tier in range(1, 8):
        donor_id = f"barracks_homm3_stronghold_{tier}"
        donor = next(
            (row for row in doc.get("array", []) if isinstance(row, dict) and row.get("id") == donor_id),
            None,
        )
        if donor is None:
            donor_id = f"barracks_human_{tier}"
            donor = next(
                (row for row in doc.get("array", []) if isinstance(row, dict) and row.get("id") == donor_id),
                None,
            )
        if donor is None:
            notes.append("warn missing map donor " + donor_id)
            continue
        tower = remap_value(copy.deepcopy(donor))
        tower["id"] = f"barracks_homm3_tower_{tier}"
        tower["prefs"] = [f"barracks/barracks_dungeon_{tier}"]
        changed = upsert_array_row(doc, tower) or changed
    changed = dedupe_array_rows_by_id(doc) or changed
    if changed:
        overlay[name] = write_json_bytes(doc)
        notes.append("merge Tower external barracks map objects")


def add_barracks(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/objects_logic/hires/barracks.json"
    doc = read_zip_json(zf, name)
    changed = False
    for tier in range(1, 8):
        donor_id = f"barracks_human_{tier}"
        donor = next(
            (row for row in doc.get("array", []) if isinstance(row, dict) and row.get("id") == donor_id),
            None,
        )
        if donor is None:
            notes.append("warn missing " + donor_id)
            continue
        tower = remap_value(copy.deepcopy(donor))
        tower["id"] = f"barracks_homm3_tower_{tier}"
        tower["fraction"] = FRACTION_ID
        changed = upsert_array_row(doc, tower) or changed
    changed = dedupe_array_rows_by_id(doc) or changed
    if changed:
        overlay[name] = write_json_bytes(doc)
        notes.append("merge Tower external barracks")


def add_tower_faction_skill(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/heroes_skills/skills/skills.json"
    doc = read_json_bytes(overlay[name]) if name in overlay else read_zip_json(zf, name)
    donor = next(
        (row for row in doc.get("array", []) if isinstance(row, dict) and row.get("id") == "skill_faction_humans"),
        None,
    )
    if donor is None:
        notes.append("warn missing skill_faction_humans donor")
        return
    tower = normalize_tower_faction_skill(normalize_tower_skill_refs(copy.deepcopy(donor)))
    changed = upsert_array_row(doc, tower)
    changed = dedupe_array_rows_by_id(doc) or changed
    if changed:
        overlay[name] = write_json_bytes(doc)
        notes.append("merge Tower faction skill")

    subskills_name = "DB/heroes_skills/sub_skills/sub_skills.json"
    subskills_doc = read_json_bytes(overlay[subskills_name]) if subskills_name in overlay else read_zip_json(zf, subskills_name)
    subskills_changed = False
    for row in make_tower_artifice_subskills():
        subskills_changed = upsert_array_row(subskills_doc, row) or subskills_changed
    subskills_changed = dedupe_array_rows_by_id(subskills_doc) or subskills_changed
    if subskills_changed:
        overlay[subskills_name] = write_json_bytes(subskills_doc)
        notes.append("merge Tower Artifice subskills")


def clone_json_members(
    zf: zipfile.ZipFile,
    overlay: dict[str, bytes],
    notes: list[str],
    prefix: str,
    target_prefix: str,
) -> None:
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir() or not name.startswith(prefix) or not name.endswith(".json"):
            continue
        target = target_prefix + name[len(prefix) :].replace("squad_human", "squad_homm3_tower")
        doc = remap_value(read_zip_json(zf, name))
        if target == CITY_JSON:
            doc = normalize_tower_city_icons(doc)
        overlay[target] = write_json_bytes(doc)
    notes.append("clone " + prefix + " -> " + target_prefix)


def clone_audio_rows(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    for name in ("DB/city_ambient_sounds.json", "DB/city_music_sounds.json"):
        doc = read_zip_json(zf, name)
        human_val = None
        for row in (doc.get("array") or {}).get("data", []):
            if isinstance(row, dict) and row.get("key") == "human":
                human_val = copy.deepcopy(row.get("val"))
                break
        if human_val is None:
            notes.append("warn missing human audio donor in " + name)
            continue
        if name.endswith("city_music_sounds.json"):
            # Sidecar Homm3StrongholdCityMusic owns Tower town BGM. Point SessionCity at the
            # faction key (Stronghold pattern), not the human donor set, or both tracks layer.
            human_val["soundSetName"] = "sounds/city/music/" + FRACTION_ID
        if upsert_data_entry(doc, FRACTION_ID, human_val):
            overlay[name] = write_json_bytes(doc)
            notes.append("merge " + name + " Tower row")


def clone_map_object_sound(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    name = "DB/map_objects_sounds.json"
    doc = read_zip_json(zf, name)
    rows = (doc.get("objectsArr") or {}).get("data", [])
    donor = next((row.get("val") for row in rows if isinstance(row, dict) and row.get("key") == "human_city"), None)
    if donor is None:
        notes.append("warn missing human_city map sound donor")
        return
    existing = next((row for row in rows if isinstance(row, dict) and row.get("key") == CITY_ID), None)
    if existing is not None and existing.get("val") == donor:
        return
    if existing is not None:
        existing["val"] = copy.deepcopy(donor)
    else:
        rows.append({"key": CITY_ID, "val": copy.deepcopy(donor)})
    overlay[name] = write_json_bytes(doc)
    notes.append("merge map object sound " + CITY_ID)


def clone_hero_scaffolding(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir() or not name.endswith(".json"):
            continue
        if name.startswith("DB/heroes/humans/human_hero_"):
            target = "DB/heroes/homm3_tower/" + Path(name).name.replace("human_hero_", "homm3_tower_hero_")
        elif name == "DB/heroes_sub_classes/sub_classes_human.json":
            target = "DB/heroes_sub_classes/sub_classes_homm3_tower.json"
        elif name == "DB/heroes_specializations/specializations_human.json":
            target = "DB/heroes_specializations/specializations_homm3_tower.json"
        elif name == "DB/heroes_skills/skills_by_level_tables/humans_might_skills_table.json":
            target = "DB/heroes_skills/skills_by_level_tables/homm3_tower_might_skills_table.json"
        elif name == "DB/heroes_skills/skills_by_level_tables/humans_magic_skills_table.json":
            target = "DB/heroes_skills/skills_by_level_tables/homm3_tower_magic_skills_table.json"
        elif name == "DB/heroes_skills/skills_by_level_tables/arenaGame_humans_might_skills_table.json":
            target = "DB/heroes_skills/skills_by_level_tables/arenaGame_homm3_tower_might_skills_table.json"
        elif name == "DB/heroes_skills/skills_by_level_tables/arenaGame_humans_magic_skills_table.json":
            target = "DB/heroes_skills/skills_by_level_tables/arenaGame_homm3_tower_magic_skills_table.json"
        else:
            continue
        doc = remap_value(read_zip_json(zf, name))
        if target.startswith("DB/heroes/homm3_tower/homm3_tower_hero_"):
            doc = normalize_tower_hero_doc(doc, target)
        elif target.startswith("DB/heroes_skills/skills_by_level_tables/homm3_tower_") or target.startswith(
            "DB/heroes_skills/skills_by_level_tables/arenaGame_homm3_tower_"
        ):
            doc = normalize_tower_skill_table(doc)
        overlay[target] = write_json_bytes(doc)
    notes.append("clone Human hero scaffolding -> homm3_tower")


def upsert_lang_row(rows: list[Any], sid: str, text: str) -> bool:
    updated = False
    for row in rows:
        if isinstance(row, dict) and row.get("sid") == sid:
            if row.get("text") != text:
                row["text"] = text
                updated = True
            updated = True
            continue
    if updated:
        return True
    rows.append({"sid": sid, "text": text})
    return True


# Lang members vanilla Core does not ship; the mod creates them (the release overlay also writes units.json).
MOD_OWNED_LANG_MEMBERS = frozenset({"Lang/english/texts/heroes.json", "Lang/english/texts/units.json"})


def merge_lang_overlay_into_core(
    zf: zipfile.ZipFile, overlay: dict[str, bytes], overlay_root: Path, notes: list[str]
) -> None:
    """--core-lang: upsert the Tower Lang overlay into Core's own Lang members.

    The installed Golden Era Core carries these rows because the release overlay once imported this
    overlay (Lang included) before its own rows; that import was removed in 96ecea8ff2, and this layer
    only wrote a loose playtest Lang dir, so a Core rebuilt from vanilla lacked the Tower unit ability
    names. Runs before add_tower_hero_lang so the manifest hero rows, and later the release overlay's
    own rows, still win. Every target member must already exist except MOD_OWNED_LANG_MEMBERS."""
    source_root = overlay_root / "Lang"
    if not source_root.is_dir():
        raise RuntimeError(f"Tower Lang overlay missing: {source_root}")
    names = set(zf.namelist())
    for source in sorted(source_root.rglob("*.json")):
        rel = "Lang/" + source.relative_to(source_root).as_posix()
        sid_to_text = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(sid_to_text, dict):
            raise RuntimeError(f"unsupported Tower Lang overlay {source}")
        if rel in overlay:
            doc = read_json_bytes(overlay[rel])
        elif rel in names:
            doc = read_zip_json(zf, rel)
        elif rel in MOD_OWNED_LANG_MEMBERS:
            doc = {"tokens": []}
            notes.append("create mod-owned " + rel)
        else:
            raise RuntimeError(f"Tower Lang overlay target {rel} is not in Core.zip")
        rows = doc.get("tokens")
        if not isinstance(rows, list):
            raise RuntimeError(f"{rel}: tokens is not a list")
        changed = False
        for sid, text in sid_to_text.items():
            changed = upsert_lang_row(rows, sid, text) or changed
        if changed:
            overlay[rel] = write_json_bytes(doc)
            notes.append("merge Tower Lang overlay into Core " + rel)


def add_tower_hero_lang(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    hero_rows = tower_hero_lang_rows()
    hero_info_name = "Lang/english/texts/heroInfo.json"
    hero_name = "Lang/english/texts/heroes.json"
    changed_any = False
    for name in (hero_name, hero_info_name):
        changed = False
        if name in overlay:
            doc = read_json_bytes(overlay[name])
        elif name == hero_name and name not in zf.namelist():
            # Lang/english/texts/heroes.json is a mod-owned member: vanilla Core
            # ships no such file (heroInfo.json holds vanilla hero text). On a
            # vanilla rebuild this layer is the first writer, so it creates it.
            # heroInfo.json stays required.
            doc = {"tokens": []}
            notes.append("create mod-owned " + name)
        else:
            doc = read_zip_json(zf, name)
        rows = doc.get("tokens")
        if not isinstance(rows, list):
            rows = []
            doc["tokens"] = rows
        for sid, text in hero_rows:
            if name == hero_info_name and sid.endswith("_specialization"):
                continue
            changed = upsert_lang_row(rows, sid, text) or changed
        if changed:
            overlay[name] = write_json_bytes(doc)
            changed_any = True
    if changed_any:
        notes.append("merge Tower hero name localization")


def clone_building_presets(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    for name in (
        "DB/buildings_bans/M2_banlists.json",
        "DB/buildings_bans/M10_banlists.json",
        "DB/buildings_constructions/M2_buildings_presets.json",
        "DB/buildings_constructions/M10_buildings_presets.json",
    ):
        doc = read_zip_json(zf, name)
        text = json.dumps(doc)
        if "human_city" not in text:
            continue
        remapped = remap_value(copy.deepcopy(doc))
        if remapped != doc:
            # Keep donor rows and add Tower rows by merging arrays with ids.
            merged = copy.deepcopy(doc)
            if isinstance(doc.get("array"), list) and isinstance(remapped.get("array"), list):
                for row in remapped["array"]:
                    if isinstance(row, dict) and CITY_ID in json.dumps(row):
                        upsert_array_row(merged, row)
                overlay[name] = write_json_bytes(merged)
                notes.append("merge " + name + " Tower city rows")


TOWER_UNIT_LOGIC_PREFIX = "DB/units/units_logics/homm3_tower/"


def strip_static_trace_debt(doc: Any, rel: str) -> bool:
    """Drop xHomm3ReleaseQuality.staticTraceDebt from a generated Tower unit logic row.

    tools/quality_pass_homm3_tower_overlay.py records static-trace debts as review
    metadata in experiments/homm3_tower/generated_core_overlay. Final Core rows must
    not carry design-debt keys (validate_custom_faction_manifests.py --no-design-debt).
    apply_release_core_overlay.py stripped them while it still imported this overlay
    (removed in 96ecea8ff2); this layer now owns the import, so it owns the strip.
    """
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise RuntimeError(f"Tower unit logic overlay {rel} has no array row")
    quality = rows[0].get("xHomm3ReleaseQuality")
    if isinstance(quality, dict) and "staticTraceDebt" in quality:
        quality.pop("staticTraceDebt")
        return True
    return False


def overlay_files(overlay_root: Path, overlay: dict[str, bytes], notes: list[str]) -> None:
    stripped = 0
    for source in sorted((overlay_root / "DB").rglob("*.json")):
        rel = source.relative_to(overlay_root).as_posix()
        if rel == CITY_JSON:
            overlay[rel] = write_json_bytes(normalize_tower_city_icons(read_json_bytes(source.read_bytes())))
        elif rel.startswith(TOWER_UNIT_LOGIC_PREFIX) and rel.endswith("_l.json"):
            doc = read_json_bytes(source.read_bytes())
            if strip_static_trace_debt(doc, rel):
                stripped += 1
                overlay[rel] = write_json_bytes(doc)
            else:
                overlay[rel] = source.read_bytes()
        else:
            overlay[rel] = source.read_bytes()
    notes.append("copy reviewed Tower DB overlay")
    if stripped:
        notes.append(f"strip staticTraceDebt review metadata from {stripped} Tower unit logic row(s)")


def merge_lang_file(target: Path, sid_to_text: dict[str, str]) -> bool:
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    else:
        data = {"tokens": []}
    rows = data.get("tokens")
    if not isinstance(rows, list):
        rows = []
        data["tokens"] = rows
    by_sid = {row.get("sid"): row for row in rows if isinstance(row, dict)}
    changed = False
    for sid, text in sid_to_text.items():
        row = by_sid.get(sid)
        if row is None:
            rows.append({"sid": sid, "text": text})
            changed = True
        elif row.get("text") != text:
            row["text"] = text
            changed = True
    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return changed


def merge_lang_overlay(overlay_root: Path, lang_root: Path, dry_run: bool, notes: list[str]) -> None:
    source_root = overlay_root / "Lang"
    if not source_root.is_dir():
        return
    for source in sorted(source_root.rglob("*.json")):
        rel = source.relative_to(source_root)
        sid_to_text = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(sid_to_text, dict):
            notes.append("warn unsupported Tower Lang overlay " + str(source))
            continue
        target = lang_root / rel
        if dry_run:
            notes.append("would merge Lang/" + rel.as_posix())
        elif merge_lang_file(target, sid_to_text):
            notes.append("merge Lang/" + rel.as_posix())


INFO_SCRIPT_HUMAN = "DB/info/info_script_unit/units_human.script"
INFO_SCRIPT_TOWER = "DB/info/info_script_unit/units_homm3_tower.script"


def clone_info_script(zf: zipfile.ZipFile, overlay: dict[str, bytes], notes: list[str]) -> None:
    """Clone units_human.script -> units_homm3_tower.script, renaming each unic_unit_<donorBase>_
    function to the Tower line's base sid (manifest unitLines). The unit info panel resolves its
    parameter functions by unit sid and renders blank without them. The installed Golden Era Core
    carries this member, but no source layer generated it, so a vanilla rebuild lacked it."""
    with TOWER_MANIFEST.open("r", encoding="utf-8-sig") as f:
        lines = json.load(f)["unitLines"]
    raw = zf.read(INFO_SCRIPT_HUMAN).decode("utf-8-sig")
    for line in lines:
        donor, base = str(line["donorBaseSid"]), str(line["baseSid"])
        raw = re.sub(rf"\bunic_unit_{re.escape(donor)}_", f"unic_unit_{base}_", raw)
    if "unic_unit_h3_" not in raw:
        raise RuntimeError(f"{INFO_SCRIPT_HUMAN}: no Tower donor function was renamed")
    overlay[INFO_SCRIPT_TOWER] = raw.encode("utf-8")
    notes.append(f"clone {INFO_SCRIPT_HUMAN} -> {INFO_SCRIPT_TOWER}")


def build_core_overlay(
    core: Path, overlay_root: Path, core_lang: bool = False
) -> tuple[dict[str, bytes], list[str]]:
    output: dict[str, bytes] = {}
    notes: list[str] = []
    with zipfile.ZipFile(core) as zf:
        overlay_files(overlay_root, output, notes)
        add_tower_to_data_json(zf, output, notes)
        add_city_map_object(zf, output, notes)
        add_barracks_map_objects(zf, output, notes)
        add_barracks(zf, output, notes)
        add_tower_faction_skill(zf, output, notes)
        clone_json_members(zf, output, notes, "DB/squads/squads_human/", "DB/squads/squads_homm3_tower/")
        clone_hero_scaffolding(zf, output, notes)
        if core_lang:
            merge_lang_overlay_into_core(zf, output, overlay_root, notes)
        add_tower_hero_lang(zf, output, notes)
        clone_audio_rows(zf, output, notes)
        clone_map_object_sound(zf, output, notes)
        clone_building_presets(zf, output, notes)
        clone_info_script(zf, output, notes)
    return output, notes


def rewrite_zip(core: Path, overlay: dict[str, bytes], dry_run: bool) -> Path | None:
    if dry_run:
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = core.with_name(core.name + ".backup-before-homm3-tower-" + timestamp)
    shutil.copy2(core, backup)
    with tempfile.TemporaryDirectory(prefix="homm3-tower-core-") as tmp:
        tmp_zip = Path(tmp) / core.name
        with zipfile.ZipFile(core, "r") as src, zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            written = set()
            for info in src.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir():
                    dst.writestr(info, b"")
                    continue
                if name.startswith("DB/squads/squads_homm3_tower/") and "squad_human" in name:
                    continue
                if name in overlay:
                    dst.writestr(name, overlay[name])
                else:
                    dst.writestr(info, src.read(info.filename))
                written.add(name)
            for name, data in sorted(overlay.items()):
                if name not in written:
                    dst.writestr(name, data)
        shutil.move(str(tmp_zip), core)
    return backup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--lang", type=Path, default=None, help=f"Loose Lang dir (default {DEFAULT_LANG}).")
    parser.add_argument(
        "--core-lang",
        action="store_true",
        help="Merge the Tower Lang overlay into Core.zip's Lang members instead of a loose Lang dir "
        "(used by tools/port_current/rebuild_core_from_vanilla.py); cannot combine with --lang.",
    )
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    core = args.core.resolve()
    if args.core_lang and args.lang is not None:
        raise SystemExit("--core-lang writes Lang into Core.zip; do not also pass --lang")
    overlay_root = args.overlay.resolve()
    overlay, notes = build_core_overlay(core, overlay_root, core_lang=args.core_lang)
    if not args.core_lang:
        lang = (args.lang if args.lang is not None else DEFAULT_LANG).resolve()
        merge_lang_overlay(overlay_root, lang, args.dry_run, notes)
    print(f"Prepared {len(overlay)} Core.zip member update(s).")
    for note in notes[:160]:
        print(note)
    if len(notes) > 160:
        print(f"... {len(notes) - 160} more")
    backup = rewrite_zip(core, overlay, args.dry_run)
    if args.dry_run:
        print("Dry run only; Core.zip/Lang were not modified.")
    else:
        print("Updated " + str(core))
        print("Backup: " + str(backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
