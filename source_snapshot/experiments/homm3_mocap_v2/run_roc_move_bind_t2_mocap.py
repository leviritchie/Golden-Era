#!/usr/bin/env python3
"""Meshy T2 Roc mesh from a roc_flight move sprite bind pose, then replay saved mocap.

Unlike run_roc_portrait_t2_mocap.py (unit portrait, forced t-pose), this uses a
side-profile move frame as the image-to-3d reference and omits pose_mode so Meshy
reconstructs the flyer in that pose instead of reposing to T-pose.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from donor_eagle import (  # noqa: E402
    bind_world_matrices,
    compute_rest_joints,
    inverse_bind_matrices,
    load_donor_package,
    skin_dense,
)
from eagle_preview import write_bind_sheet, write_mesh_gif, write_overlay_gif  # noqa: E402
from evaluation import EVALUATION_CASES  # noqa: E402
from glb_skeleton import _accessor, _base_color_albedo, read_glb  # noqa: E402
from known_rest_mesh import align_surface_to_rest  # noqa: E402
from pin import numbered_pngs, sha256_file  # noqa: E402
from reconstruct_ab import reconstruct_ab  # noqa: E402
from run_eagle_skinned_roc import load_saved_capture  # noqa: E402
from shared_camera import freeze_shared_camera  # noqa: E402

REPO = EXPERIMENT.parents[1]
MESHY_TOOLS = REPO / "tools" / "homm3_meshy_frame_pose"
if str(MESHY_TOOLS) not in sys.path:
    sys.path.insert(0, str(MESHY_TOOLS))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    create_rigging,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

MOVE_FRAMES = (
    REPO
    / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move_shadow_culled"
)
CAPTURE = (
    REPO
    / "artifacts/homm3_mocap_v2/mocap_intermediate/h3_roc/move"
    / "intermediate_v1_primary/capture/raw_capture.npz"
)
ORIGINAL_ROC = REPO / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1"
DEFAULT_BIND_FRAME = "00"
POLYCOUNT = 12000
K_BONES = 4
CHROMA_GREEN = (0, 255, 0)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prepare_meshy_bind_image(source: Path, dest: Path) -> dict[str, Any]:
    """Flatten alpha sprites onto chroma green for Meshy image-to-3d."""
    image = Image.open(source).convert("RGBA")
    arr = np.asarray(image)
    alpha = arr[:, :, 3].astype(np.float64) / 255.0
    rgb = arr[:, :, :3].astype(np.float64)
    bg = np.array(CHROMA_GREEN, dtype=np.float64)
    flat = (rgb * alpha[:, :, None] + bg * (1.0 - alpha[:, :, None])).astype(np.uint8)
    out = np.dstack([flat, np.full(alpha.shape, 255, dtype=np.uint8)])
    opaque = int((arr[:, :, 3] > 8).sum())
    if opaque < 500:
        raise RuntimeError(f"bind frame has too few opaque pixels: {opaque}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGBA").save(dest)
    return {
        "source": str(source).replace("\\", "/"),
        "prepared": str(dest).replace("\\", "/"),
        "size": list(image.size),
        "opaquePixels": opaque,
        "chromaGreen": list(CHROMA_GREEN),
    }


def load_glb_surface(path: Path) -> dict[str, Any]:
    doc = read_glb(path)
    json_doc = doc["json"]
    for mesh in json_doc.get("meshes") or ():
        for primitive in mesh.get("primitives") or ():
            attrs = primitive.get("attributes") or {}
            if "POSITION" not in attrs:
                continue
            vertices = _accessor(doc, doc["bin"], int(attrs["POSITION"])).reshape(-1, 3).astype(np.float64)
            uvs = None
            if "TEXCOORD_0" in attrs:
                uvs = _accessor(doc, doc["bin"], int(attrs["TEXCOORD_0"])).reshape(-1, 2).astype(np.float64)
            triangles = None
            if "indices" in primitive:
                triangles = _accessor(doc, doc["bin"], int(primitive["indices"])).astype(np.int32)
                if triangles.size % 3 != 0:
                    raise ValueError(f"{path} indices are not triangles")
                triangles = triangles.reshape(-1, 3)
            albedo = _base_color_albedo(doc, primitive)
            if triangles is None or len(vertices) < 32:
                continue
            return {
                "vertices": vertices,
                "triangles": triangles,
                "uvs": uvs,
                "albedo": albedo,
                "skinned": "JOINTS_0" in attrs,
            }
    raise ValueError(f"{path} has no triangle surface")


def nearest_bone_weights(vertices: np.ndarray, rest_joints: np.ndarray, *, k: int) -> np.ndarray:
    verts = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(rest_joints, dtype=np.float64)
    if k < 1 or k > len(joints):
        raise ValueError(f"k={k} is not valid for {len(joints)} joints")
    delta = verts[:, None, :] - joints[None, :, :]
    dist = np.sqrt((delta * delta).sum(axis=2))
    nearest = np.argpartition(dist, kth=k - 1, axis=1)[:, :k]
    picked = np.take_along_axis(dist, nearest, axis=1)
    weights = 1.0 / (picked * picked + 1e-8)
    weights = weights / weights.sum(axis=1, keepdims=True)
    dense = np.zeros((len(verts), len(joints)), dtype=np.float64)
    rows = np.repeat(np.arange(len(verts)), k)
    dense[rows, nearest.reshape(-1)] = weights.reshape(-1)
    return dense


def generate_mesh(
    out_dir: Path,
    image: Path,
    *,
    bind_frame: str,
    clip: str = "move",
    stem: str | None = None,
    try_rig: bool = True,
    resume_image_task_id: str | None = None,
    resume_rig_task_id: str | None = None,
    ai_model: str = "meshy-t2",
) -> dict[str, Any]:
    api_key = load_api_key()
    # Meshy 7 is Standard generation; Smart Topology is restricted to T1/T2.
    model_type = "smart-topology" if ai_model in {"meshy-t1", "meshy-t2"} else "standard"
    target_polycount = POLYCOUNT if model_type == "smart-topology" else 300_000
    should_remesh = None if model_type == "smart-topology" else True
    meshes = out_dir / "meshes"
    tasks = out_dir / "tasks"
    meshes.mkdir(parents=True, exist_ok=True)
    tasks.mkdir(parents=True, exist_ok=True)
    stem = stem or f"h3_roc_{clip}_bind_t2"
    glb = meshes / f"{stem}.glb"
    meta: dict[str, Any] = {
        "unitSid": "h3_roc",
        "clip": clip,
        "bindFrame": bind_frame,
        "ai_model": ai_model,
        "model_type": model_type,
        "should_texture": True,
        "enable_pbr": True,
        "target_polycount": target_polycount,
        "should_remesh": should_remesh,
        "pose_mode": None,
        "image": str(image).replace("\\", "/"),
        "proof": (
            f"generated-artifact — Meshy t2 from roc {clip} bind frame; "
            "pose_mode omitted so Meshy keeps the sprite pose; not OE runtime"
        ),
    }
    if resume_image_task_id:
        tid = resume_image_task_id
        print(f"[gen] resume image-to-3d {tid}", flush=True)
    else:
        print("[gen] create image-to-3d pose_mode=none (sprite bind pose)", flush=True)
        tid = create_image_to_3d(
            api_key,
            image_path=image,
            should_texture=True,
            target_polycount=target_polycount,
            model_type=model_type,
            ai_model=ai_model,
            pose_mode=None,
            should_remesh=should_remesh,
            enable_pbr=True,
        )
    meta["imageTaskId"] = tid
    # Persist the ID before polling: process interruption must not orphan a paid task.
    _write_json(tasks / "image_to_3d.json", {"taskId": tid, "status": "SUBMITTED"})
    task = poll_task(api_key, "image-to-3d", tid, timeout_s=2400, interval_s=8.0)
    _write_json(
        tasks / "image_to_3d.json",
        {"taskId": tid, **{k: task.get(k) for k in ("status", "progress", "consumed_credits", "task_error")}},
    )
    meta["imageStatus"] = str(task.get("status") or "")
    meta["imageCredits"] = task.get("consumed_credits")
    if meta["imageStatus"] != "SUCCEEDED":
        meta["error"] = task_error_message(task)
        return meta
    urls = task.get("model_urls") if isinstance(task.get("model_urls"), dict) else {}
    url = urls.get("glb") if isinstance(urls, dict) else None
    if not isinstance(url, str):
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        url = (result.get("model_urls") or {}).get("glb") if isinstance(result, dict) else None
    if not isinstance(url, str):
        meta["error"] = "image-to-3d succeeded without a GLB URL"
        return meta
    download_url(url, glb)
    meta["meshGlb"] = str(glb.resolve()).replace("\\", "/")
    meta["meshBytes"] = glb.stat().st_size
    print(f"[gen] saved {glb} ({meta['meshBytes']} bytes)", flush=True)

    if not try_rig:
        return meta
    rig_glb = out_dir / "rigged" / f"{stem}_rigged.glb"
    rig_glb.parent.mkdir(parents=True, exist_ok=True)
    print("[gen] create rigging (humanoid API; expected to fail on a bird)", flush=True)
    try:
        if resume_rig_task_id:
            rid = resume_rig_task_id
            print(f"[gen] resume rigging {rid}", flush=True)
        else:
            rid = create_rigging(api_key, input_task_id=tid, height_meters=1.4)
        meta["rigTaskId"] = rid
        # Match the image-task checkpoint; Smart Rig also consumes credits.
        _write_json(tasks / "rigging.json", {"taskId": rid, "status": "SUBMITTED"})
        rtask = poll_task(api_key, "rigging", rid, timeout_s=1200, interval_s=8.0)
        meta["rigStatus"] = str(rtask.get("status") or "")
        meta["rigCredits"] = rtask.get("consumed_credits")
        _write_json(tasks / "rigging.json", {"taskId": rid, "status": meta["rigStatus"]})
        if meta["rigStatus"] == "SUCCEEDED":
            result = rtask.get("result") if isinstance(rtask.get("result"), dict) else {}
            rurl = None
            if isinstance(result, dict):
                rurl = result.get("rigged_character_glb_url")
            if isinstance(rurl, str):
                download_url(rurl, rig_glb)
                meta["riggedGlb"] = str(rig_glb.resolve()).replace("\\", "/")
        else:
            meta["rigError"] = task_error_message(rtask)
    except RuntimeError as exc:
        meta["rigStatus"] = "FAILED"
        meta["rigError"] = str(exc)[:1000]
        print(f"[gen] rig failed as expected-or-not: {meta['rigError'][:240]}", flush=True)
    return meta


def replay_mocap(out_dir: Path, mesh_glb: Path) -> dict[str, Any]:
    case = EVALUATION_CASES["roc_flight"]
    donor = load_donor_package()
    capture = load_saved_capture(CAPTURE, donor)
    surface = load_glb_surface(mesh_glb)
    offsets = np.asarray(donor["captureSkeleton"]["offsets"], dtype=np.float64)
    parents = np.asarray(donor["captureSkeleton"]["parents"], dtype=np.int64)
    rest_joints = compute_rest_joints(offsets, parents)
    aligned = align_surface_to_rest(surface["vertices"], rest_joints)
    vertices = aligned["vertices"]
    weights = nearest_bone_weights(vertices, rest_joints, k=K_BONES)
    bind_world = bind_world_matrices(offsets, parents)
    ibm = inverse_bind_matrices(bind_world)
    ab = reconstruct_ab(
        capture_positions=capture["pred_position"],
        offsets=offsets,
        parents=parents,
    )
    mesh_a = [skin_dense(vertices, weights, world, ibm) for world in ab["jointWorldA"]]
    mesh_b = [skin_dense(vertices, weights, world, ibm) for world in ab["jointWorldB"]]
    cameras = freeze_shared_camera(
        np.concatenate(
            [
                vertices,
                ab["captureRootCentered"].reshape(-1, 3),
                ab["positionsA"].reshape(-1, 3),
                ab["positionsB"].reshape(-1, 3),
            ]
        ),
        width=256,
        height=256,
    )
    preview = out_dir / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    albedo = surface["albedo"]
    uvs = surface["uvs"]
    triangles = surface["triangles"]
    bind = write_bind_sheet(
        preview / "bind_sheet.png",
        cameras=cameras,
        vertices=vertices,
        triangles=triangles,
        uvs=uvs if uvs is not None else np.zeros((len(vertices), 2)),
        albedo=albedo if albedo is not None else np.full((16, 16, 4), 180, dtype=np.uint8),
        joints=rest_joints,
        parents=parents,
        title="move-bind T2 Roc aligned to Eagle capture skeleton",
    )
    sprites = [Image.open(path) for path in numbered_pngs(case.frames)]
    overlay = write_overlay_gif(
        preview / "roc_flight_ab.gif",
        cameras=cameras,
        sprites=sprites,
        previous_retarget=None,
        capture=ab["captureRootCentered"],
        joints_a=ab["positionsA"],
        joints_b=ab["positionsB"],
        parents=parents,
        mesh_a=mesh_a,
        mesh_b=mesh_b,
        triangles=triangles,
        uvs=uvs,
        albedo=albedo,
        title="move-bind T2 + Eagle mocap A=fixed-length B=exact-joint",
    )
    front = write_mesh_gif(
        preview / "roc_flight_A_front.gif",
        cameras=cameras,
        meshes=mesh_a,
        triangles=triangles,
        uvs=uvs,
        albedo=albedo,
        title="A front",
        view="front",
    )
    return {
        "ok": True,
        "meshGlb": str(mesh_glb).replace("\\", "/"),
        "meshSha256": sha256_file(mesh_glb),
        "capture": str(CAPTURE).replace("\\", "/"),
        "captureSha256": capture["sha256"],
        "align": {
            "policy": aligned["policy"],
            "scale": aligned["scale"],
            "vertexCount": int(len(vertices)),
            "triangleCount": int(len(triangles)),
            "hadAlbedo": albedo is not None,
            "sourceSkinned": bool(surface["skinned"]),
        },
        "bindSheet": str(bind).replace("\\", "/"),
        "overlayGif": str(overlay).replace("\\", "/"),
        "frontGif": str(front).replace("\\", "/"),
        "proof": "generated-artifact — saved Eagle roc_flight capture on move-bind T2 mesh; not OE runtime",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bind-frame", default=DEFAULT_BIND_FRAME, help="Move sprite stem, e.g. 00")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--skip-mocap", action="store_true")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    if ORIGINAL_ROC.is_file():
        original_hash = sha256_file(ORIGINAL_ROC)
    else:
        original_hash = None

    bind_frame = str(args.bind_frame).zfill(2)
    source_frame = MOVE_FRAMES / f"{bind_frame}.png"
    if not source_frame.is_file():
        raise FileNotFoundError(source_frame)

    report: dict[str, Any] = {
        "ok": False,
        "out": str(out).replace("\\", "/"),
        "originalRocSha256": original_hash,
        "bindFrameRationale": (
            "Frame 00 is the roc_flight move cycle start: side-profile glide pose, "
            "not a duplicate silhouette (frames 1=5 and 2=4), and matches the "
            "camera-registration reference used in mocap skin fit."
        ),
        "notes": (
            "Meshy t2 from move bind sprite with pose_mode omitted. "
            "Multi-image meshy-5/6/7 is a separate API and cannot be combined with meshy-t2."
        ),
    }
    source_dir = out / "source"
    prepared = prepare_meshy_bind_image(
        source_frame,
        source_dir / f"h3_roc_move_bind_f{bind_frame}_meshy_ready.png",
    )
    report["bindFrame"] = prepared
    image = Path(prepared["prepared"])

    gen_path = out / "generate_meta.json"
    if args.skip_generate:
        generate = json.loads(gen_path.read_text(encoding="utf-8"))
    else:
        generate = generate_mesh(out, image, bind_frame=bind_frame)
        _write_json(gen_path, generate)
    report["generate"] = generate
    mesh_glb = Path(generate.get("meshGlb") or "")
    if not mesh_glb.is_file():
        report["error"] = generate.get("error") or "mesh GLB missing"
        _write_json(out / "report.json", report)
        print(json.dumps(report, indent=2))
        return 2

    if not args.skip_mocap:
        mocap = replay_mocap(out, mesh_glb)
        report["mocap"] = mocap
        _write_json(out / "mocap_replay.json", mocap)
    if ORIGINAL_ROC.is_file() and original_hash is not None:
        now = sha256_file(ORIGINAL_ROC)
        if now != original_hash:
            raise RuntimeError("original Roc smartrig GLB hash changed; this experiment must not touch it")
        report["originalRocUntouched"] = True
    report["ok"] = True
    _write_json(out / "report.json", report)
    print(
        json.dumps(
            {
                "ok": True,
                "out": report["out"],
                "bindFrame": bind_frame,
                "mesh": generate.get("meshGlb"),
                "overlay": (report.get("mocap") or {}).get("overlayGif"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
