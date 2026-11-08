"""Round 5 driver (haiku_driver.py --r5): Haiku proposes intents and picks candidates; a separate, fresh, blind Haiku
judge accepts or rejects every change; items close only by a judge win; rejected attempts are TABU for the whole run.

    python tools/haiku_anim_bench/haiku_driver.py --r5 --unit h3_roc --clip Unit_Move --steps 150 --survey 25 \
        --max-out 320 --run r5_move --fresh

--steps counts EVERY proposer turn (survey included). Judge calls are separate `claude -p --model claude-haiku-5-5`
processes with no history and no tools, two per judged change (the pair in both orders), run in parallel.
Log: <work>/runs/<run>/steps.jsonl, judge.jsonl (bench), items.json (bench), summary.json/.txt, before_after.jpg.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from anim_core import SCRATCH, load_json
from haiku_driver import MODEL, Session, bench, bones_text, parse_op

SYSTEM5 = """You are an animator with fast tools. A game unit from Heroes of Might and Magic III ({UNIT}) was rebuilt in 3D from its original 2D sprite animations (the DEF). Any of its clips may be wrong in any way: motion, attitude, gaze, stiff or unnatural joints, mesh. Make it good. Each turn you get one image and a few lines of text; reply with ONE JSON op.
Clips (DEF frames): {CLIPS}

THE RUN
Phase 1, SURVEY (at most {SURVEY_MAX} steps): look at the clips from any angles and write down what is wrong: {"op":"note","clip":"Unit_Move","frame":2,"region":"head","sev":"BIG","issue":"looks at the ground instead of ahead","why":"..."} (or "items":[{...},{...}]). sev: BIG = wrong at a glance (attitude, gaze, facing, wrong action); MEDIUM = limb articulation, timing, a local tear; SMALL = polish. End the survey with {"op":"phase","to":"fix","why":"..."}.
Phase 2, FIX: work the ITEMS list. NOW is the item being worked; {"op":"note","work":3} switches; new notes add items. You never close items yourself: a separate judge compares before and after next to the DEF and keeps a change only if it is clearly better; it closes an item when the problem is gone. Rejected attempts are listed under TABU for the whole run: do not repeat them; change the goal, chain, direction, strength or frames instead.

INTENTS (your main tool): say WHAT you want; the bench solves the joint rotations, spreads the bend along the chain, avoids tearing, and shows candidates.
{"op":"intent","item":1,"clip":"Unit_Move","frame":2,"goal":"gaze","dir":"level forward","why":"..."}
 goal: gaze = where the head looks | trunk = the hips-to-chest line (body carriage) | reach = a limb's root-to-tip direction | spread = how far a limb is spread out to its side, "amount" 0 (folded along the body) .. 1 (straight out) | bend = a limb's middle joint, "deg" 0 (straight) .. 150 (folded).
 dir (gaze, trunk, reach): words, vertical: level | slightly up | up | steeply up | straight up | slightly down | down | steeply down | straight down; horizontal: forward | left | right | back | forward-left | forward-right | back-left | back-right | out (toward the limb's own side). A part you leave out stays as it is. Or numbers in the READOUT's terms: "elev":-10,"az":0 (absolute) or "d_elev":15 / "d_az":-20 (relative).
 limb (reach, spread, bend): {LIMBS}. "mirror":true does the partner limb the same way.
 One gaze/trunk/reach intent turns at most 40 degrees at 100% (a bigger change comes in judged steps).
 frames: "frame":f = that frame (the change fades over "hw" frames each side, default 2); "frames":[a,b] = every frame from a to b; "frames":"all" = every frame of the clip (each frame gets its own solve).
The reply is a CANDIDATES sheet: DEF | NOW | V1 V2 V3 V4 (rows = the views that matter) and words for each: V1, V2, V3 = 50%, 100%, 150% of the way to your goal; V4 = 100% on another chain distribution (or 75%). Then {"op":"pick","which":"V2","why":"..."} sends that candidate to the judge, or "which":"none" (that intent then counts as tried).
{"op":"check","item":3,"why":"..."} asks the judge whether an item is already fixed (original vs now), e.g. after a change for another item.

READOUT = numbers for OUR pose only (degrees; elev + = up, az 0 = forward, + = toward the unit's own left). Use it to aim your goals; how the DEF looks is judged by eye.

THE IMAGES
After a view: exactly the camera you asked for (no DEF). After an intent: the CANDIDATES sheet. Otherwise the contact sheet of the focus clip: Row 1: DEF = the original 2D sprite frame (the reference) | ours from the DEF's own camera | ours from the side (the unit's left; it faces screen-left) | ours from the top (its front points screen-down). Row 2: DEF head close-up | OUR head close-up | ours from the front with the skeleton | battle camera. Rows 3-5: the whole clip: DEF frames, ours (DEF camera), ours (side); "tk" = a transition key; "f0 loop" = back to the start; the red box marks the focus frame. Orange ray = where OUR head points. Blue dashes = a level line through the hips.
The text: your last op and its result (and the judge's verdict); the state: focus clip, pending change, MESH (clean, or flagged at a body part; the bench repairs the mesh itself after every accepted change); OURS NOW = our pose in words; READOUT; NET POSE = our kept changes per joint (#id); ITEMS; TABU.

FREE CAMERA (fast; changes nothing)
{"op":"view","clip":"Unit_Move","frame":3,"yaw":90,"pitch":15,"dist":1.3,"at":"body","mode":"shaded","why":"..."}
yaw: 0 = from the unit's front, 90 = from its left side, 180 = from behind, -90 = from its right side. pitch: + = from above. dist = picture size in body heights. at = a joint or "body". "frames":[0,5] instead of "frame" = a strip. mode: shaded | wire | normals | heat | skeleton.
{"op":"look","clip":"Unit_Idle","frame":4,"why":"..."} = that clip's contact sheet.

THE STANDARD, in priority order
1. Gaze and motion intent: what the unit is doing: how the body is carried, where the head looks, the action, its beats and rhythm, as in the DEF.
2. Natural articulation: joints bend in sequence; nothing moves as a rigid board or a toy.
3. Mesh integrity (the bench handles it after each accepted change).
Judge the motion playing, from EVERY angle; the DEF tells you the action, not an outline to trace (no silhouette matching). Stride length and move speed may stay as they are; how the legs swing, bend and land is yours to change. Loop clips must stay seamless.

FALLBACK (low level; prefer intents): joints: {BONES}. Axes in the unit's body frame: pitch + = the joint's front end tips DOWN; yaw + = turns toward the unit's own LEFT; roll + = its top tilts toward the unit's RIGHT.
{"op":"edit","clip":"Unit_Move","bone":"Head","axis":"pitch","deg":-15,"frame":2,"hw":3,"why":"..."} | {"op":"pose","frame":3,"hw":2,"mirror":true,"parts":[{"bone":"LeftUpLeg","axis":"pitch","deg":-45}],"why":"..."} | {"op":"try",...same fields...} then pick A|B|none.
A pending edit/pose goes to the judge with {"op":"keep","why":"..."}; {"op":"revert"} drops it.
ADVANCED (rarely needed; the bench repairs the mesh itself): {"op":"repair","fix":"sculpt"|"rebind"|"paint"|"smooth"|"blend"|"relax"|"robust",...} and {"op":"rig","do":"split"|"add"|"pivot"|"reparent",...} as in the bench's mesh tools.
Exactly one JSON object on one line, no prose, no code fence. "why": 15 words at most."""

JUDGE_SYSTEM = """You are a strict, impartial reviewer of 3D game-unit animation. A unit was rebuilt in 3D from its original 2D sprite animation (the DEF). You get one image: the DEF on top (the reference: one frame, its head close-up and the clip as a strip), then VERSION 1 and VERSION 2 of our 3D unit at the same frame from the sprite camera, the side and a 3/4 view, each with the clip as a strip. An orange ray shows where the 3D head looks. You judge ONE named problem only: in which version is that problem smaller, i.e. which comes closer to what the DEF shows for it (the action and its beat, how the body is carried, where the head looks, how the limbs are posed and bend, an intact mesh), seen from every view. Ignore unrelated small differences. If you cannot see a real difference, the winner is "same".
The whole unit counts too: a version that is broken overall (tipped over, upside down, lying down or diving where the DEF is upright, twisted out of its anatomy, torn, the head buried in the body) LOSES, whatever it does for the named problem. Fixing the named problem by breaking the overall pose is not better.
First describe what each version shows for the problem, then decide. Reply with exactly one JSON object on one line:
{"v1":"what VERSION 1 shows for the problem, at most 10 words","v2":"the same for VERSION 2","winner":"1"|"2"|"same","fixed":true|false}
winner = the version where the problem is smaller (it must agree with your v1/v2 descriptions). fixed = in the winner the named problem is gone."""


def limbs_text(st: dict) -> str:
    return (st.get("r5") or {}).get("limbs") or "(none found)"


def make_system5(st: dict, survey_max: int) -> str:
    clips = ", ".join(f"{c} ({v['n']})" for c, v in st["clips"].items())
    return (SYSTEM5.replace("{BONES}", bones_text(st)).replace("{UNIT}", st["unit"]).replace("{CLIPS}", clips)
            .replace("{SURVEY_MAX}", str(survey_max)).replace("{LIMBS}", limbs_text(st)))


def judge_once(img_b64: str, text: str, cwd: Path, max_out: int = 2000, timeout: float = 120.0) -> dict:
    """One fresh, history-free `claude -p` Haiku call: the image + the problem; returns the parsed verdict."""
    env = dict(os.environ)
    env.update(MAX_THINKING_TOKENS="0", CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(max_out),
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    cmd = ["claude", "-p", "--model", MODEL, "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--tools", "", "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
           "--disable-slash-commands", "--effort", "low", "--system-prompt", JUDGE_SYSTEM]
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         encoding="utf-8", env=env, cwd=str(cwd), bufsize=1)
    out = {"raw": "", "ok": False}
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        msg = {"type": "user", "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
            {"type": "text", "text": text}]}}
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.close()
        for line in p.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "assistant":
                for c in e["message"].get("content", []):
                    if c.get("type") == "text":
                        out["raw"] += c["text"]
            elif e.get("type") == "result":
                u = e.get("usage") or {}
                out["usage"] = {"in": u.get("input_tokens"), "cacheRead": u.get("cache_read_input_tokens"),
                                "out": u.get("output_tokens")}
                break
        p.wait(timeout=30)
    except Exception as ex:  # noqa: BLE001
        out["error"] = f"{type(ex).__name__}: {ex}"
        p.kill()
    finally:
        timer.cancel()
    dec = json.JSONDecoder()
    t = out["raw"]
    for i in range(len(t)):
        if t[i] == "{":
            try:
                obj, _ = dec.raw_decode(t, i)
            except ValueError:
                continue
            if isinstance(obj, dict) and ("winner" in obj or "better" in obj):
                out.update(better=str(obj.get("winner", obj.get("better"))), fixed=obj.get("fixed") is True,
                           why=f"v1: {obj.get('v1', '')} | v2: {obj.get('v2', '')}"[:160], ok=True)
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    out["raw"] = out["raw"][:300]
    return out


def judge(url: str, need: dict, cwd: Path) -> tuple[dict, dict, dict]:
    pack = bench(url, "/api/judge_pack", need, timeout=300)
    if pack.get("error"):
        raise RuntimeError(pack["error"])
    text = (f"PROBLEM: {pack['problem']}. In which version is this problem smaller? Describe both, then decide. Reply with the JSON object only.")
    res = {}

    def run(k):
        res[k] = judge_once(pack[k], text, cwd)
        if not res[k].get("ok"):                     # an unparsable reply is retried once, never read as "same"
            r2 = judge_once(pack[k], text, cwd)
            r2["retried"] = True
            res[k] = r2
    th = [threading.Thread(target=run, args=(k,)) for k in ("ab", "ba")]
    for t in th:
        t.start()
    for t in th:
        t.join()
    return res["ab"], res["ba"], pack


def resources_ok() -> str | None:
    """None when the machine has room: >= 6 GB free RAM and >= 12 GB free on V:."""
    try:
        import psutil
        ram = psutil.virtual_memory().available / 2 ** 30
    except ImportError:
        ram = 99.0
    free_v = shutil.disk_usage("V:/").free / 2 ** 30
    if ram < 6:
        return f"only {ram:.1f} GB RAM free (< 6)"
    if free_v < 12:
        return f"only {free_v:.1f} GB free on V: (< 12)"
    return None


def main(a) -> int:
    url = a.bench
    low = resources_ok()
    if low:
        raise SystemExit(f"not starting: {low}")
    st = bench(url, "/api/state")
    if st["unit"] != a.unit:
        r = bench(url, "/api/switch", {"unit": a.unit, "clip": a.clip}, timeout=300)
        if r.get("error"):
            raise SystemExit(r["error"])
        st = bench(url, "/api/state")
    if a.clip not in st["clips"]:
        raise SystemExit(f"{a.unit} has no clip {a.clip}: {sorted(st['clips'])}")
    survey_cap = a.survey or 25
    work = SCRATCH / a.unit
    run = a.run or time.strftime("r5_%Y%m%d_%H%M%S")
    rdir = work / "runs" / run
    if a.fresh and rdir.exists():
        for f in ("items.json", "judge.jsonl", "steps.jsonl", "summary.json", "summary.txt"):
            (rdir / f).unlink(missing_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)
    bench(url, "/api/reset", {"phase": "survey", "steps": a.steps, "r5": str(rdir)})
    st = bench(url, "/api/state")
    cli_cwd = SCRATCH / "cli"
    cli_cwd.mkdir(exist_ok=True)
    control = work / "control.json"
    control.write_text(json.dumps({"state": "run", "t": time.time()}), encoding="utf-8")
    system = make_system5(st, survey_cap)
    (rdir / "system_prompt.txt").write_text(system, encoding="utf-8")
    log = open(rdir / "steps.jsonl", "a", encoding="utf-8")
    first = bench(url, "/api/apply", {"op": "look", "clip": a.clip, "frame": 0})
    last_line = ("PHASE 1 (survey) starts: judge every clip from any angles; note what is wrong (with sev). "
                 f"start: {first['state']}")
    sess = Session(system, cli_cwd, a.max_out).warm().ready()
    nxt, session_no, sess_steps, ctx_tokens = Session(system, cli_cwd, a.max_out).warm(), 1, 0, 0
    history: list[str] = []
    phase, survey_steps, turns = "survey", 0, 0
    t_attempt = None
    print(f"r5 run {run}: {a.unit} {a.clip}; log {rdir / 'steps.jsonl'}", flush=True)
    while turns < a.steps:
        if phase == "survey" and survey_steps >= survey_cap:
            r0 = bench(url, "/api/apply", {"op": "phase", "to": "fix", "why": "survey budget used"})
            phase = "fix"
            last_line = f"The survey budget is used up: PHASE 2 (fixing) starts now. {r0.get('note')}. State: {r0['state']}"
        c = load_json(control, {"state": "run"}).get("state")
        if c == "stop":
            break
        if c == "pause":
            time.sleep(1.0)
            continue
        t0 = time.perf_counter()
        t0_wall = time.time()
        handover = None
        if nxt is None:
            nxt = Session(system, cli_cwd, a.max_out).warm()
        if sess_steps >= a.rotate or ctx_tokens >= a.rotate_tokens:
            ctx_tokens = 0
            sess.close()
            sess, nxt, sess_steps = nxt.ready(), None, 0
            session_no += 1
            handover = ("NEW SESSION (context reset; the warm-up turn was not a real op). ITEMS and TABU in the state "
                        "carry everything tried so far; NET POSE is what the judge accepted. Recent ops, oldest first: "
                        + " | ".join(history[-8:]) + (" We are in PHASE 1 (survey)." if phase == "survey" else
                                                      " We are in PHASE 2 (fixing)."))
        jpeg = bench(url, "/api/sheet.jpg")
        label = f"survey step {survey_steps + 1}/{survey_cap}" if phase == "survey" else f"turn {turns + 1}/{a.steps}"
        text = f"{label}. {last_line}" + (f"\n{handover}" if handover else "") + "\nReply with one JSON op."
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
        turns += 1
        u_ = r.get("usage") or {}
        ctx_tokens = (u_.get("in") or 0) + (u_.get("cacheRead") or 0) + (u_.get("cacheWrite") or 0) + (u_.get("out") or 0)
        op, err = parse_op(r["text"])
        res, jrec = None, None
        if op:
            if op["op"] in ("intent", "edit", "pose", "try"):
                t_attempt = t0_wall
            res = bench(url, "/api/apply", op)
            err = res.get("error")
        t3 = time.perf_counter()
        if res and res.get("needsJudge"):
            need = res["needsJudge"]
            tj = time.perf_counter()
            try:
                r_ab, r_ba, pack = judge(url, need, cli_cwd)
                vres = bench(url, "/api/verdict", {"mode": need["mode"], "item": need.get("item"), "r_ab": r_ab,
                                                   "r_ba": r_ba, "step": turns,
                                                   "ms": {"judge": round((time.perf_counter() - tj) * 1000)}})
                jrec = {"mode": need["mode"], "item": need.get("item"), "verdict": vres.get("verdict"),
                        "r_ab": {k: r_ab.get(k) for k in ("better", "fixed", "why", "ms", "ok")},
                        "r_ba": {k: r_ba.get(k) for k in ("better", "fixed", "why", "ms", "ok")},
                        "judgeMs": round((time.perf_counter() - tj) * 1000), "repair": vres.get("repair")}
                if need["mode"] == "pending" and (vres.get("verdict") or {}).get("accept") and t_attempt:
                    jrec["acceptLatencyS"] = round(time.time() - t_attempt, 2)
                res = dict(vres, note=((res.get("note") + "; ") if res.get("note") else "") + (vres.get("note") or ""))
            except Exception as ex:  # noqa: BLE001
                jrec = {"error": f"{type(ex).__name__}: {ex}"}
                bench(url, "/api/apply", {"op": "revert", "why": "judge failed"})
                res["note"] = f"the judge failed ({ex}); the change was dropped"
        if op is None or res is None:
            last_line = f"Your reply was rejected: {err}. Current: {bench(url, '/api/state')['stateLine']}"
        else:
            err = res.get("error")
            short = {k: v for k, v in op.items() if k != "why"}
            last_line = (f"last op {json.dumps(short, separators=(',', ':'))}" + (f" -> ERROR {err}" if err else "")
                         + (f" ({res['note']})" if res.get("note") else "") + f". State: {res['state']}")
        history.append(json.dumps(op or {}, separators=(",", ":"))[:200] + (f" err {err}" if err else "")
                       + (f" judge {jrec.get('verdict', {}).get('verdict')}" if jrec and jrec.get("verdict") else ""))
        was_phase = phase
        if op and op["op"] == "phase" and not err and op.get("to") == "fix":
            phase = "fix"
        if was_phase == "survey":
            survey_steps += 1
        t4 = time.perf_counter()
        ms = {"render": round((t3 - t2) * 1000, 1) if res else 0.0, "model": r["modelMs"],
              "fetch": round((t1 - t0) * 1000, 1), "step": round((t4 - t0) * 1000, 1)}
        rec = {"turn": turns, "phase": was_phase, "session": session_no, "unit": a.unit, "clip": a.clip,
               "t": round(time.time(), 3), "reply": r["text"][:400], "op": op, "error": err,
               "note": (res or {}).get("note"), "intent": (res or {}).get("intent"), "judge": jrec,
               "mesh": (res or {}).get("mesh"), "ms": ms, "apiMs": r["apiMs"], "usage": r["usage"],
               "ctxTokens": ctx_tokens, "state": (res or {}).get("state")}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        bench(url, "/api/driver", {"step": turns, "maxSteps": a.steps, "session": session_no,
                                   "status": f"{'survey' if was_phase == 'survey' else 'fixing'} {a.unit} (r5)",
                                   "op": op or {"error": err}, "mesh": (res or {}).get("mesh"), "ms": ms})
        jv = (jrec or {}).get("verdict") or {}
        print(f"{turns:3d} {ms['step']:6.0f} ms (model {ms['model']:5.0f}) [{was_phase}] "
              f"{json.dumps(op or {'error': err})[:140]}" + (f"  JUDGE {jv.get('verdict')}" if jv else ""), flush=True)
        if phase == "fix" and res and (res.get("done") or (res.get("items") or {}).get("done")):
            print("item list closed", flush=True)
            break
    sess.close(wait=True)
    if nxt:
        nxt.ready().close(wait=True)
    bench(url, "/api/driver", {"step": turns, "maxSteps": a.steps, "session": session_no, "status": "finished"})
    log.close()
    finish(url, a.unit, a.clip, rdir)
    print(f"done: {turns} turns; {rdir}", flush=True)
    return 0


def finish(url: str, unit: str, clip: str, rdir: Path):
    """The run's outputs: final sheet, stack copy, before/after board, summary."""
    bench(url, "/api/apply", {"op": "look", "clip": clip, "frame": 0, "prev": "revert", "why": "final sheet"})
    (rdir / "final_sheet.jpg").write_bytes(bench(url, "/api/sheet.jpg"))
    shutil.copy(SCRATCH / unit / "stack.json", rdir / "stack_final.json")
    r = bench(url, "/api/board", {"out": str(rdir / "before_after.jpg")}, timeout=300)
    if r.get("error"):
        print("board error:", r["error"], flush=True)
    else:
        (rdir / "final_mesh.json").write_text(json.dumps(r.get("mesh") or {}, indent=1), encoding="utf-8")
    import r5_report
    r5_report.summarize(rdir)
