"""Characterise the HoMM3 storm-elemental effect DEFs: contact sheets + palette/timing stats.

Output: artifacts/homm3_vfx_experiments/storm_elemental/evidence/
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import h3def  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/homm3_vfx_experiments/storm_elemental/evidence"
BG = (72, 88, 64)  # neutral grass-ish battlefield tone so both shadow and glow read
DEFS = {
    "cstorm.def": "storm elemental battle unit",
    "cprgtix.def": "missile (shared with Titan)",
    "c03spa0.def": "lightning bolt spell: bolt column",
    "c11spa1.def": "lightning bolt spell: impact flash",
    "c11spe0.def": "protection from air (storm elemental's cast)",
    "c01spa0.def": "air shield spell",
}


def comp(frame, pal, scale=1):
    rgba = h3def.to_rgba(frame, pal)
    bg = Image.new("RGBA", rgba.shape[1::-1], BG + (255,))
    im = Image.alpha_composite(bg, Image.fromarray(rgba, "RGBA")).convert("RGB")
    return im.resize((im.width * scale, im.height * scale), Image.NEAREST) if scale != 1 else im


def bbox(frames):
    ys, xs = [], []
    for f in frames:
        yy, xx = np.nonzero(f.idx > 7)
        if len(xx):
            ys += [yy.min(), yy.max()]
            xs += [xx.min(), xx.max()]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None


def sheet(frames, pal, title, scale=2, pad=4):
    b = bbox(frames)
    x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
    tiles = [comp(f, pal).crop((x0, y0, x1, y1)) for f in frames]
    tw, th = tiles[0].width * scale, tiles[0].height * scale
    cols = min(len(tiles), 12)
    rows = (len(tiles) + cols - 1) // cols
    im = Image.new("RGB", (cols * tw, rows * (th + 12) + 14), (20, 20, 20))
    dr = ImageDraw.Draw(im)
    dr.text((2, 1), title, fill=(230, 230, 230))
    for i, t in enumerate(tiles):
        x, y = (i % cols) * tw, 14 + (i // cols) * (th + 12)
        im.paste(t.resize((tw, th), Image.NEAREST), (x, y))
        dr.text((x + 2, y + th), str(i), fill=(200, 200, 200))
    return im


def palette_stats(d):
    used = np.zeros(256, np.int64)
    for fs in d.groups.values():
        for f in fs:
            used += np.bincount(f.idx.ravel(), minlength=256)
    pal = d.palette.astype(float)
    lum = pal @ [0.299, 0.587, 0.114]
    nz = [i for i in range(8, 256) if used[i]]
    # colour-family summary of used non-special indices, weighted by pixel count
    rows = []
    for i in nz:
        r, g, b = d.palette[i]
        rows.append({"i": i, "rgb": [int(r), int(g), int(b)], "px": int(used[i]), "lum": round(float(lum[i]), 1)})
    special = {h3def.SPECIAL[i]: int(used[i]) for i in range(1, 8) if used[i]}
    return {"usedIndices": len(nz), "special": special, "rows": rows}


def swatch(d, stats, title):
    rows = sorted(stats["rows"], key=lambda r: -r["px"])
    im = Image.new("RGB", (16 * 16, 16 * 16 + 14), (20, 20, 20))
    dr = ImageDraw.Draw(im)
    dr.text((2, 1), title, fill=(230, 230, 230))
    used = {r["i"] for r in rows}
    for i in range(256):
        x, y = (i % 16) * 16, 14 + (i // 16) * 16
        dr.rectangle((x, y, x + 15, y + 15), fill=tuple(int(c) for c in d.palette[i]))
        if i not in used and i > 7:
            dr.line((x, y, x + 15, y + 15), fill=(0, 0, 0))
    return im


def main():
    global OUT, DEFS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit-def", default="cstorm.def")
    ap.add_argument("--extra", nargs="*", default=None, help="extra effect DEFs (default: storm set)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    OUT = pathlib.Path(a.out)
    if a.unit_def != "cstorm.def" or a.extra is not None:
        DEFS = {a.unit_def: "battle unit"} | {n: "effect" for n in (a.extra or [])}
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, what in DEFS.items():
        d = h3def.read_def(name)
        stem = name[:-4]
        st = palette_stats(d)
        swatch(d, st, f"{stem} palette (x = unused)").save(OUT / f"{stem}_palette.png")
        groups = {}
        for g, fs in d.groups.items():
            b = bbox(fs)
            groups[g] = {"frames": len(fs), "bbox": [int(v) for v in b] if b else None,
                         "bboxSize": [int(b[2] - b[0]), int(b[3] - b[1])] if b else None,
                         "names": [f.name for f in fs]}
        report[stem] = {"what": what, "defType": hex(d.typ), "canvas": list(d.size), "groups": groups,
                        "palette": {k: v for k, v in st.items() if k != "rows"},
                        "topColours": sorted(st["rows"], key=lambda r: -r["px"])[:24]}
        if d.typ == 0x42:
            for g, fs in d.groups.items():
                sheet(fs, d.palette, f"{stem.upper()} group {g}", scale=2).save(OUT / f"{stem}_g{g:02d}.png")
        else:
            sheet(d.groups[0], d.palette, f"{stem.upper()} ({what})", scale=2).save(OUT / f"{stem}_sheet.png")
    (OUT / "def_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: {kk: v[kk] for kk in ("defType", "canvas", "palette")} | {"groups": {g: (x["frames"], x["bboxSize"]) for g, x in v["groups"].items()}} for k, v in report.items()}, indent=0))


if __name__ == "__main__":
    main()
