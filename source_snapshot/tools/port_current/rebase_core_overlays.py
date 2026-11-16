#!/usr/bin/env python3
"""Rebase campaign/scenario core_overlay snapshots from one vanilla Core onto the next.

The StoryHub mission overlays and the scenario overlays carry whole copies of vanilla id-array
and Lang catalogs taken from an older Core. Every Core-writing install merges them retain-base
with overlay rows winning per key (tools/core_overlay_member_merge.py,
install_roe_castle_continuity_weave.merge_id_array_catalog_bytes), so after a vanilla patch the
snapshots silently revert the patched rows Core-wide (port 25672315 -> 26297049: 252 rows
restated verbatim plus 68 GE-modified pins, among them every vanilla barracks row losing
``applyMultipleInteraction``).

For every overlay member that is a Core member whose bytes differ between --old-core and
--new-core, ``core_overlay_member_merge.rebase_overlay_member`` takes the rows the patch changed,
drops those that only restate vanilla and 3-way merges the rest (base old, ours overlay, theirs
new). Members and rows vanilla did not change, and GE-only members and rows, are kept verbatim. Parameterized by the two
vanilla Cores so the next patch reuses it unchanged.

Fail closed: a field conflict, a member vanilla removed, or a changed vanilla member whose shape
the rebase does not understand stops the run before anything is written. --resolutions records
decided conflicts (row key -> theirs/ours with a reason). Without --apply the run is a dry run.
--apply copies each original into --backup-dir before replacing it.

Usage:
  python tools/port_current/rebase_core_overlays.py --old-core <25672315 root or Core.zip> \
      --new-core <26297049 root or Core.zip> --report <json> [--apply --backup-dir <dir>]

Proof tier: generated artifact (rewritten overlay snapshots); not an install or runtime proof.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from core_overlay_member_merge import (  # noqa: E402
    OverlayMergeError,
    OverlayRebaseConflict,
    rebase_overlay_member,
)

REPORT_SCHEMA = "homm3.port.core_overlay_rebase.v1"
RESOLUTIONS_SCHEMA = "homm3.port.core_overlay_rebase_resolutions.v1"
DEFAULT_SCAN_ROOT = REPO_ROOT / "artifacts" / "campaign_port_poc"
OVERLAY_DIR_NAME = "core_overlay"
CORE_IN_GAME_ROOT = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
# Overlay-root files that are not Core members (installer bookkeeping) or map elsewhere.
ROOT_MEMBER_ALIASES = {"quickStart.json": "DB/quickStart.json"}


def fail(message: str) -> None:
    print(f"rebase_core_overlays: FAIL {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_core(path: Path) -> Path:
    core = path / CORE_IN_GAME_ROOT if path.is_dir() else path
    if not core.is_file() or core.suffix.lower() != ".zip":
        fail(f"not a Core.zip or game root with {CORE_IN_GAME_ROOT.as_posix()}: {path}")
    return core


def discover_overlay_roots(scan_root: Path) -> list[Path]:
    """Every ``core_overlay`` directory under ``scan_root`` (not descending into one)."""
    if not scan_root.is_dir():
        fail(f"overlay scan root is not a directory: {scan_root}")
    roots: list[Path] = []
    for dirpath, dirnames, _ in os.walk(scan_root):
        if os.path.basename(dirpath) == OVERLAY_DIR_NAME:
            roots.append(Path(dirpath))
            dirnames[:] = []
        else:
            dirnames.sort()
    return sorted(roots)


def overlay_members(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        member = ROOT_MEMBER_ALIASES.get(rel, rel)
        if member.startswith(("DB/", "Lang/")):
            out[member] = path
    return out


def changed_vanilla_members(old: zipfile.ZipFile, new: zipfile.ZipFile, wanted: set[str]) -> tuple[list[str], list[str]]:
    old_names, new_names = set(old.namelist()), set(new.namelist())
    changed: list[str] = []
    removed: list[str] = []
    for member in sorted(wanted & old_names):
        if member not in new_names:
            removed.append(member)
        elif old.getinfo(member).CRC != new.getinfo(member).CRC or old.read(member) != new.read(member):
            changed.append(member)
    return changed, removed


def load_resolutions(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != RESOLUTIONS_SCHEMA:
        fail(f"{path}: schema must be {RESOLUTIONS_SCHEMA}")
    out: dict[str, dict[str, str]] = {}
    for member, rows in (doc.get("members") or {}).items():
        for row_key, entry in rows.items():
            if not isinstance(entry, dict) or not entry.get("reason"):
                fail(f"{path}: {member}[{row_key}] needs a choice and a reason")
            out.setdefault(member, {})[row_key] = entry.get("choice")
    return out


def rebase_all(
    roots: list[Path],
    old: zipfile.ZipFile,
    new: zipfile.ZipFile,
    resolutions: dict[str, dict[str, str]],
    *,
    write: bool,
    backup_dir: Path | None,
) -> dict[str, Any]:
    by_root = {root: overlay_members(root) for root in roots}
    wanted = set().union(*(m.keys() for m in by_root.values())) if by_root else set()
    changed, removed = changed_vanilla_members(old, new, wanted)
    if removed:
        users = {m: [str(r.relative_to(REPO_ROOT)) for r, ms in by_root.items() if m in ms] for m in removed}
        fail(f"overlays carry Core members the new vanilla removed: {json.dumps(users)[:2000]}")
    members_report: dict[str, Any] = {}
    errors: list[str] = []
    used: dict[str, set[str]] = {}
    files_changed = 0
    for member in changed:
        old_b, new_b = old.read(member), new.read(member)
        per_member = {"overlays": 0, "rewritten": 0, "kept": 0, "dropped": 0, "merged": 0, "resolvedTheirs": 0, "resolvedOurs": 0}
        for root, members in by_root.items():
            path = members.get(member)
            if path is None:
                continue
            per_member["overlays"] += 1
            raw = path.read_bytes()
            try:
                rebased, stats = rebase_overlay_member(
                    member, old_b, new_b, raw, resolutions=resolutions.get(member)
                )
            except OverlayRebaseConflict as exc:
                errors.extend(f"{path.relative_to(REPO_ROOT).as_posix()}: {c}" for c in exc.conflicts)
                continue
            except OverlayMergeError as exc:
                errors.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {exc}")
                continue
            for k, v in stats.items():
                if k == "resolutionsUsed":
                    used.setdefault(member, set()).update(v)
                else:
                    per_member[k] += v
            if rebased is None:
                continue
            per_member["rewritten"] += 1
            files_changed += 1
            if write:
                assert backup_dir is not None
                backup = backup_dir / path.relative_to(REPO_ROOT)
                if backup.exists():
                    fail(f"backup already exists, refusing to overwrite it: {backup}")
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(raw)
                tmp = path.with_name(path.name + ".rebase_tmp")
                tmp.write_bytes(rebased)
                os.replace(tmp, path)
        members_report[member] = per_member
    for member, rows in sorted(resolutions.items()):
        unmatched = sorted(set(rows) - used.get(member, set()))
        if unmatched:
            errors.append(f"resolutions for {member} match no vanilla row of any overlay (already applied?): {unmatched}")
    return {
        "changedVanillaMembersInOverlays": len(changed),
        "filesRewritten" if write else "filesToRewrite": files_changed,
        "members": members_report,
        "errors": errors,
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-core", type=Path, required=True, help="vanilla game root or Core.zip the snapshots were taken against")
    ap.add_argument("--new-core", type=Path, required=True, help="vanilla game root or Core.zip to rebase onto")
    ap.add_argument("--scan-root", type=Path, default=DEFAULT_SCAN_ROOT, help="directory searched for core_overlay dirs")
    ap.add_argument("--overlay-root", type=Path, action="append", default=[], help="explicit core_overlay dir (repeatable; replaces the scan)")
    ap.add_argument("--resolutions", type=Path, help=f"decided conflicts ({RESOLUTIONS_SCHEMA})")
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--apply", action="store_true", help="rewrite the overlays (default: dry run)")
    ap.add_argument("--backup-dir", type=Path, help="required with --apply; originals are copied here")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply and args.backup_dir is None:
        fail("--apply needs --backup-dir")
    old_core, new_core = resolve_core(args.old_core), resolve_core(args.new_core)
    if old_core.resolve() == new_core.resolve():
        fail("--old-core and --new-core are the same file")
    roots = [p.resolve() for p in args.overlay_root] or discover_overlay_roots(args.scan_root.resolve())
    for root in roots:
        if root.name != OVERLAY_DIR_NAME or not root.is_dir():
            fail(f"not a core_overlay directory: {root}")
    if not roots:
        fail(f"no core_overlay directories under {args.scan_root}")
    resolutions = load_resolutions(args.resolutions)
    started = time.time()
    with zipfile.ZipFile(old_core) as old, zipfile.ZipFile(new_core) as new:
        # Dry pass first: nothing is written unless every member of every overlay rebases.
        result = rebase_all(roots, old, new, resolutions, write=False, backup_dir=None)
        if args.apply and not result["errors"]:
            result = rebase_all(roots, old, new, resolutions, write=True, backup_dir=args.backup_dir.resolve())
    report = {
        "schema": REPORT_SCHEMA,
        "oldCore": str(old_core),
        "newCore": str(new_core),
        "overlayRoots": len(roots),
        "applied": bool(args.apply and not result["errors"]),
        "seconds": round(time.time() - started, 1),
        **result,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if result["errors"]:
        print(f"rebase_core_overlays: FAIL {len(result['errors'])} conflict(s); first: {result['errors'][0]}", file=sys.stderr)
        print(f"report: {args.report}", file=sys.stderr)
        return 1
    key = "filesRewritten" if report["applied"] else "filesToRewrite"
    print(f"rebase_core_overlays: OK roots={len(roots)} changedMembers={result['changedVanillaMembersInOverlays']} {key}={result[key]} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
