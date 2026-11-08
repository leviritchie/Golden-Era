#!/usr/bin/env python3
"""Shape-preserving preparation: fit the capture rig to the original mesh.

Does not overwrite the original GLB, v1/v2 conformed copies, or saved captures.
Does not rerun inference. Uses one verified idle reference across clips,
not an automatic clip-frame-0 reset.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import numpy as np
from PIL import Image

from asset_profiles import get_profile
from barycentric_transfer import UnmatchedCorrespondenceError
from donor_eagle import bind_world_matrices, compute_rest_joints, inverse_bind_matrices, skin_dense
from eagle_glb import inspect_glb_animation, make_bind_skeleton, matrices_to_xyzw, write_skinned_glb
from eagle_preview import (
    load_gif_frames,
    write_actuation_gif,
    write_bind_sheet,
    write_mesh_gif,
    write_shape_compare_gif,
    write_stage_sheet,
)
from evaluation import EVALUATION_CASES
from fit_deformation_bind import fit_deformation_bind
from hidden_proxy import register_hidden_proxy, vertex_normals
from idle_calibration import load_or_create as load_idle_calibration
from known_motion_fixtures import sine_actuator_local
from mesh_preview import fk_world_matrices
from mocap_preflight import refuse_forbidden_inputs, refuse_holdout_without_freeze
from paths import (
    MOCAP_EAGLE_SKINNED,
    MOCAP_INTERMEDIATE,
    MOCAP_SHAPE_PRESERVED,
    SHAPE_PRESERVED_KEEP_AUTHORITY,
    SOURCE_FRAME_MS,
)
from pin import SHAPE_PRESERVED_SETTINGS, numbered_pngs, sha256_file
from reconstruct_adapted import reconstruct_adapted
from semantic_describe import describe_asset
from shape_donor import donor_rest_joints, load_shape_donor
from shape_gates import (
    assert_visible_mesh_preserved,
    deformation_preview_stats,
    export_reload_gate,
    hidden_donor_absent,
    influence_preservation_gate,
    isolated_deformation_gate,
    preservation_limit,
    rig_gate,
    weight_gate,
)
from shared_camera import freeze_shared_camera
from target_asset import load_target_asset
from verify_calibrated_export import verify_calibrated_export

RESERVED_RUN_NAMES = frozenset({"eagle_skin_v1", "eagle_skin_v2"})
FORBIDDEN_WRITE_ROOTS = (MOCAP_EAGLE_SKINNED,)
CAPTURE_BY_CASE = {
    "roc_flight": MOCAP_INTERMEDIATE / "h3_roc" / "move" / "intermediate_v1_primary" / "capture" / "raw_capture.npz",
    "roc_attack": (
        MOCAP_INTERMEDIATE / "h3_roc" / "idle_attack_front" / "intermediate_v1_primary" / "capture" / "raw_capture.npz"
    ),
}
IDLE_CALIBRATION_VERSION = "idle_reference_v1"
PREV_RETARGET_GIF = {
    "roc_flight": (
        MOCAP_INTERMEDIATE / "h3_roc" / "move" / "intermediate_v1_primary" / "retarget_v3" / "review_retarget_mesh.gif"
    ),
    "roc_attack": (
        MOCAP_INTERMEDIATE
        / "h3_roc"
        / "idle_attack_front"
        / "intermediate_v1_primary"
        / "retarget_v3"
        / "review_retarget_mesh.gif"
    ),
}
V2_AB_GIF = {
    "roc_flight": MOCAP_EAGLE_SKINNED / "ab" / "roc_flight" / "eagle_skin_v2" / "review_ab.gif",
    "roc_attack": MOCAP_EAGLE_SKINNED / "ab" / "roc_attack" / "eagle_skin_v2" / "review_ab.gif",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "describe",
            "stamp-semantic",
            "prepare",
            "actuation",
            "motion",
            "crusader-control",
            "freeze-status",
            "controls",
        ),
    )
    parser.add_argument("case", nargs="?", choices=("roc_flight", "roc_attack"))
    parser.add_argument("--asset", default="h3_roc", choices=("h3_roc", "h3_crusader"))
    parser.add_argument("--run-name", default="shape_preserved_v1")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--semantic-note", default="agent_verified")
    return parser.parse_args()


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return path


def _refuse_existing(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifacts: {path}")


def _refuse_reserved_run(run_name: str) -> None:
    if run_name in RESERVED_RUN_NAMES or run_name.startswith("eagle_skin_"):
        raise ValueError(
            f"{run_name!r} belongs to the historical conform-copy lane; "
            "shape-preserved preparation uses a new --run-name under shape_preserved/"
        )


def _refuse_forbidden_roots(path: Path) -> None:
    resolved = path.resolve()
    for root in FORBIDDEN_WRITE_ROOTS:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        raise ValueError(f"refusing to write {path} under the historical eagle-skinned tree")


def _names(values: Any) -> list[str]:
    out: list[str] = []
    for item in np.asarray(values).tolist():
        out.append(item.decode("utf-8") if isinstance(item, bytes) else str(item))
    return out


def _axis_rotation(axis: int, angle: float) -> np.ndarray:
    cosine = float(np.cos(angle))
    sine = float(np.sin(angle))
    out = np.eye(3, dtype=np.float64)
    a = int(axis)
    b = (a + 1) % 3
    d = (a + 2) % 3
    out[b, b] = cosine
    out[d, d] = cosine
    out[b, d] = -sine
    out[d, b] = sine
    return out


def _bind_root_translation(offsets: np.ndarray) -> np.ndarray:
    return np.asarray(offsets, dtype=np.float64).copy()


def asset_dir(asset_id: str) -> Path:
    return MOCAP_SHAPE_PRESERVED / asset_id


def semantic_path(asset_id: str) -> Path:
    return asset_dir(asset_id) / "semantic_description.json"


def prep_freeze_path(asset_id: str) -> Path:
    return asset_dir(asset_id) / "preparation_frozen.json"


def require_verified_semantic(asset_id: str) -> dict[str, Any]:
    path = semantic_path(asset_id)
    if not path.is_file():
        raise FileNotFoundError(f"semantic description is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("reviewStatus") != "agent_verified":
        raise ValueError(
            f"{path} is not agent_verified (got {payload.get('reviewStatus')!r}); "
            "run describe, have an agent review it once, then stamp-semantic"
        )
    if payload.get("assetId") != asset_id:
        raise ValueError("semantic description assetId does not match")
    return payload


def describe(*, asset: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    profile = get_profile(asset)
    dest = semantic_path(asset)
    _refuse_forbidden_roots(dest)
    if dest.is_file():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        if existing.get("reviewStatus") == "agent_verified":
            return existing
        raise FileExistsError(f"unverified semantic already exists: {dest}")
    payload = describe_asset(profile)
    _write_json(dest, payload)
    return payload


def stamp_semantic(*, asset: str, note: str) -> dict[str, Any]:
    path = semantic_path(asset)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("reviewStatus") == "agent_verified":
        return payload
    payload["reviewStatus"] = "agent_verified"
    payload["verificationNote"] = str(note)
    _write_json(path, payload)
    return payload


def load_saved_capture(path: Path, donor: dict[str, Any]) -> dict[str, Any]:
    raw = np.load(path, allow_pickle=False)
    names = _names(raw["joint_names"])
    if names != list(donor["jointNames"]):
        raise ValueError("saved capture joint names do not match the donor")
    offsets = np.asarray(raw["offsets"], dtype=np.float64)
    if float(np.abs(offsets - donor["bindOffsets"]).max()) > 1e-8:
        raise ValueError("saved capture offsets drifted from the donor bind")
    if "pred_rot6d" in raw.files:
        pass
    return {
        "path": path,
        "pred_position": np.asarray(raw["pred_position"], dtype=np.float64),
        "parents": np.asarray(raw["parents"], dtype=np.int64),
        "offsets": offsets,
        "jointNames": names,
        "sha256": sha256_file(path),
        "usedLearnedRotations": False,
    }


def prepare(*, asset: str, run_name: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    _refuse_reserved_run(run_name)
    profile = get_profile(asset)
    semantic = require_verified_semantic(asset)
    out_dir = asset_dir(asset) / "preparation" / run_name
    _refuse_forbidden_roots(out_dir)
    _refuse_existing(out_dir)
    wall = time.perf_counter()
    target = load_target_asset(profile)
    donor = load_shape_donor(profile)
    names = list(donor["jointNames"])
    parents = np.asarray(donor["bindParents"], dtype=np.int64)
    donor_offsets = np.asarray(donor["bindOffsets"], dtype=np.float64)
    donor_rest = donor_rest_joints(donor)
    fit = fit_deformation_bind(
        donor_names=names,
        donor_parents=parents,
        donor_rest=donor_rest,
        target_names=target["names"],
        target_rest=target["restWorld"],
        target_vertices=target["vertices"],
        target_regions=target["vertexRegions"],
        profile=profile,
    )
    rig = rig_gate(
        names=names,
        parents=parents,
        fitted=fit["fittedPositions"],
        offsets=fit["offsets"],
        profile=profile,
        helpers=fit["helpers"],
    )
    try:
        proxy = register_hidden_proxy(
            donor_vertices=donor["meshVertices"],
            donor_faces=donor["meshFaces"],
            donor_weights=donor["meshWeights"],
            donor_names=names,
            donor_offsets=donor_offsets,
            donor_parents=parents,
            fitted_offsets=fit["offsets"],
            target_vertices=target["vertices"],
            target_faces=target["triangles"],
            target_regions=target["vertexRegions"],
            region_joints=profile["regionJoints"],
            profile=profile,
        )
    except UnmatchedCorrespondenceError as exc:
        raise ValueError(
            "hidden-proxy transfer refused; correspondence must be refined or reported. "
            f"unmatched={exc.unmatched[:8]}"
        ) from exc
    weights = proxy["weights"]
    weight_gate(weights, len(target["vertices"]), len(names))
    influence_preservation_gate(donor["meshWeights"], weights, names, fit["helpers"])
    preserve = assert_visible_mesh_preserved(
        target,
        target["vertices"],
        target["triangles"],
        target["uvs"],
        target["albedo"],
    )
    fitted_bind = bind_world_matrices(fit["offsets"], parents)
    ibm = inverse_bind_matrices(fitted_bind)
    identity = skin_dense(target["vertices"], weights, fitted_bind, ibm)
    identity_err = float(np.linalg.norm(identity - target["vertices"], axis=1).max())
    gate = preserve["gate"]
    if identity_err > gate:
        raise ValueError(f"new skin is not identity in the fitted bind: max {identity_err} > {gate}")
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(names), axis=0)
    rest_off = _bind_root_translation(fit["offsets"])
    rest = compute_rest_joints(fit["offsets"], parents)
    working = make_bind_skeleton(
        names=names,
        parents=parents,
        rest_world=rest,
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=ibm,
        vertices=target["vertices"],
        triangles=target["triangles"],
        uvs=target["uvs"],
        weights=weights,
        albedo=target["albedo"],
        normals=vertex_normals(target["vertices"], target["triangles"]),
    )
    out_dir.mkdir(parents=True)
    glb_path = out_dir / f"{asset}_shape_preserved.glb"
    write_skinned_glb(
        glb_path,
        names=names,
        parents=parents,
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=ibm,
        vertices=target["vertices"],
        triangles=target["triangles"],
        uvs=target["uvs"],
        albedo=target["albedo"],
        weights=weights,
    )
    export = export_reload_gate(glb_path, working=working, original_vertices=target["vertices"])
    hidden = hidden_donor_absent(glb_path, len(target["vertices"]))
    cameras = freeze_shared_camera(
        np.concatenate([target["vertices"], rest, proxy["hiddenVertices"]]),
        width=256,
        height=256,
        space="targetBindSpace",
    )
    write_stage_sheet(
        out_dir / "geometry_stages.png",
        cameras=cameras,
        stages=[("1 original", target["vertices"]), ("2 bind-skinned", identity)],
        triangles=target["triangles"],
        uvs=target["uvs"],
        albedo=target["albedo"],
        joints=rest,
        parents=parents,
        title="shape preserved: original vs bind-skinned",
    )
    write_bind_sheet(
        out_dir / "bind_sheet.png",
        cameras=cameras,
        vertices=identity,
        triangles=target["triangles"],
        uvs=target["uvs"],
        albedo=target["albedo"],
        joints=rest,
        parents=parents,
        title=f"{asset} original mesh + fitted capture bind",
    )
    dummy = np.full((4, 4, 4), 180, dtype=np.uint8)
    dummy[..., 3] = 255
    proxy_uvs = np.zeros((len(proxy["hiddenVertices"]), 2), dtype=np.float64)
    write_bind_sheet(
        out_dir / "hidden_proxy_sheet.png",
        cameras=cameras,
        vertices=proxy["hiddenVertices"],
        triangles=donor["meshFaces"],
        uvs=proxy_uvs,
        albedo=dummy,
        joints=rest,
        parents=parents,
        title="hidden donor proxy (not exported)",
    )
    np.savez(
        out_dir / "research_skin.npz",
        vertices=target["vertices"],
        triangles=target["triangles"],
        uvs=target["uvs"],
        weights=weights,
        names=np.asarray(names),
        parents=parents,
        offsets=fit["offsets"],
        captureOffsets=donor_offsets,
        inverseBind=ibm,
        regions=np.asarray(target["vertexRegions"]).astype("U32"),
        albedo=target["albedo"],
        originalVertices=target["vertices"],
        hiddenProxy=proxy["hiddenVertices"],
        fittedPositions=fit["fittedPositions"],
    )
    _write_json(
        out_dir / "deformation_bind.json",
        {
            "names": names,
            "parents": parents,
            "offsets": fit["offsets"],
            "fittedPositions": fit["fittedPositions"],
            "helpers": fit["helpers"],
            "limitations": fit["limitations"],
            "spaces": fit["spaces"],
        },
    )
    _write_json(
        out_dir / "correspondence.json",
        {
            "semantic": semantic_path(asset).as_posix(),
            "notes": fit["notes"],
            "proxyRevisions": proxy["revisions"],
            "rigidVertexCount": proxy["rigidVertexCount"],
        },
    )
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "visualAcceptance": "unreviewed_candidate",
        "keepAuthority": SHAPE_PRESERVED_KEEP_AUTHORITY,
        "assetId": asset,
        "runName": run_name,
        "settings": dict(SHAPE_PRESERVED_SETTINGS),
        "inputHashes": {
            "originalMesh": target["sourceSha256"],
            **{f"donor.{key}": value for key, value in donor["fileSha256"].items()},
            "semantic": sha256_file(semantic_path(asset)),
        },
        "preservation": preserve,
        "rig": rig,
        "export": export,
        "hiddenDonor": hidden,
        "bindIdentityMax": identity_err,
        "proxyRevisions": proxy["revisions"],
        "helpers": fit["helpers"],
        "limitations": fit["limitations"],
        "spaces": donor["spaces"],
        "sharedIdleReferenceRequired": True,
        "notExactJointReplay": True,
        "prepareSeconds": float(time.perf_counter() - wall),
        "paths": {
            "glb": glb_path.as_posix(),
            "researchSkin": (out_dir / "research_skin.npz").as_posix(),
            "bindSheet": (out_dir / "bind_sheet.png").as_posix(),
        },
        "inspect": inspect_glb_animation(glb_path),
        "semanticReview": semantic["reviewStatus"],
    }
    _write_json(out_dir / "prepare_report.json", payload)
    freeze = {
        "assetId": asset,
        "runName": run_name,
        "preparationDir": out_dir.as_posix(),
        "glb": glb_path.as_posix(),
        "researchSkin": (out_dir / "research_skin.npz").as_posix(),
        "inputHashes": payload["inputHashes"],
        "settings": dict(SHAPE_PRESERVED_SETTINGS),
        "keepAuthority": SHAPE_PRESERVED_KEEP_AUTHORITY,
    }
    freeze_path = prep_freeze_path(asset)
    if freeze_path.is_file():
        existing = json.loads(freeze_path.read_text(encoding="utf-8"))
        if existing.get("preparationDir") != freeze["preparationDir"]:
            raise FileExistsError(f"preparation already frozen at {freeze_path}")
    else:
        _write_json(freeze_path, freeze)
    verify_original_untouched(asset, target["sourceSha256"])
    return payload


def verify_original_untouched(asset: str, expected: str) -> None:
    current = sha256_file(get_profile(asset)["mesh"])
    if current != expected:
        raise ValueError("original visible mesh hash changed; this experiment must not touch it")


def _load_frozen_prep(asset: str) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze_path = prep_freeze_path(asset)
    if not freeze_path.is_file():
        raise FileNotFoundError(f"preparation is not frozen: {freeze_path}")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    from structured_profiles import require_profile_pin
    require_profile_pin(asset, freeze)
    verify_original_untouched(asset, freeze["inputHashes"]["originalMesh"])
    if freeze.get("skinInitialization") == "mounted_capsule_owned":
        manifest_path = Path(freeze["authoringManifest"])
        if sha256_file(manifest_path) != freeze["inputHashes"]["manifest"]:
            raise ValueError("mounted authoring manifest changed")
        manifest = json.loads(manifest_path.read_text())
        if manifest["assetId"] != asset or sha256_file(Path(manifest["authorProfile"])) != manifest["authorProfileHash"]:
            raise ValueError("mounted authoring profile changed")
        if sha256_file(Path(freeze["researchSkin"])) != freeze["inputHashes"]["researchSkin"]:
            raise ValueError("mounted research skin changed")
    if freeze.get("skinInitialization") == "source_joint_map":
        from prepare_mapped_skin_asset import _profile_hash
        if freeze["inputHashes"].get("profile") != _profile_hash(get_profile(asset)):
            raise ValueError("mapped preparation profile changed or was not provenance-pinned")
        if freeze["inputHashes"].get("researchSkin") != sha256_file(Path(freeze["researchSkin"])):
            raise ValueError("mapped preparation skin changed or was not provenance-pinned")
    skin = np.load(freeze["researchSkin"], allow_pickle=False)
    ownership_profile = get_profile(asset)
    ownership_arrays = {}
    if "geometryOwnership" in ownership_profile:
        from geometry_ownership import validate_prepared_ownership
        validate_prepared_ownership(ownership_profile, skin)
        ownership_arrays = {key: np.asarray(skin[key]) for key in ("sourceVertexIds", "ownershipBoundaryPairs")}
    return freeze, {
        **ownership_arrays,
        "vertices": np.asarray(skin["vertices"], dtype=np.float64),
        "triangles": np.asarray(skin["triangles"], dtype=np.int64),
        "uvs": np.asarray(skin["uvs"], dtype=np.float64),
        "weights": np.asarray(skin["weights"], dtype=np.float64),
        "names": _names(skin["names"]),
        "parents": np.asarray(skin["parents"], dtype=np.int64),
        "offsets": np.asarray(skin["offsets"], dtype=np.float64),
        "captureOffsets": np.asarray(skin["captureOffsets"], dtype=np.float64),
        "inverseBind": np.asarray(skin["inverseBind"], dtype=np.float64),
        "regions": np.asarray(skin["regions"]).astype(object),
        "albedo": np.asarray(skin["albedo"]),
    }


def actuation(*, asset: str, run_name: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    _refuse_reserved_run(run_name)
    profile = get_profile(asset)
    freeze, skin = _load_frozen_prep(asset)
    out_dir = asset_dir(asset) / "actuation" / run_name
    _refuse_forbidden_roots(out_dir)
    _refuse_existing(out_dir)
    names = skin["names"]
    name_index = {name: index for index, name in enumerate(names)}
    parents = skin["parents"]
    rest_off = skin["offsets"].copy()
    rest_off[0] = 0.0
    rest = compute_rest_joints(skin["offsets"], parents)
    bind = bind_world_matrices(skin["offsets"], parents)
    rest_verts = skin_dense(skin["vertices"], skin["weights"], bind, skin["inverseBind"])
    posed_sets = {}
    isolation = {}
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(names), axis=0)
    for label, joint, region, opposite in profile["actuation"]:
        local = rest_local.copy()
        local[name_index[joint]] = _axis_rotation(2, 0.6)
        world = fk_world_matrices(
            local_rotation=local,
            local_translation=rest_off,
            parents=parents,
            root_world=rest[0],
        )
        posed = skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"])
        posed_sets[label] = posed
        disp = np.linalg.norm(posed - rest_verts, axis=1)
        self_med = float(np.median(disp[skin["regions"] == region]))
        other_med = float(np.median(disp[skin["regions"] == opposite]))
        isolation[label] = {
            "joint": joint,
            "regionMedian": self_med,
            "oppositeMedian": other_med,
            "isolated": bool(self_med > 1e-4 and other_med <= 0.5 * self_med),
            "deformation": deformation_preview_stats(rest_verts, posed, skin["triangles"]),
        }
        if not isolation[label]["isolated"]:
            raise ValueError(f"actuation {label} moved the opposite region too much: {isolation[label]}")
    cameras = freeze_shared_camera(np.concatenate([rest_verts, rest]), width=256, height=256, space="targetBindSpace")
    out_dir.mkdir(parents=True)
    gif = write_actuation_gif(
        out_dir / "actuation.gif",
        cameras=cameras,
        rest_vertices=rest_verts,
        posed_sets=posed_sets,
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
    )
    isolated_deformation_gate(isolation)
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "assetId": asset,
        "runName": run_name,
        "preparationDir": freeze["preparationDir"],
        "isolation": isolation,
        "gif": gif.as_posix(),
    }
    _write_json(out_dir / "actuation_report.json", payload)
    return payload


def run_motion(case_key: str, *, run_name: str, allow_holdout: bool) -> dict[str, Any]:
    refuse_forbidden_inputs()
    _refuse_reserved_run(run_name)
    case = EVALUATION_CASES[case_key]
    refuse_holdout_without_freeze(case, allow_holdout=allow_holdout)
    freeze, skin = _load_frozen_prep("h3_roc")
    out_dir = asset_dir("h3_roc") / "motion" / case_key / run_name
    _refuse_forbidden_roots(out_dir)
    _refuse_existing(out_dir)
    wall = time.perf_counter()
    donor = load_shape_donor(get_profile("h3_roc"))
    capture = load_saved_capture(CAPTURE_BY_CASE[case_key], donor)
    profile = get_profile("h3_roc")
    # Calibrate once from the attack's captured frame 0, whose source sprite is
    # verified against the standalone idle. This is shared by every Roc clip;
    # flight is deliberately not reset to this pose.
    idle_calibration = load_idle_calibration(
        calibration_path=asset_dir("h3_roc") / "calibration" / f"{IDLE_CALIBRATION_VERSION}.json",
        capture_path=CAPTURE_BY_CASE["roc_attack"],
        reference_png=numbered_pngs(EVALUATION_CASES["roc_attack"].frames)[0],
        known_idle_png=EVALUATION_CASES["roc_attack"].idle,
        research_skin=Path(freeze["researchSkin"]),
        capture_positions=load_saved_capture(CAPTURE_BY_CASE["roc_attack"], donor)["pred_position"],
        names=skin["names"],
        parents=skin["parents"],
    )
    reconstruct_started = time.perf_counter()
    adapted = reconstruct_adapted(
        capture_positions=capture["pred_position"],
        capture_reference_positions=idle_calibration["referencePositions"],
        capture_offsets=skin["captureOffsets"],
        fitted_offsets=skin["offsets"],
        parents=skin["parents"],
        names=skin["names"],
        hub_names=tuple(profile["wholeBodyHubs"]),
    )
    reconstruct_sec = time.perf_counter() - reconstruct_started
    idle_probe = reconstruct_adapted(
        capture_positions=idle_calibration["referencePositions"][None, ...],
        capture_reference_positions=idle_calibration["referencePositions"],
        capture_offsets=skin["captureOffsets"],
        fitted_offsets=skin["offsets"],
        parents=skin["parents"],
        names=skin["names"],
        hub_names=tuple(profile["wholeBodyHubs"]),
    )
    capture_root_delta = float(np.linalg.norm(capture["pred_position"][:, 0] - idle_calibration["referencePositions"][0], axis=1).max())
    if capture_root_delta > 1e-8:
        raise ValueError(
            "capture root translation differs from shared idle reference; "
            "translated captures are unsupported in this rotation-only export lane"
        )
    idle_mesh = skin_dense(skin["vertices"], skin["weights"], idle_probe["jointWorld"][0], skin["inverseBind"])
    idle_identity_max = float(np.linalg.norm(idle_mesh - skin["vertices"], axis=1).max())
    if idle_identity_max > preservation_limit(skin["vertices"]):
        raise ValueError(f"calibrated idle does not preserve the visible mesh: max vertex error {idle_identity_max}")
    if adapted["captureFrame0DirectionFromReferenceMaxRad"] > 1e-3 and adapted["clipFrame0IsBind"]:
        raise ValueError("clip frame 0 reconstructed as identity bind; capture-relative posture was lost")
    meshes = [skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"]) for world in adapted["jointWorld"]]
    rest_verts = skin["vertices"]
    distortion = [deformation_preview_stats(rest_verts, frame, skin["triangles"]) for frame in meshes]
    cameras = freeze_shared_camera(
        np.concatenate([rest_verts, adapted["mappedCapture"].reshape(-1, 3), adapted["positions"].reshape(-1, 3)]),
        width=256,
        height=256,
        space="targetBindSpace",
    )
    sprites = [Image.open(path) for path in numbered_pngs(case.frames)]
    previous = load_gif_frames(PREV_RETARGET_GIF[case_key]) if PREV_RETARGET_GIF[case_key].is_file() else None
    v2 = load_gif_frames(V2_AB_GIF[case_key]) if V2_AB_GIF[case_key].is_file() else None
    out_dir.mkdir(parents=True)
    render_started = time.perf_counter()
    gif = write_shape_compare_gif(
        out_dir / "review_shape_preserved.gif",
        cameras=cameras,
        sprites=sprites,
        previous_retarget=previous,
        v2_frames=v2,
        capture=adapted["mappedCapture"],
        joints=adapted["positions"],
        parents=skin["parents"],
        meshes=meshes,
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
        title=f"{case_key} shape-preserved adapted motion",
    )
    render_sec = time.perf_counter() - render_started
    times = np.arange(len(adapted["localRotation"]), dtype=np.float32) * float(SOURCE_FRAME_MS) / 1000.0
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(skin["names"]), axis=0)
    rest_off = _bind_root_translation(skin["offsets"])
    glb_path = out_dir / f"{case_key}_adapted.glb"
    write_skinned_glb(
        glb_path,
        names=skin["names"],
        parents=skin["parents"],
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=skin["inverseBind"],
        vertices=skin["vertices"],
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
        weights=skin["weights"],
        animation={
            "name": "adapted_capture_relative",
            "times": times,
            "rotations": matrices_to_xyzw(adapted["localRotation"]),
        },
    )
    inspect = inspect_glb_animation(glb_path)
    if inspect["translationChannels"]:
        raise ValueError("adapted motion exported translation channels; that is exact-joint B, which this lane must not do")
    export_parity = verify_calibrated_export(
        glb_path, expected_meshes=np.asarray(meshes), expected_times=times,
        idle_frame=0 if adapted["clipFrame0IsBind"] else None,
        tolerance=preservation_limit(skin["vertices"]),
    )
    clip_sec = float(time.perf_counter() - wall)
    if clip_sec > 600.0:
        raise ValueError(f"clip reconstruct+GIF exceeded 600s: {clip_sec}")
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "visualAcceptance": "unreviewed_candidate",
        "case": case_key,
        "runName": run_name,
        "notExactJointReplay": True,
        "clipFrame0IsBind": adapted["clipFrame0IsBind"],
        "residualVsMappedCaptureMax": adapted["residualVsMappedCaptureMax"],
        "residualVsMappedCaptureMean": adapted["residualVsMappedCaptureMean"],
        "fixedLengthErrorMax": adapted["fixedLengthErrorMax"],
        "angularVsCaptureMeanRad": adapted["angularVsCaptureMeanRad"],
        "motionPreservation": adapted.get("motionPreservation"),
        "usedWorldDirectionMatching": adapted.get("usedWorldDirectionMatching"),
        "unobservableDirectionJoints": adapted["unobservableDirectionJoints"],
        "proportionDifferenceNotOverlap": True,
        "historicalExactJointB": "unchanged_under_eagle_skinned_roc_ab",
        "captureSha256": capture["sha256"],
        "idleCalibration": {
            "schema": IDLE_CALIBRATION_VERSION,
            "path": idle_calibration["path"].as_posix(),
            "sha256": idle_calibration["hash"],
            "idleIdentityVertexMax": idle_identity_max,
            "captureRootDeltaMax": capture_root_delta,
        },
        "reconstructSeconds": reconstruct_sec,
        "renderSeconds": render_sec,
        "clipSeconds": clip_sec,
        "distortion": distortion,
        "gif": gif.as_posix(),
        "glb": glb_path.as_posix(),
        "inspect": inspect,
        "serializedAnimationParity": export_parity,
        "usedLearnedRotations": False,
    }
    _write_json(out_dir / "motion_report.json", payload)
    return payload


def crusader_control(*, run_name: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    _refuse_reserved_run(run_name)
    if not prep_freeze_path("h3_crusader").is_file():
        prepare(asset="h3_crusader", run_name=run_name)
    freeze, skin = _load_frozen_prep("h3_crusader")
    out_dir = asset_dir("h3_crusader") / "synthetic" / run_name
    _refuse_forbidden_roots(out_dir)
    _refuse_existing(out_dir)
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(skin["names"]), axis=0)
    rest_off = _bind_root_translation(skin["offsets"])
    working = make_bind_skeleton(
        names=skin["names"],
        parents=skin["parents"],
        rest_world=compute_rest_joints(skin["offsets"], skin["parents"]),
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=skin["inverseBind"],
        vertices=skin["vertices"],
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        weights=skin["weights"],
        albedo=skin["albedo"],
    )
    local = sine_actuator_local(working, frames=8, amplitude=0.7)
    rest = compute_rest_joints(skin["offsets"], skin["parents"])
    fk_off = skin["offsets"].copy()
    fk_off[0] = 0.0
    meshes = []
    for frame in local:
        world = fk_world_matrices(
            local_rotation=frame,
            local_translation=fk_off,
            parents=skin["parents"],
            root_world=rest[0],
        )
        meshes.append(skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"]))
    travel = float(np.linalg.norm(meshes[2] - skin["vertices"], axis=1).max())
    if travel < 1e-3:
        raise ValueError("crusader synthetic actuation did not move the mesh")
    cameras = freeze_shared_camera(
        np.concatenate([skin["vertices"], rest, *meshes]),
        width=256,
        height=256,
        space="targetBindSpace",
    )
    out_dir.mkdir(parents=True)
    gif = write_mesh_gif(
        out_dir / "synthetic_skin.gif",
        cameras=cameras,
        meshes=meshes,
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
        title="crusader synthetic skinning control",
    )
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "assetId": "h3_crusader",
        "notCrusaderMocapRecovery": True,
        "syntheticMotionOnly": True,
        "samePreparationCode": True,
        "vertexTravelMax": travel,
        "gif": gif.as_posix(),
        "preparationDir": freeze["preparationDir"],
        "reuseGate": "metadata_and_review_not_new_solver_branches",
    }
    _write_json(out_dir / "crusader_control_report.json", payload)
    return payload


def freeze_status() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for asset in ("h3_roc", "h3_crusader"):
        path = prep_freeze_path(asset)
        semantic = semantic_path(asset)
        payload[asset] = {
            "semantic": json.loads(semantic.read_text(encoding="utf-8")) if semantic.is_file() else None,
            "preparationFrozen": path.is_file(),
            "preparation": json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None,
        }
    return payload


def run_controls() -> dict[str, Any]:
    refuse_forbidden_inputs()
    suite = unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_shape_preserved.py")
    suite.addTests(unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_idle_calibration.py"))
    suite.addTests(unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_calibrated_export.py"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("shape-preserved control tests failed")
    return {"ok": True, "testsRun": result.testsRun}


def main() -> int:
    args = parse_args()
    if args.command == "describe":
        payload = describe(asset=args.asset)
    elif args.command == "stamp-semantic":
        payload = stamp_semantic(asset=args.asset, note=args.semantic_note)
    elif args.command == "prepare":
        payload = prepare(asset=args.asset, run_name=args.run_name)
    elif args.command == "actuation":
        payload = actuation(asset=args.asset, run_name=args.run_name)
    elif args.command == "motion":
        if not args.case:
            raise ValueError("motion requires roc_flight or roc_attack")
        payload = run_motion(args.case, run_name=args.run_name, allow_holdout=args.allow_holdout)
    elif args.command == "crusader-control":
        payload = crusader_control(run_name=args.run_name)
    elif args.command == "freeze-status":
        payload = freeze_status()
    elif args.command == "controls":
        payload = run_controls()
    else:
        raise ValueError(args.command)
    print(json.dumps(payload, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
