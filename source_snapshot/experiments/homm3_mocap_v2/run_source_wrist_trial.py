"""Diagnostic source-guided leaf wrist orientation on a fixed skin candidate."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

from run_skin_mesh_pilot import (
    ROOT,
    SkinImageRenderer,
    comparison,
    deform,
    digest,
    expand_camera_to_full_canvas,
    sha256_file,
)
from run_skin_weight_pilot import cascade_batch_lock, source_images
from run_surface_loss_attribution import _load_inputs
from source_wrist_orientation import solve_projected_direction
from attachment_quality import attachment_quality
from asset_profiles import get_profile
from geometry_ownership import load_ownership, validate_prepared_ownership, animated_boundary_gate
from structured_profiles import require_profile_pin


def _validate_profile_skin(fitted, prepared, ownership, owner):
    """Use reviewed physical ownership already replayed by frozen preparation."""
    names = [str(value) for value in fitted['names']]
    if names.count(owner) != 1:
        raise ValueError('profile wrist owner must resolve exactly once')
    index = names.index(owner)
    if np.any(np.asarray(fitted['parents']) == index) or fitted['parents'][index] < 0:
        raise ValueError('profile wrist owner must be a leaf with a parent')
    for key in ('names', 'parents', 'triangles', 'sourceVertexIds'):
        if key not in fitted or key not in prepared or not np.array_equal(fitted[key], prepared[key]):
            raise ValueError(f'profile wrist fitted/prepared {key} differs')
    parts = [part for part in ownership['rigidParts'] if part['owner'] == owner]
    if len(parts) != 1:
        raise ValueError('profile wrist requires exactly one reviewed part for owner')
    selected = np.asarray(parts[0]['faceIds'])
    triangles = np.asarray(fitted['triangles'])
    if selected.ndim != 1 or selected.dtype.kind not in 'iu' or not len(selected) or len(np.unique(selected)) != len(selected) or selected.min() < 0 or selected.max() >= len(triangles):
        raise ValueError('profile wrist face mask is invalid')
    rigid_ids = np.unique(triangles[selected])
    expected = np.zeros((len(rigid_ids), len(names)))
    expected[:, index] = 1
    if not np.array_equal(np.asarray(fitted['weights'])[rigid_ids], expected):
        raise ValueError('profile wrist selected surface is not rigid under its declared owner')
    if not np.all(np.asarray(fitted['regions'])[rigid_ids] == parts[0]['region']):
        raise ValueError('profile wrist selected surface region differs')
    candidate = {key: np.asarray(fitted[key]).copy() for key in ('vertices', 'weights', 'names', 'parents')}
    return candidate, selected.astype(np.int64)


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _profile_annotation_scope(annotation, corpus, corpus_path, frame_paths):
    """Every native capture is observed for completion or explicitly retained raw."""
    completed = annotation['captures']
    omitted = annotation.get('uncompletedCaptures')
    rows = {row['key']: row for row in corpus['captures']}
    if not isinstance(omitted, dict) or set(completed) & set(omitted) or set(completed) | set(omitted) != set(rows):
        raise ValueError('profile annotation must partition every corpus capture explicitly')
    if not isinstance(annotation.get('completionScope'), str) or not annotation['completionScope'].strip():
        raise ValueError('profile annotation requires source-observation scope')
    for key, capture in completed.items():
        if any(frame.get('directionEvidence') != 'observed' or frame.get('ambiguous') is not False for frame in capture['frames']):
            raise ValueError(f'completion requires observed, unambiguous directions: {key}')
    for key, capture in omitted.items():
        row = rows[key]
        if not isinstance(capture.get('reason'), str) or not capture['reason'].strip():
            raise ValueError(f'uncompleted capture requires a reason: {key}')
        frames = capture.get('frames')
        if capture.get('captureSha256') != row['captureSha256'] or capture.get('frameCount') != len(row['frames']) or not isinstance(frames, list) or len(frames) != len(row['frames']):
            raise ValueError(f'uncompleted capture provenance differs: {key}')
        for index, frame in enumerate(frames):
            expected = frame_paths[key][index].resolve()
            if frame.get('localIndex') != index or _resolve(str(frame.get('sourcePath', '')), corpus_path) != expected or frame.get('sourceSha256') != sha256_file(expected):
                raise ValueError(f'uncompleted source frame provenance differs: {key}[{index}]')
    return {'scope': annotation['completionScope'], 'completedFrameCount': sum(len(c['frames']) for c in completed.values()),
            'uncompletedCaptures': omitted, 'uncompletedMotionPolicy': 'original captured motion retained; no inferred landmarks'}


def _profile_anchor_ids(annotation, profile, fitted, rigid_ids):
    anchor = annotation.get('targetAnchor', {})
    if anchor.get('sourceMeshSha256') != profile['expectedMeshSha256'] or anchor.get('geometryOwnershipSha256') != profile['geometryOwnership']['sha256']:
        raise ValueError('target tip anchor source/ownership provenance differs')
    if anchor.get('role') != 'weapon_tip' or not isinstance(anchor.get('evidence'), str) or not anchor['evidence'].strip():
        raise ValueError('target anchor must explicitly identify reviewed weapon tip')
    ids = np.asarray(anchor.get('sourceVertexIds'))
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or not len(ids) or len(np.unique(ids)) != len(ids):
        raise ValueError('target tip anchor requires unique integer source vertex IDs')
    source_ids = np.asarray(fitted['sourceVertexIds'])[rigid_ids]
    selected = rigid_ids[np.isin(source_ids, ids)]
    if len(selected) != len(ids) or set(source_ids[np.isin(source_ids, ids)].tolist()) != set(ids.tolist()):
        raise ValueError('target tip anchor must resolve once inside reviewed rigid surface')
    return selected


def _load_annotation(
    path: Path,
    asset: str,
    corpus_path: Path,
    corpus_sha: str,
    research_skin_sha: str,
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("weapon annotation schema must be integer 1")
    if value.get("asset") != asset:
        raise ValueError("weapon annotation asset does not match --asset")
    source_corpus = Path(str(value.get("sourceCorpus", "")))
    if not source_corpus.is_absolute():
        raise ValueError("weapon annotation sourceCorpus must be absolute")
    if source_corpus.resolve() != corpus_path.resolve():
        raise ValueError("weapon annotation sourceCorpus does not match fit corpus")
    annotation_corpus_sha = value.get("corpusSha256")
    if annotation_corpus_sha != corpus_sha:
        raise ValueError("weapon annotation corpusSha256 does not match fit corpus")
    if value.get("researchSkinSha256") != research_skin_sha:
        raise ValueError("weapon annotation researchSkinSha256 does not match fit research skin")
    canvas = value.get("canvas")
    if not isinstance(canvas, dict) or int(canvas.get("width", 0)) <= 0 or int(canvas.get("height", 0)) <= 0:
        raise ValueError("weapon annotation canvas must contain positive width and height")
    if canvas.get("coordinateOrigin") != "top_left" or canvas.get("coordinatesAreOriginalSourcePixels") is not True:
        raise ValueError("weapon landmarks must use original source pixels with top-left origin")
    if value.get("landmarkOrder") != ["grip", "clubTip"]:
        raise ValueError("weapon annotation landmarkOrder must be grip, clubTip")
    captures = value.get("captures")
    if not isinstance(captures, dict) or not captures:
        raise ValueError("weapon annotation captures must be a non-empty object")
    return value


def _resolve(value: str, corpus_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (corpus_path.parent / path).resolve()


def _wrap_degrees(value: float) -> float:
    return float((value + 180.0) % 360.0 - 180.0)


def _validate_candidate(
    candidate_dir: Path,
    mask_dir: Path,
    fit_report: dict[str, Any],
    fit_provenance: dict[str, Any],
    fitted: dict[str, Any],
    owner: str,
) -> tuple[dict[str, Any], dict[str, np.ndarray], np.ndarray]:
    report_path = candidate_dir / "report.json"
    candidate_path = candidate_dir / "rigid_skin_candidate.npz"
    if not report_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("candidate-dir requires report.json and rigid_skin_candidate.npz")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("asset") != fit_report.get("asset"):
        raise ValueError("candidate asset differs from fit")
    if report.get("owner") != owner:
        raise ValueError("candidate owner differs from requested wrist")
    if report.get("ownershipRepresentation") != "skin-vertices":
        raise ValueError("candidate must be the skin-vertices ownership representation")
    if not _same_json(report.get("fitProvenance"), fit_provenance):
        raise ValueError("candidate fitProvenance differs from loaded fit")
    mask_report_path = mask_dir / "report.json"
    mask_path = mask_dir / "face_proposal.npz"
    if not mask_report_path.is_file() or not mask_path.is_file():
        raise FileNotFoundError("mask-dir requires report.json and face_proposal.npz")
    mask_report = json.loads(mask_report_path.read_text(encoding="utf-8"))
    if mask_report.get("maskSha256") != sha256_file(mask_path):
        raise ValueError("mask producer digest does not match face_proposal.npz")
    if mask_report.get("asset") != fit_report.get("asset"):
        raise ValueError("mask producer asset differs from fit")
    if mask_report.get("researchSkinSha256") != fit_report.get("inputs", {}).get("researchSkin"):
        raise ValueError("mask producer research skin differs from fit")
    if report.get("maskSha256") != mask_report["maskSha256"]:
        raise ValueError("candidate mask digest differs from mask producer")
    if report.get("maskReportSha256") != sha256_file(mask_report_path):
        raise ValueError("candidate maskReportSha256 does not match mask producer report")
    if report.get("candidateSha256") != sha256_file(candidate_path):
        raise ValueError("candidate producer digest does not match candidate NPZ")
    with np.load(mask_path, allow_pickle=False) as mask:
        selected = np.asarray(mask["propTriangles"])
    if selected.ndim != 1 or selected.dtype.kind not in "iu" or not len(selected):
        raise ValueError("mask propTriangles must be a nonempty integer vector")
    if len(np.unique(selected)) != len(selected) or selected.min() < 0 or selected.max() >= len(fitted["triangles"]):
        raise ValueError("mask propTriangles are invalid for fitted topology")
    rigid_ids = np.unique(np.asarray(fitted["triangles"])[selected])
    names = [str(value) for value in np.asarray(fitted["names"]).tolist()]
    if names.count(owner) != 1:
        raise ValueError("owner must occur exactly once")
    owner_index = names.index(owner)
    parents = np.asarray(fitted["parents"], dtype=np.int64)
    if np.any(parents == owner_index):
        raise ValueError("owner must be a leaf joint")
    if parents[owner_index] < 0:
        raise ValueError("wrist owner requires a parent joint")
    with np.load(candidate_path, allow_pickle=False) as data:
        candidate = {key: data[key].copy() for key in data.files}
    required = {"weights", "vertices", "names", "parents"}
    if set(candidate) != required:
        raise ValueError(f"candidate keys must be exactly {sorted(required)}")
    if not np.array_equal(candidate["vertices"], fitted["vertices"]):
        raise ValueError("candidate vertices differ from fitted rest")
    if not np.array_equal(candidate["names"].astype(str), np.asarray(fitted["names"]).astype(str)):
        raise ValueError("candidate names differ from fitted skeleton")
    if not np.array_equal(candidate["parents"], fitted["parents"]):
        raise ValueError("candidate parents differ from fitted skeleton")
    weights = np.asarray(candidate["weights"], dtype=np.float64)
    base_weights = np.asarray(fitted["weights"], dtype=np.float64)
    if weights.shape != base_weights.shape or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("candidate weights have invalid shape or values")
    changed = np.any(weights != base_weights, axis=1)
    if np.setdiff1d(np.flatnonzero(changed), rigid_ids).size:
        raise ValueError("candidate changed weight rows outside selected-face vertex union")
    expected = base_weights.copy()
    expected[rigid_ids] = 0.0
    expected[rigid_ids, owner_index] = 1.0
    if not np.array_equal(weights, expected):
        raise ValueError("candidate weights are not the expected one-hot owner replacement")
    return report, candidate, selected.astype(np.int64)


def _annotation_frames(
    annotation: dict[str, Any],
    corpus: dict[str, Any],
    corpus_path: Path,
    frame_paths: dict[str, list[Path]],
) -> dict[str, list[dict[str, Any]]]:
    rows = {row["key"]: row for row in corpus["captures"]}
    result: dict[str, list[dict[str, Any]]] = {}
    canvas = annotation["canvas"]
    expected_canvas = (int(canvas["width"]), int(canvas["height"]))
    for key, capture in annotation["captures"].items():
        if key not in rows or key not in frame_paths:
            raise ValueError(f"annotation clip is absent from current corpus: {key}")
        row = rows[key]
        if capture.get("captureSha256") != row["captureSha256"]:
            raise ValueError(f"annotation capture hash differs for {key}")
        if capture.get("frameCount") != len(row["frames"]):
            raise ValueError(f"annotation frame count differs for {key}")
        frames = capture.get("frames")
        if not isinstance(frames, list):
            raise ValueError(f"annotation frames must be a list for {key}")
        if len(frames) != len(row["frames"]) or len(frames) != len(frame_paths[key]):
            raise ValueError(f"annotation frame inventory differs for {key}")
        checked = []
        for index, frame in enumerate(frames):
            for landmark in ("grip", "clubTip"):
                point = frame.get(landmark)
                if not isinstance(point, list) or len(point) != 2 or not np.isfinite(point).all():
                    raise ValueError(f"invalid {landmark} landmark in {key}[{index}]")
            if np.linalg.norm(np.asarray(frame["clubTip"]) - np.asarray(frame["grip"])) < 1e-8:
                raise ValueError(f"coincident weapon landmarks in {key}[{index}]")
            if type(frame.get("ambiguous")) is not bool:
                raise ValueError(f"landmark ambiguity must be explicit for {key}[{index}]")
            if frame.get("localIndex") != index:
                raise ValueError(f"annotation localIndex is not contiguous for {key}[{index}]")
            path = _resolve(str(frame.get("sourcePath", "")), corpus_path)
            expected_path = frame_paths[key][index].resolve()
            if path != expected_path:
                raise ValueError(f"annotation sourcePath differs for {key}[{index}]")
            if frame.get("sourceSha256") != sha256_file(expected_path):
                raise ValueError(f"annotation sourceSha256 differs for {key}[{index}]")
            with Image.open(expected_path) as image:
                if image.mode != "RGBA":
                    raise ValueError(f"annotation source frame is not RGBA for {key}[{index}]")
                if image.size != expected_canvas:
                    raise ValueError(f"annotation canvas differs for {key}[{index}]")
                alpha = np.asarray(image, dtype=np.uint8)[..., 3]
                radius = max(1, int(np.ceil(0.01 * min(image.size))))
                for landmark in ("grip", "clubTip"):
                    x, y = (float(value) for value in frame[landmark])
                    if not (0.0 <= x < image.width and 0.0 <= y < image.height):
                        raise ValueError(f"{landmark} landmark is outside source canvas for {key}[{index}]")
                    cx, cy = int(round(x)), int(round(y))
                    x0, x1 = max(0, cx - radius), min(image.width, cx + radius + 1)
                    y0, y1 = max(0, cy - radius), min(image.height, cy + radius + 1)
                    if not bool((alpha[y0:y1, x0:x1] > 127).any()):
                        raise ValueError(f"{landmark} landmark has no foreground alpha support for {key}[{index}]")
            checked.append(frame)
        result[key] = checked
    return result


def run(asset: str, fit_dir: Path, candidate_dir: Path, mask_dir: Path,
        annotation_path: Path, owner: str, output: Path, *, profile_ownership=False) -> dict[str, Any]:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    fit_report, corpus, _freeze, _prepared, fitted, _calibration, motions, frame_paths, provenance = _load_inputs(fit_dir, asset)
    corpus_path = Path(fit_report["inputs"]["corpus"])
    corpus_sha = fit_report["inputs"]["corpusSha256"]
    research_skin_sha = fit_report["inputs"]["researchSkin"]
    if not research_skin_sha:
        raise ValueError("fit report lacks research skin digest")
    annotation = _load_annotation(annotation_path, asset, corpus_path, corpus_sha, research_skin_sha)
    annotated = _annotation_frames(annotation, corpus, corpus_path, frame_paths)
    profile_pin = None
    if profile_ownership:
        if candidate_dir is not None or mask_dir is not None:
            raise ValueError('profile ownership cannot be combined with legacy candidate/mask directories')
        profile = get_profile(asset)
        profile_pin = require_profile_pin(asset, profile, fit_report, _freeze, corpus, annotation)
        observation_scope = _profile_annotation_scope(annotation, corpus, corpus_path, frame_paths)
        if 'geometryOwnership' not in profile:
            raise ValueError('profile ownership requires an explicit reviewed physical mask')
        validate_prepared_ownership(profile, _prepared)
        ownership = load_ownership(profile)
        candidate, selected_np = _validate_profile_skin(fitted, _prepared, ownership, owner)
        candidate_report = {'candidateSha256': provenance['candidateSha256'],
                            'maskSha256': profile['geometryOwnership']['sha256'],
                            'cameraSha256': sha256_file(Path(fit_report['baselineDirectory']) / 'camera.json')}
        candidate_report_sha = provenance['reportSha256']
    else:
        if candidate_dir is None or mask_dir is None:
            raise ValueError('legacy wrist trial requires both candidate-dir and mask-dir')
        candidate_report, candidate, selected_np = _validate_candidate(candidate_dir, mask_dir, fit_report, provenance, fitted, owner)
        candidate_report_sha = sha256_file(candidate_dir / 'report.json')
    keys = set(annotated)
    motions = {key: motions[key] for key in keys}
    names = [str(value) for value in np.asarray(fitted["names"]).tolist()]
    owner_index = names.index(owner)
    rigid_ids = np.unique(np.asarray(fitted["triangles"])[selected_np])
    idle_rows = [row for row in corpus["captures"] if row.get("key") == "g02_idle" or str(row.get("key", "")).endswith("_idle")]
    if len(idle_rows) != 1:
        raise ValueError("corpus must contain exactly one explicit idle clip for source-idle protection")
    idle_hashes = set()
    for idle_path in idle_rows[0]["frames"]:
        resolved_idle = _resolve(str(idle_path), corpus_path)
        if not resolved_idle.is_file():
            raise FileNotFoundError(resolved_idle)
        idle_hashes.add(sha256_file(resolved_idle))
    owner_origin = np.linalg.inv(np.asarray(fitted["inverseBind"], dtype=np.float64))[owner_index, :3, 3]
    rest_vertices = np.asarray(fitted["vertices"], dtype=np.float64)
    if profile_ownership:
        anchor_ids = _profile_anchor_ids(annotation, profile, fitted, rigid_ids)
    else:
        distances = np.linalg.norm(rest_vertices[rigid_ids] - owner_origin[None], axis=1)
        count = max(1, int(np.ceil(0.05 * len(rigid_ids))))
        anchor_ids = rigid_ids[np.argsort(distances)[-count:]]
    anchor = rest_vertices[anchor_ids].mean(axis=0)
    owner_inverse_bind = np.asarray(fitted["inverseBind"], dtype=np.float64)[owner_index]
    anchor_local = owner_inverse_bind[:3, :3] @ (anchor - owner_origin)
    camera_path = Path(fit_report["baselineDirectory"]) / "camera.json"
    if candidate_report.get("cameraSha256") != sha256_file(camera_path):
        raise ValueError("candidate cameraSha256 does not match fit camera")
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text(encoding="utf-8")), 224)
    output.mkdir(parents=True)
    report: dict[str, Any] = {
        "schema": 1, "asset": asset, "owner": owner, "accepted": False,
        "proof": "source-guided-wrist-orientation-diagnostic-no-delivery",
        "fitProvenance": provenance, "candidateReportSha256": candidate_report_sha,
        "candidateSha256": candidate_report["candidateSha256"], "maskSha256": candidate_report["maskSha256"],
        "annotationSha256": sha256_file(annotation_path), "corpusSha256": corpus_sha,
        "annotationPath": str(annotation_path.resolve()),
        "cameraSha256": sha256_file(camera_path), "implementationSha256": sha256_file(Path(__file__)),
        "sourceMotionChanged": False, "bodyJointPositionsChanged": False,
        "nonOwnerWorldsChanged": False, "unobservedDepthRetained": True,
        "baselineUnmodified": True, "candidateWristRotationsChanged": True,
        "delivery": False, "restAuthority": "fitted candidate vertices and skin",
        "ownerLeaf": True, "anchorVertexIds": anchor_ids.tolist(),
        "anchorRestWorld": anchor.tolist(), "ownerRestWorld": owner_origin.tolist(),
        "anchorRule": "centroid of farthest 5 percent selected-face vertices from owner rest origin",
        "cases": {},
    }
    if profile_ownership:
        report.update(profile_pin)
        report['sourceObservation'] = observation_scope
        report['targetAnchor'] = annotation['targetAnchor']
        report['anchorRule'] = 'explicit source-pinned reviewed tip vertex centroid in fitted rest'
        report['ownershipInput'] = {'kind': 'reviewed-profile-frozen-preparation',
                                   'sourceMeshSha256': profile['expectedMeshSha256'],
                                   'geometryOwnership': profile['geometryOwnership'],
                                   'preparedSkinSha256': research_skin_sha}
    all_local = []
    all_world = []
    all_corr = []
    all_baseline_local = []
    all_baseline_world = []
    clip_keys = []
    clip_offsets = [0]
    report["inputValidationSeconds"] = time.perf_counter() - started
    replay_started = time.perf_counter()
    with cascade_batch_lock(ROOT):
        rest = torch.as_tensor(rest_vertices, device="cuda", dtype=torch.float32)
        weights = torch.as_tensor(candidate["weights"], device="cuda", dtype=torch.float32)
        identity = torch.eye(4, device="cuda")[None, None].expand(1, len(names), 4, 4)
        neutral = deform(identity[:, :, :3], weights, rest)
        report["neutralIdentitySkinMaxError"] = float((neutral - rest[None]).abs().max())
        if not np.isfinite(report["neutralIdentitySkinMaxError"]) or report["neutralIdentitySkinMaxError"] > 1e-6:
            raise ValueError("candidate skin fails neutral identity parity")
        rigid = torch.as_tensor(candidate["weights"], device="cuda", dtype=torch.float32)
        render_faces = np.arange(len(fitted["triangles"]) * 3, dtype=np.int64).reshape(-1, 3)
        render_uv = np.asarray(fitted["uvs"])[np.asarray(fitted["triangles"])].reshape(-1, 2)
        renderer = SkinImageRenderer(render_faces, render_uv, fitted["albedo"], camera, 224)
        triangles = np.asarray(fitted["triangles"], dtype=np.int64)
        rest_selected = torch.as_tensor(rest_vertices[triangles[selected_np]], device="cuda", dtype=torch.float32)
        rest_edges = torch.linalg.vector_norm(rest_selected[:, 1:] - rest_selected[:, :1], dim=-1)
        attachment_labels = np.full(len(rest_vertices), "body", dtype="<U16")
        attachment_labels[rigid_ids] = "declared_part"
        for key, frame_rows in annotated.items():
            motion = motions[key]
            world0 = np.asarray(motion["jointWorld"], dtype=np.float64)
            local0 = np.asarray(motion["localRotation"], dtype=np.float64)
            world = world0.copy()
            local = local0.copy()
            corrections = []
            before_angles = []
            after_angles = []
            target_angles = []
            protected_idle = []
            for index, row in enumerate(frame_rows):
                owner_world = world0[index, owner_index]
                current = owner_world[:3, :3] @ anchor_local
                target = np.asarray(row["clubTip"], dtype=np.float64) - np.asarray(row["grip"], dtype=np.float64)
                target_angle = float(np.degrees(np.arctan2(target[1], target[0])))
                source_hash = sha256_file(frame_paths[key][index])
                is_idle = source_hash in idle_hashes
                if is_idle:
                    world[index, owner_index] = world0[index, owner_index]
                    local[index, owner_index] = local0[index, owner_index]
                    correction = np.eye(3, dtype=np.float64)
                else:
                    solved = solve_projected_direction(current, target, np.asarray(camera["right"]), np.asarray(camera["down"]), 180.0)
                    correction = solved["rotation"]
                    world[index, owner_index, :3, :3] = correction @ owner_world[:3, :3]
                    parent = int(fitted["parents"][owner_index])
                    local[index, owner_index] = world0[index, parent, :3, :3].T @ world[index, owner_index, :3, :3]
                corrections.append(correction)
                before_angles.append(float(np.degrees(np.arctan2(current @ np.asarray(camera["down"]), current @ np.asarray(camera["right"])))) )
                after_vec = correction @ current
                after_angles.append(float(np.degrees(np.arctan2(after_vec @ np.asarray(camera["down"]), after_vec @ np.asarray(camera["right"])))) )
                target_angles.append(target_angle)
                protected_idle.append(bool(is_idle))
            if not np.array_equal(world[:, :, :3, 3], world0[:, :, :3, 3]):
                raise ValueError("wrist trial changed joint positions")
            nonowner = [index for index in range(len(names)) if index != owner_index]
            if nonowner and not np.array_equal(world[:, nonowner], world0[:, nonowner]):
                raise ValueError("wrist trial changed non-owner world matrices")
            original = deform(torch.as_tensor(world0 @ np.asarray(fitted["inverseBind"])[None], device="cuda", dtype=torch.float32)[:, :, :3], weights, rest).detach()
            corrected = deform(torch.as_tensor(world @ np.asarray(fitted["inverseBind"])[None], device="cuda", dtype=torch.float32)[:, :, :3], rigid, rest).detach()
            zero_owner = torch.as_tensor(np.asarray(candidate["weights"])[:, owner_index] == 0, device="cuda")
            zero_error = float((corrected[:, zero_owner] - original[:, zero_owner]).abs().max()) if bool(zero_owner.any()) else 0.0
            if zero_error != 0.0:
                raise ValueError("vertices with zero owner influence changed")
            idle_flags = torch.as_tensor(protected_idle, device="cuda", dtype=torch.bool)
            idle_error = float((corrected[idle_flags] - original[idle_flags]).abs().max()) if bool(idle_flags.any()) else 0.0
            if idle_error != 0.0:
                raise ValueError("protected source idle appearance changed")
            corners = corrected[:, triangles[selected_np]]
            selected_edges = torch.linalg.vector_norm(corners[:, :, 1:] - corners[:, :, :1], dim=-1)
            edge_error = float((selected_edges - rest_edges).abs().max())
            if not np.isfinite(edge_error) or edge_error > 1e-5:
                raise ValueError("selected prop edges lost rigidity")
            base_rgb = renderer.render(original[:, triangles].reshape(len(original), -1, 3))[0]
            corrected_rgb = renderer.render(corrected[:, triangles].reshape(len(corrected), -1, 3))[0]
            source = source_images(frame_paths[key], camera["sourceCrop"], 224)
            comparison(output / f"{key}_comparison.gif", [source[0], base_rgb, corrected_rgb], ["DEF", "Rigid skin baseline", "Source wrist"], f"{asset} {key}")
            report["cases"][key] = {
                "attachmentGate": attachment_quality(
                    corrected, rest, triangles, weights, attachment_labels, names,
                    [{"region": "declared_part", "donorJoints": [owner]}]),
                "frames": len(world), "fixedMotionSha256": digest(world0),
                "positionMaxError": float(np.abs(world[..., :3, 3] - world0[..., :3, 3]).max()),
                "nonOwnerWorldMaxError": float(np.abs(world[:, nonowner] - world0[:, nonowner]).max()) if nonowner else 0.0,
                "zeroOwnerVertexMaxError": zero_error, "selectedEdgeMaxError": edge_error,
                "protectedIdleVertexMaxError": idle_error,
                "correctionDegrees": [float(np.degrees(np.arccos(np.clip((c.trace() - 1) / 2, -1, 1)))) for c in corrections],
                "projectedBeforeAnglesDegrees": before_angles, "projectedAfterAnglesDegrees": after_angles,
                "projectedTargetAnglesDegrees": target_angles,
                "projectedAngularErrorDegrees": [_wrap_degrees(after_angles[i] - target_angles[i]) for i in range(len(frame_rows))],
                "protectedSourceIdleFrames": protected_idle,
                "protectedSourceIdleFrameIndices": [i for i, value in enumerate(protected_idle) if value],
            }
            all_local.append(local)
            if profile_ownership:
                report['cases'][key]['ownershipBoundaryGate'] = animated_boundary_gate(
                    profile, _prepared, corrected.cpu().numpy(), expected_frame_count=len(world))
            all_world.append(world)
            all_corr.append(np.asarray(corrections))
            all_baseline_local.append(local0)
            all_baseline_world.append(world0)
            clip_keys.append(key)
            clip_offsets.append(clip_offsets[-1] + len(world))
    report["clipKeys"] = clip_keys
    report["clipOffsets"] = clip_offsets
    report["replayRenderSeconds"] = time.perf_counter() - replay_started
    np.savez_compressed(
        output / "source_wrist_motion.npz",
        localRotation=np.concatenate(all_local),
        jointWorld=np.concatenate(all_world),
        corrections=np.concatenate(all_corr),
        baselineLocalRotation=np.concatenate(all_baseline_local),
        baselineJointWorld=np.concatenate(all_baseline_world),
        clipKeys=np.asarray(clip_keys),
        clipOffsets=np.asarray(clip_offsets, dtype=np.int64),
        anchorVertexIds=anchor_ids,
        anchorRestWorld=anchor,
        ownerRestWorld=owner_origin,
    )
    report["motionArtifactSha256"] = sha256_file(output / "source_wrist_motion.npz")
    report["elapsedSeconds"] = time.perf_counter() - started
    if profile_ownership:
        require_profile_pin(asset, profile_pin)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--mask-dir", type=Path)
    parser.add_argument("--profile-ownership", action="store_true", help="use reviewed physical mask from current pinned preparation, not legacy candidates")
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.asset, args.fit_dir, args.candidate_dir, args.mask_dir, args.annotation, args.owner, args.output, profile_ownership=args.profile_ownership), indent=2))
