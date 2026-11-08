#!/usr/bin/env python3
"""T2 town review sheet (any faction via TOWN_FULL3D_FACTION, --zooms a,b,...): painting | before (installed candidate) | after (Meshy T2 candidate), Unity editor renders.

    TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/t2_town_review.py --before wall_v40 \
        --out artifacts/claude_takeover_20260927/review/homm3_stronghold_t2_buildings.png

Rows: the full state at rest (full3d_full.png) and at the vanilla sweep poses (pan_sweep_left / right / high), then
building zooms: each zoom layer's box is its staged after-mesh projected by that pose's camera (the same box is cut
from the before render). The painting column is the HoMM3 town screen of the full state (it has no sweep; it repeats
the rest for reference). Also writes a per-row dE76 of rest vs painting over each Meshy layer's sprite mask
(diagnostic only; the Meshy layers are the candidate catalog's meshyBuildings.layers).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

POSES = [("rest", "full3d_full.png"), ("sweep_left", "pan_sweep_left.png"), ("sweep_right", "pan_sweep_right.png"),
         ("sweep_high", "pan_sweep_high.png")]
ZOOMS = ["extraCapitol_3", "wall_3", "magicGuild_3", "dwellingUp2Lvl3_2", "dwellingUp2Lvl4_2", "tavern",
         "dwellingUp2Lvl2_2", "bank", "market", "lyceum", "dwellingUp2Lvl6_2", "dwellingUp2Lvl7_2"]   # Stronghold
CW = 640   # column width of the sheet (a 1920x1080 render at 1/3)


def label(im: Image.Image, text: str) -> Image.Image:
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 8 * len(text) + 8, 16), fill=(0, 0, 0))
    d.text((4, 2), text, fill=(255, 255, 0))
    return im


def mesh_box(sc, lid: str, cam: dict) -> tuple[int, int, int, int] | None:
    pre = S.PREFIX + lid
    pts = [P for name, P, *_ in sc.preview if name.startswith(pre + "/Mesh_Body")]
    if not pts:
        return None
    px, py, zc = T.project(cam, np.concatenate(pts).astype(np.float64))
    ok = zc > 0
    x0, x1 = np.percentile(px[ok], [0.5, 99.5])
    y0, y1 = np.percentile(py[ok], [0.5, 99.5])
    pad = 0.12 * max(x1 - x0, y1 - y0) + 8
    return int(x0 - pad), int(y0 - pad), int(x1 + pad), int(y1 + pad)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="candidates/<name> holding the before renders")
    ap.add_argument("--out", required=True)
    ap.add_argument("--zooms", default="", help="comma list of zoom layers (default: the Stronghold list)")
    a = ap.parse_args()
    zooms = [x for x in a.zooms.split(",") if x] or ZOOMS
    before = SC.DATA / "candidates" / a.before / "renders"
    after = S.RENDERS
    ref = S.homm3_reference(S.STATES["full"])
    sc = S.Scene()
    S.load_staged_preview(sc)
    cams = {"rest": sc.cam, **{k: v for k, v in S.pan_cams(sc).items()}}
    rows = []
    for pose, fn in POSES:
        ims = [ref, Image.open(before / fn).convert("RGB"), Image.open(after / fn).convert("RGB")]
        row = Image.new("RGB", (CW * 3, CW * 9 // 16))
        for i, (im, cap) in enumerate(zip(ims, ["painting (HoMM3)", f"before {a.before}", f"after {S.CANDIDATE}"])):
            row.paste(label(im.resize((CW, CW * 9 // 16), Image.LANCZOS), f"{pose}: {cap}"), (i * CW, 0))
        rows.append(row)
    # zooms: one row per layer, rest + the three sweeps, before over after
    zw = CW * 3 // 4
    for lid in zooms:
        row = Image.new("RGB", (CW * 3, zw * 2 // 3 * 2), (40, 40, 40))
        for j, (pose, fn) in enumerate(POSES):
            cam = cams.get(pose)
            box = mesh_box(sc, lid, cam) if cam is not None else None
            if box is None:
                continue
            for k, src in enumerate((before, after)):
                im = Image.open(src / fn).convert("RGB").crop(box)
                im.thumbnail((zw, zw * 2 // 3), Image.LANCZOS)
                row.paste(label(im, f"{lid} {pose} {'before' if k == 0 else 'after'}"), (j * zw, k * zw * 2 // 3))
        rows.append(row)
    sheet = Image.new("RGB", (CW * 3, sum(r.height for r in rows)))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    # rest dE over each Meshy layer's sprite mask (full state layers only)
    import cv2
    import stronghold_full3d_buildings as BL
    meshed = set(json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))["meshyBuildings"]["layers"])
    lab = lambda im: cv2.cvtColor(np.asarray(im, np.float32) / 255, cv2.COLOR_RGB2LAB)  # noqa: E731
    R = lab(ref)
    rep = {}
    for lid in S.STATES["full"]:
        if lid not in meshed:
            continue
        L = SC.layers()[lid]
        m8 = BL.native_mask(L).astype(np.uint8) * 255
        big = cv2.resize(m8, (round(m8.shape[1] * SC.SCALE), round(m8.shape[0] * SC.SCALE)))
        m = np.zeros((SC.H, SC.W), bool)
        x, y = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
        sy, sx = max(0, -y), max(0, -x)
        h_, w_ = min(big.shape[0] - sy, SC.H - max(0, y)), min(big.shape[1] - sx, SC.W - max(0, x))
        m[max(0, y):max(0, y) + h_, max(0, x):max(0, x) + w_] = big[sy:sy + h_, sx:sx + w_] > 127
        rep[lid] = {}
        for k, src in (("before", before), ("after", after)):
            X = lab(Image.open(src / "full3d_full.png").convert("RGB"))
            de = np.linalg.norm(X - R, axis=-1)[m]
            rep[lid][k] = {"meanDE": round(float(de.mean()), 2), "p90DE": round(float(np.percentile(de, 90)), 2)}
    (out.with_suffix(".json")).write_text(json.dumps({"sheet": str(out), "restDE": rep,
                                                      "note": "rest dE76 is a diagnostic only (never a revert gate)"},
                                                     indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
