#!/usr/bin/env python3
"""Audit manifest units for Homm3BillboardAnimatorBuild ResolveMapFramesFolder requirements."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().parent / "homm3_units_manifest.json"
UNITY_LAB = Path(r"C:\Users\<user>\oldenera_factions\Assets\CustomUnits\homm3_lab")
OFFLINE_LAB = (
    REPO / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)


def main() -> int:
    m = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    units = [u["unitSid"].strip() for u in m.get("units", []) if u.get("unitSid")]

    no_authoring = []
    battle_map_path = []
    map_path_missing_folder = []
    map_dir_missing = []
    ok = []

    for sid in units:
        auth_path = None
        for root in (UNITY_LAB, OFFLINE_LAB):
            p = root / sid / "authoring.json"
            if p.is_file():
                auth_path = p
                break
        if not auth_path:
            no_authoring.append(sid)
            continue

        data = json.loads(auth_path.read_text(encoding="utf-8-sig"))
        mf = (data.get("mapFramesFolder") or "").replace("\\", "/").strip()
        if not mf:
            map_path_missing_folder.append((sid, "(empty mapFramesFolder)"))
            continue

        if "/extracted_map/" not in mf:
            battle_map_path.append((sid, mf))
            continue

        # Path must exist under Unity lab (batch runs against Unity project).
        rel = mf
        prefix = "Assets/CustomUnits/homm3_lab/"
        if rel.startswith(prefix):
            rel = rel[len(prefix) :]
        folder = UNITY_LAB / rel.replace("/", "\\")
        if not folder.is_dir():
            map_path_missing_folder.append((sid, mf))
            continue

        ok.append(sid)

    if not (UNITY_LAB.parent).is_dir():
        print("WARN: Unity lab not found:", UNITY_LAB, file=sys.stderr)

    for sid in units:
        if not (UNITY_LAB / sid / "extracted_map").is_dir():
            map_dir_missing.append(sid)

    fail = {s for s, _ in battle_map_path} | {s for s, _ in map_path_missing_folder} | set(no_authoring)

    print(f"Manifest units: {len(units)}")
    print(f"Would pass ResolveMapFramesFolder: {len(ok)}")
    print(f"Unity lab missing extracted_map/ (any): {len(map_dir_missing)}")
    print()
    print(f"FAIL — mapFramesFolder uses battle (no /extracted_map/): {len(battle_map_path)}")
    for sid, mf in battle_map_path:
        print(f"  {sid}\n    {mf}")
    print()
    print(f"FAIL — /extracted_map/ path but folder missing in Unity: {len(map_path_missing_folder)}")
    for sid, mf in map_path_missing_folder:
        print(f"  {sid}\n    {mf}")
    print()
    print(f"FAIL — no authoring.json: {len(no_authoring)}")
    for sid in no_authoring:
        print(f"  {sid}")
    print()
    print(f"Total distinct units that would fail batch: {len(fail)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
