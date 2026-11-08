#!/usr/bin/env python3
"""Render one fitted pose with rigid owner colors for semantic review."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import bpy

TOOL = Path(__file__).resolve().parents[1] / "homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402
from render_fixed_length_lit_60fps import (  # noqa: E402
    _apply_captured_pose,
    _clear_pose,
    _disable_inherit_scale,
    _setup_lit_scene,
)

PALETTE = {
    "Head": (0.92, 0.12, 0.12, 1.0),
    "neck": (1.0, 0.45, 0.05, 1.0),
    "Spine": (1.0, 0.82, 0.05, 1.0),
    "Spine01": (0.2, 0.82, 0.15, 1.0),
    "Spine02": (0.05, 0.72, 0.75, 1.0),
    "Hips": (0.1, 0.35, 0.95, 1.0),
    "LeftShoulder": (0.7, 0.15, 0.9, 1.0),
    "LeftArm": (0.45, 0.1, 0.65, 1.0),
    "LeftForeArm": (0.25, 0.05, 0.45, 1.0),
    "LeftHand": (0.1, 0.02, 0.25, 1.0),
    "RightShoulder": (0.1, 0.75, 0.35, 1.0),
    "RightArm": (0.05, 0.55, 0.2, 1.0),
    "RightForeArm": (0.02, 0.35, 0.12, 1.0),
    "RightHand": (0.01, 0.18, 0.05, 1.0),
    "RightWeaponTip": (0.95, 0.05, 0.7, 1.0),
    "LeftUpLeg": (0.1, 0.45, 0.95, 1.0),
    "LeftLeg": (0.05, 0.2, 0.65, 1.0),
    "LeftFoot": (0.02, 0.08, 0.35, 1.0),
    "RightUpLeg": (0.95, 0.35, 0.05, 1.0),
    "RightLeg": (0.7, 0.15, 0.02, 1.0),
    "RightFoot": (0.4, 0.05, 0.01, 1.0),
}


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", required=True, type=Path)
    ap.add_argument("--frame-index", required=True, type=int)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--highlight-owner", default="", help="Render only this owner in saturated red; gray all others")
    ap.add_argument("--highlight-component", type=int, nargs="*", default=[], help="Render these connected component ids in saturated red")
    ap.add_argument("--report-owner", default="", help="Print posed screen-space bounds for components owned by this bone")
    ap.add_argument("--report-out", type=Path, default=None, help="Also write the owner component report as JSON")
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])


def _material(name: str, color: tuple[float, float, float, float]):
    mat = bpy.data.materials.new("OwnerDebug_" + name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = color
    if bsdf.inputs.get("Emission") is not None:
        bsdf.inputs["Emission"].default_value = color
    if bsdf.inputs.get("Emission Strength") is not None:
        bsdf.inputs["Emission Strength"].default_value = 0.35
    bsdf.inputs["Roughness"].default_value = 0.78
    return mat


def main() -> int:
    args = _args()
    fit_dir = args.fit_dir.resolve()
    job = json.loads((fit_dir / "job.resolved.json").read_text(encoding="utf-8"))
    report = json.loads((fit_dir / "fit_report.json").read_text(encoding="utf-8"))
    poses = report.get("poseSnapshots") or []
    if not 0 <= args.frame_index < len(poses):
        raise SystemExit(f"frame-index {args.frame_index} outside pose snapshot count {len(poses)}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"]).resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    if arm.animation_data:
        arm.animation_data_clear()
    _disable_inherit_scale(arm)
    _clear_pose(arm)
    _setup_lit_scene()
    setup_pose_camera(job, arm, bpy_module=bpy)
    _apply_captured_pose(arm, poses[args.frame_index])

    groups = {group.index: group.name for group in mesh.vertex_groups}
    if args.highlight_component:
        mats = {name: _material(name, (0.24, 0.24, 0.27, 1.0)) for name in PALETTE}
    elif args.highlight_owner:
        mats = {
            name: _material(name, (0.95, 0.03, 0.03, 1.0) if name == args.highlight_owner else (0.24, 0.24, 0.27, 1.0))
            for name in PALETTE
        }
    else:
        mats = {name: _material(name, color) for name, color in PALETTE.items()}
    for mat in mats.values():
        mesh.data.materials.append(mat)
    counts = Counter()
    debug_materials = {}
    selected_polygons = 0
    parent = list(range(len(mesh.data.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for poly in mesh.data.polygons:
        if len(poly.vertices) >= 2:
            first = poly.vertices[0]
            for vertex_index in poly.vertices[1:]:
                union(first, vertex_index)
    roots = {}
    component_by_vertex = {}
    for vertex_index in range(len(mesh.data.vertices)):
        root = find(vertex_index)
        if root not in roots:
            roots[root] = len(roots)
        component_by_vertex[vertex_index] = roots[root]

    if args.report_owner:
        from bpy_extras.object_utils import world_to_camera_view

        component_vertices = defaultdict(list)
        component_owners = defaultdict(Counter)
        for vertex_index, component_id in component_by_vertex.items():
            vertex = mesh.data.vertices[vertex_index]
            component_vertices[component_id].append(vertex_index)
            if vertex.groups:
                strongest = max(vertex.groups, key=lambda group: group.weight)
                component_owners[component_id][groups.get(strongest.group, "UNOWNED")] += 1

        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated_mesh = mesh.evaluated_get(depsgraph)
        evaluated_data = evaluated_mesh.to_mesh()
        try:
            records = []
            for component_id, vertex_indices in component_vertices.items():
                owner = component_owners[component_id].most_common(1)[0][0] if component_owners[component_id] else "UNOWNED"
                if owner != args.report_owner:
                    continue
                projected = [world_to_camera_view(bpy.context.scene, bpy.context.scene.camera, evaluated_mesh.matrix_world @ evaluated_data.vertices[vi].co) for vi in vertex_indices]
                records.append({
                    "component": component_id,
                    "triangles": sum(1 for poly in mesh.data.polygons if component_by_vertex[poly.vertices[0]] == component_id),
                    "owner": owner,
                    "screenMin": [min(float(point.x) for point in projected), min(float(point.y) for point in projected)],
                    "screenMax": [max(float(point.x) for point in projected), max(float(point.y) for point in projected)],
                })
            report_doc = {"reportOwner": args.report_owner, "components": sorted(records, key=lambda row: (row["screenMin"][1], row["screenMin"][0]))}
            if args.report_out is not None:
                args.report_out.parent.mkdir(parents=True, exist_ok=True)
                args.report_out.write_text(json.dumps(report_doc, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report_doc, indent=2))
        finally:
            evaluated_mesh.to_mesh_clear()

    for poly in mesh.data.polygons:
        owners = []
        for vi in poly.vertices:
            vertex = mesh.data.vertices[vi]
            if not vertex.groups:
                owners.append("UNOWNED")
            else:
                strongest = max(vertex.groups, key=lambda group: group.weight)
                owners.append(groups.get(strongest.group, "UNOWNED"))
        owner = Counter(owners).most_common(1)[0][0]
        counts[owner] += 1
        if owner not in mats:
            mats[owner] = _material(owner, (0.6, 0.6, 0.6, 1.0))
            mesh.data.materials.append(mats[owner])
        if args.highlight_component:
            color = (0.95, 0.03, 0.03, 1.0) if component_by_vertex[poly.vertices[0]] in args.highlight_component else (0.24, 0.24, 0.27, 1.0)
            component_id = component_by_vertex[poly.vertices[0]]
            material_key = (component_id, color)
            if material_key not in debug_materials:
                debug_materials[material_key] = _material("Component_" + str(component_id), color)
                mesh.data.materials.append(debug_materials[material_key])
            poly.material_index = list(mesh.data.materials).index(debug_materials[material_key])
            if component_id in args.highlight_component:
                selected_polygons += 1
        else:
            poly.material_index = list(mesh.data.materials).index(mats[owner])

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.out.resolve())
    bpy.ops.render.render(write_still=True)
    args.out.with_suffix(".json").write_text(
        json.dumps({"frameIndex": args.frame_index, "ownerTriangleCounts": dict(counts)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "out": str(args.out).replace("\\", "/"), "frameIndex": args.frame_index, "componentCount": len(roots), "selectedPolygons": selected_polygons}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
