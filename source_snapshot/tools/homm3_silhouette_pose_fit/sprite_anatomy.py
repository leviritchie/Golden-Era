"""Authored anatomical labels for sprite-feasibility surgery.

Bone names on Meshy smartrigs are not anatomy. Surgery must read a unit
catalog instead of guessing tail/head from Bone_* index lists or belly from
a world-Y cut. Missing labels fail closed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

TOOLS = Path(__file__).resolve().parent

ANATOMY_CATALOG_BY_UNIT = {
    "h3_roc": TOOLS / "roc_smartrig_anatomy_groups.json",
    "h3_hobgoblin": TOOLS / "hobgoblin_smartrig_anatomy_groups.json",
    "h3_behemoth": TOOLS / "behemoth_smartrig_anatomy_groups.json",
    "h3_thunderbird": TOOLS / "thunderbird_smartrig_anatomy_groups.json",
    "h3_ancient_behemoth": TOOLS / "ancient_behemoth_smartrig_anatomy_groups.json",
}


def _bootstrap_anatomy_path(unit: str) -> Path | None:
    sid = str(unit)
    candidates = (
        TOOLS / f"{sid}_smartrig_anatomy_groups.json",
        TOOLS / f"{sid.replace('h3_', '')}_smartrig_anatomy_groups.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None

FLYER_REQUIRED_LANDMARKS = ("tailTip", "headTip", "keel")
FLYER_ATTITUDE_GROUPS = ("trunk", "neck_head", "tail")
FLYER_WING_GROUPS = ("wing_a", "wing_b")
QUADRUPED_REQUIRED_LANDMARKS = ("tailTip", "headTip", "keel")
HUMANOID_REQUIRED_LANDMARKS = ("head", "weaponTip")


def load_unit_anatomy_catalog(unit: str, *, tools_dir: Path | None = None) -> dict[str, Any]:
    sid = str(unit)
    root = Path(tools_dir) if tools_dir is not None else TOOLS
    relative = ANATOMY_CATALOG_BY_UNIT.get(sid)
    if relative is None:
        boot = _bootstrap_anatomy_path(sid)
        if boot is None:
            raise ValueError(f"no anatomy catalog registered for unit {sid!r}")
        relative = boot
    path = root / Path(relative).name if tools_dir is not None else Path(relative)
    if not path.is_file():
        raise ValueError(f"anatomy catalog missing: {path}")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if str(catalog.get("unitSid") or "") != sid:
        raise ValueError(f"anatomy catalog unitSid {catalog.get('unitSid')!r} != {sid!r}")
    validate_anatomy_catalog(catalog)
    catalog["_path"] = str(path.resolve()).replace("\\", "/")
    return catalog


def validate_anatomy_catalog(catalog: Mapping[str, Any]) -> None:
    groups = catalog.get("groups")
    if not isinstance(groups, Mapping) or not groups:
        raise ValueError("anatomy catalog needs non-empty groups")
    for name, entry in groups.items():
        bones = list(entry.get("bonesDependencyOrder") or ())
        if not bones:
            raise ValueError(f"anatomy group {name!r} has no bonesDependencyOrder")
    landmarks = catalog.get("landmarks")
    if not isinstance(landmarks, Mapping) or not landmarks:
        raise ValueError("anatomy catalog needs landmarks")
    species = str(catalog.get("species") or "")
    if species == "flyer":
        required = FLYER_REQUIRED_LANDMARKS
    elif species == "quadruped":
        required = QUADRUPED_REQUIRED_LANDMARKS
    else:
        required = HUMANOID_REQUIRED_LANDMARKS
    missing = [name for name in required if not str(landmarks.get(name) or "")]
    if missing:
        raise ValueError(f"anatomy catalog missing landmarks {missing} for species {species!r}")
    if species == "flyer":
        anatomy_ventral_bind_axis(catalog)
        for group in (*FLYER_ATTITUDE_GROUPS, *FLYER_WING_GROUPS):
            anatomy_group_bones(catalog, group)
        anatomy_bilateral_wing_pair(catalog)
    elif species == "quadruped":
        anatomy_ventral_bind_axis(catalog)
        for group in ("trunk", "neck_head", "tail", "leg_a", "leg_b"):
            anatomy_group_bones(catalog, group)


def anatomy_landmark_bone(catalog: Mapping[str, Any], name: str) -> str:
    landmarks = catalog.get("landmarks")
    if not isinstance(landmarks, Mapping):
        raise ValueError("anatomy catalog needs landmarks")
    bone = str(landmarks.get(name) or "")
    if not bone:
        raise ValueError(f"anatomy catalog has no landmark {name!r}")
    return bone


def anatomy_group_bones(catalog: Mapping[str, Any], group: str) -> list[str]:
    groups = catalog.get("groups")
    if not isinstance(groups, Mapping):
        raise ValueError("anatomy catalog needs groups")
    entry = groups.get(str(group))
    if not isinstance(entry, Mapping):
        raise ValueError(f"anatomy catalog has no group {group!r}")
    bones = [str(bone) for bone in (entry.get("bonesDependencyOrder") or ())]
    if not bones:
        raise ValueError(f"anatomy group {group!r} has no bonesDependencyOrder")
    return bones


def anatomy_ventral_bind_axis(catalog: Mapping[str, Any]) -> np.ndarray:
    axes = catalog.get("bindAxes")
    if not isinstance(axes, Mapping):
        raise ValueError("flyer anatomy catalog needs bindAxes.ventral")
    raw = axes.get("ventral")
    axis = np.asarray(raw, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError("bindAxes.ventral must be a non-zero 3-vector")
    return axis / length


def anatomy_visual_body_chain(catalog: Mapping[str, Any], names: Sequence[str]) -> list[str]:
    """Tail tip to head tip from authored landmarks. Not a parent-chain walk."""
    labels = {str(name) for name in names}
    tail = anatomy_landmark_bone(catalog, "tailTip")
    head = anatomy_landmark_bone(catalog, "headTip")
    missing = [name for name in (tail, head) if name not in labels]
    if missing:
        raise ValueError(f"anatomy landmarks not on skeleton: {missing}")
    if tail == head:
        raise ValueError("tailTip and headTip must be distinct bones")
    return [tail, head]


def anatomy_attitude_bones(catalog: Mapping[str, Any], names: Sequence[str]) -> list[str]:
    """Trunk, neck, and tail. Wings are leftover fill, not body attitude."""
    labels = {str(name) for name in names}
    ordered: list[str] = []
    for group in FLYER_ATTITUDE_GROUPS:
        for bone in anatomy_group_bones(catalog, group):
            if bone in labels and bone not in ordered:
                ordered.append(bone)
    if not ordered:
        raise ValueError("anatomy attitude groups mapped to no skeleton bones")
    return ordered


def anatomy_wing_chain(catalog: Mapping[str, Any], group: str, names: Sequence[str]) -> list[str]:
    labels = {str(name) for name in names}
    bones = [bone for bone in anatomy_group_bones(catalog, group) if bone in labels]
    if len(bones) < 2:
        raise ValueError(f"anatomy wing group {group!r} needs proximal and distal bones on the skeleton")
    return bones


def anatomy_bilateral_pairs(catalog: Mapping[str, Any]) -> list[tuple[str, str]]:
    symmetry = catalog.get("symmetry")
    if not isinstance(symmetry, Mapping):
        raise ValueError("flyer anatomy catalog needs symmetry.bilateralGroupPairs")
    pairs: list[tuple[str, str]] = []
    for pair in symmetry.get("bilateralGroupPairs") or ():
        parts = [str(part) for part in pair]
        if len(parts) != 2:
            raise ValueError(f"bilateral pair {pair!r} must have two groups")
        pairs.append((parts[0], parts[1]))
    if not pairs:
        raise ValueError("symmetry.bilateralGroupPairs is empty")
    return pairs


def anatomy_bilateral_wing_pair(catalog: Mapping[str, Any]) -> tuple[str, str]:
    """Catalog order of wing_a/wing_b. Fail-closed if symmetry does not name that pair."""
    for left, right in anatomy_bilateral_pairs(catalog):
        if {left, right} == {"wing_a", "wing_b"}:
            return left, right
    raise ValueError("symmetry.bilateralGroupPairs must include [wing_a, wing_b]")


def anatomy_bone_to_group(catalog: Mapping[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    groups = catalog.get("groups")
    if not isinstance(groups, Mapping):
        raise ValueError("anatomy catalog needs groups")
    for name in groups:
        for bone in anatomy_group_bones(catalog, str(name)):
            prior = mapping.get(bone)
            if prior is not None and prior != str(name):
                raise ValueError(f"bone {bone} is in groups {prior!r} and {name!r}")
            mapping[bone] = str(name)
    if not mapping:
        raise ValueError("anatomy catalog groups mapped to no bones")
    return mapping


def tpose_pole_for_pair(left: str, right: str) -> str:
    names = {str(left), str(right)}
    if names == {"wing_a", "wing_b"}:
        return "dorsal"
    if names == {"leg_a", "leg_b"}:
        return "ventral"
    raise ValueError(f"no T-pose pole for bilateral pair {left}/{right}")


def anatomy_central_search_groups(catalog: Mapping[str, Any]) -> list[str]:
    """Midline groups for symmetric bone fit. Trunk is attitude, not this stage."""
    symmetry = catalog.get("symmetry")
    if not isinstance(symmetry, Mapping):
        raise ValueError("anatomy catalog needs symmetry.centralGroups")
    groups = [str(name) for name in (symmetry.get("centralGroups") or ())]
    if not groups:
        raise ValueError("symmetry.centralGroups is empty")
    searchable = [name for name in groups if name != "trunk"]
    if not searchable:
        raise ValueError("central search groups are empty after excluding trunk")
    return searchable


def anatomy_central_joint_axes(catalog: Mapping[str, Any]) -> tuple[str, ...]:
    symmetry = catalog.get("symmetry")
    if not isinstance(symmetry, Mapping):
        raise ValueError("anatomy catalog needs symmetry.centralJointAxes")
    axes = [str(axis) for axis in (symmetry.get("centralJointAxes") or ())]
    allowed = {"x", "y", "z"}
    unknown = [axis for axis in axes if axis not in allowed]
    if unknown:
        raise ValueError(f"centralJointAxes must be x/y/z, not {unknown}")
    if not axes:
        raise ValueError("symmetry.centralJointAxes is empty")
    return tuple(axes)


PROP_JOINT_ANATOMY_GROUPS: dict[str, dict[str, str]] = {
    "h3_roc": {
        "HeadTip": "neck_head",
        "TailTip": "tail",
        "WingTipA": "wing_a",
        "WingTipB": "wing_b",
    },
    "h3_hobgoblin": {
        "WeaponTip": "arm_weapon",
        "RWrist": "arm_weapon",
        "LWrist": "arm_off",
    },
    "h3_behemoth": {
        "HeadTip": "neck_head",
        "TailTip": "tail",
        "PawTipA": "leg_a",
        "PawTipB": "leg_b",
    },
}


def _species_prop_joint_groups(unit: str) -> dict[str, str] | None:
    try:
        from stronghold_prop_rollout_registry import species_for_unit
    except ImportError:
        return None
    sid = str(unit)
    try:
        species = species_for_unit(sid)
    except ValueError:
        return None
    if species == "humanoid_weapon":
        return {"WeaponTip": "arm_weapon", "RWrist": "arm_weapon", "LWrist": "arm_off"}
    if species == "quadruped":
        return {
            "HeadTip": "neck_head",
            "TailTip": "tail",
            "PawTipA": "leg_a",
            "PawTipB": "leg_b",
        }
    if species == "flyer":
        return {
            "HeadTip": "neck_head",
            "TailTip": "tail",
            "WingTipA": "wing_a",
            "WingTipB": "wing_b",
        }
    return None

MANUAL_PROP_JOINT_SKIN_BONES: dict[str, dict[str, list[str]]] = {
    "h3_crusader": {
        "WeaponTip": ["Bone_001", "Bone_018", "Bone_017", "Bone_016", "Bone_044"],
        "RWrist": ["Bone_001", "Bone_018", "Bone_017", "Bone_016"],
        "ShieldCenter": ["Bone_001", "Bone_026", "Bone_033", "Bone_032", "Bone_036"],
        "LWrist": ["Bone_001", "Bone_026", "Bone_033", "Bone_032"],
    },
}


def prop_joint_skin_bones_for_unit(unit: str, joint_names: Sequence[str]) -> dict[str, list[str]]:
    """Map prop stick joints to anatomy-group bones for masked vertex calibration."""
    sid = str(unit)
    manual = MANUAL_PROP_JOINT_SKIN_BONES.get(sid)
    if manual:
        return {str(name): list(manual[str(name)]) for name in joint_names if str(name) in manual}
    mapping = PROP_JOINT_ANATOMY_GROUPS.get(sid) or _species_prop_joint_groups(sid)
    if mapping is None:
        return {}
    catalog = load_unit_anatomy_catalog(sid)
    trunk_bones = anatomy_group_bones(catalog, "trunk")
    out: dict[str, list[str]] = {}
    for joint_name in joint_names:
        group = mapping.get(str(joint_name))
        if not group:
            continue
        bones = list(trunk_bones)
        for bone in anatomy_group_bones(catalog, str(group)):
            if bone not in bones:
                bones.append(bone)
        out[str(joint_name)] = bones
    return out


def prop_joint_allowed_chain_bones(unit: str, joint_name: str) -> set[str]:
    """Bones that prop IK may rotate for one stick joint (trunk + limb group)."""
    sid = str(unit)
    manual = MANUAL_PROP_JOINT_SKIN_BONES.get(sid, {})
    if str(joint_name) in manual:
        return set(manual[str(joint_name)])
    mapping = PROP_JOINT_ANATOMY_GROUPS.get(sid, {})
    group = mapping.get(str(joint_name))
    if not group:
        return set()
    catalog = load_unit_anatomy_catalog(sid)
    allowed = set(anatomy_group_bones(catalog, "trunk"))
    allowed.update(anatomy_group_bones(catalog, str(group)))
    return allowed
