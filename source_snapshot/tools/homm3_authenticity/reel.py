"""Before/after reel of a unit's full animation set, for posting when a unit finishes the authenticity pass.

    python tools/homm3_authenticity/reel.py <unit> --before <boards_dir> --after <boards_dir> [--out <reel.gif>]

Both board dirs come from board.py (they must carry the clip_<clip>.gif.json panel sidecars; re-run board.py on the
before GLB if they do not). Every clip plays in game order, short clips repeated so each shows for at least ~1.6 s:

    | DEF            | before (sprite) | after (sprite) |
    | <clip label>   | before (battle) | after (battle) |

Default out: <after>/../reel_<unit>.gif. Pure PIL; no GPU needed (cutting and pasting frames only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageSequence

ORDER = ("Unit_Idle", "Unit_Mouseover", "Unit_MoveStart", "Unit_Move", "Unit_MoveEnd", "Unit_AttackUp", "Unit_AttackFront",
         "Unit_AttackDown", "Unit_ShootUp", "Unit_ShootFront", "Unit_ShootDown", "Unit_Cast", "Unit_Hitted", "Unit_Defence",
         "Unit_Death")
MIN_SHOW_S = 1.6
CELL_H = 170
BG = (248, 248, 248)


def font(sz: int):
    try:
        return ImageFont.truetype("segoeui.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def clip_frames(d: Path, clip: str):
    side = json.loads((d / f"clip_{clip}.gif.json").read_text(encoding="utf-8"))
    im = Image.open(d / f"clip_{clip}.gif")
    fr = [f.convert("RGB") for f in ImageSequence.Iterator(im)]
    return side, fr


def cut(fr: Image.Image, box) -> Image.Image:
    x, y, w, h = box
    return fr.crop((x, y, x + w, y + h))


def fit(im: Image.Image, h: int) -> Image.Image:
    return im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit"); ap.add_argument("--before", required=True); ap.add_argument("--after", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    bdir, adir = Path(a.before), Path(a.after)
    out = Path(a.out) if a.out else adir.parent / f"reel_{a.unit}.gif"
    clips = [c for c in ORDER if (adir / f"clip_{c}.gif").exists()]
    extra = sorted(p.name[5:-4] for p in adir.glob("clip_*.gif") if p.name[5:-4] not in ORDER)
    clips += extra
    missing = [c for c in clips if not (bdir / f"clip_{c}.gif.json").exists() or not (adir / f"clip_{c}.gif.json").exists()]
    if missing:
        sys.exit(f"panel sidecars missing for {missing}: re-run board.py into those dirs")
    f_hdr, f_lbl = font(15), font(12)
    frames, fps = [], None
    for clip in clips:
        sb, fb = clip_frames(bdir, clip)
        sa, fa = clip_frames(adir, clip)
        fps = fps or sa["fps"]
        n = max(len(fa), len(fb))
        reps = max(1, -(-round(MIN_SHOW_S * fps) // n))
        for r in range(reps):
            for k in range(n):
                A = fa[min(k, len(fa) - 1)]; B = fb[min(k, len(fb) - 1)]
                top = [fit(cut(A, sa["def"]), CELL_H), fit(cut(B, sb["sprite"]), CELL_H), fit(cut(A, sa["sprite"]), CELL_H)]
                bot = [None, fit(cut(B, sb["battle"]), CELL_H), fit(cut(A, sa["battle"]), CELL_H)]
                cw = [max(top[i].width, bot[i].width if bot[i] else 0) for i in range(3)]
                W = sum(cw) + 4 * 6; H = 24 + 2 * (CELL_H + 18)
                fr = Image.new("RGB", (W, H), BG)
                dr = ImageDraw.Draw(fr)
                dr.text((6, 3), f"{a.unit}   {clip.replace('Unit_', '')}", fill=(0, 0, 0), font=f_hdr)
                x = 6
                for i, lbl in enumerate(("HoMM3 DEF", "before", "after")):
                    dr.text((x, 24), lbl, fill=(0, 0, 0), font=f_lbl)
                    fr.paste(top[i], (x, 40))
                    if bot[i] is not None:
                        dr.text((x, 42 + CELL_H), f"{lbl} (battle view)", fill=(0, 0, 0), font=f_lbl)
                        fr.paste(bot[i], (x, 58 + CELL_H))
                    x += cw[i] + 6
                frames.append(fr)
    W = max(f.width for f in frames); H = max(f.height for f in frames)
    pal = []
    for f in frames:
        c = Image.new("RGB", (W, H), BG); c.paste(f, (0, 0))
        pal.append(c.quantize(colors=255, method=Image.Quantize.MEDIANCUT))
    out.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=int(round(1000 / fps)), loop=0, disposal=1, optimize=True)
    print(f"{out}  {len(pal)} frames  {W}x{H}  {out.stat().st_size / 1e6:.1f} MB  clips: {', '.join(clips)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
