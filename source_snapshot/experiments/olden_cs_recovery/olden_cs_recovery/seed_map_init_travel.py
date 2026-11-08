"""Seed Phase 5 Map init/travel queue partitions from a declared milestone set."""

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

MILESTONE_PATH = PACKAGE_ROOT / "proof_ledger" / "milestones" / "phase5_map_init_travel.json"
DOMAIN = "Hex.Map.InitTravel"
PARTITION_PREFIX = "Hex.Map.InitTravel"

MAP_REL = Path("Hex") / "Map"

SAMPLES = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
)

ADDRESS_MAP = SAMPLES / "address_map_hex_map.json"
NATIVE_DISASM = SAMPLES / "native_disasm_hex_map.json"

DIFFABLE_FILES = {
    "Hex.Map.Map": MAP_REL / "Map.cs",
    "Hex.Map.MapData": MAP_REL / "MapData.cs",
    "Hex.Map.MapObjects": MAP_REL / "MapObjects.cs",
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


def _partition_for(method: DiffableMethod) -> str:
    short = method.type_name.rsplit(".", 1)[-1]
    return f"{PARTITION_PREFIX}/{short}"


def _load_declared_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    ids = data.get("method_ids")
    if not isinstance(ids, list) or not ids:
        raise SystemExit(f"FAIL: milestone {path} missing non-empty method_ids")
    return [str(x) for x in ids]


def _index_map_methods(diffable_root: Path) -> dict[str, DiffableMethod]:
    out: dict[str, DiffableMethod] = {}
    for type_name, rel in DIFFABLE_FILES.items():
        path = diffable_root / rel
        if not path.is_file():
            raise SystemExit(f"FAIL: DiffableCs missing for {type_name}: {path}")
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
        evidence.append(
            {
                "kind": "isil",
                "path": _rel_repo(isil_root / MAP_REL / "MISSING_MAP_ISIL.txt"),
                "required": False,
                "notes": (
                    "Cpp2IL ISIL companion absent. Phase 5 lifter may synthesize CompGen "
                    "accessor ISIL from native_disasm_hex_map only; otherwise fail closed."
                ),
            }
        )

    evidence.append(
        {
            "kind": "address_map",
            "path": _rel_repo(ADDRESS_MAP),
            "required": ADDRESS_MAP.is_file(),
            "notes": (
                "DummyDLL method-pointer map for Hex.Map. Many CompGen getters are omitted; "
                "lifter/identity fall back to native_disasm_hex_map VA when present."
            ),
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(NATIVE_DISASM),
            "required": NATIVE_DISASM.is_file(),
            "notes": "native_disasm_hex_map.json — CompGen VA + ISIL synthesize for Map init/travel.",
        }
    )
    evidence.append(
        {
            "kind": "other",
            "path": _rel_repo(MILESTONE_PATH),
            "required": True,
            "notes": "milestone_declaration phase5_map_init_travel declared subset",
        }
    )
    return {
        "schema_version": 1,
        "method_id": method.method_id,
        "domain": DOMAIN,
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
        "notes": (
            "Seeded by seed_map_init_travel from Phase 5 Map init/travel declared milestone. "
            "Not promoted."
        ),
    }


def seed(*, diffable_root: Path, isil_root: Path, dry_run: bool) -> dict:
    declared = _load_declared_ids(MILESTONE_PATH)
    indexed = _index_map_methods(diffable_root)
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
        "milestone_id": "phase5_map_init_travel",
        "declared_count": len(declared),
        "queue_items": len(written),
        "dry_run": dry_run,
        "partition_prefix": PARTITION_PREFIX,
        "method_ids": declared,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed Phase 5 Map init/travel declared milestone queue partitions."
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
