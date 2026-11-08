#!/usr/bin/env python3
"""Fail-closed contract for the Homecoming raw_translation parallel map."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP_SID = "h3_roe_castle_homecoming_raw_translation"
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "raw_translation_map"
PROFILE_PATH = Path("scenarios") / "homecoming_roe_castle" / "raw_translation.profile.json"
GENERATOR = Path("experiments") / "campaign_port_poc" / "raw_translation" / "build_raw_translation_map.py"
PACKAGE_DIR = Path("experiments") / "campaign_port_poc" / "raw_translation"
INSTALLER = Path("tools") / "install_homecoming_raw_translation_map.py"
EXPECTED_SCHEMA = "homm3.olden_raw_translation_map.v1"
# Dual maps/ + Story_maps/ install registers QuestScript twice (Player.log: each
# homecoming_briefing_* Start dialog fires exactly twice). Native campaigns are
# Story_maps-only; installer must match continuity weave.
# Separately: a full quest tree in both map chunk 3 and the sidecar .json also
# double-registers StartTurn Dialogs after dual-install cleanup; sidecar quests
# must stay empty (chunk 3 owns runtime QuestScript).
INSTALL_DESTINATION_POLICY = "story_maps_only_forbid_maps_root_duplicate"
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
LAYERED_DEFAULT_SID = "h3_roe_castle_homecoming_layered_atlas"
APPROACH_CELL_SID = "h3_roe_castle_homecoming_approach_cell"
HOMM3_SUBTERRANEAN_GATE_PORTAL_SID = "homm3_subterranean_gate_portal"
HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID = "portal_5"
HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB = "interactive/dungeon_entrance"
HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER = "DB/map/objects/4_interactables.json"
HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER = "DB/objects_logic/portals/portals.json"
EXPECTED_SUBTERRANEAN_GATE_SOURCE_KEYS = ("0:14:41", "0:49:3", "1:14:41", "1:49:3")
# Scorched-earth: donor portal_5 [1,0,0,2] → keep OCC, convert all 0s to GATE.
EXPECTED_SUBTERRANEAN_GATE_NODES = [1, 2, 2, 2]
EXPECTED_SUBTERRANEAN_GATE_COUNT = 3
EXPECTED_SUBTERRANEAN_GATE_PREFERRED_LOCAL = (1, 1)  # south-east / prefer_gate_local 2x2
FORBIDDEN_MODULES = (
    "functional_points",
    "footprint_alignment",
    "block_parity",
    "accessibility_repair",
    "mountain_merge",
    "local_1c",
    "domains",
    "must_fight_catalogue",
    "soft_grid",
    "build_homecoming_approach_cell_map",
    "build_layered_atlas_map",
    "build_homecoming_layered_atlas_map",
    "build_campaign_layered_atlas_batch",
)
DISABLED_POST_PASS_KEYS = (
    "blockParity",
    "accessibilityRepair",
    "mountainMerge",
    "localApproachCell",
    "omitSigns",
    "spawnUnbury",
    "landonGateWaterClear",
    "boatPlacementAdjust",
    "environmentDecorations",
    "functionalEmitReservation",
    "exactAnchorScenerySuppress",
    "undergroundPayloadlessScenerySuppress",
)
# Same bake-in as layered atlas: Chebyshev-2 rock→burrow shoulder so levelsMap=1
# cliffs do not collapse 1-tile corridors' 2x2 clearance.
UNDERGROUND_TUNNEL_CLEARANCE_POLICY = "chebyshev_two_tile_elevation_shoulder_rock_to_burrow_clearance"
UNDERGROUND_TUNNEL_CLEARANCE_STATUS = "generated_static_2x2_elevation_buffer_validated_runtime_unvalidated"
EXPECTED_UNDERGROUND_TUNNEL_CLEARANCE = {
    "status": UNDERGROUND_TUNNEL_CLEARANCE_STATUS,
    "policy": UNDERGROUND_TUNNEL_CLEARANCE_POLICY,
    "sourceBurrowCellCount": 1216,
    "sourceRockCellCount": 3968,
    "widenedRockCellCount": 1576,
    "finalBurrowCellCount": 2792,
    "remainingRockVoidCellCount": 2392,
    "clearanceRadius": 2,
    "clearanceNeighborhood": "chebyshev_8_neighbor",
    "clearanceModel": "2x2_orthogonal_native_pathing_proxy",
    "clearancePositionCount": 2531,
    "clearanceComponentCount": 1,
    "clearanceLargestComponentSize": 2531,
    "clearanceComponentSizesTop10": [2531],
    "walkableComponentCount": 1,
    "walkableLargestComponentSize": 2792,
    "elevationBufferedClearanceModel": "2x2_clearance_after_8_neighbor_level1_buffer",
    "elevationBufferedWalkableCellCount": 2284,
    "elevationBufferedClearancePositionCount": 1992,
    "elevationBufferedClearanceComponentCount": 1,
    "elevationBufferedClearanceLargestComponentSize": 1992,
    "elevationBufferedClearanceComponentSizesTop10": [1992],
}
OLDEN_BURROW_TILE_ID = 15
OLDEN_VOID_TILE_ID = 23
UNDERGROUND_ROCK_LEVEL = 1
UNDERGROUND_ROCK_CLIMB = 0
SOURCE_WIDTH = 72
SOURCE_HEIGHT = 72
OLDEN_WIDTH = 160
H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID = 6
H3_UNDERGROUND_ROCK_TERRAIN_ID = 9
UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0),           (1, 0),
    (-1, 1),  (0, 1),  (1, 1),
)


def target_node(layer: int, source_x: int, source_y: int) -> int:
    offset_x = 4 if layer == 0 else 84
    return (SOURCE_HEIGHT - 1 - source_y + 4) * OLDEN_WIDTH + source_x + offset_x


def underground_tunnel_clearance_widened_rock(
    source_burrow: set[tuple[int, int]],
    source_rock: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    walkable = set(source_burrow)
    frontier = set(source_burrow)
    widened: set[tuple[int, int]] = set()
    for _ in range(2):
        next_frontier = {
            (x + dx, y + dy)
            for x, y in frontier
            for dx, dy in UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS
            if (x + dx, y + dy) in source_rock and (x + dx, y + dy) not in walkable
        }
        widened.update(next_frontier)
        walkable.update(next_frontier)
        frontier = next_frontier
    return widened


def layered_source_underground_tiles(repo_root: Path, errors: list[str]) -> list[int] | None:
    alignment_path = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "homecoming_poc"
        / "olden_storage_alignment"
        / "homecoming.olden_storage_alignment.json"
    )
    require(alignment_path.is_file(), f"missing alignment for UG clearance pin: {alignment_path}", errors)
    if not alignment_path.is_file():
        return None
    alignment = read_json(alignment_path)

    def find_underground(obj: Any) -> list[int] | None:
        if isinstance(obj, dict):
            tiles = obj.get("tilesMap")
            if (
                isinstance(tiles, list)
                and obj.get("sizeX_") == SOURCE_WIDTH
                and obj.get("sizeZ_") == SOURCE_HEIGHT
                and tiles.count(H3_UNDERGROUND_ROCK_TERRAIN_ID) == 3968
                and tiles.count(H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID) == 1216
            ):
                return tiles
            for value in obj.values():
                found = find_underground(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = find_underground(value)
                if found is not None:
                    return found
        return None

    tiles = find_underground(alignment)
    require(tiles is not None, "alignment missing underground 72x72 tilesMap", errors)
    return tiles


def validate_underground_tunnel_clearance_arrays(
    repo_root: Path,
    map_data: dict[str, Any],
    errors: list[str],
) -> None:
    source_tiles = layered_source_underground_tiles(repo_root, errors)
    generated_tiles = map_data.get("tilesMap")
    generated_levels = map_data.get("levelsMap")
    generated_climbs = map_data.get("climbsMap")
    if not isinstance(source_tiles, list):
        return
    if not all(isinstance(values, list) for values in (generated_tiles, generated_levels, generated_climbs)):
        errors.append("raw map missing tilesMap/levelsMap/climbsMap for UG clearance pin")
        return
    source_burrow = {
        (x, y)
        for y in range(SOURCE_HEIGHT)
        for x in range(SOURCE_WIDTH)
        if source_tiles[y * SOURCE_WIDTH + x] == H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID
    }
    source_rock = {
        (x, y)
        for y in range(SOURCE_HEIGHT)
        for x in range(SOURCE_WIDTH)
        if source_tiles[y * SOURCE_WIDTH + x] == H3_UNDERGROUND_ROCK_TERRAIN_ID
    }
    widened_rock = underground_tunnel_clearance_widened_rock(source_burrow, source_rock)
    require(len(source_burrow) == 1216, f"UG source burrow count changed: {len(source_burrow)}", errors)
    require(len(source_rock) == 3968, f"UG source rock count changed: {len(source_rock)}", errors)
    require(
        len(widened_rock) == EXPECTED_UNDERGROUND_TUNNEL_CLEARANCE["widenedRockCellCount"],
        f"UG widened-rock count changed: {len(widened_rock)}",
        errors,
    )
    violations: list[str] = []

    def note(message: str) -> None:
        if len(violations) < 20:
            violations.append(message)

    for y in range(SOURCE_HEIGHT):
        for x in range(SOURCE_WIDTH):
            target = target_node(1, x, y)
            terrain = source_tiles[y * SOURCE_WIDTH + x]
            if terrain == H3_UNDERGROUND_ROCK_TERRAIN_ID:
                if (x, y) in widened_rock:
                    if generated_tiles[target] != OLDEN_BURROW_TILE_ID:
                        note(f"widened rock {x},{y} tile {generated_tiles[target]} != burrow")
                    if generated_levels[target] != 0:
                        note(f"widened rock {x},{y} level {generated_levels[target]} != 0")
                    if generated_climbs[target] != 0:
                        note(f"widened rock {x},{y} climb {generated_climbs[target]} != 0")
                else:
                    if generated_tiles[target] != OLDEN_VOID_TILE_ID:
                        note(f"rock {x},{y} tile {generated_tiles[target]} != void")
                    if generated_levels[target] != UNDERGROUND_ROCK_LEVEL:
                        note(f"rock {x},{y} level {generated_levels[target]} != 1")
                    if generated_climbs[target] != UNDERGROUND_ROCK_CLIMB:
                        note(f"rock {x},{y} climb {generated_climbs[target]} != 0")
                continue
            if terrain == H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID:
                if generated_tiles[target] != OLDEN_BURROW_TILE_ID:
                    note(f"burrow {x},{y} tile {generated_tiles[target]} != burrow")
                if generated_levels[target] != 0:
                    note(f"burrow {x},{y} level {generated_levels[target]} != 0")
                continue
            note(f"unsupported UG terrain {terrain} at {x},{y}")
    require(violations == [], "UG tunnel clearance array mismatch: " + "; ".join(violations), errors)


def fail(message: str) -> None:
    raise SystemExit(f"raw_translation contract failed: {message}")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def module_imports_forbidden(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_MODULES or alias.name in FORBIDDEN_MODULES:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".", 1)[0]
                if root in FORBIDDEN_MODULES or node.module in FORBIDDEN_MODULES:
                    found.append(node.module)
    return sorted(set(found))


def validate_forbidden_imports(repo_root: Path, errors: list[str]) -> None:
    package = repo_root / PACKAGE_DIR
    require(package.is_dir(), f"missing raw_translation package: {package}", errors)
    for path in sorted(package.glob("*.py")):
        if path.name.startswith("_"):
            continue
        bad = module_imports_forbidden(path)
        require(not bad, f"{path.name} imports forbidden OUT modules: {bad}", errors)


def validate_emit_deferral_and_pickup_anchor_proof(repo_root: Path, errors: list[str]) -> None:
    """Source/static pin: random-squad not false-deferred; clear pickups keep visit emit."""
    proof = (
        repo_root
        / "experiments"
        / "campaign_port_poc"
        / "approach_cell"
        / "proof_emit_deferral_and_pickup_anchor.py"
    )
    require(proof.is_file(), f"missing emit proof script: {proof}", errors)
    if not proof.is_file():
        return
    result = subprocess.run(
        [sys.executable, str(proof)],
        cwd=str(proof.parent),
        check=False,
        capture_output=True,
        text=True,
    )
    require(
        result.returncode == 0,
        "emit deferral/pickup-anchor proof failed:\n"
        + (result.stdout or "")
        + (result.stderr or ""),
        errors,
    )


def maybe_generate(repo_root: Path) -> None:
    generator = repo_root / GENERATOR
    profile = repo_root / PROFILE_PATH
    if not generator.is_file():
        fail(f"missing generator: {generator}")
    result = subprocess.run(
        [sys.executable, str(generator), "--profile", str(profile)],
        cwd=str(repo_root / "experiments" / "campaign_port_poc" / "raw_translation"),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(
            "generator failed:\n"
            + (result.stdout or "")
            + (result.stderr or "")
        )


def _load_object_configs(artifact_root: Path) -> dict[str, dict]:
    """Core map ObjectConfig rows overlaid by the artifact's core_overlay rows."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"))
    import core_zip_cache
    import port_homecoming_poc as poc_core

    configs: dict[str, dict] = {}
    core = poc_core.resolve_olden_core_zip()
    for name in core_zip_cache.core_namelist(core):
        if name.startswith("DB/map/objects/") and name.endswith(".json"):
            for row in core_zip_cache.read_core_json(core, name).get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    configs[row["id"]] = row
    overlay_dir = artifact_root / "core_overlay" / "DB" / "map" / "objects"
    for overlay_path in sorted(overlay_dir.glob("*.json")) if overlay_dir.is_dir() else []:
        for row in read_json(overlay_path).get("array") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                configs[row["id"]] = row
    return configs


def validate_artifact(repo_root: Path, errors: list[str]) -> None:
    profile_path = repo_root / PROFILE_PATH
    require(profile_path.is_file(), f"missing profile: {profile_path}", errors)
    if not profile_path.is_file():
        return
    profile = read_json(profile_path)
    require(profile.get("mapSid") == MAP_SID, f"profile mapSid must be {MAP_SID}", errors)
    require(profile.get("outputSubdir") == "raw_translation_map", "profile outputSubdir must be raw_translation_map", errors)
    require(profile.get("pathability", {}).get("surfaceGapFill") is False, "raw_translation must disable surfaceGapFill", errors)
    known_gaps = profile.get("knownGaps") or []
    require(isinstance(known_gaps, list) and known_gaps, "profile knownGaps must be non-empty", errors)
    raw_note = any("emit-only" in str(item).lower() or "raw translation" in str(item).lower() for item in known_gaps)
    stack_note = any("stack" in str(item).lower() or "buried" in str(item).lower() for item in known_gaps)
    forbid_note = any("block parity" in str(item).lower() or "forbidden" in str(item).lower() for item in known_gaps)
    multi_hero_note = any(
        "multi-hero" in str(item).lower() or "herocountmax=8" in str(item).lower() for item in known_gaps
    )
    require(raw_note, "profile knownGaps must document emit-only raw translation", errors)
    require(stack_note, "profile knownGaps must document intentional stacks/burial", errors)
    require(forbid_note, "profile knownGaps must document forbidden post-passes", errors)
    require(multi_hero_note, "profile knownGaps must document HoMM3 multi-hero hire settings", errors)

    root = repo_root / ARTIFACT_ROOT
    manifest_path = root / "install_manifest.json"
    map_path = root / "maps" / f"{MAP_SID}.map"
    script_path = root / "maps" / f"{MAP_SID}.json"
    require(manifest_path.is_file(), f"missing install_manifest: {manifest_path}", errors)
    require(map_path.is_file(), f"missing map: {map_path}", errors)
    require(script_path.is_file(), f"missing script: {script_path}", errors)
    if not manifest_path.is_file():
        return
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == EXPECTED_SCHEMA, f"manifest schema must be {EXPECTED_SCHEMA}", errors)
    require(manifest.get("mapSid") == MAP_SID, "manifest mapSid mismatch", errors)
    require(manifest.get("pipeline") == "raw_translation", "manifest pipeline must be raw_translation", errors)
    require(manifest.get("mapSid") != LAYERED_DEFAULT_SID, "raw_translation must not reuse layered atlas SID", errors)
    require(manifest.get("mapSid") != APPROACH_CELL_SID, "raw_translation must not reuse approach_cell SID", errors)
    hero_hire = manifest.get("heroHireContract") or {}
    require(hero_hire.get("status") == "homm3_multi_hero", "manifest heroHireContract.status must be homm3_multi_hero", errors)
    require(hero_hire.get("heroCountMax") == 8, "manifest heroHireContract.heroCountMax must be 8", errors)
    poc_dir = str(repo_root / "experiments" / "campaign_port_poc")
    if poc_dir not in sys.path:
        sys.path.insert(0, poc_dir)
    import campaign_hero_level_cap
    import exact_homm3_footprint as exact_fp

    expected_homecoming_cap = campaign_hero_level_cap.handoff_level_cap_for_from_mission(
        "homecoming",
        repo_root=repo_root,
    )
    require(
        expected_homecoming_cap == 6,
        f"Homecoming H3M levelLimit must stay 6 (got {expected_homecoming_cap})",
        errors,
    )
    require(
        hero_hire.get("customHeroMaxLevel") == expected_homecoming_cap,
        "manifest heroHireContract.customHeroMaxLevel must match H3M Homecoming levelLimit "
        f"(expected {expected_homecoming_cap}, got {hero_hire.get('customHeroMaxLevel')!r})",
        errors,
    )
    require(
        hero_hire.get("enableCustomHeroMaxLevel") is True,
        "manifest heroHireContract.enableCustomHeroMaxLevel must be true for Homecoming",
        errors,
    )
    require(
        hero_hire.get("h3mLevelLimit") == expected_homecoming_cap,
        "manifest heroHireContract.h3mLevelLimit must match H3M Homecoming levelLimit",
        errors,
    )

    pack = manifest.get("emitPolicyPack") or {}
    require(pack.get("name") == "raw_translation", "emitPolicyPack.name must be raw_translation", errors)
    require(pack.get("apply_functional_emit_reservation") is True, "fer omit must be ON for raw_translation", errors)
    require(pack.get("suppress_exact_anchor_scenery") is False, "exact-anchor suppress must be OFF", errors)
    require(pack.get("suppress_underground_payloadless_scenery") is False, "UG scenery suppress must be OFF", errors)
    require(pack.get("apply_underground_tunnel_clearance") is True, "UG burrow clearance must be ON for 2x2 elev traversability", errors)
    require(pack.get("exact_homm3_footprints") is True, "exact_homm3_footprints must be ON for raw_translation", errors)
    require(
        pack.get("pickup_range_fallback_when_strict_fails") is True,
        "pickup_range_fallback_when_strict_fails must be ON for raw_translation",
        errors,
    )
    ug_clear_note = any(
        "ug tunnel clearance" in str(item).lower() or "underground tunnel clearance" in str(item).lower()
        for item in known_gaps
    )
    require(ug_clear_note, "profile knownGaps must document UG tunnel clearance ON", errors)

    br_policy = str(manifest.get("brNodeShiftPolicy") or "")
    require(
        "shape_class" in br_policy.lower()
        or "keep_donor" in br_policy.lower()
        or "visible_gap_fill" in br_policy.lower()
        or "exact_homm3" in br_policy.lower(),
        "brNodeShiftPolicy must name shape-class GATE-align/gate-on-visit + visible gap-fill",
        errors,
    )
    require("footprint_alignment" not in br_policy.lower(), "brNodeShiftPolicy must not say footprint_alignment", errors)
    require(
        "pivot" not in br_policy.lower(),
        "brNodeShiftPolicy must not name retired pivot-center placement",
        errors,
    )

    post = manifest.get("postPasses") or {}
    for key in DISABLED_POST_PASS_KEYS:
        entry = post.get(key) or {}
        status = str(entry.get("status") or "")
        require(
            status in {"disabled", "omitted"},
            f"postPasses.{key}.status must be disabled|omitted (got {status!r})",
            errors,
        )
    ug_clearance = post.get("undergroundTunnelClearance") or {}
    require(ug_clearance.get("status") == "applied", "postPasses.undergroundTunnelClearance must be applied", errors)
    require(
        ug_clearance.get("policy") == UNDERGROUND_TUNNEL_CLEARANCE_POLICY,
        "undergroundTunnelClearance policy pin",
        errors,
    )
    require(
        ug_clearance.get("contract") == EXPECTED_UNDERGROUND_TUNNEL_CLEARANCE,
        f"undergroundTunnelClearance contract mismatch: {ug_clearance.get('contract')}",
        errors,
    )
    visual_scenery = post.get("visualSceneryCanon") or {}
    if visual_scenery:
        require(
            visual_scenery.get("status") in {"applied", "skipped_by_flag", "reverted"},
            "postPasses.visualSceneryCanon.status must be applied|skipped_by_flag|reverted; "
            f"got {visual_scenery.get('status')!r}",
            errors,
        )
        require(
            "visualSceneryCanon" not in DISABLED_POST_PASS_KEYS,
            "visualSceneryCanon must not be listed in DISABLED_POST_PASS_KEYS",
            errors,
        )
    entrance = post.get("entranceOccupancy") or {}
    if entrance:
        require(
            entrance.get("status") == "applied",
            f"postPasses.entranceOccupancy.status must be applied; got {entrance.get('status')!r}",
            errors,
        )
        require(
            entrance.get("leftoverSuppressibleCount") == 0,
            "entranceOccupancy leftover suppressible count must be 0",
            errors,
        )
        require(
            "do_not_mutate_waterMap_levelsMap_climbsMap_or_ocean_geometry"
            in str(entrance.get("policy") or ""),
            "entranceOccupancy policy must refuse coastline / waterMap mutation",
            errors,
        )
        require(
            "entranceOccupancy" not in DISABLED_POST_PASS_KEYS,
            "entranceOccupancy must not be listed in DISABLED_POST_PASS_KEYS",
            errors,
        )
    spawn_unbury = post.get("spawnFootprintUnbury") or {}
    if spawn_unbury:
        require(
            spawn_unbury.get("status") in {"applied", "noop"},
            f"spawnFootprintUnbury.status must be applied|noop; got {spawn_unbury.get('status')!r}",
            errors,
        )
        require(
            "reject_envelope_padding" in str(spawn_unbury.get("policy") or ""),
            "spawnFootprintUnbury must reject envelope padding cliffs",
            errors,
        )
        require(
            "gate_visit" in str(spawn_unbury.get("policy") or "")
            or spawn_unbury.get("buryPolicy") == "gate_visit_cell_only",
            "spawnFootprintUnbury must use gate_visit_cell_only bury policy",
            errors,
        )

    require(manifest.get("parityPadCount") == 0, "parityPadCount must be 0", errors)
    landon = manifest.get("landonClones") or {}
    require(landon.get("status") == "enabled", "landonClones must be enabled", errors)
    landon_access = (manifest.get("postPasses") or {}).get("landonAccess") or {}
    require(landon_access.get("status") == "applied", "landonAccess post-pass must be applied", errors)
    require(
        (landon_access.get("guardhouseMarker") or {}).get("status") == "applied",
        "guardhouse marker relocate must be applied",
        errors,
    )
    require(
        (landon_access.get("guardhouseDialog") or {}).get("status") == "applied",
        "guardhouse dialog must bind to the persistent dwelling host",
        errors,
    )
    guardhouse_dialog = landon_access.get("guardhouseDialog") or {}
    require(
        guardhouse_dialog.get("hostLifetime") == "persistent_object",
        "guardhouse dialog hostLifetime must be persistent_object",
        errors,
    )
    require(
        guardhouse_dialog.get("eventLifetime") == "one_shot_no_host_delete",
        "guardhouse eventLifetime must be one_shot_no_host_delete",
        errors,
    )
    gate_face = (manifest.get("postPasses") or {}).get("gateFaceRotation") or {}
    require(
        gate_face.get("policy") == "raw_gated_mirror_rotation_to_free_cardinal_approach",
        "gateFaceRotation policy pin",
        errors,
    )
    require(
        gate_face.get("phase") == "after_final_occupancy",
        "gateFaceRotation must run after final occupancy",
        errors,
    )
    require(
        gate_face.get("status") == "generated_artifact_validator_runtime_unvalidated",
        "gateFaceRotation status pin",
        errors,
    )
    eligibility = gate_face.get("eligibility") or {}
    require(
        eligibility.get("requireAtLeastOneGate") is True,
        "gateFaceRotation must accept any gated canBeMirrored footprint",
        errors,
    )
    require(
        eligibility.get("requireExactlyOneGate") is False,
        "gateFaceRotation must not restrict to single-GATE-only",
        errors,
    )
    require(
        eligibility.get("maxFootprintCells") is None,
        "gateFaceRotation must not cap footprint size at 4 cells",
        errors,
    )
    require(
        (eligibility.get("blockerPolicy") or "")
        == "scenery_and_buildings_block_enemies_and_hero_spawners_ignored",
        "gateFaceRotation must ignore enemy/hero-spawner approach occupancy",
        errors,
    )
    require(
        sorted(eligibility.get("enemyNonblockingSids") or [])
        == ["hero-spawner", "random-squad"],
        "gateFaceRotation enemyNonblockingSids pin",
        errors,
    )
    require(
        "homm3_boat" in (eligibility.get("waterGateExemptSids") or []),
        "gateFaceRotation must water-exempt homm3_boat",
        errors,
    )
    require(
        (eligibility.get("terrainSealedSkipPolicy") or "")
        == "carve_void_neighbors_then_skip_when_no_land_cardinal_neighbor_any_rotation",
        "gateFaceRotation must carve void then skip water/void-sealed footprints",
        errors,
    )
    require(
        "portal_" not in (eligibility.get("visitBankGateExemptPrefixes") or []),
        "gateFaceRotation must not blanket-exempt portal_* (blocks subterranean gate rotation)",
        errors,
    )
    require(
        (eligibility.get("portalSoftUnresolvedPolicy") or "").startswith(
            "soft_skip_portal_prefix_when_still_sealed"
        ),
        "gateFaceRotation must soft-skip unresolved portal_* after rotation attempts",
        errors,
    )
    require(
        "homm3_subterranean_gate_portal"
        in (eligibility.get("subterraneanGateFailClosedSids") or []),
        "gateFaceRotation must fail-closed dedicated subterranean gate SID",
        errors,
    )
    require(
        isinstance(gate_face.get("skippedPortalApproachSealedInstanceCount"), int),
        "gateFaceRotation skippedPortalApproachSealedInstanceCount pin",
        errors,
    )
    require(gate_face.get("unresolvedCount") == 0, "gateFaceRotation must resolve all eligible objects", errors)
    require(
        isinstance(gate_face.get("skippedTerrainSealedInstanceCount"), int),
        "gateFaceRotation skippedTerrainSealedInstanceCount pin",
        errors,
    )
    rotated_rows = gate_face.get("rotated") or []
    require(isinstance(rotated_rows, list), "gateFaceRotation.rotated must be a list", errors)
    portal3 = next((row for row in rotated_rows if row.get("objectId") == 595), None)
    require(portal3 is not None, "gateFaceRotation must rotate portal_3 object 595", errors)
    if portal3 is not None:
        require(portal3.get("sid") == "portal_3", "gateFaceRotation object 595 must be portal_3", errors)
        require(portal3.get("fromRotation") == 0, "portal_3 595 fromRotation must be 0", errors)
        require(portal3.get("toRotation") == 10, "portal_3 595 toRotation must be 10 (mirror)", errors)
    exact = manifest.get("exactHomm3Footprints") or {}
    require(exact.get("status") == "enabled", "exactHomm3Footprints must be enabled", errors)
    exact_stats = exact.get("stats") or {}
    require(isinstance(exact_stats.get("sceneryCatalogMatch"), int), "exact footprint sceneryCatalogMatch pin", errors)
    require(int(exact_stats.get("sceneryCatalogMatch") or 0) > 0, "exact footprint must catalog-match some scenery", errors)
    require(isinstance(exact_stats.get("sceneryClone"), int), "exact footprint sceneryClone pin", errors)
    functional_mine_clone_count = int(exact_stats.get("functionalMineClone") or 0)
    functional_clone_count = int(
        exact_stats.get("functionalSameSizeClone")
        or exact_stats.get("functionalClone")
        or 0
    )
    require(
        functional_mine_clone_count > 0,
        "exact footprint must clone mine ObjectConfigs for functional footprint parity",
        errors,
    )
    require(
        functional_clone_count == functional_mine_clone_count,
        "exact footprint functional clones must be mine clones",
        errors,
    )
    require(
        int(exact_stats.get("functionalPointPickup") or 0) == 0,
        "exact footprint must not emit GATE-only point-pickup clones",
        errors,
    )
    require(
        int(exact_stats.get("functionalKeepDonor") or 0) > 0,
        "exact footprint must keep-donor functionals (native GATE markers + occupied body)",
        errors,
    )
    require(
        int(exact_stats.get("uniqueCloneSids") or 0)
        <= int(exact_stats.get("sceneryClone") or 0) + functional_mine_clone_count,
        "exact footprint uniqueCloneSids cannot exceed scenery plus functional mine clones",
        errors,
    )

    gap = manifest.get("pathabilityGapFill") or {}
    require(gap.get("status") == "applied", "pathabilityGapFill must be applied for traversal parity", errors)
    require(isinstance(gap.get("gapFillBlockerCount"), int), "gapFillBlockerCount pin", errors)
    require(int(gap.get("gapFillBlockerCount") or 0) > 0, "gap-fill blockers required for H3 overflow cells", errors)
    require(
        int(gap.get("gapFillDiagonalSqueezeSealCount") or 0) == 0
        or all(
            int((layer or {}).get("gapFillDiagonalSqueezeSealCount") or 0) == 0
            for layer in (gap.get("layers") or {}).values()
        ),
        "gap-fill must not invent diagonal-squeeze seals on H3-open cells",
        errors,
    )
    seal_policy_ok = gap.get("gapFillDiagonalSqueezeSealPolicy") == (
        "disabled_never_invent_blockers_on_h3_open_cells"
    ) or any(
        (layer or {}).get("gapFillDiagonalSqueezeSealPolicy")
        == "disabled_never_invent_blockers_on_h3_open_cells"
        for layer in (gap.get("layers") or {}).values()
    )
    require(seal_policy_ok, "gap-fill diagonal seal policy pin", errors)
    gap_after = manifest.get("pathabilityGapFillAfterLandonAccess") or {}
    if isinstance(gap_after, dict) and gap_after.get("status"):
        require(
            int(gap_after.get("gapFillDiagonalSqueezeSealCount") or 0) == 0,
            "post-landon gap-fill must not invent diagonal-squeeze seals",
            errors,
        )
    require(
        any(
            (layer or {}).get("pathingBlockerSid") == "mountain_dirt_small_1"
            for layer in (gap.get("layers") or {}).values()
        )
        or gap.get("pathingBlockerSid") == "mountain_dirt_small_1"
        or (
            isinstance(gap.get("gapFillSidHistogram"), dict)
            and all(
                isinstance(sid, str)
                and (
                    sid.startswith("mountain_")
                    or sid.startswith("tree_dead_")
                    or sid.startswith("pinetree")
                    or sid == "homm3_pathing_blocker"
                )
                for sid in gap.get("gapFillSidHistogram")
            )
            and int(gap.get("gapFillBlockerCount") or 0)
            == sum(int(v) for v in gap.get("gapFillSidHistogram").values())
        ),
        "raw gap-fill must use visible 1x1 blocking scenery (DEF-family or mountain_dirt_small_1)",
        errors,
    )

    scenery = manifest.get("homm3SceneryFootprint") or {}
    require(
        scenery.get("policy")
        == (
            "exact_homm3_traversal_shape_class_gate_on_visit_plus_visible_gap_fill_"
            "scenery_1x1_mountain_tree_rock_or_catalog_or_full_grid_clone_or_solid_square"
        ),
        "homm3SceneryFootprint policy pin missing",
        errors,
    )
    require(scenery.get("status") == "applied", "homm3SceneryFootprint must be applied", errors)

    overlay_manifest = root / "core_overlay" / "homecoming_exact_footprint_overlay_manifest.json"
    require(overlay_manifest.is_file(), f"missing exact footprint overlay manifest: {overlay_manifest}", errors)
    overlay_objects = root / "core_overlay" / "DB" / "map" / "objects" / "homecoming_exact_footprint_objects.json"
    require(overlay_objects.is_file(), f"missing exact footprint object overlay: {overlay_objects}", errors)
    if overlay_objects.is_file():
        overlay_doc = read_json(overlay_objects)
        rows = overlay_doc.get("array") if isinstance(overlay_doc, dict) else None
        require(isinstance(rows, list), "exact footprint object overlay must be an array doc", errors)
        functional_clone_ids: set[str] = set()
        functional_donor_sids: set[str] = set()
        for row in rows or []:
            if not isinstance(row, dict):
                errors.append("exact footprint overlay row is not an object")
                continue
            meta = row.get("homm3ExactFootprint")
            require(isinstance(meta, dict), f"exact footprint overlay {row.get('id')!r} missing meta", errors)
            if not isinstance(meta, dict):
                continue
            kind = meta.get("kind")
            require(kind in {"scenery", "functional"}, f"exact footprint overlay {row.get('id')!r} kind invalid", errors)
            require(
                meta.get("mode") == "same_size_nodes_plus_overflow_blockers",
                f"exact footprint overlay {row.get('id')!r} must use projected node-grid metadata",
                errors,
            )
            donor_sid = meta.get("donorSid")
            require(isinstance(donor_sid, str) and donor_sid, f"exact footprint overlay {row.get('id')!r} missing donorSid", errors)
            if kind == "functional":
                functional_clone_ids.add(str(row.get("id") or ""))
                functional_donor_sids.add(str(donor_sid))
                require(donor_sid in exact_fp.MINE_SIDS, f"functional exact clone donor {donor_sid!r} must use an exact mine donor", errors)
                require(row.get("canBeMirrored") is False, f"functional exact clone {row.get('id')!r} must be fixed-orientation", errors)
                require(isinstance(meta.get("gateConfig"), list) and len(meta.get("gateConfig")) == 2, f"functional exact clone {row.get('id')!r} missing gateConfig", errors)
            size_x, size_z = row.get("sizeX"), row.get("sizeZ")
            nodes = row.get("nodes")
            require(
                isinstance(size_x, int) and isinstance(size_z, int) and isinstance(nodes, list),
                f"exact footprint overlay {row.get('id')!r} missing size/nodes",
                errors,
            )
            if isinstance(nodes, list):
                require(
                    isinstance(size_x, int)
                    and isinstance(size_z, int)
                    and len(nodes) == size_x * size_z,
                    f"exact footprint overlay {row.get('id')!r} node-grid shape drift",
                    errors,
                )
                occ = sum(1 for value in nodes if int(value) == 1)
                require(
                    occ == int(meta.get("inGridBlockCount") or occ),
                    f"exact footprint overlay {row.get('id')!r} inGridBlockCount drift",
                    errors,
                )
                if kind == "functional":
                    require(
                        sum(1 for value in nodes if int(value) == 2) == 1,
                        f"functional exact clone {row.get('id')!r} must have one GATE cell",
                        errors,
                    )
                if kind == "scenery":
                    open_cells = sum(1 for value in nodes if int(value) == 0)
                    require(
                        not (open_cells > 0 and occ > 0),
                        f"exact footprint overlay {row.get('id')!r} has mesh-overhang "
                        f"holes (open={open_cells} occ={occ}); sparsened donor meshes "
                        f"are forbidden",
                        errors,
                    )

        require(
            functional_donor_sids == set(exact_fp.MINE_SIDS),
            "exact footprint functional clone donor coverage must include all native mine families",
            errors,
        )

        logic_overlay = root / "core_overlay" / "DB" / "objects_logic" / "res_mines" / "mines.json"
        if functional_clone_ids:
            require(logic_overlay.is_file(), f"missing exact footprint mine logic overlay: {logic_overlay}", errors)
            logic_rows = []
            if logic_overlay.is_file():
                logic_doc = read_json(logic_overlay)
                logic_rows = logic_doc.get("array") if isinstance(logic_doc, dict) else None
                require(isinstance(logic_rows, list), "exact footprint mine logic overlay must be an array doc", errors)
            logic_rows_by_id = {
                str(row.get("id")): row
                for row in logic_rows or []
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            logic_ids = set(logic_rows_by_id)
            require(
                functional_clone_ids <= logic_ids,
                "exact footprint mine logic overlay must contain every functional object clone",
                errors,
            )
            require(
                set(exact_fp.MINE_SIDS) <= logic_ids,
                "exact footprint mine logic overlay must retain every native mine donor row",
                errors,
            )
            for row in rows or []:
                meta = row.get("homm3ExactFootprint") if isinstance(row, dict) else None
                if not isinstance(meta, dict) or meta.get("kind") != "functional":
                    continue
                clone_id = str(row.get("id") or "")
                donor_id = str(meta.get("donorSid") or "")
                donor_logic = logic_rows_by_id.get(donor_id)
                clone_logic = logic_rows_by_id.get(clone_id)
                require(isinstance(donor_logic, dict), f"missing native mine logic donor row {donor_id!r}", errors)
                require(isinstance(clone_logic, dict), f"missing mine logic clone row {clone_id!r}", errors)
                if isinstance(donor_logic, dict) and isinstance(clone_logic, dict):
                    expected_logic = json.loads(json.dumps(donor_logic))
                    expected_logic["id"] = clone_id
                    require(clone_logic == expected_logic, f"mine logic clone {clone_id!r} drifted from donor {donor_id!r}", errors)

    overlap = manifest.get("occupiedOverlapDiagnostic") or {}
    require(overlap.get("status") == "intentional_diagnostic", "occupiedOverlapDiagnostic status pin", errors)
    require(isinstance(overlap.get("overlappedCellCount"), int), "overlappedCellCount must be int", errors)

    gt_pin = manifest.get("placementGroundTruth") or {}
    require(gt_pin.get("status") == "applied", "placementGroundTruth must be applied", errors)
    require(
        gt_pin.get("schema") == "homm3.olden_raw_translation_placement_ground_truth.v1",
        "placementGroundTruth schema pin",
        errors,
    )
    gt_rel = gt_pin.get("artifact")
    require(isinstance(gt_rel, str) and gt_rel, "placementGroundTruth.artifact missing", errors)
    gt_path = repo_root / str(gt_rel)
    require(gt_path.is_file(), f"missing placement ground truth: {gt_path}", errors)
    if gt_path.is_file():
        gt = read_json(gt_path)
        require(gt.get("schema") == "homm3.olden_raw_translation_placement_ground_truth.v1", "gt schema", errors)
        require(gt.get("mapSid") == MAP_SID, "gt mapSid mismatch", errors)
        require(gt.get("pipeline") == "raw_translation", "gt pipeline mismatch", errors)
        placements = gt.get("placements")
        require(isinstance(placements, list) and placements, "gt placements must be non-empty", errors)
        stats = gt.get("stats") or {}
        require(isinstance(stats.get("emittedCount"), int) and stats["emittedCount"] > 1000, "gt emittedCount too low", errors)
        require(stats.get("emittedSidMismatchCount") == 0, "gt emittedSidMismatchCount must be 0", errors)
        require(stats.get("missingFromEmitCount") == 0, "gt missingFromEmitCount must be 0", errors)
        # Spot-check: every emitted row has h3 + mapping + olden.
        sample = [row for row in placements if row.get("emitStatus") == "emitted"][:20]
        for row in sample:
            require(isinstance(row.get("h3"), dict), "gt sample missing h3", errors)
            require(isinstance(row.get("mapping"), dict), "gt sample missing mapping", errors)
            require(isinstance(row.get("olden"), dict), "gt sample missing olden", errors)
            require(isinstance((row.get("h3") or {}).get("templateBlockMask"), list), "gt h3 block mask", errors)
            require(isinstance((row.get("mapping") or {}).get("ruleName"), str), "gt mapping ruleName", errors)
            require(isinstance((row.get("olden") or {}).get("sid"), str), "gt olden sid", errors)
            require(isinstance((row.get("olden") or {}).get("node"), int), "gt olden node", errors)
            require(isinstance((row.get("olden") or {}).get("occupiedNodes"), list), "gt olden occupied", errors)
        # Scenery must not emit OE OCC larger than the H3 block mask (except documented
        # functional keep-donor buildings such as college_of_wonder).
        tools_dir = str(repo_root / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        poc_dir = str(repo_root / "experiments" / "campaign_port_poc")
        if poc_dir not in sys.path:
            sys.path.insert(0, poc_dir)
        import functional_emit_reservation as fer  # noqa: WPS433
        from validate_scenery_footprint_oe_larger_contract import (  # noqa: WPS433
            INTENTIONAL_OE_LARGER_SIDS,
            audit_mission as audit_scenery_oe_larger,
            load_core_configs,
        )

        suppressible = set(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS)
        core_configs = load_core_configs(
            DEFAULT_GAME_ROOT / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
        )
        # `root` is .../homecoming_poc/raw_translation_map; audit wants the mission artifact root.
        mission_root = root.parent
        oe_violations = audit_scenery_oe_larger(mission_root, core_configs, suppressible)
        require(
            not oe_violations,
            "scenery OE-larger than H3 block mask: "
            + "; ".join(
                f"{v.get('sourceKey')}:{v.get('sid')} H3={v.get('h3Cells')} OE={v.get('oeCells')}"
                for v in oe_violations[:8]
            )
            + f" (intentional exceptions={sorted(INTENTIONAL_OE_LARGER_SIDS)})",
            errors,
        )
        # Squads must keep native random-squad (node-rewritten clones render as ?).
        squad_sids = {
            str((row.get("olden") or {}).get("sid") or "")
            for row in placements
            if row.get("emitStatus") == "emitted"
            and "random_squad" in str((row.get("mapping") or {}).get("ruleName") or "")
        }
        require(squad_sids == {"random-squad"}, f"monster stacks must use random-squad SID, got {sorted(squad_sids)}", errors)
        # Human start is Caryatid City+spawnHero (map hero-spawner retired). Placement
        # report may still list a historical start_hero row as omitted; prefer live map bind.
        hero_rows = [
            row
            for row in placements
            if row.get("emitStatus") == "emitted"
            and (row.get("olden") or {}).get("sid") == "hero-spawner"
            and "start_hero" in str((row.get("mapping") or {}).get("ruleName") or "")
        ]
        require(
            len(hero_rows) <= 1,
            f"expected at most one start hero-spawner placement row, got {len(hero_rows)}",
            errors,
        )
        if hero_rows:
            olden = hero_rows[0].get("olden") or {}
            gates = olden.get("gateNodes") or []
            visits = olden.get("homm3VisitNodes") or []
            require(gates == visits, f"start hero GATE {gates} must equal visit {visits}", errors)
        # Random-squad GATE-on-visit: emit node equals H3 visit (runtime stand follows emit).
        # Do not require visit to be the open ring center (retired pivot-center model).
        squad_misaligned = 0
        for row in placements:
            if row.get("emitStatus") != "emitted":
                continue
            if (row.get("olden") or {}).get("sid") != "random-squad":
                continue
            olden = row.get("olden") or {}
            visits = olden.get("homm3VisitNodes") or []
            gates = set(olden.get("gateNodes") or [])
            node = olden.get("node")
            if len(visits) != 1 or not isinstance(node, int):
                squad_misaligned += 1
                continue
            visit = visits[0]
            if node != visit or visit not in gates:
                squad_misaligned += 1
        require(
            squad_misaligned == 0,
            f"random-squad emit-on-visit misaligned count={squad_misaligned}",
            errors,
        )
        # Guard next to artifact at hero-debug cell: emit must equal H3 visit (not -1,-1).
        guard_row = next((row for row in placements if row.get("sourceKey") == "0:48:50"), None)
        require(isinstance(guard_row, dict), "GT missing guard stack 0:48:50", errors)
        if isinstance(guard_row, dict):
            olden = guard_row.get("olden") or {}
            visits = olden.get("homm3VisitNodes") or []
            require(guard_row.get("emitStatus") == "emitted", "0:48:50 must be emitted", errors)
            require(olden.get("sid") == "random-squad", "0:48:50 must stay random-squad", errors)
            require(
                len(visits) == 1 and olden.get("node") == visits[0],
                f"0:48:50 emit must equal H3 visit; node={olden.get('node')} visit={visits}",
                errors,
            )
        # Mountains/trees must be 1x1 solid SIDs only (multi-tile meshes overhang H3-open).
        multi_tile_scenery = [
            (row.get("sourceKey"), (row.get("olden") or {}).get("sid"), len((row.get("olden") or {}).get("occupiedNodes") or []))
            for row in placements
            if row.get("emitStatus") == "emitted"
            and (
                str((row.get("olden") or {}).get("sid") or "").startswith("mountain_")
                or str((row.get("olden") or {}).get("sid") or "").startswith("tree_")
                or str((row.get("olden") or {}).get("sid") or "").startswith("pinetree")
            )
            and len((row.get("olden") or {}).get("occupiedNodes") or []) > 1
        ]
        require(
            multi_tile_scenery == [],
            f"mountain/tree multi-tile OCC forbidden (use 1x1 + gap-fill); examples={multi_tile_scenery[:8]}",
            errors,
        )
        # Subterranean gates: scorched-earth 2x2 [1,2,2,2]; preferred GATE on H3 visit.
        portal_rows = [
            row
            for row in placements
            if row.get("emitStatus") == "emitted"
            and (row.get("olden") or {}).get("sid") == HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
        ]
        portal_keys = sorted(str(row.get("sourceKey") or "") for row in portal_rows)
        require(
            portal_keys == sorted(EXPECTED_SUBTERRANEAN_GATE_SOURCE_KEYS),
            f"expected subterranean gate ends {sorted(EXPECTED_SUBTERRANEAN_GATE_SOURCE_KEYS)}; got {portal_keys}",
            errors,
        )
        occupied_by_foreign: dict[int, list[str]] = {}
        for row in placements:
            if row.get("emitStatus") != "emitted":
                continue
            olden = row.get("olden") or {}
            sid = str(olden.get("sid") or "")
            oid = olden.get("objectId")
            for node in olden.get("occupiedNodes") or []:
                if not isinstance(node, int):
                    continue
                occupied_by_foreign.setdefault(node, []).append(f"{sid}#{oid}")
        for row in portal_rows:
            olden = row.get("olden") or {}
            gates = olden.get("gateNodes") or []
            visits = olden.get("homm3VisitNodes") or []
            oid = olden.get("objectId")
            require(
                len(gates) == EXPECTED_SUBTERRANEAN_GATE_COUNT,
                f"subterranean gate {row.get('sourceKey')} must have {EXPECTED_SUBTERRANEAN_GATE_COUNT} GATE "
                f"markers (scorched-earth); gates={gates}",
                errors,
            )
            require(
                isinstance(visits, list) and len(visits) == 1 and visits[0] in gates,
                f"subterranean gate {row.get('sourceKey')} preferred/visit GATE must coincide with H3 visit; "
                f"gates={gates} visits={visits}",
                errors,
            )
            for gate in gates:
                if not isinstance(gate, int):
                    continue
                foreign = [
                    owner
                    for owner in occupied_by_foreign.get(gate, [])
                    if not owner.endswith(f"#{oid}")
                ]
                require(
                    foreign == [],
                    f"subterranean gate {row.get('sourceKey')} GATE {gate} buried by OCC {foreign}",
                    errors,
                )
        # NW mountain at hero-debug (source 0:47:47 mountain plant): must be 1x1 small.
        nw_mountains = [
            row
            for row in placements
            if row.get("sourceKey") == "0:47:47"
            and row.get("emitStatus") == "emitted"
            and str((row.get("olden") or {}).get("sid") or "").startswith("mountain_")
        ]
        require(len(nw_mountains) >= 1, "GT missing mountain plant 0:47:47", errors)
        for row in nw_mountains:
            olden = row.get("olden") or {}
            sid = str(olden.get("sid") or "")
            occ = olden.get("occupiedNodes") or []
            require(
                "big" not in sid and len(occ) == 1,
                f"0:47:47 mountain must be 1x1 small; sid={sid} occ={occ}",
                errors,
            )
        # Archer's Tower (AVGcros): H3 is visit+one block only. Landon must not invent a 3x3 OCC.
        archer_rows = [
            row
            for row in placements
            if row.get("sourceKey") == "0:15:45"
            and row.get("emitStatus") == "emitted"
            and str((row.get("olden") or {}).get("sid") or "").startswith("homm3_landon_barracks")
        ]
        require(len(archer_rows) == 1, f"expected one Archer's Tower landon row at 0:15:45; got {len(archer_rows)}", errors)
        if archer_rows:
            olden = archer_rows[0].get("olden") or {}
            visits = olden.get("homm3VisitNodes") or []
            occ = olden.get("occupiedNodes") or []
            gates = olden.get("gateNodes") or []
            require(occ == [], f"0:15:45 must not invent OCC; occupied={occ}", errors)
            require(
                len(visits) == 1 and olden.get("node") == visits[0] and visits[0] in set(gates),
                f"0:15:45 emit/GATE must equal H3 visit; node={olden.get('node')} visit={visits} gates={gates}",
                errors,
            )
        # Towns: landon cities center one north of H3 body (GATE = south-center of
        # that 3x3); do not require GATE == H3 visit (courtyard row stays open).
        # Interact uses CornerLeft at LeftBottom (1,2) — not InteractionLayout.Bottom
        # (Bottom shifts interact one cell south of the building).
        for row in placements:
            if row.get("emitStatus") != "emitted":
                continue
            olden = row.get("olden") or {}
            sid = str(olden.get("sid") or "")
            if "landon" not in sid or "city" not in sid:
                continue
            visits = olden.get("homm3VisitNodes") or []
            gates = olden.get("gateNodes") or []
            occupied = olden.get("occupiedNodes") or []
            require(olden.get("rotation") == 0, f"{row.get('sourceKey')} town must not mirror (rot 0); got {olden.get('rotation')}", errors)
            require(len(visits) == 1, f"{row.get('sourceKey')} town needs one H3 visit; got {visits}", errors)
            require(len(gates) == 1, f"{row.get('sourceKey')} town needs one GATE; got {gates}", errors)
            require(olden.get("landonGateAligned") is True, f"{row.get('sourceKey')} must mark landonGateAligned", errors)
            # Body-center flag is set by regenerated ground truth; until then accept
            # south-center GATE geometry (emit SW of GATE, 8 occupied body cells).
            if "landonBodyCenterAligned" in olden:
                require(
                    olden.get("landonBodyCenterAligned") is True,
                    f"{row.get('sourceKey')} must mark landonBodyCenterAligned",
                    errors,
                )
            # South-center GATE of a 3x3: GATE is the sole south-row middle cell; body sits north.
            require(
                isinstance(olden.get("node"), int) and bool(gates) and gates[0] != olden.get("node"),
                f"{row.get('sourceKey')} landon emit must be SW of south-center GATE; "
                f"node={olden.get('node')} gate={gates}",
                errors,
            )
            require(
                len(occupied) == 8,
                f"{row.get('sourceKey')} landon city must occupy 8 body cells; got {len(occupied)}",
                errors,
            )
        # GATE-ring pickups (gold/chest/item/resource): H3 visit must stay on a GATE
        # cell with occupied body off the visit. Emit node may be another GATE cell
        # of the same ring only when the visit-emit footprint hits mine OCC.
        # Native generator buildings (watchtower, mana_well, ...) share the 3x3 ring shape
        # but are anchored at their pivot on the H3 source anchor, not visit-on-GATE.
        sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
        import exact_homm3_footprint as exact_fp_mod

        object_configs = _load_object_configs(root)
        pickup_misaligned = 0
        for row in placements:
            if row.get("emitStatus") != "emitted":
                continue
            olden = row.get("olden") or {}
            sid = str(olden.get("sid") or "")
            if sid.startswith("homm3_xfp_"):
                # XFP rows are payloadless scenery clones, not pickups. They
                # have no GATE ring by design and must not enter this check.
                continue
            gates = set(olden.get("gateNodes") or [])
            occupied = set(olden.get("occupiedNodes") or [])
            if len(gates) < 4 or len(occupied) != 1:
                continue
            if sid == "random-squad":
                continue
            if exact_fp_mod.uses_native_building_anchor_policy(object_configs.get(sid) or {}):
                continue
            visits = olden.get("homm3VisitNodes") or []
            if len(visits) != 1:
                pickup_misaligned += 1
                continue
            visit = visits[0]
            if visit not in gates or visit in occupied:
                pickup_misaligned += 1
        require(
            pickup_misaligned == 0,
            f"gate_ring pickup visit-on-GATE misaligned count={pickup_misaligned}",
            errors,
        )
        # Monster stacks must emit as random-squad (property discovery must not
        # false-defer whitelisted SIDs via propSquads / dual Ai-intent spellings).
        monster_rows = [
            row
            for row in placements
            if (row.get("h3") or {}).get("category") == "monster_stack"
        ]
        missing_monsters = [
            str(row.get("sourceKey") or "")
            for row in monster_rows
            if row.get("emitStatus") == "missing_from_emit"
        ]
        require(
            missing_monsters == [],
            f"monster stacks must not be property-deferred; missing={missing_monsters[:12]}",
            errors,
        )
        # Prefer-visit among clear pickups is pinned by
        # approach_cell/proof_emit_deferral_and_pickup_anchor.py (source/static).
        # Stables-adjacent wood pile must keep visit-on-GATE but shift emit off the sawmill body.
        wood_row = next((row for row in placements if row.get("sourceKey") == "0:56:54"), None)
        require(isinstance(wood_row, dict), "GT missing stables-adjacent wood 0:56:54", errors)
        if isinstance(wood_row, dict):
            olden = wood_row.get("olden") or {}
            visits = olden.get("homm3VisitNodes") or []
            gates = set(olden.get("gateNodes") or [])
            require(olden.get("sid") == "resource_wood", "0:56:54 must remain resource_wood", errors)
            require(len(visits) == 1 and visits[0] in gates, "0:56:54 visit must stay on GATE", errors)
            # The pile must keep its body off the adjacent sawmill. Whether that needs a
            # re-anchor off the visit depends on where the mine clone sits; with clones on
            # the native pivot projection the visit-emit body is already clear.
            mine_occupied = {
                node
                for other in placements
                if other.get("emitStatus") == "emitted"
                and (other.get("h3") or {}).get("category") == "mine"
                for node in ((other.get("olden") or {}).get("occupiedNodes") or [])
            }
            wood_occupied = set(olden.get("occupiedNodes") or [])
            require(
                bool(wood_occupied) and not (wood_occupied & mine_occupied),
                f"0:56:54 body must stay off mine OCC; occupied={sorted(wood_occupied)} "
                f"mineOverlap={sorted(wood_occupied & mine_occupied)}",
                errors,
            )
        # Shared source cell 0:49:55: stables (functional) + green mountain (scenery).
        # FER must not omit the mountain for stables keep-donor OCC outside H3 visit∪block.
        # Mountain is 1x1-only (no *_big_* overhang); H3-blocked atlas (52,22)/3572 must
        # stay Olden-occupied (stables footprint and/or gap-fill — not by multi-tile mountain).
        stables_rows = [row for row in placements if row.get("sourceKey") == "0:49:55"]
        mountain_row = next(
            (
                row
                for row in stables_rows
                if str((row.get("h3") or {}).get("templateAnimation") or "") == "AVLmtgr2.def"
            ),
            None,
        )
        stables_row = next(
            (
                row
                for row in stables_rows
                if str((row.get("h3") or {}).get("templateAnimation") or "") == "AVXstbl0.def"
            ),
            None,
        )
        require(isinstance(mountain_row, dict), "GT missing stables-cell mountain AVLmtgr2.def at 0:49:55", errors)
        require(isinstance(stables_row, dict), "GT missing stables AVXstbl0.def at 0:49:55", errors)
        if isinstance(mountain_row, dict):
            require(
                mountain_row.get("emitStatus") == "emitted",
                f"0:49:55 mountain must be emitted (not FER-omitted); got {mountain_row.get('emitStatus')}",
                errors,
            )
            olden = mountain_row.get("olden") or {}
            sid = str(olden.get("sid") or "")
            occupied = olden.get("occupiedNodes") or []
            require(
                sid.startswith("mountain_") and "big" not in sid and len(occupied) == 1,
                f"0:49:55 mountain must be 1x1 small; sid={sid} occ={occupied}",
                errors,
            )
        if isinstance(stables_row, dict):
            require(
                stables_row.get("emitStatus") == "emitted",
                f"0:49:55 stables must remain emitted; got {stables_row.get('emitStatus')}",
                errors,
            )
            require(
                (stables_row.get("olden") or {}).get("sid") == "stables",
                "0:49:55 stables sid must remain stables",
                errors,
            )
        hero_empty_cell_node = 22 * 160 + 52  # atlas (52,22)
        cell_3572_owners = [
            (row.get("sourceKey"), (row.get("olden") or {}).get("sid"))
            for row in placements
            if row.get("emitStatus") == "emitted"
            and hero_empty_cell_node in set((row.get("olden") or {}).get("occupiedNodes") or [])
        ] + [
            (f"synthetic:{row.get('objectId')}", row.get("sid"))
            for row in (gt.get("syntheticObjects") or [])
            if isinstance(row, dict) and hero_empty_cell_node in set(row.get("occupiedNodes") or [])
        ]
        require(
            cell_3572_owners != [],
            f"H3-blocked atlas (52,22)/{hero_empty_cell_node} must stay Olden-occupied; owners={cell_3572_owners}",
            errors,
        )
        # Chest-adjacent snow wall: GATE-ring reservation previously omitted mountains
        # whose H3 blocks sit on chest GATE cells (atlas ~42,31). Must emit; residual
        # cells may be sealed by gap-fill when solid-square undersizes (map pin below).
        snow_mtn = next((row for row in placements if row.get("sourceKey") == "0:41:44"), None)
        require(isinstance(snow_mtn, dict), "GT missing snow mountain 0:41:44", errors)
        if isinstance(snow_mtn, dict):
            require(
                snow_mtn.get("emitStatus") == "emitted",
                f"0:41:44 snow mountain must be emitted (not GATE-ring FER-omitted); got {snow_mtn.get('emitStatus')}",
                errors,
            )
            olden = snow_mtn.get("olden") or {}
            require(
                str(olden.get("sid") or "").startswith("mountain_snow"),
                f"0:41:44 must stay mountain_snow_*; got {olden.get('sid')}",
                errors,
            )
        wind_rose_rows = [
            row
            for row in placements
            if row.get("emitStatus") == "emitted" and (row.get("olden") or {}).get("sid") == "wind_rose"
        ]
        require(wind_rose_rows == [], f"GT must not emit wind_rose; got {len(wind_rose_rows)}", errors)
        windmill_rows = [
            row
            for row in placements
            if row.get("emitStatus") == "emitted" and (row.get("olden") or {}).get("sid") == "windmill"
        ]
        require(len(windmill_rows) >= 6, f"GT must emit >=6 windmills; got {len(windmill_rows)}", errors)
        # Pickup clones must not invent gateInsideObject (native resource_* leave it unset).
        overlay_custom = root / "core_overlay" / "DB" / "map" / "objects" / "homecoming_custom_objects.json"
        if overlay_custom.is_file():
            custom_doc = read_json(overlay_custom)
            by_id = {
                row.get("id"): row
                for row in (custom_doc.get("array") or [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            require(
                "homm3_random_resource_pickup" not in by_id,
                "retired gold-skin random resource clone must not remain in raw overlay",
                errors,
            )
            for sid in ("homm3_flotsam_pickup",):
                row = by_id.get(sid)
                require(isinstance(row, dict), f"raw overlay missing {sid}", errors)
                if isinstance(row, dict):
                    require(
                        "gateInsideObject" not in row or row.get("gateInsideObject") in (None, False),
                        f"{sid} must leave gateInsideObject unset; got {row.get('gateInsideObject')!r}",
                        errors,
                    )
        require(
            isinstance(stats.get("ferOmittedCount"), int),
            "gt ferOmittedCount pin",
            errors,
        )
        # Recompute join integrity: emitted ids exist on map objects.
        map_path = root / "maps" / f"{MAP_SID}.map"
        if map_path.is_file():
            import gzip
            import struct

            raw = map_path.read_bytes()
            # Olden map container: use port helper if available; else skip deep join.
            try:
                sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
                import port_homecoming_poc as poc

                container = poc.read_olden_map_container(map_path)
                map_data = container.chunks[1]
                validate_underground_tunnel_clearance_arrays(repo_root, map_data, errors)
                by_id: dict[int, str] = {}
                for group in map_data.get("objects") or []:
                    sid = str(group.get("sid") or "")
                    for object_id in group.get("ids") or []:
                        if isinstance(object_id, int):
                            by_id[object_id] = sid
                mismatches = 0
                checked = 0
                for row in placements:
                    if row.get("emitStatus") != "emitted":
                        continue
                    olden = row.get("olden") or {}
                    oid = olden.get("objectId")
                    sid = olden.get("sid")
                    if not isinstance(oid, int) or not isinstance(sid, str):
                        continue
                    checked += 1
                    if by_id.get(oid) != sid:
                        mismatches += 1
                        if mismatches <= 5:
                            errors.append(
                                f"gt↔map join mismatch id={oid} gtSid={sid} mapSid={by_id.get(oid)}"
                            )
                require(checked > 1000, f"gt↔map join checked too few emitted rows: {checked}", errors)
                require(mismatches == 0, f"gt↔map join mismatches: {mismatches}", errors)
                # Chest-adjacent H3 block atlas (42,31) must be Olden-occupied (source mountain
                # and/or gap-fill). Previously empty because GATE-ring FER + gap GATE skip.
                try:
                    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
                    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc" / "approach_cell"))
                    import port_homecoming_poc as poc_core
                    import surface_emit as se
                    import zipfile

                    configs: dict[str, dict] = {}
                    with zipfile.ZipFile(poc_core.OLDEN_CORE_ZIP) as zf:
                        for name in zf.namelist():
                            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                                continue
                            for row in json.loads(zf.read(name).decode("utf-8-sig")).get("array") or []:
                                if isinstance(row, dict) and isinstance(row.get("id"), str):
                                    configs[row["id"]] = row
                    overlay_dir = root / "core_overlay" / "DB" / "map" / "objects"
                    if overlay_dir.is_dir():
                        for overlay_path in overlay_dir.glob("*.json"):
                            for row in (read_json(overlay_path).get("array") or []):
                                if isinstance(row, dict) and isinstance(row.get("id"), str):
                                    configs[row["id"]] = row
                    prev_w, prev_h = se.OLDEN_WIDTH, se.OLDEN_HEIGHT
                    se.OLDEN_WIDTH, se.OLDEN_HEIGHT = 160, 80
                    chest_gate_block_node = 31 * 160 + 42
                    occupied = False
                    owners: list[str] = []
                    for group in map_data.get("objects") or []:
                        if not isinstance(group, dict):
                            continue
                        sid = str(group.get("sid") or "")
                        cfg = configs.get(sid)
                        if not isinstance(cfg, dict):
                            continue
                        for oid, node, rot in zip(
                            group.get("ids") or [],
                            group.get("nodes") or [],
                            group.get("rotations") or [],
                        ):
                            if not isinstance(node, int):
                                continue
                            for occ_node in se.occupied_nodes_for_object_instance(
                                sid, cfg, node, int(rot or 0)
                            ):
                                if occ_node == chest_gate_block_node:
                                    occupied = True
                                    owners.append(f"{sid}:{oid}")
                    se.OLDEN_WIDTH, se.OLDEN_HEIGHT = prev_w, prev_h
                    # The cell is also a GATE of the chest's native ring. The entrance
                    # occupancy contract clears suppressible scenery on interactable GATE
                    # cells, so an open cell is accepted only when it is such a GATE.
                    chest_gate_hosts = [
                        (row.get("sourceKey"), (row.get("olden") or {}).get("sid"))
                        for row in placements
                        if row.get("emitStatus") == "emitted"
                        and (row.get("olden") or {}).get("sid") == "chest"
                        and chest_gate_block_node in set((row.get("olden") or {}).get("gateNodes") or [])
                    ]
                    require(
                        occupied or bool(chest_gate_hosts),
                        f"atlas (42,31)/node {chest_gate_block_node} must be Olden-occupied or a chest GATE "
                        f"opened by entrance occupancy; owners={owners[:8]} chestGateHosts={chest_gate_hosts}",
                        errors,
                    )
                except Exception as ex:
                    errors.append(f"chest-adjacent (42,31) occupancy pin raised: {ex}")
                # Vanilla PropResParam contract: fixed resource_* use value=0.
                gold_ids = {
                    int(oid)
                    for group in (map_data.get("objects") or [])
                    if isinstance(group, dict) and str(group.get("sid") or "").startswith("resource_")
                    for oid in (group.get("ids") or [])
                    if isinstance(oid, int)
                }
                res_rows = ((map_data.get("objectsProperties") or {}).get("propResParams") or [])
                bad_values = [
                    row
                    for row in res_rows
                    if isinstance(row, dict)
                    and isinstance(row.get("id"), int)
                    and row["id"] in gold_ids
                    and row.get("value") != 0
                ]
                require(
                    len(bad_values) == 0,
                    f"resource_* propResParams must use value=0 like native maps; bad={bad_values[:5]}",
                    errors,
                )
                require(
                    any(isinstance(row, dict) and row.get("id") in gold_ids for row in res_rows),
                    "resource_* propResParams rows missing from map",
                    errors,
                )
                # Glittering Strait / Thirst shell: full area rows + custom areas + scenario flag.
                required_area_keys = {"id", "keyObjectId", "rootNode", "nodes", "neighbors", "biome"}
                areas = map_data.get("areas") or []
                require(isinstance(areas, list) and len(areas) >= 1, "areas missing", errors)
                if areas:
                    area0 = areas[0] if isinstance(areas[0], dict) else {}
                    missing = sorted(required_area_keys - set(area0))
                    require(not missing, f"area[0] missing native keys {missing}", errors)
                require(map_data.get("haveCustomAreas") is True, "haveCustomAreas must be true like Glittering Strait", errors)
                require(
                    isinstance(map_data.get("areasVersion"), int) and int(map_data["areasVersion"]) > 1,
                    f"areasVersion must be >1 like native maps; got {map_data.get('areasVersion')!r}",
                    errors,
                )
                require(isinstance(map_data.get("keyObjects"), list) and map_data["keyObjects"], "keyObjects must list town ids", errors)
                require((map_data.get("settings") or {}).get("isScenario") is True, "settings.isScenario must be true", errors)
                settings = map_data.get("settings") or {}
                require(
                    settings.get("heroCountMin") == 1 and settings.get("heroCountMax") == 8,
                    "HoMM3 Homecoming is multi-hero; settings must use heroCountMin=1 heroCountMax=8 "
                    f"(got min={settings.get('heroCountMin')!r} max={settings.get('heroCountMax')!r})",
                    errors,
                )
                poc_dir = str(repo_root / "experiments" / "campaign_port_poc")
                if poc_dir not in sys.path:
                    sys.path.insert(0, poc_dir)
                import campaign_hero_level_cap

                expected_cap = campaign_hero_level_cap.handoff_level_cap_for_from_mission(
                    "homecoming",
                    repo_root=repo_root,
                )
                expected_settings = campaign_hero_level_cap.olden_custom_hero_max_level_settings(
                    expected_cap
                )
                require(
                    settings.get("enableCustomHeroMaxLevel")
                    is expected_settings["enableCustomHeroMaxLevel"]
                    and settings.get("customHeroMaxLevel")
                    == expected_settings["customHeroMaxLevel"],
                    "H3M Homecoming level cap must drive enableCustomHeroMaxLevel/"
                    f"customHeroMaxLevel={expected_settings['customHeroMaxLevel']} "
                    f"(got enable={settings.get('enableCustomHeroMaxLevel')!r} "
                    f"level={settings.get('customHeroMaxLevel')!r})",
                    errors,
                )
                city_rows = (map_data.get("objectsProperties") or {}).get("propCities") or []
                require(isinstance(city_rows, list) and city_rows, "propCities missing for tavern-ban pin", errors)
                for city in city_rows:
                    if not isinstance(city, dict):
                        continue
                    ban_sid = city.get("buildingsBanSid")
                    require(
                        ban_sid == "default_buildings_ban",
                        f"city {city.get('id')} must keep default_buildings_ban (tavern allowed); "
                        f"got {ban_sid!r} — homecoming_campaign_buildings_ban bans Build_Tavern",
                        errors,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"gt↔map join failed: {exc}")

    # Core overlay may ship a blocker-only pathability alignment member for overflow
    # H3 cells. Visual-clone rows remain forbidden on raw_translation.
    overlay = root / "core_overlay"
    require(overlay.is_dir(), f"missing core_overlay: {overlay}", errors)
    portal_object_path = overlay / HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER
    portal_logic_path = overlay / HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER
    require(portal_object_path.is_file(), f"missing subterranean portal object overlay: {portal_object_path}", errors)
    require(portal_logic_path.is_file(), f"missing subterranean portal logic overlay: {portal_logic_path}", errors)
    if portal_object_path.is_file() and portal_logic_path.is_file():
        object_doc = read_json(portal_object_path)
        logic_doc = read_json(portal_logic_path)
        object_rows = {
            row.get("id"): row
            for row in (object_doc.get("array") if isinstance(object_doc, dict) else [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        logic_rows = {
            row.get("id"): row
            for row in (logic_doc.get("array") if isinstance(logic_doc, dict) else [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        donor = object_rows.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID)
        portal_row = object_rows.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
        require(isinstance(donor, dict), f"overlay missing donor {HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID}", errors)
        require(isinstance(portal_row, dict), f"overlay missing {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}", errors)
        if isinstance(donor, dict) and isinstance(portal_row, dict):
            expected = json.loads(json.dumps(donor, ensure_ascii=False))
            expected["id"] = HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
            expected["prefs"] = [HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB]
            expected["nodes"] = list(EXPECTED_SUBTERRANEAN_GATE_NODES)
            require(
                portal_row == expected,
                f"raw_translation subterranean portal must clone portal_5 except SID/prefab/scorched nodes: {portal_row}",
                errors,
            )
            require(
                portal_row.get("nodes") == EXPECTED_SUBTERRANEAN_GATE_NODES,
                f"raw_translation subterranean portal must use scorched-earth nodes {EXPECTED_SUBTERRANEAN_GATE_NODES}: "
                f"{portal_row.get('nodes')}",
                errors,
            )
        require(
            logic_rows.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
            == {"id": HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, "goodsValue": 0},
            f"raw_translation subterranean portal logic mismatch: {logic_rows.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)}",
            errors,
        )
        # Land-on + stock towns: south-center GATE + CornerLeft at LeftBottom (1,2).
        # CreateCity often spawns from stock homm3_*_city (fractionConfig.city); donor
        # SW GATE (index 6) must not survive in the overlay or live interact is corner.
        # InteractionLayout.Bottom (2) shifts interact one cell south of the building.
        # CornerLeft+index-7 alone does NOT move the HoMM3 billboard entrance — that is
        # Homm3CustomTownMapBillboard (SW root +1 tile X). Do not re-tune layout enums for visuals.
        expected_landon_city_nodes = [1, 1, 1, 1, 1, 1, 1, 2, 1]
        expected_landon_city_gc = {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 1,
            "buildingLeftBottomZ": 2,
            "buildingInteractionLayout": 1,  # CornerLeft on south-center, not Bottom
        }
        stock_and_landon_city_sids = [
            sid
            for sid, row in object_rows.items()
            if isinstance(sid, str)
            and isinstance(row, dict)
            and re.fullmatch(r"homm3_(?:landon_)?[a-z0-9]+_city", sid)
        ]
        require(
            "homm3_landon_castle_city" in stock_and_landon_city_sids
            and "homm3_landon_dungeon_city" in stock_and_landon_city_sids,
            "overlay missing landon city ObjectConfigs",
            errors,
        )
        require(
            "homm3_castle_city" in stock_and_landon_city_sids
            and "homm3_dungeon_city" in stock_and_landon_city_sids,
            "overlay missing stock city ObjectConfigs for CreateCity bottom-center GATE",
            errors,
        )
        for sid in stock_and_landon_city_sids:
            city_row = object_rows.get(sid)
            require(isinstance(city_row, dict), f"overlay missing {sid}", errors)
            if not isinstance(city_row, dict):
                continue
            require(
                city_row.get("nodes") == expected_landon_city_nodes,
                f"{sid} nodes must be south-center GATE {expected_landon_city_nodes}; got {city_row.get('nodes')}",
                errors,
            )
            require(city_row.get("canBeMirrored") is False, f"{sid} must disable mirroring", errors)
            gc = city_row.get("generatorConfig") if isinstance(city_row.get("generatorConfig"), dict) else {}
            require(
                gc == expected_landon_city_gc,
                f"{sid} generatorConfig must be CornerLeft south-center {expected_landon_city_gc}; got {gc}",
                errors,
            )
    pathability_member = overlay / "DB" / "map" / "objects" / "homm3_pathability_alignment.json"
    require(pathability_member.is_file(), f"missing pathability blocker overlay: {pathability_member}", errors)
    if pathability_member.is_file():
        doc = read_json(pathability_member)
        rows = doc.get("array") if isinstance(doc, dict) else None
        require(isinstance(rows, list) and rows, "pathability overlay must contain blocker row", errors)
        sids = [row.get("id") for row in rows if isinstance(row, dict)]
        require("homm3_pathing_blocker" in sids, "pathability overlay missing homm3_pathing_blocker", errors)
        extra = [sid for sid in sids if sid != "homm3_pathing_blocker"]
        require(extra == [], f"raw_translation forbids pathability visual-clone overlay rows: {extra}", errors)
        for row in rows:
            if not isinstance(row, dict) or row.get("id") != "homm3_pathing_blocker":
                continue
            prefs = row.get("prefs")
            require(
                isinstance(prefs, list) and len(prefs) == 1,
                "homm3_pathing_blocker prefs must be exactly one entry",
                errors,
            )
            require(
                prefs == ["environment/dirt_stones_1"],
                f"homm3_pathing_blocker prefs must be [environment/dirt_stones_1]; found {prefs!r}",
                errors,
            )
            require("fx/fx_map_smoke" not in (prefs or []), "homm3_pathing_blocker must not use fx/fx_map_smoke", errors)

    # Envelope padding: elevated cliffs (surface land-match / underground Void). Occupancy blockers retired.
    padding_pin = manifest.get("envelopePaddingVoid") or {}
    require(padding_pin.get("status") == "applied", "envelopePaddingVoid must be applied", errors)
    require(
        padding_pin.get("policy") == "envelope_padding_elevated_cliffs_surface_land_match_underground_void",
        "envelopePaddingVoid policy pin missing",
        errors,
    )
    require(padding_pin.get("level") == 1, "envelopePaddingVoid.level must be 1 (elevated cliff)", errors)
    require(padding_pin.get("pathingMechanism") == "elevated_no_ramp_cliff", "envelope padding pathingMechanism pin", errors)
    require(padding_pin.get("cellCount") == 2432, "envelopePaddingVoid.cellCount must be 2432", errors)
    blockers_pin = padding_pin.get("blockers") or {}
    require(
        blockers_pin.get("status") == "retired_cliff_pathing_no_occupancy",
        "envelopePaddingVoid.blockers must be retired_cliff_pathing_no_occupancy",
        errors,
    )
    require(blockers_pin.get("cellCount") == 0, "envelope padding blocker cellCount must be 0", errors)
    padding_overlay = overlay / "DB" / "map" / "objects" / "homm3_envelope_padding_blocker.json"
    require(
        not padding_overlay.is_file(),
        f"stale padding blocker ObjectConfig overlay must be absent: {padding_overlay}",
        errors,
    )

    # Town ownership/garrison + envelope cliff recompute against generated map artifact.
    map_path = root / "maps" / f"{MAP_SID}.map"
    if map_path.is_file():
        try:
            sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
            import port_homecoming_poc as poc
            import campaign_ocean

            container = poc.read_olden_map_container(map_path)
            meta = container.chunks[0]
            map_data = container.chunks[1]
            for ocean_error in campaign_ocean.map_ocean_errors(map_data, label=MAP_SID):
                errors.append(ocean_error)
            require(
                campaign_ocean.ocean_cell_count(map_data) > 0,
                f"{MAP_SID}: Homecoming must emit native ocean cells (Sand tile 2 + waterMap 2)",
                errors,
            )
            tiles_map = map_data.get("tilesMap") or []
            levels_map = map_data.get("levelsMap") or []
            climbs_map = map_data.get("climbsMap") or []
            water_map = map_data.get("waterMap") or []
            if isinstance(tiles_map, list) and len(tiles_map) == 12800 and isinstance(levels_map, list):
                source_nodes: set[int] = set()
                for offset_x in (4, 84):
                    for sy in range(72):
                        for sx in range(72):
                            olden_y = (71 - sy) + 4
                            source_nodes.add(olden_y * 160 + (sx + offset_x))
                padding_ok = 0
                padding_bad = 0
                for node in range(12800):
                    if node in source_nodes:
                        continue
                    level = int(levels_map[node])
                    climb = int(climbs_map[node]) if climbs_map else 0
                    water = int(water_map[node]) if water_map else 0
                    if level == 1 and climb == 0 and water == 0:
                        padding_ok += 1
                    else:
                        padding_bad += 1
                require(
                    padding_ok == 2432 and padding_bad == 0,
                    f"raw envelope padding cliff recompute failed ok={padding_ok} bad={padding_bad}",
                    errors,
                )
            padding_blocker_count = 0
            for group in map_data.get("objects") or []:
                if group.get("sid") == "homm3_envelope_padding_blocker":
                    padding_blocker_count += len(group.get("ids") or [])
            require(
                padding_blocker_count == 0,
                f"raw padding blocker instance count must be 0; found {padding_blocker_count}",
                errors,
            )
            # Fail-closed: hero-spawner GATE/visit must not sit on envelope padding cliffs
            # (Bashing Skulls / Griffin Cliff regression class).
            if isinstance(levels_map, list) and len(levels_map) == 12800:
                hero_source_nodes: set[int] = set()
                for offset_x in (4, 84):
                    for sy in range(72):
                        for sx in range(72):
                            olden_y = (71 - sy) + 4
                            hero_source_nodes.add(olden_y * 160 + (sx + offset_x))
                padding_nodes = {node for node in range(12800) if node not in hero_source_nodes}
                cliff_heroes: list[dict] = []
                for group in map_data.get("objects") or []:
                    if group.get("sid") != "hero-spawner":
                        continue
                    for oid, node in zip(group.get("ids") or [], group.get("nodes") or []):
                        if not isinstance(oid, int) or not isinstance(node, int):
                            continue
                        level = int(levels_map[node]) if node < len(levels_map) else -999
                        climb = (
                            int(climbs_map[node])
                            if isinstance(climbs_map, list) and node < len(climbs_map)
                            else 0
                        )
                        on_pad = node in padding_nodes
                        elevated = level == 1 and climb == 0
                        if on_pad or elevated:
                            cliff_heroes.append(
                                {
                                    "objectId": oid,
                                    "node": node,
                                    "xy": [node % 160, node // 160],
                                    "level": level,
                                    "onPadding": on_pad,
                                    "elevatedUnramped": elevated,
                                }
                            )
                require(
                    not cliff_heroes,
                    "hero-spawner GATE/visit on envelope padding or elevated unramped cliff: "
                    f"{cliff_heroes[:5]}",
                    errors,
                )
            import scenario_menu_shell as menu_shell

            menu_shell.validate_menu_shell_fields(
                meta,
                map_data,
                MAP_SID,
                errors,
                context="raw_translation generated map",
            )
            props = map_data.get("objectsProperties") or {}
            prop_spawns = props.get("propSpawns") or []
            prop_cities = props.get("propCities") or []
            prop_owners = props.get("propOwners") or []
            prop_squads = props.get("propSquads") or []
            prop_random_squads = props.get("propRandomSquads") or []
            prop_growth = props.get("propGrowthUnits") or []
            prop_heroes = props.get("propHeroes") or []

            spawns_meta = meta.get("spawns") or {}
            require(
                isinstance(spawns_meta.get("playersCount"), int) and spawns_meta["playersCount"] == 3,
                f"raw meta.spawns.playersCount must be 3 (Player + Castle AI + Dungeon AI); "
                f"got {spawns_meta.get('playersCount')}",
                errors,
            )
            require(
                isinstance(prop_spawns, list) and len(prop_spawns) == spawns_meta["playersCount"],
                f"propSpawns length must equal playersCount "
                f"({spawns_meta.get('playersCount')}); got {len(prop_spawns) if isinstance(prop_spawns, list) else None}",
                errors,
            )
            meta_by_owner = {
                row.get("owner"): row
                for row in (spawns_meta.get("spawns") or [])
                if isinstance(row, dict) and isinstance(row.get("owner"), int)
            }
            require(1 in meta_by_owner, "raw meta.spawns missing human owner 1", errors)
            require(2 in meta_by_owner, "raw meta.spawns missing Castle AI owner 2", errors)
            require(3 in meta_by_owner, "raw meta.spawns missing Terraneus/Xyron AI owner 3", errors)
            if 2 in meta_by_owner:
                require(meta_by_owner[2].get("spawnType") == 1, "owner 2 spawnType must be AI", errors)
                require(
                    meta_by_owner[2].get("factionSid") == "homm3_castle",
                    f"owner 2 factionSid must be homm3_castle (surface AI towns); "
                    f"got {meta_by_owner[2].get('factionSid')!r}",
                    errors,
                )
                require(
                    meta_by_owner[2].get("isHeroDefined") is False,
                    "owner 2 must not claim a meta hero (Xyron lives on owner 3 with Terraneus)",
                    errors,
                )
            if 3 in meta_by_owner:
                require(meta_by_owner[3].get("spawnType") == 1, "owner 3 spawnType must be AI", errors)
                require(
                    meta_by_owner[3].get("factionSid") == "homm3_dungeon",
                    f"owner 3 factionSid must be homm3_dungeon (Terraneus city; "
                    f"Inferno Bot paints Terraneus Inferno); "
                    f"got {meta_by_owner[3].get('factionSid')!r}",
                    errors,
                )
                require(
                    meta_by_owner[3].get("isHeroDefined") is True
                    and meta_by_owner[3].get("heroSid") == "homm3_inferno_hero_10",
                    f"owner 3 must bind Xyron (homm3_inferno_hero_10); got {meta_by_owner[3]}",
                    errors,
                )

            city_ids = {
                int(row["id"])
                for row in prop_cities
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            city_spawn_by_id = {
                int(row["id"]): row
                for row in prop_spawns
                if isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and row.get("spawnPointType") == 0
            }
            owner_by_id = {
                int(row["id"]): row
                for row in prop_owners
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            # Human primary must be Caryatid City propSpawn (spawnHero path). Hero-only
            # primary left Caryatid on propOwners.owner=1, which campaign reads as
            # sides.array index 1 (Castle Bot) — town-entry NRE / wrong-side ownership.
            require(1 in meta_by_owner, "raw meta.spawns missing human owner 1", errors)
            if 1 in meta_by_owner:
                require(
                    meta_by_owner[1].get("isCityDefined") is True,
                    "human meta.isCityDefined must be True (Caryatid City start)",
                    errors,
                )
                require(
                    meta_by_owner[1].get("spawnPointType") == 0,
                    "human meta.spawnPointType must be City (0)",
                    errors,
                )
            require(16 in city_spawn_by_id, "Caryatid (16) missing City propSpawns (human primary)", errors)
            if 16 in city_spawn_by_id:
                require(city_spawn_by_id[16].get("owner") == 1, "Caryatid city spawn owner must be 1", errors)
                require(city_spawn_by_id[16].get("spawnType") == 0, "Caryatid city spawnType must be HUMAN (0)", errors)
            require(16 not in owner_by_id, "Caryatid must not remain on propOwners after City primary bind", errors)
            # Owner 3 primary is Xyron hero; Terraneus ownership is propOwners.
            require(
                1454 not in city_spawn_by_id,
                "Terraneus must not be a City propSpawn (Xyron hero primary)",
                errors,
            )
            require(1454 in owner_by_id, "Terraneus (1454) missing propOwners", errors)
            if 1454 in owner_by_id:
                require(
                    owner_by_id[1454].get("owner") == 3,
                    "Terraneus propOwners.owner must be 3 (compact Dungeon AI)",
                    errors,
                )
            # Owner 2 has no hero: lowest city id (4) is the City propSpawn; Trailia uses propOwners.
            require(4 in city_spawn_by_id, "Plinth (4) missing City propSpawns (owner 2 primary)", errors)
            if 4 in city_spawn_by_id:
                require(city_spawn_by_id[4].get("owner") == 2, "Plinth city spawn owner must be 2", errors)
                require(city_spawn_by_id[4].get("spawnType") == 1, "Plinth city spawnType must be 1", errors)
            require(629 not in city_spawn_by_id, "Trailia must not be a City propSpawn (owner 2 non-primary)", errors)
            require(629 in owner_by_id, "Trailia (629) missing propOwners", errors)
            if 629 in owner_by_id:
                require(owner_by_id[629].get("owner") == 2, "Trailia propOwners.owner must be 2", errors)

            # Map-space GATE must be south-center of the 3x3 (delta +1 X, +0 Y from SW anchor).
            # Native Olden cities keep SW-corner GATE; landon clones must not regress to index 6.
            sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc" / "approach_cell"))
            import surface_emit as se
            import native_footprint_model as native_fp

            overlay_objects = root / "core_overlay" / "DB" / "map" / "objects" / "4_interactables.json"
            landon_cfgs: dict[str, dict] = {}
            if overlay_objects.is_file():
                for row in (read_json(overlay_objects).get("array") or []):
                    if isinstance(row, dict) and row.get("id") in (
                        "homm3_landon_castle_city",
                        "homm3_landon_dungeon_city",
                    ):
                        landon_cfgs[str(row["id"])] = row
            width = int(map_data.get("sizeX_") or 0)
            height = int(map_data.get("sizeZ_") or 0)
            require(width > 0 and height > 0, f"raw map sizeX_/sizeZ_ invalid: {width}x{height}", errors)
            prev_w, prev_h = se.OLDEN_WIDTH, se.OLDEN_HEIGHT
            se.OLDEN_WIDTH, se.OLDEN_HEIGHT = width, height
            try:
                landon_gate_checked = 0
                for group in map_data.get("objects") or []:
                    if not isinstance(group, dict):
                        continue
                    sid = str(group.get("sid") or "")
                    cfg = landon_cfgs.get(sid)
                    if cfg is None:
                        continue
                    for oid, node, rot in zip(
                        group.get("ids") or [],
                        group.get("nodes") or [],
                        group.get("rotations") or [],
                    ):
                        if not isinstance(node, int):
                            continue
                        rot_i = int(rot or 0)
                        require(
                            rot_i == 0,
                            f"{sid} id {oid} must keep rotation 0 (canBeMirrored false); got {rot_i}",
                            errors,
                        )
                        # Unclipped native pivot projection (the game's node query); the
                        # emitter anchors land-on cities through the same projection.
                        model = native_fp.model_native_footprint(sid, cfg, node, rot_i, width=width, height=height)
                        gates = sorted(model.gate_cells)
                        require(
                            len(gates) == 1,
                            f"{sid} id {oid} must emit exactly one GATE; got {gates}",
                            errors,
                        )
                        size_x, size_z = int(cfg.get("sizeX") or 0), int(cfg.get("sizeZ") or 0)
                        gate_local = [
                            (i % size_x, i // size_x)
                            for i, value in enumerate(cfg.get("nodes") or [])
                            if value == 2
                        ] if size_x else []
                        require(
                            gate_local == [(size_x // 2, size_z - 1)],
                            f"{sid} GATE must be the south-center config cell; got {gate_local}",
                            errors,
                        )
                        if len(gates) == 1 and len(gate_local) == 1:
                            ax, ay = node % width, node // width
                            gx, gy = gates[0] % width, gates[0] // width
                            expected = (
                                gate_local[0][0] - model.transform.pivot_x,
                                model.transform.pivot_z - gate_local[0][1],
                            )
                            require(
                                (gx - ax, gy - ay) == expected,
                                f"{sid} id {oid} GATE must sit at the native pivot projection {expected} "
                                f"of the south-center cell; got {(gx - ax, gy - ay)} anchor=({ax},{ay}) gate=({gx},{gy})",
                                errors,
                            )
                            landon_gate_checked += 1
                require(
                    landon_gate_checked >= 5,
                    f"expected >=5 landon city GATE placements; checked {landon_gate_checked}",
                    errors,
                )
            finally:
                se.OLDEN_WIDTH, se.OLDEN_HEIGHT = prev_w, prev_h

            expected_city_name_sids = {
                4: "homecoming_city_name_plinth",
                16: "homecoming_city_name_caryatid",
                598: "homecoming_city_name_mirham",
                629: "homecoming_city_name_trailia",
                1454: "homecoming_city_name_terraneus",
            }
            city_name_by_id = {
                int(row["id"]): row.get("customCityName")
                for row in prop_cities
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            for object_id, expected_sid in expected_city_name_sids.items():
                require(
                    city_name_by_id.get(object_id) == expected_sid,
                    f"propCities {object_id} customCityName must be LocKit SID {expected_sid!r}; "
                    f"got {city_name_by_id.get(object_id)!r}",
                    errors,
                )
            # Fail closed: every emitted city name SID must exist in Lang overlay cities.json.
            overlay_cities = root / "core_overlay" / "Lang" / "english" / "texts" / "cities.json"
            require(overlay_cities.is_file(), f"missing Homecoming cities Lang overlay: {overlay_cities}", errors)
            if overlay_cities.is_file():
                cities_doc = json.loads(overlay_cities.read_text(encoding="utf-8-sig"))
                present = {
                    str(row.get("sid"))
                    for section in ("tokens", "array")
                    for row in (cities_doc.get(section) or [])
                    if isinstance(row, dict) and isinstance(row.get("sid"), str)
                }
                required_name_sids = set(expected_city_name_sids.values())
                missing_lang = sorted(required_name_sids - present)
                require(
                    missing_lang == [],
                    f"cities.json Lang overlay missing town name SIDs: {missing_lang}",
                    errors,
                )
            for enemy_id in (4, 629):
                if enemy_id == 4:
                    require(enemy_id in city_spawn_by_id, f"enemy town {enemy_id} missing City propSpawns", errors)
                    if enemy_id in city_spawn_by_id:
                        require(city_spawn_by_id[enemy_id].get("owner") == 2, f"town {enemy_id} owner must be 2", errors)
                else:
                    require(enemy_id in owner_by_id, f"enemy town {enemy_id} missing propOwners", errors)
                    if enemy_id in owner_by_id:
                        require(owner_by_id[enemy_id].get("owner") == 2, f"town {enemy_id} propOwners.owner must be 2", errors)

            growth_ids = {
                int(row["id"])
                for row in prop_growth
                if isinstance(row, dict) and isinstance(row.get("id"), int) and row.get("isConstantGrowth") is True
            }
            require(
                city_ids <= growth_ids,
                f"every propCities id must have propGrowthUnits; missing={sorted(city_ids - growth_ids)}",
                errors,
            )

            city_linked_unit_props = [
                int(row["id"])
                for row in prop_squads
                if isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and row["id"] in city_ids
                and row.get("unitProps")
            ]
            require(
                city_linked_unit_props == [],
                f"city propSquads.unitProps is a dead path; remove for cities {city_linked_unit_props}",
                errors,
            )

            garrisoned = []
            for row in prop_random_squads:
                if not isinstance(row, dict) or row.get("id") not in {4, 629}:
                    continue
                sids = row.get("sids") or []
                if (
                    isinstance(sids, list)
                    and sids
                    and all(isinstance(sid, str) and sid.startswith("homecoming_town_garrison_") for sid in sids)
                    and isinstance(row.get("requestedValue"), (int, float))
                    and float(row["requestedValue"]) > 0
                ):
                    garrisoned.append(int(row["id"]))
            require(
                sorted(garrisoned) == [4, 629],
                f"enemy towns 4/629 must bind H3 garrisons via propRandomSquads.sids; got {garrisoned}",
                errors,
            )
            # Human-owned Caryatid must keep empty propRandomSquads — fightable city
            # random-squad SIDs are the neutral-capture path and block starting ownership.
            caryatid_rs = next(
                (
                    row
                    for row in prop_random_squads
                    if isinstance(row, dict) and row.get("id") == 16
                ),
                None,
            )
            require(isinstance(caryatid_rs, dict), "Caryatid (16) missing propRandomSquads row", errors)
            if isinstance(caryatid_rs, dict):
                require(
                    (caryatid_rs.get("sids") or []) == [],
                    f"Caryatid (16) must have empty propRandomSquads.sids (human-owned); "
                    f"got {caryatid_rs.get('sids')!r}",
                    errors,
                )
                require(
                    float(caryatid_rs.get("requestedValue") or 0) == 0.0,
                    f"Caryatid (16) requestedValue must be 0; got {caryatid_rs.get('requestedValue')!r}",
                    errors,
                )

            # Starting buildings: H3M on-disk builtBuildingsMask → per-town construction preset.
            # Bit layout is H3M on-disk (Fort=bit3), NOT VCMI BuildingID ordinals (MG1=0, Fort=7).
            # Not army/rich (those invent walls/dwellings the H3 mask does not grant).
            # Difficulty does not multiply starting constructed buildings (resources/neutrals only).
            sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
            import h3m_town_construction as town_construction

            try:
                town_construction.assert_h3m_bit_layout_contract()
            except ValueError as exc:
                require(False, f"H3M town construction bit-layout contract failed: {exc}", errors)

            # Ground truth from Homecoming object_walk masks decoded with H3M on-disk bits:
            # Plinth/Mirham/Trailia 080000000000 → Fort
            # Caryatid 480840120000 → Fort+Tavern+MG1+Guardhouse+Archers+Griffins
            # Terraneus 480000000000 → Fort+Tavern
            expected_town_construction = {
                4: {"Build_Main": 1, "Build_Wall": 1},
                16: {
                    "Build_Main": 1,
                    "Build_Wall": 1,
                    "Build_Tavern": 1,
                    "Build_Magic_Guild": 1,
                    "Build_Tier_1": 1,
                    "Build_Tier_2": 1,
                    "Build_Tier_3": 1,
                },
                598: {"Build_Main": 1, "Build_Wall": 1},
                629: {"Build_Main": 1, "Build_Wall": 1},
                1454: {"Build_Main": 1, "Build_Wall": 1, "Build_Tavern": 1},
            }
            city_by_id = {
                int(row["id"]): row
                for row in prop_cities
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            for object_id, expected_constructed in expected_town_construction.items():
                city = city_by_id.get(object_id)
                require(isinstance(city, dict), f"missing propCities {object_id} for H3 construction pin", errors)
                if not isinstance(city, dict):
                    continue
                expected_sid = town_construction.construction_sid_for_object(object_id)
                require(
                    city.get("buildingsConstructionSid") == expected_sid,
                    f"town {object_id} must use H3 construction preset {expected_sid}; "
                    f"got {city.get('buildingsConstructionSid')!r} "
                    f"(army/rich presets invent dwellings H3 mask does not grant)",
                    errors,
                )
                require(
                    city.get("buildingsConstructionSid")
                    not in {"army_buildings_construction", "rich_buildings_construction"},
                    f"town {object_id} must not use army/rich construction presets",
                    errors,
                )

            preset_path = (
                root / "core_overlay" / "DB" / "buildings_constructions" / "custom_maps_buildings_presets.json"
            )
            require(preset_path.is_file(), f"missing H3 town construction overlay: {preset_path}", errors)
            if preset_path.is_file():
                preset_doc = read_json(preset_path)
                preset_by_id = {
                    row.get("id"): row
                    for row in (preset_doc.get("array") or [])
                    if isinstance(row, dict) and isinstance(row.get("id"), str)
                }
                for object_id, expected_constructed in expected_town_construction.items():
                    sid = town_construction.construction_sid_for_object(object_id)
                    row = preset_by_id.get(sid)
                    require(isinstance(row, dict), f"construction overlay missing preset {sid}", errors)
                    if not isinstance(row, dict):
                        continue
                    constructed = {
                        str(building.get("sid")): int(building.get("level") or 1)
                        for building in (row.get("buildings") or [])
                        if isinstance(building, dict)
                        and building.get("isConstructed") is True
                        and isinstance(building.get("sid"), str)
                    }
                    require(
                        constructed == expected_constructed,
                        f"preset {sid} constructed buildings must match H3M on-disk mask mapping "
                        f"{expected_constructed}; got {constructed}",
                        errors,
                    )
                    # Fail closed: dwelling tiers only when the H3M mask grants them.
                    expected_dwellings = sorted(
                        key for key in expected_constructed if key.startswith("Build_Tier_")
                    )
                    dwelling_tiers = sorted(
                        key for key in constructed if key.startswith("Build_Tier_")
                    )
                    require(
                        dwelling_tiers == expected_dwellings,
                        f"preset {sid} dwelling tiers must match H3M mask {expected_dwellings}; "
                        f"got {dwelling_tiers}",
                        errors,
                    )

            for row in prop_cities:
                if not isinstance(row, dict):
                    continue
                forbidden = [
                    key
                    for key in ("owner", "garrisonStacks", "builtBuildingsMask", "forbiddenBuildingsMask")
                    if key in row
                ]
                require(forbidden == [], f"propCities {row.get('id')} non-native fields {forbidden}", errors)

            hero_by_id = {
                int(row["id"]): row.get("heroSid")
                for row in prop_heroes
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            require(
                hero_by_id.get(1464) == "homm3_inferno_hero_10",
                f"Xyron propHeroes 1464 missing; got {hero_by_id.get(1464)}",
                errors,
            )
            # Owner 3 primary spawn is Xyron hero-spawner (c_M5: one propSpawn per player).
            xyron_spawn = next(
                (row for row in prop_spawns if isinstance(row, dict) and row.get("id") == 1464),
                None,
            )
            require(isinstance(xyron_spawn, dict), "Xyron propSpawns 1464 missing (owner 3 primary)", errors)
            if isinstance(xyron_spawn, dict):
                require(
                    xyron_spawn.get("owner") == 3,
                    f"Xyron propSpawns owner must be 3 (with Terraneus); got {xyron_spawn.get('owner')}",
                    errors,
                )
                require(xyron_spawn.get("spawnPointType") == 1, "Xyron propSpawns must be Hero spawnPointType", errors)
                require(xyron_spawn.get("isLocked") is False, "Xyron isLocked must stay False (not a patrol stand-in)", errors)
                require("patrolRadius" not in xyron_spawn, "must not invent patrolRadius on propSpawns", errors)

            # Editor contract: no orphan hero-spawners; extras are random-hero.
            id_sid: dict[int, str] = {}
            for group in map_data.get("objects") or []:
                if not isinstance(group, dict):
                    continue
                sid = group.get("sid")
                if not isinstance(sid, str):
                    continue
                for object_id in group.get("ids") or []:
                    if isinstance(object_id, int):
                        id_sid[object_id] = sid
            spawn_ids = {
                int(row["id"])
                for row in prop_spawns
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            orphan_spawners = sorted(
                oid for oid, sid in id_sid.items() if sid == "hero-spawner" and oid not in spawn_ids
            )
            require(
                orphan_spawners == [],
                f"orphan hero-spawner ids (must be random-hero or propSpawns): {orphan_spawners[:20]}",
                errors,
            )
            require(
                id_sid.get(1464) == "hero-spawner",
                f"Xyron object 1464 must remain hero-spawner; got {id_sid.get(1464)!r}",
                errors,
            )

            # DEF-family blocking scenery must survive emit (no silent snow→green / dead→pine).
            sid_counts: dict[str, int] = {}
            for group in map_data.get("objects") or []:
                sid = group.get("sid")
                if isinstance(sid, str):
                    sid_counts[sid] = sid_counts.get(sid, 0) + len(group.get("ids") or [])
            snow_mountains = sum(n for sid, n in sid_counts.items() if sid.startswith("mountain_snow"))
            dead_trees = sum(n for sid, n in sid_counts.items() if sid.startswith("tree_dead"))
            require(snow_mountains > 0, f"raw map must emit mountain_snow_* blocking scenery; got {snow_mountains}", errors)
            require(dead_trees > 0, f"raw map must emit tree_dead_* blocking scenery; got {dead_trees}", errors)
            require(
                sid_counts.get("wind_rose", 0) == 0,
                f"HoMM3 wind objects must emit as windmill, not wind_rose; got {sid_counts.get('wind_rose', 0)}",
                errors,
            )
            require(
                sid_counts.get("windmill", 0) >= 6,
                f"raw map must emit all Homecoming windmills; got {sid_counts.get('windmill', 0)}",
                errors,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"town ownership pin failed: {exc}")


def validate_install_destination_policy(repo_root: Path, errors: list[str]) -> None:
    """Fail closed if the installer again copies the same mapSid into maps/ and Story_maps/."""
    installer = repo_root / INSTALLER
    require(installer.is_file(), f"missing installer: {installer}", errors)
    if not installer.is_file():
        return
    text = installer.read_text(encoding="utf-8")
    require(
        INSTALL_DESTINATION_POLICY in text,
        f"installer must declare policy {INSTALL_DESTINATION_POLICY!r}",
        errors,
    )
    require(
        "STORY_MAPS_REL" in text and "Story_maps" in text,
        "installer must target maps/Story_maps/",
        errors,
    )
    require(
        "remove_maps_root_duplicate" in text or "assert_no_dual_install" in text,
        "installer must remove/forbid maps/-root duplicate of the same mapSid",
        errors,
    )
    # Fail closed on the old dual-destination loop (maps/ + Story_maps/).
    require(
        "for maps_dir in destinations" not in text,
        "installer must not loop destinations into both maps/ and Story_maps/",
        errors,
    )


def validate_installed_game_no_dual_map(
    game_root: Path | None,
    errors: list[str],
) -> None:
    if game_root is None:
        return
    maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
    story = maps_root / "Story_maps"
    root_map = maps_root / f"{MAP_SID}.map"
    root_json = maps_root / f"{MAP_SID}.json"
    story_map = story / f"{MAP_SID}.map"
    if not story_map.is_file() and not root_map.is_file():
        return
    require(
        not ((root_map.is_file() or root_json.is_file()) and story_map.is_file()),
        (
            f"installed dual mapSid forbidden ({INSTALL_DESTINATION_POLICY}): "
            f"{MAP_SID} exists under both maps/ and maps/Story_maps/ "
            "(QuestScript Dialogs play twice)"
        ),
        errors,
    )


def validate_runtime_script_single_day_briefing_triggers(
    repo_root: Path,
    errors: list[str],
) -> None:
    """Artifact pin: chunk 3 owns StartTurn Dialogs; sidecar must not re-register quests."""
    root = repo_root / ARTIFACT_ROOT
    map_path = root / "maps" / f"{MAP_SID}.map"
    script_path = root / "maps" / f"{MAP_SID}.json"
    require(map_path.is_file(), f"missing map for script pin: {map_path}", errors)
    require(script_path.is_file(), f"missing sidecar for script pin: {script_path}", errors)
    if not map_path.is_file() or not script_path.is_file():
        return
    try:
        sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
        import port_homecoming_poc as poc  # type: ignore
        import campaign_runtime_script as campaign_script  # type: ignore
    except Exception as exc:  # noqa: BLE001
        errors.append(f"script pin import failed: {exc}")
        return

    def start_turn_dialog_days(script: dict[str, Any]) -> list[int]:
        days: list[int] = []
        for quest in script.get("quests") or []:
            if quest.get("sid") != "homecoming_intro":
                continue
            for sub in quest.get("subQuests") or []:
                for trigger in sub.get("triggers") or []:
                    conds = trigger.get("conditions") or []
                    if not conds or conds[0].get("c") != "StartTurn":
                        continue
                    params = conds[0].get("p") or []
                    if len(params) < 2:
                        continue
                    actions = trigger.get("actions") or []
                    if any(action.get("a") == "Dialog" for action in actions):
                        days.append(int(params[1]))
        return days

    try:
        chunk3 = poc.read_olden_map_container(map_path).chunks[3]
        sidecar = read_json(script_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"script pin read failed: {exc}")
        return

    require(
        isinstance(sidecar, dict) and sidecar.get("quests") == [],
        (
            "sidecar .json must leave quests empty (chunk 3 owns QuestScript); "
            f"got {len((sidecar or {}).get('quests') or [])} quests — "
            "duplicate sidecar quests double-fire StartTurn Dialogs"
        ),
        errors,
    )
    require(
        sidecar == campaign_script.map_quest_sidecar_payload(chunk3 if isinstance(chunk3, dict) else {}),
        "sidecar payload must match map_quest_sidecar_payload(chunk3)",
        errors,
    )

    days = start_turn_dialog_days(chunk3 if isinstance(chunk3, dict) else {})
    require(
        days == sorted(days) and len(days) == len(set(days)),
        f"chunk3 must have exactly one StartTurn Dialog trigger per day; got {days}",
        errors,
    )
    require(
        days == [1, 2, 4, 6],
        f"chunk3 briefing days must be [1, 2, 4, 6]; got {days}",
        errors,
    )
    intro = next(
        (q for q in (chunk3.get("quests") or []) if isinstance(q, dict) and q.get("sid") == "homecoming_intro"),
        None,
    )
    require(intro is not None, "chunk3 missing homecoming_intro quest", errors)
    if intro is not None:
        require(
            intro.get("sharing") == "Clone",
            (
                "homecoming_intro quest sharing must be Clone (vanilla Story maps); "
                f"got {intro.get('sharing')!r}"
            ),
            errors,
        )
    for sid in ("homecoming_started", "homecoming_briefing_index"):
        counter = next(
            (c for c in (chunk3.get("counters") or []) if isinstance(c, dict) and c.get("sid") == sid),
            None,
        )
        require(counter is not None, f"chunk3 missing counter {sid}", errors)
        if counter is not None:
            require(
                counter.get("sharing") == "Clone",
                f"counter {sid} sharing must be Clone; got {counter.get('sharing')!r}",
                errors,
            )


def validate_mapdata_object_pack_hygiene(repo_root: Path, errors: list[str]) -> None:
    """Fail if objects[] pack arrays mismatch or props reference missing ids.

    Player.log correlation: Homecoming had 15 len(levels)>len(ids) groups while
    vanilla c_M1/c_M2/c_M10 had 0; session then NREd in fcr.Init, reloaded
    OnScenesLoaded, and QuestSystem.Init ran twice → doubled StartTurn Dialogs.
    """
    map_path = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "homecoming_poc"
        / "raw_translation_map"
        / "maps"
        / "h3_roe_castle_homecoming_raw_translation.map"
    )
    if not map_path.is_file():
        errors.append(f"missing artifact map for pack hygiene: {map_path}")
        return
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # noqa: WPS433

    chunk1 = poc.read_olden_map_container(map_path).chunks[1]
    if not isinstance(chunk1, dict):
        errors.append("artifact mapData chunk is not an object")
        return
    live_ids: set[int] = set()
    mismatches: list[str] = []
    for group in chunk1.get("objects") or []:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        for object_id in ids:
            if isinstance(object_id, int):
                live_ids.add(object_id)
        if not (
            isinstance(ids, list)
            and isinstance(nodes, list)
            and isinstance(rotations, list)
            and isinstance(levels, list)
            and len(ids) == len(nodes) == len(rotations) == len(levels)
        ):
            mismatches.append(
                f"{sid}: ids={len(ids)} nodes={len(nodes)} rotations={len(rotations)} levels={len(levels)}"
            )
    require(
        not mismatches,
        "objects[] pack array length mismatch (vanilla Story maps are always equal): "
        + "; ".join(mismatches[:8]),
        errors,
    )
    orphans: list[str] = []
    marker_orphans: list[str] = []
    props = chunk1.get("objectsProperties") or {}
    marker_live: set[int] = set()
    for marker in chunk1.get("markers") or []:
        if isinstance(marker, dict) and isinstance(marker.get("id"), int):
            marker_live.add(int(marker["id"]))
    if isinstance(props, dict):
        for pname, rows in props.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rid = row.get("id")
                if not isinstance(rid, int):
                    continue
                host_type = row.get("type")
                if host_type is None or host_type == 0:
                    if rid not in live_ids:
                        orphans.append(f"{pname}:{rid}")
                elif host_type == 1:
                    if rid not in marker_live:
                        marker_orphans.append(f"{pname}:{rid}")
    require(
        not orphans,
        "objectsProperties type=0 rows reference ids absent from objects[]: "
        + ", ".join(orphans[:12]),
        errors,
    )
    require(
        not marker_orphans,
        "objectsProperties type=1 rows reference ids absent from markers[]: "
        + ", ".join(marker_orphans[:12]),
        errors,
    )
    prop_marker_ids = {
        int(row["id"])
        for row in (props.get("propMarkers") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int) and row.get("type") == 1
    }
    require(
        prop_marker_ids == marker_live,
        "markers[] ids must equal propMarkers type=1 ids: "
        f"markers={sorted(marker_live)} propMarkers={sorted(prop_marker_ids)}",
        errors,
    )
    # After install expand, concrete resource_* must not keep Meta propResources.
    # Artifact may still have random-res; only pin concrete rows if present.
    id_to_sid = {}
    for group in chunk1.get("objects") or []:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        for object_id in group.get("ids") or []:
            if isinstance(object_id, int):
                id_to_sid[object_id] = sid
    bad_meta_props: list[str] = []
    for row in (props.get("propResources") or []) if isinstance(props, dict) else []:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        sid = id_to_sid.get(rid) if isinstance(rid, int) else None
        if isinstance(sid, str) and sid.startswith("resource_"):
            bad_meta_props.append(f"{sid}:{rid}")
    require(
        not bad_meta_props,
        "concrete resource_* must not keep Meta propResources (use propResParams): "
        + ", ".join(bad_meta_props[:12]),
        errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help="When set (or when default Golden Era exists), fail if mapSid is dual-installed.",
    )
    parser.add_argument(
        "--skip-installed-dual-check",
        action="store_true",
        help="Skip installed maps/ vs Story_maps/ dual-SID check.",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    compatibility_validator = repo_root / "tools" / "validate_homm3_footprint_compatibility_contract.py"
    if not compatibility_validator.is_file():
        errors.append(f"missing compatibility validator: {compatibility_validator}")
    else:
        compatibility_result = subprocess.run(
            [sys.executable, str(compatibility_validator)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if compatibility_result.returncode != 0:
            details = (compatibility_result.stdout or compatibility_result.stderr).strip()
            errors.append(f"H3 footprint compatibility contract failed: {details}")
    occupancy_validator = repo_root / "tools" / "validate_raw_translation_entrance_occupancy_contract.py"
    if not occupancy_validator.is_file():
        errors.append(f"missing entrance occupancy contract validator: {occupancy_validator}")
    else:
        occupancy_result = subprocess.run(
            [sys.executable, str(occupancy_validator)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if occupancy_result.returncode != 0:
            details = (occupancy_result.stdout or occupancy_result.stderr).strip()
            errors.append(f"entrance occupancy contract failed: {details}")
    validate_forbidden_imports(repo_root, errors)
    validate_emit_deferral_and_pickup_anchor_proof(repo_root, errors)
    validate_install_destination_policy(repo_root, errors)
    if not args.skip_generate:
        maybe_generate(repo_root)
    validate_artifact(repo_root, errors)
    validate_runtime_script_single_day_briefing_triggers(repo_root, errors)
    validate_mapdata_object_pack_hygiene(repo_root, errors)
    if not args.skip_installed_dual_check:
        game_root = args.game_root
        if game_root is None and DEFAULT_GAME_ROOT.is_dir():
            game_root = DEFAULT_GAME_ROOT
        if game_root is not None:
            validate_installed_game_no_dual_map(game_root.resolve(), errors)
    if errors:
        fail("; ".join(errors))
    print("Homecoming raw_translation map contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
