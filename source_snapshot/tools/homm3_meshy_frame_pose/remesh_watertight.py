#!/usr/bin/env python3
"""Voxel-remesh a triangle-soup GLB into one watertight manifold surface.

Meshy/Blender sculpt exports for HoMM3 units arrive as hundreds of adjacent-but-unconnected index
patches (measured on this repository's own units: the wood elf's 7207 vertices merge to 3796 and its 5567
boundary edges to 47, so the patches are *normal* splits, not holes). This tool voxelizes that surface into
a single closed one, strips UVs (they must be re-transferred later), and exports a watertight GLB.

Whether those split patches need this is settled, and the answer is no for any rule that keys weights on a
vertex's *position* rather than on its patch: two vertices at one point get one set of weights, so the seam
cannot open. Measured with the exact-reference audit on the wood elf, at three clips, merging the duplicates
and nothing else reproduces the strain to the last digit (`docs/homm3_reference_frame_skeleton_binding.md`,
"The mesh's own surface"), and the earlier crusader record reached the same verdict from a fit score
(`crusader_owned_bind_skinned_mesh_handoff.md`: the soup is fine, the weights were the problem). A
*patch-keyed* skinner does separate them, which is the symptom this tool was written for.

So this stays available for a genuinely broken mesh, not as routine mesh prep. What it does buy on an intact
one is smaller and different from strain: its output has zero boundary edges, and its uniformly sampled
surface cuts edges straddling a weight jump from 9% of the mesh to 1% (voxel 0.020 of height) or 0.14%
(0.010). What it costs is detail - it is a resampling - so the voxel size is the whole decision, and the
sweep in that doc is how to pick it.

Run from Blender:
  blender -b --python remesh_watertight.py -- \\
    --mesh <soup.glb> --output <watertight.glb> [--voxel-size 0.0125]

Verify afterwards (in Blender, not on the exported file — glTF export splits
vertices at normal crease seams and that is harmless): 1 component, 0 boundary
edges.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

# Blender cli: everything after '--' is ours.
ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _arg(name: str, default=None):
    for i, a in enumerate(ARGS):
        if a == name and i + 1 < len(ARGS):
            return ARGS[i + 1]
    return default


def main() -> int:
    mesh_path = Path(_arg("--mesh"))
    out_path = Path(_arg("--output"))
    voxel = float(_arg("--voxel-size", "0.0125"))
    if not mesh_path or not out_path:
        print(json.dumps({"ok": False, "error": "need --mesh --output"}), flush=True)
        return 2

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(mesh_path.resolve()))
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    bpy.context.view_layer.objects.active = mesh
    mesh.select_set(True)
    mesh.data.remesh_voxel_size = voxel
    bpy.ops.object.voxel_remesh()

    # Strip UV layers so the glTF export cannot split the surface at seams.
    for uv in list(mesh.data.uv_layers):
        mesh.data.uv_layers.remove(uv)
    mesh.data.update()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out_path.resolve()),
        use_selection=True,
        export_format="GLB",
        export_materials="NONE",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out_path.resolve()),
                "verts": len(mesh.data.vertices),
                "tris": len(mesh.data.polygons),
                "voxelSize": voxel,
                "note": "verify connectivity in Blender (1 component, 0 boundary); glTF export splits at normal crease seams and that is harmless.",
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
