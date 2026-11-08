"""Prepare an unskinned angel mesh for open UniRig (no owned-bind, no Meshy bones)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .glb_io import load_mesh, read_glb, write_static_mesh_keep_pbr, write_unskinned_mesh


def write_unirig_yup_unskinned(src: Path, dest: Path) -> dict[str, Any]:
    """Keep Meshy/glTF Y-up vertex space. Strip armature/skin so UniRig does not inherit Bone_*."""
    mesh = load_mesh(src)
    extras = {
        "strippedFrom": str(Path(src).resolve()).replace("\\", "/"),
        "hadSkin": bool(mesh.skin_joints),
        "reorientedYUpToZUp": False,
        "purpose": "open_unirig_input",
    }
    source_doc = read_glb(src)["json"]
    if source_doc.get("images"):
        write_static_mesh_keep_pbr(src, dest, positions=mesh.positions, indices=mesh.indices, extras=extras)
    else:
        write_unskinned_mesh(dest, mesh.positions, mesh.indices, extras=extras)
    return {
        "source": str(Path(src).resolve()).replace("\\", "/"),
        "output": str(Path(dest).resolve()).replace("\\", "/"),
        "vertexCount": int(len(mesh.positions)),
        "hadSkin": bool(mesh.skin_joints),
        "reorientedYUpToZUp": False,
        "keptPbr": bool(source_doc.get("images")),
        "proof": "generated-artifact",
    }
