"""Render sprite | selected | max-chroma yaw | antipode for profile chroma AB."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from gpu_profile_camera_initializer import (
    ProfileCameraInitConfig,
    _bind_vertices,
    _camera_candidate_basis,
    _fit_scale_and_offset,
    _mask_bounds,
    _set_backend_camera,
    _unit,
)
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


def _render_yaw(
    *,
    backend: GpuCascadeExperiment,
    vertices: np.ndarray,
    seed_right,
    seed_down,
    seed_forward,
    seed_px,
    orientation_bounds: dict,
    yaw_deg: float,
    roll_deg: float,
    fit_margin: float,
    predicted_alpha_threshold: float,
    world_up,
) -> Image.Image:
    right, down, forward = _camera_candidate_basis(
        seed_right,
        seed_down,
        seed_forward,
        yaw_deg=float(yaw_deg),
        roll_deg=float(roll_deg),
        mode="upright_turntable",
        world_up_axis=world_up,
    )
    px, offset = _fit_scale_and_offset(
        vertices,
        orientation_bounds,
        right,
        down,
        seed_px,
        fit_margin,
    )
    _set_backend_camera(
        backend,
        right=right,
        down=down,
        forward=forward,
        offset=offset,
        px_per_world=px,
    )
    zero_bones = torch.zeros(
        (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
    )
    zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
    with torch.no_grad():
        alpha, _ = backend._exact_triangle_raster(
            zero_bones,
            zero_root,
            zero_root,
            bone_mask=backend.active_node_mask,
        )
    mask = alpha[0].detach().cpu().numpy() > float(predicted_alpha_threshold)
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
        pred_rgb, _, _ = backend.exact_triangle_rgb(
            zero_bones,
            zero_root,
            zero_root,
            bone_mask=backend.active_node_mask,
        )
        alpha, _ = backend._exact_triangle_raster(
            zero_bones,
            zero_root,
            zero_root,
            bone_mask=backend.active_node_mask,
        )
    rgb = (pred_rgb[0].detach().cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
    mask = alpha[0].detach().cpu().numpy() > float(predicted_alpha_threshold)
    canvas = np.zeros_like(rgb)
    canvas[mask] = rgb[mask]
    return Image.fromarray(canvas, "RGB")


def _sprite_panel(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as sprite:
        rgba = sprite.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (24, 24, 24))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg.resize(size, Image.Resampling.NEAREST)


def build_unit(sid: str, mesh: Path, pilot: Path) -> Path:
    sprites = pilot / "frames_def12_nn_idle_shadow_culled"
    seed = pilot / "roc_sprite_camera_fit.json"
    scan = json.loads((pilot / "_profile_chroma_ab/yaw_roll0_chroma_scan.json").read_text(encoding="utf-8"))
    selected = scan["selected"]
    antipode = scan["antipode"]
    max_chroma = max(scan["rows"], key=lambda r: float(r["ch"]))
    cfg = ProfileCameraInitConfig()
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
        panels_meta = [
            ("sprite", None),
            (
                f"selected yaw={selected['yaw']:.0f} ch={selected['ch']:.3f}",
                (selected["yaw"], 0.0),
            ),
            (
                f"maxChroma yaw={max_chroma['yaw']:.0f} ch={max_chroma['ch']:.3f}",
                (max_chroma["yaw"], 0.0),
            ),
            (
                f"antipode yaw={antipode['yaw']:.0f} ch={antipode['ch']:.3f}",
                (antipode["yaw"], 0.0),
            ),
        ]
        rendered = []
        size = None
        for title, yaw_roll in panels_meta:
            if yaw_roll is None:
                continue
            img = _render_yaw(
                backend=backend,
                vertices=vertices,
                seed_right=seed_right,
                seed_down=seed_down,
                seed_forward=seed_forward,
                seed_px=seed_px,
                orientation_bounds=orientation_bounds,
                yaw_deg=yaw_roll[0],
                roll_deg=yaw_roll[1],
                fit_margin=cfg.fit_margin,
                predicted_alpha_threshold=cfg.predicted_alpha_threshold,
                world_up=world_up,
            )
            if size is None:
                size = img.size
            rendered.append((title, img))
        assert size is not None
        sprite = _sprite_panel(sprites / "00.png", size)
        all_panels = [("idle sprite f00", sprite), *rendered]
        scale = 4
        panel_w = size[0] * scale
        panel_h = size[1] * scale + 40
        canvas = Image.new("RGB", (panel_w * len(all_panels), panel_h), (18, 18, 18))
        draw = ImageDraw.Draw(canvas)
        for index, (title, img) in enumerate(all_panels):
            x = index * panel_w
            draw.text((x + 6, 10), f"{sid}: {title}", fill=(240, 240, 240))
            canvas.paste(
                img.resize((size[0] * scale, size[1] * scale), Image.Resampling.NEAREST),
                (x, 40),
            )
        out = pilot / "_profile_chroma_ab/compare_yaw_strip.png"
        canvas.save(out)
        print("wrote", out)
        return out
    finally:
        backend.release_cuda()


def main() -> None:
    build_unit(
        "h3_gargoyle",
        ROOT / "artifacts/meshy_downloads/h3_gargoyle_smartrigged.glb",
        ROOT / "artifacts/pose_picker_runs/h3_gargoyle/idle",
    )
    build_unit(
        "h3_pikeman",
        ROOT / "artifacts/meshy_downloads/h3_pikeman_smartrigged.glb",
        ROOT / "artifacts/pose_picker_runs/h3_pikeman/idle",
    )


if __name__ == "__main__":
    main()
