#!/usr/bin/env python3
"""Upscaled texture sources for the full-3D town lane (texture-consistency experiment; local models only, no Meshy).

    python tools/homm3_town_scene_meshes/town_full3d_texsrc.py build --faction stronghold \
        --model esrgan-x4plus --mode unified --out <dir>
    python tools/homm3_town_scene_meshes/town_full3d_texsrc.py measure --faction stronghold --src <dir>|native \
        [--src ...] --out <metrics.json>

A texsrc folder holds background.png (the HoMM3 town painting, RGB, k x native) and layers/<id>.png (each reachable
layer's static plate, RGBA, k x native) plus manifest.json. The lane bakes its albedo textures from it when
TOWN_FULL3D_TEXSRC=<dir> is set (stronghold_full3d_common.albedo_background / albedo_sprite); masks, depth and geometry
always stay on the native art, so every silhouette is the native mask by construction.

Modes:
  unified   the painting with the sprites composited at their positions.json places is upscaled as ONE image, so the
            model sees each building standing on its own ground; layers are split back by their native masks. Layers
            that overlap (a level's alternatives share a place) go into separate composites (greedy groups of
            non-overlapping masks); every composite is the same painting.
  separate  control: the painting alone, and each sprite alone on an edge-extended pad (its own edge colours pushed
            outwards, so no foreign colour bleeds in), each upscaled on its own with the same model.
The painting itself is always the upscale of the painting alone: under a building the painting's own ground is what
the sweeps reveal, and a composite would carry the building's colours into it.

Models (local, on V:): esrgan-x4plus / esrgan-x4plus-anime (Real-ESRGAN ncnn-vulkan, V:/Tools/video-upscale/realesrgan)
and seedvr2 (SeedVR2 3B fp8, V:/Tools/SeedVR2, run in V:/Models/ssd-venv; unified only). Every GPU run waits on memgate.
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402

K = 4
ESRGAN = Path(r"V:/Tools/video-upscale/realesrgan")
SEEDVR2 = Path(r"V:/Tools/SeedVR2")
SEEDVR2_PY = Path(r"V:/Models/ssd-venv/Scripts/python.exe")
SEEDVR2_DEPS = SC.ROOT / "artifacts" / "claude_takeover_20260927" / "town_scenes" / "texture" / "pydeps"
PAD = 16            # native px of edge-extended context around a separately upscaled sprite
GROUP_GAP = 4       # native px: masks closer than this go into different composites


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def memgate() -> None:
    rc = subprocess.run([sys.executable, str(SC.ROOT / "tools" / "homm3_def_retarget" / "memgate.py"), "--wait", "30"]).returncode
    if rc != 0:
        raise SystemExit("texsrc: memgate refused the GPU run")


def upscale_dir(model: str, src: Path, dst: Path, work: Path) -> None:
    """Upscale every PNG in src to dst (same names, K x)."""
    dst.mkdir(parents=True, exist_ok=True)
    memgate()
    if model.startswith("esrgan-"):
        name = {"esrgan-x4plus": "realesrgan-x4plus", "esrgan-x4plus-anime": "realesrgan-x4plus-anime"}[model]
        r = subprocess.run([str(ESRGAN / "realesrgan-ncnn-vulkan.exe"), "-i", str(src), "-o", str(dst), "-n", name,
                            "-s", str(K), "-m", str(ESRGAN / "models"), "-f", "png"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"texsrc: realesrgan failed: {r.stderr[-2000:]}")
    elif model == "seedvr2":
        sizes = {Image.open(p).size for p in src.glob("*.png")}
        if len({min(s) for s in sizes}) != 1:
            raise SystemExit(f"texsrc: seedvr2 runs one short side per call; inputs have {sorted(sizes)}")
        short = min(next(iter(sizes))) * K
        out = work / "seedvr2_out"
        out.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONPATH": str(SEEDVR2_DEPS), "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([str(SEEDVR2_PY), "inference_cli.py", str(src.resolve()), "--output", str(out.resolve()),
                            "--output_format", "png",
                            "--model_dir", str(SEEDVR2 / "models"), "--dit_model", "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
                            "--resolution", str(short), "--batch_size", "1", "--color_correction", "lab",
                            "--vae_encode_tiled", "--vae_decode_tiled", "--cache_dit", "--cache_vae",
                            "--dit_offload_device", "cpu", "--vae_offload_device", "cpu", "--seed", "42"],
                           cwd=str(SEEDVR2 / "seedvr2_videoupscaler"), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        (work / "seedvr2.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            raise SystemExit(f"texsrc: seedvr2 failed (see {work / 'seedvr2.log'})")
        for p in src.glob("*.png"):
            hits = sorted(out.rglob(f"{p.stem}*.png"))
            if len(hits) != 1:
                raise SystemExit(f"texsrc: seedvr2 output for {p.name}: {hits}")
            im = Image.open(hits[0]).convert("RGB")
            w, h = Image.open(p).size
            if im.size != (w * K, h * K):
                im = im.resize((w * K, h * K), Image.LANCZOS)   # the CLI rounds to its patch grid
            im.save(dst / p.name)
    else:
        raise SystemExit(f"texsrc: unknown model {model}")
    for p in src.glob("*.png"):
        w, h = Image.open(p).size
        q = dst / p.name
        if not q.is_file() or Image.open(q).size != (w * K, h * K):
            raise SystemExit(f"texsrc: {model} gave no {K}x output for {p.name}")


def edge_extend(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    _, (iy, ix) = ndimage.distance_transform_edt(~mask, return_indices=True)
    return rgb[iy, ix]


def groups(lids: list[str], L: dict) -> list[list[str]]:
    """Greedy sets of layers whose masks (grown by GROUP_GAP) do not overlap on the painting."""
    bw, bh = SC.background_rgba().size
    out, occ = [], []
    area = {lid: int((np.asarray(SC.sprite(L[lid]))[..., 3] > 0).sum()) for lid in lids}
    for lid in sorted(lids, key=lambda k: -area[k]):
        m = np.zeros((bh, bw), bool)
        s = np.asarray(SC.sprite(L[lid]))[..., 3] > 0
        x, y = int(L[lid]["x"]), int(L[lid]["y"])
        h, w = s.shape
        m[max(y, 0):y + h, max(x, 0):x + w] = s[max(-y, 0):bh - y, max(-x, 0):bw - x]
        m = ndimage.binary_dilation(m, iterations=GROUP_GAP)
        for g, o in zip(out, occ):
            if not (o & m).any():
                g.append(lid)
                o |= m
                break
        else:
            out.append([lid])
            occ.append(m)
    return out


def build(model: str, mode: str, out: Path) -> dict:
    if out.exists():
        raise SystemExit(f"texsrc: {out} exists (use a new folder)")
    work = out / "work"
    (work / "in").mkdir(parents=True)
    (out / "layers").mkdir(parents=True)
    L = SC.layers()
    lids = SC.reachable_layers()
    bg = SC.background_rgba()
    bg.convert("RGB").save(work / "in" / "background.png")
    plates = {lid: SC.static_plate(L[lid]).convert("RGBA") for lid in lids}
    man = {"schema": "town_full3d_texsrc.v1", "faction": SC.FACTION, "fraction": SC.FRACTION, "model": model,
           "mode": mode, "k": K, "background": SC.FP.BACKGROUND, "layers": {}, "groups": None,
           "proofTier": "generated artifact (local upscale; no Meshy)"}
    if mode == "unified":
        gs = groups(lids, L)
        man["groups"] = gs
        for i, g in enumerate(gs):
            comp = bg.copy()
            for lid in g:
                comp.alpha_composite(plates[lid], (int(L[lid]["x"]), int(L[lid]["y"])))
            comp.convert("RGB").save(work / "in" / f"comp_{i:02d}.png")
    elif mode == "separate":
        if model == "seedvr2":
            raise SystemExit("texsrc: seedvr2 is unified-only (one short side per call)")
        for lid in lids:
            a = np.asarray(plates[lid])
            m = a[..., 3] > 0
            rgb = edge_extend(a[..., :3], m)
            rgb = cv2.copyMakeBorder(rgb, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
            Image.fromarray(rgb).save(work / "in" / f"sprite_{lid}.png")
    else:
        raise SystemExit(f"texsrc: unknown mode {mode}")
    upscale_dir(model, work / "in", work / "up", work)
    shutil.copy2(work / "up" / "background.png", out / "background.png")
    for lid in lids:
        a = np.asarray(plates[lid])
        h, w = a.shape[:2]
        alpha = np.repeat(np.repeat(a[..., 3], K, 0), K, 1)
        if mode == "unified":
            gi = next(i for i, g in enumerate(man["groups"]) if lid in g)
            comp = np.asarray(Image.open(work / "up" / f"comp_{gi:02d}.png").convert("RGB"))
            x, y = int(L[lid]["x"]), int(L[lid]["y"])
            if x < 0 or y < 0 or (y + h) * K > comp.shape[0] or (x + w) * K > comp.shape[1]:
                raise SystemExit(f"texsrc: {lid} leaves the painting; unified split needs it inside")
            rgb = comp[y * K:(y + h) * K, x * K:(x + w) * K]
        else:
            up = np.asarray(Image.open(work / "up" / f"sprite_{lid}.png").convert("RGB"))
            rgb = up[PAD * K:(PAD + h) * K, PAD * K:(PAD + w) * K]
        Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA").save(out / "layers" / f"{lid}.png")
        man["layers"][lid] = {"native": [w, h], "sha256": sha(out / "layers" / f"{lid}.png")}
    man["backgroundSha256"] = sha(out / "background.png")
    (out / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


# ------------------------------------------------------------------------------------------------ measure
BAKE = SC.SCALE * 2          # texels per native px of the lane's albedo bakes (terrain MAIN_SCALE 2, BUILD_SCALE 2)


def _src(src: str):
    L = SC.layers()
    if src == "native":
        return SC.background_rgb(), {lid: SC.static_plate(L[lid]).convert("RGBA") for lid in SC.reachable_layers()}
    d = Path(src)
    return (Image.open(d / "background.png").convert("RGB"),
            {lid: Image.open(d / "layers" / f"{lid}.png").convert("RGBA") for lid in SC.reachable_layers()})


def _bake(im: Image.Image, native_wh) -> np.ndarray:
    return np.asarray(im.resize((round(native_wh[0] * BAKE), round(native_wh[1] * BAKE)), Image.LANCZOS))


def _lap(rgb: np.ndarray, m: np.ndarray) -> float:
    g = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2GRAY).astype(np.float32)
    return float(np.abs(cv2.Laplacian(g, cv2.CV_32F))[m].mean())


def _grain(rgb: np.ndarray, m: np.ndarray) -> float:
    """Native-pixel-scale detail over mid-scale detail (dither / pixel grain reads high; a smooth painting low).
    Both scales are in native px (the image is at BAKE texels per native px), so the ratio compares like with like."""
    g = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2GRAY).astype(np.float32)
    b1 = cv2.GaussianBlur(g, (0, 0), 0.5 * BAKE)
    b2 = cv2.GaussianBlur(g, (0, 0), 2.0 * BAKE)
    return float(np.abs(g - b1)[m].mean() / max(np.abs(b1 - b2)[m].mean(), 1e-6))


def _drift(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    """Palette drift: mean CIELAB distance after a 1.5 native px blur (colour, not the grain the upscale removes)."""
    return float(np.linalg.norm(_lab(cv2.GaussianBlur(a[..., :3], (0, 0), 1.5)) - _lab(cv2.GaussianBlur(b[..., :3], (0, 0), 1.5)),
                                axis=-1)[m].mean())


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2LAB).astype(np.float32)


def _uniq_per_kpx(rgb: np.ndarray, m: np.ndarray) -> float:
    q = (rgb[..., :3][m] >> 2).astype(np.int32)       # 6 bits per channel: ignore interpolation dust
    return float(len(np.unique(q[:, 0] * 4096 + q[:, 1] * 64 + q[:, 2])) / max(m.sum(), 1) * 1000)


def measure(srcs: list[str]) -> dict:
    L = SC.layers()
    nbg, nplates = _src("native")
    res = {}
    for src in srcs:
        bg, plates = _src(src)
        bgb = _bake(bg, nbg.size)
        allm = np.ones(bgb.shape[:2], bool)
        nb = _bake(nbg, nbg.size)
        row = {"painting": {"lap": round(_lap(bgb, allm), 2), "uniqPerKpx": round(_uniq_per_kpx(bgb, allm), 1),
                            "grain": round(_grain(bgb, allm), 3),
                            "driftDeltaE": round(_drift(np.asarray(bg.resize(nbg.size, Image.LANCZOS)),
                                                        np.asarray(nbg), np.ones(nbg.size[::-1], bool)), 2)},
               "layers": {}}
        for lid in SC.reachable_layers():
            na = np.asarray(nplates[lid])
            m_n = na[..., 3] > 0
            wh = (na.shape[1], na.shape[0])
            b = _bake(plates[lid], wh)
            m = cv2.resize(m_n.astype(np.uint8), (b.shape[1], b.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
            inner = cv2.erode(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
            # silhouette: the texture's own alpha against the native mask (bake size)
            am = b[..., 3] > 127
            iou = float((am & m).sum() / max((am | m).sum(), 1))
            # edge bleed: palette drift (as driftDeltaE) on the native mask's 1-2 px edge band, where a composite's
            # painting context can pull foreign colour into the sprite; compare with the interior drift
            back = np.asarray(plates[lid].resize(wh, Image.LANCZOS))
            back = edge_extend(np.ascontiguousarray(back[..., :3]), m_n)   # outside pixels never enter the blur
            na_x = edge_extend(np.ascontiguousarray(na[..., :3]), m_n)
            e_in = cv2.erode(m_n.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            nband = m_n & ~e_in
            bleed = _drift(back, na_x, nband) if nband.any() else 0.0
            drift = _drift(back, na_x, e_in)
            row["layers"][lid] = {"lap": round(_lap(b, inner), 2), "grain": round(_grain(b, inner), 3), "uniqPerKpx": round(_uniq_per_kpx(b, inner), 1),
                                  "silhouetteIoU": round(iou, 4), "edgeBleedDeltaE": round(bleed, 2),
                                  "driftDeltaE": round(drift, 2)}
        ls = row["layers"].values()
        pl = row["painting"]["lap"]
        row["summary"] = {
            "spriteLapMedian": round(float(np.median([v["lap"] for v in ls])), 2),
            "lapRatioSpriteOverPainting": round(float(np.median([v["lap"] for v in ls])) / pl, 3),
            "spriteUniqPerKpxMedian": round(float(np.median([v["uniqPerKpx"] for v in ls])), 1),
            "uniqRatioSpriteOverPainting": round(float(np.median([v["uniqPerKpx"] for v in ls])) / row["painting"]["uniqPerKpx"], 3),
            "spriteGrainMedian": round(float(np.median([v["grain"] for v in ls])), 3),
            "grainRatioSpriteOverPainting": round(float(np.median([v["grain"] for v in ls])) / row["painting"]["grain"], 3),
            "silhouetteIoUMin": min(v["silhouetteIoU"] for v in ls),
            "edgeBleedDeltaEMedian": round(float(np.median([v["edgeBleedDeltaE"] for v in ls])), 2),
            "spriteDriftDeltaEMedian": round(float(np.median([v["driftDeltaE"] for v in ls])), 2)}
        res[src] = row
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "measure"])
    ap.add_argument("--faction", default=SC.FACTION)
    ap.add_argument("--model", default="esrgan-x4plus", choices=["esrgan-x4plus", "esrgan-x4plus-anime", "seedvr2"])
    ap.add_argument("--mode", default="unified", choices=["unified", "separate"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", action="append", default=[])
    a = ap.parse_args()
    if a.cmd == "build":
        man = build(a.model, a.mode, Path(a.out))
        print(json.dumps({k: v for k, v in man.items() if k != "layers"}, indent=1))
    else:
        r = measure(a.src or ["native"])
        Path(a.out).write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps({k: v["painting"] | v["summary"] for k, v in r.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
