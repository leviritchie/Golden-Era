"""
Audit Core.zip for places that look like full-faction rosters or dungeon-only
wiring where homm3_stronghold may be missing (vs dungeon / other shipped ids).

Does not prove runtime bugs; narrows JSON worth eyeballing.

Usage:
  python audit_core_homm3_stronghold_gap.py
  python audit_core_homm3_stronghold_gap.py --core "D:/Games/.../Core.zip"
  python audit_core_homm3_stronghold_gap.py --json-out gaps.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterator

NEW_FRACTION = "homm3_stronghold"
NEW_CITY = "homm3_stronghold_city"
DATA_JSON = "DB/data.json"

# Zip paths that are intentionally dungeon-only (no stronghold row expected).
SKIP_PREFIXES: tuple[str, ...] = (
    "DB/units/units_logics/dungeon/",
    "DB/units/units_views/dungeon/",
    "DB/heroes/dungeon/",
    "DB/squads/squads_dungeon/",
    "DB/objects_logic/cities/dungeon_city.json",
    "DB/fractions/3_dungeon.json",
    "DB/fractions_laws/fractions_laws_table_dungeon.json",
    "DB/heroes_specializations/specializations_dungeon.json",
    "DB/heroes_sub_classes/sub_classes_dungeon.json",
)


def default_core() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "HeroesOE_Data" / "StreamingAssets" / "Core.zip"


def skip_zip_path(name: str) -> bool:
    return any(name.startswith(p) or name == p for p in SKIP_PREFIXES)


def load_fraction_ids(z: zipfile.ZipFile) -> set[str]:
    raw = z.read(DATA_JSON).decode("utf-8-sig")
    data = json.loads(raw)
    fr = data.get("fractions")
    if not isinstance(fr, list):
        return set()
    return {x for x in fr if isinstance(x, str)}


def iter_json_paths(obj: Any, base: str) -> Iterator[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            seg = k if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k) else repr(k)
            p = f"{base}.{seg}" if base else seg
            yield p, v
            yield from iter_json_paths(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{base}[{i}]"
            yield p, v
            yield from iter_json_paths(v, p)


def is_pure_fraction_list(lst: list[Any], fraction_ids: set[str]) -> bool:
    if len(lst) < 3:
        return False
    if not all(isinstance(x, str) for x in lst):
        return False
    return all(x in fraction_ids for x in lst)


def audit_zip(core: Path, min_pure_list: int, json_out: Path | None) -> int:
    if not core.is_file():
        print(f"ERROR: Core.zip not found: {core}", file=sys.stderr)
        return 1

    report: dict[str, Any] = {
        "core": str(core),
        "warnings": [],
        "pure_fraction_lists_missing_stronghold": [],
        "text_dungeon_city_without_stronghold_city": [],
        "files_referencing_stronghold": [],
        "data_json": {},
    }

    with zipfile.ZipFile(core, "r") as z:
        fraction_ids = load_fraction_ids(z)
        report["data_json"]["fraction_ids"] = sorted(fraction_ids)
        data_root = json.loads(z.read(DATA_JSON).decode("utf-8-sig"))
        af = data_root.get("availableFractions")
        if isinstance(af, list) and all(isinstance(x, str) for x in af):
            report["data_json"]["availableFractions"] = list(af)
            only_fr = set(fraction_ids) - set(af)
            only_af = set(af) - set(fraction_ids)
            if only_fr or only_af:
                report["data_json"]["fraction_vs_available_diff"] = {
                    "in_fractions_not_available": sorted(only_fr),
                    "in_available_not_fractions": sorted(only_af),
                }
        if NEW_FRACTION not in fraction_ids:
            report["warnings"].append(
                f"{DATA_JSON} does not list {NEW_FRACTION!r} in fractions[] — run generate_homm3_stronghold_city.py."
            )

        json_names = sorted(n for n in z.namelist() if n.endswith(".json") and not n.startswith("__"))
        scanned = [n for n in json_names if not skip_zip_path(n)]
        report["scanned_json_count"] = len(scanned)

        for name in scanned:
            raw = z.read(name).decode("utf-8-sig")
            has_new = NEW_FRACTION in raw or NEW_CITY in raw
            if has_new:
                report["files_referencing_stronghold"].append(name)

            if "dungeon_city" in raw and NEW_CITY not in raw:
                report["text_dungeon_city_without_stronghold_city"].append(name)

            try:
                root = json.loads(raw)
            except json.JSONDecodeError:
                continue

            for jpath, node in iter_json_paths(root, ""):
                if not isinstance(node, list):
                    continue
                if not is_pure_fraction_list(node, fraction_ids):
                    continue
                if len(node) < min_pure_list:
                    continue
                if "dungeon" not in node:
                    continue
                if NEW_FRACTION in node:
                    continue
                report["pure_fraction_lists_missing_stronghold"].append(
                    {"zipPath": name, "jsonPath": jpath or "$", "list": list(node)}
                )

    # Dedupe identical list hits same file (keep first path only per file+tuple)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[dict[str, Any]] = []
    for item in report["pure_fraction_lists_missing_stronghold"]:
        key = (item["zipPath"], tuple(item["list"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    report["pure_fraction_lists_missing_stronghold"] = deduped

    # Console summary
    print(f"Core: {core}")
    print(f"fractions in {DATA_JSON} ({len(fraction_ids)}): {', '.join(sorted(fraction_ids))}")
    af = report["data_json"].get("availableFractions")
    if af is not None:
        print(f"availableFractions ({len(af)}): {', '.join(af)}")
        diff = report["data_json"].get("fraction_vs_available_diff")
        if diff:
            print(f"  symmetric diff: fractions-only={diff.get('in_fractions_not_available')} | available-only={diff.get('in_available_not_fractions')}")
    for w in report["warnings"]:
        print(f"WARNING: {w}")
    print()
    print(f"Zip JSON scanned (excluding dungeon-only skip prefixes): {report.get('scanned_json_count', 0)}")
    print(f"Files containing {NEW_FRACTION!r} or {NEW_CITY!r}: {len(report['files_referencing_stronghold'])}")
    for p in report["files_referencing_stronghold"][:40]:
        print(f"  {p}")
    if len(report["files_referencing_stronghold"]) > 40:
        print(f"  ... and {len(report['files_referencing_stronghold']) - 40} more")
    print()
    print(
        f"Pure fraction-id lists (len>={min_pure_list}, all ids in data.json fractions[], "
        f"includes dungeon, omits {NEW_FRACTION}): {len(report['pure_fraction_lists_missing_stronghold'])}"
    )
    for item in report["pure_fraction_lists_missing_stronghold"][:80]:
        print(f"  {item['zipPath']}\n    {item['jsonPath']}\n    {item['list']!r}")
    if len(report["pure_fraction_lists_missing_stronghold"]) > 80:
        print(f"  ... and {len(report['pure_fraction_lists_missing_stronghold']) - 80} more")
    print()
    print(f"JSON files with 'dungeon_city' substring but not {NEW_CITY!r}: {len(report['text_dungeon_city_without_stronghold_city'])}")
    for p in report["text_dungeon_city_without_stronghold_city"][:50]:
        print(f"  {p}")
    if len(report["text_dungeon_city_without_stronghold_city"]) > 50:
        print(f"  ... and {len(report['text_dungeon_city_without_stronghold_city']) - 50} more")

    if json_out:
        json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print()
        print(f"Wrote {json_out}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--core", type=Path, default=None, help="Path to Core.zip (default: playtest StreamingAssets)")
    ap.add_argument(
        "--min-pure-list",
        type=int,
        default=4,
        help="Minimum length for pure fraction-id list heuristics (default 4)",
    )
    ap.add_argument("--json-out", type=Path, default=None, help="Write full report JSON")
    args = ap.parse_args()
    core = args.core or default_core()
    return audit_zip(core, args.min_pure_list, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
