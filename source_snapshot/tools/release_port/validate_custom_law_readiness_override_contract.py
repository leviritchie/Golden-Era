#!/usr/bin/env python3
"""Validate custom-law readiness classifications against override row state.

This is a static no-runtime guard. It rebuilds the implementation readiness
queue from current sources and verifies that playable and strict override rows
match the meaning of each readiness class.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RELEASE_PORT = ROOT / "tools" / "release_port"
QUEUE_GENERATOR = RELEASE_PORT / "generate_custom_law_implementation_queue.py"

EXPECTED_READINESS_COUNTS = {
    "native-exact-ready": 130,
    "source-prepared-runtime-blocked": 0,
    "temporary-compromise-playable-strict-placeholder-ready": 0,
}

def load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("generate_custom_law_implementation_queue", QUEUE_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {QUEUE_GENERATOR.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_queue(generator: Any, args: argparse.Namespace) -> dict[str, Any]:
    generator_args = argparse.Namespace(
        targets=args.targets,
        packet_proofs=args.packet_proofs,
        effect_inventory=args.effect_inventory,
        predicate_map=args.predicate_map,
        source_override_dir=args.source_override_dir,
        strict_override_dir=args.strict_override_dir,
        out_md=args.out_md,
        out_json=args.out_json,
    )
    return generator.build_queue(generator_args)


def validate_queue(queue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if queue.get("schemaVersion") != 2:
        errors.append("implementation queue schemaVersion must be 2")
    entries = queue.get("entries")
    if not isinstance(entries, list):
        return errors + ["implementation queue entries must be a list"]
    if len(entries) != 130:
        errors.append(f"expected 130 implementation queue entries, got {len(entries)}")

    readiness_counts: Counter[str] = Counter()
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"queue entry is not an object: {entry!r}")
            continue
        sid = entry.get("lawSid")
        if not isinstance(sid, str) or not sid:
            errors.append(f"queue entry has invalid lawSid: {entry!r}")
            continue
        if sid in seen:
            errors.append(f"{sid}: duplicate implementation queue entry")
        seen.add(sid)

        readiness = entry.get("readiness")
        status = entry.get("status")
        readiness_counts[str(readiness)] += 1
        source = entry.get("sourceOverride")
        strict = entry.get("strictCandidate")
        proof = entry.get("packetProof")
        profile = entry.get("profileCoverage")
        action = entry.get("withoutRuntimeAction")

        if not isinstance(source, dict):
            errors.append(f"{sid}: sourceOverride must be an object")
            continue
        if not isinstance(strict, dict):
            errors.append(f"{sid}: strictCandidate must be an object")
            continue
        if not isinstance(proof, dict):
            errors.append(f"{sid}: packetProof must be an object")
            continue

        source_status = source.get("status")
        source_bonus_count = source.get("bonusCount")
        strict_status = strict.get("status")
        strict_bonus_count = strict.get("bonusCount")

        if readiness == "native-exact-ready":
            if status != "native-exact":
                errors.append(f"{sid}: native-exact-ready requires target status native-exact, got {status!r}")
            if source_status != "playable-concrete-row" or not isinstance(source_bonus_count, int) or source_bonus_count <= 0:
                errors.append(f"{sid}: native-exact-ready requires concrete playable source bonuses")
            if strict_status != "native-row-present" or not isinstance(strict_bonus_count, int) or strict_bonus_count <= 0:
                errors.append(f"{sid}: native-exact-ready requires concrete strict native row bonuses")
            if not isinstance(action, str) or "Keep the exact native/data row" not in action:
                errors.append(f"{sid}: native-exact-ready action must preserve exact native/data row")
        elif readiness == "source-prepared-runtime-blocked":
            if status != "needs-runtime":
                errors.append(f"{sid}: source-prepared-runtime-blocked requires target status needs-runtime, got {status!r}")
            if not isinstance(profile, dict):
                errors.append(f"{sid}: source-prepared-runtime-blocked requires profileCoverage")
            if strict_status != "bonus-free-placeholder" or strict_bonus_count != 0:
                errors.append(f"{sid}: source-prepared-runtime-blocked requires bonus-free strict placeholder")
            if proof.get("gameplayAllowed") is not False:
                errors.append(f"{sid}: source-prepared-runtime-blocked must keep packet gameplayAllowed=false")
            if not isinstance(action, str) or "Keep gameplay disabled" not in action:
                errors.append(f"{sid}: source-prepared-runtime-blocked action must keep gameplay disabled")
        elif readiness == "temporary-compromise-playable-strict-placeholder-ready":
            if status != "temporary-compromise":
                errors.append(
                    f"{sid}: temporary-compromise-playable-strict-placeholder-ready requires target status temporary-compromise, got {status!r}"
                )
            if source_status != "playable-concrete-row" or not isinstance(source_bonus_count, int) or source_bonus_count <= 0:
                errors.append(f"{sid}: temporary-compromise readiness requires explicit playable compromise bonuses")
            if strict_status != "bonus-free-placeholder" or strict_bonus_count != 0:
                errors.append(f"{sid}: temporary-compromise readiness requires bonus-free strict placeholder")
            if proof.get("gameplayAllowed") is not False:
                errors.append(f"{sid}: temporary-compromise readiness must keep packet gameplayAllowed=false")
            if not isinstance(action, str) or "Keep gameplay disabled" not in action:
                errors.append(f"{sid}: temporary-compromise readiness action must keep gameplay disabled")
        else:
            errors.append(f"{sid}: unsupported readiness state {readiness!r}")

    for readiness, expected in EXPECTED_READINESS_COUNTS.items():
        actual = readiness_counts.get(readiness, 0)
        if actual != expected:
            errors.append(f"readiness count {readiness}: expected {expected}, got {actual}")

    return errors


def main() -> int:
    generator = load_generator()
    parser = argparse.ArgumentParser(
        description="Validate current custom law implementation readiness classes against playable/strict override rows."
    )
    parser.add_argument("--targets", type=Path, default=generator.DEFAULT_TARGETS_PATH)
    parser.add_argument("--packet-proofs", type=Path, default=generator.DEFAULT_PACKET_PROOFS_PATH)
    parser.add_argument("--effect-inventory", type=Path, default=generator.DEFAULT_EFFECT_INVENTORY_PATH)
    parser.add_argument("--predicate-map", type=Path, default=generator.DEFAULT_PREDICATE_MAP_PATH)
    parser.add_argument("--source-override-dir", type=Path, default=generator.DEFAULT_SOURCE_OVERRIDE_DIR)
    parser.add_argument("--strict-override-dir", type=Path, default=generator.DEFAULT_STRICT_OVERRIDE_DIR)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args()

    try:
        queue = build_queue(generator, args)
        errors = validate_queue(queue)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"custom law readiness override contract validation failed: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("custom law readiness override contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("custom law readiness override contract validation passed")
    print("Note: this proves static readiness/override consistency only, not build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

