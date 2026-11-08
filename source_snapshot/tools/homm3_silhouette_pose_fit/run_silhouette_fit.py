#!/usr/bin/env python3
"""Host launcher for silhouette-IoU fit: prepare targets → Blender fit → preview."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_PY = Path(r"V:/Games/Olden Era Playtest Tweak/tools/.venvs/homm3_dwpose/Scripts/python.exe")


def _load_job(path: Path) -> dict:
    job = json.loads(path.read_text(encoding="utf-8"))

    def resolve(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp)
        return str((ROOT / pp).resolve())

    job["masterGlb"] = resolve(job["masterGlb"])
    job["outputDir"] = resolve(job["outputDir"])
    for fr in job["frames"]:
        fr["path"] = resolve(fr["path"])
    return job


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--blender", type=Path, default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))))
    ap.add_argument("--python", type=Path, default=DEFAULT_PY)
    ap.add_argument("--skip-targets", action="store_true")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-preview", action="store_true")
    ap.add_argument("--force-targets", action="store_true")
    args = ap.parse_args()

    raw = args.config if args.config.is_file() else (ROOT / args.config)
    if not raw.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2

    job = _load_job(raw)
    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "job.resolved.json"
    resolved.write_text(json.dumps(job, indent=2), encoding="utf-8")

    py = args.python
    if not py.is_file():
        py = Path(sys.executable)

    if not args.skip_targets:
        cmd = [str(py), str(TOOL / "prepare_targets.py"), "--config", str(resolved), "--force"]
        # --force always for silhouette re-runs when shadow policy changes
        if not args.force_targets:
            # still force when cull flag is on so stale shadowed targets cannot linger
            if bool(job.get("cullDefSoftShadows", False)):
                pass  # already forcing
        print("Running:", " ".join(cmd), flush=True)
        rc = subprocess.run(cmd, cwd=str(TOOL)).returncode
        if rc != 0:
            print("prepare_targets failed (fail-closed).", file=sys.stderr)
            return rc

    if not args.skip_fit:
        if not args.blender.is_file():
            print(f"Blender missing: {args.blender}", file=sys.stderr)
            return 2
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "blender_fit_clip.py"),
            "--",
            "--job",
            str(resolved),
        ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            if "pose-fit" in line or '"ok"' in line or "Error" in line or "Traceback" in line:
                print(line, flush=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-8000:] if proc.stderr else "")
            return proc.returncode

    report = out_dir / "fit_report.json"
    if not args.skip_preview:
        if not report.is_file():
            print(f"missing fit report for preview: {report}", file=sys.stderr)
            return 2
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "render_preview.py"),
            "--",
            "--job",
            str(resolved),
            "--report",
            str(report),
            "--hold",
            "5",
        ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            if "preview" in line or '"ok"' in line or "Error" in line:
                print(line, flush=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-4000:] if proc.stderr else "")
            return proc.returncode

    print(json.dumps({"ok": True, "outputDir": str(out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
