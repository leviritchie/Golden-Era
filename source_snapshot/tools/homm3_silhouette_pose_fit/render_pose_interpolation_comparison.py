#!/usr/bin/env python3
"""Render three interpolation methods from an existing notebook pose artifact.

This is deliberately separate from fitting. It never calls the optimizer; it
only resamples the saved poses and asks the persistent Blender worker for proof
renders. The default input is the latest six-pose semantic notebook artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from roc_pose_interpolation import (
    ROTATION_METHODS,
    interpolate_clip,
    load_pose_artifact,
    pose_delta_summary,
    write_pose_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POSES = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/clip_export/clip_poses.json"
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_WORKER = Path(__file__).with_name("roc_chroma_match_worker.py")


class JsonlWorker:
    def __init__(self, blender: Path, worker_script: Path):
        self.process = subprocess.Popen(
            [str(blender), "-b", "--python", str(worker_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def request(self, command: dict[str, Any]) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("Blender worker pipes are unavailable")
        self.process.stdin.write(json.dumps(command, default=float) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(
                    f"Blender interpolation worker exited with code {self.process.poll()}"
                )
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.request({"cmd": "quit"})
            finally:
                self.process.wait(timeout=20)


def _rgb_on_black(path: Path) -> Image.Image:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _write_gif(frames: list[Image.Image], path: Path, frame_ms: int) -> None:
    if not frames:
        raise ValueError("cannot write an empty GIF")
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=int(frame_ms),
        loop=0,
        optimize=False,
    )


def _write_mp4(frames: list[Image.Image], path: Path, fps: int) -> None:
    if not frames:
        raise ValueError("cannot write an empty MP4")
    width, height = frames[0].size
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), int(fps), (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open MP4 writer: {path}")
    try:
        for image in frames:
            writer.write(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def _pixel_difference(left: Image.Image, right: Image.Image) -> dict[str, float | int]:
    delta = np.abs(np.asarray(left, dtype=np.int16) - np.asarray(right, dtype=np.int16))
    return {
        "max": int(delta.max()) if delta.size else 0,
        "mean": float(delta.mean()) if delta.size else 0.0,
        "differentPixels": int(np.count_nonzero(np.any(delta != 0, axis=2)))
        if delta.ndim == 3
        else 0,
    }


def _write_stacked_comparison(
    method_frames: dict[str, list[Image.Image]],
    path: Path,
    frame_ms: int,
) -> None:
    methods = list(method_frames)
    if not methods:
        raise ValueError("no method frames supplied")
    width, height = method_frames[methods[0]][0].size
    labels = {
        "euler_linear": (245, 185, 66),
        "quaternion_slerp": (78, 183, 255),
        "quaternion_smoothstep": (122, 226, 142),
    }
    stacked: list[Image.Image] = []
    for frame_index in range(len(method_frames[methods[0]])):
        sheet = Image.new("RGB", (width, height * len(methods)), (0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        for row, method in enumerate(methods):
            image = method_frames[method][frame_index]
            y = row * height
            sheet.paste(image, (0, y))
            draw.rectangle((0, y, width - 1, y + 25), fill=(0, 0, 0))
            draw.text((8, y + 6), method, fill=labels.get(method, (255, 255, 255)))
        stacked.append(sheet)
    _write_gif(stacked, path, frame_ms)


def _init_command(args: argparse.Namespace) -> dict[str, Any]:
    # These values mirror the most recent notebook run's render contract. The
    # encoder/scoring toggles are intentionally absent because this is export.
    return {
        "cmd": "init",
        "src": str(args.src.resolve()),
        "fit": str(args.fit.resolve()),
        "width": int(args.width),
        "height": int(args.height),
        "searchScale": 0.5,
        "meshScale": float(args.mesh_scale),
        "semanticMultiview": False,
        "semanticViewAnglesDeg": [0.0, 180.0, 90.0],
        "semanticViewElevationsDeg": [0.0, 0.0, 12.0],
        "semanticViewWeights": [1.0, 1.0, 1.0],
        "searchEngine": "BLENDER_WORKBENCH",
        "searchTaaSamples": 1,
        "proofEngine": "BLENDER_EEVEE",
        "proofTaaSamples": 8,
        "lightingMode": "flat_emission",
        "sunEnergy": 15.0,
        "sunAzimuthDeg": 95.0,
        "sunElevationDeg": 15.0,
        "sunAngleDeg": 50.0,
        "scoreMode": "depth",
        "renderDepth": True,
        "renderResultInMemory": False,
        "incrementalPoseApplication": True,
        "depthMaxDist": 0.99,
        "colorMaxDist": 0.30,
        "predOnlyPenalty": 2.5,
        "targetOnlyPenalty": 1.5,
        "targetEdgeBonus": 1.0,
        "silhouetteDepthWeight": 1.0,
        "reverseProfileEnabled": False,
        "profileHalfBias": 0.5,
        "ikEnabled": False,
        "ikMode": "off",
        "detectProfile": True,
        "meshOrientationMode": "none",
        "profileSamples": 72,
        "motionRootEnabled": True,
        "motionRootAxes": ["forward"],
        "motionRootForwardRadiusBodyLengths": 0.20,
        "motionRootLateralRadiusBodyLengths": 0.05,
        "motionRootVerticalRadiusBodyLengths": 0.0,
        "stripBoneRoll": True,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_provenance(
    args: argparse.Namespace,
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    provenance = source_metadata.get("provenance")
    if not isinstance(provenance, dict):
        if args.allow_unverified_pose_artifact:
            return {"verified": False, "reason": "no provenance sidecar"}
        raise RuntimeError(
            f"pose artifact has no provenance sidecar: {args.poses.with_name(args.poses.stem + '.provenance.json')}; "
            "rerun the notebook export or pass --allow-unverified-pose-artifact for an explicit ablation"
        )

    def _same_path(left: str | Path, right: str | Path) -> bool:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
            str(Path(right).resolve())
        )

    expected_mesh = provenance.get("sourceMesh")
    expected_fit = provenance.get("cameraFit")
    if not expected_mesh or not _same_path(expected_mesh, args.src):
        raise RuntimeError(
            f"pose provenance expects mesh {expected_mesh!r}, but --src is {str(args.src)!r}"
        )
    if not expected_fit or not _same_path(expected_fit, args.fit):
        raise RuntimeError(
            f"pose provenance expects camera fit {expected_fit!r}, but --fit is {str(args.fit)!r}"
        )
    for label, path, expected in (
        ("source mesh", args.src, provenance.get("sourceMeshSha256")),
        ("camera fit", args.fit, provenance.get("cameraFitSha256")),
    ):
        if expected and _sha256(path) != str(expected):
            raise RuntimeError(f"{label} changed since the pose artifact was exported: {path}")
    expected_frames = [int(frame) for frame in provenance.get("frameIndices", ())]
    actual_frames = [int(frame) for frame in source_metadata.get("sourceFrameIndices", ())]
    if expected_frames and expected_frames != actual_frames:
        raise RuntimeError(
            f"pose provenance frame indices {expected_frames} do not match artifact {actual_frames}"
        )
    return {
        "verified": True,
        "provenancePath": source_metadata.get("provenancePath"),
        "unit": provenance.get("unit"),
        "animation": provenance.get("animation"),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    poses, source_metadata = load_pose_artifact(args.poses)
    provenance_report = _validate_provenance(args, source_metadata)
    methods = tuple(args.methods)
    if len(methods) != len(ROTATION_METHODS) or set(methods) != set(ROTATION_METHODS):
        raise ValueError(
            "the comparison must run exactly these three methods: "
            f"{ROTATION_METHODS}"
        )
    for method in methods:
        if method not in ROTATION_METHODS:
            raise ValueError(f"unsupported method {method!r}; choose from {ROTATION_METHODS}")
    if not args.src.is_file():
        raise FileNotFoundError(f"mesh source is missing: {args.src}")
    if not args.fit.is_file():
        raise FileNotFoundError(f"camera fit is missing: {args.fit}")
    args.out.mkdir(parents=True, exist_ok=True)

    method_frames: dict[str, list[Image.Image]] = {}
    method_reports: dict[str, Any] = {}
    worker = JsonlWorker(args.blender, args.worker)
    try:
        init_result = worker.request(_init_command(args))
        if not init_result.get("ok"):
            raise RuntimeError({"stage": "init", "result": init_result})
        source_bones = {
            str(key)
            for key in poses[0]
            if str(key) != "__motion_root__"
        }
        mesh_bones = {str(name) for name in init_result.get("bones", ())}
        matched_bones = source_bones & mesh_bones
        if not matched_bones or len(matched_bones) < max(1, int(len(source_bones) * 0.5)):
            missing = sorted(source_bones - mesh_bones)
            raise RuntimeError(
                "pose artifact and mesh skeleton do not match: "
                f"matched {len(matched_bones)}/{len(source_bones)} pose bones; "
                f"missing examples={missing[:8]}. Pass the GLB used by the notebook run."
            )
        print("worker initialized:", json.dumps({
            "meshScale": init_result.get("meshScale"),
            "profileDetection": init_result.get("profileDetection"),
            "motionRoot": init_result.get("motionRoot"),
        }, default=float), flush=True)

        for method in methods:
            interpolated = interpolate_clip(
                poses,
                method=method,
                samples_per_interval=args.samples_per_interval,
                loop=args.loop,
            )
            method_dir = args.out / method
            render_dir = method_dir / "renders"
            render_dir.mkdir(parents=True, exist_ok=True)
            pose_path = method_dir / "poses.json"
            write_pose_artifact(
                pose_path,
                interpolated,
                method=method,
                source_metadata=source_metadata,
                samples_per_interval=args.samples_per_interval,
                loop=args.loop,
                fps=args.fps,
            )
            rendered: list[Image.Image] = []
            for index, pose in enumerate(interpolated):
                frame_path = render_dir / f"frame_{index:03d}.png"
                result = worker.request(
                    {"cmd": "save_render", "angles": pose, "out": str(frame_path)}
                )
                if not result.get("ok") or not frame_path.is_file():
                    raise RuntimeError({"stage": "render", "method": method, "frame": index, "result": result})
                rendered.append(_rgb_on_black(frame_path))
                if (index + 1) % max(1, args.progress_every) == 0 or index + 1 == len(interpolated):
                    print(f"{method}: rendered {index + 1}/{len(interpolated)}", flush=True)
            gif_path = method_dir / f"{method}.gif"
            mp4_path = method_dir / f"{method}_{args.fps}fps.mp4"
            _write_gif(rendered, gif_path, args.gif_frame_ms)
            _write_mp4(rendered, mp4_path, args.fps)
            method_frames[method] = rendered
            keyframe_checks = []
            source_frame_indices = [
                int(frame)
                for frame in source_metadata.get("sourceFrameIndices", range(len(poses)))
            ]
            for source_index, frame_index in enumerate(source_frame_indices):
                source_render = args.poses.parent / f"frame_{frame_index:02d}.png"
                if not source_render.is_file():
                    keyframe_checks.append(
                        {"frame": frame_index, "available": False}
                    )
                    continue
                keyframe_checks.append(
                    {
                        "frame": frame_index,
                        "available": True,
                        "difference": _pixel_difference(
                            _rgb_on_black(source_render),
                            rendered[source_index * args.samples_per_interval],
                        ),
                    }
                )
            method_reports[method] = {
                "poseArtifact": str(pose_path),
                "renderDir": str(render_dir),
                "gif": str(gif_path),
                "mp4": str(mp4_path),
                "frameCount": len(interpolated),
                "poseDeltaSummary": pose_delta_summary(interpolated),
                "sourceKeyframeChecks": keyframe_checks,
            }
    finally:
        worker.close()

    comparison_gif = args.out / "interpolation_comparison_3x1.gif"
    _write_stacked_comparison(method_frames, comparison_gif, args.gif_frame_ms)
    comparison_mp4 = args.out / f"interpolation_comparison_3x1_{args.fps}fps.mp4"
    stacked_frames: list[Image.Image] = []
    methods_for_stack = list(method_frames)
    for index in range(len(method_frames[methods_for_stack[0]])):
        width, height = method_frames[methods_for_stack[0]][index].size
        sheet = Image.new("RGB", (width, height * len(methods_for_stack)), (0, 0, 0))
        for row, method in enumerate(methods_for_stack):
            sheet.paste(method_frames[method][index], (0, row * height))
        stacked_frames.append(sheet)
    _write_mp4(stacked_frames, comparison_mp4, args.fps)

    pairwise_differences = {}
    for left_index, left_method in enumerate(methods):
        for right_method in methods[left_index + 1 :]:
            pairwise_differences[f"{left_method}__vs__{right_method}"] = {
                "meanAcrossFrames": float(
                    np.mean(
                        [
                            _pixel_difference(
                                method_frames[left_method][index],
                                method_frames[right_method][index],
                            )["mean"]
                            for index in range(len(method_frames[left_method]))
                        ]
                    )
                ),
                "maxAcrossFrames": int(
                    max(
                        _pixel_difference(
                            method_frames[left_method][index],
                            method_frames[right_method][index],
                        )["max"]
                        for index in range(len(method_frames[left_method]))
                    )
                ),
            }

    report = {
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "sourcePoseArtifact": str(args.poses),
        "sourceFrameCount": len(poses),
        "sourceFrameIndices": source_metadata.get("sourceFrameIndices"),
        "provenance": provenance_report,
        "loop": bool(args.loop),
        "samplesPerInterval": int(args.samples_per_interval),
        "fps": int(args.fps),
        "gifFrameMs": int(args.gif_frame_ms),
        "methods": list(methods),
        "comparisonGif": str(comparison_gif),
        "comparisonMp4": str(comparison_mp4),
        "pairwisePixelDifferences": pairwise_differences,
        "methodReports": method_reports,
        "renderContract": _init_command(args),
    }
    report_path = args.out / "interpolation_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), "comparisonGif": str(comparison_gif), "comparisonMp4": str(comparison_mp4)}, indent=2), flush=True)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poses", type=Path, default=DEFAULT_POSES)
    parser.add_argument("--src", type=Path, required=True, help="the GLB used for the saved pose artifact")
    parser.add_argument("--fit", type=Path, required=True, help="the camera-fit JSON used for the saved pose artifact")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=683)
    parser.add_argument("--mesh-scale", type=float, default=1.25)
    parser.add_argument("--samples-per-interval", type=int, default=5)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--gif-frame-ms", type=int, default=17)
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument(
        "--allow-unverified-pose-artifact",
        action="store_true",
        help="explicitly bypass the required pose provenance sidecar for an ablation",
    )
    parser.add_argument("--no-loop", dest="loop", action="store_false")
    parser.set_defaults(loop=True)
    parser.add_argument("--methods", nargs="+", choices=ROTATION_METHODS, default=list(ROTATION_METHODS))
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    run(parse_args())
