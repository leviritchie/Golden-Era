#!/usr/bin/env python3
"""Hybrid pose method trials for Roc Move, Crusader AttackFront, Behemoth Move, Medusa Hit.

v52 compound (frugal, <=5 min/clip) — class policies, not clip-specific Euler tables:
  - ground: DINOv3-dense joint score; profile init + three-axis root search; 1 artic round
  - flyers: side/profile camera → auto scale (pxPerWorld + dy) → HT-gated tip + phase
    wing refine via flyer_hybrid_autolock (head/tail from roles or AABB; artic=0 bake)
    soft tip bob + per-phase distal refine (downstroke not frozen open)
  The four clips are acceptance gates for one reusable pipeline, not special cases.

Does not overwrite idle keep. Does not apply CURRENT_CASCADE_KEEP (refuses dinov3).
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
OUT_ROOT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad"
BUDGET_SEC = 300.0
# Mid chord: prefer lateral wing bones, not near-spine extras like Bone_013.
FLYER_SEARCH_BONES: tuple[str, ...] = (
    "Bone_017",
    "Bone_018",
    "Bone_019",
    "Bone_020",
    "Bone_021",
    "Bone_022",
)
FLYER_REFINE_BONES: tuple[str, ...] = FLYER_SEARCH_BONES + ("Bone_013",)
METHOD_ID = "hybrid_v64_soft_secondary"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_chain_space_surface_compare import (  # noqa: E402
    _prepare_choice_config,
    _sprite_dir,
    compose_clip_gif,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
)

CLIPS: dict[str, dict[str, Any]] = {
    "roc_move": {
        "unit_sid": "h3_roc",
        "def_groups": (0,),
        "mesh": ROOT / "artifacts/meshy_downloads" / "h3_roc_smartrigged.glb",
        "unit_class": "flyer",
        "title": "Roc Move (DEF 0)",
        # Base side/profile cam; autolock discovers scale + tip (not authored Eulers).
        "side_camera": (
            ROOT
            / "artifacts/pose_picker_runs/h3_roc/move/initialization"
            / "flyer_side_profile_camera_fit.json"
        ),
        # Optional anatomical pins when AABB discovery is ambiguous; still not tip Eulers.
        "head_bone": "Bone_014",
        "tail_bone": "Bone_012",
    },
    "crusader_attack_front": {
        "unit_sid": "h3_crusader",
        "def_groups": (12,),
        "mesh": ROOT / "artifacts/meshy_downloads" / "h3_crusader_smartrigged_rigidized.glb",
        "unit_class": "ground",
        "title": "Crusader AttackFront (DEF 12)",
    },
    "behemoth_move": {
        "unit_sid": "h3_behemoth",
        "def_groups": (0,),
        "mesh": ROOT / "artifacts/meshy_downloads" / "h3_behemoth_smartrigged.glb",
        "unit_class": "ground",
        "title": "Behemoth Move (DEF 0)",
    },
    "medusa_hitted": {
        "unit_sid": "h3_medusa",
        "def_groups": (3,),
        "mesh": ROOT / "artifacts/meshy_downloads" / "h3_medusa_smartrigged_rigidized.glb",
        "unit_class": "ground",
        "title": "Medusa Hit (DEF 3)",
    },
}


def _build_isolated_def_choice(widgets, *, unit_sid: str, def_groups: tuple[int, ...]):
    from materialize_rife_source_frames import (
        def_sequence_animation_name,
        def_sequence_choice_id,
        inventory_authentic_def_groups,
    )

    if not def_groups:
        raise ValueError("def_groups must be non-empty")
    need = int(def_groups[0])
    donors = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == unit_sid
        and choice.source_kind == "authentic_def"
        and need in (choice.present_groups or ())
        and choice.def_lab_frame_dir is not None
    ]
    if not donors:
        raise RuntimeError(f"{unit_sid}: no authentic DEF inventory contains group {need}")
    donor = donors[0]
    inventory = inventory_authentic_def_groups(Path(donor.def_lab_frame_dir))
    frames: list[Any] = []
    counts: list[int] = []
    for group in def_groups:
        if int(group) not in inventory or not inventory[int(group)]:
            raise RuntimeError(
                f"{unit_sid}: DEF group {group} missing from {donor.def_lab_frame_dir}"
            )
        group_frames = tuple(inventory[int(group)])
        frames.extend(group_frames)
        counts.append(len(group_frames))
    animation = def_sequence_animation_name(tuple(int(g) for g in def_groups))
    runtime_dir, camera_fit = widgets._runtime_paths(ROOT, unit_sid, animation)
    return replace(
        donor,
        animation_name=animation,
        choice_id=def_sequence_choice_id(unit_sid, tuple(int(g) for g in def_groups)),
        pilot_dir=runtime_dir,
        camera_fit=camera_fit,
        frame_indices=tuple(range(len(frames))),
        source_frames=tuple(frames),
        def_lab_groups=tuple(int(g) for g in def_groups),
        def_expected_counts=tuple(counts),
        sequence_kind="isolated_def",
    )


def _mask_aspect(mask) -> float:
    import numpy as np
    import torch

    arr = mask.detach().cpu().numpy() > 0.5 if torch.is_tensor(mask) else (mask > 0.5)
    ys, xs = np.where(arr)
    if len(xs) == 0:
        return 0.0
    return float(xs.max() - xs.min() + 1) / float(max(ys.max() - ys.min() + 1, 1))


def _lock_flyer_roll_by_aspect_iou(
    *,
    mesh: Path,
    camera_fit: Path,
    target_frame_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Lock flyer root with compound camera_forward roll + camera_right pitch.

    Roll alone tops out near aspect ~1.0 under the idle keep camera; a modest
    positive pitch with positive roll reaches landscape aspect matching Move.
    Negative pitch alone is the v7 dive trap — require an aspect landscape gate.
    """
    import torch
    from roc_gpu_cascade_experiment import (
        MOTION_ROOT_ROTATION_KEY,
        GpuCascadeConfig,
        GpuCascadeExperiment,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = GpuCascadeConfig(
        score_mode="geometry",
        depth_weight=0.0,
        silhouette_weight=1.0,
        chroma_weight=0.0,
        motion_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        root_search_enabled=False,
        resolution=(160, 140),
    )
    cfg.validate()
    experiment = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=camera_fit,
        target_frame_dir=target_frame_dir,
        frame_indices=(0,),
        config=cfg,
    )
    target_aspect = _mask_aspect(experiment.target_masks[0])
    if target_aspect <= 0.0:
        raise RuntimeError("flyer orient lock: empty target silhouette")

    def _score(roll: float, pitch: float) -> dict[str, Any]:
        seed = {
            0: {
                MOTION_ROOT_ROTATION_KEY: {
                    "camera_forward": float(roll),
                    "camera_right": float(pitch),
                    "camera_up": 0.0,
                }
            }
        }
        bone, root_t, root_r = experiment._initial_pose_tensors(seed)
        scored = experiment.evaluate(bone, root_t, root_r, frame_indices=(0,))
        iou = float(scored["silhouetteIoU"].detach().cpu().numpy().reshape(-1)[0])
        aspect = _mask_aspect(scored["predictedMasks"][0])
        aspect_term = math.exp(-abs(math.log(max(aspect, 1e-3) / target_aspect)))
        landscape_floor = min(1.2, 0.9 * target_aspect)
        landscape = (
            1.0
            if aspect >= landscape_floor
            else max(0.0, aspect / max(landscape_floor, 1e-3))
        )
        # IoU-primary. Aspect-heavy scoring (v7–v18) preferred landscape dives.
        # Soft landscape bonus only; flight pitch prior comes from the search grid.
        hybrid = 0.70 * iou + 0.20 * aspect_term + 0.10 * landscape
        return {
            "rollDeg": float(roll),
            "pitchDeg": float(pitch),
            "iou": iou,
            "aspect": aspect,
            "aspectTerm": aspect_term,
            "landscape": landscape,
            "hybrid": hybrid,
        }

    # Flight-attitude prior: pitch >=80 under upright camera. Pick max IoU in that
    # band — aspect-weighted hybrids still slide toward divey pitch~65.
    pool: list[dict[str, Any]] = []
    for roll in range(-30, 71, 10):
        for pitch in (80, 85, 90):
            row = _score(roll, pitch)
            pool.append(row)
            print(
                f"flyer orient roll={roll:+d} pitch={pitch:+d} "
                f"iou={row['iou']:.3f} asp={row['aspect']:.2f} hyb={row['hybrid']:.3f}",
                flush=True,
            )
    chosen = max(pool, key=lambda row: (float(row["iou"]), float(row["hybrid"])))
    if float(chosen["pitchDeg"]) < 80.0:
        raise RuntimeError(
            f"flyer orient lock failed flight-pitch gate: pitch={chosen['pitchDeg']:.1f} "
            f"(need >=80); best={chosen}"
        )
    meta = {
        "selectedBy": "flight_pitch_ge80_max_iou_roll_pitch",
        "rollDeg": chosen["rollDeg"],
        "pitchDeg": chosen["pitchDeg"],
        "iou": chosen["iou"],
        "aspect": chosen["aspect"],
        "aspectTerm": chosen["aspectTerm"],
        "landscape": chosen["landscape"],
        "hybrid": chosen["hybrid"],
        "targetAspect": target_aspect,
        "candidates": pool,
        "rootRotation": {
            "camera_forward": float(chosen["rollDeg"]),
            "camera_right": float(chosen["pitchDeg"]),
            "camera_up": 0.0,
        },
    }
    (output_dir / "flyer_roll_lock.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"flyer orient lock roll={meta['rollDeg']} pitch={meta['pitchDeg']} "
        f"iou={meta['iou']:.3f} asp={meta['aspect']:.2f} hyb={meta['hybrid']:.3f} "
        f"(targetAsp={target_aspect:.3f})",
        flush=True,
    )
    del experiment
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return meta



def _geometry_polish_frozen_root(
    *,
    config,
    mesh: Path,
    camera_fit: Path,
    output_dir: Path,
    initial_poses: dict[int, dict[str, Any]],
    notebook_kwargs: dict[str, Any],
) -> Any:
    """Short silhouette/geometry joint polish with root held at the flyer prior."""
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    polish_kwargs = dict(notebook_kwargs)
    polish_kwargs.update(
        {
            "score_mode": "geometry",
            "depth_weight": 0.0,
            "silhouette_weight": 1.0,
            "chroma_weight": 0.0,
            "motion_weight": 0.0,
            "collision_enabled": False,
            "collision_weight": 0.0,
            "chain_space_enabled": False,
            "gradient_ladder_enabled": False,
            "ik_enabled": False,
            "root_search_enabled": False,
            # Keep all three axes so a frozen flyer prior with camera_up ≠ 0 is not masked.
            "root_rotation_axes": ("camera_forward", "camera_right", "camera_up"),
            "root_rotation_camera_up_limit_deg": 180.0,
            "root_rotation_first_frame_limit_deg": 180.0,
            "root_rotation_per_frame_limit_deg": 180.0,
            "root_rotation_defer_camera_up": False,
            "profile_init_enabled": False,
            "physics_smooth_enabled": True,
            "physics_smooth_stiffness": 90.0,
            "physics_smooth_gravity": 0.81,
            "physics_smooth_gravity_weight": 0.3,
            "articulated_iterations": 0,
            "fine_iterations": 0,
            "base_pose_enabled": False,
            "mid_pose_enabled": False,
            "branch_rescue_enabled": False,
            "root_refit_after_base_enabled": False,
            "fine_root_enabled": False,
            "initial_poses": initial_poses,
            "search_bones": FLYER_SEARCH_BONES,
            "include_unlisted_search_bones": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"geometry polish frozen-root -> {output_dir}", flush=True)
    return run_gpu_depth_fit_from_hybrid_config(config, output_dir=output_dir, **polish_kwargs)


def hybrid_kwargs(*, unit_class: str) -> dict[str, Any]:
    flyer = str(unit_class) == "flyer"
    kwargs: dict[str, Any] = {
        # Flyers stay on silhouette; DINOv3 artic was pulling wings into a bank.
        "score_mode": ("geometry" if flyer else "dinov3_dense"),
        "chain_space_enabled": False,
        "gradient_ladder_enabled": False,
        "ik_enabled": False,
        "collision_enabled": False,
        "collision_weight": 0.0,
        "depth_weight": 0.0,
        "silhouette_weight": (1.0 if flyer else 0.0),
        "chroma_weight": 0.0,
        "motion_weight": 0.0,
        "joint_unique_gain_weight": 0.0,
        "fine_unique_gain_weight": 0.0,
        # Flyers: freeze root at true head→tail tip; keep all three axes.
        "root_search_enabled": (not flyer),
        "root_rotation_axes": (
            ("camera_forward", "camera_right", "camera_up")
            if flyer
            else ("camera_forward", "camera_right", "camera_up")
        ),
        # Flyers need a wide yaw cap so frozen tips with |up|>45 are not clamped.
        "root_rotation_camera_up_limit_deg": (180.0 if flyer else 45.0),
        "root_rotation_first_frame_limit_deg": (180.0 if flyer else 30.0),
        "root_rotation_per_frame_limit_deg": (180.0 if flyer else 30.0),
        "root_rotation_defer_camera_up": (not flyer),
        "profile_init_enabled": (not flyer),
        "profile_init_camera_basis_mode": "upright_turntable",
        "profile_init_yaw_step_deg": 15.0,
        "profile_init_roll_range_deg": 8.0,
        "profile_init_roll_step_deg": 8.0,
        "profile_init_facing_weight": None,
        "profile_init_rank_metric": None,
        "physics_smooth_enabled": (not flyer),
        "physics_smooth_stiffness": 90.0,
        "physics_smooth_gravity": 0.81,
        "physics_smooth_gravity_weight": 0.3,
        "articulated_iterations": (0 if flyer else 1),
        "fine_iterations": 0,
        "base_pose_enabled": False,
        "mid_pose_enabled": False,
        "branch_rescue_enabled": False,
        "root_refit_after_base_enabled": (not flyer),
        "fine_root_enabled": (not flyer),
    }
    if flyer:
        kwargs["search_bones"] = FLYER_SEARCH_BONES
        kwargs["include_unlisted_search_bones"] = False
    return kwargs


def _silhouette_seed_frozen_root(
    *,
    config,
    output_dir: Path,
    notebook_kwargs: dict[str, Any],
) -> Any:
    """Short silhouette-only joint pass with root held at identity."""
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    kw = dict(notebook_kwargs)
    kw.update(
        {
            "score_mode": "geometry",
            "depth_weight": 0.0,
            "silhouette_weight": 1.0,
            "chroma_weight": 0.0,
            "motion_weight": 0.0,
            "collision_enabled": False,
            "collision_weight": 0.0,
            "chain_space_enabled": False,
            "gradient_ladder_enabled": False,
            "ik_enabled": False,
            "root_search_enabled": False,
            "root_rotation_axes": ("camera_forward",),
            "root_rotation_defer_camera_up": False,
            "profile_init_enabled": False,
            "physics_smooth_enabled": True,
            "articulated_iterations": 1,
            "fine_iterations": 0,
            "base_pose_enabled": False,
            "mid_pose_enabled": False,
            "branch_rescue_enabled": False,
            "root_refit_after_base_enabled": False,
            "fine_root_enabled": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"silhouette seed frozen-root -> {output_dir}", flush=True)
    return run_gpu_depth_fit_from_hybrid_config(config, output_dir=output_dir, **kw)



def _bake_flyer_autolock_arm(
    *,
    mesh: Path,
    scaled_cam: Path,
    sprite_dir: Path,
    seeded: dict[int, dict[str, Any]],
    arm_dir: Path,
) -> dict[str, Any]:
    """Persist autolock poses and raster previews without re-optimizing.

    Flyer class policy: attitude/wings are owned by autolock. Re-running the
    cascade with artic=0 was reporting IoU far below the same poses re-evaluated
    after export; bake-only keeps scored poses and delivery rasters aligned.
    """
    from dataclasses import fields

    from cascade_clip_pose_tweak import raster_tweak_preview
    from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

    arm_dir.mkdir(parents=True, exist_ok=True)
    bake_cfg = GpuCascadeConfig(
        score_mode="geometry",
        silhouette_weight=1.0,
        depth_weight=0.0,
        chroma_weight=0.0,
        motion_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        root_search_enabled=False,
        optimize_root_translation=False,
        optimize_root_rotation=False,
        root_rotation_defer_camera_up=False,
        root_rotation_axes=("camera_forward", "camera_right", "camera_up"),
        root_rotation_camera_up_limit_deg=180.0,
        articulated_iterations=0,
        fine_iterations=0,
        physics_smooth_enabled=False,
        exact_raster_enabled=True,
        return_masks=True,
        resolution=(160, 140),
        skip_tiny_bones=True,
        bone_order_mode="dependency",
    )
    bake_cfg.validate()

    frame_indices = tuple(sorted(int(k) for k in seeded))
    pngs = sorted(sprite_dir.glob("*.png"))
    if len(pngs) < len(frame_indices):
        raise RuntimeError(
            f"flyer bake: expected >= {len(frame_indices)} sprites in {sprite_dir}, got {len(pngs)}"
        )
    target_paths = [
        str(pngs[int(fi)].resolve()).replace("\\", "/") for fi in frame_indices
    ]

    experiment = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=scaled_cam,
        target_frame_dir=sprite_dir,
        frame_indices=frame_indices,
        config=bake_cfg,
    )
    bone, root_t, root_r = experiment._initial_pose_tensors(seeded)
    scored = experiment.evaluate(bone, root_t, root_r)
    frame_iou = [
        float(v) for v in scored["silhouetteIoU"].detach().cpu().numpy().reshape(-1)
    ]
    print(
        f"flyer bake evaluate frameIoU={[round(v, 3) for v in frame_iou]} "
        f"mean={sum(frame_iou)/max(len(frame_iou),1):.3f}",
        flush=True,
    )

    config_dict: dict[str, Any] = {}
    for f in fields(GpuCascadeConfig):
        value = getattr(bake_cfg, f.name)
        if isinstance(value, tuple):
            config_dict[f.name] = list(value)
        elif hasattr(value, "as_posix"):
            config_dict[f.name] = str(value)
        else:
            try:
                json.dumps(value)
                config_dict[f.name] = value
            except TypeError:
                config_dict[f.name] = str(value)

    payload: dict[str, Any] = {
        "poses": {str(int(k)): dict(v) for k, v in seeded.items()},
        "cameraFitPath": str(scaled_cam.resolve()).replace("\\", "/"),
        "config": config_dict,
        "targetPaths": target_paths,
        "frameIndices": list(frame_indices),
        "frameIoU": frame_iou,
        "score": float(sum(frame_iou) / max(len(frame_iou), 1)),
        "solver": "flyer_hybrid_autolock_bake",
        "root_search_enabled": False,
        "searched": False,
        "proof": "autolock bake; geometry evaluate + unlit raster; not cascade artic",
    }
    preview = raster_tweak_preview(
        payload=payload,
        mesh_glb=mesh,
        output_dir=arm_dir,
        frame_indices=None,
    )
    clip_path = Path(preview.get("clipResultPath") or (arm_dir / "gpu_clip_result.json"))
    if not clip_path.is_file():
        raise RuntimeError(f"flyer bake missing clip result: {clip_path}")
    return {
        "clipResultPath": str(clip_path),
        "pose_result": json.loads(clip_path.read_text(encoding="utf-8")),
        "preview": preview,
        "frameIoU": frame_iou,
    }



def fit_clip(label: str) -> dict[str, Any]:
    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_gpu_cascade_experiment import MOTION_ROOT_ROTATION_KEY

    spec = CLIPS[label]
    mesh = Path(spec["mesh"])
    if not mesh.is_file():
        raise FileNotFoundError(mesh)
    out = OUT_ROOT / METHOD_ID / label
    arm_dir = out / METHOD_ID
    arm_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    choice = _build_isolated_def_choice(
        widgets,
        unit_sid=str(spec["unit_sid"]),
        def_groups=tuple(int(g) for g in spec["def_groups"]),
    )
    camera_lock = {
        "selectedBy": "clip_local_profile_init",
        "note": "flyers use upright idle camera + root pitch/roll lock",
    }
    roll_lock = None
    config = _prepare_choice_config(choice, mesh, NOTEBOOK)
    gpu_kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
    gpu_kwargs.update(hybrid_kwargs(unit_class=str(spec["unit_class"])))
    if str(spec["unit_class"]) == "flyer":
        from flyer_hybrid_autolock import autolock_flyer_clip

        side_cam = Path(spec.get("side_camera") or "")
        if not side_cam.is_file():
            # Fall back to the clip's prepared camera_fit (profile/idle) as base.
            side_cam = Path(getattr(config, "camera_fit_path", "") or "")
        if not side_cam.is_file():
            raise RuntimeError(
                f"{label}: flyer needs side_camera or camera_fit_path as scale base"
            )
        wing_bones = tuple(spec.get("wing_bones") or FLYER_SEARCH_BONES)
        refine_bones = tuple(spec.get("refine_bones") or FLYER_REFINE_BONES)
        sprite_dir = Path(_sprite_dir(choice))
        autolock_dir = out / "flyer_autolock"
        print(
            f"flyer autolock base_cam={side_cam} wing_bones={wing_bones}",
            flush=True,
        )
        auto = autolock_flyer_clip(
            mesh=mesh,
            base_camera=side_cam,
            sprite_dir=sprite_dir,
            out_dir=autolock_dir,
            wing_bones=wing_bones,
            bone_roles_path=Path(spec["bone_roles"]) if spec.get("bone_roles") else None,
            head_bone=str(spec["head_bone"]) if spec.get("head_bone") else None,
            tail_bone=str(spec["tail_bone"]) if spec.get("tail_bone") else None,
            refine_wings_per_frame=True,
            refine_bones=refine_bones,
        )
        scaled_cam = Path(auto["cameraFit"])
        config.camera_fit_path = str(scaled_cam)
        if hasattr(config, "joint_free_deg"):
            config.joint_free_deg = 150.0
        gpu_kwargs["profile_init_enabled"] = False
        camera_lock = {
            "selectedBy": "flyer_hybrid_autolock_v1",
            "cameraFit": str(scaled_cam).replace("\\", "/"),
            "baseCamera": str(side_cam).replace("\\", "/"),
            "autolockReport": str(autolock_dir / "autolock_report.json").replace("\\", "/"),
            "scale": auto.get("scale"),
            "headBone": auto.get("headBone"),
            "tailBone": auto.get("tailBone"),
            "tipFrame0": auto.get("tipFrame0"),
            "rootTranslation": auto.get("rootTranslation"),
            "note": (
                "flyer class: auto scale + HT-gated tip + sprite phase wing refine; "
                "root frozen; artic=0; no authored tip Euler table"
            ),
        }
        seeded = {int(k): dict(v) for k, v in (auto.get("poses") or {}).items()}
        if not seeded:
            raise RuntimeError(f"{label}: flyer autolock produced no poses")
        gpu_kwargs["initial_poses"] = seeded
        camera_lock["autolockSeed"] = {
            "path": str(autolock_dir / "autolock_report.json").replace("\\", "/"),
            "note": "autolock poses freeze tip/root; final geometry pass artic=0",
        }
        print(
            f"flyer autolock tip0={auto.get('tipFrame0')} "
            f"scale={auto.get('scale', {}).get('scale')} "
            f"frames={len(seeded)}",
            flush=True,
        )
        _release_gpu_workspace()

    notes = {
        "schema": "hybrid_method_quad.v18",
        "methodId": METHOD_ID,
        "label": label,
        "title": spec["title"],
        "unitClass": spec["unit_class"],
        "budgetSec": BUDGET_SEC,
        "knobs": hybrid_kwargs(unit_class=str(spec["unit_class"])),
        "cameraLock": camera_lock,
        "rollLock": None
        if roll_lock is None
        else {
            key: roll_lock[key]
            for key in (
                "selectedBy",
                "rollDeg",
                "pitchDeg",
                "iou",
                "aspect",
                "aspectTerm",
                "landscape",
                "hybrid",
                "targetAspect",
                "rootRotation",
            )
        },
        "not": "CURRENT_CASCADE_KEEP; idle keep untouched",
        "v7Failure": (
            "v15 facing_weight=0 still ranked by composite silhouette score, which "
            "picked yaw=130/roll=75 dive over max-IoU yaw=-80/roll=-90; v16 ranks by IoU"
        ),
    }
    (out / "notes.json").write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    frame_count = len(config.frame_indices)
    print(f"fit {label} frames={frame_count} class={spec['unit_class']}", flush=True)

    if str(spec["unit_class"]) == "flyer":
        if "initial_poses" not in gpu_kwargs or not gpu_kwargs["initial_poses"]:
            raise RuntimeError(f"{label}: flyer bake requires autolock initial_poses")
        bake = _bake_flyer_autolock_arm(
            mesh=mesh,
            scaled_cam=Path(config.camera_fit_path),
            sprite_dir=Path(_sprite_dir(choice)),
            seeded={int(k): dict(v) for k, v in gpu_kwargs["initial_poses"].items()},
            arm_dir=arm_dir,
        )
        # Match AnimationSolveResult-ish surface used below.
        class _Solved:
            def __init__(self, bake_row: dict[str, Any]):
                self.pose_result = dict(bake_row["pose_result"])
                self.pose_result["clipResultPath"] = bake_row["clipResultPath"]

        solved = _Solved(bake)
    else:
        solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm_dir, **gpu_kwargs)
    elapsed = time.perf_counter() - started
    result_path = Path(solved.pose_result["clipResultPath"])
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    config_out = payload.get("config") or {}
    # Flyers: geometry silhouette final. Ground: DINOv3 dense.
    expected_score = "geometry" if str(spec["unit_class"]) == "flyer" else "dinov3_dense"
    if str(config_out.get("score_mode")) != expected_score:
        raise RuntimeError(
            f"{label}: expected {expected_score}, got {config_out.get('score_mode')}"
        )
    if not bool(config_out.get("physics_smooth_enabled")) and str(spec["unit_class"]) != "flyer":
        raise RuntimeError(f"{label}: physics_smooth_enabled did not stay on")
    if bool(config_out.get("physics_smooth_enabled")) and str(spec["unit_class"]) == "flyer":
        raise RuntimeError(f"{label}: flyer must keep physics_smooth off (warps frozen tip)")
    if bool(config_out.get("chain_space_enabled")):
        raise RuntimeError(f"{label}: chain_space must stay off")
    root_axes = tuple(config_out.get("root_rotation_axes") or ())
    # Autolock bake may omit root_rotation_axes in config; honor hybrid knobs.
    if not root_axes and str(spec["unit_class"]) == "flyer":
        root_axes = ("camera_forward", "camera_right", "camera_up")
    root0 = (payload.get("poses") or {}).get("0", {}).get(MOTION_ROOT_ROTATION_KEY) or {}
    if str(spec["unit_class"]) == "flyer":
        if bool(config_out.get("root_search_enabled")):
            raise RuntimeError(f"{label}: flyer must freeze root (root_search off)")
        if root_axes != ("camera_forward", "camera_right", "camera_up"):
            raise RuntimeError(
                f"{label}: flyer root axes must include camera_up when frozen, got {root_axes}"
            )
        tip0 = camera_lock.get("tipFrame0") or []
        if len(tip0) == 3:
            fwd = float(root0.get("camera_forward") or 0.0)
            right = float(root0.get("camera_right") or 0.0)
            up = float(root0.get("camera_up") or 0.0)
            need_f, need_r, need_u = float(tip0[0]), float(tip0[1]), float(tip0[2])
            if abs(fwd - need_f) > 1.5 or abs(right - need_r) > 1.5 or abs(up - need_u) > 1.5:
                raise RuntimeError(
                    f"{label}: flyer autolock tip not held "
                    f"(root0 forward={fwd}, right={right}, up={up}; "
                    f"need ~{need_f}/~{need_r}/~{need_u}); "
                    "frozen root must honor initial_poses"
                )
    else:
        if not bool(config_out.get("root_search_enabled")):
            raise RuntimeError(f"{label}: root_search_enabled must stay on for ground")
        if root_axes != ("camera_forward", "camera_right", "camera_up"):
            raise RuntimeError(f"{label}: expected full root axes, got {root_axes}")
    if str(spec["unit_class"]) == "flyer":
        knobs = hybrid_kwargs(unit_class="flyer")
        if bool(knobs.get("profile_init_enabled")):
            raise RuntimeError(f"{label}: flyer must skip profile_init and reuse side camera")
        if bool(knobs.get("root_search_enabled")):
            raise RuntimeError(f"{label}: flyer must freeze root (search off)")
    gif = compose_clip_gif(
        clip_root=out,
        sprite_dir=_sprite_dir(choice),
        frame_count=frame_count,
        arms=({"id": METHOD_ID},),
    )
    report = {
        "label": label,
        "title": spec["title"],
        "gif": str(gif).replace("\\", "/"),
        "clipResult": str(result_path).replace("\\", "/"),
        "score": payload.get("score"),
        "elapsedSec": round(elapsed, 1),
        "budgetSec": BUDGET_SEC,
        "withinBudget": elapsed <= BUDGET_SEC,
        "frameCount": frame_count,
        "unitClass": spec["unit_class"],
        "score_mode": config_out.get("score_mode"),
        "root_search_enabled": config_out.get("root_search_enabled"),
        "root_rotation_axes": list(root_axes),
        "root0": root0,
        "rollLockDeg": None if roll_lock is None else roll_lock.get("rollDeg"),
        "pitchLockDeg": None if roll_lock is None else roll_lock.get("pitchDeg"),
        "profileInitRollRangeDeg": config_out.get("profile_init_roll_range_deg"),
        "physics_smooth_enabled": config_out.get("physics_smooth_enabled"),
        "profile": payload.get("initialization") or payload.get("profile"),
        "proof": "generated-artifact; hybrid trial; not CURRENT_CASCADE_KEEP; not OE runtime",
    }
    (out / "run_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if elapsed > BUDGET_SEC:
        raise RuntimeError(
            f"{label}: exceeded {BUDGET_SEC:.0f}s budget ({elapsed:.1f}s); "
            "hybrid knobs must get cheaper before retrying this clip"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clips",
        default="roc_move",
        help=f"comma-separated labels from {sorted(CLIPS)}",
    )
    args = parser.parse_args()
    wanted = [part.strip() for part in str(args.clips).split(",") if part.strip()]
    unknown = sorted(set(wanted) - set(CLIPS))
    if unknown:
        raise SystemExit(f"unknown clips: {unknown}; known={sorted(CLIPS)}")
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    reports: list[dict[str, Any]] = []
    try:
        for label in wanted:
            reports.append(fit_clip(label))
            _release_gpu_workspace()
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock, pid=os.getpid())
    summary = {
        "methodId": METHOD_ID,
        "budgetSec": BUDGET_SEC,
        "reports": reports,
        "allWithinBudget": all(bool(row.get("withinBudget")) for row in reports),
    }
    out_dir = OUT_ROOT / METHOD_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(out_dir / "summary.json"), "n": len(reports)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
