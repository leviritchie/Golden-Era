"""Torch objective for fixed CPU-built joint anchors."""
from __future__ import annotations

from typing import Any

import torch


class FixedJointAnchorObjective(torch.nn.Module):
    """Measure animated anchor points against immutable joint-world origins."""

    def __init__(self, model: dict[str, Any], joint_world: Any, vertex_count: int, device: Any):
        super().__init__()
        if not isinstance(model, dict) or model.get("schema") != "skin-joint-anchor-model-v1":
            raise ValueError("invalid joint-anchor model")
        names = model.get("jointNames")
        if not isinstance(names, list) or not names:
            raise ValueError("anchor model has no joint inventory")
        matrices = torch.as_tensor(joint_world, dtype=torch.float32, device=device).detach().clone()
        if matrices.ndim != 4 or matrices.shape[1:] != (len(names), 4, 4) or not torch.isfinite(matrices).all():
            raise ValueError("joint_world must be finite [F,J,4,4]")
        if isinstance(vertex_count, bool) or not isinstance(vertex_count, int) or vertex_count < 1:
            raise ValueError("vertex_count must be a positive integer")
        supported = []
        unsupported = []
        for region, chain in model.get("chains", {}).items():
            if not isinstance(chain, dict):
                raise ValueError("anchor chain is malformed")
            for joint_text, anchor in chain.get("joints", {}).items():
                joint_id = int(joint_text)
                if not 0 <= joint_id < len(names) or not isinstance(anchor, dict):
                    raise ValueError("anchor joint is malformed")
                if not anchor.get("supported"):
                    unsupported.append({"region": region, "joint": names[joint_id]})
                    continue
                raw_ids = anchor.get("vertexIds")
                if (not isinstance(raw_ids, list)
                        or any(isinstance(value, bool) or not isinstance(value, int)
                              for value in raw_ids)
                        or len(set(raw_ids)) != len(raw_ids)):
                    raise ValueError("supported anchor vertex IDs must be integer values")
                ids = torch.as_tensor(raw_ids, dtype=torch.long, device=device).detach().clone()
                coeff = torch.as_tensor(anchor.get("coefficients"), dtype=torch.float32, device=device).detach().clone()
                length = float(anchor.get("adjacentSegmentLength", 0.0))
                if (ids.ndim != 1 or coeff.shape != ids.shape or not len(ids)
                        or torch.any(ids < 0) or torch.any(ids >= vertex_count)
                        or not torch.isfinite(coeff).all() or torch.any(coeff < 0)
                        or not torch.isclose(coeff.sum(), torch.ones((), device=device), atol=1e-6, rtol=0)
                        or not torch.isfinite(torch.tensor(length)) or not length > 0):
                    raise ValueError("supported anchor support/normalization is malformed")
                supported.append((region, joint_id, ids, coeff, length))
        if not supported:
            raise ValueError("anchor model has no supported anchors")
        self.vertex_count = vertex_count
        self.supported_count = len(supported)
        self.unsupported = unsupported
        self._joint_names = names
        self._supported_names = [{"region": region, "joint": names[joint_id]} for region, joint_id, *_ in supported]
        self.register_buffer("joint_world", matrices, persistent=False)
        self._anchors = supported

    def forward(self, animated: torch.Tensor) -> torch.Tensor:
        if not isinstance(animated, torch.Tensor) or animated.ndim != 3 or not animated.is_floating_point():
            raise ValueError("animated must be a floating-point torch tensor [F,V,3]")
        if animated.shape[0] != self.joint_world.shape[0] or animated.shape[1] != self.vertex_count or animated.shape[2] != 3:
            raise ValueError("animated shape does not match fixed joint-world/vertex inventory")
        if not torch.isfinite(animated).all():
            raise ValueError("animated mesh must be finite")
        losses = []
        for _, joint_id, ids, coeff, length in self._anchors:
            tracked = torch.sum(animated[:, ids, :] * coeff[None, :, None], dim=1)
            target = self.joint_world[:, joint_id, :3, 3]
            losses.append(torch.sum((tracked - target) ** 2, dim=1) / (length * length))
        return torch.stack(losses, dim=1).mean()

    def loss(self, animated: torch.Tensor) -> torch.Tensor:
        """Optimizer-facing alias for the fixed-anchor objective."""
        return self.forward(animated)

    def report(self) -> dict[str, Any]:
        return {"supportedAnchorCount": self.supported_count,
                "supportedJoints": list(self._supported_names),
                "unsupportedJoints": list(self.unsupported),
                "jointWorldFixed": True, "coefficientsFixed": True}


__all__ = ["FixedJointAnchorObjective"]
