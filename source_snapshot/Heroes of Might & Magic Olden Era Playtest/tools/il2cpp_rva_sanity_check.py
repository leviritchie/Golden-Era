#!/usr/bin/env python3
"""
Quick check that given RVAs still fall inside a loaded PE section of GameAssembly.dll
after a game update (il2cpp RAVs move when the binary is rebuilt).

  py il2cpp_rva_sanity_check.py path/to/GameAssembly.dll
  (edit KNOWN_RVAS below or pass as args: name 0x28CB310)

Requires: pip install pefile
"""
from __future__ import annotations

import sys

try:
    import pefile
except ImportError as e:
    print("Install: py -3 -m pip install pefile", file=sys.stderr)
    raise e

# From docs/il2cpp-map-generate-trace.md — refresh names/values after il2cpp re-dump.
KNOWN_RVAS: list[tuple[str, int]] = [
    ("epw$$GenerateMap", 0x20D4DF0),
    ("Hex.Map.Map$$Init", 0x28CB310),
    ("bwe$$.ctor", 0x2939110),
    ("bts$$Init", 0x28C15F0),
    ("bts_Init_tail", 0x28C9930),
    ("buz$$.ctor", 0x2900A70),
    ("buf$$.ctor", 0x28D8E20),
]


def rva_in_pe(pe: pefile.PE, rva: int) -> tuple[bool, str]:
    for s in pe.sections:
        b, e = s.VirtualAddress, s.VirtualAddress + s.Misc_VirtualSize
        if b <= rva < e:
            name = s.Name.rstrip(b"\0").decode("ascii", errors="replace")
            return True, f".text-or-{name}"
    return False, "out_of_range"


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print("Usage: il2cpp_rva_sanity_check.py <GameAssembly.dll>", file=sys.stderr)
        sys.exit(2)
    dll = args[0]
    extra: list[tuple[str, int]] = []
    i = 1
    while i + 1 < len(args):
        name = args[i]
        rva = int(args[i + 1], 0)
        extra.append((name, rva))
        i += 2
    pairs = extra if extra else KNOWN_RVAS
    pe = pefile.PE(dll)
    ok = 0
    for name, rva in pairs:
        good, where = rva_in_pe(pe, rva)
        if good:
            print(f"OK  {name} {rva:#x}  ({where})")
            ok += 1
        else:
            print(f"BAD {name} {rva:#x}  ({where})")
    if ok != len(pairs):
        sys.exit(1)


if __name__ == "__main__":
    main()
