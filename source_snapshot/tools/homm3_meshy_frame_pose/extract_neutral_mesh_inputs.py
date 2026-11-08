#!/usr/bin/env python3
"""Extract frame-zero stills for neutral catalog slots missing Meshy inputs.

The normal creature extractor writes into the Unity project junction, which is
not writable in every checkout.  This wrapper deliberately uses a local,
artifact-only extraction root and copies only the frame-zero battle stills
needed by the Meshy-7 queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "tools/homm3_import/units_inventory.json"
MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
NEUTRAL = ROOT / "tools/homm3_import/faction_concepts/homm3_neutral.json"
EXTRACT_PROJECT = ROOT / "artifacts/neutral_extract_project"
STILLS = ROOT / "artifacts/meshy_remaining_stills"
EXTRACTOR = ROOT / "tools/homm3_import/extract_creature.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _neutral_missing() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_sids = {str(row["unitSid"]) for row in manifest.get("units", [])}
    neutral = json.loads(NEUTRAL.read_text(encoding="utf-8"))
    return [
        str(row["sid"])
        for row in neutral.get("units", [])
        if str(row["sid"]) not in manifest_sids
    ]


def _extract_one(sid: str) -> dict:
    cmd = [
        sys.executable,
        str(EXTRACTOR),
        "--inventory",
        str(INVENTORY),
        "--unit",
        sid,
        "--unity-project",
        str(EXTRACT_PROJECT),
    ]
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    source_root = EXTRACT_PROJECT / "Assets/CustomUnits/homm3_lab" / sid / "extracted_battle"
    source = next(iter(sorted(source_root.glob("**/00_00.png"))), None)
    if source is None:
        raise FileNotFoundError(f"frame-zero still not found for {sid} under {source_root}")
    STILLS.mkdir(parents=True, exist_ok=True)
    dest = STILLS / f"{sid}.png"
    shutil.copy2(source, dest)
    return {
        "unitSid": sid,
        "source": str(source.resolve()).replace("\\", "/"),
        "still": str(dest.resolve()).replace("\\", "/"),
        "sha256": _sha256(dest),
        "frame": "00_00",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", action="append", default=[], help="extract only this neutral unit (repeatable)")
    args = parser.parse_args()
    wanted = set(args.unit)
    sids = [sid for sid in _neutral_missing() if not wanted or sid in wanted]
    results = [_extract_one(sid) for sid in sids]
    report = {
        "schema": "homm3-neutral-mesh-inputs.v1",
        "proof": "generated artifact validated - extracted source still",
        "extractProject": str(EXTRACT_PROJECT.resolve()).replace("\\", "/"),
        "results": results,
    }
    out = STILLS / "neutral_extract_manifest.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "count": len(results), "out": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
