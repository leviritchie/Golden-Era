"""Classify Mono semantic-map reasons into evidence classes (fail-closed)."""

from __future__ import annotations

import re
from typing import Any

# Second-evidence classes required (in addition to strong-static) for auto-accept.
SECOND_EVIDENCE_CLASSES = frozenset(
    {"signature_shape", "string_loc_anchor", "call_neighborhood"}
)

_NAME_IDENTITY_PREFIXES = (
    "exact full type name",
    "exact simple type name",
    "namespace/name token overlap",
)

_SIGNATURE_SHAPE_PREFIXES = (
    "method-name overlap",
    "public-method overlap",
    "param-count histogram similarity",
    "method-count closeness",
    "field-count closeness",
    "same parameter count",
    "same method name",
    "same field name",
    "same owner type",
    "same declaration ordinal",
    "same public flag",
    "same private flag",
    "same static flag",
    "same virtual flag",
)

_STRING_LOC_RE = re.compile(
    r"\b(string|loc|source.?line|diffable|path.?anchor|literal)\b",
    re.IGNORECASE,
)

_CALL_NEIGHBORHOOD_RE = re.compile(
    r"\b(call|callee|caller|neighborhood|used by|implemented by|paired with|inherits|derives)\b",
    re.IGNORECASE,
)

_MANUAL_SHAPE_RE = re.compile(
    r"\b(shape|signature|constructor|overload|accessor|callback|method)\b",
    re.IGNORECASE,
)


def classify_reason(reason: str) -> set[str]:
    """Map one map reason string to zero or more evidence class tags."""
    text = (reason or "").strip()
    if not text:
        return set()
    classes: set[str] = set()
    lower = text.lower()
    for prefix in _NAME_IDENTITY_PREFIXES:
        if lower.startswith(prefix) or text.startswith(prefix):
            classes.add("name_identity")
            break
    for prefix in _SIGNATURE_SHAPE_PREFIXES:
        if lower.startswith(prefix) or text.startswith(prefix):
            classes.add("signature_shape")
            break
    if _STRING_LOC_RE.search(text):
        classes.add("string_loc_anchor")
    if _CALL_NEIGHBORHOOD_RE.search(text):
        classes.add("call_neighborhood")
    if _MANUAL_SHAPE_RE.search(text) and "signature_shape" not in classes:
        # Manual alias evidence often describes member shape without score prefixes.
        if "exact" not in lower and "overlap" not in lower:
            classes.add("signature_shape")
    return classes


def classify_candidate(
    candidate: dict[str, Any] | None,
    *,
    queue_item: dict[str, Any] | None = None,
    manual_evidence: list[str] | None = None,
) -> set[str]:
    """
    Collect evidence classes for a map candidate.

    Auto-accept requires strong-static confidence (checked by caller) PLUS at least
    one second evidence class from SECOND_EVIDENCE_CLASSES.
    """
    classes: set[str] = set()
    if candidate is None and not manual_evidence:
        return classes

    reasons: list[str] = []
    if candidate is not None:
        reasons.extend(str(r) for r in (candidate.get("reasons") or []))
        # Shared member names are signature-shape evidence.
        if candidate.get("sharedMethodNames") or candidate.get("sharedFieldNames"):
            classes.add("signature_shape")
        alignment = candidate.get("memberAlignment") or {}
        if alignment.get("exactMethodNameAlignment") or alignment.get("exactFieldNameAlignment"):
            classes.add("signature_shape")
        deobf = candidate.get("deobf") or {}
        deobf_path = str(deobf.get("path") or "").replace("\\", "/")
        if deobf_path and queue_item is not None:
            # DiffableCs path corroboration between map row and queue evidence = LOC anchor.
            for ref in queue_item.get("evidence_refs") or []:
                if ref.get("kind") != "diffable_cs":
                    continue
                ref_path = str(ref.get("path") or "").replace("\\", "/")
                if not ref_path:
                    continue
                deobf_norm = deobf_path.replace("\\", "/")
                if (
                    deobf_norm.endswith(ref_path.split("DiffableCs/")[-1])
                    or ref_path.endswith(deobf_norm.split("DiffableCs/")[-1])
                    or deobf_norm in ref_path
                    or ref_path in deobf_norm
                ):
                    classes.add("string_loc_anchor")
                    break

    if manual_evidence:
        reasons.extend(str(r) for r in manual_evidence)

    for reason in reasons:
        classes |= classify_reason(reason)

    return classes


def has_second_evidence(classes: set[str]) -> bool:
    return bool(classes & SECOND_EVIDENCE_CLASSES)


def auto_accept_allowed(*, confidence: str | None, evidence_classes: set[str]) -> bool:
    """Plan rule: strong-static AND a second evidence class."""
    if confidence != "strong-static":
        return False
    return has_second_evidence(evidence_classes)
