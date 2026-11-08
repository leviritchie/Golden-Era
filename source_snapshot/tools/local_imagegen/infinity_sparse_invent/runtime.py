"""Load Infinity-2B + VAE + T5 once; wrap gen_one_img."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image


def _env_path(name: str, default: str | None = None) -> Path:
    raw = os.environ.get(name, default)
    if not raw:
        raise SystemExit(f"missing required env {name}")
    return Path(raw)


@dataclass
class InfinityRuntime:
    infinity_root: Path
    model_path: Path
    vae_path: Path
    t5_path: Path
    text_tokenizer: Any = None
    text_encoder: Any = None
    vae: Any = None
    infinity: Any = None
    args: Any = None
    _gen_one_img: Any = None
    _dynamic_resolution_h_w: Any = None
    _h_div_w_templates: Any = None

    @classmethod
    def from_env(cls) -> "InfinityRuntime":
        root = _env_path("INFINITY_ROOT", "V:/ml/Infinity")
        weights = _env_path("INFINITY_WEIGHTS", "V:/ml/models/infinity")
        return cls(
            infinity_root=root,
            model_path=_env_path("INFINITY_MODEL_PATH", str(weights / "infinity_2b_reg.pth")),
            vae_path=_env_path("INFINITY_VAE_PATH", str(weights / "infinity_vae_d32reg.pth")),
            t5_path=_env_path("INFINITY_T5_PATH", str(weights / "flan-t5-xl")),
        )

    def ensure_imports(self) -> None:
        root = str(self.infinity_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        # Single-GPU defaults for Infinity's dist helpers.
        import infinity.utils.dist as dist

        dist.set_gpu_id(0)

    def load(self) -> None:
        if self.infinity is not None:
            return
        self.ensure_imports()
        for p in (self.model_path, self.vae_path, self.t5_path):
            if not Path(p).exists():
                raise SystemExit(f"missing weight path: {p}")

        from tools.run_infinity import (  # type: ignore
            gen_one_img,
            load_tokenizer,
            load_transformer,
            load_visual_tokenizer,
        )
        from infinity.utils.dynamic_resolution import (  # type: ignore
            dynamic_resolution_h_w,
            h_div_w_templates,
        )

        self._gen_one_img = gen_one_img
        self._dynamic_resolution_h_w = dynamic_resolution_h_w
        self._h_div_w_templates = h_div_w_templates

        cache_dir = os.environ.get("TMPDIR", "V:/ml/caches/tmp")
        self.args = argparse.Namespace(
            pn="1M",
            model_path=str(self.model_path),
            cfg_insertion_layer=0,
            vae_type=32,
            vae_path=str(self.vae_path),
            add_lvl_embeding_only_first_block=1,
            use_bit_label=1,
            model_type="infinity_2b",
            rope2d_each_sa_layer=1,
            rope2d_normalized_by_hw=2,
            use_scale_schedule_embedding=0,
            sampling_per_bits=1,
            text_encoder_ckpt=str(self.t5_path),
            text_channels=2048,
            apply_spatial_patchify=0,
            h_div_w_template=1.000,
            use_flex_attn=0,
            cache_dir=cache_dir,
            checkpoint_type="torch",
            seed=0,
            bf16=1,
            enable_model_cache=0,
        )
        print("[infinity_sparse_invent] loading T5…", flush=True)
        self.text_tokenizer, self.text_encoder = load_tokenizer(t5_path=self.args.text_encoder_ckpt)
        print("[infinity_sparse_invent] loading VAE…", flush=True)
        self.vae = load_visual_tokenizer(self.args)
        print("[infinity_sparse_invent] loading Infinity-2B…", flush=True)
        self.infinity = load_transformer(self.vae, self.args)
        torch.cuda.empty_cache()
        print("[infinity_sparse_invent] ready", flush=True)

    def square_scale_schedule(self) -> list[tuple[int, int, int]]:
        self.load()
        templates = np.asarray(list(self._h_div_w_templates), dtype=np.float64)
        h_div_w = 1.0
        h_div_w_template = float(templates[np.argmin(np.abs(templates - h_div_w))])
        scales = self._dynamic_resolution_h_w[h_div_w_template][self.args.pn]["scales"]
        return [(1, int(h), int(w)) for (_t, h, w) in scales]

    def generate(
        self,
        *,
        prompt: str,
        seed: int,
        cfg: float = 3.0,
        tau: float = 0.5,
        gt_leak: int = 0,
        gt_ls_Bl: list[torch.Tensor] | None = None,
        negative_prompt: str = "",
    ) -> Image.Image:
        from condition import tensor_bgr_to_pil

        self.load()
        scale_schedule = self.square_scale_schedule()
        if gt_leak > 0 and not gt_ls_Bl:
            raise SystemExit("gt_leak>0 requires encoded Stage A bit labels (gt_ls_Bl)")
        if gt_leak > len(scale_schedule):
            raise SystemExit(f"gt_leak={gt_leak} > n_scales={len(scale_schedule)}")

        img = self._gen_one_img(
            self.infinity,
            self.vae,
            self.text_tokenizer,
            self.text_encoder,
            prompt,
            g_seed=int(seed),
            gt_leak=int(gt_leak),
            gt_ls_Bl=gt_ls_Bl,
            cfg_list=float(cfg),
            tau_list=float(tau),
            scale_schedule=scale_schedule,
            cfg_insertion_layer=[self.args.cfg_insertion_layer],
            vae_type=self.args.vae_type,
            sampling_per_bits=self.args.sampling_per_bits,
            enable_positive_prompt=0,
            negative_prompt=negative_prompt or "",
        )
        return tensor_bgr_to_pil(img)
