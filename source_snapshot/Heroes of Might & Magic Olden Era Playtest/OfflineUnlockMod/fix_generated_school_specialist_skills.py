"""
Ensure generated Hive/Grove school specialists start with the matching magic skill.

This follows the verified pattern from the original four factions:
true school specialists (heroes whose specialization boosts an entire
school via `magicSchoolSet`) start with the matching `skill_magic_*`.

Run:
  python fix_generated_school_specialist_skills.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

PLAYTEST_CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)

SCHOOL_TO_SKILL = {
    "day": "skill_magic_day",
    "night": "skill_magic_night",
    "space": "skill_magic_space",
    "primal": "skill_magic_primal",
}

GENERATED_FACTIONS = {
    "demon": {
        "hero_dir": "demon",
        "faction_skill": "skill_faction_demons",
    },
    "nature": {
        "hero_dir": "nature",
        "faction_skill": "skill_faction_nature",
    },
    "homm3_stronghold": {
        "hero_dir": "homm3_stronghold",
        # Must stay skill_faction_dungeon: a cloned top-level faction skill reuses the same
        # sub_skill_faction_dungeon_* ids and crashes session load (duplicate dictionary key).
        "faction_skill": "skill_faction_dungeon",
    },
    "homm3_fortress": {
        "hero_dir": "homm3_fortress",
        "faction_skill": "skill_faction_dungeon",
    },
}


def load_json_from_zip(zpath: Path, inner_path: str) -> dict:
    with zipfile.ZipFile(zpath, "r") as z:
        return json.loads(z.read(inner_path).decode("utf-8-sig"))


def rebuild_zip(core_path: Path, updates: dict[str, bytes]) -> None:
    backup = core_path.with_suffix(".zip.bak_before_generated_school_skill_fix")
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


def get_school_specialization(spec: dict) -> str | None:
    schools = {
        bonus["parameters"][1]
        for bonus in spec.get("bonuses") or []
        if bonus.get("type") == "heroStat"
        and isinstance(bonus.get("parameters"), list)
        and len(bonus["parameters"]) >= 2
        and bonus["parameters"][0] == "magicSchoolSet"
        and bonus["parameters"][1] in SCHOOL_TO_SKILL
    }
    if len(schools) != 1:
        return None
    return next(iter(schools))


def set_school_start_skill(hero: dict, faction_skill: str, school_skill: str) -> bool:
    old_skills = hero.get("startSkills") or []
    new_skills = [{"sid": faction_skill, "skillLevel": 1}, {"sid": school_skill, "skillLevel": 1}]
    if old_skills == new_skills:
        return False
    hero["startSkills"] = new_skills
    return True


def main() -> None:
    if not PLAYTEST_CORE.exists():
        raise SystemExit(f"Missing Playtest Core.zip: {PLAYTEST_CORE}")

    updates: dict[str, bytes] = {}
    changed: list[tuple[str, list[str], str]] = []

    with zipfile.ZipFile(PLAYTEST_CORE, "r") as z:
        for faction, meta in GENERATED_FACTIONS.items():
            spec_path = f"DB/heroes_specializations/specializations_{faction}.json"
            spec_array = json.loads(z.read(spec_path).decode("utf-8-sig"))["array"]
            specs = {spec["id"]: spec for spec in spec_array}

            prefix = f"DB/heroes/{meta['hero_dir']}/"
            hero_paths = sorted(
                name for name in z.namelist() if name.startswith(prefix) and name.endswith(".json")
            )
            for hero_path in hero_paths:
                payload = json.loads(z.read(hero_path).decode("utf-8-sig"))
                hero = payload["array"][0]
                spec = specs.get(hero["specialization"])
                if spec is None:
                    continue

                school = get_school_specialization(spec)
                if school is None:
                    continue

                required_skill = SCHOOL_TO_SKILL[school]
                old_skill_sids = [skill.get("sid") for skill in hero.get("startSkills") or []]
                if set_school_start_skill(hero, meta["faction_skill"], required_skill):
                    updates[hero_path] = json.dumps(payload, ensure_ascii=False, indent="\t").encode("utf-8")
                    changed.append((hero["id"], old_skill_sids, required_skill))

    if updates:
        rebuild_zip(PLAYTEST_CORE, updates)

    if changed:
        print("Updated generated school specialists:")
        for hero_id, old_skills, required_skill in changed:
            print(f"  {hero_id}: {old_skills} -> ['{required_skill}']")
    else:
        print("No generated school-specialist heroes needed skill fixes.")


if __name__ == "__main__":
    main()
