"""Exact-triangle CUDA depth experiment and animation-solver bridge.

The bind-pose function remains a smoke test. ``solve_gpu_depth_animation`` is
the animation path: pose search is performed by the existing GPU clip solver,
then the accepted poses are rasterized as filled triangles with CUDA. Blender
is used only by the final preview export, never in the candidate loop.
"""
from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any, Sequence

import numpy as np
from PIL import Image, ImageDraw

from nvdiffrast_local import ensure_local_nvdiffrast
from roc_geometric_proxy import _world_matrices, load_asset


@dataclass
class GpuRasterRig:
    mesh_path: Path
    camera_fit: Path
    width: int
    height: int
    mesh_scale: float
    skin_level: int
    triangles: Any
    clip_vertices: Any
    ctx: Any
    torch: Any
    vertices: Any

    def summary(self) -> dict[str, Any]:
        return {
            "mesh": str(self.mesh_path),
            "camera_fit": str(self.camera_fit),
            "vertices": int(self.vertices.shape[0]),
            "triangles": int(self.triangles.shape[0]),
            "resolution": [self.width, self.height],
            "backend": "nvdiffrast RasterizeCudaContext",
            "pose": "bind pose (validation lane)",
        }


@dataclass
class RasterResult:
    manifest_path: Path
    contact_path: Path
    gif_path: Path
    alpha_dir: Path | None = None
    alpha_gif_path: Path | None = None

    def contact_sheet(self):
        return Image.open(self.contact_path)


@dataclass
class AnimationSolveResult:
    """Pose result plus exact CUDA depth and final Blender preview artifacts."""

    pose_result: dict[str, Any]
    depth_dir: Path
    depth_gif: Path
    blender_preview: dict[str, Any] | None
    gpu_preview: Path | None = None
    alpha_dir: Path | None = None
    alpha_gif_path: Path | None = None
    rgb_dir: Path | None = None
    rgb_gif_path: Path | None = None


def _project(vertices: Any, torch: Any, width: int, height: int, camera_fit: Path):
    """Project bind geometry with the same camera contract as the solver.

    The former bind smoke test auto-framed the mesh from its own XYZ bounds.
    That made its preview look plausible while having no relationship to the
    solver or Blender camera.  Keep this path on the serialized screen basis,
    pixel scale, and top-to-bottom offset used by ``GpuCascadeExperiment``.
    """
    from roc_gpu_cascade_experiment import _read_camera_fit

    camera = _read_camera_fit(camera_fit, (int(width), int(height)))
    xyz = vertices[:, :3]
    right = torch.as_tensor(camera["right"], dtype=torch.float32, device=vertices.device)
    down = torch.as_tensor(camera["down"], dtype=torch.float32, device=vertices.device)
    forward = torch.as_tensor(camera["forward"], dtype=torch.float32, device=vertices.device)
    px_per_world = torch.as_tensor(camera["pxPerWorld"], dtype=torch.float32, device=vertices.device)
    offset = torch.as_tensor(camera["offset"], dtype=torch.float32, device=vertices.device)
    screen_x = torch.matmul(xyz, right) * px_per_world[0] + offset[0]
    screen_y = torch.matmul(xyz, down) * px_per_world[1] + offset[1]
    depth = torch.matmul(xyz, forward)
    depth_min = depth.amin()
    depth_max = depth.amax()
    depth_span = torch.clamp(depth_max - depth_min, min=1e-6)
    z = (depth - depth_min) / depth_span
    clip_x = screen_x / max(width - 1, 1) * 2.0 - 1.0
    clip_y = 1.0 - screen_y / max(height - 1, 1) * 2.0
    ones = torch.ones_like(clip_x)
    return torch.stack((clip_x, clip_y, z * 2.0 - 1.0, ones), dim=1)


def prepare_gpu_raster_depth(*, mesh_path: Path, camera_fit: Path, width: int, height: int, mesh_scale: float, skin_level: int) -> GpuRasterRig:
    import torch

    ensure_local_nvdiffrast(required=True)
    import nvdiffrast.torch as dr

    if not torch.cuda.is_available():
        raise RuntimeError("GPU raster depth requires CUDA")
    if not mesh_path.is_file():
        raise FileNotFoundError(mesh_path)
    if not camera_fit.is_file():
        raise FileNotFoundError(camera_fit)
    asset = load_asset(mesh_path)
    worlds = _world_matrices(asset, None)
    verts: list[np.ndarray] = []
    triangles: list[np.ndarray] = []
    offset = 0
    for primitive in asset.primitives:
        if primitive.indices is None:
            raise ValueError(f"primitive has no triangle indices: node={primitive.node}")
        # The proxy's CPU skinning is used only once to establish the exact
        # bind geometry. Rasterization and depth are entirely CUDA-resident.
        from roc_geometric_proxy import _primitive_points
        points = _primitive_points(asset, primitive, worlds, skin_level) * float(mesh_scale)
        verts.append(np.c_[points, np.ones(len(points), dtype=np.float64)])
        triangles.append(np.asarray(primitive.indices, dtype=np.int64).reshape(-1, 3) + offset)
        offset += len(points)
    if not verts:
        raise ValueError("mesh contains no primitives")
    torch_vertices = torch.as_tensor(np.concatenate(verts), dtype=torch.float32, device="cuda")
    torch_triangles = torch.as_tensor(np.concatenate(triangles), dtype=torch.int32, device="cuda")
    return GpuRasterRig(mesh_path.resolve(), camera_fit.resolve(), int(width), int(height), float(mesh_scale), int(skin_level), torch_triangles, _project(torch_vertices, torch, width, height, camera_fit), dr.RasterizeCudaContext(), torch, torch_vertices)


def _frame_image(depth: np.ndarray, frame_name: str) -> Image.Image:
    image = Image.fromarray(np.clip(np.rint(depth * 255), 0, 255).astype(np.uint8), "L").convert("RGB")
    canvas = Image.new("RGB", (image.width, image.height + 26), (25, 25, 25))
    canvas.paste(image, (0, 26))
    ImageDraw.Draw(canvas).text((5, 5), f"GPU triangle depth | {frame_name}", fill=(240, 240, 240))
    return canvas


def render_gpu_depth_animation(rig: GpuRasterRig, *, frame_indices: tuple[int, ...], output_dir: Path, target_vda_depth_dir: Path | None = None) -> RasterResult:
    ensure_local_nvdiffrast(required=True)
    import nvdiffrast.torch as dr
    torch = rig.torch
    output_dir.mkdir(parents=True, exist_ok=True)
    rast, _ = dr.rasterize(rig.ctx, rig.clip_vertices.unsqueeze(0), rig.triangles, resolution=[rig.height, rig.width])
    coverage_raw = (rast[..., 3:4] > 0).to(rast.dtype)
    alpha = dr.antialias(
        coverage_raw,
        rast,
        rig.clip_vertices.unsqueeze(0),
        rig.triangles,
    )[0, ..., 0].clamp(0.0, 1.0)
    coverage = torch.flip(coverage_raw[0, ..., 0], dims=(-2,)) > 0
    alpha = torch.flip(alpha, dims=(-2,))
    depth = torch.flip(rast[0, ..., 2], dims=(-2,))
    depth = depth.detach().float().cpu().numpy()
    depth = np.clip((depth + 1.0) * 0.5, 0.0, 1.0)
    depth[~coverage.detach().cpu().numpy()] = 0.0
    alpha_dir = output_dir / "alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    alpha_frames = []
    frames = []
    for frame_index in frame_indices:
        frame = _frame_image(depth, f"f{frame_index:02d}")
        frames.append(frame)
        frame.save(output_dir / f"{frame_index:02d}.png")
        alpha = Image.fromarray(
            torch.round(alpha * 255.0).detach().cpu().numpy().astype(np.uint8),
            "L",
        ).convert("RGB")
        alpha_frames.append(alpha)
        alpha.save(alpha_dir / f"{frame_index:02d}.png")
    contact = Image.new("RGB", (frames[0].width, sum(frame.height for frame in frames)), (25, 25, 25))
    y = 0
    for frame in frames:
        contact.paste(frame, (0, y)); y += frame.height
    contact_path = output_dir / "gpu_triangle_depth_contact_sheet.png"
    contact.save(contact_path)
    gif_path = output_dir / "gpu_triangle_depth.gif"
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=83, loop=0, optimize=False)
    alpha_gif_path = output_dir / "gpu_triangle_alpha.gif"
    alpha_frames[0].save(alpha_gif_path, save_all=True, append_images=alpha_frames[1:], duration=83, loop=0, optimize=False)
    manifest = {"schema_version": 1, "renderer": "nvdiffrast RasterizeCudaContext", "rig": rig.summary(), "frame_indices": list(frame_indices), "target_vda_depth_dir": str(target_vda_depth_dir) if target_vda_depth_dir else None, "alpha_dir": str(alpha_dir), "alpha_gif": str(alpha_gif_path), "pose_policy": "bind pose repeated for renderer validation; no Blender fallback"}
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return RasterResult(manifest_path, contact_path, gif_path, alpha_dir, alpha_gif_path)


def _vda_depth_targets(directory: Path, frame_indices: tuple[int, ...], width: int, height: int):
    """Load VDA near-bright depth using the same frame order as the solver."""
    frames = []
    for index in frame_indices:
        path = directory / f"{int(index):02d}.png"
        if not path.is_file():
            raise FileNotFoundError(f"VDA depth frame is missing: {path}")
        image = Image.open(path).convert("L").resize((width, height), Image.Resampling.BILINEAR)
        frames.append(np.asarray(image, dtype=np.float32) / 255.0)
    return np.stack(frames)


OWNED_RUN_CHILDREN = (
    "solved_depth",
    "solved_alpha",
    "solved_rgb",
    "preview",
    "initialization",
    "blender_preview",
)
RASTER_RUN_CHILDREN = (
    "solved_depth",
    "solved_alpha",
    "solved_rgb",
    "preview",
    "blender_preview",
)


def replace_owned_run_artifacts(output_dir: Path, *, children: tuple[str, ...] = OWNED_RUN_CHILDREN) -> Path:
    """Clear this run slot's known artifact folders before a new write.

    Raster writers still refuse to merge into an existing ``solved_depth``
    or ``solved_rgb`` directory. A new solver call owns the slot, so leftover
    folders from a previous notebook run are replaced as whole directories
    rather than mixed with new frames. ``gpu_clip_result.json`` is not an
    owned child, so a finished pose solve survives leftover raster folders.
    After a long clip solve, clear only ``RASTER_RUN_CHILDREN`` so the
    profile-init camera files stay in ``initialization/``.
    """
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in children:
        child = output / name
        if child.is_dir():
            shutil.rmtree(child)
        elif child.exists():
            raise FileExistsError(f"owned run artifact exists and is not a directory: {child}")
    return output


def render_pose_depth_animation(experiment: Any, pose_result: dict[str, Any], *, output_dir: Path, frame_indices: tuple[int, ...]) -> tuple[Path, Path]:
    """Rasterize the solved, skinned triangles on CUDA and write VDA-oriented depth.

    This uses the optimizer's canonical FK/LBS implementation, then the same
    CUDA triangle backend as the bind smoke test. It deliberately fails if
    nvdiffrast is unavailable; there is no CPU or bind-pose fallback here.
    """
    import torch
    ensure_local_nvdiffrast(required=True)
    import nvdiffrast.torch as dr
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite raster output: {output_dir}")
    output_dir.mkdir(parents=True)
    alpha_dir = output_dir.parent / "solved_alpha"
    if alpha_dir.exists():
        raise FileExistsError(f"refusing to overwrite raster alpha output: {alpha_dir}")
    alpha_dir.mkdir(parents=True)
    poses = {int(k): v for k, v in pose_result.get("poses", {}).items()}
    missing = [frame for frame in frame_indices if frame not in poses]
    if missing:
        raise ValueError(f"pose result is missing frames: {missing}")
    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(poses)
    bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
    worlds = experiment._forward_kinematics(bone_vectors, bone_mask=experiment.active_node_mask)
    width, height = (int(v) for v in experiment.config.resolution)
    context = getattr(experiment, "_exact_raster_context", None)
    if context is None:
        raise RuntimeError(
            "pose depth preview requires the clip solver's CUDA raster context; "
            "do not allocate a second nvdiffrast context"
        )
    frames = []
    alpha_frames = []
    clip_vertices: list[Any] = []
    clip_triangles: list[Any] = []
    clip_depths: list[Any] = []
    with torch.no_grad():
        for frame_position, frame in enumerate(frame_indices):
            pieces = []
            triangles = []
            offset = 0
            for primitive in experiment.primitives:
                vertices = experiment._skinned_vertices(worlds[frame_position:frame_position + 1], primitive)
                vertices = experiment._root_transform(vertices, root_translation[frame_position:frame_position + 1], root_rotation[frame_position:frame_position + 1])[0]
                pieces.append(vertices)
                triangles.append(primitive.indices + offset)
                offset += int(vertices.shape[0])
            vertices = torch.cat(pieces, dim=0)
            triangles = torch.cat(triangles, dim=0).to(torch.int32)
            projected = torch.stack((
                torch.matmul(vertices, experiment.camera_right) * experiment.px_per_world[0] + experiment.camera_offset[0],
                torch.matmul(vertices, experiment.camera_down) * experiment.px_per_world[1] + experiment.camera_offset[1],
            ), dim=-1)
            clip_x = projected[:, 0] / max(width - 1, 1) * 2.0 - 1.0
            clip_y = 1.0 - projected[:, 1] / max(height - 1, 1) * 2.0
            # The camera fit's forward vector is the camera-to-subject ray.
            # Keep one depth range for the whole clip so frame-to-frame motion
            # is not erased by independent min/max normalization.
            camera_depth = torch.matmul(vertices, experiment.camera_forward)
            clip_depths.append(camera_depth)
            clip_vertices.append(torch.stack((clip_x, clip_y, camera_depth), dim=-1))
            clip_triangles.append(triangles)
        depth_min = torch.cat(clip_depths).amin()
        depth_max = torch.cat(clip_depths).amax()
        depth_span = torch.clamp(depth_max - depth_min, min=1e-6)
        for frame, packed, triangles in zip(frame_indices, clip_vertices, clip_triangles):
            z = (packed[:, 2] - depth_min) / depth_span
            clip = torch.stack((packed[:, 0], packed[:, 1], z * 2.0 - 1.0, torch.ones_like(z)), dim=-1)
            rast, _ = dr.rasterize(context, clip[None], triangles, resolution=[height, width])
            # Keep the exported GPU alpha on the same antialiased filled-
            # triangle contract used by the optimizer.  The triangle-ID
            # channel is not coverage; thresholding it directly produced a
            # hard mask that looked different from both the scored mask and
            # the final Blender alpha at low resolution.
            coverage_raw = (rast[..., 3:4] > 0).to(rast.dtype)
            alpha = dr.antialias(
                coverage_raw,
                rast,
                clip[None],
                triangles,
            )[0, ..., 0].clamp(0.0, 1.0)
            coverage = torch.flip(coverage_raw[0, ..., 0], dims=(-2,)) > 0
            alpha = torch.flip(alpha, dims=(-2,))
            # VDA is displayed as near-bright inverse depth; nvdiffrast z is far-bright.
            depth = (1.0 - ((torch.flip(rast[0, ..., 2], dims=(-2,)) + 1.0) * 0.5)).clamp(0.0, 1.0)
            depth[~coverage] = 0.0
            array = depth.cpu().numpy().astype(np.float32)
            frames.append(array)
            alpha_array = torch.round(alpha * 255.0).cpu().numpy().astype(np.uint8)
            alpha_image = Image.fromarray(alpha_array, "L")
            alpha_image.save(alpha_dir / f"{int(frame):02d}.png")
            alpha_frames.append(alpha_image.convert("RGB"))
            Image.fromarray(np.rint(array * 255).astype(np.uint8), "L").save(output_dir / f"{int(frame):02d}.png")
    gif_path = output_dir / "gpu_solved_depth.gif"
    images = [Image.open(output_dir / f"{int(frame):02d}.png").convert("RGB") for frame in frame_indices]
    images[0].save(gif_path, save_all=True, append_images=images[1:], duration=83, loop=0, optimize=False)
    alpha_gif_path = alpha_dir / "gpu_solved_alpha.gif"
    alpha_frames[0].save(alpha_gif_path, save_all=True, append_images=alpha_frames[1:], duration=83, loop=0, optimize=False)
    (output_dir / "manifest.json").write_text(json.dumps({"schema_version": 2, "frame_indices": list(frame_indices), "depth_convention": "near_bright", "renderer": "nvdiffrast RasterizeCudaContext", "source": "solved_pose_result", "alpha_dir": str(alpha_dir), "alpha_gif": str(alpha_gif_path)}, indent=2), encoding="utf-8")
    return output_dir, gif_path


def load_rgb_png_stack(directory: Path, frame_indices: tuple[int, ...]) -> np.ndarray:
    """Read written unlit RGB frames as float [0, 1] arrays."""
    frames: list[np.ndarray] = []
    missing: list[Path] = []
    for frame in frame_indices:
        path = Path(directory) / f"{int(frame):02d}.png"
        if not path.is_file():
            missing.append(path)
            continue
        frames.append(np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0)
    if missing:
        raise FileNotFoundError(f"unlit RGB preview frame(s) are missing: {missing}")
    return np.stack(frames)


def load_target_rgb_stack(
    target_frame_dir: Path,
    frame_indices: tuple[int, ...],
    *,
    width: int,
    height: int,
) -> np.ndarray:
    """Nearest-neighbor sprite RGB at the solver raster size, for color preview."""
    frames: list[np.ndarray] = []
    missing: list[Path] = []
    for frame in frame_indices:
        path = Path(target_frame_dir) / f"{int(frame):02d}.png"
        if not path.is_file():
            missing.append(path)
            continue
        with Image.open(path) as image:
            resized = image.convert("RGB").resize((int(width), int(height)), Image.Resampling.NEAREST)
            frames.append(np.asarray(resized, dtype=np.float32) / 255.0)
    if missing:
        raise FileNotFoundError(f"color-preview target RGB frame(s) are missing: {missing}")
    return np.stack(frames)


def preview_target_rgb_stack(experiment: Any, *, width: int, height: int) -> np.ndarray:
    """Reuse chroma target RGB when loaded; otherwise read the sprite plates."""
    target_rgb = getattr(experiment, "target_rgb", None)
    if target_rgb is not None:
        return target_rgb.detach().cpu().numpy()
    return load_target_rgb_stack(
        Path(experiment.target_frame_dir),
        tuple(int(frame) for frame in experiment.frame_indices),
        width=int(width),
        height=int(height),
    )


def _as_numpy_occupancy(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=np.float32)
    return np.asarray(value.detach().cpu().numpy(), dtype=np.float32)


def _resize_occupancy_stack(stack: np.ndarray, *, height: int, width: int) -> np.ndarray:
    planes = np.asarray(stack, dtype=np.float32)
    if planes.ndim != 3:
        raise ValueError(f"occupancy stack must be [frame,height,width], got {planes.shape}")
    if int(planes.shape[1]) == int(height) and int(planes.shape[2]) == int(width):
        return planes
    resized = []
    for plane in planes:
        image = Image.fromarray(np.clip(plane * 255.0, 0.0, 255.0).astype(np.uint8), "L")
        resized.append(
            np.asarray(image.resize((int(width), int(height)), Image.Resampling.NEAREST), dtype=np.float32)
            / 255.0
        )
    return np.stack(resized)


def occupancy_stack_for_preview(
    experiment: Any,
    *,
    alpha_dir: Path,
    frame_indices: tuple[int, ...],
    height: int,
    width: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build occupancy overlays from the solver masks and written alpha PNGs.

    The clip solver does not keep mask arrays in RAM for the whole search.
    Preview still needs them once, at the unlit RGB size.
    """
    target = _resize_occupancy_stack(
        _as_numpy_occupancy(experiment.target_masks),
        height=int(height),
        width=int(width),
    )
    if int(target.shape[0]) != len(frame_indices):
        raise ValueError(
            "target occupancy frame count "
            f"{int(target.shape[0])} does not match {len(frame_indices)}"
        )
    predicted_frames: list[np.ndarray] = []
    missing: list[Path] = []
    for frame in frame_indices:
        path = Path(alpha_dir) / f"{int(frame):02d}.png"
        if not path.is_file():
            missing.append(path)
            continue
        predicted_frames.append(np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0)
    if missing:
        raise FileNotFoundError(f"solved alpha preview frame(s) are missing: {missing}")
    predicted = _resize_occupancy_stack(
        np.stack(predicted_frames),
        height=int(height),
        width=int(width),
    )
    return target, predicted


def render_pose_rgb_animation(
    experiment: Any,
    pose_result: dict[str, Any],
    *,
    output_dir: Path,
    frame_indices: tuple[int, ...],
) -> tuple[Path, Path]:
    """Write the exact rasterizer's unlit textured RGB preview.

    This is the same CUDA triangle/LBS path used by semantic interleave
    scoring. It is intentionally labeled unlit RGB: it is not a replacement
    for the later Blender lighting/parity render.
    """
    import torch

    ensure_local_nvdiffrast(required=True)
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite raster RGB output: {output_dir}")
    output_dir.mkdir(parents=True)
    poses = {int(k): v for k, v in pose_result.get("poses", {}).items()}
    missing = [frame for frame in frame_indices if frame not in poses]
    if missing:
        raise ValueError(f"pose result is missing frames: {missing}")
    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(poses)
    bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
    with torch.no_grad():
        rgb, _alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )
    images: list[Image.Image] = []
    for frame_position, frame in enumerate(frame_indices):
        array = np.rint(
            rgb[frame_position].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0
        ).astype(np.uint8)
        image = Image.fromarray(array, "RGB")
        image.save(output_dir / f"{int(frame):02d}.png", format="PNG", compress_level=0)
        images.append(image)
    gif_path = output_dir / "gpu_solved_rgb.gif"
    images[0].save(gif_path, save_all=True, append_images=images[1:], duration=83, loop=0, optimize=False)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frame_indices": list(frame_indices),
                "renderer": "nvdiffrast RasterizeCudaContext",
                "color": "unlit_base_color_texture_neutral_matte",
                "source": "solved_pose_result",
                "gif": str(gif_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_dir, gif_path


def _depth_comparison(gpu_dir: Path, target_dir: Path, frame_indices: tuple[int, ...], width: int, height: int) -> dict[str, Any]:
    target = _vda_depth_targets(target_dir, frame_indices, width, height)
    predicted = np.stack([
        np.asarray(Image.open(gpu_dir / f"{int(frame):02d}.png").convert("L"), dtype=np.float32) / 255.0
        for frame in frame_indices
    ])
    valid = (target > 0.0) & (predicted > 0.0)
    if not np.any(valid):
        raise ValueError("VDA/GPU depth comparison has no overlapping foreground pixels")
    direct = float(np.abs(predicted[valid] - target[valid]).mean())
    inverted = float(np.abs((1.0 - predicted[valid]) - target[valid]).mean())
    return {
        "frames": len(frame_indices),
        "nearBrightSelected": direct <= inverted,
        "maeNearBright": direct,
        "maeInverted": inverted,
        "validPixelFraction": float(valid.mean()),
    }


def solve_gpu_depth_animation(*, src_glb: Path, camera_fit: Path, target_frame_dir: Path, frame_indices: tuple[int, ...], config: Any, output_dir: Path, vda_depth_dir: Path | None = None, render_blender: bool = False, blender_kwargs: dict[str, Any] | None = None, profile_init_hook: Any | None = None, initial_poses: Mapping[int, Mapping[str, Any]] | None = None, live_preview: bool | None = None, preview_every: int | None = None, live_preview_scale: int = 4, live_preview_host: Any | None = None) -> AnimationSolveResult:
    """Run the real animation solve, exact CUDA depth export, and optional lit render."""
    from roc_gpu_cascade_experiment import GpuCascadeExperiment, export_gpu_render_preview, persist_gpu_clip_result
    output_dir = Path(output_dir)
    camera_fit = Path(camera_fit)
    wipe_children = OWNED_RUN_CHILDREN
    init_dir = (output_dir / "initialization").resolve()
    if camera_fit.is_file():
        try:
            camera_fit.resolve().relative_to(init_dir)
        except ValueError:
            pass
        else:
            # Reused profile camera lives in this run slot — do not wipe it.
            wipe_children = tuple(c for c in OWNED_RUN_CHILDREN if c != "initialization")
    output_dir = replace_owned_run_artifacts(output_dir, children=wipe_children)
    from gpu_depth_silhouette_solver import GpuDepthLivePreview, render_chroma_occupancy_preview

    initialization = None
    if profile_init_hook is not None:
        camera_fit, initialization = profile_init_hook(output_dir, camera_fit)
    preview_dir = output_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    use_live_preview = bool(getattr(config, "live_preview", False)) if live_preview is None else bool(live_preview)
    use_preview_every = int(getattr(config, "preview_every", 1)) if preview_every is None else int(preview_every)
    resolved_live_preview_host = live_preview_host
    if resolved_live_preview_host is None and use_live_preview:
        resolved_live_preview_host = GpuDepthLivePreview(
            preview_dir / "live_preview.png",
            every=use_preview_every,
            scale=int(live_preview_scale),
            alpha_threshold=float(getattr(config, "ik_miss_predicted_alpha_threshold", 0.5)),
        )
    experiment = GpuCascadeExperiment(src_glb=src_glb, camera_fit=camera_fit, target_frame_dir=target_frame_dir, frame_indices=frame_indices, config=config)
    try:
        result = experiment.optimize_clip(
            initial_poses=initial_poses,
            progress=True,
            live_preview=use_live_preview,
            preview_every=use_preview_every,
            live_preview_path=preview_dir / "live_preview.png",
            live_preview_scale=int(live_preview_scale),
            live_preview_host=resolved_live_preview_host,
        )
        if initialization is not None:
            result["initialization"] = initialization.to_dict() if hasattr(initialization, "to_dict") else initialization
        result["cameraFitPath"] = str(camera_fit)
        # Poses must hit disk before preview rasters. A leftover solved_depth
        # folder must not throw away a finished cascade clip.
        result["clipResultPath"] = str(persist_gpu_clip_result(result, output_dir))
        replace_owned_run_artifacts(output_dir, children=RASTER_RUN_CHILDREN)
        depth_dir, depth_gif = render_pose_depth_animation(experiment, result, output_dir=output_dir / "solved_depth", frame_indices=frame_indices)
        depth_comparison = _depth_comparison(depth_dir, vda_depth_dir, frame_indices, int(config.resolution[0]), int(config.resolution[1])) if vda_depth_dir is not None else None
        if depth_comparison is not None:
            result["depthComparison"] = depth_comparison
        rgb_dir, rgb_gif = render_pose_rgb_animation(
            experiment,
            result,
            output_dir=output_dir / "solved_rgb",
            frame_indices=frame_indices,
        )
        predicted_rgb = load_rgb_png_stack(rgb_dir, frame_indices)
        target_rgb = preview_target_rgb_stack(
            experiment,
            width=int(predicted_rgb.shape[2]),
            height=int(predicted_rgb.shape[1]),
        )
        if target_rgb.shape != predicted_rgb.shape:
            raise ValueError(
                "color preview target RGB shape "
                f"{tuple(target_rgb.shape)} does not match the rastered mesh RGB "
                f"{tuple(predicted_rgb.shape)}"
            )
        result["targetRgb"] = target_rgb
        result["predictedRgb"] = predicted_rgb
        result["rgbDir"] = str(rgb_dir)
        result["rgbGif"] = str(rgb_gif)
        target_masks, predicted_masks = occupancy_stack_for_preview(
            experiment,
            alpha_dir=output_dir / "solved_alpha",
            frame_indices=frame_indices,
            height=int(predicted_rgb.shape[1]),
            width=int(predicted_rgb.shape[2]),
        )
        result["targetMasks"] = target_masks
        result["predictedMasks"] = predicted_masks
        preview_gif = render_chroma_occupancy_preview(
            result,
            output_dir=output_dir / "preview",
            frame_indices=frame_indices,
            scale=1,
        )
        result["previewGif"] = str(preview_gif)
        blender_result = None
        if render_blender:
            kwargs = dict(blender_kwargs or {})
            required = ("unit_name", "animation_name", "pilot_dir", "camera_fit_path")
            missing = [name for name in required if name not in kwargs]
            if missing:
                raise ValueError(f"render_blender=True requires blender_kwargs: {missing}")
            blender_result = export_gpu_render_preview(result, src_glb=src_glb, frame_indices=frame_indices, output_dir=output_dir / "blender_preview", **kwargs)
        result["gpuAlphaDir"] = str(output_dir / "solved_alpha")
        result["gpuAlphaGif"] = str(output_dir / "solved_alpha" / "gpu_solved_alpha.gif")
        result["clipResultPath"] = str(persist_gpu_clip_result(result, output_dir))
        return AnimationSolveResult(
            pose_result=result,
            depth_dir=depth_dir,
            depth_gif=depth_gif,
            blender_preview=blender_result,
            gpu_preview=preview_gif,
            alpha_dir=output_dir / "solved_alpha",
            alpha_gif_path=output_dir / "solved_alpha" / "gpu_solved_alpha.gif",
            rgb_dir=rgb_dir,
            rgb_gif_path=rgb_gif,
        )
    finally:
        experiment.release_cuda()


def cascade_optimize_root_rotation(
    *,
    root_search_enabled: bool,
    articulated_root_interleave_enabled: bool = False,
    idle_fused_macro_enabled: bool = False,
    idle_fused_reroot_transit_after_articulated: bool = False,
    score_escape_enabled: bool = False,
    root_rotation_defer_camera_up: bool = False,
) -> bool:
    """True when any later root-yaw stage still needs optimize_root_rotation.

    Early 64-hypothesis search is ``root_search_enabled``. CURRENT_CASCADE_KEEP
    often leaves that off and still requires deferred after-joint camera-up yaw.
    """
    return (
        bool(root_search_enabled)
        or bool(articulated_root_interleave_enabled)
        or bool(idle_fused_macro_enabled)
        or bool(idle_fused_reroot_transit_after_articulated)
        or bool(score_escape_enabled)
        or bool(root_rotation_defer_camera_up)
    )


def run_gpu_depth_fit_from_hybrid_config(
    config: Any,
    *,
    output_dir: Path | None = None,
    depth_weight: float = 0.65,
    silhouette_weight: float = 0.35,
    depth_tolerance: float = 0.08,
    depth_robust_delta: float = 0.12,
    chroma_weight: float = 0.0,
    motion_weight: float = 0.0,
    motion_exempt_idle_prefix: bool = False,
    temporal_scoring_mode: str = "default",
    velocity_weight: float | None = None,
    acceleration_weight: float | None = None,
    root_velocity_weight: float | None = None,
    root_acceleration_weight: float | None = None,
    root_rotation_velocity_weight: float | None = None,
    root_rotation_acceleration_weight: float | None = None,
    bone_pose_prior_weight: float | None = None,
    root_translation_prior_weight: float | None = None,
    root_rotation_prior_weight: float | None = None,
    chroma_tolerance: float = 0.10,
    chroma_robust_delta: float = 0.12,
    chroma_error_scale: float = 80.0,
    chroma_scale: int = 4,
    chroma_resolution: tuple[int, int] | None = None,
    score_mode: str = "geometry",
    dense_semantic_model_id: str = "facebook/dinov3-vits16-pretrain-lvd1689m",
    dense_semantic_feature_layers: Sequence[str] = ("last",),
    dense_semantic_local_radius: int = 1,
    dense_semantic_position_weight: float = 1.0,
    dense_semantic_autograd_enabled: bool = False,
    dense_semantic_batch_size: int = 32,
    dense_semantic_raster_scale: int = 0,
    dense_semantic_subject_crop: bool = False,
    dense_semantic_subject_padding_frac: float = 0.18,
    collision_enabled: bool = True,
    collision_sample_count: int = 256,
    collision_geodesic_min_hops: int = 8,
    collision_margin_body_lengths: float = 0.04,
    collision_weight: float = 0.35,
    exact_raster_enabled: bool = True,
    resolution: tuple[int, int] | None = None,
    profile_init_enabled: bool = True,
    profile_init_frame: int | None = None,
    profile_init_target_dir: str | Path | None = None,
    profile_init_fit_target_dir: str | Path | None = None,
    profile_init_yaw_min_deg: float = -180.0,
    profile_init_yaw_max_deg: float = 180.0,
    profile_init_yaw_step_deg: float = 15.0,
    profile_init_roll_range_deg: float = 8.0,
    profile_init_roll_step_deg: float = 8.0,
    profile_init_facing_weight: float | None = None,
    profile_init_rank_metric: str | None = None,
    profile_init_fit_margin: float = 0.96,
    profile_init_top_k: int = 8,
    profile_init_camera_basis_mode: str = "upright_turntable",
    profile_init_world_up_axis: tuple[float, ...] = (0.0, 1.0, 0.0),
    profile_init_resolution: tuple[int, int] | None = None,
    profile_init_max_dimension: int = 256,
    root_rotation_first_frame_limit_deg: float = 30.0,
    root_rotation_per_frame_limit_deg: float = 30.0,
    root_rotation_camera_up_limit_deg: float = 45.0,
    root_rotation_defer_camera_up: bool = True,
    root_rotation_after_joints_yaw_enabled: bool = True,
    root_rotation_axes: Sequence[str] = ("camera_forward", "camera_right", "camera_up"),
    root_search_enabled: bool = True,
    root_translation_axes: Sequence[str] = ("forward", "lateral", "vertical"),
    root_translation_limit_body_lengths: float = 0.75,
    root_translation_radius_body_lengths: float = 0.35,
    seed_previous_frame: bool = True,
    # When set, override idle prefix/suffix derived from DEF group counts.
    # Needed when frame_indices subset a longer idle_start_move_end materialize
    # (DEF counts must stay authentic for rematerialize, but the loaded clip
    # may keep only one idle frame).
    idle_prefix_frames: int | None = None,
    idle_suffix_frames: int | None = None,
    idle_suffix_mirror_prefix_enabled: bool = False,
    joint_search_axes: Sequence[str] = ("x", "y", "z"),
    joint_diagonal_axes: int = 6,
    joint_step_deg: float = 15.0,
    fine_joint_step_deg: float = 2.5,
    joint_adaptive_step_enabled: bool = True,
    joint_step_score_coarse: float = 0.45,
    joint_step_score_fine: float = 0.80,
    joint_step_score_norm: str = "logit_minmax",
    joint_score_raster_batch: int = 512,
    cheap_joint_probe_occupancy_only: bool = False,
    cheap_joint_probe_frame_count: int = 0,
    joint_pass_limit_deg: float = 0.0,
    fine_joint_pass_limit_deg: float = 0.0,
    joint_probe_rungs: int = 3,
    joint_round_followup_neighbors: bool = True,
    joint_absolute_gain_weight: float = 1.0,
    joint_unique_gain_weight: float = 0.35,
    fine_unique_gain_weight: float = 0.0,
    joint_keep_still_sprite_lock: bool = False,
    joint_keep_still_sprite_rgb_mad: float = 0.015,
    joint_keep_sprite_change_gate: bool = False,
    joint_keep_sprite_change_weight: float = 1.0,
    joint_keep_sprite_change_slack: float = 0.0,
    joint_collision_positive_abs_slack: float = 0.12,
    joint_temporal_consensus_enabled: bool = True,
    joint_temporal_consensus_tie_bonus: float = 1e-5,
    joint_temporal_consensus_bidirectional: bool = True,
    joint_temporal_consensus_idle_end: bool = True,
    joint_temporal_consensus_independent_passes: bool = True,
    joint_temporal_consensus_whole_pose: bool = True,
    gradient_ladder_enabled: bool = False,
    gradient_ladder_iterations: int = 1,
    gradient_ladder_step_degs: Sequence[float] = (2.5, 5.0, 10.0),
    gradient_ladder_min_gradient_norm: float = 1e-6,
    joint_solver_mode: str = "discrete",
    chain_space_enabled: bool = False,
    chain_space_mode: str = "chain_grad",
    chain_space_iterations: int = 3,
    chain_space_step_degs: Sequence[float] = (5.0, 10.0, 20.0, 40.0),
    chain_space_min_gradient_norm: float = 1e-6,
    chain_space_trust_radius_deg: float = 20.0,
    chain_space_trust_radius_min_deg: float = 1.25,
    chain_space_trust_radius_max_deg: float = 40.0,
    chain_space_min_clip_improvement: float = 1e-6,
    chain_space_eval_budget: int | None = None,
    sa_enabled: bool = False,
    sa_restarts: int = 4,
    sa_iterations: int = 200,
    sa_initial_temperature: float = 0.1,
    sa_final_temperature: float = 0.001,
    sa_perturbation_scale_deg: float = 45.0,
    sa_bone_fraction: float = 0.5,
    sa_seed: int | None = None,
    sa_seed_from_current: bool = True,
    sa_min_bone_depth: int = 3,
    sa_collision_weight: float | None = 0.0,
    physics_smooth_enabled: bool = True,
    physics_smooth_outlier_window: int = 5,
    physics_smooth_outlier_sigma: float = 3.5,
    physics_smooth_outlier_min_deg: float = 10.0,
    physics_smooth_outlier_min_translation: float = 0.08,
    physics_smooth_stiffness: float = 180.0,
    physics_smooth_dt: float = 1.0 / 12.0,
    physics_smooth_substeps: int = 4,
    physics_smooth_gravity: float = 9.81,
    physics_smooth_gravity_weight: float = 0.6,
    physics_smooth_gravity_min_bone_depth: int = 3,
    physics_smooth_root_vertical_axis: int = 2,
    physics_smooth_world_up: Sequence[float] = (0.0, 1.0, 0.0),
    sprite_aligned_motion_keep_enabled: bool = False,
    sprite_aligned_motion_keep_min_improvement: float = 0.01,
    score_escape_enabled: bool = False,
    score_escape_threshold: float = 0.80,
    score_escape_mode: str = "",
    score_escape_coarse_push_coarse: float = 0.85,
    score_escape_coarse_push_fine: float = 0.92,
    score_escape_root_window_deg: float = 12.0,
    score_escape_root_step_deg: float = 4.0,
    score_escape_sa_restarts: int = 2,
    score_escape_sa_iterations: int = 80,
    score_escape_sa_perturbation_deg: float = 25.0,
    score_escape_sa_bone_fraction: float = 0.35,
    score_escape_max_rounds: int = 3,
    score_escape_min_improvement: float = 0.005,
    score_escape_worst_frame_count: int = 3,
    score_escape_worst_frame_collision_weight: float = 0.0,
    score_escape_keep_best: bool = True,
    score_escape_fail_fast: bool = True,
    score_escape_root_held_abort: int = 3,
    score_escape_threshold_uses_hybrid_mean: bool = False,
    score_escape_skip_coarse_broad_when_seeded: bool = False,
    score_escape_skip_coarse_broad_below_mean: float = 0.0,
    score_escape_shared_transit_yaw_enabled: bool = False,
    score_escape_skip_articulated_retry_when_seeded: bool = True,
    score_escape_articulated_iterations: int = 0,
    score_escape_collision_burst_enabled: bool = False,
    score_escape_collision_burst_threshold: float = 0.15,
    score_escape_translation_burst_enabled: bool = False,
    score_escape_translation_burst_mode: str = "all_transit",
    score_escape_translation_window_body_lengths: float = 0.12,
    score_escape_translation_hypotheses: int = 48,
    score_escape_translation_axes: Sequence[str] = ("vertical",),
    score_escape_translation_wave_phase_span_rad: float = math.pi,
    root_hypotheses: int | None = None,
    ik_enabled: bool = False,
    ik_keypoints_path: str | None = None,
    ik_bone_roles_path: str | None = None,
    ik_keypoints_source: str = "authored",
    ik_miss_depth_tolerance: float = 0.12,
    ik_miss_min_component_area: int = 24,
    ik_miss_max_pairs: int = 2,
    ik_miss_predicted_alpha_threshold: float = 0.5,
    ik_miss_max_tip_distance_px: float = 56.0,
    ik_miss_max_centroid_distance_px: float = 72.0,
    ik_miss_max_area_ratio: float = 4.0,
    ik_miss_min_displacement_alignment: float = 0.15,
    ik_iterations: int = 16,
    ik_max_step_deg: float = 15.0,
    ik_require_improvement: bool = True,
    ik_blob_iou_target: float = 0.9,
    ik_proximal_min_depth: int = 3,
    ik_proximal_max_step_deg: float = 5.0,
    ik_max_chain_depth: int = 6,
    ik_repair_dilate_px: int = 4,
    ik_blob_search_rounds: int = 3,
    ik_silhouette_score_mode: str = "regional_iou",
    ik_job_order_mode: str = "pair_rank",
    ik_step_scale_mode: str = "fixed",
    ik_step_displacement_ref_px: float = 56.0,
    ik_step_scale_min: float = 0.4,
    ik_step_scale_max: float = 1.6,
    ik_chain_start_mode: str = "distal",
    ik_chain_displacement_ref_px: float = 40.0,
    ik_frame_order_mode: str = "clip",
    ik_influence_dominance_min: float = 0.0,
    ik_dynamic_stop_enabled: bool = False,
    anatomy_head_pin_enabled: bool = False,
    anatomy_head_pin_parts: Sequence[str] = ("head",),
    anatomy_head_pin_bone_roles_path: str = "",
    anatomy_head_pin_chain_bones: Sequence[str] = (
        "Bone_016",
        "Bone_015",
        "Bone_014",
    ),
    anatomy_head_pin_iterations: int = 16,
    anatomy_head_pin_max_step_deg: float = 12.0,
    anatomy_head_pin_require_improvement: bool = True,
    anatomy_head_pin_skip_idle_prefix: bool = False,
    anatomy_head_pin_accept_metric: str = "hybrid",
    idle_fused_macro_enabled: bool = False,
    idle_fused_skip_macro_when_seeded: bool = True,
    idle_fused_skip_reroot_when_seeded: bool = True,
    root_skip_when_seeded: bool = True,
    articulated_skip_when_seeded: bool = True,
    idle_fused_importance_mode: str = "error_leverage",
    idle_fused_worst_frame_count: int = 4,
    idle_fused_top_bone_count: int = 4,
    idle_fused_macro_chain_count: int = 2,
    idle_fused_root_window_deg: float = 45.0,
    idle_fused_root_step_deg: float = 15.0,
    idle_fused_macro_step_deg: float = 22.0,
    idle_fused_macro_root_rotation_axes: Sequence[str] | None = None,
    idle_fused_per_frame_root_enabled: bool = True,
    idle_fused_per_frame_root_count: int = 5,
    idle_fused_shared_transit_yaw_enabled: bool = False,
    idle_fused_shared_transit_yaw_window_deg: float = 90.0,
    idle_fused_shared_transit_yaw_step_deg: float = 15.0,
    idle_fused_shared_transit_yaw_bone_adapt_rounds: int = 0,
    idle_fused_shared_transit_yaw_bone_adapt_top_bones: int = 4,
    idle_fused_shared_transit_yaw_post_articulated_iterations: int = 0,
    idle_fused_shared_transit_yaw_ignore_motion: bool = False,
    idle_fused_shared_transit_yaw_pre_articulated: bool = False,
    idle_fused_shared_transit_yaw_post_articulated: bool = True,
    live_status_path: str = "",
    idle_fused_reroot_transit_after_articulated: bool = False,
    idle_fused_reroot_all_transit: bool = True,
    base_pose_enabled: bool = True,
    base_pose_iterations: int = 2,
    mid_pose_enabled: bool = True,
    mid_pose_iterations: int = 1,
    mid_joint_step_deg: float = 5.0,
    root_refit_after_base_enabled: bool = True,
    root_refit_translation_body_lengths: float = 0.05,
    root_refit_translation_step_body_lengths: float = 0.025,
    root_refit_rotation_deg: float = 5.0,
    root_refit_rotation_step_deg: float = 2.5,
    articulated_root_interleave_enabled: bool = False,
    articulated_root_interleave_rotation_deg: float = 8.0,
    articulated_root_interleave_rotation_step_deg: float = 4.0,
    articulated_root_interleave_include_translation: bool = False,
    articulated_root_interleave_policy: str = "per_accept",
    articulated_root_interleave_primary_groups: Sequence[str] = (),
    articulated_multi_bone_enabled: bool = False,
    articulated_multi_bone_block_size: int = 2,
    articulated_funnel_enabled: bool = False,
    articulated_funnel_broad_step_deg: float = 45.0,
    articulated_funnel_broad_probe_rungs: int = 4,
    articulated_funnel_broad_rounds: int = 1,
    articulated_funnel_broad_min_improvement: float = 0.0,
    articulated_funnel_force_gradient_order: bool = True,
    articulated_funnel_broad_multi_bone_block_size: int = 3,
    articulated_funnel_worst_frame_keep_enabled: bool = False,
    articulated_funnel_worst_frame_keep_count: int = 4,
    articulated_funnel_worst_frame_keep_weight: float = 2.0,
    anatomy_groups_catalog_path: str = "",
    anatomy_group_visit_order: Sequence[str] = (),
    anatomy_veto_enabled: bool = False,
    anatomy_veto_strain_enabled: bool = True,
    anatomy_veto_collision_enabled: bool = True,
    anatomy_veto_prop_enabled: bool = False,
    anatomy_veto_strain_tolerance: float = 0.08,
    anatomy_veto_strain_exclusive_weight: float = 0.99,
    anatomy_veto_strain_min_rest_length_body_lengths: float = 0.02,
    anatomy_veto_strain_slack: float = 0.02,
    anatomy_veto_collision_slack: float = 0.12,
    anatomy_veto_prop_slack_px: float = 12.0,
    anatomy_veto_hard_strain_margin: float = 0.03,
    anatomy_veto_hard_collision_margin: float = 0.05,
    anatomy_veto_hard_prop_margin_px: float = 24.0,
    anatomy_veto_dino_tie_band: float = 0.002,
    anatomy_veto_soft_weight: float = 0.05,
    anatomy_veto_bone_roles_path: str = "",
    anatomy_veto_prop_coords_path: str = "",
    early_symmetry_enabled: bool = False,
    early_symmetry_visit_limit: int = 24,
    early_symmetry_bilateral_group_pairs: Sequence[tuple[str, str]] = (),
    early_symmetry_central_groups: Sequence[str] = (),
    early_symmetry_central_joint_axes: Sequence[str] = ("x", "y"),
    branch_rescue_enabled: bool = True,
    branch_rescue_block_size: int = 2,
    branch_rescue_values_per_bone: int = 3,
    skip_tiny_bones: bool = True,
    min_leaf_length_frac: float = 0.45,
    fine_only_leaf_length_frac: float = 0.75,
    bone_order_mode: str = "dependency",
    search_bones: Sequence[str] = (),
    include_unlisted_search_bones: bool = True,
    bone_limit_scale_overrides: Sequence[Sequence] = (),
    freeze_root_after_root_stage: bool = True,
    fine_root_enabled: bool = False,
    articulated_iterations: int | None = None,
    fine_iterations: int | None = None,
    root_iterations: int | None = None,
    live_preview: bool | None = None,
    preview_every: int | None = None,
    live_preview_scale: int = 4,
    config_only: bool = False,
    initial_poses: Mapping[int, Mapping[str, Any]] | None = None,
) -> AnimationSolveResult | object:
    """Run the Blender-free fitting backend using a ``RocHybridConfig``.

    This adapter is intentionally narrow so the original notebook can switch
    backends without reconstructing asset paths or worker protocols in a cell.
    Score terms are the same silhouette, Huber depth, Lab chroma, occupancy
    motion, and collision blend used by ``one_bone_depth``, unless
    ``score_mode='dinov3_dense'``. ``motion_weight`` 0 keeps the old per-frame
    fill mix. A positive motion weight cannot ship.
    That ablation scores every candidate with gated DINOv3 patch grids only
    and cannot ship. ``depth_weight`` is the geometry blend weight, not the
    old subtracted mean-absolute depth scale.
    """
    from cascade_bone_limits import validate_bone_limit_scale_overrides
    from gpu_geometry_score import gpu_score_raster_resolution
    from roc_gpu_cascade_experiment import (
        GpuCascadeConfig,
        clip_uses_idle_end_anchor,
        idle_prefix_frame_count,
        idle_suffix_frame_count,
        resolve_ik_bone_roles_path,
        resolve_ik_keypoints_path,
    )
    from roc_semantic_hybrid_experiment import prepare_gpu_fit_config

    config = prepare_gpu_fit_config(config)
    def_groups = getattr(config, "def_lab_group", None)
    if def_groups is None:
        idle_prefix = 0
        idle_suffix = 0
        idle_end = False
    else:
        group_tuple = (int(def_groups),) if isinstance(def_groups, int) else tuple(int(group) for group in def_groups)
        idle_prefix = idle_prefix_frame_count(group_tuple, getattr(config, "def_expected_count", None))
        idle_suffix = idle_suffix_frame_count(group_tuple, getattr(config, "def_expected_count", None))
        idle_end = bool(joint_temporal_consensus_idle_end) and clip_uses_idle_end_anchor(group_tuple)
    if idle_prefix_frames is not None:
        if int(idle_prefix_frames) < 0:
            raise ValueError("idle_prefix_frames must be >= 0")
        idle_prefix = int(idle_prefix_frames)
    if idle_suffix_frames is not None:
        if int(idle_suffix_frames) < 0:
            raise ValueError("idle_suffix_frames must be >= 0")
        idle_suffix = int(idle_suffix_frames)
        # Explicit suffix override means the loaded clip no longer ends on the
        # trailing idle block that would authorize an idle-end reverse anchor.
        if idle_suffix == 0:
            idle_end = False

    if not bool(exact_raster_enabled):
        raise ValueError("cascade geometry scoring requires exact_raster_enabled")
    root = Path(config.root).resolve()
    pilot = Path(config.pilot_dir) if config.pilot_dir is not None else root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    pilot = pilot.resolve()
    target = (pilot / config.shadow_culled_frame_dir).resolve()
    camera = Path(config.camera_fit_path) if config.camera_fit_path is not None else pilot / "roc_sprite_camera_fit.json"
    camera = camera.resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"GPU fit requires alpha-shadow-culled frames: {target}")
    if not camera.is_file():
        raise FileNotFoundError(f"GPU fit camera fit is missing: {camera}")
    frame_indices = tuple(int(frame) for frame in config.frame_indices)
    if not frame_indices:
        discovered = sorted(
            int(path.stem)
            for path in target.glob("*.png")
            if path.stem.isdigit()
        )
        if not discovered:
            raise FileNotFoundError(f"GPU fit found no numbered source frames: {target}")
        frame_indices = tuple(discovered)
    resolved_ik_keypoints_path = ik_keypoints_path
    resolved_ik_bone_roles_path = ik_bone_roles_path
    if bool(ik_enabled):
        ik_source = str(ik_keypoints_source)
        if ik_source == "authored":
            resolved_ik_keypoints_path = str(
                resolve_ik_keypoints_path(
                    root=root,
                    unit_name=str(getattr(config, "unit_name", "") or ""),
                    animation_name=str(getattr(config, "animation_name", "") or ""),
                    explicit=ik_keypoints_path,
                    def_lab_groups=getattr(config, "def_lab_group", None),
                    def_expected_counts=getattr(config, "def_expected_count", None),
                    src_glb=Path(config.src_glb).resolve(),
                    lab_sid=str(getattr(config, "unit_sid", "") or "") or None,
                )
            )
        elif ik_source != "silhouette_miss":
            raise ValueError(f"unsupported ik_keypoints_source: {ik_source!r}")
        if ik_source == "authored":
            resolved_ik_bone_roles_path = str(
                resolve_ik_bone_roles_path(
                    unit_name=str(getattr(config, "unit_name", "") or ""),
                    src_glb=Path(config.src_glb).resolve(),
                    explicit=ik_bone_roles_path,
                )
            )
        else:
            resolved_ik_bone_roles_path = None
        print(
            f"gpu ik: source={ik_source} "
            f"keypoints={resolved_ik_keypoints_path if ik_source == 'authored' else 'dynamic'} "
            f"roles={resolved_ik_bone_roles_path if ik_source == 'authored' else 'skeleton'}",
            flush=True,
        )
    proxy_resolution = tuple(int(v) for v in (resolution or getattr(config, "proxy_resolution", (96, 86))))
    dinov3_only = str(score_mode) == "dinov3_dense"
    dinov3_consensus = str(score_mode) == "dinov3_geometry_consensus"
    needs_dense_rgb = dinov3_only or dinov3_consensus
    resolved_dense_raster_scale = int(dense_semantic_raster_scale)
    if dinov3_only:
        depth_weight = 0.0
        silhouette_weight = 0.0
        chroma_weight = 0.0
        motion_weight = 0.0
        collision_enabled = False
        collision_weight = 0.0
        joint_unique_gain_weight = 0.0
        fine_unique_gain_weight = 0.0
        print(
            "gpu cascade score_mode=dinov3_dense: silhouette/depth/chroma/collision off; "
            "Adam root off; root hypotheses obey root_search_enabled. "
            "gradient_ladder_enabled and ik_enabled must stay False; "
            "bone_order_mode must be asset or dependency",
            flush=True,
        )
    elif dinov3_consensus:
        print(
            "gpu cascade score_mode=dinov3_geometry_consensus: "
            "keep = geometric mean of silhouette IoU and DINOv3 dense quality",
            flush=True,
        )
    if needs_dense_rgb:
        if resolved_dense_raster_scale < 0:
            raise ValueError("dense_semantic_raster_scale must be 0 (derive) or at least 2")
        if resolved_dense_raster_scale == 0:
            from dense_semantic_features import (
                dense_processor_input_hw,
                dense_semantic_raster_scale_for_proxy,
                load_dense_image_processor,
            )

            processor = load_dense_image_processor(
                str(dense_semantic_model_id),
                family="dino",
                local_files_only=True,
            )
            proc_height, proc_width = dense_processor_input_hw(processor)
            resolved_dense_raster_scale = dense_semantic_raster_scale_for_proxy(
                proxy_resolution,
                processor,
            )
            print(
                f"gpu cascade dinov3 raster scale={resolved_dense_raster_scale} "
                f"derived from processor {proc_width}x{proc_height} vs proxy "
                f"{int(proxy_resolution[0])}x{int(proxy_resolution[1])} "
                "(camera aspect kept; processor still square-resizes). "
                "ViT encode is fp16; local-window keep is fp32 "
                "(near-ties at joint_keep_min_improvement=1e-6 may flip vs pure fp32).",
                flush=True,
            )
        elif resolved_dense_raster_scale < 2:
            raise ValueError("dense_semantic_raster_scale must be 0 (derive) or at least 2")
        else:
            print(
                f"gpu cascade dinov3 raster scale={resolved_dense_raster_scale} explicit "
                "(camera aspect kept; processor still square-resizes)",
                flush=True,
            )
    score_resolution = gpu_score_raster_resolution(
        proxy_resolution,
        chroma_weight=float(chroma_weight),
        chroma_resolution=None if needs_dense_rgb else chroma_resolution,
        chroma_scale=int(resolved_dense_raster_scale if needs_dense_rgb else chroma_scale),
        rgb_upsample=needs_dense_rgb,
    )
    vda_dir = (pilot / config.target_depth_dir).resolve()
    if float(depth_weight) > 0.0 and not vda_dir.is_dir():
        raise FileNotFoundError(
            f"GPU depth fit requires the Video Depth Anything cache: {vda_dir}"
        )
    gpu_config = GpuCascadeConfig(
        device="cuda",
        resolution=score_resolution,
        alpha_threshold=int(getattr(config, "proxy_target_alpha_threshold", 8)),
        root_search_enabled=bool(root_search_enabled),
        root_hypotheses=int(
            root_hypotheses
            if root_hypotheses is not None
            else getattr(config, "gpu_pose_advisor_root_hypothesis_count", 64)
        ),
        root_rotation_limit_deg=float(getattr(config, "motion_root_rotation_limit_deg", 180.0)),
        root_rotation_first_frame_limit_deg=float(root_rotation_first_frame_limit_deg),
        root_rotation_per_frame_limit_deg=float(root_rotation_per_frame_limit_deg),
        root_rotation_camera_up_limit_deg=float(root_rotation_camera_up_limit_deg),
        root_rotation_defer_camera_up=bool(root_rotation_defer_camera_up),
        root_rotation_after_joints_yaw_enabled=bool(root_rotation_after_joints_yaw_enabled),
        root_rotation_axes=tuple(str(axis) for axis in root_rotation_axes),
        root_translation_axes=tuple(str(axis) for axis in root_translation_axes),
        root_translation_limit_body_lengths=float(root_translation_limit_body_lengths),
        root_translation_radius_body_lengths=float(root_translation_radius_body_lengths),
        seed_previous_frame=bool(seed_previous_frame),
        root_iterations=(
            0
            if dinov3_only
            else (
                int(root_iterations)
                if root_iterations is not None
                else int(getattr(config, "clip_rounds", 1)) * 20
            )
        ),
        articulated_iterations=(
            int(articulated_iterations)
            if articulated_iterations is not None
            else int(getattr(config, "clip_adaptive_rounds", 1)) * 2
        ),
        fine_iterations=(
            int(fine_iterations)
            if fine_iterations is not None
            else int(getattr(config, "clip_polish_rounds", 1))
        ),
        joint_limit_deg=float(getattr(config, "joint_free_deg", 150.0)),
        joint_search_axes=tuple(str(axis) for axis in joint_search_axes),
        joint_diagonal_axes=int(joint_diagonal_axes),
        joint_step_deg=float(joint_step_deg),
        fine_joint_step_deg=float(fine_joint_step_deg),
        joint_adaptive_step_enabled=bool(joint_adaptive_step_enabled),
        joint_step_score_coarse=float(joint_step_score_coarse),
        joint_step_score_fine=float(joint_step_score_fine),
        joint_step_score_norm=str(joint_step_score_norm),
        joint_score_raster_batch=int(joint_score_raster_batch),
        cheap_joint_probe_occupancy_only=bool(cheap_joint_probe_occupancy_only),
        cheap_joint_probe_frame_count=int(cheap_joint_probe_frame_count),
        joint_pass_limit_deg=float(joint_pass_limit_deg),
        fine_joint_pass_limit_deg=float(fine_joint_pass_limit_deg),
        joint_probe_rungs=int(joint_probe_rungs),
        joint_round_followup_neighbors=bool(joint_round_followup_neighbors),
        joint_absolute_gain_weight=float(joint_absolute_gain_weight),
        joint_unique_gain_weight=float(joint_unique_gain_weight),
        fine_unique_gain_weight=float(fine_unique_gain_weight),
        joint_keep_still_sprite_lock=bool(joint_keep_still_sprite_lock),
        joint_keep_still_sprite_rgb_mad=float(joint_keep_still_sprite_rgb_mad),
        joint_keep_sprite_change_gate=bool(joint_keep_sprite_change_gate),
        joint_keep_sprite_change_weight=float(joint_keep_sprite_change_weight),
        joint_keep_sprite_change_slack=float(joint_keep_sprite_change_slack),
        joint_collision_positive_abs_slack=float(joint_collision_positive_abs_slack),
        joint_temporal_consensus_enabled=bool(joint_temporal_consensus_enabled),
        joint_temporal_consensus_tie_bonus=float(joint_temporal_consensus_tie_bonus),
        joint_temporal_consensus_bidirectional=bool(joint_temporal_consensus_bidirectional),
        joint_temporal_consensus_idle_end=bool(joint_temporal_consensus_idle_end),
        joint_temporal_consensus_independent_passes=bool(joint_temporal_consensus_independent_passes),
        joint_temporal_consensus_whole_pose=bool(joint_temporal_consensus_whole_pose),
        idle_prefix_frames=idle_prefix,
        idle_suffix_frames=idle_suffix,
        idle_end_anchor=bool(idle_end),
        idle_suffix_mirror_prefix_enabled=bool(idle_suffix_mirror_prefix_enabled),
        gradient_ladder_enabled=bool(gradient_ladder_enabled),
        gradient_ladder_iterations=int(gradient_ladder_iterations),
        gradient_ladder_step_degs=tuple(float(value) for value in gradient_ladder_step_degs),
        gradient_ladder_min_gradient_norm=float(gradient_ladder_min_gradient_norm),
        joint_solver_mode=str(joint_solver_mode),
        chain_space_enabled=bool(chain_space_enabled),
        chain_space_mode=str(chain_space_mode),
        chain_space_iterations=int(chain_space_iterations),
        chain_space_step_degs=tuple(float(value) for value in chain_space_step_degs),
        chain_space_min_gradient_norm=float(chain_space_min_gradient_norm),
        chain_space_trust_radius_deg=float(chain_space_trust_radius_deg),
        chain_space_trust_radius_min_deg=float(chain_space_trust_radius_min_deg),
        chain_space_trust_radius_max_deg=float(chain_space_trust_radius_max_deg),
        chain_space_min_clip_improvement=float(chain_space_min_clip_improvement),
        chain_space_eval_budget=(
            None if chain_space_eval_budget is None else int(chain_space_eval_budget)
        ),
        sa_enabled=bool(sa_enabled),
        sa_restarts=int(sa_restarts),
        sa_iterations=int(sa_iterations),
        sa_initial_temperature=float(sa_initial_temperature),
        sa_final_temperature=float(sa_final_temperature),
        sa_perturbation_scale_deg=float(sa_perturbation_scale_deg),
        sa_bone_fraction=float(sa_bone_fraction),
        sa_seed=sa_seed if sa_seed is None else int(sa_seed),
        sa_seed_from_current=bool(sa_seed_from_current),
        sa_min_bone_depth=int(sa_min_bone_depth),
        sa_collision_weight=(
            None if sa_collision_weight is None else float(sa_collision_weight)
        ),
        physics_smooth_enabled=bool(physics_smooth_enabled),
        physics_smooth_outlier_window=int(physics_smooth_outlier_window),
        physics_smooth_outlier_sigma=float(physics_smooth_outlier_sigma),
        physics_smooth_outlier_min_deg=float(physics_smooth_outlier_min_deg),
        physics_smooth_outlier_min_translation=float(physics_smooth_outlier_min_translation),
        physics_smooth_stiffness=float(physics_smooth_stiffness),
        physics_smooth_dt=float(physics_smooth_dt),
        physics_smooth_substeps=int(physics_smooth_substeps),
        physics_smooth_gravity=float(physics_smooth_gravity),
        physics_smooth_gravity_weight=float(physics_smooth_gravity_weight),
        physics_smooth_gravity_min_bone_depth=int(physics_smooth_gravity_min_bone_depth),
        physics_smooth_root_vertical_axis=int(physics_smooth_root_vertical_axis),
        physics_smooth_world_up=tuple(float(axis) for axis in physics_smooth_world_up),
        sprite_aligned_motion_keep_enabled=bool(sprite_aligned_motion_keep_enabled),
        sprite_aligned_motion_keep_min_improvement=float(
            sprite_aligned_motion_keep_min_improvement
        ),
        score_escape_enabled=bool(score_escape_enabled),
        score_escape_threshold=float(score_escape_threshold),
        score_escape_mode=str(score_escape_mode),
        score_escape_coarse_push_coarse=float(score_escape_coarse_push_coarse),
        score_escape_coarse_push_fine=float(score_escape_coarse_push_fine),
        score_escape_root_window_deg=float(score_escape_root_window_deg),
        score_escape_root_step_deg=float(score_escape_root_step_deg),
        score_escape_sa_restarts=int(score_escape_sa_restarts),
        score_escape_sa_iterations=int(score_escape_sa_iterations),
        score_escape_sa_perturbation_deg=float(score_escape_sa_perturbation_deg),
        score_escape_sa_bone_fraction=float(score_escape_sa_bone_fraction),
        score_escape_max_rounds=int(score_escape_max_rounds),
        score_escape_min_improvement=float(score_escape_min_improvement),
        score_escape_worst_frame_count=int(score_escape_worst_frame_count),
        score_escape_worst_frame_collision_weight=float(
            score_escape_worst_frame_collision_weight
        ),
        score_escape_keep_best=bool(score_escape_keep_best),
        score_escape_fail_fast=bool(score_escape_fail_fast),
        score_escape_root_held_abort=int(score_escape_root_held_abort),
        score_escape_threshold_uses_hybrid_mean=bool(
            score_escape_threshold_uses_hybrid_mean
        ),
        score_escape_skip_coarse_broad_when_seeded=bool(
            score_escape_skip_coarse_broad_when_seeded
        ),
        score_escape_skip_coarse_broad_below_mean=float(
            score_escape_skip_coarse_broad_below_mean
        ),
        score_escape_shared_transit_yaw_enabled=bool(
            score_escape_shared_transit_yaw_enabled
        ),
        score_escape_skip_articulated_retry_when_seeded=bool(
            score_escape_skip_articulated_retry_when_seeded
        ),
        score_escape_articulated_iterations=int(score_escape_articulated_iterations),
        score_escape_collision_burst_enabled=bool(score_escape_collision_burst_enabled),
        score_escape_collision_burst_threshold=float(
            score_escape_collision_burst_threshold
        ),
        score_escape_translation_burst_enabled=bool(score_escape_translation_burst_enabled),
        score_escape_translation_burst_mode=str(score_escape_translation_burst_mode),
        score_escape_translation_window_body_lengths=float(
            score_escape_translation_window_body_lengths
        ),
        score_escape_translation_hypotheses=int(score_escape_translation_hypotheses),
        score_escape_translation_axes=tuple(
            str(axis) for axis in score_escape_translation_axes
        ),
        score_escape_translation_wave_phase_span_rad=float(
            score_escape_translation_wave_phase_span_rad
        ),
        ik_enabled=bool(ik_enabled),
        ik_keypoints_path=resolved_ik_keypoints_path,
        ik_bone_roles_path=resolved_ik_bone_roles_path,
        ik_keypoints_source=str(ik_keypoints_source),
        ik_miss_depth_tolerance=float(ik_miss_depth_tolerance),
        ik_miss_min_component_area=int(ik_miss_min_component_area),
        ik_miss_max_pairs=int(ik_miss_max_pairs),
        ik_miss_predicted_alpha_threshold=float(ik_miss_predicted_alpha_threshold),
        ik_miss_max_tip_distance_px=float(ik_miss_max_tip_distance_px),
        ik_miss_max_centroid_distance_px=float(ik_miss_max_centroid_distance_px),
        ik_miss_max_area_ratio=float(ik_miss_max_area_ratio),
        ik_miss_min_displacement_alignment=float(ik_miss_min_displacement_alignment),
        ik_iterations=int(ik_iterations),
        ik_max_step_deg=float(ik_max_step_deg),
        ik_require_improvement=bool(ik_require_improvement),
        ik_blob_iou_target=float(ik_blob_iou_target),
        ik_proximal_min_depth=int(ik_proximal_min_depth),
        ik_proximal_max_step_deg=float(ik_proximal_max_step_deg),
        ik_max_chain_depth=int(ik_max_chain_depth),
        ik_repair_dilate_px=int(ik_repair_dilate_px),
        ik_blob_search_rounds=int(ik_blob_search_rounds),
        ik_silhouette_score_mode=str(ik_silhouette_score_mode),
        ik_job_order_mode=str(ik_job_order_mode),
        ik_step_scale_mode=str(ik_step_scale_mode),
        ik_step_displacement_ref_px=float(ik_step_displacement_ref_px),
        ik_step_scale_min=float(ik_step_scale_min),
        ik_step_scale_max=float(ik_step_scale_max),
        ik_chain_start_mode=str(ik_chain_start_mode),
        ik_chain_displacement_ref_px=float(ik_chain_displacement_ref_px),
        ik_frame_order_mode=str(ik_frame_order_mode),
        ik_influence_dominance_min=float(ik_influence_dominance_min),
        ik_dynamic_stop_enabled=bool(ik_dynamic_stop_enabled),
        anatomy_head_pin_enabled=bool(anatomy_head_pin_enabled),
        anatomy_head_pin_parts=tuple(str(part) for part in anatomy_head_pin_parts),
        anatomy_head_pin_bone_roles_path=str(anatomy_head_pin_bone_roles_path or ""),
        anatomy_head_pin_chain_bones=tuple(str(bone) for bone in anatomy_head_pin_chain_bones),
        anatomy_head_pin_iterations=int(anatomy_head_pin_iterations),
        anatomy_head_pin_max_step_deg=float(anatomy_head_pin_max_step_deg),
        anatomy_head_pin_require_improvement=bool(anatomy_head_pin_require_improvement),
        anatomy_head_pin_skip_idle_prefix=bool(anatomy_head_pin_skip_idle_prefix),
        anatomy_head_pin_accept_metric=str(anatomy_head_pin_accept_metric),
        idle_fused_macro_enabled=bool(idle_fused_macro_enabled),
        idle_fused_skip_macro_when_seeded=bool(idle_fused_skip_macro_when_seeded),
        idle_fused_skip_reroot_when_seeded=bool(idle_fused_skip_reroot_when_seeded),
        root_skip_when_seeded=bool(root_skip_when_seeded),
        articulated_skip_when_seeded=bool(articulated_skip_when_seeded),
        idle_fused_importance_mode=str(idle_fused_importance_mode),
        idle_fused_worst_frame_count=int(idle_fused_worst_frame_count),
        idle_fused_top_bone_count=int(idle_fused_top_bone_count),
        idle_fused_macro_chain_count=int(idle_fused_macro_chain_count),
        idle_fused_root_window_deg=float(idle_fused_root_window_deg),
        idle_fused_root_step_deg=float(idle_fused_root_step_deg),
        idle_fused_macro_step_deg=float(idle_fused_macro_step_deg),
        idle_fused_macro_root_rotation_axes=(
            None
            if idle_fused_macro_root_rotation_axes is None
            else tuple(str(axis) for axis in idle_fused_macro_root_rotation_axes)
        ),
        idle_fused_per_frame_root_enabled=bool(idle_fused_per_frame_root_enabled),
        idle_fused_per_frame_root_count=int(idle_fused_per_frame_root_count),
        idle_fused_shared_transit_yaw_enabled=bool(idle_fused_shared_transit_yaw_enabled),
        idle_fused_shared_transit_yaw_window_deg=float(
            idle_fused_shared_transit_yaw_window_deg
        ),
        idle_fused_shared_transit_yaw_step_deg=float(
            idle_fused_shared_transit_yaw_step_deg
        ),
        idle_fused_shared_transit_yaw_bone_adapt_rounds=int(
            idle_fused_shared_transit_yaw_bone_adapt_rounds
        ),
        idle_fused_shared_transit_yaw_bone_adapt_top_bones=int(
            idle_fused_shared_transit_yaw_bone_adapt_top_bones
        ),
        idle_fused_shared_transit_yaw_post_articulated_iterations=int(
            idle_fused_shared_transit_yaw_post_articulated_iterations
        ),
        idle_fused_shared_transit_yaw_ignore_motion=bool(
            idle_fused_shared_transit_yaw_ignore_motion
        ),
        idle_fused_shared_transit_yaw_pre_articulated=bool(
            idle_fused_shared_transit_yaw_pre_articulated
        ),
        idle_fused_shared_transit_yaw_post_articulated=bool(
            idle_fused_shared_transit_yaw_post_articulated
        ),
        live_status_path=str(live_status_path or ""),
        idle_fused_reroot_transit_after_articulated=bool(
            idle_fused_reroot_transit_after_articulated
        ),
        idle_fused_reroot_all_transit=bool(idle_fused_reroot_all_transit),
        base_pose_enabled=bool(base_pose_enabled),
        base_pose_iterations=int(base_pose_iterations),
        mid_pose_enabled=bool(mid_pose_enabled),
        mid_pose_iterations=int(mid_pose_iterations),
        mid_joint_step_deg=float(mid_joint_step_deg),
        root_refit_after_base_enabled=bool(root_refit_after_base_enabled),
        root_refit_translation_body_lengths=float(root_refit_translation_body_lengths),
        root_refit_translation_step_body_lengths=float(root_refit_translation_step_body_lengths),
        root_refit_rotation_deg=float(root_refit_rotation_deg),
        root_refit_rotation_step_deg=float(root_refit_rotation_step_deg),
        articulated_root_interleave_enabled=bool(articulated_root_interleave_enabled),
        articulated_root_interleave_rotation_deg=float(
            articulated_root_interleave_rotation_deg
        ),
        articulated_root_interleave_rotation_step_deg=float(
            articulated_root_interleave_rotation_step_deg
        ),
        articulated_root_interleave_include_translation=bool(
            articulated_root_interleave_include_translation
        ),
        articulated_root_interleave_policy=str(articulated_root_interleave_policy),
        articulated_root_interleave_primary_groups=tuple(
            str(name) for name in articulated_root_interleave_primary_groups
        ),
        articulated_multi_bone_enabled=bool(articulated_multi_bone_enabled),
        articulated_multi_bone_block_size=int(articulated_multi_bone_block_size),
        articulated_funnel_enabled=bool(articulated_funnel_enabled),
        articulated_funnel_broad_step_deg=float(articulated_funnel_broad_step_deg),
        articulated_funnel_broad_probe_rungs=int(articulated_funnel_broad_probe_rungs),
        articulated_funnel_broad_rounds=int(articulated_funnel_broad_rounds),
        articulated_funnel_broad_min_improvement=float(
            articulated_funnel_broad_min_improvement
        ),
        articulated_funnel_force_gradient_order=bool(
            articulated_funnel_force_gradient_order
        ),
        articulated_funnel_broad_multi_bone_block_size=int(
            articulated_funnel_broad_multi_bone_block_size
        ),
        articulated_funnel_worst_frame_keep_enabled=bool(
            articulated_funnel_worst_frame_keep_enabled
        ),
        articulated_funnel_worst_frame_keep_count=int(
            articulated_funnel_worst_frame_keep_count
        ),
        articulated_funnel_worst_frame_keep_weight=float(
            articulated_funnel_worst_frame_keep_weight
        ),
        anatomy_groups_catalog_path=str(anatomy_groups_catalog_path or ""),
        anatomy_group_visit_order=tuple(str(name) for name in anatomy_group_visit_order),
        anatomy_veto_enabled=bool(anatomy_veto_enabled),
        anatomy_veto_strain_enabled=bool(anatomy_veto_strain_enabled),
        anatomy_veto_collision_enabled=bool(anatomy_veto_collision_enabled),
        anatomy_veto_prop_enabled=bool(anatomy_veto_prop_enabled),
        anatomy_veto_strain_tolerance=float(anatomy_veto_strain_tolerance),
        anatomy_veto_strain_exclusive_weight=float(anatomy_veto_strain_exclusive_weight),
        anatomy_veto_strain_min_rest_length_body_lengths=float(
            anatomy_veto_strain_min_rest_length_body_lengths
        ),
        anatomy_veto_strain_slack=float(anatomy_veto_strain_slack),
        anatomy_veto_collision_slack=float(anatomy_veto_collision_slack),
        anatomy_veto_prop_slack_px=float(anatomy_veto_prop_slack_px),
        anatomy_veto_hard_strain_margin=float(anatomy_veto_hard_strain_margin),
        anatomy_veto_hard_collision_margin=float(anatomy_veto_hard_collision_margin),
        anatomy_veto_hard_prop_margin_px=float(anatomy_veto_hard_prop_margin_px),
        anatomy_veto_dino_tie_band=float(anatomy_veto_dino_tie_band),
        anatomy_veto_soft_weight=float(anatomy_veto_soft_weight),
        anatomy_veto_bone_roles_path=str(anatomy_veto_bone_roles_path or ""),
        anatomy_veto_prop_coords_path=str(anatomy_veto_prop_coords_path or ""),
        early_symmetry_enabled=bool(early_symmetry_enabled),
        early_symmetry_visit_limit=int(early_symmetry_visit_limit),
        early_symmetry_bilateral_group_pairs=tuple(
            tuple(str(part) for part in pair)
            for pair in early_symmetry_bilateral_group_pairs
        ),
        early_symmetry_central_groups=tuple(
            str(name) for name in early_symmetry_central_groups
        ),
        early_symmetry_central_joint_axes=tuple(
            str(axis) for axis in early_symmetry_central_joint_axes
        ),
        branch_rescue_enabled=bool(branch_rescue_enabled),
        branch_rescue_block_size=int(branch_rescue_block_size),
        branch_rescue_values_per_bone=int(branch_rescue_values_per_bone),
        skip_tiny_bones=bool(skip_tiny_bones),
        min_leaf_length_frac=float(min_leaf_length_frac),
        fine_only_leaf_length_frac=float(fine_only_leaf_length_frac),
        bone_order_mode=str(bone_order_mode),
        search_bones=tuple(str(name) for name in search_bones),
        include_unlisted_search_bones=bool(include_unlisted_search_bones),
        bone_limit_scale_overrides=validate_bone_limit_scale_overrides(bone_limit_scale_overrides),
        # Discrete root_search is the ±big hypothesis stage. Interleaved root
        # micro-steps, deferred after-joint yaw, and idle-fused / score-escape
        # root bursts need optimize_root_* without that stage.
        optimize_root_translation=bool(root_search_enabled)
        or (
            bool(articulated_root_interleave_enabled)
            and bool(articulated_root_interleave_include_translation)
        )
        or bool(idle_fused_macro_enabled)
        or bool(idle_fused_reroot_transit_after_articulated)
        or bool(score_escape_enabled),
        optimize_root_rotation=cascade_optimize_root_rotation(
            root_search_enabled=root_search_enabled,
            articulated_root_interleave_enabled=articulated_root_interleave_enabled,
            idle_fused_macro_enabled=idle_fused_macro_enabled,
            idle_fused_reroot_transit_after_articulated=idle_fused_reroot_transit_after_articulated,
            score_escape_enabled=score_escape_enabled,
            root_rotation_defer_camera_up=root_rotation_defer_camera_up,
        ),
        optimize_bones=True,
        freeze_root_after_root_stage=bool(freeze_root_after_root_stage),
        fine_root_enabled=bool(fine_root_enabled),
        exact_raster_enabled=True,
        depth_target_dir=(vda_dir if vda_dir.is_dir() else None),
        depth_weight=float(depth_weight),
        silhouette_weight=float(silhouette_weight),
        depth_tolerance=float(depth_tolerance),
        depth_robust_delta=float(depth_robust_delta),
        chroma_weight=float(chroma_weight),
        motion_weight=float(motion_weight),
        motion_exempt_idle_prefix=bool(motion_exempt_idle_prefix),
        temporal_scoring_mode=str(temporal_scoring_mode),
        velocity_weight=(
            float(velocity_weight)
            if velocity_weight is not None
            else GpuCascadeConfig.velocity_weight
        ),
        acceleration_weight=(
            float(acceleration_weight)
            if acceleration_weight is not None
            else GpuCascadeConfig.acceleration_weight
        ),
        root_velocity_weight=(
            float(root_velocity_weight)
            if root_velocity_weight is not None
            else GpuCascadeConfig.root_velocity_weight
        ),
        root_acceleration_weight=(
            float(root_acceleration_weight)
            if root_acceleration_weight is not None
            else GpuCascadeConfig.root_acceleration_weight
        ),
        root_rotation_velocity_weight=(
            float(root_rotation_velocity_weight)
            if root_rotation_velocity_weight is not None
            else GpuCascadeConfig.root_rotation_velocity_weight
        ),
        root_rotation_acceleration_weight=(
            float(root_rotation_acceleration_weight)
            if root_rotation_acceleration_weight is not None
            else GpuCascadeConfig.root_rotation_acceleration_weight
        ),
        bone_pose_prior_weight=(
            float(bone_pose_prior_weight)
            if bone_pose_prior_weight is not None
            else GpuCascadeConfig.bone_pose_prior_weight
        ),
        root_translation_prior_weight=(
            float(root_translation_prior_weight)
            if root_translation_prior_weight is not None
            else GpuCascadeConfig.root_translation_prior_weight
        ),
        root_rotation_prior_weight=(
            float(root_rotation_prior_weight)
            if root_rotation_prior_weight is not None
            else GpuCascadeConfig.root_rotation_prior_weight
        ),
        chroma_tolerance=float(chroma_tolerance),
        chroma_robust_delta=float(chroma_robust_delta),
        chroma_error_scale=float(chroma_error_scale),
        chroma_scale=int(chroma_scale),
        chroma_resolution=chroma_resolution,
        score_mode=str(score_mode),
        dense_semantic_model_id=str(dense_semantic_model_id),
        dense_semantic_feature_layers=tuple(str(layer) for layer in dense_semantic_feature_layers),
        dense_semantic_local_radius=int(dense_semantic_local_radius),
        dense_semantic_position_weight=float(dense_semantic_position_weight),
        dense_semantic_autograd_enabled=bool(dense_semantic_autograd_enabled),
        dense_semantic_batch_size=int(dense_semantic_batch_size),
        dense_semantic_raster_scale=int(resolved_dense_raster_scale),
        dense_semantic_subject_crop=bool(dense_semantic_subject_crop),
        dense_semantic_subject_padding_frac=float(dense_semantic_subject_padding_frac),
        collision_enabled=bool(collision_enabled),
        collision_sample_count=int(collision_sample_count),
        collision_geodesic_min_hops=int(collision_geodesic_min_hops),
        collision_margin_body_lengths=float(collision_margin_body_lengths),
        collision_weight=float(collision_weight) if bool(collision_enabled) else 0.0,
        score_centroid_weight=0.0,
        score_occupancy_weight=0.0,
        sdf_weight=0.0,
        return_masks=False,
    )
    gpu_config.validate()
    if bool(config_only):
        return gpu_config
    out = (output_dir or (pilot / "gpu_depth_fit")).resolve()

    def _profile_init_hook(run_dir: Path, seed_camera: Path):
        from gpu_depth_silhouette_solver import (
            _discover_idle_profile_target_dir,
            _resolve_profile_init_resolution,
        )
        from gpu_profile_camera_initializer import PROFILE_FACING_WEIGHT, ProfileCameraInitConfig, initialize_profile_camera

        if not bool(profile_init_enabled):
            raise RuntimeError("profile_init_hook ran while profile_init_enabled is False")
        explicit_init_target = profile_init_target_dir is not None
        init_target_dir = target if not explicit_init_target else Path(profile_init_target_dir)
        if not init_target_dir.is_absolute():
            init_target_dir = (pilot / init_target_dir).resolve()
        if not explicit_init_target:
            init_target_dir = _discover_idle_profile_target_dir(config, pilot, target)
        fit_target_dir = target
        if profile_init_fit_target_dir is not None:
            fit_target_dir = Path(profile_init_fit_target_dir)
            if not fit_target_dir.is_absolute():
                fit_target_dir = (pilot / fit_target_dir).resolve()
        init_frame = int(
            0 if profile_init_frame is None and init_target_dir != target else
            frame_indices[0] if profile_init_frame is None else profile_init_frame
        )
        profile_resolution = _resolve_profile_init_resolution(
            init_target_dir,
            init_frame,
            profile_init_resolution,
            int(profile_init_max_dimension),
            tuple(int(value) for value in proxy_resolution),
        )
        initialization = initialize_profile_camera(
            src_glb=Path(config.src_glb).resolve(),
            seed_camera_fit=seed_camera,
            target_frame_dir=init_target_dir,
            fit_target_frame_dir=fit_target_dir,
            frame_index=init_frame,
            output_dir=run_dir / "initialization",
            config=ProfileCameraInitConfig(
                resolution=profile_resolution,
                alpha_threshold=int(getattr(config, "proxy_target_alpha_threshold", 8)),
                predicted_alpha_threshold=0.01,
                yaw_min_deg=float(profile_init_yaw_min_deg),
                yaw_max_deg=float(profile_init_yaw_max_deg),
                yaw_step_deg=float(profile_init_yaw_step_deg),
                roll_range_deg=float(profile_init_roll_range_deg),
                roll_step_deg=float(profile_init_roll_step_deg),
                fit_margin=float(profile_init_fit_margin),
                top_k=int(profile_init_top_k),
                camera_basis_mode=str(profile_init_camera_basis_mode),
                world_up_axis=tuple(float(value) for value in profile_init_world_up_axis),
                facing_weight=(
                    float(PROFILE_FACING_WEIGHT)
                    if profile_init_facing_weight is None
                    else float(profile_init_facing_weight)
                ),
                rank_metric=(
                    "composite"
                    if profile_init_rank_metric is None
                    else str(profile_init_rank_metric)
                ),
            ),
            progress=True,
        )
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        return initialization.camera_fit_path, initialization

    return solve_gpu_depth_animation(
        src_glb=Path(config.src_glb).resolve(),
        camera_fit=camera,
        target_frame_dir=target,
        frame_indices=frame_indices,
        config=gpu_config,
        output_dir=out,
        vda_depth_dir=vda_dir if vda_dir.is_dir() else None,
        render_blender=False,
        profile_init_hook=_profile_init_hook if bool(profile_init_enabled) else None,
        initial_poses=initial_poses,
        live_preview=live_preview,
        preview_every=preview_every,
        live_preview_scale=int(live_preview_scale),
    )
