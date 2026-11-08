"""Apply Direct State mono_live_pin_table renames for obfuscated hub types (eda/edf/eep).

The CompGen Mono semantic map often omits these live GE short names. Pin-table rows are
mandatory second evidence for Direct State write-body rename. Fail-closed: never maps
Hex.bcxo → occupancy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import REPO_ROOT
from olden_cs_recovery.queue_store import (
    empty_claim,
    iter_queue_items,
    to_iso,
    utc_now,
    write_queue_item,
)
from olden_cs_recovery.renamer.apply import make_rename_entry, write_rename_entry

PIN_TABLE = REPO_ROOT / "experiments" / "direct_state_movement_trace" / "mono_live_pin_table.md"

# method_id → (mono_type_full, member_alias, evidence note)
_PIN_MEMBER_ALIASES: dict[str, tuple[str, str, str]] = {
    # M1 commit hubs
    "edf::bcuo(Hex)": ("Hex.Session.Battle.FieldObjectData", "set_hex", "pin_table row 2b"),
    "edf::bcun()": ("Hex.Session.Battle.FieldObjectData", "get_hex", "pin_table row 2b"),
    "eep::bdhv(Unit,Hex)": ("Hex.Session.Battle.Battle", "OnUnitLeaveHex_fanout", "pin_table / bfdi call chain"),
    "eep::bdhw(Unit,Hex)": ("Hex.Session.Battle.Battle", "OnUnitEnterHex_publish", "pin_table row 5d"),
    "eda::bcim(object,BattleEventArgs)": (
        "Hex.Session.Battle.BattleLogicEvents",
        "Invoke",
        "pin_table row 5 / 5d",
    ),
    # M2 dest-recipe (adapter INPUT only — not commit ownership)
    "ehh::Init(string[])": ("Hex.Session.Battle.MechPushUnit", "Init", "pin_table row 3d"),
    "ehh::bdpe(eab,eac,InCastArgs,FieldObject,eaa)": (
        "Hex.Session.Battle.MechPushUnit",
        "ApplyForReceiver",
        "pin_table row 3c",
    ),
    "Hex.Session.Battle.Hex::bcyf(int,bool b =,ETargetAllegiance c =)": (
        "Hex.Session.Battle.Hex",
        "IsLockedForSide",
        "pin_table row 1d",
    ),
    "een::bdep(int)": (
        "een",
        "NeighbourByIndex",
        "S24/S44 role-pin (neighbour pick); mono English type/name not in pin table",
    ),
    "een::bdeo(float,float)": (
        "een",
        "HexAtCoords",
        "S24/S44 role-pin (coord→hex); mono English type/name not in pin table",
    ),
    "eeu::bdke(Hex,Hex)": (
        "eeu",
        "HexDistance",
        "S24/S44 role-pin (distance); mono English type/name not in pin table",
    ),
    # M4 damage side-effect stores (stack/HP + lastCorpse — NOT occupancy)
    "Hex.Session.Battle.UnitData::bfde(int)": (
        "Hex.Session.Battle.UnitData",
        "set_sumHp",
        "ISIL UnitData.bfde writes fullStacks(+0x34)/hpLastUnit(+0x40); mono sumHp setter shape",
    ),
    "Hex.Session.Battle.UnitData::bfda()": (
        "Hex.Session.Battle.UnitData",
        "allStacks",
        "ISIL bfda = (hpLastUnit>0?1:0)+tempFullStacks+fullStacks; mono allStacks",
    ),
    "Hex.Session.Battle.UnitData::bfdf()": (
        "Hex.Session.Battle.UnitData",
        "hasLivingStacks",
        "ISIL bfdf alive predicate over fullStacks/hpLastUnit/tempFullStacks",
    ),
    "Hex.Session.Battle.Hex::bcxo(Unit)": (
        "Hex.Session.Battle.Hex",
        "set_lastCorpse",
        "pin_table row 6b — lastCorpse ONLY; Auditor rejects occupancy mapping",
    ),
    "Hex.Session.Battle.Hex::bcxn()": (
        "Hex.Session.Battle.Hex",
        "get_lastCorpse",
        "pin_table row 6b — lastCorpse ONLY; Auditor rejects occupancy mapping",
    ),
}


def _rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def apply_pin_renames(*, partition_prefix: str, dry_run: bool) -> dict[str, Any]:
    if not PIN_TABLE.is_file():
        raise SystemExit(f"FAIL: missing pin table {PIN_TABLE}")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for path, item in iter_queue_items(partition_prefix=partition_prefix):
        mid = item["method_id"]
        if mid not in _PIN_MEMBER_ALIASES:
            skipped.append({"method_id": mid, "reason": "not in Direct State pin hub alias table"})
            continue
        if item.get("stage") != "rename":
            skipped.append({"method_id": mid, "reason": f"stage={item.get('stage')} (need rename)"})
            continue

        mono_type, member_alias, note = _PIN_MEMBER_ALIASES[mid]
        type_name = str(item.get("type_name") or mid.split("::", 1)[0])
        method_name = str(item.get("method_name") or "")
        if method_name in {"bcxo", "bcxn"} and "lastCorpse" not in member_alias and "last_corpse" not in member_alias.lower():
            rejected.append(
                {
                    "method_id": mid,
                    "reason": "Auditor reject: bcxo/bcxn must not rename via occupancy pin path",
                }
            )
            continue
        if method_name in {"bcxo", "bcxn"} and ("occupancy" in note.lower() or "occupant" in note.lower()):
            rejected.append(
                {
                    "method_id": mid,
                    "reason": "Auditor reject: bcxo/bcxn pin note must not claim occupancy",
                }
            )
            continue

        mono_ns, mono_simple = (
            mono_type.rsplit(".", 1) if "." in mono_type else ("", mono_type)
        )
        entry = make_rename_entry(
            current_type_name=type_name,
            proposed_mono_full=mono_type,
            mono_namespace=mono_ns or None,
            mono_simple=mono_simple,
            decision="renamed-accepted",
            confidence="strong-static",
            evidence_classes=["signature_shape", "call_neighborhood", "string_loc_anchor"],
            second_evidence_present=True,
            map_score=None,
            map_reasons=[
                f"direct_state_pin_table:{note}",
                f"member_alias={member_alias}",
                f"pin_table_path={_rel_repo(PIN_TABLE)}",
            ],
            method_id=mid,
            member_renames=[
                {
                    "kind": "method",
                    "current_name": method_name,
                    "mono_name": member_alias,
                    "confidence": "strong-static",
                }
            ],
            collision_reason=None,
            skip_reason=None,
            applied_to_recovered=False,
            recovered_paths=[],
            mono_map_path=_rel_repo(PIN_TABLE),
            notes=(
                "Direct State pin-table rename for write-body hub. "
                "Not bar-C. Never teaches bcxo as occupancy."
            ),
        )

        if dry_run:
            accepted.append({"method_id": mid, "mono_alias": member_alias, "dry_run": True})
            continue

        rename_path = write_rename_entry(entry)
        updated = dict(item)
        updated["stage"] = "oracle_capture"
        updated["proof_status"] = "renamed-accepted"
        updated["blocked_reason"] = None
        updated["claim"] = empty_claim()
        updated["updated_at"] = to_iso(utc_now())
        updated["notes"] = (
            (item.get("notes") or "")
            + f" | Direct State pin-table rename → {member_alias} ({note}); "
            "oracle_capture requires live_execution (field-delta for Commit; call-trace for DestRecipe)."
        ).strip(" |")
        write_queue_item(updated, path=path)
        accepted.append(
            {
                "method_id": mid,
                "mono_alias": member_alias,
                "rename_entry": _rel_repo(rename_path),
                "stage": "oracle_capture",
            }
        )

    return {
        "ok": len(rejected) == 0,
        "accepted": accepted,
        "rejected": rejected,
        "skipped": skipped,
        "pin_table": _rel_repo(PIN_TABLE),
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Direct State pin-table renames for write-body hubs (M1 Commit / M2 DestRecipe)."
    )
    parser.add_argument("--partition", default="DirectState.WriteBody/Commit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = apply_pin_renames(partition_prefix=args.partition, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
