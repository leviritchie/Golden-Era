#!/usr/bin/env python3
"""Fail-closed Bulwark ability repair contract: native dealers, transforms, shooters, immunity, loc."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any


FORBIDDEN_PLAYER_TERMS = re.compile(
    r"\b(native|exact|runtime|SID|donor|Core|deobf|tracing|validation|implementation|runtime-pending)\b",
    re.IGNORECASE,
)

EXPECTED_FOCUS: dict[str, dict[str, Any]] = {
    "h3_kobold_foreman": {
        "name": "Foreman Cadence",
        "effectKind": "spell-effect",
        "effectKey": "day_12_magic_radiant_armor:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "ally",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_kobold_upg_alt": {
        "name": "Rune Brand",
        "effectKind": "spell-effect",
        "effectKey": "day_12_magic_radiant_armor:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "self",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_argali": {
        "name": "Frost Fracture",
        "effectKind": "spell-effect",
        "effectKey": "day_5_magic_shorten_shadow:level:1",
        "energyLevel": 1,
        "cooldown": 2,
        "turnBehavior": "free",
        "targetMode": "enemy",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_mountain_ram_upg_alt": {
        "name": "Aurora Bound",
        "effectKind": "spell-effect",
        "effectKey": "space_6_magic_blink:level:1",
        "energyLevel": 1,
        "cooldown": 2,
        "turnBehavior": "ends",
        "targetMode": "self",
        "orderedDistance": 4,
        "offensive": False,
    },
    "h3_steel_elf": {
        "name": "Frost Needle",
        "effectKind": "spell-effect",
        "effectKey": "primal_6_magic_ice_bolt:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "enemy",
        "offensive": True,
    },
    "h3_snow_elf_upg_alt": {
        "name": "Cold Shackles",
        "effectKind": "spell-effect",
        "effectKey": "space_7_magic_shackles:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "enemy",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_yeti_runemaster": {
        "name": "Rune Surge",
        "effectKind": "unit-special",
        "effectKey": "sentinel:abilities:0",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "offensive": False,
    },
    "h3_yeti_upg_alt": {
        "name": "Storm Frost",
        "effectKind": "spell-effect",
        "effectKey": "primal_6_magic_ice_bolt:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "free",
        "targetMode": "enemy",
        "offensive": True,
    },
    "h3_shaman": {
        "name": "Air Ward",
        "effectKind": "spell-effect",
        "effectKey": "space_4_magic_optical_illusion:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "ally",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_great_shaman": {
        "name": "Air Ward",
        "effectKind": "spell-effect",
        "effectKey": "space_4_magic_optical_illusion:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "ally",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_shaman_upg_alt": {
        "name": "Freezing Hex",
        "effectKind": "spell-effect",
        "effectKey": "primal_6_magic_ice_bolt:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "enemy",
        "offensive": True,
    },
    "h3_war_mammoth": {
        "name": "Tusker Guard",
        "effectKind": "spell-effect",
        "effectKey": "day_12_magic_radiant_armor:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "self",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_mammoth_upg_alt": {
        "name": "Frost Wall",
        "effectKind": "spell-effect",
        "effectKey": "space_4_magic_optical_illusion:level:1",
        "energyLevel": 2,
        "cooldown": 3,
        "turnBehavior": "ends",
        "targetMode": "self",
        "fixedDuration": 1,
        "offensive": False,
    },
    "h3_jotunn": {
        "name": "Clan Warp",
        "effectKind": "unit-special",
        "effectKey": "arbitrator:abilities:0",
        "energyLevel": 2,
        "cooldown": 2,
        "turnBehavior": "ends",
        "charges": 1,
        "offensive": False,
    },
    "h3_jotunn_warlord": {
        "name": "Clan Warp",
        "effectKind": "unit-special",
        "effectKey": "arbitrator:abilities:0",
        "energyLevel": 2,
        "cooldown": 2,
        "turnBehavior": "ends",
        "offensive": False,
    },
    "h3_jotunn_upg_alt": {
        "name": "Avalanche",
        "effectKind": "spell-effect",
        "effectKey": "primal_13_magic_avalanche:level:1",
        "energyLevel": 3,
        "cooldown": 3,
        "turnBehavior": "ends",
        "offensive": True,
    },
}

FREE_SHOOTING_SIDS = {"h3_steel_elf", "h3_snow_elf_upg_alt"}
ARGALI_IMMUNITY_SIDS = {"h3_argali", "h3_mountain_ram_upg_alt"}
ICE_DAMAGE_TAGS = {"primal_6_magic_ice_bolt_damage", "primal_13_magic_avalanche_damage"}
ICE_EFFECT_TAGS = {"primal_6_magic_ice_bolt_effect"}


def fail(message: str) -> None:
    raise SystemExit("bulwark-ability-repair-contract: " + message)


def read_json(path: Path) -> Any:
    if not path.is_file():
        fail(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def enabled_focus(unit: dict[str, Any]) -> dict[str, Any] | None:
    specials = unit.get("existingSpecials") or []
    if not isinstance(specials, list):
        return None
    for special in specials:
        if not isinstance(special, dict):
            continue
        if special.get("enabled") is False:
            continue
        if special.get("slotKind") != "abilities":
            continue
        return special
    return None


def parse_spell_effect_key(value: str) -> tuple[str, int] | None:
    marker = ":level:"
    if marker not in value:
        return None
    spell_sid, level_text = value.rsplit(marker, 1)
    try:
        level = int(level_text)
    except ValueError:
        return None
    if not spell_sid or level < 1:
        return None
    return spell_sid, level


def resolve_spell_dealer(core: zipfile.ZipFile, spell_sid: str, spell_level: int) -> dict[str, Any]:
    for name in core.namelist():
        if not name.startswith("DB/magics/") or not name.endswith(".json"):
            continue
        doc = json.loads(core.read(name).decode("utf-8-sig"))
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("id") != spell_sid:
                continue
            battle_magic = row.get("battleMagic")
            dealers = battle_magic.get("magicDealers") if isinstance(battle_magic, dict) else None
            if not isinstance(dealers, list) or not dealers:
                fail(f"spell {spell_sid} has no magicDealers")
            dealer_indexes = battle_magic.get("dealersPerLevels")
            if not isinstance(dealer_indexes, list) or not dealer_indexes:
                dealer_indexes = list(range(len(dealers)))
            offset = spell_level - 1
            if offset < 0 or offset >= len(dealer_indexes):
                fail(f"spell {spell_sid} has no dealer for level {spell_level}")
            dealer_index = dealer_indexes[offset]
            if not isinstance(dealer_index, int) or dealer_index < 0 or dealer_index >= len(dealers):
                fail(f"spell {spell_sid} dealer index invalid for level {spell_level}")
            dealer = dealers[dealer_index]
            if not isinstance(dealer, dict):
                fail(f"spell {spell_sid} dealer is not an object")
            return dealer
    fail(f"spell {spell_sid} not found in Core.zip")


def dealer_has_damaging_mechanic(dealer: dict[str, Any]) -> bool:
    damage_target = dealer.get("damageTarget_")
    damage_type = dealer.get("damageType_")
    if damage_target not in (None, "", "none") and damage_type not in (None, "", "none"):
        return True
    mechs = dealer.get("targetMechanics")
    if isinstance(mechs, list):
        for mech in mechs:
            if isinstance(mech, dict) and str(mech.get("mech") or "") in {"push_unit", "pull_unit", "damage", "absolute_damage"}:
                return True
    self_mechs = dealer.get("selfMechanics")
    if isinstance(self_mechs, list) and self_mechs:
        return False
    return False


def validate_overrides(repo: Path, core: zipfile.ZipFile) -> None:
    path = repo / "custom_factions" / "ability_overrides" / "homm3_bulwark.json"
    doc = read_json(path)
    if doc.get("factionSid") != "homm3_bulwark":
        fail("ability override factionSid must be homm3_bulwark")
    overrides = doc.get("unitOverrides")
    if not isinstance(overrides, dict):
        fail("unitOverrides must be an object")
    if len(EXPECTED_FOCUS) != 16:
        fail("internal EXPECTED_FOCUS must contain exactly 16 Focus abilities")

    for sid, expected in EXPECTED_FOCUS.items():
        unit = overrides.get(sid)
        if not isinstance(unit, dict):
            fail(f"missing unit override {sid}")
        special = enabled_focus(unit)
        if special is None:
            fail(f"{sid} must have an enabled Focus ability")
        if special.get("nameText") != expected["name"]:
            fail(f"{sid} nameText must be {expected['name']!r}, got {special.get('nameText')!r}")
        for field in ("energyLevel", "cooldown", "turnBehavior", "effectKind", "effectKey"):
            if special.get(field) != expected[field]:
                fail(f"{sid} {field} must be {expected[field]!r}, got {special.get(field)!r}")
        if "charges" in expected and special.get("charges") != expected["charges"]:
            fail(f"{sid} charges must be {expected['charges']!r}, got {special.get('charges')!r}")
        for text_field in ("nameText", "descriptionText"):
            text = special.get(text_field)
            if isinstance(text, str) and FORBIDDEN_PLAYER_TERMS.search(text):
                fail(f"{sid} {text_field} exposes implementation language: {text!r}")
        payload = special.get("effectPayload")
        if not isinstance(payload, dict):
            fail(f"{sid} effectPayload must be an object")
        if "dealer" in payload:
            fail(f"{sid} must not embed a handwritten dealer object")
        for transform in ("targetMode", "orderedDistance", "fixedDuration"):
            if transform in expected and payload.get(transform) != expected[transform]:
                fail(f"{sid} effectPayload.{transform} must be {expected[transform]!r}")
        if expected["effectKind"] != "spell-effect":
            continue
        parsed = parse_spell_effect_key(str(expected["effectKey"]))
        if parsed is None:
            fail(f"{sid} invalid spell effectKey")
        spell_sid, spell_level = parsed
        dealer = resolve_spell_dealer(core, spell_sid, spell_level)
        if expected.get("offensive"):
            if not dealer_has_damaging_mechanic(dealer):
                fail(
                    f"{sid} offensive spell {spell_sid} resolves with no damaging mechanic "
                    f"(damageTarget_={dealer.get('damageTarget_')!r}, damageType_={dealer.get('damageType_')!r})"
                )
            if dealer.get("damageTarget_") in (None, "", "none") and dealer.get("damageType_") in (None, "", "none"):
                mechs = dealer.get("targetMechanics") or []
                if not any(isinstance(m, dict) and m.get("mech") == "push_unit" for m in mechs):
                    fail(f"{sid} offensive ability has damageTarget_/damageType_ none without push/damage mechanic")
        else:
            buff = dealer.get("buff")
            if expected.get("fixedDuration") is not None and not isinstance(buff, dict):
                # Blink has no buff; only fixedDuration rows require buff existence on donor.
                if expected.get("name") != "Aurora Bound":
                    fail(f"{sid} native dealer must include a buff for fixedDuration transform")


def validate_overlay_source(repo: Path) -> None:
    overlay = repo / "tools" / "release_port" / "apply_release_core_overlay.py"
    text = overlay.read_text(encoding="utf-8")
    for needle in (
        "BULWARK_SPELL_EFFECT_TRANSFORM_KEYS",
        "apply_bulwark_spell_effect_transforms",
        "GENERIC_ICE_BOLT_EFFECT_IMMUNITY_TAGS",
        "h3_common_passive_free_shooting_name",
        "primal_6_magic_ice_bolt_effect",
        'faction_sid == "homm3_bulwark"',
        "handwritten dealer forbidden",
    ):
        if needle not in text:
            fail(f"apply_release_core_overlay.py must contain {needle!r}")
    if 'append_unique_view_passive(passives, "base_passive_sharpshooter_name", "base_passive_sharpshooter_description")\n        implemented.append("no obstacle penalty")' in text:
        fail("NO_OBSTACLE shooters must not advertise Sharpshooter full-range text")


def validate_installed_units(core: zipfile.ZipFile) -> None:
    # Optional installed readback: if Bulwark units exist in Core, check dealer/shooter/immunity shape.
    sample_offensive = {
        "h3_steel_elf": "Frost Needle",
        "h3_yeti_upg_alt": "Storm Frost",
        "h3_shaman_upg_alt": "Freezing Hex",
        "h3_jotunn_upg_alt": "Avalanche",
    }
    present = 0
    for sid in sample_offensive:
        logic_name = f"DB/units/units_logics/homm3_bulwark/{sid}_l.json"
        if logic_name not in core.namelist():
            continue
        present += 1
        doc = json.loads(core.read(logic_name).decode("utf-8-sig"))
        row = (doc.get("array") or [None])[0]
        if not isinstance(row, dict):
            fail(f"installed {sid} logic row missing")
        abilities = row.get("abilities") or []
        if not isinstance(abilities, list) or not abilities:
            fail(f"installed {sid} must have Focus abilities")
        dealer = (abilities[0] or {}).get("damageDealer") if isinstance(abilities[0], dict) else None
        if not isinstance(dealer, dict):
            fail(f"installed {sid} Focus missing damageDealer")
        if not dealer_has_damaging_mechanic(dealer):
            fail(
                f"installed {sid} offensive Focus has empty damage "
                f"(damageTarget_={dealer.get('damageTarget_')!r}, damageType_={dealer.get('damageType_')!r})"
            )

    for sid in FREE_SHOOTING_SIDS:
        logic_name = f"DB/units/units_logics/homm3_bulwark/{sid}_l.json"
        view_name = f"DB/units/units_views/homm3_bulwark/{sid}_v.json"
        if logic_name not in core.namelist():
            continue
        present += 1
        logic = json.loads(core.read(logic_name).decode("utf-8-sig"))
        row = (logic.get("array") or [None])[0]
        stats = row.get("stats") if isinstance(row, dict) else None
        if not isinstance(stats, dict) or stats.get("ignoreShootingBlock") is not True:
            fail(f"installed {sid} must set ignoreShootingBlock")
        if stats.get("ignoreShootDmgBuff") is True:
            fail(f"installed {sid} must not set undocumented ignoreShootDmgBuff / Sharpshooter range immunity")
        if view_name in core.namelist():
            view = json.loads(core.read(view_name).decode("utf-8-sig"))
            vrow = (view.get("array") or [None])[0]
            passives = vrow.get("passives") if isinstance(vrow, dict) else None
            names = {
                p.get("name")
                for p in (passives or [])
                if isinstance(p, dict)
            }
            if "h3_common_passive_free_shooting_name" not in names and "base_passive_sharpshooter_name" in names:
                fail(f"installed {sid} still advertises Sharpshooter instead of Free Shooting")

    for sid in ARGALI_IMMUNITY_SIDS:
        logic_name = f"DB/units/units_logics/homm3_bulwark/{sid}_l.json"
        if logic_name not in core.namelist():
            continue
        present += 1
        logic = json.loads(core.read(logic_name).decode("utf-8-sig"))
        row = (logic.get("array") or [None])[0]
        passives = row.get("passives") if isinstance(row, dict) else None
        found_damage = False
        found_effect = False
        for passive in passives or []:
            if not isinstance(passive, dict):
                continue
            data = passive.get("data") if isinstance(passive.get("data"), dict) else {}
            for immunity in data.get("immunities") or []:
                if not isinstance(immunity, dict):
                    continue
                tags = set(immunity.get("tags") or [])
                if immunity.get("type") == "damage" and ICE_DAMAGE_TAGS <= tags:
                    found_damage = True
                if immunity.get("type") == "effect" and ICE_EFFECT_TAGS & tags:
                    found_effect = True
        if not found_damage:
            fail(f"installed {sid} missing Ice Bolt/Avalanche damage immunity tags")
        if not found_effect:
            fail(f"installed {sid} missing Ice Bolt effect immunity tag")

    if present == 0:
        # Source/static still validated; installed payload not yet overlaid.
        return


def validate_csproj(repo: Path) -> None:
    csproj = (
        repo
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "OfflineUnlockMod.csproj"
    )
    text = csproj.read_text(encoding="utf-8")
    if "ValidateHomm3BulwarkAbilityRepairContract" not in text:
        fail("OfflineUnlockMod.csproj must wire ValidateHomm3BulwarkAbilityRepairContract")
    if "validate_homm3_bulwark_ability_repair_contract.py" not in text:
        fail("OfflineUnlockMod.csproj must invoke validate_homm3_bulwark_ability_repair_contract.py")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--core",
        type=Path,
        default=Path(
            r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
            r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
        ),
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    core_path = args.core
    if not core_path.is_file():
        fail(f"missing Core.zip: {core_path}")
    with zipfile.ZipFile(core_path) as core:
        validate_overrides(repo, core)
        validate_installed_units(core)
    validate_overlay_source(repo)
    validate_csproj(repo)
    print("bulwark-ability-repair-contract: ok")


if __name__ == "__main__":
    main()
