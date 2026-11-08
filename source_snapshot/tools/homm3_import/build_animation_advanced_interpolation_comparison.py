#!/usr/bin/env python3
"""Motion-aware animation comparisons (optical flow / block motion) for HoMM3 battle sprites."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_animation_advanced_interpolation_comparison"
BASIC_OUT = REPO_ROOT / "experiments/homm3_animation_interpolation_comparison"

GROUP_IDLE = 2
GROUP_ATTACK_FRONT = 12

UNITS = (
    ("h3_angel", "Castle Angel"),
    ("h3_hydra", "Fortress Hydra"),
    ("h3_vampire", "Necropolis Vampire"),
)

CLIPS = (
    ("idle", GROUP_IDLE, True),
    ("attack", GROUP_ATTACK_FRONT, False),
)

FPS = 12
FRAME_MS = int(1000 / FPS)


def load_manifest(unit_sid: str) -> tuple[Path, dict]:
    battle_dir = LAB_ROOT / unit_sid / "extracted_battle"
    json_files = sorted(p for p in battle_dir.glob("*.json") if p.name.lower() != "manifest.json")
    if not json_files:
        raise FileNotFoundError(battle_dir)
    manifest_path = json_files[0]
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8-sig"))


def group_frame_paths(manifest: dict, group_id: int) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) != group_id:
            continue
        return [str(f).strip() for f in (sequence.get("frames") or []) if str(f or "").strip()]
    return []


def load_group_frames(battle_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for rel in rel_paths:
        path = battle_dir / rel.replace("\\", "/")
        frames.append(Image.open(path).convert("RGBA"))
    return frames


def normalize_frames(frames: list[Image.Image]) -> list[Image.Image]:
    size = (max(f.width for f in frames), max(f.height for f in frames))
    out: list[Image.Image] = []
    for f in frames:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(f, ((size[0] - f.width) // 2, (size[1] - f.height) // 2), f)
        out.append(canvas)
    return out


def pil_to_bgra(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img, dtype=np.uint8)
    return arr[:, :, [2, 1, 0, 3]]


def bgra_to_pil(arr: np.ndarray) -> Image.Image:
    rgba = arr[:, :, [2, 1, 0, 3]]
    return Image.fromarray(rgba, "RGBA")


def flow_grayscale(bgra: np.ndarray) -> np.ndarray:
    alpha = bgra[:, :, 3].astype(np.float32) / 255.0
    rgb = bgra[:, :, :3].astype(np.float32)
    lum = (0.2126 * rgb[:, :, 2] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 0]) * alpha
    return np.clip(lum, 0, 255).astype(np.uint8)


def warp_bgra(bgra: np.ndarray, flow: np.ndarray, scale: float) -> np.ndarray:
    import cv2

    h, w = bgra.shape[:2]
    fx = flow[:, :, 0] * scale
    fy = flow[:, :, 1] * scale
    x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = x + fx
    map_y = y + fy
    return cv2.remap(
        bgra,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def blend_bgra(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    af = a.astype(np.float32)
    bf = b.astype(np.float32)
    out = af * (1.0 - t) + bf * t
    alpha = np.maximum(af[:, :, 3], bf[:, :, 3])
    out[:, :, 3] = np.clip(alpha, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def midpoint_flow_warp(a: Image.Image, b: Image.Image, flow_calc) -> Image.Image:
    import cv2

    a0 = pil_to_bgra(a)
    b0 = pil_to_bgra(b)
    g0 = flow_grayscale(a0)
    g1 = flow_grayscale(b0)
    flow_ab = flow_calc(g0, g1)
    flow_ba = flow_calc(g1, g0)
    wa = warp_bgra(a0, flow_ab, 0.5)
    wb = warp_bgra(b0, flow_ba, 0.5)
    mid = blend_bgra(wa, wb, 0.5)
    return bgra_to_pil(mid)


def make_dis_calc(preset: str):
    import cv2

    flag = cv2.DISOPTICAL_FLOW_PRESET_FAST
    if preset == "medium":
        flag = cv2.DISOPTICAL_FLOW_PRESET_MEDIUM
    dis = cv2.DISOpticalFlow_create(flag)

    def calc(g0: np.ndarray, g1: np.ndarray) -> np.ndarray:
        return dis.calc(g0, g1, None)

    return calc


def make_farneback_calc():
    import cv2

    def calc(g0: np.ndarray, g1: np.ndarray) -> np.ndarray:
        return cv2.calcOpticalFlowFarneback(
            g0, g1, None, 0.5, 3, 21, 3, 5, 1.2, 0
        )

    return calc


def _block_flow_field(a: Image.Image, b: Image.Image, cell: int = 24, search: int = 20) -> np.ndarray:
    a0 = np.asarray(a.convert("RGBA"), dtype=np.float32)
    b0 = np.asarray(b.convert("RGBA"), dtype=np.float32)
    h, w = a0.shape[:2]
    gh = max(1, h // cell)
    gw = max(1, w // cell)

    def block_sad(ax: int, ay: int, bx: int, by: int) -> float:
        ap = a0[ay : ay + cell, ax : ax + cell]
        bp = b0[by : by + cell, bx : bx + cell]
        if ap.shape != bp.shape:
            return 1e9
        return float(np.sum(np.abs(ap - bp)))

    vx = np.zeros((gh, gw), dtype=np.float32)
    vy = np.zeros((gh, gw), dtype=np.float32)
    for gy_i in range(gh):
        for gx_i in range(gw):
            ax = min(gx_i * cell, max(0, w - cell))
            ay = min(gy_i * cell, max(0, h - cell))
            best = 1e9
            best_dx, best_dy = 0, 0
            for dy in range(-search, search + 1, 4):
                for dx in range(-search, search + 1, 4):
                    bx = int(np.clip(ax + dx, 0, max(0, w - cell)))
                    by = int(np.clip(ay + dy, 0, max(0, h - cell)))
                    sad = block_sad(ax, ay, bx, by)
                    if sad < best:
                        best = sad
                        best_dx, best_dy = dx, dy
            vx[gy_i, gx_i] = best_dx
            vy[gy_i, gx_i] = best_dy

    import cv2

    vx_up = cv2.resize(vx, (w, h), interpolation=cv2.INTER_LINEAR)
    vy_up = cv2.resize(vy, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.dstack([vx_up, vy_up])


def numpy_block_motion_midpoint(a: Image.Image, b: Image.Image, cell: int = 24, search: int = 20) -> Image.Image:
    flow_ab = _block_flow_field(a, b, cell, search)
    flow_ba = _block_flow_field(b, a, cell, search)
    a_bgra = pil_to_bgra(a)
    b_bgra = pil_to_bgra(b)
    wa = warp_bgra(a_bgra, flow_ab, 0.5)
    wb = warp_bgra(b_bgra, flow_ba, 0.5)
    return bgra_to_pil(blend_bgra(wa, wb, 0.5))


def expand_with_midpoints(
    frames: list[Image.Image],
    loop: bool,
    midpoint_fn,
    extra_ts: tuple[float, ...] = (),
) -> list[Image.Image]:
    if len(frames) < 2:
        return list(frames)
    out: list[Image.Image] = []
    n = len(frames)
    for i in range(n):
        out.append(frames[i])
        nxt = frames[(i + 1) % n] if loop else (frames[i + 1] if i + 1 < n else None)
        if nxt is None:
            continue
        out.append(midpoint_fn(frames[i], nxt))
        for t in extra_ts:
            if t == 0.5:
                continue
            # approximate intermediate via flow methods only at 0.5 for now
    return out


def expand_flow_quartiles(
    frames: list[Image.Image], loop: bool, flow_calc
) -> list[Image.Image]:
    import cv2

    if len(frames) < 2:
        return list(frames)
    out: list[Image.Image] = []
    n = len(frames)
    for i in range(n):
        out.append(frames[i])
        nxt = frames[(i + 1) % n] if loop else (frames[i + 1] if i + 1 < n else None)
        if nxt is None:
            continue
        a0 = pil_to_bgra(frames[i])
        b0 = pil_to_bgra(nxt)
        g0 = flow_grayscale(a0)
        g1 = flow_grayscale(b0)
        flow_ab = flow_calc(g0, g1)
        flow_ba = flow_calc(g1, g0)
        for t in (0.25, 0.5, 0.75):
            wa = warp_bgra(a0, flow_ab, t)
            wb = warp_bgra(b0, flow_ba, 1.0 - t)
            out.append(bgra_to_pil(blend_bgra(wa, wb, 0.5)))
    return out


def match_duration(frames: list[Image.Image], baseline_count: int) -> int:
    if not frames:
        return FRAME_MS
    return max(20, (baseline_count * FRAME_MS) // len(frames))


def write_gif(path: Path, frames: list[Image.Image], duration_ms: int, loop: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for f in frames]
    pal[0].save(
        path,
        save_all=True,
        append_images=pal[1:],
        duration=duration_ms,
        loop=0 if loop else 1,
        disposal=2,
        optimize=False,
    )


def try_ffmpeg_mci(in_gif: Path, out_gif: Path, fps: int = 24) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    filt = f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(in_gif),
        "-vf",
        filt,
        "-gifflags",
        "-transdiff",
        str(out_gif),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return out_gif.is_file()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def write_index(out_dir: Path) -> None:
    basic = "../homm3_animation_interpolation_comparison/index.html"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HoMM3 advanced animation comparison</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:1.5rem}}
h1,h2,h3{{color:#fff}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #333;padding:.5rem;vertical-align:top}}
th{{background:#222}}
img{{max-width:360px;background:#000;border:1px solid #444}}
.note{{color:#aaa;font-size:.9rem;max-width:720px;line-height:1.45}}
a{{color:#9cf}}
</style></head><body>
<h1>HoMM3 advanced animation comparison</h1>
<p class="note">Motion-aware methods: optical-flow warping (OpenCV DIS / Farneback) and coarse block-matching.
Simple alpha crossfades are in the <a href="{basic}">basic comparison</a>.</p>
<p class="note"><strong>Requires:</strong> <code>pip install opencv-python-headless numpy pillow</code>.
Optional <code>ffmpeg</code> enables method 05 (motion-compensated interpolation).</p>
"""
    for unit_sid, display in UNITS:
        html += f"<h2>{display} (<code>{unit_sid}</code>)</h2>"
        for clip_name, _, _ in CLIPS:
            html += f"<h3>{clip_name}</h3><table><tr><th>Method</th><th>Preview</th></tr>"
            clip_dir = out_dir / unit_sid / clip_name
            if not clip_dir.is_dir():
                continue
            for gif in sorted(clip_dir.glob("*.gif")):
                rel = gif.relative_to(out_dir).as_posix()
                txt = gif.with_suffix(".txt")
                label = txt.read_text(encoding="utf-8") if txt.is_file() else gif.stem
                html += (
                    f"<tr><td><strong>{gif.stem}</strong><br>{label}</td>"
                    f"<td><img src='{rel}' loading='lazy'></td></tr>"
                )
            html += "</table>"
    html += "</body></html>"
    (out_dir / "index.html").write_text(html, encoding="utf-8")


ADVANCED_METHODS: list[tuple[str, str]] = []


def register_methods() -> None:
    global ADVANCED_METHODS
    ADVANCED_METHODS = [
        ("01_baseline_12fps", "Reference: shipped discrete frames @ 12 FPS"),
    ]
    try:
        import cv2  # noqa: F401

        ADVANCED_METHODS.extend(
            [
                (
                    "02_opencv_dis_midpoint",
                    "OpenCV DIS optical flow: warp both frames to midpoint (50%), 12 FPS per frame",
                ),
                (
                    "03_opencv_dis_same_duration",
                    "DIS midpoint inserts; timing compressed to match baseline loop length",
                ),
                (
                    "04_opencv_dis_quartiles",
                    "DIS warped frames at 25/50/75% between each key pair",
                ),
                (
                    "05_opencv_farneback_midpoint",
                    "Farneback dense flow midpoint warp (often softer, more smear on attacks)",
                ),
            ]
        )
    except ImportError:
        pass
    ADVANCED_METHODS.append(
        (
            "06_numpy_block_motion_midpoint",
            "Coarse block-matching motion (no ML): 24px cells, midpoint warp",
        )
    )
    if shutil.which("ffmpeg"):
        ADVANCED_METHODS.append(
            (
                "07_ffmpeg_mci_24fps",
                "FFmpeg minterpolate motion-compensated interpolation on baseline GIF (24 FPS)",
            )
        )


def process_unit(unit_sid: str, out_dir: Path) -> None:
    manifest_path, manifest = load_manifest(unit_sid)
    battle_dir = manifest_path.parent
    for clip_name, group_id, loop in CLIPS:
        rel = group_frame_paths(manifest, group_id)
        if not rel:
            continue
        frames = normalize_frames(load_group_frames(battle_dir, rel))
        clip_out = out_dir / unit_sid / clip_name
        baseline_gif = clip_out / "01_baseline_12fps.gif"

        write_gif(baseline_gif, frames, FRAME_MS, loop)
        (clip_out / "01_baseline_12fps.txt").write_text(
            "Reference: shipped discrete frames @ 12 FPS", encoding="utf-8"
        )

        try:
            import cv2  # noqa: F401

            dis = make_dis_calc("fast")
            dis_mid = lambda a, b: midpoint_flow_warp(a, b, dis)

            seq = expand_with_midpoints(frames, loop, dis_mid)
            write_gif(clip_out / "02_opencv_dis_midpoint.gif", seq, FRAME_MS, loop)
            (clip_out / "02_opencv_dis_midpoint.txt").write_text(
                ADVANCED_METHODS[1][1], encoding="utf-8"
            )

            seq = expand_with_midpoints(frames, loop, dis_mid)
            write_gif(
                clip_out / "03_opencv_dis_same_duration.gif",
                seq,
                match_duration(seq, len(frames)),
                loop,
            )
            (clip_out / "03_opencv_dis_same_duration.txt").write_text(
                ADVANCED_METHODS[2][1], encoding="utf-8"
            )

            seq = expand_flow_quartiles(frames, loop, dis)
            write_gif(clip_out / "04_opencv_dis_quartiles.gif", seq, FRAME_MS, loop)
            (clip_out / "04_opencv_dis_quartiles.txt").write_text(
                ADVANCED_METHODS[3][1], encoding="utf-8"
            )

            fb = make_farneback_calc()
            seq = expand_with_midpoints(frames, loop, lambda a, b: midpoint_flow_warp(a, b, fb))
            write_gif(clip_out / "05_opencv_farneback_midpoint.gif", seq, FRAME_MS, loop)
            (clip_out / "05_opencv_farneback_midpoint.txt").write_text(
                ADVANCED_METHODS[4][1], encoding="utf-8"
            )
        except ImportError:
            pass

        seq = expand_with_midpoints(frames, loop, numpy_block_motion_midpoint)
        write_gif(clip_out / "06_numpy_block_motion_midpoint.gif", seq, FRAME_MS, loop)
        (clip_out / "06_numpy_block_motion_midpoint.txt").write_text(
            "Coarse block-matching motion (no ML): 24px cells, midpoint warp",
            encoding="utf-8",
        )

        if shutil.which("ffmpeg") and try_ffmpeg_mci(
            baseline_gif, clip_out / "07_ffmpeg_mci_24fps.gif", fps=24
        ):
            (clip_out / "07_ffmpeg_mci_24fps.txt").write_text(
                "FFmpeg minterpolate MCI on baseline GIF @ 24 FPS",
                encoding="utf-8",
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out_dir = Path(os.path.abspath(args.out))
    out_dir.mkdir(parents=True, exist_ok=True)
    register_methods()

    readme = """# HoMM3 advanced animation comparison

Open **index.html** in a browser.

## Methods in this pack

- **OpenCV DIS / Farneback**: estimate motion between frames, warp both sprites toward a midpoint or quartile times (not alpha dissolve).
- **Block motion (numpy)**: coarse block SAD matching; lighter weight, no GPU.
- **FFmpeg MCI** (optional): `minterpolate` motion-compensated frame synthesis if `ffmpeg` is on PATH.

## Still more advanced (not automated here)

- **RIFE / FILM / GMFSS** neural frame interpolation (best chance on large motion; needs GPU tool).
- **EBSynth**-style patch propagation for consistent pixel-art in-betweens.
- **Hand-drawn in-betweens** or **mesh rig** in Aseprite/Spine (highest quality).
- **Wire unused DEF groups** into clips (see basic pack `09_attack_all_melee_directions`).

Regenerate:

```bash
pip install opencv-python-headless numpy pillow
python tools/homm3_import/build_animation_advanced_interpolation_comparison.py
```
"""
    for unit_sid, _ in UNITS:
        print(f"Processing {unit_sid}...")
        process_unit(unit_sid, out_dir)

    write_index(out_dir)
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Wrote {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
