"""Town full-3D: texture-stretch audit of a staged candidate at the wide / extreme camera poses.

Any faction and any candidate: it reads the staged bins and textures (TOWN_FULL3D_CANDIDATE, --faction) exactly as the
offline preview does, and the vanilla camera's proof poses (default + cursor / sweep extremes; optionally the review
orbit). It is read-only: nothing is staged, bundled or installed.

Metric, per triangle and camera. J is the 2x2 Jacobian from the triangle's texel space (uv * texture size) to the
camera's screen pixels. Its singular values s1 >= s2 are the screen px one texel covers along its worst and best axis.
  stretch = s1 / base     base = the region's own screen-area-weighted median sqrt(s1 * s2) in the same camera,
                          so a region that is merely closer or further (zoom) scores 1
  aniso   = s1 / s2       a smear, not a zoom
A pixel is *stretched* when stretch >= STRETCH_T and aniso >= ANISO_T. Projection-textured relief (the painting
pushed onto a depth mesh) shows exactly this at wide angles: faces edge-on to the rest ray hold a few texels, and
turning the camera spreads them over many pixels in one direction. Visibility is a GPU depth pass over every staged
piece except the sky and the Fx_ particles, at the preview resolution, with no MSAA.
Regions: each staged mesh is one region. With --labels <npy> (int32 H x W in rest-frame pixels, 0 = none), a
triangle whose centroid projects into a labelled pixel at the rest pose becomes region "<piece>#<label>". That is how
instances inside the terrain's painted relief (e.g. background houses) get scored one by one; --label-pieces
limits that to the named meshes (e.g. Mesh_Terrain), so a building layer in front of a house keeps its own region.
Outputs (--out): stretch.json (per region and camera: visible px, stretched px and share, p95 stretch; ranked by the
worst camera's stretched px) and, with --sheet N, sheet.png: the N worst regions cropped from the candidate's own pan
previews (work/preview/<cam>.png, same poses) with the stretched pixels outlined in red.
    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_stretch.py --faction stronghold --out <dir> [--labels x.npy]
        [--sheet 12] [--cams cursor_left,cursor_right,sweep_left,sweep_right,sweep_high] [--orbit 35]
Proof tier: generated-artifact measurement (offline preview geometry, not the Unity renderer).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

STRETCH_T, ANISO_T = 3.0, 2.0
CAMS_DEFAULT = "cursor_left,cursor_right,sweep_left,sweep_right,sweep_high"

VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos; in vec3 in_att;
flat out vec3 v_att;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); v_att = in_att; }
"""
FS = """
#version 330
flat in vec3 v_att; out vec4 o;
void main(){ o = vec4(v_att, 1.0); }
"""


def tri_jacobian_sv(S2, T2):
    """singular values (s1 >= s2) of J = dS dT^-1 per triangle; S2, T2: (m, 3, 2)."""
    dS = np.stack([S2[:, 1] - S2[:, 0], S2[:, 2] - S2[:, 0]], -1)          # (m, 2, 2) columns = edges
    dT = np.stack([T2[:, 1] - T2[:, 0], T2[:, 2] - T2[:, 0]], -1)
    det = dT[:, 0, 0] * dT[:, 1, 1] - dT[:, 0, 1] * dT[:, 1, 0]
    bad = np.abs(det) < 1e-9
    inv = np.empty_like(dT)
    inv[:, 0, 0], inv[:, 1, 1] = dT[:, 1, 1], dT[:, 0, 0]
    inv[:, 0, 1], inv[:, 1, 0] = -dT[:, 0, 1], -dT[:, 1, 0]
    inv /= np.where(bad, 1.0, det)[:, None, None]
    J = dS @ inv
    a, b, c, d = J[:, 0, 0], J[:, 0, 1], J[:, 1, 0], J[:, 1, 1]
    e, f = (a + d) / 2, (a - d) / 2
    g, h = (c + b) / 2, (c - b) / 2
    q, r = np.hypot(e, h), np.hypot(f, g)
    s1, s2 = q + r, np.abs(q - r)
    s1[bad], s2[bad] = 1e3, 1e-3                                           # a degenerate texel map: a pure smear
    return s1, np.maximum(s2, 1e-6)


def project(PV, cam, P, w, h, near, far):
    mvp = PV.perspective(cam["fov"], w / h, near, far) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
    c = np.c_[P, np.ones(len(P))] @ mvp.T
    wc = c[:, 3]
    ok = wc > near
    x = (c[:, 0] / np.where(ok, wc, 1) * 0.5 + 0.5) * w
    y = (1 - (c[:, 1] / np.where(ok, wc, 1) * 0.5 + 0.5)) * h
    return np.c_[x, y], ok, mvp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default="stronghold")
    ap.add_argument("--out", required=True)
    ap.add_argument("--labels", default="")
    ap.add_argument("--label-pieces", default="", help="comma list of mesh-name substrings the labels apply to "
                    "(default: every piece)")
    ap.add_argument("--cams", default=CAMS_DEFAULT)
    ap.add_argument("--orbit", type=float, default=0.0, help="also score the review orbit at +/- this yaw (deg)")
    ap.add_argument("--sheet", type=int, default=0)
    ap.add_argument("--width", type=int, default=1920)
    a = ap.parse_args()
    sys.argv[1:] = ["--faction", a.faction]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import moderngl
    import stronghold_full3d_scene as S
    import stronghold_full3d_preview as PV
    import stronghold_full3d_terrain as T
    from PIL import Image, ImageDraw
    import cv2

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    S.load_staged_preview(sc)
    pans = S.pan_cams(sc)
    cams = {k: pans[k] for k in a.cams.split(",") if k}
    if a.orbit:
        cams[f"orbit_m{a.orbit:g}"] = S.orbit_cam(sc, -a.orbit)
        cams[f"orbit_p{a.orbit:g}"] = S.orbit_cam(sc, a.orbit)
    w = a.width
    h = round(w * 9 / 16)
    near, far = 2.0, T.DOME_R * 1.2
    labels = np.load(a.labels) if a.labels else None

    # pieces and their triangle regions
    pieces = []
    names = []                                           # region id -> name (id 0 = nothing)
    rid_of = {}
    for name, P, n, uv, tris, img, unlit in sc.preview:
        stem = name.split("/")[-1]
        if unlit or stem.startswith("Fx_"):
            continue
        th, tw = img.shape[:2]
        tris = np.asarray(tris, np.int64)
        reg = np.full(len(tris), -1, np.int64)
        if labels is not None and (not a.label_pieces or any(k in stem for k in a.label_pieces.split(","))):
            cen = P[tris].mean(1).astype(np.float64)
            s, ok, _ = project(PV, sc.cam, cen, labels.shape[1], labels.shape[0], near, far)
            xi, yi = np.round(s[:, 0]).astype(int), np.round(s[:, 1]).astype(int)
            inside = ok & (xi >= 0) & (yi >= 0) & (xi < labels.shape[1]) & (yi < labels.shape[0])
            lab = np.zeros(len(tris), np.int64)
            lab[inside] = labels[yi[inside], xi[inside]]
            for l in np.unique(lab[lab > 0]):
                key = f"{name}#{int(l)}"
                rid_of[key] = len(names) + 1
                names.append(key)
                reg[lab == l] = rid_of[key]
        rid_of[name] = len(names) + 1
        names.append(name)
        reg[reg < 0] = rid_of[name]
        pieces.append({"name": name, "P": np.asarray(P, np.float64), "T": np.asarray(uv, np.float64) * [tw, th],
                       "tris": tris, "reg": reg})

    ctx = moderngl.create_standalone_context()
    prog = ctx.program(vertex_shader=VS, fragment_shader=FS)
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((w, h), 4, dtype="f4")],
                          depth_attachment=ctx.depth_texture((w, h)))
    res = {n: {} for n in names}
    masks = {}
    for ck, cam in cams.items():
        fbo.use()
        ctx.clear(0.0, 0.0, 0.0, 0.0)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        mvp = None
        for pc in pieces:
            S2, ok, mvp = project(PV, cam, pc["P"], w, h, near, far)
            t = pc["tris"]
            s1, s2 = tri_jacobian_sv(S2[t], pc["T"][t])
            vis = ok[t].all(1)
            e1, e2 = S2[t][:, 1] - S2[t][:, 0], S2[t][:, 2] - S2[t][:, 0]
            area = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
            geo = np.sqrt(s1 * s2)
            stretch = np.zeros(len(t))
            for r in np.unique(pc["reg"]):
                m = (pc["reg"] == r) & vis & (area > 0.05) & (s1 < 1e3)
                if m.sum() < 3:
                    base = np.median(geo[pc["reg"] == r]) if (pc["reg"] == r).any() else 1.0
                else:
                    o = np.argsort(geo[m])
                    cw = np.cumsum(area[m][o])
                    base = geo[m][o][np.searchsorted(cw, cw[-1] / 2)]
                sel = pc["reg"] == r
                stretch[sel] = s1[sel] / max(base, 1e-6)
            aniso = s1 / s2
            vb = np.concatenate([pc["P"][t].reshape(-1, 3),
                                 np.repeat(np.c_[pc["reg"], np.minimum(stretch, 1e4), np.minimum(aniso, 1e4)], 3, 0)],
                                1).astype(np.float32)
            vbo = ctx.buffer(vb.tobytes())
            vao = ctx.vertex_array(prog, [(vbo, "3f 3f", "in_pos", "in_att")])
            prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
            vao.render()
            vao.release()
            vbo.release()
        buf = np.frombuffer(fbo.color_attachments[0].read(), np.float32).reshape(h, w, 4)[::-1]
        rid = np.round(buf[..., 0]).astype(np.int64)
        st, an = buf[..., 1], buf[..., 2]
        bad = (st >= STRETCH_T) & (an >= ANISO_T)
        masks[ck] = (rid, bad)
        vis_n = np.bincount(rid.ravel(), minlength=len(names) + 1)
        bad_n = np.bincount(rid[bad].ravel(), minlength=len(names) + 1)
        for i, nm in enumerate(names, 1):
            if vis_n[i] == 0:
                continue
            sv = st[rid == i]
            res[nm][ck] = {"visiblePx": int(vis_n[i]), "stretchedPx": int(bad_n[i]),
                           "stretchedShare": round(float(bad_n[i] / vis_n[i]), 4),
                           "p95Stretch": round(float(np.percentile(sv, 95)), 2)}
        print(ck, "visible px", int((rid > 0).sum()), "stretched px", int(bad.sum()), flush=True)

    rank = []
    for nm, per in res.items():
        if not per:
            continue
        worst = max(per, key=lambda c: per[c]["stretchedPx"])
        rank.append({"region": nm, "worstCam": worst, **per[worst],
                     "sumStretchedPx": int(sum(v["stretchedPx"] for v in per.values()))})
    rank.sort(key=lambda r: -r["stretchedPx"])
    doc = {"schema": "town_full3d_stretch.v1", "faction": a.faction, "candidate": S.CANDIDATE or "(base)",
           "thresholds": {"stretch": STRETCH_T, "aniso": ANISO_T}, "size": [w, h], "cams": list(cams),
           "labels": a.labels or None, "ranked": rank, "perRegion": res,
           "proofTier": "generated-artifact measurement (offline preview geometry)"}
    (out / "stretch.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")

    if a.sheet:
        cells = []
        for r in rank[:a.sheet]:
            ck = r["worstCam"]
            prev = S.WORK / "preview" / f"{ck}.png"
            img = np.asarray(Image.open(prev).convert("RGB").resize((w, h))) if prev.is_file() else \
                np.zeros((h, w, 3), np.uint8)
            rid, bad = masks[ck]
            i = rid_of[r["region"]]
            reg = rid == i
            ys, xs = np.nonzero(reg)
            x0, x1 = max(xs.min() - 20, 0), min(xs.max() + 20, w)
            y0, y1 = max(ys.min() - 20, 0), min(ys.max() + 20, h)
            ov = img.copy()
            edge = cv2.morphologyEx((bad & reg).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
            ov[edge] = (255, 0, 0)
            redge = cv2.morphologyEx(reg.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
            ov[redge] = (255, 255, 0)
            pair = np.concatenate([img[y0:y1, x0:x1], ov[y0:y1, x0:x1]], 1)
            im = Image.fromarray(pair)
            im.thumbnail((1000, 420))
            c = Image.new("RGB", (1000, im.height + 18), (20, 20, 20))
            c.paste(im, (0, 18))
            ImageDraw.Draw(c).text((4, 3), f"{r['region']} | {ck} | stretched {r['stretchedPx']} px "
                                   f"({r['stretchedShare']:.0%}), p95 {r['p95Stretch']}  [yellow region, red stretched]",
                                   fill=(255, 255, 255))
            cells.append(c)
        if cells:
            sh = Image.new("RGB", (1000, sum(c.height + 4 for c in cells)), (60, 60, 60))
            y = 0
            for c in cells:
                sh.paste(c, (0, y))
                y += c.height + 4
            sh.save(out / "sheet.png")
    print(json.dumps(rank[:15], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
