"""Perceiver-style sparse lattice → fixed K context tokens for SD3."""

from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


def fourier_features(xy: torch.Tensor, num_frequencies: int = 8) -> torch.Tensor:
    """xy: (..., 2) in [0,1] → (..., 4*num_frequencies) sin/cos features."""
    freqs = (2.0 ** torch.arange(num_frequencies, device=xy.device, dtype=xy.dtype)) * math.pi
    angles = xy.unsqueeze(-1) * freqs  # (..., 2, F)
    return torch.cat([angles.sin(), angles.cos()], dim=-1).flatten(-2)


class SparseLatticeEncoder(nn.Module):
    """Encode N sparse (y,x,rgb) observations into K tokens of width ``token_dim``.

    Tokens are sized for SD3 ``c_crossattn`` *before* ``context_embedder``
    (typically 4096 for T5-joint context).
    """

    def __init__(
        self,
        *,
        token_dim: int = 4096,
        num_latents: int = 128,
        num_frequencies: int = 8,
        embed_dim: int = 512,
        num_heads: int = 8,
        num_layers: int = 2,
    ) -> None:
        super().__init__()
        if token_dim <= 0 or num_latents <= 0:
            raise ValueError("token_dim and num_latents must be positive")
        if embed_dim % num_heads != 0:
            raise ValueError("embed_dim must be divisible by num_heads")
        self.token_dim = int(token_dim)
        self.num_latents = int(num_latents)
        self.num_frequencies = int(num_frequencies)

        in_dim = 4 * num_frequencies + 3  # fourier(x,y) + rgb
        self.obs_mlp = nn.Sequential(
            nn.Linear(in_dim, embed_dim),
            nn.GELU(),
            nn.Linear(embed_dim, embed_dim),
        )
        self.latents = nn.Parameter(torch.randn(1, num_latents, embed_dim) * 0.02)
        self.cross_layers = nn.ModuleList(
            [
                nn.MultiheadAttention(
                    embed_dim, num_heads, batch_first=True, dropout=0.0
                )
                for _ in range(num_layers)
            ]
        )
        self.cross_norms = nn.ModuleList(
            [nn.LayerNorm(embed_dim) for _ in range(num_layers)]
        )
        self.out_proj = nn.Linear(embed_dim, token_dim)

    def encode_observations(self, obs: torch.Tensor) -> torch.Tensor:
        """obs: (B, N, 5) or (N, 5) → (B, K, token_dim)."""
        if obs.ndim == 2:
            obs = obs.unsqueeze(0)
        if obs.ndim != 3 or obs.shape[-1] != 5:
            raise ValueError(f"expected (B,N,5) or (N,5), got {tuple(obs.shape)}")
        xy = obs[..., 0:2]
        rgb = obs[..., 2:5]
        feat = torch.cat([fourier_features(xy, self.num_frequencies), rgb], dim=-1)
        kv = self.obs_mlp(feat)
        q = self.latents.expand(obs.shape[0], -1, -1)
        for attn, norm in zip(self.cross_layers, self.cross_norms):
            out, _ = attn(q, kv, kv, need_weights=False)
            q = norm(q + out)
        return self.out_proj(q)

    def forward(
        self,
        obs: torch.Tensor,
        *,
        drop_prob: float = 0.0,
        force_drop: bool | None = None,
    ) -> torch.Tensor:
        """Return (B, K, token_dim). With drop_prob, whole-batch token dropout for CFG."""
        tokens = self.encode_observations(obs)
        if force_drop is True:
            return torch.zeros_like(tokens)
        if force_drop is False:
            return tokens
        if self.training and drop_prob > 0.0:
            # Per-sample Bernoulli dropout of the entire sparse token set.
            keep = (torch.rand(tokens.shape[0], 1, 1, device=tokens.device) >= drop_prob).to(
                tokens.dtype
            )
            tokens = tokens * keep
        return tokens


def self_check() -> None:
    enc = SparseLatticeEncoder(token_dim=64, num_latents=8, embed_dim=32, num_heads=4)
    obs = torch.rand(2, 12, 5)
    out = enc(obs)
    if out.shape != (2, 8, 64):
        raise AssertionError(f"bad shape {tuple(out.shape)}")
    dropped = enc(obs, force_drop=True)
    if dropped.abs().sum().item() != 0.0:
        raise AssertionError("force_drop did not zero tokens")
    print("encoder.self_check OK", flush=True)


if __name__ == "__main__":
    self_check()
