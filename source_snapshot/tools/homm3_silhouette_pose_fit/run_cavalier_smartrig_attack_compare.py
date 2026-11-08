#!/usr/bin/env python3
"""Attack compare: sprite | Meshy Smart Rig | owned bind (optional).

Original animated baseline: ``artifacts/meshy_downloads/h3_cavalier_smartrigged.glb``
(Meshy.ai Smart Rig handoff — not our local UniRig owned-bind rerig) with
``fused_push_v24_pipeline`` poses on ``idle_attack_front``.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
MESHY = ROOT / "artifacts/meshy_downloads"
POSE_RUNS = ROOT / "artifacts/pose_picker_runs"
PIPELINE = ROOT / "artifacts/cavalier_pose_pipeline"
# Meshy.ai Smart Rig download (external Chrome handoff). Not UniRig / not owned bind.
MESHY_SMARTRIG = MESHY / "h3_cavalier_smartrigged.glb"
OWNED_MASTER = PIPELINE / "owned_bind/h3_cavalier_master_yup.glb"
SMARTRIG_CLIP_RUN = "fused_push_v24_pipeline"
OWNED_CLIP_RUN = "owned_fused_push_v1_pipeline"
COMPARE_OUT = PIPELINE / "owned_rig_test"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import load_clip_result, raster_tweak_preview  # noqa: E402
from compose_method_compare_gif import main as compose_gif_main  # noqa: E402
from gpu_raster_depth_animation import RASTER_RUN_CHILDREN, replace_owned_run_artifacts  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from tweak_gpu_clip_poses import _with_cascade_lock  # noqa: E402


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--animation", default="idle_attack_front")
    ap.add_argument(
        "--meshy-smartrig",
        type=Path,
        default=MESHY_SMARTRIG,
        help="Meshy.ai Smart Rig GLB (default: h3_cavalier_smartrigged.glb)",
    )
    ap.add_argument("--include-owned", action="store_true", default=True)
    ap.add_argument("--no-owned", action="store_true", help="Only sprite | Meshy Smart Rig")
    ap.add_argument(
        "--out-name",
        default="meshy_smartrig_vs_owned_attack.gif",
        help="Output GIF filename under owned_rig_test/<animation>/",
    )
    ap.add_argument(
        "--reuse-solved-rgb",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Reuse fused_push solved_rgb when present (default: off — re-raster on Meshy mesh)",
    )
    return ap.parse_args()


def _raster_lane(*, payload: dict[str, Any], mesh: Path, out_dir: Path) -> Path:
    replace_owned_run_artifacts(out_dir, children=RASTER_RUN_CHILDREN)
    report = _with_cascade_lock(
        lambda: raster_tweak_preview(
            payload=payload,
            mesh_glb=mesh,
            output_dir=out_dir,
        )
    )
    return Path(report["rgbDir"])


def _resolved_rgb_dir(*, clip_run: str, animation: str, fallback_out: Path, mesh: Path, payload: dict[str, Any]) -> Path:
    solved = POSE_RUNS / "h3_cavalier" / animation / clip_run / "solved_rgb"
    if solved.is_dir() and any(solved.glob("*.png")):
        return solved
    return _raster_lane(payload=payload, mesh=mesh, out_dir=fallback_out)


def _compose(*, out_path: Path, panels: list[tuple[str, Path]], frame_count: int) -> None:
    argv = [
        "--out",
        str(out_path),
        "--cols",
        str(len(panels)),
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
    ]
    for label, folder in panels:
        argv.extend(["--panel", label, str(folder)])
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_gif_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError(f"GIF compose failed: {out_path}")


def main() -> int:
    args = _parse()
    animation = str(args.animation)
    meshy_smartrig = Path(args.meshy_smartrig).resolve()
    if not meshy_smartrig.is_file():
        raise FileNotFoundError(
            "Meshy Smart Rig GLB missing: "
            f"{meshy_smartrig}. Expected Meshy.ai handoff (h3_cavalier_smartrigged.glb)."
        )

    smartrig_clip = POSE_RUNS / "h3_cavalier" / animation / SMARTRIG_CLIP_RUN / "gpu_clip_result.json"
    if not smartrig_clip.is_file():
        raise FileNotFoundError(f"Meshy smartrig clip missing: {smartrig_clip}")

    sprite_dir = POSE_RUNS / "h3_cavalier" / animation / f"frames_def12_nn_{animation}_shadow_culled"
    if not sprite_dir.is_dir():
        raise FileNotFoundError(f"sprite dir missing: {sprite_dir}")

    smartrig_payload = load_clip_result(smartrig_clip)
    frame_count = len(smartrig_payload.get("frameIndices") or [])
    if frame_count < 1:
        raise ValueError("Meshy smartrig clip has no frames")

    clip_out = COMPARE_OUT / animation
    clip_out.mkdir(parents=True, exist_ok=True)
    if args.reuse_solved_rgb:
        meshy_rgb = _resolved_rgb_dir(
            clip_run=SMARTRIG_CLIP_RUN,
            animation=animation,
            fallback_out=clip_out / "meshy_smartrig_raster",
            mesh=meshy_smartrig,
            payload=smartrig_payload,
        )
    else:
        meshy_rgb = _raster_lane(
            payload=smartrig_payload,
            mesh=meshy_smartrig,
            out_dir=clip_out / "meshy_smartrig_raster",
        )

    panels: list[tuple[str, Path]] = [
        ("sprite", sprite_dir),
        ("meshy_smartrig", meshy_rgb),
    ]
    owned_payload = None
    include_owned = bool(args.include_owned) and not bool(args.no_owned)
    if include_owned:
        owned_clip = POSE_RUNS / "h3_cavalier" / animation / OWNED_CLIP_RUN / "gpu_clip_result.json"
        if not owned_clip.is_file():
            raise FileNotFoundError(f"owned clip missing: {owned_clip}")
        if not OWNED_MASTER.is_file():
            raise FileNotFoundError(f"owned master missing: {OWNED_MASTER}")
        owned_payload = load_clip_result(owned_clip)
        if args.reuse_solved_rgb:
            owned_rgb = _resolved_rgb_dir(
                clip_run=OWNED_CLIP_RUN,
                animation=animation,
                fallback_out=clip_out / "owned_raster",
                mesh=OWNED_MASTER,
                payload=owned_payload,
            )
        else:
            owned_rgb = _raster_lane(
                payload=owned_payload,
                mesh=OWNED_MASTER,
                out_dir=clip_out / "owned_raster",
            )
        panels.append(("owned_bind", owned_rgb))

    gif_path = clip_out / str(args.out_name)
    _compose(out_path=gif_path, panels=panels, frame_count=frame_count)

    summary = {
        "ok": True,
        "compareGif": str(gif_path).replace("\\", "/"),
        "animation": animation,
        "panels": [label for label, _ in panels],
        "frameCount": frame_count,
        "meshySmartRig": str(meshy_smartrig).replace("\\", "/"),
        "meshyClip": str(smartrig_clip).replace("\\", "/"),
        "meshyScore": smartrig_payload.get("score"),
        "ownedScore": owned_payload.get("score") if owned_payload else None,
        "ownedMesh": str(OWNED_MASTER).replace("\\", "/") if include_owned else None,
        "note": (
            "meshy_smartrig is the Meshy.ai Smart Rig GLB handoff. "
            "owned_bind is our local UniRig/owned rerig — not the Meshy baseline."
        ),
        "proof": "generated artifact validated — attack compare gif; not OE runtime proven",
    }
    summary_path = clip_out / f"{Path(args.out_name).stem}.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
