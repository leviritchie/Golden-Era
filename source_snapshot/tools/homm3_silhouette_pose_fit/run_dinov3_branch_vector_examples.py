#!/usr/bin/env python3
"""Fit and compose three full-clip DINOv3 branch-vector experiment GIFs.

This is an isolated generated-candidate lane. It deliberately does not match
``CURRENT_CASCADE_KEEP`` and is not a delivery or Olden Era runtime proof.
"""
from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import math
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
DEFAULT_OUT = ROOT / "artifacts/pose_picker_runs/dinov3_autograd_examples_v6"
MODEL_ID = "facebook/dinov3-vits16-pretrain-lvd1689m"
RIG_AUTHORITY = "foreign_smartrig_diagnostic_no_owned_bind"
MEANINGFUL_BONE_MOTION_DEG = 1.0

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import clip_result_matches_current_keep  # noqa: E402
from cascade_chain_space import trust_region_backtracking_steps  # noqa: E402
from run_crusader_full_animation_set import (  # noqa: E402
    _literal_config_kwargs,
    _notebook_config,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)


CLIPS = (
    {
        "label": "angel_move",
        "unit_sid": "h3_angel",
        "animation": "idle_start_move_end",
        "frame_count": 28,
        "title": "Angel move",
    },
    {
        "label": "hobgoblin_attack",
        "unit_sid": "h3_hobgoblin",
        "animation": "idle_attack_front",
        "frame_count": 22,
        "title": "Hobgoblin attack",
    },
    {
        "label": "crusader_death",
        "unit_sid": "h3_crusader",
        "animation": "idle_death",
        "frame_count": 14,
        "title": "Crusader death",
    },
)

MESH_BY_UNIT = {
    "h3_angel": ROOT / "artifacts/meshy_downloads/h3_angel_smartrigged_rigidized.glb",
    "h3_hobgoblin": ROOT
    / "artifacts/meshy_downloads/h3_hobgoblin_smartrigged_rigidized.glb",
    "h3_crusader": ROOT
    / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
}

CONTRACT_ENTRY_SOURCES = (
    TOOL / "dense_semantic_features.py",
    TOOL / "cascade_chain_space.py",
    TOOL / "roc_gpu_cascade_experiment.py",
    TOOL / "gpu_raster_depth_animation.py",
    TOOL / "run_dinov3_branch_vector_examples.py",
    TOOL / "compose_method_compare_gif.py",
)

EXPERIMENT_KWARGS = {
    "score_mode": "dinov3_dense",
    "dense_semantic_model_id": MODEL_ID,
    "dense_semantic_feature_layers": ("last",),
    "dense_semantic_local_radius": 1,
    "dense_semantic_position_weight": 1.0,
    "dense_semantic_autograd_enabled": True,
    "dense_semantic_batch_size": 2,
    "dense_semantic_raster_scale": 3,
    "dense_semantic_subject_crop": False,
    "profile_init_enabled": False,
    "joint_solver_mode": "branch_vector",
    "depth_weight": 0.0,
    "silhouette_weight": 0.0,
    "chroma_weight": 0.0,
    "motion_weight": 0.0,
    "collision_enabled": False,
    "collision_weight": 0.0,
    "joint_unique_gain_weight": 0.0,
    "fine_unique_gain_weight": 0.0,
    "root_search_enabled": False,
    "root_rotation_defer_camera_up": False,
    "joint_adaptive_step_enabled": False,
    "chain_space_enabled": True,
    "chain_space_mode": "branch_trust",
    "chain_space_iterations": 4,
    "chain_space_trust_radius_deg": 20.0,
    "chain_space_trust_radius_min_deg": 1.25,
    "chain_space_trust_radius_max_deg": 40.0,
    "chain_space_min_clip_improvement": 1e-6,
    "chain_space_eval_budget": None,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "ik_enabled": False,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": False,
    "root_refit_after_base_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": False,
    "articulated_iterations": 0,
    "fine_iterations": 0,
    "fine_root_enabled": False,
    "fine_only_leaf_length_frac": 0.0,
    "skip_tiny_bones": False,
    "include_unlisted_search_bones": True,
    "bone_order_mode": "dependency",
    "live_preview": False,
}


def _canonical(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value.resolve()).replace("\\", "/")
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _canonical_gpu_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize serialized path fields without weakening exact config checks."""

    normalized = _canonical(config)
    if not isinstance(normalized, dict):
        raise TypeError("GpuCascadeConfig snapshot must be a mapping")
    for name, value in normalized.items():
        if not isinstance(value, str) or not value:
            continue
        if name.endswith(("_path", "_dir")):
            normalized[name] = str(Path(value).resolve()).replace("\\", "/")
    return normalized


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_module_path(module: str) -> Path | None:
    if not str(module).strip():
        return None
    base = TOOL.joinpath(*str(module).split("."))
    module_file = base.with_suffix(".py")
    if module_file.is_file():
        return module_file.resolve()
    package_file = base / "__init__.py"
    if package_file.is_file():
        return package_file.resolve()
    return None


def _contract_source_hashes() -> dict[str, str]:
    """Hash the transitive local import closure plus dynamic hybrid fragments."""

    roots = {Path(path).resolve() for path in CONTRACT_ENTRY_SOURCES}
    roots.update(path.resolve() for path in TOOL.glob("roc_semantic_hybrid_*.py"))
    pending = list(roots)
    discovered: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in discovered:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        discovered.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and int(node.level or 0) == 0:
                if node.module:
                    modules.append(node.module)
            for module in modules:
                dependency = _local_module_path(module)
                if dependency is not None and dependency not in discovered:
                    pending.append(dependency)
    return {
        path.relative_to(ROOT).as_posix(): _file_hash(path)
        for path in sorted(discovered, key=lambda value: value.as_posix().lower())
    }


def _distribution_version(name: str) -> str:
    try:
        return str(importlib.metadata.version(name))
    except importlib.metadata.PackageNotFoundError:
        return "not-installed-as-distribution"


def _runtime_contract() -> dict[str, Any]:
    import numpy
    import torch
    import transformers
    from PIL import __version__ as pillow_version
    from nvdiffrast_local import ensure_local_nvdiffrast

    if not torch.cuda.is_available():
        raise RuntimeError("DINOv3 branch-vector examples require CUDA")
    device = torch.cuda.get_device_properties(0)
    nvdiffrast_vendor = ensure_local_nvdiffrast(required=True).resolve()
    nvdiffrast_spec = importlib.util.find_spec("nvdiffrast")
    nvdiffrast_origin = (
        Path(str(nvdiffrast_spec.origin)).resolve()
        if nvdiffrast_spec is not None and nvdiffrast_spec.origin
        else None
    )
    return _canonical(
        {
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "torchCuda": str(torch.version.cuda),
            "cudnn": int(torch.backends.cudnn.version() or 0),
            "transformers": str(transformers.__version__),
            "torchvision": _distribution_version("torchvision"),
            "huggingfaceHub": _distribution_version("huggingface-hub"),
            "safetensors": _distribution_version("safetensors"),
            "numpy": str(numpy.__version__),
            "pillow": str(pillow_version),
            "nvdiffrastDistribution": _distribution_version("nvdiffrast"),
            "nvdiffrastOrigin": (
                None
                if nvdiffrast_origin is None
                else str(nvdiffrast_origin).replace("\\", "/")
            ),
            "nvdiffrastOriginSha256": (
                None
                if nvdiffrast_origin is None or not nvdiffrast_origin.is_file()
                else _file_hash(nvdiffrast_origin)
            ),
            "nvdiffrastVendorFiles": {
                path.relative_to(nvdiffrast_vendor).as_posix(): {
                    "size": int(path.stat().st_size),
                    "sha256": _file_hash(path),
                }
                for path in sorted(nvdiffrast_vendor.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            },
            "cudaDevice": {
                "name": str(device.name),
                "computeCapability": [int(device.major), int(device.minor)],
                "totalMemory": int(device.total_memory),
            },
        }
    )


def _verify_png_sequence(folder: Path, frame_count: int, *, label: str) -> list[Path]:
    folder = Path(folder)
    expected_names = [f"{index:02d}.png" for index in range(int(frame_count))]
    actual_names = sorted(path.name for path in folder.glob("*.png") if path.is_file())
    if actual_names != expected_names:
        raise RuntimeError(
            f"{label} PNG sequence must be exactly {expected_names[0]}.."
            f"{expected_names[-1]}; got {actual_names[:4]}..{actual_names[-4:]}"
        )
    paths = [folder / name for name in expected_names]
    for path in paths:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            if int(image.width) < 1 or int(image.height) < 1:
                raise RuntimeError(f"{label} PNG is empty: {path}")
    return paths


def _verify_gif(path: Path, *, frame_count: int, duration_ms: int) -> None:
    with Image.open(path) as gif:
        if int(getattr(gif, "n_frames", 1)) != int(frame_count):
            raise RuntimeError(f"GIF frame count mismatch at {path}")
        if int(gif.info.get("duration", 0)) != int(duration_ms):
            raise RuntimeError(f"GIF timing mismatch at {path}")
        for index in range(int(frame_count)):
            gif.seek(index)
            frame = gif.copy()
            frame.load()


def _frame_set_hash(folder: Path, frame_count: int, *, label: str = "target") -> str:
    rows = [
        {"name": path.name, "sha256": _file_hash(path)}
        for path in _verify_png_sequence(folder, frame_count, label=label)
    ]
    return _json_hash(rows)


def _model_snapshot() -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    snapshot = Path(
        snapshot_download(repo_id=MODEL_ID, local_files_only=True)
    ).resolve()
    required = ("config.json", "preprocessor_config.json", "model.safetensors")
    files = {}
    for name in required:
        path = snapshot / name
        if not path.is_file():
            raise FileNotFoundError(path)
        files[name] = {"size": path.stat().st_size, "sha256": _file_hash(path)}
    return {
        "modelId": MODEL_ID,
        "snapshot": str(snapshot).replace("\\", "/"),
        "snapshotId": snapshot.name,
        "files": files,
    }


def _filter_fit_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.difference_update({"config", "output_dir"})
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError(
            "notebook GPU kwargs are not adapter parameters: " + ", ".join(unknown)
        )
    return {name: kwargs[name] for name in kwargs if name in allowed}


def _select_choice(widgets, *, unit_sid: str, animation: str):
    matches = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == unit_sid
        and choice.animation_name == animation
        and choice.source_kind == "authentic_def"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one authentic DEF {unit_sid}:{animation}, found {len(matches)}"
        )
    return matches[0]


def _sprite_dir(choice) -> Path:
    return Path(choice.pilot_dir) / (
        f"frames_def12_nn_{choice.animation_name}_shadow_culled"
    )


def _prepare_choice_config(choice, mesh: Path, notebook: Path):
    from roc_semantic_hybrid_experiment import RocHybridConfig

    notebook_kwargs = _literal_config_kwargs(notebook, require_dino=False)
    config = _notebook_config(RocHybridConfig, notebook_kwargs, notebook=notebook)
    overrides = _choice_overrides(choice, mesh)
    # These smart-rig GLBs have no matching owned-bind report. This experiment
    # therefore declares diagnostic rig authority instead of accepting the
    # unrelated Cavalier report or silently weakening a delivery gate.
    overrides["meshy_rigidization_report"] = None
    overrides["require_meshy_rigidization"] = False
    return prepare_gpu_targets(replace(config, **overrides))


def _clip_manifest(
    *,
    spec: Mapping[str, Any],
    choice,
    mesh: Path,
    config,
    fit_kwargs: Mapping[str, Any],
    effective_config: Mapping[str, Any],
    model: Mapping[str, Any],
    runtime: Mapping[str, Any],
    notebook: Path,
) -> dict[str, Any]:
    sprite_dir = _sprite_dir(choice).resolve()
    camera_fit = Path(config.camera_fit_path).resolve()
    contract = _contract_source_hashes()
    canonical_effective_config = _canonical(effective_config)
    inputs = {
        "mesh": {"path": mesh.resolve(), "sha256": _file_hash(mesh)},
        "targetFrames": {
            "path": sprite_dir,
            "count": int(spec["frame_count"]),
            "sha256": _frame_set_hash(sprite_dir, int(spec["frame_count"])),
        },
        "cameraFit": {
            "path": camera_fit,
            "sha256": _file_hash(camera_fit),
        },
        "notebook": {
            "path": notebook.resolve(),
            "sha256": _file_hash(notebook),
        },
        "initialPose": "bind_zero_joint_vectors",
        "rigAuthority": {
            "mode": RIG_AUTHORITY,
            "ownedBindValidated": False,
            "meshyRigidizationReport": None,
        },
        "model": model,
        "runtime": runtime,
        "contractSources": contract,
        "fitKwargs": fit_kwargs,
        "effectiveGpuCascadeConfig": canonical_effective_config,
        "effectiveGpuCascadeConfigHash": _json_hash(canonical_effective_config),
    }
    canonical_inputs = _canonical(inputs)
    return {
        "schema": 1,
        "proof": "generated experiment candidate; not delivery or runtime validated",
        "clip": _canonical(spec),
        "inputs": canonical_inputs,
        "inputHash": _json_hash(canonical_inputs),
    }


def _write_or_verify_manifest(
    path: Path, expected: Mapping[str, Any], *, allow_create: bool = True
) -> None:
    canonical = _canonical(expected)
    if path.is_file():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual != canonical:
            raise RuntimeError(
                f"refusing stale or mixed run at {path}; input manifest changed"
            )
        return
    if not bool(allow_create):
        raise RuntimeError(
            f"refusing to reuse output without its original manifest: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(canonical, indent=2) + "\n", encoding="utf-8")


def _release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _validated_branch_decision_rows(
    history: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if len(history) < 2:
        raise RuntimeError("chain-space history needs decisions and one terminal row")
    decision_rows = list(history[:-1])
    terminal = history[-1]
    if any("group" not in row or "finish" in row for row in decision_rows):
        raise RuntimeError("chain-space history contains a mixed or unknown decision row")
    expected_terminal_keys = {"stage", "mode", "finish", "consensusMoved"}
    if set(terminal) != expected_terminal_keys or "group" in terminal:
        raise RuntimeError("DINOv3 branch-vector terminal history shape drifted")
    consensus_moved = terminal["consensusMoved"]
    if (
        terminal["stage"] != "chain_space"
        or terminal["mode"] != "branch_trust"
        or terminal["finish"] != "temporal_consensus"
        or type(consensus_moved) is not int
        or consensus_moved != 0
    ):
        raise RuntimeError("DINOv3 branch-vector terminal history row drifted")
    return decision_rows


def _pose_motion_coverage(
    poses: Mapping[str, Any],
    search_bones: list[str],
) -> dict[str, Any]:
    """Measure serialized joint activity without promoting score to motion proof."""

    threshold_rad = math.radians(MEANINGFUL_BONE_MOTION_DEG)
    max_rotation_deg: dict[str, float] = {}
    for bone in search_bones:
        max_norm = 0.0
        for frame_pose in poses.values():
            if not isinstance(frame_pose, Mapping):
                raise RuntimeError("serialized pose frame is not an object")
            value = frame_pose.get(bone)
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise RuntimeError(f"serialized pose for {bone} is not an object")
            xyz = tuple(float(value.get(axis)) for axis in ("x", "y", "z"))
            if not all(math.isfinite(component) for component in xyz):
                raise RuntimeError(f"serialized pose for {bone} is not finite")
            max_norm = max(max_norm, math.sqrt(sum(component * component for component in xyz)))
        max_rotation_deg[bone] = math.degrees(max_norm)
    exactly_frozen = [bone for bone, value in max_rotation_deg.items() if value <= 1e-7]
    meaningful = [
        bone
        for bone, value in max_rotation_deg.items()
        if math.radians(value) >= threshold_rad
    ]
    count = len(search_bones)
    coverage = float(len(meaningful)) / float(count) if count else 0.0
    if coverage >= 0.75:
        status = "broad"
    elif coverage >= 0.5:
        status = "partial"
    else:
        status = "sparse"
    return {
        "searchBoneCount": count,
        "exactlyFrozenBoneCount": len(exactly_frozen),
        "meaningfullyMovedBoneCount": len(meaningful),
        "meaningfulMotionThresholdDeg": MEANINGFUL_BONE_MOTION_DEG,
        "meaningfulBoneCoverage": coverage,
        "motionCoverageStatus": status,
    }


def _validate_payload(
    payload: Mapping[str, Any],
    *,
    frame_count: int,
    dest: Path,
    input_hash: str,
    effective_config: Mapping[str, Any],
    expected_camera_fit: Path,
) -> dict[str, Any]:
    config = payload.get("config") or {}
    expected_config = _canonical_gpu_config(effective_config)
    expected_config_hash = _json_hash(expected_config)
    if _canonical_gpu_config(config) != expected_config:
        raise RuntimeError("result config does not match the pre-run effective config")
    if str(payload.get("experimentInputHash") or "") != str(input_hash):
        raise RuntimeError("result is not bound to the current input manifest")
    if str(payload.get("experimentConfigHash") or "") != expected_config_hash:
        raise RuntimeError("result effective configuration hash does not match")
    actual_camera_fit = Path(str(payload.get("cameraFitPath") or "")).resolve()
    if actual_camera_fit != Path(expected_camera_fit).resolve():
        raise RuntimeError("result did not use the manifest-owned camera fit")
    expected = {
        "score_mode": "dinov3_dense",
        "dense_semantic_autograd_enabled": True,
        "dense_semantic_batch_size": 2,
        "dense_semantic_subject_crop": False,
        "joint_solver_mode": "branch_vector",
        "chain_space_enabled": True,
        "chain_space_mode": "branch_trust",
        "articulated_iterations": 0,
        "fine_iterations": 0,
        "sa_enabled": False,
        "gradient_ladder_enabled": False,
        "ik_enabled": False,
        "physics_smooth_enabled": False,
        "root_search_enabled": False,
        "root_rotation_defer_camera_up": False,
        "root_refit_after_base_enabled": False,
        "joint_adaptive_step_enabled": False,
        "joint_temporal_consensus_enabled": False,
        "base_pose_enabled": False,
        "mid_pose_enabled": False,
        "branch_rescue_enabled": False,
        "fine_root_enabled": False,
        "fine_only_leaf_length_frac": 0.0,
        "skip_tiny_bones": False,
        "include_unlisted_search_bones": True,
    }
    mismatches = {
        name: {"expected": value, "actual": config.get(name)}
        for name, value in expected.items()
        if config.get(name) != value
    }
    if mismatches:
        raise RuntimeError(f"DINOv3 branch-vector config drift: {mismatches}")
    if clip_result_matches_current_keep(payload):
        raise RuntimeError("experiment result unexpectedly matches CURRENT_CASCADE_KEEP")
    scores = payload.get("frameScores") or []
    if len(scores) != int(frame_count):
        raise RuntimeError(f"result has {len(scores)} frame scores, expected {frame_count}")
    poses = payload.get("poses") or {}
    if not isinstance(poses, Mapping):
        raise RuntimeError("result poses must be a frame-keyed object")
    frame_indices = tuple(int(value) for value in (payload.get("frameIndices") or ()))
    if len(poses) != int(frame_count) or len(frame_indices) != int(frame_count):
        raise RuntimeError(
            "result must serialize one pose and one frame index per source frame"
        )
    if set(str(value) for value in frame_indices) != set(str(key) for key in poses):
        raise RuntimeError("serialized pose keys do not match frameIndices")
    search_bones = [str(value) for value in (payload.get("searchBones") or ())]
    skinned_bones = [str(value) for value in (payload.get("skinnedBones") or ())]
    if len(search_bones) != len(skinned_bones) or set(search_bones) != set(
        skinned_bones
    ):
        raise RuntimeError(
            "branch_vector searchBones must cover every solver-eligible deforming bone"
        )
    topology = [
        row
        for row in (payload.get("branchGroups") or ())
        if row.get("kind") == "branch_vector"
    ]
    if not search_bones or not topology:
        raise RuntimeError("result does not serialize branch-vector topology")
    if [int(row.get("group")) for row in topology] != list(range(len(topology))):
        raise RuntimeError("branch-vector topology groups are not deterministic")
    if any(row.get("mode") != "branch_trust" for row in topology):
        raise RuntimeError("branch-vector topology contains the wrong mode")
    owned_bones = [str(bone) for row in topology for bone in row.get("bones") or ()]
    if len(owned_bones) != len(set(owned_bones)):
        raise RuntimeError("branch-vector topology overlaps bones")
    if set(owned_bones) != set(search_bones) or len(owned_bones) != len(search_bones):
        raise RuntimeError("branch-vector topology does not exactly cover searchBones")
    motion_coverage = _pose_motion_coverage(poses, search_bones)
    _verify_png_sequence(Path(dest) / "solved_rgb", frame_count, label="solved RGB")
    history = list(payload.get("chainSpaceHistory") or [])
    if not history:
        raise RuntimeError("DINOv3 branch-vector result has no chainSpaceHistory")
    decision_rows = _validated_branch_decision_rows(history)
    first_sweep_groups = {
        int(row.get("group"))
        for row in decision_rows
        if int(row.get("sweep") or 0) == 1
    }
    if first_sweep_groups != set(range(len(topology))):
        raise RuntimeError("first branch sweep did not record every topology group")
    attempted = [row for row in decision_rows if not row.get("skipped")]
    plateaus = [row for row in decision_rows if row.get("skipped")]
    if len(attempted) + len(plateaus) != len(decision_rows):
        raise RuntimeError("chain-space history contains an unknown decision state")
    gradient_floor = float(config.get("chain_space_min_gradient_norm") or 0.0)
    if gradient_floor <= 0.0:
        raise RuntimeError("result has an invalid branch gradient floor")
    for row in plateaus:
        grad_rms = float(row.get("gradNormRms"))
        if (
            row.get("skipped") != "gradient_floor"
            or not math.isfinite(grad_rms)
            or grad_rms > gradient_floor
        ):
            raise RuntimeError("branch plateau row violates the finite gradient floor")
    bad = [
        row
        for row in attempted
        if row.get("acceptance") != "whole_clip_atomic"
        or row.get("normalization") != "full_clip_branch_block_rms"
    ]
    if bad:
        raise RuntimeError("result contains a non-atomic or non-RMS DINO branch decision")
    threshold = float(config.get("chain_space_min_clip_improvement") or 0.0)
    radius_min = float(config.get("chain_space_trust_radius_min_deg") or 0.0)
    radius_max = float(config.get("chain_space_trust_radius_max_deg") or 0.0)
    if threshold <= 0.0 or radius_min <= 0.0 or radius_max < radius_min:
        raise RuntimeError("result has invalid branch trust-region controls")
    for row in attempted:
        baseline = float(row.get("baselineObjective"))
        candidate_steps = tuple(float(value) for value in row.get("candidateStepDegs") or ())
        candidates = tuple(float(value) for value in row.get("candidateObjectives") or ())
        selected = float(row.get("selectedObjective"))
        radius = float(row.get("proposalTrustRadius"))
        next_radius = float(row.get("nextTrustRadius"))
        values = (baseline, selected, radius, next_radius, *candidate_steps, *candidates)
        if not candidates or not all(math.isfinite(value) for value in values):
            raise RuntimeError("branch history contains missing or non-finite objectives")
        if radius < radius_min or radius > radius_max:
            raise RuntimeError("branch history trust radius left its declared bounds")
        if next_radius < radius_min or next_radius > radius_max:
            raise RuntimeError("next branch trust radius left its declared bounds")
        expected_steps = trust_region_backtracking_steps(radius, radius_min)
        if candidate_steps != expected_steps or len(candidates) != len(candidate_steps):
            raise RuntimeError(
                "branch trust region did not test every half step down to its floor"
            )
        accepted = bool(row.get("accepted"))
        if accepted:
            winner = max(range(len(candidates)), key=candidates.__getitem__)
            best = candidates[winner]
            if not selected > baseline + threshold:
                raise RuntimeError("accepted branch did not clear the clip improvement gate")
            if not best > baseline + threshold:
                raise RuntimeError("best branch candidate did not clear the strict gate")
            if abs(selected - best) > 1e-7:
                raise RuntimeError("accepted branch did not select the best whole-clip candidate")
            if int(row.get("nMoved") or 0) != int(frame_count):
                raise RuntimeError("accepted branch did not own the complete clip")
            if float(row.get("selectedStepDeg") or 0.0) <= 0.0:
                raise RuntimeError("accepted branch recorded no trust-region step")
            if float(row.get("selectedStepDeg")) > radius:
                raise RuntimeError("accepted branch exceeded its proposal trust radius")
            if abs(float(row.get("selectedStepDeg")) - candidate_steps[winner]) > 1e-9:
                raise RuntimeError("accepted branch step does not own the best candidate")
            expected_next = min(
                max(float(row.get("selectedStepDeg")) * 1.5, radius_min),
                radius_max,
            )
            if abs(next_radius - expected_next) > 1e-9:
                raise RuntimeError("accepted branch recorded the wrong next trust radius")
        else:
            if abs(selected - baseline) > 1e-7:
                raise RuntimeError("rejected branch changed the serialized clip objective")
            if int(row.get("nMoved") or 0) != 0:
                raise RuntimeError("rejected branch reports moved frames")
            if float(row.get("selectedStepDeg") or 0.0) != 0.0:
                raise RuntimeError("rejected branch reports a selected step")
            if abs(next_radius - radius_min) > 1e-9:
                raise RuntimeError("rejected branch recorded the wrong next trust radius")
    accepted_groups = {
        int(row.get("group")) for row in attempted if bool(row.get("accepted"))
    }
    return {
        "frameCount": int(frame_count),
        "score": float(payload.get("score")),
        "evaluationCount": int(payload.get("evaluationCount") or 0),
        "branchVisits": len(attempted),
        "acceptedBranches": sum(bool(row.get("accepted")) for row in attempted),
        "acceptedGroupCount": len(accepted_groups),
        "branchGroupCount": len(topology),
        **motion_coverage,
    }


def _compose_gif(*, out: Path, sprite_dir: Path, solved_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    _verify_png_sequence(sprite_dir, frame_count, label="target")
    _verify_png_sequence(solved_dir, frame_count, label="solved RGB")

    argv = [
        "--out",
        str(out),
        "--cols",
        "2",
        "--cell-w",
        "360",
        "--cell-h",
        "420",
        "--hold",
        "1",
        "--duration-ms",
        "180",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "HoMM3 target",
        str(sprite_dir),
        "--panel",
        "DINOv3 autograd",
        str(solved_dir),
    ]
    old_argv = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old_argv
    if int(code) != 0:
        raise RuntimeError("DINOv3 example GIF composition failed")
    _verify_gif(out, frame_count=frame_count, duration_ms=180)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sweeps", type=int, default=4)
    parser.add_argument("--clip", action="append", dest="clips")
    args = parser.parse_args()
    if int(args.sweeps) < 1:
        raise ValueError("--sweeps must be at least 1")

    wanted = set(args.clips) if args.clips else {row["label"] for row in CLIPS}
    unknown = sorted(wanted - {row["label"] for row in CLIPS})
    if unknown:
        raise RuntimeError(f"unknown --clip labels: {unknown}")

    notebook = Path(args.notebook).resolve()
    out_root = Path(args.out).resolve()
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    try:
        import roc_semantic_hybrid_widgets as widgets
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        notebook_kwargs = _filter_fit_kwargs(notebook_gpu_fit_kwargs(notebook))
        fit_kwargs = {
            **notebook_kwargs,
            **EXPERIMENT_KWARGS,
            "chain_space_iterations": int(args.sweeps),
        }
        model = _model_snapshot()
        runtime = _runtime_contract()
        plan = {
            "schema": 1,
            "proof": "generated experiment candidate; not delivery or runtime validated",
            "objective": "frozen DINOv3 dense mean quality minus clip temporal penalty",
            "gradient": "two-frame float-RGB autograd microbatches",
            "acceptance": "whole-clip atomic trust-region candidate",
            "fitKwargs": _canonical(fit_kwargs),
            "model": model,
            "runtime": runtime,
            "clips": [_canonical(row) for row in CLIPS if row["label"] in wanted],
        }
    except BaseException:
        release_cascade_batch_lock(lock)
        raise
    plan_path = out_root / "experiment_plan.json"
    selected_specs = [row for row in CLIPS if row["label"] in wanted]
    reusing_any = bool(args.compose_only) or (
        bool(args.skip_existing)
        and any(
            (out_root / str(row["label"]) / "fit/gpu_clip_result.json").is_file()
            for row in selected_specs
        )
    )
    try:
        _write_or_verify_manifest(plan_path, plan, allow_create=not reusing_any)
        print(json.dumps(_canonical(plan), indent=2), flush=True)
    except BaseException:
        release_cascade_batch_lock(lock)
        raise
    if args.dry_run:
        release_cascade_batch_lock(lock)
        return 0

    reports = []
    try:
        for spec in CLIPS:
            if spec["label"] not in wanted:
                continue
            mesh = MESH_BY_UNIT[spec["unit_sid"]].resolve()
            if not mesh.is_file():
                raise FileNotFoundError(mesh)
            choice = _select_choice(
                widgets,
                unit_sid=str(spec["unit_sid"]),
                animation=str(spec["animation"]),
            )
            config = _prepare_choice_config(choice, mesh, notebook)
            if len(config.frame_indices) != int(spec["frame_count"]):
                raise RuntimeError(
                    f"{spec['label']} materialized {len(config.frame_indices)} frames, "
                    f"expected {spec['frame_count']}"
                )
            clip_root = out_root / str(spec["label"])
            dest = clip_root / "fit"
            result_path = dest / "gpu_clip_result.json"
            manifest_path = clip_root / "input_manifest.json"
            if result_path.is_file() and not (
                bool(args.skip_existing) or bool(args.compose_only)
            ):
                raise RuntimeError(
                    f"immutable result already exists at {result_path}; use "
                    "--skip-existing only for verified reuse, or choose a new --out"
                )
            if manifest_path.is_file() and not result_path.is_file():
                raise RuntimeError(
                    f"incomplete immutable result slot at {clip_root}; choose a new --out"
                )
            if bool(args.compose_only) and not result_path.is_file():
                raise RuntimeError(f"--compose-only requires an existing result: {result_path}")
            effective_gpu_config = run_gpu_depth_fit_from_hybrid_config(
                config,
                output_dir=dest,
                config_only=True,
                **fit_kwargs,
            )
            effective_config = _canonical_gpu_config(effective_gpu_config.__dict__)
            manifest = _clip_manifest(
                spec=spec,
                choice=choice,
                mesh=mesh,
                config=config,
                fit_kwargs=fit_kwargs,
                effective_config=effective_config,
                model=model,
                runtime=runtime,
                notebook=notebook,
            )
            reusing_result = bool(args.compose_only) or (
                bool(args.skip_existing) and result_path.is_file()
            )
            _write_or_verify_manifest(
                manifest_path,
                manifest,
                allow_create=not reusing_result,
            )

            if not reusing_result:
                started = time.perf_counter()
                print(
                    f"fit {spec['label']} frames={spec['frame_count']} out={dest}",
                    flush=True,
                )
                try:
                    run_gpu_depth_fit_from_hybrid_config(
                        config,
                        output_dir=dest,
                        **fit_kwargs,
                    )
                finally:
                    _release_gpu()
                print(
                    f"fit complete {spec['label']} elapsed={time.perf_counter() - started:.1f}s",
                    flush=True,
                )
            if not result_path.is_file():
                raise FileNotFoundError(result_path)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if not reusing_result:
                payload["experimentInputHash"] = str(manifest["inputHash"])
                payload["experimentConfigHash"] = str(
                    manifest["inputs"]["effectiveGpuCascadeConfigHash"]
                )
                result_path.write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
            validated = _validate_payload(
                payload,
                frame_count=int(spec["frame_count"]),
                dest=dest,
                input_hash=str(manifest["inputHash"]),
                effective_config=effective_config,
                expected_camera_fit=Path(
                    str(manifest["inputs"]["cameraFit"]["path"])
                ),
            )
            gif = _compose_gif(
                out=clip_root / f"{spec['label']}_dinov3_autograd.gif",
                sprite_dir=_sprite_dir(choice),
                solved_dir=dest / "solved_rgb",
                frame_count=int(spec["frame_count"]),
            )
            report = {
                "clip": _canonical(spec),
                **validated,
                "inputHash": manifest["inputHash"],
                "gif": str(gif.resolve()).replace("\\", "/"),
                "result": str(result_path.resolve()).replace("\\", "/"),
                "solvedRgbSha256": _frame_set_hash(
                    dest / "solved_rgb",
                    int(spec["frame_count"]),
                    label="solved RGB",
                ),
                "gifSha256": _file_hash(gif),
                "gifMetadataSha256": _file_hash(gif.with_suffix(".json")),
                "resultSha256": _file_hash(result_path),
                "proof": "generated artifact validated; not delivery or runtime validated",
            }
            report_path = clip_root / "example_report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            reports.append(report)
            print(json.dumps(report, indent=2), flush=True)
        summary = {
            "ok": True,
            "reports": reports,
            "proof": "generated artifact validated; not delivery or runtime validated",
        }
        (out_root / "example_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        release_cascade_batch_lock(lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
