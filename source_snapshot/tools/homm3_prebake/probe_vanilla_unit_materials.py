#!/usr/bin/env python3
"""Static study of how vanilla Olden Era units author base colour and materials for Hex/Lit.

    python tools/homm3_prebake/probe_vanilla_unit_materials.py extract [--units humans:esquire ...]
    python tools/homm3_prebake/probe_vanilla_unit_materials.py analyze [--ours h3_angel h3_pikeman ...]
    python tools/homm3_prebake/probe_vanilla_unit_materials.py sheet

``extract`` reads the installed Golden Era ``resources.assets`` lazily through UnityPy (one prefab at a time; the
ResourceManager container from tools/homm3_vfx/vanilla_vfx_probe.py) and writes, under the scratch folder
(V:/olden_port_work/vanilla_material_study/, never the repo): every body renderer's material (shader, keywords, all
saved float / colour / texture properties), the decoded body textures as PNG, and each body mesh (positions,
normals, UV0, vertex colours, triangles) as .npz. ``analyze`` measures the base colours of the vanilla sample and of
our delivered units (castle_slice_v1 ``inputs/basecolor.png`` + ``inputs/look_delivered.glb``) with the same code:
L*/chroma percentiles, local contrast, and per-vertex correlations of texture luminance with height, up-facing
normal and a mesh concavity proxy (crevices), plus texel density per unit height. ``sheet`` renders a contact sheet
(albedo only, and albedo under the sand-arena Hex/Lit formula: flat ambient + one directional sun, no shadow).

Proof tier: static read of installed serialized assets + generated-artifact measurements. Nothing here is in-game.
CPU only by design: the caller forbade GPU work while a Unity bundle build runs; the arrays are tiny (<100k verts).
Peak RAM is about 1 GB (UnityPy keeps resources.assets lazily; textures are decoded one at a time).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path("V:/olden_port_work/vanilla_material_study")
DELIVERY = ROOT / "artifacts/homm3_def_retarget_delivery/castle_slice_v1"
LOOK_ART = ROOT / "artifacts/homm3_unit_look"

# faction:unit (base tier, ResourceManager key units/<faction>/1prefabs/<unit>). Mix of size, armour, fur, magic.
SAMPLE = [
    "humans:esquire", "humans:crossbowman", "humans:sunlight_cavalry", "humans:griffin", "humans:angel",
    "humans:lightweaver", "undead:skeleton", "undead:lich", "undead:vampire", "neutral:ghoul",
    "nature:ent", "nature:phoenix", "nature:twinkle", "nature:druid", "dungeon:troglodyte", "dungeon:hydra",
    "dungeon:black_dragon", "dungeon:minos", "demons:lava_larva", "demons:scorpion", "demons:trick_demon",
    "neutral:gorilla", "neutral:goblin_rogue", "neutral:titan", "neutral:animated_armor", "neutral:unicorn",
    "unfrozen:unfrozen_cultist", "neutral:peasant",
]
OURS = ["h3_angel", "h3_pikeman", "h3_battle_griffin", "h3_cavalier"]

# Sand arena (artifacts/homm3_prebaked_lighting/game_lighting_probe.json; docs/homm3_prebaked_lighting.md)
SUN_DIR = np.array([0.624, -0.4035, 0.6692])          # travel direction
SUN_COL = np.array([1.0, 0.957, 0.839])
AMBIENT = np.array([0.6235, 0.6784, 0.7922])
YAW: dict[str, float] = {}           # per-unit render yaw overrides (degrees) for the contact sheet


# ------------------------------------------------------------------ colour helpers
def srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def srgb_to_lab(rgb):
    lin = srgb_to_lin(rgb)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    return np.stack([L, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def box_blur(img, r):
    """Separable box blur x3 (~gaussian sigma ~ r*0.8) on a 2D array, CPU (tiny images)."""
    out = img.astype(np.float64)
    for _ in range(3):
        for ax in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[ax] = (r, r)
            p = np.pad(out, pad, mode="edge")
            cs = np.cumsum(p, axis=ax)
            cs = np.concatenate([np.zeros_like(np.take(cs, [0], axis=ax)), cs], axis=ax)
            n = out.shape[ax]
            out = (np.take(cs, np.arange(2 * r + 1, 2 * r + 1 + n), axis=ax)
                   - np.take(cs, np.arange(0, n), axis=ax)) / (2 * r + 1)
    return out


# ------------------------------------------------------------------ extract (UnityPy, static)
def _probe():
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    import vanilla_vfx_probe as probe  # noqa: E402
    return probe


def _material_full(probe, mref):
    tt = mref.read_typetree()
    sh = probe.deref(tt.get("m_Shader"))
    shader = None
    if sh is not None:
        st = sh.read_typetree()
        shader = st.get("m_ParsedForm", {}).get("m_Name") or st.get("m_Name")
    props = tt.get("m_SavedProperties", {})
    texs = {}
    for name, te in props.get("m_TexEnvs", []):
        t = probe.deref(te.get("m_Texture"))
        texs[name] = None if t is None else {"pid": t.path_id, "scale": [te["m_Scale"]["x"], te["m_Scale"]["y"]],
                                            "offset": [te["m_Offset"]["x"], te["m_Offset"]["y"]]}
    return {"name": tt.get("m_Name"), "pid": mref.path_id, "shader": shader,
            "keywords": tt.get("m_ValidKeywords") or tt.get("m_ShaderKeywords"),
            "invalidKeywords": tt.get("m_InvalidKeywords"), "renderQueue": tt.get("m_CustomRenderQueue"),
            "textures": texs, "floats": {k: round(float(v), 4) for k, v in props.get("m_Floats", [])},
            "colors": {k: [round(float(v[c]), 4) for c in "rgba"] for k, v in props.get("m_Colors", [])}}


def _save_texture(probe, pid, out_dir: Path):
    r = probe.resources_file().objects.get(pid)
    if r is None:
        return None
    tex = r.read()
    png = out_dir / f"tex_{pid}.png"
    info = {"name": tex.m_Name, "pid": pid, "w": tex.m_Width, "h": tex.m_Height,
            "format": str(getattr(tex, "m_TextureFormat", "")), "mips": getattr(tex, "m_MipCount", None),
            "png": png.name}
    if not png.exists():
        img = tex.image
        img.save(png)
        del img
    return info


def _save_mesh(probe, mref, out_dir: Path):
    from UnityPy.helpers.MeshHelper import MeshHandler
    npz = out_dir / f"mesh_{mref.path_id}.npz"
    mesh = mref.read()
    info = {"name": mesh.m_Name, "pid": mref.path_id, "npz": npz.name}
    h = MeshHandler(mesh)
    h.process()
    V = np.asarray(h.m_Vertices, np.float32).reshape(-1, 3)
    N = np.asarray(h.m_Normals or [], np.float32).reshape(-1, 3)
    UV = np.asarray(h.m_UV0 or [], np.float32).reshape(-1, 2)
    C = np.asarray(h.m_Colors or [], np.float32)
    subs = h.get_triangles()
    T = [np.asarray(s, np.int64).reshape(-1, 3) for s in subs]
    info.update({"vertices": int(len(V)), "triangles": [int(len(t)) for t in T], "submeshes": len(T),
                 "hasUV0": bool(len(UV)), "hasUV1": bool(h.m_UV1), "hasColors": bool(len(C)),
                 "boundsMin": V.min(0).round(4).tolist(), "boundsMax": V.max(0).round(4).tolist()})
    if len(C):
        C = C.reshape(len(V), -1)
        info["colorsStats"] = {"min": C.min(0).round(3).tolist(), "max": C.max(0).round(3).tolist(),
                               "mean": C.mean(0).round(3).tolist()}
    np.savez_compressed(npz, V=V, N=N, UV=UV, C=C, **{f"T{i}": t for i, t in enumerate(T)})
    return info


def extract(units: list[str]) -> None:
    probe = _probe()
    _, cont = probe.env()
    out_root = SCRATCH / "vanilla"
    out_root.mkdir(parents=True, exist_ok=True)
    for u in units:
        fac, name = u.split(":")
        key = f"units/{fac}/1prefabs/{name}"
        d = out_root / name
        d.mkdir(exist_ok=True)
        ptr = probe.lookup(cont, key)[0]
        root = probe.resources_file().objects[ptr["m_PathID"]]
        renderers, mats = [], {}

        def walk(go_r, path):
            go = go_r.read_typetree()
            nm = go.get("m_Name")
            p = f"{path}/{nm}" if path else nm
            tr = None
            for c in go.get("m_Component", []):
                cr = probe.deref(c["component"])
                if cr is None:
                    continue
                tn = cr.type.name
                if tn == "Transform":
                    tr = cr.read_typetree()
                elif tn in ("SkinnedMeshRenderer", "MeshRenderer"):
                    tt = cr.read_typetree()
                    mesh_ref = probe.deref(tt.get("m_Mesh")) if tn == "SkinnedMeshRenderer" else None
                    if tn == "MeshRenderer":
                        for c2 in go.get("m_Component", []):
                            r2 = probe.deref(c2["component"])
                            if r2 is not None and r2.type.name == "MeshFilter":
                                mesh_ref = probe.deref(r2.read_typetree().get("m_Mesh"))
                    mids = []
                    for m in tt.get("m_Materials", []):
                        mr = probe.deref(m)
                        if mr is None:
                            mids.append(None)
                            continue
                        if mr.path_id not in mats:
                            mats[mr.path_id] = _material_full(probe, mr)
                        mids.append(mr.path_id)
                    renderers.append({"path": p, "type": tn, "active": bool(go.get("m_IsActive")),
                                      "enabled": tt.get("m_Enabled"), "materials": mids,
                                      "meshRef": mesh_ref.path_id if mesh_ref is not None else None,
                                      "_mesh": mesh_ref})
            if tr is not None:
                for ch in tr.get("m_Children", []):
                    t2 = probe.deref(ch)
                    if t2 is not None:
                        g2 = probe.deref(t2.read_typetree()["m_GameObject"])
                        if g2 is not None:
                            walk(g2, p)

        walk(root, "")
        textures, meshes = {}, {}
        for m in mats.values():
            if not (m["shader"] or "").startswith("Hex/"):
                continue
            for slot, t in m["textures"].items():
                if t and t["pid"] not in textures:
                    textures[t["pid"]] = _save_texture(probe, t["pid"], d)
                    t["name"] = textures[t["pid"]]["name"] if textures[t["pid"]] else None
        for r in renderers:
            mr = r.pop("_mesh")
            hex_body = any((mats.get(i) or {}).get("shader", "") and mats[i]["shader"].startswith("Hex/")
                           for i in r["materials"] if i)
            if mr is not None and hex_body and mr.path_id not in meshes:
                meshes[mr.path_id] = _save_mesh(probe, mr, d)
        rec = {"unit": u, "key": key, "proof": "static read of installed resources.assets (UnityPy)",
               "renderers": renderers, "materials": {str(k): v for k, v in mats.items()},
               "textures": {str(k): v for k, v in textures.items()}, "meshes": {str(k): v for k, v in meshes.items()}}
        (d / "unit.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        hexm = [m for m in mats.values() if (m["shader"] or "").startswith("Hex/")]
        print(f"{u}: {len(renderers)} renderers, {len(hexm)} Hex mats {[m['shader'] for m in hexm]}, "
              f"{len(textures)} tex, {len(meshes)} meshes", flush=True)


# ------------------------------------------------------------------ analysis
def _ours_inputs(unit: str):
    d = DELIVERY / unit / "inputs"
    from_glb = d / "look_delivered.glb"
    tex = d / "basecolor.png"
    if not tex.exists():
        alt = LOOK_ART / unit / "basecolor.png"
        tex = alt if alt.exists() else tex
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    from glb_io import Glb  # noqa: E402
    g = Glb(from_glb)
    Vs, Ns, UVs, Ts, off = [], [], [], [], 0
    for mesh in g.json["meshes"]:
        for prim in mesh["primitives"]:
            at = prim["attributes"]
            V = g.accessor(at["POSITION"]).astype(np.float32)
            Vs.append(V)
            Ns.append(g.accessor(at["NORMAL"]).astype(np.float32) if "NORMAL" in at else np.zeros_like(V))
            UVs.append(g.accessor(at["TEXCOORD_0"]).astype(np.float32))
            Ts.append(g.accessor(prim["indices"]).astype(np.int64).reshape(-1, 3) + off)
            off += len(V)
    V, N, UV, T = np.concatenate(Vs), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Ts)
    UV = UV.copy()
    UV[:, 1] = 1 - UV[:, 1]          # glTF uv origin top-left -> Unity bottom-left convention used below
    return {"V": V, "N": N, "UV": UV, "T": T, "tex": tex, "glb": from_glb, "up": 1}


def _vanilla_inputs(name: str):
    d = SCRATCH / "vanilla" / name
    rec = json.loads((d / "unit.json").read_text(encoding="utf-8"))
    # Body = the (mesh, _MainTex) pair with the most triangles. Material slot i draws submesh i. Only that one
    # mesh is measured: weapons/props are separate meshes, often in their own bind space.
    pairs: dict[tuple, list[int]] = {}
    for r in rec["renderers"]:
        if not r["meshRef"] or str(r["meshRef"]) not in rec["meshes"]:
            continue
        for si, mid in enumerate(r["materials"]):
            m = rec["materials"].get(str(mid)) if mid else None
            if not m or not (m["shader"] or "").startswith("Hex/") or not (m["textures"].get("_MainTex")):
                continue
            tris = rec["meshes"][str(r["meshRef"])]["triangles"]
            if si < len(tris):
                pairs.setdefault((r["meshRef"], m["textures"]["_MainTex"]["pid"]), []).append(si)
    if not pairs:
        return None
    def ntri(k):
        tris = rec["meshes"][str(k[0])]["triangles"]
        return sum(tris[i] for i in set(pairs[k]))
    mref, tpid = max(pairs, key=ntri)
    z = np.load(d / rec["meshes"][str(mref)]["npz"])
    V = z["V"]
    Vs = [V]
    Ns = [z["N"] if len(z["N"]) == len(V) else np.zeros_like(V)]
    UVs = [z["UV"] if len(z["UV"]) == len(V) else np.zeros((len(V), 2), np.float32)]
    Ts = [z[f"T{i}"] for i in sorted(set(pairs[(mref, tpid)]))]
    V, N, UV, T = np.concatenate(Vs), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Ts)
    # Vanilla meshes are stored either y-up (Unity/Maya) or z-up (unconverted Blender export, often at 0.01 scale).
    # The feet sit at the origin, so the up axis is the one of y/z whose minimum is nearest 0 relative to extent.
    lo, ext = V.min(0), np.ptp(V, 0)
    up = 1 if abs(lo[1]) / ext[1] <= abs(lo[2]) / ext[2] else 2
    if up == 2:                       # z-up -> y-up (x, z, -y), same for normals
        V = np.stack([V[:, 0], V[:, 2], -V[:, 1]], 1)
        N = np.stack([N[:, 0], N[:, 2], -N[:, 1]], 1)
    return {"V": V, "N": N, "UV": UV, "T": T, "tex": d / rec["textures"][str(tpid)]["png"], "rec": rec,
            "texInfo": rec["textures"][str(tpid)], "up": 1, "sourceUp": "y" if up == 1 else "z"}


def _cavity(V, T, N):
    """Concavity proxy per vertex: (mean of 2-ring-smoothed neighbour positions - p) . n / mean edge length.
    Positive = the surface curves away above the normal = crevice. CPU (sparse adjacency, tiny meshes)."""
    import scipy.sparse as sp
    n = len(V)
    # weld by position so UV seams do not cut the adjacency
    key = np.round(V / max(1e-6, float(np.ptp(V, 0).max()) * 1e-4)).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    Tw = inv[T]
    m = inv.max() + 1
    Pw = np.zeros((m, 3))
    np.add.at(Pw, inv, V)
    Pw /= np.bincount(inv, minlength=m)[:, None]
    Nw = np.zeros((m, 3))
    np.add.at(Nw, inv, N)
    Nw /= np.maximum(np.linalg.norm(Nw, axis=1, keepdims=True), 1e-9)
    i = np.concatenate([Tw[:, 0], Tw[:, 1], Tw[:, 2], Tw[:, 1], Tw[:, 2], Tw[:, 0]])
    j = np.concatenate([Tw[:, 1], Tw[:, 2], Tw[:, 0], Tw[:, 0], Tw[:, 1], Tw[:, 2]])
    A = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(m, m)).tocsr()
    A.data[:] = 1
    deg = np.maximum(np.asarray(A.sum(1)).ravel(), 1)
    el = np.linalg.norm(Pw[i] - Pw[j], axis=1).mean()
    out = {}
    P = Pw.copy()
    for steps, nm in ((1, "cav1"), (4, "cav4")):
        Q = Pw.copy()
        for _ in range(steps):
            Q = (A @ Q) / deg[:, None]
        out[nm] = (((Q - Pw) * Nw).sum(1) / (el * steps))[inv]
    del P
    return out


def _sample(img, UV):
    h, w = img.shape[:2]
    u = np.mod(UV[:, 0], 1.0) * (w - 1)
    v = (1 - np.mod(UV[:, 1], 1.0)) * (h - 1)
    return img[np.clip(v.round().astype(int), 0, h - 1), np.clip(u.round().astype(int), 0, w - 1)]


def _uv_mask(T, UV, size):
    m = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(m)
    uv = np.mod(UV, 1.0)
    for t in T:
        pts = [(float(uv[k, 0] * size), float((1 - uv[k, 1]) * size)) for k in t]
        dr.polygon(pts, fill=255)
    return np.asarray(m) > 0


def _corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def measure(inp: dict, up_axis: int | None = None) -> dict:
    img = np.asarray(Image.open(inp["tex"]).convert("RGBA"), np.float64) / 255.0
    H, W = img.shape[:2]
    V, N, UV, T = inp["V"], inp["N"], inp["UV"], inp["T"]
    up = inp.get("up", 1) if up_axis is None else up_axis
    # texture-space stats at 512 over UV-covered texels
    small = np.asarray(Image.fromarray((img * 255).astype(np.uint8)).resize((512, 512), Image.BILINEAR),
                       np.float64) / 255.0
    mask = _uv_mask(T, UV, 512) & (small[..., 3] > 0.5)   # alpha-clipped texels never reach the screen
    lab = srgb_to_lab(small[..., :3])
    L, C = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
    Lm, Cm = L[mask], C[mask]
    mx, mn = small[..., :3].max(-1), small[..., :3].min(-1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)[mask]
    lc = np.abs(L - box_blur(L, 2))[mask].mean()          # ~sigma 1.5 px at 512 -> fine detail contrast
    lc8 = np.abs(L - box_blur(L, 10))[mask].mean()        # mid-frequency (painted shading / form)
    hue = np.arctan2(lab[..., 2], lab[..., 1])[mask][Cm > 5]
    hue_sd = float(np.degrees(np.sqrt(-2 * np.log(max(1e-9, np.hypot(np.cos(hue).mean(), np.sin(hue).mean()))))))\
        if len(hue) else 0.0
    # per-vertex correlations
    Lv = srgb_to_lab(_sample(img[..., :3], UV))[:, 0]
    h = (V[:, up] - V[:, up].min()) / max(1e-9, np.ptp(V[:, up]))
    nup = N[:, up] / np.maximum(np.linalg.norm(N, axis=1), 1e-9)
    cav = _cavity(V, T, N)
    res = {}
    for nm, c in cav.items():
        res[f"r_L_{nm}"] = round(_corr(Lv, -c), 3)       # >0: concave (crevice) texels are darker
    dark = Lv <= np.percentile(Lv, 10)
    crev = cav["cav1"] >= np.percentile(cav["cav1"], 80)
    lift = float((dark & crev).sum() / max(1, dark.sum()) / 0.2)
    # texel density
    tri = V[T]
    a3 = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()
    tuv = UV[T]
    e1, e2 = tuv[:, 1] - tuv[:, 0], tuv[:, 2] - tuv[:, 0]
    auv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum()
    height = float(np.ptp(V[:, up]))
    tpm = float(np.sqrt(W * H * auv / max(a3, 1e-12)))
    res.update({
        "tex": f"{W}x{H}", "uvCoverage": round(float(mask.mean()), 3), "uvAreaSum": round(float(auv), 3),
        "Lp": [round(float(np.percentile(Lm, q)), 1) for q in (5, 25, 50, 75, 95)],
        "Cp": [round(float(np.percentile(Cm, q)), 1) for q in (10, 50, 90)],
        "satMean": round(float(sat.mean()), 3), "localContrast": round(float(lc), 2),
        "midContrast": round(float(lc8), 2), "hueSpreadDeg": round(hue_sd, 1),
        "r_L_height": round(_corr(Lv, h), 3), "r_L_normalUp": round(_corr(Lv, nup), 3),
        "darkInCreviceLift": round(lift, 2),
        "texelsPerUnitHeight": round(tpm * height, 0), "verts": int(len(V)), "tris": int(len(T)),
    })
    return res


def analyze(ours: list[str]) -> None:
    out = {"proof": "static read (vanilla) + generated artifacts (ours); measured on texture/mesh, not in game",
           "method": __doc__.split("\n\n")[1], "vanilla": {}, "ours": {}}
    for u in SAMPLE:
        name = u.split(":")[1]
        if not (SCRATCH / "vanilla" / name / "unit.json").exists():
            continue
        inp = _vanilla_inputs(name)
        if inp is None:
            out["vanilla"][name] = {"error": "no Hex body material with _MainTex"}
            continue
        r = measure(inp)
        r["texture"] = inp["texInfo"]["name"]
        r["sourceUp"] = inp["sourceUp"]
        out["vanilla"][name] = r
        print(name, r, flush=True)
    for u in ours:
        try:
            inp = _ours_inputs(u)
        except Exception as ex:  # noqa: BLE001 - report and continue (study, not a gate)
            out["ours"][u] = {"error": repr(ex)[:200]}
            continue
        r = measure(inp)
        r["texture"] = str(inp["tex"].relative_to(ROOT)).replace("\\", "/")
        out["ours"][u] = r
        print(u, r, flush=True)
    (SCRATCH / "analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", SCRATCH / "analysis.json")


# ------------------------------------------------------------------ contact sheet (CPU rasteriser, small)
def _render(inp: dict, size=256, lit=True, yaw_deg=-30.0, elev_deg=25.0):
    img = np.asarray(Image.open(inp["tex"]).convert("RGB"), np.float64) / 255.0
    V, N, UV, T = inp["V"].astype(np.float64), inp["N"].astype(np.float64), inp["UV"], inp["T"]
    c = (V.max(0) + V.min(0)) / 2
    P = V - c
    ya, el = np.radians(yaw_deg), -np.radians(elev_deg)  # negative: camera above the unit
    Ry = np.array([[np.cos(ya), 0, np.sin(ya)], [0, 1, 0], [-np.sin(ya), 0, np.cos(ya)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(el), -np.sin(el)], [0, np.sin(el), np.cos(el)]])
    R = Rx @ Ry
    Q = P @ R.T
    Nw = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    s = 0.9 * size / max(np.ptp(Q[:, 0]), np.ptp(Q[:, 1]))
    x = Q[:, 0] * s + size / 2
    y = -Q[:, 1] * s + size / 2
    z = Q[:, 2]
    # Sand-arena sun in view space: the camera looks along +z (arena forward), so the sun's travel direction
    # (0.624, -0.40, 0.67) is mostly away from the camera and the camera-facing side gets the key.
    Lv = -SUN_DIR / np.linalg.norm(SUN_DIR)
    ndl = np.clip((Nw @ R.T) @ Lv, 0, 1)
    col = np.zeros((size, size, 3))
    zb = np.full((size, size), np.inf)
    alpha = np.zeros((size, size))
    for t in T:
        xs, ys = x[t], y[t]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(size - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(size - 1, np.ceil(ys.max())))
        if x0 > x1 or y0 > y1:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(d) < 1e-12:
            continue
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * z[t[0]] + w1 * z[t[1]] + w2 * z[t[2]]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (zz < sub)
        if not upd.any():
            continue
        sub[upd] = zz[upd]
        uv = (w0[..., None] * UV[t[0]] + w1[..., None] * UV[t[1]] + w2[..., None] * UV[t[2]])[upd]
        alb = _sample(img, uv)
        if lit:
            nd = (w0 * ndl[t[0]] + w1 * ndl[t[1]] + w2 * ndl[t[2]])[upd]
            lin = srgb_to_lin(alb) * (AMBIENT + SUN_COL * nd[:, None])
            alb = lin_to_srgb(lin)
        col[y0:y1 + 1, x0:x1 + 1][upd] = alb
        alpha[y0:y1 + 1, x0:x1 + 1][upd] = 1
    bg = np.array([0.5, 0.5, 0.5])
    out = col * alpha[..., None] + bg * (1 - alpha[..., None])
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def sheet(names: list[str] | None = None, ours: list[str] | None = None) -> None:
    an = json.loads((SCRATCH / "analysis.json").read_text(encoding="utf-8"))
    names = names or [u.split(":")[1] for u in SAMPLE if u.split(":")[1] in an["vanilla"]
                      and "error" not in an["vanilla"][u.split(":")[1]]]
    ours = ours or [u for u in OURS if u in an["ours"] and "error" not in an["ours"][u]]
    tiles = []
    for nm, kind in [(n, "vanilla") for n in names] + [(o, "ours") for o in ours]:
        inp = _vanilla_inputs(nm) if kind == "vanilla" else _ours_inputs(nm)
        # vanilla meshes are Unity-space; ours are glTF (+z forward). Face the camera roughly the same way.
        yaw = YAW.get(nm, 210.0)
        a = _render(inp, lit=False, yaw_deg=yaw)
        b = _render(inp, lit=True, yaw_deg=yaw)
        t = Image.open(inp["tex"]).convert("RGB").resize((256, 256))
        m = an[kind][nm]
        tile = Image.new("RGB", (768, 300), (30, 30, 30) if kind == "vanilla" else (60, 25, 25))
        tile.paste(t, (0, 0))
        tile.paste(a, (256, 0))
        tile.paste(b, (512, 0))
        dr = ImageDraw.Draw(tile)
        dr.text((4, 258), f"{'VANILLA' if kind == 'vanilla' else 'OURS'} {nm}  {m['tex']}  texel/H {m['texelsPerUnitHeight']:.0f}",
                fill=(255, 255, 255))
        dr.text((4, 272), f"L p5/50/95 {m['Lp'][0]}/{m['Lp'][2]}/{m['Lp'][4]}  C50 {m['Cp'][1]}  lc {m['localContrast']} "
                f"mid {m['midContrast']}  r(L,crev) {m['r_L_cav4']}  r(L,up) {m['r_L_normalUp']}", fill=(220, 220, 220))
        dr.text((4, 286), "texture | albedo only | sand Hex/Lit (ambient+sun, no shadow)", fill=(160, 160, 160))
        tiles.append(tile)
        print("tile", nm, flush=True)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    S = Image.new("RGB", (cols * 768, rows * 300), (0, 0, 0))
    for i, t in enumerate(tiles):
        S.paste(t, ((i % cols) * 768, (i // cols) * 300))
    S.save(SCRATCH / "contact_sheet.png")
    print("wrote", SCRATCH / "contact_sheet.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["extract", "analyze", "sheet"])
    ap.add_argument("--units", nargs="*", help="faction:unit (extract)")
    ap.add_argument("--ours", nargs="*", default=OURS)
    a = ap.parse_args()
    if a.mode == "extract":
        extract(a.units or SAMPLE)
    elif a.mode == "analyze":
        analyze(a.ours)
    else:
        sheet(ours=a.ours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
