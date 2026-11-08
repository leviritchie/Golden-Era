"""Pinned checkpoint, vendor revision, hashes, and seed for the mocap-only path."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

from paths import CHECKPOINT_FILE, VENDOR, VENDOR_INFERENCE_YAML

BASELINE_SEED = 42
EXPECTED_VENDOR_REVISION = "c99fb22c2f6001958c73c197065322b98ca0b93b"
EXPECTED_CHECKPOINT_SHA256 = "f201f553225e937c743486db05c1edf10af37dce096d0c0e8722dda90de0b28f"
LOCKED_SETTINGS = {
    "sequencePolicy": "clip_only",
    "referenceImagePolicy": "bind_render_of_reference_skeleton",
    "memoryPolicy": "singleton_bind_reference",
    "subjectWindowPolicy": "clip_locked_union_alpha_aabb",
    "rmbg": False,
    "perFrameCrop": False,
    "dinoCenterCrop": False,
    "modelDtype": "float32",
    "poseSourceMode": "pred",
    "seed": BASELINE_SEED,
    "rootPolicy": "static_pos_joint_mask_index0_equals_reference",
    "rootTravelInterpretation": "zero_does_not_prove_absent_source_movement",
    "motionGate": "temporal_root_relative_not_bind_offset",
    "positionTransferSmoothing": "disabled_for_diagnosis",
    "nativeTransfer": "bind_basis_conversion_original_skin",
    "positionTransfer": "explicit_second_diagnostic_unsmoothed",
    "outputBookends": False,
}

# Intermediate-skeleton capture. Separate from direct-SmartRig baseline settings.
INTERMEDIATE_LOCKED_SETTINGS = {
    "sequencePolicy": "clip_only",
    "referenceImagePolicy": "vendor_stored_image_embed",
    "referenceSkeletonPolicy": "unmodified_vendor_package",
    "memoryPolicy": "singleton_bind_reference",
    "subjectWindowPolicy": "vendor_per_frame_prepare_image",
    "rmbg": False,
    "perFrameCrop": True,
    "dinoCenterCrop": True,
    "modelDtype": "float16",
    "poseSourceMode": "pred",
    "motionInterface": "pred_position",
    "learnedRotations": "diagnosis_only_not_fallback",
    "smartRigNetworkInput": False,
    "seed": BASELINE_SEED,
    "rootPolicy": "static_pos_joint_mask_index0_equals_reference",
    "rootTravelInterpretation": "zero_does_not_prove_absent_source_movement",
    "rootTranslationAvailable": False,
    "fkRotationConvention": "storage_rot6d_first_two_rows",
    "vendorOffsetARootSubtract": "not_the_fk_offset_convention",
    "retargeter": "parent_relative_direction_bind_frame_gated_on_capture_acceptance",
    "twistPolicy": "minimum_change_prior_not_captured_evidence",
    "outputBookends": False,
}

# Roc copy skinned to the Eagle capture skeleton. Separate from SmartRig retarget.
EAGLE_SKINNED_SETTINGS = {
    "captureReuse": "saved_raw_capture_npz_no_rerun",
    "donorReference": "zoo:Eagle#Eagle-Landing/y15",
    "bindPose": "tpose_from_unmodified_bvh_offsets_not_landing_frame0_not_flight_frame0",
    "characterRestBvh": "blender_scale_100x_offsets_not_capture_bind",
    "meshTemplate": "base_mesh.obj_same_row_as_blender_vertices",
    "weightAuthority": "donor_region_restricted_barycentric_not_nearest_bone",
    "originalSmartRig": "untouched",
    "twistPolicy": "minimum_change_prior_not_captured_evidence",
    "hypothesisA": "fixed_length_rotation_only_on_eagle_bind",
    "hypothesisB": "exact_captured_joint_replay_via_animated_local_translation",
    "sharedCamera": "explicit_capture_space_no_per_panel_autofit",
    "seed": BASELINE_SEED,
}

# Skeleton-first envelope: mocap bones plus sprite silhouettes, no Meshy mesh.
BONE_ENVELOPE_SETTINGS = {
    "captureReuse": "saved_raw_capture_npz_no_rerun",
    "donorReference": "zoo:Eagle#Eagle-Landing/y15",
    "bindPose": "tpose_from_unmodified_bvh_offsets_not_landing_frame0",
    "meshTemplate": "none_generated_capsules_and_wing_sheets_on_capture_bones",
    "weightAuthority": "authored_envelope_parent_child_blend_not_meshy_or_unirig",
    "originalSmartRig": "not_an_input",
    "camera": "frozen_orthographic_from_frame0_joints_to_sprite_silhouette",
    "jointSpanToSilhouette": 0.70,
    "radiusAuthority": "median_screen_perpendicular_silhouette_halfwidth",
    "shortOrCoincidentPolicy": "radial_occupancy_around_child_joint",
    "albedo": "flat_clay_not_frame0_sprite_projection",
    "reviewPreview": "unlit_grey_native_aspect_not_sprite_projection",
    "motion": "fixed_length_rotation_only_on_eagle_bind",
    "seed": BASELINE_SEED,
}

# Bone-owned flesh: Voronoi pixel ownership, then an anisotropic volume per bone.
OWNED_FLESH_SETTINGS = {
    "captureReuse": "saved_raw_capture_npz_no_rerun",
    "donorReference": "zoo:Eagle#Eagle-Landing/y15",
    "bindPose": "tpose_from_unmodified_bvh_offsets_not_landing_frame0",
    "meshTemplate": "bind_fuselage_loft_plus_thickened_mocap_wing_tail_sheets",
    "thicknessAuthority": "bind_fuselage_loft_plus_thickened_mocap_wing_tail_sheets",
    "weightAuthority": "parent_child_blend_on_tubes_one_hot_on_sheet_stations",
    "albedo": "source_def_sprite_on_projected_uvs",
    "reviewPreview": "textured_sprite_albedo_native_aspect",
    "hullGrid": 96,
    "volumeSpace": "tpose_bind_skinned_by_capture",
    "originalSmartRig": "not_an_input",
    "camera": "frozen_orthographic_from_frame0_joints_to_sprite_silhouette",
    "jointSpanToSilhouette": 0.70,
    "radiusAuthority": "percentile_of_voronoi_owned_pixel_distance",
    "radiusPercentile": 0.95,
    "radiusPad": 1.05,
    "zeroLengthBones": "excluded_from_ownership_and_nearest",
    "depthRatioByRegion": {
        "torso": 0.55,
        "neck_head": 0.45,
        "beak": 0.40,
        "wing_left": 0.20,
        "wing_right": 0.20,
        "tail": 0.30,
        "leg_left": 0.40,
        "leg_right": 0.40,
    },
    "sheetLift": "not_used_for_hull_volume",
    "depthAuthority": "mocap_joint_positions_define_bone_axes_and_wing_polygons",
    "volumeClip": "none_shape_from_capture_not_view_extrusion",
    "motion": "fixed_length_rotation_only_on_eagle_bind",
    "seed": BASELINE_SEED,
}

# Original visible mesh is invariant. Donor skeleton identities are fitted into it.
SHAPE_PRESERVED_SETTINGS = {
    "captureReuse": "saved_raw_capture_npz_no_rerun",
    "visibleMesh": "original_vertices_topology_uvs_materials_unchanged",
    "coordinateNormalization": "explicit_reversible_similarity_or_none",
    "deformationBind": "donor_joint_identities_fitted_to_target_not_mesh_conformed_to_donor",
    "weightAuthority": "hidden_donor_proxy_barycentric_not_nearest_bone",
    "hiddenProxy": "disposable_transfer_surface_not_exported",
    "motion": "capture_relative_directions_on_fitted_bind_fixed_target_lengths",
    "notExactJointReplay": True,
    "sharedIdleReferenceRequired": True,
    "twistPolicy": "minimum_change_prior_not_captured_evidence",
    "sharedCamera": "explicit_target_bind_space_no_per_panel_autofit",
    "seed": BASELINE_SEED,
    "maxPrepRevisions": 3,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        resolved = Path(path)
        digest.update(str(resolved).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(resolved)))
    return digest.hexdigest()


def vendor_revision() -> str:
    completed = subprocess.run(
        ["git", "-C", str(VENDOR), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    revision = completed.stdout.strip()
    if not revision:
        raise RuntimeError("vendor git revision is empty")
    return revision


def numbered_pngs(frame_dir: Path) -> list[Path]:
    paths = sorted(path for path in frame_dir.glob("*.png") if path.stem.isdigit())
    if not paths:
        raise FileNotFoundError(f"no numbered PNG frames in {frame_dir}")
    return paths


def build_pin(
    *,
    case_key: str,
    mesh: Path,
    frames: Path,
    idle: Path,
    joint_names: Path,
    bind_render: Path | None = None,
) -> dict[str, object]:
    clip_frames = numbered_pngs(frames)
    checkpoint_sha = sha256_file(CHECKPOINT_FILE)
    if checkpoint_sha != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError(
            f"checkpoint sha256 {checkpoint_sha} != pinned {EXPECTED_CHECKPOINT_SHA256}"
        )
    revision = vendor_revision()
    if revision != EXPECTED_VENDOR_REVISION:
        raise ValueError(
            f"vendor revision {revision} != pinned {EXPECTED_VENDOR_REVISION}"
        )
    files = {
        "checkpoint": checkpoint_sha,
        "vendorYaml": sha256_file(VENDOR_INFERENCE_YAML),
        "mesh": sha256_file(mesh),
        "idle": sha256_file(idle),
        "jointNames": sha256_file(joint_names),
        "clipFrames": sha256_files(clip_frames),
    }
    if bind_render is not None:
        files["bindRender"] = sha256_file(bind_render)
    return {
        "case": case_key,
        "vendorRevision": revision,
        "checkpoint": str(CHECKPOINT_FILE).replace("\\", "/"),
        "seed": BASELINE_SEED,
        "settings": dict(LOCKED_SETTINGS),
        "fileSha256": files,
        "clipFrameCount": len(clip_frames),
        "clipFrameNames": [path.name for path in clip_frames],
    }


def write_pin(path: Path, pin: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    return path
