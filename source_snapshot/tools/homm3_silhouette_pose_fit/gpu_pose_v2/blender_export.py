"""Final Blender render bridge for the V2 canonical pose contract.

Blender is intentionally outside the optimizer.  This module consumes the
same FK/LBS deformation matrices used by the CUDA renderer, renders only the
accepted keyframes/interpolated poses, and records a parity report against the
CUDA alpha buffers.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch
from PIL import Image

from roc_gpu_cascade_experiment import GLTF_TO_BLENDER_BASIS, _GpuPreviewWorker
from pose_fit_blender import resolve_pose_fit_blender

from .bridge import compare_alpha_masks
from .contracts import CameraSpec, ExperimentResult, PoseState
from .renderer import ExactCudaRenderer
from .session import ExperimentSession


def _rotvec_to_quaternion(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype=np.float64)
    angle = np.linalg.norm(value, axis=-1, keepdims=True)
    safe = np.maximum(angle, 1e-12)
    axis = value / safe
    half = angle * 0.5
    result = np.concatenate((np.cos(half), axis * np.sin(half)), axis=-1)
    identity = np.zeros_like(result)
    identity[..., 0] = 1.0
    return np.where(angle > 1e-10, result, identity)


def _quaternion_to_rotvec(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype=np.float64)
    value = value / np.maximum(np.linalg.norm(value, axis=-1, keepdims=True), 1e-12)
    sign = np.where(value[..., :1] < 0.0, -1.0, 1.0)
    value = value * sign
    w = np.clip(value[..., :1], -1.0, 1.0)
    xyz = value[..., 1:]
    angle = 2.0 * np.arccos(w)
    scale = angle / np.maximum(np.linalg.norm(xyz, axis=-1, keepdims=True), 1e-12)
    result = xyz * scale
    return np.where(angle > 1e-10, result, np.zeros_like(result))


def _quaternion_slerp(left: np.ndarray, right: np.ndarray, fraction: float) -> np.ndarray:
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    dot = np.sum(left * right, axis=-1, keepdims=True)
    right = np.where(dot < 0.0, -right, right)
    dot = np.clip(np.sum(left * right, axis=-1, keepdims=True), -1.0, 1.0)
    theta = np.arccos(dot)
    sin_theta = np.sin(theta)
    linear = left + float(fraction) * (right - left)
    a = np.sin((1.0 - float(fraction)) * theta) / np.maximum(sin_theta, 1e-8)
    b = np.sin(float(fraction) * theta) / np.maximum(sin_theta, 1e-8)
    result = a * left + b * right
    result = np.where(sin_theta < 1e-6, linear, result)
    return result / np.maximum(np.linalg.norm(result, axis=-1, keepdims=True), 1e-12)


def _smooth_fraction(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def _interpolate_rotation(left: Any, right: Any, fraction: float, mode: str) -> np.ndarray:
    left_np = left.detach().cpu().numpy() if hasattr(left, "detach") else np.asarray(left)
    right_np = right.detach().cpu().numpy() if hasattr(right, "detach") else np.asarray(right)
    if mode == "axis_angle_linear":
        return left_np + float(fraction) * (right_np - left_np)
    effective = _smooth_fraction(fraction) if mode in {"cubic_quaternion", "motion_aware"} else fraction
    return _quaternion_to_rotvec(
        _quaternion_slerp(_rotvec_to_quaternion(left_np), _rotvec_to_quaternion(right_np), effective)
    )


def _interpolate_pose(left: PoseState, right: PoseState, fraction: float, mode: str) -> PoseState:
    mode = str(mode).lower()
    effective = _smooth_fraction(fraction) if mode in {"cubic_quaternion", "motion_aware"} else float(fraction)
    registration = left.registration.detach().clone()
    left_translation = left.motion_translation.detach().cpu().numpy()
    right_translation = right.motion_translation.detach().cpu().numpy()
    translation = left_translation + effective * (right_translation - left_translation)
    motion_rotation = _interpolate_rotation(left.motion_rotation, right.motion_rotation, fraction, mode)
    bone_rotation = _interpolate_rotation(left.bone_rotation, right.bone_rotation, fraction, mode)
    device = left.registration.device
    return PoseState(
        registration=registration,
        motion_translation=torch.as_tensor(translation, dtype=torch.float32, device=device),
        motion_rotation=torch.as_tensor(motion_rotation, dtype=torch.float32, device=device),
        bone_rotation=torch.as_tensor(bone_rotation, dtype=torch.float32, device=device),
        frame_indices=(left.frame_indices[0],),
    )


def _single_frame_pose(pose: PoseState, frame_index: int) -> PoseState:
    if pose.registration.ndim == 1:
        registration = pose.registration.unsqueeze(0)
    else:
        registration = pose.registration
    if pose.motion_translation.ndim == 2:
        motion_translation = pose.motion_translation[:, frame_index : frame_index + 1]
        motion_rotation = pose.motion_rotation[:, frame_index : frame_index + 1]
    else:
        motion_translation = pose.motion_translation[:, frame_index : frame_index + 1]
        motion_rotation = pose.motion_rotation[:, frame_index : frame_index + 1]
    bone_rotation = pose.bone_rotation[:, frame_index : frame_index + 1]
    return PoseState(
        registration=registration,
        motion_translation=motion_translation,
        motion_rotation=motion_rotation,
        bone_rotation=bone_rotation,
        frame_indices=(pose.frame_indices[frame_index],),
    )


def _interpolated_poses(
    pose: PoseState,
    *,
    source_fps: float,
    output_fps: float,
    frame_durations: tuple[float, ...] | None = None,
    mode: str,
    loop: bool,
) -> tuple[list[PoseState], list[int]]:
    if source_fps <= 0.0 or output_fps <= 0.0:
        raise ValueError("source_fps and output_fps must be positive")
    frame_count = len(pose.frame_indices)
    if frame_count == 0:
        raise ValueError("cannot interpolate an empty pose")
    source = [_single_frame_pose(pose, index) for index in range(frame_count)]
    result: list[PoseState] = []
    keyframe_outputs: list[int] = []
    segment_count = frame_count if loop else max(0, frame_count - 1)
    if frame_durations is not None:
        durations = tuple(float(value) for value in frame_durations)
        if len(durations) != frame_count or any(value <= 0.0 for value in durations):
            raise ValueError("frame_durations must contain one positive duration per source keyframe")
        segment_steps = [max(1, int(round(durations[index] * float(output_fps)))) for index in range(segment_count)]
    else:
        fixed_steps = max(1, int(round(float(output_fps) / float(source_fps))))
        segment_steps = [fixed_steps] * segment_count
    for index in range(segment_count):
        left = source[index]
        right = source[(index + 1) % frame_count]
        keyframe_outputs.append(len(result))
        steps = segment_steps[index]
        for subframe in range(steps):
            result.append(_interpolate_pose(left, right, subframe / steps, mode))
    if not loop:
        keyframe_outputs.append(len(result))
        result.append(source[-1])
    return result, keyframe_outputs


def _write_mp4(paths: Iterable[Path], destination: Path, fps: float) -> None:
    try:
        import cv2
    except Exception as exc:
        raise RuntimeError("V2 Blender export requires OpenCV to write the 60 fps MP4") from exc
    paths = list(paths)
    if not paths:
        raise ValueError("cannot write an empty MP4")
    with Image.open(paths[0]) as first:
        width, height = first.size
    writer = cv2.VideoWriter(
        str(destination),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(fps),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open the V2 MP4 writer: {destination}")
    try:
        for path in paths:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError(f"could not read Blender render for MP4: {path}")
            writer.write(frame)
    finally:
        writer.release()


def _blender_basis_matrix() -> np.ndarray:
    basis = np.eye(4, dtype=np.float64)
    basis[:3, :3] = GLTF_TO_BLENDER_BASIS
    return basis


def export_blender_60fps(
    session: ExperimentSession,
    result: ExperimentResult,
    *,
    output_dir: str | Path | None = None,
    output_fps: float | None = None,
    interpolation_mode: str | None = None,
    loop: bool | None = None,
) -> dict[str, Any]:
    """Render the selected V2 pose with Blender and run the alpha parity gate."""
    fit = session.camera_fit_path
    if fit is None or not fit.is_file():
        raise FileNotFoundError("V2 Blender export requires the selected camera fit path")
    mesh = session.rig.path
    blender = resolve_pose_fit_blender()
    worker_script = Path(__file__).resolve().parent.parent / "roc_chroma_match_worker.py"
    if not worker_script.is_file():
        raise FileNotFoundError(f"Blender worker is missing: {worker_script}")

    out = Path(output_dir or (session.artifact_dir / "blender_60fps")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fps = float(output_fps or session.config.interpolation_output_fps)
    mode = str(interpolation_mode or session.config.interpolation_mode).lower()
    should_loop = bool(session.config.interpolation_loop if loop is None else loop)
    interpolated, keyframe_outputs = _interpolated_poses(
        result.selected.pose,
        source_fps=session.clip.source_fps,
        output_fps=fps,
        frame_durations=session.clip.frame_durations,
        mode=mode,
        loop=should_loop,
    )
    fit_value = json.loads(fit.read_text(encoding="utf-8"))
    source_resolution = fit_value.get("sourceResolution", [session.camera.width, session.camera.height])
    render_scale = float(session.config.blender_render_scale)
    render_width = max(64, int(round(float(source_resolution[0]) * render_scale)))
    render_height = max(64, int(round(float(source_resolution[1]) * render_scale)))
    # Compare at Blender's actual render resolution instead of resizing a
    # low-resolution optimizer mask with nearest-neighbour pixels. This keeps
    # the parity oracle about camera/deformation agreement rather than about a
    # second, unrelated downsampling filter.
    parity_camera = CameraSpec.from_mapping(fit_value, width=render_width, height=render_height)
    parity_renderer = ExactCudaRenderer(session.rig, parity_camera, antialias=session.config.raster_antialias)
    gpu_keyframe_alpha = parity_renderer.render_single(result.selected.pose).alpha[0].detach().cpu().numpy()
    renderer = ExactCudaRenderer(session.rig, session.camera, antialias=session.config.raster_antialias)

    init_command = {
        "cmd": "init",
        "src": str(mesh),
        "fit": str(fit),
        "autoFrame0Fit": False,
        # Blender's orthographic camera has one world-units-per-pixel scale.
        # Render at the fit's native aspect ratio, then compare/preview after
        # the same anisotropic target resize used by PreparedClip.  Rendering
        # directly at the square-ish optimizer resolution would change the
        # camera's vertical scale and make a false parity failure.
        "width": render_width,
        "height": render_height,
        "searchScale": 1.0,
        # canonical_deformation_matrices already includes the global scale;
        # applying it again through the worker would double-scale the mesh.
        "meshScale": 1.0,
        "useDeformPreserveVolume": False,
        "semanticMultiview": False,
        "searchEngine": "BLENDER_WORKBENCH",
        "searchTaaSamples": 1,
        "proofEngine": "BLENDER_EEVEE",
        "proofTaaSamples": 8,
        "lightingMode": str(session.config.blender_lighting_mode),
        "sunEnergy": float(session.config.blender_sun_energy),
        "sunAzimuthDeg": float(session.config.blender_sun_azimuth_deg),
        "sunElevationDeg": float(session.config.blender_sun_elevation_deg),
        "sunAngleDeg": float(session.config.blender_sun_angle_deg),
        "scoreMode": "depth",
        "renderDepth": False,
        "renderResultInMemory": False,
        "renderPngCompression": 0,
        "incrementalPoseApplication": False,
        "motionRootEnabled": False,
        "motionRootRotationEnabled": False,
        "honorFitScreenOffset": True,
        "fitCoordinateBasis": "gltf_yup_to_blender_zup",
        "detectProfile": False,
        "meshOrientationMode": "none",
        "stripBoneRoll": False,
    }

    worker = _GpuPreviewWorker(blender=blender, worker_script=worker_script)
    frame_paths: list[Path] = []
    try:
        init_result = worker.request(init_command)
        if not init_result.get("ok"):
            raise RuntimeError({"ok": False, "error": "V2 Blender init failed", "result": init_result})
        for output_index, frame_pose in enumerate(interpolated):
            matrices = renderer.canonical_deformation_matrices(frame_pose, frame_index=0)
            set_result = worker.request({
                "cmd": "set_pose",
                "angles": {},
                "boneDeformationMatrices": {
                    name: (_blender_basis_matrix() @ np.asarray(matrix, dtype=np.float64) @ _blender_basis_matrix().T).tolist()
                    for name, matrix in matrices.items()
                },
            })
            if not set_result.get("ok"):
                raise RuntimeError({"ok": False, "error": "V2 Blender set_pose failed", "result": set_result})
            path = out / f"frame_{output_index:04d}.png"
            save_result = worker.request({"cmd": "save_render", "out": str(path)})
            if not save_result.get("ok") or not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError({"ok": False, "error": "V2 Blender render was not written", "result": save_result, "path": str(path)})
            frame_paths.append(path)
    finally:
        worker.close()

    gif_path = out / "gpu_pose_v2_rendered_60fps.gif"
    images = [Image.open(path).convert("RGB") for path in frame_paths]
    try:
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=max(1, round(1000.0 / fps)),
            loop=0,
            optimize=False,
        )
    finally:
        for image in images:
            image.close()
    mp4_path = out / "gpu_pose_v2_rendered_60fps.mp4"
    _write_mp4(frame_paths, mp4_path, fps)

    keyframe_paths = [frame_paths[index] for index in keyframe_outputs[: len(gpu_keyframe_alpha)]]
    parity = compare_alpha_masks(gpu_keyframe_alpha, keyframe_paths)
    manifest = {
        "schemaVersion": 2,
        "source": "V2 canonical PoseState; Blender final lit render",
        "mesh": str(mesh),
        "cameraFit": str(fit),
        "sourceFrames": list(session.clip.frame_indices),
        "sourceFps": float(session.clip.source_fps),
        "frameDurations": list(session.clip.frame_durations),
        "outputFps": fps,
        "interpolationMode": mode,
        "loop": should_loop,
        "renderResolution": [render_width, render_height],
        "framePaths": [str(path) for path in frame_paths],
        "keyframeFramePaths": [str(path) for path in keyframe_paths],
        "parity": parity,
    }
    manifest_path = out / "blender_parity_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "gif": str(gif_path),
        "mp4": str(mp4_path),
        "framePaths": [str(path) for path in frame_paths],
        "keyframeFramePaths": [str(path) for path in keyframe_paths],
        "parity": parity,
        "manifest": str(manifest_path),
    }


def require_blender_parity(export_result: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when the Blender render is not the same geometry as CUDA."""
    parity = export_result.get("parity")
    if not isinstance(parity, dict) or not parity.get("ok"):
        raise RuntimeError({"ok": False, "error": "V2 Blender parity gate failed", "parity": parity, "manifest": export_result.get("manifest")})
    return parity
