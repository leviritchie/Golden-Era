"""Publish Direct State symbol cards from milestone ledger evaluation (fail-closed)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import PACKAGE_ROOT, REPO_ROOT
from olden_cs_recovery.promoter import evaluate_milestone, load_milestone_declaration, publish_milestone_ledger
from olden_cs_recovery.queue_store import to_iso, utc_now
from olden_cs_recovery.schema_validate import validate_instance

CARDS_DIR = PACKAGE_ROOT / "direct_state_cards"
DEFAULT_MILESTONE = PACKAGE_ROOT / "proof_ledger" / "milestones" / "ds_m1_movement_commit.json"

_METHOD_META: dict[str, dict[str, str]] = {
    "Hex.Session.Battle.UnitData::bfdi(Hex)": {
        "role": "commit_owner",
        "mono_alias": "UnitData.set_hex",
        "rva": "0x2078360",
    },
    "Hex.Session.Battle.UnitData::bfdh()": {
        "role": "readback",
        "mono_alias": "UnitData.get_hex",
        "rva": "",
    },
    "edf::bcuo(Hex)": {
        "role": "occupancy_mutator",
        "mono_alias": "FieldObjectData.set_hex",
        "rva": "0x1F055B0",
    },
    "edf::bcun()": {
        "role": "readback",
        "mono_alias": "FieldObjectData.get_hex",
        "rva": "",
    },
    "Hex.Session.Battle.Hex::bcyn(FieldObject)": {
        "role": "occupancy_mutator",
        "mono_alias": "RemoveObject",
        "rva": "0x1F33CB0",
    },
    "Hex.Session.Battle.Hex::bcyl(FieldObject)": {
        "role": "occupancy_mutator",
        "mono_alias": "AddFieldObject",
        "rva": "0x1F33BA0",
    },
    "eep::bdhv(Unit,Hex)": {
        "role": "pre_notify",
        "mono_alias": "leave-hex listener fan-out",
        "rva": "0x1F463F0",
    },
    "eep::bdhw(Unit,Hex)": {
        "role": "post_notify",
        "mono_alias": "enter-hex + publish",
        "rva": "0x1F465D0",
    },
    "eda::bcim(object,BattleEventArgs)": {
        "role": "publish_dispatcher",
        "mono_alias": "BattleLogicEvents invoke",
        "rva": "",
    },
    # M2 dest_recipe
    "ehh::Init(string[])": {
        "role": "dest_recipe",
        "mono_alias": "MechPushUnit.Init",
        "rva": "0x1FD4740",
    },
    "ehh::bdpe(eab,eac,InCastArgs,FieldObject,eaa)": {
        "role": "dest_recipe",
        "mono_alias": "MechPushUnit.ApplyForReceiver",
        "rva": "0x1FD4AC0",
    },
    "Hex.Session.Battle.Hex::bcyf(int,bool b =,ETargetAllegiance c =)": {
        "role": "dest_recipe",
        "mono_alias": "IsLockedForSide",
        "rva": "0x1F334B0",
    },
    "een::bdep(int)": {
        "role": "dest_recipe",
        "mono_alias": "NeighbourByIndex",
        "rva": "0x1F3D1B0",
    },
    "een::bdeo(float,float)": {
        "role": "dest_recipe",
        "mono_alias": "HexAtCoords",
        "rva": "0x1F3D0E0",
    },
    "eeu::bdke(Hex,Hex)": {
        "role": "dest_recipe",
        "mono_alias": "HexDistance",
        "rva": "0x1F772B0",
    },
    # M4 damage side-effect
    "Hex.Session.Battle.UnitData::bfde(int)": {
        "role": "side_effect_store",
        "mono_alias": "UnitData.set_sumHp",
        "rva": "0x20781D0",
    },
    "Hex.Session.Battle.UnitData::bfda()": {
        "role": "readback",
        "mono_alias": "UnitData.allStacks",
        "rva": "0x2078160",
    },
    "Hex.Session.Battle.UnitData::bfdf()": {
        "role": "readback",
        "mono_alias": "UnitData.hasLivingStacks",
        "rva": "0x2078290",
    },
    "Hex.Session.Battle.Hex::bcxo(Unit)": {
        "role": "corpse_store",
        "mono_alias": "Hex.set_lastCorpse",
        "rva": "0x5EA470",
    },
    "Hex.Session.Battle.Hex::bcxn()": {
        "role": "readback",
        "mono_alias": "Hex.get_lastCorpse",
        "rva": "0x5EA440",
    },
    # M5 lifecycle spawn
    "Hex.Session.Battle.Unit::Init(int,eep,eir,Hex,int,int,int,string,bool,bool)": {
        "role": "commit_owner",
        "mono_alias": "Unit.Init",
        "rva": "0x2064CB0",
    },
}


def _rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _method_status_map(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    proven = set(evaluation.get("proven_method_ids") or [])
    incomplete = {row["method_id"]: row for row in evaluation.get("incomplete") or []}
    out: dict[str, dict[str, Any]] = {}
    for mid in evaluation.get("proven_method_ids") or []:
        out[mid] = {"status": "equivalence-proven", "blocked_reason": None}
    for mid, row in incomplete.items():
        status = row.get("queue_proof_status") or row.get("ledger_status") or "blocked"
        if status == "equivalence-proven":
            status = "blocked"
        # Map ledger vocabulary into card enum; unknown → blocked.
        allowed = {
            "equivalence-proven",
            "blocked",
            "oracle-captured",
            "identity-bridged",
            "renamed-accepted",
            "static-lifted",
            "queued",
            "missing",
        }
        if status not in allowed:
            if status is None:
                status = "queued" if row.get("queue_stage") else "missing"
            else:
                status = "blocked"
        out[mid] = {
            "status": status if mid not in proven else "equivalence-proven",
            "blocked_reason": row.get("blocked_reason"),
        }
    return out


def build_card(
    declaration: dict[str, Any],
    evaluation: dict[str, Any],
    *,
    milestone_ledger_path: str | None,
) -> dict[str, Any]:
    status_map = _method_status_map(evaluation)
    live_methods: list[dict[str, Any]] = []
    for mid in declaration["method_ids"]:
        meta = _METHOD_META.get(str(mid), {})
        st = status_map.get(str(mid), {"status": "missing", "blocked_reason": "absent from evaluation"})
        live_methods.append(
            {
                "method_id": str(mid),
                "role": meta.get("role", "commit_owner"),
                "status": st["status"],
                "blocked_reason": st.get("blocked_reason"),
                "mono_alias": meta.get("mono_alias"),
                "rva": meta.get("rva") or None,
            }
        )

    all_ok = all(m["status"] in ("equivalence-proven", "blocked") for m in live_methods)
    all_have_blocked_reason = all(
        m["status"] != "blocked" or (isinstance(m.get("blocked_reason"), str) and m["blocked_reason"].strip())
        for m in live_methods
    )
    proven_ids = [m["method_id"] for m in live_methods if m["status"] == "equivalence-proven"]
    blocked_ids = [m["method_id"] for m in live_methods if m["status"] == "blocked"]
    proof_status = (
        "equivalence-proven"
        if all_ok and all_have_blocked_reason and len(proven_ids) > 0
        else "milestone_incomplete"
    )
    # Plan: promote when every live_methods entry is equivalence-proven OR blocked-with-reason.
    # Require at least one proven surface so a card of only blocks cannot export gameplay symbols.
    banned = declaration.get("banned_surfaces") or []
    publish_field = declaration.get("publish_field") or {}
    card_role = str(declaration.get("role") or "commit_owner")
    card_family = str(declaration.get("family") or "movement")
    is_dest = card_role == "dest_recipe"
    is_damage = card_family == "damage" or "DamageSide" in str(declaration.get("partition_prefix") or "")
    is_lifecycle = card_family == "lifecycle" or "LifecycleSpawn" in str(declaration.get("partition_prefix") or "")

    export_symbols: list[str] = []
    if proof_status == "equivalence-proven":
        for mid in proven_ids:
            meta = _METHOD_META.get(str(mid), {})
            alias = meta.get("mono_alias") or mid
            export_symbols.append(str(alias))

    if is_dest:
        ordered_stores = [
            {
                "offset_or_member": "ehh.cgfy (+0x28)",
                "role": "pushInwards",
                "notes": "Init store; bdpe direction scale −1.0 vs +1.0",
            },
            {
                "offset_or_member": "ehh.cgfz (+0x29)",
                "role": "skipCenter",
                "notes": "Init store; with pushInwards@dist==1 → unitsToRemove",
            },
        ]
        publish = {
            "kind": "none",
            "hub_type": None,
            "field": None,
            "offset": None,
            "english_name": None,
            "english_name_strength": None,
            "call_chain": [],
            "notes": "Dest recipe does not publish; commit publish remains eda.cfia via bfdi/bdhw.",
        }
        adapter_binding = {
            "operations": ["MovementPush"],
            "gateway_methods": [],
            "gameplay_gated": True,
            "notes": (
                "Dest-recipe INPUT only. Do not treat as commit owner. "
                "MovementPush stays gated until M3 focused_live_positive on bfdi path."
            ),
        }
        ungate_requires = [
            "focused_live_positive",
            "call_trace_oracle_bar_c",
            "movement_commit_bfdi_v1",
        ]
        notes = (
            "Bar C fail-closed. Role=dest_recipe only — commit ownership stays on "
            "movement.commit.bfdi_v1. Primary oracle: call-trace (inputs→return/stores/dest shape). "
            "Card promotes when every live_methods entry is equivalence-proven OR blocked-with-reason. "
            + str(declaration.get("notes") or "")
        )
    elif is_damage:
        ordered_stores = list(declaration.get("ordered_stores") or [])
        if not ordered_stores:
            ordered_stores = [
                {
                    "offset_or_member": "UnitData.fullStacks (+0x34)",
                    "role": "stack_count",
                    "notes": "Written by bfde",
                },
                {
                    "offset_or_member": "UnitData.choy (+0x40)",
                    "role": "hp_last_unit",
                    "notes": "Written by bfde; mono hpLastUnit",
                },
                {
                    "offset_or_member": "Hex.cfqf / lastCorpse (+0x30)",
                    "role": "corpse_store",
                    "notes": "Hex.bcxo/bcxn — NOT occupancy",
                },
            ]
        publish = {
            "kind": "none",
            "hub_type": None,
            "field": None,
            "offset": None,
            "english_name": None,
            "english_name_strength": None,
            "call_chain": [],
            "notes": str(
                publish_field.get("notes")
                or "M4 claims no eda/edb publish. DamageScalar is gateway pre-commit ref-int."
            ),
        }
        adapter_binding = {
            "operations": ["DamageApply", "KillConfirm", "CorpseCreate"],
            "gateway_methods": ["TryCommitPreparedDamage"],
            "gameplay_gated": True,
            "notes": (
                "Damage side-effect stores only. Do not treat Hex.bcxo as occupancy. "
                "Do not claim full ApplyDamage recovery. Gameplay flags stay gated until "
                "focused_live_positive for the consuming adapter."
            ),
        }
        ungate_requires = [
            "focused_live_positive",
            "field_delta_oracle_bar_c",
            "damage_scalar_gateway_owned",
        ]
        notes = (
            "Bar C fail-closed. Primary oracle: field-delta on UnitData stack/HP + Hex.lastCorpse. "
            "DamageScalar remains NativeCombatWriteGateway.TryCommitPreparedDamage (pre-commit; "
            "journal restore no-op) — source-replay corroboration only. "
            "Card promotes when every live_methods entry is equivalence-proven OR blocked-with-reason. "
            + str(declaration.get("notes") or "")
        )
    elif is_lifecycle:
        ordered_stores = list(declaration.get("ordered_stores") or [])
        publish = {
            "kind": "none",
            "hub_type": None,
            "field": None,
            "offset": None,
            "english_name": None,
            "english_name_strength": None,
            "call_chain": [],
            "notes": str(
                publish_field.get("notes")
                or "M5 claims no new publish hub. Occupancy enter reuses M1 bcyl."
            ),
        }
        adapter_binding = {
            "operations": ["SummonCreate", "CorpseRaise"],
            "gateway_methods": ["TryInitializeAndInsertObject"],
            "gameplay_gated": True,
            "notes": (
                "Lifecycle spawn Init + occupancy enter only. Reuse movement.commit.bfdi_v1 "
                "for bcyl/bcyn fieldObjects. Collection insert is journaled IList — not invented "
                "native write body. Gameplay gated until focused_live_positive."
            ),
        }
        ungate_requires = [
            "focused_live_positive",
            "field_delta_oracle_bar_c",
            "movement_commit_bfdi_v1",
        ]
        notes = (
            "Bar C fail-closed. Reuse M1 occupancy card for Hex.bcyl. Unit.Init is the spawn "
            "write body (Capstone shows edf.bcuo call). Collection insert stays journaled IList. "
            "Card promotes when every live_methods entry is equivalence-proven OR blocked-with-reason. "
            + str(declaration.get("notes") or "")
        )
    else:
        ordered_stores = [
            {
                "offset_or_member": "edf+0x10",
                "role": "helper_hex",
                "notes": "Stored inside edf.bcuo after leave; read via bcun/ede.bcuh",
            },
            {
                "offset_or_member": "Hex.fieldObjects (+0x28)",
                "role": "list_occupancy",
                "notes": "Mutated by Hex.bcyn (leave) then Hex.bcyl (enter) inside bcuo",
            },
            {
                "offset_or_member": "Hex.cfqg (+0x3A)",
                "role": "occupancy_flag_refresh",
                "notes": "May refresh on AddFieldObject; not the Unit occupant property",
            },
        ]
        publish = {
            "kind": "hub_field",
            "hub_type": publish_field.get("hub_type", "eda"),
            "field": publish_field.get("field", "cfia"),
            "offset": publish_field.get("offset", "+0xC0"),
            "english_name": publish_field.get("english_name", "OnUnitEndedMovement"),
            "english_name_strength": publish_field.get("english_name_strength", "ordinal-inferred"),
            "call_chain": publish_field.get("call_chain")
            or ["eep.bdhw", "eda.bcim", "eda.cfia"],
            "notes": "English name ordinal-inferred; do not treat as OnUnitChangedHex / edb View publish.",
        }
        adapter_binding = {
            "operations": ["MovementPush"],
            "gateway_methods": ["TryCommitUnitHexMove"],
            "gameplay_gated": True,
            "notes": (
                "Keep Homm3DirectStateAdapters.TryMove MovementPush gated until M3 focused_live_positive. "
                "Prefer one journaled UnitData.bfdi invoke over helper+_cfqf dual-write."
            ),
        }
        ungate_requires = [
            "focused_live_positive",
            "field_delta_oracle_bar_c",
            "fieldObjects_and_helper_hex_dual_readback",
        ]
        notes = (
            "Bar C fail-closed. Static lift / pin-table rename / Capstone asm are not equivalence proof. "
            "Primary oracle strategy: field-delta (edf+0x10, fieldObjects membership, eda.cfia invoke observed). "
            "Card promotes when every live_methods entry is equivalence-proven OR blocked-with-reason "
            "(bfdh may stay blocked as readback-optional). "
            + str(declaration.get("notes") or "")
        )

    card = {
        "schema_version": 1,
        "card_id": declaration.get("card_id") or "movement.commit.bfdi_v1",
        "family": card_family,
        "role": card_role,
        "title": declaration.get("title"),
        "live_methods": live_methods,
        "mono_aliases": [m.get("mono_alias") for m in live_methods if m.get("mono_alias")],
        "ordered_stores": ordered_stores,
        "publish": publish,
        "banned_surfaces": banned,
        "proof_status": proof_status,
        "adapter_binding": adapter_binding,
        "ungate_requires": ungate_requires,
        "pin_table_path": declaration.get("pin_table_path"),
        "milestone_id": declaration.get("milestone_id"),
        "milestone_ledger_path": milestone_ledger_path,
        "gamesymbols_export": {
            "exported": False,
            "reason": (
                "Export GameSymbols.DirectStateLaws only after card proof_status=equivalence-proven "
                f"and only for proven surfaces (not blocked). proven={len(proven_ids)} blocked={len(blocked_ids)}."
                if proof_status != "equivalence-proven"
                else (
                    "Card promoted (proven|blocked-with-reason). Export proven surfaces only; "
                    f"blocked readbacks remain non-exported: {blocked_ids}."
                )
            ),
            "symbols": export_symbols if proof_status == "equivalence-proven" else [],
        },
        "updated_at": to_iso(utc_now()),
        "notes": notes,
    }
    validate_instance("direct_state_card.schema.json", card, card["card_id"])
    return card


def publish_card(
    *,
    milestone_path: Path,
    holder: str,
    publish_milestone: bool,
) -> dict[str, Any]:
    declaration = load_milestone_declaration(milestone_path)
    ledger_path: str | None = None
    if publish_milestone:
        published = publish_milestone_ledger(declaration_path=milestone_path, holder=holder)
        ledger_path = published.get("ledger_path")
        evaluation = published["evaluation"]
    else:
        evaluation = evaluate_milestone(declaration)
        ledger_path = _rel_repo(
            PACKAGE_ROOT / "proof_ledger" / "milestones" / f"{declaration['milestone_id']}.ledger.json"
        )

    card = build_card(declaration, evaluation, milestone_ledger_path=ledger_path)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CARDS_DIR / f"{card['card_id'].replace('.', '_')}.json"
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return {
        "ok": True,
        "card_id": card["card_id"],
        "proof_status": card["proof_status"],
        "card_path": _rel_repo(out_path),
        "milestone_status": evaluation.get("status"),
        "equivalence_proven_count": evaluation.get("equivalence_proven_count"),
        "declared_count": evaluation.get("declared_count"),
        "incomplete": evaluation.get("incomplete"),
        "gamesymbols_exported": card["gamesymbols_export"]["exported"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish Direct State symbol card from M1 milestone.")
    parser.add_argument("--milestone", type=Path, default=DEFAULT_MILESTONE)
    parser.add_argument("--holder", type=str, default="agent")
    parser.add_argument(
        "--skip-milestone-ledger",
        action="store_true",
        help="Evaluate only; do not rewrite milestone .ledger.json",
    )
    args = parser.parse_args(argv)
    result = publish_card(
        milestone_path=args.milestone,
        holder=args.holder,
        publish_milestone=not args.skip_milestone_ledger,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
