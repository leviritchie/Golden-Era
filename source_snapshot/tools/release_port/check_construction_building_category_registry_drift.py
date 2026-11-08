#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from generate_construction_building_category_registry import DEFAULT_OUTPUT, emit_registry  # noqa: E402
from validate_construction_building_category_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    load_building_mechanics,
    load_json,
    validate_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    mechanics = load_building_mechanics(args.manifest_dir)
    validate_contracts(doc, mechanics, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    expected = emit_registry(doc)
    if not args.registry.exists():
        print(f"error: construction building category registry file missing: {args.registry}", file=sys.stderr)
        return 1

    actual = args.registry.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if actual != expected:
        print(
            "error: construction building category registry is stale; "
            "run tools/release_port/generate_construction_building_category_registry.py",
            file=sys.stderr,
        )
        return 1

    print(f"construction building category registry is in sync with {args.contracts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
