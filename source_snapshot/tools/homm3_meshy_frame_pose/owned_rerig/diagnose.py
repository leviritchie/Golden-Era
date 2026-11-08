"""Fail-closed Meshy/Mixamo smart-rig quality checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from .glb_io import load_mesh

MIXAMO_HINTS = ("mixamo", "mixamorig")
HUMANOID_LEG_L = re.compile(r"(leftupleg|leftleg|l_upleg|l_thigh|thigh_l|upleg_l)", re.I)
HUMANOID_LEG_R = re.compile(r"(rightupleg|rightleg|r_upleg|r_thigh|thigh_r|upleg_r)", re.I)
HUMANOID_ARM_L = re.compile(r"(leftarm|leftforearm|lefthand|l_arm|arm_l|hand_l|shoulder_l|leftshoulder)", re.I)
HUMANOID_ARM_R = re.compile(r"(rightarm|rightforearm|righthand|r_arm|arm_r|hand_r|shoulder_r|rightshoulder)", re.I)
HOOF_HINT = re.compile(r"(hoof|hind|foreleg|quadruped|horse|wolf|boar)", re.I)
SPINE_HINT = re.compile(r"(spine|hips|pelvis|neck)", re.I)
WING_HINT = re.compile(r"(wing|feather|pinion)", re.I)
OWNED_FLYER_HINT = re.compile(r"(rightwing|leftwing|beak)", re.I)


def _is_mixamo(names: list[str]) -> bool:
    joined = " ".join(names).lower()
    if any(h in joined for h in MIXAMO_HINTS):
        return True
    has_hips = any(n.lower() in {"hips", "mixamorig:hips"} or n.lower().endswith("hips") for n in names)
    has_upleg = any("upleg" in n.lower() or "thigh" in n.lower() for n in names)
    return has_hips and has_upleg


def _leg_chain_count(names: list[str]) -> tuple[int, int]:
    left = sum(1 for n in names if HUMANOID_LEG_L.search(n.replace(":", "")))
    right = sum(1 for n in names if HUMANOID_LEG_R.search(n.replace(":", "")))
    hooves = sum(1 for n in names if HOOF_HINT.search(n))
    return left + right, hooves


def diagnose_smartrig_quality(glb_path: Path, *, expected_species: str = "rider_mount") -> dict[str, Any]:
    mesh = load_mesh(glb_path)
    names = mesh.node_names
    pos = mesh.positions
    extent = pos.max(axis=0) - pos.min(axis=0)
    height = float(max(extent[2], 1e-8))
    length = float(max(extent[0], extent[1]))
    aspect = length / height
    mixamo = _is_mixamo(names)
    humanoid_legs, hoof_hints = _leg_chain_count(names)
    checks: list[dict[str, Any]] = []
    fail = False

    def add(check_id: str, ok: bool, detail: str) -> None:
        nonlocal fail
        checks.append({"id": check_id, "ok": ok, "detail": detail})
        if not ok:
            fail = True

    add(
        "skinned",
        mesh.joints is not None and mesh.weights is not None and bool(mesh.skin_joints),
        "smart-rig GLB must contain a skin to diagnose; unskinned mesh is already a strip candidate",
    )
    add(
        "mixamo_humanoid_on_long_mesh",
        not (mixamo and aspect >= 1.15 and humanoid_legs <= 6 and hoof_hints < 4 and expected_species == "rider_mount"),
        f"mixamo={mixamo} aspect={aspect:.3f} humanoidLegNameHits={humanoid_legs} hoofHints={hoof_hints}",
    )
    add(
        "four_hoof_chains",
        expected_species != "rider_mount" or hoof_hints >= 4,
        f"hoof/fore/hind name hits={hoof_hints}; rider_mount needs four hoof chains",
    )
    arm_l = sum(1 for n in names if HUMANOID_ARM_L.search(n.replace(":", "")))
    arm_r = sum(1 for n in names if HUMANOID_ARM_R.search(n.replace(":", "")))
    wing_hits = sum(1 for n in names if WING_HINT.search(n))
    add(
        "named_left_and_right_arm_chains",
        expected_species != "winged_humanoid" or (arm_l >= 2 and arm_r >= 2),
        f"armNameHits L={arm_l} R={arm_r}; winged_humanoid needs named shoulder/arm/hand chains, not UniRig Bone_*",
    )
    add(
        "named_wing_chains",
        expected_species != "winged_humanoid" or wing_hits >= 4,
        f"wingNameHits={wing_hits}; unnamed Bone_* wing chains are not delivery topology",
    )
    bone_star = sum(1 for n in names if n.startswith("Bone_"))
    owned_flyer = sum(1 for n in names if OWNED_FLYER_HINT.search(n.replace(":", "")))
    add(
        "flyer_not_unirig_bone_star",
        expected_species != "flyer" or (bone_star < 8 and owned_flyer >= 6),
        f"Bone_*={bone_star} ownedFlyerHits={owned_flyer}; flyer delivery needs Beak/LeftWing/RightWing chains, not UniRig Bone_*",
    )

    rider_on_spine = False
    if mesh.joints is not None and mesh.weights is not None and mesh.skin_joints:
        z = pos[:, 2]
        high = z >= (float(z.min()) + 0.72 * float(z.max() - z.min()))
        if np.any(high):
            owners: dict[str, float] = {}
            for vi in np.nonzero(high)[0]:
                j = int(mesh.joints[vi, 0])
                if j < 0 or j >= len(mesh.skin_joints):
                    continue
                node = mesh.skin_joints[j]
                name = names[node] if node < len(names) else f"joint{j}"
                owners[name] = owners.get(name, 0.0) + float(mesh.weights[vi, 0])
            if owners:
                top = max(owners, key=owners.get)
                rider_on_spine = bool(SPINE_HINT.search(top)) and not top.lower().startswith("rider")
                add(
                    "upper_cluster_not_owned_by_horse_spine",
                    not rider_on_spine,
                    f"dominant bone for upper verts={top}",
                )
    if mesh.inverse_bind is not None:
        scales = []
        for node_i in mesh.skin_joints:
            # rest vs bind is owned by inspect_glb_skinning; here we only flag missing IBM rows
            scales.append(node_i)
        add("inverse_bind_rows", len(mesh.inverse_bind) >= len(mesh.skin_joints), "IBM count vs joint count")

    verdict = "replace" if fail else "keep"
    if expected_species == "rider_mount" and mixamo and aspect >= 1.15:
        verdict = "replace"
    return {
        "schema": "smartrig_quality.v1",
        "source": str(Path(glb_path).resolve()).replace("\\", "/"),
        "expectedSpecies": expected_species,
        "verdict": verdict,
        "mixamoLike": mixamo,
        "aabbAspectLengthOverHeight": round(aspect, 4),
        "humanoidLegNameHits": humanoid_legs,
        "humanoidArmNameHits": arm_l + arm_r,
        "wingNameHits": wing_hits,
        "hoofNameHits": hoof_hints,
        "jointNames": names,
        "checks": checks,
        "proof": "generated-artifact",
    }


diagnose_smartrig_quality = diagnose_smartrig_quality
