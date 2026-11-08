"""Isolated intermediate capture: vendor skeleton in, predicted positions out.

SmartRig tensors must not enter the network. Learned rotations are saved for
diagnosis and are not an automatic alternative to predicted positions.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import numpy as np

from dino_embed import VENDOR_PREPROCESS, encode_frames
from intermediate_preview import write_capture_gif
from mocap_preflight import refuse_forbidden_inputs, refuse_smartrig_network_input
from motion_metrics import classify_motion, report_proposal_motion
from paths import CHECKPOINT_FILE, REPO, VENDOR, require_file
from pin import BASELINE_SEED, EXPECTED_CHECKPOINT_SHA256, INTERMEDIATE_LOCKED_SETTINGS, sha256_file, vendor_revision
from vendor_fk import gt_rot6d_fk_vs_bvh_positions, storage_rot6d_fk_positions
from vendor_parity import _batch_to_numpy, _forward, _load_demo_cfg, _valid_joints
from vendor_reference import config_name_for_kind, demo_root, load_complete_package, refuse_skeleton_mutation

MOTION_INTERFACE = "pred_position"


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def _array_sha256(values: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(values).tobytes())
    return digest.hexdigest()


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def assert_vendor_only_batch(batch: dict[str, Any], package: dict[str, Any]) -> None:
    species = batch["species"][0] if batch.get("species") else None
    refuse_smartrig_network_input(species=str(species) if species is not None else None)
    if str(species) != str(package["species"]):
        raise ValueError(
            f"batch species {species!r} is not vendor package species {package['species']!r}"
        )
    joint_count = int(_as_numpy(batch["J_valid"]).reshape(-1)[0])
    if joint_count != int(package["jointCount"]):
        raise ValueError(
            f"batch J_valid {joint_count} != vendor joint count {package['jointCount']}"
        )
    t5 = _as_numpy(batch["joint_t5embed"])
    if t5.ndim == 3:
        t5 = t5[0]
    package_t5 = np.asarray(package["t5"], dtype=np.float32)
    if t5.shape[0] < package_t5.shape[0]:
        raise ValueError("batch T5 is shorter than the vendor package")
    if float(np.max(np.abs(t5[: package_t5.shape[0]] - package_t5))) > 1e-5:
        raise ValueError("batch T5 does not match the unmodified vendor package")
    refuse_skeleton_mutation(original_names=list(package["jointNames"]))


def _require_cuda() -> Any:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for intermediate capture; CPU fallback is disabled")
    return torch.device("cuda")


def _attention(seq_len: int) -> dict[str, Any]:
    _vendor_on_path()
    from utils.config_utils import load_yaml_config
    from paths import VENDOR_INFERENCE_YAML

    cfg = load_yaml_config(str(require_file(VENDOR_INFERENCE_YAML, label="vendor yaml")))
    attention = dict(cfg["model"]["attention_kwargs"])
    attention["seq_len"] = int(seq_len)
    return attention


def build_vendor_cfg(package: dict[str, Any], *, frames_dir: Path, save_dir: Path) -> dict[str, Any]:
    kind = str(package["kind"])
    base_dir = Path(package["vendorBaseDir"]) if package.get("vendorBaseDir") else demo_root(kind)
    cfg = _load_demo_cfg(
        config_name_for_kind(kind),
        base_dir=base_dir,
        video_root=frames_dir.parent,
        save_dir=save_dir,
    )
    cfg["data"]["retarget"]["ref_seq"] = package["refSeq"]
    cfg["data"]["image_roots"] = [str(frames_dir.parent)]
    cfg["data"]["wild_flag"] = False
    cfg["data"]["memory_pkl_path"] = None
    cfg["output"]["output_tag"] = "intermediate_capture"
    return cfg


def encode_sprite_vendor(frames: list[Path], *, device: str, encoder_input_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    from PIL import Image

    if not frames:
        raise ValueError("no sprite frames")
    canvas = Image.open(frames[0]).size
    embeds, meta = encode_frames(
        frames,
        device=device,
        canvas=canvas,
        window={"bboxXyxy": [0, 0, canvas[0], canvas[1]]},
        preprocess_policy=VENDOR_PREPROCESS,
        do_center_crop=True,
        dino_dtype="float16",
        encoder_input_dir=encoder_input_dir,
    )
    meta["rmbg"] = False
    meta["note"] = "HoMM3 plates have alpha; vendor would skip RMBG too"
    return embeds, meta


def encode_vendor_video_frames(
    frames_dir: Path,
    *,
    device: Any,
    pipe: Any,
    rmbg_net: Any,
) -> np.ndarray:
    _vendor_on_path()
    from inference.video2pose2rot import extract_and_compare_image_features_with_rmbg

    return extract_and_compare_image_features_with_rmbg(
        image_folder=str(frames_dir),
        rmbg_net=rmbg_net,
        pipe=pipe,
    )


def _crop_joints(values: np.ndarray, joint_count: int) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim == 1:
        return array[:joint_count]
    if array.ndim == 2:
        return array[:joint_count] if array.shape[0] >= joint_count else array[:, :joint_count]
    if array.ndim == 3:
        return array[:, :joint_count] if array.shape[1] >= joint_count else array
    raise ValueError(f"cannot crop joints from shape {array.shape}")


def save_raw_capture(
    dest: Path,
    *,
    package: dict[str, Any],
    pred_position: np.ndarray,
    pred_rot6d: np.ndarray,
    image_embed: np.ndarray,
    ref_image_embed: np.ndarray,
    parents: np.ndarray,
    vendor_offset_a: np.ndarray,
    gt_position: np.ndarray | None = None,
    gt_rot6d: np.ndarray | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pred_position": np.ascontiguousarray(pred_position, dtype=np.float32),
        "pred_rot6d": np.ascontiguousarray(pred_rot6d, dtype=np.float32),
        "image_embed": np.ascontiguousarray(image_embed, dtype=np.float32),
        "ref_image_embed": np.ascontiguousarray(ref_image_embed, dtype=np.float32),
        "parents": np.ascontiguousarray(parents, dtype=np.int64),
        "offsets": np.ascontiguousarray(package["offsets"], dtype=np.float64),
        "vendor_offset_a": np.ascontiguousarray(vendor_offset_a, dtype=np.float32),
        "joint_names": np.asarray(package["jointNames"]),
        "motion_interface": np.asarray(MOTION_INTERFACE),
    }
    if gt_position is not None:
        payload["gt_position"] = np.ascontiguousarray(gt_position, dtype=np.float32)
    if gt_rot6d is not None:
        payload["gt_rot6d"] = np.ascontiguousarray(gt_rot6d, dtype=np.float32)
    np.savez(dest, **payload)
    return dest


def run_capture(
    *,
    package: dict[str, Any],
    frames_dir: Path,
    out_dir: Path,
    image_embed: np.ndarray,
    preprocess_meta: dict[str, Any],
    model: Any,
    source_kind: str,
    title: str,
    compare_gt: bool,
) -> dict[str, Any]:
    refuse_forbidden_inputs()
    refuse_smartrig_network_input()
    if out_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing capture: {out_dir}")
    out_dir.mkdir(parents=True)
    frames = sorted(path for path in frames_dir.glob("*.png") if path.stem.isdigit())
    if not frames:
        raise FileNotFoundError(f"no numbered PNG frames in {frames_dir}")
    pose_len = int(np.asarray(package["posePosition"]).shape[0])
    if image_embed.shape[0] > pose_len:
        raise ValueError(
            f"source has {image_embed.shape[0]} frames but donor pose dummy has {pose_len}; "
            "refusing silent video truncation"
        )
    started = time.perf_counter()
    cfg = build_vendor_cfg(package, frames_dir=frames_dir, save_dir=out_dir / "vendor_out")
    _vendor_on_path()
    from inference.video2pose2rot import build_inference_batch, set_seed

    set_seed(BASELINE_SEED)
    batch = build_inference_batch(cfg=cfg, image_embed_np=np.asarray(image_embed, dtype=np.float32))
    assert_vendor_only_batch(batch, package)
    batch_np = _batch_to_numpy(batch)
    joint_count = _valid_joints(batch_np)
    attention = _attention(int(image_embed.shape[0]))
    set_seed(BASELINE_SEED)
    output = _forward(model, batch, attention)
    pred_position = output["pred_position"][:, :joint_count]
    pred_rot6d = output["pred_rot6d"][:, :joint_count]
    parents = np.asarray(batch_np["parent_a"]).reshape(-1)[:joint_count]
    vendor_offset_a = np.asarray(batch_np["offset_a"])[0, :joint_count]
    gt_position = np.asarray(batch_np["position"])[0, :, :joint_count] if compare_gt else None
    gt_rot6d = np.asarray(batch_np["rot6d_a"])[0, :, :joint_count] if compare_gt else None
    rest = np.asarray(batch_np["ref_position"])[0, :joint_count]
    raw_path = save_raw_capture(
        out_dir / "raw_capture.npz",
        package=package,
        pred_position=pred_position,
        pred_rot6d=pred_rot6d,
        image_embed=np.asarray(image_embed, dtype=np.float32),
        ref_image_embed=np.asarray(batch_np["ref_image_embed"])[0],
        parents=parents,
        vendor_offset_a=vendor_offset_a,
        gt_position=gt_position,
        gt_rot6d=gt_rot6d,
    )
    pred_motion = report_proposal_motion(
        pred_position=pred_position,
        pred_rot6d=pred_rot6d,
        parents=parents,
        bind_model=rest,
        joint_count=joint_count,
    )
    gt_motion = None
    mpjpe = None
    if gt_position is not None:
        gt_motion = classify_motion(positions=gt_position, parents=parents, bind=rest)
        mpjpe = float(np.linalg.norm(pred_position - gt_position, axis=-1).mean())
    diagnosis_fk = storage_rot6d_fk_positions(
        pred_rot6d,
        np.asarray(package["offsets"], dtype=np.float64)[:joint_count],
        parents,
    )
    diagnosis_fk_err = np.linalg.norm(diagnosis_fk - (pred_position - pred_position[:, 0:1, :]), axis=-1)
    gif = write_capture_gif(
        frames_dir=frames_dir,
        pred=pred_position,
        parents=parents,
        dest=out_dir / "source_intermediate.gif",
        title=title,
        gt=gt_position,
    )
    provenance = {
        "proof": "generated-artifact",
        "phase": "intermediate_vendor_skeleton",
        "status": "unproven",
        "motionInterface": MOTION_INTERFACE,
        "learnedRotations": "diagnosis_only_not_fallback",
        "smartRigNetworkInput": False,
        "vendorSkeletonsUnmodified": True,
        "rootTranslationAvailable": False,
        "settings": dict(INTERMEDIATE_LOCKED_SETTINGS),
        "package": {
            "kind": package["kind"],
            "refSeq": package["refSeq"],
            "species": package["species"],
            "jointCount": joint_count,
            "jointNames": list(package["jointNames"]),
            "fileSha256": package["fileSha256"],
            "candidateRole": package.get("candidateRole"),
            "unit": package.get("unit"),
        },
        "checkpointSha256": sha256_file(CHECKPOINT_FILE),
        "vendorRevision": vendor_revision(),
        "seed": BASELINE_SEED,
        "sourceKind": source_kind,
        "sourceFrames": [path.name for path in frames],
        "sourceFrameCount": len(frames),
        "preprocess": preprocess_meta,
        "imageEmbedSha256": _array_sha256(np.asarray(image_embed)),
        "refImageEmbedSha256": _array_sha256(np.asarray(batch_np["ref_image_embed"])[0]),
        "rawCapture": str(raw_path).replace("\\", "/"),
        "gif": str(gif).replace("\\", "/"),
    }
    if provenance["checkpointSha256"] != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("checkpoint hash does not match the pin")
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "keepAuthority": "mocap_v2_intermediate_vendor_skeleton",
        "title": title,
        "sourceKind": source_kind,
        "refSeq": package["refSeq"],
        "jointCount": joint_count,
        "frameCount": int(pred_position.shape[0]),
        "predMotion": pred_motion,
        "gtMotion": gt_motion,
        "mpjpeVsDonorPoseNpz": mpjpe,
        "learnedRotationFkVsPredPositionMean": float(diagnosis_fk_err.mean()),
        "learnedRotationFkVsPredPositionMax": float(diagnosis_fk_err.max()),
        "learnedRotationsAreNotTheMotionInterface": True,
        "gif": provenance["gif"],
        "rawCapture": provenance["rawCapture"],
        "captureSec": time.perf_counter() - started,
        "provenance": provenance,
        "proceedToRetarget": False,
        "visualAcceptance": "unreviewed_candidate",
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    (out_dir / "capture_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def copy_or_decode_vendor_video(*, video: Path, frames_dir: Path, existing: Path | None) -> int:
    if frames_dir.exists() and any(frames_dir.glob("*.png")):
        return len(list(frames_dir.glob("*.png")))
    if existing is not None and existing.is_dir() and any(existing.glob("*.png")):
        frames_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(existing.glob("*.png")):
            shutil.copy2(path, frames_dir / path.name)
        return len(list(frames_dir.glob("*.png")))
    _vendor_on_path()
    from inference.video2pose2rot import video_to_frames

    frames_dir.mkdir(parents=True, exist_ok=True)
    count = video_to_frames(str(video), str(frames_dir))
    if count < 2:
        raise RuntimeError(f"{video} decoded {count} frames")
    return int(count)


def known_motion_control_spec() -> dict[str, Any]:
    return {
        "unit": "h3_roc",
        "role": "primary",
        "seqName": "Eagle#Eagle-Landing_y15",
        "video": VENDOR / "demo" / "data" / "inputs" / "nbg_zoo" / "Eagle#Eagle-Landing_y15.mp4",
        "existingFrames": REPO
        / "artifacts"
        / "homm3_mocap_v2"
        / "mocap_diagnosis"
        / "vendor_parity"
        / "zoo"
        / "Eagle#Eagle-Landing_y15"
        / "frames",
    }
