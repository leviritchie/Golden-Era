#!/usr/bin/env python3
"""A/B compare crusader idle+attack marker-IK variants on soft-shadow-culled frames.

Writes each variant under out_fit/idle_attack_front/compare_noshadow/<name>/,
fits sequentially, optional lit preview, and a summary JSON.

  py -3 tools/homm3_silhouette_pose_fit/compare_idle_attack_variants.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
BASE_CFG = TOOL / "configs/h3_crusader_idle_attack_front_meshy_t2_marker_ik.json"
OUT_ROOT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/idle_attack_front/compare_noshadow"
KPT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/idle_attack_front/sprite_landmarks/keypoints.json"


def _load_base() -> dict:
    return json.loads(BASE_CFG.read_text(encoding="utf-8"))


def _variant_plant_collision() -> dict:
    cfg = _load_base()
    cfg["clipId"] = "idle_attack_plant_collision"
    cfg["notes"] = "noshadow A/B: frame0_lateral_lowest_foot + collisionBias (speedups on)"
    return cfg


def _variant_plant_nocollision() -> dict:
    cfg = _load_base()
    cfg["clipId"] = "idle_attack_plant_nocollision"
    mik = cfg.setdefault("markerIk", {})
    cb = dict(mik.get("collisionBias") or {})
    cb["enabled"] = False
    mik["collisionBias"] = cb
    cfg["notes"] = "noshadow A/B: plant groundAnchor, collisionBias OFF"
    return cfg


def _variant_hips_locked() -> dict:
    cfg = _load_base()
    cfg["clipId"] = "idle_attack_hips_locked"
    mik = cfg.setdefault("markerIk", {})
    # Inline DOF override: lock Hips on both schedule segments.
    idle = TOOL / "bone_dofs_crusader_idle_g2.json"
    atk = TOOL / "bone_dofs_crusader_attack_front_g12.json"
    idle_d = json.loads(idle.read_text(encoding="utf-8"))
    atk_d = json.loads(atk.read_text(encoding="utf-8"))
    idle_d["bones"]["Hips"] = {"axes": [], "why": "A/B hips locked"}
    atk_d["bones"]["Hips"] = {"axes": [], "why": "A/B hips locked"}
    out_dofs = OUT_ROOT / "_dofs"
    out_dofs.mkdir(parents=True, exist_ok=True)
    idle_p = out_dofs / "bone_dofs_crusader_idle_g2_hips_locked.json"
    atk_p = out_dofs / "bone_dofs_crusader_attack_front_g12_hips_locked.json"
    idle_p.write_text(json.dumps(idle_d, indent=2) + "\n", encoding="utf-8")
    atk_p.write_text(json.dumps(atk_d, indent=2) + "\n", encoding="utf-8")
    sched = mik.get("boneEulerAxesSchedule") or []
    new_sched = []
    for seg in sched:
        s = dict(seg)
        p = str(s.get("path") or "")
        if "idle_g2" in p:
            s["path"] = str(idle_p.relative_to(ROOT)).replace("\\", "/")
        elif "attack_front" in p:
            s["path"] = str(atk_p.relative_to(ROOT)).replace("\\", "/")
        new_sched.append(s)
    mik["boneEulerAxesSchedule"] = new_sched
    cfg["notes"] = "noshadow A/B: plant + collision, Hips axes locked"
    return cfg


def _variant_frame0_root() -> dict:
    cfg = _load_base()
    cfg["clipId"] = "idle_attack_frame0_root"
    mik = cfg.setdefault("markerIk", {})
    mik["groundAnchor"] = {"mode": "frame0_root"}
    cfg["notes"] = "noshadow A/B: frame0_root (no foot plant), collision on"
    return cfg


VARIANTS = {
    "plant_collision": _variant_plant_collision,
    "plant_nocollision": _variant_plant_nocollision,
    "hips_locked": _variant_hips_locked,
    "frame0_root": _variant_frame0_root,
}


def _run(cmd: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"failed ({p.returncode}): {' '.join(cmd)} — {log}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS.keys()))
    ap.add_argument("--skip-lit", action="store_true")
    args = ap.parse_args()
    if not KPT.is_file():
        raise SystemExit(f"missing keypoints: {KPT}")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for name in args.variants:
        if name not in VARIANTS:
            raise SystemExit(f"unknown variant {name}; known={sorted(VARIANTS)}")
        print(f"[compare] {name}…", flush=True)
        out_dir = OUT_ROOT / name
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        (out_dir / "sprite_landmarks").mkdir()
        shutil.copy2(KPT, out_dir / "sprite_landmarks" / "keypoints.json")
        cfg = VARIANTS[name]()
        cfg["outputDir"] = str(out_dir).replace("\\", "/")
        cfg_path = out_dir / "config.json"
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        t0 = time.perf_counter()
        _run(
            [
                sys.executable,
                str(TOOL / "run_fit.py"),
                "--config",
                str(cfg_path),
                "--skip-infer",
                "--skip-absolute-match",
            ],
            out_dir / "fit_run.log",
        )
        elapsed = time.perf_counter() - t0
        report = json.loads((out_dir / "fit_report.json").read_text(encoding="utf-8"))
        row = {
            "variant": name,
            "meanLossPx": report.get("meanLossPx"),
            "elapsedSec": round(elapsed, 1),
            "groundAnchor": (report.get("groundAnchor") or {}).get("mode")
            if isinstance(report.get("groundAnchor"), dict)
            else report.get("groundAnchor"),
            "collisionBias": bool((report.get("collisionBias") or {}).get("enabled"))
            if isinstance(report.get("collisionBias"), dict)
            else report.get("collisionBias"),
            "notes": cfg.get("notes"),
        }
        stops = [f.get("stopReason") for f in (report.get("frames") or [])]
        row["stopReasons"] = {s: stops.count(s) for s in sorted(set(stops)) if s}
        tip = [float(f.get("tipErrorPx") or 0) for f in (report.get("frames") or [])]
        row["maxTipErrPx"] = max(tip) if tip else None
        row["meanTipErrPx"] = (sum(tip) / len(tip)) if tip else None
        if not args.skip_lit and BLENDER.is_file():
            # Smooth then lit
            smooth = out_dir / "fit_report_smoothed.json"
            _run(
                [
                    sys.executable,
                    str(TOOL / "smooth_marker_pose_vectors.py"),
                    "--report",
                    str(out_dir / "fit_report.json"),
                    "--out",
                    str(smooth),
                    "--preserve-extrema",
                    "1",
                ],
                out_dir / "smooth_run.log",
            )
            _run(
                [
                    str(BLENDER),
                    "-b",
                    "--python",
                    str(TOOL / "render_mesh_lit_60fps.py"),
                    "--",
                    "--job",
                    str(out_dir / "job.resolved.json"),
                    "--report",
                    str(smooth),
                ],
                out_dir / "lit_run.log",
            )
            lit_frames = out_dir / "preview_lit_60fps" / "frames"
            mp4 = out_dir / "preview_lit_60fps" / f"{name}_lit_60fps.mp4"
            if lit_frames.is_dir():
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-framerate",
                        "60",
                        "-i",
                        str(lit_frames / "frame_%04d.png"),
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-crf",
                        "18",
                        str(mp4),
                    ],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                row["litMp4"] = str(mp4).replace("\\", "/")
        results.append(row)
        print(
            f"[compare] {name} meanLoss={row['meanLossPx']:.2f} "
            f"sec={row['elapsedSec']} tipMax={row['maxTipErrPx']}",
            flush=True,
        )

    summary = {
        "ok": True,
        "proof": "generated — noshadow A/B on soft-shadow-culled idle+attack; human lit compare",
        "keypoints": str(KPT).replace("\\", "/"),
        "results": results,
    }
    (OUT_ROOT / "comparison_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
