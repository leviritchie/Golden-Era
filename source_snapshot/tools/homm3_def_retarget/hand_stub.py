"""Create a hand-keyed stand-in capture for a unit that has no usable mocap.

Usage: python tools/homm3_def_retarget/hand_stub.py <unit> [--force] [--layout <master_sequence.json>]

Some units (beholder, nereid, automatons, cannon ...) only have captures under
runs/<unit>/remaining_forced_*/ that were forced onto a mismatched skeleton and are not usable as
motion. Their joints are animated by hand instead (config "handKeys", ext/hand_keys.py). The
build pipeline still needs a clip layout and a capture file, so this writes, under
runs/<unit>/linked_master/:
  master_sequence/master_sequence.json  copied from the forced run (same DEF frames and clips)
  capture/capture/raw_capture.npz       a MOTIONLESS Mixamo pose (a reference unit's idle frame 0
                                        repeated), so the retarget adds no motion at all
  capture/capture/provenance.json       {"kind": "hand-keyed stand-in", "mocap": false, ...}
Refuses to overwrite a real capture (one without that provenance) unless --force.
"""
import json, os, shutil, sys
import numpy as np

ROOT = r"V:/games/Olden Era Playtest Tweak"
RUNS = os.path.join(ROOT, "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs")
REFERENCE = "h3_gremlin"          # any unit with a Mixamo capture: only its frame 0 is used

unit = sys.argv[1]; force = "--force" in sys.argv
lm = os.path.join(RUNS, unit, "linked_master")
cap_dir = os.path.join(lm, "capture", "capture")
prov_path = os.path.join(cap_dir, "provenance.json")
if os.path.exists(os.path.join(cap_dir, "raw_capture.npz")) and not force:
    prov = json.load(open(prov_path)) if os.path.exists(prov_path) else {}
    if prov.get("kind") != "hand-keyed stand-in":
        sys.exit(f"{unit} already has a real capture; not overwriting (use --force)")
if "--layout" in sys.argv:
    src_ms = sys.argv[sys.argv.index("--layout") + 1]; forced = ["layout:" + src_ms]
else:
    forced = sorted(d for d in os.listdir(os.path.join(RUNS, unit)) if d.startswith("remaining_forced_"))         if os.path.isdir(os.path.join(RUNS, unit)) else []
    if not forced:
        sys.exit(f"{unit}: no remaining_forced_* run to take the clip layout from (pass --layout)")
    src_ms = os.path.join(RUNS, unit, forced[0], "linked_master", "master_sequence", "master_sequence.json")
ms = json.load(open(src_ms))
T = ms["frameCount"]

ref = np.load(os.path.join(RUNS, REFERENCE, "linked_master", "capture", "capture", "raw_capture.npz"))
pos = np.repeat(ref["pred_position"][:1], T, axis=0)
os.makedirs(cap_dir, exist_ok=True)
os.makedirs(os.path.join(lm, "master_sequence"), exist_ok=True)
np.savez(os.path.join(cap_dir, "raw_capture.npz"), pred_position=pos,
         pred_rot6d=np.repeat(ref["pred_rot6d"][:1], T, axis=0), parents=ref["parents"],
         offsets=ref["offsets"], joint_names=ref["joint_names"],
         motion_interface=np.array("pred_position"))
ms_out = dict(ms, handKeyedStandIn=True, sourceForcedRun=forced[0])
json.dump(ms_out, open(os.path.join(lm, "master_sequence", "master_sequence.json"), "w"), indent=1)
json.dump({"kind": "hand-keyed stand-in", "mocap": False, "frames": T,
           "clipLayoutFrom": src_ms, "restPoseFrom": f"{REFERENCE} capture frame 0 (motionless)",
           "note": "All motion comes from the unit config's handKeys; this file carries none."},
          open(prov_path, "w"), indent=1)
print(f"HAND STUB {unit}: {T} frames, clips from {forced[0]}")
