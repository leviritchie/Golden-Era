"""High-resolution stretch review of emphasised clips, before vs after (shared review.py, unmodified).

  python tools/homm3_def_retarget_emphasis/hires_review.py <unit> [<unit> ...] [--res 640]

For each unit with an emphasised stamp, review.py renders the pre-emphasis snapshot
(<u>/source/pre_emphasis.blend) and the installed canonical .blend on temporary copies. review.py
picks the four worst-stretch frames from the stretch.json beside the .blend; here that file is the
real per-frame stretch with the emphasised clips' worst frames ranked first, so both renders show
the same frames: where the pass adds stretch. Writes <u>/hires/pair_<frame>.png (rows: before,
after; textured, stretched faces tinted) and removes the temporary copies. One Blender at a time,
memgate before each.
"""
import json, os, shutil, subprocess, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emphasis as E  # noqa: E402
import deliver as D  # noqa: E402


def frames_for(st, stretch):
    fr = []
    for c, v in st["clips"].items():
        if v.get("emphasised"):
            a, b = v["range"]
            fr.append(max(range(a, b), key=lambda i: stretch[i][2]))
    return sorted(set(fr))[:4]


def render(u, blend, stretch, pick, out, res):
    tmp = f"{out}/_tmp_{os.path.basename(out)}"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    shutil.copy2(blend, f"{tmp}/r.blend"); shutil.copy2(blend + ".frames.json", f"{tmp}/r.blend.frames.json")
    biased = [list(s) for s in stretch]
    for i in pick:
        biased[i][2] = 10 ** 9 - i
    json.dump(biased, open(f"{tmp}/stretch.json", "w"))
    D.blender([f"{tmp}/r.blend", "-P", f"{E.ROOT}/tools/homm3_def_retarget/review.py", "--", f"{tmp}/r", str(res)])
    return tmp


def main():
    args = sys.argv[1:]; res = 640
    if "--res" in args:
        i = args.index("--res"); res = int(args[i + 1]); del args[i:i + 2]
    for u in args:
        W = D.wdir(u); st = json.load(open(f"{W}/stamp.json"))
        if st["decision"] != "emphasised":
            print(u, "not emphasised"); continue
        after = json.load(open(f"{E.SRC}/{u}/stretch.json")); before = json.load(open(f"{W}/source/stretch.json"))
        pick = frames_for(st, after)
        out = f"{W}/hires"; shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
        tb = render(u, f"{W}/source/pre_emphasis.blend", before, pick, out, res)
        ta = render(u, D.canon(u)["blend"], after, pick, out, res)
        for t in pick:
            ims = []
            for d in (tb, ta):
                a = Image.open(f"{d}/r_{t:03d}_0.png"); b = Image.open(f"{d}/r_{t:03d}_1.png")
                c = Image.new("RGB", (a.width * 2, a.height)); c.paste(a, (0, 0)); c.paste(b, (a.width, 0)); ims.append(c)
            w, h = ims[0].size
            s = Image.new("RGB", (w, h * 2 + 20), (20, 20, 20)); s.paste(ims[0], (0, 20)); s.paste(ims[1], (0, h + 20))
            clip = next(c for c, v in st["clips"].items() if v["range"][0] <= t < v["range"][1])
            ImageDraw.Draw(s).text((6, 4), f"{u} {clip} frame {t}: top before (max {before[t][0]:.1f}x, edges>2x {before[t][2]}), "
                                           f"bottom after emphasis (max {after[t][0]:.1f}x, edges>2x {after[t][2]})", fill=(255, 255, 255))
            ImageDraw.Draw(s).text((6, h + 22), "after emphasis", fill=(255, 200, 0))
            s.save(f"{out}/pair_{t:03d}.png")
        shutil.rmtree(tb, ignore_errors=True); shutil.rmtree(ta, ignore_errors=True)
        print("HIRES", out, pick)


if __name__ == "__main__":
    main()
