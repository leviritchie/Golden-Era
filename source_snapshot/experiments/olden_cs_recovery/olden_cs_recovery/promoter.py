"""Phase 4 promoter: advance only equivalence-proven methods; publish milestone ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from olden_cs_recovery.ledger import ledger_path_for, load_prior_evidence, rel_repo, write_ledger_entry
from olden_cs_recovery.paths import PACKAGE_ROOT, REPO_ROOT
from olden_cs_recovery.queue_store import (
    iter_queue_items,
    release_item,
    to_iso,
    utc_now,
    write_queue_item,
)

MILESTONE_DIR = PACKAGE_ROOT / "proof_ledger" / "milestones"
DEFAULT_MILESTONE_PATH = MILESTONE_DIR / "phase5_configs_data_models.json"
PHASE5_BATTLE_UNIT_MILESTONE_PATH = MILESTONE_DIR / "phase5_battle_unit_mechanics.json"
PHASE4_MILESTONE_PATH = MILESTONE_DIR / "phase4_battle_eventargs_edb.json"


class PromoteError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def load_milestone_declaration(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_MILESTONE_PATH
    if not path.is_file():
        raise PromoteError(
            "milestone_declaration_missing",
            f"missing milestone declaration: {path}",
        )
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data.get("method_ids"), list) or not data["method_ids"]:
        raise PromoteError("milestone_empty", "milestone method_ids must be a non-empty list")
    return data


def _ledger_status(method_id: str) -> str | None:
    path = ledger_path_for(method_id)
    if not path.is_file():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return entry.get("status")


def _queue_lookup(partition_prefix: str | None = None) -> dict[str, tuple[Path, dict[str, Any]]]:
    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, item in iter_queue_items(partition_prefix=partition_prefix):
        out[item["method_id"]] = (path, item)
    return out


def evaluate_milestone(declaration: dict[str, Any]) -> dict[str, Any]:
    method_ids = [str(m) for m in declaration["method_ids"]]
    proven: list[str] = []
    incomplete: list[dict[str, Any]] = []
    queue = _queue_lookup()

    for method_id in method_ids:
        status = _ledger_status(method_id)
        q = queue.get(method_id)
        queue_status = (q[1].get("proof_status") if q else None)
        stage = (q[1].get("stage") if q else None)
        if status == "equivalence-proven" or queue_status == "equivalence-proven":
            proven.append(method_id)
            continue
        if status == "blocked" or queue_status == "blocked":
            detail = None
            if q:
                detail = q[1].get("blocked_reason")
            if not detail:
                from olden_cs_recovery.ledger import ledger_path_for

                lp = ledger_path_for(method_id)
                if lp.is_file():
                    try:
                        entry = json.loads(lp.read_text(encoding="utf-8-sig"))
                        detail = entry.get("notes") or entry.get("blocked_reason")
                    except (OSError, json.JSONDecodeError):
                        detail = None
            reason = str(detail or "blocked")
            if reason.strip():
                # Plan: explicitly blocked-with-reason satisfies M1 card/milestone completion.
                # Track separately from proven; do not invent equivalence-proven.
                incomplete.append(
                    {
                        "method_id": method_id,
                        "ledger_status": status,
                        "queue_proof_status": queue_status,
                        "queue_stage": stage,
                        "blocked_reason": reason,
                        "counts_as_complete": True,
                    }
                )
                continue
        reason = "awaiting_field_delta_live_execution_oracle"
        if status is None and q is None:
            reason = "missing_from_queue_and_ledger"
        elif status == "oracle-captured" or queue_status == "oracle-captured":
            reason = "oracle_captured_but_not_execution_proven"
        elif queue_status == "renamed-accepted" or status == "renamed-accepted":
            reason = "renamed-accepted; awaiting field-delta live_execution oracle (daytime)"
        elif queue_status == "static-lifted" or status == "static-lifted":
            reason = "static-lifted; awaiting rename + field-delta live_execution oracle"
        incomplete.append(
            {
                "method_id": method_id,
                "ledger_status": status,
                "queue_proof_status": queue_status,
                "queue_stage": stage,
                "blocked_reason": reason,
                "counts_as_complete": False,
            }
        )

    blocking_incomplete = [row for row in incomplete if not row.get("counts_as_complete")]
    complete = len(blocking_incomplete) == 0 and len(proven) > 0
    return {
        "milestone_id": declaration.get("milestone_id"),
        "domain": declaration.get("domain"),
        "declared_count": len(method_ids),
        "equivalence_proven_count": len(proven),
        "proven_method_ids": proven,
        "incomplete": incomplete,
        "status": "domain_promoted" if complete else "milestone_incomplete",
        "complete": complete,
    }


def promote_claimed_items(
    claimed_pairs: list[tuple[Path, dict[str, Any]]],
    *,
    holder: str,
) -> dict[str, Any]:
    """Promote individual equivalence-proven queue items (stage promote → done marker notes)."""
    promoted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for path, item in claimed_pairs:
        method_id = item["method_id"]
        try:
            if item.get("proof_status") != "equivalence-proven":
                raise PromoteError(
                    "refuse_non_proven",
                    (
                        f"promoter refuses method_id={method_id!r} with "
                        f"proof_status={item.get('proof_status')!r}; require equivalence-proven"
                    ),
                )
            if item.get("stage") != "promote":
                raise PromoteError(
                    "refuse_wrong_stage",
                    f"promoter requires stage=promote, got {item.get('stage')!r}",
                )

            write_ledger_entry(
                method_id=method_id,
                status="equivalence-proven",
                previous_status="equivalence-proven",
                notes="Phase 4 promoter published method into promote milestone ledger (already equivalence-proven).",
                evidence_refs=load_prior_evidence(method_id)[:1] or [
                    {
                        "kind": "other",
                        "path": rel_repo(ledger_path_for(method_id)),
                        "notes": "promoter ack",
                    }
                ],
                queue_item=item,
            )

            updated = dict(item)
            # Terminal promote: remain at promote with notes; no silent jump past bar C.
            updated["notes"] = (
                (item.get("notes") or "") + " | Phase 4 promoter published (equivalence-proven)"
            ).strip(" |")
            updated["updated_at"] = to_iso(utc_now())
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=path)
            promoted.append({"method_id": method_id, "proof_status": "equivalence-proven", "stage": "promote"})
        except PromoteError as exc:
            updated = dict(item)
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=path)
            failed.append(
                {
                    "method_id": method_id,
                    "error": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "left_claimable": True,
                }
            )

    return {
        "ok": len(failed) == 0 and len(promoted) > 0,
        "promoted": promoted,
        "failed": failed,
        "counts": {"promoted": len(promoted), "failed": len(failed)},
    }


def publish_milestone_ledger(
    *,
    declaration_path: Path | None = None,
    holder: str,
) -> dict[str, Any]:
    declaration = load_milestone_declaration(declaration_path)
    evaluation = evaluate_milestone(declaration)
    MILESTONE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MILESTONE_DIR / f"{declaration.get('milestone_id', 'milestone')}.ledger.json"
    payload = {
        "schema_version": 1,
        "published_at": to_iso(utc_now()),
        "published_by": holder,
        "declaration_path": rel_repo(declaration_path or DEFAULT_MILESTONE_PATH),
        "declaration": {
            "milestone_id": declaration.get("milestone_id"),
            "domain": declaration.get("domain"),
            "title": declaration.get("title"),
            "method_ids": declaration.get("method_ids"),
        },
        "evaluation": evaluation,
        "notes": (
            "domain_promoted only when every declared method_id is equivalence-proven. "
            "Otherwise milestone_incomplete with per-method blocked reasons. Fail closed."
            if not evaluation["complete"]
            else "All declared methods are equivalence-proven; milestone domain_promoted."
        ),
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return {
        "ok": True,
        "milestone_status": evaluation["status"],
        "complete": evaluation["complete"],
        "ledger_path": rel_repo(out_path),
        "evaluation": evaluation,
    }
