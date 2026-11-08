#!/usr/bin/env python3
"""Host launcher: pose infer → constrained keypoint fit → preview render.

Pose sources:
  - sprite_landmarks (default for HoMM3 pixel art after DWPose fail-closed)
  - dwpose (neural; often topology-wrong on this art)
"""
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
DEFAULT_DWPOSE_PY = Path(r"V:/Games/Olden Era Playtest Tweak/tools/.venvs/homm3_dwpose/Scripts/python.exe")
DEFAULT_ROLES = TOOL / "bone_roles_unirig_hobgoblin.json"
DEFAULT_DET = TOOL / "models" / "dwpose" / "yolox_l.onnx"
DEFAULT_POSE = TOOL / "models" / "dwpose" / "dw-ll_ucoco_384.onnx"


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
    if "boneRoles" in job:
        job["boneRoles"] = resolve(job["boneRoles"])
    return job


def _run_blender(cmd: list[str], tag: str, *, require_ok_line: bool) -> int:
    """Run a Blender script and fail closed on a Python error.

    Blender exits 0 after an uncaught script exception, so the return code alone
    lets a crashed fit leave its previous ``fit_report.json`` in place while the
    preview happily renders those stale poses. The script's own ``{"ok": ...}``
    line is the sentinel that it reached the end.
    """
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    for line in stdout.splitlines():
        if tag in line or '"ok"' in line or "Error" in line or "Traceback" in line:
            print(line, flush=True)
    if proc.returncode != 0:
        sys.stderr.write(stderr[-8000:])
        return proc.returncode
    if "Traceback" in stdout or "Traceback" in stderr:
        sys.stderr.write((stdout + stderr)[-8000:])
        print(f"{tag}: script raised (Blender still exits 0); failing closed.", file=sys.stderr)
        return 1
    if require_ok_line:
        ok_line = [
            line for line in stdout.splitlines() if line.strip().startswith("{") and '"ok"' in line
        ]
        if not ok_line:
            sys.stderr.write(stderr[-8000:])
            print(
                f"{tag}: no machine-readable {{\"ok\": ...}} line from the script; "
                "failing closed instead of reusing whatever report is on disk.",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--blender", type=Path, default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))))
    ap.add_argument("--dwpose-python", type=Path, default=DEFAULT_DWPOSE_PY)
    ap.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    ap.add_argument(
        "--pose-source",
        choices=["sprite_landmarks", "dwpose"],
        default=None,
        help="Override job.method pose authority (default: job.method / sprite_landmarks)",
    )
    ap.add_argument("--skip-infer", action="store_true")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-preview", action="store_true")
    ap.add_argument(
        "--skip-absolute-refine",
        action="store_true",
        help="Skip absolute chroma refine stage after joint warm-start.",
    )
    ap.add_argument(
        "--skip-absolute-match",
        action="store_true",
        help="Skip absolute chroma/pixel success gate (visual-match contract).",
    )
    ap.add_argument("--smoke-camera", action="store_true", help="Legacy silhouette smoke (retired)")
    args = ap.parse_args()

    raw = args.config if args.config.is_file() else (ROOT / args.config)
    if not raw.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2

    job = _load_job(raw)
    pose_source = args.pose_source
    if pose_source is None:
        method = str(job.get("method") or "sprite_landmarks")
        if "dwpose" in method:
            pose_source = "dwpose"
        else:
            pose_source = "sprite_landmarks"
    job["poseSource"] = pose_source
    job["method"] = (
        "sprite_landmarks_reprojection" if pose_source == "sprite_landmarks" else "dwpose_reprojection"
    )
    job.setdefault(
        "dwpose",
        {
            "longEdges": [1024, 1280],
            "backgrounds": [[0, 0, 0], [48, 48, 48], [180, 180, 180]],
            "minMeanBodyScore": 0.18,
            "minVisibleJoints": 6,
            "scoreThr": 0.22,
        },
    )
    job.setdefault(
        "keypointOptimizer",
        {"boundRad": 0.61, "restWeight": 0.4, "maxiter": 140, "maxfev": 450},
    )
    if "boneRoles" not in job:
        job["boneRoles"] = str(args.roles.resolve())

    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "job.resolved.json"
    resolved.write_text(json.dumps(job, indent=2), encoding="utf-8")

    roles_path = Path(job["boneRoles"])
    roles_doc = json.loads(roles_path.read_text(encoding="utf-8")) if roles_path.is_file() else {}
    rig_family = str(roles_doc.get("rigFamily") or "")
    is_mount_rig = rig_family == "owned_rider_mount"
    is_flyer_rig = rig_family == "owned_flyer"

    if args.smoke_camera:
        print("NOTE: --smoke-camera is silhouette-era; ignored.", flush=True)

    if pose_source == "sprite_landmarks":
        keypoints = out_dir / "sprite_landmarks" / "keypoints.json"
        if not args.skip_infer:
            if not args.dwpose_python.is_file():
                print(f"python missing: {args.dwpose_python}", file=sys.stderr)
                return 2
            infer_script = (
                TOOL / "sprite_landmarks_infer_mount.py"
                if is_mount_rig
                else TOOL / "sprite_landmarks_infer.py"
            )
            cmd = [
                str(args.dwpose_python),
                str(infer_script),
                "--config",
                str(resolved),
            ]
            print("Running:", " ".join(cmd), flush=True)
            rc = subprocess.run(cmd, cwd=str(TOOL)).returncode
            if rc != 0:
                print("sprite landmark infer failed (fail-closed).", file=sys.stderr)
                return rc
    else:
        keypoints = out_dir / "dwpose" / "keypoints.json"
        if not args.skip_infer:
            if not args.dwpose_python.is_file():
                print(f"DWPose python missing: {args.dwpose_python}", file=sys.stderr)
                return 2
            cmd = [
                str(args.dwpose_python),
                str(TOOL / "dwpose_infer.py"),
                "--config",
                str(resolved),
                "--det",
                str(DEFAULT_DET),
                "--pose",
                str(DEFAULT_POSE),
            ]
            print("Running:", " ".join(cmd), flush=True)
            rc = subprocess.run(cmd, cwd=str(TOOL)).returncode
            if rc != 0:
                print("DWPose infer failed (fail-closed). See dwpose overlays.", file=sys.stderr)
                return rc
    if not keypoints.is_file():
        print(f"missing keypoints: {keypoints}", file=sys.stderr)
        return 2

    if is_flyer_rig:
        # Authored marks are the pose *targets*; a mark that sits off the creature
        # produces a pose error the fit's own metric cannot see (it scores against
        # the same marks). Auditing here makes that visible in every fit artifact.
        audit_cmd = [
            sys.executable,
            str(TOOL / "validate_flyer_sprite_landmarks_contract.py"),
            "--keypoints",
            str(keypoints),
            "--roles",
            str(Path(job["boneRoles"])),
            "--out",
            str(out_dir / "landmark_audit.json"),
            "--report-only",
        ]
        audit_path = out_dir / "landmark_audit.json"
        proc = subprocess.run(audit_cmd, cwd=str(ROOT), capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            if "landmark-contract" in line or "off-sprite" in line:
                print(line, flush=True)

    roles = Path(job["boneRoles"])
    if not args.skip_fit:
        if not args.blender.is_file():
            print(f"Blender missing: {args.blender}", file=sys.stderr)
            return 2
        solver = str(job.get("poseSolver") or "keypoint_reprojection")
        if solver == "ground_truth_joints":
            fit_script = TOOL / "blender_ground_truth_joints.py"
            tag = "gt-joints"
        elif solver == "fixed_length_ik":
            if is_mount_rig:
                fit_script = TOOL / "blender_fixed_length_ik_mount.py"
                tag = "fixed-ik-mount"
            elif is_flyer_rig:
                fit_script = TOOL / "blender_fixed_length_ik_flyer.py"
                tag = "fixed-ik-flyer"
            else:
                fit_script = TOOL / "blender_fixed_length_ik.py"
                tag = "fixed-ik"
        elif solver == "marker_ik":
            fit_script = TOOL / "blender_ik_markers.py"
            tag = "marker-ik"
        else:
            fit_script = TOOL / "blender_fit_from_keypoints.py"
            tag = "kpt-fit"
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(fit_script),
            "--",
            "--job",
            str(resolved),
            "--keypoints",
            str(keypoints),
            "--roles",
            str(roles),
        ]
        print("Running:", " ".join(cmd), flush=True)
        rc = _run_blender(cmd, tag, require_ok_line=solver == "fixed_length_ik")
        if rc != 0:
            return rc

    report = out_dir / "fit_report.json"

    if is_flyer_rig and report.is_file() and audit_path.is_file():
        # Carry the authoring audit inside the authoritative report. The fit's own
        # error metric scores against these same marks, so it cannot see an off-sprite
        # target; consumers must read ``landmarkAudit`` to see that debt.
        rep = json.loads(report.read_text(encoding="utf-8"))
        aud = json.loads(audit_path.read_text(encoding="utf-8"))
        rep["landmarkAudit"] = {
            "ok": bool(aud.get("ok")),
            "maxOffSpritePx": aud.get("maxOffSpritePx"),
            "maxOffSpritePxAllowed": aud.get("maxOffSpritePxAllowed"),
            "offSpriteMarks": aud.get("offSpriteMarks", []),
            "report": str(audit_path).replace("\\", "/"),
        }
        report.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    # Fine stage: refine joint warm-start against absolute chroma/pixel loss.
    if (job.get("absoluteRefine") or {}).get("enabled", False) and not args.skip_absolute_refine:
        if not report.is_file():
            print(f"missing fit report for absolute refine: {report}", file=sys.stderr)
            return 2
        if not args.blender.is_file():
            print(f"Blender missing: {args.blender}", file=sys.stderr)
            return 2
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "blender_refine_absolute_chroma.py"),
            "--",
            "--job",
            str(resolved),
            "--report",
            str(report),
        ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            if "abs-refine" in line or '"ok"' in line or "Error" in line or "Traceback" in line:
                print(line, flush=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-8000:] if proc.stderr else "")
            print("absolute chroma refine failed (fail-closed).", file=sys.stderr)
            return proc.returncode

    # Absolute chroma/pixel match is the visual-match success authority (same camera, sprite grid).
    if (job.get("absoluteMatch") or {}) and not args.skip_absolute_match:
        if not report.is_file():
            print(f"missing fit report for absolute match: {report}", file=sys.stderr)
            return 2
        if not args.blender.is_file():
            print(f"Blender missing: {args.blender}", file=sys.stderr)
            return 2
        cmd = [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "render_absolute_match_frames.py"),
            "--",
            "--job",
            str(resolved),
            "--report",
            str(report),
        ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            if "abs-match" in line or '"ok"' in line or "Error" in line or "fail-closed" in line:
                print(line, flush=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-8000:] if proc.stderr else "")
            print(
                "absolute chroma/pixel match failed (fail-closed). "
                "Joints are only a pose tool — this gate is the success metric.",
                file=sys.stderr,
            )
            return proc.returncode

    if not args.skip_preview:
        if not report.is_file():
            print(f"missing fit report for preview: {report}", file=sys.stderr)
            return 2
        solver = str(job.get("poseSolver") or "keypoint_reprojection")
        if solver == "fixed_length_ik":
            if is_mount_rig:
                preview_script = TOOL / "render_fixed_length_preview_mount.py"
            elif is_flyer_rig:
                preview_script = TOOL / "render_fixed_length_preview_flyer.py"
            else:
                preview_script = TOOL / "render_fixed_length_preview.py"
            cmd = [
                str(args.blender),
                "--background",
                "--python",
                str(preview_script),
                "--",
                "--fit-dir",
                str(out_dir),
            ]
        elif solver == "ground_truth_joints":
            cmd = [
                str(args.blender),
                "--background",
                "--python",
                str(TOOL / "render_ground_truth_preview.py"),
                "--",
                "--fit-dir",
                str(out_dir),
            ]
        else:
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
        rc = _run_blender(cmd, "preview", require_ok_line=solver == "fixed_length_ik")
        if rc != 0:
            return rc

        # Slow mp4 via ffmpeg if available (marker-IK side-by-side frames only)
        preview_dir = out_dir / "preview"
        frames = preview_dir / "frames"
        ffmpeg = Path(
            os.environ.get(
                "FFMPEG",
                r"C:/Users/<user>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.2-full_build/bin/ffmpeg.exe",
            )
        )
        if (
            solver not in {"fixed_length_ik", "ground_truth_joints"}
            and ffmpeg.is_file()
            and frames.is_dir()
        ):
            slow = preview_dir / "attack_g11_side_by_side_slow.mp4"
            subprocess.run(
                [
                    str(ffmpeg),
                    "-y",
                    "-framerate",
                    "2",
                    "-i",
                    str(frames / "side_%02d.png"),
                    "-vf",
                    "fps=2,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    str(slow),
                ],
                check=False,
            )
            print(f"preview: {slow}", flush=True)

    print(json.dumps({"ok": True, "outputDir": str(out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
