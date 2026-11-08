#!/usr/bin/env python3
"""One-shot campaign portrait postpass after GenerateImage for portrait-only keys.

Reuses roster Voy finals for planned SIDs; chroma-keys new campaign-only gens
into artifacts/homm3_campaign_hero_portraits_keyed/ without overwriting unrelated
roster SIDs.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import hero_portrait_touchup_pilot as pilot  # noqa: E402

CAMP = ROOT / "artifacts" / "hero_portrait_touchup_pilot" / "campaign"
KEYED = ROOT / "artifacts" / "homm3_campaign_hero_portraits_keyed"
LIVE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
)
PILOT_FINAL = ROOT / "artifacts" / "hero_portrait_touchup_pilot" / "final"
EXTRACT = ROOT / "artifacts" / "homm3_campaign_hero_portraits_for_upscale"
PLATE = (20, 243, 14)


def main() -> int:
    KEYED.mkdir(parents=True, exist_ok=True)
    work = json.loads((CAMP / "work_manifest.json").read_text(encoding="utf-8"))
    man = json.loads((EXTRACT / "manifest.json").read_text(encoding="utf-8"))
    extract_by_key = {e["key"]: Path(e["png"]).name for e in man["entries"]}

    report: dict = {
        "schema": "homm3.campaign_portrait_voy_report.v1",
        "method": work["method"],
        "entries": [],
        "plannedSidsWrittenLive": [],
        "portraitOnlyKeyed": [],
        "proofLabels": {
            "plannedSids": "generated-artifact (roster Voy finals already promoted live)",
            "portraitOnly": "generated-artifact (new campaign GenerateImage + chroma postpass)",
            "inject": "pending",
            "runtimeDialog": "unvalidated",
        },
    }

    for e in work["entries"]:
        key = e["key"]
        wid = e["workId"]
        planned = e.get("plannedSid")
        policy = e.get("slotPolicy")
        entry: dict = {
            "key": key,
            "workId": wid,
            "plannedSid": planned,
            "slotPolicy": policy,
        }
        keyed_name = extract_by_key[key]

        if planned:
            src_final = PILOT_FINAL / f"{planned}.png"
            live = LIVE / f"{planned}.png"
            if not src_final.is_file():
                raise SystemExit(f"missing roster final for planned SID {planned}")
            if not live.is_file():
                raise SystemExit(f"missing live upscaled for {planned}")
            same = src_final.read_bytes() == live.read_bytes()
            shutil.copy2(src_final, CAMP / "final" / f"{wid}.png")
            shutil.copy2(live, KEYED / keyed_name)
            entry.update(
                {
                    "status": "reused_roster_voy_final",
                    "liveMatchesFinal": same,
                    "livePng": str(live.relative_to(ROOT)).replace("\\", "/"),
                    "keyedPng": str((KEYED / keyed_name).relative_to(ROOT)).replace("\\", "/"),
                    "finalPng": f"artifacts/hero_portrait_touchup_pilot/campaign/final/{wid}.png",
                }
            )
            report["plannedSidsWrittenLive"].append(planned)
            print(f"REUSE {key} -> {planned} live_match={same}")
        else:
            ai_path = CAMP / "ai" / f"{wid}.png"
            orig_path = CAMP / "original" / f"{wid}.png"
            if not ai_path.is_file():
                raise SystemExit(f"missing AI {ai_path}")
            ai = Image.open(ai_path).convert("RGBA")
            orig = Image.open(orig_path).convert("RGBA")
            if not pilot.looks_plate_color(ai, PLATE):
                raise SystemExit(f"FAIL-CLOSED: {wid} AI missing chroma plate #14F30E")
            final = pilot.bust_to_square(ai, pilot.OUTPUT_SIDE, orig=orig, plate_rgb=PLATE)
            arr = np.asarray(final)
            a = arr[:, :, 3]
            rgb = arr[:, :, :3].astype(np.float32)
            g, r, b = rgb[:, :, 1], rgb[:, :, 0], rgb[:, :, 2]
            green = int(((g > 180) & (g > r + 40) & (g > b + 40) & (a > 20)).sum())
            hole = a < 80
            interior_holes = int((hole & (~pilot.border_flood_junk(hole))).sum())
            if interior_holes > 2500 or green > 5000:
                raise SystemExit(
                    f"FAIL-CLOSED QA {wid}: holes={interior_holes} green={green}"
                )
            final_path = CAMP / "final" / f"{wid}.png"
            final.save(final_path)
            keyed_path = KEYED / keyed_name
            final.save(keyed_path)
            strip = pilot.strip_row(
                [
                    orig,
                    Image.open(CAMP / "gen_refs" / f"{wid}__lanczos.png"),
                    ai,
                    final,
                ],
                ["orig", "lanczos", "ai", "final"],
            )
            strip.save(CAMP / "strips" / f"{wid}__qa.png")
            entry.update(
                {
                    "status": "generated_keyed",
                    "plateOnAi": True,
                    "interiorHoles": interior_holes,
                    "greenResidual": green,
                    "opaquePct": round(float((a >= 200).mean() * 100), 2),
                    "finalPng": str(final_path.relative_to(ROOT)).replace("\\", "/"),
                    "keyedPng": str(keyed_path.relative_to(ROOT)).replace("\\", "/"),
                    "liveSidWritten": None,
                    "note": "portrait_only_no_slot: not written to roster SID",
                }
            )
            report["portraitOnlyKeyed"].append(key)
            print(
                f"KEYED {key}: holes={interior_holes} green={green} "
                f"opaque={entry['opaquePct']}%"
            )

        report["entries"].append(entry)

    report["plannedSidsWrittenLive"] = sorted(set(report["plannedSidsWrittenLive"]))
    out = ROOT / "artifacts" / "hero_portrait_touchup_pilot" / "campaign_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (CAMP / "postpass_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "planned": len(report["plannedSidsWrittenLive"]),
                "portraitOnly": report["portraitOnlyKeyed"],
                "out": str(out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
