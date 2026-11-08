#!/usr/bin/env python3
"""Append a deliberately authored rigid prop to an existing owned bind.

This is a generated-artifact diagnostic for the case where a source sprite shows a moving
weapon but no clean 3D prop source exists.  The prop is a small low-poly axe-like control
whose grip is placed at a named hand head and whose vertices are weighted 100% to that
hand.  It is intentionally not a delivery exporter: the caller must inspect the saved
replay before treating the experiment as useful evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.glb_io import load_mesh, load_render_surface, write_skinned_mesh  # noqa: E402
from preview_exact_reference_bind import load_delivered_skeleton  # noqa: E402


def _unit(value: np.ndarray, label: str) -> np.ndarray:
    value = np.asarray(value, dtype=np.float64)
    length = float(np.linalg.norm(value))
    if length <= 1e-12 or not np.isfinite(length):
        raise ValueError(f"{label} must be finite and nonzero")
    return value / length


def _basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis = _unit(axis, "axis")
    reference = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    if abs(float(np.dot(axis, reference))) > 0.92:
        reference = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    lateral = _unit(np.cross(reference, axis), "lateral")
    depth = _unit(np.cross(axis, lateral), "depth")
    return axis, lateral, depth


def _append_box(
    vertices: list[np.ndarray], faces: list[tuple[int, int, int]],
    center_a: np.ndarray, center_b: np.ndarray,
    lateral: np.ndarray, depth: np.ndarray, half_width: float, half_depth: float,
) -> None:
    """Append a prism whose long axis is center_a -> center_b."""
    start = len(vertices)
    for center in (center_a, center_b):
        for side, thick in ((-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)):
            vertices.append(center + side * half_width * lateral + thick * half_depth * depth)
    faces.extend(
        (
            (start + 0, start + 1, start + 2), (start + 0, start + 2, start + 3),
            (start + 4, start + 6, start + 5), (start + 4, start + 7, start + 6),
            (start + 0, start + 4, start + 5), (start + 0, start + 5, start + 1),
            (start + 1, start + 5, start + 6), (start + 1, start + 6, start + 2),
            (start + 2, start + 6, start + 7), (start + 2, start + 7, start + 3),
            (start + 3, start + 7, start + 4), (start + 3, start + 4, start + 0),
        )
    )


def _build_axe(origin: np.ndarray, axis: np.ndarray, length: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis, lateral, depth = _basis(axis)
    if length <= 0.0 or not np.isfinite(length):
        raise ValueError("length must be positive and finite")
    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []

    shaft_end = origin + axis * (length * 0.78)
    ring_count = 8
    ring_radius = length * 0.027
    for center in (origin, shaft_end):
        for index in range(ring_count):
            angle = 2.0 * np.pi * index / ring_count
            vertices.append(center + ring_radius * (np.cos(angle) * lateral + np.sin(angle) * depth))
    for index in range(ring_count):
        nxt = (index + 1) % ring_count
        faces.extend(
            (
                (index, nxt, ring_count + nxt),
                (index, ring_count + nxt, ring_count + index),
            )
        )
    start_center = len(vertices)
    vertices.append(origin)
    end_center = len(vertices)
    vertices.append(shaft_end)
    for index in range(ring_count):
        nxt = (index + 1) % ring_count
        faces.append((start_center, nxt, index))
        faces.append((end_center, ring_count + index, ring_count + nxt))

    blade_start = origin + axis * (length * 0.60)
    blade_end = origin + axis * (length * 0.91)
    _append_box(
        vertices, faces, blade_start, blade_end, lateral, depth,
        half_width=length * 0.13, half_depth=length * 0.035,
    )
    positions = np.asarray(vertices, dtype=np.float64)
    indices = np.asarray(faces, dtype=np.int64).reshape(-1)
    normals = np.zeros_like(positions)
    triangles = indices.reshape(-1, 3)
    for tri in triangles:
        a, b, c = positions[tri]
        normal = np.cross(b - a, c - a)
        norm = float(np.linalg.norm(normal))
        if norm > 1e-12:
            normals[tri] += normal / norm
    norms = np.linalg.norm(normals, axis=1)
    normals = normals / np.maximum(norms[:, None], 1e-12)
    return positions, indices, normals


def _texture_uv(texture: np.ndarray, predicate, fallback: tuple[float, float]) -> tuple[float, float]:
    rows, cols = np.nonzero(predicate(texture))
    if not len(rows):
        return fallback
    row = int(rows[len(rows) // 2])
    col = int(cols[len(cols) // 2])
    return (col / max(texture.shape[1] - 1, 1), row / max(texture.shape[0] - 1, 1))


def _uvs_for_prop(texture: np.ndarray, prop_count: int, shaft_count: int) -> np.ndarray:
    texture = np.asarray(texture, dtype=np.uint8)
    brown = _texture_uv(
        texture,
        lambda value: (value[:, :, 0] > value[:, :, 1] * 1.05)
        & (value[:, :, 1] > value[:, :, 2] * 1.08)
        & (value[:, :, 0] > 35),
        (0.5, 0.5),
    )
    silver = _texture_uv(
        texture,
        lambda value: (value.max(axis=2) - value.min(axis=2) < 18)
        & (value.mean(axis=2) > 105),
        brown,
    )
    result = np.repeat(np.asarray(brown, dtype=np.float32)[None, :], prop_count, axis=0)
    result[shaft_count:] = np.asarray(silver, dtype=np.float32)
    return result


def build(args: argparse.Namespace) -> dict:
    bind = args.bind.resolve()
    report_path = args.bind_report.resolve()
    output = args.output.resolve()
    output_report = args.output_report.resolve()
    body = load_mesh(bind)
    surface = load_render_surface(bind)
    skeleton = load_delivered_skeleton(bind)
    if not np.allclose(body.positions, surface["positions"], atol=1e-6):
        raise ValueError("bind mesh and render surface positions disagree")
    if body.joints is None or body.weights is None:
        raise ValueError("bind has no skin")
    if args.bone not in skeleton["names"]:
        raise ValueError(f"bone not found: {args.bone}")
    bone = skeleton["names"].index(args.bone)
    parent = skeleton["parents"][bone]
    if parent is None:
        raise ValueError("the prop bone must have a parent so its outward axis is defined")
    origin = np.asarray(skeleton["heads"][bone], dtype=np.float64)
    axis = _unit(origin - np.asarray(skeleton["heads"][parent], dtype=np.float64), "hand axis")
    axis *= int(args.axis_sign)
    prop_positions, prop_indices, prop_normals = _build_axe(origin, axis, float(args.length))
    shaft_count = 18
    prop_uvs = _uvs_for_prop(surface["baseColor"], len(prop_positions), shaft_count)

    positions = np.concatenate((body.positions, prop_positions), axis=0)
    indices = np.concatenate((body.indices, prop_indices + len(body.positions)), axis=0)
    joints = np.zeros((len(positions), 4), dtype=np.int32)
    weights = np.zeros((len(positions), 4), dtype=np.float64)
    joints[: len(body.joints)] = body.joints
    weights[: len(body.weights)] = body.weights
    joints[len(body.joints):, 0] = bone
    weights[len(body.weights):, 0] = 1.0
    normals = np.concatenate((np.asarray(surface["normals"], dtype=np.float64), prop_normals), axis=0)
    uvs = np.concatenate((np.asarray(surface["uvs"], dtype=np.float64), prop_uvs), axis=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_skinned_mesh(
        output,
        positions=positions,
        indices=indices,
        bone_names=skeleton["names"],
        parents=skeleton["parents"],
        heads=skeleton["heads"],
        joints=joints,
        weights=weights,
        source_glb=bind,
        uvs=uvs,
        normals=normals,
        extras={
            "schema": "homm3.rigid-prop-diagnostic.v1",
            "proof": "generated-artifact diagnostic only",
            "prop": "authored_low_poly_axe_control",
            "bone": args.bone,
            "axisSign": int(args.axis_sign),
            "propVertices": int(len(prop_positions)),
            "propFaces": int(len(prop_indices) // 3),
            "policy": "100 percent rigid ownership to the named hand; not delivery proof",
        },
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["vertexCount"] = int(len(positions))
    report["propDiagnostic"] = {
        "schema": "homm3.rigid-prop-diagnostic.v1",
        "prop": "authored_low_poly_axe_control",
        "bone": args.bone,
        "vertices": int(len(prop_positions)),
        "length": float(args.length),
        "policy": "generated-artifact diagnostic only; no candidate promotion",
    }
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {
        "bind": str(bind).replace("\\", "/"),
        "output": str(output).replace("\\", "/"),
        "report": str(output_report).replace("\\", "/"),
        "bone": args.bone,
        "axisSign": int(args.axis_sign),
        "propVertices": int(len(prop_positions)),
        "propFaces": int(len(prop_indices) // 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--bind-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--bone", default="RightHand")
    parser.add_argument("--length", type=float, default=0.62)
    parser.add_argument("--axis-sign", type=int, choices=(-1, 1), default=1)
    args = parser.parse_args()
    if args.length <= 0.0:
        parser.error("--length must be positive")
    print(json.dumps(build(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
