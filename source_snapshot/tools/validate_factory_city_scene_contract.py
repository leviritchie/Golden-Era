#!/usr/bin/env python3
"""Fail-closed contract for Factory cityFactory Castle-parity slot names.

Validates GameSymbols.FactoryCityScene.ExpectedSceneSlotNames in source and the
pinned vanilla ledger table stay aligned (20 slots). Does not claim runtime load.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_SYMBOLS = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"
VANILLA_LEDGER = ROOT / "docs" / "vanilla_town_scene_graph_ledger.md"
PINS_DOC = ROOT / "docs" / "factory_city_scene_load_pins.md"
BREAKAGE_CATALOG = ROOT / "docs" / "factory_city_scene_runtime_pilot_breakage_catalog.md"
HANDOFF = ROOT / "docs" / "town_unity_scene_replace_handoff.md"
PARADIGM_DOC = ROOT / "docs" / "custom_town_scene_paradigm.md"

EXPECTED = [
    "Main",
    "Tier_1",
    "Tier_2",
    "Tier_3",
    "Tier_4",
    "Tier_5",
    "Tier_6",
    "Tier_7",
    "Artifact_Market",
    "Intelligence_Academy",
    "Golden_Calf",
    "Tavern",
    "Magic_Guild",
    "Training_Range",
    "Treasury",
    "Bank",
    "Market",
    "Walls",
    "Resource_Depot",
    "Resource_Depot_2",
]

EXPECTED_NATIVE_LEVEL_COUNTS = {
    "Build_Main": 3,
    "Build_Wall": 3,
    "Build_Magic_Guild": 4,
    "Build_Artifact_Market": 1,
    "Build_Golden_Calf": 1,
    "Build_Tavern": 1,
    "Build_Treasury": 1,
    "Build_Bank": 1,
    "Build_Market": 1,
    "Build_Resource_Depot": 1,
    "Build_Resource_Depot_level_2": 1,
    **{f"Build_Tier_{i}": 2 for i in range(1, 8)},
}


def _append_peer_generic_native_level_errors(
    errors: list[str],
    *,
    faction_sid: str,
    layers_dir: Path,
    layer_map: dict,
    positions: dict,
    world_code: str,
    require_factory_decorations: bool,
) -> None:
    """Castle-parity checks shared by Factory and Bulwark owned-world peers.

    Does not pin Factory-only Main/Guild art IDs or tbfa* decorations onto Bulwark.
    """
    source_levels = layer_map.get("levels") or {}
    native_levels = layer_map.get("nativeLevels") or {}
    label = "Factory" if faction_sid == "homm3_factory" else faction_sid
    if set(native_levels) != set(EXPECTED_NATIVE_LEVEL_COUNTS):
        errors.append(
            f"{label} nativeLevels SID set drifted from the supported Castle graph: "
            f"{sorted(native_levels)}"
        )
    for sid, expected_count in EXPECTED_NATIVE_LEVEL_COUNTS.items():
        actual = native_levels.get(sid) or {}
        expected_keys = {str(level) for level in range(1, expected_count + 1)}
        if set(actual) != expected_keys:
            errors.append(
                f"{label} {sid} native levels expected {sorted(expected_keys)}, got {sorted(actual)}"
            )
        source_ids = set((source_levels.get(sid) or {}).values())
        for layer_id in actual.values():
            if layer_id not in source_ids:
                errors.append(
                    f"{label} {sid} native layer {layer_id!r} is absent from source levels"
                )
    rows = positions.get("layers") or []
    order = [(row.get("z"), row.get("order")) for row in rows]
    if order != sorted(order):
        errors.append(f"{label} positions layers must remain sorted by (z, order)")
    if require_factory_decorations:
        ids = {row.get("id") for row in rows}
        for decoration in ("tbfaext1", "tbfaext2", "tbfaext3"):
            if decoration not in ids:
                errors.append(f"Factory positions missing decoration layer {decoration}")
    mapped_ids = {
        layer_id
        for levels in native_levels.values()
        for layer_id in (levels or {}).values()
    }
    by_id = {row.get("id"): row for row in rows}
    for layer_id in mapped_ids:
        row = by_id.get(layer_id) or {}
        if any(row.get(key) is None for key in ("reference_x", "reference_y", "reference_w", "reference_h")):
            errors.append(f"{label} mapped layer {layer_id} lacks prebaked reference rect")
        if not (layers_dir / f"{layer_id}.png").is_file():
            errors.append(f"{label} mapped layer {layer_id} has no PNG")
    slot_block = re.search(
        r"BuildingSidBySceneSlot\s*=.*?\{(?P<body>.*?)\n\t\t\};", world_code, re.S
    )
    if not slot_block:
        errors.append("Factory C# sceneSlot-to-SID map is missing")
    else:
        csharp_sids = set(re.findall(r'\["[^"]+"\]\s*=\s*"([^"]+)"', slot_block.group("body")))
        if csharp_sids != set(native_levels):
            errors.append(
                f"{label} C# sceneSlot SIDs drifted from nativeLevels: "
                f"C#={sorted(csharp_sids)} JSON={sorted(native_levels)}"
            )


def _strip_csharp_comments(text: str) -> str:
    """Remove // and /* */ comments so agent-warning comments may name forbidden tokens."""
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*?$", "", without_block, flags=re.M)


def extract_expected_from_gamesymbols(text: str) -> list[str]:
    block = re.search(
        r"ExpectedSceneSlotNames\s*=\s*\{(?P<body>.*?)\};",
        text,
        re.S,
    )
    if not block:
        raise SystemExit("GameSymbols.FactoryCityScene.ExpectedSceneSlotNames block missing")
    return re.findall(r'"([^"]+)"', block.group("body"))


def extract_ledger_slots(text: str) -> list[str]:
    # Rows like: | 0 | `Main` | 3 |
    slots = re.findall(r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|", text)
    if len(slots) < 20:
        raise SystemExit(f"vanilla ledger sceneSlot rows expected >=20, got {len(slots)}")
    return slots[:20]


def main() -> int:
    errors: list[str] = []
    if not GAME_SYMBOLS.is_file():
        errors.append(f"missing {GAME_SYMBOLS}")
    if not VANILLA_LEDGER.is_file():
        errors.append(f"missing {VANILLA_LEDGER}")
    if not PINS_DOC.is_file():
        errors.append(f"missing pins doc {PINS_DOC}")
    if not BREAKAGE_CATALOG.is_file():
        errors.append(f"missing Phase 4 breakage catalog {BREAKAGE_CATALOG}")
    else:
        catalog = BREAKAGE_CATALOG.read_text(encoding="utf-8")
        for required in (
            "activeScene='cityFactory'",
            "LoadScene'd root",
            "EnsureOwnedCityPresentationActive",
            "BhBuilding",
            "Phase 5",
            "Build_Factory_Gantry",
            "Build_Mother_Nature",
            "Build_Intelligence_Academy",
            "Build_Training_Range",
            "Build_Golden_Calf",
            "IL2CPP Newtonsoft",
            "SolidColor black camera",
            "IsReleaseTownPanelVisuallyOpen",
            "custom_town_scene_paradigm",
        ):
            if required not in catalog:
                errors.append(f"breakage catalog missing required token {required!r}")
    if not HANDOFF.is_file():
        errors.append(f"missing handoff {HANDOFF}")
    if not PARADIGM_DOC.is_file():
        errors.append(f"missing preferred town paradigm doc {PARADIGM_DOC}")
    else:
        paradigm = PARADIGM_DOC.read_text(encoding="utf-8")
        for required in (
            "preferred product path",
            "cityFactory",
            "BhBuilding",
            "TryOpenOwnedCityHallConstructionMenu",
            "IsReleaseTownPanelVisuallyOpen",
            "ShouldSkipRouteATownPanelLift",
            "Route A",
        ):
            if required not in paradigm:
                errors.append(f"paradigm doc missing required token {required!r}")
    if errors:
        print("FAIL: " + "; ".join(errors))
        return 1

    symbols_slots = extract_expected_from_gamesymbols(GAME_SYMBOLS.read_text(encoding="utf-8"))
    ledger_slots = extract_ledger_slots(VANILLA_LEDGER.read_text(encoding="utf-8"))

    if symbols_slots != EXPECTED:
        errors.append(f"GameSymbols slots drift from validator EXPECTED: {symbols_slots}")
    if ledger_slots != EXPECTED:
        errors.append(f"vanilla ledger slots drift from validator EXPECTED: {ledger_slots}")
    if len(EXPECTED) != 20:
        errors.append(f"EXPECTED length {len(EXPECTED)} != 20")

    pins = PINS_DOC.read_text(encoding="utf-8")
    for token in (
        "ObjCityConfig.get_sceneName",
        "ObjectPublicAbstractSealedihESaStjlhxESaStBoUnique",
        "ObjectPublicESScbwBoLibw1GacnESUnique",
        "Hex.Session.Loader",
        "cityGnome",
        "cityFactory",
        "ObjectPublicDi2ESObbwUnique",
        "pin_escene_city_factory",
    ):
        if token not in pins:
            errors.append(f"pins doc missing token {token!r}")

    factory_manifest = ROOT / "custom_factions" / "homm3_factory.json"
    if not factory_manifest.is_file():
        errors.append(f"missing {factory_manifest}")
    else:
        import json

        scaffold = json.loads(factory_manifest.read_text(encoding="utf-8")).get("releaseScaffold") or {}
        if scaffold.get("citySceneName") != "cityFactory":
            errors.append(
                "custom_factions/homm3_factory.json releaseScaffold.citySceneName must be "
                "'cityFactory' (Harmony get_sceneName is an IL2CPP field accessor and does not rewrite)."
            )

    factory_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3FactoryCitySceneRegistrar.cs"
    )
    if not factory_cs.is_file():
        errors.append(f"missing registrar {factory_cs}")
    else:
        registrar = factory_cs.read_text(encoding="utf-8")
        # Comments may name forbidden tokens as agent warnings; gate code only.
        registrar_code = _strip_csharp_comments(registrar)
        # Failed playtest OfflineUnlockMod city_hive experiment (not vanilla Hive faction).
        # Those helpers are not a load-path template Ã¢â‚¬â€ see docs/factory_city_scene_load_pins.md.
        for forbidden in ("TryAliasHiveCityScene", "RegisterHiveCitySceneForSession", "city_hive"):
            if forbidden in registrar_code:
                errors.append(
                    f"registrar must not contain failed playtest city_hive helper token {forbidden!r} "
                    "(vanilla Hive/cityDemon is unrelated; do not treat _decompiled_shipped as load evidence)"
                )
        if "cityDemon" in registrar_code:
            errors.append(
                "registrar must not reference cityDemon (do not alias Factory onto vanilla Hive's city scene)"
            )
        if "PatchObjCityConfigSceneName" in registrar or "PostfixObjCityConfigSceneName" in registrar:
            errors.append(
                "registrar must not Harmony-rewrite ObjCityConfig.get_sceneName; "
                "Core/manifest cityFactory is the ownership path"
            )
        for required in (
            "UnloadScene",
            "LoadSceneAsync",
            "PrefixLoadSceneStringReturningScene",
            "CreateScene_Injected",
            "ManagedSpanWrapper",
            "CreateSceneParameters",
            "MoveGameObjectToScene",
            "EnsureDonorTemplateLoaded",
            "BindFactorySceneIntoDi2OrThrow",
            "allowing native Void",
            "ExpectedSceneSlotNames",
            "ExpectedBhBuildingCount",
            "SetActiveScene",
            "EnsureOwnedCityPresentationActive",
            "EnsureOwnedBuildingManagerRootActive",
            "TryValidateOwnedBuildingLifecycle",
            "QueueFactoryPresentationReconcile",
            "EnsureCityCameraSolidBlack",
            "RequiredPresentationRootNames",
            "activated presentation root",
            "ApplyOwnedFactoryWorldArt",
            "HasLiveOwnedRoots",
            "PrefixEsceneSceneLoad",
            "SessionESceneOrdinal",
        ):
            if required not in registrar:
                errors.append(f"registrar missing required landed behavior token {required!r}")
        world_visuals = (
            ROOT
            / "Heroes of Might & Magic Olden Era Playtest"
            / "OfflineUnlockMod"
            / "Homm3FactoryCityWorldVisuals.cs"
        )
        if not world_visuals.is_file():
            errors.append(f"missing Phase 5 world visuals module {world_visuals}")
        else:
            world_code = world_visuals.read_text(encoding="utf-8")
            world_code_nocomment = _strip_csharp_comments(world_code)
            for token in (
                "ApplyOwnedFactoryWorldArt",
                "ClearOwnedFactoryWorldArt",
                "OfflineUnlockFactoryWorldArt",
                "OfflineUnlockFactoryWorldBackdrop",
                "HideDonorPresentation",
                "OfflineUnlockFactoryWorldPlate",
                "OriginalTerrainStates",
                "ParseRequiredObjectToken",
                "ParseRequiredArrayToken",
                "AlignNativeColliderWithArt",
                "Build_Main",
                "PhysicsRaycaster",
                "activeInHierarchy",
                "JObject.Parse",
                "reference_x",
                "SelectHighestActiveVariantOrThrow",
                "TryResolveExactLayerId",
                "ResolvedBuildingLayer",
                "OriginalRendererStates",
                "OriginalColliderStates",
                "EnsureDecorationLayers",
                "CollectNativeBuildingBoxColliders",
                "DisableNativeBuildingCollidersIfPresent",
                "TryAlignNativeColliderWithArt",
                "SnapshotCollider",
                "result.Insert(0, collider)",
                "if (i > 0)",
                "CalculateArtBoundsInColliderSpace",
                "InverseTransformPoint(art.TransformPoint",
                "catch (Exception applyException)",
                "catch (Exception rollbackException)",
                "nativeLevels",
                "ResolveBuildingLevelOrThrow",
                "only the highest collider active",
            ):
                if token not in world_code:
                    errors.append(f"Homm3FactoryCityWorldVisuals missing required token {token!r}")
            for forbidden_proxy_cast in ("as JObject", "is JObject", "as JArray"):
                if forbidden_proxy_cast in world_code_nocomment:
                    errors.append(
                        f"Factory manifest loader must reparse IL2CPP Newtonsoft tokens; "
                        f"direct proxy cast {forbidden_proxy_cast!r} is forbidden"
                    )
            if ".Value<" in world_code_nocomment:
                errors.append(
                    "Factory manifest loader must not call JToken.Value<T> "
                    "(IL2CPP Newtonsoft TypeInitializationException / NRE); use ToString parse helpers"
                )
            for required_scalar in ("ReadOptionalFloat", "ReadOptionalString", "ReadOptionalInt"):
                if required_scalar not in world_code_nocomment:
                    errors.append(f"Factory proxy-safe scalar reader missing {required_scalar!r}")
            for forbidden_shader in (
                'Shader.Find("UI/Default")',
                'Shader.Find("Unlit/Texture")',
                'Shader.Find("Unlit/Transparent")',
                'Shader.Find("Hex/Lit")',
            ):
                if forbidden_shader in world_code_nocomment:
                    errors.append(
                        f"Factory world art must require one deterministic Golden Era unlit sprite shader; "
                        f"{forbidden_shader!r} is forbidden here"
                    )
            if 'PresentationShaderName = "Sprites/Default"' not in world_code_nocomment and \
                    'PresentationShaderName="Sprites/Default"' not in world_code_nocomment:
                errors.append('Factory world art must pin PresentationShaderName = "Sprites/Default"')
            if "Shader.Find(PresentationShaderName)" not in world_code_nocomment and \
                    "Shader.Find(TransparentShaderName)" not in world_code_nocomment:
                errors.append("Factory world art must require the centralized PresentationShaderName")
            if 'TransparentShaderName = "Unlit/Transparent"' in world_code_nocomment:
                errors.append(
                    "Unlit/Transparent is unavailable on Golden Era; Factory must use Sprites/Default"
                )
            if "LookRotation(cam.forward" in world_code_nocomment or "LookRotation(camera.forward" in world_code_nocomment:
                errors.append(
                    "Factory quads must not use LookRotation(cam.forward); that backface-culls or keyscreens town art"
                )
            if "LookRotation(-cam.forward" not in world_code_nocomment:
                errors.append(
                    "Factory PositionReferenceQuad must use camera-parallel LookRotation(-cam.forward, ...) "
                    "to avoid askew keystone framing"
                )
            if "mirrorX: true" not in world_code_nocomment:
                errors.append(
                    "Factory building art must PositionReferenceQuad(..., mirrorX: true) "
                    "to correct camera-facing sprite handedness"
                )
            if "renderer.material" in world_code_nocomment and "SetFactoryArtTint" in world_code:
                # Fail if hover tint still uses the material instancing accessor.
                tint_idx = world_code.find("SetFactoryArtTint")
                tint_chunk = world_code[tint_idx:tint_idx + 1200] if tint_idx >= 0 else ""
                if "renderer.material" in tint_chunk:
                    errors.append(
                        "Factory SetFactoryArtTint must not use renderer.material "
                        "(clones material and freezes Homm3FactoryCityWorldAnimDriver overlays); "
                        "use MaterialPropertyBlock / sharedMaterial"
                    )
            if "SetPropertyBlock" not in world_code_nocomment or "ArtTintBlock" not in world_code_nocomment:
                errors.append(
                    "Factory hover tint must use MaterialPropertyBlock so anim overlay materials stay owned"
                )
            backdrop_idx = world_code.find("static GameObject EnsureWorldBackdrop")
            if backdrop_idx < 0:
                backdrop_idx = world_code.find("EnsureWorldBackdrop(Scene")
            backdrop_chunk = world_code[backdrop_idx:backdrop_idx + 2500] if backdrop_idx >= 0 else ""
            if "mirrorX: true" not in backdrop_chunk:
                errors.append(
                    "Factory world backdrop must PositionReferenceQuad(..., mirrorX: true) "
                    "to match building camera-facing handedness"
                )
            if "scaleX = -scaleX" in world_code_nocomment:
                errors.append(
                    "Factory must not mirror via negative localScale; use UV-mirrored mesh "
                    "(negative X breaks anim overlay depth and can skew anchors after reparent)"
                )
            if "SharedUnitQuadMesh" not in world_code_nocomment or "mirrorU" not in world_code_nocomment:
                errors.append(
                    "Factory must pin UV-mirrored SharedUnitQuadMesh/BuildUnitQuadMesh for building handedness"
                )
            if "_background_mock_1920x1080.png" not in world_code_nocomment:
                errors.append(
                    "Factory world backdrop must use the Route A 1920x1080 mock plate, "
                    "not the cropped Factory-in-background.png alone"
                )
            if "SetParent(null, worldPositionStays: true)" not in world_code_nocomment:
                errors.append(
                    "Factory building art must unparent before PositionReferenceQuad to prevent shear"
                )
            anim_path = (
                ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
                / "Homm3FactoryCityWorldAnimDriver.cs"
            )
            anim_code = anim_path.read_text(encoding="utf-8") if anim_path.is_file() else ""
            if "Homm3FactoryCityWorldAnimDriver" not in world_code and "Homm3FactoryCityWorldAnimDriver" not in anim_code:
                errors.append("Factory world anim driver Homm3FactoryCityWorldAnimDriver.cs is required")
            if "localPosition = new Vector3(0f, 0f, 0.002f)" not in anim_code.replace(" ", ""):
                # tolerate spacing variants
                if "0.002f" not in anim_code or "localPosition" not in anim_code:
                    errors.append(
                        "Factory anim overlay must sit in front of the base quad "
                        "(local Z +0.002 toward camera)"
                    )
                elif "-0.002f" in anim_code:
                    errors.append(
                        "Factory anim overlay must not use local Z -0.002 (that places it behind the base)"
                    )
            if "private void Update()" not in anim_code:
                errors.append("Factory world anim driver must tick frames from Update()")
            symbols_code = (
                ROOT
                / "Heroes of Might & Magic Olden Era Playtest"
                / "OfflineUnlockMod"
                / "GameSymbols.cs"
            ).read_text(encoding="utf-8")
            if "OwnedCityWorldFactionSids" not in symbols_code:
                errors.append("GameSymbols.FactoryCityScene missing OwnedCityWorldFactionSids")
            if "IsOwnedCityWorldFaction" not in symbols_code:
                errors.append("GameSymbols.FactoryCityScene missing IsOwnedCityWorldFaction")
            if "IsOwnedCityWorldFaction" not in registrar:
                errors.append("registrar OwnsActiveFactoryCityWorld must call IsOwnedCityWorldFaction")
            if 'Path.Combine("homm3_runtime_assets", "town_scene_refs", fraction' not in world_code:
                errors.append("world visuals must Path.Combine town_scene_refs with active fraction")

            if "PostfixBuildingSelect" not in world_code_nocomment:
                errors.append("Factory must tint world art on BhBuilding.Select for hover highlight parity")
            if "RegisterHarmony" not in world_code_nocomment:
                errors.append("Homm3FactoryCityWorldVisuals.RegisterHarmony must expose Select/Deselect hover patches")
            if "GetComponentsInChildren<Component>" in world_code_nocomment:
                errors.append(
                    "HideDonorPresentation must not scan every Component; use Renderer + Terrain Behaviour only"
                )
            for parser_contract in (
                "token.Type != JTokenType.Object",
                "return JObject.Parse(token.ToString());",
                "token.Type != JTokenType.Array",
                "return JArray.Parse(token.ToString());",
            ):
                if parser_contract not in world_code_nocomment:
                    errors.append(f"Factory proxy-safe parser contract missing {parser_contract!r}")
            for render_contract in (
                "CameraClearFlags.SolidColor",
                "camera.backgroundColor = Color.black",
                'string.Equals(il2CppType.FullName, "UnityEngine.Terrain"',
                "OriginalTerrainStates[behaviour] = behaviour.enabled",
                "OriginalTerrainStates.Clear()",
            ):
                combined = registrar_code + world_code_nocomment
                if render_contract not in combined:
                    errors.append(f"Factory deterministic render-domain contract missing {render_contract!r}")
            if "CollectConstructedSidLevelsForTownArt" in world_code_nocomment:
                errors.append(
                    "Homm3FactoryCityWorldVisuals must derive the active level from the native "
                    "BhBuildingsManager-owned variant, not a parallel BuildingData scrape"
                )
            for forbidden in (
                "HideDonorWorldRenderers",
                "EnsureCityCameraSolidBlack",
                "CanvasCityPanel Route A",
                "ExecuteEvents",
                "Homm3TownLayerClickRelay",
                # Forbid calling native pointer APIs as a second click owner; Harmony patch
                # targets use nameof(...) and must not appear as `.OnPointerClick(`.
                ".OnPointerClick(",
                ".OnPointerEnter(",
                ".Select(",
                "CalculateBuildingBoundsBeforeArt",
                "TryResolveLayerId",
                "AddComponent<UnityEngine.BoxCollider>",
                "_lastApplyFrame",
                "CollectConstructedSidLevelsForTownArt",
            ):
                if forbidden in world_code_nocomment:
                    errors.append(
                        f"Homm3FactoryCityWorldVisuals must not contain Route A / parallel-click workaround token {forbidden!r}"
                    )
            # Failed bajs constructed-activation path was live-negative (black screen + load storm).
            if "EnsureConstructedNativeBuildingVariantsActive" in world_code_nocomment:
                errors.append(
                    "Homm3FactoryCityWorldVisuals must not call EnsureConstructedNativeBuildingVariantsActive "
                    "(removed: load storm / type-coerce black screen; native manager owns activation)"
                )
            if "BuildingMutationMethodName" in world_code_nocomment:
                errors.append(
                    "Homm3FactoryCityWorldVisuals must not invoke BuildingMutationMethodName during presentation"
                )
            if "owned-city-main-world-click" not in world_code:
                errors.append(
                    "Main hall world click must open BuildingsConstruction via "
                    "TryOpenOwnedCityHallConstructionMenu (owned-city-main-world-click)"
                )
            for required_fix in (
                "AnchorBuildingTransformToArt(",
                "building.position = art.position",
                "PrefixBuildingPointerClick",
                "TryOpenOwnedCityHallConstructionMenu(",
            ):
                if required_fix not in world_code_nocomment:
                    errors.append(
                        "Factory owned-city presentation missing required fix token "
                        f"{required_fix!r} (construct FX at art; Main hall click via HUD nav)"
                    )
            if "SetActive(true)" in world_code_nocomment or "SetActive(false)" in world_code_nocomment:
                errors.append(
                    "Homm3FactoryCityWorldVisuals must not SetActive BhBuilding variants; "
                    "native manager owns activation"
                )
            resolver = re.search(
                r"private static int ResolveBuildingLevelOrThrow.*?\n\t}", world_code_nocomment, re.S
            )
            if not resolver:
                errors.append("Factory ResolveBuildingLevelOrThrow is missing")
            else:
                body = resolver.group(0)
                if "return 1;" in body:
                    errors.append(
                        "Factory native level parsing must fail closed; implicit level-1 fallback "
                        "(`return 1;`) is forbidden"
                    )
                if "CastleSingleVariantLevel" not in body or "levelsByLevel.Count == 1" not in body:
                    errors.append(
                        "ResolveBuildingLevelOrThrow must accept unsuffixed Castle single-variant "
                        "names (H_build_Tavern) only when nativeLevels count==1 at CastleSingleVariantLevel; "
                        "otherwise multi-level slots throw (live-negative black-screen loop)"
                    )
                if "BuildingLevelSuffix.Match" not in body:
                    errors.append("ResolveBuildingLevelOrThrow must still prefer _Level_N suffixes")
            apply_start = world_code_nocomment.find(
                "internal static void ApplyOwnedFactoryWorldArt()"
            )
            core_start = world_code_nocomment.find(
                "private static void ApplyOwnedFactoryWorldArtOrThrow(", apply_start
            )
            clear_start = world_code_nocomment.find(
                "internal static void ClearOwnedFactoryWorldArt()", core_start
            )
            if apply_start < 0 or core_start < 0 or clear_start < 0:
                errors.append("Factory presentation wrapper/core/rollback methods are incomplete")
            else:
                wrapper = world_code_nocomment[apply_start:core_start]
                core = world_code_nocomment[core_start:clear_start]
                try_idx = wrapper.find("try")
                core_call_idx = wrapper.find("ApplyOwnedFactoryWorldArtOrThrow(")
                catch_idx = wrapper.find("catch (Exception applyException)")
                rollback_idx = wrapper.find("ClearOwnedFactoryWorldArt();", catch_idx)
                if not (0 <= try_idx < core_call_idx < catch_idx < rollback_idx):
                    errors.append(
                        "Factory rollback wrapper must cover the entire preflight/mutation core"
                    )
                for core_token in (
                    "EnsureLayerManifestLoadedOrThrow(",
                    "CollectActiveManagerOwnedBuildings(scene)",
                    "ValidatePresentationAssetsOrThrow(",
                    "EnsureWorldPlate(scene, camera",
                    "HideDonorPresentation(scene);",
                    "TryAlignNativeColliderWithArt",
                ):
                    if core_token not in core:
                        errors.append(
                            f"Factory rollback-covered core missing token {core_token!r}"
                        )
                if "has no native BoxCollider; refusing to add a parallel click owner" in world_code:
                    errors.append(
                        "owned-world compose must not abort when Castle Walls (walls_level_1) "
                        "lack BoxCollider; paint art and skip align instead of black-screen fatal"
                    )
                if "DisableNativeBuildingCollidersOrThrow" in world_code_nocomment:
                    errors.append(
                        "lower cumulative variants may lack BoxColliders; use "
                        "DisableNativeBuildingCollidersIfPresent (no throw)"
                    )

            import json

            town_refs = (
                ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
                / "homm3_runtime_assets" / "town_scene_refs"
            )
            owned_factions = re.findall(
                r'OwnedCityWorldFactionSids\s*=\s*\{(?P<body>.*?)\};',
                (
                    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"
                ).read_text(encoding="utf-8"),
                re.S,
            )
            owned_sids = re.findall(r'"([^"]+)"', owned_factions[0]) if owned_factions else []
            if not owned_sids:
                errors.append("could not parse GameSymbols.FactoryCityScene.OwnedCityWorldFactionSids")
            for faction_sid in owned_sids:
                faction_map = town_refs / faction_sid / "layers" / "building_layer_map.json"
                faction_positions = town_refs / faction_sid / "layers" / "positions.json"
                faction_layers = town_refs / faction_sid / "layers"
                faction_mock = (
                    town_refs / faction_sid / "mockups" / f"{faction_sid}_background_mock_1920x1080.png"
                )
                if not faction_map.is_file():
                    errors.append(f"{faction_sid}: missing building_layer_map.json for owned cityFactory world")
                    continue
                faction_layer_map = json.loads(faction_map.read_text(encoding="utf-8-sig"))
                native_levels = faction_layer_map.get("nativeLevels")
                if not isinstance(native_levels, dict) or not native_levels:
                    errors.append(
                        f"{faction_sid}: building_layer_map.json must include non-empty nativeLevels "
                        "(missing this on install causes black-screen suspend)"
                    )
                else:
                    # Exact HotA join only clips downward to a mapped level <= active.
                    # Missing "1" while higher levels exist black-screens on Village Hall /
                    # base dwellings (Necropolis/Dungeon/Tower/Fortress live-negative).
                    for sid in EXPECTED_NATIVE_LEVEL_COUNTS:
                        actual = native_levels.get(sid) or {}
                        if not isinstance(actual, dict) or not actual:
                            errors.append(f"{faction_sid}: nativeLevels missing {sid}")
                            continue
                        if "1" not in {str(k) for k in actual}:
                            errors.append(
                                f"{faction_sid}: {sid} nativeLevels missing level 1 "
                                "(owned cityFactory cannot present base hall/tier without it)"
                            )
                    # Donor cityHuman2 traits (unsuffixed Tavern, Walls without BoxCollider) are
                    # shared by every owned faction. Per-faction art must still resolve via
                    # positions.json sprite (Tower *.dir.png; Stronghold remaps) or id.png.
                    if faction_positions.is_file():
                        positions_doc = json.loads(faction_positions.read_text(encoding="utf-8-sig"))
                        by_id = {
                            row.get("id"): row
                            for row in (positions_doc.get("layers") or [])
                            if isinstance(row, dict)
                        }
                        mapped_ids = {
                            layer_id
                            for levels in native_levels.values()
                            for layer_id in (levels or {}).values()
                        }
                        for layer_id in sorted(mapped_ids):
                            row = by_id.get(layer_id) or {}
                            sprite = row.get("sprite") or f"{layer_id}.png"
                            if not isinstance(sprite, str) or not sprite.endswith(".png"):
                                errors.append(
                                    f"{faction_sid}: layer {layer_id!r} sprite must be a .png file name"
                                )
                                continue
                            if not (faction_layers / sprite).is_file():
                                errors.append(
                                    f"{faction_sid}: mapped layer {layer_id} missing texture {sprite}"
                                )
                            if any(
                                row.get(key) is None
                                for key in ("reference_x", "reference_y", "reference_w", "reference_h")
                            ):
                                errors.append(
                                    f"{faction_sid}: mapped layer {layer_id} lacks prebaked reference rect"
                                )
                    else:
                        errors.append(f"{faction_sid}: missing positions.json for owned cityFactory world")
                if not faction_mock.is_file():
                    errors.append(f"{faction_sid}: missing 1920 mock backdrop for owned cityFactory world")

            # Donor-class compose fixes must stay faction-agnostic (all 12 share cityHuman2).
            if "homm3_castle" in world_code_nocomment and (
                "ResolveBuildingLevelOrThrow" in world_code_nocomment
            ):
                resolve_body = re.search(
                    r"private static int ResolveBuildingLevelOrThrow.*?\n\t}",
                    world_code_nocomment,
                    re.S,
                )
                if resolve_body and "homm3_castle" in resolve_body.group(0):
                    errors.append(
                        "ResolveBuildingLevelOrThrow must not special-case homm3_castle; "
                        "unsuffixed single-variant names are a shared cityHuman2 donor trait"
                    )
            if "TryAlignNativeColliderWithArt" in world_code_nocomment:
                align_body = re.search(
                    r"private static void TryAlignNativeColliderWithArt.*?\n\t}",
                    world_code_nocomment,
                    re.S,
                )
                if align_body and "homm3_castle" in align_body.group(0):
                    errors.append(
                        "TryAlignNativeColliderWithArt must not special-case homm3_castle; "
                        "Walls without BoxCollider is a shared cityHuman2 donor trait"
                    )

            factory_layers = (
                ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
                / "homm3_runtime_assets" / "town_scene_refs" / "homm3_factory" / "layers"
            )
            layer_map_path = factory_layers / "building_layer_map.json"
            positions_path = factory_layers / "positions.json"
            if not layer_map_path.is_file() or not positions_path.is_file():
                errors.append("Factory compositor requires building_layer_map.json and positions.json")
            else:
                layer_map = json.loads(layer_map_path.read_text(encoding="utf-8-sig"))
                positions = json.loads(positions_path.read_text(encoding="utf-8-sig"))
                source_levels = layer_map.get("levels") or {}
                native_levels = layer_map.get("nativeLevels") or {}
                if source_levels.get("Build_Golden_Calf") != {"1": "tbfaholy"}:
                    errors.append("Factory grail source must map to Build_Golden_Calf level 1 / tbfaholy")
                if native_levels.get("Build_Main") != {
                    "1": "tbfahall", "2": "tbfahal2", "3": "tbfahal3"
                }:
                    errors.append(
                        "Factory Main native levels must explicitly map Village Hall through City Hall"
                    )
                if native_levels.get("Build_Magic_Guild") != {
                    "1": "tbfamage", "2": "tbfamag2", "3": "tbfamag3", "4": "tbfamag4"
                }:
                    errors.append(
                        "Factory Magic Guild native levels must explicitly map the four donor variants"
                    )
                _append_peer_generic_native_level_errors(
                    errors,
                    faction_sid="homm3_factory",
                    layers_dir=factory_layers,
                    layer_map=layer_map,
                    positions=positions,
                    world_code=world_code,
                    require_factory_decorations=True,
                )

            bulwark_layers = (
                ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
                / "homm3_runtime_assets" / "town_scene_refs" / "homm3_bulwark" / "layers"
            )
            bulwark_map_path = bulwark_layers / "building_layer_map.json"
            bulwark_positions_path = bulwark_layers / "positions.json"
            if not bulwark_map_path.is_file() or not bulwark_positions_path.is_file():
                errors.append("Bulwark compositor requires building_layer_map.json and positions.json")
            else:
                _append_peer_generic_native_level_errors(
                    errors,
                    faction_sid="homm3_bulwark",
                    layers_dir=bulwark_layers,
                    layer_map=json.loads(bulwark_map_path.read_text(encoding="utf-8-sig")),
                    positions=json.loads(bulwark_positions_path.read_text(encoding="utf-8-sig")),
                    world_code=world_code,
                    require_factory_decorations=False,
                )

            overlay_py = (
                ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
            ).read_text(encoding="utf-8")
            for token in (
                "OWNED_WORLD_UNBOUND_CASTLE_SLOT_BUILDING_SIDS",
                "strip_unbound_castle_slot_buildings_from_owned_world_city",
                "Build_Intelligence_Academy",
                "Build_Training_Range",
            ):
                if token not in overlay_py:
                    errors.append(
                        f"apply_release_core_overlay.py missing owned-world unbound-slot strip token {token!r}"
                    )
            if overlay_py.count("strip_unbound_castle_slot_buildings_from_owned_world_city(doc, manifest)") < 3:
                errors.append(
                    "owned-world IA/Training strip must run from generic, Castle, and Fortress city normalize paths"
                )
            if "SuspendOwnedCityPresentation" not in registrar:
                errors.append("registrar missing SuspendOwnedCityPresentation (leave-town lighting park)")
            if "cleared stale Factory load request during non-cityFactory session register" not in registrar:
                errors.append(
                    "registrar must clear stale Factory load request on non-cityFactory session register "
                    "(sticky _cloneFailed black-screens the next custom town)"
                )
            if "recovering from sticky cloneFailed" not in registrar:
                errors.append(
                    "EnsureFactoryCityWorldOwned must recover from sticky cloneFailed when cityFactory roots are live"
                )
            if "presentation settle" not in registrar or "_presentationSettleArmed" not in registrar:
                errors.append(
                    "owned city presentation must arm a one-shot settle window (_presentationSettleArmed); "
                    "re-arming settle every Ensure was a live-negative load storm"
                )
            if 'Main (town hall) BhBuilding not yet active and bound' not in registrar:
                errors.append(
                    "TryValidateOwnedBuildingLifecycle must wait for Main (town hall) before composing; "
                    "otherwise first-awake Tier dwellings lock art with donors hidden and no hall"
                )
            if (
                "Homm3FactoryCityWorldVisuals.IsApplied && _presentationSettleFramesLeft == 0" in registrar
                or "Homm3FactoryCityWorldVisuals.IsApplied &&\n\t\t\t_presentationSettleFramesLeft == 0" in registrar
            ):
                errors.append(
                    "EnsureOwnedCityPresentationActive must not blind-return on IsApplied after settle; "
                    "late-activating slots must re-enter Apply (signature-gated) or towns stay incomplete"
                )
            stronghold = (
                ROOT
                / "Heroes of Might & Magic Olden Era Playtest"
                / "OfflineUnlockMod"
                / "Homm3StrongholdTownLayers.cs"
            )
            stronghold_code = stronghold.read_text(encoding="utf-8") if stronghold.is_file() else ""
            stronghold_nocomment = _strip_csharp_comments(stronghold_code)
            # Pin the SyncCurrentCityLayers early-return, not any earlier helper that also
            # mentions OwnsActiveFactoryCityWorld / TryGetCurrentCity.
            sync_method = re.search(
                r"internal\s+static\s+void\s+SyncCurrentCityLayers\s*\(.*?\)\s*\{(?P<body>.*)\n\t\}",
                stronghold_nocomment,
                re.S,
            )
            sync_body = sync_method.group("body") if sync_method is not None else stronghold_nocomment
            factory_gate = re.search(
                r"if\s*\(Homm3FactoryCitySceneRegistrar\.OwnsActiveFactoryCityWorld\(fraction\)\)\s*"
                r"\{(?P<body>.*?)\}",
                sync_body,
                re.S,
            )
            route_a_marker = sync_body.find("musicMs = phase.ElapsedMilliseconds")
            if (
                factory_gate is None
                or "ClearTownLayers();" not in factory_gate.group("body")
                or "return;" not in factory_gate.group("body")
                or route_a_marker < 0
                or factory_gate.start() >= route_a_marker
            ):
                errors.append(
                    "Homm3StrongholdTownLayers must structurally return before Route A for "
                    "Factory cityFactory ownership (native BhBuilding world slice only)"
                )
            if "building overlays via Route A UI layers" in stronghold_code:
                errors.append(
                    "Homm3StrongholdTownLayers must not fall through to Route A UI layers for Factory ownership"
                )
            if "Homm3TownLayerClickRelay" in stronghold_nocomment:
                errors.append("Homm3StrongholdTownLayers must not reference Homm3TownLayerClickRelay")
            click_relay = (
                ROOT
                / "Heroes of Might & Magic Olden Era Playtest"
                / "OfflineUnlockMod"
                / "Homm3TownLayerClickRelay.cs"
            )
            if click_relay.is_file():
                errors.append(
                    "Homm3TownLayerClickRelay.cs must be removed; Factory clicks stay on native BhBuilding colliders"
                )
            plugin_cs = (
                ROOT
                / "Heroes of Might & Magic Olden Era Playtest"
                / "OfflineUnlockMod"
                / "Plugin.cs"
            )
            plugin_text = plugin_cs.read_text(encoding="utf-8") if plugin_cs.is_file() else ""
            if "apply-skip-factory-city-world-ownership" not in plugin_text:
                errors.append(
                    "Plugin.ApplyCustomCityBackdrop must skip UI OfflineUnlockCityBackdrop for Factory "
                    "cityFactory ownership (apply-skip-factory-city-world-ownership)"
                )
            plugin_nocomment = _strip_csharp_comments(plugin_text)
            if 'StartsWith("owned-city"' not in plugin_nocomment:
                errors.append(
                    "AfterReleaseCityConstructionNavigationSelected must skip SyncCurrentCityLayers "
                    "for owned-city hall open sources"
                )
            if "ShouldSkipRouteATownPanelLift" not in plugin_nocomment:
                errors.append(
                    "Plugin must define ShouldSkipRouteATownPanelLift for owned cityFactory "
                    "(no Route A UI panel lift on Unity world path)"
                )
            if "IsReleaseTownPanelVisuallyOpen" not in plugin_nocomment:
                errors.append(
                    "CloseReleaseCityUpgradeSubwindows must gate OnEscapeClick with "
                    "IsReleaseTownPanelVisuallyOpen (idle UPGRADE UNIT PANEL is hierarchy-active "
                    "with Canvas.enabled=false; OnEscapeClick was live-positive hall closer)"
                )
            upgrade_close = re.search(
                r"private static void CloseReleaseCityUpgradeSubwindows\s*\(\s*\)\s*\{(?P<body>.*?)\n\t\}",
                plugin_nocomment,
                re.S,
            )
            if upgrade_close is None:
                errors.append("Plugin missing CloseReleaseCityUpgradeSubwindows")
            elif "IsReleaseTownPanelVisuallyOpen(upgrade)" not in upgrade_close.group("body"):
                errors.append(
                    "CloseReleaseCityUpgradeSubwindows must skip visually closed upgrade panels "
                    "via IsReleaseTownPanelVisuallyOpen(upgrade)"
                )
            for lift_gate_owner in (
                "LiftActiveReleaseTownPanelCanvas",
                "LiftAnyActiveReleaseTownPrimaryPanelCanvas",
                "EnsureNativeTownMenusAboveCustomArt",
                "ReassertCustomTownNativePanelOrdering",
                "ReconcileCustomTownPresentationForNativePanels",
            ):
                method_match = re.search(
                    rf"(?:private|internal)\s+static\s+(?:bool|void)\s+{re.escape(lift_gate_owner)}\s*\([^)]*\)\s*\{{(?P<body>.*?)\n\t\}}",
                    plugin_nocomment,
                    re.S,
                )
                if method_match is None:
                    errors.append(f"Plugin missing liftable method {lift_gate_owner} for owned-city skip pin")
                    continue
                body_head = method_match.group("body")[:1200]
                if "ShouldSkipRouteATownPanelLift()" not in body_head:
                    errors.append(
                        f"Plugin.{lift_gate_owner} must early-return via ShouldSkipRouteATownPanelLift "
                        "for owned cityFactory"
                    )
            for refresh_token in (
                "ApplyCustomCityBackdrop();",
                "apply-skip-factory-city-world-ownership",
                "Homm3StrongholdTownLayers.SyncCurrentCityLayers();",
            ):
                if refresh_token not in plugin_text:
                    errors.append(f"Plugin missing Factory presentation path token {refresh_token!r}")
            # Direct Ensure+Sync double-call was live-negative load debt; Sync owns Ensure once.
            for refresh_token in (
                "PatchNativeBuildingMutation",
                "PostfixNativeBuildingMutation",
                "QueueFactoryPresentationReconcile",
                "Homm3PreviewApplyNextFrame.QueueRequired",
                "Homm3FactoryCityWorldVisuals.ApplyOwnedFactoryWorldArt();",
                "Factory presentation was suspended",
            ):
                if refresh_token not in registrar_code:
                    errors.append(
                        f"registrar missing exact native construction-refresh token {refresh_token!r}"
                    )
            # Presentation readiness re-queues from inside DrainPending while Main is unbound.
            # Drain must snapshot Count — a while(Pending.Count>0) loop freezes LateUpdate.
            preview_path = (
                ROOT
                / "Heroes of Might & Magic Olden Era Playtest"
                / "OfflineUnlockMod"
                / "Homm3PreviewApplyNextFrame.cs"
            )
            preview_code = preview_path.read_text(encoding="utf-8")
            drain_match = re.search(
                r"internal\s+static\s+void\s+DrainPending\s*\(\s*\)\s*\{(?P<body>.*?)\n\t\}",
                preview_code,
                re.S,
            )
            if drain_match is None:
                errors.append("Homm3PreviewApplyNextFrame missing DrainPending")
            else:
                drain_body = drain_match.group("body")
                if "while (Pending.Count > 0)" in drain_body or "while(Pending.Count > 0)" in drain_body:
                    errors.append(
                        "Homm3PreviewApplyNextFrame.DrainPending must not while(Pending.Count>0); "
                        "snapshot Count so readiness requeues wait until the next LateUpdate "
                        "(same-frame spin froze owned cityFactory entry while Main unbound)"
                    )
                if "var scheduled = Pending.Count" not in drain_body and "scheduled = Pending.Count" not in drain_body:
                    errors.append(
                        "Homm3PreviewApplyNextFrame.DrainPending must snapshot Pending.Count "
                        "before dequeuing (factory presentation readiness requeue pin)"
                    )
            if "ClearOwnedFactoryWorldBackdropOnly" in plugin_text and "factoryOwned" in plugin_text:
                # Allow the method to exist on world visuals; Plugin must not clear world backdrop to force UI art.
                factory_block = ""
                idx = plugin_text.find("apply-skip-factory-city-world-ownership")
                if idx >= 0:
                    factory_block = plugin_text[max(0, idx - 800) : idx + 200]
                if "ClearOwnedFactoryWorldBackdropOnly" in factory_block:
                    errors.append(
                        "Plugin Factory ownership path must not ClearOwnedFactoryWorldBackdropOnly "
                        "(world backdrop owns Factory framing)"
                    )
        if '"CityCamera"' not in registrar and '"CityCamera"' not in GAME_SYMBOLS.read_text(encoding="utf-8"):
            errors.append("RequiredPresentationRootNames must include CityCamera (live-positive black-screen fix)")
        symbols_text = GAME_SYMBOLS.read_text(encoding="utf-8")
        if "RequiredPresentationRootNames" not in symbols_text:
            errors.append("GameSymbols.FactoryCityScene missing RequiredPresentationRootNames")
        else:
            for root_name in ("CityCamera", "Lights"):
                if f'"{root_name}"' not in symbols_text.split("RequiredPresentationRootNames", 1)[1].split("};", 1)[0]:
                    errors.append(f"RequiredPresentationRootNames must include {root_name!r}")
        for symbol in (
            "BuildingsManagerTypeName",
            "BuildingTypeName",
            "BuildingBoundLogicPropertyName",
            "field_Private_ObjectPublicBuObcdStObcdcnInBocnUnique_0",
            "BuildingMutationMethodName",
            "Method_Private_Void_ObjectPublicBuObcdStObcdcnInBocnUnique_Boolean_PDM_0",
        ):
            if symbol not in symbols_text:
                errors.append(f"GameSymbols.FactoryCityScene missing native building lifecycle pin {symbol!r}")
        if "managerRoot.SetActive(true)" not in registrar_code:
            errors.append(
                "registrar must activate the BhBuildingsManager root before native Void(EScene)"
            )
        if registrar_code.find("EnsureOwnedBuildingManagerRootActive();") > registrar_code.find(
            "BindFactorySceneIntoDi2OrThrow(__instance);"
        ):
            errors.append(
                "registrar must activate BhBuildingsManager before binding/allowing native Void(EScene)"
            )
        own_start = registrar_code.find("private static void EnsureFactoryCityWorldOwned()")
        own_end = registrar_code.find(
            "internal static void EnsureOwnedCityPresentationActive()", own_start
        )
        if own_start < 0 or own_end < 0:
            errors.append("registrar ownership/presentation lifecycle methods are missing")
        elif "EnsureOwnedCityPresentationActive();" in registrar_code[own_start:own_end]:
            errors.append(
                "EnsureFactoryCityWorldOwned must not compose Factory art before native "
                "Void(EScene) binds and activates BhBuilding variants"
            )
        postfix_start = registrar_code.find("private static void PostfixEsceneSceneLoad(")
        postfix_end = registrar_code.find("private static int PatchEsceneFromString", postfix_start)
        presentation_start = registrar_code.find("internal static void EnsureOwnedCityPresentationActive()")
        presentation_end = registrar_code.find("internal static void SuspendOwnedCityPresentation", presentation_start)
        if postfix_start < 0 or postfix_end < 0 or presentation_start < 0 or presentation_end < 0:
            errors.append("registrar EScene-load and presentation lifecycle methods are missing")
        else:
            postfix = registrar_code[postfix_start:postfix_end]
            presentation = registrar_code[presentation_start:presentation_end]
            if "EnsureOwnedCityPresentationActive();" not in postfix:
                errors.append("Factory EScene postfix must activate the deterministic camera domain")
            validate_idx = presentation.find("TryValidateOwnedBuildingLifecycle(out var waitingReason)")
            present_idx = presentation.find("Homm3FactoryCityWorldVisuals.ApplyOwnedFactoryWorldArt();")
            if validate_idx < 0 or present_idx < 0 or validate_idx > present_idx:
                errors.append("Factory art must compose only after native building lifecycle readiness")
        for fatal_contract in (
            "_presentationFailed = true;",
            "FailOwnedCityPresentation",
            'SuspendOwnedCityPresentation("fatal " + context)',
            'FailOwnedCityPresentation("presentation activation", ex)',
            'FailOwnedCityPresentation("presentation activate after Void", ex)',
            'FailOwnedCityPresentation("presentation reconcile after " + reason, ex)',
        ):
            if fatal_contract not in registrar_code:
                errors.append(f"Factory structural presentation failure contract missing {fatal_contract!r}")
        fail_start = registrar_code.find("private static void FailOwnedCityPresentation(")
        fail_end = registrar_code.find("private static void QueueFactoryPresentationReconcile(", fail_start)
        if fail_start < 0 or fail_end < 0:
            errors.append("FailOwnedCityPresentation body bounds missing")
        else:
            fail_body = registrar_code[fail_start:fail_end]
            suspend_idx = fail_body.find('SuspendOwnedCityPresentation("fatal " + context)')
            sticky_idx = fail_body.find("_presentationFailed = true;")
            if suspend_idx < 0 or sticky_idx < 0 or sticky_idx < suspend_idx:
                errors.append(
                    "FailOwnedCityPresentation must set _presentationFailed=true AFTER Suspend "
                    "(Suspend clears the flag for leave-town reopen; pre-suspend sticky caused "
                    "Ensure retry loops / black screen)"
                )
        mutation_start = registrar_code.find("private static void PostfixNativeBuildingMutation()")
        mutation_end = registrar_code.find("private static int PatchEsceneSceneIsLoaded", mutation_start)
        mutation = registrar_code[mutation_start:mutation_end] if mutation_start >= 0 and mutation_end >= 0 else ""
        if "Homm3FactoryCityWorldVisuals.IsApplied" in mutation:
            errors.append("initial native building activation must not be gated on Factory art already being applied")
        if "InvalidateAppliedSignature" not in mutation:
            errors.append(
                "native building mutation postfix must InvalidateAppliedSignature before reconcile "
                "(otherwise Fort/Walls construct after settle leaves donor meshes hidden with no HotA art)"
            )
        if 'QueueFactoryPresentationReconcile("native building mutation")' not in mutation:
            errors.append("exact native building mutation postfix must schedule Factory presentation reconciliation")
        visuals_path = (
            ROOT
            / "Heroes of Might & Magic Olden Era Playtest"
            / "OfflineUnlockMod"
            / "Homm3FactoryCityWorldVisuals.cs"
        )
        visuals = visuals_path.read_text(encoding="utf-8") if visuals_path.is_file() else ""
        if "placement.SpriteFile" not in visuals or 'ReadOptionalString(row, "sprite")' not in visuals:
            errors.append(
                "Factory world visuals must load layer textures from positions.json sprite "
                "(Stronghold wall_1→treasury.png; Tower *.dir.png), not invent id.png alone"
            )
        if "InvalidateAppliedSignature" not in visuals:
            errors.append("Homm3FactoryCityWorldVisuals missing InvalidateAppliedSignature")
        # Textures must load after the applied-signature gate so town-layer sync can re-enter Apply
        # every frame without thrashing PNG IO while late slots activate.
        apply_fn = visuals.find("private static void ApplyOwnedFactoryWorldArtOrThrow")
        if apply_fn < 0:
            errors.append("ApplyOwnedFactoryWorldArtOrThrow missing")
        else:
            # Whole function body (to the next member), not a fixed window that drifts as the body grows.
            apply_end = visuals.find("\n\tprivate static ", apply_fn + 1)
            apply_body = visuals[apply_fn : apply_end if apply_end > 0 else len(visuals)]
            sig_idx = apply_body.find("_lastAppliedSignature")
            tex_idx = apply_body.find("LoadLayerTextureOrThrow")
            if sig_idx < 0 or tex_idx < 0 or tex_idx < sig_idx:
                errors.append(
                    "ApplyOwnedFactoryWorldArtOrThrow must gate on _lastAppliedSignature before "
                    "LoadLayerTextureOrThrow so incomplete-join re-entry stays cheap"
                )
            # Camera-track path must move BhBuilding art with the backdrop. Plate+backdrop alone
            # leaves building quads on the old camera pose (parented under native slots, not backdrop).
            if "RepositionExistingBuildingArtOrThrow" not in apply_body:
                errors.append(
                    "signature-matched Apply path must RepositionExistingBuildingArtOrThrow so "
                    "HotA building quads track CityCamera with the mock plate"
                )
            if "RepositionExistingBuildingArtOrThrow" not in visuals or "PlaceBuildingArtQuad" not in visuals:
                errors.append(
                    "Homm3FactoryCityWorldVisuals must share PlaceBuildingArtQuad between first compose "
                    "and camera reposition (one placement path, no silent drift)"
                )
        if "Object.Instantiate(" in registrar_code:
            errors.append(
                "registrar must not Object.Instantiate city roots; "
                "vanilla contract is LoadScene then MoveGameObjectToScene "
                "(Instantiate skipped LoadScene lifecycle Ã¢â€ â€™ black world)"
            )
        if "HasLiveClonedRoots" in registrar_code or "EnsureFactoryCityWorldCloned" in registrar_code:
            errors.append(
                "registrar still uses clone naming; use EnsureFactoryCityWorldOwned / HasLiveOwnedRoots "
                "(LoadScene + Move ownership)"
            )
        stripped = registrar.replace("SceneManager.CreateScene_Injected(", "")
        if "SceneManager.CreateScene(" in stripped:
            errors.append(
                "registrar must not call managed SceneManager.CreateScene(...); "
                "use CreateScene_Injected + ManagedSpanWrapper "
                "(ReadOnlySpan.GetPinnableReference is live-negative)"
            )
        if "Resources.UnloadUnusedAssets" in registrar:
            errors.append("registrar must not use Resources.UnloadUnusedAssets as LoadSceneAsync placeholder")
        if "is not supported for Factory city ownership" not in registrar:
            errors.append("registrar must fail-closed on LoadSceneAsync Factory intercept")
        # Donor Castle roots must be unloaded, not SetActive(false). Presentation park on leave
        # (Lights/CityCamera via SuspendOwnedCityPresentation) is the allowed SetActive(false) path.
        if "DeactivateDonorWorldForFactoryPresentation" in registrar:
            errors.append("registrar must not leave donor roots SetActive(false); unload donor instead")
        if "root.SetActive(false)" in registrar and "SuspendOwnedCityPresentation" not in registrar:
            errors.append("registrar must not leave donor roots SetActive(false); unload donor instead")
        suspend_idx = registrar.find("SuspendOwnedCityPresentation")
        own_idx = registrar.find("EnsureFactoryCityWorldOwned")
        if "root.SetActive(false)" in registrar and suspend_idx >= 0 and own_idx >= 0:
            # Fail if SetActive(false) appears in ownership/move path outside Suspend.
            own_slice = registrar[own_idx : own_idx + 8000]
            if "SetActive(false)" in own_slice and "SuspendOwnedCityPresentation" not in own_slice:
                errors.append(
                    "EnsureFactoryCityWorldOwned must not SetActive(false) donor roots; unload donor instead"
                )

    plugin_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Plugin.cs"
    )
    if not plugin_cs.is_file():
        errors.append(f"missing {plugin_cs}")
    elif "Homm3FactoryCitySceneRegistrar.RegisterRequired" not in plugin_cs.read_text(encoding="utf-8"):
        errors.append("Plugin.cs must call Homm3FactoryCitySceneRegistrar.RegisterRequired")

    launcher_cs = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "LauncherConfig.cs"
    )
    if not launcher_cs.is_file():
        errors.append(f"missing {launcher_cs}")
    else:
        launcher = launcher_cs.read_text(encoding="utf-8")
        if 'homm3FactoryCitySceneReplace' not in launcher:
            errors.append("LauncherConfig.cs missing homm3FactoryCitySceneReplace key handling")
        if "Homm3FactoryCitySceneReplace" not in launcher:
            errors.append("LauncherConfig.cs missing Homm3FactoryCitySceneReplace property")

    repo_config = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "config.json"
    )
    if repo_config.is_file():
        import json

        cfg = json.loads(repo_config.read_text(encoding="utf-8"))
        if cfg.get("homm3FactoryCitySceneReplace") is not True:
            errors.append(
                "OfflineUnlockMod/config.json must set homm3FactoryCitySceneReplace=true "
                "while Factory citySceneName is cityFactory"
            )

    symbols_text = GAME_SYMBOLS.read_text(encoding="utf-8")
    if "ExpectedBhBuildingCount = 34" not in symbols_text and "ExpectedBhBuildingCount=34" not in symbols_text:
        errors.append("GameSymbols.FactoryCityScene.ExpectedBhBuildingCount must be 34")

    if errors:
        print("FAIL factory city scene contract:")
        for e in errors:
            print(" -", e)
        return 1

    print(
        "OK factory city scene contract: 20 Castle-parity sceneSlot names aligned "
        "(GameSymbols + vanilla ledger); load pins doc present; "
        "playtest city_hive helper / get_sceneName rewrite gates OK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
