#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_adventure_owned_structure_registry_source import (  # noqa: E402
    load_structure_contracts,
    validate_structure_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3AdventureOwnedStructureRegistry.cs"


def cs_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_registry(rows: list[dict[str, str]]) -> str:
    lines = [
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "/// <summary>",
        "/// Generated static custom adventure owned-structure classifier for vision laws.",
        "/// Source: custom_factions/homm3_*.json identity.citySid and coreOverlay.directDwellingPrefix.",
        "/// This proves custom structure SID classification only; runtime owner-side and reveal behavior remain packet-gated.",
        "/// Do not edit by hand; run tools/release_port/generate_adventure_owned_structure_registry.py.",
        "/// </summary>",
        "internal static class Homm3AdventureOwnedStructureRegistry",
        "{",
        "\tprivate static readonly Dictionary<string, Entry> CityEntries = new(StringComparer.Ordinal)",
        "\t{",
    ]
    for row in sorted(rows, key=lambda item: item["factionSid"]):
        lines.append(
            "\t\t["
            + cs_string(row["citySid"])
            + "] = new Entry("
            + cs_string(row["factionSid"])
            + ', "city", '
            + cs_string(row["citySid"])
            + "),"
        )
    lines.extend(
        [
            "\t};",
            "",
            "\tprivate static readonly PrefixEntry[] DwellingPrefixes =",
            "\t{",
        ]
    )
    for row in sorted(rows, key=lambda item: item["factionSid"]):
        lines.append(
            "\t\tnew PrefixEntry("
            + cs_string(row["factionSid"])
            + ", "
            + cs_string(row["directDwellingPrefix"])
            + "),"
        )
    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly string FactionSid;",
            "\t\tinternal readonly string Kind;",
            "\t\tinternal readonly string SourceSidOrPrefix;",
            "",
            "\t\tinternal Entry(string factionSid, string kind, string sourceSidOrPrefix)",
            "\t\t{",
            "\t\t\tFactionSid = factionSid;",
            "\t\t\tKind = kind;",
            "\t\t\tSourceSidOrPrefix = sourceSidOrPrefix;",
            "\t\t}",
            "\t}",
            "",
            "\tprivate readonly struct PrefixEntry",
            "\t{",
            "\t\tinternal readonly string FactionSid;",
            "\t\tinternal readonly string Prefix;",
            "",
            "\t\tinternal PrefixEntry(string factionSid, string prefix)",
            "\t\t{",
            "\t\t\tFactionSid = factionSid;",
            "\t\t\tPrefix = prefix;",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryClassify(string configSid, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\tif (string.IsNullOrWhiteSpace(configSid))",
            "\t\t\treturn false;",
            "\t\tif (CityEntries.TryGetValue(configSid, out entry))",
            "\t\t\treturn true;",
            "\t\tfor (var i = 0; i < DwellingPrefixes.Length; i++)",
            "\t\t{",
            "\t\t\tvar prefix = DwellingPrefixes[i];",
            "\t\t\tif (configSid.StartsWith(prefix.Prefix, StringComparison.Ordinal))",
            "\t\t\t{",
            "\t\t\t\tentry = new Entry(prefix.FactionSid, \"dwelling\", prefix.Prefix);",
            "\t\t\t\treturn true;",
            "\t\t\t}",
            "\t\t}",
            "\t\treturn false;",
            "\t}",
            "",
            "\tinternal static bool IsFactionStructure(string factionSid, string configSid)",
            "\t{",
            "\t\treturn !string.IsNullOrWhiteSpace(factionSid)",
            "\t\t       && TryClassify(configSid, out var entry)",
            "\t\t       && string.Equals(entry.FactionSid, factionSid, StringComparison.Ordinal);",
            "\t}",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    rows = load_structure_contracts(args.manifest_dir)
    validate_structure_contracts(rows, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.write_text(emit_registry(rows), encoding="utf-8", newline="\n")
    print(f"generated {args.out} from enabled custom faction manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
