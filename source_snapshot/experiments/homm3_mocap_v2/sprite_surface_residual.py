"""Direct source-frame correction field; diagnostic capacity, not acceptance."""
from __future__ import annotations

import math
import torch
from torch import nn


class SpriteSurfaceResidual(nn.Module):
    """Independent selected-frame controls over explicitly selected vertices.

    Exact rest-position and skin-weight equality identifies shared deformation
    trajectories. The displacement budget is diagnostic, not a quality gate.
    The caller owns which source frames this field represents.
    """

    def __init__(self, vertices, weights, vertex_ids, frame_count,
                 max_displacement_fraction=.25, device="cpu"):
        super().__init__()
        rest = torch.as_tensor(vertices).detach().cpu()
        skin = torch.as_tensor(weights).detach().cpu()
        if (rest.ndim != 2 or rest.shape[1] != 3 or not len(rest)
                or not torch.isfinite(rest).all()):
            raise ValueError("vertices must be finite nonempty [V,3]")
        if (skin.ndim != 2 or skin.shape[0] != len(rest) or skin.shape[1] == 0
                or not torch.isfinite(skin).all() or bool((skin < 0).any())
                or bool((skin.sum(-1) <= 0).any())):
            raise ValueError("weights must be finite nonnegative [V,J] with positive rows")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
            raise ValueError("frame_count must be a positive integer")
        fraction = float(max_displacement_fraction)
        if not math.isfinite(fraction) or fraction < 0:
            raise ValueError("max_displacement_fraction must be finite and nonnegative")
        diagonal = float(torch.linalg.vector_norm(rest.double().amax(0) - rest.double().amin(0)))
        if not math.isfinite(diagonal) or diagonal <= 0:
            raise ValueError("vertices must span a finite nonzero bounding box")
        ids = torch.as_tensor(vertex_ids)
        if (ids.ndim != 1 or ids.numel() == 0 or ids.dtype == torch.bool
                or ids.is_floating_point() or ids.is_complex()
                or bool((ids < 0).any()) or bool((ids >= len(rest)).any())):
            raise ValueError("vertex_ids must be nonempty valid integer indices")
        selected = set(ids.tolist())
        # Group before float32 conversion, so nearby values never become evidence
        # of an exact duplicate merely because the learnable field is float32.
        groups = {}
        for index in range(len(rest)):
            key = (tuple(rest[index].tolist()), tuple(skin[index].tolist()))
            groups.setdefault(key, []).append(index)
        active = [members for members in groups.values() if selected.intersection(members)]
        support = torch.zeros(len(rest), dtype=torch.bool)
        mapping = torch.zeros(len(rest), dtype=torch.long)
        for group, members in enumerate(active):
            support[members] = True
            mapping[members] = group
        self.register_buffer("support_mask", support.to(device))
        self.register_buffer("vertex_groups", mapping.to(device))
        self.max_displacement = fraction * diagonal
        if not math.isfinite(self.max_displacement):
            raise ValueError("displacement budget must be finite")
        self.controls = nn.Parameter(torch.zeros((frame_count, len(active), 3), device=device))

    def displacement(self):
        if not bool(torch.isfinite(self.controls).all()):
            raise ValueError("correction controls contain nonfinite values")
        # Radial projection bounds the vector norm, not each coordinate.
        controls = self.controls.double()
        norm = torch.linalg.vector_norm(controls, dim=-1, keepdim=True)
        bounded = (controls / norm.clamp_min(1.0) * self.max_displacement).to(self.controls.dtype)
        expanded = bounded[:, self.vertex_groups]
        return torch.where(self.support_mask[None, :, None], expanded, torch.zeros_like(expanded))

    def forward(self):
        return self.displacement()
