"""Before/after review sheets for delivered emphasis units.

  python review_sheet.py <unit> [<unit> ...]     -> artifacts/homm3_def_retarget_emphasis/<u>/keys_sheet.png
  python review_sheet.py --roster [N]            -> artifacts/homm3_def_retarget_emphasis/roster_contact_sheet.png

One column per exaggerated key frame; rows: DEF | fit before | fit after (sprite camera, DEF outline
drawn over both fits) | side view before | side view after. "Before" is the pre-emphasis snapshot
(<u>/source/renders), "after" the pass's own renders of the changed clips (<u>/renders_after).
The roster sheet takes the N keys with the largest ratio change across every emphasised unit.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emphasis import OUT, SRC, frames_json  # noqa: E402

CELL = 200
ROWS = ["DEF", "fit before", "fit after", "side before", "side after"]


def rgba(p):
    return Image.open(p).convert("RGBA")


def crop_box(u, fj, ts):
    box = None
    for t in ts:
        for im in (rgba(fj["sources"][t]), rgba(f"{OUT}/{u}/source/renders/sprite_{t + 1:03d}.png"),
                   rgba(f"{OUT}/{u}/renders_after/sprite_{t + 1:03d}.png")):
            bb = im.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
            if bb:
                box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    w, h = box[2] - box[0], box[3] - box[1]; m = int(0.08 * max(w, h)) + 4
    cx, cy, s = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, max(w, h) // 2 + m
    return (cx - s, cy - s, cx + s, cy + s)


def outline(img):
    a = np.asarray(img.getchannel("A")) == 255
    e = a & ~(np.roll(a, 1, 0) & np.roll(a, -1, 0) & np.roll(a, 1, 1) & np.roll(a, -1, 1))
    o = np.zeros(a.shape + (4,), np.uint8); o[e] = (255, 230, 0, 255)
    return Image.fromarray(o)


def column(u, fj, t, box):
    d = rgba(fj["sources"][t]).crop(box); ol = outline(d); ims = [d]
    for p in (f"{OUT}/{u}/source/renders/sprite_{t + 1:03d}.png", f"{OUT}/{u}/renders_after/sprite_{t + 1:03d}.png"):
        im = rgba(p).crop(box); im.alpha_composite(ol); ims.append(im)
    ims += [rgba(f"{OUT}/{u}/source/renders/side_{t + 1:03d}.png"), rgba(f"{OUT}/{u}/renders_after/side_{t + 1:03d}.png")]
    cells = []
    for im in ims:
        c = Image.new("RGB", (CELL, CELL), (45, 45, 45)); im = im.resize((CELL, CELL), Image.LANCZOS)
        c.paste(im, (0, 0), im); cells.append(c)
    return cells


def unit_keys(u):
    st = json.load(open(f"{OUT}/{u}/stamp.json"))
    if st.get("decision") != "emphasised":
        return []
    fj = frames_json(f"{OUT}/{u}/source/pre_emphasis.blend")
    out = []
    for clip, c in st["clips"].items():
        if not c.get("emphasised"):
            continue
        a, b = c["range"]; box = crop_box(u, fj, range(a, b))
        fl = [k for k in c["keys"] if k["status"] == "underEmphasised"]
        for k, r1 in zip(fl, c["ratiosAfter"]):
            out.append({"unit": u, "clip": clip, "t": k["frame"], "r0": k["ratio"], "r1": r1, "box": box, "fj": fj,
                        "edges": c["edges2xWorstFrame"], "deg": c["maxExtraDeg"]})
    # ratiosAfter holds every key of the clip; realign by frame
    for o in out:
        c = st["clips"][o["clip"]]; idx = [k["frame"] for k in c["keys"]].index(o["t"])
        o["r1"] = c["ratiosAfter"][idx]
    return out


def sheet(cols, title, path):
    lw = 110
    s = Image.new("RGB", (lw + CELL * len(cols), 40 + CELL * len(ROWS)), (30, 30, 30))
    dr = ImageDraw.Draw(s); dr.text((6, 6), title, fill=(255, 255, 255))
    for r, name in enumerate(ROWS):
        dr.text((6, 40 + r * CELL + CELL // 2), name, fill=(220, 220, 220))
    for i, k in enumerate(cols):
        for r, c in enumerate(column(k["unit"], k["fj"], k["t"], k["box"])):
            s.paste(c, (lw + i * CELL, 40 + r * CELL))
        dr.text((lw + i * CELL + 4, 20), f"{k['unit'][:22]}", fill=(255, 255, 0))
        dr.text((lw + i * CELL + 4, 40 + 4), f"{k['clip'][:16]} f{k['t']}", fill=(255, 255, 0))
        dr.text((lw + i * CELL + 4, 40 + 16), f"r {k['r0']:.2f}->{k['r1']:.2f} +{k['deg']:.0f}deg", fill=(255, 200, 0))
        dr.text((lw + i * CELL + 4, 40 + 28), f"edges>2x {k['edges'][0]}->{k['edges'][1]}", fill=(255, 200, 0))
    s.save(path)
    print("SHEET", path)


def main():
    a = sys.argv[1:]
    if a and a[0] == "--roster":
        n = int(a[1]) if len(a) > 1 else 16
        ks = []
        for d in sorted(os.listdir(OUT)):
            if os.path.exists(f"{OUT}/{d}/stamp.json"):
                ks += unit_keys(d)
        ks.sort(key=lambda k: -(k["r1"] - k["r0"]))
        per_row = 8
        top = ks[:n]
        for i in range(0, len(top), per_row):
            sheet(top[i:i + per_row], f"Emphasis roster: largest ratio gains {i + 1}-{i + len(top[i:i + per_row])} of {len(ks)} "
                  "exaggerated keys (ratio = fit reach / DEF reach; before -> after)",
                  f"{OUT}/roster_contact_sheet_{i // per_row + 1}.png")
        return
    for u in a:
        ks = unit_keys(u)
        if ks:
            sheet(ks, f"{u}: exaggerated keys, DEF vs fit before/after emphasis", f"{OUT}/{u}/keys_sheet.png")


if __name__ == "__main__":
    main()
