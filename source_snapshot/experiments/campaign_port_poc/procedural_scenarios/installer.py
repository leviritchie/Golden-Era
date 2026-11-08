"""Transactional installer for validated procedural scenario bundles."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .bundle import verify_source_artifacts
from .emitter import canonical_json_bytes, sha256_bytes
from .game_context import CORE_REL, MAPS_REL
from .preflight import ProceduralPreflightError, run_preflight
from .validator import validate_bundle


STORY_MAPS_REL = MAPS_REL / "Story_maps"
STATE_REL = (
    Path("HeroesOldenEra_Data")
    / "StreamingAssets"
    / ".procedural_scenarios"
)


class InstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallResult:
    map_sid: str
    game_root: Path
    map_path: Path
    sidecar_path: Path
    core_path: Path
    installed_hashes: dict[str, str]
    preflight_checks: tuple[str, ...]


@dataclass(frozen=True)
class UninstallResult:
    map_sid: str
    game_root: Path
    restored: tuple[str, ...]


PreflightRunner = Callable[[Path, Path, str], Sequence[str]]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value, pretty=True))


def _path_target(document: Any, path: Sequence[str | int]) -> tuple[Any, str | int]:
    if not path:
        raise InstallationError("Core delta path may not be empty for this operation")
    current = document
    for segment in path[:-1]:
        if isinstance(segment, int):
            if not isinstance(current, list) or not 0 <= segment < len(current):
                raise InstallationError(f"Core delta list path does not resolve at {segment}")
            current = current[segment]
        else:
            if not isinstance(current, dict) or segment not in current:
                raise InstallationError(f"Core delta object path does not resolve at {segment!r}")
            current = current[segment]
    return current, path[-1]


def _read_path(document: Any, path: Sequence[str | int]) -> Any:
    current = document
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(current, list) or not 0 <= segment < len(current):
                raise InstallationError(f"Core delta list path does not resolve at {segment}")
            current = current[segment]
        else:
            if not isinstance(current, dict) or segment not in current:
                raise InstallationError(f"Core delta object path does not resolve at {segment!r}")
            current = current[segment]
    return current


def _merge_no_conflict(target: dict[str, Any], incoming: Mapping[str, Any], *, path: str) -> None:
    for key, value in incoming.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        current = target[key]
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge_no_conflict(current, value, path=f"{path}.{key}")
        elif current != value:
            raise InstallationError(
                f"merge_object conflict at {path}.{key}; use replace_path explicitly"
            )


def apply_core_delta_document(
    source_core: Path,
    delta_document: Mapping[str, Any],
    destination_core: Path,
) -> tuple[str, ...]:
    operations = delta_document.get("operations")
    if not isinstance(operations, list) or not operations:
        raise InstallationError("Core delta document has no operations")
    by_member: dict[str, list[dict[str, Any]]] = {}
    for row in operations:
        if not isinstance(row, dict):
            raise InstallationError("Core delta operation must be an object")
        member = str(row.get("member") or "")
        if not member:
            raise InstallationError("Core delta operation lacks member")
        by_member.setdefault(member, []).append(row)
    with zipfile.ZipFile(source_core, "r") as source:
        source_infos = {info.filename: info for info in source.infolist()}
        source_payloads = {
            info.filename: source.read(info.filename) for info in source.infolist()
        }
    updated_payloads: dict[str, bytes] = {}
    for member, rows in sorted(by_member.items()):
        member_exists = member in source_payloads
        create_rows = [row for row in rows if row.get("operation") == "create_json_member"]
        if not member_exists:
            if len(create_rows) != 1 or len(rows) != 1:
                raise InstallationError(
                    f"missing Core member {member} requires exactly one create_json_member operation"
                )
            create_row = create_rows[0]
            if create_row.get("path", []) != []:
                raise InstallationError("create_json_member path must be empty")
            value = create_row.get("value")
            if not isinstance(value, (Mapping, list)):
                raise InstallationError("create_json_member requires object/list value")
            document = copy.deepcopy(value)
        else:
            try:
                document = json.loads(source_payloads[member].decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InstallationError(f"Core member is not valid JSON: {member}") from exc
        for row in rows:
            operation = row.get("operation")
            path = row.get("path", [])
            if not isinstance(path, list):
                raise InstallationError("Core delta path must be a list")
            if operation == "create_json_member":
                value = row.get("value")
                if path or not isinstance(value, (Mapping, list)):
                    raise InstallationError(
                        "create_json_member requires empty path and object/list value"
                    )
                if member_exists and document != value:
                    raise InstallationError(
                        f"create_json_member conflicts with existing Core member: {member}"
                    )
            elif operation == "append_unique":
                target = _read_path(document, path)
                values = row.get("values")
                if not isinstance(target, list) or not isinstance(values, list):
                    raise InstallationError("append_unique requires list target and values")
                for value in values:
                    if value not in target:
                        target.append(copy.deepcopy(value))
            elif operation == "merge_object":
                target = _read_path(document, path) if path else document
                value = row.get("value")
                if not isinstance(target, dict) or not isinstance(value, Mapping):
                    raise InstallationError("merge_object requires object target and value")
                _merge_no_conflict(target, value, path=member)
            elif operation == "replace_path":
                parent, key = _path_target(document, path)
                if isinstance(key, int):
                    if not isinstance(parent, list) or not 0 <= key < len(parent):
                        raise InstallationError("replace_path list target does not resolve")
                    parent[key] = copy.deepcopy(row.get("value"))
                else:
                    if not isinstance(parent, dict) or key not in parent:
                        raise InstallationError("replace_path object target does not resolve")
                    parent[key] = copy.deepcopy(row.get("value"))
            elif operation == "upsert_array":
                target = _read_path(document, path)
                key = str(row.get("key") or "")
                incoming = row.get("rows")
                if not isinstance(target, list) or not key or not isinstance(incoming, list):
                    raise InstallationError("upsert_array requires list target, key, and rows")
                positions: dict[Any, int] = {}
                for index, item in enumerate(target):
                    if not isinstance(item, dict) or key not in item:
                        raise InstallationError(
                            f"upsert_array target row lacks key {key!r} in {member}"
                        )
                    item_key = item[key]
                    if item_key in positions:
                        raise InstallationError(
                            f"upsert_array target has duplicate {key}={item_key!r}"
                        )
                    positions[item_key] = index
                for item in incoming:
                    if not isinstance(item, dict) or key not in item:
                        raise InstallationError(f"upsert_array input row lacks key {key!r}")
                    item_key = item[key]
                    if item_key in positions:
                        target[positions[item_key]] = copy.deepcopy(item)
                    else:
                        positions[item_key] = len(target)
                        target.append(copy.deepcopy(item))
            else:
                raise InstallationError(f"unsupported Core delta operation {operation!r}")
        updated_payloads[member] = canonical_json_bytes(document, pretty=True)

    destination_core.parent.mkdir(parents=True, exist_ok=True)
    all_names = sorted(set(source_payloads) | set(updated_payloads))
    with zipfile.ZipFile(
        destination_core,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as target:
        for name in all_names:
            original = source_infos.get(name)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            if original is not None:
                info.external_attr = original.external_attr
                info.create_system = original.create_system
            payload = updated_payloads[name] if name in updated_payloads else source_payloads[name]
            target.writestr(info, payload)
    return tuple(sorted(updated_payloads))

def run_map_load_preflight(
    candidate_core: Path,
    candidate_map: Path,
    map_sid: str,
) -> tuple[str, ...]:
    try:
        return run_preflight(candidate_core, candidate_map, map_sid)
    except (OSError, ValueError, zipfile.BadZipFile, ProceduralPreflightError) as exc:
        raise InstallationError(str(exc)) from exc


def _state_document(state_root: Path) -> dict[str, Any]:
    state_path = state_root / "state.json"
    if not state_path.exists():
        return {"schema": "olden.procedural-installer-state.v1", "installOrder": []}
    value = _read_json(state_path)
    if (
        not isinstance(value, dict)
        or value.get("schema") != "olden.procedural-installer-state.v1"
        or not isinstance(value.get("installOrder"), list)
    ):
        raise InstallationError(f"invalid installer state: {state_path}")
    return value


def _assert_game_root(game_root: Path) -> tuple[Path, Path]:
    if not game_root.is_absolute():
        raise InstallationError("Golden Era root must be an explicit absolute path")
    maps_root = game_root / MAPS_REL
    core_path = game_root / CORE_REL
    if not maps_root.is_dir() or not core_path.is_file():
        raise InstallationError(
            f"not a Golden Era root with maps and Core.zip: {game_root}"
        )
    return maps_root, core_path


def _assert_no_installed_drift(record: Mapping[str, Any], game_root: Path) -> None:
    expected = record.get("installedHashes")
    originals = record.get("originals")
    if not isinstance(expected, dict) or not isinstance(originals, dict):
        raise InstallationError("install record lacks installed hash inventory")
    for label in ("map", "sidecar", "core"):
        row = originals.get(label)
        if not isinstance(row, dict) or not row.get("path"):
            raise InstallationError(f"install record lacks {label} destination")
        destination = game_root / Path(str(row["path"]))
        if not destination.is_file():
            raise InstallationError(f"installed {label} is missing: {destination}")
        actual = sha256_bytes(destination.read_bytes())
        if actual != expected.get(label):
            raise InstallationError(
                f"installed {label} changed outside the procedural installer"
            )

def _expected_core_source_hash(manifest: Mapping[str, Any]) -> str:
    source_hashes = manifest.get("sourceHashes")
    provenance = manifest.get("provenance")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise InstallationError("bundle manifest lacks sourceHashes")

    for legacy_key in source_hashes:
        normalized = str(legacy_key).replace("\\", "/")
        if normalized != "core" and Path(normalized).name.lower() == "core.zip":
            raise InstallationError(
                "bundle sourceHashes uses a legacy path-based Core identity; "
                "the canonical logical key is 'core'"
            )
    if "core" not in source_hashes:
        raise InstallationError(
            "bundle sourceHashes must identify the effective Core with logical key 'core'"
        )

    provenance_hashes: list[tuple[str, Any]] = []
    if isinstance(provenance, Mapping):
        for spelling in ("sourceHashes", "source_hashes"):
            if spelling in provenance:
                provenance_hashes.append((spelling, provenance[spelling]))
    for spelling, hashes in provenance_hashes:
        if not isinstance(hashes, Mapping) or dict(hashes) != dict(source_hashes):
            raise InstallationError(
                "bundle manifest sourceHashes differ from "
                f"provenance.{spelling}"
            )

    expected = str(source_hashes["core"])
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise InstallationError("bundle source Core.zip hash is not lowercase sha256")
    return expected


def _assert_bundled_source_artifacts(
    manifest: Mapping[str, Any],
    bundle_root: Path,
) -> tuple[str, ...]:
    try:
        return verify_source_artifacts(manifest, bundle_root)
    except (OSError, TypeError, ValueError) as exc:
        raise InstallationError(
            f"bundle non-Core source evidence is invalid: {exc}"
        ) from exc

def _assert_core_source_contract(
    manifest: Mapping[str, Any],
    active_core: Path,
) -> None:
    expected = _expected_core_source_hash(manifest)
    actual = sha256_bytes(active_core.read_bytes())
    if actual != expected:
        raise InstallationError(
            "active effective Core.zip does not match the Core used to generate "
            f"this bundle (expected {expected}, found {actual})"
        )


@contextmanager
def _installer_lock(state_root: Path):
    state_root.mkdir(parents=True, exist_ok=True)
    lock_root = state_root / ".installer.lock"
    try:
        lock_root.mkdir()
    except FileExistsError as exc:
        raise InstallationError(
            f"another procedural installer operation holds {lock_root}; "
            "a lock left by a terminated process must be inspected and removed manually"
        ) from exc
    try:
        _write_json(
            lock_root / "owner.json",
            {"schema": "olden.procedural-installer-lock.v1", "pid": os.getpid()},
        )
        yield
    finally:
        shutil.rmtree(lock_root, ignore_errors=False)


class _FileTransaction:
    def __init__(self, rollback_root: Path):
        self.rollback_root = rollback_root
        self.rollback_root.mkdir(parents=True, exist_ok=False)
        self._entries: list[tuple[Path, Path | None, bool]] = []
        self._created_directories: set[Path] = set()
        self._committed = False

    def _ensure_parent(self, destination: Path) -> None:
        missing: list[Path] = []
        current = destination.parent
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir()
        self._created_directories.update(missing)

    def _capture(self, destination: Path) -> tuple[Path | None, bool]:
        if not destination.exists():
            return None, False
        backup = self.rollback_root / f"{len(self._entries):04d}"
        is_directory = destination.is_dir()
        if is_directory:
            shutil.copytree(destination, backup)
        else:
            shutil.copy2(destination, backup)
        return backup, is_directory

    def replace_file(self, candidate: Path, destination: Path) -> None:
        if not candidate.is_file():
            raise InstallationError(f"replacement candidate is missing: {candidate}")
        backup, is_directory = self._capture(destination)
        if is_directory:
            raise InstallationError(
                f"cannot replace directory with file: {destination}"
            )
        self._ensure_parent(destination)
        pending = destination.with_name(
            f".{destination.name}.procedural_pending_{uuid.uuid4().hex}"
        )
        try:
            shutil.copy2(candidate, pending)
            os.replace(pending, destination)
        finally:
            pending.unlink(missing_ok=True)
        self._entries.append((destination, backup, False))

    def remove_path(self, destination: Path) -> None:
        backup, is_directory = self._capture(destination)
        self._entries.append((destination, backup, is_directory))
        if backup is None:
            return
        if is_directory:
            shutil.rmtree(destination)
        else:
            destination.unlink()

    def rollback(self) -> None:
        for destination, backup, is_directory in reversed(self._entries):
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink(missing_ok=True)
            if backup is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if is_directory:
                shutil.copytree(backup, destination)
            else:
                shutil.copy2(backup, destination)
        self._entries.clear()
        for directory in sorted(
            self._created_directories,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            if directory.exists():
                try:
                    directory.rmdir()
                except OSError as exc:
                    raise InstallationError(
                        "rollback left a transaction-created directory non-empty: "
                        f"{directory}"
                    ) from exc
        self._created_directories.clear()

    def commit(self) -> None:
        self._committed = True

    def __enter__(self) -> "_FileTransaction":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        return False


def install_bundle(
    bundle_root: Path,
    *,
    game_root: Path,
    preflight_runner: PreflightRunner | None = None,
) -> InstallResult:
    bundle_root = Path(bundle_root).resolve()
    game_root = Path(game_root)
    maps_root, core_path = _assert_game_root(game_root)
    report = validate_bundle(bundle_root)
    report.raise_for_errors()
    manifest = _read_json(bundle_root / "manifest.json")
    map_sid = str(manifest["mapSid"])
    source_map = bundle_root / "maps" / f"{map_sid}.map"
    source_sidecar = bundle_root / "maps" / f"{map_sid}.json"
    state_root = game_root / STATE_REL
    runner = preflight_runner or run_map_load_preflight

    with _installer_lock(state_root):
        story_root = game_root / STORY_MAPS_REL
        for name in (source_map.name, source_sidecar.name):
            if (story_root / name).exists():
                raise InstallationError(
                    "refusing duplicate procedural scenario under Story_maps: "
                    f"{story_root / name}"
                )
        state = _state_document(state_root)
        install_order = list(state["installOrder"])
        record_root = state_root / "installed" / map_sid
        existing = map_sid in install_order
        if existing and install_order[-1] != map_sid:
            raise InstallationError(
                "a procedural scenario can only be updated while it is the latest install"
            )
        if not existing and record_root.exists():
            raise InstallationError(
                f"orphan procedural install record requires inspection: {record_root}"
            )
        if existing:
            record = _read_json(record_root / "record.json")
            _assert_no_installed_drift(record, game_root)
            base_core = record_root / "original" / "Core.zip"
        else:
            record = {
                "schema": "olden.procedural-install-record.v1",
                "mapSid": map_sid,
                "originals": {},
            }
            base_core = core_path
        with tempfile.TemporaryDirectory(
            prefix="procedural_install_", dir=state_root
        ) as raw_tmp:
            temp_root = Path(raw_tmp)
            snapshot_root = temp_root / "bundle"
            shutil.copytree(bundle_root, snapshot_root)
            snapshot_report = validate_bundle(snapshot_root)
            snapshot_report.raise_for_errors()
            snapshot_manifest = _read_json(snapshot_root / "manifest.json")
            if snapshot_manifest != manifest:
                raise InstallationError(
                    "bundle manifest changed while the installer acquired its snapshot"
                )
            _assert_bundled_source_artifacts(snapshot_manifest, snapshot_root)
            source_map = snapshot_root / "maps" / f"{map_sid}.map"
            source_sidecar = snapshot_root / "maps" / f"{map_sid}.json"
            _assert_core_source_contract(snapshot_manifest, core_path)
            delta_document = _read_json(snapshot_root / "core_deltas.json")
            candidate_core = temp_root / "Core.zip"
            merged_members = apply_core_delta_document(
                base_core, delta_document, candidate_core
            )
            candidate_checks = tuple(runner(candidate_core, source_map, map_sid))
            backup_replacements: list[tuple[Path, Path]] = []
            if not existing:
                original_root = temp_root / "original"
                original_root.mkdir(parents=True, exist_ok=False)
                for label, path in (
                    ("map", maps_root / source_map.name),
                    ("sidecar", maps_root / source_sidecar.name),
                    ("core", core_path),
                ):
                    existed = path.exists()
                    backup = original_root / path.name
                    if existed:
                        shutil.copy2(path, backup)
                        backup_replacements.append(
                            (backup, record_root / "original" / path.name)
                        )
                    record["originals"][label] = {
                        "path": str(path.relative_to(game_root)),
                        "existed": existed,
                        "backup": f"original/{path.name}" if existed else None,
                    }
            record["bundleManifest"] = copy.deepcopy(snapshot_manifest)
            record["coreDelta"] = copy.deepcopy(delta_document)
            record["mergedCoreMembers"] = list(merged_members)
            record["installedHashes"] = {
                "map": sha256_bytes(source_map.read_bytes()),
                "sidecar": sha256_bytes(source_sidecar.read_bytes()),
                "core": sha256_bytes(candidate_core.read_bytes()),
            }
            record_candidate = temp_root / "record.json"
            state_candidate = temp_root / "state.json"
            _write_json(record_candidate, record)
            if not existing:
                install_order.append(map_sid)
            state["installOrder"] = install_order
            _write_json(state_candidate, state)

            with _FileTransaction(temp_root / "rollback") as transaction:
                for candidate, destination in backup_replacements:
                    transaction.replace_file(candidate, destination)
                for candidate, destination in (
                    (candidate_core, core_path),
                    (source_map, maps_root / source_map.name),
                    (source_sidecar, maps_root / source_sidecar.name),
                    (record_candidate, record_root / "record.json"),
                    (state_candidate, state_root / "state.json"),
                ):
                    transaction.replace_file(candidate, destination)

                installed = {
                    "map": sha256_bytes((maps_root / source_map.name).read_bytes()),
                    "sidecar": sha256_bytes(
                        (maps_root / source_sidecar.name).read_bytes()
                    ),
                    "core": sha256_bytes(core_path.read_bytes()),
                }
                if installed != record["installedHashes"]:
                    raise InstallationError(
                        "installed payload hash readback differs from candidates"
                    )
                installed_checks = tuple(
                    runner(core_path, maps_root / source_map.name, map_sid)
                )
                if not installed_checks or not candidate_checks:
                    raise InstallationError("map-load preflight returned no checks")
                if _read_json(record_root / "record.json") != record:
                    raise InstallationError("installed record readback differs from candidate")
                if _read_json(state_root / "state.json") != state:
                    raise InstallationError("installer state readback differs from candidate")
                transaction.commit()

        return InstallResult(
            map_sid,
            game_root,
            maps_root / source_map.name,
            maps_root / source_sidecar.name,
            core_path,
            installed,
            installed_checks,
        )


def uninstall_scenario(
    map_sid: str,
    *,
    game_root: Path,
    preflight_runner: PreflightRunner | None = None,
) -> UninstallResult:
    game_root = Path(game_root)
    _maps_root, core_path = _assert_game_root(game_root)
    state_root = game_root / STATE_REL
    runner = preflight_runner or run_map_load_preflight

    with _installer_lock(state_root):
        state = _state_document(state_root)
        install_order = list(state["installOrder"])
        if map_sid not in install_order:
            raise InstallationError(f"procedural scenario is not installed: {map_sid}")
        if install_order[-1] != map_sid:
            raise InstallationError(
                "procedural scenarios must be uninstalled in reverse install order"
            )
        record_root = state_root / "installed" / map_sid
        record = _read_json(record_root / "record.json")
        _assert_no_installed_drift(record, game_root)
        originals = record.get("originals")
        if not isinstance(originals, dict):
            raise InstallationError("install record lacks original-file inventory")

        with tempfile.TemporaryDirectory(
            prefix="procedural_uninstall_", dir=state_root
        ) as raw_tmp:
            temp_root = Path(raw_tmp)
            replacements: list[tuple[Path, Path]] = []
            removals: list[Path] = []
            restored: list[str] = []
            expected: dict[Path, str | None] = {}
            expected_relatives = {
                "core": CORE_REL,
                "map": MAPS_REL / f"{map_sid}.map",
                "sidecar": MAPS_REL / f"{map_sid}.json",
            }
            for label in ("core", "map", "sidecar"):
                row = originals.get(label)
                if not isinstance(row, dict):
                    raise InstallationError(f"install record lacks {label} original")
                expected_relative = expected_relatives[label]
                recorded_relative = Path(str(row.get("path", "")))
                if recorded_relative != expected_relative:
                    raise InstallationError(
                        f"install record {label} path differs from owned destination"
                    )
                destination = game_root / expected_relative
                if bool(row.get("existed")):
                    backup_value = row.get("backup")
                    expected_backup = Path("original") / expected_relative.name
                    if (
                        not isinstance(backup_value, str)
                        or Path(backup_value) != expected_backup
                    ):
                        raise InstallationError(
                            f"install record lacks owned {label} backup path"
                        )
                    backup = record_root / expected_backup
                    if not backup.is_file():
                        raise InstallationError(f"missing uninstall backup: {backup}")
                    replacements.append((backup, destination))
                    expected[destination] = sha256_bytes(backup.read_bytes())
                    restored.append(label)
                else:
                    removals.append(destination)
                    expected[destination] = None
            candidate_core = next(
                source for source, destination in replacements if destination == core_path
            )
            remaining = install_order[:-1]
            previous_map: Path | None = None
            if remaining:
                previous_sid = remaining[-1]
                previous_map = game_root / MAPS_REL / f"{previous_sid}.map"
                runner(candidate_core, previous_map, previous_sid)
            state["installOrder"] = remaining
            state_candidate = temp_root / "state.json"
            _write_json(state_candidate, state)

            with _FileTransaction(temp_root / "rollback") as transaction:
                for candidate, destination in replacements:
                    transaction.replace_file(candidate, destination)
                transaction.replace_file(state_candidate, state_root / "state.json")
                for destination in removals:
                    transaction.remove_path(destination)
                transaction.remove_path(record_root)

                for destination, expected_hash in expected.items():
                    if expected_hash is None:
                        if destination.exists():
                            raise InstallationError(
                                f"uninstall failed to remove {destination}"
                            )
                    elif not destination.is_file() or sha256_bytes(
                        destination.read_bytes()
                    ) != expected_hash:
                        raise InstallationError(
                            f"uninstall restored payload hash mismatch: {destination}"
                        )
                if _read_json(state_root / "state.json") != state:
                    raise InstallationError("uninstall state readback differs from candidate")
                if record_root.exists():
                    raise InstallationError("uninstall record directory was not removed")
                if remaining and previous_map is not None:
                    runner(core_path, previous_map, remaining[-1])
                transaction.commit()

        return UninstallResult(map_sid, game_root, tuple(restored))