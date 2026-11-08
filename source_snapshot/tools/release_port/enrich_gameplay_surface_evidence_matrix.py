#!/usr/bin/env python3
"""Enrich the gameplay surface evidence matrix with rerunnable static planning data.

This script is intentionally conservative. It can normalize patch-drift metadata,
attach runtime symbol candidates when a law-surface dossier matches by exact
target or exact type+method token evidence, attach weak-dossier generated interop
candidates from exact dossier targets, and emit a weak-surface dossier plan.

It does not promote gameplay, build, launch, patch, or infer fuzzy symbol matches.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "custom_factions" / "gameplay_surface_evidence_matrix.json"
DEFAULT_DOSSIERS = ROOT / "experiments" / "cpp2il_readable_csharp" / "samples" / "latest_refresh" / "law_surface_dossiers.json"
DEFAULT_RUNTIME_MAP = ROOT / "experiments" / "cpp2il_readable_csharp" / "samples" / "latest_refresh" / "runtime_interop_map.json"
DEFAULT_WEAK_DOSSIER_INDEX = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_index.json"
DEFAULT_PLAN_JSON = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_plan.json"
DEFAULT_PLAN_MD = ROOT / "docs" / "gameplay_surface_weak_dossier_plan.md"

WEAK_STATUSES = {"candidate", "partial", "missing", "runtime-unproven"}
PATCH_DRIFT_STABILITIES = {
    "candidate-or-partial-sensitive",
    "generated-symbol-sensitive",
    "layout-sensitive-static",
    "runtime-metadata-sensitive",
    "static-declaration-sensitive",
}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
METHOD_SIGNATURE_RE = re.compile(r"^(?P<return>.+?)\s+(?P<method>[A-Za-z_.][A-Za-z0-9_.]*)\((?P<params>.*)\)$")
SURFACE_SYMBOL_PREFIXES = {
    "construction.chargedCostAndCommit": [
        "law.constructionCommit.",
        "law.economy.resourceData.subtractIfAvailable",
        "law.economy.resourceData.hasAtLeast",
    ],
    "counterattack.listenerCandidates": ["law.counterattackCorrelation."],
    "morale.rollClassification": ["law.morale."],
    "spellCooldown.castGateAndUiSync": ["law.spellCooldown.", "law.spellCastGate."],
    "spellbook.castMagicEventPayloads": ["law.spellbook.castMagic."],
    "vision.nativeRevealMutation": ["law.vision."],
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def evidence_kinds(surface: dict[str, Any]) -> set[str]:
    return {
        ref.get("kind")
        for ref in surface.get("evidenceRefs", [])
        if isinstance(ref, dict) and isinstance(ref.get("kind"), str)
    }


def infer_patch_drift(surface: dict[str, Any]) -> dict[str, Any]:
    kinds = evidence_kinds(surface)
    status = surface.get("status")
    domain = surface.get("domain")
    if "live-bridge-proof" in kinds or status == "proven-live-metadata":
        stability = "runtime-metadata-sensitive"
        refresh_actions = [
            "validate evidence path exists",
            "refresh generated interop map",
            "rerun bridge resolver proof when runtime bridge is available",
        ]
    elif {"generated-interop", "symbol-map", "law-surface-dossier"} & kinds:
        stability = "generated-symbol-sensitive"
        refresh_actions = [
            "validate evidence path exists",
            "refresh runtime interop map",
            "refresh symbol map/law surface dossiers",
        ]
    elif domain in {"ui", "event-payload", "battle-actor"}:
        stability = "layout-sensitive-static"
        refresh_actions = [
            "validate evidence path exists",
            "compare DiffableCs declaration fields",
            "refresh semantic index for caller drift",
        ]
    elif status == "proven-static":
        stability = "static-declaration-sensitive"
        refresh_actions = [
            "validate evidence path exists",
            "compare DiffableCs declaration fields",
        ]
    else:
        stability = "candidate-or-partial-sensitive"
        refresh_actions = [
            "validate evidence path exists",
            "refresh focused method dossier before promotion",
        ]

    drift_risks: list[str] = []
    if surface.get("surface", {}).get("candidateAmbiguity", 0):
        drift_risks.append("candidate ambiguity must be rechecked after patch")
    if status in WEAK_STATUSES:
        drift_risks.append("not gameplay-authoritative")
    if domain == "ui":
        drift_risks.append("UI layout/name drift likely")
    if domain in {"event-payload", "battle-actor", "battle-lifecycle", "battle-action"}:
        drift_risks.append("event ordering and concrete implementor identity may drift")

    return {
        "stability": stability,
        "refreshActions": refresh_actions,
        "driftRisks": drift_risks,
        "lastStaticRefresh": None,
        "lastRuntimeRefresh": None,
    }


def normalize_matrix(matrix: dict[str, Any]) -> None:
    matrix.setdefault(
        "dependencySemantics",
        {
            "dependsOn": "Use only when the surface claim itself is logically invalid unless the referenced surface claim is also proven at equal or stronger status.",
            "blockedBy": "Use for weaker adjacent evidence, runtime ordering, commit timing, packet gates, patch safety, and any proof needed before gameplay use.",
            "relatedSurfaces": "Optional non-gating context. Do not use relatedSurfaces as proof.",
        },
    )
    for surface in matrix.get("surfaces", {}).values():
        if not isinstance(surface, dict):
            continue
        existing = surface.get("patchDrift")
        if not isinstance(existing, dict) or existing.get("stability") not in PATCH_DRIFT_STABILITIES:
            surface["patchDrift"] = infer_patch_drift(surface)


def surface_tokens(surface: dict[str, Any]) -> set[str]:
    chunks: list[str] = []
    chunks.append(str(surface.get("semanticClaim", "")))
    chunks.extend(str(x) for x in surface.get("surface", {}).get("decompTargets", []))
    chunks.extend(str(ref.get("id", "")) for ref in surface.get("evidenceRefs", []) if isinstance(ref, dict))
    text = "\n".join(chunks)
    return set(TOKEN_RE.findall(text))


def dossier_matches(surface: dict[str, Any], dossier: dict[str, Any]) -> list[str]:
    tokens = surface_tokens(surface)
    target = dossier.get("dossier_target")
    reasons: list[str] = []
    if isinstance(target, str) and target:
        target_tokens = set(TOKEN_RE.findall(target.replace("::", ".")))
        if target in "\n".join(str(x) for x in surface.get("surface", {}).get("decompTargets", [])):
            reasons.append("exact_dossier_target")
        elif target_tokens and target_tokens <= tokens:
            reasons.append("dossier_target_tokens")

    type_hints = [hint for hint in dossier.get("type_hints", []) if isinstance(hint, str) and hint]
    method_hints = [hint for hint in dossier.get("method_hints", []) if isinstance(hint, str) and hint]
    type_match = next((hint for hint in type_hints if hint in tokens), None)
    method_match = next((hint for hint in method_hints if hint in tokens), None)
    if type_match and method_match:
        reasons.append(f"type_and_method_hint:{type_match}+{method_match}")
    return reasons


def attach_runtime_candidates(matrix: dict[str, Any], dossiers: list[dict[str, Any]], *, max_candidates: int) -> None:
    for surface_id, surface in matrix.get("surfaces", {}).items():
        if not isinstance(surface, dict):
            continue
        matches: list[dict[str, Any]] = []
        for dossier in dossiers:
            reasons = []
            symbol_id = dossier.get("symbol_id")
            for prefix in SURFACE_SYMBOL_PREFIXES.get(surface_id, []):
                if isinstance(symbol_id, str) and symbol_id.startswith(prefix):
                    reasons.append(f"curated_surface_symbol_prefix:{prefix}")
            reasons.extend(dossier_matches(surface, dossier))
            if not reasons:
                continue
            runtime_candidates = dossier.get("runtime_generated_candidates") or []
            first = runtime_candidates[0] if runtime_candidates and isinstance(runtime_candidates[0], dict) else None
            matches.append(
                {
                    "symbolId": dossier.get("symbol_id"),
                    "dossierTarget": dossier.get("dossier_target"),
                    "diffableSignature": dossier.get("diffable_signature"),
                    "decompMethodOrdinal": dossier.get("decomp_method_ordinal"),
                    "matchReasons": reasons,
                    "firstRuntimeCandidate": first,
                    "candidateCount": len(runtime_candidates),
                    "evidenceBoundary": "Exact-token static candidate only; not runtime proof or hook safety proof.",
                }
            )
        if matches:
            surface["runtimeSymbolCandidates"] = matches[:max_candidates]


def simple_type_name(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    if "`" in text:
        text = text.split("`", 1)[0]
    if "<" in text:
        text = text.split("<", 1)[0]
    return text.split(".")[-1]


def parse_method_signature(signature: str) -> dict[str, Any] | None:
    match = METHOD_SIGNATURE_RE.match(signature.strip())
    if not match:
        return None
    params_raw = match.group("params").strip()
    params: list[str] = []
    if params_raw:
        for item in params_raw.split(","):
            item = item.strip()
            if not item:
                continue
            params.append(item.split()[0])
    return {
        "returnType": match.group("return").strip(),
        "method": match.group("method").strip(),
        "parameterTypes": params,
        "parameterCount": len(params),
    }


def runtime_type_matches(target_type: str, runtime_type: dict[str, Any]) -> bool:
    runtime_name = str(runtime_type.get("runtime_type") or "")
    obfuscated = str(runtime_type.get("obfuscated_type") or "")
    candidates = {runtime_name, obfuscated, simple_type_name(runtime_name), simple_type_name(obfuscated)}
    return target_type in candidates or runtime_name.endswith("." + target_type)


def runtime_method_candidates(
    runtime_type: dict[str, Any],
    *,
    target_method: str | None,
    decomp_signature: dict[str, Any] | None,
    decomp_callable_ordinal: int | None,
    max_candidates: int,
) -> list[dict[str, Any]]:
    methods = [m for m in runtime_type.get("methods", []) if isinstance(m, dict)]
    if not target_method:
        return []

    exact_name = [
        m for m in methods
        if m.get("runtime_method") == target_method or m.get("obfuscated_method") == target_method
    ]
    if exact_name:
        source = exact_name
        reason = "weak_dossier_runtime_method_name_exact"
    elif decomp_callable_ordinal is not None:
        source = [
            m for m in methods
            if m.get("callable_ordinal") == decomp_callable_ordinal
        ]
        reason = "weak_dossier_callable_ordinal_and_signature_shape"
    else:
        return []

    if decomp_signature:
        source = [
            m for m in source
            if m.get("callable_ordinal") is not None
            and int(m.get("parameter_count", -1)) == int(decomp_signature["parameterCount"])
            and all(
                simple_type_name(str(runtime_param)) == simple_type_name(str(decomp_param))
                or str(runtime_param).endswith("." + simple_type_name(str(decomp_param)))
                or simple_type_name(str(decomp_param)) in str(runtime_param)
                for runtime_param, decomp_param in zip(m.get("parameter_types", []), decomp_signature["parameterTypes"])
            )
        ]
    else:
        source = [m for m in source if m.get("callable_ordinal") is not None]

    candidates: list[dict[str, Any]] = []
    for method in source[:max_candidates]:
        candidates.append(
            {
                "runtime_type": runtime_type.get("runtime_type"),
                "runtime_type_obfuscated": runtime_type.get("obfuscated_type"),
                "runtime_method": method.get("runtime_method"),
                "runtime_method_obfuscated": method.get("obfuscated_method"),
                "runtime_callable_ordinal": method.get("callable_ordinal"),
                "runtime_signature": method.get("signature"),
                "runtime_source": str(DEFAULT_RUNTIME_MAP.relative_to(ROOT)),
                "confidence": reason,
            }
        )
    return candidates


def callable_methods_from_manifest(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not manifest:
        return []
    methods: list[dict[str, Any]] = []
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        for signature in target.get("matched_methods", []):
            parsed = parse_method_signature(str(signature))
            if not parsed:
                continue
            if parsed["method"] in {".ctor", ".cctor"}:
                continue
            parsed["callableOrdinal"] = len(methods)
            methods.append(parsed)
    return methods


def weak_type_method_orders(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    orders: dict[str, list[dict[str, Any]]] = {}
    for dossier in row.get("dossiers", []):
        if not isinstance(dossier, dict) or dossier.get("status") not in {"built", "declaration-only"}:
            continue
        if dossier.get("targetMethod"):
            continue
        target_type = dossier.get("targetType")
        if not isinstance(target_type, str) or not target_type:
            continue
        orders[target_type] = callable_methods_from_manifest(weak_dossier_manifest(str(dossier.get("manifest") or "")))
    return orders


def decomp_callable_ordinal_for(
    type_method_orders: dict[str, list[dict[str, Any]]],
    target_type: str,
    target_method: str | None,
) -> int | None:
    if not target_method:
        return None
    for method in type_method_orders.get(target_type, []):
        if method.get("method") == target_method:
            ordinal = method.get("callableOrdinal")
            return int(ordinal) if isinstance(ordinal, int) else None
    return None


def weak_dossier_manifest(path_text: str) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = ROOT / path_text
    if not path.exists():
        return None
    data = load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def weak_dossier_signature(manifest: dict[str, Any], target_method: str | None) -> dict[str, Any] | None:
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        for signature in target.get("matched_methods", []):
            parsed = parse_method_signature(str(signature))
            if not parsed:
                continue
            if target_method is None or parsed["method"] == target_method:
                return parsed
    return None


def build_runtime_type_lookup(runtime_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in runtime_map.get("types", []) if isinstance(row, dict)]


def attach_weak_dossier_runtime_candidates(
    matrix: dict[str, Any],
    weak_index: dict[str, Any],
    runtime_map: dict[str, Any],
    *,
    max_candidates: int,
) -> None:
    runtime_types = build_runtime_type_lookup(runtime_map)
    for row in weak_index.get("surfaces", []):
        if not isinstance(row, dict):
            continue
        type_method_orders = weak_type_method_orders(row)
        surface_id = row.get("surfaceId")
        surface = matrix.get("surfaces", {}).get(surface_id)
        if not isinstance(surface, dict):
            continue
        existing = [
            candidate for candidate in list(surface.get("runtimeSymbolCandidates") or [])
            if not (
                isinstance(candidate, dict)
                and isinstance(candidate.get("symbolId"), str)
                and candidate.get("symbolId", "").startswith("weakDossier:")
            )
        ]
        seen = {
            (candidate.get("symbolId"), candidate.get("dossierTarget"))
            for candidate in existing
            if isinstance(candidate, dict)
        }
        for dossier in row.get("dossiers", []):
            if not isinstance(dossier, dict) or dossier.get("status") not in {"built", "declaration-only"}:
                continue
            target_type = dossier.get("targetType")
            if not isinstance(target_type, str) or not target_type:
                continue
            target_method = dossier.get("targetMethod")
            if target_method is not None and not isinstance(target_method, str):
                target_method = None
            manifest = weak_dossier_manifest(str(dossier.get("manifest") or ""))
            decomp_signature = weak_dossier_signature(manifest, target_method) if manifest else None
            decomp_callable_ordinal = decomp_callable_ordinal_for(type_method_orders, target_type, target_method)
            matching_types = [runtime_type for runtime_type in runtime_types if runtime_type_matches(target_type, runtime_type)]
            for runtime_type in matching_types[:max_candidates]:
                method_candidates = runtime_method_candidates(
                    runtime_type,
                    target_method=target_method,
                    decomp_signature=decomp_signature,
                    decomp_callable_ordinal=decomp_callable_ordinal,
                    max_candidates=max_candidates,
                )
                if target_method and not method_candidates:
                    continue
                first = method_candidates[0] if method_candidates else {
                    "runtime_type": runtime_type.get("runtime_type"),
                    "runtime_type_obfuscated": runtime_type.get("obfuscated_type"),
                    "runtime_method": None,
                    "runtime_method_obfuscated": None,
                    "runtime_callable_ordinal": None,
                    "runtime_signature": None,
                    "runtime_source": str(DEFAULT_RUNTIME_MAP.relative_to(ROOT)),
                    "confidence": "weak_dossier_runtime_type_exact",
                }
                key = (f"weakDossier:{surface_id}", dossier.get("target"))
                if key in seen:
                    continue
                seen.add(key)
                existing.append(
                    {
                        "symbolId": f"weakDossier:{surface_id}",
                        "dossierTarget": dossier.get("target"),
                        "diffableSignature": (
                            None
                            if not decomp_signature
                            else f"{decomp_signature['returnType']} {decomp_signature['method']}({', '.join(decomp_signature['parameterTypes'])})"
                        ),
                        "decompMethodOrdinal": decomp_callable_ordinal,
                        "matchReasons": [
                            "weak_dossier_target",
                            "runtime_type_exact_or_suffix_match",
                            first.get("confidence"),
                        ],
                        "firstRuntimeCandidate": first,
                        "candidateCount": len(method_candidates) if method_candidates else len(matching_types),
                        "evidenceBoundary": (
                            "Weak-dossier generated interop candidate only; proves generated metadata exists for the exact dossier target, "
                            "not decomp method identity, runtime reachability, gameplay ordering, or hook safety."
                        ),
                    }
                )
                if len(existing) >= max_candidates:
                    break
        if existing:
            surface["runtimeSymbolCandidates"] = existing[:max_candidates]


def build_weak_plan(matrix: dict[str, Any]) -> dict[str, Any]:
    surfaces = matrix.get("surfaces", {})
    weak_rows: list[dict[str, Any]] = []
    for surface_id, surface in sorted(surfaces.items()):
        if not isinstance(surface, dict) or surface.get("status") not in WEAK_STATUSES:
            continue
        weak_rows.append(
            {
                "surfaceId": surface_id,
                "domain": surface.get("domain"),
                "status": surface.get("status"),
                "packets": surface.get("packets", []),
                "decompTargets": surface.get("surface", {}).get("decompTargets", []),
                "runtimeSymbolCandidates": surface.get("runtimeSymbolCandidates", []),
                "blockedBy": surface.get("blockedBy", []),
                "nextProofAction": surface.get("nextProofAction"),
                "recommendedDossierAction": recommended_dossier_action(surface_id, surface),
            }
        )
    return {
        "schemaVersion": 1,
        "purpose": "Rerunnable weak-surface dossier plan generated from gameplay_surface_evidence_matrix.json.",
    "generationBoundary": "Static planning only. Candidate runtime symbols are law-dossier exact-token matches or weak-dossier generated interop matches, not proof.",
        "weakSurfaceCount": len(weak_rows),
        "weakSurfaces": weak_rows,
    }


def recommended_dossier_action(surface_id: str, surface: dict[str, Any]) -> str:
    targets = surface.get("surface", {}).get("decompTargets", [])
    candidates = surface.get("runtimeSymbolCandidates", [])
    if candidates:
        target = candidates[0].get("dossierTarget") or candidates[0].get("symbolId")
        return f"Build/refresh focused method dossier for matched target {target} and reconcile runtime candidate before probe."
    if targets:
        return "Resolve exact decomp type/method from decompTargets, then build a focused method dossier before runtime probing."
    return "Add exact decomp target identity before dossier generation; current row is not specific enough."


def write_plan_md(path: Path, plan: dict[str, Any]) -> None:
    lines = [
        "# Gameplay Surface Weak Dossier Plan",
        "",
        "Generated from `custom_factions/gameplay_surface_evidence_matrix.json`.",
        "",
        "Boundary: static planning only. Runtime symbol candidates here are law-dossier exact-token matches or weak-dossier generated interop matches, not proof.",
        "",
        f"Weak surface count: `{plan['weakSurfaceCount']}`",
        "",
        "| Surface | Domain | Status | Candidate count | Recommended action |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in plan["weakSurfaces"]:
        candidate_count = len(row.get("runtimeSymbolCandidates", []))
        action = str(row.get("recommendedDossierAction", "")).replace("|", "\\|")
        lines.append(
            f"| `{row['surfaceId']}` | {row.get('domain')} | {row.get('status')} | {candidate_count} | {action} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--law-surface-dossiers", type=Path, default=DEFAULT_DOSSIERS)
    parser.add_argument("--runtime-map-json", type=Path, default=DEFAULT_RUNTIME_MAP)
    parser.add_argument("--weak-dossier-index", type=Path, default=DEFAULT_WEAK_DOSSIER_INDEX)
    parser.add_argument("--out-plan-json", type=Path, default=DEFAULT_PLAN_JSON)
    parser.add_argument("--out-plan-md", type=Path, default=DEFAULT_PLAN_MD)
    parser.add_argument("--write-matrix", action="store_true")
    parser.add_argument("--max-candidates-per-surface", type=int, default=8)
    args = parser.parse_args()

    matrix = load_json(args.matrix)
    normalize_matrix(matrix)

    if args.law_surface_dossiers.exists():
        dossier_doc = load_json(args.law_surface_dossiers)
        dossiers = dossier_doc.get("surfaces", [])
        if isinstance(dossiers, list):
            attach_runtime_candidates(matrix, dossiers, max_candidates=args.max_candidates_per_surface)
    if args.weak_dossier_index.exists() and args.runtime_map_json.exists():
        weak_index_doc = load_json(args.weak_dossier_index)
        runtime_map_doc = load_json(args.runtime_map_json)
        attach_weak_dossier_runtime_candidates(
            matrix,
            weak_index_doc,
            runtime_map_doc,
            max_candidates=args.max_candidates_per_surface,
        )

    plan = build_weak_plan(matrix)
    dump_json(args.out_plan_json, plan)
    write_plan_md(args.out_plan_md, plan)
    if args.write_matrix:
        dump_json(args.matrix, matrix)

    print(
        "gameplay surface matrix enrichment complete "
        f"({plan['weakSurfaceCount']} weak surface(s), write_matrix={args.write_matrix})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
