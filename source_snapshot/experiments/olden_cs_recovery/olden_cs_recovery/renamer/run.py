"""Renamer + Auditor orchestration for Phase 2 rename oracle."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import (
    ALLOWED_STAGE_TRANSITIONS,
    PACKAGE_ROOT,
    PROOF_LEDGER_ENTRIES_DIR,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import (
    method_id_to_filename,
    release_item,
    to_iso,
    utc_now,
    write_queue_item,
)
from olden_cs_recovery.renamer.apply import (
    apply_to_recovered,
    build_member_renames,
    make_rename_entry,
    write_rename_entry,
)
from olden_cs_recovery.renamer.collisions import (
    audit_rename_collisions,
    check_proposal,
    load_rename_index,
    register_in_index,
    write_rename_index,
)
from olden_cs_recovery.renamer.evidence import auto_accept_allowed, classify_candidate, has_second_evidence
from olden_cs_recovery.renamer.mono_map import MonoSemanticMap, load_mono_map
from olden_cs_recovery.schema_validate import validate_instance


def _rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def ledger_path_for(method_id: str) -> Path:
    return PROOF_LEDGER_ENTRIES_DIR / method_id_to_filename(method_id)


def write_ledger_rename(
    item: dict[str, Any],
    *,
    status: str,
    rename_entry_path: Path | None,
    notes: str,
    previous_status: str | None,
    blocked_reason: str | None = None,
) -> Path:
    PROOF_LEDGER_ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, Any]] = []
    # Preserve prior evidence refs from existing ledger when present.
    prior_path = ledger_path_for(item["method_id"])
    if prior_path.is_file():
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8-sig"))
            for ref in prior.get("evidence_refs") or []:
                cleaned = {"kind": str(ref.get("kind")), "path": str(ref.get("path"))}
                if ref.get("notes"):
                    cleaned["notes"] = str(ref["notes"])
                evidence.append(cleaned)
        except (OSError, json.JSONDecodeError):
            pass
    for ref in item.get("evidence_refs") or []:
        cleaned = {"kind": str(ref.get("kind")), "path": str(ref.get("path"))}
        if ref.get("notes"):
            cleaned["notes"] = str(ref["notes"])
        # Avoid exact duplicates
        if cleaned not in evidence:
            evidence.append(cleaned)
    # Mono map evidence
    mono_ref = {
        "kind": "mono_semantic_map",
        "path": "experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json",
        "notes": "Phase 2 rename oracle",
    }
    if mono_ref not in evidence:
        evidence.append(mono_ref)
    if rename_entry_path is not None:
        evidence.append(
            {
                "kind": "other",
                "path": _rel_repo(rename_entry_path),
                "notes": f"rename_map decision → {status}",
            }
        )
    entry = {
        "schema_version": 1,
        "method_id": item["method_id"],
        "status": status,
        "previous_status": previous_status,
        "blocked_reason": blocked_reason,
        "evidence_refs": evidence,
        "updated_at": to_iso(utc_now()),
        "notes": notes,
    }
    validate_instance("proof_ledger_entry.schema.json", entry, item["method_id"])
    path = ledger_path_for(item["method_id"])
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _decide_for_type(
    *,
    mono_map: MonoSemanticMap,
    current_type_name: str,
    queue_item: dict[str, Any],
    index: dict[str, Any],
) -> dict[str, Any]:
    """
    Produce a type-level rename decision. Never invents Mono matches.
    """
    match = mono_map.lookup_type(current_type_name)
    if match.skip_reason or not match.mono_full:
        return {
            "decision": "skipped",
            "match": match,
            "evidence_classes": [],
            "second_evidence_present": False,
            "collision_reason": None,
            "skip_reason": match.skip_reason or "empty Mono proposal (fail closed)",
            "notes": match.skip_reason or "No Mono match; proposal left empty.",
        }

    manual_evidence = None
    if match.source == "manualTypeAliases" and match.candidate:
        manual_evidence = list(match.candidate.get("reasons") or [])

    evidence_classes = classify_candidate(
        match.candidate,
        queue_item=queue_item,
        manual_evidence=manual_evidence,
    )
    second = has_second_evidence(evidence_classes)
    confidence = match.confidence

    verdict = check_proposal(
        mono_map=mono_map,
        current_type_name=current_type_name,
        proposed_mono_full=match.mono_full,
        index=index,
    )
    if not verdict.ok:
        return {
            "decision": "collision-rejected",
            "match": match,
            "evidence_classes": sorted(evidence_classes),
            "second_evidence_present": second,
            "collision_reason": verdict.reason,
            "skip_reason": None,
            "notes": f"Auditor collision reject: {verdict.reason}",
        }

    if auto_accept_allowed(confidence=confidence, evidence_classes=evidence_classes):
        second_hit = sorted(
            evidence_classes
            & {"signature_shape", "string_loc_anchor", "call_neighborhood"}
        )
        return {
            "decision": "renamed-accepted",
            "match": match,
            "evidence_classes": sorted(evidence_classes),
            "second_evidence_present": second,
            "collision_reason": None,
            "skip_reason": None,
            "notes": (
                f"Auto-accepted: confidence=strong-static with second evidence {second_hit}."
            ),
        }

    # probable-static / weaker / strong without second evidence → proposal only
    if confidence == "strong-static" and not second:
        note = (
            "strong-static but missing mandatory second evidence class "
            "(signature_shape | string_loc_anchor | call_neighborhood); proposal only."
        )
    else:
        note = (
            f"confidence={confidence!r} is not auto-eligible "
            "(only strong-static + second evidence auto-applies); proposal only."
        )
    return {
        "decision": "renamed-proposed",
        "match": match,
        "evidence_classes": sorted(evidence_classes),
        "second_evidence_present": second,
        "collision_reason": None,
        "skip_reason": None,
        "notes": note,
    }


def rename_claimed_items(
    claimed: list[tuple[Path, dict[str, Any]]],
    *,
    holder: str,
) -> dict[str, Any]:
    """
    Rename oracle for claimed stage=rename items.

    - Auto-apply only strong-static + second evidence (Auditor collision-clean).
    - probable-static / weaker → renamed-proposed; stay at rename.
    - Missing map → skipped (empty proposal); stay at rename with static-lifted.
    - renamed-accepted → advance rename → oracle_capture.
    """
    if not claimed:
        return {
            "ok": True,
            "renamed_accepted": [],
            "renamed_proposed": [],
            "skipped": [],
            "collision_rejected": [],
            "auditor": None,
        }

    mono_map = load_mono_map()
    index = load_rename_index()

    # Group by type so parallel method claims on one type share one type decision.
    by_type: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path, item in claimed:
        type_name = item.get("type_name") or item["method_id"].split("::", 1)[0]
        by_type[type_name].append((path, item))

    accepted: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []

    for type_name, group in sorted(by_type.items(), key=lambda kv: kv[0]):
        # Use first queue item as evidence context (same type share DiffableCs).
        sample_item = group[0][1]
        decided = _decide_for_type(
            mono_map=mono_map,
            current_type_name=type_name,
            queue_item=sample_item,
            index=index,
        )
        match = decided["match"]
        decision = decided["decision"]
        evidence_classes = list(decided["evidence_classes"])
        member_renames = build_member_renames(match.candidate)

        recovered_paths: list[str] = []
        applied = False
        if decision in ("renamed-accepted", "renamed-proposed") and match.mono_full:
            recovered_paths = apply_to_recovered(
                current_type_name=type_name,
                proposed_mono_full=match.mono_full,
                decision=decision,
                confidence=match.confidence,
                evidence_classes=evidence_classes,
                domain=sample_item.get("domain"),
            )
            applied = bool(recovered_paths) or decision == "renamed-proposed"
            # Proposal may lack recovered file for some edb shapes; still record map entry.

        entry = make_rename_entry(
            current_type_name=type_name,
            proposed_mono_full=match.mono_full,
            mono_namespace=match.mono_namespace,
            mono_simple=match.mono_simple,
            decision=decision,
            confidence=match.confidence,
            evidence_classes=evidence_classes,
            second_evidence_present=bool(decided["second_evidence_present"]),
            map_score=match.score,
            map_reasons=list(match.reasons),
            method_id=sample_item["method_id"],
            member_renames=member_renames,
            collision_reason=decided.get("collision_reason"),
            skip_reason=decided.get("skip_reason"),
            applied_to_recovered=applied and bool(recovered_paths),
            recovered_paths=recovered_paths,
            mono_map_path=_rel_repo(mono_map.path),
            notes=str(decided.get("notes") or ""),
        )
        entry_path = write_rename_entry(entry)

        if decision in ("renamed-accepted", "renamed-proposed"):
            index = register_in_index(
                index,
                current_type_name=type_name,
                proposed_mono_full=match.mono_full,
                decision=decision,
                method_id=sample_item["method_id"],
            )

        for path, item in group:
            previous = item.get("proof_status")
            if decision == "renamed-accepted":
                status = "renamed-accepted"
                updated = dict(item)
                if "oracle_capture" not in ALLOWED_STAGE_TRANSITIONS.get("rename", frozenset()):
                    raise SystemExit("FAIL: internal — rename→oracle_capture not allowed")
                updated["stage"] = "oracle_capture"
                updated["proof_status"] = status
                updated["blocked_reason"] = None
                updated["notes"] = (
                    (item.get("notes") or "")
                    + f" | Phase 2 renamed-accepted → {match.mono_full}"
                ).strip(" |")
                updated["updated_at"] = to_iso(utc_now())
                # Attach mono map evidence on queue item
                refs = list(updated.get("evidence_refs") or [])
                mono_ev = {
                    "kind": "mono_semantic_map",
                    "path": "experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json",
                    "required": True,
                    "notes": f"accepted → {match.mono_full}",
                }
                if mono_ev not in refs:
                    refs.append(mono_ev)
                updated["evidence_refs"] = refs
                write_ledger_rename(
                    item,
                    status=status,
                    rename_entry_path=entry_path,
                    notes=str(decided.get("notes") or ""),
                    previous_status=previous,
                )
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=path)
                accepted.append(
                    {
                        "method_id": item["method_id"],
                        "type_name": type_name,
                        "mono_type": match.mono_full,
                        "stage": "oracle_capture",
                        "rename_entry": _rel_repo(entry_path),
                    }
                )
            elif decision == "renamed-proposed":
                status = "renamed-proposed"
                updated = dict(item)
                updated["stage"] = "rename"  # stay
                updated["proof_status"] = status
                updated["blocked_reason"] = None
                updated["notes"] = (
                    (item.get("notes") or "")
                    + f" | Phase 2 renamed-proposed → {match.mono_full}"
                ).strip(" |")
                updated["updated_at"] = to_iso(utc_now())
                write_ledger_rename(
                    item,
                    status=status,
                    rename_entry_path=entry_path,
                    notes=str(decided.get("notes") or ""),
                    previous_status=previous,
                )
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=path)
                proposed.append(
                    {
                        "method_id": item["method_id"],
                        "type_name": type_name,
                        "mono_type": match.mono_full,
                        "stage": "rename",
                        "rename_entry": _rel_repo(entry_path),
                        "reason": decided.get("notes"),
                    }
                )
            elif decision == "collision-rejected":
                # Fail closed: block unsafe rename rather than silently accept.
                reason = decided.get("collision_reason") or "collision rejected"
                updated = dict(item)
                updated["stage"] = "blocked"
                updated["proof_status"] = "blocked"
                updated["blocked_reason"] = reason
                updated["updated_at"] = to_iso(utc_now())
                write_ledger_rename(
                    item,
                    status="blocked",
                    rename_entry_path=entry_path,
                    notes=str(decided.get("notes") or ""),
                    previous_status=previous,
                    blocked_reason=reason,
                )
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=path)
                collisions.append(
                    {
                        "method_id": item["method_id"],
                        "type_name": type_name,
                        "reason": reason,
                        "rename_entry": _rel_repo(entry_path),
                    }
                )
            else:  # skipped
                reason = decided.get("skip_reason") or "skipped"
                updated = dict(item)
                # Stay at rename; keep static-lifted; empty proposal recorded in rename_map.
                updated["stage"] = "rename"
                updated["proof_status"] = previous or "static-lifted"
                updated["notes"] = (
                    (item.get("notes") or "") + f" | Phase 2 rename skipped: {reason}"
                ).strip(" |")
                updated["updated_at"] = to_iso(utc_now())
                # Do not overwrite ledger status away from static-lifted; append note via rename entry only.
                # Still write a ledger note preserving static-lifted.
                write_ledger_rename(
                    item,
                    status=previous or "static-lifted",
                    rename_entry_path=entry_path,
                    notes=f"Rename skipped (empty proposal). {reason}",
                    previous_status=previous,
                )
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=path)
                skipped.append(
                    {
                        "method_id": item["method_id"],
                        "type_name": type_name,
                        "reason": reason,
                        "rename_entry": _rel_repo(entry_path),
                    }
                )

    write_rename_index(index)
    auditor = audit_rename_collisions(mono_map=mono_map)

    ok = auditor.get("ok", False) and not collisions
    return {
        "ok": ok,
        "renamed_accepted": accepted,
        "renamed_proposed": proposed,
        "skipped": skipped,
        "collision_rejected": collisions,
        "counts": {
            "renamed_accepted": len(accepted),
            "renamed_proposed": len(proposed),
            "skipped": len(skipped),
            "collision_rejected": len(collisions),
        },
        "mono_map_path": _rel_repo(mono_map.path),
        "rename_map_index": _rel_repo(PACKAGE_ROOT / "rename_map" / "index.json"),
        "auditor": auditor,
        "stage_rules": {
            "renamed-accepted": "advance rename → oracle_capture",
            "renamed-proposed": "remain at rename",
            "skipped": "remain at rename; proof_status stays static-lifted; empty proposal",
            "collision-rejected": "stage=blocked (fail closed)",
        },
        "note": (
            "Phase 2 rename oracle only. Does not capture oracle traces or run EquivTester. "
            "Auto-accept requires strong-static + second evidence class; "
            "probable-static and weaker stay proposals."
        ),
    }
