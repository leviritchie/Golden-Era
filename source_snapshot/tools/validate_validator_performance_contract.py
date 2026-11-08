"""Fast, synthetic performance invariants; never launch Unity or a GPU workload."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj")
TARGET_TIMEOUT_CEILINGS = {
    "ValidateTownZeroStreakContract": 2_100_000,
    "ValidateHomm3CsBakeContract": 2_100_000,
    "RefuseDeployWhileGameRunning": 30_000,
    "ValidateValidatorPerformanceContract": 120_000,
}


def unconditional_fail_closed(execute: ET.Element) -> bool:
    return not execute.get("Condition") and all(
        execute.get(attribute, "false").lower() == "false"
        for attribute in ("IgnoreExitCode", "ContinueOnError")
    )


def project_errors(project: ET.Element) -> list[str]:
    errors = []
    targets = {target.get("Name", ""): target for target in project.iter("Target")}
    for name, target in targets.items():
        for execute in target.iter("Exec"):
            command = execute.get("Command", "")
            if not name.startswith(("Validate", "Audit", "Refuse", "Emit")) and not (
                name == "DeployPluginToGame" and ("validate_" in command or "Validator)" in command)
            ):
                continue
            timeout = execute.get("Timeout", "")
            ceiling = TARGET_TIMEOUT_CEILINGS.get(name, 300_000)
            if not timeout.isdecimal() or not 0 < int(timeout) <= ceiling:
                errors.append(f"{name}: Exec requires a finite positive Timeout <= {ceiling}ms")
    performance = targets.get("ValidateValidatorPerformanceContract")
    if performance is None or performance.get("Condition") != "'$(FullValidationNormalized)' == 'true'":
        errors.append("performance regression contract must run in FullValidation only")
    elif performance.get("BeforeTargets") != "BeforeBuild" or not any(
        "validate_validator_performance_contract.py" in node.get("Command", "")
        for node in performance.iter("Exec")
    ):
        errors.append("performance regression contract must invoke its fixture runner before build")
    elif not all(unconditional_fail_closed(node) for node in performance.iter("Exec")):
        errors.append("performance fixtures must be unconditional and fail the build on error")
    delivery = targets.get("ValidateHomm3DefRetargetDeliveryContract")
    delivery_condition = "'$(FullValidationNormalized)' == 'true' and ('$(SkipHomm3DefRetargetDeliveryContract)' != 'true')"
    if delivery is None or delivery.get("Condition") != delivery_condition or delivery.get("BeforeTargets") != "BeforeBuild":
        errors.append("strict delivery validation must remain in the full build tier")
    elif not list(delivery.iter("Exec")) or any(
        "--selection" in node.get("Command", "")
        or "$(Homm3DefRetargetDeliveryValidator)" not in node.get("Command", "")
        or not unconditional_fail_closed(node)
        for node in delivery.iter("Exec")
    ):
        errors.append("full build delivery validation must retain the default all-selection scope")
    game_guard = targets.get("RefuseDeployWhileGameRunning")
    game_condition = "'$(DeployPluginToGame)' == 'true' and '$(TargetExt)' == '.dll' and '$(OS)' == 'Windows_NT'"
    if game_guard is None or game_guard.get("Condition") != game_condition \
            or game_guard.get("BeforeTargets") != "DeployPluginToGame" \
            or not list(game_guard.iter("Exec")) or any(
        "launch_guard.py" not in node.get("Command", "")
        or "--game-only" not in node.get("Command", "")
        or not unconditional_fail_closed(node)
        for node in game_guard.iter("Exec")
    ):
        errors.append("quick-tier game guard must fail closed on running or unknown process state")
    town = targets.get("ValidateTownScene3dContract")
    town_condition = "'$(FullValidationNormalized)' == 'true' and ('$(SkipTownScene3dContract)' != 'true')"
    if town is None or town.get("Condition") != town_condition or town.get("BeforeTargets") != "BeforeBuild":
        errors.append("town coverage and CUDA parity must remain in the full build tier")
    else:
        checks = list(town.iter("Exec"))
        parity = [node for node in checks if "test_town_gpu_pan.py" in node.get("Command", "")]
        coverage = [node for node in checks if "$(TownScene3dValidator)" in node.get("Command", "")]
        if len(parity) != 1 or "--cuda-parity" not in parity[0].get("Command", "") \
                or "--cuda-parity-test" in parity[0].get("Command", "") \
                or parity[0].get("Timeout") != "60000":
            errors.append("full town validation requires the complete bounded CUDA boundary parity fixture")
        if len(coverage) != 1 or any(flag in coverage[0].get("Command", "") for flag in ("--only", "--device")):
            errors.append("full town validation must retain all catalogs and default CUDA coverage")
        if any(not unconditional_fail_closed(node) for node in checks):
            errors.append("town coverage and parity failures must fail the build")
    return errors


def run_fixtures(root: Path, fixtures: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    errors = []
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.monotonic()
    for relative, selectors in fixtures:
        remaining = 90 - (time.monotonic() - started)
        if remaining <= 0:
            errors.append("performance fixture suite exceeded its 90s budget")
            break
        try:
            result = subprocess.run(
                [sys.executable, str(root / relative), *selectors], cwd=root,
                capture_output=True, text=True, env=environment, timeout=min(30, remaining),
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{relative}: synthetic fixture exceeded 30s or remaining suite budget")
            break
        print(f"{relative}: exit={result.returncode}")
        if result.returncode:
            errors.append(f"{relative}:\n{(result.stdout + result.stderr)[-4000:]}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    errors = project_errors(ET.parse(root / PROJECT).getroot())
    # Explicit inventory keeps full art/GPU fixtures out of this build gate.
    fixtures = [
        ("tests/test_validator_performance_contract.py", ()),
        ("tests/test_map_load_preflight_reuse.py", ()),
        ("tools/homm3_town_scene_meshes/test_phase6_pan_contract.py", ()),
        ("tools/homm3_town_scene_meshes/test_town_gpu_pan.py", ()),
        ("tools/homm3_def_retarget_delivery/test_validator_scope.py", ()),
        ("tools/homm3_def_retarget/test_launch_guard_game_probe.py", ()),
        ("tools/homm3_town_scene_meshes/test_town_gpu_lock.py", ()),
        ("tools/homm3_unit_look/test_gpuslot.py", ()),
        ("tools/homm3_def_retarget/test_memgate.py", ()),
        ("tools/homm3_vfx/test_unitylock.py", ()),
        ("tools/unity_queue/test_unity_queue.py", ()),
        ("tools/homm3_silhouette_pose_fit/test_cascade_lock_probes.py", ()),
    ]
    errors += run_fixtures(root, fixtures)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    print("validator performance contract OK (source and synthetic fixtures only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
