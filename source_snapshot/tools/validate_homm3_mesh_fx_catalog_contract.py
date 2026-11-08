#!/usr/bin/env python3
"""Fail-closed contract for the shared HoMM3 mesh FX catalog.

Proves catalog shape only (source/static). Does not prove in-map fire or
in-combat sparks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_mesh_fx"
    / "catalog.json"
)
PLUGIN_FX_ROOT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_mesh_fx"
)
SCHEMA = "homm3_mesh_fx_catalog.v1"
# Static witness of the installed ResourceManager container, written by
# `python tools/homm3_vfx/vanilla_vfx_probe.py keys --catalog` (the build never reads the install).
KEYS_WITNESS = ROOT / "tools" / "homm3_vfx" / "native_res_keys.json"
KEYS_SCHEMA = "homm3_native_res_keys.v1"
# Container names may themselves contain dots (cavalry_upg_kn_w-c.feather.l.003), so an extension is a known
# Unity asset suffix, not any dot; the witness lookup below is what proves the key exists.
ASSET_EXTENSIONS = (".prefab", ".asset", ".mat", ".png", ".tga", ".jpg", ".psd", ".fbx", ".glb", ".anim",
                    ".controller", ".shader", ".unity", ".bundle")
# The Fire Elemental conservatory's fire column is the map-building proof row. The whole-prefab
# altar_of_fire_avgfire0 row it superseded (fx_map_fire dropped on mesh bounds) must stay gone.
MAP_PROOF_ID = "mbfx_conflux_dwellings__avgfire0_fire0"
REQUIRED_IDS = (MAP_PROOF_ID, "crusader_attack_sparks")
SUPERSEDED_IDS = ("altar_of_fire_avgfire0",)
MAP_ANCHOR_PREFIX = "HOMM3_anim_anchor_"
LANES = ("map_building", "battle_skinned", "battle_emission", "battle_body_displacement", "battle_body_overlay")
VS_ORIENTS = ("bone", "emitUp", "body")
TRIGGER_MODES = ("always", "animator_state", "animator_window")
SOCKET_KINDS = ("meshBounds", "bones")


def fail(msg: str) -> None:
    print(f"homm3-mesh-fx-catalog-contract: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_native_res_path(row_id: str, native: str, witness: dict) -> None:
    """nativeResPath is handed verbatim to ResManager.Get<GameObject> (bundles, then Resources.Load).

    Canonical form is the exact ResourceManager container key: root folder included (objects/fx/..., units/...,
    magic/prefabs_vfx/...), ASCII-lowercased as Unity stores it, no extension, no leading/trailing slash. A Core DB
    short name such as fx/fx_map_fire is not a Resources key and loads nothing.
    """
    require(native == native.strip(), f"{row_id}: nativeResPath has surrounding whitespace")
    require(native == native.lower(),
            f"{row_id}: nativeResPath {native!r} is not canonical: container keys are lowercase "
            f"({native.lower()!r})")
    require(not native.startswith("/") and not native.endswith("/") and "\\" not in native
            and not native.startswith("assets/")
            and not native.rsplit("/", 1)[-1].endswith(ASSET_EXTENSIONS),
            f"{row_id}: nativeResPath {native!r} must be a Resources-relative key without extension")
    require(native in witness,
            f"{row_id}: nativeResPath {native!r} is not a ResourceManager container key in "
            f"{KEYS_WITNESS.relative_to(ROOT).as_posix()} (rerun `python tools/homm3_vfx/vanilla_vfx_probe.py "
            "keys --catalog`; it names the canonical key when only the spelling is wrong)")


def load_keys_witness() -> dict:
    require(KEYS_WITNESS.is_file(), f"missing {KEYS_WITNESS.relative_to(ROOT).as_posix()}")
    w = json.loads(KEYS_WITNESS.read_text(encoding="utf-8"))
    require(w.get("schema") == KEYS_SCHEMA, f"{KEYS_WITNESS.name}: schema {w.get('schema')!r} != {KEYS_SCHEMA}")
    keys = w.get("keys")
    require(isinstance(keys, dict) and keys and all(isinstance(v, list) and v for v in keys.values()),
            f"{KEYS_WITNESS.name}: keys must map each witnessed path to its container PathIDs")
    return keys


def check_emission_row(row_id: str, row: dict) -> None:
    """Hex/Lit emission-map layer: body glow, never a light (tools/homm3_vfx/vanilla_style_fx.py)."""
    sids = (row.get("match") or {}).get("unitSids")
    require(isinstance(sids, list) and sids and all(isinstance(x, str) and x for x in sids),
            f"{row_id}: battle_emission match needs unitSids")
    require("source" not in row and "socket" not in row and "trigger" not in row,
            f"{row_id}: battle_emission carries only an emission block")
    em = row.get("emission")
    require(isinstance(em, dict), f"{row_id}: battle_emission needs an emission object")
    tex = em.get("texture") or ""
    require(isinstance(tex, str) and tex.startswith("emission/") and tex.endswith(".png") and ".." not in tex,
            f"{row_id}: emission.texture must be emission/<file>.png")
    require((PLUGIN_FX_ROOT / tex).is_file(), f"{row_id}: emission texture missing: {tex}")
    col = em.get("color")
    require(isinstance(col, list) and len(col) == 3 and all(is_num(c) and c >= 0 for c in col),
            f"{row_id}: emission.color must be three HDR values >= 0")
    for k in ("minPower", "blinkPower", "blinkSpeed"):
        require(is_num(em.get(k)) and em[k] >= 0, f"{row_id}: emission.{k} must be >= 0")
    digest = em.get("textureSha256")
    require(isinstance(digest, str) and len(digest) == 64, f"{row_id}: emission.textureSha256 missing")
    import hashlib
    require(hashlib.sha256((PLUGIN_FX_ROOT / tex).read_bytes()).hexdigest() == digest,
            f"{row_id}: emission texture sha differs from the catalog (recompile)")


def check_displacement_row(row_id: str, row: dict) -> None:
    """Hex/Lit FLAG vertex displacement of the owned body, masked by the delivered mesh's baked COLOR_0.r."""
    sids = (row.get("match") or {}).get("unitSids")
    require(isinstance(sids, list) and sids and all(isinstance(x, str) and x for x in sids),
            f"{row_id}: battle_body_displacement match needs unitSids")
    require(set(row) <= {"id", "lane", "origin", "match", "displacement", "proof"},
            f"{row_id}: battle_body_displacement carries only a displacement block")
    d = row.get("displacement")
    require(isinstance(d, dict) and d.get("mode") == "flag", f"{row_id}: displacement.mode must be 'flag'")
    for k in ("direction", "power"):
        v = d.get(k)
        require(isinstance(v, list) and len(v) == 3 and all(is_num(c) for c in v), f"{row_id}: displacement.{k} is [x, y, z]")
    require(any(c != 0 for c in d["power"]), f"{row_id}: displacement.power must be non-zero")
    require(is_num(d.get("speed")), f"{row_id}: displacement.speed must be a number")
    digest = d.get("maskGlbSha256")
    require(isinstance(digest, str) and len(digest) == 64,
            f"{row_id}: displacement.maskGlbSha256 names the COLOR_0-baked GLB the unit must ship")


def check_overlay_row(row_id: str, row: dict, witness: dict) -> None:
    """A vanilla prefab renderer's material appended to the owned body SMR (always or on an animator window)."""
    sids = (row.get("match") or {}).get("unitSids")
    require(isinstance(sids, list) and sids and all(isinstance(x, str) and x for x in sids),
            f"{row_id}: battle_body_overlay match needs unitSids")
    src = row.get("source") or {}
    require(set(src) in ({"nativeResPath", "rendererPath", "materialIndex"}, {"nativeResPath", "rendererPath", "materialIndex", "colors"}),
            f"{row_id}: overlay source is exactly nativeResPath, rendererPath, materialIndex (+ optional colors)")
    if "colors" in src:
        # tint of the native material's own colour properties (vanilla_style_fx.check_overlay_tint picks them per
        # shader; Homm3MeshFx.TryReadOverlayTint requires each to exist on the material and read back)
        colors = src["colors"]
        require(isinstance(colors, list) and colors, f"{row_id}: overlay colors must be a non-empty list")
        props = [c.get("property") for c in colors if isinstance(c, dict)]
        require(len(props) == len(colors) and len(set(props)) == len(props),
                f"{row_id}: overlay colors are distinct {{property, rgba}} entries")
        for i, c in enumerate(colors):
            rgba = c.get("rgba")
            require(set(c) == {"property", "rgba"} and isinstance(c["property"], str) and c["property"].startswith("_"),
                    f"{row_id}: overlay colors[{i}] is exactly {{property: '_Name', rgba}}")
            require(isinstance(rgba, list) and len(rgba) == 4 and all(is_num(v) and 0 <= v <= 16 for v in rgba),
                    f"{row_id}: overlay colors[{i}].rgba is four numbers in [0, 16]")
    check_native_res_path(row_id, src["nativeResPath"], witness)
    require(isinstance(src["rendererPath"], str), f"{row_id}: overlay rendererPath must be a string ('' = root)")
    require(isinstance(src["materialIndex"], int) and not isinstance(src["materialIndex"], bool) and src["materialIndex"] >= 0,
            f"{row_id}: overlay materialIndex must be an int >= 0")
    trig = row.get("trigger") or {}
    require(trig.get("mode") in ("always", "animator_window"), f"{row_id}: overlay triggers are always or animator_window")
    if trig["mode"] == "animator_window":
        states, win = trig.get("states"), trig.get("normalizedTime")
        require(isinstance(states, list) and states and all(isinstance(x, str) and x for x in states),
                f"{row_id}: overlay animator_window needs states")
        require(isinstance(win, list) and len(win) == 2 and all(is_num(v) for v in win) and 0 <= win[0] < win[1] <= 1,
                f"{row_id}: overlay normalizedTime is [start, end] in 0..1")


def check_vanilla_style(row_id: str, row: dict) -> None:
    """Vanilla particle-prefab reuse layer: a bare Shuriken subtree of a native prefab, under a bone."""
    vs = row["vanillaStyle"]
    lane = row.get("lane")
    require(lane in ("battle_skinned", "map_building"), f"{row_id}: vanillaStyle rows are battle_skinned or map_building")
    if lane == "map_building":
        # Map-building effects: vanilla map-object systems on an anchor empty baked into the building mesh
        # (tools/homm3_map_building_meshes/map_building_fx.py), always on, native orientation from the anchor.
        sock = row.get("socket") or {}
        names = sock.get("names") or []
        require(sock.get("kind") == "bones" and len(names) == 1 and str(names[0]).startswith(MAP_ANCHOR_PREFIX),
                f"{row_id}: a map_building vanillaStyle row sits on one {MAP_ANCHOR_PREFIX}* anchor")
        require((row.get("origin") or "").startswith("map_building_fx:"),
                f"{row_id}: map_building vanillaStyle rows are compiled by map_building_fx.py")
        require(vs.get("orient") == "bone", f"{row_id}: map_building vanillaStyle keeps the anchor orientation")
        require((row.get("trigger") or {}).get("mode") == "always", f"{row_id}: map_building effects are always on")
    require((row.get("source") or {}).get("nativeResPath"), f"{row_id}: vanillaStyle needs source.nativeResPath")
    require(isinstance(vs.get("childPath"), str) and vs["childPath"], f"{row_id}: vanillaStyle.childPath missing")
    keep = vs.get("keepNodes")
    require(isinstance(keep, list) and keep and all(isinstance(k, str) for k in keep),
            f"{row_id}: vanillaStyle.keepNodes must list the emitting systems")
    require(is_num(vs.get("worldScale")) and 0 < vs["worldScale"] <= 4, f"{row_id}: vanillaStyle.worldScale in (0, 4]")
    require(is_num(vs.get("rateMul")) and vs["rateMul"] > 0, f"{row_id}: vanillaStyle.rateMul > 0")
    require(vs.get("orient") in VS_ORIENTS, f"{row_id}: vanillaStyle.orient not in {VS_ORIENTS}")
    require(is_num(vs.get("bodyYawDeg")), f"{row_id}: vanillaStyle.bodyYawDeg must be a number")
    require(isinstance(vs.get("loop"), bool) and isinstance(vs.get("zeroChildPositions"), bool),
            f"{row_id}: vanillaStyle.loop/zeroChildPositions must be booleans")
    anchor = vs.get("anchorNode")
    require(isinstance(anchor, str), f"{row_id}: vanillaStyle.anchorNode must be a string ('' = none)")
    require(vs.get("endBehaviour") == "stopEmitting", f"{row_id}: a vanilla-style window ends by stopEmitting")
    local = vs.get("localScaleNodes")
    require(isinstance(local, list) and all(k in keep for k in local),
            f"{row_id}: vanillaStyle.localScaleNodes must be a subset of keepNodes")
    rec = vs.get("recolorNodes")
    require(isinstance(rec, list), f"{row_id}: vanillaStyle.recolorNodes must be a list")
    for r in rec:
        require(isinstance(r, dict) and r.get("node") in keep, f"{row_id}: recolorNodes entry names a kept node")
        mul = r.get("materialColorMul")
        require(isinstance(mul, list) and len(mul) == 3 and all(is_num(c) and c >= 0 for c in mul),
                f"{row_id}: recolorNodes.materialColorMul must be three values >= 0")
        g = r.get("gradient")
        if g is not None:
            for part, width in (("color", 4), ("alpha", 2)):
                keys = g.get(part)
                require(isinstance(keys, list) and 1 <= len(keys) <= 8
                        and all(isinstance(k, list) and len(k) == width and all(is_num(v) for v in k) for k in keys),
                        f"{row_id}: recolour gradient {part} keys malformed (1..8 keys)")
                require(all(0 <= v <= 1 for k in keys for v in k), f"{row_id}: recolour gradient values must be 0..1")
    rot = vs.get("boneLocalRot")
    if rot is not None:
        require(vs.get("orient") in ("bone", "emitUp"), f"{row_id}: vanillaStyle.boneLocalRot needs orient bone or emitUp")
        require(isinstance(rot, list) and len(rot) == 4 and all(is_num(c) for c in rot)
                and abs(sum(c * c for c in rot) - 1) < 2e-3, f"{row_id}: vanillaStyle.boneLocalRot must be a unit quaternion")
    mode = (row.get("trigger") or {}).get("mode")
    require(mode in ("always", "animator_window"), f"{row_id}: vanillaStyle triggers are always or animator_window")
    require(mode != "always" or vs["loop"], f"{row_id}: an always-on vanilla-style effect must loop")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = ap.parse_args()
    cat_path: Path = args.catalog if args.catalog.is_absolute() else ROOT / args.catalog
    require(cat_path.is_file(), f"catalog missing: {cat_path}")
    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    require(catalog.get("schema") == SCHEMA, f"bad catalog schema: {catalog.get('schema')}")
    entries = catalog.get("entries")
    require(isinstance(entries, list) and entries, "catalog has no entries")

    witness = load_keys_witness()
    ids: list[str] = []
    for i, row in enumerate(entries):
        require(isinstance(row, dict), f"entries[{i}] is not an object")
        row_id = (row.get("id") or "").strip()
        require(row_id, f"entries[{i}] missing id")
        require(row_id not in ids, f"duplicate id: {row_id}")
        ids.append(row_id)
        lane = (row.get("lane") or "").strip()
        require(lane in LANES, f"{row_id}: unknown lane {lane!r}")
        match = row.get("match")
        require(isinstance(match, dict), f"{row_id}: match must be an object")
        if lane == "battle_emission":
            check_emission_row(row_id, row)
            continue
        if lane == "battle_body_displacement":
            check_displacement_row(row_id, row)
            continue
        if lane == "battle_body_overlay":
            check_overlay_row(row_id, row, witness)
            continue
        if row.get("vanillaStyle") is not None:
            check_vanilla_style(row_id, row)
        source = row.get("source")
        require(isinstance(source, dict), f"{row_id}: source must be an object")
        native = (source.get("nativeResPath") or "").strip()
        owned = (source.get("ownedPrefabKey") or "").strip()
        map_particles = source.get("mapObjectParticles") is True
        source_count = int(bool(native)) + int(bool(owned)) + int(map_particles)
        require(
            source_count == 1,
            f"{row_id}: source must be exactly one of nativeResPath, ownedPrefabKey, or mapObjectParticles",
        )
        if native:
            check_native_res_path(row_id, native, witness)
        if owned:
            owned_path = PLUGIN_FX_ROOT / "owned" / owned
            require(
                owned_path.is_file(),
                f"{row_id}: ownedPrefabKey file missing: {owned_path}",
            )
        if lane == "map_building":
            if native:
                require(
                    native.startswith("objects/") and "prefabs_vfx" not in native.lower(),
                    f"{row_id}: map_building nativeResPath must be a Core map-object prefab (objects/…), not combat prefabs_vfx",
                )
            require(
                not map_particles or not native,
                f"{row_id}: map_building cannot combine mapObjectParticles with nativeResPath",
            )
        if lane == "battle_skinned":
            require(
                not map_particles,
                f"{row_id}: mapObjectParticles is map_building only",
            )
        socket = row.get("socket")
        require(isinstance(socket, dict), f"{row_id}: socket must be an object")
        kind = (socket.get("kind") or "").strip()
        require(kind in SOCKET_KINDS, f"{row_id}: unknown socket.kind {kind!r}")
        if kind == "bones":
            names = socket.get("names")
            require(
                isinstance(names, list) and all(isinstance(n, str) and n.strip() for n in names),
                f"{row_id}: bones socket needs a non-empty names list",
            )
        trigger = row.get("trigger")
        require(isinstance(trigger, dict), f"{row_id}: trigger must be an object")
        mode = (trigger.get("mode") or "").strip()
        require(mode in TRIGGER_MODES, f"{row_id}: unknown trigger.mode {mode!r}")
        if mode in ("animator_state", "animator_window"):
            states = trigger.get("states")
            require(
                isinstance(states, list) and all(isinstance(s, str) and s.strip() for s in states),
                f"{row_id}: animator trigger needs a non-empty states list",
            )
        if mode == "animator_window":
            window = trigger.get("normalizedTime")
            require(
                isinstance(window, list) and len(window) == 2,
                f"{row_id}: animator_window needs normalizedTime [start, end]",
            )

    fx_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3MeshFx.cs"
    )
    require(fx_cs.is_file(), f"missing Homm3MeshFx.cs: {fx_cs}")
    fx_src = fx_cs.read_text(encoding="utf-8")
    require(
        "TryGetCachedNativeResManagerGameObject" in fx_src,
        "Homm3MeshFx attach must resolve a cached ResManager GameObject when the game already loaded it",
    )
    require(
        "TryLoadNativeResManagerGameObjectIl2Cpp" in fx_src,
        "Homm3MeshFx LateUpdate must load native prefs via Il2Cpp runtime invoke",
    )
    require(
        "TryLoadNativeResManagerGameObject(" not in fx_src,
        "Homm3MeshFx must not MethodInfo.Invoke ResManager.Get (Golden Era AV from LateUpdate, MapObject.Init, and ScMainMenu.Start)",
    )
    require(
        "TryLoadResManagerGameObject" not in fx_src,
        "Homm3MeshFx must not call TryLoadResManagerGameObject",
    )
    require(
        "TryPreloadMapLaneNativeSources" not in fx_src,
        "Homm3MeshFx must not preload via ResManager.Get at the main menu",
    )
    attach_start = fx_src.find("private static void AttachRows(")
    require(attach_start >= 0, "Homm3MeshFx.AttachRows missing")
    attach_end = fx_src.find("\n\tinternal static void Unregister(", attach_start)
    require(attach_end > attach_start, "Homm3MeshFx.AttachRows body bounds missing")
    attach_src = fx_src[attach_start:attach_end]
    require(
        "allowIl2CppNativeLoad: false" in attach_src,
        "Homm3MeshFx.AttachRows (MapObject.Init / ecd.Init) must stay cache-only",
    )
    require(
        "TryLoadNativeResManagerGameObjectIl2Cpp" not in attach_src,
        "Homm3MeshFx.AttachRows must not Il2Cpp-Get during Init",
    )
    tick_start = fx_src.find("internal static void Tick(")
    require(tick_start >= 0, "Homm3MeshFx.Tick missing")
    tick_end = fx_src.find("\n\tprivate static bool EnsureInstance(", tick_start)
    require(tick_end > tick_start, "Homm3MeshFx.Tick body bounds missing")
    tick_src = fx_src[tick_start:tick_end]
    require(
        "allowIl2CppNativeLoad: true" in tick_src,
        "Homm3MeshFx.Tick/TickSlot must allow Il2Cpp Get from LateUpdate",
    )
    require(
        "TryLoadNativeResManagerGameObject(" not in tick_src,
        "Homm3MeshFx.Tick must not MethodInfo.Invoke ResManager.Get",
    )
    import_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3ImportVisuals.cs"
    )
    require(import_cs.is_file(), f"missing Homm3ImportVisuals.cs: {import_cs}")
    import_src = import_cs.read_text(encoding="utf-8")
    rebind_start = import_src.find("internal static bool EnsureSkinnedBattleRuntimeCompatibility(")
    rebind_end = import_src.find("\n\t// Visibility reference:", rebind_start)
    require(rebind_start >= 0 and rebind_end > rebind_start,
            "owned-skinned Hex/Lit rebind source bounds missing")
    rebind_src = import_src[rebind_start:rebind_end]
    require(
        "Homm3MeshFx.TryApplyBodyDisplacement(fallback, skin, entry, lane, log);" in rebind_src
        and "VerifyOwnedSkinnedHexLitVisibleState(instance, entry, lane, log);" in rebind_src,
        "owned-skinned rebind must apply displacement before running its visibility check",
    )
    require(
        rebind_src.find("Homm3MeshFx.TryApplyBodyDisplacement(fallback, skin, entry, lane, log);")
        < rebind_src.find("VerifyOwnedSkinnedHexLitVisibleState(instance, entry, lane, log);"),
        "owned-skinned visibility check must run after body displacement application",
    )
    visibility_start = import_src.find("private static void VerifyOwnedSkinnedHexLitVisibleState(")
    visibility_end = import_src.find("\n\tprivate static void RequireFloat(", visibility_start)
    require(visibility_start >= 0 and visibility_end > visibility_start,
            "owned-skinned Hex/Lit visibility check source bounds missing")
    visibility_src = import_src[visibility_start:visibility_end]
    require(
        "string.Equals(keyword, Homm3MeshFx.FlagDisplacementKeyword, StringComparison.Ordinal)" in visibility_src
        and "Homm3MeshFx.IsExpectedBodyDisplacementApplied(m, skin, entry, lane)" in visibility_src
        and 'mismatches.Add(where + "keyword " + keyword + " enabled")' in visibility_src,
        "visibility check must use the shared row/readback verifier for FLAG displacement and keep other forbidden keywords as errors",
    )
    forbidden_start = import_src.find("private static readonly string[] OwnedSkinnedHexLitForbiddenKeywords")
    forbidden_end = import_src.find("\n\t};", forbidden_start)
    require(forbidden_start >= 0 and forbidden_end > forbidden_start,
            "owned-skinned forbidden keyword list source bounds missing")
    forbidden_src = import_src[forbidden_start:forbidden_end]
    require(
        '"HEX_VERTEX_DISPLACEMENT_FLAG"' in forbidden_src
        and '"HEX_VERTEX_DISPLACEMENT_TREE"' in forbidden_src,
        "visibility check must continue to reject unsanctioned FLAG and TREE displacement keywords",
    )
    require(
        "TryLoadNativeResManagerGameObjectIl2Cpp" in import_src,
        "Homm3ImportVisuals must expose Il2Cpp runtime invoke Get for mesh FX",
    )
    require(
        "ResManagerStaticGetGenericStore" in import_src,
        "Il2Cpp Get must use the inflated public static ResManager.Get<GameObject> MethodInfoStore Pointer, not MethodInfo.Invoke",
    )
    require(
        "ResManagerObjectLoaderGenericStore" not in import_src
        and "MethodInfoStoreGeneric_Method_Private_Object_String_0" not in import_src,
        "Il2Cpp Get must not invoke the private bundle-only loader (GetAssetFromBundle): Golden Era ships vanilla "
        "prefabs in resources.assets, so it returns null for every one",
    )
    row_verifier_start = fx_src.find("private static bool TryFindUniqueBodyDisplacementRow(")
    displacement_start = fx_src.find("internal static void TryApplyBodyDisplacement(")
    displacement_end = fx_src.find("\n\t// ------------------------------------------------------------------ vanilla body-overlay material layer", displacement_start)
    require(row_verifier_start >= 0 and displacement_start > row_verifier_start and displacement_end > displacement_start,
            "body displacement verifier/applicator source bounds missing")
    row_verifier_src = fx_src[row_verifier_start:displacement_start]
    displacement_src = fx_src[displacement_start:displacement_end]
    require(
        "candidate.Lane, LaneBattleBodyDisplacement" in row_verifier_src
        and "SidListIntersects(candidate.UnitSids, sids)" in row_verifier_src
        and "duplicateRow = candidate;" in row_verifier_src
        and 'string.Equals(lane, "battle", StringComparison.Ordinal)' in row_verifier_src
        and 'string.Equals(lane, "adventure-map", StringComparison.Ordinal)' in row_verifier_src
        and "TryFindUniqueBodyDisplacementRow(entry, out var row, out _, out _)" in row_verifier_src
        and "IsExpectedBodyDisplacementMaterialState(material, skin, row)" in row_verifier_src
        and '"_VertexDisplacementType", "_FlagDirection", "_FlagPower", "_FlagSpeed"' in row_verifier_src
        and "Mathf.Abs(readType - FlagDisplacementType) <= 1e-4f" in row_verifier_src
        and "(readDirection - d.Direction).sqrMagnitude <= 1e-10f" in row_verifier_src
        and "(readPower - d.Power).sqrMagnitude <= 1e-10f" in row_verifier_src
        and "Mathf.Abs(readSpeed - d.Speed) <= 1e-4f" in row_verifier_src
        and "!MaterialHasKeyword(material, TreeDisplacementKeyword)" in row_verifier_src
        and "VertexAttribute.Color" in displacement_src
        and "material.EnableKeyword(FlagDisplacementKeyword);" in displacement_src
        and "IsExpectedBodyDisplacementMaterialState(material, skin, row)" in displacement_src
        and "var readDirection = material.GetVector(\"_FlagDirection\");" in displacement_src
        and "var readPower = material.GetVector(\"_FlagPower\");" in displacement_src
        and "var readSpeed = material.GetFloat(\"_FlagSpeed\");" in displacement_src
        and "return true;" not in displacement_src,
        "FLAG exemption requires an idempotent exact-row verifier and fail-closed COLOR_0/property/keyword readback (<= comparisons reject NaN)",
    )
    symbols_src = (
        ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"
    ).read_text(encoding="utf-8")
    require(
        re.search(r'ResManagerStaticGetGenericStore\s*=\s*"MethodInfoStoreGeneric_Method_Public_Static_a_String_0`1"',
                  symbols_src) is not None,
        "GameSymbols.ImportVisuals.ResManagerStaticGetGenericStore must name the static Get<T> store",
    )
    plugin_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Plugin.cs"
    )
    require(plugin_cs.is_file(), f"missing Plugin.cs: {plugin_cs}")
    plugin_src = plugin_cs.read_text(encoding="utf-8")
    require(
        "Homm3MeshFx.TryPreloadMapLaneNativeSources" not in plugin_src,
        "main menu must not call Homm3MeshFx.TryPreloadMapLaneNativeSources",
    )

    for required in REQUIRED_IDS:
        require(required in ids, f"missing required proof row id: {required}")

    for gone in SUPERSEDED_IDS:
        require(gone not in ids, f"superseded map row {gone} is back (map_building_fx.py compile drops it)")
    fire = next(r for r in entries if r.get("id") == MAP_PROOF_ID)
    require(fire.get("lane") == "map_building", "avgfire0 fire row must be map_building")
    require(
        "avgfire0" in ((fire.get("match") or {}).get("prefabKeyContains") or "").lower(),
        "avgfire0 fire row must match avgfire0",
    )
    require(fire.get("vanillaStyle") is not None, "avgfire0 fire row must be a vanillaStyle row")
    require(
        ((fire.get("source") or {}).get("nativeResPath") or "").startswith("objects/"),
        "avgfire0 fire row must clone a Core map-object prefab",
    )

    crusader = next(r for r in entries if r.get("id") == "crusader_attack_sparks")
    require(crusader.get("lane") == "battle_skinned", "crusader row must be battle_skinned")
    unit_sids = (crusader.get("match") or {}).get("unitSids") or []
    require("h3_swordsman_upg" in unit_sids, "crusader row must match h3_swordsman_upg")
    require("h3_crusader" in unit_sids, "crusader row must match h3_crusader")
    names = (crusader.get("socket") or {}).get("names") or []
    require(
        isinstance(names, list) and names and names[0] == "RightWeaponTip",
        "crusader socket list must start from RightWeaponTip",
    )
    trigger = crusader.get("trigger") or {}
    require(trigger.get("mode") == "animator_window", "crusader row must be animator_window")
    require("14.Attack" in (trigger.get("states") or []), "crusader row must gate on 14.Attack")

    print(
        json.dumps(
            {
                "ok": True,
                "catalogEntries": len(ids),
                "ids": ids,
                "proof": "source/static — catalog shape only; in-map/in-combat look unproven",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
