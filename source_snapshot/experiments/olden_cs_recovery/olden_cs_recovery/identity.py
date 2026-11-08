"""Identity probe against live resolve_decomp_method / ctor NativeMethodInfoPtr."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from olden_cs_recovery.bridge import (
    BridgeUnavailableError,
    build_pin_metadata,
    default_bridge_dir,
    request_live,
)
from olden_cs_recovery.ledger import rel_repo, write_ledger_entry
from olden_cs_recovery.paths import IDENTITY_PROOFS_DIR, PACKAGE_ROOT
from olden_cs_recovery.queue_store import method_id_to_filename, to_iso, utc_now

_PARAM_SPLIT = re.compile(r"[,]")

# DiffableCs CompilerGenerated add/remove ↔ DummyDLL RVA ↔ live Il2CppInterop names.
# Proven by EdbEventHandlerProbe reading NativeMethodInfoPtr methodPointer RVAs.
EDB_EVENT_ACCESSORS: dict[str, dict[str, str]] = {
    "edb::bcjl(EventHandler)": {
        "kind": "add",
        "live_type": "ObjectPublicPrcfEvPrcf1BaPrcfEvUnique",
        "live_method": "Method_Public_add_Void_EventHandler_1_BattleEventArgs_0",
        "expected_rva": "0x181EEA920",
        "field_offset": "0x10",
        "field_name": "cfjl",
    },
    "edb::bcjm(EventHandler)": {
        "kind": "remove",
        "live_type": "ObjectPublicPrcfEvPrcf1BaPrcfEvUnique",
        "live_method": "Method_Public_rem_Void_EventHandler_1_BattleEventArgs_0",
        "expected_rva": "0x181EEA9D0",
        "field_offset": "0x10",
        "field_name": "cfjl",
    },
}

# edb parameterless ctor: DummyDLL RVA + live byte @0x2CA (cfmw) via EdbCtorCctorProbe.
EDB_CTOR: dict[str, Any] = {
    "method_id": "edb::.ctor()",
    "live_type": "ObjectPublicPrcfEvPrcf1BaPrcfEvUnique",
    "expected_rva": "0x181EEA7A0",
    "field_offset": "0x2CA",
    "field_name": "cfmw",
    "live_field": "field_Public_Boolean_1",
}

# edb static ctor: bar-C via CreateMarker call-trace (not ProfilerMarker handle fields).
EDB_CCTOR: dict[str, Any] = {
    "method_id": "edb::.cctor()",
    "live_type": "ObjectPublicPrcfEvPrcf1BaPrcfEvUnique",
    "expected_rva": "0x181EEA6C0",
    "create_marker_helper_rva": "0x183F6A090",
    "expected_marker_names": (
        "NullCheckMarker",
        "EventLogMarker",
        "EventApplyMarker",
    ),
    "probe_assembly": "CreateMarkerCallInterceptProbe.v1.dll",
}

# Legacy barrenness text retained for docs; no longer the active block reason once call-trace works.
EDB_CCTOR_BLOCKED_REASON = (
    "edb::.cctor observationally barren under field-snapshot bar C: body only stores three "
    "ProfilerMarker m_Ptr handles from CreateMarker(NullCheckMarker/EventLogMarker/EventApplyMarker); "
    "handles are zero on Golden Era player. Prefer CreateMarker call-trace oracle "
    "(CreateMarkerCallInterceptProbe / early plugin) instead of fabricated non-zero handles."
)


class IdentityProbeError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


def _parse_ctor_params(signature: str | None, method_id: str) -> list[str]:
    """Extract constructor parameter type tokens from queue signature / method_id."""
    text = signature or ""
    # Diffable-style: TypeName(bool x, int y) or System.Void .ctor(Boolean)
    paren = None
    if "(" in text and ")" in text:
        paren = text[text.index("(") + 1 : text.rindex(")")].strip()
    elif "::" in method_id and "(" in method_id:
        paren = method_id[method_id.index("(") + 1 : method_id.rindex(")")].strip()
    if not paren:
        return []
    parts = []
    for raw in _PARAM_SPLIT.split(paren):
        token = raw.strip()
        if not token:
            continue
        # Drop parameter name: "bool _isClickable" / "eep battleLogic"
        bits = token.replace(",", " ").split()
        if not bits:
            continue
        parts.append(bits[0])
    return parts


def _param_token_needles(param_types: list[str]) -> list[str]:
    """
    Substrings that must appear in NativeMethodInfoPtr__ctor_* for known primitives/arrays.

    DiffableCs short obfuscated type tokens (eir, edn, …) do not appear in interop
    MethodInfoPtr names (those use other obfuscated Il2Cpp names). Requiring them
    would false-fail identity. Custom types are handled by unique-ctor fallback.
    """
    mapping = {
        "bool": "Boolean",
        "boolean": "Boolean",
        "system.boolean": "Boolean",
        "int": "Int32",
        "int32": "Int32",
        "system.int32": "Int32",
        "float": "Single",
        "single": "Single",
        "system.single": "Single",
        "double": "Double",
        "system.double": "Double",
        "string": "String",
        "system.string": "String",
    }
    needles: list[str] = []
    for p in param_types:
        raw = p.strip()
        key = raw.lower()
        if "[]" in raw or raw.endswith("Array"):
            needles.append("Array")
            inner = raw.replace("[]", "").strip()
            inner_key = inner.lower()
            if inner_key in mapping:
                needles.append(mapping[inner_key])
            continue
        if key in mapping:
            needles.append(mapping[key])
        # else: custom/obfuscated DiffableCs token — no needle (unique-ctor gate below)
    return needles


def _match_ctor_native_methodinfo(
    fields: list[dict[str, Any]],
    *,
    param_types: list[str],
) -> dict[str, Any]:
    ctor_fields = [
        f
        for f in fields
        if isinstance(f, dict) and str(f.get("name") or "").startswith("NativeMethodInfoPtr__ctor_")
    ]
    if not ctor_fields:
        raise IdentityProbeError(
            "ctor_native_methodinfo_missing",
            "field_signatures had no NativeMethodInfoPtr__ctor_* entry for this type",
            details={"fields": fields},
        )

    needles = _param_token_needles(param_types)
    has_array_param = any("[]" in p or p.strip().endswith("Array") for p in param_types)
    primitive_int_count = sum(
        1
        for p in param_types
        if p.strip().lower() in {"int", "int32", "system.int32"}
    )
    matches: list[dict[str, Any]] = []
    for field in ctor_fields:
        name = str(field.get("name") or "")
        if "Array" in name and not has_array_param:
            continue
        if has_array_param and "Array" not in name:
            continue
        if needles and not all(token in name for token in needles):
            continue
        # Disambiguate Int32 overloads: count Int32 tokens in MethodInfoPtr name.
        if primitive_int_count:
            if name.count("Int32") < primitive_int_count:
                continue
        matches.append(field)

    # Unique ctor on the type: accept when primitive/array needles match (or none required).
    if not matches and len(ctor_fields) == 1:
        only = ctor_fields[0]
        name = str(only.get("name") or "")
        if not needles or all(token in name for token in needles):
            matches = [only]

    if len(matches) > 1 and len(ctor_fields) == 1:
        matches = list(ctor_fields)

    if not matches:
        raise IdentityProbeError(
            "ctor_native_methodinfo_mismatch",
            (
                f"No NativeMethodInfoPtr__ctor_* matched param_types={param_types!r} "
                f"needles={needles!r} among {[f.get('name') for f in ctor_fields]}"
            ),
            details={"ctor_fields": ctor_fields, "param_types": param_types, "needles": needles},
        )
    if len(matches) != 1:
        # Multiple ctors and ambiguous after needle filter — fail closed.
        raise IdentityProbeError(
            "ctor_native_methodinfo_ambiguous",
            f"Ambiguous ctor NativeMethodInfoPtr matches: {[m.get('name') for m in matches]}",
            details={"matches": matches, "needles": needles},
        )
    return matches[0]


def _validate_resolve_response(
    payload: dict[str, Any],
    response: dict[str, Any],
    *,
    require_ordinal_match: bool,
) -> dict[str, Any]:
    if response.get("ok") is not True:
        raise IdentityProbeError(
            "resolve_not_ok",
            f"resolve_decomp_method response not ok: {json.dumps(response, sort_keys=True)[:500]}",
            details={"response": response},
        )
    if response.get("decompTypeName") != payload.get("typeName"):
        raise IdentityProbeError(
            "resolve_type_echo_mismatch",
            "resolver response did not echo decompTypeName from payload",
            details={"expected": payload.get("typeName"), "got": response.get("decompTypeName")},
        )
    if payload.get("methodOrdinal") is not None and response.get("decompMethodOrdinal") != payload.get(
        "methodOrdinal"
    ):
        raise IdentityProbeError(
            "resolve_ordinal_echo_mismatch",
            "resolver response did not echo decompMethodOrdinal from payload",
        )
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise IdentityProbeError("resolve_no_candidates", "resolver response contained no runtime candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise IdentityProbeError("resolve_bad_candidate", "resolver first candidate was not an object")
    for key in ("runtimeName", "obfuscatedName", "declaringType", "signature", "score", "reasons"):
        if key not in first:
            raise IdentityProbeError("resolve_candidate_missing_field", f"first candidate missing field: {key}")
    reasons = first.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        raise IdentityProbeError("resolve_no_reasons", "first candidate had no scoring reasons")

    if require_ordinal_match or payload.get("methodOrdinal") is not None:
        if "runtime_callable_ordinal_match" not in reasons:
            raise IdentityProbeError(
                "resolve_ordinal_not_proven",
                "first candidate did not prove runtime_callable_ordinal_match (strict prove-script criteria)",
                details={"reasons": reasons, "first": first},
            )
        criteria = "runtime_callable_ordinal_match"
    else:
        # Equivalent strict criteria when ordinal is unavailable (common on EventArgs props).
        required = {"runtime_name_exact", "return_type_match", "parameter_count_match"}
        missing = sorted(required - set(reasons))
        if missing:
            raise IdentityProbeError(
                "resolve_signature_not_proven",
                (
                    "first candidate lacked strict non-ordinal reasons "
                    f"{missing}; refusing weak return_type-only matches"
                ),
                details={"reasons": reasons, "first": first},
            )
        expected_name = payload.get("methodName")
        if expected_name and first.get("runtimeName") != expected_name:
            raise IdentityProbeError(
                "resolve_name_mismatch",
                f"runtimeName {first.get('runtimeName')!r} != expected {expected_name!r}",
            )
        criteria = "runtime_name_exact+return_type_match+parameter_count_match"

    if "evidenceBoundary" not in response:
        raise IdentityProbeError("resolve_missing_evidence_boundary", "resolver response missing evidenceBoundary")

    return {"first_candidate": first, "criteria": criteria, "reasons": list(reasons)}


def build_resolve_payload(item: dict[str, Any], *, method_ordinal: int | None = None) -> dict[str, Any]:
    type_name = item.get("type_name")
    if not type_name:
        raise IdentityProbeError("missing_type_name", "queue item missing type_name")
    method_name = item.get("method_name") or ""
    signature = item.get("signature") or ""
    payload: dict[str, Any] = {
        "command": "resolve_decomp_method",
        "typeName": type_name,
        "limit": 12,
    }
    if signature:
        payload["signature"] = signature
    if method_name and method_name != ".ctor":
        payload["methodName"] = method_name
    if method_ordinal is not None:
        payload["methodOrdinal"] = method_ordinal
    return payload


def _try_compgen_dummydll_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    """
    Return identity proof for CompGen accessors when DummyDLL address_map and native
    disasm agree, else None (caller continues to resolve_decomp_method).
    """
    from olden_cs_recovery.lifter.address_map import (
        find_method_address,
        load_address_map,
        load_native_disasm_methods,
        normalize_address,
    )
    from olden_cs_recovery.lifter.compgen_synthesize import (
        find_native_method,
        index_native_disasm_by_type_method,
    )
    from olden_cs_recovery.paths import REPO_ROOT
    from olden_cs_recovery.replay import compgen_accessor_field, load_ir

    method_id = item["method_id"]
    ir = load_ir(method_id)
    info = compgen_accessor_field(ir)
    if info is None:
        return None

    samples = (
        REPO_ROOT
        / "experiments"
        / "cpp2il_readable_csharp"
        / "samples"
        / "latest_refresh"
    )
    # Prefer queue evidence packs (City UI / Hud / etc.); fall back to battle for Phase 5 domain 1.
    addr_map_path = samples / "address_map_hex_session_battle.json"
    native_path = samples / "native_disasm_hex_session_battle.json"
    for ref in item.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        path_text = str(ref.get("path") or "")
        if not path_text:
            continue
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if ref.get("kind") == "address_map" and candidate.is_file():
            addr_map_path = candidate
        if "native_disasm" in path_text.replace("\\", "/") and candidate.is_file():
            native_path = candidate
    if not addr_map_path.is_file() or not native_path.is_file():
        return None

    address_map = load_address_map(addr_map_path)
    # Use raw methods[] — address-keyed collapse drops CompGen VA aliases.
    by_tm = index_native_disasm_by_type_method(load_native_disasm_methods(native_path))
    type_name = item["type_name"]
    method_name = item.get("method_name") or ""
    map_entry = find_method_address(
        address_map,
        type_name=type_name,
        method_name=method_name,
        method_id=method_id,
    )
    native_method = find_native_method(
        by_tm,
        type_name=type_name,
        method_name=method_name,
        method_id=method_id,
    )
    if map_entry is None and native_method is None:
        return None
    map_addr = normalize_address(map_entry.address) if map_entry is not None else None
    native_addr = (
        normalize_address(str(native_method.get("address")))
        if native_method and native_method.get("address")
        else None
    )
    if map_addr and native_addr and map_addr != native_addr:
        raise IdentityProbeError(
            "compgen_address_mismatch",
            f"DummyDLL address_map {map_addr} != native_disasm {native_addr} for {method_id}",
        )
    agreed = map_addr or native_addr
    if not agreed:
        return None

    # Require live bridge freshness even for static address identity.
    status_resp, freshness = request_live(
        {"command": "status", "reason": f"compgen dummydll identity {method_id}"},
        bridge=bridge,
        timeout_seconds=timeout_seconds,
        require_fresh=True,
    )
    if status_resp.get("ok") is not True:
        raise IdentityProbeError(
            "bridge_status_not_ok",
            f"status failed during CompGen identity: {json.dumps(status_resp, sort_keys=True)[:300]}",
        )
    pin = build_pin_metadata(bridge_freshness=freshness)
    length = native_method.get("length") if native_method else None
    return {
        "schema_version": 1,
        "status": "identity-bridged",
        "method_id": method_id,
        "criteria": "compgen_dummydll_native_disasm_address_agree",
        "type_name": type_name,
        "native_address": agreed,
        "native_length": length,
        "compgen_kind": info.get("kind"),
        "compgen_field": info.get("field_name"),
        "freshness": freshness,
        "build_pin": pin,
        "evidence_boundary": [
            "CompGen accessor identity: DummyDLL method-pointer map and native_disasm agree on VA.",
            "DiffableCs CompGen names are often absent from resolve_decomp_method candidates.",
            "This is address identity, not method-body execution proof.",
        ],
        "probed_at": to_iso(utc_now()),
    }


def _try_write_body_pin_rva_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    """
    Identity for Direct State write bodies using pin-table / DummyDLL VAs.

    Requires a fresh live bridge (build pin). Does not invent addresses — only the
    declared M1 WRITE_BODY_NATIVE_VAS set is accepted.
    """
    from olden_cs_recovery.field_delta import is_direct_state_write_body_method, native_va_for

    method_id = item["method_id"]
    domain = str(item.get("domain") or "")
    if not is_direct_state_write_body_method(method_id, domain=domain):
        return None
    agreed = native_va_for(method_id)
    if not agreed:
        return None

    status_resp, freshness = request_live(
        {"command": "status", "reason": f"write-body pin VA identity {method_id}"},
        bridge=bridge,
        timeout_seconds=timeout_seconds,
        require_fresh=True,
    )
    if status_resp.get("ok") is not True:
        raise IdentityProbeError(
            "bridge_status_not_ok",
            f"status failed during write-body identity: {json.dumps(status_resp, sort_keys=True)[:300]}",
        )
    pin = build_pin_metadata(bridge_freshness=freshness)
    return {
        "schema_version": 1,
        "status": "identity-bridged",
        "method_id": method_id,
        "criteria": "direct_state_pin_table_dummydll_va",
        "type_name": item.get("type_name"),
        "native_address": agreed,
        "freshness": freshness,
        "build_pin": pin,
        "evidence_boundary": [
            "Write-body identity uses mono_live_pin_table / DummyDLL VA for the declared M1 set.",
            "WriteBodyFieldDeltaProbe re-validates the VA against live NativeMethodInfoPtr at invoke.",
            "This is address identity, not recovered-C# semantic equivalence.",
        ],
        "probed_at": to_iso(utc_now()),
    }


def probe_identity(
    item: dict[str, Any],
    *,
    bridge: Path | None = None,
    timeout_seconds: float = 8.0,
    method_ordinal: int | None = None,
) -> dict[str, Any]:
    """
    Prove method/type identity against a fresh live bridge.

    - Non-.ctor: resolve_decomp_method with prove-script ordinal criteria when ordinal present,
      else strict name+signature reasons.
    - .ctor: field_signatures NativeMethodInfoPtr__ctor_* arity/type-token match
      (resolve_decomp_method does not enumerate constructors).
    - edb CompilerGenerated event add/remove: EdbEventHandlerProbe RVA match against DummyDLL map.
    """
    bridge = bridge or default_bridge_dir()
    method_id = item["method_id"]
    method_name = item.get("method_name") or ""
    type_name = item.get("type_name")
    if not type_name:
        raise IdentityProbeError("missing_type_name", "queue item missing type_name")

    try:
        if method_id in EDB_EVENT_ACCESSORS:
            return _probe_edb_event_accessor_identity(
                item,
                bridge=bridge,
                timeout_seconds=timeout_seconds,
            )

        if method_id == EDB_CTOR["method_id"]:
            return _probe_edb_ctor_identity(
                item,
                bridge=bridge,
                timeout_seconds=timeout_seconds,
            )

        if method_id == EDB_CCTOR["method_id"]:
            return _probe_edb_cctor_identity(
                item,
                bridge=bridge,
                timeout_seconds=timeout_seconds,
            )

        if method_name == ".ctor" or method_id.endswith("::.ctor()") or "::.ctor(" in method_id:
            response, freshness = request_live(
                {"command": "field_signatures", "typeName": type_name, "limit": 200},
                bridge=bridge,
                timeout_seconds=timeout_seconds,
                require_fresh=True,
            )
            if response.get("ok") is not True:
                raise IdentityProbeError(
                    "field_signatures_not_ok",
                    f"field_signatures failed: {json.dumps(response, sort_keys=True)[:500]}",
                )
            if response.get("typeName") != type_name and not str(response.get("typeName") or "").endswith(
                "." + type_name.split(".")[-1]
            ):
                # Accept FullName echo equal or ending with simple name when FullName matches type_name.
                if response.get("typeName") != type_name:
                    raise IdentityProbeError(
                        "field_signatures_type_mismatch",
                        f"field_signatures typeName {response.get('typeName')!r} != {type_name!r}",
                    )
            fields = response.get("fields")
            if not isinstance(fields, list):
                raise IdentityProbeError("field_signatures_bad_fields", "fields must be a list")
            param_types = _parse_ctor_params(item.get("signature"), method_id)
            matched = _match_ctor_native_methodinfo(fields, param_types=param_types)
            pin = build_pin_metadata(bridge_freshness=freshness)
            proof = {
                "schema_version": 1,
                "status": "identity-bridged",
                "method_id": method_id,
                "criteria": "native_ctor_methodinfo_ptr_match",
                "type_name": type_name,
                "matched_native_methodinfo": matched,
                "param_types": param_types,
                "freshness": freshness,
                "build_pin": pin,
                "field_signatures_response": response,
                "evidence_boundary": [
                    "Constructor identity uses live field_signatures NativeMethodInfoPtr__ctor_* match.",
                    "resolve_decomp_method does not enumerate constructors (GetMethods only).",
                    "This is runtime interop metadata evidence, not method-body execution proof.",
                ],
                "probed_at": to_iso(utc_now()),
            }
            return proof

        # CompGen accessors: obfuscated DiffableCs names often lack live resolve_decomp_method
        # candidates. Prove identity via DummyDLL address_map ∩ native_disasm agreement when
        # recovered IR is a proven CompGen getter/setter (fail closed otherwise).
        compgen_proof = _try_compgen_dummydll_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)
        if compgen_proof is not None:
            return compgen_proof

        # Direct State write bodies: pin-table / DummyDLL VA identity (field-delta probe needs VA).
        write_body_proof = _try_write_body_pin_rva_identity(
            item, bridge=bridge, timeout_seconds=timeout_seconds
        )
        if write_body_proof is not None:
            return write_body_proof

        payload = build_resolve_payload(item, method_ordinal=method_ordinal)
        response, freshness = request_live(
            payload,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
            require_fresh=True,
        )
        validated = _validate_resolve_response(
            payload,
            response,
            require_ordinal_match=method_ordinal is not None,
        )
        pin = build_pin_metadata(bridge_freshness=freshness)
        proof = {
            "schema_version": 1,
            "status": "identity-bridged",
            "method_id": method_id,
            "criteria": validated["criteria"],
            "type_name": type_name,
            "payload": payload,
            "response": response,
            "first_candidate": validated["first_candidate"],
            "freshness": freshness,
            "build_pin": pin,
            "evidence_boundary": [
                "This proves the live bridge answered resolve_decomp_method under strict criteria.",
                "Not native call-order proof and not recovered-C# semantic equivalence.",
            ],
            "probed_at": to_iso(utc_now()),
        }
        return proof
    except BridgeUnavailableError as exc:
        raise IdentityProbeError(exc.code, exc.message, details=exc.details) from exc


def _probe_edb_ctor_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Identity for edb::.ctor via EdbCtorCctorProbe DummyDLL RVA match."""
    meta = EDB_CTOR
    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb identity {meta['method_id']}",
        "assemblyPath": "EdbCtorCctorProbe.v1.dll",
        "typeName": "OldenCsRecovery.Probes.EdbCtorCctorProbe",
        "methodName": "Run",
        "targetTypeName": meta["live_type"],
        "mode": "ctor",
        "expectedCtorRva": meta["expected_rva"],
    }
    response, freshness = request_live(
        payload,
        bridge=bridge,
        timeout_seconds=max(timeout_seconds, 20.0),
        require_fresh=True,
    )
    if response.get("ok") is not True:
        raise IdentityProbeError(
            "edb_ctor_probe_not_ok",
            f"EdbCtorCctorProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
            details={"response": response},
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdentityProbeError(
            "edb_ctor_probe_bad_json",
            f"EdbCtorCctorProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        raise IdentityProbeError(
            "edb_ctor_probe_failed",
            f"EdbCtorCctorProbe returned error: {json.dumps(result.get('error'), sort_keys=True)}",
            details={"result": result},
        )
    identity = result.get("identity") or {}
    if identity.get("ctorRvaMatch") is not True:
        raise IdentityProbeError(
            "edb_ctor_rva_mismatch",
            (
                f"live ctor RVA {identity.get('ctorMethodRva')!r} != expected "
                f"{meta['expected_rva']!r}"
            ),
            details={"identity": identity, "meta": meta},
        )
    cfmw = result.get("cfmw") or {}
    if cfmw.get("value") is not True or str(cfmw.get("offset") or "").lower() != "0x2ca":
        raise IdentityProbeError(
            "edb_ctor_cfmw_not_observed",
            "probe did not observe cfmw @0x2CA == true after ctor",
            details={"cfmw": cfmw, "result": result},
        )
    pin = build_pin_metadata(bridge_freshness=freshness)
    return {
        "schema_version": 1,
        "status": "identity-bridged",
        "method_id": meta["method_id"],
        "criteria": "dummydll_rva_match+live_edb_ctor_byte_0x2ca",
        "type_name": item.get("type_name"),
        "live_type": result.get("typeName"),
        "live_method": result.get("ctorMethod"),
        "expected_rva": meta["expected_rva"],
        "probe_identity": identity,
        "cfmw": cfmw,
        "freshness": freshness,
        "build_pin": pin,
        "evidence_boundary": [
            "edb::.ctor identity uses DummyDLL method RVA matched to live "
            "NativeMethodInfoPtr__ctor_Public_Void_5 methodPointer (EdbCtorCctorProbe).",
            "Observable side effect: instance byte @0x2CA (cfmw / field_Public_Boolean_1) "
            "transitions 0→1; base call is System.Object::.ctor @ 0x1805B84F0 (tail jmp).",
            "This is identity evidence, not recovered-C# semantic equivalence.",
        ],
        "probed_at": to_iso(utc_now()),
    }


def _probe_edb_cctor_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Identity for edb::.cctor via CreateMarkerCallInterceptProbe harvest + DummyDLL RVA."""
    meta = EDB_CCTOR
    persist = str((bridge / "create_marker_intercept").resolve()).replace("\\", "/")
    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb identity {meta['method_id']}",
        "assemblyPath": meta["probe_assembly"],
        "typeName": "OldenCsRecovery.Probes.CreateMarkerCallInterceptProbe",
        "methodName": "Run",
        "mode": "harvest_edb",
        "targetTypeName": meta["live_type"],
        "expectedCctorRva": meta["expected_rva"],
        "persistRoot": persist,
    }
    response, freshness = request_live(
        payload,
        bridge=bridge,
        timeout_seconds=max(timeout_seconds, 30.0),
        require_fresh=True,
    )
    if response.get("ok") is not True:
        raise IdentityProbeError(
            "edb_cctor_probe_not_ok",
            f"CreateMarkerCallInterceptProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
            details={"response": response},
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdentityProbeError(
            "edb_cctor_probe_bad_json",
            f"CreateMarkerCallInterceptProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        err = result.get("error") or {}
        raise IdentityProbeError(
            "edb_cctor_probe_failed",
            f"CreateMarkerCallInterceptProbe returned error: {json.dumps(err, sort_keys=True)}",
            details={"result": result},
        )
    identity = result.get("identity") or {}
    if identity.get("cctorRvaMatch") is not True:
        raise IdentityProbeError(
            "edb_cctor_rva_mismatch",
            (
                f"live cctor RVA {identity.get('cctorMethodRva')!r} != expected "
                f"{meta['expected_rva']!r}"
            ),
            details={"identity": identity, "meta": meta},
        )
    call_trace = result.get("callTrace") or {}
    calls = call_trace.get("calls") if isinstance(call_trace, dict) else None
    if not isinstance(calls, list) or len(calls) != 3:
        raise IdentityProbeError(
            "edb_cctor_call_trace_incomplete",
            "harvest_edb did not return exactly three CreateMarker call-trace entries",
            details={"callTrace": call_trace},
        )
    names = [str(c.get("name") or "") for c in calls]
    expected = list(meta["expected_marker_names"])
    if names != expected:
        raise IdentityProbeError(
            "edb_cctor_marker_names_mismatch",
            f"call-trace names {names!r} != expected {expected!r}",
            details={"calls": calls},
        )
    pin = build_pin_metadata(bridge_freshness=freshness)
    return {
        "schema_version": 1,
        "status": "identity-bridged",
        "method_id": meta["method_id"],
        "criteria": "dummydll_rva_match+live_createmarker_call_trace",
        "type_name": item.get("type_name"),
        "live_type": result.get("typeName"),
        "expected_rva": meta["expected_rva"],
        "probe_identity": identity,
        "call_trace": call_trace,
        "freshness": freshness,
        "build_pin": pin,
        "evidence_boundary": [
            "edb::.cctor identity uses DummyDLL .cctor RVA matched live (0x181EEA6C0) plus "
            "ordered CreateMarker name arguments captured by Harmony intercept.",
            "ProfilerMarker handles may be zero on Golden Era player; call-trace is the "
            "bar-C observable, not static field m_Ptr values.",
            "This is identity evidence, not recovered-C# semantic equivalence.",
        ],
        "probed_at": to_iso(utc_now()),
    }


def _probe_edb_event_accessor_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Identity for edb::bcjl/bcjm via live RVA match from EdbEventHandlerProbe."""
    method_id = item["method_id"]
    meta = EDB_EVENT_ACCESSORS[method_id]
    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb identity {method_id}",
        "assemblyPath": "EdbEventHandlerProbe.v1.dll",
        "typeName": "OldenCsRecovery.Probes.EdbEventHandlerProbe",
        "methodName": "Run",
        "targetTypeName": meta["live_type"],
        "invokeMethod": "Method_Public_add_Void_EventHandler_1_BattleEventArgs_0",
        "removeMethod": "Method_Public_rem_Void_EventHandler_1_BattleEventArgs_0",
        "alsoRemove": True,
        "expectedAddRva": "0x181EEA920",
        "expectedRemRva": "0x181EEA9D0",
    }
    response, freshness = request_live(
        payload,
        bridge=bridge,
        timeout_seconds=max(timeout_seconds, 20.0),
        require_fresh=True,
    )
    if response.get("ok") is not True:
        raise IdentityProbeError(
            "edb_probe_not_ok",
            f"EdbEventHandlerProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
            details={"response": response},
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdentityProbeError(
            "edb_probe_bad_json",
            f"EdbEventHandlerProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        raise IdentityProbeError(
            "edb_probe_failed",
            f"EdbEventHandlerProbe returned error: {json.dumps(result.get('error'), sort_keys=True)}",
            details={"result": result},
        )
    identity = result.get("identity") or {}
    kind = meta["kind"]
    if kind == "add":
        if identity.get("addRvaMatch") is not True:
            raise IdentityProbeError(
                "edb_add_rva_mismatch",
                (
                    f"live add RVA {identity.get('addMethodRva')!r} != expected "
                    f"{meta['expected_rva']!r}"
                ),
                details={"identity": identity, "meta": meta},
            )
        live_name = result.get("invokeMethod")
    else:
        if identity.get("remRvaMatch") is not True:
            raise IdentityProbeError(
                "edb_rem_rva_mismatch",
                (
                    f"live rem RVA {identity.get('remMethodRva')!r} != expected "
                    f"{meta['expected_rva']!r}"
                ),
                details={"identity": identity, "meta": meta},
            )
        live_name = result.get("removeMethod")
    if live_name != meta["live_method"]:
        raise IdentityProbeError(
            "edb_live_method_mismatch",
            f"probe live method {live_name!r} != expected {meta['live_method']!r}",
            details={"result": result, "meta": meta},
        )
    pin = build_pin_metadata(bridge_freshness=freshness)
    return {
        "schema_version": 1,
        "status": "identity-bridged",
        "method_id": method_id,
        "criteria": "dummydll_rva_match+live_event_accessor_name",
        "type_name": item.get("type_name"),
        "live_type": result.get("typeName"),
        "live_method": live_name,
        "expected_rva": meta["expected_rva"],
        "probe_identity": identity,
        "freshness": freshness,
        "build_pin": pin,
        "evidence_boundary": [
            "CompilerGenerated edb event add/remove identity uses DummyDLL method RVA "
            "matched to live NativeMethodInfoPtr methodPointer (EdbEventHandlerProbe).",
            "Live Il2CppInterop renames bcjl/bcjm to Method_Public_add_/rem_Void_EventHandler_*.",
            "This is identity evidence, not recovered-C# semantic equivalence.",
        ],
        "probed_at": to_iso(utc_now()),
    }

def write_identity_proof(proof: dict[str, Any]) -> Path:
    IDENTITY_PROOFS_DIR.mkdir(parents=True, exist_ok=True)
    method_id = proof["method_id"]
    path = IDENTITY_PROOFS_DIR / method_id_to_filename(method_id).replace(".json", ".identity.json")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_identity_to_ledger(
    item: dict[str, Any],
    proof: dict[str, Any],
    proof_path: Path,
) -> Path:
    previous = item.get("proof_status")
    # Never jump from static/rename straight to equivalence-proven.
    allowed_prev = {
        None,
        "static-lifted",
        "renamed-proposed",
        "renamed-accepted",
        "identity-bridged",
    }
    if previous not in allowed_prev and previous not in ("oracle-captured", "equivalence-proven"):
        raise IdentityProbeError(
            "illegal_proof_transition",
            f"refusing identity-bridged from proof_status={previous!r}",
        )
    if previous == "equivalence-proven":
        # Do not downgrade.
        raise IdentityProbeError(
            "already_equivalence_proven",
            "method already equivalence-proven; identity probe is informational only",
        )
    # Keep oracle-captured / identity-bridged if already past identity.
    if previous in ("oracle-captured", "equivalence-proven"):
        status = previous
        notes = f"Identity re-probe ok ({proof.get('criteria')}); ledger status unchanged at {previous}."
    else:
        status = "identity-bridged"
        notes = (
            f"Live identity probe passed via {proof.get('criteria')}. "
            "Not oracle-captured; not equivalence-proven."
        )
    return write_ledger_entry(
        method_id=item["method_id"],
        status=status,
        previous_status=previous if previous != status else proof.get("previous_status", previous),
        notes=notes,
        evidence_refs=[
            {
                "kind": "other",
                "path": rel_repo(proof_path),
                "notes": f"identity probe ({proof.get('criteria')})",
            }
        ],
        queue_item=item,
    )


def package_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PACKAGE_ROOT.resolve()).as_posix()
    except ValueError:
        return rel_repo(path)
