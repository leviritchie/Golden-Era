#!/usr/bin/env python3
"""Load and query tools/homm3_import/faction_concepts/homm3_neutral.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
NEUTRAL_CATALOG_PATH = REPO_ROOT / "tools" / "homm3_import" / "faction_concepts" / "homm3_neutral.json"


def load_homm3_neutral_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or NEUTRAL_CATALOG_PATH
    doc = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict):
        raise ValueError(f"{catalog_path}: catalog root must be an object")
    units = doc.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError(f"{catalog_path}: units must be a non-empty array")
    return doc


def catalog_units(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    doc = catalog if catalog is not None else load_homm3_neutral_catalog()
    return [row for row in doc.get("units", []) if isinstance(row, dict)]


def catalog_unit_sids(catalog: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(str(row["sid"]) for row in catalog_units(catalog))


def pool_eligible_unit_sids(catalog: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(str(row["sid"]) for row in catalog_units(catalog) if row.get("poolEligible") is True)


def catalog_dwellings(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in catalog_units(catalog):
        dwelling = row.get("dwelling")
        if not isinstance(dwelling, dict):
            continue
        out.append(
            {
                "unitSid": str(row["sid"]),
                "displayName": str(row.get("displayName") or row["sid"]),
                "tier": int(row.get("tier") or 1),
                **dwelling,
            }
        )
    return out


def unit_logic_path(sid: str, catalog: dict[str, Any] | None = None) -> str:
    doc = catalog if catalog is not None else load_homm3_neutral_catalog()
    folder = str((doc.get("coreOverlay") or {}).get("logicFolder") or "DB/units/units_logics/neutral/")
    return f"{folder}{sid}_l.json"


def unit_view_path(sid: str, catalog: dict[str, Any] | None = None) -> str:
    doc = catalog if catalog is not None else load_homm3_neutral_catalog()
    folder = str((doc.get("coreOverlay") or {}).get("viewFolder") or "DB/units/units_views/neutral/")
    return f"{folder}{sid}_v.json"


def dwelling_def_to_barracks_sid(catalog: dict[str, Any] | None = None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for dwelling in catalog_dwellings(catalog):
        barracks_sid = str(dwelling["barracksSid"])
        names = [str(dwelling["defName"])]
        aliases = dwelling.get("defNameAliases") or []
        if isinstance(aliases, list):
            names.extend(str(alias) for alias in aliases)
        for name in names:
            mapping[name] = barracks_sid
            mapping[name.lower()] = barracks_sid
    return mapping
