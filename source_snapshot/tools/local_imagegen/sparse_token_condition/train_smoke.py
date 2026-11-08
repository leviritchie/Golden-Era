#!/usr/bin/env python3
"""Encoder-only self-supervised train smoke for SparseLatticeEncoder + frozen SD3.5.

Contract:
  - Condition = sparse NN lattice tokens only (no Stage A image encode as cond)
  - Freeze SD3 MMDiT; train encoder so flow-matching loss responds to tokens
  - Caches/weights stay on V:

Proof bar: loss moves + encoder grad norms non-zero. CGI quality not claimed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.optim import AdamW

_HERE = Path(__file__).resolve().parent
_LOCAL = _HERE.parent
_ROOT = _HERE.parents[2]
_COMFY = Path("V:/ml/ComfyUI")
for p in (_LOCAL, str(_COMFY)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sparse_token_condition.encoder import SparseLatticeEncoder  # noqa: E402
from sparse_token_condition.inject import concat_sparse_tokens_to_context  # noqa: E402
from sparse_token_condition.observations import (  # noqa: E402
    build_sparse_observations,
    observations_to_tensor,
)


DEFAULT_CKPT = Path(
    "V:/ml/ComfyUI/models/checkpoints/sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors"
)
DEFAULT_OUT = Path("V:/ml/models/sparse_lattice/smoke.pt")


def _pil_to_bchw(img: Image.Image) -> torch.Tensor:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    t = torch.from_numpy(arr).movedim(-1, 0).unsqueeze(0)  # 1CHW
    return t * 2.0 - 1.0


def _make_train_canvas(portrait: Image.Image, size: int, scale: int) -> tuple[Image.Image, Image.Image]:
    """Build HR canvas + LR by NEAREST so lattice is exact.

    HR is a soft upsample of the portrait only as *training target content*,
    not as conditioner. Conditioner still uses LR lattice only.
    """
    lr_w = size // scale
    lr_h = size // scale
    if lr_w < 2 or lr_h < 2:
        raise SystemExit(f"size {size} / scale {scale} too small")
    # Fit portrait into LR via NEAREST (no soft blur into LR samples).
    lr = portrait.convert("RGB").resize((lr_w, lr_h), Image.Resampling.NEAREST)
    # Target HR: block-nearest expand of LR (dense target for VAE encode only).
    hr = lr.resize((size, size), Image.Resampling.NEAREST)
    return hr, lr


def _load_sd3(ckpt: Path):
    import comfy.model_management as model_management
    import comfy.sd

    # Prefer keeping UNet on GPU for the short smoke (16GB card).
    model_management.vram_state = model_management.VRAMState.HIGH_VRAM
    out = comfy.sd.load_checkpoint_guess_config(
        str(ckpt),
        output_vae=True,
        output_clip=True,
        output_model=True,
    )
    # Comfy returns (model, clip, vae, clipvision)
    model, clip, vae = out[0], out[1], out[2]
    return model, clip, vae


def _encode_empty_text(clip) -> tuple[torch.Tensor, torch.Tensor]:
    tokens = clip.tokenize("")
    cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
    if pooled is None:
        raise RuntimeError("SD3 clip encode returned no pooled output")
    return cond, pooled


@torch.no_grad()
def _vae_encode(vae, pixels_bchw_m11: torch.Tensor) -> torch.Tensor:
    # Comfy VAE expects BCHW in roughly [-1,1] via process_input inside encode
    pixels = pixels_bchw_m11
    # convert to BHWC [0,1] for comfy VAE.encode API used by nodes
    bhwc = ((pixels + 1.0) * 0.5).clamp(0, 1).movedim(1, -1)
    z = vae.encode(bhwc[:, :, :, :3])
    return z


def train(args: argparse.Namespace) -> int:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    portrait = Image.open(args.portrait).convert("RGB")
    hr, lr = _make_train_canvas(portrait, args.size, args.scale)
    obs_np, _ = build_sparse_observations(lr, scale=args.scale)
    obs = observations_to_tensor(obs_np).to(device)

    print(f"[train_smoke] loading SD3 from {args.ckpt}", flush=True)
    model_patcher, clip, vae = _load_sd3(args.ckpt)
    diffusion = model_patcher.model
    for p in diffusion.parameters():
        p.requires_grad_(False)
    diffusion.eval()

    # Move pieces as Comfy expects
    import comfy.model_management as model_management

    model_management.load_models_gpu([model_patcher, clip.patcher, vae.patcher])

    with torch.no_grad():
        text_ctx, pooled = _encode_empty_text(clip)
        text_ctx = text_ctx.to(device)
        pooled = pooled.to(device)
        x0_raw = _vae_encode(vae, _pil_to_bchw(hr).to(device))
        if x0_raw.ndim == 5:
            x0_raw = x0_raw[:, :, 0]
        # SD3 latent_format shift/scale (same as sampler path).
        x0 = diffusion.process_latent_in(x0_raw).to(device)
        if text_ctx.shape[-1] != args.token_dim:
            raise SystemExit(
                f"token_dim {args.token_dim} != SD3 context width {text_ctx.shape[-1]}"
            )

    enc = SparseLatticeEncoder(
        token_dim=args.token_dim,
        num_latents=args.num_latents,
        embed_dim=args.embed_dim,
        num_heads=args.num_heads,
    ).to(device)
    opt = AdamW(enc.parameters(), lr=args.lr)

    losses: list[float] = []
    grad_norms: list[float] = []

    print(
        f"[train_smoke] steps={args.steps} size={args.size} scale={args.scale} "
        f"obs={obs.shape[0]} K={args.num_latents} token_dim={args.token_dim} "
        f"latent={tuple(x0.shape)} ctx={tuple(text_ctx.shape)}",
        flush=True,
    )

    enc.train()
    for step in range(args.steps):
        opt.zero_grad(set_to_none=True)
        noise = torch.randn_like(x0)
        # SD3 / CONST flow: xt = (1-sigma)*x0 + sigma*noise
        # apply_model returns denoised x0 estimate (CONST.calculate_denoised).
        sigma = torch.rand((), device=device).clamp(1e-4, 0.999)
        xt = (1.0 - sigma) * x0 + sigma * noise
        target = x0

        tokens = enc(obs.unsqueeze(0), drop_prob=args.drop_prob)
        ctx = concat_sparse_tokens_to_context(
            text_ctx, tokens, cond_or_uncond=None
        )

        # Timestep embedding expects batched sigma
        ts = sigma.view(1).expand(xt.shape[0])
        pred = diffusion.apply_model(
            xt,
            ts,
            c_crossattn=ctx,
            y=pooled,
        )
        loss = torch.nn.functional.mse_loss(pred, target)
        loss.backward()
        gn = torch.nn.utils.clip_grad_norm_(enc.parameters(), 1.0)
        opt.step()

        losses.append(float(loss.detach().cpu()))
        grad_norms.append(float(gn.detach().cpu() if torch.is_tensor(gn) else gn))
        if step % max(1, args.steps // 10) == 0 or step == args.steps - 1:
            print(
                f"  step {step:04d} loss={losses[-1]:.5f} grad_norm={grad_norms[-1]:.5f}",
                flush=True,
            )

    if not any(g > 0.0 for g in grad_norms):
        raise SystemExit("FAIL: encoder grad_norm stayed 0 — injection/train path dead")
    if losses[-1] >= losses[0] and args.steps >= 20:
        print(
            f"[train_smoke] WARNING: loss did not drop ({losses[0]:.5f} -> {losses[-1]:.5f})",
            flush=True,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "local_imagegen.sparse_token_condition.smoke.v1",
        "encoder": enc.state_dict(),
        "config": {
            "token_dim": args.token_dim,
            "num_latents": args.num_latents,
            "embed_dim": args.embed_dim,
            "num_heads": args.num_heads,
            "scale": args.scale,
            "size": args.size,
        },
        "train": {
            "steps": args.steps,
            "lr": args.lr,
            "drop_prob": args.drop_prob,
            "losses": losses,
            "grad_norms": grad_norms,
            "portrait": str(Path(args.portrait).resolve()),
            "ckpt": str(Path(args.ckpt).resolve()),
        },
        "proof": (
            "Encoder-only SD3.5 flow-matching smoke on sparse lattice tokens. "
            "Collapse invent CGI unproven; this checkpoint only proves train plumbing."
        ),
    }
    torch.save(payload, args.out)
    meta_path = args.out.with_suffix(".json")
    meta = {
        k: v
        for k, v in payload.items()
        if k != "encoder"
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {args.out}", flush=True)
    print(f"wrote {meta_path}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--portrait",
        type=Path,
        default=_ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png",
    )
    ap.add_argument("--ckpt", type=Path, default=DEFAULT_CKPT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--size", type=int, default=256, help="Train canvas edge (smoke default 256)")
    ap.add_argument("--scale", type=int, default=4, help="NN scale for smoke (default 4)")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--drop-prob", type=float, default=0.1)
    ap.add_argument("--token-dim", type=int, default=4096)
    ap.add_argument("--num-latents", type=int, default=64)
    ap.add_argument("--embed-dim", type=int, default=256)
    ap.add_argument("--num-heads", type=int, default=8)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.ckpt.is_file():
        raise SystemExit(f"missing ckpt: {args.ckpt}")
    if not args.portrait.is_file():
        raise SystemExit(f"missing portrait: {args.portrait}")
    return train(args)


if __name__ == "__main__":
    raise SystemExit(main())
