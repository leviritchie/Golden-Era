#!/usr/bin/env python3
"""Validate the Crusader owned-bind clip batch and its preview evidence.

This is a generated-artifact gate, not a Unity or Olden Era runtime test. It
keeps the active master, owned roles, authored-landmark requirement, fixed
length fit outputs, and 180 ms lit preview contract aligned across the batch.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ART = ROOT / "artifacts/crusader_pose_pipeline"
OUT = ART / "out_fit"
MASTER = ART / "owned_bind/crusader_master_rigid_components.glb"
ROLES = ROOT / "tools/homm3_silhouette_pose_fit/bone_roles_crusader_owned.json"
AUDIT = ART / "owned_bind/rigid_triangle_audit.json"
SKELETON = ART / "owned_bind/crusader_skeleton_rigid_components.json"
OWNERSHIP_RULES = ROOT / "tools/homm3_meshy_frame_pose/ownership_rules_h3_crusader.json"
REPORT = OUT / "crusader_owned_batch_validation.json"

GROUPS = {
    0: ("g00_move", "move"),
    1: ("g01_mouseover", "mouseover"),
    3: ("g03_hitted", "hitted"),
    4: ("g04_defence", "defence"),
    5: ("g05_death", "death"),
    7: ("g07_turn_left", "turn_left"),
    8: ("g08_turn_right", "turn_right"),
    9: ("g09_unused_a", "unused_a"),
    10: ("g10_unused_b", "unused_b"),
    11: ("g11_attack_up", "attack_up"),
    12: ("g12_attack_front_rigid_components", "attack_front"),
    13: ("g13_attack_down", "attack_down"),
    20: ("g20_move_start", "move_start"),
    21: ("g21_move_end", "move_end"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_group(gid: int, folder: str, label: str) -> dict:
    out_folder = folder + "_fixed_length"
    out = OUT / out_folder
    authored = OUT / (folder + "_authored")
    if gid == 12:
        authored = OUT / "idle_attack_front_authored"
    result = {"group": gid, "label": label, "output": str(out).replace("\\", "/"), "errors": []}
    authored_kpt = authored / "sprite_landmarks/keypoints.json"
    if not authored_kpt.is_file():
        result["errors"].append(f"missing authored keypoints: {authored_kpt}")
    else:
        method = str(load(authored_kpt).get("method") or "")
        if "human_eye_landmark_authoring" not in method:
            result["errors"].append(f"keypoints method is not human-eye authored: {method!r}")

    job = out / "job.resolved.json"
    fit = out / "fit_report.json"
    if not job.is_file():
        result["errors"].append(f"missing resolved job: {job}")
    else:
        doc = load(job)
        if Path(doc.get("masterGlb", "")).resolve() != MASTER.resolve():
            result["errors"].append(f"wrong masterGlb: {doc.get('masterGlb')}")
        if Path(doc.get("boneRoles", "")).resolve() != ROLES.resolve():
            result["errors"].append(f"wrong boneRoles: {doc.get('boneRoles')}")
        if doc.get("poseSolver") != "fixed_length_ik":
            result["errors"].append(f"wrong poseSolver: {doc.get('poseSolver')}")
        if not doc.get("fixedLengthIk", {}).get("frame0CameraRegister"):
            result["errors"].append("frame0CameraRegister is not enabled")
        result["frameCount"] = len(doc.get("frames", []))

    if not fit.is_file():
        result["errors"].append(f"missing fit report: {fit}")
    else:
        fit_doc = load(fit)
        if not fit_doc.get("ok"):
            result["errors"].append("fit report is not ok")
        result["meanNoseErrorPx"] = fit_doc.get("meanNoseErrorPx")
        result["meanTipErrorPx"] = fit_doc.get("meanTipErrorPx")
        result["meanBodyLossPx"] = fit_doc.get("meanBodyLossPx")

    glbs = sorted(out.glob("*.glb"))
    if len(glbs) != 1:
        result["errors"].append(f"expected exactly one delivery GLB, found {len(glbs)}")
    result["deliveryGlb"] = str(glbs[0]).replace("\\", "/") if glbs else None

    meta = out / "preview_lit_60fps/preview_lit_60fps_meta.json"
    if not meta.is_file():
        result["errors"].append(f"missing lit preview metadata: {meta}")
    else:
        preview = load(meta)
        if preview.get("gifFrameMs") != 180:
            result["errors"].append(f"gifFrameMs is {preview.get('gifFrameMs')}, expected 180")
        if int(preview.get("frameCount", 0)) <= 0:
            result["errors"].append("lit preview has no frames")
        result["preview"] = preview

    result["ok"] = not result["errors"]
    return result


def check_ownership_policy() -> tuple[list[str], dict]:
    errors = []
    summary = {
        "rulesFile": str(OWNERSHIP_RULES).replace("\\", "/"),
        "skeletonFile": str(SKELETON).replace("\\", "/"),
    }
    if not OWNERSHIP_RULES.is_file():
        return [f"missing ownership rules: {OWNERSHIP_RULES}"], summary
    rules_doc = load(OWNERSHIP_RULES)
    if rules_doc.get("schema") != "owned_skin_ownership_rules.v1":
        errors.append(f"unsupported ownership rules schema: {rules_doc.get('schema')!r}")
    if rules_doc.get("unitSid") != "h3_crusader":
        errors.append(f"ownership rules target {rules_doc.get('unitSid')!r}, expected 'h3_crusader'")
    rules = rules_doc.get("rules")
    if not isinstance(rules, list):
        errors.append("ownership rules list is missing")
        rules = []
    if not SKELETON.is_file():
        errors.append(f"missing skeleton ownership audit: {SKELETON}")
        return errors, summary
    ownership = load(SKELETON).get("ownership", {})
    if Path(str(ownership.get("rulesFile", ""))).resolve() != OWNERSHIP_RULES.resolve():
        errors.append(f"skeleton was not generated with active ownership rules: {ownership.get('rulesFile')!r}")
    counts = ownership.get("applicationsByRule", {})
    applied = ownership.get("applied", [])
    if len(applied) != sum(int(value) for value in counts.values()):
        errors.append("skeleton ownership application list does not match per-rule counts")
    for rule in rules:
        rule_id = rule.get("id")
        actual = int(counts.get(rule_id, 0))
        minimum = int(rule.get("minApplications", 0))
        if actual < minimum:
            errors.append(f"ownership rule {rule_id!r} matched {actual}, expected at least {minimum}")
    summary["applicationsByRule"] = counts
    summary["appliedCount"] = len(applied)
    return errors, summary


def main() -> int:
    errors = []
    if not MASTER.is_file():
        errors.append(f"missing active master: {MASTER}")
    if not ROLES.is_file():
        errors.append(f"missing owned roles: {ROLES}")
    if not AUDIT.is_file():
        errors.append(f"missing rigid triangle audit: {AUDIT}")
    else:
        audit = load(AUDIT)
        for key in ("unownedVertices", "ambiguousVertices", "mixedTriangles"):
            if audit.get(key):
                errors.append(f"rigid triangle audit has non-empty {key}")
    ownership_errors, ownership = check_ownership_policy()
    errors.extend(ownership_errors)

    groups = [check_group(gid, folder, label) for gid, (folder, label) in GROUPS.items()]
    errors.extend(f"group {g['group']}: {err}" for g in groups for err in g["errors"])
    doc = {
        "ok": not errors,
        "proofTier": "generated-artifact-validated",
        "master": str(MASTER).replace("\\", "/"),
        "roles": str(ROLES).replace("\\", "/"),
        "rigidTriangleAudit": str(AUDIT).replace("\\", "/"),
        "ownership": ownership,
        "groupCount": len(groups),
        "groups": groups,
        "errors": errors,
    }
    REPORT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": doc["ok"], "groupCount": len(groups), "errors": errors}, indent=2))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
