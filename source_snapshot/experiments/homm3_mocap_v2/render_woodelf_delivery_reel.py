#!/usr/bin/env python3
"""Render the current wood-elf delivery clips into one diagnostic GIF.

The inputs are the ten immutable per-clip GLBs from the generated delivery
directory. Their serialized glTF animations are replayed with the repository's
own skeleton and skinning code, then rasterized through the existing CUDA
preview renderer under one union camera. This is a visual review artifact only;
it does not rewrite, repair, or accept any GLB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
TOOL_DIR = ROOT / "tools/homm3_silhouette_pose_fit"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from eagle_glb import gltf_world_matrices  # noqa: E402
from glb_skeleton import load_bind_skeleton  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from mesh_preview import skin_vertices  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from verify_calibrated_export import _serialized_local_rotations  # noqa: E402

DEFAULT_UNIT = ROOT / "artifacts/homm3_mocap_v2/remaining_idle0_ingame_v1/units/h3_wood_elf"
DEFAULT_OUTPUT = ROOT / "artifacts/homm3_mocap_v2/woodelf_delivery_reel_v1"
CLIP_ORDER = (
    "Unit_Idle",
    "Unit_MoveStart",
    "Unit_Move",
    "Unit_MoveEnd",
    "Unit_Mouseover",
    "Unit_Hitted",
    "Unit_Defence",
    "Unit_AttackFront",
    "Unit_ShootFront",
    "Unit_Death",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _camera(points: np.ndarray, resolution: int) -> dict[str, object]:
    """Build one conservative Y-up front camera for every posed frame."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
    forward = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    x = points @ right
    y = points @ down
    z = points @ forward
    span = max(float(np.ptp(x)), float(np.ptp(y)), 1e-6) * 1.14
    scale = (resolution - 1) / span
    camera = {
        "right": right.tolist(),
        "down": down.tolist(),
        "forward": forward.tolist(),
        "scale": float(scale),
        "offset": [
            float((resolution - 1) / 2 - scale * (x.min() + x.max()) / 2),
            float((resolution - 1) / 2 - scale * (y.min() + y.max()) / 2),
        ],
        "depth_center": float((z.min() + z.max()) / 2),
        "depth_span": float(max(np.ptp(z) * 1.35, 1e-4)),
        "resolution": int(resolution),
        "policy": "shared_union_y_up_front_camera",
    }
    return camera


def _durations(frame_count: int, fps: float) -> list[int]:
    """Distribute centisecond GIF rounding without changing source cadence."""
    frame_ms = 1000.0 / float(fps)
    boundaries = np.rint(np.arange(frame_count + 1) * frame_ms / 10.0).astype(int) * 10
    return np.maximum(10, np.diff(boundaries)).astype(int).tolist()


def _compose_frames(
    rendered: np.ndarray,
    labels: list[str],
    resolution: int,
) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for pixels, label in zip(rendered, labels):
        canvas = Image.new("RGB", (resolution, resolution + 34), (12, 15, 20))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 6), label, fill=(238, 240, 244))
        draw.text((8, 19), "generated delivery replay", fill=(155, 166, 178))
        image = Image.fromarray(np.uint8(np.clip(pixels, 0.0, 1.0) * 255.0), mode="RGB")
        canvas.paste(image, (0, 34))
        frames.append(canvas)
    return frames


def _contact(frames: list[Image.Image], output: Path) -> None:
    if not frames:
        raise ValueError("cannot build a contact sheet from no frames")
    selected = np.linspace(0, len(frames) - 1, min(10, len(frames)), dtype=int).tolist()
    cell_w, cell_h = frames[0].size
    sheet = Image.new("RGB", (cell_w * 5, cell_h * 2), (8, 10, 14))
    for slot, index in enumerate(selected):
        sheet.paste(frames[index], ((slot % 5) * cell_w, (slot // 5) * cell_h))
    sheet.save(output / "wood_elf_animation_reel_contact.png")


def run(*, unit_dir: Path, output: Path, resolution: int, overwrite: bool) -> dict[str, object]:
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.is_file():
            child.unlink()

    paths = [unit_dir / f"{name}.glb" for name in CLIP_ORDER]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing delivery clips: " + ", ".join(missing))

    base = load_bind_skeleton(paths[0])
    clips: list[dict[str, object]] = []
    posed_parts: list[np.ndarray] = []
    labels: list[str] = []
    for path in paths:
        skeleton = load_bind_skeleton(path)
        if skeleton.names != base.names or skeleton.parents != base.parents:
            raise ValueError(f"{path.name}: skeleton identity differs from Unit_Idle")
        if not np.array_equal(skeleton.triangles, base.triangles) or not np.allclose(
            skeleton.vertices, base.vertices, atol=0.0, rtol=0.0
        ):
            raise ValueError(f"{path.name}: mesh geometry differs from Unit_Idle")
        times, rotations, translations, animation_meta = _serialized_local_rotations(
            path, allow_root_motion=True
        )
        clip_worlds = np.stack(
            [
                gltf_world_matrices(
                    local_rotation=rotations[index],
                    local_translation=translations[index],
                    parents=np.asarray(base.parents, dtype=np.int64),
                )
                for index in range(len(times))
            ]
        )
        clip_meshes = np.stack([skin_vertices(base, worlds) for worlds in clip_worlds])
        posed_parts.append(clip_meshes)
        labels.extend([f"{path.stem.removeprefix('Unit_')}  f{index:02d}" for index in range(len(times))])
        clips.append(
            {
                "name": path.stem,
                "path": str(path.resolve()).replace("\\", "/"),
                "sha256": _sha256(path),
                "frames": int(len(times)),
                "durationSeconds": float(times[-1] if len(times) else 0.0),
                "animation": animation_meta,
            }
        )

    posed = np.concatenate(posed_parts, axis=0)
    camera = _camera(posed, resolution)

    import torch

    with cascade_batch_lock(ROOT), torch.no_grad():
        renderer = SkinImageRenderer(base.triangles, base.uvs, base.albedo, camera, resolution)
        rgb, alpha = renderer.render(torch.as_tensor(posed, device="cuda", dtype=torch.float32))
        rendered = (rgb * alpha + (1.0 - alpha) * 0.035).detach().cpu().numpy()

    frames = _compose_frames(rendered, labels, resolution)
    gif = output / "wood_elf_animation_reel.gif"
    durations = _durations(len(frames), 12.0)
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2)
    _contact(frames, output)
    report = {
        "schema": "homm3.wood-elf-delivery-reel.v1",
        "proof": "generated-artifact",
        "visualAcceptance": "unreviewed",
        "unit": "h3_wood_elf",
        "sourceDirectory": str(unit_dir.resolve()).replace("\\", "/"),
        "clipOrder": list(CLIP_ORDER),
        "fps": 12.0,
        "frameCount": len(frames),
        "resolution": int(resolution),
        "camera": camera,
        "clips": clips,
        "gif": str(gif.resolve()).replace("\\", "/"),
        "contactSheet": str((output / "wood_elf_animation_reel_contact.png").resolve()).replace("\\", "/"),
        "notes": [
            "Replayed serialized clip animations through the existing repository skinning and CUDA raster preview.",
            "No GLB was written or modified; this is not OE runtime or user-visible gameplay proof.",
        ],
    }
    (output / "reel_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-dir", type=Path, default=DEFAULT_UNIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resolution", type=int, default=384)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = run(
        unit_dir=args.unit_dir.resolve(),
        output=args.output.resolve(),
        resolution=int(args.resolution),
        overwrite=bool(args.overwrite),
    )
    print(json.dumps({"ok": True, "gif": report["gif"], "frames": report["frameCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
