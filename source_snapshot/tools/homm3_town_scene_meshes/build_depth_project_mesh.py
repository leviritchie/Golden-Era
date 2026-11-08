#!/usr/bin/env python3
"""Build a depth-displaced mesh and UV-project the original Factory plate paint.

Offline Option B: no Meshy style. Exports OBJ + copies albedo, then optionally
invokes Blender for unlit preview renders. Does not deploy to the game.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = (
    REPO
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_factory"
    / "mockups"
    / "homm3_factory_background_upscaled_3840x2160.png"
)
DEFAULT_OUT = (
    REPO
    / "artifacts"
    / "meshy_town_scene_meshes"
    / "homm3_factory"
    / "backdrop_depth_project"
)
DEFAULT_BLENDER = Path("V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
RENDER_SCRIPT = Path(__file__).resolve().parent / "render_depth_project_preview.py"


def write_obj(
    path: Path,
    verts: np.ndarray,
    uvs: np.ndarray,
    faces: np.ndarray,
    mtl_name: str,
) -> None:
    """Write triangle mesh OBJ with VT + usemtl."""
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"mtllib {mtl_name}\n")
        f.write("o FactoryBackdropDepth\n")
        for x, y, z in verts:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for u, v in uvs:
            f.write(f"vt {u:.6f} {v:.6f}\n")
        f.write("usemtl FactoryPaint\n")
        f.write("s off\n")
        # faces are (i0,i1,i2) 0-based
        for a, b, c in faces:
            # OBJ is 1-based; pair v/vt
            f.write(
                f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n"
            )


def build_mesh(
    depth: np.ndarray,
    *,
    step: int,
    depth_scale: float,
    invert_depth: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, w = depth.shape
    # Sample grid (include last column/row).
    xs = list(range(0, w, step))
    if xs[-1] != w - 1:
        xs.append(w - 1)
    ys = list(range(0, h, step))
    if ys[-1] != h - 1:
        ys.append(h - 1)
    cols = len(xs)
    rows = len(ys)

    d = depth.astype(np.float64)
    dmin, dmax = float(d.min()), float(d.max())
    norm = (d - dmin) / (dmax - dmin + 1e-8)
    if invert_depth:
        # Treat larger model output as nearer (flip if preview looks wrong).
        norm = 1.0 - norm

    # Plane: X right, Y up, Z toward camera (near = +Z). Aspect matches image.
    aspect = w / float(h)
    verts = np.zeros((rows * cols, 3), dtype=np.float64)
    uvs = np.zeros((rows * cols, 2), dtype=np.float64)
    for j, py in enumerate(ys):
        for i, px in enumerate(xs):
            idx = j * cols + i
            u = px / float(w - 1)
            v = 1.0 - (py / float(h - 1))  # image top -> UV v=1
            # Near (small norm / closer) sits toward camera (+Z).
            z = (1.0 - float(norm[py, px])) * depth_scale
            x = (u - 0.5) * aspect
            y = (v - 0.5) * 1.0
            verts[idx] = (x, y, z)
            uvs[idx] = (u, v)

    faces = []
    for j in range(rows - 1):
        for i in range(cols - 1):
            a = j * cols + i
            b = a + 1
            c = a + cols
            d_idx = c + 1
            faces.append((a, c, b))
            faces.append((b, c, d_idx))
    return verts, uvs, np.asarray(faces, dtype=np.int32)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--depth-npy", type=Path, default=None)
    ap.add_argument("--step", type=int, default=4, help="pixel stride for mesh verts")
    ap.add_argument("--depth-scale", type=float, default=0.55)
    ap.add_argument(
        "--invert-depth",
        action="store_true",
        help="flip near/far if Depth Anything polarity looks wrong",
    )
    ap.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    ap.add_argument("--skip-render", action="store_true")
    args = ap.parse_args()

    out_dir = args.out_dir.resolve()
    image_path = args.image.resolve()
    depth_npy = (
        args.depth_npy.resolve()
        if args.depth_npy
        else out_dir / "depth_float32.npy"
    )
    if not image_path.is_file():
        raise SystemExit(f"missing image: {image_path}")
    if not depth_npy.is_file():
        raise SystemExit(f"missing depth npy (run estimate first): {depth_npy}")

    depth = np.load(depth_npy)
    if depth.ndim != 2:
        raise SystemExit(f"bad depth shape: {depth.shape}")
    img = Image.open(image_path).convert("RGB")
    if img.size != (depth.shape[1], depth.shape[0]):
        raise SystemExit(
            f"size mismatch image={img.size} depth={depth.shape[1]}x{depth.shape[0]}"
        )

    verts, uvs, faces = build_mesh(
        depth,
        step=max(1, int(args.step)),
        depth_scale=float(args.depth_scale),
        invert_depth=bool(args.invert_depth),
    )

    albedo_name = "albedo_source.png"
    shutil.copy2(image_path, out_dir / albedo_name)
    mtl_name = "factory_backdrop_depth.mtl"
    obj_name = "factory_backdrop_depth.obj"
    (out_dir / mtl_name).write_text(
        "\n".join(
            [
                "newmtl FactoryPaint",
                "Ka 1.000 1.000 1.000",
                "Kd 1.000 1.000 1.000",
                "Ks 0.000 0.000 0.000",
                "d 1.0",
                "illum 1",
                f"map_Kd {albedo_name}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_obj(out_dir / obj_name, verts, uvs, faces, mtl_name)

    meta = {
        "source_image": str(image_path),
        "depth_npy": str(depth_npy),
        "obj": str(out_dir / obj_name),
        "albedo": str(out_dir / albedo_name),
        "vert_count": int(verts.shape[0]),
        "face_count": int(faces.shape[0]),
        "step": int(args.step),
        "depth_scale": float(args.depth_scale),
        "invert_depth": bool(args.invert_depth),
        "convention": "X right, Y up, +Z toward camera; near = less displaced into scene",
        "proof": "offline_spike_only_not_game_deploy",
    }
    (out_dir / "mesh_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {obj_name} verts={verts.shape[0]} tris={faces.shape[0]} "
        f"scale={args.depth_scale} invert={args.invert_depth}"
    )

    if args.skip_render:
        return
    blender = args.blender
    if not blender.is_file():
        raise SystemExit(f"missing blender: {blender}")
    if not RENDER_SCRIPT.is_file():
        raise SystemExit(f"missing render script: {RENDER_SCRIPT}")
    preview_dir = out_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(blender),
        "-b",
        "--python",
        str(RENDER_SCRIPT),
        "--",
        "--obj",
        str(out_dir / obj_name),
        "--albedo",
        str(out_dir / albedo_name),
        "--out-dir",
        str(preview_dir),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
