"""Validate the DEF-retarget emphasis delivery contract (docs/homm3_def_retarget_emphasis.md).

    python tools/validate_homm3_def_retarget_emphasis_contract.py [--repo-root R] [--unit U ...]
           [--require-complete] [--require-current]

Always (source/static):
- tools/homm3_def_retarget_emphasis/exceptions.json parses; every entry has a known kind and a
  non-empty reason; no unknown keys.
- every per-unit config in tools/homm3_def_retarget_emphasis/units/ loads (unknown keys are errors)
  and names a unit with a retarget config.

For every roster unit (a canonical artifacts/homm3_def_retarget/<u>/<u>_def_retarget.glb; artifacts
are not in git, so a fresh clone validates the static part only):
- it has an exceptions.json entry or a stamp (artifacts/homm3_def_retarget_emphasis/<u>/stamp.json);
  a unit with neither is a note, an ERROR with --require-complete.
- the stamp's version and paramsSha256 equal the current module version and unit config (ERROR:
  the delivered keys were made with other parameters; re-run deliver.py).
- the canonical .blend is the one the stamp describes (emphasisedBlendSha256 when emphasised,
  sourceBlendSha256 otherwise). A rebuild since then is a note (the unit is simply not emphasised
  now), an ERROR with --require-current.
For an emphasised, current unit:
- the canonical GLB is the emphasised export (emphasisedGlbSha256), or the unit-look delivery made
  from it through the delivery stages (delivery_chain_errors): look stamp deliveredGlbSha256 == the
  GLB, and the stage stamps in its asset.extras (DELIVERY_STAGES order: glb patch, deyaw, stride match, move
  low-pass, densify, prop floor, CS re-key, ground) link back to the emphasised export. The first stage's
  sourceGlbSha256 is emphasisedGlbSha256 (no stage: the look's source is); every stage has its own
  source; where a stage recorded its output (the <glb>.<stage>.json sidecar of prop floor and
  ground) the next stage's source, or the look's source after the last stage, is that output.
  An unknown delivery stamp or a broken link fails;
  its asset.extras.homm3DefRetargetEmphasis equals the stamp's glbExtras.
- the stored key dumps pass emphasis.check_invariants: no key changes outside the emphasised clips,
  every clip's first frame and every non-Death clip's last frame unchanged, hidden-body frames
  unchanged, zero Hips/leg/contact-chain drift, extra rotation within maxExtraDeg.
- actions.json: only Unit_ actions inside emphasised clips were rewritten; never Idle or Move.
- glb_verify.json (the shared verify_glb.py round trip on the installed build): every action's keys
  match and bone/mesh error is within tolerance; Idle and Move close their loops (their keys are
  pinned unchanged by the key invariants and actions.json).
- every emphasised clip passed the stretch gate.
A stretchGateFailed stamp is a note (the unit is not emphasised and awaits a per-unit config or an
exception), an ERROR with --require-complete.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import struct
import sys

KINDS = {"pendingRebuild", "notARosterUnit", "unreliableMetric", "handKeyed", "stretchCost", "noActionClips"}


def glb_json(p):
    with open(p, "rb") as f:
        head = f.read(20)
        if head[:4] != b"glTF":
            raise ValueError(f"{p}: not a GLB")
        ln = struct.unpack_from("<I", head, 12)[0]
        return json.loads(f.read(ln).decode("utf-8"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


# the delivery stages between the emphasised export and the unit look, in fleet_rebuild.py order:
# (asset.extras stamp, sidecar suffix recording the stage's outputGlbSha256 or None)
DELIVERY_STAGES = (("homm3DefRetargetDeliveryPatch", "patch"), ("homm3DefRetargetDeliveryDeyaw", "deyaw"), ("homm3DefRetargetDeliveryStrideMatch", "stride_match"),
                   ("homm3DefRetargetDeliveryMoveLowPass", "move_lowpass"), ("homm3DefRetargetDeliveryDensify", "densify"),
                   ("homm3DefRetargetDeliveryPropFloor", "prop_floor"), ("homm3DefRetargetDeliveryCsRekey", "cs_rekey"),
                   ("homm3DefRetargetDeliveryGround", "ground"))
DELIVERY_PREFIX = "homm3DefRetargetDelivery"


def delivery_chain_errors(emphasised: str, glb_sha: str, extras: dict, look: dict, sidecars: dict) -> list:
    """Why the canonical GLB (glb_sha, asset.extras) is not the look's delivery of the emphasised export through the
    stamped delivery stages ([] = it is). sidecars: {suffix: parsed <glb>.<suffix>.json}."""
    if glb_sha == emphasised:
        return []
    errs = []
    if look.get("deliveredGlbSha256") != glb_sha:
        errs.append(f"look stamp deliveredGlbSha256 {str(look.get('deliveredGlbSha256'))[:12]} is not the canonical "
                    f"GLB {glb_sha[:12]}")
    known = {k for k, _ in DELIVERY_STAGES}
    for k in sorted(extras):
        if k.startswith(DELIVERY_PREFIX) and k not in known:
            errs.append(f"unknown delivery stage stamp {k}")
    chain = [(k, side, extras[k]) for k, side in DELIVERY_STAGES if k in extras]
    link, prev = emphasised, "the emphasised export"
    seen = set()
    for k, side, st in chain:
        src = st.get("sourceGlbSha256") if isinstance(st, dict) else None
        if not (isinstance(src, str) and len(src) == 64):
            errs.append(f"{k} has no sourceGlbSha256")
            return errs
        if link is not None and src != link:
            errs.append(f"{k} ran on {src[:12]}, not on {prev} {link[:12]}")
        if src in seen:
            errs.append(f"{k} ran on {src[:12]}, the input of an earlier stage")
        seen.add(src)
        rec = sidecars.get(side) if side else None
        if rec is not None and rec.get("sourceGlbSha256") == src and isinstance(rec.get("outputGlbSha256"), str):
            link, prev = rec["outputGlbSha256"], f"{k}'s recorded output"
        else:
            link, prev = None, None       # an unrecorded output: the next stage must still be a new input
    ls = look.get("sourceGlbSha256")
    if not chain:
        if ls != emphasised:
            errs.append(f"look source {str(ls)[:12]} is not the emphasised export {emphasised[:12]} and no delivery "
                        "stage is stamped")
    elif link is not None and ls != link:
        errs.append(f"look source {str(ls)[:12]} is not {prev} {link[:12]}")
    elif ls in seen:
        errs.append(f"look source {str(ls)[:12]} is the input of a delivery stage, not the last stage's output")
    return errs


def sha_fast(p, stat, known):
    """sha256 of p, or `known` when p keeps the size/mtime recorded next to that hash."""
    s = os.stat(p)
    if stat and [s.st_size, s.st_mtime_ns] == list(stat) and known:
        return known
    return sha(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--unit", action="append")
    ap.add_argument("--require-complete", action="store_true")
    ap.add_argument("--require-current", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.repo_root)
    tdir = os.path.join(root, "tools", "homm3_def_retarget_emphasis")
    sys.path.insert(0, tdir)
    import emphasis as E  # noqa: E402
    import numpy as np  # noqa: E402
    errors, notes = [], []

    # ---- static
    exc_p = os.path.join(tdir, "exceptions.json")
    try:
        ex = json.load(open(exc_p, encoding="utf-8"))
        if ex.get("schema") != "homm3_def_retarget_emphasis.exceptions.v1":
            errors.append(f"{exc_p}: schema {ex.get('schema')!r}")
        exc = ex.get("exceptions", {})
        for u, e in exc.items():
            bad = set(e) - {"kind", "reason", "units", "evidence"}
            if bad:
                errors.append(f"exceptions.json {u}: unknown keys {sorted(bad)}")
            if e.get("kind") not in KINDS:
                errors.append(f"exceptions.json {u}: kind {e.get('kind')!r} not in {sorted(KINDS)}")
            if not str(e.get("reason", "")).strip():
                errors.append(f"exceptions.json {u}: empty reason")
    except Exception as x:  # noqa: BLE001
        errors.append(f"{exc_p}: {x!r}"); exc = {}
    for p in sorted(glob.glob(os.path.join(tdir, "units", "*.json"))):
        u = os.path.basename(p)[:-5]
        try:
            E.load_cfg(u)
        except Exception as x:  # noqa: BLE001
            errors.append(f"{p}: {x}")
        if not os.path.exists(os.path.join(root, "tools", "homm3_def_retarget", "units", f"{u}.json")):
            errors.append(f"{p}: no retarget config for {u}")
        if u in exc:
            errors.append(f"{u}: has both a per-unit config and an exception")

    # ---- artifacts
    src = os.path.join(root, "artifacts", "homm3_def_retarget")
    out = os.path.join(root, "artifacts", "homm3_def_retarget_emphasis")
    units = a.unit or sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(src, "*", "*_def_retarget.glb"))
                             if os.path.basename(p) == os.path.basename(os.path.dirname(p)) + "_def_retarget.glb")
    counts = {}
    for u in units:
        cdir = os.path.join(src, u); glb = os.path.join(cdir, f"{u}_def_retarget.glb")
        blend = os.path.join(cdir, f"{u}_def_retarget.blend"); W = os.path.join(out, u)
        stp = os.path.join(W, "stamp.json")
        if u in exc:
            counts["exception"] = counts.get("exception", 0) + 1
            if os.path.exists(stp):
                st = json.load(open(stp))
                if st.get("decision") == "emphasised" and os.path.exists(blend) and sha(blend) == st.get("emphasisedBlendSha256"):
                    errors.append(f"{u}: listed as an exception but its canonical build is emphasised")
            continue
        if not os.path.exists(stp):
            (errors if a.require_complete else notes).append(f"{u}: no emphasis stamp and no exception")
            counts["pending"] = counts.get("pending", 0) + 1
            continue
        st = json.load(open(stp))
        dec = st.get("decision"); counts[dec] = counts.get(dec, 0) + 1
        if st.get("version") != E.VERSION:
            errors.append(f"{u}: stamp version {st.get('version')} != {E.VERSION}")
        try:
            if st.get("paramsSha256") != E.params_sha(E.load_cfg(u)):
                errors.append(f"{u}: stamp paramsSha256 differs from the current config; re-run deliver.py {u} --force")
        except Exception as x:  # noqa: BLE001
            errors.append(f"{u}: config {x}")
        if dec == "stretchGateFailed":
            (errors if a.require_complete else notes).append(f"{u}: stretch gate failed; needs a per-unit config or an exception")
            continue
        if not os.path.exists(blend):
            notes.append(f"{u}: canonical .blend missing locally"); continue
        want = st.get("emphasisedBlendSha256") if dec == "emphasised" else st.get("sourceBlendSha256")
        bsha = sha_fast(blend, st.get("blendStat"), want)
        if bsha != want:
            (errors if a.require_current else notes).append(f"{u}: canonical .blend rebuilt since the emphasis pass ({dec}); re-run deliver.py {u}")
            continue
        if dec != "emphasised":
            continue
        # GLB identity + stamp
        gsha = sha_fast(glb, st.get("glbStat"), st.get("emphasisedGlbSha256"))
        look = os.path.join(root, "artifacts", "homm3_unit_look", u, "stamp.json")
        lst = json.load(open(look)) if os.path.exists(look) else {}
        gextras = glb_json(glb).get("asset", {}).get("extras") or {}
        sidecars = {}
        for _, side in DELIVERY_STAGES:
            sp = f"{glb}.{side}.json" if side else None
            if sp and os.path.exists(sp):
                sidecars[side] = json.load(open(sp))
        for e in delivery_chain_errors(st["emphasisedGlbSha256"], gsha, gextras, lst, sidecars):
            errors.append(f"{u}: canonical GLB is not look's delivery of the emphasised export: {e}")
        ext = gextras.get("homm3DefRetargetEmphasis")
        if ext != st.get("glbExtras"):
            errors.append(f"{u}: GLB asset.extras.homm3DefRetargetEmphasis {ext} != stamp glbExtras")
        # key invariants
        try:
            pl = json.load(open(os.path.join(W, "plan.json")))
            kb = dict(np.load(os.path.join(W, "keys_before.npz"))); ka = dict(np.load(os.path.join(W, "keys_after.npz")))
            for e in E.check_invariants(kb, ka, pl["detect"], pl["plan"], st["cfg"]):
                errors.append(f"{u}: {e}")
            rng = [pl["detect"][c]["range"] for c, i in pl["plan"].items() if i.get("emphasised")]
            if sorted(c for c, i in pl["plan"].items() if i.get("emphasised")) != st["glbExtras"]["clips"]:
                errors.append(f"{u}: plan's emphasised clips differ from the GLB stamp")
            for name, r in json.load(open(os.path.join(W, "actions.json"))).items():
                if isinstance(r, dict) and r.get("rewritten") and (
                        name in ("Unit_Idle", "Unit_Move") or not any(x <= r["masterStart"] < y for x, y in rng)):
                    errors.append(f"{u}: {name} rewritten outside the emphasised clips")
        except FileNotFoundError as x:
            errors.append(f"{u}: missing emphasis record {x.filename}")
        # round trip + loops
        v1 = json.load(open(os.path.join(cdir, "glb_verify.json")))
        for act, r in v1.items():
            # verify_glb.py's own rule: a 1-key source clip exports as 2 keys
            keys_ok = r.get("keys") == r.get("srcKeys") or (r.get("srcKeys") == 1 and r.get("keys") == 2)
            if r.get("missing") or not keys_ok or r.get("maxBoneErr", 1) > 1e-4 or r.get("maxMeshErr", 1) > 2e-3:
                errors.append(f"{u}: glb_verify {act} {r}")
        for act in ("Unit_Idle", "Unit_Move"):
            if act in v1:
                if v1[act].get("lastMinusFirst", 1) > 1e-4:
                    errors.append(f"{u}: {act} does not close its loop ({v1[act].get('lastMinusFirst')})")
        for c, v in st.get("clips", {}).items():
            if v.get("emphasised") and v.get("stretchGate") != "pass":
                errors.append(f"{u}: clip {c} installed without passing the stretch gate")
    for n in notes:
        print("note:", n)
    for e in errors:
        print("ERROR:", e)
    print(f"homm3 def-retarget emphasis contract: {len(units)} units {json.dumps(counts, sort_keys=True)}, "
          f"{len(errors)} errors, {len(notes)} notes")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
