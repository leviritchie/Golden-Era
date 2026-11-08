#!/usr/bin/env python3
"""
Scan Core.zip `generator/**/*.json` for faction-id string literals that could omit mod factions.

Findings (typical shipped Core):
  - No `"fraction": "<id>"` keys appear under generator/ — RMG data is sid/pool based.
  - Quoted tokens "human", "dungeon", … also tend to be absent (verify with --quoted-tokens).

Optional: `--all-json` scans every *.json in Core.zip for `"fraction":"..."` counts by top-level folder.

Usage:
  python tools/audit_core_generator_faction_literals.py
  python tools/audit_core_generator_faction_literals.py --core "D:/Games/.../Core.zip"
"""

from __future__ import annotations

import argparse
import re
import zipfile
from collections import Counter, defaultdict

DEFAULT_CORE = (
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)

SHIPPED = frozenset({"human", "undead", "dungeon", "demon", "nature", "unfrozen"})
QUOTED_TOKENS = tuple(f'"{s}"' for s in sorted(SHIPPED)) + ('"homm3_stronghold"', '"homm3_fortress"')

RE_EXPLICIT_FRACTION = re.compile(r'"fraction"\s*:\s*"([^"]+)"')


def scan_generator(zip_path: str, quoted: bool) -> None:
    with zipfile.ZipFile(zip_path, "r") as z:
        gen = sorted(
            n for n in z.namelist() if n.startswith("generator/") and n.endswith(".json")
        )

    explicit_files = []
    token_hits: dict[str, list[str]] = {t: [] for t in QUOTED_TOKENS}

    with zipfile.ZipFile(zip_path, "r") as z:
        for name in gen:
            raw = z.read(name).decode("utf-8-sig")
            if RE_EXPLICIT_FRACTION.search(raw):
                explicit_files.append(name)
            if quoted:
                for t in QUOTED_TOKENS:
                    if t in raw:
                        token_hits[t].append(name)

    print(f"Scanned {len(gen)} files under generator/")
    print(f'Files with JSON key pattern "fraction": "<string>": {len(explicit_files)}')
    for f in explicit_files[:20]:
        print("  ", f)
    if len(explicit_files) > 20:
        print(f"  ... +{len(explicit_files) - 20} more")

    if quoted:
        print("\nQuoted token substring hits (any context):")
        for t in QUOTED_TOKENS:
            n = len(token_hits[t])
            if n:
                print(f"  {t}: {n} file(s), e.g. {token_hits[t][:3]}")
        if not any(token_hits.values()):
            print("  (none)")


def scan_all_folders(zip_path: str) -> None:
    by_top: dict[str, Counter] = defaultdict(Counter)
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            raw = z.read(name).decode("utf-8-sig", "replace")
            for m in RE_EXPLICIT_FRACTION.finditer(raw):
                top = name.split("/")[0] if "/" in name else name
                by_top[top][m.group(1)] += 1

    print('All Core *.json: counts of "fraction": "<id>" by top-level folder (top 8 values each)')
    for top in sorted(by_top):
        c = by_top[top]
        print(f"\n[{top}/]  distinct ids: {len(c)}  total: {sum(c.values())}")
        for val, n in c.most_common(8):
            mark = " (shipped)" if val in SHIPPED else (" (mod)" if str(val).startswith("homm3_") else "")
            print(f"   {n:6}  {val!r}{mark}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", type=str, default=DEFAULT_CORE, help="Path to Core.zip")
    ap.add_argument(
        "--quoted-tokens",
        action="store_true",
        help='Also count raw substrings like "dungeon" in generator/ (can false-positive on non-JSON text)',
    )
    ap.add_argument(
        "--all-json",
        action="store_true",
        help='Scan every *.json in Core for "fraction":"..." aggregate by top-level folder',
    )
    args = ap.parse_args()

    scan_generator(args.core, quoted=args.quoted_tokens)
    if args.all_json:
        print()
        scan_all_folders(args.core)


if __name__ == "__main__":
    main()
