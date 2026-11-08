"""Vendor demo download, original-path inference, and wrapper tensor parity."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from motion_metrics import classify_motion, report_proposal_motion
from paths import CHECKPOINT_FILE, MOCAP_DIAGNOSIS, REPO, VENDOR, VENDOR_DEMO, require_file
from pin import BASELINE_SEED, EXPECTED_CHECKPOINT_SHA256, EXPECTED_VENDOR_REVISION, sha256_file, vendor_revision

SAMPLE_REPO = "kehong/MoCapAnythingV2-data-sample"
PARITY_ROOT = MOCAP_DIAGNOSIS / "vendor_parity"


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def ensure_demo_data() -> dict[str, Any]:
    started = time.perf_counter()
    VENDOR_DEMO.mkdir(parents=True, exist_ok=True)
    videos = list(VENDOR_DEMO.rglob("*.mp4"))
    if videos:
        return {
            "downloaded": False,
            "path": str(VENDOR_DEMO).replace("\\", "/"),
            "videoCount": len(videos),
            "downloadSec": 0.0,
        }
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=SAMPLE_REPO,
        repo_type="dataset",
        local_dir=str(VENDOR_DEMO),
    )
    videos = list(VENDOR_DEMO.rglob("*.mp4"))
    if not videos:
        raise FileNotFoundError(f"{SAMPLE_REPO} downloaded but no videos were found in {VENDOR_DEMO}")
    return {
        "downloaded": True,
        "path": str(VENDOR_DEMO).replace("\\", "/"),
        "videoCount": len(videos),
        "downloadSec": time.perf_counter() - started,
    }


def catalog_demo() -> dict[str, Any]:
    zoo_videos = _list_videos(VENDOR_DEMO / "inputs" / "nbg_zoo")
    obj_videos = _list_videos(VENDOR_DEMO / "inputs" / "nbg_obj")
    if not zoo_videos or not obj_videos:
        for path in sorted(VENDOR_DEMO.rglob("*.mp4")):
            row = {"seqName": path.stem, "path": str(path).replace("\\", "/")}
            text = str(path).replace("\\", "/").lower()
            if "obj" in text and row not in obj_videos:
                obj_videos.append(row)
            elif row not in zoo_videos:
                zoo_videos.append(row)
    expected = VENDOR_DEMO / "expected_results"
    return {
        "zooVideos": zoo_videos,
        "objVideos": obj_videos,
        "expectedResultsPresent": expected.is_dir(),
        "zoo1030Present": (VENDOR_DEMO / "zoo1030").is_dir(),
        "obj1kPresent": (VENDOR_DEMO / "obj1k").is_dir(),
    }


def _list_videos(root: Path) -> list[dict[str, str]]:
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}:
            rows.append({"seqName": path.stem, "path": str(path).replace("\\", "/")})
    return rows


def select_controls(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    _vendor_on_path()
    from inference.video2pose2rot import derive_ref_seq

    chosen: list[dict[str, Any]] = []
    zoo_dir = VENDOR_DEMO / "zoo1030"
    obj_dir = VENDOR_DEMO / "obj1k"
    prefer_zoo = (
        "Eagle-Landing",
        "Jaguar-Run",
        "Hamster-RollAttack",
        "HorseALL-FeetUp",
    )
    zoo_rows = sorted(
        catalog["zooVideos"],
        key=lambda row: next(
            (index for index, token in enumerate(prefer_zoo) if token in row["seqName"]),
            len(prefer_zoo),
        ),
    )
    for row in zoo_rows:
        ref = derive_ref_seq(row["seqName"], str(zoo_dir))
        if ref is None:
            continue
        pose = zoo_dir / "bvh_pose" / f"{ref}.npz"
        train = zoo_dir / "npz_train_image_only" / f"{ref}.npz"
        if not pose.is_file() or not train.is_file():
            continue
        chosen.append(
            {
                "role": "articulated_animal",
                "kind": "zoo",
                "seqName": row["seqName"],
                "video": row["path"],
                "baseDir": str(zoo_dir).replace("\\", "/"),
                "refSeq": ref,
                "configName": "demo_zoo.yaml",
            }
        )
        break
    for row in catalog["objVideos"]:
        ref = derive_ref_seq(row["seqName"], str(obj_dir))
        if ref is None:
            continue
        pose = obj_dir / "bvh_pose" / f"{ref}.npz"
        train = obj_dir / "npz_train_image_only" / f"{ref}.npz"
        if not pose.is_file() or not train.is_file():
            continue
        chosen.append(
            {
                "role": "different_topology",
                "kind": "obj",
                "seqName": row["seqName"],
                "video": row["path"],
                "baseDir": str(obj_dir).replace("\\", "/"),
                "refSeq": ref,
                "configName": "demo_obj.yaml",
            }
        )
        break
    if len(chosen) < 2:
        raise RuntimeError(
            f"could not select one zoo GT control and one obj GT control; catalog={catalog}"
        )
    return chosen


def _load_demo_cfg(config_name: str, *, base_dir: Path, video_root: Path, save_dir: Path) -> dict[str, Any]:
    _vendor_on_path()
    from utils.config_utils import load_yaml_config

    yaml_path = VENDOR / "demo" / "configs" / config_name
    cfg = load_yaml_config(str(require_file(yaml_path, label="demo yaml")))
    cfg["runtime"]["seed"] = BASELINE_SEED
    cfg["runtime"]["device"] = "cuda"
    cfg["weights"]["video2pose_ckpt_root"] = str(CHECKPOINT_FILE.parent)
    cfg["weights"]["ckpt_name"] = CHECKPOINT_FILE.name
    cfg["experiment"]["exp"] = ""
    cfg["data"]["base_dir"] = str(base_dir)
    cfg["data"]["memory_pkl_path"] = None
    cfg["data"]["scale_dict_path"] = str(base_dir / "cache" / "__mesh2pose1002_species_scale_cache.pkl")
    if (base_dir / "characters_fix_facezplus").is_dir():
        cfg["data"]["character_dir"] = str(base_dir / "characters_fix_facezplus")
    else:
        cfg["data"]["character_dir"] = str(base_dir / "characters")
    cfg["data"]["bvh_roots"] = [str(base_dir / "bvh")]
    cfg["data"]["video_roots"] = [str(video_root)]
    cfg["data"]["wild_flag"] = False
    cfg["data"]["retarget"]["toggle"] = False
    cfg["output"]["blender_path"] = None
    cfg["output"]["save_dir"] = str(save_dir)
    cfg["output"]["output_tag"] = "vendor_parity"
    return cfg


def _batch_to_numpy(batch: dict[str, Any]) -> dict[str, Any]:
    import torch

    out: dict[str, Any] = {}
    for key, value in batch.items():
        if isinstance(value, torch.Tensor):
            out[key] = value.detach().cpu().numpy()
        else:
            out[key] = value
    return out


def _numpy_to_batch(payload: dict[str, Any], device) -> dict[str, Any]:
    import torch

    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "species":
            out[key] = value
            continue
        array = np.asarray(value)
        if array.dtype == np.bool_ or array.dtype == bool:
            out[key] = torch.from_numpy(array).to(device)
        elif array.dtype.kind in "iu":
            out[key] = torch.from_numpy(array).to(device)
        elif array.dtype.kind == "f":
            out[key] = torch.from_numpy(array.astype(np.float32)).float().to(device)
        else:
            out[key] = value
    return out


def _forward(model, batch, attention) -> dict[str, np.ndarray]:
    import torch

    with torch.no_grad():
        output = model(batch, attention_kwargs=attention, pose_source_mode="pred")
    return {
        "pred_position": output["pred_position"].squeeze(0).detach().cpu().numpy(),
        "pred_rot6d": output["pred_rot6d"].squeeze(0).detach().cpu().numpy(),
        "pose_for_rot": output["pose_for_rot"].squeeze(0).detach().cpu().numpy(),
    }


def _forward_gt(model, batch, attention, *, pose_source_mode: str) -> dict[str, np.ndarray]:
    import torch

    with torch.no_grad():
        output = model(batch, attention_kwargs=attention, pose_source_mode=pose_source_mode)
    return {
        "pred_position": output["pred_position"].squeeze(0).detach().cpu().numpy(),
        "pred_rot6d": output["pred_rot6d"].squeeze(0).detach().cpu().numpy(),
        "pose_for_rot": output["pose_for_rot"].squeeze(0).detach().cpu().numpy(),
    }


def _max_abs(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


def _valid_joints(batch_np: dict[str, Any]) -> int:
    return int(np.asarray(batch_np["J_valid"]).reshape(-1)[0])


def write_compare_gif(
    *,
    frames_dir: Path,
    pred: np.ndarray,
    gt: np.ndarray,
    parents: np.ndarray,
    dest: Path,
    title: str,
    oracle_fk: np.ndarray | None = None,
) -> Path:
    from PIL import Image, ImageDraw

    dest.parent.mkdir(parents=True, exist_ok=True)
    joint_count = int(parents.shape[0])
    pred = np.asarray(pred, dtype=np.float64)[:, :joint_count]
    gt = np.asarray(gt, dtype=np.float64)[:, :joint_count]
    pngs = sorted(path for path in frames_dir.glob("*.png"))
    count = min(len(pngs), pred.shape[0], gt.shape[0])
    if count < 1:
        raise ValueError("no frames to compare")
    oracle = None
    if oracle_fk is not None:
        oracle = np.asarray(oracle_fk, dtype=np.float64)[:, :joint_count]
        count = min(count, oracle.shape[0])
    images = []
    for index in range(count):
        src = Image.open(pngs[index]).convert("RGB").resize((200, 200))
        pred_xz = _draw_skeleton_panel(pred[index], parents, size=200, color=(40, 180, 90), plane="xz")
        gt_xz = _draw_skeleton_panel(gt[index], parents, size=200, color=(40, 90, 200), plane="xz")
        pred_xy = _draw_skeleton_panel(pred[index], parents, size=200, color=(40, 180, 90), plane="xy")
        gt_xy = _draw_skeleton_panel(gt[index], parents, size=200, color=(40, 90, 200), plane="xy")
        width = 1000 if oracle is None else 1200
        row = Image.new("RGB", (width, 432), (16, 16, 20))
        row.paste(src, (0, 16))
        row.paste(pred_xz, (200, 16))
        row.paste(gt_xz, (400, 16))
        row.paste(pred_xy, (600, 16))
        row.paste(gt_xy, (800, 16))
        if oracle is not None:
            row.paste(
                _draw_skeleton_panel(oracle[index], parents, size=200, color=(200, 140, 40), plane="xy"),
                (1000, 16),
            )
        row.paste(src, (0, 232))
        draw = ImageDraw.Draw(row)
        draw.text(
            (4, 2),
            f"{title} f{index:02d} source|predXZ|gtXZ|predXY|gtXY"
            + ("|oracleFKxy" if oracle is not None else ""),
            fill=(230, 230, 235),
        )
        draw.text((4, 218), "XZ hides height; XY shows wing/limb elevation", fill=(180, 180, 190))
        images.append(row)
    images[0].save(dest, save_all=True, append_images=images[1:], duration=80, loop=0)
    return dest


def _draw_skeleton_panel(
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    size: int,
    color: tuple[int, int, int],
    plane: str = "xz",
):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (size, size), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    if plane == "xy":
        coords = joints[:, [0, 1]]
    elif plane == "xz":
        coords = joints[:, [0, 2]]
    else:
        raise ValueError(f"unknown skeleton plane {plane!r}")
    span = np.maximum(coords.max(axis=0) - coords.min(axis=0), 1e-6)
    scale = 0.8 * size / float(span.max())
    center = coords.mean(axis=0)
    xy = (coords - center) * scale + size / 2.0
    xy[:, 1] = size - xy[:, 1]
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        x0, y0 = xy[int(parent)]
        x1, y1 = xy[index]
        draw.line((x0, y0, x1, y1), fill=color, width=2)
    for x, y in xy:
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    draw.text((4, 4), plane.upper(), fill=(40, 40, 50))
    return image


def _reference_from_vendor_batch(batch_np: dict[str, Any]) -> dict[str, np.ndarray]:
    def squeeze0(key: str) -> np.ndarray:
        array = np.asarray(batch_np[key])
        if array.ndim >= 1 and array.shape[0] == 1:
            return array[0]
        return array

    return {
        "ref_position": squeeze0("ref_position"),
        "ref_rot6d": squeeze0("ref_rot6d_a"),
        "offset": squeeze0("offset_a"),
        "parents": squeeze0("parent_a"),
        "joint_mask": squeeze0("joint_mask"),
        "ancestor_mask": squeeze0("ancestor_mask"),
        "graph_hop": squeeze0("graph_hop"),
        "graph_edge": squeeze0("graph_edge"),
        "joint_t5embed": squeeze0("joint_t5embed"),
        "static_pos_joint_mask": squeeze0("static_pos_joint_mask"),
        "static_rot_joint_mask": squeeze0("static_rot_joint_mask"),
        "memory_pose": squeeze0("memory_pose"),
        "memory_rot6d": squeeze0("memory_rot6d"),
        "global_scale": np.asarray(batch_np["global_scale"]).reshape(-1).astype(np.float32),
        "J_valid": np.asarray(batch_np["J_valid"]).reshape(-1).astype(np.int32),
    }


def _amplitude_phase(pred: np.ndarray, gt: np.ndarray) -> dict[str, Any]:
    pred_rel = np.asarray(pred, dtype=np.float64) - np.asarray(pred, dtype=np.float64)[:, 0:1]
    gt_rel = np.asarray(gt, dtype=np.float64) - np.asarray(gt, dtype=np.float64)[:, 0:1]
    pred_range = float(np.linalg.norm(pred_rel.max(axis=0) - pred_rel.min(axis=0), axis=-1).max())
    gt_range = float(np.linalg.norm(gt_rel.max(axis=0) - gt_rel.min(axis=0), axis=-1).max())
    joint = int(np.argmax(np.linalg.norm(gt_rel.max(axis=0) - gt_rel.min(axis=0), axis=-1)))
    axis = int(np.argmax(np.ptp(gt_rel[:, joint], axis=0)))
    return {
        "predMaxJointRange": pred_range,
        "gtMaxJointRange": gt_range,
        "amplitudeRatioVsGt": pred_range / max(gt_range, 1e-8),
        "peakJoint": joint,
        "peakAxis": axis,
        "peakFrameGt": int(np.argmax(gt_rel[:, joint, axis])),
        "peakFramePred": int(np.argmax(pred_rel[:, joint, axis])),
    }


def _slice_batch(batch, frames: int) -> dict[str, Any]:
    sliced = {}
    for key, value in batch.items():
        if key in {"image_embed", "position", "rot6d_a"} and hasattr(value, "shape") and value.ndim >= 3:
            sliced[key] = value[:, :frames]
        else:
            sliced[key] = value
    return sliced


def compare_preprocessing(
    *,
    frames_dir: Path,
    vendor_embeds: np.ndarray,
    out_dir: Path,
    rmbg_net,
    device,
) -> dict[str, Any]:
    """Vendor prepare_image vs clip-union crop. Does not move the output camera."""
    from PIL import Image

    from dino_embed import (
        CLIP_UNION_PREPROCESS,
        clip_locked_subject_window,
        encode_frames,
        write_subject_preview,
    )
    from preprocess.image_process import prepare_image

    pngs = sorted(path for path in frames_dir.glob("*.png"))
    if not pngs:
        raise FileNotFoundError(f"no frames in {frames_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    picks = sorted({0, len(pngs) // 2, len(pngs) - 1})
    for index in picks:
        prepared = prepare_image(
            str(pngs[index]),
            bg_color=np.array([1.0, 1.0, 1.0]),
            rmbg_net=rmbg_net,
        )
        prepared.save(out_dir / f"vendor_prepare_f{index:02d}.png")
    canvas = Image.open(pngs[0]).size
    window = clip_locked_subject_window(pngs, canvas=canvas)
    for index in picks:
        write_subject_preview(
            pngs[index],
            window,
            canvas=canvas,
            dest=out_dir / f"{CLIP_UNION_PREPROCESS}_f{index:02d}.png",
        )
    union_embeds, union_meta = encode_frames(
        pngs,
        device=str(device),
        canvas=canvas,
        window=window,
        preprocess_policy=CLIP_UNION_PREPROCESS,
        do_center_crop=False,
        dino_dtype="float32",
        encoder_input_dir=out_dir / "clip_union_pixels",
    )
    if union_embeds.shape != vendor_embeds.shape:
        delta = None
        note = f"shape mismatch vendor {vendor_embeds.shape} vs clip-union {union_embeds.shape}"
    else:
        delta = float(np.max(np.abs(union_embeds - vendor_embeds)))
        note = "same tensor rank; differences are preprocessing, not camera registration"
    return {
        "vendorPreparePolicy": "prepare_image_with_rmbg_then_dino_processor_defaults_fp16",
        "clipUnionPolicy": CLIP_UNION_PREPROCESS,
        "clipUnionHasUsableAlpha": bool(window["bboxXyxy"] != [0, 0, canvas[0], canvas[1]]),
        "clipUnionWindow": window,
        "clipUnionMeta": union_meta,
        "embedMaxAbsVsVendor": delta,
        "note": note,
        "encoderInputDir": str(out_dir).replace("\\", "/"),
        "outputCameraUnchanged": True,
    }


def run_control(
    *,
    control: dict[str, Any],
    model,
    attention_template: dict[str, Any],
    pipe,
    rmbg_net,
    device,
) -> dict[str, Any]:
    _vendor_on_path()
    from inference.video2pose2rot import (
        build_inference_batch,
        extract_and_compare_image_features_with_rmbg,
        set_seed,
        video_to_frames,
    )

    out_dir = PARITY_ROOT / control["kind"] / control["seqName"]
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    if frames_dir.exists() and not any(frames_dir.glob("*.png")):
        frames_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    n_frames = video_to_frames(control["video"], str(frames_dir))
    if n_frames < 2:
        raise RuntimeError(f"{control['seqName']} decoded {n_frames} frames")
    cfg = _load_demo_cfg(
        control["configName"],
        base_dir=Path(control["baseDir"]),
        video_root=Path(control["video"]).parent,
        save_dir=out_dir / "vendor_out",
    )
    cfg["data"]["retarget"]["ref_seq"] = control["refSeq"]
    cfg["data"]["image_roots"] = [str(frames_dir.parent)]
    set_seed(BASELINE_SEED)
    embeds = extract_and_compare_image_features_with_rmbg(
        image_folder=str(frames_dir),
        rmbg_net=rmbg_net,
        pipe=pipe,
    )
    np.save(out_dir / "vendor_image_embed.npy", embeds)
    batch = build_inference_batch(cfg=cfg, image_embed_np=embeds)
    attention = dict(attention_template)
    attention["seq_len"] = int(embeds.shape[0])
    set_seed(BASELINE_SEED)
    vendor_a = _forward(model, batch, attention)
    set_seed(BASELINE_SEED)
    vendor_b = _forward(model, batch, attention)
    batch_np = _batch_to_numpy(batch)
    rebuilt = _numpy_to_batch(batch_np, device)
    set_seed(BASELINE_SEED)
    wrapper = _forward(model, rebuilt, attention)
    from model_runner import build_batch

    custom_batch = build_batch(
        reference=_reference_from_vendor_batch(batch_np),
        image_embed=np.asarray(batch_np["image_embed"])[0],
        ref_image_embed=np.asarray(batch_np["ref_image_embed"])[0],
        device=device,
    )
    set_seed(BASELINE_SEED)
    custom_wrapper = _forward(model, custom_batch, attention)
    oracle = _forward_gt(model, batch, attention, pose_source_mode="gt")
    short_frames = min(8, int(embeds.shape[0]))
    short_attention = dict(attention)
    short_attention["seq_len"] = short_frames
    set_seed(BASELINE_SEED)
    short_pred = _forward(model, _slice_batch(batch, short_frames), short_attention)
    joint_count = _valid_joints(batch_np)
    parents = np.asarray(batch_np["parent_a"]).reshape(-1)[:joint_count]
    gt_pos = np.asarray(batch_np["position"])[0, :, :joint_count]
    pred_pos = vendor_a["pred_position"][:, :joint_count]
    pred_rot = vendor_a["pred_rot6d"][:, :joint_count]
    rest = np.asarray(batch_np["ref_position"])[0, :joint_count]
    gt_motion = classify_motion(positions=gt_pos, parents=parents, bind=rest)
    pred_motion = report_proposal_motion(
        pred_position=pred_pos,
        pred_rot6d=pred_rot,
        parents=parents,
        bind_model=rest,
        joint_count=joint_count,
    )
    oracle_rot = report_proposal_motion(
        pred_position=gt_pos,
        pred_rot6d=oracle["pred_rot6d"][:, :joint_count],
        parents=parents,
        bind_model=rest,
        joint_count=joint_count,
    )
    noise = {
        "predPositionMaxAbs": _max_abs(vendor_a["pred_position"], vendor_b["pred_position"]),
        "predRot6dMaxAbs": _max_abs(vendor_a["pred_rot6d"], vendor_b["pred_rot6d"]),
        "imageEmbedSelf": 0.0,
    }
    wrapper_delta = {
        "predPositionMaxAbs": _max_abs(vendor_a["pred_position"], wrapper["pred_position"]),
        "predRot6dMaxAbs": _max_abs(vendor_a["pred_rot6d"], wrapper["pred_rot6d"]),
        "poseForRotMaxAbs": _max_abs(vendor_a["pose_for_rot"], wrapper["pose_for_rot"]),
    }
    custom_delta = {
        "predPositionMaxAbs": _max_abs(vendor_a["pred_position"], custom_wrapper["pred_position"]),
        "predRot6dMaxAbs": _max_abs(vendor_a["pred_rot6d"], custom_wrapper["pred_rot6d"]),
        "poseForRotMaxAbs": _max_abs(vendor_a["pose_for_rot"], custom_wrapper["pose_for_rot"]),
        "note": "build_batch repeats rest positions; pose_source_mode=pred must ignore that dummy",
    }
    tolerance = max(1e-5, 2.0 * noise["predPositionMaxAbs"] + 1e-6)
    rot_tolerance = max(1e-5, 2.0 * noise["predRot6dMaxAbs"] + 1e-6)
    parity_ok = (
        wrapper_delta["predPositionMaxAbs"] <= tolerance
        and wrapper_delta["predRot6dMaxAbs"] <= rot_tolerance
        and custom_delta["predPositionMaxAbs"] <= tolerance
        and custom_delta["predRot6dMaxAbs"] <= rot_tolerance
    )
    pos_err = np.linalg.norm(pred_pos - gt_pos, axis=-1)
    from preview import proposal_fk_world

    offsets = np.asarray(batch_np["offset_a"])[0, :joint_count]
    oracle_fk = proposal_fk_world(
        pred_rot6d=oracle["pred_rot6d"][:, :joint_count],
        offsets=offsets,
        parents=parents,
        global_scale=1.0,
        rest_root=np.zeros(3),
    )
    pred_fk = proposal_fk_world(
        pred_rot6d=pred_rot,
        offsets=offsets,
        parents=parents,
        global_scale=1.0,
        rest_root=np.zeros(3),
    )
    oracle_fk_err = np.linalg.norm(oracle_fk - gt_pos, axis=-1)
    pred_fk_err = np.linalg.norm(pred_fk - pred_pos, axis=-1)
    gif = write_compare_gif(
        frames_dir=frames_dir,
        pred=pred_pos,
        gt=gt_pos,
        parents=parents,
        dest=out_dir / "source_pred_gt.gif",
        title=control["seqName"],
        oracle_fk=oracle_fk,
    )
    recognizable = bool(gt_motion["countsAsLimbAction"] or gt_motion["countsAsMotion"]) and bool(
        pred_motion["countsAsMotion"]
    )
    amplitude = _amplitude_phase(pred_pos, gt_pos)
    short_gt = gt_pos[:short_frames]
    short_pred_pos = short_pred["pred_position"][:, :joint_count]
    short_amp = _amplitude_phase(short_pred_pos, short_gt)
    short_attenuated = bool(short_amp["amplitudeRatioVsGt"] < 0.5)
    preprocess = compare_preprocessing(
        frames_dir=frames_dir,
        vendor_embeds=embeds,
        out_dir=out_dir / "encoder_inputs",
        rmbg_net=rmbg_net,
        device=device,
    )
    np.savez(
        out_dir / "tensors.npz",
        image_embed=embeds.astype(np.float32),
        pred_position=pred_pos.astype(np.float32),
        pred_rot6d=pred_rot.astype(np.float32),
        gt_position=gt_pos.astype(np.float32),
        gt_rot6d=np.asarray(batch_np["rot6d_a"])[0, :, :joint_count].astype(np.float32),
        oracle_pred_rot6d=oracle["pred_rot6d"][:, :joint_count].astype(np.float32),
        oracle_fk=oracle_fk.astype(np.float32),
        pred_fk=pred_fk.astype(np.float32),
        pose_for_rot_pred=vendor_a["pose_for_rot"][:, :joint_count].astype(np.float32),
        pose_for_rot_gt=oracle["pose_for_rot"][:, :joint_count].astype(np.float32),
        parents=parents.astype(np.int64),
        ref_position=rest.astype(np.float32),
        custom_wrapper_pred_position=custom_wrapper["pred_position"][:, :joint_count].astype(np.float32),
    )
    report = {
        "ok": parity_ok and recognizable,
        "proof": "generated-artifact",
        "control": control,
        "frameCount": int(n_frames),
        "jointCount": joint_count,
        "vendorRepeatability": noise,
        "wrapperVsVendor": wrapper_delta,
        "customBuildBatchVsVendor": custom_delta,
        "wrapperWithinRepeatability": parity_ok,
        "imageToPosition": {
            "mpjpe": float(pos_err.mean()),
            "mpjpeMax": float(pos_err.max()),
            "amplitudePhase": amplitude,
            "gtMotion": gt_motion,
            "predMotion": pred_motion,
        },
        "positionToRotationOracle": {
            "poseSourceMode": "gt",
            "oracleMotion": oracle_rot,
            "fkMean": float(oracle_fk_err.mean()),
            "fkMax": float(oracle_fk_err.max()),
            "twistRecoverableFromJointPositions": False,
        },
        "predictedPositionRotation": {
            "fkMean": float(pred_fk_err.mean()),
            "fkMax": float(pred_fk_err.max()),
        },
        "shortWindow": {
            "frames": short_frames,
            "amplitudePhase": short_amp,
            "attenuatedVsGt": short_attenuated,
        },
        "preprocessingComparison": preprocess,
        "recognizableExpectedMotion": recognizable,
        "gif": str(gif).replace("\\", "/"),
        "controlSuiteSec": time.perf_counter() - started,
    }
    if not recognizable:
        report["failureClass"] = "control_or_setup"
        report["ok"] = False
        report["stopSpriteTuning"] = True
    elif not parity_ok:
        report["failureClass"] = "preprocessing_or_wrapper"
        report["ok"] = False
        report["stopSpriteTuning"] = True
    (out_dir / "control_report.json").write_text(json.dumps(report, indent=2, default=_json_default) + "\n")
    return report


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def run_vendor_parity() -> dict[str, Any]:
    wall = time.perf_counter()
    if sha256_file(CHECKPOINT_FILE) != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("checkpoint hash does not match the pin")
    if vendor_revision() != EXPECTED_VENDOR_REVISION:
        raise ValueError("vendor revision does not match the pin")
    download = ensure_demo_data()
    catalog = catalog_demo()
    controls = select_controls(catalog)
    _vendor_on_path()
    import torch
    from inference.video2pose2rot import DinoPipe, set_seed
    from preprocess.briarmbg import BriaRMBG
    from utils.config_utils import instantiate_from_config, load_yaml_config
    from run_mocap_baseline import _gpu_lock_waiting

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for vendor parity; CPU fallback is disabled")
    device = torch.device("cuda")
    with _gpu_lock_waiting(REPO) as (_lock_path, lock_wait):
        set_seed(BASELINE_SEED)
        yaml_path = VENDOR / "demo" / "configs" / "demo_zoo.yaml"
        cfg = load_yaml_config(str(yaml_path))
        rmbg_net = BriaRMBG.from_pretrained("briaai/RMBG-1.4").to(device).eval()
        pipe = DinoPipe(device)
        model = instantiate_from_config(cfg["model"]).float().to(device).eval()
        ckpt = torch.load(str(CHECKPOINT_FILE), map_location=device)
        state = None
        if isinstance(ckpt, dict):
            for key in ("model_state", "model", "model_state_dict", "state_dict"):
                if key in ckpt:
                    state = ckpt[key]
                    break
        if state is None:
            state = ckpt
        state = {key[7:] if key.startswith("module.") else key: value for key, value in state.items()}
        model.load_state_dict(state)
        attention = dict(cfg["model"]["attention_kwargs"])
        reports = []
        for control in controls:
            reports.append(
                run_control(
                    control=control,
                    model=model,
                    attention_template=attention,
                    pipe=pipe,
                    rmbg_net=rmbg_net,
                    device=device,
                )
            )
    ok = all(row.get("ok") for row in reports)
    experiment_b = any((row.get("shortWindow") or {}).get("attenuatedVsGt") for row in reports)
    summary = {
        "ok": ok,
        "proof": "generated-artifact",
        "pin": {
            "vendorRevision": EXPECTED_VENDOR_REVISION,
            "checkpointSha256": EXPECTED_CHECKPOINT_SHA256,
            "seed": BASELINE_SEED,
        },
        "download": download,
        "catalog": catalog,
        "controls": reports,
        "stopSpriteTuning": any(row.get("stopSpriteTuning") for row in reports),
        "experimentBIndicated": bool(experiment_b),
        "experimentBReason": (
            "short-window vendor controls attenuated versus ground truth"
            if experiment_b
            else "vendor 8-frame windows kept amplitude versus GT; skip temporal-context expansion"
        ),
        "failureClass": None if ok else next(
            (row.get("failureClass") for row in reports if not row.get("ok")), "control_or_setup"
        ),
        "controlSuiteSec": time.perf_counter() - wall,
        "downloadSec": download.get("downloadSec"),
        "oneTimePreparationSec": download.get("downloadSec"),
    }
    PARITY_ROOT.mkdir(parents=True, exist_ok=True)
    (PARITY_ROOT / "parity_report.json").write_text(
        json.dumps(summary, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    report = run_vendor_parity()
    print(json.dumps(report, indent=2, default=_json_default), flush=True)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
