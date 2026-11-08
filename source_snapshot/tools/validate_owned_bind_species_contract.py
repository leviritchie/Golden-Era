#!/usr/bin/env python3
"""Fail-closed contract: rider_mount owned bind cannot be swapped for Mixamo/Meshy smart-rig."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))

from owned_rerig.species import load_species_template, required_bone_names  # noqa: E402


class ContractError(RuntimeError):
    pass


REQUIRED_PATHS = (
    "tools/homm3_meshy_frame_pose/owned_rerig/diagnose.py",
    "tools/homm3_meshy_frame_pose/owned_rerig/bind.py",
    "tools/homm3_meshy_frame_pose/owned_rerig/pipeline.py",
    "tools/homm3_meshy_frame_pose/species_templates/rider_mount.json",
    "tools/homm3_meshy_frame_pose/diagnose_smartrig_quality.py",
    "tools/homm3_meshy_frame_pose/run_owned_species_bind.py",
    "tools/homm3_silhouette_pose_fit/bone_roles_cavalier_owned.json",
    "tools/homm3_silhouette_pose_fit/run_cavalier_gpu_cascade_animation_set.py",
    "tools/homm3_meshy_frame_pose/test_owned_rerig.py",
)

REQUIRED_BONES = (
    "HorseLeftShoulder",
    "HorseRightShoulder",
    "HorseLeftHip",
    "HorseRightHip",
    "Saddle",
    "RiderHips",
    "RiderHead",
    "LanceTip",
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ContractError(message)


def validate(repo: Path) -> None:
    for relative in REQUIRED_PATHS:
        require((repo / relative).is_file(), f"missing {relative}")
    template = load_species_template("rider_mount", templates_dir=repo / "tools" / "homm3_meshy_frame_pose" / "species_templates")
    names = set(required_bone_names(template))
    missing = [name for name in REQUIRED_BONES if name not in names]
    require(not missing, f"rider_mount template missing bones {missing}")
    walls = template["skinWalls"]
    require("HorseLeftShoulder" in walls["horse"], "horse wall must include HorseLeftShoulder")
    require("RiderHead" in walls["rider"], "rider wall must include RiderHead")
    require("LanceTip" in walls["lance"], "lance wall must include LanceTip")
    require("Saddle" in walls["saddle_band"], "saddle_band wall must include Saddle")
    generate = (repo / "tools" / "homm3_meshy_frame_pose" / "generate_meshy_t2_unit_master.py").read_text(encoding="utf-8")
    require("--skip-rig" in generate, "Meshy generator must expose --skip-rig")
    require("mesh + texture" in generate.lower() or "mesh+texture" in generate.lower().replace(" ", ""), "Meshy generator docs must say mesh+texture")
    require("default scalable armature authority" not in generate, "Meshy auto-rig must not be called delivery armature authority")
    cascade = (repo / "tools" / "homm3_silhouette_pose_fit" / "run_cavalier_gpu_cascade_animation_set.py").read_text(encoding="utf-8")
    require("owned_bind" in cascade, "Cavalier cascade runner must lock to owned_bind")
    require("mixamo" in cascade.lower(), "Cavalier cascade runner must refuse Mixamo leftovers")
    card = (repo / "docs" / "surfaces" / "custom_unit_skinned_mesh.md").read_text(encoding="utf-8")
    require("rider_mount" in card or "Cavalier" in card, "skinned-mesh card must mention Cavalier/rider_mount owned bind")
    master = repo / "artifacts" / "cavalier_pose_pipeline" / "owned_bind" / "h3_cavalier_master.glb"
    if master.is_file():
        sys.path.insert(0, str(repo / "tools" / "homm3_meshy_frame_pose"))
        from owned_rerig.glb_io import load_mesh

        mesh = load_mesh(master)
        node_names = set(mesh.node_names)
        missing_master = [name for name in REQUIRED_BONES if name not in node_names]
        require(not missing_master, f"owned master missing bones {missing_master}")
        require(not any("mixamo" in n.lower() for n in node_names), "owned master still has Mixamo names")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        validate(args.repo_root.resolve())
    except ContractError as exc:
        print(f"validate_owned_bind_species_contract FAILED: {exc}")
        return 1
    print("validate_owned_bind_species_contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
