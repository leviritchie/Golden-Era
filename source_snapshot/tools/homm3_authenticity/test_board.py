"""CPU reference vs CUDA parity of the authenticity board kernels (skinning + morphs, raster, shading).

    python tools/homm3_authenticity/test_board.py        (or pytest)

Renders h3_pikeman's shipped GLB (Unit_Idle frame 0 and Unit_AttackFront mid-thrust, the morph-heavy clip) under the
sprite, battle and preview cameras on both devices. Float32 on both: CUDA and CPU round differently (FMA, summation
order), so pixels whose centre sits on a triangle edge can flip; the tolerances below bound that.
Skips (exit 0 with SKIP) without a CUDA device: the parity claim needs both devices. Runs in ~10 s.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board as B  # noqa: E402
import raster as R  # noqa: E402
import torch  # noqa: E402
from gltf_scene import Scene  # noqa: E402
from sources import def_reference, shipped_glb  # noqa: E402

UNIT = "h3_pikeman"
POS_TOL = 1e-4          # skinned positions, GLB units (the body is ~1.7 tall)
COVER_TOL = 0.002       # share of covered pixels whose coverage differs
RGB_TOL = 0.004         # mean |rgb| difference over pixels covered on both


def cameras(scene, P0):
    ref = def_reference(UNIT)
    sc = B.sprite_camera(ref["spritecam"], None)
    sprite = B.with_box(sc, 250, 160, 320, 620, 1.0)
    bd = B.orbit_dirs(B.BATTLE["elevDeg"], B.BATTLE["azimuthDeg"])
    battle = {"kind": "ortho", "eye": [0, 0, 0], **{k: bd[k] for k in ("right", "up", "fwd")},
              "scale": 110.0, "cx": 120.0, "cy": 200.0, "W": 240, "H": 240}
    pd = B.orbit_dirs(B.PREVIEW["elevDeg"], B.PREVIEW["azimuthDeg"])
    eye = np.array([0, 1.0, 0]) + pd["to_cam"] * 14.0
    preview = {"kind": "persp", "eye": eye, **{k: pd[k] for k in ("right", "up", "fwd")},
               "scale": 1500.0, "cx": 120.0, "cy": 120.0, "W": 240, "H": 240}
    return {"sprite": sprite, "battle": battle, "preview": preview}


def run_device(dev_name, scene, tex, poses):
    dev = R.resolve_device(dev_name)
    mesh = R.DeviceMesh(scene, dev, tex)
    out = {}
    for tag, (clip, t) in poses.items():
        Jm, mw = scene.pose(clip, np.array([t]))
        P, N = mesh.skin(Jm, mw)
        out[tag] = {"P": P[0].cpu().numpy()}
        for cname, cam in cameras(scene, P).items():
            out[tag][cname] = R.render(mesh, cam, P, N, ss=2).cpu().numpy()
    return out


def test_device_parity():
    if not torch.cuda.is_available():
        print("SKIP: no CUDA device")
        return
    sel = shipped_glb(UNIT, UNIT)
    scene = Scene(sel["path"], body_name=UNIT)
    tex = scene.texture_rgba(512)
    ar = scene.clip_range("Unit_AttackFront")
    poses = {"idle0": ("Unit_Idle", scene.clip_range("Unit_Idle")["start"]),
             "attack5": ("Unit_AttackFront", ar["start"] + 5 * ar["duration"] / 9)}
    g, c = run_device("cuda", scene, tex, poses), run_device("cpu", scene, tex, poses)
    worst = {}
    for tag in poses:
        dp = float(np.abs(g[tag]["P"] - c[tag]["P"]).max())
        assert dp <= POS_TOL, f"{tag}: skinned positions differ by {dp}"
        for cname in ("sprite", "battle", "preview"):
            a, b = g[tag][cname], c[tag][cname]
            ca, cb = a[..., 3] > 0, b[..., 3] > 0
            cover = (ca | cb).sum()
            flip = float(np.abs(a[..., 3] - b[..., 3]).sum() / max(cover, 1))
            both = (a[..., 3] > 0.999) & (b[..., 3] > 0.999)
            drgb = float(np.abs(a[..., :3] - b[..., :3])[both].mean()) if both.any() else 0.0
            assert cover > 1000, f"{tag}/{cname}: only {cover} px covered (camera misses the unit)"
            assert flip <= COVER_TOL, f"{tag}/{cname}: coverage differs on {flip:.4%} of covered px"
            assert drgb <= RGB_TOL, f"{tag}/{cname}: mean rgb difference {drgb:.5f}"
            worst[f"{tag}/{cname}"] = (round(flip, 6), round(drgb, 6))
        worst[f"{tag}/pos"] = dp
    print("PARITY OK", worst)


if __name__ == "__main__":
    test_device_parity()
