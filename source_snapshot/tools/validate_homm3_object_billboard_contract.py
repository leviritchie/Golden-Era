#!/usr/bin/env python3
"""Contract gate for visual-only HoMM3 object billboards (``homm3_objbb_<def>``).

Owner: ``experiments/campaign_port_poc/raw_translation/object_billboards.py``; assets from
``tools/build_homm3_object_billboard_assets.py``; runtime ``Homm3ArtifactMapBillboard.cs``;
doc ``docs/homm3_map_object_animation_audit.md``.

Checks:
1. every catalog DEF has a staged PNG, the asset manifest lists exactly the catalog, and each
   PNG's size matches it;
2. the host ObjectConfig row keeps its inert shape (Interact, seer-hut donor prefab, one blocked
   cell, no GATE);
3. the runtime keeps the prefix, the folder, the dispatch, and LogError on a missing image or a
   failed draw;
4. every generated raw-translation map with hosts has them in its map objects at the reported
   nodes, has their rows in its core overlay ``4_interactables.json``, and ships no
   ``objects_logic`` row for them (an event bank would make the host visitable; an empty one
   bricks map load).

Proof tier: source/static and generated artifact. It proves nothing about runtime drawing.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
ASSET_DIR = PLUGIN / "homm3_runtime_assets" / "map_object_refs" / "homm3_object_billboards"
RUNTIME = PLUGIN / "Homm3ArtifactMapBillboard.cs"
MANIFEST_GLOBS = (
    "artifacts/campaign_port_poc/*/*/raw_translation_map/install_manifest.json",
    "artifacts/campaign_port_poc/*/raw_translation_map/install_manifest.json",
)


def main() -> int:
    errors: list[str] = []
    sys.path.insert(0, str(POC))
    sys.path.insert(0, str(POC / "raw_translation"))
    import object_billboards as ob  # noqa: E402
    import port_homecoming_poc as poc  # noqa: E402
    from PIL import Image  # noqa: E402

    # 1. assets
    catalog = set(ob.all_billboard_sids())
    manifest_path = ASSET_DIR / "manifest.json"
    if not manifest_path.is_file():
        errors.append(f"missing {manifest_path.relative_to(ROOT)}; run tools/build_homm3_object_billboard_assets.py")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = {row["sid"]: row for row in manifest.get("billboards") or []}
        if set(rows) != catalog:
            errors.append(f"asset manifest sids differ from catalog: missing {sorted(catalog - set(rows))}, extra {sorted(set(rows) - catalog)}")
        for sid in sorted(catalog):
            png = ASSET_DIR / sid / "00_00.png"
            if not png.is_file():
                errors.append(f"{sid}: missing {png.relative_to(ROOT)}")
                continue
            with Image.open(png) as im:
                size = list(im.size)
                mode = im.mode
            if mode != "RGBA":
                errors.append(f"{sid}: PNG mode {mode}, expected RGBA")
            if sid in rows and rows[sid].get("pixelSize") != size:
                errors.append(f"{sid}: PNG size {size} != manifest {rows[sid].get('pixelSize')}")
        extra_dirs = sorted(p.name for p in ASSET_DIR.iterdir() if p.is_dir() and p.name not in catalog) if ASSET_DIR.is_dir() else []
        if extra_dirs:
            errors.append(f"stale billboard folders not in the catalog: {extra_dirs}")
    for tid, defs in ob.BILLBOARD_DEFS.items():
        if tid not in ob.BILLBOARD_TEMPLATE_IDS:
            errors.append(f"BILLBOARD_DEFS has object {tid} with no BILLBOARD_TEMPLATE_IDS name")
        if not defs:
            errors.append(f"object {tid} has no DEFs")

    # 2. host row
    row = ob.host_object_row(ob.SID_PREFIX + "probe")
    expected = {"tag": "Interact", "prefs": ["interactive/wise_owl"], "nodes": [1, 0, 0, 0], "sizeX": 2, "sizeZ": 2}
    for key, value in expected.items():
        if row.get(key) != value:
            errors.append(f"host row {key}={row.get(key)!r}, expected {value!r}")
    if 2 in row.get("nodes", []):
        errors.append("host row has a GATE; the billboard host must not be visitable")
    if ob.OVERLAY_MEMBER != "DB/map/objects/4_interactables.json":
        errors.append(f"host rows must go to 4_interactables.json (custom Interact Init), not {ob.OVERLAY_MEMBER}")

    # 3. runtime
    text = RUNTIME.read_text(encoding="utf-8")
    for needle in (
        f'ObjectBillboardSidPrefix = "{ob.SID_PREFIX}"',
        '"homm3_runtime_assets/map_object_refs/homm3_object_billboards"',
        "IsArtifactSid(sid) || IsSeerHutSid(sid) || IsObjectBillboardSid(sid)",
        'LogError("HoMM3 object billboard: missing image ',
        '"HoMM3 object billboard: FAILED to draw sid=',
        "LogObjectBillboardCatalog(log);",
    ):
        if needle not in text:
            errors.append(f"Homm3ArtifactMapBillboard.cs lost {needle!r}")
    builder = (POC / "raw_translation" / "build_raw_translation_map.py").read_text(encoding="utf-8")
    for needle in ("object_billboards.apply_object_billboard_hosts(", "object_billboards.write_host_overlay("):
        if needle not in builder:
            errors.append(f"build_raw_translation_map.py no longer calls {needle}")

    # 4. generated maps
    manifests = sorted({f for g in MANIFEST_GLOBS for f in glob.glob(str(ROOT / g))})
    if not manifests:
        errors.append("no raw_translation install manifests found")
    placed_total = unplaced_total = maps_with_hosts = 0
    for path in manifests:
        out = Path(path).parent
        label = out.parent.name
        report = json.loads(Path(path).read_text(encoding="utf-8")).get("objectBillboards")
        if not isinstance(report, dict) or report.get("schema") != ob.SCHEMA:
            errors.append(f"{label}: objectBillboards report missing (regenerate the map)")
            continue
        placed_total += int(report.get("placed") or 0)
        unplaced_total += int(report.get("unplacedCount") or 0)
        for miss in report.get("unplaced") or []:
            if not miss.get("reason"):
                errors.append(f"{label}: unplaced billboard {miss.get('sourceKey')} has no reason")
        hosts = report.get("hosts") or {}
        if not hosts:
            continue
        maps_with_hosts += 1
        map_files = [p for p in (out / "maps").glob("*.map") if "pre_visual" not in p.name]
        if len(map_files) != 1:
            errors.append(f"{label}: expected one map, found {[p.name for p in map_files]}")
            continue
        body = poc.read_olden_map_container(map_files[0]).chunks[1]
        placed_nodes = {
            (group.get("sid"), int(object_id)): int(node)
            for group in body.get("objects") or []
            if str(group.get("sid") or "").startswith(ob.SID_PREFIX)
            for object_id, node in zip(group.get("ids") or [], group.get("nodes") or [])
        }
        for host in hosts.values():
            key = (host["sid"], int(host["objectId"]))
            if placed_nodes.get(key) != int(host["node"]):
                errors.append(f"{label}: host {key} not in the map at node {host['node']} (found {placed_nodes.get(key)})")
        if len(placed_nodes) != len(hosts):
            errors.append(f"{label}: map has {len(placed_nodes)} billboard hosts, report has {len(hosts)}")
        overlay = out / "core_overlay" / ob.OVERLAY_MEMBER
        overlay_rows = {}
        if overlay.is_file():
            overlay_rows = {r.get("id"): r for r in json.loads(overlay.read_text(encoding="utf-8-sig")).get("array") or [] if isinstance(r, dict)}
        for sid in {h["sid"] for h in hosts.values()}:
            if overlay_rows.get(sid) != ob.host_object_row(sid):
                errors.append(f"{label}: core overlay {ob.OVERLAY_MEMBER} lacks the exact {sid} host row")
        logic_root = out / "core_overlay" / "DB" / "objects_logic"
        if logic_root.is_dir():
            for logic in logic_root.rglob("*.json"):
                if ob.SID_PREFIX in logic.read_text(encoding="utf-8-sig"):
                    errors.append(f"{label}: {logic.relative_to(out)} mentions {ob.SID_PREFIX}; billboard hosts must have no objects_logic row")

    print(json.dumps({
        "ok": not errors,
        "catalogSids": len(catalog),
        "maps": len(manifests),
        "mapsWithHosts": maps_with_hosts,
        "placed": placed_total,
        "unplaced": unplaced_total,
        "errors": errors,
    }, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
