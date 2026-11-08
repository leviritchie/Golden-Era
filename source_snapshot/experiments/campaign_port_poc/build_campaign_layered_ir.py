#!/usr/bin/env python3
"""Build layered map IR for any campaign mission defined in the batch manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import build_homecoming_layered_ir as ir_engine
import port_homecoming_poc as poc
from campaign_mission import default_batch_manifest_path, load_batch_manifest, mission_by_id
from h3c_mission_source import H3CMissionSource, load_h3c_block

H3M_NAME_BY_MISSION_BLOCK: dict[tuple[str, int], str] = {
    ("Good1.h3c", 1): "Good-1a.h3m",
    ("Good1.h3c", 2): "Good-1b.h3m",
    ("Good1.h3c", 3): "Good-1c.h3m",
    ("Good2.h3c", 1): "Good-2a.h3m",
    ("Good2.h3c", 2): "Good-2b.h3m",
    ("Good2.h3c", 3): "Good-2c.h3m",
    ("Good2.h3c", 4): "Good-2d.h3m",
    ("Good3.h3c", 1): "Good-3A.h3m",
    ("Good3.h3c", 2): "Good-3B.h3m",
    ("Good3.h3c", 3): "Good-3C.h3m",
    ("EVIL1.H3C", 1): "Evil-1A.h3m",
    ("EVIL1.H3C", 2): "Evil-1B.h3m",
    ("EVIL1.H3C", 3): "Evil-1c.h3m",
    ("Evil2.h3c", 1): "Evil-2A.h3m",
    ("Evil2.h3c", 2): "Evil-2B.h3m",
    ("Evil2.h3c", 3): "Evil-2C.h3m",
    ("Evil2.h3c", 4): "Evil-2D.h3m",
    ("Secret.h3c", 1): "Secret A.h3m",
    ("Secret.h3c", 2): "Secret B.h3m",
    ("Secret.h3c", 3): "Secret C.h3m",
    ("Secret.h3c", 4): "Secret D.h3m",
    ("Secret1.h3c", 1): "Secret-1a.h3m",
    ("Secret1.h3c", 2): "Secret-1c.h3m",
    ("Secret1.h3c", 3): "Secret-1b.h3m",
    ("Neutral1.h3c", 1): "Neutral-1a.h3m",
    ("Neutral1.h3c", 2): "Neutral-1b.h3m",
    ("Neutral1.h3c", 3): "Neutral-1c.h3m",
    # SoD artifact campaigns (Complete LOD; HotA excluded).
    ("Crag.h3c", 1): "Has01.h3m",
    ("Crag.h3c", 2): "Has02.h3m",
    ("Crag.h3c", 3): "Has03.h3m",
    ("Crag.h3c", 4): "Has04.h3m",
    ("Gelu.h3c", 1): "gelu1.h3m",
    ("Gelu.h3c", 2): "gelu2.h3m",
    ("Gelu.h3c", 3): "gelu3.h3m",
    ("Gelu.h3c", 4): "gelu4.h3m",
    ("Gem.h3c", 1): "Gem2.h3m",
    ("Gem.h3c", 2): "Gem1.h3m",
    ("Gem.h3c", 3): "Gem3.h3m",
    ("Gem.h3c", 4): "Gem4.h3m",
    ("Sandro.h3c", 1): "Sandro A.h3m",
    ("Sandro.h3c", 2): "Sandro B.h3m",
    ("Sandro.h3c", 3): "Sandro C.h3m",
    ("Sandro.h3c", 4): "Sandro D.h3m",
    ("Yog.h3c", 1): "Yog A.h3m",
    ("Yog.h3c", 2): "Yog B.h3m",
    ("Yog.h3c", 3): "Yog C.h3m",
    ("Yog.h3c", 4): "Yog D.h3m",
    ("Yog.h3c", 5): "Yog E.h3m",
    ("Final.h3c", 1): "Final A.h3m",
    ("Final.h3c", 2): "Final B.h3m",
    ("Final.h3c", 3): "Final C.h3m",
    ("Final.h3c", 4): "Final D.h3m",
    ("Final.h3c", 5): "Final E.h3m",
    ("Final.h3c", 6): "Final F.h3m",
    ("Final.h3c", 7): "Final G.h3m",
    ("Final.h3c", 8): "Final H.h3m",
    ("Final.h3c", 9): "Final I.h3m",
    ("Final.h3c", 10): "Final J .h3m",
    ("Final.h3c", 11): "Final K.h3m",
    ("Final.h3c", 12): "Final L.h3m",
    # Armageddon's Blade (Complete H3ab_bmp.lod; HotA excluded).
    ("ab.h3c", 1): "A- Catherine's Charge.h3m",
    ("ab.h3c", 2): "B- Seeking Armageddon.h3m",
    ("ab.h3c", 3): "C- Shadows of the Forest.h3m",
    ("ab.h3c", 4): "D- Maker of Sorrows.h3m",
    ("ab.h3c", 5): "E- Return of the King.h3m",
    ("ab.h3c", 6): "F- A Blade in the Back.h3m",
    ("ab.h3c", 7): "G- To Kill a Hero.h3m",
    ("ab.h3c", 8): "H- Oblivion's Edge.h3m",
    ("blood.h3c", 1): "DB1 Culling the Weak.h3m",
    ("blood.h3c", 2): "DB2 Savaging the Scavengers.h3m",
    ("blood.h3c", 3): "DB3 Blood of the Dragon Father.h3m",
    ("blood.h3c", 4): "DB4 Blood Thirsty.h3m",
    ("slayer.h3c", 1): "DragonSlayer02.h3m",
    ("slayer.h3c", 2): "DragonSlayer03.h3m",
    ("slayer.h3c", 3): "DragonSlayer04.h3m",
    ("slayer.h3c", 4): "DragonSlayer01.h3m",
    ("festival.h3c", 1): "Festival of life 4.h3m",
    ("festival.h3c", 2): "Festival of Life 3.h3m",
    ("festival.h3c", 3): "Festival of life 2.h3m",
    ("festival.h3c", 4): "Festival of life 1.h3m",
    ("fire.h3c", 1): "Adrienne1.h3m",
    ("fire.h3c", 2): "Adrienne2.h3m",
    ("fire.h3c", 3): "Adrienne3.h3m",
    ("fool.h3c", 1): "Secret 1 - Lost at Sea.h3m",
    ("fool.h3c", 2): "Secret 3 - Here There Be Pirates.h3m",
    ("fool.h3c", 3): "Secret 4 - Hurry Up and Wait.h3m",
    ("fool.h3c", 4): "Secret 2 - Their End Of the Bargain.h3m",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_briefing_texts(source: H3CMissionSource) -> list[str]:
    key = (source.campaign_entry, source.block_index)
    map_name_text = H3M_NAME_BY_MISSION_BLOCK.get(key)
    if map_name_text is None:
        raise ValueError(f"no H3M map name mapping for campaign={source.campaign_entry} block={source.block_index}")

    strings = poc.scan_length_prefixed_strings(source.campaign_bytes)
    map_name = poc.find_required_string(strings, map_name_text)
    next_map = None
    for (entry, block_index), name in H3M_NAME_BY_MISSION_BLOCK.items():
        if entry == source.campaign_entry and block_index == source.block_index + 1:
            next_map = poc.find_required_string(strings, name)
            break

    chunk = [
        item
        for item in strings
        if item.offset >= map_name.offset and (next_map is None or item.offset < next_map.offset)
    ]
    prose: list[str] = []
    for item in chunk:
        text = item.text
        if len(text) < 20:
            continue
        if ".def" in text.lower() or ".h3m" in text:
            continue
        if "{" in text:
            continue
        if text.startswith("To win"):
            continue
        if text == "Imprisoned Erathian Heroes":
            continue
        prose.append(text)

    if len(prose) < 2:
        raise ValueError(
            f"expected at least 2 briefing texts for {key}, found {len(prose)} between "
            f"{map_name_text} and next mission boundary"
        )
    return prose[:2]


def build_mission_ir(mission) -> dict[str, Any]:
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    strings = poc.scan_length_prefixed_strings(source.campaign_bytes)
    briefing_texts = extract_briefing_texts(source)
    objective = source.summary.description or f"Complete mission: {source.summary.title}"
    likely_event_strings = [
        item
        for item in strings
        if ".def" not in item.text.lower()
        and len(item.text) >= 10
        and item.text not in {source.summary.title, objective}
    ][:40]

    ir = ir_engine.build_layered_map_ir(
        h3m_data=source.h3m_data,
        summary=source.summary,
        templates=source.templates,
        campaign_title=mission.campaign_title or mission.campaign_entry,
        mission_title=source.summary.title,
        objective=objective,
        briefing_texts=briefing_texts,
        likely_event_strings=likely_event_strings,
    )
    ir["source"]["campaignEntry"] = mission.campaign_entry
    ir["source"]["h3cBlockIndex"] = mission.block_index
    ir["source"]["missionId"] = mission.mission_id
    ir["source"]["h3mName"] = f"{mission.campaign_entry}#block{mission.block_index}"
    ir["source"]["h3mSha256"] = source.h3m_sha256
    ir["mission"]["declaredVictoryCondition"] = {
        "kind": "campaign_mission_objective_text",
        "sourceName": source.summary.title,
        "portStatus": "objective_text_only_until_mission_profile_extends_victory_contract",
        "objectiveText": objective,
    }
    validation = ir_engine.validate_layered_map_ir(ir)
    out_dir = mission.layered_ir_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ir_path = mission.layered_ir_path
    write_json(ir_path, ir)
    write_json(out_dir / f"{mission.ir_basename}.layered_ir_validation.json", validation)
    report_name = f"{mission.mission_id}.layered_map_ir_report.md"
    (out_dir / report_name).write_text(
        "\n".join(
            [
                f"# Layered Map IR — {mission.mission_id}",
                "",
                f"Validation: `{validation['result']}`",
                f"Map: `{source.summary.title}` ({source.summary.size}x{source.summary.size}, {source.summary.layers} layers)",
                f"Objects declared: {source.summary.object_count}",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if validation["result"] != "PASS":
        raise ValueError(f"layered IR validation failed for {mission.mission_id}: {validation['errors']}")
    return {"irPath": str(ir_path), "validation": validation, "summary": source.summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    parser.add_argument("--mission", required=True, help="missionId from the batch manifest")
    args = parser.parse_args()
    manifest = load_batch_manifest(args.manifest.resolve())
    mission = mission_by_id(manifest, args.mission)
    if mission.reuse_existing_upstream and mission.layered_ir_path.exists():
        print(f"reusing existing layered IR for {mission.mission_id}: {mission.layered_ir_path}")
        return 0
    result = build_mission_ir(mission)
    print(f"wrote {result['irPath']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
