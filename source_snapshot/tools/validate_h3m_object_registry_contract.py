#!/usr/bin/env python3
"""Validate shared HoMM3 adventure-object family constants used by translators."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_text(repo_root: Path, rel_path: str) -> str:
    return (repo_root / rel_path).read_text(encoding="utf-8-sig")


def function_body(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise ValueError(f"missing {start_marker}")
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError(f"missing {end_marker} after {start_marker}")
    return text[start:end]


def policy_object_ids(policy: dict[str, Any], category: str) -> set[int]:
    ids: set[int] = set()
    for row in policy.get("objectPolicies") or []:
        if isinstance(row, dict) and row.get("sourceCategory") == category:
            ids.update(value for value in row.get("objectIds") or [] if isinstance(value, int))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import h3m_object_registry as h3obj

    errors: list[str] = []
    require(h3obj.ARTIFACT_OBJECT_IDS == {5, 65, 66, 67, 68, 69}, f"artifact object ids mismatch: {sorted(h3obj.ARTIFACT_OBJECT_IDS)}", errors)
    require(h3obj.RANDOM_ARTIFACT_OBJECT_IDS == {65, 66, 67, 68, 69}, f"random artifact ids mismatch: {sorted(h3obj.RANDOM_ARTIFACT_OBJECT_IDS)}", errors)
    require(h3obj.OBJECT_RANDOM_HERO == 70, f"random hero id mismatch: {h3obj.OBJECT_RANDOM_HERO}", errors)
    require(h3obj.OBJECT_RANDOM_HERO not in h3obj.ARTIFACT_OBJECT_IDS, "random hero id 70 must not be an artifact id", errors)
    require(h3obj.OBJECT_SUBTERRANEAN_GATE == 103, f"subterranean gate id mismatch: {h3obj.OBJECT_SUBTERRANEAN_GATE}", errors)
    require(h3obj.OBJECT_WHIRLPOOL == 111, f"whirlpool id mismatch: {h3obj.OBJECT_WHIRLPOOL}", errors)
    require(h3obj.TRAVEL_LINK_OBJECT_IDS == {h3obj.OBJECT_SUBTERRANEAN_GATE, h3obj.OBJECT_WHIRLPOOL}, f"travel link ids mismatch: {sorted(h3obj.TRAVEL_LINK_OBJECT_IDS)}", errors)
    require((h3obj.OBJECT_ID_EVIDENCE.get(h3obj.OBJECT_SUBTERRANEAN_GATE) or {}).get("vcmiName") == "SUBTERRANEAN_GATE", "subterranean gate evidence mismatch", errors)
    require((h3obj.OBJECT_ID_EVIDENCE.get(h3obj.OBJECT_WHIRLPOOL) or {}).get("vcmiName") == "WHIRLPOOL", "whirlpool evidence mismatch", errors)
    require(h3obj.MONSTER_OBJECT_IDS == {54, 71, 72, 73, 74, 75, 162, 163, 164}, f"monster ids mismatch: {sorted(h3obj.MONSTER_OBJECT_IDS)}", errors)
    require(h3obj.FIXED_CREATURE_GENERATOR_IDS == {17, 18, 19, 20}, f"fixed creature generator ids mismatch: {sorted(h3obj.FIXED_CREATURE_GENERATOR_IDS)}", errors)
    require(h3obj.RANDOM_DWELLING_IDS == {216, 217, 218}, f"random dwelling ids mismatch: {sorted(h3obj.RANDOM_DWELLING_IDS)}", errors)
    require(h3obj.OBJECT_GARRISON == 33, f"garrison id mismatch: {h3obj.OBJECT_GARRISON}", errors)
    require(h3obj.OBJECT_SEER_HUT == 83, f"seer hut id mismatch: {h3obj.OBJECT_SEER_HUT}", errors)
    require(h3obj.OBJECT_SHIPYARD == 87, f"shipyard id mismatch: {h3obj.OBJECT_SHIPYARD}", errors)
    require(h3obj.OBJECT_VOLCANO in h3obj.NO_PAYLOAD_OBJECT_IDS, "volcano must be explicit no-payload", errors)
    require(h3obj.NO_PAYLOAD_OBJECT_IDS == h3obj.VCMI_CLASSIC_STATIC_NO_PAYLOAD_OBJECT_IDS, "no-payload ids must be the positive classic allowlist", errors)
    require(set(h3obj.NO_PAYLOAD_OBJECT_EVIDENCE) == set(h3obj.NO_PAYLOAD_OBJECT_IDS), "every no-payload id must have evidence", errors)
    require(all((row or {}).get("payloadShape") == "no per-instance payload" for row in h3obj.NO_PAYLOAD_OBJECT_EVIDENCE.values()), "no-payload evidence must state the zero-byte shape", errors)
    require(all((row or {}).get("h3mVersions") == [14, 21, 28] for row in h3obj.NO_PAYLOAD_OBJECT_EVIDENCE.values()), "no-payload evidence must name supported classic versions", errors)
    require(h3obj.OBJECT_RANDOM_HERO in h3obj.HERO_OBJECT_IDS, "random hero must use the source hero decoder", errors)
    require(h3obj.OBJECT_RANDOM_HERO not in h3obj.NO_PAYLOAD_OBJECT_IDS, "random hero must not be silently treated as zero-byte scenery", errors)
    for object_id in h3obj.RANDOM_DWELLING_IDS:
        require(object_id not in h3obj.UNSUPPORTED_KNOWN_OBJECTS, f"random dwelling id {object_id} must be decoded", errors)
    decoder = h3obj.PAYLOAD_DECODER_EVIDENCE.get("fixed_creature_generator") or {}
    require(decoder.get("vcmiReader") == "CMapLoaderH3M::readDwelling", f"fixed creature generator reader mismatch: {decoder}", errors)
    require(decoder.get("payloadShape") == "readPlayer32 owner only", f"fixed creature generator payload shape mismatch: {decoder}", errors)

    for rel_path in [
        "experiments/campaign_port_poc/h3m_object_walk.py",
        "experiments/campaign_port_poc/walk_homecoming_objects.py",
    ]:
        text = read_text(repo_root, rel_path)
        require("import h3m_object_registry as h3obj" in text or "import h3m_object_walk as core" in text, f"{rel_path} must use shared object registry/walker", errors)
        if rel_path.endswith("h3m_object_walk.py"):
            require("def skip_garrison" in text, f"{rel_path} must implement garrison decoder", errors)
            require("def skip_seer_hut" in text, f"{rel_path} must implement seer hut decoder", errors)
            require("def skip_hero" in text, f"{rel_path} must implement hero decoder", errors)
            require("def skip_witch_hut" in text, f"{rel_path} must implement witch hut decoder", errors)
            witch_body = function_body(text, "def skip_witch_hut", "def skip_scholar")
            require(
                'record["h3mVersion"] >= h3m.H3M_VERSION_AB' in witch_body,
                f"{rel_path} witch hut decoder must gate skill-mask bytes behind AB+",
                errors,
            )
            require("walker.skip(SKILLS_BYTES)" in witch_body, f"{rel_path} witch hut decoder must skip SKILLS_BYTES on AB+", errors)
            require("h3obj.OBJECT_SHIPYARD" in text, f"{rel_path} must use registry shipyard id 87", errors)
            body = function_body(text, "def skip_creature_generator", "def skip_resource")
            require("walker.read_u32()" in body, f"{rel_path} creature generator decoder must read owner u32", errors)
            require("ownerEncoding" in body and "h3m_readPlayer32" in body, f"{rel_path} creature generator decoder must record owner encoding", errors)
            require("creature_generator_family" in body, f"{rel_path} creature generator decoder must derive family from registry", errors)
            require("skip_message_and_guards" not in body, f"{rel_path} creature generator decoder must not use artifact-style message/guards", errors)
            require("sentinel" not in body, f"{rel_path} creature generator decoder must not treat owner as artifact sentinel", errors)
            require("OBJECT_RANDOM_ARTIFACT_RELIC = 70" not in text, f"{rel_path} must not map random relic artifact to id 70", errors)

    manifest_text = read_text(repo_root, "experiments/campaign_port_poc/build_homecoming_object_port_manifest.py")
    require("MONSTER_IDS = h3obj.MONSTER_OBJECT_IDS" in manifest_text, "manifest must consume registry monster ids", errors)
    require("ARTIFACT_IDS = h3obj.ARTIFACT_OBJECT_IDS" in manifest_text, "manifest must consume registry artifact ids", errors)
    require("CREATURE_GENERATOR_IDS = h3obj.FIXED_CREATURE_GENERATOR_IDS" in manifest_text, "manifest must consume registry fixed creature generator ids", errors)
    require("CAVE_ID = h3obj.OBJECT_SUBTERRANEAN_GATE" in manifest_text, "manifest must consume registry subterranean gate id", errors)
    require("WHIRLPOOL_ID = h3obj.OBJECT_WHIRLPOOL" in manifest_text, "manifest must consume registry whirlpool id", errors)
    require("CAVE_ID = 103" not in manifest_text and "WHIRLPOOL_ID = 111" not in manifest_text, "manifest must not hard-code travel link ids", errors)

    # The layered-atlas lane is retired; the same invariant now applies to the
    # raw_translation lane's shared object emitter.
    layered_objects_text = read_text(repo_root, "experiments/campaign_port_poc/approach_cell/layered_objects.py")
    require('"templateObjectId": h3obj.OBJECT_SUBTERRANEAN_GATE' in layered_objects_text, "layered_objects emitter must consume registry subterranean gate id", errors)
    require('"templateObjectId": 103' not in layered_objects_text, "layered_objects emitter must not hard-code subterranean gate id 103", errors)
    require("ARTIFACT_IDS = {66, 67, 68, 69, 70}" not in manifest_text, "manifest must not treat id 70 as artifact", errors)

    policy = json.loads(read_text(repo_root, "experiments/campaign_port_poc/homecoming_object_policy.json"))
    require(policy_object_ids(policy, "external_dwelling") == h3obj.FIXED_CREATURE_GENERATOR_IDS, "policy external_dwelling ids must cover fixed creature generator family", errors)
    require(policy_object_ids(policy, "artifact_pickup") == h3obj.RANDOM_ARTIFACT_OBJECT_IDS, "policy artifact_pickup ids must cover random artifact family and exclude id 70", errors)
    require(policy_object_ids(policy, "monster_stack") == h3obj.MONSTER_OBJECT_IDS, "policy monster_stack ids must cover all random monster levels", errors)

    review_text = read_text(repo_root, "experiments/campaign_port_poc/build_homecoming_mapping_review_menu.py")
    require("69: \"Random relic artifact pickup" in review_text, "review menu must describe id 69 as random relic artifact", errors)
    require("70: \"Random relic artifact pickup" not in review_text, "review menu must not describe id 70 as random relic artifact", errors)

    if errors:
        print("H3M object registry contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("H3M object registry contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())