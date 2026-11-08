#!/usr/bin/env python3
"""Surgically wire campaign hero override rows without regenerating whole faction files."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_factions" / "hero_overrides"


def load(faction: str) -> dict:
    return json.loads((ROOT / f"{faction}.json").read_text(encoding="utf-8"))


def save(faction: str, data: dict) -> None:
    (ROOT / f"{faction}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def non_faction_skills(entry: dict) -> list[dict]:
    skills = entry.get("startSkills") or []
    out = [
        {"sid": s["sid"], "skillLevel": s.get("skillLevel", 1)}
        for s in skills
        if isinstance(s, dict) and not str(s.get("sid") or "").startswith("skill_faction_")
    ]
    return out[:1]


def clone_hero(
    data: dict,
    src_sid: str,
    dst_sid: str,
    *,
    name: str,
    class_type: str,
    class_name: str,
    icon_key: str,
    spec_name: str,
    spec_desc: str,
    source_specialty_key: str,
    creature_sid: str | None = None,
    skill_sid: str | None = None,
    start_skills: list[dict] | None = None,
    description: str | None = None,
) -> None:
    src = data["heroOverrides"][src_sid]
    row = copy.deepcopy(src)
    row["nameText"] = name
    row["classType"] = class_type
    row["className"] = class_name
    row["iconKey"] = icon_key
    row["descriptionText"] = description if description is not None else (row.get("descriptionText") or "")
    row["mottoText"] = row.get("mottoText") or ""
    if start_skills is not None:
        row["startSkills"] = start_skills
    else:
        row["startSkills"] = non_faction_skills(src)
    spec = copy.deepcopy(row.get("specialization") or {})
    spec["nameText"] = spec_name
    spec["descriptionText"] = spec_desc
    spec["sourceSpecialtyKey"] = source_specialty_key
    spec["sourceSpecId"] = f"{dst_sid}_source_{source_specialty_key.replace(':', '_')}"
    if creature_sid:
        spec["iconKey"] = creature_sid
    elif skill_sid:
        spec["iconKey"] = skill_sid if skill_sid.startswith("skill_") else f"skill_{skill_sid}"
    row["specialization"] = spec
    row["notes"] = f"Campaign hero wiring for {name}; seeded from {src_sid}."
    data["heroOverrides"][dst_sid] = row


def main() -> None:
    castle = load("homm3_castle")
    for sid, name in (("homm3_castle_hero_17", "Catherine"), ("homm3_castle_hero_18", "Roland")):
        slot = sid.rsplit("_", 1)[-1]
        clone_hero(
            castle,
            "homm3_castle_hero_6",
            sid,
            name=name,
            class_type="might",
            class_name="Knight",
            icon_key=f"hero_homm3_castle_{slot}",
            spec_name="Swordsmen",
            spec_desc="Improves Swordsmen and their upgrades in the hero's army.",
            source_specialty_key="creature:h3_swordsman",
            creature_sid="h3_swordsman",
            start_skills=[{"sid": "skill_leadership", "skillLevel": 1}],
        )
    save("homm3_castle", castle)
    print("castle 17/18")

    inferno = load("homm3_inferno")
    donor = "homm3_inferno_hero_17" if "homm3_inferno_hero_17" in inferno["heroOverrides"] else "homm3_inferno_hero_8"
    clone_hero(
        inferno,
        donor,
        "homm3_inferno_hero_17",
        name="Xeron",
        class_type="might",
        class_name="Demoniac",
        icon_key="hero_homm3_inferno_17",
        spec_name="Devils",
        spec_desc="Improves Devils and their upgrades in the hero's army.",
        source_specialty_key="creature:h3_devil",
        creature_sid="h3_devil",
        start_skills=[{"sid": "skill_leadership", "skillLevel": 1}],
    )
    save("homm3_inferno", inferno)
    print("inferno 17")

    strong = load("homm3_stronghold")
    donor = "homm3_stronghold_hero_17" if "homm3_stronghold_hero_17" in strong["heroOverrides"] else "homm3_stronghold_hero_1"
    clone_hero(
        strong,
        donor,
        "homm3_stronghold_hero_17",
        name="Kilgor",
        class_type="might",
        class_name=str(strong["heroOverrides"][donor].get("className") or "Barbarian"),
        icon_key="hero_homm3_stronghold_17",
        spec_name="Behemoths",
        spec_desc="Improves Behemoths and their upgrades in the hero's army.",
        source_specialty_key="creature:h3_behemoth",
        creature_sid="h3_behemoth",
        start_skills=non_faction_skills(strong["heroOverrides"][donor])
        or [{"sid": "skill_offence", "skillLevel": 1}],
    )
    save("homm3_stronghold", strong)
    print("stronghold 17")

    necro = load("homm3_necropolis")
    for sid, name, donor, spec_name, creature, desc in (
        (
            "homm3_necropolis_hero_17",
            "Finneas",
            "homm3_necropolis_hero_3",
            "Liches",
            "h3_lich",
            "Finneas Vilmar rose quickly through the Necromancer ranks after King Gryphonheart's death. Ambitious and ruthless, he seeks to claim Deyja's throne for himself.",
        ),
        (
            "homm3_necropolis_hero_18",
            "Haart Lich",
            "homm3_necropolis_hero_5",
            "Black Knights",
            "h3_black_knight",
            "Once a living knight of Erathia, Lord Haart was transformed into a lich after his betrayal. Now bound to undeath, he serves necromantic masters with cold precision.",
        ),
    ):
        clone_hero(
            necro,
            donor if donor in necro["heroOverrides"] else "homm3_necropolis_hero_1",
            sid,
            name=name,
            class_type="might",
            class_name="Death Knight",
            icon_key=f"hero_homm3_necropolis_{sid.rsplit('_', 1)[-1]}",
            spec_name=spec_name,
            spec_desc=f"Improves {spec_name} and their upgrades in the hero's army.",
            source_specialty_key=f"creature:{creature}",
            creature_sid=creature,
            start_skills=[{"sid": "skill_necromancy", "skillLevel": 1}],
            description=desc,
        )
    save("homm3_necropolis", necro)
    print("necropolis 17/18")

    ramp = load("homm3_rampart")
    clone_hero(
        ramp,
        "homm3_rampart_hero_6",
        "homm3_rampart_hero_17",
        name="Gelu",
        class_type="might",
        class_name="Ranger",
        icon_key="hero_homm3_rampart_17",
        spec_name="Sharpshooters",
        spec_desc="Improves Wood Elves and their upgrades in the hero's army.",
        source_specialty_key="creature:h3_wood_elf",
        creature_sid="h3_wood_elf",
        start_skills=non_faction_skills(ramp["heroOverrides"]["homm3_rampart_hero_6"]),
    )
    clone_hero(
        ramp,
        "homm3_rampart_hero_7",
        "homm3_rampart_hero_18",
        name="Ordwald",
        class_type="magic",
        class_name="Druid",
        icon_key="hero_homm3_rampart_18",
        spec_name="Unicorns",
        spec_desc="Improves Unicorns and their upgrades in the hero's army.",
        source_specialty_key="creature:h3_unicorn",
        creature_sid="h3_unicorn",
        start_skills=non_faction_skills(ramp["heroOverrides"]["homm3_rampart_hero_7"]),
    )
    save("homm3_rampart", ramp)
    print("rampart 17/18")

    tower = load("homm3_tower")
    clone_hero(
        tower,
        "homm3_tower_hero_13",
        "homm3_tower_hero_17",
        name="Dracon",
        class_type="magic",
        class_name="Wizard",
        icon_key="hero_homm3_tower_17",
        spec_name="Enchanters",
        spec_desc="Improves Magi and their upgrades in the hero's army.",
        source_specialty_key="creature:h3_mage",
        creature_sid="h3_mage",
        start_skills=non_faction_skills(tower["heroOverrides"]["homm3_tower_hero_13"]),
    )
    clone_hero(
        tower,
        "homm3_tower_hero_10",
        "homm3_tower_hero_18",
        name="Yog the Wizard",
        class_type="magic",
        class_name="Wizard",
        icon_key="hero_homm3_tower_18",
        spec_name="Intelligence",
        spec_desc="Improves the hero Intelligence secondary skill.",
        source_specialty_key="skill:intelligence",
        skill_sid="skill_intelligence",
        start_skills=non_faction_skills(tower["heroOverrides"]["homm3_tower_hero_10"]),
        description=(
            "After leaving the barbarian tribes, Yog studied wizardry among the mages of Bracada. "
            "He retains a warrior's frame, but his power now comes from spellcraft rather than steel."
        ),
    )
    save("homm3_tower", tower)
    print("tower 17/18")

    fort = load("homm3_fortress")
    clone_hero(
        fort,
        "homm3_fortress_hero_14",
        "homm3_fortress_hero_17",
        name="Adrienne",
        class_type="magic",
        class_name="Witch",
        icon_key="hero_homm3_fortress_17",
        spec_name="Fire Magic",
        spec_desc="Improves the hero Sorcery secondary skill.",
        source_specialty_key="skill:sorcery",
        skill_sid="skill_sorcery",
        start_skills=non_faction_skills(fort["heroOverrides"]["homm3_fortress_hero_14"]),
    )
    clone_hero(
        fort,
        "homm3_fortress_hero_10",
        "homm3_fortress_hero_18",
        name="Kinkeria",
        class_type="magic",
        class_name="Witch",
        icon_key="hero_homm3_fortress_18",
        spec_name="Mysticism",
        spec_desc="Improves the hero Mysticism secondary skill.",
        source_specialty_key="skill:mysticism",
        skill_sid="skill_mysticism",
        start_skills=non_faction_skills(fort["heroOverrides"]["homm3_fortress_hero_10"]),
    )
    save("homm3_fortress", fort)
    print("fortress 17/18")
    print("done")


if __name__ == "__main__":
    main()
