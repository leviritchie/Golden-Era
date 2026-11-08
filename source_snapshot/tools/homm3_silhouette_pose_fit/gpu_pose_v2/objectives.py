"""Differentiable geometry and plausibility objectives for V2."""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import torch
import torch.nn.functional as F

from .contracts import CameraSpec, ObjectiveBreakdown, PoseState, PreparedClip, PreparedRig, RenderBuffers, V2Config


def _finite_edge(mask: torch.Tensor) -> torch.Tensor:
    dx = (mask[..., :, 1:] - mask[..., :, :-1]).abs()
    dy = (mask[..., 1:, :] - mask[..., :-1, :]).abs()
    result = torch.zeros_like(mask)
    result[..., :, 1:] = result[..., :, 1:] + dx
    result[..., 1:, :] = result[..., 1:, :] + dy
    return result.clamp(0.0, 1.0)


def _canonicalize_mask(
    candidate: torch.Tensor,
    target: torch.Tensor,
    camera: CameraSpec,
) -> torch.Tensor:
    """Fit candidate foreground to the target's canonical subject frame.

    The generated front references are normalized at load time.  Candidate
    masks still come from the mesh camera and can have a different absolute
    extent.  A differentiable centroid/radius fit removes that nuisance scale
    and translation from the auxiliary view without touching profile motion
    root variables or the authoritative profile objective.
    """
    hypotheses, frames, height, width = candidate.shape
    yy, xx = torch.meshgrid(
        torch.arange(height, dtype=candidate.dtype, device=candidate.device),
        torch.arange(width, dtype=candidate.dtype, device=candidate.device),
        indexing="ij",
    )
    target_mass = target.sum(dim=(-2, -1)).clamp_min(1e-6)
    candidate_mass = candidate.sum(dim=(-2, -1)).clamp_min(1e-6)
    target_cx = (target * xx).sum(dim=(-2, -1)) / target_mass
    target_cy = (target * yy).sum(dim=(-2, -1)) / target_mass
    candidate_cx = (candidate * xx).sum(dim=(-2, -1)) / candidate_mass
    candidate_cy = (candidate * yy).sum(dim=(-2, -1)) / candidate_mass
    target_radius = torch.sqrt(
        (target * ((xx - target_cx[..., None, None]) ** 2 + (yy - target_cy[..., None, None]) ** 2)).sum(dim=(-2, -1))
        / target_mass
    ).clamp_min(1.0)
    candidate_radius = torch.sqrt(
        (candidate * ((xx - candidate_cx[..., None, None]) ** 2 + (yy - candidate_cy[..., None, None]) ** 2)).sum(dim=(-2, -1))
        / candidate_mass
    ).clamp_min(1.0)
    source_x = candidate_cx[..., None, None] + (xx - target_cx[..., None, None]) * candidate_radius[..., None, None] / target_radius[..., None, None]
    source_y = candidate_cy[..., None, None] + (yy - target_cy[..., None, None]) * candidate_radius[..., None, None] / target_radius[..., None, None]
    grid = torch.stack(
        (
            source_x / max(width - 1, 1) * 2.0 - 1.0,
            1.0 - source_y / max(height - 1, 1) * 2.0,
        ),
        dim=-1,
    )
    return F.grid_sample(
        candidate.reshape(hypotheses * frames, 1, height, width),
        grid.reshape(hypotheses * frames, height, width, 2),
        mode="bilinear",
        padding_mode="zeros",
        align_corners=True,
    ).reshape(hypotheses, frames, height, width)


def _mask_sdf_error(predicted: torch.Tensor, target_sdf: torch.Tensor) -> torch.Tensor:
    """Use a resolution-normalized target SDF as a long-range boundary field."""
    pixel_scale = float(max(int(target_sdf.shape[-2]), int(target_sdf.shape[-1]), 1))
    return (
        target_sdf.abs() * predicted
    ).sum(dim=(-2, -1)) / (predicted.sum(dim=(-2, -1)).clamp_min(1.0) * pixel_scale)


class ObjectiveRegistry:
    """All enabled objective components share one normalized loss contract."""

    def __init__(
        self,
        clip: PreparedClip,
        rig: PreparedRig,
        camera: CameraSpec,
        config: V2Config,
        front_camera: CameraSpec | None = None,
    ):
        self.clip = clip
        self.rig = rig
        self.camera = camera
        self.front_camera = front_camera
        self.config = config
        device = torch.device(rig.device)
        self.target_masks = torch.as_tensor(clip.masks, dtype=torch.float32, device=device)
        self.target_edge = torch.as_tensor(clip.edge, dtype=torch.float32, device=device)
        self.target_sdf = torch.as_tensor(clip.sdf, dtype=torch.float32, device=device)
        self.target_depth = None if clip.depth is None else torch.as_tensor(clip.depth, dtype=torch.float32, device=device)
        self.target_depth_confidence = None if clip.depth_confidence is None else torch.as_tensor(clip.depth_confidence, dtype=torch.float32, device=device)
        self.target_feature_points = tuple(
            torch.as_tensor(value, dtype=torch.float32, device=device)
            for value in clip.feature_points
        )
        self.front_enabled = bool(
            config.front_view_enabled
            and front_camera is not None
            and clip.front_masks is not None
            and clip.front_edge is not None
            and clip.front_sdf is not None
        )
        self.front_target_masks = (
            None
            if not self.front_enabled
            else torch.as_tensor(clip.front_masks, dtype=torch.float32, device=device)
        )
        self.front_target_edge = (
            None
            if not self.front_enabled
            else torch.as_tensor(clip.front_edge, dtype=torch.float32, device=device)
        )
        self.front_target_sdf = (
            None
            if not self.front_enabled
            else torch.as_tensor(clip.front_sdf, dtype=torch.float32, device=device)
        )
        self.grid = self._grid(device)
        rigid_names: set[str] = set()
        if rig.rigidization:
            for mesh in rig.rigidization.get("meshes", []):
                for region in mesh.get("regions", []):
                    if region.get("classification") == "freeze_rigid_candidate" and region.get("ownerBone"):
                        rigid_names.add(str(region["ownerBone"]))
        self.rigid_indices = torch.as_tensor(
            [index for index, name in enumerate(rig.node_names) if name in rigid_names],
            dtype=torch.long,
            device=device,
        )

    def _grid(self, device: torch.device, camera: CameraSpec | None = None) -> torch.Tensor:
        camera = self.camera if camera is None else camera
        yy, xx = torch.meshgrid(
            torch.arange(camera.height, dtype=torch.float32, device=device),
            torch.arange(camera.width, dtype=torch.float32, device=device),
            indexing="ij",
        )
        return torch.stack((xx, yy), dim=-1)

    def _target_for_hypotheses(self, value: torch.Tensor, count: int) -> torch.Tensor:
        return value.unsqueeze(0).expand(count, *value.shape)

    def _centroid_error(
        self,
        predicted: torch.Tensor,
        target: torch.Tensor,
        camera: CameraSpec | None = None,
    ) -> torch.Tensor:
        camera = self.camera if camera is None else camera
        eps = 1e-6
        grid = self._grid(predicted.device, camera).view(1, 1, camera.height, camera.width, 2)
        grid = grid / torch.tensor(
            [max(camera.width - 1, 1), max(camera.height - 1, 1)],
            dtype=predicted.dtype,
            device=predicted.device,
        )
        pred_mass = predicted.sum(dim=(-2, -1)).clamp_min(eps)
        target_mass = target.sum(dim=(-2, -1)).clamp_min(eps)
        pred_center = (predicted.unsqueeze(-1) * grid).sum(dim=(-3, -2)) / pred_mass.unsqueeze(-1)
        target_center = (target.unsqueeze(-1) * grid).sum(dim=(-3, -2)) / target_mass.unsqueeze(-1)
        return torch.linalg.vector_norm(pred_center - target_center, dim=-1).clamp(0.0, 1.0)

    def _project_world(
        self,
        points: torch.Tensor,
        camera: CameraSpec | None = None,
    ) -> torch.Tensor:
        """Project world positions into ``grid_sample``'s top-origin NDC.

        The first implementation only normalized the raw right/down dot
        products.  That omitted the fitted camera offset and pixel scale and
        inverted the vertical convention used by nvdiffrast/PNG buffers.  SDF
        guidance therefore queried the wrong target pixels even though the
        final alpha renderer was correct.
        """
        camera = self.camera if camera is None else camera
        right = torch.as_tensor(camera.right, dtype=points.dtype, device=points.device)
        down = torch.as_tensor(camera.down, dtype=points.dtype, device=points.device)
        x = (
            torch.einsum("...k,k->...", points, right)
            * float(camera.px_per_world[0])
            + float(camera.offset[0])
        )
        y = (
            torch.einsum("...k,k->...", points, down)
            * float(camera.px_per_world[1])
            + float(camera.offset[1])
        )
        x_ndc = x / max(camera.width - 1, 1) * 2.0 - 1.0
        # ``grid_sample`` uses -1 at the top, matching the top-origin target
        # tensors after the renderer's explicit row flip.
        y_ndc = 1.0 - y / max(camera.height - 1, 1) * 2.0
        return torch.stack((x_ndc, y_ndc), dim=-1)

    def _sdf_error(
        self,
        buffers: RenderBuffers,
        target_sdf: torch.Tensor,
        camera: CameraSpec | None = None,
    ) -> torch.Tensor:
        # Query the target SDF at the rendered surface. This gives thin limbs a
        # long-range direction without replacing the exact raster IoU term.
        points = buffers.world_position
        camera = self.camera if camera is None else camera
        coords = self._project_world(points, camera).unsqueeze(-2)
        fields = target_sdf.reshape(-1, 1, camera.height, camera.width)
        sample_grid = coords.reshape(-1, camera.height, camera.width, 2)
        sampled = F.grid_sample(fields, sample_grid, mode="bilinear", padding_mode="border", align_corners=True).reshape(points.shape[0], points.shape[1], camera.height, camera.width)
        visible = buffers.alpha
        return (sampled.abs() * visible).sum(dim=(-2, -1)) / visible.sum(dim=(-2, -1)).clamp_min(1.0)

    def _temporal(self, pose: PoseState, hypotheses: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        zero = torch.zeros((hypotheses,), dtype=pose.bone_rotation.dtype, device=pose.bone_rotation.device)
        diagnostics: dict[str, torch.Tensor] = {}
        total = zero
        robust = math.radians(float(self.config.robust_scale_deg))
        def robust_abs(value: torch.Tensor) -> torch.Tensor:
            return torch.tanh(value.abs() / max(robust, 1e-6))
        if pose.bone_rotation.shape[1] > 1:
            velocity = robust_abs(pose.bone_rotation[:, 1:] - pose.bone_rotation[:, :-1]).mean(dim=(1, 2, 3))
            total = total + float(self.config.velocity_weight) * velocity
            diagnostics["velocity"] = velocity
        if pose.bone_rotation.shape[1] > 2:
            acceleration = robust_abs(pose.bone_rotation[:, 2:] - 2 * pose.bone_rotation[:, 1:-1] + pose.bone_rotation[:, :-2]).mean(dim=(1, 2, 3))
            total = total + float(self.config.acceleration_weight) * acceleration
            diagnostics["acceleration"] = acceleration
        if pose.motion_rotation.shape[1] > 1:
            root_velocity = robust_abs(pose.motion_rotation[:, 1:] - pose.motion_rotation[:, :-1]).mean(dim=(1, 2))
            total = total + float(self.config.velocity_weight) * 0.5 * root_velocity
            diagnostics["rootVelocity"] = root_velocity
        if bool(self.config.loop_objective_enabled) and pose.bone_rotation.shape[1] > 1:
            loop_position = robust_abs(pose.bone_rotation[:, 0] - pose.bone_rotation[:, -1]).mean(dim=(1, 2))
            loop_root = robust_abs(pose.motion_rotation[:, 0] - pose.motion_rotation[:, -1]).mean(dim=1) + robust_abs(
                pose.motion_translation[:, 0] - pose.motion_translation[:, -1]
            ).mean(dim=1)
            total = total + float(self.config.loop_weight) * (loop_position + 0.5 * loop_root)
            diagnostics["loopPosition"] = loop_position
            diagnostics["loopRoot"] = loop_root
            if pose.bone_rotation.shape[1] > 2:
                first_velocity = pose.bone_rotation[:, 1] - pose.bone_rotation[:, 0]
                seam_velocity = pose.bone_rotation[:, 0] - pose.bone_rotation[:, -1]
                loop_velocity = robust_abs(first_velocity - seam_velocity).mean(dim=(1, 2))
                total = total + float(self.config.loop_weight) * 0.5 * loop_velocity
                diagnostics["loopVelocity"] = loop_velocity
        pose_prior = robust_abs(pose.bone_rotation).mean(dim=(1, 2, 3))
        root_prior = robust_abs(pose.motion_rotation).mean(dim=(1, 2)) + robust_abs(pose.motion_translation).mean(dim=(1, 2))
        total = total + float(self.config.pose_prior_weight) * pose_prior + float(self.config.root_prior_weight) * root_prior
        diagnostics["posePrior"] = pose_prior
        diagnostics["rootPrior"] = root_prior
        if self.rigid_indices.numel():
            rigid = robust_abs(pose.bone_rotation.index_select(2, self.rigid_indices)).mean(dim=(1, 2, 3))
        else:
            rigid = torch.zeros_like(total)
        total = total + float(self.config.rigidity_weight) * rigid
        diagnostics["rigidity"] = rigid
        return total, diagnostics

    def _anatomy_error(self, predicted: torch.Tensor, feature_points: tuple[torch.Tensor, ...] | None = None) -> torch.Tensor:
        """Compare discovered target features to the nearest candidate surface.

        This is deliberately an unnamed visual correspondence term. The target
        point set is generated from each frame's own boundary evidence and the
        candidate location is solved as a differentiable soft nearest surface
        point, so the optimizer is not handed a fixed human anatomy list.
        """
        hypotheses, frames = predicted.shape[:2]
        grid = self.grid.reshape(-1, 2)
        grid = grid / torch.tensor(
            [max(self.camera.width - 1, 1), max(self.camera.height - 1, 1)],
            dtype=predicted.dtype,
            device=predicted.device,
        )
        errors: list[torch.Tensor] = []
        temperature = 0.025
        points_source = self.target_feature_points if feature_points is None else feature_points
        for frame in range(frames):
            points = points_source[frame]
            if points.numel() == 0:
                errors.append(torch.zeros((hypotheses,), dtype=predicted.dtype, device=predicted.device))
                continue
            target_xy = points[:, :2]
            confidence = points[:, 2].clamp_min(0.1)
            alpha = predicted[:, frame].reshape(hypotheses, -1).clamp(0.0, 1.0)
            log_probability = torch.log(alpha + 1e-4)
            log_probability = log_probability - torch.logsumexp(log_probability, dim=-1, keepdim=True)
            distance = ((grid.unsqueeze(0).unsqueeze(0) - target_xy.unsqueeze(0).unsqueeze(2)) ** 2).sum(dim=-1)
            soft_nearest = -temperature * torch.logsumexp(
                log_probability.unsqueeze(1) - distance / temperature,
                dim=-1,
            )
            target_grid = (target_xy * 2.0 - 1.0).view(1, -1, 1, 2).expand(hypotheses, -1, -1, -1)
            coverage = F.grid_sample(
                predicted[:, frame].unsqueeze(1),
                target_grid,
                mode="bilinear",
                padding_mode="zeros",
                align_corners=True,
            ).reshape(hypotheses, -1).clamp(0.0, 1.0)
            value = (soft_nearest + 0.5 * (1.0 - coverage)) * confidence.unsqueeze(0)
            errors.append(value.mean(dim=-1))
        return torch.stack(errors, dim=1)

    def score(
        self,
        buffers: RenderBuffers,
        pose: PoseState,
        *,
        frame_positions: tuple[int, ...] | None = None,
        include_temporal: bool = True,
        auxiliary_buffers: RenderBuffers | None = None,
    ) -> ObjectiveBreakdown:
        if frame_positions is None:
            positions = tuple(range(int(buffers.alpha.shape[1])))
        else:
            positions = tuple(int(value) for value in frame_positions)
            if not positions or min(positions) < 0 or max(positions) >= int(buffers.alpha.shape[1]):
                raise ValueError("frame_positions must select existing rendered frames")
        if positions != tuple(range(int(buffers.alpha.shape[1]))):
            index = torch.as_tensor(positions, dtype=torch.long, device=buffers.alpha.device)
            buffers = replace(
                buffers,
                rgb=buffers.rgb.index_select(1, index),
                alpha=buffers.alpha.index_select(1, index),
                depth=buffers.depth.index_select(1, index),
                triangle_id=buffers.triangle_id.index_select(1, index),
                barycentrics=buffers.barycentrics.index_select(1, index),
                world_position=buffers.world_position.index_select(1, index),
                normal=None if buffers.normal is None else buffers.normal.index_select(1, index),
                dominant_bone=None if buffers.dominant_bone is None else buffers.dominant_bone.index_select(1, index),
            )
            if auxiliary_buffers is not None:
                auxiliary_buffers = replace(
                    auxiliary_buffers,
                    rgb=auxiliary_buffers.rgb.index_select(1, index),
                    alpha=auxiliary_buffers.alpha.index_select(1, index),
                    depth=auxiliary_buffers.depth.index_select(1, index),
                    triangle_id=auxiliary_buffers.triangle_id.index_select(1, index),
                    barycentrics=auxiliary_buffers.barycentrics.index_select(1, index),
                    world_position=auxiliary_buffers.world_position.index_select(1, index),
                    normal=None if auxiliary_buffers.normal is None else auxiliary_buffers.normal.index_select(1, index),
                    dominant_bone=None if auxiliary_buffers.dominant_bone is None else auxiliary_buffers.dominant_bone.index_select(1, index),
                )
        predicted = buffers.alpha
        hypotheses = int(predicted.shape[0])
        target_masks = self.target_masks[list(positions)]
        target_edge_values = self.target_edge[list(positions)]
        target_sdf_values = self.target_sdf[list(positions)]
        target = self._target_for_hypotheses(target_masks, hypotheses)
        eps = 1e-6
        intersection = (predicted * target).sum(dim=(-2, -1))
        predicted_area = predicted.sum(dim=(-2, -1))
        target_area = target.sum(dim=(-2, -1))
        union = predicted_area + target_area - intersection
        iou = intersection / union.clamp_min(eps)
        # Normalize asymmetric silhouette errors by target foreground area,
        # not by the whole canvas. A missing wing should remain significant at
        # both 128x116 and larger preview resolutions.
        missing = ((target - predicted).clamp_min(0.0)).sum(dim=(-2, -1)) / target_area.clamp_min(1.0)
        excess = ((predicted - target).clamp_min(0.0)).sum(dim=(-2, -1)) / target_area.clamp_min(1.0)
        target_edge = self._target_for_hypotheses(target_edge_values, hypotheses)
        edge = (_finite_edge(predicted) - target_edge).abs().mean(dim=(-2, -1))
        centroid = self._centroid_error(predicted, target)
        occupancy = (predicted_area - target_area).abs() / target_area.clamp_min(1.0)
        occupancy = occupancy.clamp(0.0, 1.0)
        sdf = self._sdf_error(buffers, self._target_for_hypotheses(target_sdf_values, hypotheses))
        if self.target_depth is None or self.target_depth_confidence is None:
            depth = torch.zeros_like(iou)
        else:
            target_depth = self._target_for_hypotheses(self.target_depth[list(positions)], hypotheses)
            confidence = self._target_for_hypotheses(self.target_depth_confidence[list(positions)], hypotheses)
            predicted_depth = ((buffers.depth - float(self.camera.near)) / max(float(self.camera.far - self.camera.near), 1e-6)).clamp(0.0, 1.0)
            depth = ((predicted_depth - target_depth).abs() * buffers.alpha * confidence).sum(dim=(-2, -1)) / (buffers.alpha * confidence).sum(dim=(-2, -1)).clamp_min(1.0)
        anatomy = self._anatomy_error(predicted, tuple(self.target_feature_points[position] for position in positions))
        components: dict[str, torch.Tensor] = {
            "silhouette": 1.0 - iou,
            "missing": missing,
            "excess": excess,
            "edge": edge,
            "sdf": sdf,
            "centroid": centroid,
            "occupancy": occupancy,
            "depth": depth,
            "anatomy": anatomy,
        }
        weights = {
            "silhouette": self.config.silhouette_weight,
            "missing": self.config.missing_weight,
            "excess": self.config.excess_weight,
            "edge": self.config.edge_weight,
            "sdf": self.config.sdf_weight,
            "centroid": self.config.centroid_weight,
            "occupancy": self.config.occupancy_weight,
            "depth": self.config.depth_weight if self.target_depth is not None else 0.0,
            "anatomy": self.config.anatomy_weight,
        }
        front_iou = None
        front_target_area = None
        if self.front_enabled:
            if auxiliary_buffers is None:
                raise ValueError("front-view objective is enabled but no auxiliary render buffers were supplied")
            if self.front_target_masks is None or self.front_target_edge is None or self.front_target_sdf is None or self.front_camera is None:
                raise RuntimeError("front-view objective is enabled without prepared front targets")
            front_target_values = self.front_target_masks[list(positions)]
            front_target_edge_values = self.front_target_edge[list(positions)]
            front_target_sdf_values = self.front_target_sdf[list(positions)]
            front_target = self._target_for_hypotheses(front_target_values, hypotheses)
            # Targets were normalized once during preparation and the
            # auxiliary camera was fitted once from the bind pose.  Do not
            # recenter or resize each candidate: doing so would erase scale,
            # translation, and gross hidden-axis errors.
            front_predicted = auxiliary_buffers.alpha
            front_intersection = (front_predicted * front_target).sum(dim=(-2, -1))
            front_predicted_area = front_predicted.sum(dim=(-2, -1))
            front_target_area = front_target.sum(dim=(-2, -1))
            front_union = front_predicted_area + front_target_area - front_intersection
            front_iou = front_intersection / front_union.clamp_min(eps)
            front_missing = ((front_target - front_predicted).clamp_min(0.0)).sum(dim=(-2, -1)) / front_target_area.clamp_min(1.0)
            front_excess = ((front_predicted - front_target).clamp_min(0.0)).sum(dim=(-2, -1)) / front_target_area.clamp_min(1.0)
            front_target_edge = self._target_for_hypotheses(front_target_edge_values, hypotheses)
            front_edge = (_finite_edge(front_predicted) - front_target_edge).abs().mean(dim=(-2, -1))
            front_centroid = self._centroid_error(front_predicted, front_target, self.front_camera)
            front_occupancy = ((front_predicted_area - front_target_area).abs() / front_target_area.clamp_min(1.0)).clamp(0.0, 1.0)
            front_sdf = _mask_sdf_error(
                front_predicted,
                self._target_for_hypotheses(front_target_sdf_values, hypotheses),
            )
            components.update({
                "frontSilhouette": 1.0 - front_iou,
                "frontMissing": front_missing,
                "frontExcess": front_excess,
                "frontEdge": front_edge,
                "frontSdf": front_sdf,
                "frontCentroid": front_centroid,
                "frontOccupancy": front_occupancy,
            })
            weights.update({
                "frontSilhouette": self.config.front_view_silhouette_weight,
                "frontMissing": self.config.front_view_missing_weight,
                "frontExcess": self.config.front_view_excess_weight,
                "frontEdge": self.config.front_view_edge_weight,
                "frontSdf": self.config.front_view_sdf_weight,
                # Generated framing is useful for disambiguation, not an
                # authoritative camera calibration source.
                "frontCentroid": 0.0,
                "frontOccupancy": 0.0,
            })
        total_per_frame = sum(float(weights[name]) * value for name, value in components.items())
        temporal, temporal_diagnostics = (
            self._temporal(pose, hypotheses)
            if include_temporal
            else (torch.zeros_like(iou[:, 0]), {})
        )
        total = total_per_frame.mean(dim=1) + temporal
        diagnostics: dict[str, Any] = {
            "iou": iou,
            "predictedArea": predicted_area,
            "targetArea": target_area,
            "temporal": temporal,
            "anatomy": anatomy,
            **temporal_diagnostics,
        }
        if front_iou is not None:
            diagnostics["frontIou"] = front_iou
        feature_count = sum(int(self.target_feature_points[position].shape[0]) for position in positions)
        return ObjectiveBreakdown(
            total=total,
            per_frame={name: value for name, value in components.items()},
            diagnostics=diagnostics,
            observability={
                "targetSilhouetteMass": target_area.mean(dim=-1),
                "targetEdgeMass": target_edge.mean(dim=(-2, -1)).mean(dim=-1),
                "depthConfidence": (
                    confidence.mean(dim=(-2, -1)).mean(dim=-1)
                    if self.target_depth is not None and self.target_depth_confidence is not None
                    else torch.zeros_like(iou)
                ),
                "anatomyFeatureCount": torch.full_like(iou, float(feature_count)),
                "frontTargetSilhouetteMass": (
                    front_target_area.mean(dim=-1)
                    if front_target_area is not None
                    else torch.zeros_like(iou)
                ),
            },
        )
