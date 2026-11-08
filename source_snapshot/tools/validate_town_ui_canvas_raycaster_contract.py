#!/usr/bin/env python3
"""Validate the HoMM3 town UI canvas and art-root contracts stay scoped.

Town clickability stays narrow: known CityUI menu canvases that own active
raycastable graphics must carry a GraphicRaycaster. Custom town art mirrors the
CanvasCityPanel render domain (Route A / BhScreen→jj.hqq ScreenSpaceCamera bind)
instead of inventing ScreenSpaceOverlay elevate ladders. Native menus may only
raise sortingOrder when already in a comparable domain. The custom town art root
must stay panel-parented so backdrops and building layers share CanvasCityPanel.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


def fail(message: str) -> None:
    print(f"town-ui-raycaster-contract: {message}", file=sys.stderr)
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

def find_symbol_initializer(source: str, name: str) -> str:
    match = re.search(r"MethodSymbol\s+" + re.escape(name) + r"\s*=\s*new\s*\(", source)
    if not match:
        fail(f"missing MethodSymbol {name}")
    start = match.end()
    end = source.find(");", start)
    if end < 0:
        fail(f"unterminated MethodSymbol {name}")
    return source[start:end]



def find_between(source: str, start_token: str, end_token: str, context: str) -> str:
    start = source.find(start_token)
    if start < 0:
        fail(f"missing {context} start {start_token!r}")
    end = source.find(end_token, start + len(start_token))
    if end < 0:
        fail(f"missing {context} end {end_token!r}")
    return source[start:end]

def require_contains(body: str, token: str, context: str) -> None:
    if token not in body:
        fail(f"{context} must contain {token!r}")

def require_not_contains(body: str, token: str, context: str) -> None:
    if token in body:
        fail(f"{context} must not contain {token!r}")


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
    source = plugin_cs.read_text(encoding="utf-8-sig")
    live_probe_cs = plugin_cs.parent / "Homm3LiveProbeWorkbench.cs"
    if not live_probe_cs.is_file():
        fail(f"Homm3LiveProbeWorkbench.cs not found: {live_probe_cs}")
    live_probe_source = live_probe_cs.read_text(encoding="utf-8-sig")
    game_symbols_cs = plugin_cs.parent / "GameSymbols.cs"
    if not game_symbols_cs.is_file():
        fail(f"GameSymbols.cs not found: {game_symbols_cs}")
    game_symbols_source = game_symbols_cs.read_text(encoding="utf-8-sig")
    unit_preview_hook_cs = plugin_cs.parent / "Homm3ImportUnitPreviewModelHook.cs"
    if not unit_preview_hook_cs.is_file():
        fail(f"Homm3ImportUnitPreviewModelHook.cs not found: {unit_preview_hook_cs}")
    unit_preview_hook_source = unit_preview_hook_cs.read_text(encoding="utf-8-sig")


    hero_profile_symbols_body = find_symbol_initializer(game_symbols_source, "ProfileWindowShown")
    for token in ('"giw"', '"gip"'):
        require_contains(hero_profile_symbols_body, token, "hero profile restored show symbols")
    for token in (
        '"Method_Public_Void_0"',
        '"Method_Public_Virtual_Void_0"',
        '"Method_Public_Virtual_Void_1"',
        '"bkns"',
        '"giz"',
        '"hmh"',
    ):
        require_not_contains(hero_profile_symbols_body, token, "hero profile restored show symbols")
    ensure_body = find_method_body(source, "EnsureLiftedTownCanvasGraphicRaycaster")
    require_contains(ensure_body, "IsKnownCityMenuCanvas(canvas)", "raycaster helper")
    require_contains(ensure_body, "EnsureNativeTownNestedHudRaycaster(canvas)", "nested city HUD must not invent GraphicRaycaster")
    require_contains(ensure_body, "CanvasOwnsActiveRaycastableGraphic(canvas)", "raycaster helper")
    require_contains(ensure_body, "canvas.gameObject.AddComponent<GraphicRaycaster>()", "raycaster helper for separate root menus only")
    require_contains(ensure_body, "raycaster.enabled = true", "raycaster helper")
    require_order(
        ensure_body,
        "IsTransformUnder(canvas.transform, cityPanel.transform)",
        "CanvasOwnsActiveRaycastableGraphic(canvas)",
        "nested HUD must bail before inventing raycasters",
    )

    nested_raycaster_body = find_method_body(source, "EnsureNativeTownNestedHudRaycaster")
    require_contains(nested_raycaster_body, "raycaster.enabled = true", "nested HUD raycaster enable-only")
    require_not_contains(nested_raycaster_body, "AddComponent<GraphicRaycaster>", "nested HUD must not AddComponent GraphicRaycaster")

    known_body = find_method_body(source, "IsKnownCityMenuCanvas")
    require_contains(known_body, "scene.name", "known-canvas guard")
    require_contains(known_body, '"CityUI"', "known-canvas guard")
    require_contains(known_body, "CityMenuCanvasNames.Contains", "known-canvas guard")

    graphic_body = find_method_body(source, "CanvasOwnsActiveRaycastableGraphic")
    for token in (
        "canvas.enabled",
        "canvas.gameObject.activeInHierarchy",
        "graphic.canvas != canvas",
        "graphic.raycastTarget",
        "graphic.gameObject.activeInHierarchy",
    ):
        require_contains(graphic_body, token, "raycastable-graphic guard")

    reassert_body = find_method_body(source, "ReassertKnownCityMenuCanvasRaycasters")
    require_contains(reassert_body, "ForEachCityUiCanvas", "frame reassertion")
    require_contains(reassert_body, "EnsureLiftedTownCanvasGraphicRaycaster", "frame reassertion")
    foreach_city_body = find_method_body(source, "ForEachCityUiCanvas")
    require_contains(foreach_city_body, 'sceneNameFilter: "CityUI"', "CityUI canvas walk")
    foreach_loaded_body = find_method_body(source, "ForEachLoadedSceneCanvas")
    require_contains(foreach_loaded_body, "GetFrameCanvasSnapshot", "loaded-scene canvas walk must reuse per-frame snapshot")
    canvas_snapshot_body = find_method_body(source, "GetFrameCanvasSnapshot")
    require_contains(canvas_snapshot_body, "SceneManager.sceneCount", "frame canvas snapshot")
    require_contains(canvas_snapshot_body, "GetRootGameObjects", "frame canvas snapshot")
    require_contains(canvas_snapshot_body, "GetComponentsInChildren<Canvas>(true)", "frame canvas snapshot")
    require_contains(canvas_snapshot_body, "_frameCanvasSnapshotFrame == frame", "frame canvas snapshot must be frame-cached")

    live_probe_city_scope_body = find_method_body(live_probe_source, "IsCityInteriorSceneName")
    require_contains(live_probe_city_scope_body, "sceneName.StartsWith", "live probe city interior scope")
    require_contains(live_probe_city_scope_body, '"city"', "live probe city interior scope")
    for stale_token in ('"cityHuman"', '"cityHuman2"'):
        if stale_token in live_probe_city_scope_body:
            fail(f"live probe city interior scope must not be Castle-only via {stale_token}")

    reconcile_body = find_method_body(source, "ReconcileCustomTownPresentationForNativePanels")
    require_contains(reconcile_body, "_customTownUiLiftUntilFrame", "panel reconcile")
    require_contains(reconcile_body, "EnsureNativeTownMenusAboveCustomArt", "panel reconcile")
    require_contains(reconcile_body, "ReassertKnownCityMenuCanvasRaycasters", "panel reconcile")
    require_not_contains(reconcile_body, "EnsureNativeTownMenusAboveOverlayArt", "panel reconcile must not keep Overlay elevate owner")
    require_not_contains(
        reconcile_body,
        'EnsureReleaseBuildTreePanelVisibleForActiveNavigation(null, "frame-reconcile-build-tree")',
        "frame reconcile must not scan native city sessions to resurrect the build tree",
    )
    building_session_fbi_body = find_method_body(source, "AfterReleaseCityTownUiRefreshBuildingSessionFbiArg0")
    require_order(
        building_session_fbi_body,
        "ApplyCustomCityBackdrop();",
        'ShowReleaseBuildTreePanelOnlyIfPopulated(__instance, __originalMethod, "building-session-refresh-fbi", allowOpenHiddenPanel: false)',
        "building-session Init refresh must repair only an already-open populated build tree",
    )
    building_session_refresh_body = find_method_body(source, "AfterReleaseCityTownUiRefreshBuildingSession")
    require_order(
        building_session_refresh_body,
        "ApplyCustomCityBackdrop();",
        'ShowReleaseBuildTreePanelOnlyIfPopulated(__instance, __originalMethod, "building-session-refresh", allowOpenHiddenPanel: false)',
        "building-session refresh must repair only an already-open populated build tree",
    )
    require_not_contains(source, 'PatchCityTownMethod(harmony, buildingSessionType, "OnHide", 0, nameof(ModActions.AfterReleaseCityTownUiRefreshBuildingSession))', "building-session OnHide must not resurrect a closing build tree")
    require_not_contains(source, "EnsureReleaseBuildTreePanelVisibleIfSelected", "build-tree recovery must not keep the dormant building-view native session scan helper")
    require_not_contains(source, "EnsureReleaseBuildTreePanelVisibleForActiveNavigation", "build-tree recovery must not keep the dormant active-navigation native session scan helper")
    require_not_contains(source, "ReleaseBuildTreeOpenIntent", "build-tree repair must not use a global intent window")
    require_not_contains(source, "MarkReleaseBuildTreeOpenIntent", "build-tree repair must not use a global intent marker")
    if source.count("allowOpenHiddenPanel: true") != 2:
        fail("build-tree hidden-panel open must be allowed only by the two direct construction navigation handlers")
    if source.count("allowOpenHiddenPanel: false") != 3:
        fail("build-tree generic refresh repair must use the three closed-panel-safe false call sites")
    navigation_selected_body = find_method_body(source, "AfterReleaseCityConstructionNavigationSelected")
    navigation_tab_body = find_method_body(source, "AfterReleaseCityConstructionTabSelected")
    for body, context in (
        (navigation_selected_body, "building navigation selection"),
        (navigation_tab_body, "building tab selection"),
    ):
        require_contains(body, "allowOpenHiddenPanel: true", context + " may open the build tree from direct navigation")
    city_session_build_tree_body = find_method_body(source, "EnsureReleaseBuildTreeVisibleIfSelected")
    require_contains(city_session_build_tree_body, "allowOpenHiddenPanel: false", "city-session refresh must not open a hidden populated build tree")
    building_view_bind_body = find_method_body(source, "AfterReleaseCityTownUiRefreshArg0")
    require_not_contains(building_view_bind_body, "EnsureReleaseBuildTreePanelVisibleIfSelected", "building-view bind/update must not scan native city sessions to recover the build tree")
    building_view_fbi_body = find_method_body(source, "AfterReleaseCityTownUiRefreshFbiArg0")
    require_not_contains(building_view_fbi_body, "EnsureReleaseBuildTreePanelVisibleIfSelected", "building-view bind/update must not scan native city sessions to recover the build tree")
    active_panel_lift_body = find_method_body(source, "LiftActiveReleaseTownPanelCanvas")
    require_contains(active_panel_lift_body, "|| !panelCanvas.enabled", "active panel lift must not resurrect disabled panel shells")
    require_not_contains(active_panel_lift_body, "panelCanvas.enabled = true", "active panel lift must not resurrect disabled panel shells")
    liftable_canvas_body = find_method_body(source, "IsLiftableCustomTownUiCanvas")
    require_contains(liftable_canvas_body, "CityMenuCanvasNames.Contains(name)", "native town menu canvas lift gate")
    require_contains(liftable_canvas_body, "&& canvas.enabled", "native town menu canvas lift must not resurrect disabled panel shells")
    require_order(
        liftable_canvas_body,
        "CityMenuCanvasNames.Contains(name)",
        "&& canvas.enabled",
        "native town menu canvas lift gate",
    )
    native_lift_body = find_method_body(source, "EnsureNativeTownMenusAboveCustomArt")
    for token in (
        "IsActiveSceneCityInterior()",
        "FindCityPanelRectTransform()",
        "Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction)",
        "IsLiftableCustomTownUiCanvas(canvas, cityRoot)",
        "EnsureNativeTownUiCanvasAboveCustomArt(canvas)",
    ):
        require_contains(native_lift_body, token, "native town menu above custom art")
    require_order(
        native_lift_body,
        "IsLiftableCustomTownUiCanvas(canvas, cityRoot)",
        "EnsureNativeTownUiCanvasAboveCustomArt(canvas)",
        "native town menu above custom art",
    )
    require_not_contains(source, "EnsureNativeTownMenusAboveOverlayArt", "must not keep Overlay elevate owner")
    require_not_contains(source, "ApplyLiftedCustomTownUiCanvasPresentation", "must not keep Overlay elevate presentation")


    show_build_tree_body = find_method_body(source, "ShowReleaseBuildTreePanelOnlyIfPopulated")
    require_contains(show_build_tree_body, "if (!allowOpenHiddenPanel && !IsReleaseBuildTreePanelAlreadyOpen(buildingSession))", "build-tree populated native state must not open a hidden panel from generic refresh")
    require_contains(show_build_tree_body, "build-tree-panel-open-suppressed-closed-refresh", "build-tree suppressed auto-open must leave evidence")
    require_order(
        show_build_tree_body,
        "if (!allowOpenHiddenPanel && !IsReleaseBuildTreePanelAlreadyOpen(buildingSession))",
        "RestoreReleaseBuildTreePanelCanvasGroup(buildingSession, source)",
        "build-tree open intent gate",
    )
    already_open_body = find_method_body(source, "IsReleaseBuildTreePanelAlreadyOpen")
    for token in (
        "panelCanvas.enabled",
        "go.activeInHierarchy",
        "group.alpha > 0.01f",
        "group.interactable",
        "group.blocksRaycasts",
    ):
        require_contains(already_open_body, token, "build-tree already-open gate")
    require_contains(show_build_tree_body, "RestoreReleaseBuildTreePanelCanvasGroup(buildingSession, source)", "build-tree CanvasGroup hide must have exact paired restore")
    require_order(
        show_build_tree_body,
        "if (currentViews > 0)",
        "RestoreReleaseBuildTreePanelCanvasGroup(buildingSession, source)",
        "build-tree CanvasGroup restore must precede panel lift",
    )
    require_order(
        show_build_tree_body,
        "RestoreReleaseBuildTreePanelCanvasGroup(buildingSession, source)",
        "EnsureReleaseTownScreenVisible(",
        "build-tree CanvasGroup restore must precede panel lift",
    )
    restore_build_tree_body = find_method_body(source, "RestoreReleaseBuildTreePanelCanvasGroup")
    require_not_contains(restore_build_tree_body, 'FindCanvasByName("BUILDING VIEW PANEL", source)', "build-tree CanvasGroup restore must use the owning building session root")
    require_contains(restore_build_tree_body, "var go = buildingSession == null ? null : buildingSession.gameObject", "build-tree CanvasGroup restore must use the owning session root panel object")
    require_contains(restore_build_tree_body, "go.GetComponent<Canvas>()", "build-tree CanvasGroup restore must use the owning session Canvas")
    require_contains(restore_build_tree_body, "go.GetComponent<CanvasGroup>()", "build-tree CanvasGroup restore must use the owning session root CanvasGroup")
    require_contains(restore_build_tree_body, "panelCanvas.enabled = true", "build-tree CanvasGroup restore must invert exact canvas disable")
    require_contains(restore_build_tree_body, "HideCanvasGroup(group, hide: false)", "build-tree CanvasGroup restore must invert exact hide")
    require_order(
        restore_build_tree_body,
        "panelCanvas.enabled = true",
        "HideCanvasGroup(group, hide: false)",
        "build-tree CanvasGroup restore must enable canvas before root CanvasGroup restore",
    )
    require_not_contains(restore_build_tree_body, "GetComponentsInChildren<CanvasGroup>", "build-tree CanvasGroup restore must not force descendant groups")
    require_contains(
        show_build_tree_body,
        '"build-tree-panel-empty-native-state-no-mutation"',
        "empty native build-tree state must be diagnostic-only",
    )
    require_not_contains(source, "HideReleaseBuildTreePanelShellIfEmpty", "empty native build-tree state must not hide the panel shell")
    require_not_contains(show_build_tree_body, "panelCanvas.enabled = false", "empty native build-tree state must not disable the panel canvas")
    require_not_contains(show_build_tree_body, "HideCanvasGroup(group)", "empty native build-tree state must not hide the panel CanvasGroup")
    require_not_contains(source, '"build-tree-panel-hidden-empty-native-state"', "empty native build-tree state must not use the old hide breadcrumb")

    art_canvas_body = find_method_body(source, "EnsureCustomTownArtCanvas")
    require_contains(art_canvas_body, "ResolveCityPanelSourceCanvas()", "Route A town art canvas resolve")
    require_contains(
        art_canvas_body,
        "IsTransformUnder(canvas.transform, source.transform)",
        "Route A must detect nested canvases under CanvasCityPanel",
    )
    require_contains(art_canvas_body, "canvas.enabled = false", "Route A nested share must disable child Canvas")
    for token in (
        "canvas.renderMode = source.renderMode",
        "canvas.worldCamera = source.worldCamera",
        "canvas.planeDistance = source.planeDistance",
        "canvas.sortingLayerID = source.sortingLayerID",
        "source.sortingOrder + relativeOrder",
    ):
        require_contains(art_canvas_body, token, "Route A orphan town art canvas mirror")
    require_not_contains(art_canvas_body, "RenderMode.ScreenSpaceOverlay", "Route A must not force Overlay on custom town art")
    require_not_contains(art_canvas_body, "canvas.worldCamera = null", "Route A must not clear worldCamera on custom town art")
    require_contains(
        find_method_body(source, "EnsureCityBackdropCanvasOrder"),
        "IsTransformUnder(go.transform, source.transform)",
        "backdrop must share CanvasCityPanel domain when nested",
    )

    presentation_body = find_method_body(source, "EnsureNativeTownUiCanvasAboveCustomArt")
    for token in (
        "ResolveCityPanelSourceCanvas()",
        "GetCustomTownUiTargetSortingOrder(canvas, source)",
        "NormalizeReleaseTooltipOverlayDepth(canvas.transform)",
    ):
        require_contains(presentation_body, token, "native town UI above custom art")
    require_not_contains(presentation_body, "RenderMode.ScreenSpaceOverlay", "native town UI must not force Overlay")
    require_not_contains(presentation_body, "canvas.worldCamera = null", "native town UI must not clear worldCamera")
    tooltip_depth_body = find_method_body(source, "NormalizeReleaseTooltipOverlayDepth")
    for token in (
        "root.GetComponent<RectTransform>()",
        "Math.Abs(local.z) > 0.01f",
        "local.z = 0f",
        "rect.localPosition = local",
        "NormalizeReleaseTooltipOverlayDepth(root.GetChild(i))",
    ):
        require_contains(tooltip_depth_body, token, "tooltip overlay depth normalization")
    for token in (
        "anchoredPosition",
        "anchorMin",
        "anchorMax",
        "pivot",
        "SetAsLastSibling",
        "new Vector2",
    ):
        require_not_contains(tooltip_depth_body, token, "tooltip overlay depth normalization must preserve native x/y placement")
    city_menu_names_body = find_between(
        source,
        "private static readonly HashSet<string> CityMenuCanvasNames",
        "};",
        "city menu canvas ownership",
    )
    for token in (
        '"TOOLTIP UI CANVAS"',
        '"TOOLTIP UI CANVAS RAYCAST"',
        '"TOOLTIP UI CANVAS OVERLAY"',
    ):
        require_not_contains(city_menu_names_body, token, "town menu canvas ownership must not classify tooltip canvases as CityUI menus")
    for token in (
        "GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName",
        "GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName",
        "GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName",
        "GameSymbols.ReleaseTownUi.HireViewPanelCanvasName",
        "GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName",
    ):
        require_contains(city_menu_names_body, token, "city menu canvas ownership must include hire/market/artifact/tavern panels")

    primary_panel_names_body = find_between(
        source,
        "private static readonly string[] ReleaseTownPrimaryPanelCanvasNames",
        "};",
        "primary town panel canvas ownership",
    )
    for token in (
        "GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName",
        "GameSymbols.ReleaseTownUi.HireViewPanelCanvasName",
        "GameSymbols.ReleaseTownUi.UpgradeUnitPanelCanvasName",
        "GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName",
        "GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName",
        "GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName",
        "GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName",
    ):
        require_contains(primary_panel_names_body, token, "primary town panel lift set")

    for token in (
        'internal const string MarketViewPanelCanvasName = "MARKET VIEW"',
        'internal const string ItemMarketPanelCanvasName = "CanvasItemMarket"',
        'internal const string ArtifactChangerPanelCanvasName = "ArtifactChanger"',
        'internal const string HireViewPanelCanvasName = "HIRE VIEW PANEL"',
        'internal const string HeroBuyPanelCanvasName = "CanvasHeroBuying"',
    ):
        require_contains(game_symbols_source, token, "release town UI canvas name symbols")

    nav_panel_body = find_method_body(source, "TryGetReleaseTownPrimaryPanelCanvasName")
    for token in (
        "ECityNavigation.Tavern",
        "GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName",
        "ECityNavigation.Universal",
        "GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName",
    ):
        require_contains(nav_panel_body, token, "navigation tab → primary panel canvas map")

    require_contains(source, "AfterReleaseCityTavernUiShown", "tavern/hero-buy show lift hook")
    require_contains(source, 'GetHexType("Hex.Session.UI.BhHeroBuySession")', "tavern session type registration")
    session_ui_panel_body = find_method_body(source, "IsReleaseTownSessionUiPanelCanvasName")
    require_contains(session_ui_panel_body, "GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName", "sessionUI tavern canvas lift eligibility")

    navigation_lift_body = find_method_body(source, "LiftReleaseTownNavigationTargetPanel")
    require_contains(navigation_lift_body, "TryGetReleaseTownPrimaryPanelCanvasName(navigation)", "navigation panel lift")
    require_contains(navigation_lift_body, "LiftActiveReleaseTownPanelCanvas(panelCanvasName", "navigation panel lift")
    require_contains(navigation_lift_body, "LiftAnyActiveReleaseTownPrimaryPanelCanvas(source)", "navigation panel lift fallback")

    tooltip_canvas_body = find_method_body(source, "IsReleaseTooltipUiCanvas")
    for token in (
        '"tooltipsUI"',
        '"TOOLTIP UI CANVAS"',
        '"TOOLTIP UI CANVAS RAYCAST"',
        '"TOOLTIP UI CANVAS OVERLAY"',
    ):
        require_contains(tooltip_canvas_body, token, "tooltip canvas overlay-depth ownership")

    liftable_body = find_method_body(source, "IsLiftableCustomTownUiCanvas")
    for token in (
        '"CityUI"',
        "CityMenuCanvasNames.Contains(name)",
        "IsCanvasInActiveCityScene(canvas, cityRoot, requireActive: true)",
        "IsReleaseTooltipUiCanvas(canvas)",
        "go.activeInHierarchy",
    ):
        require_contains(liftable_body, token, "liftable custom town UI canvas guard")

    demote_peer_body = find_method_body(source, "DemoteReleaseTownPeerPanelCanvases")
    for token in (
        '"CanvasCityPanel"',
        '"GarnisonPanel"',
        '"CanvasCityTechHUDPanel"',
        '"CityNavigation"',
        "GetReleaseTownActivePanelSortingOrder()",
    ):
        require_contains(demote_peer_body, token, "town peer demotion must not move base/navigation canvases")
    require_order(
        demote_peer_body,
        '"GarnisonPanel"',
        "activeOrder - 20",
        "town peer demotion must skip base canvases before demoting peers",
    )

    sorting_body = find_method_body(source, "GetCustomTownUiTargetSortingOrder")
    require_contains(source, "private const int CustomTownArtToNativeUiGap = 20;", "town relative sorting contract")
    require_contains(source, "private const int ReleaseTownActivePanelOrderGap = 40;", "town relative sorting contract")
    require_contains(source, "private const int ReleaseTownNavigationOrderGap = 60;", "town relative sorting contract")
    require_contains(source, "private const int ReleaseTownTooltipOrderGap = 80;", "town relative sorting contract")
    require_contains(source, "private const int ReleaseTownTooltipRaycastOrderGap = 81;", "town relative sorting contract")
    require_not_contains(source, "ReleaseTownTechHudOrderGap", "must not elevate full-screen CanvasCityTechHUDPanel")
    require_contains(sorting_body, "ReleaseTownTooltipOrderGap", "town tooltip sorting contract")
    require_contains(sorting_body, "ReleaseTownTooltipRaycastOrderGap", "town tooltip sorting contract")
    require_contains(sorting_body, '"CanvasCityPanel"', "town base canvas sorting contract")
    require_contains(sorting_body, '"GarnisonPanel"', "town base canvas sorting contract")
    require_contains(sorting_body, '"CanvasCityTechHUDPanel"', "town tech HUD must stay at floor only")
    require_contains(sorting_body, '"UNIT WINDOW SESSION"', "unit detail preview must clear town art")
    require_order(
        sorting_body,
        '"UNIT WINDOW SESSION"',
        "ReleaseTownActivePanelOrderGap",
        "unit detail preview must use active-panel order",
    )

    native_above_art_body = find_method_body(source, "EnsureNativeTownUiCanvasAboveCustomArt")
    require_contains(native_above_art_body, "canvas.overrideSorting = false", "nested city HUD must clear overrideSorting")
    require_contains(native_above_art_body, "EnsureNativeTownNestedHudRaycaster(canvas)", "nested city HUD raycaster path")
    require_contains(native_above_art_body, '"CanvasCityTechHUDPanel"', "tech HUD must be skipped for forced lifts")
    require_contains(
        native_above_art_body,
        'string.Equals(canvasName, "CanvasCityTechHUDPanel", StringComparison.Ordinal)',
        "tech HUD forced-lift skip must key off canvas name",
    )
    # The skip returns before the overrideSorting=true write used for other menus.
    tech_skip_idx = native_above_art_body.find('string.Equals(canvasName, "CanvasCityTechHUDPanel"')
    override_idx = native_above_art_body.find("canvas.overrideSorting = true")
    if tech_skip_idx < 0 or override_idx < 0 or tech_skip_idx > override_idx:
        fail("tech HUD forced-lift skip must appear before overrideSorting=true write")

    sibling_order_body = find_method_body(source, "EnsureCityPanelNativeHudSiblingOrder")
    require_contains(sibling_order_body, '"GarnisonPanel"', "garrison sibling order above town art")
    require_contains(sibling_order_body, "OfflineUnlockStrongholdTownLayers", "layer root sibling floor")
    require_not_contains(sibling_order_body, "LooksLikeNativeTownMenuOrHud", "sibling order must not reshuffle every city menu child")
    for token in (
        "ReleaseTownActivePanelSortingOrder = 260",
        "ReleaseTownNavigationSortingOrder = 280",
        "ReleaseTownTooltipCanvasSortingOrder = 320",
        "CustomTownNativeUiSortingOrder = 220",
        "CustomTownBackdropSortingOrder = 100",
        "EnsureNativeTownMenusAboveOverlayArt",
        "ApplyLiftedCustomTownUiCanvasPresentation",
        "GetCustomTownUiLiftedSortingOrder",
    ):
        require_not_contains(source, token, "town sorting contract must not restore absolute Overlay elevate ladders")

    liftable_body = find_method_body(source, "IsLiftableCustomTownUiCanvas")
    for body, context in (
        (sorting_body, "town UI sorting must not own session/adventure HUD canvases"),
        (liftable_body, "town UI lift must not own session/adventure HUD canvases"),
    ):
        for token in ("SessionTownHudCanvasSortingOrders", '"sessionHUD"'):
            require_not_contains(body, token, context)
    for token in (
        '"CanvasSideHeroHUDPanel"',
        '"CanvasSideCityHUDPanel"',
        '"CanvasSideTimers"',
        '"CanvasSideMiniMapPanels"',
        '"CanvasResHUDPanel"',
        '"CanvasTechHUDPanel"',
        '"CanvasTechHUDPanel (1)"',
    ):
        require_not_contains(source, token, "town UI source must not hard-code session/adventure HUD canvases")

    heuristic_lift_body = find_method_body(source, "LooksLikeNativeTownMenuOrHud")
    require_contains(heuristic_lift_body, "CityMenuCanvasNames.Contains", "direct town child lift ownership")
    for token in (
        "IndexOf",
        "GetComponentInChildren<Selectable>",
        '"hud"',
        '"resource"',
        '"hero"',
    ):
        require_not_contains(heuristic_lift_body, token, "direct town child lift ownership")

    for token in (
        '"SpellBook"',
        '"MAGIC BOOK"',
        "Resources.FindObjectsOfTypeAll<Canvas>()",
    ):
        if token in liftable_body:
            fail(f"liftable custom town UI canvas guard must not special-case unrelated canvas {token!r}")

    art_root_body = find_method_body(source, "ApplyCustomTownArtRootTransform")
    require_contains(art_root_body, "artRoot.parent != cityPanelRoot", "custom town art root")
    require_contains(art_root_body, "artRoot.SetParent(cityPanelRoot, worldPositionStays: false)", "custom town art root")
    require_contains(art_root_body, "ApplyCustomTownOverlayRect(artRoot)", "custom town art root")
    require_contains(art_root_body, "artRoot.SetSiblingIndex(0)", "custom town art root")
    if "SetParent(null" in art_root_body:
        fail("custom town art root must remain parented to CanvasCityPanel, not detached")

    overlay_body = find_method_body(source, "ApplyCustomTownOverlayRect")
    for token in (
        "rect.anchorMin = Vector2.zero",
        "rect.anchorMax = Vector2.one",
        "rect.anchoredPosition = Vector2.zero",
        "rect.sizeDelta = Vector2.zero",
    ):
        require_contains(overlay_body, token, "custom town overlay rect")
    for token in ("new Vector2(960f, 540f)", "new Vector2(1920f, 1080f)"):
        if token in overlay_body:
            fail(f"custom town overlay rect must stretch to CanvasCityPanel, not hard-code {token}")

    backdrop_body = find_method_body(source, "ApplyCustomCityBackdrop")
    require_contains(backdrop_body, "rect.SetParent(EnsureCustomTownArtRoot(root) ?? root, worldPositionStays: false)", "custom town backdrop image")
    require_contains(backdrop_body, "ApplyCityBackdropTransform(root, rect)", "custom town backdrop image")
    if "ApplyCustomTownOverlayRect(rect)" in backdrop_body:
        fail("custom town backdrop image must use ApplyCityBackdropTransform, not overlay stretch")

    backdrop_image_body = find_method_body(source, "EnsureCityBackdropImage")
    require_contains(backdrop_image_body, "ApplyCityBackdropTransform(root, rect)", "city backdrop image helper")
    if "ApplyCustomTownOverlayRect(rect)" in backdrop_image_body:
        fail("city backdrop image helper must use the same scaled transform as building layers")

    layer_transform_body = find_method_body(source, "ApplyCityBackdropTransformToLayerRoot")
    require_contains(layer_transform_body, "ApplyCityBackdropTransform(root, rect)", "town layer transform helper")
    if "ApplyCustomTownOverlayRect(rect)" in layer_transform_body:
        fail("town layer transform helper must not switch to overlay stretch under the art root")

    forbidden = (
        "ExecuteEvents.Execute",
        "PointerEventData",
        "EventSystem.current.RaycastAll",
        "Physics.Raycast",
        "GetComponentsInChildren<Canvas>(true).ToList",
    )
    for token in forbidden:
        if token in ensure_body:
            fail(f"raycaster helper must not contain broad input fallback {token!r}")


    print("town-ui-raycaster-contract: ok")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
