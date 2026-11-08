#!/usr/bin/env python3
"""Batch fixed-length IK fits for crusader DEF groups from staged keypoints.

Expects each source fit dir already has LLM-authored
``sprite_landmarks/keypoints.json`` (method like ``human_eye_landmark_authoring``).
Track-only keypoints mean the pose pipeline has not run for that clip — do not
batch them and call the unit complete. See ``.cursor/skills/homm3-pose-pipeline``.

  py -3 tools/homm3_silhouette_pose_fit/batch_fixed_length_crusader.py \\
    --groups 1 3 4 5 7 8 11 13 20 21 --workers 1

Playback / lit use ``preview_timing.PREVIEW_GIF_FRAME_MS`` (180ms), not job fps.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
ART = ROOT / "artifacts/crusader_pose_pipeline"
# Delivery batches must run on the owned rigid master, never the historical
# Meshy/Mixamo transition rig. Override these explicitly for diagnostic work.
MASTER = ART / "owned_bind/crusader_master_rigid_components.glb"
ROLES = TOOL / "bone_roles_crusader_owned.json"
OWNERSHIP_RULES = ROOT / "tools/homm3_meshy_frame_pose/ownership_rules_h3_crusader.json"
BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")

GROUP_META = {
    0: ("move", "g00_move"),
    1: ("mouseover", "g01_mouseover"),
    3: ("hitted", "g03_hitted"),
    4: ("defence", "g04_defence"),
    5: ("death", "g05_death"),
    7: ("turn_left", "g07_turn_left"),
    8: ("turn_right", "g08_turn_right"),
    9: ("unused_a", "g09_unused_a"),
    10: ("unused_b", "g10_unused_b"),
    11: ("attack_up", "g11_attack_up"),
    12: ("attack_front", "idle_attack_front"),
    13: ("attack_down", "g13_attack_down"),
    20: ("move_start", "g20_move_start"),
    21: ("move_end", "g21_move_end"),
}

# Death lies down — plant fights the fall. Walk-like / upright clips use Z plant.
PLANT_OFF_GROUPS = {5}


def _py() -> list[str]:
    return [sys.executable]


def _frame_paths_from_keypoints(kpt: dict) -> list[Path]:
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    out: list[Path] = []
    for fr in frames:
        # Prefer path on frame; else reconstruct from transform source name.
        p = fr.get("path") or fr.get("spritePath")
        if p:
            out.append(Path(p))
            continue
        # Many keypoints store only transform; job frames list is authoritative.
        raise RuntimeError("keypoints frame missing path; supply --frames-dir")
    return out


def _build_config(
    *,
    gid: int,
    name: str,
    src_fit: Path,
    out_fit: Path,
    frame_paths: list[Path],
) -> Path:
    out_fit.mkdir(parents=True, exist_ok=True)
    lm = out_fit / "sprite_landmarks"
    lm.mkdir(parents=True, exist_ok=True)
    src_kpt = src_fit / "sprite_landmarks" / "keypoints.json"
    if not src_kpt.is_file():
        raise FileNotFoundError(src_kpt)
    src_doc = json.loads(src_kpt.read_text(encoding="utf-8"))
    method = str(src_doc.get("method") or "")
    if "human_eye_landmark_authoring" not in method:
        raise RuntimeError(
            f"{src_kpt}: refuse non-authored keypoints (method={method!r}). "
            "LLM sprite authorship is a hard pipeline gate."
        )
    # Authored sticks should already be complete; still run gap repair fail-closed.
    repaired = lm / "keypoints_gap_repaired.json"
    rr = subprocess.run(
        [
            *_py(),
            str(TOOL / "repair_keypoint_gaps.py"),
            "--keypoints",
            str(src_kpt),
            "--out",
            str(repaired),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if rr.returncode != 0:
        raise RuntimeError(
            f"gap repair failed for authored keypoints {src_kpt} (rc={rr.returncode}): "
            f"{rr.stderr or rr.stdout}"
        )
    shutil.copy2(repaired, lm / "keypoints.json")
    (lm / "gap_repair_stdout.json").write_text(rr.stdout or "{}", encoding="utf-8")

    kpt = json.loads((lm / "keypoints.json").read_text(encoding="utf-8"))
    if frame_paths:
        frames = [{"path": str(p).replace("\\", "/")} for p in frame_paths]
    else:
        frames = []
        for fr in sorted(kpt["frames"], key=lambda f: int(f["frameIndex"])):
            p = fr.get("path") or fr.get("spritePath")
            if not p:
                raise RuntimeError(f"authored frame {fr.get('frameIndex')} missing path")
            frames.append({"path": str(p).replace("\\", "/")})

    cam = {
        "axis": "iso",
        "isoAzimuthDeg": 40.0,
        "isoElevationDeg": 30.0,
        "distance": 3.0,
        "orthoScale": 4.2,
        "rootYawDeg": 0.0,
    }
    job_src = src_fit / "job.resolved.json"
    if job_src.is_file():
        prev = json.loads(job_src.read_text(encoding="utf-8"))
        cam = prev.get("camera") or cam

    fl_ik: dict = {"frame0CameraRegister": True}
    if gid in PLANT_OFF_GROUPS:
        fl_ik["groundAnchor"] = {"mode": "off"}
    else:
        fl_ik["groundAnchor"] = {
            "mode": "lowest_foot",
            "bones": ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"],
        }

    clip_id = f"{name}_g{gid}_fixed_length" if gid != 12 else "attack_front_g12_fixed_length"
    cfg = {
        "unitSid": "h3_crusader",
        "clipId": clip_id,
        "fps": 12,
        "masterGlb": str(MASTER).replace("\\", "/"),
        "outputDir": str(out_fit).replace("\\", "/"),
        "boneRoles": str(ROLES).replace("\\", "/"),
        "ownershipRules": str(OWNERSHIP_RULES).replace("\\", "/"),
        "cullDefSoftShadows": True,
        "camera": cam,
        "frames": frames,
        "method_kind": "keypoints",
        "method": "sprite_landmarks_reprojection",
        "poseSource": "sprite_landmarks",
        "poseSolver": "fixed_length_ik",
        "fixedLengthIk": fl_ik,
        "absoluteRefine": {"enabled": False},
        "absoluteMatch": {
            "paletteNormalize": True,
            "alphaThr": 8.0,
            "failClosedMaxChromaMae": 18.0,
            "failClosedMaxRgbMae": 45.0,
        },
        "notes": (
            "Fixed-length rotate-only IK toward LLM-authored sprite landmarks. "
            f"groundAnchor={fl_ik['groundAnchor']['mode']}. "
            "Proof: generated-artifact; not OE runtime."
        ),
    }
    cfg_path = TOOL / "configs" / f"h3_crusader_{name}_g{gid}_fixed_length_ik.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def _run_group(gid: int, lit: bool) -> dict:
    name, src_name = GROUP_META[gid]
    authored = ART / "out_fit" / f"{src_name}_authored"
    # Delivery runs are authored-only. Legacy fit directories remain available
    # for diagnostics, but must never be selected silently for shipping work.
    src_fit = authored

    out_fit = ART / "out_fit" / f"g{gid:02d}_{name}_fixed_length"
    if gid == 12:
        out_fit = ART / "out_fit" / "g12_attack_front_rigid_components_fixed_length"

    kpt_path = src_fit / "sprite_landmarks" / "keypoints.json"
    if not kpt_path.is_file():
        return {"group": gid, "ok": False, "error": f"missing authored keypoints: {kpt_path}"}

    cfg = _build_config(
        gid=gid,
        name=name,
        src_fit=src_fit,
        out_fit=out_fit,
        frame_paths=[],
    )
    log = out_fit / "fixed_length_fit.log"
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(
            [
                *_py(),
                str(TOOL / "run_fit.py"),
                "--config",
                str(cfg),
                "--skip-infer",
                "--skip-absolute-match",
                "--skip-preview",
            ],
            cwd=str(ROOT),
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode
    if rc != 0:
        return {
            "group": gid,
            "ok": False,
            "error": f"fit rc={rc}",
            "log": str(log).replace("\\", "/"),
            "src": str(src_fit).replace("\\", "/"),
        }

    # Stick preview
    prev_log = out_fit / "fixed_length_preview.log"
    with prev_log.open("w", encoding="utf-8") as fh:
        prc = subprocess.run(
            [
                str(BLENDER),
                "-b",
                "--python",
                str(TOOL / "render_fixed_length_preview.py"),
                "--",
                "--fit-dir",
                str(out_fit),
            ],
            cwd=str(ROOT),
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode

    result = {
        "group": gid,
        "ok": True,
        "out": str(out_fit).replace("\\", "/"),
        "src": str(src_fit).replace("\\", "/"),
        "previewRc": prc,
    }

    if lit:
        lit_log = out_fit / "fixed_length_lit.log"
        with lit_log.open("w", encoding="utf-8") as fh:
            lrc = subprocess.run(
                [
                    str(BLENDER),
                    "-b",
                    "--python",
                    str(TOOL / "render_fixed_length_lit_60fps.py"),
                    "--",
                    "--fit-dir",
                    str(out_fit),
                    "--out-fps",
                    "60",
                    "--preview-loops",
                    "6",
                    "--gif-frame-ms",
                    "180",
                ],
                cwd=str(ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
            ).returncode
        result["litRc"] = lrc

    # Attach fit metrics when present.
    report = out_fit / "fit_report.json"
    if report.is_file():
        rep = json.loads(report.read_text(encoding="utf-8"))
        result["meanNoseErrorPx"] = rep.get("meanNoseErrorPx")
        result["meanTipErrorPx"] = rep.get("meanTipErrorPx")
        result["meanBodyLossPx"] = rep.get("meanBodyLossPx")
    return result


def main() -> int:
    global MASTER, ROLES
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--groups", type=int, nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--lit", action="store_true", help="Also render GIF-timed lit preview")
    ap.add_argument("--master", type=Path, default=MASTER)
    ap.add_argument("--roles", type=Path, default=ROLES)
    args = ap.parse_args()

    MASTER = args.master.resolve()
    ROLES = args.roles.resolve()
    if not MASTER.is_file():
        raise SystemExit(f"owned master missing: {MASTER}")
    if not ROLES.is_file():
        raise SystemExit(f"owned roles missing: {ROLES}")

    for g in args.groups:
        if g not in GROUP_META:
            raise SystemExit(f"unknown group {g}")

    results = []
    if args.workers <= 1:
        for g in args.groups:
            print(f"[batch-fl] group {g} …", flush=True)
            results.append(_run_group(g, args.lit))
            print(json.dumps(results[-1]), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_run_group, g, args.lit): g for g in args.groups}
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                print(json.dumps(r), flush=True)

    summary = ART / "out_fit" / "batch_fixed_length_summary.json"
    summary.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    bad = [r for r in results if not r.get("ok")]
    print(json.dumps({"ok": not bad, "n": len(results), "failed": bad}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
