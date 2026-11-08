"""Geometry-led rest fitting for upright, Y-up, approximately T-posed bipeds.

Public API::

    fit_mesh_rest(positions, reference_heads, parents, names) -> {"heads": heads, ...metadata}

``positions`` is an (N, 3) surface point array in mesh coordinates; reference_heads
is (J, 3), parents is J parent indices (None or -1 for the root), and names is J
Mixamo-style names (an optional namespace before ':' is ignored). Returned heads
is float64 (J, 3), in the ORIGINAL mesh coordinates and original joint order.
All returned fields except heads are JSON serializable, including landmarks and timing.
Inputs are not modified. Units, translation and yaw need not match the reference.

Geometry determines the horizontal axis, arm elevation/endpoints, torso, leg
centerlines, crotch, and feet. The prior supplies chain length RATIOS for hidden
elbows/knees/spine joints and the left/right sign of an otherwise unsigned axis.
Left/right cannot be inferred uniquely from symmetric points. That sign still
needs a correctly labelled prior hemisphere (within 90 degrees of the mesh).
No skin weights, animation retargeting, or mesh changes are performed here.

Scope: separated legs and extended arms, not quadrupeds, seated figures, or
large wing/cape silhouettes. Clothing can hide the anatomical crotch; surface
landmarks are estimates, not semantic anatomy recognition. No learned models,
GPU, Blender, mesh-specific coordinates, or per-unit settings are required.

Run as a module for a JSON result and a three-view before/after overlay:
  py -3 -m owned_rerig.mesh_rest_fit --mesh M.glb --reference-bind B.glb --out-dir D
Run from tools/homm3_meshy_frame_pose (or put that directory on PYTHONPATH).
The diagnostic reuses the repo's owned-bind GLB reader, whose joint nodes are
translation-only. The array API itself has no GLB-format dependency.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.ndimage import median_filter


def _mid(points: np.ndarray) -> np.ndarray:
    """Trimmed envelope center, not a vertex-density-weighted centroid."""
    return np.quantile(points, (0.15, 0.85), axis=0).mean(axis=0)


def _section_width(points: np.ndarray) -> float:
    bounds = np.quantile(points, (0.15, 0.85), axis=0)
    return float(np.sum(bounds[1] - bounds[0]))


def _profile(points: np.ndarray, axis: int, samples: np.ndarray,
             half_width: float) -> np.ndarray:
    rows = []
    for value in samples:
        section = points[np.abs(points[:, axis] - value) <= half_width]
        if len(section) >= 5:
            center = _mid(section)
            center[axis] = value
            rows.append(center)
    if len(rows) < 3:
        raise ValueError("Insufficient surface samples for a limb centerline")
    curve = np.asarray(rows)
    for dim in range(3):
        if dim != axis:
            curve[:, dim] = median_filter(curve[:, dim], size=3, mode="nearest")
    return curve


def _at(curve: np.ndarray, axis: int, value: float) -> np.ndarray:
    order = np.argsort(curve[:, axis])
    out = np.array([np.interp(value, curve[order, axis], curve[order, d])
                    for d in range(3)])
    out[axis] = value
    return out


def fit_mesh_rest(
    positions: np.ndarray,
    reference_heads: np.ndarray,
    parents: Sequence[int | None],
    names: Sequence[str],
) -> dict[str, Any]:
    """Fit mesh-space biped heads; see module docstring for the exact contract."""
    started = time.perf_counter()
    points = np.asarray(positions, dtype=np.float64)
    prior = np.asarray(reference_heads, dtype=np.float64)
    labels = [str(n).rsplit(":", 1)[-1] for n in names]
    index = {n: i for i, n in enumerate(labels)}
    trunk = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"]
    arms = [s + n for s in ("Left", "Right")
            for n in ("Shoulder", "Arm", "ForeArm", "Hand")]
    legs = [s + n for s in ("Left", "Right")
            for n in ("UpLeg", "Leg", "Foot", "ToeBase", "Toe_End")]
    required = set(trunk + arms + legs)
    if (points.ndim != 2 or points.shape[1:] != (3,) or len(points) < 100
            or not np.isfinite(points).all()):
        raise ValueError("positions must contain at least 100 finite (N, 3) surface points")
    if (prior.shape != (len(labels), 3) or len(parents) != len(labels)
            or not np.isfinite(prior).all() or len(index) != len(labels)
            or set(labels) != required):
        raise ValueError("Expected the named 25-joint Mixamo biped topology and finite heads")
    expected = dict(zip(trunk[1:], trunk[:-1]))
    expected["Hips"] = None
    for side in ("Left", "Right"):
        for chain, root in ((["Shoulder", "Arm", "ForeArm", "Hand"], "Spine2"),
                            (["UpLeg", "Leg", "Foot", "ToeBase", "Toe_End"], "Hips")):
            for part in chain:
                expected[side + part] = root
                root = side + part
    for name, parent in zip(labels, parents):
        actual = None if parent is None or parent == -1 else (
            labels[parent] if isinstance(parent, (int, np.integer)) and 0 <= parent < len(labels)
            else "invalid")
        if actual != expected[name]:
            raise ValueError(f"Unexpected biped parent for {name}: {actual}")

    # Remove exporter seam duplicates before measuring orientation.
    points = np.unique(points, axis=0)
    bottom, top = np.quantile(points[:, 1], (0.005, 0.995))
    height = float(top - bottom)
    if height <= 1e-10:
        raise ValueError("Mesh has no upright extent")
    origin = np.array([np.median(points[:, 0]), bottom, np.median(points[:, 2])])
    normalized = (points - origin) / height
    cloud = normalized
    upper = cloud[(cloud[:, 1] > 0.55) & (cloud[:, 1] < 0.88)]
    if len(upper) < 30:
        raise ValueError("No upper-body surface for upright T-pose fit")
    _, eigenvectors = np.linalg.eigh(np.cov(upper[:, (0, 2)].T))
    side_axis = np.array([eigenvectors[0, -1], 0.0, eigenvectors[1, -1]])
    prior_side = prior[index["LeftUpLeg"]] - prior[index["RightUpLeg"]]
    if np.linalg.norm(prior_side[[0, 2]]) <= 1e-12:
        raise ValueError("Prior hip labels cannot resolve the left/right axis sign")
    if side_axis @ prior_side < 0:
        side_axis *= -1

    # Refine yaw from outer arm samples only; torso/backpack depth cannot pull it.
    for _ in range(2):
        lateral = upper @ side_axis
        center = float(np.quantile(lateral, (0.05, 0.95)).mean())
        outer = upper[np.abs(lateral - center) > 0.55 * np.quantile(np.abs(lateral - center), 0.95)]
        arm_y = float(np.median(outer[:, 1]))
        outer = outer[np.abs(outer[:, 1] - arm_y) < 0.055]
        if len(outer) < 20:
            raise ValueError("No bilateral extended-arm band")
        _, vec = np.linalg.eigh(np.cov(outer[:, (0, 2)].T))
        refined = np.array([vec[0, -1], 0.0, vec[1, -1]])
        side_axis = refined * (1 if refined @ side_axis >= 0 else -1)
    up = np.array([0.0, 1.0, 0.0])
    forward = np.cross(side_axis, up)
    basis = np.column_stack((side_axis, up, forward))
    p = cloud @ basis
    # Balance sampling only AFTER orientation. A world-axis voxel grid changes
    # which wrist section wins when an otherwise identical mesh is yaw-rotated.
    cells = np.floor((p - p.min(axis=0)) / 0.004).astype(np.int64)
    _, inverse = np.unique(cells, axis=0, return_inverse=True)
    counts = np.bincount(inverse)
    p = np.column_stack([np.bincount(inverse, weights=p[:, d]) / counts for d in range(3)])
    band = p[np.abs(p[:, 1] - arm_y) < 0.07]
    left_end, right_end = np.quantile(band[:, 0], (0.99, 0.01))
    body_x = float((left_end + right_end) * 0.5)
    p[:, 0] -= body_x
    left_end -= body_x
    right_end -= body_x
    span = float(left_end - right_end)
    if span < 0.6:
        raise ValueError("Surface is not a separated-arm T-pose biped")

    # Torso immediately below the armpits anchors shoulder width, not the prior.
    chest = p[(p[:, 1] > arm_y - 0.11) & (p[:, 1] < arm_y - 0.045)
              & (np.abs(p[:, 0]) < 0.3 * span)]
    if len(chest) < 15:
        raise ValueError("No torso surface below the arm band")
    chest_bounds = np.quantile(chest[:, 0], (0.08, 0.92))
    shoulder_x = {"Left": float(chest_bounds[1]), "Right": float(chest_bounds[0])}

    fitted = np.zeros_like(prior)
    def put(name: str, point: np.ndarray) -> None:
        fitted[index[name]] = point

    def length(a: str, b: str) -> float:
        return float(np.linalg.norm(prior[index[a]] - prior[index[b]]))

    def fraction(a: str, b: str, c: str) -> float:
        first, second = length(a, b), length(b, c)
        if min(first, second) <= 1e-12:
            raise ValueError(f"Zero-length reference proportion in {a}/{b}/{c}")
        return first / (first + second)

    curves: dict[str, np.ndarray] = {}
    for side, sign, end in (("Left", 1, left_end), ("Right", -1, right_end)):
        start = shoulder_x[side]
        arm = p[(sign * p[:, 0] > sign * start * 0.8)
                & (np.abs(p[:, 1] - arm_y) < 0.085)]
        curve = _profile(arm, 0, np.linspace(start, end, 32), 0.024)
        curves[side + "Arm"] = curve
        # A Mixamo Hand head is the wrist, not the fingertip. Detect its thin
        # cross-section in the distal arm; endpoint constraints are mesh-owned.
        wrist_samples = np.linspace(start + (end - start) * 0.68,
                                    start + (end - start) * 0.88, 14)
        widths = []
        for x in wrist_samples:
            section = arm[np.abs(arm[:, 0] - x) < 0.025]
            widths.append(_section_width(section[:, 1:])
                          if len(section) >= 5 else np.inf)
        wrist = float(wrist_samples[int(np.argmin(widths))])
        elbow = start + (wrist - start) * fraction(side + "Arm", side + "ForeArm", side + "Hand")
        put(side + "Arm", _at(curve, 0, start))
        put(side + "ForeArm", _at(curve, 0, elbow))
        put(side + "Hand", _at(curve, 0, wrist))

    # Detect the top of the persistent gap between legs. Gaps must occupy a
    # finite vertical run, so sparse triangles cannot turn one empty row into a crotch.
    lower = p[(p[:, 1] > 0.08) & (p[:, 1] < 0.28)]
    leg_seeds = {}
    for side, sign in (("Left", 1), ("Right", -1)):
        half = lower[sign * lower[:, 0] > 0]
        if len(half) < 10:
            raise ValueError("Two separated legs are required")
        leg_seeds[side] = _mid(half)
    separation = float(leg_seeds["Left"][0] - leg_seeds["Right"][0])
    if separation < 0.025:
        raise ValueError("Leg separation is not observable")
    slice_y = np.linspace(0.16, min(0.60, arm_y - 0.14), 48)
    gaps = []
    for y in slice_y:
        section = p[(np.abs(p[:, 1] - y) < 0.018)
                    & (np.abs(p[:, 0]) < separation * 0.85)]
        left, right = section[section[:, 0] > 0], section[section[:, 0] < 0]
        gap = (float(np.quantile(left[:, 0], 0.1) - np.quantile(right[:, 0], 0.9))
               if min(len(left), len(right)) >= 4 else 0.0)
        gaps.append(gap > separation * 0.24)
    runs = [i for i in range(2, len(gaps)) if all(gaps[i - 2:i + 1])]
    if not runs:
        raise ValueError("No persistent crotch gap; closed skirts are outside this fitter's scope")
    # Stop at the FIRST persistent closure above the shins. A torso shell can
    # have sparse central vertices too; it must not be mistaken for longer legs.
    closures = [i for i in range(runs[0] + 1, len(gaps) - 2) if not any(gaps[i:i + 3])]
    if not closures:
        raise ValueError("Leg gap never closes below the torso")
    crotch_y = float(slice_y[closures[0]])
    pelvis_y = crotch_y + 0.70 * separation
    hip_points = []
    for side, sign in (("Left", 1), ("Right", -1)):
        leg = p[(sign * p[:, 0] > 0) & (p[:, 1] < pelvis_y + 0.04)
                & (np.abs(p[:, 0] - leg_seeds[side][0]) < separation * 0.45)]
        curve = _profile(leg, 1, np.linspace(0.07, pelvis_y, 32), 0.022)
        curves[side + "Leg"] = curve
        hip = _at(curve, 1, pelvis_y)
        ankle = _at(curve, 1, 0.07)
        knee_y = pelvis_y + (ankle[1] - pelvis_y) * fraction(side + "UpLeg", side + "Leg", side + "Foot")
        put(side + "UpLeg", hip)
        put(side + "Leg", _at(curve, 1, knee_y))
        put(side + "Foot", ankle)
        hip_points.append(hip)
        foot = p[(sign * p[:, 0] > 0) & (p[:, 1] < 0.07)
                 & (np.abs(p[:, 0] - ankle[0]) < separation * 0.4)]
        if len(foot) < 5:
            raise ValueError("Foot surface not resolved")
        foot_center = _mid(foot)
        # Toe direction is inferred independently per foot from the extension
        # beyond the shin, so it does not inherit the prior's wrong yaw/depth.
        zlo, zhi = np.quantile(foot[:, 2], (0.05, 0.95))
        toe_z = zhi if zhi - ankle[2] >= ankle[2] - zlo else zlo
        toe = foot_center.copy()
        toe[2] = ankle[2] + 0.65 * (toe_z - ankle[2])
        put(side + "ToeBase", toe)
        toe = toe.copy()
        toe[2] = toe_z
        put(side + "Toe_End", toe)
    pelvis = np.mean(hip_points, axis=0)
    put("Hips", pelvis)

    # Neck is the narrow section between shoulder band and head mass.
    neck_rows = []
    for y in np.linspace(arm_y + 0.045, 0.90, 24):
        section = p[(np.abs(p[:, 1] - y) < 0.018)
                    & (np.abs(p[:, 0]) < 0.6 * separation)]
        if len(section) >= 8:
            width = np.diff(np.quantile(section[:, 0], (0.10, 0.90)))[0]
            neck_rows.append((width, y, _mid(section)))
    if not neck_rows:
        raise ValueError("Neck surface not resolved")
    _, neck_y, neck = min(neck_rows, key=lambda row: row[0])
    neck[1] = neck_y
    torso = p[(p[:, 1] >= pelvis_y - 0.03) & (p[:, 1] <= neck_y + 0.03)
              & (p[:, 0] > chest_bounds[0]) & (p[:, 0] < chest_bounds[1])]
    torso_curve = _profile(torso, 1, np.linspace(pelvis_y, neck_y, 26), 0.03)
    spine_lengths = np.array([length(a, b) for a, b in zip(trunk[:4], trunk[1:5])])
    spine_fractions = np.cumsum(spine_lengths) / spine_lengths.sum()
    for name, portion in zip(trunk[1:4], spine_fractions[:3]):
        put(name, _at(torso_curve, 1, pelvis_y + portion * (neck_y - pelvis_y)))
    put("Neck", neck)
    head_cloud = p[(p[:, 1] >= neck_y) & (np.abs(p[:, 0]) < separation)]
    head_curve = _profile(head_cloud, 1, np.linspace(neck_y, 0.99, 20), 0.025)
    head_y = neck_y + fraction("Neck", "Head", "HeadTop_End") * (0.99 - neck_y)
    put("Head", _at(head_curve, 1, head_y))
    put("HeadTop_End", _at(head_curve, 1, 0.99))
    for side in ("Left", "Right"):
        arm = fitted[index[side + "Arm"]]
        spine = fitted[index["Spine2"]]
        part = fraction("Spine2", side + "Shoulder", side + "Arm")
        put(side + "Shoulder", spine + part * (arm - spine))

    world_origin = origin + height * (basis @ np.array([body_x, 0.0, 0.0]))
    heads = fitted @ basis.T * height + world_origin
    prior_horizontal = prior_side.copy()
    prior_horizontal[1] = 0
    yaw_delta = np.degrees(np.arccos(np.clip(side_axis @ prior_horizontal / np.linalg.norm(prior_horizontal), -1, 1)))
    metadata = {
        "schema": "mesh_rest_fit.v1", "scope": "y_up_t_pose_biped_25_joint",
        "inputVertices": len(positions), "samplePoints": len(p),
        "meshHeight": height, "origin": world_origin.tolist(), "basis": basis.tolist(),
        "yawCorrectionDegrees": float(yaw_delta),
        "landmarksNormalized": {"armHeight": arm_y, "shoulderX": shoulder_x,
                                "crotchHeight": crotch_y, "pelvisHeight": pelvis_y,
                                "neckHeight": neck_y, "legSeparation": separation},
        "centerlines": {name: (curve @ basis.T * height + world_origin).tolist()
                        for name, curve in curves.items()},
        "priorUsage": ["named topology", "left/right hemisphere", "within-chain length ratios"],
        "limitations": ["not quadrupeds", "visible separated legs and extended arms required",
                        "clothing-derived crotch and hidden joint locations are estimates"],
        "fitSeconds": time.perf_counter() - started,
    }
    return {"heads": heads, **metadata}


def _main() -> None:
    import argparse
    import json
    from pathlib import Path

    from .glb_io import load_mesh
    from preview_exact_reference_bind import load_delivered_skeleton

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--reference-bind", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    mesh = load_mesh(args.mesh)
    ref = load_delivered_skeleton(args.reference_bind)
    result = fit_mesh_rest(mesh.positions, ref["heads"], ref["parents"], ref["names"])
    heads = result.pop("heads")
    meta = result
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {"mesh": str(args.mesh.resolve()), "referenceBind": str(args.reference_bind.resolve()),
              "names": ref["names"], "parents": ref["parents"], "heads": heads.tolist(), "fit": meta}
    (args.out_dir / "mesh_rest_fit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    basis = np.asarray(meta["basis"])
    origin = np.asarray(meta["origin"])
    verts = (mesh.positions - origin) @ basis
    before = (ref["heads"] - origin) @ basis
    after = (heads - origin) @ basis
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    for row, (joints, label, color) in enumerate(((before, "Before", "crimson"), (after, "Mesh fit", "#008b65"))):
        for col, (dims, title) in enumerate((((0, 1), "Front"), ((2, 1), "Side"), ((0, 2), "Top"))):
            ax = axes[row, col]
            xy = verts[:, dims]
            ax.add_collection(PolyCollection(xy[mesh.indices.reshape(-1, 3)], facecolors="0.78", edgecolors="none", alpha=0.28))
            for i, parent in enumerate(ref["parents"]):
                if parent is not None and parent >= 0:
                    ax.plot(joints[[parent, i], dims[0]], joints[[parent, i], dims[1]], color=color, lw=1.8)
            ax.scatter(joints[:, dims[0]], joints[:, dims[1]], c=color, s=12)
            all_points = np.concatenate((xy, before[:, dims], after[:, dims]))
            lo, hi = all_points.min(axis=0), all_points.max(axis=0)
            margin = meta["meshHeight"] * 0.04
            ax.set_xlim(lo[0] - margin, hi[0] + margin)
            ax.set_ylim(lo[1] - margin, hi[1] + margin)
            ax.set_aspect("equal")
            ax.set_title(f"{label}: {title} (shared mesh coordinates)")
            ax.grid(alpha=0.2)
    fig.suptitle(f"Geometry-led T-pose fit | {meta['fitSeconds']:.3f}s CPU | yaw correction {meta['yawCorrectionDegrees']:.2f} deg")
    fig.tight_layout()
    fig.savefig(args.out_dir / "mesh_rest_fit_overlay.png", dpi=140)
    plt.close(fig)
    print(json.dumps({"outDir": str(args.out_dir.resolve()),
                      **{k: v for k, v in meta.items() if k != "centerlines"}}, indent=2))


if __name__ == "__main__":
    _main()
