"""Necropolis: drive a unit from a sibling unit's human capture.

The h3_vampire capture run was made against a zoo (eagle) reference skeleton because its Move is
a bat, so it has no Mixamo joints and build_unit.py cannot retarget it. The Vampire Lord's DEF
has the same clips with the same frame counts and the same motion, and its capture is human.
This hook (after_skin, which runs before the capture is loaded) points CAPTURE at the donor's
raw_capture.npz. It refuses a donor whose master sequence has a different clip/frame layout.

Config: "captureDonor": "h3_vampire_lord".
"""
import json
import os


def after_skin(g):
    donor = g["cfg"].get("captureDonor")
    if not donor:
        return
    runs = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(g["CAPTURE"])))))
    droot = os.path.join(runs, donor, "linked_master")
    mine = json.load(open(g["MASTER"]))["segments"]
    theirs = json.load(open(os.path.join(droot, "master_sequence", "master_sequence.json")))["segments"]
    lay = lambda sg: [(s["clipKey"], s["frameCount"]) for s in sg]
    if lay(mine) != lay(theirs):
        raise RuntimeError(f"captureDonor {donor}: clip layout differs from this unit's DEF")
    g["CAPTURE"] = os.path.join(droot, "capture", "capture", "raw_capture.npz")
    print("CAPTUREDONOR", donor)
