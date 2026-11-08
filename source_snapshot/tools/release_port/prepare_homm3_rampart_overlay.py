#!/usr/bin/env python3
"""Rampart release-overlay preflight.

Rampart is not ready for Core.zip promotion yet. This script is a narrow
faction-owned checkpoint that keeps the release blocker explicit instead of
letting the generic overlay path clone Nature data and silently ship donor
behavior.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "custom_factions" / "homm3_rampart.json"
SOURCE_DOC = ROOT / "docs" / "homm3_faction_plans" / "rampart.md"


def _unit_sid(line: dict[str, Any], suffix: str) -> str:
    variant_sids = line.get("variantSids")
    if isinstance(variant_sids, dict) and isinstance(variant_sids.get(suffix), str):
        return variant_sids[suffix]
    return line["baseSid"] + suffix


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validation = manifest.get("validation") or {}
    status = validation.get("status")
    print(f"Rampart manifest: {MANIFEST}")
    print(f"Source doc: {SOURCE_DOC}")
    print(f"Status: {status}")
    print("Expanded unit SIDs:")
    for line in manifest.get("unitLines", []):
        sids = [_unit_sid(line, suffix) for suffix in manifest.get("unitVariants", [])]
        print(f"  tier {line['tier']}: {', '.join(sids)}")

    if status != "release_ready":
        print()
        print("Release overlay is intentionally blocked. Required before promotion:")
        for debt in validation.get("allowedDebt") or []:
            print(f"  - {debt}")
        return 0

    print("Rampart is marked release_ready, but this stub does not generate Core rows yet.")
    print("Promote it by adding a manifest-driven generator to apply_release_core_overlay.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
