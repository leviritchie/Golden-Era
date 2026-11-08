#!/usr/bin/env python3
"""Gate: HoMM3 key-gated passages stay closed until their Keymaster's Tent is visited.

Contract (experiments/campaign_port_poc/raw_translation/border_guard_gates.py):
  * Border Guard (9) substitutes to Core campaign_FX_block (visible smoke, one blocked node);
  * Border Gate (212) gains a campaign_FX_block on its passage (HoMM3 visit) cell;
  * Keymaster's Tent (10) is a Zone 1x1 marker: propActionsBefore Dialog, propActionsAfter
    CounterSet <mission>_border_key_<colour> 1;
  * one hidden quest per colour with a tent: Counter(key,"=",1) -> DeleteEntity every block.

Checks:
  1. source/static: the substitution rule and the three raw-builder calls are in place;
  2. generated artifact: every raw_translation map's report carries a verified borderKeyGates
     pass, and the map's QuestScript/properties agree with it (every block has a propEntities
     row; every colour with a tent deletes exactly its blocks; every tent marker has the dialog
     and counter actions; a colour without a tent stays closed).

Proof tier: source/static + generated artifact. Runtime DeleteEntity of campaign_FX_block on
these maps and AI tent visits are unproven.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
# Missions whose map could not be regenerated with key gates, each with the blocking cause.
# Listed ones are reported on every run; an entry fails once its map verifies (remove it then).
# Nothing else may be missing.
KNOWN_UNREGENERATED: dict[str, str] = {}
REPORT_GLOBS = (
    "artifacts/campaign_port_poc/*/*/raw_translation_map/raw_translation_report.json",
    "artifacts/campaign_port_poc/*/raw_translation_map/raw_translation_report.json",
)


def main() -> int:
    errors: list[str] = []
    sys.path.insert(0, str(POC))
    import build_homecoming_entity_substitution_map as sub  # noqa: E402
    import port_homecoming_poc as poc  # noqa: E402

    if sub.DIRECT_BLOCKED_TEMPLATE_MAP.get(9, (None,))[0] != "campaign_FX_block":
        errors.append(f"substitution: object 9 must map to campaign_FX_block, got {sub.DIRECT_BLOCKED_TEMPLATE_MAP.get(9)}")
    builder = (POC / "raw_translation" / "build_raw_translation_map.py").read_text(encoding="utf-8")
    for call in ("apply_border_key_gate_hosts(", "apply_border_key_gate_script(", "verify_border_key_gates_final("):
        if f"border_guard_gates.{call}" not in builder:
            errors.append(f"build_raw_translation_map.py no longer calls border_guard_gates.{call}")
    # Pickup bodies stay off gate passages / tent cells; a guard block may hold one portal
    # GATE but never every GATE of a subterranean portal.
    for rel, needles in (
        ("approach_cell/surface_emit.py", ("reserved_cells=key_gate_reserved_cells(",)),
        ("raw_translation/landon_access.py", ("keyGateHeldGates", "every GATE")),
    ):
        text = (POC / rel).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                errors.append(f"{rel} lost {needle!r}")

    reports = sorted({f for g in REPORT_GLOBS for f in glob.glob(str(ROOT / g))})
    if not reports:
        errors.append("no raw_translation reports found")
    blocks_total = tents_total = maps_with_gates = 0
    for report_path in reports:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        plan = (report.get("postPasses") or {}).get("borderKeyGates")
        label = Path(report_path).parent.parent.name
        verified = isinstance(plan, dict) and (plan.get("finalCheck") or {}).get("status") == "verified"
        if label in KNOWN_UNREGENERATED:
            if verified:
                errors.append(f"{label}: now verified; remove it from KNOWN_UNREGENERATED")
            else:
                print(f"  KNOWN UNREGENERATED {label}: {KNOWN_UNREGENERATED[label]}")
            continue
        if not verified:
            errors.append(f"{label}: borderKeyGates pass missing or unverified (regenerate the map)")
            continue
        if not plan.get("colours"):
            continue
        maps_with_gates += 1
        blocks_total += int(plan.get("blockCount") or 0)
        tents_total += int(plan.get("tentCount") or 0)
        map_files = [p for p in (Path(report_path).parent / "maps").glob("*.map") if "pre_visual" not in p.name]
        if len(map_files) != 1:
            errors.append(f"{label}: expected one map, found {[p.name for p in map_files]}")
            continue
        container = poc.read_olden_map_container(map_files[0])
        body, script = container.chunks[1], container.chunks[3]
        props = body.get("objectsProperties") or {}
        entity_rows = {row.get("sid"): row for row in props.get("propEntities") or []}
        quests = {q.get("sid"): q for q in script.get("quests") or []}
        counters = {c.get("sid") for c in script.get("counters") or []}
        marker_ids = {m.get("id") for m in body.get("markers") or []}
        after_by_id = {r.get("id"): r for r in props.get("propActionsAfter") or [] if r.get("type") == 1}
        before_by_id = {r.get("id"): r for r in props.get("propActionsBefore") or [] if r.get("type") == 1}
        mission = plan.get("missionId")
        for colour, row in plan["colours"].items():
            block_sids = [b["entitySid"] for b in row.get("blocks") or []]
            for sid in block_sids:
                if (entity_rows.get(sid) or {}).get("type") != 0:
                    errors.append(f"{label}: block {sid} has no type-0 propEntities row")
            quest_sid = f"{mission}_border_gate_{colour}"
            key = f"{mission}_border_key_{colour}"
            if row.get("tents"):
                if key not in counters:
                    errors.append(f"{label}: key counter {key} not declared")
                for tent in row["tents"]:
                    moved = tent.get("visitNodeRelocation")
                    if moved is not None and (
                        moved.get("toNode") != tent.get("node")
                        or moved.get("toNode") == moved.get("fromNode")
                    ):
                        errors.append(f"{label}: tent {tent['entitySid']} relocation {moved} does not match node {tent.get('node')}")
                    ent = entity_rows.get(tent["entitySid"]) or {}
                    mid = ent.get("id")
                    if ent.get("type") != 1 or mid not in marker_ids:
                        errors.append(f"{label}: tent {tent['entitySid']} is not bound to a marker")
                        continue
                    after = json.dumps((after_by_id.get(mid) or {}).get("actions"))
                    before = json.dumps((before_by_id.get(mid) or {}).get("actions"))
                    if key not in after or "CounterSet" not in after:
                        errors.append(f"{label}: tent {tent['entitySid']} does not set {key}")
                    if "Dialog" not in before:
                        errors.append(f"{label}: tent {tent['entitySid']} has no Dialog")
            if row.get("tents") and block_sids:
                quest = quests.get(quest_sid)
                if quest is None:
                    errors.append(f"{label}: quest {quest_sid} missing")
                    continue
                text = json.dumps(quest)
                deleted = {a["p"][0] for sq in quest["subQuests"] for t in sq["triggers"] for a in t["actions"] if a.get("a") == "DeleteEntity"}
                if deleted != set(block_sids) or key not in text:
                    errors.append(f"{label}: quest {quest_sid} deletes {sorted(deleted)} on {key}; expected {sorted(block_sids)}")
            elif quest_sid in quests:
                errors.append(f"{label}: colour {colour} has no tent or no blocks but quest {quest_sid} exists")

    if errors:
        print("border key gate contract FAILED:")
        for e in errors[:40]:
            print("  -", e)
        return 1
    print(f"border key gate contract OK: {len(reports)} maps, {maps_with_gates} with key gates, "
          f"{blocks_total} blocks, {tents_total} tents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
