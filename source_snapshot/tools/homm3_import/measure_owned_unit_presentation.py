#!/usr/bin/env python3
"""Owned HoMM3 units vs vanilla Olden Era units: size, ground contact, pivot, reach, bounds, materials.

    python tools/homm3_import/measure_owned_unit_presentation.py --vanilla      # stock bands (slow, ~2 min)
    python tools/homm3_import/measure_owned_unit_presentation.py                 # every homm3_import.json entry
    python tools/homm3_import/measure_owned_unit_presentation.py --only h3_goblin --verbose

What is measured (the plugin's own sequence, Homm3ImportVisuals.cs; see owned_unit_geometry.py):
  * owned: Orientation zeroed, idle clip t=0, exact posed vertices (bones + blend shapes; the plugin reads the
    same silhouette through SkinnedMeshRenderer.BakeMesh in TryGetRenderableWorldBounds), fit to
    battleHeightHexes * battleWorldHeightPerHex, lowest vertex planted on the hex floor
    (AlignOwnedSkinnedFeetToDonor); then every clip is sampled (15 Hz) through that same fit and plant.
    The retired localBounds rule (serialized bone AABBs; matched the old live ``meshY=`` lines exactly) is kept
    per row as boneBoundsHeight / boneBoundsFidelity / legacyLocalBounds for comparison;
  * vanilla: every stock battle prefab a Core.zip unit view uses, first child scaled by UnitViewConfig.scale,
    the same clips, ground = the prefab root (native units are authored on it).
Per unit: idle-0 height, idle-0 ground gap,
per-clip lowest point (sink below / lift above the hex floor), idle-0 base offset from the hex centre (the
foot/base centroid in XZ, which is what yaw turns about), horizontal reach, materials / albedo texture.
Map lane: owned map height = battle height x adventureMapToBattleHeightRatio (native median, separate artifact).
Preview lane: the plugin fits the preview to its vanilla donor's height, so the preview size relative to
other units is ownBattleHeight / donorBattleHeight (reported per unit).

Outputs (committed): tools/homm3_import/native_unit_presentation.json (vanilla bands),
tools/homm3_import/owned_unit_presentation.json (per-unit table). Cache of measured bundles (by size + mtime):
artifacts/homm3_owned_unit_presentation/cache.json. Gate: tools/validate_homm3_owned_unit_presentation_contract.py.
Proof tier: generated artifact (static read of built / installed bundles and installed stock assets).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from owned_unit_geometry import GOLDEN_ERA, INSTALLED_BUNDLES, ROOT, StockPrefabs, load_unit  # noqa: E402

IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
BUILD_OUT = HERE / "build_out"
CORE_ZIP = GOLDEN_ERA / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
NATIVE_OUT = HERE / "native_unit_presentation.json"
OWNED_OUT = HERE / "owned_unit_presentation.json"
CACHE = ROOT / "artifacts" / "homm3_owned_unit_presentation" / "cache.json"
PROFILE_VERSION = 5
CLIP_HZ = 15.0
# Native clip slots that play with the unit on its hex (ground contact matters); Death may sink (corpses).
CONTACT_SLOTS = ("22.Idle", "23.Idle_Rare", "01.Walk", "14.Attack", "20.Damage", "25.Stance", "27.Victory")
OWNED_PREFIXES = ("h3_", "hota_", "toa_")


# ---- inputs ----------------------------------------------------------------------------------------

def core_units() -> tuple[dict[str, dict], dict[str, dict]]:
    views, logics = {}, {}
    with zipfile.ZipFile(CORE_ZIP) as z:
        for n in z.namelist():
            if not n.endswith(".json"):
                continue
            if n.startswith("DB/units/units_views/"):
                tgt = views
            elif n.startswith("DB/units/units_logics/"):
                tgt = logics
            else:
                continue
            try:
                arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
            except ValueError:
                continue
            for a in arr:
                if isinstance(a, dict) and a.get("id"):
                    tgt[a["id"]] = a
    return views, logics


def bundle_candidates(name: str) -> list[Path]:
    return [p for p in (BUILD_OUT / name, INSTALLED_BUNDLES / name) if p.is_file()]


def newest_bundle(name: str) -> Path | None:
    c = bundle_candidates(name)
    return max(c, key=lambda p: p.stat().st_mtime_ns) if c else None


def signature(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


# ---- profiles --------------------------------------------------------------------------------------

def _r(x: float, n: int = 4) -> float:
    return round(float(x), n)


def profile(u, fit: float, ground: float, *, owned: bool) -> dict[str, Any]:
    """Every measurement in the lane's final space: y' = (y - ground) * fit, XZ * fit (root / hex space)."""
    idle = u.clips.get("22.Idle")
    P = (u.skinned_points(idle, 0) - [0.0, ground, 0.0]) * fit
    lo, hi = P.min(0), P.max(0)
    H = float(hi[1] - lo[1])
    base = P[P[:, 1] <= lo[1] + 0.1 * H]
    base_c = base[:, [0, 2]].mean(0)
    bbox_c = (lo[[0, 2]] + hi[[0, 2]]) / 2
    radial = np.hypot(P[:, 0], P[:, 2])
    out: dict[str, Any] = {
        "height": _r(H), "groundGap": _r(lo[1]), "top": _r(hi[1]),
        "baseOffset": _r(np.hypot(*base_c)), "bboxCenterOffset": _r(np.hypot(*bbox_c)),
        "reach": _r(radial.max()), "reachP95": _r(np.percentile(radial, 95)),
        "vertices": int(len(P)),
    }
    clips: dict[str, Any] = {}
    seen: dict[str, str] = {}
    for slot, clip in sorted(u.clips.items()):
        key = f"{id(clip)}"
        if key in seen:
            clips[slot] = dict(clips[seen[key]], sameAs=seen[key])
            continue
        seen[key] = slot
        lows, tops, offs = [], [], []
        for ti in range(len(clip.times)):
            Q = (u.skinned_points(clip, ti) - [0.0, ground, 0.0]) * fit
            lows.append(Q[:, 1].min())
            tops.append(Q[:, 1].max())
            offs.append(np.hypot(*Q[Q[:, 1] <= Q[:, 1].min() + 0.1 * H][:, [0, 2]].mean(0)))
        clips[slot] = {"clip": u.clip_by_override.get(slot, clip.name), "frames": len(clip.times),
                       "lowMin": _r(min(lows)), "lowMax": _r(max(lows)), "lowFirst": _r(lows[0]),
                       "topMax": _r(max(tops)), "baseOffsetMax": _r(max(offs))}
    out["clips"] = clips
    shaders = sorted({s for sk in u.skins for s in sk.material_shaders})
    out["materials"] = sorted({m for sk in u.skins for m in sk.material_names})
    out["shaders"] = shaders
    out["renderers"] = [{"name": sk.name, "vertices": int(len(sk.verts)), "bones": len(sk.bones),
                         "blendShapes": len(sk.shapes)} for sk in u.skins]
    return out


def measure_owned(bundle: str, hexes: float, per_hex: float) -> dict[str, Any]:
    t0 = time.time()
    u = load_unit(Path(bundle), clip_hz=CLIP_HZ)
    idle = u.clips.get("22.Idle")
    if idle is None:
        raise ValueError("no 22.Idle override clip")
    plugin, true = u.unity_bone_bounds(idle, 0)
    if plugin is None:
        raise ValueError("no skinned renderer with bone bounds")
    plugin_h = float(plugin[1][1] - plugin[0][1])
    P = u.skinned_points(idle, 0)
    geom_h = float(np.ptp(P[:, 1]))
    target = hexes * per_hex
    # Runtime rule (TryGetBakedSkinWorldBounds): fit and plant on the exact idle-0 silhouette (BakeMesh).
    fit = target / geom_h
    prof = profile(u, fit, float(P[:, 1].min()), owned=True)
    # What the retired localBounds rule would have done, kept for the before/after table.
    legacy_fit = target / plugin_h
    legacy = {"height": _r(geom_h * legacy_fit), "groundGap": _r((float(P[:, 1].min()) - float(plugin[0][1])) * legacy_fit)}
    cont = u.extra.get("container", [])
    tex = {}
    for m in prof["materials"]:
        hit = [c for c in cont if c.endswith("/" + m.lower() + "_basecolor.jpg") or c.endswith("/" + m.lower() + "_basecolor.png")]
        tex[m] = hit[0] if hit else None
    prof.update({
        "exactIdle0Height": _r(geom_h), "fitScale": _r(fit, 6), "targetHeight": _r(target),
        "boneBoundsHeight": _r(plugin_h), "boneBoundsFidelity": _r(geom_h / plugin_h), "legacyLocalBounds": legacy,
        "hasOrientationWrap": u.wrap is not None, "wrapName": u.names.get(u.wrap) if u.wrap else None,
        "basecolorTexture": tex, "seconds": round(time.time() - t0, 1),
    })
    return prof


def measure_stock(sp: StockPrefabs, key: str, scale: float) -> dict[str, Any]:
    u = sp.load(key, scale, clip_hz=CLIP_HZ)
    prof = profile(u, 1.0, 0.0, owned=False)
    prof["authoredFirstChildScale"] = u.extra["authoredFirstChildScale"]
    return prof


# ---- vanilla bands ---------------------------------------------------------------------------------

def run_vanilla() -> dict[str, Any]:
    views, logics = core_units()
    sp = StockPrefabs()
    rows, skipped, done = {}, [], {}
    for vid, v in sorted(views.items()):
        if vid.startswith(OWNED_PREFIXES) or "homm3_import" in str(v.get("mesh", "")).lower():
            continue
        key = str(v.get("mesh", "")).lower()
        lg = logics.get(vid, {})
        if not key or v.get("scale") is None:
            continue
        if "units/" + key not in sp.container:
            skipped.append({"view": vid, "reason": "no ResourceManager prefab " + key})
            continue
        try:
            prof = done.get((key, float(v["scale"])))
            if prof is None:
                prof = measure_stock(sp, key, float(v["scale"]))
                done[(key, float(v["scale"]))] = prof
        except Exception as ex:  # noqa: BLE001 - recorded, never silently used
            skipped.append({"view": vid, "reason": f"{type(ex).__name__}: {ex}"})
            continue
        rows[vid] = {"mesh": key, "tier": lg.get("tier"), "fraction": lg.get("fraction"),
                     "viewScale": float(v["scale"]), "flyer": v.get("defaultHeight") is not None,
                     "defaultHeight": v.get("defaultHeight"), "modelHeight": v.get("modelHeight"), **prof}
        print(f"  vanilla {vid:28s} tier={lg.get('tier')} H={prof['height']:.2f} gap={prof['groundGap']:+.3f} "
              f"base={prof['baseOffset']:.2f} reach={prof['reach']:.2f}", flush=True)
    return {"rows": rows, "skipped": skipped, "bands": vanilla_bands(rows)}


def _band(vals: list[float]) -> dict[str, float]:
    s = sorted(vals)
    q = lambda f: s[min(len(s) - 1, max(0, int(round(f * (len(s) - 1)))))]  # noqa: E731
    return {"n": len(s), "min": _r(s[0]), "p05": _r(q(0.05)), "p50": _r(q(0.5)), "p95": _r(q(0.95)), "max": _r(s[-1])}


def vanilla_bands(rows: dict[str, dict]) -> dict[str, Any]:
    by_tier: dict[str, list[float]] = {}
    for r in rows.values():
        if r["tier"] is not None:
            by_tier.setdefault(str(r["tier"]), []).append(r["height"])
    contact = {}
    for slot in CONTACT_SLOTS:
        lows = [r["clips"][slot] for r in rows.values() if slot in r["clips"] and "lowMin" in r["clips"][slot]]
        if lows:
            contact[slot] = {"lowMin": _band([c["lowMin"] for c in lows]), "lowMax": _band([c["lowMax"] for c in lows])}
    return {
        "heightByTier": {t: _band(v) for t, v in sorted(by_tier.items())},
        "height": _band([r["height"] for r in rows.values()]),
        "groundGap": _band([r["groundGap"] for r in rows.values()]),
        "baseOffset": _band([r["baseOffset"] for r in rows.values()]),
        "baseOffsetOverHeight": _band([r["baseOffset"] / r["height"] for r in rows.values()]),
        "reach": _band([r["reach"] for r in rows.values()]),
        "reachOverHeight": _band([r["reach"] / r["height"] for r in rows.values()]),
        "contact": contact,
        "shaders": sorted({s for r in rows.values() for s in r["shaders"]}),
    }


# ---- owned -----------------------------------------------------------------------------------------

def owned_jobs(table: dict, only: set[str] | None) -> list[dict[str, Any]]:
    jobs = []
    for e in table["entries"]:
        sid = e["gameUnitSids"][0]
        if only and sid not in only and e["bundleName"] not in only:
            continue
        b = newest_bundle(e["bundleName"])
        jobs.append({"sid": sid, "entry": e, "bundle": str(b) if b else None,
                     "signature": signature(b) if b else None,
                     "source": ("build_out" if b and b.parent == BUILD_OUT else "installed") if b else None})
    return jobs


def load_cache() -> dict[str, Any]:
    try:
        c = json.loads(CACHE.read_text(encoding="utf-8"))
        return c if c.get("profileVersion") == PROFILE_VERSION else {"profileVersion": PROFILE_VERSION, "rows": {}}
    except (OSError, ValueError):
        return {"profileVersion": PROFILE_VERSION, "rows": {}}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1) + "\n", encoding="utf-8")


def _cache_key(job: dict, per_hex: float) -> str:
    return f"{job['bundle']}|{job['signature']}|{job['entry'].get('battleHeightHexes')}|{per_hex}"


def _work(bundle: str, hexes: float, per_hex: float) -> dict[str, Any]:
    try:
        return measure_owned(bundle, hexes, per_hex)
    except Exception as ex:  # noqa: BLE001 - reported as a failed row
        return {"error": f"{type(ex).__name__}: {ex}"}


def measure_owned_jobs(jobs: list[dict], per_hex: float, workers: int, verbose: bool) -> dict[str, dict]:
    cache = load_cache()
    out: dict[str, dict] = {}
    todo = []
    for j in jobs:
        if not j["bundle"]:
            out[j["sid"]] = {"error": "no built or installed bundle " + j["entry"]["bundleName"]}
            continue
        hexes = j["entry"].get("battleHeightHexes")
        if hexes is None:
            out[j["sid"]] = {"error": "entry has no battleHeightHexes"}
            continue
        k = _cache_key(j, per_hex)
        if k in cache["rows"]:
            out[j["sid"]] = cache["rows"][k]
        else:
            todo.append((j, k, float(hexes)))
    if todo:
        print(f"measuring {len(todo)} bundle(s) with {workers} worker(s)...", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_work, j["bundle"], hexes, per_hex): (j, k) for j, k, hexes in todo}
            for i, f in enumerate(as_completed(futs), 1):
                j, k = futs[f]
                row = f.result()
                out[j["sid"]] = row
                if "error" not in row:
                    cache["rows"][k] = row
                if verbose or "error" in row:
                    print(f"  [{i}/{len(todo)}] {j['sid']}: " + (row.get("error") or
                          f"H={row['height']:.2f} boneFid={row['boneBoundsFidelity']:.3f} ({row['seconds']}s)"), flush=True)
                if i % 20 == 0:
                    save_cache(cache)
        save_cache(cache)
    return out


def default_workers() -> int:
    return max(1, min(6, (os.cpu_count() or 2) - 1))


def write_owned(table_rows: dict[str, dict], table: dict) -> None:
    OWNED_OUT.write_text(json.dumps({
        "schema": "owned_unit_presentation.v1", "profileVersion": PROFILE_VERSION, "clipHz": CLIP_HZ,
        "battleWorldHeightPerHex": float(table["battleWorldHeightPerHex"]),
        "adventureMapToBattleHeightRatio": table.get("adventureMapToBattleHeightRatio"),
        "proof": "generated artifact: static read of built / installed bundles, decoded clip samples; runtime look unproven",
        "rows": dict(sorted(table_rows.items()))}, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vanilla", action="store_true", help=f"(re)measure the stock bands into {NATIVE_OUT.name}")
    ap.add_argument("--only", action="append", default=[], help="unit sid or bundle name (repeatable)")
    ap.add_argument("--workers", type=int, default=default_workers())
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.vanilla:
        res = run_vanilla()
        NATIVE_OUT.write_text(json.dumps({
            "schema": "native_unit_presentation.v1", "profileVersion": PROFILE_VERSION,
            "gameData": str(GOLDEN_ERA).replace("\\", "/"), "clipHz": CLIP_HZ,
            "proof": "generated artifact: static read of installed stock prefabs, decoded clip samples",
            **res}, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {NATIVE_OUT} ({len(res['rows'])} stock views, {len(res['skipped'])} skipped)")
        return 0
    table = json.loads(IMPORT_TABLE.read_bytes().decode("utf-8-sig"))
    per_hex = float(table["battleWorldHeightPerHex"])
    jobs = owned_jobs(table, set(args.only) or None)
    rows = measure_owned_jobs(jobs, per_hex, args.workers, args.verbose)
    if args.no_write or args.only:
        for j in jobs:
            print(j["sid"], json.dumps(rows[j["sid"]], indent=None)[:2000])
        return 0
    _, logics = core_units()
    table_rows = {}
    for j in jobs:
        e = j["entry"]
        table_rows[j["sid"]] = {"bundle": e["bundleName"], "bundleSource": j["source"], "signature": j["signature"],
                                "battleHeightHexes": e.get("battleHeightHexes"),
                                "tier": logics.get(j["sid"], {}).get("tier"),
                                "presentationDonor": e.get("battlePresentationResPath"), **rows[j["sid"]]}
    write_owned(table_rows, table)
    print(f"wrote {OWNED_OUT} ({len(table_rows)} units)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
