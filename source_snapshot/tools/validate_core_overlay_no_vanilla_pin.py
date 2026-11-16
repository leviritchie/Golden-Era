#!/usr/bin/env python3
"""Fail when a campaign/scenario core_overlay snapshot still pins vanilla rows a patch changed.

Install merges let overlay rows win per key, so an overlay row that restates vanilla content
reverts a later vanilla patch Core-wide (port 25672315 -> 26297049: 252 restated rows plus 68
GE-modified pins). tools/port_current/rebase_core_overlays.py removes them; this validator
checks that nothing is left:

  1. built-in fixtures pin the rebase semantics of tools/core_overlay_member_merge.py (drop a
     restated row, snapshot omission is not a deletion, 3-way field merge, conflict fails
     closed, Lang sid rows, idempotence, recorded resolutions);
  2. with --old-core/--new-core, no overlay row may pin a vanilla row the patch changed: in
     every overlay member that is a Core member changed between the two builds, a rebase must
     have nothing left to drop (restated row), merge (pinned field) or refuse (conflict). Rows
     a recorded ``"ours"`` resolution keeps are allowed.

Cheap: reads only the overlay members vanilla changed. Read-only.

Usage:
  python tools/validate_core_overlay_no_vanilla_pin.py --fixtures-only
  python tools/validate_core_overlay_no_vanilla_pin.py --old-core <old root|Core.zip> --new-core <new root|Core.zip> \
      [--resolutions <rebase resolutions json>]

Proof tier: source/static (fixtures) and generated artifact (overlay scan).
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "port_current"))

from core_overlay_member_merge import (  # noqa: E402
    OverlayMergeError,
    OverlayRebaseConflict,
    merge_id_array,
    overlay_vanilla_pins,
    rebase_overlay_member,
)
from rebase_core_overlays import (  # noqa: E402
    DEFAULT_SCAN_ROOT,
    RESOLUTIONS_SCHEMA,
    changed_vanilla_members,
    discover_overlay_roots,
    overlay_members,
    resolve_core,
)


def _doc(rows: list[dict], section: str = "array") -> bytes:
    return (json.dumps({section: rows}, indent=2) + "\n").encode("utf-8")


def _rows(raw: bytes, section: str = "array") -> list[dict]:
    return json.loads(raw.decode("utf-8-sig"))[section]


def run_fixtures() -> list[str]:
    errors: list[str] = []

    def check(name: str, ok: bool) -> None:
        if not ok:
            errors.append(f"fixture {name}")

    m = "DB/objects_logic/hires/barracks.json"
    old = _doc([
        {"id": "b1", "aiValue": 1, "applyMultipleInteraction": True, "tier": 1},
        {"id": "b2", "aiValue": 2, "goodsValue": 5, "tier": 2},
        {"id": "gone", "aiValue": 3},
        {"id": "same", "aiValue": 6},
    ])
    new = _doc([
        {"id": "b1", "aiValue": 10, "applyMultipleInteraction": True, "tier": 1},
        {"id": "b2", "aiValue": 20, "goodsValue": 5, "tier": 2},
        {"id": "added", "aiValue": 4},
        {"id": "same", "aiValue": 6},
    ])
    overlay = _doc([
        {"id": "b1", "aiValue": 1, "tier": 1},  # restated old row minus a field: snapshot omission
        {"id": "b2", "aiValue": 2, "goodsValue": 7, "tier": 2},  # GE edit on a field vanilla kept
        {"id": "gone", "aiValue": 3},  # restated row vanilla removed
        {"id": "ge_row", "aiValue": 9},  # GE-owned
        {"id": "same", "aiValue": 6},  # vanilla row the patch did not touch
    ])
    out, stats = rebase_overlay_member(m, old, new, overlay)
    rows = _rows(out) if out else []
    check("drop restated + removed rows", [r["id"] for r in rows] == ["b2", "ge_row", "same"] and stats["dropped"] == 2)
    check("3-way keeps GE field, takes vanilla field", rows[:1] == [{"id": "b2", "aiValue": 20, "goodsValue": 7, "tier": 2}])
    check("GE-only and untouched vanilla rows verbatim", rows[1:] == [{"id": "ge_row", "aiValue": 9}, {"id": "same", "aiValue": 6}])
    merged = _rows(merge_id_array(new, out, member=m))
    b1 = next(r for r in merged if r["id"] == "b1")
    check("retain-base merge restores applyMultipleInteraction", b1.get("applyMultipleInteraction") is True and b1["aiValue"] == 10)
    again, _ = rebase_overlay_member(m, old, new, out)
    check("idempotent", again is None)
    check("validator clean after rebase", overlay_vanilla_pins(m, old, new, out) == [])
    check("validator flags the 3 patched rows", len(overlay_vanilla_pins(m, old, new, overlay)) == 3)

    conflict = _doc([{"id": "b1", "aiValue": 5, "tier": 1}])
    try:
        rebase_overlay_member(m, old, new, conflict)
        check("field conflict fails closed", False)
    except OverlayRebaseConflict as exc:
        check("field conflict names the field", len(exc.conflicts) == 1 and "b1.aiValue" in exc.conflicts[0])
    out_t, st_t = rebase_overlay_member(m, old, new, conflict, resolutions={"b1": "theirs"})
    check("resolution theirs drops the row", out_t is not None and _rows(out_t) == [] and st_t["resolvedTheirs"] == 1)
    out_o, st_o = rebase_overlay_member(m, old, new, conflict, resolutions={"b1": "ours"})
    check("resolution ours keeps the row", out_o is None and st_o["resolutionsUsed"] == ["b1"])
    check("validator honours keep_ours", overlay_vanilla_pins(m, old, new, conflict, keep_ours=("b1",)) == [])
    clash = _doc([{"id": "added", "aiValue": 99}])
    try:
        rebase_overlay_member(m, old, new, clash)
        check("row added by both fails closed", False)
    except OverlayRebaseConflict:
        pass
    try:
        rebase_overlay_member(m, old, new, _doc([{"id": "x"}, {"id": "x"}]))
        check("duplicate overlay ids fail closed", False)
    except OverlayMergeError:
        pass

    lm = "Lang/german/texts/customMaps.json"
    lold = (json.dumps({"tokens": [{"sid": "a", "text": "alt"}, {"sid": "b", "text": "x"}]}, indent="\t") + "\n").encode("utf-8")
    lnew = (json.dumps({"tokens": [{"sid": "a", "text": "neu"}, {"sid": "b", "text": "x"}]}, indent="\t") + "\n").encode("utf-8")
    lov = (json.dumps({"tokens": [{"sid": "a", "text": "alt"}, {"sid": "b", "text": "x"}, {"sid": "ge", "text": "ge"}]}, indent="\t") + "\n").encode("utf-8")
    lout, _ = rebase_overlay_member(lm, lold, lnew, lov)
    check("Lang patched row dropped, untouched + GE sids kept", lout is not None and _rows(lout, "tokens") == [{"sid": "b", "text": "x"}, {"sid": "ge", "text": "ge"}])
    check("Lang keeps tab indent", lout is not None and b'\n\t"tokens"' in lout)
    return errors


def load_keep_ours(path: Path | None) -> dict[str, tuple[str, ...]]:
    if path is None:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != RESOLUTIONS_SCHEMA:
        raise SystemExit(f"validate_core_overlay_no_vanilla_pin: FAIL {path}: schema must be {RESOLUTIONS_SCHEMA}")
    return {
        member: tuple(k for k, e in rows.items() if isinstance(e, dict) and e.get("choice") == "ours")
        for member, rows in (doc.get("members") or {}).items()
    }


def scan(old_core: Path, new_core: Path, scan_root: Path, keep_ours: dict[str, tuple[str, ...]]) -> tuple[int, int, list[str]]:
    roots = discover_overlay_roots(scan_root)
    if not roots:
        return 0, 0, [f"no core_overlay directories under {scan_root}"]
    by_root = {root: overlay_members(root) for root in roots}
    wanted = set().union(*(m.keys() for m in by_root.values()))
    errors: list[str] = []
    with zipfile.ZipFile(old_core) as old, zipfile.ZipFile(new_core) as new:
        changed, removed = changed_vanilla_members(old, new, wanted)
        errors.extend(f"overlays carry {m}, which the new vanilla removed" for m in removed)
        for member in changed:
            old_b, new_b = old.read(member), new.read(member)
            for root, members in by_root.items():
                path = members.get(member)
                if path is None:
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                try:
                    pins = overlay_vanilla_pins(member, old_b, new_b, path.read_bytes(), keep_ours=keep_ours.get(member, ()))
                except OverlayMergeError as exc:
                    pins = [str(exc)]
                errors.extend(f"{rel}: {p}" for p in pins)
    return len(roots), len(changed), errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-core", type=Path)
    ap.add_argument("--new-core", type=Path)
    ap.add_argument("--scan-root", type=Path, default=DEFAULT_SCAN_ROOT)
    ap.add_argument("--resolutions", type=Path, help="rebase resolutions; rows decided 'ours' are allowed pins")
    ap.add_argument("--fixtures-only", action="store_true")
    args = ap.parse_args(argv)
    errors = run_fixtures()
    summary = f"fixtures={'ok' if not errors else 'FAIL'}"
    if not args.fixtures_only:
        if args.old_core is None or args.new_core is None:
            print("validate_core_overlay_no_vanilla_pin: FAIL --old-core and --new-core are required (or --fixtures-only)", file=sys.stderr)
            return 1
        roots, changed, scan_errors = scan(
            resolve_core(args.old_core), resolve_core(args.new_core), args.scan_root.resolve(), load_keep_ours(args.resolutions)
        )
        errors.extend(scan_errors)
        summary += f" overlayRoots={roots} changedVanillaMembers={changed} pins={len(scan_errors)}"
    if errors:
        for line in errors[:40]:
            print(f"  {line}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  ... {len(errors) - 40} more", file=sys.stderr)
        print(f"validate_core_overlay_no_vanilla_pin: FAIL {summary}", file=sys.stderr)
        return 1
    print(f"validate_core_overlay_no_vanilla_pin: OK {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
