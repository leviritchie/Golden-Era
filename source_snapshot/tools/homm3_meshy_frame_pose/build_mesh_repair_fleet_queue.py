#!/usr/bin/env python3
"""Freeze the mesh-repair queue and source-identity ledger for the Luna handoff.

This is an artifact producer, not a success gate.  It deliberately keeps the
261-versus-262 roster discrepancy visible and separates catalog-only neutral
entries from the animation roster.  A mesh is never called source-correct
without a copied generation input whose hash matches the producer's selected
source image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "artifacts/homm3_mesh_repair_fleet_v1"
IMPORT_MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
NEUTRAL_CATALOG = ROOT / "tools/homm3_import/faction_concepts/homm3_neutral.json"
COVERAGE = ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json"
SCHEDULER = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/scheduler_manifest.json"
RUN_ROOT = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
REPAIR_ROOT = ROOT / "artifacts/meshy_downloads/meshy71_repair_candidates"
FLEET_MANIFEST_ROOT = OUT_ROOT / "manifests"
IDENTITY_REVIEW = OUT_ROOT / "identity_reviews.json"

EXCLUSIONS = {
    "h3_archer": "excluded_prior_pilot",
    "h3_crossbowman": "excluded_prior_pilot",
    "h3_wood_elf": "excluded_prior_pilot",
}

CENTAUROID_ADAPTER_IDS = {
    "h3_centaur",
    "h3_centaur_captain",
    "h3_centaur_ranger",
    "h3_dreadtaur",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_copy_candidates(sid: str, mesh: Path | None = None) -> list[Path]:
    # Repair candidates are new geometry attempts, not provenance for the
    # canonical mesh selected by the coverage inventory.  Mixing their copied
    # input image into canonical identity evidence can make an old mesh look
    # source-hash validated merely because a later candidate used the image.
    candidates = [
        ROOT / "artifacts/meshy_downloads/meshy7_missing" / sid / "source.png",
    ]
    # Once the coverage inventory explicitly selects a task-backed replacement
    # candidate, its copied source image is the authoritative provenance input
    # for that selected surface.  Do not use repair candidates while the old
    # canonical mesh remains selected.
    if mesh is not None and mesh.name == "mesh.glb" and mesh.parent.name == "source":
        candidate_root = mesh.parent.parent
        if candidate_root.parent.name == "meshy71_repair_candidates":
            candidates.insert(0, mesh.parent / "source.png")
    return candidates


def _body_plan(sid: str, neutral_row: dict | None) -> tuple[str, str]:
    if neutral_row and neutral_row.get("stats", {}).get("moveType") == "fly":
        return "winged-flying", "neutral_catalog.moveType"
    if any(token in sid for token in ("dragon", "griffin", "griffon", "phoenix", "pegasus", "angel", "demon", "devil", "wyvern", "roc", "bird", "elemental")):
        return "winged-flying", "sid heuristic; visual confirmation required"
    if any(token in sid for token in ("rider", "cavalier", "champion", "knight", "nomad", "boar_rider", "jotunn", "mammoth", "ram")):
        return "mounted-or-heavy", "sid heuristic; visual confirmation required"
    return "biped-or-other", "sid heuristic; visual confirmation required"


def _identity(sid: str, row: dict, neutral_row: dict | None, identity_reviews: dict) -> dict:
    image = Path(str(row.get("imageInput") or "")) if row.get("imageInput") else None
    image_exists = bool(image and image.is_file())
    expected_hash = _sha256(image) if image_exists else None
    mesh = Path(str(row.get("mesh") or "")) if row.get("mesh") else None
    mesh_exists = bool(mesh and mesh.is_file())
    source_copy = next((p for p in _source_copy_candidates(sid, mesh) if p.is_file()), None)
    source_hash = _sha256(source_copy) if source_copy else None

    if not mesh_exists:
        status = "missing_mesh"
        evidence = "coverage inventory has no selected mesh"
    elif not image_exists:
        status = "unresolved_provenance"
        evidence = "selected source image is missing"
    elif source_copy is None:
        status = "unresolved_provenance"
        evidence = "mesh exists but no retained generation-input copy was found"
    elif source_hash != expected_hash:
        status = "confirmed_wrong_source"
        evidence = "retained generation-input hash differs from selected producer source hash"
    else:
        status = "unresolved_provenance"
        evidence = "retained generation-input hash matches selected producer source hash; semantic identity review is not recorded"

    source_kind = row.get("imageInputKind")
    if source_kind == "meshy_remaining_still":
        source_quality = "fallback_extracted_frame; no named AAA upscale"
    else:
        source_quality = source_kind or "missing"
    body_plan, body_evidence = _body_plan(sid, neutral_row)
    result = {
        "status": status,
        "evidence": evidence,
        "mesh": str(mesh).replace("\\", "/") if mesh_exists else None,
        "meshSha256": _sha256(mesh) if mesh_exists else None,
        "selectedImage": str(image).replace("\\", "/") if image_exists else None,
        "selectedImageSha256": expected_hash,
        "selectedImageKind": source_kind,
        "sourceQuality": source_quality,
        "retainedGenerationInput": str(source_copy).replace("\\", "/") if source_copy else None,
        "retainedGenerationInputSha256": source_hash,
        "sourceHashMatchesSelectedImage": bool(source_hash and expected_hash and source_hash == expected_hash),
        "bodyPlan": body_plan,
        "bodyPlanEvidence": body_evidence,
    }
    review = identity_reviews.get(sid)
    if review:
        # A visual source audit may prove a mismatch even when the producer's
        # retained input copy is absent.  Keep the mechanical hashes above and
        # overlay only the reviewed classification and its durable evidence.
        review_status = str(review.get("status") or "")
        if review_status not in {"verified_correct", "confirmed_wrong_source", "missing_mesh", "unresolved_provenance"}:
            raise ValueError(f"Unsupported identity review status for {sid}: {review_status!r}")
        if review.get("meshSha256") != result["meshSha256"]:
            raise ValueError(f"Identity review mesh hash does not match coverage for {sid}")
        if review.get("selectedImageSha256") != result["selectedImageSha256"]:
            raise ValueError(f"Identity review source hash does not match coverage for {sid}")
        result["status"] = review_status
        result["evidence"] = str(review["evidence"])
        result["identityReview"] = {
            "path": str(IDENTITY_REVIEW).replace("\\", "/"),
            "reviewer": review.get("reviewer"),
            "meshSha256": review.get("meshSha256"),
            "selectedImageSha256": review.get("selectedImageSha256"),
            "comparison": review.get("comparison"),
            "action": review.get("action"),
        }
    return result


def _run_evidence(sid: str) -> dict:
    run = RUN_ROOT / sid
    report = run / "report.json"
    run_manifest = run / "run_manifest.json"
    result = {
        "runDir": str(run).replace("\\", "/") if run.is_dir() else None,
        "report": str(report).replace("\\", "/") if report.is_file() else None,
        "status": None,
        "gif": None,
        "clips": [],
        "sharedAdapterEvidence": None,
        "repairManifest": None,
        "repairManifestAttempts": [],
        "repairCandidateOut": None,
        "repairCandidateReport": None,
        "repairCandidateStatus": None,
        "repairCandidateError": None,
        "repairReview": None,
        "repairReviewStatus": None,
        "repairRestOverlay": None,
        "repairKeyframes": None,
        "repairAnimationReel": None,
        "repairDetailReel": None,
        "repairBilateralAudit": None,
    }
    if report.is_file():
        data = _load(report)
        result["status"] = data.get("status")
        result["gif"] = data.get("gif")
        result["clips"] = data.get("clipContractNames", [])
    elif run_manifest.is_file():
        data = _load(run_manifest)
        result["status"] = data.get("status")
    mounted = run / "remaining_forced_mounted_mixamo_horse"
    if (mounted / "authoring/authoring.json").is_file():
        result["sharedAdapterEvidence"] = {
            "route": "existing_mounted_mixamo_horse",
            "authoring": str(mounted / "authoring/authoring.json").replace("\\", "/"),
            "composed": str(mounted / "composed").replace("\\", "/"),
            "proof": "generated-artifact; adapter evidence, not mesh-repair acceptance",
        }
    flyer = run / "remaining_forced_eagle_flyer"
    flyer_report = flyer / "report.json"
    flyer_clips = flyer / "linked_master/clips/clips_manifest.json"
    flyer_candidate = flyer / "linked_master/skin_fit/skin_candidate.glb"
    flyer_contact = next(
        iter(sorted(run.glob(f"**/{sid}_linked_master_contact.png"))), None
    )
    if flyer_report.is_file() and flyer_clips.is_file() and flyer_candidate.is_file() \
            and result["sharedAdapterEvidence"] is None:
        result["sharedAdapterEvidence"] = {
            "route": "existing_eagle_flyer",
            "report": str(flyer_report).replace("\\", "/"),
            "clipsManifest": str(flyer_clips).replace("\\", "/"),
            "candidate": str(flyer_candidate).replace("\\", "/"),
            "contactSheet": str(flyer_contact).replace("\\", "/") if flyer_contact else None,
            "proof": "generated-artifact; adapter evidence, not mesh-repair acceptance",
        }
    zoo = run / "remaining_forced_zoo_turtle"
    zoo_report = zoo / "report.json"
    zoo_clips = zoo / "linked_master/clips/clips_manifest.json"
    zoo_candidate = zoo / "linked_master/skin_fit/skin_candidate.glb"
    zoo_comparison = zoo / "linked_master/skin_fit/skin_comparison.gif"
    if zoo_report.is_file() and zoo_clips.is_file() and zoo_candidate.is_file() \
            and result["sharedAdapterEvidence"] is None:
        result["sharedAdapterEvidence"] = {
            "route": "existing_zoo_turtle_quadruped",
            "report": str(zoo_report).replace("\\", "/"),
            "clipsManifest": str(zoo_clips).replace("\\", "/"),
            "candidate": str(zoo_candidate).replace("\\", "/"),
            "comparison": str(zoo_comparison).replace("\\", "/") if zoo_comparison.is_file() else None,
            "proof": "generated-artifact; adapter evidence, not mesh-repair acceptance",
        }
    if result["sharedAdapterEvidence"] is None:
        zoo_runs = sorted(run.glob("remaining_forced_zoo_*/report.json"))
        for generic_report in zoo_runs:
            generic_root = generic_report.parent
            generic_clips = generic_root / "linked_master/clips/clips_manifest.json"
            generic_candidate = generic_root / "linked_master/skin_fit/skin_candidate.glb"
            generic_comparison = generic_root / "linked_master/skin_fit/skin_comparison.gif"
            if not generic_clips.is_file() or not generic_candidate.is_file():
                continue
            result["sharedAdapterEvidence"] = {
                "route": "existing_zoo_quadruped",
                "report": str(generic_report).replace("\\", "/"),
                "clipsManifest": str(generic_clips).replace("\\", "/"),
                "candidate": str(generic_candidate).replace("\\", "/"),
                "comparison": str(generic_comparison).replace("\\", "/") if generic_comparison.is_file() else None,
                "proof": "generated-artifact; adapter evidence, not mesh-repair acceptance",
            }
            break
    centaur_clips = run / "linked_master/clips/clips_manifest.json"
    centaur_gif = run / "linked_master" / f"{sid}_linked_master.gif"
    centaur_contact = run / "linked_master" / f"{sid}_linked_master_contact.png"
    if sid in CENTAUROID_ADAPTER_IDS and report.is_file() and centaur_clips.is_file() \
            and centaur_contact.is_file() and result["sharedAdapterEvidence"] is None:
        result["sharedAdapterEvidence"] = {
            "route": "existing_centauroid_rider",
            "report": str(report).replace("\\", "/"),
            "clipsManifest": str(centaur_clips).replace("\\", "/"),
            "animationGif": str(centaur_gif).replace("\\", "/") if centaur_gif.is_file() else None,
            "contactSheet": str(centaur_contact).replace("\\", "/"),
            "proof": "generated-artifact; adapter evidence, not mesh-repair acceptance",
        }
    repair_out = OUT_ROOT / "candidates" / sid
    manifest_paths = []
    if FLEET_MANIFEST_ROOT.is_dir():
        manifest_paths.extend(FLEET_MANIFEST_ROOT.glob("*.json"))
    candidate_manifest_root = OUT_ROOT / "candidates"
    if candidate_manifest_root.is_dir():
        manifest_paths.extend(candidate_manifest_root.rglob("manifest.json"))
    manifests = sorted(set(manifest_paths))
    attempts = []
    for manifest in manifests:
        data = _load(manifest)
        job = next((item for item in data.get("jobs", []) if item.get("unit") == sid), None)
        if job is None:
            continue
        candidate_out = Path(str(job.get("out") or ""))
        if not candidate_out.is_absolute():
            candidate_out = ROOT / candidate_out
        candidate_report = candidate_out / "report.json"
        attempt = {
            "manifest": str(manifest).replace("\\", "/"),
            "candidateOut": str(candidate_out).replace("\\", "/"),
            "candidateReport": str(candidate_report).replace("\\", "/") if candidate_report.is_file() else None,
            "status": None,
            "error": None,
        }
        if candidate_report.is_file():
            report_data = _load(candidate_report)
            attempt["status"] = report_data.get("status")
            attempt["error"] = report_data.get("error")
        attempts.append(attempt)
    if attempts:
        latest = attempts[-1]
        result["repairManifest"] = latest["manifest"]
        result["repairManifestAttempts"] = attempts
        result["repairCandidateOut"] = latest["candidateOut"]
        result["repairCandidateReport"] = latest["candidateReport"]
        result["repairCandidateStatus"] = latest["status"]
        result["repairCandidateError"] = latest["error"]
    review_candidates = sorted(repair_out.glob("*/review.json")) if repair_out.is_dir() else []
    # Versioned candidate directories are retained as comparisons.  The newest
    # review is the active handoff evidence; choosing the first path would keep
    # a superseded repair visible after a shared adapter fix.
    review = review_candidates[-1] if review_candidates else None
    if review is not None:
        data = _load(review)
        result["repairReview"] = str(review).replace("\\", "/")
        result["repairReviewStatus"] = data.get("disposition")
        # Prefer explicitly marked high-resolution replays over the older generic
        # reel fields.  Historical reviews may retain both; the ledger must point
        # consumers at the evidence that was actually used for visual acceptance.
        review_fields = (
            ("restOverlay", "repairRestOverlay"),
            ("keyframes", "repairKeyframes"),
            ("animationReel", "repairAnimationReel"),
            ("detailAnimationReel", "repairDetailReel"),
            ("highResolutionReplay", "repairDetailReel"),
            ("bilateralAudit", "repairBilateralAudit"),
        )
        for key, result_key in review_fields:
            value = data.get(key)
            if value:
                # Some reviews retain bilateral metrics beside the report
                # path.  The ledger field is intentionally a path so later
                # consumers can open the artifact without stringifying the
                # whole diagnostic object.
                if isinstance(value, dict):
                    value = value.get("report")
                if not value:
                    continue
                path = Path(str(value))
                if not path.is_absolute():
                    path = ROOT / path
                result[result_key] = str(path).replace("\\", "/")
    return result


def build_queue() -> tuple[dict, dict, dict]:
    sys.path.insert(0, str(Path(__file__).parent))
    from audit_homm3_mesh_coverage import build_inventory

    import_manifest = _load(IMPORT_MANIFEST)
    neutral_data = _load(NEUTRAL_CATALOG)
    identity_review_data = _load(IDENTITY_REVIEW) if IDENTITY_REVIEW.is_file() else {}
    identity_reviews = identity_review_data.get("reviews", {})
    coverage = build_inventory()
    neutral_by_sid = {str(row["sid"]): row for row in neutral_data.get("units", [])}
    import_ids = [str(row["unitSid"]) for row in import_manifest.get("units", [])]
    import_set = set(import_ids)
    stated_roster_count = 261
    # There is no trustworthy second membership source in this checkout.  Do
    # not manufacture a 261-member queue by dropping whichever ID sorts last;
    # freeze all source-defined IDs and leave the one-member reconciliation to
    # the user-facing handoff.
    candidate_ids = sorted(import_set)

    coverage_by_sid = {str(row["unitSid"]): row for row in coverage["records"]}
    rows = []
    for sid in candidate_ids:
        coverage_row = coverage_by_sid.get(sid, {})
        identity = _identity(sid, coverage_row, neutral_by_sid.get(sid), identity_reviews)
        animation_evidence = _run_evidence(sid)
        review_status = animation_evidence.get("repairReviewStatus")
        candidate_status = animation_evidence.get("repairCandidateStatus")
        if sid in EXCLUSIONS:
            processing_state = EXCLUSIONS[sid]
        elif candidate_status == "error":
            error_text = str(animation_evidence.get("repairCandidateError") or "")
            source_error = any(token in error_text for token in (
                "No such file", "reference", "toes point along its hip-to-hip axis",
            ))
            processing_state = "needs_source" if source_error else "needs_shared_adapter"
        elif candidate_status == "running":
            processing_state = "working"
        elif review_status:
            processing_state = review_status
        else:
            processing_state = "queued"
        repair = {
            "processingState": processing_state,
            "excluded": sid in EXCLUSIONS,
            "candidate": str(REPAIR_ROOT / sid).replace("\\", "/") if (REPAIR_ROOT / sid).is_dir() else None,
            "animationEvidence": animation_evidence,
        }
        rows.append({
            "unitSid": sid,
            "scope": "animation_roster",
            "identity": identity,
            "repair": repair,
        })

    catalog_only = []
    for sid in sorted(set(neutral_by_sid) - set(candidate_ids)):
        coverage_row = coverage_by_sid.get(sid, {})
        catalog_only.append({
            "unitSid": sid,
            "scope": "neutral_catalog_only",
            "identity": _identity(sid, coverage_row, neutral_by_sid.get(sid), identity_reviews),
            "repair": {"processingState": "catalog_only", "excluded": False},
        })

    source_files = [IMPORT_MANIFEST, NEUTRAL_CATALOG, COVERAGE]
    if SCHEDULER.is_file():
        source_files.append(SCHEDULER)
    source_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): _sha256(p) for p in source_files}
    exclusions = [{"unitSid": sid, "reason": reason} for sid, reason in sorted(EXCLUSIONS.items())]
    queue = {
        "schema": "homm3.mesh-repair-fleet-queue.v1",
        "proof": "source/static queue freeze; not animation or runtime proof",
        "createdFrom": {
            "importManifest": str(IMPORT_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
            "neutralCatalog": str(NEUTRAL_CATALOG.relative_to(ROOT)).replace("\\", "/"),
            "coverageInventory": str(COVERAGE.relative_to(ROOT)).replace("\\", "/"),
        },
        "sourceHashes": source_hashes,
        "sourceHashesDigest": _canonical_sha256(source_hashes),
        "membership": {
            "statedUserRosterCount": stated_roster_count,
            "importManifestCount": len(import_ids),
            "candidateRosterCount": len(candidate_ids),
            "candidateRosterRule": "all source-defined import IDs retained until user identifies the one ID outside the stated 261-member roster",
            "ambiguousImportOnlyIds": None,
            "ambiguousImportOnlyIdsEvidence": "The handoff supplies the requested roster as a count only; no authoritative 261-ID membership list is present in the checkout, so the import-only difference set cannot be computed without inventing a membership rule.",
            "unresolvedDelta": len(candidate_ids) - stated_roster_count,
            "status": "needs_user_confirmation" if len(candidate_ids) != stated_roster_count else "resolved",
        },
        "exclusions": exclusions,
        "animationRoster": rows,
        "catalogOnlyNeutral": catalog_only,
    }
    ledger = {
        "schema": "homm3.mesh-repair-fleet-ledger.v1",
        "proof": "candidate-production ledger; generated and user-visible animation proof remain per-row",
        "queueDigest": _canonical_sha256(queue["animationRoster"]),
        "counts": {
            "animationRoster": len(rows),
            "catalogOnlyNeutral": len(catalog_only),
            "identityVerifiedCorrect": sum(r["identity"]["status"] == "verified_correct" for r in rows),
            "identityConfirmedWrongSource": sum(r["identity"]["status"] == "confirmed_wrong_source" for r in rows),
            "identityMissingMesh": sum(r["identity"]["status"] == "missing_mesh" for r in rows),
            "identityUnresolvedProvenance": sum(r["identity"]["status"] == "unresolved_provenance" for r in rows),
            "reviewedAnimationCandidates": sum(
                r["repair"]["animationEvidence"].get("repairReviewStatus")
                in {"candidate_reviewed", "rejected_needs_shared_adapter"}
                for r in rows
            ),
            "reviewedAdapterEvidence": sum(
                bool(r["repair"]["animationEvidence"].get("repairReview"))
                and r["repair"]["animationEvidence"].get("repairReviewStatus")
                not in {"candidate_reviewed", "rejected_needs_shared_adapter"}
                for r in rows
            ),
            "unresolvedRepairWork": len(rows) - len(EXCLUSIONS),
            "excludedPilots": len(EXCLUSIONS),
        },
        "rows": rows,
        "catalogOnlyNeutral": catalog_only,
    }
    neutral_audit = {
        "schema": "homm3.neutral-source-identity-audit.v1",
        "proof": "source/static plus retained source-copy hash evidence",
        "catalogCount": len(neutral_by_sid),
        "animationRosterNeutralCount": sum(r["unitSid"] in neutral_by_sid for r in rows),
        "rows": [r for r in rows if r["unitSid"] in neutral_by_sid] + catalog_only,
    }
    return queue, ledger, neutral_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    queue, ledger, neutral_audit = build_queue()
    for name, value in (("queue.json", queue), ("ledger.json", ledger), ("neutral_identity_audit.json", neutral_audit)):
        (out / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "counts": ledger["counts"], "membership": queue["membership"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
