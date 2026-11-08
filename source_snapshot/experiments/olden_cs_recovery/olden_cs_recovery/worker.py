"""Vehicle-agnostic recovery worker CLI.

Usage:
  python -m olden_cs_recovery.worker --role lifter --claim 5 --partition Hex.Session.Battle
"""

from __future__ import annotations

import argparse
import json
import os
import socket
from typing import Any

from olden_cs_recovery.paths import (
    ALLOWED_STAGE_TRANSITIONS,
    ROLE_CLAIM_STAGES,
    ROLES,
    STAGES,
)
from olden_cs_recovery.equiv import equiv_test_claimed_items
from olden_cs_recovery.lifter.run import lift_claimed_items
from olden_cs_recovery.oracle import CAPTURE_KINDS, capture_claimed_items
from olden_cs_recovery.promoter import promote_claimed_items, publish_milestone_ledger
from olden_cs_recovery.queue_store import (
    claim_item,
    iter_queue_items,
    lease_active,
    release_item,
    write_queue_item,
)
from olden_cs_recovery.renamer.run import rename_claimed_items
from olden_cs_recovery.renamer.collisions import audit_rename_collisions
from olden_cs_recovery.renamer.mono_map import load_mono_map


def default_holder() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "agent"
    host = socket.gethostname()
    return f"{user}@{host}"


def filter_claimable(
    items: list[tuple[Any, dict[str, Any]]],
    *,
    role: str,
    holder: str,
    stage_filter: str | None,
) -> list[tuple[Any, dict[str, Any]]]:
    allowed_stages = ROLE_CLAIM_STAGES[role]
    if role == "dumper":
        raise SystemExit(
            "FAIL: role 'dumper' does not claim method queue items. "
            "Use validate_inputs / input_manifest pinning instead."
        )
    out: list[tuple[Any, dict[str, Any]]] = []
    for path, item in items:
        stage = item.get("stage")
        if stage_filter is not None and stage != stage_filter:
            continue
        if stage not in allowed_stages:
            continue
        if lease_active(item) and (item.get("claim") or {}).get("holder") != holder:
            continue
        out.append((path, item))
    return out


def cmd_list(args: argparse.Namespace) -> int:
    items = iter_queue_items(partition_prefix=args.partition)
    rows = []
    for path, item in items:
        claim = item.get("claim") or {}
        rows.append(
            {
                "method_id": item["method_id"],
                "partition": item["partition"],
                "stage": item["stage"],
                "proof_status": item.get("proof_status"),
                "lease_holder": claim.get("holder"),
                "lease_expires_at": claim.get("lease_expires_at"),
                "path": str(path),
            }
        )
    print(json.dumps({"count": len(rows), "items": rows}, indent=2))
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    if args.claim < 0:
        raise SystemExit("FAIL: --claim must be >= 0")

    holder = args.holder or default_holder()

    # Auditor rename-collision pass does not require method leases.
    # --claim 0 still audits unless --list was requested (handled in main).
    if args.role == "auditor":
        audit = audit_rename_collisions(mono_map=load_mono_map())
        result = {
            "ok": bool(audit.get("ok")),
            "role": "auditor",
            "holder": holder,
            "claimed_count": 0,
            "claimed": [],
            "auditor": audit,
            "note": (
                "Auditor rename-collision pass over rename_map index/entries + Mono "
                "rejectedSimpleNameCollisions. No queue leases claimed."
            ),
        }
        print(json.dumps(result, indent=2))
        return 0 if audit.get("ok") else 1

    if args.claim == 0:
        return cmd_list(args)

    items = iter_queue_items(partition_prefix=args.partition)
    if not items:
        raise SystemExit(
            f"FAIL: no queue items for partition prefix {args.partition!r}. "
            "Run: python -m olden_cs_recovery.seed_battle_partition"
        )

    claimable = filter_claimable(items, role=args.role, holder=holder, stage_filter=args.stage)
    if args.role == "oracle_capturer" and (args.capture_kind or "live_execution") == "live_execution":
        # Prefer proven live_execution surfaces: base-only parameterless, then bool field-assign.
        from olden_cs_recovery.replay import (
            is_base_only_parameterless_ctor,
            is_base_then_bool_field_assign_ctor,
            is_base_then_param_field_assign_ctor,
            is_nested_null_guarded_field_copy_ctor,
            load_ir,
        )

        def _live_exec_key(pair: tuple[Any, dict[str, Any]]) -> tuple[int, str]:
            item = pair[1]
            mid = item["method_id"]
            ir = load_ir(mid)
            if mid.endswith("::.ctor()") and is_base_only_parameterless_ctor(ir):
                preferred = 0
            elif is_base_then_bool_field_assign_ctor(ir):
                preferred = 1
            elif is_base_then_param_field_assign_ctor(ir):
                preferred = 2
            elif is_nested_null_guarded_field_copy_ctor(ir):
                preferred = 3
            else:
                preferred = 4
            return (preferred, mid)

        claimable = sorted(claimable, key=_live_exec_key)
    elif args.role == "equiv_tester":
        from olden_cs_recovery.oracle import find_oracle_for_method, load_oracle_trace

        def _equiv_key(pair: tuple[Any, dict[str, Any]]) -> tuple[int, str]:
            mid = pair[1]["method_id"]
            path = find_oracle_for_method(mid)
            if path is None:
                return (2, mid)
            try:
                kind = load_oracle_trace(path).get("capture_kind")
            except Exception:
                return (2, mid)
            preferred = 0 if kind in ("live_execution", "synthetic_execution") else 1
            return (preferred, mid)

        claimable = sorted(claimable, key=_equiv_key)

    if not claimable:
        raise SystemExit(
            f"FAIL: no claimable items for role={args.role!r} partition={args.partition!r} "
            f"stage_filter={args.stage!r}. "
            "Either leases are held, stages do not match the role, or the queue is empty for that filter."
        )

    claimed_pairs: list[tuple[Any, dict[str, Any]]] = []
    claimed: list[dict[str, Any]] = []
    for path, item in claimable[: args.claim]:
        updated = claim_item(item, holder=holder, role=args.role, lease_minutes=args.lease_minutes)
        write_queue_item(updated, path=path)
        claimed_pairs.append((path, updated))
        claimed.append(
            {
                "method_id": updated["method_id"],
                "stage": updated["stage"],
                "partition": updated["partition"],
                "lease_expires_at": updated["claim"]["lease_expires_at"],
                "path": str(path),
            }
        )

    result: dict[str, Any] = {
        "ok": True,
        "role": args.role,
        "holder": holder,
        "claimed_count": len(claimed),
        "claimed": claimed,
    }

    if args.role == "lifter":
        # Recommended order: claim Hex.Session.Battle (EventArgs) before edb.
        # Mixed batches still prefer EventArgs via lifter sort key.
        lift_result = lift_claimed_items(claimed_pairs, holder=holder)
        result["lift"] = lift_result
        result["note"] = (
            "Phase 1 lifter: IR + C# skeletons emitted; compile-check is a gate, never promotion. "
            "Successful methods advance lift→rename with proof_status=static-lifted."
        )
        if not lift_result.get("ok"):
            print(json.dumps(result, indent=2))
            return 1
    elif args.role == "renamer":
        rename_result = rename_claimed_items(claimed_pairs, holder=holder)
        result["rename"] = rename_result
        result["note"] = (
            "Phase 2 rename oracle: Mono strong-static + second evidence → renamed-accepted "
            "(stage rename→oracle_capture). probable-static/weaker → renamed-proposed (stay rename). "
            "Missing map → skipped empty proposal. Does not run oracle capture or EquivTester."
        )
        if not rename_result.get("ok"):
            print(json.dumps(result, indent=2))
            return 1
    elif args.role == "oracle_capturer":
        capture_kind = args.capture_kind or "live_execution"
        capture_result = capture_claimed_items(
            claimed_pairs, holder=holder, capture_kind=capture_kind
        )
        result["oracle_capture"] = capture_result
        result["note"] = (
            f"Oracle capturer ({capture_kind}): requires fresh live Golden Era bridge. "
            "live_execution uses construct_instance_snapshot (parameterless base-only EventArgs first). "
            "Bridge unavailable / unsupported method → fail closed, leases released. "
            "Never sets equivalence-proven."
        )
        if not capture_result.get("ok"):
            print(json.dumps(result, indent=2))
            return 1
    elif args.role == "equiv_tester":
        equiv_result = equiv_test_claimed_items(claimed_pairs, holder=holder)
        result["equiv_test"] = equiv_result
        result["note"] = (
            "Phase 3 EquivTester: offline replay vs oracle_traces. "
            "equivalence-proven only for execution oracles with no blocking Unresolved. "
            "live_surface_metadata and missing fixtures fail closed. "
            "Synthetic fixtures never promote real queue methods."
        )
        if not equiv_result.get("ok"):
            print(json.dumps(result, indent=2))
            return 1
    elif args.role == "promoter":
        promote_result = promote_claimed_items(claimed_pairs, holder=holder)
        milestone = publish_milestone_ledger(holder=holder)
        result["promote"] = promote_result
        result["milestone"] = milestone
        result["note"] = (
            "Phase 4 promoter: publishes only equivalence-proven methods, then evaluates the "
            "declared milestone set. domain_promoted only if every declared method is proven; "
            "otherwise milestone_incomplete with blocked reasons."
        )
        if not promote_result.get("ok") and claimed_pairs:
            print(json.dumps(result, indent=2))
            return 1
        if not milestone.get("complete"):
            # Honest incomplete milestone is a successful publish, but non-zero exit signals gaps.
            print(json.dumps(result, indent=2))
            return 2
    else:
        result["note"] = (
            "Claim/lease only for this role. "
            "Use --release or --set-stage for explicit lease/stage maintenance."
        )

    print(json.dumps(result, indent=2))
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    holder = args.holder or default_holder()
    items = iter_queue_items(partition_prefix=args.partition)
    released = []
    for path, item in items:
        claim = item.get("claim") or {}
        if claim.get("holder") != holder:
            continue
        if args.method_id and item["method_id"] != args.method_id:
            continue
        updated = release_item(item, holder=holder)
        write_queue_item(updated, path=path)
        released.append(item["method_id"])
        if args.method_id:
            break
    if args.method_id and not released:
        raise SystemExit(f"FAIL: no releasable lease for method_id={args.method_id!r} holder={holder!r}")
    print(json.dumps({"ok": True, "holder": holder, "released": released}, indent=2))
    return 0


def cmd_set_stage(args: argparse.Namespace) -> int:
    if args.set_stage not in STAGES:
        raise SystemExit(f"FAIL: invalid stage {args.set_stage!r}")
    holder = args.holder or default_holder()
    matches = [
        (path, item)
        for path, item in iter_queue_items(partition_prefix=args.partition)
        if item["method_id"] == args.method_id
    ]
    if not matches:
        raise SystemExit(f"FAIL: method_id not found under partition prefix {args.partition!r}: {args.method_id}")
    if len(matches) != 1:
        raise SystemExit(f"FAIL: method_id ambiguous ({len(matches)} files): {args.method_id}")
    path, item = matches[0]
    claim = item.get("claim") or {}
    if claim.get("holder") != holder or not lease_active(item):
        raise SystemExit(
            f"FAIL: --set-stage requires an active lease held by {holder!r} on {args.method_id}"
        )
    current = item["stage"]
    allowed = ALLOWED_STAGE_TRANSITIONS.get(current, frozenset())
    if args.set_stage != current and args.set_stage not in allowed:
        raise SystemExit(
            f"FAIL: illegal stage transition {current!r} -> {args.set_stage!r}. "
            f"Allowed from {current!r}: {sorted(allowed) or '(none)'}"
        )
    updated = dict(item)
    updated["stage"] = args.set_stage
    if args.set_stage == "blocked":
        if not args.blocked_reason:
            raise SystemExit("FAIL: stage=blocked requires --blocked-reason")
        updated["blocked_reason"] = args.blocked_reason
        updated["proof_status"] = "blocked"
    write_queue_item(updated, path=path)
    print(
        json.dumps(
            {
                "ok": True,
                "method_id": args.method_id,
                "from_stage": current,
                "to_stage": args.set_stage,
                "path": str(path),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m olden_cs_recovery.worker",
        description="Claim-lease worker for Olden Era C# recovery queues (vehicle-agnostic).",
    )
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--claim", type=int, required=True, help="Number of items to claim; 0 lists matching items.")
    parser.add_argument(
        "--partition",
        required=True,
        help="Partition prefix filter (e.g. Hex.Session.Battle or edb).",
    )
    parser.add_argument("--holder", default=None, help="Lease holder id (default: user@host).")
    parser.add_argument("--lease-minutes", type=int, default=60)
    parser.add_argument("--stage", default=None, choices=STAGES, help="Optional exact stage filter when claiming.")
    parser.add_argument("--list", action="store_true", help="List items only (same as --claim 0).")
    parser.add_argument("--release", action="store_true", help="Release leases held by --holder.")
    parser.add_argument("--method-id", default=None, help="Target a single method_id for --release/--set-stage.")
    parser.add_argument("--set-stage", default=None, choices=STAGES, help="Explicit stage transition for a leased item.")
    parser.add_argument("--blocked-reason", default=None)
    parser.add_argument(
        "--capture-kind",
        default=None,
        choices=CAPTURE_KINDS,
        help="oracle_capturer only: live_execution (default) or live_surface_metadata.",
    )
    parser.add_argument(
        "--publish-milestone-only",
        action="store_true",
        help="promoter only: evaluate/publish milestone ledger without claiming queue items.",
    )
    parser.add_argument(
        "--milestone",
        default=None,
        help="promoter: path to milestone declaration JSON (default: phase5_city_ui_binders).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        args.claim = 0
        return cmd_list(args)

    if args.release:
        return cmd_release(args)
    if args.set_stage:
        if not args.method_id:
            raise SystemExit("FAIL: --set-stage requires --method-id")
        return cmd_set_stage(args)

    if args.role == "promoter" and args.publish_milestone_only:
        from pathlib import Path

        from olden_cs_recovery.promoter import DEFAULT_MILESTONE_PATH

        holder = args.holder or default_holder()
        milestone_path = Path(args.milestone) if args.milestone else DEFAULT_MILESTONE_PATH
        milestone = publish_milestone_ledger(declaration_path=milestone_path, holder=holder)
        result = {
            "ok": True,
            "role": "promoter",
            "holder": holder,
            "claimed_count": 0,
            "milestone": milestone,
            "note": (
                "Published milestone ledger only. domain_promoted iff declared set is fully "
                "equivalence-proven; otherwise milestone_incomplete."
            ),
        }
        print(json.dumps(result, indent=2))
        return 0 if milestone.get("complete") else 2

    return cmd_claim(args)


if __name__ == "__main__":
    raise SystemExit(main())
