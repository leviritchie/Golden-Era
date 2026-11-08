#!/usr/bin/env python3
"""Run Roc sprite-to-mesh pose transfer with SigLIP2 semantic image scoring.

This is the reusable, notebook-free pipeline for the current Roc move
experiment. It drives the existing Blender worker, but every candidate pose is
scored by local GPU image embeddings rather than by the older depth/chroma IoU.
The final output is a semantic-only report plus mesh frames that can be passed
to render_roc_semantic_transfer_pipeline.py for GIF/MP4 review delivery.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from pose_fit_auto import build_dependency_order, build_range_table, filter_search_bones
from roc_semantic_embedding_match import RocSemanticEmbedder

SEMANTIC_MODEL = "google/siglip2-base-patch16-512"
DEFAULT_PILOT = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
DEFAULT_TARGETS = DEFAULT_PILOT / "frames_nn_shadow_culled"
DEFAULT_TARGET_DEPTH = DEFAULT_PILOT / "frames_depth_predicted"
DEFAULT_FIT = DEFAULT_PILOT / "roc_sprite_camera_fit.json"
DEFAULT_GLB = Path("C:/Users/<user>/Downloads/griffon_smart_rigged.glb")
DEFAULT_BLENDER = Path("V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_WORKER = TOOL_DIR / "roc_chroma_match_worker.py"
DEFAULT_OUT = DEFAULT_PILOT / "roc_semantic_siglip2_move_v1"


class BlenderWorker:
    def __init__(self, blender: Path, worker: Path):
        self.proc = subprocess.Popen(
            [str(blender), "-b", "--python", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def request(self, command: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("Blender worker exited")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.request({"cmd": "quit"})
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


def _frame_index(path: Path) -> int:
    return int(path.stem.split("_")[-1]) if "_" in path.stem else int(path.stem)


def _pose_for_json(pose: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {bone: {axis: float(value) for axis, value in delta.items()} for bone, delta in pose.items()}


class SemanticPoseRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.out_dir: Path = args.out_dir
        self.frame_dir = self.out_dir / "mesh_frames"
        self.candidate_dir = self.out_dir / "semantic_candidates"
        self.preview_dir = self.out_dir / "candidate_previews"
        self.encoder_view_dir = self.out_dir / "encoder_views"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.frame_dir.mkdir(parents=True, exist_ok=True)
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.encoder_view_dir.mkdir(parents=True, exist_ok=True)

        self.encoder = RocSemanticEmbedder(model_id=args.semantic_model)
        self.target_vectors: dict[int, np.ndarray] = {}
        self.worker = BlenderWorker(args.blender, args.worker)
        self.init_result = self._init_worker()
        self.bones = list(self.init_result["bones"])
        self.order, self.order_groups = build_dependency_order(
            self.bones,
            parents=self.init_result["parents"],
            heads=self.init_result["boneHeads"],
            view=self.init_result["view"],
            right=self.init_result["right"],
        )
        self.range_by_bone = build_range_table(
            self.bones,
            parents=self.init_result["parents"],
            heads=self.init_result["boneHeads"],
            locked=[],
            unrestricted=True,
            free_deg=float(args.free_deg),
        )
        self.search_bones = filter_search_bones(
            self.order,
            descendant_count=self.order_groups.get("descendantCount") or {},
            bone_length=self.order_groups.get("boneLength") or {},
            skip_tiny=not args.include_tiny_bones,
        )

    def _init_worker(self) -> dict[str, Any]:
        result = self.worker.request(
            {
                "cmd": "init",
                "src": str(self.args.glb),
                "fit": str(self.args.fit),
                "width": int(self.args.width),
                "height": int(self.args.height),
                "searchScale": float(self.args.search_scale),
                "searchEngine": "BLENDER_WORKBENCH",
                "searchTaaSamples": 1,
                "proofEngine": "BLENDER_EEVEE",
                "proofTaaSamples": int(self.args.proof_taa_samples),
                # Chroma mode is used only to force true RGB candidate renders.
                # The decision score below is semantic cosine only.
                "scoreMode": "chroma",
                "depthMaxDist": 0.99,
                "colorMaxDist": 0.30,
                "predOnlyPenalty": 2.5,
                "targetEdgeSigmaPx": 4.0,
                "targetEdgeFloor": 0.25,
                "stripBoneRoll": True,
            }
        )
        if not result.get("ok"):
            raise RuntimeError(result)
        return result

    def close(self) -> None:
        self.worker.close()

    def range_for(self, bone: str) -> tuple[float, float]:
        lo, hi = self.range_by_bone.get(bone, (-float(self.args.free_deg), float(self.args.free_deg)))
        return float(lo), float(hi)

    def target_vector(self, frame_index: int) -> np.ndarray:
        if frame_index not in self.target_vectors:
            target = self.args.targets / f"{frame_index:02d}.png"
            image = self._encoder_image(target)
            image.save(self.encoder_view_dir / f"target_f{frame_index:02d}.png")
            self.target_vectors[frame_index] = self.encoder.embed([image])[0]
        return self.target_vectors[frame_index]

    def _encoder_image(self, path: Path):
        if self.args.encoder_view == "subject":
            _bbox, meta = self.encoder.subject_bbox_with_meta(path)
            if meta.get("fallbackFullCanvas"):
                raise RuntimeError(f"subject crop found no foreground pixels: {path}")
            return self.encoder.load_subject_image(path)
        if self.args.encoder_view == "canvas":
            return self.encoder.load_image(path)
        raise ValueError(f"unsupported encoder view: {self.args.encoder_view!r}")

    def _subject_crop_meta(self, path: Path) -> dict[str, Any] | None:
        if self.args.encoder_view != "subject":
            return None
        _bbox, meta = self.encoder.subject_bbox_with_meta(path)
        return meta

    def semantic_score(
        self,
        *,
        frame_index: int,
        pose: dict[str, dict[str, float]],
        label: str,
        preview: bool,
    ) -> tuple[float, dict[str, Any]]:
        safe_label = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)[:160]
        candidate_path = self.candidate_dir / f"f{frame_index:02d}_{safe_label}.png"
        target = self.args.targets / f"{frame_index:02d}.png"
        target_depth = self.args.target_depth / f"{frame_index:02d}.png"
        request = {
            "cmd": "score",
            "target": str(target),
            "targetDepth": str(target_depth),
            "angles": pose,
            "scoreMode": "chroma",
            "previewRgb": True,
            "semanticOnly": True,
            "semanticModel": self.args.semantic_model,
            "semanticCandidateOut": str(candidate_path),
            "threshold": 0.08,
        }
        if self.args.objective == "notebook-depth":
            request.pop("semanticOnly")
            request.pop("semanticModel")
            request.pop("semanticCandidateOut")
            request["scoreMode"] = "depth"
        if preview:
            request["previewOut"] = str(self.preview_dir / f"latest_f{frame_index:02d}.png")
            request["previewCaption"] = label
        t0 = time.perf_counter()
        result = self.worker.request(request)
        if not result.get("ok"):
            raise RuntimeError(result)
        if self.args.objective == "notebook-depth":
            score = float(result["iou"])
            result["scoreMode"] = "depth"
            result["dtScore"] = time.perf_counter() - t0
            return score, result
        candidate_image = self._encoder_image(candidate_path)
        if label.startswith("final_") or preview:
            candidate_image.save(self.encoder_view_dir / f"{safe_label}.png")
        candidate_vector = self.encoder.embed([candidate_image])[0]
        score = float(np.dot(self.target_vector(frame_index), candidate_vector))
        result["silhouetteIoU"] = float(result.get("iou", 0.0))
        result["semanticCosine"] = score
        result["iou"] = score
        result["semanticCandidate"] = str(candidate_path)
        result["dtScore"] = time.perf_counter() - t0
        return score, result

    def _magnitudes(self, lo: float, hi: float, step: float) -> list[float]:
        vals = [0.0]
        m = float(step)
        limit = max(abs(lo), abs(hi))
        while m <= limit + 1e-9:
            if m <= hi + 1e-9:
                vals.append(m)
            if -m >= lo - 1e-9:
                vals.append(-m)
            m += float(step)
        return sorted(set(float(min(hi, max(lo, v))) for v in vals))

    def scan_bone(
        self,
        *,
        frame_index: int,
        bone: str,
        accumulated: dict[str, dict[str, float]],
        preview: bool,
    ) -> tuple[dict[str, float], float, list[dict[str, Any]], dict[str, Any]]:
        axes = [axis.lower() for axis in self.args.search_axes]
        coarse_step = float(self.args.coarse_step_deg)
        refine_step = float(self.args.refine_step_deg)
        lo, hi = self.range_for(bone)
        trials: list[dict[str, Any]] = []
        timings: dict[str, Any] = {"mode": "compound", "axesTried": axes, "angleEvaluations": []}

        def clip(deg: float) -> float:
            return float(min(hi, max(lo, deg)))

        def score_euler(euler_deg: dict[str, float], region: str) -> float:
            pose = dict(accumulated)
            pose[bone] = {
                "x": math.radians(float(euler_deg.get("x", 0.0))),
                "y": math.radians(float(euler_deg.get("y", 0.0))),
                "z": math.radians(float(euler_deg.get("z", 0.0))),
            }
            label = (
                f"bone_{bone}_{region}_"
                f"x{euler_deg.get('x', 0.0):+.1f}_z{euler_deg.get('z', 0.0):+.1f}"
            )
            score, result = self.semantic_score(
                frame_index=frame_index,
                pose=pose,
                label=label,
                preview=preview,
            )
            row = {
                "eulerDeg": {k: float(euler_deg.get(k, 0.0)) for k in ("x", "y", "z")},
                "semanticCosine": score,
                "silhouetteIoU": float(result.get("silhouetteIoU", 0.0)),
                "region": region,
                "dtScore": float(result.get("dtScore", 0.0)),
            }
            trials.append(row)
            timings["angleEvaluations"].append(row)
            return score

        best_euler = {"x": 0.0, "y": 0.0, "z": 0.0}
        best_score = score_euler(best_euler, "bind")
        candidates: list[dict[str, float]] = [dict(best_euler)]
        for axis in axes:
            for magnitude in self._magnitudes(lo, hi, coarse_step):
                if abs(magnitude) < 1e-9:
                    continue
                candidate = {"x": 0.0, "y": 0.0, "z": 0.0}
                candidate[axis] = magnitude
                candidates.append(candidate)

        pair_step = max(refine_step, coarse_step * float(self.args.compound_pair_step_mult))
        pair_mags = [m for m in self._magnitudes(lo, hi, pair_step) if abs(m) <= 2.0 * pair_step + 1e-9]
        for i, first in enumerate(axes):
            for second in axes[i + 1 :]:
                for a in pair_mags:
                    for b in pair_mags:
                        if abs(a) < 1e-9 and abs(b) < 1e-9:
                            continue
                        candidate = {"x": 0.0, "y": 0.0, "z": 0.0}
                        candidate[first] = a
                        candidate[second] = b
                        candidates.append(candidate)

        # Keep the notebook's compound proposal set in parity: it also tests
        # simultaneous three-axis sign patterns before coordinate descent.
        for magnitude in (pair_step, 2.0 * pair_step):
            if magnitude > max(abs(lo), abs(hi)) + 1e-9:
                continue
            for sx in (-1, 0, 1):
                for sy in (-1, 0, 1):
                    for sz in (-1, 0, 1):
                        if sx == sy == sz == 0:
                            continue
                        candidates.append(
                            {
                                "x": clip(sx * magnitude) if "x" in axes else 0.0,
                                "y": clip(sy * magnitude) if "y" in axes else 0.0,
                                "z": clip(sz * magnitude) if "z" in axes else 0.0,
                            }
                        )

        unique: dict[tuple[float, float, float], dict[str, float]] = {}
        for candidate in candidates:
            key = tuple(round(float(candidate.get(axis, 0.0)), 4) for axis in ("x", "y", "z"))
            unique[key] = {axis: float(candidate.get(axis, 0.0)) for axis in ("x", "y", "z")}
        candidates = list(unique.values())
        timings["compoundCandidates"] = len(candidates)

        for candidate in candidates:
            if all(abs(candidate[axis]) < 1e-9 for axis in ("x", "y", "z")):
                continue
            score = score_euler(candidate, "joint")
            if score > best_score:
                best_score, best_euler = score, dict(candidate)

        for round_index in range(max(1, int(self.args.compound_cd_rounds))):
            for axis in axes:
                center = float(best_euler.get(axis, 0.0))
                window = max(2.0 * refine_step, coarse_step)
                samples = np.arange(clip(center - window), clip(center + window) + refine_step * 0.5, refine_step)
                if not np.any(np.isclose(samples, center)):
                    samples = np.unique(np.append(samples.astype(float), center))
                for sample in samples:
                    candidate = dict(best_euler)
                    candidate[axis] = float(sample)
                    score = score_euler(candidate, f"cd{round_index}_{axis}")
                    if score > best_score:
                        best_score, best_euler = score, dict(candidate)

        delta = {
            "x": math.radians(float(best_euler.get("x", 0.0))),
            "y": math.radians(float(best_euler.get("y", 0.0))),
            "z": math.radians(float(best_euler.get("z", 0.0))),
        }
        timings["chosenEulerDeg"] = dict(best_euler)
        return delta, float(best_score), trials, timings

    def optimize_frame(
        self,
        frame_index: int,
        *,
        initial: dict[str, dict[str, float]] | None,
        preview: bool,
    ) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]], float]:
        pose: dict[str, dict[str, float]] = dict(initial or {})
        history: list[dict[str, Any]] = []
        start = time.perf_counter()
        for bone_index, bone in enumerate(self.search_bones, start=1):
            bone_start = time.perf_counter()
            delta, score, trials, timings = self.scan_bone(
                frame_index=frame_index,
                bone=bone,
                accumulated=pose,
                preview=preview,
            )
            pose[bone] = delta
            euler_deg = {axis: round(math.degrees(float(delta.get(axis, 0.0))), 2) for axis in ("x", "y", "z")}
            elapsed = time.perf_counter() - bone_start
            history.append(
                {
                    "bone": bone,
                    "angleDeg": euler_deg,
                    "semanticCosine": score,
                    "trials": len(trials),
                    "elapsed": elapsed,
                    "timings": timings,
                }
            )
            print(
                f"f{frame_index:02d} {bone_index:02d}/{len(self.search_bones)} {bone}: "
                f"XYZ ({euler_deg['x']:.1f},{euler_deg['y']:.1f},{euler_deg['z']:.1f}) "
                f"semantic={score:.4f} elapsed={elapsed:.1f}s",
                flush=True,
            )
        return pose, history, time.perf_counter() - start

    def save_frame(self, frame_index: int, pose: dict[str, dict[str, float]]) -> Path:
        out = self.frame_dir / f"frame_{frame_index:02d}.png"
        result = self.worker.request({"cmd": "save_render", "angles": pose, "out": str(out)})
        if not result.get("ok"):
            raise RuntimeError(result)
        return out

    def final_score(self, frame_index: int, pose: dict[str, dict[str, float]]) -> dict[str, Any]:
        score, result = self.semantic_score(
            frame_index=frame_index,
            pose=pose,
            label=f"final_f{frame_index:02d}",
            preview=False,
        )
        if self.args.objective == "notebook-depth":
            return {
                "scoreMode": "depth",
                "depthIoU": score,
                "preview": str(self.preview_dir / f"latest_f{frame_index:02d}.png"),
            }
        return {
            "scoreMode": "semantic",
            "semanticCosine": score,
            "silhouetteIoU": float(result.get("silhouetteIoU", 0.0)),
            "semanticCandidate": str(result.get("semanticCandidate", "")),
            "targetEncoderView": str(self.encoder_view_dir / f"target_f{frame_index:02d}.png"),
            "candidateEncoderView": str(self.encoder_view_dir / f"final_f{frame_index:02d}.png"),
            "targetCrop": self._subject_crop_meta(self.args.targets / f"{frame_index:02d}.png"),
            "candidateCrop": self._subject_crop_meta(Path(str(result.get("semanticCandidate", "")))),
        }

    def write_report(self, rows: list[dict[str, Any]]) -> Path:
        semantic_objective = self.args.objective == "semantic"
        report = {
            "proof": "generated notebook-parity or semantic single-bone transfer; original frames only",
            "objective": self.args.objective,
            "semanticOnly": semantic_objective,
            "semanticModel": self.args.semantic_model if semantic_objective else None,
            "scoreAuthority": "semantic cosine only" if semantic_objective else "worker depth IoU (notebook parity)",
            "encoderView": self.args.encoder_view,
            "targets": str(self.args.targets),
            "targetDepth": str(self.args.target_depth),
            "meshFrames": str(self.frame_dir),
            "glb": str(self.args.glb),
            "cameraFit": str(self.args.fit),
            "width": int(self.args.width),
            "height": int(self.args.height),
            "searchScale": float(self.args.search_scale),
            "coarseStepDeg": float(self.args.coarse_step_deg),
            "refineStepDeg": float(self.args.refine_step_deg),
            "freeDeg": float(self.args.free_deg),
            "searchBones": self.search_bones,
            "lockedBones": self.order_groups.get("locked", []),
            "frames": rows,
        }
        report_path = self.out_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report_path

    def run(self) -> Path:
        rows: list[dict[str, Any]] = []
        previous_pose: dict[str, dict[str, float]] | None = None
        for frame_index in self.args.frames:
            frame_start = time.perf_counter()
            pose, history, solve_seconds = self.optimize_frame(
                frame_index,
                initial=previous_pose if self.args.seed_from_previous else None,
                preview=bool(self.args.live_preview),
            )
            mesh_frame = self.save_frame(frame_index, pose)
            final_score = self.final_score(frame_index, pose)
            row = {
                "frame": int(frame_index),
                "pose": _pose_for_json(pose),
                "history": history,
                "finalScore": final_score,
                "seconds": solve_seconds,
                "meshFrame": str(mesh_frame),
                "totalSeconds": time.perf_counter() - frame_start,
            }
            rows.append(row)
            previous_pose = pose
            report_path = self.write_report(rows)
            print(f"frame {frame_index:02d} complete -> {mesh_frame}", flush=True)
            print(f"checkpoint report -> {report_path}", flush=True)
        return self.write_report(rows)


def parse_frame_spec(spec: str, target_dir: Path) -> list[int]:
    available = sorted(_frame_index(path) for path in target_dir.glob("*.png"))
    if not available:
        raise RuntimeError(f"No target frames in {target_dir}")
    if spec == "all":
        return available
    frames: set[int] = set()
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            start, end = [int(x) for x in piece.split("-", 1)]
            frames.update(range(start, end + 1))
        else:
            frames.add(int(piece))
    missing = sorted(frames - set(available))
    if missing:
        raise RuntimeError(f"Requested frames are missing from {target_dir}: {missing}")
    return sorted(frames)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", type=Path, default=DEFAULT_GLB)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--target-depth", type=Path, default=DEFAULT_TARGET_DEPTH)
    parser.add_argument("--fit", type=Path, default=DEFAULT_FIT)
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--frames", type=str, default="all", help="'all', '0-29', or comma list")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=683)
    parser.add_argument("--search-scale", type=float, default=0.35)
    parser.add_argument("--semantic-model", type=str, default=SEMANTIC_MODEL)
    parser.add_argument(
        "--objective",
        choices=["semantic", "notebook-depth"],
        default="semantic",
        help="semantic cosine delivery or the historical notebook compound depth objective",
    )
    # The notebook's proven pilot embeds the complete fixed camera canvas.
    # Subject cropping remains available as an explicit diagnostic mode.
    parser.add_argument("--encoder-view", choices=["subject", "canvas"], default="canvas")
    parser.add_argument("--search-axes", nargs="+", default=["x", "z"])
    parser.add_argument("--coarse-step-deg", type=float, default=16.0)
    parser.add_argument("--refine-step-deg", type=float, default=4.0)
    parser.add_argument("--compound-pair-step-mult", type=float, default=1.0)
    parser.add_argument("--compound-cd-rounds", type=int, default=2)
    parser.add_argument("--free-deg", type=float, default=90.0)
    parser.add_argument("--proof-taa-samples", type=int, default=8)
    parser.add_argument("--include-tiny-bones", action="store_true")
    parser.add_argument("--seed-from-previous", dest="seed_from_previous", action="store_true")
    parser.add_argument("--no-seed-from-previous", dest="seed_from_previous", action="store_false")
    parser.add_argument("--live-preview", action="store_true", help="Write latest candidate preview PNGs")
    # Match the notebook's full-sequence loop: each frame starts from the
    # previous frame's committed pose. Use --no-seed-from-previous for an
    # isolated frame diagnostic.
    parser.set_defaults(seed_from_previous=True)
    args = parser.parse_args()
    args.frames = parse_frame_spec(args.frames, args.targets)

    for path in (args.glb, args.targets, args.target_depth, args.fit, args.blender, args.worker):
        if not path.exists():
            raise FileNotFoundError(path)

    runner = SemanticPoseRunner(args)
    try:
        report_path = runner.run()
    finally:
        runner.close()
    print(json.dumps({"ok": True, "report": str(report_path), "frames": len(args.frames)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
