#!/usr/bin/env python3
"""Gate: unit design tables (custom_factions/unit_designs/<faction>.json) and their Core readback.

    python tools/validate_homm3_unit_design_table.py [--core Core.zip] [--static-only]

Plan: docs/unit_rebalance_plan_20261120.md. Applied by tools/release_port/homm3_unit_design_table.py
inside apply_release_core_overlay.py.

Static (no Core): for every faction table
  * the table lists exactly the faction's manifest unit lines;
  * upgrade and alternate share gold and squadValue, differ in at least 3 of the 7 stats, neither falls below the base form, and each has a larger kit
    than the base;
  * the two alternates carry one role of each trade side;
  * no card text reads as chance-based;
  * the generated plugin rule table (Homm3UnitKitRules.g.cs) matches the tables' runtime kit entries.

Core readback (--core, default the installed Golden Era Core.zip) for every listed unit
  * stats, gold, squadValue and the xHomm3UnitDesign marker read back from the table;
  * effective output (tools/release_port/unit_power_model.py, bands calibrated on vanilla): weekly power
    within 0.85..1.15 of the vanilla median of the unit's tier and form, offence and toughness under the
    vanilla peak, and the two alternates within 0.10 of each other;
  * every one of the 7 stats lies inside the min..max band of vanilla faction units of the same tier
    and form (base vs upgraded), measured from the same Core;
  * the card shows exactly one entry per kit item, every card text sid resolves in English, every
    referenced buff exists, and active Focus costs sit in the tier's allowed range.

Proof tier: generated artifact or deployed payload, whichever Core is passed. Not runtime proof:
whether each ability behaves as its card says is an in-game check (docs/ingame_check_queue.md).
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))
import homm3_unit_design_table as design  # noqa: E402
import homm3_upgrade_pair_parity as parity  # noqa: E402
import build_unit_kit_runtime_table as runtime_table  # noqa: E402

CORE_ZIP = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
                "/HeroesOldenEra_Data/StreamingAssets/Core.zip")
VANILLA_FACTIONS = {"human", "nature", "dungeon", "demon", "undead", "unfrozen"}


def load_core(core: Path) -> tuple[dict[str, dict], dict[str, dict], set[str], set[str]]:
    logic: dict[str, dict] = {}
    views: dict[str, dict] = {}
    texts: set[str] = set()
    buffs: set[str] = set()
    with zipfile.ZipFile(core) as archive:
        for name in archive.namelist():
            if not name.endswith(".json"):
                continue
            if name.startswith("DB/units/units_logics/") or name.startswith("DB/units/units_views/"):
                target = logic if "/units_logics/" in name else views
                for row in json.loads(archive.read(name).decode("utf-8-sig")).get("array") or []:
                    if isinstance(row, dict) and isinstance(row.get("id"), str):
                        target[row["id"]] = row
            elif name.startswith("DB/buffs/"):
                for row in json.loads(archive.read(name).decode("utf-8-sig")).get("array") or []:
                    if isinstance(row, dict) and isinstance(row.get("id"), str):
                        buffs.add(row["id"])
            elif name.startswith("Lang/english/texts/"):
                doc = json.loads(archive.read(name).decode("utf-8-sig"))
                for row in (doc.get("tokens") or doc.get("array") or []) if isinstance(doc, dict) else []:
                    if isinstance(row, dict) and isinstance(row.get("sid"), str) and row.get("text"):
                        texts.add(row["sid"])
    return logic, views, texts, buffs


def vanilla_bands(logic: dict[str, dict]) -> dict[tuple[int, bool], dict[str, tuple[float, float]]]:
    """(tier, is_upgraded) -> stat -> (min, max) over vanilla faction units in this Core."""
    samples: dict[tuple[int, bool], dict[str, list[float]]] = {}
    for sid, row in logic.items():
        if row.get("fraction") not in VANILLA_FACTIONS or not isinstance(row.get("tier"), int):
            continue
        if not (row.get("upgradeSid") or row.get("baseSid")):
            continue
        stats = row.get("stats") or {}
        if any(not isinstance(stats.get(key), (int, float)) for key in design.STAT_KEYS):
            continue
        bucket = samples.setdefault((row["tier"], bool(row.get("baseSid"))), {})
        for key in design.STAT_KEYS:
            bucket.setdefault(key, []).append(stats[key])
    return {group: {key: (min(values), max(values)) for key, values in stats.items()} for group, stats in samples.items()}


def check_core(doc: dict, core: tuple[dict[str, dict], dict[str, dict], set[str], set[str]]) -> list[str]:
    logic, views, texts, buffs = core
    errors: list[str] = []
    bands = vanilla_bands(logic)
    for sid, unit in doc["units"].items():
        row, view = logic.get(sid), views.get(sid)
        if row is None or view is None:
            errors.append(f"{sid}: no logic/view row in the Core")
            continue
        stats = row["stats"]
        for key in design.STAT_KEYS:
            if stats.get(key) != unit["stats"][key]:
                errors.append(f"{sid}: Core stats.{key}={stats.get(key)!r}, table {unit['stats'][key]!r}")
        gold = [c.get("cost") for c in row["unitCost"]["costResArray"] if c.get("name") == "gold"]
        if gold != [unit["gold"]] or row.get("squadValue") != unit["squadValue"]:
            errors.append(f"{sid}: Core gold/squadValue {gold}/{row.get('squadValue')}, table {unit['gold']}/{unit['squadValue']}")
        if not isinstance(row.get("xHomm3UnitDesign"), dict):
            errors.append(f"{sid}: Core row has no xHomm3UnitDesign marker")
        band = bands.get((row["tier"], bool(row.get("baseSid"))))
        if band is None:
            errors.append(f"{sid}: no vanilla band for tier {row['tier']}")
        else:
            for key in design.STAT_KEYS:
                low, high = band[key]
                if not low <= unit["stats"][key] <= high:
                    errors.append(f"{sid}: {key}={unit['stats'][key]} outside vanilla tier {row['tier']} band {low:g}..{high:g}")
        low_focus, high_focus = design.FOCUS_BY_TIER[row["tier"]]
        actives = [entry for entry in unit["kit"] if entry["k"] in design.ACTIVE_KEYWORDS]
        # Runtime entries that only back an active (abilityOnly / card false / no text) show no card of their own.
        passives = [entry for entry in unit["kit"] if entry["k"] not in design.ACTIVE_KEYWORDS and entry["k"] != "alt_swirl"
                    and not design.runtime_mirror(entry)]
        if len(row.get("abilities") or []) != len(actives) or len(view.get("abilities") or []) != len(actives):
            errors.append(f"{sid}: {len(actives)} active kit item(s) but Core has {len(row.get('abilities') or [])} logic / {len(view.get('abilities') or [])} card")
        shown = [p for p in view.get("passives") or [] if p.get("name") not in design.VIEW_MARKER_PASSIVES]
        if len(shown) != len(passives):
            errors.append(f"{sid}: {len(passives)} passive kit item(s) but the card lists {len(shown)}")
        for ability in row.get("abilities") or []:
            focus = ability.get("energyLevel")
            if "xHomm3AbilityOverride" in ability:
                continue  # kept from an older contract with its own validator
            if not isinstance(focus, int) or not low_focus <= focus <= high_focus:
                errors.append(f"{sid}: active Focus cost {focus!r} outside tier {row['tier']} range {low_focus}..{high_focus}")
        cards = [c for bucket in ("passives", "abilities", "alternativeAttacks") for c in view.get(bucket) or []]
        for card in cards:
            for field in ("name", "description"):
                if card.get(field) not in texts:
                    errors.append(f"{sid}: card text {card.get(field)!r} has no English row")
            if not card.get("icon"):
                errors.append(f"{sid}: card {card.get('name')!r} has no icon")
        dealers = [a.get("damageDealer") or {} for bucket in ("defaultAttacks", "counterAttacks", "alternativeAttacks", "abilities") for a in row.get(bucket) or []]
        dealers += [a.get("damageDealer") or {} for p in row.get("passives") or [] for a in p.get("actions") or []]
        for dealer in dealers:
            buff = (dealer.get("buff") or {}).get("sid")
            if buff and buff not in buffs:
                errors.append(f"{sid}: references missing buff {buff!r}")
    return errors


def check_power(designs: dict, lines: list, core_path: Path) -> list[str]:
    """Effective-output gate (unit_power_model): each unit's weekly power inside the vanilla window of its tier
    and form, offence and toughness under the vanilla peak, and the two alternates close to each other."""
    import unit_power_model as model
    import unit_design_lab as lab
    errors: list[str] = []
    bands = model.load_bands()
    core = model.Core(core_path)
    extras = model.runtime_extras(designs)
    ratio: dict[str, float] = {}
    for doc in designs.values():
        for sid in doc["units"]:
            if sid not in core.units:
                continue
            score = model.score_unit(core, core.units[sid], bands["refs"], extras)
            errors += model.gate(score, bands)
            ratio[sid] = score["weeklyPower"] / bands["bands"][f"{score['tier']}:{score['variant']}"]["weeklyPower"]["median"]
    for line in lines:
        upg, alt = line[2], line[3]
        if upg in ratio and alt in ratio and abs(ratio[upg] - ratio[alt]) > lab.PAIR_GAP:
            errors.append(f"{upg}/{alt}: alternates' power {ratio[upg]:.2f}x vs {ratio[alt]:.2f}x differ by more than {lab.PAIR_GAP}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", "--core-zip", dest="core", type=Path, default=CORE_ZIP)
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args()
    try:
        designs = design.load_designs()
        lines = parity.unit_lines(parity.load_enabled_manifests())
        core = None if args.static_only else load_core(args.core)
    except (RuntimeError, OSError, KeyError, ValueError, zipfile.BadZipFile) as ex:
        print(f"ERROR: {ex}")
        return 1
    errors: list[str] = []
    for faction, doc in designs.items():
        faction_lines = [line[1:] for line in lines if line[0] == faction]
        if not faction_lines:
            errors.append(f"{faction}: design table for a faction with no enabled manifest unit lines")
        errors += design.check_design(doc, faction_lines)
        if core is not None:
            errors += check_core(doc, core)
    if core is not None:
        errors += check_power(designs, lines, args.core)
    # Plugin-side rules (Grudge, Strangle, Covering Fire) come from a generated C# table: it must match.
    try:
        generated = runtime_table.render(designs)
        on_disk = runtime_table.OUTPUT.read_text(encoding="utf-8").replace(chr(13), "") if runtime_table.OUTPUT.is_file() else None
        if on_disk != generated:
            errors.append(f"{runtime_table.OUTPUT.name} is stale; run tools/release_port/build_unit_kit_runtime_table.py")
    except RuntimeError as ex:
        errors.append(str(ex))
    for error in errors:
        print(f"ERROR: {error}")
    units = sum(len(doc["units"]) for doc in designs.values())
    where = "static only" if core is None else str(args.core)
    if errors:
        print(f"homm3-unit-design-table: {len(errors)} error(s), {units} unit(s) in {len(designs)} faction(s) ({where})")
        return 1
    print(f"homm3-unit-design-table: OK, {units} unit(s) in {len(designs)} faction(s) ({where})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
