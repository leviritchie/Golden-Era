#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_construction_building_category_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    load_building_mechanics,
    load_json,
    validate_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3ConstructionBuildingCategoryRegistry.cs"


def cs_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_registry(doc: dict[str, Any]) -> str:
    rows: list[tuple[str, str, str, str]] = []
    contracts = doc.get("contracts") if isinstance(doc.get("contracts"), dict) else {}
    for faction_sid, contract in sorted(contracts.items()):
        groups = contract.get("groups") if isinstance(contract.get("groups"), dict) else {}
        for group, entries in sorted(groups.items()):
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                source_id = entry.get("sourceMechanicId")
                current_row = entry.get("currentRow")
                if isinstance(source_id, str) and isinstance(current_row, str):
                    rows.append((faction_sid, current_row, group, source_id))

    lines = [
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "/// <summary>",
        "/// Generated static building category registry for no-compromise construction laws.",
        "/// Source: custom_factions/construction_building_category_contracts.json.",
        "/// This is source-authored classification only; runtime construction hooks remain packet-gated.",
        "/// Do not edit by hand; run tools/release_port/generate_construction_building_category_registry.py.",
        "/// </summary>",
        "internal static class Homm3ConstructionBuildingCategoryRegistry",
        "{",
        "\tprivate static readonly Dictionary<Key, Entry> Entries = new()",
        "\t{",
    ]
    for faction_sid, current_row, group, source_id in rows:
        lines.append(
            "\t\t[new Key("
            + cs_string(faction_sid)
            + ", "
            + cs_string(current_row)
            + ")] = new Entry("
            + cs_string(group)
            + ", "
            + cs_string(source_id)
            + "),"
        )

    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly string Group;",
            "\t\tinternal readonly string SourceMechanicId;",
            "",
            "\t\tinternal Entry(string group, string sourceMechanicId)",
            "\t\t{",
            "\t\t\tGroup = group;",
            "\t\t\tSourceMechanicId = sourceMechanicId;",
            "\t\t}",
            "\t}",
            "",
            "\tprivate readonly struct Key : IEquatable<Key>",
            "\t{",
            "\t\tprivate readonly string FactionSid;",
            "\t\tprivate readonly string BuildingSid;",
            "",
            "\t\tinternal Key(string factionSid, string buildingSid)",
            "\t\t{",
            "\t\t\tFactionSid = factionSid ?? string.Empty;",
            "\t\t\tBuildingSid = buildingSid ?? string.Empty;",
            "\t\t}",
            "",
            "\t\tpublic bool Equals(Key other)",
            "\t\t{",
            "\t\t\treturn string.Equals(FactionSid, other.FactionSid, StringComparison.Ordinal)",
            "\t\t\t       && string.Equals(BuildingSid, other.BuildingSid, StringComparison.Ordinal);",
            "\t\t}",
            "",
            "\t\tpublic override bool Equals(object obj)",
            "\t\t{",
            "\t\t\treturn obj is Key other && Equals(other);",
            "\t\t}",
            "",
            "\t\tpublic override int GetHashCode()",
            "\t\t{",
            "\t\t\tunchecked",
            "\t\t\t{",
            "\t\t\t\treturn ((FactionSid != null ? StringComparer.Ordinal.GetHashCode(FactionSid) : 0) * 397)",
            "\t\t\t\t       ^ (BuildingSid != null ? StringComparer.Ordinal.GetHashCode(BuildingSid) : 0);",
            "\t\t\t}",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryGet(string factionSid, string buildingSid, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\treturn !string.IsNullOrWhiteSpace(factionSid)",
            "\t\t       && !string.IsNullOrWhiteSpace(buildingSid)",
            "\t\t       && Entries.TryGetValue(new Key(factionSid, buildingSid), out entry);",
            "\t}",
            "",
            "\tinternal static bool IsInGroup(string factionSid, string buildingSid, string group)",
            "\t{",
            "\t\treturn !string.IsNullOrWhiteSpace(group)",
            "\t\t       && TryGet(factionSid, buildingSid, out var entry)",
            "\t\t       && string.Equals(entry.Group, group, StringComparison.Ordinal);",
            "\t}",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    mechanics = load_building_mechanics(args.manifest_dir)
    validate_contracts(doc, mechanics, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.write_text(emit_registry(doc), encoding="utf-8", newline="\n")
    print(f"generated {args.out} from {args.contracts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
