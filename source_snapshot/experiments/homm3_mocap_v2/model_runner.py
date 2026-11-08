"""Run MoCapAnything V2 on authentic sprite frames. Proposal only; not delivery."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from dino_embed import (
    CLIP_UNION_PREPROCESS,
    VENDOR_PREPROCESS,
    clip_locked_subject_window,
    encode_frames,
    write_subject_preview,
)
from motion_metrics import report_proposal_motion
from paths import (
    CHECKPOINT_FILE,
    KEEP_AUTHORITY,
    MAX_JOINTS,
    MAX_SEQ_LEN,
    SOURCE_FRAME_MS,
    VENDOR,
    VENDOR_INFERENCE_YAML,
    require_dir,
    require_file,
)
from rig_adapter import load_reference
from temporal_context import expand_frame_indices, map_predictions_to_native

FORBIDDEN_KEEP = frozenset({"silhouette", "dinov3", "dinov3_dense", "chroma", "geometry", "iou", "preview"})


def assert_keep_authority(keep_authority: str) -> None:
    token = str(keep_authority)
    if token in FORBIDDEN_KEEP:
        raise ValueError(f"keep authority {token!r} is a mesh-preview score")
    if token != KEEP_AUTHORITY:
        raise ValueError(f"keep authority must be {KEEP_AUTHORITY!r}; got {token!r}")


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def _numbered_pngs(frame_dir: Path) -> list[Path]:
    paths = sorted(
        path for path in frame_dir.glob("*.png") if path.stem.isdigit()
    )
    if not paths:
        raise FileNotFoundError(f"no numbered PNG frames in {frame_dir}")
    return paths


def _canvas_size(paths: list[Path]) -> tuple[int, int]:
    from PIL import Image

    sizes = {Image.open(path).size for path in paths}
    if len(sizes) != 1:
        raise ValueError(f"frame canvas sizes are not identical: {sizes}")
    width, height = next(iter(sizes))
    return int(width), int(height)


def video_with_rest_bookends(rest_image: Path, clip_frames: list[Path]) -> list[Path]:
    """Give the temporal model the rest image on both sides of the clip, then slice it off."""
    if not clip_frames:
        raise ValueError("clip has no frames")
    return [rest_image, *clip_frames, rest_image]


def load_model(device: torch.device):
    _vendor_on_path()
    from utils.config_utils import instantiate_from_config, load_yaml_config

    cfg = load_yaml_config(str(require_file(VENDOR_INFERENCE_YAML, label="vendor yaml")))
    model = instantiate_from_config(cfg["model"]).float().to(device).eval()
    ckpt = torch.load(require_file(CHECKPOINT_FILE, label="checkpoint"), map_location=device)
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
    return model, attention, cfg


def build_batch(
    *,
    reference: dict[str, np.ndarray],
    image_embed: np.ndarray,
    ref_image_embed: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    frames = image_embed.shape[0]
    if frames > MAX_SEQ_LEN:
        raise ValueError(f"clip has {frames} frames; vendor cap is {MAX_SEQ_LEN} and this lane does not truncate")
    joint_count = int(reference["J_valid"][0])
    position = np.repeat(reference["ref_position"][None, ...], frames, axis=0)
    rot6d = np.repeat(reference["ref_rot6d"][None, ...], frames, axis=0)
    batch = {
        "position": torch.from_numpy(position[None]).float().to(device),
        "rot6d_a": torch.from_numpy(rot6d[None]).float().to(device),
        "ref_position": torch.from_numpy(reference["ref_position"][None]).float().to(device),
        "ref_rot6d_a": torch.from_numpy(reference["ref_rot6d"][None]).float().to(device),
        "offset_a": torch.from_numpy(reference["offset"][None]).float().to(device),
        "parent_a": torch.from_numpy(reference["parents"][None]).to(torch.int64).to(device),
        "joint_mask": torch.from_numpy(reference["joint_mask"][None]).to(device),
        "ancestor_mask": torch.from_numpy(reference["ancestor_mask"][None]).to(device),
        "graph_hop": torch.from_numpy(reference["graph_hop"][None]).to(torch.int64).to(device),
        "graph_edge": torch.from_numpy(reference["graph_edge"][None]).to(torch.int64).to(device),
        "joint_t5embed": torch.from_numpy(reference["joint_t5embed"][None]).float().to(device),
        "static_pos_joint_mask": torch.from_numpy(reference["static_pos_joint_mask"][None]).to(device),
        "static_rot_joint_mask": torch.from_numpy(reference["static_rot_joint_mask"][None]).to(device),
        "memory_pose": torch.from_numpy(reference["memory_pose"][None]).float().to(device),
        "memory_rot6d": torch.from_numpy(reference["memory_rot6d"][None]).float().to(device),
        "global_scale": torch.from_numpy(reference["global_scale"]).float().to(device),
        "J_valid": torch.from_numpy(reference["J_valid"]).to(torch.int32).to(device),
        "species": ["bind_reference"],
        "image_embed": torch.from_numpy(image_embed[None]).float().to(device),
        "ref_image_embed": torch.from_numpy(ref_image_embed[None]).float().to(device),
    }
    if int(batch["J_valid"].item()) != joint_count:
        raise ValueError("J_valid changed while building the batch")
    return batch


def rotations_from_6d(rot6d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    _vendor_on_path()
    from utils.transforms3d import matrix_to_quaternion, rotation_6d_to_matrix

    tensor = torch.from_numpy(np.asarray(rot6d, dtype=np.float32))
    matrices = rotation_6d_to_matrix(tensor)
    quats = matrix_to_quaternion(matrices)
    return (
        matrices.detach().cpu().numpy().astype(np.float32),
        quats.detach().cpu().numpy().astype(np.float32),
    )


def run_proposal(
    *,
    unit: str,
    clip: str,
    frame_dir: Path,
    idle_png: Path,
    reference_image_png: Path | None = None,
    reference_npz: Path,
    out_dir: Path,
    device_name: str = "cuda",
    sequence_policy: str = "rest_bookend_context_sliced_to_clip",
    window_include_idle: bool = True,
    seed: int | None = None,
    proposal_name: str = "proposal.npz",
    preprocess_policy: str = CLIP_UNION_PREPROCESS,
    do_center_crop: bool = False,
    dino_dtype: str = "float32",
    pose_source_mode: str = "pred",
    position_override: np.ndarray | None = None,
    image_embed_override: np.ndarray | None = None,
    temporal_context: str = "native",
    cyclic: bool = False,
) -> dict[str, Any]:
    assert_keep_authority(KEEP_AUTHORITY)
    if sequence_policy not in {
        "rest_bookend_context_sliced_to_clip",
        "clip_only",
    }:
        raise ValueError(f"unknown sequence policy {sequence_policy!r}")
    frames = _numbered_pngs(require_dir(frame_dir, label="clip frames"))
    idle = require_file(idle_png, label="idle reference frame")
    reference_image = require_file(
        reference_image_png or idle,
        label="model reference image",
    )
    canvas = _canvas_size(frames)
    idle_canvas = _canvas_size([idle])
    if window_include_idle and idle_canvas != canvas:
        raise ValueError(
            f"idle canvas {idle_canvas} != clip canvas {canvas}; "
            "this lane does not resize or crop plates to hide the mismatch"
        )
    if preprocess_policy not in {CLIP_UNION_PREPROCESS, VENDOR_PREPROCESS}:
        raise ValueError(f"unknown preprocess policy {preprocess_policy!r}")
    if temporal_context not in {"native", "repeat_to_24"}:
        raise ValueError(f"unknown temporal context {temporal_context!r}")
    if pose_source_mode not in {"pred", "gt"}:
        raise ValueError(f"unsupported pose_source_mode {pose_source_mode!r}")
    reference_canvas = _canvas_size([reference_image])
    if reference_canvas != canvas:
        raise ValueError(
            f"model reference canvas {reference_canvas} != clip canvas {canvas}; "
            "this lane does not resize or crop plates to hide the mismatch"
        )
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; CPU fallback is disabled")
    if seed is not None:
        np.random.seed(int(seed))
        torch.manual_seed(int(seed))
        if device.type == "cuda":
            torch.cuda.manual_seed_all(int(seed))
    reference = load_reference(reference_npz)
    reference_image_policy = (
        "unpaired_bind_idle" if reference_image_png is None else "explicit_reference_image"
    )
    window_paths = [reference_image, *frames]
    if window_include_idle:
        window_paths = [reference_image, idle, *frames]
    window = clip_locked_subject_window(window_paths, canvas=canvas)
    if sequence_policy == "clip_only":
        video_paths = list(frames)
        expected_len = len(frames)
        temporal_plan = {
            "policy": "native_length",
            "sourceIndex": list(range(len(frames))),
            "outputIndex": list(range(len(frames))),
            "playbackDurationUnchanged": True,
        }
        if temporal_context == "repeat_to_24":
            temporal_plan = expand_frame_indices(len(frames), cyclic=cyclic)
            video_paths = [frames[index] for index in temporal_plan["sourceIndex"]]
            expected_len = len(video_paths)
    else:
        if temporal_context != "native":
            raise ValueError("temporal context expansion is only defined for clip_only")
        video_paths = video_with_rest_bookends(reference_image, frames)
        expected_len = len(frames) + 2
        temporal_plan = {
            "policy": "rest_bookend_then_slice",
            "sourceIndex": list(range(expected_len)),
            "outputIndex": list(range(1, expected_len - 1)),
            "playbackDurationUnchanged": True,
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    dino_meta: dict[str, Any]
    if image_embed_override is not None:
        embeds = np.asarray(image_embed_override, dtype=np.float32)
        dino_meta = {"preprocessPolicy": "supplied_tensors", "supplied": True}
        if embeds.shape[0] != expected_len + 1:
            raise ValueError(
                f"image_embed_override has {embeds.shape[0]} rows, expected {expected_len + 1} "
                "(reference + video)"
            )
    else:
        embeds, dino_meta = encode_frames(
            [reference_image, *video_paths],
            device=str(device),
            canvas=canvas,
            window=window,
            preprocess_policy=preprocess_policy,
            do_center_crop=do_center_crop,
            dino_dtype=dino_dtype,
            encoder_input_dir=out_dir / "encoder_inputs",
        )
    ref_image_embed = embeds[0]
    image_embed = embeds[1:]
    if image_embed.ndim != 3 or image_embed.shape[-1] != 1024:
        raise ValueError(f"unexpected DINO shape {image_embed.shape}")
    if image_embed.shape[0] != expected_len:
        raise ValueError(
            f"{sequence_policy} video has {image_embed.shape[0]} embeddings, expected {expected_len}"
        )
    model, attention, _cfg = load_model(device)
    attention["seq_len"] = int(image_embed.shape[0])
    batch = build_batch(
        reference=reference,
        image_embed=image_embed,
        ref_image_embed=ref_image_embed,
        device=device,
    )
    if position_override is not None:
        override = np.asarray(position_override, dtype=np.float32)
        if override.ndim != 3 or override.shape[-1] != 3:
            raise ValueError(f"position_override must be [T,J,3], got {override.shape}")
        if override.shape[0] == len(frames) and expected_len != len(frames):
            override = override[np.asarray(temporal_plan["sourceIndex"], dtype=np.int64)]
        if override.shape[0] != expected_len:
            raise ValueError(
                f"position_override length {override.shape[0]} != token length {expected_len}"
            )
        padded = np.zeros((expected_len, MAX_JOINTS, 3), dtype=np.float32)
        joint_use = min(int(override.shape[1]), MAX_JOINTS)
        padded[:, :joint_use] = override[:, :joint_use]
        batch["position"] = torch.from_numpy(padded[None]).float().to(device)
    with torch.no_grad():
        output = model(batch, attention_kwargs=attention, pose_source_mode=pose_source_mode)
    joint_count = int(reference["J_valid"][0])
    pred_position_full = output["pred_position"].squeeze(0).detach().cpu().numpy()[:, :joint_count]
    pred_rot6d_full = output["pred_rot6d"].squeeze(0).detach().cpu().numpy()[:, :joint_count]
    pose_for_rot_full = output["pose_for_rot"].squeeze(0).detach().cpu().numpy()[:, :joint_count]
    if pred_position_full.shape[0] != expected_len or pred_rot6d_full.shape[0] != expected_len:
        raise ValueError("model output length does not match the input video")
    pred_position = map_predictions_to_native(pred_position_full, temporal_plan["outputIndex"])
    pred_rot6d = map_predictions_to_native(pred_rot6d_full, temporal_plan["outputIndex"])
    pose_for_rot = map_predictions_to_native(pose_for_rot_full, temporal_plan["outputIndex"])
    matrices, quats = rotations_from_6d(pred_rot6d)
    rest_matrices, rest_quats = rotations_from_6d(reference["ref_rot6d"][:joint_count][None, ...])
    # Keep the historical filename for the default idle-reference lane, but do
    # not label an explicitly paired image as idle in its diagnostic preview.
    preview_name = (
        "dino_input_idle.png"
        if reference_image_policy == "unpaired_bind_idle"
        else "dino_input_reference.png"
    )
    if preprocess_policy == CLIP_UNION_PREPROCESS:
        write_subject_preview(reference_image, window, canvas=canvas, dest=out_dir / preview_name)
        write_subject_preview(frames[0], window, canvas=canvas, dest=out_dir / "dino_input_f00.png")
    else:
        from dino_embed import vendor_per_frame_prepare_rgb, write_encoder_input_preview

        write_encoder_input_preview(
            vendor_per_frame_prepare_rgb(reference_image), out_dir / preview_name
        )
        write_encoder_input_preview(
            vendor_per_frame_prepare_rgb(frames[0]), out_dir / "dino_input_f00.png"
        )
    source_canonical_normalization = None
    for key in ("source_canonical_normalization", "sourceCanonicalNormalization"):
        if key in reference:
            value = reference[key]
            source_canonical_normalization = value.item() if value.ndim == 0 else value.tolist()
            break
    if source_canonical_normalization is None and {
        "source_to_model",
        "global_scale",
    }.issubset(reference):
        source_canonical_normalization = {
            "policy": "max_abs_root_relative_after_source_to_model",
            "globalScale": float(np.asarray(reference["global_scale"]).reshape(-1)[0]),
        }
    np.savez(
        out_dir / proposal_name,
        pred_position=pred_position.astype(np.float32),
        pred_rot6d=pred_rot6d.astype(np.float32),
        pred_position_unmodified=pred_position.astype(np.float32),
        pred_rot6d_unmodified=pred_rot6d.astype(np.float32),
        pred_position_window=pred_position_full.astype(np.float32),
        pred_rot6d_window=pred_rot6d_full.astype(np.float32),
        pose_for_rot=pose_for_rot.astype(np.float32),
        local_matrices=matrices,
        local_quats_wxyz=quats,
        rest_local_matrices=rest_matrices[0],
        rest_local_quats_wxyz=rest_quats[0],
        frame_indices=np.asarray([int(path.stem) for path in frames], dtype=np.int32),
        canvas=np.asarray(canvas, dtype=np.int32),
        source_frame_ms=np.asarray([SOURCE_FRAME_MS], dtype=np.float64),
        **(
            {"source_to_model": np.asarray(reference["source_to_model"], dtype=np.float32)}
            if "source_to_model" in reference
            else {}
        ),
    )
    ident = np.zeros((6,), dtype=np.float32)
    ident[0] = 1.0
    ident[4] = 1.0
    rot_delta = pred_rot6d - ident.reshape(1, 1, 6)
    pos_radius = np.linalg.norm(pred_position, axis=-1)
    motion = report_proposal_motion(
        pred_position=pred_position,
        pred_rot6d=pred_rot6d,
        parents=reference["parents"],
        bind_model=reference["ref_position"],
        joint_count=joint_count,
    )
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "keepAuthority": KEEP_AUTHORITY,
        "unit": unit,
        "clip": clip,
        "frames": [int(path.stem) for path in frames],
        "canvas": list(canvas),
        "sourceFrameMs": SOURCE_FRAME_MS,
        "jointCount": joint_count,
        "checkpoint": str(CHECKPOINT_FILE).replace("\\", "/"),
        "predPositionShape": list(pred_position.shape),
        "predRot6dShape": list(pred_rot6d.shape),
        "predPositionRadiusMean": float(pos_radius.mean()),
        "predPositionRadiusMax": float(pos_radius.max()),
        "predRot6dAbsMean": float(np.abs(rot_delta).mean()),
        "predRot6dAbsMax": float(np.abs(rot_delta).max()),
        "predRot6dAbsMeanIsNotSo3": True,
        "rootPolicy": "static_pos_joint_mask_index0_equals_reference",
        "rootTravelInterpretation": "zero_does_not_prove_absent_source_movement",
        "poseSourceMode": pose_source_mode,
        "preprocessPolicy": preprocess_policy,
        "doCenterCrop": bool(do_center_crop),
        "dinoDtype": dino_dtype,
        "dinoMeta": dino_meta,
        "temporalContext": temporal_context,
        "temporalPlan": temporal_plan,
        "cyclic": bool(cyclic),
        "videoSequencePolicy": sequence_policy,
        "videoSequenceLength": int(pred_position_full.shape[0]),
        "seed": seed,
        "proposalFile": proposal_name,
        "unmodifiedSaved": True,
        "referenceImage": str(reference_image).replace("\\", "/"),
        "referenceImagePolicy": reference_image_policy,
        "rmbg": False,
        "cropped": True,
        "perFrameCrop": preprocess_policy == VENDOR_PREPROCESS,
        "subjectWindow": window,
        "truncated": False,
        "idleCanvas": list(idle_canvas),
        "referenceCanvas": list(reference_canvas),
        "sourceToModel": (
            np.asarray(reference["source_to_model"], dtype=np.float32).tolist()
            if "source_to_model" in reference
            else None
        ),
        "sourceCanonicalNormalization": source_canonical_normalization,
        "motion": motion,
    }
    (out_dir / "proposal_report.json").write_text(
        json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    return report


def _json_default(value: object) -> object:
    from pathlib import Path as _Path

    if isinstance(value, _Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def frames_first(frame_dir: Path) -> str:
    paths = sorted(path for path in frame_dir.glob("*.png") if path.stem.isdigit())
    if not paths:
        raise FileNotFoundError(f"no numbered PNG frames in {frame_dir}")
    return paths[0].name
