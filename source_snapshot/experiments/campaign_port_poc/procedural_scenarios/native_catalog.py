"""Typed snapshot of Olden's native generator lists, pools, and templates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .model import Point, canonical_json_bytes


CONTENT_LIST_MEMBERS = frozenset(
    {
        "generator/content_lists/basic_content_lists.json",
        "generator/content_lists/basic_content_lists_variants_table.json",
        "generator/content_lists/generator_content_lists.json",
    }
)
CONTENT_POOL_MEMBERS = frozenset(
    {
        "generator/content_pools/basic_pools_default.json",
        "generator/content_pools/basic_pools_resources.json",
        "generator/content_pools/default_content_pools.json",
    }
)
ENCOUNTER_TEMPLATE_PREFIX = "generator/encounter_templates/"


class NativeCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class WeightedContentRef:
    sid: str
    weight: int
    biome: str | None = None
    variant: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "weight": self.weight,
            "biome": self.biome,
            "variant": self.variant,
        }


@dataclass(frozen=True)
class NativeContentList:
    name: str
    content: tuple[WeightedContentRef, ...]
    source_member: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": [item.to_dict() for item in self.content],
            "sourceMember": self.source_member,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class NativePoolGroup:
    weight: int
    include_lists: tuple[str, ...]
    content: tuple[WeightedContentRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "weight": self.weight,
            "includeLists": list(self.include_lists),
            "content": [item.to_dict() for item in self.content],
        }


@dataclass(frozen=True)
class NativeContentPool:
    name: str
    groups: tuple[NativePoolGroup, ...]
    bans: tuple[tuple[str, int | None], ...]
    source_member: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "groups": [group.to_dict() for group in self.groups],
            "bans": [
                {"sid": sid, "variant": variant} for sid, variant in self.bans
            ],
            "sourceMember": self.source_member,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class NativeEncounterBuilding:
    width: int
    height: int
    interaction: int
    position: Point

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "interaction": self.interaction,
            "position": self.position.to_dict(),
        }


@dataclass(frozen=True)
class NativeEncounterPickup:
    position: Point
    optional: bool
    can_be_hole: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.to_dict(),
            "isOptional": self.optional,
            "canBeHole": self.can_be_hole,
        }


def _points_to_dict(values: tuple[Point, ...]) -> list[dict[str, int]]:
    return [value.to_dict() for value in values]


@dataclass(frozen=True)
class NativeEncounterTemplate:
    name: str
    width: int
    height: int
    encounter_type: int
    guarded: bool
    building_count: int
    pickup_count: int
    source_member: str
    content_hash: str
    relative_frequency: float = 0.0
    allow_mirror_x: bool = False
    allow_mirror_y: bool = False
    road_target_type: int = 0
    road_target: Point | None = None
    guards: tuple[Point, ...] = ()
    buildings: tuple[NativeEncounterBuilding, ...] = ()
    pickups: tuple[NativeEncounterPickup, ...] = ()
    entrances: tuple[Point, ...] = ()
    hole_tiles: tuple[Point, ...] = ()
    tile_contents: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "encounterType": self.encounter_type,
            "guarded": self.guarded,
            "buildingCount": self.building_count,
            "pickupCount": self.pickup_count,
            "sourceMember": self.source_member,
            "contentHash": self.content_hash,
            "relativeFrequency": self.relative_frequency,
            "allowMirrorX": self.allow_mirror_x,
            "allowMirrorY": self.allow_mirror_y,
            "roadTargetType": self.road_target_type,
            "roadTarget": None if self.road_target is None else self.road_target.to_dict(),
            "guards": _points_to_dict(self.guards),
            "buildings": [item.to_dict() for item in self.buildings],
            "pickups": [item.to_dict() for item in self.pickups],
            "entrances": _points_to_dict(self.entrances),
            "holeTiles": _points_to_dict(self.hole_tiles),
            "tileContents": list(self.tile_contents),
        }


@dataclass(frozen=True)
class NativeGeneratorSnapshot:
    content_lists: tuple[NativeContentList, ...]
    content_pools: tuple[NativeContentPool, ...]
    encounter_templates: tuple[NativeEncounterTemplate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contentLists": [item.to_dict() for item in self.content_lists],
            "contentPools": [item.to_dict() for item in self.content_pools],
            "encounterTemplates": [
                item.to_dict() for item in self.encounter_templates
            ],
        }


def load_native_generator_snapshot(archive: Any) -> NativeGeneratorSnapshot:
    lists: dict[str, NativeContentList] = {}
    pools: dict[str, NativeContentPool] = {}
    templates: dict[str, NativeEncounterTemplate] = {}
    members = frozenset(archive.namelist())
    for member in sorted(CONTENT_LIST_MEMBERS):
        if member not in members:
            raise NativeCatalogError(f"Core.zip is missing native content list {member}")
        for row in _root_rows(archive, member):
            name = _name(row, member)
            item = NativeContentList(
                name=name,
                content=_content_refs(row.get("content", ()), f"{member}:{name}.content"),
                source_member=member,
                content_hash=_hash(row),
            )
            _add_unique(lists, name, item, "content list")
    for member in sorted(CONTENT_POOL_MEMBERS):
        if member not in members:
            raise NativeCatalogError(f"Core.zip is missing native content pool {member}")
        for row in _root_rows(archive, member):
            name = _name(row, member)
            raw_groups = row.get("groups")
            if not isinstance(raw_groups, list):
                raise NativeCatalogError(f"{member}:{name}.groups must be a list")
            groups: list[NativePoolGroup] = []
            for index, group in enumerate(raw_groups):
                if not isinstance(group, Mapping):
                    raise NativeCatalogError(
                        f"{member}:{name}.groups[{index}] must be an object"
                    )
                weight = _nonnegative_int(
                    group.get("weight", 0),
                    f"{member}:{name}.groups[{index}].weight",
                )
                include_lists = _string_tuple(
                    group.get("includeLists", ()),
                    f"{member}:{name}.groups[{index}].includeLists",
                )
                groups.append(
                    NativePoolGroup(
                        weight=weight,
                        include_lists=include_lists,
                        content=_content_refs(
                            group.get("content", ()),
                            f"{member}:{name}.groups[{index}].content",
                        ),
                    )
                )
            bans = _bans(row.get("bans", ()), f"{member}:{name}.bans")
            item = NativeContentPool(
                name=name,
                groups=tuple(groups),
                bans=bans,
                source_member=member,
                content_hash=_hash(row),
            )
            _add_unique(pools, name, item, "content pool")
    for member in sorted(members):
        if (
            not member.startswith(ENCOUNTER_TEMPLATE_PREFIX)
            or not member.endswith(".json")
            or "/test" in member.lower()
        ):
            continue
        row = _json(archive, member)
        if not isinstance(row, Mapping):
            raise NativeCatalogError(f"{member} encounter template must be an object")
        _name(row, member)
        name = member.rsplit("/", 1)[-1][:-5]
        width = _positive_int(row.get("width"), f"{member}.width")
        height = _positive_int(row.get("height"), f"{member}.height")
        raw_tile_contents = row.get("tileContents")
        if not isinstance(raw_tile_contents, list) or len(raw_tile_contents) != width * height:
            raise NativeCatalogError(
                f"{member}.tileContents must contain width*height entries"
            )
        tile_contents = tuple(
            _nonnegative_int(value, f"{member}.tileContents[{index}]")
            for index, value in enumerate(raw_tile_contents)
        )
        if any(value > 5 for value in tile_contents):
            raise NativeCatalogError(
                f"{member}.tileContents contains an unsupported TileContent code"
            )
        guards = _encounter_guard_positions(row.get("guards"), f"{member}.guards")
        buildings = _encounter_buildings(row.get("buildings"), f"{member}.buildings")
        pickups = _encounter_pickups(row.get("pickups"), f"{member}.pickups")
        item = NativeEncounterTemplate(
            name=name,
            width=width,
            height=height,
            encounter_type=_nonnegative_int(
                row.get("encounterType", 0), f"{member}.encounterType"
            ),
            guarded=bool(guards),
            building_count=len(buildings),
            pickup_count=len(pickups),
            source_member=member,
            content_hash=_hash(row),
            relative_frequency=_positive_number(
                row.get("relativeFrequency"), f"{member}.relativeFrequency"
            ),
            allow_mirror_x=_boolean(row.get("allowMirrorX"), f"{member}.allowMirrorX"),
            allow_mirror_y=_boolean(row.get("allowMirrorY"), f"{member}.allowMirrorY"),
            road_target_type=_nonnegative_int(
                row.get("roadTargetType"), f"{member}.roadTargetType"
            ),
            road_target=_point(row.get("roadTarget"), f"{member}.roadTarget"),
            guards=guards,
            buildings=buildings,
            pickups=pickups,
            entrances=_point_list(row.get("entrances"), f"{member}.entrances"),
            hole_tiles=_point_list(row.get("holeTiles"), f"{member}.holeTiles"),
            tile_contents=tile_contents,
        )
        _validate_encounter_template(item)
        _add_unique(templates, name, item, "encounter template")
    snapshot = NativeGeneratorSnapshot(
        content_lists=tuple(lists[name] for name in sorted(lists)),
        content_pools=tuple(pools[name] for name in sorted(pools)),
        encounter_templates=tuple(templates[name] for name in sorted(templates)),
    )
    _validate_pool_list_references(snapshot)
    return snapshot


def validate_native_content_references(
    snapshot: NativeGeneratorSnapshot,
    content_sids: Iterable[str],
) -> None:
    known = frozenset(content_sids)
    unresolved: set[str] = set()
    for content_list in snapshot.content_lists:
        unresolved.update(
            item.sid for item in content_list.content if item.weight > 0 and item.sid not in known
        )
    for pool in snapshot.content_pools:
        for group in pool.groups:
            unresolved.update(
                item.sid for item in group.content if item.weight > 0 and item.sid not in known
            )
    if unresolved:
        raise NativeCatalogError(
            "native generator content references unresolved ObjectConfig SIDs: "
            f"{sorted(unresolved)[:30]}"
        )


def resolve_pool_weights(
    snapshot: NativeGeneratorSnapshot,
    pool_name: str,
    *,
    biome: str | None = None,
) -> tuple[tuple[str, int], ...]:
    pool_map = {pool.name: pool for pool in snapshot.content_pools}
    list_map = {item.name: item for item in snapshot.content_lists}
    pool = pool_map.get(pool_name)
    if pool is None:
        raise NativeCatalogError(f"native content pool not found: {pool_name}")
    normalized_biome = None if biome is None else biome.lower().replace(" ", "_")
    bans = {sid for sid, _variant in pool.bans}
    weights: dict[str, int] = {}
    for group in pool.groups:
        if group.weight <= 0:
            continue
        refs: list[WeightedContentRef] = list(group.content)
        for list_name in group.include_lists:
            refs.extend(list_map[list_name].content)
        for ref in refs:
            if ref.sid in bans or ref.weight <= 0:
                continue
            if (
                ref.biome is not None
                and normalized_biome is not None
                and ref.biome != normalized_biome
            ):
                continue
            weights[ref.sid] = weights.get(ref.sid, 0) + group.weight * ref.weight
    return tuple(sorted(weights.items()))


def _validate_pool_list_references(snapshot: NativeGeneratorSnapshot) -> None:
    names = {item.name for item in snapshot.content_lists}
    missing = sorted(
        {
            name
            for pool in snapshot.content_pools
            for group in pool.groups
            for name in group.include_lists
            if name not in names
        }
    )
    if missing:
        raise NativeCatalogError(
            f"native content pools reference missing content lists: {missing[:30]}"
        )


def _validate_encounter_template(template: NativeEncounterTemplate) -> None:
    def inside(point: Point) -> bool:
        return 0 <= point.x < template.width and 0 <= point.y < template.height

    if template.road_target is None or not inside(template.road_target):
        raise NativeCatalogError(
            f"{template.source_member}.roadTarget must be inside the template"
        )
    for label, points in (
        ("guards", template.guards),
        ("pickups", tuple(item.position for item in template.pickups)),
        ("holeTiles", template.hole_tiles),
    ):
        if any(not inside(point) for point in points):
            raise NativeCatalogError(
                f"{template.source_member}.{label} contains an out-of-bounds point"
            )
    for building in template.buildings:
        if (
            building.position.x < 0
            or building.position.y < 0
            or building.position.x + building.width > template.width
            or building.position.y + building.height > template.height
        ):
            raise NativeCatalogError(
                f"{template.source_member}.buildings contains an out-of-bounds slot"
            )



def _root_rows(archive: Any, member: str) -> list[Mapping[str, Any]]:
    raw = _json(archive, member)
    if not isinstance(raw, list):
        raise NativeCatalogError(f"{member} root must be a list")
    if any(not isinstance(row, Mapping) for row in raw):
        raise NativeCatalogError(f"{member} rows must be objects")
    return raw


def _json(archive: Any, member: str) -> Any:
    try:
        return json.loads(archive.read(member).decode("utf-8-sig"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise NativeCatalogError(f"invalid native generator JSON {member}: {ex}") from ex


def _name(row: Mapping[str, Any], member: str) -> str:
    value = row.get("name")
    if not isinstance(value, str) or not value:
        raise NativeCatalogError(f"{member} row has no non-empty name")
    return value


def _content_refs(raw: Any, label: str) -> tuple[WeightedContentRef, ...]:
    if not isinstance(raw, (list, tuple)):
        raise NativeCatalogError(f"{label} must be a list")
    refs: list[WeightedContentRef] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise NativeCatalogError(f"{label}[{index}] must be an object")
        sid = item.get("sid")
        if not isinstance(sid, str) or not sid:
            raise NativeCatalogError(f"{label}[{index}].sid must be non-empty")
        weight = _nonnegative_int(item.get("weight", 0), f"{label}[{index}].weight")
        biome = item.get("biome")
        if biome is not None:
            if not isinstance(biome, str) or not biome:
                raise NativeCatalogError(f"{label}[{index}].biome is invalid")
            biome = biome.lower().replace(" ", "_")
        variant = item.get("variant")
        if variant is not None:
            variant = _nonnegative_int(variant, f"{label}[{index}].variant")
        refs.append(WeightedContentRef(sid, weight, biome, variant))
    return tuple(refs)


def _bans(raw: Any, label: str) -> tuple[tuple[str, int | None], ...]:
    if not isinstance(raw, (list, tuple)):
        raise NativeCatalogError(f"{label} must be a list")
    values: list[tuple[str, int | None]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or not isinstance(item.get("sid"), str):
            raise NativeCatalogError(f"{label}[{index}] must contain sid")
        variant = item.get("variant")
        if variant is not None:
            variant = _nonnegative_int(variant, f"{label}[{index}].variant")
        values.append((item["sid"], variant))
    return tuple(values)


def _string_tuple(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)) or any(
        not isinstance(value, str) or not value for value in raw
    ):
        raise NativeCatalogError(f"{label} must be a list of non-empty strings")
    if len(set(raw)) != len(raw):
        raise NativeCatalogError(f"{label} contains duplicates")
    return tuple(raw)


def _point(raw: Any, label: str) -> Point:
    if not isinstance(raw, Mapping):
        raise NativeCatalogError(f"{label} must be an object")
    x = raw.get("x")
    y = raw.get("y")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
        raise NativeCatalogError(f"{label}.x/y must be integers")
    return Point(x, y)


def _point_list(raw: Any, label: str) -> tuple[Point, ...]:
    if not isinstance(raw, list):
        raise NativeCatalogError(f"{label} must be a list")
    return tuple(_point(value, f"{label}[{index}]") for index, value in enumerate(raw))


def _encounter_guard_positions(raw: Any, label: str) -> tuple[Point, ...]:
    if not isinstance(raw, list):
        raise NativeCatalogError(f"{label} must be a list")
    positions: list[Point] = []
    for index, value in enumerate(raw):
        if not isinstance(value, Mapping):
            raise NativeCatalogError(f"{label}[{index}] must be an object")
        positions.append(_point(value.get("position"), f"{label}[{index}].position"))
    return tuple(positions)


def _encounter_buildings(
    raw: Any,
    label: str,
) -> tuple[NativeEncounterBuilding, ...]:
    if not isinstance(raw, list):
        raise NativeCatalogError(f"{label} must be a list")
    values: list[NativeEncounterBuilding] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise NativeCatalogError(f"{label}[{index}] must be an object")
        values.append(
            NativeEncounterBuilding(
                width=_positive_int(item.get("width"), f"{label}[{index}].width"),
                height=_positive_int(item.get("height"), f"{label}[{index}].height"),
                interaction=_nonnegative_int(
                    item.get("interaction"), f"{label}[{index}].interaction"
                ),
                position=_point(item.get("position"), f"{label}[{index}].position"),
            )
        )
    return tuple(values)


def _encounter_pickups(
    raw: Any,
    label: str,
) -> tuple[NativeEncounterPickup, ...]:
    if not isinstance(raw, list):
        raise NativeCatalogError(f"{label} must be a list")
    values: list[NativeEncounterPickup] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise NativeCatalogError(f"{label}[{index}] must be an object")
        values.append(
            NativeEncounterPickup(
                position=_point(item.get("position"), f"{label}[{index}].position"),
                optional=_boolean(item.get("isOptional"), f"{label}[{index}].isOptional"),
                can_be_hole=_boolean(item.get("canBeHole"), f"{label}[{index}].canBeHole"),
            )
        )
    return tuple(values)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise NativeCatalogError(f"{label} must be boolean")
    return value


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise NativeCatalogError(f"{label} must be a positive number")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise NativeCatalogError(f"{label} must be positive")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NativeCatalogError(f"{label} must be a non-negative integer")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _add_unique(target: dict[str, Any], key: str, value: Any, label: str) -> None:
    if key in target:
        raise NativeCatalogError(f"duplicate native {label} name: {key}")
    target[key] = value
