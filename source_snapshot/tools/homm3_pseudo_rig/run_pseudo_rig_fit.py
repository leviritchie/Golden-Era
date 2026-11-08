#!/usr/bin/env python3
"""Host launcher: prepare silhouette targets → Blender pseudo-rig multi-pose fit → bake."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
SILHOUETTE = TOOL.parent / "homm3_silhouette_pose_fit"
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_CONFIG = TOOL / "configs/h3_crusader_combat_core_pseudo_rig.json"
DEFAULT_CONFIG_V1 = TOOL / "configs/h3_crusader_combat_core_pseudo_rig_v1.json"


def _load_job(path: Path) -> dict:
    job = json.loads(path.read_text(encoding="utf-8"))

    def resolve(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp)
        return str((ROOT / pp).resolve())

    job["masterGlb"] = resolve(job["masterGlb"])
    job["outputDir"] = resolve(job["outputDir"])
    if job.get("exportDir"):
        job["exportDir"] = resolve(job["exportDir"])
    if job.get("handleCatalog"):
        job["handleCatalog"] = resolve(job["handleCatalog"])
    for fr in job["frames"]:
        fr["path"] = resolve(fr["path"])
    return job


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument(
        "--v1",
        action="store_true",
        help="Use v1 config (clip-shared framing + edge/DT losses).",
    )
    ap.add_argument(
        "--blender",
        type=Path,
        default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))),
    )
    ap.add_argument("--python", type=Path, default=Path(sys.executable))
    ap.add_argument("--skip-targets", action="store_true")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--force-targets", action="store_true")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="Fail-closed wiring smoke: optimizer.method=smoke (rest pose only).",
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="Reduced Nelder iters for a quicker full-pipeline pass.",
    )
    ap.add_argument(
        "--clips",
        type=str,
        default="",
        help="Comma-separated clipId filter (e.g. death_g5,move_g0).",
    )
    args = ap.parse_args()

    if args.config is None:
        args.config = DEFAULT_CONFIG_V1 if args.v1 else DEFAULT_CONFIG
    raw = args.config if args.config.is_file() else (ROOT / args.config)
    if not raw.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2

    job = _load_job(raw)
    # Auto-detect v1 from config fields.
    is_v1 = args.v1 or str(job.get("targetVersion", "")).lower() in {"v1", "edge", "clip_shared"}
    if args.clips.strip():
        want = {c.strip() for c in args.clips.split(",") if c.strip()}
        job["frames"] = [f for f in job["frames"] if str(f.get("clipId")) in want]
        job["clips"] = [c for c in job.get("clips") or [] if str(c.get("clipId")) in want]
        if not job["frames"]:
            print(f"no frames left after --clips {want}", file=sys.stderr)
            return 2
        tag = "_".join(sorted(want))
        suffix = f"out_fit_v1_{tag}" if is_v1 else f"out_fit_{tag}"
        exp = f"export_v1_{tag}" if is_v1 else f"export_{tag}"
        out = Path(job["outputDir"]).parent / suffix
        job["outputDir"] = str(out)
        job["exportDir"] = str(out.parent / exp)
        args.force_targets = True
    if args.smoke:
        job.setdefault("optimizer", {})
        job["optimizer"]["method"] = "smoke"
        job["optimizer"]["stageBPasses"] = 0
    elif args.fast:
        job.setdefault("optimizer", {})
        job["optimizer"]["method"] = "nelder"
        job["optimizer"]["blockSize"] = 4
        job["optimizer"]["randomProbesPerBlock"] = 10
        job["optimizer"]["simplexBoundFrac"] = 0.40
        job["optimizer"]["polishIters"] = 64
        job["optimizer"]["stageBPasses"] = 1
        job["optimizer"]["stageBPolishIters"] = 32

    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "job.resolved.json"
    resolved.write_text(json.dumps(job, indent=2), encoding="utf-8")

    py = args.python if args.python.is_file() else Path(sys.executable)

    if not args.skip_targets:
        if is_v1:
            cmd = [
                str(py),
                str(TOOL / "prepare_targets_v1.py"),
                "--config",
                str(resolved),
            ]
        else:
            cmd = [
                str(py),
                str(SILHOUETTE / "prepare_targets.py"),
                "--config",
                str(resolved),
            ]
        if args.force_targets or bool(job.get("cullDefSoftShadows", False)):
            cmd.append("--force")
        print("Running:", " ".join(cmd), flush=True)
        cwd = str(TOOL if is_v1 else SILHOUETTE)
        rc = subprocess.run(cmd, cwd=cwd).returncode
        if rc != 0:
            print("prepare_targets failed (fail-closed).", file=sys.stderr)
            return rc

    if not args.skip_fit:
        master = Path(job["masterGlb"])
        if not master.is_file():
            print(f"master GLB missing: {master}", file=sys.stderr)
            return 2
        if not args.blender.is_file():
            print(f"Blender missing: {args.blender}", file=sys.stderr)
            return 2
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "blender_pseudo_rig_fit.py"),
            "--",
            "--job",
            str(resolved),
        ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT))
        if proc.returncode != 0:
            return int(proc.returncode)

    report = out_dir / "fit_report.json"
    if not report.is_file():
        print(f"missing fit report: {report}", file=sys.stderr)
        return 2
    print(f"fit report: {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
