#!/usr/bin/env python3
"""Pin the plugin binary-only deploy mode to its three intended files."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


EXPECTED_DEPLOY_FILES = {
    "OfflineUnlockMod.dll",
    "OfflineUnlockMod.pdb",
    "OfflineUnlockMod.payload_abi.json",
}
BINARY_ONLY_GATE = "'$(deploypluginbinaryonlynormalized)' != 'true'"
READBACK_VALIDATORS = {
    "validate_homm3_unit_bundle_audio_contract.py",
    "validate_homm3_bundle_payload_directory.py",
    "validate_homm3_owned_skinned_attack_clip_contract.py",
    "validate_homm3_lab_clip_audio_driver_contract.py",
    "validate_homm3_map_squad_death_contract.py",
    "validate_homecoming_reduced_slice_runtime_contract.py",
    "validate_homecoming_native_water_runtime_contract.py",
}
DEPLOY_TARGET_TASKS = {
    "ItemGroup",
    "MakeDir",
    "Copy",
    "PropertyGroup",
    "Message",
    "Error",
    "Exec",
    "Delete",
}
SAFETY_TARGETS = {
    "RefuseDeployWhileGameRunning": "BeforeTargets",
    "ValidatePluginLiveInteropRefs": "BeforeTargets",
    "ValidateGameSymbolsHintContract": "BeforeTargets",
    "EmitPluginPayloadAbiSidecar": "BeforeTargets",
    "ValidateOfflineUnlockModDeployHash": "AfterTargets",
    "ValidatePluginPayloadAbiSidecar": "AfterTargets",
}


def fail(message: str) -> None:
    raise SystemExit(f"binary-only deploy contract: {message}")


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def children_named(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if local_name(child) == name]


def has_binary_only_gate(condition: str) -> bool:
    return " ".join(condition.lower().split()) == BINARY_ONLY_GATE


def normalized_condition(condition: str) -> str:
    return " ".join(condition.lower().split())


def item_filename(include: str) -> str:
    normalized = include.replace("\\", "/")
    if "$(" in normalized and ")" in normalized:
        normalized = normalized.rsplit(")", 1)[-1]
    return normalized.rsplit("/", 1)[-1]


def validate_project(project_path: Path) -> None:
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as exc:
        fail(f"cannot parse {project_path}: {exc}")

    targets = {
        target.attrib.get("Name", ""): target
        for target in children_named(root, "Target")
    }
    top_properties = [
        prop
        for group in children_named(root, "PropertyGroup")
        for prop in group
    ]
    binary_property = next(
        (prop for prop in top_properties if local_name(prop) == "DeployPluginBinaryOnly" and "Condition" in prop.attrib),
        None,
    )
    normalized_property = next(
        (prop for prop in top_properties if local_name(prop) == "DeployPluginBinaryOnlyNormalized" and "Condition" not in prop.attrib),
        None,
    )
    if binary_property is None or normalized_property is None:
        fail("binary-only property defaults/normalization are missing")
    if binary_property.text != "false" or normalized_property.text != "false":
        fail("binary-only mode must default to false")
    if normalized_condition(binary_property.attrib.get("Condition", "")) != "'$(deploypluginbinaryonly)' == ''":
        fail("binary-only raw property must default only when unset")
    true_property = next(
        (
            prop
            for prop in top_properties
            if local_name(prop) == "DeployPluginBinaryOnlyNormalized"
            and prop.text == "true"
            and "Condition" in prop.attrib
        ),
        None,
    )
    expected_true_condition = (
        "'$(deploypluginbinaryonly)' == 'true' or "
        "'$(deploypluginbinaryonly)' == 'true' or "
        "'$(deploypluginbinaryonly)' == 'true'"
    )
    if true_property is None or normalized_condition(true_property.attrib.get("Condition", "")) != expected_true_condition:
        fail("binary-only normalization must accept only the explicit true casing variants")

    deploy = targets.get("DeployPluginToGame")
    if deploy is None:
        fail("DeployPluginToGame target is missing")

    deploy_file_items: list[ET.Element] = []
    deploy_file_groups: list[ET.Element] = []
    asset_groups: list[ET.Element] = []
    for group in children_named(deploy, "ItemGroup"):
        items = [item for item in group if local_name(item) != "PropertyGroup"]
        files = [item for item in items if local_name(item) == "DeployFile"]
        non_files = [item for item in items if local_name(item) != "DeployFile"]
        deploy_file_items.extend(files)
        if files:
            deploy_file_groups.append(group)
        if non_files:
            if files:
                fail("DeployFile declarations share an ItemGroup with asset declarations")
            asset_groups.append(group)
            if not has_binary_only_gate(group.attrib.get("Condition", "")):
                fail("a main-target asset ItemGroup is not empty in binary-only mode")

    deploy_file_includes = [item.attrib.get("Include", "") for item in deploy_file_items]
    expected_includes = {f"$(OutDir){name}" for name in EXPECTED_DEPLOY_FILES}
    if len(deploy_file_includes) != len(expected_includes) or set(deploy_file_includes) != expected_includes:
        fail(f"DeployFile includes are {deploy_file_includes!r}, expected only $(OutDir) plugin binaries/sidecar")
    if len(deploy_file_groups) != 1 or "Condition" in deploy_file_groups[0].attrib:
        fail("the three DeployFile declarations must remain in one unconditional ItemGroup")
    for item in deploy_file_items:
        filename = item_filename(item.attrib.get("Include", ""))
        condition = normalized_condition(item.attrib.get("Condition", ""))
        if filename == "OfflineUnlockMod.pdb":
            if condition != "exists('$(outdir)offlineunlockmod.pdb')":
                fail("optional PDB inclusion condition changed unexpectedly")
        elif condition:
            fail(f"required DeployFile {filename} must always be included")

    asset_item_names: set[str] = set()
    allowed_declaration_ids = {id(item) for item in deploy_file_items}
    for group in asset_groups:
        for item in group:
            asset_item_names.add(local_name(item))
            allowed_declaration_ids.add(id(item))
    for copy in children_named(deploy, "Copy"):
        source = copy.attrib.get("SourceFiles", "").strip()
        if source.startswith("@("):
            item_name = source[2:].split(")", 1)[0]
            if item_name != "DeployFile":
                asset_item_names.add(item_name)
    tracked_asset_names = asset_item_names | {"DeployFile"}
    for item in root.iter():
        if local_name(item) in tracked_asset_names and ("Include" in item.attrib or "Update" in item.attrib):
            if id(item) not in allowed_declaration_ids:
                fail(f"asset item declaration is outside the guarded deploy ItemGroups: {local_name(item)}")

    allowed_tasks = DEPLOY_TARGET_TASKS
    unexpected_tasks = sorted(
        {local_name(node) for node in deploy if local_name(node) not in allowed_tasks}
    )
    if unexpected_tasks:
        fail(f"unexpected deploy-target task(s) may mutate additional payloads: {unexpected_tasks}")

    deploy_copies = 0
    for copy in children_named(deploy, "Copy"):
        source = copy.attrib.get("SourceFiles", "").strip()
        condition = copy.attrib.get("Condition", "")
        if source == "@(DeployFile)":
            deploy_copies += 1
            if "Condition" in copy.attrib:
                fail("DeployFile copy must remain unconditional in binary-only mode")
            if copy.attrib.get("DestinationFiles", "").strip() != "@(DeployFile->'$(PluginDeployDir)%(FileName)%(Extension)')":
                fail("DeployFile copy no longer targets only the plugin directory root")
            continue
        if source.startswith("@("):
            item_name = source[2:].split(")", 1)[0]
            expected_condition = f"'@({item_name.lower()})' != ''"
            if normalized_condition(condition) != expected_condition:
                fail(f"asset copy from {item_name} is not count-guarded")
            continue
        expected_condition = has_binary_only_gate(condition)
        if source == "$(EsquireBundleSource)":
            expected_condition = normalized_condition(condition) == (
                "exists('$(esquirebundlesource)') and " + BINARY_ONLY_GATE
            )
        if not expected_condition:
            fail(f"direct asset copy is not explicitly gated in binary-only mode: {source}")
    if deploy_copies != 1:
        fail(f"expected one DeployFile copy task, found {deploy_copies}")
    if len(asset_groups) < 1:
        fail("no asset ItemGroups were found to protect")
    make_dirs = children_named(deploy, "MakeDir")
    if len(make_dirs) != 1 or make_dirs[0].attrib.get("Directories", "") != "$(PluginDeployDir)":
        fail("deploy target may only create the plugin root directory")

    delete_tasks = children_named(deploy, "Delete")
    if any(not has_binary_only_gate(task.attrib.get("Condition", "")) for task in delete_tasks):
        fail("a deploy-target cleanup Delete can mutate payloads in binary-only mode")
    deploy_properties = {
        local_name(prop): (prop.text or "").lower()
        for group in children_named(deploy, "PropertyGroup")
        for prop in group
    }
    for task in children_named(deploy, "Exec"):
        command = task.attrib.get("Command", "").lower()
        command_is_readback = any(script in command for script in READBACK_VALIDATORS)
        command_is_readback = command_is_readback or any(
            f"$({name.lower()})" in command and any(script in value for script in READBACK_VALIDATORS)
            for name, value in deploy_properties.items()
        )
        if not command_is_readback:
            fail("an unexpected Exec can mutate payloads in binary-only mode")

    options = targets.get("ValidateDeployPluginBinaryOnlyOptions")
    if options is None:
        fail("binary-only option validation target is missing")
    if "BeforeBuild" not in options.attrib.get("BeforeTargets", "") or "DeployPluginToGame" not in options.attrib.get("BeforeTargets", ""):
        fail("invalid-option and payload-conflict guards must run before build and deploy")
    option_errors = children_named(options, "Error")
    invalid_value_guard = next(
        (error for error in option_errors if "must be true or false" in error.attrib.get("Text", "").lower()),
        None,
    )
    expected_invalid_condition = " and ".join(
        f"'$(deploypluginbinaryonly)' != '{value}'"
        for value in ("true", "true", "true", "false", "false", "false")
    )
    if invalid_value_guard is None or normalized_condition(invalid_value_guard.attrib.get("Condition", "")) != expected_invalid_condition:
        fail("raw binary-only property does not fail closed on every non-boolean value")
    conflict_guard = next(
        (error for error in option_errors if "cannot be combined" in error.attrib.get("Text", "").lower()),
        None,
    )
    expected_conflict_condition = (
        "'$(deploypluginbinaryonlynormalized)' == 'true' and ("
        "'$(deployhomm3bundlesnormalized)' == 'true' or "
        "'$(deployhomm3factorybulwarkbundlesnormalized)' == 'true' or "
        "'$(deployhomm3bundlenamenormalized)' == 'true' or "
        "'$(deployhomm3scenariopayloadsnormalized)' == 'true')"
    )
    if conflict_guard is None or normalized_condition(conflict_guard.attrib.get("Condition", "")) != expected_conflict_condition:
        fail("binary-only option validation does not fail closed on every bundle/scenario opt-in")

    contract_target = targets.get("ValidateDeployPluginBinaryOnlyContract")
    if contract_target is None or "BeforeBuild" not in contract_target.attrib.get("BeforeTargets", ""):
        fail("binary-only static contract validator is not wired before build")
    contract_condition = contract_target.attrib.get("Condition", "").lower()
    if "fullvalidationnormalized" not in contract_condition or "deploypluginbinaryonlynormalized" not in contract_condition:
        fail("static contract validator must run for full validation and binary-only deploys")
    exec_commands = "\n".join(node.attrib.get("Command", "") for node in children_named(contract_target, "Exec"))
    if "validate_binary_only_plugin_deploy_contract.py" not in exec_commands:
        fail("static contract validator target does not invoke this validator")

    for name, hook in SAFETY_TARGETS.items():
        target = targets.get(name)
        if target is None:
            fail(f"existing deploy safety target is missing: {name}")
        if "DeployPluginToGame" not in target.attrib.get(hook, ""):
            fail(f"{name} no longer runs {hook} DeployPluginToGame")
        if "DeployPluginBinaryOnly" in target.attrib.get("Condition", ""):
            fail(f"{name} is skipped by binary-only mode")

    print("binary-only-deploy-contract-ok 3 files; asset groups gated; deploy safety hooks retained")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    validate_project(args.project.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
