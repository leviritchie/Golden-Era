#!/usr/bin/env python3

"""Validate selected-unit HUD action-bar cleanup contracts for custom units."""

from __future__ import annotations

from pathlib import Path

import re

ROOT = Path(__file__).resolve().parents[1]

PLUGIN_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

HUD = PLUGIN_DIR / "Homm3ImportBhSelectedUnitHudFix.cs"

GAME_SYMBOLS = PLUGIN_DIR / "GameSymbols.cs"

GAME_INTEROP_TYPES = PLUGIN_DIR / "GameInteropTypes.cs"

CSPROJ = PLUGIN_DIR / "OfflineUnlockMod.csproj"

EMPTY_CATCH = re.compile(r"catch\s*(?:\([^)]*\))?\s*{\s*}")

def fail(message: str) -> None:

    raise SystemExit(f"selected-unit HUD action-bar contract failed: {message}")

def method_body(text: str, signature: str) -> str:

    start = text.find(signature)
    if start < 0:
        fail(f"missing method: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        fail(f"missing method body: {signature}")
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:index]
    fail(f"unterminated method body: {signature}")
    return ""

def require_contains(body: str, needle: str, label: str) -> None:

    if needle not in body:
        fail(f"{label} missing `{needle}`")

def require_order(body: str, first: str, second: str, label: str) -> None:

    first_index = body.find(first)
    second_index = body.find(second)
    if first_index < 0 or second_index < 0 or first_index > second_index:
        fail(f"{label} must evaluate `{first}` before `{second}`")

def reject_empty_catch(body: str, label: str) -> None:

    if EMPTY_CATCH.search(body):
        fail(f"{label} must not use blank catches")

def validate_game_symbols() -> None:

    text = GAME_SYMBOLS.read_text(encoding="utf-8-sig")
    expected = 'internal static readonly string[] AbilityManagerTypeNames =\n\t\t\t{ "dxx", "ObjectPublicObceDiObce2EAInBoInUnique" };'
    normalized = text.replace("\r\n", "\n")
    if expected not in normalized:
        fail("selected-unit HUD ability manager type hints must prefer current runtime dxx before stale generated full name")

def validate_game_interop_types() -> None:

    text = GAME_INTEROP_TYPES.read_text(encoding="utf-8-sig")
    types_match = method_body(text, "internal static bool TypesMatch(Type actual, Type expected)")
    require_contains(types_match, "GameMember.ReadObfuscatedName(actual)", "interop type matching")
    require_contains(types_match, "GameMember.ReadObfuscatedName(expected)", "interop type matching")
    require_contains(types_match, "string.Equals(actualObfuscated, expectedObfuscated, StringComparison.Ordinal)", "interop type matching")
    aliases = method_body(text, "internal static string[] GetNativeTypeAliases(Type expectedType)")
    require_contains(aliases, "TypesMatch(expectedType, ReleaseAbilityManagerType)", "native type aliases")
    require_contains(aliases, "GameSymbols.SelectedUnitHud.AbilityManagerTypeNames", "native type aliases")

def validate_msbuild_hook() -> None:

    text = CSPROJ.read_text(encoding="utf-8-sig")
    require_contains(text, 'Target Name="ValidateSelectedUnitHudActionBarContract" BeforeTargets="BeforeBuild"', "csproj hook")
    require_contains(text, "validate_selected_unit_hud_actionbar_contract.py", "csproj hook")
    require_contains(text, "$(SelectedUnitHudActionBarValidator)", "csproj hook")

def main() -> int:

    validate_msbuild_hook()
    validate_game_symbols()
    validate_game_interop_types()
    text = HUD.read_text(encoding="utf-8-sig")
    for token in (
        "BeginReleaseNativeSidAlias",
        "RestoreSidAlias",
        "AliasReleaseConfigIds",
        "TryAliasReleaseConfigId",
        "SidAliasState",
    ):
        if token in text:
            fail(f"selected-unit HUD source must not contain donor identity alias token `{token}`")
    for signature, label in (
        ("private static bool PrefixBeetRelease", "event selected-HUD custom-SID prefix"),
        ("private static bool PrefixBegsRelease", "direct selected-HUD custom-SID prefix"),
    ):
        prefix = method_body(text, signature)
        require_contains(prefix, "Homm3CustomFactionRegistry.IsCustomUnitSid(sid)", label)
        require_contains(prefix, "var seeded = 0;", label)
        if "SeedAllCustomSidDictionaries" in prefix or "SeedCustomSidDictionaries" in prefix:
            fail(f"{label} must not seed donor dictionaries before native selected-HUD bind")
        require_contains(prefix, "BeginReleaseCustomSidBind(unit, sid)", label)
        require_contains(prefix, "donor identity aliasing disabled", label)
        if "TryGetDonorSid(" in prefix:
            fail(f"{label} must not resolve donor SIDs before native selected-HUD bind")
    for signature, label in (
        # Audit A4 (2026-09-27): finalizers are try/catch shells over *Core.
        ("private static Exception FinalizerBeetReleaseCore", "event selected-HUD custom-SID finalizer"),
        ("private static Exception FinalizerBegsReleaseCore", "direct selected-HUD custom-SID finalizer"),
    ):
        finalizer = method_body(text, signature)
        require_contains(finalizer, "IsReleaseRecoverableCustomSidMiss(__state, sid, eventSid, missingSid)", label)
        require_contains(finalizer, "RecoverUnitControlsRelease", label)

    release_start = text.find("private static bool PrefixBeetRelease")
    release_end = text.find("private static bool PrefixBdon")
    if release_start < 0 or release_end < release_start:
        fail("selected-unit HUD release method region not found")
    release_region = text[release_start:release_end]
    if "WriteUnitSid(" in release_region:
        fail("selected-unit HUD release path must not call WriteUnitSid")
    if "TryGetDonorSid(" in release_region:
        fail("selected-unit HUD release path must not resolve donor SIDs before native bind")
    if "SeedAllCustomSidDictionaries" in release_region or "SeedCustomSidDictionaries" in release_region:
        fail("selected-unit HUD release path must not seed donor dictionaries before native bind")
    require_contains(release_region, "IsReleaseRecoverableCustomSidMiss", "selected-HUD recovery gate")
    if "IsReleaseCustomSidContext" in release_region:
        fail("selected-HUD recovery gate must not suppress unrelated custom-context misses")
    direct_bind = method_body(
        text,
        "private static void DirectBindUnitControlsRelease(BhUnitControlsView controlsView, Unit unit, string sid)",
    )
    if "HideReleaseNoActionBarAbilityViews(controlsView" in direct_bind:
        fail("DirectBindUnitControlsRelease must use ClearReleaseNoActionBarControls, not bare hide")
    require_contains(direct_bind, "IsConclusiveNoReleaseActionBarResult(result)", "DirectBindUnitControlsRelease")
    require_contains(direct_bind, "TryPreserveNativeReleaseControls(controlsView, sid, result.Source ?? \"native-manager-miss\")", "DirectBindUnitControlsRelease")
    finder = method_body(text, "private static ReleaseAbilityArrayResult FindReleaseActionBarAbilities(Unit unit, object manager, string sid)")
    require_contains(finder, "manager:unresolved", "release action-bar native manager lookup")
    require_contains(finder, "manager:none", "release action-bar native manager lookup")
    conclusive = method_body(text, "private static bool IsConclusiveNoReleaseActionBarResult")
    require_contains(conclusive, "manager:none", "conclusive no-action-bar classification")
    require_contains(conclusive, "no-actionbar-abilities", "conclusive no-action-bar classification")
    prefix_beet = method_body(text, "private static bool PrefixBeetRelease")
    prefix_begs = method_body(text, "private static bool PrefixBegsRelease")
    require_order(prefix_beet, "ClearSelectedUnitPortraitOverride(__instance, sid, \"release-beet-prefix-native\");", "ClearCachedReleaseControls();", "release beet native bind must disarm custom hotkey cache")
    require_order(prefix_beet, "ClearCachedReleaseControls();", "return true;", "release beet native bind must return to native after disarming custom hotkey cache")
    require_order(prefix_begs, "ClearSelectedUnitPortraitOverride(__instance, sid, \"release-begs-prefix-native\");", "ClearCachedReleaseControls();", "release begs native bind must disarm custom hotkey cache")
    require_order(prefix_begs, "ClearCachedReleaseControls();", "return true;", "release begs native bind must return to native after disarming custom hotkey cache")
    hotkey = method_body(text, "private static bool PrefixReleaseControlsViewHotkey")
    require_contains(hotkey, "IsReleaseHotkeyControlsContext(__instance)", "release hotkey custom context")
    require_contains(hotkey, "FindReleaseHotkeyView(__instance, __1.idButton)", "release hotkey slot lookup")
    require_contains(hotkey, "InvokeReleaseControlsClick(__instance, releaseView)", "release hotkey must activate through native controls click path")
    if "InvokeReleaseControlsSelect(__instance" in hotkey:
        fail("release hotkey path must not only sync selected ability state; it must use the native controls click path")
    hotkey_click = method_body(text, "private static void InvokeReleaseControlsClick")
    require_contains(hotkey_click, "FindReleaseControlsClickMethods(controlsView.GetType())", "release hotkey native click invocation")
    require_contains(hotkey_click, "methods[0].Invoke(controlsView, new object[] { view })", "release hotkey native click invocation")
    hotkey_context = method_body(text, "private static bool IsReleaseHotkeyControlsContext")
    require_contains(hotkey_context, "ReferenceEquals(controlsView, _lastBoundReleaseControlsView)", "release hotkey custom context")
    require_contains(hotkey_context, "IsSameCachedReleaseControlsSid(_lastBoundReleaseControlsSid)", "release hotkey custom context")
    if "CachedReleaseControlsAlreadyBound" in hotkey_context:
        fail("release hotkey context must not require full recovered-control equality before slot handling")
    hotkey_contains = method_body(text, "private static bool ReleaseHotkeyControlsContainAbility")
    require_contains(hotkey_contains, "ReleaseControlsContainAbility(controlsView, ability)", "release hotkey ability membership")
    require_contains(hotkey_contains, "CachedReleaseControlsContainAbility(controlsView, ability)", "release hotkey ability membership")
    cleanup = method_body(text, "private static int ClearReleaseNoActionBarControls")
    for needle, label in [
        ("ClearCachedReleaseControls();", "no-action cleanup"),
        ("ClearReleaseAbilityViewState(controlsView, sid);", "no-action cleanup"),
        ("TryClearReleaseControlsSelectedViewField", "no-action cleanup"),
        ("var hidden = HideReleaseNoActionBarAbilityViews(controlsView, sid, source);", "no-action cleanup"),
        ("hidden += ClearSelectedBattleActionBarAbilityViews(sid, source);", "no-action cleanup"),
        ("controlsView.Clear();", "no-action cleanup"),
        ("LogReleaseNoAbilityCleanupWarning(sid, \"native controls clear\", ex);", "no-action cleanup"),
        ("InvokeReleaseControlsClickEnabled(controlsView, false);", "no-action cleanup"),
        ("LogReleaseNoAbilityCleanupWarning(sid, \"click disable\", ex);", "no-action cleanup"),
        ("Homm3CustomUiIconHook.ClearBattleAbilityIconsIn(controlsView);", "no-action cleanup"),
        ("hidden += HideReleaseNoActionBarAbilityViews(controlsView, sid, source);", "no-action cleanup"),
        ("hidden += ClearSelectedBattleActionBarAbilityViews(sid, source);", "no-action cleanup"),
        ("return hidden;", "no-action cleanup"),
    ]:
        require_contains(cleanup, needle, label)
    reject_empty_catch(cleanup, "no-action cleanup")
    first_selected_clear = cleanup.find("ClearSelectedBattleActionBarAbilityViews(sid, source)")
    native_clear = cleanup.find("controlsView.Clear();")
    second_selected_clear = cleanup.find("ClearSelectedBattleActionBarAbilityViews(sid, source)", native_clear)
    if first_selected_clear < 0 or native_clear < 0 or second_selected_clear < 0:
        fail("no-action cleanup must clear selected battle action-bar views before and after native Clear")
    if not first_selected_clear < native_clear < second_selected_clear:
        fail("selected battle action-bar cleanup must run on both sides of native controls clear")
    require_contains(text, "SelectedBattleActionBarAbilityPathFragment", "selected battle action-bar cleanup")
    require_contains(text, "BattleBottomHudCanvas/BottomGroupPanel/UNITPart/UNIT ABILITIES/", "selected battle action-bar cleanup")
    battle_cleanup = method_body(text, "private static int ClearSelectedBattleActionBarAbilityViews")
    for needle, label in [
        ("Resources.FindObjectsOfTypeAll<BhUnitAbilityView>()", "selected battle action-bar cleanup"),
        ("path.IndexOf(SelectedBattleActionBarAbilityPathFragment, StringComparison.Ordinal) < 0", "selected battle action-bar cleanup"),
        ("ClearReleaseAbilityViewState(view, sid);", "selected battle action-bar cleanup"),
        ("Homm3CustomUiIconHook.ClearBattleAbilityIconsIn(view);", "selected battle action-bar cleanup"),
        ("go.SetActive(false);", "selected battle action-bar cleanup"),
        ("LogReleaseNoAbilityCleanupWarning(sid, \"selected battle action-bar ability cleanup\", ex);", "selected battle action-bar cleanup"),
    ]:
        require_contains(battle_cleanup, needle, label)
    reject_empty_catch(battle_cleanup, "selected battle action-bar cleanup")
    controls_cleanup = method_body(text, "private static void ClearReleaseAbilityViewState(BhUnitControlsView controlsView, string sid)")
    require_contains(controls_cleanup, "LogReleaseNoAbilityCleanupWarning(sid, \"ability view list cleanup\", ex);", "controls cleanup")
    reject_empty_catch(controls_cleanup, "controls cleanup")
    view_cleanup = method_body(text, "private static void ClearReleaseAbilityViewState(BhUnitAbilityView view, string sid)")
    for needle, label in [
        ("RememberReleaseAbilityViewAbility(view, null);", "view cleanup"),
        ("AbilityViewEnabledByInstanceId.Remove", "view cleanup"),
        ("LogReleaseNoAbilityCleanupWarning(sid, \"ability view enabled-state cleanup\", ex);", "view cleanup"),
        ("GameInteropTypes.ReleaseAbilityWrapperType", "view cleanup"),
        ("GameSymbols.SelectedUnitHud.AbilityViewAbilityFields", "view cleanup"),
        ("!TrySetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewAbilityFields, abilityType, null)", "view cleanup"),
        ("LogReleaseNoAbilityCleanupWarning(sid, \"ability view native wrapper field cleanup\", null);", "view cleanup"),
    ]:
        require_contains(view_cleanup, needle, label)
    reject_empty_catch(view_cleanup, "view cleanup")
    warning = method_body(text, "private static void LogReleaseNoAbilityCleanupWarning")
    require_contains(warning, "Plugin.LogSource?.LogWarning", "cleanup warning")
    helper_start = text.find("private static int ClearReleaseNoActionBarControls")
    helper_end = text.find("private static void ClearReleaseAbilityViewState(BhUnitControlsView", helper_start)
    bare_hide_sites = [m.start() for m in re.finditer(r"HideReleaseNoActionBarAbilityViews\(controlsView", text)]
    if len(bare_hide_sites) != 2 or any(site < helper_start or site >= helper_end for site in bare_hide_sites):
        fail("HideReleaseNoActionBarAbilityViews must only be called from ClearReleaseNoActionBarControls")
    print("selected-unit HUD action-bar contract OK")
    return 0

if __name__ == "__main__":

    raise SystemExit(main())