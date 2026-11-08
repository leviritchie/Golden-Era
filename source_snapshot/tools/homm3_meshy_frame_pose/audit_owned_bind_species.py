#!/usr/bin/env python3
"""Audit an owned species bind and write the horse-leg rotate proof."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.audit import audit_owned_bind, lbs_delta_after_bone_rotate  # noqa: E402
from owned_rerig.glb_io import load_mesh  # noqa: E402
from owned_rerig.species import load_species_template  # noqa: E402


def _ppm(path: Path, points: np.ndarray, color: tuple[int, int, int], size: int = 256) -> None:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = (12, 12, 16)
    xy = points[:, [0, 2]]
    lo = xy.min(axis=0)
    hi = xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    uv = (xy - lo) / span
    px = np.clip((uv[:, 0] * (size - 3) + 1).astype(int), 0, size - 1)
    py = np.clip(((1.0 - uv[:, 1]) * (size - 3) + 1).astype(int), 0, size - 1)
    img[py, px] = color
    header = f"P6\n{size} {size}\n255\n".encode("ascii")
    path.write_bytes(header + img.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--labels", type=Path, help="JSON from apply_part_map.py")
    parser.add_argument("--species", default="rider_mount")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    mesh = load_mesh(args.master)
    if mesh.joints is None or mesh.weights is None:
        raise SystemExit("master GLB is not skinned")
    template = load_species_template(args.species)
    if args.labels:
        labels = np.asarray(json.loads(args.labels.read_text(encoding="utf-8"))["labels"], dtype=np.int32)
    else:
        raise SystemExit("part labels JSON is required; refusing to invent a height cut")
    heads = []
    # Approximate rest heads from inverse bind translation column if present.
    if mesh.inverse_bind is None:
        raise SystemExit("master missing inverse bind matrices")
    for ibm in mesh.inverse_bind:
        world = np.linalg.inv(ibm)
        heads.append(world[:3, 3])
    heads_arr = np.asarray(heads, dtype=np.float64)
    parents: list[int | None] = []
    # Parent list is not stored in GLB extras reliably; audit still checks walls via template names.
    names = [mesh.node_names[i] for i in mesh.skin_joints]
    name_index = {n: i for i, n in enumerate(names)}
    for bone in template["bones"]:
        parent = bone.get("parent")
        parents.append(None if parent is None else name_index.get(str(parent)))
    report = audit_owned_bind(
        template=template,
        bone_names=names,
        positions=mesh.positions,
        labels=labels,
        joints=mesh.joints,
        weights=mesh.weights,
        heads=heads_arr,
        parents=parents,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    (args.out / "owned_bind_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bone = "HorseLeftShoulder"
    if bone in name_index:
        delta = lbs_delta_after_bone_rotate(
            mesh.positions,
            mesh.joints,
            mesh.weights,
            heads_arr,
            parents,
            name_index[bone],
            np.array([1.0, 0.0, 0.0]),
            float(np.deg2rad(30.0)),
        )
        _ppm(args.out / "leg_rotate_rest.ppm", mesh.positions, (180, 180, 190))
        _ppm(args.out / "leg_rotate_posed.ppm", mesh.positions + delta, (220, 80, 80))
    print(json.dumps({"ok": report["ok"], "issues": report["issues"]}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
