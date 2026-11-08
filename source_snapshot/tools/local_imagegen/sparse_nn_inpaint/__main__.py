#!/usr/bin/env python3
"""Sparse NN inpaint via modified SD3.5 (sparse RePaint).

Known = Pillow-NEAREST sample sites from TwCrPort (one pixel per SxS block).
Unknown = all other HR pixels — true blanks to the conditioner, not soft upsample.

Init modes:
  none          — EmptySD3 latent (pure noise schedule). No Stage A / no soft fill.
                  Known sites enter only via RePaint: forward_noise(portrait, t).
  sparse_blank  — plant LR RGB on black HR; VAE still spatially bleeds, but no cubic fill.
  sparse_noise  — plant LR RGB on noise HR; same caveat.
  stage_a       — soft inverse-fill init (legacy soft-evidence lane; not true sparse).

True sparse contract: influence_radius=0 (hard lattice only). Soft radial influence
is a different experiment that deliberately bleeds known colors into blanks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

_HERE = Path(__file__).resolve().parent
_PARENT = _HERE.parent
ROOT = _HERE.parents[3]
COMFY_HELPER = _PARENT / "comfy_exact_img2img_sd35.py"
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from .gate import assert_exact_collapse, collapse_report
except ImportError:
    from gate import assert_exact_collapse, collapse_report

from nearest_collapse import (  # noqa: E402
    project_continuous_through_nn_samples,
)
from optimize_collapse_authentic_hr import synthesize_collapse_authentic_hr  # noqa: E402


def _run_comfy_repaint(
    *,
    portrait: Path,
    init_mode: str,
    init_hr: Path | None,
    out: Path,
    width: int,
    height: int,
    denoise: float,
    steps: int,
    seed: int,
    cfg: float,
    positive: str,
    negative: str,
    host: str,
    port: int,
    influence_radius: float,
    influence_falloff: str,
    project_every_n: int,
    project_start_percent: float,
    project_end_percent: float,
) -> dict:
    if init_mode not in ("none", "hr"):
        raise SystemExit(f"comfy init_mode must be none|hr, got {init_mode!r}")
    cmd = [
        sys.executable,
        str(COMFY_HELPER),
        "--image",
        str(portrait),
        "--init",
        init_mode,
        "--out",
        str(out),
        "--width",
        str(width),
        "--height",
        str(height),
        "--denoise",
        str(denoise),
        "--steps",
        str(steps),
        "--seed",
        str(seed),
        "--cfg",
        str(cfg),
        "--project-mode",
        "repaint",
        "--no-spare-nn-samples",
        "--no-spare-latent-mask",
        "--interstep-nearest-collapse",
        "--project-every-n",
        str(project_every_n),
        "--project-start-percent",
        str(project_start_percent),
        "--project-end-percent",
        str(project_end_percent),
        "--influence-radius",
        str(influence_radius),
        "--influence-falloff",
        str(influence_falloff),
        "--filename-prefix",
        "sparse_nn_true",
        "--positive",
        positive,
        "--negative",
        negative,
        "--host",
        host,
        "--port",
        str(port),
    ]
    if init_mode == "hr":
        if init_hr is None:
            raise SystemExit("init_mode=hr requires init_hr path")
        cmd.extend(["--init-hr", str(init_hr)])
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            "sparse_nn_inpaint Comfy helper failed:\n"
            + (proc.stdout or "")[-2000:]
            + "\n"
            + (proc.stderr or "")[-2000:]
        )
    if not out.is_file():
        raise SystemExit(
            "sparse_nn_inpaint Comfy helper returned success but raw out missing: "
            f"{out}\nstdout:\n{(proc.stdout or '')[-1500:]}"
        )
    meta_path = out.with_suffix(".json")
    if meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"stdout_tail": (proc.stdout or "")[-1500:]}


def infer(args: argparse.Namespace) -> int:
    portrait_path = args.portrait.resolve()
    if not portrait_path.is_file():
        raise SystemExit(f"portrait not found: {portrait_path}")
    if args.scale < 2:
        raise SystemExit("--scale must be >= 2")
    if not (0.0 < args.denoise <= 1.0):
        raise SystemExit("--denoise must be in (0, 1]")

    portrait = Image.open(portrait_path).convert("RGBA")
    lr_w, lr_h = portrait.size
    width = lr_w * args.scale
    height = lr_h * args.scale

    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    init_mode = str(args.init_mode)
    if init_mode not in ("none", "sparse_blank", "sparse_noise", "stage_a"):
        raise SystemExit(f"unknown --init-mode {init_mode!r}")
    if init_mode != "stage_a" and float(args.influence_radius) != 0.0:
        print(
            f"[sparse_nn_inpaint] WARNING: true-sparse init_mode={init_mode} "
            f"with influence_radius={args.influence_radius} bleeds known colors into blanks. "
            "Use --influence-radius 0 for lattice-only conditioning.",
            flush=True,
        )

    init_hr_path: Path | None = None
    comfy_init = "none"
    stage_a_meta: dict
    if init_mode == "none":
        stage_a_meta = {
            "source": "empty_sd3_latent",
            "path": None,
            "note": "No pixel init. Known sites only via RePaint forward_noise(portrait,t).",
        }
        comfy_init = "none"
    elif init_mode in ("sparse_blank", "sparse_noise"):
        from mask import plant_nn_samples_rgb
        import numpy as np

        planted_path = args.out.with_name(args.out.stem + f"_{init_mode}_init.png")
        if init_mode == "sparse_blank":
            hr_f, known = plant_nn_samples_rgb(portrait.convert("RGB"), scale=args.scale)
        else:
            rng = np.random.default_rng(int(args.seed) & 0xFFFFFFFF)
            hr_f, known = plant_nn_samples_rgb(portrait.convert("RGB"), scale=args.scale)
            noise = rng.random(hr_f.shape, dtype=np.float32)
            hr_f = np.where(known[..., None], hr_f, noise * 255.0)
        Image.fromarray(np.clip(hr_f, 0, 255).astype(np.uint8), mode="RGB").save(planted_path)
        init_hr_path = planted_path
        comfy_init = "hr"
        stage_a_meta = {
            "source": init_mode,
            "path": str(planted_path.resolve()),
            "known_frac": float(known.mean()),
            "note": (
                "LR RGB planted only at NN sample sites; free pixels are "
                + ("black" if init_mode == "sparse_blank" else "noise")
                + ". VAE encode still spatially mixes — prefer init-mode=none when possible."
            ),
        }
        with Image.open(init_hr_path) as im:
            if im.size != (width, height):
                raise SystemExit(
                    f"init-hr size {im.size} != expected {width}x{height} for scale {args.scale}"
                )
    else:
        # Legacy soft-evidence Stage A.
        stage_a_path = args.out.with_name(args.out.stem + "_stage_a.png")
        if args.init_hr is not None:
            init_hr_path = args.init_hr.resolve()
            if not init_hr_path.is_file():
                raise SystemExit(f"--init-hr not found: {init_hr_path}")
            stage_a_meta = {"source": "provided_stage_a", "path": str(init_hr_path)}
        else:
            stage_a, synth_meta = synthesize_collapse_authentic_hr(
                portrait.convert("RGB"),
                scale=args.scale,
                method=args.stage_a_method,
            )
            stage_a.save(stage_a_path)
            init_hr_path = stage_a_path
            stage_a_meta = {
                "source": "synthesized_stage_a",
                "path": str(stage_a_path.resolve()),
                **synth_meta,
                "note": "Soft inverse-fill — not true sparse conditioning.",
            }
        comfy_init = "hr"
        with Image.open(init_hr_path) as im:
            if im.size != (width, height):
                raise SystemExit(
                    f"init-hr size {im.size} != expected {width}x{height} for scale {args.scale}"
                )

    comfy_meta: dict | None = None
    if args.from_raw is not None:
        raw_out = args.from_raw.resolve()
        if not raw_out.is_file():
            raise SystemExit(f"--from-raw not found: {raw_out}")
    else:
        raw_out = args.out.with_name(args.out.stem + "_raw.png")
        comfy_meta = _run_comfy_repaint(
            portrait=portrait_path,
            init_mode=comfy_init,
            init_hr=init_hr_path,
            out=raw_out,
            width=width,
            height=height,
            denoise=args.denoise,
            steps=args.steps,
            seed=args.seed,
            cfg=args.cfg,
            positive=args.positive,
            negative=args.negative,
            host=args.host,
            port=args.port,
            influence_radius=args.influence_radius,
            influence_falloff=args.influence_falloff,
            project_every_n=args.project_every_n,
            project_start_percent=args.project_start_percent,
            project_end_percent=args.project_end_percent,
        )

    invented = Image.open(raw_out).convert("RGB")
    if invented.size != (width, height):
        raise SystemExit(f"size mismatch: expected {width}x{height}, got {invented.size}")

    before_report = collapse_report(invented, portrait)
    locked = project_continuous_through_nn_samples(
        invented, portrait, method=args.lock_method
    )
    after = assert_exact_collapse(locked, portrait)
    after_lattice = collapse_report(locked, portrait)["lattice"]

    locked.save(args.out)
    meta = {
        "schema": "local_imagegen.sparse_nn_inpaint.v2",
        "mode": "sd35_sparse_repaint",
        "init_mode": init_mode,
        "comfy_init": comfy_init,
        "portrait": str(portrait_path),
        "out": str(args.out.resolve()),
        "raw_out": str(Path(raw_out).resolve()),
        "init": stage_a_meta,
        "width": width,
        "height": height,
        "scale": args.scale,
        "denoise": None if args.from_raw else args.denoise,
        "steps": None if args.from_raw else args.steps,
        "seed": None if args.from_raw else args.seed,
        "cfg": None if args.from_raw else args.cfg,
        "project_mode": "repaint",
        "spare_nn_samples": False,
        "spare_latent_mask": False,
        "influence_radius": args.influence_radius,
        "influence_falloff": args.influence_falloff,
        "project_every_n": args.project_every_n,
        "project_start_percent": args.project_start_percent,
        "project_end_percent": args.project_end_percent,
        "lock": "continuous_residual_through_nn_samples",
        "lock_method": args.lock_method,
        "nearest_before_lock": before_report["nearest"],
        "nearest_after_lock": after,
        "lattice_before_lock": before_report["lattice"],
        "lattice_after_lock": after_lattice,
        "comfy": comfy_meta,
        "note": (
            "Known=NN sample sites only. init_mode=none avoids soft Stage A filler; "
            "influence_radius=0 keeps RePaint on hard lattice dots. Exact collapse gated. "
            "CGI inventiveness: human review of _raw.png."
        ),
        "proof": (
            "SD3.5 Medium + sparse RePaint + continuous residual exact collapse. "
            "Collapse generated-artifact validated; true-sparse conditioning = "
            f"init_mode={init_mode}, influence_radius={args.influence_radius}; "
            "CGI inventiveness unproven until human review."
        ),
    }
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    infer_p = sub.add_parser("infer", help="Sparse RePaint invent from TwCrPort")
    infer_p.add_argument("--portrait", type=Path, required=True)
    infer_p.add_argument("--out", type=Path, required=True)
    infer_p.add_argument("--scale", type=int, default=16)
    infer_p.add_argument(
        "--init-mode",
        choices=("none", "sparse_blank", "sparse_noise", "stage_a"),
        default="none",
        help="none=empty latent (true sparse); sparse_*=plant lattice only; stage_a=soft fill",
    )
    infer_p.add_argument(
        "--init-hr",
        type=Path,
        default=None,
        help="Optional Stage A HR when --init-mode stage_a",
    )
    infer_p.add_argument(
        "--stage-a-method",
        choices=("grid_linear", "grid_cubic", "harmonic"),
        default="grid_cubic",
    )
    infer_p.add_argument(
        "--denoise",
        type=float,
        default=1.0,
        help="Forced to 1.0 for --init-mode none",
    )
    infer_p.add_argument("--steps", type=int, default=40)
    infer_p.add_argument("--seed", type=int, default=7)
    infer_p.add_argument("--cfg", type=float, default=5.5)
    infer_p.add_argument("--host", type=str, default="127.0.0.1")
    infer_p.add_argument("--port", type=int, default=8188)
    infer_p.add_argument("--lock-method", choices=("cubic", "linear"), default="cubic")
    infer_p.add_argument(
        "--influence-radius",
        type=float,
        default=0.0,
        help="0=hard NN lattice only (true sparse). >0 soft-bleeds known colors into blanks.",
    )
    infer_p.add_argument(
        "--influence-falloff",
        choices=("linear", "quad", "cosine", "gauss"),
        default="cosine",
    )
    infer_p.add_argument("--project-every-n", type=int, default=1)
    infer_p.add_argument(
        "--project-start-percent",
        type=float,
        default=0.0,
        help="0=soft influence from the first generative step (not late paste)",
    )
    infer_p.add_argument("--project-end-percent", type=float, default=1.0)
    infer_p.add_argument(
        "--from-raw",
        type=Path,
        default=None,
        help="Skip Comfy; continuous-lock an existing raw PNG",
    )
    infer_p.add_argument(
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
    infer_p.add_argument(
        "--negative",
        type=str,
        default=(
            "pixel art, mosaic, nearest neighbor blocks, hand-painted, oil painting, "
            "illustration, anime, photoreal modern, text, watermark, blurry, soft mush, "
            "oversmoothed, gaussian blur, low resolution upscale, noise grain lattice"
        ),
    )
    infer_p.set_defaults(func=infer)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
