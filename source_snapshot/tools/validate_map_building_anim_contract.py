#!/usr/bin/env python3
"""Contract: every adventure-map building DEF that animates ships its animation data, or is
explicitly planned with a lane and reason.

Inputs (all tracked or staged into the plugin):
  tools/homm3_map_building_meshes/map_building_anim_inventory.json   (per-DEF motion inventory)
  tools/homm3_map_building_meshes/map_building_anim_spec.json        (rows the build delivers)
  OfflineUnlockMod/homm3_map_building_meshes/anim/catalog.json       (runtime animation catalog)
  OfflineUnlockMod/homm3_map_building_meshes/catalog.json            (Unity-built mesh catalog)

Checks
  * every inventory row with ``animated: true`` is ``delivered`` or ``planned`` (planned rows carry
    a lane from the allowed set and a reason) and lists its independent moving parts
    (``motionParts``), each with a lane; no row is newly planned as a DEF ``flipbook``;
  * delivered rows == spec rows == runtime catalog rows (same lane, no strays);
  * billboard_frames rows: one PNG per DEF frame, all present, all the same size;
  * HoMM3 sprite flipbooks are retired (user, 2026-09-26): no lane ``flipbook`` anywhere and no
    ``flipbooks`` key in the spec or runtime catalog;
  * effects (lane ``vanilla_style_effect``, or ``effects`` on a rotor row): every effect anchor is baked
    into the prefab (mesh catalog ``animAnchorPaths``), its kind is an effect part of the DEF, every
    effect part of a delivered mesh row is delivered by an effect of that kind, and
    ``map_building_fx.py check`` proves the homm3_mesh_fx rows are exactly the compiled effects (vanilla
    map-object systems only, magic/VfxUber, one row per effect); each row's ``prefabKeyContains`` matches
    exactly one mesh-catalog prefab;
  * rotor rows: every pivot is in the mesh catalog's ``animRotorPaths`` for that prefab (proves the
    bundle was rebuilt from ``model_anim.glb`` and carries the Animator clip), period > 0;
  * pendulum / articulated_rigid rows (parts cut from the shipped mesh, keyed clip): every part
    pivot is in the mesh catalog's ``animPartPaths``, parents precede children, and all parts share
    one loop equal to the DEF loop (frames x frameMs).

Proof tier: generated-artifact / staged payload. It does not prove in-game playback.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
INVENTORY = ROOT / "tools" / "homm3_map_building_meshes" / "map_building_anim_inventory.json"
SPEC = ROOT / "tools" / "homm3_map_building_meshes" / "map_building_anim_spec.json"
ANIM_DIR = PLUGIN / "homm3_map_building_meshes" / "anim"
ANIM_CATALOG = ANIM_DIR / "catalog.json"
MESH_CATALOG = PLUGIN / "homm3_map_building_meshes" / "catalog.json"

# Delivery lanes. ``pendulum`` (a hinged swinging part) and ``vanilla_style_effect`` (smoke/fire/
# glow/water in the vanilla Olden Era style) were added by the 2026-09-26 re-audit
# (docs/homm3_map_object_animation_audit.md). ``flipbook`` stays valid only for rows already
# delivered: the user rejected HoMM3 sprite flipbooks on flat panels, so no row may be *planned* as one.
LANES = {"rotor", "billboard_frames", "articulated_rigid", "pendulum", "vanilla_style_effect"}
PART_LANES = {"rotor", "pendulum", "articulated_rigid", "vanilla_style_effect"}
RETIRED_LANES = {"flipbook"}
EFFECT_LANE = "vanilla_style_effect"
EFFECT_KINDS = {"smoke", "fire", "glow_pulse", "glow_particles", "water"}
ANCHOR_PREFIX = "HOMM3_anim_anchor_"
FX_TOOL = ROOT / "tools" / "homm3_map_building_meshes"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    errors: list[str] = []

    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if inv.get("schema") != "homm3_map_building_anim_inventory.v1":
        errors.append(f"inventory schema {inv.get('schema')!r}")
    spec = {r["relativePng"]: r for r in json.loads(SPEC.read_text(encoding="utf-8"))["rows"]}
    if not ANIM_CATALOG.is_file():
        errors.append(f"missing runtime catalog {ANIM_CATALOG}")
        return report(errors)
    cat = json.loads(ANIM_CATALOG.read_text(encoding="utf-8"))
    if cat.get("schema") != "homm3_map_building_anim.v1":
        errors.append(f"anim catalog schema {cat.get('schema')!r}")
    cat_rows = {r["relativePng"]: r for r in cat.get("entries", [])}
    if cat.get("entryCount") != len(cat_rows):
        errors.append("anim catalog entryCount does not match entries")
    mesh_cat = {r["prefabKey"]: r for r in json.loads(MESH_CATALOG.read_text(encoding="utf-8"))["entries"]}

    delivered = {}
    animated = 0
    for r in inv["rows"]:
        rel = r["relativePng"]
        if not r.get("animated"):
            if r.get("status") != "static":
                errors.append(f"{rel}: non-animated row must be status=static")
            continue
        animated += 1
        status = r.get("status")
        lane = r.get("lane")
        if lane not in LANES:
            errors.append(f"{rel}: animated row lane {lane!r} not in {sorted(LANES)}")
        if not r.get("motionKind"):
            errors.append(f"{rel}: animated row has no motionKind")
        parts = r.get("motionParts") or []
        if not parts:
            errors.append(f"{rel}: animated row has no motionParts (one entry per independent moving part)")
        for i, part in enumerate(parts):
            if part.get("lane") not in PART_LANES:
                errors.append(f"{rel}: motion part {i} lane {part.get('lane')!r} not in {sorted(PART_LANES)}")
            if not part.get("note"):
                errors.append(f"{rel}: motion part {i} has no note")
        if lane in RETIRED_LANES:
            errors.append(f"{rel}: lane {lane!r} is retired; effects use vanilla_style_effect, not DEF flipbooks")
        if status == "planned":
            if not r.get("plannedReason"):
                errors.append(f"{rel}: planned row without plannedReason")
            if rel in cat_rows:
                errors.append(f"{rel}: planned in inventory but present in the runtime catalog (re-run inventory)")
        elif status == "delivered":
            delivered[rel] = r
        else:
            errors.append(f"{rel}: animated row status {status!r} (want delivered or planned)")
    if set(delivered) != set(spec):
        errors.append(f"delivered rows {sorted(set(delivered) ^ set(spec))} differ between inventory and spec")
    if set(cat_rows) != set(delivered):
        errors.append(f"runtime catalog rows {sorted(set(cat_rows) ^ set(delivered))} differ from delivered inventory rows")

    for rel, row in list(spec.items()) + list(cat_rows.items()):
        if row.get("lane") in RETIRED_LANES or "flipbooks" in row:
            errors.append(f"{rel}: retired HoMM3 sprite flipbook in the spec/catalog")

    for rel, r in delivered.items():
        c = cat_rows.get(rel)
        if c is None:
            continue
        lane = r["lane"]
        if c.get("lane") != lane or spec.get(rel, {}).get("lane") != lane:
            errors.append(f"{rel}: lane mismatch inventory={lane} catalog={c.get('lane')} spec={spec.get(rel, {}).get('lane')}")
            continue
        if not (c.get("frameMs") or 0) > 0:
            errors.append(f"{rel}: frameMs must be > 0")
        if lane == "billboard_frames":
            check_frames(rel, c.get("frames") or [], r["frames"], errors, same_size=True)
            continue
        mc = mesh_cat.get(c.get("prefabKey") or "")
        if mc is None:
            errors.append(f"{rel}: prefab {c.get('prefabKey')!r} not in the mesh catalog")
            continue
        if mc.get("animLane") != lane:
            errors.append(f"{rel}: mesh catalog animLane={mc.get('animLane')!r} (want {lane!r}) - "
                          "rebuild homm3_map_building_meshes from model_anim.glb")
            continue
        check_effects(rel, r, c, mc, errors)
        if lane == EFFECT_LANE:
            if not c.get("effects"):
                errors.append(f"{rel}: {EFFECT_LANE} row without effects")
        elif lane == "rotor":
            pivots = {p.rsplit("/", 1)[-1] for p in mc.get("animRotorPaths") or []}
            rotors = c.get("rotors") or []
            if not rotors:
                errors.append(f"{rel}: rotor row without rotors")
            for i, ro in enumerate(rotors):
                if ro.get("pivot") not in pivots:
                    errors.append(f"{rel}: rotor {i} pivot {ro.get('pivot')!r} not baked into the prefab {sorted(pivots)}")
                if not (ro.get("periodSeconds") or 0) > 0:
                    errors.append(f"{rel}: rotor {i} periodSeconds must be > 0")
        elif lane in ("pendulum", "articulated_rigid"):
            pivots = {p.rsplit("/", 1)[-1] for p in mc.get("animPartPaths") or []}
            parts = c.get("parts") or []
            if not parts:
                errors.append(f"{rel}: {lane} row without parts")
            loops = {pt.get("loopSeconds") for pt in parts}
            if len(loops) > 1:
                errors.append(f"{rel}: parts disagree on loopSeconds {sorted(loops)} (one clip per prefab)")
            for i, pt in enumerate(parts):
                if pt.get("pivot") not in pivots:
                    errors.append(f"{rel}: part {i} pivot {pt.get('pivot')!r} not baked into the prefab {sorted(pivots)}")
                if not (pt.get("loopSeconds") or 0) > 0:
                    errors.append(f"{rel}: part {i} loopSeconds must be > 0")
                par = pt.get("parent", -1)
                if not isinstance(par, int) or par >= i or par < -1:
                    errors.append(f"{rel}: part {i} parent {par!r} must be -1 or an earlier part")
            # The keyed loop is the DEF loop: one clip period == DEF frames x frameMs.
            if parts and abs(parts[0]["loopSeconds"] - r["frames"] * c["frameMs"] / 1000.0) > 1e-3:
                errors.append(f"{rel}: loopSeconds {parts[0]['loopSeconds']} != DEF frames {r['frames']} x frameMs")

    # Mesh catalog must not claim animation the runtime catalog does not deliver.
    cat_by_prefab = {r.get("prefabKey"): r for r in cat_rows.values() if r.get("prefabKey")}
    for key, mc in mesh_cat.items():
        if mc.get("animLane") and key not in cat_by_prefab:
            errors.append(f"mesh catalog prefab {key} has animLane={mc['animLane']!r} but no runtime anim row")

    check_fx_rows(cat_rows, mesh_cat, errors)

    if not errors:
        print(f"map building anim contract OK: animated={animated} delivered={len(delivered)} "
              f"planned={animated - len(delivered)}")
    return report(errors)


def check_effects(rel, inv_row, c, mc, errors) -> None:
    """Vanilla-style effects of a delivered mesh row: anchors baked, kinds match the DEF, parts all delivered."""
    effects = c.get("effects") or []
    if effects and c.get("lane") not in (EFFECT_LANE, "rotor"):
        errors.append(f"{rel}: effects on lane {c.get('lane')!r} (only {EFFECT_LANE} and rotor rows carry effects)")
    anchors = {p.rsplit("/", 1)[-1] for p in mc.get("animAnchorPaths") or []}
    part_kinds = {p.get("kind") for p in inv_row.get("motionParts") or []}
    ids = set()
    for fx in effects:
        fid = fx.get("id")
        if fid in ids:
            errors.append(f"{rel}: duplicate effect id {fid!r}")
        ids.add(fid)
        if fx.get("anchor") != ANCHOR_PREFIX + str(fid):
            errors.append(f"{rel}: effect {fid!r} anchor {fx.get('anchor')!r} is not {ANCHOR_PREFIX}{fid}")
        if fx.get("anchor") not in anchors:
            errors.append(f"{rel}: effect anchor {fx.get('anchor')!r} not baked into the prefab {sorted(anchors)} - "
                          "rebuild homm3_map_building_meshes from model_anim.glb")
        if fx.get("kind") not in EFFECT_KINDS or fx.get("kind") not in part_kinds:
            errors.append(f"{rel}: effect {fid!r} kind {fx.get('kind')!r} is not an effect part of this DEF")
        if not (isinstance(fx.get("scale"), (int, float)) and 0 < fx["scale"] <= 4):
            errors.append(f"{rel}: effect {fid!r} scale {fx.get('scale')!r} outside (0, 4]")
    for i, part in enumerate(inv_row.get("motionParts") or []):
        if part.get("kind") in EFFECT_KINDS and part.get("status") != "delivered":
            errors.append(f"{rel}: effect part {i} ({part.get('kind')}) of a delivered mesh row is not delivered "
                          "(add a vanilla-style effect of that kind, or record the gap)")


def check_fx_rows(cat_rows, mesh_cat, errors) -> None:
    """homm3_mesh_fx map rows are exactly the compiled effects, each matching exactly one mesh prefab."""
    sys.path.insert(0, str(FX_TOOL))
    try:
        import map_building_fx as MBF
        n = MBF.check()
    except Exception as ex:  # FxError / VsError / schema errors all fail the contract
        errors.append(f"map_building_fx check: {ex}")
        return
    want = sum(len(c.get("effects") or []) for c in cat_rows.values())
    if n != want:
        errors.append(f"map_building_fx rows {n} != catalog effects {want}")
    fx_cat = json.loads(MBF.FX_CATALOG.read_text(encoding="utf-8"))
    for row in fx_cat["entries"]:
        if row.get("lane") != "map_building":
            continue
        needle = ((row.get("match") or {}).get("prefabKeyContains") or "").lower()
        hits = [k for k in mesh_cat if needle and needle in k.lower()]
        if len(hits) != 1:
            errors.append(f"mesh-fx row {row.get('id')}: prefabKeyContains {needle!r} matches {len(hits)} mesh prefabs {hits[:4]}")


def check_frames(label, frames, expected, errors, same_size):
    if len(frames) != expected:
        errors.append(f"{label}: {len(frames)} frame file(s) but the DEF has {expected}")
    sizes = set()
    for f in frames:
        p = ANIM_DIR / f
        if not p.is_file():
            errors.append(f"{label}: missing frame {p}")
            continue
        with Image.open(p) as im:
            sizes.add(im.size)
    if same_size and len(sizes) > 1:
        errors.append(f"{label}: frames differ in size {sorted(sizes)}")


def report(errors) -> int:
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
