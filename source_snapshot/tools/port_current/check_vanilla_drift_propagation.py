"""Does a vanilla build change reach the rebuilt (modded) Core?

For every DB row (by id/sid) and Lang token (by sid) that differs between two vanilla Cores, compare
the rows of two Cores rebuilt from them by the same pipeline:
- propagated: rebuilt-new row == vanilla-new row (the mod leaves it alone and the change arrives);
- inherited: rebuilt-new != vanilla-new, but the row changed between the two rebuilds (the change
  arrives through a mod transform, e.g. a clone or a merge);
- pinned: rebuilt-new == rebuilt-old != vanilla-new (a layer re-writes the old value: the change is lost);
- missing: the row is absent from rebuilt-new.

    python tools/port_current/check_vanilla_drift_propagation.py --vanilla-old A --vanilla-new B \
        --rebuilt-old RA --rebuilt-new RB --out report.json
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diff_vanilla_cores import collect_rows, load, table_of  # noqa: E402


def lang_tokens(data: bytes) -> dict[str, object] | None:
    try:
        doc = load(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    out: dict[str, object] = {}
    for section in ("tokens", "array"):
        for row in doc.get(section) or []:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                out[row["sid"]] = row
    return out


def rows_of(z: zipfile.ZipFile, member: str) -> dict[str, object]:
    if member not in z.namelist():
        return {}
    if member.startswith("Lang/"):
        return lang_tokens(z.read(member)) or {}
    out: dict[str, object] = {}
    try:
        collect_rows(load(z.read(member)), out, Counter())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ("vanilla-old", "vanilla-new", "rebuilt-old", "rebuilt-new"):
        ap.add_argument(f"--{name}", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    va, vb = zipfile.ZipFile(args.vanilla_old), zipfile.ZipFile(args.vanilla_new)
    ra, rb = zipfile.ZipFile(args.rebuilt_old), zipfile.ZipFile(args.rebuilt_new)
    rb_names = set(rb.namelist())
    changed = [m for m in sorted(set(va.namelist()) & set(vb.namelist()))
               if m.endswith(".json") and (m.startswith("DB/") or m.startswith("Lang/"))
               and va.read(m) != vb.read(m)]
    added = [m for m in sorted(set(vb.namelist()) - set(va.namelist()))
             if m.endswith(".json") and (m.startswith("DB/") or m.startswith("Lang/"))]
    classes: Counter = Counter()
    by_table: dict[str, Counter] = defaultdict(Counter)
    details: dict[str, list] = defaultdict(list)
    # Rows can move between members of one table in the rebuilt Core (e.g. cloned into a new file);
    # index the rebuilt rows per table so lookups follow them.
    table_cache: dict[tuple[str, str], dict[str, object]] = {}

    def table_rows(z: zipfile.ZipFile, label: str, table: str) -> dict[str, object]:
        key = (label, table)
        if key not in table_cache:
            rows: dict[str, object] = {}
            for name in z.namelist():
                if table_of(name) == table and name.endswith(".json"):
                    rows.update(rows_of(z, name))
            table_cache[key] = rows
        return table_cache[key]

    for member in changed + added:
        old_rows = rows_of(va, member) if member in va.namelist() else {}
        new_rows = rows_of(vb, member)
        is_lang = member.startswith("Lang/")
        t = member if is_lang else table_of(member)
        for key in sorted(new_rows):
            if old_rows.get(key) == new_rows[key]:
                continue
            if is_lang:
                rb_rows = rows_of(rb, member) if member in rb_names else {}
                ra_rows = rows_of(ra, member)
            else:
                rb_rows = table_rows(rb, "rb", t)
                ra_rows = table_rows(ra, "ra", t)
            got_b, got_a = rb_rows.get(key), ra_rows.get(key)
            if got_b is None:
                cls = "missing"
            elif got_b == new_rows[key]:
                cls = "propagated"
            elif got_b == got_a:
                cls = "pinned"
            else:
                cls = "inherited"
            classes[cls] += 1
            by_table[t][cls] += 1
            if cls != "propagated":
                details[cls].append([member, key])
    report = {"schema": "homm3.port.vanilla_drift_propagation.v1", "proofTier": "generated artifact",
              "inputs": {k: str(getattr(args, k.replace("-", "_"))) for k in
                         ("vanilla-old", "vanilla-new", "rebuilt-old", "rebuilt-new")},
              "classes": dict(classes), "byTable": {t: dict(c) for t, c in sorted(by_table.items())},
              "details": details}
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"classes": dict(classes),
                      "nonPropagatedTables": {t: dict(c) for t, c in sorted(by_table.items())
                                              if set(c) - {"propagated"}}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
