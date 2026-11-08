#!/usr/bin/env python3
"""
Disassemble a range of x64 code in GameAssembly.dll at an Il2Cpp method RVA.
Requires: pip install pefile capstone

  py disasm_il2cpp_rva.py "path/to/GameAssembly.dll" 0x28CB310
  py disasm_il2cpp_rva.py "path/to/GameAssembly.dll" 28CB310 80
"""
from __future__ import annotations

import argparse
import sys

try:
    import pefile
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
except ImportError as e:
    print("Missing dependency:", e, file=sys.stderr)
    print("Install: py -3 -m pip install pefile capstone", file=sys.stderr)
    sys.exit(1)


def rva_to_file_offset(pe: pefile.PE, rva: int) -> int | None:
    for s in pe.sections:
        base = s.VirtualAddress
        end = base + s.Misc_VirtualSize
        if base <= rva < end:
            return s.PointerToRawData + (rva - base)
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dll", help="Path to GameAssembly.dll")
    p.add_argument("rva", help="Method RVA (e.g. 0x28CB310 or 28CB310)")
    p.add_argument("count", nargs="?", type=int, default=48, help="Max instructions (default 48)")
    args = p.parse_args()
    s = args.rva.strip()
    if s.startswith(("0x", "0X")):
        rva = int(s, 16)
    elif s.isdigit():
        rva = int(s, 10)
    else:
        rva = int(s, 16)
    pe = pefile.PE(args.dll)
    off = rva_to_file_offset(pe, rva)
    if off is None:
        print(f"RVA {rva:#x} not in any section", file=sys.stderr)
        sys.exit(1)
    with open(args.dll, "rb") as f:
        f.seek(off)
        # Capstone: enough bytes for N instructions (avg ~6)
        raw = f.read(min(8 * max(args.count, 1), 16384))
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    n = 0
    for insn in md.disasm(raw, rva):
        if n >= args.count:
            break
        print(f"  {insn.address:08x}: {insn.mnemonic:8} {insn.op_str}")
        n += 1


if __name__ == "__main__":
    main()
