"""Offline four-way material/motion comparison; never builds or installs a mod."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.spatial.transform import Rotation, Slerp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))
from eagle_glb import gltf_world_matrices
from glb_skeleton import load_bind_skeleton
from mesh_preview import skin_vertices
from verify_calibrated_export import _serialized_local_rotations
from skin_image_objective import SkinImageRenderer
from gpu_cascade_batch_lock import cascade_batch_lock


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay(path: Path, samples: np.ndarray):
    skin = load_bind_skeleton(path)
    times, rotations, translations, _ = _serialized_local_rotations(path, allow_root_motion=True)
    if len(times) == 1:
        interpolated = np.repeat(rotations, len(samples), axis=0)
    else:
        interpolated = np.stack([Slerp(times, Rotation.from_matrix(rotations[:, joint]))(samples).as_matrix()
                                 for joint in range(len(skin.names))], axis=1)
    positions = np.stack([np.stack([np.interp(samples, times, translations[:, joint, axis])
                                   for axis in range(3)], axis=-1)
                          for joint in range(len(skin.names))], axis=1)
    meshes = np.stack([skin_vertices(skin, gltf_world_matrices(local_rotation=r, local_translation=t,
                                                             parents=np.asarray(skin.parents)))
                       for r, t in zip(interpolated, positions)])
    if not np.isfinite(meshes).all():
        raise ValueError("non-finite replay")
    return skin, meshes


def union_camera(basis, meshes, resolution):
    camera = dict(basis)
    points = np.concatenate([mesh.reshape(-1, 3) for mesh in meshes])
    right, down, forward = [np.asarray(camera[k], dtype=float) for k in ("right", "down", "forward")]
    x, y, z = points @ right, points @ down, points @ forward
    scale = (resolution - 1) / (max(np.ptp(x), np.ptp(y), 1e-6) * 1.14)
    camera.update(scale=float(scale), offset=[float((resolution - 1) / 2 - (x.min() + x.max()) * scale / 2),
                                             float((resolution - 1) / 2 - (y.min() + y.max()) * scale / 2)],
                  depth_center=float((z.min() + z.max()) / 2), depth_span=float(max(np.ptp(z) * .6, 1e-4)),
                  resolution=resolution)
    return camera


def compare_geometry(base, styled):
    if base.names != styled.names:
        raise ValueError("style changed skeleton identity")
    for key in ("vertices", "triangles", "uvs", "vertex_joints", "vertex_weights", "inverse_bind",
                "parents", "rest_local_rotation", "rest_local_translation"):
        left, right = getattr(base, key), getattr(styled, key)
        if not np.array_equal(left, right):
            raise ValueError(f"style changed fixed {key}")


def edge_strain(triangles, baseline, candidate):
    """Measure added deformation against the same baseline pose, not rest."""
    edges = np.unique(np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]],
                                              triangles[:, [2, 0]]]), axis=1), axis=0)
    lengths = [np.linalg.norm(mesh[:, edges[:, 0]] - mesh[:, edges[:, 1]], axis=-1)
               for mesh in (baseline, candidate)]
    valid = lengths[0] > 1e-7
    strain = np.abs(lengths[1][valid] / lengths[0][valid] - 1)
    return {"metric": "absolute edge length ratio change from baseline at same time",
            "p50": float(np.quantile(strain, .5)), "p95": float(np.quantile(strain, .95)),
            "p99": float(np.quantile(strain, .99)), "max": float(strain.max()),
            "fractionOver25Percent": float(np.mean(strain > .25)),
            "disposition": "diagnostic only; no automatic acceptance or damping"}


def run(unit, clip, styled_glb, soft_texture, out, resolution=288, idle_duration_scale=1.0):
    import torch
    started = time.perf_counter()
    if out.exists():
        raise FileExistsError(out)
    selected = json.loads((HERE / "stronghold_ingame_test.json").read_text())
    row = next(row for row in selected["units"] if row["labSid"] == unit)
    delivered = ROOT / "artifacts/homm3_mocap_v2/stronghold_oe_approved_v1/units" / unit / "delivery_manifest.json"
    delivery = json.loads(delivered.read_text())
    item = next(item for item in delivery["clips"] if item["contractName"] == clip)
    raw = Path(item["rawSourceGlb"])
    if not raw.is_file():
        raise FileNotFoundError(
            "raw mocap GLB is gone with stronghold_ingame_test_v1; "
            f"this preview needs that source at {raw}"
        )
    if sha(raw) != item["rawSourceGlbSha256"]:
        raise ValueError("baseline raw GLB hash drift")
    times, *_ = _serialized_local_rotations(raw, allow_root_motion=True)
    styled_times, *_ = _serialized_local_rotations(styled_glb, allow_root_motion=True)
    if idle_duration_scale != 1.0 and (clip != "Unit_Idle" or idle_duration_scale != 2.5):
        raise ValueError("only the approved 2.5x idle duration comparison is supported")
    if not np.array_equal(np.asarray(times * idle_duration_scale, dtype=np.float32), styled_times):
        raise ValueError("style changed clip timing")
    source_duration = float(times[-1]) if len(times) > 1 else 1 / item["fps"]
    styled_duration = source_duration * idle_duration_scale
    # Five original cycles equal two slowed cycles, keeping both GIF seams aligned.
    duration = styled_duration * (2 if idle_duration_scale != 1.0 else 1)
    frame_count = max(2, round(duration * 24))
    samples = np.linspace(0, duration, frame_count, endpoint=False) if len(times) > 1 else np.zeros(frame_count)
    baseline_samples = np.mod(samples, source_duration) if idle_duration_scale != 1.0 else samples
    base, baseline_meshes = replay(raw, baseline_samples)
    styled_samples = np.mod(samples, styled_duration) if idle_duration_scale != 1.0 else samples
    styled, styled_meshes = replay(styled_glb, styled_samples)
    compare_geometry(base, styled)
    camera_path = (ROOT / row["fitReport"]).parent / "camera.json"
    camera = union_camera(json.loads(camera_path.read_text()), [baseline_meshes, styled_meshes], resolution)
    baked = Path(delivery["pbr"]["albedo"])
    textures = [np.asarray(Image.open(path).convert("RGB")) for path in (baked, soft_texture)]
    results = []
    with cascade_batch_lock(ROOT):
        with torch.no_grad():
            for texture in textures:
                renderer = SkinImageRenderer(base.triangles, base.uvs, texture, camera, resolution)
                for mesh in (baseline_meshes, styled_meshes):
                    rgb, alpha = renderer.render(torch.as_tensor(mesh, device="cuda", dtype=torch.float32))
                    background = torch.as_tensor([.20, .23, .24], device="cuda")
                    frames = (rgb + (1 - alpha) * background).clamp(0, 1)
                    results.append((frames.cpu().numpy() * 255).round().astype(np.uint8))
                    if float(alpha.sum((1, 2, 3)).min()) < resolution:
                        raise ValueError("blank or implausibly small rendered mesh")
                del renderer
    labels = (("Current", "2.5x slower idle", "Softer bake", "Slower idle + softer bake")
              if idle_duration_scale != 1.0 else
              ("Current", "Stronger motion", "Softer bake", "Motion + softer bake"))
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
    title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
    header, label_height, gap = 42, 30, 8
    width = 2 * resolution + gap
    height = header + 2 * (resolution + label_height) + gap
    frames = []
    for index in range(frame_count):
        frame = Image.new("RGB", (width, height), (29, 34, 36))
        draw = ImageDraw.Draw(frame)
        draw.text((10, 10), f"{unit.removeprefix('h3_').replace('_', ' ').title()} | {clip.removeprefix('Unit_')}",
                  fill=(238, 240, 240), font=title_font)
        for panel, (label, pictures) in enumerate(zip(labels, results)):
            x, y = (panel % 2) * (resolution + gap), header + (panel // 2) * (resolution + label_height + gap)
            draw.text((x + 8, y + 5), label, fill=(222, 229, 230), font=font)
            frame.paste(Image.fromarray(pictures[index]), (x, y + label_height))
        frames.append(frame)
    out.mkdir(parents=True)
    # GIF delays are centiseconds; distribute rounding instead of speeding up every frame.
    boundaries = np.rint(np.arange(frame_count + 1) * duration * 100 / frame_count).astype(int) * 10
    delays = np.maximum(10, np.diff(boundaries)).tolist()
    gif = out / "comparison.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=delays, loop=0, disposal=2)
    frames[len(frames) // 2].save(out / "comparison.png")
    movement = np.linalg.norm(styled_meshes - baseline_meshes, axis=-1)
    report = {"schema": "oe_style_offline_preview.v1", "unit": unit, "clip": clip, "accepted": False,
              "proof": "offline textured LBS preview; not an OE shader or runtime render",
              "rawGlb": str(raw), "rawSha256": sha(raw), "styledGlb": str(styled_glb), "styledSha256": sha(styled_glb),
              "baselineTexture": str(baked), "baselineTextureSha256": sha(baked),
              "softTexture": str(soft_texture), "softTextureSha256": sha(soft_texture),
              "cameraSource": str(camera_path), "sharedCamera": camera, "sourceDurationSeconds": source_duration,
              "idleDurationScale": idle_duration_scale, "styledDurationSeconds": styled_duration,
              "comparisonDurationSeconds": duration,
              "gifDurationSeconds": sum(delays) / 1000, "frames": frame_count, "sourceInfluenceSlots": int(base.vertex_weights.shape[1]),
              "styleMaxVertexDelta": float(movement.max()),
              "addedEdgeStrain": (edge_strain(base.triangles, baseline_meshes, styled_meshes)
                                  if idle_duration_scale == 1.0 else
                                  {"disposition": "not compared; panels have different animation phases"}),
              "elapsedSeconds": time.perf_counter() - started,
              "gif": str(gif)}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--clip", required=True)
    parser.add_argument("--styled-glb", type=Path, required=True)
    parser.add_argument("--soft-texture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--idle-duration-scale", type=float, choices=[1.0, 2.5], default=1.0)
    args = parser.parse_args()
    run(args.unit, args.clip, args.styled_glb.resolve(), args.soft_texture.resolve(), args.out.resolve(),
        idle_duration_scale=args.idle_duration_scale)
