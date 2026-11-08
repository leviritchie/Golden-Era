#!/usr/bin/env python3
"""Preserve a Meshy auto-rig while rigidizing high-confidence mesh regions.

This is a post-rig correction pass.  It never creates a replacement armature:
the imported Meshy armature, hierarchy, names, and rest transforms remain the
authority.  Regions whose existing weights provide a decisive owner are
rewritten to one Meshy bone.  Mixed regions are left alone, and ambiguous
rigid-like regions fail closed by default.

Run through the host wrapper so the Blender executable is explicit:

  py -3 tools/homm3_silhouette_pose_fit/run_meshy_rigidization.py -- \
    --src artifacts/.../idle_f0_rigged.glb \
    --out artifacts/.../idle_f0_rigged_rigidized.glb \
    --report artifacts/.../meshy_rigidization_report.json

The output is a generated artifact.  The report includes a re-import audit of
the exported GLB; it does not by itself prove Unity runtime behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from meshy_rigidization_core import (  # noqa: E402
    REPORT_SCHEMA,
    RigidizationConfig,
    armature_signature_diffs,
    classify_component,
    component_stats,
    connected_components,
    with_mesh_fraction,
)


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-ambiguous",
        action="store_true",
        help="Diagnostic escape hatch; never use this for batch delivery.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(_argv())


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config(path: Path | None) -> RigidizationConfig:
    if path is None:
        return RigidizationConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RigidizationConfig.from_mapping(raw)


def _armature_signature(armature) -> list[dict[str, Any]]:
    return [
        {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": [float(value) for value in bone.head_local],
            "tail": [float(value) for value in bone.tail_local],
        }
        for bone in armature.data.bones
    ]


def _mesh_objects_for_armature(armature) -> list[Any]:
    result = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
        if any(modifier.object is armature for modifier in modifiers) or obj.parent is armature:
            result.append(obj)
    return sorted(result, key=lambda obj: obj.name)


def _find_meshy_armature() -> tuple[Any, list[Any]]:
    candidates = []
    for armature in (obj for obj in bpy.data.objects if obj.type == "ARMATURE"):
        meshes = _mesh_objects_for_armature(armature)
        if meshes:
            candidates.append((armature, meshes))
    if len(candidates) != 1:
        details = [(arm.name, len(meshes), len(arm.data.bones)) for arm, meshes in candidates]
        raise RuntimeError(
            "expected exactly one armature with associated skinned meshes; "
            f"found {len(candidates)}: {details}"
        )
    return candidates[0]


def _weight_map(mesh_obj, vertex, armature_bones: set[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for group_ref in vertex.groups:
        group = mesh_obj.vertex_groups[group_ref.group]
        if group.name not in armature_bones:
            continue
        value = float(group_ref.weight)
        if value > 0.0:
            weights[group.name] = weights.get(group.name, 0.0) + value
    return weights


def _dominant(weights: dict[str, float], epsilon: float) -> tuple[str | None, float]:
    positive = [(name, float(value)) for name, value in weights.items() if value > epsilon]
    if not positive:
        return None, 0.0
    positive.sort(key=lambda pair: (-pair[1], pair[0]))
    total = sum(value for _, value in positive)
    return positive[0][0], positive[0][1] / total if total else 0.0


def _material_ids(mesh_obj) -> list[int]:
    ids = [-1] * len(mesh_obj.data.vertices)
    for polygon in mesh_obj.data.polygons:
        material = int(polygon.material_index)
        for vertex_index in polygon.vertices:
            if ids[vertex_index] < 0:
                ids[vertex_index] = material
            else:
                ids[vertex_index] = min(ids[vertex_index], material)
    return [0 if value < 0 else value for value in ids]


def _segment_distance(point: Vector, head: Vector, tail: Vector) -> float:
    direction = tail - head
    length_squared = direction.length_squared
    if length_squared <= 1e-12:
        return float((point - head).length)
    t = max(0.0, min(1.0, float((point - head).dot(direction) / length_squared)))
    return float((point - (head + direction * t)).length)


def _bone_segment_map(armature) -> dict[str, tuple[Vector, Vector]]:
    return {
        bone.name: (
            armature.matrix_world @ bone.head_local,
            armature.matrix_world @ bone.tail_local,
        )
        for bone in armature.data.bones
    }


def _classify_mesh(mesh_obj, armature, config: RigidizationConfig) -> dict[str, Any]:
    bone_names = {bone.name for bone in armature.data.bones}
    vertex_count = len(mesh_obj.data.vertices)
    weights = [_weight_map(mesh_obj, vertex, bone_names) for vertex in mesh_obj.data.vertices]
    positions = [tuple(float(value) for value in (mesh_obj.matrix_world @ vertex.co)) for vertex in mesh_obj.data.vertices]
    materials = _material_ids(mesh_obj)
    labels: list[str | None] = []
    top_values: list[float] = []
    for vertex_weights in weights:
        name, top = _dominant(vertex_weights, config.weight_epsilon)
        labels.append(name)
        top_values.append(top)
    edges = [tuple(int(value) for value in edge.vertices) for edge in mesh_obj.data.edges]
    regions = connected_components(
        vertex_count,
        edges,
        labels=labels,
        seed_top_weights=top_values,
        min_seed_top_weight=config.seed_min_top_weight,
    )
    bone_segments = _bone_segment_map(armature)
    decisions = []
    frozen_vertices: set[int] = set()
    ambiguous_count = 0
    for component_id, indices in enumerate(regions):
        stats = with_mesh_fraction(
            component_stats(
                component_id,
                indices,
                weights,
                positions,
                materials,
                epsilon=config.weight_epsilon,
            ),
            vertex_count,
        )
        decision = classify_component(stats, config)
        if decision.classification == "freeze_rigid_candidate":
            frozen_vertices.update(indices)
        elif decision.classification == "ambiguous_rigid_candidate":
            ambiguous_count += 1
        owner_distance = None
        if decision.owner_bone and decision.owner_bone in bone_segments:
            head, tail = bone_segments[decision.owner_bone]
            owner_distance = _segment_distance(Vector(stats.centroid), head, tail)
        decisions.append(
            {
                "componentId": component_id,
                "vertexIndices": [int(index) for index in indices],
                "stats": asdict(stats),
                "classification": decision.classification,
                "ownerBone": decision.owner_bone,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "ownerSegmentDistance": owner_distance,
            }
        )
    return {
        "object": mesh_obj,
        "meshName": mesh_obj.name,
        "weights": weights,
        "positions": positions,
        "regions": decisions,
        "frozenVertices": sorted(frozen_vertices),
        "ambiguousCount": ambiguous_count,
        "vertexCount": vertex_count,
    }


def _clear_vertex_groups(mesh_obj, vertex_index: int) -> None:
    vertex = mesh_obj.data.vertices[vertex_index]
    for group_ref in list(vertex.groups):
        mesh_obj.vertex_groups[group_ref.group].remove([vertex_index])


def _apply_rigid_regions(classification: dict[str, Any], armature, config: RigidizationConfig) -> int:
    mesh_obj = classification["object"]
    applied = 0
    for region in classification["regions"]:
        if region["classification"] != "freeze_rigid_candidate":
            continue
        owner = region["ownerBone"]
        if not owner or armature.data.bones.get(owner) is None:
            raise RuntimeError(f"rigid region has missing Meshy owner bone: {owner!r}")
        group = mesh_obj.vertex_groups.get(owner)
        if group is None:
            group = mesh_obj.vertex_groups.new(name=owner)
        for vertex_index in region["vertexIndices"]:
            _clear_vertex_groups(mesh_obj, vertex_index)
            group.add([vertex_index], 1.0, "REPLACE")
            applied += 1
    return applied


def _select_export_objects(armature, meshes: list[Any]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature


def _export_scene(out: Path, armature, meshes: list[Any]) -> None:
    _select_export_objects(armature, meshes)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_skins=True,
        export_all_influences=True,
        export_apply=False,
        export_morph=False,
    )
    if not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError(f"Blender did not write a usable rigidized GLB: {out}")


def _vertex_owner_weights(mesh_obj, vertex_index: int, armature_bones: set[str]) -> dict[str, float]:
    return _weight_map(mesh_obj, mesh_obj.data.vertices[vertex_index], armature_bones)


def _audit_reimport(
    source_armature_signature: list[dict[str, Any]],
    source_mesh_signatures: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
    config: RigidizationConfig,
    source_action_count: int,
) -> dict[str, Any]:
    armature, meshes = _find_meshy_armature()
    output_signature = _armature_signature(armature)
    armature_diffs = armature_signature_diffs(source_armature_signature, output_signature)
    if armature_diffs:
        raise RuntimeError(
            "rigidization changed the Meshy armature hierarchy or rest transforms: "
            + "; ".join(armature_diffs[:8])
        )
    by_name = {mesh.name: mesh for mesh in meshes}
    output_mesh_rows = []
    for source_row in source_mesh_signatures:
        name = source_row["name"]
        mesh = by_name.get(name)
        if mesh is None:
            raise RuntimeError(f"rigidization export lost Meshy mesh object {name!r}")
        if len(mesh.data.vertices) < source_row["vertexCount"]:
            raise RuntimeError(
                f"mesh {name!r} lost vertices during export: source={source_row['vertexCount']} "
                f"output={len(mesh.data.vertices)}"
            )
        output_mesh_rows.append(
            {
                "name": name,
                "sourceVertexCount": source_row["vertexCount"],
                "outputVertexCount": len(mesh.data.vertices),
                "vertexCountChangedByAttributeSplits": len(mesh.data.vertices) != source_row["vertexCount"],
            }
        )

    bone_names = {bone.name for bone in armature.data.bones}
    expected_by_owner: dict[tuple[str, str], int] = {}
    for classification in classifications:
        mesh_name = classification["meshName"]
        for region in classification["regions"]:
            if region["classification"] != "freeze_rigid_candidate":
                continue
            owner = region["ownerBone"]
            if owner is None:
                raise RuntimeError("accepted rigid region has no owner bone")
            key = (mesh_name, owner)
            expected_by_owner[key] = expected_by_owner.get(key, 0) + len(region["vertexIndices"])

    owner_rows = []
    violations = []
    for (mesh_name, owner), expected_count in sorted(expected_by_owner.items()):
        mesh = by_name[mesh_name]
        observed_count = 0
        max_other_for_owner = 0.0
        for vertex in mesh.data.vertices:
            weights = _weight_map(mesh, vertex, bone_names)
            owner_weight = float(weights.get(owner, 0.0))
            other_weight = max(
                (value for name, value in weights.items() if name != owner),
                default=0.0,
            )
            if owner_weight >= 1.0 - config.audit_weight_tolerance and other_weight <= config.audit_weight_tolerance:
                observed_count += 1
            if owner_weight >= 1.0 - config.audit_weight_tolerance:
                max_other_for_owner = max(max_other_for_owner, other_weight)
        row = {
            "mesh": mesh_name,
            "ownerBone": owner,
            "expectedRigidVertexCount": expected_count,
            "observedSingleOwnerVertexCount": observed_count,
            "maxOtherWeightOnOwnerVertices": max_other_for_owner,
            "attributeSplitSafe": observed_count >= expected_count,
        }
        owner_rows.append(row)
        if observed_count < expected_count:
            violations.append(row)
    if violations:
        raise RuntimeError(f"exported rigid regions lost single-owner coverage: {violations[:3]}")
    output_action_count = len(bpy.data.actions)
    if output_action_count < source_action_count:
        raise RuntimeError(
            f"rigidization export lost Meshy actions: source={source_action_count} output={output_action_count}"
        )
    return {
        "armatureUnchanged": True,
        "meshObjectsUnchanged": True,
        "rigidOwnerRows": owner_rows,
        "singleOwnerViolations": violations,
        "outputMeshes": output_mesh_rows,
        "sourceActionCount": source_action_count,
        "outputActionCount": output_action_count,
    }


def _load_scene(src: Path, *, bone_heuristic: str | None = None) -> tuple[Any, list[Any]]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_kwargs: dict[str, Any] = {"filepath": str(src)}
    if bone_heuristic is not None:
        # Meshy/UniRig sources use the importer default (TEMPERANCE).  The
        # audited output was just exported from Blender, so re-import it with
        # the Blender bone heuristic.  TEMPERANCE reconstructs leaf/ambiguous
        # tails from children and can fail the rest-transform audit even when
        # joint heads, hierarchy, and skinning are unchanged.
        import_kwargs["bone_heuristic"] = bone_heuristic
    bpy.ops.import_scene.gltf(**import_kwargs)
    return _find_meshy_armature()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    src = _resolve(args.src).resolve()
    out = _resolve(args.out).resolve()
    report_path = _resolve(args.report).resolve()
    config_path = _resolve(args.config).resolve() if args.config else None
    if not src.is_file():
        raise FileNotFoundError(src)
    if src == out:
        raise ValueError("--out must differ from --src; the Meshy source is never overwritten")
    if out.exists() and not args.overwrite and not args.dry_run:
        raise FileExistsError(f"output exists; pass --overwrite to replace it: {out}")
    config = _load_config(config_path)
    source_hash = _sha256(src) if config.audit_source_hash else None

    armature, meshes = _load_scene(src)
    source_signature = _armature_signature(armature)
    source_action_count = len(bpy.data.actions)
    source_mesh_signatures = [
        {
            "name": mesh.name,
            "vertexCount": len(mesh.data.vertices),
            "vertexGroupNames": sorted(group.name for group in mesh.vertex_groups),
        }
        for mesh in meshes
    ]
    classifications = []
    total_applied = 0
    total_ambiguous = 0
    for mesh in meshes:
        classification = _classify_mesh(mesh, armature, config)
        classifications.append(classification)
        total_ambiguous += int(classification["ambiguousCount"])
    if total_ambiguous > config.max_ambiguous_parts and not args.allow_ambiguous:
        raise RuntimeError(
            f"rigidization found {total_ambiguous} ambiguous rigid-like regions; "
            f"max_ambiguous_parts={config.max_ambiguous_parts}. "
            "Inspect the report or explicitly use --allow-ambiguous for diagnostics."
        )
    for classification in classifications:
        total_applied += _apply_rigid_regions(classification, armature, config)
    bpy.context.view_layer.update()

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "dry_run" if args.dry_run else "processing",
        "source": str(src).replace("\\", "/"),
        "output": str(out).replace("\\", "/"),
        "sourceSha256": source_hash,
        "config": config.to_dict(),
        "configPath": str(config_path).replace("\\", "/") if config_path else None,
        "armatureAuthority": "meshy_auto_rig",
        "armature": armature.name,
        "armatureBoneSignature": source_signature,
        "sourceMeshSignatures": source_mesh_signatures,
        "allowAmbiguous": bool(args.allow_ambiguous),
        "ambiguousRegionCount": total_ambiguous,
        "frozenVertexCount": total_applied,
        "meshes": [
            {
                "name": classification["meshName"],
                "vertexCount": classification["vertexCount"],
                "regions": classification["regions"],
            }
            for classification in classifications
        ],
        "proof": "generated artifact validated after Blender export and re-import; Meshy runtime not proven",
    }
    if args.dry_run:
        report["status"] = "dry_run"
        return report

    _export_scene(out, armature, meshes)
    output_hash = _sha256(out)
    _load_scene(out, bone_heuristic="BLENDER")
    reimport_audit = _audit_reimport(
        source_signature,
        source_mesh_signatures,
        classifications,
        config,
        source_action_count,
    )
    report["outputSha256"] = output_hash
    report["reimportAudit"] = reimport_audit
    report["status"] = "pass"
    return report


def main() -> int:
    args = _parse()
    report_path = _resolve(args.report).resolve()
    try:
        report = run(args)
        _write_report(report_path, report)
        print(json.dumps({"ok": report["status"] in {"pass", "dry_run"}, "report": str(report_path), "status": report["status"]}, indent=2))
        return 0
    except Exception as exc:
        failure = {
            "schema": REPORT_SCHEMA,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "proof": "no accepted rigidized artifact",
        }
        _write_report(report_path, failure)
        print(json.dumps({"ok": False, "report": str(report_path), "error": failure["error"]}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
