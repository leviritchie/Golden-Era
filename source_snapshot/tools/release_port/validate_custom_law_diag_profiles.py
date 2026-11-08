#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_PATH = ROOT / "custom_factions" / "custom_law_diag_profiles.json"
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
REQUIRED_BASE_FLAG = "homm3_custom_faction_law_diag.flag"


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def target_packets(targets_doc: Any, v: Validation) -> set[str]:
    packets: set[str] = set()
    if not isinstance(targets_doc, dict):
        v.error("custom law targets root must be an object")
        return packets
    families = targets_doc.get("families")
    if not isinstance(families, dict):
        v.error("custom law targets families must be an object")
        return packets
    for key, entry in sorted(families.items()):
        if not isinstance(entry, dict):
            v.error(f"targets families.{key}: must be an object")
            continue
        packet = entry.get("packet")
        if not isinstance(packet, str) or not packet:
            v.error(f"targets families.{key}: packet must be a non-empty string")
            continue
        packets.add(packet)
    return packets


def validate_profiles(profiles_doc: Any, required_packets: set[str], v: Validation) -> None:
    if not isinstance(profiles_doc, dict):
        v.error("custom law diag profiles root must be an object")
        return
    if profiles_doc.get("schemaVersion") != 1:
        v.error(f"schemaVersion must be 1, got {profiles_doc.get('schemaVersion')!r}")
    profiles = profiles_doc.get("profiles")
    if not isinstance(profiles, dict):
        v.error("profiles must be an object")
        return

    for packet in sorted(required_packets):
        if packet not in profiles:
            v.error(f"missing diagnostic profile for target packet {packet!r}")

    for profile_name, flags in sorted(profiles.items()):
        if not isinstance(profile_name, str) or not profile_name:
            v.error(f"profile key must be a non-empty string, got {profile_name!r}")
            continue
        if not isinstance(flags, list) or not flags:
            v.error(f"{profile_name}: flags must be a non-empty list")
            continue
        seen_flags: set[str] = set()
        for flag in flags:
            if not isinstance(flag, str) or not flag:
                v.error(f"{profile_name}: every flag must be a non-empty string")
                continue
            if not flag.endswith(".flag"):
                v.error(f"{profile_name}: flag {flag!r} must end with .flag")
            if flag in seen_flags:
                v.error(f"{profile_name}: duplicate flag {flag!r}")
            seen_flags.add(flag)
        if profile_name != "law-tree" and REQUIRED_BASE_FLAG not in seen_flags:
            v.error(f"{profile_name}: must include {REQUIRED_BASE_FLAG!r} so active law/rank context is captured")

    for profile_name in sorted(profiles):
        if profile_name not in required_packets and profile_name != "law-tree":
            v.warn(f"{profile_name}: profile is not referenced by current target packet families")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate custom law diagnostic profiles against target packets.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_PATH)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    args = parser.parse_args()

    v = Validation()
    if not args.profiles.exists():
        v.error(f"missing profiles file: {args.profiles}")
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
    if v.errors:
        print(f"errors: {v.errors}")
        return 1

    packets = target_packets(load_json(args.targets), v)
    validate_profiles(load_json(args.profiles), packets, v)
    print(f"target packets: {sorted(packets)}")
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
