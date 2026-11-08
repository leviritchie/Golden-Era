#!/usr/bin/env python3
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
GENERATOR_PATH = RELEASE_PORT / "generate_custom_law_static_implementation_packets.py"
DEFAULT_QUEUE = ROOT / "artifacts" / "custom_law_static" / "custom_law_implementation_queue.json"
DEFAULT_SOURCE_MATRIX = ROOT / "custom_factions" / "custom_law_source_prepared_matrix.json"
DEFAULT_PREDICATE_MAP = ROOT / "custom_factions" / "custom_law_profile_predicate_surface_map.json"

NON_NATIVE_READINESS = {
    "source-prepared-runtime-blocked",
    "temporary-compromise-playable-strict-placeholder-ready",
    "runtime-gate-open-ready-to-implement",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_generator_module() -> Any:
    spec = importlib.util.spec_from_file_location("generate_custom_law_static_implementation_packets", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load generator module: {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_packet_doc(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    packets = doc.get("packets")
    if not isinstance(packets, list):
        return errors + ["packets must be a list"]
    if len(packets) != 130:
        errors.append(f"expected 130 packets, got {len(packets)}")
    seen: set[str] = set()
    readiness_counts = Counter()
    for packet in packets:
        if not isinstance(packet, dict):
            errors.append(f"packet row is not an object: {packet!r}")
            continue
        sid = packet.get("lawSid")
        if not isinstance(sid, str) or not sid:
            errors.append(f"packet missing lawSid: {packet!r}")
            continue
        if sid in seen:
            errors.append(f"duplicate law packet: {sid}")
        seen.add(sid)
        readiness = packet.get("readiness")
        readiness_counts[str(readiness)] += 1
        proof = packet.get("packetProof")
        if not isinstance(proof, dict):
            errors.append(f"{sid}: packetProof must be an object")
        elif proof.get("gameplayAllowed") is True and readiness != "runtime-gate-open-ready-to-implement":
            errors.append(f"{sid}: gameplayAllowed=true but readiness is {readiness!r}")
        handler = packet.get("handler")
        if not isinstance(handler, str) or not handler:
            errors.append(f"{sid}: handler must be a non-empty string")
        seams = packet.get("sourceSeams")
        if not isinstance(seams, dict):
            errors.append(f"{sid}: sourceSeams must be an object")
        else:
            for field in ("adapter", "runtime", "currentCapability"):
                if not isinstance(seams.get(field), str) or not seams.get(field):
                    errors.append(f"{sid}: sourceSeams.{field} must be a non-empty string")
            blockers = seams.get("blockedBy")
            if readiness in NON_NATIVE_READINESS:
                if not isinstance(blockers, list) or "packet gameplayAllowed=false" not in blockers:
                    errors.append(f"{sid}: non-native packet must retain packet gameplayAllowed=false blocker")
        profile = packet.get("profile")
        planner = packet.get("planner")
        predicates = packet.get("predicateSurfaces")
        if readiness in NON_NATIVE_READINESS:
            if not isinstance(profile, dict) or not isinstance(profile.get("family"), str):
                errors.append(f"{sid}: non-native packet must include profile family")
            if not isinstance(profile, dict) or not isinstance(profile.get("effectKey"), str):
                errors.append(f"{sid}: non-native packet must include profile effectKey")
            if not isinstance(profile, dict) or not isinstance(profile.get("evidenceBoundary"), str):
                errors.append(f"{sid}: non-native packet must include profile evidenceBoundary")
            if not isinstance(planner, dict) or not isinstance(planner.get("planMethod"), str):
                errors.append(f"{sid}: non-native packet must include planner planMethod")
            if not isinstance(planner, dict) or not isinstance(planner.get("predicateMethod"), str):
                errors.append(f"{sid}: non-native packet must include planner predicateMethod")
            if not isinstance(predicates, list):
                errors.append(f"{sid}: predicateSurfaces must be a list")
            else:
                for predicate in predicates:
                    if not isinstance(predicate, dict):
                        errors.append(f"{sid}: predicate row is not an object")
                        continue
                    status = predicate.get("status")
                    if status in {"missing", "rejected"}:
                        errors.append(f"{sid}: predicate {predicate.get('predicate')} has blocking status {status}")
                    if status in {"mapped", "partial"} and not predicate.get("surfaceIds"):
                        errors.append(f"{sid}: predicate {predicate.get('predicate')} status {status} requires surfaceIds")
        boundary = packet.get("implementationBoundary")
        if not isinstance(boundary, str) or not boundary:
            errors.append(f"{sid}: implementationBoundary must be a non-empty string")
        elif readiness in NON_NATIVE_READINESS and "fallback" in boundary.lower():
            errors.append(f"{sid}: implementationBoundary must not contain fallback wording")
    expected_readiness = {
        "native-exact-ready": 15,
        "source-prepared-runtime-blocked": 93,
        "temporary-compromise-playable-strict-placeholder-ready": 22,
    }
    for key, expected in expected_readiness.items():
        if readiness_counts.get(key, 0) != expected:
            errors.append(f"readiness count {key}: expected {expected}, got {readiness_counts.get(key, 0)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate generated custom law static implementation packets in memory without writing reports."
    )
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--source-matrix", type=Path, default=DEFAULT_SOURCE_MATRIX)
    parser.add_argument("--predicate-map", type=Path, default=DEFAULT_PREDICATE_MAP)
    args = parser.parse_args()

    try:
        generator = load_generator_module()
        doc = generator.build_packets(
            generator.require_object(load_json(args.queue), "implementation queue"),
            generator.require_object(load_json(args.source_matrix), "source-prepared matrix"),
            generator.require_object(load_json(args.predicate_map), "predicate surface map"),
        )
        errors = validate_packet_doc(doc)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"custom law static implementation packet validation failed: {exc}")
        return 1

    if errors:
        print("custom law static implementation packet validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("custom law static implementation packet validation passed (130 packet(s))")
    print("Note: static packet validation does not prove build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
