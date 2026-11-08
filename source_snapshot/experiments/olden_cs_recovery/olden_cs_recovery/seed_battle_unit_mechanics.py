"""Seed Phase 5 Battle unit/mechanics queue partitions from a declared milestone set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from olden_cs_recovery.diffable_cs_scan import DiffableMethod, parse_diffable_cs_file
from olden_cs_recovery.paths import (
    DEFAULT_DIFFABLE_HEX_ROOT,
    DEFAULT_ISIL_HEX_ROOT,
    PACKAGE_ROOT,
    QUEUE_PARTITIONS_DIR,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import empty_claim, to_iso, utc_now, write_queue_item

MILESTONE_PATH = PACKAGE_ROOT / "proof_ledger" / "milestones" / "phase5_battle_unit_mechanics.json"
BATTLE_REL = Path("Hex") / "Session" / "Battle"
NATIVE_DISASM = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "native_disasm_hex_session_battle.json"
)
ADDRESS_MAP = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "address_map_hex_session_battle.json"
)


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


def _partition_for(method: DiffableMethod) -> str:
    short = method.type_name.rsplit(".", 1)[-1]
    return f"Hex.Session.Battle.UnitMechanics/{short}"


def _load_declared_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    ids = data.get("method_ids")
    if not isinstance(ids, list) or not ids:
        raise SystemExit(f"FAIL: milestone {path} missing non-empty method_ids")
    return [str(x) for x in ids]


def _index_battle_methods(diffable_root: Path) -> dict[str, DiffableMethod]:
    battle_dir = diffable_root / BATTLE_REL
    if not battle_dir.is_dir():
        raise SystemExit(f"FAIL: Battle DiffableCs dir missing: {battle_dir}")
    # Only types in the Phase 5 declared set — avoid struct/enum shells that confuse the class scanner.
    allowed = {"Unit.cs", "Hex.cs", "TransferUnit.cs"}
    out: dict[str, DiffableMethod] = {}
    for path in sorted(battle_dir.glob("*.cs")):
        if path.name not in allowed:
            continue
        for method in parse_diffable_cs_file(path):
            if method.method_id in out:
                raise SystemExit(f"FAIL: duplicate DiffableCs method_id {method.method_id}")
            out[method.method_id] = method
    return out


def build_item(
    method: DiffableMethod,
    *,
    diffable_root: Path,
    isil_root: Path,
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
        # Unit/UnitData ISIL dumps are absent from out_dev_isil; CompGen bodies may lift
        # from native_disasm_hex_session_battle.json (fail closed if shape unsupported).
        evidence.append(
            {
                "kind": "isil",
                "path": _rel_repo(isil_root / BATTLE_REL / "MISSING_UNIT_ISIL.txt"),
                "required": False,
                "notes": (
                    "Cpp2IL ISIL companion absent for this type. Phase 5 lifter may synthesize "
                    "CompGen accessor ISIL from native disasm only; otherwise fail closed."
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
            "notes": "native_disasm_hex_session_battle.json — required for Unit CompGen lift when ISIL dump is missing.",
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(MILESTONE_PATH),
            "required": True,
            "notes": "milestone_declaration phase5_battle_unit_mechanics declared subset",
        }
    )
    return {
        "schema_version": 1,
        "method_id": method.method_id,
        "domain": "Hex.Session.Battle.UnitMechanics",
        "partition": _partition_for(method),
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
        "notes": "Seeded by seed_battle_unit_mechanics from Phase 5 declared milestone. Not promoted.",
    }


def seed(*, diffable_root: Path, isil_root: Path, dry_run: bool) -> dict:
    declared = _load_declared_ids(MILESTONE_PATH)
    indexed = _index_battle_methods(diffable_root)
    missing = [mid for mid in declared if mid not in indexed]
    if missing:
        raise SystemExit(
            "FAIL: declared method_ids missing from DiffableCs:\n  " + "\n  ".join(missing)
        )

    items = [
        build_item(indexed[mid], diffable_root=diffable_root, isil_root=isil_root) for mid in declared
    ]
    written = []
    for item in items:
        if dry_run:
            written.append({"method_id": item["method_id"], "partition": item["partition"], "dry_run": True})
            continue
        path = write_queue_item(item)
        written.append({"method_id": item["method_id"], "partition": item["partition"], "path": str(path)})

    return {
        "ok": True,
        "milestone_id": "phase5_battle_unit_mechanics",
        "declared_count": len(declared),
        "queue_items": len(written),
        "dry_run": dry_run,
        "partition_prefix": "Hex.Session.Battle.UnitMechanics",
        "method_ids": declared,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed Phase 5 Battle unit/mechanics declared milestone queue partitions."
    )
    parser.add_argument("--diffable-hex-root", type=Path, default=DEFAULT_DIFFABLE_HEX_ROOT)
    parser.add_argument("--isil-hex-root", type=Path, default=DEFAULT_ISIL_HEX_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = seed(
        diffable_root=args.diffable_hex_root,
        isil_root=args.isil_hex_root,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
