#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def target_sort_key(target: dict[str, Any]) -> tuple[str, int, str]:
    faction = str(target.get("faction") or "")
    law_index = target.get("lawIndex")
    index = law_index if isinstance(law_index, int) else 0
    return (faction, index, str(target.get("lawSid") or ""))


def family_packet(families: dict[str, Any], law_index: Any) -> str:
    if not isinstance(law_index, int):
        return "unknown"
    entry = families.get(str(law_index))
    if isinstance(entry, dict):
        packet = entry.get("packet")
        if isinstance(packet, str) and packet:
            return packet
    return "unknown"


def emit_markdown(doc: dict[str, Any]) -> str:
    families = doc.get("families") if isinstance(doc.get("families"), dict) else {}
    targets = [target for target in doc.get("targets", []) if isinstance(target, dict)]

    by_status: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        status = str(target.get("implementationStatus") or "unknown")
        packet = family_packet(families, target.get("lawIndex"))
        by_status[status].append(target)
        by_packet[packet].append(target)

    lines: list[str] = []
    lines.append("# Custom law target coverage report")
    lines.append("")
    lines.append("Generated from `custom_factions/custom_law_targets.json`.")
    lines.append("")
    lines.append("This report is static planning evidence only. It does not prove law override correctness, build success, runtime behavior, or packet readiness.")
    lines.append("")
    lines.append("## Status counts")
    lines.append("")
    lines.append("| Status | Count | Meaning |")
    lines.append("|---|---:|---|")
    meanings = {
        "native-exact": "Current intended mechanic can be represented by exact native rows.",
        "temporary-compromise": "Playable scaffold exists, but it is not the final mechanic.",
        "needs-runtime": "Original mechanic requires a proven runtime packet.",
        "blocked": "Original mechanic lacks an accepted native-friendly surface.",
        "unknown": "Malformed or unsupported status.",
    }
    for status in sorted(by_status):
        lines.append(f"| `{status}` | {len(by_status[status])} | {meanings.get(status, 'Unrecognized status.')} |")

    lines.append("")
    lines.append("## Runtime work by packet")
    lines.append("")
    lines.append("| Packet | Native exact | Temporary compromise | Needs runtime | Blocked |")
    lines.append("|---|---:|---:|---:|---:|")
    for packet in sorted(by_packet):
        counts = defaultdict(int)
        for target in by_packet[packet]:
            counts[str(target.get("implementationStatus") or "unknown")] += 1
        lines.append(
            f"| `{packet}` | {counts['native-exact']} | {counts['temporary-compromise']} | {counts['needs-runtime']} | {counts['blocked']} |"
        )

    lines.append("")
    lines.append("## Temporary compromises")
    lines.append("")
    temp = sorted(by_status.get("temporary-compromise", []), key=target_sort_key)
    if not temp:
        lines.append("None.")
    else:
        lines.append("| Faction | Law | Target mechanic |")
        lines.append("|---|---|---|")
        for target in temp:
            lines.append(
                f"| `{target.get('faction')}` | `{target.get('lawSid')}` / {target.get('name')} | {target.get('targetMechanic')} |"
            )

    lines.append("")
    lines.append("## Needs runtime implementation")
    lines.append("")
    needs = sorted(by_status.get("needs-runtime", []), key=lambda t: (family_packet(families, t.get("lawIndex")), *target_sort_key(t)))
    if not needs:
        lines.append("None.")
    else:
        lines.append("| Packet | Faction | Law | Target mechanic |")
        lines.append("|---|---|---|---|")
        for target in needs:
            lines.append(
                f"| `{family_packet(families, target.get('lawIndex'))}` | `{target.get('faction')}` | `{target.get('lawSid')}` / {target.get('name')} | {target.get('targetMechanic')} |"
            )

    lines.append("")
    lines.append("## Native-exact baseline")
    lines.append("")
    exact = sorted(by_status.get("native-exact", []), key=target_sort_key)
    if not exact:
        lines.append("None.")
    else:
        lines.append("| Faction | Law | Target mechanic |")
        lines.append("|---|---|---|")
        for target in exact:
            lines.append(
                f"| `{target.get('faction')}` | `{target.get('lawSid')}` / {target.get('name')} | {target.get('targetMechanic')} |"
            )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report no-compromise custom law target coverage.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if not args.targets.exists():
        print(f"error: missing targets file: {args.targets}", file=sys.stderr)
        return 1

    doc = load_json(args.targets)
    if not isinstance(doc, dict):
        print("error: targets root must be an object", file=sys.stderr)
        return 1

    markdown = emit_markdown(doc)
    if args.out is None:
        print(markdown)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
