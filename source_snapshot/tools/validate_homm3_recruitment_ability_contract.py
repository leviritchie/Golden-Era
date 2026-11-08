#!/usr/bin/env python3
"""Validate HoMM3 recruitment cards keep custom unit identity through native bind.

Recruitment and in-window upgrade cards are generated with custom h3_* unit SIDs.
The native hire card must receive those custom SIDs so its UnitLogicConfig and
UnitViewConfig produce the correct native ability wrappers. Donor units may still
be used as visual/prefab references by the preview/model layer, but the hire-card
identity path must not rewrite BhHireUnitItemView.UpdateView(string) to donor
SIDs or repair donor ability rows afterward.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import xml.etree.ElementTree as ET


def fail(message: str) -> None:
    print(f"homm3-recruitment-ability-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_method_body(source: str, name: str) -> str:
    match = re.search(r"(?:private|internal|public)\s+(?:static\s+)?[\w<>\[\]]+\s+" + re.escape(name) + r"\s*\(", source)
    if not match:
        fail(f"missing method {name}")
    paren_start = match.end() - 1
    paren_depth = 0
    signature_end = None
    for index in range(paren_start, len(source)):
        char = source[index]
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
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
                return source[brace_start + 1:index]
    fail(f"unterminated method {name}")
    return ""




def find_python_function_body(source: str, name: str) -> str:
    match = re.search(r"(?m)^def\s+" + re.escape(name) + r"\s*\([^\n]*\)\s*->[^:]*:\s*$|^def\s+" + re.escape(name) + r"\s*\([^\n]*\)\s*:\s*$", source)
    if not match:
        fail(f"missing function {name}")
    start = match.end()
    next_match = re.search(r"(?m)^def\s+\w+\s*\(", source[start:])
    end = start + next_match.start() if next_match else len(source)
    return source[start:end]

def require_contains(text: str, token: str, context: str) -> None:
    if token not in text:
        fail(f"{context} must contain {token!r}")


def require_not_contains(text: str, token: str, context: str) -> None:
    if token in text:
        fail(f"{context} must not contain {token!r}")


def validate_msbuild_target(csproj: str) -> None:
    try:
        root = ET.fromstring(csproj)
    except ET.ParseError as exc:
        fail(f"OfflineUnlockMod.csproj is not parseable XML: {exc}")
    target = None
    for element in root.iter():
        if element.tag.endswith("Target") and element.attrib.get("Name") == "ValidateHomm3RecruitmentAbilityContract":
            target = element
            break
    if target is None:
        fail("OfflineUnlockMod.csproj must define ValidateHomm3RecruitmentAbilityContract")
    if target.attrib.get("BeforeTargets") != "BeforeBuild":
        fail("ValidateHomm3RecruitmentAbilityContract must run BeforeTargets=BeforeBuild")
    property_nodes = [node for node in target.iter() if node.tag.endswith("Homm3RecruitmentAbilityValidator")]
    if not any("validate_homm3_recruitment_ability_contract.py" in (node.text or "") for node in property_nodes):
        fail("ValidateHomm3RecruitmentAbilityContract must define Homm3RecruitmentAbilityValidator for this script")
    exec_nodes = [node for node in target.iter() if node.tag.endswith("Exec")]
    if not any("$(Homm3RecruitmentAbilityValidator)" in node.attrib.get("Command", "") for node in exec_nodes):
        fail("ValidateHomm3RecruitmentAbilityContract must execute Homm3RecruitmentAbilityValidator")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()

    plugin_dir = args.plugin_dir
    repo_root = plugin_dir.parents[1]
    hook_path = plugin_dir / "Homm3CustomUiIconHook.cs"
    symbols_path = plugin_dir / "GameSymbols.cs"
    csproj_path = plugin_dir / "OfflineUnlockMod.csproj"
    registry_path = plugin_dir / "Homm3CustomFactionRegistry.cs"
    overlay_path = repo_root / "tools" / "release_port" / "apply_release_core_overlay.py"
    inferno_manifest_path = repo_root / "custom_factions" / "homm3_inferno.json"
    for path in (hook_path, symbols_path, csproj_path, registry_path, overlay_path, inferno_manifest_path):
        if not path.is_file():
            fail(f"missing required file: {path}")

    hook = hook_path.read_text(encoding="utf-8-sig")
    symbols = symbols_path.read_text(encoding="utf-8-sig")
    csproj = csproj_path.read_text(encoding="utf-8-sig")
    registry = registry_path.read_text(encoding="utf-8-sig")
    overlay = overlay_path.read_text(encoding="utf-8-sig")
    inferno_manifest = inferno_manifest_path.read_text(encoding="utf-8-sig")

    prefix_body = find_method_body(hook, "PrefixStringArg0DonorSurface")
    for token in (
        "Homm3CustomFactionRegistry.IsCustomUnitSid(key)",
        "RememberRecruitmentItemSid(__instance, __state)",
        "custom sid",
        "preserved",
    ):
        require_contains(prefix_body, token, "hire-card UpdateView prefix must preserve custom identity")
    for token in (
        "key = donorSid",
        "PushRecruitmentDonorAlias",
        "TryGetDonorSid(key",
    ):
        require_not_contains(prefix_body, token, "hire-card UpdateView prefix must not donor-alias custom SIDs")

    postfix_body = find_method_body(hook, "PostfixStringArg0DonorSurface")
    require_contains(postfix_body, "TryApplyRecruitmentItemView(__instance, -1, FormatMethod(__originalMethod) + \".hire-card\", resolvedSid)", "hire-card postfix must repaint the current custom card")
    require_not_contains(postfix_body, "PopRecruitmentDonorAlias", "hire-card postfix must not unwind donor alias state")

    hire_bind_prefix_body = find_method_body(hook, "PrefixHireUnitAbilitiesBind")
    for token in (
        "var unitSid = ResolveUnitConfigSid(unit)",
        "TryResolveRecruitmentAbilityOwnerSid(__instance, out var customSid)",
        "TryGetCustomRecruitmentSidForCurrentFaction(unitSid, out var ownerlessCustomSid)",
        "without owning custom hire-card SID",
        "string.Equals(unitSid, customSid, StringComparison.OrdinalIgnoreCase)",
        "HoMM3 recruitment ability bind reached donor unit config",
        "throw new InvalidOperationException",
    ):
        require_contains(hire_bind_prefix_body, token, "hire ability bind must enforce custom identity and fail on donor leaks")
    for token in (
        "TryGetCustomRecruitmentSidForCurrentFaction(donorSid, out customSid)",
        "using current-faction custom sid",
        "TrySetFirstMemberValue(unit, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigFields",
        "TrySetFirstMemberValue(unit, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigFields",
        "CreateHireAbilityIconContext",
        "HireAbilityIconContexts.Push",
        "custom-config-bound",
    ):
        require_not_contains(hire_bind_prefix_body, token, "hire ability bind must not repair donor configs downstream")

    for token in (
        "PrefixRecruitmentAbilityBindSurface",
        "HireAbilityIconContexts",
        "CreateHireAbilityIconContext",
        "ResolveRecruitmentAbilityBindOverride",
        "FindRecruitmentAbilityBindByLogic",
        "RequiredExactAnyBySymbolWithPrefix(\"Hex.Session.City.BhHireUnitAbilityItemView primary ability bind",
        "PatchExactAnyBySymbolWithPrefix(h, log, \"Hex.Session.City.BhHireUnitAbilityItemView",
    ):
        require_not_contains(hook, token, "root-cause recruitment ability contract must not keep stale wrapper replacement machinery")
    for token in (
        "RequiredAnyBySymbol(\"Hex.Session.City.BhHireUnitAbilityItemView primary ability bind",
        "RequiredAnyBySymbol(\"Hex.Session.City.BhHireUnitAbilityItemView secondary ability bind",
        "RequiredAnyBySymbol(\"Hex.Session.City.BhHireUnitAbilityView primary ability bind",
        "RequiredAnyBySymbol(\"Hex.Session.City.BhHireUnitAbilityView secondary ability bind",
        "PatchAnyBySymbol(h, log, \"Hex.Session.City.BhHireUnitAbilityItemView",
        "PatchAnyBySymbol(h, log, \"Hex.Session.City.BhHireUnitAbilityView",
    ):
        require_contains(hook, token, "recruitment ability row surfaces must be postfix-only icon/config surfaces")
    require_not_contains(hook, "ScheduleRecruitmentAbilityRowsForHireItem(component, sid, source)", "hire-card repaint path must not schedule late ability row projection")
    require_not_contains(hook, "Recruitment ability rows did not settle", "root-cause contract must not depend on retrying stale native rows")

    init_body = find_method_body(hook, "PrefixHireUnitItemInit")
    for token in (
        "var sid = ResolveRecruitmentIndexedBaseSid(index)",
        "RememberRecruitmentItemSid(__instance, sid)",
    ):
        require_contains(init_body, token, "hire-card Init must remember custom SID ownership before native bind")

    require_contains(registry, "map[line.CustomSidForSuffix(suffix)] = line.DonorBaseSid + suffix", "custom-to-donor map remains visual/prefab metadata only")
    require_contains(registry, "RecruitmentBaseSids = BuildRecruitmentBaseSids(AllUnitLines)", "registry must expose all manifest recruitment base SIDs")
    for token in (
        "additionalRecruitmentLines",
        "AdditionalRecruitmentLine[] AdditionalRecruitmentLines",
        "TryGetManifestUnitBranch",
        "foreach (var line in faction.AllUnitLines)",
    ):
        require_contains(registry, token, "additional recruitment lines must participate in runtime identity")
    require_contains(registry, "result[i] = unitLines[i].BaseSid", "recruitment base SIDs must come from custom base SIDs")

    generic_hire_body = find_python_function_body(overlay, "generic_unit_hire_payload")
    for token in (
        "sids = generic_unit_sids_for_line(line, variants)",
        "row[\"sids\"] = list(sids)",
    ):
        require_contains(generic_hire_body, token, "generated Core hire payload must write custom unit SIDs")
    require_not_contains(generic_hire_body, "donor", "generated Core hire payload must not write donor unit SIDs")
    # Fail-closed helper takes an explicit context string; calls may be multi-line.
    require_contains(
        overlay,
        "def generic_unit_hire_payload(payload: Any, line: dict[str, Any], variants: tuple[str, ...], context: str)",
        "hire payload helper must take an explicit fail-closed context string",
    )
    for pattern, label in (
        (
            r'generic_unit_hire_payload\(\s*row\.get\("unitsHire"\),\s*unit_lines\[tier - 1\],\s*variants,',
            "town dwelling hire data must use the custom SID payload helper",
        ),
        (
            r'generic_unit_hire_payload\(\s*row\.get\("unitsData"\),\s*line,\s*variants,',
            "external dwelling hire data must use the custom SID payload helper",
        ),
    ):
        if re.search(pattern, overlay) is None:
            fail(label)

    for token in (
        '"baseSid": "h3_imp"',
        '"donorBaseSid": "trick_demon"',
        '"recruitmentBaseSids"',
        '"h3_imp"',
        '"customToDonorSource": "manifest"',
        '"reverseDonorLookup": "context_required"',
        '"allowGlobalDonorReverseLookup": false',
    ):
        require_contains(inferno_manifest, token, "Inferno manifest must keep custom recruitment identity separate from donor metadata")

    for token in (
        "UnitLogicConfigFields",
        "UnitViewConfigFields",
        "HireUnitAbilitiesBind",
        '"hun"',
        '"Method_Public_Void_Unit_0"',
    ):
        require_contains(symbols, token, "centralized native symbol contract")

    validate_msbuild_target(csproj)

    print("homm3-recruitment-ability-contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())