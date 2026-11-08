#!/usr/bin/env python3
"""Validate direct-state headless replay scenario coverage (compile gate, no game)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def fail(message: str) -> None:
    print(f"direct-state-replay: {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    manifest = json.loads(
        read(root / "custom_factions" / "runtime_mechanics" / "homm3_adapter_manifest.json")
    )
    harness = read(plugin / "Homm3RuntimeMechanicFixtureHarness.cs")
    gateway = read(plugin / "NativeCombatWriteGateway.cs")
    backends = read(plugin / "CombatWriteBackends.cs")
    iface = read(plugin / "ICombatWriteBackend.cs")

    require("ICombatWriteBackend" in iface, "ICombatWriteBackend interface missing")
    require(
        "interface ICombatStateBackend" not in iface and "interface ICombatStateBackend" not in backends,
        "must not collide with law-state ICombatStateBackend naming",
    )
    require("LiveCombatWriteBackend" in backends, "live write backend missing")
    require("ModelCombatWriteBackend" in backends, "model write backend missing")
    require("UseWriteBackend" in gateway, "gateway must own backend selection")
    require("_writeBackend" in gateway, "gateway must route through write backend")
    require("TryRunHeadlessReplayScenarios" in harness, "fixture harness must host headless replay")
    require(
        "source-replay-validated" in harness,
        "headless replay must document proof label source-replay-validated (startup smoke / source-replay only; never combat-proven)",
    )
    require(
        "Does not launch combat" in harness or "does not launch combat" in harness.lower(),
        "headless replay must state it does not launch combat",
    )
    require(
        "combat proven" not in harness.lower().replace("never combat-proven", "").replace("not combat-proven", ""),
        "headless replay must not claim combat proven",
    )

    scenarios = manifest.get("replayScenarios")
    require(isinstance(scenarios, dict), "manifest.replayScenarios is required")
    accept = scenarios.get("acceptByOperation")
    require(isinstance(accept, list) and accept, "replayScenarios.acceptByOperation required")
    operations = set()
    for row in manifest["adapters"]:
        operations.update(row["operations"])
    covered = {entry["operation"] for entry in accept}
    require(covered == operations, f"acceptByOperation must cover every manifest operation; missing={operations-covered}")
    fixed = scenarios.get("fixedCases")
    require(isinstance(fixed, list) and len(fixed) >= 4, "fixed blocked/rollback/fault/budget cases required")
    kinds = {entry.get("kind") for entry in fixed}
    for required_kind in ("occupancy", "queue", "rollback", "fault", "budget"):
        require(required_kind in kinds, f"fixedCases missing kind={required_kind}")

    print("validated direct-state headless replay contract")


if __name__ == "__main__":
    main()
