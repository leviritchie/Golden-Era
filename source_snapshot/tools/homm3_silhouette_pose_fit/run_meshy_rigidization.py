#!/usr/bin/env python3
"""Host-side launcher for the Meshy-preserving rigidization Blender pass."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pose_fit_blender import resolve_pose_fit_blender

ROOT = Path(__file__).resolve().parents[2]
BLENDER_SCRIPT = Path(__file__).with_name("rigidize_meshy_skin.py")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-ambiguous", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse()
    blender = resolve_pose_fit_blender(args.blender)
    src = _resolve(args.src).resolve()
    out = _resolve(args.out).resolve()
    report = _resolve(args.report).resolve()
    if not blender.is_file():
        raise FileNotFoundError(f"Blender executable not found: {blender}")
    if not src.is_file():
        raise FileNotFoundError(f"Meshy GLB not found: {src}")
    command = [
        str(blender),
        "-b",
        "--python",
        str(BLENDER_SCRIPT),
        "--",
        "--src",
        str(src),
        "--out",
        str(out),
        "--report",
        str(report),
    ]
    if args.config:
        command.extend(["--config", str(_resolve(args.config).resolve())])
    if args.overwrite:
        command.append("--overwrite")
    if args.allow_ambiguous:
        command.append("--allow-ambiguous")
    if args.dry_run:
        command.append("--dry-run")
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        return int(completed.returncode)
    if not report.is_file():
        raise RuntimeError(f"rigidization did not write its report: {report}")
    payload = json.loads(report.read_text(encoding="utf-8"))
    if payload.get("status") not in {"pass", "dry_run"}:
        raise RuntimeError(f"rigidization report is not accepted: {payload.get('status')!r}")
    if not args.dry_run and not out.is_file():
        raise RuntimeError(f"rigidization report passed but output is missing: {out}")
    print(json.dumps({"ok": True, "status": payload["status"], "output": str(out), "report": str(report)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        raise SystemExit(2)
