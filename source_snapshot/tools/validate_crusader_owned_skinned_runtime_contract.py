#!/usr/bin/env python3
"""Validate the shared marker and runtime seams for the owned-skinned battle lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
UNITY_PROJECT = ROOT / "oldenera_factions"
UNITY_BUILDER = ROOT / "oldenera_factions" / "Assets" / "Editor" / "CrusaderOwnedSkinnedLabBuild.cs"
UNITY_CANONICAL_LAB_BUILDER = ROOT / "tools" / "homm3_import" / "unity_editor" / "CrusaderOwnedSkinnedLabBuild.cs"
UNITY_BUNDLE_BUILDER = ROOT / "oldenera_factions" / "Assets" / "Editor" / "BuildCustomUnitBundles.cs"
UNITY_CANONICAL_BUNDLE_BUILDER = ROOT / "tools" / "custom_prefab_pipeline" / "unity_editor" / "BuildCustomUnitBundles.cs"
MARKER = "__homm3_skinned_battle_lane__"
# 2026-10-08 lane switch: the Crusader binds the shared def_retarget owned-skinned prefab like every other castle unit
# (ship_def_retarget_slice.require_scope); the Aug 17 crusader_owned_skinned.prefab lane is retired.
CRUSADER_BUNDLE = "custom_units_castle_h3_crusader"
CRUSADER_PREFAB = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/owned_skinned.prefab"
LEGACY_CRUSADER_PREFAB = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned.prefab"
IMPORT_TABLE = PLUGIN / "homm3_import.json"
UNITS_MANIFEST = ROOT / "tools" / "homm3_import" / "homm3_units_manifest.json"
ETALON_SHADER_GUID = "78014d7ab89888f49b8c173e150ffc71"


def require_contains(errors: list[str], path: Path, text: str) -> None:
    if not path.exists():
        errors.append(f"missing file: {path}")
        return
    if text not in path.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"{path}: missing contract text {text!r}")


def require_not_contains(errors: list[str], path: Path, text: str) -> None:
    if not path.exists():
        errors.append(f"missing file: {path}")
        return
    if text in path.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"{path}: forbidden contract text {text!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-artifact", action="store_true",
                        help="require the built Unity owned-skinned Crusader prefab (post lab build)")
    args = parser.parse_args()

    errors: list[str] = []
    visuals = PLUGIN / "Homm3ImportVisuals.cs"
    release = PLUGIN / "Homm3ImportReleaseBattleVisualHook.cs"
    pool = PLUGIN / "Homm3ImportBattlePoolHook.cs"
    facing = PLUGIN / "Homm3BattleAttackFacingHook.cs"
    array_bridge = PLUGIN / "Homm3MapArraySliceHexLitBridge.cs"

    # Material.IsKeywordEnabled(string) binds through Il2CppSystem.ReadOnlySpan and throws
    # MissingMethodException on the live Golden Era interop (2026-09-26: every owned skinned swap
    # failed). Use shaderKeywords (HasMaterialKeyword) instead, anywhere in the plugin.
    for source in sorted(PLUGIN.glob("*.cs")):
        require_not_contains(errors, source, ".IsKeywordEnabled(")
    require_contains(errors, visuals, "internal const string SkinnedBattleLaneMarkerName")
    require_contains(errors, visuals, "internal static bool IsHomm3SkinnedBattleInstance")
    require_contains(errors, visuals, "internal static bool TryApplySkinnedBattleTargetFacing")
    require_contains(errors, visuals, "EnsureSkinnedBattleRuntimeCompatibility")
    require_contains(errors, visuals, "Shader.Find(\"Hex/Lit\")")
    require_contains(errors, visuals, "ResolveOwnedSkinnedHexLitShader")
    require_contains(errors, visuals, "OwnedSkinnedMaterialNeedsHexLit")
    require_contains(errors, visuals, "refuse unit_cutout")
    require_contains(errors, visuals, "FallbackError")
    require_contains(errors, release, "internal static void AttachRuntimeHelpers")
    require_contains(errors, release, "EnsureSkinnedBattleRuntimeCompatibility")
    require_contains(errors, release, "TryGetCachedBattlePresentationTemplate(entry, Plugin.LogSource, out var presentationDonor)")
    require_contains(errors, release, "EnsureSkinnedBattleRuntimeCompatibility(instance, materialDonor, entry, Plugin.LogSource)")
    require_contains(errors, release, "Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance)")
    # Combat Init must not ResManager-load the presentation donor (observed combat-load freeze
    # when the re-entrant ResManager.Get ran inside ecd.Init); only the cache-only getter is
    # allowed on the release path.
    require_not_contains(errors, release, "Homm3ImportVisuals.TryGetBattlePresentationTemplate(entry")
    mesh_fx = PLUGIN / "Homm3MeshFx.cs"
    require_contains(errors, mesh_fx, "TryGetCachedNativeResManagerGameObject")
    require_contains(errors, mesh_fx, "TryLoadNativeResManagerGameObjectIl2Cpp")
    require_not_contains(errors, mesh_fx, "TryLoadNativeResManagerGameObject(")
    require_not_contains(errors, mesh_fx, "TryLoadResManagerGameObject")
    require_contains(errors, pool, "Homm3ImportReleaseBattleVisualHook.AttachRuntimeHelpers")
    require_contains(errors, pool, "PrefixBathTwoArg")
    # The 3-arg loader's out param is the drawer renderer set (live bep -> eck.cfdq); eck.bcah
    # dereferences it unguarded. A stale 'bei' hint made that loader look 2-arg, cfdq stayed null
    # for every synthetic unit, and the battle-result step softlocked (2026-09-27). Pin the live
    # type, refuse a mismatched 3-arg loader at registration, and fail the load on a null build.
    game_symbols = PLUGIN / "GameSymbols.cs"
    factory = PLUGIN / "Homm3BattlePoolMetadataFactory.cs"
    require_contains(errors, game_symbols, '{ "ObjectPublicGabsLi1ReMabsLi1InUnique", "bep" };')
    require_not_contains(errors, game_symbols, '{ "bei", "MonoBehaviourPublicStbsCaRebsLi1RabsNuUnique" }')
    require_contains(errors, pool, "refusing to patch (would leave the drawer renderer set null)")
    require_contains(errors, pool, "if (m.GetParameters().Length >= 3)")
    require_contains(errors, pool, "failing the load.")
    require_not_contains(errors, pool, "Homm3BattlePoolInterop.IsMetadataType(thirdOut))\n\t\t\t\t\th.Patch")
    require_contains(errors, factory, "match.Invoke(new object[] { instance, flag, null })")
    require_not_contains(errors, factory, "catch { }")
    require_contains(errors, pool, "TryGetCachedBattlePresentationTemplate")
    require_not_contains(errors, pool, "TryGetBattlePresentationTemplate(entry")
    require_contains(errors, facing, "Homm3ImportVisuals.TryApplySkinnedBattleTargetFacing")
    require_contains(errors, facing, "Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(root)")
    preview_model = PLUGIN / "Homm3ImportUnitPreviewModelHook.cs"
    require_contains(errors, preview_model, "DonorSidToPreviewCatalogId")
    require_not_contains(errors, preview_model, "return NormalizeDungeonDonorLeaf(donorSid)")
    require_contains(errors, preview_model, "Homm3OwnedSkinnedPreviewFraming.TryFrame(")
    require_not_contains(errors, preview_model, "PlaceOwnedSkinnedPreviewAtVanillaMeshPose")
    require_not_contains(errors, preview_model, "FitSkinnedMeshToPreviewBackground")
    require_not_contains(errors, preview_model, "return !UseStaticPreviewPortraits()")
    fine_tune = PLUGIN / "Homm3PreviewFineTune.cs"
    require_contains(errors, fine_tune, "keeping Hex/Lit on owned skinned mesh")
    require_contains(errors, fine_tune, "overlay material modes are forbidden on owned skinned meshes")
    require_contains(errors, fine_tune, "IsHomm3SkinnedBattleInstance(Target)")
    require_contains(errors, visuals, "PlaceOwnedSkinnedPreviewAtVanillaMeshPose")
    require_contains(errors, visuals, "LooksLikeHomm3BillboardPreviewDonor")
    require_not_contains(errors, visuals, "FitSkinnedMeshToPreviewBackground")
    require_contains(errors, visuals, "FitSkinnedMeshToDonorWorldHeight")
    require_contains(errors, visuals, "FinishOwnedSkinnedAdventureMapPresentation")
    require_contains(errors, visuals, "owned skinned map presentation")
    require_contains(errors, visuals, "ApplyMapRendererFlagsFromDonor(donorRenderer, visual)")
    require_contains(errors, visuals, "PrepareNativeShellFogProbeRenderers(shell, visualRoot)")
    require_contains(errors, visuals, "TryApplyOwnedSkinnedSideFacing")
    # left 150 / right -30 = native +/-90 minus the fleet bind facing -60 (validate_homm3_owned_skinned_facing_contract.py)
    require_contains(errors, visuals, "OwnedSkinnedOrientationYawFor(leftSide ? NativeBattleScaleRollYaw : -NativeBattleScaleRollYaw)")
    require_contains(errors, visuals, "internal const float OwnedSkinnedBindFacingYaw = -60f;")
    require_contains(errors, visuals, "internal const float NativeBattleScaleRollYaw = 90f;")
    require_not_contains(errors, visuals, "leftSide ? 90f : -90f")
    require_not_contains(errors, visuals, "leftSide ? 0f : 180f")
    # 2026-09-29: h3_pegasus ships the real CPEGAS retarget (pegasus_slice_v1), so the old SID refusal of the
    # Meshy sample quadruped hid a correct mesh (billboard on the map, empty recruit preview). It must not return.
    for quarantine in ("IsQuarantinedMeshyDemoLabSid", "TryRefuseQuarantinedMeshyDemoSkinned", "IsQuarantinedMeshyDemoEntry"):
        require_not_contains(errors, visuals, quarantine)
    require_contains(errors, visuals, "preserveAdventureHexFog")
    require_not_contains(errors, visuals, "_DitherFadeEnabled\", 2f")
    require_contains(errors, visuals, "hex-map")
    # Adventure-map size: battle hex target x measured native map/battle ratio (not the full battle size).
    require_contains(errors, visuals, "_adventureMapToBattleHeightRatio.Value")
    require_contains(errors, visuals, "\"hex-map mapRatio=\"")
    # Battle size: battleWorldHeightPerHex is the median of the stock/HoMM3 pair measurement
    # (tools/homm3_import/measure_native_battle_height.py), never a hand-set constant.
    import_table = json.loads((PLUGIN / "homm3_import.json").read_text(encoding="utf-8-sig"))
    height_artifact = ROOT / "tools" / "homm3_import" / "native_battle_height.json"
    measured_height = json.loads(height_artifact.read_text(encoding="utf-8")) if height_artifact.is_file() else {}
    if measured_height.get("schema") != "native_battle_height.v1" or int(measured_height.get("measuredPairs") or 0) < 20:
        errors.append(f"{height_artifact}: missing or not native_battle_height.v1 with >=20 pairs")
    elif abs(float(import_table.get("battleWorldHeightPerHex") or 0) - float(measured_height["median"])) > 5e-4:
        errors.append(f"homm3_import.json battleWorldHeightPerHex {import_table.get('battleWorldHeightPerHex')} != measured median {measured_height['median']}; rerun measure_native_battle_height.py --write")
    require_contains(errors, visuals, "_battleWorldHeightPerHex.Value")
    # Adventure-map fog is shader-global; owned materials must end on the native multi-pass Hex/Lit.
    require_contains(errors, visuals, "var nativeFogShader = VerifyOwnedSkinnedMapUsesNativeHexLit(visual, log);")
    require_contains(errors, visuals, "passes > 1")
    require_contains(errors, visuals, "AlignOwnedSkinnedPreviewToDonorCenter")
    require_contains(errors, PLUGIN / "Homm3OwnedSkinnedMapFogProbe.cs", "_HexFade")
    require_contains(errors, PLUGIN / "Homm3OwnedSkinnedMapFogProbe.cs", "controllerOwnsOwnedDraw=true")
    require_not_contains(errors, PLUGIN / "Homm3OwnedSkinnedMapFogProbe.cs", "owned.forceRenderingOff = false")
    require_not_contains(errors, PLUGIN / "Homm3OwnedSkinnedMapFogProbe.cs", "owned.enabled = nativeVisible")
    require_contains(errors, PLUGIN / "Homm3ImportReleaseBattleVisualHook.cs", "TryApplyOwnedSkinnedSideFacing")
    require_not_contains(errors, PLUGIN / "Homm3ImportReleaseBattleVisualHook.cs", "TryRefuseQuarantinedMeshyDemoSkinned")
    require_not_contains(errors, PLUGIN / "Homm3ImportBattlePoolHook.cs", "TryRefuseQuarantinedMeshyDemoSkinned")
    require_not_contains(errors, PLUGIN / "Homm3BattleDiskTextureRemap.cs", "IsQuarantinedMeshyDemoLabSid")
    require_contains(errors, visuals, "ApplyOwnedSkinnedHexLitPbr")
    # 2026-09-26 castle scramble: a cached bundle albedo freed by a scene change read as a settled miss
    # (Unity == null), and the clone kept the donor's _MainTex over the unit's UVs. Misses are managed
    # nulls, a freed hit is re-resolved, and the donor base map is always overwritten (cleared on a miss).
    require_contains(errors, visuals, "if (ReferenceEquals(cachedTexture, null))\n\t\t\t\treturn null;")
    require_not_contains(errors, visuals, "if (cachedTexture == null)\n\t\t\t\treturn null;")
    require_contains(errors, visuals, 'material.SetTexture("_MainTex", albedo ? albedo : null);')
    require_contains(errors, visuals, 'material.SetTexture("_BaseMap", albedo ? albedo : null);')
    require_not_contains(errors, visuals, "if (albedo != null)\n\t\t{\n\t\t\tif (material.HasProperty(\"_MainTex\"))")
    require_contains(errors, visuals, "VerifyOwnedSkinnedAlbedoBound(fallback, bundleTexture, entry, lane, log);")
    require_contains(errors, visuals, "_MetallicGlossMap")
    require_contains(errors, visuals, "crusader_owned_skinned_metallicgloss.png")
    require_contains(errors, visuals, "TryLoadOwnedSkinnedSidecarTexture")
    require_contains(errors, visuals, "homm3_skinned_pbr")
    require_contains(errors, visuals, "SanitizeMapMaterialForOpaqueMesh")
    require_contains(errors, visuals, "EnsureOwnedSkinnedDeliveryOrientation")
    require_contains(errors, visuals, "AlignOwnedSkinnedFeetToDonor")
    require_contains(errors, visuals, "idle-0 bind already faces Unity forward")
    require_not_contains(errors, visuals, "inserted Orientation parent +90 yaw")
    require_not_contains(errors, visuals, "applied Unity +90 yaw on map visual")
    controller = PLUGIN / "Homm3MapSquadVisualControllerHook.cs"
    require_contains(errors, controller, "fogProbeOwnsDraw=owned-skinned")
    require_not_contains(errors, controller, "initRestoreDraw=owned-skinned")
    require_contains(errors, controller, "requested=")
    require_contains(errors, PLUGIN / "Homm3ImportPreviewSyntheticMeshHook.cs", "StackContainsHqv")
    require_contains(errors, PLUGIN / "Homm3ImportPreviewSyntheticMeshHook.cs", "fromHqv && Homm3ImportVisuals.IsOwnedSkinnedBattleEntry")
    # The installed Hex/Lit declares no normal/metallic slots (docs/homm3_prebaked_lighting.md):
    # the donor gate must not require them, or every owned skinned unit is refused.
    require_contains(errors, visuals, "no native Hex/Lit sheet is loaded")
    require_contains(errors, visuals, "OwnedSkinnedHexLitSheetUsable")
    # The bundle ships a 1-pass stub named "Hex/Lit"; donor gates must require the native shader.
    require_contains(errors, visuals, "EsquirePikemanVisuals.IsNativeHexLitShader(material.shader)")
    require_contains(errors, PLUGIN / "EsquirePikemanVisuals.cs", "shader.passCount > 1")
    require_contains(errors, PLUGIN / "EsquirePikemanVisuals.cs", "if (!IsNativeHexLitShader(material.shader))")
    require_not_contains(errors, visuals, "OwnedSkinnedHexLitSheetHasPbrSlots")
    # 2026-09-26 battle-invisible regression: a UI-preview donor (per-renderer material instance)
    # was cached as the shared Hex/Lit sheet; Hex/Lit's Lit VS applies _PreviewScreenOffset to
    # clip xy in every variant. Preview donors never feed the cache; battle/map clones reset
    # per-context state and self-check against the native unit sheet values, loudly.
    require_contains(errors, visuals, "EnsureSkinnedAdventureMapIdle(visual, entry, log, hexLitDonor, uiPreviewLane: true)")
    require_contains(errors, visuals, "if (!uiPreviewLane)\n\t\t\t_cachedNativeHexLitSheet = donorMaterial;")
    require_contains(errors, visuals, "if (!uiPreviewLane)\n\t\t\t\t\t\tResetOwnedSkinnedHexLitInstanceState(fallback);")
    require_contains(errors, visuals, "VerifyOwnedSkinnedHexLitVisibleState(instance, entry, lane, log);")
    require_contains(errors, visuals, "\"_PreviewScreenOffset\", \"_HexFade\"")
    require_contains(errors, visuals, "\"HEX_UI_PREVIEW_CAMERA\"")
    require_contains(errors, visuals, "visibility self-check FAILED")
    require_contains(errors, visuals, "log.LogError(")
    require_not_contains(errors, visuals, "\t\t_cachedNativeHexLitSheet = donorMaterial;\n\n\t\tvar changedMaterials")
    require_contains(errors, PLUGIN / "EsquirePikemanVisuals.cs", "requiring them rejected every loaded donor")
    require_not_contains(errors, visuals, "new Material(hexLit)")
    mirror = PLUGIN / "Homm3MapSquadVisualMirror.cs"
    require_contains(errors, mirror, "r.forceRenderingOff = !visible")
    require_contains(errors, visuals, "glTF / PbrMetallicRoughness")
    require_contains(errors, visuals, "EnsureSkinnedAdventureMapIdle(visual, entry, log, hexLitDonor, preserveAdventureHexFog: true)")
    require_contains(errors, array_bridge, "EnsureIl2CppTypeRegistered")
    sidecar_normal = PLUGIN / "homm3_skinned_pbr" / "h3_crusader" / "crusader_owned_skinned_normal.png"
    sidecar_metal = PLUGIN / "homm3_skinned_pbr" / "h3_crusader" / "crusader_owned_skinned_metallicgloss.png"
    if not sidecar_normal.is_file():
        errors.append(f"missing crusader Hex/Lit normal sidecar: {sidecar_normal}")
    if not sidecar_metal.is_file():
        errors.append(f"missing crusader Hex/Lit metallic-gloss sidecar: {sidecar_metal}")
    require_contains(errors, UNITY_BUILDER, MARKER)
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, MARKER)
    require_contains(errors, UNITY_BUILDER, "new GameObject(SkinnedLaneMarkerName)")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "new GameObject(SkinnedLaneMarkerName)")
    require_contains(errors, UNITY_BUILDER, "Etalon_mt.mat")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "Etalon_mt.mat")
    require_contains(errors, UNITY_BUILDER, "BuildRuntimeCompatibleMaterial")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "BuildRuntimeCompatibleMaterial")
    require_contains(errors, UNITY_BUILDER, "crusader_owned_skinned.mat")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "crusader_owned_skinned.mat")
    require_contains(errors, UNITY_BUILDER, "DeliveryNormalSource")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "DeliveryNormalSource")
    require_contains(errors, UNITY_BUILDER, "DeliveryMetallicGlossSource")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "DeliveryMetallicGlossSource")
    require_contains(errors, UNITY_BUILDER, "BindMetallicGlossMap")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "BindMetallicGlossMap")
    require_contains(errors, UNITY_BUNDLE_BUILDER, "battlePresentationLane")
    require_contains(errors, UNITY_BUNDLE_BUILDER, "IsSkinnedBattleLane")
    require_contains(errors, UNITY_BUNDLE_BUILDER, "if (!skinnedBattle && !battleArray)")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "battlePresentationLane")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "IsSkinnedBattleLane")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "if (!skinnedBattle && !battleArray)")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "crusader_owned_skinned_basecolor.jpg")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "crusader_owned_skinned_normal.png")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "crusader_owned_skinned_metallicgloss.png")
    require_contains(errors, UNITY_CANONICAL_BUNDLE_BUILDER, "AddRequiredSkinnedAsset")
    require_contains(errors, UNITY_BUILDER, "RebaseClipPaths")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "RebaseClipPaths")
    require_contains(errors, UNITY_BUILDER, "EnsureQuaternionContinuity")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "EnsureQuaternionContinuity")
    require_contains(errors, UNITY_BUILDER, "FlattenRotationTangents")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "FlattenRotationTangents")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "key.inTangent /= factor")
    require_contains(errors, UNITY_BUILDER, "DeliveryAlbedoSource")
    require_contains(errors, UNITY_CANONICAL_LAB_BUILDER, "DeliveryAlbedoSource")

    # Crusader binding: the import table and the units manifest bind the shared owned-skinned prefab, never the
    # retired crusader_owned_skinned.prefab lane.
    table = json.loads(IMPORT_TABLE.read_text(encoding="utf-8")) if IMPORT_TABLE.is_file() else {}
    rows = [e for e in table.get("entries", []) if e.get("bundleName") == CRUSADER_BUNDLE]
    if len(rows) != 1:
        errors.append(f"{IMPORT_TABLE}: expected exactly one {CRUSADER_BUNDLE} import row, found {len(rows)}")
    for e in rows:
        for key in ("battlePrefabAssetPath", "mapPrefabAssetPath"):
            if str(e.get(key, "")).replace("\\", "/") != CRUSADER_PREFAB:
                errors.append(f"{IMPORT_TABLE}: Crusader {key} must be {CRUSADER_PREFAB}, got {e.get(key)!r}")
    if IMPORT_TABLE.is_file() and LEGACY_CRUSADER_PREFAB in IMPORT_TABLE.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"{IMPORT_TABLE}: still binds the retired {LEGACY_CRUSADER_PREFAB}")
    inventory = json.loads(UNITS_MANIFEST.read_text(encoding="utf-8")) if UNITS_MANIFEST.is_file() else {}
    items = [u for u in inventory.get("units", []) if u.get("unitSid") == "h3_crusader"]
    if len(items) != 1:
        errors.append(f"{UNITS_MANIFEST}: expected exactly one h3_crusader row, found {len(items)}")
    for u in items:
        for key in ("battlePrefabAsset", "mapPrefabAsset"):
            if str(u.get(key, "")).replace("\\", "/") != CRUSADER_PREFAB:
                errors.append(f"{UNITS_MANIFEST}: h3_crusader {key} must be {CRUSADER_PREFAB}, got {u.get(key)!r}")
        if u.get("battlePresentationLane") != "skinned_mesh":
            errors.append(f"{UNITS_MANIFEST}: h3_crusader must declare battlePresentationLane=skinned_mesh")

    prefab = UNITY_PROJECT.joinpath(*CRUSADER_PREFAB.split("/"))
    if args.require_artifact or prefab.is_file():
        if not prefab.is_file():
            errors.append(f"missing Unity owned-skinned Crusader prefab: {prefab}")
        else:
            prefab_text = prefab.read_text(encoding="utf-8", errors="replace")
            for required in (MARKER, "SkinnedMeshRenderer:", "Animator:", "m_Mesh:", "m_Bones:", "m_Controller:", "m_CullingMode: 0"):
                if required not in prefab_text:
                    errors.append(f"Unity prefab missing required skinned-lane evidence {required!r}: {prefab}")
            material = prefab.parent / "owned_skinned.mat"
            material_meta = material.with_name(material.name + ".meta")
            if not material.is_file() or not material_meta.is_file():
                errors.append(f"missing explicit vanilla-compatible Crusader material: {material}")
            else:
                material_text = material.read_text(encoding="utf-8", errors="replace")
                if ETALON_SHADER_GUID not in material_text:
                    errors.append(f"Crusader material does not use the Etalon runtime shader GUID {ETALON_SHADER_GUID}: {material}")
                if "Shader Graphs/glTF" in material_text or "glTF-pbrMetallicRoughness" in material_text:
                    errors.append(f"Crusader material still contains the unsupported GLTF shader contract: {material}")
                material_guid = ""
                for line in material_meta.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("guid:"):
                        material_guid = line.split(":", 1)[1].strip()
                        break
                if material_guid and f"guid: {material_guid}" not in prefab_text:
                    errors.append(f"owned-skinned prefab does not reference its explicit material asset: {material}")

    result = {"ok": not errors, "schema": "crusader_owned_skinned_runtime_contract.v1", "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
