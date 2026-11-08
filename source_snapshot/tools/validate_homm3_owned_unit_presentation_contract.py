#!/usr/bin/env python3
"""Owned HoMM3 unit presentation contract: every shipped owned unit sits in the vanilla Olden Era envelope.

Wired into OfflineUnlockMod.csproj as BeforeBuild target ValidateHomm3OwnedUnitPresentationContract
(skip with -p:SkipHomm3OwnedUnitPresentationContract=true). Adding or rebuilding an owned bundle lands here.

Checks
  1. Source: the fit / plant / preview bounds (TryGetRenderableWorldBounds) come from the exact posed
     silhouette, SkinnedMeshRenderer.BakeMesh(mesh, true) through the renderer transform, never from
     skin.localBounds (serialized bone AABBs: blend-shape envelope + root-bone space; shrank and floated
     DEF-retarget units and floated mount rigs by up to 1.4 world units).
  2. Artifact: tools/homm3_import/owned_unit_presentation.json has one error-free row per homm3_import.json
     entry, measured from the bundle that is current now. A row whose bundle changed (size / mtime) or whose
     battleHeightHexes changed is re-measured here through the measurement cache
     (tools/homm3_import/measure_owned_unit_presentation.py), and the artifact is rewritten.
  3. Vanilla envelope (tools/homm3_import/native_unit_presentation.json, stock prefabs at their view scale):
     battleHeightHexes in [HEXES_MIN, HEXES_MAX]; idle-0 height within the vanilla tier band widened by
     TIER_SLACK; idle-0 lowest vertex on the hex floor; idle / walk / attack lowest point not below the
     sink floors; base centroid offset / height and reach / height within vanilla max; every material has
     a <material>_basecolor texture in the bundle; the Orientation / MocapDeliveryRoot wrap exists.
  Known violations live in tools/homm3_owned_unit_presentation_allowlist.json with a reason. The allowlist
  only shrinks: an entry whose unit no longer violates that check fails the gate until it is removed.
Proof tier: generated artifact (static read of bundles); runtime look is proven only in game.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "homm3_import"))
import measure_owned_unit_presentation as m  # noqa: E402

VISUALS = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3ImportVisuals.cs"
ALLOWLIST = ROOT / "tools" / "homm3_owned_unit_presentation_allowlist.json"
HEXES_MIN, HEXES_MAX = 0.8, 4.0
TIER_SLACK = 0.2  # [min*(1-s), max*(1+s)] of the vanilla tier: HoMM3-proportional sizing may exceed stock
GROUND_TOL = 0.01
SINK = {"22.Idle": -0.30, "01.Walk": -0.50, "14.Attack": -0.60}


def method_body(src: str, signature: str) -> str:
    i = src.find(signature + "(")
    if i < 0:
        return ""
    b = src.index("{", i)
    depth = 0
    for j in range(b, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[b:j + 1]
    return ""


def check_source(errors: list[str]) -> None:
    src = VISUALS.read_text(encoding="utf-8-sig")
    if ".localBounds" in re.sub(r"//.*", "", src):
        errors.append("Homm3ImportVisuals.cs reads SkinnedMeshRenderer.localBounds; fit / plant must use the baked silhouette")
    bake = method_body(src, "private static bool TryGetBakedSkinWorldBounds")
    if "BakeMesh(" not in bake or ", true)" not in bake or "localToWorldMatrix" not in bake:
        errors.append("TryGetBakedSkinWorldBounds must BakeMesh(mesh, true) and map vertices through skin.transform.localToWorldMatrix")
    rend = method_body(src, "internal static bool TryGetRenderableWorldBounds")
    if "TryGetBakedSkinWorldBounds(skin" not in rend:
        errors.append("TryGetRenderableWorldBounds must measure skinned renderers through TryGetBakedSkinWorldBounds")
    for caller in ("internal static void FitSkinnedBattleMesh", "private static bool ApplySkinnedAdventureMapVisualScale",
                   "private static bool AlignOwnedSkinnedFeetToDonor", "internal static void PlaceOwnedSkinnedPreviewAtVanillaMeshPose"):
        body = method_body(src, caller)
        if not body:
            errors.append(f"missing {caller}")
        elif "TryGetRenderableWorldBounds(" not in body:
            errors.append(f"{caller} no longer measures through TryGetRenderableWorldBounds")

    cache_key = method_body(src, "private static bool TryCreateOwnedSkinnedMapFitCacheKey")
    for required in ("template.GetInstanceID()", "entry.BattleHeightHexes", "_battleWorldHeightPerHex.Value",
                     "_adventureMapToBattleHeightRatio.Value", "QualitySettings.skinWeights",
                     "shell.transform", "visual.transform"):
        if required not in cache_key:
            errors.append(f"owned map-fit cache key omits {required}")
    cache_key_type = src[src.find("private readonly struct OwnedSkinnedMapFitCacheKey"):]
    cache_key_type = cache_key_type[:cache_key_type.find("\n\tprivate readonly struct OwnedSkinnedMapFit\n")]
    for required in ("TransformVector(Vector3.right)", "TransformVector(Vector3.up)",
                     "TransformVector(Vector3.forward)", "visual.localRotation", "_initialSkinWeights",
                     "entry.BundleName", "entry.MapPrefabAssetPath",
                     "_initialSkinWeights == other._initialSkinWeights", "_initialSkinWeights.GetHashCode()"):
        if required not in cache_key_type:
            errors.append(f"owned map-fit cache identity omits {required}")

    finish = method_body(src, "static void FinishOwnedSkinnedAdventureMapPresentation")
    finish_order = ("TryCreateOwnedSkinnedMapFitCacheKey", "TryGetValue(cacheKey", "ApplySkinnedAdventureMapVisualScale",
                    "EnsureSkinnedAdventureMapIdle", "AlignOwnedSkinnedFeetToDonor(null, visual)",
                    "OwnedSkinnedMapFitCache[cacheKey]", "TryApplyOwnedSkinnedNativeModelFacing")
    positions = [finish.find(token) for token in finish_order]
    if not finish or any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("owned map-fit cache must miss through exact fit, compatibility, exact final align, then cache before facing")
    if "cachedFit.Template && cachedFit.Template == template" not in finish:
        errors.append("owned map-fit cache hit must validate the live template object to reject recycled instance IDs")
    if "ApplyOwnedSkinnedFeetFloorOffset(visual, cachedFit.FeetOffsetFromFloor)" not in finish:
        errors.append("owned map-fit cache hit must restore the cached floor-relative feet placement")
    if "fitApplied && feetAligned" not in finish or "visual.transform.position.y - floorY" not in finish:
        errors.append("owned map-fit cache must capture only a successful final plant as a floor-relative pivot offset")
    floor_replay = method_body(src, "private static bool ApplyOwnedSkinnedFeetFloorOffset")
    if "p.y = floorY + feetOffsetFromFloor" not in floor_replay:
        errors.append("owned map-fit cache hit must replay its exact floor-relative pivot Y")

    apply_fit = method_body(src, "private static bool ApplySkinnedAdventureMapVisualScale")
    if "TryGetRenderableWorldBounds(visual, out var skinnedBounds)" not in apply_fit or "AlignOwnedSkinnedFeetToDonor(vanilla, visual)" not in apply_fit:
        errors.append("owned map-fit cache miss must retain the exact current-pose measurement and pre-compat fit plant")
    cache_value = src[src.find("private readonly struct OwnedSkinnedMapFit\n"):]
    cache_value = cache_value[:cache_value.find("\n\tstatic readonly List<Entry>")]
    if any(token in cache_value for token in ("Bounds", "MinimumY", "WorldHeight", "FitScale")):
        errors.append("owned map-fit cache must store final scale and floor-relative Y, not a reusable world AABB")


def current_rows(errors: list[str]) -> tuple[dict, dict]:
    table = json.loads(m.IMPORT_TABLE.read_bytes().decode("utf-8-sig"))
    per_hex = float(table["battleWorldHeightPerHex"])
    art = json.loads(m.OWNED_OUT.read_text(encoding="utf-8")) if m.OWNED_OUT.is_file() else {"rows": {}}
    rows = art.get("rows", {})
    jobs = m.owned_jobs(table, None)
    stale = []
    for j in jobs:
        r = rows.get(j["sid"])
        fresh = (r is not None and "error" not in r and art.get("profileVersion") == m.PROFILE_VERSION
                 and r.get("signature") == j["signature"] and r.get("battleHeightHexes") == j["entry"].get("battleHeightHexes")
                 and art.get("battleWorldHeightPerHex") == per_hex)
        if not fresh:
            stale.append(j)
    if stale:
        print(f"owned presentation: re-measuring {len(stale)} changed bundle(s): " + ", ".join(j["sid"] for j in stale[:12]), flush=True)
        measured = m.measure_owned_jobs(stale, per_hex, m.default_workers(), False)
        _, logics = m.core_units()
        for j in stale:
            e = j["entry"]
            rows[j["sid"]] = {"bundle": e["bundleName"], "bundleSource": j["source"], "signature": j["signature"],
                              "battleHeightHexes": e.get("battleHeightHexes"),
                              "tier": logics.get(j["sid"], {}).get("tier"),
                              "presentationDonor": e.get("battlePresentationResPath"), **measured[j["sid"]]}
        sids = {j["sid"] for j in jobs}
        rows = {k: v for k, v in rows.items() if k in sids}
        m.write_owned(rows, table)
    for j in jobs:
        r = rows.get(j["sid"])
        if r is None:
            errors.append(f"{j['sid']}: no presentation row")
        elif "error" in r:
            errors.append(f"{j['sid']}: {r['error']}")
    return rows, table


def violations(rows: dict, bands: dict) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}

    def v(sid: str, check: str, msg: str) -> None:
        out.setdefault(check, {})[sid] = msg

    tiers = bands["heightByTier"]
    bo_max, reach_max = bands["baseOffsetOverHeight"]["max"], bands["reachOverHeight"]["max"]
    for sid, r in sorted(rows.items()):
        if "error" in r:
            continue
        hx = r.get("battleHeightHexes")
        if hx is None or not HEXES_MIN <= hx <= HEXES_MAX:
            v(sid, "hexes", f"battleHeightHexes {hx} outside [{HEXES_MIN}, {HEXES_MAX}]")
        t = tiers.get(str(r.get("tier")))
        if t and not t["min"] * (1 - TIER_SLACK) <= r["height"] <= t["max"] * (1 + TIER_SLACK):
            v(sid, "tierHeight", f"height {r['height']:.2f} outside tier {r['tier']} band "
                                 f"[{t['min'] * (1 - TIER_SLACK):.2f}, {t['max'] * (1 + TIER_SLACK):.2f}]")
        if abs(r["groundGap"]) > GROUND_TOL:
            v(sid, "ground", f"idle-0 lowest vertex {r['groundGap']:+.3f} off the hex floor")
        for slot, floor in SINK.items():
            c = r["clips"].get(slot)
            if c and c["lowMin"] < floor:
                v(sid, "sink:" + slot, f"{slot} sinks to {c['lowMin']:+.3f} (< {floor})")
        if r["baseOffset"] / r["height"] > bo_max:
            v(sid, "baseOffset", f"base centroid {r['baseOffset']:.2f} off the hex centre ({r['baseOffset'] / r['height']:.2f} x height > vanilla max {bo_max})")
        if r["reach"] / r["height"] > reach_max:
            v(sid, "reach", f"reach {r['reach'] / r['height']:.2f} x height > vanilla max {reach_max}")
        missing = [k for k, tex in r.get("basecolorTexture", {}).items() if not tex]
        if missing:
            v(sid, "basecolor", f"materials without <name>_basecolor texture in bundle: {missing}")
        if not r.get("hasOrientationWrap"):
            v(sid, "wrap", "no Orientation / MocapDeliveryRoot wrap under the prefab root")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="run only the static C# source contract; do not measure or write bundle artifacts")
    args = parser.parse_args()
    if args.source_only:
        errors: list[str] = []
        check_source(errors)
        if errors:
            print("HoMM3 owned unit presentation source contract FAILED:")
            for e in errors:
                print("  - " + e)
            return 1
        print("HoMM3 owned unit presentation source contract OK: static bounds and exact-result cache guards (source proof only).")
        return 0

    errors: list[str] = []
    check_source(errors)
    rows, _ = current_rows(errors)
    bands = json.loads(m.NATIVE_OUT.read_text(encoding="utf-8"))["bands"]
    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["allow"]
    found = violations(rows, bands)
    n_allowed = 0
    for check, units in sorted(found.items()):
        for sid, msg in units.items():
            if sid in allow.get(check, {}):
                n_allowed += 1
            else:
                errors.append(f"{sid} [{check}]: {msg}")
    for check, units in sorted(allow.items()):
        for sid in units:
            if sid not in found.get(check, {}):
                errors.append(f"allowlist entry {check}/{sid} no longer violates; remove it from {ALLOWLIST.name}")
    if errors:
        print("HoMM3 owned unit presentation contract FAILED:")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"HoMM3 owned unit presentation contract OK: {len(rows)} units, {n_allowed} allowlisted violation(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
