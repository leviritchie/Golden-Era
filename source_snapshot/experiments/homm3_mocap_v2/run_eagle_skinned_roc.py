#!/usr/bin/env python3
"""Roc copy skinned to the Eagle capture skeleton. A/B on saved captures only.

Does not overwrite the original Roc GLB, previous captures, or retarget results.
Does not rerun inference. Does not use learned pred_rot6d as a fallback.
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

from barycentric_transfer import UnmatchedCorrespondenceError, transfer_weights
from conform_roc import ConformFailed, align_roc_global_to_eagle, conform_roc_to_eagle, triangle_distortion
from donor_eagle import (
    EAGLE_REF_SEQ,
    bind_world_matrices,
    compute_rest_joints,
    inverse_bind_matrices,
    load_donor_package,
    obj_vertex_uvs,
    quat_wxyz_to_matrix,
    skin_dense,
    verify_donor_contract,
)
from eagle_glb import inspect_glb_animation, make_bind_skeleton, matrices_to_xyzw, reload_and_compare, write_skinned_glb
from eagle_preview import load_gif_frames, write_actuation_gif, write_bind_sheet, write_mesh_gif, write_overlay_gif, write_stage_sheet
from evaluation import EVALUATION_CASES
from mesh_preview import fk_world_matrices
from mocap_preflight import refuse_forbidden_inputs, refuse_holdout_without_freeze
from paths import EAGLE_SKINNED_KEEP_AUTHORITY, MESHY, MOCAP_EAGLE_SKINNED, MOCAP_INTERMEDIATE, SOURCE_FRAME_MS
from pin import EAGLE_SKINNED_SETTINGS, numbered_pngs, sha256_file
from reconstruct_ab import reconstruct_ab
from roc_copy import ROC_TO_EAGLE_LANDMARKS, duplicate_roc
from shared_camera import freeze_shared_camera

ORIGINAL_ROC = MESHY / "h3_roc_smartrigged.glb"
CAPTURE_BY_CASE = {
    "roc_flight": MOCAP_INTERMEDIATE / "h3_roc" / "move" / "intermediate_v1_primary" / "capture" / "raw_capture.npz",
    "roc_attack": (
        MOCAP_INTERMEDIATE / "h3_roc" / "idle_attack_front" / "intermediate_v1_primary" / "capture" / "raw_capture.npz"
    ),
}
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
PREP_FREEZE = MOCAP_EAGLE_SKINNED / "preparation_frozen.json"
AB_FREEZE = MOCAP_EAGLE_SKINNED / "ab_settings_frozen.json"
FAILED_PREP_MARKER = "FAILED_CANDIDATE.json"
FAILED_PREP_NAME = "eagle_skin_v1"
ACTUATION_JOINTS = (
    ("shoulder_L", "BN_Wing_L_01", "wing_left", "wing_right"),
    ("midwing_L", "BN_Wing_L_03", "wing_left", "wing_right"),
    ("neck", "Bip01_Neck", "neck_head", "wing_right"),
    ("tail", "BN_Tai_01", "tail", "wing_left"),
    ("leg_L", "Bip01_L_Thigh", "leg_left", "leg_right"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("donor-verify", "prepare", "actuation", "ab", "freeze-status", "controls"))
    parser.add_argument("case", nargs="?", choices=("roc_flight", "roc_attack"))
    parser.add_argument("--run-name", default="eagle_skin_v2")
    parser.add_argument("--allow-holdout", action="store_true")
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


def _failed_prep_dir(path: Path) -> bool:
    return (path / FAILED_PREP_MARKER).is_file()


def _archive_if_failed_freeze(freeze_path: Path, archive_name: str) -> None:
    if not freeze_path.is_file():
        return
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    prep_dir = Path(payload.get("preparationDir", ""))
    if not _failed_prep_dir(prep_dir):
        return
    archive = MOCAP_EAGLE_SKINNED / archive_name
    if not archive.is_file():
        archive.write_text(freeze_path.read_text(encoding="utf-8"), encoding="utf-8")
    freeze_path.unlink()


def _bind_root_translation(offsets: np.ndarray) -> np.ndarray:
    """glTF root translation is the bind-pose world origin, not the zeroed in-memory FK offset."""
    return np.asarray(offsets, dtype=np.float64).copy()


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


def load_saved_capture(path: Path, donor: dict[str, Any]) -> dict[str, Any]:
    raw = np.load(path, allow_pickle=False)
    names = _names(raw["joint_names"])
    if names != list(donor["captureSkeleton"]["jointNames"]):
        raise ValueError("saved capture joint names do not match the Eagle donor")
    offsets = np.asarray(raw["offsets"], dtype=np.float64)
    if float(np.abs(offsets - donor["captureSkeleton"]["offsets"]).max()) > 1e-8:
        raise ValueError("saved capture offsets drifted from the Eagle donor")
    if "pred_rot6d" in raw.files:
        # Present for diagnosis only. Replay never reads it.
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


def input_hashes(donor: dict[str, Any]) -> dict[str, str]:
    return {
        "originalRoc": sha256_file(ORIGINAL_ROC),
        **{f"donor.{key}": value for key, value in donor["fileSha256"].items()},
    }


def verify_original_untouched(expected: str) -> None:
    current = sha256_file(ORIGINAL_ROC)
    if current != expected:
        raise ValueError("original Roc GLB hash changed; this experiment must not touch it")


def freeze_status() -> dict[str, Any]:
    prep = PREP_FREEZE.is_file()
    motion = AB_FREEZE.is_file()
    payload: dict[str, Any] = {"preparationFrozen": prep, "abFrozen": motion}
    if prep:
        payload["preparation"] = json.loads(PREP_FREEZE.read_text(encoding="utf-8"))
    if motion:
        payload["ab"] = json.loads(AB_FREEZE.read_text(encoding="utf-8"))
    return payload


def run_controls() -> dict[str, Any]:
    refuse_forbidden_inputs()
    suite = unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_donor_eagle.py")
    suite.addTests(unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_reconstruct_ab.py"))
    suite.addTests(unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_eagle_skinned_roc.py"))
    suite.addTests(unittest.defaultTestLoader.discover(str(EXPERIMENT), pattern="test_conform_roc.py"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("eagle-skinned Roc control tests failed")
    return {"ok": True, "testsRun": result.testsRun}


def donor_verify() -> dict[str, Any]:
    refuse_forbidden_inputs()
    out_dir = MOCAP_EAGLE_SKINNED / "donor_verify"
    _refuse_existing(out_dir / "donor_contract.json")
    report = verify_donor_contract()
    donor = load_donor_package()
    names = donor["captureSkeleton"]["jointNames"]
    parents = donor["captureSkeleton"]["parents"]
    offsets = donor["captureSkeleton"]["offsets"]
    rest = compute_rest_joints(offsets, parents)
    bind = bind_world_matrices(offsets, parents)
    ibm = inverse_bind_matrices(bind)
    obj_v = donor["obj"]["vertices"]
    faces = donor["obj"]["faces"]
    uvs = obj_vertex_uvs(donor["obj"])
    albedo = np.asarray(Image.open(donor["texturePath"]).convert("RGBA"))
    bind_cameras = freeze_shared_camera(np.concatenate([obj_v, rest]), width=256, height=256)
    bind_verts = skin_dense(obj_v, donor["weights"], bind, ibm)
    write_bind_sheet(
        out_dir / "donor_bind_sheet.png",
        cameras=bind_cameras,
        vertices=bind_verts,
        triangles=faces,
        uvs=uvs,
        albedo=albedo,
        joints=rest,
        parents=parents,
        title="Eagle donor bind (OBJ + offset T-pose)",
    )
    anim = donor["package"]["anim"]
    local = quat_wxyz_to_matrix(np.asarray(anim.rotations, dtype=np.float64))
    local_t = offsets.copy()
    local_t[0] = 0.0
    trans = np.asarray(anim.positions, dtype=np.float64)[:, 0] - offsets[0]
    sample = list(range(0, len(local), max(1, len(local) // 12)))[:12]
    posed = []
    for frame in sample:
        world = fk_world_matrices(
            local_rotation=local[frame],
            local_translation=local_t,
            parents=parents,
            root_world=rest[0] + trans[frame],
        )
        posed.append(skin_dense(obj_v, donor["weights"], world, ibm))
    motion_cameras = freeze_shared_camera(np.concatenate([bind_verts, *posed]), width=256, height=256)
    write_mesh_gif(
        out_dir / "donor_known_motion.gif",
        cameras=motion_cameras,
        meshes=posed,
        triangles=faces,
        uvs=uvs,
        albedo=albedo,
        title="donor landing",
    )
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "refSeq": EAGLE_REF_SEQ,
        "keepAuthority": EAGLE_SKINNED_KEEP_AUTHORITY,
        "contract": report,
        "inputHashes": input_hashes(donor),
        "gifs": {
            "bindSheet": str((out_dir / "donor_bind_sheet.png").as_posix()),
            "knownMotion": str((out_dir / "donor_known_motion.gif").as_posix()),
        },
        "settings": dict(EAGLE_SKINNED_SETTINGS),
    }
    _write_json(out_dir / "donor_contract.json", payload)
    return payload


def prepare(*, run_name: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    if run_name == FAILED_PREP_NAME:
        raise ValueError(
            f"{FAILED_PREP_NAME} is a failed preparation candidate; restart from the original Roc with a new --run-name"
        )
    out_dir = MOCAP_EAGLE_SKINNED / "preparation" / run_name
    _refuse_existing(out_dir)
    donor = load_donor_package()
    hashes = input_hashes(donor)
    copy = duplicate_roc(ORIGINAL_ROC)
    if copy["sourceSha256"] != hashes["originalRoc"]:
        raise ValueError("duplicate_roc hashed a different file than the original Roc")
    return prepare_from_copy(copy, out_dir, hashes=hashes, freeze_global=True)


def prepare_from_copy(
    copy: dict[str, Any],
    out_dir: Path,
    *,
    hashes: dict[str, str],
    freeze_global: bool,
    conform_mode: str = "articulated",
) -> dict[str, Any]:
    refuse_forbidden_inputs()
    wall = time.perf_counter()
    donor = load_donor_package()
    names = donor["captureSkeleton"]["jointNames"]
    parents = np.asarray(donor["captureSkeleton"]["parents"], dtype=np.int64)
    offsets = np.asarray(donor["captureSkeleton"]["offsets"], dtype=np.float64)
    if conform_mode == "articulated":
        try:
            conf = conform_roc_to_eagle(
                copy,
                eagle_offsets=offsets,
                eagle_parents=parents,
                eagle_names=names,
            )
        except ConformFailed:
            raise
        if not conf["diagnostics"]["ok"]:
            raise ValueError(f"conformation diagnostics are not ok: {conf['diagnostics']}")
    elif conform_mode == "global_similarity_only":
        conf = align_roc_global_to_eagle(
            copy,
            eagle_offsets=offsets,
            eagle_parents=parents,
            eagle_names=names,
        )
    else:
        raise ValueError(f"unsupported conform_mode={conform_mode!r}")
    try:
        xfer = transfer_weights(
            roc_vertices=conf["vertices"],
            roc_regions=copy["vertexRegions"],
            donor_vertices=donor["obj"]["vertices"],
            donor_faces=donor["obj"]["faces"],
            donor_weights=donor["weights"],
            donor_names=names,
        )
    except UnmatchedCorrespondenceError as exc:
        raise ValueError(
            "weight transfer refused after a clean geometry gate; "
            f"unmatched={exc.unmatched[:8]}"
        ) from exc
    rest = compute_rest_joints(offsets, parents)
    bind = bind_world_matrices(offsets, parents)
    ibm = inverse_bind_matrices(bind)
    verts = conf["vertices"]
    identity = skin_dense(verts, xfer["weights"], bind, ibm)
    identity_err = float(np.linalg.norm(identity - verts, axis=1).max())
    if identity_err > 1e-5:
        raise ValueError(f"new skin is not identity in bind: max {identity_err}")
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(names), axis=0)
    rest_off = _bind_root_translation(offsets)
    normals = _vertex_normals(verts, copy["triangles"])
    failed_npz = MOCAP_EAGLE_SKINNED / "preparation" / FAILED_PREP_NAME / "research_skin.npz"
    failed_verts = np.asarray(np.load(failed_npz)["vertices"], dtype=np.float64) if failed_npz.is_file() else None
    camera_points = [copy["vertices"], conf["globallyAligned"], verts, rest, donor["obj"]["vertices"]]
    if failed_verts is not None:
        camera_points.append(failed_verts)
    cameras = freeze_shared_camera(np.concatenate(camera_points), width=256, height=256)
    out_dir.mkdir(parents=True, exist_ok=True)
    stages = [
        ("1 original", copy["vertices"]),
        ("2 globally aligned", conf["globallyAligned"]),
        ("3 conformed unskinned", verts),
        ("4 bind-skinned", identity),
    ]
    write_stage_sheet(
        out_dir / "geometry_stages.png",
        cameras=cameras,
        stages=stages,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        albedo=copy["albedo"],
        joints=rest,
        parents=parents,
        title="geometry gate: original, aligned, conformed, bind-skinned",
    )
    comparison_stages = [("original aligned", conf["globallyAligned"])]
    if failed_verts is not None:
        comparison_stages.append((f"failed {FAILED_PREP_NAME}", failed_verts))
    comparison_stages.extend(
        [
            ("repaired unskinned", verts),
            ("repaired bind-skinned", identity),
        ]
    )
    write_stage_sheet(
        out_dir / "static_comparison.png",
        cameras=cameras,
        stages=comparison_stages,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        albedo=copy["albedo"],
        joints=rest,
        parents=parents,
        title="static comparison: original aligned | failed copy | repaired",
    )
    for index, (label, stage_verts) in enumerate(stages):
        write_bind_sheet(
            out_dir / f"stage_{index}_{label.split(' ', 1)[1].replace(' ', '_')}.png",
            cameras=cameras,
            vertices=stage_verts,
            triangles=copy["triangles"],
            uvs=copy["uvs"],
            albedo=copy["albedo"],
            joints=rest,
            parents=parents,
            title=label,
        )
    write_bind_sheet(
        out_dir / "conform_before_claiming_skin.png",
        cameras=cameras,
        vertices=verts,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        albedo=copy["albedo"],
        joints=rest,
        parents=parents,
        title="conformed Roc copy on fixed Eagle T-pose (pre-transfer inspect)",
    )
    write_bind_sheet(
        out_dir / "bind_sheet.png",
        cameras=cameras,
        vertices=identity,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        albedo=copy["albedo"],
        joints=rest,
        parents=parents,
        title="Roc copy bind after donor-weight transfer",
    )
    np.savez(
        out_dir / "research_skin.npz",
        vertices=verts,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        weights=xfer["weights"],
        normals=normals,
        names=np.asarray(names),
        parents=parents,
        offsets=offsets,
        inverseBind=ibm,
        regions=copy["vertexRegions"].astype("U32"),
        albedo=copy["albedo"],
        originalVertices=copy["vertices"],
        globallyAligned=conf["globallyAligned"],
        bindSkinned=identity,
    )
    bind_glb = write_skinned_glb(
        out_dir / "roc_copy_eagle_bind.glb",
        names=names,
        parents=parents,
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=ibm,
        vertices=verts,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        albedo=copy["albedo"],
        weights=xfer["weights"],
    )
    working = make_bind_skeleton(
        names=names,
        parents=parents,
        rest_world=rest,
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=ibm,
        vertices=verts,
        triangles=copy["triangles"],
        uvs=copy["uvs"],
        weights=xfer["weights"],
        albedo=copy["albedo"],
        normals=normals,
    )
    export = reload_and_compare(out_dir / "roc_copy_eagle_bind.glb", working)
    inspect = inspect_glb_animation(out_dir / "roc_copy_eagle_bind.glb")
    if inspect["jointCount"] != 50:
        raise ValueError("bind GLB joint count is not 50")
    if inspect["animationCount"] != 0:
        raise ValueError("bind GLB must not carry clip animation")
    if not export.get("ok", False):
        raise ValueError(f"bind GLB export identity failed: {export}")
    if "originalRoc" in hashes:
        verify_original_untouched(hashes["originalRoc"])
    handles = {
        "landmarks": [
            {"rocBone": roc, "eagleJoint": eagle} for roc, eagle in ROC_TO_EAGLE_LANDMARKS
        ],
        "vertexRegions": {
            str(region): int(np.sum(copy["vertexRegions"] == region))
            for region in sorted(set(copy["vertexRegions"].tolist()))
        },
        "revisions": conf["revisions"],
        "solver": conf["solver"],
        "failedPredecessor": str(
            (MOCAP_EAGLE_SKINNED / "preparation" / FAILED_PREP_NAME).as_posix()
        ),
    }
    _write_json(out_dir / "preparation_handles.json", handles)
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "status": "unproven",
        "visualAcceptance": "unreviewed_candidate",
        "keepAuthority": EAGLE_SKINNED_KEEP_AUTHORITY,
        "originalSmartRigUntouched": True,
        "inputHashes": hashes,
        "bindSkinIdentityMax": identity_err,
        "weightTransfer": {
            "threshold": xfer["threshold"],
            "unmatchedCount": 0,
            "maxInfluencesPerVertex": xfer["maxInfluencesPerVertex"],
            "influenceCountDeferred": True,
        },
        "exportTruncation": bind_glb["truncation"],
        "exportReload": export,
        "glbInspect": inspect,
        "conform": conf["diagnostics"],
        "similarity": conf["similarity"],
        "revisions": conf["revisions"],
        "solver": conf["solver"],
        "cameras": {key: cameras[key] for key in ("space", "perPanelAutofit", "width", "height")},
        "doubleTransformRemoved": True,
        "donorGeometryNotCopied": True,
        "settings": dict(EAGLE_SKINNED_SETTINGS),
        "timings": {"wallSec": time.perf_counter() - wall},
        "paths": {
            "bindGlb": str((out_dir / "roc_copy_eagle_bind.glb").as_posix()),
            "researchSkin": str((out_dir / "research_skin.npz").as_posix()),
            "bindSheet": str((out_dir / "bind_sheet.png").as_posix()),
            "preTransferSheet": str((out_dir / "conform_before_claiming_skin.png").as_posix()),
            "geometryStages": str((out_dir / "geometry_stages.png").as_posix()),
            "staticComparison": str((out_dir / "static_comparison.png").as_posix()),
        },
    }
    _write_json(out_dir / "preparation_manifest.json", payload)
    if freeze_global:
        _archive_if_failed_freeze(PREP_FREEZE, "preparation_frozen_failed_eagle_skin_v1.json")
        if not PREP_FREEZE.is_file():
            _write_json(
                PREP_FREEZE,
                {
                    "frozen": True,
                    "preparationDir": str(out_dir.as_posix()),
                    "inputHashes": hashes,
                    "bindGlb": payload["paths"]["bindGlb"],
                    "researchSkin": payload["paths"]["researchSkin"],
                    "settings": dict(EAGLE_SKINNED_SETTINGS),
                    "failedPredecessor": handles["failedPredecessor"],
                },
            )
    return payload


def _load_frozen_prep() -> tuple[dict[str, Any], dict[str, Any]]:
    if not PREP_FREEZE.is_file():
        raise FileNotFoundError("preparation is not frozen; run prepare first")
    freeze = json.loads(PREP_FREEZE.read_text(encoding="utf-8"))
    if _failed_prep_dir(Path(freeze["preparationDir"])):
        raise ValueError(
            "frozen preparation is a failed candidate; run prepare with a new --run-name from the original Roc"
        )
    verify_original_untouched(freeze["inputHashes"]["originalRoc"])
    skin = np.load(freeze["researchSkin"], allow_pickle=False)
    return freeze, {
        "vertices": np.asarray(skin["vertices"], dtype=np.float64),
        "triangles": np.asarray(skin["triangles"], dtype=np.int64),
        "uvs": np.asarray(skin["uvs"], dtype=np.float64),
        "weights": np.asarray(skin["weights"], dtype=np.float64),
        "names": _names(skin["names"]),
        "parents": np.asarray(skin["parents"], dtype=np.int64),
        "offsets": np.asarray(skin["offsets"], dtype=np.float64),
        "inverseBind": np.asarray(skin["inverseBind"], dtype=np.float64),
        "regions": np.asarray(skin["regions"]).astype(object),
        "albedo": np.asarray(skin["albedo"]),
    }


def actuation(*, run_name: str) -> dict[str, Any]:
    refuse_forbidden_inputs()
    freeze, skin = _load_frozen_prep()
    out_dir = MOCAP_EAGLE_SKINNED / "actuation" / run_name
    _refuse_existing(out_dir)
    names = skin["names"]
    name_index = {name: index for index, name in enumerate(names)}
    parents = skin["parents"]
    offsets = skin["offsets"]
    rest_off = offsets.copy()
    rest_off[0] = 0.0
    rest = compute_rest_joints(offsets, parents)
    bind = bind_world_matrices(offsets, parents)
    rest_verts = skin_dense(skin["vertices"], skin["weights"], bind, skin["inverseBind"])
    posed_sets = {}
    isolation = {}
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(names), axis=0)
    for label, joint, region, opposite in ACTUATION_JOINTS:
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
        }
        if not isolation[label]["isolated"]:
            raise ValueError(f"actuation {label} moved the opposite region too much: {isolation[label]}")
    cameras = freeze_shared_camera(np.concatenate([rest_verts, rest]), width=256, height=256)
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
    payload = {
        "ok": True,
        "proof": "generated-artifact",
        "preparationDir": freeze["preparationDir"],
        "isolation": isolation,
        "gif": str(gif.as_posix()),
        "settings": dict(EAGLE_SKINNED_SETTINGS),
    }
    _write_json(out_dir / "actuation_report.json", payload)
    return payload


def _load_skin_npz(path: Path) -> dict[str, Any]:
    skin = np.load(path, allow_pickle=False)
    return {
        "vertices": np.asarray(skin["vertices"], dtype=np.float64),
        "triangles": np.asarray(skin["triangles"], dtype=np.int64),
        "uvs": np.asarray(skin["uvs"], dtype=np.float64),
        "weights": np.asarray(skin["weights"], dtype=np.float64),
        "names": _names(skin["names"]),
        "parents": np.asarray(skin["parents"], dtype=np.int64),
        "offsets": np.asarray(skin["offsets"], dtype=np.float64),
        "inverseBind": np.asarray(skin["inverseBind"], dtype=np.float64),
        "regions": np.asarray(skin["regions"]).astype(object),
        "albedo": np.asarray(skin["albedo"]),
    }


def run_ab(case_key: str, *, run_name: str, allow_holdout: bool) -> dict[str, Any]:
    refuse_forbidden_inputs()
    case = EVALUATION_CASES[case_key]
    refuse_holdout_without_freeze(case, allow_holdout=allow_holdout)
    if case.role == "holdout" and not AB_FREEZE.is_file():
        raise ValueError("freeze A/B settings on roc_flight before the attack holdout")
    freeze, skin = _load_frozen_prep()
    return run_ab_from_skin(
        case_key,
        skin=skin,
        freeze=freeze,
        run_name=run_name,
        allow_holdout=allow_holdout,
        freeze_global=True,
    )


def run_ab_from_skin(
    case_key: str,
    *,
    skin: dict[str, Any],
    freeze: dict[str, Any],
    run_name: str,
    allow_holdout: bool,
    freeze_global: bool,
    out_root: Path | None = None,
) -> dict[str, Any]:
    refuse_forbidden_inputs()
    case = EVALUATION_CASES[case_key]
    refuse_holdout_without_freeze(case, allow_holdout=allow_holdout)
    if freeze_global and AB_FREEZE.is_file():
        frozen_ab = json.loads(AB_FREEZE.read_text(encoding="utf-8"))
        if _failed_prep_dir(Path(frozen_ab["preparationDir"])):
            _archive_if_failed_freeze(AB_FREEZE, "ab_settings_frozen_failed_eagle_skin_v1.json")
            if frozen_ab["twistPolicy"] != EAGLE_SKINNED_SETTINGS["twistPolicy"]:
                raise ValueError("refusing to change the frozen twist policy")
            if frozen_ab["hypothesisA"] != EAGLE_SKINNED_SETTINGS["hypothesisA"]:
                raise ValueError("refusing to change frozen hypothesis A")
            if frozen_ab["hypothesisB"] != EAGLE_SKINNED_SETTINGS["hypothesisB"]:
                raise ValueError("refusing to change frozen hypothesis B")
        else:
            if frozen_ab["preparationDir"] != freeze["preparationDir"]:
                raise ValueError("A/B freeze points at a different preparation")
            if frozen_ab["twistPolicy"] != EAGLE_SKINNED_SETTINGS["twistPolicy"]:
                raise ValueError("refusing to change the frozen twist policy")
    root = out_root if out_root is not None else MOCAP_EAGLE_SKINNED
    out_dir = root / "ab" / case_key / run_name
    _refuse_existing(out_dir)
    wall = time.perf_counter()
    donor = load_donor_package()
    capture = load_saved_capture(CAPTURE_BY_CASE[case_key], donor)
    reconstruct_started = time.perf_counter()
    ab = reconstruct_ab(
        capture_positions=capture["pred_position"],
        offsets=skin["offsets"],
        parents=skin["parents"],
    )
    reconstruct_sec = time.perf_counter() - reconstruct_started
    mesh_a = [
        skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"]) for world in ab["jointWorldA"]
    ]
    mesh_b = [
        skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"]) for world in ab["jointWorldB"]
    ]
    rest_verts = skin["vertices"]
    distortion_a = [triangle_distortion(rest_verts, frame, skin["triangles"]) for frame in mesh_a]
    distortion_b = [triangle_distortion(rest_verts, frame, skin["triangles"]) for frame in mesh_b]
    cameras = freeze_shared_camera(
        np.concatenate(
            [
                rest_verts,
                ab["captureRootCentered"].reshape(-1, 3),
                ab["positionsA"].reshape(-1, 3),
                ab["positionsB"].reshape(-1, 3),
            ]
        ),
        width=256,
        height=256,
    )
    sprites = [Image.open(path) for path in numbered_pngs(case.frames)]
    previous = load_gif_frames(PREV_RETARGET_GIF[case_key]) if PREV_RETARGET_GIF[case_key].is_file() else None
    out_dir.mkdir(parents=True)
    render_started = time.perf_counter()
    overlay = write_overlay_gif(
        out_dir / "review_ab.gif",
        cameras=cameras,
        sprites=sprites,
        previous_retarget=previous,
        capture=ab["captureRootCentered"],
        joints_a=ab["positionsA"],
        joints_b=ab["positionsB"],
        parents=skin["parents"],
        mesh_a=mesh_a,
        mesh_b=mesh_b,
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
        title=f"{case_key} A=fixed-length B=exact-joint",
    )
    render_sec = time.perf_counter() - render_started
    times = np.arange(len(ab["localRotation"]), dtype=np.float32) * float(SOURCE_FRAME_MS) / 1000.0
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(skin["names"]), axis=0)
    rest_off = _bind_root_translation(skin["offsets"])
    trans_b = np.asarray(ab["localTranslationB"], dtype=np.float64).copy()
    trans_b[:, 0] = rest_off[0]
    glb_a = write_skinned_glb(
        out_dir / "roc_copy_eagle_A_fixed_length.glb",
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
            "name": "A_fixed_length",
            "times": times,
            "rotations": matrices_to_xyzw(ab["localRotation"]),
        },
    )
    glb_b = write_skinned_glb(
        out_dir / "roc_copy_eagle_B_exact_joint.glb",
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
            "name": "B_exact_joint",
            "times": times,
            "rotations": matrices_to_xyzw(ab["localRotation"]),
            "translations": trans_b.astype(np.float32),
        },
    )
    inspect_a = inspect_glb_animation(out_dir / "roc_copy_eagle_A_fixed_length.glb")
    inspect_b = inspect_glb_animation(out_dir / "roc_copy_eagle_B_exact_joint.glb")
    if inspect_a["translationChannels"] != 0 or inspect_a["hasScaleChannel"]:
        raise ValueError("hypothesis A must animate rotation only")
    if inspect_b["translationChannels"] != 50 or inspect_b["hasScaleChannel"]:
        raise ValueError("hypothesis B must animate local translation, not scale")
    if inspect_a["rotationChannels"] != 50 or inspect_b["rotationChannels"] != 50:
        raise ValueError("A/B GLBs dropped rotation channels")
    working = make_bind_skeleton(
        names=skin["names"],
        parents=skin["parents"],
        rest_world=ab["bindRestJoints"],
        rest_local_rotation=rest_local,
        rest_local_translation=rest_off,
        inverse_bind=skin["inverseBind"],
        vertices=skin["vertices"],
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        weights=skin["weights"],
        albedo=skin["albedo"],
    )
    export_a = reload_and_compare(out_dir / "roc_copy_eagle_A_fixed_length.glb", working)
    export_b = reload_and_compare(out_dir / "roc_copy_eagle_B_exact_joint.glb", working)
    clip_sec = reconstruct_sec + render_sec
    if clip_sec > 600:
        raise ValueError(f"recurring clip reconstruct+GIF exceeded 600s: {clip_sec}")
    limitations = []
    max_b_stretch = float(ab["stretchBMax"])
    if max_b_stretch > 1.5:
        limitations.append(f"exact-joint replay stretches some bones to {max_b_stretch:.2f}x bind length")
    max_dist_b = max(item["maxEdgeRatio"] for item in distortion_b)
    if max_dist_b > 3.0:
        limitations.append(f"B triangle edges reach {max_dist_b:.2f}x rest; mesh may tear even if joints overlay")
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "status": "unproven",
        "visualAcceptance": "unreviewed_candidate",
        "case": case_key,
        "keepAuthority": EAGLE_SKINNED_KEEP_AUTHORITY,
        "usedLearnedRotations": False,
        "captureSha256": capture["sha256"],
        "inputHashes": freeze["inputHashes"],
        "residualAMax": ab["residualAMax"],
        "residualAMean": ab["residualAMean"],
        "residualBMax": ab["residualBMax"],
        "fixedLengthErrorMax": ab["fixedLengthErrorMax"],
        "stretchBMax": ab["stretchBMax"],
        "stretchBMedian": ab["stretchBMedian"],
        "twistPolicy": ab["twistPolicy"],
        "distortionA": distortion_a,
        "distortionB": distortion_b,
        "exportA": {"truncation": glb_a["truncation"], "reload": export_a, "inspect": inspect_a},
        "exportB": {"truncation": glb_b["truncation"], "reload": export_b, "inspect": inspect_b},
        "limitations": limitations,
        "gifs": {
            "ab": str(overlay.as_posix()),
            "previousRetarget": str(PREV_RETARGET_GIF[case_key].as_posix()),
        },
        "timings": {
            "reconstructSec": reconstruct_sec,
            "renderSec": render_sec,
            "clipRetargetSec": clip_sec,
            "wallSec": time.perf_counter() - wall,
            "warmClipBudgetSec": 600,
        },
        "settings": dict(EAGLE_SKINNED_SETTINGS),
        "note": (
            "A and B are equal-status hypotheses on the same new skin. "
            "Exact green-joint overlay with torn feathers is not success. "
            "visualAcceptance stays unreviewed_candidate until the user judges the GIFs."
        ),
    }
    _write_json(out_dir / "ab_report.json", report)
    _write_comparison_report(out_dir / "comparison.md", report)
    if freeze_global and case_key == "roc_flight" and not AB_FREEZE.is_file():
        _write_json(
            AB_FREEZE,
            {
                "frozen": True,
                "preparationDir": freeze["preparationDir"],
                "twistPolicy": ab["twistPolicy"],
                "hypothesisA": EAGLE_SKINNED_SETTINGS["hypothesisA"],
                "hypothesisB": EAGLE_SKINNED_SETTINGS["hypothesisB"],
                "flightRun": str(out_dir.as_posix()),
            },
        )
    return report


def _write_comparison_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        f"# Eagle-skinned Roc A/B — {report['case']}",
        "",
        "Generated-artifact comparison. Not visual acceptance and not game delivery.",
        "",
        f"- A residual vs green joints (max/mean): {report['residualAMax']:.4f} / {report['residualAMean']:.4f}",
        f"- A fixed-length error max: {report['fixedLengthErrorMax']:.6f}",
        f"- B joint replay error max: {report['residualBMax']:.8f}",
        f"- B bone stretch max/median: {report['stretchBMax']:.3f} / {report['stretchBMedian']:.3f}",
        f"- Twist policy: {report['twistPolicy']}",
        f"- Learned rotations used: {report['usedLearnedRotations']}",
        "",
        "## Limitations",
        "",
    ]
    if report["limitations"]:
        lines.extend(f"- {item}" for item in report["limitations"])
    else:
        lines.append("- None recorded by the automated gates. Visual tearing can still exist.")
    lines.extend(["", f"GIF: `{report['gifs']['ab']}`", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _vertex_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    from eagle_glb import _vertex_normals as compute

    return compute(vertices, triangles)


def main() -> int:
    args = parse_args()
    if args.command == "controls":
        print(json.dumps(run_controls(), indent=2, default=_json_default))
        return 0
    if args.command == "donor-verify":
        print(json.dumps(donor_verify(), indent=2, default=_json_default))
        return 0
    if args.command == "prepare":
        print(json.dumps(prepare(run_name=args.run_name), indent=2, default=_json_default))
        return 0
    if args.command == "actuation":
        print(json.dumps(actuation(run_name=args.run_name), indent=2, default=_json_default))
        return 0
    if args.command == "freeze-status":
        print(json.dumps(freeze_status(), indent=2, default=_json_default))
        return 0
    if args.command == "ab":
        if not args.case:
            raise SystemExit("ab requires roc_flight or roc_attack")
        report = run_ab(args.case, run_name=args.run_name, allow_holdout=args.allow_holdout)
        print(json.dumps({key: report[key] for key in report if key not in {"distortionA", "distortionB"}}, indent=2, default=_json_default))
        return 0 if report.get("ok") else 1
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
