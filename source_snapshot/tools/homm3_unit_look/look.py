"""Unit look pipeline entry point: lighting (prebaked base colour) + VFX for DEF-retargeted units.

    python tools/homm3_unit_look/look.py <unit> [<unit> ...] [--stages bake,fit,finish,vfx,review,apply] [--force]
    python tools/homm3_unit_look/look.py <unit> --stages finish,apply      (re-finish a delivered look; no Blender)
    python tools/homm3_unit_look/look.py --faction custom_factions/homm3_<faction>.json [--stages ...]
    python tools/homm3_unit_look/look.py --summary
    python tools/homm3_unit_look/look.py <unit> --accept-raw "<reason>"   (after --try-modes; see stage_accept_raw)

Contract: docs/homm3_unit_look_pipeline.md. Spec: tools/homm3_unit_look/units/<unit>.json.
Writes only under artifacts/homm3_unit_look/<unit>/ (plus the delivered GLB and, for fitted light
curves, the unit's own spec). --summary rebuilds ROSTER_SUMMARY.{json,md} + WORST10_sheet.png.
Exit: 0 ok, 2 spec error, 3 missing input, 4 fit/review failure, 5 delivery/validator failure.
Proof tier of every output: generated artifact.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import spec as S  # noqa: E402
from glbpatch import Glb, sha256_bytes, sha256_file  # noqa: E402

ROOT = S.ROOT
BLENDER = os.environ.get("BLENDER", "V:/Tools/blender-mcp/blender-5.2.2/blender.exe")
PREBAKE = ROOT / "tools/homm3_prebake"
STAGES = ("bake", "fit", "finish", "vfx", "review", "apply")
# The stages a bare ``look.py <unit>`` runs: every stage. "finish" (finish.py, look B "vanilla philosophy", 2026-10-09
# user decision) joined the default when the pilot boards were approved (2026-10-09), so a full-chain rebuild by any
# lane delivers B. Delivered looks are moved to B slice by slice with --stages finish,apply (no Blender).
DEFAULT_STAGES = STAGES
SUPERSAMPLE = 2


class StageError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def log(unit, msg):
    print(f"[{unit}] {msg}", flush=True)


# ----------------------------------------------------------------------------- source GLB
def resolve_source(unit: str) -> tuple[bytes, str]:
    """The un-prebaked GLB this unit's look is built from: the delivered GLB's superseded original when
    the GLB is the stamped delivery, else the GLB itself (a fresh def_retarget build)."""
    if not S.glb_exists(unit):
        raise StageError(3, f"no def_retarget GLB at {S.glb_path(unit)}")
    cur = S.glb_bytes(unit)
    cur_sha = sha256_bytes(cur)
    stamp = read_stamp(unit)
    if stamp and stamp.get("kind") == S.RAW_ACCEPTED:
        return cur, "glb"   # a rawAccepted delivery is the un-prebaked GLB itself
    if stamp and cur_sha == stamp.get("deliveredGlbSha256"):
        src = superseded_path(unit, stamp["sourceGlbSha256"])
        if not src.is_file():
            raise StageError(5, f"stamped delivery but its original {src} is missing")
        b = src.read_bytes()
        if sha256_bytes(b) != stamp["sourceGlbSha256"]:
            raise StageError(5, f"superseded original {src} does not match its stamp")
        return b, "superseded"
    if stamp:
        g = Glb(cur)
        img = sha256_bytes(g.image_bytes(g.body_base_color_image()))
        if img == stamp.get("basecolorSha256"):
            raise StageError(5, "GLB carries the prebaked base colour but is not the stamped delivery "
                                "(edited after apply?); refusing to treat it as a source")
    return cur, "glb"


def superseded_path(unit: str, sha: str) -> Path:
    return S.out_dir(unit) / S.SUPERSEDED / f"{sha[:12]}{S.UNPREBAKED_EXT}"


def read_stamp(unit: str):
    p = S.out_dir(unit) / "stamp.json"
    return json.loads(p.read_text()) if p.is_file() else None


# ----------------------------------------------------------------------------- front
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}


def rest_joints(g: Glb) -> dict:
    """Rest-pose world positions of the GLB's nodes, in Blender axes (x, -z, y)."""
    nodes = g.json["nodes"]
    par = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

    def q2m(q):
        x, y, z, w = q
        return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    cache = {}

    def M(i):
        if i not in cache:
            n = nodes[i]
            m = np.eye(4)
            m[:3, :3] = q2m(n.get("rotation", [0, 0, 0, 1])) * np.array(n.get("scale", [1, 1, 1]))
            m[:3, 3] = n.get("translation", [0, 0, 0])
            cache[i] = M(par[i]) @ m if i in par else m
        return cache[i]
    out = {}
    for i, n in enumerate(nodes):
        p = M(i)[:3, 3]
        out[n.get("name", "")] = np.array([p[0], -p[2], p[1]])
    return out


def resolve_front(g: Glb, spec_front: str) -> dict:
    """``auto``: the feet (Foot->ToeBase, both sides, horizontal) when both agree on one axis within ~35 deg,
    else Head-Hips when the head leans at least 10% of its height, else fail closed. An axis passes through."""
    if spec_front != "auto":
        return {"axis": spec_front, "source": "spec"}
    J = rest_joints(g)

    def hz(a, b):
        if a not in J or b not in J:
            return None
        v = J[b] - J[a]
        full = np.linalg.norm(v)
        v = v.copy()
        v[2] = 0
        n = np.linalg.norm(v)
        return (v / n, n, full) if n > 1e-6 else None

    def axis_of(v):
        k, sgn = max(((k, float(np.dot(v, d))) for k, d in AXES.items()), key=lambda kv: kv[1])
        return k, sgn
    feet = [hz(f"{s}Foot", f"{s}ToeBase") for s in ("Left", "Right")]
    if all(feet):
        ks = [axis_of(f[0]) for f in feet]
        if ks[0][0] == ks[1][0] and min(k[1] for k in ks) >= 0.82:
            return {"axis": ks[0][0], "source": f"auto:feet (dot {ks[0][1]:.2f}/{ks[1][1]:.2f})"}
    hh = hz("Hips", "Head")
    if hh and hh[1] >= 0.1 * max(hh[2], 1e-6):
        k, d = axis_of(hh[0])
        if d >= 0.82:
            return {"axis": k, "source": f"auto:Head-Hips (dot {d:.2f})"}
    raise StageError(3, "front auto is ambiguous (feet absent or disagree, head above hips); set lighting.front to an "
                        "axis and check the battle facings")


# ----------------------------------------------------------------------------- frames
def choose_frames(spec, clips):
    lit = S.dynamic_zero_frames(spec, clips)
    kn = spec["lighting"].get("knobs", {})
    if kn.get("fitFrames"):
        fit = [t for t in kn["fitFrames"] if t not in lit]
    else:
        fit = []
        idle = clips.get("Unit_Idle")
        if idle:
            mf = idle["masterFrames"]
            fit += [mf[0], mf[len(mf) // 2]]
        mv = clips.get("Unit_Move")
        if mv:
            fit.append(mv["masterFrames"][len(mv["masterFrames"]) // 2])
        fit = [t for t in dict.fromkeys(fit) if t not in lit]
    if not fit:
        raise StageError(3, "no fit frames (no Idle/Move clip, or every candidate frame has a dynamic light lit)")
    review = list(fit)
    fx_clips = set()
    for ly in spec["vfx"]["layers"]:
        if ly["type"] == "defFlipbook":
            fx_clips |= set(ly["clips"])
        elif ly["type"] == "effectLight":
            fx_clips |= set(ly["intensity"])
        elif ly["type"] == "event":
            fx_clips.add(ly["clip"])
    for c in sorted(fx_clips):
        review += clips[c]["masterFrames"]
    if not fx_clips:
        for c in ("Unit_AttackFront", "Unit_Hitted"):
            if c in clips:
                mf = clips[c]["masterFrames"]
                review.append(mf[len(mf) // 2])
    review = list(dict.fromkeys(review))
    return fit, review


# ----------------------------------------------------------------------------- bake (Blender)
STD_TERMS = ["ao", "sky", "pos", "nrm", "sun_top", "sun_fl", "sun_fr", "sun_bl", "sun_br", "sun_l", "sun_r"]
EXTRA_TERMS = ["ao_short", "thickness", "pointiness", "nrm_geo"]
TERM_SIZE, TERM_SAMPLES, TERM_WELD = 2048, 64, "0.0001"
TERMS_KEY_SCHEMA = "homm3_unit_look_terms_key.v2"
BAKE_TIMEOUT = [float(os.environ.get("HOMM3_BAKE_TIMEOUT", "1800"))]  # seconds per Blender launch; --bake-timeout


def blender(unit, blend: Path, script: Path, args: list[str], logf: Path, expect: list[str] | None = None):
    """One Blender launch inside a machine-wide GPU slot (gpuslot; memgate runs inside the slot)."""
    import gpuslot
    lg = str(ROOT / "tools/homm3_def_retarget")
    if lg not in sys.path:
        sys.path.append(lg)  # appended: that folder's Blender review.py must not shadow ours
    from launch_guard import blender_env, child_env_note
    cmd = [BLENDER, "-b", str(blend), "--factory-startup", "-P", str(script), "--", *args]
    timeout = BAKE_TIMEOUT[0]
    try:
        with gpuslot.slot(cmd, unit, on_wait=lambda m: log(unit, m)):
            t0 = time.time()
            with open(logf, "a", encoding="utf-8") as f:
                f.write(f"\n$ {' '.join(cmd)}  [{child_env_note()}]\n")
                f.flush()
                start = f.tell()
                try:
                    r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=blender_env())
                except subprocess.TimeoutExpired:
                    r = None
    except gpuslot.SlotError as e:
        raise StageError(3, str(e))
    with open(logf, "rb") as f:
        f.seek(start)
        tail = f.read().decode("utf-8", errors="replace")
    if r is None:
        done = [ln.split()[1] for ln in tail.splitlines() if ln.startswith("BAKED ") and len(ln.split()) > 1]
        if expect:
            left = [t for t in expect if t not in done]
            what = (f"timed out on term {left[0] if left else '?'} (finished in this launch: {done or 'none'}; "
                    f"not started: {left[1:] or 'none'}); finished terms are kept and a rerun resumes")
        else:
            last = [ln for ln in tail.splitlines() if ln.strip()][-1:] or ["<no output>"]
            what = f"timed out (last output: {last[0][:200]})"
        msg = f"Blender {script.name} hit the {timeout:.0f}s bake timeout: {what}"
        with open(logf, "a", encoding="utf-8") as f:
            f.write(f"\nLOOK TIMEOUT {msg}\n")
        log(unit, msg)
        raise StageError(4, f"{msg}; raise --bake-timeout / HOMM3_BAKE_TIMEOUT if the machine is busy; see {logf}")
    tail = tail[-3000:]
    if r.returncode != 0 or "Traceback" in tail or "SystemExit" in tail:
        if "facing is ambiguous" in tail or "--front auto" in tail:
            raise StageError(3, "front auto is ambiguous for this unit; set lighting.front to an axis (see bake.log)")
        raise StageError(4, f"Blender {script.name} failed (rc {r.returncode}); see {logf}")
    log(unit, f"{script.name} ok in {time.time() - t0:.0f}s")


def term_path(terms: Path, t: str) -> Path:
    z = terms / f"{t}.npz"
    return z if z.is_file() else terms / f"{t}.npy"


def term_ok(p: Path) -> bool:
    """A finished term: the whole .npy payload, or a .npz that decompresses to the full array (a killed save
    leaves either short or unreadable)."""
    try:
        if p.suffix == ".npz":
            with np.load(p) as z:
                return z["term"].shape == (TERM_SIZE, TERM_SIZE, 3)
        return np.load(p, mmap_mode="r").shape == (TERM_SIZE, TERM_SIZE, 3)
    except Exception:
        return False


def compact_terms(terms: Path) -> int:
    """Re-store every finished terms/*.npy as a compressed .npz holding the identical float16 array (lossless;
    about 4x smaller). The .npz is written to a temp name, read back and compared before it replaces the .npy.
    Returns bytes saved."""
    saved = 0
    for p in sorted(terms.glob("*.npy")):
        if not term_ok(p):
            continue
        a = np.load(p)
        z, tmp = p.with_suffix(".npz"), p.with_suffix(".npz.tmp")
        try:
            with open(tmp, "wb") as f:
                np.savez_compressed(f, term=a)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise StageError(6, f"disk low while compressing {p.name} ({e}); the .npy is kept")
        with np.load(tmp) as zz:
            same = zz["term"].dtype == a.dtype and np.array_equal(zz["term"], a)
        if not same:
            tmp.unlink()
            raise StageError(4, f"compressed term {z.name} does not read back identical; kept {p.name}")
        os.replace(tmp, z)
        saved += p.stat().st_size - z.stat().st_size
        p.unlink()
    return saved


MIN_FREE_GB = float(os.environ.get("HOMM3_MIN_FREE_GB", "2"))
KEEP_WORK = [False]  # --keep-work


def disk_preflight(unit, stage):
    free = shutil.disk_usage(S.OUT_ROOT if S.OUT_ROOT.exists() else ROOT).free / 1e9
    if free < MIN_FREE_GB:
        raise StageError(6, f"disk low: {free:.2f} GB free on the artifact drive (< {MIN_FREE_GB} GB, "
                            f"HOMM3_MIN_FREE_GB); not starting {stage} so nothing is half-written. Free space "
                            "(e.g. look.py --prune-applied --all) and rerun; the bake resumes")


def prune_work(unit, keep_terms: bool = False) -> int:
    """Delete the regenerable bulk of an applied unit's work/ (terms/, views/, look_tex_lin.npy). Keeps the keys,
    fit_source.json (apply's geometry/base-colour check), source_basecolor.png, region caches, regions_fit.json
    and bake.log; the stamp, the validator and the delivered files never read what is pruned. A later rerun
    rebakes (the keys then drive a normal resumable bake). keep_terms (the post-apply prune): terms/ stays, because
    its key is the content of the .blend's bake inputs (terms_input_hash), so a rebuild that leaves the body mesh
    alone reuses it instead of rebaking (~45 s a unit). Returns bytes freed."""
    work = S.out_dir(unit) / "work"
    freed = 0
    removed = [rel for rel in ("terms", "views", "look_tex_lin.npy") if not (keep_terms and rel == "terms")]
    for rel in removed:
        q = work / rel
        if q.is_dir():
            freed += sum(f.stat().st_size for f in q.rglob("*") if f.is_file())
            shutil.rmtree(q)
        elif q.is_file():
            freed += q.stat().st_size
            q.unlink()
    if freed:
        (work / "pruned.json").write_text(json.dumps({"prunedAt": dt.datetime.now().isoformat(timespec="seconds"),
                                                     "bytes": freed,
                                                     "removed": [r + "/" if r != "look_tex_lin.npy" else r for r in removed],
                                                     "why": "applied + validated; regenerable by the bake/fit stages"}, indent=1))
    return freed


def stamp_validates(unit) -> bool:
    r = subprocess.run([sys.executable, str(ROOT / "tools/validate_homm3_unit_look_contract.py"), "--unit", unit,
                        "--require-delivered"], capture_output=True, text=True)
    return r.returncode == 0


def prune_applied(units) -> int:
    total, done, skipped = 0, [], []
    for u in units:
        if read_stamp(u) is None:
            continue  # unapplied: its (partial) terms are what the bake resumes from
        if not stamp_validates(u):
            skipped.append(u)
            continue
        b = prune_work(u)
        total += b
        done.append((u, b))
        print(f"PRUNE {u}: {b / 1e9:.2f} GB")
    for u in skipped:
        print(f"PRUNE {u}: skipped (stamp does not validate)")
    print(f"PRUNE total {total / 1e9:.2f} GB from {len(done)} unit(s)")
    return 0


def prune_superseded(units) -> int:
    """Delete every un-prebaked original under <unit>/_superseded_do_not_use/ except the one the stamp's
    sourceGlbSha256 names (the only one resolve_source ever reads). Fail closed: a unit whose stamp is
    missing, does not validate, or whose kept original is absent / hashes wrong is left untouched."""
    total, bad = 0, 0
    for u in units:
        st = read_stamp(u)
        d = S.out_dir(u) / S.SUPERSEDED
        if st is None or not d.is_dir():
            continue
        if not stamp_validates(u):
            print(f"PRUNE-SUPERSEDED {u}: skipped (stamp does not validate)")
            bad += 1
            continue
        if st.get("kind") == S.RAW_ACCEPTED:
            # a rawAccepted delivery IS the un-prebaked GLB (resolve_source reads the GLB itself, the stamp records
            # superseded: None): no original under _superseded_do_not_use is ever read, so none is kept -- but only
            # while the delivered GLB is exactly the stamped one (2026-09-28 h3_ghost_dragon: accept-raw passed and
            # this prune refused, looking for a superseded original a rawAccepted stamp never names)
            glb = S.glb_path(u)
            if st.get("superseded") is not None or not glb.is_file() or sha256_file(glb) != st.get("deliveredGlbSha256"):
                print(f"PRUNE-SUPERSEDED {u}: skipped (rawAccepted stamp, but the delivered GLB is not the stamped one "
                      f"or the stamp names a superseded original)")
                bad += 1
                continue
            keep = None
        else:
            keep = superseded_path(u, st["sourceGlbSha256"])
        if keep is not None and (not keep.is_file() or sha256_file(keep) != st["sourceGlbSha256"]):
            print(f"PRUNE-SUPERSEDED {u}: skipped (stamped original {keep.name} missing or does not hash to the stamp)")
            bad += 1
            continue
        freed, n = 0, 0
        for f in d.iterdir():
            if f.is_file() and f != keep and (f.name.endswith(S.UNPREBAKED_EXT) or f.name.endswith(S.UNPREBAKED_EXT + ".tmp")):
                freed += f.stat().st_size
                n += 1
                f.unlink()
        total += freed
        print(f"PRUNE-SUPERSEDED {u}: {n} file(s), {freed / 1e9:.2f} GB (kept {keep.name if keep else "none: rawAccepted delivers the GLB itself"})")
    print(f"PRUNE-SUPERSEDED total {total / 1e9:.2f} GB")
    return 5 if bad else 0


def compact_all(units) -> int:
    total = 0
    for u in units:
        t = S.out_dir(u) / "work/terms"
        if t.is_dir():
            b = compact_terms(t)
            if b:
                print(f"COMPACT {u}: {b / 1e9:.2f} GB")
            total += b
    print(f"COMPACT total {total / 1e9:.2f} GB")
    return 0


def terms_input_hash(unit, blend: Path, work: Path, logf: Path) -> str:
    """bake_terms.py --input-hash: sha256 over everything the terms read from the .blend (evaluated rest mesh,
    normals, UVs, topology, modifiers, armature rest, normal-map bytes, Blender version). The .blend's own bytes
    change on every save (bake_cs, emphasis, renders), so keying terms on them rebaked identical terms on every
    rebuild. CPU only (~3 s, no GPU slot: nothing is rendered); launch_guard still runs first."""
    out = work / "terms_input_hash.json"
    out.unlink(missing_ok=True)
    cmd = [sys.executable, str(ROOT / "tools/homm3_def_retarget/launch_guard.py"), "--exec", "--", BLENDER, "-b", str(blend),
           "--factory-startup", "--python-exit-code", "1", "-P", str(PREBAKE / "bake_terms.py"), "--",
           "--out", str(work / "terms"), "--input-hash", str(out)]
    t0 = time.time()
    with open(logf, "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        try:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=600)
        except subprocess.TimeoutExpired:
            raise StageError(4, f"bake_terms.py --input-hash timed out; see {logf}")
    if r.returncode != 0 or not out.is_file():
        raise StageError(4, f"bake_terms.py --input-hash failed (rc {r.returncode}); see {logf}")
    h = json.loads(out.read_text())["sha256"]
    log(unit, f"terms input hash {h[:12]} in {time.time() - t0:.0f}s")
    return h


def stage_bake(unit, spec, force=False):
    outd = S.out_dir(unit)
    work = outd / "work"
    blend = S.blend_path(unit)
    if not blend.is_file():
        raise StageError(3, f"no build .blend at {blend}")
    src, where = resolve_source(unit)
    g = Glb(src)
    geo = g.geometry_sha256()
    img = g.image_bytes(g.body_base_color_image())
    fr = resolve_front(g, spec["lighting"]["front"])
    clips = S.clip_segments(unit)
    fit, review = choose_frames(spec, clips)
    frames = sorted(set(fit) | set(review))
    key = {"geometrySha256": geo, "sourceBasecolorSha256": sha256_bytes(img), "blendSha256": sha256_file(blend),
           "front": fr["axis"], "frames": frames, "supersample": SUPERSAMPLE,
           "anchorBones": sorted({ly["anchor"]["bone"] for ly in spec["vfx"]["layers"] if "anchor" in ly}),
           "bakeTermsSha256": sha256_file(PREBAKE / "bake_terms.py"),
           "renderPassesSha256": sha256_file(PREBAKE / "render_passes.py")}
    vkey = {**key, "conds": "sand,grass"}
    kp, tkp, vkp = work / "bake_key.json", work / "terms_key.json", work / "views_key.json"
    rd = lambda p: json.loads(p.read_text()) if p.is_file() else None  # noqa: E731
    if not force and rd(kp) == key and (work / "views/views_meta.json").is_file() and term_path(work / "terms", "ao_short").is_file():
        compact_terms(work / "terms")
        log(unit, "bake cached")
        return
    disk_preflight(unit, "bake")
    if force and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    logf = work / "bake.log"
    # Resumable: terms and views carry their own cache keys; only stale, missing or truncated parts are rebaked. The
    # terms key is the content of the .blend's bake inputs, not its bytes (terms_input_hash), plus the bake params and
    # the bake script, so a rebuild that leaves the rest mesh / normal map alone keeps its terms (views still rebake:
    # they render the clips).
    tkey = {"schema": TERMS_KEY_SCHEMA, "inputSha256": terms_input_hash(unit, blend, work, logf), "front": fr["axis"],
            "size": TERM_SIZE, "samples": TERM_SAMPLES, "weld": TERM_WELD, "standard": STD_TERMS, "extras": EXTRA_TERMS,
            "bakeTermsSha256": key["bakeTermsSha256"]}
    terms, views = work / "terms", work / "views"
    if rd(tkp) != tkey and terms.exists():
        log(unit, "terms cache key changed or absent; dropping the old terms")
        shutil.rmtree(terms)
    terms.mkdir(parents=True, exist_ok=True)
    tkp.write_text(json.dumps(tkey, indent=1))  # before baking, so a killed bake's finished terms stay provable
    kp.unlink(missing_ok=True)
    (work / "source_basecolor.png").write_bytes(img)
    front = [f"--front={fr['axis']}"]
    log(unit, f"front {fr['axis']} ({fr['source']})")
    base = ["--out", str(terms), "--size", str(TERM_SIZE), "--samples", str(TERM_SAMPLES)]
    for group, extra in ((STD_TERMS, []), (EXTRA_TERMS, ["--extras", ",".join(EXTRA_TERMS), "--weld", TERM_WELD])):
        have = [t for t in group if term_ok(term_path(terms, t))]
        todo = [t for t in group if t not in have]
        for t in todo:
            (terms / f"{t}.npy").unlink(missing_ok=True)
            (terms / f"{t}.npz").unlink(missing_ok=True)
        if not todo:
            log(unit, f"terms cached ({len(group)} {'extra' if extra else 'standard'} terms, key {tkey['inputSha256'][:12]})")
            continue
        if have:
            log(unit, f"resuming terms: kept {have}, baking {todo}")
        blender(unit, blend, PREBAKE / "bake_terms.py", [*base, *extra, *(["--only", ",".join(todo)] if have else []), *front],
                logf, expect=todo)
    missing =[t for t in STD_TERMS + EXTRA_TERMS if not term_ok(term_path(terms, t))]
    if missing:
        raise StageError(4, f"bake_terms finished without terms {missing}; see {logf}")
    compact_terms(terms)
    if rd(vkp) != vkey or not (views / "views_meta.json").is_file():
        if views.exists():
            shutil.rmtree(views)
        views.mkdir(parents=True)
        vkp.write_text(json.dumps(vkey, indent=1))
        blender(unit, blend, PREBAKE / "render_passes.py", ["--out", str(views), "--frames", ",".join(str(t + 1) for t in frames),
                                                            "--supersample", str(SUPERSAMPLE), "--position", "--bones", "all",
                                                            "--conds", vkey["conds"], *front], logf)
        shutil.rmtree(views / "_tmp", ignore_errors=True)
    else:
        log(unit, "views cached")
    kp.write_text(json.dumps(key, indent=1))
    (work / "fit_source.json").write_text(json.dumps({"geometrySha256": geo, "sourceBasecolorSha256": key["sourceBasecolorSha256"],
                                                      "sourceFrom": where, "front": fr}, indent=1))


# ----------------------------------------------------------------------------- context
def build_ctx(unit, spec):
    import lighting as LT
    import masks as mk
    import prebake_lab as pl
    work = S.out_dir(unit) / "work"
    if not (work / "views/views_meta.json").is_file():
        raise StageError(3, "no bake outputs; run the bake stage first")
    vmeta, m, views = LT.load_work(work)
    clips = S.clip_segments(unit)
    fit, review = choose_frames(spec, clips)
    fm = S.frames_meta(unit)
    dname = S.def_name(unit)
    flip = [ly for ly in spec["vfx"]["layers"] if ly["type"] == "defFlipbook"]
    defs, alpha = {}, {}
    for t in sorted(set(fit) | set(review)):
        vn = f"sprite_f{t + 1:03d}"
        if vn not in views:
            raise StageError(3, f"view {vn} missing from the bake (rerun bake)")
        src = fm["sources"][t]
        rgba = mk.load_rgba(src)
        g, f = (int(x) for x in Path(src).stem.split("_")[:2])
        body = mk.body_mask(rgba)
        fx = np.zeros_like(body)
        for ly in flip:
            # A layer carves only the (group, frame) keys it lists: a breath layer never cuts idle fit targets,
            # and a file mask is only read where the layer claims an effect (a missing listed PNG still raises).
            if (g, f) not in {(c["defGroup"], x) for c in ly["clips"].values() for x in c["frames"]}:
                continue
            fx |= mk.effect_mask(ly["effectMask"], rgba, ly.get("def") or dname, g, f, unit)
        defs[vn] = {"src": src, "rgba": rgba, "body": body, "fx": fx & body, "bodyNoFx": body & ~fx, "g": g, "f": f, "t": t}
        _, a = pl.downsample(np.zeros(views[vn]["alpha"].shape + (1,), np.float32), views[vn]["alpha"], vmeta["views"][vn]["supersample"])
        alpha[vn] = a
    cam = json.loads((S.RETARGET / unit / f"{unit}_def_retarget.blend.spritecam.json").read_text())
    return {"unit": unit, "srcGlb": lambda: resolve_source(unit)[0], "vmeta": vmeta, "maps": m, "views": views, "clips": clips, "def": defs, "meshAlpha": alpha,
            "defName": dname, "spritecam": cam, "cond": spec["lighting"].get("arena", "sand"),
            "fitViews": [f"sprite_f{t + 1:03d}" for t in fit], "reviewViews": [f"sprite_f{t + 1:03d}" for t in review]}


# ----------------------------------------------------------------------------- finish (look B)
SUPERSEDE_RAW_ENV = "HOMM3_LOOK_SUPERSEDE_RAW"   # fleet_rebuild: <unit> whose fitted, reviewed look supersedes its raw


def stage_finish(unit, spec, metrics: dict, fitted_now: bool) -> None:
    """finish.py on the lighting stage's A: keeps A as basecolor_a.png, writes B (or A again for finish "none") to
    basecolor.png and records metrics["lighting"]["finish"] {mode, inputSha256, outputSha256, codeSha256, log}.
    Rerunnable: when basecolor.png is already a recorded finish output, A is read back from basecolor_a.png (pinned).
    No Blender and no views: geometry comes from the un-prebaked source GLB, the target from the DEF idle frame."""
    import finish as FN
    outd = S.out_dir(unit)
    bc, ba = outd / "basecolor.png", outd / "basecolor_a.png"
    if not bc.is_file():
        raise StageError(4, "no basecolor.png; run the fit stage first")
    st = read_stamp(unit)
    lt = metrics.setdefault("lighting", {})
    if st and st.get("kind") == S.RAW_ACCEPTED and not fitted_now:
        # fleet_rebuild's rawAccepted-superseded route (its raw_verdict 'applied': the spec's own mode now beats raw on
        # the rebuilt GLB) fits and reviews in one look.py call and finishes in the next, so the stamp is still the
        # raw delivery here. It names the unit in SUPERSEDE_RAW_ENV; the finish then takes basecolor.png as a fresh A
        # only while that fit is unfinished and was made on this spec's knobs, and was reviewed (2026-10-11
        # h3_gnoll_marauder, h3_lizardman, h3_boar_rider: exit 2 here on every rebuild; user-approved 2026-10-11)
        if not (os.environ.get(SUPERSEDE_RAW_ENV) == unit and not lt.get("finish") and metrics.get("review")
                and lt.get("knobsSha256") == S.knobs_sha(spec)):
            raise StageError(2, "a rawAccepted look delivers the raw base colour; the finish applies to a graded look only "
                                "(rerun the full chain, or keep the raw delivery)")
        fitted_now = True
    fin = lt.get("finish") or {}
    if fin.get("outputSha256") and not fitted_now and sha256_file(bc) == fin["outputSha256"]:
        if not ba.is_file() or sha256_file(ba) != fin.get("inputSha256"):
            raise StageError(5, "basecolor.png is a recorded finish output but basecolor_a.png is missing or is not its "
                                "recorded input; rerun the fit stage")
    else:
        shutil.copy2(bc, ba)          # basecolor.png is A: a fresh fit, or a look delivered before the finish existed
    a_sha = sha256_file(ba)
    mode = FN.mode_of(spec)
    if mode == "none":
        shutil.copy2(ba, bc)
        lt["finish"] = {"schema": FN.SCHEMA, "mode": "none", "inputSha256": a_sha, "outputSha256": a_sha}
    else:
        dev = FN.device(os.environ.get("HOMM3_FINISH_DEVICE", "cuda"))
        tmp = outd / "basecolor.finish.tmp.png"
        t0 = time.time()
        lg = FN.run_unit(unit, spec, ba, tmp, dev)
        os.replace(tmp, bc)
        lt["finish"] = {"schema": FN.SCHEMA, "mode": mode, "inputSha256": a_sha, "outputSha256": sha256_file(bc),
                        "codeSha256": FN.code_sha(), "seconds": round(time.time() - t0, 1), "log": lg}
        log(unit, f"finish {mode}: render body L p5/p50/p95 {lg['render_A_L_p5_p50_p95']} -> {lg['render_B_L_p5_p50_p95']} "
                  f"(DEF {lg['DEF_body_L_p5_p50_p95']}); grade k={lg['grade_k']} g={lg['grade_gamma']} chroma x{lg['chroma_scale']}"
                  + (" regions kept" if lg["regionsProtected"] else "") + (" metal masked" if lg["metalMasked"] else ""))
    lin = outd / "work/look_tex_lin.npy"
    if lin.is_file():                 # vfx / review read the look from here: keep it the delivered base colour
        import prebake_lab as pl
        from PIL import Image
        img = np.asarray(Image.open(bc).convert("RGB"), np.float32) / 255.0
        np.save(lin, pl.srgb_to_lin(img).astype(np.float16))


# ----------------------------------------------------------------------------- apply (delivery)
def stage_apply(unit, spec):
    outd = S.out_dir(unit)
    tex = outd / "basecolor.png"
    man = outd / "vfx/vfx_manifest.json"
    fs = outd / "work/fit_source.json"
    for p in (tex, man, fs, outd / "metrics.json"):
        if not p.is_file():
            raise StageError(5, f"missing {p.name}; run fit, vfx and review first")
    mj = json.loads((outd / "metrics.json").read_text())
    if mj.get("lighting", {}).get("knobsSha256") != S.knobs_sha(spec):
        raise StageError(5, "basecolor.png was not fitted from the current lighting spec (spec edited, or --try-modes "
                            "ran last); rerun fit,vfx,review")
    if mj.get("vfx", {}).get("specSha256") != S.canonical_sha(spec):
        raise StageError(5, "the VFX assets were not built from the current spec; rerun vfx,review")
    fin = mj.get("lighting", {}).get("finish")
    if fin is not None and fin.get("outputSha256") != sha256_file(tex):
        raise StageError(5, "basecolor.png is not the recorded finish output (edited, or the fit ran after the finish); "
                            "rerun the finish stage")
    if fin is not None:
        import finish as FN
        if fin.get("mode") != FN.mode_of(spec):
            raise StageError(5, f"the finish ran as {fin.get('mode')!r} but the spec asks for {FN.mode_of(spec)!r}; "
                                "rerun the finish stage")
    rv = mj.get("review", {}).get("summary", {})
    if rv and rv.get("meanLhistBodyLook", 0) > rv.get("meanLhistBodyRaw", 1e9):
        raise StageError(5, f"the look is further from the DEF than the raw base colour (body L-hist {rv['meanLhistBodyLook']} "
                            f"vs raw {rv['meanLhistBodyRaw']}); not delivering a regression. Retune the spec (mode, knobs, "
                            "regions) and rerun fit,vfx,review")
    # A floor light's base colour is graded to be seen under that light. The def_retarget delivery lane
    # holds floors (curve-less clips keep the floor; Homm3UnitLookVfxRuntime drives it in battle), so apply
    # is no longer refused; the stamp names the lights so a lane that cannot hold them can refuse the unit.
    held = [ly["id"] for ly in spec["vfx"]["layers"] if ly["type"] == "effectLight" and ly.get("floor")]
    src, where = resolve_source(unit)
    g = Glb(src)
    fsj = json.loads(fs.read_text())
    geo = g.geometry_sha256()
    if geo != fsj["geometrySha256"]:
        raise StageError(5, "the GLB's body geometry changed since the fit (rebuild moved the mesh/UVs); "
                            "rerun the full stages")
    ii = g.body_base_color_image()
    if sha256_bytes(g.image_bytes(ii)) != fsj["sourceBasecolorSha256"]:
        raise StageError(5, "the GLB's source base colour changed since the fit; rerun the full stages")
    src_sha = sha256_bytes(src)
    sp = superseded_path(unit, src_sha)
    sp.parent.mkdir(parents=True, exist_ok=True)
    if not sp.is_file():
        tmp = sp.with_name(sp.name + ".tmp")
        tmp.write_bytes(src)
        os.replace(tmp, sp)
    png = tex.read_bytes()
    g.replace_image(ii, png)
    out = g.to_bytes()
    glb = S.glb_path(unit)
    tmp = glb.with_name(glb.name + ".unit_look.tmp")
    tmp.write_bytes(out)
    os.replace(tmp, glb)
    stamp = {"schema": S.STAMP_SCHEMA, "unit": unit, "appliedAt": dt.datetime.now().isoformat(timespec="seconds"),
             "specSha256": S.canonical_sha(spec), "knobsSha256": S.knobs_sha(spec),
             "mode": spec["lighting"]["mode"],
             "frontResolved": json.loads((outd / "metrics.json").read_text())["lighting"].get("frontResolved"),
             "sourceGlbSha256": src_sha, "geometrySha256": geo, "basecolorSha256": sha256_bytes(png),
             "deliveredGlbSha256": sha256_bytes(out), "vfxManifestSha256": sha256_file(man),
             "superseded": str(sp.relative_to(outd)).replace("\\", "/"),
             "deliveredGlbStat": {"size": glb.stat().st_size, "mtimeNs": glb.stat().st_mtime_ns},
             "glbAnimations": sorted(g.animation_names()), "glbJoints": sorted(g.joint_names()),
             "floorLights": held,
             "finish": ({k: fin.get(k) for k in ("mode", "inputSha256", "codeSha256")} if fin is not None
                        else {"mode": "absent", "note": "fitted before the finish stage existed: the delivered base colour is A"}),
             "proof": "generated artifact: GLB base colour swapped offline; not built into a bundle, not in game"}
    (outd / "stamp.json").write_text(json.dumps(stamp, indent=1))
    log(unit, f"applied: GLB {stamp['deliveredGlbSha256'][:12]} (source {src_sha[:12]} from {where})")
    r = subprocess.run([sys.executable, str(ROOT / "tools/validate_homm3_unit_look_contract.py"), "--unit", unit, "--require-delivered"])
    if r.returncode != 0:
        raise StageError(5, "validator failed after apply")
    if KEEP_WORK[0]:
        log(unit, "work/ kept (--keep-work)")
    else:
        log(unit, f"pruned work/ (views, look_tex_lin; terms kept for the next rebuild) after a validated apply: "
                  f"{prune_work(unit, keep_terms=True) / 1e9:.2f} GB freed (--keep-work keeps it all)")


# ----------------------------------------------------------------------------- per unit
def stage_accept_raw(unit, reason: str) -> None:
    """Deliver the un-prebaked GLB (a rawAccepted stamp) when every grade mode in S.MODES, fitted by --try-modes on
    this very GLB with the current knobs, is further from the DEF than the raw base colour (body L-hist, the metric
    apply's regression gate uses). Fail closed: no reason, a missing or stale try, a mode that ties or wins, VFX built
    from another spec, or a non-PNG raw image refuses. Writes the GLB (restoring the un-prebaked original if a look
    was applied), raw_basecolor.png (the GLB's own body image bytes) and stamp.json, then runs the validator."""
    if not (reason or "").strip():
        raise StageError(2, "--accept-raw needs a reason")
    sp = S.spec_path(unit)
    if not sp.is_file():
        raise StageError(2, f"no spec {sp}")
    spec = S.load(sp)
    if spec["status"] == "excluded":
        raise StageError(2, "an excluded unit takes no look stamp")
    outd = S.out_dir(unit)
    src, where = resolve_source(unit)
    src_sha = sha256_bytes(src)
    g = Glb(src)
    img = g.image_bytes(g.body_base_color_image())
    transcode = None
    if not img.startswith(b"\x89PNG\r\n\x1a\n"):
        # the basecolor albedo lane ships PNG only: a JPEG raw image is re-encoded losslessly from its decoded
        # pixels (what every try measured), verified, and the original bytes kept for the validator
        if not img.startswith(b"\xff\xd8\xff"):
            raise StageError(5, "the GLB's body base colour is neither PNG nor JPEG; the basecolor albedo lane ships PNG only")
        import io
        from PIL import Image
        pix = S.image_pixels_sha256(img)
        buf = io.BytesIO()
        Image.open(io.BytesIO(img)).save(buf, format="PNG")
        png = buf.getvalue()
        if S.image_pixels_sha256(png) != pix:
            raise StageError(5, "PNG transcode of the JPEG raw base colour changed its pixels")
        transcode = {"from": "image/jpeg", "sourceImageFile": S.RAW_SOURCE_IMAGE, "sourceImageSha256": sha256_bytes(img),
                     "pngSha256": sha256_bytes(png), "pixelsSha256": pix,
                     "rule": "decoded JPEG pixels re-encoded as PNG, pixel-identical; only the body image changes"}
    tried, raws = {}, set()
    for mode in S.MODES:
        mp = outd / f"try_{mode}_metrics.json"
        if not mp.is_file():
            raise StageError(3, f"no {mp.name}; run look.py {unit} --try-modes")
        mj = json.loads(mp.read_text())
        got = (mj.get("source") or {}).get("glbSha256")
        if got != src_sha:
            raise StageError(5, f"{mp.name} was not measured on this GLB ({str(got)[:12]} != {src_sha[:12]}); "
                                f"rerun look.py {unit} --try-modes")
        ms = dict(spec, lighting=dict(spec["lighting"], mode=mode))
        if (mj.get("lighting") or {}).get("knobsSha256") != S.knobs_sha(ms):
            raise StageError(5, f"{mp.name} was fitted from other lighting knobs; rerun look.py {unit} --try-modes")
        sm = (mj.get("review") or {}).get("summary") or {}
        if sm.get("meanLhistBodyLook") is None or sm.get("meanLhistBodyRaw") is None:
            raise StageError(4, f"{mp.name} carries no review body L-hist")
        tried[mode] = {"lhistBody": sm["meanLhistBodyLook"], "lhistWithEffects": sm.get("meanLhistWithEffects"),
                       "knobsSha256": S.knobs_sha(ms), "metrics": mp.name, "metricsSha256": sha256_file(mp)}
        raws.add(sm["meanLhistBodyRaw"])
    if len(raws) != 1:
        raise StageError(5, f"the try runs disagree on the raw body L-hist {sorted(raws)}")
    raw = raws.pop()
    man = outd / "vfx/vfx_manifest.json"
    mj = json.loads((outd / "metrics.json").read_text()) if (outd / "metrics.json").is_file() else {}
    if not man.is_file() or (mj.get("vfx") or {}).get("specSha256") != S.canonical_sha(spec):
        raise StageError(5, f"the VFX assets were not built from the current spec (--try-modes builds them per mode); "
                            f"run look.py {unit} --stages bake,fit,vfx,review first")
    glb = S.glb_path(unit)
    out = src
    if transcode:
        src_img = img
        geo = g.geometry_sha256()
        g.replace_image(g.body_base_color_image(), png)
        out = g.to_bytes()
        g = Glb(out)
        if g.geometry_sha256() != geo or g.image_bytes(g.body_base_color_image()) != png:
            raise StageError(5, "the PNG transcode changed more than the body image")
        img = png
        (outd / S.RAW_SOURCE_IMAGE).write_bytes(src_img)
    if sha256_file(glb) != sha256_bytes(out):
        tmp = glb.with_name(glb.name + ".unit_look.tmp")
        tmp.write_bytes(out)
        os.replace(tmp, glb)
        log(unit, f"wrote the raw delivery {sha256_bytes(out)[:12]} from the un-prebaked GLB {src_sha[:12]} ({where})"
                  + (", JPEG body image transcoded to a pixel-identical PNG" if transcode else ""))
    (outd / S.RAW_BASECOLOR).write_bytes(img)
    held = [ly["id"] for ly in spec["vfx"]["layers"] if ly["type"] == "effectLight" and ly.get("floor")]
    stamp = {"schema": S.STAMP_SCHEMA, "unit": unit, "kind": S.RAW_ACCEPTED,
             "appliedAt": dt.datetime.now().isoformat(timespec="seconds"),
             "specSha256": S.canonical_sha(spec), "knobsSha256": S.knobs_sha(spec), "mode": spec["lighting"]["mode"],
             "rawAccepted": {"reason": reason.strip(), "rawLhistBody": raw, "modesTried": tried,
                             "rule": "raw body L-hist strictly below every S.MODES grade's, each fitted by --try-modes "
                                     "on this GLB with the current knobs (spec.raw_accepted_errors)"},
             "sourceGlbSha256": src_sha, "geometrySha256": g.geometry_sha256(), "basecolorSha256": sha256_bytes(img),
             "basecolorFile": S.RAW_BASECOLOR, "deliveredGlbSha256": sha256_bytes(out), "vfxManifestSha256": sha256_file(man),
             **({"rawTranscode": transcode} if transcode else {}),
             "superseded": None,
             "deliveredGlbStat": {"size": glb.stat().st_size, "mtimeNs": glb.stat().st_mtime_ns},
             "glbAnimations": sorted(g.animation_names()), "glbJoints": sorted(g.joint_names()),
             "floorLights": held,
             "proof": "generated artifact: the un-prebaked GLB delivered as is; not built into a bundle, not in game"}
    errs = S.raw_accepted_errors(stamp)
    if errs:
        raise StageError(5, "raw base colour not accepted: " + "; ".join(errs))
    (outd / "stamp.json").write_text(json.dumps(stamp, indent=1))
    log(unit, f"rawAccepted: GLB {src_sha[:12]}, raw body L-hist {raw} < " +
        ", ".join(f"{m} {v['lhistBody']}" for m, v in tried.items()))
    r = subprocess.run([sys.executable, str(ROOT / "tools/validate_homm3_unit_look_contract.py"), "--unit", unit, "--require-delivered"])
    if r.returncode != 0:
        raise StageError(5, "validator failed after accept-raw")


def run_unit(unit, stages, force=False, mode_override=None, glb_bytes: bytes | None = None) -> int:
    """glb_bytes: the un-looked def_retarget GLB in memory (the apply stage only; fleet_rebuild.py's fused delivery
    stages), installed as S.glb_bytes for the whole run so every check measures it; apply then writes the delivered
    GLB, the one GLB write of the run (plus the superseded original, once per source)."""
    if glb_bytes is None:
        return _run_unit(unit, stages, force, mode_override)
    if list(stages) != ["apply"] or force or mode_override:
        raise ValueError("glb_bytes is the in-memory input of the apply stage alone")
    with S.glb_in_memory(unit, glb_bytes):
        return _run_unit(unit, stages, force, mode_override)


def _run_unit(unit, stages, force=False, mode_override=None) -> int:
    t0 = time.time()
    try:
        sp = S.spec_path(unit)
        if not sp.is_file():
            raise StageError(2, f"no spec {sp}")
        spec = S.load(sp)
        if mode_override:
            spec["lighting"]["mode"] = mode_override
        try:
            clips = S.clip_segments(unit)
        except FileNotFoundError as e:
            raise StageError(3, f"missing build input: {e}")
        errs = S.validate(spec, sp.stem, clips, None, S.build_info(unit))
        if errs:
            raise StageError(2, "spec errors:\n  " + "\n  ".join(errs))
        if spec["status"] == "excluded":
            log(unit, f"excluded: {spec['excludedReason']}")
            return 0
        outd = S.out_dir(unit)
        outd.mkdir(parents=True, exist_ok=True)
        if "bake" in stages:
            stage_bake(unit, spec, force)
        need_ctx = any(s in stages for s in ("fit", "vfx", "review"))
        if need_ctx:
            import lighting as LT
            import review as RV
            import vfx as VX
            ctx = build_ctx(unit, spec)
            mpath = outd / "metrics.json"
            metrics = json.loads(mpath.read_text()) if mpath.is_file() else {}
            metrics.update({"schema": "homm3_unit_look_metrics.v1", "unit": unit,
                            "proof": "generated artifact: numpy relight of Blender passes (Hex/Lit model) + 2D effect composite"})
            work = outd / "work"
            if "fit" in stages:
                disk_preflight(unit, "fit")
                # the fit rewrites these when the spec has regions; a stale pair (regions since removed) must not
                # survive into vfx now that work/ is no longer wiped by every rebuild (fleet_rebuild dropped --force)
                (work / "regions_fit.json").unlink(missing_ok=True)
                for stale in work.glob("region_*_palette.npy"):
                    stale.unlink()
                lres = LT.run(unit, spec, work, outd, ctx)
                fsrc = json.loads((work / "fit_source.json").read_text()).get("front", {})
                lres["frontResolved"] = {"axis": fsrc.get("axis"), "source": fsrc.get("source"),
                                         "vector": ctx["vmeta"]["front"]}
                lres["knobsSha256"] = S.knobs_sha(spec)
                metrics["lighting"] = lres
                if lres["boundHits"]:
                    log(unit, f"FLAG bound hits: {lres['boundHits']}")
            if "finish" in stages:
                stage_finish(unit, spec, metrics, fitted_now="fit" in stages)
            if not (outd / "basecolor.png").is_file():
                raise StageError(4, "no basecolor.png; run the fit stage")
            tex_lin = np.load(work / "look_tex_lin.npy").astype(np.float32)
            vres = None
            if "vfx" in stages or "review" in stages:
                try:
                    vres = VX.run(spec, ctx, outd / "vfx", tex_lin, work)
                except VX.VfxNotSupported as e:
                    raise StageError(4, str(e))
                if vres["fittedIntensity"] and "vfx" in stages and not mode_override:
                    changed = False
                    for ly in spec["vfx"]["layers"]:
                        if ly["id"] in vres["fittedIntensity"] and ly["intensity"] != vres["fittedIntensity"][ly["id"]]:
                            ly["intensity"] = vres["fittedIntensity"][ly["id"]]
                            changed = True
                    if changed:
                        sp.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
                        log(unit, "spec updated with fitted light intensities")
                        vres = VX.run(spec, ctx, outd / "vfx", tex_lin, work)
                metrics["vfx"] = {"layers": list(vres["manifest"]["layers"]), "fittedIntensity": vres["fittedIntensity"],
                                  "specSha256": S.canonical_sha(spec)}
            if "review" in stages:
                try:
                    rres = RV.run(spec, ctx, outd, tex_lin, vres)
                except RV.ReviewError as e:
                    raise StageError(4, f"review: {e}")
                metrics["review"] = rres
                s = rres["summary"]
                log(unit, f"review: body L-hist {s['meanLhistBodyRaw']} raw -> {s['meanLhistBodyLook']} look; "
                          f"with effects {s['meanLhistWithEffects']}; yaw {s['yawSpreadL']}")
                if s.get("excludedFromBody"):
                    log(unit, f"review: {len(s['excludedFromBody'])} key(s) excluded from the body metric: {s['excludedFromBody']}")
                for w in s.get("warnings", []):
                    log(unit, f"review WARNING: {w}")
            mpath.write_text(json.dumps(metrics, indent=1), encoding="utf-8")
        elif "finish" in stages:
            mpath = outd / "metrics.json"
            if not mpath.is_file():
                raise StageError(4, "no metrics.json; run the fit stage first")
            metrics = json.loads(mpath.read_text())
            stage_finish(unit, spec, metrics, fitted_now=False)
            mpath.write_text(json.dumps(metrics, indent=1), encoding="utf-8")
        if mode_override:
            for name in ("metrics.json", "basecolor.png", "review_sheet.png"):
                if (outd / name).is_file():
                    shutil.copy2(outd / name, outd / f"try_{mode_override}_{name}")
            tp = outd / f"try_{mode_override}_metrics.json"
            if tp.is_file():
                # bind the try to the GLB it measured, so --accept-raw can refuse a try from an earlier build
                src, where = resolve_source(unit)
                fsj = json.loads((outd / "work/fit_source.json").read_text())
                tj = json.loads(tp.read_text())
                tj["source"] = {"glbSha256": sha256_bytes(src), "from": where, "geometrySha256": fsj["geometrySha256"],
                                "sourceBasecolorSha256": fsj["sourceBasecolorSha256"]}
                tp.write_text(json.dumps(tj, indent=1), encoding="utf-8")
        if "apply" in stages:
            if mode_override:
                raise StageError(2, "--try-modes never applies")
            stage_apply(unit, S.load(sp))
        log(unit, f"OK ({time.time() - t0:.0f}s)")
        return 0
    except StageError as e:
        log(unit, f"FAIL exit {e.code}: {e}")
        return e.code
    except Exception:
        traceback.print_exc()
        log(unit, "FAIL exit 4: unexpected error")
        return 4


def try_mode_stages(stages) -> list[str]:
    """The stages one --try-modes pass runs: never apply, and never finish. The try is compared with what the rebuild's
    review and stage_apply's regression gate measure, which is the fitted look A (fleet_rebuild LOOK_REVIEW_STEP reviews
    before LOOK_FINISH_STEP); a finish before the review would score look B instead (2026-10-12 hota_cove_crew_mate:
    v7c 2.33 in a bare --try-modes vs 5.1 in the rebuild, raw 5.05; h3_ghost_dragon 2026-10-11 hit the same order)."""
    return [s for s in stages if s not in ("apply", "finish")]


def try_source_label(unit, src: dict) -> str:
    """'<from> <path> sha <12>' for the source block a --try-modes pass records in try_<mode>_metrics.json."""
    sha, where = src.get("glbSha256") or "", src.get("from") or "?"
    path = superseded_path(unit, sha) if where == "superseded" and sha else S.glb_path(unit)
    return f"{where} {path} sha {sha[:12] or '?'}"


# ----------------------------------------------------------------------------- summary
def summary() -> int:
    from PIL import Image, ImageDraw
    rows = []
    for d in sorted(S.OUT_ROOT.iterdir()) if S.OUT_ROOT.is_dir() else []:
        mp = d / "metrics.json"
        if not d.is_dir() or not mp.is_file():
            continue
        m = json.loads(mp.read_text())
        if "review" not in m:
            continue
        s = m["review"]["summary"]
        st = read_stamp(d.name)
        rows.append({"unit": d.name, "mode": m.get("lighting", {}).get("mode"),
                     "LhistWithEffects": s["meanLhistWithEffects"], "LhistBodyLook": s["meanLhistBodyLook"],
                     "LhistBodyRaw": s["meanLhistBodyRaw"], "yawSpreadL": s["yawSpreadL"],
                     "boundHits": m.get("lighting", {}).get("boundHits", []),
                     "vfxLayers": m.get("vfx", {}).get("layers", []), "applied": bool(st),
                     "worstView": s["worstView"]})
    rows.sort(key=lambda r: -r["LhistWithEffects"])
    doc = {"schema": "homm3_unit_look_roster.v1", "generated": dt.datetime.now().isoformat(timespec="seconds"),
           "proof": "generated artifact", "rankedWorstFirst": rows}
    tmp = S.OUT_ROOT / "ROSTER_SUMMARY.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1))
    os.replace(tmp, S.OUT_ROOT / "ROSTER_SUMMARY.json")
    lines = ["# Unit look roster summary", "", "Generated by `look.py --summary`; ranked by the with-effects L-histogram "
             "distance to the DEF, worst first. Proof: generated artifact.", "",
             "| # | unit | mode | L-hist with FX | body look | body raw | yaw sand/grass | bound hits | VFX layers | applied |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows):
        y = r["yawSpreadL"]
        lines.append(f"| {i + 1} | {r['unit']} | {r['mode']} | {r['LhistWithEffects']} | {r['LhistBodyLook']} | {r['LhistBodyRaw']} | "
                     f"{y.get('sand')}/{y.get('grass')} | {len(r['boundHits'])} | {len(r['vfxLayers'])} | {'yes' if r['applied'] else 'no'} |")
    tmp = S.OUT_ROOT / "ROSTER_SUMMARY.md.tmp"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, S.OUT_ROOT / "ROSTER_SUMMARY.md")
    ims = []
    for r in rows[:10]:
        p = S.OUT_ROOT / r["unit"] / "review_worst_row.png"
        if p.is_file():
            ims.append((r, Image.open(p).convert("RGB")))
    if ims:
        w = max(i.width for _, i in ims)
        h = sum(i.height + 16 for _, i in ims)
        sheet = Image.new("RGB", (w, h), (30, 30, 30))
        y = 0
        dr = ImageDraw.Draw(sheet)
        for r, im in ims:
            dr.text((4, y + 2), f"{r['unit']} ({r['mode']}) L-hist with FX {r['LhistWithEffects']}  body {r['LhistBodyLook']} (raw {r['LhistBodyRaw']})",
                    fill=(235, 235, 235))
            sheet.paste(im, (0, y + 16))
            y += im.height + 16
        tmp = S.OUT_ROOT / "WORST10_sheet.tmp.png"
        sheet.save(tmp)
        os.replace(tmp, S.OUT_ROOT / "WORST10_sheet.png")
    print(f"summary: {len(rows)} units -> {S.OUT_ROOT / 'ROSTER_SUMMARY.md'}")
    return 0


def faction_units(path: Path) -> list[str]:
    """Units of a faction roster that have a spec (roster slots resolved as roster_status.py does)."""
    # roster_status runs its report at import and reads sys.argv; give it none and swallow the report.
    # Its folder leaves sys.path again afterwards: it holds a Blender review.py that would shadow ours.
    import contextlib, io
    rdir = str(ROOT / "tools/homm3_def_retarget")
    argv, sys.argv = sys.argv, sys.argv[:1]
    sys.path.insert(0, rdir)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import roster_status as RS  # noqa: WPS433 (read-only use of the shared script's resolver)
    finally:
        sys.argv = argv
        sys.path.remove(rdir)
    fac = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for line in fac.get("unitLines", []):
        for v, name in enumerate(line.get("names", [])):
            for cand in RS.candidates(line, v, name):
                if S.spec_path(cand).is_file():
                    out.append(cand)
                    break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("units", nargs="*")
    ap.add_argument("--faction", type=Path)
    ap.add_argument("--stages", default=",".join(DEFAULT_STAGES))
    ap.add_argument("--force", action="store_true", help="rebake from scratch (wipes work/) even when the cache keys match")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--keep-work", action="store_true",
                    help="do not prune work/terms, work/views and look_tex_lin.npy after a validated apply")
    ap.add_argument("--prune-applied", action="store_true",
                    help="only prune: for the given units (or --all) whose stamp validates, delete the regenerable "
                         "work/ bulk; unapplied or failing units are never touched")
    ap.add_argument("--prune-superseded", action="store_true",
                    help="only prune: for the given units (or --all) whose stamp validates, delete every "
                         "_superseded_do_not_use/*.glb.unprebaked except the stamp's sourceGlbSha256 original")
    ap.add_argument("--compact-terms", action="store_true",
                    help="only re-store work/terms/*.npy as lossless compressed .npz (given units or --all)")
    ap.add_argument("--all", action="store_true", help="with --prune-applied / --prune-superseded / --compact-terms: every unit folder")
    ap.add_argument("--bake-timeout", type=float, default=None,
                    help="seconds per Blender bake launch (default: env HOMM3_BAKE_TIMEOUT, else 1800); a timed-out "
                         "bake keeps its finished terms and a rerun resumes")
    ap.add_argument("--try-modes", action="store_true",
                    help="fit + review both grade modes (v7c, v6m) as look A (no finish, like the rebuild's review) without "
                         "touching the spec or the GLB; writes "
                         "try_<mode>_metrics.json / _basecolor.png / _review_sheet.png and prints which is closer")
    ap.add_argument("--accept-raw", metavar="REASON",
                    help="deliver the un-prebaked GLB with a rawAccepted stamp (every mode lost to raw in --try-modes)")
    a = ap.parse_args()
    if a.accept_raw is not None:
        if not a.units or a.faction or a.try_modes:
            ap.error("--accept-raw takes named units only")
        codes = {}
        for u in dict.fromkeys(a.units):
            try:
                stage_accept_raw(u, a.accept_raw)
                codes[u] = 0
            except StageError as e:
                log(u, f"FAIL exit {e.code}: {e}")
                codes[u] = e.code
        print("\n".join(f"STATUS {u} {'ok' if c == 0 else f'exit {c}'}" for u, c in codes.items()))
        return max(codes.values())
    if a.bake_timeout is not None:
        BAKE_TIMEOUT[0] = a.bake_timeout
    KEEP_WORK[0] = a.keep_work
    if a.prune_applied or a.prune_superseded or a.compact_terms:
        us = list(a.units)
        if a.faction:
            us += faction_units(a.faction if a.faction.is_absolute() else ROOT / a.faction)
        if a.all:
            us += [d.name for d in sorted(S.OUT_ROOT.iterdir())
                   if d.is_dir() and ((d / "work").is_dir() or (a.prune_superseded and (d / S.SUPERSEDED).is_dir()))]
        if not us:
            ap.error("--prune-applied / --prune-superseded / --compact-terms need units, --faction or --all")
        us = list(dict.fromkeys(us))
        if a.prune_superseded:
            return prune_superseded(us)
        return prune_applied(us) if a.prune_applied else compact_all(us)
    if a.summary:
        return summary()
    stages = [s for s in a.stages.split(",") if s]
    bad = [s for s in stages if s not in STAGES]
    if bad:
        ap.error(f"unknown stages {bad}")
    units = list(a.units)
    if a.faction:
        fac = faction_units(a.faction if a.faction.is_absolute() else ROOT / a.faction)
        if not a.force:
            # a faction sweep leaves delivered units alone: their work/ is pruned, so rerunning them
            # would rebake from scratch for an identical result. Name a unit (or --force) to redo it.
            done = [u for u in fac if read_stamp(u) is not None and stamp_validates(u)]
            for u in done:
                print(f"STATUS {u} applied (stamp validates; skipped by --faction)")
            fac = [u for u in fac if u not in done]
        units += fac
    if not units:
        ap.error("no units")
    if a.try_modes:
        stages = try_mode_stages(stages)
        codes = {}
        for u in dict.fromkeys(units):
            res, srcs = {}, set()
            for mode in S.MODES:
                c = run_unit(u, stages, a.force, mode_override=mode)
                codes[u] = max(codes.get(u, 0), c)
                mp = S.out_dir(u) / f"try_{mode}_metrics.json"
                if c == 0 and mp.is_file():
                    tj = json.loads(mp.read_text())
                    res[mode] = tj["review"]["summary"]
                    srcs.add(try_source_label(u, tj.get("source") or {}))
            if res:
                best = min(res, key=lambda k: res[k]["meanLhistWithEffects"])
                # the GLB measured: resolve_source's choice (the stamp's superseded original when the GLB on disk is
                # the stamped delivery -- a failed fleet rebuild rolls its new GLB back, so a try then measures the
                # old build, 2026-10-12 hota_cove_ayssid run-618)
                print(f"TRYMODES {u} measured {' | '.join(sorted(srcs))}")
                print(f"TRYMODES {u} look A (pre-finish) " + "  ".join(f"{k}: fx {v['meanLhistWithEffects']} body {v['meanLhistBodyLook']} yaw {v['yawSpreadL']}"
                                                   for k, v in res.items()) + f"  -> closer: {best}")
        print("\n".join(f"STATUS {u} {'ok' if c == 0 else f'exit {c}'}" for u, c in codes.items()))
        return max(codes.values()) if codes else 0
    codes = {u: run_unit(u, stages, a.force) for u in dict.fromkeys(units)}
    print("\n".join(f"STATUS {u} {'ok' if c == 0 else f'exit {c}'}" for u, c in codes.items()))
    return max(codes.values()) if codes else 0


if __name__ == "__main__":
    raise SystemExit(main())
