"""Run open UniRig on the unskinned angel mesh (skeleton, then optional skin).

This is an experiment against Meshy's closed Smart Rig (also UniRig under the hood).
It is not owned-bind delivery and does not bump CURRENT_CASCADE_KEEP.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIRIG = ROOT / "tools" / "third_party" / "UniRig"
VENV_PY = UNIRIG / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "artifacts" / "angel_pose_pipeline" / "unirig"
SRC_MESHY = ROOT / "artifacts" / "meshy_downloads" / "h3_angel_smartrigged.glb"


def _run(cmd: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    hf_home = str(UNIRIG / ".hf_cache")
    env["HF_HOME"] = hf_home
    env["HUGGINGFACE_HUB_CACHE"] = hf_home
    env["TRANSFORMERS_CACHE"] = hf_home
    env.setdefault("CUDA_HOME", r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8")
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def extract_npz(input_glb: Path, npz_path: Path, *, faces_target_count: int) -> None:
    sys.path.insert(0, str(UNIRIG))
    import numpy as np
    import trimesh
    import fast_simplification
    from src.data.raw_data import RawData

    mesh = trimesh.load(str(input_glb), force="mesh", process=False)
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if faces.shape[0] > faces_target_count:
        vertices, faces = fast_simplification.simplify(
            vertices, faces, target_count=faces_target_count
        )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    raw = RawData(
        vertices=np.array(mesh.vertices, dtype=np.float32),
        vertex_normals=np.array(mesh.vertex_normals, dtype=np.float32),
        faces=np.array(mesh.faces, dtype=np.int64),
        face_normals=np.array(mesh.face_normals, dtype=np.float32),
        joints=None,
        tails=None,
        skin=None,
        no_skin=None,
        parents=None,
        names=None,
        matrix_local=None,
    )
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(str(npz_path))


def _summarize_skeleton(npz_path: Path) -> dict:
    import numpy as np

    data = np.load(npz_path, allow_pickle=True)
    names = data["names"][()]
    if isinstance(names, np.ndarray):
        names = names.tolist()
    parents = data["parents"][()]
    if isinstance(parents, np.ndarray):
        parents = parents.tolist()
    joints = data["joints"].astype(np.float32)
    children: dict[int, list[int]] = {i: [] for i in range(len(names))}
    for i, parent in enumerate(parents):
        if parent is None or (isinstance(parent, float) and np.isnan(parent)):
            continue
        children[int(parent)].append(i)
    chains = 0
    for kids in children.values():
        if len(kids) >= 2:
            chains += len(kids)
    return {
        "jointCount": len(names),
        "names": names,
        "parents": [None if p is None or (isinstance(p, float) and np.isnan(p)) else int(p) for p in parents],
        "joints": joints.tolist(),
        "childCounts": [len(children[i]) for i in range(len(names))],
        "maxBranching": max((len(v) for v in children.values()), default=0),
        "chainCount": chains,
        "cls": data["cls"][()] if "cls" in data.files else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("extract", "skeleton", "skin", "all"), default="all")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument(
        "--seeds",
        type=str,
        default="",
        help="comma-separated skeleton seeds; archives each predict_skeleton.npz",
    )
    parser.add_argument("--faces-target-count", type=int, default=50000)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] if args.seeds else [args.seed]
    if not VENV_PY.is_file():
        raise FileNotFoundError(f"UniRig venv missing: {VENV_PY}")
    if not SRC_MESHY.is_file():
        raise FileNotFoundError(SRC_MESHY)

    sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
    from owned_rerig.write_unirig_input import write_unirig_yup_unskinned

    OUT.mkdir(parents=True, exist_ok=True)
    # UniRig join(npz_dir, input_without_suffix) breaks on absolute Windows paths.
    # Keep a short relative input under the UniRig clone.
    input_glb = UNIRIG / "examples" / "h3_angel_unskinned.glb"
    rel_input = "examples/h3_angel_unskinned.glb"
    npz_dir = OUT / "tmp"
    if args.stage in ("extract", "all"):
        meta = write_unirig_yup_unskinned(SRC_MESHY, input_glb)
        (OUT / "input.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        extract_npz(
            input_glb,
            npz_dir / "examples" / "h3_angel_unskinned" / "raw_data.npz",
            faces_target_count=args.faces_target_count,
        )
        print(f"wrote {npz_dir / 'examples' / 'h3_angel_unskinned' / 'raw_data.npz'}")

    if args.stage in ("skeleton", "all"):
        import shutil

        summaries = []
        for seed in seeds:
            _run(
                [
                    str(VENV_PY),
                    "run.py",
                    "--task=configs/task/angel_skeleton.yaml",
                    f"--seed={seed}",
                    f"--input={rel_input}",
                    f"--npz_dir={npz_dir}",
                    f"--output_dir={OUT / 'skeleton'}",
                ],
                cwd=UNIRIG,
            )
            src_npz = npz_dir / "examples" / "h3_angel_unskinned" / "predict_skeleton.npz"
            dest = OUT / "seeds" / str(seed)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_npz, dest / "predict_skeleton.npz")
            obj = src_npz.with_name("skeleton.obj")
            if obj.is_file():
                shutil.copy2(obj, dest / "skeleton.obj")
            summary = _summarize_skeleton(src_npz)
            summary["seed"] = seed
            (dest / "tree.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            summaries.append(summary)
            print(
                json.dumps(
                    {k: summary[k] for k in ("seed", "jointCount", "chainCount", "maxBranching")},
                    indent=2,
                )
            )
        (OUT / "seed_sweep.json").write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")

    if args.stage in ("skin", "all"):
        if len(seeds) != 1:
            raise ValueError("skin stage needs exactly one --seed (the chosen skeleton)")
        _run(
            [
                str(VENV_PY),
                "run.py",
                "--task=configs/task/angel_skin.yaml",
                f"--seed={seeds[0]}",
                f"--input={rel_input}",
                f"--npz_dir={npz_dir}",
                f"--output_dir={OUT / 'skin'}",
                "--data_name=predict_skeleton.npz",
            ],
            cwd=UNIRIG,
        )


if __name__ == "__main__":
    main()
