#!/usr/bin/env python3
"""Haiku anim bench server: one persistent process that holds the unit, the edit stack, the GL context and the live viewer.

    python tools/haiku_anim_bench/bench_server.py [--unit h3_roc] [--port 8771] [--clip Unit_Idle]

Binds 127.0.0.1 only. Work dir: V:/olden_port_work/haiku_anim/<unit>/ (work.glb = a sha-checked copy of the source GLB;
stack.json = kept pose edits, kept mesh/rig ops, the pending change and focus, rewritten on every change so a restart resumes; sheets/; control.json).
  GET  /                  live viewer (viewer.html, three.js)
  GET  /work.glb          the working GLB copy (the viewer applies the edit stack to it client-side)
  GET  /api/state         focus, edit stack (viewer form), tallies, driver status, clip timing
  GET  /api/sheet.jpg     the latest contact sheet (what Haiku saw)
  GET  /api/def/<clip>.png  the clip's DEF frames as one strip (192 px tiles, the sprite box)
  POST /api/apply         {"op": "edit"|"pose"|"repair"|"rig"|"keep"|"revert"|"move"|"look", ...} -> mesh report +
                          new sheet (see apply()); the mesh report never rejects an op
  POST /api/control       {"state": "run"|"pause"|"stop"} -> control.json (read by the driver)
  POST /api/driver        driver status (step, op, why, latency split) for the viewer
All GL work runs on one worker thread (the context's thread); HTTP threads queue to it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import queue
import re
import shutil
import statistics
import sys
import threading
import time
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anim_core import HW_ALL, MIN_HW, ROOT, SCRATCH, Unit, friendly, load_json  # noqa: E402
from anim_gl import BIG, FILM_N, AnimGL  # noqa: E402
from rig import DIRS, FIXES, RIG_DOS, SCULPT_MODES, RigEditor, mat_to_quat  # noqa: E402
from anim_gl import VIEW_MAX, VIEW_MODES  # noqa: E402
from rig_glb import build_rig_glb  # noqa: E402
from funnel import TIERS, Funnel, item_tier  # noqa: E402
from r5_bench import R5Mode  # noqa: E402

DEFAULT_HW = 2.0


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


class Bench:
    def __init__(self, unit: str, src: Path, clip: str):
        self.dir = SCRATCH / unit
        (self.dir / "sheets").mkdir(parents=True, exist_ok=True)
        self.work = self.dir / "work.glb"
        src_sha = sha256(src)
        if not self.work.is_file() or sha256(self.work) != src_sha:
            shutil.copyfile(src, self.work)
        if sha256(self.work) != src_sha:
            raise SystemExit("work.glb copy does not hash to the source GLB")
        self.src, self.src_sha = src, src_sha
        self.stack_path = self.dir / "stack.json"
        self.control_path = self.dir / "control.json"
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.driver = {}
        self.driver_hist = []
        self.sheet_jpeg = b""
        self.sheet_id = 0
        self.defect = {"open": False}
        self.rig_key = ""
        self.rig_glb = (None, b"")
        self.ready = threading.Event()
        self.unit_id, self.clip0 = unit, clip
        self.phase0 = "fix"
        self.total_steps = 300
        self.funnel = Funnel(self)
        self.r5 = None                 # round 5 mode (r5_bench.R5Mode), set by /api/reset {"r5": run_dir}
        self.r5_dir = None
        threading.Thread(target=self._worker, daemon=True).start()
        self.ready.wait()
        if self.init_error:
            raise SystemExit(self.init_error)

    # ------------------------------------------------------------ GL worker
    def _worker(self):
        self.init_error = None
        try:
            t0 = time.perf_counter()
            self.u = Unit(self.unit_id, self.work)
            self.gl = AnimGL(self.u)
            for c in self.u.clips:
                self.gl.setup_clip(c)                  # framing + per-edge thresholds from the pristine rig
            self.rig = RigEditor(self.u)
            self._words_setup()
            self.trial = None
            st = load_json(self.stack_path, None)
            if not st or st.get("glbSha256") != self.src_sha:
                st = {"schema": SCHEMA, "unit": self.unit_id, "glbSha256": self.src_sha, "source": str(self.src),
                      "kept": [], "mops": [], "pending": None, "nextId": 1, "focus": {"clip": self.clip0, "frame": 0},
                      "tally": {}, "defects": {}}
            st = upgrade_stack(st)
            self.st = st
            self._apply_rig()
            self.load_ms = (time.perf_counter() - t0) * 1000
            self._render()
        except Exception as e:  # noqa: BLE001
            self.init_error = f"bench init failed: {type(e).__name__}: {e}"
        self.ready.set()
        while True:
            item = self.q.get()
            if item is None:
                return
            fn, fut = item
            try:
                fut.set_result(fn())
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)

    def close(self):
        """Release the GL context on its own thread and end the worker (unit switch: one context at a time)."""
        try:
            self.call(lambda: self.gl.ctx.release())
        finally:
            self.q.put(None)

    def call(self, fn):
        fut = Future()
        self.q.put((fn, fut))
        return fut.result()

    # ------------------------------------------------------------ state
    def edits(self, with_pending=True):
        p = self.st["pending"] if with_pending else None
        return list(self.st["kept"]) + (list(p["parts"]) if p else [])

    def mops(self, with_pending=True):
        p = self.st["pending"] if with_pending else None
        return list(self.st["mops"]) + (list(p.get("mops", [])) if p else [])

    def _apply_rig(self):
        """Replay the effective mesh/rig ops if they changed (pristine snapshot + replay), then re-upload."""
        ops = self.mops()
        key = json.dumps(ops, sort_keys=True)
        if key == self.rig_key:
            return
        self.rig.apply(ops)
        self.gl.upload_rig()
        self.rig_key = key

    def save(self):
        tmp = self.stack_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, indent=1), encoding="utf-8")
        tmp.replace(self.stack_path)

    def film(self, clip):
        n = self.u.clips[clip]["n"]
        return list(range(n)) if n <= FILM_N else sorted({int(round(x)) for x in np.linspace(0, n - 1, FILM_N)})

    def _render(self) -> dict:
        f = self.st["focus"]
        clip = f["clip"]
        r = (self.gl.sheet_compact(clip, f["frame"], self.edits()) if SHEET == "compact" else
             self.gl.sheet(clip, f["frame"], self.film(clip), self.edits()))
        self.sheet_id += 1
        self.sheet_jpeg = r["jpeg"]
        (self.dir / "sheets" / "latest.jpg").write_bytes(r["jpeg"])
        d = r.get("defect") or {"open": False}
        d["clip"] = clip
        self.defect = d
        self.st.setdefault("defects", {})
        if d["open"]:
            self.st["defects"][clip] = self.defect_words(d)
        else:
            self.st["defects"].pop(clip, None)
        return r

    # ------------------------------------------------------------ the mesh report in words (no numbers)
    def spot_bones(self, d) -> list[str]:
        s = self.u.scene
        w = {}
        for v in d["verts"]:
            for j, x in zip(s.J[v], s.W[v]):
                w[int(j)] = w.get(int(j), 0.0) + float(x)
        top = sorted(w.items(), key=lambda t: -t[1])
        return [self.u.jnames[j] for j, x in top[:2] if x > 0.2] or [self.u.jnames[top[0][0]]]

    def defect_words(self, d) -> str:
        if not d.get("open"):
            return "clean"
        bones = self.spot_bones(d)
        n = np.asarray(d["restNormal"], float)
        n = n / max(np.linalg.norm(n), 1e-9)
        k = int(np.argmax(np.abs(n)))
        side = {(1, -1): "underside", (1, 1): "top", (2, 1): "front", (2, -1): "back",
                (0, 1): "outer left side", (0, -1): "outer right side"}[(k, 1 if n[k] > 0 else -1)]
        where = friendly(bones[0]) + (f" where it meets the {friendly(bones[1])}" if len(bones) > 1 else "")
        ext = "a small spot" if d["edges"] < 8 else ("a patch" if d["edges"] < 40 else "a wide area")
        sev = "torn" if d["severity"] >= 1.4 else "stretched"
        c = self.u.clips[d["clip"]]
        t = float(c["grid"][d["gridKey"]])
        fr = (t - c["start"]) / c["step"]
        fl = f"f{int(round(fr))}" if abs(fr - round(fr)) < 0.25 and round(fr) < c["n"] else "the loop transition"
        return f"{ext} {sev} on the {where}, {side} (bones {', '.join(bones)}), worst at {fl}"

    # ------------------------------------------------------------ resolve / build
    def _resolve_pending(self, how: str):
        p = self.st["pending"]
        if not p:
            return None
        t = self.st["tally"]
        if how == "revert":
            t["reverted"] += 1
            p["fate"] = "reverted"
            self.st["pending"] = None
            if p.get("mops"):
                self._apply_rig()
                self.mops_changed = True
        else:
            t["kept"] += 1
            p["fate"] = "kept"
            if self.defect.get("open"):
                t["keptWhileFlagged"] += 1
                p["keptWhileFlagged"] = self.defect_words(self.defect)
            for e in p["parts"]:
                self.st["kept"].append(dict(e, id=p["id"], why=p.get("why", ""), item=p.get("item", "")))
            for m in p.get("mops", []):
                self.st["mops"].append(dict(m, id=p["id"], why=p.get("why", "")))
            self.st["pending"] = None
            if p["parts"]:
                self._collapse()
        return p["fate"]

    def _collapse(self):
        """Net stack: the kept pose changes become ONE net offset per joint (exact on every key; ids stay per joint)."""
        st = self.st
        ids = {(e["clip"], e["bone"], "tr" if e["kind"] == "nettr" else "rot"): e["id"]
               for e in st["kept"] if e["kind"] in ("net", "nettr")}

        def new_id():
            st["nextId"] += 1
            return st["nextId"] - 1
        st["kept"] = self.u.net_collapse(st["kept"], ids, new_id)

    def _parts(self, clip, op, frame, hw):
        """Pose parts for an edit / pose op (each part's axis frozen on top of the parts before it)."""
        raw = op.get("parts") if op.get("op") == "pose" else [op]
        if not isinstance(raw, list) or not raw:
            raise ValueError("pose needs \"parts\": a list of {bone, axis, deg} (or {bone: Hips, tr})")
        if len(raw) > MAX_PARTS:
            raise ValueError(f"at most {MAX_PARTS} parts per pose")
        base = self.edits(False)
        parts = []
        for r in raw:
            e = self.u.make_edit(clip, str(r.get("bone")), frame, hw, base + parts, axis=r.get("axis"),
                                 deg=float(r.get("deg", 0) or 0), tr=r.get("tr"))
            parts.append(e)
            if (op.get("mirror") or r.get("mirror")) and e["kind"] == "rot":
                mb = mirror_bone(e["bone"])
                if mb and mb in self.u.jnames:
                    sgn = 1.0 if e["axis"] == "pitch" else -1.0      # mirror across the body's X plane
                    m = self.u.make_edit(clip, mb, frame, hw, base + parts, axis=e["axis"], deg=sgn * e["deg"])
                    m["mirrorOf"] = e["bone"]
                    parts.append(m)
        return parts

    def _cap(self, clip, parts):
        """Scale the new parts down until the composite offsets stay inside the lane's table limits."""
        before = set(self.u.cap_violations(clip, self.edits(False)))
        for k in (1.0, 0.5, 0.25):
            sc = [scale_edit(e, k) for e in parts]
            bad = [b for b in self.u.cap_violations(clip, self.edits(False) + sc) if b not in before]
            if not bad:
                return sc, (None if k == 1.0 else f"scaled to {int(k * 100)}% to stay inside the limits")
        raise ValueError("refused: " + "; ".join(bad) + " (undo some of it with an opposite edit first)")

    def _mops(self, op) -> list[dict]:
        """A repair / rig op -> frozen mop records (spot coordinates resolved now, so a replay is deterministic)."""
        u = self.u
        H = u.H
        d = self.defect if self.defect.get("open") and self.defect.get("clip") == self.st["focus"]["clip"] else None
        size = {"small": 0.04, "medium": 0.08, "large": 0.15}.get(str(op.get("size", "medium")), 0.08) * H

        def centre():
            if op.get("at"):
                b = str(op["at"])
                if b not in u.jnames:
                    raise ValueError(f"unknown bone {b!r} for \"at\"")
                return np.linalg.inv(u.scene.ibm[u.jnames.index(b)])[:3, 3].tolist()
            if d is None:
                raise ValueError("there is no red spot open on this clip: give \"at\": a bone to work near")
            return d["rest"]
        if op["op"] == "repair":
            fix = op.get("fix")
            if fix == "robust":
                return self._robust_mops()
            if fix in ("sculpt", "rebind", "paint", "corrective"):
                return [self._region_mop(op, fix)]
            if fix not in FIXES:
                raise ValueError(f"repair fix must be one of {list(FIXES)}")
            sb = self.spot_bones(d) if d else []
            if fix == "smooth":
                bones = op.get("bones") or sb
                if len(bones) < 1:
                    raise ValueError("smooth needs \"bones\" (the two bones on each side of the seam)")
                return [{"fix": "smooth", "bones": [str(b) for b in bones][:3], "ring": int(op.get("ring", 2)),
                         "center": centre(), "radius": size * 1.5}]
            if fix == "blend":
                fr = op.get("from") or (sb[0] if sb else None)
                to = op.get("to") or (sb[1] if len(sb) > 1 else None)
                if not fr or not to:
                    raise ValueError("blend needs \"from\" and \"to\" bones")
                return [{"fix": "blend", "from": str(fr), "to": str(to), "amount": float(op.get("amount", 0.5)),
                         "center": centre(), "radius": size}]
            if fix == "relax":
                return [{"fix": "relax", "center": centre(), "radius": size * 1.5,
                         "strength": float(op.get("strength", 0.5))}]
            bones = op.get("bones") or sb
            if not bones:
                raise ValueError("nocs needs \"bones\"")
            return [{"fix": "nocs", "bones": [str(b) for b in bones][:2]}]
        do = op.get("do")
        if do not in RIG_DOS:
            raise ValueError(f"rig do must be one of {list(RIG_DOS)}")
        if do == "split":
            m = {"do": "split", "bone": str(op.get("bone")), "at": float(op.get("at", 0.5)), "name": op.get("name")}
            if op.get("toward"):
                m["toward"] = str(op["toward"])
        elif do == "add":
            m = {"do": "add", "parent": str(op.get("parent") or op.get("bone")), "toward": str(op.get("toward", "back")),
                 "size": float(op.get("size", 0.3)) if not isinstance(op.get("size"), str) else 0.3, "name": op.get("name")}
        elif do == "pivot":
            mv = np.asarray(op.get("move", [0, 0, 0]), float)[:3]
            n = np.linalg.norm(mv)
            if n > MAX_PIVOT_H:
                mv *= MAX_PIVOT_H / n
            m = {"do": "pivot", "bone": str(op.get("bone")), "move": (mv * H).tolist()}
        else:
            m = {"do": "reparent", "bone": str(op.get("bone")), "parent": str(op.get("parent"))}
        out = [m]
        if op.get("mirror"):
            mm = mirror_mop(m)
            if mm is None:
                raise ValueError("mirror: no mirrored bone for that op")
            out.append(mm)
        return out

    # ------------------------------------------------------------ round 3: points, regions, region mesh tools
    def _point(self, op, default_bone=None) -> list:
        """A rest-space point from words: "at" a joint (its pivot), "toward" a direction (the outermost skin of that
        joint in that direction: back|front|up|down|left|right), "along" 0..1 toward its child joint, "offset"
        [dx,dy,dz] in body heights. Without "at": the open red spot, else default_bone."""
        u, s = self.u, self.u.scene
        b = op.get("at") or None
        if b is None and default_bone is None:
            d = self.defect if self.defect.get("open") else None
            if d is None:
                raise ValueError("give \"at\": a joint (there is no red spot open to work at)")
            p = np.asarray(d["rest"], float)
        else:
            b = str(b or default_bone)
            if b not in u.jnames:
                raise ValueError(f"unknown joint {b!r} for \"at\"")
            j = u.jnames.index(b)
            p = np.linalg.inv(s.ibm[j])[:3, 3].copy()
            if op.get("along") is not None:
                node = u.names.index(b)
                kids = [c for c in s.nodes[node].get("children", []) if c in s.joints]
                if kids:
                    q = np.linalg.inv(s.ibm[s.joints.index(kids[0])])[:3, 3]
                    p = p + float(np.clip(float(op["along"]), 0, 1.5)) * (q - p)
            tw = op.get("toward")
            if tw:
                if tw not in DIRS:
                    raise ValueError(f"toward must be one of {sorted(DIRS)}")
                D = self.rig.dense()
                m = np.argmax(D, 1) == j
                if m.sum() < 3:
                    m = D[:, j] > 0.2
                if m.sum() >= 3:
                    pr = s.P[m] @ np.asarray(DIRS[tw])
                    k = pr >= np.quantile(pr, 0.95)
                    p = s.P[m][k].mean(0)
        off = op.get("offset")
        if off is not None:
            p = p + np.asarray(off, float)[:3] * u.H
        return p.tolist()

    def _radius(self, op) -> float:
        if op.get("radius") is not None:
            return float(np.clip(float(op["radius"]), 0.02, 0.8)) * self.u.H
        return {"small": 0.05, "medium": 0.1, "large": 0.2}.get(str(op.get("size", "medium")), 0.1) * self.u.H

    def _region_mop(self, op, fix) -> dict:
        u = self.u
        if fix in ("rebind", "paint", "corrective"):
            b = str(op.get("bone") or "")
            if b not in u.jnames:
                raise ValueError(f"{fix} needs \"bone\": a joint ({'the one that will carry that skin' if fix != 'corrective' else 'whose bend switches the shape on'})")
        m = {"fix": fix, "center": self._point(op, op.get("bone") if fix in ("rebind", "paint") else None),
             "radius": self._radius(op)}
        if fix in ("sculpt", "corrective"):
            mode = str(op.get("mode", "smooth"))
            if mode not in SCULPT_MODES:
                raise ValueError(f"mode must be one of {list(SCULPT_MODES)}")
            m["mode"] = mode
            m["amount"] = float(op.get("amount", 0.5 if mode in ("smooth", "flatten") else 0.03))
            dv = op.get("dir", "up")
            m["dir"] = list(DIRS[dv]) if isinstance(dv, str) and dv in DIRS else [float(x) for x in list(dv)[:3]]
        if fix in ("rebind", "paint", "corrective"):
            m["bone"] = str(op["bone"])
        if fix == "paint":
            m["amount"] = float(op.get("amount", 0.5))
        if fix == "corrective":
            clip = op.get("clip") or self.st["focus"]["clip"]
            if clip not in u.clips:
                raise ValueError(f"unknown clip {clip}")
            fr = float(np.clip(float(op.get("frame", self.st["focus"]["frame"])), 0, u.clips[clip]["n"] - 1))
            G, _, _ = u.pose(clip, [u.frame_time(clip, fr)], self.edits(False))
            node = u.names.index(m["bone"])
            pn = u.scene.parent.get(node)
            L = np.linalg.inv(G[0, pn]) @ G[0, node] if pn is not None and pn >= 0 else G[0, node]
            R = L[:3, :3] / np.linalg.norm(L[:3, :3], axis=0, keepdims=True)
            m.update(qref=mat_to_quat(R).tolist(), clip=clip, frame=fr)
        return m

    def _view(self, op: dict) -> dict:
        """Free camera look (does not touch the pending change or the focus)."""
        t0 = time.perf_counter()
        u, st = self.u, self.st
        res = {"op": "view", "resolved": None, "error": None}
        try:
            clip = op.get("clip") or st["focus"]["clip"]
            if clip not in u.clips:
                raise ValueError(f"unknown clip {clip!r}: one of {list(u.clips)}")
            n = u.clips[clip]["n"]
            fr = op.get("frames")
            if isinstance(fr, list) and fr:
                a, b = int(np.clip(int(fr[0]), 0, n - 1)), int(np.clip(int(fr[-1]), 0, n - 1))
                frames = list(range(min(a, b), max(a, b) + 1))
                if len(frames) > VIEW_MAX:
                    frames = sorted({int(round(x)) for x in np.linspace(frames[0], frames[-1], VIEW_MAX)})
            else:
                frames = [int(np.clip(int(round(float(op.get("frame", st["focus"]["frame"] if st["focus"]["clip"] == clip else 0)))), 0, n - 1))]
            at = op.get("at") or "body"
            if at != "body" and at not in u.jnames:
                raise ValueError(f"unknown joint {at!r} for \"at\" (or \"body\")")
            mode = str(op.get("mode", "shaded"))
            if mode not in VIEW_MODES:
                raise ValueError(f"mode must be one of {list(VIEW_MODES)}")
            dist = float(op.get("dist", 1.3 if at == "body" else 0.5))
            yaw, pitch = float(op.get("yaw", 30)), float(op.get("pitch", 15))
            r = self.gl.view(clip, frames, yaw, pitch, dist, None if at == "body" else at, mode, self.edits())
        except (ValueError, TypeError) as ex:
            res["error"] = str(ex)
            res["mesh"] = self.defect_words(self.defect)
            res["state"] = self.state_line()
            return res
        self.sheet_jpeg = r["jpeg"]
        self.sheet_id += 1
        vd = self.dir / "views"
        vd.mkdir(exist_ok=True)
        k = st.setdefault("viewCount", 0) + 1
        st["viewCount"] = k
        (vd / f"{k % 24}.jpg").write_bytes(r["jpeg"])
        (self.dir / "sheets" / "latest.jpg").write_bytes(r["jpeg"])
        self.last_view = {"k": k, "clip": clip, "frames": frames, "yaw": yaw, "pitch": pitch, "dist": dist, "at": at,
                          "mode": mode, "why": str(op.get("why", ""))[:120]}
        self.views_hist = (getattr(self, "views_hist", []) + [self.last_view])[-12:]
        res["view"] = self.last_view
        if r.get("heat"):
            res["note"] = "heat: " + r["heat"]
        res["mesh"] = self.defect_words(self.defect)
        res["ms"] = dict(r["ms"], total=round((time.perf_counter() - t0) * 1000, 1))
        res["sheetId"] = self.sheet_id
        res["state"] = self.state_line()
        return res

    def _note(self, op: dict) -> dict:
        """The survey checklist, written by Haiku: add items (clip, frame, region, issue) or set an item's status."""
        st = self.st
        cl = st.setdefault("checklist", [])
        res = {"op": "note", "resolved": None, "error": None}
        before = {x["id"]: x["status"] for x in cl}
        if op.get("work") is not None and op.get("id") is None and not op.get("items") and not op.get("issue"):
            m = self.funnel.note_hook(op, before) if st.get("phase") == "fix" else None
            res["note"] = m or f"#{op['work']} is not an open item of this tier"
            self.save()
            res["mesh"] = self.defect_words(self.defect)
            res["state"] = self.state_line()
            res["sheetId"] = self.sheet_id
            return res
        items = op.get("items") if isinstance(op.get("items"), list) else None
        try:
            if op.get("id") is not None and not items:
                it = next((x for x in cl if x["id"] == int(op["id"])), None)
                if it is None:
                    raise ValueError(f"no checklist item #{op['id']}")
                stt = str(op.get("status", it["status"]))
                if stt not in ("open", "fixed", "dropped"):
                    raise ValueError("status must be open|fixed|dropped")
                if op.get("sev"):
                    it["sev"] = self._sev(op["sev"])
                if stt == "open" and it["status"] != "open":
                    it.pop("parked", None)
                it["status"] = stt
                if op.get("issue"):
                    it["issue"] = str(op["issue"])[:100]
                res["note"] = f"item #{it['id']} is {stt}"
            else:
                added = []
                for x in items or [op]:
                    if not isinstance(x, dict) or not x.get("issue"):
                        raise ValueError("a note needs \"issue\" (and clip, frame, region)")
                    c = x.get("clip") or st["focus"]["clip"]
                    if c not in self.u.clips:
                        raise ValueError(f"unknown clip {c!r}")
                    sev = self._sev(x.get("sev"))
                    st["checkNext"] = st.get("checkNext", 0) + 1
                    cl.append({"id": st["checkNext"], "clip": c, "frame": x.get("frame"), "sev": sev,
                               "region": str(x.get("region", ""))[:40], "issue": str(x["issue"])[:100], "status": "open"})
                    added.append(st["checkNext"])
                res["note"] = "added checklist item " + ", ".join(f"#{i}" for i in added)
        except (ValueError, TypeError) as ex:
            res["error"] = str(ex)
        if not res["error"] and st.get("phase") == "fix":
            m = self.funnel.note_hook(op, before)
            if m:
                res["note"] = (res.get("note") or "") + "; " + m
        self.save()
        res["mesh"] = self.defect_words(self.defect)
        res["state"] = self.state_line()
        res["sheetId"] = self.sheet_id
        return res

    @staticmethod
    def _sev(v) -> str:
        v = str(v or "").strip().upper()
        v = {"MED": "MEDIUM", "MID": "MEDIUM", "B": "BIG", "M": "MEDIUM", "S": "SMALL", "LARGE": "BIG"}.get(v, v)
        if v not in TIERS:
            raise ValueError('each item needs "sev": BIG | MEDIUM | SMALL (your own rating)')
        return v

    def checklist_line(self) -> str:
        cl = self.st.get("checklist") or []
        if not cl:
            return "empty"
        f = self.st.get("funnel")
        tier = f["tier"] if f else None
        op = [x for x in cl if x["status"] == "open"]
        done = [x for x in cl if x["status"] != "open"]
        full = [x for x in op if tier in (None, "DONE") or item_tier(x) == tier]
        rest = [x for x in op if x not in full]
        t = "; ".join(f"#{x['id']} {x.get('sev', '?')} {x['clip'].replace('Unit_', '')}"
                      + (f" f{x['frame']}" if x.get("frame") is not None else "") + f" {x['region']}: {x['issue']}"
                      for x in full)
        if rest:
            t += ("; " if t else "") + "later tiers: " + " ".join(f"#{x['id']}({item_tier(x)})" for x in rest)
        if done:
            t += ("; " if t else "") + "done: " + " ".join(
                f"#{x['id']}" + ("" if x["status"] == "fixed" else f"({x['status']})") for x in done)
        return t

    def apply(self, op: dict) -> dict:
        """One Haiku op (see haiku_driver.SYSTEM). Ops that create a pending change first resolve the current one via
        `prev`. The mesh report never rejects anything: it is rendered (red tint + worst-spot close-up) and worded."""
        t0 = time.perf_counter()
        kind = op.get("op")
        res = {"op": kind, "resolved": None, "error": None}
        st = self.st
        t = st["tally"]
        if self.r5 is not None:
            r5 = self.r5.apply(op)
            if r5 is not None:
                return r5
            kind = op.get("op")
        if kind == "view":
            return self._view(op)
        if kind == "note":
            return self._note(op)
        if kind == "phase":
            to = str(op.get("to", "fix"))
            fdone = (st.get("funnel") or {}).get("tier") == "DONE"
            bad = None
            if to == "fix":
                if st.get("phase") == "fix":
                    bad = "already fixing"
            elif to == "survey":
                if not fdone or st.get("phase") != "fix":
                    bad = "a re-survey round starts only after every tier is done"
            elif to == "done":
                if st.get("phase") != "survey" or not st.get("funnel"):
                    bad = "\"done\" ends the run from a re-survey round"
            else:
                bad = "phase: \"to\" must be fix | survey | done"
            if bad:
                return {"op": "phase", "error": bad, "resolved": None, "mesh": self.defect_words(self.defect),
                        "state": self.state_line(), "sheetId": self.sheet_id}
            self._resolve_pending(op.get("prev", "keep"))
            if to == "fix" and self.r5 is not None:
                st["phase"] = "fix"
                note = "phase 2 (fixing) started: work the ITEMS list"
            elif to == "fix":
                st["phase"] = "fix"
                self.funnel.start(self.total_steps)
                note = "phase 2 (fixing) started; " + st["funnel"]["log"][-1]["text"]
            elif to == "survey":
                st["phase"] = "survey"
                st["funnel"]["finished"] = False
                note = ("RE-SURVEY round: look at every clip from any angles and note (with sev) what is still wrong; "
                        'then {"op":"phase","to":"fix"} for a new funnel round, or {"op":"phase","to":"done"} if it is all good')
            else:
                st["phase"] = "fix"
                st["funnel"]["finished"] = True
                note = "run ended by you"
            self.save()
            return {"op": "phase", "error": None, "resolved": None, "note": note,
                    "mesh": self.defect_words(self.defect), "state": self.state_line(), "sheetId": self.sheet_id}
        if kind == "tier":
            if st.get("phase") != "fix":
                return {"op": "tier", "error": "tier works in phase 2 only", "resolved": None,
                        "mesh": self.defect_words(self.defect), "state": self.state_line(), "sheetId": self.sheet_id}
            r = self.funnel.tier_op(op)
            self.save()
            return {"op": "tier", "error": r.get("error"), "resolved": None, "note": r.get("note"),
                    "mesh": self.defect_words(self.defect), "state": self.state_line(), "sheetId": self.sheet_id}
        if st.get("phase") == "survey" and kind not in ("look", "keep", "revert"):
            return {"op": kind, "error": "phase 1 is the survey: view, look and note only; end it with {\"op\":\"phase\",\"to\":\"fix\"}",
                    "resolved": None, "mesh": self.defect_words(self.defect), "state": self.state_line(), "sheetId": self.sheet_id}
        if kind in ("edit", "pose", "try", "repair", "rig", "undo") and op.get("clip"):
            c2 = op["clip"]
            if c2 not in self.u.clips:
                return {"op": kind, "error": f"unknown clip {c2!r}: one of {list(self.u.clips)}", "resolved": None,
                        "mesh": self.defect_words(self.defect), "state": self.state_line(), "sheetId": self.sheet_id}
            if c2 != st["focus"]["clip"]:
                self._resolve_pending(op.get("prev", "keep"))
                op = dict(op, prev="keep")
                st["focus"] = {"clip": c2, "frame": int(np.clip(int(round(float(op.get("frame", 0)))), 0, self.u.clips[c2]["n"] - 1))}
        if kind == "look":
            kind = "move"
        if kind == "pick":
            return self._pick(op)
        if kind == "try":
            return self._try(op)
        self.trial = None
        if kind in ("edit", "pose", "repair", "rig", "move"):
            res["resolved"] = self._resolve_pending(op.get("prev", "keep"))
        elif kind in ("keep", "revert"):
            res["resolved"] = self._resolve_pending(kind)
        elif kind == "undo":
            res["resolved"] = self._resolve_pending(op.get("prev", "keep"))
        else:
            res["error"] = f"unknown op {kind!r}"
        clip = st["focus"]["clip"]
        if kind == "move":
            c2 = op.get("clip") or clip
            if c2 not in self.u.clips:
                res["error"] = f"unknown clip {c2}"
            else:
                n = self.u.clips[c2]["n"]
                st["focus"] = {"clip": c2, "frame": int(np.clip(int(round(float(op.get("frame", st["focus"]["frame"])))), 0, n - 1))}
        elif kind in ("edit", "pose"):
            try:
                frame = float(np.clip(float(op.get("frame", st["focus"]["frame"])), 0, self.u.clips[clip]["n"] - 1))
                hw = HW_ALL if str(op.get("hw")).lower() == "all" else float(op.get("hw", DEFAULT_HW))
                parts = self._parts(clip, op, frame, hw)
                note = None                      # 2026-10-07: no cap scaling; the export reports lane limits
                if hw < MIN_HW - 1e-6:
                    note = (note + "; " if note else "") + f"hw raised to the minimum {MIN_HW:g}"
                if note:
                    res["note"] = note
                p = {"id": st["nextId"], "type": "pose", "parts": parts, "why": str(op.get("why", ""))[:120],
                     "item": str(op.get("item", ""))[:40]}
                st["nextId"] += 1
                st["pending"] = p
                t["edits"] += 1
                st["focus"]["frame"] = int(round(frame))
                res["edit"] = {"id": p["id"], "parts": [part_summary(e) for e in parts]}
            except (ValueError, TypeError) as ex:
                res["error"] = str(ex)
                t["refused"] += 1
        elif kind == "undo":
            try:
                uid = int(op.get("id"))
            except (TypeError, ValueError):
                uid = None
            ne, nm = sum(1 for e in st["kept"] if e.get("id") == uid), sum(1 for m in st["mops"] if m.get("id") == uid)
            if not ne and not nm:
                res["error"] = f"undo: no kept change #{op.get('id')}"
                t["refused"] += 1
            else:
                st["kept"] = [e for e in st["kept"] if e.get("id") != uid]
                if nm:
                    st["mops"] = [m for m in st["mops"] if m.get("id") != uid]
                    self._apply_rig()
                    self.mops_changed = True
                t["undone"] += 1
                res["note"] = f"undid kept change #{uid} ({ne} pose part(s), {nm} mesh/rig op(s))"
        elif kind in ("repair", "rig"):
            try:
                if self.defect.get("open"):
                    self.repairs_open = getattr(self, "repairs_open", 0) + 1
                mops = self._mops(op)
                p = {"id": st["nextId"], "type": kind, "parts": [], "mops": mops, "why": str(op.get("why", ""))[:120],
                     "item": str(op.get("item", ""))[:40]}
                prev_pending = st["pending"]
                st["pending"] = p
                try:
                    self._apply_rig()
                except Exception as ex:  # noqa: BLE001  (any replay failure: restore the previous rig)
                    st["pending"] = prev_pending
                    self.rig_key = ""
                    self._apply_rig()
                    raise ValueError(str(ex)) from None
                st["nextId"] += 1
                t["repairs" if kind == "repair" else "rigOps"] += 1
                rep = self.rig.reports[-len(mops):]
                res["mop"] = {"id": p["id"], "ops": mops, "report": rep}
                if op.get("fix") == "robust":
                    res["note"] = ("robust: joints that tore at a 35 deg test bend, seam smoothing kept where it helped: "
                                   + ", ".join(self.robust_report[:12]))
                new = [r.get("new") for r in rep if r.get("new")]
                if new:
                    res["note"] = "new joint " + ", ".join(new) + " (poseable now; it is in the bone list)"
            except (ValueError, TypeError) as ex:
                res["error"] = str(ex)
                t["refused"] += 1
        t1 = time.perf_counter()
        if kind in ("repair", "rig") or getattr(self, "mops_changed", False) or (kind == "move" and self.mops()):
            self._other_clips()
        r = self._render()
        if kind == "move" and op.get("view") and not res.get("error"):
            try:
                z = self.gl.zoom(st["focus"]["clip"], st["focus"]["frame"], str(op["view"]), self.edits())
                self.sheet_jpeg = z["jpeg"]
                self.sheet_id += 1
                res["view"] = op["view"]
            except ValueError as ex:
                res["error"] = str(ex)
        if not self.defect.get("open"):
            self.repairs_open = 0
            self.cause = None
        elif getattr(self, "repairs_open", 0) >= 3 and kind in ("repair", "rig"):
            self.cause = self._find_cause()      # only after a repair (it re-renders up to 20 stacks); kept otherwise
        self.save()
        res["mesh"] = self.defect_words(self.defect)
        res["stretch"] = r.get("stretch")
        res["ms"] = {"apply": round((t1 - t0) * 1000, 2), **r["ms"], "total": round((time.perf_counter() - t0) * 1000, 2)}
        res["sheetId"] = self.sheet_id
        res["state"] = self.state_line()
        return res

    def apply_turn(self, op: dict) -> dict:
        """One HTTP turn: the op, then the funnel's bookkeeping (tier budget, loop breaking)."""
        res = self.apply(op)
        if self.r5 is not None:
            if "items" not in res:
                res = self.r5.after_base(op, res)
            return res
        try:
            m = self.funnel.after_turn(op, res)
        except Exception as ex:  # noqa: BLE001  (bookkeeping must never kill a turn)
            m = f"(funnel error {type(ex).__name__}: {ex})"
        if m:
            res["note"] = ((res.get("note") + "; ") if res.get("note") else "") + m
            self.save()
            res["state"] = self.state_line()
        res["funnel"] = self.funnel.public()
        return res

    def _find_cause(self):
        """After 3 repairs on an open defect: which KEPT pose group, taken out alone, clears most of the red on the
        focus clip (GPU per-edge rule, ~10 ms per candidate; cached per stack state)."""
        clip = self.st["focus"]["clip"]
        key = json.dumps([[e.get("id") for e in self.edits()], self.rig_key])
        if getattr(self, "_cause_key", None) == key:
            return self.cause
        self._cause_key = key
        ed = self.edits()
        n0 = self.gl.clip_defect_edges(clip, ed)
        if not n0:
            return None
        ids = []
        for e in reversed(self.st["kept"]):
            if e["clip"] == clip and e.get("id") not in ids:
                ids.append(e.get("id"))
        best = None
        for i in ids[:20]:
            n = self.gl.clip_defect_edges(clip, [e for e in ed if e.get("id") != i])
            if best is None or n < best[1]:
                best = (i, n)
        if best is None or best[1] > 0.5 * n0:
            return None
        parts = [e for e in self.st["kept"] if e.get("id") == best[0]]
        return {"id": best[0], "clears": best[1] == 0, "what": ", ".join(part_summary(e) for e in parts[:3]),
                "why": parts[0].get("why", "")[:60] if parts else ""}

    def cause_line(self) -> str:
        c = getattr(self, "cause", None)
        if not c or not self.defect.get("open") or not any(e.get("id") == c["id"] for e in self.st["kept"]):
            return ""
        return (f"; REPAIRS ARE NOT FIXING IT: the kept pose #{c['id']} ({c['what']}) caused this red"
                + ("" if c["clears"] else " (most of it)") + f"; undo it with {{\"op\":\"undo\",\"id\":{c['id']}}} or replace it with a gentler version")

    def _other_clips(self) -> None:
        """Mesh/rig ops change every clip: count new defect edges on the clips other than the focus one (GPU)."""
        self.mops_changed = False
        f = self.st["focus"]["clip"]
        ed = self.edits()
        out = {}
        for c in self.u.clips:
            if c != f:
                n = self.gl.clip_defect_edges(c, ed)
                if n:
                    out[c] = n
        self.other_red = out

    def other_line(self) -> str:
        o = getattr(self, "other_red", {})
        if not o:
            return ""
        return "; OTHER CLIPS now red (weights/rig touch every clip): " + ", ".join(
            f"{c.replace('Unit_', '')} ({'a small spot' if n < 8 else 'a patch' if n < 40 else 'a wide area'})"
            for c, n in o.items())

    def pending_line(self) -> str:
        p = self.st["pending"]
        if not p:
            return "no pending change"
        if p.get("mops"):
            return f"pending #{p['id']} {p['type']}: " + "; ".join(mop_summary(m) for m in p["mops"])
        return f"pending #{p['id']} " + ", ".join(part_summary(e) for e in p["parts"])

    def state_line(self) -> str:
        if self.r5 is not None:
            return self.r5.state_line()
        st = self.st
        f = st["focus"]
        kept = sum(1 for e in st["kept"] if e["clip"] == f["clip"])
        mesh = self.defect_words(self.defect) if self.defect.get("clip") == f["clip"] else "not measured"
        others = {}
        for e in st["kept"]:
            if e["clip"] != f["clip"]:
                others.setdefault(e["clip"].replace("Unit_", ""), set()).add(e["bone"])
        ph = st.get("phase", "fix")
        rs = (st.get("funnel") or {}).get("round", 0)
        return ((("RE-SURVEY (after funnel round %d). " % rs if rs else "PHASE 1 SURVEY. ") if ph == "survey" else "")
                + f"clip {f['clip']} f{f['frame']}/{self.u.clips[f['clip']]['n'] - 1}; {kept} kept edits, "
                f"{len(st['mops'])} kept mesh/rig ops; {self.pending_line()}; MESH: "
                + ("clean" if mesh == "clean" else f"OPEN DEFECT - {mesh} (red in the views, close-up row 2 right)")
                + self.cause_line() + self.other_line()
                + "\nOURS NOW " + self.ours_line(f["clip"], f["frame"], self.edits())
                + "\nNET POSE " + f["clip"].replace("Unit_", "") + ": " + self.net_line(f["clip"])
                + (("; other clips edited: " + ", ".join(f"{c} ({len(b)} joints)" for c, b in others.items())) if others else "")
                + "\nCHECKLIST: " + self.checklist_line()
                + (("\n" + self.funnel.line()) if st.get("funnel") else ""))

    # ------------------------------------------------------------ the net pose (our own changes, body-axis degrees)
    def net_line(self, clip: str) -> str:
        """Each kept joint's NET change as body-axis degrees (pitch/yaw/roll) per DEF frame, or one value when it is the
        same through the whole clip. Our own changes only (no DEF numbers, no targets)."""
        u = self.u
        nets = [e for e in self.st["kept"] if e["clip"] == clip]
        if not nets:
            return "none (the original animation)"
        c = u.clips[clip]
        grid = np.asarray(c["grid"], float)
        times = c["times"]
        G, _, _ = u.pose(clip, times, self.edits(False))
        idx = [int(np.argmin(np.abs(grid - t))) for t in times]
        out = []
        for e in nets:
            if e["bone"] not in u.names:
                continue
            node = u.names.index(e["bone"])
            if e["kind"] == "net":
                q = np.asarray(e["q"], float)[idx]
                q = q * np.where(q[:, 3:4] < 0, -1.0, 1.0)
                sn = np.linalg.norm(q[:, :3], axis=1)
                ang = 2 * np.arctan2(sn, q[:, 3])
                rv = q[:, :3] / np.maximum(sn, 1e-12)[:, None] * np.degrees(ang)[:, None]
                R = G[:, node, :3, :3] / np.linalg.norm(G[:, node, :3, :3], axis=1, keepdims=True)
                body = np.einsum("tij,tj->ti", R, rv)
                parts = []
                for k, ax in enumerate(("pitch", "yaw", "roll")):
                    v = body[:, k]
                    if np.abs(v).max() < 3:
                        continue
                    if v.max() - v.min() <= 6:
                        parts.append(f"{ax} {v.mean():+.0f} all")
                    else:
                        k = int(np.argmax(np.abs(v)))
                        parts.append(f"{ax} {v.min():+.0f}..{v.max():+.0f} (peak f{k})")
                if parts:
                    out.append(f"#{e['id']} {e['bone']} " + ", ".join(parts))
            elif e["kind"] == "nettr":
                d = np.asarray(e["d"], float)[idx]
                pn = u.scene.parent.get(node)
                Rp = G[:, pn, :3, :3] if pn is not None and pn >= 0 else np.broadcast_to(np.eye(3), (len(idx), 3, 3))
                w = np.einsum("tij,tj->ti", Rp, d) / u.H
                if np.abs(w).max() < 0.005:
                    continue
                if (w.max(0) - w.min(0)).max() <= 0.01:
                    out.append(f"#{e['id']} {e['bone']} moved {np.round(w.mean(0), 2).tolist()} H all")
                else:
                    k = int(np.argmax(np.linalg.norm(w, axis=1)))
                    out.append(f"#{e['id']} {e['bone']} moved up to {np.round(w[k], 2).tolist()} H (peak f{k})")
        return "; ".join(out) or "none (the original animation)"

    # ------------------------------------------------------------ OUR state in plain words (geometry, no numbers)
    def _words_setup(self):
        u, s = self.u, self.u.scene
        J = set(s.joints)
        kids = {}
        for n in s.joints:
            pn = s.parent.get(n)
            if pn in J:
                kids.setdefault(pn, []).append(n)

        def chain(n):
            best = [n]
            for k in kids.get(n, []):
                c = chain(k)
                if len(c) + 1 > len(best):
                    best = [n] + c
            return best
        nm = u.names
        hip = nm.index("Hips") if "Hips" in nm else s.joints[0]
        h = nm.index(u.head_bone)
        chest = h
        while s.parent.get(chest) in J and any(w in nm[chest].lower() for w in ("head", "neck")):
            chest = s.parent[chest]
        if chest == h and s.parent.get(h) in J:
            chest = s.parent[h]
        self.w_trunk = (hip, chest)
        limbs = {"leg": [], "arm": []}
        for n in s.joints:
            low = nm[n].lower()
            pn = s.parent.get(n)
            plow = nm[pn].lower() if pn is not None and pn >= 0 else ""
            if ("upleg" in low or "thigh" in low) and not ("upleg" in plow or "thigh" in plow):
                limbs["leg"].append(chain(n))
            elif (("arm" in low and "fore" not in low) or "wing" in low) and not ("arm" in plow or "wing" in plow):
                c = chain(n)
                if len(c) >= 2:
                    limbs["arm"].append(c)
        self.w_limbs = limbs
        self.w_armword = "wings" if any("wing" in nm[c[0]].lower() for c in limbs["arm"]) else "arms"

    @staticmethod
    def _dir(v) -> str:
        n = float(np.linalg.norm(v)) + 1e-12
        e = float(np.degrees(np.arcsin(np.clip(v[1] / n, -1, 1))))
        if e > 65:
            return "straight up"
        if e < -65:
            return "straight down"
        vert = ("steeply up" if e > 30 else "slightly up" if e > 12 else "steeply down" if e < -30
                else "slightly down" if e < -12 else "level")
        f, sd = v[2] / n, v[0] / n
        hz = ("to its left" if sd > 0 else "to its right") if (abs(sd) > abs(f) and abs(sd) > 0.4) else (
            "forward" if f > 0 else "back")
        return f"{vert} and {hz}" if vert != "level" else f"level, {hz}"

    def ours_words(self, clip, frame, edits) -> dict:
        u = self.u
        c = u.clips[clip]
        G, _, _ = u.pose(clip, c["times"], edits)
        P = G[:, :, :3, 3]
        fi = int(np.clip(int(round(frame)), 0, c["n"] - 1))
        out = {}
        hip, chest = self.w_trunk
        tv = P[:, chest] - P[:, hip]
        el = np.degrees(np.arctan2(tv[:, 1], np.linalg.norm(tv[:, [0, 2]], axis=1)))
        out["trunk"] = f"trunk (hips to chest) points {self._dir(tv[fi])}" + (
            ", rocking through the loop" if el.max() - el.min() > 15 else ", holding that through the loop")
        _, gd = u.gaze(G)
        out["gaze"] = f"head looks {self._dir(gd[fi])}"
        for kind, chains in self.w_limbs.items():
            ws = []
            for ch in chains:
                nm0 = u.names[ch[0]]
                side = "left" if ("Left" in nm0 or "L_" in nm0) else ("right" if ("Right" in nm0 or "R_" in nm0) else "")
                if kind == "leg":
                    m = min(2, len(ch) - 1)
                    tip = ch[m]
                    L = sum(float(np.linalg.norm(P[fi, ch[i + 1]] - P[fi, ch[i]])) for i in range(m)) + 1e-9
                    w = f"points {self._dir(P[fi, tip] - P[fi, ch[0]])}"
                    if len(ch) >= 3:
                        a, b = P[fi, ch[1]] - P[fi, ch[0]], P[fi, ch[2]] - P[fi, ch[1]]
                        cosb = a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
                        bend = float(np.degrees(np.arccos(np.clip(cosb, -1, 1))))
                        w += ", " + ("straight" if bend < 25 else "bent" if bend < 70 else "folded up")
                    sw = np.ptp(P[:, tip, 2] - P[:, ch[0], 2]) / L
                    w += ", " + ("barely swinging through the loop" if sw < 0.15 else "swinging a little" if sw < 0.45
                                 else "swinging front and back")
                else:
                    tip = ch[-1]
                    L = sum(float(np.linalg.norm(P[fi, ch[i + 1]] - P[fi, ch[i]])) for i in range(len(ch) - 1)) + 1e-9
                    w = f"tip {self._dir(P[fi, tip] - P[fi, ch[0]])}"
                    sw = np.ptp(P[:, tip, 1] - P[:, ch[0], 1]) / L
                    w += ", " + ("barely moving through the loop" if sw < 0.15 else "moving a little" if sw < 0.45
                                 else "sweeping up and down widely")
                ws.append((side, w))
            if not ws:
                continue
            label = "legs" if kind == "leg" else self.w_armword
            if len({w for _, w in ws}) == 1:
                out[kind] = f"{label} {ws[0][1]}"
            else:
                out[kind] = f"{label}: " + "; ".join(f"{sd} {w}".strip() for sd, w in ws)
        return out

    def ours_line(self, clip, frame, edits) -> str:
        try:
            w = self.ours_words(clip, frame, edits)
        except Exception as e:  # noqa: BLE001  (the words are an aid; they never break a step)
            return f"(words unavailable: {type(e).__name__})"
        return f"f{int(round(frame))}: " + "; ".join(w.values())

    # ------------------------------------------------------------ try A/B, pick, robust, reset
    def _try(self, op: dict) -> dict:
        t0 = time.perf_counter()
        st = self.st
        res = {"op": "try", "resolved": self._resolve_pending(op.get("prev", "keep")), "error": None}
        clip = st["focus"]["clip"]
        try:
            frame = float(np.clip(float(op.get("frame", st["focus"]["frame"])), 0, self.u.clips[clip]["n"] - 1))
            hw = HW_ALL if str(op.get("hw")).lower() == "all" else float(op.get("hw", DEFAULT_HW))
            a = dict(op, op="pose" if op.get("parts") else "edit")
            b = json.loads(json.dumps(a))
            for pt in (b.get("parts") if b["op"] == "pose" else [b]) or []:
                if isinstance(pt, dict):
                    if pt.get("deg") is not None:
                        pt["deg"] = -float(pt["deg"] or 0)
                    if pt.get("tr") is not None:
                        pt["tr"] = [-float(x) for x in pt["tr"]]
            base = self.edits(False)
            pa, pb = self._parts(clip, a, frame, hw), self._parts(clip, b, frame, hw)
        except (ValueError, TypeError) as ex:
            res["error"] = str(ex)
            st["tally"]["refused"] += 1
            self.save()
            res["mesh"] = self.defect_words(self.defect)
            res["state"] = self.state_line()
            return res
        st["focus"]["frame"] = int(round(frame))
        fi = st["focus"]["frame"]
        n0 = self.gl.clip_defect_edges(clip, base)
        na, nb = self.gl.clip_defect_edges(clip, base + pa), self.gl.clip_defect_edges(clip, base + pb)
        z = self.gl.try_sheet(clip, fi, base, pa, pb)
        self.sheet_jpeg = z["jpeg"]
        self.sheet_id += 1
        (self.dir / "sheets" / "latest.jpg").write_bytes(z["jpeg"])
        self.trial = {"A": {k: v for k, v in a.items() if k != "prev"}, "B": {k: v for k, v in b.items() if k != "prev"}}
        st["tally"]["tries"] = st["tally"].get("tries", 0) + 1
        now = self.ours_words(clip, fi, base)

        def diff(ed):
            w = self.ours_words(clip, fi, base + ed)
            d = [w[k] for k in w if w[k] != now.get(k)]
            return "; ".join(d) if d else "no change in the words"

        def mesh(n):
            if n <= n0:
                return "mesh clean"
            return "tears a small spot" if n - n0 < 8 else "tears a patch" if n - n0 < 40 else "tears a wide area"
        self.save()
        res["mesh"] = self.defect_words(self.defect)
        res["try"] = {"A": [part_summary(e) for e in pa], "B": [part_summary(e) for e in pb]}
        res["state"] = (f"TRY at f{fi}: the sheet shows DEF | NOW | A | B (rows: sprite cam, side, top). "
                        f"A = {', '.join(res['try']['A'])} -> {diff(pa)}; {mesh(na)}. "
                        f"B = {', '.join(res['try']['B'])} -> {diff(pb)}; {mesh(nb)}. "
                        'Reply {"op":"pick","which":"A"|"B"|"none","why":"..."}.\nOURS NOW '
                        + self.ours_line(clip, fi, base))
        res["ms"] = {"total": round((time.perf_counter() - t0) * 1000, 2)}
        res["sheetId"] = self.sheet_id
        return res

    def _pick(self, op: dict) -> dict:
        w = str(op.get("which", "")).strip().upper()
        tr = self.trial
        self.trial = None
        if not tr:
            r = self.apply({"op": "look", "prev": "keep"})
            r["error"] = "nothing to pick: use try first"
            return r
        if w in ("A", "B"):
            o = dict(tr[w], why=str(op.get("why", tr[w].get("why", "")))[:120], prev="keep")
            self.st["tally"]["picked" + w] = self.st["tally"].get("picked" + w, 0) + 1
            r = self.apply(o)
            r["note"] = f"picked {w}: it is now the pending change (your next op's prev keeps or reverts it)"
            return r
        self.st["tally"]["pickedNone"] = self.st["tally"].get("pickedNone", 0) + 1
        return self.apply({"op": "look", "prev": "keep"})

    def _robust_mops(self) -> list[dict]:
        """Mesh pre-pass. Joints whose skin tears at a test bend (whole clip, 35 deg, pitch and roll, both signs, focus
        clip, GPU per-edge rule) are candidates; each candidate's seam smoothing (local weight diffusion with its parent)
        is tried on the real rig and KEPT only if the test bends tear less and the current pose does not tear more."""
        u = self.u
        clip = self.st["focus"]["clip"]
        fr = self.st["focus"]["frame"]
        base = self.edits(False)
        prior = self.mops(False)

        def tests(bone):
            out, worst = 0, (-1, None)
            for ax in ("pitch", "roll"):
                for sg in (1, -1):
                    e = u.make_edit(clip, bone, fr, HW_ALL, base, axis=ax, deg=35 * sg)
                    n = self.gl.clip_defect_edges(clip, base + [e])
                    out += n
                    if n > worst[0]:
                        worst = (n, self.gl.last_defect_mask.copy())
            return out, worst[1]
        n0 = self.gl.clip_defect_edges(clip, base)
        cands = []
        for b in u.jnames:
            node = u.names.index(b)
            pn = u.scene.parent.get(node)
            if b == "Root" or pn is None or pn < 0 or u.names[pn] not in u.jnames or u.names[pn] == "Root":
                continue
            if not any(ch[0] == "rotation" and ch[1] == node for ch in u.scene.channels[clip]):
                continue
            t, mask = tests(b)
            t -= 4 * n0
            if t > 8 and mask is not None and mask.any():
                cands.append((t, b, mask))
        cands.sort(key=lambda c: -c[0])
        acc, report = [], []
        s_ = u.scene
        n0c = {c2: self.gl.clip_defect_edges(c2, base) for c2 in u.clips if c2 != clip}
        try:
            for t, b, mask in cands[:16]:
                vs = np.unique(u.edges[mask])
                P = s_.P[vs]
                ctr = np.median(P, 0)
                rad = float(np.percentile(np.linalg.norm(P - ctr, axis=1), 90)) + 0.04 * u.H
                w = {}
                for v in vs:
                    for j, x in zip(s_.J[v], s_.W[v]):
                        w[int(j)] = w.get(int(j), 0.0) + float(x)
                top = [u.jnames[j] for j, _ in sorted(w.items(), key=lambda q: -q[1])[:3]]
                ok = False
                tries = []
                if len(top) > 1 and not self._adjacent(top[0], top[1]):
                    # skin shared by two joints that are not neighbours (a hand weighted onto a thigh): hand it over
                    tries.append(({"fix": "blend", "from": top[1], "to": top[0], "amount": 1.0, "center": ctr.tolist(),
                                   "radius": rad}, f"gave {top[1]}'s skin there to {top[0]}"))
                for ring, k in ((3, 1.0), (6, 1.6)):           # a local weight blend at the torn spot, then a wider one
                    tries.append(({"fix": "smooth", "bones": top, "ring": ring, "center": ctr.tolist(), "radius": rad * k},
                                  f"smoothed {'/'.join(top)}"))
                for m, what in tries:
                    try:
                        self.rig.apply(prior + acc + [m])
                    except ValueError:
                        continue
                    self.gl.upload_rig()
                    n1 = self.gl.clip_defect_edges(clip, base)
                    t1 = tests(b)[0] - 4 * n1
                    if n1 <= n0 and t1 < 0.7 * t and all(self.gl.clip_defect_edges(c2, base) <= n0c[c2] for c2 in n0c):
                        acc.append(m)
                        report.append(f"{b} ({what})")
                        ok = True
                        break
                if not ok:
                    report.append(f"{b} (no help, skipped)")
        finally:
            self.rig.apply(prior)
            self.gl.upload_rig()
            self.rig_key = ""
        self.robust_report = report
        if not acc:
            raise ValueError("robust: " + ("no joint tears at a 35 deg test bend" if not cands else
                                           "seam smoothing did not help any fragile joint: " + ", ".join(report[:8])))
        return acc

    def _adjacent(self, a: str, b: str) -> bool:
        s_, nm = self.u.scene, self.u.names
        ia, ib = nm.index(a), nm.index(b)
        pa, pb = s_.parent.get(ia), s_.parent.get(ib)
        return pa == ib or pb == ia or (pa is not None and pa == pb) or (pa is not None and s_.parent.get(pa) == ib)             or (pb is not None and s_.parent.get(pb) == ia)

    def reset(self) -> dict:
        """Back to the original animation and mesh (a fresh run)."""
        st = self.st
        st.update(kept=[], mops=[], pending=None, nextId=1, defects={}, tally={}, checklist=[], checkNext=0,
                  phase=self.phase0, viewCount=0)
        self.views_hist, self.last_view = [], None
        self.funnel.reset()
        self.r5 = R5Mode(self, Path(self.r5_dir)) if self.r5_dir else None
        self.gl.show_defects = self.r5 is None
        if self.phase0 == "fix" and self.r5 is None:
            self.funnel.start(self.total_steps)
        upgrade_stack(st)
        st["focus"]["frame"] = 0
        self.trial = None
        self.repairs_open, self.cause = 0, None
        self._apply_rig()
        self._render()
        self.save()
        return {"ok": True, "state": self.state_line()}

    def rig_glb_bytes(self) -> bytes:
        """The GLB the viewer loads: work.glb, or (after rig/mesh ops) work.glb + the rig state (cached per rig)."""
        if not self.mops():
            return self.work.read_bytes()
        if self.rig_glb[0] != self.rig_key:
            g = build_rig_glb(self.work.read_bytes(), self.u, self.rig)
            self.rig_glb = (self.rig_key, g.to_bytes())
        return self.rig_glb[1]

    def public_state(self) -> dict:
        st = self.st
        u = self.u
        clips = {c: {"n": v["n"], "start": v["start"], "step": v["step"], "end": v["end"], "period": v["period"],
                     "grid": [float(x) for x in v["grid"]], "times": v["times"]} for c, v in u.clips.items()}
        h = self.driver_hist

        def med(k):
            xs = [d["ms"][k] for d in h if d.get("ms", {}).get(k) is not None]
            return round(statistics.median(xs)) if xs else None
        p = st["pending"]
        pend = [u.viewer_edit(e) | {"id": p["id"]} for e in p["parts"]] if p else []
        return {"unit": self.unit_id, "focus": st["focus"], "tally": st["tally"], "sheetId": self.sheet_id,
                "kept": [u.viewer_edit(e) | {"id": e["id"], "why": e.get("why", "")} for e in st["kept"]],
                "pendingEdits": pend, "pendingLine": self.pending_line(),
                "mops": [{"id": m.get("id"), "text": mop_summary(m), "why": m.get("why", "")} for m in st["mops"]],
                "rigKey": hashlib.sha1(self.rig_key.encode()).hexdigest()[:12] if self.mops() else "",
                "bones": list(u.jnames), "newBones": list(self.rig.new_joints), "mesh": self.defect_words(self.defect),
                "defects": st.get("defects", {}), "checklist": st.get("checklist", []), "phase": st.get("phase", "fix"),
                "funnel": self.funnel.public(), "r5": self.r5.public() if self.r5 is not None else None,
                "views": getattr(self, "views_hist", []), "lastView": getattr(self, "last_view", None),
                "stateLine": self.state_line(), "clips": clips, "driver": self.driver,
                "medians": {"render": med("render"), "model": med("model"), "step": med("step")},
                "control": load_json(self.control_path, {"state": "run"}).get("state", "run"),
                "loadMs": round(self.load_ms)}


SCHEMA = "haiku_anim_bench_stack.v2"
MAX_PARTS = 40
MAX_PIVOT_H = 0.3
TALLY_KEYS = ("edits", "kept", "reverted", "keptWhileFlagged", "repairs", "rigOps", "refused", "undone")


def upgrade_stack(st: dict) -> dict:
    """v1 (single pending edit + mirror pair, auto-revert tallies) -> v2 (pending group, mesh/rig ops)."""
    st.setdefault("mops", [])
    st.setdefault("defects", {})
    t = st.setdefault("tally", {})
    for k in TALLY_KEYS:
        t.setdefault(k, 0)
    p = st.get("pending")
    if p and "parts" not in p:
        pair = p.pop("pair", None)
        st["pending"] = {"id": p["id"], "type": "pose", "parts": [p] + ([pair] if pair else []), "why": p.get("why", ""),
                         "item": p.get("item", "")}
    st["schema"] = SCHEMA
    return st


def scale_edit(e: dict, k: float) -> dict:
    e = dict(e)
    if k == 1.0:
        return e
    if e["kind"] == "rot":
        e["deg"] = round(e["deg"] * k, 3)
    else:
        e["tr"] = [round(x * k, 4) for x in e["tr"]]
        e["deltaLocal"] = [x * k for x in e["deltaLocal"]]
    return e


def part_summary(e: dict) -> str:
    if e["kind"] in ("net", "nettr"):
        return f"{e['bone']} net {'rotation' if e['kind'] == 'net' else 'move'}"
    return (f"{e['bone']} " + (f"{e['axis']} {e['deg']:+g}deg" if e["kind"] == "rot" else f"tr {e['tr']}")
            + (" over the whole clip" if e["hw"] >= HW_ALL else f" @f{e['frame']:g}+-{e['hw']:g}"))


def mop_summary(m: dict) -> str:
    if m.get("fix"):
        if m["fix"] == "sculpt":
            return f"sculpt {m['mode']} {m['amount']:+g}"
        if m["fix"] == "corrective":
            return f"corrective {m['mode']} keyed to {m['bone']} ({m['clip'].replace('Unit_', '')} f{m['frame']:g})"
        if m["fix"] in ("rebind", "paint"):
            return f"{m['fix']} skin to {m['bone']}" + (f" {m['amount']:+g}" if m["fix"] == "paint" else "")
        if m["fix"] == "blend":
            return f"blend {m['from']}->{m['to']} near the spot"
        if m["fix"] in ("smooth", "nocs"):
            return f"{m['fix']} {'/'.join(m['bones'])}"
        return "relax the rest shape near the spot"
    if m["do"] == "split":
        return f"split {m['bone']} -> new joint {m.get('name')}"
    if m["do"] == "add":
        return f"add joint {m.get('name')} under {m['parent']} toward {m['toward']}"
    if m["do"] == "pivot":
        return f"move the pivot of {m['bone']}"
    return f"reparent {m['bone']} under {m['parent']}"


def mirror_name(n):
    if not n:
        return n
    for a, b in (("Left", "Right"), ("Right", "Left"), ("WingL_", "WingR_"), ("WingR_", "WingL_"), ("_L", "_R"), ("_R", "_L"),
                 ("L_", "R_"), ("R_", "L_")):
        if a in n:
            return n.replace(a, b, 1)
    return n + "_mirror"


def mirror_mop(m: dict):
    m = dict(m)
    key = "parent" if m["do"] == "add" else "bone"
    mb = mirror_bone(m[key])
    if mb is None:
        return None
    m[key] = mb
    if m.get("name"):
        m["name"] = mirror_name(m["name"])
    if m.get("toward") in ("left", "right"):
        m["toward"] = {"left": "right", "right": "left"}[m["toward"]]
    elif m.get("toward"):
        mt = mirror_bone(m["toward"])
        m["toward"] = mt or m["toward"]
    if m["do"] == "pivot":
        m["move"] = [-m["move"][0], m["move"][1], m["move"][2]]
    if m["do"] == "reparent":
        m["parent"] = mirror_bone(m["parent"]) or m["parent"]
    return m


B: Bench | None = None


class H(BaseHTTPRequestHandler):
    def log_message(self, *x):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/":
            return self._send((HERE / "viewer.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/work.glb":
            with B.lock:
                return self._send(B.call(B.rig_glb_bytes), "model/gltf-binary")
        if p == "/api/units":
            return self._json({"units": list_units(), "current": B.unit_id})
        if p == "/api/state":
            with B.lock:
                return self._json(B.public_state())
        if p == "/api/sheet.jpg":
            return self._send(B.sheet_jpeg, "image/jpeg")
        if p.startswith("/api/view/") and p.endswith(".jpg"):
            f = B.dir / "views" / f"{int(p[len('/api/view/'):-4]) % 24}.jpg"
            return self._send(f.read_bytes(), "image/jpeg") if f.is_file() else self._send(b"no view", "text/plain", 404)
        if p.startswith("/api/def/") and p.endswith(".png"):
            clip = p[len("/api/def/"):-4]
            tiles = B.gl.def_tiles.get(clip)
            if not tiles:
                return self._send(b"no clip", "text/plain", 404)
            buf = io.BytesIO()
            Image.fromarray(np.concatenate(tiles[BIG], 1)).save(buf, "PNG")
            return self._send(buf.getvalue(), "image/png")
        self._send(b"not found", "text/plain", 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        p = urlparse(self.path).path
        if p == "/api/apply":
            with B.lock:
                try:
                    return self._json(B.call(lambda: B.apply_turn(body)))
                except Exception as e:  # noqa: BLE001
                    return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        if p == "/api/reset":
            with B.lock:
                if body.get("phase") in ("survey", "fix"):
                    B.phase0 = body["phase"]
                if body.get("steps"):
                    B.total_steps = int(body["steps"])
                B.r5_dir = body.get("r5") or None
                return self._json(B.call(B.reset))
        if p in ("/api/judge_pack", "/api/verdict", "/api/board"):
            if B.r5 is None:
                return self._json({"error": "round 5 mode is off (reset with {\"r5\": run_dir})"}, 400)
            with B.lock:
                try:
                    if p == "/api/judge_pack":
                        return self._json(B.call(lambda: B.r5.judge_pack(body.get("mode", "pending"), body.get("item"))))
                    if p == "/api/verdict":
                        return self._json(B.call(lambda: B.r5.verdict(body)))
                    return self._json(B.call(lambda: B.r5.board(Path(body["out"]))))
                except Exception as e:  # noqa: BLE001
                    return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        if p == "/api/switch":
            try:
                return self._json(switch_unit(str(body.get("unit") or B.unit_id), body.get("clip")))
            except (ValueError, OSError) as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/control":
            s = body.get("state")
            if s not in ("run", "pause", "stop"):
                return self._json({"error": "state must be run|pause|stop"}, 400)
            B.control_path.write_text(json.dumps({"state": s, "t": time.time()}), encoding="utf-8")
            return self._json({"ok": True, "state": s})
        if p == "/api/driver":
            with B.lock:
                B.driver = body
                if body.get("ms", {}).get("model") is not None:
                    B.driver_hist.append(body)
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)


SHEET = "compact"


def mirror_bone(b: str):
    """Generic left/right partner name: Left*/Right*, *L_nn/*R_nn, *L/*R, *_L/*_R, *.L/*.R (no per-unit tables)."""
    for a, c in (("Left", "Right"), ("Right", "Left")):
        if b.startswith(a):
            return c + b[len(a):]
    m = re.match(r"^(.*?)([LR])(_\d+)$", b)
    if m:
        return m.group(1) + {"L": "R", "R": "L"}[m.group(2)] + m.group(3)
    for a, c in (("_L", "_R"), ("_R", "_L"), (".L", ".R"), (".R", ".L"), ("L", "R"), ("R", "L")):
        if b.endswith(a) and len(b) > len(a) and (len(a) == 2 or b[-2].islower()):
            return b[:-len(a)] + c
    return None


def unit_glb(unit: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"


def list_units() -> list[str]:
    d = ROOT / "artifacts/homm3_def_retarget"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / f"{p.name}_def_retarget.glb").is_file())


SWITCH_LOCK = threading.Lock()


def switch_unit(unit: str, clip: str | None) -> dict:
    """One GL context at a time: release the current bench's context, then load the new unit (its own work copy and
    stack under SCRATCH/<unit>/). Any def_retarget unit; no per-unit code."""
    global B
    src = unit_glb(unit)
    if not src.is_file():
        raise ValueError(f"no def_retarget GLB for {unit}")
    with SWITCH_LOCK:
        old = B
        if old is not None:
            with old.lock:
                old.close()
        try:
            nb = Bench(unit, src, clip or "Unit_Move")
        except SystemExit as e:
            if old is not None:
                B = Bench(old.unit_id, old.src, old.st["focus"]["clip"])
            raise ValueError(str(e)) from None
        if clip and clip in nb.u.clips and nb.st["focus"]["clip"] != clip:
            nb.call(lambda: nb.apply({"op": "move", "clip": clip, "frame": 0}))
        B = nb
    return {"unit": unit, "clip": B.st["focus"]["clip"], "clips": list(B.u.clips)}


def main() -> int:
    global B
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="h3_roc")
    ap.add_argument("--glb", default=None, help="source GLB (default artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb)")
    ap.add_argument("--clip", default="Unit_Idle")
    ap.add_argument("--port", type=int, default=8771)
    ap.add_argument("--sheet", choices=["compact", "full"], default="compact",
                    help="compact = 512 px with head crops + one loop cycle (run3+); full = the 768x672 run1/2 sheet")
    a = ap.parse_args()
    global SHEET
    SHEET = a.sheet
    src = Path(a.glb) if a.glb else ROOT / "artifacts/homm3_def_retarget" / a.unit / f"{a.unit}_def_retarget.glb"
    B = Bench(a.unit, src, a.clip)
    print(f"haiku anim bench: http://127.0.0.1:{a.port}/  (load {B.load_ms:.0f} ms, GL init {B.gl.init_ms:.0f} ms, "
          f"work {B.work})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
