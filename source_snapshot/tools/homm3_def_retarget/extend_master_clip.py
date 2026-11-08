"""Add a DEF group the linked master skipped as an exported clip, with a motionless capture for its frames.

Usage: python tools/homm3_def_retarget/extend_master_clip.py <unit> --group 18 --as ShootFront --reason "<why>"
       python tools/homm3_def_retarget/extend_master_clip.py <unit> --check

Why: the mocap corpus maps only native contract groups (g15 -> ShootFront). A unit whose DEF keeps its ranged
action in another group (h3_leprechaun: g18, the hat-and-coins throw; g17/g19 are the same action up/down) gets no
ShootFront, so the game plays the melee AttackFront for its projectile view. The capture model was never run on
those frames, so this tool gives them NO captured motion: every added frame repeats the capture row of the bind
frame (idle frame 0). All motion for the added clip comes from the unit config (ext/clip_overlay.py
"poseOverlay"), keyed against the DEF frames, and the stamp says so.

What it writes, under runs/<unit>/linked_master/ (in place, because every consumer reads that path):
  master_sequence/master_sequence.json  the new segment inserted before Death with an idle bookend after it (the
                                        layout native shooters have: ... AttackFront, bookend, ShootFront, bookend,
                                        Death); the group leaves skippedClips; "extendedClips" records each added clip
  capture/capture/raw_capture.npz       the bind-frame row inserted for every added frame (all arrays with a frame axis)
  capture/capture/provenance.json       "extendedClips" with the same record ("mocap": false for those frames)
The originals are kept under linked_master/_base/ with their sha256. A rerun always starts from _base, so the
tool is idempotent; it refuses when the live files match neither _base nor its own last output (someone else
rewrote the run). --check verifies the stamp against the files and exits nonzero on any mismatch.
Proof tier: generated artifact (offline clip layout); the added clip's motion is hand-keyed, not mocap.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUNS = os.path.join(ROOT, "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs")
SCHEMA = "homm3_def_retarget_extend_master_clip.v1"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def paths(unit):
    lm = os.path.join(RUNS, unit, "linked_master")
    return {"lm": lm, "ms": os.path.join(lm, "master_sequence", "master_sequence.json"),
            "cap": os.path.join(lm, "capture", "capture", "raw_capture.npz"),
            "prov": os.path.join(lm, "capture", "capture", "provenance.json"),
            "base": os.path.join(lm, "_base")}


def check(unit):
    p = paths(unit)
    ms = json.load(open(p["ms"]))
    ext = ms.get("extendedClips")
    if not ext:
        return [f"{unit}: master has no extendedClips"]
    errs = []
    st = json.load(open(os.path.join(p["base"], "extend_stamp.json")))
    if st.get("schema") != SCHEMA:
        errs.append("stamp schema")
    for k in ("ms", "cap", "prov"):
        if sha(p[k]) != st["out"][k]:
            errs.append(f"{k}: live file differs from the stamped output")
        if sha(os.path.join(p["base"], os.path.basename(p[k]))) != st["base"][k]:
            errs.append(f"{k}: _base copy differs from its stamped sha")
    cap = np.load(p["cap"])
    if cap["pred_position"].shape[0] != ms["frameCount"] or len(ms["frames"]) != ms["frameCount"]:
        errs.append("capture / master frame counts differ")
    for e in ext:
        seg = [s for s in ms["segments"] if s["clipKey"] == e["clipKey"]]
        if len(seg) != 1:
            errs.append(f"{e['clipKey']}: expected one segment")
            continue
        s = seg[0]
        rows = cap["pred_position"][s["globalStart"]:s["globalEnd"]]
        if not np.array_equal(rows, np.repeat(cap["pred_position"][ms["bindGlobalIndex"]][None], len(rows), 0)):
            errs.append(f"{e['clipKey']}: added frames are not the bind row (motionless contract broken)")
        for t in range(s["globalStart"], s["globalEnd"]):
            f = ms["frames"][t]
            if sha(f["sourcePng"]) != f["sourceSha256"]:
                errs.append(f"frame {t}: DEF png sha changed")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--group", type=int)
    ap.add_argument("--as", dest="suffix")
    ap.add_argument("--reason")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        errs = check(a.unit)
        print("EXTEND CHECK", a.unit, "OK" if not errs else "FAIL", *errs, sep="\n  ")
        return 1 if errs else 0
    if a.group is None or not a.suffix or not (a.reason or "").strip():
        ap.error("--group, --as and a non-empty --reason are required")
    p = paths(a.unit)
    os.makedirs(p["base"], exist_ok=True)
    stamp_p = os.path.join(p["base"], "extend_stamp.json")
    bases = {k: os.path.join(p["base"], os.path.basename(p[k])) for k in ("ms", "cap", "prov")}
    if not os.path.exists(stamp_p):
        if json.load(open(p["ms"])).get("extendedClips"):
            sys.exit(f"{a.unit}: master already carries extendedClips but no _base stamp; refusing")
        for k, b in bases.items():
            shutil.copy2(p[k], b)
        base_sha = {k: sha(b) for k, b in bases.items()}
    else:
        st = json.load(open(stamp_p))
        base_sha = st["base"]
        for k, b in bases.items():
            if sha(b) != base_sha[k]:
                sys.exit(f"{a.unit}: _base/{os.path.basename(b)} differs from its stamp; refusing")
            if sha(p[k]) not in (st["out"][k], base_sha[k]):
                sys.exit(f"{a.unit}: live {os.path.basename(p[k])} matches neither _base nor the last output; "
                         f"someone rewrote the run, refusing")

    ms = json.load(open(bases["ms"]))
    cap = dict(np.load(bases["cap"]))
    prov = json.load(open(bases["prov"]))
    T = ms["frameCount"]
    if any(s["contractSuffix"] == a.suffix and s.get("exportsClip", True) for s in ms["segments"]):
        sys.exit(f"{a.unit}: the base master already exports {a.suffix}")
    skipped = [c for c in ms["skippedClips"] if c["defGroup"] == a.group]
    if len(skipped) != 1:
        sys.exit(f"{a.unit}: DEF group {a.group} is not a skipped clip of this master")
    clip_key = skipped[0]["clipKey"]
    src_dir = os.path.dirname(ms["frames"][0]["sourcePng"])
    pngs = sorted(glob.glob(os.path.join(src_dir, f"{a.group:02d}_*.png")))
    if not pngs:
        sys.exit(f"{a.unit}: no DEF frames {a.group:02d}_*.png in {src_dir}")
    death = [s for s in ms["segments"] if s["contractSuffix"] == "Death" and s["role"] == "cycle"]
    if len(death) != 1:
        sys.exit(f"{a.unit}: expected one Death segment to insert before")
    at = death[0]["globalStart"]
    bind = ms["bindGlobalIndex"]
    idle = next(s for s in ms["segments"] if s["contractSuffix"] == "Idle" and s["role"] == "cycle")
    bookend_src = ms["frames"][bind]

    # new frames: the clip, then one idle bookend (the bookend before it is the one ahead of Death already)
    new_frames = [{"clipKey": clip_key, "defGroup": a.group, "role": "cycle", "localIndex": i,
                   "sourcePng": q.replace("\\", "/"), "sourceSha256": sha(q)} for i, q in enumerate(pngs)]
    new_frames.append({"clipKey": idle["clipKey"], "defGroup": idle["defGroup"], "role": "bookend", "localIndex": 0,
                       "sourcePng": bookend_src["sourcePng"], "sourceSha256": bookend_src["sourceSha256"]})
    n_new = len(new_frames)
    frames = ms["frames"][:at] + new_frames + ms["frames"][at:]
    di = [i for i, s in enumerate(ms["segments"]) if s is death[0]][0]
    new_segs = [{"clipKey": clip_key, "defGroup": a.group, "contractSuffix": a.suffix, "role": "cycle",
                 "frameLimit": None, "globalStart": at, "globalEnd": at + len(pngs), "frameCount": len(pngs),
                 "sourceClipFrameCount": len(pngs), "exportsClip": True},
                {"clipKey": idle["clipKey"], "defGroup": idle["defGroup"], "contractSuffix": "Idle", "role": "bookend",
                 "frameLimit": 1, "globalStart": at + len(pngs), "globalEnd": at + n_new, "frameCount": 1,
                 "sourceClipFrameCount": idle["frameCount"], "exportsClip": False}]
    segs = ms["segments"][:di] + new_segs + ms["segments"][di:]
    for s in ms["segments"][di:]:
        s["globalStart"] += n_new
        s["globalEnd"] += n_new
    for i, s in enumerate(segs):
        s["segmentIndex"] = i
        for t in range(s["globalStart"], s["globalEnd"]):
            frames[t]["segmentIndex"] = i
    fdir = os.path.dirname(frames[0].get("numberedPng") or "") or ms.get("framesDir", "")
    for t, f in enumerate(frames):
        f["globalIndex"] = t
        if "numberedPng" in ms["frames"][0]:
            f["numberedPng"] = f"{fdir}/{t:06d}.png"
    frames = [{k: f[k] for k in ("globalIndex", "segmentIndex", "clipKey", "defGroup", "role", "localIndex",
                                 "sourcePng", "sourceSha256", "numberedPng") if k in f} for f in frames]
    reel_i = next(i for i, r in enumerate(ms["reel"]) if r["clipKey"] == death[0]["clipKey"])
    reel = ms["reel"][:reel_i] + [{k: s[k] for k in ("clipKey", "defGroup", "contractSuffix", "role", "frameLimit")}
                                  for s in new_segs] + ms["reel"][reel_i:]

    record = {"clipKey": clip_key, "defGroup": a.group, "contractSuffix": a.suffix, "frames": len(pngs),
              "insertedAt": at, "bookendAt": at + len(pngs), "mocap": False,
              "captureSource": f"motionless: capture row of bind frame {bind} (idle frame 0) repeated",
              "motionSource": "unit config poseOverlay (tools/homm3_def_retarget/ext/clip_overlay.py)",
              "reason": a.reason.strip(), "tool": "tools/homm3_def_retarget/extend_master_clip.py"}
    out_ms = dict(ms, frameCount=T + n_new, frames=frames, segments=segs, reel=reel,
                  skippedClips=[c for c in ms["skippedClips"] if c["defGroup"] != a.group],
                  extendedClips=[record], extendedFrom={"masterSha256": base_sha["ms"], "captureSha256": base_sha["cap"]})

    ins = [bind] * n_new
    out_cap = {}
    for k, v in cap.items():
        if v.ndim >= 1 and v.shape[0] == T and k not in ("parents", "offsets", "vendor_offset_a", "joint_names"):
            out_cap[k] = np.concatenate([v[:at], v[ins], v[at:]], axis=0)
        else:
            out_cap[k] = v
    out_prov = dict(prov, extendedClips=[record])

    tmp = p["cap"] + ".tmp.npz"
    np.savez(tmp, **out_cap)
    os.replace(tmp, p["cap"])
    json.dump(out_ms, open(p["ms"], "w"), indent=1)
    json.dump(out_prov, open(p["prov"], "w"), indent=2)
    json.dump({"schema": SCHEMA, "unit": a.unit, "base": base_sha,
               "out": {k: sha(p[k]) for k in ("ms", "cap", "prov")}, "extendedClips": [record]},
              open(stamp_p, "w"), indent=1)
    errs = check(a.unit)
    if errs:
        sys.exit("EXTEND wrote an inconsistent run:\n  " + "\n  ".join(errs))
    print(f"EXTENDED {a.unit}: {clip_key} -> {a.suffix}, {len(pngs)} frames at {at} (+1 bookend), "
          f"{T} -> {T + n_new} frames; capture motionless for them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
