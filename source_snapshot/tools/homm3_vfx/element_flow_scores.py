"""Element flow: uvAtlas scores that animate an elemental's texture in step with its element_motion geometry.

Pairs with `tools/homm3_def_retarget/ext/element_motion.py`. It reads the same retarget unit config
(`elementMotion`: mode, period, loops) so the texture cycle and the bone-key cycle share one period, and the
per-unit texture knobs live there too, under `elementMotion.flow` (one config per unit, one rule per mode).
The unit-look layer consumes the scores with the uvAtlas `modulate` variant (vfx.modulate_cells): the look's
own colours are kept and each cell scales their brightness by clip(1 + 2 gain (score - 0.5)), so 0.5 is
neutral and a texel a mode does not animate stays at 0.5.

Per texel the generator knows the rest position (glTF, y up), the share of skin weight on the motion carrier
(Col_* / Tail_* chain) and the position along it (u, 0 at the chain root). Patterns (L cells per cycle, cell k
at phase k / L, all periodic in the phase so the loop closes):

  vortex   wispy streaks laid along a helix about the column axis plus a broad band, rotating CCW with the
           whirl (360 / repeats per cycle); upper body at `upperGain` of the column's amplitude.
  shimmer  a slow two-lobed swirl turning about the body axis plus a whole-body breathing pulse.
  roil     vertically stretched flame tongues licking upward (drift one tile height per cycle) over a broader,
           slower roil; multiplicative, so the bright cracks flare most.
  grind    faint crumble speckle drifting slowly down.
  crystal  sparse glints (each blinks once per cycle at its own phase) plus a narrow sheen band sweeping
           diagonally across the body once per cycle.
  crackle  thin ridged filaments re-rolled every cell (stepped crackle) plus a pulse.
  Any mode: `pulseFromDef: s` adds the DEF idle's own whole-body brightness curve (cells == idle frames).
  coil     bands travelling down the tail (root -> tip, `waves` per chain length) over drifting sheets;
           upper body at `upperGain`.

Writes artifacts/homm3_vfx_experiments/element_flow/<unit>_scores.npz ('scores' (cells, N, N) in [0,1], glTF UV
top-down) + <unit>_scores.json (knobs, the per-clip cell sequences for the look layer) and, with --preview,
a strip of the cells. Proof tier: generated artifact.

    python tools/homm3_vfx/element_flow_scores.py <unit> [--preview] [--print-layer]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget/ext"))
from glb_io import Glb  # noqa: E402
from oceanid_water_lab import rasterise, value_noise3  # noqa: E402
from oceanid_corkscrew_scores import wrap_noise  # noqa: E402

OUT = ROOT / "artifacts/homm3_vfx_experiments/element_flow"
RT = ROOT / "artifacts/homm3_def_retarget"
CFG = ROOT / "tools/homm3_def_retarget/units"
MOCAP = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"

FLOW_DEFAULTS = {
    "vortex": {"gain": 0.45, "repeats": 2, "pitchDefPx": 26, "upperGain": 0.25},
    "shimmer": {"gain": 0.3, "repeats": 2, "pitchDefPx": 40, "pulse": 0.12, "upperGain": 0.8},
    "roil": {"gain": 0.45, "tileDefPx": 40, "tongueDefPx": 5},
    "grind": {"gain": 0.18, "tileDefPx": 60},
    "crystal": {"gain": 0.6, "glintShare": 0.03, "glintDefPx": 2.5, "sheen": 0.4, "bandDefPx": 6},   # first cut (0.012 share, 1.5 px sites) read as nothing at showcase scale
    "crackle": {"gain": 0.45, "filamentDefPx": 9, "pulse": 0.12},
    "coil": {"gain": 0.4, "waves": 3.0, "pitchDefPx": 30, "upperGain": 0.3},
    "corkscrew": None,   # the oceanid/nymph water: oceanid_corkscrew_scores.py owns it
}


def load_body(unit: str, glb_path: Path):
    g = Glb(glb_path)
    node = next(n for n in g.json["nodes"] if n.get("name") == unit and "mesh" in n)
    pr = g.json["meshes"][node["mesh"]]["primitives"][0]
    a = pr["attributes"]
    P = g.accessor(a["POSITION"]).astype(np.float64)
    UV = g.accessor(a["TEXCOORD_0"]).astype(np.float64)
    I = g.accessor(pr["indices"]).astype(np.int64).reshape(-1, 3)
    Jn = g.accessor(a["JOINTS_0"]).astype(np.int64)
    W = g.accessor(a["WEIGHTS_0"]).astype(np.float64)
    names = [g.json["nodes"][k]["name"] for k in g.json["skins"][node["skin"]]["joints"]]
    return P, UV, I, Jn, W, names


def chain_attrs(Jn, W, names, prefix):
    """Per vertex: share of weight on the chain and position along it (0 root .. 1 end)."""
    links = sorted(n for n in names if n.startswith(prefix))
    if not links:
        return None, None, 0
    idx = {names.index(n): k for k, n in enumerate(links)}
    share = np.zeros(len(W))
    along = np.zeros(len(W))
    for c in range(Jn.shape[1]):
        k = np.array([idx.get(int(j), -1) for j in Jn[:, c]])
        m = k >= 0
        share[m] += W[m, c]
        along[m] += W[m, c] * (k[m] + 0.5) / len(links)
    along = np.where(share > 1e-6, along / np.maximum(share, 1e-6), 0.0)
    return share, along, len(links)


def clip_frames(unit):
    ms = json.loads((MOCAP / unit / "linked_master/master_sequence/master_sequence.json").read_text())
    out = {}
    for s in ms["segments"]:
        n = "Unit_" + s["contractSuffix"]
        out[n] = max(out.get(n, 0), s["frameCount"])
    return out


def def_idle_luma(unit):
    ms = json.loads((MOCAP / unit / "linked_master/master_sequence/master_sequence.json").read_text())
    seg = max((s for s in ms["segments"] if s["contractSuffix"] == "Idle"), key=lambda s: s["frameCount"])
    out = []
    for t in range(seg["globalStart"], seg["globalEnd"]):
        im = np.asarray(Image.open(ms["frames"][t]["sourcePng"]).convert("RGBA")).astype(np.float32)
        m = im[..., 3] > 127
        out.append(round(float((im[..., :3] @ np.array([.299, .587, .114]))[m].mean()), 2))
    return out


def cell_sequences(frames: dict, L: int, P: float, loops: list) -> dict:
    """Cell per key: a looping clip (N frames) runs round(N/P) whole cycles and closes; others advance one cell
    per frame. Mirrors element_motion.eff_period."""
    seq = {}
    for clip, N in frames.items():
        if clip.removeprefix("Unit_") in loops and N > 1:
            c = max(1, round(N / P))
            seq[clip] = [int(math.floor(L * c * i / N + 1e-9)) % L for i in range(N)]
        else:
            seq[clip] = [int(round(i * L / P)) % L for i in range(N)]
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--glb", help="skinned GLB (default: the delivered retarget GLB)")
    ap.add_argument("--cfg", help="retarget unit config (default: tools/homm3_def_retarget/units/<unit>.json)")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--tag", default="", help="suffix for scratch outputs")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--print-layer", action="store_true", help="print the unit-look uvAtlas layer JSON")
    a = ap.parse_args()
    U = a.unit
    cfg = json.loads(Path(a.cfg or CFG / f"{U}.json").read_text())
    # elementFlow: texture-only settings for a unit whose geometry comes from another hook (the nymph's
    # cove_corkscrew); otherwise the element_motion config itself
    em = cfg.get("elementFlow") or cfg.get("elementMotion")
    if not em:
        sys.exit(f"{U}: no elementMotion / elementFlow in the retarget config")
    mode = em["mode"]
    if FLOW_DEFAULTS.get(mode) is None:
        sys.exit(f"{U}: mode {mode!r} has no element_flow pattern (corkscrew water: oceanid_corkscrew_scores.py)")
    kn = dict(FLOW_DEFAULTS[mode])
    kn.update(em.get("flow", {}))
    P_ = float(em.get("period", 8))
    L = int(kn.get("cells", round(P_)))
    loops = cfg.get("loops", ["Idle", "Move"])
    seed = int(kn.get("seed", 7))
    glb_path = (Path(a.glb).resolve() if a.glb else RT / U / f"{U}_def_retarget.glb")
    sc_json = glb_path.parent / f"{U}_def_retarget.blend.spritecam.json"
    ppu = json.loads(sc_json.read_text())["pxPerUnit"]
    px = 1.0 / ppu                                         # one DEF px in scene units

    Pv, UV, I, Jn, W, names = load_body(U, glb_path)
    carrier = em.get("flowCarrier") or {"vortex": "Col_", "shimmer": "Col_", "coil": "Tail_"}.get(mode)
    share = along = None
    if carrier:
        share, along, nl = chain_attrs(Jn, W, names, carrier)
        if share is None:
            sys.exit(f"{U}: mode {mode} needs the {carrier}* chain in {glb_path} (rebuild with element_motion first)")
    N = a.size
    tris = np.ones(len(I), bool)
    pos, cov = rasterise(Pv, UV, I, tris, N)
    ext = np.stack([share if share is not None else np.zeros(len(Pv)),
                    along if along is not None else np.zeros(len(Pv)), np.zeros(len(Pv))], 1)
    ch, _ = rasterise(ext, UV, I, tris, N)
    csh, cu = ch[..., 0], ch[..., 1]
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    ys = Pv[:, 1]
    # body axis (glTF x, z): the carrier's texels when there is one, else the whole mesh
    sel = share > 0.5 if share is not None and (share > 0.5).any() else np.ones(len(Pv), bool)
    cx, cz = float(np.median(Pv[sel, 0])), float(np.median(Pv[sel, 2]))
    a01 = (np.arctan2(-(z - cz), x - cx) / (2 * math.pi)) % 1.0     # Blender CCW angle, [0,1)
    rng = np.random.default_rng(seed)

    def cell(k):
        ph = k / L
        if mode == "vortex":
            R, pitch = kn["repeats"], kn["pitchDefPx"] * px
            psi = (a01 * R + y / pitch - ph) % 1.0                    # helix phase; rotating CCW with the whirl
            streak = wrap_noise(psi, y, 14, pitch * 2.5, seed + 1)
            band = 0.5 + 0.5 * np.sin(2 * math.pi * psi)
            fine = wrap_noise((psi * 3) % 1.0, y, 24, pitch * 0.6, seed + 2)
            raw = 0.45 * streak + 0.35 * band + 0.2 * fine
            m = csh + (1 - csh) * kn["upperGain"]
        elif mode == "shimmer":
            R, pitch = kn["repeats"], kn["pitchDefPx"] * px
            aa = (a01 * R - ph) % 1.0
            sw = 0.6 * wrap_noise(aa, y, 3, pitch, seed + 1) + 0.4 * wrap_noise(aa, y, 6, pitch * 0.5, seed + 2)
            raw = sw + kn["pulse"] * math.sin(2 * math.pi * ph)
            m = csh + (1 - csh) * kn["upperGain"]
        elif mode == "roil":
            Hy, tw = kn["tileDefPx"] * px, kn["tongueDefPx"] * px
            v = (y / Hy - ph) % 1.0                                   # upward drift: one tile per cycle
            nt = max(2, int(round(Hy / (4 * tw))))
            tongue = 0.5 * wrap_noise(v, x, nt, tw, seed + 1) + 0.5 * wrap_noise(v, z, nt, tw, seed + 2)
            v2 = (y / (2 * Hy) - ph) % 1.0
            broad = 0.5 * wrap_noise(v2, x + z, 3, 4 * tw, seed + 3) + 0.5 * wrap_noise(v2, x - z, 3, 4 * tw, seed + 4)
            raw = 0.6 * tongue ** 1.5 / 0.35 * 0.5 + 0.4 * broad
            m = np.ones_like(y)
        elif mode == "grind":
            Hy = kn["tileDefPx"] * px
            v = (y / Hy + ph) % 1.0                                    # slow downward drift
            raw = 0.5 * wrap_noise(v, x, 12, 3 * px, seed + 1) + 0.5 * wrap_noise(v, z, 12, 3 * px, seed + 2)
            m = np.ones_like(y)
        elif mode == "crystal":
            raw = np.full_like(y, 0.45)
            d = np.cos(2 * math.pi * (ph - sites_phase))             # each glint blinks once per cycle
            raw = raw + 0.5 * np.where(sites, np.clip(d, 0, 1) ** 6, 0)
            s = ((x - z) * 0.707 + y) / span - ph                      # diagonal sheen sweep
            s = (s + 0.5) % 1.0 - 0.5
            raw = raw + kn["sheen"] * np.exp(-(s * span / (kn["bandDefPx"] * px)) ** 2)
            m = np.ones_like(y)
        elif mode == "crackle":
            f = kn["filamentDefPx"] * px
            n1 = value_noise3(np.stack([x, y, z], -1), f, seed + 100 + k)
            ridge = (1 - np.abs(2 * n1 - 1)) ** 10
            raw = 0.4 + 0.6 * ridge + kn["pulse"] * math.sin(2 * math.pi * ph)
            m = np.ones_like(y)
        elif mode == "coil":
            wv, pitch = kn["waves"], kn["pitchDefPx"] * px
            v = (cu * wv - ph) % 1.0                                   # root -> tip
            band = 0.5 + 0.5 * np.sin(2 * math.pi * v)
            sheet = wrap_noise(v, a01 * 2 * math.pi * 0.2, int(max(2, round(wv * 2))), pitch, seed + 1)
            vy = (y / (3 * pitch) + ph) % 1.0                          # upper body: sheets running down
            up = wrap_noise(vy, x + z, 3, pitch, seed + 2)
            raw = np.where(csh > 0.3, 0.55 * band + 0.45 * sheet, up)
            m = csh + (1 - csh) * kn["upperGain"]
        else:
            raise SystemExit(f"unknown mode {mode}")
        raw = np.clip(raw, 0, 1)
        return np.clip(0.5 + m * (raw - 0.5), 0, 1)

    sites = sites_phase = span = None
    if mode == "crystal":
        vn = value_noise3(np.stack([x, y, z], -1), kn["glintDefPx"] * px, seed + 9)
        vn = np.where(cov, vn, 0)
        thr = np.quantile(vn[cov], 1 - kn["glintShare"])
        sites = cov & (vn > thr)
        lab, nlab = ndimage.label(sites)
        phs = rng.random(nlab + 1)
        sites_phase = phs[lab]
        span = float(np.ptp(ys)) * 1.5

    # optional whole-body brightness curve measured on the DEF idle (magma glow, energy/storm flicker):
    # cell k takes idle frame k's mean-luma ratio (sRGB ratio -> linear ^2.2, scaled by pulseFromDef)
    off = np.zeros(L)
    defcurve = None
    if kn.get("pulseFromDef"):
        defcurve = def_idle_luma(U)
        if len(defcurve) != L:
            sys.exit(f"{U}: pulseFromDef needs cells == idle frames ({len(defcurve)}); set elementMotion.period")
        r = np.array(defcurve) / np.mean(defcurve)
        f = 1 + kn["pulseFromDef"] * (r ** 2.2 - 1)
        off = (f - 1) / (2 * kn["gain"])
    near = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
    cells = [np.clip(np.where(cov, cell(k) + off[k], 0.5), 0, 1)[near[0], near[1]] for k in range(L)]
    sc = np.stack(cells).astype(np.float16)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"{U}{a.tag}_scores"
    np.savez_compressed(OUT / f"{stem}.npz", scores=sc)
    frames = clip_frames(U)
    seqs = cell_sequences(frames, L, P_, loops)
    meta = {"schema": "element_flow_scores.v1", "unit": U, "mode": mode, "cells": L, "period": P_, "loops": loops,
            "knobs": kn, "defPxUnits": px, "axisGltfXZ": [cx, cz], "glb": glb_path.as_posix(),
            "clips": seqs, "defIdleLuma": defcurve, "pairsWith": "tools/homm3_def_retarget/ext/element_motion.py",
            "scoreStats": {"mean": float(sc.mean()), "p5": float(np.quantile(sc[:, cov], 0.05)),
                           "p95": float(np.quantile(sc[:, cov], 0.95))}}
    (OUT / f"{stem}.json").write_text(json.dumps(meta, indent=1))
    print("wrote", OUT / f"{stem}.npz", {k: meta[k] for k in ("mode", "cells", "period", "scoreStats")})
    if a.preview:
        strip = np.concatenate([(c * 255).astype(np.uint8)[::4, ::4] for c in cells], 1)
        Image.fromarray(strip).save(OUT / f"{stem}_preview.png")
    if a.print_layer:
        print(json.dumps(layer_json(U, meta, stem), indent=1))


def layer_json(U, meta, stem):
    return {"id": "element_flow", "type": "uvAtlas",
            "provenance": f"element_flow_scores.py mode {meta['mode']}: {meta['cells']} cells per {meta['period']:g}-frame "
                          f"cycle, in phase with the retarget's element_motion keys; brightness-modulated look texture",
            "modulate": {"gain": meta["knobs"]["gain"]},
            "clips": meta["clips"],
            "source": {"scores": f"artifacts/homm3_vfx_experiments/element_flow/{stem}.npz",
                       "generator": "tools/homm3_vfx/element_flow_scores.py"},
            "gutterPx": 16}


if __name__ == "__main__":
    main()
