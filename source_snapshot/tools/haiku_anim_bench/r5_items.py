"""Round 5 (2026-10-08): the persistent item list with tabu, and the blind judge's order-swap rule.

Items (clip, frame, region, the defect in words, sev) open from the survey and close ONLY by a judge win: the proposer
cannot close them. Every judged attempt is recorded on its item; a rejected one becomes a TABU entry (item, goal,
limb, chain, direction, strength) that is shown every turn (it lives in the run folder's items.json, so a session
rotation or a server restart keeps it) and an identical retry is refused before it costs a judge call.
Parking is a tool behaviour: an item with REJECT_PARK judge rejections in a row, or STALL_STEPS steps without an
accepted change, is parked; when nothing is open, parked items get one more pass; then the list is done.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

SEVS = ("BIG", "MEDIUM", "SMALL")
REJECT_PARK = 4
STALL_STEPS = 12
SECOND_PASS = 1


def judge_verdict(r_ab: dict | None, r_ba: dict | None) -> dict:
    """Two blind judgements of the same pair with the order swapped. r_ab: version 1 = BEFORE, 2 = AFTER; r_ba:
    version 1 = AFTER, 2 = BEFORE. Each {"better": "1"|"2"|"same", "fixed": bool}. AFTER must win BOTH orders to be
    accepted; the item counts as fixed only if both judgements also say the problem is gone."""
    def pick(r):
        b = str((r or {}).get("better", "")).strip().strip("\"'").lower()
        return b if b in ("1", "2") else "same"
    a, b = pick(r_ab), pick(r_ba)
    after_ab, after_ba = a == "2", b == "1"
    before_ab, before_ba = a == "1", b == "2"
    accept = after_ab and after_ba
    fixed = bool(accept and (r_ab or {}).get("fixed") is True and (r_ba or {}).get("fixed") is True)
    if accept:
        v = "accept"
    elif before_ab and before_ba:
        v = "worse"            # BEFORE won both orders: the change went the wrong way (or too far)
    elif (after_ab or after_ba) and (before_ab or before_ba):
        v = "split"            # each order picked its first / second slot: position bias, no real preference
    else:
        v = "same"
    return {"verdict": v, "accept": accept, "fixed": fixed, "orders": [a, b]}


def dir_key(spec: dict) -> str:
    """The direction part of a tabu signature, coarse enough that a near-identical retry matches."""
    if spec.get("goal") == "spread":
        return f"amount {round(float(spec.get('amount', 1)) * 4) / 4:g}"
    if spec.get("goal") == "bend":
        return f"deg {int(round(float(spec.get('deg', 30)) / 15) * 15)}"
    d = spec.get("dir")
    if isinstance(d, str):
        return " ".join(d.lower().replace(",", " ").split())
    vals = d if isinstance(d, dict) else spec
    parts = []
    for k in ("elev", "az", "d_elev", "d_az"):
        if vals.get(k) is not None:
            parts.append(f"{k} {int(round(float(vals[k]) / 10) * 10)}")
    return " ".join(parts) or "?"


def frames_key(frames) -> str:
    if isinstance(frames, str):
        return frames
    fr = sorted({int(f) for f in frames})
    return f"f{fr[0]}" if len(fr) == 1 else f"f{fr[0]}-{fr[-1]}"


class ItemStore:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.d = {"schema": "haiku_anim_items.r5", "items": [], "tabu": [], "next": 1, "log": [], "passes": 0}
        if self.path and self.path.is_file():
            self.d = json.loads(self.path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ persistence
    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def items(self) -> list[dict]:
        return self.d["items"]

    def get(self, iid) -> dict | None:
        try:
            iid = int(iid)
        except (TypeError, ValueError):
            return None
        return next((x for x in self.items if x["id"] == iid), None)

    def add(self, clip, frame, region, issue, sev="MEDIUM") -> dict:
        sev = str(sev or "MEDIUM").upper()
        sev = {"MED": "MEDIUM", "LARGE": "BIG", "B": "BIG", "M": "MEDIUM", "S": "SMALL"}.get(sev, sev)
        if sev not in SEVS:
            sev = "MEDIUM"
        it = {"id": self.d["next"], "clip": clip, "frame": frame, "region": str(region or "")[:40],
              "issue": str(issue)[:100], "sev": sev, "status": "open", "attempts": [], "steps": 0, "sinceAccept": 0,
              "rejectRun": 0, "parks": 0, "t": round(time.time(), 1)}
        self.d["next"] += 1
        self.items.append(it)
        self.save()
        return it

    # ------------------------------------------------------------ order and NOW
    def open_items(self) -> list[dict]:
        return sorted([x for x in self.items if x["status"] == "open"], key=lambda x: (SEVS.index(x["sev"]), x["id"]))

    def now(self) -> dict | None:
        w = self.get(self.d.get("work"))
        if w and w["status"] == "open":
            return w
        op = self.open_items()
        self.d["work"] = op[0]["id"] if op else None
        return op[0] if op else None

    def work(self, iid) -> str:
        it = self.get(iid)
        if not it or it["status"] != "open":
            return f"#{iid} is not an open item"
        self.d["work"] = it["id"]
        self.save()
        return f"working on #{it['id']} now"

    def done(self) -> bool:
        """Nothing open and no parked item left with a pass to spend."""
        if self.open_items():
            return False
        again = [x for x in self.items if x["status"] == "parked" and x["parks"] <= SECOND_PASS]
        if again and self.d["passes"] < SECOND_PASS:
            self.d["passes"] += 1
            for x in again:
                x["status"], x["rejectRun"], x["sinceAccept"] = "open", 0, 0
            self._log("every item was closed or parked: parked items reopened for one more pass: "
                      + " ".join(f"#{x['id']}" for x in again))
            self.save()
            return False
        return True

    def _log(self, text):
        self.d["log"].append({"t": round(time.time(), 1), "text": text})
        self.d["log"] = self.d["log"][-200:]
        return text

    # ------------------------------------------------------------ tabu
    @staticmethod
    def signature(item_id, att: dict) -> dict:
        """(item, goal, limb, chain, direction, strength) for intents; (item, bone, axis, sign) for low-level parts."""
        if att.get("goal"):
            return {"item": item_id, "kind": "intent", "goal": att["goal"], "limb": att.get("limb") or "",
                    "chain": att.get("chain", ""), "dir": dir_key(att), "strength": round(float(att.get("strength", 1)), 2),
                    "frames": frames_key(att.get("frames", []))}
        return {"item": item_id, "kind": "raw", "moves": sorted(att.get("moves", []))}

    @staticmethod
    def same(a: dict, b: dict) -> bool:
        keys = ("item", "kind", "goal", "limb", "chain", "dir", "strength", "frames", "moves")
        return all(a.get(k) == b.get(k) for k in keys)

    def tabu_hit(self, sig: dict) -> dict | None:
        return next((t for t in self.d["tabu"] if self.same(t["sig"], sig)), None)

    def record(self, item_id, att: dict, verdict: dict, fixed=False, step=None) -> str:
        """One judged attempt. A rejection becomes a tabu entry; an acceptance resets the item's stall counters and
        closes the item when the judge also said the problem is gone. Returns words for the turn text."""
        it = self.get(item_id)
        sig = self.signature(item_id, att)
        rec = {"sig": sig, "verdict": verdict.get("verdict"), "accept": bool(verdict.get("accept")),
               "fixed": bool(fixed), "step": step, "t": round(time.time(), 1), "what": att.get("what", "")[:120]}
        msg = []
        if it is not None:
            it["attempts"].append(rec)
        if rec["accept"]:
            if it is not None:
                it["rejectRun"], it["sinceAccept"] = 0, 0
                it.setdefault("accepted", 0)
                it["accepted"] += 1
                if fixed:
                    it["status"] = "closed"
                    it["closedBy"] = "judge"
                    msg.append(self._log(f"#{item_id} CLOSED by the judge"))
        else:
            self.d["tabu"].append({"sig": sig, "verdict": rec["verdict"], "what": rec["what"], "step": step})
            if it is not None:
                it["rejectRun"] += 1
                if it["rejectRun"] >= REJECT_PARK and it["status"] == "open":
                    msg.append(self.park(it, f"{it['rejectRun']} judge rejections in a row"))
        self.save()
        return "; ".join(msg)

    def dismissed(self, item_id, att: dict, step=None):
        """The proposer picked none of the candidates: that intent (all its strengths) becomes tabu too."""
        sig = dict(self.signature(item_id, att), strength="any")
        self.d["tabu"].append({"sig": sig, "verdict": "picked none", "what": att.get("what", "")[:120], "step": step})
        self.save()

    def is_tabu(self, item_id, att: dict) -> dict | None:
        sig = self.signature(item_id, att)
        hit = self.tabu_hit(sig)
        if hit is None and sig["kind"] == "intent":
            hit = self.tabu_hit(dict(sig, strength="any"))
        return hit

    def park(self, it: dict, why: str) -> str:
        it["status"], it["parked"] = "parked", why[:80]
        it["parks"] += 1
        if self.d.get("work") == it["id"]:
            self.d["work"] = None
        nxt = self.now()
        self.save()
        return self._log(f"parked #{it['id']} ({why}); " + (f"next: #{nxt['id']}" if nxt else "nothing else open"))

    def step(self, iid) -> str | None:
        """Count a fix-phase step against the item worked; park on a stall."""
        it = self.get(iid)
        if not it or it["status"] != "open":
            return None
        it["steps"] += 1
        it["sinceAccept"] += 1
        if it["sinceAccept"] >= STALL_STEPS:
            return self.park(it, f"{it['sinceAccept']} steps without an accepted change")
        self.save()
        return None

    # ------------------------------------------------------------ words
    def line(self) -> str:
        if not self.items:
            return "ITEMS: none yet"
        now = self.now()
        out = []
        for x in sorted(self.items, key=lambda x: (x["status"] != "open", SEVS.index(x["sev"]), x["id"])):
            if x["status"] == "open":
                acc = x.get("accepted", 0)
                rej = sum(1 for a in x["attempts"] if not a["accept"])
                out.append(f"#{x['id']} {x['sev']} {x['clip'].replace('Unit_', '')}"
                           + (f" f{x['frame']}" if x.get("frame") is not None else "") + f" {x['region']}: {x['issue']}"
                           + (f" [{acc} accepted, {rej} rejected]" if acc or rej else ""))
        closed = [x for x in self.items if x["status"] == "closed"]
        parked = [x for x in self.items if x["status"] == "parked"]
        s = "ITEMS (only the judge closes them): " + ("; ".join(out) or "none open")
        if closed:
            s += " | closed: " + " ".join(f"#{x['id']}" for x in closed)
        if parked:
            s += " | parked: " + " ".join(f"#{x['id']}" for x in parked)
        if now:
            s += f" | NOW #{now['id']}"
        return s

    def tabu_line(self, focus_item=None, limit=10) -> str:
        t = self.d["tabu"]
        if not t:
            return "TABU: none yet"
        mine = [x for x in t if x["sig"].get("item") == focus_item] if focus_item else []
        rest = len(t) - len(mine)
        show = (mine or t)[-limit:]

        def w(x):
            s = x["sig"]
            if s["kind"] == "intent":
                st = s["strength"] if s["strength"] == "any" else f"{int(round(s['strength'] * 100))}%"
                return (f"#{s['item']} {s['goal']}" + (f" {s['limb']}" if s["limb"] else "") + f" {s['dir']} {s['frames']}"
                        f" via {s['chain']} {st} ({x['verdict']})")
            return f"#{s['item']} {' + '.join(s['moves'])} ({x['verdict']})"
        return ("TABU (judge-rejected or dismissed; do not repeat, change goal/chain/direction/strength): "
                + "; ".join(w(x) for x in show) + (f" (+{rest} on other items)" if mine and rest else ""))


def raw_moves(parts: list[dict]) -> list[str]:
    """Low-level parts as (bone, axis, sign) moves for a raw tabu signature."""
    out = []
    for e in parts:
        if e.get("kind") == "rot" and e.get("axis") in ("pitch", "yaw", "roll"):
            out.append(f"{e['bone']} {e['axis']}{'+' if e['deg'] > 0 else '-'}")
        elif e.get("kind") == "tr":
            k = max(range(3), key=lambda i: abs(e["tr"][i]))
            out.append(f"{e['bone']} {'xyz'[k]}{'+' if e['tr'][k] > 0 else '-'}")
    return sorted(set(out))


def median(xs):
    xs = sorted(x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])
