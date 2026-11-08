"""H3 artifact id → Olden Core item SID.

Primary path: generated SoD+HotA catalog (`custom_factions/artifacts/homm3_artifact_catalog.json`).
Legacy exact stock overlaps remain available as optional aliases but campaign emit prefers catalog SIDs.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CATALOG_PATH = _REPO_ROOT / "custom_factions" / "artifacts" / "homm3_artifact_catalog.json"

# Proven by stock Lang/english/texts/artifacts.json display names + map object rows.
# Kept for documentation / optional aliasing only — emit uses catalog SIDs.
STOCK_H3_ARTIFACT_ID_TO_ITEM_SID: dict[int, str] = {
    # Endless Bag of Gold → stock "Endless Bag"
    116: "endless_bag_artifact",
    # Ogre's Club of Havoc (exact name match)
    10: "ogres_club_of_havoc_artifact",
}


@lru_cache(maxsize=1)
def _catalog_by_h3_id() -> dict[int, str]:
    if not _CATALOG_PATH.is_file():
        return {}
    doc = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for row in doc.get("artifacts") or []:
        if not isinstance(row, dict):
            continue
        try:
            h3_id = int(row["h3Id"])
            sid = str(row["sid"])
        except (KeyError, TypeError, ValueError):
            continue
        out[h3_id] = sid
    return out


def catalog_item_sid_for_h3_artifact_id(artifact_id: int) -> str | None:
    return _catalog_by_h3_id().get(int(artifact_id))


def stock_item_sid_for_h3_artifact_id(artifact_id: int) -> str | None:
    """Prefer generated HoMM3 catalog SID; fall back to tiny exact stock map."""
    sid = catalog_item_sid_for_h3_artifact_id(artifact_id)
    if sid:
        return sid
    return STOCK_H3_ARTIFACT_ID_TO_ITEM_SID.get(int(artifact_id))


def require_item_sid_for_h3_artifact_id(artifact_id: int) -> str:
    sid = stock_item_sid_for_h3_artifact_id(artifact_id)
    if not sid:
        raise KeyError(f"no HoMM3 artifact catalog SID for h3Id={artifact_id}")
    return sid


def catalog_rows() -> list[dict[str, Any]]:
    if not _CATALOG_PATH.is_file():
        return []
    doc = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    rows = doc.get("artifacts") or []
    return [r for r in rows if isinstance(r, dict)]
