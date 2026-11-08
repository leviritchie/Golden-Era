"""Scan roll=0 yaw grid for chroma vs silhouette; compare best vs antipode."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from gpu_profile_camera_initializer import (
    PROFILE_CHROMA_WEIGHT,
    PROFILE_FACING_WEIGHT,
    ProfileCameraInitConfig,
    _bind_vertices,
    _camera_candidate_basis,
    _character_ground_forward,
    _fit_scale_and_offset,
    _inclusive_grid,
    _load_target_rgb_tensor,
    _mask_bounds,
    _profile_bind_pose_chroma_quality,
    _profile_facing_score,
    _score_mask,
    _set_backend_camera,
    _silhouette_selection_score,
    _unit,
)
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
UNITS = [
    (
        "h3_gargoyle",
        ROOT / "artifacts/meshy_downloads/h3_gargoyle_smartrigged.glb",
        ROOT / "artifacts/pose_picker_runs/h3_gargoyle/idle",
    ),
    (
        "h3_pikeman",
        ROOT / "artifacts/meshy_downloads/h3_pikeman_smartrigged.glb",
        ROOT / "artifacts/pose_picker_runs/h3_pikeman/idle",
    ),
]


def scan(sid: str, mesh: Path, pilot: Path) -> None:
    sprites = pilot / "frames_def12_nn_idle_shadow_culled"
    seed = pilot / "roc_sprite_camera_fit.json"
    cfg = ProfileCameraInitConfig(
        chroma_weight=PROFILE_CHROMA_WEIGHT,
        facing_weight=PROFILE_FACING_WEIGHT,
    )
    backend = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=seed,
        target_frame_dir=sprites,
        frame_indices=(0,),
        config=GpuCascadeConfig(
            device="cuda",
            resolution=tuple(cfg.resolution),
            alpha_threshold=cfg.alpha_threshold,
            max_triangles_per_primitive=2048,
            samples_per_triangle=3,
            root_search_enabled=False,
            root_hypotheses=1,
            root_iterations=0,
            articulated_iterations=0,
            fine_iterations=0,
            optimize_root_translation=False,
            optimize_root_rotation=False,
            root_rotation_defer_camera_up=False,
            optimize_bones=False,
            exact_raster_enabled=True,
            collision_enabled=False,
            collision_weight=0.0,
            return_masks=True,
        ),
    )
    try:
        orientation_target = backend.target_masks[0].detach().cpu().numpy() > 0.5
        orientation_bounds = _mask_bounds(orientation_target)
        vertices = _bind_vertices(backend).detach().cpu().numpy()
        seed_right = backend.camera_right.detach().cpu().numpy()
        seed_down = backend.camera_down.detach().cpu().numpy()
        seed_forward = backend.camera_forward.detach().cpu().numpy()
        seed_px = backend.px_per_world.detach().cpu().numpy()
        world_up = _unit(np.asarray(cfg.world_up_axis, dtype=np.float32))
        character_forward = _character_ground_forward(backend.asset, world_up)
        target_rgb, target_alpha = _load_target_rgb_tensor(
            sprites / "00.png",
            cfg.resolution,
            device=backend.device,
        )
        zero_bones = torch.zeros(
            (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
        )
        zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
        rows: list[dict] = []
        for yaw in _inclusive_grid(cfg.yaw_min_deg, cfg.yaw_max_deg, cfg.yaw_step_deg):
            right, down, forward = _camera_candidate_basis(
                seed_right,
                seed_down,
                seed_forward,
                yaw_deg=float(yaw),
                roll_deg=0.0,
                mode=str(cfg.camera_basis_mode),
                world_up_axis=world_up,
            )
            px, offset = _fit_scale_and_offset(
                vertices,
                orientation_bounds,
                right,
                down,
                seed_px,
                cfg.fit_margin,
            )
            _set_backend_camera(
                backend,
                right=right,
                down=down,
                forward=forward,
                offset=offset,
                px_per_world=px,
            )
            with torch.no_grad():
                alpha, _ = backend._exact_triangle_raster(
                    zero_bones,
                    zero_root,
                    zero_root,
                    bone_mask=backend.active_node_mask,
                )
            mask = alpha[0].detach().cpu().numpy() > cfg.predicted_alpha_threshold
            ys, xs = np.where(mask)
            if len(xs):
                cx, cy = float(xs.mean()), float(ys.mean())
                offset = offset + np.asarray(
                    (
                        orientation_bounds["centerX"] - cx,
                        -(orientation_bounds["centerY"] - cy),
                    ),
                    dtype=np.float32,
                )
                _set_backend_camera(
                    backend,
                    right=right,
                    down=down,
                    forward=forward,
                    offset=offset,
                    px_per_world=px,
                )
                with torch.no_grad():
                    alpha, _ = backend._exact_triangle_raster(
                        zero_bones,
                        zero_root,
                        zero_root,
                        bone_mask=backend.active_node_mask,
                    )
                mask = alpha[0].detach().cpu().numpy() > cfg.predicted_alpha_threshold
            sil, diag = _score_mask(
                orientation_target,
                mask,
                target_bounds=orientation_bounds,
            )
            chroma = _profile_bind_pose_chroma_quality(
                backend,
                target_rgb=target_rgb,
                target_alpha=target_alpha,
                predicted_alpha_threshold=cfg.predicted_alpha_threshold,
            )
            facing = _profile_facing_score(character_forward, right)
            score, _ = _silhouette_selection_score(
                silhouette_score=sil,
                geometry_score=0.0,
                character_forward=character_forward,
                right=right,
                camera_basis_mode=cfg.camera_basis_mode,
                facing_weight=PROFILE_FACING_WEIGHT,
                chroma_quality=chroma["chromaQuality"],
                chroma_weight=PROFILE_CHROMA_WEIGHT,
            )
            rows.append(
                {
                    "yaw": float(yaw),
                    "sil": float(sil),
                    "iou": float(diag["iou"]),
                    "ch": float(chroma["chromaQuality"]),
                    "face": float(facing),
                    "score": float(score),
                }
            )
        rows.sort(key=lambda r: r["score"], reverse=True)
        by_ch = sorted(rows, key=lambda r: r["ch"], reverse=True)
        by_sil = sorted(rows, key=lambda r: r["sil"], reverse=True)
        print(f"\n==== {sid} characterForward={character_forward.tolist()} ====")
        print("top by composite+chroma:")
        for r in rows[:6]:
            print(
                f"  yaw={r['yaw']:6.1f} sil={r['sil']:.4f} iou={r['iou']:.3f} "
                f"ch={r['ch']:.3f} face={r['face']:.3f} score={r['score']:.4f}"
            )
        print("top by chroma alone:")
        for r in by_ch[:6]:
            print(
                f"  yaw={r['yaw']:6.1f} sil={r['sil']:.4f} iou={r['iou']:.3f} "
                f"ch={r['ch']:.3f} face={r['face']:.3f}"
            )
        print("top by silhouette alone:")
        for r in by_sil[:6]:
            print(
                f"  yaw={r['yaw']:6.1f} sil={r['sil']:.4f} iou={r['iou']:.3f} "
                f"ch={r['ch']:.3f} face={r['face']:.3f}"
            )
        ab_path = pilot / "_profile_chroma_ab/with_chroma/profile_camera_initialization.json"
        byaw = float(json.loads(ab_path.read_text(encoding="utf-8"))["best"]["yawDeg"])
        anti = ((byaw + 180.0 + 180.0) % 360.0) - 180.0

        def nearest(yaw: float) -> dict:
            return min(rows, key=lambda r: abs(((r["yaw"] - yaw + 180.0) % 360.0) - 180.0))

        b = nearest(byaw)
        a = nearest(anti)
        print(
            f"selected yaw~{byaw}: sil={b['sil']:.4f} ch={b['ch']:.3f} "
            f"face={b['face']:.3f} score={b['score']:.4f}"
        )
        print(
            f"antipode yaw~{anti}: sil={a['sil']:.4f} ch={a['ch']:.3f} "
            f"face={a['face']:.3f} score={a['score']:.4f}"
        )
        out = pilot / "_profile_chroma_ab/yaw_roll0_chroma_scan.json"
        out.write_text(
            json.dumps(
                {
                    "characterForward": [float(v) for v in character_forward],
                    "selectedYaw": byaw,
                    "antipodeYaw": anti,
                    "selected": b,
                    "antipode": a,
                    "rows": rows,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("wrote", out)
    finally:
        backend.release_cuda()


def main() -> None:
    for sid, mesh, pilot in UNITS:
        scan(sid, mesh, pilot)


if __name__ == "__main__":
    main()
