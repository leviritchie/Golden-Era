#!/usr/bin/env python3
"""Full-3D towns: import the 2026-09-30 image-to-image background depth map as the lane's background depth source.

    TOWN_FULL3D_FACTION=<town> python town_full3d_bg_depth.py import      # write depth/img2img_bg.{npy,json}
    TOWN_FULL3D_FACTION=<town> python town_full3d_bg_depth.py compare     # + depth/img2img_vs_da_large.png

Source (user, 2026-09-30): artifacts/img2img_depth_maps/homm3_<town>/background/<Town>-in-background__depth_raw.png,
manifest artifacts/img2img_depth_maps/background_checkpoint.json (sha256 per file). Convention white = near,
black = far, relative (not metric) - the same polarity as Depth Anything's disparity, and the terrain's calibration
(stronghold_full3d_terrain.calibrate: robust degree-2 polynomial disparity -> inverse depth on the floor polygon)
needs relative disparity only, so the map enters exactly where da_large.npy did.

import
  * refuses unless the metadata's source_sha256 is this lane's own <Faction>-in-background.png and the raw file's
    sha256 is the checkpoint manifest's;
  * reads the RAW output (1836x857 RGB, not the 8-bit 800x374 L resample: one resample instead of two), mean of the
    three channels as float, resized (INTER_AREA) to the frame rect TW x TH;
  * registration is "requested_not_guaranteed" in the metadata, so it is MEASURED: ECC (affine) between the
    gradient magnitude of the painting and of the depth, both blurred; the warp is applied only when it is
    significant (> REG_MIN_PX anywhere in the rect) and refused when implausible (> REG_MAX_PX: not a registration
    of this painting). Recorded either way.
  * writes depth/img2img_bg.npy (float32, TH x TW, larger = nearer) + img2img_bg.json (provenance + registration).
The terrain reads it when the faction profile sets BACKGROUND_DEPTH_SOURCE = "img2img" (stronghold_full3d_terrain
.background_disparity; a missing or sha-mismatched file fails, never falls back to da_large).
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402

SRC_ROOT = SC.ROOT / "artifacts" / "img2img_depth_maps"
MANIFEST = SRC_ROOT / "background_checkpoint.json"
OUT_NPY = SC.DATA / "depth" / "img2img_bg.npy"
OUT_JSON = SC.DATA / "depth" / "img2img_bg.json"
REG_MIN_PX = 1.0     # warp displacement below this anywhere in the rect: identity kept
REG_MAX_PX = 24.0    # above this the map is not a registration of this painting: refuse


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_files() -> tuple[Path, Path, dict]:
    d = SRC_ROOT / SC.FRACTION / "background"
    raws = sorted(d.glob("*__depth_raw.png"))
    metas = sorted(d.glob("*__metadata.json"))
    if len(raws) != 1 or len(metas) != 1:
        raise SystemExit(f"bg depth: expected one raw + one metadata under {d}, got {raws} {metas}")
    return raws[0], metas[0], json.loads(metas[0].read_text(encoding="utf-8"))


def grad(img: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 2.0)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    m = np.sqrt(gx * gx + gy * gy)
    return m / (np.percentile(m, 99) + 1e-6)


def do_import() -> dict:
    raw, meta_p, meta = source_files()
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rel = raw.relative_to(SRC_ROOT).as_posix()
    want = {f["path"]: f["sha256"] for f in man["files"]}.get(rel)
    got = sha(raw)
    if want is None or want != got:
        raise SystemExit(f"bg depth: {rel} sha256 {got} is not the checkpoint manifest's {want}")
    bg_sha = sha(SC.REFS / SC.FP.BACKGROUND)
    if meta.get("source_sha256") != bg_sha or meta.get("polarity") != "white_near_black_far":
        raise SystemExit(f"bg depth: metadata source {meta.get('source_sha256')} / polarity {meta.get('polarity')} "
                         f"is not this lane's background ({bg_sha}) / white_near_black_far")
    rgb = np.asarray(Image.open(raw).convert("RGB"), np.float32) / 255.0
    d = cv2.resize(rgb.mean(-1), (SC.TW, SC.TH), interpolation=cv2.INTER_AREA)
    paint = np.asarray(SC.background_rgb().resize((SC.TW, SC.TH), Image.LANCZOS).convert("L"), np.float32)
    a, b = grad(paint), grad(d)
    warp = np.eye(2, 3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    cc0 = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    try:
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_AFFINE, crit, None, 5)
    except cv2.error as e:
        raise SystemExit(f"bg depth: ECC registration did not converge ({e})")
    ys, xs = np.mgrid[0:SC.TH:8, 0:SC.TW:8].astype(np.float32)
    dx = warp[0, 0] * xs + warp[0, 1] * ys + warp[0, 2] - xs
    dy = warp[1, 0] * xs + warp[1, 1] * ys + warp[1, 2] - ys
    disp = np.sqrt(dx * dx + dy * dy)
    reg = {"method": "ECC affine on blurred gradient magnitude (painting vs depth)", "ccBefore": round(cc0, 4),
           "ccAfter": round(float(cc), 4), "warp": np.round(warp, 5).tolist(),
           "maxDisplacementPx": round(float(disp.max()), 2), "medianDisplacementPx": round(float(np.median(disp)), 2)}
    if disp.max() > REG_MAX_PX:
        raise SystemExit(f"bg depth: registration displacement {disp.max():.1f} px > {REG_MAX_PX}: {reg}")
    if disp.max() > REG_MIN_PX:
        d = cv2.warpAffine(d, warp, (SC.TW, SC.TH), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                           borderMode=cv2.BORDER_REPLICATE)
        reg["applied"] = True
    else:
        reg["applied"] = False
    OUT_NPY.parent.mkdir(parents=True, exist_ok=True)
    np.save(OUT_NPY, d.astype(np.float32))
    rep = {"schema": "town_full3d_bg_depth.v1", "fraction": SC.FRACTION,
           "source": {"raw": str(raw.relative_to(SC.ROOT)).replace("\\", "/"), "rawSha256": got,
                      "metadata": str(meta_p.relative_to(SC.ROOT)).replace("\\", "/"), "metadataSha256": sha(meta_p),
                      "manifest": str(MANIFEST.relative_to(SC.ROOT)).replace("\\", "/"),
                      "manifestSha256": sha(MANIFEST), "backgroundSha256": bg_sha, "method": meta.get("method"),
                      "polarity": meta.get("polarity"), "registrationClaim": meta.get("source_registration")},
           "read": "raw RGB mean / 255, INTER_AREA to the frame rect", "shape": [SC.TH, SC.TW],
           "registration": reg, "npySha256": sha(OUT_NPY)}
    OUT_JSON.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def compare() -> dict:
    import stronghold_full3d_terrain as T
    paint = T.painting()
    sky = T.sky_mask(paint)
    floor = T.Floor(T.camera())
    z_old = T.calibrate(floor, np.load(SC.DATA / "depth" / "da_large.npy"), sky)
    z_new = T.calibrate(floor, np.load(OUT_NPY), sky)
    m = ~sky & np.isfinite(z_old["zc"]) & np.isfinite(z_new["zc"])
    lr = np.log(z_new["zc"] / z_old["zc"])
    vis = []
    for z in (z_old["zc"], z_new["zc"]):
        v = np.where(m, 1.0 / np.clip(z, 1, None), 0)
        v = (np.clip(v / np.percentile(v[m], 99), 0, 1) * 255).astype(np.uint8)
        vis.append(cv2.applyColorMap(v, cv2.COLORMAP_TURBO)[..., ::-1])
    diff = np.clip(np.where(m, lr, 0) * 255 / 1.0 + 128, 0, 255).astype(np.uint8)
    sheet = np.concatenate([np.concatenate([paint, vis[0]], 1),
                            np.concatenate([vis[1], cv2.applyColorMap(diff, cv2.COLORMAP_COOL)[..., ::-1]], 1)], 0)
    out = SC.DATA / "depth" / "img2img_vs_da_large.png"
    Image.fromarray(sheet).save(out)
    rep = {"calibNew": {k: v for k, v in z_new.items() if k != "zc"},
           "calibOld": {k: v for k, v in z_old.items() if k != "zc"},
           "absLogRatio": {"median": round(float(np.median(np.abs(lr[m]))), 4),
                           "p90": round(float(np.percentile(np.abs(lr[m]), 90)), 4)},
           "sheet": str(out.relative_to(SC.ROOT)).replace("\\", "/")}
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["import", "compare"])
    a = ap.parse_args()
    if a.cmd == "import":
        rep = do_import()
        print(json.dumps({"registration": rep["registration"], "npySha256": rep["npySha256"][:12]}))
    print(json.dumps(compare()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
