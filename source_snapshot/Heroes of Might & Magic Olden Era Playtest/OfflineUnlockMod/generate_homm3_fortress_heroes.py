"""
Clone Dungeon heroes + specializations into the fortress debug clone (same creature SIDs as Dungeon).

Default (homm3_fortress): hero ids homm3_fortress_hero_N, …

  python generate_homm3_fortress_heroes.py

--raw (must match generate_homm3_fortress_city.py --raw): dungeon_raw fraction,
hero ids dungeon_hero_N_raw (parallel to dungeon_hero_N), sub_class_dungeon_raw_*,
specializations_dungeon_raw.json.

  python generate_homm3_fortress_heroes.py --raw

--raw-exact-hero-ids: dungeon_raw fraction, but hero ids/specialization ids stay
exactly dungeon_hero_N / dungeon_hero_N_specialization. This intentionally collides
with vanilla Dungeon ids and is only for runtime ID-shape bisects.

  python generate_homm3_fortress_heroes.py --raw-exact-hero-ids

Run after the matching city generator pass.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

PLAYTEST_CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_LANG_ROOT = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Lang"
)
CUSTOM_FACTION_MANIFEST = Path(__file__).resolve().parents[2] / "custom_factions" / "homm3_fortress.json"

REMOVED_BAD_FACTION_SKILL_SID = "skill_faction_homm3_stronghold"
SKILLS_JSON_PATH = "DB/heroes_skills/skills/skills.json"
STRONGHOLD_MIGHT_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/homm3_stronghold_might_skills_table.json"
STRONGHOLD_MAGIC_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/homm3_stronghold_magic_skills_table.json"
DUNGEON_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_dungeon.json"
DEMON_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_demon.json"
NATURE_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_nature.json"

_RAW_HERO_ID_RE = re.compile(r"dungeon_hero_(\d+)(?=_|$)")


@dataclass(frozen=True)
class HeroProfile:
    fraction_id: str
    """homm3_fortress_hero for branded clone; ignored when use_raw_hero_ids."""
    hero_prefix: str
    sub_classes_out_path: str
    sub_class_new_prefix: str
    specializations_out_suffix: str
    backup_suffix: str
    use_raw_hero_ids: bool
    exact_dungeon_hero_ids: bool


def _hero_profile_default() -> HeroProfile:
    return HeroProfile(
        fraction_id="homm3_fortress",
        hero_prefix="homm3_fortress_hero",
        sub_classes_out_path="DB/heroes_sub_classes/sub_classes_homm3_fortress.json",
        sub_class_new_prefix="sub_class_homm3_fortress_",
        specializations_out_suffix="homm3_fortress",
        backup_suffix="bak_before_homm3_fortress_heroes",
        use_raw_hero_ids=False,
        exact_dungeon_hero_ids=False,
    )


def _hero_profile_raw() -> HeroProfile:
    return HeroProfile(
        fraction_id="dungeon_raw",
        hero_prefix="",
        sub_classes_out_path="DB/heroes_sub_classes/sub_classes_dungeon_raw.json",
        sub_class_new_prefix="sub_class_dungeon_raw_",
        specializations_out_suffix="dungeon_raw",
        backup_suffix="bak_before_dungeon_raw_heroes",
        use_raw_hero_ids=True,
        exact_dungeon_hero_ids=False,
    )


def _hero_profile_raw_exact_hero_ids() -> HeroProfile:
    return HeroProfile(
        fraction_id="dungeon_raw",
        hero_prefix="",
        sub_classes_out_path="DB/heroes_sub_classes/sub_classes_dungeon_raw.json",
        sub_class_new_prefix="sub_class_dungeon_raw_",
        specializations_out_suffix="dungeon_raw",
        backup_suffix="bak_before_dungeon_raw_exact_hero_ids",
        use_raw_hero_ids=False,
        exact_dungeon_hero_ids=True,
    )


_PROFILE: HeroProfile = _hero_profile_default()


def manifest_hero_count() -> int:
    if not CUSTOM_FACTION_MANIFEST.exists():
        return 18
    manifest = json.loads(CUSTOM_FACTION_MANIFEST.read_text(encoding="utf-8-sig"))
    heroes = manifest.get("heroes") or {}
    names = heroes.get("names") or []
    return int(heroes.get("count") or len(names) or 18)


def fix_hero_id_strings(s: str) -> str:
    if _PROFILE.exact_dungeon_hero_ids:
        return s
    if _PROFILE.use_raw_hero_ids:
        return _RAW_HERO_ID_RE.sub(r"dungeon_hero_\1_raw", s)
    return s.replace("dungeon_hero_", f"{_PROFILE.hero_prefix}_")


def cleanup_broken_homm3_faction_skill_clone(all_data: dict[str, bytes]) -> None:
    skills = json.loads(all_data[SKILLS_JSON_PATH].decode("utf-8-sig"))
    before = len(skills["array"])
    skills["array"] = [
        x for x in skills["array"] if x.get("id") != REMOVED_BAD_FACTION_SKILL_SID
    ]
    if len(skills["array"]) != before:
        all_data[SKILLS_JSON_PATH] = json.dumps(
            skills, ensure_ascii=False, indent="\t"
        ).encode("utf-8")
    all_data.pop(STRONGHOLD_MIGHT_TABLE_PATH, None)
    all_data.pop(STRONGHOLD_MAGIC_TABLE_PATH, None)


def clone_sub_classes_for_profile(all_data: dict[str, bytes]) -> None:
    src = json.loads(all_data[DUNGEON_SUB_CLASSES_PATH].decode("utf-8-sig"))
    out = copy.deepcopy(src)
    for item in out.get("array") or []:
        item["faction"] = _PROFILE.fraction_id
        hid = item.get("id")
        if isinstance(hid, str):
            item["id"] = hid.replace("sub_class_dungeon_", _PROFILE.sub_class_new_prefix)
    all_data[_PROFILE.sub_classes_out_path] = json.dumps(
        out, ensure_ascii=False, indent="\t"
    ).encode("utf-8")


def ensure_base_sub_classes_files(all_data: dict[str, bytes]) -> int:
    src = json.loads(all_data[DUNGEON_SUB_CLASSES_PATH].decode("utf-8-sig"))
    restored = 0
    for faction, path in (
        ("demon", DEMON_SUB_CLASSES_PATH),
        ("nature", NATURE_SUB_CLASSES_PATH),
    ):
        if path in all_data:
            continue
        out = copy.deepcopy(src)
        for item in out.get("array") or []:
            hid = item.get("id")
            item["faction"] = faction
            if isinstance(hid, str):
                item["id"] = hid.replace("sub_class_dungeon_", f"sub_class_{faction}_")
        all_data[path] = json.dumps(out, ensure_ascii=False, indent="\t").encode("utf-8")
        restored += 1
    return restored


def morph_hero_record(h: dict) -> None:
    icon_src = h.get("icon")
    h["id"] = fix_hero_id_strings(h["id"])
    h["specialization"] = fix_hero_id_strings(h["specialization"])
    if isinstance(icon_src, str) and icon_src.startswith("hero_dungeon_"):
        h["icon"] = icon_src
    h["fraction"] = _PROFILE.fraction_id


def morph_specializations(data: dict) -> dict:
    out = copy.deepcopy(data)
    for item in out.get("array") or []:
        for key in ("id", "name", "desc", "icon"):
            if key in item and isinstance(item[key], str) and "dungeon_hero_" in item[key]:
                item[key] = fix_hero_id_strings(item[key])
    return out


def merge_hero_info_from_dungeon_copies() -> int:
    total_added = 0
    label = _PROFILE.fraction_id
    for hero_info_path in sorted(PLAYTEST_LANG_ROOT.glob("*/texts/heroInfo.json")):
        pt = json.loads(hero_info_path.read_text(encoding="utf-8-sig"))
        existing = {t["sid"] for t in pt.get("tokens", []) if "sid" in t}

        added = []
        for t in pt.get("tokens", []):
            sid = t.get("sid")
            if not isinstance(sid, str) or not sid.startswith("dungeon_hero_"):
                continue
            new_sid = fix_hero_id_strings(sid)
            if new_sid in existing:
                continue
            new_t = copy.deepcopy(t)
            new_t["sid"] = new_sid
            added.append(new_t)
            existing.add(new_sid)

        if not added:
            continue

        pt["tokens"].extend(added)
        hero_info_path.write_text(
            json.dumps(pt, ensure_ascii=False, indent="\t") + "\n",
            encoding="utf-8",
        )
        total_added += len(added)
        print(f"Merged {len(added)} {label} hero token(s) into {hero_info_path}")

    if total_added == 0:
        print(f"heroInfo.json already contains {label} hero tokens in all locales; skipping merge.")
    return total_added


def main() -> None:
    if not PLAYTEST_CORE.exists():
        raise SystemExit(f"Missing Playtest Core.zip: {PLAYTEST_CORE}")

    backup = PLAYTEST_CORE.with_suffix(f".zip.{_PROFILE.backup_suffix}")
    if not backup.exists():
        backup.write_bytes(PLAYTEST_CORE.read_bytes())

    with zipfile.ZipFile(PLAYTEST_CORE, "r") as zin:
        zip_entries = {i.filename: i for i in zin.infolist()}
        all_data: dict[str, bytes] = {name: zin.read(name) for name in zin.namelist()}

    cleanup_broken_homm3_faction_skill_clone(all_data)
    restored_base_subclasses = ensure_base_sub_classes_files(all_data)
    clone_sub_classes_for_profile(all_data)

    fid = _PROFILE.fraction_id
    hero_dir_prefix = f"DB/heroes/{fid}/"
    stale_heroes = [k for k in list(all_data.keys()) if k.startswith(hero_dir_prefix)]
    for k in stale_heroes:
        del all_data[k]

    hero_count = manifest_hero_count()
    for i in range(1, hero_count + 1):
        inner = f"DB/heroes/dungeon/dungeon_hero_{i}.json"
        data = json.loads(all_data[inner].decode("utf-8-sig"))
        hero = copy.deepcopy(data["array"][0])
        morph_hero_record(hero)
        raw = json.dumps({"array": [hero]}, ensure_ascii=False, indent="\t").encode("utf-8")
        if _PROFILE.exact_dungeon_hero_ids:
            out_path = f"DB/heroes/{fid}/dungeon_hero_{i}.json"
        elif _PROFILE.use_raw_hero_ids:
            out_path = f"DB/heroes/{fid}/dungeon_hero_{i}_raw.json"
        else:
            out_path = f"DB/heroes/{fid}/{_PROFILE.hero_prefix}_{i}.json"
        all_data[out_path] = raw

    specs = json.loads(
        all_data["DB/heroes_specializations/specializations_dungeon.json"].decode("utf-8-sig")
    )
    new_specs = morph_specializations(specs)
    all_data[
        f"DB/heroes_specializations/specializations_{_PROFILE.specializations_out_suffix}.json"
    ] = json.dumps(new_specs, ensure_ascii=False, indent="\t").encode("utf-8")

    with zipfile.ZipFile(PLAYTEST_CORE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = zip_entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)

    merged_hero_tokens = merge_hero_info_from_dungeon_copies()

    if _PROFILE.exact_dungeon_hero_ids:
        hp = "dungeon_hero_* (exact duplicate ids)"
    else:
        hp = _PROFILE.hero_prefix if not _PROFILE.use_raw_hero_ids else "dungeon_hero_*_raw"
    print(
        f"Patched {PLAYTEST_CORE}: cleanup broken homm3 skill clone if any, "
        f"restored {restored_base_subclasses} missing base sub_classes file(s), "
        f"{_PROFILE.sub_classes_out_path}, {hero_count} heroes ({hp}), "
        f"specializations_{_PROFILE.specializations_out_suffix}.json, merged {merged_hero_tokens} heroInfo token(s)"
    )
    print(f"Backup (if created): {backup}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Clone Dungeon heroes for homm3_fortress or dungeon_raw (--raw). "
        "Match generate_homm3_fortress_city.py flags."
    )
    ap.add_argument(
        "--raw",
        action="store_true",
        help="dungeon_raw / dungeon_hero_N_raw / sub_classes_dungeon_raw (pair with city --raw).",
    )
    ap.add_argument(
        "--raw-exact-hero-ids",
        action="store_true",
        help=(
            "dungeon_raw but exact Dungeon hero/specialization ids (dungeon_hero_N). "
            "Intentional duplicate-id stress test; implies --raw."
        ),
    )
    ns = ap.parse_args()
    if ns.raw_exact_hero_ids:
        _PROFILE = _hero_profile_raw_exact_hero_ids()
    else:
        _PROFILE = _hero_profile_raw() if ns.raw else _hero_profile_default()
    main()
