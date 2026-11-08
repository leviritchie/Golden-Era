#!/usr/bin/env python3
"""Material and lighting pass for the Conflux 3D town: bake the HoMM3 look into Hex/Lit base colour.

    python tools/homm3_town_scene_meshes/bake_town_materials.py            # all registered meshes
    python tools/homm3_town_scene_meshes/bake_town_materials.py --only tbelhall_4

Why this exists: the installed Hex/Lit reads base colour only (no specular, metallic or normal map;
docs/homm3_prebaked_lighting.md), so gold and copper can only look burnished if the burnish is in the
base colour. Meshy's textures already carry baked lighting (remove_lighting=false), and Hex/Lit lights
them again: double lighting. This pass is explicit about both:

  runtime   = albedo * L(n)                       (L = the Hex/Lit Lit-pass model, see below)
  target    = T( base*L(n)*(1-k*metal) + metal*base*(env(r) + sunSpec) )
  albedo'   = clamp(target / L(n), 0, 1)          => runtime reproduces target wherever unclamped

  * L(n) = trilight ambient(n) + sun * max(0, n.l): the cityHuman2 rig as the game evaluates it
    (linear colour space, lightsUseLinearIntensity: sun = colour.linear * 3.86). The sun DIRECTION is
    the key light fitted to the HoMM3 painting (see fit_key_light), which the town scene must set on its
    directional light; with it, the painting's lit faces and the runtime's lit faces are the same faces.
  * The metal term uses Meshy's own metallic/roughness maps; env(r) is a sky/horizon/ground gradient
    sampled by the reflection vector and sunSpec a normalised Blinn-Phong lobe. Reflection is
    VIEW-DEPENDENT: it is baked for the registered town camera and holds only near that pose (the town
    camera is fixed; the orbit video shows the small-move behaviour).
  * T is a per-building colour transfer fitted on the default-pose screen render against the HoMM3
    sprite's own visible pixels: L* quantile mapping plus L*-banded a*/b* mean/std matching
    (distribution only, so it is robust to the mesh/sprite misregistration).
  * Not modelled: cast shadows, SSAO, the game's post chain (tonemapping was not read), point lights.
    Where target/L exceeds 1 the albedo clamps; the clamped share is reported per mesh.
Proof tier: generated artifact. The Unity preview (replica shader, same L) re-measures the result.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_conflux_town3d_preview as B  # noqa: E402

OUT = B.WORK / "materials"
TEX_RES = 2048
METAL_DIFFUSE_CUT = 0.8
SPEC_STRENGTH = 1.0
# Environment seen by the metal (linear): bright warm sky overhead, pale horizon, dark umber ground. The
# sky/ground split across a dome is what reads as burnished copper in the HoMM3 art.
ENV_SKY = np.array([2.2, 2.0, 1.7])
ENV_HORIZON = np.array([0.70, 0.62, 0.52])
ENV_GROUND = np.array([0.04, 0.03, 0.025])
# Buildings whose sprite colours inside the mesh silhouette are mostly an animated effect (the fountain's
# water jets): no colour transfer, the effect layer supplies that look.
NO_TRANSFER = {"tbeldw_2": "sprite pixels over the basin are the water jets (an effect, not the stone)"}
# Painted ornament the Meshy mesh lost (the portal ring's stars and gold filigree): texels the town camera sees
# take the HoMM3 sprite's own colour, divided by the modelled runtime light like the rest of the bake, blended
# by visibility and facing. View-dependent: exact at the default pose, flat paint on the ring otherwise.
PROJECT_SPRITE = {"tbeldw_5_frame": 1.0}


# ----------------------------------------------------------------------------------------------- GL
VS = """
#version 330
uniform vec3 camPos; uniform vec3 camR; uniform vec3 camU; uniform vec3 camF;
uniform float tanHalf; uniform float aspect; uniform int uvSpace;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv;
out vec3 v_pos; out vec3 v_nrm; out vec2 v_uv;
void main() {
    v_pos = in_pos; v_nrm = in_nrm; v_uv = in_uv;
    if (uvSpace == 1) { gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0); return; }
    vec3 d = in_pos - camPos;
    float z = dot(d, camF);
    float n = 0.05, f = 1000.0;
    gl_Position = vec4(dot(d, camR) / (tanHalf * aspect), dot(d, camU) / tanHalf,
                       z * (f + n) / (f - n) - 2.0 * f * n / (f - n), z);
}
"""
FS = """
#version 330
uniform float meshId;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv;
layout(location=0) out vec4 o_pos; layout(location=1) out vec4 o_nrm; layout(location=2) out vec4 o_uv;
void main() {
    o_pos = vec4(v_pos, meshId); o_nrm = vec4(normalize(v_nrm), 1.0); o_uv = vec4(v_uv, 0.0, 1.0);
}
"""


class GL:
    def __init__(self):
        import moderngl

        self.mgl = moderngl
        self.ctx = moderngl.create_standalone_context()
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)

    def vao(self, mesh: dict):
        ctx = self.ctx
        tri = mesh["faces"].ravel()
        data = np.concatenate([mesh["pos"][tri], mesh["nrm"][tri], mesh["uv"][tri]], 1).astype("f4")
        vbo = ctx.buffer(data.tobytes())
        return ctx.vertex_array(self.prog, [(vbo, "3f 3f 2f", "in_pos", "in_nrm", "in_uv")])

    def render(self, meshes: list[dict], cam: dict, w: int, h: int, uv_space: bool = False) -> dict:
        ctx = self.ctx
        tex = [ctx.texture((w, h), 4, dtype="f4") for _ in range(3)]
        depth = ctx.depth_renderbuffer((w, h))
        fbo = ctx.framebuffer(color_attachments=tex, depth_attachment=depth)
        fbo.use()
        fbo.clear(0, 0, 0, -1, depth=1.0)
        ctx.enable(self.mgl.DEPTH_TEST) if not uv_space else ctx.disable(self.mgl.DEPTH_TEST)
        ctx.disable(self.mgl.CULL_FACE)
        p = self.prog
        p["camPos"].value = tuple(cam["pos"]); p["camR"].value = tuple(cam["right"])
        p["camU"].value = tuple(cam["up"]); p["camF"].value = tuple(cam["fwd"])
        p["tanHalf"].value = math.tan(math.radians(cam["fov"]) / 2); p["aspect"].value = w / h
        p["uvSpace"].value = 1 if uv_space else 0
        for i, m in enumerate(meshes):
            p["meshId"].value = float(m.get("id", i))
            self.vao(m).render()
        out = {}
        for k, t in zip(("pos", "nrm", "uv"), tex):
            a = np.frombuffer(t.read(), "f4").reshape(h, w, 4)
            out[k] = a[::-1] if not uv_space else a  # GL rows are bottom-up; uv space keeps v-up rows
        for t in tex:
            t.release()
        depth.release(); fbo.release()
        return out


# ------------------------------------------------------------------------------------------ helpers
def srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, np.float32), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def rgb2lab(srgb):
    from skimage.color import rgb2lab as f

    return f(np.clip(srgb, 0, 1).reshape(-1, 1, 3)).reshape(-1, 3)


def lab2rgb(lab):
    from skimage.color import lab2rgb as f

    return f(lab.reshape(-1, 1, 3)).reshape(-1, 3)


def ambient(n, rig):
    ny = n[..., 1:2]
    up = np.sqrt(np.clip(ny, 0, 1))
    dn = np.sqrt(np.clip(-ny, 0, 1))
    sky, eq, gr = (np.array(rig[k]) for k in ("ambSky", "ambEq", "ambGround"))
    return np.where(ny >= 0, eq + (sky - eq) * up, eq + (gr - eq) * dn)


def light(n, rig, sun_dir):
    ndl = np.clip(n @ -np.asarray(sun_dir), 0, None)[..., None]
    out = ambient(n, rig) + np.array(rig["sunColor"]) * ndl
    if rig.get("fillColor"):  # second directional light (Hex/Lit sums up to 4; unshadowed)
        out = out + np.array(rig["fillColor"]) * np.clip(n @ -np.asarray(rig["fillDir"]), 0, None)[..., None]
    return out


# Fill light: the key (fitted to the painting) comes from the front-right, so faces turned left/away get only the
# city trilight, whose equator term is ~0.013 - those texels divide by a tiny L and clamp. The fill mirrors the
# key across the camera's vertical plane (front-left), sits FILL_ELEV_DEG above the horizon, is cool (sky-lit
# side) and carries --fill x the sun's mean linear intensity. Camera-relative so the runtime can place it the
# same way on the town camera.
FILL_ELEV_DEG = 20.0
FILL_TINT = np.array([0.85, 0.93, 1.12])


def fill_light(key_dir, cam, frac):
    to_key = -np.asarray(key_dir, np.float64)
    r, f = np.asarray(cam["right"], np.float64), np.asarray(cam["fwd"], np.float64)
    up = np.array([0.0, 1.0, 0.0])
    fh = f - up * (f @ up)
    fh /= np.linalg.norm(fh)
    rh = np.cross(up, fh)
    rh *= np.sign(rh @ r)
    kr, kf = to_key @ rh, to_key @ fh
    h = -kr * rh + kf * fh  # mirror the key's horizontal heading across the camera's vertical plane
    h /= np.linalg.norm(h) + 1e-9
    e = math.radians(FILL_ELEV_DEG)
    to_fill = h * math.cos(e) + up * math.sin(e)
    return to_fill, -to_fill


def env(r):
    ry = r[..., 1:2]
    upper = ENV_HORIZON + (ENV_SKY - ENV_HORIZON) * np.clip(ry, 0, 1) ** 0.6
    lower = ENV_HORIZON + (ENV_GROUND - ENV_HORIZON) * np.clip(-ry * 4, 0, 1)
    return np.where(ry >= 0, upper, lower)


def rolloff(c):
    return np.where(c < 0.8, c, 0.8 + 0.2 * (1 - np.exp(-(c - 0.8) / 0.2)))


def shade(base, metal, rough, n, p, cam_pos, rig, sun_dir):
    """Pre-grade target (linear): runtime diffuse of the Meshy colour + the metal's reflection."""
    L = light(n, rig, sun_dir)
    v = cam_pos - p
    v /= np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9
    l = -np.asarray(sun_dir)
    h = v + l
    h /= np.linalg.norm(h, axis=-1, keepdims=True) + 1e-9
    r = 2 * np.sum(n * v, -1, keepdims=True) * n - v
    s = np.clip(2 / np.maximum(rough, 0.05) ** 4 - 2, 8, 256)[..., None]
    ndh = np.clip(np.sum(n * h, -1, keepdims=True), 0, 1)
    ndl = np.clip(n @ l, 0, None)[..., None]
    spec = np.array(rig["sunColor"]) * (s + 8) / (8 * math.pi) * ndh ** s * ndl * SPEC_STRENGTH
    m = metal[..., None]
    c = base * L * (1 - METAL_DIFFUSE_CUT * m) + m * base * (env(r) + spec)
    return c, L


class Transfer:
    """Per-building colour transfer: L* quantile map + L*-banded chroma gain; hue is preserved (a banded
    a*/b* mean shift turned the mage tower's blue gems purple)."""

    def __init__(self, src_lab: np.ndarray, dst_lab: np.ndarray, bands: int = 6):
        q = np.linspace(0, 100, 101)
        self.qs, self.qd = np.percentile(src_lab[:, 0], q), np.percentile(dst_lab[:, 0], q)
        self.qs = np.maximum.accumulate(self.qs + np.arange(101) * 1e-6)
        lm = self.map_l(src_lab[:, 0])
        edges = np.percentile(dst_lab[:, 0], np.linspace(0, 100, bands + 1))
        self.centers, self.params = [], []
        for i in range(bands):
            s = (lm >= edges[i]) & (lm <= edges[i + 1])
            d = (dst_lab[:, 0] >= edges[i]) & (dst_lab[:, 0] <= edges[i + 1])
            if s.sum() < 20 or d.sum() < 20:
                continue
            cs = np.hypot(src_lab[s, 1], src_lab[s, 2]).mean() + 1e-3
            cd = np.hypot(dst_lab[d, 1], dst_lab[d, 2]).mean()
            self.centers.append((edges[i] + edges[i + 1]) / 2)
            self.params.append([np.clip(cd / cs, 0.6, 1.6)])
        self.centers = np.array(self.centers)
        self.params = np.array(self.params)

    def map_l(self, l):
        return np.interp(l, self.qs, self.qd)

    def __call__(self, lab: np.ndarray) -> np.ndarray:
        out = lab.copy()
        out[:, 0] = self.map_l(lab[:, 0])
        gain = np.interp(out[:, 0], self.centers, self.params[:, 0])
        out[:, 1:] = lab[:, 1:] * gain[:, None]
        return out


class Identity:
    def __call__(self, lab):
        return lab


def load_mesh(spec_row: dict, mesh_dir: Path) -> dict:
    import trimesh

    sc = trimesh.load(str(mesh_dir / "model.glb"), force="scene")
    m = sc.to_geometry() if hasattr(sc, "to_geometry") else sc.dump(concatenate=True)
    v = np.asarray(m.vertices, np.float64).copy()
    nrm = np.asarray(m.vertex_normals, np.float64).copy()
    v[:, 0] *= -1
    nrm[:, 0] *= -1
    R = B.yaw_matrix(spec_row["yaw"])
    if spec_row.get("kneeY") is not None:  # spire surgery (fit_mesh_to_sprite.refine_knee)
        above = v[:, 1] > spec_row["kneeY"]
        v = B.knee_remap(v, spec_row["kneeY"], spec_row["kneeScale"])
        nrm[above, 1] /= spec_row["kneeScale"]
    k = spec_row.get("stretchY", 1.0)
    pos = np.asarray(spec_row["rootPosition"]) + (v * np.array([1.0, k, 1.0]) * spec_row["scale"]) @ R.T
    nw = (nrm * np.array([1.0, 1.0 / k, 1.0])) @ R.T  # normals take the inverse-transpose of the stretch
    nw /= np.linalg.norm(nw, axis=1, keepdims=True) + 1e-9

    def img(name, mode):
        return Image.open(mesh_dir / name).convert(mode).resize((TEX_RES, TEX_RES), Image.LANCZOS)

    return {"name": spec_row["name"], "pos": pos.astype("f4"), "nrm": nw.astype("f4"),
            "uv": np.asarray(m.visual.uv, "f4"), "faces": np.asarray(m.faces, np.int64),
            "base": srgb_to_lin(np.asarray(img("texture_0_base_color.png", "RGB"), np.float32) / 255),
            "metal": np.asarray(img("texture_0_metallic.png", "L"), np.float32) / 255,
            "rough": np.asarray(img("texture_0_roughness.png", "L"), np.float32) / 255}


def sample(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Bilinear sample of a v-up (GL) uv into an image stored top row first (PIL)."""
    h, w = tex.shape[:2]
    mx = (uv[:, 0] * w - 0.5).astype(np.float32)
    my = ((1 - uv[:, 1]) * h - 0.5).astype(np.float32)
    n = len(uv)
    cols = 1024
    pad = (-n) % cols
    mx = np.pad(mx, (0, pad)).reshape(-1, cols)
    my = np.pad(my, (0, pad)).reshape(-1, cols)
    out = cv2.remap(tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out.reshape(-1, *tex.shape[2:])[:n]


def fit_key_light(gl: GL, meshes: list[dict], cam: dict, ref: np.ndarray, targets: dict,
                  city_sun: np.ndarray) -> dict:
    """Sun direction whose Lambert term best explains the painting's shading on the registered meshes."""
    g = gl.render(meshes, cam, B.W // 2, B.H // 2)
    mid = g["pos"][..., 3]
    refs = cv2.resize(ref, (B.W // 2, B.H // 2), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    Y = (srgb_to_lin(refs) @ np.array([0.2126, 0.7152, 0.0722]))
    ns, ys = [], []
    for i, m in enumerate(meshes):
        t = cv2.resize(targets[m["name"]].astype(np.uint8), (B.W // 2, B.H // 2), interpolation=cv2.INTER_NEAREST) > 0
        sel = (mid == i) & t
        if sel.sum() < 50:
            continue
        y = Y[sel]
        ns.append(g["nrm"][sel][:, :3])
        ys.append((y - y.mean()) / (y.std() + 1e-6))  # per building: albedo level differs
    N, Yz = np.concatenate(ns), np.concatenate(ys)

    def corr(d):
        s = np.clip(N @ -d, 0, None)
        return float(np.corrcoef(s, Yz)[0, 1])

    best = (-2, None)
    grid = []
    for el in range(5, 86, 5):
        for az in range(0, 360, 10):
            e, a = math.radians(el), math.radians(az)
            d = -np.array([math.cos(e) * math.sin(a), math.sin(e), math.cos(e) * math.cos(a)])  # travel dir
            c = corr(d)
            grid.append((el, az, c))
            if c > best[0]:
                best = (c, d, el, az)
    # Camera-relative description for the doc.
    d = best[1]
    to_sun = -d
    return {"sunDir": d.tolist(), "elevationDeg": best[2], "azimuthDeg": best[3], "corr": best[0],
            "citySunCorr": corr(np.asarray(city_sun)), "pixels": int(len(Yz)),
            "toSunInCamera": {"right": float(to_sun @ cam["right"]), "up": float(to_sun @ cam["up"]),
                              "towardCamera": float(-(to_sun @ cam["fwd"]))}}


def dilate_fill(img: np.ndarray, cov: np.ndarray, iters: int = 16) -> np.ndarray:
    out = img.copy()
    c = cov.copy()
    k = np.ones((3, 3), np.float32)
    for _ in range(iters):
        s = cv2.filter2D(out * c[..., None], -1, k, borderType=cv2.BORDER_REPLICATE)
        n = cv2.filter2D(c.astype(np.float32), -1, k, borderType=cv2.BORDER_REPLICATE)
        grow = (n > 0) & (c == 0)
        out[grow] = s[grow] / n[grow][:, None]
        c = c | grow
    return out


def hue_clamp(alb: np.ndarray) -> np.ndarray:
    """Albedo above 1 is scaled down by its largest channel, not clipped per channel: a per-channel clip
    bleached the castle's clamped copper towers to grey."""
    alb = np.maximum(alb, 0)
    return alb / np.maximum(alb.max(1, keepdims=True), 1.0)


def project(cam: dict, p: np.ndarray):
    """World points -> town-camera pixels (the fitter's pinhole model)."""
    t = math.tan(math.radians(cam["fov"]) / 2)
    d = p - cam["pos"]
    zc = np.maximum(d @ cam["fwd"], 1e-3)
    px = ((d @ cam["right"]) / (zc * t * (B.W / B.H)) + 1) * 0.5 * B.W
    py = (1 - (d @ cam["up"]) / (zc * t)) * 0.5 * B.H
    return px, py, zc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append")
    ap.add_argument("--fill", type=float, default=0.35, help="fill light as a fraction of the sun's mean intensity (0 = none)")
    a = ap.parse_args()
    spec = json.loads((B.WORK / "preview_spec.json").read_text(encoding="utf-8"))
    cam = B.camera()
    rig = B.city_rig(cam["scene"])
    layers = {l["id"]: l for l in json.loads((B.REFS / "layers" / "positions.json").read_text())["layers"]}
    OUT.mkdir(parents=True, exist_ok=True)
    gl = GL()
    # Every mesh instance of every town state (preview_spec "states"). An instance is baked once, in the state it
    # was emitted in (its first state), against that state's HoMM3 composite; bakeAs instances reuse a texture.
    rows = spec["meshes"]
    first = {r["name"]: (r.get("states") or ["full"])[0] for r in rows}
    meshes = []
    for i, row in enumerate(rows):
        m = load_mesh(row, B.MESHY / row.get("mesh", row["name"]) / B.MESH_ATTEMPT)
        m["id"] = i
        m["bakeAs"] = row.get("bakeAs", row["name"])
        meshes.append(m)
    targets = {}
    for row in rows:
        fl = row.get("fitLayer", row["layer"])
        entry = {"layer": fl, "fitBox": row.get("fitBox")}
        targets[row["name"]] = B.fit_target(layers, entry, B.layer_frame(layers[fl], row.get("span"))) > 0
    refs = {"full": np.asarray(Image.open(B.WORK / "homm3_conflux_reference_1920.png").convert("RGB"))}
    for st in set(first.values()) - {"full"}:
        refs[st] = np.asarray(Image.open(B.WORK / f"homm3_conflux_reference_{st}_1920.png").convert("RGB"))
    ref = refs["full"]
    full_meshes = [m for m in meshes if first[m["name"]] == "full"]
    sm = np.array(next(l for l in cam["scene"]["lights"] if l["type"] == 1)["m"]).reshape(4, 4).T
    city_sun = sm[:3, 2] / np.linalg.norm(sm[:3, 2])
    # The key light is the full town's (the shipped catalog key): lower-level states never refit it.
    key = fit_key_light(gl, full_meshes, cam, ref, targets, city_sun)
    print("key light", json.dumps(key), flush=True)
    sun_dir = np.asarray(key["sunDir"])
    fill = None
    if a.fill > 0:
        to_fill, fill_dir = fill_light(sun_dir, cam, a.fill)
        fill_col = FILL_TINT * float(np.mean(rig["sunColor"])) * a.fill
        rig = dict(rig, fillDir=fill_dir.tolist(), fillColor=fill_col.tolist())
        fill = {"dir": fill_dir.tolist(), "color": fill_col.tolist(), "fraction": a.fill, "elevationDeg": FILL_ELEV_DEG,
                "toLightInCamera": {"right": float(to_fill @ cam["right"]), "up": float(to_fill @ cam["up"]),
                                    "towardCamera": float(-(to_fill @ cam["fwd"]))}}
    print("fill light", json.dumps(fill), flush=True)

    renders = {}

    def state_render(st: str) -> dict:
        if st not in renders:
            renders[st] = gl.render([m for m in meshes if st in (rows[m["id"]].get("states") or ["full"])], cam, B.W, B.H)
        return renders[st]
    report = {"schema": "homm3_conflux_town_material_bake.v1", "rig": rig, "keyLight": key, "fillLight": fill,
              "model": "albedo' = hue_clamp(T(shade(meshy)) / L(n)); L = trilight(n) + sun*max(0,n.l) + fill*max(0,n.lf)",
              "meshes": []}
    for m in meshes:
        if a.only and m["name"] not in a.only:
            continue
        if m["bakeAs"] != m["name"]:
            continue  # same mesh and painted pixels as its owner: shares the owner's texture
        g = state_render(first[m["name"]])
        mid = g["pos"][..., 3]
        ref = refs[first[m["name"]]]
        sel = (mid == m["id"]) & targets[m["name"]]
        uv = g["uv"][sel][:, :2]
        n = g["nrm"][sel][:, :3]
        p = g["pos"][sel][:, :3]
        base = sample(m["base"], uv)
        met = sample(m["metal"], uv)
        rou = sample(m["rough"], uv)
        c_scr, _ = shade(base, met, rou, n, p, cam["pos"], rig, sun_dir)
        src = rgb2lab(lin_to_srgb(rolloff(c_scr)))
        dst = rgb2lab(ref[sel].astype(np.float32) / 255)
        T = Identity() if m["name"] in NO_TRANSFER else Transfer(src, dst)
        # Texture space.
        u = gl.render([m], cam, TEX_RES, TEX_RES, uv_space=True)
        cov = u["nrm"][..., 3] > 0.5
        cov_img = cov[::-1]  # uv rows v-up -> image rows (PIL top-first)
        n_t = u["nrm"][..., :3][::-1][cov_img]
        p_t = u["pos"][..., :3][::-1][cov_img]
        n_t /= np.linalg.norm(n_t, axis=1, keepdims=True) + 1e-9
        c_t, L_t = shade(m["base"][cov_img], m["metal"][cov_img], m["rough"][cov_img], n_t, p_t, cam["pos"], rig, sun_dir)
        tgt_srgb = lab2rgb(T(rgb2lab(lin_to_srgb(rolloff(c_t)))))
        tgt_lin = srgb_to_lin(tgt_srgb)
        alb = tgt_lin / np.maximum(L_t, 1e-4)
        clamped = float((alb > 1.0).any(1).mean())
        alb = hue_clamp(alb)
        proj_share = None
        if m["name"] in PROJECT_SPRITE:
            px, py, zc = project(cam, p_t)
            xi = np.clip(np.round(px).astype(int), 0, B.W - 1)
            yi = np.clip(np.round(py).astype(int), 0, B.H - 1)
            inside = (px >= 0) & (px < B.W) & (py >= 0) & (py < B.H)
            gz = np.linalg.norm(g["pos"][yi, xi, :3] - cam["pos"], axis=1)
            dz = np.linalg.norm(p_t - cam["pos"], axis=1)
            vis = inside & (mid[yi, xi] == m["id"]) & (np.abs(gz - dz) < 0.01 * dz) & targets[m["name"]][yi, xi]
            view = (cam["pos"] - p_t) / (dz[:, None] + 1e-9)
            facing = np.clip(((n_t * view).sum(1) - 0.1) / 0.3, 0, 1)
            w = (vis * facing * PROJECT_SPRITE[m["name"]])[:, None]
            spr = srgb_to_lin(ref[yi, xi].astype(np.float32) / 255) / np.maximum(L_t, 1e-4)
            alb = hue_clamp(w * spr + (1 - w) * alb)
            proj_share = round(float((w[:, 0] > 0.5).mean()), 4)
        out = m["base"].copy()
        out[cov_img] = alb
        out = dilate_fill(out, cov_img)
        Image.fromarray((lin_to_srgb(out) * 255 + 0.5).astype(np.uint8)).save(OUT / f"{m['name']}_hexlit_base.png")
        # Metrics on the screen pixels: before (raw Meshy under the runtime model) and after.
        _, L_s = shade(base, met, rou, n, p, cam["pos"], rig, sun_dir)
        before = rgb2lab(lin_to_srgb(base * L_s))
        raw_alb = srgb_to_lin(lab2rgb(T(src))) / np.maximum(L_s, 1e-4)
        vis_clamped = float((raw_alb > 1.0).any(1).mean())
        after_alb = hue_clamp(raw_alb)
        after = rgb2lab(lin_to_srgb(after_alb * L_s))

        def stats(lab):
            ch = np.hypot(lab[:, 1], lab[:, 2])
            return {"Lp5_50_95": np.percentile(lab[:, 0], [5, 50, 95]).round(1).tolist(),
                    "chromaMean": round(float(ch.mean()), 1),
                    "hueDeg": round(float(np.degrees(np.arctan2(lab[:, 2].mean(), lab[:, 1].mean()))), 1)}

        row = {"name": m["name"], "state": first[m["name"]], "pixels": int(sel.sum()), "clampedTexelShare": round(clamped, 4),
               "clampedVisiblePixelShare": round(vis_clamped, 4),
               "metalTexelShare": round(float((m["metal"][cov_img] > 0.5).mean()), 3),
               "spriteProjectedTexelShare": proj_share,
               "sprite": stats(dst), "rawMeshyUnderRig": stats(before), "baked": stats(after)}
        report["meshes"].append(row)
        print(json.dumps(row), flush=True)
    prev = OUT / "bake_report.json"
    if a.only and prev.is_file():
        old = json.loads(prev.read_text(encoding="utf-8"))
        keep = [r for r in old.get("meshes", []) if r["name"] not in {r2["name"] for r2 in report["meshes"]}]
        report["meshes"] = keep + report["meshes"]
    prev.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
