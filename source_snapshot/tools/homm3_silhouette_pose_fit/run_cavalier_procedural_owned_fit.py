#!/usr/bin/env python3
"""Procedural sprite-guided fixed-length IK on owned cavalier bind.

Pipeline:
  1. Per-frame mount landmarks from DEF sprites (sprite_landmarks_infer_mount.py)
  2. Rotate-only fixed-length IK on owned Y-up master (blender_fixed_length_ik_mount.py)
  3. Lit preview + optional 3-way compare GIF (sprite | smartrig GPU | procedural IK)

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
DEFAULT_CONFIG = TOOL / "configs/h3_cavalier_idle_attack_front_owned_fixed_length_ik.json"
DEFAULT_BLENDER = Path(r"V:/Tools/blender-3.5.1/blender.exe")
DEFAULT_PYTHON = Path(r"C:/Python312/python.exe")
OUT_ROOT = ROOT / "artifacts/cavalier_pose_pipeline/out_fit/idle_attack_front_owned_fixed_length"
COMPARE_OUT = ROOT / "artifacts/cavalier_pose_pipeline/owned_rig_test/idle_attack_front/procedural_vs_gpu.gif"
SPRITE_DIR = (
    ROOT
    / "artifacts/pose_picker_runs/h3_cavalier/idle_attack_front/frames_def12_nn_idle_attack_front_shadow_culled"
)
SMARTRIG_RASTER = ROOT / "artifacts/cavalier_pose_pipeline/owned_rig_test/idle_attack_front/smartrig_raster"
OWNED_GPU_RASTER = ROOT / "artifacts/cavalier_pose_pipeline/owned_rig_test/idle_attack_front/owned_raster"


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    ap.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    ap.add_argument("--skip-infer", action="store_true")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-preview", action="store_true")
    ap.add_argument("--skip-compare", action="store_true")
    ap.add_argument("--animation", default="idle_attack_front")
    return ap.parse_args()


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("Running:", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=str(cwd or ROOT)).returncode
    if rc != 0:
        raise SystemExit(rc)


def _compose_compare(*, frame_count: int, out_gif: Path) -> None:
    from compose_method_compare_gif import main as compose_main

    proc_dir = OUT_ROOT / "preview/fixed_length"
    argv = [
        "--out",
        str(out_gif),
        "--frame-count",
        str(frame_count),
        "--duration-ms",
        "180",
        "--panel",
        "sprite",
        str(SPRITE_DIR),
        "--panel",
        "gpu_owned",
        str(OWNED_GPU_RASTER),
        "--panel",
        "procedural_ik",
        str(proc_dir),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        compose_main()
    finally:
        sys.argv = old


def main() -> int:
    args = _parse()
    config = args.config.resolve()
    if not config.is_file():
        raise FileNotFoundError(config)

    if not args.skip_infer:
        _run(
            [
                str(args.python),
                str(TOOL / "sprite_landmarks_infer_mount.py"),
                "--config",
                str(config),
            ]
        )

    fit_argv = [
        str(args.python),
        str(TOOL / "run_fit.py"),
        "--config",
        str(config),
        "--skip-infer",
        "--dwpose-python",
        str(args.python),
        "--blender",
        str(args.blender),
    ]
    if args.skip_fit:
        fit_argv.append("--skip-fit")
    if args.skip_preview:
        fit_argv.append("--skip-preview")
    _run(fit_argv)

    report_path = OUT_ROOT / "fit_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "ok": True,
                    "meanBodyLossPx": report.get("meanBodyLossPx"),
                    "meanLanceTipErrorPx": report.get("meanLanceTipErrorPx"),
                    "meanHorseNoseErrorPx": report.get("meanHorseNoseErrorPx"),
                    "glb": report.get("glb"),
                    "previewGif": str(
                        OUT_ROOT
                        / "preview/fixed_length/idle_attack_front_owned_fixed_length_fixed_length_side_by_side.gif"
                    ),
                },
                indent=2,
            ),
            flush=True,
        )

    if not args.skip_compare:
        if not OWNED_GPU_RASTER.is_dir():
            print(f"skip compare: missing {OWNED_GPU_RASTER}", flush=True)
        else:
            frame_count = len(list(SPRITE_DIR.glob("*.png")))
            COMPARE_OUT.parent.mkdir(parents=True, exist_ok=True)
            _compose_compare(frame_count=frame_count, out_gif=COMPARE_OUT)
            print(json.dumps({"compareGif": str(COMPARE_OUT)}, indent=2), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
