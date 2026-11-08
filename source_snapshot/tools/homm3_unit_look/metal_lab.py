"""Metal lab: Meshy metallic mask evidence, reflection fit, before/after sheets (offline relight only).

python tools/homm3_unit_look/metal_lab.py <unit> [--block '<json lighting.metal block>']
Needs the unit's work/ (look.py <unit> --stages bake). The "before" is the unit's current basecolor.png.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
import look as LK  # noqa: E402
import metal as MT  # noqa: E402
import prebake_lab as pl  # noqa: E402
import spec as S  # noqa: E402
import vfx as VX  # noqa: E402
from glbpatch import Glb  # noqa: E402

BATTLE = ["battle_faces_right", "battle_faces_left", "battle_faces_camera", "battle_faces_away"]


def to_u8(srgb, a, bg=46):
    return (np.clip(srgb, 0, 1) * a[..., None] * 255 + bg * (1 - a[..., None])).astype(np.uint8)


def crop(imgs, alphas, pad=6):
    m = np.zeros_like(alphas[0], bool)
    for a in alphas:
        m |= a > 0.05
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = max(ys.min() - pad, 0), ys.max() + pad, max(xs.min() - pad, 0), xs.max() + pad
    return [i[y0:y1, x0:x1] for i in imgs]


def labelled(img, text, scale):
    im = Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST)
    ImageDraw.Draw(im).text((3, 2), text, fill=(255, 255, 0))
    return im


def hstack(ims, bg=(46, 46, 46)):
    w = sum(i.width for i in ims)
    h = max(i.height for i in ims)
    out = Image.new("RGB", (w, h), bg)
    x = 0
    for i in ims:
        out.paste(i, (x, 0))
        x += i.width
    return out


def vstack(ims, bg=(46, 46, 46)):
    w = max(i.width for i in ims)
    out = Image.new("RGB", (w, sum(i.height for i in ims)), bg)
    y = 0
    for i in ims:
        out.paste(i, (0, y))
        y += i.height
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--block", default=None, help="lighting.metal JSON (default: the spec's, else a Titan-style default)")
    ap.add_argument("--tag", default="v1")
    a = ap.parse_args()
    unit = a.unit
    out = ROOT / "artifacts/homm3_unit_look/_metal_lab" / unit
    out.mkdir(parents=True, exist_ok=True)
    spec = S.load(S.spec_path(unit))
    lt = spec["lighting"]
    classes = (lt.get("knobs") or {}).get("classes")
    block = json.loads(a.block) if a.block else lt.get("metal")
    if block is None:
        raise SystemExit("give --block")
    errs = MT.validate(block, [c["name"] for c in classes or []])
    if errs:
        raise SystemExit("\n".join(errs))
    ctx = LK.build_ctx(unit, spec)
    m = ctx["maps"]
    valid = m["valid"]
    size = m["albedo"].shape[0]
    glb = Glb(LK.resolve_source(unit)[0])
    cond = ctx["cond"]
    rep = {"unit": unit, "block": block, "proof": "generated artifact: numpy relight of Blender passes (Hex/Lit model)"}

    # ---- step 1: the metallic map
    mrb = MT.metallic_roughness_image(glb)
    rep["metallicTexture"] = mrb is not None
    if mrb is not None:
        _, met, rough = MT.meshy_metal_mask(glb, size, {"metallic": [0.45, 0.8]})
        mv, rv = met[valid], rough[valid]
        rep["metallicOnValidTexels"] = {
            "hist10": np.round(np.histogram(mv, bins=10, range=(0, 1))[0] / mv.size, 3).tolist(),
            "share>0.5": round(float((mv > 0.5).mean()), 3), "share<0.2": round(float((mv < 0.2).mean()), 3),
            "roughnessP5_50_95": np.round(np.percentile(rv, [5, 50, 95]), 3).tolist()}
        img = Image.fromarray((np.stack([met, rough, np.zeros_like(met)], -1) * 255).astype(np.uint8))
        img.resize((1024, 1024)).save(out / "metallic_R_rough_G.png")
    W = MT.texture_mask(block, glb, size, None) * valid
    alb_s = pl.lin_to_srgb(m["albedo"])
    ov = alb_s * 0.55 + 0.45 * np.stack([W, np.zeros_like(W), 1 - W], -1) * valid[..., None]
    ov = np.where(valid[..., None], ov, alb_s * 0.3)
    Image.fromarray((np.clip(ov, 0, 1) * 255).astype(np.uint8)).resize((1024, 1024)).save(out / "mask_over_texture.png")
    rep["maskCoverage"] = {"share>0.5": round(float((W[valid] > 0.5).mean()), 3),
                           "meanWeight": round(float(W[valid].mean()), 3)}
    if classes:
        import lighting as LT
        cw = LT.window_weights(pl.lin_to_lab(m["albedo"]), classes)
        rest = np.clip(1 - cw.sum(-1, keepdims=True), 0, 1)
        cw = np.concatenate([cw, rest], -1)
        cw = cw / np.maximum(cw.sum(-1, keepdims=True), 1e-6)
        names = [c["name"] for c in classes] + ["rest"]
        rep["maskShareByAlbedoClass"] = {n: round(float((W[valid & (cw[..., i] > 0.5)] > 0.5).mean()), 3)
                                         for i, n in enumerate(names) if (valid & (cw[..., i] > 0.5)).any()}

    # ---- steps 2-3: fit the reflection on top of the current look
    before = pl.srgb_to_lin(np.asarray(Image.open(S.out_dir(unit) / "basecolor.png").convert("RGB"), np.float32) / 255)
    nz, conv = MT.env_terms(m, block.get("normalDetail", 0.5))
    extras = VX.floor_extras(spec, ctx, ctx["fitViews"])[0]
    p, frep = MT.fit(before, m, W, nz, conv, ctx, ctx["fitViews"], block, classes, cond, extras)
    after = MT.apply_params(before, m, W, nz, conv, p)
    rep["fit"] = frep
    rep["metalMetric"] = MT.region_metric(before, after, W, ctx, ctx["reviewViews"], block["defRegion"], classes, cond)
    # whole-body metric (review.py's L-hist on the mesh vs DEF bodyNoFx), before/after
    body = {"before": [], "after": []}
    for vn in ctx["reviewViews"]:
        rec = ctx["def"][vn]
        ref = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))[..., 0][rec["bodyNoFx"]]
        if ref.size == 0:
            continue
        for n, t in (("before", before), ("after", after)):
            col, al = VX.lit_render(t, ctx["views"][vn], ctx["vmeta"]["views"][vn], cond)
            if (al > 0.9).any():
                body[n].append(pl.hist_distance(pl.lin_to_lab(col)[..., 0][al > 0.9], ref))
    rep["bodyMetric"] = {n: round(float(np.mean(v)), 2) for n, v in body.items()}
    yaw = {}
    for c in ("sand", "grass"):
        for n, t in (("before", before), ("after", after)):
            ms = []
            for b in BATTLE:
                col, al = VX.lit_render(t, ctx["views"][b], ctx["vmeta"]["views"][b], c)
                ms.append(float(pl.lin_to_lab(col)[..., 0][al > 0.9].mean()))
            yaw.setdefault(c, {})[n] = round(max(ms) - min(ms), 1)
    rep["yawSpreadL"] = yaw
    np.save(out / f"metal_tex_{a.tag}.npy", after.astype(np.float16))
    Image.fromarray((pl.lin_to_srgb(after) * 255 + 0.5).astype(np.uint8)).save(out / f"basecolor_metal_{a.tag}.png")

    # ---- sheets: DEF | current look | metal look (sprite views), and battle facings
    rows = []
    for vn in ctx["reviewViews"][:6]:
        rec = ctx["def"][vn]
        v, vmv = ctx["views"][vn], ctx["vmeta"]["views"][vn]
        cb, al = VX.lit_render(before, v, vmv, cond)
        ca, _ = VX.lit_render(after, v, vmv, cond)
        dmask = rec["body"].astype(np.float32)
        wv, _ = pl.downsample(pl.sample_tex(W[..., None], v["uv"]), v["alpha"], vmv["supersample"])
        mimg = np.stack([wv[..., 0], wv[..., 0] * 0.2, 1 - wv[..., 0]], -1) * 0.8
        ims = [to_u8(rec["rgba"][..., :3], dmask), to_u8(pl.lin_to_srgb(cb), al),
               to_u8(pl.lin_to_srgb(ca), al), to_u8(mimg, al)]
        ims = crop(ims, [dmask, al])
        mm = rep["metalMetric"]["views"].get(vn, {})
        rows.append(hstack([labelled(ims[0], f"{vn[-4:]} DEF", 3),
                            labelled(ims[1], f"current {mm.get('before', '')}", 3),
                            labelled(ims[2], f"metal {mm.get('after', '')}", 3),
                            labelled(ims[3], "metal mask", 3)]))
    vstack(rows).save(out / f"sheet_sprite_{a.tag}.png")
    rows = []
    for c in ("sand", "grass"):
        for n, t in (("current", before), ("metal", after)):
            ims, als = [], []
            for b in BATTLE:
                col, al = VX.lit_render(t, ctx["views"][b], ctx["vmeta"]["views"][b], c)
                ims.append(to_u8(pl.lin_to_srgb(col), al))
                als.append(al)
            ims = crop(ims, als)
            rows.append(hstack([labelled(i, f"{n} {c} {b[13:]}", 2) for i, b in zip(ims, BATTLE)]))
    vstack(rows).save(out / f"sheet_battle_{a.tag}.png")
    (out / f"report_{a.tag}.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in rep if k not in ("block",)}, indent=1)[:3000])


if __name__ == "__main__":
    main()
