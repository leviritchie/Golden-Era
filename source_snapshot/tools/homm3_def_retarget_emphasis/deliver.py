"""Deliver the emphasis pass onto built DEF-retarget units (post-pass, in place on the canonical build).

  python tools/homm3_def_retarget_emphasis/deliver.py <unit> [<unit> ...] [--force]
  python tools/homm3_def_retarget_emphasis/deliver.py --roster [--force] [--first a,b] [--last a,b]
  python tools/homm3_def_retarget_emphasis/deliver.py --summary

Chain position (per unit):  retarget build (run_unit.sh) -> EMPHASIS (this) -> idle retime
(tools/homm3_idle_cadence/rollout_idle.py) -> unit look (tools/homm3_unit_look/look.py --force).
Emphasis rewrites the canonical artifacts/homm3_def_retarget/<u>/<u>_def_retarget.{blend,glb}; every
downstream lane must re-read them after it.

Per unit (W = artifacts/homm3_def_retarget_emphasis/<u>/, C = artifacts/homm3_def_retarget/<u>/):
  1. exceptions.json entry -> skipped (reported, never silent).
  2. source: the canonical .blend's sha256 vs W/stamp.json.  Equal to emphasisedBlendSha256 -> the
     pre-emphasis snapshot W/source/ is the source (up to date with the same paramsSha -> skip unless
     --force); anything else is a fresh build and is the source.
  3. detection (system Python, unit-look bodyNoFx DEF masks vs the build's own sprite renders).
     Nothing underEmphasised -> decision "unchanged", canonical untouched (restored from W/source/
     when it was emphasised before).
  4. snapshot C -> W/source/ (fresh builds only), work copy -> W/work/, one Blender (bl_deliver.py):
     plan, rewrite keys, re-bake corrective smooth, render changed clips, stretch, export work.glb.
  5. verify_glb.py (shared) on work.blend vs work.glb must print VERIFY OK; Idle/Move identical to
     the source's glb_verify (keys and loop closure); check_invariants on the key dumps.
  6. stretch gate per changed clip: worst frame edges>2x after <= max(STRETCH_MUL * before,
     before + STRETCH_ADD).  A failing unit is not installed (decision "stretchGateFailed"); it
     gets an explicit per-unit config (lower strength) or an exceptions.json entry.
  7. install: GLB asset.extras.homm3DefRetargetEmphasis stamp, atomic replace of C's .blend and .glb
     (after re-checking C's .blend is still the source), renders/stretch/metrics/compare media
     refreshed, glb_verify.json replaced, W/stamp.json written, W/work/ removed.
Proof tier: generated artifact (nothing here is in game).
"""
import argparse, datetime, glob, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emphasis as E  # noqa: E402

ROOT = E.ROOT
RT = f"{ROOT}/tools/homm3_def_retarget"
BLENDER = os.environ.get("BLENDER", "V:/Tools/blender-mcp/blender-5.2.2/blender.exe")
SCHEMA = "homm3_def_retarget_emphasis.stamp.v1"
GLB_EXTRAS_KEY = "homm3DefRetargetEmphasis"
STRETCH_MUL, STRETCH_ADD = 1.6, 40
CHAIN = ["retarget build (tools/homm3_def_retarget/run_unit.sh)",
         "emphasis (this stamp; in place on the canonical .blend/.glb)",
         "idle retime (tools/homm3_idle_cadence/rollout_idle.py, reads the canonical .glb)",
         "unit look (tools/homm3_unit_look/look.py <unit> --force)"]
def defer_last(u):
    """Units another agent is rebuilding (Conflux elementals, the cove nymph line): processed last."""
    return u.endswith("_elemental") or u in ("hota_cove_nymph", "hota_cove_oceanid")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def canon(u):
    c = f"{E.SRC}/{u}"
    return {"dir": c, "blend": f"{c}/{u}_def_retarget.blend", "glb": f"{c}/{u}_def_retarget.glb",
            "renders": f"{c}/renders"}


def wdir(u):
    return f"{E.OUT}/{u}"


def fstat(p):
    """[size, mtime_ns]: lets the validator skip re-hashing an untouched file."""
    st = os.stat(p)
    return [st.st_size, st.st_mtime_ns]


def load_json(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except FileNotFoundError:
        return default


def dump_json(obj, p):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def exceptions():
    return load_json(E.EXCEPTIONS, {"exceptions": {}})["exceptions"]


def roster():
    """Every folder in artifacts/homm3_def_retarget with a canonical <u>_def_retarget.glb."""
    return sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{E.SRC}/*/*_def_retarget.glb")
                  if os.path.basename(p) == os.path.basename(os.path.dirname(p)) + "_def_retarget.glb")


def gate():
    r = subprocess.run([sys.executable, f"{RT}/launch_guard.py"], capture_output=True, text=True)
    log(r.stdout.strip())
    if r.returncode != 0:
        raise SystemExit(f"paused: launch guard refused: {r.stderr.strip()}")


# the processes that hold a unit: Blender itself, bash running a build script, and python running one of the scripts
# that write a unit's .blend / GLB / look (a read-only dry run or validator that merely names the unit does not;
# 2026-09-27 a scratch dry run listing the fleet on its argv deferred worker A's Q10 as busy)
BUILDER_SCRIPTS = ("deliver.py", "fleet_rebuild.py", "look.py", "unit_writer.py", "run_unit.sh", "build_unit.py",
                   "look_queue.py", "deyaw_glb.py", "stride_match_glb.py", "move_lowpass_glb.py",
                   "densify_clip_glb.py", "prop_floor_glb.py", "ground_glb.py", "bake_cs.py", "verify_glb.py")


def is_builder(name: str, cmdline: str) -> bool:
    """A process that can be writing a unit: any Blender, or a python / bash whose command line runs a builder
    script (BUILDER_SCRIPTS, matched on the script's file name)."""
    if re.search(r"blender", name, re.I):
        return True
    if not re.search(r"python|bash", name, re.I):
        return False
    words = re.split(r"[\s\"']+", cmdline.replace("\\", "/"))
    return any(w.rsplit("/", 1)[-1] in BUILDER_SCRIPTS for w in words if w)


def holds(u: str, cmdline: str) -> bool:
    l = cmdline.replace("\\", "/")
    return f"/{u}/" in l or f"/{u}_" in l or f" {u} " in f" {l} " or f",{u}," in f",{l.split()[-1] if l.split() else ''},"


def ancestry(procs: dict, pid: int) -> set:
    """pid and every ancestor (parent, grandparent, ...) in procs {pid: (ppid, name, cmdline)}: the chain that launched
    this deliver (unit_writer -> fleet_rebuild -> deliver) is this build, never a holder of its unit."""
    mine = set()
    while pid in procs and pid not in mine:
        mine.add(pid); pid = procs[pid][0]
    return mine


def holders(u: str, procs: dict, mine: set) -> list[int]:
    """pids of the builder processes (is_builder) other than `mine` whose command line names unit u."""
    return [pid for pid, (_, name, cl) in procs.items() if pid not in mine and is_builder(name, cl) and holds(u, cl)]


def building(u):
    """True when another builder process (a rebuild, look.py, another agent's deliver.py <unit>, Blender) has
    this unit open. This process and its ancestors (the shell that launched it) are not counted."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.Name)`t$($_.CommandLine)\" }"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    procs = {}
    for l in out.splitlines():
        f = l.split("	", 3)
        if len(f) == 4 and f[0].isdigit():
            procs[int(f[0])] = (int(f[1]) if f[1].isdigit() else 0, f[2], f[3])
    if not procs:
        raise SystemExit("building(): the process listing came back empty; cannot tell whether the unit is busy")
    return bool(holders(u, procs, ancestry(procs, os.getpid())))


def blender(args, grep=("EMPH", "VERIFY", "Traceback", "Error")):
    gate()
    if RT not in sys.path:
        sys.path.append(RT)  # appended: that folder holds a Blender review.py that must not shadow others
    from launch_guard import blender_env
    r = subprocess.run([BLENDER, "-b", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=blender_env())
    lines = [l for l in (r.stdout + r.stderr).splitlines() if any(g in l for g in grep)]
    return r.returncode, lines


def clip_stretch(st, a, b):
    return max(st[i][2] for i in range(a, b)), round(max(st[i][0] for i in range(a, b)), 2)


def glb_stamp(src_glb, dst_glb, extras):
    sys.path.insert(0, f"{ROOT}/tools/homm3_unit_look")
    import glbpatch
    g = glbpatch.Glb.load(src_glb)
    g.json.setdefault("asset", {}).setdefault("extras", {})[GLB_EXTRAS_KEY] = extras
    tmp = dst_glb + ".emph.tmp"
    open(tmp, "wb").write(g.to_bytes())
    os.replace(tmp, dst_glb)


def read_glb_extras(p):
    sys.path.insert(0, f"{ROOT}/tools/homm3_unit_look")
    import glbpatch
    return (glbpatch.Glb.load(p).json.get("asset", {}).get("extras") or {}).get(GLB_EXTRAS_KEY)


def refresh_canonical_media(u, blend, rdir, stretch_path):
    """metrics.json + compare gif/mp4 exactly as run_unit.sh makes them (from the installed renders)."""
    c = canon(u)["dir"]
    for p in glob.glob(f"{rdir}/cmp_*.png"):
        os.remove(p)
    subprocess.run([sys.executable, f"{RT}/compose.py", blend, rdir, f"{c}/{u}_compare.gif"], check=True,
                   capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "8", "-i", f"{rdir}/cmp_%03d.png", "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", f"{c}/{u}_compare.mp4"], check=True)
    subprocess.run([sys.executable, f"{RT}/metrics.py", blend, rdir, stretch_path, f"{c}/metrics.json"], check=True,
                   capture_output=True)


SNAP_FILES = ("stretch.json", "metrics.json", "glb_verify.json")


def snapshot(u, src_dir):
    """Pre-emphasis copy of the build; snapshot.json (with the .blend's sha) is written last, so a
    partial snapshot is never taken for a complete one."""
    c = canon(u)
    shutil.rmtree(src_dir, ignore_errors=True)
    os.makedirs(f"{src_dir}/renders")
    shutil.copy2(c["blend"], f"{src_dir}/pre_emphasis.blend")
    shutil.copy2(c["blend"] + ".frames.json", f"{src_dir}/pre_emphasis.blend.frames.json")
    for f in SNAP_FILES:
        shutil.copy2(f"{c['dir']}/{f}", f"{src_dir}/{f}")
    for p in glob.glob(f"{c['renders']}/sprite_*.png") + glob.glob(f"{c['renders']}/side_*.png"):
        shutil.copy2(p, f"{src_dir}/renders/")
    dump_json({"unit": u, "blendSha256": E.sha256_file(f"{src_dir}/pre_emphasis.blend")}, f"{src_dir}/snapshot.json")


def restore_from_source(u, src_dir, stamp):
    """Canonical .blend was emphasised under an older config and is now unchanged: put the pre-emphasis
    build back (blend, renders, stretch, metrics, media) and re-export + verify its GLB."""
    c = canon(u)
    if E.sha256_file(f"{src_dir}/pre_emphasis.blend") != stamp["sourceBlendSha256"]:
        raise RuntimeError(f"{u}: W/source/pre_emphasis.blend does not match its stamp")
    wk = f"{wdir(u)}/work"; shutil.rmtree(wk, ignore_errors=True); os.makedirs(wk)
    wb = f"{wk}/{u}_def_retarget.blend"
    shutil.copy2(f"{src_dir}/pre_emphasis.blend", wb)
    shutil.copy2(f"{src_dir}/pre_emphasis.blend.frames.json", wb + ".frames.json")
    rc, _ = blender([wb, "-P", f"{RT}/export_glb.py", "--", f"{wk}/work.glb"], grep=("EXPORTED", "Error"))
    rc, lines = blender(["--factory-startup", "-P", f"{RT}/verify_glb.py", "--", wb, f"{wk}/work.glb",
                         f"{wk}/glb_verify.json"])
    if not any("VERIFY OK" in l for l in lines):
        raise RuntimeError(f"{u}: restore verify failed {lines[-3:]}")
    if E.sha256_file(c["blend"]) != stamp["emphasisedBlendSha256"]:
        raise RuntimeError(f"{u}: canonical .blend changed during restore; not touched")
    shutil.copy2(wb, c["blend"] + ".emph.tmp"); os.replace(c["blend"] + ".emph.tmp", c["blend"])
    shutil.copy2(f"{wk}/work.glb", c["glb"] + ".emph.tmp"); os.replace(c["glb"] + ".emph.tmp", c["glb"])
    for p in glob.glob(f"{src_dir}/renders/*.png"):
        shutil.copy2(p, c["renders"])
    for f in ("stretch.json",):
        shutil.copy2(f"{src_dir}/{f}", f"{c['dir']}/{f}")
    shutil.copy2(f"{wk}/glb_verify.json", f"{c['dir']}/glb_verify.json")
    refresh_canonical_media(u, c["blend"], c["renders"], f"{c['dir']}/stretch.json")
    shutil.rmtree(wk, ignore_errors=True)


def deliver(u, force=False):
    exc = exceptions()
    if u in exc:
        log(u, "EXCEPTION", exc[u]["reason"])
        return {"unit": u, "decision": "exception", "reason": exc[u]["reason"]}
    c = canon(u); W = wdir(u); src_dir = f"{W}/source"
    os.makedirs(W, exist_ok=True)
    if not os.path.exists(c["blend"]):
        raise RuntimeError(f"{u}: no canonical .blend (add an exceptions.json entry)")
    if building(u):
        log(u, "busy (another process has it open) -> deferred")
        return {"unit": u, "decision": "deferred-busy"}
    cfg = E.load_cfg(u); psha = E.params_sha(cfg)
    stamp = load_json(f"{W}/stamp.json")
    csha = E.sha256_file(c["blend"])
    emphasised_now = bool(stamp and stamp.get("emphasisedBlendSha256") == csha)
    if stamp and not force and stamp.get("paramsSha256") == psha and (
            emphasised_now or (stamp.get("decision") != "emphasised" and stamp.get("sourceBlendSha256") == csha)):
        log(u, "up to date", stamp["decision"])
        return {"unit": u, "decision": "up-to-date", "was": stamp["decision"]}
    if emphasised_now:
        blend, rdir, stretch_p = f"{src_dir}/pre_emphasis.blend", f"{src_dir}/renders", f"{src_dir}/stretch.json"
        ssha = stamp["sourceBlendSha256"]
        if (load_json(f"{src_dir}/snapshot.json") or {}).get("blendSha256") != ssha or E.sha256_file(blend) != ssha:
            raise RuntimeError(f"{u}: W/source/ snapshot incomplete or does not match its stamp")
        verify_src = f"{src_dir}/glb_verify.json"
    else:
        blend, rdir, stretch_p, ssha = c["blend"], c["renders"], f"{c['dir']}/stretch.json", csha
        verify_src = f"{c['dir']}/glb_verify.json"
    ucfg_p = f"{RT}/units/{u}.json"
    det = E.detect(u, blend, rdir, cfg)
    flagged = {k: [x for x in v["keys"] if x["status"] == "underEmphasised"] for k, v in det.items()}
    base = {"schema": SCHEMA, "version": E.VERSION, "unit": u, "paramsSha256": psha, "cfg": cfg,
            "sourceBlendSha256": ssha, "chain": CHAIN, "proof": "generated artifact",
            "appliedAt": datetime.datetime.now().isoformat(timespec="seconds")}
    dump_json(det, f"{W}/detect.json")

    def unchanged(why, extra=None):
        if emphasised_now:
            log(u, "restoring pre-emphasis build")
            restore_from_source(u, src_dir, stamp)
        st = dict(base, decision="unchanged", why=why, clips=summ_clips(det, {}, None, None, None), **(extra or {}))
        st["sourceBlendSha256"] = E.sha256_file(c["blend"]); st["blendStat"] = fstat(c["blend"])
        dump_json(st, f"{W}/stamp.json")
        for p in ("keys_before.npz", "keys_after.npz", "plan.json", "report.json", "actions.json"):
            if os.path.exists(f"{W}/{p}"):
                os.remove(f"{W}/{p}")
        if not emphasised_now:
            shutil.rmtree(src_dir, ignore_errors=True)
        log(u, "unchanged:", why)
        return {"unit": u, "decision": "unchanged", "why": why}

    if not any(flagged.values()):
        return unchanged("no underEmphasised key")
    if not emphasised_now:
        snapshot(u, src_dir)
        if E.sha256_file(f"{src_dir}/pre_emphasis.blend") != csha:
            raise RuntimeError(f"{u}: canonical .blend changed while snapshotting")
    wk = f"{W}/work"; shutil.rmtree(wk, ignore_errors=True); os.makedirs(wk)
    wb = f"{wk}/{u}_def_retarget.blend"
    shutil.copy2(f"{src_dir}/pre_emphasis.blend", wb)
    shutil.copy2(f"{src_dir}/pre_emphasis.blend.frames.json", wb + ".frames.json")
    dump_json(det, f"{wk}/detect.json"); dump_json(cfg, f"{wk}/cfg.json")
    t0 = time.time()
    rc, lines = blender([wb, "-P", f"{HERE}/bl_deliver.py", "--", wk, ucfg_p])
    log(u, "bl_deliver", rc, f"{time.time() - t0:.0f}s", *lines[-3:])
    if any("Traceback" in l for l in lines) or not os.path.exists(f"{wk}/plan.json"):
        raise RuntimeError(f"{u}: bl_deliver failed: {lines[-6:]}")
    pl = json.load(open(f"{wk}/plan.json"))
    if pl["decision"] == "unchanged":
        shutil.rmtree(wk, ignore_errors=True)
        return unchanged("flagged keys all hidden or no articulable bones", {"plan": pl["plan"]})
    if not any("EMPH_DELIVER done" in l for l in lines) or not os.path.exists(f"{wk}/work.glb"):
        raise RuntimeError(f"{u}: bl_deliver did not finish: {lines[-6:]}")
    det = pl["detect"]; info = pl["plan"]
    rc, vl = blender(["--factory-startup", "-P", f"{RT}/verify_glb.py", "--", wb, f"{wk}/work.glb", f"{wk}/glb_verify.json"])
    ver_ok = any("VERIFY OK" in l for l in vl)
    import numpy as np
    kb = dict(np.load(f"{wk}/keys_before.npz")); ka = dict(np.load(f"{wk}/keys_after.npz"))
    errs = E.check_invariants(kb, ka, det, info, cfg)
    if not ver_ok:
        errs.append(f"verify_glb: {vl[-3:]}")
    errs += loop_errors(load_json(verify_src, {}), load_json(f"{wk}/glb_verify.json", {}))
    errs += action_errors(json.load(open(f"{wk}/actions.json")), det, info)
    st0 = json.load(open(stretch_p)); st1 = json.load(open(f"{wk}/stretch_after.json"))
    ratios = {clip: E.ratio_at(u, wb, f"{wk}/renders_after", det[clip]) for clip, i in info.items() if i.get("emphasised")}
    clips = summ_clips(det, info, ratios, st0, st1)
    gate_fail = [k for k, v in clips.items() if v.get("stretchGate") == "fail"]
    report = {"unit": u, "invariantErrors": errs, "verifyOk": ver_ok, "clips": clips, "stretchGateFailed": gate_fail}
    dump_json(report, f"{W}/report.json")
    for f in ("keys_before.npz", "keys_after.npz", "plan.json", "actions.json"):
        shutil.copy2(f"{wk}/{f}", f"{W}/{f}")
    if errs:
        log(u, "INVARIANT/VERIFY ERRORS", errs)
        return {"unit": u, "decision": "failed", "errors": errs}
    if gate_fail:
        log(u, "stretch gate failed", gate_fail)
        # keep the after renders for the review; nothing is installed
        shutil.rmtree(f"{W}/gate_failed_renders", ignore_errors=True)
        shutil.move(f"{wk}/renders_after", f"{W}/gate_failed_renders")
        shutil.rmtree(wk, ignore_errors=True)
        dump_json(dict(base, decision="stretchGateFailed", clips=clips), f"{W}/stamp.json")
        if not emphasised_now:
            shutil.rmtree(src_dir, ignore_errors=True)
        return {"unit": u, "decision": "stretchGateFailed", "clips": gate_fail}
    # ---- install
    esha_blend = E.sha256_file(wb)
    extras = {"schema": SCHEMA, "version": E.VERSION, "unit": u, "paramsSha256": psha,
              "sourceBlendSha256": ssha, "emphasisedBlendSha256": esha_blend,
              "clips": sorted(k for k, v in info.items() if v.get("emphasised")),
              "chain": "retarget build -> emphasis -> idle retime -> unit look"}
    glb_stamp(f"{wk}/work.glb", f"{wk}/stamped.glb", extras)
    if E.sha256_file(c["blend"]) != csha:
        raise RuntimeError(f"{u}: canonical .blend changed during the pass; nothing installed")
    shutil.copy2(wb, c["blend"] + ".emph.tmp"); os.replace(c["blend"] + ".emph.tmp", c["blend"])
    os.replace(f"{wk}/stamped.glb", c["glb"])
    for p in glob.glob(f"{src_dir}/renders/*.png"):
        shutil.copy2(p, c["renders"])
    for p in glob.glob(f"{wk}/renders_after/sprite_*.png") + glob.glob(f"{wk}/renders_after/side_*.png"):
        shutil.copy2(p, c["renders"])
    shutil.copy2(f"{wk}/stretch_after.json", f"{c['dir']}/stretch.json")
    shutil.copy2(f"{wk}/glb_verify.json", f"{c['dir']}/glb_verify.json")
    refresh_canonical_media(u, c["blend"], c["renders"], f"{c['dir']}/stretch.json")
    shutil.rmtree(f"{W}/renders_after", ignore_errors=True)
    shutil.move(f"{wk}/renders_after", f"{W}/renders_after")
    shutil.rmtree(f"{W}/gate_failed_renders", ignore_errors=True)
    stamp = dict(base, decision="emphasised", emphasisedBlendSha256=esha_blend,
                 emphasisedGlbSha256=E.sha256_file(c["glb"]), glbExtras=extras, clips=clips,
                 blendStat=fstat(c["blend"]), glbStat=fstat(c["glb"]),
                 downstream=["tools/homm3_idle_cadence/rollout_idle.py (re-read this GLB)",
                             f"tools/homm3_unit_look/look.py {u} --force"])
    dump_json(stamp, f"{W}/stamp.json")
    shutil.rmtree(wk, ignore_errors=True)
    log(u, "EMPHASISED", {k: v.get("ratiosAfter") for k, v in clips.items() if v.get("emphasised")})
    return {"unit": u, "decision": "emphasised", "clips": [k for k, v in clips.items() if v.get("emphasised")]}


def summ_clips(det, info, ratios, st0, st1):
    out = {}
    for clip, c in det.items():
        i = info.get(clip, {})
        a, b = c["range"]
        e = {"range": [a, b], "suffix": c.get("suffix"), "emphasised": bool(i.get("emphasised")),
             "keys": [{k: x.get(k) for k in ("frame", "basis", "ratio", "status", "gain")} for x in c["keys"]],
             "fxMasked": c.get("fxMasked"), "defFxPixels": c.get("defFxPixels")}
        if i.get("emphasised"):
            e["ratiosAfter"] = ratios[clip]
            e["contactChains"] = i.get("contactChains", [])
            e["maxExtraDeg"] = max(i["extraDegPerFrameMax"])
            w0, m0 = clip_stretch(st0, a, b); w1, m1 = clip_stretch(st1, a, b)
            e["edges2xWorstFrame"] = [w0, w1]; e["maxStretch"] = [m0, m1]
            e["stretchGate"] = "fail" if w1 > max(STRETCH_MUL * w0, w0 + STRETCH_ADD) else "pass"
        out[clip] = e
    return out


def loop_errors(v0, v1):
    """Idle/Move are never rewritten (action_errors, check_invariants); here: they still close their
    loops in the new round trip. v0 (the build's own glb_verify.json) can predate the .blend, so it is
    only reported, never compared."""
    err = []
    for a in ("Unit_Idle", "Unit_Move"):
        if a in v1 and v1[a].get("lastMinusFirst", 1) > 1e-4:
            err.append(f"{a} does not close its loop: {v1[a]}")
    return err


def action_errors(actions, det, info):
    """Only Unit_ actions whose master range lies inside an emphasised clip may be rewritten."""
    err = []
    rngs = [det[c]["range"] for c, i in info.items() if i.get("emphasised")]
    for name, r in actions.items():
        if isinstance(r, dict) and r.get("rewritten"):
            s = r["masterStart"]
            if not any(a <= s < b for a, b in rngs):
                err.append(f"{name} rewritten but its range starts outside an emphasised clip")
            if name in ("Unit_Idle", "Unit_Move"):
                err.append(f"{name} rewritten")
    return err


def summary():
    rows, exc = [], exceptions()
    for u in roster():
        if u in exc:
            rows.append({"unit": u, "decision": "exception", "reason": exc[u]["reason"]}); continue
        st = load_json(f"{wdir(u)}/stamp.json")
        if not st:
            rows.append({"unit": u, "decision": "pending"}); continue
        r = {"unit": u, "decision": st["decision"], "paramsSha256": st["paramsSha256"][:12]}
        if st["decision"] in ("emphasised", "stretchGateFailed"):
            r["clips"] = {k: {"keys": [(x["frame"], x["ratio"]) for x in v["keys"] if x["status"] == "underEmphasised"],
                              "after": v.get("ratiosAfter"), "edges2x": v.get("edges2xWorstFrame"),
                              "maxStretch": v.get("maxStretch"), "maxExtraDeg": v.get("maxExtraDeg")}
                          for k, v in st["clips"].items() if v.get("emphasised")}
        rows.append(r)
    cnt = {}
    for r in rows:
        cnt[r["decision"]] = cnt.get(r["decision"], 0) + 1
    out = {"schema": "homm3_def_retarget_emphasis.roster.v1", "version": E.VERSION,
           "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"), "counts": cnt, "units": rows}
    dump_json(out, f"{E.OUT}/roster_summary.json")
    print(json.dumps(cnt))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--roster", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.summary:
        summary(); return
    units = a.units
    if a.roster:
        rs = roster()
        units = [u for u in rs if not defer_last(u)] + [u for u in rs if defer_last(u)]
    results = []
    queue = list(units); retried = set()
    while queue:
        u = queue.pop(0)
        try:
            results.append(deliver(u, a.force))
        except SystemExit:
            raise
        except Exception as ex:  # noqa: BLE001  (one unit's fault is reported, the batch continues)
            log(u, "ERROR", repr(ex))
            results.append({"unit": u, "decision": "error", "error": repr(ex)})
            shutil.rmtree(f"{wdir(u)}/work", ignore_errors=True)
        with open(f"{E.OUT}/deliver_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(results[-1], at=datetime.datetime.now().isoformat(timespec="seconds"))) + "\n")
        if results[-1]["decision"] == "deferred-busy" and u not in retried:
            retried.add(u); queue.append(u)            # one retry at the end of the batch
    print(json.dumps(results, indent=1))
    return not_done_exit(results)


# decisions that leave a unit's emphasis step not done: a caller (fleet_rebuild.py) must fail, never read exit 0 as OK
# (2026-09-28: a busy check matched another agent's shell wrappers, deliver returned "deferred-busy" and the rebuild
# counted the step as rc 0 / OK). A unit's last result counts, so a deferred unit that ran on its retry is done.
NOT_DONE = ("deferred-busy", "error", "failed")
NOT_DONE_EXIT = 2


def not_done_exit(results) -> int:
    last = {r["unit"]: r for r in results}
    bad = [r for r in last.values() if r["decision"] in NOT_DONE]
    for r in bad:
        print(f"DELIVER NOT DONE {r['unit']}: {r['decision']}"
              + (f" {r.get('error') or r.get('errors')}" if r["decision"] != "deferred-busy" else ""),
              file=sys.stderr, flush=True)
    return NOT_DONE_EXIT if bad else 0


if __name__ == "__main__":
    sys.exit(main())
