#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUEUE = ROOT / "artifacts" / "custom_law_static" / "custom_law_implementation_queue.json"
DEFAULT_SOURCE_MATRIX = ROOT / "custom_factions" / "custom_law_source_prepared_matrix.json"
DEFAULT_PREDICATE_MAP = ROOT / "custom_factions" / "custom_law_profile_predicate_surface_map.json"

FAMILY_PLANNER = {
    "Calendar": {"planMethod": "TryPlanCalendarEffect", "predicateMethod": "DescribeCalendarPredicates"},
    "Construction": {"planMethod": "TryPlanConstructionEffect", "predicateMethod": "DescribeConstructionPredicates"},
    "CounterattackDoctrine": {"planMethod": "TryPlanCounterattackDoctrineEffect", "predicateMethod": "DescribeCounterattackPredicates"},
    "Formation": {"planMethod": "TryPlanFormationEffect", "predicateMethod": "DescribeFormationPredicates"},
    "MoralePackage": {"planMethod": "TryPlanMoralePackageEffect", "predicateMethod": "DescribeMoralePackagePredicates"},
    "MoraleTrigger": {"planMethod": "TryPlanMoraleTriggerEffect", "predicateMethod": "DescribeMoraleTriggerPredicates"},
    "RewardEconomy": {"planMethod": "TryPlanRewardEconomyEffect", "predicateMethod": "DescribeRewardEconomyPredicates"},
    "SpellCooldown": {"planMethod": "TryPlanSpellCooldownEffect", "predicateMethod": "DescribeSpellCooldownPredicates"},
    "SpellSchool": {"planMethod": "TryPlanSpellSchoolEffect", "predicateMethod": "DescribeSpellSchoolPredicates"},
    "TrainingDamage": {"planMethod": "TryPlanTrainingDamageEffect", "predicateMethod": "DescribeTrainingDamagePredicates"},
    "Vision": {"planMethod": "TryPlanVisionEffect", "predicateMethod": "DescribeVisionPredicates"},
}


class PacketError(ValueError):
    pass


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PacketError(f"{label} must be an object")
    return value


def source_family(source_matrix: dict[str, Any], law_index: int) -> dict[str, Any]:
    families = require_object(source_matrix.get("families"), "source matrix families")
    family = families.get(str(law_index))
    if not isinstance(family, dict):
        raise PacketError(f"source-prepared matrix missing law index {law_index}")
    return family


def predicate_details(predicate_map: dict[str, Any], predicates: list[str]) -> list[dict[str, Any]]:
    entries = require_object(predicate_map.get("predicates"), "predicate surface map predicates")
    result: list[dict[str, Any]] = []
    for predicate in predicates:
        if not isinstance(predicate, str):
            raise PacketError(f"invalid predicate in queue profile: {predicate!r}")
        entry = entries.get(predicate)
        if not isinstance(entry, dict):
            raise PacketError(f"predicate {predicate} missing from surface map")
        result.append(
            {
                "predicate": predicate,
                "status": entry.get("status"),
                "surfaceIds": entry.get("surfaceIds") if isinstance(entry.get("surfaceIds"), list) else [],
                "notes": entry.get("notes"),
            }
        )
    return result


def build_packets(queue: dict[str, Any], source_matrix: dict[str, Any], predicate_map: dict[str, Any]) -> dict[str, Any]:
    entries = queue.get("entries")
    if not isinstance(entries, list):
        raise PacketError("implementation queue has no entries list")
    packets: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise PacketError("implementation queue contains a non-object entry")
        law_index = entry.get("lawIndex")
        profile = entry.get("profileCoverage")
        implementation_status = entry.get("status")
        if not isinstance(law_index, int):
            raise PacketError(f"queue row has invalid lawIndex: {entry!r}")
        if not isinstance(profile, dict):
            if implementation_status != "native-exact":
                errors.append(f"{entry.get('lawSid')}: missing profile coverage")
            profile = {}
        family_name = profile.get("family")
        planner = FAMILY_PLANNER.get(str(family_name))
        if planner is None:
            if implementation_status != "native-exact":
                errors.append(f"{entry.get('lawSid')}: no planner mapping for family {family_name!r}")
            planner = {"planMethod": None, "predicateMethod": None}
        matrix_family = source_family(source_matrix, law_index)
        predicates = profile.get("requiredPredicates") if isinstance(profile.get("requiredPredicates"), list) else []
        predicate_rows = predicate_details(predicate_map, predicates)
        packet = {
            "lawSid": entry.get("lawSid"),
            "faction": entry.get("faction"),
            "lawIndex": law_index,
            "name": entry.get("name"),
            "targetMechanic": entry.get("targetMechanic"),
            "implementationStatus": entry.get("status"),
            "readiness": entry.get("readiness"),
            "packet": entry.get("packet"),
            "packetProof": entry.get("packetProof"),
            "handler": profile.get("handler") or matrix_family.get("handler"),
            "profile": {
                "family": family_name,
                "effectKey": profile.get("effectKey"),
                "dataOnly": profile.get("dataOnly"),
                "numericEffects": profile.get("numericEffects") if isinstance(profile.get("numericEffects"), dict) else {},
                "evidenceBoundary": profile.get("evidenceBoundary"),
                "sourceFile": profile.get("sourceFile"),
                "sourceLine": profile.get("sourceLine"),
            },
            "planner": planner,
            "sourceSeams": {
                "adapter": matrix_family.get("adapter"),
                "runtime": matrix_family.get("runtime"),
                "currentCapability": matrix_family.get("currentCapability"),
                "blockedBy": matrix_family.get("blockedBy") if isinstance(matrix_family.get("blockedBy"), list) else [],
            },
            "predicateSurfaces": predicate_rows,
            "sourceOverride": entry.get("sourceOverride"),
            "strictCandidate": entry.get("strictCandidate"),
            "implementationBoundary": boundary_for(entry),
        }
        packets.append(packet)
    if errors:
        raise PacketError("; ".join(errors))
    return {
        "schemaVersion": 1,
        "purpose": "Per-law static implementation packets for custom faction laws. This is source-prepared handoff data only and does not authorize gameplay mutation.",
        "boundary": "Packet gameplayAllowed remains authoritative. Runtime-unproven packets must not mutate gameplay.",
        "inputs": queue.get("inputs"),
        "summary": summarize(packets),
        "packets": packets,
    }


def boundary_for(entry: dict[str, Any]) -> str:
    readiness = entry.get("readiness")
    if readiness == "native-exact-ready":
        return "Native/data row may remain; no custom runtime mutation required for current target."
    if readiness == "temporary-compromise-playable-strict-placeholder-ready":
        return "Playable source contains a known compromise; strict candidate strips it. Do not promote custom gameplay until packet runtime proof exists."
    if readiness == "source-prepared-runtime-blocked":
        return "Source profile/planner exists, but gameplay is blocked by packet proof gate and predicate runtime surfaces."
    return "Review readiness before implementation; do not add fallback behavior."


def summarize(packets: list[dict[str, Any]]) -> dict[str, Any]:
    by_readiness = Counter(str(packet.get("readiness")) for packet in packets)
    by_packet = Counter(str(packet.get("packet")) for packet in packets)
    predicate_status = Counter()
    for packet in packets:
        for predicate in packet.get("predicateSurfaces", []):
            if isinstance(predicate, dict):
                predicate_status[str(predicate.get("status"))] += 1
    return {
        "total": len(packets),
        "byReadiness": dict(sorted(by_readiness.items())),
        "byPacket": dict(sorted(by_packet.items())),
        "predicateSurfaceStatuses": dict(sorted(predicate_status.items())),
    }


def md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(doc: dict[str, Any]) -> str:
    packets = doc["packets"]
    by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in packets:
        by_packet[str(packet["packet"])].append(packet)
    lines: list[str] = []
    lines.append("# Custom Law Static Implementation Packets")
    lines.append("")
    lines.append("This is source-prepared handoff data only. It does not build, deploy, runtime-prove, or authorize gameplay mutation.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Total packets | {doc['summary']['total']} |")
    for readiness, count in doc["summary"]["byReadiness"].items():
        lines.append(f"| Readiness `{readiness}` | {count} |")
    for status, count in doc["summary"]["predicateSurfaceStatuses"].items():
        lines.append(f"| Predicate surface `{status}` | {count} |")
    lines.append("")
    lines.append("## Packet table")
    lines.append("")
    lines.append("| Packet | Faction | Law | Readiness | Planner | Handler | Predicates | Boundary |")
    lines.append("|---|---|---|---|---|---|---:|---|")
    for packet_name in sorted(by_packet):
        for packet in by_packet[packet_name]:
            planner = packet.get("planner") if isinstance(packet.get("planner"), dict) else {}
            predicate_count = len(packet.get("predicateSurfaces", [])) if isinstance(packet.get("predicateSurfaces"), list) else 0
            lines.append(
                "| `{packet}` | `{faction}` | `{sid}` / {name} | `{readiness}` | `{planner}` | `{handler}` | {predicates} | {boundary} |".format(
                    packet=md(packet.get("packet")),
                    faction=md(packet.get("faction")),
                    sid=md(packet.get("lawSid")),
                    name=md(packet.get("name")),
                    readiness=md(packet.get("readiness")),
                    planner=md(planner.get("planMethod")),
                    handler=md(packet.get("handler")),
                    predicates=predicate_count,
                    boundary=md(packet.get("implementationBoundary")),
                )
            )
    lines.append("")
    lines.append("## Per-law details")
    lines.append("")
    for packet in packets:
        lines.append(f"### `{packet['lawSid']}` {packet['name']}")
        lines.append("")
        lines.append(f"- Faction: `{packet['faction']}`")
        lines.append(f"- Packet/handler: `{packet['packet']}` / `{packet['handler']}`")
        lines.append(f"- Readiness: `{packet['readiness']}`")
        lines.append(f"- Planner: `{packet['planner'].get('planMethod')}` with `{packet['planner'].get('predicateMethod')}`")
        lines.append(f"- Source seams: adapter `{packet['sourceSeams'].get('adapter')}`, runtime `{packet['sourceSeams'].get('runtime')}`")
        lines.append(f"- Target mechanic: {md(packet['targetMechanic'])}")
        lines.append(f"- Profile effect key: `{packet['profile'].get('effectKey')}`")
        lines.append(f"- Profile boundary: {md(packet['profile'].get('evidenceBoundary'))}")
        lines.append(f"- Implementation boundary: {md(packet['implementationBoundary'])}")
        blockers = packet["sourceSeams"].get("blockedBy") if isinstance(packet["sourceSeams"], dict) else []
        lines.append("- Blocked by: " + (", ".join(f"`{md(item)}`" for item in blockers) if blockers else "none"))
        predicates = packet.get("predicateSurfaces", [])
        if predicates:
            lines.append("")
            lines.append("| Predicate | Status | Surfaces | Notes |")
            lines.append("|---|---|---|---|")
            for predicate in predicates:
                surfaces = predicate.get("surfaceIds") if isinstance(predicate.get("surfaceIds"), list) else []
                lines.append(
                    "| `{predicate}` | `{status}` | {surfaces} | {notes} |".format(
                        predicate=md(predicate.get("predicate")),
                        status=md(predicate.get("status")),
                        surfaces=", ".join(f"`{md(surface)}`" for surface in surfaces) or "-",
                        notes=md(predicate.get("notes")),
                    )
                )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate per-law static implementation packets for custom faction laws.")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--source-matrix", type=Path, default=DEFAULT_SOURCE_MATRIX)
    parser.add_argument("--predicate-map", type=Path, default=DEFAULT_PREDICATE_MAP)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()

    try:
        doc = build_packets(
            require_object(load_json(args.queue), "implementation queue"),
            require_object(load_json(args.source_matrix), "source-prepared matrix"),
            require_object(load_json(args.predicate_map), "predicate surface map"),
        )
    except (OSError, json.JSONDecodeError, PacketError) as exc:
        print(f"custom law static implementation packet generation failed: {exc}", file=sys.stderr)
        return 1

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {rel(args.out_json)}")
    markdown = render_markdown(doc)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(markdown + "\n", encoding="utf-8")
        print(f"wrote {rel(args.out_md)}")
    if not args.out_json and not args.out_md:
        print(markdown)
    print(f"custom law static implementation packets generated: {doc['summary']['total']} packet(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
