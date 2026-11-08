"""Add wing and sword joints to the UniRig 22-bone skeleton, then leave weights to UniRig skin.

Joint heads come from authored sprite-space 3D seeds (converted Z-up -> Y-up, then
into UniRig's normalized mesh box). This is the UniRig README refine-skeleton path,
not nearest-bone weight paint.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
from owned_rerig.glb_io import load_mesh  # noqa: E402
from owned_rerig.preview import write_ppm  # noqa: E402

UNIRIG = ROOT / "tools" / "third_party" / "UniRig"
OUT = ROOT / "artifacts" / "angel_pose_pipeline" / "unirig"
SEED_NPZ = OUT / "seeds" / "12345" / "predict_skeleton.npz"
RAW_NPZ = OUT / "tmp" / "examples" / "h3_angel_unskinned" / "raw_data.npz"
DEST_NPZ = OUT / "tmp" / "examples" / "h3_angel_unskinned" / "predict_skeleton.npz"
PART_MAP = ROOT / "artifacts" / "angel_pose_pipeline" / "owned_bind" / "part_map_authored.json"
YUP_GLB = UNIRIG / "examples" / "h3_angel_unskinned.glb"
CHEST = 11
RIGHT_HAND = 17


def _z_up_to_y_up(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=np.float64)
    return np.array([p[0], p[2], -p[1]], dtype=np.float64)


def _world_to_norm(points: np.ndarray, raw_vertices: np.ndarray) -> np.ndarray:
    lo = raw_vertices.min(axis=0)
    hi = raw_vertices.max(axis=0)
    center = (lo + hi) / 2.0
    scale = float(np.max(hi - lo) / 2.0)
    return (points - center) / scale


def _lerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return a * (1.0 - t) + b * t


def _seed_map(authored: dict) -> dict[str, np.ndarray]:
    out = {}
    for seed in authored["seeds"]:
        out[str(seed["label"])] = _z_up_to_y_up(np.array(seed["point"], dtype=np.float64))
    return out


def _chain(start: np.ndarray, mid: np.ndarray, tip: np.ndarray) -> list[np.ndarray]:
    return [
        _lerp(start, mid, 0.25),
        np.asarray(mid, dtype=np.float64),
        _lerp(mid, tip, 0.55),
        np.asarray(tip, dtype=np.float64),
    ]


def _draw(path: Path, positions: np.ndarray, joints: np.ndarray, parents: list) -> None:
    size = 512
    xy = np.asarray(positions, dtype=np.float64)[:, [0, 1]]
    jxy = np.asarray(joints, dtype=np.float64)[:, [0, 1]]
    all_xy = np.concatenate([xy, jxy], axis=0)
    lo = all_xy.min(axis=0)
    hi = all_xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = (16, 16, 20)

    def px(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        uv = (p - lo) / span
        x = np.clip((uv[:, 0] * (size - 8) + 4).astype(int), 0, size - 1)
        y = np.clip(((1.0 - uv[:, 1]) * (size - 8) + 4).astype(int), 0, size - 1)
        return x, y

    x, y = px(xy)
    img[y, x] = (180, 170, 150)
    jx, jy = px(jxy)
    for i, parent in enumerate(parents):
        if parent is None:
            continue
        n = max(abs(int(jx[i] - jx[parent])), abs(int(jy[i] - jy[parent])), 1)
        xs = np.linspace(jx[parent], jx[i], n).astype(int)
        ys = np.linspace(jy[parent], jy[i], n).astype(int)
        color = (80, 200, 255) if i >= 22 else (240, 80, 80)
        img[ys, xs] = color
    img[jy, jx] = (255, 230, 80)
    write_ppm(path, img)
    Image.fromarray(img).save(path.with_suffix(".png"))


def main() -> None:
    src = np.load(SEED_NPZ, allow_pickle=True)
    raw = np.load(RAW_NPZ, allow_pickle=True)
    raw_verts = raw["vertices"].astype(np.float64)
    authored = json.loads(PART_MAP.read_text(encoding="utf-8"))
    seeds = _seed_map(authored)
    world_seeds = {k: _world_to_norm(v, raw_verts) for k, v in seeds.items()}

    sys.path.insert(0, str(UNIRIG))
    from src.data.raw_data import RawData

    joints = src["joints"].astype(np.float64)
    tails = src["tails"].astype(np.float64)
    names = [str(n) for n in src["names"].tolist()]
    parents = src["parents"].tolist()
    names[14:18] = ["RightShoulder", "RightArm", "RightForeArm", "RightHand"]
    names[18:22] = ["LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"]

    chest = joints[CHEST]
    left = _chain(chest, world_seeds["left_wing_mid"], world_seeds["left_wing_tip"])
    right = _chain(chest, world_seeds["right_wing_mid"], world_seeds["right_wing_tip"])
    weapon = [
        world_seeds["hilt"],
        world_seeds["tip"],
    ]

    new_names = [
        "LeftWing0",
        "LeftWing1",
        "LeftWing2",
        "LeftWing3",
        "RightWing0",
        "RightWing1",
        "RightWing2",
        "RightWing3",
        "Weapon",
        "WeaponTip",
    ]
    new_parents = [CHEST, 22, 23, 24, CHEST, 26, 27, 28, RIGHT_HAND, 30]
    new_joints = np.stack(left + right + weapon, axis=0)
    added = []
    for i, name in enumerate(new_names):
        idx = 22 + i
        parent = new_parents[i]
        if parent >= idx:
            raise ValueError(f"parent index {parent} must be < {idx} for {name}")
        names.append(name)
        parents.append(parent)
        added.append(new_joints[i])
    joints = np.concatenate([joints, np.stack(added)], axis=0)

    new_tails = np.zeros_like(joints)
    new_tails[:22] = tails
    children: dict[int, list[int]] = {i: [] for i in range(len(names))}
    for i, parent in enumerate(parents):
        if parent is None:
            continue
        children[int(parent)].append(i)
    for i in range(len(names)):
        kids = children[i]
        if len(kids) == 1:
            new_tails[i] = joints[kids[0]]
        elif i > 0 and parents[i] is not None:
            direction = joints[i] - joints[int(parents[i])]
            norm = float(np.linalg.norm(direction))
            new_tails[i] = joints[i] + direction * (0.35 if norm > 1e-8 else 0.02)
        else:
            new_tails[i] = joints[i]

    payload = RawData(
        vertices=src["vertices"],
        vertex_normals=src["vertex_normals"],
        faces=src["faces"],
        face_normals=src["face_normals"],
        joints=joints.astype(np.float32),
        tails=new_tails.astype(np.float32),
        skin=None,
        no_skin=None,
        parents=parents,
        names=names,
        matrix_local=None,
        path=str(DEST_NPZ),
        cls=str(src["cls"][()]),
    )
    payload.check()
    DEST_NPZ.parent.mkdir(parents=True, exist_ok=True)
    payload.save(str(DEST_NPZ))
    archive = OUT / "refined"
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEST_NPZ, archive / "predict_skeleton.npz")

    mesh = load_mesh(YUP_GLB)
    lo = raw_verts.min(axis=0)
    hi = raw_verts.max(axis=0)
    center = (lo + hi) / 2.0
    scale = float(np.max(hi - lo) / 2.0)
    world_joints = joints * scale + center
    _draw(archive / "skeleton_front.ppm", mesh.positions, world_joints, parents)
    notes = {
        "schema": "unirig_refine_skeleton.v1",
        "base": "seeds/12345 22-bone UniRig predict",
        "added": new_names,
        "parents": {new_names[i]: names[new_parents[i]] for i in range(len(new_names))},
        "method": "authored Z-up seeds -> Y-up -> UniRig normalize; UniRig skin assigns weights",
        "not": "AABB nearest-bone owned bind",
        "proof": "generated-artifact",
    }
    (archive / "skeleton.json").write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bones": len(names), "dest": str(DEST_NPZ)}, indent=2))


if __name__ == "__main__":
    main()
