#!/usr/bin/env python3
"""Retired HoMM3 remaining-unit loose asset deployer.

The current production path is the OfflineUnlockMod.csproj DeployPluginToGame
target plus tools/validate_custom_faction_manifests.py. This command is kept
only as a fail-closed breadcrumb so old automation does not silently recreate
retired loose runtime payload trees.
"""

from __future__ import annotations

import argparse


RETIRED_MESSAGE = (
    "tools/deploy_homm3_remaining_unit_assets.py is retired. Use the "
    "OfflineUnlockMod.csproj DeployPluginToGame target and "
    "tools/validate_custom_faction_manifests.py instead."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)
    parser.parse_args()
    raise RuntimeError(RETIRED_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(main())