"""Load owned-bind species templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "owned_bind_species_template.v1"
TEMPLATES = Path(__file__).resolve().parents[1] / "species_templates"


def load_species_template(species: str, *, templates_dir: Path | None = None) -> dict[str, Any]:
    root = Path(templates_dir) if templates_dir is not None else TEMPLATES
    path = root / f"{species}.json"
    if not path.is_file():
        raise FileNotFoundError(f"species template missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"unsupported species template schema in {path}")
    if payload.get("species") != species:
        raise ValueError(f"template species {payload.get('species')!r} does not match {species!r}")
    bones = payload.get("bones")
    if not isinstance(bones, list) or not bones:
        raise ValueError(f"species template has no bones: {path}")
    names = []
    for bone in bones:
        name = str(bone.get("name") or "")
        if not name or name in names:
            raise ValueError(f"duplicate or empty bone name in {path}: {name!r}")
        names.append(name)
        parent = bone.get("parent")
        if parent is not None and parent not in names and parent != name:
            # parent must already appear (roots first)
            if parent not in {str(b.get("name")) for b in bones}:
                raise ValueError(f"bone {name} parent {parent} is not in template")
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError(f"species template has no parts: {path}")
    part_set = {str(item) for item in parts}
    walls = payload.get("skinWalls")
    if not isinstance(walls, dict) or set(walls) != part_set:
        raise ValueError(f"skinWalls keys must match parts in {path}")
    for bone in bones:
        part = str(bone.get("part") or "")
        if part not in part_set:
            raise ValueError(f"bone {bone.get('name')} part {part!r} is not in parts")
    return payload


def required_bone_names(template: dict[str, Any]) -> list[str]:
    return [str(bone["name"]) for bone in template["bones"]]


def _required_bone_names_impl(template: dict[str, Any]) -> list[str]:
    return [str(bone["name"]) for bone in template["bones"]]


def parent_index_list(template: dict[str, Any]) -> list[int | None]:
    names = required_bone_names(template)
    index = {name: i for i, name in enumerate(names)}
    out: list[int | None] = []
    for bone in template["bones"]:
        parent = bone.get("parent")
        out.append(None if parent is None else index[str(parent)])
    return out


load_species_template = load_species_template
required_bone_names = required_bone_names
parent_index_list = parent_index_list
