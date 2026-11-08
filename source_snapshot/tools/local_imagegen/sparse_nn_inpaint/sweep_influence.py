#!/usr/bin/env python3
"""Sweep soft-influence RePaint params on hobgoblin; write scoreboard JSON."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = Path(__file__).resolve().parent / "__main__.py"
OUT_DIR = ROOT / "artifacts/collapse_authentic_upscale/candidates/influence_sweep"
PORTRAIT = ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png"
INIT_HR = ROOT / "artifacts/collapse_authentic_upscale/candidates/hobgoblin_grid_cubic_x16.png"

# Compact grid covering hard dots vs soft radii / falloffs / denoise / schedule.
CONFIGS: list[dict] = []
for radius in (0.0, 2.0, 4.0, 6.0, 8.0):
    falloffs = ("quad",) if radius == 0.0 else ("linear", "quad", "cosine", "gauss")
    for falloff in falloffs:
        for denoise in (0.80, 0.90):
            for start in (0.45, 0.60):
                CONFIGS.append(
                    {
                        "influence_radius": radius,
                        "influence_falloff": falloff,
                        "denoise": denoise,
                        "project_start_percent": start,
                        "project_every_n": 2,
                        "steps": 24,
                        "seed": 7,
                        "cfg": 5.5,
                    }
                )


def _slug(cfg: dict) -> str:
    return (
        f"r{cfg['influence_radius']:g}_"
        f"{cfg['influence_falloff']}_"
        f"d{cfg['denoise']:g}_"
        f"s{cfg['project_start_percent']:g}_"
        f"e{cfg['project_every_n']}_"
        f"n{cfg['seed']}"
    )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not PORTRAIT.is_file():
        raise SystemExit(f"portrait missing: {PORTRAIT}")
    if not INIT_HR.is_file():
        raise SystemExit(f"init-hr missing: {INIT_HR}")

    results: list[dict] = []
    t0 = time.time()
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
            str(cfg["steps"]),
            "--seed",
            str(cfg["seed"]),
            "--cfg",
            str(cfg["cfg"]),
            "--influence-radius",
            str(cfg["influence_radius"]),
            "--influence-falloff",
            str(cfg["influence_falloff"]),
            "--project-every-n",
            str(cfg["project_every_n"]),
            "--project-start-percent",
            str(cfg["project_start_percent"]),
            "--project-end-percent",
            "1.0",
        ]
        started = time.time()
        proc = subprocess.run(cmd, cwd=str(ROOT), check=False, capture_output=True, text=True)
        elapsed = time.time() - started
        row: dict = {
            "slug": slug,
            "cfg": cfg,
            "out": str(out),
            "elapsed_s": round(elapsed, 2),
            "returncode": proc.returncode,
        }
        meta_path = out.with_suffix(".json")
        if proc.returncode == 0 and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            row["exact_frac"] = meta["nearest_after_lock"]["exact_frac"]
            row["lattice_after"] = meta["lattice_after_lock"]["mean"]
            row["lattice_before"] = meta["lattice_before_lock"]["mean"]
            row["mae_before"] = meta["nearest_before_lock"]["mae_rgb"]
        else:
            row["error"] = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-1500:]
            print(f"  FAIL rc={proc.returncode}", flush=True)
        results.append(row)
        # Checkpoint scoreboard after each run.
        scoreboard = {
            "schema": "local_imagegen.sparse_nn_inpaint.influence_sweep.v1",
            "n_configs": len(CONFIGS),
            "n_done": len(results),
            "elapsed_total_s": round(time.time() - t0, 2),
            "results": results,
        }
        (OUT_DIR / "scoreboard.json").write_text(
            json.dumps(scoreboard, indent=2), encoding="utf-8"
        )

    ok = [r for r in results if r.get("exact_frac") == 1.0]
    ok.sort(key=lambda r: (r.get("lattice_after", 1e9), r.get("mae_before", 1e9)))
    summary = {
        "n_ok": len(ok),
        "n_fail": len(results) - len(ok),
        "best_by_lattice": ok[:8] if ok else [],
        "scoreboard": str((OUT_DIR / "scoreboard.json").resolve()),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if all(r.get("returncode") == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
