#!/usr/bin/env python3
"""Validate the active Factory/Bulwark source and 45-row ownership contract (Sandworm Larva retired: no Core unit).

The earlier neutral-pool and alternate-concept contract is superseded. Active
faction manifests and pinned Factory/Bulwark archives are now authoritative.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_hota_factory_bulwark_runtime_assets import (  # noqa: E402
    BUILD_OUT,
    CONTRACT,
    IMPORT_TABLE,
    SPECS,
    active_unit_lines,
    expected_import_rows,
    load_json,
    validate_active_manifest_contract,
)

RETIRED_LARVA_SID = "h3_sandworm_larva"
RETIRED_LARVA_BUNDLE = "custom_units_factory_hota_factory_sandworm_larva"


def main() -> int:
    expected_recruits = []
    for spec in SPECS:
        manifest = validate_active_manifest_contract(spec)
        expected_recruits.extend(
            line["variantSids"][variant]
            for line in active_unit_lines(manifest)
            for variant in manifest["unitVariants"]
        )

    rows = expected_import_rows()
    actual_sids = [row["gameUnitSids"][0] for row in rows]
    expected_sids = expected_recruits
    if len(expected_recruits) != 45:
        raise SystemExit(f"FAIL: active Factory/Bulwark recruit ownership count {len(expected_recruits)} != 45")
    if len(rows) != 45 or len(set(actual_sids)) != 45:
        raise SystemExit(f"FAIL: exact ownership rows are not 45 unique rows: {len(rows)} rows")
    if actual_sids != expected_sids:
        raise SystemExit("FAIL: 45-row ownership order drifted from active manifests")
    # Retired orphan: no Core unit defines or summons h3_sandworm_larva, so its bundle must not ship
    # (see expected_import_rows). Pinned so the row cannot silently come back without its Core unit.
    larva_rows = [row for row in (load_json(IMPORT_TABLE).get("entries") or [])
                  if RETIRED_LARVA_SID in (row.get("gameUnitSids") or [])]
    if larva_rows:
        raise SystemExit(f"FAIL: homm3_import.json still binds retired {RETIRED_LARVA_SID} (no Core unit)")
    if RETIRED_LARVA_BUNDLE in (load_json(CONTRACT).get("bundles") or {}):
        raise SystemExit(f"FAIL: bundle payload contract still ships retired {RETIRED_LARVA_BUNDLE}")

    expected_sid_set = set(expected_sids)
    import_rows = [
        row
        for row in (load_json(IMPORT_TABLE).get("entries") or [])
        if expected_sid_set.intersection(row.get("gameUnitSids") or [])
    ]
    expected_by_sid = {row["gameUnitSids"][0]: row for row in rows}
    if import_rows != rows:
        raise SystemExit("FAIL: active homm3_import.json rows drifted from exact generated ownership rows")
    couatl_alt = expected_by_sid["h3_couatl_upg_alt"]
    safe_shell = "units/Nature/1Prefabs/phoenix_upg"
    if couatl_alt.get("battlePresentationResPath") != safe_shell:
        raise SystemExit("FAIL: h3_couatl_upg_alt must use the safe phoenix_upg battle shell")
    if any(row.get("battlePresentationResPath") == "units/Nature/1Prefabs/phoenix_upg_alt" for row in rows):
        raise SystemExit("FAIL: unsafe phoenix_upg_alt battle shell remains in Factory/Bulwark rows")
    bundle_name = couatl_alt["bundleName"]
    bundle_data = (BUILD_OUT / bundle_name).read_bytes()
    expected_bundle = {"length": len(bundle_data), "sha256": hashlib.sha256(bundle_data).hexdigest().upper()}
    if (load_json(CONTRACT).get("bundles") or {}).get(bundle_name) != expected_bundle:
        raise SystemExit(f"FAIL: bundle payload contract row drifted: {bundle_name}")

    for spec in SPECS:
        manifest_sids = {
            line["variantSids"][variant]
            for line in active_unit_lines(load_json(spec.manifest))
            for variant in ("", "_upg", "_upg_alt")
        }
        row_sids = {sid for sid in actual_sids if sid in manifest_sids}
        if row_sids != manifest_sids:
            raise SystemExit(f"FAIL: {spec.sid} unit ownership rows are incomplete")

    print("validated active Factory/Bulwark pinned sources and 45 exact ownership rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())