#!/usr/bin/env python3
"""Contract for the camera-registered 3D town scene lane (Homm3TownScene3d; Conflux first).

Checks, for every staged OfflineUnlockMod/homm3_town_scene_meshes/scene3d/<fraction>/catalog.json:
  * schema matches the runtime and builder constants; fraction == folder and is an owned city-world fraction;
  * layers: non-empty, unique layerId / prefabKey, every layerId is a positions.json layer of that fraction;
  * every meshed layer is reachable at runtime: a building_layer_map.json nativeLevels value (the only
    runtime join for owned city worlds) or an always-shown decoration row. A meshed layer outside that set
    never renders (Conflux tbelhall_4 before nativeLevelSourceOverrides mapped it to Main level 3);
  * unusedLayers (layerId -> reason, the record of layers deliberately left without a native level) name
    positions.json layers that are neither reachable nor meshed;
  * layerDepths: exactly the positions.json layers that are not meshed, each strictly in front of the backdrop
    quad (0 < distance < 79.9, the runtime BackdropDistance 80 minus the HotA layer offset);
  * key/fill light directions are unit vectors, the fill colour is non-negative and not black, fog is "off";
  * referenceCamera and depthScale are sane;
  * the staged bundle matches the recorded sha256/bytes when present, and must be present when config.json
    turns homm3TownScene3d on.
And, statically, that the runtime lane does not call Material.IsKeywordEnabled (throws on this interop).

Full-3D catalogs ("fullScene3d": true; docs/homm3_conflux_full_3d_town.md) must leave nothing 2D:
  * every reachable layer (nativeLevels) has a 3D prefab row: no layer may fall back to a HotA art quad;
  * no row carries a sprite (skirt/hole quad) and layerDepths is empty (nothing is drawn at a quad depth);
  * "backdrop": "hidden" and an environment prefab whose pieces include Mesh_Terrain and a Sky_* dome;
    environment / layer piece names use only the Mesh_ / Sky_ / Fx_ prefixes (never Sprite_ or a quad);
  * the bundle's build report (<bundle>.build_report.txt, written by Homm3TownScene3dBundleBuild) lists every
    catalog prefab with sprites=0;
  * a STAGED full-3D catalog also needs runtime support: Homm3TownScene3d.cs must parse fullScene3d
    (otherwise the runtime would still draw the backdrop and 2D layers under it).
Phase-2 full-3D catalogs ("phase" >= 2) additionally:
  * "references" name only the HoMM3 town screen and building art: nothing from the old 2D backdrop plate, its
    outpaint or any derivative ("plate", "outpaint", "backdrop" are refused);
  * "bundleShaders" is non-empty and every name is declared by a .shader under
    tools/homm3_town_scene_meshes/unity/shaders that exposes _TimeOffset / _TimeScale (deterministic renders);
  * every Fx_ piece sits in a prefab whose build-report line has bins or particles (it was really built), and
    "notAnimated" maps layerId -> a non-empty reason.
Phase-3 catalogs ("phase" >= 3) additionally carry "terrainDetail": every source is a Texture2D read from the
installed game's own .assets (file + pathId + sha256), and nothing names an AI upscale / outpaint / Meshy lineage.
Phase-3b catalogs ("phaseRevision" >= "3b") additionally carry "waterLook": its sources are game .assets textures
(file + pathId + sha256) and its shader is a declared bundle shader exposing _NormalMap / _ShoreRange / _ShoreOut /
_SpecDir (the vanilla river normal map, the feathered shore and the fixed specular direction).
Phase-4 catalogs ("phaseRevision" >= "4") carry "animationAudit": every catalog layer whose HoMM3 DEF has more than
one frame (layers/anims/metadata.json) has a row with defFrames, what moves, and a non-empty list of its Fx_ effect
pieces (pieces of that layer, or of the co-present layer named in sharedWith); a missing row or piece fails.
Phase-5 catalogs ("phaseRevision" >= "5") carry "nearField": the extension albedo's sources are game .assets textures
(file + pathId + sha256), the painting is declared low-frequency colour only with paintedCrops false, the seam blend is
world-space, the near terrain pieces are baked at >= the buildings' median texels/px, and every dressing bin is a
built Mesh_ environment piece.
Phase-6 catalogs ("phaseRevision" >= "6") carry "periphery" (vertex intrusion count 0, outer terrain/water/forest/
rock pieces, meshyCredits stated; continued water may be declared absent with periphery.water.required = false and
a reason; periphery.scatter._tree/_rock follow the faction profile's PERIPHERY_SCATTER declaration: a required kind names
the Mesh_Outer_* prefixes that must be built, a kind declared not required carries its reason and builds nothing, the
near-field density is measured or the profile's value, and a fraction with no declaration fails), a v2 authored rest pose verified against installed cityHuman2 native data, and
"panCoverage": a post-settle triangle-height raster beside the catalog (sha256 pinned). Sampled cursor, sweep and
mode-transition rays (16:9 / 4096x2160 / 21:9) are raymarched against this geometry-grounded proxy; the canonical
16:9 path with outer coverage stripped must find voids. This gate rejects sampled gaps, not exact pixel occlusion or
all possible motion. Default/pan editor renders remain required for visual acceptance.
Phase-6b catalogs ("phaseRevision" >= "6b") carry "terrainStreak": every shipped terrain triangle (main pieces and the
back layer that continues the far surface under ridges) re-measured beside the catalog (sha256 pinned) must span at
most STREAK_RATIO_CAP in rest-camera forward depth (max/min over its vertices: a ridge curtain is a triangle running
along the rest rays), and the cut triangles stored with it must each exceed the cap (negative: the measurement sees
the curtains the phase-6 grid shipped).
Full-3D catalogs carrying "props" (the 2026-09-30 streak-cover props pass, tools/homm3_town_scene_meshes/
town_t2_props.py; schema town_t2_props.v1): every type's bin is a built Mesh_Prop_* environment piece with triangles
and instances, the per-type instances sum to props.instances, every Mesh_Prop_* environment piece is declared,
props.pass names its budget file (artifacts/meshy_town_scene_meshes/_budget_<pass>.json) which lists this fraction,
props.meshyCredits equals this fraction's ledger spend for the pass, and the pass's whole ledger spend is within the
budget's cap. A missing ledger or budget file fails (the spend cannot be proven).
Full-3D catalogs whose bundle shaders read the camera depth texture, or that ship Fx_SsrWater* pieces (the opt-in SSR water, tools/homm3_town_scene_meshes/
town_full3d_ssr_water.py; schema town_full3d_ssr_water.v1) must declare waterLook.screenSpaceReflection with requiresCameraDepthTexture and
requiresCameraColorTexture true; its shader is the only depth reader, a declared bundle shader with the FlowWater
shore / normal-map / specular inputs and no GrabPass; its pieces are built Fx_ environment pieces; and
Homm3TownScene3d.cs requests the depth texture while the scene is shown and restores the camera on clear.
Full-3D catalogs shipping Mesh_Cloth_<layer>_b<k> pieces (the cloth wave, tools/homm3_town_scene_meshes/
town_full3d_cloth.py; schema town_full3d_cloth.v1; docs/homm3_town_cloth_wave.md) must declare every one in clothLook
with finite prefab-frame wave vectors (|power| <= 20% of the banner length, speed 0.5..12 rad/s) and the vertex-colour
sha256; each cloth layer's animationAudit effects are exactly its cloth pieces and its old Fx_Glow_ overlay is gone;
buildingDepth measures the pieces with role cloth; and Homm3TownScene3d.cs applies the native Hex/Lit FLAG variant with
the world-space conversion and re-derives it when the root is placed.
Candidates outside the plugin tree are checked with --catalog <path> (bundle and build report beside it).
Proof tier: source/static + generated artifact. Not runtime proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
SCENE3D = PLUGIN / "homm3_town_scene_meshes" / "scene3d"
RUNTIME = PLUGIN / "Homm3TownScene3d.cs"
BUILDER = ROOT / "tools" / "homm3_town_scene_meshes" / "build_town_scene3d_bundle.py"
GAME_SYMBOLS = PLUGIN / "GameSymbols.cs"
CONFIG = PLUGIN / "config.json"
REFS = PLUGIN / "homm3_runtime_assets" / "town_scene_refs"
BACKDROP_LIMIT = 79.9
DEFAULT_GAME_DATA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
GAME_DATA = DEFAULT_GAME_DATA
FILE_HASH_CHUNK_SIZE = 1 << 20
PAN_DEFAULT_DEVICE = "cuda"


def fail(msg: str) -> None:
    print(f"town-scene3d-contract: {msg}", file=sys.stderr)
    raise SystemExit(1)


def csharp_method_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        fail(f"runtime load boundary: missing method {signature!r}")
    opening = source.find("{", start + len(signature))
    if opening < 0:
        fail(f"runtime load boundary: missing body for {signature!r}")
    depth = 0
    i = opening
    state = "code"
    verbatim = False
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line-comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block-comment"
                i += 2
                continue
            if ch == '"':
                verbatim = i > 0 and source[i - 1] == "@"
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[opening + 1:i]
        elif state == "line-comment":
            if ch in "\r\n":
                state = "code"
        elif state == "block-comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
        elif state == "string":
            if verbatim and ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                state = "code"
            elif not verbatim and ch == "\\":
                i += 2
                continue
        elif state == "char":
            if ch == "'":
                state = "code"
            elif ch == "\\":
                i += 2
                continue
        i += 1
    fail(f"runtime load boundary: unterminated body for {signature!r}")


def check_runtime_load_boundary() -> None:
    preloader_path = PLUGIN / "Homm3RuntimeManifestPreloader.cs"
    visuals_path = PLUGIN / "Homm3FactoryCityWorldVisuals.cs"
    for path in (RUNTIME, preloader_path, visuals_path):
        if not path.is_file():
            fail(f"runtime load boundary: missing {path}")

    runtime = RUNTIME.read_text(encoding="utf-8")
    preloader = preloader_path.read_text(encoding="utf-8")
    visuals = visuals_path.read_text(encoding="utf-8")
    catalog_gate = csharp_method_body(runtime, "internal static void ValidateCatalogPayloadsOrFail(")
    selected_gate = csharp_method_body(runtime, "internal static void ValidateFactionPayloadOrFail(")
    all_factions_gate = csharp_method_body(runtime, "internal static void ValidateAllPayloadsOrFail(")
    catalog_load = csharp_method_body(runtime, "private static int LoadCatalogPrefabsOrThrow(")
    bundle_path = csharp_method_body(runtime, "private static string ResolveBundlePathOrThrow(")
    catalog_parse = csharp_method_body(runtime, "private static SceneCatalog ParseCatalogOrThrow(")
    preloader_entry = csharp_method_body(preloader, "internal static void PrewarmAtMainMenuOrFail(")
    world_apply = csharp_method_body(visuals, "internal static void ApplyOwnedFactoryWorldArt(")
    apply = csharp_method_body(visuals, "private static void ApplyOwnedFactoryWorldArtOrThrow(")

    eager_markers = ("AssetBundle.LoadFromFile(", "LoadAsset<GameObject>(", "LoadPrefabOrThrow(",
                     "LoadPrefabByKeyOrThrow(", "LoadCatalogPrefabsOrThrow(")
    if any(marker in catalog_gate for marker in eager_markers):
        fail("main-menu catalog validation must not load AssetBundles or prefab assets")
    if "ValidateAllPayloadsOrFail(" in catalog_gate:
        fail("main-menu catalog validation must not delegate to all-faction prefab validation")
    if "ResolveBundlePathOrThrow(catalog)" not in catalog_gate:
        fail("main-menu catalog validation must resolve each catalog bundle file")
    if "Homm3TownScene3d.ValidateCatalogPayloadsOrFail(log);" not in preloader_entry:
        fail("main-menu preloader must run metadata and bundle-file validation")
    if any(marker in preloader_entry for marker in eager_markers) or \
            "Homm3TownScene3d.ValidateAllPayloadsOrFail(" in preloader_entry:
        fail("main-menu preloader must not load town-scene AssetBundles or prefab assets")
    if "LoadCatalogPrefabsOrThrow(catalog)" not in all_factions_gate:
        fail("explicit all-faction runtime diagnostic must retain deep prefab validation")
    if "TryGetCatalog(fraction, out var catalog)" not in selected_gate:
        fail("selected-faction preflight must resolve only the requested fraction catalog")
    if any(marker in selected_gate for marker in ("Directory.GetDirectories(", "ResolvePluginFolder(",
                                                    "ValidateAllPayloadsOrFail(")):
        fail("selected-faction preflight must not enumerate or load other factions")
    if "ParseBundleBytesOrThrow(Str(root, \"bundleBytes\"), fraction, path)" not in catalog_parse:
        fail("scene catalog parser must strictly read bundleBytes for menu file validation")
    for marker in ("File.Exists(path)", "new FileInfo(path).Length", "catalog.BundleBytes"):
        if marker not in bundle_path:
            fail(f"runtime bundle-file validation is missing {marker!r}")

    cache_check = selected_gate.find("if (catalog.PayloadValidated)")
    selected_load = selected_gate.find("LoadCatalogPrefabsOrThrow(catalog)")
    cache_set = selected_gate.find("catalog.PayloadValidated = true")
    if cache_check < 0 or not (cache_check < selected_load < cache_set):
        fail("selected-faction preflight must validate once and cache only that catalog's declared prefabs")
    for marker in ("LogFatal", "before presentation changes", "no 2D fallback"):
        if marker not in selected_gate:
            fail(f"selected-faction load failure must remain fail-closed and diagnostic ({marker!r})")
    for marker in ("catalog.PrefabKeyByLayer", "LoadPrefabOrThrow(catalog, pair.Key)",
                   "catalog.FullScene3d", "catalog.EnvironmentPrefabKey",
                   "LoadPrefabByKeyOrThrow(catalog, EnvironmentCacheKey"):
        if marker not in catalog_load:
            fail(f"selected-faction preflight is missing {marker!r}")
    preflight = "Homm3TownScene3d.ValidateFactionPayloadOrFail(fraction);"
    owner_at = world_apply.find("OwnsActiveFactoryCityWorld(fraction)")
    active_at = world_apply.find("Homm3TownScene3d.IsActiveFor(fraction)")
    preflight_at = world_apply.find(preflight)
    rollback_try_at = world_apply.find("\n\t\ttry")
    mutation_at = world_apply.find("ApplyOwnedFactoryWorldArtOrThrow(fraction)")
    if not (0 <= owner_at < active_at < preflight_at < rollback_try_at < mutation_at):
        fail("selected-faction assets must load after the ownership guard and before presentation/rollback mutation")
    if preflight in apply:
        fail("selected-faction preflight must stay outside the mutating apply/rollback path")
    preflight_prefix = world_apply[owner_at:preflight_at]
    early_mutations = ("ClearOwnedFactoryWorldArt(", "HideDonorPresentation(", "EnsureWorldPlate(",
                       "EnsureWorldBackdrop(", "RemoveBuildingArtChild(", "SetActive(", "Destroy(",
                       "renderer.enabled", "collider.enabled")
    if any(marker in preflight_prefix for marker in early_mutations):
        fail("factory city wrapper must not mutate presentation before selected-faction asset preflight")


def const(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text(encoding="utf-8"))
    if not m:
        fail(f"{path.name}: pattern {pattern!r} not found")
    return m.group(1)


def unit(v, what: str) -> None:
    if not isinstance(v, list) or len(v) != 3 or not all(isinstance(x, (int, float)) for x in v):
        fail(f"{what} must be 3 numbers")
    n = math.sqrt(sum(x * x for x in v))
    if abs(n - 1) > 1e-3:
        fail(f"{what} is not a unit vector (|v|={n:.4f})")


def revision_at_least(cat: dict, minimum: str) -> bool:
    value = str(cat.get("phaseRevision") or "")
    if not value:
        return False
    current = re.fullmatch(r"([0-9]+)([a-z]?)", value)
    target = re.fullmatch(r"([0-9]+)([a-z]?)", minimum)
    if current is None or target is None:
        fail(f"invalid phaseRevision {value!r}")
    return (int(current[1]), current[2]) >= (int(target[1]), target[2])


FULL_PREFIXES = ("Mesh_", "Sky_", "Fx_")
FX_SHADER_DIR = ROOT / "tools" / "homm3_town_scene_meshes" / "unity" / "shaders"
FORBIDDEN_REFERENCES = ("plate", "outpaint", "backdrop")


def check_phase2(cat: dict, where: str, report_lines: dict, folder: Path | None = None,
                 device: str = PAN_DEFAULT_DEVICE) -> str:
    """Phase-2 rules (module docstring). Returns a short summary for the OK line."""
    if int(cat.get("phase") or 1) < 2:
        return ""
    refs = cat.get("references")
    if not isinstance(refs, list) or not refs:
        fail(f"{where}: phase 2 requires a non-empty references list (HoMM3 screen + building art)")
    bad = [r for r in refs if any(w in str(r).lower() for w in FORBIDDEN_REFERENCES)]
    if bad:
        fail(f"{where}: references use the old 2D backdrop / outpaint lineage: {bad}")
    shaders = cat.get("bundleShaders")
    if not isinstance(shaders, list) or not shaders:
        fail(f"{where}: phase 2 requires bundleShaders")
    declared = {}
    for f in sorted(FX_SHADER_DIR.glob("*.shader")) if FX_SHADER_DIR.is_dir() else []:
        txt = f.read_text(encoding="utf-8")
        m = re.search(r'^\s*Shader\s+"([^"]+)"', txt, re.M)
        if m:
            declared[m.group(1)] = txt
    for name in shaders:
        if name not in declared:
            fail(f"{where}: bundleShaders {name} is not declared under {FX_SHADER_DIR}")
        if "_TimeOffset" not in declared[name] or "_TimeScale" not in declared[name]:
            fail(f"{where}: shader {name} lacks _TimeOffset/_TimeScale (editor renders need a frozen clock)")
    rows = [(cat.get("environment") or {}).get("prefabKey"), (cat.get("environment") or {}).get("pieces") or []]
    prefabs = [tuple(rows)] + [(r.get("prefabKey"), r.get("pieces") or []) for r in cat.get("layers") or []]
    n_fx = 0
    for key, pieces in prefabs:
        fx = [n for n in pieces if n.startswith("Fx_")]
        n_fx += len(fx)
        if fx and report_lines:
            ln = report_lines.get(key, "")
            built = re.search(r" bins=(\d+)", ln), re.search(r" particles=(\d+)", ln)
            if not any(m and int(m.group(1)) > 0 for m in built):
                fail(f"{where}: prefab {key} lists {fx} but its build report shows no bins/particles ({ln!r})")
    na = cat.get("notAnimated") or {}
    if not isinstance(na, dict) or not all(isinstance(v, str) and v.strip() for v in na.values()):
        fail(f"{where}: notAnimated must map layerId -> non-empty reason")
    extra = ""
    if int(cat.get("phase") or 1) >= 3:
        td = cat.get("terrainDetail")
        srcs = td.get("sources") if isinstance(td, dict) else None
        if not isinstance(srcs, list) or not srcs:
            fail(f"{where}: phase 3 requires terrainDetail.sources (vanilla game terrain textures)")
        for r in srcs:
            if not (str(r.get("file", "")).endswith(".assets") and isinstance(r.get("pathId"), int)
                    and re.fullmatch(r"[0-9a-f]{64}", str(r.get("sha256", "")))):
                fail(f"{where}: terrainDetail source {r!r} is not a game .assets Texture2D with pathId + sha256")
        blob = json.dumps(td).lower()
        for w in ("upscal", "meshy", "esrgan"):
            if w in blob.replace("no ai upscale, outpaint or meshy", ""):
                fail(f"{where}: terrainDetail names a forbidden lineage ({w})")
        extra = f" detail={len(srcs)}"
    if revision_at_least(cat, "3b"):
        wl = cat.get("waterLook")
        wsrc = wl.get("sources") if isinstance(wl, dict) else None
        if not isinstance(wsrc, list) or not wsrc:
            fail(f"{where}: phase 3b requires waterLook.sources (the vanilla river textures)")
        for r in wsrc:
            if not (str(r.get("file", "")).endswith(".assets") and isinstance(r.get("pathId"), int)
                    and re.fullmatch(r"[0-9a-f]{64}", str(r.get("sha256", "")))):
                fail(f"{where}: waterLook source {r!r} is not a game .assets Texture2D with pathId + sha256")
        wsh = wl.get("shader")
        if wsh not in shaders or wsh not in declared:
            fail(f"{where}: waterLook shader {wsh!r} is not a declared bundle shader")
        missing = [p for p in ("_NormalMap", "_ShoreRange", "_ShoreOut", "_SpecDir") if p not in declared[wsh]]
        if missing:
            fail(f"{where}: waterLook shader {wsh} lacks {missing} (vanilla normal map / shore feather / specular)")
        extra += f" water={len(wsrc)}"
    if revision_at_least(cat, "4"):
        extra += check_animation_audit(cat, where)
    if revision_at_least(cat, "5"):
        extra += check_near_field(cat, where)
    if revision_at_least(cat, "6"):
        extra += check_pan_coverage(cat, where, folder, device=device)
    if revision_at_least(cat, "6b"):
        extra += check_terrain_streak(cat, where, folder)
    if "buildingDepth" in cat:
        extra += check_building_depth(cat, where, folder)
    return f" phase={cat.get('phase')} fx={n_fx} shaders={len(shaders)}" + extra


PROPS_LEDGER = ROOT / "artifacts" / "meshy_town_scene_meshes" / "_ledger.jsonl"


def check_props(cat: dict, where: str) -> str:
    """The props block written by town_t2_props.py stage (see module docstring)."""
    pr = cat.get("props")
    env_pieces = set((cat.get("environment") or {}).get("pieces") or [])
    declared_bins = sorted(n for n in env_pieces if n.startswith("Mesh_Prop_"))
    if pr is None:
        if declared_bins:
            fail(f"{where}: environment has prop bins {declared_bins} but the catalog has no props block")
        return ""
    if not isinstance(pr, dict) or pr.get("schema") != "town_t2_props.v1":
        fail(f"{where}: props block schema {pr.get('schema') if isinstance(pr, dict) else pr!r} != town_t2_props.v1")
    types = pr.get("types")
    if not isinstance(types, dict) or not types:
        fail(f"{where}: props.types must be a non-empty map")
    bins = []
    for name, row in types.items():
        b = row.get("bin") if isinstance(row, dict) else None
        if not (isinstance(b, str) and b.startswith("Mesh_Prop_") and b in env_pieces):
            fail(f"{where}: props type {name!r} bin {b!r} is not a Mesh_Prop_* environment piece")
        if not (isinstance(row.get("instances"), int) and row["instances"] > 0
                and isinstance(row.get("tris"), int) and row["tris"] > 0):
            fail(f"{where}: props type {name!r} needs instances > 0 and tris > 0")
        bins.append(b)
    if sorted(bins) != declared_bins:
        fail(f"{where}: Mesh_Prop_* environment pieces {declared_bins} != props.types bins {sorted(bins)}")
    if pr.get("instances") != sum(r["instances"] for r in types.values()):
        fail(f"{where}: props.instances {pr.get('instances')!r} != the per-type sum")
    credits, pas = pr.get("meshyCredits"), pr.get("pass")
    if not isinstance(credits, int) or credits < 0 or not (isinstance(pas, str) and re.fullmatch(r"[\w-]+", pas)):
        fail(f"{where}: props needs an int meshyCredits and a pass name")
    budget = PROPS_LEDGER.parent / f"_budget_{pas}.json"
    if not budget.is_file() or not PROPS_LEDGER.is_file():
        fail(f"{where}: props pass {pas}: budget {budget.name} or ledger {PROPS_LEDGER.name} missing")
    bud = json.loads(budget.read_text(encoding="utf-8"))
    frac = cat.get("fraction")
    if bud.get("pass") != pas or frac not in (bud.get("towns") or []) or not isinstance(bud.get("cap"), int):
        fail(f"{where}: budget {budget.name} does not cover {frac} for pass {pas} with an int cap")
    total = mine = 0
    for ln in PROPS_LEDGER.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("pass") == pas:
                total += int(r.get("credits", 0))
                mine += int(r.get("credits", 0)) if r.get("faction") == frac else 0
    if mine != credits:
        fail(f"{where}: props.meshyCredits {credits} != the ledger's {mine} for {frac} in pass {pas}")
    if total > bud["cap"]:
        fail(f"{where}: props pass {pas} ledger spend {total} exceeds its cap {bud['cap']}")
    return f" props={pr['instances']}/{len(types)}types cr={credits} pass={total}/{bud['cap']}"


def check_near_field(cat: dict, where: str) -> str:
    """Phase 5: the extension's albedo is synthesised from game .assets terrain textures (file + pathId + sha256), the
    painting is low-frequency colour only (no painted crops), the seam blends in world space, a near texture piece is
    at least as dense as the buildings' median texels/px, and every dressing bin is a Mesh_ piece of the environment
    with triangles."""
    nf = cat.get("nearField")
    if not isinstance(nf, dict):
        fail(f"{where}: phase 5 requires nearField")
    ea = nf.get("extensionAlbedo") or {}
    srcs = ea.get("sources")
    if not isinstance(srcs, list) or not srcs:
        fail(f"{where}: nearField.extensionAlbedo.sources must list the vanilla terrain textures")
    for r in srcs:
        if not (str(r.get("file", "")).endswith(".assets") and isinstance(r.get("pathId"), int)
                and re.fullmatch(r"[0-9a-f]{64}", str(r.get("sha256", "")))):
            fail(f"{where}: nearField source {r!r} is not a game .assets Texture2D with pathId + sha256")
    if ea.get("paintedCrops") is not False:
        fail(f"{where}: nearField.extensionAlbedo.paintedCrops must be false (no upscaled painted crops)")
    if "low-frequency" not in str(ea.get("paintingRole", "")):
        fail(f"{where}: nearField.extensionAlbedo.paintingRole must declare the painting low-frequency only")
    blob = json.dumps(nf).lower()
    for w in ("upscal", "outpaint", "esrgan", "backdrop"):
        if w in blob:
            fail(f"{where}: nearField names a forbidden lineage ({w})")
    sb = nf.get("seamBlend") or {}
    if sb.get("space") != "world" or not (isinstance(sb.get("bandM"), (int, float)) and sb["bandM"] > 0):
        fail(f"{where}: nearField.seamBlend must be a world-space band with bandM > 0")
    pieces = nf.get("texturePieces")
    if not isinstance(pieces, list) or not pieces:
        fail(f"{where}: nearField.texturePieces missing")
    bld = nf.get("buildingsTexelsPerPx")
    if not isinstance(bld, (int, float)) or bld <= 0:
        fail(f"{where}: nearField.buildingsTexelsPerPx missing")
    env_pieces = set((cat.get("environment") or {}).get("pieces") or [])
    for pc in pieces:
        if pc.get("name") not in env_pieces:
            fail(f"{where}: nearField texture piece {pc.get('name')!r} is not an environment piece")
    near = [pc for pc in pieces if str(pc.get("name", "")).startswith("Mesh_TerrainNear")]
    if not near or min(float(pc.get("texelsPerPx") or 0) for pc in near) < bld:
        fail(f"{where}: near terrain pieces must be baked at >= the buildings' {bld} texels/px")
    dress = nf.get("dressing")
    if not isinstance(dress, dict) or not dress:
        fail(f"{where}: nearField.dressing missing (near-field geometry)")
    for nm, row in dress.items():
        if not nm.startswith("Mesh_") or nm not in env_pieces or not (isinstance(row, dict) and row.get("tris", 0) > 0):
            fail(f"{where}: nearField dressing {nm!r} is not a built Mesh_ environment piece with triangles")
    if not isinstance(nf.get("hudBottomPx"), int) or not isinstance(nf.get("meshyCredits"), int):
        fail(f"{where}: nearField must state hudBottomPx and meshyCredits")
    return f" nearPieces={len(near)} dressing={len(dress)}"


PAN_MODULE_DIR = ROOT / "tools" / "homm3_town_scene_meshes"
PAN_MAX_STEPS = None
PAN_BATCH = None
PAN_EL_MIN = None


def load_pan_constants() -> None:
    """Import the NumPy-backed pan module only for full validation or direct pan-ray tests."""
    global PAN_MAX_STEPS, PAN_BATCH, PAN_EL_MIN
    if PAN_MAX_STEPS is not None:
        return
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    from town_gpu_pan import MAX_STEPS, PAN_BATCH as batch, PAN_EL_MIN as elevation_min

    PAN_MAX_STEPS = MAX_STEPS
    PAN_BATCH = batch
    PAN_EL_MIN = elevation_min

# A ray that reaches no ground must meet the sky dome at least this high (the horizon).
PAN_NEG_MIN = 0.01     # the negative check (outer coverage stripped) must find at least this share of voids
STREAK_RATIO_CAP = 1.25  # phase 6b: max/min rest forward depth over any shipped terrain triangle


def check_framing(ref: dict, where: str, v2: bool) -> str:
    """Optional referenceCamera.framing (town_full3d_framing.v1): bounds mirror Homm3TownScene3d.ParseFramingOrThrow,
    and the block must carry its own measurement (no building out of view at rest after framing)."""
    fr = ref.get("framing")
    if fr is None:
        return ""
    if not v2:
        fail(f"{where}: referenceCamera.framing needs v2 rest-pose seating")
    if fr.get("schema") != "town_full3d_framing.v1":
        fail(f"{where}: referenceCamera.framing schema {fr.get('schema')!r}")
    zoom, pan, q = fr.get("zoom"), fr.get("panScale"), fr.get("aimRotation")
    if not isinstance(zoom, (int, float)) or not 1.0 <= zoom <= 1.6:
        fail(f"{where}: framing zoom {zoom!r} outside [1, 1.6]")
    if not isinstance(pan, (int, float)) or not 0 < pan <= 1:
        fail(f"{where}: framing panScale {pan!r} outside (0, 1]")
    if (not isinstance(q, list) or len(q) != 4 or abs(sum(v * v for v in q) - 1) > 1e-3 or q[3] < 0.98):
        fail(f"{where}: framing aimRotation must be a unit quaternion with w >= 0.98 (a nudge, not a new view)")
    after = ((fr.get("measured") or {}).get("after") or {})
    if not after or after.get("buildingsOutAtRest") != []:
        fail(f"{where}: framing lacks measured.after with 0 buildings out of view at rest")
    if not str(fr.get("reason") or "").strip():
        fail(f"{where}: framing has no reason")
    return f" framing=zoom{zoom}/pan{pan}"


def load_camera_rest_pose_contract() -> dict:
    """Load the inexpensive pinned row so a catalog mismatch can fail before native asset work."""
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    import conflux_town_camera_pan as pan

    return pan.rest_pose_contract()


def verify_native_camera_rest_pose(where: str, expected: dict | None = None) -> None:
    """Verify the installed native camera source against its pinned camera extraction record."""
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    import conflux_town_camera_pan as pan
    import extract_city_camera_pan as extractor

    expected = expected if expected is not None else pan.rest_pose_contract()
    if extractor.GAME != GAME_DATA or extractor.LEVELS.get("cityHuman2") != "level67":
        fail(f"{where}: native camera extractor no longer targets the installed cityHuman2/level67 scene")
    level = GAME_DATA / expected["sourceLevelFile"]
    resources = GAME_DATA / "resources.assets"
    if not level.is_file() or not resources.is_file():
        fail(f"{where}: installed level67 and resources.assets are required to verify native camera provenance")
    doc = json.loads(pan.PAN_JSON.read_text(encoding="utf-8"))
    files = doc.get("gameFiles", {})
    schema = doc.get("schema")
    if schema == "homm3.vanilla_city_camera_pan.v2":
        rows = doc.get("cities") or []
        expected_files = set().union(*(extractor.consumed_input_file_names(row["level"],
                                                                           row["settingsRef"]["file"])
                                       for row in rows)) if rows else set()
        if set(files) != expected_files:
            fail(f"{where}: v2 camera extraction file set differs from its consumed inputs")
        if Path(str(doc.get("gameDataRoot", ""))).resolve() != GAME_DATA.resolve():
            fail(f"{where}: camera extraction gameDataRoot does not match --game-data-root")
        for name, digest in files.items():
            path = GAME_DATA / name
            if not path.is_file() or extractor.sha256(path) != digest:
                fail(f"{where}: installed {name} differs from camera extraction record")
    elif schema == "homm3.vanilla_city_camera_pan.v1" and GAME_DATA.resolve() == DEFAULT_GAME_DATA.resolve():
        # The checked-in Golden record predates exact hashes for the shared scene inputs and camera FOV.
        if extractor.sha256(level) != expected["sourceLevelSha256"]:
            fail(f"{where}: installed level67 differs from restPose.sourceLevelSha256")
        if extractor.sha256(resources) != files.get("resources.assets"):
            fail(f"{where}: installed resources.assets differs from camera extraction record")
    else:
        fail(f"{where}: unsupported or legacy camera extraction schema {schema!r} for selected game data")
    try:
        native = extractor.extract("cityHuman2", "level67", {}, game_data_root=GAME_DATA)
    except (Exception, SystemExit) as exc:
        fail(f"{where}: could not re-extract cityHuman2 camera from installed native assets: {exc}")
    pinned = pan.load()
    if schema == "homm3.vanilla_city_camera_pan.v1":
        # Explicit v1 compatibility: fieldOfView was not present in the historic Golden row.
        native["camera"].pop("fieldOfView", None)
    if native != pinned:
        fail(f"{where}: vanilla_city_camera_pan.json cityHuman2 row differs from installed native camera/settings")


def check_camera_provenance_catalogs(catalog_dir: Path, source_catalog_dir: Path,
                                    canonical_camera_json: Path) -> int:
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    import conflux_town_camera_pan as pan
    import extract_city_camera_pan as extractor

    if not catalog_dir.is_dir() or not source_catalog_dir.is_dir():
        fail("camera-provenance-only requires existing target and source catalog directories")
    if not canonical_camera_json.is_file():
        fail(f"camera-provenance-only canonical Golden camera JSON is missing: {canonical_camera_json}")
    if (catalog_dir.resolve() == source_catalog_dir.resolve() or catalog_dir.resolve() in source_catalog_dir.resolve().parents
            or source_catalog_dir.resolve() in catalog_dir.resolve().parents):
        fail("camera-provenance-only source and target catalog directories must be separate")
    target_paths = {p.parent.name: p for p in catalog_dir.glob("*/catalog.json")}
    source_paths = {p.parent.name: p for p in source_catalog_dir.glob("*/catalog.json")}
    if len(target_paths) != 12 or target_paths.keys() != source_paths.keys():
        fail(f"camera-provenance-only requires matching all-12 catalog sets; target={sorted(target_paths)}, "
             f"source={sorted(source_paths)}")
    expected = pan.rest_pose_contract("cityHuman2", pan_json=pan.PAN_JSON)
    row = pan.load("cityHuman2", pan.PAN_JSON)
    camera_doc = json.loads(pan.PAN_JSON.read_text(encoding="utf-8"))
    if len(camera_doc.get("cities", [])) != 1 or camera_doc["cities"][0].get("scene") != "cityHuman2":
        fail("current port camera JSON must contain only the cityHuman2 native camera row")
    canonical_doc = json.loads(canonical_camera_json.read_text(encoding="utf-8"))
    if canonical_doc.get("schema") != "homm3.vanilla_city_camera_pan.v2":
        fail("canonical Golden camera JSON must use the v2 exact consumed-file provenance schema")
    if Path(str(canonical_doc.get("gameDataRoot", ""))).resolve() != DEFAULT_GAME_DATA.resolve():
        fail("canonical Golden camera JSON gameDataRoot does not match the installed Golden Era data")
    canonical_rows = [r for r in canonical_doc.get("cities", []) if r.get("scene") == "cityHuman2"]
    if len(canonical_rows) != 1 or len(canonical_doc.get("cities", [])) != 1:
        fail("canonical Golden camera JSON must contain only the cityHuman2 native camera row")
    canonical_row = canonical_rows[0]
    canonical_files = canonical_doc.get("gameFiles", {})
    canonical_expected = extractor.consumed_input_file_names(
        canonical_row["level"], canonical_row["settingsRef"]["file"])
    if set(canonical_files) != canonical_expected:
        fail("canonical Golden camera JSON file set differs from its consumed inputs")
    for name, digest in canonical_files.items():
        path = DEFAULT_GAME_DATA / name
        if not path.is_file() or extractor.sha256(path) != digest:
            fail(f"canonical Golden consumed source file differs from its camera JSON: {path}")
    canonical = pan.load("cityHuman2", canonical_camera_json)
    differences = pan.native_layout_differences(row, canonical)
    if differences:
        fail(f"port cityHuman2 camera differs from current Golden extraction at {differences}; "
             "catalog framing needs measured adjustment")
    fov = row.get("camera", {}).get("fieldOfView")
    if not isinstance(fov, (int, float)) or not math.isfinite(fov):
        fail("current port camera extraction has no finite MainCamera field of view")

    def without_rest_pose(catalog: dict) -> dict:
        result = dict(catalog)
        reference = dict(result.get("referenceCamera") or {})
        reference.pop("restPose", None)
        result["referenceCamera"] = reference
        return result

    for faction, target_path in sorted(target_paths.items()):
        source_path = source_paths[faction]
        source = json.loads(source_path.read_text(encoding="utf-8"))
        target = json.loads(target_path.read_text(encoding="utf-8"))
        reference = target.get("referenceCamera") or {}
        if target.get("schema") != "homm3_town_scene3d_catalog.v2" or not target.get("fullScene3d"):
            fail(f"{target_path}: expected a full-3D v2 catalog")
        if target.get("referenceCamera", {}).get("restPose") != expected:
            fail(f"{target_path}: restPose differs from current port native camera extraction")
        if source.get("referenceCamera", {}).get("restPose") == expected:
            fail(f"{target_path}: source catalog was not actually retargeted")
        if not isinstance(reference.get("fov"), (int, float)) or not math.isclose(
                float(reference["fov"]), float(fov), rel_tol=0.0, abs_tol=1e-5):
            fail(f"{target_path}: catalog FOV differs from current port MainCamera")
        if without_rest_pose(source) != without_rest_pose(target):
            fail(f"{target_path}: fields other than referenceCamera.restPose differ from the Golden source catalog")

    verify_native_camera_rest_pose("current port town catalogs", expected)
    print(f"town-scene3d-camera-provenance: OK catalogs={len(target_paths)} camera/settings=port-native-compatible")
    return len(target_paths)


def compare_rest_pose(cat: dict, where: str, expected: dict) -> None:
    actual = (cat.get("referenceCamera") or {}).get("restPose")
    if actual != expected:
        fail(f"{where}: referenceCamera.restPose differs from the extracted cityHuman2 rest pose")


def check_rest_pose(cat: dict, where: str, expected: dict | None = None) -> str:
    """Compare before doing native asset work, then verify provenance for standalone calls."""
    expected = expected if expected is not None else load_camera_rest_pose_contract()
    compare_rest_pose(cat, where, expected)
    verify_native_camera_rest_pose(where, expected)
    return " restPose=installed-native-verified"


class NativeCameraRestPoseVerifier:
    """Invocation-local lazy verification shared by all rest-pose catalogs in one validator run."""

    def __init__(self):
        self._verified_rest_pose = None
        self._native_verified = False

    def check(self, cat: dict, where: str) -> str:
        if self._verified_rest_pose is None:
            self._verified_rest_pose = load_camera_rest_pose_contract()
        compare_rest_pose(cat, where, self._verified_rest_pose)
        if not self._native_verified:
            verify_native_camera_rest_pose(where, self._verified_rest_pose)
            self._native_verified = True
        return " restPose=installed-native-verified"


def file_sha256_and_size(path: Path) -> tuple[int, str]:
    """Hash a file with bounded memory while counting the exact bytes read."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(FILE_HASH_CHUNK_SIZE), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def pan_voids_cpu(npz: dict, O, D, strip_outer: bool = False):
    """NumPy CPU reference for the sampled pan raymarcher.

    The raster is a sampled proxy, not exact ray/triangle or pixel visibility. Buildings are ignored (they only add
    coverage). Returns a bool array (True = sampled void).
    """
    import numpy as np

    load_pan_constants()
    h = npz["h"]
    outer_h = npz["outer_h"]
    cov = np.zeros_like(npz["covered"]) if strip_outer else npz["covered"]
    x0, z0, res = float(npz["x0"]), float(npz["z0"]), float(npz["res"])
    nz, nx = h.shape
    cpos, fwd, up, rgt = npz["cam_pos"], npz["cam_fwd"], npz["cam_up"], npz["cam_right"]
    W, H = (int(v) for v in npz["frame_wh"])
    sky = npz["frame_sky"]
    t_h = math.tan(math.radians(float(npz["fov"])) / 2)
    ok = np.zeros(len(O), bool)
    live = np.ones(len(O), bool)
    esc = np.zeros(len(O), bool)
    t = np.full(len(O), 0.3)
    for _ in range(PAN_MAX_STEPS):
        idx = np.nonzero(live)[0]
        if not len(idx):
            break
        P = O[idx] + D[idx] * t[idx, None]
        gx = np.round((P[:, 0] - x0) / res).astype(int)
        gz = np.round((P[:, 2] - z0) / res).astype(int)
        inb = (gx >= 0) & (gx < nx) & (gz >= 0) & (gz < nz)
        outer_hit = np.zeros(len(idx), bool)
        frame_hit = np.zeros(len(idx), bool)
        outer_hit[inb] = cov[gz[inb], gx[inb]] & (P[inb, 1] <= outer_h[gz[inb], gx[inb]])
        frame_hit[inb] = P[inb, 1] <= h[gz[inb], gx[inb]]
        if frame_hit.any():
            frame_candidates = np.nonzero(frame_hit)[0]
            Ph = P[frame_hit]
            d = Ph - cpos
            zc = d @ fwd
            px = ((d @ rgt) / (np.maximum(zc, 1e-6) * t_h * W / H) + 1) * 0.5 * W
            py = (1 - (d @ up) / (np.maximum(zc, 1e-6) * t_h)) * 0.5 * H
            # Image rays include the mathematical border (x=W or y=H), whose nearest actual pixel is W-1/H-1.
            inf = (zc > 0.05) & (px >= -1e-4) & (px <= W + 1e-4) & (py >= -1e-4) & (py <= H + 1e-4)
            frame_hit[:] = False
            frame_hit[frame_candidates[inf]] = ~sky[np.clip(py[inf].astype(int), 0, H - 1),
                                                     np.clip(px[inf].astype(int), 0, W - 1)]
        hit = outer_hit | frame_hit
        ok[idx[hit]] = True
        live[idx[hit]] = False
        leave = ~inb
        live[idx[leave]] = False
        esc[idx[leave]] = True
        adv = ~hit & ~leave
        step = 0.25 + 0.01 * t[idx]
        near_outer = np.zeros(len(idx), bool)
        near_outer[inb] = cov[gz[inb], gx[inb]] & (P[inb, 1] > outer_h[gz[inb], gx[inb]]) \
            & (P[inb, 1] - outer_h[gz[inb], gx[inb]] < 0.5)
        # Resolve the thin post-settle lip at the default-frame boundary without slowing distant empty rays.
        step[near_outer] = np.minimum(step[near_outer], 0.05 + 0.002 * t[idx[near_outer]])
        t[idx[adv]] += step[adv]
    esc |= live
    if esc.any():
        f = np.array([fwd[0], 0.0, fwd[2]])
        f = f / np.linalg.norm(f)
        r = np.cross([0.0, 1.0, 0.0], f)
        Oe, De = O[esc] - cpos, D[esc]
        b = (Oe * De).sum(1)
        c = (Oe * Oe).sum(1) - float(npz["dome_r"]) ** 2
        s = -b + np.sqrt(np.maximum(b * b - c, 0))
        Q = Oe + De * s[:, None]
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        az = np.degrees(np.arctan2(Q @ r, Q @ f))
        el = np.degrees(np.arcsin(np.clip(Q[:, 1], -1, 1)))
        sa, se = npz["sky_az"], npz["sky_el"]
        ok[esc] = (az >= sa[0]) & (az <= sa[1]) & (el >= max(float(se[0]), PAN_EL_MIN)) & (el <= se[1])
    return ~ok


def pan_voids(npz: dict, O, D, strip_outer: bool = False):
    """Compatibility name for direct CPU-reference tests; validation uses pan_voids_device."""
    return pan_voids_cpu(npz, O, D, strip_outer=strip_outer)


def pan_voids_device(npz: dict, O, D, strip_outer: bool = False,
                     device: str = PAN_DEFAULT_DEVICE, engine=None):
    """Dispatch one batch; CUDA is the production default and CPU must be selected explicitly."""
    if device not in ("cpu", "cuda"):
        raise ValueError(f"pan coverage device must be 'cpu' or 'cuda', got {device!r}")
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    from town_gpu_pan import validate_pan_evidence, validate_pan_rays

    validate_pan_evidence(npz)
    if device == "cpu":
        O, D = validate_pan_rays(O, D)
        return pan_voids_cpu(npz, O, D, strip_outer=strip_outer)
    if engine is None:
        from town_gpu_pan import PanVoidEngine
        engine = PanVoidEngine(npz)
    return engine.voids(O, D, strip_outer=strip_outer)


def _check_pan_rays(npz: dict, rays: dict, where: str, device: str) -> tuple[int, float]:
    """Run every generated ray and the canonical sensitivity negative without changing the sample set."""
    load_pan_constants()
    neg_share, n_all = None, 0

    def run(engine=None):
        nonlocal neg_share, n_all
        for name, rr in rays.items():
            n_all += len(rr["O"])
            for i in range(0, len(rr["O"]), PAN_BATCH):
                j = min(i + PAN_BATCH, len(rr["O"]))
                void = pan_voids_device(npz, rr["O"][i:j], rr["D"][i:j], device=device, engine=engine)
                if void.any():
                    modes = sorted(set(rr["mode"][i:j][void].tolist()))
                    fail(f"{where}: pan coverage {name}: {int(void.sum())} of {len(rr['O'])} rays end in a void "
                         f"(first failing batch; {modes})")
            # The negative is a sensitivity check of the shared coverage raster and raymarcher, not a second proof for
            # each aspect. One complete canonical path is enough to prove that removing the outer world makes it fail.
            if name == "16:9":
                neg = sum(int(pan_voids_device(npz, rr["O"][i:i + PAN_BATCH], rr["D"][i:i + PAN_BATCH],
                                               strip_outer=True, device=device, engine=engine).sum())
                          for i in range(0, len(rr["O"]), PAN_BATCH))
                neg_share = neg / len(rr["O"])
                if neg_share < PAN_NEG_MIN:
                    fail(f"{where}: pan coverage negative check: stripping the outer world leaves only "
                         f"{neg_share:.4f} voids (the raster or rays do not exercise the periphery)")

    if device == "cpu":
        run()
    elif device == "cuda":
        if str(PAN_MODULE_DIR) not in sys.path:
            sys.path.insert(0, str(PAN_MODULE_DIR))
        from town_full3d_gpu import gate as gpu_gate
        from town_gpu_pan import PanVoidEngine

        # The existing shared gate bounds acquisition to 30 seconds and releases GPU ownership before returning.
        # Ray generation and asset/hash validation have already finished before this reservation is taken.
        with gpu_gate("phase-6 pan coverage", need_vram_gb=1.0, wait_min=0.5):
            engine = PanVoidEngine(npz)
            run(engine)
            del engine
    else:
        raise ValueError(f"pan coverage device must be 'cpu' or 'cuda', got {device!r}")

    if neg_share is None:
        fail(f"{where}: canonical 16:9 aspect missing from pan coverage check")
    return n_all, neg_share


def check_pan_coverage(cat: dict, where: str, folder: Path | None, device: str = PAN_DEFAULT_DEVICE) -> str:
    """Phase 6: reject gaps in sampled camera rays using the final-mesh height proxy and a sensitivity negative.

    Spline basis, unsampled transitions and pixel occlusion still need native/live or editor-render proof.
    """
    import hashlib as _h
    import numpy as np

    pc = cat.get("panCoverage")
    if not isinstance(pc, dict) or not pc.get("file") or not re.fullmatch(r"[0-9a-f]{64}", str(pc.get("sha256", ""))):
        fail(f"{where}: phase 6 requires panCoverage (file + sha256)")
    per = cat.get("periphery")
    if not isinstance(per, dict) or not isinstance(per.get("meshyCredits"), int):
        fail(f"{where}: phase 6 requires periphery with meshyCredits")
    if (per.get("mesh") or {}).get("frameIntrusions") != 0:
        fail(f"{where}: periphery.mesh.frameIntrusions must be 0 (vertex-level default-frame check)")
    env_pieces = set((cat.get("environment") or {}).get("pieces") or [])
    terrain = per.get("pieces") or {}
    scatter = per.get("scatter") or {}
    water = per.get("water") or {}
    if not isinstance(terrain, dict) or not terrain or not all(n.startswith("Mesh_Outer") and
                                                               isinstance(row, dict) and row.get("tris", 0) > 0
                                                               for n, row in terrain.items()):
        fail(f"{where}: periphery requires built outer terrain triangles")
    # Declared requirements: continued water is required unless the catalog declares it absent with a reason (a town
    # whose painting has no river leaving the frame); scatter kinds name their bin prefixes (default: the Conflux
    # conifer / boulder bins). A declared requirement whose content is missing fails like an undeclared one.
    if not isinstance(water, dict):
        fail(f"{where}: periphery.water must be an object")
    if water.get("required", True) is False:
        if not str(water.get("reason") or "").strip():
            fail(f"{where}: periphery.water.required is false without a reason")
        if "Fx_WaterOuter" in env_pieces:
            fail(f"{where}: periphery.water.required is false but Fx_WaterOuter is an environment piece")
    elif water.get("required", True) is not True:
        fail(f"{where}: periphery.water.required must be a boolean")
    elif "Fx_WaterOuter" not in env_pieces or water.get("tris", 0) <= 0 or len(water.get("rivers") or []) != 2:
        fail(f"{where}: periphery requires a built Fx_WaterOuter with two continued rivers")
    # Scatter kinds follow the faction profile's PERIPHERY_SCATTER declaration (scrub -> _tree, rock -> _rock); a
    # fraction whose profile declares none fails. A required kind is checked as before (non-empty Mesh_Outer_* prefixes,
    # now equal to the declared ones, each a built bin outside the frame); a kind declared not required must carry the
    # declared reason, no sites, no prefixes and no Mesh_Outer_ bin of any undeclared prefix.
    policy = scatter_policy(str(cat.get("fraction")), where, lane_form=not any(
        isinstance(v, dict) and "prefixes" in v for k, v in scatter.items() if k in ("_tree", "_bush", "_rock")))
    claimed = []
    if "bush" not in policy and "_bush" in scatter:
        fail(f"{where}: periphery.scatter._bush is built but the fraction declares no PERIPHERY_SCATTER.bush")
    for kind, pkey in (("tree", "scrub"), ("bush", "bush"), ("rock", "rock")):
        if pkey not in policy:
            continue
        decl = policy[pkey]
        sites = scatter.get(f"_{kind}") or {}
        if isinstance(sites, dict) and "prefixes" not in sites and decl.get("catalogPrefixes") is False:
            # the Conflux lane's catalogs predate per-kind prefixes: its declared prefixes are the ones checked
            sites = {**sites, "prefixes": decl["prefixes"]}
        if not isinstance(sites, dict):
            fail(f"{where}: periphery.scatter._{kind} must be an object")
        if decl["required"] is False:
            if sites.get("sites") != 0 or sites.get("outsideFrame") != 0 or sites.get("prefixes") != []                     or sites.get("source") != decl["reason"]:
                fail(f"{where}: profile PERIPHERY_SCATTER.{pkey} is not required, so periphery.scatter._{kind} must "
                     f"be sites 0 / outsideFrame 0 / prefixes [] with the declared reason; got {sites}")
            continue
        prefixes = sites.get("prefixes")
        if not isinstance(prefixes, list) or not prefixes or not all(
                isinstance(p, str) and p.startswith("Mesh_Outer_") and len(p) > len("Mesh_Outer_") for p in prefixes):
            fail(f"{where}: periphery.scatter._{kind}.prefixes must be a non-empty list of Mesh_Outer_* prefixes")
        if prefixes != decl["prefixes"]:
            fail(f"{where}: periphery.scatter._{kind}.prefixes {prefixes} != profile PERIPHERY_SCATTER.{pkey}.prefixes "
                 f"{decl['prefixes']}")
        claimed += prefixes
        for prefix in prefixes:
            built = [row for name, row in scatter.items() if name.startswith(prefix)]
            if sites.get("outsideFrame", 0) <= 0 or not built or not all(
                    isinstance(row, dict) and row.get("instances", 0) > 0 and row.get("tris", 0) > 0 for row in built):
                fail(f"{where}: periphery requires nonempty outer {kind} scatter bins ({prefix}*)")
    stray = [n for n in scatter if n.startswith("Mesh_Outer_") and not n.startswith(tuple(claimed))]
    if stray:
        fail(f"{where}: periphery scatter bins {stray} belong to no declared PERIPHERY_SCATTER kind")
    nd, dens = policy["nearDensity"], ((cat.get("nearField") or {}).get("density") or {})
    if nd["source"] == "none":
        if dens or any(n.startswith("Mesh_Near_scrub") for n in env_pieces):
            fail(f"{where}: PERIPHERY_SCATTER.nearDensity is none but nearField.density / Mesh_Near_scrub is built")
    elif nd["source"] == "profile":
        if dens.get("scrubPerM2") != nd["perM2"] or dens.get("scrubBlobs") is not None:
            fail(f"{where}: profile PERIPHERY_SCATTER.nearDensity perM2 {nd['perM2']} is not nearField.density "
                 f"(scrubPerM2 {dens.get('scrubPerM2')}, scrubBlobs {dens.get('scrubBlobs')})")
    elif not (isinstance(dens.get("scrubBlobs"), int) and dens["scrubBlobs"] > 0):
        fail(f"{where}: profile PERIPHERY_SCATTER.nearDensity is measured but nearField.density has no blob count")
    if policy["scrub"]["required"] is False and any(n.startswith("Mesh_Near_scrub") for n in env_pieces):
        fail(f"{where}: profile PERIPHERY_SCATTER.scrub is not required but a Mesh_Near_scrub piece is built")
    listed = list(terrain) + [n for n in scatter if n.startswith("Mesh_")]
    missing = [n for n in listed if n not in env_pieces]
    if missing:
        fail(f"{where}: periphery pieces missing from the environment: {missing or 'none listed'}")
    if folder is None:
        fail(f"{where}: phase 6 coverage needs the catalog folder")
    path = folder / pc["file"]
    if not path.is_file():
        fail(f"{where}: panCoverage file {path} missing")
    if _h.sha256(path.read_bytes()).hexdigest() != pc["sha256"]:
        fail(f"{where}: {path.name} sha256 differs from panCoverage.sha256")
    with np.load(path) as data:
        npz = dict(data.items())
    required = ("h", "outer_h", "covered", "x0", "z0", "res", "cam_pos", "cam_fwd", "cam_up",
                "cam_right", "frame_wh", "frame_sky", "fov", "C", "cpos", "depth_scale", "dome_r",
                "sky_az", "sky_el")
    missing = [name for name in required if name not in npz]
    if missing:
        fail(f"{where}: panCoverage lacks {missing}")
    if str(PAN_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(PAN_MODULE_DIR))
    from town_gpu_pan import validate_pan_evidence

    try:
        validate_pan_evidence(npz)
    except ValueError as exc:
        fail(f"{where}: invalid panCoverage evidence: {exc}")
    if npz["h"].shape != npz["outer_h"].shape or npz["h"].shape != npz["covered"].shape \
            or not np.isfinite(npz["h"]).all() \
            or not np.array_equal(npz["covered"], np.isfinite(npz["outer_h"])) \
            or not np.isneginf(npz["outer_h"][~npz["covered"]]).all():
        fail(f"{where}: panCoverage outer_h/covered must describe final retained triangle sample heights")
    import conflux_town_camera_pan as pan

    rays = pan.pan_rays_w(npz["C"], npz["cpos"], float(npz["depth_scale"]), float(npz["fov"]), per_seg=16, nx=25, ny=15)
    n_all, neg_share = _check_pan_rays(npz, rays, where, device)
    return f" panRays={n_all} panVoid=0 panNeg16x9={neg_share:.3f} panDevice={device}"


def streak_ratios(P, tris, cpos, fwd):
    """Rest-camera forward-depth ratio (max/min over the vertices) of each triangle."""
    import numpy as np

    z = (np.asarray(P, np.float64) - np.asarray(cpos, np.float64)) @ np.asarray(fwd, np.float64)
    zt = z[np.asarray(tris, np.int64)]
    if (zt <= 0).any():
        return np.full(len(zt), np.inf)
    return zt.max(1) / zt.min(1)


def check_terrain_streak(cat: dict, where: str, folder: Path | None) -> str:
    """Phase 6b: no shipped terrain triangle is a ridge curtain; the stored cut triangles prove the check can fail."""
    import hashlib as _h
    import numpy as np

    ts = cat.get("terrainStreak")
    if not isinstance(ts, dict) or not ts.get("file") or not re.fullmatch(r"[0-9a-f]{64}", str(ts.get("sha256", ""))):
        fail(f"{where}: phase 6b requires terrainStreak (file + sha256)")
    cap = ts.get("ratioCap")
    if not isinstance(cap, (int, float)) or not 1.0 < cap <= STREAK_RATIO_CAP:
        fail(f"{where}: terrainStreak.ratioCap {cap!r} must be in (1, {STREAK_RATIO_CAP}]")
    env_pieces = set((cat.get("environment") or {}).get("pieces") or [])
    back = ts.get("backPieces")
    if not isinstance(back, list) or not back or not all(isinstance(n, str) and n.startswith("Mesh_Back_") for n in back):
        fail(f"{where}: terrainStreak.backPieces must name the Mesh_Back_* back-layer bins")
    missing = [n for n in back if n not in env_pieces]
    if missing:
        fail(f"{where}: terrainStreak back-layer pieces missing from the environment: {missing}")
    if folder is None:
        fail(f"{where}: terrainStreak needs the catalog folder")
    path = folder / ts["file"]
    if not path.is_file():
        fail(f"{where}: terrainStreak file {path} missing")
    if _h.sha256(path.read_bytes()).hexdigest() != ts["sha256"]:
        fail(f"{where}: {path.name} sha256 differs from terrainStreak.sha256")
    with np.load(path) as data:
        d = dict(data.items())
    need = ("main_P", "main_tris", "back_P", "back_tris", "cut_tris", "cpos", "cam_fwd")
    lack = [k for k in need if k not in d]
    if lack:
        fail(f"{where}: terrainStreak lacks {lack}")
    if not len(d["main_tris"]) or not len(d["back_tris"]):
        fail(f"{where}: terrainStreak has no main or no back-layer triangles")
    r_main = streak_ratios(d["main_P"], d["main_tris"], d["cpos"], d["cam_fwd"])
    r_back = streak_ratios(d["back_P"], d["back_tris"], d["cpos"], d["cam_fwd"])
    worst = float(max(r_main.max(), r_back.max()))
    if worst > cap + 1e-6:
        fail(f"{where}: terrain streak: {int((r_main > cap).sum())} main and {int((r_back > cap).sum())} back-layer "
             f"triangles exceed forward-depth ratio {cap} (worst {worst:.3f}): ridge curtains")
    # Negative: the triangles the build cut are curtains by this same measure (the check sees what it removes).
    # An empty cut set is valid when the catalog agrees (cutTris == 0): the zone cut and back layers already bound every
    # triangle under the cap (Tower zs_v2, vlb back rule), so "every stored cut exceeds the cap" holds vacuously; the
    # positive check above has passed on it, and the output names the bound (coordinator 2026-10-02). The measure's
    # ability to fail is proven by test_phase6b_streak_contract.py.
    r_cut = streak_ratios(d["main_P"], d["cut_tris"], d["cpos"], d["cam_fwd"])
    if len(r_cut) != ts.get("cutTris") or not (r_cut > cap).all():
        fail(f"{where}: terrainStreak negative check: the {len(r_cut)} stored cut triangles (catalog "
             f"{ts.get('cutTris')!r}) must match the catalog and all exceed the cap")
    if not len(r_cut):
        return f" streakMax={worst:.3f} streakNeg=0 (empty cut: maxRatioAfter={worst:.3f} <= cap {cap})"
    return f" streakMax={worst:.3f} streakNeg={len(r_cut)}"


BUILDING_DEPTH_SCHEMA = "town_building_depth.v1"


# terrain under a building vertex (buildingDepth.terrainSample): the shipped env pieces this matches are the ground the
# upright test measures from, so a building's ground lying on a hill above the floor plane is not upright
BUILDING_TERRAIN_PIECE = re.compile(r"^Mesh_(Back_)?Terrain")
BUILDING_TERRAIN_KEYS = ("terrain_grid", "terrain_origin", "terrain_cell", "terrain_e1", "terrain_e2", "terrain_sha")


def building_terrain_pieces_sha(env_dir: Path) -> tuple[list, str]:
    """The staged terrain pieces (Mesh_Terrain*, Mesh_Back_Terrain*) of an environment prefab and one sha256 over
    their names and bytes: the provenance a terrain sample is pinned to."""
    pieces = sorted(p for p in Path(env_dir).glob("*.bytes") if BUILDING_TERRAIN_PIECE.match(p.stem))
    h = hashlib.sha256()
    for p in pieces:
        b = p.read_bytes()
        h.update(p.stem.encode() + b"\0" + len(b).to_bytes(8, "little") + b)
    return [p.stem for p in pieces], h.hexdigest()


def building_terrain_under(v_m, t: dict):
    """Height (m) of the sampled terrain above the floor plane under each vertex (painting m, camera-local); NaN where
    the grid has no walkable terrain."""
    import numpy as np
    v = np.asarray(v_m, np.float64)
    g = np.asarray(t["terrain_grid"], np.float64)
    o = np.asarray(t["terrain_origin"], np.float64)
    c = float(t["terrain_cell"])
    i = np.floor((v @ np.asarray(t["terrain_e1"], np.float64) - o[0]) / c).astype(np.int64)
    j = np.floor((v @ np.asarray(t["terrain_e2"], np.float64) - o[1]) / c).astype(np.int64)
    ok = (i >= 0) & (j >= 0) & (i < g.shape[1]) & (j < g.shape[0])
    out = np.full(len(v), np.nan)
    out[ok] = g[j[ok], i[ok]]
    return out


def building_upright_stats(v_local, scale: float, n, d: float, h_min: float, terrain: dict | None = None) -> dict:
    """Upright forward-depth span vs lateral width of one building bin (identical to
    tools/homm3_town_scene_meshes/town_full3d_building_depth.upright_stats). Upright = more than h_min above the
    floor plane and not lying on the sampled terrain (terrain: the npz terrain_*). Lying on it = within h_min of the
    terrain under the vertex: above max(floor plane, terrain) by more than h_min is upright, and so is a vertex buried
    more than h_min under the terrain (a terrain bump the painting's own building left in the ground is not ground to
    that building's walls)."""
    import numpy as np
    v = np.asarray(v_local, np.float64) / scale
    h = v @ np.asarray(n, np.float64) - d
    up = h > h_min
    if terrain is not None:
        ht = building_terrain_under(v, terrain)
        up &= ~(np.isfinite(ht) & (np.abs(h - ht) <= h_min))
    if up.sum() < 50:
        return {"uprightN": int(up.sum()), "uprightSpanM": 0.0, "widthM": 0.0, "spanOverWidth": 0.0}
    vu = v[up]
    z = vu[:, 2]
    z2, z50, z98 = np.percentile(z, [2, 50, 98])
    az = np.arctan2(vu[:, 0], z)
    wid = float(np.percentile(az, 98) - np.percentile(az, 2)) * float(z50)
    return {"uprightN": int(up.sum()), "uprightSpanM": round(float(z98 - z2), 3), "widthM": round(wid, 3),
            "spanOverWidth": round(float(z98 - z2) / max(wid, 0.5), 4)}


def building_terrain_failures(bd: dict, d: dict) -> tuple[list, dict | None]:
    """A block with terrainSample must carry the npz terrain_* sample, pinned (sha) to the staged terrain pieces it
    was sampled from; a missing or changed stage refuses it (a stale sample). No terrainSample: the floor plane alone
    (the stricter v1 measure)."""
    import numpy as np
    ts = bd.get("terrainSample")
    have = [k for k in BUILDING_TERRAIN_KEYS if k in d]
    if ts is None and not have:
        return [], None
    if ts is None or len(have) != len(BUILDING_TERRAIN_KEYS):
        return [f"buildingDepth terrainSample and the npz terrain_* arrays must come together (block "
                f"{'with' if ts else 'without'} terrainSample, npz has {have})"], None
    out = []
    if str(d["terrain_sha"]) != ts.get("sha256"):
        out.append("buildingDepth npz terrain_sha differs from terrainSample.sha256")
    env = ROOT / str(ts.get("stageDir", ""))
    if not ts.get("stageDir") or not env.is_dir():
        out.append(f"buildingDepth terrainSample stage {env} missing: the terrain sample cannot be checked against "
                   f"the staged terrain it measures (keep the candidate's staged Assets)")
    else:
        pieces, sha = building_terrain_pieces_sha(env)
        if not pieces:
            out.append(f"buildingDepth terrainSample stage {env} has no terrain pieces")
        if sha != ts.get("sha256") or pieces != ts.get("pieces"):
            out.append(f"buildingDepth terrainSample is stale: staged terrain {pieces} sha {sha[:12]} != sampled "
                       f"{ts.get('pieces')} sha {str(ts.get('sha256'))[:12]}")
    if float(d["terrain_cell"]) <= 0 or np.asarray(d["terrain_grid"]).ndim != 2:
        out.append("buildingDepth terrain_grid must be a 2D grid with a positive cell")
    return out, (None if out else d)


# building seams (buildingDepth.seams, seams_v1; docs/homm3_town_building_seams.md): one
# building's rest-adjacent pieces must not come apart at the vanilla camera's proof poses
BUILDING_SEAM_SCHEMA = "seams_v2"
# seams_v2 (2026-10-01) is seams_v1 with the off-frame correction: a pair counts at a proof pose only where its
# midpoint is on that pose's screen (off screen nothing is drawn there, so seam_fill is inf without the layer being
# see-through; Rampart tbrmdw_0 at the frame's left edge: 86-91% of its "split" pairs at sweep_right / cursor_right
# were off screen, at pose x -52..-108). A pair on screen at no proof pose is unmeasured, counted apart. seams_v1
# blocks (built before the correction, e.g. installed Cove ssr_dfix) are re-measured by their own rule.
BUILDING_SEAM_SCHEMAS = {"seams_v1": False, "seams_v2": True}   # schema -> off-frame correction
BUILDING_SEAM_UNMEASURED_FLAG = 0.25   # a layer with more than this share of unmeasured residual pairs is flagged
BUILDING_SEAM_KEYS = ("seam_a", "seam_b", "seam_layer", "seam_roles", "seam_fill", "seam_layers", "seam_pose_names",
                      "seam_pose_pos", "seam_pose_fwd", "seam_pose_up", "seam_pose_right", "seam_fov", "seam_frame")
BUILDING_SEAM_POSES = ("cursor_left", "cursor_right", "sweep_left", "sweep_right", "sweep_high")
BUILDING_SEAM_OPEN_PX = 2.0         # a rest seam pair whose screen distance grows by more than this (1080p px) is split
BUILDING_SEAM_SPLIT_MAX = 0.01      # a layer fails when more than this share of its residual seam pairs split
BUILDING_SEAM_SPLIT_MIN_PAIRS = 20  # ... and more than this many (a handful of edge px is raster noise)
BUILDING_SEAM_HOLE_RATIO = 1.01     # an opening is see-through where the layer draws only something this x deeper


def building_seam_openings(a, b, pos, fwd, up, right, fov: float, frame):
    """Per seam pair (endpoints a, b in the prefab frame: camera-rest local x depthScale) and per given pose: the growth
    of its screen distance (1080p px) against the rest camera (origin, axes x/y/z), and the deeper side's camera depth
    (prefab units). Identical to tools/homm3_town_scene_meshes/town_full3d_building_seams (which calls it)."""
    import numpy as np
    W, H = float(frame[0]), float(frame[1])
    t = np.tan(np.radians(float(fov)) / 2)

    def proj(p, o, f, u, r):
        d = np.asarray(p, np.float64) - o
        zc = d @ f
        return np.stack([((d @ r) / (zc * t * W / H) + 1) * 0.5 * W, (1 - (d @ u) / (zc * t)) * 0.5 * H], 1), zc
    e = np.eye(3)
    rest = np.linalg.norm(proj(a, np.zeros(3), e[2], e[1], e[0])[0] - proj(b, np.zeros(3), e[2], e[1], e[0])[0], axis=1)
    grow = np.zeros((len(rest), len(pos)))
    deep = np.zeros((len(rest), len(pos)))
    for k in range(len(pos)):
        args = (np.asarray(pos[k], np.float64), np.asarray(fwd[k], np.float64), np.asarray(up[k], np.float64),
                np.asarray(right[k], np.float64))
        (qa, za), (qb, zb) = proj(a, *args), proj(b, *args)
        grow[:, k] = np.linalg.norm(qa - qb, axis=1) - rest
        deep[:, k] = np.maximum(za, zb)
    return grow, deep


def building_seam_onscreen(d: dict):
    """Per seam pair and proof pose: its midpoint projects in front of the pose camera and inside its frame (the
    rasteriser that wrote seam_fill samples nothing elsewhere)."""
    import numpy as np
    W, H = float(d["seam_frame"][0]), float(d["seam_frame"][1])
    t = np.tan(np.radians(float(d["seam_fov"])) / 2)
    mid = 0.5 * (np.asarray(d["seam_a"], np.float64) + np.asarray(d["seam_b"], np.float64))
    on = np.zeros((len(mid), len(d["seam_pose_pos"])), bool)
    for k in range(on.shape[1]):
        q = mid - np.asarray(d["seam_pose_pos"][k], np.float64)
        zc = q @ np.asarray(d["seam_pose_fwd"][k], np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            x = ((q @ np.asarray(d["seam_pose_right"][k], np.float64)) / (zc * t * W / H) + 1) * 0.5 * W
            y = (1 - (q @ np.asarray(d["seam_pose_up"][k], np.float64)) / (zc * t)) * 0.5 * H
        on[:, k] = (zc > 0) & (x >= 0) & (x < W) & (y >= 0) & (y < H)
    return on


def building_seam_split(d: dict, onscreen: bool = True):
    """Per seam pair: split (at some proof pose it opens by more than BUILDING_SEAM_OPEN_PX and is see-through: the
    layer alone draws nothing at its midpoint there, seam_fill inf, or only something BUILDING_SEAM_HOLE_RATIO x
    deeper than both sides), and its worst opening over the see-through poses (0 where none). onscreen (seams_v2):
    only the poses where the pair's midpoint is on screen count (building_seam_onscreen)."""
    import numpy as np
    grow, deep = building_seam_openings(d["seam_a"], d["seam_b"], d["seam_pose_pos"], d["seam_pose_fwd"],
                                        d["seam_pose_up"], d["seam_pose_right"], float(d["seam_fov"]), d["seam_frame"])
    fill = np.asarray(d["seam_fill"], np.float64)
    if fill.shape != grow.shape:
        raise ValueError(f"seam_fill shape {fill.shape} != pairs x poses {grow.shape}")
    hole = ~np.isfinite(fill) | (fill > deep * BUILDING_SEAM_HOLE_RATIO)
    if onscreen:
        hole &= building_seam_onscreen(d)
    worst = np.where(hole, grow, 0.0).max(1) if grow.shape[1] else np.zeros(len(grow))
    return worst > BUILDING_SEAM_OPEN_PX, worst


def building_seam_stats(d: dict, onscreen: bool = True) -> dict:
    """Per layer: residual seam pairs (a ray side), split pairs (building_seam_split), share, p99 see-through opening;
    plus the solid-solid pairs (reported, not gated). onscreen (seams_v2) adds residualUnmeasured: residual pairs on
    screen at no proof pose (they cannot split, and are counted apart so they never pass silently)."""
    import numpy as np
    split, g = building_seam_split(d, onscreen)
    never = ~building_seam_onscreen(d).any(1) if onscreen else None
    roles = np.asarray(d["seam_roles"])
    ray = (roles == 0).any(1)
    sol = (roles == 1).all(1)
    out = {}
    for i, lid in enumerate(str(x) for x in d["seam_layers"]):
        m = np.asarray(d["seam_layer"]) == i
        r, s_ = m & ray, m & sol
        n, k = int(r.sum()), int(split[r].sum())
        out[lid] = {"residualPairs": n, "residualSplit": k, "residualSplitShare": round(k / max(n, 1), 4),
                    "residualP99OpenPx": round(float(np.percentile(g[r], 99)), 2) if n else 0.0,
                    "solidPairs": int(s_.sum()), "solidSplit": int(split[s_].sum())}
        if never is not None:
            out[lid]["residualUnmeasured"] = int((never & r).sum())
    return out


def building_seam_failures(bd: dict, d: dict) -> list:
    """A block with seams must carry the npz seam_* arrays at the contract's own poses, and every layer's declared
    numbers must equal the re-measure; a layer whose residual seam pairs split beyond BUILDING_SEAM_SPLIT_MAX (and
    BUILDING_SEAM_SPLIT_MIN_PAIRS) breaks into discrete layers on a camera turn (installed rampart rx_layer_card_dfix,
    2026-10-01). No seams block and no arrays: a pre-seams build (installed catalogs), measured by the rest alone."""
    sm = bd.get("seams")
    have = [k for k in BUILDING_SEAM_KEYS if k in d]
    if sm is None and not have:
        return []
    if sm is None or len(have) != len(BUILDING_SEAM_KEYS):
        return [f"buildingDepth seams and the npz seam_* arrays must come together (block "
                f"{'with' if sm else 'without'} seams, npz has {have})"]
    out = []
    if sm.get("schema") not in BUILDING_SEAM_SCHEMAS:
        out.append(f"buildingDepth.seams.schema must be one of {sorted(BUILDING_SEAM_SCHEMAS)}")
    onscreen = BUILDING_SEAM_SCHEMAS.get(sm.get("schema"), True)
    if tuple(str(x) for x in d["seam_pose_names"]) != BUILDING_SEAM_POSES:
        out.append(f"buildingDepth seams poses {list(map(str, d['seam_pose_names']))} != {list(BUILDING_SEAM_POSES)}")
    for k, v in (("openPx", BUILDING_SEAM_OPEN_PX), ("splitShareMax", BUILDING_SEAM_SPLIT_MAX),
                 ("splitMinPairs", BUILDING_SEAM_SPLIT_MIN_PAIRS), ("holeRatio", BUILDING_SEAM_HOLE_RATIO)):
        if sm.get(k) != v:
            out.append(f"buildingDepth.seams.{k} {sm.get(k)!r} must be {v}")
    try:
        st = building_seam_stats(d, onscreen)
    except ValueError as e:
        return out + [f"buildingDepth seams: {e}"]
    dec = sm.get("layers") or {}
    if sorted(dec) != sorted(st):
        out.append(f"buildingDepth.seams.layers {sorted(dec)} != measured {sorted(st)}")
    for lid, s in st.items():
        if (dec.get(lid) or {}).get("residualSplit") != s["residualSplit"]:
            out.append(f"buildingDepth seams {lid}: declared {(dec.get(lid) or {}).get('residualSplit')} split pairs, "
                       f"measured {s['residualSplit']}")
        if onscreen and (dec.get(lid) or {}).get("residualUnmeasured") != s["residualUnmeasured"]:
            out.append(f"buildingDepth seams {lid}: declared {(dec.get(lid) or {}).get('residualUnmeasured')} "
                       f"unmeasured pairs, measured {s['residualUnmeasured']}")
        if s["residualSplit"] > BUILDING_SEAM_SPLIT_MIN_PAIRS and s["residualSplitShare"] > BUILDING_SEAM_SPLIT_MAX:
            out.append(f"building seam split: {lid} residual pieces come apart from their body at the proof poses on "
                       f"{s['residualSplit']}/{s['residualPairs']} seam px ({s['residualSplitShare']:.3f} > "
                       f"{BUILDING_SEAM_SPLIT_MAX}; p99 {s['residualP99OpenPx']} px > {BUILDING_SEAM_OPEN_PX})")
    return out


def building_seam_unmeasured_flags(sm) -> list:
    """Summary flags for layers whose unmeasured residual share exceeds BUILDING_SEAM_UNMEASURED_FLAG (reported, not
    failed: those pairs are seen at no proof pose, so the gate says nothing about them)."""
    if not isinstance(sm, dict):
        return []
    out = []
    for lid, v in sorted((sm.get("layers") or {}).items()):
        n, u = int(v.get("residualPairs", 0)), int(v.get("residualUnmeasured", 0))
        if n and u / n > BUILDING_SEAM_UNMEASURED_FLAG:
            out.append(f" UNMEASURED-SEAMS:{lid}={u}/{n}")
    return out


def building_depth_failures(bd: dict, folder: Path | None) -> list:
    """Every failure of a buildingDepth block against its own npz (shared with town_full3d_building_depth.py audit,
    which runs it on pre-contract candidates). A ray / solid bin whose part above the floor plane spans more than
    spanOverWidthMax times its width and more than spanMinM is a depth streak (the Cove waterfall, the stilt houses,
    BodyRest residuals); a layer shipping a ray / solid bin whose legacy relief window clipped more than
    windowShareMax of its sprite carries the clamp, not the painting. Meshy bins are measured but exempt."""
    import hashlib as _h
    import numpy as np
    out = []
    if not isinstance(bd, dict) or bd.get("schema") != BUILDING_DEPTH_SCHEMA:
        return [f"buildingDepth must be a {BUILDING_DEPTH_SCHEMA} block"]
    # the thresholds are the contract's, not the catalog's: a catalog cannot loosen them
    lim = {"uprightHeightM": 2.0, "spanOverWidthMax": 3.0, "spanMinM": 20.0, "windowShareMax": 0.8}
    for k, v in lim.items():
        if bd.get(k) != v:
            out.append(f"buildingDepth.{k} {bd.get(k)!r} must be {v}")
    if folder is None:
        return out + ["buildingDepth needs the catalog folder"]
    path = folder / str(bd.get("file", ""))
    if not path.is_file():
        return out + [f"buildingDepth file {path} missing"]
    if _h.sha256(path.read_bytes()).hexdigest() != bd.get("sha256"):
        return out + [f"{path.name} sha256 differs from buildingDepth.sha256"]
    with np.load(path) as data:
        d = dict(data.items())
    lack = [k for k in ("P", "bin", "names", "roles", "layers", "floor_n", "floor_d", "depth_scale") if k not in d]
    if lack:
        return out + [f"buildingDepth npz lacks {lack}"]
    terr_fail, terrain = building_terrain_failures(bd, d)
    out += terr_fail
    if terr_fail:
        return out
    out += building_seam_failures(bd, d)
    declared = {b.get("name"): b for b in bd.get("bins") or []}
    if sorted(declared) != sorted(str(x) for x in d["names"]):
        out.append("buildingDepth.bins and the npz name different bins")
    layers = bd.get("layers") or {}
    for i, (nm, role, lid) in enumerate(zip(d["names"], d["roles"], d["layers"])):
        nm, role, lid = str(nm), str(role), str(lid)
        st = building_upright_stats(d["P"][d["bin"] == i], float(d["depth_scale"]), d["floor_n"], float(d["floor_d"]),
                                    lim["uprightHeightM"], terrain)
        dec = declared.get(nm) or {}
        if dec.get("role") != role or abs(float(dec.get("spanOverWidth", -1)) - st["spanOverWidth"]) > 1e-3:
            out.append(f"buildingDepth bin {nm}: declared {dec.get('role')}/{dec.get('spanOverWidth')} but measured "
                       f"{role}/{st['spanOverWidth']}")
        if role not in ("ray", "solid", "meshy", "cloth", "decal"):
            out.append(f"buildingDepth bin {nm}: unknown role {role}")
        if role == "meshy":
            continue
        if st["spanOverWidth"] > lim["spanOverWidthMax"] and st["uprightSpanM"] > lim["spanMinM"]:
            out.append(f"building depth streak: {lid}/{nm} ({role}) upright span {st['uprightSpanM']:.1f} m over "
                       f"width {st['widthM']:.1f} m = {st['spanOverWidth']:.2f} (> {lim['spanOverWidthMax']} and > "
                       f"{lim['spanMinM']} m)")
        ws = float((layers.get(lid) or {}).get("reliefWindowShare", 0.0))
        if ws > lim["windowShareMax"]:
            out.append(f"building depth clamp: {lid}/{nm} ({role}) reliefWindowShare {ws:.3f} > "
                       f"{lim['windowShareMax']} (the legacy relief window, not the painting, set its depth)")
    return out


def check_building_depth(cat: dict, where: str, folder: Path | None) -> str:
    """buildingDepth (opt-in contact_v1 candidates; docs/homm3_town_building_contact_depth.md): every non-Fx bin of
    every building layer is measured, and none is a depth streak or a relief-window clamp."""
    bd = cat.get("buildingDepth")
    fails = building_depth_failures(bd, folder)
    names = {b.get("name") for b in (bd.get("bins") or [])} if isinstance(bd, dict) else set()
    for lay in cat.get("layers") or []:
        miss = [p for p in lay.get("pieces") or [] if not str(p).startswith(("Fx_", "Ps_")) and p not in names
                and p not in {g for g in lay.get("animated") or []}]
        if miss:
            fails.append(f"buildingDepth does not measure {lay.get('layerId')} pieces {miss}")
    if fails:
        fail(f"{where}: " + "; ".join(fails[:12]) + (f" (+{len(fails) - 12} more)" if len(fails) > 12 else ""))
    worst = max([b["spanOverWidth"] for b in bd["bins"] if b["role"] != "meshy"] or [0.0])
    ts = bd.get("terrainSample")
    terr = f" terrain={str(ts.get('sha256'))[:12]}" if isinstance(ts, dict) else " terrain=plane"
    sm = bd.get("seams")
    seam = (f" seams={sum(v.get('residualSplit', 0) for v in (sm.get('layers') or {}).values())}/"
            f"{sum(v.get('residualPairs', 0) for v in (sm.get('layers') or {}).values())}") if isinstance(sm, dict) else ""
    if isinstance(sm, dict) and sm.get("schema") != BUILDING_SEAM_SCHEMA:
        seam += f"({sm.get('schema')})"
    seam += "".join(building_seam_unmeasured_flags(sm))
    return f" bldDepth={bd.get('mode')}:{len(bd['bins'])} spanW<={worst:.2f}{terr}{seam}"


def resolve_anim_crosswalk(frames: dict, fraction: str, where: str) -> dict:
    """DEF frame counts keyed by catalog layer id. A full-3D profile's ANIM_CROSSWALK maps DEF ids of
    layers/anims/metadata.json that are not layer ids (Tower's dwellingUp2Lvl*_1) onto the layer they animate; without
    it such a layer read as static and its missing effect passed silently. A fraction with no town_full3d_factions
    profile (Conflux, its own lane) keys its DEFs by layer id and takes no crosswalk. Fails closed on two profiles for
    one fraction, a malformed crosswalk, a crosswalk key that is no DEF id or is itself a layer id, and a layer that two
    DEFs claim with different frame counts."""
    import ast
    hits = []
    for path in sorted(PROFILES.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        vals = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id in ("FRACTION", "ANIM_CROSSWALK"):
                try:
                    vals[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    fail(f"{where}: profile {path.name} {node.targets[0].id} is not a literal")
        if vals.get("FRACTION") == fraction:
            hits.append((path.name, vals))
    if len(hits) > 1:
        fail(f"{where}: {fraction} has more than one town_full3d_factions profile ({[h[0] for h in hits]})")
    if not hits:
        return dict(frames)
    name, vals = hits[0]
    cw = vals.get("ANIM_CROSSWALK", {})
    if not isinstance(cw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in cw.items()):
        fail(f"{where}: profile {name} ANIM_CROSSWALK must map DEF id -> layer id (str -> str)")
    out = dict(frames)
    for src, dst in sorted(cw.items()):
        if src not in frames:
            fail(f"{where}: profile {name} ANIM_CROSSWALK key {src} is not a layers/anims DEF id")
        if src == dst:
            fail(f"{where}: profile {name} ANIM_CROSSWALK maps {src} onto itself")
        n = frames[src]
        have = out.get(dst, 1)
        if have > 1 and n > 1 and have != n:
            fail(f"{where}: layer {dst} is claimed by DEFs with {have} and {n} frames (ANIM_CROSSWALK {src})")
        out[dst] = max(have, n)
        del out[src]
    return out


def check_animation_audit(cat: dict, where: str) -> str:
    """Phase 4: every catalog layer whose HoMM3 DEF is animated (more than one frame in the fraction's
    layers/anims/metadata.json) names its moving effect pieces in "animationAudit", and each is an Fx_ piece of that
    layer (or of the co-present layer it declares "sharedWith")."""
    meta_p = REFS / str(cat.get("fraction")) / "layers" / "anims" / "metadata.json"
    if not meta_p.is_file():
        fail(f"{where}: phase 4 animation audit needs {meta_p}")
    frames = {m["id"]: len(m.get("frames") or []) for m in json.loads(meta_p.read_text(encoding="utf-8"))}
    frames = resolve_anim_crosswalk(frames, str(cat.get("fraction")), where)
    audit = cat.get("animationAudit")
    if not isinstance(audit, dict):
        fail(f"{where}: phase 4 requires animationAudit (layerId -> defFrames / moves / effects)")
    pieces = {r.get("layerId"): set(r.get("pieces") or []) for r in cat.get("layers") or []}
    cl = cat.get("clothLook") if isinstance(cat.get("clothLook"), dict) else {}
    cloth = {(p.get("layerId"), p.get("piece")) for p in cl.get("pieces") or []}
    n = 0
    for lid in sorted(pieces):
        nf = frames.get(lid, 1)
        if nf <= 1:
            if lid in audit:
                fail(f"{where}: animationAudit lists {lid} but its HoMM3 DEF is static")
            continue
        row = audit.get(lid)
        if not isinstance(row, dict):
            fail(f"{where}: {lid}: HoMM3 DEF has {nf} frames but animationAudit has no row (its effect is missing)")
        if row.get("defFrames") != nf:
            fail(f"{where}: {lid}: animationAudit defFrames {row.get('defFrames')} != DEF {nf}")
        if not str(row.get("moves") or "").strip():
            fail(f"{where}: {lid}: animationAudit row lacks 'moves' (what the DEF animates)")
        owner = row.get("sharedWith") or lid
        if owner not in pieces:
            fail(f"{where}: {lid}: sharedWith {owner} is not a catalog layer")
        if owner != lid and frames.get(owner, 1) <= 1:
            fail(f"{where}: {lid}: sharedWith {owner} is not an animated layer")
        eff = row.get("effects")
        if not isinstance(eff, list) or not eff:
            fail(f"{where}: {lid}: HoMM3 DEF has {nf} frames but animationAudit names no effect piece")
        bad = [e for e in eff if e not in pieces[owner]
               or not (str(e).startswith("Fx_") or (owner, e) in cloth)]
        if bad:
            fail(f"{where}: {lid}: animationAudit effects {bad} are not Fx_ pieces (or clothLook cloth pieces) of {owner}")
        n += 1
    stray = sorted(set(audit) - set(pieces))
    if stray:
        fail(f"{where}: animationAudit rows for layers not in the catalog: {stray}")
    return f" animated={n}"


def check_full3d(cat: dict, where: str, reachable: set, ids: list, bundle: Path, staged: bool, runtime_src: str,
                 device: str = PAN_DEFAULT_DEVICE) -> str:
    """The full-3D rules (module docstring). Returns a short summary for the OK line."""
    if cat.get("fullScene3d") is not True:
        return ""
    missing = sorted(reachable - set(ids))
    if missing:
        fail(f"{where}: fullScene3d but reachable layers have no 3D prefab (would render as 2D quads): {missing}")
    for r in cat.get("layers") or []:
        if r.get("sprites"):
            fail(f"{where}: fullScene3d but layer {r['layerId']} carries 2D sprites {r['sprites']}")
    if cat.get("layerDepths"):
        fail(f"{where}: fullScene3d but layerDepths is non-empty (2D quad depths)")
    if cat.get("backdrop") != "hidden":
        fail(f"{where}: fullScene3d requires \"backdrop\": \"hidden\" (the 2D backdrop quad must not draw)")
    env = cat.get("environment") or {}
    if not env.get("prefabKey"):
        fail(f"{where}: fullScene3d requires environment.prefabKey")
    env_pieces = env.get("pieces") or []
    if "Mesh_Terrain" not in env_pieces or not any(n.startswith("Sky_") for n in env_pieces):
        fail(f"{where}: environment must include Mesh_Terrain and a Sky_* dome (got {env_pieces})")
    names = list(env_pieces)
    for r in cat.get("layers") or []:
        names += [n for n in r.get("pieces") or []]
        if not any(n.startswith("Mesh_") or not n.startswith(("Sky_", "Fx_")) for n in r.get("pieces") or []):
            fail(f"{where}: layer {r['layerId']} has no mesh piece (the runtime Body needs one)")
    bad = [n for n in env_pieces if not n.startswith(FULL_PREFIXES)]
    if bad:
        fail(f"{where}: environment pieces outside Mesh_/Sky_/Fx_: {bad}")
    if any(n.startswith("Sprite_") or "quad" in n.lower() for n in names):
        fail(f"{where}: a piece is named as a sprite/quad: {[n for n in names if n.startswith('Sprite_') or 'quad' in n.lower()]}")
    rep = bundle.parent / (bundle.name + ".build_report.txt")
    lines = {}
    if bundle.is_file():
        if not rep.is_file():
            fail(f"{where}: fullScene3d bundle without its build report {rep.name}")
        lines = {ln.split(" ", 1)[0]: ln for ln in rep.read_text(encoding="utf-8").splitlines() if ln.strip()}
        keys = [env["prefabKey"]] + [r["prefabKey"] for r in cat.get("layers") or []]
        for k in keys:
            if k not in lines:
                fail(f"{where}: prefab {k} not in the bundle build report")
            if " sprites=0" not in lines[k]:
                fail(f"{where}: bundle prefab {k} contains sprite quads ({lines[k]})")
    if staged and "fullScene3d" not in runtime_src:
        fail(f"{where}: a fullScene3d catalog is staged but Homm3TownScene3d.cs does not parse fullScene3d "
             f"(the runtime would still draw the 2D backdrop and HotA quads)")
    if staged:
        # Runtime spec items (docs/homm3_conflux_full_3d_town.md): environment kept under the root, sky drawn first,
        # far clip past the dome, environment loaded by the preload gate; consumer hides both quads, skips
        # decoration and throws on a reachable layer without a prefab.
        for needle in ("EnsureEnvironment(", "SkyRenderQueue", "FullSceneMinFarClip",
                       "LoadPrefabByKeyOrThrow(catalog, EnvironmentCacheKey"):
            if needle not in runtime_src:
                fail(f"{where}: staged full-3D catalog but Homm3TownScene3d.cs lacks '{needle}'")
        visuals = (PLUGIN / "Homm3FactoryCityWorldVisuals.cs").read_text(encoding="utf-8").replace("\r\n", "\n")
        for needle in ("Homm3TownScene3d.EnsureEnvironment(", "hidden: full3d", "no 2D fallback in full-3D mode",
                       "if (!full3d)\n\t\t\tEnsureDecorationLayers("):
            if needle not in visuals:
                fail(f"{where}: staged full-3D catalog but Homm3FactoryCityWorldVisuals.cs lacks {needle!r}")
    return (f" full3d=on env={len(env_pieces)}" + check_phase2(cat, where, lines, bundle.parent, device=device)
            + check_props(cat, where) + check_ssr_water(cat, where, runtime_src)
            + check_sky_continuous(cat, where, runtime_src, bundle.parent) + check_cloth_look(cat, where, runtime_src)
            + check_town_scene_abi(cat, where))


# Plugin payload versions (docs/plugin_payload_abi.md): a catalog key the plugin only reads from TownScene vN on needs
# the source reader to declare at least vN, so it is installed only against a plugin that serves it
# (install_town_scene3d.py requires the installed sidecar to carry the source version).
TOWN_SCENE_ABI_SRC = PLUGIN / "PluginPayloadAbi.cs"
TOWN_SCENE_KEY_MIN = {"clothLook": 2, "skyLook": 2}


def town_scene_abi_need(cat: dict) -> int:
    """The lowest TownScene version that reads every key this catalog ships (1: the v1 baseline)."""
    return max([1] + [v for k, v in TOWN_SCENE_KEY_MIN.items() if cat.get(k) is not None])


def check_town_scene_abi(cat: dict, where: str) -> str:
    need = town_scene_abi_need(cat)
    have = int(const(TOWN_SCENE_ABI_SRC, r"TownSceneContractVersion\s*=\s*(\d+)"))
    if have < need:
        keys = sorted(k for k, v in TOWN_SCENE_KEY_MIN.items() if cat.get(k) is not None and v > have)
        fail(f"{where}: catalog ships {keys}, which need TownScene v{need}, but PluginPayloadAbi.cs declares v{have}")
    return f" abi=TownScene>={need}"


# The opt-in cloth wave (tools/homm3_town_scene_meshes/town_full3d_cloth.py, docs/homm3_town_cloth_wave.md).
CLOTH_SCHEMA = "town_full3d_cloth.v1"
# Runtime needles: the block is parsed, each cloth renderer's donor clone gets the native FLAG variant, and the prefab-
# frame vectors are converted to world space (power by localToWorld, direction by the inverse transpose).
CLOTH_RUNTIME_NEEDLES = ("clothLook", "ApplyClothWaveOrThrow(", "FlagDisplacementKeyword", "_FlagDirection",
                         "ClothDirectionWorld(renderer.worldToLocalMatrix", "RefreshClothWaves(root, catalog)")


def check_cloth_look(cat: dict, where: str, runtime_src: str) -> str:
    """Mesh_Cloth_<layer>_b<k> pieces ship only with a clothLook block that declares every one of them, on a layer
    whose animationAudit names exactly its cloth pieces and whose old Fx_Glow_ cloth overlay is gone; the wave
    vectors are finite and bounded by the banner's own length (a few % of it, never a sweep across the wall); and the
    runtime applies the native Hex/Lit FLAG variant with the world-space conversion. Source/static + generated
    artifact: how the wave looks in game is a separate (runtime) proof."""
    shipped = sorted((r.get("layerId"), p) for r in cat.get("layers") or [] for p in r.get("pieces") or []
                     if str(p).startswith("Mesh_Cloth_"))
    cl = cat.get("clothLook")
    if cl is None:
        if shipped:
            fail(f"{where}: layers ship cloth pieces {shipped[:4]} but clothLook is absent")
        return ""
    if not isinstance(cl, dict) or cl.get("schema") != CLOTH_SCHEMA:
        fail(f"{where}: clothLook must be a {CLOTH_SCHEMA} block")
    decl = sorted((p.get("layerId"), p.get("piece")) for p in cl.get("pieces") or [])
    if decl != shipped:
        fail(f"{where}: clothLook declares {len(decl)} pieces but the layers ship {len(shipped)} Mesh_Cloth_ pieces "
             f"({sorted(set(decl) ^ set(shipped))[:4]})")
    layers = {r.get("layerId"): r for r in cat.get("layers") or []}
    audit = cat.get("animationAudit") or {}
    for p in cl["pieces"]:
        lid, nm = p.get("layerId"), str(p.get("piece"))
        if not nm.startswith(f"Mesh_Cloth_{lid}_b"):
            fail(f"{where}: clothLook piece {nm} is not named Mesh_Cloth_{lid}_b<k>")
        try:
            pw = [float(x) for x in p["power"]]; dr = [float(x) for x in p["direction"]]
            sp, hu = float(p["speed"]), float(p["heightUnits"])
        except (KeyError, TypeError, ValueError):
            fail(f"{where}: clothLook piece {nm} lacks power/direction/speed/heightUnits")
        if len(pw) != 3 or len(dr) != 3 or not all(math.isfinite(x) for x in pw + dr + [sp, hu]) or hu <= 0:
            fail(f"{where}: clothLook piece {nm} has non-finite or malformed wave vectors")
        if math.sqrt(sum(x * x for x in pw)) > 0.2 * hu:
            fail(f"{where}: clothLook piece {nm} power {pw} exceeds 20% of its banner length {hu:.3f}")
        if not 0.5 <= sp <= 12.0:
            fail(f"{where}: clothLook piece {nm} speed {sp} outside 0.5..12 rad/s")
        if not re.fullmatch(r"[0-9a-f]{64}", str(p.get("colorsSha256", ""))):
            fail(f"{where}: clothLook piece {nm} lacks the vertex-colour sha256")
    for lid in cl.get("layers") or []:
        own = sorted(p["piece"] for p in cl["pieces"] if p.get("layerId") == lid)
        eff = sorted((audit.get(lid) or {}).get("effects") or [])
        if eff != own:
            fail(f"{where}: cloth layer {lid}: animationAudit effects {eff} are not its cloth pieces {own}")
        old = [x for x in (layers.get(lid) or {}).get("pieces") or [] if str(x).startswith("Fx_Glow_")]
        if old:
            fail(f"{where}: cloth layer {lid} still ships the old cloth overlay {old}")
    for needle in CLOTH_RUNTIME_NEEDLES:
        if needle not in runtime_src:
            fail(f"{where}: clothLook ships but Homm3TownScene3d.cs lacks '{needle}'")
    return f" cloth={len(decl)}"


# The opt-in SSR water (tools/homm3_town_scene_meshes/town_full3d_ssr_water.py, schema town_full3d_ssr_water.v1).
SSR_SCHEMA = "town_full3d_ssr_water.v1"
# Runtime needles: the catalog flag is parsed, the camera's depth texture is requested while the scene is shown, and the
# camera's original mode is restored when it is cleared (Homm3TownScene3d.EnsureCameraDepthTexture / Clear).
SSR_RUNTIME_NEEDLES = ("requiresCameraDepthTexture", "DepthTextureMode.Depth", "EnsureCameraDepthTexture(",
                       "RestoreCameraDepthTexture(")


def declared_shaders() -> dict:
    out = {}
    for f in sorted(FX_SHADER_DIR.glob("*.shader")) if FX_SHADER_DIR.is_dir() else []:
        txt = f.read_text(encoding="utf-8")
        m = re.search(r'^\s*Shader\s+"([^"]+)"', txt, re.M)
        if m:
            out[m.group(1)] = txt
    return out


def check_ssr_water(cat: dict, where: str, runtime_src: str) -> str:
    """A bundle shader that reads the camera depth texture ships only with catalog waterLook.screenSpaceReflection declaring
    requiresCameraDepthTexture true, and only with a runtime that requests and restores that texture. The SSR block's
    shader is a declared bundle shader that reads _CameraDepthTexture and _CameraColorTexture without a GrabPass (the
    game's Hex render pipeline is a scriptable pipeline: GrabPass does not run there), exposes the FlowWater shore /
    normal-map / specular inputs, and its pieces are built Fx_ environment pieces (fxmesh bins: the runtime
    re-materials Mesh_ pieces to Hex/Lit). Source/static + generated artifact: not proof that the game's pipeline fills
    either texture in the town scene."""
    declared = declared_shaders()
    shaders = cat.get("bundleShaders") or []
    depth_readers = sorted(n for n in shaders if n in declared and "_CameraDepthTexture" in declared[n])
    wl = cat.get("waterLook") if isinstance(cat.get("waterLook"), dict) else {}
    ssr = wl.get("screenSpaceReflection")
    if ssr is None:
        named = sorted(n for n in ((cat.get("environment") or {}).get("pieces") or []) if n.startswith("Fx_SsrWater"))
        if named:
            fail(f"{where}: environment ships SSR water pieces {named} but waterLook.screenSpaceReflection is absent")
        if depth_readers:
            fail(f"{where}: bundle shaders {depth_readers} read _CameraDepthTexture but waterLook.screenSpaceReflection is absent (the "
                 f"camera depth texture would never be requested: an SSR material cannot ship undeclared)")
        return ""
    if not isinstance(ssr, dict) or ssr.get("schema") != SSR_SCHEMA:
        fail(f"{where}: waterLook.screenSpaceReflection must be a {SSR_SCHEMA} block")
    if ssr.get("requiresCameraDepthTexture") is not True:
        fail(f"{where}: waterLook.screenSpaceReflection.requiresCameraDepthTexture must be true (the SSR shader reads the camera depth)")
    if ssr.get("requiresCameraColorTexture") is not True:
        fail(f"{where}: waterLook.screenSpaceReflection.requiresCameraColorTexture must be true (the SSR shader reads the colour copy)")
    sh = ssr.get("shader")
    if sh not in shaders or sh not in declared:
        fail(f"{where}: waterLook.screenSpaceReflection shader {sh!r} is not a declared bundle shader")
    stray = [n for n in depth_readers if n != sh]
    if stray:
        fail(f"{where}: bundle shaders {stray} read _CameraDepthTexture but are not the declared SSR shader {sh}")
    txt = declared[sh]
    for need in ("_CameraDepthTexture", "_CameraColorTexture", "_NormalMap", "_ShoreRange", "_ShoreOut", "_SpecDir",
                 "_TimeOffset", "_TimeScale"):
        if need not in txt:
            fail(f"{where}: SSR shader {sh} lacks {need}")
    if re.search(r"^\s*GrabPass\b", txt, re.M):
        fail(f"{where}: SSR shader {sh} uses a GrabPass (not run by the game's scriptable Hex pipeline)")
    pieces = ssr.get("pieces")
    env_pieces = set(((cat.get("environment") or {}).get("pieces")) or [])
    if not isinstance(pieces, list) or not pieces:
        fail(f"{where}: waterLook.screenSpaceReflection.pieces is empty")
    bad = [n for n in pieces if not str(n).startswith("Fx_") or n not in env_pieces]
    if bad:
        fail(f"{where}: waterLook.screenSpaceReflection pieces {bad} are not Fx_ environment pieces (fxmesh bins keep their material)")
    missing = [n for n in SSR_RUNTIME_NEEDLES if n not in runtime_src]
    if missing:
        fail(f"{where}: waterLook.screenSpaceReflection ships but Homm3TownScene3d.cs lacks {missing} (the camera would not provide "
             f"the depth texture the SSR material reads)")
    return f" ssr={len(pieces)}"


# The opt-in continuous sky (tools/homm3_town_scene_meshes/town_full3d_sky_continuous.py, schema
# town_full3d_sky_continuous.v1; docs/homm3_town_sky_continuous.md): ONE Sky_ surface drawn by a */SkyPanorama shader.
SKY_SCHEMA = "town_full3d_sky_continuous.v1"
SKY_SHADER_NEEDLES = ("_SkyFwd", "_SkyRight", "_SkyUp", "unity_WorldToObject", "UNITY_REVERSED_Z", "ZWrite On",
                      "tex2Dgrad", "_TimeOffset", "_TimeScale")
# Runtime needles: the catalog block is parsed (schema pinned), the declared piece keeps its bundle material only when
# its shader is the declared one, an undeclared panorama shader is refused, and more than one Sky_ piece is refused.
SKY_RUNTIME_NEEDLES = ('SkySchema = "town_full3d_sky_continuous.v1"', "ParseSkyLookOrThrow(", "KeepSkyPanoramaOrThrow(",
                       "but the catalog's skyLook does not declare it", "the sky must be a single surface",
                       "-Time.timeSinceLevelLoad")


def check_sky_continuous(cat: dict, where: str, runtime_src: str, folder: Path | None) -> str:
    """The continuous sky: a */SkyPanorama bundle shader ships only with catalog skyLook; skyLook names the ONE Sky_
    environment piece (a single surface), a declared shader that looks the panorama up by direction (object-space
    camera position: zero parallax), pins depth to the far plane and has no GrabPass / camera-texture read; the
    runtime keeps it fail-closed; and sky_continuity.npz (sha-pinned) re-measures within the lane's limits: no straight
    seam line standing out more than the painting's own, the wrap column, the painted-edge step, the rest view against
    the HoMM3 painting, the relief no longer carrying painted sky, and a synthetic seam the detector must catch.
    Generated artifact + source/static: not proof of the editor render or of the game's Hex pipeline."""
    declared = declared_shaders()
    shaders = cat.get("bundleShaders") or []
    env_pieces = list(((cat.get("environment") or {}).get("pieces")) or [])
    sky_pieces = [n for n in env_pieces if n.startswith("Sky_")]
    pano_shaders = sorted(n for n in shaders if n.endswith("/SkyPanorama"))
    sky = cat.get("skyLook")
    if sky is None:
        if pano_shaders:
            fail(f"{where}: bundle shaders {pano_shaders} are sky panoramas but catalog skyLook is absent (the runtime "
                 f"would draw the piece with the sprite dome material)")
        return ""
    if not isinstance(sky, dict) or sky.get("schema") != SKY_SCHEMA:
        fail(f"{where}: skyLook must be a {SKY_SCHEMA} block")
    sh = sky.get("shader")
    if sh not in shaders or sh not in declared or not str(sh).endswith("/SkyPanorama"):
        fail(f"{where}: skyLook shader {sh!r} is not a declared */SkyPanorama bundle shader")
    if pano_shaders != [sh]:
        fail(f"{where}: bundle sky panorama shaders {pano_shaders} are not exactly skyLook's {sh}")
    txt = declared[sh]
    for need in SKY_SHADER_NEEDLES:
        if need not in txt:
            fail(f"{where}: sky shader {sh} lacks {need}")
    if re.search(r"^\s*GrabPass\b", txt, re.M) or "_CameraDepthTexture" in txt or "_CameraColorTexture" in txt:
        fail(f"{where}: sky shader {sh} reads a GrabPass / camera texture (the sky reads its panorama only)")
    if sky_pieces != [sky.get("piece")]:
        fail(f"{where}: skyLook declares the one sky {sky.get('piece')!r} but the environment's Sky_ pieces are "
             f"{sky_pieces}: the sky must be a single surface")
    missing = [n for n in SKY_RUNTIME_NEEDLES if n not in runtime_src]
    if missing:
        fail(f"{where}: skyLook ships but Homm3TownScene3d.cs lacks {missing}")
    # a drifting sky is the one panorama turning (the profile's SKY_ANIM drift folded into the shader), never a band
    import importlib.util
    prof = []
    for path in sorted(PROFILES.glob("*.py")):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(f"_town_profile_skyc_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "FRACTION", None) == cat.get("fraction"):
            prof.append(mod)
    if len(prof) != 1:
        fail(f"{where}: skyLook needs exactly one town_full3d_factions profile for {cat.get('fraction')}")
    anim = getattr(prof[0], "SKY_ANIM", None) or {}
    want_drift = round(360.0 / float(anim["periodS"]), 6) if anim.get("mode") == "drift" else 0.0
    if sky.get("driftDegPerSec") != want_drift:
        fail(f"{where}: skyLook.driftDegPerSec {sky.get('driftDegPerSec')!r} is not the profile's SKY_ANIM drift "
             f"{want_drift} (360 / periodS, 0 when static)")
    if folder is None:
        fail(f"{where}: skyLook needs its evidence folder")
    npz = folder / str(sky.get("file") or "")
    if not npz.is_file() or hashlib.sha256(npz.read_bytes()).hexdigest() != sky.get("sha256"):
        fail(f"{where}: skyLook evidence {npz.name} is missing or its sha256 differs from the catalog")
    lane = ROOT / "tools" / "homm3_town_scene_meshes"
    if str(lane) not in sys.path:
        sys.path.insert(0, str(lane))
    import warnings
    import numpy as np
    import town_full3d_sky_continuous as SKYC
    lim = sky.get("limits") or {}
    pinned = {"seamRelPaintingMax": SKYC.SEAM_REL_MAX, "wrapRatioMax": SKYC.WRAP_RATIO_MAX,
              "edgeRatioMax": SKYC.EDGE_RATIO_MAX, "restDeltaEMean": SKYC.REST_DE_MEAN_MAX,
              "restDeltaEP95": SKYC.REST_DE_P95_MAX, "reliefSkyPxMax": SKYC.RELIEF_SKY_PX_MAX}
    drift = {k: (lim.get(k), v) for k, v in pinned.items() if lim.get(k) != v}
    if drift:
        fail(f"{where}: skyLook.limits differ from the lane's pinned limits {drift}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        z = np.load(npz)
        if str(z["schema"]) != SKY_SCHEMA:
            fail(f"{where}: {npz.name} is not {SKY_SCHEMA}")
        m = SKYC.measure_evidence(z)
        neg = SKYC.synthetic_negative(z)
    pv = max(m["paintingSeams"]["vertical"]["max"], 1e-3)
    if neg["verticalMax"] / pv <= SKYC.SEAM_REL_MAX:
        fail(f"{where}: the sky seam detector misses a synthetic strip seam ({neg['verticalMax']:.2f} vs the "
             f"painting's {pv:.2f}): the seam check is blind")
    if not m["ok"]:
        fail(f"{where}: continuous sky outside its limits: seamRelPainting={m['seamRelPainting']} "
             f"wrap={m['wrapRatio']} edge={m['edge']['max']} restDeltaE={m['restDeltaE']} "
             f"restFromPano={m['restFromPano']} reliefSkyPx={m['reliefSkyPxAfter']} (limits {pinned})")
    return (f" sky=1:{sky['piece']} seamRel={max(m['seamRelPainting'].values()):.2f} wrap={m['wrapRatio']:.2f} "
            f"edge={m['edge']['max']:.2f} restDE={m['restDeltaE']['mean']:.2f}/{m['restDeltaE']['p95']:.2f} "
            f"reliefSky={m['reliefSkyPxBefore']}->{m['reliefSkyPxAfter']}")


PROFILES = ROOT / "tools" / "homm3_town_scene_meshes" / "town_full3d_factions"
# The Conflux lane's periphery declaration (phase 6b, installed): conifer forest, bushes and boulders are all required
# and built outside the frame; its near field is hand-dressed pieces (Mesh_NearGrass/Flowers/Pebbles/Rocks/Roots),
# not a measured scrub density. Its catalogs carry no per-kind prefixes, so these are the prefixes checked.
CONFLUX_LANE_SCATTER = {
    "scrub": {"required": True, "prefixes": ["Mesh_Outer_conifer_a_", "Mesh_Outer_conifer_b_"],
              "catalogPrefixes": False},
    "bush": {"required": True, "prefixes": ["Mesh_Outer_bush_"], "catalogPrefixes": False},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"], "catalogPrefixes": False},
    "nearDensity": {"source": "none", "reason": "the Conflux near field is hand-dressed pieces "
                                                "(Mesh_NearGrass/Flowers/Pebbles/Rocks/Roots), not scrub blobs"},
}


def scatter_policy(fraction: str, where: str, lane_form: bool = False) -> dict:
    """The periphery scatter policy the fraction's full-3D profile declares (PERIPHERY_SCATTER). Fails closed: a
    fraction with no profile, or a profile without a well-formed declaration, fails. lane_form: the catalog's scatter
    kinds carry no per-kind prefixes (the Conflux phase-6 lane's catalogs predate them; every town_full3d catalog
    writes them); for homm3_conflux such a catalog is held to CONFLUX_LANE_SCATTER, a recipe-v2 one to its profile."""
    import importlib.util
    hits = []
    for path in sorted(PROFILES.glob("*.py")):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(f"_town_profile_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "FRACTION", None) == fraction:
            hits.append((path.name, mod))
    if fraction == "homm3_conflux" and (lane_form or not hits):
        # Conflux is built on its own lane (docs/homm3_conflux_full_3d_town.md), not from a town_full3d profile; its
        # declaration lives here and is held to the same rules below.
        name, pol, scrub_mesh = "CONFLUX_LANE_SCATTER", CONFLUX_LANE_SCATTER, True
    elif len(hits) != 1:
        fail(f"{where}: {fraction} needs exactly one town_full3d_factions profile (found {[h[0] for h in hits]})")
    else:
        name, mod = hits[0]
        pol = getattr(mod, "PERIPHERY_SCATTER", None)
        scrub_mesh = getattr(mod, "SCRUB_MESH", None) is not None
    if not isinstance(pol, dict) or not {"scrub", "rock", "nearDensity"} <= set(pol) <= {"scrub", "bush", "rock",
                                                                                         "nearDensity"}:
        fail(f"{where}: profile {name} must declare PERIPHERY_SCATTER with scrub / rock / nearDensity (bush optional)")
    for k in [k for k in ("scrub", "bush", "rock") if k in pol]:
        d = pol[k]
        if not isinstance(d, dict) or not isinstance(d.get("required"), bool):
            fail(f"{where}: profile {name} PERIPHERY_SCATTER.{k}.required must be a boolean")
        if d["required"] and not (isinstance(d.get("prefixes"), list) and d["prefixes"]):
            fail(f"{where}: profile {name} PERIPHERY_SCATTER.{k} is required without prefixes")
        if not d["required"] and not str(d.get("reason") or "").strip():
            fail(f"{where}: profile {name} PERIPHERY_SCATTER.{k} is not required without a reason")
    nd = pol["nearDensity"]
    if not isinstance(nd, dict) or nd.get("source") not in ("measured", "profile", "none") or (
            nd["source"] == "profile" and not (isinstance(nd.get("perM2"), float) and nd["perM2"] > 0
                                               and str(nd.get("reason") or "").strip())) or (
            nd["source"] == "none" and not str(nd.get("reason") or "").strip()):
        fail(f"{where}: profile {name} PERIPHERY_SCATTER.nearDensity must be measured, profile with perM2 > 0 "
             f"and a reason, or none with a reason")
    if bool(pol["scrub"]["required"]) != scrub_mesh:
        fail(f"{where}: profile {name} PERIPHERY_SCATTER.scrub.required disagrees with its SCRUB_MESH")
    return pol


def check_town_gpu_lock() -> None:
    """The lane's single-flight GPU lock breaks a holder only when provably gone (the old tasklist-grep liveness test
    read any failure as dead), and the gate asks for need + VRAM_MARGIN_GB free (a point-in-time check with Blender
    bakes growing beside it). Full test: test_town_gpu_lock.py."""
    lane = ROOT / "tools" / "homm3_town_scene_meshes"
    src = (lane / "town_full3d_gpu.py").read_text(encoding="utf-8")
    if "pid_alive" in src or "def holder_state" not in src:
        fail("town_full3d_gpu.py: the lock's stale test must be holder_state (never gpuslot.pid_alive)")
    sys.path.insert(0, str(lane))
    import town_full3d_gpu as G
    st, ct = G._creation_time(os.getpid())
    if st != "alive" or not ct:
        fail(f"town_full3d_gpu: own process probes as {st!r} (creation {ct})")
    for h, bad in (({"pid": os.getpid(), "created": ct}, ("gone",)), ({"pid": "x"}, ("gone",)),
                   ({"pid": os.getpid(), "created": ct + 1}, ("alive", "unknown"))):
        if G.holder_state(h) in bad:
            fail(f"town_full3d_gpu.holder_state({h}) = {G.holder_state(h)!r}: the single-flight lock is not fail-closed")
    if getattr(G, "VRAM_MARGIN_GB", 0) < 2.5 or G.vram_ok(13.4, 11.0) or (
        G._capacity_problem(11.0, (5.0, 32.0, 13.4, 16.0)) is None
        or G._capacity_problem(11.0, (5.0, 32.0, 13.5, 16.0)) is not None
    ):
        fail("town_full3d_gpu: the gate must require free VRAM >= need + VRAM_MARGIN_GB (>= 2.5 GB)")


# profiles that keep the mirror-filled dome on purpose (key: reason); every other profile with a sky takes SKY_PANO
SKY_PANO_EXEMPT = {"stronghold": "finished in its own lane; its staged dome stays byte-identical until a separate change"}


def check_town_sky_pano() -> None:
    """Every faction profile whose SKY_ANIM is not "none" declares SKY_PANO (the static dome's periodic SD panorama),
    unless SKY_PANO_EXEMPT names it: the mirror fill streaked right of the painted rect (x1440 under the sweeps) and
    mirrored a second moon on every faction that kept it. Castle's drift reads its panorama from SKY_PANO too."""
    import importlib.util
    for path in sorted(PROFILES.glob("*.py")):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(f"_town_profile_sky_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        anim = getattr(mod, "SKY_ANIM", None)
        mode = anim.get("mode") if isinstance(anim, dict) else None
        pano = getattr(mod, "SKY_PANO", None)
        if isinstance(anim, dict) and "pano" in anim:
            fail(f"profile {path.name}: the panorama lives in SKY_PANO, not SKY_ANIM['pano']")
        if mode == "none" or path.stem in SKY_PANO_EXEMPT:
            continue
        if not (isinstance(pano, dict) and all(isinstance(pano.get(k), str) and pano[k].strip()
                                               for k in ("key", "prompt", "negative"))
                and isinstance(pano.get("seed"), int)):
            fail(f"profile {path.name}: SKY_ANIM mode {mode!r} needs SKY_PANO (key / prompt / negative / seed) "
                 f"for the dome, or SKY_ANIM mode 'none'")


def check_town_houses_carve() -> None:
    """Houses lane silhouette carve (multi-group): a rest silhouette is the per-triangle coverage (one fillPoly over the
    overlapping triangle list fills even-odd and dropped up to 11 % of a house), its Z is the farthest covering
    triangle, the carve grows only into px some placed model covers, and the carved terrain never sits in front of
    the model it was carved for. Synthetic: two overlapping triangles under an orthographic stub projection."""
    import json as _json
    import tempfile
    lane = ROOT / "tools" / "homm3_town_scene_meshes"
    sys.path.insert(0, str(lane))
    import numpy as np
    import town_full3d_houses as HS
    src = (lane / "town_full3d_houses.py").read_text(encoding="utf-8")
    if "& cover & ~foreign" not in src or "lim = group_behind()" not in src:
        fail("town_full3d_houses: the silhouette carve must stay inside the models' rest coverage and put the carved "
             "terrain behind the model (group_behind)")
    V = np.array([[10, 10, 5], [60, 10, 5], [10, 60, 5], [30, 30, 9], [70, 30, 9], [30, 70, 9]], np.float64)
    model = {"V": V, "F": np.array([[0, 1, 2], [3, 4, 5]])}
    ins = {"label": 1, "base": [0.0, 0.0, 0.0], "scale": 1.0, "yaw": 0.0}

    class _T:
        @staticmethod
        def project(cam, P):
            return P[:, 0], P[:, 1], P[:, 2]
    real_t = HS.T
    HS.T = _T
    try:
        with tempfile.TemporaryDirectory() as td:
            hd = Path(td)
            (hd / "placement.json").write_text(_json.dumps({"instances": [ins]}), encoding="utf-8")
            HS.write_silhouettes(hd, type("Sc", (), {"cam": None})(), model, [ins])
            with np.load(hd / "silhouettes.npz") as z:
                L, Z = z["L1"].copy(), z["Z1"].copy()
    finally:
        HS.T = real_t
    if not (L[35, 35] and L[15, 15] and L[50, 50]) or L[80, 80]:
        fail("town_full3d_houses.write_silhouettes: rest silhouette is not the per-triangle coverage (overlap dropped)")
    if not (abs(float(Z[35, 35]) - 9.0) < 1e-4 and abs(float(Z[15, 15]) - 5.0) < 1e-4) or np.isfinite(Z[80, 80]):
        fail("town_full3d_houses.write_silhouettes: Z<label> is not the farthest covering triangle's depth")
    if (L != np.isfinite(Z)).any():
        fail("town_full3d_houses.write_silhouettes: L<label> and Z<label> coverage disagree")


def main() -> int:
    global GAME_DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, help="check a candidate catalog (bundle beside it) instead of the staged ones")
    ap.add_argument("--game-data-root", type=Path,
                    help="native HeroesOldenEra_Data root for an explicit port camera verification")
    ap.add_argument("--camera-json", type=Path,
                    help="camera extraction JSON to verify (port checks require v2 exact input provenance)")
    ap.add_argument("--camera-provenance-only", action="store_true",
                    help="check all staged town camera contracts against current native data without rerunning art gates")
    ap.add_argument("--camera-catalog-dir", type=Path,
                    help="target <fraction>/catalog.json directory for --camera-provenance-only")
    ap.add_argument("--camera-source-catalog-dir", type=Path,
                    help="Golden source catalogs that target catalogs must preserve except restPose")
    ap.add_argument("--camera-canonical-json", type=Path,
                    help="fresh Golden v2 cityHuman2 extraction used for port camera compatibility")
    ap.add_argument("--device", choices=("cuda", "cpu"), default=PAN_DEFAULT_DEVICE,
                    help="pan-coverage device (default: cuda; cpu is the explicit NumPy reference)")
    ap.add_argument("--runtime-boundary-only", action="store_true",
                    help="check the cheap menu-vs-first-use source contract without GPU or bundle validation")
    ap.add_argument("--only", action="append", default=[], metavar="homm3_<faction>",
                    help="staged mode: check only these scene3d folders (the installer re-checks just the towns it "
                         "installed); without it every staged town is checked, as the build and releases do")
    args = ap.parse_args()
    if bool(args.game_data_root) != bool(args.camera_json):
        fail("--game-data-root and --camera-json must be provided together")
    if args.game_data_root:
        GAME_DATA = args.game_data_root.resolve()
        if not GAME_DATA.is_dir():
            fail(f"--game-data-root is not a directory: {GAME_DATA}")
        if str(PAN_MODULE_DIR) not in sys.path:
            sys.path.insert(0, str(PAN_MODULE_DIR))
        import conflux_town_camera_pan as pan
        import extract_city_camera_pan as extractor
        pan.PAN_JSON = args.camera_json.resolve()
        extractor.GAME = GAME_DATA
        try:
            camera_schema = json.loads(pan.PAN_JSON.read_text(encoding="utf-8")).get("schema")
        except (OSError, ValueError) as exc:
            fail(f"cannot read --camera-json {pan.PAN_JSON}: {exc}")
        if camera_schema != "homm3.vanilla_city_camera_pan.v2":
            fail("explicit --camera-json must use the v2 exact consumed-file provenance schema")
    if args.camera_provenance_only:
        if not (args.game_data_root and args.camera_catalog_dir and args.camera_source_catalog_dir and
                args.camera_canonical_json):
            fail("--camera-provenance-only requires --game-data-root, --camera-json, --camera-catalog-dir, "
                 "--camera-source-catalog-dir, and --camera-canonical-json")
        if args.catalog or args.only:
            fail("--camera-provenance-only cannot be combined with --catalog or --only")
        check_camera_provenance_catalogs(args.camera_catalog_dir.resolve(), args.camera_source_catalog_dir.resolve(),
                                         args.camera_canonical_json.resolve())
        return 0
    if args.camera_catalog_dir or args.camera_source_catalog_dir or args.camera_canonical_json:
        fail("camera catalog and canonical JSON inputs require --camera-provenance-only")
    check_runtime_load_boundary()
    if args.runtime_boundary_only:
        print("town-scene3d-contract: OK runtime menu/first-use asset-load boundary")
        return 0
    load_pan_constants()
    if args.device == "cuda":
        if str(PAN_MODULE_DIR) not in sys.path:
            sys.path.insert(0, str(PAN_MODULE_DIR))
        from town_gpu_pan import ensure_cuda_available
        try:
            ensure_cuda_available()
        except Exception as exc:
            fail(str(exc))
    check_town_gpu_lock()
    check_town_houses_carve()
    check_town_sky_pano()
    for p in (RUNTIME, BUILDER, GAME_SYMBOLS, CONFIG):
        if not p.is_file():
            fail(f"missing {p}")
    runtime_schema = const(RUNTIME, r'CatalogSchema\s*=\s*"([^"]+)"')
    builder_schema = const(BUILDER, r'CATALOG_SCHEMA\s*=\s*"([^"]+)"')
    if runtime_schema != builder_schema:
        fail(f"schema drift: runtime {runtime_schema} vs builder {builder_schema}")
    rest_runtime_schema = const(RUNTIME, r'RestPoseCatalogSchema\s*=\s*"([^"]+)"')
    rest_builder_schema = const(ROOT / "tools" / "homm3_town_scene_meshes" / "build_conflux_full3d_scene.py",
                                r'REST_POSE_CATALOG_SCHEMA\s*=\s*"([^"]+)"')
    if rest_runtime_schema != rest_builder_schema or rest_runtime_schema == runtime_schema:
        fail(f"rest-pose schema drift: runtime {rest_runtime_schema}, builder {rest_builder_schema}, legacy {runtime_schema}")
    src = RUNTIME.read_text(encoding="utf-8")
    if const(RUNTIME, r'FramingSchema\s*=\s*"([^"]+)"') != "town_full3d_framing.v1":
        fail("Homm3TownScene3d.cs FramingSchema drifted from town_full3d_framing.v1")
    for needle in ("root.position = pivot.TransformPoint(catalog.RestLocalPosition)",
                   "root.rotation = pivot.rotation * catalog.RestLocalRotation * catalog.FramingAim",
                   "Mathf.Tan(NativeFov(camera) * 0.5f", "RestoreFraming();"):
        if needle not in src:
            fail(f"Homm3TownScene3d.cs v2 seating is missing {needle!r}")
    apply_start = src.find("internal static void ApplyLighting(")
    capture_start = src.find("if (VolumeOverrides.Count", apply_start)
    if apply_start < 0 or capture_start < 0 or "frame = root.transform" not in src[apply_start:capture_start]:
        fail("Homm3TownScene3d.cs v2 lighting must use the fixed scene root frame")
    if "IsKeywordEnabled" in src:
        fail("Homm3TownScene3d.cs calls IsKeywordEnabled (throws on this interop; use shaderKeywords)")
    # The Hex pipeline (bdr::kqq -> bdw::ktg) rewrites the main light's rotation and RenderSettings.fog from the
    # city's Hex.Render.LightingSettings volume on every camera render: key light and fog must go through it.
    # Field writes only (4ec34e2f22): ParameterOverride<T>.Override(T) is a value-type generic instantiation the
    # game never calls; the first in-game call died with coreclr 0xc0000005 right after "driving LightingSettings".
    for needle in ("lightZenithAngle.overrideState = true", "lightAzimuthAngle.overrideState = true",
                   "fogEnabled.overrideState = true", "Volume.profile = null"):
        if needle not in src:
            fail(f"Homm3TownScene3d.cs must drive the key/fog through LightingSettings (missing '{needle}')")
    if re.search(r"\w\.Override\(", src):
        fail("Homm3TownScene3d.cs calls ParameterOverride<T>.Override(T) (no IL2CPP body; write overrideState/value)")
    if re.search(r"^\s*RenderSettings\.fog\s*=(?!=)", src, re.M):
        fail("Homm3TownScene3d.cs writes RenderSettings.fog; bdw::ktg overwrites it every render (use fogEnabled)")
    if re.search(r"_sun\b|FindSceneSun", src):
        fail("Homm3TownScene3d.cs rotates the scene sun directly; bdw::ktg overwrites it every render")
    owned_block = re.search(r"OwnedCityWorldFactionSids\s*=\s*\{(.*?)\}", GAME_SYMBOLS.read_text(encoding="utf-8"), re.S)
    if not owned_block:
        fail("GameSymbols.OwnedCityWorldFactionSids not found")
    owned = set(re.findall(r'"([^"]+)"', owned_block.group(1)))
    cfg_text = CONFIG.read_text(encoding="utf-8-sig")
    flag_on = bool(re.search(r'"homm3TownScene3d"\s*:\s*true', cfg_text))

    if args.catalog:
        cat_paths = [(args.catalog.resolve(), False)]
    else:
        folders = sorted(p for p in SCENE3D.iterdir() if p.is_dir()) if SCENE3D.is_dir() else []
        if flag_on and not folders:
            fail("config homm3TownScene3d=true but no scene3d catalog is staged")
        if args.only:
            names = {f.name for f in folders}
            unknown = sorted(set(args.only) - names)
            if unknown:
                fail(f"--only names no staged scene3d folder: {unknown} (staged: {sorted(names)})")
            folders = [f for f in folders if f.name in set(args.only)]
        cat_paths = [(f / "catalog.json", True) for f in folders]
    folders = cat_paths
    rest_pose_verifier = NativeCameraRestPoseVerifier()
    for cat_path, staged in cat_paths:
        folder = cat_path.parent
        if not cat_path.is_file():
            fail(f"{folder}: catalog.json missing")
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        fraction = folder.name if staged else str(cat.get("fraction"))
        where = f"{fraction}/catalog.json" if staged else str(cat_path)
        schema = cat.get("schema")
        if schema not in (runtime_schema, rest_runtime_schema):
            fail(f"{where}: unrecognized schema {schema}")
        if cat.get("fullScene3d") is True and not cat.get("phaseRevision"):
            fail(f"{where}: fullScene3d requires a phaseRevision")
        if revision_at_least(cat, "6") and cat.get("fullScene3d") is True and schema != rest_runtime_schema:
            fail(f"{where}: phase-6 full-3D catalog requires {rest_runtime_schema} fixed rest-pose seating")
        if schema == rest_runtime_schema and cat.get("fullScene3d") is not True:
            fail(f"{where}: rest-pose schema requires fullScene3d")
        if schema == rest_runtime_schema and not revision_at_least(cat, "6"):
            fail(f"{where}: rest-pose schema requires phaseRevision 6 or later")
        if cat.get("fraction") != fraction:
            fail(f"{where}: fraction {cat.get('fraction')} != folder {fraction}")
        if fraction not in owned:
            fail(f"{where}: {fraction} is not an owned city-world fraction (GameSymbols)")
        positions = REFS / fraction / "layers" / "positions.json"
        if not positions.is_file():
            fail(f"{where}: positions.json missing for {fraction}")
        layer_ids = {l["id"] for l in json.loads(positions.read_text(encoding="utf-8"))["layers"]}

        rows = cat.get("layers") or []
        if not rows:
            fail(f"{where}: no layers")
        ids = [r.get("layerId") for r in rows]
        keys = [r.get("prefabKey") for r in rows]
        if len(set(ids)) != len(ids) or len(set(keys)) != len(keys) or not all(ids) or not all(keys):
            fail(f"{where}: layerId/prefabKey missing or duplicated")
        unknown = set(ids) - layer_ids
        if unknown:
            fail(f"{where}: layers not in positions.json: {sorted(unknown)}")
        for r in rows:
            if not r.get("pieces"):
                fail(f"{where}: layer {r['layerId']} has no mesh piece")

        layer_map_path = REFS / fraction / "layers" / "building_layer_map.json"
        if not layer_map_path.is_file():
            fail(f"{where}: building_layer_map.json missing for {fraction}")
        layer_map = json.loads(layer_map_path.read_text(encoding="utf-8-sig"))
        native = layer_map.get("nativeLevels")
        if not isinstance(native, dict) or not native:
            fail(f"{fraction}/building_layer_map.json: nativeLevels missing")
        reachable = {v for lv in native.values() if isinstance(lv, dict) for v in lv.values()}
        position_rows = json.loads(positions.read_text(encoding="utf-8"))["layers"]
        reachable |= {l["id"] for l in position_rows
                      if str(l.get("structure") or "").lower().startswith("decoration")}
        unreachable = sorted(set(ids) - reachable)
        if unreachable:
            fail(f"{where}: meshed layers no native level reaches (never rendered): {unreachable}; map them in "
                 f"nativeLevels via nativeLevelSourceOverrides (tools/generate_owned_city_native_levels.py)")
        unused = layer_map.get("unusedLayers") or {}
        if not isinstance(unused, dict) or not all(isinstance(v, str) and v.strip() for v in unused.values()):
            fail(f"{fraction}/building_layer_map.json: unusedLayers must map layerId -> non-empty reason")
        for lid in sorted(unused):
            if lid not in layer_ids:
                fail(f"{fraction}/building_layer_map.json: unusedLayers {lid} is not a positions.json layer")
            if lid in reachable:
                fail(f"{fraction}/building_layer_map.json: unusedLayers {lid} is still reachable")
            if lid in ids:
                fail(f"{where}: unused layer {lid} is meshed")

        depths = cat.get("layerDepths")
        if not isinstance(depths, list):
            fail(f"{where}: layerDepths must be an array of rows")
        dmap = {}
        for d in depths:
            lid, dist = d.get("layerId"), d.get("distance")
            if lid in dmap:
                fail(f"{where}: duplicate layerDepths row {lid}")
            if not isinstance(dist, (int, float)) or not (0 < dist < BACKDROP_LIMIT):
                fail(f"{where}: layerDepths {lid}={dist} not in (0, {BACKDROP_LIMIT})")
            dmap[lid] = dist
        expected = set() if cat.get("fullScene3d") is True else layer_ids - set(ids)
        if set(dmap) != expected:
            fail(f"{where}: layerDepths must cover exactly the 2D layers; missing {sorted(expected - set(dmap))}, "
                 f"extra {sorted(set(dmap) - expected)}")

        unit(cat.get("keyLight", {}).get("cameraLocalDir"), f"{where}: keyLight.cameraLocalDir")
        fill = cat.get("fillLight") or {}
        unit(fill.get("cameraLocalDir"), f"{where}: fillLight.cameraLocalDir")
        col = fill.get("linearColor")
        if not isinstance(col, list) or len(col) != 3 or min(col) < 0 or max(col) <= 0:
            fail(f"{where}: fillLight.linearColor must be 3 non-negative numbers, not black")
        if cat.get("fog") != "off":
            fail(f"{where}: fog must be 'off' (Hex/Lit fog at 16-92 would wash the meshes; see the pilot doc)")
        ref = cat.get("referenceCamera") or {}
        if not (1 < float(ref.get("fov", 0)) < 179) or float(ref.get("aspect", 0)) <= 0:
            fail(f"{where}: referenceCamera fov/aspect invalid")
        rest_note = rest_pose_verifier.check(cat, where) if schema == rest_runtime_schema else ""
        rest_note += check_framing(ref, where, schema == rest_runtime_schema)
        if schema == runtime_schema and ref.get("restPose") is not None:
            fail(f"{where}: legacy schema must not contain a restPose that runtime ignores")
        if not (0 < float(cat.get("depthScale", 0)) <= 1):
            fail(f"{where}: depthScale must be in (0, 1]")

        bundle = folder / str(cat.get("bundle") or "")
        if not cat.get("bundle"):
            fail(f"{where}: bundle name missing")
        if bundle.is_file():
            bundle_bytes, bundle_sha256 = file_sha256_and_size(bundle)
            if bundle_bytes != cat.get("bundleBytes") or bundle_sha256 != cat.get("bundleSha256"):
                fail(f"{where}: staged bundle does not match bundleBytes/bundleSha256 (rebuild and restage)")
        elif flag_on and staged:
            fail(f"{where}: config homm3TownScene3d=true but bundle {bundle.name} is not staged")
        full = check_full3d(cat, where, reachable - {l["id"] for l in position_rows
                                                     if str(l.get("structure") or "").lower().startswith("decoration")},
                            ids, bundle, staged, src, device=args.device)
        print(f"town-scene3d-contract: OK {fraction} layers={len(ids)} reachable={len(ids)} unused={len(unused)} "
              f"depths={len(dmap)} "
              f"bundle={'present' if bundle.is_file() else 'absent'} flag={'on' if flag_on else 'off'}"
              f"{'' if staged else ' (candidate)'}{rest_note}{full}")
    if not folders:
        print("town-scene3d-contract: OK (no scene3d catalog staged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
