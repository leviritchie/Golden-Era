"""
Scan IL2CPP global-metadata.dat for ASCII runs mentioning faction/town keywords.

Shipped mod faction ids (homm3_*, dungeon_raw) live in Core.zip JSON; they typically do **not**
appear in global-metadata.dat. Type names like BhCityUISession **do**.

GameAssembly.dll usually does **not** embed plaintext \"dungeon\" literals (Il2CPP stores strings
in metadata); use Il2CppDumper on metadata + GameAssembly for xref graphs.

Run:
  python scan_il2cpp_metadata_strings.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
METADATA_REL = Path("HeroesOE_Data/il2cpp_data/Metadata/global-metadata.dat")

KEYWORDS = re.compile(
    r"(dungeon|cityDungeon|fraction|Fraction|town|ObjCity|BhCity|Stronghold|homm3)",
    re.IGNORECASE,
)


def ascii_runs(blob: bytes, min_len: int) -> list[str]:
    pat = re.compile(rb"[ -~]{%d,}" % min_len)
    return [m.group().decode("ascii") for m in pat.finditer(blob)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--min-len", type=int, default=6)
    args = ap.parse_args()

    meta = args.game_root / METADATA_REL
    if not meta.is_file():
        print(f"Missing {meta}")
        return

    blob = meta.read_bytes()
    runs = ascii_runs(blob, args.min_len)
    matched = sorted({s for s in runs if KEYWORDS.search(s)})
    print(f"{meta.name}: {len(blob) / 1024 / 1024:.1f} MB, {len(runs)} ascii runs (min_len={args.min_len})")
    print(f"Runs matching keyword heuristic: {len(matched)}\n")
    for s in matched[:500]:
        print(s)
    if len(matched) > 500:
        print(f"\n... and {len(matched) - 500} more")


if __name__ == "__main__":
    main()
