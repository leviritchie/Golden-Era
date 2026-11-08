"""
Search Il2CppDumper dump.cs (and optionally stringliteral.json) for needles.

Examples:
  python search_il2cpp_dump.py LocKit "does not contain" MapInfoLocalization
  python search_il2cpp_dump.py --dump path/to/dump.cs LocInfo

Default dump path: <playtest>/tools/il2cpp_out/dump.cs (next to this script's tools folder).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="Path to dump.cs (default: ../tools/il2cpp_out/dump.cs next to playtest root)",
    )
    ap.add_argument(
        "--strings",
        type=Path,
        default=None,
        help="Optional stringliteral.json from same Il2CppDumper run",
    )
    ap.add_argument("needles", nargs="+", help="Substrings to search (case-sensitive)")
    args = ap.parse_args()

    script = Path(__file__).resolve()
    playtest_root = script.parent.parent
    dump = args.dump
    if dump is None:
        dump = playtest_root / "tools" / "il2cpp_out" / "dump.cs"
    if not dump.is_file():
        print(f"Not found: {dump}", file=sys.stderr)
        print("Run tools/run_il2cpp_dumper.cmd (or .sh) after placing Il2CppDumper in tools/il2cpp_dumper/", file=sys.stderr)
        return 1

    strings_path = args.strings
    if strings_path is None:
        cand = playtest_root / "tools" / "il2cpp_out" / "stringliteral.json"
        if cand.is_file():
            strings_path = cand

    text = dump.read_text(encoding="utf-8", errors="replace")
    print(f"dump.cs: {dump} ({len(text)} chars)\n")

    max_hits = 25
    for n in args.needles:
        print(f"=== {n!r} in dump.cs ===")
        hits = list(re.finditer(re.escape(n), text))
        if not hits:
            print("(no matches)\n")
            continue
        print(f"({len(hits)} hit(s); showing up to {max_hits})\n")
        for m in hits[:max_hits]:
            lo = max(0, m.start() - 200)
            hi = min(len(text), m.end() + 200)
            chunk = text[lo:hi].replace("\r", "")
            if chunk.count("\n") > 12:
                lines = chunk.split("\n")
                chunk = "\n".join(lines[:6] + ["  ..."] + lines[-6:])
            print(chunk)
            print("---")
        if len(hits) > max_hits:
            print(f"... {len(hits) - max_hits} more hit(s) omitted\n")
        else:
            print()

    if strings_path and strings_path.is_file():
        print(f"=== stringliteral.json: {strings_path} ===")
        try:
            data = json.loads(strings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"JSON error: {e}", file=sys.stderr)
            return 1
        # structure varies by dumper version; flatten common shapes
        literals: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    literals.append(item)
                elif isinstance(item, dict):
                    for k in ("value", "Value", "literal", "text"):
                        v = item.get(k)
                        if isinstance(v, str):
                            literals.append(v)
                            break
        for n in args.needles:
            hits = [s for s in literals if n in s]
            print(f"{n!r}: {len(hits)} string literal(s)")
            for s in hits[:30]:
                print(f"  {s[:500]!r}")
            if len(hits) > 30:
                print(f"  ... and {len(hits) - 30} more")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
