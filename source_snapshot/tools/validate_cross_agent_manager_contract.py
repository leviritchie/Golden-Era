"""Validate cross-tool coordination without reading or mutating the active board.

CPU work here is schema/protocol inspection and transactional I/O, not GPU array math.
The bounded behavioral fixtures run under an isolated repo-local temporary root.
This proves the manager contract, not any participant's reported product evidence.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


TARGET = "ValidateCrossAgentManagerContract"
PROJECT = "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj"
REQUIRED = (
    "tools/cross_agent_manager/__init__.py",
    "tools/cross_agent_manager/store.py",
    "tools/cross_agent_manager/manager.py",
    "tools/cross_agent_manager/test_manager.py",
    "docs/cross_agent_manager.md",
    ".agents/skills/cross-agent-manager/SKILL.md",
    "CLAUDE.md",
)


def validate(root: Path) -> list[str]:
    errors = [f"Missing manager contract file: {name}" for name in REQUIRED if not (root / name).is_file()]
    for name in ("AGENTS.md", "CLAUDE.md", "docs/README.md"):
        path = root / name
        if not path.is_file() or "cross_agent_manager" not in path.read_text(encoding="utf-8-sig"):
            errors.append(f"Missing cross-tool onboarding pointer in {name}")
    ignore = root / ".gitignore"
    if not ignore.is_file() or "/.cross-agent/" not in ignore.read_text(encoding="utf-8-sig").splitlines():
        errors.append("Local coordination state must be ignored with /.cross-agent/")
    doc = root / "docs/cross_agent_manager.md"
    if doc.is_file() and '{"resource":"golden-era-deploy"}' not in doc.read_text(encoding="utf-8-sig"):
        errors.append("Cross-tool deployers must share the documented golden-era-deploy resource")
    try:
        tree = ET.parse(root / PROJECT)
        matches = [node for node in tree.getroot().findall("Target") if node.get("Name") == TARGET]
        if len(matches) != 1:
            errors.append(f"Expected one {TARGET} build gate")
        else:
            target = matches[0]
            if target.get("Condition") != "'$(FullValidationNormalized)' == 'true'":
                errors.append("Manager validator must run in the full tier only")
            if target.get("BeforeTargets") != "BeforeBuild":
                errors.append("Manager validator must gate BeforeBuild")
            command = target.find("Exec")
            if command is None or command.get("Timeout") != "60000":
                errors.append("Manager build gate must have a 60000 ms timeout")
            elif "$(CrossAgentManagerValidator)" not in command.get("Command", "") or "--repo-root" not in command.get("Command", ""):
                errors.append("Manager build gate must invoke its owning validator")
            property_node = target.find("PropertyGroup/CrossAgentManagerValidator")
            if property_node is None or not (property_node.text or "").endswith("tools\\validate_cross_agent_manager_contract.py"):
                errors.append("Manager build gate points at the wrong validator")
            guard = target.find("Error")
            if guard is None or guard.get("Condition") != "!Exists('$(CrossAgentManagerValidator)')":
                errors.append("Manager build gate must fail if the validator is missing")
    except (OSError, ET.ParseError) as exc:
        errors.append(f"Cannot inspect manager build gate: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    errors = validate(root)
    if errors:
        print("Cross-agent manager contract FAIL:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "tools.cross_agent_manager.test_manager"],
            cwd=root, env=env, capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Cross-agent manager contract FAIL: fixture execution failed: {exc}", file=sys.stderr)
        return 1
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print("Cross-agent manager contract FAIL: behavioral fixture failed", file=sys.stderr)
        return 1
    print("Cross-agent manager contract PASS (isolated behavior; participant evidence remains self-reported)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
