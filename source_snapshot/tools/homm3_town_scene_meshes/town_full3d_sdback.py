#!/usr/bin/env python3
"""Town full-3D: SDXL-inpainted texture for the layered-depth back layers (experiment; see
docs/homm3_town_sdback_inpaint.md).

The layered-depth pass (town_full3d_ldi) gives each ridge a back layer: the far ground continued under the ridge. The
texels that layer shows only when the camera moves (the ridge's own paint in the main albedo) are synthesised there by
image quilting from far-side texels, which reads as pale smear once revealed. This pass repaints exactly those texels
with SDXL inpainting. The input is the quilted texture, so the ridge the fill replaced is already absent and the model
cannot clone it. The prompt is the faction's own extension prompt (TEX["sd"]). The result is graded to the quilted
fill's per-channel mean and standard deviation, which come from real painted far ground.

Mask: every texel where the back texture differs from the main albedo crop (the synthesised texels, and nothing else).
Every other texel, including every texel shown at rest, stays byte for byte, so the rest frame is unchanged by
construction.

Work scale: SCALE of the texel resolution (the albedo is a 2x upscale of the painting). Windows are WIN_W x WIN_H,
overlap by OVERLAP, and run in order, each seeing the earlier windows' output as context. Only windows with masked
texels run.

    V:/Tools/sdinpaint/venv/Scripts/python.exe town_full3d_sdback.py --faction factory --candidate <name>
    (HF_HOME=V:/Tools/sdinpaint/hf)

The GPU is taken through town_full3d_gpu.gate. The script rewrites the candidate's Mesh_Back_* albedo PNGs in place
(the originals go to <candidate>/sdback/orig/ first) and refuses if that backup already exists. Proof tier: generated
artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

LANE = Path(__file__).resolve().parent
sys.path.insert(0, str(LANE))
import town_full3d_factions as FA  # noqa: E402  (reads --faction)
import town_full3d_gpu  # noqa: E402
from town_full3d_sdfill import GUIDANCE, MODEL, REVISION, STEPS  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

SCALE = 0.5
NEED_VRAM_GB = 8.0    # SDXL fp16 inpaint at 1024x768 (half the px of the sdfill 1536x1024 run, which needs 11)
WIN_W, WIN_H = 1024, 768
OVERLAP = 256
STRENGTH = 1.0         # below 1.0 the pipeline starts masked areas from its grey placeholder and small islands stay
                       # grey blotches (v1 at 0.92, fa_v9_sdback review); sdfill runs at 1.0 too
CLOSE = 0              # work px: morphological closing of the SD mask (merges the hidden fragments into whole regions)
DILATE = 8             # work px the SD mask grows past the synthesised texels (the composite uses the exact mask)
FEATHER = 2.0          # composite feather inside the exact mask (texel px)
PIECES = {             # back piece -> (main piece, stage_report ldi key for its crop box)
    "Mesh_Back_Terrain": ("Mesh_Terrain", "texture"),
    "Mesh_Back_Terrain_Far": ("Mesh_Terrain", "stopTexture"),
    "Mesh_Back_TerrainNear_0": ("Mesh_TerrainNear_0", "texture"),
}


def windows(mask: np.ndarray):
    h, w = mask.shape
    ww, wh = min(WIN_W, w), min(WIN_H, h)
    xs = list(range(0, max(w - ww, 0) + 1, ww - OVERLAP)) or [0]
    ys = list(range(0, max(h - wh, 0) + 1, wh - OVERLAP)) or [0]
    if xs[-1] != max(w - ww, 0):
        xs.append(max(w - ww, 0))
    if ys[-1] != max(h - wh, 0):
        ys.append(max(h - wh, 0))
    for y in ys:
        for x in xs:
            if mask[y:y + wh, x:x + ww].any():
                yield x, y, ww, wh


def grade(gen: np.ndarray, ref: np.ndarray, sel: np.ndarray) -> np.ndarray:
    """Per-channel mean / std of gen over sel matched to ref's over sel."""
    out = gen.astype(np.float64).copy()
    for c in range(3):
        g, r = out[..., c][sel], ref[..., c][sel].astype(np.float64)
        gs = g.std() if g.std() > 1e-6 else 1.0
        out[..., c] = (out[..., c] - g.mean()) * (r.std() / gs) + r.mean()
    return np.clip(out, 0, 255)


def run_piece(pipe, torch, back: np.ndarray, main_crop: np.ndarray, sd: dict, seed: int, dbg: Path, name: str):
    mask = np.abs(back.astype(np.int16) - main_crop.astype(np.int16)).max(2) > 0
    th, tw = mask.shape
    sw, sh = max(8, int(round(tw * SCALE / 8)) * 8), max(8, int(round(th * SCALE / 8)) * 8)
    work = np.asarray(Image.fromarray(back).resize((sw, sh), Image.LANCZOS)).copy()
    wmask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((sw, sh), Image.BILINEAR)) > 0
    wm = Image.fromarray((wmask * 255).astype(np.uint8))
    if CLOSE:
        wm = wm.filter(ImageFilter.MaxFilter(2 * CLOSE + 1)).filter(ImageFilter.MinFilter(2 * CLOSE + 1))
    wmask_d = np.asarray(wm.filter(ImageFilter.MaxFilter(2 * DILATE + 1))) > 0
    # pad to window size where the texture is smaller than a window (reflect)
    ph, pw = max(WIN_H - sh, 0), max(WIN_W - sw, 0)
    if ph or pw:
        work = np.pad(work, ((0, ph), (0, pw), (0, 0)), mode="reflect")
        wmask_d = np.pad(wmask_d, ((0, ph), (0, pw)))
    wins = list(windows(wmask_d))
    for k, (x, y, ww, wh) in enumerate(wins):
        img = Image.fromarray(work[y:y + wh, x:x + ww])
        m = Image.fromarray((wmask_d[y:y + wh, x:x + ww] * 255).astype(np.uint8))
        g = torch.Generator("cuda").manual_seed(seed + k)
        out = pipe(prompt=sd["prompt"], negative_prompt=sd["negative"], image=img, mask_image=m, width=ww, height=wh,
                   num_inference_steps=STEPS, guidance_scale=GUIDANCE, strength=STRENGTH, generator=g).images[0]
        o = np.asarray(out.convert("RGB"))
        sel = wmask_d[y:y + wh, x:x + ww]
        work[y:y + wh, x:x + ww] = np.where(sel[..., None], o, work[y:y + wh, x:x + ww])
        print(f"  {name} window {k + 1}/{len(wins)} @({x},{y})", flush=True)
    work = work[:sh, :sw]
    up = np.asarray(Image.fromarray(work).resize((tw, th), Image.LANCZOS)).astype(np.float64)
    up = grade(up, back, mask)
    a = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
                   .filter(ImageFilter.GaussianBlur(FEATHER)), np.float64)[..., None] / 255.0
    a = np.where(mask[..., None], np.maximum(a, 0.0), 0.0)
    res = np.clip(up * a + back.astype(np.float64) * (1 - a) + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray((mask * 255).astype(np.uint8)).save(dbg / f"{name}_mask.png")
    return res, {"maskTexels": int(mask.sum()), "windows": len(wins), "workSize": [sw, sh],
                 "changedOutsideMask": int((res != back).any(2)[~mask].sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=FA.KEY)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--close", type=int, default=CLOSE, help="work px of mask closing before SD (0: off)")
    ap.add_argument("--seed", type=int, default=0, help="default: the profile's TEX['sd'] seed")
    a = ap.parse_args()
    globals()["CLOSE"] = a.close
    P = FA.P
    sd = P.TEX["sd"]
    seed = a.seed or int(sd["seed"])
    cand = LANE.parents[1] / "artifacts" / P.DATA_DIR / "candidates" / a.candidate
    envs = list((cand / "unity_project" / "Assets" / "Homm3TownScene3d").glob("*/*_environment"))
    if len(envs) != 1:
        raise SystemExit(f"sdback: expected one environment prefab dir under {cand}, found {envs}")
    pdir = envs[0]
    sr = json.loads((cand / "work" / "stage_report.json").read_text(encoding="utf-8"))
    ldi = sr.get("ldi", {}).get("pieces", {})
    dbg = cand / "sdback"
    orig = dbg / "orig"
    if orig.exists():
        raise SystemExit(f"sdback: {orig} exists (already applied; re-seed the candidate)")
    orig.mkdir(parents=True)
    todo = []
    for bname, (mname, key) in PIECES.items():
        bp = pdir / f"{bname}_albedo.png"
        rep = ldi.get(mname, {}).get(key)
        if not bp.is_file() or not rep:
            continue
        x0, y0, x1, y1 = rep["cropTexels"]
        main_crop = np.asarray(Image.open(pdir / f"{mname}_albedo.png").convert("RGB"))[y0:y1, x0:x1]
        back = np.asarray(Image.open(bp).convert("RGB"))
        if back.shape != main_crop.shape:
            raise SystemExit(f"sdback: {bname} {back.shape} does not match its crop of {mname} {main_crop.shape}")
        shutil.copy2(bp, orig / bp.name)
        todo.append((bname, bp, back, main_crop))
    import torch
    from diffusers import StableDiffusionXLInpaintPipeline
    report = {"schema": "town_full3d_sdback.v1", "faction": FA.KEY, "candidate": a.candidate, "model": MODEL,
              "revision": REVISION, "prompt": sd["prompt"], "negative": sd["negative"], "seed": seed,
              "steps": STEPS, "guidance": GUIDANCE, "strength": STRENGTH, "scale": SCALE, "close": CLOSE, "dilate": DILATE, "pieces": {},
              "proofTier": "generated artifact"}
    with town_full3d_gpu.gate(f"sdback {FA.KEY}", need_vram_gb=NEED_VRAM_GB):
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.float16,
                                                                variant="fp16").to("cuda")
        pipe.set_progress_bar_config(disable=True)
        for bname, bp, back, main_crop in todo:
            res, rep = run_piece(pipe, torch, back, main_crop, sd, seed, dbg, bname)
            if rep["changedOutsideMask"]:
                raise SystemExit(f"sdback: {bname} changed {rep['changedOutsideMask']} texels outside the mask")
            Image.fromarray(res).save(bp)
            report["pieces"][bname] = rep
            print(bname, json.dumps(rep), flush=True)
        del pipe
        torch.cuda.empty_cache()
    (dbg / "sdback_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
