"""
Quick scan of Unity IL2Cpp global-metadata.dat for symbol names (no GameAssembly decompile).

Use this before/ alongside Il2CppDumper output:
  py -3 il2cpp_metadata_scan.py "V:/.../global-metadata.dat" GenerateMap epw buf "Hex.Map|Map"

Full pseudo-decompile (struct types, method bodies as IL-ish):
  - Get Il2CppDumper (e.g. Perfare/Il2CppDumper), point at GameAssembly.dll + global-metadata.dat
  - Search dump.cs for "GenerateMap", "class epw", "Map.Init" — that is the deterministic map path.

This repo’s BepInEx interop/Hex.dll is Il2CppInterop glue, not a line-by-line game decompile.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
	if len(sys.argv) < 3:
		print(__doc__, file=sys.stderr)
		return 2
	meta = Path(sys.argv[1])
	needles = sys.argv[2:]
	if not meta.is_file():
		print(f"Not found: {meta}", file=sys.stderr)
		return 1
	raw = meta.read_bytes()
	s = raw.decode("utf-8", "replace")
	print(f"file={meta} size={len(raw)}", file=sys.stderr)
	for n in needles:
		idx = s.find(n)
		print(f"--- {n!r} -> offset {idx}")
		if idx < 0:
			continue
		lo, hi = max(0, idx - 100), min(len(s), idx + len(n) + 180)
		chunk = s[lo:hi]
		chunk = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "·", chunk)
		print(chunk)
		print()
	return 0


if __name__ == "__main__":
	sys.exit(main())
