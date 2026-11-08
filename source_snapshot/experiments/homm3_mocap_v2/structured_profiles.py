"""Explicit data-authored unit profiles for the existing fitted-bind solver.

Draft entries fail closed. Donor recipes share donor facts only, never another
unit's anatomical assignments or acceptance. Loading validates before preparation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
REGISTRY = Path(__file__).with_name("profiles") / "registry.json"
SCHEMA = "homm3-mocap-structured-profile-v1"
ANATOMY_FIELDS = ("regionBones", "sourceJointMap", "hubs", "chains", "leftRightPairs",
                  "rigidAttachments", "requiredBranches", "extraTargetBones",
                  "unsupportedRequiredArticulations", "actuation", "wholeBodyHubs",
                  "headBone", "neckBone")


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate structured profile key {key!r}")
        result[key] = value
    return result


def read_document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


def anatomy_hash(anatomy: dict) -> str:
    return hashlib.sha256(json.dumps(anatomy, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def registered_profiles() -> dict[str, Path]:
    data = read_document(REGISTRY)
    if data.get("schema") != "homm3-mocap-profile-registry-v1" or not isinstance(data.get("profiles"), dict):
        raise ValueError("invalid structured profile registry")
    result = {}
    for asset, filename in data["profiles"].items():
        path = (REGISTRY.parent / filename).resolve()
        if not path.is_relative_to(REGISTRY.parent.resolve()):
            raise ValueError("profile entry escapes registry directory")
        result[asset] = path
    return result


def donor_recipe(name: str) -> dict:
    if name != "mixamo-25-v1":
        raise ValueError(f"unsupported explicit donor recipe {name!r}")
    # Imports are delayed because asset_profiles owns the established donor data.
    from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
    from paths import VENDOR_DEMO
    return {"donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ,
            "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
            "donorBindSource": "ffs_bvh_capture_scale", "regionJoints": deepcopy(MIXAMO_REGION_JOINTS)}


def validate_document(data: dict, asset_id: str, source_names: list[str]) -> dict:
    """Return a complete solver profile, rejecting inferred anatomy and draft use."""
    if data.get("schema") != SCHEMA or data.get("assetId") != asset_id:
        raise ValueError("structured profile schema or asset identity mismatch")
    if data.get("status") != "authored":
        raise ValueError(f"{asset_id}: anatomy is not authored; structured draft cannot prepare")
    anatomy = data.get("anatomy")
    if not isinstance(anatomy, dict) or set(anatomy) != set(ANATOMY_FIELDS):
        raise ValueError("structured anatomy requires the exact complete field set")
    if anatomy_hash(anatomy) != data.get("anatomySha256"):
        raise ValueError("structured anatomy hash mismatch")
    profile = donor_recipe(data["donorRecipe"])
    profile.update(deepcopy(anatomy))
    if "geometryOwnership" in data:
        profile["geometryOwnership"] = deepcopy(data["geometryOwnership"])
    profile.update({"assetId": asset_id, "displayName": data["displayName"],
                    "mesh": (ROOT / data["mesh"]).resolve(),
                    "expectedMeshSha256": data["meshSha256"],
                    "skinInitialization": "source_joint_map", "requireCompleteRegionCoverage": True,
                    "beakFromHeadQuantile": None, "syntheticMotionOnly": True,
                    "visualAcceptance": "unreviewed_candidate"})
    from target_asset import validate_complete_region_coverage
    validate_complete_region_coverage(source_names, profile)
    if len(set(source_names)) != len(source_names) or set(profile["sourceJointMap"]) != set(source_names):
        raise ValueError("structured sourceJointMap must cover every unique source bone")
    donor_names = {n for group in profile["regionJoints"].values() for n in group}
    # End helpers are present on the established 25-joint Mixamo skeleton.
    donor_names.update(("mixamorig:LeftToe_End", "mixamorig:RightToe_End"))
    unknown = set(profile["sourceJointMap"].values()) - donor_names
    if unknown:
        raise ValueError(f"structured sourceJointMap contains unknown donor joints: {sorted(unknown)}")
    if not data.get("sourceSelectionReason"):
        raise ValueError("structured profile requires explicit source selection rationale")
    return profile


def load_registered_profile(asset_id: str, path: Path) -> dict:
    profile_bytes = path.read_bytes()
    data = json.loads(profile_bytes, object_pairs_hook=_unique_object)
    if data.get("status") != "authored":
        raise ValueError(f"{asset_id}: anatomy is not authored; structured draft cannot prepare")
    mesh = (ROOT / data["mesh"]).resolve()
    if hashlib.sha256(mesh.read_bytes()).hexdigest() != data.get("meshSha256"):
        raise ValueError(f"{asset_id}: structured source mesh hash mismatch")
    from glb_skeleton import read_glb
    doc = read_glb(mesh)["json"]
    skins = doc.get("skins", [])
    if len(skins) != 1:
        raise ValueError("structured source must have exactly one skin")
    names = [doc["nodes"][index]["name"] for index in skins[0]["joints"]]
    profile = validate_document(data, asset_id, names)
    if "geometryOwnership" in profile:
        from geometry_ownership import load_ownership
        load_ownership(profile)
    profile["structuredProfile"] = str(path.resolve())
    profile["structuredProfileSha256"] = hashlib.sha256(profile_bytes).hexdigest()
    return profile


def validate_selected_profiles(rows: list[dict]) -> list[str]:
    """Build/deploy gate for registered selections; builtin profiles are unchanged."""
    errors = []
    try:
        registered = registered_profiles()
    except (ValueError, OSError, TypeError) as exc:
        return [f"structured profile registry invalid: {exc}"]
    for row in rows:
        asset = row.get("assetId")
        if asset not in registered:
            continue
        try:
            profile = load_registered_profile(asset, registered[asset])
            if row.get("structuredProfileSha256") != profile["structuredProfileSha256"]:
                raise ValueError("selected structured profile hash is missing or changed; regenerate selection from the prepared profile")
            report_path = (ROOT / row["sourceReport"]).resolve()
            if hashlib.sha256(report_path.read_bytes()).hexdigest() != row["sourceReportSha256"]:
                raise ValueError("selected fit report hash changed")
            source_report = read_document(report_path)
            if source_report.get("structuredProfileSha256") != profile["structuredProfileSha256"]:
                raise ValueError("selected fit report has a missing or changed structured profile pin")
            if "geometryOwnership" in profile:
                gate = source_report.get("ownershipBoundaryGate", {})
                if gate.get("passed") is not True or source_report.get("candidateValidForExport") is not True:
                    raise ValueError("selected physical ownership fit report lacks a passing boundary/export gate")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f"{asset}: structured profile invalid: {exc}")
    return errors


def current_profile_pin(asset_id: str) -> dict:
    """Capture an authored profile pin at a producer boundary, never from history."""
    paths = registered_profiles()
    if asset_id not in paths:
        return {}
    profile = load_registered_profile(asset_id, paths[asset_id])
    return {"structuredProfileSha256": profile["structuredProfileSha256"]}


def require_profile_pin(asset_id: str, *records: dict) -> dict:
    """Consumers require every input to name the same current authored profile."""
    pin = current_profile_pin(asset_id)
    for record in records:
        if pin:
            if record.get("structuredProfileSha256") != pin["structuredProfileSha256"]:
                raise ValueError(f"{asset_id}: structured profile pin missing or changed; regenerate the upstream artifact")
        elif "structuredProfileSha256" in record:
            raise ValueError(f"{asset_id}: structured profile pin supplied for an unregistered asset")
    return pin
