"""ComfyUI node: attach SparseLatticeEncoder tokens to an SD3 MODEL."""

from __future__ import annotations

import sys
from pathlib import Path

import torch
from PIL import Image
from torch import Tensor

_REPO_LOCAL = Path(__file__).resolve().parents[2]  # tools/local_imagegen
if str(_REPO_LOCAL) not in sys.path:
    sys.path.insert(0, str(_REPO_LOCAL))

from sparse_token_condition.encoder import SparseLatticeEncoder  # noqa: E402
from sparse_token_condition.inject import attach_sparse_tokens_to_model  # noqa: E402
from sparse_token_condition.observations import (  # noqa: E402
    build_sparse_observations,
    observations_to_tensor,
)


def _tensor_bhwc_to_pil(image: Tensor) -> Image.Image:
    # Comfy IMAGE: BHWC float [0,1]
    if image.ndim != 4:
        raise ValueError(f"expected BHWC image tensor, got {tuple(image.shape)}")
    arr = (image[0, ..., :3].detach().clamp(0, 1).cpu().numpy() * 255.0).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


class SparseLatticeCondition:
    """Encode TwCrPort lattice → K tokens and patch MODEL to concat onto c_crossattn."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "portrait": ("IMAGE",),
                "scale": ("INT", {"default": 16, "min": 2, "max": 64}),
                "enabled": ("BOOLEAN", {"default": True}),
                "weights_path": ("STRING", {"default": ""}),
                "num_latents": ("INT", {"default": 128, "min": 8, "max": 512}),
                "token_dim": ("INT", {"default": 4096, "min": 64, "max": 8192}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "conditioning/sparse_lattice"

    def apply(
        self,
        model,
        portrait: Tensor,
        scale: int,
        enabled: bool = True,
        weights_path: str = "",
        num_latents: int = 128,
        token_dim: int = 4096,
    ):
        # Clone patcher options so we do not mutate the upstream node permanently.
        m = model.clone()
        if not enabled:
            return (m,)

        lr = _tensor_bhwc_to_pil(portrait)
        obs_np, _coords = build_sparse_observations(lr, scale=int(scale))
        obs = observations_to_tensor(obs_np)

        weights_path = (weights_path or "").strip()
        enc_kwargs = {
            "token_dim": int(token_dim),
            "num_latents": int(num_latents),
        }
        state = None
        if weights_path:
            path = Path(weights_path)
            if not path.is_file():
                raise FileNotFoundError(f"sparse lattice weights not found: {path}")
            blob = torch.load(path, map_location="cpu", weights_only=False)
            if isinstance(blob, dict) and "encoder" in blob:
                state = blob["encoder"]
                cfg = blob.get("config") or {}
                if "token_dim" in cfg:
                    enc_kwargs["token_dim"] = int(cfg["token_dim"])
                if "num_latents" in cfg:
                    enc_kwargs["num_latents"] = int(cfg["num_latents"])
                if "embed_dim" in cfg:
                    enc_kwargs["embed_dim"] = int(cfg["embed_dim"])
                if "num_heads" in cfg:
                    enc_kwargs["num_heads"] = int(cfg["num_heads"])
            else:
                state = blob
        enc = SparseLatticeEncoder(**enc_kwargs)
        if state is not None:
            enc.load_state_dict(state, strict=True)
        enc.eval()

        device = m.load_device if hasattr(m, "load_device") else torch.device("cuda")
        enc = enc.to(device=device)
        with torch.no_grad():
            tokens = enc(obs.to(device=device))
        attach_sparse_tokens_to_model(m, tokens)
        return (m,)


NODE_CLASS_MAPPINGS = {
    "SparseLatticeCondition": SparseLatticeCondition,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SparseLatticeCondition": "Sparse Lattice Condition (SD3)",
}
