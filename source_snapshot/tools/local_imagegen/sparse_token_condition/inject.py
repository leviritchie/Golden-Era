"""Inject sparse lattice tokens into SD3 ``c_crossattn`` (pre-context_embedder)."""

from __future__ import annotations

from typing import Any, Callable

import torch


def concat_sparse_tokens_to_context(
    context: torch.Tensor,
    sparse_tokens: torch.Tensor,
    *,
    cond_or_uncond: list[int] | None,
) -> torch.Tensor:
    """Concat ``sparse_tokens`` onto sequence dim of ``context``.

    ``context``: (B, L, D) text/joint context before MMDiT embedder.
    ``sparse_tokens``: (1, K, D) or (B, K, D).
    For CFG batches, ``cond_or_uncond[i]==0`` means positive (use tokens);
    ``1`` means negative (zeros). If ``cond_or_uncond`` is None, apply to all rows.
    """
    if context.ndim != 3:
        raise ValueError(f"context must be (B,L,D), got {tuple(context.shape)}")
    if sparse_tokens.ndim == 2:
        sparse_tokens = sparse_tokens.unsqueeze(0)
    if sparse_tokens.ndim != 3:
        raise ValueError(f"sparse_tokens must be (B,K,D) or (K,D), got {tuple(sparse_tokens.shape)}")
    if sparse_tokens.shape[-1] != context.shape[-1]:
        raise ValueError(
            f"token width {sparse_tokens.shape[-1]} != context width {context.shape[-1]}"
        )

    b = context.shape[0]
    k = sparse_tokens.shape[1]
    d = context.shape[-1]
    tokens = sparse_tokens.to(device=context.device, dtype=context.dtype)
    if tokens.shape[0] == 1 and b > 1:
        tokens = tokens.expand(b, -1, -1)
    elif tokens.shape[0] != b:
        raise ValueError(f"sparse batch {tokens.shape[0]} incompatible with context batch {b}")

    if cond_or_uncond is None:
        mask = torch.ones(b, 1, 1, device=context.device, dtype=context.dtype)
    else:
        if len(cond_or_uncond) != b:
            raise ValueError(
                f"cond_or_uncond length {len(cond_or_uncond)} != batch {b}"
            )
        # 0 = positive/cond → keep tokens; 1 = uncond → zero
        mask = torch.tensor(
            [[0.0 if int(v) == 1 else 1.0] for v in cond_or_uncond],
            device=context.device,
            dtype=context.dtype,
        ).view(b, 1, 1)
    tokens = tokens * mask
    return torch.cat([context, tokens], dim=1)


def make_sparse_token_model_wrapper(
    sparse_tokens: torch.Tensor,
) -> Callable[[Callable, dict[str, Any]], torch.Tensor]:
    """Comfy ``model_function_wrapper`` that appends sparse tokens to ``c_crossattn``."""

    def _wrapper(apply_model: Callable, extras: dict[str, Any]) -> torch.Tensor:
        c = dict(extras["c"])
        cond_or_uncond = extras.get("cond_or_uncond")
        ctx = c.get("c_crossattn")
        if ctx is None:
            raise RuntimeError(
                "sparse lattice inject requires c_crossattn on the model call "
                "(SD3 text context missing)"
            )
        c["c_crossattn"] = concat_sparse_tokens_to_context(
            ctx, sparse_tokens, cond_or_uncond=cond_or_uncond
        )
        return apply_model(extras["input"], extras["timestep"], **c)

    return _wrapper


def attach_sparse_tokens_to_model(model, sparse_tokens: torch.Tensor):
    """Attach / chain onto ``model.model_options['model_function_wrapper']``."""
    wrapper = make_sparse_token_model_wrapper(sparse_tokens)
    existing = model.model_options.get("model_function_wrapper")
    if existing is None:
        model.model_options["model_function_wrapper"] = wrapper
        return model

    def _chained(apply_model, extras):
        def _inner_apply(input_x, timestep, **c):
            return apply_model(input_x, timestep, **c)

        # Run sparse inject first, then any prior wrapper.
        return existing(
            lambda inp, ts, **c: _inner_apply(inp, ts, **c),
            {
                "input": extras["input"],
                "timestep": extras["timestep"],
                "c": dict(extras["c"]),
                "cond_or_uncond": extras.get("cond_or_uncond"),
            },
        )

    # Prefer sparse as the outermost so it sees raw c_crossattn.
    def _outer(apply_model, extras):
        def _after_sparse(inp, ts, **c):
            return existing(apply_model, {
                "input": inp,
                "timestep": ts,
                "c": c,
                "cond_or_uncond": extras.get("cond_or_uncond"),
            })

        return wrapper(_after_sparse, extras)

    model.model_options["model_function_wrapper"] = _outer
    return model
