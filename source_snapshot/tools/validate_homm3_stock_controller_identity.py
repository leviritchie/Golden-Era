#!/usr/bin/env python3
"""Gate: owned skinned override controllers resolve one stock base, and stock controller GUIDs are unique.

Every owned skinned AnimatorOverrideController (AOC) serializes its base as
`m_Controller: {fileID: 9100000, guid: <G>, type: 2}`. Unity resolves <G> through the `.meta` files. When two
`.meta` files declare the same GUID (the Crusader stock copy once repeated esquire's `dcc84d...`), Unity's
AssetDatabase gives neither file that GUID, every AOC serializing it loads with a null base and zero override
pairs, and a bundle rebuilt from it ships a unit with no animation. This gate reads only the named files (no
project scan):

  * the esquire and Crusader stock controller `.meta` files and every manifest unit's own
    `Reference/StockEsquireBattle.controller.meta` (lab root and `OwnedSkinned/`) must declare distinct GUIDs;
  * each manifest skinned unit that has an AOC must name, as its base, a GUID declared by exactly one of those
    stock controller `.meta` files, with fileID 9100000;
  * each AOC override clip must be a GUID declared by a `.anim.meta` in that unit's own `Animations/` folder.

Wired into the bundle stage of tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py and the attack-slot
remap driver (tools/homm3_import/remap_owned_attack_slots.py). Unity-side proof that the bases load non-null lives in Homm3StockControllerIdentityAudit.cs. Static
(project file) proof only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = Path("V:/homm3_unity_work")
DEFAULT_MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
STOCK_NAME = "StockEsquireBattle.controller"
DONORS = (
    "Assets/CustomUnits/esquire/Reference/" + STOCK_NAME,
    "Assets/CustomUnits/homm3_lab/h3_crusader/Reference/" + STOCK_NAME,
)
CONTROLLER_FILE_ID = "9100000"
GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})\s*$", re.M)
BASE_RE = re.compile(r"^  m_Controller: \{fileID: (-?\d+), guid: ([0-9a-f]{32}), type: \d+\}\s*$", re.M)
OVERRIDE_RE = re.compile(r"m_OverrideClip: \{fileID: (-?\d+)(?:, guid: ([0-9a-f]{32}), type: \d+)?\}")


def meta_guid(path: Path) -> str | None:
    if not path.is_file():
        return None
    match = GUID_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def check(project: Path, manifest: Path, units_filter: set[str] | None = None) -> tuple[list[str], dict]:
    errors: list[str] = []
    rows = json.loads(manifest.read_text(encoding="utf-8-sig"))["units"]
    skinned = [r for r in rows if str(r.get("battlePrefabAsset", "")).endswith("owned_skinned.prefab")]
    if units_filter is not None:
        unknown = units_filter - {r["unitSid"] for r in skinned}
        if unknown:
            errors.append("requested unit(s) are not manifest skinned rows: " + ", ".join(sorted(unknown)))
        skinned = [r for r in skinned if r["unitSid"] in units_filter]

    # GUID registry of every stock controller copy this gate is allowed to resolve against.
    declared: dict[str, list[str]] = defaultdict(list)
    stock_paths: list[str] = list(DONORS)
    for row in rows:
        if not str(row.get("battlePrefabAsset", "")).endswith("owned_skinned.prefab"):
            continue
        root = row["battlePrefabAsset"].rsplit("/", 1)[0]
        stock_paths.append(root + "/Reference/" + STOCK_NAME)
        stock_paths.append(root.rsplit("/", 1)[0] + "/Reference/" + STOCK_NAME)
    for rel in dict.fromkeys(stock_paths):
        guid = meta_guid(project / (rel + ".meta"))
        if guid is None:
            if rel in DONORS:
                errors.append(f"stock donor {rel}: missing .meta or GUID")
            continue
        if not (project / rel).is_file():
            errors.append(f"{rel}.meta declares {guid} but the controller file is missing")
        declared[guid].append(rel)
    for guid, paths in declared.items():
        if len(paths) > 1:
            errors.append(f"stock controller GUID {guid} is declared by {len(paths)} .meta files "
                          f"({', '.join(paths)}); Unity will resolve it to none of them")

    cohorts: dict[str, int] = defaultdict(int)
    checked = 0
    for row in skinned:
        sid = row["unitSid"]
        root = row["battlePrefabAsset"].rsplit("/", 1)[0]
        aoc = next((project / root / n for n in ("owned_skinned.overrideController",
                                                   "crusader_owned_skinned.overrideController")
                    if (project / root / n).is_file()), None)
        if aoc is None:
            if (project / row["battlePrefabAsset"]).is_file():
                errors.append(f"{sid}: prefab exists but no override controller under {root}")
            continue
        checked += 1
        text = aoc.read_text(encoding="utf-8", errors="replace")
        base = BASE_RE.search(text)
        if not base:
            errors.append(f"{sid}: {aoc.name} has no serialized m_Controller base")
            continue
        file_id, guid = base.groups()
        owners = declared.get(guid, [])
        if file_id != CONTROLLER_FILE_ID or len(owners) != 1:
            errors.append(f"{sid}: base {{fileID {file_id}, guid {guid}}} resolves to "
                          f"{len(owners)} stock controller(s) {owners}")
            continue
        cohorts[owners[0]] += 1
        anim_dir = project / root / "Animations"
        clip_guids = {meta_guid(p) for p in anim_dir.glob("*.anim.meta")} if anim_dir.is_dir() else set()
        for fid, cguid in OVERRIDE_RE.findall(text):
            if fid == "0" and not cguid:
                continue  # an unset override keeps the stock clip
            if cguid not in clip_guids:
                errors.append(f"{sid}: override clip guid {cguid} is not an .anim in {root}/Animations")
                break
    if checked == 0:
        errors.append("no owned skinned override controllers found; wrong --project?")
    return errors, {"checked": checked, "cohorts": dict(cohorts),
                    "stockGuids": {g: p for g, p in declared.items() if len(p) == 1 and p[0] in DONORS}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--unit", action="append", help="limit AOC checks to these manifest unitSids (registry is always full)")
    args = ap.parse_args()
    errors, summary = check(args.project, args.manifest, set(args.unit) if args.unit else None)
    for e in errors:
        print("ERROR: " + e)
    print(("FAIL" if errors else "OK") + f": stock controller identity ({summary['checked']} AOC(s); cohorts "
          + json.dumps(summary["cohorts"]) + f"; {len(errors)} error(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
