#!/usr/bin/env python3
"""Fit Cavalier idle + walk on the owned rider_mount master.

Sprite GPU cascade is used when authentic 12fps plates exist. Otherwise this
writer emits bind-proof clips through the existing cascade GLB writer so the
owned skeleton can be judged (horse legs vs rider helmet) without claiming a
sprite-solved cascade run.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "homm3_silhouette_pose_fit"
MESHY = ROOT / "tools" / "homm3_meshy_frame_pose"
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(MESHY))

from gpu_cascade_delivery import write_gpu_cascade_clip_glb  # noqa: E402
from owned_rerig.glb_io import load_mesh  # noqa: E402

OWNED_MASTER = ROOT / "artifacts" / "cavalier_pose_pipeline" / "owned_bind" / "h3_cavalier_master_yup.glb"
OUT_DIR = ROOT / "artifacts" / "cavalier_pose_pipeline" / "gpu_cascade_skinned"
SPRITE_ROOTS = (
    ROOT / "OfflineUnlockMod" / "homm3_lab" / "h3_cavalier" / "extracted_battle_source_12fps",
    Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_cavalier/extracted_battle_source_12fps"),
)

CONTRACT = {
    2: "Cavalier_Idle",
    0: "Cavalier_Move",
}
REQUIRED_BONES = ("HorseLeftShoulder", "HorseRightShoulder", "RiderHead", "LanceTip")


def _require_owned_master(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"owned Cavalier master missing: {path}")
    mesh = load_mesh(path)
    names = set(mesh.node_names)
    missing = [name for name in REQUIRED_BONES if name not in names]
    if missing:
        raise RuntimeError(f"{path} is not an owned rider_mount master; missing {missing}")
    if any("mixamo" in n.lower() for n in names):
        raise RuntimeError(f"{path} still contains Mixamo bones; refuse cascade")


def _find_sprites() -> Path | None:
    for path in SPRITE_ROOTS:
        if path.is_dir() and any(path.glob("*.png")):
            return path
    return None


def _idle_poses(n: int, bone_names: list[str]) -> dict[int, dict[str, Any]]:
    zero = {name: {"x": 0.0, "y": 0.0, "z": 0.0} for name in bone_names}
    return {i: dict(zero) for i in range(n)}


def _walk_poses(n: int, bone_names: list[str]) -> dict[int, dict[str, Any]]:
    # Pose-dict x/y/z values are axis-angle DEGREES (gpu_clip_result contract);
    # the GLB exporter converts to radians internally.
    poses = {}
    for i in range(n):
        phase = 2.0 * math.pi * i / max(n, 1)
        frame = {name: {"x": 0.0, "y": 0.0, "z": 0.0} for name in bone_names}
        if "HorseLeftShoulder" in frame:
            frame["HorseLeftShoulder"]["x"] = 25.0 * math.sin(phase)
        if "HorseRightShoulder" in frame:
            frame["HorseRightShoulder"]["x"] = 25.0 * math.sin(phase + math.pi)
        if "HorseLeftHip" in frame:
            frame["HorseLeftHip"]["x"] = 23.0 * math.sin(phase + math.pi)
        if "HorseRightHip" in frame:
            frame["HorseRightHip"]["x"] = 23.0 * math.sin(phase)
        poses[i] = frame
    return poses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=OWNED_MASTER)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--bind-proof", action="store_true", default=True)
    parser.add_argument("--sprite-fit", action="store_true")
    args = parser.parse_args()
    master = args.master.resolve()
    _require_owned_master(master)
    mesh = load_mesh(master)
    bone_names = [mesh.node_names[i] for i in mesh.skin_joints] if mesh.skin_joints else mesh.node_names
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sprite_dir = _find_sprites()
    solver = "owned_bind_pose_proof"
    if args.sprite_fit:
        if sprite_dir is None:
            raise FileNotFoundError(
                "authentic 12fps Cavalier plates are missing; refusing to claim GPU cascade sprite fit"
            )
        raise RuntimeError(
            f"Cavalier GPU sprite cascade is not wired to plates yet ({sprite_dir}). "
            "Run --bind-proof until idle/walk plates are authored and cascaded."
        )
    idle = write_gpu_cascade_clip_glb(
        master,
        out / "Cavalier_Idle.glb",
        _idle_poses(8, bone_names),
        clip_name="Cavalier_Idle",
        fps=12.0,
    )
    walk = write_gpu_cascade_clip_glb(
        master,
        out / "Cavalier_Move.glb",
        _walk_poses(12, bone_names),
        clip_name="Cavalier_Move",
        fps=12.0,
    )
    report = {
        "schema": "cavalier_cascade_clips.v1",
        "solver": solver,
        "proof": "generated-artifact",
        "notUserVisibleGameplay": True,
        "master": str(master).replace("\\", "/"),
        "idle": idle,
        "walk": walk,
        "spriteDir": None if sprite_dir is None else str(sprite_dir).replace("\\", "/"),
        "note": "Horse shoulder/hip sinus vs still rider helmet is the bind tell. This is not a sprite-fitted GPU cascade.",
    }
    (out / "clip_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "solver": solver, "out": str(out).replace("\\", "/")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
