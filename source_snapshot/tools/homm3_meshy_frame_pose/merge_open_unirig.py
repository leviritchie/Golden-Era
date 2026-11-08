"""Merge UniRig skin NPZ onto the Y-up unskinned angel GLB and write inspect stills."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
UNIRIG = ROOT / "tools" / "third_party" / "UniRig"
POSE = ROOT / "tools" / "homm3_meshy_frame_pose"
OUT = ROOT / "artifacts" / "angel_pose_pipeline" / "unirig"
INPUT_GLB = UNIRIG / "examples" / "h3_angel_unskinned.glb"
NPZ_DIR = OUT / "tmp" / "examples" / "h3_angel_unskinned"

sys.path.insert(0, str(UNIRIG))
sys.path.insert(0, str(POSE))

from owned_rerig.glb_io import load_mesh, write_skinned_mesh  # noqa: E402
from owned_rerig.preview import write_ppm  # noqa: E402
from src.system.skin import reskin  # noqa: E402


def _denorm(points: np.ndarray, mesh_vertices: np.ndarray) -> np.ndarray:
    lo = mesh_vertices.min(axis=0)
    hi = mesh_vertices.max(axis=0)
    center = (lo + hi) / 2.0
    scale = float(np.max(hi - lo) / 2.0)
    return points * scale + center


def _pack_top4(skin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-skin, axis=1)[:, :4]
    weights = np.take_along_axis(skin, order, axis=1)
    total = weights.sum(axis=1, keepdims=True)
    total = np.maximum(total, 1e-8)
    weights = weights / total
    return order.astype(np.uint8), weights.astype(np.float32)


def _draw_yup(path: Path, positions: np.ndarray, joints: np.ndarray, parents: list, *, posed: np.ndarray | None = None) -> None:
    size = 512
    pts = np.asarray(positions, dtype=np.float64)
    xy = pts[:, [0, 1]]
    jxy = np.asarray(joints, dtype=np.float64)[:, [0, 1]]
    all_xy = np.concatenate([xy, jxy], axis=0)
    lo = all_xy.min(axis=0)
    hi = all_xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = (16, 16, 20)

    def to_px(p):
        uv = (p - lo) / span
        px = np.clip((uv[:, 0] * (size - 8) + 4).astype(int), 0, size - 1)
        py = np.clip(((1.0 - uv[:, 1]) * (size - 8) + 4).astype(int), 0, size - 1)
        return px, py

    px, py = to_px(xy)
    img[py, px] = (180, 170, 150)
    if posed is not None:
        qx, qy = to_px(np.asarray(posed, dtype=np.float64)[:, [0, 1]])
        img[qy, qx] = (80, 180, 220)
    jx, jy = to_px(jxy)
    for i, parent in enumerate(parents):
        if parent is None:
            continue
        x0, y0 = int(jx[parent]), int(jy[parent])
        x1, y1 = int(jx[i]), int(jy[i])
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        xs = np.linspace(x0, x1, n).astype(int)
        ys = np.linspace(y0, y1, n).astype(int)
        img[ys, xs] = (240, 80, 80)
    img[jy, jx] = (255, 230, 80)
    write_ppm(path, img)
    Image.fromarray(img).save(path.with_suffix(".png"))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument(
        "--proof-bones",
        default="LeftWing2,LeftArm,RightHand",
        help="comma-separated bone names to rotate for stills",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    skel = np.load(NPZ_DIR / "predict_skeleton.npz", allow_pickle=True)
    sampled = np.load(NPZ_DIR / "predict_skin.npz", allow_pickle=True)
    names = skel["names"][()]
    if isinstance(names, np.ndarray):
        names = [str(n) for n in names.tolist()]
    parents = skel["parents"][()]
    if isinstance(parents, np.ndarray):
        parents = parents.tolist()
    parents = [None if p is None or (isinstance(p, float) and np.isnan(p)) else int(p) for p in parents]
    origin = skel["vertices"].astype(np.float32)
    faces = skel["faces"].astype(np.int64)
    joints_n = skel["joints"].astype(np.float32)
    sampled_skin = sampled["skin"].astype(np.float32)
    sampled_verts = sampled["vertices"].astype(np.float32)
    origin_skin = reskin(
        sampled_vertices=sampled_verts,
        vertices=origin,
        parents=parents,
        faces=faces,
        sampled_skin=sampled_skin,
        sample_method="median",
        alpha=2.0,
        threshold=0.03,
    )
    mesh = load_mesh(INPUT_GLB)
    world_origin = _denorm(origin, mesh.positions)
    world_joints = _denorm(joints_n, mesh.positions)
    tree = cKDTree(world_origin)
    _, nn = tree.query(mesh.positions, k=1)
    full_skin = origin_skin[nn]
    joints4, weights4 = _pack_top4(full_skin)
    owners = np.argmax(full_skin, axis=1)
    counts = {names[i]: int((owners == i).sum()) for i in range(len(names))}
    dest = out_dir / "h3_angel_unirig.glb"
    write_skinned_mesh(
        dest,
        positions=mesh.positions.astype(np.float32),
        indices=mesh.indices,
        bone_names=names,
        parents=parents,
        heads=world_joints,
        joints=joints4,
        weights=weights4,
        extras={
            "source": "open_unirig_refined_skeleton",
            "seed": 12345,
            "checkpoint": "articulation-xl skin on edited UniRig skeleton",
            "proof": "generated-artifact; not owned-bind delivery; not OE runtime",
        },
        source_glb=INPUT_GLB,
    )
    stills = out_dir / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    _draw_yup(stills / "rest_front.ppm", mesh.positions, world_joints, parents)
    from owned_rerig.audit import lbs_delta_after_bone_rotate

    name_index = {n: i for i, n in enumerate(names)}
    for proof_bone in [b.strip() for b in str(args.proof_bones).split(",") if b.strip()]:
        if proof_bone not in name_index:
            raise KeyError(f"proof bone {proof_bone} not in {names}")
        delta = lbs_delta_after_bone_rotate(
            mesh.positions,
            joints4,
            weights4,
            world_joints,
            parents,
            name_index[proof_bone],
            np.array([0.0, 0.0, 1.0]),
            float(np.deg2rad(35.0)),
        )
        _draw_yup(
            stills / f"rotate_{proof_bone}_front.ppm",
            mesh.positions,
            world_joints,
            parents,
            posed=mesh.positions + delta,
        )
    report = {
        "schema": "open_unirig_angel_refined.v1",
        "glb": str(dest).replace("\\", "/"),
        "seed": 12345,
        "jointCount": len(names),
        "names": names,
        "parents": parents,
        "ownerCounts": counts,
        "vertexCount": int(len(mesh.positions)),
        "method": "UniRig 22-bone predict + authored wing/sword joints + UniRig skin weights",
        "proof": "generated-artifact; rest stills only; not OE runtime; CURRENT_CASCADE_KEEP stays closed",
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"glb": report["glb"], "ownerCounts": counts}, indent=2))


if __name__ == "__main__":
    main()
