#!/usr/bin/env python3
"""Fail if substituted scenery emits OE OCC larger than the H3 block mask,
or if exact-footprint scenery clones leave mesh-overhang holes in the donor grid.

Contract for campaign raw_translation OE-larger scenery: rocks/pools/plates/hills
must not keep oversized Core donors after exact_homm3_footprint catalog/clone.
Same-size clones must not mix open and occupied nodes (sparsened dirt_rock /
pool meshes overhang H3-open cells). Covers all HUB_CONFIGS raw_translation
missions (RoE castle/remaining + AB/SoD) by default. Functional keep-donor
buildings (e.g. college_of_wonder / Library of Enlightenment) may be listed as
intentional exceptions.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_BATCH = ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json"
HUB_INSTALLER = ROOT / "tools" / "install_roe_castle_continuity_weave.py"

# Functional keep-donor buildings that remain OE-larger by design (GATE/OCC rewrite
# forbidden). Scenery class must not appear here.
INTENTIONAL_OE_LARGER_SIDS = frozenset({
    "college_of_wonder",
})


def hub_configs_mission_dirs(repo_root: Path) -> list[Path]:
    """Artifact roots for every raw_translation mission wired in HUB_CONFIGS."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("roe_castle_hub_installer", HUB_INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load HUB_CONFIGS from {HUB_INSTALLER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hubs = getattr(mod, "HUB_CONFIGS", None)
    if not isinstance(hubs, dict):
        raise RuntimeError(f"HUB_CONFIGS missing in {HUB_INSTALLER}")

    dirs: list[Path] = []
    seen: set[Path] = set()
    for cfg in hubs.values():
        if not isinstance(cfg, dict):
            continue
        for install in cfg.get("mapInstalls") or []:
            if not isinstance(install, dict):
                continue
            artifact = install.get("artifact")
            if not isinstance(artifact, Path):
                continue
            art = (repo_root / artifact).resolve()
            # mapInstalls point at .../raw_translation_map/maps
            mission_dir = art.parent if art.name == "maps" else art
            if mission_dir.name == "raw_translation_map":
                mission_dir = mission_dir.parent
            if mission_dir in seen:
                continue
            seen.add(mission_dir)
            dirs.append(mission_dir)
    return dirs

H3M_MASK_WIDTH = 8
H3M_MASK_HEIGHT = 6
H3M_MASK_ANCHOR_X = 7
H3M_MASK_ANCHOR_Y = 5


def source_block_offsets(mask: Any) -> set[tuple[int, int]]:
    offsets: set[tuple[int, int]] = set()
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        return offsets
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int):
            continue
        for col_index in range(H3M_MASK_WIDTH):
            if (raw >> col_index) & 1 == 0:
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def load_core_configs(core: Path, overlay: Path | None = None) -> dict[str, dict[str, Any]]:
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
    if overlay is not None and overlay.is_file():
        payload = json.loads(overlay.read_text(encoding="utf-8"))
        for row in payload.get("array") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                configs[row["id"]] = row
    return configs


def occ_count(cfg: dict[str, Any] | None) -> int | None:
    if not isinstance(cfg, dict):
        return None
    nodes = cfg.get("nodes")
    if not isinstance(nodes, list):
        return None
    return sum(1 for value in nodes if int(value) == 1)


def is_scenery_placement(placement: dict[str, Any], suppressible: set[str]) -> bool:
    sid = (placement.get("olden") or {}).get("sid") or (placement.get("mapping") or {}).get("replacementSid")
    h3 = placement.get("h3") or {}
    category = str(h3.get("category") or "")
    rule = str((placement.get("mapping") or {}).get("ruleName") or "")
    base_sid = str(sid or "")
    if base_sid.startswith("homm3_xfp_"):
        # Same-size scenery clones — still scenery for this contract.
        return True
    if base_sid in suppressible:
        return True
    if category == "payloadless_object_unclassified_for_current_scope" and any(
        token in rule for token in ("scenery", "biome", "rock", "mountain", "tree", "pool", "terrain", "hill", "dune")
    ):
        return True
    if isinstance(sid, str) and any(
        sid.startswith(prefix)
        for prefix in (
            "dirt_",
            "mountain_",
            "tree_",
            "pool_",
            "pinetree",
            "grass_",
            "snow_",
            "desert_",
            "lava_",
            "log_",
            "mushroom",
            "water_reed",
            "dead_meadow",
            "crystal_trail",
            "rocks_",
            "dead_sculls",
            "homm3_xfp_",
        )
    ):
        return True
    return False


def audit_mission(
    mission_dir: Path,
    configs: dict[str, dict[str, Any]],
    suppressible: set[str],
) -> list[dict[str, Any]]:
    gt_path = mission_dir / "raw_translation_map" / "homecoming.raw_translation_placement_ground_truth.json"
    if not gt_path.is_file():
        # Some missions nest GT under a different name; accept any *placement_ground_truth.json.
        matches = list((mission_dir / "raw_translation_map").glob("*placement_ground_truth.json"))
        if not matches:
            return []
        gt_path = matches[0]
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    overlay = (
        mission_dir
        / "raw_translation_map"
        / "core_overlay"
        / "DB"
        / "map"
        / "objects"
        / "homecoming_exact_footprint_objects.json"
    )
    local_configs = dict(configs)
    functional_clone_sids: set[str] = set()
    if overlay.is_file():
        payload = json.loads(overlay.read_text(encoding="utf-8"))
        for row in payload.get("array") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                local_configs[row["id"]] = row
                meta = row.get("homm3ExactFootprint")
                if isinstance(meta, dict) and meta.get("kind") == "functional":
                    functional_clone_sids.add(row["id"])

    violations: list[dict[str, Any]] = []
    for placement in gt.get("placements") or []:
        if placement.get("emitStatus") != "emitted":
            continue
        candidate_sid = (placement.get("olden") or {}).get("sid") or (placement.get("mapping") or {}).get("replacementSid")
        if str(candidate_sid) in functional_clone_sids:
            continue
        if not is_scenery_placement(placement, suppressible):
            continue
        h3 = placement.get("h3") or {}
        h3_cells = len(source_block_offsets(h3.get("templateBlockMask")))
        olden = placement.get("olden") or {}
        sid = olden.get("sid") or (placement.get("mapping") or {}).get("replacementSid")
        oe_nodes = olden.get("occupiedNodes") or []
        oe_cells = len(oe_nodes) if isinstance(oe_nodes, list) else None
        cfg = local_configs.get(str(sid)) if sid else None
        cfg_cells = occ_count(cfg)
        oe_effective = oe_cells if oe_cells is not None else cfg_cells
        # Mesh-overhang: only exact-footprint same-size clones (homm3_xfp_*) may not
        # mix open + occupied nodes. Native donors (GATE rings, keep-donor buildings)
        # intentionally have open cells inside sizeX×sizeZ.
        if isinstance(sid, str) and sid.startswith("homm3_xfp_") and isinstance(cfg, dict):
            nodes = cfg.get("nodes")
            size_x, size_z = cfg.get("sizeX"), cfg.get("sizeZ")
            if (
                isinstance(nodes, list)
                and isinstance(size_x, int)
                and isinstance(size_z, int)
                and len(nodes) == size_x * size_z
            ):
                open_n = sum(1 for value in nodes if int(value) == 0)
                occ_n = sum(1 for value in nodes if int(value) == 1)
                if open_n > 0 and occ_n > 0:
                    violations.append(
                        {
                            "mission": mission_dir.name,
                            "sourceKey": placement.get("sourceKey"),
                            "sid": sid,
                            "ruleName": (placement.get("mapping") or {}).get("ruleName"),
                            "kind": "mesh_overhang_partial_nodes",
                            "h3Cells": h3_cells,
                            "oeCells": occ_n,
                            "openCellsInSizeGrid": open_n,
                            "size": [size_x, size_z],
                        }
                    )
        if oe_effective is None:
            continue
        if oe_effective <= h3_cells:
            continue
        if str(sid) in INTENTIONAL_OE_LARGER_SIDS:
            continue
        # Clones may still be keyed by donor visual; treat intentional only by exact SID.
        violations.append(
            {
                "mission": mission_dir.name,
                "sourceKey": placement.get("sourceKey"),
                "sid": sid,
                "ruleName": (placement.get("mapping") or {}).get("ruleName"),
                "kind": "oe_occ_larger_than_h3",
                "h3Cells": h3_cells,
                "oeCells": oe_effective,
                "delta": oe_effective - h3_cells,
            }
        )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Optional batch manifest subset. Default (no --manifest/--mission-dir): "
            "all raw_translation missions from HUB_CONFIGS."
        ),
    )
    parser.add_argument("--mission", action="append", dest="missions", default=None)
    parser.add_argument(
        "--mission-dir",
        type=Path,
        action="append",
        dest="mission_dirs",
        default=None,
        help="Direct artifact root(s) containing raw_translation_map/",
    )
    parser.add_argument(
        "--allow-missing-gt",
        action="store_true",
        help="Skip missions with no ground-truth file (default: fail closed).",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(POC))
    import functional_emit_reservation as fer  # noqa: E402
    from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402

    suppressible = set(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS)
    configs = load_core_configs(args.core.resolve())

    mission_dirs: list[Path] = []
    if args.mission_dirs:
        mission_dirs.extend(path.resolve() for path in args.mission_dirs)
    elif args.manifest is not None or args.missions:
        manifest_path = (args.manifest or DEFAULT_BATCH).resolve()
        batch = load_batch_manifest(manifest_path)
        selected = args.missions or [mission.mission_id for mission in batch.missions]
        for mission_id in selected:
            mission = mission_by_id(batch, mission_id)
            mission_dirs.append(mission.artifact_root.resolve())
    else:
        mission_dirs.extend(hub_configs_mission_dirs(ROOT))

    all_violations: list[dict[str, Any]] = []
    missing_gt: list[str] = []
    audited = 0
    for mission_dir in mission_dirs:
        gt_dir = mission_dir / "raw_translation_map"
        has_gt = gt_dir.is_dir() and (
            (gt_dir / "homecoming.raw_translation_placement_ground_truth.json").is_file()
            or any(gt_dir.glob("*placement_ground_truth.json"))
        )
        if not has_gt:
            missing_gt.append(mission_dir.name)
            continue
        audited += 1
        all_violations.extend(audit_mission(mission_dir, configs, suppressible))

    if missing_gt and not args.allow_missing_gt:
        print(
            f"FAIL scenery OE-larger contract: missing ground truth for {len(missing_gt)} missions: "
            + ", ".join(missing_gt[:12])
        )
        return 1

    if all_violations:
        by_sid: dict[str, int] = {}
        for row in all_violations:
            by_sid[str(row.get("sid"))] = by_sid.get(str(row.get("sid")), 0) + 1
        print(
            f"FAIL scenery OE-larger contract: {len(all_violations)} instances across "
            f"{audited} missions; intentional exceptions={sorted(INTENTIONAL_OE_LARGER_SIDS)}"
        )
        for sid, count in sorted(by_sid.items(), key=lambda item: (-item[1], item[0]))[:20]:
            print(f"  {sid}: {count}")
        for row in all_violations[:12]:
            print(
                f"  ex {row.get('mission')} {row.get('sourceKey')} "
                f"sid={row.get('sid')} H3={row.get('h3Cells')} OE={row.get('oeCells')} "
                f"rule={row.get('ruleName')}"
            )
        return 1

    print(
        f"OK scenery OE-larger contract: 0 violations across {audited} missions "
        f"(intentional keep-donor exceptions={sorted(INTENTIONAL_OE_LARGER_SIDS)}; "
        f"skipped_missing_gt={len(missing_gt)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
