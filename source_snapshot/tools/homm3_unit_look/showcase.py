"""Showcase MP4s of the prebaked lighting: HoMM3 DEF | raw Meshy colour | prebaked look.

    python tools/homm3_unit_look/showcase.py <unit> [<unit> ...] [--cond sand] [--rerender]

Writes artifacts/homm3_unit_look/_showcase/<unit>/:
  <unit>_clips.mp4      every DEF frame of every built clip, sprite camera, three panels, 10 fps
  <unit>_turntable.mp4  raw | look, the unit turning 360 degrees in place under a fixed arena sun
  <unit>_showcase.mp4   the two joined (clips twice, then the turntable)
1920x1080, 30 fps, H.264. Both mesh panels use the Hex/Lit relight (showcase_render.py); the DEF
panel is the original sprite, nearest-neighbour scaled to the same size. One crop (the union of every
frame of every panel) holds for the whole reel, so the scale never changes between frames.
Effects: a uvAtlas layer (the oceanid's water flow) swaps the look's base colour per key, in the
clips and under the turntable's idle; billboard/groundPlane defFlipbook cells are pinned at their anchor
bone's projected head/tail as the unit-look review does; dynamic effectLights (the Titan's strike and
bolt flashes) light the mesh on their keys with Hex/Lit's point term. Depth-aware parts (unitPlane/trail)
are not drawn here, and the subtitle says so when a unit has them.
Proof tier: generated artifact (Blender Eevee render + 2D composite), not an in-game capture.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import look as L  # noqa: E402
import spec as S  # noqa: E402

OUT = L.ROOT / "artifacts/homm3_unit_look/_showcase"
W, H, FPS, SRC_FPS = 1920, 1080, 30, 10
BODY_REACH = 1.6  # crop extent cap, as a multiple of the body's own extent
BG_TOP, BG_BOT = (58, 62, 56), (30, 32, 30)


def font(size):
    for f in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def background():
    g = np.linspace(0, 1, H)[:, None, None]
    bg = np.array(BG_TOP) * (1 - g) + np.array(BG_BOT) * g
    return Image.fromarray(np.broadcast_to(bg, (H, W, 3)).astype(np.uint8))


def union_box(paths):
    box = None
    for p in paths:
        b = Image.open(p).getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def pad_box(box, frac, limit):
    w, h = box[2] - box[0], box[3] - box[1]
    p = int(max(w, h) * frac)
    return (max(0, box[0] - p), max(0, box[1] - p), min(limit[0], box[2] + p), min(limit[1], box[3] + p))


def fit(img, bw, bh, nearest=False):
    s = min(bw / img.width, bh / img.height)
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                      Image.NEAREST if nearest else Image.LANCZOS)


def panel_frame(title, panels, sub=None):
    """panels: [(label, RGBA image)] laid side by side, bottom-aligned, labelled."""
    im = background()
    d = ImageDraw.Draw(im)
    d.text((W // 2, 44), title, font=font(40), fill=(236, 230, 214), anchor="mm")
    if sub:
        d.text((W // 2, 88), sub, font=font(24), fill=(170, 170, 160), anchor="mm")
    n = len(panels)
    pw, top, bottom = W // n, 130, H - 80
    for i, (label, p) in enumerate(panels):
        x0 = i * pw + (pw - p.width) // 2
        y0 = bottom - p.height
        im.paste(p, (x0, y0), p)
        d.text((i * pw + pw // 2, H - 42), label, font=font(30), fill=(236, 230, 214), anchor="mm")
    return im


def encode(frames_dir: Path, out: Path):
    ff = shutil.which("ffmpeg")
    if not ff:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames_dir / "%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow", "-movflags", "+faststart",
                    str(out)], check=True)


def frame_keys(ms):
    """Blender frame -> (GLB clip name, key index) for every master frame (repeated segments included)."""
    out = {}
    for sg in ms["segments"]:
        for t in range(sg["globalStart"], sg["globalEnd"]):
            out[t + 1] = ("Unit_" + sg["contractSuffix"], t - sg["globalStart"])
    return out


def atlas_cells(manifest, vdir: Path, cdir: Path, keys):
    """Cut each uvAtlas cell to its own texture; map Blender frames to the cell shown on them."""
    per_frame = {}
    for lid, ly in manifest["layers"].items():
        if ly.get("type") != "uvAtlas":
            continue
        atlas = Image.open(vdir / ly["atlas"]).convert("RGB")
        aw, ah = atlas.size
        for t, (clip, ki) in keys.items():
            rows = ly["clips"].get(clip)
            if not rows or ki >= len(rows) or rows[ki]["cell"] < 0:
                continue
            c = rows[ki]["cell"]
            png = cdir / f"{lid}_{c}.png"
            if not png.is_file():
                sx, sy, ox, oy = ly["cellST"][c]  # Unity v-up
                box = (round(ox * aw), round((1 - oy - sy) * ah), round((ox + sx) * aw), round((1 - oy) * ah))
                cdir.mkdir(parents=True, exist_ok=True)
                atlas.crop(box).save(png)
            per_frame[t] = str(png)
    return per_frame


def effect_lights(manifest, keys):
    """Every dynamic effectLight as {rgb (sRGB), range, frames: {Blender frame: [positionWorld, intensity]}},
    lit on exactly the keys the unit-look review lights (intensity > 0 with a world position)."""
    out = []
    for lid, ly in manifest["layers"].items():
        if ly.get("type") != "effectLight":
            continue
        fr = {}
        for t, (clip, ki) in keys.items():
            rows = ly.get("clips", {}).get(clip)
            if rows and ki < len(rows) and rows[ki]["intensity"] > 0 and rows[ki].get("positionWorld") is not None:
                fr[str(t)] = [rows[ki]["positionWorld"], rows[ki]["intensity"]]
        out.append({"id": lid, "rgb": ly["rgb"], "range": ly["range"], "frames": fr})
    return out


def composite_flipbooks(manifest, vdir: Path, keys, anchors, lookf, outd: Path, scale):
    """Pin every billboard/groundPlane defFlipbook cell on the look's sprite renders (RGBA over)."""
    outd.mkdir(parents=True, exist_ok=True)
    cache, out = {}, []
    for p in lookf:
        t = int(p.stem.split("_")[1])
        clip, ki = keys.get(t, (None, 0))
        im = Image.open(p).convert("RGBA")
        for ly in manifest["layers"].values():
            fb = ly.get("clips", {}).get(clip) if ly.get("type") == "defFlipbook" else None
            if not fb or not fb.get("sheet") or fb.get("render") not in (None, "billboard", "groundPlane") \
                    or ki >= len(fb["keys"]) or fb["keys"][ki]["cell"] < 0:
                continue
            if fb["sheet"] not in cache:
                cache[fb["sheet"]] = Image.open(vdir / fb["sheet"]).convert("RGBA")
            sheet, sc = cache[fb["sheet"]], fb["texelsPerDefPx"]
            cw, ch = fb["cellPx"]
            r, c = divmod(fb["keys"][ki]["cell"], fb["tilesX"])
            cell = sheet.crop((c * cw * sc, r * ch * sc, (c + 1) * cw * sc, (r + 1) * ch * sc))
            cell = cell.resize((round(cw * scale), round(ch * scale)), Image.NEAREST)
            b = anchors["frames"][str(t)][fb["anchorBone"]]
            ax, ay = b["tailPx"] if fb.get("anchorPoint") == "tail" else b["headPx"]
            layer = Image.new("RGBA", im.size)
            layer.paste(cell, (round(ax * scale - cell.width / 2), round(ay * scale - cell.height / 2)))
            im = Image.alpha_composite(im, layer)
        im.save(outd / p.name)
        out.append(outd / p.name)
    return out


def run(unit, cond, rerender, title=None, preview=False):
    out = OUT / unit
    rend = out / "render"
    ms = S.master_sequence(unit)
    frames = ms["frames"]
    idle = [f["globalIndex"] + 1 for f in frames if "idle" in f["clipKey"]] or [1]
    look_png = S.out_dir(unit) / "basecolor.png"
    stamp = S.out_dir(unit) / "stamp.json"
    if not stamp.is_file() and not preview:
        raise SystemExit(f"{unit}: not applied (no stamp.json); the showcase shows delivered looks only "
                         "(--preview renders the unapplied look, labelled as such)")
    vdir = S.out_dir(unit) / "vfx"
    mpath = vdir / "vfx_manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {"layers": {}}
    keys = frame_keys(ms)
    cells = atlas_cells(manifest, vdir, rend / "cells", keys)
    cells_json = rend / "cells.json"
    cells_doc = json.dumps({"sprite": {str(t): p for t, p in cells.items()}, "turn": [cells.get(t) for t in idle],
                            "lights": effect_lights(manifest, keys)})
    stale = not cells_json.is_file() or cells_json.read_text(encoding="utf-8") != cells_doc
    if rerender or stale or not (rend / "look" / f"turn_{239:03d}.png").is_file() or not (rend / "anchors.json").is_file():
        rend.mkdir(parents=True, exist_ok=True)
        cells_json.write_text(cells_doc, encoding="utf-8")
        L.blender(unit, S.blend_path(unit), HERE / "showcase_render.py",
                  ["--out", str(rend), "--look", str(look_png), "--idle", ",".join(map(str, idle)), "--cond", cond,
                   "--cells", str(cells_json)],
                  out / "render.log", expect=["SHOWCASE_RENDER_OK"])
    rawf = sorted((rend / "raw").glob("sprite_*.png"))
    anchors = json.loads((rend / "anchors.json").read_text(encoding="utf-8"))
    scale = Image.open(rawf[0]).width / anchors["resolution"][0]
    lookf = composite_flipbooks(manifest, vdir, keys, anchors, [rend / "look" / p.name for p in rawf],
                                rend / "look_fx", scale)
    kinds = {ly.get("type") for ly in manifest["layers"].values()} - {"event"}
    missing = sorted({fb.get("render") for ly in manifest["layers"].values() if ly.get("type") == "defFlipbook"
                      for fb in ly.get("clips", {}).values() if fb.get("render") in ("unitPlane", "trail")})
    defs = [Image.open(f["sourcePng"]).convert("RGBA") for f in frames[:len(rawf)]]
    size = Image.open(rawf[0]).size
    # one crop for the whole reel (every frame of all three panels): a per-clip crop rescales at each clip change
    b = union_box(rawf + lookf)
    d = union_box([f["sourcePng"] for f in frames[:len(rawf)]])
    b = (min(b[0], d[0] * scale), min(b[1], d[1] * scale), max(b[2], d[2] * scale), max(b[3], d[3] * scale))
    # far-flung effects (a wide attack splash) would shrink the unit for the whole reel: the crop reaches at most
    # BODY_REACH times the body's own extent (every frame of the raw mesh), centred on it; beyond that effects clip
    body = union_box(rawf)
    b = list(b)
    for i in (0, 1):  # x, then y
        span, c = (body[i + 2] - body[i]) * BODY_REACH, (body[i] + body[i + 2]) / 2
        b[i], b[i + 2] = max(b[i], c - span / 2), min(b[i + 2], c + span / 2)
    b = pad_box(tuple(int(v) for v in b), 0.04, size)
    crop = (b, tuple(round(v / scale) for v in b))
    pw, ph = W // 3 - 30, H - 130 - 100
    name = title or unit.replace("h3_", "").replace("_", " ").title()
    raw_l = json.loads((S.out_dir(unit) / "metrics.json").read_text()).get("review", {}).get("summary", {})
    sub = (f"body L* histogram distance to the sprite: raw {raw_l.get('meanLhistBodyRaw', '?')} -> look "
           f"{raw_l.get('meanLhistBodyLook', '?')} (lower is closer)") if raw_l else None
    fx_note = ("lighting + effects" if kinds else "lighting only (no effect layers)") + \
        (f"; not drawn: {', '.join(missing)}" if missing else "")
    sub = f"{sub}; {fx_note}" if sub else fx_note
    if not stamp.is_file():
        name += "  (preview: look not delivered)"

    clips_dir = out / "_frames_clips"; shutil.rmtree(clips_dir, ignore_errors=True); clips_dir.mkdir(parents=True)
    k = 0
    for i, (rp, lp) in enumerate(zip(rawf, lookf)):
        clip = frames[i]["clipKey"].split("_", 1)[-1]
        box, dboxs = crop
        panels = [("HoMM3 sprite", fit(defs[i].crop(dboxs), pw, ph, nearest=True)),
                  ("Meshy mesh, raw colour", fit(Image.open(rp).crop(box), pw, ph)),
                  ("Prebaked lighting + effects" if kinds else "Prebaked lighting", fit(Image.open(lp).crop(box), pw, ph))]
        im = panel_frame(f"{name}  -  {clip}", panels, sub)
        for _ in range(FPS // SRC_FPS):
            im.save(clips_dir / f"{k:05d}.png"); k += 1
    encode(clips_dir, out / f"{unit}_clips.mp4")

    turn_dir = out / "_frames_turn"; shutil.rmtree(turn_dir, ignore_errors=True); turn_dir.mkdir(parents=True)
    rt = sorted((rend / "raw").glob("turn_*.png"))
    tbox = pad_box(union_box(rt + [rend / "look" / p.name for p in rt]), 0.03, Image.open(rt[0]).size)
    for i, p in enumerate(rt):
        panels = [("Meshy mesh, raw colour", fit(Image.open(p).crop(tbox), W // 2 - 40, ph)),
                  ("Prebaked lighting", fit(Image.open(rend / "look" / p.name).crop(tbox), W // 2 - 40, ph))]
        panel_frame(f"{name}  -  turning under a fixed arena sun", panels,
                    "the prebake reads the same from every facing").save(turn_dir / f"{i:05d}.png")
    encode(turn_dir, out / f"{unit}_turntable.mp4")

    lst = out / "_concat.txt"
    c = out / f"{unit}_clips.mp4"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in (c, c, out / f"{unit}_turntable.mp4")))
    ff = shutil.which("ffmpeg")
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(out / f"{unit}_showcase.mp4")], check=True)
    shutil.rmtree(clips_dir); shutil.rmtree(turn_dir); lst.unlink()
    print(f"SHOWCASE {unit}: {out / f'{unit}_showcase.mp4'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="+")
    ap.add_argument("--cond", default="sand", choices=["sand", "grass", "snow"])
    ap.add_argument("--rerender", action="store_true")
    ap.add_argument("--title", help="display name (one unit)")
    ap.add_argument("--preview", action="store_true", help="allow a unit whose look is not applied (title says so)")
    a = ap.parse_args()
    for u in a.units:
        run(u, a.cond, a.rerender, a.title, a.preview)


if __name__ == "__main__":
    main()
