"""Round 5 mode of the bench server (2026-10-08): intent ops with candidates, a blind judge, a persistent item list
with tabu, and mesh repair out of the proposer's loop.

  intent   -> the bench solves the joints (intent.IntentSolver) and renders 3-4 candidates next to the DEF;
  pick     -> the chosen candidate becomes the pending change and is sent to the judge (the driver runs it);
  keep     -> a low-level pending change (edit/pose/try) is sent to the judge;
  check    -> the judge compares ORIGINAL vs NOW for an item (closes it when NOW wins both orders and is fixed);
  verdict  -> (driver) accept: keep + auto repair; reject: revert + tabu.
The proposer cannot close items, cannot keep a change without the judge, and sees the mesh only as
"clean / flagged at <body part>". Repair/rig ops stay available as an advanced fallback.
"""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from anim_core import friendly
from anim_gl import BG, C_BIG
from intent import GOALS, IntentSolver, elev_az, readout, readout_text
from r5_items import ItemStore, judge_verdict, raw_moves

JT = 160            # judge / board tile


def jpeg(img: Image.Image, q=85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return buf.getvalue()


class R5Mode:
    def __init__(self, bench, run_dir: Path):
        self.b = bench
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.items = ItemStore(self.run_dir / "items.json")
        self.items.d.setdefault("stats", {"tabuRefused": 0, "tabuFiltered": 0, "judged": 0, "accepted": 0,
                                          "rejected": 0, "autoRepairs": 0, "repairKept": 0})
        self.solver = IntentSolver(bench.u)
        self.trial = None
        self.meta = None            # what the pending change is (item, attempt signature fields)
        self.mesh = {}              # clip -> words, from the last all-clip check

    # ------------------------------------------------------------ words
    def spot_words(self, mask) -> str:
        u = self.b.u
        s = u.scene
        vs = np.unique(u.edges[mask])
        w = np.zeros(len(u.jnames))
        np.add.at(w, s.J[vs].ravel(), s.W[vs].ravel())
        top = [u.jnames[j] for j in np.argsort(-w)[:2] if w[j] > 0.25 * w.max()]
        return " / ".join(friendly(b) for b in top)

    def spot_bones(self, mask) -> list[str]:
        u = self.b.u
        s = u.scene
        vs = np.unique(u.edges[mask])
        w = np.zeros(len(u.jnames))
        np.add.at(w, s.J[vs].ravel(), s.W[vs].ravel())
        return [u.jnames[j] for j in np.argsort(-w)[:3] if w[j] > 0.15 * w.max()]

    def mesh_line(self) -> str:
        b = self.b
        f = b.st["focus"]["clip"]
        flags = dict(self.mesh)
        if b.defect.get("open") and b.defect.get("clip") == f:
            flags[f] = " / ".join(friendly(x) for x in b.spot_bones(b.defect))
        elif b.defect.get("clip") == f:
            flags.pop(f, None)
        if not flags:
            return "MESH: clean"
        return "MESH: flagged at " + "; ".join(f"the {w} ({c.replace('Unit_', '')})" for c, w in flags.items())

    def readout_line(self, clip, frame, edits) -> str:
        try:
            G = self.solver.pose_at(clip, frame, edits)
            return (f"READOUT f{int(frame)} (OUR pose only, degrees; elev + = up, az 0 = forward, + = toward its left): "
                    + readout_text(readout(self.solver.an, G)))
        except Exception as e:  # noqa: BLE001  (an aid; never breaks a step)
            return f"READOUT unavailable ({type(e).__name__})"

    def state_line(self) -> str:
        b = self.b
        st = b.st
        f = st["focus"]
        ph = st.get("phase", "fix")
        now = self.items.now()
        return (("PHASE 1 SURVEY. " if ph == "survey" else "")
                + f"clip {f['clip']} f{f['frame']}/{b.u.clips[f['clip']]['n'] - 1}; {b.pending_line()}; "
                + self.mesh_line()
                + "\nOURS NOW " + b.ours_line(f["clip"], f["frame"], b.edits())
                + "\n" + self.readout_line(f["clip"], f["frame"], b.edits())
                + "\nNET POSE " + f["clip"].replace("Unit_", "") + ": " + b.net_line(f["clip"])
                + "\n" + self.items.line()
                + "\n" + self.items.tabu_line(now["id"] if now else None))

    def _res(self, kind, **kw) -> dict:
        b = self.b
        r = {"op": kind, "resolved": None, "error": None, "mesh": self.mesh_line(), "sheetId": b.sheet_id}
        r.update(kw)
        b.save()
        r["state"] = self.state_line()
        r["items"] = self.public()
        return r

    def public(self) -> dict:
        return {"items": self.items.items, "tabu": len(self.items.d["tabu"]), "stats": self.items.d["stats"],
                "now": (self.items.now() or {}).get("id"), "done": False, "limbs": self.solver.an.limb_list()}

    # ------------------------------------------------------------ the op router (called first by Bench.apply)
    def apply(self, op: dict) -> dict | None:
        """Handle a round 5 op, or pre-process one for the base bench and return None."""
        b = self.b
        kind = op.get("op")
        if kind == "intent":
            return self.intent(op)
        if kind == "check":
            it = self.items.get(op.get("item") or op.get("id")) or self.items.now()
            if it is None:
                return self._res("check", error="check: no such item")
            return self._res("check", needsJudge={"mode": "check", "item": it["id"]},
                             note=f"asking the judge whether #{it['id']} is fixed (original vs now)")
        if kind == "pick" and self.trial and self.trial.get("kind") == "intent":
            return self.pick(op)
        if kind == "tier":
            return self._res("tier", error="there are no tiers in this run: work the ITEMS list")
        if kind == "undo":
            return self._res("undo", error="undo is off: a judge-accepted change is replaced only by a better one "
                                           "the judge accepts (send an intent for that item)")
        if kind == "note":
            return self.note(op)
        if kind == "keep":
            p = b.st["pending"]
            if not p:
                return self._res("keep", note="nothing pending")
            it = self.items.get(op.get("item") or p.get("item")) or self.items.now()
            self.meta = self.meta or {}
            self.meta.setdefault("item", it["id"] if it else None)
            if not self.meta.get("att"):
                self.meta["att"] = {"moves": raw_moves(p.get("parts", [])), "what": b.pending_line()}
            hit = self.items.is_tabu(self.meta["item"], self.meta["att"]) if self.meta.get("item") else None
            if hit:
                self.items.d["stats"]["tabuRefused"] += 1
                b._resolve_pending("revert")
                self.meta = None
                b._render()
                return self._res("keep", error=f"that change repeats a TABU attempt ({hit['verdict']}); it was "
                                               "dropped. Change the joint, direction or strength")
            return self._res("keep", needsJudge={"mode": "pending", "item": self.meta["item"]},
                             note="sent to the judge")
        if kind in ("edit", "pose", "try", "repair", "rig", "look", "move") and b.st["pending"] \
                and op.get("prev") != "revert":
            b._resolve_pending("revert")
            self.meta = None
            op["prev"] = "revert"
            op["_r5note"] = "your unjudged pending change was dropped (only keep or pick sends a change to the judge)"
        if kind in ("edit", "pose", "try"):
            self.meta = {"item": (self.items.get(op.get("item")) or self.items.now() or {}).get("id")}
        return None

    def after_base(self, op: dict, res: dict) -> dict:
        """Base-bench result post-processing in round 5 mode."""
        if op.get("_r5note"):
            res["note"] = op["_r5note"] + ("; " + res["note"] if res.get("note") else "")
        if op.get("op") == "pick" and self.b.st["pending"] and not res.get("error"):
            res["needsJudge"] = {"mode": "pending", "item": (self.meta or {}).get("item")}
            self.meta = dict(self.meta or {}, att={"moves": raw_moves(self.b.st["pending"]["parts"]),
                                                   "what": self.b.pending_line()})
            hit = self.items.is_tabu(self.meta.get("item"), self.meta["att"]) if self.meta.get("item") else None
            if hit:
                self.items.d["stats"]["tabuRefused"] += 1
                self.b._resolve_pending("revert")
                self.meta = None
                res.pop("needsJudge", None)
                res["error"] = f"that change repeats a TABU attempt ({hit['verdict']}); it was dropped"
        elif op.get("op") in ("edit", "pose") and self.b.st["pending"] and not res.get("error"):
            res["note"] = ((res.get("note") + "; ") if res.get("note") else "") + \
                'pending: send {"op":"keep"} to have it judged, or {"op":"revert"}'
        res["state"] = self.state_line()
        res["mesh"] = self.mesh_line()
        res["items"] = self.public()
        return res

    # ------------------------------------------------------------ notes = items
    def note(self, op: dict) -> dict:
        b = self.b
        if op.get("work") is not None and not op.get("items") and not op.get("issue"):
            return self._res("note", note=self.items.work(op["work"]))
        if op.get("status") is not None or (op.get("id") is not None and not op.get("issue")):
            return self._res("note", error="items close only by a judge win (send a change, or check an item); "
                                           "you cannot mark them fixed or dropped")
        added = []
        for x in (op.get("items") if isinstance(op.get("items"), list) else [op]):
            if not isinstance(x, dict) or not x.get("issue"):
                return self._res("note", error="a note needs \"issue\" (and clip, frame, region, sev)")
            c = x.get("clip") or b.st["focus"]["clip"]
            if c not in b.u.clips:
                return self._res("note", error=f"unknown clip {c!r}")
            fr = x.get("frame")
            try:
                fr = None if fr is None else int(np.clip(int(fr), 0, b.u.clips[c]["n"] - 1))
            except (TypeError, ValueError):
                fr = None
            added.append(self.items.add(c, fr, x.get("region"), x["issue"], x.get("sev"))["id"])
        return self._res("note", note="added item " + ", ".join(f"#{i}" for i in added))

    # ------------------------------------------------------------ intents
    def _frames(self, op, clip, it):
        n = self.b.u.clips[clip]["n"]
        fr = op.get("frames")
        if isinstance(fr, str) and fr.lower() == "all":
            return list(range(n)), True
        if isinstance(fr, list) and fr:
            a, z = (int(np.clip(int(fr[0]), 0, n - 1)), int(np.clip(int(fr[-1]), 0, n - 1)))
            return list(range(min(a, z), max(a, z) + 1)), True
        f = op.get("frame")
        if f is None:
            f = it["frame"] if it and it.get("frame") is not None and it["clip"] == clip else self.b.st["focus"]["frame"]
        return [int(np.clip(int(round(float(f))), 0, n - 1))], False

    def intent(self, op: dict) -> dict:
        t0 = time.perf_counter()
        b, u = self.b, self.b.u
        st = b.st
        if st.get("phase") == "survey":
            return self._res("intent", error="phase 1 is the survey: view, look and note only")
        notes = []
        if st["pending"]:
            b._resolve_pending("revert")
            self.meta = None
            notes.append("your unjudged pending change was dropped")
        it = self.items.get(op.get("item")) or self.items.now()
        clip = op.get("clip") or (it["clip"] if it else st["focus"]["clip"])
        if clip not in u.clips:
            return self._res("intent", error=f"unknown clip {clip!r}: one of {list(u.clips)}")
        goal = str(op.get("goal", "")).lower()
        if goal not in GOALS:
            return self._res("intent", error=f"goal must be one of {list(GOALS)}")
        try:
            frames, multi = self._frames(op, clip, it)
            hw = 1.0 if multi else float(np.clip(float(op.get("hw", 2) or 2), 1, 6))
            limb = op.get("limb")
            if goal in ("reach", "spread", "bend"):
                limb = self.solver.an.find_limb(limb)
            spec = {k: op[k] for k in ("dir", "elev", "az", "d_elev", "d_az", "amount", "deg") if op.get(k) is not None}
            att = dict(spec, goal=goal, limb=limb or "", frames=frames, mirror=bool(op.get("mirror")))
            iid = it["id"] if it else None
            filtered = []

            def skip(k, chain):
                hit = self.items.is_tabu(iid, dict(att, strength=k, chain=chain)) if iid else None
                if hit:
                    filtered.append(f"{int(k * 100)}% {chain}")
                return bool(hit)
            base = b.edits(False)
            n0 = b.gl.clip_defect_edges(clip, base)

            def tears(parts):
                n = b.gl.clip_defect_edges(clip, base + parts)
                return n, (self.spot_bones(b.gl.last_defect_mask) if n > n0 else [])
            vs = self.solver.variants(clip, frames, hw, base, goal, limb, spec, tears=tears, n0=n0,
                                      mirror=bool(op.get("mirror")), skip=skip)
        except (ValueError, TypeError, KeyError) as ex:
            return self._res("intent", error=str(ex))
        st["focus"] = {"clip": clip, "frame": frames[0] if not multi else (
            it["frame"] if it and it.get("frame") in frames else frames[len(frames) // 2])}
        live = [v for v in vs if not v.get("skipped")]
        if filtered:
            self.items.d["stats"]["tabuFiltered"] += len(filtered)
        if not live:
            self.items.d["stats"]["tabuRefused"] += 1
            self.items.save()
            return self._res("intent", error="every candidate of that intent is TABU for this item ("
                                             + ", ".join(filtered) + "): change the goal, direction, chain or frames")
        fs = st["focus"]["frame"]
        labels = [f"V{k + 1}" for k in range(len(live))]
        rows = ("sprite", "front", "top") if goal == "spread" else ("sprite", "side", "q34")
        z = b.gl.variants_sheet(clip, fs, base, [v["parts"] for v in live], labels, rows)
        b.sheet_jpeg = z["jpeg"]
        b.sheet_id += 1
        (b.dir / "sheets" / "latest.jpg").write_bytes(z["jpeg"])
        G0 = self.solver.pose_at(clip, fs, base)
        before = self._fword(goal, limb, G0)
        words = []
        for lab, v in zip(labels, live):
            G = self.solver.pose_at(clip, fs, base + v["parts"])
            mesh = "mesh clean" if not v["tears"] else (
                f"tears {'a small spot' if v['tears'] < 8 else 'a patch' if v['tears'] < 40 else 'a wide area'}"
                + (f" at the {' / '.join(friendly(x) for x in v['torn'][:2])}" if v["torn"] else ""))
            words.append(f"{lab} = {v['label']} [{v['share']}] -> {self._fword(goal, limb, G)}; {mesh}")
        self.trial = {"kind": "intent", "variants": dict(zip(labels, live)), "item": iid, "att": att, "clip": clip,
                      "frames": frames, "goal": goal}
        self.items.save()
        tgt = f"{goal}" + (f" {limb}" if limb else "") + " " + " ".join(
            f"{k} {v}" for k, v in spec.items()) + (" mirrored" if op.get("mirror") else "")
        note = "; ".join(notes + ([f"skipped as TABU: {', '.join(filtered)}"] if filtered else []))
        st_line = (f"CANDIDATES for #{iid} ({tgt} at {('f' + str(frames[0])) if not multi else f'f{frames[0]}-f{frames[-1]}'};"
                   f" shown at f{fs}; now {before}): " + " | ".join(words)
                   + '. Reply {"op":"pick","which":"V2","why":"..."} to send one to the judge, or "which":"none".\n'
                   + self.items.tabu_line(iid))
        b.save()
        return {"op": "intent", "resolved": None, "error": None, "note": note or None, "mesh": self.mesh_line(),
                "sheetId": b.sheet_id, "state": st_line, "items": self.public(),
                "intent": {"variants": [{k: v[k] for k in ("label", "chain", "err", "turn", "tears", "share", "reweighted")}
                                        for v in live], "filtered": filtered},
                "ms": {"total": round((time.perf_counter() - t0) * 1000, 1), "sheet": z["ms"]["total"]}}

    def _fword(self, goal, limb, G) -> str:
        r = readout(self.solver.an, G)
        if goal == "gaze":
            return f"gaze elev {r['gaze'][0]:+.0f} az {r['gaze'][1]:+.0f}"
        if goal == "trunk":
            return f"trunk elev {r['trunk'][0]:+.0f} az {r['trunk'][1]:+.0f}"
        L = r["limbs"].get(limb, {})
        if goal == "bend":
            return f"{limb} bend {L.get('bend', 0):.0f}"
        if goal == "spread":
            return f"{limb} spread {L.get('spread', 0) * 100:.0f}%"
        return f"{limb} tip elev {L['tip'][0]:+.0f} az {L['tip'][1]:+.0f}"

    def pick(self, op: dict) -> dict:
        b = self.b
        tr, self.trial = self.trial, None
        w = str(op.get("which", "")).strip().upper()
        if w in ("1", "2", "3", "4"):
            w = "V" + w
        if w not in tr["variants"]:
            self.items.dismissed(tr["item"], dict(tr["att"], chain="any", what=f"{tr['goal']} intent, none picked"),
                                 step=None)
            b._render()
            return self._res("pick", note="none picked: that intent is now TABU for this item")
        v = tr["variants"][w]
        p = {"id": b.st["nextId"], "type": "pose", "parts": v["parts"], "why": str(op.get("why", ""))[:120],
             "item": str(tr["item"] or "")}
        b.st["nextId"] += 1
        b.st["pending"] = p
        b.st["tally"]["edits"] += 1
        self.meta = {"item": tr["item"], "att": dict(tr["att"], strength=v["strength"], chain=v["chain"],
                                                     what=f"{tr['goal']} {v['label']} [{v['share']}]")}
        b.st["focus"] = {"clip": tr["clip"], "frame": b.st["focus"]["frame"]}
        b._render()
        return self._res("pick", needsJudge={"mode": "pending", "item": tr["item"]},
                         note=f"picked {w} ({v['label']}): sent to the judge")

    # ------------------------------------------------------------ the judge's images
    def _rig_swap(self, ops):
        b = self.b
        b.rig.apply(ops)
        b.gl.upload_rig()

    def judge_pack(self, mode: str, iid) -> dict:
        b, u = self.b, self.b.u
        it = self.items.get(iid)
        p = b.st["pending"]
        if mode == "pending":
            if not p:
                raise ValueError("nothing pending to judge")
            clip = p["parts"][0]["clip"] if p.get("parts") else b.st["focus"]["clip"]
            frs = sorted({int(round(e["frame"])) for e in p.get("parts", []) if e.get("frame") is not None}) or [b.st["focus"]["frame"]]
            f = it["frame"] if it and it.get("frame") is not None and it["clip"] == clip and \
                (frs[0] <= it["frame"] <= frs[-1]) else frs[len(frs) // 2]
            before, after = b.edits(False), b.edits(True)
            pb = pa = None
        else:
            if it is None:
                raise ValueError("check needs an item")
            clip, f = it["clip"], it["frame"] if it.get("frame") is not None else 0
            before, after = [], b.edits(False)
            pb, pa = [], b.mops(False)
        film = b.film(clip)
        ft = min(64, (3 * JT) // max(len(film), 1))
        try:
            if pb is not None:
                self._rig_swap(pb)
            img_b = b.gl.panel(clip, f, before, film=film, ft=ft, T=JT)
            if pa is not None:
                self._rig_swap(pa)
            img_a = b.gl.panel(clip, f, after, film=film, ft=ft, T=JT)
        finally:
            if pb is not None:
                self._rig_swap(b.mops())
        problem = (f"{clip} f{f}" + (f" {it['region']}: {it['issue']}" if it else ""))
        top = self._def_rows(clip, f, film, ft)
        out = {}
        for key, (one, two) in (("ab", (img_b, img_a)), ("ba", (img_a, img_b))):
            out[key] = base64.b64encode(jpeg(self._judge_image(top, one, two, problem))).decode()
        return {"ab": out["ab"], "ba": out["ba"], "problem": problem, "clip": clip, "frame": f, "mode": mode,
                "item": it["id"] if it else None}

    def _def_rows(self, clip, f, film, ft) -> np.ndarray:
        gl = self.b.gl
        W = 3 * JT
        img = np.empty((JT + ft, W, 3), np.uint8)
        img[:] = BG
        img[:JT, :JT] = gl._def_tile(clip, f, JT)
        img[:JT, JT:2 * JT] = gl._def_tile(clip, f, JT, gl.def_head_boxes[clip][f])
        for k, fr in enumerate(film):
            img[JT:JT + ft, k * ft:(k + 1) * ft] = gl._def_tile(clip, fr, ft)
        return img

    def _judge_image(self, top, one, two, problem) -> Image.Image:
        W = top.shape[1]
        H = 16 + top.shape[0] + 2 * (16 + one.shape[0])
        im = Image.new("RGB", (W, H), BG)
        dr = ImageDraw.Draw(im)
        font = self.b.gl.font
        dr.text((3, 2), "DEF = the original sprite (reference): frame, head, the clip", fill=(10, 10, 10), font=font)
        im.paste(Image.fromarray(top), (0, 16))
        dr.text((2 * JT + 6, 22), "problem:", fill=(10, 10, 10), font=font)
        words = problem.split()
        line, y = "", 38
        for w in words:
            if len(line) + len(w) > 24:
                dr.text((2 * JT + 6, y), line, fill=(150, 0, 0), font=font)
                line, y = "", y + 14
            line = (line + " " + w).strip()
        dr.text((2 * JT + 6, y), line, fill=(150, 0, 0), font=font)
        y = 16 + top.shape[0]
        for lab, pan in (("1", one), ("2", two)):
            dr.rectangle((0, y, W, y + 15), fill=(60, 60, 60))
            dr.text((4, y + 2), f"VERSION {lab}: sprite cam | side (faces left) | 3/4 front-left; the clip",
                    fill=(255, 255, 255), font=font)
            im.paste(Image.fromarray(pan), (0, y + 16))
            y += 16 + pan.shape[0]
        return im

    # ------------------------------------------------------------ the verdict
    def verdict(self, body: dict) -> dict:
        b = self.b
        mode = body.get("mode", "pending")
        iid = body.get("item")
        v = judge_verdict(body.get("r_ab"), body.get("r_ba"))
        stt = self.items.d["stats"]
        stt["judged"] += 1
        rec = {"t": round(time.time(), 2), "step": body.get("step"), "mode": mode, "item": iid, **v,
               "r_ab": body.get("r_ab"), "r_ba": body.get("r_ba"), "ms": body.get("ms"),
               "what": ((self.meta or {}).get("att") or {}).get("what") if mode == "pending" else "check"}
        msg = []
        repair = None
        if mode == "check":
            it = self.items.get(iid)
            if v["accept"] and v["fixed"] and it and it["status"] != "closed":
                it["status"], it["closedBy"] = "closed", "judge (check)"
                msg.append(f"the judge confirms #{iid} is fixed: CLOSED")
                self.items.save()
            else:
                msg.append(f"the judge does not confirm #{iid} as fixed ({v['verdict']}); it stays open")
            if it:
                it.setdefault("checks", []).append({"verdict": v["verdict"], "fixed": v["fixed"], "step": body.get("step")})
                self.items.save()
        else:
            att = (self.meta or {}).get("att") or {"moves": raw_moves((b.st["pending"] or {}).get("parts", [])),
                                                     "what": b.pending_line()}
            if v["accept"]:
                stt["accepted"] += 1
                b._resolve_pending("keep")
                m = self.items.record(iid, att, v, fixed=v["fixed"], step=body.get("step"))
                msg.append(f"JUDGE ACCEPTED it (the change won both orders)"
                           + ("; the judge says the problem is gone" if v["fixed"] else
                              "; the judge says the problem is still visible: keep working this item"))
                if m:
                    msg.append(m)
                repair = self.auto_repair()
                rec["repair"] = repair
            else:
                stt["rejected"] += 1
                b._resolve_pending("revert")
                m = self.items.record(iid, att, v, step=body.get("step"))
                why = {"worse": "BEFORE won both orders: the change made it worse (wrong direction or too far)",
                       "split": "the two orders disagreed: no clear improvement",
                       "same": "no difference the judge could see"}[v["verdict"]]
                msg.append(f"JUDGE REJECTED it ({why}); reverted and added to TABU")
                if m:
                    msg.append(m)
            self.meta = None
        with open(self.run_dir / "judge.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        b._render()
        res = self._res("verdict", note="; ".join(msg), verdict=v, repair=repair)
        res["done"] = self.items.done()
        res["items"]["done"] = res["done"]
        return res

    # ------------------------------------------------------------ mesh repair, out of Haiku's loop
    def _spot_tries(self, mask) -> list:
        b, u = self.b, self.b.u
        s_ = u.scene
        vs = np.unique(u.edges[mask])
        P = s_.P[vs]
        ctr = np.median(P, 0)
        rad = float(np.percentile(np.linalg.norm(P - ctr, axis=1), 90)) + 0.04 * u.H
        w = {}
        for v in vs:
            for j, x in zip(s_.J[v], s_.W[v]):
                w[int(j)] = w.get(int(j), 0.0) + float(x)
        top = [u.jnames[j] for j, _ in sorted(w.items(), key=lambda q: -q[1])[:3]]
        tries = []
        if len(top) > 1 and not b._adjacent(top[0], top[1]):
            tries.append(([{"fix": "blend", "from": top[1], "to": top[0], "amount": 1.0, "center": ctr.tolist(),
                            "radius": rad}], f"gave {top[1]}'s skin there to {top[0]}"))
        for ring, k in ((3, 1.0), (6, 1.6)):
            tries.append(([{"fix": "smooth", "bones": top, "ring": ring, "center": ctr.tolist(), "radius": rad * k}],
                          f"smoothed {'/'.join(top)}"))
        return tries

    def auto_repair(self) -> dict:
        """After an accepted change: if any clip has new defect edges, try local seam fixes at each torn spot and the
        existing robust pre-pass; keep a repair only if the total tears go down and no clip gets worse."""
        t0 = time.perf_counter()
        b, u, gl = self.b, self.b.u, self.b.gl
        ed = b.edits(False)
        prior = b.mops(False)

        def counts():
            return {c: gl.clip_defect_edges(c, ed) for c in u.clips}
        n0 = counts()
        rep = {"before": sum(n0.values()), "kept": [], "tried": 0}
        if not rep["before"]:
            self.mesh = {}
            rep["after"] = 0
            rep["ms"] = round((time.perf_counter() - t0) * 1000)
            return rep
        self.items.d["stats"]["autoRepairs"] += 1
        acc = []
        try:
            tries = []
            for c in sorted(n0, key=lambda c: -n0[c]):
                if n0[c]:
                    gl.clip_defect_edges(c, ed)
                    tries += self._spot_tries(gl.last_defect_mask.copy())
            tries = tries[:9]
            for robust in (False, True):
                if robust:
                    if not sum(n0.values()):
                        break
                    foc = dict(b.st["focus"])
                    worst = max(n0, key=lambda c: n0[c])
                    b.st["focus"] = {"clip": worst, "frame": 0}
                    try:
                        tries = [(b._robust_mops(), "robust seam smoothing")]
                    except ValueError:
                        tries = []
                    finally:
                        b.st["focus"] = foc
                        self._rig_swap(prior + acc)
                for m, what in tries:
                    rep["tried"] += 1
                    try:
                        self._rig_swap(prior + acc + m)
                    except ValueError:
                        continue
                    n1 = counts()
                    if sum(n1.values()) < sum(n0.values()) and all(n1[c] <= n0[c] for c in n0):
                        acc += m
                        rep["kept"].append(what)
                        n0 = n1
                        if not sum(n0.values()):
                            break
                    self._rig_swap(prior + acc)
        finally:
            self._rig_swap(prior + acc)
            b.rig_key = ""
        if acc:
            st = b.st
            st["mops"] += [dict(m, id=st["nextId"], why="auto repair after an accepted change") for m in acc]
            st["nextId"] += 1
            self.items.d["stats"]["repairKept"] += 1
        b._apply_rig()
        self.mesh = {}
        for c in u.clips:
            if gl.clip_defect_edges(c, ed):
                self.mesh[c] = self.spot_words(gl.last_defect_mask)
        rep["after"] = sum(n0.values())
        rep["ms"] = round((time.perf_counter() - t0) * 1000)
        self.items.save()
        return rep

    # ------------------------------------------------------------ the before/after board (original vs now)
    def board(self, out: Path, cols=(("battle", "battle cam"), ("preview", "preview cam"), ("q34", "yawed 3/4"))) -> dict:
        b, u, gl = self.b, self.b.u, self.b.gl
        its = sorted(self.items.items, key=lambda x: (["BIG", "MEDIUM", "SMALL"].index(x["sev"]), x["id"]))[:8]
        if not its:
            its = [{"id": 0, "clip": b.st["focus"]["clip"], "frame": 0, "sev": "-", "status": "-", "region": "",
                    "issue": "(no items)"}]
        T = JT
        views = tuple(v for v, _ in cols)
        shots = {}
        try:
            for tag, mops, ed in (("before", [], []), ("after", b.mops(False), b.edits(False))):
                self._rig_swap(mops)
                for it in its:
                    f = it["frame"] if it.get("frame") is not None else 0
                    shots[(tag, it["id"])] = gl.panel(it["clip"], f, ed, views=views, T=T)
        finally:
            self._rig_swap(b.mops())
        W = T * (1 + 2 * len(cols))
        im = Image.new("RGB", (W, 22 + len(its) * (T + 18)), (235, 235, 235))
        dr = ImageDraw.Draw(im)
        dr.text((4, 4), f"{b.unit_id}: DEF | per camera BEFORE (original) then AFTER (round 5 result): "
                        + ", ".join(n for _, n in cols), fill=(0, 0, 0), font=gl.font)
        y = 22
        for it in its:
            f = it["frame"] if it.get("frame") is not None else 0
            dr.text((4, y + 2), (f"#{it['id']} {it['sev']} [{it['status']}] {it['clip'].replace('Unit_', '')} f{f} "
                                 f"{it['region']}: {it['issue']}")[:170], fill=(0, 0, 0), font=gl.font)
            im.paste(Image.fromarray(gl._def_tile(it["clip"], f, T)), (0, y + 16))
            for k, (v, name) in enumerate(cols):
                for j, tag in enumerate(("before", "after")):
                    tile = shots[(tag, it["id"])][:, k * T:(k + 1) * T]
                    x = T * (1 + 2 * k + j)
                    im.paste(Image.fromarray(tile), (x, y + 16))
                    dr.rectangle((x, y + 16, x + 70, y + 28), fill=(235, 235, 235))
                    dr.text((x + 2, y + 16), f"{tag} {name.split()[0]}", fill=(150, 0, 0) if tag == "after" else (0, 0, 0),
                            font=gl.font)
            y += T + 18
        im.save(out, quality=82)
        ed = b.edits(False)
        mesh = {}
        for c in u.clips:                       # final all-clip mesh check (new defect edges vs the original)
            n = gl.clip_defect_edges(c, ed)
            if n:
                mesh[c] = {"edges": int(n), "where": self.spot_words(gl.last_defect_mask)}
        return {"path": str(out), "size": im.size, "mesh": mesh}
