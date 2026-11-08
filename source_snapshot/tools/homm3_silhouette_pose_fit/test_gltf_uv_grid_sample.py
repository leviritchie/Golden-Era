"""glTF UV (0,0) is the top of a PIL texture, not OpenGL's bottom-left."""
from __future__ import annotations

import torch
import torch.nn.functional as F

from roc_geometric_proxy import gltf_uv_to_grid_sample


def run() -> dict[str, object]:
    # Row 0 is the top of the PNG. Red on top, blue on the bottom.
    texture = torch.zeros((1, 3, 2, 2), dtype=torch.float32)
    texture[0, 0, 0, :] = 1.0
    texture[0, 2, 1, :] = 1.0
    top_uv = torch.tensor([[[[0.5, 0.0]]]], dtype=torch.float32)
    bottom_uv = torch.tensor([[[[0.5, 1.0]]]], dtype=torch.float32)
    top = F.grid_sample(
        texture, gltf_uv_to_grid_sample(top_uv), mode="bilinear",
        padding_mode="border", align_corners=True,
    )[0, :, 0, 0]
    bottom = F.grid_sample(
        texture, gltf_uv_to_grid_sample(bottom_uv), mode="bilinear",
        padding_mode="border", align_corners=True,
    )[0, :, 0, 0]
    opengl = torch.stack((top_uv[..., 0] * 2.0 - 1.0, 1.0 - top_uv[..., 1] * 2.0), dim=-1)
    inverted = F.grid_sample(
        texture, opengl, mode="bilinear", padding_mode="border", align_corners=True,
    )[0, :, 0, 0]
    assert float(top[0]) > 0.9, top
    assert float(top[2]) < 0.1, top
    assert float(bottom[2]) > 0.9, bottom
    assert float(bottom[0]) < 0.1, bottom
    assert float(inverted[2]) > 0.9, inverted
    return {
        "ok": True,
        "top": [float(value) for value in top],
        "bottom": [float(value) for value in bottom],
        "openglWouldSampleBottomAtV0": [float(value) for value in inverted],
    }


if __name__ == "__main__":
    print(run())
