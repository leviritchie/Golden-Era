"""town_full3d_upscale.py: faithful hi-res albedo for a staged full-3D town candidate, whatever lane built it.

Every lane stages its meshes through `add_bin` (rows.json bins with a `<prefab>/<name>_albedo.png` texture and a
`maxSize`), so one pass over the staged rows lifts the whole scene without rebuilding anything: UVs are unchanged
because each texture is the same image at a higher resolution.

Per texture (bins of kind lit / sky; fx atlases are left alone):
  1. RGBA: RGB alpha-bled outward (TELEA) so no dark halo is upscaled into the cutout edge
  2. pre-downscale (INTER_AREA) to the texture's real detail, so the network starts from the painting's own pixels
     rather than interpolation blur. `--pre auto`: a building bin's albedo is the frame sprite resampled by its
     stage-report texelsPerPx (texels per frame px, typically 2), so that is its factor -- not x SC.SCALE down to the
     native sprite: the frame sprite's LANCZOS x1.8 keeps the painted detail (castle tavern roof tiles survive at
     pre 2, average away at pre 3.6 and the network invents planks; upscale/test/tvrn_pres.jpg); any bin also takes
     the largest f in PRE_STEPS whose down-and-back-up (area / cubic) round trip keeps PSNR >= --pre-psnr dB on every
     detailed tile of a 3x3 spread (the most detailed tile decides); a texture whose net gain would fall under
     --min-gain is left as it is
     (resampled terrain / sky plates)
  3. 0.55 px Gaussian pre-soften (the raw upscale turns HoMM3 dither into grain; tower ns2 up/cmp_upscale.jpg)
  4. Kokon /upscale x4 (4x_NMKD-Superscale-SP, steps 0: a network, not diffusion -- no new content)
  5. resized to the target: source size x min(4 / pre, --max-gain), capped so the longest side is <= --cap; alpha (if any) from the
     source alpha resized cubic
The bin's `maxSize` becomes the power of two that holds the new size (<= --cap) and the bin is marked
`upscaled: {"from": [w, h], "pre": .., "net": ..}`; marked bins are skipped, so the pass is idempotent. Textures whose
net gain would be under --min-gain are skipped (already at the --cap 8192), and so are building/prop textures of
--atlas-max (2048) px or more: mesh UV atlases already finer than the screen. Every file is unlinked before it is written
(candidates seeded with `cp -al` share files with their parent).

GPU: Kokon runs inside town_full3d_gpu.gate. Kokon is the user's local service (KOKON_SERVICE_JSON, default
V:/olden_port_work/kokon/KokonData/service.json holds its token; API on 127.0.0.1:39151).

  TOWN_FULL3D_FACTION=<f> TOWN_FULL3D_CANDIDATE=<cand> python town_full3d_upscale.py [--pre 2] [--cap 8192]
      [--only <prefab substring>] [--dry]
Writes <candidate>/work/upscale.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stronghold_full3d_scene as S  # noqa: E402

API = os.environ.get("KOKON_API", "http://127.0.0.1:39151/api/v1")
SERVICE = Path(os.environ.get("KOKON_SERVICE_JSON", "V:/olden_port_work/kokon/KokonData/service.json"))
SOFT = 0.55
KINDS = ("lit", "sky")
PRE_STEPS = (1.0, 1.5, 2.0, 3.0, 4.0)
KOKON_MAX = 8192
KOKON_MIN = 64      # px per side, both limits on the x4 output
KOKON_MP = 38e6     # its limit is 'about 40 megapixels'


def oversampling(rgb, psnr_min: float) -> float:
    """Largest f in PRE_STEPS whose area-down / cubic-up round trip keeps PSNR >= psnr_min (texture already that
    oversampled), on every 512 px tile of a 3x3 spread over the texture: the most detailed tile decides (one central
    window let a wide plate's flat sea pick x3 and soften the cove palms at its ends). Flat tiles (std < 2) abstain."""
    import cv2
    h, w = rgb.shape[:2]
    T = min(512, h, w)
    best = PRE_STEPS[-1]
    for ty in sorted({0, (h - T) // 2, h - T}):
        for tx in sorted({0, (w - T) // 2, w - T}):
            c = rgb[ty:ty + T, tx:tx + T].astype(np.float32)
            if float(c.std()) < 2.0:
                continue
            f_ok = 1.0
            for f in PRE_STEPS[1:]:
                if f > best:
                    break
                sw, sh = max(4, round(T / f)), max(4, round(T / f))
                rt = cv2.resize(cv2.resize(c, (sw, sh), interpolation=cv2.INTER_AREA), (T, T),
                                interpolation=cv2.INTER_CUBIC)
                mse = float(((rt - c) ** 2).mean())
                if 10 * math.log10(255 ** 2 / max(mse, 1e-6)) < psnr_min:
                    break
                f_ok = f
            best = min(best, f_ok)
    return best


def kokon_upscale(src: Path, w: int, h: int, dst: Path) -> None:
    tok = json.loads(SERVICE.read_text(encoding="utf-8"))["token"]
    body = json.dumps({"image": str(src), "scale": 4, "width": w * 4, "height": h * 4}).encode()
    req = urllib.request.Request(API + "/upscale", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        res = json.loads(r.read())
    out = None
    for x in res.get("results") or []:
        if isinstance(x, dict) and x.get("file_path"):
            out = x["file_path"]
            break
    out = out or res.get("output_path") or res.get("path")
    if not out or not Path(out).is_file():
        raise SystemExit(f"upscale: Kokon returned no image for {src}: {json.dumps(res)[:1500]}")
    shutil.copy2(out, dst)
    try:
        Path(out).unlink()  # our own output; Kokon keeps no other use for it
    except OSError:
        pass


def bleed(rgba):
    import cv2
    a = rgba[..., 3]
    rgb = np.ascontiguousarray(rgba[..., :3])
    hole = (a < 8).astype(np.uint8)
    if hole.any() and not hole.all():
        rgb = cv2.inpaint(rgb, hole, 5, cv2.INPAINT_TELEA)
    return rgb


def pow2_at_least(n: int) -> int:
    return 1 << max(0, math.ceil(math.log2(max(1, n))))


def tex_file(path: str) -> Path:
    root = S.ASSET_ROOT.rstrip("/") + "/"
    if not path.startswith(root):
        raise SystemExit(f"upscale: texture outside the town asset root: {path}")
    return S.STAGE / path[len(root):]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pre", default="auto", help="pre-downscale before the x4 network (number, or auto per texture)")
    ap.add_argument("--pre-psnr", type=float, default=38.0)
    ap.add_argument("--max-gain", type=float, default=2.0, help="net size gain per texture (tower ns2: 2x)")
    ap.add_argument("--cap", type=int, default=8192)
    ap.add_argument("--min-gain", type=float, default=1.25)
    ap.add_argument("--atlas-max", type=int, default=2048,
                    help="building/prop textures already this large are left as they are (terrain and sky still go)")
    ap.add_argument("--only", default="", help="only prefabs whose key contains this")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import cv2
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    srp = S.WORK / "stage_report.json"
    bld = (json.loads(srp.read_text(encoding="utf-8")).get("buildings") or {}) if srp.is_file() else {}

    def pre_of(key, rgb):
        if a.pre != "auto":
            return float(a.pre)
        f = oversampling(rgb, a.pre_psnr)
        tpp = (bld.get(key[len(S.PREFIX):]) or {}).get("texelsPerPx")
        if key != S.ENV_KEY and tpp:
            f = max(f, min(4.0, float(tpp)))
        return round(f, 3)
    tmp = S.CAND / "work" / "upscale_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    jobs = []
    for key, row in rows.items():
        if a.only and a.only not in key:
            continue
        for b in row.get("bins") or []:
            if b.get("kind", "lit") not in KINDS or not b.get("texture") or b.get("upscaled"):
                continue
            p = tex_file(b["texture"])
            if not p.is_file():
                raise SystemExit(f"upscale: {key}/{b['name']}: missing {p}")
            w, h = Image.open(p).size
            if a.cap / max(w, h) < a.min_gain or min(w, h) < KOKON_MIN // 4 * 2:
                continue        # at the cap, or a texel swatch too small to carry detail (Kokon: >= 64 px out)
            if key != S.ENV_KEY and max(w, h) >= a.atlas_max:
                continue        # a mesh UV atlas already past screen detail (factory/fortress Meshy 2048s: x2 was
                                # +450 MP, bundles 360 -> 880 MB, for nothing visible at town distance)
            jobs.append((key, b, p, w, h))
    print(f"upscale: {len(jobs)} textures, {sum(j[3] * j[4] for j in jobs) / 1e6:.0f} MP in", flush=True)
    if a.dry:
        for key, b, p, w, h in jobs:
            im = np.asarray(Image.open(p))
            im = bleed(im) if im.ndim == 3 and im.shape[2] == 4 else np.asarray(Image.open(p).convert("RGB"))
            pre = pre_of(key, im)
            g = min(4.0 / pre, a.max_gain, a.cap / max(w, h))
            print(f"  {key[len(S.PREFIX):]} {b['name']} {w}x{h} pre {pre} -> {round(w * g)}x{round(h * g)}")
        return 0
    import town_full3d_gpu
    rep = {}
    t0 = time.time()
    with town_full3d_gpu.gate("town upscale", need_vram_gb=6.0, wait_min=600):
        for i, (key, b, p, w, h) in enumerate(jobs):
            im = np.asarray(Image.open(p))
            rgba = im.ndim == 3 and im.shape[2] == 4
            rgb = bleed(im) if rgba else (im[..., :3] if im.ndim == 3 else np.repeat(im[..., None], 3, -1))
            pre = pre_of(key, rgb)
            gain = min(4.0 / pre, a.max_gain, a.cap / max(w, h))
            if gain < a.min_gain:
                continue        # already at its painted detail: a down-and-back-up round trip adds nothing but loss
            # Kokon refuses outputs past KOKON_MAX px a side or KOKON_MP pixels
            pre = max(pre, 4 * max(w, h) / KOKON_MAX, math.sqrt(16 * w * h / KOKON_MP))
            pre = max(1.0, min(pre, 4 * min(w, h) / KOKON_MIN))
            sw, sh = max(1, round(w / pre)), max(1, round(h / pre))
            src = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA) if pre != 1 else rgb
            src = cv2.GaussianBlur(src, (0, 0), SOFT)
            fin, fout = tmp / f"in_{i}.png", tmp / f"out_{i}.png"
            Image.fromarray(src).save(fin)
            kokon_upscale(fin, sw, sh, fout)
            tw, th = max(1, round(w * gain)), max(1, round(h * gain))
            hi = np.asarray(Image.open(fout).convert("RGB").resize((tw, th), Image.LANCZOS))
            if rgba:
                al = cv2.resize(im[..., 3], (tw, th), interpolation=cv2.INTER_CUBIC)
                hi = np.dstack([hi, al])
            p.unlink()
            Image.fromarray(hi).save(p)
            fin.unlink(); fout.unlink()
            b["maxSize"] = min(a.cap, max(int(b.get("maxSize") or 0), pow2_at_least(max(tw, th))))
            b["upscaled"] = {"from": [w, h], "pre": pre, "net": round(gain, 3)}
            rep[f"{key}/{b['name']}"] = {"from": [w, h], "to": [tw, th], "pre": pre, "maxSize": b["maxSize"]}
            print(f"  [{i + 1}/{len(jobs)}] {key[len(S.PREFIX):] or key} {b['name']} {w}x{h} pre {pre} -> {tw}x{th}", flush=True)
    S.ROWS.unlink()
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    out = S.CAND / "work" / "upscale.json"
    if out.is_file():
        out.unlink()
    out.write_text(json.dumps({"pre": a.pre, "cap": a.cap, "secs": round(time.time() - t0), "textures": rep},
                              indent=1), encoding="utf-8")
    print(f"upscale: {len(rep)} textures in {time.time() - t0:.0f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
