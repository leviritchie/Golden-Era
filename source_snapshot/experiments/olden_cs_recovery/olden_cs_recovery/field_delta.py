"""Direct State write-body field-delta oracle helpers (M1 bar C)."""

from __future__ import annotations

from typing import Any

# Pin-table / DummyDLL VAs (GameAssembly preferred base 0x180000000).
WRITE_BODY_NATIVE_VAS: dict[str, str] = {
    "Hex.Session.Battle.UnitData::bfdi(Hex)": "0x182078360",
    "edf::bcuo(Hex)": "0x181F055B0",
    "edf::bcun()": "0x1805B97C0",
    "Hex.Session.Battle.Hex::bcyn(FieldObject)": "0x181F33CB0",
    "Hex.Session.Battle.Hex::bcyl(FieldObject)": "0x181F33BA0",
    "eep::bdhv(Unit,Hex)": "0x181F463F0",
    "eep::bdhw(Unit,Hex)": "0x181F465D0",
    "eda::bcim(object,BattleEventArgs)": "0x181EE3BC0",
}

# Capstone / pin-table Unresolved codes that are expected for write-body stub IR.
# EquivTester may ignore these when protocol is field_delta and a real live delta exists.
WRITE_BODY_FIELD_DELTA_UNRESOLVED = frozenset(
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

FIELD_DELTA_PROTOCOL_NAME = "olden_cs_recovery.live_execution.field_delta"


def is_direct_state_write_body_method(method_id: str, *, domain: str | None = None) -> bool:
    if domain and str(domain).startswith("DirectState.WriteBody"):
        return True
    from olden_cs_recovery.damage_side import DAMAGE_SIDE_NATIVE_VAS

    return method_id in WRITE_BODY_NATIVE_VAS or method_id in DAMAGE_SIDE_NATIVE_VAS


def native_va_for(method_id: str) -> str | None:
    if method_id in WRITE_BODY_NATIVE_VAS:
        return WRITE_BODY_NATIVE_VAS[method_id]
    from olden_cs_recovery.damage_side import native_va_for_damage_side
    from olden_cs_recovery.dest_recipe import native_va_for_dest_recipe

    return native_va_for_damage_side(method_id) or native_va_for_dest_recipe(method_id)


def expected_field_delta_engine(method_id: str) -> dict[str, Any]:
    """
    Recovered expected engine outputs for EquivTester.

    Derived from Capstone call/store dossiers + pin table — not invented CF.
    EquivTester also requires hasRealDiff=true on the live oracle.
    """
    if method_id.endswith("::bcyl(FieldObject)") or method_id.endswith("Hex::bcyl(FieldObject)"):
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "fieldObjectsCount": {"from": 0, "to": 1},
                "membershipContainsFo": {"from": False, "to": True},
            },
            "requiredDeltaKeys": ["fieldObjectsCount", "membershipContainsFo"],
        }
    if method_id.endswith("::bcyn(FieldObject)") or method_id.endswith("Hex::bcyn(FieldObject)"):
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "fieldObjectsCount": {"from": 1, "to": 0},
                "membershipContainsFo": {"from": True, "to": False},
            },
            "requiredDeltaKeys": ["fieldObjectsCount", "membershipContainsFo"],
        }
    if method_id == "edf::bcuo(Hex)" or method_id.endswith("::bcuo(Hex)"):
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "helperHexIsFrom": {"from": True, "to": False},
                "helperHexIsTo": {"from": False, "to": True},
                "fromMembership": {"from": True, "to": False},
                "toMembership": {"from": False, "to": True},
            },
            "requiredDeltaKeys": [
                "helperHexIsFrom",
                "helperHexIsTo",
                "fromMembership",
                "toMembership",
            ],
        }
    if method_id == "edf::bcun()" or method_id.endswith("::bcun()"):
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "returnWasNull": {"from": True, "to": False},
                "returnSameAsPlanted": {"from": None, "to": True},
            },
            "requiredDeltaKeys": ["returnWasNull"],
        }
    if method_id.endswith("::bfdi(Hex)"):
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "helperHexIsFrom": {"from": True, "to": False},
                "helperHexIsTo": {"from": False, "to": True},
                "fromMembership": {"from": True, "to": False},
                "toMembership": {"from": False, "to": True},
            },
            "requiredDeltaKeys": [
                "helperHexIsFrom",
                "helperHexIsTo",
                "fromMembership",
                "toMembership",
            ],
        }
    # Notify/publish with empty listeners / null cfia: no store mutation.
    # EquivTester must refuse equivalence-proven (no real diffs).
    if method_id.startswith("eep::bdhv") or method_id.startswith("eep::bdhw") or method_id.startswith(
        "eda::bcim"
    ):
        return {
            "hasRealDiff": False,
            "fieldDelta": {},
            "requiredDeltaKeys": [],
            "notes": (
                "Empty-listener / null-cfia plant produces no store mutation. "
                "Bar C requires real diffs — capture with live battle listeners or planted cfia handler."
            ),
        }
    from olden_cs_recovery.damage_side import (
        expected_field_delta_engine_damage_side,
        is_damage_side_method,
        is_lifecycle_spawn_method,
    )

    if is_damage_side_method(method_id) or is_lifecycle_spawn_method(method_id):
        return expected_field_delta_engine_damage_side(method_id)
    raise KeyError(f"no field-delta expectation for {method_id}")


def normalize_field_delta_engine(payload: dict[str, Any]) -> dict[str, Any]:
    """Build EquivTester-comparable engine object from probe payload."""
    field_delta = payload.get("fieldDelta")
    if not isinstance(field_delta, dict):
        field_delta = {}
    has_real = bool(payload.get("hasRealDiff")) and len(field_delta) > 0
    return {
        "hasRealDiff": has_real,
        "fieldDelta": field_delta,
        "before": payload.get("before") if isinstance(payload.get("before"), dict) else {},
        "after": payload.get("after") if isinstance(payload.get("after"), dict) else {},
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
    }


def compare_field_delta(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Compare recovered expected field-delta shape to live probe engine output.

    Requires hasRealDiff on both sides. Checks requiredDeltaKeys presence and
    from/to equality for those keys only (extra live keys allowed as corroboration).
    """
    diffs: list[dict[str, Any]] = []
    if not expected.get("hasRealDiff"):
        diffs.append(
            {
                "path": "$.hasRealDiff",
                "expected": True,
                "actual": expected.get("hasRealDiff"),
                "reason": "expected_has_no_real_diff",
            }
        )
        return diffs
    if not actual.get("hasRealDiff"):
        diffs.append(
            {
                "path": "$.hasRealDiff",
                "expected": True,
                "actual": actual.get("hasRealDiff"),
                "reason": "live_has_no_real_diff",
            }
        )
        return diffs

    exp_delta = expected.get("fieldDelta") if isinstance(expected.get("fieldDelta"), dict) else {}
    act_delta = actual.get("fieldDelta") if isinstance(actual.get("fieldDelta"), dict) else {}
    required = list(expected.get("requiredDeltaKeys") or exp_delta.keys())
    for key in required:
        if key not in act_delta:
            diffs.append(
                {
                    "path": f"$.fieldDelta.{key}",
                    "expected": exp_delta.get(key),
                    "actual": None,
                    "reason": "missing_delta_key",
                }
            )
            continue
        exp_row = exp_delta.get(key)
        act_row = act_delta.get(key)
        if not isinstance(exp_row, dict) or not isinstance(act_row, dict):
            if exp_row != act_row:
                diffs.append(
                    {
                        "path": f"$.fieldDelta.{key}",
                        "expected": exp_row,
                        "actual": act_row,
                        "reason": "delta_row_mismatch",
                    }
                )
            continue
        for side in ("from", "to"):
            if side not in exp_row:
                continue
            if exp_row.get(side) != act_row.get(side):
                diffs.append(
                    {
                        "path": f"$.fieldDelta.{key}.{side}",
                        "expected": exp_row.get(side),
                        "actual": act_row.get(side),
                        "reason": "delta_value_mismatch",
                    }
                )
    return diffs
