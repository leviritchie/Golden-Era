#!/usr/bin/env python3
"""Source/static gate for native-hook safety contracts fixed by the 2026-09-27 mod audit.

Checks (each names the audit item it guards):

* A2 sprite resolver: `Homm3CustomUiIconHook.PrefixSpriteResolver` runs inside native
  `Method_Public_Sprite_String_0`. It must wrap its body in try/catch, must not contain a
  `throw`, and its core must not contain a `throw` either. The building-icon cache must map
  the native `_BP` blueprint key explicitly.
* A4 selected-unit HUD: the release `BhSelectedUnitHud` finalizers run inside native handlers.
  Each must wrap its core in try/catch and never throw; the recoverable-miss rule must cover
  the whole custom-sid class (missing key is any custom unit sid), not only the bound sid.
* A6 battle-local law state: state stored through one IL2CPP proxy and read through another
  must key by native identity. `Homm3BattleLocalLawState*` and `Homm3TrainingDamageLawRuntime`
  must not declare `ConditionalWeakTable<object, ...>` tables, must use `Homm3NativeKeyedTable`,
  and the battle cleanup must clear those tables (native pointers are reused).
* A3 Focus energy: the live energy manager field, grant and spend methods are pinned by exact
  interop name (GameAssembly disasm evidence in GameSymbols), and spend passes a negative delta.
* A5 hero map visuals: native map views (ets) cache child renderers (bep List<Renderer>) for the
  selection outline, so mod hero visuals are parked (deactivated, reused), never destroyed.

Proof tier: source/static only. Runtime behaviour is not proven by this gate.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLUGIN_DIR = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"


def method_body(source: str, signature_regex: str) -> str | None:
    match = re.search(signature_regex, source)
    if not match:
        return None
    start = source.find("{", match.end())
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return None


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def check_sprite_resolver(plugin: Path, errors: list[str]) -> None:
    hook = (plugin / "Homm3CustomUiIconHook.cs").read_text(encoding="utf-8")
    outer = method_body(hook, r"private static bool PrefixSpriteResolver\(")
    core = method_body(hook, r"private static bool PrefixSpriteResolverCore\(")
    if outer is None:
        errors.append("A2: PrefixSpriteResolver not found")
        return
    outer_code = strip_comments(outer)
    if "try" not in outer_code or "catch (Exception" not in outer_code:
        errors.append("A2: PrefixSpriteResolver must wrap its body in try/catch (Exception)")
    if re.search(r"\bthrow\b", outer_code):
        errors.append("A2: PrefixSpriteResolver must never throw into native Method_Public_Sprite_String_0")
    if core is None:
        errors.append("A2: PrefixSpriteResolverCore not found")
    elif re.search(r"\bthrow\b", strip_comments(core)):
        errors.append("A2: PrefixSpriteResolverCore must decline (return true) instead of throwing")
    cache = (plugin / "Homm3StrongholdBuildingIconSpriteCache.cs").read_text(encoding="utf-8")
    if 'BlueprintSuffix = "_BP"' not in cache:
        errors.append("A2: Homm3StrongholdBuildingIconSpriteCache must map the native '_BP' blueprint key explicitly")


def check_selected_unit_hud_finalizers(plugin: Path, errors: list[str]) -> None:
    source = (plugin / "Homm3ImportBhSelectedUnitHudFix.cs").read_text(encoding="utf-8")
    for name in ("FinalizerBeetRelease", "FinalizerBegsRelease"):
        outer = method_body(source, r"private static Exception " + name + r"\(")
        core = method_body(source, r"private static Exception " + name + r"Core\(")
        if outer is None or core is None:
            errors.append("A4: " + name + " and " + name + "Core must both exist")
            continue
        outer_code = strip_comments(outer)
        if "catch (Exception" not in outer_code or (name + "Core(") not in outer_code:
            errors.append("A4: " + name + " must call its Core inside try/catch (Exception)")
        for label, body in ((name, outer_code), (name + "Core", strip_comments(core))):
            if re.search(r"\bthrow\b", body):
                errors.append("A4: " + label + " must never throw into native BhSelectedUnitHud")
    rule = method_body(source, r"private static bool IsReleaseRecoverableCustomSidMiss\(")
    if rule is None:
        errors.append("A4: IsReleaseRecoverableCustomSidMiss not found")
    else:
        code = strip_comments(rule)
        if "OriginalSid)" in code and "string.Equals(missingSid" in code:
            errors.append("A4: IsReleaseRecoverableCustomSidMiss must not narrow recovery to the HUD's bound sid")
        if "IsCustomUnitSid(missingSid)" not in code:
            errors.append("A4: IsReleaseRecoverableCustomSidMiss must accept any custom unit sid as the missing key")


A6_FILES = (
    "Homm3BattleLocalLawState.cs",
    "Homm3BattleLocalLawState.RuntimeMechanics.cs",
    "Homm3BattleLocalLawState.DirectState.cs",
    "Homm3TrainingDamageLawRuntime.cs",
)


def check_battle_local_native_keys(plugin: Path, errors: list[str]) -> None:
    for name in A6_FILES:
        code = strip_comments((plugin / name).read_text(encoding="utf-8"))
        if re.search(r"ConditionalWeakTable\s*<\s*object\s*,", code):
            errors.append("A6: " + name + " must key battle-local state by native identity, not ConditionalWeakTable<object, ...>")
        if re.search(r"ReferenceEquals\s*\(\s*(?:state\.|unitState\.|lawState\.|Volatile\.Read|receiver\b)", code):
            errors.append("A6: " + name + " compares IL2CPP proxies with ReferenceEquals; use Homm3NativeIdentity.Same")
    state = strip_comments((plugin / "Homm3BattleLocalLawState.cs").read_text(encoding="utf-8"))
    for table in ("UnitDamageStates", "LawOwnerStates"):
        if not re.search(r"Homm3NativeKeyedTable<\w+>\s+" + table + r"\b", state):
            errors.append("A6: " + table + " must be a Homm3NativeKeyedTable")
    clear = method_body(state, r"internal static void ClearBattleSideIndexedState\(")
    for call in ("UnitDamageStates.Clear()", "LawOwnerStates.Clear()", "Homm3TrainingDamageLawRuntime.ClearBurningAshForBattle()"):
        if clear is None or call not in clear:
            errors.append("A6: ClearBattleSideIndexedState must call " + call)
    training = strip_comments((plugin / "Homm3TrainingDamageLawRuntime.cs").read_text(encoding="utf-8"))
    if not re.search(r"Homm3NativeKeyedTable<BurningAshState>\s+BurningAshByTarget\b", training):
        errors.append("A6: BurningAshByTarget must be a Homm3NativeKeyedTable")


def check_focus_energy_members(plugin: Path, errors: list[str]) -> None:
    """A3: live Golden Era energy members are pinned by exact interop name (disasm-proven)."""
    symbols = (plugin / "GameSymbols.cs").read_text(encoding="utf-8")
    for needle in (
        '"field_Public_ObjectPublicIncgInObcgObIncgIncgUnique_0"',
        '"law.focus.energyManager.grantEnergy",\n\t\t\t"bdwy",\n\t\t\t"Method_Public_Void_Int32_0"',
        '"directState.focus.spend",\n\t\t\t"bdwx",\n\t\t\t"Method_Public_Void_Int32_1"',
    ):
        if needle not in symbols.replace("\r\n", "\n"):
            errors.append("A3: GameSymbols must pin the live energy member " + needle.split("\n")[0])
    adapter = strip_comments((plugin / "Homm3FocusNativeAdapter.cs").read_text(encoding="utf-8"))
    spend = method_body(adapter, r"internal static bool TrySpendFocusFromSide\(")
    if spend is None or "new object[] { -amount }" not in spend:
        errors.append("A3: TrySpendFocusFromSide must pass -amount (native spend takes a signed delta; native callers negate the cost)")
    grant = method_body(adapter, r"internal static bool TryGrantFocusToSide\(")
    if grant is None or "ResolveExactVoidIntMethod(" not in grant:
        errors.append("A3: TryGrantFocusToSide must resolve the grant method by exact name only")


def check_hero_map_visual_parking(plugin: Path, errors: list[str]) -> None:
    """A5: mod renderers under a native hero map view are parked (hidden), never destroyed."""
    hook = (plugin / "Homm3HeroMapSpriteHook.cs").read_text(encoding="utf-8")
    for signature in (
        r"private static void RemoveAttachedVisual\(",
        r"private static bool ApplySprite\(",
        r"private static void ParkAttachedVisual\(",
        r"private static GameObject AcquireVisualRoot\(",
    ):
        body = method_body(hook, signature)
        if body is None:
            errors.append("A5: Homm3HeroMapSpriteHook is missing " + signature.split(" ")[-1].rstrip("\\("))
            continue
        if re.search(r"\bDestroy(?:Immediate)?\s*\(", strip_comments(body)):
            errors.append("A5: " + signature.split(" ")[-1].rstrip("\\(") + " must park mod visuals, not destroy renderers the native bep outline cache may hold")


def check_army_strip_hero_arg_refresh(plugin: Path, errors: list[str]) -> None:
    """A7: the hero-arg HUD refresh is pinned to the live session-hero method and type-checked."""
    symbols = (plugin / "GameSymbols.cs").read_text(encoding="utf-8").replace("\r\n", "\n")
    needle = (
        '"importVisuals.armyStrip.heroHud.heroArgRefresh",\n\t\t\t'
        '"Method_Private_Void_ObjectPublicHeObInObciSiObVeSeObUnique_0",\n\t\t\t"vty");'
    )
    if needle not in symbols:
        errors.append("A7: HeroHudPanelHeroArgRefresh must pin Method_Private_Void_ObjectPublicHeObInObciSiObVeSeObUnique_0 / vty (stale vso binds junk type ObjectPublicVo2)")
    hud = strip_comments((plugin / "Homm3FactorySplitAssemblyArmyStripHud.cs").read_text(encoding="utf-8"))
    if "IsSessionHeroParameterType(heroArgRefresh.GetParameters()[0].ParameterType)" not in hud:
        errors.append("A7: the hero-arg refresh patch must require the session hero parameter type")
    if "SessionHeroTypeHints" not in hud:
        errors.append("A7: IsSessionHeroParameterType must match GameSymbols.HeroMap.SessionHeroTypeHints")
    if "hero-arg refresh not patched" not in hud:
        errors.append("A7: a rejected hero-arg refresh must be logged, not skipped silently")


def check_swashbuckler_gold_add(plugin: Path, errors: list[str]) -> None:
    """B1: the gold add is pinned by exact live name; the same-shape _1 sibling is a SET."""
    symbols = (plugin / "GameSymbols.cs").read_text(encoding="utf-8").replace("\r\n", "\n")
    needle = '"homm3.swashbuckler.gold.addResource",\n\t\t\t"Method_Public_Void_String_Int32_0",'
    if needle not in symbols:
        errors.append("B1: SwashbucklerGold.AddResource must pin Method_Public_Void_String_Int32_0 first (disasm: _0 adds, _1 sets)")
    hook = strip_comments((plugin / "Homm3SwashbucklerGoldHook.cs").read_text(encoding="utf-8"))
    if "GameMember.FindFirstMethodByNames(" not in hook or "SwashbucklerGold.AddResource" not in hook:
        errors.append("B1: Homm3SwashbucklerGoldHook must resolve AddResource by exact name")
    if "GameMember.FindFirstMethod(" in hook:
        errors.append("B1: Homm3SwashbucklerGoldHook must not use the signature-fallback FindFirstMethod (it can bind the SET sibling)")


def check_factory_city_open_attempts(plugin: Path, errors: list[str]) -> None:
    """B2: Factory city per-open flags reset per open attempt and on every leave."""
    reg = strip_comments((plugin / "Homm3FactoryCitySceneRegistrar.cs").read_text(encoding="utf-8"))
    begin = method_body(reg, r"private static void BeginFactoryCityOpenAttempt\(")
    if begin is None or "_cloneFailed = false" not in begin or "_factoryCitySessionInjected = false" not in begin:
        errors.append("B2: BeginFactoryCityOpenAttempt must clear the previous attempt's _cloneFailed and _factoryCitySessionInjected")
    end = method_body(reg, r"private static void EndFactoryCityOpenAttempt\(")
    if end is None or "_factoryCityLoadRequested = false" not in end or "_factoryCitySessionInjected = false" not in end:
        errors.append("B2: EndFactoryCityOpenAttempt must reset the per-open flags")
    if reg.count("BeginFactoryCityOpenAttempt(\"") < 4:
        errors.append("B2: every Factory open entry point (Void, both LoadScene, LoadSceneAsync) must begin an attempt")
    if "_factoryCityLoadRequested = true" in reg.replace(begin or "", ""):
        errors.append("B2: only BeginFactoryCityOpenAttempt may set _factoryCityLoadRequested = true")
    suspend = method_body(reg, r"internal static void SuspendOwnedCityPresentation\(")
    if suspend is None or suspend.count("EndFactoryCityOpenAttempt()") < 2:
        errors.append("B2: SuspendOwnedCityPresentation must end the attempt on both the unloaded-scene and normal paths")


def check_draconic_dominion_escape_ordering(plugin: Path, errors: list[str]) -> None:
    """B3 (Captives contract, 2026-10-12; was the Draconic Dominion flee redirect).

    The native escape click has exactly one mod owner, Homm3DungeonCaptivesRuntime: a void prefix
    that only reads context into __state (the native flee always runs) and a postfix that records
    the capture after the native flee resolved. The removed Diplomacy redirect (popup dismiss,
    navigator opener, flee-state bookkeeping) must not come back in either file.
    """
    dominion = strip_comments((plugin / "Homm3DungeonDraconicDominionHook.cs").read_text(encoding="utf-8"))
    for token in ("PrefixSquadEscapeOnEscapeClick", "SquadEscapeOnEscapeClick", "ResolveNativeDiplomacyNavigatorOrThrow",
                  "NativeOpenDiplomacy", "DismissSquadEscapePopup", "FleeRecruitmentState", "DominionPricingSession"):
        if token in dominion:
            errors.append("B3: Homm3DungeonDraconicDominionHook must not own the escape click or the Diplomacy redirect (found " + token + ")")
    captives_path = plugin / "Homm3DungeonCaptivesRuntime.cs"
    if not captives_path.exists():
        errors.append("B3: Homm3DungeonCaptivesRuntime.cs missing")
        return
    captives = strip_comments(captives_path.read_text(encoding="utf-8"))
    prefix = method_body(captives, r"private static void PrefixEscapeClick\(")
    postfix = method_body(captives, r"private static void PostfixEscapeClick\(")
    if prefix is None or postfix is None:
        errors.append("B3: Captives must patch the escape click with a void prefix PrefixEscapeClick and a postfix PostfixEscapeClick")
        return
    if "return false" in prefix:
        errors.append("B3: the Captives escape prefix must never suppress the native flee")
    if "TryWriteState(" in prefix or "_buffAddMethod" in prefix:
        errors.append("B3: the Captives escape prefix must only read context; recording belongs to the postfix")
    if "TryWriteState(" not in postfix:
        errors.append("B3: the Captives escape postfix must record the capture")
    if "isEscape" not in prefix:
        errors.append("B3: the Captives escape prefix must require DataSquad.isEscape")
    for token in ("NativeOpenDiplomacy", "DismissSquadEscapePopup", "SquadEscapeHide"):
        if token in captives:
            errors.append("B3: Captives must not reintroduce the Diplomacy redirect (found " + token + ")")
    if captives.count("SquadEscapeOnEscapeClick") != 1:
        errors.append("B3: Captives must resolve the escape click exactly once")
    else:
        resolve_line = next((line for line in captives.splitlines() if "SquadEscapeOnEscapeClick" in line), "")
        # Live 25672315 interop exposes BhSquadEscapeUISession.Method_Public_Void_0 and the hidden
        # BhScreen.Method_Public_Void_0 (C# `new`); without the declared-type filter registration fails ambiguous.
        if "declaredOnType: true" not in resolve_line:
            errors.append("B3: Captives must resolve the escape click on BhSquadEscapeUISession itself (declaredOnType: true); the base BhScreen wrapper shares its live name")


def check_elite_strategem_session_scope(plugin: Path, errors: list[str]) -> None:
    """B4: stored Elite Strategem modes are stamped with the session identity and dropped across sessions."""
    ident = strip_comments((plugin / "Homm3SessionIdentity.cs").read_text(encoding="utf-8"))
    if "GameSymbols.AdventureVisionLaws.SessionHolderTypeHints" not in ident or "Homm3DirectStateIdentity.TryResolveKey(" not in ident:
        errors.append("B4: Homm3SessionIdentity must key the GameSymbols session Data root by native identity")
    rt = strip_comments((plugin / "Homm3CastleEliteStrategemRuntime.cs").read_text(encoding="utf-8"))
    if "internal long SessionKey;" not in rt or "SessionKey = sessionKey," not in rt:
        errors.append("B4: HeroModeState must carry the SessionKey stamped at selection")
    prune = method_body(rt, r"private static bool TryPruneModesToCurrentSession\(")
    if prune is None or "Homm3SessionIdentity.TryResolveSessionDataKey(" not in prune or "ModesByHeroId.Remove(" not in prune:
        errors.append("B4: TryPruneModesToCurrentSession must resolve the session and drop other-session modes")
    cast = method_body(rt, r"private static bool PrefixNecromancyWorldMagicCast\(")
    if cast is None or "TryPruneModesToCurrentSession(" not in cast:
        errors.append("B4: mode selection must refuse when the session identity is unresolved")
    apply = method_body(rt, r"private static void ApplySelectedModeToBattle\(")
    if apply is None or "TryPruneModesToCurrentSession(" not in apply:
        errors.append("B4: ApplySelectedModeToBattle must skip (fail closed) when the session identity is unresolved")


def check_live_renamed_members(plugin: Path, errors: list[str]) -> None:
    """B5: members renamed on live Golden Era are read by name through GameSymbols.LiveRenamedMembers."""
    symbols = (plugin / "GameSymbols.cs").read_text(encoding="utf-8")
    for needle in (
        '{ "pic", "field_Private_Image_0" }',
        '{ "crit", "field_Public_Single_0" }',
        '{ "hp", "field_Public_Int32_0" }',
        '{ "me", "field_Public_Static_BhHeroHUDPanel_0" }',
    ):
        if needle not in symbols:
            errors.append("B5: GameSymbols.LiveRenamedMembers must pin " + needle)
    banned = {
        "Homm3ImportReleaseBattleUiHook.cs": (r"\?\.pic\b", r"\.unitView\.pic\b"),
        "LuckCritMixture.cs": (r"\.crit\b",),
        "DamageKillMapping.cs": (r"stats\.hp\b",),
        "Homm3HeroPortraitHook.cs": (r"BhHeroHUDPanel\.me\b",),
        "BattleForecastProbe.cs": (r"damageUiParams\.(caster|castSource|target)\b",),
    }
    for name, patterns in banned.items():
        text = strip_comments((plugin / name).read_text(encoding="utf-8"))
        for pattern in patterns:
            if re.search(pattern, text):
                errors.append("B5: " + name + " must not use the deobf-only direct member /" + pattern + "/ (MissingMethodException on live Golden Era)")
        if "GameSymbols.LiveRenamedMembers." not in text:
            errors.append("B5: " + name + " must read the renamed member through GameSymbols.LiveRenamedMembers")


def check_stale_presentation_type_lookups(plugin: Path, errors: list[str]) -> None:
    """A8: no legacy "ckj" resolver lookups; the profile window type comes from GameSymbols."""
    for name in ("Homm3HeroPortraitHook.cs", "Homm3StrongholdLawIconHook.cs"):
        text = strip_comments((plugin / name).read_text(encoding="utf-8"))
        if 'GetHexType("ckj")' in text:
            errors.append("A8: " + name + " must not look up the legacy ckj resolver (absent on Golden Era; the central guarded resolver serves these keys)")
        if "nameof(PrefixSpriteResolver)" in text:
            errors.append("A8: " + name + " must not add a second, unguarded prefix on the native sprite resolver")
    central = (plugin / "Homm3CustomUiIconHook.cs").read_text(encoding="utf-8")
    for needle in ("Homm3StrongholdLawIconSpriteCache.TryGetOrCreateSprite(sid", "Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(sid"):
        if needle not in central:
            errors.append("A8: the central sprite resolver must still serve " + needle.split(".")[0] + " keys")
    profile = strip_comments((plugin / "Homm3HeroClassProfileHook.cs").read_text(encoding="utf-8"))
    if '"Hex.Session.UI.BhHeroProfileWindow"' in profile or "GameSymbols.HeroProfile.ProfileWindowTypeHints" not in profile:
        errors.append("A8: Homm3HeroClassProfileHook must resolve the profile window type from GameSymbols.HeroProfile.ProfileWindowTypeHints")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    plugin = args.repo_root / PLUGIN_DIR
    errors: list[str] = []
    check_sprite_resolver(plugin, errors)
    check_selected_unit_hud_finalizers(plugin, errors)
    check_battle_local_native_keys(plugin, errors)
    check_focus_energy_members(plugin, errors)
    check_hero_map_visual_parking(plugin, errors)
    check_army_strip_hero_arg_refresh(plugin, errors)
    check_swashbuckler_gold_add(plugin, errors)
    check_factory_city_open_attempts(plugin, errors)
    check_draconic_dominion_escape_ordering(plugin, errors)
    check_elite_strategem_session_scope(plugin, errors)
    check_live_renamed_members(plugin, errors)
    check_stale_presentation_type_lookups(plugin, errors)
    if errors:
        for error in errors:
            print("native hook safety contract FAILED: " + error, file=sys.stderr)
        return 1
    print("native hook safety contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
