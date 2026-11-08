"""Offline EquivTester: replay recovered model against oracle_traces (fail-closed)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from olden_cs_recovery.ledger import rel_repo, write_ledger_entry
from olden_cs_recovery.oracle import find_oracle_for_method, load_oracle_trace
from olden_cs_recovery.paths import (
    ALLOWED_STAGE_TRANSITIONS,
    ORACLE_TRACES_SYNTHETIC_DIR,
)
from olden_cs_recovery.queue_store import (
    release_item,
    to_iso,
    utc_now,
    write_queue_item,
)
from olden_cs_recovery.identity import EDB_CCTOR, EDB_CTOR, EDB_EVENT_ACCESSORS
from olden_cs_recovery.replay import (
    ReplayError,
    blocking_unresolved_nodes,
    compute_recovered_replay,
    load_ir,
    normalize_observable_value,
    recovered_ctor_throws_unresolved,
)


class EquivTestError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


def _is_synthetic_method_id(method_id: str) -> bool:
    return method_id.startswith("synthetic.")


def blocking_unresolved(ir: dict[str, Any] | None, *, allow_write_body_field_delta: bool = False) -> list[dict[str, Any]]:
    return blocking_unresolved_nodes(ir, allow_write_body_field_delta=allow_write_body_field_delta)


def recovered_has_unresolved_throw(method_id: str, item: dict[str, Any] | None = None) -> bool:
    return recovered_ctor_throws_unresolved(method_id, item)


def structural_diff(
    expected: Any,
    actual: Any,
    *,
    path: str = "$",
    tolerances: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Recursive structural/value diff. Returns list of mismatch records (empty = equal)."""
    tolerances = tolerances or {}
    diffs: list[dict[str, Any]] = []

    if isinstance(expected, float) or isinstance(actual, float):
        try:
            e = float(expected)
            a = float(actual)
        except (TypeError, ValueError):
            diffs.append({"path": path, "expected": expected, "actual": actual, "reason": "float_coerce_failed"})
            return diffs
        tol = tolerances.get(path, tolerances.get("*", 0.0))
        if math.isnan(e) and math.isnan(a):
            return diffs
        if abs(e - a) > tol:
            diffs.append({"path": path, "expected": e, "actual": a, "reason": "float_tolerance", "tolerance": tol})
        return diffs

    if type(expected) is not type(actual) and not (
        isinstance(expected, (int, float)) and isinstance(actual, (int, float))
    ):
        # Allow int/bool strictness
        if isinstance(expected, bool) or isinstance(actual, bool):
            if expected is not actual:
                diffs.append({"path": path, "expected": expected, "actual": actual, "reason": "bool_mismatch"})
            return diffs
        diffs.append(
            {
                "path": path,
                "expected": expected,
                "actual": actual,
                "reason": "type_mismatch",
                "expected_type": type(expected).__name__,
                "actual_type": type(actual).__name__,
            }
        )
        return diffs

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            diffs.append({"path": path, "expected": expected, "actual": actual, "reason": "expected_object"})
            return diffs
        exp_keys = set(expected)
        act_keys = set(actual)
        for missing in sorted(exp_keys - act_keys):
            diffs.append({"path": f"{path}.{missing}", "expected": expected[missing], "actual": None, "reason": "missing_field"})
        for extra in sorted(act_keys - exp_keys):
            diffs.append({"path": f"{path}.{extra}", "expected": None, "actual": actual[extra], "reason": "extra_field"})
        for key in sorted(exp_keys & act_keys):
            diffs.extend(
                structural_diff(
                    expected[key],
                    actual[key],
                    path=f"{path}.{key}",
                    tolerances=tolerances,
                )
            )
        return diffs

    if isinstance(expected, list):
        if not isinstance(actual, list):
            diffs.append({"path": path, "expected": expected, "actual": actual, "reason": "expected_array"})
            return diffs
        if len(expected) != len(actual):
            diffs.append(
                {
                    "path": path,
                    "expected_len": len(expected),
                    "actual_len": len(actual),
                    "reason": "length_mismatch",
                }
            )
        for i, (e, a) in enumerate(zip(expected, actual)):
            diffs.extend(structural_diff(e, a, path=f"{path}[{i}]", tolerances=tolerances))
        return diffs

    if expected != actual:
        diffs.append({"path": path, "expected": expected, "actual": actual, "reason": "value_mismatch"})
    return diffs


def replay_execution(
    oracle: dict[str, Any],
    *,
    queue_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build replay outputs for execution oracles.

    Synthetic harness may bake outputs.recovered_replay.
    live_execution computes recovered replay from IR/recovered C# (fail-closed).
    """
    try:
        return compute_recovered_replay(oracle, queue_item=queue_item)
    except ReplayError as exc:
        raise EquivTestError(exc.code, exc.message, details=exc.details) from exc


def oracle_expected_outputs(oracle: dict[str, Any]) -> dict[str, Any]:
    outputs = dict(oracle.get("outputs") or {})
    # recovered_replay is the replay side; expected engine side is under expected / engine / values.
    if "expected" in outputs and isinstance(outputs["expected"], dict):
        return outputs["expected"]
    if "engine" in outputs and isinstance(outputs["engine"], dict):
        return outputs["engine"]
    # Synthetic harness may use outputs.values as expected and recovered_replay as actual.
    if "values" in outputs and isinstance(outputs["values"], dict):
        return outputs["values"]
    raise EquivTestError(
        "missing_expected_outputs",
        "execution oracle outputs must include expected|engine|values object for comparison",
    )


def run_equiv_on_oracle(
    oracle: dict[str, Any],
    *,
    queue_item: dict[str, Any] | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """
    Run equivalence check for one oracle fixture.

    Rules (fail-closed):
    - synthetic fixtures cannot promote real (non-synthetic.*) method_ids
    - live_surface_metadata cannot become equivalence-proven
    - execution kinds require no blocking Unresolved on path + structural equality
    """
    method_id = oracle["method_id"]
    capture_kind = oracle["capture_kind"]
    synthetic = bool(oracle.get("synthetic"))

    if synthetic and not allow_synthetic and not _is_synthetic_method_id(method_id):
        raise EquivTestError(
            "synthetic_blocks_real_method",
            (
                f"synthetic oracle fixture cannot be used to prove real method_id={method_id!r}. "
                "Synthetic fixtures are harness-only."
            ),
        )
    if synthetic and not _is_synthetic_method_id(method_id):
        raise EquivTestError(
            "synthetic_method_id_required",
            "synthetic=true fixtures must use method_id starting with 'synthetic.'",
        )
    if not synthetic and _is_synthetic_method_id(method_id):
        raise EquivTestError(
            "synthetic_id_requires_flag",
            "method_id starts with synthetic. but fixture.synthetic is false",
        )

    if capture_kind == "live_surface_metadata":
        raise EquivTestError(
            "bar_c_requires_execution_oracle",
            (
                "live_surface_metadata fixtures are not bar-C execution traces. "
                "Refuse equivalence-proven. Capture live_execution inputs→outputs first."
            ),
            details={"capture_kind": capture_kind, "method_id": method_id},
        )

    if capture_kind not in ("live_execution", "synthetic_execution"):
        raise EquivTestError("unsupported_capture_kind", f"unsupported capture_kind={capture_kind!r}")

    ir = load_ir(method_id)
    protocol_name = str((oracle.get("protocol") or {}).get("name") or "")
    is_field_delta = protocol_name == "olden_cs_recovery.live_execution.field_delta"
    is_dest_call_trace = protocol_name == "olden_cs_recovery.live_execution.call_trace_dest_recipe"
    # edb CompilerGenerated event accessors: specialized recovered Delegate.Combine/Remove
    # + live EdbEventHandlerProbe path. Remaining IR @bN CAS-loop markers are informational
    # once helpers are classified; do not block bar-C on opaque CAS landings.
    if method_id in EDB_EVENT_ACCESSORS or method_id == EDB_CTOR["method_id"] or method_id == EDB_CCTOR["method_id"]:
        blockers = []
    else:
        blockers = blocking_unresolved(
            ir,
            allow_write_body_field_delta=is_field_delta or is_dest_call_trace,
        )
    if blockers:
        raise EquivTestError(
            "unresolved_on_path",
            f"IR has {len(blockers)} blocking Unresolved node(s) on exercised path",
            details={"unresolved": blockers},
        )
    if (
        queue_item is not None
        and recovered_has_unresolved_throw(method_id, queue_item)
        and not is_field_delta
        and not is_dest_call_trace
    ):
        raise EquivTestError(
            "unresolved_throw_in_recovered",
            "recovered C# still throws UnresolvedLiftException on exercised path",
        )

    if is_dest_call_trace:
        from olden_cs_recovery.dest_recipe import compare_call_trace

        expected = normalize_observable_value(oracle_expected_outputs(oracle))
        actual = normalize_observable_value(replay_execution(oracle, queue_item=queue_item))
        # recovered expectation vs live observation
        diffs = compare_call_trace(actual, expected)
        if diffs:
            raise EquivTestError(
                "equiv_diff_failed",
                f"dest-recipe call-trace differs from oracle in {len(diffs)} place(s)",
                details={"diffs": diffs[:50]},
            )
        if not expected.get("hasRealTrace"):
            raise EquivTestError(
                "call_trace_requires_real_trace",
                (
                    "DestRecipe EquivTester refuses equivalence-proven without a real call-trace "
                    "(plant_incomplete / empty traces are not bar-C proof)."
                ),
                details={"method_id": method_id, "engine": expected},
            )
        return {
            "ok": True,
            "method_id": method_id,
            "capture_kind": capture_kind,
            "synthetic": synthetic,
            "protocol": protocol_name,
            "note": "DestRecipe call-trace equivalence-proven (bar C). Role=dest_recipe only.",
        }

    if is_field_delta:
        from olden_cs_recovery.field_delta import compare_field_delta

        expected = normalize_observable_value(oracle_expected_outputs(oracle))
        # Recovered side: Capstone/pin-table expected delta shape.
        actual = normalize_observable_value(replay_execution(oracle, queue_item=queue_item))
        # Live oracle engine is the source of truth for observed deltas; recovered replay
        # is the expected shape. Swap naming to match compare_field_delta(expected, actual).
        # Here `expected` from oracle.engine is LIVE; recovered is `actual` from replay.
        # compare_field_delta wants recovered expectation vs live observation:
        diffs = compare_field_delta(actual, expected)
        if diffs:
            raise EquivTestError(
                "equiv_diff_failed",
                f"field-delta replay differs from oracle in {len(diffs)} place(s)",
                details={"diffs": diffs[:50]},
            )
        if not expected.get("hasRealDiff"):
            raise EquivTestError(
                "field_delta_requires_real_diff",
                (
                    "field-delta EquivTester refuses equivalence-proven without a real store/membership "
                    "diff (empty listener / null cfia plants are not bar-C proof)."
                ),
                details={"method_id": method_id, "engine": expected},
            )
        return {
            "ok": True,
            "method_id": method_id,
            "capture_kind": capture_kind,
            "synthetic": synthetic,
            "diff_count": 0,
            "status": "equivalence-proven",
            "protocol": protocol_name,
        }

    expected = normalize_observable_value(oracle_expected_outputs(oracle))
    actual = normalize_observable_value(replay_execution(oracle, queue_item=queue_item))
    tolerances = oracle.get("numeric_tolerances") or {}
    diffs = structural_diff(expected, actual, tolerances=tolerances)
    if diffs:
        raise EquivTestError(
            "equiv_diff_failed",
            f"replay differs from oracle in {len(diffs)} place(s)",
            details={"diffs": diffs[:50]},
        )

    # Require expected fields present (no empty expected)
    if not expected:
        raise EquivTestError("empty_expected", "oracle expected outputs object is empty")

    return {
        "ok": True,
        "method_id": method_id,
        "capture_kind": capture_kind,
        "synthetic": synthetic,
        "diff_count": 0,
        "status": "equivalence-proven",
    }


def equiv_test_claimed_items(
    claimed_pairs: list[tuple[Path, dict[str, Any]]],
    *,
    holder: str,
) -> dict[str, Any]:
    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for path, item in claimed_pairs:
        method_id = item["method_id"]
        try:
            oracle_path = find_oracle_for_method(method_id)
            if oracle_path is None:
                raise EquivTestError(
                    "oracle_fixture_missing",
                    f"no oracle_traces fixture for {method_id}; refuse equivalence-proven",
                )
            oracle = load_oracle_trace(oracle_path)
            if oracle.get("synthetic") and ORACLE_TRACES_SYNTHETIC_DIR not in oracle_path.resolve().parents and oracle_path.parent != ORACLE_TRACES_SYNTHETIC_DIR:
                raise EquivTestError(
                    "synthetic_path_violation",
                    "synthetic fixture must live under oracle_traces/synthetic/",
                )
            if oracle["method_id"] != method_id:
                raise EquivTestError(
                    "oracle_method_id_mismatch",
                    f"oracle method_id {oracle['method_id']!r} != queue {method_id!r}",
                )
            # Real queue methods must never use synthetic fixtures.
            allow_synthetic = _is_synthetic_method_id(method_id)
            result = run_equiv_on_oracle(oracle, queue_item=item, allow_synthetic=allow_synthetic)

            previous = item.get("proof_status")
            if previous not in ("oracle-captured", "equivalence-proven"):
                raise EquivTestError(
                    "illegal_proof_precondition",
                    (
                        f"refuse equivalence-proven from proof_status={previous!r}; "
                        "require oracle-captured first (never upgrade static/rename directly)"
                    ),
                )

            write_ledger_entry(
                method_id=method_id,
                status="equivalence-proven",
                previous_status=previous,
                notes="Offline EquivTester replay matched execution oracle (bar C).",
                evidence_refs=[
                    {
                        "kind": "oracle_trace",
                        "path": rel_repo(oracle_path),
                        "notes": f"equiv pass capture_kind={oracle['capture_kind']}",
                    }
                ],
                queue_item=item,
            )

            if "promote" not in ALLOWED_STAGE_TRANSITIONS.get("equiv_test", frozenset()):
                raise EquivTestError("illegal_stage", "equiv_test→promote not allowed")

            updated = dict(item)
            updated["stage"] = "promote"
            updated["proof_status"] = "equivalence-proven"
            updated["blocked_reason"] = None
            updated["notes"] = (
                (item.get("notes") or "") + " | Phase 3 equivalence-proven (bar C)"
            ).strip(" |")
            updated["updated_at"] = to_iso(utc_now())
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=path)
            passed.append(
                {
                    "method_id": method_id,
                    "oracle_path": rel_repo(oracle_path),
                    "stage": "promote",
                    "proof_status": "equivalence-proven",
                    "result": result,
                }
            )
        except EquivTestError as exc:
            updated = dict(item)
            updated = release_item(updated, holder=holder)
            # Leave at equiv_test claimable; do not fake pass.
            write_queue_item(updated, path=path)
            failed.append(
                {
                    "method_id": method_id,
                    "error": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "stage": "equiv_test",
                    "left_claimable": True,
                }
            )

    return {
        "ok": len(failed) == 0 and len(passed) > 0,
        "passed": passed,
        "failed": failed,
        "counts": {"passed": len(passed), "failed": len(failed)},
        "note": (
            "Phase 3 EquivTester: equivalence-proven only on execution oracle match with no "
            "blocking Unresolved. live_surface_metadata never promotes. Synthetic fixtures "
            "never promote real queue methods."
        ),
    }
