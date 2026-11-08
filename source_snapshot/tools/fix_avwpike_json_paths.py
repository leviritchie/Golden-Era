#!/usr/bin/env python3
"""Rewrite defextract JSON frame paths from cpkman.dir to avwpike.dir (Unity FramesFolder name)."""
from __future__ import annotations

import json
import pathlib
import sys


def main() -> int:
	if len(sys.argv) != 2:
		print("usage: fix_avwpike_json_paths.py path/to/avwpike.json", file=sys.stderr)
		return 1
	p = pathlib.Path(sys.argv[1])
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
			if n.startswith("cpkman.dir/"):
				n = "avwpike.dir/" + n[len("cpkman.dir/") :]
			fixed.append(n)
		seq["frames"] = fixed
	p.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
