#!/usr/bin/env python3
"""Fail-closed Bulwark ability uniqueness + upgrade-active coverage contract."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


FACTORY_FOCUS_DONOR_PREFIXES = (
    "space_1_magic_early_start",
    "space_5_magic_trap_jaws",
    "night_11_magic_vulnerability",
    "day_8_magic_taunt",
    "space_8_magic_carapace",
    "arbitrator:abilities:1",
)

# Authentic HotA Jotunn ally teleport may share Arbitrator ally teleport with no Factory twin.
# Yeti Rune Surge uses Sentinel Arina's Way (once-per-battle dispel + restore).
ALLOWLISTED_EFFECT_KEYS = {
    "arbitrator:abilities:0",
    "sentinel:abilities:0",
}

STANDARD_UPGRADE_SIDS = {
    "h3_kobold_foreman",
    "h3_argali",
    "h3_steel_elf",
    "h3_yeti_runemaster",
    "h3_great_shaman",
    "h3_war_mammoth",
    "h3_jotunn_warlord",
}

ALTERNATE_UPGRADE_SIDS = {
    "h3_kobold_upg_alt",
    "h3_mountain_ram_upg_alt",
    "h3_snow_elf_upg_alt",
    "h3_yeti_upg_alt",
    "h3_shaman_upg_alt",
    "h3_mammoth_upg_alt",
    "h3_jotunn_upg_alt",
}

UPGRADE_SIDS = STANDARD_UPGRADE_SIDS | ALTERNATE_UPGRADE_SIDS


def fail(message: str) -> None:
    raise SystemExit("bulwark-ability-uniqueness-contract: " + message)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def effect_key_donor(effect_key: str) -> str:
    key = (effect_key or "").strip()
    if ":level:" in key:
        return key.split(":level:", 1)[0]
    return key


def enabled_focus_specials(unit_override: dict[str, Any]) -> list[dict[str, Any]]:
    specials = unit_override.get("existingSpecials") or []
    if not isinstance(specials, list):
        return []
    out: list[dict[str, Any]] = []
    for special in specials:
        if not isinstance(special, dict):
            continue
        if special.get("enabled") is False:
            continue
        if special.get("slotKind") != "abilities":
            continue
        out.append(special)
    return out


def validate_ability_overrides(repo: Path) -> None:
    path = repo / "custom_factions" / "ability_overrides" / "homm3_bulwark.json"
    doc = read_json(path)
    if doc.get("factionSid") != "homm3_bulwark":
        fail("ability override factionSid must be homm3_bulwark")
    overrides = doc.get("unitOverrides")
    if not isinstance(overrides, dict):
        fail("unitOverrides must be an object")

    for sid in sorted(UPGRADE_SIDS):
        unit = overrides.get(sid)
        if not isinstance(unit, dict):
            fail(f"upgrade unit {sid} missing from ability_overrides")
        actives = enabled_focus_specials(unit)
        if not actives:
            fail(f"upgrade unit {sid} must keep at least one enabled Focus active")

    for sid, unit in overrides.items():
        if not isinstance(unit, dict):
            continue
        for special in enabled_focus_specials(unit):
            effect_key = str(special.get("effectKey") or "")
            if effect_key in ALLOWLISTED_EFFECT_KEYS:
                continue
            donor = effect_key_donor(effect_key)
            for banned in FACTORY_FOCUS_DONOR_PREFIXES:
                if donor == banned or effect_key.startswith(banned):
                    fail(
                        f"{sid} Focus effectKey {effect_key!r} overlaps Factory donor {banned!r}; "
                        "replace with a Bulwark-unique donor or allowlist explicitly"
                    )


def validate_runtime_owners(repo: Path) -> None:
    plugin = repo / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    unit_runtime = plugin / "Homm3BulwarkUnitAbilityRuntime.cs"
    runes_runtime = plugin / "Homm3BulwarkRunesRuntime.cs"
    plugin_cs = plugin / "Plugin.cs"
    for path in (unit_runtime, runes_runtime, plugin_cs):
        if not path.is_file():
            fail(f"missing required runtime owner: {path}")
    plugin_text = plugin_cs.read_text(encoding="utf-8")
    for needle in (
        "Homm3BulwarkUnitAbilityRuntime.TryRegister(_harmony, Log)",
        "Homm3BulwarkRunesRuntime.TryRegister(_harmony, Log)",
    ):
        if needle not in plugin_text:
            fail(f"Plugin.cs must register {needle}")

    unit_text = unit_runtime.read_text(encoding="utf-8")
    for needle in (
        "internal static class Homm3BulwarkUnitAbilityRuntime",
        "TryRegister(",
        "homm3_bulwark_frostbound_skies_speed_1",
        "homm3_bulwark_frostbound_skies_speed_2",
        "UnitConfigFlyMoveTypeValue",
        "Homm3DirectStateIdentity.TryResolveKey",
    ):
        if needle not in unit_text:
            fail(f"Homm3BulwarkUnitAbilityRuntime.cs must contain {needle!r}")
    if "magic_nairas_kiss_slow_effect" in unit_text:
        fail("Frostbound Skies must not use Naira's Kiss (Initiative+Speed) buff")
    if 'new[] { "isFlyer", "IsFlyer", "flyer", "Flyer" }' in unit_text:
        fail("Frostbound Skies must not probe readable isFlyer member names")
    if "RuntimeHelpers.GetHashCode(unit)" in unit_text:
        fail("Frostbound Skies must not dedupe with managed GetHashCode")

    runes_text = runes_runtime.read_text(encoding="utf-8")
    for needle in (
        "internal static class Homm3BulwarkRunesRuntime",
        "TryRegister(",
        "runtime-pending",
    ):
        if needle not in runes_text:
            fail(f"Homm3BulwarkRunesRuntime.cs must contain {needle!r}")


def validate_overlay_after_shot(repo: Path) -> None:
    overlay = repo / "tools" / "release_port" / "apply_release_core_overlay.py"
    text = overlay.read_text(encoding="utf-8")
    for needle in (
        "BULWARK_AFTER_SHOT_ICE_BY_SID",
        "h3_shaman_upg_alt",
        "h3_snow_elf_upg_alt",
        "magic_ice_bolt_effect_0",
        "BULWARK_FLYER_SLOW_SIDS",
    ):
        if needle not in text:
            fail(f"apply_release_core_overlay.py must contain {needle!r}")
    if re.search(r'BULWARK_AFTER_SHOT_ICE_BY_SID\s*=\s*\{[^}]*:\s*"magic_ice_bolt_effect"', text, re.S):
        fail("BULWARK_AFTER_SHOT_ICE_BY_SID must not use bare magic_ice_bolt_effect; Core only has leveled ids")


def validate_source_mechanics(repo: Path) -> None:
    path = repo / "custom_factions" / "source_mechanics" / "homm3_bulwark.json"
    doc = read_json(path)
    mechanics = doc.get("mechanics")
    if not isinstance(mechanics, list):
        fail("source_mechanics mechanics must be a list")
    ids = {str(item.get("id")) for item in mechanics if isinstance(item, dict)}
    required = {
        "bulwark.runes",
        "bulwark.focus_native_spell_dealers",
        "bulwark.rune_surge_arinas_way",
        "bulwark.free_shooting",
        "bulwark.argali_ice_immunity",
        "bulwark.after_shot_ice",
        "bulwark.jotunn_flyer_slow",
        "bulwark.war_mammoth_defend_defense",
        "bulwark.yeti_recovery",
        "bulwark.argali_spell_amp_aura",
    }
    missing = sorted(required - ids)
    if missing:
        fail(f"source_mechanics missing required Bulwark mechanic rows: {', '.join(missing)}")
    by_id = {str(item.get("id")): item for item in mechanics if isinstance(item, dict)}
    if by_id.get("bulwark.war_mammoth_defend_defense", {}).get("status") != "absent":
        fail("bulwark.war_mammoth_defend_defense must be absent until Defend correlation exists")
    if by_id.get("bulwark.yeti_recovery", {}).get("status") != "absent":
        fail("bulwark.yeti_recovery must be absent while Rune Surge substitutes Arina's Way")
    if by_id.get("bulwark.argali_spell_amp_aura", {}).get("status") != "absent":
        fail("bulwark.argali_spell_amp_aura must remain deliberately absent")


def validate_csproj(repo: Path) -> None:
    csproj = (
        repo
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "OfflineUnlockMod.csproj"
    )
    if not csproj.is_file():
        fail(f"missing csproj: {csproj}")
    text = csproj.read_text(encoding="utf-8-sig")
    if "ValidateHomm3BulwarkAbilityUniquenessContract" not in text:
        fail("OfflineUnlockMod.csproj must define ValidateHomm3BulwarkAbilityUniquenessContract")
    if "validate_homm3_bulwark_ability_uniqueness_contract.py" not in text:
        fail("OfflineUnlockMod.csproj must reference validate_homm3_bulwark_ability_uniqueness_contract.py")
    root = ET.fromstring(text)
    target = next(
        (
            node
            for node in root.iter()
            if node.tag.endswith("Target")
            and node.attrib.get("Name") == "ValidateHomm3BulwarkAbilityUniquenessContract"
        ),
        None,
    )
    if target is None:
        fail("OfflineUnlockMod.csproj must define ValidateHomm3BulwarkAbilityUniquenessContract")
    if target.attrib.get("BeforeTargets") != "BeforeBuild":
        fail("ValidateHomm3BulwarkAbilityUniquenessContract must run BeforeTargets=BeforeBuild")
    if "Homm3BulwarkAbilityUniquenessValidator" not in text:
        fail("ValidateHomm3BulwarkAbilityUniquenessContract must define Homm3BulwarkAbilityUniquenessValidator")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    validate_ability_overrides(repo)
    validate_runtime_owners(repo)
    validate_overlay_after_shot(repo)
    validate_source_mechanics(repo)
    validate_csproj(repo)
    print("bulwark-ability-uniqueness-contract: ok")


if __name__ == "__main__":
    main()
