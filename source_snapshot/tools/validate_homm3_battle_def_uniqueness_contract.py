"""Two HoMM3 inventory units must not resolve to the same battle DEF unless an allowlist entry says why.

    python tools/validate_homm3_battle_def_uniqueness_contract.py [-v]

Every row of tools/homm3_import/units_inventory.json resolves its battle source the way
tools/homm3_import/extract_creature.py does (vcmi JSON zip member, else loose battleDefPath, else zip
member, else battleLod + battleLodEntry; names compared case-insensitively). When two or more units
resolve to the same source, the group must be listed in tools/homm3_battle_def_shared_allowlist.json
with a reason - otherwise one unit is silently showing another creature's art (h3_rust_dragon was
extracted from CRDRGN.def, the Red Dragon, instead of CRsDgn.def). An allowlist group that is no longer
shared fails too, so the list only shrinks. Entries with "kind": "defect" are known-wrong mappings kept
visible until their owner re-extracts; they are not a licence to add more.
Proof tier: source/static (reads the inventory only).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tools/homm3_import/units_inventory.json"
ALLOWLIST = ROOT / "tools/homm3_battle_def_shared_allowlist.json"


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().lower()


def battle_source(row: dict) -> str | None:
    if row.get("battleJsonZipMember"):
        return f"zipjson:{_norm(row.get('battleZipPath', ''))}!{_norm(row['battleJsonZipMember'])}"
    if row.get("battleDefPath"):
        return f"path:{_norm(row['battleDefPath'])}"
    if row.get("battleZipMember"):
        return f"zip:{_norm(row.get('battleZipPath', ''))}!{_norm(row['battleZipMember'])}"
    if row.get("battleLodEntry"):
        return f"lod:{_norm(row.get('battleLod') or 'H3sprite.lod')}:{_norm(row['battleLodEntry'])}"
    return None


def main() -> int:
    verbose = "-v" in sys.argv
    inv = json.loads(INVENTORY.read_text(encoding="utf-8-sig"))
    groups: dict[str, list[str]] = defaultdict(list)
    for row in inv.get("units") or []:
        src = battle_source(row)
        if src:
            groups[src].append(row["unitSid"])
    shared = {src: sorted(sids) for src, sids in groups.items() if len(sids) > 1}
    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["groups"]
    allowed = {frozenset(e["units"]): e for e in allow}
    errors = []
    for e in allow:
        if not e.get("reason") or e.get("kind") not in ("shared_art", "defect"):
            errors.append(f"allowlist entry {e.get('units')}: needs a reason and kind shared_art|defect")
    for src, sids in sorted(shared.items()):
        if frozenset(sids) not in allowed:
            errors.append(f"{src}: units {sids} resolve to the same battle DEF; fix the inventory row or "
                          f"allowlist the group with a reason in {ALLOWLIST.relative_to(ROOT).as_posix()}")
        elif verbose:
            e = allowed[frozenset(sids)]
            print(f"  allowed {src}: {sids} ({e['kind']}: {e['reason']})")
    live = {frozenset(s) for s in shared.values()}
    for key, e in allowed.items():
        if key not in live:
            errors.append(f"allowlist group {sorted(key)} no longer shares a battle DEF; remove it")
    for m in errors:
        print("FAIL", m)
    defects = sum(1 for e in allow if e.get("kind") == "defect")
    print(f"homm3 battle DEF uniqueness contract: {len(groups)} sources, {len(shared)} shared "
          f"({defects} known defects), {len(errors)} violation(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
