#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from generate_unit_family_registry import DEFAULT_OUTPUT, DEFAULT_TAGS_PATH, emit_registry  # noqa: E402
from validate_unit_family_tags import load_json, load_live_unit_sids, validate_tags  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    validation = Validation()
    live_sids = load_live_unit_sids(args.manifest_dir)
    doc = load_json(args.tags)
    validate_tags(doc, live_sids, validation)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    expected = emit_registry(doc)
    if not args.registry.exists():
        print(f"error: registry file missing: {args.registry}", file=sys.stderr)
        return 1

    actual = args.registry.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if actual != expected:
        print("error: unit family registry is stale; run tools/release_port/generate_unit_family_registry.py", file=sys.stderr)
        return 1

    print(f"unit family registry is in sync with {args.tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
