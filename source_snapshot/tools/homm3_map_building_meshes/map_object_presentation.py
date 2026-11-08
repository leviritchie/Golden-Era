#!/usr/bin/env python3
"""Presentation census: which placed HoMM3 map objects the translated maps draw nothing for.

``census`` aggregates every placement in the raw_translation ``*placement_ground_truth.json`` files
and writes ``map_object_presentation_census.json`` (tracked, small). Per HoMM3 object id it records
the placement count by emit status, and for every placement that draws nothing:

  * ``blocked_by_substitution`` - the substitution map returned no Olden Era SID, so nothing is
    emitted. The object's HoMM3 non-visit block cells are still sealed by the invisible
    ``homm3_pathing_blocker`` gap fill, so passability survives but the object is invisible and
    its function is gone;
  * ``missing_from_emit`` / ``fer_omitted`` / ``approach_cleared`` - deliberately or accidentally
    removed after substitution (normally scenery);
  * an emitted SID in ``INVISIBLE_SIDS`` (a stand-in with no visible prefab).

A placement with a ``visualBillboard`` host (raw_translation/object_billboards.py: the HoMM3 DEF
drawn as a sprite on an inert host, no function) counts as drawn and is tallied per object as
``visualBillboardPlacements``.

``tools/validate_map_object_presentation_contract.py`` checks this census against the hand-written
``map_object_presentation_ledger.json``: every object id that draws nothing must have a ledger row
with its cause and status, so a new silent drop fails the OfflineUnlockMod build.

Proof tier of the output: generated artifact (placement ground truth of the last raw_translation
emit). It says nothing about maps that have not been regenerated since.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
ROOT = TOOL_DIR.parents[1]
CENSUS = TOOL_DIR / "map_object_presentation_census.json"
LEDGER = TOOL_DIR / "map_object_presentation_ledger.json"
GROUND_TRUTH_GLOBS = [
    "artifacts/campaign_port_poc/*/*/raw_translation_map/*placement_ground_truth.json",
    "artifacts/campaign_port_poc/*/raw_translation_map/*placement_ground_truth.json",
]
CORE_CATALOG = ROOT / "artifacts" / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"

NOT_DRAWN_STATUSES = ("blocked_by_substitution", "missing_from_emit", "fer_omitted", "approach_cleared")
# Emitted stand-ins with no visible prefab. The gap-fill blocker is appended by the emitter and is
# not a placement, so a placement mapped to one of these is a silent draw-nothing.
# campaign_FX_block is not listed: its Core prefab is fx/fx_map_smoke (visible smoke). It is the
# border key-gate block (raw_translation/border_guard_gates.py); homm3_pathing_blocker is the
# invisible custom clone of it.
INVISIBLE_SIDS = frozenset({"homm3_pathing_blocker", "block", "block_2", "block_campaign"})


def ground_truth_files() -> list[str]:
    return sorted({f for g in GROUND_TRUTH_GLOBS for f in glob.glob(str(ROOT / g))})


def environment_sids() -> set[str]:
    """Non-interactive Core scenery SIDs (removing one for an approach is deliberate)."""
    cat = json.loads(CORE_CATALOG.read_text(encoding="utf-8"))
    return {r["id"] for r in cat.get("mapObjects", [])
            if isinstance(r, dict) and r.get("tag") == "Environment" and not r.get("isInteractable")}


def cmd_census(_args) -> int:
    files = ground_truth_files()
    if not files:
        raise SystemExit("no placement ground-truth files found; run the raw_translation map pipeline first")
    scenery = environment_sids()
    agg: dict[int, dict] = {}
    for f in files:
        mission = Path(f).parent.parent.name
        for p in json.loads(Path(f).read_text(encoding="utf-8"))["placements"]:
            h = p.get("h3") or {}
            tid = h.get("templateObjectId")
            if not isinstance(tid, int):
                continue
            status = str(p.get("emitStatus"))
            mapping = p.get("mapping") or {}
            sid = mapping.get("replacementSid")
            a = agg.setdefault(tid, {"placements": 0, "status": collections.Counter(),
                                     "notDrawn": collections.Counter(), "notDrawnDefs": collections.Counter(),
                                     "notDrawnRules": collections.Counter(), "missions": set(),
                                     "emittedSids": collections.Counter(), "billboards": 0})
            a["placements"] += 1
            a["status"][status] += 1
            if status.startswith("emitted") and sid:
                a["emittedSids"][sid] += 1
            not_drawn = None
            if p.get("visualBillboard"):
                a["billboards"] += 1
            elif status == "blocked_by_substitution":
                not_drawn = status
            elif status in NOT_DRAWN_STATUSES and sid not in scenery:
                not_drawn = status  # a removed non-scenery object
            elif status.startswith("emitted") and sid in INVISIBLE_SIDS:
                not_drawn = f"invisible_sid:{sid}"
            if not_drawn:
                a["notDrawn"][not_drawn] += 1
                a["notDrawnDefs"][str(h.get("templateAnimation") or "").lower()] += 1
                a["notDrawnRules"][str(mapping.get("ruleName"))] += 1
                a["missions"].add(mission)
    rows = []
    for tid in sorted(agg):
        a = agg[tid]
        row = {"objectId": tid, "placements": a["placements"], "status": dict(a["status"].most_common())}
        if a["notDrawn"]:
            row.update({
                "notDrawn": dict(a["notDrawn"].most_common()),
                "notDrawnPlacements": sum(a["notDrawn"].values()),
                "notDrawnMissions": len(a["missions"]),
                "notDrawnDefs": dict(a["notDrawnDefs"].most_common()),
                "notDrawnRules": dict(a["notDrawnRules"].most_common()),
            })
        if a["billboards"]:
            row["visualBillboardPlacements"] = a["billboards"]
        row["emittedSids"] = dict(a["emittedSids"].most_common(8))
        rows.append(row)
    doc = {
        "schema": "homm3_map_object_presentation_census.v1",
        "generator": "tools/homm3_map_building_meshes/map_object_presentation.py census",
        "source": f"{len(files)} raw_translation placement_ground_truth files",
        "notDrawnStatuses": list(NOT_DRAWN_STATUSES),
        "invisibleSids": sorted(INVISIBLE_SIDS),
        "counts": {
            "objectIds": len(rows),
            "notDrawnObjectIds": sum(1 for r in rows if r.get("notDrawn")),
            "notDrawnPlacements": sum(r.get("notDrawnPlacements", 0) for r in rows),
            "visualBillboardPlacements": sum(r.get("visualBillboardPlacements", 0) for r in rows),
        },
        "rows": rows,
    }
    CENSUS.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {CENSUS} {doc['counts']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("census", help="write map_object_presentation_census.json from placement ground truth")
    args = ap.parse_args()
    return {"census": cmd_census}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
