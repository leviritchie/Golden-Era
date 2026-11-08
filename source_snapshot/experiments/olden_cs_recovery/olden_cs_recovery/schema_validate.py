"""Validate recovery JSON artifacts against schemas/ (fail-closed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from olden_cs_recovery.paths import PACKAGE_ROOT, SCHEMAS_DIR


def load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SystemExit(f"FAIL: cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL: invalid JSON in {path}: {exc}") from exc


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    if not path.is_file():
        raise SystemExit(f"FAIL: missing schema file: {path}")
    schema = load_json(path)
    if not isinstance(schema, dict):
        raise SystemExit(f"FAIL: schema root must be object: {path}")
    return schema


def validator_for(schema_name: str) -> Draft202012Validator:
    schema = load_schema(schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_instance(schema_name: str, instance: Any, label: str) -> None:
    validator = validator_for(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if not errors:
        return
    details = []
    for err in errors[:12]:
        path = ".".join(str(p) for p in err.path) or "<root>"
        details.append(f"  - {path}: {err.message}")
    extra = "" if len(errors) <= 12 else f"\n  … {len(errors) - 12} more"
    raise SystemExit(f"FAIL: schema validation failed for {label} ({schema_name}):\n" + "\n".join(details) + extra)


def validate_file(schema_name: str, path: Path) -> None:
    instance = load_json(path)
    validate_instance(schema_name, instance, str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate olden_cs_recovery JSON against schemas.")
    parser.add_argument(
        "--all-queue",
        action="store_true",
        help="Validate every queue item under queue/partitions/",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Validate input_manifest.json",
    )
    parser.add_argument(
        "--ledger",
        action="store_true",
        help="Validate every proof_ledger/entries/*.json",
    )
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="Validate every oracle_traces/**/*.oracle.json fixture",
    )
    parser.add_argument(
        "--direct-state-cards",
        action="store_true",
        help="Validate every direct_state_cards/*.json against direct_state_card.schema.json",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Explicit JSON files to validate as queue items")
    args = parser.parse_args(argv)

    if not (
        args.all_queue
        or args.manifest
        or args.ledger
        or args.oracle
        or args.direct_state_cards
        or args.paths
    ):
        raise SystemExit(
            "FAIL: specify --manifest, --all-queue, --ledger, --oracle, "
            "--direct-state-cards, and/or explicit paths"
        )

    if args.manifest:
        validate_file("input_manifest.schema.json", PACKAGE_ROOT / "input_manifest.json")
        print("OK: input_manifest.json")

    if args.all_queue:
        root = PACKAGE_ROOT / "queue" / "partitions"
        files = sorted(root.rglob("*.json")) if root.is_dir() else []
        if not files:
            raise SystemExit(f"FAIL: no queue items under {root}")
        for path in files:
            validate_file("queue_item.schema.json", path)
        print(f"OK: {len(files)} queue item(s)")

    if args.ledger:
        root = PACKAGE_ROOT / "proof_ledger" / "entries"
        files = sorted(root.glob("*.json")) if root.is_dir() else []
        for path in files:
            validate_file("proof_ledger_entry.schema.json", path)
        print(f"OK: {len(files)} proof ledger entr(y/ies)")

    if args.oracle:
        root = PACKAGE_ROOT / "oracle_traces"
        files = sorted(root.rglob("*.oracle.json")) if root.is_dir() else []
        if not files:
            raise SystemExit(f"FAIL: no oracle fixtures under {root}")
        for path in files:
            validate_file("oracle_trace.schema.json", path)
        print(f"OK: {len(files)} oracle fixture(s)")

    if args.direct_state_cards:
        root = PACKAGE_ROOT / "direct_state_cards"
        files = sorted(root.glob("*.json")) if root.is_dir() else []
        if not files:
            raise SystemExit(f"FAIL: no Direct State cards under {root}")
        for path in files:
            validate_file("direct_state_card.schema.json", path)
        print(f"OK: {len(files)} Direct State card(s)")

    for path in args.paths:
        validate_file("queue_item.schema.json", path)
        print(f"OK: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
