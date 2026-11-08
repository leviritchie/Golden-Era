"""Compare two Core.zip files member by member (bytes). Prints missing/extra/differing counts.

    python tools/port_current/compare_core_members.py A.zip B.zip [--list N] [--json OUT]
Exit 0 when identical, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile


def members(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {i.filename.replace("\\", "/"): zf.read(i) for i in zf.infolist() if not i.is_dir()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--list", type=int, default=20)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    a, b = members(args.a), members(args.b)
    missing = sorted(set(a) - set(b))
    extra = sorted(set(b) - set(a))
    differ = sorted(m for m in set(a) & set(b) if a[m] != b[m])
    out = {"a": args.a, "b": args.b, "aMembers": len(a), "bMembers": len(b),
           "missingInB": missing, "extraInB": extra, "differ": differ}
    print(json.dumps({k: (v if not isinstance(v, list) else {"count": len(v), "head": v[:args.list]})
                      for k, v in out.items()}, indent=1))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    return 0 if not (missing or extra or differ) else 1


if __name__ == "__main__":
    sys.exit(main())
