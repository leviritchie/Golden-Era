"""Coarse-to-fine funnel for the fix phase (round 4, 2026-10-08).

Haiku rates every checklist item BIG / MEDIUM / SMALL itself. The fix phase works the tiers in order (BIG, then
MEDIUM, then SMALL), each with a share of the run's step budget (leftover rolls forward). A tier ends when its items
are all fixed / dropped / parked: after a quick check from 2-3 free-camera angles, Haiku advances with
{"op":"tier","to":"next"}. In SMALL Haiku may re-survey; a new or reopened BIG item jumps back to the BIG tier.

Loop breaking is a tool behaviour, not a quality rule: the item being worked is PARKED when Haiku cycles on it
(the same joint+axis flipping sign again and again, apply/revert cycles, or many steps with no kept net change).
Parked items come back once, in the SMALL tier.

All state lives in st["funnel"] and the checklist items (sev, status open|fixed|dropped|parked) so it is saved with
the stack and shown in the viewer."""
from __future__ import annotations

import hashlib

import numpy as np

TIERS = ("BIG", "MEDIUM", "SMALL")
SPLIT = (0.5, 0.3, 0.2)
STALL_STEPS = 12          # steps on one item with no kept net change
FLIPS = 3                 # sign flips on one joint+axis within one item
REVERT_RUN = 5            # reverts in a row with no kept net change
CHECK_VIEWS = 2           # distinct free-camera angles before a tier can be left
JUMP_MIN = 10             # steps lent to BIG when a BIG regression appears in a later tier


def item_tier(it: dict) -> str:
    return "SMALL" if it.get("revisit") else it.get("sev", "MEDIUM")


def short(it: dict) -> str:
    return (f"#{it['id']} {it['clip'].replace('Unit_', '')}" + (f" f{it['frame']}" if it.get("frame") is not None else "")
            + f" {it['region']}: {it['issue']}")


class Funnel:
    def __init__(self, bench):
        self.b = bench

    # ------------------------------------------------------------------ state
    @property
    def st(self):
        return self.b.st

    @property
    def f(self) -> dict | None:
        return self.st.get("funnel")

    def cl(self) -> list[dict]:
        return self.st.setdefault("checklist", [])

    def start(self, total: int):
        """Called when the fix phase starts: budgets from the steps left in the run, first tier with open items."""
        old = self.st.get("funnel") or {}
        spent = int(old.get("spent", 0)) + (sum(old.get("used", {}).values()) if old.get("used") else 0)
        rnd = int(old.get("round", 0)) + 1
        total = max(int(total or 300) - spent, 6)
        bud = {t: int(round(total * s)) for t, s in zip(TIERS, SPLIT)}
        self.st["funnel"] = {"tier": None, "budget": bud, "used": {t: 0 for t in TIERS}, "total": total,
                             "work": None, "check": None, "visitKeeps": 0, "item": None, "log": [], "jumpFrom": None,
                             "revisited": False, "spent": spent, "round": rnd}
        self._enter(self._first_tier(0), why="the fix phase starts")

    def reset(self):
        self.st["funnel"] = None

    def open_in(self, tier: str) -> list[dict]:
        return [x for x in self.cl() if x["status"] == "open" and item_tier(x) == tier]

    def _first_tier(self, k: int) -> str:
        for t in TIERS[k:]:
            if self.open_in(t):
                return t
        return "SMALL" if k < len(TIERS) else "DONE"      # SMALL always runs: it is where the re-survey happens

    def _log(self, text: str):
        f = self.f
        f["log"].append({"turn": sum(f["used"].values()), "tier": f["tier"], "text": text})
        f["log"] = f["log"][-40:]
        return text

    def _enter(self, tier: str, why: str) -> str:
        f = self.f
        prev = f["tier"]
        if prev in TIERS and tier in TIERS and TIERS.index(tier) > TIERS.index(prev):
            for t in TIERS[TIERS.index(prev):TIERS.index(tier)]:        # leftover budget rolls forward
                left = f["budget"][t] - f["used"][t]
                if left > 0:
                    f["budget"][t] -= left
                    f["budget"][tier] += left
        f["tier"], f["check"], f["visitKeeps"], f["item"], f["work"] = tier, None, 0, None, None
        f["recentYaws"] = []
        msg = []
        if tier == "SMALL" and not f["revisited"]:
            f["revisited"] = True
            back = [x for x in self.cl() if x["status"] == "parked" and not x.get("revisited")]
            for x in back:
                x["status"], x["revisit"], x["revisited"] = "open", True, True
            if back:
                msg.append("parked items reopened once for this tier: " + " ".join(f"#{x['id']}" for x in back))
            msg.append("you may first re-survey (view + note with sev) for BIG problems your own changes made; "
                       "a BIG note jumps back to the BIG tier")
        self._pick_item()
        if tier == "SMALL" and not self.open_in("SMALL"):
            f["check"] = {"yaws": [], "turn0": sum(f["used"].values())}
            msg.append("nothing open in SMALL: re-survey from 2-3 angles for anything still wrong (note it with sev), "
                       'then {"op":"tier","to":"next"}')
        return self._log(f"TIER {tier} ({why})" + ("; " + "; ".join(msg) if msg else ""))

    def _pick_item(self):
        f = self.f
        if f["tier"] not in TIERS:
            f["work"] = None
            return
        ops = self.open_in(f["tier"])
        cur = next((x for x in ops if x["id"] == f["work"]), None)
        it = cur or (ops[0] if ops else None)
        if it is None:
            f["work"], f["item"] = None, None
            return
        if f["work"] != it["id"] or not f["item"]:
            f["work"] = it["id"]
            f["item"] = {"id": it["id"], "steps": 0, "since": 0, "fp": self.fingerprint(), "reverts": 0,
                         "signs": {}, "pend": None}

    # ------------------------------------------------------------------ the kept net change, as a fingerprint
    def fingerprint(self) -> str:
        h = hashlib.sha1()
        for e in sorted(self.st["kept"], key=lambda e: (e["clip"], e["bone"], e["kind"])):
            h.update(f"{e['clip']}|{e['bone']}|{e['kind']}".encode())
            v = e.get("q") if e["kind"] == "net" else e.get("d") if e["kind"] == "nettr" else [e.get("deg", 0)]
            if v is not None:
                h.update(np.round(np.asarray(v, float), 2).tobytes())
        for m in self.st["mops"]:
            h.update(str(m.get("id")).encode())
        return h.hexdigest()[:16]

    # ------------------------------------------------------------------ ops Haiku sends
    def tier_op(self, op: dict) -> dict:
        f = self.f
        if not f or f["tier"] not in TIERS:
            return {"error": "tier: the funnel is not running (fix phase only)"}
        if str(op.get("to", "next")) != "next":
            return {"error": 'tier: "to" must be "next"'}
        if f["check"] is None and len(set(f.get("recentYaws", []))) >= CHECK_VIEWS:
            return {"note": self._advance("you checked it from %d angles and moved on" % len(set(f["recentYaws"])))}
        if f["check"] is None:
            f["check"] = {"yaws": [], "turn0": sum(f["used"].values())}
            left = self.open_in(f["tier"])
            return {"note": self._log(f"TIER {f['tier']} CHECK: view the result from {CHECK_VIEWS}-3 free-camera angles "
                                      "(different yaw), then send tier next again"
                                      + ("; still open here (they will be parked): "
                                         + " ".join(f"#{x['id']}" for x in left) if left else ""))}
        if len(set(f["check"]["yaws"])) < CHECK_VIEWS:
            return {"error": f"tier check: {len(set(f['check']['yaws']))} of {CHECK_VIEWS} angles viewed so far; "
                             "view from another yaw first"}
        return {"note": self._advance("you checked it and moved on")}

    def _advance(self, why: str) -> str:
        f = self.f
        t = f["tier"]
        left = self.open_in(t)
        for x in left:
            self._park(x, "left open at the tier exit", log=False)
        if f.get("jumpFrom") and t == "BIG":
            f["jumpFrom"] = None
        k = TIERS.index(t) + 1
        nxt = self._first_tier(k) if k < len(TIERS) else "DONE"
        if nxt == "DONE":
            f["tier"], f["work"], f["item"], f["check"] = "DONE", None, None, None
            return self._log(f"tier {t} done ({why}); ALL TIERS DONE")
        return self._enter(nxt, f"tier {t} done: {why}")

    def note_hook(self, op: dict, before: dict[int, str]) -> str | None:
        """After a note op: new or reopened BIG items in a later tier jump back; a finished tier goes to its check."""
        f = self.f
        if not f or f["tier"] not in TIERS + ("DONE",):
            return None
        msgs = []
        if op.get("work") is not None:
            it = next((x for x in self.cl() if x["id"] == int(op["work"])), None)
            if it and it["status"] == "open" and item_tier(it) == f["tier"]:
                f["work"], f["item"] = it["id"], None
                self._pick_item()
                msgs.append(f"working on #{it['id']} now")
        big_new = [x for x in self.cl() if x["status"] == "open" and item_tier(x) == "BIG"
                   and before.get(x["id"]) != "open"]
        if big_new and f["tier"] != "BIG":
            src = f["tier"]
            if src in TIERS:
                left = f["budget"][src] - f["used"][src]
                lend = min(max(JUMP_MIN, left // 3), max(left, 0))
                f["budget"][src] -= lend
                f["budget"]["BIG"] = f["used"]["BIG"] + max(lend, JUMP_MIN)
            else:                                   # DONE: a small fresh budget for the regression
                f["budget"]["BIG"] = f["used"]["BIG"] + JUMP_MIN
            f["jumpFrom"] = src
            f["tier"] = None
            msgs.append(self._enter("BIG", "BIG regression " + " ".join(f"#{x['id']}" for x in big_new)
                                    + f" found during {src}: back to BIG"))
        elif f["tier"] in TIERS:
            if f["check"] is not None and self.open_in(f["tier"]):
                f["check"] = None
                msgs.append("tier check cancelled: an item in this tier is open again")
            self._pick_item()
            if not self.open_in(f["tier"]) and f["check"] is None:
                msgs.append(self._finish_tier())
        return "; ".join(m for m in msgs if m) or None

    def _finish_tier(self) -> str:
        f = self.f
        if f["visitKeeps"] == 0:
            return self._advance("no open items left and nothing changed in it")
        f["check"] = {"yaws": [], "turn0": sum(f["used"].values())}
        return self._log(f"TIER {f['tier']}: every item is closed. CHECK: view the result from {CHECK_VIEWS}-3 "
                         'free-camera angles (different yaw), then {"op":"tier","to":"next"}')

    def _park(self, it: dict, why: str, log=True) -> str:
        it["status"], it["parked"] = "parked", why[:80]
        if it.get("revisit"):
            it["revisit"] = False              # parked twice: stays parked
        f = self.f
        if f["work"] == it["id"]:
            f["work"], f["item"] = None, None
        t = f"parked #{it['id']}: {why}; move on"
        return self._log(t) if log else t

    # ------------------------------------------------------------------ after every fix-phase turn
    def after_turn(self, op: dict, res: dict) -> str | None:
        f = self.f
        if not f or self.st.get("phase") != "fix" or f["tier"] not in TIERS:
            return None
        kind = (op or {}).get("op")
        if kind == "phase":
            return None
        tier = f["tier"]
        if kind != "pick":
            f["used"][tier] += 1
        msgs = []
        if kind == "view" and not res.get("error"):
            y = int(round(float(op.get("yaw", 30) or 0))) % 360
            f.setdefault("recentYaws", []).append(y)
            if f["check"] is not None:
                f["check"]["yaws"].append(y)
        if res.get("resolved") == "kept" or (kind == "keep" and not res.get("error")):
            f["visitKeeps"] += 1
            f["recentYaws"] = []            # views count for a tier check only when taken after the last kept change
        self._pick_item()
        it = next((x for x in self.cl() if x["id"] == f["work"]), None)
        s = f["item"]
        if it and s and kind not in ("note", "tier", "view") and f["check"] is None:
            s["steps"] += 1
            fp = self.fingerprint()
            if fp != s["fp"]:
                s["fp"], s["since"], s["reverts"] = fp, 0, 0
            else:
                s["since"] += 1
                if res.get("resolved") == "reverted" or (kind == "pick" and str(op.get("which", "")).upper() not in ("A", "B")):
                    s["reverts"] += 1
            p = self.st.get("pending")
            if p and p.get("id") != s["pend"]:
                s["pend"] = p["id"]
                for e in p.get("parts", []):
                    if e.get("kind") == "rot" and abs(float(e.get("deg", 0))) > 0.5:
                        key, sg = f"{e['bone']} {e['axis']}", 1 if e["deg"] > 0 else -1
                    elif e.get("kind") == "tr" and e.get("tr"):
                        a = int(np.argmax(np.abs(e["tr"])))
                        key, sg = f"{e['bone']} {'xyz'[a]}-move", 1 if e["tr"][a] > 0 else -1
                    else:
                        continue
                    last, n = s["signs"].get(key, (0, 0))
                    s["signs"][key] = (sg, n + (1 if last and sg != last else 0))
            why = None
            flip = [(k, n) for k, (_, n) in s["signs"].items() if n >= FLIPS]
            if flip:
                why = f"you've cycled on {flip[0][0]} (+/- {flip[0][1] + 1} times)"
            elif s["reverts"] >= REVERT_RUN:
                why = f"{s['reverts']} apply/revert cycles with no kept change"
            elif s["since"] >= STALL_STEPS:
                why = f"{s['since']} steps on it with no kept net change"
            if why:
                msgs.append(self._park(it, why))
                self._pick_item()
                if f["work"] is not None:
                    msgs.append("next: " + short(next(x for x in self.cl() if x["id"] == f["work"])))
                elif f["check"] is None:
                    msgs.append(self._finish_tier())
        if f["tier"] in TIERS and f["used"][f["tier"]] >= f["budget"][f["tier"]]:
            msgs.append(self._advance(f"its budget of {f['budget'][f['tier']]} steps is used"))
        return "; ".join(m for m in msgs if m) or None

    # ------------------------------------------------------------------ words for the state line
    def line(self) -> str:
        f = self.f
        if not f:
            return ""
        if f["tier"] == "DONE":
            return f"FUNNEL: round {f.get('round', 1)} done (all tiers)"
        t = f["tier"]
        left = {x: max(f["budget"][x] - f["used"][x], 0) for x in TIERS}
        s = (f"FUNNEL: round {f.get('round', 1)}, tier {t} (step {f['used'][t]}/{f['budget'][t]}; later: "
             + ", ".join(f"{x} {left[x]}" for x in TIERS[TIERS.index(t) + 1:]) + ")")
        if f.get("jumpFrom"):
            s += f" [jumped back from {f['jumpFrom']}]"
        if f["check"] is not None:
            n = len(set(f["check"]["yaws"]))
            s += (f" | TIER CHECK: {n}/{CHECK_VIEWS} angles viewed; view from different yaws, then "
                  '{"op":"tier","to":"next"} (or reopen/add items)')
            closed = [x for x in self.cl() if x["status"] == "fixed" and item_tier(x) == t]
            if closed:
                s += ("; you marked fixed (compare each with the picture and OURS NOW): "
                      + "; ".join(f"#{x['id']} {x['region']}: {x['issue'][:70]}" for x in closed))
        elif f["work"] is not None:
            it = next(x for x in self.cl() if x["id"] == f["work"])
            st_ = f["item"] or {}
            s += f" | NOW {short(it)}" + (f" ({st_.get('steps', 0)} steps on it)" if st_.get("steps") else "")
        park = [x for x in self.cl() if x["status"] == "parked"]
        if park:
            s += " | parked: " + " ".join(f"#{x['id']}" for x in park)
        return s

    def public(self) -> dict | None:
        f = self.f
        if not f:
            return None
        return {"finished": bool(f.get("finished")), "tier": f["tier"], "budget": f["budget"], "used": f["used"], "work": f["work"], "round": f.get("round", 1),
                "spent": f.get("spent", 0),
                "check": f["check"], "jumpFrom": f.get("jumpFrom"), "log": f["log"][-12:]}
