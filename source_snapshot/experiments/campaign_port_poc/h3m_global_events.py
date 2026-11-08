#!/usr/bin/env python3
"""Decode H3M post-object-table global timed events (VCMI CMapLoaderH3M::readEvents)."""

from __future__ import annotations

from typing import Any

import h3m_object_walk as walk_engine

SCHEMA = "homm3.h3m_global_timed_events.v1"
# RoE/AB (v14/v21): no humanAffected byte after players mask
# (Homecoming Good-1a.h3m v21 proven).
# SoD+ (v28+): humanAffected is present (Specter Secret.h3c maps proven).
# HotA adds further trailing fields after the shared SoD body.
GLOBAL_EVENT_ZERO_PAD_BYTES = 16


def read_global_timed_events(data: bytes, walk_end_offset: int, *, h3m_version: int) -> dict[str, Any]:
    if walk_end_offset < 0 or walk_end_offset > len(data):
        raise ValueError(f"walkEndOffset out of range: {walk_end_offset:#x} len={len(data)}")
    walker = walk_engine.Walker(data)
    walker.seek(walk_end_offset)
    if walker.tell() == len(data):
        return {
            "schema": SCHEMA,
            "status": "empty_tail",
            "walkEndOffset": f"0x{walk_end_offset:x}",
            "eventCount": 0,
            "events": [],
            "bytesConsumed": 0,
            "remainingBytes": 0,
            "layout": "none",
        }

    event_count = walker.read_u32()
    if event_count > 256:
        raise ValueError(f"implausible global timed event count {event_count} at {walk_end_offset:#x}")

    import h3m_format as h3m

    has_human_affected = int(h3m_version) >= h3m.H3M_VERSION_SOD
    events: list[dict[str, Any]] = []
    for index in range(event_count):
        name = walker.read_string()
        message = walker.read_string(max_length=1_000_000)
        resources = [walker.read_i32() for _ in range(walk_engine.RESOURCES_COUNT)]
        players_mask = walker.read_u8()
        human_affected: int | None
        if has_human_affected:
            human_affected = walker.read_u8()
        else:
            human_affected = None
        computer_affected = walker.read_u8()
        first_occurrence = walker.read_u16()
        next_occurrence = walker.read_u16()
        pad_offset = walker.tell()
        pad = data[pad_offset : pad_offset + GLOBAL_EVENT_ZERO_PAD_BYTES]
        if len(pad) != GLOBAL_EVENT_ZERO_PAD_BYTES:
            raise ValueError(f"global timed event {index} truncated zero pad at {pad_offset:#x}")
        if pad != b"\x00" * GLOBAL_EVENT_ZERO_PAD_BYTES:
            raise ValueError(
                f"global timed event {index} expected {GLOBAL_EVENT_ZERO_PAD_BYTES} zero bytes at {pad_offset:#x}, "
                f"got {pad.hex()}"
            )
        walker.skip(GLOBAL_EVENT_ZERO_PAD_BYTES)
        event = {
            "index": index,
            "name": name,
            "message": message,
            "resources": resources,
            "playersMask": players_mask,
            "humanAffected": human_affected,
            "computerAffected": bool(computer_affected),
            "firstOccurrence": first_occurrence,
            "nextOccurrence": next_occurrence,
            # H3M firstOccurrence is 0-based (0 = calendar day 1).
            "triggerDay": int(first_occurrence) + 1,
        }
        if h3m_version == walk_engine.h3m.H3M_VERSION_HOTA:
            event["affectedDifficulties"] = walker.read_u32()
            uses_event_system = walker.read_bool()
            event["usesEventSystem"] = uses_event_system
            if uses_event_system:
                event["eventId"] = walker.read_i32()
                event["synchronizeObjects"] = walker.read_bool()
        events.append(event)

    remaining = len(data) - walker.tell()
    # Trailing zeros after events are allowed (Homecoming has 124 zero bytes).
    if remaining and any(data[walker.tell() :]):
        raise ValueError(
            f"non-zero bytes remain after global timed events at {walker.tell():#x} remaining={remaining}"
        )

    if has_human_affected and int(h3m_version) >= walk_engine.H3M_VERSION_HOTA_MIN:
        layout = "sod_or_hota_human_affected"
    elif has_human_affected:
        layout = "sod_human_affected"
    else:
        layout = "roe_ab_no_human_affected"

    return {
        "schema": SCHEMA,
        "status": "decoded",
        "walkEndOffset": f"0x{walk_end_offset:x}",
        "eventsEndOffset": f"0x{walker.tell():x}",
        "eventCount": len(events),
        "events": events,
        "bytesConsumed": walker.tell() - walk_end_offset,
        "remainingBytes": remaining,
        "layout": layout,
        "proofBoundary": "source/static decoded from H3M tail; runtime QuestScript day triggers remain separately validated",
    }


def try_read_global_timed_events(
    data: bytes,
    walk_end_offset: int,
    *,
    h3m_version: int,
) -> dict[str, Any] | None:
    """Probe whether ``walk_end_offset`` is the H3M global timed-event table.

    Used to disambiguate post-object event bytes from false-positive synthetic
    ROE campaign briefing tails (Steadwick's Liberation). Failures return None;
    callers must not treat None as empty events.
    """
    try:
        return read_global_timed_events(data, walk_end_offset, h3m_version=h3m_version)
    except ValueError:
        return None


def attach_global_timed_events(walk: dict[str, Any], data: bytes) -> dict[str, Any]:
    object_table = walk.get("objectTable") or {}
    if not object_table.get("complete"):
        walk["globalTimedEvents"] = {
            "schema": SCHEMA,
            "status": "skipped_incomplete_object_walk",
            "eventCount": 0,
            "events": [],
        }
        return walk
    walk_end = object_table.get("walkEndOffset")
    if isinstance(walk_end, str):
        walk_end_offset = int(walk_end, 16)
    elif isinstance(walk_end, int):
        walk_end_offset = walk_end
    else:
        raise ValueError(f"object walk missing walkEndOffset: {object_table}")
    h3m_meta = walk.get("h3m") or {}
    version = int(h3m_meta.get("version") or 0)
    walk["globalTimedEvents"] = read_global_timed_events(data, walk_end_offset, h3m_version=version)
    return walk
