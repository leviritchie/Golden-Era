"""Strip armature/skin and keep mesh + PBR. Reorient Y-up Meshy meshes to Z-up."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .glb_io import (
    load_mesh,
    read_glb,
    should_reorient_y_up,
    write_static_mesh_keep_pbr,
    write_unskinned_mesh,
    y_up_to_z_up,
)


def strip_armature(src: Path, dest: Path) -> dict[str, Any]:
    mesh = load_mesh(src)
    positions = mesh.positions.copy()
    reoriented = False
    if should_reorient_y_up(positions):
        positions = y_up_to_z_up(positions)
        reoriented = True
    extras = {
        "strippedFrom": str(Path(src).resolve()).replace("\\", "/"),
        "hadSkin": bool(mesh.skin_joints),
        "reorientedYUpToZUp": reoriented,
    }
    source_doc = read_glb(src)["json"]
    if source_doc.get("images"):
        write_static_mesh_keep_pbr(src, dest, positions=positions, indices=mesh.indices, extras=extras)
    else:
        write_unskinned_mesh(dest, positions, mesh.indices, extras=extras)
    return {
        "source": str(Path(src).resolve()).replace("\\", "/"),
        "output": str(Path(dest).resolve()).replace("\\", "/"),
        "vertexCount": int(len(positions)),
        "hadSkin": bool(mesh.skin_joints),
        "reorientedYUpToZUp": reoriented,
        "keptPbr": bool(source_doc.get("images")),
        "proof": "generated-artifact",
    }
