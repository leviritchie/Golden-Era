#!/usr/bin/env python3
"""Regenerate remaining-RoE LocKit rows with quest-log objective bullets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from campaign_objective_text import objective_loc_rows  # noqa: E402
from h3c_mission_source import load_h3c_block  # noqa: E402
from scenario_menu_shell import resolve_menu_shell  # noqa: E402

MANIFEST = ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json"
OUT = ROOT / "experiments" / "campaign_port_poc" / "remaining_roe_localization.py"


def build_rows() -> dict[str, str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows: dict[str, str] = {}
    for mission in manifest["missions"]:
        mission_id = str(mission["missionId"])
        map_sid = str(mission["mapSid"])
        shell = resolve_menu_shell(map_sid)
        source = load_h3c_block(mission["campaignEntry"], int(mission["blockIndex"]))
        title = (source.summary.title or mission_id).strip()
        full_desc = (source.summary.description or title).strip()
        rows.update(
            objective_loc_rows(
                mission_id=mission_id,
                title=title,
                full_description=full_desc,
                menu_title_sid=shell.title_sid,
                menu_desc_sid=shell.desc_sid,
            )
        )
    return rows


def write_rows(rows: dict[str, str]) -> Path:
    lines = [
        '"""English LocKit rows for remaining RoE campaign raw_translation maps.',
        "",
        "Auto-derived from H3C scenario title/description. Menu shell keeps vanilla",
        "budgets (title<=23, desc<=172). Quest-log attributes use unclipped",
        "main_goal_obj_* bullets (native quest_sub pattern). Merged into",
        "homecoming_localization.CUSTOM_MAPS_EN.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "REMAINING_ROE_CUSTOM_MAPS_EN: dict[str, str] = {",
    ]
    for key, value in rows.items():
        lines.append(f"    {key!r}: {value!r},")
    lines.append("}")
    lines.append("")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT


def main() -> int:
    path = write_rows(build_rows())
    print(f"Wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
