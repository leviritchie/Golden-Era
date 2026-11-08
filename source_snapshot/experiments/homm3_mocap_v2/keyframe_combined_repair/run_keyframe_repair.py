"""Run per-keyframe combined-score repair for one deployed unit.

Pipeline per unit (generated-artifact only):
1. Replay every deployed ``Unit_*.glb`` keyframe exactly (frozen motion).
2. Map clip frame *i* <-> DEF group plate *i* (install-side homm3_lab).
3. Register one frozen camera from the bind rest vs the idle plate.
4. Fit ONE shared ``TopologyWeightField`` (+ optional shared ``MeshField``
   rest) against ALL keyframes with the combined silhouette + chroma +
   dense-DINOv2 objective (``repair_keyframes.repair_weights``).
5. Re-score every keyframe (silhouette / chroma / DINOv2 / combined) before
   and after; write repaired ``candidate_weights.npz`` + ``repaired_mesh.npz``
   (rest), per-keyframe GIFs, and ``report.json``.

Nothing here touches delivery: no motion/bind/topology/UV/albedo edits, no
retiming, no export gating. The report pins every input hash.

Example:
  <venv-python> experiments/homm3_mocap_v2/keyframe_combined_repair/run_keyframe_repair.py
    --lab-sid h3_goblin
    --lab-root "V:/SteamLibrary/.../BepInEx/plugins/OfflineUnlockMod/homm3_lab"
    --out artifacts/homm3_mocap_v2/keyframe_combined_repair_v1
    --iterations 150 --seconds 600
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

HERE = Path(__file__).resolve().parent
# HERE is the module dir: parents[0]=homm3_mocap_v2, [1]=experiments, [2]=repo.
REPO = HERE.parents[2]
EXP = REPO / "experiments" / "homm3_mocap_v2"
# EXP first: sibling mocap modules win over HERE.
for _p in (str(HERE), str(REPO / "tools" / "homm3_silhouette_pose_fit")):
    if _p in sys.path:
        sys.path.remove(_p)
if str(EXP) not in sys.path:
    sys.path.insert(0, str(EXP))
sys.path.append(str(HERE))
sys.path.append(str(REPO / "tools" / "homm3_silhouette_pose_fit"))

from repair_contract import (  # noqa: E402
    APPROVED,
    CLIP_TO_GROUP,
    SCHEMA,
    deployed_clips,
    frame_metrics,
    resolve_plate_lookup,
)
from repair_keyframes import repair_weights  # noqa: E402
from replay_deployed import replay_clip  # noqa: E402

from audit_keyframes import _register_camera_from_idle, _shared_canvas_rgba  # noqa: E402
import audit_keyframes as audit_mod  # noqa: E402
from dino_embed import extract_subject_from_rgba  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from hybrid_dinov2 import DinoEncoder  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from skin_surface_constraints import SurfaceConstraints  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rescale_bbox_to_working_canvas(bbox, canvas_wh, resolution):
    """Rescale a source-canvas union bbox to the working-resolution canvas.

    The rescoring subjects are resized directly to (resolution, resolution)
    while union_alpha_bbox reports source-canvas pixels; pairing the raw bbox
    with that canvas crops empty. Mirrors the audit, which windows the resized
    clip: floor the min corner, ceil (+1, audit convention) the max corner,
    clamp to the canvas, and never return an empty box.
    """
    sx0, sy0, sx1, sy1 = (int(value) for value in bbox)
    canvas_w, canvas_h = int(canvas_wh[0]), int(canvas_wh[1])
    res = int(resolution)
    if canvas_w <= 0 or canvas_h <= 0 or res <= 0:
        raise ValueError("canvas and resolution must be positive")
    if sx1 <= sx0 or sy1 <= sy0:
        raise ValueError("source bbox is empty")
    rx0 = max(0, int(sx0 * res / canvas_w))
    ry0 = max(0, int(sy0 * res / canvas_h))
    rx1 = min(res, int(sx1 * res / canvas_w) + 1)
    ry1 = min(res, int(sy1 * res / canvas_h) + 1)
    rx1 = max(rx1, min(res, rx0 + 1))
    ry1 = max(ry1, min(res, ry0 + 1))
    if rx1 <= rx0 or ry1 <= ry0:
        raise ValueError("rescaled bbox is empty")
    return rx0, ry0, rx1, ry1


def run_unit(
    *,
    lab_sid: str,
    lab_root: Path,
    out_root: Path,
    resolution: int = 192,
    iterations: int = 150,
    seconds: float = 600.0,
    allow_mesh: bool = False,
    dino_weight: float = 2.0,
    photo_weight: float = 10.0,
    dino_batch: int = 8,
) -> dict[str, object]:
    started = time.perf_counter()
    unit_dir = APPROVED / lab_sid
    clips = deployed_clips(unit_dir)
    lookup = resolve_plate_lookup(lab_root, lab_sid)
    groups = lookup["groups"]
    if 2 not in groups:
        raise ValueError(f"{lab_sid}: no idle group 2 plates")
    idle_plate = groups[2][0]
    idle_canvas = Image.open(idle_plate).convert("RGBA").size

    out = out_root / lab_sid
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)

    # 1-2. Replay all keyframes; collect frozen motion + plate pairs.
    keyframes: list[dict[str, object]] = []
    names: list[str] = []
    for clip_path in clips:
        clip = clip_path.stem
        group = CLIP_TO_GROUP[clip]
        plates = groups.get(group)
        if not plates:
            raise ValueError(f"{lab_sid}: no plates for group {group}")
        replay = replay_clip(clip_path)
        skeleton = replay["skeleton"]
        names = list(skeleton.names)
        posed = np.asarray(replay["posed"])
        worlds = np.asarray(replay["worlds"])
        if len(posed) != len(plates):
            raise ValueError(f"{lab_sid} {clip}: {len(posed)} vs {len(plates)} plates")
        for frame in range(len(posed)):
            keyframes.append(
                {
                    "clip": clip,
                    "group": group,
                    "frame": frame,
                    "plate": plates[frame],
                    "world": worlds[frame],
                }
            )
    skeleton = replay_clip(clips[0])["skeleton"]
    rest = np.asarray(skeleton.vertices, dtype=np.float64)
    triangles = np.asarray(skeleton.triangles, dtype=np.int64)
    uvs = np.asarray(skeleton.uvs, dtype=np.float64)
    albedo = np.asarray(skeleton.albedo)
    inverse_bind = np.asarray(skeleton.inverse_bind, dtype=np.float64)
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int64)
    deployed_weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    deployed_weights = deployed_weights / np.maximum(
        deployed_weights.sum(axis=1, keepdims=True), 1e-8
    )
    # Position-welded seam duplicates in the deployed GLB carry slightly
    # divergent rows (1463/3251 coincident groups on h3_goblin, up to 0.04).
    # TopologyWeightField requires exact weld agreement, and the audit's
    # slot-based LBS replays the deployed rows verbatim. Reconcile by
    # averaging each position group: keeps the replayed silhouette identical
    # to <1e-3/vertex while giving the field one row per weld. The report
    # records the max drift so the baseline stays comparable.
    weld_mean = deployed_weights.copy()
    _weld_groups: dict[tuple[float, ...], list[int]] = {}
    for _i, _point in enumerate(rest):
        _weld_groups.setdefault(tuple(np.asarray(_point).tolist()), []).append(_i)
    weld_max_drift = 0.0
    for _rows in _weld_groups.values():
        if len(_rows) < 2:
            continue
        _mean = deployed_weights[_rows].mean(axis=0)
        weld_max_drift = max(
            weld_max_drift, float(np.abs(deployed_weights[_rows] - _mean).max())
        )
        weld_mean[_rows] = _mean
    deployed_weights = weld_mean / np.maximum(
        weld_mean.sum(axis=1, keepdims=True), 1e-8
    )

    # 3. One frozen camera from bind rest vs idle plate.
    audit_mod._TRIANGLES = np.asarray(skeleton.triangles, dtype=np.int64)
    camera, camera_report = _register_camera_from_idle(
        rest_vertices=rest, idle_plate=idle_plate, resolution=resolution
    )

    # Source targets on the shared canvas at working resolution.
    source_list: list[np.ndarray] = []
    for key in keyframes:
        rgba = _shared_canvas_rgba(key["plate"], idle_canvas)  # type: ignore[arg-type]
        small = np.asarray(
            Image.fromarray(rgba).resize(
                (resolution, resolution), Image.Resampling.LANCZOS
            ),
            dtype=np.float32,
        ) / 255.0
        source_list.append(small)
    source_stack = np.stack(source_list, axis=0)
    source_rgb = source_stack[..., :3] * source_stack[..., 3:4]
    source_alpha = source_stack[..., 3:4]
    source_distance = np.stack(
        [distance_transform_edt(a[..., 0] < 0.5) for a in source_alpha]
    ).astype(np.float32)

    joint_worlds = np.stack(
        [np.asarray(k["world"], dtype=np.float64) for k in keyframes], axis=0
    )

    # 4. Shared repair against ALL keyframes.
    result = repair_weights(
        rest_vertices=rest,
        triangles=triangles,
        uvs=uvs,
        albedo=albedo,
        initial_weights=deployed_weights,
        joint_slots=joints,
        joint_worlds=joint_worlds,
        inverse_bind=inverse_bind,
        camera=camera,
        source_rgb=np.asarray(source_rgb, dtype=np.float32),
        source_alpha=np.asarray(source_alpha, dtype=np.float32),
        source_distance=np.asarray(source_distance, dtype=np.float32),
        resolution=resolution,
        iterations=iterations,
        seconds=seconds,
        allow_mesh=allow_mesh,
        dino_weight=dino_weight,
        photo_weight=photo_weight,
        dino_batch=dino_batch,
    )
    learned = np.asarray(result["weights"], dtype=np.float64)
    learned_rest = np.asarray(result["rest"], dtype=np.float64)
    if learned.shape != deployed_weights.shape:
        raise ValueError("repaired weights changed the vertex/joint inventory")
    if not np.isfinite(learned).all() or np.any(learned < 0):
        raise ValueError("repaired weights must be finite and nonnegative")
    row_error = float(np.abs(learned.sum(axis=1) - 1.0).max())
    max_influences = int((learned > 1e-8).sum(axis=1).max())
    if row_error > 1e-5 or max_influences > 8:
        raise ValueError("repaired weights violate normalization/export limits")
    if np.any((deployed_weights <= 1e-8) & (learned > 1e-8)):
        raise ValueError("repair expanded support beyond deployed influences")
    np.savez_compressed(
        out / "candidate_weights.npz", weights=learned, names=np.asarray(names)
    )
    np.savez_compressed(
        out / "repaired_mesh.npz",
        vertices=learned_rest,
        triangles=triangles,
        uvs=uvs,
    )

    # 5. Re-score every keyframe before/after (silhouette/chroma/DINOv2).
    with cascade_batch_lock(REPO), torch.no_grad():
        encoder = DinoEncoder("cuda")
        renderer = SkinImageRenderer(triangles.astype(np.int32), uvs, albedo, camera, resolution)
        transforms = torch.as_tensor(
            joint_worlds @ inverse_bind[None], dtype=torch.float32, device="cuda"
        )
        # (dead rest_h/posed_* inputs removed with skin(); blend() builds its own.)
        # NOTE: a dead skin()/posed_* helper block was deleted here; blend()
        # below is the only rescoring path.
        # Blend with explicit rest per side (before=deployed rest, after=repaired rest).
        # NOTE: the pre-repair blend uses the weld-reconciled deployed rows
        # (max drift in weightContract.weldReconcileMaxDrift), not the raw GLB
        # rows: the repair optimizes the reconciled field, so before/after
        # compare the same representation. Raw-GLB replay parity is the
        # audit's job (audit.json), not this report's.
        def blend(weights_np: np.ndarray, rest_np: np.ndarray) -> torch.Tensor:
            weights_t = torch.as_tensor(weights_np, dtype=torch.float32, device="cuda")
            hom_t = torch.cat(
                (
                    torch.as_tensor(rest_np, dtype=torch.float32, device="cuda"),
                    torch.ones((len(rest_np), 1), dtype=torch.float32, device="cuda"),
                ),
                dim=1,
            )
            out_t = torch.zeros(
                (len(keyframes), len(rest_np), 3), dtype=torch.float32, device="cuda"
            )
            joints_t = torch.as_tensor(joints, device="cuda")
            for slot in range(joints_t.shape[1]):
                moved = torch.einsum(
                    "nvij,vj->nvi", transforms[:, joints_t[:, slot]], hom_t
                )[..., :3]
                out_t = out_t + weights_t[:, slot][None, :, None] * moved
            return out_t

        before_t = blend(deployed_weights, rest)
        after_t = blend(learned, learned_rest)
        rgb_before, alpha_before = renderer.render(before_t)
        rgb_after, alpha_after = renderer.render(after_t)
        rgba_before = np.zeros(
            (*rgb_before.shape[:3], 4), dtype=np.uint8
        )
        rgba_before[..., :3] = np.uint8(
            np.clip(rgb_before.detach().cpu().numpy(), 0.0, 1.0) * 255.0
        )
        rgba_before[..., 3] = np.uint8(
            np.clip(alpha_before.detach().cpu().numpy()[..., 0], 0.0, 1.0) * 255.0
        )
        rgba_after = np.zeros((*rgb_after.shape[:3], 4), dtype=np.uint8)
        rgba_after[..., :3] = np.uint8(
            np.clip(rgb_after.detach().cpu().numpy(), 0.0, 1.0) * 255.0
        )
        rgba_after[..., 3] = np.uint8(
            np.clip(alpha_after.detach().cpu().numpy()[..., 0], 0.0, 1.0) * 255.0
        )
        # DINO subjects share one clip-locked window per clip.
        from dino_embed import union_alpha_bbox

        rows: list[dict[str, object]] = []
        gif_frames: list[Image.Image] = []
        cursor = 0
        for clip_path in clips:
            clip = clip_path.stem
            count = sum(1 for k in keyframes if k["clip"] == clip)
            plates = [keyframes[cursor + i]["plate"] for i in range(count)]  # type: ignore[index]
            x0, y0, x1, y1 = rescale_bbox_to_working_canvas(
                union_alpha_bbox([Path(str(p)) for p in plates], canvas=idle_canvas), idle_canvas, resolution
            )
            window = {
                "policy": "clip_locked_union_alpha_aabb",
                "paddingRatio": 0.1,
                "bg": [1.0, 1.0, 1.0],
                "bboxXyxy": [x0, y0, x1, y1],
                "bboxWh": [x1 - x0, y1 - y0],
                "canvas": [resolution, resolution],
                "rmbg": False,
                "perFrameCrop": False,
            }
            src_small = np.stack(
                [
                    np.asarray(
                        Image.fromarray(
                            _shared_canvas_rgba(p, idle_canvas)  # type: ignore[arg-type]
                        ).resize(
                            (resolution, resolution), Image.Resampling.LANCZOS
                        ),
                        dtype=np.uint8,
                    )
                    for p in plates
                ],
                axis=0,
            )
            src_subjects = [extract_subject_from_rgba(s, window) for s in src_small]
            before_subjects = [
                extract_subject_from_rgba(rgba_before[cursor + i], window)
                for i in range(count)
            ]
            after_subjects = [
                extract_subject_from_rgba(rgba_after[cursor + i], window)
                for i in range(count)
            ]
            src_embeds = np.concatenate(
                [
                    encoder.encode_rgb(src_subjects[i : i + dino_batch])
                    for i in range(0, count, dino_batch)
                ],
                axis=0,
            )
            before_embeds = np.concatenate(
                [
                    encoder.encode_rgb(before_subjects[i : i + dino_batch])
                    for i in range(0, count, dino_batch)
                ],
                axis=0,
            )
            after_embeds = np.concatenate(
                [
                    encoder.encode_rgb(after_subjects[i : i + dino_batch])
                    for i in range(0, count, dino_batch)
                ],
                axis=0,
            )
            for i in range(count):
                key = keyframes[cursor + i]
                before_m = frame_metrics(
                    src_small[i], rgba_before[cursor + i], src_embeds[i], before_embeds[i]
                )
                after_m = frame_metrics(
                    src_small[i], rgba_after[cursor + i], src_embeds[i], after_embeds[i]
                )
                rows.append(
                    {
                        "clip": clip,
                        "group": key["group"],
                        "frame": key["frame"],
                        "plate": str(key["plate"]),
                        "before": before_m,
                        "after": after_m,
                        "delta": float(after_m["score"] - before_m["score"]),
                    }
                )
                panel = Image.new("RGB", (resolution * 4, resolution + 30), (10, 10, 14))
                draw = ImageDraw.Draw(panel)
                draw.text(
                    (4, 5),
                    f"{lab_sid} {clip} f{key['frame']:02d} "
                    f"{before_m['score']:.3f}->{after_m['score']:.3f}",
                    fill="white",
                )
                for col, label, image in (
                    (0, "source", src_small[i]),
                    (1, f"before {before_m['score']:.3f}", rgba_before[cursor + i]),
                    (2, f"after {after_m['score']:.3f}", rgba_after[cursor + i]),
                    (3, f"delta {after_m['score'] - before_m['score']:+.3f}", rgba_after[cursor + i]),
                ):
                    rgb_panel = image[..., :3].astype(np.float32) / 255.0
                    panel.paste(
                        Image.fromarray(np.uint8(rgb_panel * 255.0)),
                        (col * resolution, 30),
                    )
                    draw.text((col * resolution + 4, 17), label, fill=(190, 190, 205))
                gif_frames.append(panel)
            cursor += count

        surface = SurfaceConstraints(rest, triangles, device="cuda")
        before_surface = surface.metrics(before_t)
        after_surface = surface.metrics(after_t)

    before_scores = np.asarray([float(r["before"]["score"]) for r in rows])  # type: ignore[index]
    after_scores = np.asarray([float(r["after"]["score"]) for r in rows])  # type: ignore[index]
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact repair; deployed motion replayed exactly; shared weight (+optional rest) fit against all keyframes",
        "labSid": lab_sid,
        "dinoModel": "facebook/dinov2-large",
        "scoring": {
            "components": ["silhouetteIoU", "lumaNormalizedChromaQuality", "normalizedDinoV2Cosine"],
            "composite": "equal_mean",
        },
        "objective": {
            "photoWeight": float(photo_weight),
            "surfaceWeight": 3.0,
            "weightPriorWeight": 25.0,
            "dinoWeight": float(dino_weight),
            "allowMesh": bool(allow_mesh),
            "iterations": int(iterations),
            "secondsBudget": float(seconds),
            "resolution": int(resolution),
            "dinoBatch": int(dino_batch),
            "dinoPolicy": "rotating_shard_full_photo",
        },
        "camera": camera,
        "cameraReport": camera_report,
        "frameCount": len(rows),
        "beforeMean": float(before_scores.mean()),
        "afterMean": float(after_scores.mean()),
        "meanDelta": float((after_scores - before_scores).mean()),
        "improvedFraction": float((after_scores > before_scores).mean()),
        "weightContract": {
            "normalizationMaxError": row_error,
            "maxInfluences": max_influences,
            "supportExpanded": False,
            "weldReconcileMaxDrift": float(weld_max_drift),
        },
        "surface": {"before": before_surface, "after": after_surface},
        "history": result["history"],
        "elapsedSeconds": time.perf_counter() - started,
        "frames": rows,
        "inputs": {
            "clips": [
                {"clip": p.stem, "path": str(p), "sha256": _sha256(p)} for p in clips
            ],
            "defJson": str(lookup["defJson"]),
            "candidateWeights": str((out / "candidate_weights.npz").resolve()),
            "repairedMesh": str((out / "repaired_mesh.npz").resolve()),
        },
        "notDelivery": "motion, bind, topology, UVs, albedo, timing unchanged; per-frame correctives not exported",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    gif = out / f"{lab_sid}_repair.gif"
    gif_frames[0].save(gif, save_all=True, append_images=gif_frames[1:], duration=180, loop=0)
    contact = out / f"{lab_sid}_repair_contact.png"
    sheet = Image.new(
        "RGB", (gif_frames[0].width, gif_frames[0].height * min(12, len(gif_frames)))
    )
    step = max(1, len(gif_frames) // 12)
    for i, image in enumerate(gif_frames[::step][:12]):
        sheet.paste(image, (0, i * gif_frames[0].height))
    sheet.save(contact)
    print(
        json.dumps(
            {
                "ok": True,
                "labSid": lab_sid,
                "frames": len(rows),
                "beforeMean": report["beforeMean"],
                "afterMean": report["afterMean"],
                "gif": str(gif),
            },
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-sid", required=True)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--allow-mesh", action="store_true")
    parser.add_argument("--dino-weight", type=float, default=2.0)
    parser.add_argument("--photo-weight", type=float, default=10.0)
    parser.add_argument("--dino-batch", type=int, default=8)
    args = parser.parse_args()
    run_unit(
        lab_sid=args.lab_sid,
        lab_root=args.lab_root.resolve(),
        out_root=args.out.resolve(),
        resolution=args.resolution,
        iterations=args.iterations,
        seconds=args.seconds,
        allow_mesh=args.allow_mesh,
        dino_weight=args.dino_weight,
        photo_weight=args.photo_weight,
        dino_batch=args.dino_batch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
