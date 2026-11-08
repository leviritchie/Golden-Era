#!/usr/bin/env python3
"""Focused generative soft-influence sweep (influence from step 0, not late paste).

Writes RAW comparisons so radius/falloff differences are invent differences.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
CLI = Path(__file__).resolve().parent / "__main__.py"
OUT_DIR = ROOT / "artifacts/collapse_authentic_upscale/candidates/influence_gen_sweep"
PORTRAIT = ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png"
INIT_HR = ROOT / "artifacts/collapse_authentic_upscale/candidates/hobgoblin_grid_cubic_x16.png"

CONFIGS = [
    {"influence_radius": 0.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 7},
    {"influence_radius": 8.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "linear", "denoise": 0.85, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "gauss", "denoise": 0.85, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "cosine", "denoise": 0.75, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "cosine", "denoise": 0.95, "seed": 7},
    {"influence_radius": 4.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 11},
    {"influence_radius": 6.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 7},
    {"influence_radius": 2.0, "influence_falloff": "cosine", "denoise": 0.85, "seed": 7},
]


def _slug(cfg: dict) -> str:
    return (
        f"gen_r{cfg['influence_radius']:g}_{cfg['influence_falloff']}"
        f"_d{cfg['denoise']:g}_n{cfg['seed']}"
    )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    raw_paths = {}
    for i, cfg in enumerate(CONFIGS):
        slug = _slug(cfg)
        out = OUT_DIR / f"hobgoblin_{slug}.png"
        print(f"[{i + 1}/{len(CONFIGS)}] {slug}", flush=True)
        cmd = [
            sys.executable,
            str(CLI),
            "infer",
            "--portrait",
            str(PORTRAIT),
            "--init-hr",
            str(INIT_HR),
            "--out",
            str(out),
            "--scale",
            "16",
            "--denoise",
            str(cfg["denoise"]),
            "--steps",
            "28",
            "--seed",
            str(cfg["seed"]),
            "--cfg",
            "5.5",
            "--influence-radius",
            str(cfg["influence_radius"]),
            "--influence-falloff",
            str(cfg["influence_falloff"]),
            "--project-every-n",
            "1",
            "--project-start-percent",
            "0.0",
            "--project-end-percent",
            "1.0",
        ]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=str(ROOT), check=False, capture_output=True, text=True)
        row = {
            "slug": slug,
            "cfg": cfg,
            "out": str(out),
            "raw": str(out.with_name(out.stem + "_raw.png")),
            "elapsed_s": round(time.time() - t0, 2),
            "returncode": proc.returncode,
        }
        if proc.returncode == 0 and out.with_suffix(".json").is_file():
            meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
            row["exact_frac"] = meta["nearest_after_lock"]["exact_frac"]
            row["lattice_after"] = meta["lattice_after_lock"]["mean"]
            raw = Path(row["raw"])
            if raw.is_file():
                raw_paths[slug] = raw
                row["raw_sha256_16"] = hashlib.sha256(raw.read_bytes()).hexdigest()[:16]
        else:
            row["error"] = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-1200:]
            print("  FAIL", flush=True)
        rows.append(row)

    # Pairwise raw mean-abs between all successes
    slugs = [r["slug"] for r in rows if r.get("raw_sha256_16")]
    pairwise = {}
    for i, a in enumerate(slugs):
        aa = np.asarray(Image.open(raw_paths[a]).convert("RGB"), np.float32)
        for b in slugs[i + 1 :]:
            bb = np.asarray(Image.open(raw_paths[b]).convert("RGB"), np.float32)
            pairwise[f"{a}__vs__{b}"] = float(np.abs(aa - bb).mean())

    report = {
        "schema": "local_imagegen.sparse_nn_inpaint.influence_gen_sweep.v1",
        "note": (
            "Soft influence applied before denoiser + on x0 + after Euler from step 0. "
            "Compare RAW mean-abs; locked images are post-measurement."
        ),
        "unique_raw_hashes": len({r.get("raw_sha256_16") for r in rows if r.get("raw_sha256_16")}),
        "results": rows,
        "raw_pairwise_mean_abs": pairwise,
    }
    (OUT_DIR / "gen_sweep_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "unique_raw": report["unique_raw_hashes"],
        "n": len(rows),
        "pairwise_sample": {k: round(v, 3) for k, v in list(pairwise.items())[:8]},
        "out": str(OUT_DIR / "gen_sweep_report.json"),
    }, indent=2))
    return 0 if all(r["returncode"] == 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
