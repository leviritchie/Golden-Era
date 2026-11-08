"""Seed Direct State write-body queue partitions from a declared DS milestone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from olden_cs_recovery.diffable_cs_scan import DiffableMethod, parse_diffable_cs_file
from olden_cs_recovery.paths import (
    DEFAULT_DIFFABLE_HEX_ROOT,
    DEFAULT_ISIL_HEX_ROOT,
    PACKAGE_ROOT,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import empty_claim, to_iso, utc_now, write_queue_item

MILESTONE_PATH = PACKAGE_ROOT / "proof_ledger" / "milestones" / "ds_m1_movement_commit.json"
PIN_TABLE = REPO_ROOT / "experiments" / "direct_state_movement_trace" / "mono_live_pin_table.md"
ASM_DIR = REPO_ROOT / "experiments" / "direct_state_movement_trace"
ADDRESS_MAP = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "address_map_hex_session_battle.json"
)
NATIVE_DISASM = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "native_disasm_hex_session_battle.json"
)

# Live GE type → DiffableCs path under DiffableCs/Hex/
_TYPE_FILES: dict[str, Path] = {
    "Hex.Session.Battle.UnitData": Path("Hex") / "Session" / "Battle" / "UnitData.cs",
    "Hex.Session.Battle.Hex": Path("Hex") / "Session" / "Battle" / "Hex.cs",
    "Hex.Session.Battle.Unit": Path("Hex") / "Session" / "Battle" / "Unit.cs",
    "edf": Path("edf.cs"),
    "eep": Path("eep.cs"),
    "eda": Path("eda.cs"),
    "ehh": Path("ehh.cs"),
    "een": Path("een.cs"),
    "eeu": Path("eeu.cs"),
}

_ASM_BY_METHOD: dict[str, str] = {
    "Hex.Session.Battle.UnitData::bfdi(Hex)": "UnitData_bfdi.asm.txt",
    "Hex.Session.Battle.UnitData::bfde(int)": "UnitData_bfde.asm.txt",
    "Hex.Session.Battle.UnitData::bfda()": "UnitData_bfda.asm.txt",
    "Hex.Session.Battle.UnitData::bfdf()": "UnitData_bfdf.asm.txt",
    "edf::bcuo(Hex)": "edf_bcuo.asm.txt",
    "Hex.Session.Battle.Hex::bcyl(FieldObject)": "Hex_bcyl.asm.txt",
    "Hex.Session.Battle.Hex::bcyn(FieldObject)": "Hex_bcyn.asm.txt",
    "Hex.Session.Battle.Hex::bcxo(Unit)": "Hex_bcxo.asm.txt",
    "eep::bdhv(Unit,Hex)": "eep_bdhv.asm.txt",
    "eep::bdhw(Unit,Hex)": "eep_bdhw.asm.txt",
    "eda::bcim(object,BattleEventArgs)": "eda_bcim.asm.txt",
    "ehh::Init(string[])": "ehh_Init.asm.txt",
    "ehh::bdpe(eab,eac,InCastArgs,FieldObject,eaa)": "ehh_bdpe.asm.txt",
    "Hex.Session.Battle.Hex::bcyf(int,bool b =,ETargetAllegiance c =)": "Hex_bcyf.asm.txt",
    "Hex.Session.Battle.Unit::Init(int,eep,eir,Hex,int,int,int,string,bool,bool)": "Unit_Init.asm.txt",
}


def _rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _isil_path_for(diffable_path: Path, diffable_root: Path, isil_root: Path) -> Path | None:
    try:
        rel = diffable_path.resolve().relative_to(diffable_root.resolve())
    except ValueError:
        return None
    candidate = isil_root / rel.with_suffix(".txt")
    return candidate if candidate.is_file() else None


def _partition_for(method: DiffableMethod, *, partition_prefix: str) -> str:
    short = method.type_name.rsplit(".", 1)[-1]
    return f"{partition_prefix}/{short}"


def _load_milestone(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    ids = data.get("method_ids")
    if not isinstance(ids, list) or not ids:
        raise SystemExit(f"FAIL: milestone {path} missing non-empty method_ids")
    prefix = data.get("partition_prefix")
    if not isinstance(prefix, str) or not prefix.strip():
        raise SystemExit(f"FAIL: milestone {path} missing partition_prefix")
    return data


def _load_declared_ids(path: Path) -> list[str]:
    return [str(x) for x in _load_milestone(path)["method_ids"]]


def _index_declared_methods(diffable_root: Path, declared: list[str]) -> dict[str, DiffableMethod]:
    needed_types = {mid.split("::", 1)[0] for mid in declared}
    out: dict[str, DiffableMethod] = {}
    for type_name in sorted(needed_types):
        rel = _TYPE_FILES.get(type_name)
        if rel is None:
            raise SystemExit(f"FAIL: no DiffableCs path mapping for type {type_name!r}")
        path = diffable_root / rel
        if not path.is_file():
            raise SystemExit(f"FAIL: DiffableCs missing for {type_name}: {path}")
        for method in parse_diffable_cs_file(path):
            if method.method_id in declared:
                if method.method_id in out:
                    raise SystemExit(f"FAIL: duplicate DiffableCs method_id {method.method_id}")
                out[method.method_id] = method
    return out


def build_item(
    method: DiffableMethod,
    *,
    diffable_root: Path,
    isil_root: Path,
    milestone_path: Path,
    partition_prefix: str,
    domain: str,
) -> dict:
    now = to_iso(utc_now())
    evidence = [
        {
            "kind": "diffable_cs",
            "path": _rel_repo(method.source_path),
            "required": True,
            "notes": f"source_line={method.source_line}",
        }
    ]
    isil = _isil_path_for(method.source_path, diffable_root, isil_root)
    if isil is not None:
        evidence.append({"kind": "isil", "path": _rel_repo(isil), "required": True})
    else:
        evidence.append(
            {
                "kind": "isil",
                "path": _rel_repo(isil_root / "MISSING_WRITE_BODY_ISIL.txt"),
                "required": False,
                "notes": (
                    "Cpp2IL ISIL companion absent for this type. Write-body lift may use "
                    "experiments/direct_state_movement_trace Capstone asm + native_disasm; "
                    "otherwise fail closed with Unresolved (do not invent CF)."
                ),
            }
        )
    evidence.append(
        {
            "kind": "address_map",
            "path": _rel_repo(ADDRESS_MAP),
            "required": ADDRESS_MAP.is_file(),
            "notes": "Battle session method-pointer map when present.",
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(NATIVE_DISASM),
            "required": NATIVE_DISASM.is_file(),
            "notes": "native_disasm_hex_session_battle.json",
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(PIN_TABLE),
            "required": True,
            "notes": "mono_live_pin_table — mandatory second evidence for DirectState rename; Auditor rejects bcxo↔occupancy.",
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(milestone_path),
            "required": True,
            "notes": f"milestone_declaration {milestone_path.name} declared subset",
        }
    )
    asm_name = _ASM_BY_METHOD.get(method.method_id)
    if asm_name:
        asm_path = ASM_DIR / asm_name
        evidence.append(
            {
                "kind": "other",
                "path": _rel_repo(asm_path),
                "required": asm_path.is_file(),
                "notes": "Capstone write-body disasm from direct_state_movement_trace",
            }
        )
    oracle_note = (
        "call-trace live_execution oracle (dest recipe; not commit ownership)"
        if "DestRecipe" in partition_prefix
        else (
            "field-delta live_execution oracle (damage side-effect stores; "
            "DamageScalar gateway is secondary journal corroboration only)"
            if "DamageSide" in partition_prefix
            else "field-delta live_execution oracle"
        )
    )
    return {
        "schema_version": 1,
        "method_id": method.method_id,
        "domain": domain,
        "partition": _partition_for(method, partition_prefix=partition_prefix),
        "stage": "lift",
        "type_name": method.type_name,
        "method_name": method.method_name,
        "signature": method.signature,
        "evidence_refs": evidence,
        "proof_status": None,
        "claim": empty_claim(),
        "blocked_reason": None,
        "source_line": method.source_line,
        "updated_at": now,
        "notes": (
            f"Seeded by seed_direct_state_write_body from {milestone_path.name}. "
            f"Bar C requires {oracle_note}. Not promoted. "
            "Overnight-safe: lift/rename/equiv_test(with pre-captured traces). "
            "Live/daytime: oracle_capture + card promote. Gameplay ungating is M3+."
        ),
    }


def seed(*, diffable_root: Path, isil_root: Path, dry_run: bool, milestone_path: Path) -> dict:
    milestone = _load_milestone(milestone_path)
    declared = [str(x) for x in milestone["method_ids"]]
    partition_prefix = str(milestone["partition_prefix"]).strip()
    domain = str(milestone.get("domain") or partition_prefix)
    indexed = _index_declared_methods(diffable_root, declared)
    missing = [mid for mid in declared if mid not in indexed]
    if missing:
        raise SystemExit(
            "FAIL: declared method_ids missing from DiffableCs:\n  " + "\n  ".join(missing)
        )

    items = [
        build_item(
            indexed[mid],
            diffable_root=diffable_root,
            isil_root=isil_root,
            milestone_path=milestone_path,
            partition_prefix=partition_prefix,
            domain=domain,
        )
        for mid in declared
    ]
    written = []
    for item in items:
        if dry_run:
            written.append(
                {"method_id": item["method_id"], "partition": item["partition"], "dry_run": True}
            )
            continue
        path = write_queue_item(item)
        written.append(
            {"method_id": item["method_id"], "partition": item["partition"], "path": str(path)}
        )

    return {
        "ok": True,
        "milestone_id": milestone.get("milestone_id"),
        "card_id": milestone.get("card_id"),
        "declared_count": len(declared),
        "queue_items": len(written),
        "dry_run": dry_run,
        "partition_prefix": partition_prefix,
        "method_ids": declared,
        "overnight_safe_stages": ["lift", "rename", "equiv_test_with_precaptured_traces"],
        "live_required_stages": ["oracle_capture", "promote_card_to_equivalence_proven"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed Direct State write-body / dest-recipe queue partitions from a DS milestone."
    )
    parser.add_argument("--diffable-hex-root", type=Path, default=DEFAULT_DIFFABLE_HEX_ROOT)
    parser.add_argument("--isil-hex-root", type=Path, default=DEFAULT_ISIL_HEX_ROOT)
    parser.add_argument(
        "--milestone",
        type=Path,
        default=MILESTONE_PATH,
        help="Milestone declaration JSON (default: ds_m1_movement_commit).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = seed(
        diffable_root=args.diffable_hex_root,
        isil_root=args.isil_hex_root,
        dry_run=args.dry_run,
        milestone_path=args.milestone,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
