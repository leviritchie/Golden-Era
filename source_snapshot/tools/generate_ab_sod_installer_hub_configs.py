#!/usr/bin/env python3
"""Emit installer HUB_CONFIGS fragment for AB/SoD hubs (and optionally patch installer)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"


def hub_config_entries() -> dict:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    configs: dict = {}
    for hub in index["hubs"]:
        hub_key = hub["hub"]
        faction_tag = hub["factionTag"]
        missions = hub["missions"]
        map_installs = []
        mission_files = []
        for mission_id in missions:
            mission_files.append(f"{hub['prefix']}_{mission_id}.json")
            map_sid = f"h3_{faction_tag}_{mission_id}_raw_translation"
            map_installs.append(
                {
                    "mapSid": map_sid,
                    "artifact": Path(
                        f"artifacts/campaign_port_poc/ab_sod_campaigns/{mission_id}/raw_translation_map/maps"
                    ),
                    "coreOverlay": Path(
                        f"artifacts/campaign_port_poc/ab_sod_campaigns/{mission_id}/raw_translation_map/core_overlay"
                    ),
                }
            )
        configs[hub_key] = {
            "hubSid": hub["hubSid"],
            "campaignHeroSid": hub["heroSid"],
            "weaveDir": Path(
                f"artifacts/campaign_port_poc/ab_sod_campaigns/continuity_weave_{hub_key}"
            ),
            "missions": tuple(mission_files),
            "mapInstalls": map_installs,
        }
    return configs


def main() -> int:
    # Import Path into generated repr by building Python source.
    configs = hub_config_entries()
    lines = ["# --- BEGIN AB/SoD HUB_CONFIGS (generated) ---"]
    for hub_key, cfg in configs.items():
        lines.append(f'    "{hub_key}": {{')
        lines.append(f'        "hubSid": {cfg["hubSid"]!r},')
        lines.append(f'        "campaignHeroSid": {cfg["campaignHeroSid"]!r},')
        lines.append(
            f'        "weaveDir": Path({str(cfg["weaveDir"]).replace(chr(92), "/")!r}),'
        )
        lines.append('        "missions": (')
        for mission_file in cfg["missions"]:
            lines.append(f"            {mission_file!r},")
        lines.append("        ),")
        lines.append('        "mapInstalls": [')
        for row in cfg["mapInstalls"]:
            art = str(row["artifact"]).replace("\\", "/")
            overlay = str(row["coreOverlay"]).replace("\\", "/")
            lines.append("            {")
            lines.append(f'                "mapSid": {row["mapSid"]!r},')
            lines.append(f'                "artifact": Path({art!r}),')
            lines.append(f'                "coreOverlay": Path({overlay!r}),')
            lines.append("            },")
        lines.append("        ],")
        lines.append("    },")
    lines.append("    # --- END AB/SoD HUB_CONFIGS ---")
    out = ROOT / "scenarios" / "ab_sod_campaigns" / "installer_hub_configs.fragment.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
