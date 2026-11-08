#!/usr/bin/env python3
"""Prove one law-surface bridge resolver payload against the live bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))

from live_probe_request import DEFAULT_BRIDGE, request_bridge  # noqa: E402


DEFAULT_DOSSIERS = Path("experiments/cpp2il_readable_csharp/samples/latest_refresh/law_surface_dossiers.json")
SAFE_OUTPUT_ROOTS = (
    REPO_ROOT / "tmp" / "cpp2il_experiment",
    REPO_ROOT / "experiments" / "cpp2il_readable_csharp" / "samples",
)


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path}: expected JSON object")
    return value


def select_surface(document: dict[str, Any], symbol_id: str) -> dict[str, Any]:
    matches = [
        surface
        for surface in document.get("surfaces", [])
        if isinstance(surface, dict) and surface.get("symbol_id") == symbol_id
    ]
    if not matches:
        raise SystemExit(f"law surface not found in dossier: {symbol_id}")
    if len(matches) != 1:
        raise SystemExit(f"law surface is ambiguous in dossier: {symbol_id}")
    surface = matches[0]
    payload = surface.get("bridge_resolver_payload")
    if not isinstance(payload, dict):
        raise SystemExit(f"law surface has no bridge_resolver_payload: {symbol_id}")
    return surface


def resolver_payload(surface: dict[str, Any]) -> dict[str, Any]:
    payload = dict(surface["bridge_resolver_payload"])
    payload["command"] = "resolve_decomp_method"
    return payload


def validate_resolver_response(surface: dict[str, Any], payload: dict[str, Any], response: dict[str, Any]) -> None:
    if response.get("ok") is not True:
        raise SystemExit(f"resolver response was not ok: {json.dumps(response, sort_keys=True)}")
    if response.get("decompTypeName") != payload.get("typeName"):
        raise SystemExit("resolver response did not echo decompTypeName from payload")
    if response.get("decompMethodOrdinal") != payload.get("methodOrdinal"):
        raise SystemExit("resolver response did not echo decompMethodOrdinal from payload")
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit("resolver response contained no runtime candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise SystemExit("resolver first candidate was not an object")
    for key in ("runtimeName", "obfuscatedName", "declaringType", "signature", "runtimeCallableOrdinal", "score", "reasons"):
        if key not in first:
            raise SystemExit(f"resolver first candidate missing field: {key}")
    if not isinstance(first.get("reasons"), list) or not first["reasons"]:
        raise SystemExit("resolver first candidate had no scoring reasons")
    if payload.get("methodOrdinal") is not None and "runtime_callable_ordinal_match" not in first["reasons"]:
        raise SystemExit("resolver first candidate did not prove runtime_callable_ordinal_match")
    if "evidenceBoundary" not in response:
        raise SystemExit("resolver response missing evidenceBoundary")


def build_proof(surface: dict[str, Any], payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": 1,
        "status": "live_bridge_resolver_proven",
        "symbol_id": surface.get("symbol_id"),
        "law_class": surface.get("law_class"),
        "dossier_target": surface.get("dossier_target"),
        "payload": payload,
        "response": response,
        "evidence_boundary": [
            "This proves the live bridge answered resolve_decomp_method for one dossier payload.",
            "The response is runtime reflection metadata evidence, not native call order or Harmony patch safety proof.",
            "Candidate ranking remains evidence to reconcile with DiffableCs, ISIL, generated interop, or native disassembly.",
        ],
    }


def markdown_code(value: object) -> str:
    text = "" if value is None else str(value)
    return "`" + text.replace("`", "\\`") + "`"


def render_markdown(proof: dict[str, Any]) -> str:
    response = proof["response"]
    first = response["candidates"][0]
    lines = [
        "# Live Bridge Resolver Proof",
        "",
        f"- Status: {markdown_code(proof['status'])}",
        f"- Symbol: {markdown_code(proof['symbol_id'])}",
        f"- Law class: {markdown_code(proof['law_class'])}",
        f"- Dossier target: {markdown_code(proof['dossier_target'])}",
        f"- Request type: {markdown_code(proof['payload'].get('typeName'))}",
        f"- Request signature: {markdown_code(proof['payload'].get('signature'))}",
        f"- Request method ordinal: {markdown_code(proof['payload'].get('methodOrdinal'))}",
        f"- Resolved type: {markdown_code(response.get('resolvedTypeName'))}",
        f"- Type obfuscated name: {markdown_code(response.get('typeObfuscatedName'))}",
        f"- First runtime candidate: {markdown_code(first.get('runtimeName'))}",
        f"- First runtime callable ordinal: {markdown_code(first.get('runtimeCallableOrdinal'))}",
        f"- First score: {markdown_code(first.get('score'))}",
        f"- First reasons: {markdown_code(', '.join(first.get('reasons', [])))}",
        "",
        "## Evidence Boundary",
        "",
    ]
    lines.extend(f"- {item}" for item in proof["evidence_boundary"])
    lines.append("")
    return "\n".join(lines)


def write_outputs(proof: dict[str, Any], out_json: Path, out_md: Path | None) -> None:
    out_json = safe_output_path(out_json)
    out_md = safe_output_path(out_md) if out_md else None
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    if out_md:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(proof), encoding="utf-8")


def safe_output_path(path: Path) -> Path:
    resolved = path if path.is_absolute() else REPO_ROOT / path
    resolved = resolved.resolve()
    for root in SAFE_OUTPUT_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(root) for root in SAFE_OUTPUT_ROOTS)
    raise SystemExit(f"output path must be under one of: {allowed}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove one law-surface resolve_decomp_method bridge payload against a running live bridge."
    )
    parser.add_argument("--law-dossiers", type=Path, default=DEFAULT_DOSSIERS)
    parser.add_argument("--symbol-id", required=True, help="Exact law surface symbol_id to prove.")
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()

    document = load_json_object(args.law_dossiers)
    surface = select_surface(document, args.symbol_id)
    payload = resolver_payload(surface)
    response = request_bridge(args.bridge, payload, args.timeout)
    validate_resolver_response(surface, payload, response)
    proof = build_proof(surface, payload, response)
    write_outputs(proof, args.out_json, args.out_md)
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
