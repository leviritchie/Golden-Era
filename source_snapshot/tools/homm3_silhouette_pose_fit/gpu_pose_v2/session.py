"""Session preparation and notebook-facing display/export helpers."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .contracts import CameraSpec, ExperimentResult, PreparedClip, PreparedRig, V2Config, fingerprint_paths
from .preflight import preflight
from .rig import prepare_rig
from .targets import prepare_clip, resolve_front_perspective_paths


@dataclass(frozen=True)
class ExperimentSession:
    config: V2Config
    camera: CameraSpec
    rig: PreparedRig
    clip: PreparedClip
    artifact_dir: Path
    preflight_report: Mapping[str, Any]
    camera_fit_path: Path | None = None
    front_camera: CameraSpec | None = None

    @property
    def device(self) -> str:
        return self.config.device

    def preview(self, result: ExperimentResult, *, output_dir: str | Path | None = None) -> dict[str, Any]:
        return preview(self, result, output_dir=output_dir)

    def export(self, result: ExperimentResult) -> Path:
        return export(self, result)


def _camera_from_selection(selection: Mapping[str, Any], config: V2Config) -> CameraSpec:
    raw: Mapping[str, Any] | None = None
    path_value = selection.get("camera_fit_path") or selection.get("cameraFitPath")
    if path_value:
        path = Path(path_value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"V2 camera fit is missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, Mapping):
            raw = value.get("camera") if isinstance(value.get("camera"), Mapping) else value
    if raw is None and isinstance(selection.get("camera"), Mapping):
        raw = selection["camera"]
    return CameraSpec.from_mapping(raw, width=config.resolution[0], height=config.resolution[1])


def _front_camera_from_selection(
    selection: Mapping[str, Any],
    profile_camera: CameraSpec,
    config: V2Config,
) -> CameraSpec:
    """Build the auxiliary head-on camera without changing profile registration.

    The supplied profile camera looks along the unit's side axis.  Its screen
    right vector is therefore the approximate longitudinal axis.  Looking
    back along that axis gives a generic front/rear view; the profile camera's
    up vector supplies a stable vertical basis.  A caller may provide an
    explicit fit when a unit's generated front art uses a nonstandard view.
    """
    raw: Mapping[str, Any] | None = None
    path_value = selection.get("front_camera_fit_path") or selection.get("frontCameraFitPath")
    if path_value:
        path = Path(path_value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"front camera fit is missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, Mapping):
            raw = value.get("camera") if isinstance(value.get("camera"), Mapping) else value
    if raw is None and isinstance(selection.get("front_camera"), Mapping):
        raw = selection["front_camera"]
    if raw is not None:
        return CameraSpec.from_mapping(raw, width=config.resolution[0], height=config.resolution[1])

    def normalize(value: np.ndarray) -> np.ndarray:
        length = float(np.linalg.norm(value))
        if length <= 1e-8:
            raise ValueError("cannot derive front camera from a degenerate profile basis")
        return value / length

    up = normalize(-np.asarray(profile_camera.down, dtype=np.float64))
    forward = normalize(-np.asarray(profile_camera.right, dtype=np.float64))
    right = np.asarray(profile_camera.forward, dtype=np.float64)
    right = normalize(right - float(np.dot(right, up)) * up)
    down = -up
    scale = float(config.front_view_camera_scale)
    return CameraSpec(
        width=profile_camera.width,
        height=profile_camera.height,
        right=tuple(float(value) for value in right),
        down=tuple(float(value) for value in down),
        forward=tuple(float(value) for value in forward),
        offset=(profile_camera.width * 0.5, profile_camera.height * 0.5),
        px_per_world=tuple(float(value) * scale for value in profile_camera.px_per_world),
        near=profile_camera.near,
        far=profile_camera.far,
    )


def _fit_front_camera_scale(
    front_camera: CameraSpec,
    rig: PreparedRig,
    clip: PreparedClip,
    config: V2Config,
) -> tuple[CameraSpec, dict[str, Any]]:
    """Fit one shared front-camera scale after per-image target normalization.

    Generated perspective references have unreliable crop/zoom.  The target
    loader removes that nuisance per image; this pass then fits the mesh once
    from its bind pose to the median normalized subject extent.  Candidate
    poses are subsequently scored in this fixed camera and cannot resize
    themselves to hide a wrong articulation.
    """
    if not config.front_view_fit_camera_scale or clip.front_masks is None:
        return front_camera, {
            "enabled": False,
            "method": "disabled",
        }

    from .contracts import PoseState
    from .renderer import ExactCudaRenderer
    import torch

    def extent(mask: np.ndarray) -> float:
        ys, xs = np.where(np.asarray(mask) > 0.5)
        if len(xs) == 0:
            return 0.0
        return float(max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))

    target_extents = [extent(value) for value in np.asarray(clip.front_masks)]
    target_extents = [value for value in target_extents if value > 0.0]
    if not target_extents:
        raise ValueError("front-view normalization produced no measurable subject extent")

    renderer = ExactCudaRenderer(rig, front_camera, antialias=True)
    node_count = len(rig.node_names)
    pose = PoseState(
        registration=torch.zeros((1, 7), dtype=torch.float32, device=rig.device),
        motion_translation=torch.zeros((1, 1, 3), dtype=torch.float32, device=rig.device),
        motion_rotation=torch.zeros((1, 1, 3), dtype=torch.float32, device=rig.device),
        bone_rotation=torch.zeros((1, 1, node_count, 3), dtype=torch.float32, device=rig.device),
        frame_indices=(0,),
    )
    bind_alpha = renderer.render_single(pose).alpha[0, 0].detach().cpu().numpy()
    bind_extent = extent(bind_alpha)
    if bind_extent <= 0.0:
        raise RuntimeError("bind pose is not visible in the generated front camera; cannot fit front scale")

    target_extent = float(np.median(np.asarray(target_extents, dtype=np.float64)))
    factor = float(np.clip(target_extent / bind_extent, 0.25, 4.0))
    fitted = replace(
        front_camera,
        px_per_world=tuple(float(value) * factor for value in front_camera.px_per_world),
    )
    return fitted, {
        "enabled": True,
        "method": "bind_pose_to_median_normalized_extent",
        "targetMedianExtentPx": target_extent,
        "bindExtentPx": bind_extent,
        "scaleFactor": factor,
        "basePxPerWorld": list(front_camera.px_per_world),
        "fittedPxPerWorld": list(fitted.px_per_world),
    }


def prepare_experiment(
    selection: Mapping[str, Any],
    preset: str | V2Config = "plausible_3d",
    overrides: Mapping[str, Any] | None = None,
) -> ExperimentSession:
    """Prepare immutable rig/target caches; no optimization occurs here."""
    if isinstance(preset, V2Config):
        config = preset
        if overrides:
            config = replace(config, **dict(overrides))
    else:
        from .contracts import preset_config

        config = preset_config(str(preset), **dict(overrides or {}))
    config.validate()
    report = preflight(
        require_renderer=True,
        require_semantics=bool(config.semantic_enabled or config.dense_semantic_enabled),
        model_ids=tuple(
            value
            for enabled, value in (
                (config.semantic_enabled, config.semantic_model_id),
                (config.dense_semantic_enabled, config.dense_model_id),
            )
            if enabled and value
        ),
        local_files_only_model_ids=(
            (config.dense_model_id,)
            if config.dense_semantic_enabled and config.dense_local_files_only
            else ()
        ),
    )
    mesh = selection.get("mesh_path") or selection.get("mesh")
    source = selection.get("target_frame_dir") or selection.get("targetDir")
    if not mesh or not source:
        raise ValueError("selection must contain mesh_path and target_frame_dir")
    camera = _camera_from_selection(selection, config)
    front_camera = None
    front_paths: list[Path] = []
    if config.front_view_enabled:
        front_camera = _front_camera_from_selection(selection, camera, config)
        # Resolve against the authentic source paths before the clip loader
        # renames them to the notebook's normalized frame names.
        source_files = sorted(Path(source).resolve().glob("*.png"))
        if selection.get("frame_indices") is not None:
            wanted = tuple(int(value) for value in selection["frame_indices"])
            by_number = {}
            for path in source_files:
                match = re.search(r"(?:frame[_-]?)?(\d+)(?:\D*)$", path.stem.lower())
                if match:
                    by_number[int(match.group(1))] = path
            source_files = [by_number[value] for value in wanted if value in by_number]
        front_paths = resolve_front_perspective_paths(dict(selection), source_files)
        if not front_paths:
            raise FileNotFoundError(
                "front_view_enabled=True but no generated front-perspective mapping was supplied; "
                "use the asset picker selection or set front_perspective_paths explicitly"
            )
        if len(front_paths) != len(source_files):
            raise ValueError("generated front-perspective mapping does not match the selected DEF frames")
    rig = prepare_rig(
        mesh,
        device=config.device,
        mesh_scale=config.mesh_scale,
        rigidization_report=selection.get("rigidization_report") or selection.get("rigidizationReport"),
    )
    clip = prepare_clip(
        source,
        camera=camera,
        config=config,
        frame_indices=None if selection.get("frame_indices") is None else tuple(selection["frame_indices"]),
        depth_dir=selection.get("target_depth_dir") or config.target_depth_dir,
        front_perspective_paths=front_paths,
        front_camera=front_camera,
        source_fps=float(selection.get("source_fps", 12.0)),
        frame_durations=None if selection.get("frame_durations") is None else tuple(selection["frame_durations"]),
    )
    front_scale_fit: dict[str, Any] | None = None
    if front_camera is not None:
        front_camera, front_scale_fit = _fit_front_camera_scale(front_camera, rig, clip, config)
        if clip.front_provenance is not None:
            front_provenance = dict(clip.front_provenance)
            front_provenance["scaleFit"] = front_scale_fit
            clip = replace(clip, front_provenance=front_provenance)
    artifact_dir = Path(selection.get("artifact_dir") or (Path(source).resolve().parent / "gpu_pose_v2")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "v2_session.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "mesh": str(Path(mesh).resolve()),
                "targetFrameDir": str(Path(source).resolve()),
                "camera": camera.__dict__,
                "config": config.to_jsonable(),
                "rigFingerprint": rig.fingerprint,
                "sceneNodeCount": len(rig.node_names),
                "skeletonNodeIndices": list(rig.skeleton_indices),
                "skeletonNodeNames": [rig.node_names[index] for index in rig.skeleton_indices],
                "clipFingerprint": clip.fingerprint,
                "cameraFitPath": None if not selection.get("camera_fit_path") and not selection.get("cameraFitPath") else str(Path(selection.get("camera_fit_path") or selection.get("cameraFitPath")).resolve()),
                "frontCamera": None if front_camera is None else front_camera.__dict__,
                "frameDurations": list(clip.frame_durations),
                "frontView": clip.front_provenance,
                "preflight": dict(report),
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    camera_fit_value = selection.get("camera_fit_path") or selection.get("cameraFitPath")
    camera_fit_path = None if not camera_fit_value else Path(camera_fit_value).resolve()
    return ExperimentSession(config, camera, rig, clip, artifact_dir, report, camera_fit_path, front_camera)


def preview(session: ExperimentSession, result: ExperimentResult, *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Write exact GPU RGB/depth/alpha previews without invoking Blender.

    The profile comparison is the optimization view.  The additional
    front-upper-diagonal image is a diagnostic view rendered from the same
    deformed triangles, not a second scoring camera.
    """
    from PIL import Image, ImageDraw

    from .renderer import ExactCudaRenderer
    out = Path(output_dir or (session.artifact_dir / "preview")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    renderer = ExactCudaRenderer(session.rig, session.camera, antialias=session.config.raster_antialias)
    buffers = renderer.render_single(result.selected.pose)
    frames: list[Path] = []
    for index in range(len(session.clip.frame_indices)):
        target = (session.clip.rgb[index] * session.clip.masks[index][..., None] * 255.0).clip(0, 255).astype(np.uint8)
        candidate = buffers.rgb[0, index].detach().cpu().numpy()
        alpha = buffers.alpha[0, index].detach().cpu().numpy()[..., None]
        candidate = (candidate * alpha * 255.0).clip(0, 255).astype(np.uint8)
        depth = buffers.depth[0, index].detach().cpu().numpy()
        visible = buffers.alpha[0, index].detach().cpu().numpy() > 0.01
        if np.any(visible):
            near = float(np.nanmin(depth[visible]))
            far = float(np.nanmax(depth[visible]))
            depth = (depth - near) / max(far - near, 1e-6)
        depth = ((1.0 - np.nan_to_num(depth, nan=0.0).clip(0.0, 1.0)) * visible * 255.0).astype(np.uint8)
        target_mask = session.clip.masks[index] > 0.5
        candidate_mask = buffers.alpha[0, index].detach().cpu().numpy() > 0.5
        overlay = np.zeros((session.camera.height, session.camera.width, 3), dtype=np.uint8)
        overlap = target_mask & candidate_mask
        overlay[overlap] = (55, 190, 90)
        overlay[target_mask & ~candidate_mask] = (45, 110, 235)
        overlay[~target_mask & candidate_mask] = (225, 65, 55)
        tiles = [
            (Image.fromarray(target, mode="RGB"), "target RGB"),
            (Image.fromarray(candidate, mode="RGB"), "exact GPU RGB"),
            (Image.fromarray(depth, mode="L").convert("RGB"), "exact GPU depth"),
            (Image.fromarray(overlay, mode="RGB"), "IoU overlay"),
        ]
        canvas = Image.new("RGB", (session.camera.width * 2, session.camera.height * 2), "black")
        for tile_index, (tile, label) in enumerate(tiles):
            x = (tile_index % 2) * session.camera.width
            y = (tile_index // 2) * session.camera.height
            canvas.paste(tile, (x, y))
            ImageDraw.Draw(canvas).text((x + 4, y + 4), label, fill="white")
        draw = ImageDraw.Draw(canvas)
        draw.text((4, session.camera.height * 2 - 14), f"frame {session.clip.frame_indices[index]:02d}", fill="white")
        path = out / f"frame_{index:02d}.png"
        canvas.save(path)
        frames.append(path)
    gif = out / "gpu_pose_v2_preview.gif"
    images = [Image.open(path).convert("RGB") for path in frames]
    images[0].save(gif, save_all=True, append_images=images[1:], duration=max(1, round(1000 / session.clip.source_fps)), loop=0)
    for image in images:
        image.close()
    front_frames: list[Path] = []
    front_gif: Path | None = None
    if (
        session.config.front_view_enabled
        and session.front_camera is not None
        and session.clip.front_rgb is not None
        and session.clip.front_masks is not None
    ):
        front_renderer = ExactCudaRenderer(
            session.rig,
            session.front_camera,
            antialias=session.config.raster_antialias,
        )
        front_buffers = front_renderer.render_single(result.selected.pose)
        front_images: list[Image.Image] = []
        for index in range(len(session.clip.frame_indices)):
            target_rgb = session.clip.front_rgb[index]
            target_mask = session.clip.front_masks[index]
            candidate_rgb = front_buffers.rgb[0, index].detach().cpu().numpy()
            candidate_mask = front_buffers.alpha[0, index].detach().cpu().numpy()
            # The target was normalized during clip preparation and the
            # auxiliary camera was fitted once from bind pose.  Preview the
            # exact candidate in that fixed camera; independently fitting it
            # here would hide the same scale/translation errors the objective
            # is meant to expose.
            overlay = np.zeros((session.front_camera.height, session.front_camera.width, 3), dtype=np.uint8)
            target_bool = target_mask > 0.5
            candidate_bool = candidate_mask > 0.5
            overlap = target_bool & candidate_bool
            overlay[overlap] = (55, 190, 90)
            overlay[target_bool & ~candidate_bool] = (45, 110, 235)
            overlay[~target_bool & candidate_bool] = (225, 65, 55)
            tiles = [
                (Image.fromarray((target_rgb * target_mask[..., None] * 255.0).clip(0, 255).astype(np.uint8), mode="RGB"), "front target"),
                (Image.fromarray((candidate_rgb * candidate_mask[..., None] * 255.0).clip(0, 255).astype(np.uint8), mode="RGB"), "front exact GPU"),
                (Image.fromarray(overlay, mode="RGB"), "front fixed-camera IoU"),
            ]
            canvas = Image.new("RGB", (session.front_camera.width * 2, session.front_camera.height * 2), "black")
            for tile_index, (tile, label) in enumerate(tiles):
                x = (tile_index % 2) * session.front_camera.width
                y = (tile_index // 2) * session.front_camera.height
                canvas.paste(tile, (x, y))
                ImageDraw.Draw(canvas).text((x + 4, y + 4), label, fill="white")
            path = out / f"front_frame_{index:02d}.png"
            canvas.save(path)
            front_frames.append(path)
            front_images.append(canvas.convert("RGB"))
        front_gif = out / "front_auxiliary_preview.gif"
        front_images[0].save(
            front_gif,
            save_all=True,
            append_images=front_images[1:],
            duration=max(1, round(1000 / session.clip.source_fps)),
            loop=0,
        )
        for image in front_images:
            image.close()
    # A fixed diagnostic camera makes hidden-axis twists visible without
    # changing the profile camera used by the objective.
    camera_forward = np.asarray(session.camera.forward, dtype=np.float64)
    camera_forward /= max(float(np.linalg.norm(camera_forward)), 1e-8)
    camera_up = -np.asarray(session.camera.down, dtype=np.float64)
    camera_up /= max(float(np.linalg.norm(camera_up)), 1e-8)
    action_forward = camera_forward - 0.32 * camera_up + 0.25 * np.asarray(session.camera.right, dtype=np.float64)
    action_forward /= max(float(np.linalg.norm(action_forward)), 1e-8)
    action_right = -np.cross(camera_up, action_forward)
    action_right /= max(float(np.linalg.norm(action_right)), 1e-8)
    action_down = -np.cross(action_right, action_forward)
    action_camera = replace(
        session.camera,
        right=tuple(float(value) for value in action_right),
        down=tuple(float(value) for value in action_down),
        forward=tuple(float(value) for value in action_forward),
        # The diagonal projection foreshortens the profile; enlarge only this
        # diagnostic view so the 3D result remains inspectable in the notebook.
        px_per_world=tuple(float(value) * 1.6 for value in session.camera.px_per_world),
    )
    action_renderer = ExactCudaRenderer(session.rig, action_camera, antialias=session.config.raster_antialias)
    action_buffers = action_renderer.render_single(result.selected.pose)
    action = action_buffers.rgb[0, 0].detach().cpu().numpy()
    action_alpha = action_buffers.alpha[0, 0].detach().cpu().numpy()[..., None]
    action_path = out / "front_upper_diagonal_action_camera.png"
    Image.fromarray((action * action_alpha * 255.0).clip(0, 255).astype(np.uint8), mode="RGB").save(action_path)
    result_paths = {
        "frames": [str(path) for path in frames],
        "gif": str(gif),
        "actionCamera": str(action_path),
        "source": "exact CUDA triangle renderer",
    }
    if front_gif is not None:
        result_paths.update({
            "frontFrames": [str(path) for path in front_frames],
            "frontGif": str(front_gif),
            "frontSource": "normalized generated front target vs fixed-scale exact CUDA triangle renderer",
        })
    return result_paths


def export(session: ExperimentSession, result: ExperimentResult) -> Path:
    """Persist the canonical result; Blender export consumes this artifact."""
    path = session.artifact_dir / "gpu_pose_v2_result.json"
    path.write_text(json.dumps(result.to_jsonable(), indent=2, default=str) + "\n", encoding="utf-8")
    return path
