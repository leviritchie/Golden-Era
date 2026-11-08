"""Exact CUDA triangle renderer used by the V2 search loop."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from roc_geometric_proxy import gltf_uv_to_grid_sample
from .contracts import CameraSpec, PoseState, PreparedRig, RenderBuffers


def _axis_angle_matrix(vectors: torch.Tensor) -> torch.Tensor:
    """Return Rodrigues matrices with a nonzero derivative at the identity.

    The usual ``axis = v / ||v||`` form is numerically safe at zero only after
    clamping the denominator, but its derivative is still zero there.  V2
    initializes motion roots and bone rotations at exactly zero, so that form
    silently made every articulated parameter invisible to gradient descent.
    Evaluating Rodrigues in its matrix-exponential form keeps the first-order
    term ``skew(v)`` and therefore gives the optimizer a direction to leave the
    bind pose.
    """
    x, y, z = vectors.unbind(dim=-1)
    skew = torch.zeros((*vectors.shape[:-1], 3, 3), dtype=vectors.dtype, device=vectors.device)
    skew[..., 0, 1] = -z
    skew[..., 0, 2] = y
    skew[..., 1, 0] = z
    skew[..., 1, 2] = -x
    skew[..., 2, 0] = -y
    skew[..., 2, 1] = x

    theta2 = (vectors * vectors).sum(dim=-1)
    # Clamp before sqrt as well.  ``sqrt(0)`` has an infinite derivative and
    # can leak NaNs through the unselected branch of ``torch.where``.
    theta = torch.sqrt(torch.clamp(theta2, min=1e-8))
    safe_theta = torch.clamp(theta, min=1e-4)
    safe_theta2 = torch.clamp(theta2, min=1e-8)

    # Taylor expansions avoid cancellation around the identity while retaining
    # the correct finite limits: sinc(0)=1 and (1-cos(t))/t^2=1/2.
    theta4 = theta2 * theta2
    sinc_small = 1.0 - theta2 / 6.0 + theta4 / 120.0
    cosine_small = 0.5 - theta2 / 24.0 + theta4 / 720.0
    sinc = torch.where(theta2 < 1e-6, sinc_small, torch.sin(safe_theta) / safe_theta)
    cosine = torch.where(
        theta2 < 1e-6,
        cosine_small,
        (1.0 - torch.cos(safe_theta)) / safe_theta2,
    )
    identity = torch.eye(3, dtype=vectors.dtype, device=vectors.device)
    return identity + sinc.unsqueeze(-1).unsqueeze(-1) * skew + cosine.unsqueeze(-1).unsqueeze(-1) * torch.matmul(skew, skew)


class ExactCudaRenderer:
    """Batch FK/LBS/rasterization with no Blender or image-file round trips."""

    def __init__(self, rig: PreparedRig, camera: CameraSpec, *, antialias: bool = True):
        if not torch.cuda.is_available():
            raise RuntimeError("ExactCudaRenderer requires CUDA")
        try:
            import nvdiffrast.torch as dr
        except Exception as exc:  # fail closed; the old point renderer is not a fallback
            raise RuntimeError(
                "nvdiffrast is required for V2 exact triangle rendering; install the pinned CUDA extension"
            ) from exc
        camera.validate()
        self.rig = rig
        self.camera = camera
        self.antialias = bool(antialias)
        self.dr = dr
        self.glctx = dr.RasterizeCudaContext(device=torch.device(rig.device))
        self.device = torch.device(rig.device)
        self.node_count = len(rig.node_names)
        self.base_rotation = torch.stack(
            [self._quat_matrix(node.rotation) for node in rig.asset.nodes], dim=0
        ).to(self.device)
        self.translation = torch.as_tensor(
            np.asarray([node.translation for node in rig.asset.nodes], dtype=np.float32), device=self.device
        )
        self.scale = torch.as_tensor(
            np.asarray([node.scale for node in rig.asset.nodes], dtype=np.float32), device=self.device
        )
        self.parents = rig.parents
        skeleton_mask = torch.zeros(self.node_count, dtype=torch.float32, device=self.device)
        if rig.skeleton_indices:
            skeleton_mask[torch.as_tensor(rig.skeleton_indices, dtype=torch.long, device=self.device)] = 1.0
        self.skeleton_mask = skeleton_mask
        self.camera_right = torch.as_tensor(camera.right, dtype=torch.float32, device=self.device)
        self.camera_down = torch.as_tensor(camera.down, dtype=torch.float32, device=self.device)
        self.camera_forward = torch.as_tensor(camera.forward, dtype=torch.float32, device=self.device)
        self.camera_up = -self.camera_down
        self.camera_axes = torch.stack((self.camera_forward, self.camera_right, self.camera_up), dim=0)
        self._build_triangle_buffers()
        # The bind worlds are part of the resident CUDA renderer state.  The
        # same matrices are reused by the Blender bridge when it serializes a
        # canonical pose, so export does not reconstruct a second skeleton
        # interpretation on the CPU.
        self.rest_worlds = self._forward_kinematics(
            torch.zeros((1, self.node_count, 3), dtype=torch.float32, device=self.device)
        ).detach()

    @staticmethod
    def _quat_matrix(q: Any) -> torch.Tensor:
        value = torch.as_tensor(q, dtype=torch.float32)
        x, y, z, w = value / torch.clamp(torch.linalg.vector_norm(value), min=1e-8)
        return torch.as_tensor(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ],
            dtype=torch.float32,
            device=value.device,
        )

    def _build_triangle_buffers(self) -> None:
        vertex_offset = 0
        triangles = []
        colors = []
        uvs = []
        owners = []
        self.triangle_ranges: list[tuple[int, int]] = []
        self.textured_primitives: list[tuple[int, int, Any, Any]] = []
        triangle_offset = 0
        for primitive in self.rig.primitives:
            triangles.append(primitive.indices + int(vertex_offset))
            colors.append(primitive.vertex_color)
            if primitive.uv is None:
                uvs.append(torch.zeros((primitive.positions.shape[0], 2), dtype=torch.float32, device=self.device))
            else:
                uvs.append(primitive.uv)
            if primitive.bone_owner is None:
                owners.append(torch.full((primitive.positions.shape[0],), -1, dtype=torch.float32, device=self.device))
            else:
                owners.append(primitive.bone_owner.to(torch.float32))
            triangle_count = int(primitive.indices.shape[0])
            self.triangle_ranges.append((triangle_offset, triangle_offset + triangle_count))
            if primitive.texture is not None and primitive.uv is not None:
                self.textured_primitives.append((triangle_offset, triangle_offset + triangle_count, primitive.texture, primitive.color_factor))
            triangle_offset += triangle_count
            vertex_offset += int(primitive.positions.shape[0])
        if not triangles:
            raise ValueError("prepared rig has no triangles")
        self.triangles = torch.cat(triangles, dim=0).contiguous()
        self.bind_colors = torch.cat(colors, dim=0).contiguous()
        self.bind_uv = torch.cat(uvs, dim=0).contiguous()
        self.bind_owners = torch.cat(owners, dim=0).contiguous()
        self.vertex_count = int(vertex_offset)

    def _forward_kinematics(self, bone_rotation: torch.Tensor) -> torch.Tensor:
        batch = int(bone_rotation.shape[0])
        # Only nodes referenced by a glTF skin are bones. Scene containers
        # such as the mesh node and armature root remain at their bind pose.
        bone_rotation = bone_rotation * self.skeleton_mask.view(1, self.node_count, 1)
        mask = _axis_angle_matrix(bone_rotation)
        local_rotation = torch.matmul(self.base_rotation.unsqueeze(0), mask)
        local = torch.zeros((batch, self.node_count, 4, 4), dtype=torch.float32, device=self.device)
        local[..., 3, 3] = 1.0
        local[..., :3, :3] = local_rotation * self.scale.unsqueeze(0).unsqueeze(-2)
        local[..., :3, 3] = self.translation.unsqueeze(0)
        world: list[torch.Tensor | None] = [None] * self.node_count
        visiting: set[int] = set()

        def visit(index: int) -> torch.Tensor:
            if world[index] is not None:
                return world[index]  # type: ignore[return-value]
            if index in visiting:
                raise ValueError("GLB node hierarchy contains a cycle")
            visiting.add(index)
            parent = self.parents[index]
            current = local[:, index]
            world[index] = current if parent is None else torch.matmul(visit(int(parent)), current)
            visiting.remove(index)
            return world[index]  # type: ignore[return-value]

        return torch.stack([visit(index) for index in range(self.node_count)], dim=1)

    def _skinned_vertices(self, worlds: torch.Tensor, primitive: Any) -> tuple[torch.Tensor, torch.Tensor]:
        positions = primitive.positions
        if primitive.skin is None or primitive.joints is None or primitive.weights is None:
            vertices = torch.einsum("bkl,nl->bnk", worlds[:, primitive.node], positions)[..., :3]
            owner = torch.full((vertices.shape[0], vertices.shape[1]), -1.0, dtype=torch.float32, device=self.device)
            return vertices, owner
        skin = self.rig.asset.skins[int(primitive.skin)]
        joints = torch.as_tensor(skin.joints, dtype=torch.long, device=self.device)
        inverse_bind = torch.as_tensor(skin.inverse_bind, dtype=torch.float32, device=self.device)
        joint_matrices = torch.matmul(worlds[:, joints], inverse_bind.unsqueeze(0))
        transformed = torch.einsum("bjkl,nl->bjnk", joint_matrices, positions)
        gather_index = primitive.joints.T.unsqueeze(0).unsqueeze(-1).expand(worlds.shape[0], 4, -1, 4)
        selected = torch.gather(transformed, 1, gather_index)
        weights = primitive.weights / torch.clamp(primitive.weights.sum(dim=1, keepdim=True), min=1e-8)
        skinned = (selected * weights.T.unsqueeze(0).unsqueeze(-1)).sum(dim=1)
        vertices = torch.einsum("bkl,bnl->bnk", worlds[:, primitive.node], skinned)[..., :3]
        return vertices, primitive.bone_owner.to(torch.float32).unsqueeze(0).expand(worlds.shape[0], -1)

    def _camera_vector(self, value: torch.Tensor) -> torch.Tensor:
        return torch.einsum("...i,ij->...j", value, self.camera_axes)

    def _apply_rigid(self, points: torch.Tensor, rotation: torch.Tensor, translation: torch.Tensor, scale: torch.Tensor) -> torch.Tensor:
        pivot = (self.rig.pivot * float(self.rig.mesh_scale)).view(1, 1, 3)
        rotation_world = _axis_angle_matrix(self._camera_vector(rotation))
        displaced = torch.matmul(points - pivot, rotation_world.transpose(-1, -2)) * scale.view(-1, 1, 1)
        offset = self._camera_vector(translation).view(-1, 1, 3)
        return displaced + pivot + offset

    def _project(self, points: torch.Tensor) -> torch.Tensor:
        width, height = self.camera.width, self.camera.height
        pixel_x = torch.einsum("bnk,k->bn", points, self.camera_right) * float(self.camera.px_per_world[0]) + float(self.camera.offset[0])
        pixel_y = torch.einsum("bnk,k->bn", points, self.camera_down) * float(self.camera.px_per_world[1]) + float(self.camera.offset[1])
        depth = torch.einsum("bnk,k->bn", points, self.camera_forward)
        ndc_x = pixel_x / max(width - 1, 1) * 2.0 - 1.0
        ndc_y = 1.0 - pixel_y / max(height - 1, 1) * 2.0
        ndc_z = (depth - float(self.camera.near)) / max(float(self.camera.far - self.camera.near), 1e-6) * 2.0 - 1.0
        return torch.stack((ndc_x, ndc_y, ndc_z, torch.ones_like(ndc_x)), dim=-1)

    def _vertices_for_pose(self, pose: PoseState) -> tuple[torch.Tensor, torch.Tensor]:
        registration = pose.registration
        if registration.ndim == 1:
            registration = registration.unsqueeze(0)
        hypotheses = int(registration.shape[0])
        frames = int(pose.motion_translation.shape[-2])
        bones = pose.bone_rotation
        if bones.ndim == 3:
            bones = bones.unsqueeze(0)
        if pose.motion_translation.ndim == 2:
            motion_translation = pose.motion_translation.unsqueeze(0)
            motion_rotation = pose.motion_rotation.unsqueeze(0)
        else:
            motion_translation = pose.motion_translation
            motion_rotation = pose.motion_rotation
        flat_bones = bones.reshape(hypotheses * frames, self.node_count, 3)
        worlds = self._forward_kinematics(flat_bones)
        vertices: list[torch.Tensor] = []
        owners: list[torch.Tensor] = []
        for primitive in self.rig.primitives:
            value, owner = self._skinned_vertices(worlds, primitive)
            vertices.append(value)
            owners.append(owner)
        points = torch.cat(vertices, dim=1)
        owner = torch.cat(owners, dim=1)
        # Apply the global Meshy mesh scale exactly once, before the shared
        # registration and per-frame motion roots.  This keeps the scale a
        # real geometric parameter instead of changing only the vertex cloud.
        points = points * float(self.rig.mesh_scale)
        reg = registration[:, None, :].expand(hypotheses, frames, -1).reshape(hypotheses * frames, -1)
        mt = motion_translation.reshape(hypotheses * frames, 3)
        mr = motion_rotation.reshape(hypotheses * frames, 3)
        points = self._apply_rigid(
            points,
            reg[:, :3],
            reg[:, 3:6],
            torch.exp(reg[:, 6]).clamp(0.25, 4.0),
        )
        points = self._apply_rigid(points, mr, mt, torch.ones_like(reg[:, 6]))
        return points, owner

    def render(self, pose: PoseState) -> RenderBuffers:
        points, owners = self._vertices_for_pose(pose)
        clip = self._project(points).contiguous()
        rast, rast_db = self.dr.rasterize(
            self.glctx,
            clip,
            self.triangles,
            resolution=[self.camera.height, self.camera.width],
        )
        covered = (rast[..., 3:4] > 0).to(torch.float32)
        if self.antialias:
            # nvdiffrast's antialias kernel requires an RGBA image. Keep the
            # coverage in alpha and discard the three color channels after it
            # has produced differentiable edge coverage.
            coverage_rgba = torch.cat((torch.zeros_like(covered).expand(-1, -1, -1, 3), covered), dim=-1)
            alpha = self.dr.antialias(coverage_rgba, rast, clip, self.triangles)[..., 3].clamp(0.0, 1.0)
        else:
            alpha = covered[..., 0]
        color_attr = self.bind_colors.unsqueeze(0).expand(points.shape[0], -1, -1)
        rgb = self.dr.interpolate(color_attr.contiguous(), rast, self.triangles)[0].clamp(0.0, 1.0)
        if self.textured_primitives:
            uv_attr = self.bind_uv.unsqueeze(0).expand(points.shape[0], -1, -1)
            pixel_uv = self.dr.interpolate(uv_attr.contiguous(), rast, self.triangles)[0]
            raw_triangle_id = rast[..., 3].to(torch.long) - 1
            for start, end, texture, factor in self.textured_primitives:
                covered_primitive = (raw_triangle_id >= int(start)) & (raw_triangle_id < int(end))
                texture_rgb = texture[..., :3].permute(2, 0, 1).unsqueeze(0)
                texture_rgb = texture_rgb.expand(points.shape[0], -1, -1, -1)
                grid = gltf_uv_to_grid_sample(pixel_uv)
                sampled = F.grid_sample(texture_rgb, grid, mode="bilinear", padding_mode="border", align_corners=True)
                sampled = (sampled.permute(0, 2, 3, 1) * factor.view(1, 1, 1, 3)).clamp(0.0, 1.0)
                rgb = torch.where(covered_primitive.unsqueeze(-1), sampled, rgb)
        depth_attr = torch.einsum("bnk,k->bn", points, self.camera_forward).unsqueeze(-1)
        depth = self.dr.interpolate(depth_attr.contiguous(), rast, self.triangles)[0][..., 0]
        world_position = self.dr.interpolate(points.contiguous(), rast, self.triangles)[0]
        owner_attr = owners.unsqueeze(-1).contiguous()
        dominant_bone = self.dr.interpolate(owner_attr, rast, self.triangles)[0][..., 0]
        triangle_id = rast[..., 3].to(torch.long) - 1
        barycentrics = rast[..., :3]
        # Per-frame vertex normals are derived from the same deformed triangle
        # positions as alpha/depth. This is cheap relative to rasterization and
        # avoids a second normal/skinning implementation in the Blender bridge.
        triangle_points = points[:, self.triangles.to(torch.long)]
        face_normals = torch.cross(
            triangle_points[:, :, 1] - triangle_points[:, :, 0],
            triangle_points[:, :, 2] - triangle_points[:, :, 0],
            dim=-1,
        )
        vertex_normals = torch.zeros_like(points)
        for corner in range(3):
            indices = self.triangles[:, corner].to(torch.long).view(1, -1, 1).expand(points.shape[0], -1, 3)
            vertex_normals.scatter_add_(1, indices, face_normals)
        vertex_normals = F.normalize(vertex_normals, dim=-1, eps=1e-8)
        normal = self.dr.interpolate(vertex_normals.contiguous(), rast, self.triangles)[0]
        # nvdiffrast stores raster rows from the bottom of the NDC viewport,
        # while PNG/DEF tensors and PreparedClip masks are top-origin.  Keep
        # this conversion at the renderer boundary so objectives, previews,
        # and Blender parity all consume the same image convention.
        def top_origin(value: torch.Tensor) -> torch.Tensor:
            return torch.flip(value, dims=(1,))

        rgb = top_origin(rgb)
        alpha = top_origin(alpha)
        depth = top_origin(depth)
        world_position = top_origin(world_position)
        dominant_bone = top_origin(dominant_bone)
        triangle_id = top_origin(triangle_id)
        barycentrics = top_origin(barycentrics)
        normal = top_origin(normal)
        hypotheses = int(pose.registration.shape[0] if pose.registration.ndim > 1 else 1)
        frames = int(pose.motion_translation.shape[-2])
        def reshape(value: torch.Tensor) -> torch.Tensor:
            return value.reshape(hypotheses, frames, *value.shape[1:])
        return RenderBuffers(
            rgb=reshape(rgb),
            alpha=reshape(alpha),
            depth=reshape(depth),
            triangle_id=reshape(triangle_id),
            barycentrics=reshape(barycentrics),
            world_position=reshape(world_position),
            normal=reshape(normal),
            dominant_bone=reshape(dominant_bone),
        )

    def render_single(self, pose: PoseState) -> RenderBuffers:
        result = self.render(pose)
        if int(result.alpha.shape[0]) != 1:
            raise ValueError("render_single requires exactly one hypothesis")
        return result

    def canonical_deformation_matrices(
        self,
        pose: PoseState,
        *,
        hypothesis_index: int = 0,
        frame_index: int = 0,
    ) -> dict[str, list[list[float]]]:
        """Serialize the exact V2 deformation for one frame in glTF space.

        Registration and motion are deliberately composed here, after FK/LBS
        has been defined by the renderer.  The Blender bridge converts these
        relative matrices to Blender's basis but does not reinterpret bone
        axes, Euler order, root pivots, or Meshy rolls.
        """
        registration = pose.registration
        if registration.ndim == 1:
            registration = registration.unsqueeze(0)
        motion_translation = pose.motion_translation
        motion_rotation = pose.motion_rotation
        bone_rotation = pose.bone_rotation
        if motion_translation.ndim == 2:
            motion_translation = motion_translation.unsqueeze(0)
            motion_rotation = motion_rotation.unsqueeze(0)
        if bone_rotation.ndim == 3:
            bone_rotation = bone_rotation.unsqueeze(0)
        hypothesis_index = int(hypothesis_index)
        frame_index = int(frame_index)
        if not 0 <= hypothesis_index < int(registration.shape[0]):
            raise IndexError("hypothesis_index is outside the pose state")
        if not 0 <= frame_index < int(bone_rotation.shape[1]):
            raise IndexError("frame_index is outside the pose state")
        current_worlds = self._forward_kinematics(
            bone_rotation[hypothesis_index, frame_index].unsqueeze(0)
        )[0]

        def rigid_matrix(rotation: torch.Tensor, translation: torch.Tensor, scale: torch.Tensor) -> torch.Tensor:
            rotation_world = _axis_angle_matrix(self._camera_vector(rotation.unsqueeze(0)))[0]
            scale_value = scale.reshape(()).clamp(0.25, 4.0)
            pivot = self.rig.pivot * float(self.rig.mesh_scale)
            linear = rotation_world * scale_value
            offset = self._camera_vector(translation.unsqueeze(0))[0]
            matrix = torch.eye(4, dtype=torch.float32, device=self.device)
            matrix[:3, :3] = linear
            matrix[:3, 3] = pivot + offset - torch.matmul(linear, pivot)
            return matrix

        reg = registration[hypothesis_index]
        static_matrix = rigid_matrix(reg[:3], reg[3:6], torch.exp(reg[6]))
        motion_matrix = rigid_matrix(
            motion_rotation[hypothesis_index, frame_index],
            motion_translation[hypothesis_index, frame_index],
            torch.ones((), dtype=torch.float32, device=self.device),
        )
        mesh_scale = torch.eye(4, dtype=torch.float32, device=self.device)
        mesh_scale[:3, :3] *= float(self.rig.mesh_scale)
        global_matrix = torch.matmul(torch.matmul(motion_matrix, static_matrix), mesh_scale)
        matrices: dict[str, list[list[float]]] = {}
        for index, name in enumerate(self.rig.node_names):
            deformation = torch.matmul(
                torch.matmul(global_matrix, current_worlds[index]),
                torch.linalg.inv(self.rest_worlds[0, index]),
            )
            matrices[str(name)] = deformation.detach().cpu().tolist()
        return matrices
