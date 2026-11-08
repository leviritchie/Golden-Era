"""Re-bake a census `rebuild_then_ship` unit on the current corrective-smooth baker, then re-apply its look.

    python tools/homm3_def_retarget_delivery/fleet_rebuild.py <unit> [<unit> ...]

Only the existing unit tools run; this file sequences them and records the outcome. Route per unit:

  a fresh build under a stale "emphasised" stamp (stale_emphasis_stamp: neither the .blend nor the GLB is the
  stamp's): the direct re-bake below (its plain deliver plans against this build)
  emphasised (emphasis stamp decision "emphasised"):
      tools/homm3_def_retarget_emphasis/deliver.py <u> --force
      (re-plans from the pre-emphasis snapshot W/source/ and re-bakes through the shared bake_cs.py)
  first, when the build's weights (<blend>.weights.npz) have non-finite rows (built before surface_weights.py's
  component seeding; those vertices export to neutral_bone and export_glb.py refuses the skin):
      tools/homm3_def_retarget/run_unit.sh <u>                          (full build: heat, surface_weights, build)
      then the direct re-bake below (deliver snapshots the fresh build)
  otherwise (unchanged / exception / no stamp) and the unit config does not disable the bake:
      blender -b <canonical .blend> -P tools/homm3_def_retarget/bake_cs.py -- <iterations> <factor>
      RENDER_ONLY=1 tools/homm3_def_retarget/run_unit.sh <u>        (renders, stretch, metrics, GLB export)
      blender -b -P tools/homm3_def_retarget/verify_glb.py            (must print VERIFY OK -> glb_verify.json)
      tools/homm3_def_retarget_emphasis/deliver.py <u>                (skipped for exceptions.json units; a
      deferred-busy / error / failed emphasis step exits non-zero and fails the rebuild, named in the report)
  then the delivery stages, in this process on the GLB's bytes (fused_delivery_stages; each stage's CLI runs the same
  apply_bytes on the file): the glb patch (tools/homm3_glb_patch/patch_glb.py apply <u>, exit 3 = no "glbPatch"), then,
  for a unit whose config turns the body for the DEF fit (castle_yaw / necropolis_yaw yawDeg):
      tools/homm3_def_retarget_delivery/deyaw_glb.py <u>              (the turn comes back out for delivery)
  then always:
      tools/homm3_def_retarget_delivery/stride_match_glb.py apply <u>   (exit 3 = HoMM3 flier or strideExempt, skipped)
      tools/homm3_def_retarget_delivery/move_lowpass_glb.py apply <u>   (exit 3 = no "moveLowPass", skipped)
      tools/homm3_def_retarget_delivery/densify_clip_glb.py apply <u>   (exit 3 = no "deliveryDensify", skipped)
      tools/homm3_def_retarget_delivery/prop_floor_glb.py apply <u>     (exit 3 = no "propFloor", skipped)
      tools/homm3_def_retarget_delivery/cs_rekey_glb.py (in process only: the CS_ targets of every pose the stages above
        re-keyed, re-baked in numpy at the delivered pose against the post-patch export; skipped without CS_ targets)
      tools/homm3_def_retarget_delivery/ground_glb.py apply <u>         (feet / dead body onto the DEF floor; stamps)
      (in-memory stage fusion, docs/homm3_glb_patch_lane.md: every stage parses its input bytes and returns the exact
       bytes its CLI would write; its sidecar records that sha pair, so the chain links as when each stage rewrote the
       canonical GLB. The sidecars are written after the last stage, then the GLB once: the pre-look GLB here, which
       look.py reads, or on --from-base nothing -- look apply takes the bytes in process and writes the delivery)
      tools/homm3_unit_look/look.py <u> --stages bake,fit,vfx,review, then look.py <u> --stages finish,apply
        (review judges the fitted look against the DEF before the finish, as the look-B rollout did: look B is the
         user-approved departure from the DEF, so it is not reviewed against it; deliver_graded_look)
        (no --force since 2026-10-05: --force wipes work/, and the terms bake (~45 s) is keyed on the content of the
         .blend's bake inputs (look.terms_input_hash), so a rebuild that leaves the rest mesh alone reuses it; views
         still rebake whenever the .blend changes, and fit / vfx / review always rerun)
        (a rawAccepted look stamp instead: look.py <u> --try-modes; --stages bake,fit,vfx,review; --accept-raw
         "<prior reason> | fleet_rebuild <date>: <this GLB's numbers>" -- look.py's raw-beats-every-mode rule decides;
         a superseded raw takes --stages finish,apply on the bake just reviewed)
      (look --prune-superseded is not here: it runs last of all, after the idle rollout, on a passing unit only)
  last, pass or fail: chain_errors -- the canonical GLB must be the look's delivery of this run's export through the
      stamped stages (validate_homm3_def_retarget_emphasis_contract.delivery_chain_errors); a broken link fails the unit
      and names it (e.g. a stage rewrote the GLB and the run stopped before look re-ran).
  no regression: gate_faults (freeze_check, ground_check, the Unit_Move articulation gate) on the snapshot's GLB and on
      the new one; a fault the new GLB has and the delivered one did not fails the unit, and the transaction restores.
  idle cadence: a passing unit then runs tools/homm3_idle_cadence/rollout_idle.py <u> so the retimed idle follows the
      new delivery (validate_homm3_idle_cadence_contract otherwise reports it STALE); a refusal fails and restores.
  prune, last: tools/homm3_unit_look/look.py <u> --prune-superseded (keeps only the stamp's source original) runs only
      after every step that can fail has passed. The transaction does not snapshot _superseded_do_not_use/, so a prune
      before a failing step deleted the original the restored look stamp points at (2026-10-09 h3_peasant: the idle
      rollout refused after the prune, and the restored stamp's fdf3852dce0e.glb.unprebaked was gone). A prune that
      fails is recorded (rec["prune"]) and does not fail the delivered unit; the next run prunes again.
  transaction: before the run, the delivered state (delivered_paths: canonical GLB, its delivery-stage sidecars,
      glb_verify.json, the emphasis stamp, the look's stamp / metrics / textures / VFX manifest, and the patch base
      artifacts/homm3_glb_patch/<u>/, which the run re-retains right after its export) is snapshotted under
      _fleet_logs/_txn/<u>/; a unit that fails (a refused stage, a crash, a broken chain) gets exactly that state back,
      byte for byte, and the record says so (rec["restore"]). A refused stage never leaves a half-delivered GLB. Not
      restored: the .blend and its build companions, renders and look work files (build inputs and scratch, not the
      delivery; the next rebuild starts from them again), and _superseded_do_not_use/ (only ever added to before the prune,
      which runs only once the unit has passed). A standalone run_unit.sh <u> takes that snapshot itself before it
      writes anything (--pre-run-snapshot; its export is recorded with --pre-run-export), and the run that follows
      adopts it while it still describes the delivered state (adopt_pre_run), so a failure restores the previous
      delivery rather than run_unit's raw export (2026-10-09 h3_sharpshooter).

Blender-free route (docs/homm3_glb_patch_lane.md): fleet_rebuild.py --from-base <unit> [...] restores the patch base
(tools/homm3_glb_patch/base.py: the export, its emphasis stamp and glb_verify.json, retained by every full run above
right after its export) and runs only the numpy stages: glb patch, the "then always" stages, look.py --stages apply
(the stamped texture; refuses a geometry change) and the idle rollout, under the same transaction and gates. A missing
or stale base (the .blend rebuilt since) and a rawAccepted look refuse. The glb patch stage (patch_glb.py apply, exit 3 =
no "glbPatch") runs first after the export in every route. The route writes one GLB: the base comes back as bytes, the
stages and look apply (look.run_unit(glb_bytes=...)) run in process, and look apply writes the delivered GLB by tmp +
os.replace -- so the transaction snapshot hard-links the canonical GLB and the look images (their pre-run inode is the
restore point) instead of copying them; the JSONs, which are rewritten in place, are copied.

launch_guard runs before every Blender launch this file starts (deliver.py and look.py gate their own).
The morph extent (slice gate MORPH_DELTA_MAX_HEIGHT_RATIO) is measured before and after and written to
artifacts/homm3_def_retarget_delivery/_fleet_logs/rebuild_<u>.json. Exit 1 if any unit failed.
Proof tier: generated artifact.
"""
from __future__ import annotations

import contextlib
import datetime
import gc
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fleet_census import MORPH_DELTA_MAX_HEIGHT_RATIO, ROOT, morph_extent, verify_status, load  # noqa: E402
sys.path.append(str(ROOT / "tools/homm3_def_retarget"))
from launch_guard import blender_env  # noqa: E402
sys.path.append(str(ROOT / "tools"))
from validate_homm3_def_retarget_emphasis_contract import DELIVERY_STAGES, delivery_chain_errors  # noqa: E402
sys.path.append(str(ROOT / "tools/homm3_unit_look"))
from spec import RAW_ACCEPTED  # noqa: E402
import importlib.util  # noqa: E402
_pb = importlib.util.spec_from_file_location("homm3_glb_patch_base", ROOT / "tools/homm3_glb_patch/base.py")
patch_base = importlib.util.module_from_spec(_pb)
_pb.loader.exec_module(patch_base)
FROM_BASE = [False]   # --from-base: the Blender-free route (docs/homm3_glb_patch_lane.md)

BLENDER = os.environ.get("BLENDER", "V:/Tools/blender-mcp/blender-5.2.2/blender.exe")
BASH = os.environ.get("BASH_EXE", "C:/Program Files/Git/bin/bash.exe")
RT = ROOT / "tools/homm3_def_retarget"
LOGS = ROOT / "artifacts/homm3_def_retarget_delivery/_fleet_logs"


def sha(p) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_glb_json(p: Path) -> dict:
    with open(p, "rb") as f:
        head = f.read(20)
        return json.loads(f.read(struct.unpack("<I", head[12:16])[0]))


def run(cmd, log: Path, env=None, timeout=3600) -> int:
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n")
        f.flush()
        return subprocess.run([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode


@contextlib.contextmanager
def logged(log: Path, cmd: str):
    """An in-process step's output into the unit's log, as run() sends a subprocess's: file descriptors 1 and 2 (so
    prints, tracebacks and the step's own child processes all land there), under a "$ <cmd>" header."""
    sys.stdout.flush()
    sys.stderr.flush()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n$ {cmd}\n")
        f.flush()
        saved = os.dup(1), os.dup(2)
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])


def in_process(log: Path, cmd: str, fn):
    """Run fn() in this process with its output in the log; (rc, result) with the exit code its CLI would have had: 0,
    a SystemExit's int code (its message: 1, printed as the interpreter prints it), 1 for any other exception."""
    with logged(log, cmd):
        try:
            return 0, fn()
        except SystemExit as e:
            if e.code is None or isinstance(e.code, int):
                return e.code or 0, None
            print(e.code, file=sys.stderr)
            return 1, None
        except Exception:  # noqa: BLE001  (the traceback is the log's record, the step fails)
            traceback.print_exc()
            return 1, None


def delivery_stage_modules() -> dict:
    """The delivery stages' modules (imported on first use; each stage's CLI is the same module's main())."""
    if str(ROOT / "tools/homm3_glb_patch") not in sys.path:
        sys.path.append(str(ROOT / "tools/homm3_glb_patch"))
    import cs_rekey_glb, deyaw_glb, densify_clip_glb, ground_glb, move_lowpass_glb, patch_glb, prop_floor_glb, stride_match_glb  # noqa: E401
    return {"patch": patch_glb, "deyaw": deyaw_glb, "stride_match": stride_match_glb, "move_lowpass": move_lowpass_glb,
            "densify": densify_clip_glb, "prop_floor": prop_floor_glb, "cs_rekey": cs_rekey_glb, "ground": ground_glb}


def launch_guard(log: Path) -> None:
    if run([sys.executable, RT / "launch_guard.py"], log, timeout=60) != 0:
        raise RuntimeError(f"launch guard refused Blender; see {log}")


def stale_emphasis_stamp(stamp: dict, blend_sha: str, glb_sha: str, glb_extras: dict) -> bool:
    """An "emphasised" emphasis stamp that describes neither the canonical build nor its GLB: the .blend is neither the
    stamp's emphasised build nor its source, and the GLB is neither the stamp's emphasised export nor carries emphasis
    extras. A plain run_unit build replaced the canonical after the stamp (2026-09-28 hota_bulwark_steel_elf: a raw
    00:05 build under a 09-27 "emphasised" stamp with no W/source/ snapshot), so the canonical is a fresh build: it
    takes the direct re-bake, whose plain deliver plans against this build. emphasis_redeliver would re-emphasise a
    build the stamp never saw and, on a stretch-gate refusal, find no pre-emphasis snapshot to restore."""
    return (stamp.get("decision") == "emphasised"
            and blend_sha not in {stamp.get("emphasisedBlendSha256"), stamp.get("sourceBlendSha256")}
            and glb_sha != stamp.get("emphasisedGlbSha256")
            and "homm3DefRetargetEmphasis" not in glb_extras)


def stale_weight_rows(blend: Path) -> int:
    """Rows of the build's weights (<blend>.weights.npz W, what build_unit.py skinned the .blend with) that are not
    finite: vertices the exporter binds to neutral_bone. 0 when the file is absent (a build that predates it)."""
    import numpy as np
    wp = Path(str(blend) + ".weights.npz")
    if not wp.is_file():
        return 0
    with np.load(wp) as d:
        return int((~np.isfinite(d["W"])).any(1).sum())


def rebuild(u: str, rec: dict) -> dict:
    log = LOGS / f"rebuild_{u}.log"
    log.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} rebuild {u}\n", encoding="utf-8")
    C = ROOT / "artifacts/homm3_def_retarget" / u
    glb, blend = C / f"{u}_def_retarget.glb", C / f"{u}_def_retarget.blend"
    cfg = load(RT / "units" / f"{u}.json") or {}
    stamp = load(ROOT / "artifacts/homm3_def_retarget_emphasis" / u / "stamp.json") or {}
    exc = load(ROOT / "tools/homm3_def_retarget_emphasis/exceptions.json")["exceptions"]
    rec.update({"unit": u, "startedAt": datetime.datetime.now().isoformat(timespec="seconds"),
                "morphBefore": morph_extent(glb), "steps": []})
    t0 = time.time()
    heat = Path(str(blend) + ".heat.npz")
    if heat.is_file() and blend.stat().st_mtime < heat.stat().st_mtime:
        # run_unit.sh writes .heat.npz in pass 1 and the .blend at the end of pass 2: a .blend older than its heat is a
        # failed pass 2 whose earlier .blend would be re-baked and recorded as this build (2026-09-27 stormbird/paokai)
        raise RuntimeError(f"{blend.name} is older than {heat.name}: the last run_unit build did not save; rebuild it")

    def fresh(p: Path, since: float, what: str):
        if not p.is_file() or p.stat().st_mtime < since:
            raise RuntimeError(f"{what}: {p.name} was not written by this step; see {log}")

    def step(name, rc):
        rec["steps"].append({"step": name, "rc": rc})
        if rc != 0:
            raise RuntimeError(f"{name} rc={rc}; see {log}")

    cs = cfg.get("correctiveSmooth", {})
    W = ROOT / "artifacts/homm3_def_retarget_emphasis" / u

    def deliver_step(name, extra):
        """deliver.py exits non-zero when the emphasis step was not done (deferred-busy, error, failed): the rebuild
        fails and names deliver's own reason (its "DELIVER NOT DONE" line), never counts the step as OK."""
        mark = log.stat().st_size if log.exists() else 0
        rc = run([sys.executable, ROOT / "tools/homm3_def_retarget_emphasis/deliver.py", u] + extra, log)
        rec["steps"].append({"step": name, "rc": rc})
        if rc != 0:
            with log.open("rb") as f:
                f.seek(mark)
                why = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.startswith("DELIVER NOT DONE")]
            rec["emphasisNotDone"] = why[-1] if why else None
            raise RuntimeError(f"{name} rc={rc}: {why[-1] if why else 'no DELIVER NOT DONE line'}; see {log}")

    def direct_rebake():
        launch_guard(log)
        ts = time.time()
        step("bake_cs", run([BLENDER, "-b", "--python-exit-code", "1", blend, "-P", RT / "bake_cs.py", "--",
                             cs.get("iterations", 30), cs.get("factor", 0.7),
                             ",".join(cs.get("excludeBones", []))], log, env=blender_env()))
        fresh(blend, ts, "bake_cs")
        env = dict(os.environ, RENDER_ONLY="1")
        ts = time.time()
        step("run_unit RENDER_ONLY", run([BASH, (RT / "run_unit.sh").as_posix(), u], log, env=env))
        fresh(glb, ts, "run_unit RENDER_ONLY")
        launch_guard(log)
        vj = C / "glb_verify.json"
        rc = run([BLENDER, "-b", "--python-exit-code", "1", "--factory-startup", "-P", RT / "verify_glb.py", "--", blend, glb, vj], log, env=blender_env())
        if "VERIFY OK" not in log.read_text(encoding="utf-8", errors="replace").split("verify_glb.py")[-1]:
            raise RuntimeError(f"verify_glb did not print VERIFY OK; see {log}")
        step("verify_glb", rc)
        if u not in exc:
            deliver_step("deliver", [])
            rec["emphasisDecision"] = (load(W / "stamp.json") or {}).get("decision")

    def restore_pre_emphasis() -> bool:
        """Canonical .blend is an emphasised build (GLB extras name it) whose re-emphasis was refused: put the
        pre-emphasis snapshot back, so the direct re-bake + deliver re-plans against a baseline on the same bake."""
        snap, pre = load(W / "source/snapshot.json") or {}, W / "source/pre_emphasis.blend"
        js = read_glb_json(glb)
        extras = js.get("asset", {}).get("extras", {}).get("homm3DefRetargetEmphasis") or {}
        if not pre.is_file() or extras.get("emphasisedBlendSha256") != sha(blend):
            return False
        if sha(pre) != snap.get("blendSha256") or extras.get("sourceBlendSha256") != snap.get("blendSha256"):
            raise RuntimeError("pre-emphasis snapshot does not match the emphasised build's source")
        shutil.copy2(pre, str(blend) + ".fleet.tmp")
        os.replace(str(blend) + ".fleet.tmp", blend)
        shutil.copy2(W / "source/pre_emphasis.blend.frames.json", str(blend) + ".frames.json")
        rec["restoredPreEmphasis"] = snap["blendSha256"]
        return True

    stale = 0 if FROM_BASE[0] else stale_weight_rows(blend)
    data = None   # the export the delivery stages start from, in memory
    if FROM_BASE[0]:
        # the retained export state (tools/homm3_glb_patch/base.py) instead of any Blender step: every stage from here
        # on is numpy, and the look re-delivers its stamped texture (geometry unchanged by construction). The base
        # comes back as bytes; the canonical GLB is written once, by look apply
        rec["route"] = "from_base"
        rec["base"], data = patch_base.restore(u)
    elif stale:
        # the .blend was built from weight rows surface_weights.py left NaN (a welded component unreachable along the
        # surface, fixed 2026-09-28): those vertices export unweighted to glTF's neutral_bone and export_glb.py refuses
        # the skin. Re-baking or re-emphasising that .blend (or its pre-emphasis snapshot) re-exports the same rows, so
        # the build itself is redone (run_unit.sh re-runs build_heat + surface_weights + build), then the direct
        # re-bake; deliver sees a fresh build and snapshots it (2026-09-28 h3_pit_spawn: 217 rows)
        rec["route"] = "stale_weights_rebuild"
        rec["staleWeightRows"] = stale
        ts = time.time()
        env = {k: v for k, v in os.environ.items() if k != "RENDER_ONLY"}
        step("run_unit full build", run([BASH, (RT / "run_unit.sh").as_posix(), u], log, env=env, timeout=7200))
        fresh(blend, ts, "run_unit full build")
        fresh(glb, ts, "run_unit full build")
        left = stale_weight_rows(blend)
        if left:
            raise RuntimeError(f"run_unit full build still wrote {left} non-finite weight rows; see {log}")
        direct_rebake()
    elif cs is not False and u not in exc and stale_emphasis_stamp(
            stamp, sha(blend), sha(glb), read_glb_json(glb).get("asset", {}).get("extras") or {}):
        rec["route"] = "fresh_build_stale_emphasis_stamp"
        direct_rebake()
    elif stamp.get("decision") == "emphasised" and u not in exc:
        rec["route"] = "emphasis_redeliver"
        deliver_step("deliver --force", ["--force"])
        st = load(W / "stamp.json") or {}
        rec["emphasisDecision"] = st.get("decision")
        if st.get("appliedAt", "") < rec["startedAt"]:
            raise RuntimeError(f"deliver did not write a fresh stamp (decision {st.get('decision')}); see {log}")
        if st.get("decision") == "stretchGateFailed":
            # the gate compared the re-baked emphasis against the old bake's stretch: re-bake the baseline first
            if not restore_pre_emphasis():
                raise RuntimeError("stretch gate failed and the canonical build is not a restorable emphasised build")
            rec["route"] = "emphasis_gate_failed_restore_rebake"
            direct_rebake()
        elif st.get("decision") != "emphasised":
            rec["route"] = "emphasis_unchanged"   # deliver restored + re-exported the pre-emphasis build: re-bake it
            direct_rebake()
    elif cs is False:
        rec["route"] = "bake_disabled"
    else:
        rec["route"] = "direct_rebake"
        if restore_pre_emphasis():
            rec["route"] = "restore_rebake"
        direct_rebake()
    # the delivery chain starts here: every later GLB edit must link back to this export (chain_errors)
    if data is None:
        data = glb.read_bytes()
    rec["deliveryBaseGlbSha256"] = sha_bytes(data)
    if rec["route"] not in ("from_base", "bake_disabled"):
        # keep this export (and the stamps that describe it) so a later localized fix needs no Blender
        rec["patchBaseRetainedAt"] = patch_base.retain(u, rec["route"])["retainedAt"]
    held, data = [data], None   # handed over, so the export's bytes are freed once the first stage has replaced them
    cur = fused_delivery_stages(u, rec, held, cfg, log, step)
    LOOK = ROOT / "tools/homm3_unit_look/look.py"

    def look_step(name, args, env=None):
        rc = run([sys.executable, LOOK, u, *args], log, env=env, timeout=7200)
        tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
        step(name, 0 if (rc == 0 and f"STATUS {u} ok" in tail) else (rc or 1))

    prior = load(ROOT / "artifacts/homm3_unit_look" / u / "stamp.json") or {}
    if prior.get("kind") == RAW_ACCEPTED and FROM_BASE[0]:
        raise RuntimeError("--from-base cannot re-earn a rawAccepted look (look.py --try-modes re-bakes in Blender); "
                           "run the full chain")
    if FROM_BASE[0]:
        # the patch lane never changes POSITION / TEXCOORD_0 / indices / images (patch_glb.py checks), so look's own
        # geometry-unchanged path re-delivers the stamped base colour; it refuses if the geometry did change. In process
        # on the last stage's bytes (look.py --stages apply, the GLB in memory): look apply writes the delivered GLB,
        # the one GLB this route writes
        import look as LK
        with logged(log, f"{sys.executable} {LOOK} {u} --stages apply  (in process, the pre-look GLB in memory)"):
            code = LK.run_unit(u, ["apply"], glb_bytes=cur)
            print(f"STATUS {u} {'ok' if code == 0 else f'exit {code}'}", flush=True)
        step("look --stages apply", code)
        rec["look"] = "stamped texture re-applied"
    elif prior.get("kind") == RAW_ACCEPTED:
        # a rawAccepted look delivers the un-prebaked GLB: look.py --force would regrade it and refuse (exit 5, raw
        # beats every mode), so the rebuilt GLB re-earns the raw delivery the way it first did. look.py's own rule
        # (raw strictly below every mode, each fitted on this GLB) stays the gate; a refusal restores the transaction.
        look_step(*LOOK_TRY_STEP)
        look_step(*LOOK_REVIEW_STEP)
        # 2026-10-01 hota_cove_ayssid: raw is a measurement on the GLB it was earned on. A rebuild (new geometry,
        # motion) can let a grade win, and --accept-raw then refuses (exit 5) on every rebuild. The decision is re-made
        # here on the same numbers look.py's own rule reads: raw still below every mode -> re-earn it; the spec's own
        # mode now at or below raw -> the applied look (look --stages apply on the bake just reviewed; --force would
        # rebake and re-measure inside the noise), recorded as superseding the raw decision;
        # anything else (another mode wins, the spec's does not) refuses, naming the numbers.
        verdict, why = raw_verdict(ROOT / "artifacts/homm3_unit_look" / u, u)
        if verdict == "raw":
            look_step("look --accept-raw", ["--accept-raw", accept_raw_reason(prior, ROOT / "artifacts/homm3_unit_look" / u)])
            rec["look"] = "rawAccepted re-earned"
        elif verdict == "applied":
            print(f"LOOK {u}: rawAccepted superseded on the rebuilt GLB: {why}", flush=True)
            # the bake just reviewed, not a rebake; then look B as every graded look. The stamp is still rawAccepted
            # until this apply, so look.py's finish is told this unit's fit supersedes the raw delivery
            look_step(*LOOK_FINISH_STEP, env={**os.environ, "HOMM3_LOOK_SUPERSEDE_RAW": u})
            rec["look"] = f"rawAccepted superseded by the applied look: {why}"
        else:
            raise RuntimeError(f"rawAccepted cannot be re-earned and the spec's own mode does not beat raw: {why}; "
                               f"set the look spec's lighting.mode or re-review the unit's look")
    else:
        deliver_graded_look(look_step)
    del cur
    # the look delivered; the prune of superseded originals waits for main() (after the idle rollout, passing units only)
    rec["steps"].append({"step": LOOK_DELIVERED_STEP, "rc": 0})
    rec["morphAfter"] = morph_extent(glb)
    rec["verify"] = verify_status(u)
    rec["seconds"] = round(time.time() - t0)
    ratio = rec["morphAfter"]["ratio"]
    rebaked = rec["route"] != "emphasis_redeliver" or rec.get("emphasisDecision") == "emphasised"
    rec["ok"] = rebaked and rec["verify"]["status"] == "ok" and ratio is not None and ratio <= MORPH_DELTA_MAX_HEIGHT_RATIO
    return rec


def fused_delivery_stages(u: str, rec: dict, held: list, cfg: dict, log: Path, step) -> bytes:
    """The delivery stages on the export's bytes, in this process: glb patch, deyaw (a castle_yaw / necropolis_yaw unit),
    stride match, Move low-pass, densify, prop floor, CS re-key, ground -- the order of DELIVERY_STAGES. Each stage's apply_bytes
    parses its input bytes and returns the bytes its CLI writes (stage_sidecar.StageResult; None = not opted in, the
    CLI's exit 3), so every sidecar's sha link is those bytes' own. After the last stage the sidecars are written, then
    the GLB once: here in the full routes (look.py reads it from disk), not at all on --from-base (look apply in process
    takes the returned bytes and writes the delivered GLB). A refused stage writes nothing (fail closed).
    held: [the export's bytes], emptied here so no caller keeps them alive. Returns the pre-look GLB's bytes."""
    import stage_sidecar
    M = delivery_stage_modules()
    glb = M["ground"].canonical_glb(u)
    cur, done = held.pop(), []

    def fused(name, key, cli, fn, skipped=None):
        nonlocal cur
        src = cur
        rc, res = in_process(log, f"{sys.executable} {cli} {u}  (in process, the GLB in memory)", lambda: fn(src))
        gc.collect()   # a stage's parsed GLB sits in reference cycles: free it now, not at the next stage's peak
        if rc == 0 and res is None and skipped is not None:
            rec[key] = skipped
            return
        step(name, rc)
        if res is None or res.source_sha != sha_bytes(src):
            raise RuntimeError(f"{name}: the stage's result does not start from the previous stage's bytes")
        if Path(res.sidecar["outputGlb"]).resolve() != glb.resolve():
            raise RuntimeError(f"{name}: the stage names {res.sidecar['outputGlb']} as its output, not {glb}")
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res.report, default=str) + "\n")
        done.append(res._replace(data=None))   # the sidecar is kept, the bytes only while they are the current GLB
        cur = res.data
        if key:
            rec[key] = "applied"

    def stride(b):
        res, skip = M["stride_match"].apply_bytes(M["stride_match"].build_parser().parse_args(["apply", u]), b)
        if res is None:
            print(json.dumps(skip, default=str))
        return res

    # glbPatch (tools/homm3_glb_patch/patch_glb.py): the unit config's numpy skin / track patch on the export, the first
    # delivery stage so every later one measures the patched body; None = no "glbPatch"
    fused("glb patch apply", "glbPatch", ROOT / "tools/homm3_glb_patch/patch_glb.py apply",
          lambda b: M["patch"].apply_bytes(u, b, M["patch"].canonical_glb(u)), "skipped: no glbPatch")
    ref = cur   # the bytes the pose-editing stages start from (the patch re-bakes its own targets): cs_rekey's reference
    if cfg.get("yawDeg") and {"castle_yaw", "necropolis_yaw"} & set(cfg.get("extensions", [])):
        # the fit's body turn comes back out for delivery, on the freshly exported (pre-look) GLB
        fused("deyaw", None, HERE / "deyaw_glb.py", lambda b: M["deyaw"].deyaw_bytes(u, b, M["deyaw"].canonical_glb(u)))
        rec["deyawed"] = cfg["yawDeg"]
    # stride match (docs/homm3_stride_match.md): lengthen Move's steps to OE's ground speed, before the look
    fused("stride_match apply", "strideMatch", HERE / "stride_match_glb.py apply", stride,
          "skipped: HoMM3 flier or strideExempt (reference/homm3_fliers.json, unit config)")
    # Move low-pass for fliers / strideExempt units (move_lowpass_glb.py): config "moveLowPass"
    fused("move_lowpass apply", "moveLowPass", HERE / "move_lowpass_glb.py apply",
          lambda b: M["move_lowpass"].apply_bytes(u, b, M["move_lowpass"].canonical_glb(u)), "skipped: no moveLowPass")
    # key densify (densify_clip_glb.py): only units whose config opts in with "deliveryDensify"
    fused("densify apply", "densify", HERE / "densify_clip_glb.py apply",
          lambda b: M["densify"].apply_bytes(u, b, M["densify"].canonical_glb(u)), "skipped: no deliveryDensify")
    # prop floor (prop_floor_glb.py): a rigid hand prop tilted out of the floor on its own bone, so the ground stage
    # does not lift the whole body for it; only units whose config opts in with "propFloor"
    fused("prop_floor apply", "propFloor", HERE / "prop_floor_glb.py apply",
          lambda b: M["prop_floor"].apply_bytes(u, b, glb), "skipped: no propFloor")
    # CS re-key (cs_rekey_glb.py, docs/homm3_cs_bake_float64.md): every CS_ target whose pose a stage above changed
    # (beyond one rigid motion) is re-baked in numpy at the delivered pose, and the bake record says so per clip; after
    # the last non-rigid pose edit, before ground (a whole-body translation, under which CS is invariant)
    fused("cs_rekey apply", "csRekey", HERE / "cs_rekey_glb.py",
          lambda b: M["cs_rekey"].apply_bytes(u, b, ref, glb), "skipped: no CS_ morph targets")
    del ref
    # ground (ground_glb.py, grounding.offsets): whole-body vertical offsets onto the DEF floor, last GLB edit before
    # the look; it refuses a result ground_check would fail and stamps asset.extras for freeze_slice
    fused("ground apply", "ground", HERE / "ground_glb.py apply", lambda b: M["ground"].apply_bytes(u, b, glb))
    for r in done:
        stage_sidecar.write_sidecar(glb, r.suffix, r.sidecar)
    if not FROM_BASE[0]:
        tmp = glb.with_name(glb.name + ".fleet_stages.tmp")
        tmp.write_bytes(cur)
        os.replace(tmp, glb)
    return cur


REBUILD_NOTE = " | fleet_rebuild "


# A graded look is reviewed before the finish, the same order as the look-B rollout (look.py --stages finish,apply on
# reviewed looks; coordinator decision 2026-10-09): review judges the fitted look (A) against the DEF and its refusal
# (look further from the DEF than raw, look.py apply) still gates the rebuild; the finish (look B, the user-approved
# vanilla departure from the DEF, 2026-10-09) then applies to that reviewed A. A bare look.py runs finish before
# review, so a rebuild would judge B against the DEF and refuse units whose B is the approved look.
LOOK_REVIEW_STEP = ("look --stages bake,fit,vfx,review", ["--stages", "bake,fit,vfx,review"])
LOOK_FINISH_STEP = ("look --stages finish,apply", ["--stages", "finish,apply"])
# 2026-10-11 h3_ghost_dragon: --try-modes on look.py's default stages ran the finish (look B) before its review, so
# raw_verdict set post-finish try numbers (v6m 4.22) against the pre-finish reviewed bake (4.43) and refused both
# routes; the try measures what LOOK_REVIEW_STEP measures (look A against the DEF, 81edb3f084's order)
LOOK_TRY_STEP = ("look --try-modes", ["--try-modes", *LOOK_REVIEW_STEP[1]])
LOOK_DELIVERED_STEP = "look delivered"   # rebuild()'s last recorded step: every look stage of the run passed


def deliver_graded_look(look_step) -> None:
    """The graded-look delivery: bake, fit, vfx and review on the rebuilt GLB, then finish and apply (each a look.py
    run; a failing step raises in look_step and the transaction restores)."""
    look_step(*LOOK_REVIEW_STEP)
    look_step(*LOOK_FINISH_STEP)


def raw_verdict(look_dir: Path, u: str, mode: str | None = None) -> tuple[str, str]:
    """('raw' | 'applied' | 'refuse', numbers) for a rebuilt rawAccepted unit, from the try_<mode>_metrics.json that
    --try-modes just wrote: 'raw' when the raw body L-hist is strictly below every MODES grade's (spec's rule),
    'applied' when the look spec's own lighting.mode is at or below raw -- measured on the bake look --stages apply
    delivers (metrics.json, written by the bake,fit,vfx,review run on the spec's mode), since a rebake moves the body
    L-hist by ~0.05 and the two sit that close on hota_cove_ayssid -- else 'refuse'."""
    import spec as LS
    raws, body = set(), {}
    for m in LS.MODES:
        mp = look_dir / f"try_{m}_metrics.json"
        if not mp.is_file():
            raise RuntimeError(f"{u}: --try-modes wrote no {mp.name}")
        sm = (json.loads(mp.read_text(encoding="utf-8")).get("review") or {}).get("summary") or {}
        if sm.get("meanLhistBodyLook") is None or sm.get("meanLhistBodyRaw") is None:
            raise RuntimeError(f"{u}: {mp.name} carries no review body L-hist")
        body[m] = float(sm["meanLhistBodyLook"])
        raws.add(float(sm["meanLhistBodyRaw"]))
    if len(raws) != 1:
        raise RuntimeError(f"{u}: the try runs disagree on the raw body L-hist {sorted(raws)}")
    raw = raws.pop()
    if mode is None:
        mode = json.loads((ROOT / "tools/homm3_unit_look/units" / f"{u}.json").read_text(encoding="utf-8"))["lighting"]["mode"]
    nums = f"raw {raw}, " + ", ".join(f"{m} {v}" for m, v in body.items()) + f" (spec mode {mode})"
    if all(v > raw for v in body.values()):
        return "raw", nums
    mj = look_dir / "metrics.json"
    if mj.is_file():
        sm = (json.loads(mj.read_text(encoding="utf-8")).get("review") or {}).get("summary") or {}
        applied = sm.get("meanLhistBodyLook")
        nums += f"; applied bake {applied} vs raw {sm.get('meanLhistBodyRaw')}"
        if applied is not None and sm.get("meanLhistBodyRaw") is not None and float(applied) <= float(sm["meanLhistBodyRaw"]):
            return "applied", nums
        return "refuse", nums
    if mode in body and body[mode] <= raw:
        return "applied", nums
    return "refuse", nums


def accept_raw_reason(prior: dict, look_dir: Path) -> str:
    """The --accept-raw reason for a rebuilt rawAccepted unit: the prior stamp's own reason (without the numbers an
    earlier rebuild appended) plus this rebuild's body L-hist per mode, read from the try_<mode>_metrics.json that
    --try-modes just wrote. look.py re-checks every number against the GLB; this only records them."""
    base = ((prior.get("rawAccepted") or {}).get("reason") or "").split(REBUILD_NOTE)[0].strip()
    if not base:
        raise RuntimeError("the prior rawAccepted stamp records no reason")
    got, raw = [], set()
    for mp in sorted(look_dir.glob("try_*_metrics.json")):
        sm = (json.loads(mp.read_text(encoding="utf-8")).get("review") or {}).get("summary") or {}
        if sm.get("meanLhistBodyLook") is None:
            continue
        got.append(f"{mp.name[4:-len('_metrics.json')]} {sm['meanLhistBodyLook']}")
        raw.add(sm.get("meanLhistBodyRaw"))
    if not got or len(raw) != 1:
        raise RuntimeError(f"no consistent --try-modes metrics under {look_dir}")
    return (f"{base}{REBUILD_NOTE}{datetime.date.today().isoformat()}: body L-hist raw {raw.pop()}, "
            + ", ".join(got))


def chain_errors(u: str, rec: dict) -> list[str]:
    """Why the canonical GLB is not the look's delivery of this run's export through the stamped delivery stages
    (the emphasis gate's delivery_chain_errors, scoped to this unit and run). [] = linked end to end. A run that stopped
    after a stage rewrote the canonical GLB but before look re-ran fails here, naming the broken link."""
    base = rec.get("deliveryBaseGlbSha256")
    if not base:
        return ["the rebuild stopped before its export; the delivery chain has no base"]
    glb = ROOT / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.glb"
    errs = []
    if rec.get("route") == "emphasis_redeliver":
        st = load(ROOT / "artifacts/homm3_def_retarget_emphasis" / u / "stamp.json") or {}
        if st.get("emphasisedGlbSha256") != base:
            errs.append(f"the export {base[:12]} is not the emphasis stamp's emphasisedGlbSha256 "
                        f"{str(st.get('emphasisedGlbSha256'))[:12]}")
    look = load(ROOT / "artifacts/homm3_unit_look" / u / "stamp.json") or {}
    sidecars = {}
    for _, side in DELIVERY_STAGES:
        sp = Path(f"{glb}.{side}.json") if side else None
        if sp and sp.is_file():
            sidecars[side] = json.loads(sp.read_text(encoding="utf-8"))
    extras = read_glb_json(glb).get("asset", {}).get("extras") or {}
    gsha = sha(glb)
    if gsha == base and rec.get("steps") and rec["steps"][-1]["step"] != LOOK_DELIVERED_STEP:
        return errs + [f"the canonical GLB is still the un-looked export {base[:12]}"]
    return errs + delivery_chain_errors(base, gsha, extras, look, sidecars)


def delivered_paths(u: str) -> list[Path]:
    """The files that make up the unit's delivered state -- what freeze, the emphasis/look contracts and the delivery
    chain read -- that one rebuild can rewrite, plus the patch base that describes it (tools/homm3_glb_patch/base.py:
    retained right after the export, so a run that fails after its export would otherwise leave a base of the failed
    export beside the restored delivery; 2026-09-30 h3_monk / h3_crossbowman). A failed rebuild restores exactly these;
    the transaction is the one owner of both."""
    C = ROOT / "artifacts/homm3_def_retarget" / u
    glb = C / f"{u}_def_retarget.glb"
    L = ROOT / "artifacts/homm3_unit_look" / u
    B = ROOT / "artifacts/homm3_glb_patch" / u
    return ([glb] + [Path(f"{glb}.{side}.json") for _, side in DELIVERY_STAGES if side] +
            [C / "glb_verify.json", ROOT / "artifacts/homm3_def_retarget_emphasis" / u / "stamp.json",
             L / "stamp.json", L / "metrics.json", L / "basecolor.png", L / "raw_basecolor.png",
             L / "raw_source_image.jpg", L / "review_sheet.png", L / "review_worst_row.png",
             L / "vfx/vfx_manifest.json"] +
            [B / n for n in ("base.json", "base.glb", "glb_verify.json", "emphasis_stamp.json")])


def gate_faults(u: str, glb: Path) -> set[str]:
    """The freeze-time gates' faults on one GLB, as stable keys (numbers dropped, so a run is compared by what fails,
    not by how much): flyer_articulation.freeze_check per clip, ground_check per clip and check, freeze_slice's stride
    gate (stride:slip / stride:ratio) and the Unit_Move articulation gate (wings / body / legs / jittery). A gate that raises is a fault key too ("measure:<gate>"), so
    an unmeasurable delivered GLB and an unmeasurable rebuild compare equal and neither is waved through."""
    from flyer_articulation import GATE_CLIP, freeze_check, gate, glb_clips
    from ground_check import fault_key, ground_check
    keys: set[str] = set()
    try:
        keys |= {"freeze:" + ":".join(b.split()[:2]) for b in freeze_check(u, glb)[0]}
    except BaseException as e:  # noqa: BLE001  (SystemExit included: the gate's own refusal)
        keys.add(f"measure:freeze_check {type(e).__name__}")
    try:
        keys |= {"ground:" + fault_key(b) for b in ground_check(u, glb)[0]}
    except BaseException as e:  # noqa: BLE001
        keys.add(f"measure:ground_check {type(e).__name__}")
    try:
        from stride_match_glb import gate_faults as stride_faults
        keys |= {"stride:" + w for w in stride_faults(u, glb)}
    except BaseException as e:  # noqa: BLE001
        keys.add(f"measure:stride {type(e).__name__}")
    try:
        m = glb_clips(glb).get(GATE_CLIP)
        keys |= {f"articulation:no {GATE_CLIP}"} if m is None else {"articulation:" + b.split()[0].rstrip(":") for b in gate(m, u)}
    except BaseException as e:  # noqa: BLE001
        keys.add(f"measure:articulation {type(e).__name__}")
    return keys


def snapshot_glb(txn: dict, u: str) -> Path | None:
    """The snapshot's copy of the canonical GLB (None: there was no delivered GLB)."""
    for f in txn["files"]:
        if Path(f["path"]).name == f"{u}_def_retarget.glb":
            return Path(f["keep"]) if f["keep"] else None
    return None


LINKED_ON_FROM_BASE = (".glb", ".png", ".jpg")


def snapshot(u: str, d: Path, link: bool = False) -> dict:
    """Copy the delivered state into d (mtimes kept: the look stamp's deliveredGlbStat is size + mtime). A path absent
    now is recorded absent, so a failed run that created it has it removed again. link (the --from-base route): the
    GLB and the look images are hard-linked instead -- that route never writes them in place (look apply replaces the
    GLB by tmp + os.replace, the images are not rewritten), so the pre-run inode itself is the restore point. A link
    that cannot be made fails the run before it starts (fail closed); restore re-hashes every path either way."""
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    files = []
    for i, p in enumerate(delivered_paths(u)):
        if p.is_file():
            keep = d / f"{i:02d}_{p.name}"
            linked = link and p.suffix.lower() in LINKED_ON_FROM_BASE
            if linked:
                os.link(p, keep)
            else:
                shutil.copy2(p, keep)
            files.append({"path": str(p), "keep": str(keep), "sha256": sha(keep), **({"linked": True} if linked else {})})
        else:
            files.append({"path": str(p), "keep": None, "sha256": None})
    txn = {"unit": u, "dir": str(d), "files": files}
    (d / "txn.json").write_text(json.dumps(txn, indent=1) + "\n", encoding="utf-8")
    return txn


def restore(txn: dict) -> dict:
    """Put the snapshot back: changed files are replaced, files the run created are removed, untouched files are left
    alone. Every restored path is re-hashed against the snapshot; a mismatch raises (fail closed, the snapshot stays)."""
    changed, removed = [], []
    for f in txn["files"]:
        p = Path(f["path"])
        if f["keep"] is None:
            if p.exists():
                p.unlink()
                removed.append(p.name)
            continue
        if p.is_file() and sha(p) == f["sha256"]:
            continue
        tmp = p.with_name(p.name + ".fleet_restore.tmp")
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f["keep"], tmp)
        os.replace(tmp, p)
        changed.append(p.name)
    bad = [f["path"] for f in txn["files"]
           if (f["keep"] is None and Path(f["path"]).exists())
           or (f["keep"] is not None and (not Path(f["path"]).is_file() or sha(f["path"]) != f["sha256"]))]
    if bad:
        raise RuntimeError(f"restore of {txn['unit']} left {bad} differing from the snapshot {txn['dir']}")
    out = {"restoredGlbSha256": txn["files"][0]["sha256"], "replaced": changed, "removed": removed,
           "notRestored": "the .blend and its build companions, renders, look work files"}
    discard(txn)
    return out


def discard(txn: dict) -> None:
    shutil.rmtree(txn["dir"], ignore_errors=True)


def pre_run_snapshot(u: str) -> dict:
    """run_unit.sh <u>, before it writes anything (fleet_rebuild.py --pre-run-snapshot <u>): snapshot the delivered
    state, so the fleet_rebuild that follows restores the previous delivery and not run_unit's raw export (2026-10-09
    h3_sharpshooter: run_unit rc 0 overwrote the canonical with raw export cf42ac0e, fleet_rebuild's own snapshot then
    took that export, and the idle-rollout refusal restored it under the look stamps of the delivered GLB). A pending
    pre-run snapshot that still describes the delivered state is kept (a second run_unit before the rebuild)."""
    txn = adopt_pre_run(u)
    if txn is None:
        txn = snapshot(u, LOGS / "_txn" / u)
        txn.update({"preRun": True, "exports": []})
        (Path(txn["dir"]) / "txn.json").write_text(json.dumps(txn, indent=1) + "\n", encoding="utf-8")
    return txn


def pre_run_export(u: str) -> None:
    """run_unit.sh <u>, after its export (--pre-run-export <u>): the pending snapshot records the export's sha, the only
    GLB other than the snapshot's own that adopt_pre_run lets the canonical be."""
    txn = adopt_pre_run(u, new_export=True)
    if txn is None:
        raise RuntimeError(f"no pending pre-run snapshot of {u} matches the delivered state")
    glb = ROOT / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.glb"
    txn["exports"].append(sha(glb))
    (Path(txn["dir"]) / "txn.json").write_text(json.dumps(txn, indent=1) + "\n", encoding="utf-8")


def adopt_pre_run(u: str, new_export: bool = False) -> dict | None:
    """The pending pre-run snapshot (pre_run_snapshot), when it still describes the delivered state: same paths, every
    snapshotted copy present, every delivered file but the canonical GLB unchanged, and the GLB either the snapshot's or
    one of run_unit's recorded exports. Otherwise None: the delivery moved on since (a diagnostic run_unit never
    followed by a rebuild), and the caller snapshots afresh. new_export: the GLB is the export about to be recorded."""
    d = LOGS / "_txn" / u
    txn = load(d / "txn.json")
    if not txn or not txn.get("preRun") or [f["path"] for f in txn["files"]] != [str(p) for p in delivered_paths(u)]:
        return None
    for f in txn["files"]:
        p = Path(f["path"])
        if f["keep"] is not None and not Path(f["keep"]).is_file():
            return None
        cur = sha(p) if p.is_file() else None
        if cur != f["sha256"] and not (p.name == f"{u}_def_retarget.glb" and (new_export or cur in txn["exports"])):
            return None
    return txn


def idle_rollout(u: str) -> int:
    """tools/homm3_idle_cadence/rollout_idle.py <u> on the new delivery (exit 1 = refused, nothing written)."""
    return run([sys.executable, ROOT / "tools/homm3_idle_cadence/rollout_idle.py", u],
               LOGS / f"rebuild_{u}.log", timeout=1800)


def prune_superseded(u: str) -> int:
    """look.py <u> --prune-superseded: drop superseded originals other than the stamp's source. Only for a passing unit
    after its last failing-capable step -- the transaction cannot restore what this deletes."""
    return run([sys.executable, ROOT / "tools/homm3_unit_look/look.py", u, "--prune-superseded"],
               LOGS / f"rebuild_{u}.log")


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    bad = 0
    args = sys.argv[1:]
    if args[:1] in (["--pre-run-snapshot"], ["--pre-run-export"]):
        for u in args[1:]:
            (pre_run_snapshot if args[0] == "--pre-run-snapshot" else pre_run_export)(u)
        return 0
    # the run_unit.sh this run starts (directly or under deliver.py) is inside this transaction: no pre-run snapshot
    os.environ["FLEET_REBUILD_TXN"] = "1"
    if "--from-base" in args:
        FROM_BASE[0] = True
        args = [a for a in args if a != "--from-base"]
    for u in args:
        # a run that dies mid-rebuild (killed, fork failure, Blender crash) must not leave the previous run's ok:true
        # standing as this build's record (2026-09-27 battle griffin: 16:21 ok:true survived a 17:02 bake_cs death)
        (LOGS / f"rebuild_{u}.json").write_text(json.dumps(
            {"unit": u, "ok": False, "error": "rebuild started and did not finish",
             "startedAt": datetime.datetime.now().isoformat(timespec="seconds")}, indent=1) + "\n", encoding="utf-8")
        rec = {"unit": u}
        # a standalone run_unit.sh before this run already replaced the canonical GLB; its pre-run snapshot holds the
        # delivery that a failure must restore
        txn = adopt_pre_run(u)
        rec["snapshot"] = "pre-run (run_unit.sh)" if txn else "this run"
        txn = txn or snapshot(u, LOGS / "_txn" / u, link=FROM_BASE[0])
        # no regression past the freeze-time gates: what the delivered GLB already fails may stay, nothing new may
        # (2026-09-28 h3_fire_hound: a clean rebuild took Move jitterP90 0.151 -> 0.456 past the 0.35 cap and
        # replaced a freezable delivery). A unit with no delivered GLB has nothing to keep: every fault is new.
        kept = snapshot_glb(txn, u)
        before = gate_faults(u, kept) if kept else set()
        try:
            rebuild(u, rec)
        except Exception as e:  # noqa: BLE001  (one unit's fault is recorded, the batch continues)
            rec.update({"ok": False, "error": str(e)})
        # final step, pass or fail: the canonical GLB must be the look's delivery of this run's export
        try:
            ce = chain_errors(u, rec)
        except Exception as e:  # noqa: BLE001
            ce = [f"delivery chain check raised {e!r}"]
        rec["deliveryChain"] = ce or "linked"
        if ce:
            rec["ok"] = False
            rec["error"] = "; ".join(filter(None, [rec.get("error"), "delivery chain broken: " + "; ".join(ce)]))
        if rec["ok"]:
            after = gate_faults(u, ROOT / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.glb")
            rec["gateFaults"] = {"before": sorted(before), "after": sorted(after)}
            if after - before:
                rec["ok"] = False
                rec["error"] = "gate regression: new faults " + ", ".join(sorted(after - before))
        if rec["ok"]:
            # the new delivery changes the idle-cadence input; re-roll the retime so validate_homm3_idle_cadence_contract
            # does not report the unit STALE (2026-09-29 h3_boar_rider). A refusal (outlier without a recorded decision)
            # writes nothing and fails the unit like any refused stage.
            rc = idle_rollout(u)
            rec["idleRollout"] = rc
            if rc != 0:
                rec["ok"] = False
                rec["error"] = f"idle cadence rollout_idle.py {u} rc={rc}"
        if rec["ok"]:
            # last: nothing after this can fail the unit, so the restore can never need what the prune deletes
            rc = prune_superseded(u)
            rec["prune"] = rc
            if rc != 0:
                rec["warning"] = f"look --prune-superseded rc={rc} (delivery kept; the next run prunes again)"
            discard(txn)
        else:
            # the failed run's state is recorded above (steps, deliveryChain); the delivered state goes back
            try:
                rec["restore"] = restore(txn)
            except Exception as e:  # noqa: BLE001  (recorded; the snapshot is kept for a hand restore)
                rec["restore"] = {"error": str(e), "snapshot": txn["dir"]}
        (LOGS / f"rebuild_{u}.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        bad += not rec["ok"]
        mb, ma = rec.get("morphBefore", {}).get("ratio"), rec.get("morphAfter", {}).get("ratio")
        print(f"{u}: {'OK' if rec['ok'] else 'FAIL'} route={rec.get('route')} morph {mb} -> {ma} "
              f"{rec.get('seconds', '')}s {rec.get('error', '')}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
