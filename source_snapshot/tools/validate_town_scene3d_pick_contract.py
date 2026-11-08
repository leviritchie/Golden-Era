#!/usr/bin/env python3
"""Gate: on every staged full-3D town catalog the pointer hits the building that is drawn.

    python tools/validate_town_scene3d_pick_contract.py [--faction rampart ...] [--static-only]

Static (source): the full-3D layer branch of Homm3FactoryCityWorldVisuals builds the pick from the drawn body
meshes (Homm3TownScene3dPick, MeshCollider of each body renderer's own mesh, Read/Write checked, holder under the
BhBuilding so native dispatch bubbles to it) and re-poses it on every camera reposition; the old refit BoxCollider
(TryAlignNativeColliderWithArt) is not used for scene-3D layers; every environment Mesh_ renderer gets an occluder
on a layer the PhysicsRaycaster cannot see (checked against finalEventMask at build) and the PhysicsRaycaster.Raycast
postfix drops hits beyond the nearest occluder.

Measured (generated artifact): tools/homm3_town_scene_meshes/town_full3d_pick.py on every staged fullScene3d
catalog, the native pan under the catalog framing, every town state. Fails on anything the runtime would refuse
(a reachable layer without a prefab or a Mesh_ body, a mesh that is not Read/Write, no environment Mesh_), and
unless the shipped `occluded` model has recall, precision and pixel agreement >= OCCLUDED_MIN for every
interactive building. The `mesh` model (building colliders without occluders) is printed as the share the
occluders carry. Proof tier: source/static + generated artifact; in-game hover/click is runtime-unproven.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
VISUALS = PLUGIN / "Homm3FactoryCityWorldVisuals.cs"
PICK = PLUGIN / "Homm3TownScene3dPick.cs"

OCCLUDED_MIN = 0.999


def static_errors() -> list[str]:
    errs = []
    v = VISUALS.read_text(encoding="utf-8-sig")
    p = PICK.read_text(encoding="utf-8-sig")
    branch = re.search(r"else if \(scene3d && Homm3TownScene3d\.HasLayer\(fraction, item\.LayerId\)\)\s*"
                       r"ApplyScene3dPickOrThrow\(", v)
    if not branch:
        errs.append("Visuals: scene-3D variant branch does not call ApplyScene3dPickOrThrow")
    m = re.search(r"private static void ApplyScene3dPickOrThrow\(.*?\n\t}\n", v, re.S)
    if not m:
        errs.append("Visuals: ApplyScene3dPickOrThrow missing")
    else:
        body = m.group(0)
        for need in ("CollectNativeBuildingBoxColliders", "DisableNativeBuildingCollidersIfPresent",
                     "Homm3TownScene3dPick.BuildOrThrow"):
            if need not in body:
                errs.append(f"Visuals: ApplyScene3dPickOrThrow does not call {need}")
        if "TryAlignNativeColliderWithArt" in body:
            errs.append("Visuals: ApplyScene3dPickOrThrow still refits the native box")
    r = re.search(r"private static void RepositionScene3dLayerOrThrow\(.*?\n\t}\n", v, re.S)
    if not r or "Homm3TownScene3dPick.ReposeOrThrow" not in r.group(0):
        errs.append("Visuals: RepositionScene3dLayerOrThrow does not re-pose the pick")
    elif "TryAlignNativeColliderWithArt" in r.group(0):
        errs.append("Visuals: RepositionScene3dLayerOrThrow refits the native box")
    for need, why in (("AddComponent<MeshCollider>", "MeshCollider per body renderer"),
                      ("collider.convex = false", "concave collider (the drawn surface, not a hull)"),
                      ("mesh.isReadable", "Read/Write check before cooking"),
                      ("Homm3TownSceneMeshBundle.MeshChildPrefix", "holder shares the owned-child prefix"),
                      ("refusing silent pick drift", "fail-closed reposition"),
                      ("OccluderLayer = 31", "occluder layer outside the level67 camera cullingMask 0x9f17"),
                      ("raycaster.finalEventMask", "occluder layer checked against the PhysicsRaycaster event mask"),
                      ("ComputeRayAndDistance", "occlusion on the raycaster's own ray"),
                      ("resultAppendList.RemoveAt", "occluded hits removed, nothing added"),
                      ("module.Pointer != self", "only this raycaster's results (native identity)"),
                      # Native BhBuildings may be mirrored (Castle 'H_build_Tier_3_Level_1' lossy scale
                      # (-445.6, 445.6, 445.6)); refusing them suspended the whole town presentation (black screen
                      # on building the Griffin Tower, 2026-10-01). The holder solves a mirrored local pose and
                      # checks it against the scene root.
                      ("mirrored ? -scale : scale", "mirrored BhBuilding reproduced with a mirrored holder scale"),
                      ("RequireHolderMatchesRootOrThrow(holder, building, sceneRoot);",
                       "holder pose checked against the scene root")):
        if need not in p:
            errs.append(f"Pick: missing {why} ({need!r})")
    env = re.search(r"var environment = Homm3TownScene3d\.EnsureEnvironment\(.*?\);\s*scene3dKeep\.Add\(environment\.name\);"
                    r"\s*Homm3TownScene3dPick\.EnsureEnvironmentOccludersOrThrow\(environment\.transform, camera\);", v, re.S)
    if not env:
        errs.append("Visuals: the full-3D environment does not get its occluders right after EnsureEnvironment")
    reg = re.search(r"internal static int RegisterHarmony\(HarmonyLib\.Harmony harmony\).*?\n\t}\n", v, re.S)
    if not reg or "Homm3TownScene3dPick.RegisterHarmony(harmony)" not in reg.group(0):
        errs.append("Visuals: RegisterHarmony does not register the PhysicsRaycaster occluder postfix")
    if "is not uniform and positive" in p:
        errs.append("Pick: refuses mirrored BhBuildings (a negative lossy scale is a valid native pose)")
    if "BoxCollider" in re.sub(r"///.*", "", p):
        errs.append("Pick: builds or touches a BoxCollider")
    return errs


def measured_errors(factions) -> tuple[list[str], list[str]]:
    sys.path.insert(0, str(ROOT / "tools" / "homm3_town_scene_meshes"))
    import town_full3d_pick as PK  # noqa: E402

    errs, lines = [], []
    dirs = PK.installed_dirs(factions)
    if not dirs:
        return ["no staged fullScene3d catalog found under " + str(PK.SCENE3D)], lines
    rd = PK.IdRenderer()
    try:
        for d in dirs:
            r = PK.measure_faction(d, ("mesh", "occluded"), rd)
            f = r["fraction"]
            mr, orr = r["models"]["mesh"], r["models"]["occluded"]
            lines.append(f"{f:18s} occluded={orr['pixelAgreement']:.4f} withoutOccluders={mr['pixelAgreement']:.4f} "
                         f"poses={r['poses']} states={r['states']}")
            errs += [f"{f}: {e}" for e in r["errors"]]
            if orr["pixelAgreement"] < OCCLUDED_MIN:
                errs.append(f"{f}: pixelAgreement {orr['pixelAgreement']} < {OCCLUDED_MIN} (worst {orr['worstPose']})")
            if not orr["buildings"]:
                errs.append(f"{f}: no interactive building measured")
            for label, b in orr["buildings"].items():
                if b["visiblePx"] == 0:
                    continue
                if b["recall"] < OCCLUDED_MIN:
                    errs.append(f"{f} {label}: recall {b['recall']} < {OCCLUDED_MIN} (visible parts that do not pick it)")
                if b["precision"] is not None and b["precision"] < OCCLUDED_MIN:
                    errs.append(f"{f} {label}: precision {b['precision']} < {OCCLUDED_MIN} (picked where it is not drawn)")
    finally:
        rd.release()
    return errs, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--faction", nargs="*")
    ap.add_argument("--static-only", action="store_true")
    a = ap.parse_args()
    errs = static_errors()
    lines = []
    if not a.static_only:
        e, lines = measured_errors(a.faction)
        errs += e
    for line in lines:
        print(line)
    if errs:
        for e in errs:
            print("FAIL:", e)
        print(f"town scene3d pick contract: FAILED ({len(errs)})")
        return 1
    print("town scene3d pick contract: OK" + (" (static only)" if a.static_only else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
