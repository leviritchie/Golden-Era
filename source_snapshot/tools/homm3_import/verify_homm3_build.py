#!/usr/bin/env python3
"""Gate: manifest bundle for unitSid exists under build_out/ and is non-trivial size."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--unit", required=True, help="unitSid in homm3_units_manifest.json")
	ap.add_argument("--manifest", type=pathlib.Path, default=None)
	ap.add_argument("--build-out", type=pathlib.Path, dest="build_out", default=None)
	ap.add_argument("--emit-bundle-path", action="store_true", help="Print absolute bundle path and exit 0")

	args = ap.parse_args()

	here = pathlib.Path(__file__).resolve().parent
	manifest = (args.manifest or (here / "homm3_units_manifest.json")).resolve()
	build_out = (args.build_out or (here / "build_out")).resolve()

	if not manifest.is_file():
		print(f"verify_homm3_build: no manifest {manifest}", file=sys.stderr)
		return 1

	data = json.loads(manifest.read_text(encoding="utf-8-sig"))
	units = data.get("units") or []
	row = next((u for u in units if u.get("unitSid") == args.unit), None)
	if not row:
		print(f"verify_homm3_build: unitSid '{args.unit}' not in manifest", file=sys.stderr)
		return 1

	bundle_name = (row.get("bundleName") or "").strip()
	if not bundle_name:
		print("verify_homm3_build: row has no bundleName", file=sys.stderr)
		return 1

	bundle_path = build_out / bundle_name
	if args.emit_bundle_path:
		print(str(bundle_path.resolve()))
		return 0 if bundle_path.is_file() else 1
	if not bundle_path.is_file():
		print(f"verify_homm3_build: missing bundle file {bundle_path}", file=sys.stderr)
		return 1

	n = bundle_path.stat().st_size
	if n < 4096:
		print(f"verify_homm3_build: bundle too small ({n} bytes): {bundle_path}", file=sys.stderr)
		return 1

	print(f"verify_homm3_build: OK {bundle_path.name} ({n} bytes)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
