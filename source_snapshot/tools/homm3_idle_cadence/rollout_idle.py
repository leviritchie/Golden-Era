"""Roll the idle-cadence rule out over the def_retarget roster (never writes the sources).

    python tools/homm3_idle_cadence/rollout_idle.py [unit ...] [--detect-only] [--force]

For every artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb, reading the input that
idle_cadence_rule.resolve_input picks (the emphasised build; look's superseded original when the GLB
is look's stamped delivery):
1. sample the source Unit_Idle and run the outlier detector (idle_cadence_rule.detect);
2. take the treatment from idle_exceptions.json (default: the global rule);
3. REFUSE the unit (no output, listed in the roster report) when the detector flags it and the
   table has no entry for it, or when the entry's recorded flags differ from what the detector
   finds now - an outlier is never retimed without a recorded decision;
4. write artifacts/homm3_idle_cadence/roster/<unit>/<unit>_idle_retimed.glb and report.json
   (treatment, source size/mtime, before/after cadence), unless excluded.
Up-to-date units (same input animation hash and treatment; a look apply that only moves the
input to its superseded path is not a change) are skipped unless --force.
Summary: artifacts/homm3_idle_cadence/roster/roster_report.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_anim import raw_accessor, read_glb, sample_rotations, write_glb  # noqa: E402
from idle_metrics import cadence  # noqa: E402
import idle_cadence_rule as rule  # noqa: E402
from retime_idle import RetimeError, retime  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "artifacts/homm3_idle_cadence/roster")


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def brief(m):
    if not m or not m.get("movingBones"):
        return {"lengthS": m and m["lengthS"], "movingBones": 0}
    return {"lengthS": m["lengthS"], "beats": m["beats"], "meanDegS": m["angSpeedDegS"]["median"],
            "peakDegS": m["peakAngSpeedDegS"]["median"], "peakP90DegS": m["peakAngSpeedDegS"]["p90"],
            "swingDeg": m["amplitudeDeg"]["median"], "swingP90Deg": m["amplitudeDeg"]["p90"]}


def file_stats(unit, src):
    """Size/mtime of the on-disk def_retarget GLB and of the resolved input. Only a cache key for the
    validator (unchanged files -> unchanged resolution); currency itself is srcAnimSha256."""
    g = os.stat(os.path.join(ROOT, f"artifacts/homm3_def_retarget/{unit}/{unit}_def_retarget.glb"))
    s = os.stat(src)
    return {"glbSize": g.st_size, "glbMtime": g.st_mtime, "srcSize": s.st_size, "srcMtime": s.st_mtime}


def roster_units():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "artifacts/homm3_def_retarget/*/*_def_retarget.glb"))):
        u = os.path.basename(os.path.dirname(p))
        if os.path.basename(p) == f"{u}_def_retarget.glb":
            out.append(u)
    return out


def process(unit, table, detect_only, force):
    src, src_kind = rule.resolve_input(unit)
    udir = os.path.join(OUT, unit)
    dst = os.path.join(udir, f"{unit}_idle_retimed.glb")
    rp = os.path.join(udir, "report.json")
    tr = rule.treatment_for(unit, table)
    js, bn = read_glb(src)
    anim_sha = rule.anim_sha256(js, lambda i: raw_accessor(js, bn, i))
    emph = rule.emphasis_errors(unit, js)
    if emph:
        return {"unit": unit, "src": rel(src), "status": "refused", "why": emph[0]}
    if not force and not detect_only and os.path.exists(rp):
        old = json.load(open(rp))
        if (old.get("srcAnimSha256") == anim_sha and old.get("treatment") == tr["treatment"]
                and old.get("factor") == tr["factor"] and old.get("wingCycles") == tr.get("wingCycles")
                and (tr["treatment"] == "exclude" or os.path.exists(dst))):
            old.update(file_stats(unit, src), src=rel(src), srcKind=src_kind)   # a look apply may move the input
            json.dump(old, open(rp, "w"), indent=1)
            return {**old, "status": "up-to-date"}
    rots, length = sample_rotations(js, bn, rule.IDLE_CLIP)
    flags, met = rule.detect(rots, length)
    row = {"unit": unit, "src": rel(src), "srcKind": src_kind, "srcAnimSha256": anim_sha,
           "emphasis": (js.get("asset", {}).get("extras") or {}).get(rule.EMPHASIS_EXTRAS_KEY), **file_stats(unit, src), "flags": flags, "treatment": tr["treatment"], "factor": tr["factor"],
           "wingCycles": tr.get("wingCycles"), "before": brief(met["all"]),
           "beforeWing": brief(met["wing"]) if met["wing"] else None}
    entry = table.get("units", {}).get(unit)
    if flags and entry is None:
        return {**row, "status": "refused", "why": f"detector flags {flags} but idle_exceptions.json has no decision"}
    if entry is not None and sorted(entry.get("flags", [])) != sorted(flags):
        return {**row, "status": "refused",
                "why": f"table records flags {entry.get('flags', [])}, detector now finds {flags}; re-decide"}
    if detect_only:
        return {**row, "status": "detected"}
    os.makedirs(udir, exist_ok=True)
    if tr["treatment"] == "exclude":
        rep = {**row, "status": "excluded", "reason": tr["reason"], "dst": None}
        json.dump(rep, open(rp, "w"), indent=1)
        return rep
    cyc = rule.cycles_for(js, tr)
    try:
        new_bin, stats = retime(js, bn, rule.IDLE_CLIP, tr["factor"], rule.RESAMPLE_HZ, cyc)
    except (RetimeError, KeyError) as e:
        return {**row, "status": "refused", "why": f"retime: {e}"}
    js.setdefault("asset", {}).setdefault("extras", {})["homm3IdleCadence"] = {
        "srcAnimSha256": anim_sha, "treatment": tr["treatment"], "factor": tr["factor"],
        "wingCycles": tr.get("wingCycles"), "exceptions": "tools/homm3_idle_cadence/idle_exceptions.json"}
    tmp = dst + ".tmp"
    write_glb(tmp, js, new_bin)
    os.replace(tmp, dst)
    r2, l2 = sample_rotations(js, new_bin, rule.IDLE_CLIP)
    wing2 = {k: v for k, v in r2.items() if "wing" in k.lower()}
    rep = {**row, "status": "retimed", "reason": tr.get("reason"), "dst": rel(dst),
           "upstreamStages": list(rule.UPSTREAM_ANIMATION_STAGES), "wingNodes": sorted(cyc),
           "after": brief(cadence(r2, l2)), "afterWing": brief(cadence(wing2, l2)) if wing2 else None,
           "rule": rule.describe(), **stats}
    json.dump(rep, open(rp, "w"), indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--detect-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    table = rule.load_exceptions()
    errs = rule.table_errors(table)
    if errs:
        sys.exit("FAIL: exceptions table: " + "; ".join(errs))
    units = args.units or roster_units()
    rows, t0 = [], time.time()
    for u in units:
        try:
            r = process(u, table, args.detect_only, args.force)
        except Exception as e:
            r = {"unit": u, "status": "refused", "why": f"{type(e).__name__}: {e}"}
        rows.append(r)
        print(f"{u:34} {r['status']:10} {r.get('treatment', '')!s:12} flags={r.get('flags')} "
              f"{(r.get('before') or {}).get('lengthS')} -> {(r.get('after') or {}).get('lengthS')} {r.get('why', '')}", flush=True)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = {"schema": "homm3_idle_cadence.roster.v1", "rule": rule.describe(), "counts": counts,
               "seconds": round(time.time() - t0, 1), "units": rows}
    os.makedirs(OUT, exist_ok=True)
    name = "detect_report.json" if args.detect_only else "roster_report.json"
    if args.units:
        name = name.replace(".json", "_partial.json")
    json.dump(summary, open(os.path.join(OUT, name), "w"), indent=1)
    print(json.dumps(counts))
    return 1 if counts.get("refused") else 0


if __name__ == "__main__":
    sys.exit(main())
