"""Oracle trace writer + live capture protocol (fail-closed)."""

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
from olden_cs_recovery.identity import (
    IdentityProbeError,
    apply_identity_to_ledger,
    probe_identity,
    write_identity_proof,
    EDB_CCTOR,
    EDB_CCTOR_BLOCKED_REASON,
    EDB_CTOR,
    EDB_EVENT_ACCESSORS,
)
from olden_cs_recovery.ledger import rel_repo, write_ledger_entry
from olden_cs_recovery.paths import (
    ALLOWED_STAGE_TRANSITIONS,
    ORACLE_TRACES_LIVE_DIR,
    ORACLE_TRACES_SYNTHETIC_DIR,
    PACKAGE_ROOT,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import (
    method_id_to_filename,
    release_item,
    to_iso,
    utc_now,
    write_queue_item,
)
from olden_cs_recovery.replay import (
    field_assign_plan_from_ir,
    is_base_only_parameterless_ctor,
    is_base_then_bool_field_assign_ctor,
    is_base_then_param_field_assign_ctor,
    is_nested_null_guarded_field_copy_ctor,
    load_ir,
    parse_ctor_param_types_from_ir,
)
from olden_cs_recovery.schema_validate import validate_instance

_FIELD_DECL = re.compile(
    r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?P<type>[^\s]+)\s+(?P<name>[A-Za-z_][\w]*)\s*;",
    re.MULTILINE,
)

CAPTURE_KINDS = ("live_execution", "live_surface_metadata")


class OracleCaptureError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


def oracle_path_for(method_id: str, *, synthetic: bool) -> Path:
    root = ORACLE_TRACES_SYNTHETIC_DIR if synthetic else ORACLE_TRACES_LIVE_DIR
    return root / method_id_to_filename(method_id).replace(".json", ".oracle.json")


def write_oracle_trace(fixture: dict[str, Any], *, path: Path | None = None) -> Path:
    validate_instance("oracle_trace.schema.json", fixture, fixture.get("method_id", "<oracle>"))
    if fixture.get("synthetic") is True:
        target = path or oracle_path_for(fixture["method_id"], synthetic=True)
        if ORACLE_TRACES_LIVE_DIR in target.parents or target.parent == ORACLE_TRACES_LIVE_DIR:
            raise OracleCaptureError(
                "synthetic_in_live_dir",
                "synthetic fixtures must not be written under oracle_traces/live/",
            )
    else:
        target = path or oracle_path_for(fixture["method_id"], synthetic=False)
        if fixture.get("capture_kind") == "synthetic_execution":
            raise OracleCaptureError(
                "synthetic_kind_not_live",
                "capture_kind=synthetic_execution is only valid under oracle_traces/synthetic/",
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load_oracle_trace(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleCaptureError("oracle_unreadable", f"cannot load oracle fixture {path}: {exc}") from exc
    validate_instance("oracle_trace.schema.json", data, str(path))
    return data


def find_oracle_for_method(method_id: str) -> Path | None:
    live = oracle_path_for(method_id, synthetic=False)
    if live.is_file():
        return live
    syn = oracle_path_for(method_id, synthetic=True)
    if syn.is_file():
        return syn
    return None


def _parse_recovered_fields(recovered_cs: Path) -> list[dict[str, str]]:
    if not recovered_cs.is_file():
        return []
    text = recovered_cs.read_text(encoding="utf-8-sig")
    fields: list[dict[str, str]] = []
    for match in _FIELD_DECL.finditer(text):
        fields.append({"name": match.group("name"), "type": match.group("type")})
    return fields


def _recovered_cs_for_item(item: dict[str, Any]) -> Path | None:
    type_name = item.get("type_name") or ""
    if not type_name:
        return None
    simple = type_name.split(".")[-1]
    domain = item.get("domain") or ""
    candidates = [
        PACKAGE_ROOT / "recovered" / domain / f"{simple}.cs",
        PACKAGE_ROOT / "recovered" / "Hex.Session.Battle" / f"{simple}.cs",
        PACKAGE_ROOT / "recovered" / "edb" / f"{simple}.cs",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _ctor_parameter_arity(method_id: str) -> int | None:
    if "::.ctor(" not in method_id:
        return None
    inside = method_id.split("::.ctor(", 1)[1]
    if not inside.endswith(")"):
        return None
    inside = inside[:-1].strip()
    if not inside:
        return 0
    return len([p for p in inside.split(",") if p.strip()])


def _ensure_identity(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], Path]:
    try:
        identity_proof = probe_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)
    except IdentityProbeError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc
    identity_path = write_identity_proof(identity_proof)
    return identity_proof, identity_path


def capture_live_surface_metadata(
    item: dict[str, Any],
    *,
    bridge: Path | None = None,
    timeout_seconds: float = 8.0,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """
    Capture live surface metadata after a successful identity probe.

    Produces capture_kind=live_surface_metadata. EquivTester will refuse
    equivalence-proven until a live_execution fixture exists.
    """
    bridge = bridge or default_bridge_dir()
    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)

    type_name = item["type_name"]
    try:
        fields_resp, freshness = request_live(
            {"command": "field_signatures", "typeName": type_name, "limit": 200},
            bridge=bridge,
            timeout_seconds=timeout_seconds,
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc

    if fields_resp.get("ok") is not True:
        raise OracleCaptureError(
            "field_signatures_not_ok",
            f"field_signatures failed during oracle capture: {json.dumps(fields_resp, sort_keys=True)[:500]}",
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id; refuse oracle capture without build pin",
            details={"freshness": freshness},
        )

    recovered_path = _recovered_cs_for_item(item)
    recovered_fields = _parse_recovered_fields(recovered_path) if recovered_path else []

    fixture = {
        "schema_version": 1,
        "method_id": item["method_id"],
        "capture_kind": "live_surface_metadata",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": type_name,
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": type_name,
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "method_id": item["method_id"],
        },
        "outputs": {
            "runtime_type_name": fields_resp.get("typeName"),
            "runtime_fields": fields_resp.get("fields") or [],
            "recovered_declared_fields": recovered_fields,
            "identity": {
                "criteria": identity_proof.get("criteria"),
                "matched_native_methodinfo": identity_proof.get("matched_native_methodinfo"),
                "first_candidate": identity_proof.get("first_candidate"),
            },
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_surface_metadata",
            "version": 1,
            "notes": (
                "Captures live type resolution + field_signatures + identity criteria. "
                "Does not invoke the method body. EquivTester must not mark equivalence-proven "
                "from live_surface_metadata alone (bar C requires live_execution)."
            ),
        },
        "notes": (
            "Phase 3 live surface-metadata oracle. Not an execution trace. "
            "Bar C equivalence-proven still requires live_execution inputs→outputs."
        ),
    }
    path = write_oracle_trace(fixture)
    return fixture, identity_proof, path


def _parse_probe_result_payload(resp: dict[str, Any]) -> dict[str, Any]:
    """Parse volatile_load_probe_assembly resultText JSON into a construct-like payload."""
    text = resp.get("resultText")
    if not isinstance(text, str) or not text.strip():
        raise OracleCaptureError(
            "probe_result_missing",
            "volatile_load_probe_assembly returned no resultText",
            details={"response": resp},
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OracleCaptureError(
            "probe_result_unreadable",
            f"probe resultText is not JSON: {exc}",
            details={"resultText": text[:500]},
        ) from exc
    if not isinstance(payload, dict):
        raise OracleCaptureError("probe_result_invalid", "probe resultText root must be an object")
    if payload.get("ok") is not True:
        err = payload.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message")
        elif isinstance(err, str):
            code = err
            message = payload.get("message")
        else:
            code = "unknown"
            message = payload.get("message")
        raise OracleCaptureError(
            "probe_construct_failed",
            f"probe reported failure: {code}: {message}",
            details={"payload": payload},
        )
    return payload


def _invoke_construct_snapshot(
    *,
    type_name: str,
    method_id: str,
    bridge: Path,
    timeout_seconds: float,
    parameter_arity: int = 0,
    args: list[Any] | None = None,
    parameter_types: list[str] | None = None,
    allow_throw: bool = False,
    expect_throw: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """
    Prefer native construct_instance_snapshot; fall back to hot-loaded probe assembly.

    Returns (payload_with_instance_or_threw, freshness, source_label).
    """
    args = list(args or [])
    parameter_types = list(parameter_types or [])
    if len(args) != parameter_arity:
        raise OracleCaptureError(
            "construct_args_arity_mismatch",
            f"args length {len(args)} != parameter_arity {parameter_arity}",
        )

    native_request: dict[str, Any] = {
        "command": "construct_instance_snapshot",
        "typeName": type_name,
        "parameterArity": parameter_arity,
        "argsJson": json.dumps(args, separators=(",", ":")),
        "includeInheritedFields": True,
        "fieldLimit": 64,
        "reason": f"olden_cs_recovery live_execution {method_id}",
    }
    if parameter_arity > 0:
        native_request["parameterTypes"] = ",".join(parameter_types)

    try:
        exec_resp, freshness = request_live(
            native_request,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc

    if exec_resp.get("ok") is True and isinstance(exec_resp.get("instance"), dict):
        return exec_resp, freshness, "construct_instance_snapshot"

    err = exec_resp.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else ""
    # Unknown command on older loaded DLL → try volatile probe without inventing outputs.
    if code not in {"unknown_command", "bad_request"} and exec_resp.get("ok") is False:
        message = err.get("message") if isinstance(err, dict) else json.dumps(exec_resp, sort_keys=True)[:500]
        # Still attempt probe fallback for unknown_command only; other failures fail closed.
        if code != "unknown_command":
            raise OracleCaptureError(
                "construct_instance_snapshot_failed",
                f"construct_instance_snapshot failed: {code}: {message}",
                details={"response": exec_resp},
            )

    # Probe v8: nested __uninitialized__ args + allowThrow null-path capture.
    probe_name = "ConstructInstanceSnapshotProbe.v8.dll"
    probe_request: dict[str, Any] = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden_cs_recovery live_execution fallback {method_id}",
        "assemblyPath": probe_name,
        "typeName": "OldenCsRecovery.Probes.ConstructInstanceSnapshotProbe",
        "methodName": "Run",
        "targetTypeName": type_name,
        "parameterArity": parameter_arity,
        "argsJson": json.dumps(args, separators=(",", ":")),
        "allowThrow": bool(allow_throw or expect_throw),
    }
    if expect_throw:
        probe_request["expectThrow"] = expect_throw
    if parameter_arity > 0 and parameter_types:
        probe_request["parameterTypes"] = ",".join(parameter_types)
    try:
        probe_resp, freshness = request_live(
            probe_request,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc

    if probe_resp.get("ok") is not True:
        raise OracleCaptureError(
            "construct_snapshot_unavailable",
            (
                "Neither construct_instance_snapshot nor volatile probe construct succeeded. "
                "Deploy OfflineUnlockMod with construct_instance_snapshot and/or place "
                f"{probe_name} under live_probe_bridge/probes, then retry. Fail closed."
            ),
            details={"construct_response": exec_resp, "probe_response": probe_resp},
        )

    payload = _parse_probe_result_payload(probe_resp)
    return payload, freshness, "volatile_load_probe_assembly:" + probe_name


def _nested_construct_args(
    method_id: str, *, happy_path: bool = True
) -> tuple[list[Any], list[str], bool, str | None]:
    """Build nested-field construct args for the two grounded EventArgs ctors."""
    if method_id == "Hex.Session.Battle.EnergyUpdateEventArgs::.ctor(eir,int)":
        types = ["eir", "System.Int32"]
        if happy_path:
            side = {
                # Live Il2CppInterop name for DiffableCs `eir` (bridge field_signatures pin).
                "__uninitialized__": "ObjectPublicPrcgObPrcgInTrPrcgInUnique",
                "fields": {
                    # DiffableCs eir.cglw @ 0xC0 → eix; live type ObjectPublicIncgInObcgObIncgIncgUnique
                    "0xC0": {
                        "__uninitialized__": "ObjectPublicIncgInObcgObIncgIncgUnique",
                        "fields": {
                            "0x10": 42,
                            "0x18": None,
                        },
                    }
                },
            }
            return [side, 7], types, False, None
        return [None, 7], types, True, "NullReferenceException"
    if method_id == (
        "Hex.Session.Battle.UnitStartedMovementEventArgs::.ctor("
        "float,float,int,Unit,EMovementType,Hex[],bool)"
    ):
        types = [
            "System.Single",
            "System.Single",
            "System.Int32",
            "Unit",
            "EMovementType",
            "Hex[]",
            "System.Boolean",
        ]
        if happy_path:
            unit = {
                "__uninitialized__": "Hex.Session.Battle.Unit",
                "fields": {
                    # FieldObject.<cfno> id @ 0x34 (native unit+0x34 load)
                    "0x34": 99,
                },
            }
            return [1.25, 2.5, 3, unit, 0, None, True], types, False, None
        return [1.25, 2.5, 3, None, 0, None, True], types, True, "NullReferenceException"
    raise OracleCaptureError(
        "nested_args_unsupported_method",
        f"no nested construct arg recipe for {method_id}",
    )


def _null_safe_construct_args_for_param_ctor(ir: dict[str, Any]) -> tuple[list[Any], list[str]]:
    """
    Build honest null-safe construct args for a proven base+param field-assign ctor.

    Reference/obfuscated object params → null.
    bool → True (observable vs default false).
    int/enum → small non-zero where useful.
    float → 1.25.
    string → fixed probe marker.
    """
    params = parse_ctor_param_types_from_ir(ir)
    plan = field_assign_plan_from_ir(ir)
    if plan is None or len(params) == 0:
        raise OracleCaptureError(
            "param_ctor_plan_unavailable",
            "cannot derive null-safe construct args without a complete IR field-assign plan",
        )
    args: list[Any] = []
    types: list[str] = []
    # Params that assign into non-reference / non-enum fields need default(T), not null
    # (embedded struct copies such as BattleAiAction).
    value_type_args: set[int] = set()
    for _fname, ftype, action in plan:
        kind, value = action
        if kind != "arg":
            continue
        ft = str(ftype)
        if _looks_like_enum_token(ft):
            continue
        if not _looks_like_reference_field_type_for_construct(ft):
            value_type_args.add(int(value))

    for arg_i, ptype in enumerate(params):
        token = (ptype or "").strip()
        simple = token.split(".")[-1]
        low = token.lower()
        # Nested enums appear as DeclaringType+EEnumName — prefer enum zero over __default__.
        if _looks_like_enum_token(token) or _looks_like_enum_token(simple):
            args.append(0)
            types.append(token if "." in token or "+" in token else simple)
            continue
        if arg_i in value_type_args:
            args.append("__default__")
            types.append(token if "." in token or "+" in token else (token or simple or "object"))
            continue
        if simple in {"bool", "Boolean"} or token in {"System.Boolean", "bool"}:
            args.append(True)
            types.append("System.Boolean")
        elif simple in {"float", "Single"} or token in {"System.Single", "float"}:
            args.append(1.25)
            types.append("System.Single")
        elif simple in {"double", "Double"} or token in {"System.Double", "double"}:
            args.append(1.25)
            types.append("System.Double")
        elif simple in {"string", "String"} or token in {"System.String", "string"}:
            args.append("olden_cs_recovery")
            types.append("System.String")
        elif simple in {"int", "Int32"} or token in {"System.Int32", "int"}:
            args.append(7)
            types.append("System.Int32")
        elif simple in {"long", "Int64"} or token in {"System.Int64", "long"}:
            args.append(7)
            types.append("System.Int64")
        elif token.endswith("[]"):
            args.append(None)
            types.append(token)
        elif simple.startswith("List") or simple.startswith("HashSet"):
            args.append(None)
            types.append(simple)
        else:
            # Obfuscated/reference object params — null-safe only.
            args.append(None)
            types.append(token or simple or "object")
        # silence unused
        _ = low
    return args, types


def _looks_like_reference_field_type_for_construct(field_type: str) -> bool:
    """Mirror replay._looks_like_reference_field_type without importing private helper cycles."""
    from olden_cs_recovery.replay import _looks_like_reference_field_type

    return _looks_like_reference_field_type(field_type)


def _looks_like_enum_token(token: str) -> bool:
    simple = (token or "").split(".")[-1]
    # Nested enums appear as DeclaringType+EEnumName
    if "+" in simple:
        simple = simple.split("+")[-1]
    return bool(simple) and simple.startswith("E") and len(simple) > 1 and simple[1].isupper()


def _capture_edb_ctor_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Live-execution oracle for edb::.ctor via EdbCtorCctorProbe."""
    method_id = item["method_id"]
    meta = EDB_CTOR
    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)

    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb live_execution {method_id}",
        "assemblyPath": "EdbCtorCctorProbe.v1.dll",
        "typeName": "OldenCsRecovery.Probes.EdbCtorCctorProbe",
        "methodName": "Run",
        "targetTypeName": meta["live_type"],
        "mode": "ctor",
        "expectedCtorRva": meta["expected_rva"],
    }
    try:
        response, freshness = request_live(
            payload,
            bridge=bridge,
            timeout_seconds=max(timeout_seconds, 20.0),
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc
    if response.get("ok") is not True:
        raise OracleCaptureError(
            "edb_ctor_probe_bridge_not_ok",
            f"EdbCtorCctorProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OracleCaptureError(
            "edb_ctor_probe_bad_json",
            f"EdbCtorCctorProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        raise OracleCaptureError(
            "edb_ctor_probe_failed",
            f"EdbCtorCctorProbe returned error: {json.dumps(result.get('error'), sort_keys=True)}",
            details={"result": result},
        )

    before = result.get("before") or {}
    after = result.get("after") or {}
    if before.get("byteAt0x2CA") != 0:
        raise OracleCaptureError(
            "edb_ctor_dirty_before",
            "refuse oracle: uninitialized byte @0x2CA was already non-zero",
            details={"before": before},
        )
    if after.get("byteAt0x2CA") != 1:
        raise OracleCaptureError(
            "edb_ctor_byte_not_set",
            "refuse oracle: after ctor byte @0x2CA was not 1",
            details={"after": after},
        )
    cfmw = result.get("cfmw") or {}
    if cfmw.get("value") is not True:
        raise OracleCaptureError(
            "edb_ctor_cfmw_false",
            "refuse oracle: cfmw observation was not true",
            details={"cfmw": cfmw},
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id; refuse oracle capture without build pin",
            details={"freshness": freshness},
        )

    engine_out = {
        "cfmw": {
            "offset": meta["field_offset"],
            "name": meta["field_name"],
            "liveField": meta["live_field"],
            "value": True,
        },
        "byteAt0x2CA": 1,
    }

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": item.get("type_name"),
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": item.get("type_name"),
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "method_id": method_id,
            "parameter_arity": 0,
            "args": [],
            "live_type": result.get("typeName"),
            "bridge_command": "volatile_load_probe_assembly:EdbCtorCctorProbe.v1.dll",
            "setup": "uninitialized_baseline_then_parameterless_ctor",
            "baseline_byteAt0x2CA": 0,
        },
        "outputs": {
            "engine": engine_out,
            "capture_source": "volatile_load_probe_assembly:EdbCtorCctorProbe.v1.dll",
            "probe_identity": result.get("identity"),
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_execution",
            "version": 2,
            "notes": (
                "Invokes EdbCtorCctorProbe on live Golden Era: constructs uninitialized edb, "
                "invokes parameterless .ctor, snapshots byte @0x2CA (cfmw). EquivTester replays "
                "recovered `this.cfmw = true` (+ implicit Object base ctor). Never fabricates."
            ),
        },
        "notes": (
            "Phase 4 live_execution oracle from EdbCtorCctorProbe. "
            "Bar C equivalence-proven requires EquivTester recovered replay match."
        ),
    }
    validate_instance("oracle_trace.schema.json", fixture, method_id)
    oracle_path = write_oracle_trace(fixture)
    return fixture, identity_proof, oracle_path


def _capture_edb_event_accessor_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Live-execution oracle for edb::bcjl / edb::bcjm via EdbEventHandlerProbe."""
    method_id = item["method_id"]
    meta = EDB_EVENT_ACCESSORS[method_id]
    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)

    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb live_execution {method_id}",
        "assemblyPath": "EdbEventHandlerProbe.v1.dll",
        "typeName": "OldenCsRecovery.Probes.EdbEventHandlerProbe",
        "methodName": "Run",
        "targetTypeName": meta["live_type"],
        "invokeMethod": "Method_Public_add_Void_EventHandler_1_BattleEventArgs_0",
        "removeMethod": "Method_Public_rem_Void_EventHandler_1_BattleEventArgs_0",
        # Always run add+remove so remove oracles observe a prior subscribe.
        "alsoRemove": True,
        "expectedAddRva": "0x181EEA920",
        "expectedRemRva": "0x181EEA9D0",
    }
    try:
        response, freshness = request_live(
            payload,
            bridge=bridge,
            timeout_seconds=max(timeout_seconds, 20.0),
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc
    if response.get("ok") is not True:
        raise OracleCaptureError(
            "edb_probe_bridge_not_ok",
            f"EdbEventHandlerProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OracleCaptureError(
            "edb_probe_bad_json",
            f"EdbEventHandlerProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        raise OracleCaptureError(
            "edb_probe_failed",
            f"EdbEventHandlerProbe returned error: {json.dumps(result.get('error'), sort_keys=True)}",
            details={"result": result},
        )

    before = result.get("beforeSubscribe") or {}
    after_add = result.get("afterSubscribe") or {}
    after_rem = result.get("afterUnsubscribe") or {}
    if before.get("nonNullEventHandlerFields") != 0:
        raise OracleCaptureError(
            "edb_probe_dirty_before",
            "refuse oracle: EventHandler fields were already non-null before subscribe",
            details={"before": before},
        )
    if after_add.get("nonNullEventHandlerFields") != 1 or after_add.get("firstNonNullOffset") != meta["field_offset"]:
        raise OracleCaptureError(
            "edb_probe_add_not_observable",
            "refuse oracle: subscribe did not produce exactly one non-null EventHandler at expected offset",
            details={"afterSubscribe": after_add, "meta": meta},
        )
    if after_rem.get("nonNullEventHandlerFields") != 0:
        raise OracleCaptureError(
            "edb_probe_remove_not_observable",
            "refuse oracle: unsubscribe did not clear EventHandler fields",
            details={"afterUnsubscribe": after_rem},
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id; refuse oracle capture without build pin",
            details={"freshness": freshness},
        )

    kind = meta["kind"]
    if kind == "add":
        engine_out = {
            "event_handler_field": {
                "offset": meta["field_offset"],
                "name": meta["field_name"],
                "isNull": False,
            },
            "nonNullEventHandlerFields": 1,
        }
        observed_phase = "afterSubscribe"
    else:
        engine_out = {
            "event_handler_field": {
                "offset": meta["field_offset"],
                "name": meta["field_name"],
                "isNull": True,
            },
            "nonNullEventHandlerFields": 0,
        }
        observed_phase = "afterUnsubscribe"

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": item.get("type_name"),
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": item.get("type_name"),
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "method_id": method_id,
            "accessor_kind": kind,
            "handler": "non_null_il2cpp_eventhandler_1_battleeventargs",
            "live_type": result.get("typeName"),
            "live_method": meta["live_method"],
            "field_offset": meta["field_offset"],
            "bridge_command": "volatile_load_probe_assembly:EdbEventHandlerProbe.v1.dll",
            "setup": "uninitialized_edb_then_subscribe" if kind == "add" else "subscribe_then_unsubscribe",
        },
        "outputs": {
            "engine": engine_out,
            "capture_source": "volatile_load_probe_assembly:EdbEventHandlerProbe.v1.dll",
            "observed_phase": observed_phase,
            "probe_identity": result.get("identity"),
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_execution",
            "version": 2,
            "notes": (
                "Invokes EdbEventHandlerProbe on live Golden Era: constructs edb, creates "
                "Il2CppSystem.EventHandler`1[BattleEventArgs], invokes live add/rem accessors, "
                "snapshots EventHandler field nullness at offset 0x10. EquivTester replays "
                "Delegate.Combine/Remove recovered bodies. Never fabricates engine outputs."
            ),
        },
        "notes": (
            "Phase 4 live_execution oracle from EdbEventHandlerProbe. "
            "Bar C equivalence-proven requires EquivTester recovered replay match."
        ),
    }
    validate_instance("oracle_trace.schema.json", fixture, method_id)
    oracle_path = write_oracle_trace(fixture)
    return fixture, identity_proof, oracle_path


def _capture_edb_cctor_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """
    Live-execution oracle for edb::.cctor via CreateMarker call-trace.

    Oracle shape is call-trace (ordered CreateMarker name arguments), NOT field snapshot.
    Requires early hook install (AAA_CreateMarkerInterceptEarly + SoftDependency) so the
    three edb marker names are captured on first class init. Fail closed on early-init miss.
    """
    method_id = item["method_id"]
    meta = EDB_CCTOR
    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)

    persist = str((bridge / "create_marker_intercept").resolve()).replace("\\", "/")
    payload = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden edb live_execution call_trace {method_id}",
        "assemblyPath": meta["probe_assembly"],
        "typeName": "OldenCsRecovery.Probes.CreateMarkerCallInterceptProbe",
        "methodName": "Run",
        "mode": "harvest_edb",
        "targetTypeName": meta["live_type"],
        "expectedCctorRva": meta["expected_rva"],
        "persistRoot": persist,
    }
    try:
        response, freshness = request_live(
            payload,
            bridge=bridge,
            timeout_seconds=max(timeout_seconds, 30.0),
            require_fresh=True,
        )
    except BridgeUnavailableError as exc:
        raise OracleCaptureError(exc.code, exc.message, details=exc.details) from exc
    if response.get("ok") is not True:
        raise OracleCaptureError(
            "edb_cctor_probe_bridge_not_ok",
            f"CreateMarkerCallInterceptProbe bridge call failed: {json.dumps(response, sort_keys=True)[:500]}",
        )
    raw = response.get("resultText") or ""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OracleCaptureError(
            "edb_cctor_probe_bad_json",
            f"CreateMarkerCallInterceptProbe resultText was not JSON: {exc}",
            details={"resultText": raw[:500]},
        ) from exc
    if result.get("ok") is not True:
        err = result.get("error") or {}
        code = err.get("code") if isinstance(err, dict) else "probe_failed"
        raise OracleCaptureError(
            str(code),
            f"CreateMarkerCallInterceptProbe returned error: {json.dumps(err, sort_keys=True)}",
            details={"result": result, "legacy_field_snapshot_note": EDB_CCTOR_BLOCKED_REASON},
        )

    call_trace = result.get("callTrace") or {}
    calls = call_trace.get("calls") if isinstance(call_trace, dict) else None
    if not isinstance(calls, list) or len(calls) != 3:
        raise OracleCaptureError(
            "edb_cctor_call_trace_incomplete",
            "refuse oracle: harvest_edb must return exactly three CreateMarker calls",
            details={"callTrace": call_trace},
        )
    names = [str(c.get("name") or "") for c in calls]
    expected = list(meta["expected_marker_names"])
    if names != expected:
        raise OracleCaptureError(
            "edb_cctor_marker_names_mismatch",
            f"refuse oracle: call-trace names {names!r} != {expected!r}",
            details={"calls": calls},
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id; refuse oracle capture without build pin",
            details={"freshness": freshness},
        )

    engine_calls = []
    for c in calls:
        engine_calls.append(
            {
                "name": c.get("name"),
                "categoryId": int(c.get("categoryId") or 0),
                "flags": int(c.get("flags") or 0),
                "metadataCount": int(c.get("metadataCount") or 0),
                "returnHandle": str(c.get("returnHandle") or "0x0"),
            }
        )

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": item.get("type_name"),
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": item.get("type_name"),
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "method_id": method_id,
            "oracle_shape": "call_trace",
            "live_type": result.get("typeName"),
            "bridge_command": "volatile_load_probe_assembly:CreateMarkerCallInterceptProbe.v1.dll",
            "setup": "early_createmarker_harmony_hook_then_harvest_edb_names",
            "create_marker_helper_rva": meta["create_marker_helper_rva"],
            "expected_marker_names": expected,
        },
        "outputs": {
            "engine": {
                "oracle_shape": "call_trace",
                "call_trace": {
                    "callee": "Unity.Profiling.LowLevel.Unsafe.ProfilerUnsafeUtility.CreateMarker",
                    "calls": engine_calls,
                },
            },
            "capture_source": "volatile_load_probe_assembly:CreateMarkerCallInterceptProbe.v1.dll",
            "probe_identity": result.get("identity"),
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_execution.call_trace",
            "version": 1,
            "notes": (
                "Call-trace oracle for edb::.cctor: Harmony intercept records ordered "
                "ProfilerUnsafeUtility.CreateMarker(name, categoryId=1, flags=0, metadataCount=0) "
                "arguments during first class init. EquivTester compares call_trace names/args; "
                "does NOT require non-zero ProfilerMarker handles (zero on Golden Era player). "
                "Fail closed on cctor_already_ran_miss / missing names."
            ),
        },
        "notes": (
            "Phase 4 live_execution call-trace oracle from CreateMarkerCallInterceptProbe. "
            "Bar C equivalence-proven requires EquivTester recovered CreateMarker name replay match."
        ),
    }
    validate_instance("oracle_trace.schema.json", fixture, method_id)
    oracle_path = write_oracle_trace(fixture)
    return fixture, identity_proof, oracle_path


def _capture_compgen_accessor_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
    ir: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Capture CompGen getter/setter via FieldAccessorRoundtripProbe.v1."""
    from olden_cs_recovery.replay import compgen_accessor_field

    method_id = item["method_id"]
    type_name = item["type_name"]
    method_name = item.get("method_name") or ""
    info = compgen_accessor_field(ir)
    if info is None:
        raise OracleCaptureError(
            "compgen_ir_unproven",
            f"refuse CompGen capture: IR not proven for {method_id}",
        )

    kind = str(info["kind"])
    field_name = str(info["field_name"])
    arity = 0 if kind == "getter" else 1
    args: list[Any] = []
    if kind == "setter":
        ftype = str(info.get("field_type") or "").lower()
        if "bool" in ftype:
            args = [True]
        else:
            # Reference CompGen setters: null arg is the honest default-construct roundtrip.
            args = [None]

    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)
    native_address = identity_proof.get("native_address")
    if not isinstance(native_address, str) or not native_address.strip():
        raise OracleCaptureError(
            "compgen_identity_missing_native_address",
            (
                f"CompGen identity for {method_id} did not provide native_address; "
                "FieldAccessorRoundtripProbe requires VA resolve (DiffableCs names absent live)."
            ),
            details={"identity_criteria": identity_proof.get("criteria")},
        )

    probe_name = "FieldAccessorRoundtripProbe.v1.dll"
    probe_request: dict[str, Any] = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden phase5 CompGen live_execution {method_id}",
        "assemblyPath": probe_name,
        "typeName": "OldenCsRecovery.Probes.FieldAccessorRoundtripProbe",
        "methodName": "Run",
        "targetTypeName": type_name,
        "accessorMethodName": method_name,
        "nativeAddress": native_address,
        "parameterArity": arity,
        "argsJson": json.dumps(args, separators=(",", ":")),
    }
    probe_resp, freshness = request_live(
        probe_request,
        bridge=bridge,
        timeout_seconds=timeout_seconds,
    )
    if probe_resp.get("ok") is not True:
        raise OracleCaptureError(
            "compgen_probe_failed",
            (
                f"FieldAccessorRoundtripProbe failed for {method_id}. "
                f"Build/deploy {probe_name} under live_probe_bridge/probes. Fail closed."
            ),
            details={"response": probe_resp},
        )
    payload = _parse_probe_result_payload(probe_resp)
    if payload.get("ok") is False:
        raise OracleCaptureError(
            "compgen_probe_payload_error",
            f"probe payload error for {method_id}",
            details={"payload": payload},
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id",
            details={"freshness": freshness},
        )

    engine_out: dict[str, Any]
    if kind == "getter":
        rv = payload.get("returnValue")
        if not isinstance(rv, dict):
            raise OracleCaptureError(
                "compgen_missing_return",
                "getter probe missing returnValue object",
                details={"payload": payload},
            )
        engine_out = {"returnValue": rv}
    else:
        instance = payload.get("instance")
        if not isinstance(instance, dict):
            raise OracleCaptureError(
                "compgen_missing_instance",
                "setter probe missing instance snapshot",
                details={"payload": payload},
            )
        fields = instance.get("fields") if isinstance(instance.get("fields"), dict) else {}
        if field_name not in fields:
            raise OracleCaptureError(
                "compgen_field_absent_in_snapshot",
                f"setter field {field_name!r} absent from probe field snapshot",
                details={"fields": list(fields.keys())[:40]},
            )
        engine_out = {
            "instance": {
                "isNull": False,
                "fields": {field_name: fields[field_name]},
            }
        }

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": type_name,
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": type_name,
            "method_name": method_name,
            "signature": item.get("signature"),
            "method_id": method_id,
            "accessor_kind": kind,
            "parameter_arity": arity,
            "args": args,
            "field_name": field_name,
            "bridge_command": "volatile_load_probe_assembly:" + probe_name,
        },
        "outputs": {
            "engine": engine_out,
            "capture_source": "volatile_load_probe_assembly:" + probe_name,
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_execution.compgen_accessor",
            "version": 1,
            "notes": (
                "Constructs via parameterless ctor, invokes CompGen getter/setter, "
                "records returnValue or written field only. EquivTester replays IR field load/store."
            ),
        },
        "notes": (
            "Phase 5 CompGen accessor live_execution oracle. "
            "Bar C equivalence-proven requires EquivTester recovered replay match."
        ),
    }
    path = write_oracle_trace(fixture)
    return fixture, identity_proof, path


def _capture_write_body_field_delta_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Capture Direct State write-body field-delta via WriteBodyFieldDeltaProbe.v4."""
    from olden_cs_recovery.field_delta import (
        FIELD_DELTA_PROTOCOL_NAME,
        is_direct_state_write_body_method,
        native_va_for,
        normalize_field_delta_engine,
    )

    method_id = item["method_id"]
    type_name = item["type_name"]
    if not is_direct_state_write_body_method(method_id, domain=item.get("domain")):
        raise OracleCaptureError(
            "not_write_body_method",
            f"field-delta capture refuses non-write-body method {method_id!r}",
        )

    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)
    native_address = identity_proof.get("native_address") or native_va_for(method_id)
    if not isinstance(native_address, str) or not native_address.strip():
        raise OracleCaptureError(
            "write_body_missing_native_address",
            (
                f"write-body identity/pin table missing nativeAddress for {method_id}. "
                "Pin against mono_live_pin_table / DummyDLL RVA before capture."
            ),
            details={"identity_criteria": identity_proof.get("criteria")},
        )

    probe_name = "WriteBodyFieldDeltaProbe.v5.dll"
    probe_request: dict[str, Any] = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden DirectState write-body field-delta {method_id}",
        "assemblyPath": probe_name,
        "typeName": "OldenCsRecovery.Probes.WriteBodyFieldDeltaProbe",
        "methodName": "Run",
        "scenario": method_id,
        "methodId": method_id,
        "nativeAddress": native_address,
        "targetTypeName": type_name,
    }
    probe_resp, freshness = request_live(
        probe_request,
        bridge=bridge,
        timeout_seconds=max(timeout_seconds, 30.0),
    )
    if probe_resp.get("ok") is not True:
        raise OracleCaptureError(
            "write_body_probe_failed",
            (
                f"WriteBodyFieldDeltaProbe failed for {method_id}. "
                f"Build/deploy {probe_name} under live_probe_bridge/probes. Fail closed."
            ),
            details={"response": probe_resp},
        )
    payload = _parse_probe_result_payload(probe_resp)
    if payload.get("ok") is False:
        raise OracleCaptureError(
            "write_body_probe_payload_error",
            f"probe payload error for {method_id}",
            details={"payload": payload},
        )

    engine_out = normalize_field_delta_engine(payload)
    if not engine_out.get("hasRealDiff"):
        # Still write the oracle (honest empty delta) but leave EquivTester to refuse proof.
        pass

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id",
            details={"freshness": freshness},
        )

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": type_name,
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": type_name,
            "method_id": method_id,
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "native_address": native_address,
            "scenario": method_id,
            "bridge_command": "volatile_load_probe_assembly:" + probe_name,
        },
        "outputs": {
            "engine": engine_out,
            "capture_source": "volatile_load_probe_assembly:" + probe_name,
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": FIELD_DELTA_PROTOCOL_NAME,
            "version": 1,
            "notes": (
                "Plant minimal Hex/FieldObject/edf/(UnitData/eep/eda) graph, invoke write body by "
                "native VA, record before/after field deltas. EquivTester requires hasRealDiff."
            ),
        },
        "notes": (
            "Direct State M1 field-delta live_execution oracle. Bar C equivalence-proven only when "
            "EquivTester sees real store/membership diffs."
        ),
    }
    path = write_oracle_trace(fixture)
    return fixture, identity_proof, path


def _capture_dest_recipe_call_trace_execution(
    item: dict[str, Any],
    *,
    bridge: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Capture Direct State DestRecipe call-trace via DestRecipeCallTraceProbe.v1."""
    from olden_cs_recovery.dest_recipe import (
        CALL_TRACE_PROTOCOL_NAME,
        is_dest_recipe_method,
        native_va_for_dest_recipe,
        normalize_call_trace_engine,
    )
    from olden_cs_recovery.field_delta import native_va_for

    method_id = item["method_id"]
    type_name = item["type_name"]
    if not is_dest_recipe_method(method_id, domain=item.get("domain")):
        raise OracleCaptureError(
            "not_dest_recipe_method",
            f"call-trace dest-recipe capture refuses {method_id!r}",
        )

    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)
    native_address = (
        identity_proof.get("native_address")
        or native_va_for_dest_recipe(method_id)
        or native_va_for(method_id)
    )
    if not isinstance(native_address, str) or not native_address.strip():
        raise OracleCaptureError(
            "dest_recipe_missing_native_address",
            f"DestRecipe pin table missing nativeAddress for {method_id}.",
            details={"identity_criteria": identity_proof.get("criteria")},
        )

    probe_name = "DestRecipeCallTraceProbe.v1.dll"
    probe_request: dict[str, Any] = {
        "command": "volatile_load_probe_assembly",
        "reason": f"olden DirectState dest-recipe call-trace {method_id}",
        "assemblyPath": probe_name,
        "typeName": "OldenCsRecovery.Probes.DestRecipeCallTraceProbe",
        "methodName": "Run",
        "scenario": method_id,
        "methodId": method_id,
        "nativeAddress": native_address,
        "targetTypeName": type_name,
    }
    probe_resp, freshness = request_live(
        probe_request,
        bridge=bridge,
        timeout_seconds=max(timeout_seconds, 30.0),
    )
    if probe_resp.get("ok") is not True:
        raise OracleCaptureError(
            "dest_recipe_probe_failed",
            (
                f"DestRecipeCallTraceProbe failed for {method_id}. "
                f"Build/deploy {probe_name} under live_probe_bridge/probes. Fail closed."
            ),
            details={"response": probe_resp},
        )
    payload = _parse_probe_result_payload(probe_resp)
    if payload.get("ok") is False:
        raise OracleCaptureError(
            "dest_recipe_probe_payload_error",
            f"probe payload error for {method_id}: {payload.get('error')}: {payload.get('message')}",
            details={"payload": payload},
        )

    engine_out = normalize_call_trace_engine(payload)
    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id",
            details={"freshness": freshness},
        )

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": type_name,
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": {
            "type_name": type_name,
            "method_id": method_id,
            "method_name": item.get("method_name"),
            "signature": item.get("signature"),
            "native_address": native_address,
            "scenario": method_id,
            "bridge_command": "volatile_load_probe_assembly:" + probe_name,
        },
        "outputs": {
            "engine": engine_out,
            "capture_source": "volatile_load_probe_assembly:" + probe_name,
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": CALL_TRACE_PROTOCOL_NAME,
            "version": 1,
            "notes": (
                "DestRecipe call-trace: plant inputs → observe return/stores/dest shape. "
                "Role=dest_recipe only; commit ownership stays on bfdi. EquivTester requires hasRealTrace."
            ),
        },
        "notes": (
            "Direct State M2 call-trace live_execution oracle (dest_recipe). "
            "Not commit ownership. Bar C only when EquivTester sees real trace."
        ),
    }
    path = write_oracle_trace(fixture)
    return fixture, identity_proof, path


def capture_live_execution(
    item: dict[str, Any],
    *,
    bridge: Path | None = None,
    timeout_seconds: float = 8.0,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """
    Capture live_execution via construct_instance_snapshot or EdbEventHandlerProbe.

    Honest surfaces (fail closed otherwise):
    - parameterless EventArgs ctors whose IR is base-only
    - single-bool EventArgs ctors whose IR is base() + one bool field assign
    - linear base()+param/const field-assign EventArgs (Il2Cpp write barriers allowed)
      with null-safe reference args + primitive/enum/string values
    - nested-null-guarded field-copy EventArgs (EnergyUpdate eir,int / UnitStartedMovement)
      with planted nested objects or null-throw observation
    - edb CompilerGenerated EventHandler add/remove (bcjl/bcjm) via EdbEventHandlerProbe
    - edb::.ctor() via EdbCtorCctorProbe
    - edb::.cctor() via CreateMarker call-trace (CreateMarkerCallInterceptProbe)
    - DirectState.WriteBody field-delta via WriteBodyFieldDeltaProbe
    - DirectState.WriteBody/DestRecipe call-trace via DestRecipeCallTraceProbe
    Never fabricates outputs.
    """
    bridge = bridge or default_bridge_dir()
    method_id = item["method_id"]
    if method_id == EDB_CCTOR["method_id"]:
        return _capture_edb_cctor_execution(
            item,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
        )
    if method_id == EDB_CTOR["method_id"]:
        return _capture_edb_ctor_execution(
            item,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
        )
    if method_id in EDB_EVENT_ACCESSORS:
        return _capture_edb_event_accessor_execution(
            item,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
        )

    type_name = item["type_name"]
    arity = _ctor_parameter_arity(method_id)
    ir = load_ir(method_id)

    # Direct State write bodies: DestRecipe call-trace (M2) or Commit field-delta (M1).
    from olden_cs_recovery.dest_recipe import is_dest_recipe_method
    from olden_cs_recovery.field_delta import is_direct_state_write_body_method, native_va_for
    from olden_cs_recovery.replay import is_compgen_field_getter, is_compgen_field_setter, compgen_accessor_field

    domain = str(item.get("domain") or "")
    if is_dest_recipe_method(method_id, domain=domain) or domain.startswith(
        "DirectState.WriteBody/DestRecipe"
    ):
        return _capture_dest_recipe_call_trace_execution(
            item,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
        )
    if is_direct_state_write_body_method(method_id, domain=domain):
        # CompGen readbacks (edf.bcun) may use either path; field-delta is preferred for M1.
        if native_va_for(method_id) or domain.startswith("DirectState.WriteBody"):
            return _capture_write_body_field_delta_execution(
                item,
                bridge=bridge,
                timeout_seconds=timeout_seconds,
            )

    # Phase 5 CompGen field accessors (Unit/Hex): FieldAccessorRoundtripProbe.
    if arity is None and ir is not None and (is_compgen_field_getter(ir) or is_compgen_field_setter(ir)):
        return _capture_compgen_accessor_execution(
            item,
            bridge=bridge,
            timeout_seconds=timeout_seconds,
            ir=ir,
        )

    if arity is None:
        raise OracleCaptureError(
            "live_execution_unsupported_method",
            f"live_execution capture currently supports .ctor methods, CompGen accessors, and DirectState write-body field-delta only; got {method_id!r}",
        )

    construct_args: list[Any] = []
    parameter_types: list[str] = []
    allow_throw = False
    expect_throw: str | None = None
    if arity == 0:
        if not is_base_only_parameterless_ctor(ir):
            raise OracleCaptureError(
                "live_execution_ir_not_base_only",
                (
                    "refuse live_execution: IR is not a proven base-only parameterless EventArgs ctor. "
                    "Complex bodies need a dedicated execution surface first."
                ),
                details={"method_id": method_id},
            )
    elif arity == 1 and is_base_then_bool_field_assign_ctor(ir):
        # Capture with true so the field write is observable (false is also the zero default).
        construct_args = [True]
        parameter_types = ["System.Boolean"]
    elif ir is not None and is_base_then_param_field_assign_ctor(ir):
        construct_args, parameter_types = _null_safe_construct_args_for_param_ctor(ir)
        if len(construct_args) != arity:
            raise OracleCaptureError(
                "param_ctor_arity_mismatch",
                f"derived args length {len(construct_args)} != method arity {arity}",
                details={"method_id": method_id, "args": construct_args},
            )
    elif ir is not None and is_nested_null_guarded_field_copy_ctor(ir):
        construct_args, parameter_types, allow_throw, expect_throw = _nested_construct_args(
            method_id, happy_path=True
        )
        if len(construct_args) != arity:
            raise OracleCaptureError(
                "nested_ctor_arity_mismatch",
                f"nested args length {len(construct_args)} != method arity {arity}",
                details={"method_id": method_id, "args": construct_args},
            )
    else:
        raise OracleCaptureError(
            "live_execution_requires_supported_surface",
            (
                f"live_execution capture for this ctor is not enabled yet (arity={arity}). "
                "Supported: parameterless base-only, single-bool base+field-assign, "
                "linear base+param field-assign with null-safe args, or nested-null-guarded "
                "field-copy EventArgs. Fail closed."
            ),
            details={"method_id": method_id, "arity": arity},
        )

    identity_proof, identity_path = _ensure_identity(item, bridge=bridge, timeout_seconds=timeout_seconds)

    exec_resp, freshness, exec_source = _invoke_construct_snapshot(
        type_name=type_name,
        method_id=method_id,
        bridge=bridge,
        timeout_seconds=timeout_seconds,
        parameter_arity=arity,
        args=construct_args,
        parameter_types=parameter_types,
        allow_throw=allow_throw,
        expect_throw=expect_throw,
    )

    instance = exec_resp.get("instance")
    threw = exec_resp.get("threw")
    if threw is not None and not isinstance(threw, dict):
        raise OracleCaptureError(
            "construct_snapshot_bad_threw",
            "construct snapshot threw payload must be an object",
            details={"response": exec_resp, "source": exec_source},
        )
    if threw is None and not isinstance(instance, dict):
        raise OracleCaptureError(
            "construct_snapshot_missing_instance",
            "construct snapshot response missing instance object",
            details={"response": exec_resp, "source": exec_source},
        )

    pin = build_pin_metadata(bridge_freshness=freshness)
    if not pin.get("game_build_id"):
        raise OracleCaptureError(
            "missing_game_build_id",
            "bridge freshness did not provide game build id; refuse oracle capture without build pin",
            details={"freshness": freshness},
        )

    engine_out: dict[str, Any]
    if threw is not None:
        engine_out = {"threw": {"type": str(threw.get("type") or "NullReferenceException")}}
    else:
        engine_out = {"instance": instance}

    inputs: dict[str, Any] = {
        "type_name": type_name,
        "method_name": item.get("method_name"),
        "signature": item.get("signature"),
        "method_id": method_id,
        "parameter_arity": arity,
        "args": construct_args,
        "parameter_types": parameter_types,
        "bridge_command": exec_source,
    }
    if expect_throw:
        inputs["expect_throw"] = expect_throw

    fixture = {
        "schema_version": 1,
        "method_id": method_id,
        "capture_kind": "live_execution",
        "synthetic": False,
        "game_build_id": pin["game_build_id"],
        "gameassembly_sha256": pin["gameassembly_sha256"],
        "bridge_profile": pin.get("bridge_profile"),
        "bridge_scene": pin.get("bridge_scene"),
        "bridge_frame": pin.get("bridge_frame"),
        "captured_at": to_iso(utc_now()),
        "type_name": type_name,
        "signature": item.get("signature"),
        "identity_criteria": identity_proof.get("criteria"),
        "identity_proof_path": rel_repo(identity_path),
        "inputs": inputs,
        "outputs": {
            "engine": engine_out,
            "constructor_parameter_types": exec_resp.get("constructorParameterTypes") or parameter_types,
            "capture_source": exec_source,
        },
        "numeric_tolerances": {},
        "protocol": {
            "name": "olden_cs_recovery.live_execution",
            "version": 2,
            "notes": (
                "Invokes construct_instance_snapshot / probe v8 on the live Golden Era process and "
                "records observable instance fields or null-throw outcomes. EquivTester replays "
                "recovered/IR for supported EventArgs surfaces including nested-null-guarded copies. "
                "Never fabricates engine outputs."
            ),
        },
        "notes": (
            "Phase 4 live_execution oracle from construct_instance_snapshot/probe. "
            "Bar C equivalence-proven requires EquivTester recovered replay match."
        ),
    }
    path = write_oracle_trace(fixture)
    return fixture, identity_proof, path


def capture_claimed_items(
    claimed_pairs: list[tuple[Path, dict[str, Any]]],
    *,
    holder: str,
    bridge: Path | None = None,
    capture_kind: str = "live_execution",
) -> dict[str, Any]:
    """
    Oracle capturer role body.

    Default capture_kind=live_execution (bar-C path).
    """
    if capture_kind not in CAPTURE_KINDS:
        raise OracleCaptureError(
            "invalid_capture_kind",
            f"capture_kind must be one of {CAPTURE_KINDS}, got {capture_kind!r}",
        )

    bridge = bridge or default_bridge_dir()
    captured: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    identity_only: list[dict[str, Any]] = []

    for path, item in claimed_pairs:
        method_id = item["method_id"]
        prior_stage = item.get("stage")
        try:
            if capture_kind == "live_execution":
                fixture, identity_proof, oracle_path = capture_live_execution(item, bridge=bridge)
            else:
                fixture, identity_proof, oracle_path = capture_live_surface_metadata(item, bridge=bridge)

            id_abs = REPO_ROOT / fixture["identity_proof_path"]
            apply_identity_to_ledger(item, identity_proof, id_abs)

            write_ledger_entry(
                method_id=method_id,
                status="oracle-captured",
                previous_status="identity-bridged",
                notes=(
                    f"Oracle captured ({fixture['capture_kind']}). "
                    + (
                        "Ready for EquivTester bar-C replay."
                        if fixture["capture_kind"] == "live_execution"
                        else "Not equivalence-proven (bar C requires live_execution replay)."
                    )
                ),
                evidence_refs=[
                    {
                        "kind": "oracle_trace",
                        "path": rel_repo(oracle_path),
                        "notes": f"capture_kind={fixture['capture_kind']}",
                    }
                ],
                queue_item=item,
            )

            if prior_stage == "equiv_test":
                next_stage = "equiv_test"
            else:
                if "equiv_test" not in ALLOWED_STAGE_TRANSITIONS.get("oracle_capture", frozenset()):
                    raise OracleCaptureError("illegal_stage", "oracle_capture→equiv_test not allowed")
                next_stage = "equiv_test"

            updated = dict(item)
            updated["stage"] = next_stage
            updated["proof_status"] = "oracle-captured"
            updated["blocked_reason"] = None
            refs = list(updated.get("evidence_refs") or [])
            refs.append(
                {
                    "kind": "oracle_trace",
                    "path": rel_repo(oracle_path),
                    "required": True,
                    "notes": f"Phase 3/4 oracle ({fixture['capture_kind']})",
                }
            )
            updated["evidence_refs"] = refs
            updated["notes"] = (
                (item.get("notes") or "") + f" | oracle-captured ({fixture['capture_kind']})"
            ).strip(" |")
            updated["updated_at"] = to_iso(utc_now())
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=path)
            captured.append(
                {
                    "method_id": method_id,
                    "oracle_path": rel_repo(oracle_path),
                    "identity_criteria": identity_proof.get("criteria"),
                    "capture_kind": fixture["capture_kind"],
                    "game_build_id": fixture["game_build_id"],
                    "gameassembly_sha256": fixture["gameassembly_sha256"],
                    "stage": next_stage,
                    "proof_status": "oracle-captured",
                }
            )
        except (OracleCaptureError, IdentityProbeError, BridgeUnavailableError) as exc:
            code = getattr(exc, "code", "capture_failed")
            message = getattr(exc, "message", str(exc))
            details = getattr(exc, "details", {})
            updated = dict(item)
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=path)
            failed.append(
                {
                    "method_id": method_id,
                    "error": code,
                    "message": message,
                    "details": details,
                    "stage": prior_stage,
                    "left_claimable": True,
                }
            )

    return {
        "ok": len(failed) == 0 and len(captured) > 0,
        "captured": captured,
        "failed": failed,
        "identity_only": identity_only,
        "capture_kind": capture_kind,
        "counts": {
            "captured": len(captured),
            "failed": len(failed),
        },
        "note": (
            f"Oracle capturer wrote {capture_kind} fixtures when the bridge could execute/observe. "
            "Bridge unavailable or unsupported method → fail closed, leases released. "
            "equivalence-proven is never set here."
        ),
    }
