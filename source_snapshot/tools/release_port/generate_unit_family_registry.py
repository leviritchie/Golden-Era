#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_unit_family_tags import (  # noqa: E402
    ALLOWED_FACTS,
    DEFAULT_TAGS_PATH,
    load_json,
    load_live_unit_sids,
    validate_tags,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3UnitLawFamilyRegistry.cs"
FACT_TO_FIELD = {
    "gunpowder": "Gunpowder",
    "shooter": "Shooter",
    "melee": "Melee",
    "construct": "Construct",
    "elemental": "Elemental",
    "undead": "Undead",
    "living": "Living",
    "gatedOrSummoned": "GatedOrSummoned",
    "corpseProducing": "CorpseProducing",
}


def fact(value: str) -> str:
    if value == "yes":
        return "Homm3UnitLawClassifier.Fact.Yes"
    if value == "no":
        return "Homm3UnitLawClassifier.Fact.No"
    return "Homm3UnitLawClassifier.Fact.Unknown"


def emit_registry(doc: dict[str, Any]) -> str:
    units = doc.get("units") if isinstance(doc.get("units"), dict) else {}
    lines: list[str] = [
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "/// <summary>",
        "/// Generated custom-owned unit-family registry for no-compromise faction laws.",
        "/// Source: custom_factions/unit_family_tags.json.",
        "/// Do not edit by hand; run tools/release_port/generate_unit_family_registry.py.",
        "/// </summary>",
        "internal static class Homm3UnitLawFamilyRegistry",
        "{",
        "\tprivate static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)",
        "\t{",
    ]

    for sid in sorted(units):
        entry = units[sid]
        args = ", ".join(f"{FACT_TO_FIELD[key][0].lower() + FACT_TO_FIELD[key][1:]}: {fact(entry[key])}" for key in sorted(ALLOWED_FACTS))
        lines.append(f"\t\t[\"{sid}\"] = new Entry({args}),")

    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Gunpowder;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Shooter;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Melee;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Construct;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Elemental;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Undead;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact Living;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact GatedOrSummoned;",
            "\t\tinternal readonly Homm3UnitLawClassifier.Fact CorpseProducing;",
            "",
            "\t\tinternal Entry(",
            "\t\t\tHomm3UnitLawClassifier.Fact gunpowder = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact shooter = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact melee = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact construct = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact elemental = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact undead = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact living = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact gatedOrSummoned = Homm3UnitLawClassifier.Fact.Unknown,",
            "\t\t\tHomm3UnitLawClassifier.Fact corpseProducing = Homm3UnitLawClassifier.Fact.Unknown)",
            "\t\t{",
            "\t\t\tGunpowder = gunpowder;",
            "\t\t\tShooter = shooter;",
            "\t\t\tMelee = melee;",
            "\t\t\tConstruct = construct;",
            "\t\t\tElemental = elemental;",
            "\t\t\tUndead = undead;",
            "\t\t\tLiving = living;",
            "\t\t\tGatedOrSummoned = gatedOrSummoned;",
            "\t\t\tCorpseProducing = corpseProducing;",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryGet(string sid, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\treturn !string.IsNullOrEmpty(sid) && Entries.TryGetValue(sid, out entry);",
            "\t}",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    live_sids = load_live_unit_sids(args.manifest_dir)
    doc = load_json(args.tags)
    validate_tags(doc, live_sids, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.write_text(emit_registry(doc), encoding="utf-8", newline="\n")
    unit_count = len(doc.get("units") or {}) if isinstance(doc, dict) else 0
    print(f"generated {args.out} from {args.tags} with {unit_count} unit entr{'y' if unit_count == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
