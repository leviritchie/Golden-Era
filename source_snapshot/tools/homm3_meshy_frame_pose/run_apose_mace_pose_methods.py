#!/usr/bin/env python3
"""After A-pose+mace master exists, run several attack-g11 pose methods and write a compare note."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "tools/.venvs/homm3_dwpose/Scripts/python.exe"
POSE = ROOT / "tools/homm3_silhouette_pose_fit"
OUT_ROOT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline"
MASTER = OUT_ROOT / "master/hobgoblin_apose_mace_attach.glb"
ROLES = OUT_ROOT / "out_apose_mace_attach/bone_roles_apose_mace.json"
CFG_DIR = POSE / "configs"


def _write_cfg(name: str, body: dict) -> Path:
    path = CFG_DIR / name
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _base_job(output_dir: str, method_kind: str) -> dict:
    frames = [
        {"path": f"artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11/frame_{i:02d}.png"}
        for i in range(8)
    ]
    roles_rel = "artifacts/hobgoblin_attack_pose_pipeline/out_apose_mace_attach/bone_roles_apose_mace.json"
    return {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "fps": 12,
        "masterGlb": "artifacts/hobgoblin_attack_pose_pipeline/master/hobgoblin_apose_mace_attach.glb",
        "outputDir": output_dir,
        "boneRoles": roles_rel,
        "cullDefSoftShadows": True,
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 2.6,
            "rootYawDeg": 0.0,
        },
        "frames": frames,
        "method_kind": method_kind,
    }


def main() -> int:
    if not MASTER.is_file():
        print(f"missing master: {MASTER}", file=sys.stderr)
        return 2
    if not ROLES.is_file():
        print(f"missing roles: {ROLES}", file=sys.stderr)
        return 2

    roles = json.loads(ROLES.read_text(encoding="utf-8"))
    optimize = list(roles.get("optimizeBones") or [])

    methods = []

    # 1) chroma75 + sil + motion
    j = _base_job(
        "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_chroma75_motion_iso_apose_mace",
        "silhouette",
    )
    j.update(
        {
            "method": "chroma_silhouette_motion",
            "render": {"width": 192, "height": 170},
            "optimizeBones": optimize,
            "optimizer": {
                "method": "hybrid",
                "boundRad": 0.96,
                "restWeight": 0.0,
                "motionWeight": 0.15,
                "chromaWeight": 0.75,
                "silhouetteWeight": 0.25,
                "identityFrame0": True,
                "maxStepRad": 0.7,
                "deMaxiter": 5,
                "popsize": 18,
                "polishIters": 40,
                "seed": 7,
            },
            "notes": "A-pose+mace-attach master. chroma75/sil25/motion on canonical g11.",
        }
    )
    cfg1 = _write_cfg("h3_hobgoblin_attack_g11_chroma75_motion_iso_apose_mace.json", j)
    methods.append(("chroma75_motion", "silhouette", cfg1))

    # 2) DWPose + temporal
    j2 = _base_job(
        "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_dwpose_temporal_iso_apose_mace",
        "keypoints",
    )
    j2.update(
        {
            "method": "dwpose_reprojection",
            "dwpose": {
                "longEdges": [1024, 1280],
                "backgrounds": [[0, 0, 0], [32, 32, 32], [180, 180, 180]],
                "minMeanBodyScore": 0.14,
                "minVisibleJoints": 8,
                "scoreThr": 0.18,
                "requireVerticalLegs": False,
            },
            "temporalSmooth": {
                "enabled": True,
                "method": "score_weighted_gaussian",
                "window": 5,
                "sigma": 1.25,
                "scorePower": 1.0,
            },
            "keypointOptimizer": {
                "boundRad": 0.95,
                "restWeight": 0.06,
                "motionWeight": 0.18,
                "maxStepRad": 0.7,
                "localRestarts": True,
                "identityFrame0": True,
                "maxiter": 180,
                "maxfev": 650,
                "restarts": 5,
                "seed": 7,
            },
            "notes": "A-pose+mace-attach. DWPose+temporal on canonical g11.",
        }
    )
    cfg2 = _write_cfg("h3_hobgoblin_attack_g11_dwpose_temporal_iso_apose_mace.json", j2)
    methods.append(("dwpose_temporal", "keypoints", cfg2))

    # 3) sprite landmarks
    j3 = _base_job(
        "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_landmarks_iso_apose_mace",
        "keypoints",
    )
    j3.update(
        {
            "method": "sprite_landmarks_reprojection",
            "keypointOptimizer": {
                "boundRad": 0.95,
                "restWeight": 0.05,
                "motionWeight": 0.15,
                "maxStepRad": 0.7,
                "localRestarts": True,
                "identityFrame0": True,
                "maxiter": 180,
                "maxfev": 650,
                "restarts": 5,
                "seed": 7,
            },
            "notes": "A-pose+mace-attach. sprite landmarks on canonical g11.",
        }
    )
    cfg3 = _write_cfg("h3_hobgoblin_attack_g11_landmarks_iso_apose_mace.json", j3)
    methods.append(("landmarks", "keypoints", cfg3))

    summary = {"master": str(MASTER).replace("\\", "/"), "runs": []}
    for tag, kind, cfg in methods:
        print(f"\n======== RUN {tag} ({kind}) ========", flush=True)
        if kind == "silhouette":
            cmd = [
                str(PY),
                str(POSE / "run_silhouette_fit.py"),
                "--config",
                str(cfg),
                "--force-targets",
            ]
        else:
            cmd = [
                str(PY),
                str(POSE / "run_fit.py"),
                "--config",
                str(cfg),
                "--pose-source",
                "dwpose" if tag.startswith("dwpose") else "sprite_landmarks",
                "--roles",
                str(ROLES),
            ]
        print("Running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT))
        rec = {"tag": tag, "config": str(cfg).replace("\\", "/"), "rc": proc.returncode}
        out_dir = ROOT / json.loads(cfg.read_text())["outputDir"]
        fr = out_dir / "fit_report.json"
        fr2 = out_dir / "fit_report_kpt.json"
        report_path = fr2 if fr2.is_file() else fr
        if report_path.is_file():
            data = json.loads(report_path.read_text(encoding="utf-8"))
            rec["meanLoss"] = data.get("meanLoss")
            rec["losses"] = data.get("losses")
            rec["preview"] = str((out_dir / "preview" / "attack_g11_side_by_side.gif")).replace("\\", "/")
        summary["runs"].append(rec)
        if proc.returncode != 0:
            print(f"FAIL {tag} rc={proc.returncode}", flush=True)

    out_sum = OUT_ROOT / "out_apose_mace_attach" / "method_runs_summary.json"
    out_sum.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if all(r["rc"] == 0 for r in summary["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
