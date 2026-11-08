#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CONSTRUCTION_PREFIX = "HoMM3 custom construction law diagnostic:"
ECONOMY_PREFIX = "HoMM3 custom economy law diagnostic:"
REGISTRATION_RE = re.compile(r"HoMM3 custom construction law diagnostics registered ([0-9]+) exact trace patch")
ECONOMY_REGISTRATION_RE = re.compile(r"HoMM3 custom economy law diagnostics registered ([0-9]+) exact trace patch")
STAGE_RE = re.compile(r"HoMM3 custom construction law diagnostic: ([a-z0-9-]+) ")
ECONOMY_STAGE_RE = re.compile(r"HoMM3 custom economy law diagnostic: ([a-z0-9-]+) ")
ACTIVE_LAW_RE = re.compile(r"activeKnownCustomLawsFromThisObject=\[(?P<state>[^\]]+)\]")
NONE_OR_UNRESOLVED_RE = re.compile(r"activeKnownCustomLawsFromThisObject=none-or-unresolved")


REQUIRED_CONSTRUCTION_STAGES = [
    "building-view-bind-candidate",
    "building-session-select-candidate",
    "building-session-cost-candidate",
    "buildings-manager-state-candidate",
    "buildings-manager-refresh-candidate",
    "building-view-update-candidate",
]


def read_log(path: Path) -> str:
    if path.is_dir():
        candidate = path / "LogOutput.log"
        if not candidate.exists():
            raise FileNotFoundError(f"{path} is a directory but has no LogOutput.log")
        path = candidate
    return path.read_text(encoding="utf-8-sig", errors="replace")


def line_numbered(text: str) -> list[tuple[int, str]]:
    return [(index + 1, line) for index, line in enumerate(text.splitlines())]


def analyze(text: str) -> dict[str, object]:
    lines = line_numbered(text)
    registration_count = None
    economy_registration_count = None
    construction_events: list[dict[str, object]] = []
    economy_events: list[dict[str, object]] = []
    active_law_events: list[dict[str, object]] = []
    none_or_unresolved_count = 0

    for lineno, line in lines:
        reg = REGISTRATION_RE.search(line)
        if reg:
            registration_count = int(reg.group(1))
        econ_reg = ECONOMY_REGISTRATION_RE.search(line)
        if econ_reg:
            economy_registration_count = int(econ_reg.group(1))

        stage = STAGE_RE.search(line)
        if stage:
            construction_events.append({"line": lineno, "stage": stage.group(1), "text": line})
        economy_stage = ECONOMY_STAGE_RE.search(line)
        if economy_stage:
            economy_events.append({"line": lineno, "stage": economy_stage.group(1), "text": line})

        active = ACTIVE_LAW_RE.search(line)
        if active:
            active_law_events.append({"line": lineno, "state": active.group("state"), "text": line})
        none_or_unresolved_count += len(NONE_OR_UNRESOLVED_RE.findall(line))

    stages_present = sorted({str(event["stage"]) for event in construction_events})
    economy_stages_present = sorted({str(event["stage"]) for event in economy_events})
    missing_stages = [stage for stage in REQUIRED_CONSTRUCTION_STAGES if stage not in stages_present]

    proof_gaps: list[str] = []
    if registration_count != 7:
        proof_gaps.append("construction diagnostic surface registration is not proven as 7 exact trace patches in this log")
    if economy_registration_count is None or economy_registration_count < 1:
        proof_gaps.append("economy diagnostic registration is missing, so charged resource mutation cannot be correlated")
    if not construction_events:
        proof_gaps.append("no construction interaction trace lines are present")
    if missing_stages:
        proof_gaps.append("missing construction stages: " + ", ".join(missing_stages))
    if "resource-add" not in economy_stages_present:
        proof_gaps.append("no economy resource-add trace is present")
    if not active_law_events:
        proof_gaps.append("no active custom law/rank was resolved from construction/economy trace objects")

    return {
        "schemaVersion": 1,
        "constructionRegistrationPatchCount": registration_count,
        "economyRegistrationPatchCount": economy_registration_count,
        "constructionTraceCount": len(construction_events),
        "economyTraceCount": len(economy_events),
        "constructionStagesPresent": stages_present,
        "missingConstructionStages": missing_stages,
        "economyStagesPresent": economy_stages_present,
        "activeLawResolutionCount": len(active_law_events),
        "noneOrUnresolvedMentionCount": none_or_unresolved_count,
        "packetPromotionReady": len(proof_gaps) == 0,
        "proofGaps": proof_gaps,
        "firstConstructionEvents": construction_events[:12],
        "firstEconomyEvents": economy_events[:12],
        "firstActiveLawEvents": active_law_events[:12],
    }


def emit_markdown(result: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Construction law capture analysis")
    lines.append("")
    lines.append("This report is static log analysis only. It does not promote packet proof state.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Construction registration patches: `{result['constructionRegistrationPatchCount']}`")
    lines.append(f"- Economy registration patches: `{result['economyRegistrationPatchCount']}`")
    lines.append(f"- Construction trace lines: `{result['constructionTraceCount']}`")
    lines.append(f"- Economy trace lines: `{result['economyTraceCount']}`")
    lines.append(f"- Active law/rank resolution lines: `{result['activeLawResolutionCount']}`")
    lines.append(f"- Packet promotion ready: `{result['packetPromotionReady']}`")
    lines.append("")
    lines.append("## Construction stages present")
    lines.append("")
    stages = result["constructionStagesPresent"]
    if stages:
        for stage in stages:
            lines.append(f"- `{stage}`")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Proof gaps")
    lines.append("")
    gaps = result["proofGaps"]
    if gaps:
        for gap in gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("None by mechanical log checklist. Human review is still required before promotion.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze construction packet runtime capture logs.")
    parser.add_argument("--log", type=Path, required=True, help="LogOutput.log path or capture directory containing LogOutput.log")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    parser.add_argument("--out", type=Path, help="Optional output path")
    args = parser.parse_args()

    result = analyze(read_log(args.log))
    output = json.dumps(result, indent=2) + "\n" if args.json else emit_markdown(result) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8", newline="\n")
    else:
        print(output, end="")
    return 0 if result["packetPromotionReady"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
