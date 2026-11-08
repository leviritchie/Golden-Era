#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_PACKET_PROOFS_PATH = ROOT / "custom_factions" / "custom_law_packet_proofs.json"
DEFAULT_EFFECT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_PREDICATE_MAP_PATH = ROOT / "custom_factions" / "custom_law_profile_predicate_surface_map.json"
DEFAULT_SOURCE_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
DEFAULT_STRICT_OVERRIDE_DIR = ROOT / "artifacts" / "custom_law_static" / "strict_law_overrides"


LAW_INDEX_PROFILE_REQUIREMENTS = {
    2: ("Vision", "vision.reveal"),
    6: ("TrainingDamage", "damage.training"),
    13: ("CounterattackDoctrine", "counterattack.doctrine"),
    15: ("SpellSchool", "spell.low"),
    18: ("Formation", "battle.melee-formation"),
    19: ("Formation", "battle.ranged-formation"),
    21: ("RewardEconomy", "reward.gold-economy"),
    22: ("MoralePackage", "morale.package"),
    25: ("MoraleTrigger", "morale.trigger"),
    27: ("SpellSchool", "spell.high"),
    28: ("Construction", "construction.commit"),
    33: ("Calendar", "reward.calendar"),
    34: ("SpellCooldown", "spell.cooldown"),
}

RUNTIME_BLOCKING_ACTION = "Keep gameplay disabled. Use the source-prepared profile and predicate surface map to design/prove the packet; strict candidate rows must stay bonus-free until then."


class QueueError(ValueError):
    pass


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def require_object(doc: Any, path: Path) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise QueueError(f"{rel(path)} root must be an object")
    return doc


def family_packet(families: dict[str, Any], law_index: Any) -> str:
    if not isinstance(law_index, int):
        return "unknown"
    entry = families.get(str(law_index))
    if isinstance(entry, dict) and isinstance(entry.get("packet"), str):
        return str(entry["packet"])
    return "unknown"


def load_override_rows(directory: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        doc = require_object(load_json(path), path)
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            raise QueueError(f"{rel(path)} has no lawOverrides object")
        for sid, row in overrides.items():
            if not isinstance(sid, str):
                raise QueueError(f"{rel(path)} has a non-string law override key")
            if not isinstance(row, dict):
                raise QueueError(f"{rel(path)} row for {sid} is not an object")
            if sid in rows:
                raise QueueError(f"duplicate law override row for {sid}")
            rows[sid] = row
    return rows


def bonus_count(row: dict[str, Any] | None) -> int:
    if row is None:
        return 0
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return 0
    total = 0
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list):
            total += len(bonuses)
    return total


def level_count(row: dict[str, Any] | None) -> int:
    levels = row.get("parametersPerLevel") if isinstance(row, dict) else None
    return len(levels) if isinstance(levels, list) else 0


def build_profile_index(inventory: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    rows = inventory.get("rows")
    if not isinstance(rows, list):
        raise QueueError("custom_law_effect_plan_inventory.json has no rows list")
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("factionSid")),
            str(row.get("family")),
            str(row.get("handler")),
            str(row.get("lawName")),
        )
        if key in index:
            raise QueueError(f"duplicate effect profile row for {key}")
        index[key] = row
    return index


def profile_for_target(target: dict[str, Any], profile_index: dict[tuple[str, str, str, str], dict[str, Any]]) -> dict[str, Any] | None:
    law_index = target.get("lawIndex")
    if not isinstance(law_index, int):
        return None
    requirement = LAW_INDEX_PROFILE_REQUIREMENTS.get(law_index)
    if requirement is None:
        return None
    family, handler = requirement
    faction = target.get("faction")
    name = target.get("name")
    if not isinstance(faction, str) or not isinstance(name, str):
        return None
    return profile_index.get((f"homm3_{faction}", family, handler, name))


def packet_info(packet_proofs: dict[str, Any], packet: str) -> dict[str, Any]:
    packets = packet_proofs.get("packets")
    if not isinstance(packets, dict):
        raise QueueError("custom_law_packet_proofs.json has no packets object")
    info = packets.get(packet)
    if not isinstance(info, dict):
        raise QueueError(f"missing packet proof entry for {packet}")
    return info


def predicate_counts(profile: dict[str, Any] | None, predicate_map: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if profile is None:
        return {"total": 0, "mapped": 0, "partial": 0, "missing": 0, "rejected": 0, "unmapped": 0}
    predicates = profile.get("requiredPredicates")
    if not isinstance(predicates, list):
        predicates = []
    entries = predicate_map.get("predicates") if isinstance(predicate_map, dict) else None
    if not isinstance(entries, dict):
        raise QueueError("custom_law_profile_predicate_surface_map.json has no predicates object")
    for predicate in predicates:
        if not isinstance(predicate, str):
            continue
        counts["total"] += 1
        entry = entries.get(predicate)
        if not isinstance(entry, dict):
            counts["unmapped"] += 1
            continue
        status = entry.get("status")
        if isinstance(status, str):
            counts[status] += 1
        else:
            counts["unmapped"] += 1
    return {key: counts.get(key, 0) for key in ("total", "mapped", "partial", "missing", "rejected", "unmapped")}


def strict_status(status: str, strict_row: dict[str, Any] | None) -> str:
    count = bonus_count(strict_row)
    if strict_row is None:
        return "missing"
    if status == "native-exact":
        return "native-row-present"
    if count == 0:
        return "bonus-free-placeholder"
    return "has-concrete-bonuses"


def source_status(source_row: dict[str, Any] | None) -> str:
    if source_row is None:
        return "missing"
    if bonus_count(source_row) > 0:
        return "playable-concrete-row"
    return "bonus-free-row"


def classify_readiness(
    target_status: str,
    packet: str,
    packet_proof: dict[str, Any],
    profile: dict[str, Any] | None,
    predicates: dict[str, int],
    source_row: dict[str, Any] | None,
    strict_row: dict[str, Any] | None,
) -> tuple[str, str]:
    gameplay_allowed = packet_proof.get("gameplayAllowed") is True
    strict = strict_status(target_status, strict_row)
    if target_status == "native-exact":
        if source_row is None:
            return "native-exact-source-missing", "Restore or verify the exact native/data row before relying on this target."
        return "native-exact-ready", "Keep the exact native/data row; no custom runtime implementation is needed for the current target mechanic."
    if profile is None:
        return "profile-missing", "Add a source-prepared effect profile matching this target before any implementation work."
    if predicates.get("missing", 0) or predicates.get("rejected", 0) or predicates.get("unmapped", 0):
        return "source-prepared-surface-gap", "Resolve missing/rejected predicate surface mappings before runtime proof or gameplay implementation."
    if strict != "bonus-free-placeholder":
        return "strict-placeholder-not-ready", "Regenerate or repair strict no-compromise candidates so this non-final target has no concrete bonuses."
    if gameplay_allowed:
        return "runtime-gate-open-ready-to-implement", "Packet proof gate allows gameplay; implement through the prepared handler/profile path with packet-specific acceptance checks."
    if target_status == "temporary-compromise":
        return "temporary-compromise-playable-strict-placeholder-ready", RUNTIME_BLOCKING_ACTION
    if target_status == "needs-runtime":
        return "source-prepared-runtime-blocked", RUNTIME_BLOCKING_ACTION
    if target_status == "blocked":
        return "blocked-needs-surface", "Do not implement; first find and prove one native-friendly surface."
    return "unknown-status-review-required", "Fix unsupported target implementationStatus before implementation."


def queue_entries(
    targets_doc: dict[str, Any],
    packet_proofs: dict[str, Any],
    inventory: dict[str, Any],
    predicate_map: dict[str, Any],
    source_rows: dict[str, dict[str, Any]],
    strict_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    families = targets_doc.get("families") if isinstance(targets_doc.get("families"), dict) else {}
    targets = targets_doc.get("targets")
    if not isinstance(targets, list):
        raise QueueError("custom_law_targets.json has no targets list")
    profile_index = build_profile_index(inventory)
    entries: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            raise QueueError("custom_law_targets.json contains a non-object target")
        sid = target.get("lawSid")
        law_index = target.get("lawIndex")
        target_status = str(target.get("implementationStatus") or "unknown")
        if not isinstance(sid, str) or not isinstance(law_index, int):
            raise QueueError(f"invalid target row: {target!r}")
        packet = family_packet(families, law_index)
        proof = packet_info(packet_proofs, packet)
        profile = profile_for_target(target, profile_index)
        predicates = predicate_counts(profile, predicate_map)
        source_row = source_rows.get(sid)
        strict_row = strict_rows.get(sid)
        readiness, action = classify_readiness(target_status, packet, proof, profile, predicates, source_row, strict_row)
        profile_summary: dict[str, Any] | None = None
        if profile is not None:
            profile_summary = {
                "family": profile.get("family"),
                "handler": profile.get("handler"),
                "effectKey": profile.get("effectKey"),
                "dataOnly": profile.get("dataOnly"),
                "requiredPredicates": profile.get("requiredPredicates") if isinstance(profile.get("requiredPredicates"), list) else [],
                "numericEffects": profile.get("numericEffects") if isinstance(profile.get("numericEffects"), dict) else {},
                "evidenceBoundary": profile.get("evidenceBoundary"),
                "sourceFile": profile.get("sourceFile"),
                "sourceLine": profile.get("sourceLine"),
            }
        entries.append(
            {
                "packet": packet,
                "status": target_status,
                "faction": target.get("faction"),
                "lawIndex": law_index,
                "lawSid": sid,
                "name": target.get("name"),
                "targetMechanic": target.get("targetMechanic"),
                "packetProof": {
                    "proofStatus": proof.get("proofStatus"),
                    "gameplayAllowed": proof.get("gameplayAllowed"),
                    "lastEvidenceArtifact": proof.get("lastEvidenceArtifact"),
                },
                "profileCoverage": profile_summary,
                "predicateSurfaceCounts": predicates,
                "sourceOverride": {
                    "status": source_status(source_row),
                    "bonusCount": bonus_count(source_row),
                    "levelCount": level_count(source_row),
                },
                "strictCandidate": {
                    "status": strict_status(target_status, strict_row),
                    "bonusCount": bonus_count(strict_row),
                    "levelCount": level_count(strict_row),
                },
                "readiness": readiness,
                "withoutRuntimeAction": action,
            }
        )
    return sorted(entries, key=lambda e: (str(e["packet"]), str(e["readiness"]), str(e["faction"]), int(e["lawIndex"]), str(e["lawSid"])))


def markdown_escape(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def counts_by(entries: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(entry.get(key, "unknown")) for entry in entries)


def emit_markdown(entries: list[dict[str, Any]], source_paths: dict[str, str]) -> str:
    by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        by_packet[str(entry["packet"])].append(entry)

    lines: list[str] = []
    lines.append("# Custom law implementation readiness queue")
    lines.append("")
    lines.append("Generated from target specs, packet proof ledger, source-prepared effect profiles, predicate surface mappings, playable law overrides, and strict no-compromise override candidates.")
    lines.append("")
    lines.append("Boundary: this is a static/source-prepared readiness artifact. It does not build, launch, mutate Core, prove runtime event reachability, prove active law/rank resolution, or authorize gameplay mutation.")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for label, path in source_paths.items():
        lines.append(f"- `{label}`: `{path}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Total target laws | {len(entries)} |")
    for status, count in sorted(counts_by(entries, "status").items()):
        lines.append(f"| Target status `{status}` | {count} |")
    for readiness, count in sorted(counts_by(entries, "readiness").items()):
        lines.append(f"| Readiness `{readiness}` | {count} |")
    lines.append("")
    lines.append("## Packet proof gates")
    lines.append("")
    lines.append("| Packet | Laws | Gameplay allowed | Proof status |")
    lines.append("|---|---:|---|---|")
    for packet in sorted(by_packet):
        proof = by_packet[packet][0]["packetProof"]
        lines.append(
            "| `{packet}` | {count} | `{allowed}` | `{proof}` |".format(
                packet=packet,
                count=len(by_packet[packet]),
                allowed=proof.get("gameplayAllowed"),
                proof=markdown_escape(proof.get("proofStatus")),
            )
        )
    lines.append("")
    lines.append("## No-runtime implementation decision")
    lines.append("")
    lines.append("| Readiness | Meaning |")
    lines.append("|---|---|")
    lines.append("| `native-exact-ready` | Static/native row can remain as the intended mechanic. |")
    lines.append("| `source-prepared-runtime-blocked` | A matching source profile and predicate map exist, but packet gameplay remains disabled until runtime proof. |")
    lines.append("| `temporary-compromise-playable-strict-placeholder-ready` | Playable source still has a known compromise, but the strict candidate strips it to a no-effect placeholder. |")
    lines.append("| `source-prepared-surface-gap` | The profile exists, but one or more predicates are missing/rejected/unmapped in the surface matrix. |")
    lines.append("| `strict-placeholder-not-ready` | A non-final target still has concrete bonuses in the strict candidate artifact. |")
    lines.append("| `profile-missing` | No source-prepared profile matches the target; implementation would be guesswork. |")
    lines.append("| `runtime-gate-open-ready-to-implement` | Packet proof gate is open; implementation may mutate gameplay through the prepared path. |")
    lines.append("")

    for packet in sorted(by_packet):
        lines.append(f"## Packet `{packet}`")
        lines.append("")
        lines.append("| Readiness | Faction | Law | Profile | Predicates | Source bonuses | Strict bonuses | Action without runtime proof | Target mechanic |")
        lines.append("|---|---|---|---|---:|---:|---:|---|---|")
        for entry in by_packet[packet]:
            profile = entry.get("profileCoverage")
            if isinstance(profile, dict):
                profile_text = f"{profile.get('family')}/{profile.get('handler')} `{profile.get('effectKey')}`"
            else:
                profile_text = "missing"
            predicates = entry["predicateSurfaceCounts"]
            predicate_text = "{total} total; {mapped} mapped; {partial} partial; {missing} missing; {rejected} rejected; {unmapped} unmapped".format(**predicates)
            lines.append(
                "| `{readiness}` | `{faction}` | `{sid}` / {name} | {profile} | {predicates} | {source_bonus} | {strict_bonus} | {action} | {target} |".format(
                    readiness=markdown_escape(entry["readiness"]),
                    faction=markdown_escape(entry["faction"]),
                    sid=markdown_escape(entry["lawSid"]),
                    name=markdown_escape(entry["name"]),
                    profile=markdown_escape(profile_text),
                    predicates=markdown_escape(predicate_text),
                    source_bonus=entry["sourceOverride"]["bonusCount"],
                    strict_bonus=entry["strictCandidate"]["bonusCount"],
                    action=markdown_escape(entry["withoutRuntimeAction"]),
                    target=markdown_escape(entry["targetMechanic"]),
                )
            )
        lines.append("")
    return "\n".join(lines)


def build_queue(args: argparse.Namespace) -> dict[str, Any]:
    targets_path = args.targets
    packet_proofs_path = args.packet_proofs
    inventory_path = args.effect_inventory
    predicate_map_path = args.predicate_map
    for path in (targets_path, packet_proofs_path, inventory_path, predicate_map_path):
        if not path.exists():
            raise QueueError(f"missing required input: {rel(path)}")
    source_rows = load_override_rows(args.source_override_dir)
    strict_rows = load_override_rows(args.strict_override_dir)
    targets_doc = require_object(load_json(targets_path), targets_path)
    entries = queue_entries(
        targets_doc,
        require_object(load_json(packet_proofs_path), packet_proofs_path),
        require_object(load_json(inventory_path), inventory_path),
        require_object(load_json(predicate_map_path), predicate_map_path),
        source_rows,
        strict_rows,
    )
    return {
        "schemaVersion": 2,
        "purpose": "Static/source-prepared readiness queue for custom faction law implementation without runtime evidence.",
        "boundary": "Does not authorize gameplay mutation; packet gameplayAllowed remains authoritative.",
        "inputs": {
            "targets": rel(targets_path),
            "packetProofs": rel(packet_proofs_path),
            "effectInventory": rel(inventory_path),
            "predicateSurfaceMap": rel(predicate_map_path),
            "sourceOverrideDir": rel(args.source_override_dir),
            "strictOverrideDir": rel(args.strict_override_dir),
        },
        "summary": {
            "total": len(entries),
            "byStatus": dict(sorted(counts_by(entries, "status").items())),
            "byReadiness": dict(sorted(counts_by(entries, "readiness").items())),
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a static no-runtime custom law implementation readiness queue.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--packet-proofs", type=Path, default=DEFAULT_PACKET_PROOFS_PATH)
    parser.add_argument("--effect-inventory", type=Path, default=DEFAULT_EFFECT_INVENTORY_PATH)
    parser.add_argument("--predicate-map", type=Path, default=DEFAULT_PREDICATE_MAP_PATH)
    parser.add_argument("--source-override-dir", type=Path, default=DEFAULT_SOURCE_OVERRIDE_DIR)
    parser.add_argument("--strict-override-dir", type=Path, default=DEFAULT_STRICT_OVERRIDE_DIR)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout or --out instead of Markdown.")
    args = parser.parse_args()

    try:
        queue = build_queue(args)
    except (OSError, json.JSONDecodeError, QueueError) as exc:
        print(f"custom law implementation queue failed: {exc}", file=sys.stderr)
        return 1

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        output = json.dumps(queue, indent=2, sort_keys=True) + "\n"
    else:
        output = emit_markdown(queue["entries"], queue["inputs"])
    if args.out is None:
        print(output)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output if output.endswith("\n") else output + "\n", encoding="utf-8")
        print(f"wrote {rel(args.out)}")
    if args.out_json:
        print(f"wrote {rel(args.out_json)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
