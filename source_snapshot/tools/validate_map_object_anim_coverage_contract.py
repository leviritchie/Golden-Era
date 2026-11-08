#!/usr/bin/env python3
"""Contract: every HoMM3 adventure-map object that animates, and is placed on a translated map, has
an animation plan.

Inputs (tracked):
  tools/homm3_map_building_meshes/map_object_anim_census.json    every animated placed DEF (from the
      raw_translation placement ground truth; ``audit_map_object_animation.py census``)
  tools/homm3_map_building_meshes/map_object_anim_coverage.json  hand-audited plan per object
  tools/homm3_map_building_meshes/oe_native_prefab_anim.json     native prefab Animator/particle probe
      (``audit_map_object_animation.py probe-native``)
  tools/homm3_map_building_meshes/map_building_anim_inventory.json

Checks
  * every census DEF is assigned to exactly one coverage row, and no coverage row names a DEF the
    census does not have (a re-run census that finds a new animated object fails the build until
    it is audited);
  * frame counts in the coverage match the census;
  * every row has a lane from the allowed set, at least one moving part and a presentation;
  * ``inventory_row`` DEFs that are themselves inventory rows are animated there (the plan lives in
    map_building_anim_inventory.json);
  * ``native_covered`` rows name native prefabs whose probe shows an Animator or ParticleSystem -
    a native stand-in with neither is not "covered";
  * rows planned for an effect/bob lane on a native stand-in only when that stand-in is inert;
  * ``not_presented`` rows really draw nothing (presentation ``nothing`` or ``scenery_standin``).

Proof tier: generated artifact / source. It says what the translated maps present and what is
planned; it does not prove in-game playback.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "homm3_map_building_meshes"
CENSUS = TOOL / "map_object_anim_census.json"
COVERAGE = TOOL / "map_object_anim_coverage.json"
PROBE = TOOL / "oe_native_prefab_anim.json"
INVENTORY = TOOL / "map_building_anim_inventory.json"

LANES = {"inventory_row", "native_covered", "vanilla_style_effect", "rotor", "pendulum",
         "articulated_rigid", "bob", "creature_deferred", "not_presented"}
PRESENTATIONS = {"our_mesh", "our_mesh_or_billboard", "native_oe_object", "scenery_standin", "nothing"}


def main() -> int:
    errors: list[str] = []
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))["prefabs"]
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if census.get("schema") != "homm3_map_object_anim_census.v1":
        errors.append(f"census schema {census.get('schema')!r}")
    if cov.get("schema") != "homm3_map_object_anim_coverage.v1":
        errors.append(f"coverage schema {cov.get('schema')!r}")
    cen = {r["def"]: r for r in census["rows"]}
    inv_by_def = {r["def"].lower(): r for r in inv["rows"]}

    owner: dict[str, str] = {}
    lanes: dict[str, int] = {}
    for row in cov["rows"]:
        rid = row.get("id")
        lane = row.get("lane")
        lanes[lane] = lanes.get(lane, 0) + 1
        if lane not in LANES:
            errors.append(f"{rid}: lane {lane!r} not in {sorted(LANES)}")
        if row.get("presentation") not in PRESENTATIONS:
            errors.append(f"{rid}: presentation {row.get('presentation')!r} not in {sorted(PRESENTATIONS)}")
        if not row.get("defs"):
            errors.append(f"{rid}: no defs")
        if lane != "inventory_row" and not row.get("homm3MovingParts"):
            errors.append(f"{rid}: no homm3MovingParts")
        for d in row.get("defs", []):
            if d in owner:
                errors.append(f"{d}: assigned to both {owner[d]} and {rid}")
            owner[d] = rid
            c = cen.get(d)
            if c is None:
                errors.append(f"{rid}: {d} is not an animated placed DEF in the census")
                continue
            if (row.get("frames") or {}).get(d) != c["frames"]:
                errors.append(f"{rid}: {d} frames {(row.get('frames') or {}).get(d)} != census {c['frames']}")
            if lane == "inventory_row" and d in inv_by_def:
                ir = inv_by_def[d]
                if not ir.get("animated") or ir.get("status") not in ("delivered", "planned"):
                    errors.append(f"{rid}: {d} inventory row is not animated+planned/delivered")
        prefabs = row.get("nativePrefabPaths") or []
        animated_native = []
        for p in prefabs:
            rec = probe.get(p)
            if rec is None or rec.get("missing"):
                errors.append(f"{rid}: native prefab {p} missing from {PROBE.name} (re-run probe-native)")
                continue
            animated_native.append(bool(rec.get("animators")) or (rec.get("particleSystems") or 0) > 0)
        if lane == "native_covered":
            if row.get("presentation") != "native_oe_object" or not prefabs:
                errors.append(f"{rid}: native_covered needs presentation native_oe_object and nativePrefabPaths")
            elif not all(animated_native):
                errors.append(f"{rid}: native_covered but a stand-in prefab has no Animator and no ParticleSystem")
        if lane in ("vanilla_style_effect", "bob", "creature_deferred") and prefabs and any(animated_native):
            errors.append(f"{rid}: planned {lane} but the native stand-in already animates (use native_covered)")
        if lane == "not_presented" and row.get("presentation") not in ("nothing", "scenery_standin"):
            errors.append(f"{rid}: not_presented but presentation is {row.get('presentation')!r}")
    missing = sorted(set(cen) - set(owner))
    if missing:
        errors.append(f"animated placed DEF(s) with no coverage row (audit them): {missing}")

    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    if errors:
        return 1
    print(f"map object anim coverage OK: census animated DEFs={len(cen)} rows={len(cov['rows'])} "
          f"lanes={dict(sorted(lanes.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
