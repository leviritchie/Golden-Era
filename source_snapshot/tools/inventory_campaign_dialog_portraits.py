#!/usr/bin/env python3
"""Inventory AB/SoD campaign event texts for dialog portrait eligibility.

Writes:
  artifacts/dialog_portrait_inventory/event_portrait_plan.json
  artifacts/dialog_portrait_inventory/required_homm3_icons.json

Does not modify Core or maps.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "campaign_port_poc"))

import dialog_portrait_plan as portraits  # noqa: E402

ROOT = REPO / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns"
OUT = REPO / "artifacts" / "dialog_portrait_inventory"


def _load_loc(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["array"] if isinstance(data, dict) and "array" in data else data
    return {r["sid"]: r.get("text", "") for r in rows if isinstance(r, dict) and "sid" in r}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    plans = []
    required: set[str] = set()
    mode_counts: Counter[str] = Counter()
    for mission_dir in sorted(ROOT.iterdir()):
        if not mission_dir.is_dir():
            continue
        overlay = mission_dir / "raw_translation_map" / "core_overlay"
        dialogs = overlay / "DB" / "dialogs"
        loc_p = overlay / "Lang" / "english" / "texts" / "dialogues.json"
        if not dialogs.is_dir() or not loc_p.is_file():
            continue
        loc = _load_loc(loc_p)
        mission_id = mission_dir.name
        for path in sorted(dialogs.rglob("*.json")):
            # Prefer non-AbSod folder when both exist
            if "BashingSkullsAbSod" in str(path) or "AbSod" in path.parts:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("array") or []:
                dialog_sid = str(row.get("id") or "")
                slides = row.get("slides") or []
                if not slides:
                    continue
                start = slides[0]
                text_sid = start.get("text")
                text = loc.get(text_sid, "") if isinstance(text_sid, str) else ""
                if not text and isinstance(text_sid, str) and text_sid.startswith("dialogue_text_"):
                    # Intro often concatenates; still try
                    text = loc.get(text_sid, "")
                existing = start.get("avatars") if isinstance(start.get("avatars"), list) else []
                title = None
                title_obj = start.get("title")
                if isinstance(title_obj, dict):
                    title = loc.get(str(title_obj.get("sid") or ""), None) or str(
                        title_obj.get("sid") or ""
                    )
                # Prefer briefing bodies over mega intro when both share content: still plan each
                if not any(x in dialog_sid for x in ("briefing", "map_event", "intro")):
                    continue
                if not text.strip():
                    continue
                plan = portraits.plan_dialog_portraits(
                    dialog_sid=dialog_sid,
                    mission_id=mission_id,
                    text=text,
                    existing_avatars=existing,
                    existing_title=title,
                )
                mode_counts[plan.mode] += 1
                required.update(plan.required_homm3_icons)
                plans.append(
                    {
                        "mission": mission_id,
                        "dialogSid": dialog_sid,
                        "member": str(path.relative_to(overlay)).replace("\\", "/"),
                        "mode": plan.mode,
                        "slideCount": len(plan.slides),
                        "speakers": [
                            {"label": s.speaker_label, "icon": s.icon}
                            for s in plan.slides
                            if s.icon
                        ],
                        "requiredHomm3Icons": plan.required_homm3_icons,
                        "notes": plan.notes,
                        "preview": text[:180].replace("\n", " "),
                    }
                )

    summary = {
        "dialogCount": len(plans),
        "modeCounts": dict(mode_counts),
        "requiredHomm3IconCount": len(required),
        "requiredHomm3Icons": sorted(required),
        "single": [p for p in plans if p["mode"] == "single"],
        "multi": [p for p in plans if p["mode"] == "multi"],
        "none": [p for p in plans if p["mode"] == "none"],
    }
    (OUT / "event_portrait_plan.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT / "required_homm3_icons.json").write_text(
        json.dumps({"icons": sorted(required)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"dialogs={len(plans)} modes={dict(mode_counts)} required_homm3={len(required)}")
    print(f"wrote {OUT / 'event_portrait_plan.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
