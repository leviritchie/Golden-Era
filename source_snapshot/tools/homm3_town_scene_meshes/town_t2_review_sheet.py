#!/usr/bin/env python3
"""Full-3D T2 towns: painting | before | after review sheets for one candidate against the installed one.

    TOWN_FULL3D_FACTION=<town> TOWN_FULL3D_CANDIDATE=<cand> python town_t2_review_sheet.py --before <installed cand>

Rows: the rest frame (pan_default) and every vanilla proof pose (cursor_left/right, sweep_left/right/high), then the
effects frames (full3d_full_t0..t2) before and after, and a per-effect motion row: the after candidate's
|t1 - t0| + |t2 - t1| heat (what the editor render animates). Column 1 is the HoMM3 town painting (full state, x1.8
top-left, black = no HoMM3 art) at rest and blank at the poses (HoMM3 has no pan). Writes <candidate>/review_t2/
(sheet PNGs + manifest with sha256). Proof tier: generated artifact (editor renders).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402

POSES = ("default", "cursor_left", "cursor_right", "sweep_left", "sweep_right", "sweep_high")


def lab(img: Image.Image, text: str) -> Image.Image:
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, min(img.width, 14 + 7 * len(text)), 22), fill=(0, 0, 0))
    d.text((6, 5), text, fill=(255, 255, 255))
    return img


def row(imgs, h=400):
    imgs = [i.resize((round(i.width * h / i.height), h), Image.LANCZOS) for i in imgs]
    out = Image.new("RGB", (sum(i.width for i in imgs) + 8 * (len(imgs) - 1), h), (40, 40, 40))
    x = 0
    for i in imgs:
        out.paste(i, (x, 0))
        x += i.width + 8
    return out


def col(rows):
    w = max(r.width for r in rows)
    out = Image.new("RGB", (w, sum(r.height for r in rows) + 8 * (len(rows) - 1)), (40, 40, 40))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + 8
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    before = SC.DATA / "candidates" / a.before / "renders"
    after = S.RENDERS
    out = S.CAND / "review_t2"
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.png"):
        p.unlink()
    ref = S.homm3_reference(SC.FP.STATES["full"])
    blank = Image.new("RGB", ref.size, (0, 0, 0))

    def r(d, n):
        p = d / n
        if not p.is_file():
            raise SystemExit(f"review: {p} missing")
        return Image.open(p)

    sheets = {}
    rows = []
    for pose in POSES:
        rows.append(row([lab(ref if pose == "default" else blank,
                             "HoMM3 painting (full)" if pose == "default" else f"{pose}: HoMM3 has no pan"),
                         lab(r(before, f"pan_{pose}.png"), f"before ({a.before}) {pose}"),
                         lab(r(after, f"pan_{pose}.png"), f"after ({S.CANDIDATE}) {pose}")]))
    sheets["01_painting_before_after_poses.png"] = col(rows)
    fx = []
    for tag, d in (("before", before), ("after", after)):
        fx.append(row([lab(r(d, f"full3d_full_t{i}.png"), f"{tag} effects t{i}") for i in range(3)], h=360))
    f = [np.asarray(r(after, f"full3d_full_t{i}.png").convert("RGB"), np.float32) for i in range(3)]
    fb = [np.asarray(r(before, f"full3d_full_t{i}.png").convert("RGB"), np.float32) for i in range(3)]
    heat = lambda fr: Image.fromarray(np.clip((np.abs(fr[1] - fr[0]) + np.abs(fr[2] - fr[1])).max(-1) * 3, 0, 255)
                                      .astype(np.uint8)).convert("RGB")
    fx.append(row([lab(heat(fb), "before: motion heat |t1-t0|+|t2-t1| x3"),
                   lab(heat(f), "after: motion heat |t1-t0|+|t2-t1| x3"), lab(ref, "HoMM3 painting (full)")], h=360))
    sheets["02_effects_before_after.png"] = col(fx)
    man = {}
    for name, img in sheets.items():
        img.save(out / name)
        man[name] = {"sha256": hashlib.sha256((out / name).read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps({"faction": SC.FACTION, "before": a.before, "after": S.CANDIDATE,
                                                   "proofTier": "generated artifact (editor renders; not in-game)",
                                                   "files": man}, indent=1), encoding="utf-8")
    print(json.dumps({k: v["sha256"][:12] for k, v in man.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
