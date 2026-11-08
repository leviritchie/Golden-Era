#!/usr/bin/env python3
"""One-shot: extract spectre.bik and bake Specter StoryHub selection icon."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))
sys.path.insert(0, str(ROOT / "tools"))

from bake_ab_sod_selection_icons import extract_still_png  # noqa: E402
from campaign_selection_icon import (  # noqa: E402
    COMPOSE_VERTICAL_FOCUS,
    build_main_icon_from_still,
)
from extract_homm3_complete_vid import extract_vid  # noqa: E402


def main() -> int:
    vid = ROOT / "HoMM 3 Complete" / "Data" / "VIDEO.VID"
    visual = (
        ROOT
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "storyhub_visual"
    )
    out_strip = visual / "hub_strips"
    icons = visual / "icons"
    out_strip.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)

    rows = extract_vid(
        vid, out_strip, wanted_stems=frozenset({"spectre"}), label="VIDEO.VID"
    )
    src = out_strip / rows[0]["name"]
    still = visual / "spectre_selection_still.png"
    extract_still_png(src, still, frame_fraction=0.35)
    icon = icons / "spectre_main_icon.png"
    meta = build_main_icon_from_still(
        still,
        icon_out=icon,
        compose_policy=COMPOSE_VERTICAL_FOCUS,
        focus_x=0.52,
        focus_y=0.42,
    )
    report = {
        "schema": "homm3.spectre_selection_icon_bake.v1",
        "source": rows[0],
        "still": str(still.relative_to(ROOT)).replace("\\", "/"),
        "icon": str(icon.relative_to(ROOT)).replace("\\", "/"),
        "meta": meta,
    }
    (visual / "spectre_selection_icon_bake.v1.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"baked spectre selection still -> {still}")
    print(f"baked spectre main_icon -> {icon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
