#!/usr/bin/env python3
"""Audit native building footprints without regenerating or installing maps.

The report compares the current emitter projection with the native ObjectConfig
query projection. It includes the HUB continuity lane and the AB/SoD batch so
that cases such as Bashing Skulls are not silently omitted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from native_footprint_model_v2 import model_native_footprint


DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
HUB_INSTALLER = ROOT / "tools" / "install_roe_castle_continuity_weave.py"
DEFAULT_BATCH_MANIFEST = ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json"
VIEW_SECTION_SIZE = 16


def load_core_configs(core: Path) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(core) as archive:
        for member in archive.namelist():
            normalized = member.replace("\\", "/")
            if not normalized.startswith("DB/map/objects/") or not normalized.endswith(".json"):
                continue
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            for row in payload.get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    configs[row["id"]] = row
    return configs


def normalize_mission_dir(repo_root: Path, artifact: Any) -> Path | None:
    if not isinstance(artifact, (str, Path)):
        return None
    mission_dir = (repo_root / Path(artifact)).resolve()
    if mission_dir.name == "maps":
        mission_dir = mission_dir.parent
    if mission_dir.name == "raw_translation_map":
        mission_dir = mission_dir.parent
    return mission_dir


def load_hub_configs(repo_root: Path) -> list[Path]:
    spec = importlib.util.spec_from_file_location("raw_translation_hub_installer_v2", HUB_INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load HUB_CONFIGS from {HUB_INSTALLER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hubs = getattr(module, "HUB_CONFIGS", None)
    if not isinstance(hubs, dict):
        raise RuntimeError("HUB_CONFIGS is missing or not a dictionary")
    mission_dirs: list[Path] = []
    for config in hubs.values():
        if not isinstance(config, dict):
            continue
        for install in config.get("mapInstalls") or []:
            if not isinstance(install, dict):
                continue
            mission_dir = normalize_mission_dir(repo_root, install.get("artifact"))
            if mission_dir is not None:
                mission_dirs.append(mission_dir)
    return mission_dirs


def load_batch_configs(repo_root: Path, manifest: Path) -> list[Path]:
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    rows = payload.get("missions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError(f"batch manifest missions is not a list: {manifest}")
    mission_dirs: list[Path] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mission_dir = normalize_mission_dir(repo_root, row.get("artifactRoot"))
        if mission_dir is not None:
            mission_dirs.append(mission_dir)
    return mission_dirs


def load_mission_dirs(repo_root: Path, batch_manifest: Path | None) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    sources = [load_hub_configs(repo_root)]
    if batch_manifest is not None:
        sources.append(load_batch_configs(repo_root, batch_manifest))
    for source in sources:
        for mission_dir in source:
            if mission_dir not in seen:
                seen.add(mission_dir)
                result.append(mission_dir)
    return result


def find_ground_truth(mission_dir: Path) -> Path | None:
    root = mission_dir / "raw_translation_map"
    preferred = root / "homecoming.raw_translation_placement_ground_truth.json"
    if preferred.is_file():
        return preferred
    matches = sorted(root.glob("*placement_ground_truth.json"))
    return matches[0] if matches else None


def find_layered_ir(mission_dir: Path) -> Path | None:
    matches = sorted((mission_dir / "layered_ir").glob("*layered_map_ir.json"))
    return matches[0] if matches else None


def mission_envelope(mission_dir: Path) -> tuple[int, int, dict[str, Any]] | None:
    """Return the emitted atlas dimensions, not the source surface dimensions."""
    ir_path = find_layered_ir(mission_dir)
    if ir_path is None:
        return None
    payload = json.loads(ir_path.read_text(encoding="utf-8-sig"))
    layers = [row for row in payload.get("layers") or [] if isinstance(row, dict)]
    surface = next((row for row in layers if row.get("sid") == "surface"), None)
    if not isinstance(surface, dict):
        return None
    source_width = surface.get("width")
    source_height = surface.get("height")
    if not isinstance(source_width, int) or not isinstance(source_height, int):
        return None
    layer_count = len(layers)
    if layer_count <= 0:
        return None
    layer_width = ((source_width + VIEW_SECTION_SIZE - 1) // VIEW_SECTION_SIZE) * VIEW_SECTION_SIZE
    layer_height = ((source_height + VIEW_SECTION_SIZE - 1) // VIEW_SECTION_SIZE) * VIEW_SECTION_SIZE
    width = layer_width * layer_count
    height = layer_height
    return width, height, {
        "sourceWidth": source_width,
        "sourceHeight": source_height,
        "layerCount": layer_count,
        "layerWidth": layer_width,
        "layerHeight": layer_height,
        "atlasWidth": width,
        "atlasHeight": height,
    }


def load_local_configs(base: dict[str, dict[str, Any]], mission_dir: Path) -> dict[str, dict[str, Any]]:
    configs = dict(base)
    overlay_root = mission_dir / "raw_translation_map" / "core_overlay" / "DB" / "map" / "objects"
    for overlay in sorted(overlay_root.glob("*.json")):
        payload = json.loads(overlay.read_text(encoding="utf-8-sig"))
        for row in payload.get("array") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                configs[row["id"]] = row
    return configs


def is_building_like(config: dict[str, Any]) -> bool:
    return (
        isinstance(config.get("generatorConfig"), dict)
        and (config.get("tag") == "Interact" or config.get("isInteractable") is True)
    )


def placement_source_key(placement: dict[str, Any]) -> Any:
    return placement.get("sourceKey") or (placement.get("h3") or {}).get("sourceKey")


def example_row(mission: str, placement: dict[str, Any], model: Any) -> dict[str, Any]:
    return {
        "mission": mission,
        "sourceKey": placement_source_key(placement),
        "objectId": (placement.get("olden") or {}).get("objectId"),
        "sid": model.sid,
        "anchorNode": model.anchor_node,
        "anchor": [model.anchor_node % model.width, model.anchor_node // model.width],
        "rotation": model.rotation,
        "nativeOrientation": model.native_orientation,
        "nativeOccupiedCells": sorted(model.occupied_cells),
        "legacyOccupiedCells": sorted(model.legacy_occupied_cells),
        "nativeOnlyOccupiedCells": sorted(model.native_only_occupied_cells),
        "legacyOnlyOccupiedCells": sorted(model.legacy_only_occupied_cells),
        "generatorOnlyCells": sorted(model.generator_only_cells),
        "runtimeModelStatus": model.runtime_model_status,
        "unresolved": list(model.unresolved),
    }


def audit(
    repo_root: Path,
    core: Path,
    *,
    batch_manifest: Path | None,
    example_limit: int,
) -> dict[str, Any]:
    base_configs = load_core_configs(core)
    mission_dirs = load_mission_dirs(repo_root, batch_manifest)
    stats: Counter[str] = Counter()
    sid_counts: Counter[str] = Counter()
    native_changed_sids: Counter[str] = Counter()
    generator_only_sids: Counter[str] = Counter()
    transform_sids: Counter[str] = Counter()
    unresolved_reasons: Counter[str] = Counter()
    orientation_counts: Counter[str] = Counter()
    envelope_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    stables_examples: list[dict[str, Any]] = []
    bashing_examples: list[dict[str, Any]] = []
    missing_gt: list[str] = []
    missing_envelope: list[str] = []

    for mission_dir in mission_dirs:
        gt_path = find_ground_truth(mission_dir)
        if gt_path is None:
            missing_gt.append(str(mission_dir))
            continue
        envelope = mission_envelope(mission_dir)
        if envelope is None:
            missing_envelope.append(str(mission_dir))
            continue
        width, height, envelope_meta = envelope
        envelope_counts[f"{width}x{height}"] += 1
        payload = json.loads(gt_path.read_text(encoding="utf-8-sig"))
        local_configs = load_local_configs(base_configs, mission_dir)
        mission_name = mission_dir.name
        stats["missionsWithGroundTruth"] += 1
        if mission_name == "bashing_skulls":
            stats["bashingSkullsMissionsWithGroundTruth"] += 1
        for placement in payload.get("placements") or []:
            if not isinstance(placement, dict) or placement.get("emitStatus") != "emitted":
                continue
            olden = placement.get("olden")
            if not isinstance(olden, dict):
                continue
            sid = olden.get("sid")
            node = olden.get("node")
            rotation = olden.get("rotation", 0)
            object_id = olden.get("objectId")
            config = local_configs.get(str(sid)) if isinstance(sid, str) else None
            if not isinstance(config, dict) or not is_building_like(config):
                continue
            if not isinstance(node, int) or not isinstance(rotation, int) or not isinstance(object_id, int):
                stats["invalidBuildingPlacementRows"] += 1
                continue
            model = model_native_footprint(str(sid), config, node, rotation, width=width, height=height)
            stats["buildingInstances"] += 1
            sid_counts[str(sid)] += 1
            orientation_counts[model.native_orientation] += 1
            stats["nativeOccupiedCells"] += len(model.occupied_cells)
            stats["legacyOccupiedCells"] += len(model.legacy_occupied_cells)
            if model.native_only_occupied_cells or model.legacy_only_occupied_cells:
                stats["instancesWithNativeLegacyProjectionDifference"] += 1
                stats["nativeOnlyOccupiedCells"] += len(model.native_only_occupied_cells)
                stats["legacyOnlyOccupiedCells"] += len(model.legacy_only_occupied_cells)
                native_changed_sids[str(sid)] += 1
                if len(examples) < example_limit:
                    examples.append(example_row(mission_name, placement, model))
            if model.generator_only_cells:
                stats["instancesWithGeneratorOnlyCells"] += 1
                stats["generatorOnlyCells"] += len(model.generator_only_cells)
                generator_only_sids[str(sid)] += 1
            if model.generator_local_cells:
                stats["instancesWithGeneratorBody"] += 1
            if model.transform.has_nonzero_transform:
                stats["instancesWithNonzeroTransform"] += 1
                transform_sids[str(sid)] += 1
            for reason in model.unresolved:
                unresolved_reasons[reason] += 1
            if str(sid) == "stables" and len(stables_examples) < example_limit:
                stables_examples.append(example_row(mission_name, placement, model))
            if mission_name == "bashing_skulls" and len(bashing_examples) < example_limit:
                bashing_examples.append(example_row(mission_name, placement, model))

    return {
        "schema": "olden.raw_translation.native_footprint_model_audit.v3",
        "status": "static_candidate_audit_only",
        "proofBoundary": (
            "native ObjectConfig nodes use the recovered bvf query projection; "
            "generator rectangle, presentation offsets, and final runtime pathfinder behavior remain separate"
        ),
        "core": str(core),
        "batchManifest": str(batch_manifest) if batch_manifest is not None else None,
        "missionCount": len(mission_dirs),
        "missingGroundTruth": missing_gt,
        "missingEnvelope": missing_envelope,
        "envelopeCounts": dict(envelope_counts),
        "stats": dict(stats),
        "orientationCounts": dict(orientation_counts),
        "unresolvedReasons": unresolved_reasons.most_common(),
        "topBuildingSids": sid_counts.most_common(30),
        "topNativeLegacyProjectionDifferenceSids": native_changed_sids.most_common(30),
        "topGeneratorOnlySids": generator_only_sids.most_common(30),
        "topTransformSids": transform_sids.most_common(30),
        "projectionDifferenceExamples": examples,
        "stablesExamples": stables_examples,
        "bashingSkullsExamples": bashing_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--batch-manifest", type=Path, default=DEFAULT_BATCH_MANIFEST)
    parser.add_argument("--without-batch", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--example-limit", type=int, default=25)
    args = parser.parse_args()
    batch_manifest = None if args.without_batch else args.batch_manifest.resolve()
    report = audit(
        args.repo_root.resolve(),
        args.core.resolve(),
        batch_manifest=batch_manifest,
        example_limit=max(0, args.example_limit),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "stats": report["stats"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
