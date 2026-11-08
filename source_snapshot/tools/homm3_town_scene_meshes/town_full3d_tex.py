"""Frame-extension texture chain of the full-3D town lane ("tex_sdgrade"), faction-parameterised.

The rest camera's 1920x1080 frame holds the HoMM3 painting in its top-left 1440x673 rect (x1.8); everything else the
pans can see (x >= 1440, y >= 673, and the image plane to the left of x=0 and right of x=1920) is an outpaint baked
from one canvas, TOWN_FULL3D_EXTSRC (schema town_full3d_extsrc.v1, frame columns [-600, 2320)). This module builds that
canvas; the SDXL fill itself runs in the SD venv (town_full3d_sdfill.py). All faction values come from the profile
(TEX, SKY_MASK); the method constants below are the lane's. Moved from the Stronghold scripts under
artifacts/claude_takeover_20260927/town_scenes/texture/ (build_kit, integrate, grade, blend, deliver); Stronghold's
constants moved into its profile verbatim, and the numpy op order is kept so its canvases rebuild byte-identically.

Steps (outputs under --root, default artifacts/<DATA_DIR>/tex):
  kit        kit/job_A_right.png, kit/job_B_left.png (painting on grey 128), kit/style_ref_buildings.png, manifest
  fill       (town_full3d_sdfill.py, SD venv) kit/sdinpaint_runs/<promptKey>_s<seed>[_<context>][_clean]/
  integrate  integrated/: Real-ESRGAN x4plus, ECC registration on the kept context, CIELAB match, floor grain/tone,
             seam carry; the rect is always the lane's painting (asserted)
  grade      extsrc/ + masks.npy: local weighted CIELAB histogram match to the painting, local contrast, edge residual,
             optional render-referred residual (--render-ref <rest preview of the previous grade's stage>)
  blend      extsrc_blend/: cliff tone beside the side edges + low-pass-only edge blend (detail kept)
  deliver    mask viz, building-pixel diff between two candidates' previews, seam metrics (seam_metrics.json),
             painting | before | after crop sheet
Never written by any step: the painted rect, the building-layer footprints (dilated), the extension sky. Asserted.

python town_full3d_tex.py --faction castle kit|integrate|grade|blend|deliver [...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import distance_transform_edt, gaussian_filter, gaussian_filter1d

import stronghold_full3d_common as SC  # noqa: E402  (reads --faction)
import town_full3d_masks as M

LANE = Path(__file__).resolve().parent
ROOT = LANE.parents[1]
TEX = SC.FP.TEX
W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
GREY = (128, 128, 128)
JOBS = {"job_A_right": (700, 2320), "job_B_left": (-600, 1020)}   # frame x ranges; y is always [0, H)
ESRGAN = Path("V:/Tools/video-upscale/realesrgan")


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def f32(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB")).astype(np.float32) / 255


def default_root() -> Path:
    return SC.DATA / "tex"


# ================================================================================================ kit
def frame_painting() -> Image.Image:
    return SC.background_rgb().resize((TW, TH), Image.LANCZOS)


def kit(root: Path) -> dict:
    out = root / "kit"
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, (x0, x1) in JOBS.items():
        c = Image.new("RGB", (x1 - x0, H), GREY)
        c.paste(frame_painting(), (0 - x0, 0))
        p = out / f"{name}.png"
        c.save(p)
        files[name] = {"file": p.name, "sha256": sha(p), "frameX": [x0, x1], "frameY": [0, H],
                       "size": [x1 - x0, H], "result": f"results/{name}.png"}
    bg = SC.background_rgba()
    for L in sorted(SC.layers().values(), key=lambda L: L.get("z", 0)):
        bg.alpha_composite(SC.sprite(L), (int(L["x"]), int(L["y"])))
    crop = tuple(TEX["styleCropNative"])
    c = bg.convert("RGB").crop(crop)
    sp = out / "style_ref_buildings.png"
    c.resize((c.width * 2, c.height * 2), Image.LANCZOS).save(sp)
    props = None
    if TEX["sd"]["context"] == "props":
        # SD input with the painted props pre-filled (prefill(): local floor colour + the bare floor's own grain;
        # a cv2 Telea inpaint carried the cottages' shadows in as grey blobs the model cloned): the model sees a
        # plain floor there, so it cannot clone the props into the extension. Masking the props for generation instead
        # leaves scattered holes that SDXL-inpaint fills with grey latent blocks (p2_s*_props, first pass). The kit's
        # job_*.png stay the painting: integrate registers and colour-matches against the painting itself.
        pm = prop_mask_rect(np.asarray(frame_painting()))
        pmd = cv2.dilate(pm.astype(np.uint8), np.ones((PREFILL_DILATE, PREFILL_DILATE), np.uint8))
        pre_img = Image.fromarray(prefill(np.asarray(frame_painting()), pmd > 0))
        pp = out / "prop_mask.png"
        Image.fromarray((pmd * 255).astype(np.uint8)).save(pp)
        props = {"file": pp.name, "sha256": sha(pp), "px": int(pmd.sum()), "sdInputs": {}}
        for name, (x0, x1) in JOBS.items():
            c = Image.new("RGB", (x1 - x0, H), GREY)
            c.paste(pre_img, (0 - x0, 0))
            q = out / f"{name}_sdinput.png"
            c.save(q)
            props["sdInputs"][name] = {"file": q.name, "sha256": sha(q)}
    man = {"schema": "town_full3d_chatgpt_kit.v1", "faction": SC.FACTION, "fraction": SC.FRACTION,
           "background": SC.FP.BACKGROUND, "frame": [W, H], "rect": [TW, TH], "scale": SC.SCALE,
           "canvasX": [min(a for a, _ in JOBS.values()), max(b for _, b in JOBS.values())], "grey": list(GREY),
           "jobs": files, "styleRef": {"file": sp.name, "sha256": sha(sp), "nativeCrop": list(crop)},
           **({"propMask": props} if props else {}),
           "proofTier": "kit inputs only (no generation has run)"}
    (out / "kit_manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


PREFILL_DILATE, PREFILL_SIGMA = 13, 20.0


def prefill(paint: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Props replaced by floor: the local colour of the surrounding non-prop pixels (normalised Gaussian, sigma
    PREFILL_SIGMA, x3 and x9 where the finer scale sees under 5% known pixels) plus the high-pass grain of the profile's bare floor box (TEX['integrate']['paintFloor']), tiled.
    Only the SD input uses it; nothing staged keeps these pixels."""
    f = paint.astype(np.float32)
    known = (~hole).astype(np.float32)
    low, have = np.zeros_like(f), np.zeros(f.shape[:2], np.float32)
    for sig in (PREFILL_SIGMA, PREFILL_SIGMA * 3, PREFILL_SIGMA * 9):   # push-pull: coarser where a hole is wide
        num = cv2.GaussianBlur(f * known[..., None], (0, 0), sig)
        den = cv2.GaussianBlur(known, (0, 0), sig)
        w = np.clip(den / 0.05, 0, 1) * (1 - have)
        low += w[..., None] * num / np.maximum(den, 1e-6)[..., None]
        have += w
    x0, y0, x1, y1 = TEX["integrate"]["paintFloor"]
    box = f[y0:y1, x0:x1]
    hp = box - cv2.GaussianBlur(box, (0, 0), 3.0)
    reps = (f.shape[0] // hp.shape[0] + 1, f.shape[1] // hp.shape[1] + 1, 1)
    det = np.tile(hp, reps)[:f.shape[0], :f.shape[1]]
    out = np.where(hole[..., None], low + det, f)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def fill_run_dir(root: Path, clean: bool = True) -> Path:
    sd = TEX["sd"]
    name = f"{sd['promptKey']}_s{sd['seed']}" + ("" if sd["context"] == "full" else f"_{sd['context']}")
    return root / "kit" / "sdinpaint_runs" / (name + ("_clean" if clean and TEX.get("clean") else ""))


# ================================================================================================ integrate
BAND_PX = 200
SEAM_IN_PX = 12
FEATHER_PX = 48.0
WIDE_SIGMA, WIDE_IN_PX, WIDE_FEATHER_PX = 40.0, 40, 240.0
BAND_SIGMAS = (1.0, 3.0, 8.0)
GAIN_MAX = 2.5
GRAIN_PATCH, GRAIN_STRIDE = 64, 32
GRAIN_SEED = 7
MIN_ECC = 0.85
MAX_SCALE_ERR, MAX_SHIFT_PX = 0.06, 60.0


def _painted_mask(x0: int, x1: int) -> np.ndarray:
    m = np.zeros((H, x1 - x0), bool)
    m[:TH, max(0, -x0):max(0, min(x1, TW) - x0)] = True
    return m


def _register(src, ref, mask):
    g = lambda a: cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), (0, 0), 1.5)
    s2, r2 = cv2.resize(g(src), None, fx=0.5, fy=0.5), cv2.resize(g(ref), None, fx=0.5, fy=0.5)
    m2 = cv2.resize(cv2.erode(mask.astype(np.uint8), np.ones((13, 13), np.uint8)), None, fx=0.5, fy=0.5,
                    interpolation=cv2.INTER_NEAREST)
    warp = np.eye(2, 3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6)
    cc, warp = cv2.findTransformECC(r2, s2, warp, cv2.MOTION_AFFINE, crit, m2, 5)
    warp[:, 2] *= 2
    sx, sy = float(np.hypot(*warp[:, 0])), float(np.hypot(*warp[:, 1]))
    rep = {"ecc": round(float(cc), 4), "scale": [round(sx, 4), round(sy, 4)],
           "shiftPx": [round(float(warp[0, 2]), 2), round(float(warp[1, 2]), 2)]}
    bad = []
    if cc < MIN_ECC:
        bad.append(f"ecc {cc:.3f} < {MIN_ECC}")
    if max(abs(sx - 1), abs(sy - 1)) > MAX_SCALE_ERR:
        bad.append(f"scale {sx:.3f}/{sy:.3f}")
    if max(abs(warp[0, 2]), abs(warp[1, 2])) > MAX_SHIFT_PX:
        bad.append(f"shift {warp[0, 2]:.1f}/{warp[1, 2]:.1f}")
    if bad:
        raise SystemExit("registration refused (" + ", ".join(bad) + "): the fill is cropped, zoomed or moved")
    h, w = ref.shape[:2]
    return cv2.warpAffine(src, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE), rep


def _colour_match(src, ref, band):
    ls, lr = cv2.cvtColor(src, cv2.COLOR_RGB2LAB), cv2.cvtColor(ref, cv2.COLOR_RGB2LAB)
    ms, ss = ls[band].mean(0), ls[band].std(0) + 1e-3
    mr, sr = lr[band].mean(0), lr[band].std(0) + 1e-3
    lab = (ls - ms) / ss * sr + mr
    out = np.clip(cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1)
    de = float(np.linalg.norm(cv2.cvtColor(out, cv2.COLOR_RGB2LAB)[band] - lr[band], axis=-1).mean())
    return out, {"labMeanShift": [round(float(v), 2) for v in mr - ms], "labStdGain": [round(float(v), 3)
                 for v in sr / ss], "bandDeltaEAfter": round(de, 2)}


def _carry(src, ref, painted, din, dout, iy, ix, depth, sigma, feather):
    near = painted & (din <= depth)
    res = np.where(near[..., None], ref - src, 0).astype(np.float32)
    wt = cv2.GaussianBlur(near.astype(np.float32), (0, 0), sigma)
    res = cv2.GaussianBlur(res, (0, 0), sigma) / np.maximum(wt[..., None], 1e-3)
    off = res[iy, ix] * np.exp(-dout / feather)[..., None]
    out = np.where(painted[..., None], src, np.clip(src + off, 0, 1)).astype(np.float32)
    return out, round(float(np.abs(res[near]).mean()) * 255, 2)


def _tone_across(src, ref, painted, din, dout, iy, ix):
    fr = TEX["integrate"]["floorRamp"]
    ins = (painted & (din <= WIDE_IN_PX)).astype(np.float32)
    outs = (~painted & (dout <= WIDE_IN_PX)).astype(np.float32)
    blur = lambda a: cv2.GaussianBlur(a, (0, 0), WIDE_SIGMA)
    m_in = blur(ref * ins[..., None]) / np.maximum(blur(ins), 1e-4)[..., None]
    m_out = blur(src * outs[..., None]) / np.maximum(blur(outs), 1e-4)[..., None]
    # cliff and sky rows only: on the floor the rect edge can be painted props (carried out as a grey cast)
    h = src.shape[0]
    cliff = 1 - np.clip((np.arange(h, dtype=np.float32) - fr[0]) / (fr[1] - fr[0]), 0, 1)
    diff = (m_in - m_out)[iy, ix] * cliff[iy][..., None]
    out = np.where(painted[..., None], src, np.clip(src + diff * np.exp(-dout / WIDE_FEATHER_PX)[..., None], 0, 1))
    seam = ~painted & (dout <= 1.5)
    return out.astype(np.float32), round(float(np.abs(diff[seam]).mean()) * 255, 2)


def _seam_correct(src, ref, painted):
    din = distance_transform_edt(painted)
    dout, (iy, ix) = distance_transform_edt(~painted, return_indices=True)
    wide, rw = _tone_across(src, ref, painted, din, dout, iy, ix)
    out, rn = _carry(wide, ref, painted, din, dout, iy, ix, SEAM_IN_PX, 8.0, FEATHER_PX)
    return out, {"seamToneStepMeanAbs": rw, "seamResidualMeanAbs": rn}


def _loglum(rgb):
    return np.log(np.maximum((np.clip(rgb, 0, 1) ** 2.2).mean(-1), 1e-4))


def _bands(l):
    gs = [cv2.GaussianBlur(l, (0, 0), s) for s in BAND_SIGMAS]
    return [l - gs[0], gs[0] - gs[1], gs[1] - gs[2]]


def _grain_reference(paint):
    x0, y0, x1, y1 = TEX["integrate"]["paintFloor"]
    bd = _bands(_loglum(paint))
    lab = cv2.cvtColor(np.ascontiguousarray(paint[y0:y1, x0:x1]), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    return {"std": [float(b[y0:y1, x0:x1].std()) for b in bd], "grainSrc": [b[y0:y1, x0:x1].copy() for b in bd[:2]],
            "labMean": lab.mean(0), "labStd": lab.std(0)}


def _quilt(src, h, w, rng):
    P, S = GRAIN_PATCH, GRAIN_STRIDE
    src = (src - src.mean()) / (src.std() + 1e-6)
    win = np.outer(np.hanning(P + 2)[1:-1], np.hanning(P + 2)[1:-1]).astype(np.float32)
    acc = np.zeros((h + 2 * P, w + 2 * P), np.float32)
    w2 = np.zeros_like(acc)
    for y in range(0, h + P, S):
        for x in range(0, w + P, S):
            sy, sx = rng.integers(0, src.shape[0] - P + 1), rng.integers(0, src.shape[1] - P + 1)
            p = src[sy:sy + P, sx:sx + P]
            if rng.random() < 0.5:
                p = p[:, ::-1]
            acc[y:y + P, x:x + P] += p * win
            w2[y:y + P, x:x + P] += win * win
    g = (acc / np.sqrt(np.maximum(w2, 1e-6)))[P:P + h, P:P + w]
    return g / (g.std() + 1e-6)


def _grain_tone(src, painted, x0, g):
    fr = TEX["integrate"]["floorRamp"]
    h, w = src.shape[:2]
    ys = np.arange(h, dtype=np.float32)
    ramp = np.clip((ys - fr[0]) / (fr[1] - fr[0]), 0, 1)
    wt = np.where(painted, 0.0, ramp[:, None]).astype(np.float32)
    wt = cv2.GaussianBlur(wt, (0, 0), 6) * (~painted)
    sel = wt > 0.5
    lab = cv2.cvtColor(src, cv2.COLOR_RGB2LAB)
    ms, ss = lab[sel].mean(0), lab[sel].std(0) + 1e-3
    tgt = (lab - ms) / ss * g["labStd"] + g["labMean"]
    tgt[..., 0] = lab[..., 0] - ms[0] + g["labMean"][0]
    toned = np.clip(cv2.cvtColor(tgt.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1)
    bd = _bands(_loglum(toned))
    fs = [float(b[sel].std()) for b in bd]
    gains = [1.0, *(float(np.clip(r / max(f, 1e-6), 1.0, GAIN_MAX)) for r, f in zip(g["std"][1:], fs[1:]))]
    add = sum((gn - 1) * b for gn, b in zip(gains, bd))
    rng = np.random.default_rng(GRAIN_SEED + (x0 % 9973))
    needs = []
    for k, srcband in enumerate(g["grainSrc"]):
        need = float(np.sqrt(max(g["std"][k] ** 2 - (fs[k] * gains[k]) ** 2, 0.0)))
        needs.append(round(need, 4))
        if need > 0:
            q = _quilt(srcband, h, w, rng)
            add = add + need * q / (float(_bands(q)[k].std()) + 1e-6)
    lin = toned ** 2.2 * np.exp(np.clip(add, -1.5, 1.5))[..., None]
    grained = np.clip(lin, 0, 1) ** (1 / 2.2)
    out = src * (1 - wt[..., None]) + grained * wt[..., None]
    rt = (ramp[:, None] * painted)[..., None]
    out = np.where(painted[..., None], src * (1 - rt) + toned * rt, out)
    return out.astype(np.float32), {"grain": {"fillBandStd": [round(v, 4) for v in fs],
                                              "paintBandStd": [round(v, 4) for v in g["std"]],
                                              "gains": [round(v, 3) for v in gains], "quiltedStd": needs,
                                              "labShift": [round(float(v), 2) for v in g["labMean"] - ms]}}


def _esrgan(results: Path, names, work: Path) -> Path:
    """Real-ESRGAN x4plus (ncnn-vulkan, ~1 GB VRAM) on each fill, through the lane's GPU gate; cached."""
    work.mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not (work / f"{n}.png").is_file()]
    if todo:
        import town_full3d_gpu
        with town_full3d_gpu.gate(f"esrgan {SC.FACTION}", need_vram_gb=2.0):
            for n in todo:
                o = work / f"{n}.png"
                r = subprocess.run([str(ESRGAN / "realesrgan-ncnn-vulkan.exe"), "-i", str(results / f"{n}.png"),
                                    "-o", str(o), "-n", "realesrgan-x4plus"], capture_output=True, text=True)
                if r.returncode != 0 or not o.is_file():
                    raise SystemExit(f"realesrgan failed on {n}: {r.stderr[-1500:]}")
    for n in names:
        mp = results / f"{n}_mask.png"
        if mp.is_file():
            (work / mp.name).write_bytes(mp.read_bytes())
    return work


def integrate(root: Path, results: Path | None = None, out: Path | None = None) -> dict:
    kitd = root / "kit"
    man = json.loads((kitd / "kit_manifest.json").read_text(encoding="utf-8"))
    if man["faction"] != SC.FACTION:
        raise SystemExit(f"kit {kitd} is {man['faction']!r}, not {SC.FACTION!r}")
    results = results or fill_run_dir(root)
    out = out or root / "integrated"
    cfg = TEX["integrate"]
    cx0, cx1 = man["canvasX"]
    paint = f32(frame_painting())
    acc = np.zeros((H, cx1 - cx0, 3), np.float32)
    wsum = np.zeros((H, cx1 - cx0), np.float32)
    jobs = man["jobs"]
    rep = {}
    src_dir = results
    if cfg["esrgan"]:
        results = _esrgan(src_dir, list(jobs), out / "esrgan_x4plus")
    gref = _grain_reference(paint) if cfg["grain"] else None
    for name, j in jobs.items():
        rp = results / f"{name}.png"
        if not rp.is_file():
            raise SystemExit(f"missing {rp}")
        x0, x1 = j["frameX"]
        ref = f32(Image.open(kitd / j["file"]))
        got = f32(Image.open(rp).resize((x1 - x0, H), Image.LANCZOS))
        painted = _painted_mask(x0, x1)
        mp = results / f"{name}_mask.png"
        keep = painted
        if mp.is_file():
            gen = np.asarray(Image.open(mp).convert("L").resize((x1 - x0, H), Image.NEAREST)) > 127
            keep = painted & ~gen
        reg, r1 = _register(got, ref, keep)
        r1["registeredOn"] = "kept context (mask file)" if mp.is_file() else "painted rect"
        band = keep & (distance_transform_edt(painted) <= BAND_PX)
        col, r2 = _colour_match(reg, ref, band)
        r4 = {}
        if gref is not None:
            col, r4 = _grain_tone(col, painted, x0, gref)
        fin, r3 = _seam_correct(col, ref, painted)
        others = [o["frameX"] for k, o in jobs.items() if k != name]
        w = np.ones(x1 - x0, np.float32)
        for ox0, ox1 in others:
            lo, hi = max(x0, ox0), min(x1, ox1)
            if lo < hi:
                t = np.clip((np.arange(x0, x1) - lo) / (hi - lo), 0, 1)
                w *= np.where((np.arange(x0, x1) >= lo) & (np.arange(x0, x1) < hi), 1 - t if x0 < ox0 else t, 1)
        c0 = x0 - cx0
        acc[:, c0:c0 + (x1 - x0)] += fin * w[None, :, None]
        wsum[:, c0:c0 + (x1 - x0)] += w[None, :]
        rep[name] = {"result": rp.name, "sha256": sha(rp), "size": list(Image.open(rp).size), **r1, **r2, **r3, **r4}
    ext = acc / np.maximum(wsum[..., None], 1e-6)
    if (wsum <= 0).any():
        raise SystemExit("the jobs leave canvas pixels uncovered")
    canvas = ext.copy()
    canvas[:TH, -cx0:-cx0 + TW] = paint
    out.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray((np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8))
    img.save(out / "extended_canvas.png")
    rect_exact = bool(np.array_equal(np.asarray(img)[:TH, -cx0:-cx0 + TW],
                                     (np.clip(paint, 0, 1) * 255 + 0.5).astype(np.uint8)))
    if not rect_exact:
        raise SystemExit("integrate: the painted rect was not preserved")
    m = {"schema": "town_full3d_extsrc.v1", "faction": SC.FACTION, "fraction": SC.FRACTION,
         "file": "extended_canvas.png", "sha256": sha(out / "extended_canvas.png"), "frame": [W, H],
         "rect": [TW, TH], "canvasX": [cx0, cx1], "source": str(src_dir), "kit": str(kitd),
         "esrgan": "realesrgan-x4plus" if cfg["esrgan"] else None, "rectExact": rect_exact, "jobs": rep,
         "params": {"bandPx": BAND_PX, "seamInPx": SEAM_IN_PX, "featherPx": FEATHER_PX, "minEcc": MIN_ECC,
                    "wide": [WIDE_SIGMA, WIDE_IN_PX, WIDE_FEATHER_PX],
                    "grain": ({"paintFloor": cfg["paintFloor"], "floorRamp": cfg["floorRamp"],
                               "bandSigmas": BAND_SIGMAS, "gainMax": GAIN_MAX, "patch": GRAIN_PATCH,
                               "seed": GRAIN_SEED} if cfg["grain"] else None)},
         "proofTier": "generated artifact (integrated outpaint; offline)"}
    (out / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    return m


# ================================================================================================ masks
def building_mask_frame() -> np.ndarray:
    """Every positions.json layer's own native mask (the solid split's), x1.8, dilated 7x7, frame px."""
    import stronghold_full3d_buildings as BL
    bmask_f = np.zeros((SC.H, SC.W), bool)
    for L in SC.positions()["layers"]:
        m = BL.native_mask(L).astype(np.uint8)
        m = cv2.resize(m, (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)),
                       interpolation=cv2.INTER_NEAREST)
        x, y = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
        h, w = m.shape
        y1, x1 = min(y + h, SC.H), min(x + w, SC.W)
        ya, xa = max(y, 0), max(x, 0)   # a sprite may start above / left of the screen (Fortress tbfrdw_2_3, y -12)
        if y1 > ya and x1 > xa:
            bmask_f[ya:y1, xa:x1] |= m[ya - y:y1 - y, xa - x:x1 - x] > 0
    return cv2.dilate(bmask_f.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0


def prop_mask_rect(paint_u8: np.ndarray) -> np.ndarray:
    """Painted (non-layer) props of the rect, on the painted floor only (above it the rule also catches pale
    rock faces, which are scenery)."""
    import stronghold_full3d_terrain as T
    return M.prop_mask(paint_u8, TEX["propMask"]) & T.floor_mask()


# ================================================================================================ grade
GR_BAND_PX, GR_ANCHOR_PX = 16, 80
ROW_SIG, COL_TAU = 18.0, 260.0
GR_SEAM_IN, SEAM_SIG, SEAM_FEATHER_PX = 24, 24.0, 160.0
SEAM_CLIP = (14.0, 8.0, 8.0)
LC_SIGMAS = (1.5, 4.0, 12.0)
LC_GAIN_MAX = 1.8
NBINS = 256
RENDER_CLIP = (12.0, 6.0, 6.0)


def grade(root: Path, src: Path | None = None, out: Path | None = None, render_ref: str | None = None) -> dict:
    import stronghold_full3d_terrain as T
    g_cfg = TEX["grade"]
    FLOOR_ROWS = tuple(g_cfg["floorRows"])
    CLIFF_ROWS, FLOORZ_ROWS = g_cfg["cliffRows"], g_cfg["floorzRows"]
    SEAM_IN = GR_SEAM_IN
    BAND_PX_, ANCHOR_PX = GR_BAND_PX, GR_ANCHOR_PX
    src = src or root / "integrated"
    out = out or root / "extsrc"
    t0 = time.time()
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    cx0 = int(man["canvasX"][0])
    canvas = np.asarray(Image.open(src / man["file"]).convert("RGB"))
    H_, W_ = canvas.shape[:2]
    rect = np.zeros((H_, W_), bool); rect[:TH, -cx0:-cx0 + TW] = True
    paint = np.asarray(frame_painting())
    assert (canvas[:TH, -cx0:-cx0 + TW] == paint).all(), "the canvas rect is not the painting"

    bmask = np.zeros((H_, W_), bool); bmask[:, -cx0:-cx0 + SC.W] = building_mask_frame()
    hut = np.zeros((H_, W_), bool); hut[:TH, -cx0:-cx0 + TW] = prop_mask_rect(paint)
    sky_p = np.zeros((H_, W_), bool); sky_p[:TH, -cx0:-cx0 + TW] = T.sky_mask(paint)

    f32_ = canvas.astype(np.float32) / 255
    lab = cv2.cvtColor(f32_, cv2.COLOR_RGB2LAB)
    sky_e = M.extension_sky(lab, rect, SC.FP.SKY_MASK)
    sky_soft = cv2.GaussianBlur(sky_e.astype(np.float32), (0, 0), 2.0)
    ext = ~rect
    tgt_ok = rect & ~sky_p & ~hut & ~bmask
    src_ok = ext & ~sky_e
    print("masks: building px", int(bmask.sum()), "target px", int(tgt_ok.sum()), "source px", int(src_ok.sum()),
          round(time.time() - t0, 1), "s", flush=True)

    H, W = H_, W_  # noqa: N806  (the canvas's own size from here on)
    rows_c = np.arange(BAND_PX_ // 2, H, BAND_PX_)
    cols_c = np.arange(0, W + ANCHOR_PX, ANCHOR_PX)
    cols_c = cols_c[cols_c < W + ANCHOR_PX // 2]
    edges = [np.linspace(0, 100, NBINS + 1), np.linspace(-60, 80, NBINS + 1), np.linspace(-60, 90, NBINS + 1)]
    tq = [np.clip(np.digitize(lab[..., c], edges[c]) - 1, 0, NBINS - 1) for c in range(3)]
    yy = np.arange(H)[:, None].astype(np.float32); xx = np.arange(W)[None, :].astype(np.float32)
    LUT = np.zeros((len(rows_c), len(cols_c), 3, NBINS), np.float32)
    RB, CB = 4, 20
    nrb, ncb = (H + RB - 1) // RB, (W + CB - 1) // CB
    rcell = (np.arange(H) // RB)[:, None].repeat(W, 1); ccell = (np.arange(W) // CB)[None, :].repeat(H, 0)
    rcen = np.arange(nrb) * RB + (RB - 1) / 2; ccen = np.arange(ncb) * CB + (CB - 1) / 2

    def cell_hist(ok, c):
        idx = (rcell[ok] * ncb + ccell[ok]) * NBINS + tq[c][ok]
        return np.bincount(idx, minlength=nrb * ncb * NBINS).reshape(nrb, ncb * NBINS).astype(np.float64)

    WYt = np.zeros((len(rows_c), nrb)); WYs = np.zeros((len(rows_c), nrb))
    for i, r in enumerate(rows_c):
        if r > FLOOR_ROWS[1]:
            WYt[i] = ((rcen >= FLOOR_ROWS[0]) & (rcen <= FLOOR_ROWS[1])).astype(np.float64)
        else:
            WYt[i] = np.exp(-0.5 * ((rcen - r) / ROW_SIG) ** 2)
        WYs[i] = np.exp(-0.5 * ((rcen - r) / ROW_SIG) ** 2)
    WXt = np.exp(-np.abs((ccen[None, :] + cx0) - np.clip(cols_c[:, None] + cx0, 0, TW - 1)) / COL_TAU)
    WXs = np.exp(-np.abs(ccen[None, :] - cols_c[:, None]) / COL_TAU)
    for c in range(3):
        Ht = (WYt @ cell_hist(tgt_ok, c)).reshape(len(rows_c), ncb, NBINS)
        Hs = (WYs @ cell_hist(src_ok, c)).reshape(len(rows_c), ncb, NBINS)
        Ht = np.einsum("jk,ikb->ijb", WXt, Ht); Hs = np.einsum("jk,ikb->ijb", WXs, Hs)
        ct = np.cumsum(Ht, -1); cs = np.cumsum(Hs, -1)
        for i in range(len(rows_c)):
            for j in range(len(cols_c)):
                if ct[i, j, -1] < 1e-6 or cs[i, j, -1] < 1e-6:
                    LUT[i, j, c] = np.arange(NBINS); continue
                LUT[i, j, c] = np.interp(cs[i, j] / cs[i, j, -1], ct[i, j] / ct[i, j, -1], np.arange(NBINS))
    print("luts", round(time.time() - t0, 1), "s", flush=True)

    centers = [0.5 * (e[1:] + e[:-1]) for e in edges]
    out_lab = lab.copy()
    fi = np.clip((np.arange(H) - rows_c[0]) / BAND_PX_, 0, len(rows_c) - 1)
    fj = np.clip(np.arange(W) / ANCHOR_PX, 0, len(cols_c) - 1)
    i0 = np.floor(fi).astype(int); i1 = np.minimum(i0 + 1, len(rows_c) - 1); ti = (fi - i0)[:, None]
    j0 = np.floor(fj).astype(int); j1 = np.minimum(j0 + 1, len(cols_c) - 1); tj = (fj - j0)[None, :]
    for c in range(3):
        q = tq[c]
        v = lambda I, J: np.interp(LUT[I[:, None], J[None, :], c, q], np.arange(NBINS), centers[c])  # noqa: E731
        g = ((1 - ti) * (1 - tj) * v(i0, j0) + (1 - ti) * tj * v(i0, j1) + ti * (1 - tj) * v(i1, j0)
             + ti * tj * v(i1, j1))
        off = lab[..., c] - centers[c][q]
        out_lab[..., c] = g + off

    # local contrast per side (L / R / below) and zone (cliff / floor), L* bands, gain in [1, LC_GAIN_MAX]
    Lg = out_lab[..., 0].copy()
    if TEX["grade"].get("extOnlyBands"):
        # bands of the extension alone (normalised masked blur): the rect's edge step is not read as extension
        # detail, so the gain cannot print a halo along the seam (a painting darker than its fill at the edge)
        ef = ext.astype(np.float32)
        blur = [Lg] + [cv2.GaussianBlur(Lg * ef, (0, 0), s_) / np.maximum(cv2.GaussianBlur(ef, (0, 0), s_), 1e-3)
                       for s_ in LC_SIGMAS]
    else:
        blur = [Lg] + [cv2.GaussianBlur(Lg, (0, 0), s_) for s_ in LC_SIGMAS]
    bands = [blur[k] - blur[k + 1] for k in range(len(LC_SIGMAS))]
    Lp = lab[..., 0]
    blp = [Lp] + [cv2.GaussianBlur(Lp, (0, 0), s_) for s_ in LC_SIGMAS]
    bandp = [blp[k] - blp[k + 1] for k in range(len(LC_SIGMAS))]
    xl_, xr_ = -cx0, -cx0 + TW
    REF = {
        ("L", "cliff"): ((40, CLIFF_ROWS, xl_, xl_ + 400), (40, CLIFF_ROWS, 0, xl_)),
        ("R", "cliff"): ((40, CLIFF_ROWS, xr_ - 400, xr_), (40, CLIFF_ROWS, xr_, W)),
        ("L", "floor"): ((FLOOR_ROWS[0], FLOOR_ROWS[1], xl_, xl_ + 600), (FLOORZ_ROWS, H, 0, xl_)),
        ("R", "floor"): ((FLOOR_ROWS[0], FLOOR_ROWS[1], xr_ - 600, xr_), (FLOORZ_ROWS, H, xr_, W)),
        ("B", "floor"): ((FLOOR_ROWS[0], FLOOR_ROWS[1], xl_, xr_), (TH, H, xl_, xr_)),
    }
    gains = {}
    for key, (pb, eb) in REF.items():
        gl = []
        for k in range(len(LC_SIGMAS)):
            pm = tgt_ok[pb[0]:pb[1], pb[2]:pb[3]]
            em = src_ok[eb[0]:eb[1], eb[2]:eb[3]]
            if pm.sum() < 50 or em.sum() < 50:       # a side with no scenery to measure keeps its contrast
                gl.append(1.0); continue
            sp = bandp[k][pb[0]:pb[1], pb[2]:pb[3]][pm].std()
            se = bands[k][eb[0]:eb[1], eb[2]:eb[3]][em].std()
            gl.append(float(np.clip(sp / max(se, 1e-3), 1.0, LC_GAIN_MAX)))
        gains["/".join(key)] = [round(v, 3) for v in gl]
    print("local-contrast gains", gains, flush=True)
    zc = np.clip((yy - CLIFF_ROWS) / (FLOORZ_ROWS - CLIFF_ROWS), 0, 1)
    side_L = (xx < xl_).astype(np.float32); side_R = (xx >= xr_).astype(np.float32); side_B = 1 - side_L - side_R
    for k in range(len(LC_SIGMAS)):
        gL = (1 - zc) * gains["L/cliff"][k] + zc * gains["L/floor"][k]
        gR = (1 - zc) * gains["R/cliff"][k] + zc * gains["R/floor"][k]
        gB = np.full_like(zc, gains["B/floor"][k])
        gk = side_L * gL + side_R * gR + side_B * gB
        gk = cv2.GaussianBlur(gk.astype(np.float32), (0, 0), 24)
        out_lab[..., 0] += (gk - 1) * bands[k]

    # seam residual (painting - graded) along the rect edges, carried out with exp(-d / SEAM_FEATHER_PX)
    res = np.zeros_like(out_lab)
    xr = -cx0 + TW
    xl = -cx0
    okp = (~sky_p & ~hut & ~bmask).astype(np.float32)
    oke = (~sky_e).astype(np.float32)

    def edge_res(pa, pm, ea, em, sig):
        num_p = (pa * pm[..., None]).sum(1); den_p = pm.sum(1)[:, None]
        num_e = (ea * em[..., None]).sum(1); den_e = em.sum(1)[:, None]
        good = (den_p[:, 0] > 2) & (den_e[:, 0] > 2)
        r = np.zeros((pa.shape[0], 3), np.float32)
        r[good] = num_p[good] / den_p[good] - num_e[good] / den_e[good]
        wgt = gaussian_filter1d(good.astype(np.float32), sig, mode="nearest")
        r = gaussian_filter1d(r * good[:, None], sig, axis=0, mode="nearest") / np.maximum(wgt, 1e-3)[:, None]
        return np.clip(r, -np.array(SEAM_CLIP), np.array(SEAM_CLIP)).astype(np.float32)

    rr = edge_res(lab[:TH, xr - SEAM_IN:xr], okp[:TH, xr - SEAM_IN:xr], out_lab[:TH, xr + 1:xr + 1 + SEAM_IN],
                  oke[:TH, xr + 1:xr + 1 + SEAM_IN], SEAM_SIG)
    lr_ = edge_res(lab[:TH, xl:xl + SEAM_IN], okp[:TH, xl:xl + SEAM_IN], out_lab[:TH, xl - 1 - SEAM_IN:xl - 1],
                   oke[:TH, xl - 1 - SEAM_IN:xl - 1], SEAM_SIG)
    br = edge_res(lab[FLOOR_ROWS[1] - SEAM_IN:FLOOR_ROWS[1], xl:xr].transpose(1, 0, 2),
                  okp[FLOOR_ROWS[1] - SEAM_IN:FLOOR_ROWS[1], xl:xr].T,
                  out_lab[TH + 1:TH + 1 + SEAM_IN, xl:xr].transpose(1, 0, 2), oke[TH + 1:TH + 1 + SEAM_IN, xl:xr].T,
                  SEAM_SIG)
    wR = np.where((xx >= xr) & (yy < TH), np.exp(-(xx - xr) / SEAM_FEATHER_PX), 0.0)
    wL = np.where((xx < xl) & (yy < TH), np.exp(-(xl - 1 - xx) / SEAM_FEATHER_PX), 0.0)
    wB = np.where((yy >= TH) & (xx >= xl) & (xx < xr), np.exp(-(yy - TH) / SEAM_FEATHER_PX), 0.0)
    res += wR[..., None] * rr[np.clip(yy.astype(int), 0, TH - 1)[:, 0]][:, None, :]
    res += wL[..., None] * lr_[np.clip(yy.astype(int), 0, TH - 1)[:, 0]][:, None, :]
    res += wB[..., None] * br[np.clip(xx.astype(int) - xl, 0, TW - 1)[0]][None, :, :]
    for side, xe, col in (("R", xr, TW - 1), ("L", xl - 1, 0)):
        sel = (yy >= TH) & ((xx >= xr) if side == "R" else (xx < xl))
        d = np.hypot(np.abs(xx - xe), yy - TH)
        wc = np.where(sel, np.exp(-d / SEAM_FEATHER_PX), 0.0)
        val = 0.5 * br[col] + 0.5 * (rr[TH - 1] if side == "R" else lr_[TH - 1])
        res += wc[..., None] * val[None, None, :]
    # render-referred residual (one iteration): the lane lights the extension meshes differently from the rect, so a
    # canvas that matches the painting can still step in the render; the step left in the previous stage's rest
    # preview is added on top (building / prop / sky px excluded both sides)
    rref = None
    if render_ref:
        rf = np.asarray(Image.open(render_ref).convert("RGB")).astype(np.float32) / 255
        rl = cv2.cvtColor(rf, cv2.COLOR_RGB2LAB)
        fok = np.zeros(rl.shape[:2], np.float32)
        fok[:] = 1.0
        fok[(bmask | hut | sky_p | sky_e)[:, -cx0:-cx0 + rl.shape[1]]] = 0.0
        fx = TW
        rr2 = edge_res(rl[:TH, fx - SEAM_IN:fx], fok[:TH, fx - SEAM_IN:fx], rl[:TH, fx + 1:fx + 1 + SEAM_IN],
                       fok[:TH, fx + 1:fx + 1 + SEAM_IN], SEAM_SIG)
        br2 = edge_res(rl[FLOOR_ROWS[1] - SEAM_IN:FLOOR_ROWS[1], :TW].transpose(1, 0, 2),
                       fok[FLOOR_ROWS[1] - SEAM_IN:FLOOR_ROWS[1], :TW].T,
                       rl[TH + 1:TH + 1 + SEAM_IN, :TW].transpose(1, 0, 2), fok[TH + 1:TH + 1 + SEAM_IN, :TW].T,
                       SEAM_SIG)
        rr2 = np.clip(rr2, -np.array(RENDER_CLIP), np.array(RENDER_CLIP))
        br2 = np.clip(br2, -np.array(RENDER_CLIP), np.array(RENDER_CLIP))
        res2 = wR[..., None] * rr2[np.clip(yy.astype(int), 0, TH - 1)[:, 0]][:, None, :]
        res2 += wB[..., None] * br2[np.clip(xx.astype(int) - xl, 0, TW - 1)[0]][None, :, :]
        sel = (yy >= TH) & (xx >= xr)
        wc = np.where(sel, np.exp(-np.hypot(xx - xr, yy - TH) / SEAM_FEATHER_PX), 0.0)
        res2 += wc[..., None] * (0.5 * br2[TW - 1] + 0.5 * rr2[TH - 1])[None, None, :]
        res = res + res2
        rref = {"file": str(render_ref).replace("\\", "/"), "clip": list(RENDER_CLIP),
                "rightMeanLab": rr2.mean(0).round(2).tolist(), "bottomMeanLab": br2.mean(0).round(2).tolist()}
    out_lab = out_lab + res

    rgb = np.clip(cv2.cvtColor(out_lab.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1)
    wgt = (ext.astype(np.float32) * (1 - sky_soft))[..., None]
    res_rgb = f32_ * (1 - wgt) + rgb * wgt
    res_u8 = (res_rgb * 255 + 0.5).astype(np.uint8)
    res_u8[rect] = canvas[rect]
    res_u8[bmask] = canvas[bmask]
    assert (res_u8[rect] == canvas[rect]).all() and (res_u8[bmask] == canvas[bmask]).all()
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(res_u8).save(out / "extended_canvas.png")
    np.save(root / "masks.npy", np.stack([rect, bmask, hut, sky_p, sky_e]))
    m2 = dict(man)
    m2["file"] = "extended_canvas.png"
    m2["sha256"] = sha(out / "extended_canvas.png")
    m2["grade"] = {"from": str(src), "fromSha256": man["sha256"], "bandPx": BAND_PX_, "anchorPx": ANCHOR_PX,
                   "rowSigma": ROW_SIG, "colTau": COL_TAU, "localContrastGains": gains, "seamClip": list(SEAM_CLIP),
                   "floorRows": list(FLOOR_ROWS), "seam": [SEAM_IN, SEAM_SIG, SEAM_FEATHER_PX],
                   "skyMask": SC.FP.SKY_MASK["rule"],
                   "method": "local weighted CIELAB histogram match to the painting (sky, painted props and "
                             "building-layer footprints excluded; building footprints and the rect never written)",
                   "proofTier": "generated artifact (graded outpaint; offline)", "renderRef": rref}
    (out / "manifest.json").write_text(json.dumps(m2, indent=1), encoding="utf-8")
    print("grade done", round(time.time() - t0, 1), "s", m2["sha256"][:12], flush=True)
    return m2


# ================================================================================================ blend
BL_K, BL_E, BL_E_B = 40, 16, 8
SIG_ALONG, SIG_ACROSS = 8.0, 3.0
TONE_ROW_SIG, TONE_COLS, TONE_NEAR_TAU = 30.0, (90, 290), 150.0
TONE_CLIP = (10.0, 5.0, 5.0)
BLEND_CLIP = (25.0, 10.0, 10.0)


TONE_GAIN_SIG, TONE_GAIN_EPS, TONE_GAIN_MAX = 8.0, 0.5, 4.0   # blend toneLMode 'gain' (opt-in)


def blend(root: Path, src: Path | None = None, out: Path | None = None) -> dict:
    """Seam post-pass on the grade: (1) cliff mean-tone shift beside the side edges, faded to 0 on the floor rows
    (profile TEX['blend']['toneRows']); (2) along each rect edge the extension's anisotropic low-pass over the first
    K px is replaced by a smoothstep from the painting's edge value to its own value at depth K (detail kept)."""
    K, E, E_B = BL_K, BL_E, BL_E_B
    # profile sideEdgePx (opt-in): the side edges' painted edge value is the mean of the painting's last sideEdgePx
    # columns instead of BL_E. Necropolis rows 80-150: the painted cliff ends in a 5 px dark crease (L* 14 -> 4.3 at
    # x = TW - 1) that the bridge continues; over 16 px the edge mean (~12) lifted the continuation to L* 15 beside it.
    if "sideEdgePx" in TEX["blend"]:
        E = TEX["blend"]["sideEdgePx"]
        if not isinstance(E, int) or not 1 <= E <= BL_E:
            raise SystemExit(f"blend: sideEdgePx {E!r} is not an int in 1..{BL_E}")
    TONE_ROWS = tuple(TEX["blend"]["toneRows"])
    src = src or root / "extsrc"
    out = out or root / "extsrc_blend"
    t0 = time.time()
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    canvas = np.asarray(Image.open(src / man["file"]).convert("RGB"))
    H_, W_ = canvas.shape[:2]
    rect, bmask, hut, sky_p, sky_e = np.load(root / "masks.npy")
    ys, xs = np.nonzero(rect)
    TH_, xl, xr = ys.max() + 1, xs.min(), xs.max() + 1
    lab = cv2.cvtColor(canvas.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    if TEX["blend"].get("skyFromSource", False):
        # profile-gated: the extension sky is re-derived (profile SKY_MASK["extension"]) on this blend's own input.
        # masks.npy holds the grade's sky, measured before the bridge; a bridge with writeSky moves the skyline, so the
        # stale mask handed the bridge's new sky to the tone / edge corrections as ground (Necropolis x 1440-1520,
        # rows 0-220: per-row shifts drew horizontal blocks into the bridged sky).
        sky_e = M.extension_sky(lab, rect, SC.FP.SKY_MASK)
    okp = rect & ~bmask & ~hut & ~sky_p
    oke = ~rect & ~bmask & ~sky_e
    # profile writeExtBuildingMask (as in TEX["bridge"]): the building mask's dilation margin past the rect (<= 3 px)
    # takes the tone and edge corrections too; the terrain shows it once EDGE_FRAY cuts the building back, and left
    # at the bridge's value it is a 3 px strip beside the corrected extension (Dungeon rows 0-100: L* 1.6 vs 0.7).
    # Statistics stay on oke; the building mask inside the rect is never written.
    okw = (oke | (bmask & ~rect & ~sky_e)) if TEX["blend"].get("writeExtBuildingMask", False) else oke
    # profile edgeSource 'paintedAll': the side edge blend's painted edge value comes from every painted pixel but
    # the hut props and the painted sky, building layers included, since the viewer sees the painting there either
    # way (a building mesh textured with it, or the terrain once EDGE_FRAY cuts it back). Default: plain ground only,
    # which leaves rows whose edge is a building unblended (Dungeon rows 40-100: the Dragon Cave's painted near-black
    # backdrop L* 0.6-0.9 against a flat L* 0.0-0.2 extension).
    oke_src = TEX["blend"].get("edgeSource")
    if oke_src not in (None, "paintedAll"):
        raise SystemExit(f"blend: edgeSource {oke_src!r} is not 'paintedAll'")
    okp_edge = (rect & ~hut & ~sky_p) if oke_src == "paintedAll" else okp
    # profile sideEdgeSky (opt-in): the side edge blend takes the sky too, painted (sky_p, hut props still out) and
    # extension (sky_e within the K-px band beside each side edge, rows < TH), and writes that band's extension sky.
    # Default: the sky is neither measured nor written, which leaves a bridged sky's small tone step at x = TW on a
    # smooth sky, where the scale-free seam line reads it large (Cove rows 20-40: RGB 47/42/57 painted against
    # 54/46/63 bridged, ratio 5-8 at a 3 L*ab step). The rect and the building mask are still never written.
    side_sky = TEX["blend"].get("sideEdgeSky", False)
    if not isinstance(side_sky, bool):
        raise SystemExit(f"blend: sideEdgeSky {side_sky!r} is not a bool")
    okw_side = okw | (~rect & sky_e & ~bmask) if side_sky else okw
    okp_side = okp_edge | (rect & sky_p & ~hut & ~bmask) if side_sky else okp_edge
    diag = {"rectRowsCols": [int(TH_), int(xl), int(xr)]}

    def mmean_rows(a, m, y0, y1, x0, x1, sig):
        s = (a[y0:y1, x0:x1] * m[y0:y1, x0:x1, None]).sum(1)
        n = m[y0:y1, x0:x1].sum(1).astype(np.float32)
        s = gaussian_filter1d(s, sig, axis=0, mode="nearest"); n = gaussian_filter1d(n, sig, mode="nearest")
        return s / np.maximum(n, 1e-3)[:, None], n

    tone = np.zeros_like(lab)
    rows = np.arange(TH_)
    rw = np.clip((TONE_ROWS[1] - rows) / (TONE_ROWS[1] - TONE_ROWS[0]), 0, 1)
    diag["tone"] = {}

    def side_shift(side, cols_w):
        if side == "R":
            p, np_ = mmean_rows(lab, okp, 0, TH_, xr - cols_w, xr, TONE_ROW_SIG)
            e, ne = mmean_rows(lab, oke, 0, TH_, xr, xr + cols_w, TONE_ROW_SIG)
        else:
            p, np_ = mmean_rows(lab, okp, 0, TH_, xl, xl + cols_w, TONE_ROW_SIG)
            e, ne = mmean_rows(lab, oke, 0, TH_, xl - cols_w, xl, TONE_ROW_SIG)
        d = np.clip(p - e, -np.array(TONE_CLIP), np.array(TONE_CLIP)) * rw[:, None]
        low = (np_ < 20) | (ne < 20)
        if TEX["blend"].get("lowCountRows") == "interp" and (~low).any():
            # profile-gated: a row with too few samples on either side (the extension's sky above the skyline, a
            # building on the painting's edge) takes the shift interpolated from its valid neighbours (nearest past
            # the ends) instead of 0: the shift runs across the whole extension, so a 0 row band ends in a hard
            # horizontal line on the far rock (Bulwark: L* steps 4.9 / 9.5 at canvas rows 135 / 327)
            ok = np.nonzero(~low)[0]
            d = np.stack([np.interp(np.arange(len(d)), ok, d[ok, c]) for c in range(d.shape[1])], -1)
        else:
            d[low] = 0
        return d

    for side in ("R", "L"):
        dn, dfar = side_shift(side, TONE_COLS[0]), side_shift(side, TONE_COLS[1])
        dx = (np.arange(xr, W_) - xr) if side == "R" else (xl - 1 - np.arange(0, xl))
        wn = np.exp(-dx / TONE_NEAR_TAU)[None, :, None]
        sh = dfar[:, None, :] + (dn - dfar)[:, None, :] * wn
        if side == "R":
            tone[:TH_, xr:] = sh
        else:
            tone[:TH_, :xl] = sh
        diag["tone"][side] = {"nearShiftLabRows0_440": dn[:440].mean(0).round(2).tolist(),
                              "regionalShiftLabRows0_440": dfar[:440].mean(0).round(2).tolist()}
    lab1 = lab + tone * okw[..., None]
    if TEX["blend"].get("toneLMode") == "gain":
        # profile-gated: L* takes the tone shift as a gain on the local extension mean (low-passed over oke), so a
        # darkening shift keeps the rock's texture instead of clipping it to L* 0 (Dungeon rows 40-80 beside the
        # Dragon Cave's near-black backdrop: the additive shift left a flat L* 0.0 band against the painting's 0.5-0.7,
        # a seam-line step with no texture to hide it). Mean-equivalent to the additive shift where it does not clip.
        mw = gaussian_filter(oke.astype(np.float32), TONE_GAIN_SIG, mode="nearest")
        mL = gaussian_filter(lab[..., 0] * oke, TONE_GAIN_SIG, mode="nearest") / np.maximum(mw, 1e-4)
        gain = np.clip((mL + tone[..., 0]) / np.maximum(mL, TONE_GAIN_EPS), 0.0, TONE_GAIN_MAX)
        lab1[..., 0] = np.where(okw, lab[..., 0] * gain, lab1[..., 0])
        diag["toneLGain"] = {"sig": TONE_GAIN_SIG, "eps": TONE_GAIN_EPS, "max": TONE_GAIN_MAX,
                             "gainP5P50P95": np.percentile(gain[okw & (np.abs(tone[..., 0]) > 0)], [5, 50, 95])
                             .round(3).tolist() if (okw & (np.abs(tone[..., 0]) > 0)).any() else None}

    def lowpass(a, m, sig_y, sig_x):
        n = gaussian_filter(m.astype(np.float32), (sig_y, sig_x), mode="nearest")
        o = np.stack([gaussian_filter(a[..., c] * m, (sig_y, sig_x), mode="nearest") for c in range(3)], -1)
        return o / np.maximum(n, 1e-4)[..., None], n

    corr = np.zeros_like(lab1)
    sm = lambda t: t * t * (3 - 2 * t)  # noqa: E731
    wk = sm(np.clip(np.arange(K + 1) / K, 0, 1))
    for side in ("R", "L"):
        x0, x1 = (xr - E - 4, xr + K + 6) if side == "R" else (xl - K - 6, xl + E + 4)
        sub = lab1[:TH_, x0:x1]; me = okw_side[:TH_, x0:x1]
        lp_e, n_e = lowpass(sub, me, SIG_ALONG, SIG_ACROSS)
        if side == "R":
            pe, npe = mmean_rows(lab1, okp_side, 0, TH_, xr - E, xr, SIG_ALONG)
            cols = [xr + k for k in range(K + 1)]
        else:
            pe, npe = mmean_rows(lab1, okp_side, 0, TH_, xl, xl + E, SIG_ALONG)
            cols = [xl - 1 - k for k in range(K + 1)]
        far = lp_e[:, cols[K] - x0]
        good = (npe > 1.0) & (n_e[:, cols[0] - x0] > 0.3) & (n_e[:, cols[K] - x0] > 0.3)
        for k, c in enumerate(cols[:K]):
            tgt = pe * (1 - wk[k]) + far * wk[k]
            dlt = np.clip(tgt - lp_e[:, c - x0], -np.array(BLEND_CLIP), np.array(BLEND_CLIP))
            corr[:TH_, c] = np.where(good[:, None], dlt, 0)
        diag[f"edge{side}"] = {"rowsBlended": int(good.sum()),
                               "stepBeforeLab": np.abs((pe - lp_e[:, cols[0] - x0])[good]).mean(0).round(2).tolist()}
    # profile bottomSourceHut (opt-in): the bottom edge blend's painted edge value and the bottomMirrorPx source take
    # the hut-prop mask's pixels too. The viewer sees the painting above y = TH either way, and a propMask whose hue
    # rule also takes painted ground leaves those columns unblended (Tower: the tan gravel plaza and the pool's rocks
    # read as props over cols 40-285, 981-1050 and 1183-1221 of the last rows, sky_v1 / tw_v2_edge y = TH run 162-246
    # where the pale snowfield fill meets them). The hut props are still never written and stay out of every statistic.
    b_hut = TEX["blend"].get("bottomSourceHut", False)
    if not isinstance(b_hut, bool):
        raise SystemExit(f"blend: bottomSourceHut {b_hut!r} is not a bool")
    okp_b = (okp | (rect & hut & ~bmask & ~sky_p)) if b_hut else okp
    y0b = TH_ - E_B - 4
    y1b = TH_ + K + 6
    sub = lab1[y0b:y1b, xl:xr]; me = okw[y0b:y1b, xl:xr]
    lp_e, n_e = lowpass(sub, me, SIG_ACROSS, SIG_ALONG)
    pe_s = (lab1[TH_ - E_B:TH_, xl:xr] * okp_b[TH_ - E_B:TH_, xl:xr, None]).sum(0)
    pe_n = okp_b[TH_ - E_B:TH_, xl:xr].sum(0).astype(np.float32)
    pe_s = gaussian_filter1d(pe_s, SIG_ALONG, axis=0, mode="nearest")
    pe_n = gaussian_filter1d(pe_n, SIG_ALONG, mode="nearest")
    pe = pe_s / np.maximum(pe_n, 1e-3)[:, None]
    far = lp_e[TH_ + K - y0b]
    good = (pe_n > 1.0) & (n_e[TH_ - y0b] > 0.3) & (n_e[TH_ + K - y0b] > 0.3)
    for k in range(K):
        tgt = pe * (1 - wk[k]) + far * wk[k]
        dlt = np.clip(tgt - lp_e[TH_ + k - y0b], -np.array(BLEND_CLIP), np.array(BLEND_CLIP))
        corr[TH_ + k, xl:xr] = np.where(good[:, None], dlt, 0)
    diag["edgeB"] = {"colsBlended": int(good.sum()),
                     "stepBeforeLab": np.abs((pe - lp_e[TH_ - y0b])[good]).mean(0).round(2).tolist()}
    corr[:TH_] = gaussian_filter1d(corr[:TH_], 1.0, axis=0)
    corr[TH_:TH_ + K] = gaussian_filter1d(corr[TH_:TH_ + K], 1.0, axis=1)

    wside = np.zeros_like(okw)
    if side_sky:
        wside[:TH_, xr:xr + K] = True
        wside[:TH_, max(xl - K, 0):xl] = True
        wside &= okw_side & ~okw
    out_lab = lab1 + corr * (okw | wside)[..., None]
    mir = int(TEX["blend"].get("bottomMirrorPx", 0))
    if mir > 0:
        # profile-gated: the extension's first `mir` rows below the rect crossfade (smoothstep) from the painting's
        # rows mirrored about y = TH to their own values (source and target masks below). The low-pass pass above
        # only matches tone; Dungeon's painted floor ends
        # in a dark featureless strip against the fill's lit stones, a texture step the tone match cannot remove
        # (seamLine y673 5.4 with the strip already in the canvas before any frays).
        # Source: every painted pixel except the hut props and the painted sky, building-mask pixels included: a
        # building layer that reaches the bottom is cut back by EDGE_FRAY_BOTTOM, so what the terrain shows above
        # y = TH there is this canvas (Dungeon: the dilated mask covers the floor's last rows at x 1170-1390).
        # Target: the extension's ground plus the building mask's dilation margin past the rect (<= 3 px), which the
        # terrain shows once the fray cuts the building back; the building mask inside the rect is never written.
        src_m = (rect & ~sky_p) if b_hut else (rect & ~hut & ~sky_p)
        tgt_m = ~rect & ~sky_e
        wm = sm((np.arange(mir) + 0.5) / mir)
        nmir = 0
        for k in range(mir):
            yp, ye = TH_ - 1 - k, TH_ + k
            if yp < 0 or ye >= H_:
                break
            m = src_m[yp, xl:xr] & tgt_m[ye, xl:xr]
            row = out_lab[ye, xl:xr]
            row[m] = lab[yp, xl:xr][m] * (1 - wm[k]) + row[m] * wm[k]
            nmir += int(m.sum())
        diag["bottomMirror"] = {"px": mir, "rows": [int(TH_), int(min(TH_ + mir, H_))], "pixels": nmir}
    rmir = TEX["blend"].get("rightMirrorPx", 0)
    wrm = np.zeros_like(okw)
    if rmir:
        # profile-gated: the extension's first `rmir` columns right of x = TW crossfade (smoothstep) from the painting's
        # columns mirrored about x = TW to their own values, rows 0..TH-1, as bottomMirrorPx does below the rect. The
        # edge blend above is a low-pass (sigma 8 rows along the edge) and cannot follow a painted feature a few rows
        # tall that ends at the edge (Cove: the peak's red rim at rows 238-250, RGB ~230/122/91 against the bridge's
        # ~180/120/100; the Grail plume's lit edge at rows 160-180), a step the scale-free seam line reads at 4-11.
        # Source: every painted pixel but the hut props, building-mask and painted sky included (EDGE_FRAY cuts the
        # building layers back from the edge, so what the terrain and the dome show there is this canvas). Target:
        # the extension's ground, its sky and the building mask's margin past the rect; the rect is never written.
        if not isinstance(rmir, int) or not 1 <= rmir <= K:
            raise SystemExit(f"blend: rightMirrorPx {rmir!r} is not an int in 1..{K}")
        # profile rightMirrorMode (opt-in): "reflect" (default) is the crossfade above; "offset" instead shifts the
        # extension's own columns by the per-row step between the painting's last two columns and its first two
        # (rows smoothed with sigma 1.5), fading to 0 over the same smoothstep, so the edge meets the painting without
        # any painted texel being copied across it (Dungeon: the painting's darker column at x 1436-1437, reflected to
        # 1442-1443, read as a symmetric zipper the height of the cave wall)
        mode = TEX["blend"].get("rightMirrorMode", "reflect")
        if mode not in ("reflect", "offset"):
            raise SystemExit(f"blend: rightMirrorMode {mode!r} is not 'reflect' / 'offset'")
        src_r = rect & ~hut
        tgt_r = ~rect
        wmr = sm((np.arange(rmir) + 0.5) / rmir)
        nrm = 0
        if mode == "offset":
            ps, pt = src_r[:TH_, xr - 2:xr].all(1), tgt_r[:TH_, xr:xr + 2].all(1)
            ok_r = ps & pt
            d = np.where(ok_r[:, None], lab[:TH_, xr - 2:xr].mean(1) - out_lab[:TH_, xr:xr + 2].mean(1), 0)
            wn = gaussian_filter1d(ok_r.astype(np.float32), 1.5, mode="nearest")
            d = gaussian_filter1d(d, 1.5, axis=0, mode="nearest") / np.maximum(wn, 1e-3)[:, None]
        for k in range(rmir):
            xp, xe = xr - 1 - k, xr + k
            if xp < xl or xe >= W_:
                break
            col = out_lab[:TH_, xe]
            if mode == "offset":
                m = ok_r & tgt_r[:TH_, xe]
                col[m] = col[m] + d[m] * (1 - wmr[k])
            else:
                m = src_r[:TH_, xp] & tgt_r[:TH_, xe]
                col[m] = lab[:TH_, xp][m] * (1 - wmr[k]) + col[m] * wmr[k]
            out_lab[:TH_, xe] = col
            wrm[:TH_, xe] = m
            nrm += int(m.sum())
        diag["rightMirror"] = {"px": rmir, "mode": mode, "cols": [int(xr), int(min(xr + rmir, W_))], "pixels": nrm}
    rgb = np.clip(cv2.cvtColor(out_lab.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1)
    res = canvas.copy()
    wr = okw | wside | wrm
    if mir > 0:
        wr[TH_:TH_ + mir] |= tgt_m[TH_:TH_ + mir]
    res[wr] = (rgb[wr] * 255 + 0.5).astype(np.uint8)
    assert (res[rect] == canvas[rect]).all() and (res[bmask & ~wr] == canvas[bmask & ~wr]).all() \
        and (res[sky_e & ~wside & ~wrm] == canvas[sky_e & ~wside & ~wrm]).all() and not (wr & bmask & rect).any()
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(res).save(out / "extended_canvas.png")
    m2 = dict(man)
    m2["sha256"] = sha(out / "extended_canvas.png")
    m2["blend"] = {"from": str(src / man["file"]), "fromSha256": man["sha256"], "K": K, "E": E, "E_B": E_B,
                   "sigAlongAcross": [SIG_ALONG, SIG_ACROSS], "toneRowSig": TONE_ROW_SIG,
                   "toneCols": list(TONE_COLS), "toneNearTau": TONE_NEAR_TAU, "toneRows": list(TONE_ROWS),
                   "toneClip": list(TONE_CLIP), "blendClip": list(BLEND_CLIP),
                   "method": "cliff mean-tone shift beside the side edges + low-pass-only edge blend (detail kept); "
                             "rect, building mask and extension sky never written",
                   "proofTier": "generated artifact (offline)"}
    for key in ("bottomMirrorPx", "writeExtBuildingMask", "edgeSource", "toneLMode", "skyFromSource", "sideEdgePx",
                "sideEdgeSky", "rightMirrorPx", "bottomSourceHut", "rightMirrorMode"):
        if TEX["blend"].get(key):
            m2["blend"][key] = TEX["blend"][key]
    (out / "manifest.json").write_text(json.dumps(m2, indent=1), encoding="utf-8")
    (root / "blend_report.json").write_text(json.dumps(diag, indent=1), encoding="utf-8")
    print("blend changed px", int((res != canvas).any(-1).sum()), round(time.time() - t0, 1), "s", flush=True)
    return m2


# ================================================================================================ bridge context
def bridge_context(root: Path) -> dict:
    """<root>/bridge_context.png (TW x TH): the painting as the SD bridge's left context (town_full3d_sdfill --step
    bridge, profile TEX["bridge"]["rectContext"] == "housesCarved") with the modelled houses' carve (TOWN_FULL3D_HOUSES)
    replaced by the carved background, i.e. what the terrain shows under the cabins, so the bridge does not continue
    a painted hut the cabins already model. Context only: the bridge never writes the rect."""
    import town_full3d_houses as HS
    cm = HS.carve_mask()
    bg = HS.carved_background()
    if cm is None or bg is None:
        raise SystemExit("bridge-context: TOWN_FULL3D_HOUSES is not set (the context is the houses' carve)")
    paint = np.asarray(frame_painting().convert("RGB")).copy()
    carved = np.asarray(bg.resize((TW, TH), Image.LANCZOS))
    m = cm[:TH, :TW]
    paint[m] = carved[m]
    Image.fromarray(paint).save(root / "bridge_context.png")
    rep = {"schema": "town_full3d_bridge_context.v1", "faction": SC.FACTION, "file": "bridge_context.png",
           "sha256": sha(root / "bridge_context.png"), "size": [TW, TH], "carvedPx": int(m.sum()),
           "houses": [str(d) for d in HS.houses_dirs()], "proofTier": "generated artifact (offline)"}
    (root / "bridge_context.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


# ================================================================================================ deliver
POSES = ("default", "sweep_left", "sweep_right", "sweep_high", "cursor_left", "cursor_right")


def seam_metrics(preview: Path) -> dict:
    """Frame-extension seam and texture statistics on a rest render (moved from the Stronghold seam_measure.py).
      seamStep  the colour step across x=TW (rows 180..TH-23) and y=TH (cols 40..TW-40): mean CIELAB distance between
                the pixels 3 px either side, over the median of the same measure at control lines 20..80 px away on
                both sides (1.0 = the seam line is as strong as ordinary texture)
      bands     std of log(lum / blurred lum) at sigma 2 / 6 / 20 px in the profile's CONTRAST_REGIONS (painting box,
                extension box) and their ratio ext/paint (1.0 = the same grain at that scale); lab mean / std there"""
    img = np.asarray(Image.open(preview).convert("RGB"))
    L = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    Lv = cv2.GaussianBlur(L, (1, 25), sigmaX=0, sigmaY=4)
    Lh = cv2.GaussianBlur(L, (25, 1), sigmaX=4, sigmaY=0)
    rows, cols = np.arange(180, TH - 23), np.arange(40, TW - 40)

    def sx(x):
        return float(np.linalg.norm(Lv[rows, x - 3] - Lv[rows, x + 2], axis=-1).mean())

    def sy(y):
        return float(np.linalg.norm(Lh[y - 3, cols] - Lh[y + 2, cols], axis=-1).mean())
    ctl = list(range(-80, -19, 10)) + list(range(20, 81, 10))
    ax, ay = sx(TW), sy(TH)
    out = {"seamStep": {f"x{TW}": round(ax / float(np.median([sx(TW + d) for d in ctl])), 3),
                        f"y{TH}": round(ay / float(np.median([sy(TH + d) for d in ctl])), 3),
                        f"x{TW}Abs": round(ax, 2), f"y{TH}Abs": round(ay, 2)}, "regions": {}}
    lum = ((img.astype(np.float32) / 255) ** 2.2).mean(-1)
    q = {sg: np.log(np.maximum(lum, 1e-4)) - np.log(np.maximum(cv2.GaussianBlur(lum, (0, 0), sg), 1e-4))
         for sg in (2, 6, 20)}
    for name, boxes in SC.FP.CONTRAST_REGIONS.items():
        r = {}
        for side, (x0, y0, x1, y1) in zip(("paint", "ext"), boxes):
            box = L[y0:y1, x0:x1].reshape(-1, 3)
            r[side] = {"bands": [round(float(q[sg][y0:y1, x0:x1].std()), 3) for sg in (2, 6, 20)],
                       "labMean": [round(float(v), 1) for v in box.mean(0)],
                       "labStd": [round(float(v), 1) for v in box.std(0)]}
        r["bandRatio"] = [round(e / max(p_, 1e-6), 3) for e, p_ in zip(r["ext"]["bands"], r["paint"]["bands"])]
        out["regions"][name] = r
    out["seamLine"] = seam_line(L)
    return out


# seam-line gate (2026-09-28): the mean seamStep above averaged a straight step at the rect's right edge away (Dungeon
# fx_v1 1.169 with a hard vertical line from the top of the frame to y ~660 in its 4K rest render). A seam is a STRAIGHT
# line on the rect edge, so it is measured per row against the same row's nearby columns (x +- 6..16) and judged by how
# far it runs. Calibrated 2026-09-28 (town_all/seam_probe/seam_line.py) on the rest previews and 4K renders of Dungeon,
# Cove, Bulwark, Fortress, Factory candidates and the 09-27 Stronghold render: at x = TW p90 6.8..16.5 and runs of
# 160..378 rows; interior columns (x 300 / 600 / 900 / 1200 / 1650) p90 1.4..3.2 and runs 11..79 (one outlier: Factory
# x 300, p90 5.19 run 176, a painted vertical, not a rect edge). Bottom edge (y = TH) on the same previews: p90
# 2.6..5.4, runs 90..220 (Cove / Bulwark pass, Dungeon / Fortress / Factory fail); interior rows (y 200..950) p90
# 1.2..3.1 and runs 7..101, with one painted horizon (Cove y 200: p90 4.29, run 106), so the bottom-edge limits sit
# closer to ordinary texture than the side's and a failure there is to be confirmed by eye on the rest render.
LINE_P90_MAX = 3.5        # p90 over the edge of the smoothed line ratio
LINE_RUN_MAX = 100        # longest run (rows / cols) with the ratio over LINE_RATIO_ON
LINE_RATIO_ON = 1.6
LINE_SMOOTH = 15


def _line_profile(Lb: np.ndarray, pos: int, span: np.ndarray, axis: int) -> np.ndarray:
    """Smoothed ratio of the 3-px step across line `pos` over the median step at pos +- 6..16, along `span`."""
    def st(c):
        if axis == 1:    # vertical line at column c, one value per row in span
            return np.linalg.norm(Lb[span, c - 2] - Lb[span, c + 1], axis=-1)
        return np.linalg.norm(Lb[c - 2, span] - Lb[c + 1, span], axis=-1)
    ctl = np.median(np.stack([st(pos + d) for d in list(range(-16, -5)) + list(range(6, 17))]), 0)
    k = np.ones(LINE_SMOOTH) / LINE_SMOOTH
    return np.convolve(st(pos), k, mode="same") / np.maximum(np.convolve(ctl, k, mode="same"), 0.3)


def seam_line(L: np.ndarray) -> dict:
    """Straight-line seam test on the rect's right edge (x = TW, rows 0..TH-23) and bottom edge (y = TH, cols
    40..TW-40); {"x<TW>": {p90, runRows}, "y<TH>": {p90, runCols}, "pass": bool, "limits": ...}."""
    out = {}
    for key, pos, span, axis in ((f"x{TW}", TW, np.arange(0, TH - 23), 1), (f"y{TH}", TH, np.arange(40, TW - 40), 0)):
        Lb = cv2.GaussianBlur(L, (1, 9), sigmaX=0, sigmaY=1.5) if axis == 1 else \
            cv2.GaussianBlur(L, (9, 1), sigmaX=1.5, sigmaY=0)
        r = _line_profile(Lb, pos, span, axis)
        run = cur = 0
        for v in r > LINE_RATIO_ON:
            cur = cur + 1 if v else 0
            run = max(run, cur)
        out[key] = {"p90": round(float(np.percentile(r, 90)), 3), "run": int(run),
                    "pass": bool(np.percentile(r, 90) <= LINE_P90_MAX and run <= LINE_RUN_MAX)}
    out["pass"] = all(v["pass"] for v in out.values())
    out["limits"] = {"p90Max": LINE_P90_MAX, "runMax": LINE_RUN_MAX, "ratioOn": LINE_RATIO_ON}
    return out


def deliver(root: Path, before: str, after: str, out: Path) -> dict:
    """Mask viz; building-pixel diff between two candidates' previews (the building-layer and painted-prop footprint
    at the rest pose must not change); painting | before | after sheet of the six poses (rest crops + full frames)."""
    out.mkdir(parents=True, exist_ok=True)
    rect, bmask, hut, sky_p, sky_e = np.load(root / "masks.npy")
    man = json.loads((root / "extsrc" / "manifest.json").read_text(encoding="utf-8"))
    cx0 = man["canvasX"][0]
    canvas = np.asarray(Image.open(root / "extsrc" / "extended_canvas.png").convert("RGB"))
    v = canvas.astype(np.float32) * 0.55
    graded = ~rect & ~bmask & ~sky_e
    v[graded] = v[graded] * 0.6 + np.array([255, 200, 0]) * 0.4
    v[bmask] = np.array([255, 0, 255])
    v[hut] = np.array([0, 255, 255])
    v[sky_p | sky_e] = v[sky_p | sky_e] * 0.5 + np.array([0, 80, 255]) * 0.5
    im = Image.fromarray(v.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle((-cx0, 0, -cx0 + TW - 1, TH - 1), outline=(255, 255, 255), width=3)
    d.text((10, H - 30), f"{SC.FP.LABEL}: orange=graded extension  magenta=building layers (native_mask, 7x7 dil)  "
           f"cyan=painted props (never graded)  blue=sky ({SC.FP.SKY_MASK['rule']})  white=painting rect",
           fill=(255, 255, 255))
    im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(out / "masks_viz.png")
    C = SC.DATA / "candidates"
    fb = bmask[:, -cx0:-cx0 + W] | hut[:, -cx0:-cx0 + W]
    rep = {"before": before, "after": after, "previews": {}}
    for pose in POSES:
        pa, pb = C / before / "work/preview" / f"{pose}.png", C / after / "work/preview" / f"{pose}.png"
        if not (pa.exists() and pb.exists()):
            rep["previews"][pose] = {"missing": [str(p) for p in (pa, pb) if not p.exists()]}
            continue
        a = np.asarray(Image.open(pa).convert("RGB")).astype(int)
        b = np.asarray(Image.open(pb).convert("RGB")).astype(int)
        dd = np.abs(a - b).max(-1)
        r = {"changedPx": int((dd > 0).sum()), "maxAbs": int(dd.max())}
        if pose == "default":
            r.update(buildingFootprintPx=int(fb.sum()), maxAbsInBuildingFootprint=int(dd[fb].max()),
                     changedPxInBuildingFootprint=int((dd[fb] > 0).sum()),
                     changedPxInRect=int((dd[:TH, :TW] > 0).sum()))
            hm = np.dstack([np.clip(dd * 8, 0, 255)] * 3).astype(np.uint8)
            hm[fb & (dd == 0)] = (90, 0, 90)
            Image.fromarray(hm).save(out / "building_diff_default.png")
        rep["previews"][pose] = r
    (out / "building_diff.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    seams = {k: {"candidate": c, **seam_metrics(C / c / "work/preview" / "default.png")}
             for k, c in (("before", before), ("after", after)) if (C / c / "work/preview" / "default.png").exists()}
    (out / "seam_metrics.json").write_text(json.dumps(seams, indent=1), encoding="utf-8")
    # painting | before | after, one row per pose, full frames at 1/3
    paint = Image.new("RGB", (W, H), (128, 128, 128))
    paint.paste(frame_painting(), (0, 0))
    CW = W // 3
    rows = []
    for pose in POSES:
        cells = []
        for lab_, cand in (("painting", None), ("before " + before, before), ("after " + after, after)):
            p = None if cand is None else C / cand / "work/preview" / f"{pose}.png"
            img = paint if cand is None else (Image.open(p).convert("RGB") if p.exists()
                                             else Image.new("RGB", (W, H), (40, 40, 40)))
            c = Image.new("RGB", (CW, H // 3 + 18), (20, 20, 20))
            c.paste(img.resize((CW, H // 3), Image.LANCZOS), (0, 18))
            ImageDraw.Draw(c).text((4, 3), f"{pose} | {lab_}" + (" (rest frame)" if cand is None else ""),
                                   fill=(255, 255, 255))
            cells.append(c)
        rows.append(cells)
    sheet = Image.new("RGB", (CW * 3 + 8, sum(r[0].height + 6 for r in rows)), (60, 60, 60))
    y = 0
    for r in rows:
        for i, c in enumerate(r):
            sheet.paste(c, (i * (CW + 4), y))
        y += r[0].height + 6
    sheet.save(out / "painting_before_after.png")
    # seam-line gate: the delivered candidate's rest preview must show no straight step on the rect edges
    sl = seams.get("after", {}).get("seamLine")
    rep["seamLineGate"] = {"after": after, "seamLine": sl, "pass": bool(sl and sl["pass"])}
    return rep


# ================================================================================================ CLI
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=SC.FACTION)
    ap.add_argument("step", choices=["kit", "integrate", "grade", "bridge-context", "blend", "deliver"])
    ap.add_argument("--root", default="", help="output root (default artifacts/<DATA_DIR>/tex)")
    ap.add_argument("--src", default="", help="step input dir (default: the previous step's output under --root)")
    ap.add_argument("--out", default="", help="step output dir")
    ap.add_argument("--render-ref", default="", help="grade: rest preview of the previous grade's stage")
    ap.add_argument("--before", default="", help="deliver: candidate compared against")
    ap.add_argument("--after", default="", help="deliver: candidate delivered")
    a = ap.parse_args()
    root = Path(a.root) if a.root else default_root()
    src = Path(a.src) if a.src else None
    out = Path(a.out) if a.out else None
    if a.step == "kit":
        m = kit(root)
        print(json.dumps({k: v["sha256"][:12] for k, v in m["jobs"].items()}))
    elif a.step == "integrate":
        m = integrate(root, src, out)
        print(json.dumps({k: {x: v[x] for x in ("ecc", "bandDeltaEAfter")} for k, v in m["jobs"].items()}),
              m["sha256"][:12])
    elif a.step == "grade":
        grade(root, src, out, a.render_ref or None)
    elif a.step == "bridge-context":
        print(json.dumps(bridge_context(root)))
    elif a.step == "blend":
        blend(root, src, out)
    else:
        rep = deliver(root, a.before, a.after, out or root / "deliver")
        print(json.dumps(rep, indent=1))
        if not rep["seamLineGate"]["pass"]:
            print(f"deliver: SEAM LINE GATE FAILED for {a.after}: {json.dumps(rep['seamLineGate']['seamLine'])} "
                  f"(a straight step on the rect edge; not deliverable)")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
