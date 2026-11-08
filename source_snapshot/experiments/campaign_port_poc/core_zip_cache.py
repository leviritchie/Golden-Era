#!/usr/bin/env python3
"""Process-level Core.zip JSON/member cache for raw_translation emit.

Frozen-Core batch workers and single-mission emits repeatedly open the same zip
and re-parse the same members (map objects, Lang texts, unit rows). Cache by
(path, mtime_ns, size) so a replaced Core.zip still invalidates cleanly.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

_CACHE_IDENTITY: tuple[str, int, int] | None = None
_MEMBER_JSON: dict[str, Any] = {}
_MEMBER_BYTES: dict[str, bytes] = {}
_NAMELIST: list[str] | None = None
_MAP_OBJECT_BY_ID: dict[str, dict[str, Any]] | None = None
# The archive is held in memory (not as an open file), so the process never locks Core.zip
# against an installer replacing it; re-parsing the central directory per member cost
# ~0.2 s a read.
_ARCHIVE: zipfile.ZipFile | None = None


def _identity(core_zip: Path) -> tuple[str, int, int]:
    resolved = core_zip.resolve()
    stat = resolved.stat()
    return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))


def clear_core_zip_cache() -> None:
    global _CACHE_IDENTITY, _NAMELIST, _MAP_OBJECT_BY_ID, _ARCHIVE
    _CACHE_IDENTITY = None
    _MEMBER_JSON.clear()
    _MEMBER_BYTES.clear()
    _NAMELIST = None
    _MAP_OBJECT_BY_ID = None
    _ARCHIVE = None


def _ensure_identity(core_zip: Path) -> tuple[str, int, int]:
    global _CACHE_IDENTITY, _NAMELIST, _MAP_OBJECT_BY_ID, _ARCHIVE
    ident = _identity(core_zip)
    if _CACHE_IDENTITY != ident:
        _MEMBER_JSON.clear()
        _MEMBER_BYTES.clear()
        _NAMELIST = None
        _MAP_OBJECT_BY_ID = None
        _ARCHIVE = None
        _CACHE_IDENTITY = ident
    return ident


def core_identity(core_zip: Path | str) -> tuple[str, int, int]:
    """(resolved path, mtime_ns, size) of the Core.zip the cache is bound to."""
    return _ensure_identity(Path(core_zip))


def _archive(path: Path) -> zipfile.ZipFile:
    global _ARCHIVE
    _ensure_identity(path)
    if _ARCHIVE is None:
        _ARCHIVE = zipfile.ZipFile(io.BytesIO(path.read_bytes()), "r")
    return _ARCHIVE


def core_namelist(core_zip: Path | str) -> list[str]:
    global _NAMELIST
    path = Path(core_zip)
    _ensure_identity(path)
    if _NAMELIST is None:
        _NAMELIST = list(_archive(path).namelist())
    return _NAMELIST


def read_core_bytes(core_zip: Path | str, member: str) -> bytes:
    path = Path(core_zip)
    _ensure_identity(path)
    cached = _MEMBER_BYTES.get(member)
    if cached is not None:
        return cached
    data = _archive(path).read(member)
    _MEMBER_BYTES[member] = data
    return data


def read_core_json(core_zip: Path | str, member: str) -> Any:
    path = Path(core_zip)
    _ensure_identity(path)
    if member in _MEMBER_JSON:
        return _MEMBER_JSON[member]
    text = read_core_bytes(path, member).decode("utf-8-sig")
    doc = json.loads(text)
    _MEMBER_JSON[member] = doc
    return doc


def map_object_configs_by_id(core_zip: Path | str) -> dict[str, dict[str, Any]]:
    """Parse every DB/map/objects/*.json row once; return id → row."""
    global _MAP_OBJECT_BY_ID
    path = Path(core_zip)
    _ensure_identity(path)
    if _MAP_OBJECT_BY_ID is not None:
        return _MAP_OBJECT_BY_ID
    configs: dict[str, dict[str, Any]] = {}
    for name in core_namelist(path):
        if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
            continue
        doc = read_core_json(path, name)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"Core map-object member has no array rows: {name}")
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                configs[row["id"]] = row
    _MAP_OBJECT_BY_ID = configs
    return configs
