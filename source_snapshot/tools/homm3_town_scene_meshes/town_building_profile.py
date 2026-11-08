"""Per-building 90-degree profiles of a staged town candidate: every Mesh_Body_ bin drawn front-on, from the side and
from above, at one metric scale, so malformed relief (rims dragged back along the view ray, fins, spikes) is plain to see
and the point where it should be cut off can be read straight off the side view.

The bins are in the prefab frame (x right, y up, z = forward depth from the camera), so the side view is the
orthographic (z, y) plane seen from the camera's right and the top view the (x, z) plane seen from above. Triangles
are drawn back to front with their texture colour (alpha < 0.5 dropped, as the shader cuts them). A second side panel
tints each triangle by how far it sits behind (red) or in front of (blue) the building's core depth: the median depth
of the texels at least `--core` px inside the sprite's alpha outline, so a rim tail shows as a red fringe hanging off
the body. A fifth panel shows texture streaking: per triangle, the largest stretch of the texel -> side-view map (in
texels per texel of the front view's scale), so a surface the view slides along -- where the painted texture smears
into streaks at sweeps -- glows yellow; it marks where a rim stops being painted surface.

  TOWN_FULL3D_FACTION=<f> TOWN_FULL3D_CANDIDATE=<cand> python town_building_profile.py [--only lid,...] [--core 6]
    -> artifacts/homm3_<f>_full3d/candidates/<cand>/profiles/<lid>.png + profiles/sheet.jpg
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import stronghold_full3d_scene as S

Image.MAX_IMAGE_PIXELS = None
PANEL = 520          # px of the longest side of a panel
BG = (24, 26, 30)


def core_depth(v, uv, tris, alpha, core_px):
    """Median z of the vertices whose texel lies at least core_px inside the alpha outline (falls back to all)."""
    from scipy.ndimage import distance_transform_edt
    inside = alpha >= 128
    dist = distance_transform_edt(inside)
    h, w = alpha.shape
    tx = np.clip((uv[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
    ty = np.clip(((1 - uv[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
    d = dist[ty, tx]
    sel = d >= core_px
    z = v[:, 2]
    return float(np.median(z[sel] if sel.sum() > 20 else z)), d


def render(v, tris, tcol, axes, flip_order, size, lo, span):
    """Paint triangles (tcol per triangle) on the plane of `axes`, farthest first along the remaining axis."""
    a, b = axes
    other = 3 - a - b
    w, h = size
    im = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(im)
    s = (min(w, h) - 20) / span
    p = np.stack([(v[:, a] - lo[0]) * s + 10, h - ((v[:, b] - lo[1]) * s + 10)], 1)
    key = v[tris, other].mean(1) * (-1 if flip_order else 1)
    for k in np.argsort(-key):
        t = tris[k]
        dr.polygon([tuple(p[i]) for i in t], fill=tuple(int(c) for c in tcol[k]))
    return im


def profile(lid, binp, texp, core_px):
    v, _n, uv, subs = S.read_bin(binp)
    v = np.asarray(v, np.float64)
    tris = np.vstack(subs).astype(np.int64)
    rgba = np.asarray(Image.open(texp).convert("RGBA"))
    h, w = rgba.shape[:2]
    cuv = uv[tris].mean(1)
    tx = np.clip((cuv[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
    ty = np.clip(((1 - cuv[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
    tc = rgba[ty, tx]
    keep = tc[:, 3] >= 128
    tris, tc = tris[keep], tc[keep, :3].astype(np.float64)
    if not len(tris):
        return None, {}
    zc, dpx = core_depth(v, uv, tris, rgba[:, :, 3], core_px)
    used = np.unique(tris)
    vu = v[used]
    lo3, hi3 = vu.min(0), vu.max(0)
    ext = hi3 - lo3
    # depth offset of each triangle from the core, in units of the building's height (scale-free)
    dz = (v[tris, 2].mean(1) - zc) / max(ext[1], 1e-6)
    heat = np.zeros_like(tc)
    r = np.clip(dz / 0.25, 0, 1)
    bl = np.clip(-dz / 0.25, 0, 1)
    grey = tc.mean(1, keepdims=True) * 0.35
    heat[:] = grey
    heat[:, 0] += r * 230
    heat[:, 2] += bl * 230
    heat[:, 1] += (1 - r - bl).clip(0, 1) * 0
    heat = heat.clip(0, 255)
    # texture streaking in the side view: largest singular value of d(side z,y)/d(texel), normalised by the median
    # front-view value (so 1 = as sharp as the painting; 4 = each texel smeared over 4 texels' worth of side view)
    def stretch(ax):
        P = v[tris][:, :, ax]                                        # (k,3,2) metres
        T = uv[tris] * np.array([w, h])                              # (k,3,2) texels
        dP = np.stack([P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]], 2)     # (k,2,2) columns = edges
        dT = np.stack([T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]], 2)
        det = np.linalg.det(dT)
        ok = np.abs(det) > 1e-9
        J = np.zeros_like(dP)
        J[ok] = dP[ok] @ np.linalg.inv(dT[ok])
        return np.where(ok, np.linalg.svd(J, compute_uv=False)[:, 0], 0.0)
    sf = stretch([0, 1])
    ss = stretch([2, 1])
    ref = float(np.median(sf[sf > 0])) if (sf > 0).any() else 1.0
    st = ss / max(ref, 1e-12)
    q = np.clip((st - 1.5) / 4.5, 0, 1)[:, None]
    streak = tc * 0.3 * (1 - q) + q * np.array([255, 220, 40])
    span = float(max(ext)) * 1.05
    sz = (PANEL, PANEL)
    front = render(v, tris, tc, (0, 1), False, sz, (lo3[0], lo3[1]), span)       # camera view (farther drawn first)
    side = render(v, tris, tc, (2, 1), False, sz, (lo3[2], lo3[1]), span)        # seen from the right: z right, y up
    side_h = render(v, tris, heat, (2, 1), False, sz, (lo3[2], lo3[1]), span)
    side_s = render(v, tris, streak, (2, 1), False, sz, (lo3[2], lo3[1]), span)
    top = render(v, tris, tc, (0, 2), True, sz, (lo3[0], lo3[2]), span)          # seen from above: x right, z up (far)
    # core depth marker on the side panels
    s = (PANEL - 20) / span
    xz = (zc - lo3[2]) * s + 10
    for im in (side, side_h, side_s):
        ImageDraw.Draw(im).line([(xz, 0), (xz, PANEL)], fill=(90, 220, 90), width=1)
    sheet = Image.new("RGB", (PANEL * 5 + 40, PANEL + 34), BG)
    for i, (im, name) in enumerate([(front, "front (camera)"), (side, "side 90 (z ->)"),
                                     (side_h, "side: behind core = red, in front = blue"),
                                     (side_s, "side: texture streak (yellow = >2x smeared)"), (top, "top (z up = far)")]):
        sheet.paste(im, (i * (PANEL + 10), 34))
        ImageDraw.Draw(sheet).text((i * (PANEL + 10) + 6, 8), name, fill=(220, 220, 220))
    ImageDraw.Draw(sheet).text((PANEL * 5 - 260, 8), f"{lid}  h {ext[1]:.2f}  depth {ext[2]:.2f}", fill=(255, 210, 120))
    beh = float((dz > 0.08).mean())
    p95 = float(np.percentile(dz, 95))
    return sheet, {"height": float(ext[1]), "depthSpan": float(ext[2]), "behind8pct": round(beh, 4), "dzP95": round(p95, 4),
                   "streak3x": round(float((st > 3).mean()), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--core", type=float, default=6.0, help="px inside the alpha outline that count as the body core")
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x}
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    root = S.STAGE.parent.parent.parent              # unity_project
    out = root.parent / "profiles"
    out.mkdir(exist_ok=True)
    stats, thumbs = {}, []
    for key, row in sorted(rows.items()):
        if key == S.ENV_KEY:
            continue
        for b in row.get("bins") or []:
            if not b["name"].startswith("Mesh_Body_"):
                continue
            lid = b["name"][len("Mesh_Body_"):]
            if only and lid not in only:
                continue
            sheet, st = profile(lid, root / b["mesh"], root / b["texture"], a.core)
            if sheet is None:
                continue
            p = out / f"{lid}.png"
            p.unlink(missing_ok=True)
            sheet.save(p)
            stats[lid] = st
            thumbs.append(sheet.resize((sheet.width // 3, sheet.height // 3), Image.LANCZOS))
            print(lid, st, flush=True)
    if thumbs:
        tw, th = thumbs[0].size
        sh = Image.new("RGB", (tw * 2, th * ((len(thumbs) + 1) // 2)), BG)
        for i, t in enumerate(thumbs):
            sh.paste(t, ((i % 2) * tw, (i // 2) * th))
        (out / "sheet.jpg").unlink(missing_ok=True)
        sh.save(out / "sheet.jpg", quality=88)
    (out / "stats.json").unlink(missing_ok=True)
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"profiles: {len(stats)} buildings -> {out}")


if __name__ == "__main__":
    main()
