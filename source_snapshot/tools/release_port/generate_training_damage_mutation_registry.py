#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_training_damage_mutation_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    DEFAULT_INVENTORY_PATH,
    load_json,
    load_training_damage_profiles,
    validate_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation  # noqa: E402


DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3TrainingDamageMutationRegistry.cs"


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
        "/// Generated source-prepared mutation design registry for TrainingDamage laws.",
        "/// Source: custom_factions/training_damage_mutation_contracts.json.",
        "/// Design classification only; runtime gameplay remains packet-gated.",
        "/// Do not edit by hand; run tools/release_port/generate_training_damage_mutation_registry.py.",
        "/// </summary>",
        "internal static class Homm3TrainingDamageMutationRegistry",
        "{",
        "\tprivate static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)",
        "\t{",
    ]
    contracts = doc.get("contracts") if isinstance(doc.get("contracts"), dict) else {}
    for effect_key, contract in sorted(contracts.items()):
        runtime = contract.get("requiredRuntimeProof") if isinstance(contract.get("requiredRuntimeProof"), list) else []
        numeric = contract.get("numericInputs") if isinstance(contract.get("numericInputs"), list) else []
        runtime_values = ", ".join(cs_string(str(item)) for item in runtime)
        numeric_values = ", ".join(cs_string(str(item)) for item in numeric)
        lines.append(
            "\t\t["
            + cs_string(effect_key)
            + "] = new Entry("
            + cs_string(str(contract.get("mutationKind", "")))
            + ", "
            + cs_string(str(contract.get("direction", "")))
            + ", "
            + cs_string(str(contract.get("mutationPoint", "")))
            + ", new string[] { "
            + runtime_values
            + " }, new string[] { "
            + numeric_values
            + " }, "
            + cs_string(str(contract.get("cleanup", "")))
            + "),"
        )
    lines.extend(
        [
            "\t};",
            "",
            "\tinternal readonly struct Entry",
            "\t{",
            "\t\tinternal readonly string MutationKind;",
            "\t\tinternal readonly string Direction;",
            "\t\tinternal readonly string MutationPoint;",
            "\t\tinternal readonly string[] RequiredRuntimeProof;",
            "\t\tinternal readonly string[] NumericInputs;",
            "\t\tinternal readonly string Cleanup;",
            "",
            "\t\tinternal Entry(string mutationKind, string direction, string mutationPoint, string[] requiredRuntimeProof, string[] numericInputs, string cleanup)",
            "\t\t{",
            "\t\t\tMutationKind = mutationKind;",
            "\t\t\tDirection = direction;",
            "\t\t\tMutationPoint = mutationPoint;",
            "\t\t\tRequiredRuntimeProof = requiredRuntimeProof ?? Array.Empty<string>();",
            "\t\t\tNumericInputs = numericInputs ?? Array.Empty<string>();",
            "\t\t\tCleanup = cleanup;",
            "\t\t}",
            "\t}",
            "",
            "\tinternal static bool TryGet(string effectKey, out Entry entry)",
            "\t{",
            "\t\tentry = default;",
            "\t\treturn !string.IsNullOrWhiteSpace(effectKey)",
            "\t\t       && Entries.TryGetValue(effectKey, out entry);",
            "\t}",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    validate_contracts(doc, load_training_damage_profiles(args.inventory), validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    args.out.write_text(emit_registry(doc), encoding="utf-8", newline="\n")
    print(f"generated {args.out} from {args.contracts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
