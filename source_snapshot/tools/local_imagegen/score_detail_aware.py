#!/usr/bin/env python3
"""OBSOLETE for the active NN-collapse lane.

Kept only as a historical lab scorer. Active contract is:
  diffusion + era prompt + inter-step KSamplerNearestCollapse
  scored with verify_upscale_collapse_authenticity.py --method nearest

---

Re-score collapse candidates with a detail-aware policy.

Root failure of auth-only / auth+anti-block ranking:
  Soft Tile+LoRA can win while looking muddy because collapse authenticity
  rewards near-lanczos enlargements. Those barely invent high-frequency
  structure relative to a lanczos baseline.

This scorer keeps collapse authenticity, but multiplies in:
  - generative HF residual vs the lanczos baseline (detail that was invented)
  - anti-NN flat-block penalty (so hard mosaics cannot fake detail via edges)

Proof: source/static validated only. Does not prove perceptual CGI quality alone.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DIR = ROOT / "artifacts" / "collapse_authentic_upscale"
VERIFY = ROOT / "tools" / "verify_upscale_collapse_authenticity.py"


def _load_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def generative_hf_mae(candidate: Image.Image, baseline: Image.Image, blur_radius: float = 3.0) -> float:
    """Mean abs high-frequency residual difference vs baseline (invented detail)."""
    c = np.asarray(candidate, dtype=np.float32)
    b = np.asarray(baseline.resize(candidate.size, Image.Resampling.LANCZOS), dtype=np.float32)
    c_blur = np.asarray(candidate.filter(ImageFilter.GaussianBlur(radius=blur_radius)), dtype=np.float32)
    b_blur = np.asarray(
        baseline.resize(candidate.size, Image.Resampling.LANCZOS).filter(
            ImageFilter.GaussianBlur(radius=blur_radius)
        ),
        dtype=np.float32,
    )
    return float(np.mean(np.abs((c - c_blur) - (b - b_blur))))


def flat_block_frac(candidate: Image.Image, block: int = 16) -> float:
    arr = np.asarray(candidate, dtype=np.float32)
    h, w, _ = arr.shape
    vars_ = []
    for y in range(0, h - block + 1, block):
        for x in range(0, w - block + 1, block):
            vars_.append(arr[y : y + block, x : x + block].reshape(-1, 3).var(axis=0).mean())
    return float((np.asarray(vars_) < 1.0).mean())


def detail_score(gen_hf: float, *, soft: float = 0.8, hard: float = 2.5) -> float:
    """Map generative HF MAE into [0,1]. Near-lanczos (~0-0.8) scores low; ~2.5 saturates."""
    if gen_hf <= soft:
        return max(0.0, gen_hf / soft) * 0.25
    span = max(1e-6, hard - soft)
    return float(min(1.0, 0.25 + 0.75 * (gen_hf - soft) / span))


def fidelity_score(auth: float, flat_frac: float) -> float:
    """Collapse authenticity after anti-NN penalty (NN mosaics are not 'faithful detail')."""
    anti_nn = 1.0 - flat_frac
    return float(max(0.0, min(1.0, auth * (0.25 + 0.75 * anti_nn))))


def f1_balance(precision: float, recall: float) -> float:
    """Harmonic mean — same shape as F1: either arm near 0 collapses the score."""
    p = max(0.0, float(precision))
    r = max(0.0, float(recall))
    if p + r <= 1e-12:
        return 0.0
    return float(2.0 * p * r / (p + r))


def combined_score(auth: float, gen_hf: float, flat_frac: float) -> float:
    """F1-style balance of fidelity (auth×anti-NN) and generative detail."""
    return f1_balance(fidelity_score(auth, flat_frac), detail_score(gen_hf))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Lanczos baseline at target size (default: candidates/_baseline_lanczos_x16.png)",
    )
    ap.add_argument(
        "--auth-json",
        type=Path,
        default=None,
        help="Existing collapse scoreboard JSON with ranked[].authenticity_score",
    )
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    cand_dir = args.out_dir / "candidates"
    baseline_path = args.baseline or (cand_dir / "_baseline_lanczos_x16.png")
    if not baseline_path.is_file():
        raise SystemExit(f"lanczos baseline missing: {baseline_path}")
    baseline = _load_rgb(baseline_path)

    auth_path = args.auth_json or (args.out_dir / "reports" / "_tmp_lever_scores.json")
    if not auth_path.is_file():
        # fall back to method_levers scores if present
        ml = args.out_dir / "reports" / "method_levers.json"
        if not ml.is_file():
            raise SystemExit(f"need auth scoreboard at {auth_path} or {ml}")
        scores_map = json.loads(ml.read_text(encoding="utf-8")).get("scores") or {}
        auth_rows = [
            {"candidate": v["path"], "authenticity_score": v["authenticity_score"], "global_mae_rgb": v.get("global_mae_rgb")}
            for v in scores_map.values()
        ]
    else:
        auth_rows = json.loads(auth_path.read_text(encoding="utf-8"))["ranked"]

    ranked = []
    for row in auth_rows:
        path = Path(row["candidate"])
        if not path.is_file():
            continue
        if path.name.startswith("_baseline"):
            # Baseline defines the zero of generative HF; keep for reference only.
            continue
        im = _load_rgb(path)
        gen_hf = generative_hf_mae(im, baseline)
        flat = flat_block_frac(im)
        auth = float(row["authenticity_score"])
        fidelity = fidelity_score(auth, flat)
        detail = detail_score(gen_hf)
        entry = {
            "candidate": str(path),
            "authenticity_score": auth,
            "global_mae_rgb": row.get("global_mae_rgb"),
            "gen_hf_mae_vs_lanczos": gen_hf,
            "fidelity_score": fidelity,
            "detail_score": detail,
            "flat_block_frac": flat,
            "f1_fidelity_detail": f1_balance(fidelity, detail),
            "combined_detail_aware_score": combined_score(auth, gen_hf, flat),
            "policy": "F1(fidelity=auth*(0.25+0.75*anti_nn), detail=genHF_mapped)",
        }
        ranked.append(entry)

    ranked.sort(key=lambda r: r["f1_fidelity_detail"], reverse=True)
    for i, row in enumerate(ranked, 1):
        row["rank"] = i

    out = {
        "schema": "collapse_authentic_upscale.detail_aware_score.v2",
        "proof": "source/static validated",
        "baseline": str(baseline_path.resolve()),
        "note": (
            "F1-style harmonic mean of fidelity (collapse auth × anti-NN) and generative "
            "detail (HF residual vs lanczos). High auth with muddy near-lanczos detail, "
            "or high detail with drifted identity, both get pulled down."
        ),
        "ranked": ranked,
    }
    json_out = args.json_out or (args.out_dir / "reports" / "scoreboard_detail_aware.json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"Wrote {json_out}")
    print(f"{'rank':>4} {'F1':>7} {'fidelity':>9} {'detail':>7} {'auth':>7} {'genHF':>7}  name")
    for row in ranked[:15]:
        print(
            f"{row['rank']:4d} {row['f1_fidelity_detail']:7.3f} "
            f"{row['fidelity_score']:9.3f} {row['detail_score']:7.3f} "
            f"{row['authenticity_score']:7.3f} {row['gen_hf_mae_vs_lanczos']:7.2f}  "
            f"{Path(row['candidate']).name}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
