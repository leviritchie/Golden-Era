#!/usr/bin/env python3
"""Validate delivery metadata for the current skin-mesh mocap lane.

This is deliberately separate from the fused-push clip validator.  Current mocap
exports must not acquire a fabricated ``physicsSmooth`` claim merely to satisfy
that older contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "homm3_silhouette_pose_fit"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
if str(ROOT / "experiments" / "homm3_mocap_v2") not in sys.path:
    sys.path.insert(0, str(ROOT / "experiments" / "homm3_mocap_v2"))

from validate_homm3_skinned_clip_pose_contract import _accessor_f4, _read_glb  # noqa: E402
from experiments.homm3_mocap_v2.glb_skeleton import load_bind_skeleton  # noqa: E402
from experiments.homm3_mocap_v2.delivery_style import MOTION_GAIN, PROFILE, policy, validate_derived
from experiments.homm3_mocap_v2.measure_move_stride import measure_move_stride

SCHEMA = "homm3_mocap_v2_delivery_provenance.v1"
ORIENTATION = (0.0, -0.7071067811865476, 0.0, 0.7071067811865476)
WRAPPER_NAMES = {"Orientation", "MocapDeliveryRoot"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_groups(manifest: dict, selected: dict, unit_dir: Path, errors: list[str]) -> None:
    from experiments.homm3_mocap_v2.assemble_ingame_delivery import native_contract_for_raw_group, SOURCE_ONLY_REASON
    try:
        raw_path = _path(manifest["rawManifest"], base=unit_dir)
        if _sha256(raw_path) != manifest["rawManifestSha256"]:
            raise ValueError("raw manifest hash changed")
        matches = [row for row in _load(raw_path)["units"] if row["gameSid"] == selected["gameSid"]]
        if len(matches) != 1:
            raise ValueError("raw manifest game SID mapping is missing or ambiguous")
        prefix = "Crusader" if selected["labSid"] == "h3_crusader" else "Unit"
        expected, native = [], []
        for group in matches[0]["groups"]:
            name = native_contract_for_raw_group(group["groupId"], prefix)
            if name is not None:
                native.append(name)
                continue
            source = _path(group["glb"], base=raw_path.parent).resolve()
            expected.append({"groupId": group["groupId"], "reason": SOURCE_ONLY_REASON,
                             "rawSourceGlb": str(source), "rawSourceGlbSha256": _sha256(source)})
        if manifest.get("sourceOnlyGroups") != expected:
            raise ValueError("source-only groups do not match the pinned raw manifest")
        if sorted(row["contractName"] for row in manifest["clips"]) != sorted(native):
            raise ValueError("native clip set does not match the pinned raw manifest")
    except (ValueError, KeyError, OSError) as exc:
        errors.append(f"{selected.get('labSid')}: raw group coverage invalid: {exc}")


def _path(value: Any, *, base: Path) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate)


def _near(a: list[float], b: tuple[float, ...], tol: float = 1e-6) -> bool:
    return len(a) == len(b) and all(math.isclose(float(x), float(y), abs_tol=tol) for x, y in zip(a, b))


def _orientation_is_live(doc: dict[str, Any]) -> bool:
    nodes = doc.get("nodes") or []
    orientation = next((index for index, node in enumerate(nodes) if node.get("name") == "Orientation"), None)
    if orientation is None:
        return False
    stack = [int(index) for index in (doc.get("scenes") or [{}])[0].get("nodes") or []]
    visited: set[int] = set()
    while stack:
        index = stack.pop()
        if index in visited or index >= len(nodes):
            continue
        visited.add(index)
        if index == orientation:
            return bool(nodes[index].get("children"))
        stack.extend(int(child) for child in nodes[index].get("children") or [])
    return False


def _validate_clip(path: Path, row: dict[str, Any], errors: list[str]) -> None:
    try:
        doc, blob = _read_glb(path)
    except Exception as exc:  # pragma: no cover - parser diagnostics are surfaced
        errors.append(f"{path}: invalid GLB: {exc}")
        return
    animations = doc.get("animations") or []
    if len(animations) != 1:
        errors.append(f"{path}: expected one animation, got {len(animations)}")
        return
    animation = animations[0]
    expected_name = str(row.get("contractName") or "")
    if animation.get("name") != expected_name:
        errors.append(f"{path}: animation name {animation.get('name')!r} != {expected_name!r}")
    orientations = [node for node in doc.get("nodes") or [] if node.get("name") == "Orientation"]
    if len(orientations) != 1 or not _near(list(orientations[0].get("rotation") or []), ORIENTATION) or not _orientation_is_live(doc):
        errors.append(f"{path}: missing canonical -90 degree Orientation node")

    times: list[float] = []
    samplers = animation.get("samplers") or []
    if samplers:
        try:
            times = [float(x[0]) for x in _accessor_f4(doc, blob, samplers[0]["input"])]
        except Exception as exc:
            errors.append(f"{path}: invalid animation timing accessor: {exc}")
    frame_count = int(row.get("frameCount") or 0)
    fps = float(row.get("fps") or 12.0)
    if frame_count <= 0 or fps <= 0:
        errors.append(f"{path}: clip row requires positive frameCount/fps")
    else:
        dt = 1.0 / fps
        role = str(row.get("lifecycleRole") or "")
        # Current mocap preserves the raw sampler exactly.  A cycle closing key is
        # optional and must be validated only when present in the raw source.
        expected_count = frame_count
        expected = [index * dt for index in range(expected_count)]
        if len(times) != expected_count or any(not math.isclose(a, b, abs_tol=1e-5) for a, b in zip(times, expected)):
            errors.append(f"{path}: timing does not match {role or 'non-cycle'} {frame_count} frames at {fps:g} fps")


def _accessor_signature(doc: dict[str, Any], blob: bytes, index: int) -> tuple[Any, ...]:
    accessor = doc["accessors"][int(index)]
    view = doc["bufferViews"][accessor["bufferView"]]
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    item_size = {5121: 1, 5123: 2, 5125: 4, 5126: 4}[int(accessor["componentType"])]
    components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[accessor["type"]]
    size = int(accessor["count"]) * components * item_size
    return (
        int(accessor["componentType"]), accessor["type"], int(accessor["count"]),
        bool(accessor.get("normalized", False)), bytes(blob[start : start + size]),
    )


def _mesh_accessor_indices(doc: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    for mesh in doc.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            if "indices" in primitive:
                indices.add(int(primitive["indices"]))
            indices.update(int(value) for value in (primitive.get("attributes") or {}).values())
    for skin in doc.get("skins") or []:
        if "inverseBindMatrices" in skin:
            indices.add(int(skin["inverseBindMatrices"]))
    return indices


def _node_signature(doc: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    nodes = doc.get("nodes") or []
    by_name: dict[str, tuple[Any, ...]] = {}
    for index, node in enumerate(nodes):
        if node.get("name") in WRAPPER_NAMES:
            continue
        child_names: list[str] = []
        def append_children(index: int) -> None:
            child_node = nodes[index]
            if child_node.get("name") in WRAPPER_NAMES:
                for grandchild in child_node.get("children") or []:
                    append_children(int(grandchild))
            else:
                child_names.append(str(child_node.get("name") or ""))
        for child in node.get("children") or []:
            append_children(int(child))
        children = tuple(child_names)
        fields = {key: value for key, value in node.items() if key not in {"name", "children"}}
        by_name[str(node.get("name") or f"#node{index}")] = (
            json.dumps(fields, sort_keys=True, separators=(",", ":")), children,
        )
    return by_name


def _normalized_scene_roots(doc: dict[str, Any]) -> tuple[str, ...]:
    nodes = doc.get("nodes") or []
    roots: list[str] = []
    def append_root(index: int) -> None:
        node = nodes[index]
        if node.get("name") in WRAPPER_NAMES:
            for child in node.get("children") or []:
                append_root(int(child))
        else:
            roots.append(str(node.get("name") or ""))
    for scene_root in (doc.get("scenes") or [{}])[0].get("nodes") or []:
        append_root(int(scene_root))
    return tuple(roots)


def _mesh_signature(doc: dict[str, Any]) -> str:
    meshes = []
    for mesh in doc.get("meshes") or []:
        row = dict(mesh)
        row["primitives"] = []
        for primitive in mesh.get("primitives") or []:
            item = dict(primitive)
            item.pop("material", None)
            row["primitives"].append(item)
        meshes.append(row)
    return json.dumps(meshes, sort_keys=True, separators=(",", ":"))


def _validate_raw_parity(raw: Path, output: Path, errors: list[str]) -> None:
    try:
        source, source_bin = _read_glb(raw)
        candidate, candidate_bin = _read_glb(output)
    except Exception as exc:
        errors.append(f"{output}: raw parity GLB parse failed: {exc}")
        return
    if _node_signature(source) != _node_signature(candidate) or _normalized_scene_roots(source) != _normalized_scene_roots(candidate):
        errors.append(f"{output}: node transforms/mesh skin topology differ from rawSourceGlb")
    if _mesh_signature(source) != _mesh_signature(candidate):
        errors.append(f"{output}: mesh primitive attributes/indices differ from rawSourceGlb")
    if len(source.get("accessors") or []) != len(candidate.get("accessors") or []):
        errors.append(f"{output}: accessor count differs from rawSourceGlb")
    else:
        for index in range(len(source.get("accessors") or [])):
            if _accessor_signature(source, source_bin, index) != _accessor_signature(candidate, candidate_bin, index):
                errors.append(f"{output}: accessor {index} differs from rawSourceGlb")
                break
    if source.get("skins") != candidate.get("skins"):
        errors.append(f"{output}: skin joints/inverse bind data differ from rawSourceGlb")
    source_animations = source.get("animations") or []
    candidate_animations = candidate.get("animations") or []
    if len(source_animations) != len(candidate_animations):
        errors.append(f"{output}: animation count differs from rawSourceGlb")
        return
    for left, right in zip(source_animations, candidate_animations):
        left_channels = sorted(
             (str((item.get("target") or {}).get("path")), str((source.get("nodes") or [])[int((item.get("target") or {}).get("node", -1))].get("name") or ""),
             str(left["samplers"][int(item["sampler"])].get("interpolation") or "LINEAR"),
             _accessor_signature(source, source_bin, int(left["samplers"][int(item["sampler"])] ["input"])),
             _accessor_signature(source, source_bin, int(left["samplers"][int(item["sampler"])] ["output"])))
            for item in left.get("channels") or []
        )
        right_channels = sorted(
             (str((item.get("target") or {}).get("path")), str((candidate.get("nodes") or [])[int((item.get("target") or {}).get("node", -1))].get("name") or ""),
             str(right["samplers"][int(item["sampler"])].get("interpolation") or "LINEAR"),
             _accessor_signature(candidate, candidate_bin, int(right["samplers"][int(item["sampler"])] ["input"])),
             _accessor_signature(candidate, candidate_bin, int(right["samplers"][int(item["sampler"])] ["output"])))
            for item in right.get("channels") or []
        )
        if left_channels != right_channels:
            errors.append(f"{output}: animation channels/timing/rotation values differ from rawSourceGlb")


def _validate_skin_weights(manifest: dict[str, Any], selected: dict[str, Any], unit_dir: Path,
                           clips: list[dict[str, Any]], errors: list[str]) -> None:
    """Validate the lossless eight-slot sidecar against the delivered raw idle GLB."""
    sid = str(selected.get("labSid") or "")
    row = manifest.get("skinWeights")
    if not isinstance(row, dict):
        errors.append(f"{sid}: manifest skinWeights must be an object")
        return
    path = _path(row.get("path"), base=unit_dir)
    expected = str(row.get("sha256") or "").lower()
    if not path.is_file():
        errors.append(f"{sid}: missing skinWeights sidecar {path}")
        return
    if not expected or _sha256(path) != expected:
        errors.append(f"{sid}: skinWeights sha256 mismatch")
    try:
        sidecar = _load(path)
    except Exception as exc:
        errors.append(f"{sid}: invalid skinWeights sidecar: {exc}")
        return
    if sidecar.get("schema") != "stronghold-current-mocap-skin-sidecar-v1":
        errors.append(f"{sid}: skinWeights sidecar schema mismatch")
    if sidecar.get("sourceReportSha256", "").lower() != str(selected.get("sourceReportSha256") or "").lower():
        errors.append(f"{sid}: skinWeights source report hash does not match selection")
    raw_manifest_sha = str(sidecar.get("rawManifestSha256") or "")
    raw_manifest = _path(sidecar.get("rawManifest"), base=unit_dir)
    if not raw_manifest.is_file() or len(raw_manifest_sha) != 64 or _sha256(raw_manifest) != raw_manifest_sha:
        errors.append(f"{sid}: skinWeights raw manifest path/hash is invalid")
    try:
        vertex_count = int(sidecar["vertexCount"])
        slots = int(sidecar["influenceSlots"])
        if slots != 8:
            raise ValueError("influenceSlots must be 8")
        if len(sidecar["vertices"]) != vertex_count * 3 or len(sidecar["uvs"]) != vertex_count * 2:
            raise ValueError("vertex/UV dimensions differ")
        if len(sidecar["jointIndices"]) != vertex_count * slots or len(sidecar["weights"]) != vertex_count * slots:
            raise ValueError("influence dimensions differ")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"{sid}: invalid skinWeights dimensions: {exc}")
    idle = next((clip for clip in clips if str(clip.get("lifecycleRole") or "").lower() == "idle"), None)
    if idle is None:
        idle = next((clip for clip in clips if "idle" in str(clip.get("contractName") or "").lower()), None)
    if idle is None and clips:
        idle = clips[0]
    if idle is not None:
        raw = _path(idle.get("rawSourceGlb"), base=unit_dir)
        raw_hash = _sha256(raw) if raw.is_file() else ""
        if str(sidecar.get("sourceGlbSha256") or "").lower() != raw_hash.lower():
            errors.append(f"{sid}: skinWeights source GLB is not the delivered raw idle source")
        source_glb = _path(sidecar.get("sourceGlb"), base=unit_dir)
        if source_glb.resolve() != raw.resolve():
            errors.append(f"{sid}: skinWeights sourceGlb path is not the delivered raw idle source")
        if source_glb.is_file():
            try:
                skeleton = load_bind_skeleton(source_glb)
                vertices = np.asarray(sidecar["vertices"], dtype=np.float64).reshape(-1, 3)
                uvs = np.asarray(sidecar["uvs"], dtype=np.float64).reshape(-1, 2)
                triangles = np.asarray(sidecar["triangles"], dtype=np.int64).reshape(-1, 3)
                joints = np.asarray(sidecar["jointIndices"], dtype=np.int64).reshape(-1, 8)
                weights = np.asarray(sidecar["weights"], dtype=np.float64).reshape(-1, 8)
                if skeleton.vertices is None or not np.array_equal(vertices, skeleton.vertices):
                    errors.append(f"{sid}: skinWeights vertices differ from raw idle GLB")
                if skeleton.uvs is None or not np.array_equal(uvs, skeleton.uvs):
                    errors.append(f"{sid}: skinWeights UVs differ from raw idle GLB")
                if skeleton.triangles is None or not np.array_equal(triangles, skeleton.triangles):
                    errors.append(f"{sid}: skinWeights triangles differ from raw idle GLB")
                if skeleton.vertex_joints is None or not np.array_equal(joints, skeleton.vertex_joints):
                    errors.append(f"{sid}: skinWeights joint indices differ from raw idle GLB")
                if skeleton.vertex_weights is None or not np.array_equal(weights, skeleton.vertex_weights):
                    errors.append(f"{sid}: skinWeights values differ from raw idle GLB")
                if list(sidecar.get("jointNames") or []) != list(skeleton.names):
                    errors.append(f"{sid}: skinWeights joint names differ from raw idle GLB")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{sid}: skinWeights raw semantic comparison failed: {exc}")


def _validate_ownership_replay(manifest: dict[str, Any], selected: dict[str, Any], unit_dir: Path,
                               clips: list[dict[str, Any]], errors: list[str]) -> None:
    """Replay source-pinned split pairs on final current-mocap clip GLBs."""
    sid = str(selected.get("labSid") or "")
    try:
        from experiments.homm3_mocap_v2.delivery_ownership import ownership_context, replay_boundaries
        context = ownership_context(selected)
        row = manifest['skinWeights']
        sidecar = _load(_path(row['path'], base=unit_dir))
        ref = sidecar.get('preparedOwnership')
        if context is None:
            if ref is not None:
                raise ValueError('unmasked profile carries unexpected ownership metadata')
            return
        if ref != context['reference']:
            raise ValueError('missing or stale prepared ownership reference')
        for clip in clips:
            output = _path(clip.get("output"), base=unit_dir)
            replay_boundaries(output, context)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        errors.append(f"{sid}: delivered ownership replay failed: {exc}")


def validate(*, rollout_dir: Path, selection_path: Path, unit: str = "") -> list[str]:
    errors: list[str] = []
    try:
        selection = _load(selection_path)
    except Exception as exc:
        return [f"selection JSON invalid: {exc}"]
    if selection.get("schema") != "stronghold-current-mocap-ingame-test-selection-v1":
        errors.append("selection has unexpected schema")
    from experiments.homm3_mocap_v2.structured_profiles import validate_selected_profiles
    errors.extend(validate_selected_profiles([row for row in selection.get("units") or []
                  if isinstance(row, dict) and (not unit or row.get("labSid") == unit)]))
    for selected in selection.get("units") or []:
        if not isinstance(selected, dict):
            errors.append("selection unit row is not an object")
            continue
        sid = str(selected.get("labSid") or "")
        if unit and sid != unit:
            continue
        unit_dir = rollout_dir / "units" / sid
        manifest_path = unit_dir / "delivery_manifest.json"
        if not manifest_path.is_file():
            errors.append(f"{sid}: missing delivery_manifest.json")
            continue
        try:
            manifest = _load(manifest_path)
        except Exception as exc:
            errors.append(f"{sid}: invalid delivery manifest: {exc}")
            continue
        provenance = manifest.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("schema") != SCHEMA:
            errors.append(f"{sid}: missing {SCHEMA} provenance")
            continue
        if provenance.get("motionAuthority") != "current_mocap_v2":
            errors.append(f"{sid}: motionAuthority must be current_mocap_v2")
        if provenance.get("motionInjected") is not False:
            errors.append(f"{sid}: motionInjected must be false")
        if provenance.get("physicsSmoothApplied") is not False:
            errors.append(f"{sid}: physicsSmoothApplied must be false; do not fake cascade metadata")
        style_profile = provenance.get("styleProfile")
        if style_profile is not None or "sourceOnlyGroups" in manifest:
            _validate_source_groups(manifest, selected, unit_dir, errors)
        if style_profile is not None:
            if style_profile != PROFILE or provenance.get("derivedMotionAuthority") != "approved-style-from-current-mocap-v2":
                errors.append(f"{sid}: unsupported derived motion authority")
            if provenance.get("motionGain") != MOTION_GAIN:
                errors.append(f"{sid}: provenance motionGain must be the current approved {MOTION_GAIN}")
            try:
                lighting_path = _path(provenance["lightingManifest"], base=unit_dir)
                if _sha256(lighting_path) != provenance["lightingManifestSha256"]:
                    raise ValueError("lighting manifest hash drift")
                lighting = _load(lighting_path)
                if lighting.get("styleProfile") != PROFILE:
                    raise ValueError("lighting profile mismatch")
                from experiments.homm3_mocap_v2.prepare_ingame_lighting import validate_styled_lighting
                validate_styled_lighting(lighting)
                if lighting["bakedTextureSha256"] != provenance.get("bakedTextureSha256"):
                    raise ValueError("delivery texture differs from approved bake")
            except (ValueError, KeyError, OSError) as exc:
                errors.append(f"{sid}: approved lighting invalid: {exc}")
        for key in ("sourceReportSha256", "corpusSha256"):
            selected_hash = str(selected.get(key) or "").lower()
            if selected_hash and str(provenance.get(key) or "").lower() != selected_hash:
                errors.append(f"{sid}: provenance {key} does not match stronghold_ingame_test selection")
        for key in ("sourceReport", "corpus"):
            source = _path(provenance.get(key), base=ROOT)
            expected = str(provenance.get(key + "Sha256") or "").lower()
            if source.is_dir():
                if key == "corpus" and expected != str(selected.get("corpusSha256") or "").lower():
                    errors.append(f"{sid}: directory corpus identity does not match selection")
                continue
            if not source.is_file():
                errors.append(f"{sid}: provenance {key} missing: {source}")
            elif expected != _sha256(source):
                errors.append(f"{sid}: provenance {key} sha256 mismatch")
        if manifest.get("labSid") != sid:
            errors.append(f"{sid}: manifest labSid mismatch")
        clips = manifest.get("clips")
        if not isinstance(clips, list) or not clips:
            errors.append(f"{sid}: manifest clips must be non-empty")
            continue
        _validate_skin_weights(manifest, selected, unit_dir, clips, errors)
        _validate_ownership_replay(manifest, selected, unit_dir, clips, errors)
        for row in clips:
            if not isinstance(row, dict):
                errors.append(f"{sid}: clip row is not an object")
                continue
            output = _path(row.get("output"), base=unit_dir)
            if not output.is_file():
                errors.append(f"{sid}: missing clip output {output}")
                continue
            raw = _path(row.get("rawSourceGlb"), base=unit_dir)
            expected_raw_sha = str(row.get("rawSourceGlbSha256") or "").lower()
            if not raw.is_file():
                errors.append(f"{sid}: missing rawSourceGlb {raw}")
                continue
            if not expected_raw_sha or _sha256(raw) != expected_raw_sha:
                errors.append(f"{sid}: rawSourceGlb sha256 mismatch for {raw}")
                continue
            authority = raw
            if style_profile is not None:
                try:
                    authority = validate_derived(raw, row["contractName"], row["motionStyle"])
                    expected_fps = 12.0 / policy(row["contractName"])["durationMultiplier"]
                    if not math.isclose(float(row.get("fps", 0)), expected_fps):
                        raise ValueError("derived clip fps does not match approved time mapping")
                except (ValueError, KeyError, OSError) as exc:
                    errors.append(f"{sid}: approved motion invalid: {exc}")
                    continue
            elif "motionStyle" in row:
                errors.append(f"{sid}: styled clip lacks explicit approved profile")
                continue
            _validate_raw_parity(authority, output, errors)
            _validate_clip(output, row, errors)
        move_rows = [row for row in clips if isinstance(row, dict) and str(row.get("contractName") or "").endswith("_Move")]
        if len(move_rows) != 1:
            errors.append(f"{sid}: expected exactly one Move clip for stride measurement")
        else:
            try:
                measured = measure_move_stride(_path(move_rows[0].get("output"), base=unit_dir))
                recorded = manifest.get("battleMoveStride")
                if not isinstance(recorded, dict):
                    raise ValueError("battleMoveStride missing")
                if abs(float(recorded.get("strideBindUnits") or 0) - measured["strideBindUnits"]) > 1e-6:
                    raise ValueError("strideBindUnits does not match the delivered Move GLB")
                if abs(float(recorded.get("cycleSeconds") or 0) - measured["cycleSeconds"]) > 1e-6:
                    raise ValueError("cycleSeconds does not match the delivered Move GLB")
            except (ValueError, KeyError, OSError, TypeError) as exc:
                errors.append(f"{sid}: Move stride invalid: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=ROOT / "experiments/homm3_mocap_v2/stronghold_ingame_test.json")
    args = parser.parse_args()
    errors = validate(rollout_dir=args.rollout_dir.resolve(), selection_path=args.selection.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"HoMM3 current mocap delivery validation passed: {args.rollout_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
