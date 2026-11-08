#!/usr/bin/env python3
"""Validate custom town adventure-map billboard contracts stay scoped.

Adventure map billboards must inherit layer/sorting from the selected donor
Renderer, copied native draw renderers must bottom-anchor to the native shell
origin instead of using synthetic lift, and random-hire dwelling bindings must
use exact map-object ids instead of raw-SID queues.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


def fail(message: str) -> None:
    print(f"custom-town-billboard-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_method_body(source: str, name: str) -> str:
    match = re.search(r"(?:private|internal|public)?\s*(?:static\s+)?[\w<>]+\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", source)
    if not match:
        fail(f"missing method {name}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    fail(f"unterminated method {name}")
    return ""


def require_contains(body: str, token: str, context: str) -> None:
    if token not in body:
        fail(f"{context} must contain {token!r}")


def require_order(body: str, first: str, second: str, context: str) -> None:
    first_index = body.find(first)
    second_index = body.find(second)
    if first_index < 0 or second_index < 0 or first_index > second_index:
        fail(f"{context} must evaluate {first!r} before {second!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-cs", required=True, type=pathlib.Path)
    args = parser.parse_args()

    plugin_cs = args.plugin_cs
    if not plugin_cs.is_file():
        fail(f"Plugin.cs not found: {plugin_cs}")
    presentation_cs = plugin_cs.parent / "EsquireBattleVisualPresentation.cs"
    if not presentation_cs.is_file():
        fail(f"EsquireBattleVisualPresentation.cs not found: {presentation_cs}")
    presentation_source = presentation_cs.read_text(encoding="utf-8-sig")
    renderer_body = find_method_body(presentation_source, "ApplyMapRendererFlagsFromDonor")
    for token in (
        "var donorLayer = donor.gameObject != null ? donor.gameObject.layer : customRoot.layer",
        "customRoot.layer = donorLayer",
        "r.gameObject.layer = donorLayer",
        "r.sortingLayerID = donor.sortingLayerID",
        "r.sortingOrder = donor.sortingOrder",
        "r.renderingLayerMask = donor.renderingLayerMask",
        "r.shadowCastingMode = donor.shadowCastingMode",
        "r.receiveShadows = donor.receiveShadows",
        "r.lightProbeUsage = donor.lightProbeUsage",
        "r.reflectionProbeUsage = donor.reflectionProbeUsage",
        "r.motionVectorGenerationMode = donor.motionVectorGenerationMode",
        "r.allowOcclusionWhenDynamic = donor.allowOcclusionWhenDynamic",
    ):
        require_contains(renderer_body, token, "map renderer donor flag helper")

    import_visuals_cs = plugin_cs.parent / "Homm3ImportVisuals.cs"
    if not import_visuals_cs.is_file():
        fail(f"Homm3ImportVisuals.cs not found: {import_visuals_cs}")
    import_visuals_source = import_visuals_cs.read_text(encoding="utf-8-sig")
    scale_body = find_method_body(import_visuals_source, "ResolveLocalScaleForParent")
    require_contains(scale_body, "parent.lossyScale", "map billboard scale helper")
    require_contains(scale_body, "throw new InvalidOperationException", "map billboard scale helper")
    for token in (
        "desiredWorldScale.x / parentScale.x",
        "desiredWorldScale.y / parentScale.y",
        "desiredWorldScale.z / parentScale.z",
    ):
        require_contains(scale_body, token, "map billboard scale helper")
    if "? value : value / divisor" in scale_body or "DivideScale(" in scale_body:
        fail("map billboard scale helper must fail loudly on impossible parent scale, not substitute desired scale")

    anchor_body = find_method_body(import_visuals_source, "AlignMapBillboardRendererBottomToShellAnchor")
    for token in (
        "targetRenderer.bounds",
        "bounds.min.y",
        "throw new InvalidOperationException",
        "shellTransform.position.y - bottomY",
        "targetRenderer.transform.position += Vector3.up * deltaY",
    ):
        require_contains(anchor_body, token, "map billboard shell-anchor helper")

    bridge_cs = plugin_cs.parent / "Homm3MapArraySliceHexLitBridge.cs"
    if not bridge_cs.is_file():
        fail(f"Homm3MapArraySliceHexLitBridge.cs not found: {bridge_cs}")
    bridge_source = bridge_cs.read_text(encoding="utf-8-sig")
    bridge_transform_body = find_method_body(bridge_source, "SyncBillboardTransformFromSourceToTarget")
    require_contains(bridge_transform_body, "tgt.position = src.position", "map array bridge transform")
    require_contains(bridge_transform_body, "tgt.rotation = src.rotation", "map array bridge transform")
    require_contains(bridge_transform_body, "ResolveLocalScaleForParent(src.lossyScale, tgt.parent)", "map array bridge transform")
    require_contains(bridge_transform_body, "AlignMapBillboardRendererBottomToShellAnchor(_targetRenderer, transform)", "map array bridge transform")
    if "tgt.position = src.position +" in bridge_transform_body or "ResolveSyntheticWorldVerticalLift" in bridge_source:
        fail("map array bridge must use renderer-bottom shell anchoring, not synthetic vertical lift")

    transplant_cs = plugin_cs.parent / "Homm3NativeShellRendererTransplantSync.cs"
    if not transplant_cs.is_file():
        fail(f"Homm3NativeShellRendererTransplantSync.cs not found: {transplant_cs}")
    transplant_source = transplant_cs.read_text(encoding="utf-8-sig")
    transplant_transform_body = find_method_body(transplant_source, "SyncBillboardTransformFromSourceToTarget")
    require_contains(transplant_transform_body, "tgt.position = src.position", "native-shell transplant transform")
    require_contains(transplant_transform_body, "tgt.rotation = src.rotation", "native-shell transplant transform")
    require_contains(transplant_transform_body, "ResolveLocalScaleForParent(src.lossyScale, tgt.parent)", "native-shell transplant transform")
    require_contains(transplant_transform_body, "AlignMapBillboardRendererBottomToShellAnchor(_targetRenderer, transform)", "native-shell transplant transform")
    if "tgt.position = src.position +" in transplant_transform_body or "ResolveSyntheticWorldVerticalLift" in transplant_source:
        fail("native-shell transplant must use renderer-bottom shell anchoring, not synthetic vertical lift")
    apply_transplant_body = find_method_body(transplant_source, "ApplyTransplant")
    require_order(apply_transplant_body, "SyncBillboardTransformFromSourceToTarget();", "_targetRenderer.enabled = _controllerVisible", "native-shell transplant apply")
    if "if (meshCopied)\n\t\t\tSyncBillboardTransformFromSourceToTarget();" in apply_transplant_body:
        fail("native-shell transplant must sync transform even when mesh copy fails and material sync continues")

    town_billboard_cs = plugin_cs.parent / "Homm3CustomTownMapBillboard.cs"
    if not town_billboard_cs.is_file():
        fail(f"Homm3CustomTownMapBillboard.cs not found: {town_billboard_cs}")
    town_billboard_source = town_billboard_cs.read_text(encoding="utf-8-sig")
    require_contains(town_billboard_source, 'PostLoadScannerFlagName = "homm3_town_billboard_post_load_scanner.flag"', "town billboard diagnostic post-load scanner gate")
    if "DisablePostLoadFinalizerFlagName" in town_billboard_source or "homm3_town_billboard_disable_post_load_finalizer.flag" in town_billboard_source:
        fail("town billboard post-load scanner must be opt-in diagnostic, not default-on with a disable flag")
    post_load_scanner_body = find_method_body(town_billboard_source, "EnsurePostLoadScanner")
    require_contains(post_load_scanner_body, "if (!Homm3DiagnosticFlags.IsEnabled(PostLoadScannerFlagName))", "town billboard diagnostic post-load scanner gate")
    root_name_city_body = find_method_body(town_billboard_source, "TryGetRootNameCityBillboard")
    for token in (
        "TryGetPlacedObjectRootName(placedInstance)",
        "string.IsNullOrWhiteSpace(rootName)",
        "TryResolveCityBillboardSid(rootName, out citySid, out relativePath, out billboardHeight)",
    ):
        require_contains(root_name_city_body, token, "town billboard exact root-name SID lane")
    init_body = find_method_body(town_billboard_source, "PostfixReleaseMapObjectInit")
    require_contains(init_body, "TryGetRootNameCityBillboard(__instance, out citySid, out relativePath, out billboardHeight)", "town billboard init SID resolution")
    require_order(
        init_body,
        "TryGetMetaCityBillboard(meta, out citySid, out relativePath, out billboardHeight)",
        "TryGetRootNameCityBillboard(__instance, out citySid, out relativePath, out billboardHeight)",
        "town billboard init SID resolution",
    )
    require_order(
        init_body,
        "TryGetRootNameCityBillboard(__instance, out citySid, out relativePath, out billboardHeight)",
        "TryGetPropCityBillboard(__instance, meta, mapInstance, nodeArg, out citySid, out relativePath, out billboardHeight)",
        "town billboard exact root-name SID lane must run before generic PropCity routing",
    )
    prop_city_body = find_method_body(town_billboard_source, "TryGetPropCityBillboard")
    require_contains(prop_city_body, "var isGenericCityObject =", "town billboard PropCity routing")
    require_contains(prop_city_body, "not-generic-city-object-without-custom-propcity", "town billboard PropCity routing")
    require_order(
        prop_city_body,
        "Homm3MapObjectPropCityResolver.TryGetMapObjectPropCityFaction(objectsProperties, objectId, out var factionSid)",
        "not-generic-city-object-without-custom-propcity",
        "town billboard PropCity routing must check object PropCity before rejecting non-generic roots",
    )
    if "LogPropCityRouteMiss(\"not-generic-city-object\"" in prop_city_body:
        fail("town billboard PropCity routing must not reject non-generic roots before object PropCity lookup")
    hide_renderers_body = find_method_body(town_billboard_source, "HideExistingRenderers")
    require_contains(hide_renderers_body, "r.forceRenderingOff = true;", "town billboard donor renderer suppression")
    suppressor_body = find_method_body(town_billboard_source, "SuppressDonorRenderers")
    require_contains(suppressor_body, "renderer.forceRenderingOff = true;", "town billboard donor suppressor reassertion")
    late_suppressor_body = find_method_body(town_billboard_source, "SuppressLateCitySidRenderers")
    require_contains(late_suppressor_body, "renderer.forceRenderingOff = true;", "town billboard late donor suppressor reassertion")
    suppressor_type_source = town_billboard_source[town_billboard_source.index("public sealed class Homm3TownBillboardDonorSuppressor"):]
    # Native map init can re-enable donor meshes after Start. LateUpdate reassertion is the
    # owned suppress path; forbid empty/unrelated Update polling and any Update() hook.
    if "private void Update(" in suppressor_type_source:
        fail("town billboard donor suppressor must not poll in Update; use Start + LateUpdate reassertion only")
    require_contains(suppressor_type_source, "private void Start()", "town billboard donor suppressor lifecycle")
    require_contains(suppressor_type_source, "private void LateUpdate()", "town billboard donor suppressor LateUpdate reassertion")
    late_update_body = find_method_body(suppressor_type_source, "LateUpdate")
    require_contains(late_update_body, "SuppressDonorRenderers();", "town billboard donor suppressor LateUpdate must only reassert donor suppression")
    require_contains(suppressor_type_source, "SuppressDonorRenderers();", "town billboard donor suppressor lifecycle")
    require_order(
        init_body,
        "ResolveTownBillboardPlacement(__instance, __args, root, citySid)",
        "RememberTownBillboardPlacement(root, citySid, placement)",
        "town billboard init placement memory",
    )

    dwelling_cs = plugin_cs.parent / "Homm3StrongholdDwellingMapBillboard.cs"
    if not dwelling_cs.is_file():
        fail(f"Homm3StrongholdDwellingMapBillboard.cs not found: {dwelling_cs}")
    dwelling_source = dwelling_cs.read_text(encoding="utf-8-sig")
    dwelling_apply_body = find_method_body(dwelling_source, "ApplyResolvedRandomHireDwelling")
    require_contains(
        dwelling_apply_body,
        "PendingRandomHireMapObjectsById.TryGetValue(mapObjectId, out var entry)",
        "dwelling random-hire visual apply",
    )
    require_contains(
        dwelling_apply_body,
        "string.Equals(entry.RawSid, rawSid, StringComparison.Ordinal)",
        "dwelling random-hire visual apply",
    )
    for token in (
        "PendingRandomHireMapObjectsBySid",
        "QueuePendingRandomHireMapObjectBySid",
        "TryTakePendingRandomHireMapObjectBySid",
    ):
        if token in dwelling_source:
            fail(f"dwelling billboard random-hire binding must use exact map-object id, not raw SID queue {token!r}")

    print("custom-town-billboard-contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
