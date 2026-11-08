#!/usr/bin/env python3
"""Owned HoMM3 units in the UI unit previews: size and ground placement, before and after the battle-size rule.

    python tools/homm3_import/measure_owned_preview_framing.py            # every homm3_import.json owned entry
    python tools/homm3_import/measure_owned_preview_framing.py --only h3_goblin --verbose

How vanilla frames a unit preview (Mono demo Hex.dll, same flow the live Golden Era names drift from):
  * ``UiModelsSpawner.Spawn`` instantiates the battle prefab at world scale 1 and yaw 22, sets the prefab's
    first child ``localScale = sign * UnitViewConfig.scale`` and parents it keeping world scale;
  * ``BhUnitPreviews.LoadModel`` / ``BhUnitWindowPreview.SpawnModel`` repeat that first-child write and
    ``SpawnModel`` / ``BhHireUnitItemView.PresetModels`` put the model root at ``localPosition = 0``;
  * one fixed camera (``UiConstants.UnitCamParams``: angle 13.7, distance 25, yOffset 1.95) frames every unit.
  There is no bounds framing. A vanilla preview therefore shows the unit at its battle size (the same prefab
  and the same view scale ``tools/homm3_import/native_unit_presentation.json`` measures), feet on the root.

Owned lanes before the fix (Homm3ImportVisuals.PlaceOwnedSkinnedPreviewAtVanillaMeshPose):
  * detail window (``BhUnitWindowPreview.Show`` aliased to the donor): the owned mesh is height-fitted to the
    donor's rendered height and centred on the donor's bounds -> preview height = donor height;
  * hire screen / ``BhUnitPreviews`` pool (synthetic loader supply): the owned mesh keeps localScale 1 and is
    centred on the slot, then native writes the unit's own (donor-copied) view scale onto the first child and
    zeroes the root position -> preview height = raw bundle height x view scale, feet at view scale x raw min Y.
After (Homm3OwnedSkinnedPreviewFraming): every lane = the battle rule, battleHeightHexes x battleWorldHeightPerHex
in world units, lowest idle-0 vertex on the model root, planted on the first child so the native writes that
follow cannot undo it. So owned units stand in the previews at the size and relation they have in battle,
exactly as vanilla units do.

Output (committed): tools/homm3_import/owned_preview_framing.json.
Gate: tools/validate_homm3_owned_preview_framing_contract.py.
Proof tier: generated artifact (static read of built / installed bundles, installed Core.zip and stock bands).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from owned_unit_geometry import load_unit  # noqa: E402
import measure_owned_unit_presentation as mp  # noqa: E402
from validate_homm3_owned_skinned_preview_contract import (  # noqa: E402
    SOURCE_FACTIONS,
    owned_skinned_sids,
    registry_donor_map,
)

OUT = HERE / "owned_preview_framing.json"
SCHEMA = "owned_preview_framing.v1"


def core_view_scales() -> dict[str, float]:
    out: dict[str, float] = {}
    with zipfile.ZipFile(mp.CORE_ZIP) as z:
        for n in z.namelist():
            if not (n.startswith("DB/units/units_views/") and n.endswith(".json")):
                continue
            try:
                arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
            except ValueError:
                continue
            for a in arr:
                if isinstance(a, dict) and a.get("id") and a.get("scale") is not None:
                    out[a["id"]] = float(a["scale"])
    return out


def measure_bundle(bundle: str) -> dict[str, Any]:
    """Raw idle-0 geometry of the prefab at localScale 1 (wrap zeroed), and where the native first-child write lands."""
    try:
        u = load_unit(Path(bundle), clip_hz=mp.CLIP_HZ)
        idle = u.clips.get("22.Idle")
        if idle is None:
            return {"error": "no 22.Idle override clip"}
        P = u.skinned_points(idle, 0)
        kids = u.children.get(u.root, [])
        first = kids[0] if kids else None
        under = set()
        if first is not None:
            stack = [first]
            while stack:
                p = stack.pop()
                under.add(p)
                stack += u.children.get(p, [])
        skin_nodes = set()
        placed = set()  # what actually positions vertices: bones for a skinned renderer, the node for a static one
        for sk in u.skins:
            skin_nodes.add(sk.node)
            skin_nodes.update(sk.bones)
            if sk.root_bone is not None:
                skin_nodes.add(sk.root_bone)
            placed.update(sk.bones if sk.bones else [sk.node])
        # The plant node (Homm3OwnedSkinnedPreviewFraming.FindWrap): direct child Orientation, else MocapDeliveryRoot.
        names = {c: u.names.get(c) for c in kids}
        plant = next((c for c in kids if names[c] == "Orientation"), None) or \
            next((c for c in kids if names[c] == "MocapDeliveryRoot"), None)
        plant_sub = set()
        if plant is not None:
            stack = [plant]
            while stack:
                p = stack.pop()
                plant_sub.add(p)
                stack += u.children.get(p, [])
        animated = set()
        for clip in {id(c): c for c in u.clips.values()}.values():
            for h, attrs in clip.transform.items():
                if 1 in attrs or 3 in attrs:
                    animated.add(h)
        plant_hash = str(zlib.crc32(u.names[plant].encode())) if plant is not None else None
        first_hash = str(zlib.crc32(u.names[first].encode())) if first is not None else None
        return {
            "rawMinY": round(float(P[:, 1].min()), 4),
            "rawMaxY": round(float(P[:, 1].max()), 4),
            "firstChild": u.names.get(first) if first is not None else None,
            "firstChildIsWrap": first is not None and first == u.wrap,
            "skinUnderFirstChild": bool(skin_nodes) and skin_nodes <= under,
            "plantNode": u.names.get(plant) if plant is not None else None,
            "placedUnderPlantNode": bool(placed) and placed <= plant_sub,
            "plantNodeAnimated": plant_hash in animated if plant_hash else None,
            "firstChildScaleAnimated": first_hash in animated if first_hash else None,
        }
    except Exception as ex:  # noqa: BLE001 - reported as a failed row
        return {"error": f"{type(ex).__name__}: {ex}"}


def band(vals: list[float]) -> dict[str, float]:
    s = sorted(vals)
    q = lambda f: s[min(len(s) - 1, max(0, int(round(f * (len(s) - 1)))))]  # noqa: E731
    logs = [math.log(v) for v in s if v > 0]
    return {"n": len(s), "min": round(s[0], 4), "p05": round(q(0.05), 4), "p50": round(q(0.5), 4),
            "p95": round(q(0.95), 4), "max": round(s[-1], 4), "p95OverP05": round(q(0.95) / q(0.05), 3),
            "maxOverMin": round(s[-1] / s[0], 3), "logStd": round(statistics.pstdev(logs), 4)}


def signed_band(vals: list[float]) -> dict[str, float]:
    s = sorted(vals)
    q = lambda f: s[min(len(s) - 1, max(0, int(round(f * (len(s) - 1)))))]  # noqa: E731
    return {"n": len(s), "min": round(s[0], 4), "p05": round(q(0.05), 4), "p50": round(q(0.5), 4),
            "p95": round(q(0.95), 4), "max": round(s[-1], 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="unit SID(s) to measure (no artifact write)")
    ap.add_argument("--workers", type=int, default=mp.default_workers())
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    table = json.loads(mp.IMPORT_TABLE.read_text(encoding="utf-8-sig"))
    per_hex = float(table["battleWorldHeightPerHex"])
    presentation = json.loads(mp.OWNED_OUT.read_text(encoding="utf-8"))["rows"]
    native = json.loads(mp.NATIVE_OUT.read_text(encoding="utf-8"))
    vanilla = native["rows"]
    views = core_view_scales()
    donors = registry_donor_map(SOURCE_FACTIONS)
    preview_donors: dict[str, str] = {}
    errors: list[str] = []
    owned, _ = owned_skinned_sids(mp.IMPORT_TABLE, None, preview_donors, errors)
    donors = {**preview_donors, **donors}

    jobs = [j for j in mp.owned_jobs(table, set(args.only) if args.only else None) if j["sid"] in owned]
    geo: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(measure_bundle, j["bundle"]): j for j in jobs if j["bundle"]}
        for f in as_completed(futs):
            geo[futs[f]["sid"]] = f.result()
    rows: dict[str, dict] = {}
    for j in jobs:
        sid = j["sid"]
        hexes = j["entry"].get("battleHeightHexes")
        pres = presentation.get(sid, {})
        g = geo.get(sid, {"error": "no bundle"})
        row: dict[str, Any] = {"bundle": j["entry"]["bundleName"], "tier": pres.get("tier"),
                               "battleHeightHexes": hexes, "donor": donors.get(sid), "viewScale": views.get(sid)}
        if hexes is None or "error" in g:
            row["error"] = "no battleHeightHexes" if hexes is None else g["error"]
            rows[sid] = row
            continue
        raw_h = g["rawMaxY"] - g["rawMinY"]
        target = float(hexes) * per_hex
        donor_row = vanilla.get(donors.get(sid) or "")
        vs = abs(views[sid]) if views.get(sid) else None
        row.update(g)
        row["rawHeight"] = round(raw_h, 4)
        row["battleTarget"] = round(target, 4)
        row["before"] = {
            # Detail window: fitted to the donor's rendered height and centred on its bounds (feet at its min).
            "detail": {"height": donor_row["height"], "feetY": donor_row["groundGap"]} if donor_row else None,
            # Pool / hire: raw size x the view scale native writes on the first child; root position zeroed.
            "pool": ({"height": round(raw_h * vs, 4), "feetY": round(g["rawMinY"] * vs, 4)}
                     if vs and g["firstChildIsWrap"] else
                     {"height": round(raw_h, 4), "feetY": round(g["rawMinY"], 4)}),
        }
        row["after"] = {"height": round(target, 4), "feetY": 0.0}
        for lane in ("detail", "pool"):
            b = row["before"][lane]
            if b:
                b["overBattle"] = round(b["height"] / target, 4)
        rows[sid] = row
        if args.verbose:
            print(f"{sid:28s} target={target:5.2f} detail={row['before']['detail']} pool={row['before']['pool']}")

    ok = {k: r for k, r in rows.items() if "error" not in r}
    van_h = [r["height"] for r in vanilla.values()]

    def ranked(lane: str, n: int = 12) -> list[dict[str, Any]]:
        c = [(abs(math.log(r["before"][lane]["overBattle"])), k, r) for k, r in ok.items() if r["before"][lane]]
        return [{"sid": k, "donor": r["donor"], "viewScale": r["viewScale"], "battleTarget": r["battleTarget"],
                 "beforeHeight": r["before"][lane]["height"], "overBattle": r["before"][lane]["overBattle"]}
                for _, k, r in sorted(c, reverse=True)[:n]]

    by_tier: dict[str, dict[str, Any]] = {}
    for t in sorted({str(r["tier"]) for r in ok.values() if r["tier"] is not None}):
        vt = [r["height"] for r in vanilla.values() if str(r.get("tier")) == t]
        ot = [r for r in ok.values() if str(r["tier"]) == t]
        by_tier[t] = {
            "vanillaP50": round(statistics.median(vt), 4) if vt else None,
            "afterP50": round(statistics.median(r["after"]["height"] for r in ot), 4),
            "beforeDetailP50": round(statistics.median(r["before"]["detail"]["height"] for r in ot if r["before"]["detail"]), 4)
            if any(r["before"]["detail"] for r in ot) else None,
            "beforePoolP50": round(statistics.median(r["before"]["pool"]["height"] for r in ot), 4),
            "n": len(ot),
        }
    summary = {
        "vanillaHeight": band(van_h),
        "afterHeight": band([r["after"]["height"] for r in ok.values()]),
        "beforeDetailHeight": band([r["before"]["detail"]["height"] for r in ok.values() if r["before"]["detail"]]),
        "beforePoolHeight": band([r["before"]["pool"]["height"] for r in ok.values()]),
        "beforeDetailOverBattle": band([r["before"]["detail"]["overBattle"] for r in ok.values() if r["before"]["detail"]]),
        "beforePoolOverBattle": band([r["before"]["pool"]["overBattle"] for r in ok.values()]),
        "beforePoolFeetYOverHeight": signed_band([r["before"]["pool"]["feetY"] / r["before"]["pool"]["height"] for r in ok.values()]),
        "vanillaGroundGapOverHeight": signed_band([r["groundGap"] / r["height"] for r in vanilla.values()]),
        "byTier": by_tier,
        "worstDetail": ranked("detail"),
        "worstPool": ranked("pool"),
        "wrapNotFirstChild": sorted(k for k, r in ok.items() if not r["firstChildIsWrap"]),
        "skinOutsideFirstChild": sorted(k for k, r in ok.items() if not r["skinUnderFirstChild"]),
        "noPlantNode": sorted(k for k, r in ok.items() if not r["plantNode"]),
        "placedOutsidePlantNode": sorted(k for k, r in ok.items() if not r["placedUnderPlantNode"]),
        "plantNodeAnimated": sorted(k for k, r in ok.items() if r["plantNodeAnimated"]),
        "firstChildScaleAnimated": sorted(k for k, r in ok.items() if r["firstChildScaleAnimated"]),
        "noDonor": sorted(k for k, r in ok.items() if not r["donor"]),
        "failed": {k: r["error"] for k, r in rows.items() if "error" in r},
    }
    if args.only:
        print(json.dumps(summary, indent=1))
        return 0
    OUT.write_text(json.dumps({
        "schema": SCHEMA,
        "battleWorldHeightPerHex": per_hex,
        "rule": "preview world height = battleHeightHexes * battleWorldHeightPerHex (the battle fit); lowest idle-0 "
                "vertex on the model root, planted on the prefab's first child",
        "nativeFraming": "fixed UiConstants.UnitCamParams camera (angle 13.7, distance 25, yOffset 1.95); model at world "
                         "scale 1 with its first child at sign*UnitViewConfig.scale, root at localPosition 0; no bounds framing",
        "proof": "generated artifact: static read of built / installed bundles, installed Core.zip view scales and the "
                 "stock idle-0 bands; runtime preview look unproven",
        "summary": summary,
        "rows": rows,
    }, indent=1) + "\n", encoding="utf-8")
    s = summary
    print(f"wrote {OUT.relative_to(mp.ROOT)}: {len(ok)} units ({len(s['failed'])} failed)")
    for k in ("vanillaHeight", "afterHeight", "beforeDetailHeight", "beforePoolHeight"):
        b = s[k]
        print(f"  {k:20s} p05={b['p05']:.2f} p50={b['p50']:.2f} p95={b['p95']:.2f} max/min={b['maxOverMin']:.1f} logStd={b['logStd']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
