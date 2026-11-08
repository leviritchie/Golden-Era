#!/usr/bin/env python3
"""Stage B: generative invent under nearest-collapse measurement.

Stage A (grid fill through NN samples) is a collapse-valid soft prior. It is a
measurement check, not an invent canvas. Soft img2img / high-pass polish of
Stage A only cleans mush — it cannot become a late-90s CGI master.

This lane invents around the known sample pixels:
  1) Text2img (empty latent) with spare_nn_samples model-wrap: plant portrait
     RGB at Pillow-NEAREST sample sites into a random free field, then let SD
     invent CGI around those anchors. No coarse 8x8 latent spare-mask.
  2) Final continuous residual lock for exact collapse — keeps the invented
     surface; does NOT blend back toward Stage A.

Proof: generated artifact + nearest metrics. CGI look: human review (primary).
Lattice discontinuity is diagnostic only — not the optimization target.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from nearest_collapse import (
    nearest_collapse_metrics,
    project_continuous_through_nn_samples,
    sample_neighbor_discontinuity,
)

ROOT = Path(__file__).resolve().parents[2]
COMFY_HELPER = _HERE / "comfy_exact_img2img_sd35.py"


def _run_comfy_generate(
    *,
    portrait: Path,
    out: Path,
    width: int,
    height: int,
    steps: int,
    seed: int,
    cfg: float,
    positive: str,
    negative: str,
    host: str,
    port: int,
) -> dict:
    cmd = [
        sys.executable,
        str(COMFY_HELPER),
        "--image",
        str(portrait),
        "--init",
        "none",
        "--out",
        str(out),
        "--width",
        str(width),
        "--height",
        str(height),
        "--denoise",
        "1.0",
        "--steps",
        str(steps),
        "--seed",
        str(seed),
        "--cfg",
        str(cfg),
        "--project-mode",
        "samples",
        "--spare-nn-samples",
        "--no-spare-latent-mask",
        "--interstep-nearest-collapse",
        "--filename-prefix",
        "collapse_stageb_gen",
        "--positive",
        positive,
        "--negative",
        negative,
        "--host",
        host,
        "--port",
        str(port),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            "Stage B generative Comfy helper failed:\n"
            + (proc.stdout or "")[-2000:]
            + "\n"
            + (proc.stderr or "")[-2000:]
        )
    meta_path = out.with_suffix(".json")
    if meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"stdout_tail": (proc.stdout or "")[-1500:]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--portrait", type=Path, required=True, help="TwCrPort / LR ground truth")
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output HR PNG (generative invent + continuous collapse lock)",
    )
    ap.add_argument(
        "--scale",
        type=int,
        default=16,
        help="Integer nearest scale (HR = LR * scale). Default 16 → 928x1024 for hobgoblin.",
    )
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cfg", type=float, default=5.5)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument(
        "--lock-method",
        choices=("cubic", "linear"),
        default="cubic",
        help="Continuous residual interpolant for final exact collapse",
    )
    ap.add_argument(
        "--positive",
        type=str,
        default=(
            "late 1990s pre-rendered 3D CGI hobgoblin portrait, Heroes of Might and Magic III, "
            "New World Computing render style, sharp specular highlights on bronze armor, "
            "plastic 90s CGI materials, crisp geometric silhouette, desert stronghold tower, "
            "high-resolution master render, not soft blur, not hand-painted, not photoreal modern, "
            "not pixel art, not upscaled mush"
        ),
    )
    ap.add_argument(
        "--negative",
        type=str,
        default=(
            "pixel art, mosaic, nearest neighbor blocks, hand-painted, oil painting, "
            "illustration, anime, photoreal modern, text, watermark, blurry, soft mush, "
            "oversmoothed, gaussian blur, low resolution upscale"
        ),
    )
    ap.add_argument(
        "--from-raw",
        type=Path,
        default=None,
        help="Skip Comfy; continuous-lock an existing generative raw PNG",
    )
    args = ap.parse_args()

    portrait_path = args.portrait.resolve()
    if not portrait_path.is_file():
        raise SystemExit(f"portrait not found: {portrait_path}")
    if args.scale < 2:
        raise SystemExit("--scale must be >= 2")

    portrait = Image.open(portrait_path).convert("RGBA")
    lr_w, lr_h = portrait.size
    width = lr_w * args.scale
    height = lr_h * args.scale

    comfy_meta: dict | None = None
    if args.from_raw is not None:
        raw_out = args.from_raw.resolve()
        if not raw_out.is_file():
            raise SystemExit(f"--from-raw not found: {raw_out}")
        with Image.open(raw_out) as raw_im:
            width, height = raw_im.size
    else:
        raw_out = args.out.with_name(args.out.stem + "_raw.png")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        comfy_meta = _run_comfy_generate(
            portrait=portrait_path,
            out=raw_out,
            width=width,
            height=height,
            steps=args.steps,
            seed=args.seed,
            cfg=args.cfg,
            positive=args.positive,
            negative=args.negative,
            host=args.host,
            port=args.port,
        )

    invented = Image.open(raw_out).convert("RGB")
    if invented.size != (width, height):
        raise SystemExit(f"size mismatch: expected {width}x{height}, got {invented.size}")

    before = nearest_collapse_metrics(invented, portrait)
    before_lattice = sample_neighbor_discontinuity(invented, portrait)
    # Continuous residual keeps invented free pixels; only smooths the sample residual.
    # Deliberately NOT StageA+highpass (that forces invent back toward mush).
    locked = project_continuous_through_nn_samples(
        invented, portrait, method=args.lock_method
    )
    after = nearest_collapse_metrics(locked, portrait)
    after_lattice = sample_neighbor_discontinuity(locked, portrait)
    if after["exact_frac"] < 1.0:
        raise SystemExit(f"Stage B continuous lock failed exact collapse: {after}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    locked.save(args.out)
    meta = {
        "schema": "local_imagegen.invent_collapse_free_pixels.v5_generate",
        "stage": "B",
        "mode": "generative_text2img_around_nn_samples",
        "portrait": str(portrait_path),
        "out": str(args.out.resolve()),
        "raw_out": str(Path(raw_out).resolve()),
        "width": width,
        "height": height,
        "scale": args.scale,
        "steps": None if args.from_raw else args.steps,
        "seed": None if args.from_raw else args.seed,
        "cfg": None if args.from_raw else args.cfg,
        "init": "none",
        "denoise": 1.0,
        "spare_nn_samples": True,
        "spare_latent_mask": False,
        "project_mode": "samples",
        "lock": "continuous_residual_through_nn_samples",
        "lock_method": args.lock_method,
        "nearest_before_lock": before,
        "nearest_after_lock": after,
        "lattice_before_lock": before_lattice,
        "lattice_after_lock": after_lattice,
        "comfy": comfy_meta,
        "note": (
            "Stage A is not used as invent init. Primary success criterion is "
            "human-reviewed CGI inventiveness with exact nearest collapse."
        ),
        "proof": (
            "Generative SD3.5 text2img with model-wrap NN sample planting "
            "(no coarse latent mask) + continuous residual exact collapse. "
            "CGI inventiveness: human review."
        ),
    }
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
