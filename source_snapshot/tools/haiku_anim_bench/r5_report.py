"""Round 5 run summaries and the round 4 vs round 5 table.

    python tools/haiku_anim_bench/r5_report.py <run_dir> [<run_dir> ...]      # (re)write summary.json/.txt
    python tools/haiku_anim_bench/r5_report.py --table                         # round 4 vs 5 for the three cases
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from anim_core import SCRATCH
from r5_items import median

DIR_RE = re.compile(r"wrong (way|direction)|opposite|overshoot|too far|flipp|backward|inverted|reverse", re.I)
CASES = (("h3_roc", "r4_move", "r5_move"), ("h3_troll", "r4_move", "r5_move"), ("h3_wyvern", "r4_attack", "r5_attack"))


def _lines(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def summarize(rdir: Path) -> dict:
    rdir = Path(rdir)
    steps = _lines(rdir / "steps.jsonl")
    judge = _lines(rdir / "judge.jsonl")
    items = json.loads((rdir / "items.json").read_text(encoding="utf-8")) if (rdir / "items.json").exists() else {}
    its = items.get("items", [])
    st = items.get("stats", {})
    pend = [j for j in judge if j.get("mode") == "pending"]
    checks = [j for j in judge if j.get("mode") == "check"]
    acc = [j for j in pend if j.get("accept")]
    worse = [j for j in pend if j.get("verdict") == "worse"]
    lat = [s["judge"]["acceptLatencyS"] for s in steps if (s.get("judge") or {}).get("acceptLatencyS") is not None]
    kw = sum(1 for s in steps if (s.get("op") or {}).get("op") in ("revert", "undo", "pick", "intent")
             and DIR_RE.search(str((s.get("op") or {}).get("why", ""))))
    ops = {}
    for s in steps:
        k = (s.get("op") or {}).get("op", "(bad reply)")
        ops[k] = ops.get(k, 0) + 1
    picks = [s for s in steps if (s.get("op") or {}).get("op") == "pick"]
    mesh = json.loads((rdir / "final_mesh.json").read_text(encoding="utf-8")) if (rdir / "final_mesh.json").exists() else None
    model_ms = [s["ms"]["model"] for s in steps if s.get("ms")]
    step_ms = [s["ms"]["step"] for s in steps if s.get("ms")]
    sm = {
        "run": str(rdir), "turns": len(steps),
        "surveyTurns": sum(1 for s in steps if s.get("phase") == "survey"),
        "itemsOpened": len(its), "itemsClosed": sum(1 for x in its if x["status"] == "closed"),
        "itemsParked": sum(1 for x in its if x["status"] == "parked"),
        "itemsOpen": sum(1 for x in its if x["status"] == "open"),
        "judged": len(pend), "accepted": len(acc), "acceptRate": round(len(acc) / len(pend), 3) if pend else None,
        "rejectedByJudge": len(pend) - len(acc),
        "verdicts": {v: sum(1 for j in pend if j.get("verdict") == v) for v in ("accept", "worse", "split", "same")},
        "checks": len(checks), "checksClosed": sum(1 for j in checks if j.get("accept") and j.get("fixed")),
        "tabuRepeats": st.get("tabuRefused", 0), "tabuFilteredVariants": st.get("tabuFiltered", 0),
        "directionErrors": len(worse), "directionKeywordNotes": kw,
        "picksNone": sum(1 for s in picks if str(s["op"].get("which", "")).lower() == "none"),
        "medianAcceptLatencyS": median(lat), "acceptLatenciesS": lat,
        "medianModelMs": median(model_ms), "medianStepMs": median(step_ms),
        "medianJudgeMs": median([s["judge"]["judgeMs"] for s in steps if (s.get("judge") or {}).get("judgeMs")]),
        "autoRepairs": st.get("autoRepairs", 0), "repairKept": st.get("repairKept", 0),
        "ops": ops, "errors": sum(1 for s in steps if s.get("error")),
        "meshAtEnd": mesh, "items": [{k: x.get(k) for k in ("id", "sev", "clip", "frame", "region", "issue", "status",
                                                             "closedBy")} for x in its],
    }
    (rdir / "summary.json").write_text(json.dumps(sm, indent=1), encoding="utf-8")
    (rdir / "summary.txt").write_text(text(sm), encoding="utf-8")
    return sm


def mesh_words(m) -> str:
    if m is None:
        return "?"
    if not m:
        return "clean"
    return "; ".join(f"{c.replace('Unit_', '')}: {v['edges']} edges at {v['where']}" for c, v in m.items())


def text(sm: dict) -> str:
    L = [f"run {sm['run']}: {sm['turns']} proposer turns ({sm['surveyTurns']} survey)",
         f"items opened {sm['itemsOpened']}, closed by the judge {sm['itemsClosed']}, parked {sm['itemsParked']}, "
         f"open {sm['itemsOpen']}",
         f"judged changes {sm['judged']}: accepted {sm['accepted']} (rate {sm['acceptRate']}), rejected "
         f"{sm['rejectedByJudge']} {sm['verdicts']}; checks {sm['checks']} (closed {sm['checksClosed']})",
         f"tabu repeats refused {sm['tabuRepeats']} (variants filtered {sm['tabuFilteredVariants']}); picks of none "
         f"{sm['picksNone']}",
         f"direction errors (judge: before wins both orders) {sm['directionErrors']}; keyword notes {sm['directionKeywordNotes']}",
         f"median latency per accepted change {sm['medianAcceptLatencyS']} s; median step {sm['medianStepMs']} ms, "
         f"model {sm['medianModelMs']} ms, judge pair {sm['medianJudgeMs']} ms",
         f"auto repairs {sm['autoRepairs']} (kept {sm['repairKept']}); mesh at end: {mesh_words(sm['meshAtEnd'])}",
         f"ops {sm['ops']}; bench errors {sm['errors']}", "items:"]
    for x in sm["items"]:
        L.append(f"  #{x['id']} {x['sev']} [{x['status']}] {x['clip'].replace('Unit_', '')} f{x['frame']} "
                 f"{x['region']}: {x['issue']}")
    return "\n".join(L) + "\n"


# round 4 numbers, read from the r4 steps.jsonl / stack_final.json (no judge in r4; items were self-graded)
R4 = {"h3_roc": {"turns": 247, "items": "19 (14 self-fixed)", "kept": 37, "reverted": 18, "dirErr": 5,
                 "repairOps": 13, "median": "1.08 s/step", "mesh": "torn neck/head (Move); stretched leg (MoveStart)"},
      "h3_troll": {"turns": 116, "items": "10 (6 self-fixed)", "kept": 10, "reverted": 14, "dirErr": 1,
                   "repairOps": 18, "median": "0.96 s/step", "mesh": "small tear right hand/forearm"},
      "h3_wyvern": {"turns": 353, "items": "36 (26 self-fixed)", "kept": 55, "reverted": 16, "dirErr": 1,
                    "repairOps": 24, "median": "0.99 s/step", "mesh": "AttackFront + Move stretched hips/spine"}}


def table() -> str:
    rows = ["| unit | round | turns | items (closed) | kept / rejected | accept rate | tabu repeats | direction errors "
            "| repair ops by Haiku | latency | mesh at end |", "|" + "---|" * 11]
    for unit, _r4, r5 in CASES:
        a = R4[unit]
        rows.append(f"| {unit} | 4 | {a['turns']} | {a['items']} | {a['kept']} / {a['reverted']} reverted | (no judge) | "
                    f"n/a | {a['dirErr']} | {a['repairOps']} | {a['median']} | {a['mesh']} |")
        p = SCRATCH / unit / "runs" / r5 / "summary.json"
        if not p.exists():
            rows.append(f"| {unit} | 5 | (not run) |||||||||")
            continue
        s = json.loads(p.read_text(encoding="utf-8"))
        rows.append(f"| {unit} | 5 | {s['turns']} | {s['itemsOpened']} ({s['itemsClosed']} judge-closed) | "
                    f"{s['accepted']} / {s['rejectedByJudge']} | {s['acceptRate']} | {s['tabuRepeats']} | "
                    f"{s['directionErrors']} judge-worse ({s['directionKeywordNotes']} kw) | "
                    f"{s['ops'].get('repair', 0) + s['ops'].get('rig', 0)} | {s['medianAcceptLatencyS']} s/accepted change "
                    f"| {mesh_words(s['meshAtEnd'])} |")
    return "\n".join(rows)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--table":
        print(table())
    else:
        for d in sys.argv[1:]:
            print(text(summarize(Path(d))))
