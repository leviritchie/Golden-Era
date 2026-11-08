"""Seed Battle EventArgs + edb queue partitions from DiffableCs (fail-closed)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from olden_cs_recovery.diffable_cs_scan import DiffableMethod, scan_battle_eventargs, scan_edb
from olden_cs_recovery.paths import (
    DEFAULT_DIFFABLE_HEX_ROOT,
    DEFAULT_ISIL_HEX_ROOT,
    PACKAGE_ROOT,
    QUEUE_PARTITIONS_DIR,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import empty_claim, to_iso, utc_now, write_queue_item


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


def _partition_for(method: DiffableMethod, domain: str) -> str:
    # Domain prefix + type short name keeps EventArgs claimable by Hex.Session.Battle
    # while still separating types for parallel lifters.
    short = method.type_name.rsplit(".", 1)[-1]
    if domain == "edb":
        return "edb"
    return f"{domain}/{short}"


def build_item(
    method: DiffableMethod,
    *,
    domain: str,
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
        evidence.append(
            {
                "kind": "isil",
                "path": _rel_repo(isil),
                "required": True,
            }
        )
    else:
        evidence.append(
            {
                "kind": "isil",
                "path": _rel_repo(isil_root / "MISSING"),
                "required": False,
                "notes": "ISIL companion not found at seed time; Phase 1 lifter must fail closed if still missing.",
            }
        )

    addr_map = REPO_ROOT / "experiments" / "cpp2il_readable_csharp" / "samples" / "latest_refresh" / "address_map_hex_session_battle.json"
    evidence.append(
        {
            "kind": "address_map",
            "path": _rel_repo(addr_map),
            "required": addr_map.is_file(),
            "notes": "Battle session method-pointer map when present.",
        }
    )

    partition = _partition_for(method, domain)
    return {
        "schema_version": 1,
        "method_id": method.method_id,
        "domain": domain,
        "partition": partition,
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
        "notes": "Seeded by seed_battle_partition from DiffableCs shells. Not promoted.",
    }


def seed(
    *,
    diffable_root: Path,
    isil_root: Path,
    dry_run: bool,
    clean_partitions: bool,
) -> dict:
    gaps: list[str] = []
    if not diffable_root.is_dir():
        gaps.append(f"DiffableCs Hex root missing: {diffable_root}")
    edb_path = diffable_root / "edb.cs"
    battle_dir = diffable_root / "Hex" / "Session" / "Battle"
    if diffable_root.is_dir() and not edb_path.is_file():
        gaps.append(f"edb.cs missing: {edb_path}")
    if diffable_root.is_dir() and not battle_dir.is_dir():
        gaps.append(f"Battle EventArgs dir missing: {battle_dir}")

    if gaps:
        report = {
            "ok": False,
            "scaffolding_only": True,
            "gaps": gaps,
            "queue_partitions_dir": str(QUEUE_PARTITIONS_DIR),
            "hint": (
                "Queue scaffolding remains under queue/partitions/. "
                "Regenerate Cpp2IL DiffableCs, then re-run this seed. Fail closed — no invented methods."
            ),
        }
        QUEUE_PARTITIONS_DIR.mkdir(parents=True, exist_ok=True)
        marker = PACKAGE_ROOT / "queue" / "SEED_GAP.json"
        marker.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(json.dumps(report, indent=2))

    eventargs = scan_battle_eventargs(diffable_root)
    edb_methods = scan_edb(diffable_root)

    # Prefer instance/static methods that look like dispatch for edb milestone visibility,
    # but still seed every parsed method so the queue is honest about surface area.
    items: list[dict] = []
    for method in eventargs:
        items.append(build_item(method, domain="Hex.Session.Battle", diffable_root=diffable_root, isil_root=isil_root))
    for method in edb_methods:
        items.append(build_item(method, domain="edb", diffable_root=diffable_root, isil_root=isil_root))

    # Deduplicate by method_id (fail closed on collision with differing signatures/paths).
    by_id: dict[str, dict] = {}
    for item in items:
        mid = item["method_id"]
        if mid in by_id:
            prev = by_id[mid]
            if prev["signature"] != item["signature"] or prev["source_line"] != item["source_line"]:
                raise SystemExit(
                    f"FAIL: duplicate method_id with conflicting metadata: {mid}\n"
                    f"  a: {prev['signature']} @ {prev['source_line']}\n"
                    f"  b: {item['signature']} @ {item['source_line']}"
                )
            continue
        by_id[mid] = item

    written = []
    if clean_partitions and not dry_run:
        for path in QUEUE_PARTITIONS_DIR.rglob("*.json"):
            path.unlink()

    for item in by_id.values():
        if dry_run:
            written.append({"method_id": item["method_id"], "partition": item["partition"], "dry_run": True})
            continue
        path = write_queue_item(item)
        written.append({"method_id": item["method_id"], "partition": item["partition"], "path": str(path)})

    gap_marker = PACKAGE_ROOT / "queue" / "SEED_GAP.json"
    if gap_marker.is_file() and not dry_run:
        gap_marker.unlink()

    summary = {
        "ok": True,
        "scaffolding_only": False,
        "diffable_root": str(diffable_root),
        "eventargs_methods": len(eventargs),
        "edb_methods": len(edb_methods),
        "queue_items": len(by_id),
        "dry_run": dry_run,
        "sample_method_ids": sorted(by_id.keys())[:8],
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Hex.Session.Battle EventArgs + edb queue partitions.")
    parser.add_argument("--diffable-hex-root", type=Path, default=DEFAULT_DIFFABLE_HEX_ROOT)
    parser.add_argument("--isil-hex-root", type=Path, default=DEFAULT_ISIL_HEX_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing queue JSON under queue/partitions/ before writing (fail-closed reseed).",
    )
    args = parser.parse_args(argv)
    summary = seed(
        diffable_root=args.diffable_hex_root,
        isil_root=args.isil_hex_root,
        dry_run=args.dry_run,
        clean_partitions=args.clean,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
