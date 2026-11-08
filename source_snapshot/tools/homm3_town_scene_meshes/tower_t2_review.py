#!/usr/bin/env python3
"""Tower T2 buildings: review renders and sheets (docs/homm3_tower_t2_town_buildings.md).

    TOWN_FULL3D_CANDIDATE=tw_t2 python tools/homm3_town_scene_meshes/tower_t2_review.py preview [--state full]
        moderngl previews (iteration only) of the seed tw_v4 and the candidate, same state, same poses:
        <candidate>/work/t2_preview/{seed,cand}_<state>_<pose>.png
    TOWN_FULL3D_CANDIDATE=tw_t2 python tools/homm3_town_scene_meshes/tower_t2_review.py sheet [--source unity|preview]
        artifacts/claude_takeover_20260927/review/homm3_tower_t2_buildings.png: painting | before (installed tw_v4) |
        after (candidate), at rest and at sweep_left / sweep_right / sweep_high, plus building zooms. unity = the
        editor renders of both (<cand>/renders/full3d_full.png, pan_sweep_*.png; the pan renders show the full state).
Proof tier: generated artifact (editor / offline renders).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "tower")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402

POSES = ["default", "sweep_left", "sweep_right", "sweep_high"]
SEED = "tw_v4"
SHEET = SC.ROOT / "artifacts" / "claude_takeover_20260927" / "review" / "homm3_tower_t2_buildings.png"
ZOOMS = [("tbtwhall_4", "capitol"), ("tbtwcstl_3", "castle"), ("tbtwmage_4", "mage guild"),
         ("tbtwdw_6_2", "cloud temple"), ("tbtwblak", "blacksmith"), ("tbtwdw_2_2", "golem factory")]


def load(sc, root: Path, prefabs: list[str]) -> None:
    stage = root / "unity_project" / S.ASSET_ROOT
    rows = json.loads((stage / "rows.json").read_text(encoding="utf-8"))
    sc.preview = []
    for pk in prefabs:
        for b in rows[pk]["bins"]:
            mb = stage / pk / f"{b['name']}.bytes"
            tex = mb.with_name(mb.stem + "_albedo.png")
            if not tex.is_file():
                continue
            v, n, uv, subs = S.read_bin(mb)
            if mb.stem == "Sky_Drift":
                import town_full3d_sky as SKY
                v, n = SKY.holder_to_prefab(v, n, pk)
            P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
            nw = n.astype(np.float64) @ sc.C.T
            sc.preview.append((f"{pk}/{mb.stem}", P.astype(np.float32), nw.astype(np.float32), uv,
                               np.concatenate(subs), np.asarray(Image.open(tex)), mb.stem.startswith("Sky_")))


FRONT_FACE = os.environ.get("TOWER_T2_FRONT_FACE", "cw")


def render_culled(R, cam: dict, near: float, far: float) -> np.ndarray:
    """stronghold_full3d_preview.Renderer.render with back-face culling on the lit pieces, as the game's Hex/Lit
    (Cull Back; unity/Homm3TownLabHexLit.shader). The two-sided T2 bins z-fight without it."""
    import moderngl
    import stronghold_full3d_preview as PV
    mvp = PV.perspective(cam["fov"], R.w / R.h, near, far) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
    R.fbo.use()
    R.ctx.clear(1.0, 0.0, 1.0, 1.0)
    R.ctx.front_face = FRONT_FACE
    p = R.prog
    p["mvp"].write(mvp.T.astype(np.float32).tobytes())
    for k in ("sunColor", "ambSky", "ambEq", "ambGround"):
        p[k].value = tuple(float(x) for x in R.rig[k])
    p["sunDir"].value = tuple(float(x) for x in R.sun)
    p["fillDir"].value = tuple(float(x) for x in R.rig.get("fillDir", (0, -1, 0)))
    p["fillColor"].value = tuple(float(x) for x in R.rig.get("fillColor", (0, 0, 0)))
    for pc in sorted(R.pieces, key=lambda q: not q["unlit"]):
        p["unlit"].value = int(pc["unlit"])
        p["cutout"].value = float(pc["cutout"])
        if pc["unlit"]:
            R.ctx.disable(moderngl.DEPTH_TEST)
            R.ctx.disable(moderngl.CULL_FACE)
        else:
            R.ctx.enable(moderngl.DEPTH_TEST)
            R.ctx.enable(moderngl.CULL_FACE)
        pc["tex"].use(0)
        p["tex"].value = 0
        pc["vao"].render()
    R.ctx.disable(moderngl.CULL_FACE)
    R.ctx.copy_framebuffer(R.out, R.fbo)
    a = np.frombuffer(R.out.read(components=3), np.uint8).reshape(R.h, R.w, 3)
    return a[::-1].copy()


def preview(state: str) -> None:
    import stronghold_full3d_preview as PV
    import stronghold_full3d_terrain as T
    sc = S.Scene()
    cams = {"default": sc.cam, **{k: v for k, v in S.pan_cams(sc).items() if k in POSES}}
    prefabs = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES[state]]
    out = S.WORK / "t2_preview"
    out.mkdir(parents=True, exist_ok=True)
    for tag, root in (("seed", SC.DATA / "candidates" / SEED), ("cand", S.CAND)):
        load(sc, root, prefabs)
        R = PV.Renderer(sc.rig, sc.sun, SC.W, SC.H)
        for name, P, n, uv, tris, img, unlit in sc.preview:
            R.add(name, P, n, uv, tris, img, unlit=unlit)
        for k, c in cams.items():
            Image.fromarray(render_culled(R, c, 2.0, T.DOME_R * 1.2)).save(out / f"{tag}_{state}_{k}.png")
        print(tag, state, "rendered")


def bbox(lid: str, pad: float = 0.25) -> tuple[int, int, int, int]:
    L = SC.layers()[lid]
    im = SC.sprite(L)
    x0, y0 = L["x"] * SC.SCALE, L["y"] * SC.SCALE
    w, h = im.width * SC.SCALE, im.height * SC.SCALE
    p = pad * max(w, h)
    return (int(max(0, x0 - p)), int(max(0, y0 - p)), int(min(SC.W, x0 + w + p)), int(min(SC.H, y0 + h + p)))


def sheet(source: str) -> Path:
    seed = SC.DATA / "candidates" / SEED
    if source == "unity":
        def shot(root, pose):
            return root / "renders" / ("full3d_full.png" if pose == "default" else f"pan_{pose}.png")
    else:
        def shot(root, pose):
            return S.WORK / "t2_preview" / f"{'seed' if root == seed else 'cand'}_full_{pose}.png"
    paint = S.homm3_reference(SC.FP.STATES["full"])
    cw, ch = 960, 540
    cols = ["HoMM3 painting (full state)", f"before: installed {SEED}", f"after: {S.CANDIDATE} (Meshy T2)"]
    rows_img = []
    for pose in POSES:
        ims = [paint if pose == "default" else None, Image.open(shot(seed, pose)).convert("RGB"),
               Image.open(shot(S.CAND, pose)).convert("RGB")]
        rows_img.append((pose, ims))
    zw, zh = 640, 540
    zrows = []
    for lid, name in ZOOMS:
        b = bbox(lid)
        ims = [paint.crop(b), Image.open(shot(seed, "default")).convert("RGB").crop(b),
               Image.open(shot(S.CAND, "default")).convert("RGB").crop(b)]
        zrows.append((f"{lid} {name} (rest)", ims))
    lab = 28
    Wt = 3 * cw
    Ht = lab + len(rows_img) * (ch + lab) + len(zrows) * (zh + lab)
    out = Image.new("RGB", (Wt, Ht), (24, 24, 24))
    d = ImageDraw.Draw(out)
    for i, c in enumerate(cols):
        d.text((i * cw + 8, 6), c, fill=(255, 255, 255))
    y = lab
    for pose, ims in rows_img:
        d.text((8, y + 4), f"pose: {pose}", fill=(255, 220, 120))
        for i, im in enumerate(ims):
            if im is not None:
                out.paste(im.resize((cw, ch), Image.LANCZOS), (i * cw, y + lab))
            else:
                d.text((i * cw + 20, y + lab + 20), "(HoMM3 has one fixed view)", fill=(160, 160, 160))
        y += ch + lab
    for title, ims in zrows:
        d.text((8, y + 4), title, fill=(255, 220, 120))
        for i, im in enumerate(ims):
            s = min(zw / im.width, zh / im.height)
            r = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
            out.paste(r, (i * cw + (cw - r.width) // 2, y + lab))
        y += zh + lab
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    out.save(SHEET)
    print(SHEET)
    return SHEET


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preview", "sheet"])
    ap.add_argument("--state", default="full")
    ap.add_argument("--source", default="unity", choices=["unity", "preview"])
    ap.add_argument("--faction", default="tower")
    a = ap.parse_args()
    if not S.CANDIDATE or S.CANDIDATE == SEED:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE to the T2 candidate")
    if a.cmd == "preview":
        preview(a.state)
    else:
        sheet(a.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
