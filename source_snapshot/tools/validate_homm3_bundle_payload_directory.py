#!/usr/bin/env python3
"""Validate a HoMM3 custom-unit bundle directory against the payload contract."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "custom_factions" / "contracts" / "homm3_bundle_payload_contract.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_contract(path: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        errors.append(f"missing HoMM3 bundle payload contract: {path}")
        return {}
    try:
        doc = load_json(path)
    except json.JSONDecodeError as ex:
        errors.append(f"{path}: invalid JSON: {ex}")
        return {}

    bundles = doc.get("bundles") if isinstance(doc, dict) else None
    if not isinstance(bundles, dict) or not bundles:
        errors.append(f"{path}: bundles must be a non-empty object")
        return {}

    contract: dict[str, dict[str, Any]] = {}
    for name, row in bundles.items():
        if not isinstance(name, str) or not name:
            errors.append(f"{path}: bundle contract name must be a non-empty string")
            continue
        if not isinstance(row, dict):
            errors.append(f"{path}: contract row for {name} must be an object")
            continue
        length = row.get("length")
        sha256 = row.get("sha256")
        if not isinstance(length, int) or length <= 0:
            errors.append(f"{path}: contract row for {name} has invalid length {length!r}")
            continue
        if not isinstance(sha256, str) or len(sha256) != 64:
            errors.append(f"{path}: contract row for {name} has invalid sha256 {sha256!r}")
            continue
        contract[name] = {"length": length, "sha256": sha256.upper()}
    return contract


def bundle_name_matches(name: str, prefix: str) -> bool:
    """Exact bundle names stay exact; a trailing '_' is a family prefix."""
    if prefix.endswith("_"):
        return name.startswith(prefix)
    return name == prefix


def filter_contract(
    contract: dict[str, dict[str, Any]], name_prefixes: list[str]
) -> dict[str, dict[str, Any]]:
    if not name_prefixes:
        return contract
    return {
        name: row
        for name, row in contract.items()
        if any(bundle_name_matches(name, prefix) for prefix in name_prefixes)
    }


def validate_bundle_dir(
    bundle_dir: Path,
    contract_path: Path,
    payload_glob: str,
    name_prefixes: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    contract = load_contract(contract_path, errors)
    if not contract:
        return errors
    prefixes = list(name_prefixes or [])
    contract = filter_contract(contract, prefixes)
    if prefixes and not contract:
        errors.append(
            f"{contract_path}: no bundle rows match name prefix(es) {prefixes!r}"
        )
        return errors

    if not bundle_dir.is_dir():
        errors.append(f"HoMM3 bundle directory is missing: {bundle_dir}")
        return errors

    for bundle_name, expected in sorted(contract.items()):
        bundle_path = bundle_dir / bundle_name
        if not bundle_path.is_file():
            errors.append(f"HoMM3 bundle contract target is missing: {bundle_path}")
            continue
        actual_length = bundle_path.stat().st_size
        if actual_length != expected["length"]:
            errors.append(
                f"HoMM3 bundle {bundle_name} length mismatch: got {actual_length}, "
                f"expected {expected['length']} from {contract_path}"
            )
            continue
        actual_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest().upper()
        if actual_hash != expected["sha256"]:
            errors.append(
                f"HoMM3 bundle {bundle_name} sha256 mismatch: got {actual_hash}, "
                f"expected {expected['sha256']} from {contract_path}"
            )

    contracted_names = set(contract)
    for bundle_path in sorted(bundle_dir.iterdir()):
        if not bundle_path.is_file() or bundle_path.name.endswith(".manifest"):
            continue
        if not fnmatch.fnmatch(bundle_path.name, payload_glob):
            continue
        if prefixes and not any(bundle_name_matches(bundle_path.name, prefix) for prefix in prefixes):
            continue
        if bundle_path.name not in contracted_names:
            errors.append(
                f"HoMM3 bundle payload contains uncontracted non-manifest file: {bundle_path}; "
                "remove stale bundle leftovers or update the authoritative contract intentionally"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a homm3_bundles directory before it is deployed."
    )
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument(
        "--payload-glob",
        default="*",
        help="Validate uncontracted non-manifest files matching this glob; default is strict for installed homm3_bundles.",
    )
    parser.add_argument(
        "--name-prefix",
        action="append",
        default=[],
        help=(
            "Limit contract and leftover checks to this exact bundle name, or a "
            "family prefix ending in '_' (Factory/Bulwark). Repeatable. A complete "
            "name such as custom_units_h3_mage must not pull custom_units_h3_mage_upg."
        ),
    )
    args = parser.parse_args()

    errors = validate_bundle_dir(
        args.bundle_dir, args.contract, args.payload_glob, args.name_prefix
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    scope = (
        f" (prefixes={args.name_prefix!r}, rows checked)"
        if args.name_prefix
        else ""
    )
    print(f"HoMM3 bundle payload directory validation passed: {args.bundle_dir}{scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
