#!/usr/bin/env python3
"""Batch diagnostic preview for Stronghold units.

Each unit is rendered with its prepared bind and, when available, the fitted
all-frame candidate saved by the existing skin pilot.  The higher-scoring
candidate is kept even when a compatibility gate fails; the report marks those
frames so this remains a review preview rather than delivery proof.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))
from glb_skeleton import load_bind_skeleton  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from hybrid_dinov2 import DinoEncoder  # noqa: E402
from reconstruct_ab import compute_rest_joints, reconstruct_ab  # noqa: E402
from run_skin_weight_pilot import shared_canvas_source_images, skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
import preview_per_frame_mesh_selection as selector  # noqa: E402


def load_render_skin(path: Path) -> dict[str, Any]:
    skeleton = load_bind_skeleton(path)
    if skeleton.inverse_bind is None:
        raise RuntimeError(f"{path} is missing inverse bind matrices")
    sparse = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int64)
    weights = np.zeros((len(skeleton.vertices), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        valid = sparse[:, slot] > 1e-8
        weights[np.arange(len(weights))[valid], joints[valid, slot]] += sparse[valid, slot]
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    return {
        "vertices": np.asarray(skeleton.vertices, dtype=np.float64),
        "triangles": np.asarray(skeleton.triangles, dtype=np.int64),
        "uvs": np.asarray(skeleton.uvs, dtype=np.float64),
        "albedo": np.asarray(skeleton.albedo),
        "names": list(skeleton.names),
        "parents": np.asarray(skeleton.parents, dtype=np.int64),
        "offsets": np.asarray(skeleton.rest_local_translation, dtype=np.float64),
        "inverseBind": np.asarray(skeleton.inverse_bind, dtype=np.float64),
        "weights": weights,
    }


def candidate_skin(base: dict[str, Any], npz_path: Path | None) -> tuple[dict[str, Any], str]:
    if npz_path is None or not npz_path.exists():
        return copy.deepcopy(base), "prepared_bind_only"
    raw = np.load(npz_path, allow_pickle=False)
    names = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in np.asarray(raw["names"]).tolist()]
    if sorted(names) != sorted(base["names"]):
        raise ValueError(f"candidate joint set does not match prepared bind: {npz_path}")
    order = np.asarray([names.index(name) for name in base["names"]], dtype=np.int64)
    vertices = np.asarray(raw["vertices"], dtype=np.float64)
    weights = np.asarray(raw["weights"], dtype=np.float64)[:, order]
    if vertices.shape != base["vertices"].shape or weights.shape != base["weights"].shape:
        raise ValueError(f"candidate dimensions do not match prepared bind: {npz_path}")
    result = copy.deepcopy(base)
    result["vertices"] = vertices
    result["weights"] = weights
    return result, "all_def_candidate"


def skin_render(skin: dict[str, Any], positions: np.ndarray, camera: dict[str, Any], resolution: int):
    ab = reconstruct_ab(capture_positions=positions, offsets=skin["offsets"], parents=skin["parents"], reference_frame=0)
    worlds = np.asarray(ab["jointWorldA"], dtype=np.float64)
    with cascade_batch_lock(REPO), torch.no_grad():
        transforms = torch.as_tensor(worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"]))),), dtype=torch.float32, device="cuda")
        candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest)
        posed = skin_with(candidates, torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda"))
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, alpha = renderer.render(posed)
        posed_np = posed.detach().cpu().numpy()
        rgb_np = rgb.detach().cpu().numpy()
        alpha_np = alpha.detach().cpu().numpy()
    rgba = np.zeros((*rgb_np.shape[:3], 4), dtype=np.uint8)
    rgba[..., :3] = np.uint8(np.clip(rgb_np, 0.0, 1.0) * 255.0)
    rgba[..., 3] = np.uint8(np.clip(alpha_np[..., 0], 0.0, 1.0) * 255.0)
    return rgba, selector.deformation_health(skin, posed_np)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, default=REPO / "experiments/homm3_mocap_v2/stronghold_animation_status.json")
    parser.add_argument("--out", type=Path, default=REPO / "artifacts/homm3_mocap_v2/stronghold_best_candidate_v1")
    parser.add_argument("--clips", default="g00_move,g02_idle", help="comma-separated corpus clip keys")
    parser.add_argument("--resolution", type=int, default=160)
    parser.add_argument("--max-units", type=int, default=0)
    args = parser.parse_args()
    status = json.loads(args.status.read_text(encoding="utf-8"))
    requested = [x.strip() for x in args.clips.split(",") if x.strip()]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    encoder = DinoEncoder("cuda")
    units = status["units"][: args.max_units or None]
    batch_rows: list[dict[str, Any]] = []
    for unit in units:
        name, sid = str(unit["name"]), str(unit["sid"])
        corpus_path = Path(unit["corpus"]) if unit.get("corpus") else None
        if not unit.get("mesh") or corpus_path is None or not corpus_path.is_file() or not unit.get("fit"):
            batch_rows.append({"name": name, "sid": sid, "status": "skipped_mesh_or_corpus_unresolved"})
            continue
        fit_dir = Path(unit["fit"]).parent
        move_glb = fit_dir / "g00_move_candidate.glb"
        idle_glb = fit_dir / "g02_idle_candidate.glb"
        if not move_glb.exists() or not idle_glb.exists():
            batch_rows.append({"name": name, "sid": sid, "status": "skipped_candidate_bind_missing"})
            continue
        base = load_render_skin(move_glb); candidate = load_render_skin(idle_glb); candidate_kind = "all_def_move_idle_candidate_glbs"
        if sorted(base["names"]) != sorted(candidate["names"]):
            batch_rows.append({"name": name, "sid": sid, "status": "skipped_candidate_joint_set_mismatch"})
            continue
        if base["vertices"].shape != candidate["vertices"].shape:
            batch_rows.append({"name": name, "sid": sid, "status": "skipped_candidate_topology_mismatch"})
            continue
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        entries = {str(item["key"]): item for item in corpus["captures"]}
        camera_path = fit_dir / "camera.json"
        if not camera_path.exists():
            batch_rows.append({"name": name, "sid": sid, "status": "skipped_camera_missing"})
            continue
        camera = selector.common_camera(json.loads(camera_path.read_text(encoding="utf-8")), args.resolution)
        unit_out = out / sid; unit_out.mkdir(parents=True, exist_ok=True)
        frames: list[Image.Image] = []; rows: list[dict[str, Any]] = []
        for key in requested:
            if key not in entries:
                continue
            entry = entries[key]; paths = [Path(p) for p in entry["frames"]]
            source_targets, _, _ = shared_canvas_source_images(paths, args.resolution)
            source_rgb = source_targets[0].detach().cpu().numpy(); source_alpha = source_targets[1].detach().cpu().numpy()
            sources = np.zeros((*source_rgb.shape[:3], 4), dtype=np.uint8)
            sources[..., :3] = np.uint8(np.clip(source_rgb, 0, 1) * 255); sources[..., 3] = np.uint8(np.clip(source_alpha[..., 0], 0, 1) * 255)
            window = selector.clip_window(sources, args.resolution)
            source_embeddings = selector.encode_subjects(encoder, sources, window, 8)
            capture = np.load(Path(entry["capture"]), allow_pickle=False); capture_dict = {k: capture[k] for k in capture.files}
            indices = [int(i) for i in entry["sourceIndices"]]
            names = [str(x) for x in capture_dict["joint_names"]]
            order = np.asarray([names.index(n) for n in base["names"]], dtype=np.int64)
            positions = np.asarray(capture_dict["pred_position"], dtype=np.float64)[:, order]
            base_pos = positions.copy(); cand_pos = positions.copy()
            base_all, base_health_all = skin_render(base, base_pos, camera, args.resolution)
            cand_all, cand_health_all = skin_render(candidate, cand_pos, camera, args.resolution)
            base_rgba, base_health = base_all[np.asarray(indices)], [base_health_all[i] for i in indices]
            cand_rgba, cand_health = cand_all[np.asarray(indices)], [cand_health_all[i] for i in indices]
            base_emb = selector.encode_subjects(encoder, list(base_rgba), window, 8); cand_emb = selector.encode_subjects(encoder, list(cand_rgba), window, 8)
            for frame, (source, prepared, fitted) in enumerate(zip(sources, base_rgba, cand_rgba)):
                ratio = selector.wing_span_torso_ratio(source)
                a = selector.frame_metrics(source, prepared, source_embeddings[frame], base_emb[frame], ratio, base_health[frame])
                b = selector.frame_metrics(source, fitted, source_embeddings[frame], cand_emb[frame], ratio, cand_health[frame])
                for score in (a, b):
                    rel_shape = abs(score["wingSpanTorsoRatio"] - ratio) / max(ratio, 1e-9)
                    rel_aspect = abs(score["projectedBBoxAspect"] - score["sourceProjectedBBoxAspect"]) / max(score["sourceProjectedBBoxAspect"], 1e-9)
                    score["shapeCompatibility"] = rel_shape <= 0.25
                    score["bboxAspectCompatibility"] = rel_aspect <= 0.50
                    h = score["deformationHealth"]
                    score["deformationCompatibility"] = h["edgeRatioQ01"] >= 0.30 and h["edgeRatioQ99"] <= 5.00 and h["edgeExtremeFraction"] <= 0.08
                winner = "prepared" if a["score"] >= b["score"] else "candidate"; selected = prepared if winner == "prepared" else fitted
                override = not ((a["shapeCompatibility"] and a["bboxAspectCompatibility"] and a["deformationCompatibility"]) if winner == "prepared" else (b["shapeCompatibility"] and b["bboxAspectCompatibility"] and b["deformationCompatibility"]))
                rows.append({"clip": key, "frame": frame, "winner": winner, "selectionGateOverride": bool(override), "preparedScore": a["score"], "candidateScore": b["score"]})
                panel = Image.new("RGB", (args.resolution * 4, args.resolution + 28), (10, 10, 14)); draw = ImageDraw.Draw(panel)
                draw.text((4, 4), f"{sid} {key} f{frame:02d} winner={winner}{'*' if override else ''}", fill="white")
                for col, label, image in ((0, "source", source), (1, f"prepared {a['score']:.3f}", prepared), (2, f"candidate {b['score']:.3f}", fitted), (3, f"selected {winner}", selected)):
                    panel.paste(Image.fromarray(image[..., :3]), (col * args.resolution, 28)); draw.text((col * args.resolution + 4, 16), label, fill=(190, 190, 205))
                frames.append(panel)
        if frames:
            gif = unit_out / f"{sid}_best_candidate.gif"; frames[0].save(gif, save_all=True, append_images=frames[1:], duration=85, loop=0)
            contact = unit_out / f"{sid}_best_candidate_contact.png"; step = max(1, len(frames) // 8); sheet = Image.new("RGB", (frames[0].width, frames[0].height * min(8, len(frames[::step]))))
            for i, image in enumerate(frames[::step][:8]): sheet.paste(image, (0, i * frames[0].height))
            sheet.save(contact)
            batch_rows.append({"name": name, "sid": sid, "status": "previewed", "candidate": candidate_kind, "gif": str(gif), "contact": str(contact), "frames": rows, "winnerCounts": {x: sum(r["winner"] == x for r in rows) for x in ("prepared", "candidate")}, "gateOverrideFrames": sum(bool(r["selectionGateOverride"]) for r in rows)})
    (out / "batch_report.json").write_text(json.dumps({"proof": "generated-candidate visual preview", "selectionPolicy": "best_score_even_if_gated", "clips": requested, "units": batch_rows}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "units": len(batch_rows), "previewed": sum(r.get("status") == "previewed" for r in batch_rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
