"""Olden objectsProperties id namespaces: objects (type 0) vs markers (type 1).

Raw translation converts unguarded map events into Zone markers whose property
rows use ``type=1`` and an id space owned by ``markers[]``, not ``objects[]``.
Object-only orphan / deletion sweeps must never treat those rows as missing
object props — doing so wipes Dialog bindings before marker id rebase.
"""

from __future__ import annotations

from typing import Any

# Native Olden property host kinds used by raw_translation emit.
OBJECT_PROPERTY_TYPE = 0
MARKER_PROPERTY_TYPE = 1


def property_host_type(row: dict[str, Any]) -> int:
    """Return the host namespace for a property row (missing type ⇒ object)."""
    host_type = row.get("type")
    if host_type is None:
        return OBJECT_PROPERTY_TYPE
    if not isinstance(host_type, int):
        raise TypeError(f"objectsProperties row type must be int or omitted; got {host_type!r}")
    return host_type


def is_object_property_row(row: dict[str, Any]) -> bool:
    return property_host_type(row) == OBJECT_PROPERTY_TYPE


def is_marker_property_row(row: dict[str, Any]) -> bool:
    return property_host_type(row) == MARKER_PROPERTY_TYPE


def live_object_ids(objects: list[dict[str, Any]] | None) -> set[int]:
    live: set[int] = set()
    for group in objects or []:
        if not isinstance(group, dict):
            continue
        for object_id in group.get("ids") or []:
            if isinstance(object_id, int):
                live.add(object_id)
    return live


def live_marker_ids(markers: list[dict[str, Any]] | None) -> set[int]:
    live: set[int] = set()
    for marker in markers or []:
        if not isinstance(marker, dict):
            continue
        marker_id = marker.get("id")
        if isinstance(marker_id, int):
            live.add(marker_id)
    return live


def remove_object_property_rows(properties: dict[str, Any] | None, remove_ids: set[int]) -> int:
    """Drop object-namespace rows whose id was removed from objects[].

    Marker-namespace rows (type 1) are never removed by object-id coincidence.
    Returns the number of removed rows.
    """
    if not properties or not remove_ids:
        return 0
    removed = 0
    for key, rows in list(properties.items()):
        if not isinstance(rows, list):
            continue
        kept: list[Any] = []
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and row["id"] in remove_ids
                and is_object_property_row(row)
            ):
                removed += 1
                continue
            kept.append(row)
        properties[key] = kept
    return removed


def scrub_orphan_object_namespace_properties(
    properties: dict[str, Any] | None,
    *,
    live_object_ids: set[int],
) -> int:
    """Remove type-0 property rows whose id is absent from live objects.

    Type-1 (marker) rows are preserved for a separate marker-live check.
    Returns removed row count.
    """
    if not properties:
        return 0
    removed = 0
    for key, rows in list(properties.items()):
        if not isinstance(rows, list):
            continue
        kept: list[Any] = []
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and is_object_property_row(row)
                and row["id"] not in live_object_ids
            ):
                removed += 1
                continue
            kept.append(row)
        properties[key] = kept
    return removed


def scrub_orphan_marker_namespace_properties(
    properties: dict[str, Any] | None,
    *,
    live_marker_ids: set[int],
) -> int:
    """Remove type-1 property rows whose id is absent from markers[]."""
    if not properties:
        return 0
    removed = 0
    for key, rows in list(properties.items()):
        if not isinstance(rows, list):
            continue
        kept: list[Any] = []
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and is_marker_property_row(row)
                and row["id"] not in live_marker_ids
            ):
                removed += 1
                continue
            kept.append(row)
        properties[key] = kept
    return removed


def assert_marker_property_integrity(
    *,
    markers: list[dict[str, Any]] | None,
    properties: dict[str, Any] | None,
    context: str,
) -> None:
    """Fail closed when Zone markers lack activation rows or type-1 hosts drift."""
    marker_list = [row for row in (markers or []) if isinstance(row, dict)]
    if not marker_list:
        return
    props = properties if isinstance(properties, dict) else {}
    live = live_marker_ids(marker_list)
    prop_markers = [
        row
        for row in (props.get("propMarkers") or [])
        if isinstance(row, dict) and is_marker_property_row(row)
    ]
    prop_marker_ids = {
        int(row["id"]) for row in prop_markers if isinstance(row.get("id"), int)
    }
    if prop_marker_ids != live:
        raise ValueError(
            f"{context}: markers[] ids {sorted(live)} must equal propMarkers ids "
            f"{sorted(prop_marker_ids)}"
        )
    for family, rows in props.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not is_marker_property_row(row):
                continue
            row_id = row.get("id")
            if not isinstance(row_id, int) or row_id not in live:
                raise ValueError(
                    f"{context}: {family} type=1 id={row_id!r} is not in markers[] {sorted(live)}"
                )
