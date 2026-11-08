"""ComfyUI custom nodes: nearest-collapse constraint BETWEEN diffusion steps.

Active invent path: project_mode=repaint (sparse RePaint).
  At noise level sigma t, known NN sample pixels are set to
  forward_noise(portrait_sample, t) — NOT clean RGB stamps into a noisy latent.
  Free pixels keep the model trajectory. Final step plants clean samples.

Retired / diagnostic:
  - spare_nn_samples clean model-wrap inject (fights the denoiser)
  - spare_latent_mask coarse ~8x8 VAE cell freeze
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from tqdm.auto import trange

import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview


PROJECT_MODES = ("latent", "pixel", "samples", "hybrid", "repaint")


def _match_portrait_channels(portrait: torch.Tensor, channels: int) -> torch.Tensor:
    if portrait.shape[-1] == channels:
        return portrait
    if portrait.shape[-1] == 4 and channels == 3:
        return portrait[..., :3]
    if portrait.shape[-1] == 3 and channels == 4:
        alpha = torch.ones(
            (*portrait.shape[:-1], 1), device=portrait.device, dtype=portrait.dtype
        )
        return torch.cat([portrait, alpha], dim=-1)
    raise ValueError(
        f"cannot adapt portrait channels {portrait.shape[-1]} to {channels}"
    )


def _project_blocks_bhwc(
    hr: torch.Tensor,
    lr: torch.Tensor,
    *,
    block_pull: float,
    exact_sample: bool,
) -> torch.Tensor:
    """hr/lr are BHWC float in [0,1]. Integer scale only."""
    if hr.ndim != 4 or lr.ndim != 4:
        raise ValueError("expected BHWC tensors")
    b, h_hr, w_hr, c = hr.shape
    b2, h_lr, w_lr, c2 = lr.shape
    if b != b2 or c != c2:
        raise ValueError(f"batch/channel mismatch hr={hr.shape} lr={lr.shape}")
    if h_hr % h_lr != 0 or w_hr % w_lr != 0:
        raise ValueError(f"HR {w_hr}x{h_hr} not integer multiple of LR {w_lr}x{h_lr}")
    sy, sx = h_hr // h_lr, w_hr // w_lr
    blocks = hr.reshape(b, h_lr, sy, w_lr, sx, c)
    target = lr.reshape(b, h_lr, 1, w_lr, 1, c)
    pull = float(max(0.0, min(1.0, block_pull)))
    if pull > 0.0:
        blocks = blocks * (1.0 - pull) + target * pull
    if exact_sample:
        oy, ox = sy // 2, sx // 2
        blocks = blocks.clone()
        blocks[:, :, oy, :, ox, :] = target[:, :, 0, :, 0, :]
    return blocks.reshape(b, h_hr, w_hr, c)


def _nn_mosaic_from_portrait(
    portrait_bhwc: torch.Tensor,
    h_hr: int,
    w_hr: int,
    channels: int,
) -> torch.Tensor:
    """Nearest-neighbor enlarge portrait to HxW (BHWC)."""
    portrait = _match_portrait_channels(portrait_bhwc, channels)
    if portrait.shape[0] != 1:
        portrait = portrait[:1]
    bchw = portrait.movedim(-1, 1)
    up = F.interpolate(bchw, size=(h_hr, w_hr), mode="nearest")
    return up.movedim(1, -1)


def _encode_portrait_mosaic_latent(
    vae,
    portrait_bhwc: torch.Tensor,
    *,
    h_hr: int,
    w_hr: int,
    ref_latent: torch.Tensor,
) -> torch.Tensor:
    """Encode NN mosaic once; return latent on ref_latent device/dtype/shape batch."""
    channels = 3
    mosaic = _nn_mosaic_from_portrait(portrait_bhwc, h_hr, w_hr, channels)
    if ref_latent.shape[0] > 1:
        mosaic = mosaic.expand(ref_latent.shape[0], -1, -1, -1)
    encoded = vae.encode(mosaic)
    if not torch.is_tensor(encoded):
        raise TypeError(f"vae.encode returned {type(encoded).__name__}, expected Tensor")
    if encoded.shape[-2:] != ref_latent.shape[-2:]:
        raise ValueError(
            f"mosaic latent spatial {tuple(encoded.shape[-2:])} != "
            f"ref {tuple(ref_latent.shape[-2:])} (HR pixels {w_hr}x{h_hr})"
        )
    return encoded.to(device=ref_latent.device, dtype=ref_latent.dtype)


def _project_denoised_pixel(
    denoised: torch.Tensor,
    vae,
    portrait_bhwc: torch.Tensor,
    *,
    block_pull: float,
    exact_sample: bool,
) -> torch.Tensor:
    """denoised latent -> VAE decode -> block project -> encode."""
    target_device = denoised.device
    target_dtype = denoised.dtype
    pixels = vae.decode(denoised)
    if pixels.ndim == 5:
        pixels = pixels.reshape(-1, pixels.shape[-3], pixels.shape[-2], pixels.shape[-1])
    if portrait_bhwc.shape[0] == 1 and pixels.shape[0] > 1:
        portrait = portrait_bhwc.expand(pixels.shape[0], -1, -1, -1)
    else:
        portrait = portrait_bhwc
    portrait = _match_portrait_channels(portrait, pixels.shape[-1])
    projected = _project_blocks_bhwc(
        pixels,
        portrait.to(device=pixels.device, dtype=pixels.dtype),
        block_pull=block_pull,
        exact_sample=exact_sample,
    )
    encoded = vae.encode(projected)
    if not torch.is_tensor(encoded):
        raise TypeError(f"vae.encode returned {type(encoded).__name__}, expected Tensor")
    return encoded.to(device=target_device, dtype=target_dtype)


def _project_denoised_latent_lerp(
    denoised: torch.Tensor,
    target_latent: torch.Tensor,
    *,
    block_pull: float,
) -> torch.Tensor:
    pull = float(max(0.0, min(1.0, block_pull)))
    if pull <= 0.0:
        return denoised
    tgt = target_latent.to(device=denoised.device, dtype=denoised.dtype)
    if tgt.shape[0] == 1 and denoised.shape[0] > 1:
        tgt = tgt.expand(denoised.shape[0], -1, -1, -1)
    return denoised * (1.0 - pull) + tgt * pull


def _infer_hr_pixels_from_latent(vae, latent: torch.Tensor) -> tuple[int, int]:
    """Best-effort HR pixel size from latent spatial dims + VAE downscale."""
    down = getattr(vae, "downscale_ratio", None)
    if down is None:
        down = 8
    if isinstance(down, (tuple, list)):
        dy, dx = int(down[0]), int(down[1] if len(down) > 1 else down[0])
    else:
        dy = dx = int(down)
    h_lat, w_lat = int(latent.shape[-2]), int(latent.shape[-1])
    return h_lat * dy, w_lat * dx


def _pixel_denoise_mask_nn_samples(
    *,
    batch: int,
    h_hr: int,
    w_hr: int,
    h_lr: int,
    w_lr: int,
) -> torch.Tensor:
    """B,1,H,W mask: 1=denoise/free, 0=lock at Pillow-NEAREST sample sites."""
    if h_hr % h_lr != 0 or w_hr % w_lr != 0:
        raise ValueError(f"HR {w_hr}x{h_hr} not integer multiple of LR {w_lr}x{h_lr}")
    sy, sx = h_hr // h_lr, w_hr // w_lr
    oy, ox = sy // 2, sx // 2
    mask = torch.ones(batch, 1, h_hr, w_hr, dtype=torch.float32)
    for y in range(h_lr):
        yy = y * sy + oy
        for x in range(w_lr):
            xx = x * sx + ox
            mask[:, :, yy, xx] = 0.0
    return mask


def _nn_known_mask_bhwc(
    *,
    batch: int,
    h_hr: int,
    w_hr: int,
    h_lr: int,
    w_lr: int,
    channels: int,
    device,
    dtype,
) -> torch.Tensor:
    """BHWC bool-as-float mask: 1 at Pillow-NEAREST sample sites, else 0."""
    if h_hr % h_lr != 0 or w_hr % w_lr != 0:
        raise ValueError(f"HR {w_hr}x{h_hr} not integer multiple of LR {w_lr}x{h_lr}")
    sy, sx = h_hr // h_lr, w_hr // w_lr
    oy, ox = sy // 2, sx // 2
    mask = torch.zeros(batch, h_hr, w_hr, channels, device=device, dtype=dtype)
    for y in range(h_lr):
        yy = y * sy + oy
        for x in range(w_lr):
            xx = x * sx + ox
            mask[:, yy, xx, :] = 1.0
    return mask


def _stamp_nn_sample_sites(
    hr_bhwc: torch.Tensor,
    portrait_bhwc: torch.Tensor,
) -> torch.Tensor:
    """Hard-set Pillow NEAREST sample pixels to portrait colors."""
    portrait = _match_portrait_channels(portrait_bhwc, hr_bhwc.shape[-1])
    if portrait.shape[0] == 1 and hr_bhwc.shape[0] > 1:
        portrait = portrait.expand(hr_bhwc.shape[0], -1, -1, -1)
    return _project_blocks_bhwc(
        hr_bhwc, portrait.to(device=hr_bhwc.device, dtype=hr_bhwc.dtype),
        block_pull=0.0, exact_sample=True,
    )


def _sigma_scalar(sigma: torch.Tensor) -> float:
    if not torch.is_tensor(sigma):
        return float(sigma)
    return float(sigma.detach().float().reshape(-1)[0].item())


def _forward_noise_const(clean: torch.Tensor, noise: torch.Tensor, sigma: float) -> torch.Tensor:
    """CONST / flow-matching style: x_t = sigma * noise + (1 - sigma) * clean."""
    s = max(0.0, min(1.0, float(sigma)))
    return s * noise + (1.0 - s) * clean


def _influence_falloff(norm_dist: torch.Tensor, kind: str) -> torch.Tensor:
    """Map distance/R in [0,1+] → weight in [0,1]. Outside unit disk → 0."""
    t = norm_dist.clamp(min=0.0)
    inside = t <= 1.0
    if kind == "linear":
        w = (1.0 - t).clamp(min=0.0)
    elif kind == "quad":
        w = ((1.0 - t).clamp(min=0.0)) ** 2
    elif kind == "cosine":
        w = (0.5 * (1.0 + torch.cos(torch.pi * t.clamp(max=1.0)))).clamp(min=0.0)
        w = torch.where(inside, w, torch.zeros_like(w))
    elif kind == "gauss":
        # ~3-sigma at radius edge
        w = torch.exp(-(t * t) * 4.5)
        w = torch.where(inside, w, torch.zeros_like(w))
    else:
        raise ValueError(f"unknown influence_falloff {kind!r}")
    return torch.where(inside, w, torch.zeros_like(w))


def _nn_soft_influence_weights(
    *,
    h_hr: int,
    w_hr: int,
    h_lr: int,
    w_lr: int,
    radius: float,
    falloff: str,
    device,
    dtype,
) -> torch.Tensor:
    """HW weight map: 1 at NN sample sites, falloff within radius, else 0.

    Uses min distance to the sample in this block and its 8 neighbors so radius
    may exceed half-block without seams.
    """
    if radius <= 0.0:
        # Hard dots only.
        sy, sx = h_hr // h_lr, w_hr // w_lr
        oy, ox = sy // 2, sx // 2
        w = torch.zeros(h_hr, w_hr, device=device, dtype=dtype)
        for y in range(h_lr):
            for x in range(w_lr):
                w[y * sy + oy, x * sx + ox] = 1.0
        return w

    if h_hr % h_lr != 0 or w_hr % w_lr != 0:
        raise ValueError(f"HR {w_hr}x{h_hr} not integer multiple of LR {w_lr}x{h_lr}")
    sy, sx = h_hr // h_lr, w_hr // w_lr
    oy, ox = sy // 2, sx // 2
    yy = torch.arange(h_hr, device=device, dtype=dtype).view(h_hr, 1).expand(h_hr, w_hr)
    xx = torch.arange(w_hr, device=device, dtype=dtype).view(1, w_hr).expand(h_hr, w_hr)
    by0 = (yy // sy).long().clamp(0, h_lr - 1)
    bx0 = (xx // sx).long().clamp(0, w_lr - 1)
    dist = torch.full((h_hr, w_hr), 1e9, device=device, dtype=dtype)
    for dby in (-1, 0, 1):
        for dbx in (-1, 0, 1):
            by = (by0 + dby).clamp(0, h_lr - 1)
            bx = (bx0 + dbx).clamp(0, w_lr - 1)
            syy = by.to(dtype) * float(sy) + float(oy)
            sxx = bx.to(dtype) * float(sx) + float(ox)
            d = torch.sqrt((yy - syy) ** 2 + (xx - sxx) ** 2)
            dist = torch.minimum(dist, d)
    w = _influence_falloff(dist / float(radius), falloff)
    # Exact sample sites always fully known.
    for y in range(h_lr):
        for x in range(w_lr):
            w[y * sy + oy, x * sx + ox] = 1.0
    return w


def _repaint_nn_samples_at_sigma(
    z: torch.Tensor,
    vae,
    portrait_bhwc: torch.Tensor,
    sigma: torch.Tensor | float,
    *,
    generator: torch.Generator | None = None,
    influence_radius: float = 0.0,
    influence_falloff: str = "quad",
) -> torch.Tensor:
    """Sparse RePaint with optional soft radial influence around NN samples.

    Known sites (and neighbors within radius) blend toward
    forward_noise(block_portrait_color, t). Radius 0 = hard sample dots only.
    """
    target_device = z.device
    target_dtype = z.dtype
    pixels = vae.decode(z)
    if pixels.ndim == 5:
        pixels = pixels.reshape(-1, pixels.shape[-3], pixels.shape[-2], pixels.shape[-1])
    pixels = pixels.to(dtype=torch.float32)

    if portrait_bhwc.shape[0] == 1 and pixels.shape[0] > 1:
        portrait = portrait_bhwc.expand(pixels.shape[0], -1, -1, -1)
    else:
        portrait = portrait_bhwc
    portrait = _match_portrait_channels(portrait, pixels.shape[-1]).to(
        device=pixels.device, dtype=pixels.dtype
    )

    b, h_hr, w_hr, c = pixels.shape
    h_lr, w_lr = int(portrait.shape[1]), int(portrait.shape[2])
    # Target clean: hard lattice only when radius=0 (no block mosaic filler).
    # Soft influence (>0) still uses NN mosaic so neighbors can blend toward
    # the block's LR color — that is intentionally soft-evidence, not true sparse.
    if float(influence_radius) <= 0.0:
        target_clean = torch.zeros_like(pixels)
        oy, ox = (h_hr // h_lr) // 2, (w_hr // w_lr) // 2
        sy, sx = h_hr // h_lr, w_hr // w_lr
        for y in range(h_lr):
            for x in range(w_lr):
                target_clean[:, y * sy + oy, x * sx + ox, :] = portrait[:, y, x, :]
    else:
        target_clean = _nn_mosaic_from_portrait(portrait[:1], h_hr, w_hr, c)
        if b > 1:
            target_clean = target_clean.expand(b, -1, -1, -1)
        target_clean = target_clean.to(device=pixels.device, dtype=pixels.dtype)

    if generator is None:
        noise = torch.randn_like(pixels)
    else:
        noise = torch.randn(
            pixels.shape,
            dtype=pixels.dtype,
            device="cpu",
            generator=generator,
        ).to(device=pixels.device)
    s = _sigma_scalar(sigma)
    target_noised = _forward_noise_const(target_clean, noise, s)

    weights = _nn_soft_influence_weights(
        h_hr=h_hr,
        w_hr=w_hr,
        h_lr=h_lr,
        w_lr=w_lr,
        radius=float(influence_radius),
        falloff=str(influence_falloff),
        device=pixels.device,
        dtype=pixels.dtype,
    )
    w = weights.view(1, h_hr, w_hr, 1).expand(b, h_hr, w_hr, c)
    out_pixels = pixels * (1.0 - w) + target_noised * w
    out_pixels = out_pixels.clamp(0.0, 1.0)

    encoded = vae.encode(out_pixels)
    if not torch.is_tensor(encoded):
        raise TypeError(f"vae.encode returned {type(encoded).__name__}, expected Tensor")
    return encoded.to(device=target_device, dtype=target_dtype)


def _latent_denoise_mask_from_pixel_mask(
    pixel_mask_b1hw: torch.Tensor,
    latent_bchw: torch.Tensor,
) -> torch.Tensor:
    """Lock any latent cell that overlaps a locked pixel (conservative max-pool)."""
    lock = 1.0 - pixel_mask_b1hw
    h_lat, w_lat = int(latent_bchw.shape[-2]), int(latent_bchw.shape[-1])
    lock_lat = F.adaptive_max_pool2d(lock.to(device=latent_bchw.device), (h_lat, w_lat))
    denoise = (1.0 - lock_lat).clamp(0.0, 1.0)
    if denoise.shape[0] == 1 and latent_bchw.shape[0] > 1:
        denoise = denoise.expand(latent_bchw.shape[0], -1, -1, -1)
    return denoise.to(device=latent_bchw.device, dtype=torch.float32)


def _build_spare_nn_init_latent(
    vae,
    portrait_bhwc: torch.Tensor,
    latent_samples: torch.Tensor,
    *,
    h_hr: int,
    w_hr: int,
    seed: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Plant NN sample sites into init; return (latent, optional_coarse_denoise_mask)."""
    batch = int(latent_samples.shape[0])
    portrait = _match_portrait_channels(portrait_bhwc[:1], 3).detach().float().cpu()
    h_lr, w_lr = int(portrait.shape[1]), int(portrait.shape[2])

    if float(latent_samples.detach().abs().mean()) < 1e-4:
        gen = torch.Generator(device="cpu")
        gen.manual_seed(int(seed) & 0x7FFFFFFF)
        init = torch.rand((batch, h_hr, w_hr, 3), generator=gen, dtype=torch.float32)
    else:
        decoded = vae.decode(latent_samples)
        if decoded.ndim == 5:
            decoded = decoded.reshape(-1, decoded.shape[-3], decoded.shape[-2], decoded.shape[-1])
        init = decoded[..., :3].detach().float().cpu()
        if init.shape[0] == 1 and batch > 1:
            init = init.expand(batch, -1, -1, -1).clone()

    if portrait.shape[0] == 1 and batch > 1:
        portrait_b = portrait.expand(batch, -1, -1, -1)
    else:
        portrait_b = portrait
    init = _stamp_nn_sample_sites(init, portrait_b)

    pixel_mask = _pixel_denoise_mask_nn_samples(
        batch=batch, h_hr=h_hr, w_hr=w_hr, h_lr=h_lr, w_lr=w_lr,
    )
    encoded = vae.encode(init)
    if not torch.is_tensor(encoded):
        raise TypeError(f"vae.encode returned {type(encoded).__name__}, expected Tensor")
    encoded = encoded.to(device=latent_samples.device, dtype=latent_samples.dtype)
    if encoded.shape[-2:] != latent_samples.shape[-2:]:
        raise ValueError(
            f"spare-init latent spatial {tuple(encoded.shape[-2:])} != "
            f"ref {tuple(latent_samples.shape[-2:])}"
        )
    coarse_mask = _latent_denoise_mask_from_pixel_mask(pixel_mask, encoded)
    return encoded, coarse_mask


def _inject_nn_samples_into_latent(
    z: torch.Tensor,
    vae,
    portrait_bhwc: torch.Tensor,
) -> torch.Tensor:
    """Decode → stamp CLEAN Pillow-NEAREST sample sites → encode (legacy; fights denoiser)."""
    return _project_denoised_pixel(
        z, vae, portrait_bhwc, block_pull=0.0, exact_sample=True,
    )


def _make_euler_nn_collapse_sampler(
    vae,
    portrait_bhwc: torch.Tensor,
    *,
    project_mode: str,
    block_pull: float,
    exact_sample: bool,
    every_n: int,
    start_percent: float,
    end_percent: float,
    target_latent: torch.Tensor | None = None,
    spare_nn_samples: bool = False,
    repaint_seed: int = 0,
    influence_radius: float = 0.0,
    influence_falloff: str = "quad",
):
    """KSAMPLER whose euler loop projects nearest-collapse / sparse RePaint each step."""
    if project_mode not in PROJECT_MODES:
        raise ValueError(f"project_mode must be one of {PROJECT_MODES}, got {project_mode!r}")
    needs_target = project_mode in ("latent", "hybrid")
    if needs_target and target_latent is None:
        raise ValueError(f"{project_mode} project_mode requires target_latent")
    use_repaint = project_mode == "repaint"
    if use_repaint:
        # Clean inject fights RePaint; ignore spare_nn_samples for this mode.
        spare_nn_samples = False
    if influence_falloff not in ("linear", "quad", "cosine", "gauss"):
        raise ValueError(f"influence_falloff must be linear|quad|cosine|gauss, got {influence_falloff!r}")
    if float(influence_radius) < 0.0:
        raise ValueError("influence_radius must be >= 0")

    def _project(denoised: torch.Tensor) -> torch.Tensor:
        if project_mode == "repaint":
            # Final clean plant for exact collapse measurement.
            return _inject_nn_samples_into_latent(denoised, vae, portrait_bhwc)
        if project_mode == "latent":
            out = _project_denoised_latent_lerp(
                denoised, target_latent, block_pull=block_pull
            )
            if spare_nn_samples:
                out = _inject_nn_samples_into_latent(out, vae, portrait_bhwc)
            return out
        if project_mode == "samples":
            return _inject_nn_samples_into_latent(denoised, vae, portrait_bhwc)
        if project_mode == "hybrid":
            pulled = _project_denoised_latent_lerp(
                denoised, target_latent, block_pull=block_pull
            )
            return _inject_nn_samples_into_latent(pulled, vae, portrait_bhwc)
        out = _project_denoised_pixel(
            denoised,
            vae,
            portrait_bhwc,
            block_pull=block_pull,
            exact_sample=exact_sample or spare_nn_samples,
        )
        return out

    def sampler_function(model, x, sigmas, extra_args=None, callback=None, disable=None, **extra_options):
        extra_args = {} if extra_args is None else extra_args
        s_in = x.new_ones([x.shape[0]])
        total = max(len(sigmas) - 1, 1)
        gen = torch.Generator(device="cpu")
        gen.manual_seed(int(repaint_seed) & 0x7FFFFFFF)

        def model_with_nn_inject(x_in, sigma_in, **kwargs):
            if not spare_nn_samples:
                return model(x_in, sigma_in, **kwargs)
            x_cond = _inject_nn_samples_into_latent(x_in, vae, portrait_bhwc)
            denoised = model(x_cond, sigma_in, **kwargs)
            return _inject_nn_samples_into_latent(denoised, vae, portrait_bhwc)

        for i in trange(len(sigmas) - 1, disable=disable):
            sigma_hat = sigmas[i]
            pct = i / max(total - 1, 1)
            is_last = i == (len(sigmas) - 2)
            do_project = is_last or (
                start_percent <= pct <= end_percent
                and every_n > 0
                and (i % every_n) == 0
            )

            # Generative soft influence: condition the noisy latent BEFORE the
            # denoiser so radius/falloff steers invent (not a late paste).
            if use_repaint and do_project:
                step_gen = torch.Generator(device="cpu")
                step_gen.manual_seed((int(repaint_seed) + i * 1009) & 0x7FFFFFFF)
                x = _repaint_nn_samples_at_sigma(
                    x,
                    vae,
                    portrait_bhwc,
                    sigma_hat,
                    generator=step_gen,
                    influence_radius=float(influence_radius),
                    influence_falloff=str(influence_falloff),
                )

            denoised = model_with_nn_inject(x, sigma_hat * s_in, **extra_args)

            if do_project and not use_repaint:
                if project_mode == "latent":
                    denoised = _project_denoised_latent_lerp(
                        denoised, target_latent, block_pull=block_pull
                    )
                    if spare_nn_samples:
                        denoised = _inject_nn_samples_into_latent(
                            denoised, vae, portrait_bhwc
                        )
                elif project_mode == "hybrid":
                    denoised = _project_denoised_latent_lerp(
                        denoised, target_latent, block_pull=block_pull
                    )
                    denoised = _inject_nn_samples_into_latent(
                        denoised, vae, portrait_bhwc
                    )
                elif project_mode == "pixel":
                    denoised = _project_denoised_pixel(
                        denoised,
                        vae,
                        portrait_bhwc,
                        block_pull=block_pull,
                        exact_sample=exact_sample or spare_nn_samples,
                    )
                elif project_mode == "samples" and not spare_nn_samples:
                    denoised = _inject_nn_samples_into_latent(
                        denoised, vae, portrait_bhwc
                    )
            elif use_repaint and do_project:
                # Soft-pull predicted x0 toward clean block colors (sigma=0).
                x0_gen = torch.Generator(device="cpu")
                x0_gen.manual_seed((int(repaint_seed) + i * 7919 + 17) & 0x7FFFFFFF)
                denoised = _repaint_nn_samples_at_sigma(
                    denoised,
                    vae,
                    portrait_bhwc,
                    0.0,
                    generator=x0_gen,
                    influence_radius=float(influence_radius),
                    influence_falloff=str(influence_falloff),
                )

            if callback is not None:
                callback(
                    {
                        "x": x,
                        "i": i,
                        "sigma": sigmas[i],
                        "sigma_hat": sigma_hat,
                        "denoised": denoised,
                    }
                )

            from comfy.k_diffusion.sampling import to_d

            d = to_d(x, sigma_hat, denoised)
            dt = sigmas[i + 1] - sigma_hat
            x = x + d * dt

            if use_repaint and do_project:
                # Keep trajectory soft-anchored at the next noise level.
                step_gen2 = torch.Generator(device="cpu")
                step_gen2.manual_seed((int(repaint_seed) + i * 1009 + 3) & 0x7FFFFFFF)
                x = _repaint_nn_samples_at_sigma(
                    x,
                    vae,
                    portrait_bhwc,
                    sigmas[i + 1],
                    generator=step_gen2,
                    influence_radius=float(influence_radius),
                    influence_falloff=str(influence_falloff),
                )
            elif spare_nn_samples:
                x = _inject_nn_samples_into_latent(x, vae, portrait_bhwc)

        if len(sigmas) >= 2:
            x = _project(x)
            if spare_nn_samples and not use_repaint:
                x = _inject_nn_samples_into_latent(x, vae, portrait_bhwc)
        return x

    return comfy.samplers.KSAMPLER(sampler_function)


class KSamplerNearestCollapse:
    """KSampler with inter-step nearest-collapse / sparse RePaint."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "vae": ("VAE",),
                "portrait": ("IMAGE", {
                    "tooltip": "Low-res TwCrPort / ground-truth portrait (integer scale into HR).",
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "steps": ("INT", {"default": 28, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 4.5, "min": 0.0, "max": 100.0, "step": 0.1}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "sgm_uniform"}),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "denoise": ("FLOAT", {"default": 0.85, "min": 0.0, "max": 1.0, "step": 0.01}),
                "project_mode": (list(PROJECT_MODES), {
                    "default": "repaint",
                    "tooltip": (
                        "repaint=sparse RePaint (noised known at sigma t; preferred). "
                        "samples/hybrid=legacy clean stamp. latent/pixel=legacy pulls."
                    ),
                }),
                "pixel_width": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 8192,
                    "tooltip": "HR pixel width (0 = infer from VAE downscale_ratio).",
                }),
                "pixel_height": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 8192,
                    "tooltip": "HR pixel height (0 = infer from VAE downscale_ratio).",
                }),
                "block_pull": ("FLOAT", {
                    "default": 0.45,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Pull strength toward portrait (pixel/latent modes only).",
                }),
                "exact_sample": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "pixel mode only: also hard-set NEAREST sample pixel.",
                }),
                "spare_nn_samples": ("BOOLEAN", {
                    "default": False,
                    "tooltip": (
                        "LEGACY clean model-wrap inject. Off by default — fights the "
                        "denoiser. Prefer project_mode=repaint."
                    ),
                }),
                "spare_latent_mask": ("BOOLEAN", {
                    "default": False,
                    "tooltip": (
                        "Coarse ~8x8 VAE cell freeze. Off — wrong for single-pixel known sets."
                    ),
                }),
                "every_n": ("INT", {"default": 1, "min": 1, "max": 32}),
                "start_percent": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": (
                        "When soft influence starts (0=whole generative trajectory). "
                        "Late-only values act like post-process and barely change invent."
                    ),
                }),
                "end_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "influence_radius": ("FLOAT", {
                    "default": 4.0,
                    "min": 0.0,
                    "max": 64.0,
                    "step": 0.5,
                    "tooltip": (
                        "Soft pull radius (pixels) around each NN sample. 0=hard dots only. "
                        "Neighbors blend toward the block portrait color (noised at sigma t)."
                    ),
                }),
                "influence_falloff": (["linear", "quad", "cosine", "gauss"], {
                    "default": "quad",
                    "tooltip": "Weight falloff inside influence_radius.",
                }),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = "sampling/collapse"
    DESCRIPTION = (
        "Euler sampler with sparse NN RePaint (project_mode=repaint) or legacy "
        "nearest-collapse projection. RePaint noised-known paste is the invent path."
    )

    def sample(
        self,
        model,
        vae,
        portrait,
        seed,
        steps,
        cfg,
        scheduler,
        positive,
        negative,
        latent_image,
        denoise,
        project_mode,
        pixel_width,
        pixel_height,
        block_pull,
        exact_sample,
        spare_nn_samples,
        spare_latent_mask,
        every_n,
        start_percent,
        end_percent,
        influence_radius,
        influence_falloff,
    ):
        if start_percent > end_percent:
            raise ValueError("start_percent must be <= end_percent")
        if project_mode not in PROJECT_MODES:
            raise ValueError(f"project_mode must be one of {PROJECT_MODES}")

        # RePaint path: never coarse-freeze VAE cells; never clean-inject.
        if project_mode == "repaint":
            spare_nn_samples = False
            spare_latent_mask = False

        latent = latent_image.copy()
        latent_samples = comfy.sample.fix_empty_latent_channels(
            model,
            latent["samples"],
            latent.get("downscale_ratio_spacial", None),
            latent.get("downscale_ratio_temporal", None),
        )

        if portrait.shape[0] != 1 and portrait.shape[0] != latent_samples.shape[0]:
            portrait = portrait[:1]

        if int(pixel_width) > 0 and int(pixel_height) > 0:
            h_hr, w_hr = int(pixel_height), int(pixel_width)
        else:
            h_hr, w_hr = _infer_hr_pixels_from_latent(vae, latent_samples)

        noise_mask = latent.get("noise_mask")
        if spare_nn_samples:
            latent_samples, coarse_mask = _build_spare_nn_init_latent(
                vae,
                portrait,
                latent_samples,
                h_hr=h_hr,
                w_hr=w_hr,
                seed=int(seed),
            )
            if spare_latent_mask:
                if noise_mask is None:
                    noise_mask = coarse_mask
                else:
                    noise_mask = torch.minimum(
                        comfy.utils.reshape_mask(noise_mask, latent_samples.shape),
                        comfy.utils.reshape_mask(coarse_mask, latent_samples.shape),
                    )

        noise = comfy.sample.prepare_noise(
            latent_samples,
            seed,
            latent["batch_index"] if "batch_index" in latent else None,
        )
        if noise_mask is not None:
            nm = comfy.utils.reshape_mask(noise_mask, noise.shape).to(
                device=noise.device, dtype=noise.dtype
            )
            noise = noise * nm

        target_latent = None
        if project_mode in ("latent", "hybrid"):
            target_latent = _encode_portrait_mosaic_latent(
                vae,
                portrait,
                h_hr=h_hr,
                w_hr=w_hr,
                ref_latent=latent_samples,
            )

        sampler = _make_euler_nn_collapse_sampler(
            vae,
            portrait,
            project_mode=project_mode,
            block_pull=block_pull,
            exact_sample=exact_sample,
            every_n=int(every_n),
            start_percent=float(start_percent),
            end_percent=float(end_percent),
            target_latent=target_latent,
            spare_nn_samples=bool(spare_nn_samples),
            repaint_seed=int(seed),
            influence_radius=float(influence_radius),
            influence_falloff=str(influence_falloff),
        )

        ksampler = comfy.samplers.KSampler(
            model,
            steps=steps,
            device=latent_samples.device,
            sampler="euler",
            scheduler=scheduler,
            denoise=denoise,
            model_options=model.model_options,
        )
        sigmas = ksampler.sigmas

        callback = latent_preview.prepare_callback(model, len(sigmas) - 1)
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        samples = comfy.samplers.sample(
            model,
            noise,
            positive,
            negative,
            cfg,
            latent_samples.device,
            sampler,
            sigmas,
            model_options=model.model_options,
            latent_image=latent_samples,
            denoise_mask=noise_mask,
            callback=callback,
            disable_pbar=disable_pbar,
            seed=seed,
        )
        out = latent.copy()
        out.pop("downscale_ratio_spacial", None)
        out.pop("downscale_ratio_temporal", None)
        out["samples"] = samples
        if noise_mask is not None:
            out["noise_mask"] = noise_mask
        return (out,)


NODE_CLASS_MAPPINGS = {
    "KSamplerNearestCollapse": KSamplerNearestCollapse,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "KSamplerNearestCollapse": "KSampler Nearest Collapse (inter-step)",
}
