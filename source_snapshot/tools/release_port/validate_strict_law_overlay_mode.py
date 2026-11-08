#!/usr/bin/env python3
"""Validate strict no-compromise law overlay mode wiring.

This is a static source guard for the overlay control-flow only. It does not
run the overlay, mutate Core.zip, deploy files, or prove runtime behavior.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERLAY_SCRIPT = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
CORE_METADATA_VALIDATOR = ROOT / "tools" / "release_port" / "validate_custom_law_core_metadata.py"


def load_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RuntimeError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def has_string_constant(node: ast.AST, value: str) -> bool:
    return any(isinstance(child, ast.Constant) and child.value == value for child in ast.walk(node))


def name_references(node: ast.AST, name: str) -> list[ast.Name]:
    return [child for child in ast.walk(node) if isinstance(child, ast.Name) and child.id == name]


def function_def(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise RuntimeError(f"missing function {name}")


def assignment_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def literal_dict_value(tree: ast.Module, name: str) -> dict[Any, Any] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                continue
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.target.id != name:
                continue
            value_node = node.value
        else:
            continue
        if value_node is None:
            return None
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, dict) else None
    return None


def validate_overlay_ast(source: str) -> list[str]:
    failures: list[str] = []
    try:
        tree = ast.parse(source, filename=str(OVERLAY_SCRIPT))
    except SyntaxError as exc:
        return [f"{OVERLAY_SCRIPT.relative_to(ROOT)}: syntax error: {exc}"]

    assigned = assignment_names(tree)
    for required_name in ("LAW_OVERRIDE_DIR", "STRICT_LAW_OVERRIDE_DIR", "_ACTIVE_LAW_OVERRIDE_DIR"):
        if required_name not in assigned:
            failures.append(f"missing top-level {required_name}")

    load_law_override = function_def(tree, "load_law_override")
    if "_ACTIVE_LAW_OVERRIDE_DIR" not in ast.unparse(load_law_override):
        failures.append("load_law_override must read from _ACTIVE_LAW_OVERRIDE_DIR")
    if name_references(load_law_override, "LAW_OVERRIDE_DIR"):
        failures.append("load_law_override must not hard-code LAW_OVERRIDE_DIR")

    build_overlay = function_def(tree, "build_overlay")
    build_args = {arg.arg for arg in build_overlay.args.args}
    if "law_override_dir" not in build_args:
        failures.append("build_overlay must accept law_override_dir")
    build_source = ast.unparse(build_overlay)
    if "_ACTIVE_LAW_OVERRIDE_DIR = law_override_dir" not in build_source:
        failures.append("build_overlay must set _ACTIVE_LAW_OVERRIDE_DIR from law_override_dir")
    if "_ACTIVE_LAW_OVERRIDE_DIR = previous_law_override_dir" not in build_source:
        failures.append("build_overlay must restore _ACTIVE_LAW_OVERRIDE_DIR in a finally block")
    if not any(isinstance(node, ast.Try) and node.finalbody for node in ast.walk(build_overlay)):
        failures.append("build_overlay active law override switch must be protected by finally")

    strict_validator = function_def(tree, "run_custom_law_strict_row_validation")
    strict_validator_source = ast.unparse(strict_validator)
    if "override_dir" not in {arg.arg for arg in strict_validator.args.args}:
        failures.append("run_custom_law_strict_row_validation must accept override_dir")
    if "--override-dir" not in strict_validator_source:
        failures.append("source strict validation must pass --override-dir")

    parse_args = function_def(tree, "parse_args")
    if not has_string_constant(parse_args, "--use-strict-no-compromise-law-overrides"):
        failures.append("parse_args missing --use-strict-no-compromise-law-overrides")

    main = function_def(tree, "main")
    main_source = ast.unparse(main)
    required_main_fragments = [
        "STRICT_LAW_OVERRIDE_DIR if args.use_strict_no_compromise_law_overrides else LAW_OVERRIDE_DIR",
        "args.use_strict_no_compromise_law_overrides",
        "args.strip_nonfinal_no_compromise_law_bonuses",
        "run_custom_law_strict_row_validation('source law overrides', override_dir=law_override_dir)",
        "law_override_dir=law_override_dir",
        "strict_law_row_validation",
    ]
    for fragment in required_main_fragments:
        if fragment not in main_source:
            failures.append(f"main strict overlay wiring missing fragment: {fragment}")
    if "require_existing_path('strict no-compromise law override directory', law_override_dir, is_dir=True)" not in main_source:
        failures.append("strict override source mode must fail closed when the generated strict directory is absent")

    candidate_indices = function_def(tree, "custom_law_candidate_indices")
    candidate_source = ast.unparse(candidate_indices)
    for fragment in (
        "set(range(1, donor_count + 1))",
        "set(custom_law_tracked_indices(manifest))",
        "set(custom_law_override_indices(manifest))",
    ):
        if fragment not in candidate_source:
            failures.append(f"custom_law_candidate_indices missing union fragment: {fragment}")

    explicit_icons = literal_dict_value(tree, "CUSTOM_LAW_EXPLICIT_INDEX_ICONS")
    if explicit_icons is None:
        failures.append("CUSTOM_LAW_EXPLICIT_INDEX_ICONS must be a literal dictionary")
    else:
        if explicit_icons.get(33) != "fraction_law_human_33_icon":
            failures.append("CUSTOM_LAW_EXPLICIT_INDEX_ICONS[33] must be fraction_law_human_33_icon")
        if explicit_icons.get(34) != "fraction_law_human_34_icon":
            failures.append("CUSTOM_LAW_EXPLICIT_INDEX_ICONS[34] must be fraction_law_human_34_icon")

    custom_law_icon = function_def(tree, "custom_law_icon")
    custom_law_icon_source = ast.unparse(custom_law_icon)
    if "CUSTOM_LAW_EXPLICIT_INDEX_ICONS.get(index)" not in custom_law_icon_source:
        failures.append("custom_law_icon must use explicit high-index law icon anchors")

    castle_laws = function_def(tree, "make_castle_laws_doc")
    castle_laws_source = ast.unparse(castle_laws)
    for fragment in (
        "custom_law_override_definition(manifest, index)",
        "copied['parametersPerLevel'] = levels",
        "copied['xHomm3LawOverride'] = True",
        "stamp_no_compromise_law_target_metadata(copied, copied['id'])",
    ):
        if fragment not in castle_laws_source:
            failures.append(f"make_castle_laws_doc must preserve strict/Core law behavior: {fragment}")

    castle_lang = function_def(tree, "add_release_castle_lang")
    castle_lang_source = ast.unparse(castle_lang)
    if "custom_law_lang_rows(manifest, release_zip)" not in castle_lang_source:
        failures.append("add_release_castle_lang must emit override-aware faction law language rows")

    return failures


def validate_core_metadata_validator_ast(source: str) -> list[str]:
    failures: list[str] = []
    try:
        tree = ast.parse(source, filename=str(CORE_METADATA_VALIDATOR))
    except SyntaxError as exc:
        return [f"{CORE_METADATA_VALIDATOR.relative_to(ROOT)}: syntax error: {exc}"]
    validate_core = function_def(tree, "validate_core")
    validate_core_source = ast.unparse(validate_core)
    if "faction if faction.startswith('homm3_') else f'homm3_{faction}'" not in validate_core_source:
        failures.append("validate_custom_law_core_metadata must resolve target faction keys to homm3_* manifest SIDs")
    if "law_tables.get(faction_sid)" not in validate_core_source:
        failures.append("validate_custom_law_core_metadata must look up enabled law table by resolved faction SID")
    return failures


def main() -> int:
    try:
        failures = validate_overlay_ast(load_source(OVERLAY_SCRIPT))
        failures.extend(validate_core_metadata_validator_ast(load_source(CORE_METADATA_VALIDATOR)))
    except RuntimeError as exc:
        print(f"strict law overlay mode validation failed: {exc}", file=sys.stderr)
        return 1
    if failures:
        print("strict law overlay mode validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("strict law overlay mode validation passed")
    print("Note: this proves only overlay source selection wiring, not generated Core behavior or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
