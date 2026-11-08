"""
homm3_fortress — debug faction: a perfect clone of Dungeon under new ids (same unit SIDs,
same meshes, same city scene, same laws shape). Use this to bisect what breaks vs the HoMM3
Stronghold pipeline (h3_* units, remapped hires, etc.).

Default branding:
* Fraction homm3_fortress, city homm3_fortress_city, squads_homm3_fortress, squad_homm3_fortress_*

--raw: Dungeon-parallel **id strings** for stress-testing (globally unique but grep-close):
* dungeon_raw, dungeon_city_raw, squads_dungeon_raw, squad_dungeon_raw_*, fraction_law_dungeon_raw_*
  (Still runs the **full** clone pipeline: 4_interactables + map/city audio + M2/M10 + squads + Lang —
  same class of fixes as homm3_stronghold; "raw" does **not** mean skipping those steps.)

After Core:
  python generate_homm3_fortress_heroes.py [--raw]

Run:
  python generate_homm3_fortress_city.py
  python generate_homm3_fortress_city.py --raw
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_ROOT = CORE.parents[2]


@dataclass(frozen=True)
class CityProfile:
    fraction_id: str
    city_id: str
    city_config_id: str
    fraction_json_path: str
    laws_json_path: str
    law_id_full_prefix: str  # e.g. fraction_law_homm3_fortress or fraction_law_dungeon_raw
    squads_folder: str
    squad_id_new_prefix: str
    backup_suffix: str
    lang_fraction_name: str
    lang_fraction_desc: str
    lang_city_name: str
    lang_city_desc: str
    lang_city_narrative: str
    lang_map_desc: str
    lang_map_narrative: str


def _profile_default() -> CityProfile:
    return CityProfile(
        fraction_id="homm3_fortress",
        city_id="homm3_fortress_city",
        city_config_id="homm3_fortress_city",
        fraction_json_path="DB/fractions/8_homm3_fortress.json",
        laws_json_path="DB/fractions_laws/fractions_laws_table_homm3_fortress.json",
        law_id_full_prefix="fraction_law_homm3_fortress",
        squads_folder="squads_homm3_fortress",
        squad_id_new_prefix="squad_homm3_fortress_",
        backup_suffix="bak_before_homm3_fortress_city",
        lang_fraction_name="Fortress (Dungeon clone)",
        lang_fraction_desc=(
            "Debug faction: same creatures, stats, and town as Dungeon; only internal ids differ."
        ),
        lang_city_name="Fortress Town",
        lang_city_desc="Clone of Dungeon for regression testing.",
        lang_city_narrative=(
            "Uses Dungeon scene and units; use this to isolate HoMM3 Stronghold-specific breakage."
        ),
        lang_map_desc="Dungeon-equivalent town (debug clone).",
        lang_map_narrative="Fortress (homm3_fortress) mirrors Dungeon behavior.",
    )


def _profile_raw() -> CityProfile:
    return CityProfile(
        fraction_id="dungeon_raw",
        city_id="dungeon_city_raw",
        city_config_id="dungeon_city_raw",
        fraction_json_path="DB/fractions/9_dungeon_raw.json",
        laws_json_path="DB/fractions_laws/fractions_laws_table_dungeon_raw.json",
        law_id_full_prefix="fraction_law_dungeon_raw",
        squads_folder="squads_dungeon_raw",
        squad_id_new_prefix="squad_dungeon_raw_",
        backup_suffix="bak_before_dungeon_raw_city",
        lang_fraction_name="Dungeon (raw ids)",
        lang_fraction_desc=(
            "Debug clone: Dungeon-parallels ids (dungeon_raw, …) for stepwise id bisect."
        ),
        lang_city_name="Dungeon town (raw)",
        lang_city_desc="dungeon_city clone with *_raw ids.",
        lang_city_narrative="Stress-test build; compare to Dungeon / homm3_fortress.",
        lang_map_desc="Dungeon-equivalent (raw id clone).",
        lang_map_narrative="dungeon_raw city entry (debug).",
    )


def _profile_raw_exact_city_id() -> CityProfile:
    p = _profile_raw()
    return CityProfile(
        fraction_id=p.fraction_id,
        city_id=p.city_id,
        city_config_id="dungeon_city",
        fraction_json_path=p.fraction_json_path,
        laws_json_path=p.laws_json_path,
        law_id_full_prefix=p.law_id_full_prefix,
        squads_folder=p.squads_folder,
        squad_id_new_prefix=p.squad_id_new_prefix,
        backup_suffix="bak_before_dungeon_raw_exact_city_id",
        lang_fraction_name=p.lang_fraction_name,
        lang_fraction_desc=p.lang_fraction_desc,
        lang_city_name=p.lang_city_name,
        lang_city_desc=p.lang_city_desc,
        lang_city_narrative=p.lang_city_narrative,
        lang_map_desc=p.lang_map_desc,
        lang_map_narrative=p.lang_map_narrative,
    )


FRACTION_ID = ""
CITY_ID = ""
CITY_CONFIG_ID = ""
FRACTION_JSON_PATH = ""
LAWS_JSON_PATH = ""
CITY_JSON_PATH = ""
UNITS_LOGIC_DIR = ""
UNITS_VIEW_DIR = ""
LAW_ID_FULL_PREFIX = ""
SQUADS_CLONE_PREFIX = ""
SQUAD_ID_PREFIX_CLONE = ""
_CURRENT_PROFILE: CityProfile | None = None


def install_city_profile(p: CityProfile) -> None:
    """Bind module globals used by all patch steps."""
    global FRACTION_ID, CITY_ID, CITY_CONFIG_ID, FRACTION_JSON_PATH, LAWS_JSON_PATH, CITY_JSON_PATH
    global UNITS_LOGIC_DIR, UNITS_VIEW_DIR, LAW_ID_FULL_PREFIX
    global SQUADS_CLONE_PREFIX, SQUAD_ID_PREFIX_CLONE, _CURRENT_PROFILE
    _CURRENT_PROFILE = p
    FRACTION_ID = p.fraction_id
    CITY_ID = p.city_id
    CITY_CONFIG_ID = p.city_config_id
    FRACTION_JSON_PATH = p.fraction_json_path
    LAWS_JSON_PATH = p.laws_json_path
    CITY_JSON_PATH = f"DB/objects_logic/cities/{CITY_ID}.json"
    UNITS_LOGIC_DIR = f"DB/units/units_logics/{FRACTION_ID}"
    UNITS_VIEW_DIR = f"DB/units/units_views/{FRACTION_ID}"
    LAW_ID_FULL_PREFIX = p.law_id_full_prefix
    SQUADS_CLONE_PREFIX = f"DB/squads/{p.squads_folder}/"
    SQUAD_ID_PREFIX_CLONE = p.squad_id_new_prefix


install_city_profile(_profile_default())

LANG_ROOT = PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang"
ARGS_FACTION_LAWS_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "factionLaws.json"
)


def morph_unit_logic_identity(data: dict, sid: str) -> None:
    a = data["array"][0]
    a["id"] = sid
    a["fraction"] = FRACTION_ID
    tags = a.get("tags")
    if isinstance(tags, list):
        a["tags"] = [FRACTION_ID if t == "dungeon" else t for t in tags]


def morph_unit_view_identity(data: dict, sid: str) -> None:
    a = data["array"][0]
    a["id"] = sid


def copy_all_units_from_dungeon(all_data: dict) -> None:
    """Deep-copy every dungeon unit JSON into homm3_fortress dirs; SIDs unchanged."""
    dungeon_logic_prefix = "DB/units/units_logics/dungeon/"
    for old_path, blob in list(all_data.items()):
        if not old_path.startswith(dungeon_logic_prefix) or not old_path.endswith("_l.json"):
            continue
        old_sid = old_path[len(dungeon_logic_prefix) : -len("_l.json")]
        v_path = f"DB/units/units_views/dungeon/{old_sid}_v.json"
        if v_path not in all_data:
            continue
        logic = json.loads(blob.decode("utf-8-sig"))
        view = json.loads(all_data[v_path].decode("utf-8-sig"))
        morph_unit_logic_identity(logic, old_sid)
        morph_unit_view_identity(view, old_sid)
        all_data[f"{UNITS_LOGIC_DIR}/{old_sid}_l.json"] = json.dumps(
            logic, ensure_ascii=False, indent="\t"
        ).encode("utf-8")
        all_data[f"{UNITS_VIEW_DIR}/{old_sid}_v.json"] = json.dumps(
            view, ensure_ascii=False, indent="\t"
        ).encode("utf-8")


def clone_city_from_dungeon(all_data: dict) -> dict:
    raw = all_data["DB/objects_logic/cities/dungeon_city.json"].decode("utf-8-sig")
    root = json.loads(raw)
    city = copy.deepcopy(root["array"][0])
    city["id"] = CITY_CONFIG_ID
    city["fraction"] = FRACTION_ID
    # Do not string-replace "dungeon_city" -> CITY_ID on json text: for CITY_ID like
    # "dungeon_city_raw", the result still contains substring "dungeon_city" and would
    # become "dungeon_city_raw_raw" (breaks map object / session / town UI).
    return city


def remap_law_bonus_identity(obj: object) -> None:
    """Only flip embedded faction dungeon -> homm3_fortress; unit SIDs stay trogl/…."""
    if isinstance(obj, dict):
        if obj.get("fraction") == "dungeon":
            obj["fraction"] = FRACTION_ID
        for v in obj.values():
            remap_law_bonus_identity(v)
    elif isinstance(obj, list):
        for it in obj:
            remap_law_bonus_identity(it)


def clone_dungeon_laws(all_data: dict) -> dict:
    laws = json.loads(all_data["DB/fractions_laws/fractions_laws_table_dungeon.json"].decode("utf-8-sig"))
    out = copy.deepcopy(laws)
    for law in out["array"]:
        old_id = law["id"]
        m = re.match(r"^fraction_law_dungeon_(\d+)$", old_id)
        if not m:
            raise RuntimeError(f"Unexpected law id: {old_id}")
        n = m.group(1)
        law["id"] = f"{LAW_ID_FULL_PREFIX}_{n}"
        law["name"] = f"{LAW_ID_FULL_PREFIX}_{n}_name"
        law["desc"] = f"{LAW_ID_FULL_PREFIX}_{n}_desc"
        remap_law_bonus_identity(law)
    return out


def clone_fraction_config(all_data: dict) -> dict:
    d = json.loads(all_data["DB/fractions/3_dungeon.json"].decode("utf-8-sig"))
    frac = copy.deepcopy(d["array"][0])
    frac["id"] = FRACTION_ID
    frac["name"] = f"{FRACTION_ID}_name"
    frac["desc"] = f"{FRACTION_ID}_desc"
    frac["narrativeDesc"] = f"{FRACTION_ID}_desc"
    frac["icon"] = "fraction_dungeon"
    frac["iconFractionLaws"] = "Scroll_Faction_Dungeon"
    frac["cityNames"] = [f"{CITY_ID}_name_{i}" for i in range(1, 21)]

    def remap_law_line_refs(obj: object) -> None:
        if isinstance(obj, str):
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "laws" and isinstance(v, list):
                    obj[k] = [
                        re.sub(
                            r"^fraction_law_dungeon_",
                            f"{LAW_ID_FULL_PREFIX}_",
                            x,
                        )
                        if isinstance(x, str)
                        else x
                        for x in v
                    ]
                else:
                    remap_law_line_refs(v)
        elif isinstance(obj, list):
            for it in obj:
                remap_law_line_refs(it)

    remap_law_line_refs(frac.get("fractionLawsLines"))
    return {"array": [frac]}


def upsert_text_tokens(path: Path, updates: dict[str, str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    tokens = payload.setdefault("tokens", [])
    by_sid = {token["sid"]: token for token in tokens if "sid" in token}
    for sid, text in updates.items():
        if sid in by_sid:
            by_sid[sid]["text"] = text
        else:
            tokens.append({"sid": sid, "text": text})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def upsert_args_tokens(path: Path, new_sids: list[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list}
    for sid in new_sids:
        old = sid.replace(f"{LAW_ID_FULL_PREFIX}_", "fraction_law_dungeon_")
        if old not in by_sid:
            continue
        if sid not in by_sid:
            args_list.append({"sid": sid, "args": copy.deepcopy(by_sid[old]["args"])})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_faction_law_text_from_dungeon(faction_laws_path: Path) -> dict[str, str]:
    eng = json.loads(faction_laws_path.read_text(encoding="utf-8-sig"))
    by_sid = {t["sid"]: t["text"] for t in eng.get("tokens", []) if "sid" in t}
    out: dict[str, str] = {}
    for i in range(1, 34):
        for suffix in ("_name", "_desc"):
            old = f"fraction_law_dungeon_{i}{suffix}"
            new = f"{LAW_ID_FULL_PREFIX}_{i}{suffix}"
            if old in by_sid:
                out[new] = by_sid[old]
    return out


def list_lang_locales() -> list[str]:
    if not LANG_ROOT.is_dir():
        return []
    out: list[str] = []
    for p in sorted(LANG_ROOT.iterdir()):
        if not p.is_dir():
            continue
        if (p / "texts" / "cities.json").is_file():
            out.append(p.name)
    return out


def collect_dungeon_city_name_templates(cities_path: Path, city_id: str) -> dict[str, str]:
    eng = json.loads(cities_path.read_text(encoding="utf-8-sig"))
    by_sid = {t["sid"]: t["text"] for t in eng.get("tokens", []) if "sid" in t}
    out: dict[str, str] = {}
    for i in range(1, 21):
        old = f"dungeon_city_name_{i}"
        new = f"{city_id}_name_{i}"
        if old in by_sid:
            out[new] = by_sid[old]
    return out


def patch_localization() -> None:
    locales = list_lang_locales()
    if not locales:
        print("Lang: no locales under", LANG_ROOT)
        return

    for locale in locales:
        texts = LANG_ROOT / locale / "texts"
        cities_path = texts / "cities.json"
        dungeon_city_name = collect_dungeon_city_name_templates(cities_path, CITY_ID)

        pr = _CURRENT_PROFILE
        if pr is None:
            raise RuntimeError("install_city_profile() before patch_localization")
        cities_updates: dict[str, str] = {
            f"{FRACTION_ID}_name": pr.lang_fraction_name,
            f"{FRACTION_ID}_desc": pr.lang_fraction_desc,
            f"{CITY_ID}_name": pr.lang_city_name,
            f"{CITY_ID}_description": pr.lang_city_desc,
            f"{CITY_ID}_narrativeDescription": pr.lang_city_narrative,
            **dungeon_city_name,
        }
        if CITY_CONFIG_ID != CITY_ID:
            # Bisect mode: the cloned raw city keeps config id "dungeon_city" but still uses
            # raw city-name tokens for generated town names. LocKit asks for the config id
            # directly in some UI paths, so provide aliases instead of changing the city data.
            cities_updates.update(
                {
                    CITY_CONFIG_ID: pr.lang_city_name,
                    f"{CITY_CONFIG_ID}_name": pr.lang_city_name,
                    f"{CITY_CONFIG_ID}_description": pr.lang_city_desc,
                    f"{CITY_CONFIG_ID}_narrativeDescription": pr.lang_city_narrative,
                }
            )

        upsert_text_tokens(cities_path, cities_updates)

        fl_path = texts / "factionLaws.json"
        if fl_path.is_file():
            law_text = build_faction_law_text_from_dungeon(fl_path)
            upsert_text_tokens(fl_path, law_text)

    new_arg_sids = [f"{LAW_ID_FULL_PREFIX}_{i}_desc" for i in range(1, 34)]
    upsert_args_tokens(ARGS_FACTION_LAWS_PATH, new_arg_sids)

    for locale in locales:
        texts = LANG_ROOT / locale / "texts"
        mo = texts / "mapObjects.json"
        if mo.is_file():
            pr = _CURRENT_PROFILE
            upsert_text_tokens(
                mo,
                {
                    f"{CITY_ID}_name": pr.lang_city_name,
                    f"{CITY_ID}_description": pr.lang_map_desc,
                    f"{CITY_ID}_narrativeDescription": pr.lang_map_narrative,
                    **(
                        {
                            CITY_CONFIG_ID: pr.lang_city_name,
                            f"{CITY_CONFIG_ID}_name": pr.lang_city_name,
                            f"{CITY_CONFIG_ID}_description": pr.lang_map_desc,
                            f"{CITY_CONFIG_ID}_narrativeDescription": pr.lang_map_narrative,
                        }
                        if CITY_CONFIG_ID != CITY_ID
                        else {}
                    ),
                },
            )

    print(f"Lang: patched locales {', '.join(locales)} under {LANG_ROOT}.")


def patch_interactables_city(all_data: dict) -> None:
    path = "DB/map/objects/4_interactables.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    arr = root["array"]
    ids = {o.get("id") for o in arr if isinstance(o, dict)}
    if CITY_ID in ids:
        return
    dungeon_entry = next(o for o in arr if isinstance(o, dict) and o.get("id") == "dungeon_city")
    clone = copy.deepcopy(dungeon_entry)
    clone["id"] = CITY_ID
    clone["prefs"] = ["interactive/dungeon_city"]
    arr.append(clone)
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def _clone_kv_data_item(data: list, source_key: str, new_key: str) -> None:
    keys = {item["key"] for item in data if isinstance(item, dict) and "key" in item}
    if new_key in keys:
        return
    src = next(x for x in data if isinstance(x, dict) and x.get("key") == source_key)
    dup = copy.deepcopy(src)
    dup["key"] = new_key
    data.append(dup)


def patch_map_object_sounds(all_data: dict) -> None:
    path = "DB/map_objects_sounds.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    data = root["objectsArr"]["data"]
    _clone_kv_data_item(data, "dungeon_city", CITY_ID)
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def patch_city_audio_tables(all_data: dict) -> None:
    for path, wrapper in (
        ("DB/city_ambient_sounds.json", "array"),
        ("DB/city_music_sounds.json", "array"),
    ):
        root = json.loads(all_data[path].decode("utf-8-sig"))
        data = root[wrapper]["data"]
        _clone_kv_data_item(data, "dungeon", FRACTION_ID)
        all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def patch_map_registration(all_data: dict) -> None:
    patch_interactables_city(all_data)
    patch_map_object_sounds(all_data)
    patch_city_audio_tables(all_data)


M2_M10_BUILDING_JSON_PATHS = (
    "DB/buildings_bans/M10_banlists.json",
    "DB/buildings_bans/M2_banlists.json",
    "DB/buildings_constructions/M10_buildings_presets.json",
    "DB/buildings_constructions/M2_buildings_presets.json",
)


def patch_m2_m10_building_presets(all_data: dict) -> None:
    suffix = "dungeon_city"
    for path in M2_M10_BUILDING_JSON_PATHS:
        if path not in all_data:
            continue
        root = json.loads(all_data[path].decode("utf-8-sig"))
        arr = root.get("array")
        if not isinstance(arr, list):
            continue
        ids = {o.get("id") for o in arr if isinstance(o, dict) and "id" in o}
        added = 0
        for item in list(arr):
            if not isinstance(item, dict):
                continue
            oid = item.get("id")
            if not isinstance(oid, str) or not oid.endswith(suffix):
                continue
            new_id = oid[: -len(suffix)] + CITY_ID
            if new_id in ids:
                continue
            clone = copy.deepcopy(item)
            clone["id"] = new_id
            arr.append(clone)
            ids.add(new_id)
            added += 1
        if added:
            all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
            print(f"{path}: added {added} {CITY_ID} row(s) (clone of *_dungeon_city).")


_GOBLIN_ROGUE_REF_PATHS = (
    "DB/unit_sets/unit_sets.json",
    "DB/reward_units_container.json",
    "DB/objects_logic/event_banks/campaign_objects/shady_den_campaign.json",
)
_GOBLIN_ROGUE_FALLBACK_UNIT = "halfling"


def _replace_exact_json_strings(obj: object, old: str, new: str) -> tuple[object, int]:
    if isinstance(obj, dict):
        out: dict = {}
        n = 0
        for k, v in obj.items():
            v2, c = _replace_exact_json_strings(v, old, new)
            out[k] = v2
            n += c
        return out, n
    if isinstance(obj, list):
        out_list: list = []
        n = 0
        for v in obj:
            v2, c = _replace_exact_json_strings(v, old, new)
            out_list.append(v2)
            n += c
        return out_list, n
    if isinstance(obj, str) and obj == old:
        return new, 1
    return obj, 0


def patch_orphan_goblin_rogue_unit_refs(all_data: dict) -> int:
    total = 0
    for path in _GOBLIN_ROGUE_REF_PATHS:
        if path not in all_data:
            continue
        root = json.loads(all_data[path].decode("utf-8-sig"))
        new_root, n = _replace_exact_json_strings(root, "goblin_rogue", _GOBLIN_ROGUE_FALLBACK_UNIT)
        if n:
            all_data[path] = json.dumps(new_root, ensure_ascii=False, indent="\t").encode("utf-8")
            total += n
    if total:
        print(
            f"Core: remapped goblin_rogue -> {_GOBLIN_ROGUE_FALLBACK_UNIT} ({total} string leaf(es)) in known JSON."
        )
    return total


SQUADS_DUNGEON_PREFIX = "DB/squads/squads_dungeon/"
SQUAD_ID_PREFIX_DUNGEON = "squad_dungeon_"


def morph_squad_json_identity(obj: object) -> None:
    if isinstance(obj, dict):
        if obj.get("fraction") == "dungeon":
            obj["fraction"] = FRACTION_ID
        iid = obj.get("id")
        if isinstance(iid, str) and iid.startswith(SQUAD_ID_PREFIX_DUNGEON):
            obj["id"] = SQUAD_ID_PREFIX_CLONE + iid[len(SQUAD_ID_PREFIX_DUNGEON) :]
        for k, v in obj.items():
            if k in ("id", "fraction"):
                continue
            morph_squad_json_identity(v)
    elif isinstance(obj, list):
        for item in obj:
            morph_squad_json_identity(item)


def patch_squads_tree_from_dungeon(all_data: dict) -> None:
    stale = [k for k in list(all_data.keys()) if k.startswith(SQUADS_CLONE_PREFIX)]
    for k in stale:
        del all_data[k]

    for old_path, blob in list(all_data.items()):
        if not old_path.startswith(SQUADS_DUNGEON_PREFIX):
            continue
        new_path = SQUADS_CLONE_PREFIX + old_path[len(SQUADS_DUNGEON_PREFIX) :].replace(
            SQUAD_ID_PREFIX_DUNGEON, SQUAD_ID_PREFIX_CLONE
        )
        try:
            root = json.loads(blob.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            all_data[new_path] = blob
            continue
        morph_squad_json_identity(root)
        all_data[new_path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def main() -> None:
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")

    pr = _CURRENT_PROFILE
    if pr is None:
        raise RuntimeError("install_city_profile() before main")
    backup = CORE.with_suffix(f".zip.{pr.backup_suffix}")
    if not backup.exists():
        backup.write_bytes(CORE.read_bytes())

    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    copy_all_units_from_dungeon(all_data)

    city = clone_city_from_dungeon(all_data)
    all_data[CITY_JSON_PATH] = json.dumps(
        {"array": [city]}, ensure_ascii=False, indent="\t"
    ).encode("utf-8")

    laws_out = clone_dungeon_laws(all_data)
    all_data[LAWS_JSON_PATH] = json.dumps(laws_out, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    frac_out = clone_fraction_config(all_data)
    all_data[FRACTION_JSON_PATH] = json.dumps(frac_out, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    data_json = json.loads(all_data["DB/data.json"].decode("utf-8-sig"))
    fr = data_json.setdefault("fractions", [])
    af = data_json.setdefault("availableFractions", [])
    if FRACTION_ID not in fr:
        fr.append(FRACTION_ID)
    if FRACTION_ID not in af:
        af.append(FRACTION_ID)
    all_data["DB/data.json"] = json.dumps(data_json, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    patch_map_registration(all_data)
    patch_m2_m10_building_presets(all_data)
    patch_squads_tree_from_dungeon(all_data)
    patch_orphan_goblin_rogue_unit_refs(all_data)

    with zipfile.ZipFile(CORE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)

    patch_localization()

    print(
        f"Patched {CORE}: profile {FRACTION_ID} — units/ (same SIDs as Dungeon), {CITY_JSON_PATH}, laws, "
        f"{FRACTION_JSON_PATH}, data.json, map interactables + audio, {pr.squads_folder}, "
        f"M2/M10 presets for {CITY_ID}, Lang cities/factionLaws/mapObjects + args."
    )
    if backup.exists():
        print(f"Backup: {backup}")


def patch_lang_only() -> None:
    if _CURRENT_PROFILE is None:
        raise RuntimeError("install_city_profile() before patch_lang_only")
    patch_localization()


def orphan_units_only() -> None:
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")
    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}
    patch_orphan_goblin_rogue_unit_refs(all_data)
    with zipfile.ZipFile(CORE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)
    print(f"Updated {CORE} (orphan unit refs only).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="homm3_fortress: Dungeon-perfect clone -> Core.zip + Lang. "
        "Use --raw for dungeon_raw / squad_dungeon_raw_* ids (stress-test bisect)."
    )
    ap.add_argument(
        "--raw",
        action="store_true",
        help="Dungeon-parallel ids: dungeon_raw, dungeon_city_raw, squads_dungeon_raw, …",
    )
    ap.add_argument(
        "--raw-exact-city-id",
        action="store_true",
        help=(
            "dungeon_raw profile, but cloned city config keeps exact id dungeon_city. "
            "Intentional duplicate-id stress test; implies --raw."
        ),
    )
    ap.add_argument("--lang-only", action="store_true", help="Patch Lang only.")
    ap.add_argument("--orphan-units-only", action="store_true", help="Only goblin_rogue remap in Core.")
    args = ap.parse_args()
    if args.raw_exact_city_id:
        install_city_profile(_profile_raw_exact_city_id())
    else:
        install_city_profile(_profile_raw() if args.raw else _profile_default())
    if args.lang_only:
        patch_lang_only()
    elif args.orphan_units_only:
        orphan_units_only()
    else:
        main()
