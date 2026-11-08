"""A/B base-colour variants of our units, pulled toward vanilla on the biggest measured deviations.

    python tools/homm3_style_compare/variants.py [--units h3_pikeman,h3_crusader,h3_black_dragon]
    python tools/homm3_style_compare/render_all.py --side ours --only <units> \
        --variants-json artifacts/homm3_style_compare/variants/variants.json

Reads metrics.json (measure.py). Each unit is pulled to ITS OWN vanilla pair (factors.json also records the
roster medians, the value a single roster knob would take), applied in texture space to a COPY of artifacts/homm3_unit_look/<unit>/basecolor.png:
  sat     Lab chroma * k_C             k_C  = vanilla Cmean / ours Cmean                   (lit renders)
  detail  low + a * (tex - low)        a    = vanilla detailFineRms / ours (clamped 0.2..1)  low = masked gaussian
          (sigma DETAIL_SIGMA texels)  -> attenuates the fine texture band (speckle, Meshy mottling, v7c wet speckle)
  bright  L* + dL                      dL   = vanilla Lmean - ours Lmean (lit renders)
  combo   sat + detail + bright
These are texture-space stand-ins for pipeline knobs (grade saturation, detailAmount/chromaDetail/glossAmount,
exposure); they are not look.py outputs. Never touches the unit-look outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "homm3_unit_look"))
import pairs as PR  # noqa: E402
import spec as S  # noqa: E402
from measure import lab_to_srgb, srgb_to_lab  # noqa: E402

VDIR = PR.OUT / "variants"
DETAIL_SIGMA = 3.0


def pair_factors(p):
    """Pulled to this unit's own vanilla pair (what the page shows per unit)."""
    return {"k_C": p["v"]["Cmean"] / p["o"]["Cmean"],
            "a_detail": float(np.clip(p["v"]["detailFineRms"] / p["o"]["detailFineRms"], 0.2, 1.0)),
            "dL": p["v"]["Lmean"] - p["o"]["Lmean"]}


def factors(met):
    P = met["pairs"]
    med = lambda f: float(np.median([f(p) for p in P]))
    return {"k_C": med(lambda p: p["v"]["Cmean"] / p["o"]["Cmean"]),
            "a_detail": float(np.clip(med(lambda p: p["v"]["detailFineRms"] / p["o"]["detailFineRms"]), 0.2, 1.0)),
            "dL": med(lambda p: p["v"]["albedoLmean"] - p["o"]["albedoLmean"])}


def apply(rgb, valid, sat=1.0, detail=1.0, dl=0.0):
    lab = srgb_to_lab(rgb)
    if detail != 1.0:
        w = valid.astype(np.float64)
        for c in range(3):
            low = ndi.gaussian_filter(lab[..., c] * w, DETAIL_SIGMA) / np.maximum(ndi.gaussian_filter(w, DETAIL_SIGMA), 1e-3)
            lab[..., c] = np.where(valid, low + detail * (lab[..., c] - low), lab[..., c])
    if sat != 1.0:
        lab[..., 1:] *= sat
    if dl:
        lab[..., 0] = np.clip(lab[..., 0] + dl, 0, 100)
    out = lab_to_srgb(lab)
    return np.where(valid[..., None], out, rgb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default="h3_pikeman,h3_black_dragon,h3_medusa")
    a = ap.parse_args()
    met = json.loads((PR.OUT / "metrics.json").read_text())
    fr = factors(met)
    print("roster factors", fr)
    doc, per = {}, {}
    for u in a.units.split(","):
        f = pair_factors(next(p for p in met["pairs"] if p["ours"] == u))
        per[u] = f
        src = Image.open(S.out_dir(u) / "basecolor.png")
        rgba = np.asarray(src.convert("RGBA"))
        rgb = rgba[..., :3]
        valid = (rgba[..., 3] > 0) & (rgb.max(-1) > 2)
        od = VDIR / u; od.mkdir(parents=True, exist_ok=True)
        specs = {"sat": dict(sat=f["k_C"]), "detail": dict(detail=f["a_detail"]), "bright": dict(dl=f["dL"]),
                 "combo": dict(sat=f["k_C"], detail=f["a_detail"], dl=f["dL"])}
        doc[u] = {}
        for name, kw in specs.items():
            out = apply(rgb.copy(), valid, **kw)
            p = od / f"{name}.png"
            Image.fromarray(out).save(p)
            doc[u][name] = str(p)
    (VDIR / "variants.json").write_text(json.dumps(doc, indent=1))
    (VDIR / "factors.json").write_text(json.dumps({"roster": fr, "perUnit": per, "detailSigmaTexels": DETAIL_SIGMA}, indent=1))
    print("VARIANTS", VDIR / "variants.json")


if __name__ == "__main__":
    main()
