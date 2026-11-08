"""Ledger for the per-unit animation authenticity pass (docs/homm3_unit_authenticity_pass.md).

    python tools/homm3_authenticity/ledger.py init            # add any import-table row not yet in the ledger
    python tools/homm3_authenticity/ledger.py next            # print the unit the next run should work on
    python tools/homm3_authenticity/ledger.py show <unit>
    python tools/homm3_authenticity/ledger.py set <unit> <status> [--note TEXT] [--commit SHA] [--run RUNID]
    python tools/homm3_authenticity/ledger.py clip <unit> <clip> <pass|fail|n/a> [--defect TEXT ...]
    python tools/homm3_authenticity/ledger.py summary
    python tools/homm3_authenticity/ledger.py next --claim --owner LANE   # pick the next unclaimed unit and claim it
    python tools/homm3_authenticity/ledger.py claim <unit> --owner LANE / release <unit>

Parallel workers: every mutation holds an OS lock on ledger.json.lock, and `next` skips units another owner claimed,
so two lanes never pick the same unit.

One row per homm3_import.json unit (read from the fleet quality census). Rows are only ever added, never dropped, so
the ledger is the durable record of what has been judged. `init` is idempotent and keeps every existing verdict.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEDGER = HERE / "ledger.json"
CENSUS = ROOT / "tools/homm3_def_retarget_delivery/census/quality_census.json"

STATUSES = (
    "queued",          # not looked at yet
    "in_review",       # boards rendered, clip verdicts being written
    "fixing",          # at least one clip failed; fixes in progress
    "passed",          # every clip passes the rubric on the shipped (frozen) GLB
    "blocked_mesh",    # needs mesh surgery bigger than one run; see notes
    "blocked_vfx",     # animation passes, the unit's DEF effect still needs authoring
    "blocked_input",   # no retarget build / no capture / no DEF; cannot be judged yet
    "needs_user",      # a decision only the user can make (named in notes)
)
OPEN = ("in_review", "fixing", "queued")
# Faction order: whole factions finish together so they can install as one batch. Castle and rampart hold the
# user-reported flyers (griffin line, angels, green dragon); tower holds the gargoyle reference; neutrals last.
FACTION_ORDER = ("castle", "rampart", "tower", "inferno", "necropolis", "dungeon", "stronghold", "fortress",
                 "conflux", "cove", "factory", "bulwark", "neutral")


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"schema": "homm3_authenticity_ledger_v1", "doc": "docs/homm3_unit_authenticity_pass.md", "units": {}}


@contextlib.contextmanager
def locked():
    """Exclusive OS lock around a load-modify-save (msvcrt on Windows, fcntl elsewhere); waits up to 60 s."""
    fh = open(str(LEDGER) + ".lock", "a+b")
    deadline = time.monotonic() + 60
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close(); sys.exit("ledger lock busy for 60 s")
            time.sleep(0.2)
    try:
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()


def save(d: dict) -> None:
    d["updatedAt"] = now()
    LEDGER.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def order_key(r: dict) -> tuple:
    f = r["faction"]
    return (FACTION_ORDER.index(f) if f in FACTION_ORDER else len(FACTION_ORDER), r.get("censusRank", 9999), r["labSid"])


def cmd_init(_a) -> None:
    with locked():
        _init()


def _init() -> None:
    d = load()
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    added = 0
    for c in census["rows"]:
        lab = c["labSid"]
        if lab in d["units"]:
            continue
        d["units"][lab] = {
            "labSid": lab, "gameSids": c.get("gameSids", [lab]), "faction": c["faction"],
            "censusRank": c.get("queueRank", 9999), "visibilitySquads": c.get("visibilitySquads", 0),
            "userReported": c.get("userReported"), "status": "queued", "attempts": 0,
            "clips": {}, "commits": [], "runs": [], "notes": [],
        }
        added += 1
    save(d)
    print(f"ledger: {len(d['units'])} units ({added} added)")


def claimed_by_other(r: dict, owner: str | None) -> bool:
    c = r.get("claimedBy")
    return bool(c) and c.get("owner") != owner


def pick_next(d: dict, owner: str | None = None) -> dict | None:
    rows = sorted(d["units"].values(), key=order_key)
    # Own claims first, then what is open (oldest work first), then the next queued unit in faction order.
    for r in rows:
        if owner and (r.get("claimedBy") or {}).get("owner") == owner and r["status"] in OPEN:
            return r
    for st in ("fixing", "in_review", "queued"):
        for r in rows:
            if r["status"] == st and not claimed_by_other(r, owner):
                return r
    return None


def cmd_next(a) -> None:
    with locked():
        d = load()
        r = pick_next(d, a.owner)
        if r and a.claim:
            if not a.owner:
                sys.exit("--claim needs --owner")
            r["claimedBy"] = {"owner": a.owner, "at": now()}
            save(d)
    print(json.dumps(r, indent=1, ensure_ascii=False) if r else "ALL_DONE")


def cmd_claim(a) -> None:
    with locked():
        d = load(); r = row(d, a.unit)
        if claimed_by_other(r, a.owner) and not a.steal:
            sys.exit(f"{a.unit} is claimed by {r['claimedBy']}")
        r["claimedBy"] = {"owner": a.owner, "at": now()}
        save(d)
    print(f"{a.unit}: claimed by {a.owner}")


def cmd_release(a) -> None:
    with locked():
        d = load(); r = row(d, a.unit)
        r.pop("claimedBy", None)
        save(d)
    print(f"{a.unit}: released")


def row(d: dict, unit: str) -> dict:
    if unit not in d["units"]:
        sys.exit(f"unknown unit {unit}")
    return d["units"][unit]


def cmd_show(a) -> None:
    print(json.dumps(row(load(), a.unit), indent=1, ensure_ascii=False))


def cmd_set(a) -> None:
    if a.status not in STATUSES:
        sys.exit(f"status must be one of {STATUSES}")
    with locked():
        _set(a)


def _set(a) -> None:
    d = load(); r = row(d, a.unit)
    if a.status == "passed":
        bad = [k for k, v in r["clips"].items() if v["verdict"] == "fail"]
        if not r["clips"] or bad:
            sys.exit(f"cannot pass {a.unit}: clips {'missing' if not r['clips'] else 'failing: ' + ', '.join(bad)}")
        r["passedAt"] = now()
    if a.status in ("in_review", "fixing") and r["status"] == "queued":
        r["startedAt"] = now()
    if a.status == "fixing":
        r["attempts"] += 1
    r["status"] = a.status
    if a.note:
        r["notes"].append({"at": now(), "status": a.status, "note": a.note})
    if a.commit:
        r["commits"].append(a.commit)
    if a.run and a.run not in r["runs"]:
        r["runs"].append(a.run)
    if a.status not in OPEN:
        r.pop("claimedBy", None)
    save(d)
    print(f"{a.unit}: {a.status}")


def cmd_clip(a) -> None:
    with locked():
        d = load(); r = row(d, a.unit)
        r["clips"][a.clip] = {"verdict": a.verdict, "defects": a.defect or [], "at": now()}
        save(d)
    print(f"{a.unit} {a.clip}: {a.verdict}")


def cmd_summary(_a) -> None:
    d = load()
    by: dict[str, dict[str, int]] = {}
    for r in d["units"].values():
        by.setdefault(r["faction"], {}).setdefault(r["status"], 0)
        by[r["faction"]][r["status"]] += 1
    for f in sorted(by, key=lambda f: FACTION_ORDER.index(f) if f in FACTION_ORDER else 99):
        print(f"{f:12s} " + "  ".join(f"{k}={v}" for k, v in sorted(by[f].items())))
    tot: dict[str, int] = {}
    for r in d["units"].values():
        tot[r["status"]] = tot.get(r["status"], 0) + 1
    print("total        " + "  ".join(f"{k}={v}" for k, v in sorted(tot.items())))


def main() -> None:
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("init").set_defaults(f=cmd_init)
    q = s.add_parser("next"); q.add_argument("--owner"); q.add_argument("--claim", action="store_true"); q.set_defaults(f=cmd_next)
    q = s.add_parser("claim"); q.add_argument("unit"); q.add_argument("--owner", required=True)
    q.add_argument("--steal", action="store_true"); q.set_defaults(f=cmd_claim)
    q = s.add_parser("release"); q.add_argument("unit"); q.set_defaults(f=cmd_release)
    s.add_parser("summary").set_defaults(f=cmd_summary)
    q = s.add_parser("show"); q.add_argument("unit"); q.set_defaults(f=cmd_show)
    q = s.add_parser("set"); q.add_argument("unit"); q.add_argument("status")
    q.add_argument("--note"); q.add_argument("--commit"); q.add_argument("--run"); q.set_defaults(f=cmd_set)
    q = s.add_parser("clip"); q.add_argument("unit"); q.add_argument("clip"); q.add_argument("verdict", choices=("pass", "fail", "n/a"))
    q.add_argument("--defect", action="append"); q.set_defaults(f=cmd_clip)
    a = p.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
