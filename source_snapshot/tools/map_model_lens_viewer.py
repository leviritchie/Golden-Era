#!/usr/bin/env python3
"""Map model lens viewer — inspect what the generator thinks a map contains.

Not an editor. Read-only lenses over generated Olden .map files, plus a
``homm3_source`` preset that paints the decoded HoMM3 Homecoming grid
(tile-object + pathability artifacts from Good-1a.h3m) so you can verify
must-fight / pathing vision against the original map.

Object lenses paint ObjectConfig footprints (occupied / GATE cells), not just
anchors. Pathability uses water domain + occupied footprint cells (Olden) or
the HoMM3 pathability grid (homm3_source preset).

  python tools/map_model_lens_viewer.py
  python tools/map_model_lens_viewer.py --preset raw_translation --lens pathability
  python tools/map_model_lens_viewer.py --preset homm3_source --lens pathability
  python tools/map_model_lens_viewer.py --map artifacts/.../approach_cell.map
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from tkinter import ttk
from typing import Any

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

# Keep imports light: port_homecoming_poc only. Footprint math is inlined so we
# do not pull build_homecoming_single_layer_map (segfaults with tk on this host).
import port_homecoming_poc as poc  # noqa: E402

DEFAULT_ALIGNMENT = (
    REPO
    / "artifacts/campaign_port_poc/homecoming_poc/olden_storage_alignment"
    / "homecoming.olden_storage_alignment.json"
)
ARTIFACT_ROOT = REPO / "artifacts/campaign_port_poc/homecoming_poc"

# raw_translation is the only campaign map generation lane; retired-lane presets
# (approach_cell / layered_atlas) are gone because nothing regenerates those maps.
PRESETS: dict[str, Path | dict[str, Any]] = {
    "raw_translation": REPO
    / "artifacts/campaign_port_poc/homecoming_poc/raw_translation_map/maps"
    / "h3_roe_castle_homecoming_raw_translation.map",
    # Pure HoMM3 source vision (Good-1a.h3m) from decoded grids — not an Olden .map.
    "homm3_source": {
        "kind": "homm3_source",
        "title": "Homecoming — HoMM3 source (Good-1a.h3m)",
        "tileObjectGrid": ARTIFACT_ROOT
        / "tile_object_grid"
        / "homecoming.homm3_surface_80x80_tile_object_grid.json",
        "pathabilityGrid": ARTIFACT_ROOT
        / "pathability_grid"
        / "homecoming.surface_pathability_grid.json",
        "alignment": DEFAULT_ALIGNMENT,
    },
}

SURFACE_W = 80
SURFACE_H = 80
SOURCE_W = 72
SOURCE_H = 72
OFFSET_X = 4
OFFSET_Y = 4
DISPLAY_FLIP_Y = True

# Campaign ocean = native Sand seabed tile 2 + waterMap 2 at levelsMap -1
# (experiments/campaign_port_poc/campaign_ocean.py); a Sand river is the same pair at land level.
OCEAN_TILE_CODE = 2
OCEAN_WATER_MAP_ID = 2
OCEAN_BASIN_LEVEL = -1
OLDEN_MIRRORED_ROTATION = 10
POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS = {
    "dirt_stones_1",
    "flowers_1",
    "flowers_2",
    "fx_map_light",
    "fx_quest_mark_gold_01",
    "fx_quest_mark_silver_01",
    "grass_1",
    "grass_snow_1",
    "grass_stones_1",
    "lava_stones_1",
    "mushrooms_1",
    "mushrooms_2",
    "mushrooms_3",
    "mushrooms_4",
    "snow_stones_1",
    "water_reed_1",
}
HOMM3_BOAT_SID = "homm3_boat"
HOMM3_PATHING_BLOCKER_SID = "homm3_pathing_blocker"
HOMM3_PATHING_VISUAL_SID_PREFIX = "homm3_pathing_visual"

LENSES = [
    ("terrain", "Terrain tiles"),
    ("water", "Water domain (waterMap≠0)"),
    ("levels", "Elevation levelsMap"),
    ("pathability", "Pathable vs blocked (water domain + occupied footprints)"),
    ("objects", "All object footprints"),
    ("interactables", "Towns / dwellings / mines / portals / boats / markers"),
    ("guards", "random-squad / monster stacks"),
    ("mountains", "mountain_* scenery"),
    ("scenery", "Trees / grass / stones / flowers / mushrooms"),
    ("synthetics", "Olden-only id≥900000"),
    ("homm3_source", "HoMM3 source entities (projected)"),
    ("homm3_vs_olden", "HoMM3 vs Olden: match / H3-only / Olden-only"),
    ("spawn_cluster", "Spawn + start city neighborhood"),
    ("must_fight_poi", "Must-fight gated POIs + required packs"),
    ("soft_bypass", "Block parity pads / access repair clears"),
]

VIEWS = [
    ("surface", "Surface (left 80×80)"),
    ("underground", "Underground (right 80×80)"),
]

KIND_PRIORITY = (
    "spawn",
    "town",
    "dwelling",
    "mine",
    "portal",
    "boat",
    "guard",
    "marker",
    "pickup",
    "landon",
    "mountain",
    "scenery",
    "synthetic",
    "other",
)

_CONFIG_CACHE: dict[frozenset[str], dict[str, dict[str, Any]]] = {}


def classify_sid(sid: str) -> str:
    if sid == "hero-spawner":
        return "spawn"
    if "city" in sid or sid.endswith("_city"):
        return "town"
    if "barracks" in sid or "dwelling" in sid:
        return "dwelling"
    if sid.startswith("mine_") or sid == "mine":
        return "mine"
    if "portal" in sid or "subterranean" in sid or "gate" in sid:
        return "portal"
    if "boat" in sid:
        return "boat"
    if "random-squad" in sid or "squad" in sid:
        return "guard"
    if "mountain" in sid:
        return "mountain"
    if "landon_map_event" in sid or "quest_mark" in sid:
        return "marker"
    if any(k in sid for k in ("chest", "artifact", "resource", "pickup", "flotsam", "random-item")):
        return "pickup"
    if any(k in sid for k in ("pine", "tree", "grass", "flower", "mushroom", "stone", "snow", "dirt")):
        return "scenery"
    if sid.startswith("homm3_landon"):
        return "landon"
    return "other"


def classify_h3_category(category: str) -> str:
    c = str(category or "")
    if c == "monster_stack":
        return "guard"
    if c == "town":
        return "town"
    if c in {"external_dwelling", "dwelling"}:
        return "dwelling"
    if c == "mine":
        return "mine"
    if c == "travel_link_candidate":
        return "portal"
    if c == "boat_or_water_travel_object":
        return "boat"
    if c in {
        "artifact_pickup",
        "resource_pickup",
        "interactive_reward_object",
        "map_event",
        "treasure_chest",
        "pickup",
    }:
        return "pickup"
    if c in {"readable_sign_or_bottle", "map_event"}:
        return "marker"
    if c == "hero_or_prison":
        return "spawn"
    if "payloadless" in c:
        return "scenery"
    return "other"


def preset_is_homm3(preset: Path | dict[str, Any]) -> bool:
    return isinstance(preset, dict) and preset.get("kind") == "homm3_source"


PALETTE = {
    "empty": "#1e1e1e",
    "land": "#3d5a3d",
    "water": "#2a4a6a",
    "elevated": "#6a5a3a",
    "spawn": "#ffcc00",
    "town": "#e06060",
    "dwelling": "#c08040",
    "mine": "#a0a040",
    "portal": "#c060c0",
    "boat": "#60c0e0",
    "guard": "#ff4040",
    "mountain": "#705040",
    "marker": "#ffff80",
    "pickup": "#80ff80",
    "scenery": "#508050",
    "landon": "#e09090",
    "other": "#8080a0",
    "synthetic": "#ff80ff",
    "h3": "#40a0ff",
    "match": "#40c040",
    "h3_only": "#4080ff",
    "olden_only": "#ff8040",
    "highlight": "#ffffff",
    "path_land": "#3a8a3a",
    "path_water": "#3a7aaa",
    "blocked_land": "#8a3030",
    "blocked_water": "#603050",
    "path_unknown": "#a08020",
    "gate": "#c0a060",
    "diagonal_squeeze": "#d07020",
    "must_fight_poi": "#ff66aa",
    "must_fight_pack": "#ff2222",
    "seal_pad": "#886622",
    "access_clear": "#44aacc",
    "unenforceable": "#aa44ff",
}


def is_homm3_pathing_visual_sid(sid: str) -> bool:
    return sid.startswith(f"{HOMM3_PATHING_VISUAL_SID_PREFIX}_")


def diagonal_squeeze_corridor_cells(
    blocked: set[int],
    *,
    grid_width: int,
    grid_height: int,
) -> set[int]:
    """Open cells on a diagonal squeeze between two blocked corners.

    Mirrors ``approach_cell.domains.diagonal_squeeze_corridor_cells`` without
    importing that module (tk + layer_atlas is unsafe on this host).
    """
    marks: set[int] = set()
    for node in range(grid_width * grid_height):
        if node in blocked:
            continue
        x = node % grid_width
        y = node // grid_width
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < grid_width and 0 <= ny < grid_height):
                continue
            dest = ny * grid_width + nx
            if dest in blocked:
                continue
            corner_a = y * grid_width + nx
            corner_b = ny * grid_width + x
            if corner_a in blocked and corner_b in blocked:
                marks.add(node)
                marks.add(dest)
    return marks


def overlay_roots() -> list[Path]:
    candidates = [
        ARTIFACT_ROOT / "raw_translation_map" / "core_overlay" / "DB" / "map" / "objects",
        ARTIFACT_ROOT / "approach_cell_handedit_map" / "core_overlay" / "DB" / "map" / "objects",
        ARTIFACT_ROOT / "raw_translation_map" / "core_overlay" / "DB" / "map" / "objects",
    ]
    return [root for root in candidates if root.exists()]


def load_object_configs(sids: set[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    key = frozenset(sids)
    if key in _CONFIG_CACHE:
        return _CONFIG_CACHE[key], []
    configs: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in sids:
                    configs[row["id"]] = row
    for overlay_root in overlay_roots():
        for path in sorted(overlay_root.rglob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            for row in doc.get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in sids:
                    configs[row["id"]] = row
    # Minimal synthetics used by Homecoming maps when Core/overlay lack a row.
    if HOMM3_BOAT_SID in sids and HOMM3_BOAT_SID not in configs:
        configs[HOMM3_BOAT_SID] = {
            "id": HOMM3_BOAT_SID,
            "sizeX": 1,
            "sizeZ": 1,
            "nodes": [1],
            "canBeMirrored": False,
        }
    if HOMM3_PATHING_BLOCKER_SID in sids and HOMM3_PATHING_BLOCKER_SID not in configs:
        configs[HOMM3_PATHING_BLOCKER_SID] = {
            "id": HOMM3_PATHING_BLOCKER_SID,
            "sizeX": 1,
            "sizeZ": 1,
            "nodes": [1],
            "canBeMirrored": False,
        }
    missing = sorted(sids - set(configs))
    _CONFIG_CACHE[key] = configs
    return configs, missing


def resolve_size(sid: str, config: dict[str, Any]) -> tuple[int | None, int | None, str]:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    if isinstance(size_x, int) and isinstance(size_z, int) and size_x > 0 and size_z > 0:
        return size_x, size_z, "native_object_config_size_grid"
    generator_config = config.get("generatorConfig")
    if (
        isinstance(generator_config, dict)
        and isinstance(generator_config.get("buildingSizeX"), int)
        and isinstance(generator_config.get("buildingSizeZ"), int)
    ):
        return (
            int(generator_config["buildingSizeX"]),
            int(generator_config["buildingSizeZ"]),
            "native_generator_building_size_grid",
        )
    if sid in POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS or is_homm3_pathing_visual_sid(sid):
        return 1, 1, "explicit_point_anchor_without_native_size"
    return None, None, "native_config_missing_size_anchor_only"


def footprint_sections(sid: str, config: dict[str, Any], rotation: int) -> list[dict[str, Any]]:
    """Mirror tile_grid.native_grid_sections without importing that module."""
    if sid == HOMM3_PATHING_BLOCKER_SID:
        return [{
            "placedOffset": [0, 0],
            "nodeValue": 1,
            "occupied": True,
            "footprintSource": "pathing_blocker_anchor",
        }]
    size_x, size_z, footprint_source = resolve_size(sid, config)
    if size_x is None or size_z is None:
        return [{
            "placedOffset": [0, 0],
            "nodeValue": None,
            "occupied": False,
            "footprintSource": footprint_source,
        }]
    nodes = config.get("nodes")
    if nodes is not None and (not isinstance(nodes, list) or len(nodes) != size_x * size_z):
        return [{
            "placedOffset": [0, 0],
            "nodeValue": None,
            "occupied": False,
            "footprintSource": "invalid_nodes_grid_anchor_only",
        }]
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and config.get("canBeMirrored") is True
    sections: list[dict[str, Any]] = []
    for config_z in range(size_z):
        for config_x in range(size_x):
            node_value = nodes[config_z * size_x + config_x] if isinstance(nodes, list) else None
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            sections.append({
                "placedOffset": [placed_dx, size_z - 1 - config_z],
                "nodeValue": node_value,
                "occupied": node_value == 1,
                "footprintSource": footprint_source,
            })
    return sections


def pick_kind(kinds: list[str]) -> str:
    for preferred in KIND_PRIORITY:
        if preferred in kinds:
            return preferred
    return kinds[0] if kinds else "other"


class MapModel:
    def __init__(
        self,
        map_path: Path | dict[str, Any],
        alignment_path: Path | None,
    ) -> None:
        if isinstance(map_path, dict) and map_path.get("kind") == "homm3_source":
            self._init_from_homm3(map_path)
            return

        self.source_kind = "olden_map"
        self.map_path = map_path
        container = poc.read_olden_map_container(map_path)
        self.meta = container.chunks[0]
        self.md = container.chunks[1]
        self.width = int(self.md["sizeX_"])
        self.height = int(self.md["sizeZ_"])
        self.tiles = list(self.md.get("tilesMap") or [])
        self.water = list(self.md.get("waterMap") or [])
        self.levels = list(self.md.get("levelsMap") or [])
        self.pathability_override: dict[int, dict[str, Any]] = {}

        self.anchors_at: dict[int, list[tuple[int, str]]] = defaultdict(list)
        self.by_id: dict[int, tuple[str, int, int]] = {}
        instances: list[tuple[int, str, int, int]] = []
        sids: set[str] = set()
        for group in self.md.get("objects") or []:
            sid = str(group.get("sid") or "")
            ids = group.get("ids") or []
            nodes = group.get("nodes") or []
            rotations = group.get("rotations") or []
            for i, (oid, node) in enumerate(zip(ids, nodes)):
                if not isinstance(oid, int) or not isinstance(node, int):
                    continue
                rotation = rotations[i] if i < len(rotations) and isinstance(rotations[i], int) else 0
                self.anchors_at[node].append((oid, sid))
                self.by_id[oid] = (sid, node, rotation)
                instances.append((oid, sid, node, rotation))
                sids.add(sid)

        self.configs, self.missing_configs = load_object_configs(sids)
        self.cover_at: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.blocked_nodes: set[int] = set()
        self.gate_nodes: set[int] = set()
        self.unknown_size_anchors: set[int] = set()
        self.footprint_stats = Counter()
        for oid, sid, anchor_node, rotation in instances:
            config = self.configs.get(sid)
            if config is None:
                self.cover_at[anchor_node].append({
                    "id": oid,
                    "sid": sid,
                    "kind": classify_sid(sid),
                    "anchor": True,
                    "occupied": False,
                    "gate": False,
                    "footprintSource": "missing_object_config",
                    "rotation": rotation,
                    "anchorNode": anchor_node,
                })
                self.unknown_size_anchors.add(anchor_node)
                self.footprint_stats["missing_config"] += 1
                continue
            sections = footprint_sections(sid, config, rotation)
            ax = anchor_node % self.width
            ay = anchor_node // self.width
            painted = 0
            for section in sections:
                dx, dy = section["placedOffset"]
                gx = ax + int(dx)
                gy = ay + int(dy)
                if not (0 <= gx < self.width and 0 <= gy < self.height):
                    continue
                node = gy * self.width + gx
                occupied = section.get("occupied") is True
                gate = section.get("nodeValue") == 2
                source = str(section.get("footprintSource") or "")
                entry = {
                    "id": oid,
                    "sid": sid,
                    "kind": classify_sid(sid),
                    "anchor": node == anchor_node,
                    "occupied": occupied,
                    "gate": gate,
                    "footprintSource": source,
                    "rotation": rotation,
                    "anchorNode": anchor_node,
                    "nodeValue": section.get("nodeValue"),
                }
                self.cover_at[node].append(entry)
                painted += 1
                if occupied:
                    self.blocked_nodes.add(node)
                if gate:
                    self.gate_nodes.add(node)
                if source in {
                    "native_config_missing_size_anchor_only",
                    "invalid_nodes_grid_anchor_only",
                }:
                    self.unknown_size_anchors.add(node)
            if painted == 0:
                self.cover_at[anchor_node].append({
                    "id": oid,
                    "sid": sid,
                    "kind": classify_sid(sid),
                    "anchor": True,
                    "occupied": False,
                    "gate": False,
                    "footprintSource": "empty_footprint_anchor_fallback",
                    "rotation": rotation,
                    "anchorNode": anchor_node,
                })
                self.footprint_stats["empty_footprint"] += 1
            else:
                self.footprint_stats["instanced"] += 1

        self.diagonal_squeeze_nodes = diagonal_squeeze_corridor_cells(
            self.blocked_nodes,
            grid_width=self.width,
            grid_height=self.height,
        )

        self.h3_entities: list[dict[str, Any]] = []
        self.h3_at_olden: dict[int, list[dict[str, Any]]] = defaultdict(list)
        if alignment_path and alignment_path.is_file():
            self._load_alignment(alignment_path)

        self.must_fight_poi_nodes: set[int] = set()
        self.must_fight_pack_nodes: set[int] = set()
        self.block_parity_seal_nodes: set[int] = set()
        self.accessibility_clear_nodes: set[int] = set()
        self._load_must_fight(
            catalogue_path=None,
            map_path=map_path if isinstance(map_path, Path) else None,
        )
        self._load_block_parity_and_access(
            map_path=map_path if isinstance(map_path, Path) else None,
        )

    def _init_from_homm3(self, preset: dict[str, Any]) -> None:
        """Build a surface atlas model from HoMM3 tile-object + pathability grids."""
        tile_path = Path(preset["tileObjectGrid"])
        path_path = Path(preset["pathabilityGrid"])
        if not tile_path.is_file():
            raise FileNotFoundError(f"missing HoMM3 tile-object grid: {tile_path}")
        if not path_path.is_file():
            raise FileNotFoundError(f"missing HoMM3 pathability grid: {path_path}")

        tile_doc = json.loads(tile_path.read_text(encoding="utf-8-sig"))
        path_doc = json.loads(path_path.read_text(encoding="utf-8-sig"))
        tile_rows = tile_doc.get("rows") or []
        path_rows = path_doc.get("rows") or []
        if len(tile_rows) != SURFACE_H or any(len(r) != SURFACE_W for r in tile_rows):
            raise ValueError("HoMM3 tile-object grid must be 80x80 rows")
        if len(path_rows) != SURFACE_H or any(len(r) != SURFACE_W for r in path_rows):
            raise ValueError("HoMM3 pathability grid must be 80x80 rows")

        self.source_kind = "homm3_source"
        self.map_path = tile_path
        self.meta = {
            "title": str(preset.get("title") or "Homecoming — HoMM3 source"),
            "source": "Good1.h3c block 1 / Good-1a.h3m",
        }
        self.md = {"fileMapName": "homm3_source_Good-1a", "objects": []}
        self.width = SURFACE_W * 2
        self.height = SURFACE_H
        cell_count = self.width * self.height
        self.tiles = [0] * cell_count
        self.water = [0] * cell_count
        self.levels = [0] * cell_count
        self.pathability_override: dict[int, dict[str, Any]] = {}
        self.anchors_at = defaultdict(list)
        self.by_id = {}
        self.configs = {}
        self.missing_configs: list[str] = []
        self.cover_at = defaultdict(list)
        self.blocked_nodes = set()
        self.gate_nodes = set()
        self.unknown_size_anchors = set()
        self.footprint_stats = Counter()

        object_index = {
            int(row["id"]): row
            for row in (tile_doc.get("objectIndex") or [])
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }

        for y in range(SURFACE_H):
            for x in range(SURFACE_W):
                node = y * self.width + x
                tcell = tile_rows[y][x]
                pcell = path_rows[y][x]
                terrain = (tcell.get("terrain") or {}).get("projectedOlden") or {}
                self.tiles[node] = int(terrain.get("tilesMap") or 0)
                self.water[node] = int(terrain.get("waterMap") or 0)
                self.levels[node] = int(terrain.get("levelsMap") or 0)

                h3p = pcell.get("homm3") or {}
                domain = str(h3p.get("domain") or "land")
                land_p = bool(h3p.get("landPathable"))
                water_p = bool(h3p.get("waterPathable"))
                blocked = bool(h3p.get("objectBlocked")) or (
                    domain == "land" and not land_p and not water_p
                )
                if domain == "water" and not water_p and not land_p:
                    blocked = True
                self.pathability_override[node] = {
                    "domain": domain,
                    "blocked": blocked and not bool(h3p.get("visitableDestination")),
                    "unknown": False,
                    "gate": bool(h3p.get("visitableDestination")),
                    "landPathable": land_p,
                    "waterPathable": water_p,
                }
                if self.pathability_override[node]["blocked"]:
                    self.blocked_nodes.add(node)
                if self.pathability_override[node]["gate"]:
                    self.gate_nodes.add(node)

                for obj in tcell.get("objects") or []:
                    if not isinstance(obj, dict):
                        continue
                    oid = obj.get("id")
                    if not isinstance(oid, int):
                        continue
                    meta = object_index.get(oid) or {}
                    category = str(meta.get("category") or "other")
                    kind = classify_h3_category(category)
                    sid = str(meta.get("sid") or f"h3m:{category}:{oid}")
                    section = obj.get("section") or {}
                    mask_kinds = set(section.get("maskKinds") or [])
                    occupied = "block" in mask_kinds
                    gate = "visit" in mask_kinds
                    is_anchor = bool(section.get("isAnchor"))
                    entry = {
                        "id": oid,
                        "sid": sid,
                        "kind": kind,
                        "anchor": is_anchor,
                        "occupied": occupied,
                        "gate": gate,
                        "footprintSource": "homm3_template_mask",
                        "rotation": 0,
                        "anchorNode": node if is_anchor else None,
                        "category": category,
                    }
                    self.cover_at[node].append(entry)
                    self.footprint_stats["instanced"] += 1
                    if occupied:
                        self.blocked_nodes.add(node)
                    if gate:
                        self.gate_nodes.add(node)
                    if is_anchor:
                        self.anchors_at[node].append((oid, sid))
                        if oid not in self.by_id:
                            self.by_id[oid] = (sid, node, 0)

        # Ensure every indexed object has an anchor entry even if mask missed isAnchor.
        for oid, meta in object_index.items():
            if oid in self.by_id:
                continue
            covered = meta.get("coveredNodes") or meta.get("anchorMarkerNodes") or []
            if not covered:
                continue
            local80 = int(covered[0])
            lx = local80 % SURFACE_W
            ly = local80 // SURFACE_W
            node = ly * self.width + lx
            sid = str(meta.get("sid") or f"h3m:{meta.get('category')}:{oid}")
            self.by_id[oid] = (sid, node, 0)
            self.anchors_at[node].append((oid, sid))

        self.h3_entities = []
        self.h3_at_olden = defaultdict(list)
        alignment = preset.get("alignment")
        if isinstance(alignment, Path) and alignment.is_file():
            self._load_alignment(alignment)
            # Mirror alignment entities into h3_source overlays for homm3_source lens.
            for entity in self.h3_entities:
                node = entity.get("_oldenNode")
                if isinstance(node, int):
                    # Remap 80-wide olden node from h3_to_olden (uses self.width) — already atlas.
                    pass

        self.must_fight_poi_nodes = set()
        self.must_fight_pack_nodes = set()
        self.block_parity_seal_nodes = set()
        self.accessibility_clear_nodes = set()
        self.diagonal_squeeze_nodes = diagonal_squeeze_corridor_cells(
            self.blocked_nodes,
            grid_width=self.width,
            grid_height=self.height,
        )
        cat_path = preset.get("mustFightCatalogue")
        self._load_must_fight(
            catalogue_path=cat_path if isinstance(cat_path, Path) else None,
            map_path=None,
        )
        # HoMM3 source preset has no Olden block-parity / access-repair artifacts.

    def _load_must_fight(
        self,
        *,
        catalogue_path: Path | None = None,
        map_path: Path | None = None,
    ) -> None:
        """Load approach_cell must-fight catalogue (diagnostic) when present."""
        if catalogue_path is None and map_path is not None:
            root = map_path.parent.parent
            catalogue_path = root / "must_fight" / "homecoming.surface_must_fight_catalogue.json"
        if catalogue_path is None or not catalogue_path.is_file():
            return
        cat = json.loads(catalogue_path.read_text(encoding="utf-8-sig"))
        for _key, cells in (cat.get("packCells") or {}).items():
            for cell in cells or []:
                if not isinstance(cell, int):
                    continue
                x = cell % SURFACE_W
                y = cell // SURFACE_W
                self.must_fight_pack_nodes.add(y * self.width + x)
        for point in cat.get("points") or []:
            if not isinstance(point, dict):
                continue
            if not (point.get("evidence") or {}).get("unreachableWithAllPacks"):
                continue
            poi = point.get("poiSourceIndex")
            if not isinstance(poi, int):
                continue
            if poi in self.by_id:
                self.must_fight_poi_nodes.add(self.by_id[poi][1])
            else:
                sx, sy = point.get("sourceX"), point.get("sourceY")
                if isinstance(sx, int) and isinstance(sy, int):
                    node, _ox, _oy = self.h3_to_olden(sx, sy)
                    self.must_fight_poi_nodes.add(node)

    def _load_block_parity_and_access(
        self,
        *,
        map_path: Path | None = None,
        block_parity_path: Path | None = None,
        access_path: Path | None = None,
    ) -> None:
        """Load approach_cell block-parity + accessibility-repair reports when present."""
        if map_path is not None:
            root = map_path.parent.parent
            if block_parity_path is None:
                block_parity_path = (
                    root / "block_parity" / "homecoming.block_parity_report.json"
                )
            if access_path is None:
                access_path = (
                    root / "accessibility_repair" / "homecoming.accessibility_repair_report.json"
                )
        if block_parity_path is not None and block_parity_path.is_file():
            parity = json.loads(block_parity_path.read_text(encoding="utf-8-sig"))
            for node in parity.get("sealedNodes") or []:
                if isinstance(node, int):
                    self.block_parity_seal_nodes.add(node)
        if access_path is not None and access_path.is_file():
            access = json.loads(access_path.read_text(encoding="utf-8-sig"))
            for node in access.get("clearedNodes") or []:
                if isinstance(node, int):
                    self.accessibility_clear_nodes.add(node)
            for mut in access.get("mutations") or []:
                if not isinstance(mut, dict):
                    continue
                for node in mut.get("clearedNodes") or []:
                    if isinstance(node, int):
                        self.accessibility_clear_nodes.add(node)

    def _load_alignment(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        ents = raw.get("alignment", {}).get("globalObjectProperties", {}).get("propEntities") or []
        for entity in ents:
            if entity.get("sourceLayer") != 0:
                continue
            sx, sy = entity.get("sourceX"), entity.get("sourceY")
            if not isinstance(sx, int) or not isinstance(sy, int):
                continue
            node, ox, oy = self.h3_to_olden(sx, sy)
            row = {**entity, "_oldenNode": node, "_oldenX": ox, "_oldenY": oy}
            self.h3_entities.append(row)
            self.h3_at_olden[node].append(row)

    def h3_to_olden(self, sx: int, sy: int) -> tuple[int, int, int]:
        oy = SOURCE_H - 1 - sy
        ox = sx
        x = ox + OFFSET_X
        y = oy + OFFSET_Y
        node = y * self.width + x
        return node, x, y

    def view_node(self, view: str, x: int, y: int) -> int:
        ox = x + (SURFACE_W if view == "underground" else 0)
        return y * self.width + ox

    def view_xy(self, view: str, node: int) -> tuple[int, int] | None:
        ax = node % self.width
        ay = node // self.width
        if view == "surface":
            if ax >= SURFACE_W:
                return None
            return ax, ay
        if ax < SURFACE_W or ax >= SURFACE_W * 2:
            return None
        return ax - SURFACE_W, ay

    def water_domain(self, node: int) -> bool:
        if node in self.pathability_override:
            return self.pathability_override[node].get("domain") == "water"
        tile = self.tiles[node] if node < len(self.tiles) else None
        water = self.water[node] if node < len(self.water) else None
        level = self.levels[node] if node < len(self.levels) else None
        return tile == OCEAN_TILE_CODE and water == OCEAN_WATER_MAP_ID and level == OCEAN_BASIN_LEVEL

    def pathability(self, node: int) -> dict[str, Any]:
        squeeze = node in getattr(self, "diagonal_squeeze_nodes", set())
        if node in self.pathability_override:
            result = dict(self.pathability_override[node])
            blocked = bool(result.get("blocked"))
            result["diagonalSqueeze"] = squeeze and not blocked
            return result
        water = self.water_domain(node)
        blocked = node in self.blocked_nodes
        unknown = node in self.unknown_size_anchors and not blocked
        if unknown:
            land: bool | None = None if not water else False
            water_p: bool | None = None if water else False
        else:
            land = (not water) and (not blocked)
            water_p = water and (not blocked)
        return {
            "domain": "water" if water else "land",
            "blocked": blocked,
            "unknown": unknown,
            "gate": node in self.gate_nodes,
            "diagonalSqueeze": squeeze and not blocked,
            "landPathable": land,
            "waterPathable": water_p,
        }


class LensViewer(tk.Tk):
    def __init__(self, map_path: Path | dict[str, Any], alignment_path: Path | None) -> None:
        super().__init__()
        self.title("Map model lens viewer")
        self.geometry("1280x820")
        self.cell = 8
        self.hover = tk.StringVar(value="Loading…")
        self.lens = tk.StringVar(value="interactables")
        self.view = tk.StringVar(value="surface")
        self.preset = tk.StringVar(value=self._guess_preset(map_path))
        self.selected: tuple[int, int] | None = None
        self.photo: tk.PhotoImage | None = None
        self._redraw_after: str | None = None
        self.alignment_path = alignment_path
        self.model = MapModel(map_path, alignment_path)
        self._build_ui()
        label = self._model_label()
        self.hover.set(
            f"loaded {label} | footprints={self.model.footprint_stats['instanced']} "
            f"blocked_cells={len(self.model.blocked_nodes)} "
            f"source={getattr(self.model, 'source_kind', 'olden_map')}"
        )
        self.after(50, self.redraw)

    def _model_label(self) -> str:
        if getattr(self.model, "source_kind", "") == "homm3_source":
            return str(self.model.meta.get("title") or "homm3_source")
        return self.model.map_path.name

    def _guess_preset(self, path: Path | dict[str, Any]) -> str:
        if isinstance(path, dict) and path.get("kind") == "homm3_source":
            return "homm3_source"
        name = path.name if isinstance(path, Path) else ""
        for key, preset in PRESETS.items():
            if isinstance(preset, Path) and preset.name == name:
                return key
        return "custom"

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)

        ttk.Label(top, text="Map").pack(side=tk.LEFT)
        preset = ttk.Combobox(
            top,
            textvariable=self.preset,
            values=list(PRESETS.keys()) + ["custom"],
            width=28,
            state="readonly",
        )
        preset.pack(side=tk.LEFT, padx=4)
        preset.bind("<<ComboboxSelected>>", self._on_preset)

        ttk.Label(top, text="View").pack(side=tk.LEFT, padx=(12, 0))
        view = ttk.Combobox(
            top,
            textvariable=self.view,
            values=[k for k, _ in VIEWS],
            width=14,
            state="readonly",
        )
        view.pack(side=tk.LEFT, padx=4)
        view.bind("<<ComboboxSelected>>", lambda _e: self.redraw())

        ttk.Label(top, text="Lens").pack(side=tk.LEFT, padx=(12, 0))
        lens = ttk.Combobox(
            top,
            textvariable=self.lens,
            values=[k for k, _ in LENSES],
            width=22,
            state="readonly",
        )
        lens.pack(side=tk.LEFT, padx=4)
        lens.bind("<<ComboboxSelected>>", lambda _e: self.redraw())

        ttk.Button(top, text="Reload", command=self._reload).pack(side=tk.LEFT, padx=8)

        self.status = ttk.Label(top, textvariable=self.hover)
        self.status.pack(side=tk.LEFT, padx=12)

        body = ttk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(body)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, background="#111", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Configure>", self._schedule_redraw)

        side = ttk.Frame(body, width=360)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)

        ttk.Label(side, text="Legend / cell detail", font=("", 10, "bold")).pack(anchor=tk.W, padx=8, pady=4)
        self.legend = tk.Text(side, height=14, wrap=tk.WORD, font=("Consolas", 9))
        self.legend.pack(fill=tk.X, padx=8)
        self.detail = tk.Text(side, wrap=tk.WORD, font=("Consolas", 9))
        self.detail.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._write_legend_help()

    def _write_legend_help(self) -> None:
        lines = ["Lenses:"]
        for key, label in LENSES:
            lines.append(f"  {key}: {label}")
        lines.append("")
        lines.append("Object lenses paint ObjectConfig occupied")
        lines.append("and GATE footprint cells (not just anchors).")
        lines.append("Pathability: green=land pathable, cyan=water")
        lines.append("pathable, red=blocked, gold=unknown size,")
        lines.append("tan=GATE (visit) cell, orange=diagonal squeeze")
        lines.append("corridor (open cells between blocked corners).")
        lines.append("")
        lines.append("Atlas: surface left, underground right.")
        lines.append("North is up (Olden y=0 is south).")
        self.legend.delete("1.0", tk.END)
        self.legend.insert(tk.END, "\n".join(lines))

    def _on_preset(self, _event: object | None = None) -> None:
        key = self.preset.get()
        if key not in PRESETS:
            return
        preset = PRESETS[key]
        if preset_is_homm3(preset):
            assert isinstance(preset, dict)
            self.hover.set("Loading HoMM3 source grids…")
            self.update_idletasks()
            alignment = preset.get("alignment")
            alignment_path = alignment if isinstance(alignment, Path) else None
            self.alignment_path = alignment_path
            self.model = MapModel(preset, alignment_path)
            self.title(f"Map model lens viewer — {self.model.meta.get('title')}")
            self.hover.set(
                f"loaded {self._model_label()} | blocked_cells={len(self.model.blocked_nodes)} "
                f"objects={len(self.model.by_id)} source=homm3_source"
            )
            self.redraw()
            return
        assert isinstance(preset, Path)
        path = preset
        if not path.is_file():
            self.hover.set(f"missing map: {path}")
            return
        self.hover.set(f"Loading {path.name}…")
        self.update_idletasks()
        alignment = self.alignment_path if self.alignment_path and self.alignment_path.is_file() else None
        self.model = MapModel(path, alignment)
        self.title(f"Map model lens viewer — {path.name}")
        self.hover.set(
            f"loaded {path.name} | blocked_cells={len(self.model.blocked_nodes)} "
            f"missing_configs={len(self.model.missing_configs)}"
        )
        self.redraw()

    def _reload(self) -> None:
        # Prefer the selected preset path. Reloading via model.map_path breaks after
        # visiting homm3_source, which stores a JSON grid path there.
        _CONFIG_CACHE.clear()
        key = self.preset.get()
        if key in PRESETS:
            self._on_preset()
            return
        self.hover.set("Reloading…")
        self.update_idletasks()
        if getattr(self.model, "source_kind", None) != "olden_map":
            self.hover.set("reload needs an Olden .map preset (not homm3_source JSON)")
            return
        map_path = self.model.map_path
        if not isinstance(map_path, Path) or not map_path.is_file():
            self.hover.set(f"missing map: {map_path}")
            return
        alignment = self.alignment_path if self.alignment_path and self.alignment_path.is_file() else None
        self.model = MapModel(map_path, alignment)
        self.redraw()
        self.hover.set(f"reloaded {self._model_label()}")

    def _covers(self, node: int) -> list[dict[str, Any]]:
        return self.model.cover_at.get(node, [])

    def _anchors(self, node: int) -> list[tuple[int, str]]:
        return self.model.anchors_at.get(node, [])

    def color_for(self, x: int, y: int) -> str:
        m = self.model
        view = self.view.get()
        node = m.view_node(view, x, y)
        lens = self.lens.get()
        covers = self._covers(node)
        anchors = self._anchors(node)
        level = m.levels[node] if node < len(m.levels) else 0

        if lens == "terrain":
            if m.water_domain(node):
                return PALETTE["water"]
            if level == 1:
                return PALETTE["elevated"]
            return PALETTE["land"]

        if lens == "water":
            return PALETTE["water"] if m.water_domain(node) else PALETTE["empty"]

        if lens == "levels":
            if level == 1:
                return PALETTE["elevated"]
            if level < 0:
                return PALETTE["water"]
            return PALETTE["water"] if m.water_domain(node) else PALETTE["land"]

        if lens == "pathability":
            p = m.pathability(node)
            if p["unknown"]:
                return PALETTE["path_unknown"]
            if p["blocked"]:
                return PALETTE["blocked_water"] if p["domain"] == "water" else PALETTE["blocked_land"]
            if p["gate"]:
                return PALETTE["gate"]
            if p.get("diagonalSqueeze"):
                return PALETTE["diagonal_squeeze"]
            if p["waterPathable"]:
                return PALETTE["path_water"]
            if p["landPathable"]:
                return PALETTE["path_land"]
            return PALETTE["empty"]

        if lens == "synthetics":
            syn = [c for c in covers if c["id"] >= 900_000]
            if not syn:
                return PALETTE["empty"]
            if any(c["occupied"] for c in syn):
                return PALETTE["synthetic"]
            return "#804080"

        if lens == "homm3_source":
            if view != "surface":
                return PALETTE["empty"]
            if m.h3_at_olden.get(node):
                return PALETTE["h3"]
            return PALETTE["empty"]

        if lens == "homm3_vs_olden":
            if view != "surface":
                return PALETTE["empty"]
            h3 = m.h3_at_olden.get(node, [])
            olden_ids = {oid for oid, _ in anchors}
            h3_ids = {e.get("sourceIndex") for e in h3 if isinstance(e.get("sourceIndex"), int)}
            if h3_ids & olden_ids:
                return PALETTE["match"]
            if h3 and not anchors:
                return PALETTE["h3_only"]
            if anchors and not h3:
                if any(oid >= 900_000 for oid, _ in anchors):
                    return PALETTE["olden_only"]
                kinds = {classify_sid(sid) for _, sid in anchors}
                if kinds & {"town", "dwelling", "mine", "portal", "boat", "guard", "spawn", "marker", "pickup"}:
                    return PALETTE["olden_only"]
                return PALETTE["empty"]
            if h3 and anchors and not (h3_ids & olden_ids):
                return PALETTE["olden_only"]
            return PALETTE["empty"]

        if lens == "spawn_cluster":
            interesting = False
            for c in covers:
                if c["kind"] in {"spawn", "town", "guard", "boat", "marker"} or c["id"] in {1429, 16}:
                    interesting = True
                    break
            spawn = m.by_id.get(1429)
            city = m.by_id.get(16)
            for anchor in (spawn, city):
                if not anchor:
                    continue
                _, anode, _rot = anchor
                local = m.view_xy(view, anode)
                if local is None:
                    continue
                ax, ay = local
                if abs(ax - x) <= 4 and abs(ay - y) <= 4:
                    interesting = True
            if not interesting:
                return PALETTE["empty"]
            solid = [c for c in covers if c["occupied"] or c["gate"] or c["anchor"]]
            if solid:
                return PALETTE[pick_kind([c["kind"] for c in solid])]
            return "#303030"

        if lens == "must_fight_poi":
            if view != "surface":
                return PALETTE["empty"]
            if node in m.must_fight_pack_nodes:
                return PALETTE["must_fight_pack"]
            if node in m.must_fight_poi_nodes:
                return PALETTE["must_fight_poi"]
            return PALETTE["empty"]

        if lens == "soft_bypass":
            if view != "surface":
                return PALETTE["empty"]
            if node in m.accessibility_clear_nodes:
                return PALETTE["access_clear"]
            if node in m.block_parity_seal_nodes:
                return PALETTE["seal_pad"]
            if node in m.must_fight_pack_nodes:
                return PALETTE["must_fight_pack"]
            return PALETTE["empty"]

        solid = [
            c for c in covers
            if c["occupied"] or c["gate"] or (
                c["anchor"] and c["footprintSource"] in {
                    "explicit_point_anchor_without_native_size",
                    "native_config_missing_size_anchor_only",
                    "empty_footprint_anchor_fallback",
                    "missing_object_config",
                    "invalid_nodes_grid_anchor_only",
                }
            )
        ]
        if not solid:
            if lens == "objects" and m.water_domain(node):
                return "#152030"
            return PALETTE["empty"]

        if lens == "objects":
            if any(c["occupied"] for c in solid):
                return PALETTE[pick_kind([c["kind"] for c in solid if c["occupied"]])]
            if any(c["gate"] for c in solid):
                return PALETTE["gate"]
            return PALETTE[pick_kind([c["kind"] for c in solid])]

        if lens == "interactables":
            for kind in ("spawn", "town", "dwelling", "mine", "portal", "boat", "marker", "pickup", "landon"):
                if any(c["kind"] == kind for c in solid):
                    return PALETTE[kind]
            return PALETTE["empty"]

        if lens == "guards":
            return PALETTE["guard"] if any(c["kind"] == "guard" for c in solid) else PALETTE["empty"]

        if lens == "mountains":
            return PALETTE["mountain"] if any(c["kind"] == "mountain" for c in solid) else PALETTE["empty"]

        if lens == "scenery":
            return PALETTE["scenery"] if any(c["kind"] == "scenery" for c in solid) else PALETTE["empty"]

        return PALETTE["other"]

    def _schedule_redraw(self, _event: object | None = None) -> None:
        if self._redraw_after is not None:
            try:
                self.after_cancel(self._redraw_after)
            except tk.TclError:
                pass
        self._redraw_after = self.after(80, self.redraw)

    def redraw(self) -> None:
        self._redraw_after = None
        cw = max(int(self.canvas.winfo_width()), 1)
        ch = max(int(self.canvas.winfo_height()), 1)
        self.cell = max(4, min(cw // SURFACE_W, ch // SURFACE_H, 14))
        c = self.cell
        img_w = SURFACE_W * c
        img_h = SURFACE_H * c
        photo = tk.PhotoImage(width=img_w, height=img_h)
        for model_y in range(SURFACE_H):
            colors = [self.color_for(x, model_y) for x in range(SURFACE_W)]
            expanded: list[str] = []
            for color in colors:
                expanded.extend([color] * c)
            row_data = "{" + " ".join(expanded) + "}"
            _, display_y = self._model_to_display(0, model_y)
            for yy in range(c):
                photo.put(row_data, to=(0, display_y * c + yy))
        self.photo = photo
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        for i in range(0, SURFACE_W + 1, 8):
            self.canvas.create_line(i * c, 0, i * c, SURFACE_H * c, fill="#2a2a2a")
            self.canvas.create_line(0, i * c, SURFACE_W * c, i * c, fill="#2a2a2a")
        if self.selected:
            sx, sy = self.selected
            dx, dy = self._model_to_display(sx, sy)
            self.canvas.create_rectangle(
                dx * c, dy * c, (dx + 1) * c - 1, (dy + 1) * c - 1,
                outline=PALETTE["highlight"], width=2,
            )
        title = self.model.meta.get("title") or self.model.md.get("fileMapName")
        self.canvas.create_text(
            8, 8, anchor=tk.NW, fill="#ddd",
            text=f"{title} | view={self.view.get()} | lens={self.lens.get()} | {SURFACE_W}x{SURFACE_H}",
            font=("Consolas", 10),
        )

    def _display_to_model(self, dx: int, dy: int) -> tuple[int, int]:
        if DISPLAY_FLIP_Y:
            return dx, SURFACE_H - 1 - dy
        return dx, dy

    def _model_to_display(self, mx: int, my: int) -> tuple[int, int]:
        if DISPLAY_FLIP_Y:
            return mx, SURFACE_H - 1 - my
        return mx, my

    def _xy_from_event(self, event: tk.Event) -> tuple[int, int] | None:
        dx = event.x // self.cell
        dy = event.y // self.cell
        if 0 <= dx < SURFACE_W and 0 <= dy < SURFACE_H:
            return self._display_to_model(dx, dy)
        return None

    def _on_motion(self, event: tk.Event) -> None:
        xy = self._xy_from_event(event)
        if not xy:
            return
        x, y = xy
        node = self.model.view_node(self.view.get(), x, y)
        covers = self._covers(node)
        bits = ", ".join(
            f"{c['id']}:{c['sid']}{'*' if c['occupied'] else ('G' if c['gate'] else '')}"
            for c in covers[:4]
        ) or "-"
        more = f" (+{len(covers)-4})" if len(covers) > 4 else ""
        p = self.model.pathability(node)
        path = "blocked" if p["blocked"] else ("unknown" if p["unknown"] else "pathable")
        self.hover.set(
            f"{self.view.get()} ({x},{y}) n={node} {p['domain']}/{path} | {bits}{more}"
        )

    def _on_click(self, event: tk.Event) -> None:
        xy = self._xy_from_event(event)
        if not xy:
            return
        self.selected = xy
        self.redraw()
        self._show_detail(*xy)

    def _show_detail(self, x: int, y: int) -> None:
        m = self.model
        view = self.view.get()
        node = m.view_node(view, x, y)
        p = m.pathability(node)
        lines = [
            f"View={view} cell ({x},{y}) node={node}",
            f"tile={m.tiles[node] if node < len(m.tiles) else '?'} "
            f"water={m.water[node] if node < len(m.water) else '?'} "
            f"level={m.levels[node] if node < len(m.levels) else '?'}",
            f"pathability: domain={p['domain']} blocked={p['blocked']} "
            f"gate={p['gate']} squeeze={p.get('diagonalSqueeze')} "
            f"unknown={p['unknown']} "
            f"land={p['landPathable']} water={p['waterPathable']}",
            "",
            "Objects covering this cell (footprint):",
        ]
        covers = self._covers(node)
        if not covers:
            lines.append("  (none)")
        for c in covers:
            flags = []
            if c["anchor"]:
                flags.append("anchor")
            if c["occupied"]:
                flags.append("OCCUPIED")
            if c["gate"]:
                flags.append("GATE")
            if c["id"] >= 900_000:
                flags.append("SYNTHETIC")
            flag_s = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  id={c['id']} sid={c['sid']} kind={c['kind']} rot={c['rotation']} "
                f"src={c['footprintSource']}{flag_s}"
            )
            if c["anchorNode"] != node:
                ax, ay = c["anchorNode"] % m.width, c["anchorNode"] // m.width
                lines.append(f"    anchor atlas=({ax},{ay}) n={c['anchorNode']}")

        h3 = m.h3_at_olden.get(node, []) if view == "surface" else []
        lines.append("")
        lines.append("HoMM3 source entities projecting here:")
        if not h3:
            lines.append("  (none)" if view == "surface" else "  (surface alignment only)")
        for e in h3:
            lines.append(
                f"  id={e.get('sourceIndex')} H3({e.get('sourceX')},{e.get('sourceY')}) "
                f"{e.get('category')} {e.get('templateAnimation')} {e.get('name') or ''}"
            )
            oid = e.get("sourceIndex")
            if isinstance(oid, int) and oid in m.by_id:
                sid, onode, rot = m.by_id[oid]
                local = m.view_xy(view, onode)
                if local:
                    ox, oy = local
                    lines.append(f"    -> Olden emit id={oid} {sid} rot={rot} @({ox},{oy}) n={onode}")
                else:
                    ax, ay = onode % m.width, onode // m.width
                    lines.append(f"    -> Olden emit id={oid} {sid} rot={rot} atlas=({ax},{ay}) n={onode}")
            elif isinstance(oid, int):
                lines.append(f"    -> Olden emit MISSING for sourceIndex {oid}")

        lines.append("")
        lines.append(f"Map: {m.map_path.name}")
        lines.append(f"Title: {m.meta.get('title')}")
        hist = Counter(classify_sid(sid) for sid, _node, _rot in m.by_id.values())
        lines.append("Kind histogram: " + ", ".join(f"{k}={v}" for k, v in hist.most_common(12)))
        syn_count = sum(1 for oid in m.by_id if oid >= 900_000)
        lines.append(f"Synthetic objects: {syn_count}")
        lines.append(f"Blocked footprint cells: {len(m.blocked_nodes)}")
        lines.append(f"GATE cells: {len(m.gate_nodes)}")
        lines.append(f"Unknown-size anchors: {len(m.unknown_size_anchors)}")
        if m.missing_configs:
            lines.append(f"Missing configs ({len(m.missing_configs)}): {', '.join(m.missing_configs[:12])}")
        lines.append(f"HoMM3 surface entities loaded: {len(m.h3_entities)}")

        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=None, help="Path to Olden .map")
    parser.add_argument("--preset", choices=list(PRESETS), default="approach_cell")
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT)
    parser.add_argument("--lens", choices=[k for k, _ in LENSES], default="interactables")
    args = parser.parse_args()
    if args.map is not None:
        map_spec: Path | dict[str, Any] = args.map
        if not map_spec.is_file():
            raise SystemExit(f"map not found: {map_spec}")
        alignment = args.alignment if args.alignment.is_file() else None
        print(f"Loading {map_spec.name}…", flush=True)
    else:
        preset = PRESETS[args.preset]
        if preset_is_homm3(preset):
            assert isinstance(preset, dict)
            map_spec = preset
            alignment = preset.get("alignment") if isinstance(preset.get("alignment"), Path) else None
            print(f"Loading HoMM3 source preset…", flush=True)
        else:
            assert isinstance(preset, Path)
            map_spec = preset
            if not map_spec.is_file():
                raise SystemExit(f"map not found: {map_spec}")
            alignment = args.alignment if args.alignment.is_file() else None
            print(f"Loading {map_spec.name}…", flush=True)
    app = LensViewer(map_spec, alignment if isinstance(alignment, Path) else None)
    app.lens.set(args.lens)
    app.redraw()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
