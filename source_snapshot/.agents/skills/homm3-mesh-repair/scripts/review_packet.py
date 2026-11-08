"""Bounded saved-matrix diagnostic packet. Never selects or approves a fleet asset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools/homm3_meshy_frame_pose"))
from fit_mesh_rest_pipeline import job_fingerprint, skin
from reel_meshy71_candidate import load_bind, load_saved_motion, render
from owned_rerig.tpose import edge_stretch


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def identity(path):
    path = resolve(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return {"path": path.as_posix(), "sha256": digest.hexdigest()}


def replay_lineage(frames):
    if not frames or [f["globalIndex"] for f in frames] != list(range(len(frames))):
        raise ValueError("Master frames must retain consecutive global indices")
    rows = []
    for i, frame in enumerate(frames):
        same_segment = i > 0 and frame["segmentIndex"] == frames[i - 1]["segmentIndex"]
        row = {key: frame[key] for key in ("globalIndex", "clipKey", "localIndex", "segmentIndex")}
        row["replayPredecessorIndex"] = i - 1 if same_segment else None
        row["sourcePrevFrameRefPresent"] = "prevFrameRef" in frame
        if "prevFrameRef" in frame:
            row["prevFrameRef"] = frame["prevFrameRef"]
        rows.append(row)
    return rows


def verify_fit(report):
    if job_fingerprint(report["inputs"]) != report["fingerprint"]:
        raise ValueError("Fit inputs/code changed; rerun the fitter before reviewing saved matrices")


def run(candidate, out, scale=3, extra_frames=()):
    candidate, out = resolve(candidate), resolve(out)
    if scale not in (3, 4):
        raise ValueError("Use scale 3 or 4 for this bounded diagnostic")
    if out.exists():
        raise ValueError("Packet output must be new; do not mix previous reviews")
    report_path = candidate / "report.json"
    report = read(report_path)
    if report.get("status") != "experimental_candidate":
        raise ValueError("No completed experimental candidate; inspect fit failure first")
    verify_fit(report)
    inputs = report["inputs"]
    run_dir = resolve(inputs["runDir"])
    master_path = run_dir / "linked_master/master_sequence/master_sequence.json"
    master = read(master_path)
    if master["unit"] != report["unit"]:
        raise ValueError("Candidate and master unit differ")
    lineage = replay_lineage(master["frames"])
    bind_path, motion_path = candidate / "fitted_bind.glb", candidate / "retargeted_motion.npz"
    bind = load_bind(bind_path)
    d = bind["delivered"]
    motion = load_saved_motion(motion_path, master, len(d["heads"]))
    if report["frames"] != len(lineage):
        raise ValueError("Fit report and master frame counts differ")
    paths = [report_path, bind_path, motion_path, master_path, resolve(inputs["mesh"]),
             resolve(inputs["sourceReport"]), run_dir / "linked_master/capture/capture/raw_capture.npz",
             Path(__file__), ROOT / "tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py"]
    if inputs.get("propAttachments"):
        paths.append(resolve(inputs["propAttachments"]))
    if inputs.get("authoredSkinMap"):
        paths.append(resolve(inputs["authoredSkinMap"]))
    if inputs.get("handClearance"):
        paths.append(resolve(inputs["handClearance"]))
    if inputs.get("propOrientation"):
        paths.append(resolve(inputs["propOrientation"]))
    identities = [identity(path) for path in paths]
    positions = bind["positions"]
    frames = [skin(positions, d["joints"], d["weights"], r, t)
              for r, t in zip(motion["rotations"], motion["offsets"])]
    metrics = [edge_stretch(positions=positions, indices=bind["indices"], deformed=p,
                            subject_height=bind["height"]) for p in frames]
    selected = {0}
    for clip in ("g02_idle", "g00_move", "g12_attack_front", "g15_shoot_front", "g05_death"):
        indices = [i for i, f in enumerate(master["frames"]) if f["clipKey"] == clip]
        if indices:
            selected.add(indices[len(indices) // 2])
    worst = sorted(range(len(frames)), key=lambda i: metrics[i]["max"], reverse=True)[:2]
    selected.update(worst)
    if len(extra_frames) > 8 or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(frames) for i in extra_frames):
        raise ValueError("At most eight explicit additional frame indices are allowed")
    selected.update(extra_frames)
    # One fixed camera for all selected frames; no frame-specific reframing hides excursions.
    render.PANEL = (360 * scale, 520 * scale)
    camera = render.camera(25, np.concatenate([positions] + frames))
    out.mkdir(parents=True, exist_ok=False)
    panels = []
    for i in sorted(selected):
        normals = skin(bind["restNormals"], d["joints"], d["weights"], motion["rotations"][i])
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        pixels = render.textured(camera, deformed=frames[i], normals=normals,
                                 surface=bind["surface"], indices=bind["indices"])
        path = out / f"frame_{i:03d}_{master['frames'][i]['clipKey']}.png"
        Image.fromarray(np.clip(pixels, 0, 255).astype("uint8")).save(path)
        source = resolve(master["frames"][i]["sourcePng"])
        source_identity = identity(source)
        if source_identity["sha256"] != master["frames"][i]["sourceSha256"]:
            raise ValueError(f"Source plate changed: {source}")
        panels.append({**lineage[i], "image": identity(path), "sourcePlate": source_identity,
                       "pixels": list(render.PANEL), "stretch": metrics[i]})
    rest = candidate / "rest_overlay.png"
    rest_panels = []
    with Image.open(rest) as image:
        if image.width % 2 or image.height < 1560:
            raise ValueError("Expected full-resolution two-view rest overlay at scale >=3")
        half = image.width // 2
        for index, label in enumerate(("front", "side")):
            path = out / f"rest_{label}.png"
            image.crop((index * half, 0, (index + 1) * half, image.height)).save(path)
            rest_panels.append(identity(path))
    summary = {
        "unit": report["unit"], "proof": "generated diagnostic only; visual review required",
        "qualityAccepted": False, "inputs": identities, "fitFingerprint": report["fingerprint"],
        "restPanels": rest_panels,
        "frameCount": len(frames), "panels": panels, "worstStretchFrames": worst,
        "stretchDefinition": "abs(posed_edge/rest_edge - 1); not the length ratio or an acceptance score",
        "lineage": lineage,
        "continuity": "Recorded within-segment replay order only; loop/transition quality unproven",
        "bilateralAudit": "not performed; audit this bind rather than inheriting an older bind result",
        "detailReel": identity(candidate / "detail_reel.gif") if (candidate / "detail_reel.gif").is_file() else None,
    }
    (out / "packet.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"unit": summary["unit"], "frameCount": len(frames), "panels": len(panels),
                      "worstStretchFrames": worst, "packet": str(out / "packet.json"),
                      "qualityAccepted": False}))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scale", type=int, choices=(3, 4), default=3)
    parser.add_argument("--frames", type=int, nargs="*", default=[], help="Additional suspected failure frames, at most eight")
    args = parser.parse_args()
    run(args.candidate, args.out, args.scale, args.frames)
