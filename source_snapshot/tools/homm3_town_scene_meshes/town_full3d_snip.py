#!/usr/bin/env python3
"""Town full-3D: reviewed stretch snip (docs/homm3_town_stretch_snip.md).

A cheap alternative to generative / layered-depth back-fill for the rubber-sheet stretching of a full-3D town at the
camera's reachable extremes (the vanilla sweep_left / sweep_right / sweep_high poses). A reviewer (an LLM that looks at
the renders, or a person) marks the regions that read badly at a pose; the pass maps each region back to the
triangles responsible through a per-pixel (piece, triangle) id render, filtered by a rule, and removes / shortens /
fades those triangles. The triangles it touches are depth-step bridges that lie along the rest camera's rays, so the
rest frame is (nearly) unchanged; nothing is recoloured in any piece's own texture.

    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_snip.py --faction <key> render --round N [--pose sweep_left,...]
    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_snip.py --faction <key> select --selection <json>
    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_snip.py --faction <key> apply  --selection <json>

render   writes, per pose, the lit preview (<pose>.png), a gridded copy with 100 px coordinates (<pose>_grid.png) and a
         streak overlay (<pose>_streak.png: texel footprint anisotropy >= STREAK_ANISO in red) into
         <candidate>/work/snip/round_<N>/ - the images the reviewer looks at.
select   resolves the selection file's rules in order (rounds in order; each round is id-rendered on the state left by
         the rounds before it) into triangle ids of the seed's original bins, and writes them into the file's
         "resolved" section. A rule: {"round", "pose", "region": [x0, y0, x1, y1] in pose px (1920x1080) or "all",
         "groups": ["terrain" | "env" | "buildings"], "minAniso", "minRestRatio", "action": "remove" | "clamp" |
         "fade", "note"}. A triangle is taken when it is the visible surface of some pixel in the region at the pose,
         its texel footprint there is elongated at least minAniso (s1/s2 of the screen -> texel map) and its rest
         forward-depth ratio (max / min over its vertices) is at least minRestRatio (a depth step: flat ground and
         front-facing paint are never taken), its face is within maxRestCos of edge-on at rest (|cos| of normal vs
         rest ray; default 1 = any) and it owns at most maxRestPx pixels of the rest frame (default MAX_REST_PX).
apply    rewrites the touched bins from the originals kept in <candidate>/work/snip/orig/ (made on first apply; the
         pass never compounds): remove drops the triangles; clamp keeps them on duplicated vertices moved along their
         own rest rays to at most CLAMP_RATIO x the triangle group's nearest depth (a shorter curtain, same rest
         silhouette); fade moves them into a new piece <piece>_SnipFade whose texture is the piece's albedo
         blurred by FADE_SIGMA texels (the streak's high frequencies gone, its colour kept).
Proof tier: generated artifact / offline render (moderngl Hex/Lit preview; not Unity, not in-game).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REACHABLE = ("sweep_left", "sweep_right", "sweep_high")
CLAMP_RATIO = 1.05
MAX_REST_PX = 2            # a triangle that owns more than this many pixels at rest is never taken (rest identity)
FADE_SIGMA = 12.0
GROUPS = ("terrain", "env", "buildings")

ID_VS = """
#version 330
uniform mat4 mvp; in vec3 in_pos;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); }
"""
ID_FS = """
#version 330
uniform int item; out ivec4 o;
void main(){ o = ivec4(item, gl_PrimitiveID, 0, 1); }
"""


def _mods():
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import stronghold_full3d_building_review as BR
    import stronghold_full3d_preview as PV
    import stronghold_full3d_terrain as T
    return SC, S, BR, PV, T


def cams_of(sc, S) -> dict:
    pans = S.pan_cams(sc)
    return {"rest": sc.cam, **{k: pans[k] for k in ("cursor_left", "cursor_right") + REACHABLE}}


def load_items(sc, S, BR, stage: Path) -> list[dict]:
    """Every staged bin the review draws (environment + the full build state), world space, with its group."""
    rows = json.loads((stage / "rows.json").read_text(encoding="utf-8"))
    full = [S.PREFIX + l for l in S.STATES["full"]]
    out = []
    for prefab in [S.ENV_KEY] + full:
        named = {b["name"] for b in rows.get(prefab, {}).get("bins", [])}
        for name, P, n, uv, tris, img, unlit in BR.load_prefab(sc, stage, prefab):
            if name not in named:
                continue
            g = "buildings" if prefab != S.ENV_KEY else \
                "terrain" if name.startswith(("Mesh_Terrain", "Mesh_Back_")) else "env"
            out.append({"key": f"{prefab}/{name}", "prefab": prefab, "name": name, "P": P, "n": n, "uv": uv,
                        "tris": np.asarray(tris, np.int64), "img": img, "unlit": unlit, "group": g})
    return out


def rest_cos(sc, P, tris) -> np.ndarray:
    """|cos| between each face's normal and the rest camera's ray to its centroid (0 = edge-on at rest)."""
    P = P.astype(np.float64)
    nrm = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    d = P[tris].mean(1) - sc.cam["pos"]
    return np.abs((nrm * d).sum(1)) / np.maximum(np.linalg.norm(nrm, axis=1) * np.linalg.norm(d, axis=1), 1e-12)


def rest_ratio(sc, P, tris) -> np.ndarray:
    z = (P.astype(np.float64) - sc.cam["pos"]) @ sc.cam["fwd"]
    zt = z[tris]
    return zt.max(1) / np.maximum(zt.min(1), 1e-6)


def tri_aniso(PV, cam, P, uv, tris, ts, W, H) -> np.ndarray:
    """Per triangle, s1/s2 of its screen -> texel affine map at the pose (the review's streak measure, per face)."""
    mvp = PV.perspective(cam["fov"], W / H, 2.0, 1e6) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
    h = np.concatenate([P.astype(np.float64), np.ones((len(P), 1))], 1) @ mvp.T
    wv = np.where(np.abs(h[:, 3]) < 1e-9, 1e-9, h[:, 3])
    s = np.stack([h[:, 0] / wv * W / 2, h[:, 1] / wv * H / 2], 1)
    t = uv.astype(np.float64) * np.asarray(ts, np.float64)
    S0 = np.stack([s[tris[:, 1]] - s[tris[:, 0]], s[tris[:, 2]] - s[tris[:, 0]]], 2)    # 2x2 columns
    T0 = np.stack([t[tris[:, 1]] - t[tris[:, 0]], t[tris[:, 2]] - t[tris[:, 0]]], 2)
    det = S0[:, 0, 0] * S0[:, 1, 1] - S0[:, 0, 1] * S0[:, 1, 0]
    ok = np.abs(det) > 1e-9
    inv = np.zeros_like(S0)
    inv[:, 0, 0], inv[:, 1, 1] = S0[:, 1, 1], S0[:, 0, 0]
    inv[:, 0, 1], inv[:, 1, 0] = -S0[:, 0, 1], -S0[:, 1, 0]
    inv /= np.where(ok, det, 1.0)[:, None, None]
    M = T0 @ inv
    sv = np.linalg.svd(M, compute_uv=False)
    a = sv[:, 0] / np.maximum(sv[:, 1], 1e-9)
    a[~ok] = np.inf
    # all three vertices on one texel (a relief side wall extruded from one silhouette texel): one colour smeared
    # over the whole face - the worst curtain, although its footprint has no direction
    a[sv[:, 0] < 1e-4] = np.inf
    a[h[tris, 3].min(1) <= 0] = 0.0
    return a


class Renderer:
    def __init__(self, sc, PV, T, BR, items, W, H):
        import moderngl
        self.mg, self.PV, self.T, self.W, self.H = moderngl, PV, T, W, H
        self.R = PV.Renderer(sc.rig, sc.sun, W, H)
        self.ctx = self.R.ctx
        self.idp = self.ctx.program(vertex_shader=ID_VS, fragment_shader=ID_FS)
        self.fbo = self.ctx.framebuffer(color_attachments=[self.ctx.renderbuffer((W, H), 4, dtype="i4")],
                                        depth_attachment=self.ctx.depth_renderbuffer((W, H)))
        self.ids = []
        for i, it in enumerate(items):
            self.R.add(it["name"], it["P"], it["n"], it["uv"], it["tris"], it["img"], unlit=it["unlit"])
            if it["unlit"] or not len(it["tris"]):
                continue
            vbo = self.ctx.buffer(np.asarray(it["P"], np.float32).tobytes())
            ibo = self.ctx.buffer(np.asarray(it["tris"], np.int32).tobytes())
            self.ids.append((i, self.ctx.vertex_array(self.idp, [(vbo, "3f", "in_pos")], ibo)))

    def render(self, cam):
        far = self.T.DOME_R * 1.2
        lit = self.R.render(cam, near=2.0, far=far)
        mvp = self.PV.perspective(cam["fov"], self.W / self.H, 2.0, far) @ self.PV.view(cam["pos"], cam["fwd"],
                                                                                         cam["up"], cam["right"])
        self.fbo.use()
        self.fbo.clear(-1, -1, -1, -1, depth=1.0)
        self.ctx.enable(self.mg.DEPTH_TEST)
        self.ctx.disable(self.mg.CULL_FACE)
        self.idp["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for i, vao in self.ids:
            self.idp["item"].value = i
            vao.render()
        a = np.frombuffer(self.fbo.read(components=4, dtype="i4"), np.int32).reshape(self.H, self.W, 4)[::-1]
        return lit, a[..., 0].copy(), a[..., 1].copy()

    def release(self):
        self.ctx.release()


# ------------------------------------------------------------------------------------------------ bin rewriting
def orig_dir(S) -> Path:
    return S.WORK / "snip" / "orig"


def orig_bin(S, key: str) -> Path:
    return orig_dir(S) / f"{key}.bytes"


def fade_texture(img: np.ndarray, sigma: float) -> np.ndarray:
    import cv2
    return cv2.GaussianBlur(img, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)


def apply_resolved(S, resolved: dict) -> dict:
    """Rewrite every touched bin from its original (kept in work/snip/orig/, made once) with the resolved actions."""
    stage = S.STAGE
    rows_path = stage / "rows.json"
    od = orig_dir(S)
    if not (od / "rows.json").is_file():
        od.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rows_path, od / "rows.json")
    rows = json.loads((od / "rows.json").read_text(encoding="utf-8"))
    # restore everything this pass ever touched, then re-apply (idempotent; never compounds)
    for ob in sorted(od.rglob("*.bytes")):
        rel = ob.relative_to(od)
        shutil.copy2(ob, stage / rel)
    for fb in sorted(stage.glob("*/*_SnipFade*")):
        fb.unlink()
    rep = {}
    for key, acts in sorted(resolved.items()):
        prefab, name = key.split("/", 1)
        src = stage / prefab / f"{name}.bytes"
        ob = orig_bin(S, key)
        if not ob.is_file():
            ob.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, ob)
        v, n, uv, subs = S.read_bin(ob)
        if len(subs) != 1:
            raise SystemExit(f"snip: {key} has {len(subs)} submeshes (one expected)")
        tris = subs[0].reshape(-1, 3).astype(np.int64)
        rm = np.asarray(acts.get("remove", []), np.int64)
        cl = np.asarray(acts.get("clamp", []), np.int64)
        fd = np.asarray(acts.get("fade", []), np.int64)
        allsel = np.concatenate([rm, cl, fd])
        if len(allsel) and (allsel.max() >= len(tris) or len(np.unique(allsel)) != len(allsel)):
            raise SystemExit(f"snip: {key} selection out of range or overlapping actions")
        keep = np.ones(len(tris), bool)
        keep[allsel] = False
        V, N, UV, TT = [v], [n], [uv], [tris[keep]]
        if len(cl):
            # duplicated vertices moved along their own rest rays (prefab-local: the rest camera at the origin, +z
            # forward), each to at most CLAMP_RATIO x the nearest depth of the clamped triangles it belongs to
            ct = tris[cl]
            u, inv = np.unique(ct.ravel(), return_inverse=True)
            z = v[u, 2].astype(np.float64)
            tz = z[inv.reshape(-1, 3)].min(1)
            zlim = np.full(len(u), np.inf)
            np.minimum.at(zlim, inv.reshape(-1, 3).ravel(), np.repeat(tz, 3) * CLAMP_RATIO)
            k = np.minimum(1.0, zlim / np.maximum(z, 1e-9))
            V.append((v[u] * k[:, None]).astype(np.float32)); N.append(n[u]); UV.append(uv[u])
            TT.append(inv.reshape(-1, 3) + len(v))
        nv, nn, nuv = np.concatenate(V), np.concatenate(N), np.concatenate(UV)
        S_write(src, nv, nn, nuv, np.concatenate(TT))
        if len(fd):
            ft = tris[fd]
            u, inv = np.unique(ft.ravel(), return_inverse=True)
            fname = f"{name}_SnipFade"          # keeps the piece's prefix, so it stays in its review group
            S_write(stage / prefab / f"{fname}.bytes", v[u], n[u], uv[u], inv.reshape(-1, 3))
            img = np.asarray(Image.open(stage / prefab / f"{name}_albedo.png").convert("RGB"))
            Image.fromarray(fade_texture(img, FADE_SIGMA)).save(stage / prefab / f"{fname}_albedo.png")
            base = next(b for b in rows[prefab]["bins"] if b["name"] == name)
            row = dict(base)
            row.update({"name": fname, "mesh": base["mesh"].replace(f"/{name}.bytes", f"/{fname}.bytes"),
                        "texture": base["texture"].replace(f"/{name}_albedo.png", f"/{fname}_albedo.png")})
            rows[prefab]["bins"] = sorted([b for b in rows[prefab]["bins"] if b["name"] != fname] + [row],
                                          key=lambda b: b["name"])
        rep[key] = {"tris": int(len(tris)), "remove": int(len(rm)), "clamp": int(len(cl)), "fade": int(len(fd))}
    rows_path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rep


def S_write(path: Path, v, n, uv, tris) -> None:
    import town_full3d_ldi as L
    L.write_bin(path, v, n, uv, tris)


# ------------------------------------------------------------------------------------------------ commands
def cmd_render(a) -> int:
    SC, S, BR, PV, T = _mods()
    W, H = SC.W, SC.H
    sc = S.Scene()
    cams = cams_of(sc, S)
    poses = [p for p in (a.pose.split(",") if a.pose else ("rest",) + REACHABLE)]
    items = load_items(sc, S, BR, S.STAGE)
    rr = Renderer(sc, PV, T, BR, items, W, H)
    out = S.WORK / "snip" / f"round_{a.round}"
    out.mkdir(parents=True, exist_ok=True)
    stats = {}
    for p in poses:
        cam = cams[p]
        lit, iid, tid = rr.render(cam)
        Image.fromarray(lit).save(out / f"{p}.png")
        g = Image.fromarray(lit).copy()
        d = ImageDraw.Draw(g)
        for x in range(0, W, 100):
            d.line((x, 0, x, H), fill=(0, 255, 255) if x % 500 == 0 else (255, 255, 255), width=1)
            d.text((x + 2, 2), str(x), fill=(255, 255, 0))
        for y in range(0, H, 100):
            d.line((0, y, W, y), fill=(0, 255, 255) if y % 500 == 0 else (255, 255, 255), width=1)
            d.text((2, y + 2), str(y), fill=(255, 255, 0))
        g.save(out / f"{p}_grid.png")
        an = np.zeros((H, W), np.float32)
        for i, it in enumerate(items):
            if it["unlit"]:
                continue
            m = iid == i
            if not m.any():
                continue
            ta = tri_aniso(PV, cam, it["P"], it["uv"], it["tris"], (it["img"].shape[1], it["img"].shape[0]), W, H)
            an[m] = ta[tid[m]]
        red = lit.copy()
        red[an >= BR.STREAK_ANISO] = (0.5 * red[an >= BR.STREAK_ANISO] + [127, 0, 0]).astype(np.uint8)
        Image.fromarray(red).save(out / f"{p}_streak.png")
        stats[p] = {"streakPx": int((an >= BR.STREAK_ANISO).sum()), "skyPx": int((iid < 0).sum())}
    rr.release()
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), **stats}))
    return 0


def cmd_select(a) -> int:
    SC, S, BR, PV, T = _mods()
    W, H = SC.W, SC.H
    sel_path = Path(a.selection)
    sel = json.loads(sel_path.read_text(encoding="utf-8"))
    if sel.get("schema") != "town_full3d_snip.v1":
        raise SystemExit("snip: selection schema is not town_full3d_snip.v1")
    sc = S.Scene()
    cams = cams_of(sc, S)
    resolved: dict = {}
    per_rule = []
    rounds = sorted({r["round"] for r in sel["rules"]})
    for rnd in rounds:
        apply_resolved(S, resolved)                # the state the rounds before this one leave
        items = load_items(sc, S, BR, S.STAGE)
        # map the staged (possibly snipped) triangle order back to the original bins' triangle ids
        idmap = {}
        for it in items:
            idmap[it["key"]] = original_ids(S, it, resolved.get(it["key"], {}))
        rr = Renderer(sc, PV, T, BR, items, W, H)
        _l, riid, rtid = rr.render(cams["rest"])
        shots = {}
        for rule in [r for r in sel["rules"] if r["round"] == rnd]:
            p = rule["pose"]
            if p not in shots:
                shots[p] = rr.render(cams[p])
            _lit, iid, tid = shots[p]
            reg = np.zeros((H, W), bool)
            if rule["region"] == "all":
                reg[:] = True
            else:
                x0, y0, x1, y1 = (int(c) for c in rule["region"])
                reg[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = True
            took = 0
            for i, it in enumerate(items):
                if it["unlit"] or it["group"] not in rule.get("groups", GROUPS) or it["name"].endswith("_SnipFade"):
                    continue
                m = reg & (iid == i)
                if not m.any():
                    continue
                cand = np.unique(tid[m])
                ta = tri_aniso(PV, cams[p], it["P"], it["uv"], it["tris"][cand],
                               (it["img"].shape[1], it["img"].shape[0]), W, H)
                rr_ = rest_ratio(sc, it["P"], it["tris"][cand])
                rpx = np.bincount(rtid[riid == i], minlength=len(it["tris"]))[cand]
                ok = ((ta >= rule.get("minAniso", 0.0)) & (rr_ >= rule.get("minRestRatio", 1.0))
                      & (rpx <= rule.get("maxRestPx", MAX_REST_PX))
                      & (rest_cos(sc, it["P"], it["tris"][cand]) <= rule.get("maxRestCos", 1.0)))
                ids = idmap[it["key"]][cand[ok]]
                ids = ids[ids >= 0]                 # clamped duplicates are not re-selected
                if not len(ids):
                    continue
                acts = resolved.setdefault(it["key"], {})
                done = set().union(*[set(v) for v in acts.values()]) if acts else set()
                new = sorted(set(int(x) for x in ids) - done)
                acts.setdefault(rule["action"], [])
                acts[rule["action"]] = sorted(set(acts[rule["action"]]) | set(new))
                took += len(new)
            per_rule.append({"id": rule["id"], "round": rnd, "pose": p, "tris": took})
            print(rule["id"], p, took, flush=True)
        rr.release()
    rep = apply_resolved(S, resolved)
    sel["resolved"] = {k: {a_: v for a_, v in acts.items() if v} for k, acts in sorted(resolved.items())}
    sel["resolvedPerRule"] = per_rule
    sel["resolvedTotals"] = rep
    sel_path.write_text(json.dumps(sel, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


def original_ids(S, it, acts) -> np.ndarray:
    """Staged triangle index -> original bin triangle id (-1 for clamped duplicates)."""
    ob = orig_bin(S, it["key"])
    n_now = len(it["tris"])
    if not ob.is_file() or not acts:
        return np.arange(n_now)
    _v, _n, _uv, subs = S.read_bin(ob)
    n0 = len(subs[0]) // 3 if subs[0].ndim == 1 else len(subs[0])
    gone = np.zeros(n0, bool)
    for k in ("remove", "clamp", "fade"):
        gone[np.asarray(acts.get(k, []), np.int64)] = True
    kept = np.nonzero(~gone)[0]
    out = np.full(n_now, -1, np.int64)
    out[:len(kept)] = kept
    return out


def cmd_apply(a) -> int:
    SC, S, BR, PV, T = _mods()
    sel = json.loads(Path(a.selection).read_text(encoding="utf-8"))
    if sel.get("schema") != "town_full3d_snip.v1" or "resolved" not in sel:
        raise SystemExit("snip apply: selection is not a resolved town_full3d_snip.v1 file (run select)")
    rep = apply_resolved(S, sel["resolved"])
    print(json.dumps(rep, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["render", "select", "apply"])
    ap.add_argument("--faction", required=True)
    ap.add_argument("--round", default="0")
    ap.add_argument("--pose", default="")
    ap.add_argument("--selection", default="")
    a = ap.parse_args()
    _SC, S, *_ = _mods()
    if not S.CANDIDATE:
        raise SystemExit("snip: set TOWN_FULL3D_CANDIDATE (the shipped outputs are never rewritten)")
    return {"render": cmd_render, "select": cmd_select, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
