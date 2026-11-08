#!/usr/bin/env python3
"""Copy only prepared video dependencies referenced by a current Core's StoryHubs.

This is a generated-artifact staging layer, not a video builder. It never changes
playback rows: the prepared source clip rows, MP4s, sidecars, and referenced
English cinematic tokens are merged into an explicit scratch game root.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

CORE_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
VIDEO_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "video"
CLIPS_MEMBER = "DB/clips_info.json"
CINEMATIC_MEMBER = "Lang/english/texts/cinematic.json"
REPORT_SCHEMA = "homm3.port.campaign_video_dependencies.v1"


class DependencyError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _no_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DependencyError(f"duplicate JSON object key: {key!r}")
        out[key] = value
    return out


def parse_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, DependencyError) as exc:
        raise DependencyError(f"invalid JSON in {label}: {exc}") from exc


def encode_json(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _zip_names(zf: zipfile.ZipFile, label: str) -> list[str]:
    names = [item.filename.replace("\\", "/") for item in zf.infolist()]
    if len(names) != len(set(names)):
        raise DependencyError(f"{label} contains duplicate ZIP members")
    return names


def _read_member(zf: zipfile.ZipFile, name: str, label: str, *, required: bool = True) -> bytes | None:
    try:
        return zf.read(name)
    except KeyError:
        if required:
            raise DependencyError(f"{label} is missing {name}") from None
        return None
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DependencyError(f"cannot read {name} from {label}: {exc}") from exc


def _array_rows(doc: Any, label: str) -> tuple[list[Any], Any]:
    if not isinstance(doc, dict):
        raise DependencyError(f"{label} must be a JSON object")
    array = doc.get("array")
    if isinstance(array, list):
        return array, ("list", None)
    if isinstance(array, dict) and set(array) == {"data"} and isinstance(array.get("data"), list):
        return array["data"], ("data", array)
    raise DependencyError(f"{label} must contain array list or an array object with only a data list")


def _set_array_rows(doc: dict[str, Any], rows: list[Any], shape: tuple[str, Any]) -> None:
    kind, owner = shape
    if kind == "list":
        doc["array"] = rows
    else:
        owner["data"] = rows


def _safe_basename(name: Any, label: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise DependencyError(f"{label} must be a non-empty basename")
    if "/" in name or "\\" in name or ":" in name or PureWindowsPath(name).is_absolute():
        raise DependencyError(f"{label} is not a safe basename: {name!r}")
    if any(ord(char) < 32 for char in name):
        raise DependencyError(f"{label} contains a control character")
    return name


def _clip_rows(doc: Any, label: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], tuple[str, Any]]:
    rows, shape = _array_rows(doc, label)
    by_key: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"key", "val"}:
            raise DependencyError(f"{label} row {index} must contain exactly key and val")
        key, value = row["key"], row["val"]
        if not isinstance(key, str) or not key or key.strip() != key:
            raise DependencyError(f"{label} row {index} has an invalid key")
        if key in by_key:
            raise DependencyError(f"{label} has duplicate clip key {key!r}")
        if not isinstance(value, dict):
            raise DependencyError(f"{label} row {key!r} val must be an object")
        _safe_basename(value.get("name"), f"{label} row {key!r} val.name")
        if not isinstance(value.get("haveSubtitles"), bool):
            raise DependencyError(f"{label} row {key!r} haveSubtitles must be boolean")
        by_key[key] = row
    return rows, by_key, shape


def _story_hubs(zf: zipfile.ZipFile, hub: str | None) -> dict[str, dict[str, Any]]:
    names = _zip_names(zf, "target Core.zip")
    members: dict[str, str] = {}
    for member in names:
        parts = member.split("/")
        if len(parts) == 3 and parts[0] == "campaigns" and parts[2] == "storyHub.json":
            folder = parts[1]
            if not folder or folder in {".", ".."}:
                raise DependencyError(f"invalid campaign folder in Core member {member!r}")
            if folder in members:
                raise DependencyError(f"duplicate StoryHub folder {folder!r} in target Core")
            members[folder] = member
    if hub is not None:
        _safe_basename(hub, "--hub")
        members = {hub: members[hub]} if hub in members else {}
    if not members:
        requested = f"{hub!r}" if hub else "any"
        raise DependencyError(f"target Core has no campaigns/*/storyHub.json for hub {requested}")
    out: dict[str, dict[str, Any]] = {}
    for folder, member in sorted(members.items()):
        doc = parse_json(_read_member(zf, member, "target Core") or b"", member)
        if not isinstance(doc, dict):
            raise DependencyError(f"{member} must be a JSON object")
        out[folder] = doc
    return out


def _play_video_keys(story_hubs: dict[str, dict[str, Any]]) -> list[str]:
    found: set[str] = set()

    def visit(value: Any, where: str) -> None:
        if isinstance(value, dict):
            if "type" in value:
                action_type = value["type"]
                if not isinstance(action_type, str):
                    raise DependencyError(f"{where}.type must be a string")
                if action_type == "PlayVideo":
                    values = value.get("values")
                    if not isinstance(values, list) or not values:
                        raise DependencyError(f"{where} PlayVideo.values must be a non-empty list")
                    for item in values:
                        if not isinstance(item, str) or not item or item.strip() != item:
                            raise DependencyError(f"{where} PlayVideo contains an invalid clip key")
                        found.add(item)
            for key, child in value.items():
                visit(child, f"{where}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{where}[{index}]")

    for folder, doc in story_hubs.items():
        visit(doc, f"campaigns/{folder}/storyHub.json")
    if not found:
        raise DependencyError("selected StoryHubs contain no PlayVideo action values")
    return sorted(found)


def _loc_rows(doc: Any, label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None,
                                               dict[str, dict[str, Any]], dict[str, dict[str, Any]] | None]:
    if not isinstance(doc, dict) or not isinstance(doc.get("tokens"), list):
        raise DependencyError(f"{label} must contain a tokens list")
    if "array" in doc and not isinstance(doc["array"], list):
        raise DependencyError(f"{label}.array must be a list when present")
    sections = [("tokens", doc["tokens"])]
    if "array" in doc:
        sections.append(("array", doc["array"]))
    maps: dict[str, dict[str, dict[str, Any]]] = {}
    for section, rows in sections:
        by_sid: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str) or not row["sid"]:
                raise DependencyError(f"{label}.{section}[{index}] must have a non-empty sid")
            if not isinstance(row.get("text"), str):
                raise DependencyError(f"{label}.{section}[{index}].text must be a string")
            if row["sid"] in by_sid:
                raise DependencyError(f"{label}.{section} has duplicate SID {row['sid']!r}")
            by_sid[row["sid"]] = row
        maps[section] = by_sid
    return doc["tokens"], doc.get("array"), maps["tokens"], maps.get("array")


def _parse_sidecar(data: bytes, label: str) -> tuple[list[dict[str, Any]], list[str]]:
    doc = parse_json(data, label)
    if not isinstance(doc, dict) or not isinstance(doc.get("subtitles"), list) or not doc["subtitles"]:
        raise DependencyError(f"{label} must contain a non-empty subtitles list")
    cues: list[dict[str, Any]] = []
    sids: list[str] = []
    for index, cue in enumerate(doc["subtitles"]):
        if not isinstance(cue, dict) or set(cue) != {"sid", "start", "end"}:
            raise DependencyError(f"{label}.subtitles[{index}] must contain sid, start, and end")
        sid, start, end = cue["sid"], cue["start"], cue["end"]
        if not isinstance(sid, str) or not sid or sid.strip() != sid:
            raise DependencyError(f"{label}.subtitles[{index}].sid is invalid")
        if sid in sids:
            raise DependencyError(f"{label} has duplicate subtitle SID {sid!r}")
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start):
            raise DependencyError(f"{label}.subtitles[{index}].start must be finite numeric seconds")
        if isinstance(end, bool) or not isinstance(end, (int, float)) or not math.isfinite(end) or end <= start or start < 0:
            raise DependencyError(f"{label}.subtitles[{index}].end must be finite and greater than start >= 0")
        cues.append(cue)
        sids.append(sid)
    return cues, sids


@dataclass
class ClipDependency:
    key: str
    row: dict[str, Any]
    name: str
    subtitles: bool
    video: Path
    video_hash: str
    sidecar: Path | None = None
    sidecar_hash: str | None = None
    cues: list[dict[str, Any]] | None = None


def _contained_file(root: Path, relative: Path, label: str) -> Path:
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DependencyError(f"{label} is missing or escapes its game root: {path}") from exc
    if not resolved.is_file():
        raise DependencyError(f"{label} is not a file: {resolved}")
    return resolved


def _load_core(core: Path, label: str) -> tuple[zipfile.ZipFile, dict[str, Any], dict[str, Any], list[str]]:
    try:
        zf = zipfile.ZipFile(core, "r")
        names = _zip_names(zf, label)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DependencyError(f"cannot open {label}: {exc}") from exc
    try:
        clips_raw = _read_member(zf, CLIPS_MEMBER, label)
        clips_doc = parse_json(clips_raw or b"", CLIPS_MEMBER)
        loc_raw = _read_member(zf, CINEMATIC_MEMBER, label, required=False)
        loc_doc = parse_json(loc_raw, CINEMATIC_MEMBER) if loc_raw is not None else None
        return zf, clips_doc, loc_doc, names
    except Exception:
        zf.close()
        raise


def _validate_root(game_root: Path, *, target: bool) -> tuple[Path, Path]:
    try:
        root = game_root.resolve(strict=True)
    except OSError as exc:
        raise DependencyError(f"game root does not exist: {game_root}") from exc
    normalized = str(root).replace("\\", "/").lower()
    if target and "steamapps/common/" in normalized:
        raise DependencyError(f"refusing to write under a Steam game install: {root}")
    core_path = root / CORE_REL
    if core_path.is_symlink() or (hasattr(core_path, "is_junction") and core_path.is_junction()):
        raise DependencyError(f"Core path may not be a symlink or junction: {core_path}")
    try:
        core = core_path.resolve(strict=True)
        core.relative_to(root)
    except (OSError, ValueError) as exc:
        raise DependencyError(f"Core path is missing or escapes game root: {core_path}") from exc
    if not core.is_file():
        raise DependencyError(f"game root has no regular {CORE_REL}: {core}")
    video = root / VIDEO_REL
    if target:
        if video.is_symlink() or (hasattr(video, "is_junction") and video.is_junction()):
            raise DependencyError(f"target video directory may not be a symlink: {video}")
        try:
            video = video.resolve(strict=video.exists())
            video.relative_to(root)
        except (OSError, ValueError) as exc:
            raise DependencyError(f"target video directory escapes game root: {video}") from exc
    return core, video


def assert_no_running_game_process() -> None:
    """Refuse all target writes while the game executable is running anywhere."""
    if os.name != "nt":
        return
    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot_fn = kernel.CreateToolhelp32Snapshot
    snapshot_fn.argtypes = (ctypes.c_ulong, ctypes.c_ulong)
    snapshot_fn.restype = ctypes.c_void_p
    first_fn = kernel.Process32FirstW
    first_fn.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    first_fn.restype = ctypes.c_int
    next_fn = kernel.Process32NextW
    next_fn.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    next_fn.restype = ctypes.c_int
    close_fn = kernel.CloseHandle
    close_fn.argtypes = (ctypes.c_void_p,)
    close_fn.restype = ctypes.c_int
    snapshot = snapshot_fn(0x00000002, 0)
    invalid = ctypes.c_void_p(-1).value
    if snapshot == invalid:
        raise DependencyError(f"cannot enumerate processes (Win32 error {ctypes.get_last_error()})")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        if not first_fn(snapshot, ctypes.byref(entry)):
            raise DependencyError(f"cannot read process list (Win32 error {ctypes.get_last_error()})")
        while True:
            if _is_running_game_row(entry.szExeFile):
                raise DependencyError("refusing target mutation while HeroesOldenEra.exe is running")
            if not next_fn(snapshot, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error != 18:  # ERROR_NO_MORE_FILES
                    raise DependencyError(f"process enumeration failed (Win32 error {error})")
                break
    finally:
        close_fn(snapshot)


def _is_running_game_row(image_name: str) -> bool:
    return image_name.casefold() == "heroesoldenera.exe"


def _process_memory_metrics() -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "unavailable", "scope": "stager process only", "reason": "Windows process counters are required"}

    class MemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        current_process = kernel.GetCurrentProcess
        current_process.restype = ctypes.c_void_p
        get_counters = psapi.GetProcessMemoryInfo
        get_counters.argtypes = (ctypes.c_void_p, ctypes.POINTER(MemoryCountersEx), ctypes.c_ulong)
        get_counters.restype = ctypes.c_int
        counters = MemoryCountersEx()
        counters.cb = ctypes.sizeof(MemoryCountersEx)
        if not get_counters(current_process(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return {
            "status": "measured",
            "scope": "stager process only; excludes the separate 7-Zip child process",
            "peakPagefileUsageBytes": counters.PeakPagefileUsage,
            "peakWorkingSetBytes": counters.PeakWorkingSetSize,
            "privateBytesAtEnd": counters.PrivateUsage,
        }
    except (AttributeError, OSError) as exc:
        return {"status": "unavailable", "reason": str(exc)}


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
    except OSError as exc:
        raise DependencyError(f"cannot resolve output layout: {exc}") from exc


def _is_steam_common_path(path: Path) -> bool:
    normalized = str(path.resolve(strict=False)).replace("\\", "/").casefold().rstrip("/")
    return normalized.endswith("/steamapps/common") or "/steamapps/common/" in normalized


def _validate_output_layout(
    *, game_root: Path, source_game_root: Path | None, work: Path, report_path: Path,
) -> None:
    target = game_root.resolve(strict=True)
    source = source_game_root.resolve(strict=True) if source_game_root is not None else None
    work_abs = work.resolve(strict=False)
    report_abs = report_path.resolve(strict=False)
    if _is_steam_common_path(work_abs) or _is_steam_common_path(report_abs):
        raise DependencyError("--work and --report may not be inside a Steam steamapps/common tree")
    if source is not None:
        try:
            source.relative_to(target)
            raise DependencyError("source and target game roots may not overlap")
        except ValueError:
            pass
        try:
            target.relative_to(source)
            raise DependencyError("source and target game roots may not overlap")
        except ValueError:
            pass
        if _is_under(source, work_abs):
            raise DependencyError(f"source game root is inside scratch work: {source}")
    for label, output in (("--work", work_abs), ("--report", report_abs)):
        if _is_under(output, target):
            raise DependencyError(f"{label} may not be inside target game root: {output}")
        if source is not None and _is_under(output, source):
            raise DependencyError(f"{label} may not be inside prepared source game root: {output}")
    if not _is_under(report_abs, work_abs) or report_abs == work_abs:
        raise DependencyError("--report must be a file path inside --work")


def _plan_source_closure(
    source_root: Path,
    target_root: Path,
    keys: list[str],
    source_clips_doc: Any,
    target_clips_doc: Any,
    source_loc_doc: Any,
    target_loc_doc: Any,
) -> tuple[list[ClipDependency], dict[str, Any], dict[str, Any] | None, dict[str, str]]:
    source_rows, source_by_key, _ = _clip_rows(source_clips_doc, f"source {CLIPS_MEMBER}")
    target_rows, target_by_key, target_shape = _clip_rows(target_clips_doc, f"target {CLIPS_MEMBER}")
    del source_rows
    source_loc_maps: tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]] | None] | None = None
    if source_loc_doc is not None:
        _, _, source_tokens, source_array = _loc_rows(source_loc_doc, f"source {CINEMATIC_MEMBER}")
        source_loc_maps = (source_tokens, source_array)
    if target_loc_doc is not None:
        _loc_rows(target_loc_doc, f"target {CINEMATIC_MEMBER}")

    clips: list[ClipDependency] = []
    selected_sids: dict[str, str] = {}
    required_sources: dict[str, str] = {}
    for key in keys:
        if key not in source_by_key:
            raise DependencyError(f"source {CLIPS_MEMBER} has no row for PlayVideo key {key!r}")
        row = source_by_key[key]
        if key in target_by_key and target_by_key[key] != row:
            raise DependencyError(f"target {CLIPS_MEMBER} has conflicting selected row {key!r}")
        value = row["val"]
        name = _safe_basename(value["name"], f"source row {key!r} name")
        subtitles = value["haveSubtitles"]
        video = _contained_file(source_root, VIDEO_REL / name, f"source video for {key}")
        video_hash = sha256_file(video)
        dependency = ClipDependency(key, row, name, subtitles, video, video_hash)
        required_sources[name] = video_hash
        if subtitles:
            sidecar_name = name + ".json"
            sidecar = _contained_file(source_root, VIDEO_REL / sidecar_name, f"subtitle sidecar for {key}")
            sidecar_hash = sha256_file(sidecar)
            cues, sids = _parse_sidecar(sidecar.read_bytes(), str(sidecar))
            if source_loc_maps is None:
                raise DependencyError(f"source {CINEMATIC_MEMBER} is missing for subtitled clip {key!r}")
            for sid in sids:
                token = source_loc_maps[0].get(sid)
                if token is None:
                    raise DependencyError(f"source English cinematic token {sid!r} is missing from tokens")
                array_row = source_loc_maps[1].get(sid) if source_loc_maps[1] is not None else None
                if array_row is not None and token["text"] != array_row["text"]:
                    raise DependencyError(f"source English cinematic token {sid!r} disagrees between tokens and array")
                prior = selected_sids.get(sid)
                if prior is not None and prior != token["text"]:
                    raise DependencyError(f"selected source clips disagree on English SID {sid!r}")
                selected_sids[sid] = token["text"]
            dependency.sidecar = sidecar
            dependency.sidecar_hash = sidecar_hash
            dependency.cues = cues
            required_sources[sidecar_name] = sidecar_hash
        clips.append(dependency)

    updated_clips_doc = json.loads(json.dumps(target_clips_doc))
    updated_rows, updated_by_key, updated_shape = _clip_rows(updated_clips_doc, f"target {CLIPS_MEMBER}")
    if updated_shape[0] != target_shape[0]:
        raise DependencyError("target clips_info array shape changed while planning")
    for clip in clips:
        if clip.key not in updated_by_key:
            updated_rows.append(clip.row)
    _set_array_rows(updated_clips_doc, updated_rows, updated_shape)

    updated_loc_doc: dict[str, Any] | None = None
    if selected_sids:
        if target_loc_doc is None:
            updated_loc_doc = {"tokens": []}
        else:
            updated_loc_doc = json.loads(json.dumps(target_loc_doc))
        tokens, array_rows, target_tokens, target_array = _loc_rows(updated_loc_doc, f"target {CINEMATIC_MEMBER}")
        for sid, text in selected_sids.items():
            sections = [("tokens", target_tokens, tokens)]
            if target_array is not None:
                sections.append(("array", target_array, array_rows))
            for label, mapping, rows in sections:
                current = mapping.get(sid)
                if current is not None and current["text"] != text:
                    raise DependencyError(f"target English cinematic {label} has conflicting SID {sid!r}")
                if current is None:
                    rows.append({"sid": sid, "text": text})

    targets: dict[str, str] = {}
    for name, source_hash in required_sources.items():
        target = target_root / VIDEO_REL / name
        if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
            raise DependencyError(f"target video dependency may not be a symlink: {target}")
        targets[name] = source_hash
    return clips, updated_clips_doc, updated_loc_doc, targets


def _check_target_closure(game_root: Path, core: Path, hub: str | None) -> dict[str, Any]:
    with zipfile.ZipFile(core, "r") as zf:
        _zip_names(zf, "target Core.zip")
        hubs = _story_hubs(zf, hub)
        keys = _play_video_keys(hubs)
        clips_raw = _read_member(zf, CLIPS_MEMBER, "target Core.zip")
        clips_doc = parse_json(clips_raw or b"", CLIPS_MEMBER)
        loc_raw = _read_member(zf, CINEMATIC_MEMBER, "target Core.zip", required=False)
        loc_doc = parse_json(loc_raw, CINEMATIC_MEMBER) if loc_raw is not None else None
    _, by_key, _ = _clip_rows(clips_doc, f"target {CLIPS_MEMBER}")
    if loc_doc is None:
        loc_maps = ({}, None)
    else:
        _, _, tokens, array = _loc_rows(loc_doc, f"target {CINEMATIC_MEMBER}")
        loc_maps = (tokens, array)
    clips: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for key in keys:
        row = by_key.get(key)
        if row is None:
            raise DependencyError(f"target {CLIPS_MEMBER} has no row for PlayVideo key {key!r}")
        value = row["val"]
        name = _safe_basename(value["name"], f"target row {key!r} name")
        video = _contained_file(game_root, VIDEO_REL / name, f"target video for {key}")
        hashes[name] = sha256_file(video)
        item = {"key": key, "name": name, "haveSubtitles": value["haveSubtitles"], "videoSha256": hashes[name]}
        if value["haveSubtitles"]:
            sidecar_name = name + ".json"
            sidecar = _contained_file(game_root, VIDEO_REL / sidecar_name, f"target subtitle sidecar for {key}")
            cues, sids = _parse_sidecar(sidecar.read_bytes(), str(sidecar))
            for sid in sids:
                left = loc_maps[0].get(sid)
                right = loc_maps[1].get(sid) if loc_maps[1] is not None else None
                if left is None:
                    raise DependencyError(f"target English cinematic token {sid!r} is missing from tokens")
                if right is not None and left["text"] != right["text"]:
                    raise DependencyError(f"target English cinematic token {sid!r} disagrees between tokens and array")
            item["sidecarSha256"] = sha256_file(sidecar)
            item["subtitleCueCount"] = len(cues)
        clips.append(item)
    return {"selectedCampaigns": sorted(hubs), "clips": clips}


def _merge_core_candidates(
    *,
    target_core: Path,
    source_core: Path,
    keys: list[str],
    source_root: Path,
    target_root: Path,
) -> tuple[list[ClipDependency], dict[str, bytes], dict[str, bytes], dict[str, str]]:
    source_zf, source_clips, source_loc, _ = _load_core(source_core, "source Core.zip")
    target_zf, target_clips, target_loc, _ = _load_core(target_core, "target Core.zip")
    try:
        clips, merged_clips, merged_loc, file_hashes = _plan_source_closure(
            source_root, target_root, keys, source_clips, target_clips, source_loc, target_loc,
        )
        before_clips = _read_member(target_zf, CLIPS_MEMBER, "target Core.zip") or b""
        after_clips = encode_json(merged_clips)
        members_before_after = {CLIPS_MEMBER: (before_clips, after_clips, merged_clips != target_clips)}
        if merged_loc is not None:
            before_loc = _read_member(target_zf, CINEMATIC_MEMBER, "target Core.zip", required=False)
            after_loc = encode_json(merged_loc)
            if before_loc is None or before_loc != after_loc:
                members_before_after[CINEMATIC_MEMBER] = (before_loc or b"", after_loc, True)
        changed = {name: after for name, (before, after, semantic_change) in members_before_after.items()
                   if semantic_change and before != after}
        return clips, changed, {name: before for name, (before, _, _) in members_before_after.items()}, file_hashes
    finally:
        source_zf.close()
        target_zf.close()


def _target_file_hash(root: Path, name: str) -> str | None:
    target = root / VIDEO_REL / name
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise DependencyError(f"target dependency may not be a symlink: {target}")
    if not target.exists():
        return None
    if not target.is_file():
        raise DependencyError(f"target dependency is not a regular file: {target}")
    return sha256_file(target)


def _seven_zip_update(executable: Path, candidate: Path, stage_root: Path, members: list[str]) -> None:
    if not executable.is_file():
        raise DependencyError(f"--seven-zip does not exist: {executable}")
    try:
        result = subprocess.run(
            [str(executable), "u", str(candidate), *members], cwd=stage_root,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DependencyError(f"7-Zip update failed to run: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stdout + "\n" + result.stderr).splitlines()[-8:]
        raise DependencyError(f"7-Zip update failed ({result.returncode}): {' | '.join(tail)}")


def _read_candidate_member(core: Path, member: str) -> bytes:
    try:
        with zipfile.ZipFile(core, "r") as zf:
            _zip_names(zf, "candidate Core.zip")
            return zf.read(member)
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DependencyError(f"candidate Core.zip cannot read {member}: {exc}") from exc


def stage_campaign_video_dependencies(
    *,
    game_root: Path,
    work: Path,
    report_path: Path,
    source_game_root: Path | None = None,
    hub: str | None = None,
    check_only: bool = False,
    seven_zip: Path | None = None,
) -> dict[str, Any]:
    _validate_output_layout(
        game_root=game_root, source_game_root=source_game_root, work=work, report_path=report_path,
    )
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "planning",
        "checkOnly": check_only,
        "gameRoot": str(game_root),
        "hub": hub,
        "changedMembers": [],
        "changedFiles": [],
    }
    candidate: Path | None = None
    mutated_paths: list[str] = []
    try:
        target_core, target_video = _validate_root(game_root, target=True)
        if check_only:
            checked = _check_target_closure(game_root.resolve(strict=True), target_core, hub)
            report.update(checked)
            report["coreSha256"] = sha256_file(target_core)
            report["status"] = "checked"
            return report

        if source_game_root is None:
            raise DependencyError("--source-game-root is required unless --check-only is set")
        source_core, source_video = _validate_root(source_game_root, target=False)
        with zipfile.ZipFile(target_core, "r") as target_zf:
            hubs = _story_hubs(target_zf, hub)
            keys = _play_video_keys(hubs)
        report["selectedCampaigns"] = sorted(hubs)
        report["clipKeys"] = keys
        original_core_hash = sha256_file(target_core)
        report["coreSha256Before"] = original_core_hash
        report["sourceCoreSha256"] = sha256_file(source_core)

        clips, changed_member_bytes, _member_before, required_hashes = _merge_core_candidates(
            target_core=target_core, source_core=source_core, keys=keys,
            source_root=source_game_root.resolve(strict=True), target_root=game_root.resolve(strict=True),
        )
        report["clips"] = [
            {
                "key": clip.key, "name": clip.name, "haveSubtitles": clip.subtitles,
                "sourceRowSha256": sha256_bytes(encode_json(clip.row)),
                "sourceVideoSha256": clip.video_hash,
                **({"sourceSidecarSha256": clip.sidecar_hash, "subtitleCueCount": len(clip.cues or [])}
                   if clip.subtitles else {}),
            }
            for clip in clips
        ]
        # Prepare every external file and archive member before touching the target.
        run_work = work.resolve() / f"campaign_video_dependencies_{uuid.uuid4().hex}"
        stage_root = run_work / "members"
        backup_root = run_work / "backups"
        stage_root.mkdir(parents=True, exist_ok=False)
        report["workRun"] = str(run_work)
        staged_files: dict[str, Path] = {}
        for relative, expected_hash in sorted(required_hashes.items()):
            source = source_video / relative
            if not source.is_file() or source.is_symlink() or sha256_file(source) != expected_hash:
                raise DependencyError(f"prepared source dependency changed during planning: {source}")
            staged = run_work / "files" / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)
            if sha256_file(staged) != expected_hash:
                raise DependencyError(f"staged dependency hash mismatch: {staged}")
            staged_files[relative] = staged

        changed_files: list[dict[str, Any]] = []
        for relative, staged in staged_files.items():
            old_hash = _target_file_hash(game_root.resolve(strict=True), relative)
            new_hash = required_hashes[relative]
            changed_files.append({
                "path": str((target_video / relative)), "relativePath": str(VIDEO_REL / relative).replace("\\", "/"),
                "beforeSha256": old_hash, "afterSha256": new_hash, "changed": old_hash != new_hash,
                "stagePath": str(staged),
            })
        report["files"] = changed_files
        report["changedFiles"] = [row["relativePath"] for row in changed_files if row["changed"]]
        changed_member_names = sorted(changed_member_bytes)
        report["changedMembers"] = changed_member_names

        staged_members: dict[str, Path] = {}
        for member, data in changed_member_bytes.items():
            member_path = stage_root.joinpath(*member.split("/"))
            member_path.parent.mkdir(parents=True, exist_ok=True)
            member_path.write_bytes(data)
            staged_members[member] = member_path

        if changed_member_names:
            if seven_zip is None:
                raise DependencyError("--seven-zip is required because Core.zip members need updating")
            if not seven_zip.is_file():
                raise DependencyError(f"--seven-zip does not exist: {seven_zip}")
            candidate = run_work / f"Core.campaign_video_{uuid.uuid4().hex}.zip"
            shutil.copy2(target_core, candidate)
            _seven_zip_update(seven_zip, candidate, stage_root, changed_member_names)
            with zipfile.ZipFile(target_core, "r") as original_zf, zipfile.ZipFile(candidate, "r") as candidate_zf:
                original_names = _zip_names(original_zf, "target Core.zip")
                candidate_names = _zip_names(candidate_zf, "candidate Core.zip")
                expected_names = set(original_names)
                if CINEMATIC_MEMBER not in expected_names and CINEMATIC_MEMBER in changed_member_names:
                    expected_names.add(CINEMATIC_MEMBER)
                if set(candidate_names) != expected_names:
                    raise DependencyError("candidate Core.zip member set changed during update")
            for member, expected in staged_members.items():
                if _read_candidate_member(candidate, member) != expected.read_bytes():
                    raise DependencyError(f"candidate Core.zip readback mismatch for {member}")
            # Verify selected rows and referenced SID closure on the updated archive.
            with zipfile.ZipFile(candidate, "r") as zf:
                candidate_hubs = _story_hubs(zf, hub)
                candidate_keys = _play_video_keys(candidate_hubs)
                candidate_clips = parse_json(zf.read(CLIPS_MEMBER), CLIPS_MEMBER)
                _, candidate_by_key, _ = _clip_rows(candidate_clips, f"candidate {CLIPS_MEMBER}")
                source_zf, source_clips_doc, source_loc_doc, _ = _load_core(source_core, "source Core.zip")
                try:
                    _, source_by_key, _ = _clip_rows(source_clips_doc, f"source {CLIPS_MEMBER}")
                    for key in candidate_keys:
                        if key not in candidate_by_key or candidate_by_key[key] != source_by_key[key]:
                            raise DependencyError(f"candidate Core.zip selected clip row readback failed for {key!r}")
                    if any(clip.cues for clip in clips):
                        candidate_loc = parse_json(zf.read(CINEMATIC_MEMBER), CINEMATIC_MEMBER)
                        _, candidate_array, tokens, array = _loc_rows(candidate_loc, f"candidate {CINEMATIC_MEMBER}")
                        _, _, source_tokens, source_array = _loc_rows(source_loc_doc, f"source {CINEMATIC_MEMBER}")
                        for clip in clips:
                            if clip.cues:
                                for cue in clip.cues:
                                    sid = cue["sid"]
                                    source_array_text = source_array[sid]["text"] if source_array is not None and sid in source_array else None
                                    candidate_array_text = array[sid]["text"] if candidate_array is not None and sid in array else None
                                    if sid not in tokens or tokens[sid]["text"] != source_tokens[sid]["text"]:
                                        raise DependencyError(f"candidate English SID readback failed for {sid!r}")
                                    if source_array_text is not None and source_array_text != source_tokens[sid]["text"]:
                                        raise DependencyError(f"source English SID array mismatch for {sid!r}")
                                    if candidate_array_text is not None and candidate_array_text != source_tokens[sid]["text"]:
                                        raise DependencyError(f"candidate English SID array readback failed for {sid!r}")
                finally:
                    source_zf.close()
            if candidate_keys != keys:
                raise DependencyError("candidate StoryHub PlayVideo closure changed during Core update")
            report["candidateCoreSha256"] = sha256_file(candidate)
            report["candidateCoreMemberCount"] = len(candidate_names)
        else:
            report["candidateCoreSha256"] = original_core_hash

        # Verify all staged media against the candidate registry and subtitle closure.
        for clip in clips:
            if not clip.video.is_file() or sha256_file(clip.video) != clip.video_hash:
                raise DependencyError(f"prepared source video changed before delivery: {clip.video}")
            if clip.sidecar is not None and (not clip.sidecar.is_file() or sha256_file(clip.sidecar) != clip.sidecar_hash):
                raise DependencyError(f"prepared source subtitle sidecar changed before delivery: {clip.sidecar}")

        files_to_change = [row for row in changed_files if row["changed"]]
        core_will_change = bool(changed_member_names)
        if not files_to_change and not core_will_change:
            report["coreSha256After"] = original_core_hash
            report["targetClosure"] = _check_target_closure(game_root.resolve(strict=True), target_core, hub)
            report["status"] = "unchanged"
            return report

        if sha256_file(source_core) != report["sourceCoreSha256"]:
            raise DependencyError("prepared source Core.zip changed after planning")
        for row in files_to_change:
            observed = _target_file_hash(game_root.resolve(strict=True), Path(row["relativePath"]).relative_to(VIDEO_REL).as_posix())
            if observed != row["beforeSha256"]:
                raise DependencyError(f"target dependency changed after planning: {row['relativePath']}")

        run_work.mkdir(parents=True, exist_ok=True)
        backup_root.mkdir(parents=True, exist_ok=True)
        if core_will_change:
            backup_core = backup_root / "Core.zip"
            shutil.copy2(target_core, backup_core)
            report["coreBackup"] = str(backup_core)
        for row in files_to_change:
            target = Path(row["path"])
            if target.exists():
                relative = Path(row["relativePath"])
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                row["backup"] = str(backup)
        if os.name == "nt":
            assert_no_running_game_process()

        if files_to_change and not target_video.exists():
            if os.name == "nt":
                assert_no_running_game_process()
            target_video.mkdir(parents=True, exist_ok=False)
            mutated_paths.append(str(target_video))
        for row in files_to_change:
            if os.name == "nt":
                assert_no_running_game_process()
            relative = Path(row["relativePath"]).relative_to(VIDEO_REL)
            target = target_video / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                shutil.copy2(staged_files[relative.as_posix()], temp)
                if sha256_file(temp) != row["afterSha256"]:
                    raise DependencyError(f"target temporary copy hash mismatch: {temp}")
                if os.name == "nt":
                    assert_no_running_game_process()
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            mutated_paths.append(str(target))
        if core_will_change:
            if candidate is None or not candidate.is_file():
                raise DependencyError("candidate Core.zip disappeared before atomic replacement")
            if sha256_file(target_core) != original_core_hash:
                raise DependencyError("target Core.zip changed after planning; refusing to replace it")
            if os.name == "nt":
                assert_no_running_game_process()
            target_candidate = target_core.with_name(f".Core.campaign_video_{uuid.uuid4().hex}.zip")
            try:
                shutil.copy2(candidate, target_candidate)
                if sha256_file(target_candidate) != sha256_file(candidate):
                    raise DependencyError("same-volume Core candidate copy hash mismatch")
                if os.name == "nt":
                    assert_no_running_game_process()
                os.replace(target_candidate, target_core)
                candidate = None
            finally:
                if target_candidate.exists():
                    target_candidate.unlink()
            mutated_paths.append(str(target_core))
        report["coreSha256After"] = sha256_file(target_core)
        report["targetClosure"] = _check_target_closure(game_root.resolve(strict=True), target_core, hub)
        report["status"] = "staged"
        return report
    except Exception as exc:
        report["status"] = "failed" if not mutated_paths else "partial_failure"
        report["error"] = str(exc)
        if mutated_paths:
            report["mutatedPaths"] = mutated_paths
        raise
    finally:
        report["elapsedSec"] = round(time.perf_counter() - started, 3)
        report["processMemory"] = _process_memory_metrics()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-game-root", type=Path, help="Read-only game root containing prepared source Core/video.")
    parser.add_argument("--game-root", type=Path, required=True, help="Explicit scratch/current-version game root to update.")
    parser.add_argument("--hub", help="Exact campaigns/<folder>/StoryHub folder; limits planning to one campaign.")
    parser.add_argument("--work", type=Path, required=True, help="Scratch directory for staged files and backups.")
    parser.add_argument("--report", type=Path, required=True, help="Explicit JSON report path.")
    parser.add_argument("--seven-zip", type=Path, help="Explicit 7z.exe used only when Core JSON members need updating.")
    parser.add_argument("--check-only", action="store_true", help="Verify target Core/media/subtitle closure without source access or writes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = stage_campaign_video_dependencies(
            source_game_root=args.source_game_root, game_root=args.game_root, hub=args.hub,
            work=args.work, report_path=args.report, check_only=args.check_only, seven_zip=args.seven_zip,
        )
    except Exception as exc:
        print(f"campaign video dependency staging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({key: report.get(key) for key in ("status", "selectedCampaigns", "clipKeys", "changedMembers", "changedFiles", "elapsedSec")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
