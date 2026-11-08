#!/usr/bin/env python3
"""Review sheets for the Fortress Meshy T2 buildings.

    set TOWN_FULL3D_CANDIDATE=<cand>
    python fortress_t2_review.py zoom  --layers a,b [--renders preview|unity] [--before <cand>]  # per-building zooms
    python fortress_t2_review.py sheet --before fr_v4 --out <png>                                  # the brief's sheet
    python fortress_t2_review.py isolate --layers a,b --out DIR      # rest preview per layer: environment + that layer only
    python fortress_t2_review.py restde --layers a,b --before DIR --after DIR --out <json>  # per-layer rest dE76

zoom: per layer, a crop around the building at the rest pose and at sweep_left / sweep_right / sweep_high (the crop box
is the layer's fitted model projected by each pose's camera): HoMM3 sprite composite | before | after.
sheet: painting | before (installed candidate's editor renders) | after (this candidate's editor renders) at rest,
sweep_left, sweep_right and sweep_high, plus the zoom rows.
The before candidate is always its editor renders. Renders (after): 'unity' reads <cand>/renders/pan_<pose>.png (editor renders, the review evidence); 'preview' reads
<cand>/work/preview/<pose>.png (moderngl iteration renders).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("TOWN_FULL3D_FACTION", "fortress")   # TOWN_FULL3D_FACTION=factory reviews Factory's T2

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402

W, H = SC.W, SC.H
FACTION = os.environ["TOWN_FULL3D_FACTION"]
FITS = SC.ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_fortress" / "_fits"
POSES = ("default", "sweep_left", "sweep_right", "sweep_high")


def cams(sc) -> dict:
    c = {"default": sc.cam}
    c.update(S.pan_cams(sc))
    return c


def render_path(cand: str, pose: str, kind: str) -> Path:
    base = SC.DATA / "candidates" / cand
    if kind == "unity":
        return base / "renders" / f"pan_{pose}.png"
    return base / "work" / ("preview_cull" if kind == "culled" else "preview") / f"{pose}.png"


def world_points(lid: str):
    """The placed Meshy model's world vertices (None when the layer has no model)."""
    if FACTION == "factory":
        import factory_t2_meshy as FM
        import factory_t2_stage as FS
        return FS.placed(lid)[0]["V"] if (FM.OUT / lid / "fit.json").is_file() else None
    return np.load(FITS / f"{lid}_world.npy") if (FITS / f"{lid}_world.npy").is_file() else None


def sprite_mask(lid: str):
    if FACTION == "factory":
        import factory_t2_stage as FS
        return FS.frame_mask(lid)
    import fortress_t2_buildings as FB
    return FB.sprite_mask_frame(lid) >= 128


def box_for(sc, cam, lid: str, pad: float = 0.25):
    L = SC.layers()[lid]
    P = world_points(lid)
    if P is None:   # no model: the sprite's rest box
        x0, y0 = L["x"] * SC.SCALE, L["y"] * SC.SCALE
        spr = SC.sprite(L)
        return x0, y0, x0 + spr.width * SC.SCALE, y0 + spr.height * SC.SCALE
    px, py, zc = T.project(cam, P)
    ok = zc > 0
    x0, x1, y0, y1 = px[ok].min(), px[ok].max(), py[ok].min(), py[ok].max()
    w, h = x1 - x0, y1 - y0
    s = max(w, h) * (1 + 2 * pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2


def crop(img: Image.Image, box, size=300) -> Image.Image:
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    c = Image.new("RGB", (x1 - x0, y1 - y0), (0, 0, 0))
    ix0, iy0, ix1, iy1 = max(0, x0), max(0, y0), min(img.width, x1), min(img.height, y1)
    if ix1 > ix0 and iy1 > iy0:   # the building can leave the frame at a sweep pose: black then
        c.paste(img.crop((ix0, iy0, ix1, iy1)), (ix0 - x0, iy0 - y0))
    return c.resize((size, size), Image.LANCZOS)


def lab(img: Image.Image, text: str) -> Image.Image:
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, min(img.width, 8 + 7 * len(text)), 16), fill=(0, 0, 0))
    d.text((4, 3), text, fill=(255, 255, 255))
    return img


def grid(rows: list[list[Image.Image]], gap=6, bg=(40, 40, 40)) -> Image.Image:
    wmax = max(sum(i.width for i in r) + gap * (len(r) - 1) for r in rows)
    hsum = sum(max(i.height for i in r) for r in rows) + gap * (len(rows) - 1)
    out = Image.new("RGB", (wmax, hsum), bg)
    y = 0
    for r in rows:
        x = 0
        for i in r:
            out.paste(i, (x, y))
            x += i.width + gap
        y += max(i.height for i in r) + gap
    return out


def homm3_full() -> Image.Image:
    return S.homm3_reference(S.STATES["full"])


def zoom_rows(sc, lids, before: str, after: str, kind: str, size=260) -> list[list[Image.Image]]:
    cs = cams(sc)
    ref = homm3_full()
    imgs = {(c, p): Image.open(render_path(c, p, "unity" if c == before else kind)).convert("RGB")
            for c in (before, after) for p in POSES}
    rows = []
    for lid in lids:
        row = [lab(crop(ref, box_for(sc, sc.cam, lid), size), f"{lid} HoMM3")]
        for p in POSES:
            b = box_for(sc, cs[p], lid)
            row += [lab(crop(imgs[(before, p)], b, size), f"before {p}"), lab(crop(imgs[(after, p)], b, size), f"after {p}")]
        rows.append(row)
    return rows


def render_culled(R, cam, cull: str):
    """The lane Renderer with back-face culling (the game's Cull Back) instead of its two-sided default: a
    double-sided Meshy body otherwise z-fights its reversed copy, whose normal faces away, and reads blotchy."""
    import moderngl
    if cull == "none":
        return R.render(cam, near=2.0, far=T.DOME_R * 1.2)
    ctx = R.ctx
    orig = ctx.disable

    def disable(flag):
        orig(flag)
        if flag == moderngl.CULL_FACE:
            ctx.enable(moderngl.CULL_FACE)
            ctx.front_face = cull
    ctx.disable = disable
    try:
        return R.render(cam, near=2.0, far=T.DOME_R * 1.2)
    finally:
        ctx.disable = orig


def isolate(sc, lids, out: Path, cull: str = "none") -> None:
    """Rest preview (the lane's moderngl renderer) of the environment plus one building layer, per layer, from this
    candidate's staged bins: the rest-frame comparison against the painting without the other building levels that the
    all-prefab preview stacks on top of each other."""
    import stronghold_full3d_preview as PV
    S.load_staged_preview(sc, None)
    builds = {S.PREFIX + l for l in SC.reachable_layers()}
    R = PV.Renderer(sc.rig, sc.sun, W, H)
    for name, P, n, uv, tris, img, unlit in (r for r in sc.preview if r[0].split("/")[0] not in builds):
        R.add(name, P, n, uv, tris, img, unlit=unlit)
    n_env = len(R.pieces)
    out.mkdir(parents=True, exist_ok=True)
    for lid in lids:
        for name, P, n, uv, tris, img, unlit in (r for r in sc.preview if r[0].split("/")[0] == S.PREFIX + lid):
            R.add(name, P, n, uv, tris, img, unlit=unlit)
        Image.fromarray(render_culled(R, sc.cam, cull)).save(out / f"{lid}.png")
        R.pieces = R.pieces[:n_env]
        print(lid, flush=True)


def restde(lids, before: Path, after: Path) -> dict:
    """Mean / p90 CIELAB dE76 of each isolated rest render against the painting with that layer alone, over the layer's
    sprite mask (x1.8 frame px, alpha >= 128)."""
    import cv2
    lab = lambda im: cv2.cvtColor(np.asarray(im.convert("RGB"), np.float32) / 255, cv2.COLOR_RGB2LAB)  # noqa: E731
    rep = {}
    for lid in lids:
        R = lab(S.homm3_reference([lid]))
        m = sprite_mask(lid)
        rep[lid] = {"maskPx": int(m.sum())}
        for k, d in (("before", before), ("after", after)):
            de = np.linalg.norm(lab(Image.open(d / f"{lid}.png")) - R, axis=-1)[m]
            rep[lid][k] = {"meanDE": round(float(de.mean()), 2), "p90DE": round(float(np.percentile(de, 90)), 2)}
        rep[lid]["winner"] = "meshy" if rep[lid]["after"]["meanDE"] < rep[lid]["before"]["meanDE"] else "relief"
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["zoom", "sheet", "isolate", "restde", "pans"])
    ap.add_argument("--layers", default="")
    ap.add_argument("--renders", default="preview", choices=["preview", "culled", "unity"])
    ap.add_argument("--before", default="fr_v4")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cull", default="none", choices=["none", "cw", "ccw"])
    ap.add_argument("--before-dir", default="")
    ap.add_argument("--after-dir", default="")
    a = ap.parse_args()
    after = os.environ["TOWN_FULL3D_CANDIDATE"]
    lids = [x for x in a.layers.split(",") if x]
    if a.cmd == "restde":
        rep = restde(lids, Path(a.before_dir), Path(a.after_dir))
        Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
        for k, v in rep.items():
            print(f"{k:12s} before {v['before']['meanDE']:6.2f} after {v['after']['meanDE']:6.2f}  {v['winner']}")
        return 0
    sc = S.Scene()
    if a.cmd == "pans":   # rest + pan poses, Cull Back (the game's culling), all staged prefabs -> work/preview_cull
        import stronghold_full3d_preview as PV
        S.load_staged_preview(sc, None)
        R = PV.Renderer(sc.rig, sc.sun, W, H)
        for name, P, n, uv, tris, img, unlit in sc.preview:
            R.add(name, P, n, uv, tris, img, unlit=unlit)
        d = SC.DATA / "candidates" / after / "work" / "preview_cull"
        d.mkdir(parents=True, exist_ok=True)
        for k, cam in cams(sc).items():
            Image.fromarray(render_culled(R, cam, "cw")).save(d / f"{k}.png")
        print(d)
        return 0
    if a.cmd == "isolate":
        isolate(sc, lids, Path(a.out), a.cull)
        return 0
    if a.cmd == "zoom":
        rows = zoom_rows(sc, lids, a.before, after, a.renders)
        grid(rows).save(a.out)
        print(a.out)
        return 0
    ref = homm3_full()
    top = []
    for p in POSES:
        b = Image.open(render_path(a.before, p, "unity")).convert("RGB").resize((640, 360), Image.LANCZOS)
        f = Image.open(render_path(after, p, a.renders)).convert("RGB").resize((640, 360), Image.LANCZOS)
        first = lab(ref.resize((640, 360), Image.LANCZOS), "HoMM3 painting (full state)") if p == "default" else \
            Image.new("RGB", (640, 360), (40, 40, 40))
        top.append([first, lab(b, f"before {a.before} {p}"), lab(f, f"after {after} {p}")])
    rows = top + zoom_rows(sc, lids, a.before, after, a.renders, size=210)
    grid(rows).save(a.out)
    print(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
