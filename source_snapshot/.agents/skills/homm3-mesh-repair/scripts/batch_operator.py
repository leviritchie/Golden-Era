"""Execute approved fit attempts, then verify agent QA and emit batch outcomes.

The invoking agent owns repair decisions and visual QA within one skill invocation.
This driver does not pretend a CLI can replace those judgments or authorize spending.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import repair_knowledge
from review_packet import ROOT, identity, read, resolve, verify_fit

GATES = ("identity", "alignment", "orientation", "surface", "ownership", "prop", "contact", "continuity")
SEQUENCE = ("source", "registration", "ownership", "props", "regeneration")
ARTIFACTS = ("fitted_bind.glb", "retargeted_motion.npz", "detail_reel.gif")
EXCLUDED = ("h3_archer", "h3_crossbowman", "h3_wood_elf")
RESOURCE_DEFAULTS = {
    "maxUnits": 1,
    "maxRepairAttemptsPerUnit": 2,
    "maxMeshyBodyGenerations": 1,
    "maxMeshyPropGenerations": 1,
    "maxIndependentReviews": 1,
    "maxBlenderSessions": 1,
    "allowNestedDelegation": False,
}


def normalized_job(job):
    result = dict(job)
    for key in ("mesh", "runDir", "sourceReport", "out", "propAttachments", "authoredSkinMap", "handClearance", "propOrientation"):
        if key in result:
            result[key] = str(resolve(result[key]))
    return result


def attempt_identity(attempt):
    return {"job": normalized_job(attempt["job"]),
            "renderMode": attempt.get("renderMode", "review"),
            "reuseExisting": attempt.get("reuseExisting") is True,
            "packetDir": str(resolve(attempt["packetDir"]))}


def context(units, signatures=None, ledger=None):
    """Print selected fields, never the full fleet or chronological repair history."""
    if not 1 <= len(units) <= 3 or len(units) != len(set(units)):
        raise ValueError("Select one to three distinct units")
    if set(units).intersection(EXCLUDED):
        raise ValueError("Selected unit is excluded from the fleet assignment")
    ledger = read(ROOT / "artifacts/homm3_mesh_repair_fleet_v1/ledger.json") if ledger is None else ledger
    rows = {row["unitSid"]: row for row in ledger["rows"]}
    if set(units) - rows.keys():
        raise ValueError("Unknown unit IDs: " + ", ".join(sorted(set(units) - rows.keys())))
    index = repair_knowledge.load()
    result = []
    for unit in units:
        row = rows[unit]
        source = row["identity"]
        evidence = row["repair"].get("animationEvidence", {})
        report_path = evidence.get("repairCandidateReport")
        report = read(resolve(report_path)) if report_path else {}
        if report and report.get("unit") != unit:
            raise ValueError("Selected candidate report belongs to another unit")
        body_plan = report.get("inputs", {}).get("bodyPlan", source.get("bodyPlan", "unknown"))
        body_plan = "biped" if body_plan in ("smartrig-biped", "biped-tpose") else body_plan
        rules = repair_knowledge.select(index, body_plan=body_plan, signatures=signatures, unit=unit)
        result.append({"unit": unit, "bodyPlan": body_plan,
                       "identity": {key: source.get(key) for key in
                                    ("status", "mesh", "meshSha256", "selectedImage", "selectedImageSha256",
                                     "retainedGenerationInput")},
                       "fitReport": report_path, "selectedJob": report.get("inputs"),
                       "activeReview": evidence.get("repairReview"),
                       "detailReel": evidence.get("repairDetailReel"),
                       "rules": rules})
    return {"proof": "routing context, not quality acceptance", "units": result}


def owned_path(path, workspace):
    path = resolve(path)
    if path == workspace or not path.is_relative_to(workspace):
        raise ValueError(f"Output must be inside the isolated batch workspace: {path}")
    return path


def validate_resource_budget(raw, unit_count):
    """Keep one skill run bounded; nested workers are never implicit."""
    budget = dict(RESOURCE_DEFAULTS)
    budget.update(raw or {})
    for key in RESOURCE_DEFAULTS:
        if key not in budget:
            raise ValueError(f"resourceBudget missing {key}")
    integer_limits = ("maxUnits", "maxRepairAttemptsPerUnit", "maxMeshyBodyGenerations",
                      "maxMeshyPropGenerations", "maxIndependentReviews", "maxBlenderSessions")
    for key in integer_limits:
        if type(budget[key]) is not int or budget[key] < 0:
            raise ValueError(f"resourceBudget.{key} must be a non-negative integer")
    if budget["maxUnits"] < unit_count:
        raise ValueError("resourceBudget.maxUnits is smaller than the selected unit count")
    if budget["maxRepairAttemptsPerUnit"] > 2:
        raise ValueError("A sparse run allows at most two repair attempts per unit")
    if budget["maxMeshyBodyGenerations"] > 1 or budget["maxMeshyPropGenerations"] > 1:
        raise ValueError("A sparse run allows at most one body and one prop generation")
    if budget["maxIndependentReviews"] > 1 or budget["maxBlenderSessions"] > 1:
        raise ValueError("A sparse run allows at most one independent review and Blender session")
    if budget["allowNestedDelegation"] is not False:
        raise ValueError("Nested delegation is forbidden; the owning Astra worker is the only worker")
    return budget


def load_batch(path):
    manifest = read(path)
    workspace = resolve(manifest["workspace"])
    if not workspace.is_relative_to(ROOT / "artifacts") or workspace == ROOT / "artifacts":
        raise ValueError("Batch workspace must be an isolated directory under artifacts")
    fleet = ROOT / "artifacts/homm3_mesh_repair_fleet_v1"
    if workspace == fleet or workspace.is_relative_to(fleet):
        raise ValueError("Driver must not write the fleet workspace")
    units = manifest["units"]
    if not 1 <= len(units) <= 3 or len({u["unit"] for u in units}) != len(units):
        raise ValueError("Select one to three distinct units")
    manifest["resourceBudget"] = validate_resource_budget(manifest.get("resourceBudget"), len(units))
    outputs = set()
    reserved = [workspace / name for name in ("logs", "working_state.json", "batch_result.json")]
    for unit in units:
        if not re.fullmatch(r"[a-z0-9_]+", unit["unit"]):
            raise ValueError("Unit ID must be a safe catalog identifier")
        if unit["unit"] in EXCLUDED:
            raise ValueError("Fleet pilot exclusions require a separate explicit assignment")
        limit = unit["maxAttempts"]
        if type(limit) is not int or limit < 1 or limit > manifest["resourceBudget"]["maxRepairAttemptsPerUnit"] \
                or not 1 <= len(unit["attempts"]) <= limit:
            raise ValueError("Each unit needs one to maxAttempts explicitly budgeted attempts")
        for attempt in unit["attempts"]:
            jobs = read(resolve(attempt["fitManifest"]))["jobs"]
            selected = [job for job in jobs if job["unit"] == unit["unit"]]
            if len(selected) != 1:
                raise ValueError("Fit manifest must select the unit exactly once")
            attempt["job"] = selected[0]
            attempt["candidate"] = (resolve(selected[0]["out"]) if attempt.get("reuseExisting") is True
                                    else owned_path(selected[0]["out"], workspace))
            attempt["packetDir"] = owned_path(attempt["packetDir"], workspace)
            attempt["review"] = owned_path(attempt["review"], workspace)
            for path in (attempt["candidate"], attempt["packetDir"], attempt["review"]):
                if any(path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in reserved):
                    raise ValueError("Attempt collides with driver-owned logs/state outputs")
            for path in (attempt["candidate"], attempt["packetDir"]):
                if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
                       for other in outputs):
                    raise ValueError("Candidate/packet output directories must be disjoint")
                outputs.add(path)
            if attempt.get("renderMode", "review") not in ("review", "full"):
                raise ValueError("renderMode must be review or full")
            if not attempt.get("hypothesis", "").strip():
                raise ValueError("Every approved attempt needs a concrete repair hypothesis")
    return manifest, workspace


def verify_packet(attempt, unit, require_full=False):
    candidate = attempt["candidate"]
    report = read(candidate / "report.json")
    if report.get("status") != "experimental_candidate" or report.get("unit") != unit:
        raise ValueError("Missing completed candidate for this unit")
    verify_fit(report)
    if normalized_job(report["inputs"]) != normalized_job(attempt["job"]):
        raise ValueError("Retained fit is not the selected attempt job")
    if report.get("previewScale", 0) < 3:
        raise ValueError("Review requires native evidence at scale >=3")
    if require_full and not report.get("preview"):
        raise ValueError("Passing final QA requires full saved-motion replay")
    packet = read(attempt["packetDir"] / "packet.json")
    if packet["unit"] != unit or packet["fitFingerprint"] != report["fingerprint"]:
        raise ValueError("Packet belongs to another candidate")
    if packet["frameCount"] != report["frames"]:
        raise ValueError("Packet frame count differs from the full replay")
    expected_inputs = {str(resolve(candidate / name)) for name in
                       ("report.json", "fitted_bind.glb", "retargeted_motion.npz")}
    if not expected_inputs.issubset({str(resolve(i["path"])) for i in packet["inputs"]}):
        raise ValueError("Packet does not pin selected candidate/report/motion")
    rest = packet.get("restPanels", [])
    if {Path(i["path"]).name for i in rest} != {"rest_front.png", "rest_side.png"}:
        raise ValueError("Packet must pin front and side rest evidence")
    for item in packet["inputs"] + [p["image"] for p in packet["panels"]] + rest:
        if identity(item["path"])["sha256"] != item["sha256"]:
            raise ValueError(f"Packet input changed: {item['path']}")
    reel = packet.get("detailReel")
    if (require_full or report.get("preview")) and not reel:
        raise ValueError("Packet lacks the generated detail reel")
    if reel and resolve(reel["path"]) != candidate / "detail_reel.gif":
        raise ValueError("Packet has no matching full detail reel")
    if reel and identity(reel["path"])["sha256"] != reel["sha256"]:
        raise ValueError("Detail reel changed since packet creation")
    return report, packet


def validate_review(review, fingerprint, artifact_hashes, panel_hashes, required_frames):
    if review.get("candidateFingerprint") != fingerprint:
        raise ValueError("Visual review refers to another fit")
    if review.get("artifacts") != artifact_hashes:
        raise ValueError("Visual review artifact hashes do not match")
    if review.get("decision") not in ("pass", "reject"):
        raise ValueError("Visual review needs an explicit pass or reject decision")
    gates = review.get("gates", {})
    if set(gates) != set(GATES):
        raise ValueError("Visual review must address every quality gate")
    for gate in GATES:
        if type(gates[gate].get("pass")) is not bool or not str(gates[gate].get("evidence", "")).strip():
            raise ValueError(f"Gate {gate} needs a boolean and concrete evidence")
    inspected = review.get("inspectedPanels", [])
    if not inspected:
        raise ValueError("No individual native-resolution visual evidence")
    for item in inspected:
        path = resolve(item["path"]).as_posix()
        if panel_hashes.get(path) != item["sha256"]:
            raise ValueError("Inspected panel is stale or not part of this packet")
    missing = sorted(set(required_frames) - set(review.get("reviewedFrames", [])))
    failed = [gate for gate in GATES if not gates[gate]["pass"]]
    if review["decision"] == "pass" and (failed or missing or review.get("fullReelReviewed") is not True):
        raise ValueError("Passing QA requires all gates, selected frames and full reel inspection")
    if review["decision"] == "pass":
        if len({resolve(i["path"]).as_posix() for i in inspected}) != len(panel_hashes):
            raise ValueError("Passing QA must inspect every selected individual panel")
        if not all(isinstance(review.get(k), str) and review[k].strip()
                   for k in ("reviewer", "repairWorker")) or review["reviewer"] == review["repairWorker"]:
            raise ValueError("Finalist requires a named independent visual reviewer")
    if review["decision"] == "reject" and not str(review.get("nextAction", "")).strip():
        raise ValueError("Rejected candidate needs an actionable next step")
    return failed


def execute(command, log, timeout):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Stage exceeded its {timeout}s budget: {command[1]}") from error
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"Stage failed ({result.returncode}); inspect {log}")


def claim_candidate(attempt):
    """Only this driver's matching attempt may resume writes to an existing directory."""
    candidate = attempt["candidate"]
    stamp = candidate / "batch_attempt.json"
    owner = {"schema": "mesh_repair_batch_attempt.v1", "job": normalized_job(attempt["job"])}
    if candidate.exists() and any(candidate.iterdir()):
        if not stamp.is_file() or read(stamp) != owner:
            raise ValueError("Existing candidate is not this resumable attempt; use a fresh output")
    candidate.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(owner, sort_keys=True) + "\n", encoding="utf-8")


def prepare(manifest, workspace):
    state = []
    for unit in manifest["units"]:
        for index, attempt in enumerate(unit["attempts"]):
            try:
                # Existing valid evidence is reused; an invalid packet is never silently overwritten.
                packet_path = attempt["packetDir"] / "packet.json"
                if not packet_path.is_file():
                    if attempt.get("reuseExisting") is True:
                        # Reused candidates are read-only, even if their preview is incomplete.
                        verify_fit(read(attempt["candidate"] / "report.json"))
                    else:
                        claim_candidate(attempt)
                        execute([sys.executable, str(ROOT / "tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py"),
                                 "--manifest", str(resolve(attempt["fitManifest"])), "--units", unit["unit"],
                                 "--preview" if attempt.get("renderMode") == "full" else "--review",
                                 "--preview-scale", "3"],
                                workspace / "logs" / f"{unit['unit']}-{index}-fit.log", 1200)
                    execute([sys.executable, str(Path(__file__).with_name("review_packet.py")),
                             "--candidate", str(attempt["candidate"]), "--out", str(attempt["packetDir"])],
                            workspace / "logs" / f"{unit['unit']}-{index}-packet.log", 300)
                verify_packet(attempt, unit["unit"], attempt.get("renderMode") == "full")
                state.append({"unit": unit["unit"], "attempt": index, "job": normalized_job(attempt["job"]),
                              "state": "ready_for_agent_qa",
                              "review": str(attempt["review"])})
            except (ValueError, OSError, KeyError) as error:
                state.append({"unit": unit["unit"], "attempt": index, "job": normalized_job(attempt["job"]),
                              "attemptIdentity": attempt_identity(attempt),
                              "state": "stage_exception",
                              "reason": str(error)})
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "working_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"phase": "internal_preparation", "attempts": state}


def finalize(manifest, workspace):
    candidates, exceptions = [], []
    for unit in manifest["units"]:
        accepted = None
        rejected = []
        for index, attempt in enumerate(unit["attempts"]):
            if not attempt["review"].is_file():
                state_path = workspace / "working_state.json"
                failures = [row for row in read(state_path) if row["unit"] == unit["unit"]
                            and row["attempt"] == index and row["state"] == "stage_exception"
                            and row.get("attemptIdentity") == attempt_identity(attempt)]
                if len(failures) != 1:
                    raise ValueError("Attempt needs visual QA or a matching recorded stage failure")
                rejected.append({"candidate": str(attempt["candidate"]), "stageFailure": failures[0],
                                 "evidence": identity(state_path)})
                continue
            review = read(attempt["review"])
            report, packet = verify_packet(attempt, unit["unit"], review.get("decision") == "pass")
            hashes = {name: identity(attempt["candidate"] / name)["sha256"] for name in ARTIFACTS
                      if (attempt["candidate"] / name).is_file()}
            panels = {resolve(p["image"]["path"]).as_posix(): identity(p["image"]["path"])["sha256"]
                      for p in packet["panels"]}
            panels.update({resolve(p["path"]).as_posix(): p["sha256"] for p in packet["restPanels"]})
            failed = validate_review(review, report["fingerprint"], hashes, panels,
                                     [p["globalIndex"] for p in packet["panels"]])
            if review["decision"] == "pass":
                accepted = {"unit": unit["unit"], "candidate": str(attempt["candidate"]),
                            "review": str(attempt["review"]), "artifacts": hashes,
                            "candidateFingerprint": report["fingerprint"],
                            "reviewIdentity": identity(attempt["review"]),
                            "packetIdentity": identity(attempt["packetDir"] / "packet.json"),
                            "proof": "agent-reviewed generated candidate; not delivery/runtime proof"}
                break
            rejected.append({"candidate": str(attempt["candidate"]), "failedGates": failed,
                             "nextAction": review["nextAction"], "review": str(attempt["review"])})
        if accepted:
            candidates.append(accepted)
            continue
        closure = unit.get("sequenceClosure", {})
        for stage in SEQUENCE:
            row = closure.get(stage, {})
            if row.get("state") not in ("completed", "not_indicated", "exhausted", "blocked") or not row.get("reason"):
                raise ValueError(f"{unit['unit']}: approved sequence not closed at {stage}; continue internally")
            if not row.get("evidence"):
                raise ValueError(f"{stage}: closure requires retained evidence, not a reason alone")
            for item in row["evidence"]:
                if identity(item["path"])["sha256"] != item["sha256"]:
                    raise ValueError(f"{stage}: closure evidence changed")
        if not any(row["state"] in ("blocked", "exhausted") for row in closure.values()):
            raise ValueError("Rejected quality with an available route must continue internally")
        if not unit.get("exceptionNextAction"):
            raise ValueError("A terminal unit exception requires a concrete next action")
        exceptions.append({"unit": unit["unit"], "attempts": rejected,
                           "sequenceClosure": closure, "nextAction": unit["exceptionNextAction"]})
    result = {"proof": "generated-candidate batch only", "workRemaining": bool(exceptions),
              "candidates": candidates, "exceptions": exceptions}
    path = workspace / "batch_result.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {"result": str(path), "candidates": len(candidates), "exceptions": len(exceptions),
            "workRemaining": bool(exceptions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("context", "prepare", "finalize"))
    parser.add_argument("--manifest")
    parser.add_argument("--units", nargs="+")
    parser.add_argument("--signature", action="append")
    args = parser.parse_args()
    try:
        if args.phase == "context":
            if not args.units:
                parser.error("context requires --units")
            result = context(args.units, args.signature)
        else:
            if not args.manifest:
                parser.error("prepare/finalize require --manifest")
            batch, directory = load_batch(resolve(args.manifest))
            result = (prepare if args.phase == "prepare" else finalize)(batch, directory)
        print(json.dumps(result, separators=(",", ":")))
        if any(a["state"] == "stage_exception" for a in result.get("attempts", [])):
            return 1
        return 2 if result.get("workRemaining") else 0
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
