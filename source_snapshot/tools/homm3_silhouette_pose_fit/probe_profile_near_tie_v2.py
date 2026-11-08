"""Re-run profile init after near-tie chroma + weak facing; write RGB compares."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from gpu_profile_camera_initializer import (
    PROFILE_CHROMA_WEIGHT,
    PROFILE_FACING_WEIGHT,
    PROFILE_SILHOUETTE_NEAR_TIE,
    ProfileCameraInitConfig,
    initialize_profile_camera,
)
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
UNITS = (
    ("h3_gargoyle", ROOT / "artifacts/meshy_downloads/h3_gargoyle_smartrigged.glb"),
    ("h3_pikeman", ROOT / "artifacts/meshy_downloads/h3_pikeman_smartrigged.glb"),
)


def _render_camera(mesh: Path, camera_fit: Path, sprites: Path) -> Image.Image:
    cfg = ProfileCameraInitConfig()
    backend = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=camera_fit,
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
        zero_bones = torch.zeros(
            (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
        )
        zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
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
        mask = alpha[0].detach().cpu().numpy() > float(cfg.predicted_alpha_threshold)
        canvas = np.zeros_like(rgb)
        canvas[mask] = rgb[mask]
        return Image.fromarray(canvas, "RGB")
    finally:
        backend.release_cuda()


def main() -> None:
    summary = []
    for sid, mesh in UNITS:
        pilot = ROOT / f"artifacts/pose_picker_runs/{sid}/idle"
        sprites = pilot / "frames_def12_nn_idle_shadow_culled"
        seed = pilot / "roc_sprite_camera_fit.json"
        out = pilot / "_profile_chroma_ab/near_tie_v2"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        old_path = pilot / "_profile_chroma_ab/with_chroma/profile_camera_initialization.json"
        old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.is_file() else None
        result = initialize_profile_camera(
            src_glb=mesh,
            seed_camera_fit=seed,
            target_frame_dir=sprites,
            frame_index=0,
            output_dir=out,
            config=ProfileCameraInitConfig(top_k=12),
            progress=True,
        )
        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        best = report["best"]
        selection = best.get("selection", {})
        print(
            f"[{sid}] yaw={best['yawDeg']} roll={best['rollDeg']} "
            f"ch={best.get('chromaQuality')} face={best.get('facingScore')} "
            f"rule={selection.get('selectionRule')} near={selection.get('nearTieCount')}",
            flush=True,
        )
        with Image.open(sprites / "00.png") as sprite:
            rgba = sprite.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (24, 24, 24))
            bg.paste(rgba, mask=rgba.split()[-1])
        new_img = _render_camera(mesh, result.camera_fit_path, sprites)
        sprite_img = bg.resize(new_img.size, Image.Resampling.NEAREST)
        panels = [("idle sprite", sprite_img)]
        if old is not None:
            old_img = _render_camera(mesh, old["cameraFitPath"], sprites)
            panels.append(
                (
                    f"prev yaw={old['best']['yawDeg']:.0f} ch={float(old['best'].get('chromaQuality', 0)):.3f}",
                    old_img,
                )
            )
        panels.append(
            (
                f"near-tie yaw={best['yawDeg']:.0f} ch={float(best.get('chromaQuality', 0)):.3f} "
                f"rule={selection.get('selectionRule', '?')}",
                new_img,
            )
        )
        scale = 4
        w, h = new_img.size
        pw, ph = w * scale, h * scale + 44
        canvas = Image.new("RGB", (pw * len(panels), ph), (18, 18, 18))
        draw = ImageDraw.Draw(canvas)
        for index, (title, img) in enumerate(panels):
            x = index * pw
            draw.text((x + 6, 10), f"{sid}: {title}", fill=(240, 240, 240))
            canvas.paste(img.resize((w * scale, h * scale), Image.Resampling.NEAREST), (x, 44))
        compare = out / "compare_vs_prev.png"
        canvas.save(compare)
        row = {
            "sid": sid,
            "prevYaw": None if old is None else old["best"]["yawDeg"],
            "newYaw": best["yawDeg"],
            "newRoll": best["rollDeg"],
            "chromaQuality": best.get("chromaQuality"),
            "facingScore": best.get("facingScore"),
            "selection": selection,
            "facingWeight": PROFILE_FACING_WEIGHT,
            "chromaWeight": PROFILE_CHROMA_WEIGHT,
            "silhouetteNearTie": PROFILE_SILHOUETTE_NEAR_TIE,
            "compare": str(compare),
            "preview": str(out / "profile_camera_initialization.png"),
        }
        summary.append(row)
        (out / "summary.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    out_summary = ROOT / "artifacts/pose_picker_runs/_profile_near_tie_v2_summary.json"
    out_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("wrote", out_summary)


if __name__ == "__main__":
    main()
