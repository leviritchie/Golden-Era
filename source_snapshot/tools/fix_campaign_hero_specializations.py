#!/usr/bin/env python3
"""Fix campaign hero specializations by cloning known-good specialists."""
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
    return [
        {"sid": s["sid"], "skillLevel": s.get("skillLevel", 1)}
        for s in (entry.get("startSkills") or [])
        if isinstance(s, dict) and not str(s.get("sid") or "").startswith("skill_faction_")
    ][:1]


def first_creature_donor(data: dict, preferred: str | None = None) -> str:
    if preferred and preferred in data["heroOverrides"]:
        key = (data["heroOverrides"][preferred].get("specialization") or {}).get("sourceSpecialtyKey") or ""
        if str(key).startswith("creature:"):
            return preferred
    for sid, entry in data["heroOverrides"].items():
        key = (entry.get("specialization") or {}).get("sourceSpecialtyKey") or ""
        if str(key).startswith("creature:"):
            return sid
    raise KeyError("no creature specialist donor")


def first_skill_donor(data: dict) -> str:
    for sid, entry in data["heroOverrides"].items():
        key = (entry.get("specialization") or {}).get("sourceSpecialtyKey") or ""
        if str(key).startswith("skill:"):
            return sid
    raise KeyError("no skill specialist donor")


def rewrite_creature_spec(spec: dict, creature_sid: str, *, name: str, dst_sid: str) -> dict:
    old_key = str(spec.get("sourceSpecialtyKey") or "")
    old_creature = old_key.split(":", 1)[-1] if old_key.startswith("creature:") else ""
    if old_creature and old_creature != creature_sid:
        blob = json.dumps(spec).replace(old_creature, creature_sid)
        spec = json.loads(blob)
    spec["sourceSpecialtyKey"] = f"creature:{creature_sid}"
    spec["iconKey"] = creature_sid
    spec["nameText"] = name
    spec["descriptionText"] = f"Improves {name} and their upgrades in the hero's army."
    spec["sourceSpecId"] = f"{dst_sid}_source_{creature_sid}_specialist"
    return spec


def apply_creature_hero(
    data: dict,
    dst_sid: str,
    *,
    name: str,
    class_type: str,
    class_name: str,
    donor_sid: str,
    icon_key: str,
    creature_sid: str | None = None,
    description: str | None = None,
    start_skills: list[dict] | None = None,
) -> None:
    donor = data["heroOverrides"][donor_sid]
    row = copy.deepcopy(donor)
    row["nameText"] = name
    row["classType"] = class_type
    row["className"] = class_name
    row["iconKey"] = icon_key
    if description is not None:
        row["descriptionText"] = description
    row["startSkills"] = start_skills if start_skills is not None else non_faction_skills(donor)
    spec = copy.deepcopy(donor["specialization"])
    donor_creature = str(spec.get("sourceSpecialtyKey") or "").split(":", 1)[-1]
    target_creature = creature_sid or donor_creature
    spec = rewrite_creature_spec(spec, target_creature, name=spec.get("nameText") or name, dst_sid=dst_sid)
    if creature_sid:
        # Prefer explicit specialty display names for campaign leads.
        pretty = {
            "h3_swordsman": "Swordsmen",
            "h3_devil": "Devils",
            "h3_behemoth": "Behemoths",
            "h3_lich": "Liches",
            "h3_black_knight": "Black Knights",
            "h3_wood_elf": "Sharpshooters",
            "h3_unicorn": "Unicorns",
            "h3_mage": "Enchanters",
        }.get(creature_sid)
        if pretty:
            spec["nameText"] = pretty
            spec["descriptionText"] = f"Improves {pretty} and their upgrades in the hero's army."
    row["specialization"] = spec
    row["notes"] = f"Campaign hero {name}; creature specialty from {donor_sid}."
    data["heroOverrides"][dst_sid] = row


def apply_skill_hero(
    data: dict,
    dst_sid: str,
    *,
    name: str,
    class_type: str,
    class_name: str,
    donor_sid: str,
    icon_key: str,
    skill_key: str,
    spec_name: str,
    spec_desc: str,
    description: str | None = None,
) -> None:
    body_donor = data["heroOverrides"][donor_sid]
    skill_donor = data["heroOverrides"][first_skill_donor(data)]
    row = copy.deepcopy(body_donor)
    row["nameText"] = name
    row["classType"] = class_type
    row["className"] = class_name
    row["iconKey"] = icon_key
    if description is not None:
        row["descriptionText"] = description
    row["startSkills"] = non_faction_skills(body_donor)
    spec = copy.deepcopy(skill_donor["specialization"])
    spec["nameText"] = spec_name
    spec["descriptionText"] = spec_desc
    spec["sourceSpecialtyKey"] = f"skill:{skill_key}"
    spec["sourceSpecId"] = f"{dst_sid}_source_{skill_key}_specialist"
    spec["iconKey"] = "skill_wisdom"
    row["specialization"] = spec
    row["notes"] = f"Campaign/HotA hero {name}; skill specialty template."
    data["heroOverrides"][dst_sid] = row


def main() -> None:
    castle = load("homm3_castle")
    for sid, name in (("homm3_castle_hero_17", "Catherine"), ("homm3_castle_hero_18", "Roland")):
        apply_creature_hero(
            castle,
            sid,
            name=name,
            class_type="might",
            class_name="Knight",
            donor_sid="homm3_castle_hero_6",
            icon_key=f"hero_homm3_castle_{sid.rsplit('_', 1)[-1]}",
            creature_sid="h3_swordsman",
            start_skills=[{"sid": "skill_leadership", "skillLevel": 1}],
        )
    save("homm3_castle", castle)

    inferno = load("homm3_inferno")
    apply_creature_hero(
        inferno,
        "homm3_inferno_hero_17",
        name="Xeron",
        class_type="might",
        class_name="Demoniac",
        donor_sid=first_creature_donor(inferno, "homm3_inferno_hero_8"),
        icon_key="hero_homm3_inferno_17",
        creature_sid="h3_devil",
        start_skills=[{"sid": "skill_leadership", "skillLevel": 1}],
    )
    save("homm3_inferno", inferno)

    strong = load("homm3_stronghold")
    apply_creature_hero(
        strong,
        "homm3_stronghold_hero_17",
        name="Kilgor",
        class_type="might",
        class_name="Barbarian",
        donor_sid=first_creature_donor(strong, "homm3_stronghold_hero_6"),
        icon_key="hero_homm3_stronghold_17",
        creature_sid="h3_behemoth",
    )
    save("homm3_stronghold", strong)

    necro = load("homm3_necropolis")
    apply_creature_hero(
        necro,
        "homm3_necropolis_hero_17",
        name="Finneas",
        class_type="might",
        class_name="Death Knight",
        donor_sid="homm3_necropolis_hero_3",
        icon_key="hero_homm3_necropolis_17",
        creature_sid="h3_lich",
        description=(
            "Finneas Vilmar rose quickly through the Necromancer ranks after King Gryphonheart's death. "
            "Ambitious and ruthless, he seeks to claim Deyja's throne for himself."
        ),
        start_skills=[{"sid": "skill_necromancy", "skillLevel": 1}],
    )
    apply_creature_hero(
        necro,
        "homm3_necropolis_hero_18",
        name="Haart Lich",
        class_type="might",
        class_name="Death Knight",
        donor_sid="homm3_necropolis_hero_5",
        icon_key="hero_homm3_necropolis_18",
        creature_sid="h3_black_knight",
        description=(
            "Once a living knight of Erathia, Lord Haart was transformed into a lich after his betrayal. "
            "Now bound to undeath, he serves necromantic masters with cold precision."
        ),
        start_skills=[{"sid": "skill_necromancy", "skillLevel": 1}],
    )
    save("homm3_necropolis", necro)

    ramp = load("homm3_rampart")
    apply_creature_hero(
        ramp,
        "homm3_rampart_hero_17",
        name="Gelu",
        class_type="might",
        class_name="Ranger",
        donor_sid="homm3_rampart_hero_6",
        icon_key="hero_homm3_rampart_17",
        creature_sid="h3_wood_elf",
    )
    apply_creature_hero(
        ramp,
        "homm3_rampart_hero_18",
        name="Ordwald",
        class_type="magic",
        class_name="Druid",
        donor_sid="homm3_rampart_hero_7",
        icon_key="hero_homm3_rampart_18",
        creature_sid="h3_unicorn",
    )
    save("homm3_rampart", ramp)

    tower = load("homm3_tower")
    apply_creature_hero(
        tower,
        "homm3_tower_hero_17",
        name="Dracon",
        class_type="magic",
        class_name="Wizard",
        donor_sid="homm3_tower_hero_13",
        icon_key="hero_homm3_tower_17",
        creature_sid="h3_mage",
    )
    # Pairing slot: keep a creature specialty (genie) so Core validation stays fail-closed.
    apply_creature_hero(
        tower,
        "homm3_tower_hero_18",
        name="Yog the Wizard",
        class_type="magic",
        class_name="Wizard",
        donor_sid="homm3_tower_hero_2",
        icon_key="hero_homm3_tower_18",
        creature_sid="h3_genie",
        description=(
            "After leaving the barbarian tribes, Yog studied wizardry among the mages of Bracada. "
            "He retains a warrior's frame, but his power now comes from spellcraft rather than steel."
        ),
    )
    save("homm3_tower", tower)

    fort = load("homm3_fortress")
    apply_creature_hero(
        fort,
        "homm3_fortress_hero_17",
        name="Adrienne",
        class_type="magic",
        class_name="Witch",
        donor_sid="homm3_fortress_hero_1",
        icon_key="hero_homm3_fortress_17",
        creature_sid="h3_basilisk",
    )
    apply_creature_hero(
        fort,
        "homm3_fortress_hero_18",
        name="Kinkeria",
        class_type="magic",
        class_name="Witch",
        donor_sid="homm3_fortress_hero_6",
        icon_key="hero_homm3_fortress_18",
        creature_sid="h3_serpent_fly",
    )
    save("homm3_fortress", fort)
    print("campaign hero overrides repaired")


if __name__ == "__main__":
    main()
