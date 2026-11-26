"""HoMM3 tone grade: match a repainted unit's brightness / contrast / saturation to its own DEF sprite frames.

Nano Banana repaints come back brighter, flatter and more saturated than the HoMM3 battle sprites (the gnoll paints
as a saturated cartoon yellow; the DEF is a darker ochre-brown with deep shadow). This tool measures both in CIELAB
and fits one global per-unit transform:

  * target: the median of per-frame stats over the unit's native DEF frames (alpha >= 200, so HoMM3's 64/128
    shadow pixels do not count; the median drops effect frames such as an angel's gold flash);
  * source: the foreground of out/repaint_primary.png (+ repaint_secondary.png), i.e. the painting the texture was
    projected from;
  * HoMM3's harsh pre-baked lighting, self-shadow and dark rims are lighting, not texture, and Olden Era lights the
    mesh itself. So only the LIT half of each image (L >= its median) is compared: brightness matches the lit tone
    (L p75), contrast only the lit-half spread (p90 - p50, tightly clamped), saturation/hue the lit pixels' chroma;
  * transform (Lab, float): L' = p75S + dL + (L - p75S) * kL  (brightness + contrast),
    ab' = ab * kC + hueShift  (saturation; a partial pull of the mean a/b toward the DEF's hue).
    Every factor is clamped (GRADE_LIMITS) so a noisy sprite cannot wreck a texture, and ``--strength`` blends
    the whole transform toward identity.

The same transform is then applied to the shipped textures (out/basecolor_hexlit_pbr.png, out/basecolor_albedo.png)
and, for review, to the repaint sheets. Graded copies land in out/graded/ with grade.json; originals are untouched.
``--install`` overwrites out/basecolor_*.png after keeping out/pre_grade/ backups (method approved by the owner
2026-11-25). It is idempotent: grade.json records the sha of what it installed, so a re-run grades the pre_grade/
original instead of grading twice, and a fresh `batch_driver.py project` (new sha) is graded and backed up anew.
Pipeline order: project -> color_grade --install -> qa-board -> assemble.

    python tools/homm3_retexture_pbr/color_grade.py --work-dir V:/olden_port_work/retexture_exp/fortress \\
        --units h3_gnoll [--strength 1.0] [--preview] [--install]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from def_sprite_loader import DEFAULT_REPO_ROOT, resolve_def_sources  # noqa: E402

GRADE_LIMITS = {
    "kL": (0.90, 1.20),        # contrast: lit-half spread ratio only, kept tight (shading is not texture)
    "dL": (-12.0, 8.0),        # lit-tone brightness shift (L units, 0..100), matched at L p75
    "kC": (0.60, 1.25),        # saturation (chroma of lit pixels) multiplier
    "hue": 6.0,                # max |a|,|b| mean pull
}
HUE_PULL = 0.5                 # fraction of the a/b mean difference (after chroma scaling) to correct
TEXTURES = ("basecolor_hexlit_pbr.png", "basecolor_albedo.png")
SHEETS = ("repaint_primary.png", "repaint_secondary.png")
SCHEMA = "homm3_color_grade.v1"


def to_lab(rgb_u8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb_u8.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def from_lab(lab: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB)
    return (np.clip(rgb, 0.0, 1.0) * 255.0).round().astype(np.uint8)


def lab_stats(lab: np.ndarray) -> dict[str, float]:
    """Material-tone stats. HoMM3 sprites carry harsh pre-baked key light, self-shadow and dark rims; that is
    lighting, not texture. So brightness, saturation and hue come from the LIT half only (L >= median), and the
    contrast proxy is the lit-half spread (p90 - p50), never the full shadow-to-highlight range."""
    L = lab[:, 0]
    p50 = float(np.percentile(L, 50))
    lit = lab[L >= p50]
    Ll, a, b = lit[:, 0], lit[:, 1], lit[:, 2]
    return {"n": int(len(L)), "Lmean": float(L.mean()), "Lp50": p50, "Lp75": float(np.percentile(L, 75)),
            "Lp90": float(np.percentile(L, 90)), "litSpread": float(np.percentile(L, 90) - p50),
            "chroma": float(np.hypot(a, b).mean()), "a": float(a.mean()), "b": float(b.mean())}


def def_stats(unit: str, repo_root: Path) -> dict[str, float]:
    """Median of per-frame stats, so effect frames (an angel's gold flash, a death fade) do not drag the target."""
    kind, paths = resolve_def_sources(unit, repo_root)
    if kind != "sources":
        raise SystemExit(f"{unit}: only composited cmp_*.png renders available; grade needs native DEF frames")
    per = []
    for p in paths:
        rgba = np.array(Image.open(p).convert("RGBA"))
        fg = rgba[..., 3] >= 200
        if fg.sum() >= 64:
            per.append(lab_stats(to_lab(rgba[..., :3][fg][None])[0]))
    if not per:
        raise SystemExit(f"{unit}: no opaque DEF pixels in {len(paths)} frames")
    out = {k: float(np.median([s[k] for s in per])) for k in per[0]}
    out["frames"] = len(per)
    return out


def sheet_mask(rgb: np.ndarray) -> np.ndarray:
    """Foreground of a repaint sheet: everything not connected to the flat grey border background."""
    corners = np.stack([rgb[4, 4], rgb[4, -5], rgb[-5, 4], rgb[-5, -5]]).astype(np.int16)
    bg = np.median(corners, axis=0)
    near = np.all(np.abs(rgb.astype(np.int16) - bg) <= 10, axis=-1).astype(np.uint8)
    n, lab = cv2.connectedComponents(near, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bgmask = np.isin(lab, list(border)) & (near > 0)
    fg = ~bgmask
    return cv2.erode(fg.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0


def fit(src: dict, tgt: dict, strength: float) -> dict[str, float]:
    lim = GRADE_LIMITS
    kL = float(np.clip(tgt["litSpread"] / max(src["litSpread"], 1e-3), *lim["kL"]))
    # pivot contrast on the lit tone, then move the lit tone to the sprite's
    dL = float(np.clip(tgt["Lp75"] - src["Lp75"], *lim["dL"]))
    kC = float(np.clip(tgt["chroma"] / max(src["chroma"], 1e-3), *lim["kC"]))
    ha = float(np.clip((tgt["a"] - src["a"] * kC) * HUE_PULL, -lim["hue"], lim["hue"]))
    hb = float(np.clip((tgt["b"] - src["b"] * kC) * HUE_PULL, -lim["hue"], lim["hue"]))
    s = float(np.clip(strength, 0.0, 1.5))
    return {"pivotL": src["Lp75"], "kL": 1 + (kL - 1) * s, "dL": dL * s, "kC": 1 + (kC - 1) * s,
            "ha": ha * s, "hb": hb * s, "strength": s}


def apply(rgb: np.ndarray, g: dict, mask: np.ndarray | None = None) -> np.ndarray:
    lab = to_lab(rgb)
    L = g["pivotL"] + g["dL"] + (lab[..., 0] - g["pivotL"]) * g["kL"]
    out = np.stack([np.clip(L, 0, 100), lab[..., 1] * g["kC"] + g["ha"], lab[..., 2] * g["kC"] + g["hb"]], -1)
    res = from_lab(out)
    if mask is not None:
        res = np.where(mask[..., None], res, rgb)
    return res


def grade_unit(unit: str, work_dir: Path, repo_root: Path, strength: float, preview: bool, install: bool) -> dict:
    out = work_dir / unit / "out"
    sheets = [out / s for s in SHEETS if (out / s).is_file()]
    if not sheets:
        raise SystemExit(f"{unit}: no repaint sheets in {out}")
    src_px, sheet_imgs = [], {}
    for p in sheets:
        rgb = np.array(Image.open(p).convert("RGB"))
        m = sheet_mask(rgb)
        sheet_imgs[p.name] = (rgb, m)
        src_px.append(rgb[m])
    src = lab_stats(to_lab(np.concatenate(src_px)[None])[0])
    tgt = def_stats(unit, repo_root)
    g = fit(src, tgt, strength)

    gdir = out / "graded"
    gdir.mkdir(exist_ok=True)
    prev = {}
    if (gdir / "grade.json").is_file():
        prev = json.loads((gdir / "grade.json").read_text(encoding="utf-8")).get("installedSha256", {})
    written, skipped = [], []
    for name in TEXTURES:
        p = out / name
        if not p.is_file():
            continue
        if prev.get(name) == _sha(p):
            # out/<tex> is the graded image this tool installed last time: grade the ungraded backup instead,
            # never the graded image again (a fresh `project` run replaces out/<tex>, and its sha then differs)
            p = out / "pre_grade" / name
            if not p.is_file():
                skipped.append(name)
                continue
        Image.fromarray(apply(np.array(Image.open(p).convert("RGB")), g)).save(gdir / name)
        written.append(name)
    graded_sheets = {}
    for name, (rgb, m) in sheet_imgs.items():
        graded = apply(rgb, g, m)
        graded_sheets[name] = graded
        if preview:
            Image.fromarray(graded).save(gdir / name)
    after = lab_stats(to_lab(np.concatenate([graded_sheets[n][sheet_imgs[n][1]] for n in graded_sheets])[None])[0])
    if skipped:
        raise SystemExit(f"{unit}: {skipped} already graded but pre_grade/ backup missing; re-run project first")
    installed = dict(prev)
    if install:
        bak = out / "pre_grade"
        bak.mkdir(exist_ok=True)
        for name in written:
            if prev.get(name) != _sha(out / name):   # out/<tex> is ungraded (first run or a fresh projection)
                shutil.copy2(out / name, bak / name)
            shutil.copy2(gdir / name, out / name)
            installed[name] = _sha(out / name)
    rec = {"schema": SCHEMA, "unit": unit, "def": tgt, "sheetBefore": src, "sheetAfter": after, "grade": g,
           "limits": GRADE_LIMITS, "huePull": HUE_PULL, "graded": written, "installedSha256": installed}
    (gdir / "grade.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    return rec


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--units", required=True)
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--preview", action="store_true", help="also write graded repaint sheets for review")
    ap.add_argument("--install", action="store_true", help="overwrite out/basecolor_*.png (backups in pre_grade/)")
    a = ap.parse_args()
    for unit in [u.strip() for u in a.units.split(",") if u.strip()]:
        r = grade_unit(unit, a.work_dir, a.repo_root, a.strength, a.preview, a.install)
        g, s, t, f = r["grade"], r["sheetBefore"], r["def"], r["sheetAfter"]
        print(f"{unit}: litL {s['Lp75']:.1f}->{f['Lp75']:.1f} (DEF {t['Lp75']:.1f})  litSpread {s['litSpread']:.1f}->"
              f"{f['litSpread']:.1f} (DEF {t['litSpread']:.1f})  chroma {s['chroma']:.1f}->{f['chroma']:.1f} "
              f"(DEF {t['chroma']:.1f})  kL={g['kL']:.2f} dL={g['dL']:+.1f} kC={g['kC']:.2f} "
              f"hue=({g['ha']:+.1f},{g['hb']:+.1f}){'  INSTALLED' if a.install else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
