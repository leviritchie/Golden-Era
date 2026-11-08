#!/usr/bin/env python3
"""Compose labeled multi-angle UniRig cross-section and bone role map."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot/rig_cross_section"
)


def bone_color(name: str) -> tuple[int, int, int]:
    n = int(name.split("_")[-1])
    if n in {0, 1}:
        return (0, 255, 255)
    if n in {2, 3, 17, 18, 19, 26, 27, 28, 29}:
        return (0, 220, 255)
    if n in {20, 21, 22, 30, 31, 32, 33, 34, 35, 36, 37}:
        return (255, 64, 255)
    if n in {23, 24, 25, 38, 39, 40, 41, 42, 43, 44, 45}:
        return (80, 255, 80)
    if n in {4, 5, 6}:
        return (255, 180, 40)
    if n in {7, 8, 9, 10, 11}:
        return (255, 255, 60)
    if n in {12, 13, 14, 15, 16}:
        return (255, 140, 40)
    return (200, 200, 200)


def draw_view(view_name: str, title: str) -> Image.Image:
    mesh = Image.open(OUT / f"mesh_{view_name}.png").convert("RGBA")
    proj = json.loads((OUT / f"proj_{view_name}.json").read_text(encoding="utf-8"))
    bg = Image.new("RGBA", mesh.size, (16, 16, 20, 255))
    bg.alpha_composite(mesh)
    im = bg.convert("RGB")
    dr = ImageDraw.Draw(im)
    bones = proj["bones"]
    for e in proj["edges"]:
        a = bones[e["parent"]]
        b = bones[e["child"]]
        dr.line([(a["px"], a["py"]), (b["px"], b["py"])], fill=bone_color(e["child"]), width=3)
    for name, b in bones.items():
        x, y = b["px"], b["py"]
        r = 4
        dr.ellipse([x - r, y - r, x + r, y + r], fill=bone_color(name), outline=(0, 0, 0))
        dr.text((x + 5, y - 10), name.replace("Bone_", ""), fill=(255, 255, 255))
    dr.rectangle([0, 0, im.width, 44], fill=(10, 10, 12))
    dr.text((10, 6), title, fill=(240, 240, 240))
    dr.text(
        (10, 24),
        "magenta=022wingA  lime=025wingB  cyan=spine/head  orange=tail  yellow=legA  darkorange=legB",
        fill=(180, 180, 190),
    )
    im.save(OUT / f"labeled_{view_name}.png")
    return im


def fit_h(im: Image.Image, h: int) -> Image.Image:
    w = int(round(im.width * (h / im.height)))
    return im.resize((w, h), Image.BILINEAR)


def main() -> None:
    profile = draw_view("profile_mX", "PROFILE (-X)  beak RIGHT of tail")
    top = draw_view("top", "TOP-DOWN (+Z)")
    front = draw_view("front_mY", "FRONT (from beak / -Y)")
    draw_view("profile_pX", "PROFILE (+X) mirrored")
    draw_view("front_pY", "REAR (from tail / +Y)")

    h = 520
    L, T, F = fit_h(profile, h), fit_h(top, h), fit_h(front, h)
    sheet = Image.new("RGB", (L.width + T.width + F.width + 24, h), (8, 8, 10))
    x = 0
    for im in (L, T, F):
        sheet.paste(im, (x, 0))
        x += im.width + 12
    sheet.save(OUT / "cross_section_3view.png")
    print("sheet", sheet.size)

    proj = json.loads((OUT / "proj_profile_mX.json").read_text(encoding="utf-8"))
    bones = proj["bones"]
    topb = json.loads((OUT / "proj_top.json").read_text(encoding="utf-8"))["bones"]
    frontb = json.loads((OUT / "proj_front_mY.json").read_text(encoding="utf-8"))["bones"]

    def W(name: str) -> np.ndarray:
        return np.array(bones[name]["head"], dtype=float)

    beak = W("Bone_028")
    tail = W("Bone_004")
    print("beak", beak, "tail", tail, "delta", beak - tail)
    print("wingA_035", W("Bone_035"), "wingB_043", W("Bone_043"))
    print("legA_007", W("Bone_007"), "legB_012", W("Bone_012"))

    print("\n=== TOP px ===")
    for n in [
        "Bone_022",
        "Bone_035",
        "Bone_025",
        "Bone_043",
        "Bone_028",
        "Bone_004",
        "Bone_007",
        "Bone_012",
        "Bone_000",
    ]:
        b = topb[n]
        print(f"{n:10s} top_px=({b['px']:.0f},{b['py']:.0f})")

    print("\n=== FRONT px ===")
    for n in [
        "Bone_022",
        "Bone_035",
        "Bone_025",
        "Bone_043",
        "Bone_028",
        "Bone_007",
        "Bone_012",
        "Bone_000",
    ]:
        b = frontb[n]
        print(f"{n:10s} front_px=({b['px']:.0f},{b['py']:.0f})")

    root_tx = topb["Bone_000"]["px"]
    root_fx = frontb["Bone_000"]["px"]
    wingA_top = "SCREEN_RIGHT" if topb["Bone_035"]["px"] > root_tx else "SCREEN_LEFT"
    wingB_top = "SCREEN_RIGHT" if topb["Bone_043"]["px"] > root_tx else "SCREEN_LEFT"
    wingA_front = "SCREEN_RIGHT" if frontb["Bone_035"]["px"] > root_fx else "SCREEN_LEFT"
    wingB_front = "SCREEN_RIGHT" if frontb["Bone_043"]["px"] > root_fx else "SCREEN_LEFT"
    legA_top = "SCREEN_RIGHT" if topb["Bone_007"]["px"] > root_tx else "SCREEN_LEFT"
    legB_top = "SCREEN_RIGHT" if topb["Bone_012"]["px"] > root_tx else "SCREEN_LEFT"

    roles = {
        "Bone_000": {"role": "root_pelvis", "chain": "spine"},
        "Bone_001": {"role": "spine_mid", "chain": "spine"},
        "Bone_003": {"role": "chest", "chain": "spine"},
        "Bone_002": {"role": "upper_chest_wing_hub", "chain": "spine"},
        "Bone_019": {"role": "neck_base", "chain": "head"},
        "Bone_018": {"role": "neck_mid", "chain": "head"},
        "Bone_017": {"role": "skull", "chain": "head"},
        "Bone_027": {"role": "upper_beak_base", "chain": "head"},
        "Bone_026": {"role": "upper_beak_tip", "chain": "head"},
        "Bone_029": {"role": "lower_beak_base", "chain": "head"},
        "Bone_028": {"role": "beak_tip", "chain": "head"},
        "Bone_006": {"role": "tail_base", "chain": "tail"},
        "Bone_005": {"role": "tail_mid", "chain": "tail"},
        "Bone_004": {"role": "tail_tip", "chain": "tail"},
        "Bone_022": {"role": "wingA_shoulder", "chain": "wingA_022"},
        "Bone_021": {"role": "wingA_elbow", "chain": "wingA_022"},
        "Bone_020": {"role": "wingA_wrist", "chain": "wingA_022"},
        "Bone_031": {"role": "wingA_digit0_mid", "chain": "wingA_022"},
        "Bone_030": {"role": "wingA_digit0_tip", "chain": "wingA_022"},
        "Bone_034": {"role": "wingA_digit1_prox", "chain": "wingA_022"},
        "Bone_033": {"role": "wingA_digit1_mid", "chain": "wingA_022"},
        "Bone_032": {"role": "wingA_digit1_tip", "chain": "wingA_022"},
        "Bone_037": {"role": "wingA_digit2_prox", "chain": "wingA_022"},
        "Bone_036": {"role": "wingA_digit2_mid", "chain": "wingA_022"},
        "Bone_035": {"role": "wingA_digit2_tip", "chain": "wingA_022"},
        "Bone_025": {"role": "wingB_shoulder", "chain": "wingB_025"},
        "Bone_024": {"role": "wingB_elbow", "chain": "wingB_025"},
        "Bone_023": {"role": "wingB_wrist", "chain": "wingB_025"},
        "Bone_039": {"role": "wingB_digit0_mid", "chain": "wingB_025"},
        "Bone_038": {"role": "wingB_digit0_tip", "chain": "wingB_025"},
        "Bone_042": {"role": "wingB_digit1_prox", "chain": "wingB_025"},
        "Bone_041": {"role": "wingB_digit1_mid", "chain": "wingB_025"},
        "Bone_040": {"role": "wingB_digit1_tip", "chain": "wingB_025"},
        "Bone_045": {"role": "wingB_digit2_prox", "chain": "wingB_025"},
        "Bone_044": {"role": "wingB_digit2_mid", "chain": "wingB_025"},
        "Bone_043": {"role": "wingB_digit2_tip", "chain": "wingB_025"},
        "Bone_011": {"role": "legA_hip", "chain": "legA"},
        "Bone_010": {"role": "legA_knee", "chain": "legA"},
        "Bone_009": {"role": "legA_ankle", "chain": "legA"},
        "Bone_008": {"role": "legA_foot", "chain": "legA"},
        "Bone_007": {"role": "legA_talon_tip", "chain": "legA"},
        "Bone_016": {"role": "legB_hip", "chain": "legB"},
        "Bone_015": {"role": "legB_knee", "chain": "legB"},
        "Bone_014": {"role": "legB_ankle", "chain": "legB"},
        "Bone_013": {"role": "legB_foot", "chain": "legB"},
        "Bone_012": {"role": "legB_talon_tip", "chain": "legB"},
    }

    summary = {
        "beakWorld": [float(x) for x in beak],
        "tailWorld": [float(x) for x in tail],
        "profileView": "profile_mX",
        "topView": "top",
        "frontView": "front_mY",
        "wingA_022": {
            "topSideOfRoot": wingA_top,
            "frontSideOfRoot": wingA_front,
            "tip": "Bone_035",
            "chain": "022-021-020 + digits 031/030, 034/033/032, 037/036/035",
        },
        "wingB_025": {
            "topSideOfRoot": wingB_top,
            "frontSideOfRoot": wingB_front,
            "tip": "Bone_043",
            "chain": "025-024-023 + digits 039/038, 042/041/040, 045/044/043",
        },
        "legA_011": {"topSideOfRoot": legA_top, "tip": "Bone_007"},
        "legB_016": {"topSideOfRoot": legB_top, "tip": "Bone_012"},
        "roles": roles,
    }
    (OUT / "bone_roles.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wingA", wingA_top, wingA_front)
    print("wingB", wingB_top, wingB_front)
    print("legA", legA_top, "legB", legB_top)
    print("wrote", OUT / "cross_section_3view.png")


if __name__ == "__main__":
    main()
