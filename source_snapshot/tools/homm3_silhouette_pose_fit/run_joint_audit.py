#!/usr/bin/env python3
"""Host wrapper: run bind-pose multi-angle joint audit in Blender (fail-closed).

  py -3 tools/homm3_silhouette_pose_fit/run_joint_audit.py
  py -3 tools/homm3_silhouette_pose_fit/run_joint_audit.py \\
    --master <glb> --roles <json> --out <dir> [--sprite <png>]

Exit non-zero if joint_audit_report.json reports issues (duplicate landmarks,
collapsed LWrist/LElbow, missing bones, etc.).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
TOOL = Path(__file__).resolve().parent
SCRIPT = TOOL / "render_crusader_joint_audit.py"
DEFAULT_MASTER = (
    ROOT
    / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged"
    / "idle_f0_rigged_meshy6_bridgefix_hand.glb"
)
DEFAULT_ROLES = TOOL / "bone_roles_crusader_meshy_t2.json"
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/joint_audit_bind"
DEFAULT_SPRITE = (
    ROOT
    / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale_idle_attack/frame_00.png"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Bind-pose multi-angle joint audit")
    ap.add_argument("--blender", type=Path, default=BLENDER)
    ap.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    ap.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--sprite", type=Path, default=DEFAULT_SPRITE)
    args = ap.parse_args()

    blender = args.blender.resolve()
    if not blender.is_file():
        raise SystemExit(f"Blender missing: {blender}")
    if not SCRIPT.is_file():
        raise SystemExit(f"audit script missing: {SCRIPT}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(blender),
        "-b",
        "--python",
        str(SCRIPT),
        "--",
        "--master",
        str(args.master.resolve()),
        "--roles",
        str(args.roles.resolve()),
        "--out",
        str(out),
    ]
    if args.sprite is not None:
        cmd.extend(["--sprite", str(args.sprite.resolve())])

    print(f"[joint-audit] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    report_path = out / "joint_audit_report.json"
    if not report_path.is_file():
        raise SystemExit(f"joint audit produced no report at {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    issues = report.get("issues") or []
    ok = bool(report.get("ok")) and proc.returncode == 0 and not issues
    summary = {
        "ok": ok,
        "blenderExit": proc.returncode,
        "issues": issues,
        "out": str(out).replace("\\", "/"),
        "contactSheet": str((out / "joints_contact_sheet.png")).replace("\\", "/"),
        "report": str(report_path).replace("\\", "/"),
        "proof": "generated — bind joint audit preflight; not OE runtime",
    }
    print(json.dumps(summary, indent=2))
    (out / "joint_audit_host_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
