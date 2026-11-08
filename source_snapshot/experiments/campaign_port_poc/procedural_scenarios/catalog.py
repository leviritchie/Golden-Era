"""Immutable, fail-closed procedural content catalog built from ``Core.zip``."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .model import Footprint, Point, canonical_json_bytes, sha256_json
from .native_catalog import (
    NativeCatalogError,
    NativeGeneratorSnapshot,
    load_native_generator_snapshot,
    resolve_pool_weights,
)



CUSTOM_CONTENT_MANIFEST_SCHEMA = "homm3.procedural_content_manifest.v1"
# These are abstract native-generator requests, not placeable ObjectConfig SIDs.
# Keep the list exact so new unresolved references fail closed.
_ABSTRACT_NATIVE_REFS = frozenset(
    tuple(f"random_hire_{tier}" for tier in range(1, 8))
    + tuple(
        f"random_item_{rarity}" for rarity in ("common", "rare", "epic", "legendary")
    )
)

_EMPTY_NATIVE = NativeGeneratorSnapshot((), (), ())


# These ObjectConfig rows are map/editor helpers rather than player-facing
# scenery. They remain available through an explicit profile allowlist, but
# must not silently consume the default visual-density budget.
_PROCEDURAL_HELPER_SIDS = frozenset(
    {
        "fx_map_object_blocked",
        "fx_map_smoke",
        "homm3_envelope_padding_blocker",
        "homm3_landon_map_event_marker",
        "homm3_pathing_blocker",
    }
)

class CatalogBuildError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogSourceArtifact:
    """Immutable bytes for one non-Core source recorded by the catalog."""

    source_key: str
    sha256: str
    payload: bytes

    def __post_init__(self) -> None:
        if not self.source_key or self.source_key == "core":
            raise CatalogBuildError("catalog source artifact requires a non-Core source key")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise CatalogBuildError("catalog source artifact hash must be lowercase sha256")
        if not isinstance(self.payload, bytes):
            raise CatalogBuildError("catalog source artifact payload must be immutable bytes")
        actual = hashlib.sha256(self.payload).hexdigest()
        if actual != self.sha256:
            raise CatalogBuildError(
                f"catalog source artifact hash mismatch for {self.source_key}"
            )


class ContentKind(str, Enum):
    FACTION = "faction"
    HERO = "hero"
    UNIT = "unit"
    TERRAIN = "terrain"
    SETTLEMENT = "settlement"
    ENCOUNTER = "encounter"
    REWARD = "reward"
    INTERACTABLE = "interactable"
    OBJECTIVE = "objective"
    SCENERY = "scenery"
    OBJECT = "object"


@dataclass(frozen=True)
class CatalogEntry:
    sid: str
    kind: ContentKind
    source: str
    source_member: str
    content_hash: str
    footprint: Footprint
    biomes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    native_id: int | str | None = None
    eligible: bool = True
    exclusion_reason: str | None = None
    metadata: tuple[tuple[str, Any], ...] = ()

    def metadata_value(self, key: str, default: Any = None) -> Any:
        return dict(self.metadata).get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "kind": self.kind.value,
            "source": self.source,
            "sourceMember": self.source_member,
            "contentHash": self.content_hash,
            "footprint": self.footprint.to_dict(),
            "biomes": list(self.biomes),
            "tags": list(self.tags),
            "nativeId": self.native_id,
            "eligible": self.eligible,
            "exclusionReason": self.exclusion_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ContentCatalogSnapshot:
    entries: tuple[CatalogEntry, ...]
    source_hashes: tuple[tuple[str, str], ...]
    core_hash: str
    allowlist: tuple[str, ...] = ()
    native_generator: NativeGeneratorSnapshot = _EMPTY_NATIVE
    source_artifacts: tuple[CatalogSourceArtifact, ...] = ()

    def __post_init__(self) -> None:
        canonical = tuple(
            sorted(
                self.entries,
                key=lambda entry: (entry.kind.value, entry.sid, entry.source_member),
            )
        )
        if self.entries != canonical:
            raise CatalogBuildError("catalog entries must use canonical order")
        keys = [(entry.kind, entry.sid) for entry in self.entries]
        duplicates = sorted(
            f"{kind.value}:{sid}"
            for kind, sid in set(keys)
            if keys.count((kind, sid)) > 1
        )
        if duplicates:
            raise CatalogBuildError(
                f"ambiguous duplicate catalog entries: {duplicates[:20]}"
            )
        artifact_order = tuple(
            sorted(self.source_artifacts, key=lambda artifact: artifact.source_key)
        )
        if self.source_artifacts != artifact_order:
            raise CatalogBuildError("catalog source artifacts must use canonical order")
        artifact_keys = [artifact.source_key for artifact in self.source_artifacts]
        if len(artifact_keys) != len(set(artifact_keys)):
            raise CatalogBuildError("catalog source artifact keys must be unique")
        source_hashes = dict(self.source_hashes)
        for artifact in self.source_artifacts:
            if source_hashes.get(artifact.source_key) != artifact.sha256:
                raise CatalogBuildError(
                    "catalog source artifact is not declared by sourceHashes: "
                    f"{artifact.source_key}"
                )

    @classmethod
    def from_core(
        cls,
        core_zip: Path,
        *,
        custom_manifests: Sequence[Path] = (),
        allowlist: Iterable[str] = (),
    ) -> "ContentCatalogSnapshot":
        core_zip = Path(core_zip)
        if not core_zip.is_file():
            raise CatalogBuildError(f"Core.zip not found: {core_zip}")
        allow = tuple(sorted({_sid(value, "allowlist SID") for value in allowlist}))
        try:
            core_payload = core_zip.read_bytes()
        except OSError as ex:
            raise CatalogBuildError(f"cannot snapshot Core.zip {core_zip}: {ex}") from ex
        core_hash = hashlib.sha256(core_payload).hexdigest()
        source_hashes: list[tuple[str, str]] = [("core", core_hash)]
        source_artifacts: list[CatalogSourceArtifact] = []
        entries: list[CatalogEntry] = []
        try:
            with zipfile.ZipFile(io.BytesIO(core_payload)) as archive:
                native_generator = load_native_generator_snapshot(archive)
                for member in sorted(archive.namelist()):
                    kind_hint = _member_kind(member)
                    if kind_hint is None or not member.endswith(".json"):
                        continue
                    payload = _archive_json(archive, member)
                    rows = payload.get("array") if isinstance(payload, dict) else None
                    if not isinstance(rows, list):
                        raise CatalogBuildError(
                            f"Core catalog member {member} has no array list"
                        )
                    for index, row in enumerate(rows):
                        if not isinstance(row, dict):
                            raise CatalogBuildError(
                                f"Core catalog row {member}[{index}] is not an object"
                            )
                        if "id" in row:
                            entries.append(
                                _core_entry(
                                    row,
                                    member=member,
                                    source="core",
                                    allowlist=frozenset(allow),
                                )
                            )
        except (OSError, zipfile.BadZipFile, NativeCatalogError) as ex:
            raise CatalogBuildError(f"cannot read Core.zip {core_zip}: {ex}") from ex

        for path in sorted((Path(value) for value in custom_manifests), key=str):
            custom_entries, hashes, artifacts = _manifest_entries(
                path, allowlist=frozenset(allow)
            )
            entries.extend(custom_entries)
            source_hashes.extend(hashes)
            source_artifacts.extend(artifacts)
        source_hash_map: dict[str, str] = {}
        for source_key, source_hash in source_hashes:
            previous = source_hash_map.setdefault(source_key, source_hash)
            if previous != source_hash:
                raise CatalogBuildError(
                    f"conflicting source hashes for logical key {source_key!r}"
                )
        artifact_map: dict[str, CatalogSourceArtifact] = {}
        for artifact in source_artifacts:
            previous = artifact_map.setdefault(artifact.source_key, artifact)
            if previous != artifact:
                raise CatalogBuildError(
                    "conflicting source artifacts for logical key "
                    f"{artifact.source_key!r}"
                )
        entries = _collapse(entries)
        entries.sort(key=lambda entry: (entry.kind.value, entry.sid, entry.source_member))
        return cls(
            entries=tuple(entries),
            source_hashes=tuple(sorted(source_hash_map.items())),
            core_hash=core_hash,
            allowlist=allow,
            native_generator=native_generator,
            source_artifacts=tuple(
                artifact_map[key] for key in sorted(artifact_map)
            ),
        )

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[CatalogEntry],
        *,
        core_hash: str = "test-core",
        source_hashes: Iterable[tuple[str, str]] = (("test-core", "test-core"),),
        allowlist: Iterable[str] = (),
        native_generator: NativeGeneratorSnapshot = _EMPTY_NATIVE,
        source_artifacts: Iterable[CatalogSourceArtifact] = (),
    ) -> "ContentCatalogSnapshot":
        return cls(
            entries=tuple(
                sorted(
                    entries,
                    key=lambda entry: (
                        entry.kind.value,
                        entry.sid,
                        entry.source_member,
                    ),
                )
            ),
            source_hashes=tuple(sorted(source_hashes)),
            core_hash=core_hash,
            allowlist=tuple(sorted(set(allowlist))),
            native_generator=native_generator,
            source_artifacts=tuple(
                sorted(source_artifacts, key=lambda artifact: artifact.source_key)
            ),
        )

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "entries": [entry.to_dict() for entry in self.entries],
                "sourceHashes": list(self.source_hashes),
                "coreHash": self.core_hash,
                "allowlist": list(self.allowlist),
                "nativeGenerator": self.native_generator.to_dict(),
            }
        )

    def eligible(
        self,
        kind: ContentKind,
        *,
        biomes: Iterable[str] = (),
    ) -> tuple[CatalogEntry, ...]:
        requested = frozenset(value.lower() for value in biomes)
        return tuple(
            entry
            for entry in self.entries
            if entry.kind is kind
            and entry.eligible
            and (
                not requested
                or not entry.biomes
                or bool(requested.intersection(entry.biomes))
            )
        )

    def require_sid(
        self,
        sid: str,
        *,
        kinds: Iterable[ContentKind] | None = None,
    ) -> CatalogEntry:
        kind_set = None if kinds is None else frozenset(kinds)
        matches = tuple(
            entry
            for entry in self.entries
            if entry.sid == sid and (kind_set is None or entry.kind in kind_set)
        )
        if len(matches) != 1:
            raise CatalogBuildError(
                f"content SID {sid!r} requires exactly one matching catalog row; "
                f"found {len(matches)}"
            )
        if not matches[0].eligible:
            raise CatalogBuildError(
                f"content SID {sid!r} is ineligible: {matches[0].exclusion_reason}"
            )
        return matches[0]

    def require_factions(self, sids: Iterable[str]) -> tuple[CatalogEntry, ...]:
        return tuple(
            self.require_sid(sid, kinds=(ContentKind.FACTION,)) for sid in sids
        )

    def terrain_for_biome(self, biome: str) -> CatalogEntry:
        name = biome.lower()
        matches = tuple(
            entry
            for entry in self.eligible(ContentKind.TERRAIN)
            if name in entry.biomes
        )
        if len(matches) != 1:
            raise CatalogBuildError(
                f"biome {name!r} requires exactly one eligible terrain tile; "
                f"found {len(matches)}"
            )
        return matches[0]

    def entries_for_faction(
        self,
        kind: ContentKind,
        faction_sid: str,
    ) -> tuple[CatalogEntry, ...]:
        return tuple(
            entry
            for entry in self.eligible(kind)
            if entry.metadata_value("factionSid") == faction_sid
        )

    def pool_entries(
        self,
        pool_name: str,
        *,
        kinds: Iterable[ContentKind],
        biome: str | None = None,
    ) -> tuple[tuple[CatalogEntry, int], ...]:
        try:
            weights = resolve_pool_weights(
                self.native_generator, pool_name, biome=biome
            )
        except NativeCatalogError as ex:
            raise CatalogBuildError(str(ex)) from ex
        allowed = frozenset(kinds)
        resolved: list[tuple[CatalogEntry, int]] = []
        for sid, weight in weights:
            if weight <= 0:
                continue
            matches = tuple(entry for entry in self.entries if entry.sid == sid)
            if not matches:
                if sid in _ABSTRACT_NATIVE_REFS:
                    continue
                raise CatalogBuildError(
                    f"native pool {pool_name!r} references unresolved content SID {sid!r}"
                )
            typed = tuple(entry for entry in matches if entry.kind in allowed)
            if not typed:
                continue
            if len(typed) != 1:
                raise CatalogBuildError(
                    f"native pool {pool_name!r} resolves {sid!r} ambiguously for "
                    f"{sorted(kind.value for kind in allowed)}"
                )
            entry = typed[0]
            if not entry.eligible:
                raise CatalogBuildError(
                    f"native pool {pool_name!r} references ineligible content SID "
                    f"{sid!r}: {entry.exclusion_reason}"
                )
            resolved.append((entry, weight))
        if not resolved:
            raise CatalogBuildError(
                f"native pool {pool_name!r} has no eligible entries for "
                f"{sorted(kind.value for kind in allowed)}"
            )
        return tuple(resolved)


def _core_entry(
    row: Mapping[str, Any],
    *,
    member: str,
    source: str,
    allowlist: frozenset[str],
) -> CatalogEntry:
    raw_id = row["id"]
    if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
        raise CatalogBuildError(f"{member} row has invalid id {raw_id!r}")
    sid = str(raw_id)
    hint = _member_kind(member)
    if hint is None:
        raise AssertionError(member)
    kind = _object_kind(sid, row) if hint is ContentKind.OBJECT else hint
    reason = _exclusion_reason(sid, row, member, allowlist)
    metadata: list[tuple[str, Any]] = []
    if isinstance(row.get("fraction"), str):
        metadata.append(("factionSid", row["fraction"]))
    if kind is ContentKind.SETTLEMENT:
        faction_sid = _city_faction_sid(sid)
        if faction_sid is not None:
            metadata.append(("factionSid", faction_sid))
    if kind is ContentKind.UNIT:
        if isinstance(row.get("squadValue"), (int, float)) and not isinstance(
            row.get("squadValue"), bool
        ):
            metadata.append(("squadValue", float(row["squadValue"])))
        if isinstance(row.get("tier"), int) and not isinstance(row.get("tier"), bool):
            metadata.append(("tier", row["tier"]))
    if kind is ContentKind.TERRAIN:
        metadata.append(("penalty", row.get("penalty", 0.0)))
    if isinstance(row.get("isInteractable"), bool):
        metadata.append(("isInteractable", row["isInteractable"]))
    return CatalogEntry(
        sid=sid,
        kind=kind,
        source=source,
        source_member=member,
        content_hash=hashlib.sha256(canonical_json_bytes(row)).hexdigest(),
        footprint=_footprint(row, f"{member}:{sid}"),
        biomes=_biomes(row),
        tags=_tags(row),
        native_id=raw_id,
        eligible=reason is None,
        exclusion_reason=reason,
        metadata=tuple(sorted(metadata)),
    )


def _member_kind(member: str) -> ContentKind | None:
    name = member.replace("\\", "/")
    if name.startswith("DB/map/tiles/"):
        return ContentKind.TERRAIN
    if name.startswith("DB/map/objects/"):
        return ContentKind.OBJECT
    if name.startswith("DB/fractions/"):
        return ContentKind.FACTION
    if name.startswith("DB/heroes/"):
        return ContentKind.HERO
    if name.startswith("DB/units/"):
        return ContentKind.UNIT
    return None


def _object_kind(sid: str, row: Mapping[str, Any]) -> ContentKind:
    lowered = sid.lower()
    tag = str(row.get("tag") or "").lower()
    if lowered in {"city-spawner", "random-city"} or lowered.endswith("_city") or lowered in {
        "human_city",
        "nature_city",
        "demon_city",
        "undead_city",
        "dungeon_city",
    }:
        return ContentKind.SETTLEMENT
    if sid == "random-squad":
        return ContentKind.ENCOUNTER
    if "quest_mark" in lowered or "objective" in lowered:
        return ContentKind.OBJECTIVE
    if tag == "resource" or any(
        token in lowered
        for token in ("resource_", "chest", "camp_fire", "random-res", "random-item")
    ):
        return ContentKind.REWARD
    if tag in {"interact", "interactive"} or bool(row.get("isInteractable")):
        return ContentKind.INTERACTABLE
    if tag in {"environment", "block", "fx"}:
        return ContentKind.SCENERY
    return ContentKind.OBJECT


def _city_faction_sid(sid: str) -> str | None:
    if sid.endswith("_city"):
        return sid[:-5]
    return {
        "human_city": "human",
        "nature_city": "nature",
        "demon_city": "demon",
        "undead_city": "undead",
        "dungeon_city": "dungeon",
    }.get(sid)


def _footprint(row: Mapping[str, Any], label: str) -> Footprint:
    nodes = row.get("nodes")
    if nodes is None:
        return Footprint(1, 1, (), ())
    width, height = row.get("sizeX"), row.get("sizeZ")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width <= 0
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height <= 0
        or not isinstance(nodes, list)
        or len(nodes) != width * height
    ):
        raise CatalogBuildError(f"{label} has an invalid ObjectConfig node grid")
    if any(isinstance(value, bool) or value not in (0, 1, 2) for value in nodes):
        raise CatalogBuildError(f"{label} has unsupported ObjectConfig node codes")
    pivot_x = row.get("pivotX", 0)
    pivot_y = row.get("pivotZ", 0)
    if (
        isinstance(pivot_x, bool)
        or not isinstance(pivot_x, int)
        or isinstance(pivot_y, bool)
        or not isinstance(pivot_y, int)
        or not 0 <= pivot_x < width
        or not 0 <= pivot_y < height
    ):
        raise CatalogBuildError(f"{label} has an invalid pivotX/pivotZ")

    return Footprint(
        width,
        height,
        tuple(
            Point(index % width - pivot_x, index // width - pivot_y)
            for index, value in enumerate(nodes)
            if value == 1
        ),
        tuple(
            Point(index % width - pivot_x, index // width - pivot_y)
            for index, value in enumerate(nodes)
            if value == 2
        ),
    )


def _biomes(row: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    raw = row.get("biome")
    if isinstance(raw, str) and raw:
        values.add(raw.lower().replace(" ", "_"))
    raw_values = row.get("biomes")
    if isinstance(raw_values, list):
        if any(not isinstance(value, str) or not value for value in raw_values):
            raise CatalogBuildError("biomes must contain non-empty strings")
        values.update(value.lower().replace(" ", "_") for value in raw_values)
    return tuple(sorted(values))


def _tags(row: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    raw = row.get("tag")
    if isinstance(raw, str) and raw:
        values.add(raw.lower())
    raw_values = row.get("tags")
    if isinstance(raw_values, list):
        if any(not isinstance(value, str) or not value for value in raw_values):
            raise CatalogBuildError("tags must contain non-empty strings")
        values.update(value.lower() for value in raw_values)
    return tuple(sorted(values))


def _exclusion_reason(
    sid: str,
    row: Mapping[str, Any],
    member: str,
    allowlist: frozenset[str],
) -> str | None:
    if sid in allowlist:
        return None
    if sid.lower() in _PROCEDURAL_HELPER_SIDS:
        return "procedural_helper_content"
    if row.get("proceduralEligible") is False:
        return "procedural_eligible_false"
    if row.get("scenarioOnly") is True:
        return "scenario_only"
    classification_parts = [
        str(row.get(key) or "")
        for key in ("status", "tag", "category", "sourceStatus")
    ]
    for key in ("prefs", "tags"):
        values = row.get(key, ())
        if isinstance(values, (list, tuple)):
            classification_parts.extend(value for value in values if isinstance(value, str))
    status = " ".join(classification_parts).lower()
    if "unresolved" in status:
        return "unresolved_content"
    if re.search(r"(^|[\s/_.-])meta($|[\s/_.-])", status):
        return "meta_content"
    searchable = " ".join((member, sid, status)).lower()

    if re.search(r"(^|[\s/_.-])(?:test|probe|debug)(?:$|[\s/_.-])", searchable):
        return "test_or_probe_content"
    # Core also carries map-specific helper members (for example the
    # Homecoming exact-footprint clones). They look like ordinary ObjectConfig
    # rows but are not reusable procedural content without an explicit
    # allowlist entry. Use member provenance rather than guessing from a SID.
    if re.search(
        r"(^|[/_.-])(?:campaigns?|homecoming|missions?|scenarios?|stories?|story)(?:[/_.-]|$)",
        member.lower(),
    ):
        return "scenario_specific_content"
    if re.match(r"^(?:campaign|scenario|story|mission)[_.-]", sid.lower()):
        return "scenario_specific_content"
    return None


def _collapse(entries: Iterable[CatalogEntry]) -> list[CatalogEntry]:
    grouped: dict[tuple[ContentKind, str], list[CatalogEntry]] = {}
    for entry in entries:
        grouped.setdefault((entry.kind, entry.sid), []).append(entry)
    out: list[CatalogEntry] = []
    for key in sorted(grouped, key=lambda value: (value[0].value, value[1])):
        group = sorted(grouped[key], key=lambda entry: entry.source_member)
        if len(group) == 1:
            out.append(group[0])
            continue
        first = group[0]
        merged_metadata: dict[str, Any] = {}
        for entry in group:
            for name, value in entry.metadata:
                if name in merged_metadata and merged_metadata[name] != value:
                    raise CatalogBuildError(
                        f"conflicting metadata for {first.kind.value}:{first.sid}:{name}"
                    )
                merged_metadata[name] = value
        signatures = {
            (
                entry.footprint,
                entry.biomes,
                entry.native_id,
                entry.eligible,
                entry.exclusion_reason,
            )
            for entry in group
        }
        if len(signatures) != 1:
            raise CatalogBuildError(
                f"conflicting definitions for {first.kind.value}:{first.sid}"
            )
        out.append(
            CatalogEntry(
                sid=first.sid,
                kind=first.kind,
                source=first.source,
                source_member=";".join(item.source_member for item in group),
                content_hash=hashlib.sha256(
                    "".join(item.content_hash for item in group).encode("ascii")
                ).hexdigest(),
                footprint=first.footprint,
                biomes=first.biomes,
                tags=tuple(sorted({tag for item in group for tag in item.tags})),
                native_id=first.native_id,
                eligible=first.eligible,
                exclusion_reason=first.exclusion_reason,
                metadata=tuple(sorted(merged_metadata.items())),
            )
        )
    return out


def _manifest_entries(
    path: Path,
    *,
    allowlist: frozenset[str],
) -> tuple[
    list[CatalogEntry],
    list[tuple[str, str]],
    list[CatalogSourceArtifact],
]:
    if not path.is_file():
        raise CatalogBuildError(f"custom content manifest not found: {path}")
    try:
        manifest_payload = path.read_bytes()
        manifest_hash = hashlib.sha256(manifest_payload).hexdigest()
        raw = json.loads(manifest_payload.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise CatalogBuildError(f"cannot read custom manifest {path}: {ex}") from ex
    if not isinstance(raw, dict) or raw.get("schema") != CUSTOM_CONTENT_MANIFEST_SCHEMA:
        raise CatalogBuildError(
            f"custom manifest {path} must use {CUSTOM_CONTENT_MANIFEST_SCHEMA!r}"
        )
    rows = raw.get("content")
    if not isinstance(rows, list):
        raise CatalogBuildError(f"{path}:content must be a list")
    source_label = f"custom-manifest/{manifest_hash}"
    hashes = [(source_label, manifest_hash)]
    artifacts = [
        CatalogSourceArtifact(source_label, manifest_hash, manifest_payload)
    ]
    _verify_files(
        path,
        raw.get("files"),
        hashes,
        artifacts,
        source_label=source_label,
    )
    entries: list[CatalogEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogBuildError(f"{path}:content[{index}] must be an object")
        sid = _sid(row.get("sid"), f"{path}:content[{index}].sid")
        try:
            kind = ContentKind(row.get("kind"))
        except ValueError as ex:
            raise CatalogBuildError(
                f"{path}:content[{index}] has invalid kind"
            ) from ex
        eligible = row.get("eligible", True)
        if not isinstance(eligible, bool):
            raise CatalogBuildError(f"{path}:content[{index}].eligible must be boolean")
        footprint = _manifest_footprint(
            row.get("footprint", {}), f"{path}:content[{index}].footprint"
        )
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            raise CatalogBuildError(f"{path}:content[{index}].metadata must be an object")
        reason = _exclusion_reason(sid, row, f"content[{index}]", allowlist)
        if not eligible and sid not in allowlist:
            reason = str(row.get("exclusionReason") or "manifest_ineligible")
        entries.append(
            CatalogEntry(
                sid=sid,
                kind=kind,
                source=source_label,
                source_member=f"content[{index}]",
                content_hash=hashlib.sha256(canonical_json_bytes(row)).hexdigest(),
                footprint=footprint,
                biomes=_string_tuple(row.get("biomes", ()), "biomes"),
                tags=_string_tuple(row.get("tags", ()), "tags"),
                native_id=row.get("nativeId", sid),
                eligible=reason is None,
                exclusion_reason=reason,
                metadata=tuple(sorted((str(key), value) for key, value in metadata.items())),
            )
        )
    return entries, hashes, artifacts


def _manifest_footprint(raw: Any, label: str) -> Footprint:
    if not isinstance(raw, Mapping):
        raise CatalogBuildError(f"{label} must be an object")
    width, height = raw.get("width", 1), raw.get("height", 1)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (width, height)
    ):
        raise CatalogBuildError(f"{label} dimensions must be positive integers")

    pivot_x, pivot_y = raw.get("pivotX", 0), raw.get("pivotZ", 0)
    if (
        isinstance(pivot_x, bool)
        or not isinstance(pivot_x, int)
        or isinstance(pivot_y, bool)
        or not isinstance(pivot_y, int)
        or not 0 <= pivot_x < width
        or not 0 <= pivot_y < height
    ):
        raise CatalogBuildError(f"{label} has an invalid pivotX/pivotZ")

    def points(key: str) -> tuple[Point, ...]:
        values = raw.get(key, ())
        if not isinstance(values, (list, tuple)):
            raise CatalogBuildError(f"{label}.{key} must be a list")
        result: list[Point] = []
        for pair in values:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in pair)
            ):
                raise CatalogBuildError(f"{label}.{key} cells must be [x,y]")
            point = Point(pair[0], pair[1])
            if not 0 <= point.x < width or not 0 <= point.y < height:
                raise CatalogBuildError(f"{label}.{key} cell is out of bounds")
            result.append(Point(point.x - pivot_x, point.y - pivot_y))
        if len(result) != len(set(result)):
            raise CatalogBuildError(f"{label}.{key} has duplicate cells")
        return tuple(result)

    occupied, interaction = points("occupied"), points("interaction")
    if set(occupied).intersection(interaction):
        raise CatalogBuildError(f"{label} occupied and interaction cells overlap")
    return Footprint(width, height, occupied, interaction)


def _verify_files(
    manifest: Path,
    raw: Any,
    hashes: list[tuple[str, str]],
    artifacts: list[CatalogSourceArtifact],
    *,
    source_label: str,
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise CatalogBuildError(f"{manifest}:files must be an object")
    base = manifest.parent.resolve()
    for relative, expected in sorted(raw.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise CatalogBuildError(f"{manifest}:files entries must be strings")
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as ex:
            raise CatalogBuildError(f"{manifest}:files path escapes root") from ex
        try:
            payload = candidate.read_bytes()
        except OSError as ex:
            raise CatalogBuildError(
                f"{manifest}:cannot read referenced file {relative}: {ex}"
            ) from ex
        actual = hashlib.sha256(payload).hexdigest()
        if actual.lower() != expected.lower():
            raise CatalogBuildError(f"{manifest}:files hash mismatch for {relative}")
        normalized_relative = Path(relative).as_posix()
        source_key = f"{source_label}/files/{normalized_relative}"
        hashes.append((source_key, actual))
        artifacts.append(CatalogSourceArtifact(source_key, actual, payload))


def _archive_json(archive: zipfile.ZipFile, member: str) -> Any:
    try:
        return json.loads(archive.read(member).decode("utf-8-sig"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise CatalogBuildError(f"invalid Core catalog JSON {member}: {ex}") from ex


def _string_tuple(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)) or any(
        not isinstance(value, str) or not value for value in raw
    ):
        raise CatalogBuildError(f"{label} must be a list of non-empty strings")
    return tuple(sorted({value.lower().replace(" ", "_") for value in raw}))


def _sid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogBuildError(f"{label} must be a non-empty SID")
    return value.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as ex:
        raise CatalogBuildError(f"cannot hash {path}: {ex}") from ex
    return digest.hexdigest()
