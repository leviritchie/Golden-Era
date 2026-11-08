#!/usr/bin/env python3
"""CLI for Infinity-2B collapse-authentic invent.

Commands:
  smoke  — plain T2I (proves install/VRAM)
  infer  — Stage A encode → gt_leak invent → crop → continuous residual lock
  ab     — run gt_leak={0, half, almost} on hobgoblin
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

_HERE = Path(__file__).resolve().parent
_PARENT = _HERE.parent
_ROOT = _HERE.parents[2]  # .../Olden Era Playtest Tweak
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from nearest_collapse import (  # noqa: E402
    project_continuous_through_nn_samples,
    sample_neighbor_discontinuity,
)
from sparse_nn_inpaint.gate import assert_exact_collapse, collapse_report  # noqa: E402

from condition import (  # noqa: E402
    crop_from_square,
    encode_stage_a_bit_labels,
    resolve_gt_leak,
)
from runtime import InfinityRuntime  # noqa: E402

DEFAULT_PORTRAIT = _ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png"
DEFAULT_STAGE_A = (
    _ROOT / "artifacts/collapse_authentic_upscale/candidates/hobgoblin_grid_cubic_x16.png"
)
DEFAULT_OUT_DIR = _ROOT / "artifacts/collapse_authentic_upscale/candidates/infinity_2b"

DEFAULT_PROMPT = (
    "late 1990s pre-rendered 3D CGI hobgoblin portrait, Heroes of Might and Magic III, "
    "New World Computing render style, sharp specular highlights on bronze armor, "
    "plastic 90s CGI materials, crisp geometric silhouette, desert stronghold tower, "
    "high-resolution master render, not soft blur, not hand-painted, not photoreal modern, "
    "not pixel art, not upscaled mush"
)
DEFAULT_NEGATIVE = "pixel art, soft blur, mushy upscale, modern photoreal, watercolor, sketch"


def _save_pair(out: Path, raw: Image.Image, locked: Image.Image, meta: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out.with_name(out.stem + "_raw.png")
    raw.save(raw_path)
    locked.save(out)
    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "raw": str(raw_path), "meta": str(meta_path)}, indent=2))


def cmd_smoke(args: argparse.Namespace) -> int:
    rt = InfinityRuntime.from_env()
    rt.load()
    t0 = time.time()
    img = rt.generate(
        prompt=args.prompt,
        seed=args.seed,
        cfg=args.cfg,
        tau=args.tau,
        gt_leak=0,
        gt_ls_Bl=None,
        negative_prompt=args.negative,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    meta = {
        "schema": "local_imagegen.infinity_sparse_invent.smoke.v1",
        "prompt": args.prompt,
        "seed": args.seed,
        "cfg": args.cfg,
        "tau": args.tau,
        "elapsed_s": round(time.time() - t0, 2),
        "size": list(img.size),
        "proof": "Infinity-2B plain T2I smoke (install/VRAM); collapse invent unproven",
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    print(f"saved {out}")
    return 0


def _run_infer(
    *,
    rt: InfinityRuntime,
    portrait: Path,
    stage_a: Path,
    out: Path,
    prompt: str,
    negative: str,
    seed: int,
    cfg: float,
    tau: float,
    gt_leak_spec: int | str,
) -> dict:
    lr = Image.open(portrait).convert("RGB")
    hr_a = Image.open(stage_a).convert("RGB")
    if hr_a.size[0] % lr.size[0] != 0 or hr_a.size[1] % lr.size[1] != 0:
        raise SystemExit(
            f"Stage A {hr_a.size} is not an integer multiple of portrait {lr.size}"
        )

    scale_schedule = rt.square_scale_schedule()
    n_scales = len(scale_schedule)
    gt_leak = resolve_gt_leak(n_scales, gt_leak_spec)

    gt_ls_Bl = None
    crop_box = None
    if gt_leak > 0:
        print(f"[infer] encoding Stage A for gt_leak={gt_leak}/{n_scales}", flush=True)
        gt_ls_Bl, crop_box, _padded = encode_stage_a_bit_labels(
            rt.vae, hr_a, scale_schedule, device=next(rt.vae.parameters()).device
        )
    else:
        # Still need crop box from pad geometry of Stage A frame.
        from condition import pad_stage_a_to_square

        _padded, crop_box = pad_stage_a_to_square(hr_a)

    t0 = time.time()
    gen_square = rt.generate(
        prompt=prompt,
        seed=seed,
        cfg=cfg,
        tau=tau,
        gt_leak=gt_leak,
        gt_ls_Bl=gt_ls_Bl,
        negative_prompt=negative,
    )
    raw = crop_from_square(gen_square, crop_box)
    if raw.size != hr_a.size:
        raise SystemExit(f"cropped invent {raw.size} != Stage A {hr_a.size}")

    # Persist raw invent before lock so a gate failure does not discard the gen.
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out.with_name(out.stem + "_raw.png")
    raw.save(raw_path)

    locked = project_continuous_through_nn_samples(raw, lr, method="cubic")
    nearest = assert_exact_collapse(locked, lr)
    report = collapse_report(locked, lr)
    lattice_raw = sample_neighbor_discontinuity(raw, lr)

    meta = {
        "schema": "local_imagegen.infinity_sparse_invent.infer.v1",
        "backend": "infinity_2b",
        "prompt": prompt,
        "negative": negative,
        "seed": seed,
        "cfg": cfg,
        "tau": tau,
        "gt_leak": gt_leak,
        "gt_leak_spec": gt_leak_spec,
        "n_scales": n_scales,
        "crop_box": list(crop_box),
        "portrait": str(portrait),
        "stage_a": str(stage_a),
        "elapsed_s": round(time.time() - t0, 2),
        "nearest_after_lock": nearest,
        "lattice_after_lock": report["lattice"],
        "lattice_raw": lattice_raw,
        "note": (
            "Hard NN continuous residual lock only (no soft radial paste). "
            "Judge CGI invent on _raw.png; locked image gates exact nearest collapse."
        ),
        "proof": (
            "Infinity-2B + Stage-A gt_leak invent + continuous residual exact collapse. "
            "Collapse generated-artifact validated; CGI inventiveness = human review."
        ),
    }
    locked.save(out)
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "raw": str(raw_path), "meta": str(out.with_suffix(".json"))}, indent=2))
    return meta


def cmd_infer(args: argparse.Namespace) -> int:
    rt = InfinityRuntime.from_env()
    rt.load()
    _run_infer(
        rt=rt,
        portrait=Path(args.portrait),
        stage_a=Path(args.init_hr),
        out=Path(args.out),
        prompt=args.prompt,
        negative=args.negative,
        seed=args.seed,
        cfg=args.cfg,
        tau=args.tau,
        gt_leak_spec=args.gt_leak,
    )
    return 0


def cmd_ab(args: argparse.Namespace) -> int:
    rt = InfinityRuntime.from_env()
    rt.load()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = ["0", "half", "almost"]
    rows = []
    for spec in specs:
        slug = f"hobgoblin_gtleak_{spec}_n{args.seed}"
        out = out_dir / f"{slug}.png"
        print(f"=== ab gt_leak={spec} -> {out.name} ===", flush=True)
        meta = _run_infer(
            rt=rt,
            portrait=Path(args.portrait),
            stage_a=Path(args.init_hr),
            out=out,
            prompt=args.prompt,
            negative=args.negative,
            seed=args.seed,
            cfg=args.cfg,
            tau=args.tau,
            gt_leak_spec=spec,
        )
        rows.append(
            {
                "slug": slug,
                "gt_leak": meta["gt_leak"],
                "exact_frac": meta["nearest_after_lock"]["exact_frac"],
                "lattice_raw_mean": meta["lattice_raw"]["mean"],
                "lattice_lock_mean": meta["lattice_after_lock"]["mean"],
                "out": str(out),
                "raw": str(out.with_name(out.stem + "_raw.png")),
            }
        )
    report = {
        "schema": "local_imagegen.infinity_sparse_invent.ab.v1",
        "results": rows,
        "proof": "A/B gt_leak on hobgoblin; exact collapse gated; CGI = human review of _raw.png",
    }
    report_path = out_dir / "ab_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {report_path}")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--negative", default=DEFAULT_NEGATIVE)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--cfg", type=float, default=3.0)
    p.add_argument("--tau", type=float, default=0.5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    smoke_p = sub.add_parser("smoke", help="plain T2I smoke")
    _add_common(smoke_p)
    smoke_p.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR / "smoke_t2i.png"),
    )
    smoke_p.set_defaults(func=cmd_smoke)

    infer_p = sub.add_parser("infer", help="Stage-A-conditioned invent + collapse lock")
    _add_common(infer_p)
    infer_p.add_argument("--portrait", default=str(DEFAULT_PORTRAIT))
    infer_p.add_argument("--init-hr", default=str(DEFAULT_STAGE_A))
    infer_p.add_argument(
        "--gt-leak",
        default="half",
        help="int or alias: 0|pure|half|almost",
    )
    infer_p.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR / "hobgoblin_infer.png"),
    )
    infer_p.set_defaults(func=cmd_infer)

    ab_p = sub.add_parser("ab", help="gt_leak A/B on hobgoblin")
    _add_common(ab_p)
    ab_p.add_argument("--portrait", default=str(DEFAULT_PORTRAIT))
    ab_p.add_argument("--init-hr", default=str(DEFAULT_STAGE_A))
    ab_p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ab_p.set_defaults(func=cmd_ab)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
