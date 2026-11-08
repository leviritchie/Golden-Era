"""Custom-game menu shell for campaign-port maps (LocKit SIDs + vanilla length budgets).

Vanilla Golden Era custom maps store LocKit SIDs in meta/mapData with
``nameFromLocalization`` / ``descFromLocalization`` / ``mapNameFromLoc`` /
``mapDescFromLoc`` true, and leave ``displayWinCondition`` empty. Measured
English LocKit budgets from shipped ``Lang/english/texts/customMaps.json``
resolved against installed vanilla ``*.map`` files (2026-07-12):

- title max length: 23 (``Ascension to the Throne``, ``Song of the Murmurwoods``)
- description max length: 172 (``scenario_3_desc`` / Gorges of Discord)
- ``displayWinCondition``: empty string on every shipped vanilla custom map

Engineering profile titles/descriptions must not be written into map meta; doing
so produces the messy custom-game menu copy observed in playtest. Missing LocKit
rows surface as player-visible ``LOC:…`` placeholders (same class as town
``customCityName``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Evidence-backed English LocKit budgets (vanilla customMaps + installed maps).
VANILLA_MENU_TITLE_MAX_CHARS = 23
VANILLA_MENU_DESC_MAX_CHARS = 172

# Map SID -> (title LocKit SID, description LocKit SID).
MENU_SHELL_BY_MAP_SID: dict[str, tuple[str, str]] = {
    # Homecoming pipelines (short variant titles stay within the 23-char budget).
    "h3_roe_castle_homecoming_poc": (
        "homm3_roe_castle_homecoming_title",
        "homm3_roe_castle_homecoming_description",
    ),
    "h3_roe_castle_homecoming_raw_translation": (
        "homm3_roe_castle_homecoming_raw_title",
        "homm3_roe_castle_homecoming_description",
    ),
    "h3_roe_castle_homecoming_underground_slice": (
        "homm3_roe_castle_homecoming_slice_title",
        "homm3_roe_castle_homecoming_description",
    ),
    # RoE Castle batch missions (raw_translation installs).
    "h3_roe_castle_guardian_angels_raw_translation": (
        "homm3_roe_castle_guardian_angels_title",
        "homm3_roe_castle_guardian_angels_description",
    ),
    "h3_roe_castle_griffin_cliff_raw_translation": (
        "homm3_roe_castle_griffin_cliff_title",
        "homm3_roe_castle_griffin_cliff_description",
    ),
    "h3_roe_castle_steadwick_liberation_raw_translation": (
        "homm3_roe_castle_steadwick_liberation_title",
        "homm3_roe_castle_steadwick_liberation_description",
    ),
    "h3_roe_castle_deal_with_the_devil_raw_translation": (
        "homm3_roe_castle_deal_with_the_devil_title",
        "homm3_roe_castle_deal_with_the_devil_description",
    ),
    "h3_roe_castle_neutral_affairs_raw_translation": (
        "homm3_roe_castle_neutral_affairs_title",
        "homm3_roe_castle_neutral_affairs_description",
    ),
    "h3_roe_castle_tunnels_and_troglodytes_raw_translation": (
        "homm3_roe_castle_tunnels_and_troglodytes_title",
        "homm3_roe_castle_tunnels_and_troglodytes_description",
    ),
}


@dataclass(frozen=True)
class ScenarioMenuShell:
    map_sid: str
    title_sid: str
    desc_sid: str


def resolve_menu_shell(map_sid: str) -> ScenarioMenuShell:
    token = str(map_sid or "").strip()
    if not token:
        raise ValueError("scenario menu shell requires a non-empty map SID")
    pair = MENU_SHELL_BY_MAP_SID.get(token)
    if pair is None:
        # Convention for newly generated raw_translation SIDs:
        # h3_roe_<arc>_<mission>_raw_translation
        # -> LocKit homm3_roe_<arc>_<mission>_{title,description}
        suffix = "_raw_translation"
        if token.startswith("h3_") and token.endswith(suffix):
            base = "homm3_" + token[len("h3_") : -len(suffix)]
            pair = (f"{base}_title", f"{base}_description")
    if pair is None:
        raise ValueError(
            "unregistered campaign-port map SID for custom-game menu LocKit shell: "
            f"{token!r}; known={sorted(MENU_SHELL_BY_MAP_SID)}"
        )
    title_sid, desc_sid = pair
    return ScenarioMenuShell(map_sid=token, title_sid=title_sid, desc_sid=desc_sid)


def assert_english_menu_copy_budget(title_text: str, desc_text: str, *, label: str) -> None:
    title = str(title_text or "")
    desc = str(desc_text or "")
    if len(title) > VANILLA_MENU_TITLE_MAX_CHARS:
        raise ValueError(
            f"{label} menu title exceeds vanilla English budget "
            f"{VANILLA_MENU_TITLE_MAX_CHARS} (len={len(title)}): {title!r}"
        )
    if len(desc) > VANILLA_MENU_DESC_MAX_CHARS:
        raise ValueError(
            f"{label} menu description exceeds vanilla English budget "
            f"{VANILLA_MENU_DESC_MAX_CHARS} (len={len(desc)}): {desc!r}"
        )
    if not title.strip():
        raise ValueError(f"{label} menu title must be non-empty")
    if not desc.strip():
        raise ValueError(f"{label} menu description must be non-empty")


def apply_menu_shell(meta: dict[str, Any], map_data: dict[str, Any], map_sid: str) -> ScenarioMenuShell:
    """Write LocKit menu fields onto map meta + mapData. Fail closed for unknown SIDs."""
    shell = resolve_menu_shell(map_sid)
    meta["title"] = shell.title_sid
    meta["desc"] = shell.desc_sid
    meta["displayWinCondition"] = ""
    meta["nameFromLocalization"] = True
    meta["descFromLocalization"] = True
    map_data["mapName"] = shell.title_sid
    map_data["mapDesc"] = shell.desc_sid
    map_data["mapNameFromLoc"] = True
    map_data["mapDescFromLoc"] = True
    return shell


def validate_menu_shell_fields(
    meta: dict[str, Any],
    map_data: dict[str, Any],
    map_sid: str,
    errors: list[str],
    *,
    context: str,
) -> None:
    """Fail-closed validator for generated/installed map menu fields."""
    try:
        shell = resolve_menu_shell(map_sid)
    except ValueError as exc:
        errors.append(f"{context}: {exc}")
        return

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"{context}: {message}")

    require(meta.get("title") == shell.title_sid, f"meta.title must be LocKit SID {shell.title_sid!r}")
    require(meta.get("desc") == shell.desc_sid, f"meta.desc must be LocKit SID {shell.desc_sid!r}")
    require(meta.get("displayWinCondition") == "", "meta.displayWinCondition must be empty (vanilla custom-map pattern)")
    require(meta.get("nameFromLocalization") is True, "meta.nameFromLocalization must be True")
    require(meta.get("descFromLocalization") is True, "meta.descFromLocalization must be True")
    require(map_data.get("mapName") == shell.title_sid, f"mapData.mapName must be LocKit SID {shell.title_sid!r}")
    require(map_data.get("mapDesc") == shell.desc_sid, f"mapData.mapDesc must be LocKit SID {shell.desc_sid!r}")
    require(map_data.get("mapNameFromLoc") is True, "mapData.mapNameFromLoc must be True")
    require(map_data.get("mapDescFromLoc") is True, "mapData.mapDescFromLoc must be True")
    for field_name, value in (
        ("meta.title", meta.get("title")),
        ("meta.desc", meta.get("desc")),
        ("mapData.mapName", map_data.get("mapName")),
        ("mapData.mapDesc", map_data.get("mapDesc")),
    ):
        text = str(value or "")
        require(not text.startswith("LOC:"), f"{field_name} must not be a LOC: placeholder")
        require(" " not in text, f"{field_name} must be a LocKit SID without spaces: {text!r}")
