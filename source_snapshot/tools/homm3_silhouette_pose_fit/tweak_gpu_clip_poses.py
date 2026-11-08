#!/usr/bin/env python3
"""Inspect, freeze/rotate, and re-raster GPU clip poses without searching.

This is an agent-facing editor for ``gpu_clip_result.json``. It does not run
the cascade, keep/zero, or physics. Preview is unlit CUDA raster only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    apply_operations,
    build_tweaked_payload,
    inspect_clip,
    load_clip_result,
    load_hierarchy,
    load_operations,
    probe_axis_deltas,
    raster_tweak_preview,
)
from roc_gpu_cascade_experiment import persist_gpu_clip_result  # noqa: E402


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2), flush=True)


def _require_out(path: Path, source_clip: Path) -> Path:
    out = path.resolve()
    if out == source_clip.parent.resolve():
        raise RuntimeError(f"refusing to overwrite the source clip directory: {out}")
    return out


def _cmd_inspect(args: argparse.Namespace) -> int:
    payload = load_clip_result(args.clip)
    hierarchy = load_hierarchy(args.mesh) if args.mesh else None
    report = inspect_clip(payload, hierarchy=hierarchy)
    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_json(report)
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    source = Path(args.clip).resolve()
    payload = load_clip_result(source)
    operations = load_operations(args.ops)
    hierarchy = load_hierarchy(args.mesh) if args.mesh else None
    poses = apply_operations(payload, operations, hierarchy=hierarchy)
    tweaked = build_tweaked_payload(
        payload,
        poses,
        source_clip=source,
        operations=operations,
    )
    out = _require_out(Path(args.out), source)
    out.mkdir(parents=True, exist_ok=True)
    (out / "operations.json").write_text(
        json.dumps({"operations": operations}, indent=2) + "\n",
        encoding="utf-8",
    )
    clip_path = persist_gpu_clip_result(tweaked, out)
    report: dict[str, Any] = {
        "clipResultPath": str(clip_path).replace("\\", "/"),
        "operations": operations,
        "searched": False,
        "proof": "edited poses; not a new solve",
    }
    if args.preview:
        if not args.mesh:
            raise RuntimeError("preview requires --mesh")
        preview = _with_cascade_lock(
            lambda: raster_tweak_preview(
                payload=tweaked,
                mesh_glb=args.mesh,
                output_dir=out,
                frame_indices=args.frames,
            )
        )
        report.update(preview)
    _print_json(report)
    return 0


def _with_cascade_lock(body):
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )

    lock_path = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    try:
        return body()
    finally:
        release_cascade_batch_lock(lock_path)


def _cmd_probe(args: argparse.Namespace) -> int:
    payload = load_clip_result(args.clip)
    joints = [item.strip() for item in str(args.bones).split(",") if item.strip()]
    if not joints:
        raise RuntimeError("probe --bones listed no joints")

    def _run() -> dict[str, Any]:
        return probe_axis_deltas(
            payload=payload,
            mesh_glb=args.mesh,
            frame=int(args.frame),
            joints=joints,
            delta_deg=float(args.delta_deg),
            translate_delta=float(args.translate_delta),
        )

    report = _with_cascade_lock(_run)
    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_json(report)
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    source = Path(args.clip).resolve()
    payload = load_clip_result(source)
    out = _require_out(Path(args.out), source)
    report = _with_cascade_lock(
        lambda: raster_tweak_preview(
            payload=payload,
            mesh_glb=args.mesh,
            output_dir=out,
            frame_indices=args.frames,
        )
    )
    _print_json(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="List joints and which frames they travel")
    inspect_p.add_argument("--clip", type=Path, required=True)
    inspect_p.add_argument("--mesh", type=Path, help="GLB for parent/child names")
    inspect_p.add_argument("--out", type=Path, help="Optional inspect JSON path")

    apply_p = sub.add_parser("apply", help="Write edited poses; optional unlit preview")
    apply_p.add_argument("--clip", type=Path, required=True)
    apply_p.add_argument("--ops", type=Path, required=True)
    apply_p.add_argument("--out", type=Path, required=True)
    apply_p.add_argument("--mesh", type=Path, help="Required for include_descendants or --preview")
    apply_p.add_argument("--preview", action="store_true")
    apply_p.add_argument("--frames", help="Preview subset, e.g. 0-7 (default all)")

    preview_p = sub.add_parser("preview", help="Unlit raster of existing poses; no search")
    preview_p.add_argument("--clip", type=Path, required=True)
    preview_p.add_argument("--mesh", type=Path, required=True)
    preview_p.add_argument("--out", type=Path, required=True)
    preview_p.add_argument("--frames", help="Preview subset, e.g. 8-12 (default all)")

    probe_p = sub.add_parser(
        "probe",
        help="One-frame ±axis occupancy IoU table; no search",
    )
    probe_p.add_argument("--clip", type=Path, required=True)
    probe_p.add_argument("--mesh", type=Path, required=True)
    probe_p.add_argument("--frame", type=int, required=True)
    probe_p.add_argument(
        "--bones",
        required=True,
        help="Comma-separated joints, including root_rotation / root_translation",
    )
    probe_p.add_argument("--delta-deg", type=float, default=20.0)
    probe_p.add_argument("--translate-delta", type=float, default=0.08)
    probe_p.add_argument("--out", type=Path, help="Optional JSON path")

    args = parser.parse_args()
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "apply":
        return _cmd_apply(args)
    if args.command == "preview":
        return _cmd_preview(args)
    if args.command == "probe":
        return _cmd_probe(args)
    raise RuntimeError(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
