#!/usr/bin/env python3
"""Retired Tower loose preview-animation generator.

Tower recruitment/detail idle animation is now bundle-backed. This command is
kept only as a fail-closed breadcrumb so old automation does not recreate loose
runtime frame trees.
"""

from __future__ import annotations

import argparse


RETIRED_MESSAGE = (
    "tools/extract_homm3_tower_unit_portraits.py is retired. Use bundle-backed "
    "Unity idle clips and validate them through tools/validate_custom_faction_manifests.py."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)
    parser.parse_args()
    raise RuntimeError(RETIRED_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(main())