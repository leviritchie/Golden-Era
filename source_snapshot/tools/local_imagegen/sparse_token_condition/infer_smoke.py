#!/usr/bin/env python3
"""Infer smoke: empty latent + sparse tokens vs token ablation.

Contract:
  - Conditioner = SparseLatticeEncoder tokens from NN lattice only
  - No Stage A image as conditioner
  - Empty SD3 latent (full denoise)
  - With-tokens vs zero-tokens must diverge (plumbing proof)
  - Optional continuous lock for exact collapse gate (not invent proof)

CGI invent quality is NOT claimed by this smoke.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

_HERE = Path(__file__).resolve().parent
_LOCAL = _HERE.parent
_ROOT = _HERE.parents[2]
_COMFY = Path("V:/ml/ComfyUI")
for p in (_LOCAL, str(_COMFY)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from nearest_collapse import project_continuous_through_nn_samples  # noqa: E402
from sparse_nn_inpaint.gate import assert_exact_collapse, collapse_report  # noqa: E402
from sparse_token_condition.encoder import SparseLatticeEncoder  # noqa: E402
from sparse_token_condition.inject import attach_sparse_tokens_to_model  # noqa: E402
from sparse_token_condition.observations import (  # noqa: E402
    build_sparse_observations,
    observations_to_tensor,
)
from sparse_token_condition.train_smoke import (  # noqa: E402
    DEFAULT_CKPT,
    _encode_empty_text,
    _load_sd3,
    _make_train_canvas,
)


DEFAULT_WEIGHTS = Path("V:/ml/models/sparse_lattice/smoke.pt")
DEFAULT_OUT_DIR = (
    _ROOT / "artifacts/collapse_authentic_upscale/candidates/sparse_token_condition"
)


def _load_encoder(weights: Path, device: torch.device) -> SparseLatticeEncoder:
    blob = torch.load(weights, map_location="cpu", weights_only=False)
    if not isinstance(blob, dict) or "encoder" not in blob or "config" not in blob:
        raise SystemExit(f"bad weights payload: {weights}")
    cfg = blob["config"]
    enc = SparseLatticeEncoder(
        token_dim=int(cfg["token_dim"]),
        num_latents=int(cfg["num_latents"]),
        embed_dim=int(cfg["embed_dim"]),
        num_heads=int(cfg.get("num_heads", 8)),
    )
    enc.load_state_dict(blob["encoder"], strict=True)
    enc.to(device)
    enc.eval()
    return enc, cfg


@torch.no_grad()
def _sample_once(
    *,
    model_patcher,
    clip,
    vae,
    tokens: torch.Tensor | None,
    size: int,
    steps: int,
    seed: int,
    cfg: float,
) -> Image.Image:
    import comfy.model_management as model_management
    import comfy.sample
    import comfy.samplers

    m = model_patcher.clone()
    if tokens is not None:
        attach_sparse_tokens_to_model(m, tokens)

    text_ctx, pooled = _encode_empty_text(clip)
    # Empty positive/negative text — sparse tokens carry the condition.
    positive = [[text_ctx, {"pooled_output": pooled}]]
    negative = [[torch.zeros_like(text_ctx), {"pooled_output": torch.zeros_like(pooled)}]]

    latent_h = size // 8
    latent_w = size // 8
    channels = m.model.latent_format.latent_channels
    latent = torch.zeros([1, channels, latent_h, latent_w], device="cpu")
    noise = comfy.sample.prepare_noise(latent, seed)

    model_management.load_models_gpu([m])
    samples = comfy.sample.sample(
        m,
        noise,
        steps,
        cfg,
        "euler",
        "simple",
        positive,
        negative,
        latent,
        denoise=1.0,
        disable_pbar=True,
        seed=seed,
    )
    # Decode: Comfy VAE expects process_latent_out first.
    z = m.model.process_latent_out(samples)
    pixels = vae.decode(z)
    # pixels: BHWC [0,1]
    arr = (pixels[0, ..., :3].detach().float().cpu().clamp(0, 1).numpy() * 255.0).astype(
        np.uint8
    )
    return Image.fromarray(arr, mode="RGB")


def run(args: argparse.Namespace) -> int:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    portrait = Image.open(args.portrait).convert("RGB")
    # Match train smoke geometry: LR = NEAREST fit into size/scale.
    hr_canvas, lr = _make_train_canvas(portrait, args.size, args.scale)
    # Collapse gate compares against the LR lattice portrait, not the original sheet.
    gate_lr = lr

    enc, cfg = _load_encoder(args.weights, device)
    if int(cfg.get("scale", args.scale)) != args.scale:
        print(
            f"[infer_smoke] WARNING: weights scale={cfg.get('scale')} vs --scale {args.scale}",
            flush=True,
        )

    obs_np, _ = build_sparse_observations(lr, scale=args.scale)
    obs = observations_to_tensor(obs_np).to(device)
    with torch.no_grad():
        tokens = enc(obs.unsqueeze(0))
        tokens_zero = torch.zeros_like(tokens)

    print(f"[infer_smoke] loading SD3 from {args.ckpt}", flush=True)
    model_patcher, clip, vae = _load_sd3(args.ckpt)
    import comfy.model_management as model_management

    model_management.load_models_gpu([model_patcher, clip.patcher, vae.patcher])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name

    print(
        f"[infer_smoke] sample with-tokens size={args.size} scale={args.scale} "
        f"steps={args.steps} seed={args.seed} K={tokens.shape[1]}",
        flush=True,
    )
    with_img = _sample_once(
        model_patcher=model_patcher,
        clip=clip,
        vae=vae,
        tokens=tokens,
        size=args.size,
        steps=args.steps,
        seed=args.seed,
        cfg=args.cfg,
    )
    print("[infer_smoke] sample ablation (zero tokens)", flush=True)
    without_img = _sample_once(
        model_patcher=model_patcher,
        clip=clip,
        vae=vae,
        tokens=tokens_zero,
        size=args.size,
        steps=args.steps,
        seed=args.seed,
        cfg=args.cfg,
    )

    with_raw = args.out_dir / f"{stem}_with_tokens_raw.png"
    without_raw = args.out_dir / f"{stem}_ablate_zero_raw.png"
    with_img.save(with_raw)
    without_img.save(without_raw)

    a = np.asarray(with_img, dtype=np.float32)
    b = np.asarray(without_img, dtype=np.float32)
    mae = float(np.mean(np.abs(a - b)))
    if mae < args.min_ablation_mae:
        raise SystemExit(
            f"FAIL: with/without tokens too similar (mae={mae:.6f} < {args.min_ablation_mae}). "
            "Sparse inject path likely dead."
        )

    # Continuous lock for collapse gate (not invent evidence).
    with_locked = project_continuous_through_nn_samples(with_img, gate_lr)
    without_locked = project_continuous_through_nn_samples(without_img, gate_lr)
    with_lock_path = args.out_dir / f"{stem}_with_tokens_locked.png"
    without_lock_path = args.out_dir / f"{stem}_ablate_zero_locked.png"
    with_locked.save(with_lock_path)
    without_locked.save(without_lock_path)

    with_metrics = assert_exact_collapse(with_locked, gate_lr)
    without_metrics = assert_exact_collapse(without_locked, gate_lr)

    report = {
        "schema": "local_imagegen.sparse_token_condition.infer_smoke.v1",
        "weights": str(args.weights.resolve()),
        "ckpt": str(args.ckpt.resolve()),
        "size": args.size,
        "scale": args.scale,
        "steps": args.steps,
        "seed": args.seed,
        "cfg": args.cfg,
        "ablation_mae": mae,
        "with_tokens": {
            "raw": str(with_raw),
            "locked": str(with_lock_path),
            "collapse": with_metrics,
            "report": collapse_report(with_locked, gate_lr),
        },
        "ablate_zero": {
            "raw": str(without_raw),
            "locked": str(without_lock_path),
            "collapse": without_metrics,
            "report": collapse_report(without_locked, gate_lr),
        },
        "proof": (
            "Empty-latent SD3.5 sample with sparse lattice tokens vs zero-token ablation. "
            "MAE divergence proves inject plumbing. Locked PNGs gate exact NN collapse only; "
            "raw invent CGI quality unproven."
        ),
    }
    report_path = args.out_dir / f"{stem}_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"ablation_mae={mae:.6f}", flush=True)
    print(f"wrote {with_raw}", flush=True)
    print(f"wrote {without_raw}", flush=True)
    print(f"wrote {report_path}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--portrait",
        type=Path,
        default=_ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png",
    )
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--ckpt", type=Path, default=DEFAULT_CKPT)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--name", type=str, default="hobgoblin_sparse_token_smoke")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument(
        "--min-ablation-mae",
        type=float,
        default=1.0,
        help="Fail if with/without token MAE is below this (RGB 0-255 scale)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.weights.is_file():
        raise SystemExit(f"missing weights: {args.weights}")
    if not args.ckpt.is_file():
        raise SystemExit(f"missing ckpt: {args.ckpt}")
    if not args.portrait.is_file():
        raise SystemExit(f"missing portrait: {args.portrait}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
