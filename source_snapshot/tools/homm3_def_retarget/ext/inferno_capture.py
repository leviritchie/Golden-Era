"""Inferno capture adapters (hooks for build_unit.py).

Unit-config keys (both optional):
  "captureRemap": "bip01"
      Some Inferno captures (imp, magog, hell hound) were fitted with the vendor's 50-joint
      Bip01 creature template (wings, tail, horse-link legs, no arms) instead of the 25-joint
      Mixamo humanoid. after_skin writes a Mixamo-named copy of the capture next to the build
      and points CAPTURE at it, so build_unit's retarget reads it unchanged:
        Hips/Spine/Spine1   <- Bip01_Pelvis / Bip01_Spine / Bip01_Spine1
        Spine2/Neck/Head    <- Bip01_Neck / Bip01_Neck2 / Bip01_Head, HeadTop_End continues Neck1->Head
        arms (or a quadruped's front legs) <- the BN_Wing chains: the template's "wings" are the
            limbs that leave Spine1, and on these sprites they track the arms / front legs
            (Shoulder=Spine1, Arm=Wing_01, ForeArm=Wing_02, Hand=Wing_03, Hand_End=Wing_04)
        legs <- Thigh / Calf / HorseLink / Foot / mean of the toe tips
  "captureUp": "camera"
      build_unit's map_capture takes "up" from the capture's idle Hips->Spine2 line. For a
      quadruped that line is horizontal, so the whole capture world is pitched 90 degrees and
      every relative rotation is conjugated by it (a head turn becomes a roll). after_pose
      re-maps the capture with up = the capture camera's +Y axis (image up) and lateral = the
      hip + shoulder lines, then rebuilds posed_world with build_unit's own pose_frame.
"""
import os
import numpy as np

BIP = {
    "Hips": "Bip01_Pelvis", "Spine": "Bip01_Spine", "Spine1": "Bip01_Spine1",
    "Spine2": "Bip01_Neck", "Neck": "Bip01_Neck2", "Head": "Bip01_Head",
}
for _s, _b in (("Left", "L"), ("Right", "R")):
    BIP.update({f"{_s}Shoulder": "Bip01_Spine1", f"{_s}Arm": f"BN_Wing_{_b}_01", f"{_s}ForeArm": f"BN_Wing_{_b}_02",
                f"{_s}Hand": f"BN_Wing_{_b}_03", f"{_s}Hand_End": f"BN_Wing_{_b}_04",
                f"{_s}UpLeg": f"Bip01_{_b}_Thigh", f"{_s}Leg": f"Bip01_{_b}_Calf",
                f"{_s}Foot": f"Bip01_{_b}_HorseLink", f"{_s}ToeBase": f"Bip01_{_b}_Foot"})


def after_skin(g):
    cfg = g["cfg"]
    if cfg.get("captureRemap") != "bip01":
        return
    cap = np.load(g["CAPTURE"])
    names = [str(n).split(":")[-1] for n in cap["joint_names"]]
    ix = {n: i for i, n in enumerate(names)}
    P = cap["pred_position"].astype(float)
    out_names, cols = [], []
    for k, src in BIP.items():
        out_names.append("mixamorig:" + k); cols.append(P[:, ix[src]])
    n1, hd = P[:, ix["Bip01_Neck1"]], P[:, ix["Bip01_Head"]]
    out_names.append("mixamorig:HeadTop_End"); cols.append(hd + (hd - n1))
    for s, b in (("Left", "L"), ("Right", "R")):
        tips = [ix[n] for n in names if n.startswith(f"BN_Toe_{b}_") and n.endswith("1")]
        out_names.append(f"mixamorig:{s}Toe_End"); cols.append(P[:, tips].mean(1))
    path = g["OUT"] + ".capture_mixamo.npz"
    np.savez(path, pred_position=np.stack(cols, 1), joint_names=np.array(out_names))
    g["CAPTURE"] = path
    print("CAPTURE remapped bip01 ->", len(out_names), "mixamo joints", path)


def after_pose(g):
    cfg = g["cfg"]
    if cfg.get("captureUp") != "camera":
        return
    Vector = g["Vector"]; frame_of = g["frame_of"]; P = g["P"]; ix = g["ix"]
    p0 = P[0]
    V = lambda a: Vector((float(a[0]), float(a[1]), float(a[2])))
    lat = V(p0[ix["LeftUpLeg"]] - p0[ix["RightUpLeg"]]) + V(p0[ix["LeftArm"]] - p0[ix["RightArm"]])
    Fcap = frame_of(Vector((0.0, 1.0, 0.0)), lat)
    Mcap = frame_of(Vector((0, 0, 1)), Vector((1, 0, 0))) @ Fcap.transposed()
    g["W"] = [[Mcap @ V(P[t, j]) for j in range(P.shape[1])] for t in range(P.shape[0])]
    g["posed_world"][:] = [g["pose_frame"](t) for t in range(g["T"])]
    W = g["W"]; jw = lambda t, n: W[t][ix[n]]
    fw = (jw(0, "Head") - jw(0, "Hips")); fw.z = 0
    print("CAPTURE up=camera; hips->head (expect ~ -Y):", tuple(round(x, 2) for x in fw.normalized()))
