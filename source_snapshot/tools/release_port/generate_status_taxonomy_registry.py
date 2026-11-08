#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_status_taxonomy_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    load_json,
    load_status_evidence,
    validate_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3StatusTaxonomyRegistry.cs"


def cs_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_registry(doc: dict[str, Any]) -> str:
    statuses = doc.get("statuses") if isinstance(doc.get("statuses"), dict) else {}
    tag_map: dict[str, list[str]] = {}
    for status_sid, entry in sorted(statuses.items()):
        for tag in entry.get("tags", []):
            tag_map.setdefault(str(tag), []).append(status_sid)

    lines = [
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "/// <summary>",
        "/// Generated static status taxonomy seed for no-compromise custom laws.",
        "/// Source: custom_factions/status_taxonomy_contracts.json.",
        "/// This is source-authored classification only; runtime buff/status hooks remain packet-gated.",
        "/// Do not edit by hand; run tools/release_port/generate_status_taxonomy_registry.py.",
        "/// </summary>",
        "internal static class Homm3StatusTaxonomyRegistry",
        "{",
        "\tprivate static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)",
        "\t{",
    ]
    for status_sid, entry in sorted(statuses.items()):
        tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        tag_literals = ", ".join(cs_string(str(tag)) for tag in tags)
        lines.append(
            "\t\t["
            + cs_string(status_sid)
            + "] = new Entry(new[] { "
            + tag_literals
            + " }),"
        )

    lines.extend(
        [
            "\t};",
            "",
            "\tprivate static readonly Dictionary<string, string[]> SidsByTag = new(StringComparer.Ordinal)",
            "\t{",
        ]
    )
    for tag, sids in sorted(tag_map.items()):
        sid_literals = ", ".join(cs_string(sid) for sid in sorted(sids))
        lines.append("\t\t[" + cs_string(tag) + "] = new[] { " + sid_literals + " },")

    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly string[] Tags;",
            "",
            "\t\tinternal Entry(string[] tags)",
            "\t\t{",
            "\t\t\tTags = tags ?? Array.Empty<string>();",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryGet(string statusSid, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\treturn !string.IsNullOrWhiteSpace(statusSid)",
            "\t\t       && Entries.TryGetValue(statusSid, out entry);",
            "\t}",
            "",
            "\tinternal static bool HasTag(string statusSid, string tag)",
            "\t{",
            "\t\treturn !string.IsNullOrWhiteSpace(tag)",
            "\t\t       && TryGet(statusSid, out var entry)",
            "\t\t       && EntryHasTag(entry, tag);",
            "\t}",
            "",
            "\tinternal static bool TryGetSidsForTag(string tag, out string[] statusSids)",
            "\t{",
            "\t\tstatusSids = null;",
            "\t\treturn !string.IsNullOrWhiteSpace(tag)",
            "\t\t       && SidsByTag.TryGetValue(tag, out statusSids)",
            "\t\t       && statusSids != null",
            "\t\t       && statusSids.Length > 0;",
            "\t}",
            "",
            "\tinternal static bool TryGetSidsForAnyTag(string[] tags, out string[] statusSids)",
            "\t{",
            "\t\tstatusSids = null;",
            "\t\tif (tags == null || tags.Length == 0)",
            "\t\t\treturn false;",
            "\t\tvar seen = new HashSet<string>(StringComparer.Ordinal);",
            "\t\tvar result = new List<string>();",
            "\t\tfor (var i = 0; i < tags.Length; i++)",
            "\t\t{",
            "\t\t\tif (!TryGetSidsForTag(tags[i], out var current))",
            "\t\t\t\treturn false;",
            "\t\t\tfor (var j = 0; j < current.Length; j++)",
            "\t\t\t{",
            "\t\t\t\tif (seen.Add(current[j]))",
            "\t\t\t\t\tresult.Add(current[j]);",
            "\t\t\t}",
            "\t\t}",
            "\t\tstatusSids = result.ToArray();",
            "\t\treturn statusSids.Length > 0;",
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
    validate_contracts(doc, load_status_evidence(), validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.write_text(emit_registry(doc), encoding="utf-8", newline="\n")
    print(f"generated {args.out} from {args.contracts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
