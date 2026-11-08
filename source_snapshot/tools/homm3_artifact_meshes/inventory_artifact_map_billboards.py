#!/usr/bin/env python3
"""Inventory HoMM3 adventure-map artifact AVA frames for Meshy meshes.

Source of truth: OfflineUnlockMod/homm3_runtime_assets/artifacts/map/homm3_artifact_*/00_00.png
Never inventories icons/, seer hut, or map_object_refs buildings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
ARTIFACT_MAP = PLUGIN / "homm3_runtime_assets" / "artifacts" / "map"
DEFAULT_OUT = ROOT / "artifacts" / "meshy_artifacts" / "inventory.json"
# Matches Homm3ArtifactMapBillboard.BillboardHeight (non-seer).
DEFAULT_TARGET_HEIGHT = 0.90


def fail(msg: str) -> None:
    print(f"inventory-artifact-map-billboards: {msg}", file=sys.stderr)
    raise SystemExit(1)


def prefab_key(dir_name: str) -> str:
    raw = f"map_mesh_artifact__{dir_name}".lower()
    return re.sub(r"[^a-z0-9_]+", "_", raw)


def build_inventory() -> dict:
    if not ARTIFACT_MAP.is_dir():
        fail(f"missing artifact map folder: {ARTIFACT_MAP}")

    entries: list[dict] = []
    for d in sorted(ARTIFACT_MAP.iterdir()):
        if not d.is_dir() or not d.name.startswith("homm3_artifact_"):
            continue
        png = d / "00_00.png"
        if not png.is_file():
            fail(f"missing 00_00.png under {d}")
        frames = len(list(d.glob("*.png")))
        rel = d.relative_to(PLUGIN / "homm3_runtime_assets").as_posix()
        # relative under artifacts/map/...
        map_rel = d.relative_to(ARTIFACT_MAP).as_posix()
        plugin_rel = f"homm3_runtime_assets/artifacts/map/{map_rel}/00_00.png"
        entries.append(
            {
                "kind": "artifact",
                "sid": d.name,
                "source": "homm3_runtime_assets/artifacts/map",
                "relativePng": plugin_rel,
                "mapObjectRel": f"{map_rel}/00_00.png",
                "dir": map_rel,
                "frameCount": frames,
                "animated": frames > 1,
                "generate": True,
                "firstFrameOnly": frames > 1,
                "prefabKey": prefab_key(d.name),
                "targetHeight": DEFAULT_TARGET_HEIGHT,
                "absolutePng": str(png.resolve()).replace("\\", "/"),
            }
        )

    if not entries:
        fail("no homm3_artifact_* folders found under artifacts/map")

    generate = [e for e in entries if e["generate"]]
    first_frame = [e for e in entries if e.get("firstFrameOnly")]
    return {
        "schema": "homm3_artifact_map_billboard_inventory.v1",
        "proof": "source/static validated — all homm3_artifact_* map AVA first frames",
        "excludedTrees": [
            "homm3_runtime_assets/artifacts/icons",
            "homm3_runtime_assets/map_object_refs",
            "seer hut overlay",
        ],
        "counts": {
            "wiredUnique": len(entries),
            "generate": len(generate),
            "generateStaticSingleFrame": len(generate) - len(first_frame),
            "generateFirstFrameFromAnimated": len(first_frame),
            "animatedSourceStacks": sum(1 for e in entries if e["animated"]),
        },
        "entries": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    inv = build_inventory()
    out: Path = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"ok": True, "out": str(out).replace("\\", "/"), "counts": inv["counts"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
