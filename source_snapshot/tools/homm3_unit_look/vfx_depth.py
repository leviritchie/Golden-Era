"""Depth-aware renders for defFlipbook layers: ``render: "unitPlane"`` and ``render: "trail"`` (opt-in).

A defFlipbook cell is DEF pixels drawn for the one HoMM3 sprite facing. A camera-facing billboard shows it the
same way from every angle, which is right for glows, sparkles and puffs and wrong for anything directional (a
blast thrown forward, a breath jet, a beam, a blade sweep): with the unit turned, a billboarded jet still
leaves the hand towards the same side of the screen.

unitPlane  Each key's effect is split into pieces (connected components of the effect mask after a 2 px
           dilation, the def_effects grouping rule). A piece is *isotropic* when it sits on the DEF origin and
           is not elongated (centroid within max(isoMinOffsetPx, isoOffsetRadius x its RMS radius) of the
           origin and PCA aspect below isoMaxAspect); it stays in the view-facing ``sheet``. A *displaced*
           piece (round, detached: no pixel within attachPx of the origin) keeps a view-facing cell whose pivot
           is offset in the unit's frame (``unitPlane.displaced``). Every other piece (elongated, or attached
           to the emitter) is a *card* piece in ``unitPlane.sheet``, drawn on a card fixed in the unit root's frame:
             sagittal card  the plane through the anchor point spanned by the unit's front and world up. The
                            DEF pixels are unprojected onto it along the sprite camera's rays, so from the
                            sprite camera it is pixel-identical to the billboard, and from the mirrored battle
                            facing it is the mirrored DEF (what HoMM3 itself shows).
             cross card     the same card turned 90 degrees about the emission axis (the unit's front through
                            the anchor): DEF-up maps to the unit's left. It shows the jet from head-on/tail-on,
                            where the sagittal card is edge-on.
           Weights: w = smoothstep(fade[0], fade[1], |left . viewDir|) on the sagittal card, 1 - w on the cross
           card (one card at a time, never double exposure). From the sprite camera w must be 1 (checked).
trail      The effect is a blade sweep: a ribbon strip between two rails that follow the weapon along the
           bone's 3D path through the clip. rail(k) = bone head + boneDir * r for r = reach - width (inner) and
           reach (outer); the strip spans the last ``historyKeys`` keys. The ribbon texture (``ramp``) is
           coloured from the DEF arc's own pixels: rows = radial bands (distance from the anchor pixel), mean
           colour and coverage of the listed frames' effect pixels in that band; columns = age (alpha fades
           newest -> oldest). reach "auto" = the 90th percentile of the effect pixels' distance from the anchor
           pixel (DEF px / pxPerUnit); widthPx "auto" = the 10-90 percentile band of that distance.

All positions and vectors in the manifest are unit-root components ``[front, left, up]`` (front = the unit's
facing, left = up x front, up = world up), so the runtime applies them in the unit root's own frame and they
turn with the unit. Proof tier: generated artifact.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

RENDERS = ("unitPlane", "trail")
UNITPLANE_KEYS = {"fade", "isoMinOffsetPx", "isoOffsetRadius", "isoMaxAspect", "attachPx", "notes"}
TRAIL_KEYS = {"bone", "boneTip", "reach", "widthPx", "historyKeys", "notes"}
DEFAULT_FADE = [0.10, 0.30]
DEFAULT_ISO = {"isoMinOffsetPx": 4.0, "isoOffsetRadius": 0.6, "isoMaxAspect": 2.0, "attachPx": 3.0}
TRAIL_HISTORY = 3
PIECE_CLASSES = ("isotropic", "displaced", "card")
RAMP_ROWS = 8


# ----------------------------------------------------------------------------- spec
def validate_layer(ly: dict, w: str) -> list[str]:
    """Errors for the unitPlane / trail blocks of a defFlipbook layer (called by spec.validate)."""
    e = []
    r = ly.get("render", "billboard")
    for blk, keys, want in (("unitPlane", UNITPLANE_KEYS, "unitPlane"), ("trail", TRAIL_KEYS, "trail")):
        if blk in ly:
            if r != want:
                e.append(f"{w}: {blk} block needs render {want!r}")
            if not isinstance(ly[blk], dict):
                e.append(f"{w}: {blk} must be an object")
                continue
            bad = set(ly[blk]) - keys
            if bad:
                e.append(f"{w}.{blk}: unknown keys {sorted(bad)}")
    up = ly.get("unitPlane", {}) if isinstance(ly.get("unitPlane"), dict) else {}
    if "fade" in up:
        f = up["fade"]
        if not (isinstance(f, list) and len(f) == 2 and all(isinstance(x, (int, float)) for x in f) and 0 <= f[0] < f[1] <= 1):
            e.append(f"{w}.unitPlane.fade must be [lo, hi] with 0 <= lo < hi <= 1")
    for k in ("isoMinOffsetPx", "isoOffsetRadius", "isoMaxAspect", "attachPx"):
        if k in up and not (isinstance(up[k], (int, float)) and up[k] > 0):
            e.append(f"{w}.unitPlane.{k} must be a number > 0")
    tr = ly.get("trail", {}) if isinstance(ly.get("trail"), dict) else {}
    if r == "trail":
        if "bone" in tr and not isinstance(tr["bone"], str):
            e.append(f"{w}.trail.bone must be a bone name")
        for k in ("reach", "widthPx"):
            if k in tr and not (tr[k] == "auto" or (isinstance(tr[k], (int, float)) and tr[k] > 0)):
                e.append(f"{w}.trail.{k} must be \"auto\" or a number > 0")
        if "historyKeys" in tr and not (isinstance(tr["historyKeys"], int) and 1 <= tr["historyKeys"] <= 12):
            e.append(f"{w}.trail.historyKeys must be an int in 1..12")
        if "boneTip" in tr and not isinstance(tr["boneTip"], bool):
            e.append(f"{w}.trail.boneTip must be a bool")
    return e


# ----------------------------------------------------------------------------- frames and projections
def unit_axes(ctx):
    vm = ctx["vmeta"]
    f = np.array(vm["front"], np.float64)
    up = np.array([0.0, 0.0, 1.0])
    left = np.cross(up, f)
    left /= np.linalg.norm(left)
    return f, left, up


def to_local(v, axes):
    f, l, u = axes
    v = np.asarray(v, np.float64)
    return [round(float(v @ f), 6), round(float(v @ l), 6), round(float(v @ u), 6)]


def from_local(c, axes):
    f, l, u = axes
    return c[0] * f + c[1] * l + c[2] * u


def view_affine(vm):
    """World -> output px for an orthographic view, fitted from its bone heads/tails (exact for ortho)."""
    W, P = [], []
    for b in vm["bones"].values():
        for end in ("head", "tail"):
            if b.get(end) is not None and b.get(end + "Px") is not None:
                W.append(b[end])
                P.append(b[end + "Px"])
    W, P = np.array(W, np.float64), np.array(P, np.float64)
    X = np.c_[W, np.ones(len(W))]
    sol, *_ = np.linalg.lstsq(X, P, rcond=None)
    err = float(np.abs(X @ sol - P).max())
    return sol[:3].T, sol[3], err          # px = A @ w + t


def card_vectors(ctx):
    """World offset per +1 cell px (x right) and per +1 cell px (y down), for both cards (world coords)."""
    cam = ctx["spritecam"]
    r, u = np.array(cam["right"], np.float64), np.array(cam["up"], np.float64)
    ppu = float(cam["pxPerUnit"])
    f, l, z = unit_axes(ctx)
    M = np.array([[r @ f, r @ z], [u @ f, u @ z]])
    if abs(np.linalg.det(M)) < 1e-3:
        raise ValueError("unitPlane: the sprite camera looks along the unit's sagittal plane; the card is degenerate")
    ax, bx = np.linalg.solve(M, [1.0 / ppu, 0.0])
    ay, by = np.linalg.solve(M, [0.0, -1.0 / ppu])
    sag = (ax * f + bx * z, ay * f + by * z)
    cross = (ax * f + bx * l, ay * f + by * l)
    return {"sagittal": sag, "cross": cross, "normals": {"sagittal": l, "cross": z}}


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def card_weights(view_dir, ctx, fade):
    f, l, z = unit_axes(ctx)
    w = smoothstep(fade[0], fade[1], abs(float(np.asarray(view_dir) @ l)))
    return {"sagittal": w, "cross": 1.0 - w}


# ----------------------------------------------------------------------------- pieces
def split_pieces(mask: np.ndarray, origin, prm) -> tuple[dict, list]:
    """Masks per piece class for one key, and the piece records.

    isotropic  round and centred on the DEF origin: view-facing, exactly as before;
    card       elongated (PCA aspect >= isoMaxAspect: jet, beam, streak) or attached to the emitter (a pixel
               within attachPx of the origin): drawn on the unit-frame card, so it stays attached;
    displaced  round, detached and away from the origin (a blast cloud thrown forward): its *position* is
               directional, its shape is not, so it is a view-facing cell whose pivot is offset in the unit's frame."""
    grp, n = ndimage.label(ndimage.binary_dilation(mask, iterations=2, structure=np.ones((3, 3), bool)),
                           structure=np.ones((3, 3), bool))
    lab = np.where(mask, grp, 0)
    out = {c: np.zeros_like(mask) for c in PIECE_CLASSES}
    rec = []
    ox, oy = origin
    for k in range(1, n + 1):
        sel = lab == k
        ys, xs = np.nonzero(sel)
        if len(xs) == 0:
            continue
        cx, cy = xs.mean(), ys.mean()
        rms = math.sqrt(float(((xs - cx) ** 2 + (ys - cy) ** 2).mean()) + 1e-9)
        if len(xs) >= 3:
            ev = np.linalg.eigvalsh(np.cov(np.vstack([xs, ys])) + np.eye(2) * 0.25)
            aspect = math.sqrt(ev[1] / ev[0])
        else:
            aspect = 1.0
        off = math.hypot(cx - ox, cy - oy)
        near = float(np.hypot(xs - ox, ys - oy).min())
        if off <= max(prm["isoMinOffsetPx"], prm["isoOffsetRadius"] * rms) and aspect < prm["isoMaxAspect"]:
            cls = "isotropic"
        elif aspect >= prm["isoMaxAspect"] or near <= prm["attachPx"]:
            cls = "card"
        else:
            cls = "displaced"
        out[cls] |= sel
        rec.append({"px": int(len(xs)), "offsetPx": round(off, 1), "rmsPx": round(rms, 1), "aspect": round(aspect, 2),
                    "nearPx": round(near, 1), "class": cls})
    return out, rec


def _sheet(cells, masks, hw, hh, seq, tx, ty, tex_scale, shifts=None):
    """Tile sheet; each key's cell is centred on its rounded DEF origin plus ``shifts[i]`` (integer px)."""
    sheet = np.zeros((ty * 2 * hh, tx * 2 * hw, 4), np.uint8)
    for i, (c, m, s) in enumerate(zip(cells, masks, seq)):
        if s < 0 or m is None:
            continue
        rgba = (c["rgba"] * 255 + 0.5).astype(np.uint8).copy()
        rgba[~m] = 0
        ox, oy = c["origin"]
        dx, dy = shifts[i] if shifts and shifts[i] else (0, 0)
        x0, y0 = int(round(ox)) + dx - hw, int(round(oy)) + dy - hh
        H, W = rgba.shape[:2]
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + 2 * hw), min(H, y0 + 2 * hh)
        r, cc = divmod(s, tx)
        cell = np.zeros((2 * hh, 2 * hw, 4), np.uint8)
        if sx1 > sx0 and sy1 > sy0:
            cell[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
        sheet[r * 2 * hh:(r + 1) * 2 * hh, cc * 2 * hw:(cc + 1) * 2 * hw] = cell
    if tex_scale > 1:
        sheet = sheet.repeat(tex_scale, 0).repeat(tex_scale, 1)
    return sheet


# ----------------------------------------------------------------------------- build
def build(ly, ctx, vdir: Path, fb: dict, layer_cells) -> dict:
    """Extend build_flipbook's per-clip entries for a unitPlane / trail layer (``layer_cells`` = vfx.layer_cells)."""
    r = ly["render"]
    for clip, ent in fb.items():
        cells = layer_cells(ly, clip, ctx)
        if r == "unitPlane":
            _build_unit_plane(ly, ctx, vdir, clip, ent, cells)
        elif r == "trail":
            _build_trail(ly, ctx, vdir, clip, ent, cells)
    return fb


def _build_unit_plane(ly, ctx, vdir, clip, ent, cells):
    up = ly.get("unitPlane", {})
    prm = {k: float(up.get(k, v)) for k, v in DEFAULT_ISO.items()}
    fade = list(up.get("fade", DEFAULT_FADE))
    cw, ch = ent["cellPx"]
    hw, hh = cw // 2, ch // 2
    seq = [k["cell"] for k in ent["keys"]]
    split, pieces = [], []
    for c, s in zip(cells, seq):
        if s < 0:
            split.append(None)
            pieces.append(None)
            continue
        m, rec = split_pieces(c["mask"], c["origin"], prm)
        split.append(m)
        pieces.append(rec)
    ts, tx, ty = ent["texelsPerDefPx"], ent["tilesX"], ent["tilesY"]

    def pick(cls):
        return [None if m is None else m[cls] for m in split]
    iso_sheet = _sheet(cells, pick("isotropic"), hw, hh, seq, tx, ty, ts)
    elo_sheet = _sheet(cells, pick("card"), hw, hh, seq, tx, ty, ts)
    # displaced: one view-facing cell per key, re-centred on the displaced pieces' centroid (integer px shift)
    shifts, dhw, dhh = [], 4, 4
    for c, m in zip(cells, split):
        if m is None or not m["displaced"].any():
            shifts.append(None)
            continue
        ys, xs = np.nonzero(m["displaced"])
        ox, oy = int(round(c["origin"][0])), int(round(c["origin"][1]))
        dx, dy = int(round(xs.mean())) - ox, int(round(ys.mean())) - oy
        shifts.append((dx, dy))
        dhw = max(dhw, int(max(abs(xs.min() - ox - dx), abs(xs.max() - ox - dx))) + 3)
        dhh = max(dhh, int(max(abs(ys.min() - oy - dy), abs(ys.max() - oy - dy))) + 3)
    dis_sheet = _sheet(cells, pick("displaced"), dhw, dhh, seq, tx, ty, ts, shifts)
    if not (elo_sheet[..., 3].any() or dis_sheet[..., 3].any()):
        raise ValueError(f"layer {ly['id']} clip {clip}: render unitPlane but every piece is isotropic "
                         "(nothing directional: use billboard)")
    base = ent["sheet"]
    if iso_sheet[..., 3].any():
        Image.fromarray(iso_sheet).save(vdir / base)
    else:
        (vdir / base).unlink(missing_ok=True)
        ent["sheet"] = None
    plane_name = dis_name = None
    if elo_sheet[..., 3].any():
        plane_name = base[:-4] + "__plane.png"
        Image.fromarray(elo_sheet).save(vdir / plane_name)
    if dis_sheet[..., 3].any():
        dis_name = base[:-4] + "__displaced.png"
        Image.fromarray(dis_sheet).save(vdir / dis_name)
    cv = card_vectors(ctx)
    axes = unit_axes(ctx)
    cam = ctx["spritecam"]
    w_sprite = card_weights(np.array(cam["forward"]), ctx, fade)
    if w_sprite["sagittal"] < 1.0:
        raise ValueError(f"layer {ly['id']}: from the sprite camera the sagittal card weighs {w_sprite['sagittal']:.3f} < 1 "
                         f"(|left . forward| below fade[1]={fade[1]}); lower unitPlane.fade so the source view stays exact")
    # the sagittal card seen by the sprite camera must be the DEF pixel grid (unprojection check)
    r_, u_, ppu = np.array(cam["right"]), np.array(cam["up"]), cam["pxPerUnit"]
    du, dv = cv["sagittal"]
    err = max(abs(du @ r_ * ppu - 1), abs(du @ u_ * ppu), abs(dv @ r_ * ppu), abs(-dv @ u_ * ppu - 1))
    ent["render"] = "unitPlane"
    ent["billboard"] = "view"
    ent["unitPlane"] = {
        "sheet": plane_name, "space": "unit root, [front, left, up] components",
        "pivot": "cell centre (the key's DEF origin) at the anchor point; position follows the anchor bone, "
                 "orientation follows the unit root (never the bone's rotation)",
        "cards": {name: {"uPerCellPx": to_local(cv[name][0], axes), "vPerCellPxDown": to_local(cv[name][1], axes),
                         "normal": to_local(cv["normals"][name], axes)} for name in ("sagittal", "cross")},
        "fade": {"sagittal": f"smoothstep({fade[0]}, {fade[1]}, |normal . viewDir|)", "cross": "1 - sagittal weight",
                 "lo": fade[0], "hi": fade[1]},
        "displaced": None if dis_name is None else {
            "sheet": dis_name, "cellPx": [2 * dhw, 2 * dhh], "sizeUnits": [2 * dhw / ppu, 2 * dhh / ppu],
            "billboard": "view",
            "pivot": "anchor + w*offset.sagittal + (1-w)*offset.cross (w = the sagittal card weight); cell centre there",
            "keys": [None if sh is None else {"offsetPx": list(sh),
                                              "offset": {n: to_local(sh[0] * cv[n][0] + sh[1] * cv[n][1], axes)
                                                         for n in ("sagittal", "cross")}} for sh in shifts]},
        "spriteView": {"sagittalWeight": round(w_sprite["sagittal"], 4), "unprojectErrPx": round(float(err), 8)},
        "pieces": [None if p is None else {c: {"n": sum(x["class"] == c for x in p),
                                               "px": sum(x["px"] for x in p if x["class"] == c)} for c in PIECE_CLASSES}
                   for p in pieces],
        "classifier": {**prm, "rule": "isotropic iff centroid offset <= max(isoMinOffsetPx, isoOffsetRadius*rmsPx) "
                                      "and PCA aspect < isoMaxAspect; else card iff aspect >= isoMaxAspect or a "
                                      "pixel lies within attachPx of the origin; else displaced. "
                                      "Pieces = 8-connected after a 2 px dilation"},
    }


def _trail_points(ly, ctx, cells, reach, width):
    tr = ly.get("trail", {})
    bone = tr.get("bone", ly["anchor"]["bone"])
    rails = []
    for c in cells:
        vm = ctx["vmeta"]["views"][f"sprite_f{c['t'] + 1:03d}"]
        b = vm["bones"][bone]
        h, t = np.array(b["head"], np.float64), np.array(b["tail"], np.float64)
        d = t - h
        d /= max(np.linalg.norm(d), 1e-9)
        o = t if tr.get("boneTip") else h
        rails.append((o + d * (reach - width), o + d * reach))
    return bone, rails


def _build_trail(ly, ctx, vdir, clip, ent, cells):
    tr = ly.get("trail", {})
    ppu = float(ctx["spritecam"]["pxPerUnit"])
    dist, cols = [], []
    for c in cells:
        if c["mask"] is None or not c["mask"].any():
            continue
        ys, xs = np.nonzero(c["mask"])
        ax, ay = c["anchor"]
        dist.append(np.hypot(xs - ax, ys - ay))
        cols.append(c["rgba"][ys, xs, :3])
    if not dist:
        raise ValueError(f"layer {ly['id']} clip {clip}: trail has no effect pixels")
    dist, cols = np.concatenate(dist), np.concatenate(cols)
    p10, p90 = np.percentile(dist, [10, 90])
    reach_px = p90 if tr.get("reach", "auto") == "auto" else float(tr["reach"]) * ppu
    width_px = max(2.0, p90 - p10) if tr.get("widthPx", "auto") == "auto" else float(tr["widthPx"])
    width_px = min(width_px, reach_px * 0.95)
    hist = int(tr.get("historyKeys", TRAIL_HISTORY))
    # ramp: rows = radial bands inner -> outer, columns = age newest -> oldest
    lo = reach_px - width_px
    band = np.clip(((dist - lo) / max(width_px, 1e-6) * RAMP_ROWS).astype(int), 0, RAMP_ROWS - 1)
    inside = (dist >= lo - 1) & (dist <= reach_px + 1)
    ramp_rgb = np.zeros((RAMP_ROWS, 3))
    cov = np.zeros(RAMP_ROWS)
    for k in range(RAMP_ROWS):
        m = inside & (band == k)
        cov[k] = m.sum()
        if m.any():
            ramp_rgb[k] = cols[m].mean(0)
    if not cov.any():
        raise ValueError(f"layer {ly['id']} clip {clip}: no effect pixels in the trail's radial band")
    alpha_row = cov / cov.max()
    ncol = hist * 4
    age = 1.0 - np.arange(ncol) / max(ncol - 1, 1)
    ramp = np.zeros((RAMP_ROWS, ncol, 4), np.uint8)
    ramp[..., :3] = (ramp_rgb[:, None, :] * 255 + 0.5).astype(np.uint8)
    ramp[..., 3] = (alpha_row[:, None] * age[None, :] * 255 + 0.5).astype(np.uint8)
    name = f"{ly['id']}__{clip}__trail.png"
    Image.fromarray(ramp).save(vdir / name)
    reach_u, width_u = reach_px / ppu, width_px / ppu
    bone, rails = _trail_points(ly, ctx, cells, reach_u, width_u)
    axes = unit_axes(ctx)
    listed = [k["cell"] >= 0 for k in ent["keys"]]
    ent["render"] = "trail"
    ent["billboard"] = "none"
    ent["sourceSheet"] = ent.pop("sheet")      # the DEF arc cells the ramp was coloured from; not drawn at runtime
    ent["trail"] = {
        "ramp": name, "space": "unit root, [front, left, up] components",
        "bone": bone, "point": "tail" if tr.get("boneTip") else "head", "reachUnits": round(reach_u, 5),
        "widthUnits": round(width_u, 5), "historyKeys": hist,
        "rail": "point + boneDir * r, r = reachUnits - widthUnits (inner) .. reachUnits (outer); bone rotation drives it",
        "ramp_layout": "rows inner->outer radial band (DEF arc colour + coverage), columns age newest->oldest (alpha fade)",
        "keys": [{"visible": vis, "inner": to_local(a, axes), "outer": to_local(b, axes)}
                 for vis, (a, b) in zip(listed, rails)],
        "reachSource": "auto: p90 of effect px distance from the anchor px" if tr.get("reach", "auto") == "auto" else "spec",
    }


# ----------------------------------------------------------------------------- CPU compositing (review + proof)
def _load(vdir, name, cache):
    if name not in cache:
        cache[name] = np.asarray(Image.open(vdir / name).convert("RGBA"), np.float32) / 255
    return cache[name]


def cell_of(fb, sheet_name, k, vdir, cache):
    s = _load(vdir, sheet_name, cache)
    sc = fb["texelsPerDefPx"]
    cw, ch = fb["cellPx"]
    r, c = divmod(k, fb["tilesX"])
    return s[r * ch * sc:(r + 1) * ch * sc:sc, c * cw * sc:(c + 1) * cw * sc:sc]


def over(dst_rgb, cov, src_rgba_full, weight=1.0):
    a = src_rgba_full[..., 3:4] * weight
    dst_rgb = dst_rgb * (1 - a) + src_rgba_full[..., :3] * a
    return dst_rgb, cov | (a[..., 0] > 0.5)


def warp_card(shape, cell, anchor_world, u_world, v_world, A, t):
    """Inverse-warp a cell (centre = anchor) drawn on a world-space card into an HxW view with px = A w + t."""
    H, W = shape
    ch, cw = cell.shape[:2]
    J = np.c_[A @ u_world, A @ v_world]            # d px / d cell px
    if abs(np.linalg.det(J)) < 1e-6:
        return np.zeros((H, W, 4), np.float32)
    c0 = A @ anchor_world + t
    corners = np.array([[x, y] for x in (-cw / 2, cw / 2) for y in (-ch / 2, ch / 2)])
    pc = c0 + corners @ J.T
    x0, y0 = np.floor(pc.min(0)).astype(int)
    x1, y1 = np.ceil(pc.max(0)).astype(int) + 1
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    out = np.zeros((H, W, 4), np.float32)
    if x1 <= x0 or y1 <= y0:
        return out
    yy, xx = np.mgrid[y0:y1, x0:x1]
    q = np.linalg.solve(J, np.vstack([xx.ravel() + 0.5 - c0[0], yy.ravel() + 0.5 - c0[1]]))
    cx = np.floor(q[0] + cw / 2).astype(int)
    cy = np.floor(q[1] + ch / 2).astype(int)
    ok = (cx >= 0) & (cx < cw) & (cy >= 0) & (cy < ch)
    vals = np.zeros((len(cx), 4), np.float32)
    vals[ok] = cell[cy[ok], cx[ok]]
    out[y0:y1, x0:x1] = vals.reshape(y1 - y0, x1 - x0, 4)
    return out


def paste_billboard(shape, cell, anchor_px, scale):
    """A view-facing cell centred at anchor_px, nearest-resized by ``scale`` (view px per cell px)."""
    H, W = shape
    ch, cw = cell.shape[:2]
    nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    im = np.asarray(Image.fromarray((cell * 255 + 0.5).astype(np.uint8)).resize((nw, nh), Image.NEAREST), np.float32) / 255
    out = np.zeros((H, W, 4), np.float32)
    x0, y0 = int(round(anchor_px[0])) - nw // 2, int(round(anchor_px[1])) - nh // 2
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + nw), min(H, y0 + nh)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0:sy1, sx0:sx1] = im[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
    return out


def draw_trail(shape, ent, ki, A, t, axes, vdir, cache):
    """Rasterise the ribbon of key ``ki`` (quad strip over the history) into an HxW RGBA layer."""
    H, W = shape
    out = np.zeros((H, W, 4), np.float32)
    tr = ent["trail"]
    keys = tr["keys"]
    if not keys[ki]["visible"]:
        return out
    ramp = _load(vdir, tr["ramp"], cache)
    R, C = ramp.shape[:2]
    hist = [j for j in range(ki, max(-1, ki - tr["historyKeys"] - 1), -1)]
    if len(hist) < 2:
        return out
    pts = [(A @ from_local(keys[j]["inner"], axes) + t, A @ from_local(keys[j]["outer"], axes) + t) for j in hist]
    yy, xx = np.mgrid[0:H, 0:W]
    P = np.stack([xx + 0.5, yy + 0.5], -1)
    n = len(pts) - 1
    for s in range(n):
        (i0, o0), (i1, o1) = pts[s], pts[s + 1]
        for tri, uv in (((i0, o0, o1), ((0, 0), (0, 1), (1, 1))), ((i0, o1, i1), ((0, 0), (1, 1), (1, 0)))):
            a, b, c = (np.asarray(p) for p in tri)
            M = np.c_[b - a, c - a]
            if abs(np.linalg.det(M)) < 1e-9:
                continue
            lo = np.floor(np.min([a, b, c], 0)).astype(int)
            hi = np.ceil(np.max([a, b, c], 0)).astype(int) + 1
            x0, y0 = max(0, lo[0]), max(0, lo[1])
            x1, y1 = min(W, hi[0]), min(H, hi[1])
            if x1 <= x0 or y1 <= y0:
                continue
            q = np.linalg.solve(M, (P[y0:y1, x0:x1].reshape(-1, 2) - a).T)
            l1, l2 = q
            ins = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
            (ua, va), (ub, vb), (uc, vc) = uv
            age = (s + ua + l1 * (ub - ua) + l2 * (uc - ua)) / n
            rad = va + l1 * (vb - va) + l2 * (vc - va)
            ci = np.clip((age * (C - 1)).round().astype(int), 0, C - 1)
            ri = np.clip((rad * (R - 1)).round().astype(int), 0, R - 1)
            vals = ramp[ri, ci]
            blk = out[y0:y1, x0:x1].reshape(-1, 4)
            blk[ins] = vals[ins]
            out[y0:y1, x0:x1] = blk.reshape(y1 - y0, x1 - x0, 4)
    return out


def review_parts(fb, ki, vm, shape, vdir, cache, ctx):
    """Extra RGBA layers a unitPlane / trail clip entry adds to a sprite-camera review key (the view-facing
    ``sheet`` is pasted by the caller as before). From the sprite camera the sagittal card is the DEF grid."""
    r = fb.get("render")
    k = fb["keys"][ki]["cell"]
    out = []
    if r == "unitPlane" and k >= 0:
        up = fb["unitPlane"]
        bone = vm["bones"][fb["anchorBone"]]
        anc = np.array(bone["tailPx"] if fb.get("anchorPoint") == "tail" else bone["headPx"], np.float64)
        if up.get("sheet"):
            out.append(paste_billboard(shape, cell_of(fb, up["sheet"], k, vdir, cache), anc, 1.0))
        dis = up.get("displaced")
        if dis and dis["keys"][ki]:
            out.append(paste_billboard(shape, cell_of({**fb, "cellPx": dis["cellPx"]}, dis["sheet"], k, vdir, cache),
                                       anc + np.array(dis["keys"][ki]["offsetPx"]), 1.0))
    elif r == "trail":
        A, t, _ = view_affine(vm)
        out.append(draw_trail(shape, fb, ki, A, t, unit_axes(ctx), vdir, cache))
    return out
