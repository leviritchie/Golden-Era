"""Reproducible procedural-scenario bundle construction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .emitter import (
    EmissionResult,
    NativeMapContainer,
    _field,
    _jsonable,
    canonical_json_bytes,
    emit_scenario,
    sha256_bytes,
)


BUNDLE_SCHEMA = "olden.procedural-scenario-bundle.v1"
CORE_DELTA_SCHEMA = "olden.core-json-deltas.v1"
ALLOWED_DELTA_OPERATIONS = {
    "append_unique",
    "merge_object",
    "replace_path",
    "upsert_array",
    "create_json_member",
}


@dataclass(frozen=True)
class BundleResult:
    root: Path
    map_sid: str
    manifest_path: Path
    emission: EmissionResult
    hashes: dict[str, str]


def _write_json(path: Path, payload: Any) -> str:
    encoded = canonical_json_bytes(payload, pretty=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return sha256_bytes(encoded)


def _safe_member(member: str) -> str:
    normalized = PurePosixPath(str(member).replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise ValueError(f"unsafe Core member path: {member!r}")
    if normalized.suffix.lower() != ".json":
        raise ValueError(f"Core delta member must be JSON: {member!r}")
    return normalized.as_posix()


def _safe_source_artifact_path(relative: str) -> str:
    normalized = PurePosixPath(str(relative).replace("\\", "/"))
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or len(normalized.parts) != 2
        or normalized.parts[0] != "sources"
        or not normalized.parts[1]
    ):
        raise ValueError(f"unsafe bundled source artifact path: {relative!r}")
    return normalized.as_posix()


def write_source_artifacts(
    output_root: Path,
    source_hashes: Mapping[str, Any],
    source_artifacts: Mapping[str, bytes] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Write content-addressed evidence for every non-Core generation source."""

    if not all(
        isinstance(key, str)
        and bool(key)
        and isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value)
        for key, value in source_hashes.items()
    ):
        raise ValueError(
            "source hashes must use non-empty string keys and lowercase sha256 values"
        )
    expected = {
        key: value for key, value in source_hashes.items() if key != "core"
    }
    provided = {} if source_artifacts is None else dict(source_artifacts)
    if set(provided) != set(expected):
        raise ValueError(
            "bundled source artifacts must match every non-Core source hash exactly; "
            f"missing={sorted(set(expected) - set(provided))}, "
            f"extra={sorted(set(provided) - set(expected))}"
        )
    bindings: dict[str, str] = {}
    file_hashes: dict[str, str] = {}
    for source_key in sorted(expected):
        expected_hash = expected[source_key]
        if not isinstance(provided[source_key], bytes):
            raise TypeError(f"source artifact {source_key!r} must be immutable bytes")
        payload = provided[source_key]
        actual_hash = sha256_bytes(payload)
        if actual_hash != expected_hash:
            raise ValueError(
                f"source artifact hash mismatch for {source_key!r}: "
                f"expected {expected_hash}, found {actual_hash}"
            )
        relative = _safe_source_artifact_path(f"sources/{expected_hash}")
        root = Path(output_root).resolve()
        path = root.joinpath(*PurePosixPath(relative).parts).resolve()
        if root not in path.parents:
            raise ValueError(f"source artifact path escapes bundle root: {relative!r}")
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(
                    f"content-addressed source artifact collision at {relative}"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        bindings[source_key] = relative
        file_hashes[relative] = expected_hash
    return bindings, file_hashes


def verify_source_artifacts(
    manifest: Mapping[str, Any],
    bundle_root: Path,
) -> tuple[str, ...]:
    """Verify self-contained evidence for every non-Core source hash."""

    source_hashes = manifest.get("sourceHashes")
    files = manifest.get("files")
    if not isinstance(source_hashes, Mapping):
        raise ValueError("bundle manifest sourceHashes must be an object")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in source_hashes.items()
    ):
        raise ValueError("bundle manifest sourceHashes entries must be strings")
    if not isinstance(files, Mapping):
        raise ValueError("bundle manifest files must be an object")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in files.items()
    ):
        raise ValueError("bundle manifest files entries must be strings")
    expected_keys = {key for key in source_hashes if key != "core"}
    bindings = manifest.get("sourceArtifacts")
    if bindings is None and not expected_keys:
        bindings = {}
    if not isinstance(bindings, Mapping):
        raise ValueError("bundle manifest sourceArtifacts must be an object")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in bindings.items()
    ):
        raise ValueError("bundle manifest sourceArtifacts entries must be strings")
    if set(bindings) != expected_keys:
        raise ValueError(
            "sourceArtifacts must bind every non-Core source hash exactly; "
            f"missing={sorted(expected_keys - set(bindings))}, "
            f"extra={sorted(set(bindings) - expected_keys)}"
        )
    verified: list[str] = []
    root = Path(bundle_root).resolve()
    for source_key in sorted(expected_keys):
        relative = bindings[source_key]
        if not isinstance(relative, str):
            raise ValueError(f"source artifact path for {source_key!r} must be a string")
        relative = _safe_source_artifact_path(relative)
        expected_hash = source_hashes[source_key]
        expected_relative = f"sources/{expected_hash}"
        if relative != expected_relative:
            raise ValueError(
                f"source artifact {source_key!r} must use content-addressed path "
                f"{expected_relative!r}"
            )
        if files.get(relative) != expected_hash:
            raise ValueError(
                f"source artifact {source_key!r} is not hash-bound in manifest files"
            )
        path = root.joinpath(*PurePosixPath(relative).parts).resolve()
        if root not in path.parents:
            raise ValueError(f"source artifact path escapes bundle root: {relative!r}")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ValueError(
                f"cannot read bundled source artifact {source_key!r}: {exc}"
            ) from exc
        actual_hash = sha256_bytes(payload)
        if actual_hash != expected_hash:
            raise ValueError(
                f"bundled source artifact hash mismatch for {source_key!r}: "
                f"expected {expected_hash}, found {actual_hash}"
            )
        verified.append(source_key)
    return tuple(verified)


def normalize_core_deltas(
    deltas: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    map_sid: str,
) -> dict[str, Any]:
    if deltas is None:
        operations: list[dict[str, Any]] = []
    elif isinstance(deltas, Mapping):
        raw = deltas.get("operations")
        if not isinstance(raw, list):
            raise ValueError("Core delta document requires an operations list")
        operations = [dict(row) for row in raw]
    else:
        operations = [dict(row) for row in deltas]
    quickstart_declared = any(
        row.get("member") == "DB/quickStart.json"
        and row.get("operation") == "append_unique"
        and map_sid in (row.get("values") or [])
        for row in operations
    )
    if not quickstart_declared:
        operations.insert(
            0,
            {
                "member": "DB/quickStart.json",
                "operation": "append_unique",
                "path": ["scenarios"],
                "values": [map_sid],
            },
        )
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(operations):
        operation = str(row.get("operation") or "")
        if operation not in ALLOWED_DELTA_OPERATIONS:
            raise ValueError(f"unsupported Core delta operation {operation!r}")
        member = _safe_member(str(row.get("member") or ""))
        path = row.get("path", [])
        if not isinstance(path, list) or not all(
            isinstance(part, (str, int)) for part in path
        ):
            raise ValueError("Core delta path must be a list of string/integer segments")
        delta_id = str(row.get("id") or f"{map_sid}:{index:04d}")
        if delta_id in seen_ids:
            raise ValueError(f"duplicate Core delta id {delta_id}")
        seen_ids.add(delta_id)
        normalized_row = {
            "id": delta_id,
            "member": member,
            "operation": operation,
            "path": list(path),
        }
        if operation == "append_unique":
            values = row.get("values")
            if not isinstance(values, list) or not values:
                raise ValueError("append_unique Core delta requires non-empty values")
            normalized_row["values"] = _jsonable(values)
        elif operation == "merge_object":
            value = row.get("value")
            if not isinstance(value, Mapping):
                raise ValueError("merge_object Core delta requires object value")
            normalized_row["value"] = _jsonable(value)
        elif operation == "replace_path":
            if "value" not in row:
                raise ValueError("replace_path Core delta requires value")
            normalized_row["value"] = _jsonable(row["value"])
        elif operation == "upsert_array":
            key = str(row.get("key") or "")
            rows = row.get("rows")
            if not key or not isinstance(rows, list) or not rows:
                raise ValueError("upsert_array Core delta requires key and rows")
            if not all(isinstance(item, Mapping) and key in item for item in rows):
                raise ValueError("every upsert_array row must contain its key")
            normalized_row["key"] = key
            normalized_row["rows"] = _jsonable(rows)
        elif operation == "create_json_member":
            value = row.get("value")
            if path:
                raise ValueError("create_json_member Core delta path must be empty")
            if not isinstance(value, (Mapping, list)):
                raise ValueError("create_json_member Core delta requires object/list value")
            normalized_row["value"] = _jsonable(value)
        normalized.append(normalized_row)
    return {
        "schema": CORE_DELTA_SCHEMA,
        "mapSid": map_sid,
        "operations": normalized,
    }


def build_preview(scenario: Any) -> dict[str, Any]:
    profile = _jsonable(_field(scenario, "profile"))
    terrain = _jsonable(_field(scenario, "terrain"))
    return {
        "schema": "olden.procedural-scenario-preview.v1",
        "mapSid": str(_field(scenario, "map_sid")),
        "seed": int(_field(scenario, "seed")),
        "size": int(
            _field(scenario, "size", 0)
            or _field(_field(scenario, "profile"), "map_size", 0)
        ),
        "archetype": (
            profile.get("archetype") if isinstance(profile, dict) else None
        ),
        "topology": _jsonable(_field(scenario, "topology")),
        "layout": _jsonable(_field(scenario, "layout")),
        "terrain": terrain,
        "placements": _jsonable(_field(scenario, "placements")),
        "metrics": _jsonable(_field(scenario, "metrics")),
    }


def create_bundle(
    scenario: Any,
    output_root: Path,
    *,
    donor_map: Path | None = None,
    donor_container: NativeMapContainer | None = None,
    core_deltas: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    compiled_triggers: Sequence[Mapping[str, Any]] | None = None,
    manifest_fragment: Mapping[str, Any] | None = None,
    source_artifacts: Mapping[str, bytes] | None = None,
) -> BundleResult:
    """Emit and package one scenario.

    ``output_root`` must be empty. The service layer builds into a staging
    directory, validates the complete bundle, and only then publishes it.
    Bundle construction itself never touches a game installation.
    """

    output_root = Path(output_root)
    map_sid = str(_field(scenario, "map_sid"))
    if output_root.exists():
        existing_children = [child for child in output_root.iterdir() if child.name != ".gitkeep"]
        if existing_children:
            raise ValueError(
                "create_bundle requires an empty staging directory; publish validated bundles through the service"
            )
    output_root.mkdir(parents=True, exist_ok=True)
    emission = emit_scenario(
        scenario,
        output_root,
        donor_map=None if donor_map is None else Path(donor_map),
        donor_container=donor_container,
        compiled_triggers=compiled_triggers,
    )
    profile_path = output_root / "profile.json"
    preview_path = output_root / "preview.json"
    delta_path = output_root / "core_deltas.json"
    profile_hash = _write_json(profile_path, _jsonable(_field(scenario, "profile")))
    preview_hash = _write_json(preview_path, build_preview(scenario))
    delta_doc = normalize_core_deltas(core_deltas, map_sid=map_sid)
    delta_hash = _write_json(delta_path, delta_doc)
    provenance = _jsonable(_field(scenario, "provenance", {}))
    source_hashes = (
        provenance.get("source_hashes", provenance.get("sourceHashes", {}))
        if isinstance(provenance, dict)
        else {}
    )
    if not isinstance(source_hashes, Mapping):
        raise ValueError("scenario provenance source hashes must be an object")
    source_bindings, source_file_hashes = write_source_artifacts(
        output_root,
        source_hashes,
        source_artifacts,
    )
    hashes = {
        f"maps/{map_sid}.map": emission.container_sha256,
        f"maps/{map_sid}.json": emission.sidecar_sha256,
        "profile.json": profile_hash,
        "preview.json": preview_hash,
        "core_deltas.json": delta_hash,
        **source_file_hashes,
    }
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "mapSid": map_sid,
        "scenarioId": str(_field(scenario, "scenario_id", map_sid)),
        "generatorVersion": str(
            _field(scenario, "generator_version", "")
            or (provenance.get("generatorVersion", "") if isinstance(provenance, dict) else "")
        ),
        "seed": int(_field(scenario, "seed")),
        "mechanicalFingerprint": emission.mechanical_fingerprint,
        "installDestinationPolicy": "maps_root_custom_only",
        "proofBoundary": "generated artifact validated; runtime unproven",
        "files": hashes,
        "sourceHashes": dict(source_hashes),
        "sourceArtifacts": source_bindings,
        "provenance": provenance,
    }
    if manifest_fragment:
        for key, value in manifest_fragment.items():
            normalized_value = _jsonable(value)
            if key in manifest and manifest[key] != normalized_value:
                raise ValueError(f"manifest fragment conflicts at {key!r}")
            manifest[key] = normalized_value
    manifest_path = output_root / "manifest.json"
    _write_json(manifest_path, manifest)
    verify_source_artifacts(manifest, output_root)
    return BundleResult(output_root, map_sid, manifest_path, emission, hashes)


def list_library(library_root: Path) -> list[dict[str, Any]]:
    library_root = Path(library_root)
    if not library_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(library_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append(
                {
                    "mapSid": None,
                    "scenarioId": None,
                    "seed": None,
                    "generatorVersion": None,
                    "path": str(manifest_path.parent),
                    "error": f"manifest unreadable: {exc}",
                }
            )
            continue
        if not isinstance(manifest, Mapping):
            rows.append(
                {
                    "mapSid": None,
                    "scenarioId": None,
                    "seed": None,
                    "generatorVersion": None,
                    "path": str(manifest_path.parent),
                    "error": "manifest root must be an object",
                }
            )
            continue
        rows.append(
            {
                "mapSid": manifest.get("mapSid"),
                "scenarioId": manifest.get("scenarioId"),
                "seed": manifest.get("seed"),
                "generatorVersion": manifest.get("generatorVersion"),
                "path": str(manifest_path.parent),
            }
        )
    return rows
