#!/usr/bin/env python3
"""Retired Stronghold loose portrait-animation generator.

Static HoMM3 interface portraits are owned by tools/generate_homm3_interface_portraits.py.
Recruitment/detail idle animation is bundle-backed; this command is kept only as
a fail-closed breadcrumb so old automation cannot recreate loose runtime frame
trees.
"""

from __future__ import annotations

import argparse


RETIRED_MESSAGE = (
    "OfflineUnlockMod/tools/extract_homm3_stronghold_unit_portraits.py is retired. "
    "Use static homm3_portraits plus bundle-backed Unity idle clips and validate "
    "with tools/validate_custom_faction_manifests.py."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)
    parser.parse_args()
    raise RuntimeError(RETIRED_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(main())