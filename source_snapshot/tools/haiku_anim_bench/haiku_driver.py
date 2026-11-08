#!/usr/bin/env python3
"""Haiku fast-loop driver: Claude Haiku 5.5 repairs a unit's animation (and mesh) by itself against the anim bench.

    python tools/haiku_anim_bench/haiku_driver.py --unit h3_roc --clip Unit_Move [--steps 300] [--rotate 8]
                                                  [--max-out 200] [--run NAME]

Any def_retarget unit, any clip (the bench is switched to --unit/--clip first). The prompt is GENERIC: the art
standard, the sheet layout and the op palette; no unit hints, no agenda, no policing rules (2026-10-07 user: the
experiment is how far a small model gets with fast tooling and freedom). Haiku decides what is wrong and what to do.

There is no ANTHROPIC_API_KEY here, so the model is reached through the installed Claude Code CLI as ONE persistent
process per session: `claude -p --model claude-haiku-5-5 --input-format stream-json --output-format stream-json
--verbose --tools ""` (no tools, no MCP, no settings, no slash commands, effort low, CLAUDE_CODE_MAX_OUTPUT_TOKENS
small: that, not MAX_THINKING_TOKENS, is what keeps Haiku 5.5 from thinking). CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
drops the CLI's post-turn summary request (~1.0 s of every turn). The op is taken from the `assistant` event.
Each turn: the contact sheet (JPEG) + last op + its result + a one-line state (pending change, MESH report in words).
Sessions rotate every --rotate steps (model latency grows with context); a spare process is spawned and warmed (one
throwaway turn) in the background and seeded with the kept changes and recent ops.
Log: <work>/runs/<run>/steps.jsonl. Control: <work>/control.json {"state": run|pause|stop} (the viewer's buttons).
Never logs the CLI's environment or raw events.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anim_core import SCRATCH, friendly, load_json  # noqa: E402

MODEL = "claude-haiku-5-5"
OPS = ("edit", "pose", "try", "pick", "repair", "rig", "undo", "keep", "revert", "look", "view", "note", "phase", "tier", "intent", "check")

SYSTEM = """You are an animator and mesh artist with fast tools and full freedom. A game unit from Heroes of Might and Magic III ({UNIT}) was rebuilt in 3D from its original 2D sprite animations (the DEF). Any of its clips may be broken in any way: wrong motion or pose, stiff or unnatural joints, a mesh that tears, stretches, twists, collapses or passes through itself. Make it good. Each turn you get one image and a few lines of text; reply with ONE JSON op. Decide fast; anything can be undone.
Clips (DEF frames): {CLIPS}

THE RUN HAS TWO PHASES
Phase 1, SURVEY: look at every clip's poses, from whatever angles you choose, and judge them: the motion and attitude (what the unit is doing, where it looks, how the body is carried) and the mesh (torn or stretched skin, parts passing through each other, candy-wrapper twists, collapsed volume, spikes or floating pieces, bad bending at joints, anything else). Write each problem down with note (clip, frame, region, what is wrong) and rate it yourself with "sev":
  BIG = wrong at a glance from across the room: whole-body attitude, gaze or facing, the wrong action or motion, a missing beat, gross mesh breakage;
  MEDIUM = limb articulation, timing, a visible local tear;
  SMALL = polish.
Only view, look and note work in phase 1. You choose how many steps it takes (at most {SURVEY_MAX}); end it with {"op":"phase","to":"fix","why":"..."}.
Phase 2, FIX, a funnel from coarse to fine: the BIG tier first, then MEDIUM, then SMALL; each tier has its share of the steps (shown in the FUNNEL line; unused steps roll forward). Work the tier's items with tools that size: BIG items want big tools (whole-chain or compound poses, "hw":"all" whole-clip changes, large angles, whole-body and root moves, rebind, sculpt, rig changes); fine tuning waits for the later tiers. NOW in the FUNNEL line is the item being worked; {"op":"note","work":5} switches to another open item of this tier. Mark an item fixed or dropped when it is done. When a tier's items are closed, check the result from 2-3 free-camera angles (views with different yaw), then {"op":"tier","to":"next"}. In the SMALL tier you may re-survey: a new BIG note (or reopening a BIG item) jumps back to the BIG tier.
PARKED: when you cycle on one item (the same joint flipping back and forth, apply/revert loops, many steps with no kept change), the tool parks it and moves you to the next item. Accept it and move on; parked items come back once, in the SMALL tier.
When every tier is done and steps are left, a RE-SURVEY round starts: look again (view + note with sev), then {"op":"phase","to":"fix"} starts a new funnel round, or {"op":"phase","to":"done"} ends the run when nothing worth fixing is left.

THE IMAGES
After a view: exactly the camera you asked for (no DEF).
After any other op: the contact sheet of the focus clip. Row 1: DEF = the original 2D sprite frame (the reference) | ours from the DEF's own camera | ours from the side (the unit's left; it faces screen-left) | ours from the top (its front points screen-down). Row 2: DEF head close-up | OUR head close-up, same camera | ours from the front with the skeleton (yellow dots = joints, cyan = joints you added) | battle camera, OR "WORST NEW STRETCH": a close-up of the worst new mesh defect. Rows 3-5: the whole clip as motion: DEF frames, ours (DEF camera), ours (side); "tk" = a transition key; "f0 loop" = back to the start; the red box marks the focus frame. Orange ray = where OUR head points. Blue dashes = a level line through the hips. RED faces = skin stretched or torn by OUR changes.
The text: your last op and its result; the state (focus clip, pending change, MESH = new stretch caused by our changes in the focus clip, and other clips that went red); OURS NOW = our pose in plain words; NET POSE = our kept changes in the focus clip, one net value per joint (#id); CHECKLIST = your notes (this tier's open items in full, later tiers and done ones by #id); FUNNEL = the tier, its steps used/budget, the item being worked (NOW) and parked items.

FREE CAMERA (fast; changes nothing)
{"op":"view","clip":"Unit_Move","frame":3,"yaw":90,"pitch":15,"dist":1.3,"at":"body","mode":"shaded","why":"..."}
yaw: 0 = from the unit's front, 90 = from its left side, 180 = from behind, -90 = from its right side. pitch: + = from above (-89..89). dist = picture size in body heights (1.3 = the whole body, 0.3 = a close-up). at = a joint to centre on, or "body". "frames":[0,5] instead of "frame" = a strip of those frames. mode: shaded | wire (shaded + wireframe) | normals (colour = surface direction; creases and folds show dark) | heat (red = stretched skin, blue = squashed; the text says where) | skeleton (joints over the mesh).

CHECKLIST
{"op":"note","clip":"Unit_Idle","frame":2,"region":"left shoulder","sev":"MEDIUM","issue":"skin folds into the chest when the arm lifts","why":"..."}
{"op":"note","items":[{"clip":...,"frame":...,"region":...,"sev":...,"issue":...},{...}],"why":"..."}   several at once
{"op":"note","id":3,"status":"fixed","why":"..."}   status open|fixed|dropped (optional "sev" re-rates it)
{"op":"note","work":3,"why":"..."}   work on open item #3 of this tier next
{"op":"tier","to":"next","why":"..."}   leave this tier (after the 2-3 angle check)

THE STANDARD, in priority order
1. Gaze and motion intent: what the unit is doing: how the body is carried, where the head looks, the action, its beats and rhythm, as in the DEF.
2. Natural articulation: joints bend in sequence; nothing moves as a rigid board or a toy.
3. Mesh integrity: a clean mesh in every pose of every clip. It never blocks a change.
Judge the motion playing, from EVERY angle; the DEF tells you the action, not an outline to trace (no silhouette matching). Stride length and move speed may stay as they are; how the legs swing, bend and land, and everything else about the motion, is yours to change. Loop clips must stay seamless.

FREEDOM
No limits to speak of: big rotations (40-90 deg is normal when a part is far off), whole-body attitude, root moves, many joints in one pose, mesh sculpting and re-skinning are all fine. Mistakes are cheap: revert the pending change, or undo any kept one by its #id.

POSE CHANGES (a kept change merges into its joint's net pose)
"clip": any clip (default = the focus clip; naming another clip moves the focus there). A change is a smooth bump peaking at `frame` and fading to zero over `hw` frames each side (hw 1..6, wraps around the loop seam), or "hw":"all" = the same change at every frame of the clip.
Joints: {BONES}
Axes (the unit's body frame): pitch + = the joint's front end tips DOWN; yaw + = turns toward the unit's own LEFT; roll + = its top tilts toward the unit's RIGHT. deg -120..120. "mirror": true also applies the mirrored change to the other side.
{"op":"edit","clip":"Unit_Move","bone":"Head","axis":"pitch","deg":-15,"frame":2,"hw":3,"prev":"keep","why":"..."}
{"op":"pose","frame":3,"hw":2,"mirror":true,"parts":[{"bone":"LeftUpLeg","axis":"pitch","deg":-45},{"bone":"LeftLeg","axis":"pitch","deg":50}],"prev":"keep","why":"..."}   several joints as ONE change
Move a joint that has a position track (e.g. Hips): a part or edit with "tr":[dx,dy,dz] in body heights (dy + = up, dz + = forward).
{"op":"try", ...the same fields as an edit or pose...} shows the change both ways (A = as written, B = every angle flipped) in one small sheet with words for each; then {"op":"pick","which":"A"|"B"|"none","why":"..."}. A try and its pick count as one step.

MESH TOOLS (they change the mesh or skin for EVERY clip; the text reports any clip that went red)
Where: "at": a joint (its pivot); "toward": back|front|up|down|left|right (that joint's outermost skin that way); "along": 0..1 toward its child joint; "offset":[dx,dy,dz] in body heights (x + = the unit's left, y + = up, z + = forward). Size: "radius" in body heights (0.02..0.8) or "size": small|medium|large. A region grows along the surface from that point, so it stays on the part it starts on. Without "at": the current red spot.
{"op":"repair","fix":"sculpt","mode":"inflate","amount":0.02,"at":"Spine1","toward":"front","radius":0.15,"prev":"keep","why":"..."}   reshape the mesh: mode move (+ "dir": up|down|front|back|left|right; amount in body heights) | scale (amount -0.8..1.5) | inflate | deflate (amount in body heights, up to 0.15) | smooth (amount 0..1) | flatten (amount 0..1)
{"op":"repair","fix":"rebind","bone":"RightHand","toward":"down","radius":0.2,"prev":"keep","why":"..."}   bind that piece of surface rigidly to one joint (something held, a horn, a shell plate...)
{"op":"repair","fix":"paint","bone":"Head","amount":0.5,"at":"Neck","size":"small","prev":"keep","why":"..."}   paint skin weight toward a joint (amount -1..1; negative takes weight off it)
{"op":"repair","fix":"corrective","bone":"LeftLeg","clip":"Unit_Idle","frame":2,"mode":"inflate","amount":0.03,"at":"LeftLeg","radius":0.1,"prev":"keep","why":"..."}   a sculpt that appears only as that joint bends toward its pose at that clip/frame (keeps volume at a bent joint, ...)
{"op":"repair","fix":"smooth","bones":["Neck","Spine2"],"ring":2,...}   blend skin weights across a seam (ring 1..6)
{"op":"repair","fix":"blend","from":"Spine","to":"Hips","amount":0.5,"size":"medium",...}   hand part of the skin from one joint to another
{"op":"repair","fix":"relax","size":"medium","strength":0.5,...} | {"op":"repair","fix":"nocs","bones":["Head"],...} (baked corrective smoothing off) | {"op":"repair","fix":"robust",...} (test-bend every joint, smooth the seams that tear)

RIG CHANGES (new joints are poseable at once)
{"op":"rig","do":"split","bone":"Neck","at":0.5,"name":"UpperNeck","prev":"keep","why":"..."}   a new joint partway along a bone ("toward": a child joint when it has several)
{"op":"rig","do":"add","parent":"Hips","toward":"back","size":0.3,"name":"Tail","prev":"keep","why":"..."}
{"op":"rig","do":"pivot","bone":"LeftArm","move":[0,0.02,0],...} | {"op":"rig","do":"reparent","bone":"Tail","parent":"Spine",...}   "mirror": true works for split/add/pivot.

OTHER OPS
{"op":"look","clip":"Unit_Idle","frame":4,"prev":"keep","why":"..."}   resolve the pending change and show that clip's contact sheet
{"op":"keep","why":"..."} / {"op":"revert","why":"..."}
{"op":"undo","id":12,"prev":"keep","why":"..."}   take out a joint's net change (its #id in NET POSE) or a kept mesh/rig change
prev = what happens to the CURRENT pending change first: "keep" or "revert".
Exactly one JSON object on one line, no prose, no code fence. "why": 15 words at most."""


def bench(url: str, path: str, body=None, timeout=120):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if path.endswith(".jpg") else json.loads(data)


class Session:
    """One persistent `claude -p` stream-json process."""

    def __init__(self, system: str, cwd: Path, max_out: int):
        env = dict(os.environ)
        env.update(MAX_THINKING_TOKENS="0", CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(max_out),
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        cmd = ["claude", "-p", "--model", MODEL, "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--tools", "", "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
               "--disable-slash-commands", "--effort", "low", "--system-prompt", system]
        self.t_spawn = time.perf_counter()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  encoding="utf-8", env=env, cwd=str(cwd), bufsize=1)
        self.turns = 0
        self.api_ms_prev = 0

    def ask(self, content: list) -> dict:
        t0 = time.perf_counter()
        self.p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n")
        self.p.stdin.flush()
        text, t_asst, usage, api_ms = "", None, {}, None
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("claude CLI exited")
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "assistant":
                for c in e["message"].get("content", []):
                    if c.get("type") == "text":
                        text += c["text"]
                if t_asst is None:
                    t_asst = time.perf_counter()
            elif e.get("type") == "result":
                u = e.get("usage") or {}
                usage = {"in": u.get("input_tokens"), "cacheRead": u.get("cache_read_input_tokens"),
                         "cacheWrite": u.get("cache_creation_input_tokens"), "out": u.get("output_tokens"),
                         "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens")}
                d = e.get("duration_api_ms")
                if d is not None:
                    api_ms, self.api_ms_prev = d - self.api_ms_prev, d
                if e.get("is_error"):
                    text = text or f"ERROR {e.get('subtype')}"
                break
        self.turns += 1
        t1 = time.perf_counter()
        return {"text": text, "modelMs": round(((t_asst or t1) - t0) * 1000, 1), "turnMs": round((t1 - t0) * 1000, 1),
                "apiMs": api_ms, "usage": usage}

    def warm(self):
        """Absorb the fresh process's slow first turn (boot, prompt-cache write, one-off thinking) off the clock."""
        def run():
            try:
                self.warm_result = self.ask([{"type": "text", "text": "Warm-up turn before the session starts: reply "
                                              "exactly {\"op\":\"keep\",\"why\":\"ready\"} and nothing else."}])
            except Exception as e:  # noqa: BLE001
                self.warm_result = {"error": str(e)}
        self.warm_result = None
        self.warm_thread = threading.Thread(target=run, daemon=True)
        self.warm_thread.start()
        return self

    def ready(self):
        if getattr(self, "warm_thread", None):
            self.warm_thread.join()
            self.warm_thread = None
        return self

    def close(self, wait=False):
        def run():
            try:
                self.p.stdin.close()
                self.p.wait(timeout=20)
            except Exception:  # noqa: BLE001
                self.p.kill()
        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()


def parse_op(text: str) -> tuple[dict | None, str | None]:
    """The LAST complete JSON op in the reply (a capped reply that the CLI continues can arrive as a truncated op
    followed by the full one)."""
    dec = json.JSONDecoder()
    found, last_err = None, "no JSON object in the reply"
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError as e:
            last_err = f"bad JSON ({e})"
            continue
        if isinstance(obj, dict) and "op" in obj:
            found = obj
    if found is None:
        return None, last_err
    if found.get("op") not in OPS:
        return None, f"unknown op {found.get('op')!r}"
    return found, None


WORDS = {"pitch": ("tipped its front DOWN", "lifted its front UP"),
         "yaw": ("turned it toward the unit's LEFT", "turned it toward the unit's RIGHT"),
         "roll": ("tilted its top toward the unit's RIGHT", "tilted its top toward the unit's LEFT")}


def describe(op: dict) -> str:
    """Rotation changes restated in plain direction words (no measurement): helps keep the axis signs straight."""
    parts = op.get("parts") if op.get("op") == "pose" else ([op] if op.get("op") == "edit" else [])
    out = []
    for p in parts or []:
        if not isinstance(p, dict) or p.get("tr") is not None or p.get("axis") not in WORDS:
            continue
        d = float(p.get("deg", 0) or 0)
        out.append(f"{p.get('bone')} {WORDS[p['axis']][0 if d >= 0 else 1]}")
    if not out:
        return ""
    at = "over the whole clip" if str(op.get("hw")).lower() == "all" else f"at f{op.get('frame')}"
    return f" [that {op['op']} {at}: " + "; ".join(out) + (", mirrored" if op.get("mirror") else "") + "]"


def bones_text(st: dict) -> str:
    """The unit's own joint list, generic: numbered chains collapsed (Tail_00..Tail_06), plain words where they help."""
    new = set(st.get("newBones") or [])
    chains, out = {}, []
    for b in st["bones"]:
        m = re.match(r"^(.*?)_(\d+)$", b)
        if m and b not in new:
            if m.group(1) not in chains:
                chains[m.group(1)] = []
                out.append(("chain", m.group(1)))
            chains[m.group(1)].append(b)
        elif b not in new and b != "Root":
            out.append(("bone", b))
    parts = []
    for kind, x in out:
        if kind == "bone":
            parts.append(x + (f" ({friendly(x)})" if friendly(x) != x.lower() else ""))
        else:
            c = chains[x]
            parts.append(f"{c[0]}..{c[-1]} (a chain, base to tip)" if len(c) > 1 else c[0])
    t = ", ".join(parts)
    if new:
        t += "; joints you added: " + ", ".join(sorted(new))
    return t


SURVEY_MAX = 60


def make_system(st: dict, clip: str) -> str:
    clips = ", ".join(f"{c} ({v['n']})" for c, v in st["clips"].items())
    return (SYSTEM.replace("{BONES}", bones_text(st)).replace("{UNIT}", st["unit"]).replace("{CLIPS}", clips)
            .replace("{SURVEY_MAX}", str(SURVEY_MAX)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="h3_roc")
    ap.add_argument("--clip", default="Unit_Move")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--rotate", type=int, default=60, help="max steps per CLI session")
    ap.add_argument("--rotate-tokens", type=int, default=24000,
                    help="start a new CLI session once a turn's context reaches this many tokens (latency grows with it)")
    ap.add_argument("--survey", type=int, default=0, help="phase 1 survey budget (Haiku ends it earlier with a phase op)")
    ap.add_argument("--max-out", type=int, default=200, help="output-token cap (keeps Haiku from thinking; every session "
                                                              "gets a warm-up turn first, which absorbs its one-off thinking)")
    ap.add_argument("--bench", default="http://127.0.0.1:8771")
    ap.add_argument("--run", default=None)
    ap.add_argument("--fresh", action="store_true", help="reset the unit to its original animation and mesh first")
    ap.add_argument("--r5", action="store_true", help="round 5: intents + candidates, blind judge, items with tabu, "
                                                      "auto mesh repair (steps = ALL proposer turns incl. the survey)")
    a = ap.parse_args()
    if a.r5:
        import r5_driver
        return r5_driver.main(a)
    st = bench(a.bench, "/api/state")
    if st["unit"] != a.unit:
        r = bench(a.bench, "/api/switch", {"unit": a.unit, "clip": a.clip}, timeout=300)
        if r.get("error"):
            raise SystemExit(r["error"])
        st = bench(a.bench, "/api/state")
    if a.clip not in st["clips"]:
        raise SystemExit(f"{a.unit} has no clip {a.clip}: {sorted(st['clips'])}")
    global SURVEY_MAX
    SURVEY_MAX = a.survey or SURVEY_MAX
    if a.fresh:
        bench(a.bench, "/api/reset", {"phase": "survey" if a.survey else "fix", "steps": a.steps})
        st = bench(a.bench, "/api/state")
    phase = st.get("phase", "fix")
    survey_steps = 0
    survey_cap = a.survey
    ctx_tokens = 0
    work = SCRATCH / a.unit
    run = a.run or time.strftime("run_%Y%m%d_%H%M%S")
    rdir = work / "runs" / run
    rdir.mkdir(parents=True, exist_ok=True)
    cli_cwd = SCRATCH / "cli"
    cli_cwd.mkdir(exist_ok=True)
    control = work / "control.json"
    control.write_text(json.dumps({"state": "run", "t": time.time()}), encoding="utf-8")
    system = make_system(st, a.clip)
    (rdir / "system_prompt.txt").write_text(system, encoding="utf-8")
    log = open(rdir / "steps.jsonl", "a", encoding="utf-8")
    first = bench(a.bench, "/api/apply", {"op": "look", "clip": a.clip,
                                          "frame": st["focus"]["frame"] if st["focus"]["clip"] == a.clip else 0, "prev": "keep"})
    last_line = (("PHASE 1 (survey) starts: judge the mesh in every clip from any angles; note what is wrong. "
                  if phase == "survey" else "") + f"start: {first['state']}")
    sess = Session(system, cli_cwd, a.max_out).warm().ready()
    nxt, session_no, sess_steps = Session(system, cli_cwd, a.max_out).warm(), 1, 0
    nxt_bones = st["bones"]
    history: list[str] = []
    print(f"run {run}: {a.unit} {a.clip}; log {rdir / 'steps.jsonl'}", flush=True)
    step = 0
    tier_now = None
    while step < a.steps:
        if phase == "survey" and survey_steps >= survey_cap:
            r0 = bench(a.bench, "/api/apply", {"op": "phase", "to": "fix", "why": "survey budget used"})
            phase = "fix"
            last_line = f"The survey budget is used up: PHASE 2 (fixing) starts now. {r0.get('note')}. State: {r0['state']}"
        c = load_json(control, {"state": "run"}).get("state")
        if c == "stop":
            break
        if c == "pause":
            bench(a.bench, "/api/driver", {"step": step, "maxSteps": a.steps, "session": session_no, "status": "paused"})
            time.sleep(1.0)
            continue
        t0 = time.perf_counter()
        handover = None
        if nxt is None:
            s_now = bench(a.bench, "/api/state")
            system = make_system(s_now, a.clip)
            nxt, nxt_bones = Session(system, cli_cwd, a.max_out).warm(), s_now["bones"]
        if sess_steps >= a.rotate or ctx_tokens >= a.rotate_tokens:
            ctx_tokens = 0
            sess.close()
            sess, nxt, sess_steps = nxt.ready(), None, 0
            session_no += 1
            s2 = bench(a.bench, "/api/state")
            mops = [f"#{m['id']} {m['text']}" for m in s2.get("mops", [])]
            added = [b for b in s2["bones"] if b not in nxt_bones]
            handover = ("NEW SESSION (context reset; the warm-up turn was not a real op). Your kept pose is the NET POSE "
                        "in the state below. Kept mesh/rig changes: " + ("; ".join(mops) or "none")
                        + (f". Joints added since this session's joint list: {', '.join(added)}" if added else "")
                        + ". Recent ops, oldest first: " + " | ".join(history[-8:])
                        + (" We are in PHASE 1 (survey)." if phase == "survey"
                           else f" We are in PHASE 2 (fixing), funnel tier {tier_now}."))
        jpeg = bench(a.bench, "/api/sheet.jpg")
        label = (f"survey step {survey_steps + 1}/{survey_cap}" if phase == "survey" else f"fix step {step + 1}/{a.steps}"
                 + (f", tier {tier_now}" if tier_now else ""))
        text = (f"{label}. {last_line}" + (f"\n{handover}" if handover else "")
                + "\nReply with one JSON op.")
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpeg).decode()}},
                   {"type": "text", "text": text}]
        t1 = time.perf_counter()
        try:
            r = sess.ask(content)
        except RuntimeError as e:
            print(f"session died: {e}; respawning", flush=True)
            sess = Session(system, cli_cwd, a.max_out).warm().ready()
            session_no += 1
            sess_steps = 0
            continue
        t2 = time.perf_counter()
        sess_steps += 1
        u_ = r.get("usage") or {}
        ctx_tokens = (u_.get("in") or 0) + (u_.get("cacheRead") or 0) + (u_.get("cacheWrite") or 0) + (u_.get("out") or 0)
        op, err = parse_op(r["text"])
        res = None
        if op:
            res = bench(a.bench, "/api/apply", op)
            err = res.get("error")
        t3 = time.perf_counter()
        fun = (res or {}).get("funnel") or {}
        was_tier = tier_now
        if fun.get("tier"):
            tier_now = fun["tier"]
        if op is None or res is None:
            last_line = f"Your reply was rejected: {err}. Current: {bench(a.bench, '/api/state')['stateLine']}"
        else:
            res_s = f" [previous pending change {res['resolved']}]" if res.get("resolved") else ""
            err_s = f" -> ERROR {err}" if err else ""
            short = {k: v for k, v in op.items() if k != "why"}
            note = f" ({res['note']})" if res.get("note") else ""
            last_line = (f"last op {json.dumps(short, separators=(',', ':'))}{describe(op)}{res_s}{err_s}{note}. "
                         f"State: {res['state']}")
        history.append(f"{json.dumps(op or {}, separators=(',', ':'))}" + (f" err {err}" if err else ""))
        is_try = bool(op and op["op"] == "try" and not err and not (history[-2:-1] and '"op":"try"' in history[-2]))
        was_phase = phase
        if op and op["op"] == "phase" and not err:
            phase = "survey" if op.get("to") == "survey" else "fix"
        if was_phase == "survey":
            survey_steps += 1
        elif not is_try:
            step += 1                   # a try and its pick count as ONE step (a try after a try counts)
        t4 = time.perf_counter()
        ms = {"render": round((t3 - t2) * 1000, 1) if res else 0.0, "model": r["modelMs"],
              "fetch": round((t1 - t0) * 1000, 1), "step": round((t4 - t0) * 1000, 1)}
        ms["other"] = round(ms["step"] - ms["render"] - ms["model"], 1)
        rec = {"step": step, "phase": was_phase, "tier": was_tier, "funnel": fun.get("log", [])[-1:] if fun else None, "surveyStep": survey_steps, "ctxTokens": ctx_tokens, "try": is_try, "session": session_no, "unit": a.unit, "clip": a.clip, "t": round(time.time(), 3),
               "reply": r["text"][:400], "op": op, "error": err, "mesh": res.get("mesh") if res else None,
               "stretch": res.get("stretch") if res else None, "mop": res.get("mop") if res else None,
               "resolved": res.get("resolved") if res else None, "benchMs": res.get("ms") if res else None,
               "ms": ms, "apiMs": r["apiMs"], "turnMs": r["turnMs"], "usage": r["usage"], "state": res["state"] if res else None}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        bench(a.bench, "/api/driver", {"step": step if was_phase == "fix" else survey_steps,
                                       "maxSteps": a.steps if was_phase == "fix" else a.survey, "session": session_no,
                                       "status": f"{'survey' if was_phase == 'survey' else 'fixing'} {a.unit}",
                                       "op": op or {"error": err}, "mesh": res.get("mesh") if res else None, "ms": ms})
        print(f"{step:3d} {ms['step']:6.0f} ms (model {ms['model']:5.0f}, render {ms['render']:5.1f}) "
              f"[{was_tier or phase}] {json.dumps(op or {'error': err})[:150]}", flush=True)
        if fun.get("finished"):
            print("run ended by Haiku (phase done)", flush=True)
            break
        if tier_now == "DONE" and phase == "fix":
            left = a.steps - step
            if left < 20:
                print(f"all funnel tiers done ({left} steps left)", flush=True)
                break
            r0 = bench(a.bench, "/api/apply", {"op": "phase", "to": "survey", "why": "funnel round done"})
            phase = "survey"
            survey_cap = survey_steps + max(a.survey // 3, 6)
            print(f"funnel round done; re-survey round ({left} steps left)", flush=True)
            last_line = (f"Every tier of this funnel round is done and {left} fix steps are left. {r0.get('note')}. "
                         f"Re-survey budget: {survey_cap - survey_steps} steps. State: {r0['state']}")
    sess.close(wait=True)
    if nxt:
        nxt.ready().close(wait=True)
    bench(a.bench, "/api/driver", {"step": step, "maxSteps": a.steps, "session": session_no, "status": "finished"})
    log.close()
    print(f"done: {step} steps; log {rdir / 'steps.jsonl'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
