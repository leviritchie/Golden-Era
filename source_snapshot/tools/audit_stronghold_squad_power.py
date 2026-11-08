#!/usr/bin/env python3
"""Audit Stronghold unit stat power against squadValue and squad templates.

Reads the live release Core.zip by default and writes a markdown report under
docs/. The audit is intentionally static: it uses unit logic JSON and squad
config JSON, not runtime probes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path


DEFAULT_CORE = Path(
    "Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_OUT = Path("docs/homm3_stronghold_squad_value_audit.md")

VANILLA_FACTIONS = ["humans", "dungeon", "nature", "undead", "demons", "unfrozen"]
STRONGHOLD = "homm3_stronghold"
ALL_FACTIONS = VANILLA_FACTIONS + [STRONGHOLD]
STAT_KEYS = ["hp", "offence", "defence", "avgDmg", "initiative", "speed"]


def load_core(core_zip: Path):
    units = {}
    squads = []
    with zipfile.ZipFile(core_zip) as zf:
        for name in zf.namelist():
            match = re.match(r"DB/units/units_logics/([^/]+)/([^/]+)\.json$", name)
            if not match or match.group(1) not in ALL_FACTIONS:
                continue
            data = json.loads(zf.read(name))
            for row in data.get("array", []):
                if row.get("fraction") in ALL_FACTIONS:
                    row["_path"] = name
                    stats = row.get("stats", {})
                    row["_auditStats"] = {
                        "hp": number(stats.get("hp")),
                        "offence": number(stats.get("offence")),
                        "defence": number(stats.get("defence")),
                        "avgDmg": (number(stats.get("damageMin")) + number(stats.get("damageMax"))) / 2,
                        "initiative": number(stats.get("initiative")),
                        "speed": number(stats.get("speed")),
                    }
                    units[row["id"]] = row

        for name in zf.namelist():
            match = re.match(r"DB/squads/squads_([^/]+)/.*\.json$", name)
            if not match or match.group(1) not in ALL_FACTIONS:
                continue
            data = json.loads(zf.read(name))
            for row in data.get("array", []):
                if row.get("fraction") not in ALL_FACTIONS:
                    continue
                base_units = row.get("baseSquad", {}).get("units") or []
                if not base_units:
                    continue
                ids = [item.get("s") for item in base_units]
                if not all(unit_id in units for unit_id in ids):
                    continue
                vals = [number(item.get("v")) for item in base_units]
                eq_counts = [
                    vals[i] / max(1, number(units[unit_id].get("squadValue")))
                    for i, unit_id in enumerate(ids)
                ]
                squads.append(
                    {
                        "id": row.get("id"),
                        "path": name,
                        "faction": row.get("fraction"),
                        "tier": number(row.get("tier")),
                        "n": len(ids),
                        "ids": ids,
                        "vals": vals,
                        "base_total": sum(vals),
                        "required": number(row.get("dynamicSquad", {}).get("requiredValue")),
                        "random_max": number(row.get("randomSquad", {}).get("maxValue")),
                        "eq_sum": sum(eq_counts),
                    }
                )
    return units, squads


def number(value):
    if value is None:
        return 0
    return float(value)


def variant(unit_id: str) -> str:
    if unit_id.endswith("_upg_alt"):
        return "alt"
    if unit_id.endswith("_upg"):
        return "upg"
    return "base"


def z(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    sd = statistics.pstdev(values)
    if sd == 0:
        return 0.0
    return (value - statistics.mean(values)) / sd


def fmt(value: float, digits: int = 2) -> str:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "n/a"
    return f"{value:.{digits}f}"


def unit_rows(units):
    by_bucket = defaultdict(list)
    for row in units.values():
        if row.get("fraction") in VANILLA_FACTIONS:
            by_bucket[(int(row.get("tier", 0)), variant(row["id"]))].append(row)

    rows = []
    for row in units.values():
        if row.get("fraction") != STRONGHOLD:
            continue
        bucket = by_bucket[(int(row.get("tier", 0)), variant(row["id"]))]
        stat_zs = []
        for key in STAT_KEYS:
            stat_zs.append(z(row["_auditStats"][key], [item["_auditStats"][key] for item in bucket]))
        stat_alignment = statistics.mean(stat_zs)
        sv_values = [number(item.get("squadValue")) for item in bucket]
        sv_avg = statistics.mean(sv_values)
        sv_ratio = number(row.get("squadValue")) / sv_avg if sv_avg else 0
        rows.append(
            {
                "tier": int(row.get("tier", 0)),
                "variant": variant(row["id"]),
                "id": row["id"],
                "squadValue": int(number(row.get("squadValue"))),
                "stat_alignment": stat_alignment,
                "sv_ratio": sv_ratio,
                "sv_avg": sv_avg,
                "stat_minus_sv": stat_alignment - z(number(row.get("squadValue")), sv_values),
            }
        )
    return sorted(rows, key=lambda r: (r["tier"], {"base": 0, "upg": 1, "alt": 2}[r["variant"]]))


def squad_rows(squads):
    rows = []
    for key in sorted({(row["tier"], row["n"]) for row in squads if row["faction"] == STRONGHOLD}):
        tier, n = key
        sh = [row for row in squads if row["faction"] == STRONGHOLD and row["tier"] == tier and row["n"] == n]
        vanilla = [row for row in squads if row["faction"] != STRONGHOLD and row["tier"] == tier and row["n"] == n]
        if not sh or not vanilla:
            continue
        rows.append(
            {
                "tier": int(tier),
                "n": int(n),
                "sh_count": len(sh),
                "sh_budget": statistics.mean([row["base_total"] for row in sh]),
                "vanilla_budget": statistics.mean([row["base_total"] for row in vanilla]),
                "sh_eq": statistics.mean([row["eq_sum"] for row in sh]),
                "vanilla_eq": statistics.mean([row["eq_sum"] for row in vanilla]),
                "eq_ratio": statistics.mean([row["eq_sum"] for row in sh])
                / statistics.mean([row["eq_sum"] for row in vanilla]),
            }
        )
    return rows


def write_report(core_zip: Path, out_path: Path, units, squads):
    units_table = unit_rows(units)
    squads_table = squad_rows(squads)
    overvalued = sorted(units_table, key=lambda r: r["stat_minus_sv"])[:6]
    undervalued = sorted(units_table, key=lambda r: r["stat_minus_sv"], reverse=True)[:6]

    lines = [
        "# HoMM3 Stronghold Squad Value Audit",
        "",
        "Date: 2026-05-06",
        "",
        f"Source: `{core_zip.as_posix()}`.",
        "",
        "Scope: static audit of live Core unit logic and squad config. This does not run battles and does not simulate tactical AI. It compares `squadValue`, raw stat alignment, and how map squad `v` budgets translate into approximate creature counts.",
        "",
        "## Finding",
        "",
        "The Stronghold squad templates are not obviously under-budgeted versus vanilla: same-tier one-unit templates use the same base budgets as vanilla, and mixed templates are broadly in the same budget family. The larger issue is unit power calibration versus `squadValue`.",
        "",
        "For Stronghold as the player's army, the likely auto-battle pain point is high-tier overvaluation: Cyclops and Behemoth variants consume roughly vanilla high-tier squad value while their raw stat profile is below the vanilla tier band. That gives the auto-battle system fewer bodies for the displayed/encounter value unless their special mechanics fully compensate. This matches the symptom \"my auto-battle loses more than expected\" better than a map-squad underbudget theory.",
        "",
        "For Stronghold as neutral/enemy guards, the low and mid tiers do not look like hidden under-valued monsters. Tier 2 Wolf Rider variants are strong, but their `squadValue` is also high. Rocs and Ogres have high `squadValue` for their tier, so the map generator usually buys fewer of them, not more.",
        "",
        "## Unit Calibration",
        "",
        "| Tier | Variant | Unit | SquadValue | Raw stat alignment | SquadValue vs vanilla avg | Read |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for row in units_table:
        if row["stat_alignment"] <= -0.75 and row["sv_ratio"] >= 0.85:
            read = "overvalued for raw stats"
        elif row["stat_alignment"] >= 0.6 and row["sv_ratio"] <= 1.15:
            read = "potentially undercosted"
        elif row["sv_ratio"] >= 1.25:
            read = "expensive for tier"
        else:
            read = "near expected"
        lines.append(
            f"| {row['tier']} | {row['variant']} | `{row['id']}` | {row['squadValue']} | {fmt(row['stat_alignment'])} | {fmt(row['sv_ratio'])}x | {read} |"
        )

    lines.extend(
        [
            "",
            "Most suspicious over-valued units by raw stats versus `squadValue`: "
            + ", ".join(f"`{row['id']}`" for row in overvalued)
            + ". These are the units where the displayed/engine value most risks promising more battlefield output than raw stats deliver.",
            "",
            "No broad under-valued Stronghold pattern appears in the static stat data. The closest under-valued candidates are the low-tier fast attackers, especially the Wolf Rider line, but their `squadValue` is already at or above vanilla tier averages.",
            "",
            "## Squad Template Pressure",
            "",
            "`Budget` is the sum of `baseSquad.units[].v`. `Equivalent units` divides those budgets by each unit's `squadValue`; lower values mean the same encounter budget buys fewer creatures.",
            "",
            "Tier-1 squad rows are included for completeness but should not drive balance conclusions: their `v` budgets are tiny special values in the source data, so equivalent-unit ratios are not meaningful there.",
            "",
            "| Tier | Unit slots | Stronghold squads | SH budget avg | Vanilla budget avg | SH equivalent units | Vanilla equivalent units | SH/vanilla units |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in squads_table:
        lines.append(
            f"| {row['tier']} | {row['n']} | {row['sh_count']} | {fmt(row['sh_budget'], 0)} | {fmt(row['vanilla_budget'], 0)} | {fmt(row['sh_eq'])} | {fmt(row['vanilla_eq'])} | {fmt(row['eq_ratio'])}x |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- If Stronghold auto-battle is losing as the player's faction, first suspect high-tier unit `squadValue` being optimistic relative to actual battlefield output, especially Cyclops and Behemoth lines.",
            "- If fights against Stronghold are estimated too easy, the current static data does not support a broad squad-template underbudget theory. The better suspects are specific ability semantics that are stronger in practice than their `squadValue`, or auto-battle AI mishandling the opposing army composition.",
            "- Do not rebalance by changing only squad templates unless the map generator is the target. Unit `squadValue` changes are the lever that affects how many creatures a value budget buys and how armies compare in value-driven systems.",
            "- Keep ability compensation explicit. This audit treats the raw stat gap as a warning, not final proof, because Cyclops ranged/AoE behavior, Behemoth armor penetration, Thunderbird lightning, and cloned donor passives can change real auto-battle output.",
            "- Auto-battle is not just a squad-value formula: the release dump has `DataSquad.isAutobattle`, side `useMagicInAutoBattle`/`simulateBattle`, `UnitLogicConfig.saj/sak(EAbilityType)`, the `dxr` unit ability manager, and `BattleAiParams.topAbilityCasts`/mech evaluation fields. Native passives, auras, default attacks, counterattacks, and alternative attacks should therefore participate when the battle is simulated. Active `abilities[]` are less certain: they need AI scoring/targeting support and may be ignored or undervalued if the ability is only a custom approximation, UI-facing hook, or unsupported mechanic.",
            "- Re-run this audit after any Core overlay change; Steam patches can replace `Core.zip`, and stale overlays will make squad and unit values disagree with the source tree.",
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    units, squads = load_core(args.core)
    write_report(args.core, args.out, units, squads)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
