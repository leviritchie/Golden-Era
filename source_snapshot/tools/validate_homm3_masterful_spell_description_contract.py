#!/usr/bin/env python3
"""Validate HoMM3 masterful spellbook description generation.

Masterful spell rows are shown in the spellbook for custom heroes. Their
localized description must include the original spell behavior plus the
masterful delta, not only the tier-up sentence.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"


def load_overlay_tree() -> ast.Module:
    return ast.parse(OVERLAY.read_text(encoding="utf-8-sig"), filename=str(OVERLAY))


def masterful_variants(tree: ast.Module) -> dict[str, dict[str, Any]]:
    for node in tree.body:
        value_node = None
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MASTERFUL_MAGIC_VARIANTS" for target in node.targets):
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MASTERFUL_MAGIC_VARIANTS":
            value_node = node.value
        if value_node is None:
            continue
        value = ast.literal_eval(value_node)
        if not isinstance(value, dict):
            raise AssertionError("MASTERFUL_MAGIC_VARIANTS must be a dict")
        return value
    raise AssertionError("MASTERFUL_MAGIC_VARIANTS is missing")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source, filename=str(OVERLAY))
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name and node.end_lineno is not None:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} is missing")


def validate_source_contract() -> list[str]:
    errors: list[str] = []
    source = OVERLAY.read_text(encoding="utf-8-sig")
    tree = load_overlay_tree()
    variants = masterful_variants(tree)
    for base_sid, variant in variants.items():
        if not isinstance(variant, dict):
            errors.append(f"{base_sid}: variant row must be an object")
            continue
        text = variant.get("spellbookMasterfulDescription")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{base_sid}: missing spellbookMasterfulDescription")
            continue
        if not text.startswith("Masterful: "):
            errors.append(f"{base_sid}: spellbookMasterfulDescription must start with 'Masterful: '")
        if "one tier stronger" not in text:
            errors.append(f"{base_sid}: spellbookMasterfulDescription must describe the tier-up behavior")

    variant_function = function_source(source, "masterful_magic_variant_description")
    required_fragments = (
        "base_description: str",
        "normalize_masterful_magic_base_description(base_description)",
        "variant[\"spellbookMasterfulDescription\"]",
        "return f\"{base_text} {masterful_text}\"",
    )
    for fragment in required_fragments:
        if fragment not in variant_function:
            errors.append(f"masterful_magic_variant_description must contain {fragment!r}")
    forbidden_fragments = (
        "return tier_text",
        "return tier_text +",
        "variant[\"description\"]",
    )
    for fragment in forbidden_fragments:
        if fragment in variant_function:
            errors.append(f"masterful_magic_variant_description must not use old tier-only fragment {fragment!r}")

    add_function = function_source(source, "add_custom_masterful_magic_variants")
    for fragment in (
        "magic_text_by_sid",
        "base_description = magic_text_by_sid.get(f\"{base_sid}_description\")",
        "masterful_magic_variant_description(base_sid, base_description)",
    ):
        if fragment not in add_function:
            errors.append(f"add_custom_masterful_magic_variants must contain {fragment!r}")
    if "masterful_magic_variant_description(base_sid)" in add_function:
        errors.append("add_custom_masterful_magic_variants must not call masterful_magic_variant_description without the base description")
    return errors


def lang_text_map(core: Path, member: str) -> dict[str, str]:
    if core.is_dir():
        doc = json.loads((core / member).read_text(encoding="utf-8-sig"))
    else:
        with zipfile.ZipFile(core, "r") as zf:
            doc = json.loads(zf.read(member).decode("utf-8-sig"))
    rows = doc.get("tokens") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        row["sid"]: row["text"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str)
    }


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_core_payload(core: Path) -> list[str]:
    errors: list[str] = []
    variants = masterful_variants(load_overlay_tree())
    magic = lang_text_map(core, "Lang/english/texts/magic.json")
    for base_sid in variants:
        base_text = magic.get(f"{base_sid}_description")
        spec_text = magic.get(f"{base_sid}_description_spec")
        if not isinstance(base_text, str) or not base_text.strip():
            errors.append(f"{base_sid}: Core is missing base magic description")
            continue
        if not isinstance(spec_text, str) or not spec_text.strip():
            errors.append(f"{base_sid}: Core is missing masterful magic description")
            continue
        normalized_base = normalize_text(base_text)
        normalized_spec = normalize_text(spec_text)
        if not normalized_spec.startswith(normalized_base + " "):
            errors.append(f"{base_sid}: masterful spellbook description must start with original spell description")
        if "Masterful: " not in normalized_spec or "one tier stronger" not in normalized_spec:
            errors.append(f"{base_sid}: masterful spellbook description must include the masterful tier-up clause")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, help="Optional Core.zip or extracted Core directory to validate generated localization.")
    args = parser.parse_args(argv)

    errors = validate_source_contract()
    if args.core:
        errors.extend(validate_core_payload(args.core))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"masterful spell description validation failed: {len(errors)} error(s)")
        return 1
    print("masterful spell description validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))