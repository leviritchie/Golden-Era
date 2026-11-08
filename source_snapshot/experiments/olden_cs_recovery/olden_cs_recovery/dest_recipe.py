"""Direct State M2 dest-recipe call-trace oracle helpers (adapter INPUT only)."""

from __future__ import annotations

from typing import Any

# Pin-table / DummyDLL VAs (GameAssembly preferred base 0x180000000).
DEST_RECIPE_NATIVE_VAS: dict[str, str] = {
    "Hex.Session.Battle.Hex::bcyf(int,bool b =,ETargetAllegiance c =)": "0x181F334B0",
    "ehh::Init(string[])": "0x181FD4740",
    "ehh::bdpe(eab,eac,InCastArgs,FieldObject,eaa)": "0x181FD4AC0",
    "een::bdeo(float,float)": "0x181F3D0E0",
    "een::bdep(int)": "0x181F3D1B0",
    "eeu::bdke(Hex,Hex)": "0x181F772B0",
}

CALL_TRACE_PROTOCOL_NAME = "olden_cs_recovery.live_execution.call_trace_dest_recipe"

# Capstone/ISIL Unresolved codes expected on dest-recipe stub IR.
DEST_RECIPE_CALL_TRACE_UNRESOLVED = frozenset(
    {
        "write_body_capstone_stub",
        "mandatory_unresolved_write_body",
        "opaque_branch_target",
        "unresolved_native_call",
        "static_lift_only",
        "method_native_address_unmapped",
        "native_disasm_absent",
        "null_throw_helper_branch",
        "routine_metadata_guard_branch",
    }
)


def is_dest_recipe_method(method_id: str, *, domain: str | None = None) -> bool:
    if domain and str(domain).startswith("DirectState.WriteBody/DestRecipe"):
        return True
    return method_id in DEST_RECIPE_NATIVE_VAS


def native_va_for_dest_recipe(method_id: str) -> str | None:
    return DEST_RECIPE_NATIVE_VAS.get(method_id)


def expected_call_trace_engine(method_id: str) -> dict[str, Any]:
    """
    Recovered expected engine outputs for EquivTester (call-trace shape).

    Derived from pin table / Capstone store notes — not invented CF.
    EquivTester requires hasRealTrace=true on the live oracle.
    """
    if "bcyf" in method_id:
        return {
            "hasRealTrace": True,
            "oracle_shape": "call_trace",
            "call_trace": {
                "scenario": "bcyf_blocked_from_all",
                "returnValue": True,
                "inputs": {"side": 0, "ignoreUnits": False, "allegiance": 2},
            },
            "requiredKeys": ["returnValue"],
        }
    if method_id.endswith("::Init(string[])") or method_id == "ehh::Init(string[])":
        return {
            "hasRealTrace": True,
            "oracle_shape": "call_trace",
            "call_trace": {
                "scenario": "ehh_init_bool_params",
                "stores": {"cgfy_pushInwards": True, "cgfz_skipCenter": False},
                "inputs": {"parameters": ["true", "false"]},
            },
            "requiredKeys": ["stores"],
        }
    if method_id == "eeu::bdke(Hex,Hex)" or method_id.endswith("::bdke(Hex,Hex)"):
        return {
            "hasRealTrace": True,
            "oracle_shape": "call_trace",
            "call_trace": {
                "scenario": "eeu_bdke_bare_hex_pair",
                "distance": 0,
                "inputs": {"hexA": "allocated", "hexB": "allocated"},
            },
            "requiredKeys": ["distance"],
        }
    # Helpers / ApplyForReceiver need richer plants — EquivTester refuses until real trace.
    return {
        "hasRealTrace": False,
        "oracle_shape": "call_trace",
        "call_trace": {},
        "requiredKeys": [],
    }


def normalize_call_trace_engine(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize DestRecipeCallTraceProbe payload into oracle engine outputs."""
    trace = payload.get("callTrace") if isinstance(payload.get("callTrace"), dict) else {}
    if not trace and isinstance(payload.get("call_trace"), dict):
        trace = payload["call_trace"]
    has_real = bool(payload.get("hasRealTrace") or payload.get("hasRealDiff"))
    if not has_real:
        # Infer from observable return/stores.
        if trace.get("returnValue") is not None:
            has_real = True
        stores = trace.get("stores")
        if isinstance(stores, dict) and stores:
            has_real = True
        if trace.get("destHexCount") is not None or trace.get("distance") is not None:
            has_real = True
    return {
        "hasRealTrace": has_real,
        "oracle_shape": "call_trace",
        "call_trace": trace,
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
        "methodId": payload.get("methodId"),
        "resolvedMethodName": payload.get("resolvedMethodName"),
        "nativeAddress": payload.get("nativeAddress"),
    }


def compare_call_trace(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fail-closed compare of dest-recipe call-trace engines."""
    diffs: list[dict[str, Any]] = []
    if not actual.get("hasRealTrace"):
        diffs.append(
            {
                "path": "$.hasRealTrace",
                "expected": True,
                "actual": actual.get("hasRealTrace"),
                "reason": "no_real_call_trace",
            }
        )
        return diffs
    exp_trace = expected.get("call_trace") if isinstance(expected.get("call_trace"), dict) else {}
    act_trace = actual.get("call_trace") if isinstance(actual.get("call_trace"), dict) else {}
    for key in expected.get("requiredKeys") or []:
        if key == "returnValue":
            if exp_trace.get("returnValue") != act_trace.get("returnValue"):
                diffs.append(
                    {
                        "path": "$.call_trace.returnValue",
                        "expected": exp_trace.get("returnValue"),
                        "actual": act_trace.get("returnValue"),
                        "reason": "return_mismatch",
                    }
                )
        elif key == "distance":
            if exp_trace.get("distance") != act_trace.get("distance"):
                diffs.append(
                    {
                        "path": "$.call_trace.distance",
                        "expected": exp_trace.get("distance"),
                        "actual": act_trace.get("distance"),
                        "reason": "distance_mismatch",
                    }
                )
        elif key == "stores":
            exp_stores = exp_trace.get("stores") if isinstance(exp_trace.get("stores"), dict) else {}
            act_stores = act_trace.get("stores") if isinstance(act_trace.get("stores"), dict) else {}
            for sk, sv in exp_stores.items():
                if act_stores.get(sk) != sv:
                    diffs.append(
                        {
                            "path": f"$.call_trace.stores.{sk}",
                            "expected": sv,
                            "actual": act_stores.get(sk),
                            "reason": "store_mismatch",
                        }
                    )
    return diffs
