"""Fail-closed semantic coverage checks for HoMM3 scenario conversion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SAFE_LOSSINESS = frozenset({
    "direct_or_family_substitution",
    # Geometric pad/shift/absorb against HoMM3 masks — not a semantic placeholder.
    "footprint_alignment",
})
SEMANTIC_COVERAGE_POLICY = (
    "every emitted source semantic must have a direct_or_family_substitution "
    "translator; approximate, placeholder, deferred, and blocked records stop emission. "
    "footprint_alignment is geometric mask fit, not a semantic loss budget"
)


class ScenarioSemanticCoverageError(ValueError):
    """Raised when a scenario would silently lose source semantics."""


def _record_label(record: dict[str, Any]) -> str:
    signature = record.get("sourceSignature")
    if isinstance(signature, str) and signature:
        return signature
    source_key = record.get("sourceKey")
    if isinstance(source_key, str) and source_key:
        return source_key
    return "<unknown-source-record>"


def _unsafe_substitution_records(substitution: dict[str, Any]) -> list[dict[str, Any]]:
    entries = substitution.get("invalidEntitySubstitutions") or []
    if not isinstance(entries, list):
        raise ScenarioSemanticCoverageError("substitution map invalidEntitySubstitutions must be a list")

    unsafe: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ScenarioSemanticCoverageError(f"substitution entry must be an object: {entry!r}")
        lossiness = entry.get("lossiness")
        replacement_sid = entry.get("replacementSid")
        if replacement_sid is None or lossiness == "blocked":
            unsafe.append({
                "source": _record_label(entry),
                "ruleName": entry.get("ruleName"),
                "lossiness": lossiness,
                "replacementSid": replacement_sid,
                "count": entry.get("count"),
                "scope": "signature",
            })
        elif lossiness not in SAFE_LOSSINESS:
            unsafe.append({
                "source": _record_label(entry),
                "ruleName": entry.get("ruleName"),
                "lossiness": lossiness,
                "replacementSid": replacement_sid,
                "count": entry.get("count"),
                "scope": "signature",
            })
        overrides = entry.get("placementOverrides") or []
        if not isinstance(overrides, list):
            raise ScenarioSemanticCoverageError(
                f"placementOverrides must be a list for {_record_label(entry)}"
            )
        for override in overrides:
            if not isinstance(override, dict):
                raise ScenarioSemanticCoverageError(
                    f"placement override must be an object for {_record_label(entry)}"
                )
            override_lossiness = override.get("lossiness")
            override_sid = override.get("replacementSid")
            if override_sid is None or override_lossiness == "blocked":
                unsafe.append({
                    "source": str(override.get("sourceKey") or _record_label(entry)),
                    "ruleName": override.get("ruleName"),
                    "lossiness": override_lossiness,
                    "replacementSid": override_sid,
                    "count": 1,
                    "scope": "placement",
                })
            elif override_lossiness not in SAFE_LOSSINESS:
                unsafe.append({
                    "source": str(override.get("sourceKey") or _record_label(entry)),
                    "ruleName": override.get("ruleName"),
                    "lossiness": override_lossiness,
                    "replacementSid": override_sid,
                    "count": 1,
                    "scope": "placement",
                })
    return unsafe


def semantic_coverage_report(
    substitution: dict[str, Any],
    *,
    emission_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unsafe_substitutions = _unsafe_substitution_records(substitution)
    unsafe_emission: list[dict[str, Any]] = []
    if emission_stats is not None:
        if not isinstance(emission_stats, dict):
            raise ScenarioSemanticCoverageError("emission stats must be an object")
        for field in (
            "deferredBlockedEntityCount",
            "deferredPropertyRequiredEntityCount",
            "deferredNonStartHeroSpawnerCount",
        ):
            value = emission_stats.get(field, 0)
            if not isinstance(value, int) or value < 0:
                raise ScenarioSemanticCoverageError(f"emission stat {field} must be a non-negative integer")
            if value:
                unsafe_emission.append({"field": field, "count": value})
        # Border-overhang exclusion is geometric envelope clipping, not a semantic
        # placeholder. Track it in emission stats but do not fail coverage for it.
        overhang = emission_stats.get("excludedSurfaceBorderOverhangEntityCount", 0)
        if overhang is not None and (not isinstance(overhang, int) or overhang < 0):
            raise ScenarioSemanticCoverageError(
                "emission stat excludedSurfaceBorderOverhangEntityCount must be a non-negative integer"
            )

        for lossiness, count in (emission_stats.get("lossinessHistogram") or {}).items():
            if lossiness not in SAFE_LOSSINESS and isinstance(count, int) and count:
                unsafe_emission.append({
                    "field": "lossinessHistogram",
                    "lossiness": lossiness,
                    "count": count,
                })

    return {
        "schema": "homm3.scenario_semantic_coverage.v1",
        "policy": SEMANTIC_COVERAGE_POLICY,
        "safeLossiness": sorted(SAFE_LOSSINESS),
        "substitutionUnsafeCount": len(unsafe_substitutions),
        "substitutionUnsafeInstanceCount": sum(
            value.get("count", 1) for value in unsafe_substitutions if isinstance(value.get("count", 1), int)
        ),
        "unsafeSubstitutions": unsafe_substitutions,
        "emissionUnsafeCount": len(unsafe_emission),
        "unsafeEmission": unsafe_emission,
        "complete": not unsafe_substitutions and not unsafe_emission,
    }


def require_complete_semantic_coverage(
    substitution: dict[str, Any],
    *,
    emission_stats: dict[str, Any] | None = None,
    scenario_id: str,
) -> dict[str, Any]:
    report = semantic_coverage_report(substitution, emission_stats=emission_stats)
    if report["complete"]:
        return report
    fragments: list[str] = []
    unsafe_substitutions = report["unsafeSubstitutions"]
    if unsafe_substitutions:
        labels = ", ".join(
            f"{item['source']} ({item.get('ruleName')}, {item.get('lossiness')})"
            for item in unsafe_substitutions[:8]
        )
        fragments.append(f"untranslated substitutions: {labels}")
    unsafe_emission = report["unsafeEmission"]
    if unsafe_emission:
        labels = ", ".join(
            f"{item.get('field')}={item.get('count')}"
            for item in unsafe_emission
        )
        fragments.append(f"untranslated emitted records: {labels}")
    raise ScenarioSemanticCoverageError(
        f"{scenario_id} fails semantic coverage: {'; '.join(fragments)}. "
        "Implement a direct-state/native translator before emission."
    )


def load_substitution_and_require_complete(path: Path, *, scenario_id: str) -> dict[str, Any]:
    try:
        substitution = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as ex:
        raise ScenarioSemanticCoverageError(f"invalid substitution map JSON: {path}") from ex
    if not isinstance(substitution, dict):
        raise ScenarioSemanticCoverageError(f"substitution map must be a JSON object: {path}")
    return require_complete_semantic_coverage(substitution, scenario_id=scenario_id)
