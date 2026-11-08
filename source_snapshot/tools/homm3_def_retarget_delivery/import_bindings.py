"""Per-unit pins on homm3_import.json for def_retarget runtime records (docs/plugin_payload_abi.md, "Import bindings").

A runtime record used to pin the sha256 of the whole import table. Any other unit's binding edit staled every record.
It now pins one digest per unit of its own selection:

    "importBindings": {"schema": "homm3_import_unit_bindings.v1", "units": {"<labSid>": "<sha256>", ...}}

A unit's digest covers the table's global keys (everything but "entries", e.g. battleWorldHeightPerHex) plus every
entry that concerns the unit: its prefab under Assets/CustomUnits/homm3_lab/<labSid>/, its bundleName, or its gameSid
in gameUnitSids. Entries are canonical JSON (sorted keys) in sorted order, so moving rows does not change a digest.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "homm3_import_unit_bindings.v1"
KEY = "importBindings"


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def unit_entries(table: dict, row: dict) -> list[dict]:
    lab = f"Assets/CustomUnits/homm3_lab/{row['labSid']}/"
    return [e for e in table.get("entries", [])
            if str(e.get("battlePrefabAssetPath", "")).startswith(lab) or str(e.get("mapPrefabAssetPath", "")).startswith(lab)
            or e.get("bundleName") == row.get("bundleName") or row.get("gameSid") in (e.get("gameUnitSids") or [])]


def unit_digest(table: dict, row: dict) -> str:
    entries = unit_entries(table, row)
    if not entries:
        raise ValueError(f"homm3_import.json has no binding for {row['labSid']}")
    body = {"global": {k: v for k, v in table.items() if k != "entries"}, "entries": sorted(_canon(e) for e in entries)}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


def pin(table: dict, rows: list[dict]) -> dict:
    return {"schema": SCHEMA, "units": {r["labSid"]: unit_digest(table, r) for r in rows}}


def check(record_pin: dict, table: dict, rows: list[dict], what: str) -> None:
    """Fail closed unless the pin covers exactly these rows and each unit's bindings in `table` still hash to it."""
    if not isinstance(record_pin, dict) or record_pin.get("schema") != SCHEMA or not isinstance(record_pin.get("units"), dict):
        raise ValueError(f"runtime record has no {KEY} {SCHEMA} pin")
    want = {r["labSid"] for r in rows}
    if set(record_pin["units"]) != want:
        raise ValueError(f"{KEY} pins {sorted(record_pin['units'])}, the selection ships {sorted(want)}")
    changed = [r["labSid"] for r in rows if unit_digest(table, r) != record_pin["units"][r["labSid"]]]
    if changed:
        raise ValueError(f"{what}: the bindings of {changed} changed since the recorded runtime build")
