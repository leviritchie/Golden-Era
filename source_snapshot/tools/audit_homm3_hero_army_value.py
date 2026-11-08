#!/usr/bin/env python3
"""Audit custom HoMM3 hero starting-army power (armyValue proxy).

Olden Era does not store armyValue on HeroConfig rows. The UI and diplomacy
systems derive army strength from startSquad stacks multiplied by each unit's
UnitLogicConfig.squadValue. This script approximates that as:

    armyValue ≈ Σ squadValue(unit_sid) × stack_count

for min, average ((min+max)/2 per slot), and max counts.

Sources:
  - Live Core.zip hero rows (runtime truth after overlay apply)
  - custom_factions/hero_overrides/*.json (authoring source; may drift)

Usage:
  python tools/audit_homm3_hero_army_value.py
  python tools/audit_homm3_hero_army_value.py --markdown docs/homm3_hero_army_value_audit.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "hero_overrides"
DEFAULT_MARKDOWN = ROOT / "docs" / "homm3_hero_army_value_audit.md"
Z_OUTLIER = 1.5
FACTION_RATIO_OUTLIER = 0.35


def load_squad_values(core_zip: Path) -> dict[str, int]:
    units: dict[str, int] = {}
    with zipfile.ZipFile(core_zip) as zf:
        for name in zf.namelist():
            match = re.match(r"DB/units/units_logics/([^/]+)/([^/]+)\.json$", name)
            if not match:
                continue
            data = json.loads(zf.read(name))
            for row in data.get("array", []):
                uid = row.get("id")
                if uid:
                    units[str(uid)] = int(row.get("squadValue") or 0)
    return units


def squad_army_values(
    rows: list[dict], units: dict[str, int]
) -> tuple[float, float, float] | None:
    if not rows:
        return 0.0, 0.0, 0.0
    vmin = vmax = vavg = 0.0
    for row in rows:
        sid = str(row.get("sid") or "")
        squad_value = units.get(sid)
        if squad_value is None:
            return None
        mn = int(row.get("min") or 0)
        mx = int(row.get("max") or mn)
        vmin += squad_value * mn
        vmax += squad_value * mx
        vavg += squad_value * (mn + mx) / 2
    return vmin, vavg, vmax


def format_squad(rows: list[dict]) -> str:
    return ", ".join(
        f"{row.get('sid')} {row.get('min')}-{row.get('max')}" for row in rows
    )


def load_override_names(override_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for hero_sid, entry in (doc.get("heroOverrides") or {}).items():
            if entry.get("enabled", True):
                names[str(hero_sid)] = str(entry.get("nameText") or hero_sid)
    return names


def load_override_squads(override_dir: Path) -> dict[str, list[dict]]:
    squads: dict[str, list[dict]] = {}
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for hero_sid, entry in (doc.get("heroOverrides") or {}).items():
            if entry.get("enabled", True):
                squads[str(hero_sid)] = list(entry.get("startSquad") or [])
    return squads


def load_core_heroes(core_zip: Path) -> tuple[dict[str, dict], list[tuple[str, str, list[dict], list[dict]]]]:
    heroes: dict[str, dict] = {}
    duplicate_rows: list[tuple[str, str, list[dict], list[dict]]] = []
    with zipfile.ZipFile(core_zip) as zf:
        for name in sorted(zf.namelist()):
            match = re.match(r"DB/heroes/(homm3_[^/]+)/([^/]+)\.json$", name)
            if not match:
                continue
            faction = match.group(1)
            data = json.loads(zf.read(name))
            rows = data.get("array") or []
            seen: dict[str, list[dict]] = {}
            for row in rows:
                hero_sid = str(row.get("id") or "")
                squad = list(row.get("startSquad") or [])
                if hero_sid in seen:
                    duplicate_rows.append((name, hero_sid, seen[hero_sid], squad))
                seen[hero_sid] = squad
            for hero_sid, squad in seen.items():
                heroes[hero_sid] = {
                    "hero": hero_sid,
                    "faction": faction,
                    "source": name,
                    "squad": squad,
                }
    return heroes, duplicate_rows


def build_audit_records(
    heroes: dict[str, dict],
    units: dict[str, int],
    names: dict[str, str],
) -> list[dict]:
    records: list[dict] = []
    for hero_sid, hero in sorted(heroes.items()):
        squad = hero["squad"]
        values = squad_army_values(squad, units)
        if values is None:
            continue
        vmin, vavg, vmax = values
        records.append(
            {
                "hero": hero_sid,
                "name": names.get(hero_sid, hero_sid),
                "faction": hero["faction"],
                "slots": len(squad),
                "min": vmin,
                "avg": vavg,
                "max": vmax,
                "squad": squad,
                "source": hero["source"],
            }
        )
    return records


def find_outliers(records: list[dict]) -> tuple[list[dict], dict[str, float]]:
    avgs = [row["avg"] for row in records]
    mean = statistics.mean(avgs)
    stdev = statistics.pstdev(avgs) if len(avgs) > 1 else 0.0
    for row in records:
        row["z"] = (row["avg"] - mean) / stdev if stdev else 0.0
    z_outliers = [row for row in records if abs(row["z"]) >= Z_OUTLIER]

    by_faction: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_faction[row["faction"]].append(row)

    faction_medians = {
        faction: statistics.median([row["avg"] for row in rows])
        for faction, rows in by_faction.items()
    }

    ratio_outliers: list[dict] = []
    for row in records:
        med = faction_medians[row["faction"]]
        if med <= 0:
            continue
        ratio = row["avg"] / med
        row["faction_ratio"] = ratio
        if ratio < (1.0 - FACTION_RATIO_OUTLIER) or ratio > (1.0 + FACTION_RATIO_OUTLIER):
            ratio_outliers.append(row)

    return z_outliers, faction_medians


def compare_override_drift(
    records: list[dict],
    override_squads: dict[str, list[dict]],
    units: dict[str, int],
) -> list[dict]:
    by_hero = {row["hero"]: row for row in records}
    drift: list[dict] = []
    for hero_sid, squad in sorted(override_squads.items()):
        core_row = by_hero.get(hero_sid)
        if core_row is None:
            drift.append(
                {
                    "hero": hero_sid,
                    "kind": "missing in core",
                    "override": squad,
                    "core": None,
                }
            )
            continue
        if squad == core_row["squad"]:
            continue
        ov_values = squad_army_values(squad, units)
        core_values = squad_army_values(core_row["squad"], units)
        drift.append(
            {
                "hero": hero_sid,
                "name": core_row["name"],
                "kind": "startSquad drift",
                "override_avg": None if ov_values is None else ov_values[1],
                "core_avg": core_values[1] if core_values else None,
                "override": squad,
                "core": core_row["squad"],
            }
        )
    return drift


def render_markdown(
    records: list[dict],
    z_outliers: list[dict],
    faction_medians: dict[str, float],
    duplicate_rows: list[tuple[str, str, list[dict], list[dict]]],
    drift: list[dict],
    core_zip: Path,
) -> str:
    avgs = [row["avg"] for row in records]
    mean = statistics.mean(avgs)
    stdev = statistics.pstdev(avgs) if len(avgs) > 1 else 0.0

    lines = [
        "# HoMM3 Custom Hero Starting Army Value Audit",
        "",
        f"Source Core: `{core_zip}`",
        "",
        "## Method",
        "",
        "There is no `armyValue` field on hero rows. This audit uses the same",
        "per-creature `squadValue` scalar used by map guards, diplomacy, and",
        "auto-battle value estimates:",
        "",
        "```",
        "armyValue ≈ Σ squadValue(unit_sid) × stack_count",
        "```",
        "",
        "Each `startSquad` slot contributes min, average `(min+max)/2`, and max",
        "totals. Outliers use global z-score on the average total and a",
        f"±{int(FACTION_RATIO_OUTLIER * 100)}% deviation from the hero's faction median.",
        "",
        f"Population: **{len(records)}** custom heroes; mean avg armyValue **{mean:.0f}**",
        f"(σ={stdev:.0f}).",
        "",
    ]

    if duplicate_rows:
        lines.extend(
            [
                "## Data integrity warning",
                "",
                f"**{len(duplicate_rows)}** Core hero JSON files contain duplicate `id`",
                "rows in the same `array`. The audit uses the **last** row per file,",
                "which matches typical dictionary merge behavior but should be fixed",
                "in generation so only one row ships.",
                "",
                "| File | First startSquad | Last startSquad |",
                "|---|---|---|",
            ]
        )
        for path, hero_sid, first, last in duplicate_rows[:12]:
            lines.append(
                f"| `{path}` | `{format_squad(first)}` | `{format_squad(last)}` |"
            )
        if len(duplicate_rows) > 12:
            lines.append(f"| … | … | *{len(duplicate_rows) - 12} more* |")
        lines.append("")

    lines.extend(["## Faction summary (avg armyValue)", "", "| Faction | Heroes | Median | Min | Max |", "|---|---:|---:|---:|---:|"])
    by_faction: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_faction[row["faction"]].append(row)
    for faction in sorted(by_faction):
        vals = sorted(r["avg"] for r in by_faction[faction])
        lines.append(
            f"| `{faction}` | {len(vals)} | {statistics.median(vals):.0f} | {min(vals):.0f} | {max(vals):.0f} |"
        )
    lines.append("")

    def outlier_table(title: str, rows: list[dict], reverse: bool = False) -> None:
        lines.extend([f"## {title}", ""])
        if not rows:
            lines.append("_None._")
            lines.append("")
            return
        ordered = sorted(rows, key=lambda r: r["avg"], reverse=reverse)
        lines.extend(
            [
                "| z | Hero | Faction | Avg | Min | Max | startSquad |",
                "|---:|---|---|---:|---:|---:|---|",
            ]
        )
        for row in ordered:
            lines.append(
                f"| {row['z']:+.2f} | {row['name']} (`{row['hero']}`) | `{row['faction']}` | "
                f"{row['avg']:.0f} | {row['min']:.0f} | {row['max']:.0f} | `{format_squad(row['squad'])}` |"
            )
        lines.append("")

    low = [row for row in z_outliers if row["z"] <= -Z_OUTLIER]
    high = [row for row in z_outliers if row["z"] >= Z_OUTLIER]
    outlier_table("Global low outliers (z ≤ -1.5)", low)
    outlier_table("Global high outliers (z ≥ +1.5)", high, reverse=True)

    ratio_rows = [
        row
        for row in records
        if row.get("faction_ratio") is not None
        and (
            row["faction_ratio"] < (1.0 - FACTION_RATIO_OUTLIER)
            or row["faction_ratio"] > (1.0 + FACTION_RATIO_OUTLIER)
        )
    ]
    lines.extend(["## Faction-relative outliers (≥35% off faction median)", ""])
    if not ratio_rows:
        lines.append("_None._")
    else:
        lines.extend(
            [
                "| Ratio | Hero | Faction | Avg | Faction median | startSquad |",
                "|---:|---|---|---:|---:|---|",
            ]
        )
        for row in sorted(ratio_rows, key=lambda r: r["faction_ratio"]):
            med = faction_medians[row["faction"]]
            lines.append(
                f"| {row['faction_ratio']:.2f}x | {row['name']} (`{row['hero']}`) | `{row['faction']}` | "
                f"{row['avg']:.0f} | {med:.0f} | `{format_squad(row['squad'])}` |"
            )
    lines.append("")

    if drift:
        lines.extend(["## hero_overrides drift vs deployed Core", ""])
        lines.extend(
            [
                f"**{len(drift)}** heroes differ between `custom_factions/hero_overrides`",
                "and the deployed Core row used at runtime.",
                "",
                "| Hero | Override avg | Core avg | Override startSquad | Core startSquad |",
                "|---|---:|---:|---|---|",
            ]
        )
        for item in drift:
            lines.append(
                f"| {item.get('name', item['hero'])} (`{item['hero']}`) | "
                f"{item.get('override_avg', 'n/a')} | {item.get('core_avg', 'n/a')} | "
                f"`{format_squad(item['override'])}` | `{format_squad(item['core'] or [])}` |"
            )
        lines.append("")

    lines.extend(
        [
            "## Interpretation notes",
            "",
            "- Many low outliers are intentional HoMM3 specialist starters: triple",
            "  low-tier stacks (Walking Dead, Dwarf, Harpy, Archer) or two-stack armies.",
            "- High outliers usually come from large low-tier counts (30-40 Troglo/Gremlin)",
            "  or upgraded tier mixes (Roc/Ogre/Basilisk specialists).",
            "- `squadValue` inflation on high-tier custom units (see",
            "  `docs/homm3_stronghold_squad_value_audit.md`) amplifies specialist armies",
            "  that include Roc, Ogre, or Basilisk stacks.",
            "- Re-run after `apply_release_core_overlay.py` or hero prefill changes.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args()

    if not args.core.is_file():
        raise SystemExit(f"Core.zip not found: {args.core}")

    units = load_squad_values(args.core)
    names = load_override_names(args.override_dir)
    override_squads = load_override_squads(args.override_dir)
    heroes, duplicate_rows = load_core_heroes(args.core)
    records = build_audit_records(heroes, units, names)
    z_outliers, faction_medians = find_outliers(records)
    drift = compare_override_drift(records, override_squads, units)

    avgs = [row["avg"] for row in records]
    print(
        f"heroes={len(records)} mean_avg={statistics.mean(avgs):.0f} "
        f"stdev={statistics.pstdev(avgs):.0f} z_outliers={len(z_outliers)} "
        f"faction_outliers={sum(1 for r in records if r.get('faction_ratio') and (r['faction_ratio'] < 0.65 or r['faction_ratio'] > 1.35))} "
        f"duplicate_core_files={len(duplicate_rows)} override_drift={len(drift)}"
    )

    low = [r for r in z_outliers if r["z"] <= -Z_OUTLIER]
    high = [r for r in z_outliers if r["z"] >= Z_OUTLIER]
    print("\nLow outliers:")
    for row in sorted(low, key=lambda r: r["z"]):
        print(
            f"  {row['z']:+.2f} {row['name']:22} avg={row['avg']:.0f} [{format_squad(row['squad'])}]"
        )
    print("\nHigh outliers:")
    for row in sorted(high, key=lambda r: r["z"], reverse=True):
        print(
            f"  {row['z']:+.2f} {row['name']:22} avg={row['avg']:.0f} [{format_squad(row['squad'])}]"
        )

    markdown_path = args.markdown or DEFAULT_MARKDOWN
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_markdown(
                records, z_outliers, faction_medians, duplicate_rows, drift, args.core
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {markdown_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
