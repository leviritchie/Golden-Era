"""Before/after sheet for depth-aware VFX: billboard vs unitPlane / trail on the four battle facings.

    python tools/homm3_unit_look/facing_proof.py h3_zealot [--layers cast_melee] [--keys 3] [--size 320]

Needs the unit's vfx stage output (vfx/vfx_manifest.json with unitPlane/trail layers) and the build .blend.
Renders the attack pose from each battle facing (facing_proof_blender.py, one Blender launch through
look.py's gpuslot), then composites per facing: BEFORE = the whole DEF cell as a view-facing billboard at the
anchor bone (what render "billboard" does), AFTER = the layer's own render (isotropic pieces billboarded,
directional pieces on the sagittal/cross cards in the unit's frame, or the ribbon trail).
Writes artifacts/homm3_unit_look/<unit>/facing_proof/facing_before_after.png and facing_proof.json.
Proof tier: generated artifact (offline render + CPU composite), not in-game.
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
sys.path.insert(0, str(HERE.parent / "homm3_prebake"))
import spec as S  # noqa: E402
import vfx_depth as VD  # noqa: E402

FACES = ["faces_right", "faces_left", "faces_camera", "faces_away"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--layers", default="")
    ap.add_argument("--keys", type=int, default=2, help="keys per layer clip (the ones with the most pixels)")
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--reuse", action="store_true", help="reuse the facing renders if present")
    a = ap.parse_args()
    import look as LK
    u = a.unit
    outd = S.out_dir(u)
    man = json.loads((outd / "vfx/vfx_manifest.json").read_text())
    front_axis = json.loads((outd / "metrics.json").read_text())["lighting"]["frontResolved"]["axis"]
    cam = json.loads((S.RETARGET / u / f"{u}_def_retarget.blend.spritecam.json").read_text())
    clips = S.clip_segments(u)
    want = [x for x in a.layers.split(",") if x]
    picks = []                                   # (layer id, clip, key index, master frame)
    for lid, L in man["layers"].items():
        if L.get("type") != "defFlipbook" or (want and lid not in want):
            continue
        for clip, fb in L["clips"].items():
            if fb.get("render") not in VD.RENDERS:
                continue
            px = fb.get("pixels", [])
            order = sorted(range(len(px)), key=lambda i: -px[i])[:a.keys]
            for ki in sorted(order):
                if px[ki] > 0:
                    picks.append((lid, clip, ki, clips[clip]["masterFrames"][ki]))
    if not picks:
        print("no unitPlane/trail layer keys in the manifest")
        return 2
    pd = outd / "facing_proof"
    frames = sorted({t + 1 for *_, t in picks})
    meta_p = pd / "facing_meta.json"
    if not (a.reuse and meta_p.is_file()):
        pd.mkdir(parents=True, exist_ok=True)
        LK.blender(u, S.blend_path(u), HERE / "facing_proof_blender.py",
                   ["--out", str(pd), "--frames", ",".join(map(str, frames)), f"--front={front_axis}", "--size", str(a.size)],
                   pd / "blender.log")
    meta = json.loads(meta_p.read_text())
    ctx = {"vmeta": {"front": meta["front"]}, "spritecam": cam}
    axes = VD.unit_axes(ctx)
    cv = VD.card_vectors(ctx)
    vdir = outd / "vfx"
    cache = {}
    rows, report = [], []
    for lid, clip, ki, t in picks:
        fb = man["layers"][lid]["clips"][clip]
        k = fb["keys"][ki]["cell"]
        for face in FACES:
            name = f"f{t + 1:03d}_{face}.png"
            im = meta["images"][name]
            mesh = np.asarray(Image.open(pd / name).convert("RGBA"), np.float32) / 255
            A, tt, err = VD.view_affine(im)
            ppu_view = float(np.linalg.norm(A, axis=1).mean())
            scale = ppu_view / cam["pxPerUnit"]
            bone = im["bones"][fb["anchorBone"]]
            anc_w = np.array(bone["tail"] if fb.get("anchorPoint") == "tail" else bone["head"])
            anc_px = A @ anc_w + tt
            shape = mesh.shape[:2]
            before, after = [], []
            wts = None
            if fb["render"] == "unitPlane":
                up = fb["unitPlane"]
                dis = up.get("displaced")
                dk = dis["keys"][ki] if dis else None
                dfb = {**fb, "cellPx": dis["cellPx"]} if dis else None
                wts = VD.card_weights(np.array(im["camForward"]), ctx, [up["fade"]["lo"], up["fade"]["hi"]])
                # BEFORE: every piece view-facing at the anchor, offsets kept in screen px (render "billboard")
                for s in (fb.get("sheet"), up.get("sheet")):
                    if s:
                        before.append((VD.paste_billboard(shape, VD.cell_of(fb, s, k, vdir, cache), anc_px, scale), 1.0))
                if dk:
                    dcell = VD.cell_of(dfb, dis["sheet"], k, vdir, cache)
                    before.append((VD.paste_billboard(shape, dcell, anc_px + np.array(dk["offsetPx"]) * scale, scale), 1.0))
                # AFTER: isotropic view-facing; displaced view-facing at the unit-frame offset; elongated on the cards
                if fb.get("sheet"):
                    after.append((VD.paste_billboard(shape, VD.cell_of(fb, fb["sheet"], k, vdir, cache), anc_px, scale), 1.0))
                if dk:
                    off = sum(wts[n] * VD.from_local(dk["offset"][n], axes) for n in ("sagittal", "cross"))
                    after.append((VD.paste_billboard(shape, dcell, A @ (anc_w + off) + tt, scale), 1.0))
                if up.get("sheet"):
                    cell = VD.cell_of(fb, up["sheet"], k, vdir, cache)
                    for card in ("sagittal", "cross"):
                        if wts[card] > 0:
                            after.append((VD.warp_card(shape, cell, anc_w, cv[card][0], cv[card][1], A, tt), wts[card]))
            else:
                before.append((VD.paste_billboard(shape, VD.cell_of(fb, fb["sourceSheet"], k, vdir, cache), anc_px, scale), 1.0))
                after.append((VD.draw_trail(shape, fb, ki, A, tt, axes, vdir, cache), 1.0))
            tiles = []
            for layers in (before, after):
                rgb = mesh[..., :3] * mesh[..., 3:4] + np.array([0.24, 0.27, 0.22]) * (1 - mesh[..., 3:4])
                for lay, wgt in layers:
                    al = lay[..., 3:4] * wgt
                    rgb = rgb * (1 - al) + lay[..., :3] * al
                tiles.append(rgb)
            rows.append((f"{lid} {clip} key {ki} {face}" + (f" w_sag={wts['sagittal']:.2f}" if wts else ""), tiles))
            report.append({"layer": lid, "clip": clip, "key": ki, "facing": face, "affineErrPx": round(err, 4),
                           **({"weights": {c: round(v, 3) for c, v in wts.items()}} if wts else {})})
    sz = a.size
    img = Image.new("RGB", (2 * sz, 18 + len(rows) * (sz + 14)), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.text((4, 3), f"{u}: BEFORE billboard | AFTER {'/'.join(sorted({man['layers'][p[0]]['clips'][p[1]]['render'] for p in picks}))} "
                   "(battle facings; generated artifact)", fill=(235, 235, 235))
    for r, (lab, tiles) in enumerate(rows):
        y = 18 + r * (sz + 14)
        d.text((4, y), lab, fill=(220, 220, 220))
        for c, tile in enumerate(tiles):
            img.paste(Image.fromarray((np.clip(tile, 0, 1) * 255 + 0.5).astype(np.uint8)), (c * sz, y + 14))
    img.save(pd / "facing_before_after.png")
    (pd / "facing_proof.json").write_text(json.dumps({"proof": "generated artifact (offline render + CPU composite)",
                                                      "rows": report}, indent=1), encoding="utf-8")
    print(pd / "facing_before_after.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
