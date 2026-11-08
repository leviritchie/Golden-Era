#!/usr/bin/env python3
"""Guard the live C# probe compile and pre-deployment metadata check."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = Path("tools/live_probe_mcp/server.mjs")
TEST = Path("tools/live_probe_mcp/test_probe_compile.mjs")
PROJECT = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj")
TARGET = "ValidateLiveProbeCompileContract"


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    server_path = root / SERVER
    test_path = root / TEST
    project_path = root / PROJECT
    if not server_path.is_file():
        return [f"Missing live probe adapter: {SERVER.as_posix()}"]
    if not test_path.is_file():
        return [f"Missing compile regression fixture: {TEST.as_posix()}"]
    if not project_path.is_file():
        return [f"Missing plugin build project: {PROJECT.as_posix()}"]

    server = server_path.read_text(encoding="utf-8")
    test = test_path.read_text(encoding="utf-8")
    output_start = server.find("const outputDir = path.join(workDir, \"bin\")")
    build_start = server.find("const build = await runProcess(\"dotnet\", [\"build\", \"LiveProbe.csproj\"")
    copy_start = server.find("fs.copyFileSync(builtDllPath, dllPath)")
    bridge_start = server.find('const response = await callBridge("volatile_load_probe_assembly"')
    cecil_start = server.find('const cecilPath = references.find((ref) => path.basename(ref).toLowerCase() === "mono.cecil.dll")')
    validate_task_start = server.find('TaskName="ValidateLiveProbeAssembly" TaskFactory="RoslynCodeTaskFactory"')

    if output_start < 0 or 'path.join(outputDir, "LiveProbe.dll")' not in server:
        errors.append("server.mjs: build output must be under a distinct bin subdirectory")
    if 'OutputPath>${xmlEscape(outputDir)}\\\\</OutputPath>' not in server:
        errors.append("server.mjs: generated project OutputPath must use outputDir")
    if "EnableDefaultCompileItems" in server or "<Compile Include=" in server:
        errors.append("server.mjs: do not suppress or bypass the SDK default compile glob")
    if cecil_start < 0 or validate_task_start < 0:
        errors.append("server.mjs: compile must fail closed if the Mono.Cecil verifier is unavailable")
    for needle in (
        'RequestedTypeName.Replace(\'+\', \'/\')',
        "module.GetType(typeName)",
        "type.HasGenericParameters",
        "type.IsInterface",
        "!method.IsStatic",
        "method.IsAbstract",
        "method.HasGenericParameters",
        "method.Parameters.Count == 0",
        "method.Parameters.Count == 1",
        "ParameterType.MetadataType == MetadataType.String",
        "Log.LogError(",
        'AfterTargets="Build"',
    ):
        if needle not in server:
            errors.append(f"server.mjs: missing required metadata guard {needle!r}")
    if not (build_start >= 0 and copy_start > build_start and bridge_start > copy_start):
        errors.append("server.mjs: failed compile/metadata validation must occur before copy and bridge invocation")
    if 'const builtPdbPath = path.join(outputDir, "LiveProbe.pdb")' not in server:
        errors.append("server.mjs: PDB path must follow the separate output directory")

    try:
        tree = ET.parse(project_path)
        matches = [node for node in tree.getroot().findall("Target") if node.get("Name") == TARGET]
        if len(matches) != 1:
            errors.append(f"OfflineUnlockMod.csproj: expected one {TARGET} full-validation gate")
        else:
            target = matches[0]
            if target.get("Condition") != "'$(FullValidationNormalized)' == 'true'":
                errors.append(f"OfflineUnlockMod.csproj: {TARGET} must run only in FullValidation")
            if target.get("BeforeTargets") != "BeforeBuild":
                errors.append(f"OfflineUnlockMod.csproj: {TARGET} must gate BeforeBuild")
            command = target.find("Exec")
            if command is None or command.get("Timeout") != "60000":
                errors.append(f"OfflineUnlockMod.csproj: {TARGET} must invoke its validator with a 60000 ms timeout")
            elif "$(LiveProbeCompileContractValidator)" not in command.get("Command", "") or "--repo-root" not in command.get("Command", ""):
                errors.append(f"OfflineUnlockMod.csproj: {TARGET} omits its validator property or --repo-root")
            property_node = target.find("PropertyGroup/LiveProbeCompileContractValidator")
            if property_node is None or not (property_node.text or "").endswith("tools\\validate_live_probe_compile_contract.py"):
                errors.append(f"OfflineUnlockMod.csproj: {TARGET} points at the wrong validator")
    except (OSError, ET.ParseError) as exc:
        errors.append(f"Cannot inspect plugin build gate: {exc}")

    for needle in (
        "Mono.Cecil.dll",
        "OLDEN_LIVE_PROBE_BRIDGE_DIR",
        "Fixture.Entrypoint",
        "Fixture.MissingType",
        "Fixture.UnsupportedEntrypoint",
        "Run(int value)",
        "Compile",
        "wrong requested type reached the fake bridge",
        "wrong-type assembly was copied into bridge probes",
    ):
        if needle not in test:
            errors.append(f"test_probe_compile.mjs: missing regression assertion {needle!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate(args.repo_root.resolve())
    if errors:
        print("Live probe compile contract FAIL:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print("Live probe compile contract PASS (separate output, Cecil type/entrypoint check, fake-bridge regression fixture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
