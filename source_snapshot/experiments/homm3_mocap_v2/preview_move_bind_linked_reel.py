#!/usr/bin/env python3
"""Linked DEF reel: this move-bind T2 mesh/skin, every saved Roc capture, idle between actions.

Motion is reconstruct_ab path A on the capture-skeleton bind (flight frame 0).
Clip frames are the corpus sourceIndices (authored DEF frames, not idle context).
Move is wrapped by native start/stop; other actions are bookended by the idle clip.
No weights or bones are refit. Generated-artifact only — not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(EXPERIMENT.parents[1] / "tools/homm3_silhouette_pose_fit"))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO, SOURCE_FRAME_MS  # noqa: E402
from pin import sha256_file  # noqa: E402
from prepare_move_bind_capture_bind import DEFAULT_OUT as CAPTURE_BIND_GLB, load_capture  # noqa: E402
from reconstruct_ab import reconstruct_ab  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_skin_bundle  # noqa: E402
from run_skin_weight_pilot import skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402

WEIGHTS = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit/candidate_weights.npz"
CAMERA = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit/camera.json"
CORPUS = REPO / "artifacts/homm3_mocap_v2/skin_mesh_pilot/captures_v2/corpus.json"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/linked_reel"
SKIP = frozenset({"g09_unused_a", "g10_unused_b"})
# Native movement chain is start -> cycle -> stop. Everything else is idle-bookended.
REEL: tuple[tuple[str, int], ...] = (
    ("g02_idle", 1),
    ("g20_move_start", 1),
    ("g00_move", 2),
    ("g21_move_end", 1),
    ("g02_idle", 1),
    ("g01_mouseover", 1),
    ("g02_idle", 1),
    ("g03_hitted", 1),
    ("g02_idle", 1),
    ("g04_defence", 1),
    ("g02_idle", 1),
    ("g11_attack_up", 1),
    ("g02_idle", 1),
    ("g12_attack_front", 1),
    ("g02_idle", 1),
    ("g13_attack_down", 1),
    ("g02_idle", 1),
    ("g07_turn_left", 1),
    ("g02_idle", 1),
    ("g08_turn_right", 1),
    ("g02_idle", 1),
    ("g05_death", 1),
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def permute_capture_to_bind(capture: dict[str, Any], skin: dict[str, Any]) -> np.ndarray:
    if sorted(capture["names"]) != sorted(skin["names"]):
        raise ValueError("capture joint names do not match the bind")
    capture_index = {name: index for index, name in enumerate(capture["names"])}
    order = np.asarray([capture_index[name] for name in skin["names"]], dtype=np.int64)
    capture_parent_names = [
        None if int(capture["parents"][index]) < 0 else capture["names"][int(capture["parents"][index])]
        for index in order
    ]
    bind_parent_names = [None if int(parent) < 0 else skin["names"][int(parent)] for parent in skin["parents"]]
    if capture_parent_names != bind_parent_names:
        raise ValueError("capture hierarchy does not match the bind")
    return capture["positions"][:, order]


def frame_camera(base: dict[str, Any], vertices: np.ndarray, resolution: int, *, pad: float = 1.12) -> dict[str, Any]:
    """Keep the registered yaw/pitch; refit scale/offset/depth so every posed vertex is on canvas."""
    right = np.asarray(base["right"], dtype=np.float64)
    down = np.asarray(base["down"], dtype=np.float64)
    forward = np.asarray(base["forward"], dtype=np.float64)
    pts = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    x = pts @ right
    y = pts @ down
    z = pts @ forward
    span = float(max(x.max() - x.min(), y.max() - y.min(), 1e-6)) * pad
    scale = resolution / span
    camera = dict(base)
    camera["scale"] = float(scale)
    camera["offset"] = [resolution / 2 - scale * float(x.mean()), resolution / 2 - scale * float(y.mean())]
    camera["pxPerWorld"] = float(scale)
    camera["screenOffsetPx"] = list(camera["offset"])
    camera["depth_center"] = float(z.mean())
    camera["depth_span"] = float(max(z.max() - z.min(), 1e-3) * pad)
    camera["resolution"] = int(resolution)
    camera["framingPolicy"] = "registered_yaw_pitch_union_posed_aabb"
    return camera


def letterbox_sprite(path: Path, resolution: int) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        box = rgba.getbbox()
        if box is None:
            raise ValueError(f"empty sprite {path}")
        cropped = rgba.crop(box)
    scale = min(resolution / cropped.size[0], resolution / cropped.size[1])
    size = (max(1, int(round(cropped.size[0] * scale))), max(1, int(round(cropped.size[1] * scale))))
    resized = cropped.resize(size, Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 255))
    canvas.paste(resized, ((resolution - size[0]) // 2, (resolution - size[1]) // 2), resized)
    values = np.asarray(canvas, dtype=np.float32) / 255.0
    rgb = values[..., :3] * values[..., 3:4]
    return rgb


def load_weights(path: Path, names: list[str]) -> np.ndarray:
    raw = np.load(path, allow_pickle=False)
    stored = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in np.asarray(raw["names"]).tolist()]
    if stored != list(names):
        raise ValueError("candidate weights joint order does not match the bind GLB")
    weights = np.asarray(raw["weights"], dtype=np.float64)
    if weights.ndim != 2 or weights.shape[1] != len(names):
        raise ValueError(f"candidate weights shape {weights.shape} does not match {len(names)} joints")
    return weights


def run(*, output: Path, bind_glb: Path, weights_path: Path, corpus_path: Path, camera_path: Path, resolution: int, overwrite: bool) -> dict[str, Any]:
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {output} (pass --overwrite)")
    if output.exists():
        for child in output.iterdir():
            if child.is_file():
                child.unlink()
    output.mkdir(parents=True, exist_ok=True)

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("unit") != "h3_roc":
        raise ValueError(f"corpus unit is {corpus.get('unit')!r}, expected h3_roc")
    entries = {str(entry["key"]): entry for entry in corpus["captures"]}
    missing = [key for key, _ in REEL if key not in entries]
    if missing:
        raise FileNotFoundError(f"corpus is missing reel clips: {missing}")

    skin = load_skin_bundle(bind_glb)
    weights = load_weights(weights_path, skin["names"])
    base_camera = json.loads(camera_path.read_text(encoding="utf-8"))

    clips: dict[str, dict[str, Any]] = {}
    for key, entry in entries.items():
        if key in SKIP:
            continue
        capture = load_capture(Path(entry["capture"]))
        indices = [int(i) for i in entry["sourceIndices"]]
        sprites = [Path(p) for p in entry["frames"]]
        if len(sprites) != len(indices):
            raise ValueError(f"{key}: {len(sprites)} sprite frames vs {len(indices)} sourceIndices")
        positions = permute_capture_to_bind(capture, skin)[indices]
        ab = reconstruct_ab(capture_positions=positions, offsets=skin["offsets"], parents=skin["parents"])
        clips[key] = {
            "jointWorld": np.asarray(ab["jointWorldA"], dtype=np.float64),
            "sprites": sprites,
            "sourceIndices": indices,
            "captureSha256": capture["sha256"],
            "lengthErrorMax": float(ab["fixedLengthErrorMax"]),
            "residualAMax": float(ab["residualAMax"]),
        }

    rest_xyz = skin["restWorld"][:, :3, 3] if skin["restWorld"].ndim == 3 else np.asarray(skin["restWorld"], dtype=np.float64)
    move0 = float(np.abs(clips["g00_move"]["jointWorld"][0][:, :3, 3] - rest_xyz).max())

    sequence: list[dict[str, Any]] = []
    for key, repeats in REEL:
        clip = clips[key]
        for _ in range(repeats):
            for frame in range(len(clip["jointWorld"])):
                sequence.append({"key": key, "frame": frame, "label": f"{key} f{frame:02d}"})

    worlds = np.stack([clips[item["key"]]["jointWorld"][item["frame"]] for item in sequence])
    output.mkdir(parents=True, exist_ok=True)
    with cascade_batch_lock(REPO):
        transforms = torch.as_tensor(worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(
            np.column_stack((skin["vertices"], np.ones(len(skin["vertices"])))), dtype=torch.float32, device="cuda"
        )
        candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest).detach()
        posed = skin_with(candidates, torch.as_tensor(weights, dtype=torch.float32, device="cuda")).detach().cpu().numpy()
        camera = frame_camera(base_camera, posed, resolution)
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, alpha = renderer.render(torch.as_tensor(posed, dtype=torch.float32, device="cuda"))
        mesh_rgb = (rgb.detach().cpu().numpy() * alpha.detach().cpu().numpy())

    gif_frames = []
    for index, item in enumerate(sequence):
        sprite = letterbox_sprite(clips[item["key"]]["sprites"][item["frame"]], resolution)
        mesh = np.clip(mesh_rgb[index], 0, 1)
        row = Image.new("RGB", (resolution * 2, resolution + 28), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 6), item["label"], fill="white")
        draw.text((4, 16), "sprite", fill=(180, 180, 200))
        draw.text((resolution + 4, 16), "mesh+skin (fixed mocap)", fill=(180, 180, 200))
        row.paste(Image.fromarray(np.uint8(sprite * 255)), (0, 28))
        row.paste(Image.fromarray(np.uint8(mesh * 255)), (resolution, 28))
        gif_frames.append(row)

    gif_path = output / "roc_linked_reel.gif"
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=int(round(SOURCE_FRAME_MS)),
        loop=0,
    )
    contact = Image.new("RGB", (gif_frames[0].size[0], gif_frames[0].size[1] * min(8, len(gif_frames))))
    step = max(1, len(gif_frames) // 8)
    for i, frame in enumerate(gif_frames[::step][:8]):
        contact.paste(frame, (0, i * gif_frames[0].size[1]))
    contact.save(output / "roc_linked_reel_contact.png")

    report = {
        "ok": True,
        "proof": "generated-artifact",
        "visualAcceptance": "unreviewed",
        "paradigm": "owned_bones_capture_skeleton_frame0_bind",
        "motionPolicy": "reconstruct_ab_path_A_fixed_length_rotations_on_flight_bind",
        "bind": str(bind_glb).replace("\\", "/"),
        "bindSha256": sha256_file(bind_glb),
        "weights": str(weights_path).replace("\\", "/"),
        "weightsSha256": sha256_file(weights_path),
        "corpus": str(corpus_path).replace("\\", "/"),
        "corpusSha256": sha256_file(corpus_path),
        "g00MoveFrame0JointErrorVsBind": move0,
        "g00MoveFrame0Note": (
            "Bind rest is mocap_intermediate move frame 0; this reel's g00_move is the later "
            "skin-corpus capture of the same sprites (idle-context episode). Frame 0 is therefore "
            "not identity on this bind; all clips share reconstruct_ab onto the flight skeleton."
        ),
        "reel": [{"key": key, "repeats": repeats, "authoredFrames": len(clips[key]["jointWorld"])} for key, repeats in REEL],
        "skipped": sorted(SKIP),
        "frameCount": len(sequence),
        "camera": {k: camera[k] for k in ("yawDeg", "pitchDeg", "scale", "offset", "framingPolicy", "resolution")},
        "gif": str(gif_path).replace("\\", "/"),
        "note": (
            "Mesh rest is move frame 0 (flight). Idle and ground actions are the same skeleton "
            "rotated toward those captures; the surface stays the flight-shaped T2 mesh."
        ),
    }
    _write_json(output / "report.json", report)
    print(json.dumps({"ok": True, "gif": report["gif"], "frames": len(sequence)}, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bind", type=Path, default=CAPTURE_BIND_GLB)
    parser.add_argument("--weights", type=Path, default=WEIGHTS)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--camera", type=Path, default=CAMERA)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    def absolute(path: Path) -> Path:
        return (path if path.is_absolute() else REPO / path).resolve()

    run(
        output=absolute(args.output),
        bind_glb=absolute(args.bind),
        weights_path=absolute(args.weights),
        corpus_path=absolute(args.corpus),
        camera_path=absolute(args.camera),
        resolution=int(args.resolution),
        overwrite=bool(args.overwrite),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
