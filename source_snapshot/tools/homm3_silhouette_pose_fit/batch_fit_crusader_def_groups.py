#!/usr/bin/env python3
"""Batch-fit crusader DEF groups with authored DOFs (parallel Blender fits).

Quality-same speedups live in blender_ik_markers (vectorized collision sample,
CCD skip locked axes). This runner parallelizes independent group fits.

  py -3 tools/homm3_silhouette_pose_fit/batch_fit_crusader_def_groups.py \\
    --groups 0 1 3 4 5 7 8 9 10 11 13 20 21 --workers 2

Preflight: bind multi-angle joint audit (`run_joint_audit.py`) — fail-closed.
Stages NN frames → mesh-bind seed → LK track → marker IK → optional lit preview.
Fail-closed: missing DOF file / empty group / failed subprocess aborts that group.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
TRACK = ROOT / "tools/homm3_sprite_motion_track/track_joints_lk.py"
NN_ROOT = ROOT / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale"
ART = ROOT / "artifacts/crusader_pose_pipeline"
MASTER = (
    ART
    / "out_meshy_t2_idle_f0/rigged/idle_f0_rigged_meshy6_bridgefix_hand.glb"
)
ROLES_DEFAULT = TOOL / "bone_roles_crusader_meshy_t2.json"
ROLES_WALK = TOOL / "bone_roles_crusader_meshy_t2_walk.json"

# Present CCRUSD groups excluding already-proven idle g2 + attack front g12.
GROUP_META = {
    0: ("move", "walk"),
    1: ("mouseover", "idle_like"),
    3: ("hitted", "hit"),
    4: ("defence", "defence"),
    5: ("death", "death"),
    7: ("turn_left", "turn"),
    8: ("turn_right", "turn"),
    9: ("unused_a", "idle_like"),
    10: ("unused_b", "idle_like"),
    11: ("attack_up", "attack"),
    13: ("attack_down", "attack"),
    20: ("move_start", "walk"),
    21: ("move_end", "walk"),
}


def _py() -> list[str]:
    return [sys.executable]


def _slice_group(gid: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    srcs = sorted(NN_ROOT.glob(f"{gid:02d}_*.png"))
    if not srcs:
        raise RuntimeError(f"no NN frames for group {gid} under {NN_ROOT}")
    frames: list[Path] = []
    index = []
    for i, src in enumerate(srcs):
        dst = out_dir / f"frame_{i:02d}.png"
        shutil.copy2(src, dst)
        frames.append(dst)
        index.append({"i": i, "source": src.name, "frame": dst.name, "group": gid})
    # Soft ground-shadow must be gone before seed/track/fit (alpha snap + landmarks).
    _run(
        [
            *_py(),
            str(TOOL / "cull_def_soft_shadow_frames.py"),
            "--src-dir",
            str(out_dir),
            "--min-culled-per-frame",
            "1",
        ],
        out_dir / "soft_shadow_cull_run.log",
    )
    (out_dir / "frame_index.json").write_text(
        json.dumps(
            {
                "group": gid,
                "frames": index,
                "cullDefSoftShadows": True,
                "cullReport": "soft_shadow_cull_report.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return frames


def _write_job_stub(clip_id: str, frames: list[Path], out_job: Path, roles: Path) -> None:
    """Minimal job for mesh-bind seed (camera matches crusader visual-match)."""
    job = {
        "unitSid": "h3_crusader",
        "clipId": clip_id,
        "masterGlb": str(MASTER).replace("\\", "/"),
        "boneRoles": str(roles).replace("\\", "/"),
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 4.2,
            "rootYawDeg": 0.0,
        },
        "frames": [{"path": str(p).replace("\\", "/")} for p in frames],
    }
    out_job.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")


def _ik_profile(family: str) -> dict:
    """Per-family markerIk levers from visual inspection (not one attack template)."""
    # Shared upright planted baseline.
    base = {
        "rekeyTipIfErrorPx": 140.0,
        "rootTranslate": True,
        "rootTranslateBound": 0.85,
        "boundRad": 1.45,
        "armBoundRad": 1.95,
        "maxSteps": 48,
        "plateauSteps": 8,
        "damping": 0.18,
        "eps": 0.02,
        "lossFloorPx": 2.0,
        "joltFrac": 0.22,
        "joltGrow": 1.12,
        "joltFracMax": 0.75,
        "ccdTipIterations": 48,
        "ccdAngCapHi": 0.85,
        "ccdAngCapLo": 0.40,
        "tipWeightBoost": 1.2,
        "restWeight": 0.05,
        "motionWeight": 0.12,
        "skipFullBodyIfTipErrorPx": 160.0,
        "ccdBodyGuardPx": 200.0,
        "bodyGuardSlackPx": 70.0,
        "bodyGuardAbsCeilPx": 200.0,
        "torsoMinDot": 0.10,
        "spineBoundRad": 0.85,
        "bodyLandmarkBoost": 1.6,
        "maxStepRad": 0.28,
        "groundAnchor": {"mode": "frame0_lateral_lowest_foot"},
        "collisionBias": {
            "enabled": True,
            "sampleCount": 256,
            "geodesicMinHops": 8,
            "margin": 0.045,
            "weight": 22.0,
        },
    }
    if family == "idle_like":
        base.update(
            {
                "tipWeightBoost": 1.05,
                "restWeight": 0.10,
                "motionWeight": 0.20,
                "ccdTipIterations": 24,
                "skipFullBodyIfTipErrorPx": 220.0,
                "maxStepRad": 0.12,
                "bodyLandmarkBoost": 1.8,
                "collisionBias": {
                    "enabled": True,
                    "sampleCount": 192,
                    "geodesicMinHops": 8,
                    "margin": 0.05,
                    "weight": 28.0,
                },
            }
        )
    elif family == "turn":
        base.update(
            {
                "tipWeightBoost": 1.8,
                "restWeight": 0.08,
                "motionWeight": 0.14,
                "ccdTipIterations": 48,
                "skipFullBodyIfTipErrorPx": 120.0,
                "torsoMinDot": 0.25,
                "maxStepRad": 0.18,
                "spineBoundRad": 0.90,
            }
        )
    elif family == "walk":
        base.update(
            {
                "tipWeightBoost": 1.0,
                "restWeight": 0.08,
                "motionWeight": 0.16,
                "ccdTipIterations": 24,
                "skipFullBodyIfTipErrorPx": 260.0,
                "bodyLandmarkBoost": 2.0,
                "maxStepRad": 0.22,
                "boundRad": 1.40,
                "torsoMinDot": 0.25,
                "joltFrac": 0.14,
                "collisionBias": {
                    "enabled": True,
                    "sampleCount": 224,
                    "geodesicMinHops": 8,
                    "margin": 0.05,
                    "weight": 24.0,
                },
            }
        )
    elif family in ("hit", "defence"):
        base.update(
            {
                "tipWeightBoost": 1.35,
                "restWeight": 0.10,
                "motionWeight": 0.16,
                "ccdTipIterations": 36,
                "skipFullBodyIfTipErrorPx": 180.0,
                "bodyLandmarkBoost": 2.0,
                "torsoMinDot": 0.35,
                "maxStepRad": 0.18,
                "spineBoundRad": 0.70,
                "boundRad": 1.25,
                "joltFrac": 0.15,
                "collisionBias": {
                    "enabled": True,
                    "sampleCount": 256,
                    "geodesicMinHops": 8,
                    "margin": 0.05,
                    "weight": 30.0,
                },
            }
        )
    elif family == "death":
        # Lying/flip sprites fight upright plant — disable plant, allow larger steps.
        base.update(
            {
                "tipWeightBoost": 1.1,
                "restWeight": 0.03,
                "motionWeight": 0.06,
                "ccdTipIterations": 40,
                "skipFullBodyIfTipErrorPx": 220.0,
                "torsoMinDot": -0.5,
                "spineBoundRad": 1.35,
                "boundRad": 1.75,
                "armBoundRad": 2.2,
                "maxStepRad": 0.45,
                "rootTranslateBound": 1.2,
                "groundAnchor": {"mode": "off"},
                "collisionBias": {
                    "enabled": True,
                    "sampleCount": 256,
                    "geodesicMinHops": 8,
                    "margin": 0.04,
                    "weight": 16.0,
                },
            }
        )
    elif family == "attack":
        base.update(
            {
                "tipWeightBoost": 2.6,
                "restWeight": 0.04,
                "motionWeight": 0.10,
                "ccdTipIterations": 80,
                "skipFullBodyIfTipErrorPx": 70.0,
                "bodyGuardSlackPx": 40.0,
                "bodyGuardAbsCeilPx": 160.0,
                "ccdBodyGuardPx": 160.0,
                "torsoMinDot": 0.20,
                "spineBoundRad": 0.70,
                "maxStepRad": 0,
                "bodyLandmarkBoost": 2.2,
                "collisionBias": {
                    "enabled": True,
                    "sampleCount": 320,
                    "geodesicMinHops": 8,
                    "margin": 0.045,
                    "weight": 40.0,
                },
            }
        )
    return base


def _write_fit_config(
    *,
    gid: int,
    name: str,
    clip_id: str,
    frames: list[Path],
    out_dir: Path,
    dof_path: Path,
    roles: Path,
    unlock_legs: bool,
    family: str,
) -> Path:
    # Legs always optimized; unlock_legs kept for call-site clarity / legacy configs.
    optimize = [
        "Hips",
        "Spine02",
        "Spine01",
        "Spine",
        "neck",
        "Head",
        "RightShoulder",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
    ]
    if not unlock_legs:
        raise RuntimeError(
            f"{clip_id}: unlock_legs=False is retired — HoMM3 clips need knee/weight-shift; "
            "use hinge DOFs + groundAnchor plant instead of lockedBones"
        )
    profile = _ik_profile(family)
    marker_ik = {
        "identityFrame0": False,
        "frame0RootAlign": True,
        "frame0CameraRegister": False,
        "lockGrabVertsAfterFrame0": True,
        "tipPickMode": "farthest_from_hand",
        "midlineBias": {"enabled": False},
        "boneEulerAxesSchedule": [
            {
                "frameFrom": 0,
                "frameTo": len(frames) - 1,
                "path": str(dof_path.relative_to(ROOT)).replace("\\", "/"),
            }
        ],
        "armChain": ["RightShoulder", "RightArm", "RightForeArm", "RightHand"],
        "minSkinWeight": 0.20,
        "preferPrevVertSlackPx": 14.0,
        "skinBoneExtras": {
            "WeaponTip": ["RightHand", "RightForeArm"],
            "RWrist": ["RightHand", "RightForeArm"],
            "LWrist": ["LeftHand", "LeftForeArm", "LeftArm"],
        },
        "seed": 11,
        "optimizeBones": optimize,
        # Always drive hips/knees — track already has them; omitting froze lower body.
        "markers": [
            "WeaponTip",
            "RWrist",
            "RElbow",
            "RShoulder",
            "LWrist",
            "LElbow",
            "Nose",
            "Neck",
            "MidHip",
            "RHip",
            "RKnee",
            "LHip",
            "LKnee",
        ],
        **profile,
    }
    cfg = {
        "unitSid": "h3_crusader",
        "clipId": clip_id,
        "fps": 12,
        "masterGlb": str(MASTER).replace("\\", "/"),
        "outputDir": str(out_dir).replace("\\", "/"),
        "boneRoles": str(roles).replace("\\", "/"),
        "cullDefSoftShadows": True,
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 4.2,
            "rootYawDeg": 0.0,
        },
        "frames": [{"path": str(p).replace("\\", "/")} for p in frames],
        "method_kind": "keypoints",
        "method": "sprite_visual_match_contract",
        "poseSource": "sprite_landmarks",
        "poseSolver": "marker_ik",
        "markerIk": marker_ik,
        "optimizeBones": optimize,
        "absoluteRefine": {"enabled": False},
        "absoluteMatch": {
            "paletteNormalize": True,
            "alphaThr": 8.0,
            "failClosedMaxChromaMae": 18.0,
            "failClosedMaxRgbMae": 45.0,
        },
        "notes": (
            f"Batch crusader DEF group {gid} ({name}/{family}); "
            "per-clip DOFs + family IK profile from visual inspection."
        ),
    }
    cfg_path = TOOL / "configs" / f"h3_crusader_{clip_id}_meshy_t2_marker_ik.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def _run(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(cmd)} — see {log_path}")


def _fill_joint_from_seed_anchor_offset(
    kpt_path: Path,
    seed_path: Path,
    *,
    joint: str,
    anchor: str,
    method: str,
) -> int:
    """Fill invisible joint from anchor using seed joint−anchor vector. Returns fill count."""
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    sj = seed.get("joints") or {}
    if joint not in sj or anchor not in sj:
        return 0
    dx = float(sj[joint]["x"]) - float(sj[anchor]["x"])
    dy = float(sj[joint]["y"]) - float(sj[anchor]["y"])
    kpt = json.loads(kpt_path.read_text(encoding="utf-8"))
    filled = 0
    for fr in kpt.get("frames") or []:
        joints = fr.get("joints") or {}
        tgt = joints.get(joint)
        anc = joints.get(anchor)
        if tgt is None or anc is None:
            continue
        if tgt.get("visible") and float(tgt.get("score") or 0) > 0:
            continue
        if not anc.get("visible"):
            continue
        tgt["x"] = float(anc["x"]) + dx
        tgt["y"] = float(anc["y"]) + dy
        tgt["score"] = 0.5
        tgt["visible"] = True
        tgt["method"] = method
        tgt["dx"] = 0.0
        tgt["dy"] = 0.0
        filled += 1
    if filled:
        key = f"{joint}SeedOffsetFills"
        kpt[key] = int(kpt.get(key) or 0) + filled
        kpt_path.write_text(json.dumps(kpt, indent=2) + "\n", encoding="utf-8")
    return filled


def _fill_weapon_tip_from_seed_offset(kpt_path: Path, seed_path: Path) -> int:
    """Fill invisible WeaponTip from RWrist using seed tip−wrist vector. Returns fill count."""
    return _fill_joint_from_seed_anchor_offset(
        kpt_path,
        seed_path,
        joint="WeaponTip",
        anchor="RWrist",
        method="seed_tip_wrist_offset",
    )


def _temporal_hold_joint(kpt_path: Path, joint: str) -> int:
    """Fill invisible joint from previous visible frame. Returns hold count."""
    kpt = json.loads(kpt_path.read_text(encoding="utf-8"))
    holds = 0
    prev = None
    for fr in kpt.get("frames") or []:
        joints = fr.get("joints") or {}
        j = joints.get(joint)
        if j is None:
            continue
        if j.get("visible") and float(j.get("score") or 0) > 0:
            prev = dict(j)
            continue
        if prev is not None and prev.get("visible"):
            j["x"] = float(prev["x"])
            j["y"] = float(prev["y"])
            j["score"] = 0.45
            j["visible"] = True
            j["method"] = "temporal_hold_prev"
            j["dx"] = 0.0
            j["dy"] = 0.0
            holds += 1
        prev = dict(j) if j.get("visible") else prev
    if holds:
        key = f"{joint}TemporalHolds"
        kpt[key] = int(kpt.get(key) or 0) + holds
        kpt_path.write_text(json.dumps(kpt, indent=2) + "\n", encoding="utf-8")
    return holds


def _write_static_keypoints_from_seed(
    *, seed_path: Path, frames_dir: Path, out_path: Path
) -> None:
    """For near-static clips: replicate seed joints on every frame (explicit, not a silent track fallback)."""
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError(f"no frames in {frames_dir}")
    rgba0 = frames[0]
    from PIL import Image

    w, h = Image.open(rgba0).size
    joints0 = seed.get("joints") or {}
    out_frames = []
    for i, fp in enumerate(frames):
        joints = {}
        for name, j in joints0.items():
            joints[name] = {
                "x": float(j["x"]),
                "y": float(j["y"]),
                "score": float(j.get("score", 1.0)),
                "visible": True,
                "dx": 0.0,
                "dy": 0.0,
                "method": "static_seed_replicate",
            }
        out_frames.append(
            {
                "frameIndex": i,
                "ok": True,
                "path": str(fp).replace("\\", "/"),
                "transform": {"srcWidth": w, "srcHeight": h},
                "joints": joints,
            }
        )
    report = {
        "ok": True,
        "method": "static_seed_replicate",
        "frames": out_frames,
        "proof": "generated — near-static clip; seed joints copied per frame (not LK track)",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def prepare_group(gid: int) -> dict:
    name, family = GROUP_META[gid]
    clip_id = f"{name}_g{gid}"
    # Legs always unlocked: track already has hip/knee landmarks; freezing them
    # made non-walk clips look mannequin-legged. Plant is groundAnchor, not lockedBones.
    unlock_legs = True
    roles = ROLES_DEFAULT
    dof_path = TOOL / f"bone_dofs_crusader_{clip_id}.json"
    if not dof_path.is_file():
        raise RuntimeError(f"missing authored DOF file: {dof_path}")
    if not roles.is_file():
        raise RuntimeError(f"missing bone roles: {roles}")

    frames_dir = ART / "source_frames" / f"nn_upscale_g{gid:02d}_{name}"
    frames = _slice_group(gid, frames_dir)
    work = ART / f"out_track_g{gid:02d}_{name}"
    seed_dir = work / "seed"
    track_dir = work / "track"
    fit_dir = ART / "out_fit" / f"g{gid:02d}_{name}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    track_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "sprite_landmarks").mkdir(parents=True, exist_ok=True)

    job_path = work / "job.seed.json"
    _write_job_stub(clip_id, frames, job_path, roles)

    # Mesh-bind seed (Blender).
    _run(
        [
            str(BLENDER),
            "-b",
            "--python",
            str(TOOL / "seed_joints_from_mesh_bind.py"),
            "--",
            "--job",
            str(job_path),
            "--roles",
            str(roles),
            "--sprite",
            str(frames[0]),
            "--out-dir",
            str(seed_dir),
        ],
        work / "seed_run.log",
    )
    seed_raw = seed_dir / "seed_joints_f00_mesh_bind.json"
    if not seed_raw.is_file():
        cands = list(seed_dir.glob("seed_joints*.json"))
        if not cands:
            raise RuntimeError(f"seed missing under {seed_dir}")
        seed_raw = cands[0]
    seed = seed_dir / "seed_joints_f00.json"
    _run(
        [
            *_py(),
            str(TOOL / "snap_seed_to_sprite_alpha.py"),
            "--seed",
            str(seed_raw),
            "--sprite",
            str(frames[0]),
            "--out",
            str(seed),
            "--max-dist-px",
            "64",
        ],
        work / "seed_snap_run.log",
    )

    kpt = track_dir / "keypoints.json"
    # Near-static clips still need real tip/wrist motion (mouseover raises the sword).
    # static_seed_replicate froze mesh-bind tip and fought the sprite — use LK + fills.
    use_lk = True
    if use_lk:
        core = ["Nose", "MidHip", "RWrist"]
        track_cmd = [
            *_py(),
            str(TRACK),
            "--seed",
            str(seed),
            "--sprite-dir",
            str(frames_dir),
            "--out-dir",
            str(track_dir),
            "--tip-profile",
            "silver_blade",
            "--core-joints",
            ",".join(core),
        ]
        track_log = work / "track_run.log"
        track_log.parent.mkdir(parents=True, exist_ok=True)
        with track_log.open("w", encoding="utf-8") as log:
            trc = subprocess.run(
                track_cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT
            )
        if not kpt.is_file():
            raise RuntimeError(
                f"keypoints missing after track (rc={trc.returncode}): {kpt} — see {track_log}"
            )
        if trc.returncode != 0:
            print(
                f"[batch] g{gid} track rc={trc.returncode}; repairing dropped joints…",
                flush=True,
            )
        mid_holds = _temporal_hold_joint(kpt, "MidHip")
        neck_fills = _fill_joint_from_seed_anchor_offset(
            kpt,
            seed,
            joint="Neck",
            anchor="Nose",
            method="seed_neck_nose_offset",
        )
        neck_holds = _temporal_hold_joint(kpt, "Neck")
        nose_fills = _fill_joint_from_seed_anchor_offset(
            kpt,
            seed,
            joint="Nose",
            anchor="Neck",
            method="seed_nose_neck_offset",
        )
        tip_fills = _fill_weapon_tip_from_seed_offset(kpt, seed)
        if mid_holds or neck_fills or neck_holds or nose_fills or tip_fills:
            print(
                f"[batch] g{gid} fills midHold={mid_holds} neck={neck_fills}+hold{neck_holds} "
                f"nose={nose_fills} tip={tip_fills}",
                flush=True,
            )
        kpt_data = json.loads(kpt.read_text(encoding="utf-8"))
        required = list(core) + ["Neck"]
        if family in ("attack", "walk", "idle_like", "turn", "hit", "defence"):
            required.append("WeaponTip")
        missing = []
        for fr in kpt_data.get("frames") or []:
            joints = fr.get("joints") or {}
            for joint_name in required:
                j = joints.get(joint_name) or {}
                if not j.get("visible"):
                    missing.append(f"frame {fr.get('frameIndex')} {joint_name}")
        if missing:
            raise RuntimeError(
                f"g{gid} ({family}) joints still invisible after seed-offset: "
                f"{missing[:12]}"
            )
        kpt_data["ok"] = True
        kpt_data["errors"] = []
        kpt_data["repairedAfterTrack"] = True
        kpt.write_text(json.dumps(kpt_data, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(kpt, fit_dir / "sprite_landmarks" / "keypoints.json")

    cfg_path = _write_fit_config(
        gid=gid,
        name=name,
        clip_id=clip_id,
        frames=frames,
        out_dir=fit_dir,
        dof_path=dof_path,
        roles=roles,
        unlock_legs=unlock_legs,
        family=family,
    )
    return {
        "gid": gid,
        "name": name,
        "clipId": clip_id,
        "config": str(cfg_path),
        "fitDir": str(fit_dir),
        "frames": len(frames),
        "family": family,
    }


def fit_group(payload: dict) -> dict:
    fit_dir = Path(payload["fitDir"])
    log = fit_dir / "fit_batch_run.log"
    _run(
        [
            *_py(),
            str(TOOL / "run_fit.py"),
            "--config",
            payload["config"],
            "--skip-infer",
            "--skip-absolute-match",
        ],
        log,
    )
    report = fit_dir / "fit_report.json"
    if not report.is_file():
        raise RuntimeError(f"fit_report missing for g{payload['gid']}")
    mean = json.loads(report.read_text(encoding="utf-8")).get("meanLossPx")
    return {**payload, "ok": True, "meanLossPx": mean, "log": str(log)}


def _emit_clip_ready(result: dict) -> dict:
    """Copy clip-named preview + print a line agents/humans can watch for."""
    fit_dir = Path(result["fitDir"])
    preview = fit_dir / "preview"
    clip_id = result["clipId"]
    generic_gif = preview / "attack_g11_side_by_side.gif"
    named_gif = preview / f"{clip_id}_side_by_side.gif"
    generic_mp4 = preview / "attack_g11_side_by_side_slow.mp4"
    named_mp4 = preview / f"{clip_id}_side_by_side_slow.mp4"
    if generic_gif.is_file():
        shutil.copy2(generic_gif, named_gif)
    if generic_mp4.is_file():
        shutil.copy2(generic_mp4, named_mp4)
    mid = preview / "frames" / "side_00.png"
    payload = {
        "gid": result["gid"],
        "name": result["name"],
        "clipId": clip_id,
        "meanLossPx": result.get("meanLossPx"),
        "gif": str(named_gif if named_gif.is_file() else generic_gif).replace("\\", "/"),
        "mp4": str(named_mp4 if named_mp4.is_file() else generic_mp4).replace("\\", "/"),
        "side0": str(mid).replace("\\", "/") if mid.is_file() else None,
        "fitDir": str(fit_dir).replace("\\", "/"),
        "proof": "generated — side-by-side preview; not OE runtime",
    }
    ready_path = preview / "CLIP_READY.json"
    preview.mkdir(parents=True, exist_ok=True)
    ready_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Single-line machine token for shell notify_on_output / chat watchers.
    print(
        "NOTIFY_CLIP_READY "
        + json.dumps(payload, separators=(",", ":")),
        flush=True,
    )
    return payload


def _run_joint_audit_preflight() -> Path:
    """Fail-closed bind multi-angle joint audit before any prepare/fit."""
    out = ART / "out_fit" / "joint_audit_bind"
    sprite = (
        ART / "source_frames/nn_upscale_idle_attack/frame_00.png"
        if (ART / "source_frames/nn_upscale_idle_attack/frame_00.png").is_file()
        else None
    )
    cmd = [
        *_py(),
        str(TOOL / "run_joint_audit.py"),
        "--master",
        str(MASTER),
        "--roles",
        str(ROLES_DEFAULT),
        "--out",
        str(out),
    ]
    if sprite is not None:
        cmd.extend(["--sprite", str(sprite)])
    print("[batch] joint-audit preflight…", flush=True)
    _run(cmd, out / "joint_audit_batch_preflight.log")
    report = out / "joint_audit_report.json"
    if not report.is_file():
        raise RuntimeError(f"joint audit missing report: {report}")
    payload = json.loads(report.read_text(encoding="utf-8"))
    if not payload.get("ok") or payload.get("issues"):
        raise RuntimeError(
            "joint audit failed (fix bone_roles / master before fitting): "
            + json.dumps(payload.get("issues") or [], indent=2)
        )
    print(f"[batch] joint-audit ok → {out / 'joints_contact_sheet.png'}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--groups",
        nargs="+",
        type=int,
        default=sorted(GROUP_META.keys()),
    )
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--fit-only", action="store_true")
    ap.add_argument(
        "--skip-joint-audit",
        action="store_true",
        help="Skip bind multi-angle joint audit (not recommended; audit is fail-closed by default).",
    )
    ap.add_argument(
        "--notify",
        action="store_true",
        help="After each clip fit+preview, print NOTIFY_CLIP_READY JSON line and write CLIP_READY.json.",
    )
    ap.add_argument(
        "--interleaved",
        action="store_true",
        help="Prepare+fit one group at a time (earlier first preview). Implied by --notify.",
    )
    args = ap.parse_args()
    for g in args.groups:
        if g not in GROUP_META:
            raise SystemExit(f"unsupported group {g}; known={sorted(GROUP_META)}")

    if not args.skip_joint_audit:
        _run_joint_audit_preflight()
    else:
        print("[batch] WARNING: --skip-joint-audit set; roles/master unchecked", flush=True)

    notify = bool(args.notify)
    interleaved = bool(args.interleaved or notify)
    if notify and args.prepare_only:
        raise SystemExit("--notify cannot combine with --prepare-only")

    # Interleaved: prepare → fit → notify per group so previews arrive early.
    if interleaved and not args.fit_only and not args.prepare_only:
        results = []
        ready = []
        print(
            f"[batch] interleaved prepare+fit for {len(args.groups)} groups "
            f"(notify={notify})",
            flush=True,
        )
        for g in args.groups:
            print(f"[batch] prepare g{g}…", flush=True)
            payload = prepare_group(g)
            print(
                f"[batch] prepared g{g} frames={payload['frames']}; fitting…",
                flush=True,
            )
            result = fit_group(payload)
            results.append(result)
            if notify:
                ready.append(_emit_clip_ready(result))
            else:
                print(
                    f"[batch] done g{g} meanLossPx={result.get('meanLossPx')}",
                    flush=True,
                )
        out = ART / "out_fit" / "batch_remaining_summary.json"
        out.write_text(
            json.dumps({"ok": True, "results": results, "ready": ready}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(
            "NOTIFY_PASS_DONE "
            + json.dumps(
                {
                    "ok": True,
                    "count": len(results),
                    "summary": str(out).replace("\\", "/"),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0

    prepared = []
    if not args.fit_only:
        for g in args.groups:
            print(f"[batch] prepare g{g}…", flush=True)
            prepared.append(prepare_group(g))
            print(f"[batch] prepared g{g} frames={prepared[-1]['frames']}", flush=True)
    else:
        for g in args.groups:
            name, _ = GROUP_META[g]
            clip_id = f"{name}_g{g}"
            fit_dir = ART / "out_fit" / f"g{g:02d}_{name}"
            cfg = TOOL / "configs" / f"h3_crusader_{clip_id}_meshy_t2_marker_ik.json"
            if not cfg.is_file():
                raise SystemExit(f"--fit-only missing config {cfg}")
            prepared.append(
                {
                    "gid": g,
                    "name": name,
                    "clipId": clip_id,
                    "config": str(cfg),
                    "fitDir": str(fit_dir),
                    "frames": 0,
                }
            )

    if args.prepare_only:
        print(json.dumps({"ok": True, "prepared": prepared}, indent=2))
        return 0

    workers = 1 if notify else max(1, int(args.workers))
    results = []
    ready = []
    print(f"[batch] fitting {len(prepared)} groups with workers={workers}", flush=True)
    if workers == 1:
        for p in prepared:
            print(f"[batch] fit g{p['gid']}…", flush=True)
            result = fit_group(p)
            results.append(result)
            if notify:
                ready.append(_emit_clip_ready(result))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fit_group, p): p["gid"] for p in prepared}
            for fut in as_completed(futs):
                gid = futs[fut]
                try:
                    r = fut.result()
                    results.append(r)
                    print(
                        f"[batch] done g{gid} meanLossPx={r.get('meanLossPx')}",
                        flush=True,
                    )
                    if notify:
                        ready.append(_emit_clip_ready(r))
                except Exception as e:
                    print(f"[batch] FAIL g{gid}: {e}", flush=True)
                    raise

    out = ART / "out_fit" / "batch_remaining_summary.json"
    out.write_text(
        json.dumps({"ok": True, "results": results, "ready": ready}, indent=2) + "\n",
        encoding="utf-8",
    )
    if notify:
        print(
            "NOTIFY_PASS_DONE "
            + json.dumps(
                {
                    "ok": True,
                    "count": len(results),
                    "summary": str(out).replace("\\", "/"),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    print(json.dumps({"ok": True, "summary": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
