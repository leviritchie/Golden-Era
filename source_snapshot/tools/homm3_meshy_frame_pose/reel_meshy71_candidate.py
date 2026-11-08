"""Render a source-vs-Meshy 7.1 animation reel for one selected repair candidate.

The source panel may use reconstructed reference tracks, but a fitted candidate can instead consume
the exact rotations and offsets emitted by ``fit_mesh_rest_pipeline.py``. Reconstructing transforms
from joint positions is deliberately not equivalent: it loses inherited axial rotation. The output
is diagnostic animation evidence: it is not installed-game proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "artifacts/homm3_owned_bind"))

import exp_tpose as render  # noqa: E402
import exp_tpose_gifs as gifs  # noqa: E402
from owned_rerig.glb_io import load_render_surface  # noqa: E402
from owned_rerig.exact_bind import driver_transforms  # noqa: E402
from owned_rerig.pose_source import CaptureToWorld, load_registered_pose_source  # noqa: E402
from owned_rerig.tpose import edge_stretch, tpose_joint_track  # noqa: E402

SCHEMA = "meshy71.candidate_reel.v1"
GAP = 6


def load_bind(path: Path) -> dict:
    delivered = render.pv.load_delivered_skeleton(path)
    surface = load_render_surface(path)
    return {
        "path": str(path.resolve()).replace("\\", "/"),
        "delivered": delivered,
        "surface": surface,
        "positions": np.asarray(delivered["positions"], dtype=np.float64),
        "indices": np.asarray(delivered["indices"], dtype=np.int64),
        "restNormals": np.asarray(surface["normals"], dtype=np.float64),
        "height": float(np.ptp(np.asarray(delivered["positions"], dtype=np.float64)[:, 1])),
    }


def load_similarity(report_path: Path) -> CaptureToWorld:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    fit = report.get("similarity") or {}
    if report.get("schema") == "homm3.static-bind-registration.v1":
        selected_id = (report.get("acceptance") or {}).get("selectedCandidateId")
        candidates = (report.get("views") or {}).get("candidates") or []
        selected_rows = [row for row in candidates if selected_id and row.get("id") == selected_id]
        if len(selected_rows) != 1:
            raise ValueError(f"{report_path}: selected registration candidate is missing or ambiguous: {selected_id!r}")
        selected = selected_rows[0]
        fit = (selected or {}).get("skeletonSimilarity") or {}
        if fit:
            fit = dict(fit)
            fit["source"] = str(report_path.resolve()).replace("\\", "/")
    required = ("rotation", "scale", "translation", "policy", "source")
    missing = [key for key in required if key not in fit]
    if missing:
        raise SystemExit(f"fail-closed: bind report {report_path} has no similarity fields {missing}")
    return CaptureToWorld(
        rotation=np.asarray(fit["rotation"], dtype=np.float64),
        scale=float(fit["scale"]),
        translation=np.asarray(fit["translation"], dtype=np.float64),
        policy=str(fit["policy"]),
        source=str(fit["source"]),
    )


def load_candidate_similarity(report_path: Path, motion_mode: str) -> CaptureToWorld | None:
    """Load a candidate registration only when the replay is not fitter-owned."""
    if motion_mode == "saved-retargeted":
        return None
    return load_similarity(report_path)


def registration_path(run_dir: Path) -> Path:
    candidates = (
        run_dir / "linked_master_remaining_scale/idle0_registration.json",
        run_dir / "linked_master/idle0_registration.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit("fail-closed: Archer run has no registered idle registration")


def master_data(run_dir: Path) -> dict:
    return json.loads(
        (run_dir / "linked_master/master_sequence/master_sequence.json").read_text(encoding="utf-8")
    )


def reel_unit(master: dict, run_dir: Path) -> str:
    """Use the actual run unit in filenames and reports, never a pilot leftover."""
    return str(master.get("unit") or run_dir.name)


def clip_keys(master: dict) -> list[str]:
    return [
        str(segment["clipKey"])
        for segment in master["segments"]
        if str(segment["role"]) != "bookend"
    ]


def clip_span(master: dict, clip: str) -> tuple[int, int]:
    matches = [
        segment
        for segment in master["segments"]
        if str(segment["clipKey"]) == clip and str(segment["role"]) != "bookend"
    ]
    if len(matches) != 1:
        raise SystemExit(f"fail-closed: clip {clip!r} has {len(matches)} non-bookend segments")
    segment = matches[0]
    return int(segment["globalStart"]), int(segment["globalEnd"])


def load_saved_motion(
    path: Path, master: dict, joint_count: int
) -> dict[str, np.ndarray]:
    """Load a fitter-owned motion artifact without reconstructing rotations from points."""
    if not path.is_file():
        raise SystemExit(f"fail-closed: saved candidate motion is missing: {path}")
    with np.load(path) as archive:
        required = ("frame_joints", "rotations", "offsets")
        missing = [key for key in required if key not in archive]
        if missing:
            raise SystemExit(f"fail-closed: saved candidate motion lacks {missing}: {path}")
        motion = {key: np.asarray(archive[key], dtype=np.float64) for key in required}
    frame_count = len(master["frames"])
    expected = {
        "frame_joints": (frame_count, joint_count, 3),
        "rotations": (frame_count, joint_count, 3, 3),
        "offsets": (frame_count, joint_count, 3),
    }
    for key, shape in expected.items():
        if motion[key].shape != shape:
            raise SystemExit(
                f"fail-closed: saved candidate motion {key} shape {motion[key].shape} "
                f"does not match {shape}: {path}"
            )
        if not np.isfinite(motion[key]).all():
            raise SystemExit(
                f"fail-closed: saved candidate motion {key} contains non-finite values: {path}"
            )
    return motion


def saved_motion_for_clip(
    motion: dict[str, np.ndarray], master: dict, clip: str
) -> dict[str, np.ndarray]:
    start, end = clip_span(master, clip)
    return {key: value[start:end] for key, value in motion.items()}


def tracks_for(
    run_dir: Path,
    clip: str,
    similarity: CaptureToWorld,
    motion_mode: str,
) -> np.ndarray:
    pose = load_registered_pose_source(
        capture=run_dir / "linked_master/capture/capture/raw_capture.npz",
        registration=registration_path(run_dir),
        master_sequence=run_dir / "linked_master/master_sequence/master_sequence.json",
        segment_index=None,
        clip_key=clip,
        max_frames=None,
    )
    original = pose.capture_positions[pose.capture_indices]
    if motion_mode == "registered-reference":
        return similarity.apply(original)
    if motion_mode != "canonical-t-pose":
        raise SystemExit(f"fail-closed: unsupported reel motion mode {motion_mode!r}")
    rest = pose.capture_positions[pose.bind_index()]
    tpose = tpose_joint_track(
        rest=rest,
        parents=pose.parents,
        joint_names=pose.joint_names,
    )["joints"]
    canonical_rotation, canonical_offset = driver_transforms(
        heads=rest,
        parents=pose.parents,
        frame_joints=tpose,
    )
    rebased = []
    for frame in original:
        motion_rotation, motion_offset = driver_transforms(
            heads=rest,
            parents=pose.parents,
            frame_joints=frame,
        )
        rotation = np.einsum("nij,nkj->nik", motion_rotation, canonical_rotation)
        offset = motion_offset - np.einsum("nij,nj->ni", rotation, canonical_offset)
        rebased.append(np.einsum("nij,nj->ni", rotation, tpose) + offset)
    return similarity.apply(np.asarray(rebased, dtype=np.float64))


def skin(
    values: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    rotations: np.ndarray,
    offsets: np.ndarray | None = None,
) -> np.ndarray:
    result = np.zeros_like(values, dtype=np.float64)
    for slot in range(joints.shape[1]):
        ids = joints[:, slot]
        moved = np.einsum("nij,nj->ni", rotations[ids], values)
        if offsets is not None:
            moved += offsets[ids]
        result += moved * weights[:, slot, None]
    return result


def bake(bind: dict, tracks: np.ndarray, motion: dict[str, np.ndarray] | None = None) -> list[np.ndarray]:
    if motion is not None:
        return [
            skin(
                bind["positions"],
                bind["delivered"]["joints"],
                bind["delivered"]["weights"],
                rotation,
                offset,
            )
            for rotation, offset in zip(motion["rotations"], motion["offsets"])
        ]
    return [
        render.bake(
            delivered=bind["delivered"],
            positions=bind["positions"],
            joints=bind["delivered"]["joints"],
            weights=bind["delivered"]["weights"],
            frame_joints=track,
        )
        for track in tracks
    ]


def panel(
    bind: dict,
    view: dict,
    deformed: np.ndarray,
    tracks: np.ndarray,
    index: int,
    label: str,
    motion: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    if motion is None:
        normals = render.skinned_normals(
            delivered=bind["delivered"],
            rest_normals=bind["restNormals"],
            frame_joints=tracks[index],
        )
    else:
        normals = skin(
            bind["restNormals"],
            bind["delivered"]["joints"],
            bind["delivered"]["weights"],
            motion["rotations"][index],
        )
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    image = render.textured(
        view,
        deformed=deformed,
        normals=normals,
        surface=bind["surface"],
        indices=bind["indices"],
    )
    render.label(image, label)
    return image


def run(args: argparse.Namespace) -> int:
    if int(args.panel_scale) < 1:
        raise SystemExit("fail-closed: panel scale must be positive")
    if args.candidate_motion != "saved-retargeted" and args.candidate_motion_file:
        raise SystemExit(
            "fail-closed: --candidate-motion-file is only valid with "
            "--candidate-motion saved-retargeted"
        )
    render.PANEL = (430 * int(args.panel_scale), 620 * int(args.panel_scale))
    run_dir = Path(args.run_dir).resolve()
    source_bind = load_bind(Path(args.source_bind).resolve())
    candidate_bind = load_bind(Path(args.candidate_bind).resolve())
    source_similarity = load_similarity(Path(args.source_report).resolve())
    # A fitter-owned saved motion already contains the candidate-space joint transforms.
    # Requiring an older registration report here would either reject a valid fitted bind or
    # tempt callers to reconstruct the candidate motion from joint positions again.
    candidate_similarity = load_candidate_similarity(
        Path(args.candidate_report).resolve(), args.candidate_motion
    )
    master = master_data(run_dir)
    unit = reel_unit(master, run_dir)
    clips = clip_keys(master)
    if not clips:
        raise SystemExit("fail-closed: master sequence contains no non-bookend clips")

    saved_candidate_motion = None
    if args.candidate_motion == "saved-retargeted":
        if not args.candidate_motion_file:
            raise SystemExit("fail-closed: --candidate-motion-file is required for saved-retargeted motion")
        saved_candidate_motion = load_saved_motion(
            Path(args.candidate_motion_file).resolve(),
            master,
            len(candidate_bind["delivered"]["heads"]),
        )
    tracks: dict[str, dict[str, np.ndarray]] = {}
    motions: dict[str, dict[str, dict[str, np.ndarray] | None]] = {}
    deformed: dict[str, dict[str, list[np.ndarray]]] = {}
    metrics: list[dict] = []
    for clip in clips:
        source_tracks = tracks_for(run_dir, clip, source_similarity, args.source_motion)
        candidate_motion = (
            saved_motion_for_clip(saved_candidate_motion, master, clip)
            if saved_candidate_motion is not None
            else None
        )
        candidate_tracks = (
            candidate_motion["frame_joints"]
            if candidate_motion is not None
            else tracks_for(run_dir, clip, candidate_similarity, args.candidate_motion)
        )
        if len(source_tracks) != len(candidate_tracks):
            raise SystemExit(f"fail-closed: {clip} source/candidate track counts disagree")
        tracks[clip] = {"source": source_tracks, "candidate": candidate_tracks}
        motions[clip] = {"source": None, "candidate": candidate_motion}
        source_deformed = bake(source_bind, source_tracks)
        candidate_deformed = bake(candidate_bind, candidate_tracks, candidate_motion)
        deformed[clip] = {"source": source_deformed, "candidate": candidate_deformed}
        source_edges = [
            edge_stretch(
                positions=source_bind["positions"],
                indices=source_bind["indices"],
                deformed=points,
                subject_height=source_bind["height"],
            )
            for points in source_deformed
        ]
        candidate_edges = [
            edge_stretch(
                positions=candidate_bind["positions"],
                indices=candidate_bind["indices"],
                deformed=points,
                subject_height=candidate_bind["height"],
            )
            for points in candidate_deformed
        ]
        metrics.append(
            {
                "clip": clip,
                "frames": len(source_tracks),
                "source": {
                    "worstStretch": max(row["max"] for row in source_edges),
                    "worstEdgesPastReviewLimit": max(row["edgesPastReviewLimit"] for row in source_edges),
                },
                "candidate": {
                    "worstStretch": max(row["max"] for row in candidate_edges),
                    "worstEdgesPastReviewLimit": max(row["edgesPastReviewLimit"] for row in candidate_edges),
                },
            }
        )
        print(f"  prepared {clip} frames={len(source_tracks)}", flush=True)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_label = args.candidate_label
    reel_root = out_dir / f"yaw{int(args.yaw):03d}"
    views = {}
    for name, bind in (("source", source_bind), ("candidate", candidate_bind)):
        cloud = [bind["positions"]]
        for clip in clips:
            cloud.append(tracks[clip][name].reshape(-1, 3))
        views[name] = render.camera(args.yaw, np.vstack(cloud))

    for clip in clips:
        frames = []
        for index in range(len(tracks[clip]["source"])):
            left = panel(
                source_bind,
                views["source"],
                deformed[clip]["source"][index],
                tracks[clip]["source"],
                index,
                f"source | {clip}",
                motions[clip]["source"],
            )
            right = panel(
                candidate_bind,
                views["candidate"],
                deformed[clip]["candidate"][index],
                tracks[clip]["candidate"],
                index,
                f"{candidate_label} | {clip}",
                motions[clip]["candidate"],
            )
            frames.append(np.concatenate([left, np.full((left.shape[0], GAP, 3), 16.0), right], axis=1))
        gifs.gif(frames, reel_root / f"{unit}_{clip}.gif")

    master_path = None
    if not args.skip_master:
        master_frames = []
        # The master sequence contains six bookend frames that are not members of the ten replay clips.
        # Build this reel from the actual clip tracks so bookends cannot silently become idle frame zero.
        for clip in clips:
            for local in range(len(tracks[clip]["source"])):
                left = panel(
                    source_bind,
                    views["source"],
                    deformed[clip]["source"][local],
                    tracks[clip]["source"],
                    local,
                    f"source | {clip}",
                    motions[clip]["source"],
                )
                right = panel(
                    candidate_bind,
                    views["candidate"],
                    deformed[clip]["candidate"][local],
                    tracks[clip]["candidate"],
                    local,
                    f"{candidate_label} | {clip}",
                    motions[clip]["candidate"],
                )
                master_frames.append(np.concatenate([left, np.full((left.shape[0], GAP, 3), 16.0), right], axis=1))
        master_path = reel_root / f"{unit}_master.gif"
        gifs.gif(master_frames, master_path)
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact",
        "unit": unit,
        "run": str(run_dir).replace("\\", "/"),
        "sourceBind": source_bind["path"],
        "candidateBind": candidate_bind["path"],
        "sourceReport": str(Path(args.source_report).resolve()).replace("\\", "/"),
        "candidateReport": str(Path(args.candidate_report).resolve()).replace("\\", "/"),
        "sourceMotion": args.source_motion,
        "candidateMotion": args.candidate_motion,
        "candidateMotionFile": (
            str(Path(args.candidate_motion_file).resolve()).replace("\\", "/")
            if args.candidate_motion_file
            else None
        ),
        "yaw": args.yaw,
        "panelScale": int(args.panel_scale),
        "clips": metrics,
        "masterReel": str(master_path).replace("\\", "/") if master_path else None,
    }
    report_path = out_dir / "reel_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(report_path),
        "masterReel": str(master_path).replace("\\", "/") if master_path else None,
        "clips": len(clips),
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source-bind", required=True)
    parser.add_argument("--candidate-bind", required=True)
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--yaw", type=float, default=40.0)
    parser.add_argument("--panel-scale", type=int, default=1)
    parser.add_argument("--candidate-label", default="Meshy 7.1 T-pose")
    parser.add_argument(
        "--source-motion",
        choices=("registered-reference", "canonical-t-pose"),
        default="registered-reference",
    )
    parser.add_argument(
        "--candidate-motion",
        choices=("registered-reference", "canonical-t-pose", "saved-retargeted"),
        required=True,
    )
    parser.add_argument("--candidate-motion-file")
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="Write per-clip replays and metrics without retaining the memory-heavy aggregate reel",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
