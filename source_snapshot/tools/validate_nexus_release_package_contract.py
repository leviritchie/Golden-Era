#!/usr/bin/env python3
"""Validate the direct depot-root package intended for Nexus Mods uploads."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Mapping


SCHEMA = "homm3-nexus-depot-package/v2"
CORE_ZIP_PATH = "HeroesOldenEra_Data/StreamingAssets/Core.zip"
PLUGIN_PREFIX = "BepInEx/plugins/OfflineUnlockMod"
BEPINEX_VERSION = "6.0.0-be.755+3fab71a"
BEPINEX_SOURCE_URL = "https://builds.bepinex.dev/projects/bepinex_be/755/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755%2B3fab71a.zip"
BEPINEX_PACKAGE_SHA256 = "3616d6a67f5f595973ec4aa7bd7edaf7f799d5bb9926f7146a6dcc7b4abf478f"
BEPINEX_PACKAGE_BYTES = 34323430
BEPINEX_PACKAGE_ENTRY_COUNT = 233
BEPINEX_RUNTIME_ROOT_FILES = {
    ".doorstop_version",
    "changelog.txt",
    "doorstop_config.ini",
    "winhttp.dll",
}
BEPINEX_RUNTIME_PREFIXES = ("dotnet/", "BepInEx/core/")
PACKAGE_BOUNDARY = (
    f"BepInEx {BEPINEX_VERSION} runtime + "
    f"{CORE_ZIP_PATH} + {PLUGIN_PREFIX}"
)
PROVENANCE_FORMAT = "hommoe-golden-era-release-overlay-v1"
THIRD_PARTY_NOTICE_PATH = "THIRD_PARTY_NOTICES.txt"
THIRD_PARTY_NOTICE_REQUIRED_MARKERS = (
    "BepInEx 6.0.0-be.755+3fab71a",
    "BepInEx/core/",
    "Microsoft .NET runtime files under dotnet/",
    BEPINEX_SOURCE_URL,
    BEPINEX_PACKAGE_SHA256,
    "https://github.com/BepInEx/BepInEx",
    "https://github.com/dotnet/runtime",
    "THIRD-PARTY-NOTICES",
)
TOP_LEVEL_FILES = {"README.md", "manifest.json", "SHA256SUMS.txt", THIRD_PARTY_NOTICE_PATH}
REQUIRED_FILES = {
    "README.md",
    "manifest.json",
    "SHA256SUMS.txt",
    CORE_ZIP_PATH,
    "winhttp.dll",
    "doorstop_config.ini",
    "dotnet/coreclr.dll",
    "BepInEx/core/BepInEx.Core.dll",
    "BepInEx/core/BepInEx.Unity.IL2CPP.dll",
    THIRD_PARTY_NOTICE_PATH,
    f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll",
    f"{PLUGIN_PREFIX}/OfflineLauncherConfig.json",
}
FORBIDDEN_BASENAMES = {
    "coreclr.dll",
    "doorstop_config.ini",
    "global-metadata.dat",
    "globalgamemanagers",
    "resources.assets",
    "winhttp.dll",
}
FORBIDDEN_SCRIPT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".js",
    ".msi",
    ".ps1",
    ".psm1",
    ".scr",
    ".vbs",
}
FORBIDDEN_EXTENSIONS = {".flag", ".log", ".tmp"}
FORBIDDEN_STALE_MARKERS = (
    ".force_win_game_pending",
    ".foldercache",
    ".pre_compose_bak",
    ".pre_native_canvas_bak",
    ".broken_fp_spawn_stack_",
)
PRIVATE_PATH_MARKERS = (
    "users\\",
    "users/",
    "\\appdata\\",
    "/appdata/",
    "\\tmp\\",
    "/tmp/",
    "v:\\",
    "v:/",
    "c:\\",
    "c:/",
)
LAB_SIDECAR_RE = re.compile(
    r"^homm3_lab/[^/]+/(Generated|extracted_battle|extracted_map)/.+\.json$",
    re.IGNORECASE,
)
TOWN_REF_RE = re.compile(r"^homm3_runtime_assets/town_scene_refs/(grove|hive)/.+$", re.IGNORECASE)


class ContractError(ValueError):
    """Raised when a package violates the upload contract."""


def normalize_name(name: str) -> str:
    """Return a safe POSIX package path, rejecting traversal and absolutes."""

    if "\\" in name:
        name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:/", name):
        raise ContractError(f"absolute package path is not allowed: {name}")

    parts = name.split("/")
    if any(part == ".." for part in parts):
        raise ContractError(f"path traversal is not allowed: {name}")
    normalized_parts = [part for part in parts if part not in ("", ".")]
    if not normalized_parts:
        raise ContractError(f"empty package path is not allowed: {name}")
    return "/".join(normalized_parts)


def _forbidden_reason(name: str) -> str | None:
    lower = name.lower()
    basename = PurePosixPath(lower).name
    extension = PurePosixPath(lower).suffix

    if any(marker in lower for marker in ("live_probe", "ai_driver_bridge", "flag_hold", "log_archive")):
        return "diagnostic or development payload"
    if any(marker in lower for marker in FORBIDDEN_STALE_MARKERS):
        return "stale suffix artifact"
    if extension in FORBIDDEN_SCRIPT_EXTENSIONS:
        return "executable or script payload"
    if extension in FORBIDDEN_EXTENSIONS:
        return "runtime log/flag/temp payload"
    if basename.endswith(".pdb"):
        return "debug-symbol payload"
    if ".pdb." in basename and not basename.endswith(".pdb.dll"):
        return "debug-symbol payload"
    if extension in {".7z", ".cab", ".rar", ".zip"}:
        return "nested archive"
    if _is_allowed_bepinex_runtime_path(name):
        return None
    if basename in FORBIDDEN_BASENAMES:
        return "game-root/bootstrap payload"
    if "homm3_lab" in lower and not LAB_SIDECAR_RE.fullmatch(
        lower.removeprefix(PLUGIN_PREFIX.lower() + "/")
    ):
        return "unapproved lab payload"
    return None


def _is_allowed_plugin_path(name: str) -> bool:
    if not name.startswith(PLUGIN_PREFIX + "/"):
        return False
    relative = name[len(PLUGIN_PREFIX) + 1 :]
    lower_relative = relative.lower()
    if lower_relative.startswith("homm3_lab/"):
        return bool(LAB_SIDECAR_RE.fullmatch(relative))
    if lower_relative.startswith("homm3_runtime_assets/town_scene_refs/"):
        return bool(TOWN_REF_RE.fullmatch(relative))
    return True


def _is_allowed_bepinex_runtime_path(name: str) -> bool:
    if name in BEPINEX_RUNTIME_ROOT_FILES:
        return True
    return any(name.startswith(prefix) for prefix in BEPINEX_RUNTIME_PREFIXES)


def _validate_names(names: Iterable[str]) -> None:
    for raw_name in names:
        name = normalize_name(raw_name)
        if name in TOP_LEVEL_FILES or name == CORE_ZIP_PATH:
            continue
        reason = _forbidden_reason(name)
        if reason:
            raise ContractError(f"{reason}: {name}")
        if _is_allowed_bepinex_runtime_path(name):
            continue
        if not _is_allowed_plugin_path(name):
            raise ContractError(f"unexpected package path: {name}")


def _walk_json_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_strings(child)


def _reject_private_paths(value: object, label: str) -> None:
    for text in _walk_json_strings(value):
        lower = text.lower()
        if any(marker in lower for marker in PRIVATE_PATH_MARKERS):
            raise ContractError(f"private/local path in {label}")


def _load_json(data: bytes, label: str) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON in {label}: {exc}") from exc


def _validate_third_party_notice(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{THIRD_PARTY_NOTICE_PATH} is not UTF-8: {exc}") from exc
    missing = [marker for marker in THIRD_PARTY_NOTICE_REQUIRED_MARKERS if marker not in text]
    if missing:
        raise ContractError(f"{THIRD_PARTY_NOTICE_PATH} is missing required attribution marker: {missing[0]}")


def _validate_config(data: bytes) -> None:
    value = _load_json(data, "OfflineLauncherConfig.json")
    if not isinstance(value, dict):
        raise ContractError("OfflineLauncherConfig.json must contain an object")
    if value.get("releaseSafeProfile") is not True:
        raise ContractError("OfflineLauncherConfig.json must set releaseSafeProfile=true")
    if value.get("autoLaunchOnMenu") is True or value.get("releaseSafeAutoLaunchOnMenu") is True:
        raise ContractError("release package cannot enable automatic launch")

    diagnostic_key = re.compile("diagnostic|probe|inspector|liveprobeworkbench", re.IGNORECASE)

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str) and isinstance(child, bool) and child and diagnostic_key.search(key):
                    raise ContractError(f"diagnostic flag is enabled in config: {key}")
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    _reject_private_paths(value, "OfflineLauncherConfig.json")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def _validate_core_zip(data: bytes) -> None:
    """Check that the shipped Core is a real modded game-data archive."""

    required_members = {
        "DB/data.json",
        "DB/fractions/7_homm3_stronghold.json",
    }
    members: Dict[str, bytes] = {}
    folded_names: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                name = normalize_name(info.filename)
                if info.is_dir():
                    continue
                if _is_symlink(info):
                    raise ContractError(f"symlink member is not allowed in Core.zip: {name}")
                folded = name.casefold()
                if folded in folded_names:
                    raise ContractError(
                        f"case-insensitive duplicate Core.zip path: {folded_names[folded]} / {name}"
                    )
                folded_names[folded] = name
                members[name] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise ContractError(f"Core.zip is not a valid ZIP: {exc}") from exc
    except (OSError, RuntimeError, zipfile.LargeZipFile) as exc:
        raise ContractError(f"Core.zip could not be read: {exc}") from exc

    missing = sorted(required_members - set(members))
    if missing:
        raise ContractError(f"Core.zip is missing required member(s): {', '.join(missing)}")

    data_json = _load_json(members["DB/data.json"], "Core.zip DB/data.json")
    _reject_private_paths(data_json, "Core.zip DB/data.json")
    core_strings = {text.casefold() for text in _walk_json_strings(data_json)}
    if not any("homm3_stronghold" in text for text in core_strings):
        raise ContractError("Core.zip DB/data.json does not identify the Stronghold faction")


def _validate_manifest(data: bytes, core_data: bytes, files: Mapping[str, bytes]) -> None:
    value = _load_json(data, "manifest.json")
    if not isinstance(value, dict):
        raise ContractError("manifest.json must contain an object")
    if value.get("schema") != SCHEMA:
        raise ContractError(f"manifest.json schema must be {SCHEMA}")
    for key in (
        "packageVersion",
        "sourceCommit",
        "releaseInputSha256",
        "packageBoundary",
        "bepInExVersion",
        "bepInExSourceUrl",
        "thirdPartyNoticePath",
    ):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ContractError(f"manifest.json requires string field: {key}")
    if value["packageBoundary"] != PACKAGE_BOUNDARY:
        raise ContractError(f"manifest.json packageBoundary must be {PACKAGE_BOUNDARY}")
    if value["bepInExVersion"] != BEPINEX_VERSION:
        raise ContractError(f"manifest.json bepInExVersion must be {BEPINEX_VERSION}")
    if value["bepInExSourceUrl"] != BEPINEX_SOURCE_URL:
        raise ContractError("manifest.json bepInExSourceUrl must identify the pinned official package")
    if value["thirdPartyNoticePath"] != THIRD_PARTY_NOTICE_PATH:
        raise ContractError(f"manifest.json thirdPartyNoticePath must be {THIRD_PARTY_NOTICE_PATH}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value["sourceCommit"]):
        raise ContractError("manifest.json sourceCommit must be a 40-character Git commit")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value["releaseInputSha256"]):
        raise ContractError("manifest.json releaseInputSha256 must be a SHA-256 digest")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value.get("bepInExPackageSha256", "")):
        raise ContractError("manifest.json bepInExPackageSha256 must be a SHA-256 digest")
    if value["bepInExPackageSha256"].lower() != BEPINEX_PACKAGE_SHA256:
        raise ContractError("manifest.json bepInExPackageSha256 must match the pinned official package")
    for key in ("bepInExPackageBytes", "bepInExPackageEntryCount", "bepInExRuntimeFileCount"):
        if isinstance(value.get(key), bool) or not isinstance(value.get(key), int) or value[key] <= 0:
            raise ContractError(f"manifest.json {key} must be a positive integer")
    if value["bepInExPackageBytes"] != BEPINEX_PACKAGE_BYTES:
        raise ContractError("manifest.json bepInExPackageBytes must match the pinned official package")
    if value["bepInExPackageEntryCount"] != BEPINEX_PACKAGE_ENTRY_COUNT:
        raise ContractError("manifest.json bepInExPackageEntryCount must match the pinned official package")
    if value.get("coreZipPath") != CORE_ZIP_PATH:
        raise ContractError(f"manifest.json coreZipPath must be {CORE_ZIP_PATH}")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(value.get("coreZipSha256", ""))):
        raise ContractError("manifest.json coreZipSha256 must be a SHA-256 digest")
    if value["coreZipSha256"].lower() != hashlib.sha256(core_data).hexdigest():
        raise ContractError("manifest.json coreZipSha256 does not match Core.zip")
    if isinstance(value.get("coreZipBytes"), bool) or not isinstance(value.get("coreZipBytes"), int):
        raise ContractError("manifest.json coreZipBytes must be a positive integer")
    if value["coreZipBytes"] <= 0 or value["coreZipBytes"] != len(core_data):
        raise ContractError("manifest.json coreZipBytes does not match Core.zip")
    if value.get("coreProvenanceFormat") != PROVENANCE_FORMAT:
        raise ContractError(f"manifest.json coreProvenanceFormat must be {PROVENANCE_FORMAT}")
    if isinstance(value.get("coreProvenanceOperationCount"), bool) or not isinstance(
        value.get("coreProvenanceOperationCount"), int
    ):
        raise ContractError("manifest.json coreProvenanceOperationCount must be a positive integer")
    if value["coreProvenanceOperationCount"] <= 0:
        raise ContractError("manifest.json coreProvenanceOperationCount must be a positive integer")
    if isinstance(value.get("coreProvenanceSkippedDeletedMemberCount"), bool) or not isinstance(
        value.get("coreProvenanceSkippedDeletedMemberCount"), int
    ):
        raise ContractError("manifest.json coreProvenanceSkippedDeletedMemberCount must be a non-negative integer")
    if value["coreProvenanceSkippedDeletedMemberCount"] < 0:
        raise ContractError("manifest.json coreProvenanceSkippedDeletedMemberCount must be a non-negative integer")
    for key in ("coreProvenanceSkippedDeletedMembers", "coreProvenanceRequiredCoreTokens"):
        if not isinstance(value.get(key), list) or not all(isinstance(item, str) for item in value[key]):
            raise ContractError(f"manifest.json {key} must be a string list")
    if value["coreProvenanceSkippedDeletedMemberCount"] != len(value["coreProvenanceSkippedDeletedMembers"]):
        raise ContractError("manifest.json Core provenance deleted-member count does not match the list")
    if not any("homm3_stronghold" in token.casefold() for token in value["coreProvenanceRequiredCoreTokens"]):
        raise ContractError("manifest.json Core provenance must identify Stronghold")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(value.get("pinnedVanillaCoreZipSha256", ""))):
        raise ContractError("manifest.json pinnedVanillaCoreZipSha256 must be a SHA-256 digest")
    if isinstance(value.get("pinnedVanillaCoreZipBytes"), bool) or not isinstance(
        value.get("pinnedVanillaCoreZipBytes"), int
    ):
        raise ContractError("manifest.json pinnedVanillaCoreZipBytes must be a positive integer")
    if value["pinnedVanillaCoreZipBytes"] <= 0:
        raise ContractError("manifest.json pinnedVanillaCoreZipBytes must be a positive integer")
    for key in (
        "copiedPluginFiles",
        "scrubbedPluginDlls",
        "excludedReleaseInputFiles",
        "bepInExRuntimeFiles",
    ):
        if not isinstance(value.get(key), list):
            raise ContractError(f"manifest.json {key} must be a list")

    copied_keys: set[str] = set()
    for raw_name in value["copiedPluginFiles"]:
        if not isinstance(raw_name, str):
            raise ContractError("manifest.json copiedPluginFiles entries must be strings")
        name = normalize_name(raw_name)
        folded = name.casefold()
        if folded in copied_keys or not _is_allowed_plugin_path(name) or name not in files:
            raise ContractError(f"manifest.json copiedPluginFiles contains invalid or missing path: {name}")
        copied_keys.add(folded)
    expected_plugin_keys = {
        name.casefold() for name in files if name.startswith(PLUGIN_PREFIX + "/")
    }
    if copied_keys != expected_plugin_keys:
        raise ContractError("manifest.json copiedPluginFiles does not cover the shipped plugin files exactly")

    runtime_keys: set[str] = set()
    for raw_name in value["bepInExRuntimeFiles"]:
        if not isinstance(raw_name, str):
            raise ContractError("manifest.json bepInExRuntimeFiles entries must be strings")
        name = normalize_name(raw_name)
        folded = name.casefold()
        if (
            folded in runtime_keys
            or not _is_allowed_bepinex_runtime_path(name)
            or name not in files
        ):
            raise ContractError(f"manifest.json bepInExRuntimeFiles contains invalid or missing path: {name}")
        runtime_keys.add(folded)
    expected_runtime_keys = {
        name.casefold() for name in files if _is_allowed_bepinex_runtime_path(name)
    }
    if runtime_keys != expected_runtime_keys:
        raise ContractError("manifest.json bepInExRuntimeFiles does not cover the shipped BepInEx runtime exactly")
    if value["bepInExRuntimeFileCount"] != len(value["bepInExRuntimeFiles"]):
        raise ContractError("manifest.json bepInExRuntimeFileCount does not match the runtime file list")

    scrubbed_keys: set[str] = set()
    for raw_name in value["scrubbedPluginDlls"]:
        if not isinstance(raw_name, str):
            raise ContractError("manifest.json scrubbedPluginDlls entries must be strings")
        name = normalize_name(raw_name)
        folded = name.casefold()
        if folded in scrubbed_keys or not _is_allowed_plugin_path(name) or name not in files:
            raise ContractError(f"manifest.json scrubbedPluginDlls contains invalid or missing path: {name}")
        scrubbed_keys.add(folded)
    expected_scrubbed_keys = {
        f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll".casefold(),
        f"{PLUGIN_PREFIX}/OldenAiSim.dll".casefold(),
    }
    if scrubbed_keys != expected_scrubbed_keys:
        raise ContractError("manifest.json scrubbedPluginDlls does not identify the expected scrubbed DLLs")

    excluded_keys: set[str] = set()
    for raw_name in value["excludedReleaseInputFiles"]:
        if not isinstance(raw_name, str):
            raise ContractError("manifest.json excludedReleaseInputFiles entries must be strings")
        name = normalize_name(raw_name)
        folded = name.casefold()
        if folded in excluded_keys or not name.lower().startswith("payload/"):
            raise ContractError(f"manifest.json excludedReleaseInputFiles contains invalid path: {name}")
        excluded_keys.add(folded)
    _reject_private_paths(value, "manifest.json")


def _validate_checksums(files: Mapping[str, bytes]) -> None:
    checksum_name = "SHA256SUMS.txt"
    if checksum_name not in files:
        raise ContractError("missing SHA256SUMS.txt")
    entries: Dict[str, str] = {}
    entry_keys: Dict[str, str] = {}
    try:
        lines = files[checksum_name].decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError(f"SHA256SUMS.txt is not UTF-8: {exc}") from exc
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+(.+)", line)
        if not match:
            raise ContractError(f"invalid checksum line {line_number}")
        digest, raw_name = match.groups()
        name = normalize_name(raw_name.strip())
        folded = name.casefold()
        if name == checksum_name or folded in entry_keys:
            raise ContractError(f"duplicate or self-referential checksum entry: {name}")
        entry_keys[folded] = name
        entries[name] = digest.lower()

    expected = set(files) - {checksum_name}
    if set(entries) != expected:
        missing = sorted(expected - set(entries))
        extra = sorted(set(entries) - expected)
        raise ContractError(f"checksum coverage mismatch; missing={missing}, extra={extra}")
    for name, expected_digest in entries.items():
        actual_digest = hashlib.sha256(files[name]).hexdigest()
        if actual_digest != expected_digest:
            raise ContractError(f"checksum mismatch: {name}")


def validate_data(files: Mapping[str, bytes]) -> int:
    normalized: Dict[str, bytes] = {}
    folded_names: Dict[str, str] = {}
    for raw_name, content in files.items():
        name = normalize_name(raw_name)
        folded = name.casefold()
        if name in normalized or folded in folded_names:
            previous = folded_names.get(folded, name)
            raise ContractError(f"case-insensitive duplicate package path: {previous} / {name}")
        normalized[name] = content
        folded_names[folded] = name

    _validate_names(normalized)
    missing = sorted(REQUIRED_FILES - set(normalized))
    if missing:
        raise ContractError(f"missing required file(s): {', '.join(missing)}")
    _validate_config(normalized[f"{PLUGIN_PREFIX}/OfflineLauncherConfig.json"])
    _validate_third_party_notice(normalized[THIRD_PARTY_NOTICE_PATH])
    _validate_core_zip(normalized[CORE_ZIP_PATH])
    _validate_manifest(normalized["manifest.json"], normalized[CORE_ZIP_PATH], normalized)
    _validate_checksums(normalized)
    return len(normalized)


def validate_root(root: Path) -> int:
    if not root.is_dir():
        raise ContractError(f"package root is not a directory: {root}")
    files: Dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink():
            raise ContractError(f"symlink is not allowed in package root: {path}")
        relative = path.relative_to(root).as_posix()
        files[relative] = path.read_bytes()
    return validate_data(files)


def validate_zip(path: Path) -> int:
    if not path.is_file():
        raise ContractError(f"package ZIP does not exist: {path}")
    files: Dict[str, bytes] = {}
    folded_names: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = normalize_name(info.filename)
                if info.is_dir():
                    continue
                if _is_symlink(info):
                    raise ContractError(f"symlink is not allowed in package ZIP: {name}")
                folded = name.casefold()
                if folded in folded_names:
                    raise ContractError(
                        f"case-insensitive duplicate ZIP path: {folded_names[folded]} / {name}"
                    )
                folded_names[folded] = name
                files[name] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise ContractError(f"invalid ZIP: {exc}") from exc
    return validate_data(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path, help="staged package directory")
    source.add_argument("--zip", dest="zip_path", type=Path, help="package ZIP")
    args = parser.parse_args(argv)
    try:
        count = validate_root(args.root) if args.root else validate_zip(args.zip_path)
    except (OSError, ContractError) as exc:
        print(f"Nexus release package contract: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Nexus release package contract: PASS ({count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
