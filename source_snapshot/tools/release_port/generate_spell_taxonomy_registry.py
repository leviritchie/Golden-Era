#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_spell_taxonomy_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    load_json,
    load_spell_evidence,
    validate_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3SpellTaxonomyRegistry.cs"


def cs_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_registry(doc: dict[str, Any]) -> str:
    lines = [
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "/// <summary>",
        "/// Generated static spell taxonomy seed for no-compromise custom laws.",
        "/// Source: custom_factions/spell_taxonomy_contracts.json.",
        "/// This is source-authored classification only; runtime spell/cooldown/status hooks remain packet-gated.",
        "/// Do not edit by hand; run tools/release_port/generate_spell_taxonomy_registry.py.",
        "/// </summary>",
        "internal static class Homm3SpellTaxonomyRegistry",
        "{",
        "\tprivate static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)",
        "\t{",
    ]
    spells = doc.get("spells") if isinstance(doc.get("spells"), dict) else {}
    for spell_sid, entry in sorted(spells.items()):
        tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        tag_literals = ", ".join(cs_string(str(tag)) for tag in tags)
        lines.append(
            "\t\t["
            + cs_string(spell_sid)
            + "] = new Entry("
            + cs_string(str(entry.get("school", "")))
            + ", new[] { "
            + tag_literals
            + " }),"
        )

    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly string School;",
            "\t\tinternal readonly string[] Tags;",
            "",
            "\t\tinternal Entry(string school, string[] tags)",
            "\t\t{",
            "\t\t\tSchool = school;",
            "\t\t\tTags = tags ?? Array.Empty<string>();",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryGet(string spellSid, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\treturn !string.IsNullOrWhiteSpace(spellSid)",
            "\t\t       && Entries.TryGetValue(spellSid, out entry);",
            "\t}",
            "",
            "\tinternal static bool HasTag(string spellSid, string tag)",
            "\t{",
            "\t\treturn !string.IsNullOrWhiteSpace(tag)",
            "\t\t       && TryGet(spellSid, out var entry)",
            "\t\t       && EntryHasTag(entry, tag);",
            "\t}",
            "",
            "\tinternal static bool HasAnyTag(string spellSid, string[] tags)",
            "\t{",
            "\t\tif (tags == null || tags.Length == 0)",
            "\t\t\treturn false;",
            "\t\tif (!TryGet(spellSid, out var entry))",
            "\t\t\treturn false;",
            "\t\tfor (var i = 0; i < tags.Length; i++)",
            "\t\t{",
            "\t\t\tif (EntryHasTag(entry, tags[i]))",
            "\t\t\t\treturn true;",
            "\t\t}",
            "\t\treturn false;",
            "\t}",
            "",
            "\tprivate static bool EntryHasTag(Entry entry, string tag)",
            "\t{",
            "\t\tif (string.IsNullOrWhiteSpace(tag) || entry.Tags == null)",
            "\t\t\treturn false;",
            "\t\tfor (var i = 0; i < entry.Tags.Length; i++)",
            "\t\t{",
            "\t\t\tif (string.Equals(entry.Tags[i], tag, StringComparison.Ordinal))",
            "\t\t\t\treturn true;",
            "\t\t}",
            "\t\treturn false;",
            "\t}",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    validate_contracts(doc, load_spell_evidence(), validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.write_text(emit_registry(doc), encoding="utf-8", newline="\n")
    print(f"generated {args.out} from {args.contracts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
