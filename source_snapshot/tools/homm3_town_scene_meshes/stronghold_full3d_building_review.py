#!/usr/bin/env python3
"""Per-building before/after review of the Stronghold full-3D buildings (offline moderngl, not Unity, not in-game).

    python tools/homm3_town_scene_meshes/stronghold_full3d_building_review.py \
        --before artifacts/homm3_stronghold_full3d/unity_project/Assets/Homm3TownScene3d/stronghold \
        --after  artifacts/homm3_stronghold_full3d/candidates/<name>/unity_project/Assets/Homm3TownScene3d/stronghold \
        --out    artifacts/homm3_stronghold_full3d/candidates/<name>/building_review [--only a,b]

Each building is drawn alone over the environment prefab (terrain, sky, periphery) from the vanilla rest pose, the
vanilla sweep poses (the camera's translating pan extremes; the cursor poses are pure rotations and reveal nothing)
and two +-18 deg review orbits (a stress test, not runtime poses). Per pose it measures, on the building's pixels:
  revealed   pixels whose surface point is hidden at the rest pose (the painting never saw it: sides, backs, the
             far side of a depth step) - reprojected into the rest camera against the rest depth buffer;
  streak     pixels whose texture footprint is elongated past STREAK_ANISO (one texel smeared across many pixels,
             the relief's side walls and rubber-sheet depth steps);
  restDiff   (rest pose only) mean |after - before| over the building's pixels (0 = unchanged registration).
Sheets: HoMM3 reference crop | before | after at the rest pose, then before | after per pose, same crop.
Proof tier: generated artifact (offline preview renders with the Hex/Lit diffuse model, not the Unity editor).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_preview as PV  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

W, H = SC.W, SC.H
STREAK_ANISO = 6.0
DARK_Q = 0.1          # revealedDark: revealed pixels darker than this quantile (a back pushed to mud by a luminance cap)
PALE_Q = 0.9          # revealedPale: revealed pixels brighter than this quantile of the building's rest-pose luminance
ORBITS = ((-18, 6), (18, 6))

META_FS = """
#version 330
uniform vec2 texSize; uniform float pid;
in vec2 v_uv; in vec3 v_p;
layout(location=0) out vec4 o0; layout(location=1) out vec4 o1;
void main(){
  vec2 dx = dFdx(v_uv) * texSize, dy = dFdy(v_uv) * texSize;
  float a = dot(dx, dx), b = dot(dx, dy), c = dot(dy, dy);
  float m = 0.5 * (a + c), q = sqrt(max(0.25 * (a - c) * (a - c) + b * b, 0.0));
  float s1 = sqrt(max(m + q, 0.0)), s2 = sqrt(max(m - q, 0.0));
  o0 = vec4(v_p, pid);
  o1 = vec4(s1 / max(s2, 1e-6), s1, s2, 1.0);
}
"""
META_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos; in vec2 in_uv;
out vec2 v_uv; out vec3 v_p;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); v_uv = in_uv; v_p = in_pos; }
"""


def load_prefab(sc, stage: Path, prefab: str, with_fx=False) -> list:
    out = []
    pdir = stage / prefab
    for mb in sorted(pdir.glob("*.bytes")):
        if mb.stem.endswith("_uv2") or (mb.stem.startswith("Fx_") and not with_fx):
            continue
        tex = mb.with_name(mb.stem + "_albedo.png")
        if not tex.is_file():
            continue
        v, n, uv, subs = S.read_bin(mb)
        P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
        nw = n.astype(np.float64) @ sc.C.T
        out.append((mb.stem, P.astype(np.float32), nw.astype(np.float32), uv, np.concatenate(subs),
                    np.asarray(Image.open(tex).convert("RGB")), mb.stem.startswith("Sky_")))
    return out


class Rig:
    def __init__(self, sc):
        import moderngl
        self.R = PV.Renderer(sc.rig, sc.sun, W, H)
        self.ctx = self.R.ctx
        self.meta = self.ctx.program(vertex_shader=META_VS, fragment_shader=META_FS)
        self.t0 = self.ctx.texture((W, H), 4, dtype="f4")
        self.t1 = self.ctx.texture((W, H), 4, dtype="f4")
        self.db = self.ctx.depth_renderbuffer((W, H))
        self.fbo = self.ctx.framebuffer(color_attachments=[self.t0, self.t1], depth_attachment=self.db)
        self.mg = moderngl

    def _add(self, items: list, pid: float) -> None:
        for name, P, n, uv, tris, img, unlit in items:
            self.R.add(name, P, n, uv, tris, img, unlit=unlit)
            vb = np.concatenate([P, uv.astype(np.float32)], 1).astype(np.float32)
            vbo = self.ctx.buffer(vb.tobytes())
            ibo = self.ctx.buffer(np.asarray(tris, np.int32).tobytes())
            vao = self.ctx.vertex_array(self.meta, [(vbo, "3f 2f", "in_pos", "in_uv")], ibo)
            self.metas.append((vao, (img.shape[1], img.shape[0]), pid, unlit, vbo, ibo))

    def set_env(self, env: list) -> None:
        self.metas = []
        self._add(env, 0.0)
        self.n_env = len(self.R.pieces)

    def set_building(self, bld: list) -> None:
        for pc in self.R.pieces[self.n_env:]:
            pc["vao"].release()
            pc["tex"].release()
        for m in self.metas[self.n_env:]:
            for o in (m[0], m[4], m[5]):
                o.release()
        del self.R.pieces[self.n_env:]
        del self.metas[self.n_env:]
        self._add(bld, 1.0)

    def render(self, cam: dict):
        lit = self.R.render(cam, near=2.0, far=T.DOME_R * 1.2)
        mvp = PV.perspective(cam["fov"], W / H, 2.0, T.DOME_R * 1.2) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                                cam["right"])
        self.fbo.use()
        self.fbo.clear(0, 0, 0, -1, depth=1.0)
        self.ctx.enable(self.mg.DEPTH_TEST)
        self.ctx.disable(self.mg.CULL_FACE)
        self.meta["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for vao, ts, pid, unlit, _, _ in self.metas:
            if unlit:
                continue
            self.meta["texSize"].value = ts
            self.meta["pid"].value = pid
            vao.render()
        a0 = np.frombuffer(self.t0.read(), np.float32).reshape(H, W, 4)[::-1]
        a1 = np.frombuffer(self.t1.read(), np.float32).reshape(H, W, 4)[::-1]
        return lit, a0, a1


def measure(cam, rest_cam, rest_a0, a0, a1) -> dict:
    bld = a0[..., 3] > 0.5
    Pw = a0[..., :3][bld].astype(np.float64)
    px, py, zc = T.project(rest_cam, Pw)
    inside = (px >= 0) & (px < W) & (py >= 0) & (py < H) & (zc > 0)
    rz = np.full(len(Pw), np.inf)
    xi = np.clip(px[inside].astype(int), 0, W - 1)
    yi = np.clip(py[inside].astype(int), 0, H - 1)
    rp = rest_a0[yi, xi]
    rest_z = np.where(rp[:, 3] >= 0, (rp[:, :3].astype(np.float64) - rest_cam["pos"]) @ rest_cam["fwd"], np.inf)
    rz[inside] = rest_z
    revealed = inside & (zc > rz * 1.004 + 0.1)
    streak = a1[..., 0][bld] > STREAK_ANISO
    n = int(bld.sum())
    rev_img = np.zeros(bld.shape, bool)
    rev_img[bld] = revealed
    return {"px": n, "revealed": int(revealed.sum()), "streak": int(streak.sum()),
            "revealedStreak": int((revealed & streak).sum()), "_mask": bld, "_revealed": rev_img}


def pale_count(lit: np.ndarray, rev: np.ndarray, lum_ref: float, lum_lo: float = -1.0) -> tuple[int, int]:
    """revealed pixels brighter than the building's own rest-pose PALE_Q luminance (a pale patch on a side / back) and
    darker than its DARK_Q luminance (a side pushed to mud)."""
    lum = lit.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return int((rev & (lum > lum_ref)).sum()), int((rev & (lum < lum_lo)).sum())


def bbox(mask: np.ndarray, pad=0.15):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return (0, 0, W, H)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    px_, py_ = int((x1 - x0) * pad) + 8, int((y1 - y0) * pad) + 8
    return (max(0, x0 - px_), max(0, y0 - py_), min(W, x1 + px_), min(H, y1 + py_))


def label(img: Image.Image, text: str) -> Image.Image:
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, min(img.width, 10 + 6 * len(text)), 14), fill=(0, 0, 0))
    d.text((3, 2), text, fill=(255, 255, 255))
    return img


def fit_h(img: Image.Image, h: int) -> Image.Image:
    return img.resize((max(1, round(img.width * h / img.height)), h), Image.LANCZOS)


def hstack(imgs, gap=6, bg=(40, 40, 40)):
    out = Image.new("RGB", (sum(i.width for i in imgs) + gap * (len(imgs) - 1), max(i.height for i in imgs)), bg)
    x = 0
    for i in imgs:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def vstack(imgs, gap=6, bg=(40, 40, 40)):
    out = Image.new("RGB", (max(i.width for i in imgs), sum(i.height for i in imgs) + gap * (len(imgs) - 1)), bg)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=SC.FACTION, help="town_full3d_factions/<key>.py (default stronghold)")
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--row-h", type=int, default=300)
    ap.add_argument("--labels", default="relief,solid", help="names of the before / after closures on the sheets")
    ap.add_argument("--rest-diff", action="store_true", help="also write <layer>_restdiff.png (|after - before| x4)")
    args = ap.parse_args()
    lab_b, lab_a = args.labels.split(",")
    before, after, out = Path(args.before), Path(args.after), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    env = load_prefab(sc, before, S.ENV_KEY)
    cams = {"rest": sc.cam}
    pans = S.pan_cams(sc)
    for k in ("sweep_left", "sweep_right", "sweep_high"):
        cams[k] = pans[k]
    for y, p in ORBITS:
        cams[f"orbit{y:+d}"] = S.orbit_cam(sc, y, p)
    rig = Rig(sc)
    rig.set_env(env)
    only = [x for x in args.only.split(",") if x]
    layers = [l for l in SC.reachable_layers() if not only or l in only]
    report = {}
    for lid in layers:
        prefab = S.PREFIX + lid
        shots = {}
        for tag, stage in (("before", before), ("after", after)):
            bld = load_prefab(sc, stage, prefab)
            if not bld:
                raise SystemExit(f"review: {prefab} has no staged mesh in {stage}")
            rig.set_building(bld)
            res = {}
            rest_lit, rest_a0, rest_a1 = rig.render(sc.cam)
            rl = rest_lit.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
            rmask = rest_a0[..., 3] > 0.5
            lum_ref = float(np.quantile(rl[rmask], PALE_Q)) if rmask.any() else 255.0
            lum_lo = float(np.quantile(rl[rmask], DARK_Q)) if rmask.any() else -1.0
            for cname, cam in cams.items():
                lit, a0, a1 = (rest_lit, rest_a0, rest_a1) if cname == "rest" else rig.render(cam)
                m = measure(cam, sc.cam, rest_a0, a0, a1)
                m["revealedPale"], m["revealedDark"] = pale_count(lit, m["_revealed"], lum_ref, lum_lo)
                res[cname] = (lit, m)
            shots[tag] = res
        rb, ra = shots["before"]["rest"], shots["after"]["rest"]
        mk = rb[1]["_mask"] | ra[1]["_mask"]
        rest_diff = float(np.abs(rb[0].astype(np.float32) - ra[0].astype(np.float32)).mean(-1)[mk].mean())
        ref = np.asarray(S.homm3_reference([lid]))
        inrect = np.zeros_like(mk)
        inrect[:SC.TH, :SC.TW] = True
        err = {t: round(float(np.abs(r[0].astype(np.float32) - ref.astype(np.float32)).mean(-1)[mk & inrect].mean()), 2)
               for t, r in (("before", rb), ("after", ra))}
        # error summed over the union mask as well (px x mean abs): the mean alone moves when the mask changes
        errsum = {t: int(np.abs(r[0].astype(np.float32) - ref.astype(np.float32)).mean(-1)[mk & inrect].sum())
                  for t, r in (("before", rb), ("after", ra))}
        row = {"restDiff": round(rest_diff, 2), "restErrVsHomm3": err, "restErrSumVsHomm3": errsum}
        if args.rest_diff:
            dimg = np.clip(np.abs(rb[0].astype(np.float32) - ra[0].astype(np.float32)).mean(-1) * 4, 0, 255)
            Image.fromarray(dimg.astype(np.uint8)).crop(bbox(mk)).save(out / f"{lid}_restdiff.png")
            dm = dimg > 40
            if dm.any():
                db = bbox(dm, 0.05)
                hstack([Image.fromarray(x).crop(db) for x in (ref, rb[0], ra[0])]).save(out / f"{lid}_restzoom.png")
        for tag in ("before", "after"):
            row[tag] = {c: {k: v for k, v in m.items() if not k.startswith("_")} for c, (_, m) in shots[tag].items()}
        report[lid] = row
        # sheet
        rows = []
        box = bbox(mk)
        crop = lambda a, b: Image.fromarray(a).crop(b)  # noqa: E731
        rows.append(hstack([label(fit_h(crop(ref, box), args.row_h), "HoMM3 painting+sprite (reference)"),
                            label(fit_h(crop(rb[0], box), args.row_h), f"before ({lab_b}) rest pose"),
                            label(fit_h(crop(ra[0], box), args.row_h), f"after ({lab_a}) rest pose")]))
        for cname in cams:
            if cname == "rest":
                continue
            lb, mb_ = shots["before"][cname]
            la, ma_ = shots["after"][cname]
            box = bbox(mb_["_mask"] | ma_["_mask"])
            tb = f"before {cname}: revealed {mb_['revealed']} streak {mb_['streak']} pale {mb_['revealedPale']} dark {mb_['revealedDark']}"
            ta = f"after {cname}: revealed {ma_['revealed']} streak {ma_['streak']} pale {ma_['revealedPale']} dark {ma_['revealedDark']}"
            rows.append(hstack([label(fit_h(crop(lb, box), args.row_h), tb),
                                label(fit_h(crop(la, box), args.row_h), ta)]))
        vstack(rows).save(out / f"{lid}.png")
        print(lid, json.dumps({k: (v if k.startswith("rest") else {c: [v[c]["revealed"], v[c]["streak"]]
                                                               for c in ("sweep_left", "sweep_right", "orbit-18")})
                               for k, v in row.items()}), flush=True)
    (out / "metrics.json").write_text(json.dumps({"proofTier": "generated artifact (offline moderngl preview)",
                                                 "streakAniso": STREAK_ANISO, "paleQ": PALE_Q, "darkQ": DARK_Q, "before": str(before),
                                                 "after": str(after), "layers": report}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
