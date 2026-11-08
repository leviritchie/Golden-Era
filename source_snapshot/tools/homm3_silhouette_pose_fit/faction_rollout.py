#!/usr/bin/env python3
"""Faction-scoped ordering for fused_push skinned-mesh rollout + Golden Era install.

One faction is fully fitted, exported, and deployed (battle meshes + audio + adventure
map paths) before the next faction begins.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
CUSTOM_FACTIONS = ROOT / "custom_factions"
UNITS_MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
STATUS_PATH = ROOT / "artifacts/homm3_smartrig_skinned_rollout/status.json"
GPU_RUN_NAME = "fused_push_v24_pipeline"
VARIANT_SUFFIXES = ("", "_upg", "_upg_alt")

# Castle is the active pilot (Crusader fused_push in progress).
FACTION_ROLLOUT_ORDER: tuple[str, ...] = (
    "homm3_castle",
    "homm3_rampart",
    "homm3_tower",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_dungeon",
    "homm3_stronghold",
    "homm3_fortress",
    "homm3_conflux",
    "homm3_cove",
    "homm3_factory",
    "homm3_bulwark",
)

_BUNDLE_SLUG_RE = re.compile(r"^custom_units_([^_]+)_")


def normalize_faction_key(key: str) -> str:
    value = str(key or "").strip().lower().replace("-", "_")
    if not value:
        raise ValueError("faction key is required")
    if not value.startswith("homm3_"):
        value = f"homm3_{value}"
    if value not in FACTION_ROLLOUT_ORDER:
        known = ", ".join(FACTION_ROLLOUT_ORDER)
        raise ValueError(f"unknown faction {value!r}; expected one of: {known}")
    return value


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bundle_slug(bundle_name: str) -> str | None:
    match = _BUNDLE_SLUG_RE.match(str(bundle_name or ""))
    return match.group(1) if match else None


def faction_key_from_bundle(bundle_name: str) -> str | None:
    slug = bundle_slug(bundle_name)
    if not slug:
        return None
    candidate = f"homm3_{slug}"
    return candidate if candidate in FACTION_ROLLOUT_ORDER else None


def faction_key_from_import_relpath(path: str) -> str | None:
    """Map ``homm3_import/<faction>/...`` onto a rollout faction key.

    Legacy Stronghold bundles are ``custom_units_h3_goblin`` (no town slug).
    Overlay and preview paths still name the town.
    """
    text = str(path or "").replace("\\", "/")
    marker = "homm3_import/"
    index = text.find(marker)
    if index < 0:
        return None
    slug = text[index + len(marker) :].split("/", 1)[0].strip()
    if not slug:
        return None
    candidate = f"homm3_{slug}"
    return candidate if candidate in FACTION_ROLLOUT_ORDER else None


def _assign_lab_sid_faction(mapping: dict[str, str], sid: str, faction: str) -> None:
    previous = mapping.get(sid)
    if previous is not None and previous != faction:
        raise RuntimeError(
            f"{sid} maps to both {previous} and {faction}; faction membership must be unique"
        )
    mapping[sid] = faction


def catalog_rows() -> list[dict[str, Any]]:
    payload = _load_json(UNITS_MANIFEST)
    units = payload.get("units")
    if not isinstance(units, list):
        raise RuntimeError(f"{UNITS_MANIFEST} has no units list")
    return [row for row in units if isinstance(row, dict) and row.get("unitSid")]


def lab_sid_to_faction_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in catalog_rows():
        sid = str(row.get("unitSid") or "").strip()
        faction = faction_key_from_bundle(str(row.get("bundleName") or ""))
        if sid and faction:
            _assign_lab_sid_faction(mapping, sid, faction)
    if STATUS_PATH.is_file():
        payload = _load_json(STATUS_PATH)
        units = payload.get("units")
        if not isinstance(units, list):
            raise RuntimeError(f"{STATUS_PATH} has no units list")
        for row in units:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("labSid") or "").strip()
            if not sid:
                continue
            scale = row.get("scale") if isinstance(row.get("scale"), dict) else {}
            candidates = (
                row.get("previewPath"),
                row.get("adventureMapPath"),
                scale.get("mesh"),
                scale.get("mapMesh"),
            )
            for candidate in candidates:
                faction = faction_key_from_import_relpath(str(candidate or ""))
                if faction:
                    _assign_lab_sid_faction(mapping, sid, faction)
                    break
    return mapping


def faction_catalog_lab_sids(faction_key: str) -> list[str]:
    faction_key = normalize_faction_key(faction_key)
    mapping = lab_sid_to_faction_key()
    sids: list[str] = []
    seen: set[str] = set()
    for row in catalog_rows():
        sid = str(row.get("unitSid") or "").strip()
        if not sid or sid in seen:
            continue
        if mapping.get(sid) == faction_key:
            sids.append(sid)
            seen.add(sid)
    for sid, mapped in mapping.items():
        if mapped == faction_key and sid not in seen:
            sids.append(sid)
            seen.add(sid)
    return sids


def faction_tier_lab_sids(faction_key: str) -> list[str]:
    """Tier order from custom_factions unitLines (base + upgrade variants)."""
    faction_key = normalize_faction_key(faction_key)
    path = CUSTOM_FACTIONS / f"{faction_key}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = _load_json(path)
    catalog = set(faction_catalog_lab_sids(faction_key))
    ordered: list[str] = []
    seen: set[str] = set()
    for line in payload.get("unitLines") or []:
        if not isinstance(line, dict):
            continue
        base = str(line.get("baseSid") or "").strip()
        if not base:
            continue
        for suffix in VARIANT_SUFFIXES:
            sid = f"{base}{suffix}" if suffix else base
            if sid in catalog and sid not in seen:
                ordered.append(sid)
                seen.add(sid)
    for sid in sorted(catalog - seen):
        ordered.append(sid)
    return ordered


def bundle_names_for_faction(faction_key: str) -> list[str]:
    faction_key = normalize_faction_key(faction_key)
    names: list[str] = []
    for row in catalog_rows():
        bundle = str(row.get("bundleName") or "").strip()
        if faction_key_from_bundle(bundle) == faction_key:
            names.append(bundle)
    return sorted(names)


def active_faction_key(
    *,
    clip_done: Callable[[str, str], bool],
    status_units: Sequence[Mapping[str, Any]],
    all_choices: Sequence[Any],
    mesh_blocked: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> str | None:
    """First faction in rollout order that still has pending own-GLB clip work."""
    from gpu_cascade_delivery import select_unit_delivery_choices

    own_by_faction: dict[str, list[Mapping[str, Any]]] = {key: [] for key in FACTION_ROLLOUT_ORDER}
    sid_faction = lab_sid_to_faction_key()
    for row in status_units:
        if row.get("meshRole") != "own_glb":
            continue
        sid = str(row.get("labSid") or "")
        faction = sid_faction.get(sid)
        if faction:
            own_by_faction.setdefault(faction, []).append(row)

    for faction_key in FACTION_ROLLOUT_ORDER:
        rows = own_by_faction.get(faction_key) or []
        if not rows:
            continue
        for row in rows:
            sid = str(row["labSid"])
            if mesh_blocked and mesh_blocked(row):
                continue
            try:
                choices = select_unit_delivery_choices(all_choices, sid)
            except RuntimeError:
                return faction_key
            for choice in choices:
                if not clip_done(sid, str(choice.animation_name)):
                    return faction_key
    return None


def faction_clip_progress(
    faction_key: str,
    *,
    status_units: Sequence[Mapping[str, Any]],
    all_choices: Sequence[Any],
    clip_done: Callable[[str, str], bool],
    mesh_blocked: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict[str, Any]:
    from gpu_cascade_delivery import select_unit_delivery_choices

    faction_key = normalize_faction_key(faction_key)
    sid_order = faction_tier_lab_sids(faction_key)
    sid_set = set(sid_order)
    units_out: list[dict[str, Any]] = []
    total = 0
    done = 0
    blocked: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    status_by_sid = {
        str(row.get("labSid")): row for row in status_units if row.get("labSid")
    }
    for sid in sid_order:
        row = status_by_sid.get(sid)
        if row is None or row.get("meshRole") != "own_glb":
            continue
        block = mesh_blocked(row) if mesh_blocked else None
        if block:
            blocked.append({"labSid": sid, "reason": block})
            continue
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            errors.append({"labSid": sid, "error": str(exc)})
            continue
        clip_rows = []
        for choice in choices:
            animation = str(choice.animation_name)
            total += 1
            complete = clip_done(sid, animation)
            if complete:
                done += 1
            clip_rows.append({"animation": animation, "complete": complete})
        units_out.append({"labSid": sid, "clips": clip_rows})

    extra_sids = sorted(
        sid
        for sid, row in status_by_sid.items()
        if sid in sid_set and sid not in {u["labSid"] for u in units_out}
        and row.get("meshRole") == "own_glb"
    )
    for sid in extra_sids:
        row = status_by_sid[sid]
        block = mesh_blocked(row) if mesh_blocked else None
        if block:
            blocked.append({"labSid": sid, "reason": block})
            continue
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            errors.append({"labSid": sid, "error": str(exc)})
            continue
        clip_rows = []
        for choice in choices:
            animation = str(choice.animation_name)
            total += 1
            complete = clip_done(sid, animation)
            if complete:
                done += 1
            clip_rows.append({"animation": animation, "complete": complete})
        units_out.append({"labSid": sid, "clips": clip_rows})

    pending = total - done
    return {
        "factionKey": faction_key,
        "bundleNames": bundle_names_for_faction(faction_key),
        "labSidOrder": sid_order,
        "totalClips": total,
        "completedClips": done,
        "pendingClips": pending,
        "complete": pending == 0 and not errors,
        "blockedUnits": blocked,
        "planErrors": errors,
        "units": units_out,
    }


def sort_jobs_by_faction(
    jobs: Sequence[tuple[Mapping[str, Any], Any]],
    faction_key: str,
) -> list[tuple[Mapping[str, Any], Any]]:
    order = {sid: index for index, sid in enumerate(faction_tier_lab_sids(faction_key))}
    return sorted(
        list(jobs),
        key=lambda item: (
            order.get(str(item[0].get("labSid")), 10_000),
            str(item[1].animation_name),
        ),
    )


def filter_units_for_faction(
    units: Sequence[Mapping[str, Any]],
    faction_key: str,
) -> list[dict[str, Any]]:
    faction_key = normalize_faction_key(faction_key)
    allowed = set(faction_tier_lab_sids(faction_key))
    filtered = [dict(row) for row in units if str(row.get("labSid")) in allowed]
    order = {sid: index for index, sid in enumerate(faction_tier_lab_sids(faction_key))}
    filtered.sort(key=lambda row: order.get(str(row.get("labSid")), 10_000))
    return filtered
