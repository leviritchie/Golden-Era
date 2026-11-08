"""Shared proof-ledger writers (fail-closed vocabulary)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import PROOF_LEDGER_ENTRIES_DIR, PROOF_STATUSES, REPO_ROOT
from olden_cs_recovery.queue_store import method_id_to_filename, to_iso, utc_now
from olden_cs_recovery.schema_validate import validate_instance


def rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def ledger_path_for(method_id: str) -> Path:
    return PROOF_LEDGER_ENTRIES_DIR / method_id_to_filename(method_id)


def load_prior_evidence(method_id: str) -> list[dict[str, Any]]:
    path = ledger_path_for(method_id)
    if not path.is_file():
        return []
    try:
        prior = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for ref in prior.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        cleaned: dict[str, Any] = {"kind": str(ref.get("kind")), "path": str(ref.get("path"))}
        if ref.get("notes"):
            cleaned["notes"] = str(ref["notes"])
        out.append(cleaned)
    return out


def merge_evidence(
    existing: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = list(existing)
    for ref in extra:
        cleaned: dict[str, Any] = {"kind": str(ref["kind"]), "path": str(ref["path"])}
        if ref.get("notes"):
            cleaned["notes"] = str(ref["notes"])
        if cleaned not in out:
            out.append(cleaned)
    return out


def write_ledger_entry(
    *,
    method_id: str,
    status: str,
    previous_status: str | None,
    notes: str,
    evidence_refs: list[dict[str, Any]],
    blocked_reason: str | None = None,
    queue_item: dict[str, Any] | None = None,
) -> Path:
    if status not in PROOF_STATUSES:
        raise SystemExit(f"FAIL: illegal proof_status {status!r}")
    PROOF_LEDGER_ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    evidence = load_prior_evidence(method_id)
    if queue_item is not None:
        for ref in queue_item.get("evidence_refs") or []:
            cleaned: dict[str, Any] = {"kind": str(ref.get("kind")), "path": str(ref.get("path"))}
            if ref.get("notes"):
                cleaned["notes"] = str(ref["notes"])
            if cleaned not in evidence:
                evidence.append(cleaned)
    evidence = merge_evidence(evidence, evidence_refs)
    entry = {
        "schema_version": 1,
        "method_id": method_id,
        "status": status,
        "previous_status": previous_status,
        "blocked_reason": blocked_reason,
        "evidence_refs": evidence,
        "updated_at": to_iso(utc_now()),
        "notes": notes,
    }
    validate_instance("proof_ledger_entry.schema.json", entry, method_id)
    path = ledger_path_for(method_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
