"""Conflux full-3D, phase 3: vanilla Olden Era terrain detail over the HoMM3 macro colour.

The 2026-09-27 in-game review of phase 2: the terrain reads far lower-resolution than the building meshes. The terrain
albedo is registered to the HoMM3 town screen (800x374 shown at 1440x673), so inside the town rect it carries 0.56
source texels per 1080p screen pixel however large the texture is; the buildings carry their own 1024 textures.

This module keeps the HoMM3-derived albedo as the macro colour (the only composition and colour reference) and
multiplies in tiling high-frequency detail from the game's own terrain textures:
  * sources   vanilla Texture2D assets read (read-only, UnityPy) from the installed game's resources.assets and cached
              on F: (DETAIL_SOURCES; provenance in detail_sources.json). Nothing is AI-generated, upscaled or blurred.
  * detail    each source is turned into a modulation map with mean 1 per channel (linear): its luminance over a
              wrap-around Gaussian of size/HP_DIV (grain, not the tile's own blotches), plus a fraction of its chroma
              ratio (the native micro-hue, e.g. grass tips), raised to the layer's strength. The macro colour
              survives on average; the detail only adds what the macro map cannot hold. On grass and dirt it
              multiplies a macro whose own sub-2-px painted grain is damped to MACRO_KEEP; painted shadows (linear
              luminance well under its surroundings, SHADOW_REL) fade the detail out so the HoMM3 light/shade modelling of the crags survives.
  * splat     per frame pixel, from the macro map's own classes (build_conflux_full3d_scene.classify: grass, forest,
              rock, snow, dirt) and slope: steep grass/forest turns to rock, a ~1.5 m band along every river bank is
              dirt; water and sky take none. Weights are softened (Gaussian, 2 px) and upsampled to the bake.
  * projection two only. Level ground seen from above: top-down world x/z at the vanilla tile size, tiled LEVEL_STEP x
              coarser per level with distance (continuous in log footprint, coarser levels weaker: LEVEL_GAIN).
              Everything else (grazing meadow, slopes, the right cliff, mountain faces): the fixed reference camera's
              image plane at SCREEN_TEXEL_PX frame px per detail texel, two octaves, prefiltered to the bake texel.
              The camera never moves, so this is undistorted and as dense as the screen can show; a 3-axis triplanar
              on the depth-derived normals smeared the pattern along the view (measured and rejected).
Used by bake_albedo's caller for the terrain and by the footing skirts (same world positions, so the two continue).
Proof tier: generated artifact / editor render. Not in-game.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

import conflux_full3d_env as E

GAME_DATA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
# layer -> (vanilla Texture2D name, expected width, tile metres at level 0, strength, chroma share)
DETAIL_SOURCES = {
    "grass": ("grass1", 512, 2.4, 3.2, 0.35),
    "dirt": ("dirt_ground3", 512, 2.4, 3.4, 0.3),
    "rock": ("512_6_dirt_rock4_diffuse", 512, 3.2, 0.8, 0.0),
    "snow": ("Snow2", 1024, 5.0, 5.0, 0.2),
}
LAYERS = tuple(DETAIL_SOURCES)
LEVEL_STEP = 4.0
LEVEL_GAIN = (1.0, 0.95, 0.85, 0.75)
BANK_M = 1.5
# A detail texel spans this many bake texels: 2 = one 1080p screen pixel, the finest scale that survives the GPU's
# mip selection (the bake holds 2 texels per pixel, so the runtime samples it about one mip down).
TEXEL_PER_BAKE = 0.6   # top projection: detail texels are this many bake texels (0.3 frame px, prefiltered)
MACRO_SIGMA_PX = 2.0   # frame px: the macro's low-pass
SCREEN_TEXEL_PX = 0.3  # image-plane projection: frame px per detail texel (texture grain spans tens of texels)
OCTAVE_GAIN = (0.7, 0.45)  # image-plane octaves at 1x and 2x SCREEN_TEXEL_PX
HP_DIV = 24.0          # detail keeps features up to size/HP_DIV texels: grain, not blotches
SHADOW_REL = (0.3, 0.7)  # detail fades where macro luminance / its local mean falls from 0.7 to 0.3
SHADOW_SIGMA_PX = 12.0   # frame px: the local mean for SHADOW_REL
EXT_SIGMA_PX = 10.0     # frame px: the extension macro's low-pass
EXT_KEEP = 0.4          # share of the extension macro's mid/high-frequency pattern kept
EXT_BLOTCH_SIGMA_PX = 60.0  # frame px: the extension's broad base the dark blotches are measured against
EXT_BLOTCH_GAMMA = 0.45     # blotch contrast kept (ratio to the base, as a power): the smeared dark patches flatten
EXT_DETAIL_GAIN = 1.35      # detail gain in the extension (the near field the player sees most)
MACRO_KEEP = 0.75      # share of the macro's own painted grain kept above it


def extract_sources(cache: Path) -> dict:
    """Cache each DETAIL_SOURCES texture as PNG under `cache` (read-only UnityPy on the installed game)."""
    cache.mkdir(parents=True, exist_ok=True)
    prov_path = cache / "detail_sources.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.is_file() else {}
    missing = [k for k, (name, *_r) in DETAIL_SOURCES.items() if not (cache / f"{name}.png").is_file() or name not in prov]
    if missing:
        import UnityPy

        env = UnityPy.load(str(GAME_DATA / "resources.assets"))
        want = {DETAIL_SOURCES[k][0]: DETAIL_SOURCES[k][1] for k in missing}
        for o in env.objects:
            if o.type.name != "Texture2D":
                continue
            tt = o.read_typetree()
            nm = tt.get("m_Name")
            if nm in want and tt.get("m_Width") == want[nm]:
                del want[nm]  # first match by name + width
                o.read().image.convert("RGB").save(cache / f"{nm}.png")
                prov[nm] = {"file": "resources.assets", "pathId": int(o.path_id), "width": tt["m_Width"],
                            "height": tt["m_Height"]}
        prov_path.write_text(json.dumps(prov, indent=1), encoding="utf-8")
    for k, (name, w, *_r) in DETAIL_SOURCES.items():
        if not (cache / f"{name}.png").is_file():
            raise SystemExit(f"detail source {name} ({w}px) not found in {GAME_DATA / 'resources.assets'}")
        prov[name]["sha256"] = hashlib.sha256((cache / f"{name}.png").read_bytes()).hexdigest()
    return prov


def _wrap_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    h, w = img.shape[:2]
    big = np.tile(img, (3, 3, 1) if img.ndim == 3 else (3, 3))
    return cv2.GaussianBlur(big, (0, 0), sigma)[h:2 * h, w:2 * w]


def _mips(d: np.ndarray, n: int = 6) -> list[np.ndarray]:
    out = [d]
    for _ in range(n):
        h, w = out[-1].shape[:2]
        if h < 8:
            break
        out.append(cv2.resize(out[-1], (w // 2, h // 2), interpolation=cv2.INTER_AREA))
    return out


class Detail:
    def __init__(self, cache: Path):
        from PIL import Image

        self.prov = extract_sources(cache)
        self.maps = {}
        for k, (name, _w, tile, strength, chroma) in DETAIL_SOURCES.items():
            t = E.srgb_to_lin(np.asarray(Image.open(cache / f"{name}.png").convert("RGB")).astype(np.float32) / 255)
            s = t.shape[0]
            L = np.maximum(E.lum(t), 1e-4)
            Lb = np.maximum(_wrap_blur(L, s / HP_DIV), 1e-4)
            rl = L / Lb
            rc = (t + 1e-4) / (_wrap_blur(t, s / HP_DIV) + 1e-4) / rl[..., None]
            d = np.power(rl, strength)[..., None] * np.power(np.clip(rc, 0.5, 2.0), strength * chroma)
            d = np.clip(d, 0.35, 2.2).astype(np.float32)
            d /= d.reshape(-1, 3).mean(0)  # exactly mean 1 per channel: the macro colour survives on average
            self.maps[k] = {"mips": _mips(d), "size": s, "tile": tile}

    @staticmethod
    def _bilinear(tex: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        h, w = tex.shape[:2]
        x = np.mod(u, 1.0) * w - 0.5
        y = np.mod(v, 1.0) * h - 0.5
        x0 = np.floor(x).astype(np.int64)
        y0 = np.floor(y).astype(np.int64)
        fx = (x - x0)[:, None].astype(np.float32)
        fy = (y - y0)[:, None].astype(np.float32)
        x0 %= w; y0 %= h
        x1 = (x0 + 1) % w; y1 = (y0 + 1) % h
        return ((tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx) * (1 - fy)
                + (tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx) * fy)

    def _trilinear(self, mips: list, u: np.ndarray, v: np.ndarray, mip: np.ndarray) -> np.ndarray:
        """Wrap-around bilinear lookup at a fractional mip level per point."""
        out = np.zeros((len(u), 3), np.float32)
        mip = np.clip(mip, 0, len(mips) - 1.001)
        m0 = np.floor(mip).astype(np.int64)
        fr = (mip - m0).astype(np.float32)[:, None]
        for lv in np.unique(m0):
            s = m0 == lv
            a = self._bilinear(mips[lv], u[s], v[s])
            b = self._bilinear(mips[lv + 1], u[s], v[s])
            out[s] = a * (1 - fr[s]) + b * fr[s]
        return out

    def modulation(self, P: np.ndarray, N: np.ndarray, weights: np.ndarray, foot_m: np.ndarray, scr: np.ndarray,
                   cosv: np.ndarray, bake_px: float) -> np.ndarray:
        """Per point: the mean-1 RGB detail modulation. weights (n, len(LAYERS)) in [0,1] (sum <= 1; the remainder is
        no detail), foot_m = metres covered by one bake texel at that point, N a smoothed normal, scr (n, 2) the
        point's 1080p frame pixel, cosv |normal . view|, bake_px = frame px per texel of the texture being baked.
        Two projections only. Level ground seen from above takes a top-down world projection (x/z, metres), levels
        of LEVEL_STEP blended by footprint. Everything else - grazing ground (the far meadow), slopes, cliffs and
        mountain faces - takes the reference camera's own image plane at SCREEN_TEXEL_PX frame pixels per detail
        texel (plus a second octave at twice that), prefiltered to the bake's texel: the camera is fixed, so the
        pattern is undistorted and its features (the textures draw grain over tens of texels) land at a few px.
        A 3-axis triplanar (and an orthographic camera-plane projection) on the
        depth-derived geometry smeared the pattern along the view."""
        n = len(P)
        wt = (E.smoothstep(0.8, 0.95, N[:, 1]) * E.smoothstep(0.5, 0.7, cosv)).astype(np.float32)
        acc = np.zeros((n, 3), np.float32)
        wsum = np.zeros(n, np.float32)
        pu_top, pv_top = P[:, 0], -P[:, 2]
        for li, k in enumerate(LAYERS):
            wk = weights[:, li]
            sel = np.nonzero(wk > 0.01)[0]
            if len(sel) == 0:
                continue
            m = self.maps[k]
            dk = np.zeros((len(sel), 3), np.float32)
            w_top = wt[sel]
            # image plane (screen space): one detail texel per SCREEN_TEXEL_PX frame px, mip-filtered to the bake texel
            b = np.nonzero(w_top < 0.99)[0]
            if len(b):
                ids = sel[b]
                sz = m["size"] * SCREEN_TEXEL_PX
                off = 0.37 + 0.11 * li
                m1 = np.full(len(ids), max(math.log2(bake_px / SCREEN_TEXEL_PX), 0.0))
                s1 = self._trilinear(m["mips"], scr[ids, 0] / sz + off, scr[ids, 1] / sz + off * 0.6, m1)
                s2 = self._trilinear(m["mips"], scr[ids, 0] / (2 * sz) + off * 1.7, scr[ids, 1] / (2 * sz),
                                     np.maximum(m1 - 1, 0))
                smp = 1 + (s1 - 1) * OCTAVE_GAIN[0] + (s2 - 1) * OCTAVE_GAIN[1]
                dk[b] += smp * (1 - w_top[b])[:, None]
            a = np.nonzero(w_top > 0.01)[0]
            if len(a):
                ids = sel[a]
                fs = foot_m[ids]
                lam = np.clip(np.log(np.maximum(TEXEL_PER_BAKE * fs * m["size"] / m["tile"], 1e-9))
                              / math.log(LEVEL_STEP), 0, len(LEVEL_GAIN) - 1.001)
                k0 = np.floor(lam).astype(np.int64)
                fr = (lam - k0).astype(np.float32)
                top = np.zeros((len(a), 3), np.float32)
                for lev in np.unique(np.r_[k0, k0 + 1]):
                    wl = np.where(k0 == lev, 1 - fr, 0) + np.where(k0 + 1 == lev, fr, 0)
                    s_ = np.nonzero(wl > 1e-3)[0]
                    if len(s_) == 0:
                        continue
                    tile = m["tile"] * LEVEL_STEP ** lev
                    mip = np.log2(np.maximum(fs[s_] / (tile / m["size"]), 1e-9))
                    smp = self._trilinear(m["mips"], pu_top[ids[s_]] / tile, pv_top[ids[s_]] / tile, mip)
                    top[s_] += (1 + (smp - 1) * LEVEL_GAIN[lev]) * wl[s_, None]
                dk[a] += top * w_top[a][:, None]
            acc[sel] += dk * wk[sel, None]
            wsum[sel] += wk[sel]
        out = np.ones((n, 3), np.float32)
        has = wsum > 0
        out[has] = acc[has] / wsum[has, None]
        t = np.clip(wsum, 0, 1)[:, None]
        return out * t + (1 - t)


def splat_weights(ctx, cls: np.ndarray, nf: np.ndarray, zfill: np.ndarray, water: np.ndarray, classes: dict) -> np.ndarray:
    """(H, W, len(LAYERS)) detail weights at frame resolution from the macro classes, slope and river banks."""
    from scipy.ndimage import distance_transform_edt

    H, W = cls.shape
    g = (cls == classes["GRASS"]).astype(np.float32)
    f = (cls == classes["FOREST"]).astype(np.float32)
    r = (cls == classes["ROCK"]).astype(np.float32)
    s = (cls == classes["SNOW"]).astype(np.float32)
    d = (cls == classes["DIRT"]).astype(np.float32)
    slope = np.degrees(np.arccos(np.clip(nf[..., 1], -1, 1)))
    steep = E.smoothstep(40.0, 58.0, slope).astype(np.float32)
    grass = (g + f) * (1 - steep)
    rock = r + (g + f) * steep
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    m_px = 2 * zfill * t / H
    dist_px = distance_transform_edt(~water)
    bank = (1 - E.smoothstep(0.6, 1.0, dist_px * m_px / BANK_M)).astype(np.float32) * (1 - water)
    bank *= (1 - s) * (cls != classes["SKY"])
    dirt = d + bank * (grass + rock * 0.5)
    grass = grass * (1 - bank)
    rock = rock * (1 - 0.5 * bank)
    wts = np.stack([grass, dirt, rock, s], -1)
    wts = cv2.GaussianBlur(wts, (0, 0), 2.0)
    tot = wts.sum(-1, keepdims=True)
    wts = np.where(tot > 1, wts / np.maximum(tot, 1e-6), wts)
    wts[water | (cls == classes["SKY"])] = 0
    return wts.astype(np.float32)


def _grid(x0, y0, tw, th, scale, W, H):
    ty, tx = np.mgrid[0:th, 0:tw]
    px = np.clip(x0 + (tx + 0.5) / scale - 0.5, 0, W - 1).ravel()
    py = np.clip(y0 + (ty + 0.5) / scale - 0.5, 0, H - 1).ravel()
    return px, py


def _remap(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear lookup of img at float pixel coords (cv2.remap limits each map axis to < 32767: 4096-wide rows)."""
    n = len(x)
    cols = 4096
    rows = -(-n // cols)
    pad = rows * cols - n
    mx = np.r_[x, np.zeros(pad, np.float32)].reshape(rows, cols).astype(np.float32)
    my = np.r_[y, np.zeros(pad, np.float32)].reshape(rows, cols).astype(np.float32)
    out = cv2.remap(np.ascontiguousarray(img, dtype=np.float32), mx, my, cv2.INTER_LINEAR)
    return out.reshape((rows * cols,) + out.shape[2:])[:n]


def apply_to_frame_texture(ctx, det: Detail, alb_lin: np.ndarray, x0: int, y0: int, scale: float, zmap: np.ndarray,
                           nmap: np.ndarray, wts: np.ndarray, keep: np.ndarray | None = None,
                           rows: int = 256, town_rect: tuple | None = None) -> np.ndarray:
    """Multiply the detail into a frame-registered albedo (texel (i, j) = frame pixel (x0 + (j+0.5)/scale - 0.5, ...)).
    zmap / nmap / wts are frame-resolution (depth along fwd, normals, splat weights); keep masks texels to modulate."""
    th, tw = alb_lin.shape[:2]
    H, W = zmap.shape
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    # The macro keeps the HoMM3 colour at low frequency; its own painted grain (0.56 source texels per pixel, the
    # blur the review saw) is damped to MACRO_KEEP so the vanilla detail carries the high frequencies.
    soft = cv2.GaussianBlur(alb_lin, (0, 0), MACRO_SIGMA_PX * scale)
    # Only grass and dirt: the painted crags and snow fields carry their own drawn edges, which the damping erased
    # (measured: the Altar of Air crags lost their lit faces).
    damp = wts[..., LAYERS.index("grass")] + wts[..., LAYERS.index("dirt")]
    live_w = np.clip(_remap(damp, *_grid(x0, y0, tw, th, scale, W, H)).reshape(th, tw), 0, 1)[..., None]
    out = alb_lin * (1 - live_w) + (soft + MACRO_KEEP * (alb_lin - soft)) * live_w
    if town_rect is not None:
        # Outside the HoMM3 rect the macro is tiled painting crops (0.6 source texels/px): their mid-scale dark
        # blotches overpowered the detail nearest the camera. Keep their colour, flatten their pattern to EXT_KEEP.
        gx, gy = _grid(x0, y0, tw, th, scale, W, H)
        ext = ((gx >= town_rect[0]) | (gy >= town_rect[1])).reshape(th, tw).astype(np.float32)
        ext = cv2.GaussianBlur(ext, (0, 0), 8.0 * scale)[..., None] * live_w
        low = cv2.GaussianBlur(out, (0, 0), EXT_SIGMA_PX * scale)
        # Phase 3b: the blotches themselves (tens of px, below EXT_SIGMA_PX's reach) are compressed toward a broad
        # base as a luminance ratio, so their hue stays and the smeared dark patches stop dominating the near field.
        base = cv2.GaussianBlur(low, (0, 0), EXT_BLOTCH_SIGMA_PX * scale)
        ratio = (E.lum(low) + 1e-4) / (E.lum(base) + 1e-4)
        low_c = low * (np.power(ratio, EXT_BLOTCH_GAMMA) / ratio)[..., None]
        out = out * (1 - ext) + (low_c + EXT_KEEP * (out - low)) * ext
        gain = 1.0 + (EXT_DETAIL_GAIN - 1.0) * ext[..., 0]
        # The shadow gate reads the flattened extension (its blotches are not painted shadows).
        lm = E.lum(alb_lin) * (1 - ext[..., 0]) + E.lum(out) * ext[..., 0]
    else:
        gain = np.ones((th, tw), np.float32)
        lm = E.lum(alb_lin)
    rel = lm / (cv2.GaussianBlur(lm, (0, 0), SHADOW_SIGMA_PX * scale) + 1e-4)
    for r0 in range(0, th, rows):
        r1 = min(th, r0 + rows)
        ty, tx = np.mgrid[r0:r1, 0:tw]
        px = x0 + (tx + 0.5) / scale - 0.5
        py = y0 + (ty + 0.5) / scale - 0.5
        if keep is not None:
            m = keep[r0:r1]
            px, py, ty, tx = px[m], py[m], ty[m], tx[m]
        else:
            px, py, ty, tx = px.ravel(), py.ravel(), ty.ravel(), tx.ravel()
        if len(px) == 0:
            continue
        mx = np.clip(px, 0, W - 1).astype(np.float32)
        my = np.clip(py, 0, H - 1).astype(np.float32)
        z = _remap(zmap, mx, my)
        nn = _remap(nmap, mx, my)
        nn /= np.linalg.norm(nn, axis=-1, keepdims=True) + 1e-9
        wv = _remap(wts, mx, my)
        if wv.ndim == 1:
            wv = wv[:, None]
        live = wv.sum(1) > 0.01
        if not live.any():
            continue
        px, py, z, nn, wv, ty, tx = px[live], py[live], z[live], nn[live], wv[live], ty[live], tx[live]
        P = ctx.cpos + E.rays(ctx.cam, px, py) * z[:, None]
        view = ctx.cpos - P
        view /= np.linalg.norm(view, axis=-1, keepdims=True) + 1e-9
        cosv = np.clip(np.abs((nn * view).sum(-1)), 0.1, 1)
        foot_scr = (2 * z * t / H) / scale
        foot = foot_scr / np.sqrt(cosv)
        mod = det.modulation(P, nn, wv, foot, np.stack([px, py], -1), cosv, 1.0 / scale)
        # Painted shadows stay flat: detail fades out where the macro is much darker than its surroundings (texture
        # multiplied into the dark crag faces read as a grey haze over the HoMM3 light/shade modelling).
        k = E.smoothstep(SHADOW_REL[0], SHADOW_REL[1], rel[ty, tx])[:, None].astype(np.float32)
        out[ty, tx] = out[ty, tx] * np.maximum(1 + (mod - 1) * k * gain[ty, tx][:, None], 0.05)
    mx_ = out.max(-1, keepdims=True)
    return np.where(mx_ > 0.95, out * 0.95 / np.maximum(mx_, 1e-6), out)


def density_map(ctx, det: Detail, zmap: np.ndarray, nmap: np.ndarray, wts: np.ndarray, bake_scale: float) -> np.ndarray:
    """Detail texels per 1080p screen pixel at each frame pixel (0 where no detail), capped by the bake's own
    texels per pixel (the texture the runtime samples)."""
    H, W = zmap.shape
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    ys, xs = np.mgrid[0:H, 0:W]
    P = ctx.cpos + E.rays(ctx.cam, xs.astype(np.float64), ys.astype(np.float64)) * zmap[..., None]
    view = ctx.cpos - P
    view /= np.linalg.norm(view, axis=-1, keepdims=True) + 1e-9
    cosv = np.clip(np.abs((nmap * view).sum(-1)), 0.1, 1)
    m_px = 2 * zmap * t / H / np.sqrt(cosv)
    dens = np.zeros((H, W), np.float32)
    wsum = wts.sum(-1)
    for li, k in enumerate(LAYERS):
        m = det.maps[k]
        foot_bake = m_px / bake_scale
        lam = np.clip(np.log(np.maximum(TEXEL_PER_BAKE * foot_bake * m["size"] / m["tile"], 1e-9)) / math.log(LEVEL_STEP), 0,
                      len(LEVEL_GAIN) - 1.001)
        texel = m["tile"] * LEVEL_STEP ** lam / m["size"]
        dens += np.minimum(m_px / texel, bake_scale) * wts[..., li]
    # Only level ground seen from above takes the top-down projection; the rest is the image plane at
    # SCREEN_TEXEL_PX (same weight as Detail.modulation).
    wt = E.smoothstep(0.8, 0.95, nmap[..., 1]) * E.smoothstep(0.5, 0.7, cosv)
    dens = wt * dens + (1 - wt) * min(1.0 / SCREEN_TEXEL_PX, bake_scale) * np.minimum(wsum, 1)
    return np.where(wsum > 0.01, dens / np.maximum(wsum, 1e-6), 0).astype(np.float32)
