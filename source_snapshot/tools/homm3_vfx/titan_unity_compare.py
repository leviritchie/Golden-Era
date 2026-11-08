"""Titan VFX: write unit_vfx_preview.v1 specs for the Unity harness and build DEF-vs-Unity comparisons.

  python tools/homm3_vfx/titan_unity_compare.py specs      -> work/unity_specs/*.json
  python tools/homm3_import/preview_unit_vfx.py --spec <spec> --out artifacts/unit_vfx_preview/<run>
  python tools/homm3_vfx/titan_unity_compare.py compare    -> titan/compare_<clip>.gif + _sheet.png

Proof level of everything produced here: Unity-editor camera render (preview harness), not in-game.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import h3def  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TITAN = ROOT / "artifacts/homm3_vfx_experiments/titan"
WORK = TITAN / "work"
SPECS = WORK / "unity_specs"
RUNS = ROOT / "artifacts/unit_vfx_preview"
LAB = "Assets/Homm3VfxLab/h3_giant_upg"
REF = "Assets/CustomUnits/homm3_lab/h3_giant_upg/extracted_battle/CGTITA.dir"
CAMERA_DIR = [0.4158, 0.1739, 0.8927]  # -(SpriteCam forward), Blender (x,y,z) -> Unity (-x,z,-y) (glTFast mirrors X)
RUN_PREFIX = "titan_vfx_"

VARIANTS = {
    # run name: (clip, DEF group, effect prefab, anchor, duration)
    "attack_A": ("Unit_AttackFront", 12, "titan_attack_A", "RightHand", 8 / 12),
    "attack_B": ("Unit_AttackFront", 12, "titan_attack_B", "RightHand", 8 / 12),
    "shoot_A": ("Unit_ShootFront", 15, "titan_shoot_A_missile", "LeftHand", 10 / 12),
    "shoot_B": ("Unit_ShootFront", 15, "titan_shoot_B_missile", "LeftHand", 10 / 12),
}


def write_specs():
    SPECS.mkdir(parents=True, exist_ok=True)
    for run, (clip, g, prefab, anchor, dur) in VARIANTS.items():
        spec = {
            "schema": "unit_vfx_preview.v1",
            "unitSid": "h3_giant_upg",
            "prefabAssetPath": f"{LAB}/h3_giant_upg_vfxlab.prefab",
            "clipAssetPath": f"{LAB}/{clip}.anim",
            "anchorName": anchor,
            "effectKind": "particlePrefab",
            "effectPrefabAssetPath": f"{LAB}/{prefab}.prefab",
            "effectBoundsMarginRelativeToHeight": 0.35,
            "candidateStatus": "vfx lab experiment; Unity-editor render only; not delivered",
            "effectSourceNote": (f"CGTITA.DEF group {g} lightning pixels as a point-filtered flipbook ("
                                 + ("literal DEF pixels" if run.endswith("A") else "skeletonised 2x redraw") + ")"
                                 + ("; missile is CPRGTIX frame 4" if "shoot" in run else "")),
            "durationSeconds": round(dur, 6),
            "loopClip": False,
            "requireSkinnedMeshDeformation": False,
            "effectDurationSeconds": round(dur - 1 / 12, 6),
            "eventTimesSeconds": [round(1 / 12, 6)],  # GLB clip keys DEF frame i at (i+1)/12
            "anchorLocalOffset": [0.0, 0.0, 0.0],
            "seed": 11,
            "fps": 24,
            "sourceFramesPerSecond": 12,
            "width": 900,
            "height": 900,
            "cameraDirection": CAMERA_DIR,
            "orthographicPadding": 1.05,
            "referenceFrames": [f"{REF}/{g}_{i:02d}.png" for i in range(7)],
        }
        (SPECS / f"{run}.json").write_text(json.dumps(spec, indent=1))
        print(SPECS / f"{run}.json")


def alpha_box(imgs):
    boxes = [im.getbbox() for im in imgs if im.getbbox()]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def load_run(run):
    d = RUNS / (RUN_PREFIX + run)
    rep = json.loads((d / "preview_report.json").read_text())
    base = [Image.open(p).convert("RGBA") for p in sorted((d / "baseline").glob("frame_*.png"))]
    fx = [Image.open(p).convert("RGBA") for p in sorted((d / "effect").glob("frame_*.png"))]
    return rep, base, fx


def compare(clip_key, runs, scale_out=2):
    """Panels at one common scale: 1 DEF px = `scale_out` screen px. Unity frames are resampled so
    the mesh's frame-0 height matches the Blender sprite-camera render of the same mesh (which is
    calibrated to DEF pixels), so all panels share the DEF's scale."""
    clip, g = VARIANTS[runs[0]][0], VARIANTS[runs[0]][1]
    d = h3def.read_def("cgtita.def")
    defs = [Image.fromarray(h3def.to_rgba(f, d.palette)) for f in d.groups[g]]
    m0 = {12: 46, 15: 54}[g]
    blender0 = Image.open(WORK / f"mesh2x/base_{m0 + 1:03d}.png").convert("RGBA")
    b_box = blender0.getbbox()
    mesh_h_def_px = (b_box[3] - b_box[1]) / 2.0  # mesh2x renders at 2 px per DEF px
    data = {r: load_run(r) for r in runs}
    rep0, base0, _ = data[runs[0]]
    u_box = base0[0].getbbox()
    k = mesh_h_def_px * scale_out / (u_box[3] - u_box[1])  # unity px -> output px
    ubox = alpha_box(base0 + sum((data[r][2] for r in runs), []))
    dbox = alpha_box(defs)
    def_panel = lambda i: defs[i].crop(dbox).resize(((dbox[2] - dbox[0]) * scale_out, (dbox[3] - dbox[1]) * scale_out), Image.NEAREST)
    # Unity renders are ~3x the output scale: box-filter them down (what a GPU at that size resolves to)
    uni_panel = lambda im: im.crop(ubox).resize((max(1, round((ubox[2] - ubox[0]) * k)), max(1, round((ubox[3] - ubox[1]) * k))), Image.BOX)
    heads = ["DEF g%d" % g, "mesh, no FX"] + [f"mesh + {r.split('_')[1]}" for r in runs]
    n = len(base0)
    pw = max(def_panel(0).width, uni_panel(base0[0]).width) + 16
    ph = max(def_panel(0).height, uni_panel(base0[0]).height) + 16
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    frames = []
    for i in range(n):
        t = i / rep0["fps"]
        di = min(len(defs) - 1, max(0, int(t * 12 + 1e-6) - 1))  # clip key i sits at (i+1)/12
        panels = [def_panel(di), uni_panel(base0[i])] + [uni_panel(data[r][2][i]) for r in runs]
        W, H = pw * len(panels), ph + 52
        can = Image.new("RGBA", (W, H), (58, 66, 52, 255))  # neutral battlefield-ish green-grey
        dr = ImageDraw.Draw(can)
        for c, (lab, p) in enumerate(zip(heads, panels)):
            dr.text((c * pw + 8, 6), lab, font=font, fill=(235, 235, 225, 255))
            can.alpha_composite(p, (c * pw + (pw - p.width) // 2, 28 + ph - p.height - 8))
        dr.text((8, H - 22), f"t={t:.3f}s  DEF frame {di}  |  1 DEF px = {scale_out} screen px  |  Unity editor render, not in-game",
                font=font, fill=(210, 210, 200, 255))
        frames.append(can.convert("RGB"))
    tag = "" if scale_out == 2 else f"_{scale_out}x"
    out_gif = TITAN / f"compare_unity_{clip_key}{tag}.gif"
    frames[0].save(out_gif, save_all=True, append_images=frames[1:], duration=int(1000 / rep0["fps"]), loop=0)
    # sheet: every other frame (12 fps, i.e. one row per DEF frame)
    picks = frames[::2]
    sheet = Image.new("RGB", (picks[0].width, picks[0].height * len(picks)))
    for j, f in enumerate(picks):
        sheet.paste(f, (0, j * f.height))
    sheet.save(TITAN / f"compare_unity_{clip_key}{tag}_sheet.png")
    print(out_gif, "scale k=%.3f" % k)


if __name__ == "__main__":
    if sys.argv[1] == "specs":
        write_specs()
    else:
        for key, runs in (("attack", ["attack_A", "attack_B"]), ("shoot", ["shoot_A", "shoot_B"])):
            if all((RUNS / (RUN_PREFIX + r) / "preview_report.json").exists() for r in runs):
                compare(key, runs)
                compare(key, runs, scale_out=1)  # ~Olden Era on-screen size (assumption)
