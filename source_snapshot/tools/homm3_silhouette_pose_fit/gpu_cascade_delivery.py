"""Slice idle-prefix GPU cascade poses and write in-place skinned clip GLBs.

Idle (DEF group 2) ships as its own clip. When concatenated in front of other
groups during fitting, that idle span is a posing prefix only and is stripped
from every other delivered clip. Camera-space motion root stays in the fit
result for sprite registration and is not written into Unity clips.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from roc_gpu_cascade_experiment import (
    MOTION_ROOT_KEY,
    MOTION_ROOT_ROTATION_KEY,
    _axis_angle_quaternion_np,
    _quat_multiply,
)
from deliberate_motion_boundaries import close_cycle_pose_copy
from deliberate_motion_contract import (
    AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
    clip_lifecycle_row,
    contract_suffix,
    lifecycle_role_for_clip_name,
    sample_times_seconds,
)

IDLE_GROUP = 2
SOURCE_FPS = 12.0
ROTATION_MINUS_90_YAW = [0.0, -0.7071067811865476, 0.0, 0.7071067811865476]

# Crusader DEF groups 7 and 8 are the same two sprites in reverse order.
# Olden Era's Esquire controller has no turn states for them. Do not fit or ship.
# Groups 11 and 13 (attack up/down) and 14/16 (shoot up/down) are skipped:
# Olden Era's 3D space has no vertical attack/shoot variants. Keep 12 and 15.
SKIPPED_DEF_GROUPS = frozenset({7, 8, 11, 13, 14, 16})
ALBEDO_JPEG_NAME = "crusader_owned_skinned_basecolor.jpg"
NORMAL_PNG_NAME = "crusader_owned_skinned_normal.png"
METALLIC_GLOSS_PNG_NAME = "crusader_owned_skinned_metallicgloss.png"

CONTRACT_SUFFIX_BY_GROUP = {
    0: "Move",
    1: "Mouseover",
    2: "Idle",
    3: "Hitted",
    4: "Defence",
    5: "Death",
    12: "AttackFront",
    15: "ShootFront",
    20: "MoveStart",
    21: "MoveEnd",
}

# Chosen OE skinned-mesh DEF groups. Turns (7/8), attack up/down (11/13),
# and shoot up/down (14/16) stay skipped. ShootFront is required only when
# the unit DEF has group 15.
CHOSEN_DEF_GROUPS = frozenset(CONTRACT_SUFFIX_BY_GROUP)

CONTRACT_BY_GROUP = {
    group: f"Crusader_{suffix}"
    for group, suffix in CONTRACT_SUFFIX_BY_GROUP.items()
    if group != 15
}

# Ranged units: only the front shoot group maps into OE 3D space.
SHOOT_CONTRACT_BY_GROUP = {
    15: "Crusader_ShootFront",
}


def contract_prefix_for_unit(unit_sid: str) -> str:
    """Unity clip-name prefix for a unit. Only the Crusader owns a unit-named contract set."""
    if not isinstance(unit_sid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", unit_sid):
        raise ValueError(f"unit sid must be a lab/inventory identifier, got {unit_sid!r}")
    return "Crusader" if unit_sid == "h3_crusader" else "Unit"


def contract_name_for_group(group: int, prefix: str = "Crusader") -> str:
    """Return the Unity clip contract name for a DEF group."""
    suffix = CONTRACT_SUFFIX_BY_GROUP.get(int(group))
    if suffix is None:
        raise KeyError(f"DEF group {group} is not a chosen skinned-mesh contract")
    return f"{prefix}_{suffix}"


def chosen_contracts_for_groups(groups: Sequence[int], prefix: str = "Crusader") -> dict[int, str]:
    """Map present DEF groups onto the chosen skinned-mesh contracts."""
    out: dict[int, str] = {}
    for group in groups:
        if int(group) in SKIPPED_DEF_GROUPS or int(group) not in CHOSEN_DEF_GROUPS:
            continue
        out[int(group)] = contract_name_for_group(int(group), prefix)
    if not out:
        raise ValueError(f"no chosen contracts in DEF groups {list(groups)}")
    return out

def select_unit_delivery_choices(choices, unit_sid: str):
    """Pick idle-leading authentic DEF sequences covering every chosen group."""
    selected = []
    covered: set[int] = set()
    present: set[int] = set()
    sid = str(unit_sid)
    for choice in choices:
        if str(choice.unit_sid) != sid or str(choice.source_kind) != "authentic_def":
            continue
        if str(getattr(choice, "sequence_kind", "") or "") == "motion_only":
            continue
        groups = tuple(int(group) for group in choice.def_lab_groups)
        if not groups or groups[0] != IDLE_GROUP:
            continue
        present.update(int(group) for group in (choice.present_groups or ()))
        ship = [
            group
            for group in groups
            if group in CHOSEN_DEF_GROUPS
            and group not in SKIPPED_DEF_GROUPS
            and not (group == IDLE_GROUP and len(groups) > 1)
        ]
        if not ship:
            continue
        overlap = set(ship) & covered
        if overlap:
            raise RuntimeError(
                f"{sid}: DEF group(s) {sorted(overlap)} are covered by more than one picker sequence"
            )
        covered.update(ship)
        selected.append(choice)
    required = (present & CHOSEN_DEF_GROUPS) - set(SKIPPED_DEF_GROUPS)
    if IDLE_GROUP not in covered:
        raise RuntimeError(f"{sid}: missing idle DEF group {IDLE_GROUP}")
    missing = sorted(required - covered)
    if missing:
        raise RuntimeError(f"{sid}: missing chosen delivery DEF groups: {missing}")
    return selected


CURRENT_CASCADE_KEEP = {
    "solver": "cascade",
    "joint_collision_positive_abs_slack": 0.12,
    "joint_temporal_consensus_enabled": True,
    "joint_temporal_consensus_bidirectional": True,
    "joint_temporal_consensus_idle_end": True,
    "joint_temporal_consensus_independent_passes": True,
    "joint_temporal_consensus_whole_pose": True,
    "root_rotation_camera_up_limit_deg": 45.0,
    "root_rotation_defer_camera_up": True,
    "joint_adaptive_step_enabled": True,
    "joint_step_score_norm": "logit_minmax",
    "articulated_iterations": 2,
    "physics_smooth_enabled": True,
}


def group_frame_spans(
    groups: Sequence[int],
    counts: Sequence[int],
) -> tuple[tuple[int, int, int], ...]:
    """Return (group_id, start_index, frame_count) for a concatenated DEF sequence."""
    if len(groups) != len(counts):
        raise ValueError(
            f"DEF group/count length mismatch: groups={list(groups)} counts={list(counts)}"
        )
    if any(int(count) < 1 for count in counts):
        raise ValueError(f"DEF expected counts must be positive: {list(counts)}")
    spans: list[tuple[int, int, int]] = []
    start = 0
    for group, count in zip(groups, counts):
        spans.append((int(group), start, int(count)))
        start += int(count)
    return tuple(spans)


def delivery_poses_by_group(
    poses: Mapping[Any, Mapping[str, Any]],
    groups: Sequence[int],
    counts: Sequence[int],
    *,
    idle_group: int = IDLE_GROUP,
) -> dict[int, dict[int, dict[str, Any]]]:
    """Return per-group poses with frames reindexed from 0.

    Idle is delivered only from an idle-only sequence. When idle leads a
    multi-group fit, it is omitted from every other group's shipped clip.

    ``poses`` is keyed by concatenated fit-frame index (0 .. sum(counts)-1).
    """
    keyed = {int(frame): dict(pose) for frame, pose in poses.items()}
    spans = group_frame_spans(groups, counts)
    expected = sum(int(count) for count in counts)
    missing = [index for index in range(expected) if index not in keyed]
    if missing:
        raise KeyError(f"GPU result is missing concatenated frames: {missing[:12]}")
    extra = sorted(frame for frame in keyed if frame < 0 or frame >= expected)
    if extra:
        raise ValueError(f"GPU result has poses outside the concatenated DEF span: {extra[:12]}")

    idle_only = len(spans) == 1 and int(spans[0][0]) == int(idle_group)
    delivered: dict[int, dict[int, dict[str, Any]]] = {}
    for group, start, count in spans:
        if int(group) == int(idle_group) and not idle_only:
            continue
        sliced: dict[int, dict[str, Any]] = {}
        for local_index in range(count):
            sliced[local_index] = keyed[start + local_index]
        delivered[int(group)] = sliced
    if not delivered:
        raise ValueError("delivery slice produced no groups")
    return delivered


def clip_result_matches_current_keep(payload: Mapping[str, Any]) -> bool:
    """True when a persisted GPU result used the sprite-authority cascade keep."""
    if payload.get("solver") != CURRENT_CASCADE_KEEP["solver"]:
        return False
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    if float(config.get("joint_collision_positive_abs_slack", -1.0)) != float(
        CURRENT_CASCADE_KEEP["joint_collision_positive_abs_slack"]
    ):
        return False
    if bool(config.get("joint_temporal_consensus_enabled")) is not True:
        return False
    if bool(config.get("joint_temporal_consensus_bidirectional")) is not True:
        return False
    if bool(config.get("joint_temporal_consensus_idle_end")) is not True:
        return False
    if bool(config.get("joint_temporal_consensus_independent_passes")) is not True:
        return False
    if bool(config.get("joint_temporal_consensus_whole_pose")) is not True:
        return False
    if float(config.get("root_rotation_camera_up_limit_deg", -1.0)) != float(
        CURRENT_CASCADE_KEEP["root_rotation_camera_up_limit_deg"]
    ):
        return False
    if bool(config.get("root_rotation_defer_camera_up")) is not True:
        return False
    if bool(config.get("joint_adaptive_step_enabled")) is not True:
        return False
    if str(config.get("joint_step_score_norm")) != str(CURRENT_CASCADE_KEEP["joint_step_score_norm"]):
        return False
    if int(config.get("articulated_iterations", 0)) != int(CURRENT_CASCADE_KEEP["articulated_iterations"]):
        return False
    if bool(config.get("physics_smooth_enabled")) is not True:
        return False
    if str(config.get("score_mode") or "geometry") != "geometry":
        return False
    if bool(config.get("chain_space_enabled")):
        return False
    if float(config.get("motion_weight") or 0.0) != 0.0:
        return False
    if bool(config.get("sprite_aligned_motion_keep_enabled")):
        return False
    poses = payload.get("poses")
    return isinstance(poses, Mapping) and bool(poses)


# Notebook cells are often left on dinov3_dense / physics off / 1 articulated
# round from experiments. Delivery restores CURRENT_CASCADE_KEEP and the last
# shipped crusader geometry term weights so scoring is not an empty dinov3 path.
GEOMETRY_DELIVERY_GPU_OVERRIDES = {
    "score_mode": "geometry",
    "silhouette_weight": 0.01,
    "depth_weight": 0.99,
    "chroma_weight": 0.5,
    "chroma_tolerance": 0.10,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "chain_space_enabled": False,
    "motion_weight": 0.0,
    "sprite_aligned_motion_keep_enabled": False,
    "gradient_ladder_enabled": False,
    "ik_enabled": False,
}


def apply_current_cascade_keep(gpu_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Force notebook GPU kwargs onto the sprite-authority keep fingerprint."""
    out = dict(gpu_kwargs)
    out.update(GEOMETRY_DELIVERY_GPU_OVERRIDES)
    for key, value in CURRENT_CASCADE_KEEP.items():
        if key == "solver":
            continue
        out[key] = value
    probe = {"solver": "cascade", "config": out, "poses": {"0": {"Bone_000": {"x": 0.0}}}}
    if not clip_result_matches_current_keep(probe):
        raise RuntimeError("delivery GPU kwargs do not satisfy CURRENT_CASCADE_KEEP")
    return out


def require_pose_units_degrees(payload: Mapping[str, Any], *, source: str) -> None:
    """Fail closed unless the clip-result payload declares degree pose units.

    The serializer writes ``"poseUnits": "degrees"``; results persisted before
    that marker existed must be audited and stamped by
    ``mark_pose_units_degrees.py`` (or re-fit) before they may feed the GLB
    clip exporter. Exporting unmarked poses risks replaying the degrees data
    as radians, which over-rotates every joint ~57.3x.
    """
    units = payload.get("poseUnits")
    if units != "degrees":
        raise RuntimeError(
            f"{source} has poseUnits={units!r}; the clip GLB exporter requires 'degrees'. "
            "Re-fit the clip, or audit stored magnitudes against the radians cap and stamp "
            "the marker with tools/homm3_silhouette_pose_fit/mark_pose_units_degrees.py."
        )


def gpu_pose_local_rotation(rest_xyzw: Sequence[float], delta_xyz: Sequence[float]) -> np.ndarray:
    """Return the GPU evaluator's local quaternion: rest * axis-angle delta.

    ``delta_xyz`` is a serialized pose-dict entry: an axis-angle vector in
    DEGREES (``RocGpuCascadeExperiment._pose_dicts`` applies ``np.degrees``;
    ``_pose_entry_to_xyz`` converts back with ``math.radians``). The exporter
    must convert to radians before building the quaternion — treating the
    stored numbers as radians over-rotates every joint ~57.3x and melts the
    skinned mesh in game.
    """
    rest = np.asarray(rest_xyzw, dtype=np.float64).reshape(4)
    radians = np.radians(np.asarray(delta_xyz, dtype=np.float64).reshape(3))
    return _quat_multiply(rest, _axis_angle_quaternion_np(radians))


def _read_glb(path: Path) -> tuple[dict[str, Any], bytearray]:
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    json_blob: dict[str, Any] | None = None
    bin_blob = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        payload = data[start : start + chunk_length]
        if chunk_type == b"JSON":
            json_blob = json.loads(payload.decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_blob = payload
        offset = start + chunk_length
    if json_blob is None:
        raise ValueError(f"no JSON chunk: {path}")
    return json_blob, bytearray(bin_blob)


def _write_glb(path: Path, doc: Mapping[str, Any], bin_blob: bytes) -> None:
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(bin_blob) + b"\x00" * ((4 - len(bin_blob) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I4s", len(json_bytes), b"JSON")
    out += json_bytes
    out += struct.pack("<I4s", len(bin_bytes), b"BIN\x00")
    out += bin_bytes
    Path(path).write_bytes(bytes(out))


def _glb_embedded_image_payload(
    src: Path,
    doc: Mapping[str, Any],
    bin_blob: bytes,
    tex_ref: Mapping[str, Any],
    *,
    slot: str,
) -> tuple[bytes, str]:
    textures = doc.get("textures")
    images = doc.get("images")
    if not isinstance(textures, list) or not textures:
        raise ValueError(f"{src} has no textures")
    if not isinstance(images, list) or not images:
        raise ValueError(f"{src} has no images")
    if "index" not in tex_ref:
        raise ValueError(f"{src} {slot} has no texture index")
    texture = textures[int(tex_ref["index"])]
    source = texture.get("source")
    if source is None:
        raise ValueError(f"{src} {slot} has no image source")
    image = images[int(source)]
    mime = str(image.get("mimeType") or "application/octet-stream")
    if "bufferView" not in image:
        raise ValueError(f"{src} {slot} image is not embedded")
    view = doc["bufferViews"][int(image["bufferView"])]
    start = int(view.get("byteOffset", 0))
    end = start + int(view["byteLength"])
    if start < 0 or end > len(bin_blob):
        raise ValueError(f"{src} {slot} image exceeds BIN chunk")
    return bytes(bin_blob[start:end]), mime


def glb_material0_pbr(
    src_glb: str | Path,
    *,
    require_metallic_roughness: bool = True,
    require_normal: bool = True,
) -> dict[str, Any]:
    """Return material 0 PBR texture refs.

    Missing metal/normal fail closed by default. Rollout export may allow a
    recorded neutral map so a SmartRig without those textures still ships.
    """
    src = Path(src_glb).resolve()
    doc, bin_blob = _read_glb(src)
    materials = doc.get("materials")
    if not isinstance(materials, list) or not materials:
        raise ValueError(f"{src} has no materials")
    material = materials[0]
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, dict):
        raise ValueError(f"{src} material 0 has no pbrMetallicRoughness")
    base_ref = pbr.get("baseColorTexture")
    metal_ref = pbr.get("metallicRoughnessTexture")
    normal_ref = material.get("normalTexture")
    if not isinstance(base_ref, dict):
        raise ValueError(f"{src} material 0 has no baseColorTexture")
    if not isinstance(metal_ref, dict):
        if require_metallic_roughness:
            raise ValueError(f"{src} material 0 has no metallicRoughnessTexture")
        metal_ref = None
    if not isinstance(normal_ref, dict):
        if require_normal:
            raise ValueError(f"{src} material 0 has no normalTexture")
        normal_ref = None
    return {
        "doc": doc,
        "bin": bin_blob,
        "src": src,
        "baseColorTexture": base_ref,
        "metallicRoughnessTexture": metal_ref,
        "normalTexture": normal_ref,
    }


def glb_basecolor_image_payload(
    src_glb: str | Path,
    *,
    require_metallic_roughness: bool = True,
    require_normal: bool = True,
) -> tuple[bytes, str]:
    """Return (bytes, mime) for the first mesh material's baseColorTexture."""
    info = glb_material0_pbr(
        src_glb,
        require_metallic_roughness=require_metallic_roughness,
        require_normal=require_normal,
    )
    return _glb_embedded_image_payload(
        info["src"],
        info["doc"],
        info["bin"],
        info["baseColorTexture"],
        slot="baseColorTexture",
    )


def pack_gltf_metallic_roughness_to_unity_metallic_gloss(image: Any) -> Any:
    """glTF ORM (G=roughness, B=metallic) → Unity MetallicGlossMap (R=metallic, A=smoothness)."""
    from PIL import Image

    if not isinstance(image, Image.Image):
        raise TypeError("metallic-roughness image must be a PIL Image")
    pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    metal = pixels[..., 2]
    roughness = pixels[..., 1]
    packed = np.zeros_like(pixels)
    packed[..., 0] = metal
    packed[..., 1] = metal
    packed[..., 2] = metal
    packed[..., 3] = np.uint8(255) - roughness
    return Image.fromarray(packed, mode="RGBA")


def extract_glb_basecolor_jpeg(
    src_glb: str | Path,
    dest_jpeg: str | Path,
    *,
    quality: int = 95,
    require_metallic_roughness: bool = True,
    require_normal: bool = True,
) -> dict[str, Any]:
    """Write the mesh's own baseColor atlas as a JPEG for the Unity lab."""
    from PIL import Image

    payload, mime = glb_basecolor_image_payload(
        src_glb,
        require_metallic_roughness=require_metallic_roughness,
        require_normal=require_normal,
    )
    dest = Path(dest_jpeg).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(payload)) as image:
        rgb = image.convert("RGB")
        rgb.save(dest, format="JPEG", quality=int(quality), subsampling=0, optimize=True)
        width, height = rgb.size
    return {
        "source": str(Path(src_glb).resolve()),
        "output": str(dest),
        "sourceMime": mime,
        "sourceSha256": hashlib.sha256(payload).hexdigest().upper(),
        "jpegSha256": hashlib.sha256(dest.read_bytes()).hexdigest().upper(),
        "width": int(width),
        "height": int(height),
    }


def extract_glb_hexlit_pbr_maps(
    src_glb: str | Path,
    dest_dir: str | Path,
    *,
    jpeg_quality: int = 95,
    allow_missing_pbr_maps: bool = False,
) -> dict[str, Any]:
    """Write albedo JPEG plus Hex/Lit normal and metallic-gloss PNGs next to the master."""
    from PIL import Image

    info = glb_material0_pbr(
        src_glb,
        require_metallic_roughness=not allow_missing_pbr_maps,
        require_normal=not allow_missing_pbr_maps,
    )
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    albedo = extract_glb_basecolor_jpeg(
        src_glb,
        dest / ALBEDO_JPEG_NAME,
        quality=jpeg_quality,
        require_metallic_roughness=not allow_missing_pbr_maps,
        require_normal=not allow_missing_pbr_maps,
    )
    notes: list[str] = []

    normal_path = dest / NORMAL_PNG_NAME
    if info["normalTexture"] is None:
        notes.append("missing_normalTexture")
        rgb = Image.new("RGB", (int(albedo["width"]), int(albedo["height"])), (128, 128, 255))
        rgb.save(normal_path, format="PNG", optimize=True)
        normal_size = rgb.size
        normal_report = {
            "output": str(normal_path),
            "source": "neutral_default_missing_glb_texture",
            "width": int(normal_size[0]),
            "height": int(normal_size[1]),
        }
    else:
        normal_payload, normal_mime = _glb_embedded_image_payload(
            info["src"],
            info["doc"],
            info["bin"],
            info["normalTexture"],
            slot="normalTexture",
        )
        with Image.open(io.BytesIO(normal_payload)) as image:
            rgb = image.convert("RGB")
            rgb.save(normal_path, format="PNG", optimize=True)
            normal_size = rgb.size
        normal_report = {
            "output": str(normal_path),
            "sourceMime": normal_mime,
            "sourceSha256": hashlib.sha256(normal_payload).hexdigest().upper(),
            "pngSha256": hashlib.sha256(normal_path.read_bytes()).hexdigest().upper(),
            "width": int(normal_size[0]),
            "height": int(normal_size[1]),
        }

    metal_path = dest / METALLIC_GLOSS_PNG_NAME
    if info["metallicRoughnessTexture"] is None:
        notes.append("missing_metallicRoughnessTexture")
        packed = Image.new(
            "RGBA",
            (int(albedo["width"]), int(albedo["height"])),
            (0, 0, 0, 89),
        )
        packed.save(metal_path, format="PNG", optimize=True)
        metal_size = packed.size
        metal_report = {
            "output": str(metal_path),
            "source": "neutral_default_missing_glb_texture",
            "width": int(metal_size[0]),
            "height": int(metal_size[1]),
            "unitySmoothness": 0.35,
        }
    else:
        metal_payload, metal_mime = _glb_embedded_image_payload(
            info["src"],
            info["doc"],
            info["bin"],
            info["metallicRoughnessTexture"],
            slot="metallicRoughnessTexture",
        )
        with Image.open(io.BytesIO(metal_payload)) as image:
            packed = pack_gltf_metallic_roughness_to_unity_metallic_gloss(image)
            packed.save(metal_path, format="PNG", optimize=True)
            metal_size = packed.size
        metal_report = {
            "output": str(metal_path),
            "sourceMime": metal_mime,
            "sourceSha256": hashlib.sha256(metal_payload).hexdigest().upper(),
            "pngSha256": hashlib.sha256(metal_path.read_bytes()).hexdigest().upper(),
            "width": int(metal_size[0]),
            "height": int(metal_size[1]),
        }

    albedo_w = int(albedo["width"])
    albedo_h = int(albedo["height"])
    if normal_size != (albedo_w, albedo_h):
        notes.append(
            f"resized_normal_{normal_size[0]}x{normal_size[1]}_to_{albedo_w}x{albedo_h}"
        )
        with Image.open(normal_path) as image:
            rgb = image.convert("RGB").resize((albedo_w, albedo_h), Image.Resampling.LANCZOS)
            rgb.save(normal_path, format="PNG", optimize=True)
            normal_size = rgb.size
        normal_report = dict(normal_report)
        normal_report["resizedFrom"] = [int(normal_report["width"]), int(normal_report["height"])]
        normal_report["width"] = int(normal_size[0])
        normal_report["height"] = int(normal_size[1])
        normal_report["pngSha256"] = hashlib.sha256(normal_path.read_bytes()).hexdigest().upper()
    if metal_size != (albedo_w, albedo_h):
        notes.append(
            f"resized_metallicGloss_{metal_size[0]}x{metal_size[1]}_to_{albedo_w}x{albedo_h}"
        )
        with Image.open(metal_path) as image:
            packed = image.convert("RGBA").resize((albedo_w, albedo_h), Image.Resampling.LANCZOS)
            packed.save(metal_path, format="PNG", optimize=True)
            metal_size = packed.size
        metal_report = dict(metal_report)
        metal_report["resizedFrom"] = [int(metal_report["width"]), int(metal_report["height"])]
        metal_report["width"] = int(metal_size[0])
        metal_report["height"] = int(metal_size[1])
        metal_report["pngSha256"] = hashlib.sha256(metal_path.read_bytes()).hexdigest().upper()
    return {
        "albedo": albedo,
        "normal": normal_report,
        "metallicGloss": metal_report,
        "pbrNotes": notes,
    }


def _append_floats(doc: dict[str, Any], bin_blob: bytearray, values: np.ndarray, accessor_type: str) -> int:
    raw = np.asarray(values, dtype="<f4").reshape(-1).tobytes()
    pad = (4 - (len(bin_blob) % 4)) % 4
    bin_blob.extend(b"\x00" * pad)
    view_index = len(doc.setdefault("bufferViews", []))
    doc["bufferViews"].append(
        {
            "buffer": 0,
            "byteOffset": len(bin_blob),
            "byteLength": len(raw),
        }
    )
    bin_blob.extend(raw)
    accessor_index = len(doc.setdefault("accessors", []))
    count = int(np.asarray(values).reshape(-1, {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor_type]).shape[0])
    accessor: dict[str, Any] = {
        "bufferView": view_index,
        "componentType": 5126,
        "count": count,
        "type": accessor_type,
    }
    flat = np.asarray(values, dtype=np.float32).reshape(count, -1)
    accessor["min"] = [float(v) for v in flat.min(axis=0)]
    accessor["max"] = [float(v) for v in flat.max(axis=0)]
    doc["accessors"].append(accessor)
    return accessor_index


def _rest_rotation(node: Mapping[str, Any]) -> np.ndarray:
    value = node.get("rotation")
    if value is None:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    rest = np.asarray(value, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(rest))
    if norm <= 1e-12:
        raise ValueError(f"node {node.get('name')!r} has a zero rest quaternion")
    return rest / norm


def _pose_delta(pose: Mapping[str, Any], bone_name: str) -> tuple[float, float, float]:
    entry = pose.get(bone_name)
    if entry is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(entry, Mapping):
        raise TypeError(f"pose for {bone_name!r} must be an xyz mapping")
    return (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)), float(entry.get("z", 0.0)))


def _align_quaternion(previous: np.ndarray | None, current: np.ndarray) -> np.ndarray:
    if previous is None:
        return current
    if float(np.dot(previous, current)) < 0.0:
        return -current
    return current


def write_gpu_cascade_clip_glb(
    src_glb: str | Path,
    dest_glb: str | Path,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    clip_name: str,
    fps: float = SOURCE_FPS,
    lifecycle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write bone-local rotation animation. Motion root is intentionally omitted.

    ``poses`` maps frame -> bone -> axis-angle vector in DEGREES (the
    ``gpu_clip_result.json`` pose contract; see ``gpu_pose_local_rotation``).
    Callers exporting from a clip-result payload must verify the payload's
    ``poseUnits`` marker before calling (see ``require_pose_units_degrees``).

    Cycle clips receive a quaternion-sign-aligned copy of frame 0 at
    ``N * frameDuration`` so ``loopTime`` repeats a closed period.
    """
    frames = tuple(sorted(int(frame) for frame in poses))
    if not frames:
        raise ValueError(f"refusing to write an empty clip: {clip_name}")
    if frames != tuple(range(len(frames))):
        raise ValueError(f"{clip_name} delivery poses must be reindexed 0..n-1, got {frames}")
    row = dict(lifecycle) if lifecycle is not None else clip_lifecycle_row(
        clip_name=str(clip_name),
        def_group=-1,
        source_frame_count=len(frames),
        frame_duration_seconds=AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
    )
    role = str(row.get("lifecycleRole") or lifecycle_role_for_clip_name(clip_name))
    dt = float(row.get("frameDurationSeconds") or AUTHENTIC_DEF_FRAME_DURATION_SECONDS)
    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError(f"{clip_name}: frameDurationSeconds must be positive, got {dt}")
    if abs(float(fps) * dt - 1.0) > 1e-6:
        raise ValueError(
            f"{clip_name}: fps={fps} is not the reciprocal of lifecycle "
            f"frameDurationSeconds={dt}; do not mix solver FPS with delivery timing"
        )
    times_list = sample_times_seconds(len(frames), role=role, frame_duration_seconds=dt)
    pose_keys = tuple(range(len(frames) + 1)) if role == "cycle" else frames
    if len(times_list) != len(pose_keys):
        raise ValueError(
            f"{clip_name}: lifecycle times {len(times_list)} != export keys {len(pose_keys)}"
        )

    src = Path(src_glb).resolve()
    dest = Path(dest_glb).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source mesh is missing: {src}")
    doc, bin_blob = _read_glb(src)
    buffers = doc.get("buffers")
    if not isinstance(buffers, list) or len(buffers) != 1:
        raise ValueError(f"{src} must have exactly one GLB buffer")
    skins = doc.get("skins")
    if not isinstance(skins, list) or not skins:
        raise ValueError(f"{src} has no skin; cannot write a skinned clip")
    joints = [int(index) for index in skins[0]["joints"]]
    if not joints:
        raise ValueError(f"{src} skin has no joints")
    nodes = doc["nodes"]
    times = np.asarray(times_list, dtype=np.float32)
    time_accessor = _append_floats(doc, bin_blob, times, "SCALAR")
    samplers: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    animated = 0
    closing_pose = close_cycle_pose_copy(poses[frames[0]]) if role == "cycle" else None
    for node_index in joints:
        node = nodes[int(node_index)]
        name = str(node.get("name") or "")
        if not name:
            raise ValueError(f"skinned node {node_index} has no name")
        rest = _rest_rotation(node)
        rotations: list[np.ndarray] = []
        previous = None
        for key in pose_keys:
            if role == "cycle" and int(key) == len(frames):
                delta = _pose_delta(closing_pose, name)
            else:
                delta = _pose_delta(poses[int(key)], name)
            local = gpu_pose_local_rotation(rest, delta)
            local = _align_quaternion(previous, local)
            rotations.append(local)
            previous = local
        stacked = np.stack(rotations).astype(np.float32)
        rotation_accessor = _append_floats(doc, bin_blob, stacked, "VEC4")
        sampler_index = len(samplers)
        samplers.append(
            {
                "input": time_accessor,
                "output": rotation_accessor,
                "interpolation": "LINEAR",
            }
        )
        channels.append(
            {
                "sampler": sampler_index,
                "target": {"node": int(node_index), "path": "rotation"},
            }
        )
        animated += 1
    doc["buffers"] = [{"byteLength": len(bin_blob)}]
    doc["animations"] = [
        {
            "name": str(clip_name),
            "samplers": samplers,
            "channels": channels,
        }
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_glb(dest, doc, bin_blob)
    return {
        "source": str(src),
        "output": str(dest),
        "clipName": str(clip_name),
        "frameCount": len(frames),
        "sourceFrameCount": len(frames),
        "keyCount": len(pose_keys),
        "fps": 1.0 / dt,
        "frameDurationSeconds": dt,
        "lifecycleRole": role,
        "suffix": contract_suffix(str(clip_name)),
        "loopTime": role == "cycle",
        "jointCount": animated,
        "durationSeconds": float(times_list[-1]),
        "serializeRegistrationRoot": False,
        "applyRootMotion": False,
    }


def bake_orientation_minus_90_yaw(path: str | Path, *, rewrite: bool = True) -> dict[str, Any]:
    """Insert or rewrite the Unity-facing Orientation node. Does not retarget animation indices."""
    glb = Path(path).resolve()
    doc, bin_blob = _read_glb(glb)
    nodes = doc["nodes"]
    root_index = int(doc["scenes"][0]["nodes"][0])
    root = nodes[root_index]
    existing = next((index for index, node in enumerate(nodes) if node.get("name") == "Orientation"), None)
    if existing is not None:
        if not rewrite:
            return {"source": str(glb), "status": "already has Orientation"}
        nodes[existing]["rotation"] = list(ROTATION_MINUS_90_YAW)
        _write_glb(glb, doc, bin_blob)
        return {"source": str(glb), "status": "rewrote Orientation to -90 glTF yaw"}
    children = list(root.get("children", []))
    mesh_node = next((child for child in children if nodes[child].get("mesh") is not None), None)
    skeleton_root = next((child for child in children if child != mesh_node), None)
    if skeleton_root is None:
        raise ValueError(f"no skeleton root child found under {root.get('name')}: {children}")
    orientation_index = len(nodes)
    nodes.append(
        {
            "name": "Orientation",
            "rotation": list(ROTATION_MINUS_90_YAW),
            "children": [int(skeleton_root)],
        }
    )
    root["children"] = [child for child in children if child != skeleton_root] + [orientation_index]
    _write_glb(glb, doc, bin_blob)
    return {
        "source": str(glb).replace("\\", "/"),
        "root": root.get("name"),
        "skeletonRoot": nodes[skeleton_root].get("name"),
        "orientationNode": orientation_index,
        "rotationYawDeg": -90.0,
    }


def write_oriented_master_glb(
    src_glb: str | Path,
    dest_glb: str | Path,
    *,
    allow_missing_pbr_maps: bool = False,
) -> dict[str, Any]:
    src = Path(src_glb).resolve()
    dest = Path(dest_glb).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    report = bake_orientation_minus_90_yaw(dest, rewrite=True)
    report["master"] = str(dest)
    report["pbr"] = extract_glb_hexlit_pbr_maps(
        dest,
        dest.parent,
        allow_missing_pbr_maps=allow_missing_pbr_maps,
    )
    report["albedo"] = report["pbr"]["albedo"]
    return report


def write_oriented_clip_glb(
    src_glb: str | Path,
    dest_glb: str | Path,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    clip_name: str,
    fps: float = SOURCE_FPS,
    lifecycle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = write_gpu_cascade_clip_glb(
        src_glb, dest_glb, poses, clip_name=clip_name, fps=fps, lifecycle=lifecycle
    )
    report["orientation"] = bake_orientation_minus_90_yaw(dest_glb, rewrite=True)
    return report
