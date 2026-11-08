#!/usr/bin/env python3
"""Validate HoMM3 battle ability custom icon routing.

Inferno Gating hero abilities intentionally use HoMM3 unit SID icons such as
h3_imp, h3_gog, and h3_hell_hound. Both the selected-unit battle HUD and the
hero-action button strip must route those data-owned unit SID icon keys through
custom icon routing. Native cko.sfo sprite resolution must register custom keys
into the native sprite catalog instead of short-circuiting with hook-returned sprites.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
import zipfile
from typing import Any


EXPECTED_GATING_ROWS = {
    "HOMM3_INFERNO_GATING_IMP_ABILITY_SID": "h3_imp",
    "HOMM3_INFERNO_GATING_GOG_ABILITY_SID": "h3_gog",
    "HOMM3_INFERNO_GATING_HELL_HOUND_ABILITY_SID": "h3_hell_hound",
}

EXPECTED_CUSTOM_HERO_ABILITY_ICON_ROWS = {
    "skill_faction_homm3_inferno_ability_gating": ["h3_imp"],
    "skill_faction_homm3_inferno_ability_gating_gogs": ["h3_gog"],
    "skill_faction_homm3_inferno_ability_gating_hell_hounds": ["h3_hell_hound"],
    "skill_faction_homm3_rampart_ability_avenger": ["sub_skill_faction_homm3_rampart_avenger_mark"] * 7,
    "skill_faction_homm3_tower_ability_arcane_battery": ["h3_mage"] * 3,
    "skill_faction_homm3_stronghold_ability_moral": ["sub_skill_faction_homm3_stronghold_warcry_rallying"] * 3,
    "skill_faction_homm3_stronghold_ability_luck": ["sub_skill_faction_homm3_stronghold_warcry_fortune"] * 3,
    "skill_faction_homm3_stronghold_ability_initiative": ["sub_skill_faction_homm3_stronghold_warcry_tempo"] * 3,
}

HERO_ABILITIES_PATH = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"


def fail(message: str) -> None:
    print(f"homm3-battle-ability-icon-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_method_body(source: str, name: str) -> str:
    match = re.search(
        r"(?:private|internal|public)?\s*(?:static\s+)?[\w<>\[\]]+\s+"
        + re.escape(name)
        + r"\s*\([^{}]*\)\s*\{",
        source,
    )
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
                return source[start + 1 : index]
    fail(f"unterminated method {name}")
    return ""


def require_contains(text: str, token: str, context: str) -> None:
    if token not in text:
        fail(f"{context} must contain {token!r}")


def require_not_contains(text: str, token: str, context: str) -> None:
    if token in text:
        fail(f"{context} must not contain {token!r}")


def require_order(text: str, first: str, second: str, context: str) -> None:
    first_index = text.find(first)
    second_index = text.find(second)
    if first_index < 0 or second_index < 0 or first_index >= second_index:
        fail(f"{context} must contain {first!r} before {second!r}")


def validate_overlay_source(source: str) -> None:
    require_contains(source, "HOMM3_INFERNO_GATING_ABILITY_UNITS", "Inferno Gating source icon map")
    for const_name, expected_icon in EXPECTED_GATING_ROWS.items():
        require_contains(source, const_name, "Inferno Gating source icon map")
        pattern = re.compile(re.escape(const_name) + r"\s*:\s*['\"]" + re.escape(expected_icon) + r"['\"]")
        if not pattern.search(source):
            fail(f"Inferno Gating icon map must route {const_name} to {expected_icon}")
        factory_pattern = re.compile(
            r"make_homm3_inferno_gating_hero_ability\(\s*"
            + re.escape(const_name)
            + r"\s*,\s*['\"]"
            + re.escape(expected_icon)
            + r"['\"]",
            re.MULTILINE,
        )
        if not factory_pattern.search(source):
            fail(f"Inferno Gating factory row must emit {const_name} with icon {expected_icon}")


def import_overlay_module(repo_root: pathlib.Path) -> Any:
    overlay_source = repo_root / "tools" / "release_port" / "apply_release_core_overlay.py"
    overlay_dir = overlay_source.parent
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    if not overlay_source.is_file():
        fail(f"missing overlay source: {overlay_source}")
    spec = importlib.util.spec_from_file_location("homm3_battle_ability_icon_overlay_contract", overlay_source)
    if spec is None or spec.loader is None:
        fail(f"cannot import overlay source: {overlay_source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_candidate_overlay(repo_root: pathlib.Path) -> tuple[pathlib.Path, dict[str, bytes]]:
    module = import_overlay_module(repo_root)
    core_path = pathlib.Path(module.DEFAULT_RELEASE_CORE)
    if not core_path.is_file():
        fail(f"missing release Core.zip for candidate icon validation: {core_path}")
    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001 - contract should fail closed with source error text.
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    if not isinstance(overlay, dict):
        fail("build_overlay did not return an overlay dictionary")
    return core_path, overlay


def read_candidate_json(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        fail(f"candidate Core output is missing {member}")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        fail(f"cannot read candidate {member}: {ex}")


def validate_candidate_core(repo_root: pathlib.Path) -> None:
    core_path, overlay = build_candidate_overlay(repo_root)
    with zipfile.ZipFile(core_path) as core_zip:
        doc = read_candidate_json(core_zip, overlay, HERO_ABILITIES_PATH)
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        fail(f"candidate {HERO_ABILITIES_PATH} must contain an array")
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if not isinstance(sid, str):
            continue
        if sid in by_id:
            duplicates.add(sid)
        by_id[sid] = row
    for sid in duplicates:
        if sid in EXPECTED_CUSTOM_HERO_ABILITY_ICON_ROWS:
            fail(f"candidate {HERO_ABILITIES_PATH} contains duplicate custom hero ability icon row {sid}")
    for sid, expected_icons in EXPECTED_CUSTOM_HERO_ABILITY_ICON_ROWS.items():
        row = by_id.get(sid)
        if row is None:
            fail(f"candidate {HERO_ABILITIES_PATH} is missing custom hero ability icon row {sid}")
        levels = row.get("levels")
        if not isinstance(levels, list) or len(levels) != len(expected_icons):
            fail(f"candidate custom hero ability row {sid} must have {len(expected_icons)} level object(s)")
        for index, expected_icon in enumerate(expected_icons):
            if not isinstance(levels[index], dict):
                fail(f"candidate custom hero ability row {sid} level {index} must be an object")
            icon = levels[index].get("icon")
            if icon != expected_icon:
                fail(f"candidate custom hero ability row {sid} level {index} must use icon {expected_icon}, found {icon!r}")


def validate_packaged_custom_hero_ability_icon_files(plugin_dir: pathlib.Path) -> None:
    icon_dir = plugin_dir / "homm3_skill_icons"
    missing: list[pathlib.Path] = []
    expected_icons = sorted(
        {
            icon
            for icons in EXPECTED_CUSTOM_HERO_ABILITY_ICON_ROWS.values()
            for icon in icons
            if icon.startswith("sub_skill_faction_homm3_")
        }
    )
    for icon in expected_icons:
        icon_file = icon_dir / f"{icon}.png"
        if not icon_file.is_file():
            missing.append(icon_file)
    if missing:
        fail("missing packaged custom hero ability icon file(s): " + ", ".join(str(path) for path in missing))

def validate_hook(source: str) -> None:
    gate_body = find_method_body(source, "IsBattleAbilityCustomIconKey")
    require_contains(gate_body, "IsStrongholdAbilityDonorIconKey(sid)", "battle ability custom icon gate")
    require_contains(gate_body, "IsHomm3UnitSid(sid)", "battle ability custom icon gate")
    require_contains(gate_body, "Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(sid)", "battle ability custom icon gate")
    require_not_contains(gate_body, "TryResolveSprite", "battle ability custom icon gate must classify keys, not probe assets")

    for method_name in ("PostfixBattleAbilityViewBind", "RefreshBattleAbilityIconRelease"):
        body = find_method_body(source, method_name)
        require_contains(body, "ResolveStrongholdAbilityIconKey(abilityViewConfig)", method_name)
        require_contains(body, "if (!IsBattleAbilityCustomIconKey(iconKey))", method_name)
        require_contains(body, "TryResolveSprite(iconKey, out var sprite)", method_name)
        require_not_contains(body, "if (!IsStrongholdAbilityDonorIconKey(iconKey))", method_name)

    resolver_body = find_method_body(source, "ResolveStrongholdAbilityIconKey")
    require_contains(resolver_body, "var iconKey = TryGetStringMember(abilityViewConfig, \"icon\")", "ability icon resolver")
    require_contains(resolver_body, "if (!string.IsNullOrWhiteSpace(iconKey))", "ability icon resolver")

    sprite_body = find_method_body(source, "TryResolveSprite")
    require_contains(sprite_body, "IsHomm3UnitSid(sid)", "battle ability unit SID sprite resolver")
    require_contains(sprite_body, "Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out sprite)", "battle ability unit SID sprite resolver")
    require_contains(sprite_body, "Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(sid, out sprite)", "battle ability packaged HoMM icon resolver")
    require_contains(sprite_body, "var semanticAbilityIconKey = ResolveStrongholdAbilitySemanticIconKey(sid)", "native sprite catalog semantic ability-name resolver")
    require_contains(sprite_body, "TryResolveSprite(semanticAbilityIconKey, out sprite)", "native sprite catalog semantic ability-name resolver")
    # The Harmony entry point is a try/catch shell; the resolver contract lives in its core.
    native_prefix_body = find_method_body(source, "PrefixSpriteResolverCore")
    custom_key_body = find_method_body(source, "IsCustomKey")

    require_contains(custom_key_body, "Homm3CustomFactionRegistry.IsCustomUnitSid(sid)", "native sprite catalog custom-key gate must recognize manifest-backed custom unit icon SIDs before sprite resolution")
    require_not_contains(custom_key_body, "IsHomm3UnitSid(sid)", "native sprite catalog custom-key gate must not treat every h3_* token as a custom unit icon")
    require_not_contains(custom_key_body, 'sid.StartsWith("h3_"', "native sprite catalog custom-key gate must not treat all h3 localization tokens as icons")
    require_contains(custom_key_body, "ResolveStrongholdAbilitySemanticIconKey(sid)", "native sprite catalog custom-key gate must recognize mapped combat semantic ability names")
    require_not_contains(custom_key_body, "TryResolveSprite(sid, out var sprite) && sprite", "native sprite catalog custom-key gate must not silently fall through when recognized custom sprites are missing")
    require_contains(source, "ResolveStrongholdAbilitySemanticIconKey(sid)", "native sprite catalog must map known combat semantic ability names before registration")
    require_contains(source, '"h3_common_melee_attack_name" => "sub_skill_assault_1_icon"', "native sprite catalog combat semantic ability name mapping")

    require_contains(native_prefix_body, "if (!IsCustomKey(key))", "native sprite resolver prefix")
    require_contains(native_prefix_body, "Homm3NativeSpriteCatalogRegistrar.TryEnsureRegistered(key, TryResolveSprite", "native sprite resolver prefix must register the exact native request key")
    # 2026-09-27 audit A2: a throw here escaped native Method_Public_Sprite_String_0 (Fortress black
    # city UI, every custom build panel). Misses decline to native and log once per key instead;
    # validate_native_hook_safety_contract.py owns the no-throw gate.
    require_contains(native_prefix_body, "LogSpriteResolverDecline(key", "native sprite resolver prefix must log custom key registration misses once per key")
    require_not_contains(native_prefix_body, "throw new", "native sprite resolver prefix must never throw into native code")
    require_contains(native_prefix_body, "return true", "native sprite resolver prefix must let native cko.sfo continue after registration")
    # Dialog portraits may short-circuit; all other custom keys must fall through to native sfo.
    require_contains(
        native_prefix_body,
        "Homm3DialogPortraitCatalog.IsDialogHeroPortraitKey(key)",
        "native sprite resolver prefix must gate dialog-portrait short-circuit separately",
    )
    dialog_short_circuit = (
        "if (Homm3DialogPortraitCatalog.IsDialogHeroPortraitKey(key))\n"
        "\t\t{\n"
        "\t\t\t__result = sprite;"
    )
    require_contains(
        native_prefix_body,
        dialog_short_circuit,
        "native sprite resolver prefix must short-circuit only dialog hero portrait keys",
    )
    non_dialog_body = native_prefix_body
    dialog_idx = non_dialog_body.find("Homm3DialogPortraitCatalog.IsDialogHeroPortraitKey(key)")
    if dialog_idx >= 0:
        # Strip the dialog early-return block so the remaining path cannot blanket short-circuit.
        brace = non_dialog_body.find("{", dialog_idx)
        if brace >= 0:
            depth = 0
            end = brace
            for i, ch in enumerate(non_dialog_body[brace:], start=brace):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            non_dialog_body = non_dialog_body[:dialog_idx] + non_dialog_body[end:]
    require_not_contains(
        non_dialog_body,
        "__result = sprite",
        "native sprite resolver prefix must not short-circuit non-dialog custom keys",
    )
    require_not_contains(
        non_dialog_body,
        "return false",
        "native sprite resolver prefix must not bypass native sprite resolution for non-dialog keys",
    )



def validate_native_catalog_registrar(source: str, symbols: str) -> None:
    # The Golden Era pins live in GameSymbols.NativeSpriteCatalog so each build's scope applies; the
    # registrar must read them from there rather than carry its own literals.
    require_contains(symbols, "ResolverTypeHints = { \"ObjectPublicObbxDi2StSpbxDi2StUnique\" }", "GameSymbols.NativeSpriteCatalog")
    require_contains(symbols, "\"Method_Public_Static_ObjectPublicObbxDi2StSpbxDi2StUnique_0\"", "GameSymbols.NativeSpriteCatalog")
    require_contains(symbols, "\"get_field_Public_Dictionary_2_String_Sprite_0\"", "GameSymbols.NativeSpriteCatalog")
    require_contains(source, "ResolverTypeName => GameSymbols.NativeSpriteCatalog.ResolverTypeHints[0]", "native sprite catalog registrar")
    require_contains(source, "ResolverSingletonMethodName => GameSymbols.NativeSpriteCatalog.ResolverSingleton.NameHints[0]", "native sprite catalog registrar")
    require_contains(source, "SpriteCatalogGetterName => GameSymbols.NativeSpriteCatalog.SpriteCatalogGetter.NameHints[0]", "native sprite catalog registrar")
    require_contains(source, "TryEnsureRegistered", "native sprite catalog registrar")
    require_contains(source, "AddCatalogSprite", "native sprite catalog registrar")
    require_contains(source, "CatalogContains", "native sprite catalog registrar")
    require_not_contains(source, "get_field_Public_Dictionary_2_String_Sprite_1", "native sprite catalog registrar must use the runtime-proven catalog")

def validate_hero_button_hook(source: str, cache_source: str) -> None:
    compared_body = find_method_body(source, "IsComparedHeroAbilitySid")
    require_contains(compared_body, "IsWarcrySid(sid)", "hero action comparison gate")
    require_contains(compared_body, "IsHeroIconOverrideSid(sid)", "hero action comparison gate")
    require_contains(compared_body, "skill_faction_dungeon_ability_", "hero action comparison gate")

    icon_override_body = find_method_body(source, "IsHeroIconOverrideSid")
    require_contains(icon_override_body, "Homm3CustomHeroAbilityIconSpriteCache.HasIconForAbilitySid(sid)", "hero icon override gate")

    view_wrapper_body = find_method_body(source, "TryGetViewWrapper")
    require_contains(view_wrapper_body, "GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields", "hero action view wrapper resolver")
    require_not_contains(view_wrapper_body, "bxga", "hero action view wrapper resolver")
    require_not_contains(view_wrapper_body, "GetInstanceFields(view.GetType())", "hero action view wrapper resolver")

    release_resolver_body = find_method_body(source, "TryGetReleaseWarcryAbility")
    require_contains(release_resolver_body, "TryExtractHeroIconOverrideSid(obj) != null", "release hero ability resolver must accept config-name-only custom hero abilities")
    require_contains(release_resolver_body, "GameSymbols.WarcryHeroAbility.HeroAbilityFields", "release hero ability resolver")
    require_contains(release_resolver_body, "GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields", "release hero ability resolver")

    apply_body = find_method_body(source, "ApplyWarcryHeroIcon")
    require_contains(apply_body, "IsHeroIconOverrideSid(sid)", "hero action icon apply")
    require_contains(apply_body, "TryGetHeroAbilityIconKey(ability, sid, out var iconKey)", "hero action icon apply")
    require_contains(apply_body, "Homm3CustomUiIconHook.TryResolveSprite(iconKey, out var sprite)", "hero action icon apply")

    require_contains(apply_body, "TryExtractHeroIconOverrideSid(ability)", "hero action icon apply must use the shared custom hero ability SID resolver")
    require_contains(apply_body, "ApplyExactHeroAbilityIconImages(view, sprite)", "hero action icon apply must target the exact native hero-button icon images")
    require_not_contains(apply_body, "allowComponentImageFallback", "hero action icon apply must not keep broad image fallback switches")
    require_not_contains(apply_body, "GetComponentsInChildren<Image>(true)", "hero action icon apply must not sweep arbitrary child images")
    require_not_contains(apply_body, "EnumerateIl2CppList(pics)", "hero action icon apply must not depend on viewBase.pics for the native hero-button icons")

    shared_sid_body = find_method_body(source, "TryExtractHeroIconOverrideSid")
    require_contains(shared_sid_body, "TryExtractSid(ability)", "shared hero icon SID resolver must preserve direct managed SID extraction")
    require_contains(shared_sid_body, "TryExtractReleaseSid(ability)", "shared hero icon SID resolver must preserve release SID extraction")
    require_contains(shared_sid_body, "TryExtractHeroAbilitySidFromLevelConfig(ability)", "shared hero icon SID resolver must recover config-name-only custom hero abilities")
    require_contains(shared_sid_body, "IsHeroIconOverrideSid(sid)", "shared hero icon SID resolver must only accept custom hero ability SIDs")

    release_log_body = find_method_body(source, "LogReleaseWarcryObserved")
    require_contains(release_log_body, "TryExtractHeroIconOverrideSid(ability)", "release hero ability diagnostics must log config-name-only custom hero abilities")
    hero_sid_body = find_method_body(source, "TryExtractHeroAbilitySidFromLevelConfig")
    require_contains(hero_sid_body, "TryGetMemberValue(ability, \"config\")", "hero ability SID recovery must read the native runtime level config")
    require_contains(hero_sid_body, "TryGetMemberValue(config, \"name\")", "hero ability SID recovery must read the level config name token")
    require_contains(hero_sid_body, "EndsWith(\"_name\", StringComparison.Ordinal)", "hero ability SID recovery must only strip localization name tokens")
    require_contains(hero_sid_body, "IsHeroIconOverrideSid(sid)", "hero ability SID recovery must only accept custom hero ability SIDs")

    exact_icon_body = find_method_body(source, "ApplyExactHeroAbilityIconImages")
    for expected_path in ("DISABLED ICON/ICON", "NORMAL ICON/ICON", "HOVER ICON/ICON"):
        require_contains(exact_icon_body, expected_path, "exact hero ability icon image target")
    require_contains(exact_icon_body, "MissingMemberException", "exact hero ability icon target must fail visibly when the native layout changes")
    require_not_contains(exact_icon_body, "GetComponentsInChildren", "exact hero ability icon target must not sweep broad child images")
    require_not_contains(source, "ShouldReplaceWarcryIconImage", "hero action icon path must not use the old WIP sprite-name predicate")

    require_contains(cache_source, "HeroAbilitiesPath", "custom hero ability icon cache")
    require_contains(cache_source, "var arrayToken = root[\"array\"]", "custom hero ability icon cache")
    require_contains(cache_source, "arrayToken.Type != JTokenType.Array", "custom hero ability icon cache")
    require_contains(cache_source, "JArray.Parse(arrayToken.ToString())", "custom hero ability icon cache")
    require_contains(cache_source, "var rowToken = rows[rowIndex]", "custom hero ability icon cache must reparse runtime row tokens")
    require_contains(cache_source, "row = JObject.Parse(rowToken.ToString())", "custom hero ability icon cache must reparse runtime row tokens")
    require_not_contains(cache_source, "rows[rowIndex] as JObject", "custom hero ability icon cache must not rely on direct JToken casts")
    require_contains(cache_source, "var levelsToken = row[\"levels\"]", "custom hero ability icon cache")
    require_contains(cache_source, "levelsToken.Type != JTokenType.Array", "custom hero ability icon cache")
    require_contains(cache_source, "JArray.Parse(levelsToken.ToString())", "custom hero ability icon cache")
    require_not_contains(cache_source, "row[\"levels\"] as JArray", "custom hero ability icon cache")
    require_contains(cache_source, "IsCustomFactionHeroAbilitySid(id)", "custom hero ability icon cache")
    require_contains(cache_source, "level = JObject.Parse(levelToken.ToString())", "custom hero ability icon cache must reparse runtime level tokens")
    require_contains(cache_source, "row \" + rowIndex + \" parse failed", "custom hero ability icon cache must fail closed on row parse failure")
    require_contains(cache_source, "level \" + i + \" parse failed", "custom hero ability icon cache must fail closed on level parse failure")
    require_contains(cache_source, "if (loadedRows == 0)", "custom hero ability icon cache must fail closed when no custom rows load")
    require_contains(cache_source, "loaded zero custom hero ability icon rows from Core.zip.", "custom hero ability icon cache must fail closed when no custom rows load")
    require_not_contains(cache_source, "loadedRows == 0);", "custom hero ability icon cache must not log zero rows as successful load")
    require_not_contains(cache_source, "levelToken[\"icon\"]", "custom hero ability icon cache must read icons from reparsed level objects")
    require_contains(cache_source, "level[\"icon\"]", "custom hero ability icon cache")
    require_contains(cache_source, "var loadedIcons = new Dictionary<string, string[]>", "custom hero ability icon cache")
    require_contains(cache_source, "_iconsByAbilitySid = loadedIcons", "custom hero ability icon cache")
    require_not_contains(cache_source, "_iconsByAbilitySid = new Dictionary<string, string[]>", "custom hero ability icon cache")
    require_contains(cache_source, "icons.Length == 1", "custom hero ability icon cache")
    require_contains(cache_source, "_nextLoadRetryUtc = DateTime.UtcNow.AddSeconds(2)", "custom hero ability icon cache")
    require_contains(cache_source, "DescribeRootPreview(root)", "custom hero ability icon cache")
    require_contains(cache_source, "coreZipPath", "custom hero ability icon cache diagnostics")
    require_contains(cache_source, "if (!EnsureLoaded())", "custom hero ability icon cache must fail closed on load failure")
    require_contains(cache_source, "throw new InvalidOperationException", "custom hero ability icon cache must fail closed on load failure")
    require_contains(cache_source, "return false;", "custom hero ability icon cache keeps non-custom SIDs out of override path")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()

    plugin_dir = args.plugin_dir.resolve()
    repo_root = plugin_dir.parents[1]
    hook_path = plugin_dir / "Homm3CustomUiIconHook.cs"
    hero_hook_path = plugin_dir / "Homm3WarcriesHeroAbilityHook.cs"
    icon_cache_path = plugin_dir / "Homm3CustomHeroAbilityIconSpriteCache.cs"
    native_catalog_path = plugin_dir / "Homm3NativeSpriteCatalogRegistrar.cs"
    overlay_path = repo_root / "tools" / "release_port" / "apply_release_core_overlay.py"
    for path in (hook_path, hero_hook_path, icon_cache_path, native_catalog_path, overlay_path):
        if not path.is_file():
            fail(f"missing required file: {path}")

    validate_hook(hook_path.read_text(encoding="utf-8-sig"))
    validate_native_catalog_registrar(
        native_catalog_path.read_text(encoding="utf-8-sig"),
        (plugin_dir / "GameSymbols.cs").read_text(encoding="utf-8-sig"),
    )
    validate_hero_button_hook(
        hero_hook_path.read_text(encoding="utf-8-sig"),
        icon_cache_path.read_text(encoding="utf-8-sig"),
    )
    validate_overlay_source(overlay_path.read_text(encoding="utf-8-sig"))
    validate_packaged_custom_hero_ability_icon_files(plugin_dir)
    validate_candidate_core(repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
