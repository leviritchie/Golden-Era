#!/usr/bin/env python3
"""Rescore-parity check and optional gated warp detect on owned Cavalier clips.

Default: rescore frozen poses with the source clip objective and verify parity
with stored ``frameScores``. Corrections are off unless ``--apply`` is passed
and each frame beats its source score under the same rescore config.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
POSE_RUNS = ROOT / "artifacts/pose_picker_runs"
PIPELINE = ROOT / "artifacts/cavalier_pose_pipeline"
OWNED_MASTER = PIPELINE / "owned_bind/h3_cavalier_master_yup.glb"
GROUPS = TOOL / "cavalier_owned_anatomy_groups.json"
DEFAULT_CLIP_RUN = "owned_fused_push_v1_pipeline"
DEFAULT_OUT_RUN = "owned_warp_repair_v2_rescore"
COMPARE_OUT = PIPELINE / "owned_rig_test"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_post_pose_warp_repair import RescoreParityConfig, WarpDetectConfig, repair_clip_warp  # noqa: E402


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--animation", default="idle_attack_front")
    ap.add_argument("--clip-run", default=DEFAULT_CLIP_RUN)
    ap.add_argument("--out-run", default=DEFAULT_OUT_RUN)
    ap.add_argument("--mesh-glb", type=Path, default=OWNED_MASTER)
    ap.add_argument("--groups", type=Path, default=GROUPS)
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Attempt gated vertex offsets (requires rescore parity pass first)",
    )
    ap.add_argument("--skip-repair", action="store_true")
    ap.add_argument("--skip-compare", action="store_true")
    return ap.parse_args()


def _clip_path(animation: str, clip_run: str) -> Path:
    return POSE_RUNS / "h3_cavalier" / animation / clip_run / "gpu_clip_result.json"


def _sprite_dir(animation: str) -> Path:
    return POSE_RUNS / "h3_cavalier" / animation / f"frames_def12_nn_{animation}_shadow_culled"


def _compose_compare(*, out_path: Path, sprite_dir: Path, before_rgb: Path, after_rgb: Path, frame_count: int) -> None:
    from compose_method_compare_gif import main as compose_gif_main
    from preview_timing import PREVIEW_GIF_FRAME_MS

    argv = [
        "--out",
        str(out_path),
        "--cols",
        "3",
        "--cell-w",
        "280",
        "--cell-h",
        "320",
        "--hold",
        "2",
        "--duration-ms",
        str(int(PREVIEW_GIF_FRAME_MS)),
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
        "--panel",
        "rescore_baseline",
        str(before_rgb),
        "--panel",
        "after_gated_repair",
        str(after_rgb),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_gif_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError(f"compose compare gif failed for {out_path}")


def main() -> int:
    args = _parse()
    clip_path = _clip_path(args.animation, args.clip_run)
    if not clip_path.is_file():
        raise FileNotFoundError(f"gpu clip missing: {clip_path}")
    out_dir = POSE_RUNS / "h3_cavalier" / args.animation / args.out_run
    compare_dir = COMPARE_OUT / args.animation
    compare_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_repair:
        report = repair_clip_warp(
            clip_path=clip_path,
            mesh_glb=args.mesh_glb,
            output_dir=out_dir,
            groups_catalog_path=args.groups,
            detect_cfg=WarpDetectConfig(),
            parity_cfg=RescoreParityConfig(),
            max_rounds=int(args.max_rounds),
            apply_corrections=bool(args.apply),
        )
        print(json.dumps(report, indent=2))
    else:
        report_path = out_dir / "warp_repair_report.json"
        if not report_path.is_file():
            raise FileNotFoundError(f"warp repair report missing: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))

    if not args.skip_compare and report.get("ok"):
        frame_count = len(report.get("frameIndices") or report.get("baselineRescore", {}).get("frameIndices") or [])
        sprite_dir = _sprite_dir(args.animation)
        before_rgb = out_dir / "baseline_rgb"
        after_rgb = out_dir / "solved_rgb"
        compare_gif = compare_dir / "owned_warp_repair_v2_compare.gif"
        _compose_compare(
            out_path=compare_gif,
            sprite_dir=sprite_dir,
            before_rgb=before_rgb,
            after_rgb=after_rgb,
            frame_count=frame_count,
        )
        print(f"compare gif: {compare_gif}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
