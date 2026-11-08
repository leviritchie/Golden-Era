"""Branch scoring stays complete while rasters stay inside a VRAM cap."""
from __future__ import annotations

import torch

from gpu_depth_silhouette_solver import DepthSilhouetteConfig, score_raster_chunks
from gpu_mesh_collision import linear_blend_skin_vertices


class _SkinPrimitive:
    def __init__(self) -> None:
        self.node = 0
        self.skin_joints = torch.tensor([0, 1], dtype=torch.long)
        self.inverse_bind = torch.eye(4).repeat(2, 1, 1)
        self.joints = torch.tensor([[0, 1], [1, 0]], dtype=torch.long)
        self.normalized_weights = torch.tensor(
            [[0.75, 0.25], [0.10, 0.90]],
            dtype=torch.float32,
        )
        self.homogeneous_positions = torch.tensor(
            [
                [0.0, 0.0, 0.0, 1.0],
                [1.0, 2.0, 3.0, 1.0],
            ],
            dtype=torch.float32,
        )


def _expanded_skin(worlds: torch.Tensor, primitive: _SkinPrimitive) -> torch.Tensor:
    """Reference copy of the old [batch, verts, influences, 4, 4] formula."""
    joint_matrices = torch.matmul(
        worlds[:, primitive.skin_joints],
        primitive.inverse_bind.unsqueeze(0),
    )
    influences = primitive.joints
    vertex_count = int(primitive.homogeneous_positions.shape[0])
    influence_count = int(influences.shape[1])
    mats = joint_matrices[:, influences]
    posed = torch.matmul(
        mats,
        primitive.homogeneous_positions.view(1, vertex_count, 1, 4, 1),
    ).squeeze(-1)
    skinned = (posed * primitive.normalized_weights.view(1, vertex_count, influence_count, 1)).sum(dim=2)
    return torch.einsum("bkl,bnl->bnk", worlds[:, primitive.node], skinned)[..., :3]


def run() -> dict[str, object]:
    DepthSilhouetteConfig(score_raster_batch=128).validate()
    try:
        DepthSilhouetteConfig(score_raster_batch=0).validate()
        raise AssertionError("score_raster_batch=0 must stay fail-closed")
    except ValueError as exc:
        assert "score_raster_batch" in str(exc), str(exc)

    chunks = score_raster_chunks(441, 128)
    assert chunks == ((0, 128), (128, 256), (256, 384), (384, 441)), chunks
    assert score_raster_chunks(1, 128) == ((0, 1),)
    assert score_raster_chunks(128, 128) == ((0, 128),)
    try:
        score_raster_chunks(441, 0)
        raise AssertionError("zero raster cap must stay fail-closed")
    except ValueError as exc:
        assert "score_raster_batch" in str(exc), str(exc)

    primitive = _SkinPrimitive()
    worlds = torch.eye(4).repeat(3, 2, 1, 1)
    worlds[1, 0, :3, 3] = torch.tensor([4.0, 0.0, 0.0])
    worlds[2, 1, :3, 3] = torch.tensor([0.0, 5.0, 0.0])
    looped = linear_blend_skin_vertices(
        worlds,
        primitive,
        primitive.homogeneous_positions,
        primitive.joints,
        primitive.normalized_weights,
    )
    expanded = _expanded_skin(worlds, primitive)
    delta = float(torch.max(torch.abs(looped - expanded)).item())
    assert delta < 1e-6, delta

    return {
        "ok": True,
        "chunks": [list(item) for item in chunks],
        "lbsDelta": delta,
    }


if __name__ == "__main__":
    print(run())
