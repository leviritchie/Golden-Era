#!/usr/bin/env python3
"""Inventory contract-wired adventure-map city/dwelling billboards only.

Source of truth:
  - custom_factions/homm3_*.json assets.cityBillboard + runtime.dwellingBillboardImages
  - Homm3CustomFactionRegistry default city billboard paths (when authoritative)

Never inventories town_scene_refs, AVW leftovers, or unwired map_object_refs dirs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
MAP_OBJECT_REFS = PLUGIN / "homm3_runtime_assets" / "map_object_refs"
FACTIONS = ROOT / "custom_factions"
REGISTRY_CS = PLUGIN / "Homm3CustomFactionRegistry.cs"
DEFAULT_OUT = ROOT / "artifacts" / "meshy_map_buildings" / "inventory.json"


def fail(msg: str) -> None:
    print(f"inventory-adventure-map-building-billboards: {msg}", file=sys.stderr)
    raise SystemExit(1)


def normalize_rel(path: str) -> str:
    p = path.replace("\\", "/")
    markers = (
        "homm3_runtime_assets/map_object_refs/",
        "map_object_refs/",
    )
    for m in markers:
        if m in p:
            p = p.split(m, 1)[1]
            break
    # Absolute / repo-relative plugin paths
    if p.startswith("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/"):
        p = p.split("OfflineUnlockMod/", 1)[1]
        if p.startswith("homm3_runtime_assets/map_object_refs/"):
            p = p[len("homm3_runtime_assets/map_object_refs/") :]
    return p.lstrip("/")


def resolve_png(rel_under_map_object_refs: str) -> Path:
    rel = normalize_rel(rel_under_map_object_refs)
    if not rel.lower().endswith(".png"):
        fail(f"expected PNG path, got {rel_under_map_object_refs!r}")
    candidate = MAP_OBJECT_REFS / rel
    if candidate.is_file():
        return candidate.resolve()
    # Case-insensitive fallback on Windows for AVG/avg mismatches
    parts = Path(rel).parts
    cur = MAP_OBJECT_REFS
    for part in parts[:-1]:
        if not cur.is_dir():
            fail(f"missing directory while resolving {rel}: {cur}")
        match = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
        if match is None:
            fail(f"cannot resolve path segment {part!r} under {cur} for {rel}")
        cur = match
    name = parts[-1]
    match = next((c for c in cur.iterdir() if c.name.lower() == name.lower()), None)
    if match is None or not match.is_file():
        fail(f"missing billboard PNG: {MAP_OBJECT_REFS / rel}")
    return match.resolve()


def frame_count(png: Path) -> int:
    d = png.parent
    if not d.is_dir() or not d.name.lower().endswith(".dir"):
        fail(f"billboard PNG not inside a *.dir folder: {png}")
    return len(list(d.glob("*.png")))


def prefab_key(rel_png: str) -> str:
    # map_mesh_homm3_tower_city__capitol
    rel = normalize_rel(rel_png).replace("\\", "/")
    parts = rel.split("/")
    if len(parts) < 3:
        fail(f"unexpected billboard relative path shape: {rel}")
    group, dirname, _ = parts[0], parts[1], parts[2]
    stem = dirname[:-4] if dirname.lower().endswith(".dir") else dirname
    raw = f"map_mesh_{group}__{stem}".lower()
    return re.sub(r"[^a-z0-9_]+", "_", raw)


def collect_manifest_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(FACTIONS.glob("homm3_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        fac = (data.get("identity") or {}).get("factionSid") or path.stem
        assets = data.get("assets") or {}
        runtime = data.get("runtime") or {}
        height = float(runtime.get("cityMapBillboardHeight") or 4.5)
        city = assets.get("cityBillboard")
        if city:
            rows.append(
                {
                    "kind": "city",
                    "factionSid": fac,
                    "source": f"manifest:{path.name}",
                    "rawPath": city,
                    "targetHeight": height,
                }
            )
        folder = (assets.get("dwellingBillboardFolder") or "").replace("\\", "/").rstrip("/")
        for img in runtime.get("dwellingBillboardImages") or []:
            if not folder:
                fail(f"{fac}: dwellingBillboardImages present but dwellingBillboardFolder missing")
            rows.append(
                {
                    "kind": "dwelling",
                    "factionSid": fac,
                    "source": f"manifest:{path.name}",
                    "rawPath": f"{folder}/{img}",
                    "targetHeight": 2.25,
                }
            )
    return rows


def collect_registry_city_rows() -> list[dict]:
    if not REGISTRY_CS.is_file():
        fail(f"missing registry: {REGISTRY_CS}")
    text = REGISTRY_CS.read_text(encoding="utf-8-sig")
    rows: list[dict] = []
    for m in re.finditer(
        r'return\s+"(homm3_runtime_assets/map_object_refs/[^"]+\.png)"',
        text,
    ):
        rows.append(
            {
                "kind": "city",
                "factionSid": "registry_default",
                "source": "Homm3CustomFactionRegistry.ResolveDefaultCityMapBillboardRelativePath",
                "rawPath": m.group(1),
                "targetHeight": 5.15,
            }
        )
    return rows


def build_inventory() -> dict:
    if not MAP_OBJECT_REFS.is_dir():
        fail(f"missing map_object_refs: {MAP_OBJECT_REFS}")

    raw_rows = collect_manifest_rows() + collect_registry_city_rows()
    by_key: dict[str, dict] = {}
    excluded: list[dict] = []

    for row in raw_rows:
        raw = row["rawPath"].replace("\\", "/")
        lower = raw.lower()
        if "town_scene_refs" in lower:
            fail(f"town_scene_refs path leaked into billboard inventory: {raw}")
        png = resolve_png(raw)
        try:
            rel = png.relative_to(MAP_OBJECT_REFS).as_posix()
        except ValueError:
            fail(f"resolved PNG outside map_object_refs: {png}")
        dir_name = png.parent.name
        if dir_name.lower().startswith("avw"):
            fail(f"AVW wandering path must not be a wired billboard: {rel}")

        frames = frame_count(png)
        plugin_rel = f"homm3_runtime_assets/map_object_refs/{rel}"
        key = plugin_rel.lower()
        # Wired billboards always mesh from the authored first frame (00_00.png path).
        # Multi-frame DEF stacks stay animated for PNG fallback only when no mesh exists.
        entry = {
            "kind": row["kind"],
            "factionSid": row["factionSid"],
            "source": row["source"],
            "relativePng": plugin_rel,
            "mapObjectRel": rel,
            "dir": png.parent.relative_to(MAP_OBJECT_REFS).as_posix(),
            "frameCount": frames,
            "animated": frames > 1,
            "generate": True,
            "firstFrameOnly": frames > 1,
            "prefabKey": prefab_key(rel),
            "targetHeight": float(row["targetHeight"]),
            "absolutePng": str(png).replace("\\", "/"),
        }
        if key in by_key:
            # Prefer manifest faction identity over registry_default duplicate
            prev = by_key[key]
            if prev["factionSid"] == "registry_default" and row["factionSid"] != "registry_default":
                by_key[key] = entry
            elif prev["kind"] == "city" and row["kind"] == "city":
                # Keep taller authored height when both city
                if entry["targetHeight"] > prev["targetHeight"]:
                    prev["targetHeight"] = entry["targetHeight"]
            continue
        by_key[key] = entry

    entries = sorted(by_key.values(), key=lambda e: e["relativePng"].lower())
    generate = [e for e in entries if e["generate"]]
    animated = [e for e in entries if e["animated"]]
    first_frame = [e for e in entries if e.get("firstFrameOnly")]

    # Unwired leftovers (informational only)
    wired_dirs = {e["dir"].lower() for e in entries}
    for group in sorted(MAP_OBJECT_REFS.iterdir()):
        if not group.is_dir():
            continue
        name = group.name
        if not (
            name.endswith("_city")
            or name.endswith("_dwellings")
            or name == "homm3_neutral_dwellings"
        ):
            continue
        for d in sorted(group.glob("*.dir")):
            rel_dir = d.relative_to(MAP_OBJECT_REFS).as_posix()
            if rel_dir.lower() in wired_dirs:
                continue
            excluded.append(
                {
                    "reason": "unwired_map_object_refs_leftover",
                    "dir": rel_dir,
                    "frameCount": len(list(d.glob("*.png"))),
                }
            )

    return {
        "schema": "homm3_adventure_map_building_billboard_inventory.v1",
        "proof": "source/static validated — contract-wired city/dwelling billboards only",
        "excludedTrees": [
            "homm3_runtime_assets/town_scene_refs",
            "unwired map_object_refs leftovers",
            "AVW* wandering extracts",
            "unit map stacks",
            "artifacts",
        ],
        "counts": {
            "wiredUnique": len(entries),
            "generate": len(generate),
            "generateStaticSingleFrame": len(generate) - len(first_frame),
            "generateFirstFrameFromAnimated": len(first_frame),
            "animatedSourceStacks": len(animated),
            "unwiredLeftovers": len(excluded),
        },
        "entries": entries,
        "unwiredLeftovers": excluded,
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
            {
                "ok": True,
                "out": str(out).replace("\\", "/"),
                "counts": inv["counts"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
