#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from generate_adventure_owned_structure_registry import DEFAULT_OUTPUT, emit_registry  # noqa: E402
from validate_adventure_owned_structure_registry_source import (  # noqa: E402
    load_structure_contracts,
    validate_structure_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    rows = load_structure_contracts(args.manifest_dir)
    validate_structure_contracts(rows, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    expected = emit_registry(rows)
    if not args.registry.exists():
        print(f"error: adventure owned-structure registry file missing: {args.registry}", file=sys.stderr)
        return 1

    actual = args.registry.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if actual != expected:
        print(
            "error: adventure owned-structure registry is stale; "
            "run tools/release_port/generate_adventure_owned_structure_registry.py",
            file=sys.stderr,
        )
        return 1

    print("adventure owned-structure registry is in sync with enabled custom faction manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
