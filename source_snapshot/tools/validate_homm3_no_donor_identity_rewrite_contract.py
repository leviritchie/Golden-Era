#!/usr/bin/env python3
"""Validate donor mappings stay out of identity-bearing native bind paths.

Custom HoMM3 unit SIDs may use donor assets for meshes, portraits, and other
view-only compatibility surfaces. They must not be rewritten to donor SIDs
before native code constructs wrappers, hover payloads, action buttons, costs,
or gameplay objects from the SID it receives.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import xml.etree.ElementTree as ET


IDENTITY_REWRITE_TOKENS = (
    "TryGetDonorSid(",
    "StrongholdUnitSidMapping.TryGetDonorSid(",
    "Homm3CustomFactionRegistry.TryGetDonorSid(",
    "key = donorSid",
    "sid = donorSid",
    "unitSid = donorSid",
    "PushRecruitmentDonorAlias",
    "PopRecruitmentDonorAlias",
)

DONOR_IDENTITY_ASSIGNMENT_PATTERNS = (
    re.compile(r"\b(?:key|sid|unitSid|resolvedSid|customSid)\s*=\s*\w*donor\w*", re.IGNORECASE),
    re.compile(r"\b(?:key|sid|unitSid|resolvedSid|customSid)\s*=\s*.*TryGetDonorSid", re.IGNORECASE),
)


def fail(message: str) -> None:
    print(f"homm3-no-donor-identity-rewrite-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_method_body(source: str, name: str) -> str:
    match = re.search(
        r"(?:private|internal|public)\s+(?:static\s+)?[\w<>\[\]]+\s+"
        + re.escape(name)
        + r"\s*\(",
        source,
    )
    if not match:
        fail(f"missing method {name}")
    paren_start = match.end() - 1
    depth = 0
    signature_end = None
    for index in range(paren_start, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                signature_end = index
                break
    if signature_end is None:
        fail(f"unterminated method signature {name}")
    brace_start = source.find("{", signature_end)
    if brace_start < 0:
        fail(f"missing method body {name}")
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : index]
    fail(f"unterminated method {name}")
    return ""


def require_contains(text: str, token: str, context: str) -> None:
    if token not in text:
        fail(f"{context} must contain {token!r}")


def require_not_contains(text: str, token: str, context: str) -> None:
    if token in text:
        fail(f"{context} must not contain {token!r}")


def reject_identity_rewrite(body: str, context: str, allowed: tuple[str, ...] = ()) -> None:
    for token in IDENTITY_REWRITE_TOKENS:
        if token in allowed:
            continue
        if token == "TryGetDonorSid(" and any(allowed_token.endswith("TryGetDonorSid(") for allowed_token in allowed):
            continue
        if token in body:
            fail(f"{context} must not rewrite custom identity through {token!r}")
    for pattern in DONOR_IDENTITY_ASSIGNMENT_PATTERNS:
        match = pattern.search(body)
        if match:
            fail(f"{context} must not assign donor-derived values into identity variables: {match.group(0)!r}")


def validate_hook_contract(hook: str) -> None:
    prefix_body = find_method_body(hook, "PrefixStringArg0DonorSurface")
    require_contains(prefix_body, "Homm3CustomFactionRegistry.IsCustomUnitSid(key)", "hire-card identity prefix")
    require_contains(prefix_body, "RememberRecruitmentItemSid(__instance, __state)", "hire-card identity prefix")
    require_contains(prefix_body, "preserved", "hire-card identity prefix")
    reject_identity_rewrite(prefix_body, "hire-card identity prefix")

    postfix_body = find_method_body(hook, "PostfixStringArg0DonorSurface")
    require_contains(postfix_body, "var resolvedSid = string.IsNullOrWhiteSpace(__state) ? key : __state;", "hire-card identity postfix")
    require_contains(postfix_body, "TryApplyRecruitmentItemView(__instance, -1, FormatMethod(__originalMethod) + \".hire-card\", resolvedSid)", "hire-card identity postfix")
    reject_identity_rewrite(postfix_body, "hire-card identity postfix")

    hire_bind_body = find_method_body(hook, "PrefixHireUnitAbilitiesBind")
    require_contains(hire_bind_body, "ResolveUnitConfigSid(unit)", "hire ability native bind")
    require_contains(hire_bind_body, "TryResolveRecruitmentAbilityOwnerSid(__instance, out var customSid)", "hire ability native bind")
    require_contains(hire_bind_body, "throw new InvalidOperationException", "hire ability native bind")
    require_contains(hire_bind_body, "HoMM3 recruitment ability bind reached donor unit config", "hire ability native bind")
    reject_identity_rewrite(
        hire_bind_body,
        "hire ability native bind",
        allowed=("StrongholdUnitSidMapping.TryGetDonorSid(",),
    )

    init_body = find_method_body(hook, "PrefixHireUnitItemInit")
    require_contains(init_body, "ResolveRecruitmentIndexedBaseSid(index)", "hire-card indexed identity prefix")
    require_contains(init_body, "RememberRecruitmentItemSid(__instance, sid)", "hire-card indexed identity prefix")
    reject_identity_rewrite(init_body, "hire-card indexed identity prefix")

    tooltip_body = find_method_body(hook, "PostfixTooltipUnitsView")
    require_contains(tooltip_body, "ResolveBuildingHireUnitSids(building, level", "tooltip unit identity source")
    require_contains(tooltip_body, "TryApplyRecruitmentItemList(TryGetMemberValue(__instance, \"unitViews\"), sids", "tooltip unit identity source")
    reject_identity_rewrite(tooltip_body, "tooltip unit identity source")

    indexed_body = find_method_body(hook, "ResolveRecruitmentIndexedBaseSid")
    require_contains(indexed_body, "GetRecruitmentBaseSidsForCurrentFaction()", "indexed recruitment identity resolver")
    require_contains(indexed_body, "baseSids[index]", "indexed recruitment identity resolver")
    reject_identity_rewrite(indexed_body, "indexed recruitment identity resolver")

    item_sid_body = find_method_body(hook, "ResolveRecruitmentItemSid")
    require_contains(item_sid_body, "NormalizeUnitSid(keyOrLabel)", "recruitment item identity resolver")
    require_contains(item_sid_body, "GetRecruitmentBaseSidsForCurrentFaction()", "recruitment item identity resolver")
    reject_identity_rewrite(item_sid_body, "recruitment item identity resolver")

    normalize_body = find_method_body(hook, "NormalizeUnitSid")
    require_contains(normalize_body, "IsHomm3UnitSid(text)", "unit SID normalizer")
    require_contains(normalize_body, "TryGetCustomRecruitmentSidForCurrentFaction(text, out var sid)", "unit SID normalizer")
    reject_identity_rewrite(normalize_body, "unit SID normalizer")

    building_hire_body = find_method_body(hook, "ResolveBuildingHireUnitSids")
    require_contains(building_hire_body, "AppendSessionHireUnitSetSids(result, data, requestedLevel)", "building hire identity resolver")
    require_contains(building_hire_body, "AppendRegistryBuildingHireSids(result, building, data, requestedLevel)", "building hire identity resolver")
    require_contains(building_hire_body, "NormalizeUnitSid(value)", "building hire identity resolver")
    reject_identity_rewrite(building_hire_body, "building hire identity resolver")

    session_hire_body = find_method_body(hook, "AppendSessionHireUnitSetSids")
    require_contains(session_hire_body, "NormalizeUnitSid(value)", "session hire set identity resolver")
    reject_identity_rewrite(session_hire_body, "session hire set identity resolver")

    registry_hire_body = find_method_body(hook, "AppendRegistryBuildingHireSids")
    require_contains(registry_hire_body, "Homm3CustomFactionRegistry.TryGetRecruitmentSidsForBuilding", "registry hire identity resolver")
    require_contains(registry_hire_body, "NormalizeUnitSid(value)", "registry hire identity resolver")
    reject_identity_rewrite(registry_hire_body, "registry hire identity resolver")

    battle_body = find_method_body(hook, "PostfixBattleAbilityViewBind")
    require_contains(battle_body, "TryGetReleaseAbility(__0) ?? TryGetReleaseAbility(__instance)", "battle ability identity source")
    require_contains(battle_body, "TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields)", "battle ability identity source")
    require_contains(battle_body, "ResolveStrongholdAbilityIconKey(abilityViewConfig)", "battle ability identity source")
    reject_identity_rewrite(battle_body, "battle ability identity source")

    battle_refresh_body = find_method_body(hook, "RefreshBattleAbilityIconRelease")
    require_contains(battle_refresh_body, "var ability = abilityHint ?? TryGetReleaseAbility(view);", "selected action-bar ability identity source")
    require_contains(battle_refresh_body, "TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields)", "selected action-bar ability identity source")
    reject_identity_rewrite(battle_refresh_body, "selected action-bar ability identity source")

    image_body = find_method_body(hook, "TryApplyToSurface")
    require_contains(image_body, "TryResolveSprite(key, out var sprite)", "asset-only image repaint")
    require_contains(image_body, "ApplySpriteToImage(image, sprite)", "asset-only image repaint")
    for token in ("ResolveUnitConfigSid", "TryGetReleaseAbility", "TryResolveRecruitmentAbilityOwnerSid", "new Unit", "AbilityLogicConfig"):
        require_not_contains(image_body, token, "asset-only image repaint")


def validate_registry_contract(registry: str) -> None:
    require_contains(registry, "RequireExact(runtime, \"customToDonorSource\", \"manifest\"", "manifest donor contract")
    require_contains(registry, "RequireExact(runtime, \"reverseDonorLookup\", \"context_required\"", "manifest donor contract")
    require_contains(registry, "runtime.allowGlobalDonorReverseLookup must be false", "manifest donor contract")
    require_contains(registry, "internal static bool TryGetDonorSid(string sid, out string donorSid)", "central donor map")
    require_contains(registry, "RecruitmentBaseSids = BuildRecruitmentBaseSids(AllUnitLines)", "all-lines recruitment identity source")
    require_contains(registry, "AdditionalRecruitmentLine[] AdditionalRecruitmentLines", "additional recruitment identity source")
    require_contains(registry, "result[i] = unitLines[i].BaseSid", "recruitment identity source")


def validate_selected_hud_contract(hud: str) -> None:
    for token in (
        "BeginReleaseNativeSidAlias",
        "RestoreSidAlias",
        "AliasReleaseConfigIds",
        "TryAliasReleaseConfigId",
        "SidAliasState",
    ):
        require_not_contains(hud, token, "selected-unit HUD source")

    for method_name, context in (
        ("PrefixBeetRelease", "selected-unit HUD event prefix"),
        ("PrefixBegsRelease", "selected-unit HUD direct prefix"),
    ):
        prefix = find_method_body(hud, method_name)
        require_contains(prefix, "Homm3CustomFactionRegistry.IsCustomUnitSid(sid)", context)
        require_contains(prefix, "var seeded = 0;", context)
        require_not_contains(prefix, "SeedAllCustomSidDictionaries", context)
        require_not_contains(prefix, "SeedCustomSidDictionaries", context)
        require_contains(prefix, "BeginReleaseCustomSidBind(unit, sid)", context)
        require_contains(prefix, "donor identity aliasing disabled", context)
        reject_identity_rewrite(prefix, context)

    for method_name, context in (
        # Audit A4 (2026-09-27): the finalizers are try/catch shells over *Core; the recovery gate
        # also receives the event sid so the whole custom-sid class is covered.
        ("FinalizerBeetReleaseCore", "selected-unit HUD event finalizer"),
        ("FinalizerBegsReleaseCore", "selected-unit HUD direct finalizer"),
    ):
        finalizer = find_method_body(hud, method_name)
        require_contains(finalizer, "IsReleaseRecoverableCustomSidMiss(__state, sid, eventSid, missingSid)", context)
        require_contains(finalizer, "RecoverUnitControlsRelease", context)
        reject_identity_rewrite(finalizer, context)


    release_region = hud[
        hud.find("private static bool PrefixBeetRelease") : hud.find("private static bool PrefixBdon")
    ]
    if "WriteUnitSid(" in release_region:
        fail("selected-unit HUD release path must not call WriteUnitSid")
    if "TryGetDonorSid(" in release_region:
        fail("selected-unit HUD release path must not resolve donor SIDs before native bind")
    if "SeedAllCustomSidDictionaries" in release_region or "SeedCustomSidDictionaries" in release_region:
        fail("selected-unit HUD release path must not seed donor dictionaries before native bind")
    require_contains(release_region, "IsReleaseRecoverableCustomSidMiss", "selected-unit HUD release recovery gate")
    require_not_contains(release_region, "IsReleaseCustomSidContext", "selected-unit HUD release recovery gate")

    direct_bind = find_method_body(hud, "DirectBindUnitControlsRelease")
    require_contains(direct_bind, "sid", "selected-unit HUD bind")
    require_contains(direct_bind, "FindReleaseActionBarAbilities(unit, manager, sid)", "selected-unit HUD bind")
    require_contains(direct_bind, "FindReleaseActionBarAbilitiesBySid(sid)", "selected-unit HUD bind")
    reject_identity_rewrite(direct_bind, "selected-unit HUD bind")

def validate_csproj(csproj: str) -> None:
    root = ET.fromstring(csproj)
    target = None
    for element in root.iter():
        if element.tag.endswith("Target") and element.attrib.get("Name") == "ValidateHomm3NoDonorIdentityRewriteContract":
            target = element
            break
    if target is None:
        fail("OfflineUnlockMod.csproj must define ValidateHomm3NoDonorIdentityRewriteContract")
    if target.attrib.get("BeforeTargets") != "BeforeBuild":
        fail("ValidateHomm3NoDonorIdentityRewriteContract must run BeforeTargets=BeforeBuild")
    if "validate_homm3_no_donor_identity_rewrite_contract.py" not in ET.tostring(target, encoding="unicode"):
        fail("ValidateHomm3NoDonorIdentityRewriteContract must execute this validator")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()

    plugin_dir = args.plugin_dir.resolve()
    paths = {
        "hook": plugin_dir / "Homm3CustomUiIconHook.cs",
        "registry": plugin_dir / "Homm3CustomFactionRegistry.cs",
        "hud": plugin_dir / "Homm3ImportBhSelectedUnitHudFix.cs",
        "csproj": plugin_dir / "OfflineUnlockMod.csproj",
    }
    for label, path in paths.items():
        if not path.is_file():
            fail(f"missing {label} file: {path}")

    validate_hook_contract(paths["hook"].read_text(encoding="utf-8-sig"))
    validate_registry_contract(paths["registry"].read_text(encoding="utf-8-sig"))
    validate_selected_hud_contract(paths["hud"].read_text(encoding="utf-8-sig"))
    validate_csproj(paths["csproj"].read_text(encoding="utf-8-sig"))
    print("homm3-no-donor-identity-rewrite-contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
