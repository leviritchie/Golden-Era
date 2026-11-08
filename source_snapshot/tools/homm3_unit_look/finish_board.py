"""Before/after boards and the crush score for the look finish (finish.py, look B).

    python tools/homm3_unit_look/finish_board.py --rows <rows.json> --out <sheet.png> [--device cuda|cpu]

rows.json: [{"title", "glb" (geometry: the un-prebaked source GLB or the delivered GLB), "a", "b" (sRGB PNGs),
"def" (DEF idle frame 0 PNG), "raw" (the un-prebaked source base colour, for the crush score; optional), "note"}].
Each row: DEF idle f0 | A battle | B battle | A preview | B preview, Unit_Idle frame 0 of ``glb`` relit with the sand
sun + ambient + shadow map (finish.gbuffer) at game-distance tiles (TILE px, the unit's larger extent at 85%); battle =
orthographic 40 deg elevation, yaw 120 (render_passes battle_faces_right); preview = UiConstants.UnitCamParams angle
(13.7 deg) at the fleet preview facing (body yaw 112), rendered orthographic (the game's is a narrow perspective).
Crush (V:/olden_port_work/authenticity/h3_pegasus/blk/crushscan.py, same rule): of the texels whose raw L* >= 60
(chart: raw max channel > 8, both at 512 nearest), the share the look leaves at L* < 25.
Torch, CUDA by default; --device cpu is the reference (finish.py kernels; test_finish.py). Proof: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as TF
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finish as FN  # noqa: E402

TILE = 256
SS = 2
BG = np.array([0.55, 0.50, 0.40])
PREVIEW_YAW, PREVIEW_ELEV = 112.0, 13.7


def crush_score(raw_png: Path, look_png: Path) -> dict:
    def L(rgb):
        c = rgb / 255.0
        c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        Y = c @ [0.2126, 0.7152, 0.0722]
        f = np.where(Y > 0.008856, np.cbrt(Y), 7.787 * Y + 16 / 116)
        return (116 * f - 16) / 100
    a = np.asarray(Image.open(look_png).convert("RGB").resize((512, 512), Image.NEAREST)).astype(float)
    r = np.asarray(Image.open(raw_png).convert("RGB").resize((512, 512), Image.NEAREST)).astype(float)
    chart = r.max(-1) > 8
    la, lr = L(a), L(r)
    pale = chart & (lr >= 0.60)
    return {"crush": float((pale & (la < 0.25)).sum() / max(1, pale.sum())),
            "darkLook": float((chart & (la < 0.25)).mean() / max(chart.mean(), 1e-9)),
            # the blotch itself: pale raw texels the look leaves near black (L* < 10)
            "blackCrush": float((pale & (la < 0.10)).sum() / max(1, pale.sum()))}


def font(n):
    try:
        return ImageFont.truetype("arial.ttf", n)
    except OSError:
        return ImageFont.load_default()


def render(geo, tex, yaw, elev):
    gb = FN.gbuffer(geo, yaw=yaw, size=TILE * SS, elev=elev, fill=0.85)
    uv = gb["uv"]
    grid = torch.stack([torch.remainder(uv[:, 0], 1.0) * 2 - 1, FN.vwrap(uv[:, 1]) * 2 - 1], -1).to(torch.float32)
    alb = TF.grid_sample(tex.permute(2, 0, 1)[None], grid[None, None], mode="bilinear", padding_mode="border",
                         align_corners=False)[0, :, 0].T.to(torch.float64)
    rgb = FN.lin_to_srgb(FN.srgb_to_lin(alb) * gb["light"])
    img = torch.as_tensor(BG, dtype=torch.float64, device=tex.device).expand(TILE * SS, TILE * SS, 3).clone()
    img[gb["mask"]] = rgb
    img = TF.avg_pool2d(img.permute(2, 0, 1)[None], SS)[0].permute(1, 2, 0)
    m = TF.avg_pool2d(gb["mask"][None, None].float(), SS)[0, 0] > 0.5
    return Image.fromarray((img.clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8)), m.cpu().numpy()


def def_tile(def_png, body_h):
    im = np.asarray(Image.open(def_png).convert("RGBA"))
    ys, xs = np.nonzero(im[..., 3] == 255)
    crop = Image.fromarray(im[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    s = body_h / crop.height
    crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.LANCZOS)
    if crop.width > TILE:
        s2 = TILE / crop.width
        crop = crop.resize((TILE, max(1, round(crop.height * s2))), Image.LANCZOS)
    a = np.asarray(crop).astype(float)
    al = a[..., 3:4] / 255.0
    al = np.where(al > 0.9, 1.0, al * 0.0)           # body only: HoMM3 shadow pixels (alpha < 255) are dropped
    rgb = a[..., :3] * al + BG * 255 * (1 - al)
    t = Image.new("RGB", (TILE, TILE), tuple((BG * 255).astype(int)))
    t.paste(Image.fromarray(rgb.astype(np.uint8)), ((TILE - crop.width) // 2, (TILE - crop.height) // 2))
    return t


def label(img, text):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 18], fill=(20, 20, 20))
    d.text((5, 2), text, fill=(235, 235, 235), font=font(13))
    return img


def row(r, dev):
    import finish as FN_
    geo = FN_.load_geometry(Path(r["glb"]), dev)
    A = FN_.load_png(Path(r["a"]), dev)
    B = FN_.load_png(Path(r["b"]), dev)
    tiles, body_h = [], None
    for nm, yaw, el in (("battle", FN_.OUR_YAW, FN_.ELEV), ("preview", PREVIEW_YAW, PREVIEW_ELEV)):
        ia, m = render(geo, A, yaw, el)
        ib, _ = render(geo, B, yaw, el)
        if nm == "battle":
            ys = np.nonzero(m.any(1))[0]
            body_h = int(ys.max() - ys.min() + 1)
        tiles += [(f"A {nm}", ia), (f"B {nm}", ib)]
    tiles.insert(0, ("HoMM3 DEF idle f0", def_tile(r["def"], body_h)))
    st = r.get("stats") or {}
    lines = [r["title"] + (f"   [{r['note']}]" if r.get("note") else "")]
    if "crushA" in st:
        lines.append(f"crush (pale raw -> L*<25) {st['crushA'] * 100:.1f}% -> {st['crushB'] * 100:.1f}%   pale raw -> L*<10 "
                     f"{st.get('blackA', 0) * 100:.1f}% -> {st.get('blackB', 0) * 100:.1f}%   dark share {st['darkA'] * 100:.1f}% -> "
                     f"{st['darkB'] * 100:.1f}%")
    if "finish" in st:
        f = st["finish"]
        lines.append(f"render body L* p5/p50/p95  DEF {f['DEF_body_L_p5_p50_p95']}  A {f['render_A_L_p5_p50_p95']}  "
                     f"B {f['render_B_L_p5_p50_p95']}   C50 DEF {f['DEF_body_C50']:.1f} A {f['render_A_C50']} B {f['render_B_C50']}")
        lines.append(f"grade k={f['grade_k']} g={f['grade_gamma']}{' (BOUND)' if f['grade_bound_hit'] else ''}  chroma x{f['chroma_scale']}  "
                     f"top-lit k={f['toplit_k']}  r(L,up) {f['r_L_up_A']:.2f}->{f['r_L_up_B']:.2f}  r(L,cav) "
                     f"{f['r_L_cavity_A']:.2f}->{f['r_L_cavity_B']:.2f}"
                     + ("  regions kept" if f.get("regionsProtected") else "") + ("  metal masked" if f.get("metalMasked") else ""))
    W = TILE * len(tiles)
    sheet = Image.new("RGB", (W, TILE + 8 + 18 * len(lines)), (24, 24, 24))
    for i, (t, im) in enumerate(tiles):
        sheet.paste(label(im.copy(), t), (i * TILE, 0))
    d = ImageDraw.Draw(sheet)
    for i, s in enumerate(lines):
        d.text((8, TILE + 4 + 18 * i), s, fill=(220, 220, 220), font=font(13))
    return sheet


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    a = ap.parse_args(argv)
    dev = FN.device(a.device)
    rows = json.loads(Path(a.rows).read_text())
    ims = []
    for r in rows:
        im = row(r, dev)
        im.save(Path(a.out).with_name(Path(a.out).stem + f"_{r['key']}.png"))
        ims.append(im)
    W = max(i.width for i in ims)
    sheet = Image.new("RGB", (W, sum(i.height + 6 for i in ims)), (12, 12, 12))
    y = 0
    for i in ims:
        sheet.paste(i, (0, y))
        y += i.height + 6
    sheet.save(a.out)
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
