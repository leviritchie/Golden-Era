"""Prepare the oceanid flowing-water lab inputs (numpy only; no Blender, no Unity).

Reads a COPY of the def_retarget GLB and the DEF measurements from oceanid_water_motion.py and
writes, under artifacts/homm3_vfx_experiments/oceanid/work/:

- `hota_cove_oceanid_waterlab.glb`: the GLB copy plus a COLOR_0 vertex attribute
  (r = water, g = foam, b = 0, a = 1). Water = vertices whose dominant bone is Tail_*; foam =
  water vertices in the bottom flare. The build output itself is never modified.
- `boil_atlas.png`: the DEF-matched "boil" flipbook for candidate B. A 2x4 grid of cells, each
  the unit's own base colour at CELL px with the water texels re-rolled: a 3D-positional
  speckle (continuous across UV seams because it is evaluated at each texel's rest-pose surface
  point) and cream highlights at the DEF's measured density, independently seeded per cell so
  highlight survival between cells is at chance, as in the DEF. Body texels are identical in
  every cell, so stepping the cell never changes the torso. Each cell has a GUTTER px border
  (edge-extended) so mips do not bleed between cells.
- `sparkle_atlas.png`: same grid, RGBA, highlights only (candidate C, the transparent shell).
- `scroll_base.png`: cell 0 alone at CELL px (candidate A, native `_UvScroll`).
- `cells.json`: per clip, the atlas cell for every DEF frame. A new cell wherever the DEF redraws
  the water, the same cell wherever the DEF holds it (mouseover 4-6, defence 3-5, loop seams).

Usage: python tools/homm3_vfx/oceanid_water_lab.py [--cell 1024]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from glb_io import Glb  # noqa: E402
import oceanid_water_motion as wm  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC_GLB = ROOT / "artifacts/homm3_def_retarget/hota_cove_oceanid/hota_cove_oceanid_def_retarget.glb"
OUT = ROOT / "artifacts/homm3_vfx_experiments/oceanid/work"
GRID = (2, 4)  # cols, rows -> 8 cells
GUTTER = 32
DEF_PX_UNITS = 1.0 / 39.67222079026895  # SpriteCam pxPerUnit
CLIP_GROUPS = {"Unit_Idle": "02", "Unit_Mouseover": "01", "Unit_MoveStart": "20", "Unit_MoveEnd": "21",
               "Unit_Hitted": "03", "Unit_Defence": "04", "Unit_AttackFront": "12", "Unit_Death": "05"}


# ---------------------------------------------------------------- mesh + GLB copy

def load_mesh(glb: Glb):
    pr = glb.json["meshes"][0]["primitives"][0]
    a = pr["attributes"]
    P = glb.accessor(a["POSITION"]).astype(np.float64)
    UV = glb.accessor(a["TEXCOORD_0"]).astype(np.float64)
    I = glb.accessor(pr["indices"]).astype(np.int64).reshape(-1, 3)
    J = glb.accessor(a["JOINTS_0"]).astype(np.int64)
    W = glb.accessor(a["WEIGHTS_0"]).astype(np.float64)
    names = [glb.json["nodes"][k]["name"] for k in glb.json["skins"][0]["joints"]]
    dom = J[np.arange(len(J)), W.argmax(1)]
    water = np.array([names[d].startswith("Tail_") for d in dom])
    # foam = the bottom flare: low and wider than the column just above it
    r = np.hypot(P[:, 0], P[:, 2])
    y = P[:, 1]
    col_r = np.median(r[water & (y > 0.25) & (y < 0.45)])
    foam = water & (y < 0.16) & (r > 1.05 * col_r)
    return P, UV, I, water, foam


def write_glb_with_colors(src: Path, dst: Path, colors: np.ndarray):
    b = src.read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + n])
    off = 20 + n
    bl = struct.unpack("<I", b[off:off + 4])[0]
    binc = bytearray(b[off + 8:off + 8 + bl])
    while len(binc) % 4:
        binc.append(0)
    data = colors.astype(np.float32).tobytes()
    js["bufferViews"].append({"buffer": 0, "byteOffset": len(binc), "byteLength": len(data), "target": 34962})
    binc += data
    while len(binc) % 4:
        binc.append(0)
    js["buffers"][0]["byteLength"] = len(binc)
    js["accessors"].append({"bufferView": len(js["bufferViews"]) - 1, "componentType": 5126,
                            "count": int(colors.shape[0]), "type": "VEC4"})
    for prim in js["meshes"][0]["primitives"]:
        prim["attributes"]["COLOR_0"] = len(js["accessors"]) - 1
    jb = json.dumps(js, separators=(",", ":")).encode()
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(binc)
    with open(dst, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A))
        f.write(jb)
        f.write(struct.pack("<II", len(binc), 0x004E4942))
        f.write(binc)


# ---------------------------------------------------------------- texel rasterisation

def rasterise(P, UV, I, tri_mask, size):
    """Per texel: rest-pose 3D position and coverage for the masked triangles (glTF UV: v down)."""
    pos = np.zeros((size, size, 3), np.float32)
    cov = np.zeros((size, size), bool)
    uv = UV * size - 0.5
    for t in np.nonzero(tri_mask)[0]:
        a, b, c = I[t]
        x0, y0 = uv[a]
        x1, y1 = uv[b]
        x2, y2 = uv[c]
        xmin, xmax = int(np.floor(min(x0, x1, x2))), int(np.ceil(max(x0, x1, x2)))
        ymin, ymax = int(np.floor(min(y0, y1, y2))), int(np.ceil(max(y0, y1, y2)))
        xmin, ymin = max(xmin, 0), max(ymin, 0)
        xmax, ymax = min(xmax, size - 1), min(ymax, size - 1)
        if xmax < xmin or ymax < ymin:
            continue
        gx, gy = np.meshgrid(np.arange(xmin, xmax + 1), np.arange(ymin, ymax + 1))
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-12:
            continue
        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / d
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / d
        l2 = 1 - l0 - l1
        eps = -0.02
        inside = (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        if not inside.any():
            continue
        p = l0[..., None] * P[a] + l1[..., None] * P[b] + l2[..., None] * P[c]
        pos[gy[inside], gx[inside]] = p[inside]
        cov[gy[inside], gx[inside]] = True
    return pos, cov


def value_noise3(p: np.ndarray, cell: float, seed: int) -> np.ndarray:
    """Trilinear value noise in [0,1] at 3D points p (..., 3), lattice spacing `cell`."""
    q = p / cell
    i = np.floor(q).astype(np.int64)
    f = q - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        v = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
        v = (v ^ (v >> 13)) * 1274126177
        return ((v ^ (v >> 16)) & 0xFFFF) / 65535.0

    out = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[..., 0] if dx else 1 - f[..., 0]) * (f[..., 1] if dy else 1 - f[..., 1]) * (f[..., 2] if dz else 1 - f[..., 2])
                out = out + w * h(i[..., 0] + dx, i[..., 1] + dy, i[..., 2] + dz)
    return out


def dilate_into(img: np.ndarray, cov: np.ndarray, src: np.ndarray):
    """Fill texels outside `cov` from the nearest covered texel of `src` (seam padding)."""
    idx = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
    return src[idx[0], idx[1]]


# ---------------------------------------------------------------- DEF-derived statistics

def def_stats():
    rep = json.loads((ROOT / "artifacts/homm3_vfx_experiments/oceanid/evidence/water_motion.json").read_text())
    boil = rep["clips"]["02"]["loopAnalysis"]["boil"]
    col_px = rep["clips"]["02"]["pairs"][0]["columnPx"]
    foam_px = rep["clips"]["02"]["pairs"][0]["foamPx"]
    return {
        "columnHighlightFrac": float(np.mean(boil["column"]["highlightPxPerFrame"]) / col_px),
        "foamHighlightFrac": float(np.mean(boil["foam"]["highlightPxPerFrame"]) / foam_px),
    }


def def_water_palette():
    """DEF idle water pixels (column, foam), each sorted by luma: the palette the B2 atlas maps onto."""
    files = sorted(glob.glob(os.path.join(wm.DEFAULT_DEF_DIR, "02_*.png")))
    col, foam = [], []
    for f in files:
        fr = np.array(Image.open(f).convert("RGBA"))
        sg = wm.segment(fr)
        col.append(fr[sg["column"], :3])
        foam.append(fr[sg["foam"], :3])
    out = {}
    for k, v in (("column", col), ("foam", foam)):
        px = np.concatenate(v).astype(np.float32) / 255
        out[k] = px[np.argsort(px @ wm.LUMA, kind="stable")]
    return out


def palette_map(score: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Rank-preserving map: the texel at score-quantile q takes the DEF colour at luma-quantile q."""
    r = np.argsort(np.argsort(score, kind="stable"), kind="stable") / max(1, len(score) - 1)
    return palette[np.minimum((r * len(palette)).astype(int), len(palette) - 1)]


def cell_sequences(def_dir: str) -> dict:
    """Atlas cell per DEF frame: new cell when the DEF redraws the water, same cell when it holds."""
    out = {}
    for clip, g in CLIP_GROUPS.items():
        files = sorted(glob.glob(os.path.join(def_dir, f"{g}_*.png")))
        frames = [np.array(Image.open(f).convert("RGBA")) for f in files]
        seen, cells, nxt = [], [], 0
        for fr in frames:
            hit = None
            for k, (prev, cell) in enumerate(seen):
                if np.array_equal(prev, fr):
                    hit = cell
                    break
            if hit is None:
                hit = nxt % (GRID[0] * GRID[1])
                nxt += 1
            seen.append((fr, hit))
            cells.append(hit)
        out[clip] = {"group": g, "cells": cells}
    return out


def periodic_noise(n: int, feature_px: float, rng) -> np.ndarray:
    """Tileable band-limited noise in [0,1] (white noise low-passed in the Fourier domain)."""
    f = np.fft.fftfreq(n)
    k = np.hypot(f[:, None], f[None, :])
    spec = np.fft.fft2(rng.standard_normal((n, n))) * np.exp(-(k * feature_px) ** 2 * 4)
    x = np.real(np.fft.ifft2(spec))
    x = (x - x.min()) / (x.max() - x.min() + 1e-9)
    return x


def write_scroll_tile(albedo, cov, stats, seed, n=256):
    """Candidate A: a tileable water tile for a cylindrical UV (u = around the column, v = down it).

    One tile spans the column's circumference (~1.9 world units ~= 75 DEF px) in u, so one DEF px is
    ~3.4 texels. Colours are the Meshy water texels' own distribution; speckle and highlights use
    the same sizes and the DEF highlight fraction as the boil atlas.
    """
    rng = np.random.default_rng(seed)
    wat = albedo[cov]
    lum = wat @ np.array([0.299, 0.587, 0.114])
    order = np.argsort(lum)
    ramp = wat[order][np.linspace(0, len(order) - 1, 256).astype(int)]
    texel_per_defpx = n / 75.0
    base = periodic_noise(n, 6 * texel_per_defpx, rng)
    speck = periodic_noise(n, 1.2 * texel_per_defpx, rng)
    v = np.clip(0.55 * base + 0.45 * speck, 0, 1)
    v = (v - v.min()) / (v.max() - v.min())
    rgb = ramp[(v * 255).astype(int)]
    hl = periodic_noise(n, 1.0 * texel_per_defpx, rng)
    rgb[hl > np.quantile(hl, 1 - stats["columnHighlightFrac"])] = [0.99, 0.98, 0.90]
    Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).save(OUT / "scroll_tile.png")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    glb = Glb(SRC_GLB)
    P, UV, I, water, foam = load_mesh(glb)
    colors = np.zeros((len(P), 4), np.float32)
    colors[:, 0] = water
    colors[:, 1] = foam
    colors[:, 3] = 1
    write_glb_with_colors(SRC_GLB, OUT / "hota_cove_oceanid_waterlab.glb", colors)

    N = a.cell
    tri_w = water[I].all(1)
    tri_f = foam[I].sum(1) >= 2
    pos, cov = rasterise(P, UV, I, tri_w, N)
    _, cov_f = rasterise(P, UV, I, tri_f & tri_w, N)
    _, cov_all = rasterise(P, UV, I, np.ones(len(I), bool), N)  # any triangle: never pad over these
    albedo = np.asarray(glb.image(glb.base_color_image_index()).convert("RGB").resize((N, N), Image.LANCZOS)).astype(np.float32) / 255
    stats = def_stats()
    # speckle / highlight sizes in DEF pixels (1 DEF px = DEF_PX_UNITS world units)
    speck_cell = 1.2 * DEF_PX_UNITS
    hl_cell = 1.0 * DEF_PX_UNITS
    cells_rgb, cells_sparkle, cells_def = [], [], []
    pal = def_water_palette()
    lum = albedo @ wm.LUMA
    for k in range(GRID[0] * GRID[1]):
        seed = a.seed * 100 + k
        n1 = value_noise3(pos, speck_cell, seed)
        n2 = value_noise3(pos, speck_cell * 2.5, seed + 50)
        speck = 0.62 * n1 + 0.38 * n2  # 0..1
        gain = 0.55 + 0.9 * speck      # dark troughs / light crests, mean ~1
        hn = value_noise3(pos, hl_cell, seed + 99)
        frac = np.where(cov_f, stats["foamHighlightFrac"], stats["columnHighlightFrac"])
        # threshold each texel's noise at the quantile giving the DEF's highlight fraction
        thr_col = np.quantile(hn[cov & ~cov_f], 1 - stats["columnHighlightFrac"]) if (cov & ~cov_f).any() else 1
        thr_foam = np.quantile(hn[cov_f], 1 - stats["foamHighlightFrac"]) if cov_f.any() else 1
        hl = cov & (hn > np.where(cov_f, thr_foam, thr_col))
        rgb = albedo.copy()
        boiled = np.clip(albedo * gain[..., None], 0, 1)
        cream = np.array([0.99, 0.98, 0.90], np.float32)
        boiled[hl] = cream
        rgb[cov] = boiled[cov]
        # pad water islands outward so mips/bilinear at seams read water, not the old texel
        pad = dilate_into(rgb, cov, rgb)
        band = ndimage.binary_dilation(cov, iterations=4) & ~cov_all
        rgb[band] = pad[band]
        sp = np.zeros((N, N, 4), np.float32)
        sp[hl] = [*cream, 1.0]
        sp[..., :3][~hl] = 0.8  # colour under zero alpha; keeps bilinear fringes light
        cells_rgb.append(rgb)
        # B2: same boil field and highlights, but the water takes the DEF's own palette by rank
        score = lum * gain + 10.0 * hl  # highlights sort to the top
        rgb2 = albedo.copy()
        for region, key in ((cov & ~cov_f, "column"), (cov & cov_f, "foam")):
            if region.any():
                rgb2[region] = palette_map(score[region], pal[key])
        pad2 = dilate_into(rgb2, cov, rgb2)
        rgb2[band] = pad2[band]
        cells_def.append(rgb2)
        cells_sparkle.append(sp)
        del frac

    def atlas(cells, ch):
        cw, chh = N + 2 * GUTTER, N + 2 * GUTTER
        img = np.zeros((chh * GRID[1], cw * GRID[0], ch), np.float32)
        for k, c in enumerate(cells):
            cx, cy = k % GRID[0], k // GRID[0]
            padded = np.pad(c, ((GUTTER, GUTTER), (GUTTER, GUTTER), (0, 0)), mode="edge")
            img[cy * chh:(cy + 1) * chh, cx * cw:(cx + 1) * cw] = padded
        return img

    A = atlas(cells_rgb, 3)
    Image.fromarray((A * 255 + 0.5).astype(np.uint8)).save(OUT / "boil_atlas.png")
    Image.fromarray((atlas(cells_def, 3) * 255 + 0.5).astype(np.uint8)).save(OUT / "boil_atlas_defpal.png")
    S = atlas(cells_sparkle, 4)
    Image.fromarray((S * 255 + 0.5).astype(np.uint8), "RGBA").save(OUT / "sparkle_atlas.png")
    Image.fromarray((cells_rgb[0] * 255 + 0.5).astype(np.uint8)).save(OUT / "scroll_base.png")
    Image.fromarray((albedo * 255 + 0.5).astype(np.uint8)).save(OUT / "albedo_cell.png")
    write_scroll_tile(albedo, cov, stats, a.seed)

    # _MainTex_ST for a cell (Unity UV: v up; glTFast flips glTF v, so atlas row 0 is at the TOP)
    W_px, H_px = A.shape[1], A.shape[0]
    cw, chh = N + 2 * GUTTER, N + 2 * GUTTER
    st = []
    for k in range(GRID[0] * GRID[1]):
        cx, cy = k % GRID[0], k // GRID[0]
        sx, sy = N / W_px, N / H_px
        ox = (cx * cw + GUTTER) / W_px
        oy = 1 - ((cy + 1) * chh - GUTTER) / H_px  # bottom of the cell's content, from the image bottom
        st.append([sx, sy, ox, oy])
    seqs = cell_sequences(wm.DEFAULT_DEF_DIR)
    meta = {
        "schema": "homm3_oceanid_waterlab.v1",
        "glb": str((OUT / "hota_cove_oceanid_waterlab.glb").relative_to(ROOT)).replace("\\", "/"),
        "sourceGlb": str(SRC_GLB.relative_to(ROOT)).replace("\\", "/"),
        "cell": N, "gutter": GUTTER, "grid": list(GRID), "atlasSize": [W_px, H_px],
        "cellST": st, "clips": seqs, "defStats": stats,
        "waterVertices": int(water.sum()), "foamVertices": int(foam.sum()), "vertices": int(len(P)),
        "waterTriangles": int(tri_w.sum()), "triangles": int(len(I)),
        "waterTexelFrac": float(cov.mean()),
        "speckleCellDefPx": 1.2, "highlightCellDefPx": 1.0,
    }
    (OUT / "cells.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k not in ("cellST",)}, indent=1))


if __name__ == "__main__":
    main()
