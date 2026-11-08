#!/usr/bin/env python3
"""Rewrite defextract JSON frame path prefixes (e.g. cpkman.dir/ → creature.dir/) for Unity FramesFolder layout."""
from __future__ import annotations

import json
import pathlib
import sys


def main() -> int:
	if len(sys.argv) != 4:
		print(
			"usage: fix_defextract_json_paths.py path/to/output.json fromPrefix toPrefix\n"
			"  example: fix_defextract_json_paths.py creature.json cpkman.dir/ creature.dir/",
			file=sys.stderr,
		)
		return 1
	p = pathlib.Path(sys.argv[1])
	from_prefix = sys.argv[2].replace("\\", "/")
	to_prefix = sys.argv[3].replace("\\", "/")
	raw = p.read_text(encoding="utf-8-sig")
	data = json.loads(raw)
	for seq in data.get("sequences") or []:
		frames = seq.get("frames")
		if not frames:
			continue
		fixed = []
		for fr in frames:
			if not isinstance(fr, str):
				fixed.append(fr)
				continue
			n = fr.replace("\\", "/")
			if n.startswith(from_prefix):
				n = to_prefix + n[len(from_prefix) :]
			fixed.append(n)
		seq["frames"] = fixed
	p.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
