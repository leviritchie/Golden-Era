#!/usr/bin/env python3
"""Build props_coords.json from DEF articulation discovery (no cascade pose seed)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
DISCOVER = ROOT / "tools/homm3_sprite_motion_track/discover_articulation_from_motion.py"
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"


def _part_index(part_id: str) -> int:
    return int(str(part_id).split("_")[-1])


def map_parts_by_bind_tip_proximity(
    parts: list[dict[str, Any]],
    *,
    joint_screen_xy: dict[str, tuple[float, float]],
) -> dict[str, int]:
    """Match articulation parts to prop joints by minimum total bind-tip distance."""
    if not parts:
        raise ValueError("articulation parts list is empty")
    part_indices = [_part_index(str(part["id"])) for part in parts]
    part_points = np.asarray([part["centroidF0"] for part in parts], dtype=np.float64)
    joint_names = list(joint_screen_xy.keys())
    targets = np.asarray([joint_screen_xy[name] for name in joint_names], dtype=np.float64)
    if targets.shape[0] > part_points.shape[0]:
        raise ValueError(
            f"need at least {targets.shape[0]} articulation parts, got {part_points.shape[0]}"
        )
    cost = np.linalg.norm(part_points[:, None, :] - targets[None, :, :], axis=2)
    try:
        from scipy.optimize import linear_sum_assignment

        rows, cols = linear_sum_assignment(cost)
    except Exception:
        rows = np.arange(len(joint_names), dtype=np.int64)
        cols = np.argsort(cost[rows, :], axis=1)[:, 0]
    mapping: dict[str, int] = {}
    for row, col in zip(rows, cols):
        if int(col) >= len(joint_names):
            continue
        mapping[joint_names[int(col)]] = int(part_indices[int(row)])
    missing = [name for name in joint_names if name not in mapping]
    if missing:
        raise ValueError(f"articulation mapping missing joints {missing}")
    return mapping


def bind_tip_screen_xy(
    *,
    unit: str,
    clip: str,
    frame_dir: Path,
    frame_index: int,
    prop_joints: Sequence[str],
    bone_roles_path: Path,
) -> dict[str, tuple[float, float]]:
    """Project bind-pose prop tips to full-resolution sprite pixels (correspondence only)."""
    if str(TOOL) not in sys.path:
        sys.path.insert(0, str(TOOL))
    from anatomy_probe_veto import load_bone_roles, resolve_prop_joint_node_indices
    from def_mocap_bootstrap import bootstrap_flow_mocap_experiment

    clip_base = ROOT / "artifacts" / "pose_picker_runs" / unit / clip
    init_dir = clip_base / "_bind_tip_probe_init"
    experiment, _bones, root_t, root_r, _camera, _shell = bootstrap_flow_mocap_experiment(
        unit=unit,
        clip=clip,
        frame_dir=frame_dir,
        frame_indices=[int(frame_index)],
        init_dir=init_dir,
    )
    roles = load_bone_roles(bone_roles_path)
    joint_nodes = resolve_prop_joint_node_indices(
        experiment.node_names,
        bone_roles=roles,
        joint_names=tuple(prop_joints),
    )
    screen = experiment._screen_joint_xy(_bones, root_t, root_r)
    raster_w, raster_h = (float(v) for v in experiment.config.resolution)
    from PIL import Image

    probe = next(frame_dir.glob(f"{int(frame_index):02d}.png"), None)
    if probe is None:
        probe = frame_dir / f"{int(frame_index)}.png"
    sprite_w, sprite_h = Image.open(probe).size
    scale = np.asarray([sprite_w / raster_w, sprite_h / raster_h], dtype=np.float64)
    out: dict[str, tuple[float, float]] = {}
    for joint_name in prop_joints:
        node = int(joint_nodes[str(joint_name)])
        xy = screen[0, node, :2].detach().cpu().numpy().astype(np.float64) * scale
        out[str(joint_name)] = (float(xy[0]), float(xy[1]))
    return out


def run_articulation_discovery(
    *,
    frames_dir: Path,
    out_dir: Path,
    k: int = 8,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "articulation_report.json"
    if report_path.is_file():
        return json.loads(report_path.read_text(encoding="utf-8"))
    cmd = [
        sys.executable,
        str(DISCOVER),
        "--frames-dir",
        str(frames_dir),
        "--out-dir",
        str(out_dir),
        "--k",
        str(int(k)),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"articulation discovery failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    return json.loads(report_path.read_text(encoding="utf-8"))


def articulation_to_props_coords(
    report: dict[str, Any],
    *,
    unit: str,
    clip: str,
    prop_joints: list[str],
    sprite_size: tuple[int, int],
    frame_indices: list[int],
    bone_roles_path: Path,
    frame_dir: Path,
) -> dict[str, Any]:
    parts = list(report.get("parts") or [])
    centroids = list(report.get("partCentroidsPerFrame") or [])
    if not parts or not centroids:
        raise ValueError("articulation report missing parts or partCentroidsPerFrame")
    if len(centroids) != len(frame_indices):
        raise ValueError(
            f"articulation frame count {len(centroids)} != clip frames {len(frame_indices)}"
        )
    tip_xy = bind_tip_screen_xy(
        unit=unit,
        clip=clip,
        frame_dir=frame_dir,
        frame_index=int(frame_indices[0]),
        prop_joints=prop_joints,
        bone_roles_path=bone_roles_path,
    )
    joint_to_part = map_parts_by_bind_tip_proximity(parts, joint_screen_xy=tip_xy)
    frames_out: list[dict[str, Any]] = []
    for frame_num, row in zip(frame_indices, centroids):
        if len(row) < max(joint_to_part.values()) + 1:
            raise ValueError(f"articulation row too short for frame {frame_num}")
        xy: dict[str, list[int]] = {}
        for joint_name, part_idx in joint_to_part.items():
            cx, cy = row[int(part_idx)]
            xy[joint_name] = [int(round(float(cx))), int(round(float(cy)))]
        frames_out.append({"frameIndex": int(frame_num), "xy": xy})
    return {
        "clipId": str(clip),
        "unitSid": str(unit),
        "joints": list(prop_joints),
        "edgeSet": "def_articulation_centroids",
        "notes": (
            "2D part centroids from discover_articulation_from_motion; "
            f"mapping={joint_to_part}"
        ),
        "spriteSize": {"width": int(sprite_size[0]), "height": int(sprite_size[1])},
        "articulationMapping": {key: int(value) for key, value in joint_to_part.items()},
        "frames": frames_out,
    }
