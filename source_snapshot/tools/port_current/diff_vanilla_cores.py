"""Diff two vanilla Core.zip builds: members, schema paths, rows and values.

Both inputs must be vanilla (no mod markers). Rows are the dict items of any list in a JSON
member that carry a string ``id`` or ``sid``; a row's table is its member's directory
(``DB/units/units_logics``) so rows moved between files of one table still pair up.

    python tools/port_current/diff_vanilla_cores.py --old A/Core.zip --new B/Core.zip \
        --old-build 25061458 --new-build 25509697 --out artifacts/port_current/core_diff_X_Y.json

The output is one JSON with sections ``members``, ``schema`` (JSON paths added/removed per table),
``rows`` (added/removed/changed ids per table) and ``values`` (per table: changed leaf paths with
counts, and every changed row's leaf changes as ``[path, old, new]``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MOD_MARKERS = ("homm3", "h3_", "hota_")
MISSING = "<absent>"


def strip_comments(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j < 0 else j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        out.append(c); i += 1
    return "".join(out)


def load(data: bytes) -> Any:
    text = data.decode("utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r",\s*([}\]])", r"\1", strip_comments(text))
        return json.loads(text)


def table_of(member: str) -> str:
    parts = member.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else member


def row_key(item: Any) -> str | None:
    if isinstance(item, dict):
        for k in ("id", "sid"):
            if isinstance(item.get(k), str):
                return item[k]
    return None


def collect_rows(doc: Any, out: dict[str, Any], dup: Counter) -> None:
    if isinstance(doc, dict):
        for v in doc.values():
            collect_rows(v, out, dup)
    elif isinstance(doc, list):
        keyed = [row_key(x) for x in doc]
        if doc and all(k is not None for k in keyed):
            for k, x in zip(keyed, doc):
                if k in out:
                    dup[k] += 1
                out[k] = x
            return
        for v in doc:
            collect_rows(v, out, dup)


def schema_paths(doc: Any, prefix: str = "", out: set[str] | None = None) -> set[str]:
    out = set() if out is None else out
    if isinstance(doc, dict):
        for k, v in doc.items():
            p = f"{prefix}.{k}"
            out.add(p)
            schema_paths(v, p, out)
    elif isinstance(doc, list):
        for v in doc:
            schema_paths(v, prefix + "[]", out)
    return out


def leaves(doc: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf map; list items are keyed by their row key when they have one, else by index."""
    out: dict[str, Any] = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.update(leaves(v, f"{prefix}.{k}"))
    elif isinstance(doc, list):
        keys = [row_key(x) for x in doc]
        use_keys = doc and all(k is not None for k in keys) and len(set(keys)) == len(keys)
        out[f"{prefix}#len"] = len(doc)
        for i, v in enumerate(doc):
            out.update(leaves(v, f"{prefix}[{keys[i] if use_keys else i}]"))
    else:
        out[prefix] = doc
    return out


GENERIC_INDEX = re.compile(r"\[[^\]]*\]")


def generic(path: str) -> str:
    return GENERIC_INDEX.sub("[]", path)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument("--old-build", required=True)
    ap.add_argument("--new-build", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    za, zb = zipfile.ZipFile(args.old), zipfile.ZipFile(args.new)
    ma = {i.filename: i for i in za.infolist() if not i.is_dir()}
    mb = {i.filename: i for i in zb.infolist() if not i.is_dir()}
    for name, members in (("old", ma), ("new", mb)):
        marked = [m for m in members if any(t in m.lower() for t in MOD_MARKERS)]
        if marked:
            raise SystemExit(f"--{name} is not vanilla: {marked[:5]}")

    added = sorted(set(mb) - set(ma))
    removed = sorted(set(ma) - set(mb))
    changed = sorted(m for m in set(ma) & set(mb) if za.read(m) != zb.read(m))

    rows_a: dict[str, dict[str, Any]] = defaultdict(dict)
    rows_b: dict[str, dict[str, Any]] = defaultdict(dict)
    schema_a: dict[str, set[str]] = defaultdict(set)
    schema_b: dict[str, set[str]] = defaultdict(set)
    dups: dict[str, Counter] = defaultdict(Counter)
    unparsed: list[str] = []
    json_members = [m for m in sorted(set(ma) | set(mb)) if m.startswith("DB/") or m.startswith("generator/")]
    for m in json_members:
        t = table_of(m)
        for z, members, rows, schema in ((za, ma, rows_a, schema_a), (zb, mb, rows_b, schema_b)):
            if m not in members:
                continue
            try:
                doc = load(z.read(m))
            except (json.JSONDecodeError, UnicodeDecodeError):
                unparsed.append(m)
                continue
            collect_rows(doc, rows[t], dups[t])
            schema_paths(doc, "", schema[t])

    schema_out = {}
    for t in sorted(set(schema_a) | set(schema_b)):
        add = sorted(schema_b[t] - schema_a[t])
        rem = sorted(schema_a[t] - schema_b[t])
        if add or rem:
            schema_out[t] = {"added": add, "removed": rem}

    rows_out, values_out = {}, {}
    for t in sorted(set(rows_a) | set(rows_b)):
        ra, rb = rows_a[t], rows_b[t]
        radd, rrem = sorted(set(rb) - set(ra)), sorted(set(ra) - set(rb))
        rchg, detail, paths = [], {}, Counter()
        for k in sorted(set(ra) & set(rb)):
            if ra[k] == rb[k]:
                continue
            rchg.append(k)
            la, lb = leaves(ra[k]), leaves(rb[k])
            diffs = []
            for p in sorted(set(la) | set(lb)):
                va, vb = la.get(p, MISSING), lb.get(p, MISSING)
                if va != vb:
                    diffs.append([p, va, vb])
                    paths[generic(p)] += 1
            detail[k] = diffs
        if radd or rrem or rchg:
            rows_out[t] = {"oldRows": len(ra), "newRows": len(rb), "added": radd, "removed": rrem,
                           "changedCount": len(rchg), "changed": rchg}
        if detail:
            values_out[t] = {"pathCounts": paths.most_common(), "rows": detail}

    report = {
        "schema": "homm3.port.vanilla_core_diff.v1",
        "proofTier": "generated artifact",
        "old": {"build": args.old_build, "path": str(args.old), "sha256": sha(args.old.read_bytes()),
                "members": len(ma)},
        "new": {"build": args.new_build, "path": str(args.new), "sha256": sha(args.new.read_bytes()),
                "members": len(mb)},
        "members": {"added": added, "removed": removed, "changedCount": len(changed), "changed": changed},
        "unparsedMembers": sorted(set(unparsed)),
        "duplicateRowKeys": {t: dict(c) for t, c in dups.items() if c},
        "schemaPaths": schema_out,
        "rows": rows_out,
        "values": values_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    summary = {
        "members": {"added": len(added), "removed": len(removed), "changed": len(changed)},
        "schemaTablesChanged": len(schema_out),
        "rowTables": {t: [len(r["added"]), len(r["removed"]), r["changedCount"]] for t, r in rows_out.items()},
        "unparsed": len(set(unparsed)),
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
