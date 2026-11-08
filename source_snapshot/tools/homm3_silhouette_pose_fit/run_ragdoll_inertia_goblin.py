#!/usr/bin/env python3
"""Fused inertial post-pass on a fused-push walk clip.

Takes fused-push presmooth poses and coasts leftover joint motion into later
frames. This is not a from-idle search and not pose-pipeline delivery.

Writes only under ``artifacts/pose_picker_runs/<unit>/<clip>/ragdoll_inertia_v1/``.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    gpu_config_for_rescore,
    load_clip_result,
    raster_tweak_preview,
    target_frame_dir_from_clip,
)
from fused_push_mesh_raster_budget import apply_mesh_raster_budget  # noqa: E402
from gpu_cascade_batch_lock import SCRIPT_TOKENS, cascade_batch_lock  # noqa: E402
from gpu_post_pose_warp_repair import frozen_pose_tensors  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from ragdoll_inertia_plant import (  # noqa: E402
    REPO_ROOT,
    SOLVER_ID,
    RagdollPlantConfig,
    assert_ragdoll_write_path,
    death_skips_idle_end,
    idle_end_required,
    plant_from_experiment,
)
from ragdoll_inertia_search import (  # noqa: E402
    assert_not_idle_search_clip,
    assert_presmooth_parity,
    assert_score_config,
    boundary_report,
    consolidate_fused_clip,
    idle_and_bands_from_payload,
    plant_constants,
    poses_from_trajectory,
    score_trajectory_gpu,
    strain_of_clip,
)
from roc_gpu_cascade_experiment import (  # noqa: E402
    GpuCascadeExperiment,
    persist_gpu_clip_result,
)
from sprite_pose_feasibility import (  # noqa: E402
    VISION_CHECK_FIXED_CAMERAS,
    VISION_CHECK_ORBIT_YAW_DEG,
    orbit_projection,
    vision_check_frame_positions,
)

UNIT_MESHES = {
    "h3_goblin": ROOT / "artifacts/meshy_downloads/h3_goblin_smartrigged.glb",
    "h3_roc": ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb",
}
WALK_CLIP = "idle_start_move_end"
IDLE_CLIP = "idle"
WALK_DEF_GROUPS = (2, 20, 0, 21, 2)
IDLE_DEF_GROUPS = (2,)
EXPERIMENT_NOTE = """# ragdoll_inertia_v1 (experiment lane only)

Not pose-pipeline compliant. Not `CURRENT_CASCADE_KEEP`. Do not copy these
poses into `fused_push_v24_pipeline/` or `meshy_downloads/`. Do not call
`gpu_cascade_delivery` or skinned-clip/deliberate-motion ship validators.

- Seed is the fused-push presmooth clip, including walk free frames. Gravity is
  off. Leftover from a fused joint change is coasted through the plant and
  faded onto later frames. The fused pose is kept, so a walk is not flattened.
  A run that drops pose amplitude versus rest below 85% of fused is refused.
- Clip is walk (`idle_start_move_end`). That clip already contains idle prefix
  and suffix. Do not run `idle` as a separate ragdoll search.
- Score mix matches the unit's fused presmooth geometry weights. Raster
  chroma_scale is 2 or 3 from the mesh budget — do not copy Goblin chroma 2
  onto Roc. Goblin adapter parity re-scores goblin walk presmooth at
  `score.mean()` 0.6473305 ± 1e-3. That pin is goblin-only.
- Human gate: loop seam, melt/ribbons (top/rear stills), card-flat cheats,
  clamp mismatch. Compare fused-push | ragdoll | occupancy.
- Proof: generated-artifact JSON + GIFs. Not OE battle.
"""


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unit_root(unit: str) -> Path:
    if unit not in UNIT_MESHES:
        raise ValueError(f"unsupported ragdoll unit {unit}")
    return ROOT / "artifacts/pose_picker_runs" / unit


def fused_dir(unit: str, clip: str) -> Path:
    return unit_root(unit) / clip / "fused_push_v24_pipeline"


def output_dir(unit: str, clip: str) -> Path:
    path = unit_root(unit) / clip / SOLVER_ID
    return assert_ragdoll_write_path(path)


def clip_def_groups(clip: str) -> tuple[int, ...]:
    if clip == IDLE_CLIP:
        return IDLE_DEF_GROUPS
    if clip == WALK_CLIP:
        return WALK_DEF_GROUPS
    if clip == "idle_death":
        return (2, 5)
    raise ValueError(f"unhandled clip {clip}")


def build_rescore_experiment(
    payload: Mapping[str, Any],
    mesh: Path,
    *,
    unit: str,
) -> tuple[Any, dict[str, Any]]:
    from dataclasses import fields

    base = gpu_config_for_rescore(payload["config"])
    frames = tuple(int(frame) for frame in payload["frameIndices"])
    kwargs = {item.name: getattr(base, item.name) for item in fields(type(base))}
    updated, chosen = apply_mesh_raster_budget(kwargs, mesh, frame_count=len(frames))
    chroma = int(updated["chroma_scale"])
    if chroma not in (2, 3):
        raise RuntimeError(f"raster budget chroma_scale={chroma} not in {{2, 3}}")
    if unit == "h3_goblin" and chroma != 2:
        raise RuntimeError(
            f"goblin raster budget chroma_scale={chroma} != 2; do not hardcode 768/3"
        )
    config = replace(
        base,
        joint_score_raster_batch=int(updated["joint_score_raster_batch"]),
        chroma_scale=chroma,
    )
    assert_score_config(config, chroma_scale=chroma)
    experiment = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=config,
    )
    return experiment, chosen


def _projection_from_experiment(experiment) -> dict[str, Any]:
    return {
        "right": experiment.camera_right.detach().cpu().numpy().astype(np.float64),
        "down": experiment.camera_down.detach().cpu().numpy().astype(np.float64),
        "up": experiment.camera_up.detach().cpu().numpy().astype(np.float64),
        "forward": experiment.camera_forward.detach().cpu().numpy().astype(np.float64),
        "offset": experiment.camera_offset.detach().cpu().numpy().astype(np.float64),
        "pxPerWorld": experiment.px_per_world.detach().cpu().numpy().astype(np.float64),
    }


def _apply_projection(experiment, camera: Mapping[str, Any]) -> None:
    import torch

    device = experiment.device
    experiment.camera_right = torch.as_tensor(
        np.asarray(camera["right"], dtype=np.float64), dtype=torch.float32, device=device
    )
    experiment.camera_down = torch.as_tensor(
        np.asarray(camera["down"], dtype=np.float64), dtype=torch.float32, device=device
    )
    experiment.camera_up = torch.as_tensor(
        np.asarray(camera["up"], dtype=np.float64), dtype=torch.float32, device=device
    )
    experiment.camera_forward = torch.as_tensor(
        np.asarray(camera["forward"], dtype=np.float64), dtype=torch.float32, device=device
    )
    experiment.camera_offset = torch.as_tensor(
        np.asarray(camera["offset"], dtype=np.float64), dtype=torch.float32, device=device
    )


def _raster_rgb_uint8(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> np.ndarray:
    import torch

    bone, root_t, root_r = frozen_pose_tensors(experiment, poses)
    pos = int(frame_pos)
    with torch.no_grad():
        rgb, _alpha, _depth = experiment.exact_triangle_rgb(
            bone[pos : pos + 1],
            root_t[pos : pos + 1],
            root_r[pos : pos + 1],
            bone_mask=experiment.active_node_mask,
        )
    return np.rint(rgb[0].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0).astype(np.uint8)


def write_multi_angle(
    *,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    dest: Path,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    dest = assert_ragdoll_write_path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    prefix = int(config.get("idle_prefix_frames") or 0)
    suffix = int(config.get("idle_suffix_frames") or 0)
    frames = [int(frame) for frame in experiment.frame_indices]
    positions = vision_check_frame_positions(len(frames), prefix, suffix)
    sprites = [Path(str(path)) for path in payload.get("targetPaths") or []]
    pivot = experiment.root_pivot.detach().cpu().numpy().astype(np.float64).reshape(3)
    seed = _projection_from_experiment(experiment)
    stills: dict[str, dict[str, str]] = {}
    orbit_images: list[Any] = []
    mid_pos = positions[len(positions) // 2] if positions else 0
    try:
        for spec in VISION_CHECK_FIXED_CAMERAS:
            camera = orbit_projection(
                right=seed["right"],
                down=seed["down"],
                offset=seed["offset"],
                px_per_world=seed["pxPerWorld"],
                pivot=pivot,
                yaw_deg=float(spec["yawDeg"]),
                pitch_deg=float(spec["pitchDeg"]),
            )
            _apply_projection(experiment, camera)
            stills[str(spec["id"])] = {}
            for position in positions:
                frame = frames[int(position)]
                image = _raster_rgb_uint8(experiment, poses, int(position))
                path = dest / f"f{int(frame):02d}_{spec['id']}.png"
                Image.fromarray(image, "RGB").save(path, format="PNG", compress_level=0)
                stills[str(spec["id"])][f"{int(frame):02d}"] = str(path).replace("\\", "/")
        panel_w = int(experiment.config.resolution[0])
        panel_h = int(experiment.config.resolution[1])
        header = 22
        strips: list[Any] = []
        for position in positions:
            frame = frames[int(position)]
            canvas = Image.new(
                "RGB",
                (panel_w * (1 + len(VISION_CHECK_FIXED_CAMERAS)), header + panel_h),
                (12, 12, 16),
            )
            draw = ImageDraw.Draw(canvas)
            if int(position) < len(sprites) and sprites[int(position)].is_file():
                with Image.open(sprites[int(position)]) as sprite:
                    canvas.paste(sprite.convert("RGB").resize((panel_w, panel_h)), (0, header))
            draw.text((8, 4), f"sprite f{int(frame):02d}", fill=(230, 230, 235))
            for col, spec in enumerate(VISION_CHECK_FIXED_CAMERAS, start=1):
                x0 = col * panel_w
                draw.text((x0 + 8, 4), str(spec["id"]), fill=(230, 230, 235))
                with Image.open(dest / f"f{int(frame):02d}_{spec['id']}.png") as panel:
                    canvas.paste(panel.convert("RGB"), (x0, header))
            strip = dest / f"strip_f{int(frame):02d}.png"
            canvas.save(strip, format="PNG", compress_level=0)
            strips.append(str(strip).replace("\\", "/"))
        for yaw in VISION_CHECK_ORBIT_YAW_DEG:
            camera = orbit_projection(
                right=seed["right"],
                down=seed["down"],
                offset=seed["offset"],
                px_per_world=seed["pxPerWorld"],
                pivot=pivot,
                yaw_deg=float(yaw),
                pitch_deg=0.0,
            )
            _apply_projection(experiment, camera)
            orbit_images.append(Image.fromarray(_raster_rgb_uint8(experiment, poses, int(mid_pos)), "RGB"))
    finally:
        _apply_projection(experiment, seed)
    orbit_gif = dest / "orbit.gif"
    if orbit_images:
        orbit_images[0].save(
            orbit_gif,
            save_all=True,
            append_images=orbit_images[1:],
            duration=int(PREVIEW_GIF_FRAME_MS),
            loop=0,
            optimize=False,
        )
    report = {
        "stills": stills,
        "strips": strips,
        "orbitGif": str(orbit_gif).replace("\\", "/"),
        "questions": [
            "loop seam",
            "melt/ribbons (top/rear stills)",
            "card-flat cheats",
            "clamp mismatch",
        ],
        "proof": "generated-artifact; occupancy leftover stays profile-only",
    }
    (dest / "vision_check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def compose_three_column(
    *,
    fused_rgb_dir: Path,
    ragdoll_rgb_dir: Path,
    occupancy_preview_dir: Path,
    dest: Path,
    frames: Sequence[int],
) -> Path:
    from PIL import Image, ImageDraw

    dest = assert_ragdoll_write_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images: list[Any] = []
    for frame in frames:
        fused = Image.open(fused_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        ragdoll = Image.open(ragdoll_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        occ_path = occupancy_preview_dir / f"preview_{int(frame):02d}.png"
        occupancy_src = Image.open(occ_path).convert("RGB")
        panel_w, panel_h = fused.size
        occ_w = occupancy_src.size[0] // 3
        occ_h = occupancy_src.size[1] - 18
        occupancy = occupancy_src.crop((occ_w * 2, 18, occ_w * 3, 18 + occ_h)).resize((panel_w, panel_h))
        header = 22
        canvas = Image.new("RGB", (panel_w * 3, header + panel_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "fused-push", fill=(230, 230, 235))
        draw.text((panel_w + 8, 4), "ragdoll", fill=(230, 230, 235))
        draw.text((panel_w * 2 + 8, 4), "occupancy", fill=(230, 230, 235))
        canvas.paste(fused, (0, header))
        canvas.paste(ragdoll, (panel_w, header))
        canvas.paste(occupancy, (panel_w * 2, header))
        images.append(canvas)
        fused.close()
        ragdoll.close()
        occupancy_src.close()
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return dest


def write_payload(
    *,
    fused: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    score,
    residual: Mapping[str, Any],
    plant,
    plant_config: RagdollPlantConfig,
    stats: Mapping[str, Any],
    raster_budget: Mapping[str, Any],
    dest_dir: Path,
    clip: str,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    dest_dir = assert_ragdoll_write_path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "solver": SOLVER_ID,
        "poseUnits": "degrees",
        "poses": {str(int(frame)): poses[int(frame)] for frame in poses},
        "frameIndices": [int(frame) for frame in fused["frameIndices"]],
        "config": dict(fused["config"]),
        "cameraFitPath": fused["cameraFitPath"],
        "targetPaths": fused.get("targetPaths"),
        "initialization": fused.get("initialization"),
        "skinnedBones": fused.get("skinnedBones"),
        "searchBones": fused.get("searchBones"),
        "clipObjectiveMean": float(score.clip_objective),
        "scoreMean": float(score.score_mean),
        "imageMean": [float(value) for value in np.asarray(score.image_mean).tolist()],
        "collisionError": [float(value) for value in np.asarray(score.collision).tolist()],
        "temporalPenalty": float(score.temporal),
        "idleResidual": dict(residual),
        "plant": plant_constants(plant, plant_config),
        "search": dict(stats),
        "rasterBudget": dict(raster_budget),
        "aborted": bool(stats.get("aborted")),
        "clip": clip,
        "notPosePipelineCompliant": True,
        "experimentLaneOnly": True,
        "currentCascadeKeep": False,
        "humanGate": [
            "loop seam",
            "melt/ribbons (top/rear stills)",
            "card-flat cheats",
            "clamp mismatch",
        ],
        "proof": "generated-artifact; not pose-pipeline compliant; experiment lane only",
        "writtenAt": _utc_now(),
        **dict(extra),
    }
    persist_gpu_clip_result(payload, dest_dir)
    (dest_dir / "EXPERIMENT.md").write_text(EXPERIMENT_NOTE, encoding="utf-8")
    return payload


def run_clip(
    clip: str,
    *,
    unit: str,
    mesh: Path,
    plant_config: RagdollPlantConfig,
    write_vision: bool = True,
    write_compare: bool = True,
) -> dict[str, Any]:
    assert_not_idle_search_clip(clip)
    dest = output_dir(unit, clip)
    fused_path = fused_dir(unit, clip) / "gpu_clip_result.presmooth.json"
    fused = load_clip_result(fused_path)
    groups = clip_def_groups(clip)
    lock_suffix = bool(idle_end_required(groups)) and int(fused["config"].get("idle_suffix_frames") or 0) > 0
    if death_skips_idle_end(groups) and lock_suffix:
        raise RuntimeError(f"{clip} is death but lock_suffix is set")
    experiment, budget = build_rescore_experiment(fused, mesh, unit=unit)
    plant = plant_from_experiment(experiment, config=plant_config)
    source, bands = idle_and_bands_from_payload(plant, fused, lock_suffix=lock_suffix)
    started = time.perf_counter()
    picked, physics = consolidate_fused_clip(plant, source, bands, config=plant_config)
    fused_score = score_trajectory_gpu(experiment, plant, source)
    score = score_trajectory_gpu(experiment, plant, picked)
    elapsed = time.perf_counter() - started
    stats = {
        "aborted": False,
        "abortReason": "",
        "mode": "fused_post_pass",
        **dict(physics),
    }

    residual = boundary_report(plant, picked, bands)
    poses = poses_from_trajectory(plant, picked)
    payload = write_payload(
        fused=fused,
        poses=poses,
        score=score,
        residual=residual,
        plant=plant,
        plant_config=plant_config,
        stats=stats,
        raster_budget=budget,
        dest_dir=dest,
        clip=clip,
        extra={
            "elapsedSec": float(elapsed),
            "strainMax": strain_of_clip(plant, picked),
            "clampCount": int(np.sum(picked.clamp_counts)),
            "lockSuffix": bool(lock_suffix),
            "defGroups": list(groups),
            "unit": unit,
            "srcGlb": str(mesh).replace("\\", "/"),
            "seed": "fused_presmooth",
            "role": "fused_post_pass",
            "fusedObjective": float(fused_score.clip_objective),
            "fusedPresmoothPath": str(fused_path).replace("\\", "/"),
            "physics": dict(physics),
        },
    )
    preview = raster_tweak_preview(payload=payload, mesh_glb=mesh, output_dir=dest)
    vision: dict[str, Any] = {}
    compare = None
    if write_vision:
        vision = write_multi_angle(
            experiment=experiment, payload=payload, poses=poses, dest=dest / "vision_check"
        )
    if write_compare:
        compare = compose_three_column(
            fused_rgb_dir=fused_dir(unit, clip) / "solved_rgb",
            ragdoll_rgb_dir=dest / "solved_rgb",
            occupancy_preview_dir=dest / "preview",
            dest=dest / "fused_ragdoll_occupancy.gif",
            frames=tuple(int(frame) for frame in payload["frameIndices"]),
        )
    summary = {
        "unit": unit,
        "clip": clip,
        "role": "fused_post_pass",
        "outputDir": str(dest).replace("\\", "/"),
        "clipObjectiveMean": float(score.clip_objective),
        "scoreMean": float(score.score_mean),
        "fusedObjective": float(fused_score.clip_objective),
        "motionKeepFrac": physics["keepFrac"],
        "aborted": False,
        "idleResidual": residual,
        "previewGif": preview.get("previewGif"),
        "orbitGif": vision.get("orbitGif"),
        "compareGif": None if compare is None else str(compare).replace("\\", "/"),
        "proof": "generated-artifact; not pose-pipeline compliant; experiment lane only",
    }
    (dest / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    del experiment
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return summary


def run_presmooth_parity(mesh: Path) -> float:
    fused = load_clip_result(fused_dir("h3_goblin", WALK_CLIP) / "gpu_clip_result.presmooth.json")
    experiment, _budget = build_rescore_experiment(fused, mesh, unit="h3_goblin")
    try:
        mean = assert_presmooth_parity(experiment, fused)
    finally:
        del experiment
        gc.collect()
    return float(mean)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_goblin", choices=sorted(UNIT_MESHES))
    parser.add_argument("--clips", default=WALK_CLIP)
    parser.add_argument("--mesh", default="")
    return parser.parse_args()


def main() -> int:
    if "run_ragdoll_inertia_goblin.py" not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    args = parse_args()
    unit = str(args.unit)
    mesh = Path(args.mesh).resolve() if str(args.mesh) else UNIT_MESHES[unit]
    mesh = mesh.resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"{unit} mesh missing: {mesh}")
    clips = tuple(item.strip() for item in str(args.clips).split(",") if item.strip())
    plant_config = RagdollPlantConfig()
    plant_config.validate()
    summaries: list[dict[str, Any]] = []
    with cascade_batch_lock(REPO_ROOT):
        parity = None
        if unit == "h3_goblin":
            parity = run_presmooth_parity(mesh)
            print(f"presmooth adapter score={parity:.7f}", flush=True)
        else:
            print(f"skip goblin presmooth pin for {unit}", flush=True)
        for clip in clips:
            summaries.append(
                run_clip(
                    clip,
                    unit=unit,
                    mesh=mesh,
                    plant_config=plant_config,
                )
            )
    print(json.dumps({"unit": unit, "presmoothScore": parity, "clips": summaries}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
