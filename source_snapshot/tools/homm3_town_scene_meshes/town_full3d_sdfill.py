"""SDXL-inpaint fill of the texture kit's job canvases (town_full3d_tex kit -> fill -> integrate). Local; no API.

Run with the SD venv:  V:/Tools/sdinpaint/venv/Scripts/python.exe town_full3d_sdfill.py --faction castle [--root R]
(HF_HOME=V:/Tools/sdinpaint/hf). Imports only the faction profile (TEX["sd"], TEX["clean"]), never the lane modules.

  fill   kit/sdinpaint_runs/<promptKey>_s<seed>[_<context>]/<job>.png (1536x1024) + <job>_mask.png + run.json
         The mask is everything outside the painted rect, grown DILATE_PX into it; context 'nohuts' also regenerates
         the painted floor (frame rows >= floorTopY) except seamKeepPx along the seams, and context 'props' fills from the
         kit's props-prefilled input (job_*_sdinput.png) with the extension as the only mask, so the model never sees the painted props it would otherwise clone into the
         extension (integrate keeps extension pixels only). --seeds explores other seeds; the profile's seed is the
         one integrate uses.
  clean  <run>_clean/: only the profile's TEX["clean"] boxes (job:x0,y0,x1,y1[@seed], fill px) re-inpainted and
         feathered in; every other pixel is the source fill's, byte for byte. An empty list skips the step.
  bridge <root>/extsrc_bridge/ (--seeds: extsrc_bridge_s<seed>/): the graded extsrc/ with a band of the extension beside
         the rect's right edge re-inpainted (profile TEX["bridge"]; see bridge()). Run between grade and blend
         (town_full3d_tex blend --src <root>/extsrc_bridge). A profile without TEX["bridge"] refuses the step.
  sky    tex/skypano/<SKY_PANO key>/pano.png: the drift's periodic 360 deg sky (town_full3d_sky.py). From the
         kit (known.png / known_mask.png, the painted sky on the equirectangular band), SDXL fills 1536 x 1024
         windows outward: one centred on the painted sky (its holes and the sky above it), then alternately right
         and left, each keeping SKY_CONTEXT px of what is already filled, and one last window centred on the
         remaining gap across the wrap with context on both sides, so the band closes without a join. Unfilled
         pixels start as the painted sky's mean colour with low-frequency noise (strength SKY_STRENGTH keeps its
         palette); the mask is grown SKY_BLEND px into earlier SD output (crossfaded there, so window joins leave no
         step) and SKY_DILATE px into the painted sky. Last, the SD pixels take the painted sky's CIELAB mean / std
         (measured on the rows the painted sky covers). windows/*.png record every step.
The GPU is taken through town_full3d_gpu.gate (gpuslot + town single-flight lock + memgate VRAM check), held for the
whole model run; there is no other wait.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

LANE = Path(__file__).resolve().parent
sys.path.insert(0, str(LANE))
import town_full3d_factions as FA  # noqa: E402  (reads --faction)
import town_full3d_gpu  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

MODEL = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"
REVISION = "115134f363124c53c7d878647567d04daf26e41e"
OUT_W, OUT_H = 1536, 1024
DILATE_PX = 24
STEPS, GUIDANCE, STRENGTH = 40, 7.0, 1.0
NEED_VRAM_GB = 10.0          # SDXL fp16 inpaint at 1536x1024 (a resource estimate, not a quality gate).
# Measured 2026-10-02 (Conflux --step both, nvidia-smi every 2 s): the whole card went 2.48 -> 14.97 GB used, i.e. this
# step held ~11.9 GiB (torch's caching reserve included); need + VRAM_MARGIN_GB = 12.5 GB free covers it. 11.0 + margin
# asked 13.5 GB free of a 16 GB card whose desktop holds ~2.4 GB, so the gate could never pass (it held the town GPU
# lock 40 min).
CLEAN_FEATHER_PX = 8
SKY_WIN, SKY_CONTEXT, SKY_DILATE, SKY_BLEND, SKY_STRENGTH = 1536, 448, 12, 128, 0.93


def mask_for(man: dict, x0: int, x1: int, sd: dict, kit_dir: Path | None = None, record: bool = False) -> Image.Image:
    TW, TH = man["rect"]
    H = man["frame"][1]
    m = np.full((H, x1 - x0), 255, np.uint8)
    c0, c1 = max(0, -x0), max(0, min(x1, TW) - x0)
    m[:TH, c0:c1] = 0
    img = Image.fromarray(m).filter(ImageFilter.MaxFilter(2 * DILATE_PX + 1))
    if sd["context"] == "nohuts":
        a = np.asarray(img).copy()
        xs = np.arange(x0, x1)
        keep = sd["seamKeepPx"]
        inner = (xs >= 0 + (keep if x0 < 0 else 0)) & (xs < TW - keep)
        a[sd["floorTopY"]:TH - keep, inner] = 255
        img = Image.fromarray(a)
    elif sd["context"] == "props":
        # generation mask = the extension only (the props are pre-filled in the SD input); the saved mask adds the
        # props, so integrate registers on pixels the fill reproduces from the painting, never on the pre-fill
        if record:
            pm = np.asarray(Image.open(kit_dir / man["propMask"]["file"]).convert("L")) > 127
            a = np.asarray(img).copy()
            c0, c1 = max(0, -x0), max(0, min(x1, TW) - x0)
            a[:TH, c0:c1] |= (pm[:, max(0, x0):max(0, x0) + (c1 - c0)] * 255).astype(np.uint8)
            img = Image.fromarray(a)
    elif sd["context"] != "full":
        raise SystemExit(f"sdfill: context {sd['context']!r} is not full / nohuts / props")
    return img.resize((OUT_W, OUT_H), Image.NEAREST)


def run_name(sd: dict) -> str:
    return f"{sd['promptKey']}_s{sd['seed']}" + ("" if sd["context"] == "full" else f"_{sd['context']}")


def fill(pipe, torch, kit: Path, man: dict, sd: dict) -> Path:
    d = kit / "sdinpaint_runs" / run_name(sd)
    d.mkdir(parents=True, exist_ok=True)
    jobs = {}
    for name, j in man["jobs"].items():
        x0, x1 = j["frameX"]
        src = man["propMask"]["sdInputs"][name]["file"] if sd["context"] == "props" else j["file"]
        img = Image.open(kit / src).convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
        mask = mask_for(man, x0, x1, sd, kit)
        mask_for(man, x0, x1, sd, kit, record=True).save(d / f"{name}_mask.png")
        t = time.time()
        g = torch.Generator("cuda").manual_seed(sd["seed"])
        out = pipe(prompt=sd["prompt"], negative_prompt=sd["negative"], image=img, mask_image=mask,
                   width=OUT_W, height=OUT_H, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                   strength=STRENGTH, generator=g).images[0]
        out.save(d / f"{name}.png")
        jobs[name] = {"seconds": round(time.time() - t, 1), "kitInput": j["file"], "kitSha256": j["sha256"]}
        print(run_name(sd), name, jobs[name]["seconds"], flush=True)
    (d / "run.json").write_text(json.dumps({
        "model": MODEL, "revision": REVISION, "variant": "fp16", "pipeline": "StableDiffusionXLInpaintPipeline",
        "faction": FA.KEY, "prompt": sd["prompt"], "negativePrompt": sd["negative"], "seed": sd["seed"],
        "steps": STEPS, "guidance": GUIDANCE, "strength": STRENGTH, "size": [OUT_W, OUT_H], "dilatePx": DILATE_PX,
        "context": sd["context"], "floorTopY": sd.get("floorTopY"), "seamKeepPx": sd.get("seamKeepPx"),
        "torch": torch.__version__, "jobs": jobs}, indent=1), encoding="utf-8")
    return d


def inpaint_box(pipe, torch, srun: dict, img: Image.Image, box, seed: int) -> Image.Image:
    m = np.zeros((OUT_H, OUT_W), np.uint8)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = 255
    g = torch.Generator("cuda").manual_seed(seed)
    gen = pipe(prompt=srun["prompt"], negative_prompt=srun["negativePrompt"], image=img,
               mask_image=Image.fromarray(m).filter(ImageFilter.MaxFilter(2 * CLEAN_FEATHER_PX + 1)),
               width=OUT_W, height=OUT_H, num_inference_steps=STEPS, guidance_scale=GUIDANCE, strength=STRENGTH,
               generator=g).images[0]
    w = np.asarray(Image.fromarray(m).filter(ImageFilter.MaxFilter(2 * CLEAN_FEATHER_PX + 1))
                   .filter(ImageFilter.GaussianBlur(CLEAN_FEATHER_PX / 2)), np.float32)[..., None] / 255
    w = np.maximum(w, m[..., None] / 255.0)
    a0, a1 = np.asarray(img, np.float32), np.asarray(gen, np.float32)
    out = np.where(w > 0, a0 * (1 - w) + a1 * w, a0)
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8))


def clean(pipe, torch, src: Path, boxes: list[str], seed: int, jobs_: list[str]) -> Path:
    srun = json.loads((src / "run.json").read_text(encoding="utf-8"))
    dst = src.parent / f"{src.name}_clean"
    dst.mkdir(parents=True, exist_ok=True)
    per: dict[str, list[tuple]] = {}
    for b in boxes:
        job, xy = b.split(":")
        xy, _, sdv = xy.partition("@")
        per.setdefault(job, []).append(tuple(int(v) for v in xy.split(",")) + ((int(sdv),) if sdv else ()))
    unknown = set(per) - set(jobs_)
    if unknown:
        raise SystemExit(f"sdfill clean: boxes name unknown jobs {sorted(unknown)}")
    jobs = {}
    for name in jobs_:
        shutil.copyfile(src / f"{name}_mask.png", dst / f"{name}_mask.png")
        img = Image.open(src / f"{name}.png").convert("RGB")
        if name not in per:
            shutil.copyfile(src / f"{name}.png", dst / f"{name}.png")
            jobs[name] = {"boxes": [], "copied": True}
            continue
        t = time.time()
        for bx in per[name]:
            img = inpaint_box(pipe, torch, srun, img, bx[:4], bx[4] if len(bx) > 4 else seed)
        Image.fromarray(np.asarray(img)).save(dst / f"{name}.png")
        jobs[name] = {"boxes": per[name], "seconds": round(time.time() - t, 1)}
        print("clean", name, jobs[name], flush=True)
    (dst / "run.json").write_text(json.dumps({**srun, "cleanedFrom": src.name, "cleanSeed": seed,
                                              "cleanFeatherPx": CLEAN_FEATHER_PX, "cleanJobs": jobs}, indent=1),
                                  encoding="utf-8")
    return dst


def sky(pipe, torch, root: Path, pano: dict) -> Path:
    d = root / "skypano" / pano["key"]
    kit = json.loads((d / "kit" / "kit.json").read_text(encoding="utf-8"))
    if kit["faction"] != FA.KEY or kit["pano"] != pano:
        raise SystemExit(f"sdfill sky: kit {d / 'kit'} is not this profile's pano run (re-run town_full3d_sky.py kit)")
    img = np.asarray(Image.open(d / "kit" / "known.png").convert("RGB")).astype(np.float32)
    filled = np.asarray(Image.open(d / "kit" / "known_mask.png")) > 127
    ph, pw = filled.shape
    if ph != OUT_H or pw < 3 * SKY_WIN:
        raise SystemExit(f"sdfill sky: panorama {pw}x{ph} must be {OUT_H} rows and at least {3 * SKY_WIN} wide")
    cols = np.flatnonzero(filled.any(0))
    # the painted block's centre on the circle (its columns are one run; the largest empty run is the gap)
    gaps = np.diff(np.concatenate([cols, cols[:1] + pw]))
    g = int(np.argmax(gaps))
    k1 = int(cols[g]) + 1                 # first empty column after the block (the gap starts here)
    k0 = int(cols[(g + 1) % len(cols)])   # first column of the block
    block = (k1 - k0) % pw or pw
    starts = [(k0 + block // 2 - SKY_WIN // 2) % pw]
    left, right = starts[0], starts[0] + SKY_WIN   # covered arc [left, right) on the unwrapped circle
    step = SKY_WIN - SKY_CONTEXT
    side = 0
    while pw - (right - left) > SKY_WIN - 2 * 192:  # the closing window keeps >= 192 px of context each side
        if side == 0:
            starts.append((right - SKY_CONTEXT) % pw)
            right += step
        else:
            starts.append((left - step) % pw)
            left -= step
        side ^= 1
    gap_c = (right + (pw - (right - left)) // 2) % pw
    starts.append((gap_c - SKY_WIN // 2) % pw)
    wdir = d / "windows"
    wdir.mkdir(parents=True, exist_ok=True)
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    painted = filled.copy()
    rng = np.random.default_rng(pano["seed"])
    mean_rgb = img[painted].mean(0)
    noise = gaussian_filter(rng.normal(0, 1, (ph, pw, 3)), (24, 24, 0), mode="wrap")
    img = np.where(painted[..., None], img, mean_rgb + noise / noise.std() * 18.0)
    log = []
    for i, x0 in enumerate(starts):
        roll = -x0
        win = np.roll(img, roll, 1)[:, :SKY_WIN]
        need = ~np.roll(filled, roll, 1)[:, :SKY_WIN]
        if not need.any():
            log.append({"x0": int(x0), "maskPx": 0})
            continue
        # crossfade width: SKY_BLEND into earlier SD output, SKY_DILATE into the painted sky
        dist, (iy, ix) = distance_transform_edt(~need, return_indices=True)
        pw_ = np.roll(painted, roll, 1)[:, :SKY_WIN]
        width = np.where(pw_, SKY_DILATE, SKY_BLEND)
        w = np.where(need, 1.0, np.clip(1.0 - dist / width, 0.0, 1.0)).astype(np.float32)
        m = Image.fromarray(((w > 0) * 255).astype(np.uint8))
        t0 = time.time()
        gen = torch.Generator("cuda").manual_seed(pano["seed"] + i)
        out = pipe(prompt=pano["prompt"], negative_prompt=pano["negative"],
                   image=Image.fromarray(win.clip(0, 255).astype(np.uint8)), mask_image=m, width=SKY_WIN,
                   height=OUT_H, num_inference_steps=STEPS, guidance_scale=GUIDANCE, strength=SKY_STRENGTH,
                   generator=gen).images[0]
        a1 = np.asarray(out, np.float32)
        mixed = win * (1 - w[..., None]) + a1 * w[..., None]
        full = np.roll(img, roll, 1)
        full[:, :SKY_WIN] = mixed
        img = np.roll(full, -roll, 1)
        ff = np.roll(filled, roll, 1)
        ff[:, :SKY_WIN] = True
        filled = np.roll(ff, -roll, 1)
        Image.fromarray(np.clip(img + 0.5, 0, 255).astype(np.uint8)).resize((pw // 4, ph // 4)).save(
            wdir / f"after_{i}.png")
        log.append({"x0": int(x0), "maskPx": int((w > 0).sum()), "seed": pano["seed"] + i,
                    "seconds": round(time.time() - t0, 1)})
        print("sky window", i, log[-1], flush=True)
    # palette: the SD pixels take the painted sky's CIELAB mean / std (rows the painted sky covers)
    import cv2
    lab = cv2.cvtColor(np.clip(img / 255, 0, 1).astype(np.float32), cv2.COLOR_RGB2LAB)
    rows = painted.any(1)
    ref, src = lab[painted], lab[~painted & rows[:, None]]
    mu_r, sd_r, mu_s, sd_s = ref.mean(0), ref.std(0), src.mean(0), np.maximum(src.std(0), 1e-3)
    lab2 = np.where(painted[..., None], lab, (lab - mu_s) / sd_s * sd_r + mu_r)
    img = cv2.cvtColor(lab2.astype(np.float32), cv2.COLOR_LAB2RGB) * 255
    palette = {"paintedLabMean": mu_r.round(2).tolist(), "paintedLabStd": sd_r.round(2).tolist(),
               "sdLabMeanBefore": mu_s.round(2).tolist(), "sdLabStdBefore": sd_s.round(2).tolist()}
    if not filled.all():
        raise SystemExit(f"sdfill sky: {int((~filled).sum())} px left unfilled")
    Image.fromarray(np.clip(img + 0.5, 0, 255).astype(np.uint8)).save(d / "pano.png")
    (d / "run.json").write_text(json.dumps({
        "model": MODEL, "revision": REVISION, "variant": "fp16", "pipeline": "StableDiffusionXLInpaintPipeline",
        "faction": FA.KEY, "pano": pano, "steps": STEPS, "guidance": GUIDANCE, "strength": STRENGTH,
        "window": SKY_WIN, "contextPx": SKY_CONTEXT, "dilatePx": SKY_DILATE, "blendPx": SKY_BLEND,
        "skyStrength": SKY_STRENGTH, "palette": palette, "size": [pw, ph],
        "kitSha256": kit["knownSha256"], "windows": log, "torch": torch.__version__}, indent=1), encoding="utf-8")
    return d


# bridge (2026-09-28): the graded extension meets the painting at x = TW with a straight structural cut (the fill drew
# its own cliffs / floor beside the painted ones, and context 'nohuts' leaves the painting's edge huts cut). Grade and
# blend correct tone only; the seam-line gate (town_full3d_tex seam_line) fails on it. The bridge re-inpaints a band of
# the EXTENSION beside the right edge with the painting as the left context and the graded extension as the right, so
# the model continues the painted structure into the extension. The rect, the building layers and the extension sky are
# never written (they are context only; the sky is written only under the profile's writeSky); the band crossfades into the extension over its far FADE px.
BRIDGE_WIN = 1024


def bridge(pipe, torch, root: Path, br: dict, seed: int, out: Path) -> Path:
    src = root / "extsrc"
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    canvas = np.asarray(Image.open(src / man["file"]).convert("RGB"))
    rect, bmask, hut, sky_p, sky_e = np.load(root / "masks.npy")
    TW, TH = man["rect"]
    cx0 = man["canvasX"][0]
    H_, W_ = canvas.shape[:2]
    if W_ != man["canvasX"][1] - cx0 or H_ != man["frame"][1]:
        raise SystemExit(f"sdfill bridge: canvas {W_}x{H_} is not the manifest's scale-1 canvas {man['canvasX']}")
    band, fade, rows_extra, ctx = br["bandPx"], br["fadePx"], br["rowsBelowPx"], br["contextPx"]
    xe = TW - cx0                                   # canvas column of the rect's right edge
    c0 = xe - ctx
    if c0 < 0 or c0 + BRIDGE_WIN > W_ or ctx + band + fade > BRIDGE_WIN:
        raise SystemExit(f"sdfill bridge: window [{c0}, {c0 + BRIDGE_WIN}) does not fit the canvas / band")
    r1 = min(TH + rows_extra + fade, BRIDGE_WIN)
    # profile writeSky: the band may also repaint the fill's own sky (Bulwark: the painted edge peak stands against the
    # fill's sky, so its slope can only continue into pixels the fill left as sky; the terrain's skyline follows the
    # result, stronghold_full3d_terrain.fit_ext_skyline). Default: the sky is context only.
    write_sky = bool(br.get("writeSky", False))
    # profile writeExtBuildingMask: the building mask's dilation margin past the rect (a <= 3 px strip at x = TW on
    # Bulwark) is repainted too: it keeps the raw fill's specks, which the terrain shows once EDGE_FRAY cuts the
    # building back from the edge. Inside the rect the building mask is never written.
    bkeep = (bmask & rect) if br.get("writeExtBuildingMask", False) else bmask
    keep = (rect | bkeep | (sky_e & ~write_sky))[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN]
    xs = np.arange(BRIDGE_WIN)[None, :] - ctx       # 0 at the rect edge
    ys = np.arange(BRIDGE_WIN)[:, None]
    sm = lambda t: t * t * (3 - 2 * t)  # noqa: E731
    wx = 1 - sm(np.clip((xs - band) / fade, 0, 1))
    wy = 1 - sm(np.clip((ys - TH - rows_extra) / fade, 0, 1))
    w = np.where((xs >= 0) & ~keep, wx * wy, 0.0).astype(np.float32)
    gen_mask = (w > 0).astype(np.uint8) * 255
    sd_in = canvas.copy()
    ctx_rep = None
    if br.get("rectContext") == "buildingsInpainted":
        # SD input only: the building layers' pixels inside the rect within stripPx of the edge are filled from their
        # surroundings (OpenCV Telea), so the model does not continue a cut building's roof / wall into the band
        # (Bulwark: a hall's roof ridge was drawn on as a bright 4 px line at x = TW)
        import cv2
        strip = int(br["stripPx"])
        cm = np.zeros(rect.shape, bool)
        r0, r1 = br.get("stripRows", (0, rect.shape[0]))   # optional frame-row band of the strip
        cm[int(r0):int(r1), xe - strip:xe] = True
        cm &= rect & bmask
        win = np.s_[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN]
        sd_in[win] = cv2.inpaint(np.ascontiguousarray(sd_in[win]), cm[win].astype(np.uint8), 5, cv2.INPAINT_TELEA)
        ctx_rep = {"rule": "buildingsInpainted", "stripPx": strip, "stripRows": [int(r0), int(r1)],
                   "inpaintedPx": int(cm[win].sum())}
    elif br.get("rectContext") is not None:
        if br["rectContext"] != "housesCarved":
            raise SystemExit(f"sdfill bridge: rectContext {br['rectContext']!r} is not 'housesCarved' / "
                             f"'buildingsInpainted'")
        cj = json.loads((root / "bridge_context.json").read_text(encoding="utf-8"))
        cimg = np.asarray(Image.open(root / cj["file"]).convert("RGB"))
        if cj["faction"] != FA.KEY or list(cimg.shape[:2]) != [TH, TW]:
            raise SystemExit(f"sdfill bridge: {root / 'bridge_context.json'} is not {FA.KEY}'s {TW}x{TH} context "
                             f"(run town_full3d_tex.py bridge-context)")
        sd_in[:TH, -cx0:-cx0 + TW] = cimg     # SD input only: the composite below starts from the canvas
        ctx_rep = {"file": str(root / cj["file"]), "sha256": cj["sha256"], "carvedPx": cj["carvedPx"]}
    img = Image.fromarray(sd_in[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN])
    g = torch.Generator("cuda").manual_seed(seed)
    t = time.time()
    gen = pipe(prompt=br["prompt"], negative_prompt=br["negative"], image=img, mask_image=Image.fromarray(gen_mask),
               width=BRIDGE_WIN, height=BRIDGE_WIN, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
               strength=br.get("strength", STRENGTH), generator=g).images[0]
    a0 = canvas[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN].astype(np.float32)
    a1 = np.asarray(gen, np.float32)
    res = canvas.copy()
    res[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN] = np.clip(a0 * (1 - w[..., None]) + a1 * w[..., None] + 0.5, 0, 255) \
        .astype(np.uint8)
    rr_rep = None
    rr = br.get("rowRepaint")
    if rr is not None:
        # profile rowRepaint (opt-in): a second SDXL pass over the band's own pixels in canvas rows [r0, r1) only, its
        # own seed / prompt, with the first pass's result as context above and below and the painting beside it;
        # feathered over fadePx rows at both ends and weighted by the band weight w, so it writes nothing the first
        # pass did not (Castle: seed 173 bridged rows 170-250 beside the edge as smooth dark sky where the painting's
        # mountain band starts; the sky join and the ghost wall showed it as a dark flat blob)
        if not (isinstance(rr, dict) and set(rr) <= {"rows", "seed", "prompt", "negative", "fadePx", "strength"}
                and isinstance(rr.get("seed"), int) and isinstance(rr.get("fadePx"), int) and rr["fadePx"] >= 1
                and len(rr.get("rows", ())) == 2 and 0 <= rr["rows"][0] < rr["rows"][1] <= BRIDGE_WIN):
            raise SystemExit(f"sdfill bridge: rowRepaint {rr!r} needs rows [r0, r1) in 0..{BRIDGE_WIN}, int seed, "
                             f"int fadePx >= 1 (optional prompt / negative / strength)")
        q0, q1, qf = int(rr["rows"][0]), int(rr["rows"][1]), int(rr["fadePx"])
        wr = np.clip(np.minimum(ys - q0, q1 - 1 - ys) / qf, 0, 1)
        wr = (wr * wr * (3 - 2 * wr)) * (w > 0)
        w2 = (w * wr).astype(np.float32)
        in2 = sd_in.copy()
        in2[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN] = np.where((w > 0)[..., None], res[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN],
                                                         sd_in[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN])
        g2 = torch.Generator("cuda").manual_seed(int(rr["seed"]))
        gen2 = pipe(prompt=rr.get("prompt", br["prompt"]), negative_prompt=rr.get("negative", br["negative"]),
                    image=Image.fromarray(in2[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN]),
                    mask_image=Image.fromarray(((w2 > 0) * 255).astype(np.uint8)), width=BRIDGE_WIN,
                    height=BRIDGE_WIN, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                    strength=rr.get("strength", br.get("strength", STRENGTH)), generator=g2).images[0]
        b0 = res[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN].astype(np.float32)
        res[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN] = np.clip(
            b0 * (1 - w2[..., None]) + np.asarray(gen2, np.float32) * w2[..., None] + 0.5, 0, 255).astype(np.uint8)
        rr_rep = {**rr, "pixels": int((w2 > 0).sum())}
    wrote = np.zeros(rect.shape, bool)
    wrote[:BRIDGE_WIN, c0:c0 + BRIDGE_WIN] = w > 0
    assert (res[rect] == canvas[rect]).all() and (res[bkeep] == canvas[bkeep]).all() \
        and (res[sky_e & ~wrote] == canvas[sky_e & ~wrote]).all() and (write_sky or not (sky_e & wrote).any())
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(res).save(out / "extended_canvas.png")
    Image.fromarray((w * 255).astype(np.uint8)).save(out / "bridge_weight.png")
    import hashlib
    m2 = dict(man)
    m2["sha256"] = hashlib.sha256((out / "extended_canvas.png").read_bytes()).hexdigest()
    m2["bridge"] = {"from": str(src / man["file"]), "fromSha256": man["sha256"], "model": MODEL, "revision": REVISION,
                    "seed": seed, "steps": STEPS, "guidance": GUIDANCE, "strength": br.get("strength", STRENGTH),
                    "window": [int(c0 + cx0), 0, int(c0 + cx0 + BRIDGE_WIN), BRIDGE_WIN], "profile": br,
                    "rows": [0, int(r1)], "rectContext": ctx_rep, "rowRepaint": rr_rep, "seconds": round(time.time() - t, 1), "torch": torch.__version__,
                    "method": "SDXL re-inpaint of the extension band beside the rect's right edge (painting = left "
                              "context), crossfaded into the extension; rect and building layers never written, the "
                              "extension sky only with the profile's writeSky",
                    "proofTier": "generated artifact (offline)"}
    (out / "manifest.json").write_text(json.dumps(m2, indent=1), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=FA.KEY)
    ap.add_argument("--root", default="", help="tex root (default artifacts/<DATA_DIR>/tex)")
    ap.add_argument("--step", choices=["fill", "clean", "both", "sky", "bridge"], default="both")
    ap.add_argument("--seeds", type=int, nargs="*", default=[], help="fill these seeds instead (exploration)")
    ap.add_argument("--repaint-seeds", type=int, nargs="*", default=[],
                    help="bridge: the profile seed with these rowRepaint seeds instead (exploration)")
    a = ap.parse_args()
    P = FA.P
    root = Path(a.root) if a.root else LANE.parents[1] / "artifacts" / P.DATA_DIR / "tex"
    kit = root / "kit"
    if a.step == "sky":
        pano = getattr(P, "SKY_PANO", None)
        if not isinstance(pano, dict):
            raise SystemExit(f"sdfill sky: {FA.KEY} declares no SKY_PANO")
        import torch
        from diffusers import StableDiffusionXLInpaintPipeline
        with town_full3d_gpu.gate(f"sdfill sky {FA.KEY}", need_vram_gb=NEED_VRAM_GB):
            pipe = StableDiffusionXLInpaintPipeline.from_pretrained(MODEL, revision=REVISION,
                                                                    torch_dtype=torch.float16, variant="fp16").to("cuda")
            pipe.set_progress_bar_config(disable=True)
            print(sky(pipe, torch, root, pano))
            del pipe
            torch.cuda.empty_cache()
        return 0
    if a.step == "bridge":
        br = P.TEX.get("bridge")
        if not isinstance(br, dict):
            raise SystemExit(f"sdfill bridge: {FA.KEY} declares no TEX['bridge']")
        import torch
        from diffusers import StableDiffusionXLInpaintPipeline
        with town_full3d_gpu.gate(f"sdfill bridge {FA.KEY}", need_vram_gb=NEED_VRAM_GB):
            pipe = StableDiffusionXLInpaintPipeline.from_pretrained(MODEL, revision=REVISION,
                                                                    torch_dtype=torch.float16, variant="fp16").to("cuda")
            pipe.set_progress_bar_config(disable=True)
            if a.repaint_seeds:     # exploration: extsrc_bridge_rr<seed>/ per rowRepaint seed
                if not isinstance(br.get("rowRepaint"), dict):
                    raise SystemExit(f"sdfill bridge: --repaint-seeds needs {FA.KEY}'s TEX['bridge']['rowRepaint']")
                for s in a.repaint_seeds:
                    b2 = {**br, "rowRepaint": {**br["rowRepaint"], "seed": s}}
                    print(bridge(pipe, torch, root, b2, br["seed"], root / f"extsrc_bridge_rr{s}"), flush=True)
            elif a.seeds:     # exploration: extsrc_bridge_s<seed>/ per seed; the profile's seed writes extsrc_bridge/
                for s in a.seeds:
                    print(bridge(pipe, torch, root, br, s, root / f"extsrc_bridge_s{s}"), flush=True)
            else:
                print(bridge(pipe, torch, root, br, br["seed"], root / "extsrc_bridge"), flush=True)
            del pipe
            torch.cuda.empty_cache()
        return 0
    man = json.loads((kit / "kit_manifest.json").read_text(encoding="utf-8"))
    if man["faction"] != FA.KEY:
        raise SystemExit(f"kit {kit} is {man['faction']!r}, not {FA.KEY!r}")
    sd = P.TEX["sd"]
    boxes = list(P.TEX.get("clean", []))
    import torch
    from diffusers import StableDiffusionXLInpaintPipeline
    with town_full3d_gpu.gate(f"sdfill {FA.KEY}", need_vram_gb=NEED_VRAM_GB):
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.float16,
                                                                variant="fp16").to("cuda")
        pipe.set_progress_bar_config(disable=True)
        src = kit / "sdinpaint_runs" / run_name(sd)
        for seed in a.seeds:
            fill(pipe, torch, kit, man, {**sd, "seed": seed})
        if a.step in ("fill", "both") and not a.seeds:
            src = fill(pipe, torch, kit, man, sd)
        if a.step in ("clean", "both") and boxes and not a.seeds:
            clean(pipe, torch, src, boxes, sd["seed"], list(man["jobs"]))
        del pipe
        torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
