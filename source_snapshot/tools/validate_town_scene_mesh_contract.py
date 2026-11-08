#!/usr/bin/env python3
"""Validate interior town-scene mesh catalog contracts (Factory town-hall pilot)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "artifacts" / "meshy_town_scene_meshes" / "inventory.json"
DEFAULT_CATALOG = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_town_scene_meshes"
    / "catalog.json"
)
PLUGIN_CONFIG = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "config.json"
)


def fail(msg: str) -> None:
    print(f"town-scene-mesh-contract: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument(
        "--require-catalog",
        action="store_true",
        help="Fail if catalog is missing (use when mesh flag is enabled).",
    )
    args = ap.parse_args()

    inv_path: Path = args.inventory if args.inventory.is_absolute() else ROOT / args.inventory
    cat_path: Path = args.catalog if args.catalog.is_absolute() else ROOT / args.catalog

    if not inv_path.is_file():
        fail(f"inventory missing: {inv_path}")
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    if inv.get("schema") != "homm3_town_scene_mesh_inventory.v1":
        fail(f"bad inventory schema: {inv.get('schema')}")
    # Backdrop rows are generation experiments (the meshy-6 full-plate backdrop was judged poor and is
    # not bundled); only building rows are catalog/bundle contracts.
    generate = [
        e for e in (inv.get("entries") or [])
        if e.get("generate") and str(e.get("kind") or "") != "backdrop"
    ]
    if not generate:
        fail("inventory has no generate=true building entries")

    for e in generate:
        for req in ("relativePng", "prefabKey", "dir", "layerId", "buildingSid", "fraction"):
            if not e.get(req):
                fail(f"inventory entry missing {req}: {e}")
        rel = str(e["relativePng"]).replace("\\", "/")
        if "town_scene_refs" not in rel:
            fail(f"town-scene inventory must use town_scene_refs paths, got {rel}")
        if e.get("buildingSid") == "Build_Main" and e.get("layerId") != "tbfahall" and e.get("nativeLevel") == 1:
            fail("Factory Build_Main level 1 must map to tbfahall for the locked pilot")

    flag_on = False
    if PLUGIN_CONFIG.is_file():
        cfg = json.loads(PLUGIN_CONFIG.read_text(encoding="utf-8"))
        flag_on = bool(cfg.get("homm3TownSceneMeshes"))

    if not cat_path.is_file():
        if args.require_catalog or flag_on:
            fail(f"catalog missing while required/flag-on: {cat_path}")
        print(json.dumps({"ok": True, "catalogPresent": False, "generate": len(generate)}, indent=2))
        return 0

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    if catalog.get("schema") != "homm3_town_scene_mesh_catalog.v1":
        fail(f"bad catalog schema: {catalog.get('schema')}")
    by_layer = {
        str(e.get("layerId") or "").strip(): e for e in (catalog.get("entries") or []) if e.get("layerId")
    }
    for e in generate:
        layer = e["layerId"]
        if layer not in by_layer:
            fail(f"catalog missing inventory layer {layer}")
        row = by_layer[layer]
        for field in ("buildingSid", "fraction", "prefabKey"):
            if str(row.get(field) or "") != str(e.get(field) or ""):
                fail(f"catalog/{field} mismatch for {layer}: {row.get(field)!r} vs {e.get(field)!r}")
        if float(row.get("stageDepthFromBackdrop") or 0) <= 0:
            fail(f"catalog stageDepthFromBackdrop must be > 0 for {layer}")

    bundle = cat_path.parent / "homm3_town_scene_meshes"
    if not bundle.is_file() or bundle.stat().st_size < 1000:
        fail(f"bundle missing/empty beside catalog: {bundle}")

    print(
        json.dumps(
            {
                "ok": True,
                "catalogPresent": True,
                "generate": len(generate),
                "catalogEntries": len(by_layer),
                "flagOn": flag_on,
                "proof": "generated artifact / staged payload validated — not OE town runtime proven",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
