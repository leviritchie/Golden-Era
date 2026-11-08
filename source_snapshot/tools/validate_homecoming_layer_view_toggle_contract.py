#!/usr/bin/env python3
"""Validate the HoMM3 two-view layered-atlas native view-toggle source contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"missing required file: {path}")
        return ""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def extract_symbols_block(symbols: str, errors: list[str]) -> str:
    m = re.search(r"internal static (?:partial )?class HomecomingLayerViewToggle\b", symbols)
    start = m.start() if m else -1
    if start < 0:
        errors.append("GameSymbols.cs missing HomecomingLayerViewToggle symbol block")
        return ""
    m = re.compile(r"internal static (?:partial )?class TerrainMaterial\b").search(symbols, start)
    end = m.start() if m else -1
    if end < 0:
        errors.append("GameSymbols.cs missing TerrainMaterial marker after HomecomingLayerViewToggle block")
        return symbols[start:]
    return symbols[start:end]


def require_method_symbol(symbols_block: str, symbol_name: str, symbol_id: str, name_hint: str, errors: list[str]) -> None:
    marker = f"internal static readonly MethodSymbol {symbol_name} = new("
    start = symbols_block.find(marker)
    if start < 0:
        errors.append(f"GameSymbols.HomecomingLayerViewToggle missing MethodSymbol: {symbol_name}")
        return
    end = symbols_block.find(");", start)
    if end < 0:
        errors.append(f"GameSymbols.HomecomingLayerViewToggle MethodSymbol is unterminated: {symbol_name}")
        return
    block = symbols_block[start:end]
    quoted_id = f'"{symbol_id}"'
    quoted_name = f'"{name_hint}"'
    id_pos = block.find(quoted_id)
    name_pos = block.find(quoted_name)
    require(id_pos >= 0, f"GameSymbols.HomecomingLayerViewToggle.{symbol_name} missing id: {symbol_id}", errors)
    require(name_pos >= 0, f"GameSymbols.HomecomingLayerViewToggle.{symbol_name} missing name hint: {name_hint}", errors)
    require(0 <= id_pos < name_pos, f"GameSymbols.HomecomingLayerViewToggle.{symbol_name} must pair id {symbol_id} with name hint {name_hint}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugin-dir", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    plugin_dir = (args.plugin_dir or (repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod")).resolve()
    source_path = plugin_dir / "Homm3HomecomingLayerViewToggle.cs"
    symbols_path = plugin_dir / "GameSymbols.cs"
    plugin_path = plugin_dir / "Plugin.cs"
    csproj_path = plugin_dir / "OfflineUnlockMod.csproj"
    asset_root = plugin_dir / "homm3_adventure_ui" / "layer_toggle"

    errors: list[str] = []
    source = read_text(source_path, errors)
    symbols = read_text(symbols_path, errors)
    plugin = read_text(plugin_path, errors)
    csproj = read_text(csproj_path, errors)
    symbols_block = extract_symbols_block(symbols, errors) if symbols else ""

    require('LogPrefix = "HOMM3_HOMECOMING_LAYER_VIEW_TOGGLE"' in source, "toggle source must keep the exact log prefix", errors)
    require('ClassInjector.RegisterTypeInIl2Cpp<Homm3HomecomingLayerViewToggleBehaviour>()' in source, "toggle must register its IL2CPP MonoBehaviour host", errors)
    require('new GameObject(GoName)' in source, "toggle must attach a persistent GameObject host", errors)
    require('UnityObject.DontDestroyOnLoad(go)' in source, "toggle host must survive scene loads", errors)
    require('TryValidateLayeredMapContract' in source, "toggle must validate the layered map contract before mutating native state", errors)
    require('TryValidateLayeredMapContract(mapData, fileMapName, out var views, out targetMapSeen, out reason)' in source, "toggle must classify layered atlas maps by native view shape instead of a fixed map SID", errors)
    require('views.Length != 2' in source, "toggle must require exactly two native views", errors)
    require('ViewHasRole(surface, "surface", false, -1)' in source, "toggle must validate the surface view role", errors)
    require('ViewHasRole(underground, "underground", true, -1)' in source, "toggle must validate the underground view role", errors)
    require('surface.secSizeX <= 0 || surface.secSizeZ <= 0' in source, "toggle must reject invalid native view sizes", errors)
    require('surface.minSecX != 0 || surface.minSecZ != 0' in source, "toggle must require the surface atlas view to start at the native origin", errors)
    require('underground.minSecX != surface.minSecX + surface.secSizeX || underground.minSecZ != surface.minSecZ' in source, "toggle must require a horizontal surface/underground atlas layout", errors)
    require('underground.secSizeX != surface.secSizeX || underground.secSizeZ != surface.secSizeZ' in source, "toggle must require same-sized surface and underground views", errors)
    require('GameMember.FindFirstMethodByNames' in source, "toggle must resolve native methods through centralized symbol names", errors)
    require('ButtonTopOffset = 56f' in source, "toggle button must sit below the native top-right menu button", errors)
    require('ButtonTopOffset * (UiScale() / DisplayMultiplier)' in source, "toggle button rect must scale the non-overlap top offset with resolution", errors)
    require('NativeButtonPixels = 32f' in source, "toggle must use the native HoMM3 32px IAM button size", errors)
    require('ReferenceHeight = 1080f' in source, "toggle must scale IAM buttons against a 1080p reference height", errors)
    require('DisplayMultiplier = 2f' in source, "toggle must render IAM buttons at a readable modern display multiplier", errors)
    require('UiScale()' in source, "toggle must expose a resolution-dependent UI scale", errors)
    require('IsAdventureHudVisible()' in source, "toggle must gate drawing on adventure HUD visibility so menu exits clean up", errors)
    require('SessionHudSceneName = "sessionHUD"' in source, "toggle adventure HUD gate must require the sessionHUD scene", errors)
    require('AdventureHudCanvasName = "CanvasTechHUDPanel"' in source, "toggle adventure HUD gate must require the adventure HUD canvas", errors)
    require('AssetRoot = "homm3_adventure_ui/layer_toggle"' in source, "toggle must load IAM frames from the curated adventure UI folder", errors)
    require('FilterMode.Point' in source, "toggle IAM textures must use point filtering", errors)
    require('showUndergroundIcon = state.CurrentIndex == Homm3HomecomingLayerViewToggle.SurfaceIndex' in source, "toggle must show the destination-layer IAM icon (HoMM3 elevation UX)", errors)
    require('evt.type == EventType.MouseDown' in source, "toggle must handle mouse-down directly instead of relying only on GUI.Button MouseUp", errors)
    require('&& evt.button == 0' in source, "toggle must only handle primary-button clicks", errors)
    require('&& hovering' in source, "toggle click handling must hit-test the drawn button rect", errors)
    require('evt.Use();' in source, "toggle must consume the handled click event", errors)
    require('LogButtonClick(evt.mousePosition);' in source, "toggle must log native button clicks for live runtime proof", errors)
    require('TryToggleLayer(out var toggleReason)' in source, "toggle direct click path must call the native layer toggle", errors)
    require('GUI.DrawTexture(rect, texture, ScaleMode.StretchToFill, true);' in source, "toggle must draw the HoMM3 IAM button texture after direct click handling", errors)
    require('GUI.Button(' not in source, "toggle must not draw the old text GUI.Button", errors)
    require('Layer: ' not in source, "toggle must not use the old text Layer label", errors)

    click_pos = source.find('evt.type == EventType.MouseDown')
    use_pos = source.find('evt.Use();')
    log_click_pos = source.find('LogButtonClick(evt.mousePosition);')
    toggle_click_pos = source.find('TryToggleLayer(out var toggleReason)')
    draw_pos = source.find('GUI.DrawTexture(rect, texture, ScaleMode.StretchToFill, true);')
    require(0 <= click_pos < use_pos < log_click_pos < toggle_click_pos < draw_pos, "toggle click event must be consumed and dispatched before the button is drawn", errors)
    require('InvokeSetCurrentView(state, targetIndex);' in source, "toggle must set the native current view index", errors)
    require('TryReadViewCount(viewState, getViewCount, out var viewCount, out reason)' in source, "toggle must read the native view-state count", errors)
    require('viewCount != views.Length' in source, "toggle must reject a native view-state count mismatch before calling the camera", errors)
    require('ViewCount = viewCount' in source, "toggle state must carry the validated native view-state count", errors)
    require('InvokeMoveCameraBetweenViews(state, state.CurrentIndex, targetIndex);' in source, "toggle must reframe the native camera by old and target view indexes", errors)
    require('InvokeSetCurrentView(state, state.CurrentIndex);' in source, "toggle must roll back the native view index if camera movement throws", errors)

    set_pos = source.find('InvokeSetCurrentView(state, targetIndex);')
    move_pos = source.find('InvokeMoveCameraBetweenViews(state, state.CurrentIndex, targetIndex);')
    require(set_pos >= 0 and move_pos >= 0 and set_pos < move_pos, "native view index must be set before the camera reframe call", errors)

    for forbidden in [
        "MapViewChange",
        "hjz",
        "msq",
        "TryReadCurrentMapData",
        "Homm3HomecomingWaterTraversalBridge",
        "homm3_homecoming_layer_view_toggle.flag",
        "InvokeMoveCameraToViewCenter",
        "ViewCenterCellX",
        "ViewCenterCellZ",
        "WorldCameraMoveToMapCell",
        "moveToMapCell",
        "centerCell=",
        "ExpectedView",
        "ExpectedSurfaceView",
        "ExpectedUndergroundView",
        "GameSymbols.HomecomingLayerViewToggle.MapSid",
    ]:
        require(forbidden not in source, f"toggle source must not use forbidden or diagnostic-only path: {forbidden}", errors)

    required_symbol_tokens = [
        'WorldCameraTypeHints = { "Hex.BhWorldCamera" }',
        '{ "fileMapName" }',
        '{ "views" }',
    ]
    for token in required_symbol_tokens:
        require(token in symbols_block, f"GameSymbols.HomecomingLayerViewToggle missing token: {token}", errors)
    require("MapSid" not in symbols_block, "GameSymbols.HomecomingLayerViewToggle must not hard-code a single map SID", errors)

    required_method_symbols = [
        ("WorldCameraSingleton", "homecoming.layerViewToggle.worldCamera.singleton", "Method_Public_Static_get_BhWorldCamera_PDM_0"),
        ("WorldCameraCurrentMap", "homecoming.layerViewToggle.worldCamera.currentMap", "Method_Public_Map_0"),
        ("WorldCameraMoveBetweenViews", "homecoming.layerViewToggle.worldCamera.moveBetweenViews", "Method_Public_Void_Int32_Int32_0"),
        ("MapData", "homecoming.layerViewToggle.map.mapData", "Method_Public_get_MapData_0"),
        ("MapViewState", "homecoming.layerViewToggle.map.viewState", "Method_Public_get_ObjectPublicLi1MabvInbvInbvInbvUnique_0"),
        ("CurrentViewIndexGetter", "homecoming.layerViewToggle.viewState.currentIndex.getter", "Method_Public_Int32_0"),
        ("ViewCountGetter", "homecoming.layerViewToggle.viewState.viewCount.getter", "Method_Public_Int32_1"),
        ("CurrentViewIndexSetter", "homecoming.layerViewToggle.viewState.currentIndex.setter", "Method_Public_Void_Int32_1"),
    ]
    for symbol_name, symbol_id, name_hint in required_method_symbols:
        require_method_symbol(symbols_block, symbol_name, symbol_id, name_hint, errors)
    for forbidden in ['"his"', '"hjs"', '"hju"', '"oex"', '"oez"', '"osm"', '"oso"', "MapViewChange", "hjz", "msq"]:
        require(forbidden not in symbols_block, f"GameSymbols.HomecomingLayerViewToggle must not include stale or alternate view toggle token: {forbidden}", errors)

    call = 'Homm3HomecomingLayerViewToggleBootstrap.Ensure(Log);'
    inspector = 'Homm3UiInspectorOverlayBootstrap.Ensure();'
    live_probe_gate = '#if !RELEASE_CANDIDATE_BUILD'
    require(call in plugin, "Plugin.cs must attach the Homecoming layer view toggle host", errors)
    if call in plugin and inspector in plugin and live_probe_gate in plugin:
        require(plugin.index(inspector) < plugin.index(call) < plugin.index(live_probe_gate), "toggle host should attach after optional UI inspector and before diagnostic-only live-probe gates", errors)

    require('ValidateHomecomingLayerViewToggleContract' in csproj, "OfflineUnlockMod.csproj must run the layer view-toggle validator", errors)
    require('validate_homecoming_layer_view_toggle_contract.py' in csproj, "OfflineUnlockMod.csproj must reference the layer view-toggle validator script", errors)
    require('DeployHomm3AdventureUi' in csproj or 'homm3_adventure_ui' in csproj, "OfflineUnlockMod.csproj must deploy the HoMM3 adventure UI layer-toggle assets", errors)
    require('homm3_adventure_ui\\layer_toggle' in csproj or 'homm3_adventure_ui/layer_toggle' in csproj, "OfflineUnlockMod.csproj must deploy curated layer_toggle frames", errors)

    required_frames = [
        asset_root / "surface" / "00_00.png",
        asset_root / "surface" / "00_01.png",
        asset_root / "surface" / "00_03.png",
        asset_root / "underground" / "00_00.png",
        asset_root / "underground" / "00_01.png",
        asset_root / "underground" / "00_03.png",
        asset_root / "manifest.json",
    ]
    for frame in required_frames:
        require(frame.is_file(), f"missing curated IAM layer-toggle asset: {frame}", errors)

    extract_script = repo_root / "tools" / "extract_homm3_layer_toggle_buttons.py"
    require(extract_script.is_file(), f"missing IAM layer-toggle extract script: {extract_script}", errors)

    if errors:
        print("Homecoming layer view-toggle contract validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Homecoming layer view-toggle contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
