#!/usr/bin/env python3
"""Validate adventure-map building mesh catalog contracts.

When the mesh flag is conceptually on (catalog present), every generate=true
wired city/dwelling billboard path (including first-frame animated stacks) must
appear in the catalog under --require-complete; town_scene_refs and AVW paths
must never appear.

Facing: every catalog entry carries artYawDegrees equal to what
tools/homm3_map_building_meshes/map_building_facing.json says for its model's
front axis (+Z -> 0, -Z -> 180, +X -> 90, -X -> -90), every entry is in that census, and a local
model.glb whose byte size differs from the census fails (a regenerated Meshy
model must be re-inspected; the 2026-09-11 Meshy-7 Castle capitol came back
with its gate on -Z and stood backwards on the map).

Kind: every catalog row carries its own inventory row's ``kind``, and every
``*_city`` prefab is ``city`` (the Unity builder once read the next row's kind,
so each city was catalogued ``dwelling``).

Placement: the staged AssetBundle beside the catalog is read with UnityPy and
every prefab is measured in the pose the runtime renders
(``map_building_prefab_placement.py``: baked tip dropped, root scale kept).
The horizontal centre of its renderers' bounds must sit on the prefab origin,
which the runtime puts on the donor's footprint centre, within
``PLACEMENT_MAX_REL`` of the footprint. The 2026-09-29 playtest Factory city
sat 0.5 footprint (1.8 world units) off its town because the builder seated
model_anim.glb children in the tipped pose.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "homm3_map_building_meshes"))
import map_building_facing  # noqa: E402
import map_building_prefab_placement  # noqa: E402

# Good prefabs measure <= 0.0073 of their footprint (Meshy bbox-centred origins); the
# tipped-pose seating bug measured exactly 0.5.
PLACEMENT_MAX_REL = 0.02

MESHES_ROOT = ROOT / "artifacts" / "meshy_map_buildings" / "meshes"
DEFAULT_INVENTORY = ROOT / "artifacts" / "meshy_map_buildings" / "inventory.json"
DEFAULT_CATALOG = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_map_building_meshes"
    / "catalog.json"
)


def fail(msg: str) -> None:
    print(f"map-building-mesh-contract: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument(
        "--require-catalog",
        action="store_true",
        help="Fail if catalog is missing (use when mesh flag is enabled in deploy).",
    )
    ap.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail if any generate=true wired billboard is missing from the catalog.",
    )
    args = ap.parse_args()

    inv_path: Path = args.inventory if args.inventory.is_absolute() else ROOT / args.inventory
    cat_path: Path = args.catalog if args.catalog.is_absolute() else ROOT / args.catalog

    if not inv_path.is_file():
        fail(f"inventory missing: {inv_path}")
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    entries = inv.get("entries") or []
    generate = [e for e in entries if e.get("generate")]
    first_frame = [e for e in generate if e.get("firstFrameOnly") or e.get("animated")]

    if not cat_path.is_file():
        if args.require_catalog:
            fail(f"catalog missing: {cat_path}")
        print(
            json.dumps(
                {
                    "ok": True,
                    "catalogPresent": False,
                    "generateWired": len(generate),
                    "firstFrameFromAnimated": len(first_frame),
                    "note": "catalog optional until --require-catalog",
                },
                indent=2,
            )
        )
        return 0

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    if catalog.get("schema") != "homm3_map_building_mesh_catalog.v1":
        fail(f"bad catalog schema: {catalog.get('schema')}")
    by_png = {
        (e.get("relativePng") or "").replace("\\", "/").lower(): e
        for e in (catalog.get("entries") or [])
    }
    if not by_png:
        fail("catalog has no entries")

    for key, row in by_png.items():
        if "town_scene_refs" in key:
            fail(f"town_scene_refs leaked into catalog: {row.get('relativePng')}")
        leaf = Path(key).parent.name
        if leaf.startswith("avw"):
            fail(f"AVW path in catalog: {row.get('relativePng')}")

    try:
        facing = map_building_facing.load_facing()
    except map_building_facing.FacingError as ex:
        fail(str(ex))
    inv_by_key = {e.get("prefabKey"): e for e in entries}
    turned = []
    size_checked = 0
    for row in by_png.values():
        key = row.get("prefabKey")
        try:
            want = map_building_facing.expected_art_yaw(row, facing)
        except map_building_facing.FacingError as ex:
            fail(str(ex))
        got = row.get("artYawDegrees")
        if not isinstance(got, (int, float)) or abs(float(got) - want) > 1e-3:
            fail(
                f"{key}: catalog artYawDegrees={got!r}, facing census wants {want:g} "
                f"(front {facing[key]['frontAxis']}); run "
                "tools/homm3_map_building_meshes/map_building_facing.py stamp"
            )
        if want:
            turned.append(key)
        inv_row = inv_by_key.get(key)
        glb = MESHES_ROOT / inv_row["dir"] / "model.glb" if inv_row and inv_row.get("dir") else None
        if glb is not None and glb.is_file():
            size_checked += 1
            if glb.stat().st_size != facing[key]["glbBytes"]:
                fail(
                    f"{key}: model.glb is {glb.stat().st_size} bytes, facing census inspected "
                    f"{facing[key]['glbBytes']}; re-inspect its front axis (+Z/-Z/+X/-X) and update map_building_facing.json"
                )

    for row in by_png.values():
        key = row.get("prefabKey") or ""
        inv_row = inv_by_key.get(key)
        want_kind = inv_row.get("kind") if inv_row else None
        if want_kind and row.get("kind") != want_kind:
            fail(
                f"{key}: catalog kind={row.get('kind')!r}, inventory row says {want_kind!r} "
                "(rebuild with tools/homm3_import/build_homm3_map_building_meshes_bundle.py)"
            )
        if "_city__" in key and row.get("kind") != "city":
            fail(f"{key}: a *_city prefab must be kind 'city', catalog has {row.get('kind')!r}")

    bundle_path = cat_path.parent / (catalog.get("bundle") or "")
    if not catalog.get("bundle") or not bundle_path.is_file():
        fail(f"staged bundle missing beside the catalog: {bundle_path}")
    placement = map_building_prefab_placement.measure_bundle(bundle_path)
    worst = {"key": None, "offsetRel": 0.0}
    for row in by_png.values():
        key = row.get("prefabKey")
        m = placement.get(key)
        if not m or not m.get("renderers"):
            fail(f"{key}: prefab missing from {bundle_path.name} or has no MeshRenderer")
        if m["offsetRel"] > PLACEMENT_MAX_REL:
            fail(
                f"{key}: footprint centre sits {m['offsetRel']:.3f} of its footprint "
                f"({m['offsetWorld']:.3f} world units) off the prefab origin the runtime puts on the "
                f"donor's centre (centreXZ={m['centreXZ']}, baked root tip {m['bakedRootEuler']}); "
                "rebuild the bundle (children must be seated in the untipped runtime pose)"
            )
        if m["offsetRel"] >= worst["offsetRel"]:
            worst = {"key": key, "offsetRel": m["offsetRel"], "offsetWorld": m["offsetWorld"]}
    cities = {
        k: {"offsetWorld": v["offsetWorld"], "offsetRel": v["offsetRel"]}
        for k, v in sorted(placement.items())
        if "_city__" in k
    }

    missing = []
    for e in generate:
        key = (e.get("relativePng") or "").replace("\\", "/").lower()
        if key not in by_png:
            missing.append(e.get("relativePng"))
    if missing and args.require_complete:
        fail(
            "generate=true wired billboards missing from mesh catalog ("
            + str(len(missing))
            + "): "
            + ", ".join(missing[:8])
            + ("..." if len(missing) > 8 else "")
        )

    print(
        json.dumps(
            {
                "ok": True,
                "catalogPresent": True,
                "catalogEntries": len(by_png),
                "generateWired": len(generate),
                "firstFrameFromAnimated": len(first_frame),
                "missingGenerate": len(missing),
                "requireComplete": bool(args.require_complete),
                "facingTurnedOffPlusZ": sorted(turned),
                "facingGlbSizeChecked": size_checked,
                "placementMeasured": len(by_png),
                "placementMaxRel": PLACEMENT_MAX_REL,
                "placementWorst": worst,
                "cityPlacement": cities,
                "proof": (
                    "generated artifact validated — partial catalog OK; "
                    "missing generate paths keep PNG until Meshy completion"
                    if missing
                    else "generated artifact validated — complete generate=true wired catalog "
                    "(static + first-frame animated)"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
