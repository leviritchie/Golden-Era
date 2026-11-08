#!/usr/bin/env python3
"""Fail-closed static preflight for Olden Session.Loader map-load hang classes.

Known hang signatures (extensible checklist)
--------------------------------------------
1. ``orphan_meta_logic_without_objectconfig``
   Meta catalogs (``resources.json``, ``resources_camps.json``, chest catalogs)
   list logic ids that Session.Loader resolves as map-object SIDs. Missing
   ObjectConfig → ArgumentNullException → Loader retry forever.
2. ``orphan_homm3_xfp_logic``
   Exact-footprint historically cloned ``homm3_xfp_*`` logic rows without keeping
   matching ObjectConfig. Same Meta null hang when those ids sit in Meta catalogs;
   elsewhere they are dead hang fuel if reintroduced into Meta content lists.
3. ``camp_fire_variant_missing_objectconfig``
   ``resources_camps.json`` keys ``camp_fire_1/2/3`` while native ObjectConfig only
   defines ``camp_fire``. Requires aliases upserted into ``3_resources.json``
   (Loader Meta / MapObjects resource dict; side-file-only aliases are insufficient).
4. ``map_emits_meta_random_res``
   Campaign maps that emit Meta ``random-res`` resolve against ``resources.json`` ∪
   ``resources_camps.json``. Even with camp_fire aliases, Steadwick-scale counts
   (tens of pickups) still hit ``MapObjects.opn(null)`` → Loader retry. Emit concrete
   ``resource_*`` instead (HoMM3 random resource is one-shot, not weekly Meta).
5. ``map_sid_missing_objectconfig``
   Emitted map object group SIDs must resolve against effective Core
   (stock Core.zip ∪ overlay members after merge-later-wins policy).
6. ``storyhub_owner_missing_side``
   Map ``propSpawns.owner`` values (non-neutral) must be covered by a StoryHub
   mission Player/Bot ``spawns`` entry; missing Bot leaves cities unbound → Loader retry.
7. ``storyhub_ai_script_empty``
   Difficulty ``ai.script`` empty → Config id \"\" not found → fjl NRE → Loader leak.
8. ``dual_maps_story_maps_install``
   Same mapSid under both ``maps/`` and ``maps/Story_maps/`` registers QuestScript
   twice (day briefings / map Dialogs fire ×2).
9. ``map_city_construction_sid_missing``
   ``propCities.buildingsConstructionSid`` must exist in Core
   ``DB/buildings_constructions/*.json`` after id-keyed overlay merge. Whole-file
   later-wins across Good2 mission overlays previously dropped Steadwick rows when
   Tunnels installed last → Loader ``Config with id ... was not found`` and map-object
   init fallout.
10. ``map_city_garrison_squad_sid_missing``
    City ``propRandomSquads`` ``*_town_garrison_*`` SIDs must exist under
    ``DB/squads/squads_custom_maps/``. A stale ``homecoming_town_garrison_*``
    prefix (MISSION_ID default leak after layered merge) points at missing overlays
    so town defenders never resolve.
10b. ``map_human_city_fightable_garrison``
    Human-owned cities (City ``propSpawns`` spawnType=0 or ``propOwners`` matching
    the human seat) must keep empty ``propRandomSquads.sids``. Fightable town
    garrison binds are the neutral-capture path and block starting ownership.
11. ``map_random_item_rarity_out_of_range``
    ``propRandomItems.rarity`` must be Hex.Configs.ERarity ``0..3``
    (Common/Rare/Epic/Legendary). Emit policy
    ``homm3_rarity_bin_to_olden_erarity_v1`` bins HoMM ``0/1/2→1``, ``3→2``,
    ``4→3`` and never emits ``4``. A raw ``4`` makes ``RandomItemsPool.bfou``
    return null → ``MapObjects.opn(null)`` → Loader ``OnScenesLoaded`` retry.
12. ``lockit_sid_missing_from_lang_array``
    Quest ``name``/``desc`` and dialog ``localization:true`` slides resolve LocKit
    SIDs from Lang ``array`` (tokens-only is insufficient). Missing rows render as
    player-visible ``Loc:`` / ``LOC:`` placeholders.
13. ``map_quest_counter_sid_missing``
    Chunk-3 quest ``CounterSet``/``CounterPlus``/``CounterMinus``/``Counter``/
    ``CounterEqualityInDays`` SIDs must exist in chunk-3 ``counters[].sid``.
    Pack-suffix drift (``{slug}_ab_sod_started`` vs declared ``{slug}_started``)
    surfaces as runtime ``counter … dont found`` on briefing StartTurn.
14. ``storyhub_spawn_missing_on_map``
    StoryHub Player/Bot ``spawns`` owners must exist on the map (inverse of
    ``storyhub_owner_missing_side``). Orphan StoryHub sides → SpawnsCreator /
    side-binding faults.

Proof boundary: source/static + installed-payload validated. Runtime Loader
behavior and clickability remain user-unvalidated.
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

# Meta content lists whose row ids are resolved as map-object SIDs by Loader/Meta.
META_MAP_OBJECT_LOGIC_MEMBERS: tuple[str, ...] = (
    "DB/objects_logic/res/resources.json",
    "DB/objects_logic/res/resources_camps.json",
    "DB/objects_logic/chests/chests.json",
    "DB/objects_logic/chests/camp_fire.json",
    "DB/objects_logic/chests/scroll_box.json",
    "DB/objects_logic/chests/enchanted_scroll_box.json",
    "DB/objects_logic/chests/mythic_scroll_box.json",
    "DB/objects_logic/chests/pandora_box.json",
)

RESOURCES_LOGIC_MEMBER = "DB/objects_logic/res/resources.json"
RESOURCES_CAMPS_LOGIC_MEMBER = "DB/objects_logic/res/resources_camps.json"
CAMP_FIRE_META_ALIAS_IDS: tuple[str, ...] = ("camp_fire_1", "camp_fire_2", "camp_fire_3")
NATIVE_RESOURCE_LOGIC_IDS: tuple[str, ...] = (
    "resource_gold",
    "resource_dust",
    "resource_wood",
    "resource_ore",
    "resource_crystals",
    "resource_mercury",
    "resource_gemstones",
)

MAPS_ROOT_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
STORY_MAPS_REL = MAPS_ROOT_REL / "Story_maps"
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"

# Owners that do not require a StoryHub Player/Bot side binding.
NEUTRAL_OWNERS = frozenset({0, 255})

HANG_SIGNATURES: tuple[dict[str, str], ...] = (
    {
        "id": "orphan_meta_logic_without_objectconfig",
        "summary": "Meta logic catalog id lacks ObjectConfig (Loader Meta null retry)",
    },
    {
        "id": "orphan_homm3_xfp_logic",
        "summary": "homm3_xfp_* objects_logic row without matching ObjectConfig",
    },
    {
        "id": "camp_fire_variant_missing_objectconfig",
        "summary": "camp_fire_1/2/3 logic present without ObjectConfig in 3_resources.json",
    },
    {
        "id": "map_emits_meta_random_res",
        "summary": "Map emits Meta random-res (Loader MapObjects.opn null retry)",
    },
    {
        "id": "map_sid_missing_objectconfig",
        "summary": "Map emits object SID absent from effective Core ObjectConfig",
    },
    {
        "id": "storyhub_owner_missing_side",
        "summary": "Map propSpawns.owner lacks StoryHub Player/Bot spawn coverage",
    },
    {
        "id": "storyhub_ai_script_empty",
        "summary": "StoryHub difficulty ai.script empty (fjl/Loader leak)",
    },
    {
        "id": "dual_maps_story_maps_install",
        "summary": "Same mapSid under maps/ and maps/Story_maps/ (QuestScript ×2)",
    },
    {
        "id": "map_city_construction_sid_missing",
        "summary": "propCities.buildingsConstructionSid absent from Core buildings_constructions",
    },
    {
        "id": "map_city_garrison_squad_sid_missing",
        "summary": "propCities propRandomSquads town_garrison SID absent from Core squad overlays",
    },
    {
        "id": "map_human_city_fightable_garrison",
        "summary": "human-owned city has fightable propRandomSquads (blocks starting ownership)",
    },
    {
        "id": "map_human_city_missing_city_prop_spawn",
        "summary": "human owns cities but meta start is Hero-only (propOwners side-index crash)",
    },
    {
        "id": "map_random_item_rarity_out_of_range",
        "summary": "propRandomItems.rarity outside ERarity 0..3 (RandomItemsPool null → opn retry)",
    },
    {
        "id": "lockit_sid_missing_from_lang_array",
        "summary": "Quest/dialog LocKit SID missing from Lang array (Loc:/LOC: placeholder)",
    },
    {
        "id": "map_quest_counter_sid_missing",
        "summary": "Quest Counter* SID absent from map counters (briefing counter dont found)",
    },
    {
        "id": "storyhub_spawn_missing_on_map",
        "summary": "StoryHub Player/Bot spawn owner absent from map propSpawns/propCities",
    },
    {
        "id": "map_ocean_retired_or_unresolved",
        "summary": "Map ocean uses retired GE tiles 18-22 / waterMap 18, or Core lacks Sand tile 2 / water sand 2",
    },
)

CONCRETE_RESOURCE_SIDS: tuple[str, ...] = tuple(NATIVE_RESOURCE_LOGIC_IDS)
META_RANDOM_RES_SID = "random-res"
# Hex.Configs.ERarity — Common=0, Rare=1, Epic=2, Legendary=3 (no 4th tier).
# Emit policy homm3_rarity_bin_to_olden_erarity_v1 uses {1,2,3} only (OE 0 unused).
VALID_ERARITY_VALUES: frozenset[int] = frozenset({0, 1, 2, 3})
POLICY_EMITTED_ERARITY_VALUES: frozenset[int] = frozenset({1, 2, 3})
LEGENDARY_ERARITY = 3
HOMM3_RARITY_BIN_POLICY = "homm3_rarity_bin_to_olden_erarity_v1"


@dataclass
class PreflightIssue:
    signature: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def format(self) -> str:
        return f"[{self.signature}] {self.message}"


@dataclass
class EffectiveCoreIndex:
    """ObjectConfig + logic catalogs after stock ∪ overlay merge (later wins)."""

    object_config_ids: set[str]
    object_config_members: dict[str, str]
    logic_by_member: dict[str, list[dict[str, Any]]]
    logic_id_to_member: dict[str, str]
    buildings_construction_ids: set[str]
    members_present: set[str]


class CoreZipIndex:
    """Invocation-owned Core reader with one central-directory name index."""

    def __init__(self, core_zip: Path) -> None:
        self.path = Path(core_zip)
        self.archive: zipfile.ZipFile | None = None
        self.names: frozenset[str] = frozenset()

    def __enter__(self) -> "CoreZipIndex":
        if self.archive is not None:
            raise RuntimeError("CoreZipIndex is already open")
        archive = zipfile.ZipFile(self.path, "r")
        try:
            self.names = frozenset(archive.namelist())
        except Exception:
            archive.close()
            raise
        self.archive = archive
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        archive, self.archive = self.archive, None
        self.names = frozenset()
        if archive is not None:
            archive.close()

    def read(self, member: str) -> bytes:
        if self.archive is None:
            raise RuntimeError("CoreZipIndex is not open")
        return self.archive.read(member)

    def __contains__(self, member: str) -> bool:
        if self.archive is None:
            raise RuntimeError("CoreZipIndex is not open")
        return member in self.names


@contextmanager
def _core_zip_scope(
    core_zip: Path, core_index: CoreZipIndex | None
) -> Iterator[CoreZipIndex]:
    if core_index is not None:
        if core_index.path != Path(core_zip) or core_index.archive is None:
            raise ValueError("provided CoreZipIndex must be open for the requested Core.zip")
        yield core_index
        return
    with CoreZipIndex(core_zip) as opened:
        yield opened


@dataclass
class MapSnapshot:
    """One invocation's parsed map container, including a replayable read failure."""

    path: Path
    container: Any = None
    load_failed: bool = False
    load_error: str = ""

    @classmethod
    def load(cls, map_path: Path) -> "MapSnapshot":
        path = Path(map_path)
        try:
            return cls(path=path, container=_read_map_container(path))
        except Exception as exc:  # Preserve per-signature diagnostics at consumers.
            return cls(path=path, load_failed=True, load_error=str(exc))

    def get_container(self) -> Any:
        if self.load_failed:
            raise ValueError(self.load_error)
        return self.container

    def get_map_data(self) -> tuple[Any, dict[str, Any]]:
        container = self.get_container()
        map_data = container.chunks[1]
        if not isinstance(map_data, dict):
            raise ValueError(f"mapData chunk is not an object: {self.path}")
        return container, map_data


def _map_path_cache_key(map_path: Path) -> Path:
    return Path(os.path.normcase(os.path.abspath(map_path)))


def _load_json_bytes(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"))


def _array_rows(doc: Any) -> list[Any]:
    if not isinstance(doc, dict):
        return []
    rows = doc.get("array")
    return rows if isinstance(rows, list) else []


def _try_parse_id_array_catalog(raw: bytes) -> list[dict[str, Any]] | None:
    try:
        doc = _load_json_bytes(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    rows = doc.get("array")
    if not isinstance(rows, list):
        return None
    # Empty catalogs are valid (prior installs may leave empty overlay stubs in Core).
    if not rows:
        return []
    if not all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows):
        return None
    return rows


def merge_id_array_catalog_bytes(base: bytes | None, overlay: bytes) -> bytes:
    """Id-keyed merge for ``{"array":[{"id":...},...]}`` catalogs (later wins per id).

    Fail closed when the overlay is not a well-formed id-array catalog: returning
    ``overlay`` alone would wipe previously merged construction rows.
    """
    overlay_rows = _try_parse_id_array_catalog(overlay)
    if overlay_rows is None:
        raise ValueError(
            "cannot id-merge catalog: overlay is not an id-array JSON object"
        )
    by_id: dict[str, dict[str, Any]] = {}
    if base is not None:
        base_rows = _try_parse_id_array_catalog(base)
        if base_rows is None:
            raise ValueError(
                "cannot id-merge catalog: base is not an id-array JSON object"
            )
        for row in base_rows:
            by_id[str(row["id"])] = row
    for row in overlay_rows:
        by_id[str(row["id"])] = row
    return (
        json.dumps({"array": list(by_id.values())}, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _try_parse_lang_sid_catalog(raw: bytes) -> dict[str, Any] | None:
    try:
        doc = _load_json_bytes(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    has_sid_rows = False
    for key in ("tokens", "array"):
        rows = doc.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        if all(isinstance(row, dict) and isinstance(row.get("sid"), str) for row in rows):
            has_sid_rows = True
        else:
            return None
    return doc if has_sid_rows else None


def merge_lang_sid_catalog_bytes(base: bytes | None, overlay: bytes) -> bytes:
    """SID-keyed merge for Lang text catalogs; mirror overlay sids into tokens+array."""
    overlay_doc = _try_parse_lang_sid_catalog(overlay)
    if overlay_doc is None:
        return overlay
    if base is None:
        merged: dict[str, Any] = {"tokens": [], "array": []}
    else:
        base_doc = _try_parse_lang_sid_catalog(base)
        if base_doc is None:
            return overlay
        merged = {
            "tokens": list(base_doc.get("tokens") or []),
            "array": list(base_doc.get("array") or []),
        }
        for key, value in base_doc.items():
            if key not in ("tokens", "array"):
                merged[key] = value

    overlay_by_sid: dict[str, str] = {}
    for key in ("tokens", "array"):
        for row in overlay_doc.get(key) or []:
            if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                overlay_by_sid[str(row["sid"])] = str(row["text"])
    if not overlay_by_sid:
        return overlay

    for section in ("tokens", "array"):
        rows = list(merged.get(section) or [])
        present = {
            str(row.get("sid")): index
            for index, row in enumerate(rows)
            if isinstance(row, dict) and isinstance(row.get("sid"), str)
        }
        for sid, text in overlay_by_sid.items():
            if sid in present:
                rows[present[sid]]["text"] = text
            else:
                present[sid] = len(rows)
                rows.append({"sid": sid, "text": text})
        merged[section] = rows
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def collect_overlay_members(overlay_roots: Sequence[Path]) -> dict[str, bytes]:
    """Merge DB/ (+ Lang/) files from overlay roots.

    Id-array JSON catalogs merge by ``id`` (later root wins per id).
    Lang text catalogs merge by ``sid`` across ``tokens``/``array``.
    Other files: later root wins wholesale.
    """
    members: dict[str, bytes] = {}
    for overlay_root in overlay_roots:
        if overlay_root is None:
            continue
        root = Path(overlay_root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative.endswith("_overlay_manifest.json"):
                continue
            if relative == "quickStart.json":
                members["DB/quickStart.json"] = path.read_bytes()
                continue
            if not (relative.startswith("DB/") or relative.startswith("Lang/")):
                continue
            raw = path.read_bytes()
            if relative.startswith("Lang/") and relative.endswith(".json"):
                if relative in members:
                    members[relative] = merge_lang_sid_catalog_bytes(members[relative], raw)
                else:
                    members[relative] = merge_lang_sid_catalog_bytes(None, raw)
            elif relative in members and _try_parse_id_array_catalog(raw) is not None:
                members[relative] = merge_id_array_catalog_bytes(members[relative], raw)
            else:
                members[relative] = raw
    return members


def _effective_object_config_ids(
    source: zipfile.ZipFile,
    overlay_members: Mapping[str, bytes],
) -> set[str]:
    """Return ObjectConfig ids after applying overlay replacement semantics."""
    names = {
        name
        for name in source.namelist()
        if name.startswith("DB/map/objects/") and name.endswith(".json")
    }
    names |= {
        name
        for name in overlay_members
        if name.startswith("DB/map/objects/") and name.endswith(".json")
    }
    object_config_ids: set[str] = set()
    for name in sorted(names):
        raw = overlay_members[name] if name in overlay_members else source.read(name)
        for row in _array_rows(_load_json_bytes(raw)):
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                object_config_ids.add(str(row["id"]))
    return object_config_ids


def build_effective_core_index(
    core_zip: Path,
    *,
    overlay_members: Mapping[str, bytes] | None = None,
    core_index: CoreZipIndex | None = None,
) -> EffectiveCoreIndex:
    if not core_zip.is_file():
        raise FileNotFoundError(f"missing Core.zip: {core_zip}")
    overlay = dict(overlay_members or {})
    object_config_ids: set[str] = set()
    object_config_members: dict[str, str] = {}
    logic_by_member: dict[str, list[dict[str, Any]]] = {}
    logic_id_to_member: dict[str, str] = {}
    members_present: set[str] = set()

    with _core_zip_scope(core_zip, core_index) as source:
        names = source.names
        # ObjectConfig: stock then overlay replacements / additions.
        stock_object_docs: dict[str, Any] = {}
        for name in sorted(names):
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            stock_object_docs[name] = _load_json_bytes(source.read(name))
        for name, raw in overlay.items():
            if name.startswith("DB/map/objects/") and name.endswith(".json"):
                stock_object_docs[name] = _load_json_bytes(raw)
        for name, doc in stock_object_docs.items():
            members_present.add(name)
            for row in _array_rows(doc):
                if not isinstance(row, dict):
                    continue
                sid = row.get("id")
                if isinstance(sid, str) and sid:
                    object_config_ids.add(sid)
                    object_config_members[sid] = name

        # Logic catalogs: stock members, replaced wholesale when overlay provides them.
        logic_members = {
            name
            for name in names
            if name.startswith("DB/objects_logic/") and name.endswith(".json")
        }
        logic_members |= {
            name
            for name in overlay
            if name.startswith("DB/objects_logic/") and name.endswith(".json")
        }
        for name in sorted(logic_members):
            if name in overlay:
                doc = _load_json_bytes(overlay[name])
            else:
                doc = _load_json_bytes(source.read(name))
            members_present.add(name)
            rows = [row for row in _array_rows(doc) if isinstance(row, dict)]
            logic_by_member[name] = rows
            for row in rows:
                sid = row.get("id")
                if isinstance(sid, str) and sid:
                    logic_id_to_member[sid] = name

        # Buildings construction presets: id-merge stock ∪ overlay (never wholesale replace).
        buildings_construction_ids: set[str] = set()
        construction_members = {
            name
            for name in names
            if name.startswith("DB/buildings_constructions/") and name.endswith(".json")
        }
        construction_members |= {
            name
            for name in overlay
            if name.startswith("DB/buildings_constructions/") and name.endswith(".json")
        }
        for name in sorted(construction_members):
            members_present.add(name)
            if name in names:
                raw = source.read(name)
            else:
                raw = b'{"array":[]}\n'
            if name in overlay:
                overlay_raw = overlay[name]
                if _try_parse_id_array_catalog(overlay_raw) is not None:
                    raw = merge_id_array_catalog_bytes(
                        raw if name in names else None, overlay_raw
                    )
                else:
                    raw = overlay_raw
            for row in _array_rows(_load_json_bytes(raw)):
                if not isinstance(row, dict):
                    continue
                sid = row.get("id")
                if isinstance(sid, str) and sid:
                    buildings_construction_ids.add(sid)

    return EffectiveCoreIndex(
        object_config_ids=object_config_ids,
        object_config_members=object_config_members,
        logic_by_member=logic_by_member,
        logic_id_to_member=logic_id_to_member,
        buildings_construction_ids=buildings_construction_ids,
        members_present=members_present,
    )


def scrub_orphan_xfp_from_logic_doc(
    doc: dict[str, Any],
    *,
    object_config_ids: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Remove homm3_xfp_* rows that lack a matching ObjectConfig."""
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError("objects_logic document must contain an array")
    kept: list[Any] = []
    removed: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        sid = str(row.get("id") or "")
        if sid.startswith("homm3_xfp_") and sid not in object_config_ids:
            removed.append(sid)
            continue
        kept.append(row)
    if not removed:
        return doc, []
    out = dict(doc)
    out["array"] = kept
    return out, removed


def scrub_orphan_xfp_logic_members(
    source: zipfile.ZipFile,
    overlay_members: dict[str, bytes],
) -> dict[str, list[str]]:
    """Scrub only xfp logic rows without matching effective ObjectConfig."""
    removed_by_member: dict[str, list[str]] = {}
    object_config_ids = _effective_object_config_ids(source, overlay_members)
    logic_names = {
        name
        for name in source.namelist()
        if name.startswith("DB/objects_logic/") and name.endswith(".json")
    }
    logic_names |= {
        name
        for name in overlay_members
        if name.startswith("DB/objects_logic/") and name.endswith(".json")
    }
    for name in sorted(logic_names):
        if name in overlay_members:
            raw = overlay_members[name]
        else:
            raw = source.read(name)
        doc = _load_json_bytes(raw)
        if not isinstance(doc, dict):
            continue
        scrubbed, removed = scrub_orphan_xfp_from_logic_doc(
            doc,
            object_config_ids=object_config_ids,
        )
        if not removed:
            continue
        overlay_members[name] = (
            json.dumps(scrubbed, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        removed_by_member[name] = removed
    return removed_by_member


def check_meta_logic_objectconfig_integrity(
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
) -> None:
    for member in META_MAP_OBJECT_LOGIC_MEMBERS:
        rows = index.logic_by_member.get(member)
        if rows is None:
            if member in (RESOURCES_LOGIC_MEMBER, RESOURCES_CAMPS_LOGIC_MEMBER):
                issues.append(
                    PreflightIssue(
                        "orphan_meta_logic_without_objectconfig",
                        f"effective Core missing required Meta catalog {member}",
                    )
                )
            continue
        for row in rows:
            sid = str(row.get("id") or "")
            if not sid:
                issues.append(
                    PreflightIssue(
                        "orphan_meta_logic_without_objectconfig",
                        f"{member} has a logic row with empty id",
                        {"member": member},
                    )
                )
                continue
            if sid not in index.object_config_ids:
                issues.append(
                    PreflightIssue(
                        "orphan_meta_logic_without_objectconfig",
                        f"{member} id {sid!r} has no ObjectConfig "
                        "(Loader Meta map-object hang)",
                        {"member": member, "sid": sid},
                    )
                )


def check_orphan_xfp_logic(
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
) -> None:
    orphans: list[tuple[str, str]] = []
    for member, rows in sorted(index.logic_by_member.items()):
        for row in rows:
            sid = str(row.get("id") or "")
            if not sid.startswith("homm3_xfp_"):
                continue
            if sid not in index.object_config_ids:
                orphans.append((member, sid))
    if orphans:
        sample = ", ".join(f"{m}:{s}" for m, s in orphans[:8])
        more = "" if len(orphans) <= 8 else f" (+{len(orphans) - 8} more)"
        issues.append(
            PreflightIssue(
                "orphan_homm3_xfp_logic",
                f"found {len(orphans)} orphan homm3_xfp_* logic row(s) without "
                f"ObjectConfig: {sample}{more}",
                {"count": len(orphans), "examples": orphans[:8]},
            )
        )


def check_camp_fire_aliases(
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
) -> None:
    camp_rows = index.logic_by_member.get(RESOURCES_CAMPS_LOGIC_MEMBER) or []
    camp_ids = [str(row.get("id") or "") for row in camp_rows]
    if camp_ids and camp_ids != list(CAMP_FIRE_META_ALIAS_IDS):
        issues.append(
            PreflightIssue(
                "camp_fire_variant_missing_objectconfig",
                f"{RESOURCES_CAMPS_LOGIC_MEMBER} ids must be "
                f"{list(CAMP_FIRE_META_ALIAS_IDS)}; got {camp_ids}",
            )
        )
    for sid in CAMP_FIRE_META_ALIAS_IDS:
        member = index.object_config_members.get(sid)
        if sid not in index.object_config_ids:
            issues.append(
                PreflightIssue(
                    "camp_fire_variant_missing_objectconfig",
                    f"camp variant {sid!r} lacks ObjectConfig "
                    f"(Meta hang; upsert into {NATIVE_CAMP_FIRE_OBJECT_MEMBER})",
                    {"sid": sid},
                )
            )
        elif member != NATIVE_CAMP_FIRE_OBJECT_MEMBER:
            issues.append(
                PreflightIssue(
                    "camp_fire_variant_missing_objectconfig",
                    f"camp variant {sid!r} ObjectConfig must live in "
                    f"{NATIVE_CAMP_FIRE_OBJECT_MEMBER} (found in {member!r}; "
                    "side-file aliases are not enough for MapObjects resource dict)",
                    {"sid": sid, "member": member},
                )
            )


def check_map_meta_random_res(
    map_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed if a campaign map still emits Meta random-res groups."""
    label = map_sid or map_path.stem
    try:
        sids = read_map_object_sids(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_emits_meta_random_res",
                f"failed to read map object SIDs for {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    if META_RANDOM_RES_SID in sids:
        issues.append(
            PreflightIssue(
                "map_emits_meta_random_res",
                f"map {label} emits Meta {META_RANDOM_RES_SID!r}; rewrite to concrete "
                f"resource_* (Loader MapObjects.opn null retry after squads)",
                {"mapSid": label, "sid": META_RANDOM_RES_SID},
            )
        )


def _read_map_container(map_path: Path) -> Any:
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    import port_homecoming_poc as poc_mod  # noqa: WPS433

    return poc_mod.read_olden_map_container(map_path)


def _read_map_data(
    map_path: Path, *, snapshot: MapSnapshot | None = None
) -> tuple[Any, dict[str, Any]]:
    if snapshot is not None:
        return snapshot.get_map_data()
    container = _read_map_container(map_path)
    map_data = container.chunks[1]
    if not isinstance(map_data, dict):
        raise ValueError(f"mapData chunk is not an object: {map_path}")
    return container, map_data


def check_map_random_item_rarity(
    map_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed if propRandomItems.rarity is outside Hex.Configs.ERarity 0..3.

    Emit policy ``homm3_rarity_bin_to_olden_erarity_v1`` never writes 4 (or values
    outside 0..3). OE 0 is engine-legal but unused by that policy.
    """
    label = map_sid or map_path.stem
    try:
        _container, map_data = _read_map_data(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_random_item_rarity_out_of_range",
                f"failed to read map for random-item rarity check {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    props = map_data.get("objectsProperties") or {}
    if not isinstance(props, dict):
        return
    bad: list[dict[str, Any]] = []
    for row in props.get("propRandomItems") or []:
        if not isinstance(row, dict):
            continue
        rarity = row.get("rarity")
        if not isinstance(rarity, int) or rarity not in VALID_ERARITY_VALUES:
            bad.append({"id": row.get("id"), "rarity": rarity})
    if bad:
        sample = ", ".join(
            f"id={r.get('id')}:rarity={r.get('rarity')!r}" for r in bad[:8]
        )
        more = "" if len(bad) <= 8 else f" (+{len(bad) - 8} more)"
        issues.append(
            PreflightIssue(
                "map_random_item_rarity_out_of_range",
                f"map {label} has {len(bad)} propRandomItems rarity value(s) outside "
                f"ERarity {{0,1,2,3}} (emit policy {HOMM3_RARITY_BIN_POLICY} bins "
                f"HoMM 0/1/2→1, 3→2, 4→3 and must not emit 4): {sample}{more} "
                "(RandomItemsPool.bfou → MapObjects.opn(null) Loader retry)",
                {"mapSid": label, "count": len(bad), "examples": bad[:8]},
            )
        )


def _campaign_ocean_module() -> Any:
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    import campaign_ocean  # noqa: WPS433

    return campaign_ocean


def check_core_ocean_tables(
    core_path: Path,
    *,
    issues: list[PreflightIssue],
    core_index: CoreZipIndex | None = None,
) -> None:
    """The Core's own DB/map tables must resolve the campaign ocean (tile 2 Sand, water 2 water sand)."""
    ocean = _campaign_ocean_module()
    try:
        if core_index is None:
            errors = ocean.core_zip_ocean_errors(core_path)
        else:
            if core_index.path != Path(core_path) or core_index.archive is None:
                raise ValueError("provided CoreZipIndex must be open for the requested Core.zip")
            errors = ocean.core_archive_ocean_errors(
                core_index.archive, label=str(core_path)
            )
    except Exception as exc:  # noqa: BLE001
        errors = [f"failed to read Core ocean tables from {core_path}: {exc}"]
    for error in errors:
        issues.append(
            PreflightIssue("map_ocean_retired_or_unresolved", error, {"corePath": str(core_path)})
        )


def check_map_ocean_representation(
    map_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed on retired Golden Era ocean ids or an off-contract native ocean basin."""
    label = map_sid or map_path.stem
    ocean = _campaign_ocean_module()
    try:
        _container, map_data = _read_map_data(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_ocean_retired_or_unresolved",
                f"failed to read map for ocean check {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    for error in ocean.map_ocean_errors(map_data, label=label):
        issues.append(
            PreflightIssue("map_ocean_retired_or_unresolved", error, {"mapSid": label})
        )


def check_native_resources_shape(
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
) -> None:
    rows = index.logic_by_member.get(RESOURCES_LOGIC_MEMBER) or []
    ids = [str(row.get("id") or "") for row in rows]
    if ids != list(NATIVE_RESOURCE_LOGIC_IDS):
        issues.append(
            PreflightIssue(
                "orphan_meta_logic_without_objectconfig",
                f"{RESOURCES_LOGIC_MEMBER} must be exactly native resource_* ids "
                f"{list(NATIVE_RESOURCE_LOGIC_IDS)}; got {ids}",
            )
        )


def read_map_object_sids(
    map_path: Path, *, snapshot: MapSnapshot | None = None
) -> set[str]:
    _container, map_data = _read_map_data(map_path, snapshot=snapshot)
    sids: set[str] = set()
    for group in map_data.get("objects") or []:
        if isinstance(group, dict) and isinstance(group.get("sid"), str):
            sids.add(group["sid"])
    return sids


def read_map_owners(
    map_path: Path, *, snapshot: MapSnapshot | None = None
) -> set[int]:
    _container, map_data = _read_map_data(map_path, snapshot=snapshot)
    props = map_data.get("objectsProperties") or {}
    if not isinstance(props, dict):
        return set()
    owners: set[int] = set()
    for key in ("propSpawns", "propCities"):
        for row in props.get(key) or []:
            if not isinstance(row, dict):
                continue
            owner = row.get("owner")
            if isinstance(owner, int):
                owners.add(owner)
    return owners


def check_map_city_construction_sids(
    map_path: Path,
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed when propCities references missing buildingsConstructionSid rows."""
    label = map_sid or map_path.stem
    try:
        container = snapshot.get_container() if snapshot is not None else _read_map_container(map_path)
        map_data = container.chunks[1]
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_city_construction_sid_missing",
                f"failed to read map for construction SID check {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    if not isinstance(map_data, dict):
        issues.append(
            PreflightIssue(
                "map_city_construction_sid_missing",
                f"mapData chunk is not an object: {label}",
            )
        )
        return
    props = map_data.get("objectsProperties") or {}
    rows = props.get("propCities") if isinstance(props, dict) else None
    if not isinstance(rows, list):
        return
    missing: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("buildingsConstructionSid")
        if not isinstance(sid, str) or not sid:
            continue
        if sid not in index.buildings_construction_ids:
            missing.append(sid)
    missing = sorted(set(missing))
    if missing:
        sample = missing[:12]
        more = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        issues.append(
            PreflightIssue(
                "map_city_construction_sid_missing",
                f"map {label} propCities buildingsConstructionSid missing from "
                f"Core buildings_constructions: {sample}{more}",
                {"mapSid": label, "missing": missing},
            )
        )


def check_map_human_city_prop_spawn_binding(
    map_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed when human owns towns but none are City propSpawns.

    Campaign ``ObjCity.OnCreate`` assigns ``ownerSide`` from ``propOwners.owner`` as a
    raw ``sides.array`` index. Human spawn-id ``1`` is out of range on solo hubs and
    the wrong Bot side on multi-side hubs. At least one human town must stay on City
    ``propSpawns`` so ``CreateCityOnCampaignSpawn`` sets ``ownerSide`` from side.index.
    Secondary human towns may still use ``propOwners`` (stock t_M shape).
    """
    label = map_sid or map_path.stem
    try:
        container, map_data = _read_map_data(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_human_city_missing_city_prop_spawn",
                f"failed to read map for human city spawn bind check {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    props = map_data.get("objectsProperties") or {}
    if not isinstance(props, dict):
        return
    city_ids = {
        int(row["id"])
        for row in (props.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    if not city_ids:
        return

    human_owners: set[int] = set()
    for row in props.get("propSpawns") or []:
        if isinstance(row, dict) and isinstance(row.get("owner"), int) and row.get("spawnType") == 0:
            human_owners.add(int(row["owner"]))
    if not human_owners:
        return

    human_city_via_owners = sorted(
        int(row["id"])
        for row in (props.get("propOwners") or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and int(row["id"]) in city_ids
        and isinstance(row.get("owner"), int)
        and int(row["owner"]) in human_owners
    )
    human_city_spawn_ids = sorted(
        int(row["id"])
        for row in (props.get("propSpawns") or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and int(row["id"]) in city_ids
        and row.get("spawnPointType") == 0
        and row.get("spawnType") == 0
    )
    if not human_city_via_owners:
        return
    if human_city_spawn_ids:
        return

    meta = getattr(container, "chunks", [None])[0] if container is not None else None
    human_meta = None
    if isinstance(meta, dict):
        for row in ((meta.get("spawns") or {}).get("spawns") or []):
            if isinstance(row, dict) and row.get("spawnType") == 0:
                human_meta = {
                    "isCityDefined": row.get("isCityDefined"),
                    "spawnPointType": row.get("spawnPointType"),
                }
                break

    issues.append(
        PreflightIssue(
            "map_human_city_missing_city_prop_spawn",
            f"map {label} has human-owned cities only via propOwners {human_city_via_owners[:8]} "
            f"with no human City propSpawn; campaign ownerSide uses spawn-id as sides.array "
            f"index (town-entry NRE on solo / wrong Bot on multi)",
            {
                "mapSid": label,
                "humanPropOwnerCityIds": human_city_via_owners,
                "humanMeta": human_meta,
            },
        )
    )


def check_map_city_garrison_squad_sids(
    map_path: Path,
    core_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
    core_index: CoreZipIndex | None = None,
) -> None:
    """Fail closed when city propRandomSquads town_garrison SIDs are missing from Core.

    Catches the MISSION_ID default leak where maps reference homecoming_town_garrison_*
    while overlays were emitted under the real mission prefix.

    Also refuses fightable city random-squad SIDs on human-owned towns. Native owned
    cities keep empty propRandomSquads; binding H3 garrison there blocks starting
    ownership (neutral-capture path).
    """
    label = map_sid or map_path.stem
    try:
        _container, map_data = _read_map_data(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_city_garrison_squad_sid_missing",
                f"failed to read map for town garrison SID check {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    props = map_data.get("objectsProperties") or {}
    if not isinstance(props, dict):
        return
    city_ids = {
        int(row["id"])
        for row in (props.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    if not city_ids:
        return

    human_owners: set[int] = set()
    for row in props.get("propSpawns") or []:
        if not isinstance(row, dict) or not isinstance(row.get("owner"), int):
            continue
        if row.get("spawnType") == 0:
            human_owners.add(int(row["owner"]))
    human_city_ids: set[int] = set()
    for row in props.get("propSpawns") or []:
        if (
            isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and int(row["id"]) in city_ids
            and row.get("spawnType") == 0
        ):
            human_city_ids.add(int(row["id"]))
    for row in props.get("propOwners") or []:
        if (
            isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and int(row["id"]) in city_ids
            and isinstance(row.get("owner"), int)
            and int(row["owner"]) in human_owners
        ):
            human_city_ids.add(int(row["id"]))

    blocked: list[dict[str, object]] = []
    for row in props.get("propRandomSquads") or []:
        if not isinstance(row, dict) or row.get("id") not in human_city_ids:
            continue
        sids = row.get("sids") or []
        if isinstance(sids, list) and sids:
            blocked.append({"id": int(row["id"]), "sids": list(sids)})
    if blocked:
        sample = blocked[:8]
        more = "" if len(blocked) <= 8 else f" (+{len(blocked) - 8} more)"
        issues.append(
            PreflightIssue(
                "map_human_city_fightable_garrison",
                f"map {label} human-owned cities must keep empty propRandomSquads.sids; "
                f"fightable town_garrison binds block starting ownership: {sample}{more}",
                {"mapSid": label, "blocked": blocked},
            )
        )

    referenced: list[str] = []
    for row in props.get("propRandomSquads") or []:
        if not isinstance(row, dict) or row.get("id") not in city_ids:
            continue
        for sid in row.get("sids") or []:
            if isinstance(sid, str) and "town_garrison" in sid:
                referenced.append(sid)
    if not referenced:
        return
    try:
        if core_index is not None:
            if core_index.path != Path(core_path) or core_index.archive is None:
                raise ValueError("provided CoreZipIndex must be open for the requested Core.zip")
            members = core_index.names
        else:
            with CoreZipIndex(core_path) as core:
                members = core.names
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_city_garrison_squad_sid_missing",
                f"failed to open Core.zip for town garrison SID check: {exc}",
                {"corePath": str(core_path)},
            )
        )
        return
    missing: list[str] = []
    for sid in sorted(set(referenced)):
        needle = f"/{sid}.json"
        if not any(name.endswith(needle) or name.endswith(f"{sid}.json") for name in members):
            missing.append(sid)
    if missing:
        sample = missing[:12]
        more = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        issues.append(
            PreflightIssue(
                "map_city_garrison_squad_sid_missing",
                f"map {label} city propRandomSquads town_garrison SID(s) missing from "
                f"Core squad overlays: {sample}{more}",
                {"mapSid": label, "missing": missing},
            )
        )


def check_map_sids_resolve(
    map_path: Path,
    index: EffectiveCoreIndex,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    label = map_sid or map_path.stem
    try:
        sids = read_map_object_sids(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001 — fail-closed with context
        issues.append(
            PreflightIssue(
                "map_sid_missing_objectconfig",
                f"failed to read map object SIDs for {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    missing = sorted(sid for sid in sids if sid not in index.object_config_ids)
    if missing:
        sample = missing[:12]
        more = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        issues.append(
            PreflightIssue(
                "map_sid_missing_objectconfig",
                f"map {label} references ObjectConfig-missing SID(s): "
                f"{sample}{more}",
                {"mapSid": label, "missing": missing},
            )
        )


def storyhub_bound_owners(sides: Sequence[Any]) -> set[int]:
    bound: set[int] = set()
    for side in sides:
        if not isinstance(side, dict):
            continue
        if side.get("type") not in ("Player", "Bot"):
            continue
        for spawn in side.get("spawns") or []:
            if isinstance(spawn, int):
                bound.add(spawn)
    return bound


def check_storyhub_owner_coverage(
    *,
    map_path: Path,
    mission: Mapping[str, Any],
    issues: list[PreflightIssue],
    mission_label: str,
    snapshot: MapSnapshot | None = None,
) -> None:
    rows = mission.get("array") if isinstance(mission.get("array"), list) else []
    if not rows:
        issues.append(
            PreflightIssue(
                "storyhub_owner_missing_side",
                f"{mission_label} mission payload missing array[0]",
            )
        )
        return
    variant = (rows[0].get("variants") or [{}])[0]
    if not isinstance(variant, dict):
        issues.append(
            PreflightIssue(
                "storyhub_owner_missing_side",
                f"{mission_label} variant missing",
            )
        )
        return
    bound = storyhub_bound_owners(variant.get("sides") or [])
    try:
        owners = read_map_owners(map_path, snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "storyhub_owner_missing_side",
                f"failed to read map owners for {mission_label}: {exc}",
            )
        )
        return
    required = sorted(owner for owner in owners if owner not in NEUTRAL_OWNERS)
    missing = [owner for owner in required if owner not in bound]
    if missing:
        issues.append(
            PreflightIssue(
                "storyhub_owner_missing_side",
                f"{mission_label}: map owners {missing} lack StoryHub Player/Bot "
                f"spawns (bound={sorted(bound)}; Loader retry risk)",
                {
                    "mission": mission_label,
                    "missingOwners": missing,
                    "boundOwners": sorted(bound),
                    "mapOwners": required,
                },
            )
        )
    orphan_sides = sorted(owner for owner in bound if owner not in owners)
    if orphan_sides:
        issues.append(
            PreflightIssue(
                "storyhub_spawn_missing_on_map",
                f"{mission_label}: StoryHub spawns {orphan_sides} missing from map "
                f"owners (map={required}; SpawnsCreator/side bind risk)",
                {
                    "mission": mission_label,
                    "orphanSpawns": orphan_sides,
                    "boundOwners": sorted(bound),
                    "mapOwners": required,
                },
            )
        )


def check_map_quest_counter_sid_consistency(
    map_path: Path,
    *,
    issues: list[PreflightIssue],
    map_sid: str | None = None,
    snapshot: MapSnapshot | None = None,
) -> None:
    """Fail closed when quest Counter* SIDs are missing from declared counters."""
    import sys

    label = map_sid or map_path.stem
    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    import campaign_runtime_script as campaign_script  # noqa: WPS433

    try:
        container = snapshot.get_container() if snapshot is not None else _read_map_container(map_path)
        chunk3 = container.chunks[3] if len(container.chunks) > 3 else None
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PreflightIssue(
                "map_quest_counter_sid_missing",
                f"failed to read map quest chunk for {label}: {exc}",
                {"mapPath": str(map_path)},
            )
        )
        return
    if not isinstance(chunk3, dict):
        issues.append(
            PreflightIssue(
                "map_quest_counter_sid_missing",
                f"{label}: map chunk3 missing or not an object",
                {"mapPath": str(map_path)},
            )
        )
        return

    counters = chunk3.get("counters") or []
    quests = chunk3.get("quests") or []
    declared = {
        str(row.get("sid"))
        for row in counters
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and row.get("sid")
    }
    referenced = campaign_script.collect_referenced_counter_sids(
        quests if isinstance(quests, list) else []
    )
    missing = sorted(referenced - declared)
    if missing:
        sample = ", ".join(missing[:8])
        more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        issues.append(
            PreflightIssue(
                "map_quest_counter_sid_missing",
                f"{label}: quest Counter* SID(s) missing from counters: {sample}{more}",
                {
                    "mapSid": label,
                    "missing": missing,
                    "declaredStarted": sorted(
                        sid for sid in declared if sid.endswith("_started")
                    ),
                },
            )
        )


def check_storyhub_ai_scripts(
    mission: Mapping[str, Any],
    *,
    issues: list[PreflightIssue],
    mission_label: str,
    expect_script: str | None = "campaign_M1",
) -> None:
    rows = mission.get("array") if isinstance(mission.get("array"), list) else []
    if not rows:
        return
    variant = (rows[0].get("variants") or [{}])[0]
    if not isinstance(variant, dict):
        return
    for diff in variant.get("difficulties") or []:
        if not isinstance(diff, dict):
            continue
        index = diff.get("index")
        script = ((diff.get("ai") or {}) if isinstance(diff.get("ai"), dict) else {}).get(
            "script"
        )
        if not isinstance(script, str) or not script.strip():
            issues.append(
                PreflightIssue(
                    "storyhub_ai_script_empty",
                    f"{mission_label} difficulties[{index}].ai.script must be "
                    "non-empty (empty → fjl/Loader leak)",
                )
            )
            continue
        if expect_script is not None and script != expect_script:
            issues.append(
                PreflightIssue(
                    "storyhub_ai_script_empty",
                    f"{mission_label} difficulties[{index}].ai.script must be "
                    f"{expect_script!r}; got {script!r}",
                )
            )


def check_dual_story_maps_install(
    game_root: Path,
    map_sids: Iterable[str],
    *,
    issues: list[PreflightIssue],
) -> None:
    maps_root = game_root / MAPS_ROOT_REL
    story = game_root / STORY_MAPS_REL
    for map_sid in map_sids:
        root_map = maps_root / f"{map_sid}.map"
        root_json = maps_root / f"{map_sid}.json"
        story_map = story / f"{map_sid}.map"
        if (root_map.is_file() or root_json.is_file()) and story_map.is_file():
            issues.append(
                PreflightIssue(
                    "dual_maps_story_maps_install",
                    f"dual mapSid install forbidden for {map_sid}: exists under "
                    "both maps/ and maps/Story_maps/ (QuestScript Dialogs ×2)",
                    {"mapSid": map_sid},
                )
            )


def run_core_integrity_checks(index: EffectiveCoreIndex) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    check_meta_logic_objectconfig_integrity(index, issues=issues)
    check_orphan_xfp_logic(index, issues=issues)
    check_camp_fire_aliases(index, issues=issues)
    check_native_resources_shape(index, issues=issues)
    return issues


def run_installed_campaign_preflight(
    *,
    game_root: Path,
    core_zip: Path | None = None,
    core_index: CoreZipIndex | None = None,
    overlay_members: Mapping[str, bytes] | None = None,
    map_checks: Sequence[dict[str, Any]] = (),
    require_story_maps: bool = True,
) -> list[PreflightIssue]:
    """Run full preflight.

    ``map_checks`` entries:
      - mapSid: str
      - mapPath: Path (optional; defaults to Story_maps/<mapSid>.map)
      - mission: dict (optional StoryHub mission JSON)
      - missionLabel: str
    """
    core_path = core_zip or (game_root / CORE_ZIP_REL)
    if core_index is None:
        if not core_path.is_file():
            raise FileNotFoundError(f"missing Core.zip: {core_path}")
        with CoreZipIndex(core_path) as owned_core:
            return _run_installed_campaign_preflight(
                game_root=game_root,
                core_path=core_path,
                core_index=owned_core,
                overlay_members=overlay_members,
                map_checks=map_checks,
                require_story_maps=require_story_maps,
            )
    return _run_installed_campaign_preflight(
        game_root=game_root,
        core_path=core_path,
        core_index=core_index,
        overlay_members=overlay_members,
        map_checks=map_checks,
        require_story_maps=require_story_maps,
    )


def _run_installed_campaign_preflight(
    *,
    game_root: Path,
    core_path: Path,
    core_index: CoreZipIndex,
    overlay_members: Mapping[str, bytes] | None,
    map_checks: Sequence[dict[str, Any]],
    require_story_maps: bool,
) -> list[PreflightIssue]:
    index = build_effective_core_index(
        core_path, overlay_members=overlay_members, core_index=core_index
    )
    issues = run_core_integrity_checks(index)
    check_core_ocean_tables(core_path, issues=issues, core_index=core_index)

    map_sids: list[str] = []
    map_snapshots: dict[Path, MapSnapshot] = {}
    map_path_uses: Counter[Path] = Counter()
    for row in map_checks:
        map_sid = str(row.get("mapSid") or "")
        if not map_sid:
            continue
        map_path = row.get("mapPath")
        if map_path is None:
            map_path = game_root / STORY_MAPS_REL / f"{map_sid}.map"
        map_path_uses[_map_path_cache_key(Path(map_path))] += 1

    for row in map_checks:
        map_sid = str(row.get("mapSid") or "")
        if not map_sid:
            continue
        map_sids.append(map_sid)
        map_path = row.get("mapPath")
        if map_path is None:
            map_path = game_root / STORY_MAPS_REL / f"{map_sid}.map"
        else:
            map_path = Path(map_path)
        map_key = _map_path_cache_key(map_path)
        map_exists = map_path.is_file()
        if require_story_maps and not map_exists:
            issues.append(
                PreflightIssue(
                    "map_sid_missing_objectconfig",
                    f"Story_maps missing {map_sid}.map at {map_path}",
                    {"mapSid": map_sid},
                )
            )
        elif map_exists:
            snapshot = map_snapshots.get(map_key)
            if snapshot is None:
                snapshot = MapSnapshot.load(map_path)
                map_snapshots[map_key] = snapshot
            check_map_sids_resolve(
                map_path, index, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_meta_random_res(
                map_path, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_random_item_rarity(
                map_path, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_ocean_representation(
                map_path, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_city_construction_sids(
                map_path, index, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_city_garrison_squad_sids(
                map_path,
                core_path,
                issues=issues,
                map_sid=map_sid,
                snapshot=snapshot,
                core_index=core_index,
            )
            check_map_human_city_prop_spawn_binding(
                map_path, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            check_map_quest_counter_sid_consistency(
                map_path, issues=issues, map_sid=map_sid, snapshot=snapshot
            )
            mission = row.get("mission")
            if isinstance(mission, dict):
                label = str(row.get("missionLabel") or map_sid)
                check_storyhub_owner_coverage(
                    map_path=map_path,
                    mission=mission,
                    issues=issues,
                    mission_label=label,
                    snapshot=snapshot,
                )
                check_storyhub_ai_scripts(
                    mission, issues=issues, mission_label=label
                )

        remaining_uses = map_path_uses[map_key] - 1
        if remaining_uses:
            map_path_uses[map_key] = remaining_uses
        else:
            map_path_uses.pop(map_key, None)
            map_snapshots.pop(map_key, None)
        snapshot = None

    check_dual_story_maps_install(game_root, map_sids, issues=issues)
    mission_ids = [
        str(row.get("missionId") or "").strip()
        for row in map_checks
        if str(row.get("missionId") or "").strip()
    ]
    issues.extend(
        check_installed_campaign_lockit_sids(
            core_path,
            mission_ids=mission_ids or None,
            core_index=core_index,
        )
    )
    return issues


ROE_CASTLE_LOCKIT_MISSION_IDS: tuple[str, ...] = (
    "homecoming",
    "guardian_angels",
    "griffin_cliff",
    "steadwick_liberation",
    "deal_with_the_devil",
    "neutral_affairs",
    "tunnels_and_troglodytes",
)


def _lang_array_sids(doc: Any) -> set[str]:
    sids: set[str] = set()
    if not isinstance(doc, dict):
        return sids
    for row in doc.get("array") or []:
        if isinstance(row, dict) and isinstance(row.get("sid"), str):
            text = row.get("text")
            # Empty string is a valid intentional blank dialog title (narration /
            # unresolved speaker). Only LOC: placeholders and non-strings are absent.
            if isinstance(text, str) and not text.startswith("LOC:"):
                sids.add(str(row["sid"]))
    return sids


def check_installed_campaign_lockit_sids(
    core_zip: Path,
    *,
    mission_ids: Sequence[str] | None = None,
    core_index: CoreZipIndex | None = None,
) -> list[PreflightIssue]:
    """Fail closed when installed hubs reference LocKit SIDs missing from Lang array.

    Runtime resolves quest/dialog localization from the ``array`` section. Tokens-only
    rows (historically emitted for non-Homecoming briefings) still present as Loc:.
    Only missions with installed StoryHub mission JSON and/or dialog DB members are
    checked, so a Good1-only install does not require Good2 Loc rows.
    """
    issues: list[PreflightIssue] = []
    if not core_zip.is_file():
        return issues
    requested = [
        mid.strip()
        for mid in (mission_ids or ROE_CASTLE_LOCKIT_MISSION_IDS)
        if isinstance(mid, str) and mid.strip()
    ]
    if not requested:
        requested = list(ROE_CASTLE_LOCKIT_MISSION_IDS)

    with _core_zip_scope(core_zip, core_index) as source:
        names = source.names
        custom_maps = (
            _load_json_bytes(source.read("Lang/english/texts/customMaps.json"))
            if "Lang/english/texts/customMaps.json" in names
            else {}
        )
        dialogues = (
            _load_json_bytes(source.read("Lang/english/texts/dialogues.json"))
            if "Lang/english/texts/dialogues.json" in names
            else {}
        )
        custom_sids = _lang_array_sids(custom_maps)
        dialog_sids = _lang_array_sids(dialogues)

        for mission_id in requested:
            mission_members = [
                name
                for name in names
                if name.endswith(f"/missions/homm3_roe_castle_{mission_id}.json")
            ]
            dialog_members = sorted(
                name
                for name in names
                if name.startswith("DB/dialogs/dialogs/custom_maps/")
                and name.endswith(".json")
                and f"/{mission_id}_" in name.replace("\\", "/")
            )
            if not mission_members and not dialog_members:
                continue

            for sid in (
                f"{mission_id}_intro",
                f"{mission_id}_main_goal",
                f"{mission_id}_main_goal_obj_1",
            ):
                if sid not in custom_sids:
                    issues.append(
                        PreflightIssue(
                            "lockit_sid_missing_from_lang_array",
                            f"customMaps.json array missing quest LocKit SID {sid}",
                            {"missionId": mission_id, "sid": sid, "file": "customMaps.json"},
                        )
                    )

            for member in dialog_members:
                doc = _load_json_bytes(source.read(member))
                for row in _array_rows(doc):
                    if not isinstance(row, dict):
                        continue
                    dialog_id = str(row.get("id") or "")
                    if not dialog_id:
                        continue
                    if dialog_id == "homecoming_intro_dialog":
                        title_sid = "dialogue_title_homecoming_intro"
                        text_sid = "dialogue_text_homecoming_intro_0"
                    else:
                        title_sid = f"dialogue_title_{dialog_id}"
                        text_sid = f"dialogue_text_{dialog_id}_0"
                    for sid in (title_sid, text_sid):
                        if sid not in dialog_sids:
                            issues.append(
                                PreflightIssue(
                                    "lockit_sid_missing_from_lang_array",
                                    f"dialogues.json array missing {sid} for {member}",
                                    {
                                        "missionId": mission_id,
                                        "sid": sid,
                                        "file": "dialogues.json",
                                        "dialogMember": member,
                                    },
                                )
                            )
    return issues


def format_issues(issues: Sequence[PreflightIssue]) -> str:
    if not issues:
        return "map load preflight OK"
    lines = ["map load preflight FAILED:"]
    for issue in issues:
        lines.append(f"- {issue.format()}")
    return "\n".join(lines)


def hang_signature_checklist() -> list[dict[str, str]]:
    return [dict(row) for row in HANG_SIGNATURES]


CAMP_FIRE_META_ALIASES_MEMBER = "DB/map/objects/homm3_camp_fire_meta_aliases.json"
NATIVE_CAMP_FIRE_OBJECT_MEMBER = "DB/map/objects/3_resources.json"
HOMM3_BOAT_SID = "homm3_boat"
HOMM3_SEER_HUT_SID = "homm3_seer_hut"
HOMM3_CUSTOM_OBJECTS_MEMBER = "DB/map/objects/homecoming_custom_objects.json"
HOMM3_BOAT_INTERACT_DONOR_PREFAB = "interactive/autumn_well"
HOMM3_SEER_HUT_INTERACT_DONOR_PREFAB = "interactive/wise_owl"


def build_camp_fire_rows_from_donor(donor: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid in CAMP_FIRE_META_ALIAS_IDS:
        row = json.loads(json.dumps(donor, ensure_ascii=False))
        row["id"] = sid
        rows.append(row)
    return rows


def build_camp_fire_meta_alias_object_bytes(source: zipfile.ZipFile) -> bytes:
    """Legacy side-file alias bytes (kept for overlay compatibility; prefer 3_resources upsert)."""
    resources = _load_json_bytes(source.read(NATIVE_CAMP_FIRE_OBJECT_MEMBER))
    donor = next(
        (
            row
            for row in _array_rows(resources)
            if isinstance(row, dict) and row.get("id") == "camp_fire"
        ),
        None,
    )
    if donor is None:
        raise ValueError(f"{NATIVE_CAMP_FIRE_OBJECT_MEMBER} missing native camp_fire ObjectConfig")
    return (
        json.dumps({"array": build_camp_fire_rows_from_donor(donor)}, indent=2, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def upsert_camp_fire_aliases_into_resources_object(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> list[str]:
    """Upsert camp_fire_1/2/3 into DB/map/objects/3_resources.json (Loader resource dict)."""
    if RESOURCES_CAMPS_LOGIC_MEMBER not in source.namelist():
        raise FileNotFoundError(RESOURCES_CAMPS_LOGIC_MEMBER)
    camps = _load_json_bytes(source.read(RESOURCES_CAMPS_LOGIC_MEMBER))
    camp_ids = [
        str(row.get("id") or "")
        for row in _array_rows(camps)
        if isinstance(row, dict)
    ]
    if camp_ids != list(CAMP_FIRE_META_ALIAS_IDS):
        raise ValueError(
            f"{RESOURCES_CAMPS_LOGIC_MEMBER} must define ids {list(CAMP_FIRE_META_ALIAS_IDS)}; "
            f"got {camp_ids}"
        )
    if NATIVE_CAMP_FIRE_OBJECT_MEMBER in overlay_members:
        resources = _load_json_bytes(overlay_members[NATIVE_CAMP_FIRE_OBJECT_MEMBER])
    else:
        resources = _load_json_bytes(source.read(NATIVE_CAMP_FIRE_OBJECT_MEMBER))
    if not isinstance(resources, dict):
        raise ValueError(f"{NATIVE_CAMP_FIRE_OBJECT_MEMBER} must be an object")
    rows = resources.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{NATIVE_CAMP_FIRE_OBJECT_MEMBER} must contain an array")
    donor = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and row.get("id") == "camp_fire"
        ),
        None,
    )
    if donor is None:
        raise ValueError(f"{NATIVE_CAMP_FIRE_OBJECT_MEMBER} missing native camp_fire ObjectConfig")
    alias_by_id = {row["id"]: row for row in build_camp_fire_rows_from_donor(donor)}
    kept = [
        row
        for row in rows
        if not (isinstance(row, dict) and row.get("id") in alias_by_id)
    ]
    kept.extend(alias_by_id[sid] for sid in CAMP_FIRE_META_ALIAS_IDS)
    resources["array"] = kept
    overlay_members[NATIVE_CAMP_FIRE_OBJECT_MEMBER] = (
        json.dumps(resources, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    # Clear legacy side-file so it cannot override 3_resources membership in the index.
    overlay_members[CAMP_FIRE_META_ALIASES_MEMBER] = b'{"array": []}\n'
    return list(CAMP_FIRE_META_ALIAS_IDS)


def expand_meta_random_res_in_map_data(map_data: dict[str, Any]) -> int:
    """Rewrite Meta random-res groups into concrete resource_* groups. Returns expanded count.

    Also converts leftover Meta ``propResources`` rows for those IDs into vanilla
    ``propResParams`` (value=0). Native Story maps never keep propResources on
    concrete resource_* instances.
    """
    objects = map_data.get("objects")
    if not isinstance(objects, list):
        return 0
    expanded = 0
    expanded_ids: set[int] = set()
    new_objects: list[Any] = []
    for group in objects:
        if not isinstance(group, dict) or group.get("sid") != META_RANDOM_RES_SID:
            new_objects.append(group)
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        if not (
            isinstance(ids, list)
            and isinstance(nodes, list)
            and isinstance(rotations, list)
            and isinstance(levels, list)
            and len(ids) == len(nodes) == len(rotations) == len(levels)
        ):
            raise ValueError(
                f"{META_RANDOM_RES_SID} group has mismatched ids/nodes/rotations/levels"
            )
        buckets: dict[str, dict[str, list[Any]]] = {
            sid: {"ids": [], "nodes": [], "rotations": [], "levels": []}
            for sid in CONCRETE_RESOURCE_SIDS
        }
        for i, object_id in enumerate(ids):
            sid = CONCRETE_RESOURCE_SIDS[int(object_id) % len(CONCRETE_RESOURCE_SIDS)]
            buckets[sid]["ids"].append(object_id)
            buckets[sid]["nodes"].append(nodes[i])
            buckets[sid]["rotations"].append(rotations[i])
            buckets[sid]["levels"].append(levels[i])
            expanded += 1
            if isinstance(object_id, int):
                expanded_ids.add(object_id)
        for sid in CONCRETE_RESOURCE_SIDS:
            bucket = buckets[sid]
            if not bucket["ids"]:
                continue
            new_objects.append(
                {
                    "sid": sid,
                    "ids": bucket["ids"],
                    "nodes": bucket["nodes"],
                    "rotations": bucket["rotations"],
                    "levels": bucket["levels"],
                }
            )
    map_data["objects"] = new_objects
    if expanded_ids:
        _convert_expanded_resource_props(map_data, expanded_ids)
    return expanded


def _convert_expanded_resource_props(map_data: dict[str, Any], expanded_ids: set[int]) -> None:
    props = map_data.get("objectsProperties")
    if not isinstance(props, dict) or not expanded_ids:
        return
    prop_resources = props.get("propResources")
    if not isinstance(prop_resources, list):
        prop_resources = []
    prop_res_params = props.get("propResParams")
    if not isinstance(prop_res_params, list):
        prop_res_params = []
    existing_param_ids = {
        int(row["id"])
        for row in prop_res_params
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    kept_resources: list[Any] = []
    for row in prop_resources:
        if not isinstance(row, dict):
            kept_resources.append(row)
            continue
        rid = row.get("id")
        if not isinstance(rid, int) or rid not in expanded_ids:
            kept_resources.append(row)
            continue
        if rid not in existing_param_ids:
            prop_res_params.append({"type": 0, "id": rid, "value": 0})
            existing_param_ids.add(rid)
    props["propResources"] = kept_resources
    props["propResParams"] = prop_res_params


def scrub_orphan_object_properties(map_data: dict[str, Any]) -> int:
    """Remove object-namespace property rows whose id is absent from objects[].

    Marker-namespace rows (``type=1`` / Zone map-event hosts) live in ``markers[]``
    id space and must not be scrubbed against ``objects[]`` alone. Returns removed
    object-namespace row count.
    """
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    import object_property_namespaces as propns  # noqa: WPS433

    objects = map_data.get("objects")
    props = map_data.get("objectsProperties")
    if not isinstance(objects, list) or not isinstance(props, dict):
        return 0
    removed = propns.scrub_orphan_object_namespace_properties(
        props,
        live_object_ids=propns.live_object_ids(objects),
    )
    markers = map_data.get("markers")
    if isinstance(markers, list):
        removed += propns.scrub_orphan_marker_namespace_properties(
            props,
            live_marker_ids=propns.live_marker_ids(markers),
        )
    return removed


def normalize_object_group_array_lengths(map_data: dict[str, Any]) -> int:
    """Zip-trim ids/nodes/rotations/levels to a common length. Returns groups repaired."""
    objects = map_data.get("objects")
    if not isinstance(objects, list):
        return 0
    repaired = 0
    for group in objects:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        levels = group.get("levels")
        if not all(isinstance(v, list) for v in (ids, nodes, rotations, levels)):
            continue
        n = min(len(ids), len(nodes), len(rotations), len(levels))
        if n == len(ids) == len(nodes) == len(rotations) == len(levels):
            continue
        group["ids"] = list(ids[:n])
        group["nodes"] = list(nodes[:n])
        group["rotations"] = list(rotations[:n])
        group["levels"] = list(levels[:n])
        repaired += 1
    return repaired


def rewrite_map_file_expand_meta_random_res(map_path: Path) -> int:
    """Load an Olden .map, expand random-res → resource_*, write in place. Returns count."""
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    import port_homecoming_poc as poc_mod  # noqa: WPS433

    container = poc_mod.read_olden_map_container(map_path)
    map_data = container.chunks[1]
    if not isinstance(map_data, dict):
        raise ValueError(f"mapData chunk is not an object: {map_path}")
    expanded = expand_meta_random_res_in_map_data(map_data)
    repaired = normalize_object_group_array_lengths(map_data)
    scrubbed = scrub_orphan_object_properties(map_data)
    if expanded or repaired or scrubbed:
        meta = container.chunks[0] if isinstance(container.chunks[0], dict) else {}
        hash_sum = str(meta.get("hashSum") or "")
        poc_mod.write_olden_map_container(map_path, container, hash_sum)
    return expanded


def clamp_prop_random_item_rarities_in_map_data(map_data: dict[str, Any]) -> int:
    """Retired installer clamp — rarity binning lives in the shared generator.

    Policy ``homm3_rarity_bin_to_olden_erarity_v1`` is applied at emit time in
    ``homm3_olden_rarity_bin`` / ``surface_emit.random_artifact_rarity``. This
    helper no longer rewrites map payloads (avoids diverging from the generator).
    Returns 0 always. Kept as a named no-op so older installer call sites can
    drop the import cleanly.
    """
    del map_data  # unused; signature preserved for call-site migration
    return 0


def rewrite_map_file_clamp_random_item_rarity(map_path: Path) -> int:
    """No-op: do not clamp/re-bin installed maps independently of the generator.

    Regenerate maps so ``propRandomItems.rarity`` comes from
    ``homm3_rarity_bin_to_olden_erarity_v1``. Preflight still rejects values
    outside ERarity ``{0,1,2,3}``.
    """
    del map_path
    return 0


def homm3_boat_object_row() -> dict[str, Any]:
    """HoMM3 boat: 1x1 GATE on visit (matches surface_emit; not multi-tile BR body)."""
    return {
        "id": HOMM3_BOAT_SID,
        "tag": "Interact",
        "isInteractable": True,
        "prefs": [HOMM3_BOAT_INTERACT_DONOR_PREFAB],
        "canBeMirrored": False,
        "selectionUiPrefabID": "1x1",
        "pivotX": 0,
        "pivotZ": 0,
        "sizeX": 1,
        "sizeZ": 1,
        "offsetX": 0,
        "offsetZ": 0,
        "nodes": [2],
        "gateInsideObject": True,
        "generatorConfig": {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 0,
            "buildingInteractionLayout": 0,
        },
    }


def _upsert_homecoming_custom_object(
    source: zipfile.ZipFile,
    overlay_members: dict[str, bytes],
    *,
    object_sid: str,
    object_row: dict[str, Any],
) -> bool:
    """Idempotent upsert of one SID into homecoming_custom_objects.json."""
    if HOMM3_CUSTOM_OBJECTS_MEMBER in overlay_members:
        doc = _load_json_bytes(overlay_members[HOMM3_CUSTOM_OBJECTS_MEMBER])
    elif HOMM3_CUSTOM_OBJECTS_MEMBER in source.namelist():
        doc = _load_json_bytes(source.read(HOMM3_CUSTOM_OBJECTS_MEMBER))
    else:
        doc = {"array": []}
    if not isinstance(doc, dict):
        raise ValueError(f"{HOMM3_CUSTOM_OBJECTS_MEMBER} must be an object")
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{HOMM3_CUSTOM_OBJECTS_MEMBER} must contain an array")
    existing = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and row.get("id") == object_sid
        ),
        None,
    )
    changed = existing != object_row
    kept = [
        row
        for row in rows
        if not (isinstance(row, dict) and row.get("id") == object_sid)
    ]
    kept.append(object_row)
    doc["array"] = kept
    overlay_members[HOMM3_CUSTOM_OBJECTS_MEMBER] = (
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return changed


def ensure_homm3_boat_objectconfig(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> bool:
    """Idempotent upsert of homm3_boat into homecoming_custom_objects.json."""
    return _upsert_homecoming_custom_object(
        source,
        overlay_members,
        object_sid=HOMM3_BOAT_SID,
        object_row=homm3_boat_object_row(),
    )


def homm3_seer_hut_object_row() -> dict[str, Any]:
    """HoMM3 Seer's Hut: wise_owl-native 2x2 host; Hex/Lit billboard replaces donor mesh.

    Footprint must match stock wise_owl. Inventing a 3x2 ObjectConfig on a 2x2 interactable
    prefab produced a silent non-spawn (no map-object Init) on Steadwick Liberation.

    Emit classifies this SID as single_gate (see exact_homm3_footprint) so the interact
    GATE aligns to the H3 visit cell instead of BR-placing onto river waterMap.
    """
    return {
        "id": HOMM3_SEER_HUT_SID,
        "tag": "Interact",
        "isInteractable": True,
        "prefs": [HOMM3_SEER_HUT_INTERACT_DONOR_PREFAB],
        "canBeMirrored": False,
        "selectionUiPrefabID": "1x1",
        "pivotX": 0,
        "pivotZ": 0,
        "sizeX": 2,
        "sizeZ": 2,
        "offsetX": 0,
        "offsetZ": 0,
        "nodes": [1, 2, 2, 2],
        "gateInsideObject": True,
        "proceduralEligible": True,
        "generatorConfig": {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 0,
            "buildingInteractionLayout": 0,
        },
    }


HOMM3_INTERACTABLES_MEMBER = "DB/map/objects/4_interactables.json"
HOMM3_SEER_HUT_LOGIC_MEMBER = (
    "DB/objects_logic/event_banks/campaign_objects/homm3_seer_hut.json"
)
HOMM3_BOTTOM_CENTER_GATE_CITY_NODES = [1, 1, 1, 1, 1, 1, 1, 2, 1]
HOMM3_CITY_INTERACTION_LAYOUT_CORNER_LEFT = 1


def _upsert_objectconfig_member(
    source: zipfile.ZipFile,
    overlay_members: dict[str, bytes],
    *,
    member: str,
    object_sid: str,
    object_row: dict[str, Any],
) -> bool:
    if member in overlay_members:
        doc = _load_json_bytes(overlay_members[member])
    elif member in source.namelist():
        doc = _load_json_bytes(source.read(member))
    else:
        doc = {"array": []}
    if not isinstance(doc, dict):
        raise ValueError(f"{member} must be an object")
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain an array")
    existing = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and row.get("id") == object_sid
        ),
        None,
    )
    changed = existing != object_row
    kept = [
        row
        for row in rows
        if not (isinstance(row, dict) and row.get("id") == object_sid)
    ]
    kept.append(object_row)
    doc["array"] = kept
    overlay_members[member] = (
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return changed


def _remove_objectconfig_id(
    source: zipfile.ZipFile,
    overlay_members: dict[str, bytes],
    *,
    member: str,
    object_sid: str,
) -> bool:
    if member in overlay_members:
        doc = _load_json_bytes(overlay_members[member])
    elif member in source.namelist():
        doc = _load_json_bytes(source.read(member))
    else:
        return False
    if not isinstance(doc, dict):
        raise ValueError(f"{member} must be an object")
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain an array")
    kept = [
        row
        for row in rows
        if not (isinstance(row, dict) and row.get("id") == object_sid)
    ]
    if len(kept) == len(rows):
        return False
    doc["array"] = kept
    overlay_members[member] = (
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return True


def ensure_homm3_seer_hut_objectconfig(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> bool:
    """Upsert seer into 4_interactables + a minimal no-op event-bank visit shell.

    ``homecoming_custom_objects.json`` is not sufficient for Interact hosts: Steadwick
    live-negative showed map bytes present but no map-object Init / billboard apply.
    Proven custom interactables (homm3_landon_*) live in 4_interactables.json.

    ObjectConfig alone still yields a scenery (red-circle) adventure cursor. Ship a
    non-empty event-bank using the campaign MovePointsAdditionReward 0 Invisible
    pattern (``homm3_seer_hut_event_bank_doc``). Empty ``rewards: []`` is forbidden —
    Loader ``ObjEventBank`` / ``RewardSetConfig`` IndexOutOfRangeException bricked
    Steadwick map load (live-negative 2026-07-30). QuestScript owns dialog/rewards;
    complete trigger ``EntityActionsOff`` disables this shell after the quest finishes.
    """
    repo_root = Path(__file__).resolve().parents[1]
    poc = repo_root / "experiments" / "campaign_port_poc"
    if str(poc) not in sys.path:
        sys.path.insert(0, str(poc))
    from seer_hut_quest import (  # noqa: WPS433
        homm3_seer_hut_event_bank_doc,
        homm3_seer_hut_object_row as shared_seer_object_row,
    )

    changed = _upsert_objectconfig_member(
        source,
        overlay_members,
        member=HOMM3_INTERACTABLES_MEMBER,
        object_sid=HOMM3_SEER_HUT_SID,
        object_row=shared_seer_object_row(),
    )
    if _remove_objectconfig_id(
        source,
        overlay_members,
        member=HOMM3_CUSTOM_OBJECTS_MEMBER,
        object_sid=HOMM3_SEER_HUT_SID,
    ):
        changed = True
    logic_bytes = (
        json.dumps(homm3_seer_hut_event_bank_doc(), indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    prior = overlay_members.get(HOMM3_SEER_HUT_LOGIC_MEMBER)
    if prior != logic_bytes:
        overlay_members[HOMM3_SEER_HUT_LOGIC_MEMBER] = logic_bytes
        changed = True
    return changed


def seer_hut_core_members_to_delete(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> list[str]:
    """Delete only a broken empty-reward seer event bank if one is still in Core.zip.

    The install overlay now ships a valid no-op bank; do not delete that member.
    """
    del overlay_members  # delete decision is based on source contents only
    if HOMM3_SEER_HUT_LOGIC_MEMBER not in source.namelist():
        return []
    try:
        doc = json.loads(source.read(HOMM3_SEER_HUT_LOGIC_MEMBER).decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return [HOMM3_SEER_HUT_LOGIC_MEMBER]
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        return [HOMM3_SEER_HUT_LOGIC_MEMBER]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for variant in row.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            rewards = (variant.get("rewardSet") or {}).get("rewards")
            if rewards == []:
                return [HOMM3_SEER_HUT_LOGIC_MEMBER]
    return []


def _is_homm3_town_city_object_sid(sid: Any) -> bool:
    if not isinstance(sid, str):
        return False
    return bool(re.fullmatch(r"homm3_(?:landon_)?[a-z0-9]+_city", sid.strip()))


def ensure_homm3_town_bottom_center_gates(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> int:
    """Force every homm3_*_city ObjectConfig onto south-center GATE (index 7).

    CreateCity paints from fractionConfig.city (often stock donor). Stock ships with
    SW GATE index 6; without this normalize, body-center / one-north map emit leaves
    live interact on the town corner.
    """
    if HOMM3_INTERACTABLES_MEMBER in overlay_members:
        doc = _load_json_bytes(overlay_members[HOMM3_INTERACTABLES_MEMBER])
    else:
        doc = _load_json_bytes(source.read(HOMM3_INTERACTABLES_MEMBER))
    if not isinstance(doc, dict):
        raise ValueError(f"{HOMM3_INTERACTABLES_MEMBER} must be an object")
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{HOMM3_INTERACTABLES_MEMBER} must contain an array")
    changed = 0
    for row in rows:
        if not isinstance(row, dict) or not _is_homm3_town_city_object_sid(row.get("id")):
            continue
        size_x = int(row.get("sizeX") or 0)
        size_z = int(row.get("sizeZ") or 0)
        if size_x != 3 or size_z != 3:
            raise ValueError(
                f"homm3 town ObjectConfig {row.get('id')!r} must remain 3x3 for "
                f"bottom-center GATE; got sizeX={size_x} sizeZ={size_z}"
            )
        before = (
            row.get("nodes"),
            row.get("canBeMirrored"),
            row.get("generatorConfig"),
        )
        row["nodes"] = list(HOMM3_BOTTOM_CENTER_GATE_CITY_NODES)
        row["canBeMirrored"] = False
        row["generatorConfig"] = {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 1,
            "buildingLeftBottomZ": size_z - 1,
            "buildingInteractionLayout": HOMM3_CITY_INTERACTION_LAYOUT_CORNER_LEFT,
        }
        after = (
            row.get("nodes"),
            row.get("canBeMirrored"),
            row.get("generatorConfig"),
        )
        if before != after:
            changed += 1
    if changed:
        overlay_members[HOMM3_INTERACTABLES_MEMBER] = (
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    return changed


def apply_loader_hang_core_guards(
    source: zipfile.ZipFile, overlay_members: dict[str, bytes]
) -> dict[str, Any]:
    """Scrub orphan xfp logic, upsert camp_fire_*, and ensure ObjectConfig guards."""
    removed_by_member = scrub_orphan_xfp_logic_members(source, overlay_members)
    if RESOURCES_LOGIC_MEMBER in overlay_members:
        resources_doc = _load_json_bytes(overlay_members[RESOURCES_LOGIC_MEMBER])
    else:
        resources_doc = _load_json_bytes(source.read(RESOURCES_LOGIC_MEMBER))
    resource_ids = [
        str(row.get("id") or "")
        for row in _array_rows(resources_doc)
        if isinstance(row, dict)
    ]
    if resource_ids != list(NATIVE_RESOURCE_LOGIC_IDS):
        raise ValueError(
            f"{RESOURCES_LOGIC_MEMBER} must be exactly native resource_* ids "
            f"{list(NATIVE_RESOURCE_LOGIC_IDS)}; got {resource_ids}"
        )
    camp_ids = upsert_camp_fire_aliases_into_resources_object(source, overlay_members)
    boat_changed = ensure_homm3_boat_objectconfig(source, overlay_members)
    seer_hut_changed = ensure_homm3_seer_hut_objectconfig(source, overlay_members)
    town_gate_changed = ensure_homm3_town_bottom_center_gates(source, overlay_members)
    return {
        "scrubbedOrphanXfpLogicByMember": removed_by_member,
        "scrubbedOrphanXfpLogic": [
            sid for sids in removed_by_member.values() for sid in sids
        ],
        "campFireMetaAliasObjectIds": camp_ids,
        "campFireMetaAliasMember": NATIVE_CAMP_FIRE_OBJECT_MEMBER,
        "ensuredHomm3BoatObjectConfig": boat_changed,
        "ensuredHomm3SeerHutObjectConfig": seer_hut_changed,
        "normalizedHomm3TownBottomCenterGates": town_gate_changed,
    }
