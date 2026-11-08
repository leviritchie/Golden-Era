#!/usr/bin/env python3
"""Validate adventure-map artifact mesh catalog contracts.

When the mesh flag is conceptually on (catalog present), every generate=true
artifact map billboard path (including first-frame animated stacks) must
appear in the catalog under --require-complete; only artifacts/map paths; refuse map_object_refs / town_scene_refs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "artifacts" / "meshy_artifacts" / "inventory.json"
DEFAULT_CATALOG = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_artifact_meshes"
    / "catalog.json"
)


def fail(msg: str) -> None:
    print(f"artifact-mesh-contract: {msg}", file=sys.stderr)
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
        help="Fail if any generate=true artifact billboard is missing from the catalog.",
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
    if catalog.get("schema") != "homm3_artifact_mesh_catalog.v1":
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
        if "map_object_refs" in key:
            fail(f"map_object_refs leaked into artifact catalog: {row.get('relativePng')}")
        if "artifacts/map/" not in key:
            fail(f"artifact catalog entry outside artifacts/map: {row.get('relativePng')}")

    missing = []
    for e in generate:
        key = (e.get("relativePng") or "").replace("\\", "/").lower()
        if key not in by_png:
            missing.append(e.get("relativePng"))
    if missing and args.require_complete:
        fail(
            "generate=true artifact billboards missing from mesh catalog ("
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
