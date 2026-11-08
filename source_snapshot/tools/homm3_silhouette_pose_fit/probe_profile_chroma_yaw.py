"""A/B profile-init yaw with/without painted albedo scoring.

Writes per-unit baseline (chroma_weight=0) vs chroma (default weight) under
artifacts/pose_picker_runs/<sid>/idle/_profile_chroma_ab/ and a side-by-side
RGB compare sheet for human gate.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from gpu_profile_camera_initializer import (
    PROFILE_CHROMA_WEIGHT,
    PROFILE_FACING_WEIGHT,
    ProfileCameraInitConfig,
    initialize_profile_camera,
)
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
UNITS = (
    {
        "sid": "h3_gargoyle",
        "mesh": ROOT / "artifacts/meshy_downloads/h3_gargoyle_smartrigged.glb",
        "pilot": ROOT / "artifacts/pose_picker_runs/h3_gargoyle/idle",
    },
    {
        "sid": "h3_pikeman",
        "mesh": ROOT / "artifacts/meshy_downloads/h3_pikeman_smartrigged.glb",
        "pilot": ROOT / "artifacts/pose_picker_runs/h3_pikeman/idle",
    },
)


def _seed_camera(pilot: Path) -> Path:
    for rel in (
        "roc_sprite_camera_fit.json",
        "gpu_cascade_delivery/initialization/profile_camera_fit.json",
    ):
        path = pilot / rel
        if path.is_file():
            return path
    raise FileNotFoundError(f"no seed camera under {pilot}")


def _sprite_dir(pilot: Path) -> Path:
    for name in (
        "frames_def12_nn_idle_shadow_culled",
        "frames_def12_nn_idle",
    ):
        path = pilot / name
        if path.is_dir() and (path / "00.png").is_file():
            return path
    raise FileNotFoundError(f"no idle sprite frames under {pilot}")


def _run_variant(
    *,
    sid: str,
    mesh: Path,
    seed: Path,
    sprites: Path,
    out_dir: Path,
    chroma_weight: float,
    label: str,
) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = initialize_profile_camera(
        src_glb=mesh,
        seed_camera_fit=seed,
        target_frame_dir=sprites,
        frame_index=0,
        output_dir=out_dir,
        config=ProfileCameraInitConfig(
            facing_weight=PROFILE_FACING_WEIGHT,
            chroma_weight=float(chroma_weight),
            top_k=12,
        ),
        progress=True,
    )
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    best = report["best"]
    print(
        f"[{sid}/{label}] yaw={best['yawDeg']:.1f} roll={best['rollDeg']:.1f} "
        f"oriIoU={float(best.get('orientationIoU', best['iou'])):.4f} "
        f"facing={float(best.get('facingScore', 0)):.3f} "
        f"chroma={float(best.get('chromaQuality', 0)):.3f} "
        f"oriScore={float(best.get('orientationScore', best['score'])):.4f}",
        flush=True,
    )
    return report


def _render_best_rgb(report: dict, mesh: Path, sprites: Path) -> Image.Image:
    import torch

    best = report["best"]
    frame = sprites / f"{int(report['frameIndex']):02d}.png"
    config = report["config"]
    resolution = tuple(int(v) for v in config["resolution"])
    backend = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=report["cameraFitPath"],
        target_frame_dir=sprites,
        frame_indices=(int(report["frameIndex"]),),
        config=GpuCascadeConfig(
            device="cuda",
            resolution=resolution,
            alpha_threshold=int(config["alpha_threshold"]),
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
        mask = alpha[0].detach().cpu().numpy() > float(config["predicted_alpha_threshold"])
        canvas = np.zeros_like(rgb)
        canvas[mask] = rgb[mask]
        mesh_img = Image.fromarray(canvas, "RGB")
        with Image.open(frame) as sprite:
            sprite_img = sprite.convert("RGBA")
            bg = Image.new("RGB", sprite_img.size, (24, 24, 24))
            bg.paste(sprite_img, mask=sprite_img.split()[-1])
            sprite_rgb = bg.resize(mesh_img.size, Image.Resampling.NEAREST)
        return mesh_img, sprite_rgb, best
    finally:
        backend.release_cuda()


def _compose_compare(
    *,
    sid: str,
    baseline: dict,
    chroma: dict,
    mesh: Path,
    sprites: Path,
    out_path: Path,
) -> None:
    base_mesh, sprite, base_best = _render_best_rgb(baseline, mesh, sprites)
    chroma_mesh, _, chroma_best = _render_best_rgb(chroma, mesh, sprites)
    scale = 4
    w, h = base_mesh.size
    panel_w, panel_h = w * scale, h * scale + 36
    canvas = Image.new("RGB", (panel_w * 3, panel_h), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    panels = [
        (sprite.resize((w * scale, h * scale), Image.Resampling.NEAREST), "idle sprite f00"),
        (
            base_mesh.resize((w * scale, h * scale), Image.Resampling.NEAREST),
            f"baseline chroma=0  yaw={base_best['yawDeg']:.0f} "
            f"IoU={float(base_best.get('orientationIoU', base_best['iou'])):.3f} "
            f"ch={float(base_best.get('chromaQuality', 0)):.3f}",
        ),
        (
            chroma_mesh.resize((w * scale, h * scale), Image.Resampling.NEAREST),
            f"chroma w={PROFILE_CHROMA_WEIGHT}  yaw={chroma_best['yawDeg']:.0f} "
            f"IoU={float(chroma_best.get('orientationIoU', chroma_best['iou'])):.3f} "
            f"ch={float(chroma_best.get('chromaQuality', 0)):.3f}",
        ),
    ]
    for index, (panel, title) in enumerate(panels):
        x = index * panel_w
        draw.text((x + 6, 8), f"{sid}: {title}", fill=(240, 240, 240))
        canvas.paste(panel, (x, 36))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def _antipode_note(report: dict) -> dict:
    best = report["best"]
    byaw = float(best["yawDeg"])
    target = ((byaw + 180.0 + 180.0) % 360.0) - 180.0
    cands = list(report.get("candidates", []))
    # candidates are top-k only; also scan is enough for note
    nearest = None
    nearest_gap = 999.0
    for cand in cands:
        yaw = float(cand["yawDeg"])
        gap = abs(((yaw - target + 180.0) % 360.0) - 180.0)
        if gap < nearest_gap:
            nearest_gap = gap
            nearest = cand
    return {
        "bestYawDeg": byaw,
        "antipodeTargetDeg": target,
        "nearestTopK": None
        if nearest is None
        else {
            "yawDeg": nearest.get("yawDeg"),
            "rollDeg": nearest.get("rollDeg"),
            "score": nearest.get("score"),
            "silhouetteScore": nearest.get("silhouetteScore"),
            "chromaQuality": nearest.get("chromaQuality"),
            "facingScore": nearest.get("facingScore"),
            "iou": nearest.get("iou"),
            "yawGapDeg": nearest_gap,
        },
    }


def main() -> None:
    summary = []
    for unit in UNITS:
        sid = unit["sid"]
        mesh = Path(unit["mesh"])
        pilot = Path(unit["pilot"])
        seed = _seed_camera(pilot)
        sprites = _sprite_dir(pilot)
        root = pilot / "_profile_chroma_ab"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)

        baseline = _run_variant(
            sid=sid,
            mesh=mesh,
            seed=seed,
            sprites=sprites,
            out_dir=root / "baseline_no_chroma",
            chroma_weight=0.0,
            label="baseline",
        )
        chroma = _run_variant(
            sid=sid,
            mesh=mesh,
            seed=seed,
            sprites=sprites,
            out_dir=root / "with_chroma",
            chroma_weight=PROFILE_CHROMA_WEIGHT,
            label="chroma",
        )
        compare_path = root / "compare_rgb.png"
        _compose_compare(
            sid=sid,
            baseline=baseline,
            chroma=chroma,
            mesh=mesh,
            sprites=sprites,
            out_path=compare_path,
        )
        row = {
            "sid": sid,
            "mesh": str(mesh),
            "sprites": str(sprites),
            "seedCamera": str(seed),
            "baseline": {
                "yawDeg": baseline["best"]["yawDeg"],
                "rollDeg": baseline["best"]["rollDeg"],
                "orientationIoU": baseline["best"].get("orientationIoU"),
                "facingScore": baseline["best"].get("facingScore"),
                "chromaQuality": baseline["best"].get("chromaQuality"),
                "orientationScore": baseline["best"].get("orientationScore"),
                "antipode": _antipode_note(baseline),
            },
            "chroma": {
                "yawDeg": chroma["best"]["yawDeg"],
                "rollDeg": chroma["best"]["rollDeg"],
                "orientationIoU": chroma["best"].get("orientationIoU"),
                "facingScore": chroma["best"].get("facingScore"),
                "chromaQuality": chroma["best"].get("chromaQuality"),
                "orientationScore": chroma["best"].get("orientationScore"),
                "antipode": _antipode_note(chroma),
            },
            "yawChanged": float(baseline["best"]["yawDeg"]) != float(chroma["best"]["yawDeg"])
            or float(baseline["best"]["rollDeg"]) != float(chroma["best"]["rollDeg"]),
            "compareRgb": str(compare_path),
            "baselinePreview": str(root / "baseline_no_chroma" / "profile_camera_initialization.png"),
            "chromaPreview": str(root / "with_chroma" / "profile_camera_initialization.png"),
        }
        summary.append(row)
        (root / "ab_summary.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")

    out = ROOT / "artifacts/pose_picker_runs/_profile_chroma_ab_summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
