#!/usr/bin/env python3
"""
Diff attack animation frames for authoring feedback.

Writes:
  - source consecutive diffs (intended motion)
  - mesh consecutive diffs (actual motion)
  - per-frame mesh vs source overlay panels
  - tip trajectory CSV from painted keypoints (if provided)

Usage:
  python diff_attack_frames.py --src .../painted_g11 --mesh .../preview/frames \\
    --keypoints .../manual_keypoints/keypoints.json --out .../diffs
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _load_rgba(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    if size is not None and im.size != size:
        im = im.resize(size, Image.NEAREST if max(im.size) < 300 else Image.LANCZOS)
    return im


def _alpha_mask(im: Image.Image, thr: int = 8) -> np.ndarray:
    a = np.asarray(im.split()[-1])
    # also treat near-black as bg for sprites without alpha
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    lum = rgb.mean(axis=2)
    return (a > thr) & (lum > 12.0)


def _diff_rgb(a: Image.Image, b: Image.Image) -> Image.Image:
    aa = np.asarray(a.convert("RGB"), dtype=np.float32)
    bb = np.asarray(b.convert("RGB"), dtype=np.float32)
    d = np.clip(np.abs(aa - bb), 0, 255).astype(np.uint8)
    return Image.fromarray(d, "RGB")


def _overlay_err(src: Image.Image, mesh: Image.Image) -> tuple[Image.Image, dict]:
    """Red = source-only, green = mesh-only, yellow = overlap."""
    sm = _alpha_mask(src)
    mm = _alpha_mask(mesh)
    h, w = sm.shape
    panel = np.zeros((h, w, 3), dtype=np.uint8)
    panel[sm & ~mm] = (220, 40, 40)
    panel[mm & ~sm] = (40, 200, 60)
    panel[sm & mm] = (220, 200, 40)
    inter = float(np.count_nonzero(sm & mm))
    union = float(np.count_nonzero(sm | mm)) + 1e-8
    iou = inter / union
    return Image.fromarray(panel, "RGB"), {
        "iou": iou,
        "srcPix": int(np.count_nonzero(sm)),
        "meshPix": int(np.count_nonzero(mm)),
        "onlySrc": int(np.count_nonzero(sm & ~mm)),
        "onlyMesh": int(np.count_nonzero(mm & ~sm)),
    }


def _fit_cell(im: Image.Image, box: tuple[int, int], label: str) -> Image.Image:
    tw, th = box
    canvas = Image.new("RGB", (tw, th), (12, 12, 12))
    r = min(tw / im.size[0], (th - 18) / im.size[1])
    nw, nh = max(1, int(im.size[0] * r)), max(1, int(im.size[1] * r))
    resized = im.resize((nw, nh), Image.NEAREST if max(im.size) < 300 else Image.LANCZOS)
    if resized.mode == "RGBA":
        bg = Image.new("RGBA", resized.size, (0, 0, 0, 255))
        resized = Image.alpha_composite(bg, resized).convert("RGB")
    else:
        resized = resized.convert("RGB")
    canvas.paste(resized, ((tw - nw) // 2, 18 + (th - 18 - nh) // 2))
    d = ImageDraw.Draw(canvas)
    d.text((4, 2), label, fill=(255, 220, 80))
    return canvas


def _tip_from_keypoints(kpt_path: Path) -> list[dict]:
    data = json.loads(kpt_path.read_text(encoding="utf-8"))
    rows = []
    for fr in data.get("frames") or []:
        tip = (fr.get("joints") or {}).get("WeaponTip") or {}
        wrist = (fr.get("joints") or {}).get("RWrist") or {}
        rows.append(
            {
                "frame": int(fr.get("frameIndex", len(rows))),
                "tipX": float(tip.get("x", 0.0)),
                "tipY": float(tip.get("y", 0.0)),
                "wristX": float(wrist.get("x", 0.0)),
                "wristY": float(wrist.get("y", 0.0)),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="Dir with frame_XX.png sources")
    ap.add_argument("--mesh", type=Path, required=True, help="Dir with mesh_XX.png renders")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keypoints", type=Path, default=None)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--cell", type=int, default=180)
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    cell = int(args.cell)
    n = int(args.frames)

    srcs = [_load_rgba(args.src / f"frame_{i:02d}.png") for i in range(n)]
    # normalize source to common size (first frame)
    base = (max(s.size[0] for s in srcs), max(s.size[1] for s in srcs))
    srcs = [_load_rgba(args.src / f"frame_{i:02d}.png", base) for i in range(n)]
    meshes = [_load_rgba(args.mesh / f"mesh_{i:02d}.png", base) for i in range(n)]

    report = {"frames": [], "motion": []}

    # Consecutive source + mesh diffs
    src_diff_row = []
    mesh_diff_row = []
    for i in range(1, n):
        sd = _diff_rgb(srcs[i], srcs[i - 1])
        md = _diff_rgb(meshes[i], meshes[i - 1])
        sd.save(out / f"src_motion_{i-1:02d}_to_{i:02d}.png")
        md.save(out / f"mesh_motion_{i-1:02d}_to_{i:02d}.png")
        src_diff_row.append(_fit_cell(sd, (cell, cell), f"src {i-1}->{i}"))
        mesh_diff_row.append(_fit_cell(md, (cell, cell), f"mesh {i-1}->{i}"))
        # motion magnitude
        sa = np.asarray(sd, dtype=np.float32).mean()
        ma = np.asarray(md, dtype=np.float32).mean()
        report["motion"].append(
            {
                "from": i - 1,
                "to": i,
                "srcMotionMean": float(sa),
                "meshMotionMean": float(ma),
                "motionRatio": float(ma / (sa + 1e-6)),
            }
        )

    # Per-frame overlay error
    err_row = []
    trio_rows = []
    for i in range(n):
        ov, stats = _overlay_err(srcs[i], meshes[i])
        ov.save(out / f"overlay_err_{i:02d}.png")
        err_row.append(_fit_cell(ov, (cell, cell), f"err f{i} IoU={stats['iou']:.2f}"))
        trio = Image.new("RGB", (cell * 3, cell), (0, 0, 0))
        trio.paste(_fit_cell(srcs[i], (cell, cell), f"src f{i}"), (0, 0))
        trio.paste(_fit_cell(meshes[i], (cell, cell), f"mesh f{i}"), (cell, 0))
        trio.paste(_fit_cell(ov, (cell, cell), f"diff f{i}"), (cell * 2, 0))
        trio.save(out / f"trio_{i:02d}.png")
        trio_rows.append(trio)
        report["frames"].append({"frame": i, **stats})

    def _hstack(cells: list[Image.Image], path: Path) -> None:
        if not cells:
            return
        w = sum(c.size[0] for c in cells)
        h = max(c.size[1] for c in cells)
        strip = Image.new("RGB", (w, h), (0, 0, 0))
        x = 0
        for c in cells:
            strip.paste(c, (x, 0))
            x += c.size[0]
        strip.save(path)

    _hstack(src_diff_row, out / "strip_src_motion.png")
    _hstack(mesh_diff_row, out / "strip_mesh_motion.png")
    _hstack(err_row, out / "strip_overlay_err.png")

    # Full compare board: for each i, src|mesh|err and below motion from i-1
    board_h = cell * 2
    board_w = cell * 3 * n
    board = Image.new("RGB", (board_w, board_h + 8), (0, 0, 0))
    for i, trio in enumerate(trio_rows):
        board.paste(trio, (i * cell * 3, 0))
    for i, cell_im in enumerate(src_diff_row):
        board.paste(cell_im, ((i + 1) * cell * 3, cell))
        if i < len(mesh_diff_row):
            # small label strip already in cell; place mesh motion under middle
            board.paste(mesh_diff_row[i], ((i + 1) * cell * 3 + cell, cell))
    board.save(out / "board_frames_and_motion.png")

    tips = []
    if args.keypoints and args.keypoints.is_file():
        tips = _tip_from_keypoints(args.keypoints)
        with (out / "tip_trajectory.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["frame", "tipX", "tipY", "wristX", "wristY", "dTipX", "dTipY"])
            w.writeheader()
            prev = None
            for row in tips:
                dtx = 0.0 if prev is None else row["tipX"] - prev["tipX"]
                dty = 0.0 if prev is None else row["tipY"] - prev["tipY"]
                w.writerow({**row, "dTipX": dtx, "dTipY": dty})
                prev = row
        # tip path plot on black
        plot = Image.new("RGB", (512, 512), (0, 0, 0))
        d = ImageDraw.Draw(plot)
        pts = [(r["tipX"], r["tipY"]) for r in tips]
        if len(pts) >= 2:
            d.line(pts, fill=(80, 160, 255), width=3)
        for i, (x, y) in enumerate(pts):
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 200, 40))
            d.text((x + 6, y - 6), f"f{i}", fill=(255, 255, 255))
        plot.save(out / "tip_path_painted.png")
        report["tipTrajectory"] = tips

    (out / "diff_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "meanIoU": float(np.mean([f["iou"] for f in report["frames"]]))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
