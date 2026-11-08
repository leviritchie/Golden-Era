#!/usr/bin/env python3
"""Fail-closed validator for tools/homm3_import/faction_concepts/homm3_neutral.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from homm3_neutral_catalog import (  # noqa: E402
    NEUTRAL_CATALOG_PATH,
    catalog_dwellings,
    catalog_units,
    load_homm3_neutral_catalog,
    pool_eligible_unit_sids,
    unit_logic_path,
    unit_view_path,
)
from validate_custom_faction_manifests import Validation  # noqa: E402

REQUIRED_STAT_KEYS = (
    "hp",
    "offence",
    "defence",
    "damageMin",
    "damageMax",
    "initiative",
    "speed",
    "squadValue",
    "gold",
)


# Native OE tier bands: min/max over the six native factions plus native neutrals
# (avatars, peasants, undead_peasant and lich_dragon excluded), pinned per explicit game
# target. validate_neutral_kits_in_core recomputes them from the Core it is given and fails
# if the pin for the named target has drifted.
# - golden_era: the active modded install. Read from the Golden Era Core on 2026-09-26; GE now
#   runs 25672315 (GameAssembly d9972b0e) and its Core matched the 25672315 bands on 2026-10-22,
#   so it pins the same table.
# - steam_25509697: read from the vanilla Steam 25509697 Core on 2026-10-01 (port Core
#   option A, user decision): t2/t3/t5/t6/t7 differ from Golden Era.
# - steam_25672315: read from the vanilla Steam 25672315 Core on 2026-10-02 (hotfix); equal to
#   steam_25509697 (the hotfix changed no DB/units row), so it pins the same table.
# The target is always named by the caller (--neutral-band-target / band_target); it is never
# inferred from the Core's contents, and an unknown target fails closed. Omitting it means
# DEFAULT_NEUTRAL_BAND_TARGET, the active modded runtime target named in AGENTS.md.
NATIVE_TIER_BAND_FOLDERS = ("humans", "nature", "dungeon", "undead", "demon", "unfrozen", "neutral")
NATIVE_TIER_BAND_EXCLUDED_IDS = {
    "avatar",
    "avatar_nature",
    "avatar_unfrozen",
    "peasant",
    "peasant_normal",
    "undead_peasant",
    "lich_dragon",
}
BAND_STAT_KEYS = ("hp", "offence", "defence", "damageMin", "damageMax", "initiative", "speed", "squadValue", "gold")
STEAM_25509697_NATIVE_TIER_BANDS: dict[int, dict[str, tuple[int, int]]] = {
    1: {"hp": (6, 15), "offence": (2, 6), "defence": (1, 8), "damageMin": (1, 6), "damageMax": (2, 6), "initiative": (4, 8), "speed": (2, 8), "squadValue": (29, 121), "gold": (35, 150)},
    2: {"hp": (6, 18), "offence": (3, 9), "defence": (0, 7), "damageMin": (2, 4), "damageMax": (3, 8), "initiative": (4, 9), "speed": (3, 7), "squadValue": (83, 216), "gold": (95, 250)},
    3: {"hp": (14, 45), "offence": (4, 9), "defence": (6, 11), "damageMin": (3, 7), "damageMax": (5, 12), "initiative": (1, 12), "speed": (2, 7), "squadValue": (110, 340), "gold": (120, 360)},
    4: {"hp": (30, 50), "offence": (9, 16), "defence": (9, 18), "damageMin": (6, 14), "damageMax": (9, 18), "initiative": (4, 13), "speed": (2, 8), "squadValue": (244, 657), "gold": (240, 630)},
    5: {"hp": (45, 95), "offence": (12, 20), "defence": (12, 22), "damageMin": (10, 20), "damageMax": (14, 20), "initiative": (4, 13), "speed": (2, 8), "squadValue": (345, 1366), "gold": (320, 1220)},
    6: {"hp": (75, 160), "offence": (19, 30), "defence": (18, 30), "damageMin": (12, 30), "damageMax": (14, 38), "initiative": (5, 13), "speed": (3, 8), "squadValue": (852, 2273), "gold": (700, 1900)},
    7: {"hp": (150, 400), "offence": (22, 40), "defence": (20, 40), "damageMin": (25, 65), "damageMax": (25, 75), "initiative": (7, 16), "speed": (4, 11), "squadValue": (1875, 8064), "gold": (1200, 5000)},
}
NATIVE_TIER_BANDS_BY_TARGET: dict[str, dict[int, dict[str, tuple[int, int]]]] = {
    "golden_era": STEAM_25509697_NATIVE_TIER_BANDS,
    "steam_25509697": STEAM_25509697_NATIVE_TIER_BANDS,
    "steam_25672315": STEAM_25509697_NATIVE_TIER_BANDS,
}
NEUTRAL_BAND_TARGETS: tuple[str, ...] = tuple(NATIVE_TIER_BANDS_BY_TARGET)
DEFAULT_NEUTRAL_BAND_TARGET = "golden_era"


def native_tier_bands_for_target(target: str) -> dict[int, dict[str, tuple[int, int]]]:
    """Pinned bands for an explicitly named game target; unknown targets fail closed."""
    bands = NATIVE_TIER_BANDS_BY_TARGET.get(target)
    if bands is None:
        raise ValueError(f"unknown neutral band target {target!r}; expected one of {NEUTRAL_BAND_TARGETS}")
    return bands


BAND_TOLERANCE = 0.20
# Native OE active counts: t1 units carry none, the rest one or two, t7 bosses up to four.
MAX_ACTIVES_BY_TIER = {1: 0, 2: 1, 3: 2, 4: 2, 5: 2, 6: 2, 7: 4}
KIT_PROFILES = ("living", "undead", "construct", "dragon", "native_donor", "hand_authored")
KIT_MECHANICS = (
    "positive_luck",
    "no_retaliation",
    "unlimited_retaliation",
    "sharpshooter",
    "free_shooting",
    "regeneration",
    "magic_resistance",
    "magic_level_immunity",
    "fearless",
    "luck_aura",
)
OWN_TEXT_MECHANICS = {"regeneration", "magic_resistance", "luck_aura"}
LIBRARY_ACTIVE_KINDS = {
    "stone_gaze", "poison_decay", "attack_defense_debuff", "disrupting_ray", "curse", "weakness_ray",
    "magnetic_slow", "misfortune", "fearsome", "mirth_spell", "fortune_spell", "blind", "stunning_blow",
    "root_bind", "thunderbolt", "mana_transfer", "bless_spell", "repair", "animate_dead", "death_stare",
}
# The HoMM3/HotA identity each neutral must keep (docs/homm3_neutral_oe_kits.md):
# sid -> (tier, profile, required actives, required mechanics).
EXPECTED_NEUTRAL_KITS: dict[str, tuple[int, str, tuple[str, ...], tuple[str, ...]]] = {
    "h3_peasant": (1, "native_donor", (), ()),
    "h3_neutral_halfling": (1, "living", (), ("positive_luck",)),
    "h3_boar": (2, "living", (), ()),
    "h3_rogue": (2, "living", (), ("no_retaliation",)),
    "h3_leprechaun": (2, "living", ("fortune_spell",), ("luck_aura",)),
    "h3_nomad": (3, "living", (), ()),
    "h3_mummy": (3, "undead", ("curse",), ()),
    "h3_sharpshooter": (4, "living", (), ("sharpshooter",)),
    "h3_satyr": (4, "living", ("mirth_spell",), ()),
    "h3_steel_golem": (4, "construct", (), ("magic_resistance",)),
    "h3_troll": (5, "living", (), ("regeneration",)),
    "h3_fangarm": (5, "hand_authored", (), ()),
    "h3_enchanter": (6, "living", ("bless_spell", "magnetic_slow"), ("free_shooting",)),
    "h3_faerie_dragon": (7, "native_donor", ("thunderbolt",), ()),
    "h3_rust_dragon": (7, "dragon", ("disrupting_ray",), ()),
    "h3_crystal_dragon": (7, "dragon", (), ("magic_resistance",)),
    "h3_azure_dragon": (7, "dragon", ("fearsome",), ("magic_level_immunity", "fearless")),
}
# Donor stat keys that carry a donor faction mechanic and must not survive on a rebuilt kit.
DONOR_MECHANIC_STAT_KEYS = ("damagePerHex", "armorPen", "attackPen", "alwaysMinDmg", "alwaysTakeMinDmg")


def band_violations(tier: int, stats: dict[str, Any], bands: dict[int, dict[str, tuple[int, int]]]) -> list[str]:
    band = bands.get(tier)
    if band is None:
        return [f"no native band for tier {tier}"]
    out: list[str] = []
    for key in BAND_STAT_KEYS:
        lo, hi = band[key]
        value = stats.get(key)
        if not isinstance(value, (int, float)):
            out.append(f"{key} missing")
            continue
        if value < lo * (1 - BAND_TOLERANCE) or value > hi * (1 + BAND_TOLERANCE):
            out.append(f"{key}={value} outside t{tier} band {lo}-{hi} (+/-{int(BAND_TOLERANCE * 100)}%)")
    return out


def validate_oe_kit(row: dict[str, Any], v: Validation) -> None:
    sid = str(row.get("sid"))
    label = f"homm3_neutral:{sid}.oeKit"
    kit = row.get("oeKit")
    if not isinstance(kit, dict):
        v.error(f"{label}: missing oeKit (every neutral needs its own OE kit)")
        return
    profile = kit.get("profile")
    if profile not in KIT_PROFILES:
        v.error(f"{label}: profile {profile!r} not in {KIT_PROFILES}")
    for key in ("design", "homm3Identity"):
        if not isinstance(kit.get(key), str) or not kit[key].strip():
            v.error(f"{label}: missing {key} rationale")
    actives = kit.get("actives")
    if not isinstance(actives, list):
        v.error(f"{label}: actives must be a list")
        actives = []
    kinds = []
    for active in actives:
        kind = active.get("kind") if isinstance(active, dict) else None
        if kind not in LIBRARY_ACTIVE_KINDS:
            v.error(f"{label}: active {kind!r} is not a library kind")
            continue
        kinds.append(kind)
        if ("name" in active) != ("description" in active):
            v.error(f"{label}: active {kind} own text needs both name and description")
    mechanics = kit.get("mechanics")
    if not isinstance(mechanics, list):
        v.error(f"{label}: mechanics must be a list")
        mechanics = []
    mechs = []
    for mech in mechanics:
        name = mech.get("mech") if isinstance(mech, dict) else None
        if name not in KIT_MECHANICS:
            v.error(f"{label}: mechanic {name!r} not in {KIT_MECHANICS}")
            continue
        mechs.append(name)
        if name in OWN_TEXT_MECHANICS and not (isinstance(mech.get("name"), str) and isinstance(mech.get("description"), str)):
            v.error(f"{label}: mechanic {name} needs its own name and description")
        if name in {"regeneration", "magic_resistance", "magic_level_immunity", "luck_aura"} and not isinstance(mech.get("value"), (int, float)):
            v.error(f"{label}: mechanic {name} needs a numeric value")
    tier = row.get("tier")
    donor_actives = kit.get("donorActives") is True
    if isinstance(tier, int) and not donor_actives and len(kinds) > MAX_ACTIVES_BY_TIER.get(tier, 0):
        v.error(f"{label}: {len(kinds)} actives exceed the native t{tier} maximum {MAX_ACTIVES_BY_TIER.get(tier, 0)}")
    expected = EXPECTED_NEUTRAL_KITS.get(sid)
    if expected is None:
        v.error(f"{label}: no pinned EXPECTED_NEUTRAL_KITS entry (add the intended kit to the validator)")
    else:
        exp_tier, exp_profile, exp_actives, exp_mechs = expected
        if tier != exp_tier:
            v.error(f"{label}: tier {tier} != intended HoMM3-level tier {exp_tier}")
        if profile != exp_profile:
            v.error(f"{label}: profile {profile} != intended {exp_profile}")
        for kind in exp_actives:
            if kind not in kinds:
                v.error(f"{label}: identity active {kind} missing")
        for mech in exp_mechs:
            if mech not in mechs:
                v.error(f"{label}: identity mechanic {mech} missing")
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    if isinstance(tier, int):
        exempt = kit.get("bandExempt")
        # The catalog ships to every target, so it must sit inside every target's bands.
        if not (isinstance(exempt, str) and exempt.strip()):
            for target in NEUTRAL_BAND_TARGETS:
                for problem in band_violations(tier, stats, NATIVE_TIER_BANDS_BY_TARGET[target]):
                    v.error(f"homm3_neutral:{sid}: {problem} [{target}]")
    dwelling = row.get("dwelling")
    if isinstance(dwelling, dict) and "costGold" in dwelling and dwelling.get("costGold") != stats.get("gold"):
        v.error(f"homm3_neutral:{sid}: dwelling.costGold {dwelling.get('costGold')} != stats.gold {stats.get('gold')}")


def _require_str(row: dict[str, Any], key: str, v: Validation, label: str) -> str | None:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        v.error(f"{label}: missing string {key}")
        return None
    return value.strip()


def validate_catalog(catalog: dict[str, Any], v: Validation) -> None:
    if int(catalog.get("schemaVersion") or 0) != 1:
        v.error("homm3_neutral: schemaVersion must be 1")
    core = catalog.get("coreOverlay")
    if not isinstance(core, dict) or core.get("enabled") is not True:
        v.error("homm3_neutral: coreOverlay.enabled must be true")
    for key in ("logicFolder", "viewFolder", "squadTree", "directDwellingPrefix", "donorDwellingSid"):
        if not isinstance((core or {}).get(key), str) or not str((core or {}).get(key)).strip():
            v.error(f"homm3_neutral: coreOverlay.{key} must be a non-empty string")

    seen_sids: set[str] = set()
    seen_barracks: set[str] = set()
    seen_defs: set[str] = set()
    for row in catalog_units(catalog):
        sid = _require_str(row, "sid", v, "unit")
        if sid is None:
            continue
        label = f"homm3_neutral:{sid}"
        if sid in seen_sids:
            v.error(f"{label}: duplicate sid")
        seen_sids.add(sid)
        if not sid.startswith("h3_"):
            v.error(f"{label}: sid must start with h3_")
        if sid == "h3_cannon":
            v.error(f"{label}: Cannon must stay out of the neutral catalog")
        if sid == "h3_halfling":
            v.error(f"{label}: use h3_neutral_halfling to avoid Factory collision")
        for key in ("displayName", "donorFactionSid", "donorUnitSid", "nativeBiome", "ai", "bundleName"):
            _require_str(row, key, v, label)
        if not isinstance(row.get("tier"), int) or int(row["tier"]) < 1:
            v.error(f"{label}: tier must be a positive int")
        if not isinstance(row.get("poolEligible"), bool):
            v.error(f"{label}: poolEligible must be bool")
        tags = row.get("tags")
        if not isinstance(tags, list) or "neutral" not in tags:
            v.error(f"{label}: tags must include neutral")
        stats = row.get("stats")
        if not isinstance(stats, dict):
            v.error(f"{label}: stats must be an object")
        else:
            for key in REQUIRED_STAT_KEYS:
                if key not in stats:
                    v.error(f"{label}: stats missing {key}")
        validate_oe_kit(row, v)
        dwelling = row.get("dwelling")
        if dwelling is None:
            continue
        if not isinstance(dwelling, dict):
            v.error(f"{label}: dwelling must be an object when present")
            continue
        for key in ("name", "defName", "barracksSid"):
            _require_str(dwelling, key, v, f"{label}.dwelling")
        barracks_sid = str(dwelling.get("barracksSid") or "")
        if barracks_sid and not barracks_sid.startswith("barracks_homm3_neutral_"):
            v.error(f"{label}: barracksSid must use barracks_homm3_neutral_ prefix")
        if barracks_sid in seen_barracks:
            v.error(f"{label}: duplicate barracksSid {barracks_sid}")
        seen_barracks.add(barracks_sid)
        def_name = str(dwelling.get("defName") or "")
        if def_name.lower() in seen_defs:
            v.error(f"{label}: duplicate dwelling defName {def_name}")
        seen_defs.add(def_name.lower())
        growth = dwelling.get("growth")
        if not isinstance(growth, int) or growth < 1:
            v.error(f"{label}: dwelling.growth must be a positive int")

    missing_kits = set(EXPECTED_NEUTRAL_KITS) - seen_sids
    if missing_kits:
        v.error(f"homm3_neutral: pinned kits for sids absent from the catalog: {sorted(missing_kits)}")

    pool = set(pool_eligible_unit_sids(catalog))
    if "h3_fangarm" not in pool:
        v.error("homm3_neutral: h3_fangarm must be poolEligible")
    if not catalog_dwellings(catalog):
        v.error("homm3_neutral: expected at least one dwelling entry")

    # Campaign DEF map must resolve every catalog dwelling animation.
    try:
        repo_root = Path(__file__).resolve().parents[1]
        campaign_dir = repo_root / "experiments" / "campaign_port_poc"
        if str(campaign_dir) not in sys.path:
            sys.path.insert(0, str(campaign_dir))
        from homm3_external_dwelling_map import lookup_creature_generator_replacement

        for dwelling in catalog_dwellings(catalog):
            def_name = str(dwelling["defName"])
            hit = lookup_creature_generator_replacement(def_name)
            if hit is None:
                v.error(f"homm3_neutral: dwelling DEF {def_name} missing from CREATURE_GENERATOR_ANIMATION_EXACT_MAP")
                continue
            creature_key = str(dwelling["barracksSid"]).removeprefix("barracks_homm3_neutral_")
            expected = f"homm3_landon_barracks_neutral_{creature_key}"
            if hit[0] != expected:
                v.error(f"homm3_neutral: dwelling DEF {def_name} maps to {hit[0]}, expected {expected}")
    except Exception as ex:
        v.error(f"homm3_neutral: dwelling DEF map check failed: {ex}")


def validate_optional_core(core_zip: Path | None, catalog: dict[str, Any], v: Validation) -> None:
    if core_zip is None or not core_zip.is_file():
        return
    import zipfile

    with zipfile.ZipFile(core_zip) as zf:
        names = set(zf.namelist())
        for row in catalog_units(catalog):
            sid = str(row["sid"])
            logic = unit_logic_path(sid, catalog)
            view = unit_view_path(sid, catalog)
            if logic not in names:
                v.error(f"core missing neutral logic row: {logic}")
            if view not in names:
                v.error(f"core missing neutral view row: {view}")
            if row.get("handAuthoredCore") is True:
                continue
            donor_faction = str(row["donorFactionSid"])
            donor_unit = str(row["donorUnitSid"])
            donor_logic = f"DB/units/units_logics/{donor_faction}/{donor_unit}_l.json"
            if donor_logic not in names:
                v.error(f"{sid}: missing donor logic {donor_logic}")
        for dwelling in catalog_dwellings(catalog):
            barracks_sid = str(dwelling["barracksSid"])
            # Presence in merged interactables/hires is checked after overlay apply.
            _ = barracks_sid


def native_tier_bands_from_core(zf: Any) -> dict[int, dict[str, tuple[int, int]]]:
    bands: dict[int, dict[str, tuple[int, int]]] = {}
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) != 5 or parts[:3] != ["DB", "units", "units_logics"] or not name.endswith("_l.json"):
            continue
        if parts[3] not in NATIVE_TIER_BAND_FOLDERS:
            continue
        try:
            row = json.loads(zf.read(name).decode("utf-8-sig"))["array"][0]
        except (KeyError, IndexError, ValueError):
            continue
        rid = str(row.get("id") or "")
        if rid in NATIVE_TIER_BAND_EXCLUDED_IDS or rid.startswith("h3_"):
            continue
        stats = row.get("stats") or {}
        values = {key: stats.get(key) for key in BAND_STAT_KEYS[:7]}
        values["squadValue"] = row.get("squadValue")
        costs = ((row.get("unitCost") or {}).get("costResArray") or [{}])
        values["gold"] = next((c.get("cost") for c in costs if c.get("name") == "gold"), None)
        band = bands.setdefault(int(row.get("tier") or 0), {})
        for key, value in values.items():
            if not isinstance(value, (int, float)):
                continue
            lo, hi = band.get(key, (value, value))
            band[key] = (min(lo, value), max(hi, value))
    return bands


def validate_neutral_kits_in_core(
    core_zip: Path,
    catalog: dict[str, Any],
    v: Validation,
    *,
    band_target: str = DEFAULT_NEUTRAL_BAND_TARGET,
) -> None:
    """Read back every neutral's generated kit and stats from a built Core.zip.

    ``band_target`` names the game build the Core is for (see NATIVE_TIER_BANDS_BY_TARGET).
    """
    import zipfile

    try:
        pinned_bands = native_tier_bands_for_target(band_target)
    except ValueError as ex:
        v.error(f"homm3_neutral: {ex}")
        return
    with zipfile.ZipFile(core_zip) as zf:
        names = set(zf.namelist())
        live_bands = native_tier_bands_from_core(zf)
        for tier, band in pinned_bands.items():
            if live_bands.get(tier) != band:
                v.error(
                    f"homm3_neutral: pinned {band_target} native t{tier} band {band} drifted from Core "
                    f"{live_bands.get(tier)} (wrong --neutral-band-target, or the target's live data moved)"
                )

        def lang_sids(path: str) -> set[str]:
            if path not in names:
                return set()
            doc = json.loads(zf.read(path).decode("utf-8-sig"))
            return {str(t.get("sid")) for key in ("tokens", "array") for t in doc.get(key) or [] if isinstance(t, dict)}

        ability_lang = lang_sids("Lang/english/texts/unitsAbility.json")
        buff_ids: set[str] = set()
        for name in names:
            if name.startswith("DB/buffs/") and name.endswith(".json"):
                try:
                    doc = json.loads(zf.read(name).decode("utf-8-sig"))
                except ValueError:
                    continue
                buff_ids.update(str(r.get("id")) for r in doc.get("array") or [] if isinstance(r, dict))

        for row in catalog_units(catalog):
            sid = str(row["sid"])
            label = f"core homm3_neutral:{sid}"
            kit = row.get("oeKit") or {}
            logic_name = unit_logic_path(sid, catalog)
            view_name = unit_view_path(sid, catalog)
            if logic_name not in names or view_name not in names:
                v.error(f"{label}: logic/view row missing")
                continue
            logic = json.loads(zf.read(logic_name).decode("utf-8-sig"))["array"][0]
            view = json.loads(zf.read(view_name).decode("utf-8-sig"))["array"][0]
            stats = logic.get("stats") or {}
            if logic.get("tier") != row.get("tier"):
                v.error(f"{label}: tier {logic.get('tier')} != catalog {row.get('tier')}")
            for key in BAND_STAT_KEYS[:7]:
                if stats.get(key) != row["stats"].get(key):
                    v.error(f"{label}: {key} {stats.get(key)} != catalog {row['stats'].get(key)}")
            if logic.get("squadValue") != row["stats"].get("squadValue"):
                v.error(f"{label}: squadValue {logic.get('squadValue')} != catalog")
            gold = next((c.get("cost") for c in (logic.get("unitCost") or {}).get("costResArray") or [] if c.get("name") == "gold"), None)
            if gold != row["stats"].get("gold"):
                v.error(f"{label}: gold {gold} != catalog")
            if kit.get("profile") == "hand_authored":
                continue
            marker = logic.get("xHomm3NeutralOeKit")
            if not isinstance(marker, dict):
                v.error(f"{label}: missing xHomm3NeutralOeKit marker (kit applier did not run)")
            logic_abilities = logic.get("abilities") or []
            view_abilities = view.get("abilities") or []
            if len(logic_abilities) != len(view_abilities):
                v.error(f"{label}: {len(logic_abilities)} logic abilities vs {len(view_abilities)} view abilities")
            expected_count = len(kit.get("actives") or [])
            if kit.get("donorActives") is not True and len(logic_abilities) != expected_count:
                v.error(f"{label}: {len(logic_abilities)} actives != kit {expected_count} (donor actives leaked or kit dropped)")
            for ability in logic_abilities:
                buff = ((ability.get("damageDealer") or {}).get("buff") or {}).get("sid")
                if isinstance(buff, str) and buff not in buff_ids:
                    v.error(f"{label}: active buff {buff} is not defined in DB/buffs")
            if kit.get("profile") != "native_donor":
                for key in DONOR_MECHANIC_STAT_KEYS:
                    if key in stats:
                        v.error(f"{label}: donor mechanic stat {key} survived")
            mechs = {str(m.get("mech")): m for m in kit.get("mechanics") or [] if isinstance(m, dict)}
            passives_text = json.dumps(logic.get("passives") or [])
            if "regeneration" in mechs and "heal_percent" not in passives_text:
                v.error(f"{label}: regeneration passive missing")
            if "magic_resistance" in mechs:
                mods = (stats.get("inDmgMods") or {}).get("list") or []
                want = -float(mechs["magic_resistance"]["value"])
                if not any(m.get("t") == "magic_damage" and abs(float(m.get("v")) - want) < 1e-6 for m in mods):
                    v.error(f"{label}: magic_damage {want} modifier missing")
            if "no_retaliation" in mechs:
                for attack in (logic.get("defaultAttacks") or []) + (logic.get("alternativeAttacks") or []):
                    if (attack.get("damageDealer") or {}).get("triggerCounter") is not False:
                        v.error(f"{label}: an attack still triggers retaliation")
            if "sharpshooter" in mechs and not (stats.get("ignoreShootDmgBuff") and stats.get("ignoreShootingBlock")):
                v.error(f"{label}: sharpshooter flags missing")
            if "free_shooting" in mechs and not stats.get("ignoreShootingBlock"):
                v.error(f"{label}: free shooting flag missing")
            if "positive_luck" in mechs and int(stats.get("luckMin") or 0) < 1:
                v.error(f"{label}: positive luck floor missing")
            if "luck_aura" in mechs and ((logic.get("aura") or {}).get("data") or {}).get("stats", {}).get("luck") != mechs["luck_aura"]["value"]:
                v.error(f"{label}: luck aura missing")
            if "magic_level_immunity" in mechs and '"magic_level"' not in passives_text:
                v.error(f"{label}: magic level immunity missing")
            if "magic_level_immunity" not in mechs and kit.get("keepDonorPassives") is not True and '"magic_level"' in passives_text:
                v.error(f"{label}: donor spell-level immunity survived")
            if "fearless" in mechs and "homm3_cove_fearsome_effect" not in passives_text:
                v.error(f"{label}: fearless immunity missing")
            for card in (view.get("passives") or []) + view_abilities:
                name = str(card.get("name") or "")
                if name.startswith(f"{sid}_") and name not in ability_lang:
                    v.error(f"{label}: own card text {name} missing from unitsAbility.json")
                for kind in (a.get("kind") for a in kit.get("actives") or []):
                    if name == f"h3_common_ability_{kind}_name" and name not in ability_lang:
                        v.error(f"{label}: library card text {name} missing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=NEUTRAL_CATALOG_PATH)
    parser.add_argument("--core-zip", type=Path, default=None)
    parser.add_argument(
        "--neutral-band-target",
        choices=NEUTRAL_BAND_TARGETS,
        default=DEFAULT_NEUTRAL_BAND_TARGET,
        help="Game build the --core-zip is for; selects the pinned native tier bands (default: golden_era).",
    )
    args = parser.parse_args()
    v = Validation()
    catalog = load_homm3_neutral_catalog(args.catalog)
    validate_catalog(catalog, v)
    validate_optional_core(args.core_zip, catalog, v)
    if args.core_zip is not None and args.core_zip.is_file():
        validate_neutral_kits_in_core(args.core_zip, catalog, v, band_target=args.neutral_band_target)
    if v.errors:
        for err in v.errors:
            print(f"ERROR: {err}")
        return 1
    print(
        "OK homm3_neutral catalog: "
        f"units={len(catalog_units(catalog))} "
        f"poolEligible={len(pool_eligible_unit_sids(catalog))} "
        f"dwellings={len(catalog_dwellings(catalog))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
